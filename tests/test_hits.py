"""Where a song hits, and which hits carry a kill.

The detector was tuned against 662 kills the player marked by ear (see
autostream/clips/hits.py); these pin what that tuning settled on, on signals
built here so the suite needs no song and no ffmpeg.
"""
from __future__ import annotations

import numpy as np
import pytest

from autostream.clips import beatsync as bs, hits as H


def _kicks(times: list[float], seconds: float, level: float = 1.0,
           hz: float = 60.0, decay: float = 30.0) -> np.ndarray:
    """A quiet hiss with a decaying low tone at each time: a drum machine."""
    n = int(seconds * bs.SR)
    rng = np.random.default_rng(7)
    x = rng.normal(0.0, 0.01, n).astype(np.float32)
    t = np.arange(int(0.25 * bs.SR)) / bs.SR
    kick = (np.sin(2 * np.pi * hz * t) * np.exp(-decay * t)).astype(np.float32)
    for when in times:
        i = int(when * bs.SR)
        end = min(n, i + len(kick))
        x[i:end] += level * kick[:end - i]
    return x


def _near(got: list[float], want: list[float], tol: float = 0.03) -> int:
    return sum(1 for w in want if any(abs(g - w) <= tol for g in got))


# ------------------------------------------------------------------ the hits

def test_every_kick_is_a_hit_and_nothing_else_is():
    want = [1.0 + 0.5 * i for i in range(20)]
    hits, strength = H.bass_hits(_kicks(want, seconds=13.0))
    assert _near(hits, want) == len(want)
    assert len(hits) <= len(want) + 2, f"fired more than once per kick: {hits}"
    assert all(0.0 <= s <= 1.5 for s in strength)
    assert all(isinstance(t, float) for t in hits)


def test_a_quiet_verse_has_hits_of_its_own():
    """Judged against the six seconds around it, not the whole song: a verse
    kick is a hit even though a chorus kick is four times louder."""
    quiet = [1.0 + 0.5 * i for i in range(12)]
    loud = [9.0 + 0.5 * i for i in range(12)]
    x = _kicks(quiet, seconds=17.0, level=0.25) + _kicks(loud, seconds=17.0, level=1.0)
    hits, _ = H.bass_hits(x)
    assert _near(hits, quiet) >= len(quiet) - 1
    assert _near(hits, loud) >= len(loud) - 1


def test_a_big_hit_is_the_song_coming_back_in():
    on = [1.0 + 0.5 * i for i in range(8)]          # a first run
    back = [12.0 + 0.5 * i for i in range(8)]       # ...silence, then back in
    x = _kicks(on + back, seconds=18.0)
    hits, _ = H.bass_hits(x)
    big, rises = H.big_hits(x, hits)
    assert big, "nothing counted as the song coming back in"
    assert min(abs(b - 12.0) for b in big) <= 0.05
    assert all(t >= H.BIG_WINDOW for t in big), "a hit in the first seconds has no 'before'"
    assert len(big) <= 3 and len(rises) == len(big)


# ------------------------------------------------------------------ the kills

def test_hits_far_apart_each_carry_a_kill():
    hits = [1.0, 3.0, 5.0, 7.0]
    kills, accents = H.choose_kills(hits, target_gap=1.0)
    assert kills == hits and accents == []


def test_a_short_burst_is_cut_one_kill_each():
    hits = [1.0, 1.35, 1.7, 5.0]
    kills, accents = H.choose_kills(hits, target_gap=1.0)
    assert kills == hits and accents == []


def test_a_long_dense_run_is_thinned_and_the_rest_are_accents():
    hits = [1.0 + 0.25 * i for i in range(40)]
    kills, accents = H.choose_kills(hits, target_gap=1.0)
    gaps = np.diff(kills)
    assert 0.75 <= float(np.median(gaps)) <= 1.25
    assert sorted(kills + accents) == pytest.approx(hits)
    assert not set(kills) & set(accents)


def test_the_style_sets_how_rapid_the_kills_are():
    """The same song, cut for hype and for story: hype takes three times the
    kills, and neither lands one off a hit."""
    hits = [1.0 + 0.2 * i for i in range(150)]
    fast, fast_acc = H.choose_kills(hits, target_gap=60.0 / 53.8)     # hype
    slow, slow_acc = H.choose_kills(hits, target_gap=60.0 / 21.4)     # story
    assert len(fast) > len(slow) * 2
    assert float(np.median(np.diff(fast))) < float(np.median(np.diff(slow)))
    for got, acc in ((fast, fast_acc), (slow, slow_acc)):
        assert set(got) <= set(hits) and set(acc) <= set(hits)
        assert min(np.diff(got)) >= 0.25 - 1e-9


def test_no_shot_is_shorter_than_a_quarter_of_a_second():
    hits = [1.0 + 0.1 * i for i in range(10)] + [5.0]
    kills, accents = H.choose_kills(hits, target_gap=1.0)
    assert min(np.diff(kills)) >= 0.25 - 1e-9
    assert sorted(kills + accents) == pytest.approx(hits)


def test_a_song_with_no_hits_asks_for_nothing():
    assert H.choose_kills([]) == ([], [])
    assert H.bass_hits(np.zeros(100, dtype=np.float32)) == ([], [])


# ------------------------------------------------------- a song with a figure

def _hats(times: list[float], seconds: float, level: float = 1.0) -> np.ndarray:
    """Bright, quickly-decaying noise bursts: a hi-hat or a shaker."""
    n = int(seconds * bs.SR)
    rng = np.random.default_rng(3)
    x = np.zeros(n, dtype=np.float32)
    t = np.arange(int(0.12 * bs.SR)) / bs.SR
    tick = (rng.normal(0.0, 1.0, len(t)) * np.exp(-60.0 * t)).astype(np.float32)
    tick -= np.convolve(tick, np.ones(9) / 9, mode="same")      # keep the top end
    for when, loud in zip(times, [level] * len(times)):
        i = int(when * bs.SR)
        end = min(n, i + len(tick))
        x[i:end] += loud * tick[:end - i]
    return x


def _believer(seconds: float = 40.0, bpm: float = 125.0) -> np.ndarray:
    """A song like Believer: one hat a beat, the third of the bar loudest, and
    a bass that plays nothing in particular."""
    beat = 60.0 / bpm
    x = np.zeros(int(seconds * bs.SR), dtype=np.float32)
    for b in range(int(seconds / beat) - 1):
        at = 0.25 + b * beat
        x += _hats([at], seconds, level=1.0 if b % 4 == 2 else 0.35)
    rng = np.random.default_rng(11)
    kicks = sorted(rng.uniform(0.5, seconds - 1.0, int(seconds / 1.3)))
    return x + _kicks(list(kicks), seconds, level=0.6)


def test_a_bands_repeated_bar_figure_is_found():
    x = _believer()
    beat = 60.0 / 125.0
    hats = H.bar_figure(x, beat, *H.BANDS["hats"])[0]
    bass = H.bar_figure(x, beat, *H.BANDS["bass"])[0]
    assert hats > bass * H.FIGURE_OVER_BASS and hats >= H.FIGURE_CLEAR, (hats, bass)


def test_a_song_whose_pattern_is_not_its_bass_uses_the_band_that_has_one():
    """Believer's kick lands on 4% of the marks; its hats play the same bar
    over and over and the player marked beat three of every one."""
    x = _believer()
    beat = 60.0 / 125.0
    times, strength, kind = H.song_hits(x, beat, 40.0)
    assert kind == "hats figure"
    assert times and len(times) == len(strength)
    # one kill a bar, on the loud step, when the reel cuts at that pace
    kills, accents = H.choose_kills(times, strength, target_gap=4 * beat)
    gaps = np.diff(kills)
    assert abs(float(np.median(gaps)) - 4 * beat) < 0.25
    loud = [0.25 + b * beat for b in range(int(40.0 / beat) - 1) if b % 4 == 2]
    assert sum(1 for k in kills if any(abs(k - t) <= 0.06 for t in loud)) >= len(kills) * 0.7
    assert accents


def test_a_song_with_a_kick_stays_on_its_bass():
    x = _kicks([1.0 + 0.5 * i for i in range(70)], seconds=40.0)
    times, _s, kind = H.song_hits(x, 60.0 / 120.0, 40.0)
    assert kind == "bass hits" and times


def test_the_loudest_hit_in_the_window_carries_the_kill():
    """Not every Nth: an editor cuts on the hit that is loudest there. Measured
    on the marks, the loudest-in-window rule cut on 62% of them, every Nth 45%."""
    hits = [1.0 + 0.25 * i for i in range(40)]
    strength = [1.0 if i % 4 == 2 else 0.2 for i in range(40)]
    kills, accents = H.choose_kills(hits, strength, target_gap=1.0)
    assert all(any(abs(k - h) < 1e-9 and s > 0.5 for h, s in zip(hits, strength)) for k in kills)
    assert abs(float(np.median(np.diff(kills))) - 1.0) < 0.1
    assert sorted(kills + accents) == pytest.approx(hits)
