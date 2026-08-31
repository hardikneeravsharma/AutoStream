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


def test_too_few_kills_in_the_window_falls_back(tmp_path, monkeypatch):
    """Two kills cannot fingerprint a match, and guessing from them would
    mis-cut every clip. The whole recording gets read instead."""
    import autostream.clips.detect as detect
    import autostream.clips.cs2_demo as cs2_demo

    job = a_job(tmp_path)
    monkeypatch.setattr(cs2_demo, "demo_folder", lambda *a, **k: "C:/demos")
    monkeypatch.setattr(detect, "scan", lambda *a, **k: [])
    assert job._probe_for_demo(Prof(), {}, LONG) is None


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
    assert job._probe_for_demo(Prof(), {}, LONG) is None


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
