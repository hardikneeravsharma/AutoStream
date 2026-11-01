"""The story of a match, from who won each round (clips/match_story.py).

The Bind match of 2026-10-25 is the case: 4-8 at the half, six losses running to
4-11, seven of the next eight won to 11-12, the last round lost. A recap that never
says so missed the match (ChatGPT, grading it as a summary: momentum 5.5/10).
"""
from __future__ import annotations

from autostream.clips.match_story import Story

BIND = [c == "W" for c in "WLLWLLWLWLLLLLLWWWLWWWWL"]


def test_the_score_after_each_round_and_at_the_half():
    s = Story(BIND)
    assert s.final == (11, 13) and s.half_score == (4, 8) and s.rounds == 24
    assert s.before(16) == (4, 11) and s.after[22] == (11, 12)


def test_the_comeback_is_the_swing_and_a_one_round_lead_is_no_collapse():
    s = Story(BIND)
    assert s.swing() == (16, 23, True)
    # 1-0 to 4-11 is ten rounds of difference, but from a lead of one: not a collapse
    assert Story([True, True, True, True, False, False, False, False, False]).swing() == (5, 9, False)


def test_runs_are_three_or_more():
    assert Story(BIND).runs() == [(10, 15, False), (16, 18, True), (20, 23, True)]


def test_what_each_round_meant():
    s = Story(BIND)
    assert s.importance(24) == (1.0, "Final round")
    assert s.importance(20) == (0.8, "Match point")
    assert s.importance(16)[1] == "Ends the streak"
    assert s.importance(12) == (0.4, "Half-time")
    assert s.importance(3)[1] == "Falls behind"
    assert s.importance(7) == (0.0, "")
    assert s.importance(99) == (0.0, "")


def test_the_rounds_a_recap_must_show():
    assert Story(BIND).must_show() == [24, 23]


def test_the_match_in_one_sentence():
    assert Story(BIND).line() == "4-8 at the half, came back from 4-11 to 11-12, lost 11-13"
    assert Story([True] * 13).line().endswith("won 13-0")


def test_a_lead_changing_hands_is_named():
    # 1-0, 2-0, 2-1, 2-2, 2-3 (falls behind from level), 3-3, 4-3 (goes ahead), then on
    s = Story([True, True, False, False, False, True, True, False, False])
    assert s.importance(5)[1] == "Falls behind"
    assert s.importance(7)[1] == "Goes ahead"
    # a lead that flips in one round -- only possible from level -- never happens in
    # rounds, so "Takes the lead" needs a tie first: which is the "Goes ahead" case
    assert s.importance(9)[1] == "Final round"
