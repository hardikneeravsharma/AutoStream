"""Finding the tempo of a track, measured against tracks of known tempo.

577 lines of DSP with almost no tests. Rather than assert on the shape of the
code, these synthesise audio at a tempo we chose and check the app's own
analysis recovers it -- so the answer is a measurement.

WHAT THESE DELIBERATELY DO NOT TEST
    Tempo-octave ambiguity. A pattern of evenly-spaced, equally-loud hi-hats
    on every eighth genuinely repeats at the eighth as strongly as at the
    beat, and a human hearing it in isolation could not say which is "the
    tempo" either. Real music resolves that with accents. Asserting a
    particular answer on an ambiguous signal would pin down an arbitrary
    choice and call it correctness, so the patterns here are unambiguous.

WHAT THEY DO TEST, AND WHY IT FOUND A BUG
    The declared range is 70 to 180 bpm. Because a lag is a whole number of
    23 ms frames and both bounds were truncated with int(), the range actually
    searched was 73.8 to 184.6. A 70 bpm track could not be found at all and
    came back at 140; and a tempo above the declared maximum could be
    returned, which the rest of the module does not expect.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

np = pytest.importorskip("numpy", reason="the Clips page needs numpy anyway")

from autostream.clips import beatsync as bs  # noqa: E402

SR = bs.SR


def clicks(bpm: float, seconds: float = 30.0, noise: float = 0.0,
           seed: int = 0) -> np.ndarray:
    """One unambiguous thump per beat and nothing else.

    Nothing else on purpose: with a single event per beat, the beat period is
    the only period in the signal, so the right answer is not a matter of
    interpretation.
    """
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    x = np.zeros(n, dtype=np.float32)
    t = np.arange(int(SR * 0.09)) / SR
    hit = (np.sin(2 * np.pi * 62 * t) * np.exp(-28 * t)).astype(np.float32)
    hit += (0.35 * rng.standard_normal(len(t))
            * np.exp(-60 * t)).astype(np.float32)
    period = 60.0 / bpm
    at = 0.0
    while at < seconds:
        i = int(at * SR)
        if i + len(hit) < n:
            x[i:i + len(hit)] += hit
        at += period
    if noise:
        x += (noise * rng.standard_normal(n)).astype(np.float32)
    return x


def found(bpm: float, **kw) -> float:
    return bs.estimate_bpm(bs.onset_envelope(clicks(bpm, **kw)))


# ------------------------------------------------- the range it claims to cover

def test_the_search_can_actually_reach_both_declared_bounds():
    """Arithmetic, not behaviour: the bug was in two int() calls.

    A lag is a whole number of frames 23 ms apart. Truncating both bounds moved
    both inwards, so the module searched a narrower range than it documented
    and nothing said so.
    """
    fps = bs.SR / bs.HOP
    slowest_lag = fps * 60.0 / bs.BPM_MIN
    fastest_lag = fps * 60.0 / bs.BPM_MAX

    # The module's OWN answer, not the arithmetic repeated here. A test that
    # recomputes the bounds agrees with itself whatever the module does, which
    # is how a test ends up decorative.
    lo, hi = bs.search_lags(4096)

    assert lo <= fastest_lag <= hi - 1, (
        f"{bs.BPM_MAX} bpm needs lag {fastest_lag:.2f}, outside {lo}..{hi - 1}")
    assert lo <= slowest_lag <= hi - 1, (
        f"{bs.BPM_MIN} bpm needs lag {slowest_lag:.2f}, outside {lo}..{hi - 1}")


def test_the_search_range_is_never_empty_or_backwards():
    """Short envelopes still have to produce a usable slice."""
    for n in (0, 1, 2, 16, 40, 64, 4096):
        lo, hi = bs.search_lags(n)
        assert lo >= 1
        assert hi > lo, f"a {n}-frame envelope gave an empty range {lo}..{hi}"


def test_the_slowest_declared_tempo_is_actually_found():
    """It used to come back at 140.58 -- double, because 70 bpm's lag sat one
    frame past the end of the search."""
    assert found(bs.BPM_MIN) == pytest.approx(bs.BPM_MIN, abs=1.5)


def test_nothing_outside_the_declared_range_is_ever_returned():
    """The search looks one frame beyond each bound so the sub-frame
    refinement has neighbours. That must not widen what comes out."""
    for bpm in (bs.BPM_MIN, 100.0, bs.BPM_MAX):
        got = found(bpm)
        assert bs.BPM_MIN <= got <= bs.BPM_MAX, f"{bpm} bpm gave {got}"
    # ...including for something with no tempo at all.
    rng = np.random.default_rng(7)
    hiss = (0.05 * rng.standard_normal(SR * 20)).astype(np.float32)
    got = bs.estimate_bpm(bs.onset_envelope(hiss))
    assert got == 0.0 or bs.BPM_MIN <= got <= bs.BPM_MAX


@pytest.mark.parametrize("bpm", [70, 75, 90, 100, 110, 120, 128, 135,
                                 140, 150, 160, 174, 180])
def test_an_unambiguous_tempo_is_recovered(bpm):
    got = found(bpm)
    assert got == pytest.approx(bpm, abs=1.5), (
        f"asked for {bpm}, got {got:.2f}")


@pytest.mark.parametrize("bpm", [95, 128, 145, 172])
def test_a_tempo_survives_a_noisy_recording(bpm):
    got = found(bpm, noise=0.004, seed=bpm)
    assert got == pytest.approx(bpm, abs=1.5)


# ------------------------------------------------------------- the beat grid

@pytest.mark.parametrize("bpm", [90, 120, 128, 174])
def test_the_grid_lands_on_the_beats(bpm):
    """A grid is only useful if the cuts it produces land on the music.

    TWO SEPARATE TOLERANCES, BECAUSE THEY MEAN DIFFERENT THINGS.
        The MEAN is what decides whether cuts feel on the beat, and a frame is
        the floor: HOP is 512 samples at 22050 Hz, so the envelope is sampled
        every 23 ms and no grid built from it can be more precise than that.

        One line being further out is allowed, and is not a fault. The phase
        search picks whatever offset lands the whole grid on the most onset
        energy, and when the estimated tempo is a fraction of a bpm off, the
        best compromise across a thirty-second track is not the offset that
        fits the FIRST beat perfectly. Demanding otherwise would be demanding
        a worse grid.
    """
    x = clicks(bpm, seconds=30.0)
    env = bs.onset_envelope(x)
    grid = bs.beat_grid(env, bs.estimate_bpm(env))
    assert grid, "no grid at all"

    period = 60.0 / bpm
    frame = bs.HOP / bs.SR
    # The first sixteen beats only. Distance to the nearest TRUE beat mixes two
    # different things: how well the grid's phase is placed, and how far a
    # fraction of a bpm has drifted by the fortieth beat. Over four bars the
    # second is negligible, so what is left is the phase -- which is the thing
    # this test is about. The tempo itself is checked separately, above.
    off = [abs(g - round(g / period) * period) for g in grid[:16]]
    assert max(off) < frame * 3.5, (
        f"worst of the first 16 grid lines is {max(off) * 1000:.1f} ms off a "
        f"real beat ({max(off) / frame:.1f} frames)")
    assert sum(off) / len(off) < frame * 1.5, (
        f"the grid sits off the beat: mean {sum(off) / len(off) * 1000:.1f} ms")


def test_a_grid_is_refused_rather_than_invented():
    """Nothing to work with has to mean no reel, not a reel cut to noise."""
    assert bs.beat_grid(np.zeros(0, dtype=np.float32), 120.0) == []
    assert bs.beat_grid(np.ones(500, dtype=np.float32), 0.0) == []


def test_a_clip_too_short_to_analyse_says_so_instead_of_guessing():
    tiny = np.zeros(bs.WIN, dtype=np.float32)
    assert bs.onset_envelope(tiny).size == 0
    assert bs.estimate_bpm(bs.onset_envelope(tiny)) == 0.0
