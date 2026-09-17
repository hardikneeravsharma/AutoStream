"""The editor's rulebook, one rule at a time.

Each test names the reel version whose review produced the rule; the numbers
in the docstrings are what was measured on that version. See
autostream/clips/rulebook.py.
"""
from __future__ import annotations

import pytest

from autostream.clips import rulebook as rb


def _clip(kills, duration=15.0, name="c"):
    return {"path": f"C:/clips/{name}.mp4", "name": name, "duration": duration, "kills": kills}


# ------------------------------------------------------------------ moments

def test_a_triple_kill_nine_seconds_long_is_three_moments_captioned_once():
    """v1 showed the first of three kills and captioned the shot TRIPLE KILL."""
    ms = rb.moments([_clip([3.5, 8.7, 12.1])], beat=0.5)
    assert [m.kills for m in ms] == [[3.5], [8.7], [12.1]]
    assert [m.caption for m in ms] == ["", "", "TRIPLE KILL"]
    assert [m.seq for m in ms] == [0, 1, 2]


def test_kills_close_together_share_one_shot_at_any_tempo():
    """At 134 BPM 2.5 beats is 1.1 s; kills 1.5 s apart still belong together (v10)."""
    ms = rb.moments([_clip([3.5, 5.0])], beat=60 / 134)
    assert len(ms) == 1 and ms[0].kills == [3.5, 5.0] and ms[0].caption == "DOUBLE KILL"


def test_a_kill_with_no_footage_before_it_is_not_a_moment():
    """v1's shot 7 opened on its kill: the clip's first kill was 0.12 s in."""
    ms = rb.moments([_clip([0.12, 6.0])], beat=0.5)
    assert [m.kills for m in ms] == [[6.0]]
    assert ms[0].caption == ""                  # one kill left to show is not a double


def test_the_reel_is_whole_phrases_long_enough_to_hold_the_clips():
    """Whole 8-bar phrases: as many as the picked clips need, up to the cap."""
    beat = 60 / 82.81
    phrase = rb.PHRASE_BARS * 4 * beat
    # More material than any reel may run: the longest whole phrases that fit.
    s = rb.phrase_seconds(beat, "landscape", available=300.0)
    assert s == pytest.approx(3 * phrase) and s <= rb.MAX_SECONDS["landscape"]
    assert rb.phrase_seconds(beat, "vertical", available=300.0) <= s
    # Enough for two phrases and a bit: the reel holds it all, rounded up.
    s2 = rb.phrase_seconds(beat, "landscape", available=2.2 * phrase)
    assert s2 == pytest.approx(3 * phrase)
    # Less than one phrase is as long as the material, and an asked-for length
    # is still the length asked for.
    assert rb.phrase_seconds(beat, "landscape", available=10.0) == 10.0
    assert rb.phrase_seconds(beat, "landscape", available=300.0, want=30.0) == pytest.approx(phrase)


def test_a_sequence_is_taken_whole_or_not_at_all():
    ms = rb.moments([_clip([3.5, 8.7, 12.1], name="a"), _clip([3.5], name="b")], beat=0.5)
    got = rb.select(ms, seconds=2.0, length_of=lambda m: 2.0)
    assert [m.clip["name"] for m in got] == ["a", "a", "a"]


def test_the_strongest_moment_is_the_climax_not_the_opener():
    clips = [_clip([3.5], name=f"s{i}") for i in range(4)] + [_clip([3.5, 4.0, 4.4], name="best")]
    ms = rb.moments(clips, beat=0.5)
    order = rb.order(ms)
    names = [m.clip["name"] for m in order]
    assert names[0] != "best" and names[-1] != "best"


# ------------------------------------------------------------------ action

def test_a_death_camera_is_dropped_and_captions_follow_what_is_left():
    """v2: a feed-read kill while the player lay dead; p90 frame change 4.9 against a median of 14."""
    clips = [_clip([3.5, 8.0], name="dm")] + [_clip([3.5], name=f"s{i}") for i in range(5)]
    ms = rb.moments(clips, beat=0.5)
    stats = {id(m): {"action": 14.0} for m in ms}
    dead = [m for m in ms if m.clip["name"] == "dm"][1]
    stats[id(dead)] = {"action": 4.9}
    keep, dropped = rb.drop_still(ms, stats)
    assert dropped == 1 and dead not in keep
    left = [m for m in keep if m.clip["name"] == "dm"]
    assert len(left) == 1 and left[0].caption == ""


def test_places_do_not_chain_two_maps_together():
    """v7: one in-between clip (0.66 from one map, 0.69 from the other) chained them."""
    a = [1.0, 0.0, 0.0]
    b = [0.34, 0.66, 0.0]
    c = [0.0, 1.0, 0.0]
    looks = {0: a, 1: b, 2: c}
    place = rb.places([0, 1, 2], looks)
    assert place[0] != place[2]


def test_the_middle_alternates_places():
    clips = [_clip([3.5], name=f"m{i}") for i in range(7)]
    ms = rb.moments(clips, beat=0.5)
    for i, m in enumerate(ms):
        m.strength = 10 - abs(3 - i)
    looks = {i: ([1.0, 0.0] if i % 2 == 0 or i in (1, 3) else [0.0, 1.0]) for i in range(7)}
    order = rb.order(ms, looks)
    middle = order[1:-1]
    same = sum(1 for x, y in zip(middle, middle[1:])
               if rb.look_similarity(looks[x.group], looks[y.group]) >= rb.LOOK_SAME)
    assert same < len(middle) - 1


# ------------------------------------------------------------------ pace

def test_quiet_music_gets_longer_shots_and_loud_music_shorter():
    assert rb.pace(0.5, 4) == 8
    assert rb.pace(1.0, 4) == 4
    assert rb.pace(1.3, 4) == 2


def test_energy_is_relative_to_the_song_itself():
    peaks = [0.2] * 100 + [0.8] * 900
    e = rb.energy_profile(peaks, seconds=100.0)
    assert e(0, 10) < 0.7 and e(50, 60) == pytest.approx(1.0)


def test_follow_ups_are_jump_cuts_and_the_closer_gets_a_bar():
    ms = rb.moments([_clip([3.5], name="a"), _clip([3.5, 8.7, 12.1], name="b"), _clip([4.0], name="c")],
                    beat=0.5)
    lens = rb.walk(ms, beat=0.5, energy=lambda a, b: 1.0, song_start=0.0, base=4, open_beats=4,
                   run_beats=1, pre_share=0.5, closer_post=4)
    follow = [l for m, l in zip(ms, lens) if m.seq > 0][:1]
    assert sum(follow[0]) == 2
    assert lens[-1][2] == 4


def test_a_hero_keeps_its_run_up_through_the_bar_nudge():
    """v9: the bar-line nudge ran after the hero floor and took a beat off the climax."""
    beat = 60 / 82.81
    ms = rb.moments([_clip([4.0], name=f"s{i}") for i in range(4)], beat=beat)
    for first_index in range(4):
        lens = rb.walk(ms, beat=beat, energy=lambda a, b: 1.0, song_start=0.0, base=2, open_beats=4,
                       run_beats=1, pre_share=0.5, heroes={2}, first_index=first_index)
        assert lens[2][0] * beat >= rb.HERO_RUN_SECONDS - 1e-6


def test_the_phrase_shapes_the_pace():
    assert rb.phrase_factor(0) > rb.phrase_factor(12) > rb.phrase_factor(28)


def test_a_middle_shot_never_holds_past_the_cap():
    beat = 60 / 162
    ms = rb.moments([_clip([6.0], name=f"s{i}") for i in range(4)], beat=beat)
    lens = rb.walk(ms, beat=beat, energy=lambda a, b: 0.3, song_start=0.0, base=4, open_beats=4,
                   run_beats=1, pre_share=0.9)
    for l in lens[1:-1]:
        assert sum(l) <= rb.shot_cap(4, beat)


# ------------------------------------------------------------------ effects

def _shots():
    return [{"clip": "a", "fx": ["k01", "k02"], "transition": "t01", "tlen": 0.0, "pre": 1.0,
             "duration": 2.0, "speed": "s04", "hero": False, "caption": ""},
            {"clip": "a", "fx": ["k03"], "transition": "t05", "tlen": 0.3, "pre": 0.5,
             "duration": 1.0, "speed": "s04", "hero": False, "caption": ""},
            {"clip": "b", "fx": ["k16"], "transition": "t02", "tlen": 0.2, "pre": 0.4,
             "duration": 1.0, "speed": "s02", "hero": False, "caption": ""},
            {"clip": "c", "fx": ["k01"], "transition": "t01", "tlen": 0.0, "pre": 1.0,
             "duration": 2.0, "speed": "s00", "hero": True, "caption": "ACE"}]


POOLS = {"kill": ["k01", "k02", "k03", "k06", "k16"], "transition": ["t01", "t02", "t05", "t06"]}


def test_one_effect_per_ordinary_kill_and_jump_cuts_are_plain():
    shots = _shots()
    rb.budget(shots, POOLS)
    assert len(shots[0]["fx"]) == 1
    assert shots[1]["transition"] == "t01" and not set(shots[1]["fx"]) & set(rb.BRIGHT_KILL)
    assert shots[1]["speed"] == "s00"


def test_light_never_doubles():
    """v3: a white-flash cut into a white-flash kill was a white frame."""
    shots = _shots()
    rb.budget(shots, POOLS)
    s = shots[2]
    assert not (s["transition"] in rb.BRIGHT_CUT and set(s["fx"]) & set(rb.BRIGHT_KILL))


def test_mixing_one_kind_changes_only_that_kind():
    shots = _shots()
    before = [(s["transition"], s["speed"]) for s in shots]
    rb.budget(shots, POOLS, only="kill")
    assert [(s["transition"], s["speed"]) for s in shots] == before


def test_saturation_is_trimmed_to_the_references():
    """v3 measured 0.411 against the references' 0.309 under the warm grade."""
    trim = rb.saturation_trim([0.31] * 10, "g02")
    assert 0.6 <= trim < 0.8
    assert rb.saturation_trim([0.31] * 10, "g07") == 1.0   # monochrome is left alone
    assert rb.saturation_trim([], "g02") == 1.0


def test_transitions_follow_the_music_and_the_places():
    shots = [{"clip": c, "fx": ["k01"], "transition": "t01", "tlen": 0.0, "pre": 1.0, "duration": 2.0}
             for c in ("a", "a", "b", "c", "d")]
    starts = [0, 4, 8, 32 + 3, 40]
    looks = {"a": [1.0, 0.0], "b": [0.0, 1.0], "c": [1.0, 0.0], "d": [0.0, 1.0]}
    rb.transitions(shots, starts, first_kill_beat=3, looks=looks, pools=POOLS)
    assert shots[1]["transition"] == "t01"               # a jump cut
    assert shots[3]["transition"] == "t05"               # opens a phrase
    assert shots[2]["transition"] in ("t06", "t01")


def test_only_the_climax_freezes():
    shots = [{"hero": True, "hero_fx": ["h02"], "speed": "s00"},
             {"hero": True, "hero_fx": ["h01"], "speed": "s00"}]
    rb.climax(shots, [1.0, 5.0], {"hero": ["h01", "h02", "h05"]})
    assert "h02" not in shots[0]["hero_fx"] and "h02" in shots[1]["hero_fx"]
    assert shots[1]["speed"] == "s04"


def test_a_climax_without_run_up_footage_slows_in_instead_of_rushing():
    shots = [{"hero": True, "hero_fx": [], "speed": "s00"}]
    rb.climax(shots, [1.0], {"hero": ["h01"]}, speed_ok=lambda s, sp: False)
    assert shots[0]["speed"] == "s02"


# ------------------------------------------------------------------ open and close

def test_a_quiet_intro_gets_a_build():
    beat = 60 / 82.81
    quiet = lambda a, b: 0.3 if b <= 24 else 1.0
    assert rb.wants_build(quiet, 23.7, beat)
    assert not rb.wants_build(lambda a, b: 1.0, 23.7, beat)
    assert not rb.wants_build(quiet, None, beat)


def test_no_drums_in_means_the_first_loud_phrase():
    """v12 started a short on the first beat of a sixteen-second quiet intro."""
    beat = 60 / 162
    beats = [i * beat for i in range(800)]
    e = lambda a, b: 0.4 if a < 16.0 else 1.0
    t = rb.first_loud(e, beats, beat)
    assert 16.0 <= t < 16.0 + 4 * beat


def test_the_ending_fade_is_most_of_a_bar():
    assert rb.ending_fade(60 / 82.81) == pytest.approx(2.174, abs=1e-3)
    assert 1.2 <= rb.ending_fade(60 / 180) <= 2.2
