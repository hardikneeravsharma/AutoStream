r"""YouTube chapters for a montage.

A MONTAGE IS THE ONE OUTPUT OF THIS APP WITH NO WAY INTO THE MIDDLE OF IT.
Forty clips joined into eight minutes, and the good one is somewhere in there.

The offsets are the same arithmetic `_plan_offsets` hands ffmpeg to place the
crossfades with, so a chapter lands on the frame its clip starts on rather
than near it -- which is the difference between a chapter list and a guess.

YOUTUBE'S RULES ARE NOT ADVICE. Break one and it shows NONE of them, with no
error anywhere: a description full of timestamps and a video with no chapter
bar, which reads as YouTube being slow rather than as a rule being broken.
"""
from __future__ import annotations

import pytest

from autostream.clips import montage
from autostream.clips.summary import chapter_text


def _labels(n):
    return [f"clip {i}" for i in range(n)]


# ------------------------------------------------- the offsets are exact

def test_a_chapter_lands_where_its_clip_starts():
    """THE SAME RECURRENCE THE CROSSFADES USE. A chapter computed any other
    way is near the clip rather than on it, and 'near' on an eight-minute
    montage is a few seconds into the wrong one."""
    d = [20.0, 30.0, 25.0]
    fade = 0.5
    got = montage.chapter_marks(d, fade, _labels(3))
    want = [0.0] + montage._plan_offsets(d, fade)
    assert [t for t, _ in got] == pytest.approx(want)


def test_the_first_is_always_at_zero():
    """YouTube shows nothing at all without it."""
    got = montage.chapter_marks([30.0, 30.0, 30.0], 0.5, _labels(3))
    assert got[0][0] == 0.0


def test_the_labels_come_through_in_order():
    got = montage.chapter_marks([30.0, 30.0, 30.0], 0.5,
                                ["first", "second", "third"])
    assert [n for _t, n in got] == ["first", "second", "third"]


def test_no_transition_still_lines_up():
    d = [30.0, 40.0, 20.0]
    got = montage.chapter_marks(d, 0.0, _labels(3))
    assert [t for t, _ in got] == pytest.approx([0.0, 30.0, 70.0])


# ------------------------------------------------------- YouTube's rules

def test_chapters_closer_than_ten_seconds_are_dropped_not_moved():
    """A chapter moved to satisfy the rule points at the wrong moment, which
    is worse than one chapter fewer."""
    d = [30.0, 4.0, 4.0, 30.0, 30.0]
    got = montage.chapter_marks(d, 0.0, _labels(5))
    times = [t for t, _ in got]
    assert all(b - a >= montage.CHAPTER_MIN for a, b in zip(times, times[1:]))
    # The two four-second clips cannot each have one; the ones that remain
    # are still at their real offsets.
    assert 0.0 in times
    assert len(got) < 5


def test_a_chapter_too_close_to_the_end_is_dropped():
    """YouTube will not show a final chapter with nothing after it."""
    d = [60.0, 60.0, 60.0, 3.0]
    got = montage.chapter_marks(d, 0.0, _labels(4))
    total = montage.expected_duration(d, 0.0)
    assert all(total - t >= montage.CHAPTER_MIN for t, _ in got)
    assert len(got) == 3


def test_fewer_than_three_is_no_chapters_at_all():
    """Two is not a chapter list to YouTube, and a description carrying two
    timestamps that do nothing is worse than one carrying none."""
    assert montage.chapter_marks([60.0, 60.0], 0.5, _labels(2)) == []


def test_a_montage_of_very_short_clips_gets_none():
    """Twelve four-second clips cannot have twelve chapters, and the three
    that would survive the spacing rule are not worth the description."""
    d = [4.0] * 12
    got = montage.chapter_marks(d, 0.0, _labels(12))
    times = [t for t, _ in got]
    assert all(b - a >= montage.CHAPTER_MIN for a, b in zip(times, times[1:]))


def test_one_clip_is_not_a_montage():
    assert montage.chapter_marks([60.0], 0.0, ["only"]) == []
    assert montage.chapter_marks([], 0.0, []) == []


def test_mismatched_labels_produce_nothing_rather_than_wrong_names():
    """A label list out of step with the durations would name every chapter
    after the wrong clip -- silently, and plausibly."""
    assert montage.chapter_marks([30.0, 30.0, 30.0], 0.0, ["a", "b"]) == []


# ------------------------------------------------------- what it looks like

def test_the_text_is_youtubes_format():
    got = montage.chapter_marks([30.0, 40.0, 50.0], 0.0,
                                ["3 kills", "4 kills", "2 kills"])
    text = chapter_text(got)
    assert text.splitlines() == ["0:00 3 kills", "0:30 4 kills", "1:10 2 kills"]


def test_an_hour_long_montage_is_stamped_with_hours():
    d = [1800.0, 1800.0, 60.0]
    got = montage.chapter_marks(d, 0.0, _labels(3))
    assert chapter_text(got).splitlines()[2].startswith("1:00:00")


# -------------------------------------------------- how a clip is named

class _Plan:
    def __init__(self, kills=0, labels=None, round_number=None):
        self.kills = kills
        self.labels = labels or []
        self.round_number = round_number


def _label(p):
    from autostream.clips.jobs import ClipJob

    return ClipJob._chapter_label(p)


def test_a_clip_is_named_for_what_happens_in_it():
    """SAID AS THE MOMENT, not as the file. The filename carries a rank and a
    timestamp because it has to sort on disk; a chapter is read while
    watching, where the only useful thing is what happens next."""
    assert _label(_Plan(kills=3)) == "3 kills"
    assert _label(_Plan(kills=1)) == "1 kill"


def test_a_round_is_named_for_what_it_earned():
    assert _label(_Plan(labels=["ACE"], round_number=14)) == "Round 14 - Ace"
    assert _label(_Plan(labels=["PISTOL_ROUND"])) == "Pistol Round"


def test_a_clip_with_nothing_to_say_still_has_a_name():
    """An empty chapter title is one YouTube drops, taking the rest with it."""
    assert _label(_Plan(kills=0)) == "Moment"
