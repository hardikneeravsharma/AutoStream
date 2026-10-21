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


# ------------------------------------------------------------------ the clutch take (R9)

def _shot(clip, kill, name=None):
    return {"clip": clip, "name": name or Path(clip).stem, "kill": kill, "pre": 0.5,
            "duration": 1.0, "transition": "t02", "tlen": 0.2}


def test_a_clutch_gets_consecutive_slots_ending_on_the_drop_as_far_apart_as_its_kills():
    c = "C:/x/VALORANT_04_CLUTCH-1v3_r1_56m50s_42s.mp4"
    shots = [_shot("C:/x/a.mp4", 5.0), _shot(c, 27.87), _shot("C:/x/b.mp4", 6.0),
             _shot(c, 30.18), _shot(c, 34.37), _shot("C:/x/d.mp4", 3.0)]
    slots = [1.3, 3.6, 5.9, 9.375, 9.95, 10.53]
    order, got = studio.clutch_take(shots, slots, 9.375, 0.0)
    clutch = [k for k, i in enumerate(order) if shots[i]["clip"] == c]
    assert clutch == [1, 2, 3], order
    assert got[1:4] == pytest.approx([9.375 - 6.5, 9.375 - 4.19, 9.375], abs=1e-3)
    assert got[0] == 1.3 and got[4:] == [9.95, 10.53]
    assert all(shots[order[k]]["transition"] == "t01" for k in clutch)


def test_kills_that_would_fall_before_the_part_starts_are_left_to_the_order():
    c = "C:/x/VALORANT_01_CLUTCH-1v2_r13.mp4"
    shots = [_shot(c, 3.5), _shot(c, 24.0), _shot(c, 26.0), _shot("C:/x/a.mp4", 4.0)]
    order, got = studio.clutch_take(shots, [2.0, 9.375, 10.0, 11.0], 9.375, 0.0)
    take = [i for i in order if shots[i]["clip"] == c][-2:]
    assert [shots[i]["kill"] for i in take] == [24.0, 26.0]


def test_no_clutch_no_drop_slot_no_change():
    shots = [_shot("C:/x/a.mp4", 5.0), _shot("C:/x/a.mp4", 7.0)]
    assert studio.clutch_take(shots, [1.0, 9.375], 9.375, 0.0) == ([0, 1], [1.0, 9.375])
    c = "C:/x/CLUTCH.mp4"
    shots = [_shot(c, 5.0), _shot(c, 7.0)]
    assert studio.clutch_take(shots, [1.0, 2.0], 9.375, 0.0) == ([0, 1], [1.0, 2.0])


def test_headshots_only_keeps_a_clutch_whole():
    clips = [{"path": "C:/x/VALORANT_04_CLUTCH-1v3.mp4", "kills": [28.0, 30.3, 34.5], "hs": [True, True, False]},
             {"path": "C:/x/VALORANT_05_3-KILLS.mp4", "kills": [3.0, 5.0], "hs": [True, False]}]
    kept, none, dropped = studio._headshots_only(clips)
    assert kept[0]["kills"] == [28.0, 30.3, 34.5]
    assert kept[1]["kills"] == [3.0] and dropped == 1


def test_the_main_drop_is_the_entrance_whose_bass_stays():
    """Ashke: a few bass hits at 20.5 s stepped up further than the drop at 58.0 s, and were
    gone two seconds later; the reel's ACE landed on them and not on the drop."""
    import numpy as np
    from autostream.clips import beatsync as bs
    sr = bs.SR
    t = np.arange(int(70 * sr)) / sr
    rng = np.random.default_rng(3)
    hats = np.diff(rng.normal(0, 0.05, t.size), prepend=0)                  # the beat, all the way
    bass = np.sin(2 * np.pi * 55 * t)
    hits = ((t >= 20) & (t < 22.5)) * 0.9 + (t >= 45) * 0.6                  # a burst, then a drop that stays
    x = (hats + bass * hits).astype(np.float32)
    got = [e for e in bs.find_entrances(x) if e["ok"]]
    near = lambda s: next(e for e in got if abs(e["t"] - s) <= 1.0)       # noqa: E731
    burst, drop = near(20), near(45)
    assert burst["stay"] < bs.STAY_MIN <= drop["stay"]
    assert burst["bass_step"] > drop["bass_step"]                          # the old rule took the burst
    assert got[reel.main_entrance(got)] is drop
    assert reel.main_entrance([{"t": 1.0, "bass_step": 20.0}]) == 0       # an entrance read before stay was
