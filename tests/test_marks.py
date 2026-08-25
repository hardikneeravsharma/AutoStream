"""Clips that chat asked for.

A viewer typing !clip is reacting to something that has ALREADY happened.
Reaction plus typing runs several seconds behind the moment, so a clip centred
on the mark opens after the thing it was asked for. Everything here exists to
pin that the window sits BEHIND the mark, and that a mark can never quietly
replace a detected clip on the same moment.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import plan                               # noqa: E402


def marks(*rows):
    return [{"at": at, "author": who} for at, who in rows]


# ------------------------------------------------------------- clustering

def test_several_people_at_once_are_one_moment():
    got = plan.cluster_marks(marks((100.0, "a"), (103.0, "b"), (108.0, "c")))
    assert len(got) == 1
    assert got[0].votes == 3
    assert sorted(got[0].who) == ["a", "b", "c"]


def test_moments_far_apart_stay_apart():
    got = plan.cluster_marks(marks((100.0, "a"), (400.0, "b")))
    assert len(got) == 2


def test_the_cluster_is_anchored_on_the_last_mark():
    """The stragglers are still reacting to the same moment, and anchoring on
    the last one keeps the whole reaction inside the clip."""
    got = plan.cluster_marks(marks((100.0, "a"), (110.0, "b")))
    assert got[0].at == 110.0


def test_rubbish_is_ignored_rather_than_raising():
    assert plan.cluster_marks([{"at": "nonsense"}, {"at": -5}, {}]) == []


# ------------------------------------------------------------- the window

def test_the_clip_sits_behind_the_mark():
    """The whole point. A clip centred on the mark misses the moment."""
    got = plan.build_marks(marks((200.0, "a")), game="CS2", clip_seconds="30")
    assert len(got) == 1
    c = got[0]
    assert c.end <= 200.0 + plan.MARK_AFTER + 0.01
    assert c.start < 200.0                      # opens before it was asked for
    assert abs(c.duration - 30.0) < 0.01


def test_the_most_asked_for_moment_ranks_first():
    """Nothing was detected, so votes are the only evidence a clip is good."""
    got = plan.build_marks(
        marks((100.0, "a"), (500.0, "x"), (503.0, "y"), (506.0, "z")),
        game="CS2", clip_seconds="20")
    assert got[0].peak_score == 3                # the three-vote moment
    assert got[0].start > got[1].start


def test_a_mark_near_the_start_is_not_negative():
    got = plan.build_marks(marks((4.0, "a")), game="CS2", clip_seconds="30")
    assert got and got[0].start == 0.0


def test_a_mark_is_labelled_so_the_reel_can_tell():
    got = plan.build_marks(marks((200.0, "a")), game="CS2")
    assert got[0].labels == ["CHAT"]
    assert got[0].kills == 0                     # nothing was detected


def test_the_end_is_clamped_to_the_recording():
    got = plan.build_marks(marks((300.0, "a")), game="CS2", clip_seconds="30",
                           source_duration=301.0)
    assert got[0].end <= 301.0


# --------------------------------------------------------------- merging

def one(start, end, name="detected"):
    return plan.ClipPlan(rank=1, start=start, end=end, kills=3, burst_kills=3,
                         peak_score=1.0, name=name)


def test_a_detected_clip_wins_the_same_moment():
    """Placed from the kill times themselves, not from how fast someone types."""
    detected = [one(180.0, 210.0)]
    marked = plan.build_marks(marks((205.0, "a")), game="CS2", clip_seconds="30")
    out = plan.merge_marks(detected, marked)
    assert len(out) == 1
    assert out[0].name == "detected"


def test_a_mark_the_detector_missed_is_kept():
    """The entire reason for having chat marks at all."""
    detected = [one(10.0, 40.0)]
    marked = plan.build_marks(marks((600.0, "a")), game="CS2", clip_seconds="30")
    out = plan.merge_marks(detected, marked)
    assert len(out) == 2
    assert any(p.labels == ["CHAT"] for p in out)


def test_merging_renumbers_so_ranks_stay_contiguous():
    out = plan.merge_marks([one(10.0, 40.0)],
                           plan.build_marks(marks((600.0, "a")), game="CS2"))
    assert [p.rank for p in out] == [1, 2]


def test_no_marks_changes_nothing():
    detected = [one(10.0, 40.0)]
    assert plan.merge_marks(detected, plan.build_marks([], game="CS2")) == detected


# ----------------------------------------------------- reading them from chat

from autostream.engine import Engine                            # noqa: E402
from autostream.state import LIVE, State                        # noqa: E402


class Rec:
    """An Obs that is a given number of seconds into a recording."""
    def __init__(self, at=123.0):
        self.at = at

    def record_offset(self):
        return self.at


def an_engine(recording=True, at=123.0) -> Engine:
    eng = Engine.__new__(Engine)
    eng.state = State(phase=LIVE)
    eng.state.recording = recording
    eng.state.save = lambda: None            # type: ignore[method-assign]
    eng.obs = Rec(at)
    eng._marks = []
    eng._mark_seen = {}
    return eng


def say(who, text):
    return {"author": who, "text": text}


def test_clip_from_chat_is_recorded_where_the_recording_is():
    """Asked of OBS, never worked out from wall clocks: the recording may have
    started late, been paused, or been adopted from a running output."""
    eng = an_engine(at=456.0)
    eng._maybe_mark(say("viewer", "!clip"))
    assert eng._marks == [{"at": 456.0, "author": "viewer"}]


def test_ordinary_chat_is_not_a_mark():
    eng = an_engine()
    for text in ("nice clip", "that was a clip moment", "clip", "!clipboard"):
        eng._maybe_mark(say("v", text))
    assert eng._marks == []


def test_trailing_words_are_allowed():
    eng = an_engine()
    eng._maybe_mark(say("v", "!clip that was insane"))
    assert len(eng._marks) == 1


def test_one_viewer_cannot_spam_the_reel():
    eng = an_engine()
    for _ in range(5):
        eng._maybe_mark(say("spammer", "!clip"))
    assert len(eng._marks) == 1


def test_different_viewers_all_count():
    """Votes are the ranking signal, so every distinct person has to land."""
    eng = an_engine()
    for who in ("a", "b", "c"):
        eng._maybe_mark(say(who, "!clip"))
    assert len(eng._marks) == 3


def test_nothing_is_marked_when_nothing_is_recording():
    """There is no file for an offset to be an offset INTO."""
    eng = an_engine(recording=False)
    eng._maybe_mark(say("v", "!clip"))
    assert eng._marks == []


def test_a_whole_stream_of_marks_is_still_bounded():
    eng = an_engine()
    for i in range(Engine.MARK_MAX + 50):
        eng._mark_seen.clear()               # every one a different moment
        eng._maybe_mark(say(f"v{i}", "!clip"))
    assert len(eng._marks) == Engine.MARK_MAX
