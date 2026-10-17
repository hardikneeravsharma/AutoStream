r"""Build and drop, as a reel cut by hand to a 21 s Short (Espresso, 104 BPM) is built.

Measured on that reel and on the app's own attempt at it (2026-10-17): the app read the
drop at 10.5 s against the 9.33 s the reference edit flashes on, played the song from
3.05 s, cut a kill every two beats with white dissolves and slow motion -- because the
style's drop logic sat behind a 110 BPM gate and a chosen part. These hold it to the
hand-cut reel's shape: the whole short song, the drop read off the bass entrance and
snapped to its hit, one kill a beat after it, half a beat each side, a flash on the drop.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import test_studio as T                                             # noqa: E402
from autostream.clips import reel, studio                           # noqa: E402

BEAT = 60.0 / 104.0


@pytest.fixture
def clips_root(tmp_path):
    r = tmp_path / "clips"
    T._run(r, "2026-09-01_1200_VALORANT", "VALORANT",
           [{"start": 100.0 * i, "end": 100.0 * i + 12} for i in range(1, 31)],
           kills=[100.0 * i + 6 for i in range(1, 31)])
    return r


def _espresso_like():
    """21.3 s at 104 BPM, a hit on every beat a few ms late, the drop's entrance read at 9.0."""
    beats = [0.099 + BEAT * i for i in range(36)]
    hits = [round(b + 0.04, 4) for b in beats]
    shape = T.Shape(bpm=104.0, seconds=21.3, phase=0.099, hits=hits)
    shape.beats = beats
    shape.hit_strength = [1.0 if abs(h - 3.40) < 0.2 else 0.5 for h in hits]
    shape.big = [h for h in hits if abs(h - 9.37) < 0.1]
    shape.drop = reel.snap_drop(9.0, hits, shape.hit_strength, shape.big)
    shape.drops = [shape.drop]
    return shape


def _kills(proj):
    t, out = 0.0, []
    for s in proj["shots"]:
        out.append(t + s["pre"] + proj["song_offset"])
        t += s["duration"]
    return out, t


# ------------------------------------------------------------------ the drop

def test_an_entrance_is_snapped_onto_the_big_hit_just_after_it():
    """find_entrances reads 0.25 s windows and walks back: Espresso's came out at 9.0 s,
    the hit the reference edit flashes on is at 9.375."""
    hits = [8.8, 9.375, 9.95]
    assert reel.snap_drop(9.0, hits, [0.5, 0.5, 0.9], big=[9.375]) == pytest.approx(9.375)


def test_with_no_big_hit_near_it_takes_the_strongest_hit_in_reach():
    assert reel.snap_drop(9.0, [8.9, 9.3, 9.6, 10.5], [0.4, 0.9, 0.6, 1.0], big=[]) == pytest.approx(9.3)


def test_an_entrance_with_no_hit_near_it_stays_where_it_was_read():
    assert reel.snap_drop(9.0, [2.0, 15.0], [1.0, 1.0], big=[]) == 9.0


# ------------------------------------------------------------------ the part

def test_a_short_song_plays_whole_when_no_part_was_chosen():
    g = studio.Grid.of(_espresso_like())
    assert studio.auto_part(g, studio.STYLE["montage"]) == (0.0, pytest.approx(21.3))


def test_build_and_drop_on_a_long_song_plays_its_build_into_the_first_drop():
    beat = 0.5
    g = studio.Grid(beat=beat, beats=[0.1 + beat * i for i in range(380)], seconds=195.7,
                    drops=[18.13, 46.0, 89.16], drop=18.13, hits=[0.12 + beat * i for i in range(380)])
    start, end = studio.auto_part(g, studio.STYLE["drop"])
    assert start == pytest.approx(18.13 - studio.DROP_LEAD_BARS * 4 * beat, abs=beat / 2)
    assert end == pytest.approx(46.0), "it runs on to the next drop when that is nearer"


def test_a_long_song_with_no_hits_keeps_the_planners_own_drop_path():
    g = studio.Grid(beat=0.5, beats=[0.5 * i for i in range(380)], seconds=195.7, drops=[18.13], drop=18.13)
    assert studio.auto_part(g, studio.STYLE["drop"]) is None


def test_other_styles_on_a_long_song_choose_their_own_start():
    g = studio.Grid(beat=0.5, beats=[0.5 * i for i in range(380)], seconds=195.7, drops=[18.13])
    assert studio.auto_part(g, studio.STYLE["montage"]) is None


def test_build_and_drop_cuts_fast_at_any_tempo():
    assert studio.fast_reel(studio.STYLE["drop"], 90.0)
    assert not studio.fast_reel(studio.STYLE["hype"], 104.0), "the gate stays for the others"


# ------------------------------------------------------------------ the reel

def test_espresso_plays_whole_with_a_flashed_kill_on_the_drop_and_one_a_beat_after(clips_root):
    shape = _espresso_like()
    proj, notes = studio.plan(T._clips(clips_root), "drop", shape=shape, song="x.m4a")
    if proj.get("song_drop") is None:
        pytest.skip("this song stand-in is not a file the planner will keep")
    assert proj["song_offset"] == pytest.approx(0.0)
    kills, length = _kills(proj)
    assert length > 19.0, "the reel runs to near the song's end"
    at_drop = [i for i, k in enumerate(kills) if abs(k - 9.375) < 0.02]
    assert at_drop, kills
    i = at_drop[0]
    assert studio.DROP_FLASH in proj["shots"][i]["fx"]
    # Only that kill: it was once counted as one of the reel's two kill effects and
    # spread to every other kill, and once given to the shot two along.
    assert sum(studio.DROP_FLASH in s["fx"] for s in proj["shots"]) == 1
    after = kills[i:i + 8]
    gaps = [b - a for a, b in zip(after, after[1:])]
    assert max(gaps) < 1.5 * BEAT and min(gaps) > 0.5 * BEAT, gaps
    assert {s["transition"] for s in proj["shots"]} == {"t01"}
    # Real speed through the drop; only the closer slows as it leaves (the style's outro).
    assert {s["speed"] for s in proj["shots"][i:-1]} == {"s00"}


def test_a_shot_after_the_drop_opens_about_half_a_beat_before_its_kill(clips_root):
    proj, _ = studio.plan(T._clips(clips_root), "drop", shape=_espresso_like(), song="x.m4a")
    if proj.get("song_drop") is None:
        pytest.skip("this song stand-in is not a file the planner will keep")
    kills, _ = _kills(proj)
    after = [s for s, k in zip(proj["shots"], kills) if k > 9.4][:6]
    for s in after:
        assert BEAT / 2 - 0.02 <= s["pre"] <= BEAT / 2 + studio.CUT_LEAD + 0.02, s["pre"]
