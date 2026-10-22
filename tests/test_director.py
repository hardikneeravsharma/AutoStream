"""Follow the song: the set-up take into the drop, the drums after it.

Synthetic clips and a synthetic song, so every claim is arithmetic: the take's
last kill is ON the drop, every kill after it is on a cue, no clip plays twice,
a double is retimed to hit two cues, and each shot ends where the next one's
run-up starts.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import director, reel, rhythm, studio            # noqa: E402

BEAT = 60 / 174
DROP = 40.0


def song():
    """174 BPM, a kick every beat, a snare on the off-beats, sections around one drop."""
    beats = [0.1 + i * BEAT for i in range(int(80 / BEAT))]
    shape = reel.Shape(path=Path("song.m4a"), seconds=80.0, bpm=174.0, phase=0.1, downbeat_pos=0,
                       drop=DROP, drums_in=8.0, beats=beats, drops=[DROP])
    kick = [b for b in beats]
    snare = [b + BEAT / 2 for b in beats]
    layers = {"kick": rhythm.Layer("kick", kick, [0.9] * len(kick)),
              "snare": rhythm.Layer("snare", snare, [0.7] * len(snare)),
              "hats": rhythm.Layer("hats", [], [])}
    r = rhythm.Rhythm(seconds=80.0, beat=BEAT, phase=0.1, kick_phase=0.1, downbeat_pos=0, layers=layers,
                      cues=rhythm.cluster(layers), energy=[0.5] * 800,
                      sections=[rhythm.Section(0.0, 30.0, "verse", 0.5), rhythm.Section(30.0, DROP, "build", 0.6),
                                rhythm.Section(DROP, 62.0, "drop", 0.9), rhythm.Section(62.0, 80.0, "outro", 0.2)])
    return shape, r


def clip(name, kills, hs=None, seconds=12.0, labels=()):
    return {"path": f"C:/clips/{name}.mp4", "id": name, "name": name, "duration": seconds,
            "kills": kills, "hs": hs if hs is not None else [True] * len(kills), "labels": list(labels)}


def library(singles=30, doubles=6):
    out = [clip("clutch", [3.5, 5.0, 7.2], labels=["CLUTCH 1v3"], seconds=12.0)]
    out += [clip(f"one{i}", [3.5], hs=[i % 3 != 0]) for i in range(singles)]
    out += [clip(f"two{i}", [3.5, 3.5 + 0.55 + 0.05 * i]) for i in range(doubles)]
    return out


def test_the_setup_take_lands_its_last_kill_on_the_drop():
    shape, r = song()
    p = director.plan(library(), shape, r, seed=3)
    take = [s for s in p.shots if s["name"] == "clutch"]
    assert [s["kill"] for s in take] == [3.5, 5.0, 7.2]
    t = 0.0
    for s, m in zip(p.shots, p.marks):
        if s["name"] == "clutch":
            assert p.part[0] + t + s["pre"] == pytest.approx(m, abs=1e-3)
        t += s["duration"]
    assert p.marks[len(take) - 1] == pytest.approx(DROP, abs=1e-3)
    # the take is one piece of footage: each shot starts where the last one stopped
    for a, b in zip(take, take[1:]):
        assert a["kill"] - a["pre"] + a["duration"] == pytest.approx(b["kill"] - b["pre"], abs=1e-3)


def test_every_kill_after_the_drop_is_on_a_cue_and_on_its_mark():
    shape, r = song()
    p = director.plan(library(), shape, r, seed=1)
    cues = {round(c["t"], 3) for c in r.cues}
    t = 0.0
    for s, m in zip(p.shots, p.marks):
        reel_kill = p.part[0] + t + s["pre"]
        assert reel_kill == pytest.approx(m, abs=1e-3)
        if m > DROP + 0.01:
            assert round(m, 3) in cues
        t += s["duration"]


def test_the_flurry_keeps_the_pace_and_the_drop_is_held_not_stalled():
    """Reviewed on That Acid: 1.34 s after the drop's kill "costs momentum".
    Every kill after it -- a double's second one included -- comes within a
    second of the one before."""
    shape, r = song()
    for seed in range(1, 6):
        p = director.plan(library(singles=30, doubles=8), shape, r, seed=seed)
        after = [k for k in p.kills if k > DROP + 0.01]
        assert after, "nothing after the drop"
        gap = director.preferred_gap(BEAT)
        assert gap == pytest.approx(1.5 * BEAT)                 # 0.517 s at 174 BPM
        assert director.DROP_HOLD[0] * gap - 1e-6 <= after[0] - DROP <= director.MAX_GAP + 1e-6
        for a, b in zip(after, after[1:]):
            assert 0.8 * gap - 1e-6 <= b - a <= director.MAX_GAP + 1e-6, (seed, a, b)


def test_no_effect_hides_the_kill():
    """No blur on the kill (k21 blurred all seven frames of one) and one inversion at most."""
    shape, r = song()
    for seed in range(1, 6):
        fx = [f for s in director.plan(library(), shape, r, seed=seed).shots for f in s["fx"]]
        assert "k21" not in fx and "k14" not in fx
        assert fx.count(director.INVERT) <= 1


def test_no_clip_plays_twice_outside_its_take():
    """By file, not by fight: one LAST-ALIVE clip with two separate kills
    played at 17.4 s and again at 21.2 s."""
    shape, r = song()
    lib = library() + [clip("twice", [3.5, 11.0], seconds=14.0)]
    for seed in range(1, 6):
        p = director.plan(lib, shape, r, seed=seed)
        clips = [s["clip"] for s in p.shots if s["name"] != "clutch"]
        assert len(clips) == len(set(clips))


def test_a_double_is_one_shot_that_hits_two_cues():
    shape, r = song()
    p = director.plan(library(singles=10, doubles=8), shape, r, seed=4)
    runs = [s for s in p.shots if s.get("anchors")]
    assert runs, "no double was used as a run"
    cues = {round(c["t"], 3) for c in r.cues}
    t = 0.0
    for s in p.shots:
        if s.get("anchors"):
            (src, out), = s["anchors"]
            assert src == s["kills"][1]
            assert round(p.part[0] + t + out, 3) in cues
            rate = (s["kills"][1] - s["kill"]) / (out - s["pre"])
            assert director.PAIR_RATE[0] - 1e-6 <= rate <= director.PAIR_RATE[1] + 1e-6
        t += s["duration"]


def test_the_best_headshots_take_the_last_and_strongest_hits():
    shape, r = song()
    p = director.plan(library(), shape, r, seed=6)
    singles = [s for s in p.shots if s["name"].startswith("one")]
    # the last shot is a headshot (one0, one3 ... are not)
    last = p.shots[-1]
    if last["name"].startswith("one"):
        assert int(last["name"][3:]) % 3 != 0
    non_hs = [s for s in singles if int(s["name"][3:]) % 3 == 0]
    hs = [s for s in singles if int(s["name"][3:]) % 3 != 0]
    assert len(hs) >= len(non_hs)


def test_nothing_to_build_with_is_said_not_guessed():
    shape, r = song()
    with pytest.raises(ValueError, match="clutch"):
        director.plan([clip(f"one{i}", [3.5]) for i in range(10)], shape, r)


def test_studio_plans_it_and_the_timeline_agrees(tmp_path):
    """Through studio.plan and normalise: every kill on its mark, as derive() reads it."""
    shape, r = song()
    clips = library()
    for c in clips:
        p = tmp_path / Path(c["path"]).name
        p.write_bytes(b"x")
        c["path"] = str(p)
    shape.path = tmp_path / "song.m4a"
    shape.path.write_bytes(b"x")
    rhythm._MEMO.clear()
    orig = rhythm.for_song
    rhythm.for_song = lambda sh, cache_dir=None: r
    try:
        proj, notes = studio.plan(clips, "montage", shape=shape, song=str(shape.path), fmt="vertical",
                                  shape_it={"arrange": "sections"})
    finally:
        rhythm.for_song = orig
    assert proj["arrange"] == "sections"
    assert proj["song_drop"] == pytest.approx(DROP)
    got, derived, _ = studio.normalise(proj, tmp_path, probe=lambda p: 12.0)
    assert derived["on_marks"] == len(got["shots"])
    # the ending's fade starts after the last kill, never over it
    last_kill = max(derived["kills"])
    assert derived["length"] - derived["outro_fade"] >= last_kill + studio.OUTRO_AFTER_KILL - 1e-3


def test_a_kill_through_a_flash_is_not_cut_to(tmp_path, monkeypatch):
    """Two reviewed kills were filmed through a flash -- a flat beige or green
    screen -- and read as the edit blurring them. Measured clarity under
    CLEAR_MIN keeps a kill out of the reel."""
    shape, r = song()
    clips = library()
    for c in clips:
        p = tmp_path / Path(c["path"]).name
        p.write_bytes(b"x")
        c["path"] = str(p)
    shape.path = tmp_path / "song.m4a"
    shape.path.write_bytes(b"x")
    flashed = {str(tmp_path / f"one{i}.mp4") for i in range(0, 30, 2)}
    monkeypatch.setattr(rhythm, "for_song", lambda sh, cache_dir=None: r)
    monkeypatch.setattr(studio, "kill_clarity", lambda path, t: 20.0 if path in flashed else 900.0)
    monkeypatch.setattr(studio, "plan_checks", lambda: {})
    proj, notes = studio.plan(clips, "montage", shape=shape, song=str(shape.path), fmt="vertical",
                              checks=True, shape_it={"arrange": "sections"})
    used = {s["clip"] for s in proj["shots"]}
    assert used and not (used & flashed)
    assert any("washed out" in n for n in notes)


def test_a_hole_after_the_drop_widens_the_first_step_rather_than_stopping():
    """Notorious: the first cue came 4 ms before the hold's window opened and the
    next 1.36 s on, so the run never started and the take played on for twenty
    seconds. A wider first step is taken instead."""
    gap = 0.5357
    cues = [(57.861, 0.8), (58.561, 0.5), (59.289, 0.8), (60.0, 0.7)] + \
        [(60.0 + 0.5357 * k, 0.6) for k in range(1, 20)]
    got = director.targets(cues, 57.2023, 70.0, gap)
    assert got and got[0] == 57.861
    assert director.targets([], 57.2, 70.0, gap) == []


def test_build_and_drop_plans_itself_without_asking_for_an_order(tmp_path, monkeypatch):
    """The style used to get the director only with "Follow the song" also chosen
    under Order. Choose the style and nothing else, and it is what plans."""
    shape, r = song()
    clips = library()
    for c in clips:
        p = tmp_path / Path(c["path"]).name
        p.write_bytes(b"x")
        c["path"] = str(p)
    shape.path = tmp_path / "song.m4a"
    shape.path.write_bytes(b"x")
    monkeypatch.setattr(rhythm, "for_song", lambda sh, cache_dir=None: r)
    proj, notes = studio.plan(clips, "drop", shape=shape, song=str(shape.path), fmt="vertical")
    assert any("Builds on" in n for n in notes), notes
    assert proj["song_drop"] == pytest.approx(DROP)
    # a style that is not Build and drop is not taken over
    other, notes = studio.plan(clips, "montage", shape=shape, song=str(shape.path), fmt="vertical")
    assert not any("Builds on" in n for n in notes)
    # nothing to build with: it says so and plans the usual way rather than failing
    singles = [c for c in clips if c["name"].startswith("one")]
    proj, notes = studio.plan(singles, "drop", shape=shape, song=str(shape.path), fmt="vertical")
    assert proj["shots"] and any("usual build-and-drop way" in n for n in notes), notes


def test_the_reel_ends_on_a_bar_line_when_the_footage_allows():
    """F17: it stopped TAIL after its last kill, wherever in the bar that fell."""
    shape, r = song()
    lib = [dict(c, duration=30.0) for c in library()]
    p = director.plan(lib, shape, r, seed=3)
    end = p.part[1]
    downbeats = [b for i, b in enumerate(shape.beats) if i % 4 == 0]
    assert min(abs(end - b) for b in downbeats) < 0.01, end
    assert end - max(p.kills) >= director.END_AFTER - 1e-6


def test_a_file_named_2_kills_is_not_a_set_up_but_an_ace_is():
    """Every multi-kill file is named N-KILLS; that made each double a set-up."""
    two = director.bursts(clip("VALORANT_15_2-KILLS_r18", [3.5, 5.6]))[0]
    ace = director.bursts(clip("ACE", [36.0, 40.0, 42.0], seconds=46.0))[0]
    assert not director.is_setup(two) and director.is_setup(ace)


def test_the_clip_chosen_to_build_on_is_the_take():
    shape, r = song()
    lib = library() + [clip("mine", [4.0, 6.5], labels=["CLUTCH"], seconds=12.0)]
    p = director.plan(lib, shape, r, seed=3, build="C:/clips/mine.mp4")
    assert [s["name"] for s in p.shots[:2]] == ["mine", "mine"]
    assert p.marks[1] == pytest.approx(DROP, abs=1e-3)
    # a chosen clip with nothing to build on is said, and the best set-up is used
    q = director.plan(lib, shape, r, seed=3, build="C:/clips/one0.mp4")
    assert q.shots[0]["name"] == "clutch" and any("chosen to build on" in n for n in q.notes)


def test_doubles_too_far_apart_for_a_run_still_fill_the_hits():
    """48 clips of mostly 2-KILLS, kills 2-4 s apart: the reel ended 13 s early."""
    shape, r = song()
    lib = [clip("clutch", [3.5, 5.0, 7.2], labels=["CLUTCH 1v3"])]
    lib += [clip(f"far{i}", [3.5, 6.0 + 0.1 * i], seconds=14.0) for i in range(40)]
    p = director.plan(lib, shape, r, seed=1)
    assert len({s["clip"] for s in p.shots}) >= 25
    assert not any("ran out" in n for n in p.notes)
    # a single taken from a double never shows the other kill inside its shot
    for s in p.shots[3:]:
        other = [k for k in next(c for c in lib if c["path"] == s["clip"])["kills"] if abs(k - s["kill"]) > 1e-6]
        a, b = s["kill"] - s["pre"], s["kill"] - s["pre"] + s["duration"]
        if not s.get("anchors"):
            assert not any(a < k < b for k in other), s


def test_an_untouched_part_is_a_length_not_an_end():
    """The page's own 30 s part, drawn 15 s before the drop, made a 22 s reel of an ACE
    whose take needs 9 s: the reel starts where the take does and still runs 30 s."""
    shape, r = song()
    part = (DROP - 15.0, DROP + 15.0)
    fixed = director.plan(library(), shape, r, seed=3, part=part)
    loose = director.plan(library(), shape, r, seed=3, part=part, loose=True)
    assert fixed.part[1] <= part[1] + 2.0                     # a chosen part is where it ends
    assert loose.part[0] > part[0] + 5.0                      # the take starts late in both
    assert loose.part[1] - loose.part[0] == pytest.approx(30.0, abs=2.5)
    assert loose.part[1] - loose.part[0] > fixed.part[1] - fixed.part[0] + 4.0


def test_a_chosen_build_clip_works_when_nothing_else_is_a_set_up():
    shape, r = song()
    lib = [clip(f"one{i}", [3.5]) for i in range(30)] + [clip("pair", [4.0, 6.0], seconds=12.0)]
    p = director.plan(lib, shape, r, seed=2, build="C:/clips/pair.mp4")
    assert p.shots[0]["name"] == "pair"


def test_a_chosen_ace_plays_all_five_kills_with_the_wait_cut_out():
    """Reported: "I selected the ACE clip but it still showed only 3 kills out of it". The
    fourth kill came 13 s after the third, so the round was split in two fights."""
    shape, r = song()
    ace = clip("ACE", [36.0, 40.0, 42.0, 55.018, 57.352], hs=[False] * 5, seconds=69.6)
    lib = library() + [ace]
    p = director.plan(lib, shape, r, seed=1, build=ace["path"])
    take = [s for s in p.shots if s["name"] == "ACE"]
    assert [s["kill"] for s in take] == [36.0, 40.0, 42.0, 55.018, 57.352]
    assert p.marks[len(take) - 1] == pytest.approx(DROP, abs=1e-3)
    # every kill where its mark says, the jump included
    t = 0.0
    for s, m in zip(p.shots, p.marks):
        assert p.part[0] + t + s["pre"] == pytest.approx(m, abs=1e-3)
        t += s["duration"]
    # the 13 s wait is shown as the jump's two ends, not played
    gap = p.marks[3] - p.marks[2]
    assert gap == pytest.approx(director.JUMP_AFTER + director.JUMP_BEFORE, abs=1e-3)
    assert take[2]["kill"] - take[2]["pre"] + take[2]["duration"] == pytest.approx(42.0 + director.JUMP_AFTER, abs=1e-3)
    assert any("cut out" in n for n in p.notes)


def test_an_ace_named_clip_is_one_round_even_unchosen():
    shape, r = song()
    ace = clip("VALORANT_03_ACE_r9", [10.0, 12.0, 20.0, 22.0, 23.0], hs=[False] * 5, seconds=30.0)
    p = director.plan(library() + [ace], shape, r, seed=0)
    assert [s["name"] for s in p.shots].count("VALORANT_03_ACE_r9") == 5


def test_the_flurry_takes_an_anchor_every_four_to_six_kills():
    """Reviewed on Lalala: a nearly uniform 0.46 s after the drop "becomes predictable". With
    a hit on every half beat, the run now takes a 0.69-0.92 s step every 4-6 fast kills."""
    gap = 0.5
    cues = [(40.0 + 0.25 * k, 0.6 + (0.2 if k % 4 == 0 else 0.0)) for k in range(1, 100)]
    T = director.targets(cues, 40.0, 64.0, gap)
    steps = [b - a for a, b in zip([40.0] + T, T)][1:]          # the drop's own hold aside
    lo, hi = director.ANCHOR_GAPS[0] * gap, max(director.ANCHOR_BEATS * gap, director.ANCHOR_GAPS[1] * gap)
    anchors = [i for i, d in enumerate(steps) if lo - 1e-6 <= d <= hi + 1e-6]
    assert len(anchors) >= 3, steps
    runs = [b - a - 1 for a, b in zip([-1] + anchors, anchors)]
    assert all(r <= director.ANCHOR_EVERY[1] + 1 for r in runs), (runs, steps)
    assert max(steps) <= director.MAX_GAP + 1e-6


def test_an_anchor_is_in_beats_and_only_onto_a_strong_hit():
    """The second review: 0.69-0.92 s is 1.5-2 beats at 130 BPM but 1.06-1.41 at 92. The
    anchor is now up to two beats, and only onto a hit at the 70th percentile of its bar."""
    gap, beat = 0.652, 0.652                                    # 92 BPM: the gap is one beat
    cues = [(40.0 + 0.326 * k, 0.9 if k % 4 == 0 else 0.4) for k in range(1, 120)]
    T = director.targets(cues, 40.0, 70.0, gap, beat=beat)
    steps = [b - a for a, b in zip([40.0] + T, T)][1:]
    strong = {round(t, 3) for t, s in cues if s >= 0.9}
    # a step past 1.6 gaps can only be an anchor: two beats here, longer than the old 0.92 s
    anchors = [(d, t) for d, t in zip(steps, T[1:]) if d > 1.6 * gap + 1e-6]
    assert anchors and all(d > 0.92 for d, _ in anchors), steps
    assert all(round(t, 3) in strong for d, t in anchors), anchors


def test_a_deathmatch_run_is_never_the_build():
    """Reported: 7- and 12-kill Deathmatch clips were offered as the build. A mode with no
    rounds (the match record says) is no build, and in Valorant neither is a clip with more
    kills than a round has enemies."""
    dm = dict(clip("VALORANT_01_7kills_6m45s_44s", [3.0, 5.0, 7.0, 9.0, 20.0, 22.0, 24.0], seconds=44.0),
              game="VALORANT", round=None)
    flagged = dict(clip("VALORANT_03_3kills_21m31s_9s", [2.0, 3.0, 4.5], seconds=9.0), game="VALORANT", respawn=True)
    ranked = dict(clip("VALORANT_04_3-KILLS_r6_12m", [2.0, 3.0, 4.5], seconds=9.0), game="VALORANT", round=6)
    assert not any(director.is_setup(b) for b in director.bursts(dm))
    assert not any(director.is_setup(b) for b in director.bursts(flagged))
    assert any(director.is_setup(b) for b in director.bursts(ranked))
    shape, r = song()
    p = director.plan(library() + [dm, flagged], shape, r, seed=3)
    assert p.shots[0]["name"] == "clutch"


def test_a_chosen_clutch_with_its_kills_far_apart_can_build():
    """Reported: a CLUTCH 1v4 chosen for the build, kills at 3.5, 4.0, 12.3 and 25.2 s, and the
    chip said Build and drop needs a clutch. The plan builds on it as one round; the check
    the chip makes is now the same."""
    c = dict(clip("VALORANT_01_CLUTCH-1v4_r15", [3.498, 3.961, 12.278, 25.211], seconds=33.0,
                  labels=["CLUTCH 1v4"]), game="VALORANT", round=15)
    assert not any(director.is_setup(b) for b in director.bursts(c))       # what the chip used to test
    assert director.can_build([c]) and director.can_build([c], c["path"])


def test_a_montage_holds_its_opening_then_cuts_on_the_drums_each_clip_once():
    """Montage's first review: 4.2/10 on the general planner -- a fixed 2.1 s cut, 30 shots from 10
    clips, the same fight twice, kills seconds off the beat. Its own plan: one strong kill held
    1-2 bars, then kills on cues about the unit apart, every clip once, every kill on its mark."""
    shape, r = song()
    p = director.plan_montage(library(), shape, r, part=(16.0, 52.0), seed=2)
    beat = BEAT
    assert director.montage_unit(beat) == pytest.approx(3 * beat)             # 1.03 s at 174 BPM
    assert director.montage_unit(0.48) == pytest.approx(0.96)                 # 2 beats at 125
    first = p.marks[0] - p.part[0]
    assert 4 * beat - 1e-3 <= first <= 8 * beat + 1e-3                        # held one to two bars
    assert len({s["clip"] for s in p.shots}) == len(p.shots)
    cues = {round(c["t"], 3) for c in r.cues}
    t = 0.0
    for s, m in zip(p.shots, p.marks):
        assert p.part[0] + t + s["pre"] == pytest.approx(m, abs=1e-3)
        if m > p.drop + 0.01:
            assert round(m, 3) in cues
        t += s["duration"]
    gaps = [b - a for a, b in zip(p.marks, p.marks[1:])]
    assert sorted(gaps)[len(gaps) // 2] == pytest.approx(3 * beat, abs=0.2)


def test_a_kill_read_twice_is_one_kill():
    """A 1v4's first kill was in the clip at 3.415 and 3.417 s: the take cut a 2 ms shot between
    them and the note said four kills where there were three."""
    c = clip("VALORANT_01_CLUTCH-1v4_r15", [3.415, 3.417, 5.8, 12.0], hs=[False, True, True, True], seconds=20.0,
             labels=["CLUTCH 1v4"])
    b = director.bursts(c)
    assert [x.kills for x in b] == [[3.415, 5.8], [12.0]] and b[0].hs[0] is True
    shape, r = song()
    p = director.plan(library() + [c], shape, r, seed=1, build=c["path"])
    take = [s for s in p.shots if s["name"] == c["name"]]
    assert len(take) == 3 and all(s["duration"] > 0.2 for s in take)
    assert "3 kills" in p.notes[0]
