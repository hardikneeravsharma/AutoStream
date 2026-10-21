"""A shot's speed changes rendered smoothly: eased, optical-flow slow, shuttered fast.

The promise that lets the rest of the Studio ignore this module: outside the
eases the source time is exactly what the pieces say, and an ease is never laid
over a kill -- so derive(), preview_at() and every kill's frame are unchanged.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import retime                                 # noqa: E402

FPS = retime.FPS
RAMP = [(0.0, 1.0, 1.6), (1.0, 1.3, 0.7), (1.3, 2.0, 0.3), (2.0, 3.0, 1.0)]   # s02 with its kill at 1.45


def test_real_speed_needs_nothing():
    assert not retime.needed([(0.0, 2.0, 1.0)])
    assert retime.needed(RAMP)
    assert retime.eases([(0.0, 1.0, 1.0), (1.0, 2.0, 1.0)]) == []


def test_outside_the_eases_the_map_is_the_pieces_own():
    frames = 3 * FPS
    src, _ = retime.frame_map(RAMP, frames, kills=[1.45])
    windows = retime.eases(RAMP, [1.45])
    for i in range(frames):
        t = i / FPS
        if any(c - h - 1e-9 <= t <= c + h + 1e-9 for c, h, *_ in windows):
            continue
        assert src[i] == pytest.approx(retime.stepped(RAMP, t), abs=2e-4), t


def test_the_kill_is_on_its_planned_frame():
    for kill in (1.45, 1.31, 1.99):
        src, _ = retime.frame_map(RAMP, 3 * FPS, kills=[kill])
        i = round(kill * FPS)
        assert src[i] == pytest.approx(retime.stepped(RAMP, i / FPS), abs=2e-4)


def test_no_ease_is_laid_over_a_kill():
    for c, h, *_ in retime.eases(RAMP, [1.31]):
        assert abs(c - 1.31) >= h + retime.KILL_CLEAR - 1e-9


def test_the_speed_never_jumps():
    """The complaint in one number: the old map changed 1.6x -> 0.7x between
    two frames. Eased, no two frames differ by more than a fraction of that."""
    _, rate = retime.frame_map(RAMP, 3 * FPS, kills=[1.45])
    assert np.max(np.abs(np.diff(rate))) < 0.15
    stepped = np.array([[r for a, b, r in RAMP if a <= i / FPS < b][0] for i in range(3 * FPS)])
    assert np.max(np.abs(np.diff(stepped))) >= 0.9


def test_an_ease_fits_inside_short_pieces():
    tight = [(0.0, 0.1, 2.0), (0.1, 0.2, 0.5), (0.2, 1.0, 1.0)]
    for c, h, *_ in retime.eases(tight):
        assert h <= retime.EASE_SHARE * 0.1 + 1e-9


def test_slow_spans_are_found_with_their_slowest_rate():
    src, rate = retime.frame_map(RAMP, 3 * FPS, kills=[1.45])
    spans = retime.slow_spans(src, rate)
    assert len(spans) == 1
    a, b, slowest = spans[0]
    assert slowest == pytest.approx(0.3, abs=0.01)
    assert a < retime.stepped(RAMP, 1.3) < retime.stepped(RAMP, 2.0) < b


def test_work_size_keeps_the_aspect_and_never_upscales():
    assert retime.work_size(1920, 1080, 720) == (1280, 720)
    assert retime.work_size(2560, 1440, 1080) == (1920, 1080)
    assert retime.work_size(1280, 720, 1080) == (1280, 720)


# ------------------------------------------------------------ rendering

def _ffmpeg():
    from autostream.clips.tools import binary
    try:
        return binary("ffmpeg")
    except Exception:                                    # noqa: BLE001
        return None


def test_a_rendered_retime_has_every_frame_and_slow_motion_is_not_repeats(tmp_path):
    ff = _ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg")
    clip = tmp_path / "c.mp4"
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=60:duration=4",
                    "-pix_fmt", "yuv420p", str(clip)], check=True, creationflags=retime._NO_WINDOW)
    pieces = [(0.0, 0.5, 1.0), (0.5, 1.5, 0.3), (1.5, 2.0, 2.5)]
    frames = 2 * FPS
    out = retime.render(str(clip), 0.5, pieces, frames, tmp_path / "rt.mp4", kills=[0.25],
                        size=(320, 180), ff=ff, work=tmp_path / "w")
    raw = subprocess.run([ff, "-v", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True, creationflags=retime._NO_WINDOW).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, 180, 320).astype(np.int16)
    assert len(v) == frames
    # in the slow stretch (0.7-1.3 s, clear of the eases) no frame repeats the one before
    slow = v[int(0.75 * FPS):int(1.3 * FPS)]
    same = sum(1 for a, b in zip(slow, slow[1:]) if np.abs(a - b).mean() < 0.3)
    assert same == 0, f"{same} repeated frames in slow motion"
    assert not list((tmp_path / "w").glob("*.flow*")), "the optical-flow copies are left behind"


class _Held:
    """A file Windows will not let go of for the first `busy` deletes."""

    def __init__(self, busy: int):
        self.busy, self.gone = busy, False

    def unlink(self, missing_ok=False):
        if self.busy:
            self.busy -= 1
            raise PermissionError("in use by another process")
        self.gone = True


def test_a_flow_copy_still_held_is_removed_once_it_is_let_go(monkeypatch):
    monkeypatch.setattr(retime.time, "sleep", lambda s: None)
    f = _Held(busy=3)
    retime._remove(f)
    assert f.gone


def test_a_flow_copy_that_is_never_let_go_is_reported_not_raised(monkeypatch, caplog):
    monkeypatch.setattr(retime.time, "sleep", lambda s: None)
    f = _Held(busy=10_000)
    retime._remove(f, tries=3)
    assert not f.gone and "could not remove" in caplog.text
