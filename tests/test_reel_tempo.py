r"""The reel grid's tempo is searched on the grid, not taken from one autocorrelation lag.

JUST A BOY reads as 119.93 BPM from the lag and is 120.00; over three minutes
that is a grid that starts on the kicks and ends 75 ms off them. These build a
click track at a known tempo and hand `rigid_grid` a beat that is wrong by that
much, and measure where the grid's last line falls.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import beatsync as bs
from autostream.clips import reel


def clicks(bpm: float, seconds: float, offset: float = 0.13) -> np.ndarray:
    n = int(seconds * bs.SR)
    t = np.arange(n) / bs.SR
    beat = 60.0 / bpm
    since = (t - offset) % beat
    x = np.sin(2 * np.pi * 1400 * t) * np.exp(-since * 55.0)
    x += 0.35 * np.sin(2 * np.pi * 70 * t) * np.exp(-since * 25.0)
    x[t < offset] = 0.0
    return (0.5 * x + 0.01 * np.random.default_rng(0).standard_normal(n)).astype(np.float32)


def test_a_slightly_wrong_tempo_is_pulled_onto_the_clicks():
    seconds, bpm, offset = 180.0, 120.0, 0.13
    env = bs.onset_envelope(clicks(bpm, seconds, offset))
    fps = bs.SR / bs.HOP
    beat, phase = reel.rigid_grid(env, 60.0 / 119.93, fps)
    assert abs(60.0 / beat - bpm) < 0.01

    # The grid sits as far from the clicks at the end as at the start: no drift.
    # (Not zero at either: an onset frame is read where the window that holds
    # the click's rise is centred, a constant few frames that every line shares.)
    def off(line: float) -> float:
        return line - (offset + (60.0 / bpm) * round((line - offset) / (60.0 / bpm)))
    first = phase + beat * 2
    last = phase + beat * int((seconds - 1 - phase) / beat)
    assert abs(off(last) - off(first)) < 0.006
    # The old answer, the lag's 119.93 as it was, drifted far past that.
    assert abs(off(phase + (60 / 119.93) * 358) - off(phase + (60 / 119.93) * 2)) > 0.05


def test_the_tempo_the_lag_got_right_is_left_where_it_is():
    env = bs.onset_envelope(clicks(104.0, 60.0))
    beat, _ = reel.rigid_grid(env, 60.0 / 104.0, bs.SR / bs.HOP)
    assert abs(60.0 / beat - 104.0) < 0.01


def test_nothing_to_search_returns_what_it_was_given():
    assert reel.rigid_grid(np.zeros(4), 0.5, 86.0) == (0.5, 0.0)
