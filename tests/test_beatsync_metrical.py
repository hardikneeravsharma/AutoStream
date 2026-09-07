"""Telling a beat from a SUBDIVISION of it.

estimate_bpm already defended against the 2:1 octave error -- reporting half
the tempo because autocorrelation cannot tell a beat from every second beat --
and that is covered by click tracks every 2 BPM from 70 to 180.

It had no defence against 3:2 and 4:3. A track built on triplets puts a strong
voice on the DOTTED EIGHTH, three quarters of a beat, and autocorrelation
prefers that lag. Three quarters is not a factor of two, so every octave check
in the file passed it through.

FOUND ON REAL MUSIC, not by reading. SICKO MODE came back at 103.41 BPM where
the beat is 77.6, and a person tapping along produced gaps of 0.7725s and
3.09s -- exactly one beat and four beats at 77.6. Their thirteen taps sat
123ms off the 103.41 grid and 40ms off the 77.6 one.

The synthetic track below reproduces that: its raw autocorrelation peak lands
at 103.36 BPM, within 0.05 of what the real track produced.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import beatsync as bs                      # noqa: E402


def tick(x: np.ndarray, at: float, amp: float) -> None:
    i = int(at * bs.SR)
    n = np.arange(240)
    if i + 240 < len(x):
        x[i:i + 240] += (amp * np.exp(-n / 45.0)
                         * np.sin(2 * np.pi * 1400 * n / bs.SR)).astype(np.float32)


def triplet_track(bpm: float = 78.0, seconds: float = 30.0,
                  sub: float = 0.75, sub_gain: float = 0.85) -> np.ndarray:
    """A beat, plus a quieter voice on every `sub` of a beat.

    At sub=0.75 that is the dotted eighth -- a trap hi-hat -- and it is what
    makes the autocorrelation prefer a 4:3 relative of the real tempo.
    """
    x = np.zeros(int(seconds * bs.SR), dtype=np.float32)
    beat = 60.0 / bpm
    t = 0.0
    while t < seconds:
        tick(x, t, 1.0)
        t += beat
    t = 0.0
    while t < seconds:
        tick(x, t, sub_gain)
        t += beat * sub
    return x


def raw_peak(env: np.ndarray) -> float:
    """What the autocorrelation alone says, before any rescoring."""
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    lo, hi = bs.search_lags(len(ac))
    lag = lo + int(np.argmax(ac[lo:hi]))
    return 60.0 * (bs.SR / bs.HOP) / lag


def test_the_raw_peak_really_does_land_on_the_dotted_eighth():
    """Proof the fixture reproduces the bug rather than testing a strawman.
    103.4 is also what the real track produced, to within 0.05 BPM."""
    got = raw_peak(bs.onset_envelope(triplet_track()))
    assert 100.0 < got < 107.0, f"the fixture does not reproduce it: {got}"


@pytest.mark.parametrize("bpm", [74.0, 78.0, 84.0, 92.0])
def test_a_triplet_track_is_read_at_the_beat_not_the_subdivision(bpm):
    got = bs.estimate_bpm(bs.onset_envelope(triplet_track(bpm=bpm)))
    assert got == pytest.approx(bpm, abs=2.0), \
        f"read {got:.2f} instead of {bpm} -- the 4:3 error is back"


def test_the_beat_scores_better_than_its_subdivision():
    """The mechanism, separately from the answer. A subdivision grid puts half
    its points between onsets, so its weakest points are weak -- which is why
    the score is a percentile and not a mean."""
    env = bs.onset_envelope(triplet_track(bpm=78.0))
    beat = bs.grid_salience(env, 78.0)
    dotted = bs.grid_salience(env, 78.0 / 0.75)      # 104, the wrong answer
    assert beat > dotted, f"beat {beat:.1f} did not beat dotted {dotted:.1f}"


@pytest.mark.parametrize("bpm", [140.0, 160.0, 172.0])
def test_a_plain_click_track_is_not_halved_by_the_new_scoring(bpm):
    """THE REGRESSION THIS NEARLY CAUSED. On a click track every click is
    identical, so a half-tempo grid hits every other one and scores a dead
    heat -- measured at 0.962 to 1.002 of the true tempo's score. Without a
    tie-break that prefers the faster reading, seven tempos came back halved.
    """
    from tests.test_beatsync_tempo import clicks

    got = bs.estimate_bpm(bs.onset_envelope(clicks(bpm)))
    assert got == pytest.approx(bpm, abs=2.0), f"halved to {got:.2f}"


def test_a_subdivision_as_loud_as_the_beat_is_genuinely_ambiguous():
    """AN HONEST LIMIT, asserted so it is not mistaken for a fix.

    When the dotted eighth is exactly as loud as the beat there is nothing in
    the signal that distinguishes them, and this returns the subdivision. The
    test pins that it stays inside the declared range and does not crash --
    not that it is right, because there is no right answer available.
    """
    got = bs.estimate_bpm(bs.onset_envelope(triplet_track(sub_gain=1.0)))
    assert bs.BPM_MIN <= got <= bs.BPM_MAX


def test_nothing_outside_the_declared_range_survives_the_rescoring():
    """The relatives multiply the tempo, so they can leave the range."""
    for bpm in (70.0, 72.0, 175.0, 180.0):
        got = bs.estimate_bpm(bs.onset_envelope(triplet_track(bpm=bpm)))
        assert bs.BPM_MIN <= got <= bs.BPM_MAX, f"{bpm} -> {got}"
