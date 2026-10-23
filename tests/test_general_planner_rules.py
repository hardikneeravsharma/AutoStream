"""The general planner's rules, held for every style it plans, at three tempos.

Written from two reels the render gate refused on 2026-10-22 -- Hype on That Acid
(174 BPM: 117 s planned as 44 s, nine kills 2-50 s off the beat, six 7-10 s shots,
a white last frame) and Velocity on Skechers (100 BPM: five kills off the beat,
eight repeat-fight findings, a washed-out first kill, the last six shots
ping-ponging between two clips). Each rule here is one of those, made general:
synthetic songs and clips, no render, no network.
"""
from __future__ import annotations

import re
import statistics

import pytest

from autostream.clips import reelcheck, rulebook, studio
from autostream.clips.rulebook import Moment

from test_studio import Shape, _clips, _run

GENERAL = ["hype", "velocity", "chaos", "short", "story", "clean", "cinematic", "retro"]
TEMPOS = [90.0, 125.0, 174.0]
HOLE = (50.0, 56.5)            # a breakdown: no hit at all for 6.5 s


@pytest.fixture(scope="module")
def pile(tmp_path_factory):
    """Thirty single-kill clips and six long rounds whose kills come in every shape:
    two 2.3 s apart (inside the gate's repeat window), a double 0.8 s apart, and
    fights further on -- the material that made the repeat-fight and ping-pong reels."""
    r = tmp_path_factory.mktemp("pile") / "clips"
    rows, kills = [], []
    for i in range(30):
        start = 1000.0 + 100.0 * i
        rows.append({"start": start, "end": start + 12.0})
        kills.append(start + 6.0)
    for j in range(6):
        start = 10_000.0 + 200.0 * j
        rows.append({"start": start, "end": start + 40.0, "kills": 7})
        kills += [start + t for t in (4.0, 6.3, 12.0, 12.8, 20.0, 26.0, 33.0)]
    _run(r, "2026-10-20_2000_VALORANT", "VALORANT", rows, kills=kills)
    return r


def _song(bpm: float, hole=HOLE) -> Shape:
    """A song with a hit on every half beat -- except through a breakdown."""
    half = 30.0 / bpm
    hits = [2.0 + n * half for n in range(int(170.0 / half))]
    hits = [t for t in hits if not hole[0] < t < hole[1]]
    return Shape(bpm=bpm, seconds=180.0, phase=0.0, hits=hits)


def _planned(root, style: str, bpm: float, **kw):
    song = root.parent / "s.mp3"            # on disk, or normalise drops the song and its marks
    song.write_bytes(b"not really a song")
    proj, notes = studio.plan(_clips(root), style, shape=_song(bpm, **kw), song=str(song), fmt="vertical")
    got, derived, _ = studio.normalise(proj, root)
    st = studio.STYLE[style]
    found = reelcheck.plan_findings(got, derived, fast=bool(st.drop or st.fast_cuts))
    return proj, notes, got, derived, found


@pytest.mark.parametrize("bpm", TEMPOS)
@pytest.mark.parametrize("style", GENERAL)
def test_every_plan_passes_the_gate_by_construction(pile, style, bpm):
    """(a) (b) (c) (g): no kill off its mark, no shot past the planned length, no fight
    twice, no clip ping-ponging -- planned that way, not caught afterwards."""
    proj, notes, got, derived, found = _planned(pile, style, bpm)
    hard = [(f.code, f.message) for f in found if f.level == reelcheck.HARD]
    assert not hard, hard
    # (b) every shot's kill is on a mark: nothing "follows at its own length"
    placed = [r for r in derived["shots"] if not r["lead_in"]]
    assert derived["on_marks"] == len(placed), [r["drift"] for r in placed]
    # (a) the reel ends inside the length it was planned at, plus its closing tail
    fill = next((n for n in notes if "moments fill" in n), "")
    if fill:
        target = float(re.search(r"fill (\d+) s", fill).group(1))
        assert derived["length"] <= target + 1.5, (derived["length"], fill)
    # (g) no A B A B anywhere
    c = [s["clip"] for s in got["shots"]]
    assert not any(c[i] == c[i + 2] and c[i + 1] == c[i + 3] for i in range(len(c) - 3)), c


@pytest.mark.parametrize("style", GENERAL)
def test_every_kill_keeps_enough_detail_to_be_seen(pile, style):
    """(d): no stack of effects that, multiplied, washes the kill out (KILL_DETAIL)."""
    proj, *_ = _planned(pile, style, 125.0)
    soft = [(s["fx"], s["hero_fx"], s["speed"], s["camera"]) for s in proj["shots"]
            if studio.kill_detail(s) < studio.SHARP_FLOOR]
    assert not soft, soft


@pytest.mark.parametrize("style", ["hype", "chaos", "velocity"])
def test_a_fast_style_cuts_at_its_references_median_shot(pile, style):
    """(f): the kills land at the references' median shot, not their mean. Hype on That
    Acid laid 34 kills 1.38 s apart for a 3.1 s median shot against the references'
    0.63; the floor is a run-up and a landing (MIN_KILL_GAP_SECONDS)."""
    proj, notes, got, derived, _ = _planned(pile, style, 174.0)
    singles = sorted(s["duration"] for s in got["shots"] if len(s["kills"]) == 1)
    med = statistics.median(singles)
    want = studio.studio_refs.summary(studio.STYLE[style].refs)["median_shot"]
    assert rulebook.MIN_KILL_GAP_SECONDS - 0.15 <= med <= max(want, rulebook.MIN_KILL_GAP_SECONDS) + 0.4, singles
    cpm = 60.0 * len(got["shots"]) / derived["length"]
    ref = studio.studio_refs.summary(studio.STYLE[style].refs)["cuts_per_min"]
    assert cpm >= 0.8 * ref, (cpm, ref)


def test_fast_cuts_keep_the_variety_their_pools_define(pile):
    """(f): fast_rules takes out ramps, freezes, stacking and white-flash or slow cuts --
    and keeps every other kill effect and camera. It used to cut each pool to one entry."""
    st = studio.fast_rules(studio.STYLE["hype"])
    assert len(set(st.kill_pool)) > 3 and len(set(st.camera_pool)) > 1
    assert st.speed_pool == ("s00",) and st.energy == 0.0
    assert "t02" not in st.transition_pool and all(
        studio._cut_seconds(t) <= studio.FAST_CUT_SECONDS for t in st.transition_pool)
    assert not any(studio.fam(h) == "h02" for h in st.hero_pool)
    proj, *_ = _planned(pile, "hype", 174.0)
    assert len({s["fx"][0] for s in proj["shots"]}) == studio.MAX_KILL_FX
    assert len({s["camera"] for s in proj["shots"]}) > 1


def test_build_and_drop_keeps_its_own_single_mix():
    st = studio.fast_rules(studio.STYLE["drop"])
    assert st.transition_pool == ("t01",) and len(set(st.kill_pool)) == 1


def test_a_breakdown_with_no_hit_is_cut_on_its_beats(pile):
    """(a) (b): That Acid has no hit from 53.5 s to 59.6 s and the Hype reel held one
    shot over all of it. The kills go on the beat grid there instead."""
    proj, notes, got, derived, found = _planned(pile, "hype", 174.0)
    off = proj["song_offset"]
    marks = proj["song_marks"]
    inside = [m for m in marks if HOLE[0] < m < HOLE[1]]
    if marks[0] < HOLE[0] < marks[-1]:
        assert inside, marks
    assert max(s["duration"] for s in got["shots"]) <= reelcheck.FAST_MAX_SHOT
    assert off >= 0


def test_fill_holes_lays_beats_at_the_pace_and_clear_of_the_hits():
    beats = [i * 0.5 for i in range(40)]
    got = studio._fill_holes([1.0, 2.0, 9.0, 10.0], beats, gap=1.0, end=12.0)
    between = [t for t in got if 2.0 < t < 9.0]
    assert between and all(b - a >= 0.8 - 1e-6 for a, b in zip(got, got[1:])), got
    assert min(between) >= 2.8 - 1e-6 and max(between) <= 8.2 + 1e-6
    assert studio._fill_holes([1.0, 2.0], beats, gap=1.0, end=2.5) == [1.0, 2.0]


# ------------------------------------------------------------------ (c) one fight, one shot

def _m(kills, strength=2.0, group=0, seq=0):
    return Moment(clip={"path": "a.mp4"}, kills=list(kills), group=group, seq=seq, strength=strength)


def test_two_bursts_of_one_fight_become_one_shot():
    out = rulebook.one_shot_per_fight([_m([4.0]), _m([6.3], seq=1), _m([20.0], seq=2)])
    assert [m.kills for m in out] == [[4.0, 6.3], [20.0]]


def test_a_fight_too_long_for_one_shot_loses_its_weaker_burst():
    dropped = []
    out = rulebook.one_shot_per_fight([_m([4.0], 2.0), _m([6.5, 7.0], 5.0, seq=1), _m([9.4], 1.0, seq=2)],
                                      dropped, span=3.5)
    assert [m.kills for m in out] == [[4.0, 6.5, 7.0]]
    assert dropped == [("a.mp4", 9.4)]


def test_a_shot_holds_later_kills_only_as_far_as_the_pace_allows():
    dropped = []
    out = rulebook.hold_within([_m([3.0, 3.8, 6.4])], 1.5, dropped)
    assert out[0].kills == [3.0, 3.8] and dropped == [("a.mp4", 6.4)]


def _gate(shots):
    rows = [{"kill_reel": float(i), "start": float(i), "drift": 0.0} for i in range(len(shots))]
    return {f.code for f in reelcheck.plan_findings({"shots": shots}, {"shots": rows}, fast=False)}


def test_the_gate_does_not_call_a_double_kill_a_repeat():
    """Five of the eight repeat-fight findings on Velocity were a double kill in ONE shot."""
    one = {"clip": "a.mp4", "duration": 2.0, "kills": [39.2, 40.7]}
    other = {"clip": "a.mp4", "duration": 2.0, "kills": [13.8]}
    assert "repeat-fight" not in _gate([one, {"clip": "b.mp4", "duration": 1, "kills": [3]}, other])
    near = {"clip": "a.mp4", "duration": 2.0, "kills": [41.5]}
    assert "repeat-fight" in _gate([one, {"clip": "b.mp4", "duration": 1, "kills": [3]}, near])


# ------------------------------------------------------------------ (g) no ping-pong

def test_space_apart_breaks_a_b_a_b_and_keeps_each_clips_order():
    items = [("x", 0)] + [(c, t) for t in range(1, 4) for c in ("a", "b")] + [("c", 9), ("d", 9), ("e", 9)]
    out = rulebook.space_apart(items, key=lambda it: it[0], when=lambda it: it[1], fixed=(0,))
    c = [k for k, _ in out]
    assert out[0] == ("x", 0)
    assert all(c[i] != c[i + 1] for i in range(len(c) - 1)), c
    assert not any(c[i] == c[i + 2] and c[i + 1] == c[i + 3] for i in range(len(c) - 3)), c
    for k in "ab":
        assert [t for kk, t in out if kk == k] == [1, 2, 3]


# ------------------------------------------------------------------ (d) sharp kills

def test_the_washed_out_opener_is_made_sharp_without_a_freeze():
    """Velocity's first kill: s04 + k06 + h01 + c08 read 0.26 of a plain frame."""
    shot = {"clip": "a.mp4", "kill": 3.0, "kills": [3.0], "pre": 1.5, "duration": 2.4, "clip_seconds": 20.0,
            "speed": "s04", "fx": ["k06"], "hero": True, "hero_fx": ["h01"], "camera": "c08"}
    assert studio.kill_detail(shot) < studio.SHARP_FLOOR
    n = studio.sharp_kills([shot], {"kill": ["k06", "k01"], "hero": ["h01", "h02"]})
    assert n == 1 and studio.kill_detail(shot) >= studio.SHARP_FLOOR
    assert studio._freeze_of(shot) == 0.0


def test_a_drawer_the_player_chose_is_left_alone():
    shot = {"clip": "a.mp4", "kill": 3.0, "kills": [3.0], "pre": 1.0, "duration": 2.0, "clip_seconds": 20.0,
            "speed": "s04", "fx": ["k06"], "hero_fx": [], "camera": "c00"}
    studio.sharp_kills([shot], {"kill": ["k06", "k01"]}, free={"kill", "speed"})
    assert shot["fx"] == ["k06"] and shot["speed"] == "s04"


# ------------------------------------------------------------------ (e) no white burn

def test_the_flash_intro_and_ending_stop_short_of_white(pile):
    """Both reels opened on frames 88-100% over the gate's 245, and Hype ended on 255."""
    proj, _ = studio.plan(_clips(pile)[:12], "hype", shape=Shape(bpm=120.0))
    proj.update(intro="i08", outro="e05")
    got, derived, _ = studio.normalise(proj, pile)
    segs = studio.segments(got, derived, has_audio=lambda p: True, song_beats=derived["beats"])
    argv = studio.assemble_command(got, derived, segs, [studio.Path(f"{i}.mp4") for i in range(len(segs))],
                                   studio.Path("r.mp4"))
    graph = argv[argv.index("-filter_complex") + 1]
    assert not re.search(r"fade=out:[^,\[]*color=white", graph) and "brightness='max(0,0.85" not in graph
    assert graph.count("eq=contrast='1-(") == 2, graph
    # eq's luma is contrast*(y-128)+128+brightness*256: at the flash's peak a video-range
    # picture moves FLASH_PEAK of the way to white (235), never past it.
    a = studio.FLASH_PEAK
    for y in (16, 70, 128, 235):
        out = (1 - a) * (y - 128) + 128 + 256 * a * 107 / 256
        assert out == pytest.approx(y * (1 - a) + 235 * a, abs=0.01) and out <= 235 + 1e-6
    # a frame of the game's usual grey peaks well under the gate's white-ending line
    grey = (70 * (1 - a) + 235 * a - 16) * 255 / 219
    assert grey < reelcheck.WHITE_END
