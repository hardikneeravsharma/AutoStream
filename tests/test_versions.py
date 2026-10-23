"""Render versions (clips/versions.py): a render never replaces the reel until it has finished.

A render used to swap its file in over the reel, so the reel before was gone the
moment a new one landed, a worse render could not be taken back, and the page
had to let go of the video before every render. These pin the version model:
each render is its own file, promoted only on success; the previous one stays
untouched and playable; History can restore any of them or save one as a reel
of its own; and a reel from before versions is migrated on first read.
"""
from __future__ import annotations

import json
from pathlib import Path

from autostream.clips import studio, versions
from test_studio import _built, root  # noqa: F401  (the fixture)


def _reel(tmp_path: Path, name: str = "r", body: bytes = b"one") -> Path:
    reels = tmp_path / "reels"
    reels.mkdir(parents=True, exist_ok=True)
    mp4 = reels / f"{name}.mp4"
    mp4.write_bytes(body)
    mp4.with_suffix(".reel.json").write_text(json.dumps({"name": name, "style": "montage", "shots": [{}]}))
    return mp4


def _swap(tmp: Path, out: Path) -> None:
    tmp.replace(out)


def test_a_reel_from_before_versions_becomes_v1_on_first_read(tmp_path):
    mp4 = _reel(tmp_path)
    rows = versions.listing(mp4)
    assert [r["version"] for r in rows] == [1] and rows[0]["current"]
    assert (versions.folder(mp4) / "v1.mp4").read_bytes() == b"one"
    assert rows[0]["made_from"]["style"] == "montage"
    versions.listing(mp4)
    assert versions.numbers(mp4) == [1], "migrated once, not on every read"


def test_a_new_version_is_promoted_and_the_old_one_is_left_untouched(tmp_path):
    mp4 = _reel(tmp_path)
    n, f = versions.next_file(mp4)
    assert n == 2 and f.parent == versions.folder(mp4)
    assert mp4.read_bytes() == b"one", "the reel is untouched while the render runs"
    f.write_bytes(b"two")
    versions.write_meta(mp4, n, {"name": "r", "render_version": 2})
    versions.promote(mp4, n, _swap)
    assert mp4.read_bytes() == b"two"
    assert (versions.folder(mp4) / "v1.mp4").read_bytes() == b"one", "the version before is still whole"
    assert json.loads(mp4.with_suffix(".reel.json").read_text())["render_version"] == 2
    assert versions.current(mp4) == 2


def test_restore_promotes_an_older_version_again(tmp_path):
    mp4 = _reel(tmp_path)
    n, f = versions.next_file(mp4)
    f.write_bytes(b"two")
    versions.write_meta(mp4, n, {"name": "r", "render_version": 2})
    versions.promote(mp4, n, _swap)
    versions.promote(mp4, 1, _swap)
    assert mp4.read_bytes() == b"one" and versions.current(mp4) == 1
    assert (versions.folder(mp4) / "v2.mp4").read_bytes() == b"two"


def test_save_as_new_reel_makes_a_reel_of_its_own(tmp_path):
    mp4 = _reel(tmp_path)
    versions.listing(mp4)
    new = mp4.with_name("copy.mp4")
    meta = versions.fork(mp4, 1, new, "The copy")
    assert new.read_bytes() == b"one" and meta["name"] == "The copy"
    assert json.loads(new.with_suffix(".reel.json").read_text())["output"] == str(new)
    assert versions.numbers(new) == [1]
    assert mp4.read_bytes() == b"one", "the original is not touched"


def test_old_versions_are_pruned_but_never_the_current_one(tmp_path):
    mp4 = _reel(tmp_path)
    for _ in range(5):
        n, f = versions.next_file(mp4)
        f.write_bytes(b"v%d" % n)
        versions.write_meta(mp4, n, {"render_version": n})
    versions.promote(mp4, 1, _swap)
    versions.prune(mp4, keep=2)
    assert 1 in versions.numbers(mp4), "the reel's own version stays"
    assert versions.numbers(mp4)[-2:] == [5, 6]


def test_deleting_a_reel_takes_its_versions_with_it(root):  # noqa: F811
    mp4 = _reel(root, "gone")
    versions.listing(mp4)
    assert versions.folder(mp4).is_dir()
    studio.delete_reels(root, [str(mp4)])
    assert not mp4.exists() and not versions.folder(mp4).exists()


def test_the_version_folder_and_promotion_files_are_not_reels(root):  # noqa: F811
    mp4 = _reel(root, "keep")
    versions.listing(mp4)
    mp4.with_name("keep.v2.promote.mp4").write_bytes(b"x")
    assert [r["name"] for r in studio.reels(root)] == ["keep"]


def test_a_render_writes_its_version_and_promotes_it_only_once_finished(root, monkeypatch):  # noqa: F811
    from autostream.clips import tools

    monkeypatch.setattr(tools, "binary", lambda name: "ffmpeg")
    monkeypatch.setattr(tools, "media_info", lambda p: {"audio_tracks": 1})
    out = root / "reels" / "x.mp4"
    out.write_bytes(b"before")
    got, derived, _ = _built(root)
    job = studio.StudioJob(got, derived, root, out)
    assert job.version == 2, "the reel already there became v1"
    seen = {}

    def fake_ff(argv, capture=False, seconds=0.0):
        f = Path(argv[-1])
        if f.name.endswith(".part.mp4") and f.parent.parent.name == ".versions":
            seen["reel_during_join"] = out.read_bytes()
        f.write_bytes(b"after")
        return ""
    monkeypatch.setattr(job, "_run_ff", fake_ff)
    monkeypatch.setattr(job, "_retime", lambda seg, o, ff: o)
    monkeypatch.setattr(job, "_loudness", lambda ff, p: None)
    monkeypatch.setattr(job, "_check", lambda ff, intro: [])
    job.run()
    snap = job.snapshot()
    assert snap["state"] == "done", snap
    assert seen["reel_during_join"] == b"before", "the reel was touched before the render finished"
    assert out.read_bytes() == b"after"
    assert (versions.folder(out) / "v1.mp4").read_bytes() == b"before"
    meta = json.loads(out.with_suffix(".reel.json").read_text())
    assert meta["render_version"] == 2 and meta["made_from"]["shots"] == len(got["shots"])
    assert snap["version"] == 2 and snap["version_file"].endswith("v2.mp4")


def test_a_failed_render_leaves_the_reel_and_its_versions_alone(root, monkeypatch):  # noqa: F811
    from autostream.clips import tools

    monkeypatch.setattr(tools, "binary", lambda name: "ffmpeg")
    monkeypatch.setattr(tools, "media_info", lambda p: {"audio_tracks": 1})
    out = root / "reels" / "y.mp4"
    out.write_bytes(b"before")
    got, derived, _ = _built(root)
    job = studio.StudioJob(got, derived, root, out)

    def fake_ff(argv, capture=False, seconds=0.0):
        f = Path(argv[-1])
        if f.name.endswith(".part.mp4") and f.parent.parent.name == ".versions":
            raise RuntimeError("the join broke")
        f.write_bytes(b"x")
        return ""
    monkeypatch.setattr(job, "_run_ff", fake_ff)
    monkeypatch.setattr(job, "_retime", lambda seg, o, ff: o)
    job.run()
    assert job.snapshot()["state"] == "failed"
    assert out.read_bytes() == b"before"
    assert versions.numbers(out) == [1]
    assert not list(versions.folder(out).glob("*.part.mp4"))
