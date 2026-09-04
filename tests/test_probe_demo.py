"""Reading a few minutes instead of the whole recording.

The scan only ever existed to FIND THE DEMO: where one aligns, every kill and
round is thrown away and taken from the demo instead. Reading a whole recording
to build a fingerprint that a few minutes would have built was the most
expensive thing a Counter-Strike job did, for the least reason -- about eleven
seconds of scanning per minute of video, so twenty minutes on a feature-length
file.

Five minutes of kills picked the right demo out of fourteen real ones, every
kill aligned, no error. Twelve is used for headroom.

These tests exercise the probe by CALLING it. An earlier version of this change
wired the call and never defined the method: the suite stayed green, because
nothing here ran that path, and it would have crashed on the next real job.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest                                                    # noqa: E402

from autostream.clips import jobs                                 # noqa: E402
from autostream.clips.jobs import ClipJob                         # noqa: E402


class Prof:
    def __init__(self, demos=True, mode="killfeed"):
        self.demos, self.mode = demos, mode
        self.player = "someone"


def a_job(tmp_path) -> ClipJob:
    job = ClipJob.__new__(ClipJob)
    job.source = tmp_path / "rec.mp4"
    job.source.write_bytes(b"x")
    job.game = "Counter-Strike 2"
    job.demo = {}
    import threading
    job._cancel = threading.Event()
    job._lock = threading.Lock()
    job.state = "running"
    job.done = job.total = 0
    job.message = ""
    # The part of the file being read. A real job settles this from the run's
    # options before the probe is reached; these tests are about the probe, so
    # they use the default -- the whole recording.
    job.win_start, job.win_end, job.win_whole = 0.0, 0.0, True
    # How long the recording is. A real job probes it before the demo search
    # ever runs; it is here because _source_started subtracts it from mtime to
    # date a file OBS did not name -- see test_source_started.py.
    job.source_seconds = 0.0
    job.demo_note, job.needs_demo = "", False
    # The probe keeps its kills so a second run does not re-read the same
    # twelve minutes. Pointed at the tmp dir so nothing here touches the real
    # clips folder.
    job.folder = tmp_path / "run"
    return job


LONG = {"duration": 111 * 60}


def test_the_method_exists_and_is_callable(tmp_path):
    """The regression that motivated this file: the call was wired and the
    method never written. The suite stayed green and the job would crash."""
    job = a_job(tmp_path)
    assert callable(getattr(job, "_probe_for_demo", None))


def test_a_game_without_demos_is_not_probed(tmp_path):
    job = a_job(tmp_path)
    assert job._probe_for_demo(Prof(demos=False), {}, LONG) is None


def test_no_profile_at_all_is_not_probed(tmp_path):
    job = a_job(tmp_path)
    assert job._probe_for_demo(None, {}, LONG) is None


def test_a_short_recording_is_not_probed(tmp_path):
    """Probing then reading the rest would cost MORE than one full read."""
    job = a_job(tmp_path)
    assert job._probe_for_demo(Prof(), {}, {"duration": 5 * 60}) is None


def test_cached_kills_skip_the_probe(tmp_path):
    """A previous scan is already free; spending minutes to re-derive it is
    strictly worse."""
    job = a_job(tmp_path)
    assert job._probe_for_demo(Prof(), {"kills": [{"time": 1.0}]}, LONG) is None


def test_demo_turned_off_skips_the_probe(tmp_path):
    job = a_job(tmp_path)
    assert job._probe_for_demo(Prof(), {"demo": False}, LONG) is None


def test_too_few_kills_in_the_window_stops_and_asks(tmp_path, monkeypatch):
    """Two kills cannot fingerprint a match, and guessing from them would
    mis-cut every clip.

    It used to read the whole recording instead. That is about forty minutes
    for three quarters of an hour of Counter-Strike, for a worse answer than
    the demo would have given -- spent on the user's behalf because a replay
    they may simply not have downloaded yet did not match. So it stops.
    """
    import autostream.clips.detect as detect
    import autostream.clips.cs2_demo as cs2_demo

    job = a_job(tmp_path)
    monkeypatch.setattr(cs2_demo, "demo_folder", lambda *a, **k: "C:/demos")
    monkeypatch.setattr(detect, "scan", lambda *a, **k: [])
    with pytest.raises(jobs.NeedsDemo):
        job._probe_for_demo(Prof(), {}, LONG)
    assert "0 kill" in job.demo_note
    assert "start handle" in job.demo_note, (
        "the usual cause is a selection that opens on a menu, so the note has "
        "to name the fix")


def test_the_slow_read_still_happens_when_it_is_asked_for(tmp_path, monkeypatch):
    """The escape hatch. Nobody loses the ability to read the screen -- they
    just have to choose it, with the cost on the button."""
    import autostream.clips.detect as detect
    import autostream.clips.cs2_demo as cs2_demo

    job = a_job(tmp_path)
    monkeypatch.setattr(cs2_demo, "demo_folder", lambda *a, **k: "C:/demos")
    monkeypatch.setattr(detect, "scan", lambda *a, **k: [])
    assert job._probe_for_demo(Prof(), {"demo_fallback": True}, LONG) is None
    assert not job.needs_demo
    assert "as asked" in job.demo_note


def test_a_failing_probe_costs_the_run_nothing(tmp_path, monkeypatch):
    """It is an optimisation. Anything it cannot answer falls back to the
    behaviour that always worked, rather than failing the job."""
    import autostream.clips.detect as detect
    import autostream.clips.cs2_demo as cs2_demo

    job = a_job(tmp_path)
    monkeypatch.setattr(cs2_demo, "demo_folder", lambda *a, **k: "C:/demos")

    def boom(*a, **k):
        raise RuntimeError("ffmpeg fell over")
    monkeypatch.setattr(detect, "scan", boom)
    # Still a fall-back, not a stop: the probe could not ASK the question, so
    # it has learnt nothing about whether a replay exists. Refusing to run on
    # the strength of a crash would be refusing for the wrong reason.
    assert job._probe_for_demo(Prof(), {}, LONG) is None
    assert not job.needs_demo


def test_cancelling_during_the_probe_still_cancels(tmp_path, monkeypatch):
    """Cancel must not be swallowed by the fallback -- a user pressing Stop
    expects the job to stop, not to start reading the whole file."""
    import autostream.clips.detect as detect
    import autostream.clips.cs2_demo as cs2_demo

    job = a_job(tmp_path)
    monkeypatch.setattr(cs2_demo, "demo_folder", lambda *a, **k: "C:/demos")

    def cancelled(*a, **k):
        raise detect.Cancelled("cancelled")
    monkeypatch.setattr(detect, "scan", cancelled)
    with pytest.raises(detect.Cancelled):
        job._probe_for_demo(Prof(), {}, LONG)


def test_a_found_demo_is_returned_and_the_rest_is_skipped(tmp_path, monkeypatch):
    import autostream.clips.detect as detect
    import autostream.clips.cs2_demo as cs2_demo

    class K:
        def __init__(self, t):
            self.time = self.end = t
            self.score, self.count = 1.0, 1

    job = a_job(tmp_path)
    monkeypatch.setattr(cs2_demo, "demo_folder", lambda *a, **k: "C:/demos")
    monkeypatch.setattr(detect, "scan", lambda *a, **k: [K(1.0), K(2.0), K(3.0)])
    answer = {"kills": [{"time": 9.0}], "rounds": [1], "about": {"demo": "x.dem"}}
    monkeypatch.setattr(ClipJob, "_from_demo", lambda self, kills: answer)

    got = job._probe_for_demo(Prof(), {}, LONG)
    assert got is answer, "the demo's own kills must replace the probe's"


# ------------------------------------------- choosing between real demos

def test_choosing_a_demo_needs_a_real_count_not_just_a_share(monkeypatch):
    """A wrong demo does not fail loudly -- it mis-cuts every clip in the run.

    align() judges one candidate on its own terms, and a player with seven
    kills needs only five to clear the 0.6 share. A demo from two days before
    a recording was accepted on five coincidental timings out of seven. The
    CHOICE between demos therefore demands an absolute count as well.
    """
    from autostream.clips import cs2_demo

    assert cs2_demo.MIN_MATCHED >= 5, "the floor is what makes the choice safe"

    src = __import__("inspect").getsource(cs2_demo.pick_demo)
    assert "MIN_MATCHED" in src, "pick_demo does not apply the floor"


def test_align_itself_stays_permissive():
    """It is also used to audit a demo already known to be right, where a
    three-kill fixture is a legitimate thing to align."""
    from autostream.clips import cs2_demo

    demo = [10.0, 20.0, 30.0]
    vod = [110.0, 120.0, 130.0]
    s = cs2_demo.align(demo, vod)
    assert s.ok, "align became too strict for the audit path"


# ------------------------------- not looking when there is nothing to find

def test_the_probe_is_skipped_when_no_demo_is_newer(tmp_path, monkeypatch):
    """A demo cannot record a match played after it was written.

    Reading twelve minutes to search a folder whose newest demo predates the
    recording proves something a directory listing already knew. It cost 2.2
    minutes on a real recording made two days after the last demo -- and the
    whole file was then read anyway.
    """
    import autostream.clips.cs2_demo as cs2_demo
    import autostream.clips.detect as detect

    job = a_job(tmp_path)
    scanned = []
    monkeypatch.setattr(cs2_demo, "demo_folder", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(cs2_demo, "newest_demo_time", lambda f: 1_000.0)
    monkeypatch.setattr(ClipJob, "_source_started", lambda self: 200_000.0)
    monkeypatch.setattr(detect, "scan", lambda *a, **k: scanned.append(1) or [])

    with pytest.raises(jobs.NeedsDemo):
        job._probe_for_demo(Prof(), {}, LONG)
    assert scanned == [], "it scanned anyway"
    assert "newer than this recording" in job.demo_note


def test_a_demo_newer_than_the_recording_is_still_searched(tmp_path, monkeypatch):
    """The ordinary case: you played, the demo was written, then you clip it."""
    import autostream.clips.cs2_demo as cs2_demo
    import autostream.clips.detect as detect

    job = a_job(tmp_path)
    scanned = []
    monkeypatch.setattr(cs2_demo, "demo_folder", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(cs2_demo, "newest_demo_time", lambda f: 300_000.0)
    monkeypatch.setattr(ClipJob, "_source_started", lambda self: 200_000.0)
    monkeypatch.setattr(detect, "scan",
                        lambda *a, **k: scanned.append(1) or [])

    with pytest.raises(jobs.NeedsDemo):
        job._probe_for_demo(Prof(), {}, LONG)
    # At least one -- the probe widens and tries again when a window turns up
    # too few kills to fingerprint with, so the count is a budget, not a fact.
    assert scanned, "it skipped a search that could have succeeded"
    assert len(scanned) <= jobs.ClipJob.PROBE_TRIES


def test_an_unknown_recording_time_does_not_skip(tmp_path, monkeypatch):
    """Refusing to look because a timestamp could not be read would lose the
    demo path on any file OBS did not name."""
    import autostream.clips.cs2_demo as cs2_demo
    import autostream.clips.detect as detect

    job = a_job(tmp_path)
    scanned = []
    monkeypatch.setattr(cs2_demo, "demo_folder", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(cs2_demo, "newest_demo_time", lambda f: 1_000.0)
    monkeypatch.setattr(ClipJob, "_source_started", lambda self: None)
    monkeypatch.setattr(detect, "scan", lambda *a, **k: scanned.append(1) or [])

    with pytest.raises(jobs.NeedsDemo):
        job._probe_for_demo(Prof(), {}, LONG)
    assert scanned
    assert len(scanned) <= jobs.ClipJob.PROBE_TRIES


def test_an_empty_demo_folder_does_not_skip_on_time(tmp_path, monkeypatch):
    """No demos at all is a different answer from stale demos, and the rest of
    the guard already covers it."""
    import autostream.clips.cs2_demo as cs2_demo

    assert cs2_demo.newest_demo_time(tmp_path) is None


# --------------------------------------------- the probe widens before giving up
#
# FROM A REAL RUN. The chosen window began at 20m22s, the match's first kill
# was at 31m14s, and the probe read the eleven minutes of nothing in between --
# ONE of the demo's sixteen kills fell inside it. The fingerprint had nothing to
# work with and the run stopped, asking for a replay that was on disk.
#
# Twelve more minutes would have covered nine of them.

def test_a_thin_window_is_widened_rather_than_abandoned(tmp_path, monkeypatch):
    import autostream.clips.cs2_demo as cs2_demo
    import autostream.clips.detect as detect

    class K:
        def __init__(self, t):
            self.time = self.end = t
            self.score, self.count = 1.0, 1

    job = a_job(tmp_path)
    monkeypatch.setattr(cs2_demo, "demo_folder", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(cs2_demo, "newest_demo_time", lambda f: None)

    windows = []

    def scan(video, prof, *, duration=None, start=0.0, **kw):
        windows.append((start, duration))
        # Nothing in the first window, plenty in the second -- the shape of the
        # failure this exists for.
        return [] if len(windows) == 1 else [K(900.0), K(930.0), K(980.0)]

    monkeypatch.setattr(detect, "scan", scan)
    answer = {"kills": [{"time": 9.0}], "rounds": [], "about": {"demo": "x.dem"}}
    monkeypatch.setattr(ClipJob, "_from_demo", lambda self, kills: answer)

    got = job._probe_for_demo(Prof(), {}, LONG)
    assert got is answer, "a second window found it and the run carried on"
    assert len(windows) == 2, "it should have widened exactly once"


def test_each_window_reads_only_what_the_last_one_did_not(tmp_path, monkeypatch):
    """Re-reading the first twelve minutes to extend to twenty-four would
    double the cost of the thing that exists to be cheap."""
    import autostream.clips.cs2_demo as cs2_demo
    import autostream.clips.detect as detect

    job = a_job(tmp_path)
    monkeypatch.setattr(cs2_demo, "demo_folder", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(cs2_demo, "newest_demo_time", lambda f: None)
    windows = []

    def scan(video, prof, *, duration=None, start=0.0, **kw):
        windows.append((start, duration))
        return []

    monkeypatch.setattr(detect, "scan", scan)
    with pytest.raises(jobs.NeedsDemo):
        job._probe_for_demo(Prof(), {}, LONG)

    assert windows[0][0] == 0.0
    covered = 0.0
    for start, dur in windows:
        assert start == pytest.approx(covered), "a window overlapped the last"
        covered += dur
    assert covered <= jobs.ClipJob.PROBE_SECONDS * jobs.ClipJob.PROBE_TRIES


def test_widening_stops_well_short_of_reading_everything(tmp_path):
    """The whole point is to be cheaper than the full read it avoids."""
    budget = jobs.ClipJob.PROBE_SECONDS * jobs.ClipJob.PROBE_TRIES
    assert budget < LONG["duration"] / 2, (
        "a probe that can read half the recording is not a probe")
