r"""Kill accuracy and fast cuts (roadmap K1-K5).

All of it measured on one reel, headshot3 (Hype, 150 BPM, 30 shots), read frame by
frame against the source clips:

  K1  The time a clip is marked at is not the moment the kill is seen. The first frame
      of the game's kill emblem is: 0.4 s after the mark in one clip, 0.3 s BEFORE it
      in another. Read by eye on six clips, then scored: the glyph detector is within
      0.035 s on all six, and found a glyph for 83 of 90 sampled kills.
  K2  Fast cuts keep one transition, one kill effect and real speed.
  K3  A kill needs 0.4 s after it. apply_marks gave the next shot everything in the gap
      except 0.22 s: 14 of 30 shots had exactly that, under a crossfade.
  K4  Build slowly, then drop: the first kill EXACTLY on the drop.
  K5  Every caller makes the same checks the web page does.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import test_studio as T                                             # noqa: E402
from autostream.clips import killmark, studio                       # noqa: E402


@pytest.fixture
def clips_root(tmp_path):
    r = tmp_path / "clips"
    T._run(r, "2026-09-01_1200_VALORANT", "VALORANT",
           [{"start": 100.0 * i, "end": 100.0 * i + 12} for i in range(1, 25)],
           kills=[100.0 * i + 6 for i in range(1, 25)])
    return r


def _clips(root):
    return T._clips(root)


# ======================================================================== K1

def _series(n=120, base=2.0, at=60, level=20.0, around=4.0, around_at=None):
    centre = np.full(n, base)
    surround = np.full(n, 3.0)
    centre[at:] = level
    surround[at:] = around
    if around_at is not None:
        surround[around_at:] = 30.0
    return centre, surround


def test_the_glyph_is_found_on_the_frame_it_appears():
    c, a = _series(at=60)
    assert killmark.glyph_onsets(c, a) == [pytest.approx(60 / 60, abs=1 / 60)]


def test_a_camera_cut_is_not_a_glyph():
    """Scenery has edges too. A hard cut or a fast turn raises them everywhere, so a
    jump counts only when it is LOCAL -- stronger in the window than around it."""
    c, a = _series(at=60, level=20.0, around=19.0)
    assert killmark.glyph_onsets(c, a) == []


def test_a_flash_that_does_not_hold_is_not_a_glyph():
    c = np.full(120, 2.0)
    c[60:64] = 25.0                       # four frames, then gone
    assert killmark.glyph_onsets(c, np.full(120, 3.0)) == []


def test_a_small_bump_is_not_a_glyph():
    """The floor is measured: a glyph's first frame reads 13.7 to 22 on a baseline of
    1.5 to 5; a wall's own texture sits under it."""
    c, a = _series(at=60, base=2.0, level=8.0)
    assert killmark.glyph_onsets(c, a) == []


def test_a_false_trigger_does_not_swallow_the_real_glyph_behind_it():
    """The first version skipped 1.5 s after any hit, and on VALORANT_06 a bright edge
    at the centre 1.06 s before the kill swallowed the real glyph. A glyph that is not
    there fails the hold test, so the skip can be short."""
    c = np.full(240, 2.0)
    c[60:75] = 20.0                       # a false one that holds for 15 frames...
    c[75:100] = 2.0                       # ...and ends
    c[100:] = 22.0                        # the real glyph, 0.67 s later
    on = killmark.glyph_onsets(c, np.full(240, 3.0))
    assert any(abs(t - 100 / 60) < 0.05 for t in on), on


def test_no_emblem_means_no_answer_and_the_time_is_kept(tmp_path):
    assert killmark.appearance(tmp_path / "x.mp4", "Counter-Strike 2", 3.0) is None


def test_refine_moves_each_kill_onto_its_glyph_and_keeps_the_rest():
    clips = [{"path": "a.mp4", "game": "VALORANT", "kills": [3.5, 9.0]},
             {"path": "b.mp4", "game": "VALORANT", "kills": [3.5]}]
    seen = {("a.mp4", 3.5): 3.87, ("a.mp4", 9.0): None, ("b.mp4", 3.5): 5.0}   # b's is out of reach
    out, got = studio._refine_kills(clips, lambda p, g, t: seen[(p, t)])
    assert out[0]["kills"] == [3.87, 9.0]
    assert out[1]["kills"] == [3.5], "a glyph 1.5 s away is another kill's, not this one's"
    assert got == {"seen": 1, "total": 3, "moved": 1, "shifts": [0.37]}


def test_refine_keeps_the_headshot_readings_matched_to_their_kills():
    """The headshot filter matches readings to kills by time, so a moved kill must take
    its reading with it or a later step unmatches them."""
    clips = [{"path": "a.mp4", "game": "VALORANT", "kills": [3.5], "_hs_times": [3.5]}]
    out, _ = studio._refine_kills(clips, lambda p, g, t: 3.8)
    assert out[0]["kills"] == [3.8] and out[0]["_hs_times"] == [3.8]


def test_two_kills_never_share_one_emblem():
    """A 2-kill clip's 3.505 and 4.326 both read the emblem at 3.45, and the reel's kill
    counter ticked twice in one frame. The nearer kill takes it; the other keeps its time."""
    clips = [{"path": "a.mp4", "game": "VALORANT", "kills": [3.505, 4.326]}]
    out, got = studio._refine_kills(clips, lambda p, g, t: 3.45)
    assert out[0]["kills"] == [3.45, 4.326]
    assert got["seen"] == 1


def test_refine_survives_a_reader_that_throws():
    clips = [{"path": "a.mp4", "game": "VALORANT", "kills": [3.5]}]

    def boom(*a):
        raise RuntimeError("ffmpeg went away")
    out, got = studio._refine_kills(clips, boom)
    assert out[0]["kills"] == [3.5] and got["seen"] == 0


def test_a_plan_says_how_far_the_kills_moved(clips_root):
    proj, notes = studio.plan(_clips(clips_root), "montage", shape=T.Shape(bpm=100.0),
                              refine=lambda p, g, t: round(t + 0.2, 3))
    said = [n for n in notes if "first frame of the game's own kill emblem" in n]
    assert said and "+0.20 s" in said[0], notes
    # ...and the shots were cut around the NEW time.
    assert all(abs((s["kill"] % 1.0) - 0.2) < 0.02 or abs((s["kill"] % 1.0) - 0.2) > 0.98
               for s in proj["shots"]), [s["kill"] for s in proj["shots"]]


# ======================================================================== K5

def test_checks_are_the_four_the_web_page_makes(monkeypatch):
    from autostream import clips as clips_mod

    monkeypatch.setattr(clips_mod, "available", lambda: True)
    assert sorted(studio.plan_checks()) == ["confirm", "measure", "refine", "theirs"]
    monkeypatch.setattr(clips_mod, "available", lambda: False)
    assert studio.plan_checks() == {}, "no ffmpeg means no checks, as it always did"


def test_the_web_page_asks_for_the_checks_through_the_one_door():
    """It used to pass three of them by hand. A fourth added to the list in one place and
    not the other is how a reel built from a script came out cut from raw times."""
    from autostream import webui

    src = inspect.getsource(webui)
    i = src.index("proj, notes = studio.plan(chosen")
    call = src[i:src.index("shape_it=", i)]
    # on unless the page asked for a dry run (the guided maker's chips, which skip the slow footage checks)
    assert "checks=not body.get(\"dry\")" in call, call


def test_the_fit_planner_takes_the_same_arguments_as_the_ordinary_one():
    from autostream.clips import arrange_fit

    for name in ("refine", "checks"):
        assert name in inspect.signature(arrange_fit.plan).parameters, name
        assert name in inspect.signature(studio.plan).parameters, name


# ======================================================================== K2

@pytest.mark.parametrize("style", ["hype", "chaos", "fasthead"])
def test_a_fast_style_on_a_fast_song_keeps_real_speed_and_one_effect_a_kill(clips_root, style):
    """K2, as revised 2026-10-23: real speed, one effect a kill, no white-flash or slow
    cut -- and the rest of the style's variety KEPT. Cutting every pool to its first
    entry made a Hype reel of That Acid 34 shots of one zoom punch, one camera and one
    hard cut."""
    proj, notes = studio.plan(_clips(clips_root), style, shape=T.Shape(bpm=150.0))
    shots = proj["shots"]
    trans = {s["transition"] for s in shots}
    assert "t02" not in trans and len(trans - {"t01"}) <= 1, trans
    assert all(studio._cut_seconds(t) <= studio.FAST_CUT_SECONDS for t in trans), trans
    # One effect a kill -- beside the style's signature (Hype's shake), which every
    # kill carries on top (studio.signature_fx).
    sig = {studio.fam(p) for p in studio.STYLE[style].signature}
    assert all(len([f for f in s["fx"] if studio.fam(f) not in sig]) <= 1 for s in shots), [s["fx"] for s in shots]
    assert {s["speed"] for s in shots} == {"s00"}
    assert any("fast-cut style" in n for n in notes), notes
    st = studio.STYLE[style]
    if len(set(st.kill_pool)) > 1:
        # The variety the pools define survives: two kill effects (calm_mix's cap),
        # and the cameras the style lists.
        assert len({f for s in shots for f in s["fx"] if studio.fam(f) not in sig}) == 2, [s["fx"] for s in shots]
        assert len(proj["pools"]["kill"]) > 1 and len(proj["pools"]["camera"]) > 1, proj["pools"]
    else:
        assert len({tuple(s["fx"]) for s in shots}) == 1, "Fast-paced headshot is one effect by design"


def test_the_climax_does_not_ramp_in_a_fast_reel(clips_root):
    """rulebook.climax rushes the best shot in and hangs on its kill (s04). On headshot3
    that was shot 20, in a reel built to have no ramp."""
    proj, _ = studio.plan(_clips(clips_root), "hype", shape=T.Shape(bpm=150.0))
    assert {s["speed"] for s in proj["shots"]} == {"s00"}


def test_a_slow_song_keeps_the_variety():
    """Variety stops helping when the cuts are fast. At 90 BPM they are not."""
    st = studio.STYLE["hype"]
    assert studio.fast_reel(st, 150.0) and studio.fast_reel(st, 110.0)
    assert not studio.fast_reel(st, 90.0)
    assert not studio.fast_reel(studio.STYLE["clean"], 150.0), "clean did not ask"


def test_a_slow_song_is_planned_exactly_as_before(clips_root):
    proj, notes = studio.plan(_clips(clips_root), "hype", shape=T.Shape(bpm=90.0))
    assert not any("fast-cut style" in n for n in notes)
    assert len({s["transition"] for s in proj["shots"]}) > 1


def test_a_choice_made_on_the_make_page_beats_the_rule(clips_root):
    """Applied before the template, so what the player picked still wins."""
    proj, _ = studio.plan(_clips(clips_root), "hype", shape=T.Shape(bpm=150.0),
                          template={"kill": "k11"})
    assert {tuple(s["fx"]) for s in proj["shots"]} == {("k11",)}


def test_no_flash_cuts_in_a_reel_that_asked_for_one_transition(clips_root):
    """A white flash on a share of the cuts is a second transition. (That is what t02 is.)"""
    proj, _ = studio.plan(_clips(clips_root), "chaos", shape=T.Shape(bpm=150.0))
    assert "t02" not in {s["transition"] for s in proj["shots"]}
    studio.vary(proj, "all", seed=3)
    assert "t02" not in {s["transition"] for s in proj["shots"]}, "Mix again brought them back"


# ======================================================================== K3

def _two_kills_apart(gap: float, style: str):
    shots = []
    for i in range(3):
        shots.append({"clip": f"c{i}.mp4", "clip_id": str(i), "name": f"c{i}", "clip_seconds": 20.0,
                      "clip_mtime": 0, "kills": [8.0], "kill": 8.0, "duration": 2.0, "pre": 1.0,
                      "speed": "s00", "fx": [], "hero": False, "hero_fx": [], "camera": "c00",
                      "transition": "t01", "tlen": 0.0, "caption": ""})
    proj = {"style": style, "beat": 0.4, "shots": shots, "song_offset": 0.0}
    studio.apply_marks(proj, [2.0, 2.0 + gap, 2.0 + 2 * gap])
    return proj["shots"]


def test_a_fast_reel_has_no_floor_of_its_own_any_more():
    """K3's 0.4 s after every kill in a fast reel is removed (asked 2026-10-17): at one
    kill a beat it left 0.17 s of run-up at 104 BPM. Every style has the same floor."""
    assert studio.after_floor({"style": "hype", "beat": 0.4}) == studio.SLOW_AFTER
    shots = _two_kills_apart(0.8, "hype")
    after = [s["duration"] - s["pre"] for s in shots[:-1]]
    assert min(after) >= studio.SLOW_AFTER - 1e-3, after


def test_every_style_keeps_the_floor_it_always_had():
    shots = _two_kills_apart(0.8, "clean")
    after = [s["duration"] - s["pre"] for s in shots[:-1]]
    assert min(after) == pytest.approx(studio.SLOW_AFTER, abs=1e-3), after


def test_a_cut_leads_its_kill_by_three_frames_when_the_shot_before_can_spare_them():
    """Reference editors cut a median 46 ms before the hit; the kill stays on it."""
    shots = _two_kills_apart(1.5, "clean")
    kills = [sum(s["duration"] for s in shots[:i]) + shots[i]["pre"] for i in range(3)]
    assert kills == pytest.approx([2.0, 3.5, 5.0], abs=1e-3)
    after = [s["duration"] - s["pre"] for s in shots[:-1]]
    assert min(after) >= studio.SLOW_AFTER - 1e-3
    assert shots[1]["pre"] == pytest.approx(1.0 + studio.CUT_LEAD, abs=1e-3)


def test_the_kills_do_not_move_when_the_aftermath_grows():
    """The aftermath comes out of the NEXT shot's lead-up, so every kill stays on its mark."""
    shots = _two_kills_apart(0.8, "hype")
    t, kills = 0.0, []
    for s in shots:
        kills.append(round(t + s["pre"], 3))
        t += s["duration"]
    assert kills[1] - kills[0] == pytest.approx(0.8, abs=1e-2)
    assert kills[2] - kills[1] == pytest.approx(0.8, abs=1e-2)


# ======================================================================== K4

HITS = [round(100.0 + 0.4 * i, 4) for i in range(400)]
STRENGTH = [1.0] * len(HITS)


def test_the_first_kill_after_the_build_is_exactly_on_the_drop():
    slots = studio.build_then_drop(HITS, STRENGTH, first=100.0, drop=111.13, count=14,
                                   beat=0.4, gap=0.9, end=140.0)
    assert 111.13 in slots, "headshot3 had its kill 0.36 s after the drop: the drop is not on a hit"


def test_the_build_is_slower_than_what_follows():
    slots = studio.build_then_drop(HITS, STRENGTH, first=100.0, drop=111.2, count=16,
                                   beat=0.4, gap=0.9, end=140.0)
    before = np.diff([t for t in slots if t <= 111.2 + 1e-6])
    after = np.diff([t for t in slots if t >= 111.2 - 1e-6])
    assert before.mean() >= studio.BUILD_BEATS * 0.4 * 0.9, before
    assert after.mean() < before.mean()


def test_the_drop_is_the_one_inside_the_part_not_the_biggest_in_the_song():
    """headshot3 plays 2:29-3:31; the song's biggest drop is at 4:33. The reel never reached
    it, so it had no build and no drop at all."""
    g = studio.Grid(beat=0.4, drop=273.5, drops=[31.25, 108.5, 172.25, 270.75, 326.25])
    assert studio.drop_in(g, 161.0, 202.0) == 172.25
    assert studio.drop_in(g, 100.0, 120.0) == 108.5
    assert studio.drop_in(g, 200.0, 240.0) is None, "no drop in that stretch is a fact, not a guess"


def test_a_drop_too_close_to_the_start_has_no_build_to_speak_of():
    g = studio.Grid(beat=0.4, drops=[162.0])
    assert studio.drop_in(g, 161.0, 202.0) is None


def test_a_fast_reel_over_a_chosen_part_lands_a_kill_on_the_drop(clips_root):
    hits = [round(0.4 * i, 4) for i in range(1, 280)]
    shape = T.Shape(bpm=150.0, seconds=120.0, phase=0.0, hits=hits)
    shape.drops = [40.1]
    shape.drop = 40.1
    proj, _ = studio.plan(_clips(clips_root), "hype", shape=shape, song="x.m4a", part=(28.8, 70.0))
    if proj.get("song_drop") is None:
        pytest.skip("this song stand-in is not a file the planner will keep")
    assert proj["song_drop"] == pytest.approx(40.1)
    kills = [s["pre"] for s in proj["shots"]]
    t, at = 0.0, []
    for s in proj["shots"]:
        at.append(t + s["pre"])
        t += s["duration"]
    want = 40.1 - proj["song_offset"]
    assert min(abs(k - want) for k in at) < 0.02, (want, at[:8])
