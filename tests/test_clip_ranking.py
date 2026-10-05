"""Which of forty clips is worth watching.

A FOLDER OF FORTY IS NOT A SHORTLIST. Clips were ranked by kill count and then
by when they happened, so every three-kill clip tied and the order inside a tie
was the order of the recording -- which is not an order of quality at all.

Three kills in five seconds and three kills spread over twenty-five are the
same number and very different clips. The first is the one somebody wants to
watch, and until now nothing said so.
"""
from __future__ import annotations

import pytest

from autostream.clips import plan


class K:
    """What the planner reads off a detected kill."""

    def __init__(self, t: float, score: float = 1.0, count: int = 1):
        self.time = t
        self.end = t
        self.score = score
        self.count = count


def _build(times, **kw):
    kw.setdefault("game", "Testing")
    kw.setdefault("min_kills", 1)
    kw.setdefault("clip_seconds", "auto")
    kw.setdefault("source_duration", 10_000.0)
    return plan.build([K(t) for t in times], **kw)


# -------------------------------------------------- the kill count still wins

def test_more_kills_always_outranks_fewer(_=None):
    """The dominant term, unchanged. It is what people expect and check, and
    a four-kill clip ranking under a three would read as a bug whatever the
    reason."""
    # A tight pair and a loose quartet, far apart so they are separate fights.
    got = _build([10.0, 10.5, 500.0, 504.0, 508.0, 512.0])
    assert got[0].kills == 4, [(p.kills, p.duration) for p in got]
    assert got[1].kills == 2


# ------------------------------------------------ and density breaks the tie

def test_the_tighter_of_two_equal_clips_comes_first():
    """THE WHOLE POINT. Both have three kills; one has them in a few seconds
    and the other has dead air between them."""
    loose = [100.0, 112.0, 124.0]            # 3 kills over 24s
    tight = [500.0, 501.5, 503.0]            # 3 kills over 3s
    got = _build(loose + tight)

    assert [p.kills for p in got] == [3, 3], got
    assert got[0].start > 400, (
        "the loose fight came first; the tie-break is still the clock")
    assert got[0].density > got[1].density


def test_it_was_the_recording_order_before():
    """The behaviour this replaces, stated so the test says what changed: the
    loose fight happens FIRST in the recording, so a clock tie-break puts it
    at rank 1 -- and it is the worse clip."""
    loose = [100.0, 112.0, 124.0]
    tight = [500.0, 501.5, 503.0]
    got = _build(loose + tight)
    by_clock = sorted(got, key=lambda p: p.start)
    assert by_clock[0].start < 200, "the loose fight is earlier in the file"
    assert got[0] is not by_clock[0], (
        "ranking still agrees with the clock, so nothing was fixed")


def test_density_is_kills_per_second_of_the_clip_as_cut():
    got = _build([500.0, 501.5, 503.0])
    p = got[0]
    assert p.density == pytest.approx(p.kills / p.duration)
    assert p.density > 0


def test_a_clip_of_no_length_does_not_divide_by_zero():
    p = plan.ClipPlan(rank=1, start=5.0, end=5.0, kills=2, burst_kills=2,
                      peak_score=0.0, name="x")
    assert p.density == 0.0


def test_the_order_is_still_stable_across_reruns():
    """Two clips alike in every term still have to come out the same way
    twice, or a re-cut renames every file."""
    times = [10.0, 11.0, 200.0, 201.0, 400.0, 401.0]
    first = [p.name for p in _build(times)]
    for _ in range(5):
        assert [p.name for p in _build(times)] == first


# ----------------------------------------------------------- the shortlist

def test_the_best_few_are_marked():
    """Somewhere to start, which is the thing a folder in filename order
    never had."""
    times = []
    for i in range(12):
        base = i * 300.0
        times += [base, base + 1.0]
    got = _build(times)
    assert len(got) == 12
    assert sum(1 for p in got if p.top) == plan.SHORTLIST


def test_it_is_a_flag_and_not_a_filter():
    """Nothing is hidden. The other thirty-five are still cut, still numbered
    and still there."""
    times = []
    for i in range(9):
        base = i * 300.0
        times += [base, base + 1.0]
    got = _build(times)
    assert len(got) == 9, "clips went missing"
    assert [p.rank for p in got] == list(range(1, 10))


def test_the_marked_ones_are_the_top_of_the_order():
    times = []
    for i in range(10):
        base = i * 300.0
        times += [base] * (1 + (i % 4))      # varying kill counts
    got = _build(times)
    marked = [p.rank for p in got if p.top]
    assert marked == sorted(marked)
    assert marked == list(range(1, len(marked) + 1))


def test_a_run_with_fewer_clips_than_the_shortlist_marks_them_all():
    got = _build([10.0, 11.0, 300.0, 301.0])
    assert len(got) == 2
    assert all(p.top for p in got)


def test_combining_two_lists_does_not_produce_two_shortlists():
    """Each arrives carrying its own five, and a shortlist twice as long as it
    says it is -- with half of it outranked by clips not on it -- is worse
    than none."""
    a = _build([i * 300.0 for i in range(8) for _ in range(2)][:16])
    b = _build([5000.0 + i * 300.0 for i in range(8) for _ in range(2)][:16])
    assert sum(1 for p in a if p.top) == plan.SHORTLIST
    assert sum(1 for p in b if p.top) == plan.SHORTLIST

    both = plan.combine(a, b, "Testing")
    assert sum(1 for p in both if p.top) == plan.SHORTLIST, (
        f"{sum(1 for p in both if p.top)} clips are marked best of "
        f"{len(both)}")


# -------------------------------------------------- what the page is handed

def test_the_reason_for_the_order_is_carried_out_with_it():
    """So the page can say why a clip ranks where it does, rather than
    presenting an order the reader has to take on trust."""
    got = _build([500.0, 501.5, 503.0])
    d = got[0].as_dict()
    assert "density" in d and d["density"] > 0
    assert d["top"] is True
    assert d["rank"] == 1
