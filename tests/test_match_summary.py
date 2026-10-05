r"""A Counter-Strike match as one video, with the dead time taken out.

GROUND TRUTH, WHICH IS WHY THIS IS PROVABLE WITHOUT FOOTAGE.
`rounds.from_demo()` gives exact round starts, ends, scores and labels out of
the `.dem` -- not read off a screen and not inferred -- so everything here is
arithmetic over known numbers.

What is decided here is which seconds to keep and what to call each chapter.
The cutting itself is `cutter.master_segments`, which the Marvel Rivals
summary already uses and which is proved against real files there: this adds
no new way to touch ffmpeg, on purpose.
"""
from __future__ import annotations

import pytest

from autostream.clips import match_summary as ms


class R:
    """What a round looks like to this module. See clips/rounds.Round."""

    def __init__(self, number, started, ended, *, won=None, my_kills=0,
                 my_deaths=0, labels=None, score_after=None):
        self.number = number
        self.started = started
        self.ended = ended
        self.won = won
        self.my_kills = my_kills
        self.my_deaths = my_deaths
        self.labels = labels or []
        self.score_after = score_after


def _match(n=6, every=120.0, length=90.0):
    """`n` rounds, each `length` long, starting `every` seconds apart."""
    out = []
    for i in range(n):
        a = 100.0 + i * every
        out.append(R(i + 1, a, a + length, won=(i % 2 == 0),
                     my_kills=i % 4, score_after=(i // 2 + 1, i // 2)))
    return out


# ----------------------------------------------------- which seconds to keep

def test_the_dead_time_between_rounds_comes_out():
    """THE WHOLE POINT. Six rounds 120s apart, 90s each: the half-minute of
    buy time and walking between them is what a summary exists to remove."""
    rounds = _match(6, every=120.0, length=90.0)
    got = ms.spans(rounds)
    covered = rounds[-1].ended - rounds[0].started
    assert ms.total(got) < covered, "nothing was cut"
    # Each round keeps its own run-up and tail and nothing else.
    assert len(got) == 6
    for span, r in zip(got, rounds):
        assert span[0] == pytest.approx(r.started - ms.PRE)
        assert span[1] == pytest.approx(r.ended + ms.POST)


def test_rounds_that_nearly_touch_become_one_span():
    """A hard cut every round in a match that ran without a break is
    twenty-four joins where the footage was already continuous, and each one
    costs a keyframe and shows."""
    rounds = [R(1, 100.0, 190.0), R(2, 195.0, 280.0), R(3, 600.0, 690.0)]
    got = ms.spans(rounds)
    assert len(got) == 2, got
    assert got[0] == pytest.approx((94.0, 285.0))


def test_the_order_is_the_match_and_not_the_ranking():
    """A summary is the match as it happened. Ranking belongs to clips, where
    the viewer is choosing one."""
    rounds = [R(3, 500.0, 560.0, my_kills=5, labels=["ACE"]),
              R(1, 100.0, 160.0, my_kills=0),
              R(2, 300.0, 360.0, my_kills=1)]
    got = ms.spans(rounds)
    assert [a for a, _b in got] == sorted(a for a, _b in got)
    assert got[0][0] < 200, "the ace was put first"


def test_it_never_asks_for_frames_before_the_file_starts():
    rounds = [R(1, 2.0, 40.0)]
    assert ms.spans(rounds)[0][0] == 0.0


def test_it_never_asks_for_frames_past_the_end():
    rounds = [R(1, 100.0, 190.0)]
    got = ms.spans(rounds, source_duration=191.0)
    assert got[0][1] == 191.0


def test_a_round_that_lasted_no_time_is_not_a_round():
    """Read from a demo they never are; read off a scoreboard, a misread
    digit can start and end one in the same second -- and padding that by PRE
    and POST gives an eleven-second span and a "Round 1" chapter for a round
    that did not happen."""
    rounds = [R(1, 100.0, 100.0), R(2, 300.0, 390.0)]
    got = ms.spans(rounds)
    assert len(got) == 1
    assert got[0][0] == pytest.approx(294.0)


def test_a_short_but_real_round_is_kept():
    """Counter-Strike rounds end fast: a 5v5 opening duel can finish one in
    twenty seconds, and dropping those would be throwing away the match."""
    rounds = [R(1, 100.0, 122.0), R(2, 300.0, 390.0)]
    assert len(ms.spans(rounds)) == 2


def test_no_rounds_is_no_spans():
    assert ms.spans([]) == []


def test_the_spans_never_overlap():
    """Overlapping spans would put the same seconds in the output twice, and
    every chapter after the first would be wrong by the overlap."""
    rounds = _match(8, every=60.0, length=55.0)
    got = ms.spans(rounds)
    for (a1, b1), (a2, _b2) in zip(got, got[1:]):
        assert b1 <= a2, (a1, b1, a2)


# ------------------------------------------- recording time -> output time

def test_a_moment_inside_a_span_maps_to_where_it_lands():
    spans = [(0.0, 10.0), (100.0, 110.0)]
    assert ms.to_output(spans, 5.0) == pytest.approx(5.0)
    # The second span begins at 10s of output, because the first was 10 long.
    assert ms.to_output(spans, 100.0) == pytest.approx(10.0)
    assert ms.to_output(spans, 105.0) == pytest.approx(15.0)


def test_a_moment_that_was_cut_out_maps_to_nothing():
    """A real answer, not a failure: a chapter for a moment that is not in the
    video points at whatever happens to be there instead."""
    assert ms.to_output([(0.0, 10.0), (100.0, 110.0)], 50.0) is None


def test_the_total_is_what_was_kept():
    assert ms.total([(0.0, 10.0), (100.0, 115.0)]) == pytest.approx(25.0)


# ------------------------------------------------------------- chapters

def test_every_round_becomes_a_chapter():
    rounds = _match(6, every=200.0, length=120.0)
    spans = ms.spans(rounds)
    got = ms.chapters(rounds, spans)
    assert len(got) == 6, got


def test_the_first_chapter_is_at_zero():
    """YouTube shows nothing at all without it. The first round's span starts
    PRE seconds before it, so its mark is moved to zero rather than dropped --
    those seconds are that round's own run-up and belong to it."""
    rounds = _match(4, every=200.0, length=120.0)
    got = ms.chapters(rounds, ms.spans(rounds))
    assert got[0][0] == 0.0


def test_chapters_are_at_least_ten_seconds_apart():
    rounds = [R(i + 1, 100.0 + i * 8.0, 104.0 + i * 8.0) for i in range(8)]
    got = ms.chapters(rounds, ms.spans(rounds))
    times = [t for t, _ in got]
    assert all(b - a >= ms.CHAPTER_MIN for a, b in zip(times, times[1:]))


def test_a_chapter_too_close_to_the_end_is_dropped():
    rounds = _match(5, every=200.0, length=120.0)
    spans = ms.spans(rounds)
    end = ms.total(spans)
    for t, _ in ms.chapters(rounds, spans):
        assert end - t >= ms.CHAPTER_MIN


def test_fewer_than_three_is_no_chapters_at_all():
    """Two timestamps that YouTube will not render are worse in a description
    than none."""
    rounds = _match(2, every=200.0, length=120.0)
    assert ms.chapters(rounds, ms.spans(rounds)) == []


def test_no_spans_is_no_chapters():
    assert ms.chapters(_match(4), []) == []


# ------------------------------------------------- what a round is called

def test_the_score_leads_because_that_is_the_question():
    """Watching a match back, the question at every chapter is "where were
    we"."""
    assert ms.label_for(R(7, 0, 1, score_after=(4, 3))) == "Round 7  4-3"


def test_what_the_round_earned_follows_it():
    got = ms.label_for(R(9, 0, 1, score_after=(5, 4), labels=["ACE"]))
    assert got == "Round 9  5-4 - Ace"


def test_a_good_round_with_no_label_still_says_so():
    got = ms.label_for(R(3, 0, 1, score_after=(2, 1), my_kills=3))
    assert got == "Round 3  2-1 - 3 kills"


def test_an_ordinary_round_is_just_the_round():
    assert ms.label_for(R(2, 0, 1, score_after=(1, 1), my_kills=1)) == "Round 2  1-1"


def test_a_round_with_no_score_still_has_a_name():
    """An empty chapter title is one YouTube drops, taking the rest with it."""
    assert ms.label_for(R(4, 0, 1)).strip() == "Round 4"


# ------------------------------------------------- the numbers and the title

def test_the_description_counts_what_happened():
    rounds = [R(1, 100, 160, won=True, my_kills=3, my_deaths=0),
              R(2, 300, 360, won=False, my_kills=1, my_deaths=1),
              R(3, 500, 560, won=True, my_kills=2, my_deaths=1)]
    got = ms.describe(rounds, ms.spans(rounds))
    assert got["rounds"] == 3
    assert (got["won"], got["lost"]) == (2, 1)
    assert (got["kills"], got["deaths"]) == (6, 2)


def test_it_says_how_much_of_the_match_survived():
    """A summary that keeps everything has cut nothing, which is worth
    noticing rather than presenting as a summary."""
    rounds = _match(6, every=300.0, length=60.0)
    got = ms.describe(rounds, ms.spans(rounds))
    assert 0.0 < got["kept_fraction"] < 0.5, got["kept_fraction"]


def test_the_title_says_the_result():
    rounds = [R(1, 0, 1, won=True), R(2, 2, 3, won=True), R(3, 4, 5, won=False)]
    got = ms.title("Counter-Strike 2", rounds, "12 Oct")
    assert got.startswith("Counter-Strike 2 2-1")
    assert "win" in got
    assert "12 Oct" in got


def test_a_loss_is_called_a_loss():
    rounds = [R(1, 0, 1, won=False), R(2, 2, 3, won=False), R(3, 4, 5, won=True)]
    assert "loss" in ms.title("Counter-Strike 2", rounds)


def test_no_result_invents_none():
    """Rounds read off a screen may not know who won. A title that guesses is
    worse than one that does not mention it."""
    rounds = [R(1, 0, 1), R(2, 2, 3)]
    got = ms.title("Counter-Strike 2", rounds)
    assert "win" not in got and "loss" not in got
    assert "Counter-Strike 2" in got
