"""Clipping only part of a recording.

One file is not one game. It holds a menu, a warm-up, the tail of the last
match, and often a different game entirely after it -- and a scan reads one
game at a time. A window says which part to read.

The failure mode this guards against is the silent one: a window that is
mis-applied does not raise, it produces "No kills found in this recording" for
a file full of them, or -- worse -- clips cut from the part the user
deliberately excluded. Neither looks like a bug from the outside.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import types
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest                                                    # noqa: E402

from autostream import webui                                     # noqa: E402
from autostream.clips import detect                              # noqa: E402
from autostream.clips.jobs import ClipJob                        # noqa: E402
from autostream.clips.profiles import Profile                    # noqa: E402


def a_job(tmp_path, **options) -> ClipJob:
    job = ClipJob.__new__(ClipJob)
    job.source = tmp_path / "rec.mp4"
    job.source.write_bytes(b"x")
    job.options = options
    job.win_start, job.win_end, job.win_whole = 0.0, 0.0, True
    job._cancel = threading.Event()
    job._lock = threading.Lock()
    return job


HOUR = {"duration": 3600.0}


# --------------------------------------------------------- what gets honoured

def test_no_window_reads_the_whole_file(tmp_path):
    assert a_job(tmp_path)._window(HOUR) == (0.0, 3600.0)


def test_a_chosen_window_is_kept(tmp_path):
    job = a_job(tmp_path, scan_start=600.0, scan_end=1800.0)
    assert job._window(HOUR) == (600.0, 1800.0)


def test_an_end_of_zero_means_to_the_end_of_the_file(tmp_path):
    """What the page sends when only the start handle was moved."""
    job = a_job(tmp_path, scan_start=600.0, scan_end=0.0)
    assert job._window(HOUR) == (600.0, 3600.0)


def test_a_window_past_the_end_is_clamped(tmp_path):
    job = a_job(tmp_path, scan_start=100.0, scan_end=99999.0)
    assert job._window(HOUR) == (100.0, 3600.0)


# ----------------------------------------------------------- what gets refused
#
# Every one of these would otherwise scan nothing and report "no kills", which
# is indistinguishable from a recording that genuinely has none.

def test_a_backwards_window_is_ignored(tmp_path):
    job = a_job(tmp_path, scan_start=1800.0, scan_end=600.0)
    assert job._window(HOUR) == (0.0, 3600.0)


def test_a_window_too_short_to_hold_a_clip_is_ignored(tmp_path):
    job = a_job(tmp_path, scan_start=600.0, scan_end=605.0)
    assert job._window(HOUR) == (0.0, 3600.0)


def test_a_negative_start_is_ignored(tmp_path):
    job = a_job(tmp_path, scan_start=-500.0, scan_end=1800.0)
    assert job._window(HOUR) == (0.0, 1800.0)


def test_nonsense_is_ignored_rather_than_raising(tmp_path):
    job = a_job(tmp_path, scan_start="soon", scan_end=None)
    assert job._window(HOUR) == (0.0, 3600.0)


# ------------------------------------------------- the window reaches the scan
#
# The scan is where a window either works or silently does not, so this checks
# the spans ffmpeg is actually asked for rather than the argument going in.

def _spans_for(monkeypatch, **kw) -> list[tuple[float, float]]:
    asked: list[tuple[float, float]] = []

    def fake_span(video, profile, start, dur, tmpl0, geom):
        asked.append((start, dur))
        return []

    monkeypatch.setattr(detect, "scan_span", fake_span)
    monkeypatch.setattr(detect, "media_info",
                        lambda p: {"duration": 3600.0, "width": 1920,
                                   "height": 1080, "fps": 60.0})
    monkeypatch.setattr(detect, "load_template", lambda p: None)
    monkeypatch.setattr(detect, "band_geometry", lambda w, h, p: ((0, 0), (10, 10)))
    prof = Profile(key="x.exe", label="X", band=(0, 0, 1, 1), template="t.png",
                   mode="colour")
    detect.scan(Path("rec.mp4"), prof, **kw)
    return asked


def test_a_full_scan_starts_at_zero(monkeypatch):
    spans = _spans_for(monkeypatch)
    assert spans[0][0] == 0.0
    assert spans[-1][0] + spans[-1][1] == pytest.approx(3600.0)


def test_a_windowed_scan_reads_only_the_window(monkeypatch):
    spans = _spans_for(monkeypatch, start=1200.0, duration=600.0)
    assert spans[0][0] == 1200.0
    assert spans[-1][0] + spans[-1][1] == pytest.approx(1800.0)
    # And nothing outside it. This is the whole point: the cost of a run is
    # the seconds of video read, so a window that leaks is a window that saves
    # nothing.
    assert all(1200.0 <= a and a + d <= 1800.0 + 0.001 for a, d in spans)


def test_the_last_span_does_not_overrun_the_window(monkeypatch):
    """CHUNK_SECONDS does not divide the window, and the arithmetic that
    handles that is the easiest thing here to get wrong by one chunk."""
    spans = _spans_for(monkeypatch, start=100.0, duration=185.0)
    assert spans[-1][0] + spans[-1][1] == pytest.approx(285.0)


# -------------------------------------------------- reusing an earlier scan
#
# Kills are cached so re-cutting a recording does not pay to scan it twice.
# A scan that only read part of the file has a kill list that is complete only
# inside that part, and reusing it anywhere else reports an empty stretch for
# footage that was never read.

def _cache(tmp_path, scanned, kills=None):
    app = webui.Server.__new__(webui.Server)
    app._clips_dir = lambda c=None: tmp_path                     # noqa: SLF001
    run = tmp_path / "a_run"
    run.mkdir()
    body = {"source": str(tmp_path / "rec.mp4"),
            "kills": kills or [{"time": 10.0}, {"time": 20.0}]}
    if scanned is not None:
        body["scanned"] = scanned
    (run / "session.json").write_text(json.dumps(body), encoding="utf-8")
    return app


def test_a_whole_file_scan_is_reused(tmp_path):
    app = _cache(tmp_path, [0.0, 0.0])
    assert app._cached_kills(tmp_path / "rec.mp4", object(), (0.0, 0.0))


def test_a_sidecar_from_before_windows_existed_is_still_reused(tmp_path):
    """No `scanned` key at all. Those runs always read the whole file, and
    treating them as unusable would make every existing install rescan."""
    app = _cache(tmp_path, None)
    assert app._cached_kills(tmp_path / "rec.mp4", object(), (0.0, 0.0))


def test_a_windowed_scan_is_not_reused_for_the_whole_file(tmp_path):
    app = _cache(tmp_path, [600.0, 1200.0])
    assert app._cached_kills(tmp_path / "rec.mp4", object(), (0.0, 0.0)) is None


def test_a_windowed_scan_is_not_reused_for_a_wider_window(tmp_path):
    app = _cache(tmp_path, [600.0, 1200.0])
    assert app._cached_kills(tmp_path / "rec.mp4", object(), (300.0, 1500.0)) is None


def test_a_windowed_scan_is_reused_for_the_same_window(tmp_path):
    """The normal case: cut it, look at it, cut it again at a different
    length. Rescanning there would be minutes spent to reach the same list."""
    app = _cache(tmp_path, [600.0, 1200.0])
    assert app._cached_kills(tmp_path / "rec.mp4", object(), (600.0, 1200.0))


def test_a_windowed_scan_is_reused_for_a_narrower_window(tmp_path):
    app = _cache(tmp_path, [600.0, 1200.0])
    assert app._cached_kills(tmp_path / "rec.mp4", object(), (700.0, 1100.0))


# ------------------------------------------------- cached kills are trimmed
#
# A cached list covers the whole file. Cutting a window from it must not
# produce clips from outside the window -- which is the same bug as above seen
# from the other end, and the one that puts the wrong footage on screen.

def test_cached_kills_outside_the_window_are_dropped(tmp_path):
    job = a_job(tmp_path)
    job.win_start, job.win_end, job.win_whole = 600.0, 1200.0, False
    kept = job._trim_cached([{"time": 10.0}, {"time": 700.0},
                             {"time": 1190.0}, {"time": 2000.0}])
    assert [k["time"] for k in kept] == [700.0, 1190.0]


def test_cached_kills_survive_untouched_without_a_window(tmp_path):
    job = a_job(tmp_path)
    kills = [{"time": 10.0}, {"time": 2000.0}]
    assert job._trim_cached(kills) == kills


def test_trimming_nothing_is_not_an_error(tmp_path):
    job = a_job(tmp_path)
    job.win_start, job.win_end, job.win_whole = 600.0, 1200.0, False
    assert job._trim_cached(None) is None
    assert job._trim_cached([]) == []


# ------------------------------------------------------- the demo, out loud
#
# Three things were invisible from the outside on a real run, all reported
# from one screenshot: a replay WAS on disk and the page showed nothing; the
# probe read twelve minutes, matched nothing, and fell back silently; and the
# card quoted "about 4m of scanning" for a run that took thirty.

def test_the_scan_rate_for_round_mode_is_not_the_plain_killfeed_rate():
    """scan_with_hud reads the scoreboard as well as the feed -- two crops
    OCR'd per frame instead of one. Measured at 1.5x against plain killfeed's
    4.5x, and quoting the wrong one advertised a 30-minute run as 4."""
    from autostream.clips import jobs

    assert jobs.scan_rate("killfeed", rounds=False) == 4.5
    # Two real runs measured 1.46x and 1.19x. The lower is used, because this
    # number's whole job is to be quoted BEFORE the run and the estimate that
    # undersells is the one that gets somebody to press the button.
    assert jobs.scan_rate("killfeed", rounds=True) == 1.2
    assert jobs.scan_rate("killfeed", rounds=True) < jobs.scan_rate("killfeed")


def test_a_mode_without_a_round_rate_is_unaffected():
    from autostream.clips import jobs

    assert jobs.scan_rate("feedbar", rounds=True) == jobs.scan_rate("feedbar")
    assert jobs.scan_rate("nonsense") == jobs.DEFAULT_SCAN_RATE


def test_the_estimate_uses_the_round_rate_when_rounds_are_on(tmp_path):
    """The number the page and the progress bar both quote before any chunk
    has finished."""
    import threading
    import time as _t

    job = ClipJob.__new__(ClipJob)
    job._lock = threading.Lock()
    job.state, job.step = "running", "scan"
    job.done, job.total = 0, 1
    job.clip_count = 0
    job.scan_seconds = 3600.0
    job.scan_mode = "killfeed"
    job.started_at = job.step_started = _t.time()

    job.scan_rounds = False
    fast = job.eta()
    job.scan_rounds = True
    slow = job.eta()
    assert fast is not None and slow is not None
    assert slow > fast * 2, (
        "an hour of round-mode footage must not be estimated at the "
        "plain-killfeed rate")


def test_every_demo_outcome_says_what_happened():
    """A probe that finds nothing costs twelve minutes and used to leave no
    trace outside the log, so a demo that did not match was indistinguishable
    from one that was never looked for."""
    import inspect

    from autostream.clips import jobs

    src = inspect.getsource(jobs.ClipJob)
    # Every branch that decides the demo question sets the note.
    assert src.count("demo_note=") >= 5, (
        "each way the demo search can end -- nothing newer, too few kills, "
        "no match, matched by the probe, matched after the scan -- has to say "
        "so, or the slow path looks like the only path")
    assert '"demo_note": self.demo_note' in src, "and it has to reach the page"


# ------------------------------------------ stopping instead of falling back
#
# Reported from a real run: the replay was downloaded, it still did not match,
# and the job quietly spent forty minutes reading 48 minutes of Counter-Strike
# off the screen -- for a worse answer than the demo would have given. The
# expensive decision was being made silently, on the user's behalf.

def test_a_stopped_run_is_distinguishable_from_a_failed_one(tmp_path):
    """The page shows a sharing-code box on one and a stack trace hint on the
    other, so they must not arrive looking the same."""
    import threading
    import time as _t

    from autostream.clips import jobs

    job = ClipJob.__new__(ClipJob)
    job._lock = threading.Lock()
    job._cancel = threading.Event()
    job._proc = None
    job.cancel_at = None
    job.state, job.step = "running", "scan"
    job.done, job.total = 0, 1
    job.message, job.error = "", None
    job.game, job.folder = "Counter-Strike 2", Path("x")
    job.results, job.preview, job.summary = [], [], {}
    job.montage_path = job.reel_path = job.promo_path = None
    job.started_at = job.step_started = _t.time()
    job.source = Path("rec.mp4")
    job.source_seconds = job.scan_seconds = 2640.0
    job.scan_mode, job.clip_count, job.scan_rounds = "killfeed", 0, True
    job.demo, job.demo_note, job.needs_demo = {}, "", False
    job.finished_at = None

    def boom(self):
        raise jobs.NeedsDemo("no replay matched")

    job._run = boom.__get__(job)
    job._write_manifest = lambda: None
    job.run()

    snap = job.snapshot()
    assert snap["state"] == "failed"
    assert snap["needs_demo"] is True, (
        "without this the page shows 'Could not finish' and none of the two "
        "things that actually move it forward")
    assert "replay" in snap["message"].lower()
    assert snap["error"] == "no replay matched"


def test_an_ordinary_failure_does_not_ask_for_a_replay(tmp_path):
    import threading
    import time as _t

    job = ClipJob.__new__(ClipJob)
    job._lock = threading.Lock()
    job._cancel = threading.Event()
    job._proc = None
    job.cancel_at = None
    job.state, job.step = "running", "scan"
    job.done, job.total = 0, 1
    job.message, job.error = "", None
    job.game, job.folder = "Counter-Strike 2", Path("x")
    job.results, job.preview, job.summary = [], [], {}
    job.montage_path = job.reel_path = job.promo_path = None
    job.started_at = job.step_started = _t.time()
    job.source = Path("rec.mp4")
    job.source_seconds = job.scan_seconds = 10.0
    job.scan_mode, job.clip_count, job.scan_rounds = "killfeed", 0, False
    job.demo, job.demo_note, job.needs_demo = {}, "", False
    job.finished_at = None

    def boom(self):
        raise RuntimeError("something else went wrong")

    job._run = boom.__get__(job)
    job._write_manifest = lambda: None
    job.run()
    assert job.snapshot()["needs_demo"] is False


# ------------------------------------------------- the probe is kept
#
# The answer to "no replay matched" is to download the replay and run again.
# Re-reading the same twelve minutes to rebuild an identical seed is about nine
# minutes spent to learn nothing.

def _probe_job(tmp_path, start=0.0):
    job = ClipJob.__new__(ClipJob)
    job.source = tmp_path / "rec.mp4"
    job.source.write_bytes(b"x")
    job.win_start = start
    job.folder = tmp_path / "runs" / "one"
    return job


def test_a_probe_is_remembered_and_read_back(tmp_path):
    job = _probe_job(tmp_path)
    seed = [{"time": 10.0}, {"time": 20.0}]
    job._remember_probe(seed, 720.0)

    again = _probe_job(tmp_path)
    again.folder = tmp_path / "runs" / "two"
    assert again._recall_probe(720.0) == seed


def test_a_probe_of_a_different_part_is_not_reused(tmp_path):
    job = _probe_job(tmp_path, start=0.0)
    job._remember_probe([{"time": 10.0}], 720.0)

    other = _probe_job(tmp_path, start=1800.0)
    other.folder = tmp_path / "runs" / "two"
    assert other._recall_probe(720.0) is None, (
        "a probe of the first twelve minutes says nothing about a selection "
        "that starts half an hour in")


def test_a_shorter_probe_is_not_reused_for_a_longer_one(tmp_path):
    job = _probe_job(tmp_path)
    job._remember_probe([{"time": 10.0}], 300.0)

    other = _probe_job(tmp_path)
    other.folder = tmp_path / "runs" / "two"
    assert other._recall_probe(720.0) is None


def test_a_probe_of_another_file_is_not_reused(tmp_path):
    job = _probe_job(tmp_path)
    job._remember_probe([{"time": 10.0}], 720.0)

    other = _probe_job(tmp_path)
    other.source = tmp_path / "different.mp4"
    other.folder = tmp_path / "runs" / "two"
    assert other._recall_probe(720.0) is None
