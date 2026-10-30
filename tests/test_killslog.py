"""kills.json: every kill a clip job found, for other tools to read later.

A NEW output beside session.json, not a change to it. session.json is read by
the Studio, the library and the next run's cache, so the side keys that ride
along on kill dicts for kills.json (`seen`, `votes`) must never reach it --
and a kills.json that cannot be written must never cost the run its clips.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

import autostream
from autostream.clips import detect, killslog, plan


# ------------------------------------------------------ source / confidence

def test_a_kill_from_the_match_record_is_certain():
    k = {"time": 1.0, "record": True, "votes": "kdd"}
    assert killslog.source_of(k) == "record"
    assert killslog.confidence(k) == 1.0, "the record outranks the screen's votes"


def test_confidence_is_the_share_of_sightings_that_read_as_a_kill():
    assert killslog.confidence({"time": 1.0, "votes": "kkkok"}) == 0.8
    assert killslog.confidence({"time": 1.0, "votes": "kkkkkkd"}) == 0.857


def test_a_kill_the_ocr_second_look_added_has_no_vote_share():
    """feed_ocr marks its own kills votes="ocr". Read as letters that is
    zero kills out of three -- a reader sure it was not a kill."""
    assert killslog.confidence({"time": 1.0, "votes": "ocr", "seen": 2}) is None


def test_nothing_measured_is_none_not_zero():
    """Kills reused from an older session.json carry no votes; 0.0 would say
    the reader was sure they were wrong."""
    assert killslog.confidence({"time": 1.0}) is None
    assert killslog.confidence({"time": 1.0, "votes": ""}) is None


def test_source_names():
    assert killslog.source_of({"time": 1.0}) == "screen"
    assert killslog.source_of({"time": 1.0, "emblem": True}) == "emblem"
    assert killslog.source_of({"time": 1.0, "record": True, "emblem": True}) == "record"


def test_a_counter_strike_demo_kill_is_a_record():
    """Valve's demo is exact, like Riot's record -- it just cannot say so in
    session.json, so it rides as a side key."""
    k = {"time": 1.0, "round": 4, "demo": True}
    assert killslog.source_of(k) == "record"
    assert killslog.confidence(k) == 1.0


# ------------------------------------------------------------ for_session

def test_for_session_drops_only_the_side_keys_and_leaves_its_input_alone():
    kills = [{"time": 1.0, "end": 2.0, "score": 0.9, "count": 1, "hs": True,
              "round": 3, "seen": 4, "votes": "kkko", "demo": True},
             {"time": 5.0, "end": 5.0, "score": 0.8, "count": 2}]
    before = copy.deepcopy(kills)
    out = killslog.for_session(kills)
    assert out == [{"time": 1.0, "end": 2.0, "score": 0.9, "count": 1,
                    "hs": True, "round": 3},
                   {"time": 5.0, "end": 5.0, "score": 0.8, "count": 2}]
    assert kills == before, "session.json's copy must not strip the kills.json copy"
    assert set(killslog.SIDE_KEYS) == {"seen", "votes", "demo"}


def test_for_session_is_byte_for_byte_what_session_json_had():
    """Same keys in the same order, so json.dumps is identical."""
    old = [{"time": 1.0, "end": 2.0, "score": 0.9, "count": 1, "round": 3,
            "tags": ["smoke"]}]
    new = [dict(old[0], seen=4, votes="kkko", demo=True)]
    assert json.dumps(killslog.for_session(new)) == json.dumps(old)


# ----------------------------------------------------------------- events

EVENT_KEYS = {"kind", "time", "end", "headshot", "round", "source", "confidence",
              "seen", "burst_id", "burst_size"}


def test_every_event_is_a_kill_for_now():
    ev = killslog.events([{"time": 1.0}, {"time": 90.0, "record": True}])
    assert [e["kind"] for e in ev] == ["kill", "kill"]


def test_no_kills_is_no_events():
    assert killslog.events([]) == []


def test_events_are_sorted_rounded_and_never_end_before_they_start():
    kills = [{"time": 30.0, "end": 10.0},                  # end before time
             {"time": 1214.71234, "end": 1215.98765, "votes": "kkkkkkd", "seen": 7},
             {"time": 20.0}]                                # no end at all
    ev = killslog.events(kills)
    assert [e["time"] for e in ev] == [20.0, 30.0, 1214.712]
    assert all(set(e) == EVENT_KEYS for e in ev)
    assert ev[0]["end"] == 20.0
    assert ev[1]["end"] == 30.0
    assert ev[2]["end"] == 1215.988
    assert ev[2]["confidence"] == 0.857 and ev[2]["seen"] == 7
    assert ev[2]["source"] == "screen"
    assert all(e["end"] >= e["time"] for e in ev)


def test_headshot_is_unknown_unless_it_was_read():
    ev = killslog.events([{"time": 1.0, "hs": True}, {"time": 100.0, "hs": False},
                          {"time": 200.0}])
    assert [e["headshot"] for e in ev] == [True, False, None]


def test_round_and_seen_are_none_when_absent_or_zero():
    ev = killslog.events([{"time": 1.0, "round": 7, "seen": 3},
                          {"time": 100.0, "round": 0, "seen": 0},
                          {"time": 200.0}])
    assert [e["round"] for e in ev] == [7, None, None]
    assert [e["seen"] for e in ev] == [3, None, None]
    assert isinstance(ev[0]["round"], int)


def test_bursts_are_the_planners_own():
    """Two kills 5 s apart are one fight; one 60 s later is another."""
    kills = [{"time": 165.0}, {"time": 100.0}, {"time": 105.0}]
    ev = killslog.events(kills)
    assert [e["burst_id"] for e in ev] == [0, 0, 1]
    assert [e["burst_size"] for e in ev] == [2, 2, 1]
    # And it is the same grouping the clips were cut from.
    bursts = plan.cluster(kills)
    assert [b.kills for b in bursts] == [2, 1]


def test_burst_ids_follow_time_order_not_input_order():
    kills = [{"time": 500.0}, {"time": 10.0}, {"time": 501.0}, {"time": 502.0}]
    ev = killslog.events(kills)
    assert [(e["time"], e["burst_id"], e["burst_size"]) for e in ev] == [
        (10.0, 0, 1), (500.0, 1, 3), (501.0, 1, 3), (502.0, 1, 3)]


# ------------------------------------------------------------------ build

DOC_KEYS = {"schema_version", "kind", "status", "source", "duration", "game",
            "game_key", "started_at", "autostream", "scanned", "events"}


def _doc(**over):
    kw = dict(kind="clips", source=Path("rec.mp4"), duration=2731.5,
              game="VALORANT", game_key="valorant-win64-shipping.exe",
              started_at=1_790_000_000.7,
              kills=[{"time": 10.0}, {"time": 12.0}])
    kw.update(over)
    return killslog.build(**kw)


def test_build_has_every_key():
    doc = _doc()
    assert set(doc) == DOC_KEYS
    assert doc["schema_version"] == killslog.SCHEMA_VERSION == 1
    assert doc["kind"] == "clips" and doc["status"] == "ok"
    assert doc["source"] == str(Path("rec.mp4")) and isinstance(doc["source"], str)
    assert doc["duration"] == 2731.5
    assert doc["game"] == "VALORANT"
    assert doc["game_key"] == "valorant-win64-shipping.exe"
    assert doc["scanned"] is None
    assert len(doc["events"]) == 2
    json.dumps(doc)                                       # it has to be writable


def test_build_says_which_autostream_wrote_it():
    about = _doc()["autostream"]
    assert set(about) == {"version", "commit"}
    assert about["version"] == autostream.__version__
    assert about["commit"] is None or (isinstance(about["commit"], str) and about["commit"])


def test_started_at_is_local_time_with_its_offset_to_the_second():
    s = _doc()["started_at"]
    when = datetime.fromisoformat(s)
    assert when.utcoffset() is not None, "a time with no offset cannot be placed"
    assert "." not in s, "seconds precision"
    assert abs(when.timestamp() - 1_790_000_000.7) < 1.0


def test_no_kills_is_a_status_not_an_absence():
    doc = _doc(kills=[])
    assert doc["status"] == "no_kills" and doc["events"] == []


def test_a_window_is_recorded():
    assert _doc(scanned=[600.0, 1500.0])["scanned"] == [600.0, 1500.0]


# ------------------------------------------------------------------ write

def test_write_creates_the_folder_and_writes_json(tmp_path):
    folder = tmp_path / "a" / "run"
    doc = _doc()
    got = killslog.write(folder, doc)
    assert got == folder / killslog.FILENAME
    assert killslog.FILENAME == "kills.json"
    assert json.loads(got.read_text(encoding="utf-8")) == json.loads(json.dumps(doc))


def test_write_never_raises(tmp_path):
    """The folder path is a file: nothing can be written there, and the run
    that asked must carry on as if kills.json did not exist."""
    blocker = tmp_path / "run"
    blocker.write_text("not a folder")
    assert killslog.write(blocker, _doc()) is None
    assert blocker.read_text() == "not a folder"


# ------------------------------------------------------------ detect.Kill

def test_kill_still_constructs_positionally():
    k = detect.Kill(10.0, 0.9, 2)
    assert (k.time, k.score, k.count, k.end) == (10.0, 0.9, 2, 10.0)
    assert k.seen == 0 and k.votes == ""
    k = detect.Kill(10.0, 0.9, 2, 12.0)
    assert k.end == 12.0
    k = detect.Kill(10.0, 0.9, 1, seen=7, votes="kkkok")
    assert (k.seen, k.votes) == (7, "kkkok")


# --------------------------------------------------- a whole job, faked

def _kills_json(job) -> dict:
    return json.loads((job.folder / "kills.json").read_text(encoding="utf-8"))


def test_a_run_with_no_kills_still_writes_kills_json(tmp_path, monkeypatch):
    from autostream.clips import jobs

    src = tmp_path / "menu.mp4"
    src.write_bytes(b"")
    job = jobs.ClipJob(src, game="Counter-Strike 2", game_key="cs2.exe",
                       outdir=tmp_path / "out", options={})

    def nothing():
        job._set(summary={"kills": 0, "clips": 0, "covered": 0,
                          "coverage": 0, "runtime": 0})
        raise jobs.NoKills("No kills found in this recording.")

    monkeypatch.setattr(job, "_run", nothing)
    job.run()
    assert job.state == "done" and not job.error
    doc = _kills_json(job)
    assert doc["status"] == "no_kills" and doc["events"] == []
    assert doc["kind"] == "clips"
    assert doc["source"] == str(src) and doc["game_key"] == "cs2.exe"
    # Nothing else: a clips.json would put a run with no clips in the
    # Studio's library, which never happened before kills.json.
    assert [f.name for f in job.folder.iterdir()] == ["kills.json"]


def test_a_kills_only_folder_is_reused_and_starts_clean(tmp_path, monkeypatch):
    """A retry of a run that found nothing keeps the folder name it would
    always have had, not name_2, and starts from no folder at all."""
    from autostream.clips import jobs

    src = tmp_path / "menu.mp4"
    src.write_bytes(b"")
    out = tmp_path / "out"

    def job_for():
        return jobs.ClipJob(src, game="Counter-Strike 2", game_key="cs2.exe",
                            outdir=out, options={}, started=1_790_000_000.0)

    seen_at_start = []

    def nothing(job):
        def run():
            seen_at_start.append(job.folder.exists())
            raise jobs.NoKills("No kills found in this recording.")
        return run

    first = job_for()
    monkeypatch.setattr(first, "_run", nothing(first))
    first.run()
    assert (first.folder / "kills.json").is_file()

    second = job_for()
    assert second.folder == first.folder
    monkeypatch.setattr(second, "_run", nothing(second))
    second.run()
    seen_at_start.pop(0)
    assert seen_at_start == [False], "the leftover must be gone before _run"
    assert [f.name for f in second.folder.iterdir()] == ["kills.json"]


def test_a_folder_with_anything_else_in_it_is_still_taken(tmp_path):
    from autostream.clips import jobs

    taken = tmp_path / "run"
    taken.mkdir()
    (taken / "kills.json").write_text("{}")
    (taken / "session.json").write_text("{}")
    assert jobs._free_folder(tmp_path, "run") == tmp_path / "run_2"
    empty = tmp_path / "other"
    empty.mkdir()
    assert jobs._free_folder(tmp_path, "other") == tmp_path / "other_2", \
        "an empty folder was taken before kills.json and still is"
    only = tmp_path / "solo"
    only.mkdir()
    (only / "kills.json").write_text("{}")
    assert jobs._free_folder(tmp_path, "solo") == only
    # Opening it in Finder or Explorer leaves litter; still free.
    (only / ".DS_Store").write_bytes(b"\0")
    (only / "Thumbs.db").write_bytes(b"\0")
    assert jobs._free_folder(tmp_path, "solo") == only
    litter_only = tmp_path / "junk"
    litter_only.mkdir()
    (litter_only / ".DS_Store").write_bytes(b"\0")
    assert jobs._free_folder(tmp_path, "junk") == tmp_path / "junk_2", \
        "litter with no kills.json is not ours to take"


def test_a_reused_folder_is_cleared_of_litter_too(tmp_path, monkeypatch):
    from autostream.clips import jobs

    src = tmp_path / "menu.mp4"
    src.write_bytes(b"")
    job = jobs.ClipJob(src, game="Counter-Strike 2", game_key="cs2.exe",
                       outdir=tmp_path / "out", options={}, started=1_790_000_000.0)
    job.folder.mkdir(parents=True)
    (job.folder / "kills.json").write_text("{}")
    (job.folder / ".DS_Store").write_bytes(b"\0")
    existed = []

    def nothing():
        existed.append(job.folder.exists())
        raise jobs.NoKills("No kills found in this recording.")
    monkeypatch.setattr(job, "_run", nothing)
    job.run()
    assert existed == [False]
    assert [f.name for f in job.folder.iterdir()] == ["kills.json"]


def test_a_failed_run_writes_no_kills_json(tmp_path, monkeypatch):
    from autostream.clips import jobs

    src = tmp_path / "rec.mp4"
    src.write_bytes(b"")
    job = jobs.ClipJob(src, game="Counter-Strike 2", game_key="cs2.exe",
                       outdir=tmp_path / "out", options={})

    def boom():
        raise RuntimeError("something else went wrong")

    monkeypatch.setattr(job, "_run", boom)
    job.run()
    assert job.state == "failed"
    assert not (job.folder / "kills.json").exists()


def test_a_plan_only_run_keeps_the_side_keys_out_of_session_json(tmp_path, monkeypatch):
    """The real _run, as far as the plan: cached kills (so nothing is
    decoded), no profile, no emblems. Plan-only removes its session.json on
    the way out, so every write of it is captured as it happens."""
    from autostream import atomic
    from autostream.clips import cutter, jobs

    src = tmp_path / "rec.mp4"
    src.write_bytes(b"not really a video")
    monkeypatch.setattr(cutter, "probe_source", lambda p: {"duration": 600.0})
    monkeypatch.setattr(jobs.profiles, "for_game", lambda key, name=None: None)
    monkeypatch.setattr(jobs.overlay, "detect_tags", lambda *a, **k: {})
    sessions = []
    real = atomic.write_json

    def spy(path, data, *a, **k):
        if Path(path).name == "session.json":
            sessions.append(json.loads(json.dumps(data)))
        return real(path, data, *a, **k)
    monkeypatch.setattr(atomic, "write_json", spy)

    cached = [{"time": 100.0, "end": 101.0, "score": 0.9, "count": 1,
               "seen": 5, "votes": "kkkok"},
              {"time": 105.0, "end": 106.0, "score": 0.9, "count": 1},
              {"time": 300.0, "end": 301.0, "score": 0.9, "count": 1,
               "seen": 2, "votes": "kk"}]
    job = jobs.ClipJob(src, game="Testing", game_key=None,
                       outdir=tmp_path / "out",
                       options={"plan_only": True, "kills": cached,
                                "emblems": False, "promo": False,
                                "min_kills": 1})
    job.run()
    assert job.state == "done", job.error
    assert sessions, "the run never wrote session.json"
    for s in sessions:
        for k in s["kills"]:
            assert not set(k) & {"seen", "votes"}, k
            assert {"time", "end", "score", "count"} <= set(k)
    doc = _kills_json(job)
    assert doc["kind"] == "plan_only" and doc["status"] == "ok"
    assert doc["duration"] == 600.0 and doc["scanned"] is None
    ev = doc["events"]
    assert [e["time"] for e in ev] == [100.0, 105.0, 300.0]
    assert [e["confidence"] for e in ev] == [0.8, None, 1.0]
    assert [e["seen"] for e in ev] == [5, None, 2]
    assert [(e["burst_id"], e["burst_size"]) for e in ev] == [(0, 2), (0, 2), (1, 1)]
    # Plan-only leaves nothing behind but this: no session.json, no clips.json.
    assert [f.name for f in job.folder.iterdir()] == ["kills.json"]


def test_a_match_video_run_writes_kills_json_beside_session_json(tmp_path, monkeypatch):
    """Marvel Rivals has no kill list in session.json; its KOs are the
    moments, so kills.json is the only place they are written one by one."""
    from test_rivals import build, with_kills

    from autostream.clips import cutter, highlight, jobs, rivals

    src = tmp_path / "rec.mp4"
    src.write_bytes(b"not really a video")
    readings = build(600, with_kills)
    monkeypatch.setattr(cutter, "probe_source", lambda p: {"duration": 600.0})
    monkeypatch.setattr(rivals, "scan", lambda *a, **k: readings)

    def fake_master(source, spans, name, outdir, **kw):
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / f"{name}.mp4"
        out.write_bytes(b"")
        return out
    monkeypatch.setattr(cutter, "master_segments", fake_master)

    def fake_render(source, shots, out, **kw):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"")
        return out
    monkeypatch.setattr(highlight, "render", fake_render)

    job = jobs.ClipJob(src, game="Marvel Rivals",
                       game_key="marvel-win64-shipping.exe",
                       outdir=tmp_path / "out", options={})
    job.run()
    assert job.state == "done", job.error
    assert (job.folder / "session.json").is_file()
    doc = _kills_json(job)
    assert doc["kind"] == "match-videos"
    kos = sorted(t for m in rivals.matches(readings) for t in m.all_kos())
    assert kos, "the fixture has no KOs to write"
    assert [e["time"] for e in doc["events"]] == [round(t, 3) for t in kos]
    assert all(e["end"] == e["time"] for e in doc["events"])
