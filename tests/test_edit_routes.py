"""The routes that resolve a reel's timing and its render versions, driven offline.

Render refuses a plan the spec has moved past; re-time and replan answer as dry
runs with what they would change, echoing the revision they were asked about;
History lists, restores and forks render versions. The page half is in
tests/verify/test_ui_studio_timing.py.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from test_instant_preview import _server, root  # noqa: F401  (the fixture)
from test_studio import Shape, _clips

from autostream.clips import studio, versions


@pytest.fixture
def srv(monkeypatch, root):  # noqa: F811
    s = _server()
    monkeypatch.setattr(s, "_clips_dir", lambda c: root, raising=False)
    monkeypatch.setattr("autostream.clips.available", lambda: True)
    monkeypatch.setattr("autostream.clips.runner", lambda: SimpleNamespace(busy=lambda: False))
    shape = Shape(bpm=120.0, seconds=180.0, phase=0.0)
    monkeypatch.setattr(s, "_studio_shape", lambda song: shape if song else None, raising=False)
    s.shape = shape
    return s


@pytest.fixture
def reel(root, tmp_path):  # noqa: F811
    """A planned reel on a song that is on disk, normalised once so its clips' lengths are known."""
    song = tmp_path / "song.wav"
    song.write_bytes(b"RIFF")
    proj, _ = studio.plan(_clips(root), "montage", shape=Shape(bpm=120.0, seconds=180.0, phase=0.0),
                          song=str(song), part=(0.0, 20.0))
    got, _, _ = studio.normalise(proj, root, probe=lambda p: 30.0)
    return got


def test_render_refuses_a_part_the_plan_was_not_made_for(srv, reel, monkeypatch):
    started = []
    monkeypatch.setattr(studio.Runner, "start", lambda self, job, claim=0: started.append(job) or "")
    stale = dict(reel, draft={"start": 59.0, "end": 127.0})
    got = srv.studio_render({"project": stale})
    assert got["ok"] is False and got["error"].startswith("Song part changed")
    assert got["stale"] == ["part"] and started == []
    got = srv.studio_render({"project": reel})
    assert got["ok"] is True and started
    assert got["version"] >= 1 and got["version_file"].endswith(f"v{got['version']}.mp4")


def test_retime_is_a_dry_run_that_answers_for_its_revision(srv, reel):
    stale = dict(reel, draft={"start": 59.0, "end": 127.0})
    got = srv.studio_retime({"project": stale, "rev": 7})
    assert got["ok"] and got["rev"] == 7 and got["conflicts"] == []
    new = got["project"]
    assert "draft" not in new and new["song_offset"] == pytest.approx(59.0)
    assert [s["clip"] for s in new["shots"]] == [s["clip"] for s in reel["shots"]]
    assert got["diff"]["shots"][0] == len(reel["shots"])
    beats = set(round(b, 4) for b in srv.shape.beats)
    assert all(round(m, 4) in beats for m in new["song_marks"]), new["song_marks"]


def test_a_drop_style_with_its_drop_outside_the_part_cannot_be_retimed_or_replanned(srv, reel):
    srv.shape.drop = 30.0
    stale = dict(reel, style="drop", draft={"start": 59.0, "end": 127.0})
    for route in (srv.studio_retime, srv.studio_replan):
        got = route({"project": stale, "rev": 1})
        assert got["ok"] and got["project"] is None
        assert got["conflicts"][0]["kind"] == "drop-outside", route


def test_replan_keeps_the_players_marks_their_effects_and_the_file(srv, reel, root, monkeypatch):  # noqa: F811
    sent = []

    def plan(body):
        sent.append(body)
        p, notes = studio.plan(_clips(root), body["style"], shape=srv.shape, song=body["song"],
                               part=(body["part_start"], body["part_end"]))
        p, d, more = studio.normalise(p, root, probe=lambda _p: 30.0)
        return {"ok": True, "project": p, "derived": d, "notes": notes + more, "song": None}
    monkeypatch.setattr(srv, "studio_plan", plan, raising=False)
    first = reel["shots"][0]
    marked = dict(reel, output=str(root / "reels" / "keep.mp4"), anchors=[61.3],
                  draft={"start": 59.0, "end": 79.0})
    marked["shots"] = [dict(first, fx=["k07"])] + reel["shots"][1:]
    got = srv.studio_replan({"project": marked, "rev": 3})
    assert got["ok"] and got["rev"] == 3, got
    assert sent[0]["part_start"] == 59.0 and sent[0]["part_end"] == 79.0
    new = got["project"]
    assert 61.3 in new["song_marks"] and new["anchors"] == [61.3]
    assert new["output"] == marked["output"]
    same = [s for s in new["shots"] if s["clip"] == first["clip"] and s["kill"] == first["kill"]]
    assert same and same[0]["fx"] == ["k07"] and got["diff"]["effects_kept"] >= 1
    assert not got["derived"]["edited"], "a plan just made is not an edited one"


def test_history_lists_restores_and_forks_render_versions(srv, root):  # noqa: F811
    mp4 = root / "reels" / "hist.mp4"
    mp4.write_bytes(b"one")
    mp4.with_suffix(".reel.json").write_text(json.dumps({"name": "hist", "style": "montage", "shots": []}))
    got = srv.studio_versions(str(mp4))
    assert got["ok"] and [v["version"] for v in got["versions"]] == [1]
    n, f = versions.next_file(mp4)
    f.write_bytes(b"two")
    versions.write_meta(mp4, n, {"name": "hist", "render_version": n, "shots": []})
    versions.promote(mp4, n, studio._swap_in)
    assert [v["version"] for v in srv.studio_versions(str(mp4))["versions"]] == [2, 1]
    got = srv.studio_version({"path": str(mp4), "version": 1, "action": "restore"})
    assert mp4.read_bytes() == b"one" and versions.current(mp4) == 1
    got = srv.studio_version({"path": str(mp4), "version": 2, "action": "fork", "name": "Second take"})
    assert got["ok"] and got["name"] == "Second take"
    from pathlib import Path
    assert Path(got["path"]).read_bytes() == b"two"
    assert mp4.read_bytes() == b"one"
    assert srv.studio_version({"path": str(mp4), "version": 9, "action": "restore"})["ok"] is False
    assert srv.studio_versions("C:/elsewhere/x.mp4")["ok"] is False
