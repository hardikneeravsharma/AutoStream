r"""A rigid beat grid, for a style whose effects key off the beat and not a kill.

Everything else in `beatsync` serves a montage: it finds where the music
actually hits and snaps cuts to it, which is right when a cut has to land on a
transient. A beat ENGINE wants the opposite -- an even grid that never drifts,
because its expressions are `mod(t, BEAT)` and any wobble shows as a stutter
twice a second for the length of the reel.

These synthesise audio at a tempo and a drop we chose, so every answer is a
measurement rather than an assertion about the shape of the code. The one place
real music is named is in the comments, where the number came from a track whose
drop is known because a reel was cut to it by hand.

See docs/STYLE-FAST-PACED-HEADSHOT.md sections 3.1 to 3.3.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import beatsync as b


def click_track(bpm: float, seconds: float = 40.0, *, quiet_until: float = 0.0,
                quiet_gain: float = 0.08) -> np.ndarray:
    """A click on every beat, optionally quiet until `quiet_until` -- which is
    a drop, in the only sense this module cares about."""
    n = int(seconds * b.SR)
    t = np.arange(n) / b.SR
    beat = 60.0 / bpm
    since = t % beat
    x = np.sin(2 * np.pi * 1400 * t) * np.exp(-since * 55.0)
    x += 0.35 * np.sin(2 * np.pi * 70 * t) * np.exp(-since * 25.0)
    # A SUSTAINED BED under the clicks. Without it every other quarter-second
    # window lands in the decay and reads as silence, the level alternates by
    # 60 dB, and a "has it stayed up" test cannot mean anything -- which is
    # not what music does and would make this fixture test the fixture.
    rng = np.random.default_rng(7)
    x += 0.12 * rng.standard_normal(n) + 0.18 * np.sin(2 * np.pi * 110 * t)
    if quiet_until > 0:
        x = np.where(t < quiet_until, x * quiet_gain, x)
    return x.astype(np.float32)


# ---- snapping to a whole tempo -------------------------------------------


def test_a_tempo_within_noise_of_a_whole_number_becomes_it():
    """A track produced at exactly 120 gives 30 frames a beat at 60 fps, so a
    grid built on it is frame-exact for as long as the reel runs. A reading of
    120.0081 is that track plus noise, and 30.002 frames a beat drifts a whole
    frame every eight bars."""
    env = b.onset_envelope(click_track(120.0))
    assert b.whole_bpm(env, 120.0081) == 120.0


def test_a_tempo_that_is_not_nearly_whole_is_left_alone():
    """Measured over 18 real tracks: a span of 0.6 let 73.554 snap to 74,
    which is 0.6% and a quarter of a second across a forty-second reel -- half
    a beat, and visible."""
    env = b.onset_envelope(click_track(120.0))
    assert b.whole_bpm(env, 120.45) == pytest.approx(120.45)


def test_snapping_is_decided_by_the_music_not_by_the_distance():
    """The guard is the SCORE: a whole value is accepted only if the grid it
    implies is as salient as the measured one. A track genuinely at 119.9
    must not be dragged to 120 just because 120 is round."""
    env = b.onset_envelope(click_track(119.9, seconds=60.0))
    got = b.whole_bpm(env, 119.9)
    assert got in (119.9, 120.0)
    # ...and whatever it answers, it answers the same way twice.
    assert b.whole_bpm(env, 119.9) == got


def test_nonsense_in_nonsense_out_but_no_crash():
    assert b.whole_bpm(np.zeros(0), 120.0) == 120.0
    assert b.whole_bpm(b.onset_envelope(click_track(120.0)), 0.0) == 0.0


# ---- the drop, by loudness step -------------------------------------------


def test_the_drop_is_where_the_level_steps_up_and_stays_up():
    x = click_track(120.0, seconds=40.0, quiet_until=17.0)
    got = b.rms_drop(x, 40.0)
    assert got == pytest.approx(17.0, abs=b.RMS_WIN)


def test_a_single_loud_window_is_a_crash_and_not_a_drop():
    """It has to STAY up, measured against its own rise: a crash cymbal clears
    the threshold for one window and is gone."""
    x = click_track(120.0, seconds=40.0, quiet_until=17.0)
    # One loud quarter-second at 8s, then quiet again.
    i0, i1 = int(8.0 * b.SR), int(8.25 * b.SR)
    x = x.copy()
    x[i0:i1] *= 40.0
    assert b.rms_drop(x, 40.0) == pytest.approx(17.0, abs=b.RMS_WIN)


def test_a_track_that_never_steps_says_so():
    """None, not a guess. A reel built on a drop that is not there puts its
    hook in the wrong place for its whole length."""
    assert b.rms_drop(click_track(120.0, seconds=40.0), 40.0) is None


def test_too_short_to_judge_is_not_judged():
    assert b.rms_drop(click_track(120.0, seconds=1.0), 1.0) is None
    assert b.rms_drop(np.zeros(0, dtype=np.float32), 0.0) is None


# ---- the grid itself ------------------------------------------------------


def test_the_grid_is_even_to_the_microsecond():
    g = b.rigid_grid(120.0, 17.0, 40.0)
    gaps = np.diff(np.asarray(g))
    assert float(gaps.max() - gaps.min()) < 1e-6
    assert float(gaps.mean()) == pytest.approx(0.5, abs=1e-9)


def test_the_drop_lands_on_the_grid_and_not_beside_it():
    """Hi-hats on the off-beat pull the onset phase half a beat out: on the
    reference track the comb said offset 0.25s, which puts beats at 16.75 and
    17.25 -- and the drop is at 17.00. The drop wins, because it is the one
    moment a listener can point at."""
    g = b.rigid_grid(120.0, 17.0, 40.0)
    assert any(abs(t - 17.0) < 1e-6 for t in g)


def test_the_grid_starts_at_the_top_and_covers_the_track():
    g = b.rigid_grid(150.0, 12.3, 60.0)
    assert g[0] >= 0.0
    assert g[0] < 60.0 / 150.0 + 1e-9
    assert g[-1] <= 60.0


def test_a_grid_needs_a_tempo_and_a_length():
    assert b.rigid_grid(0.0, 1.0, 40.0) == []
    assert b.rigid_grid(120.0, 1.0, 0.0) == []
    assert b.rigid_grid(120.0, 1.0, 0.4) == []


def test_two_bars_before_the_drop_is_where_the_reel_starts():
    """Section 3.3: `song_start = drop - 2 bars`. On the reference that is
    17.0 - 4.0 = 13.0, so the bass lands at v-time 4.0 on the fifth cut."""
    bpm, drop = 120.0, 17.0
    assert drop - 8 * (60.0 / bpm) == pytest.approx(13.0)
