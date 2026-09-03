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
