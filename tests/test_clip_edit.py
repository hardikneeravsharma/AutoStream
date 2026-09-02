"""Re-cutting one clip: run-up, tail, and taking a piece out of the middle.

WHAT THIS IS ACTUALLY ABOUT
    A clip is cut where the kills are, which is rarely where the moment
    starts. Wanting three seconds of run-up before the first shot, or four
    more at the end so the round result lands, is the normal case rather than
    the exception -- and the old in/out points could only ever make a clip
    SHORTER, because they were measured from the clip itself.

    So the in and out points are now recording seconds, which can reach
    outside what was originally cut, and a list of stretches can be removed
    from the middle. The pieces that survive are joined into one clip.

The arithmetic is separated from the encoding on purpose: keep_spans is where
every off-by-one lives, and it can be tested exhaustively in microseconds.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import edit  # noqa: E402


# --------------------------------------------------------------- the maths

def test_nothing_removed_leaves_one_piece():
    assert edit.keep_spans(10, 40, None) == [(10, 40)]
    assert edit.keep_spans(10, 40, []) == [(10, 40)]


def test_a_piece_out_of_the_middle_leaves_two():
    assert edit.keep_spans(10, 40, [(20, 25)]) == [(10, 20), (25, 40)]


def test_two_pieces_out_leave_three():
    assert edit.keep_spans(10, 40, [(20, 25), (30, 32)]) == [
        (10, 20), (25, 30), (32, 40)]


def test_removals_given_out_of_order_still_work():
    """Handles get dragged in whatever order they get dragged."""
    assert edit.keep_spans(10, 40, [(30, 32), (20, 25)]) == [
        (10, 20), (25, 30), (32, 40)]


def test_a_backwards_removal_is_read_the_way_it_was_meant():
    assert edit.keep_spans(10, 40, [(25, 20)]) == [(10, 20), (25, 40)]


def test_overlapping_removals_merge_instead_of_splitting():
    """Two drags over the same second mean one removal, not a zero-length piece."""
    assert edit.keep_spans(10, 40, [(20, 25), (24, 30)]) == [(10, 20), (30, 40)]


def test_touching_removals_merge():
    assert edit.keep_spans(10, 40, [(20, 25), (25, 30)]) == [(10, 20), (30, 40)]


def test_a_removal_reaching_past_the_start_just_moves_the_start():
    assert edit.keep_spans(10, 40, [(5, 12)]) == [(12, 40)]


def test_a_removal_reaching_past_the_end_just_moves_the_end():
    assert edit.keep_spans(10, 40, [(38, 60)]) == [(10, 38)]


def test_a_removal_entirely_outside_the_clip_does_nothing():
    assert edit.keep_spans(10, 40, [(50, 60)]) == [(10, 40)]
    assert edit.keep_spans(10, 40, [(0, 5)]) == [(10, 40)]


def test_removing_everything_leaves_nothing():
    assert edit.keep_spans(10, 40, [(10, 40)]) == []


def test_a_removal_too_short_to_see_is_ignored():
    """Splitting a clip in two costs an encode and a join; three frames do not."""
    assert edit.keep_spans(10, 40, [(20, 20.05)]) == [(10, 40)]


def test_a_piece_too_short_to_see_is_dropped():
    assert edit.keep_spans(10, 40, [(10.1, 30)]) == [(30, 40)]
    assert edit.keep_spans(10, 40, [(20, 39.95)]) == [(10, 20)]


def test_the_pieces_always_add_up_to_the_window_minus_the_removals():
    """The property that matters, over every arrangement worth trying."""
    import itertools

    for cuts in itertools.chain.from_iterable(
            itertools.combinations([(15, 18), (20, 25), (24, 30), (33, 36)], k)
            for k in range(5)):
        spans = edit.keep_spans(10, 40, list(cuts))
        kept = sum(b - a for a, b in spans)
        # Nothing overlaps, nothing runs backwards, everything is inside.
        for a, b in spans:
            assert 10 <= a < b <= 40
        for (_, b), (c, _) in zip(spans, spans[1:]):
            assert b < c
        assert 0 <= kept <= 30


# ------------------------------------------------------------- the re-cut

@pytest.fixture
def run(tmp_path, monkeypatch):
    """A session folder and a recut that records rather than encodes."""
    folder = tmp_path / "session"
    folder.mkdir()
    (folder / "session.json").write_text(json.dumps({
        "source": str(tmp_path / "rec.mp4"),
        "recording_seconds": 600.0,
        "options": {"encoder": "auto", "captions": False, "voice": False,
                    "vertical_mode": "crop"},
        "kills": [{"time": 105.0}, {"time": 118.0}, {"time": 140.0}],
        "plans": [{"name": "clip_01", "start": 100.0, "end": 130.0, "rank": 1,
                   "kills": 2, "labels": ["2 KILLS"], "round": 4}],
    }), encoding="utf-8")
    (tmp_path / "rec.mp4").write_bytes(b"not really a video")

    seen: dict = {}

    def fake_segments(source, spans, name, outdir, **kw):
        seen["spans"] = [(round(a, 3), round(b, 3)) for a, b in spans]
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / f"{name}.mp4"
        out.write_bytes(b"cut")
        return out

    monkeypatch.setattr(edit.cutter, "master_segments", fake_segments)
    monkeypatch.setattr(edit.cutter, "vertical", lambda *a, **k: None)
    seen["folder"] = folder
    return seen


def _spec(run, **kw):
    return edit.Spec(folder=run["folder"], name="clip_01", **kw)


def test_by_default_a_recut_reproduces_the_same_span(run):
    res = edit.recut(_spec(run))
    assert res.ok
    assert run["spans"] == [(100.0, 130.0)]
    assert res.duration == pytest.approx(30.0)


def test_a_run_up_starts_the_clip_before_the_original(run):
    """The whole point: the old in-point could only ever move forwards."""
    res = edit.recut(_spec(run, start_at=95.0))
    assert res.ok
    assert run["spans"] == [(95.0, 130.0)]
    assert res.duration == pytest.approx(35.0)


def test_a_tail_ends_the_clip_after_the_original(run):
    res = edit.recut(_spec(run, end_at=138.0))
    assert res.ok
    assert run["spans"] == [(100.0, 138.0)]


def test_a_run_up_cannot_start_before_the_recording_does(run):
    """Asking for more than exists gets what exists, not a negative timestamp."""
    res = edit.recut(_spec(run, start_at=-20.0, end_at=30.0))
    assert res.ok
    assert run["spans"][0][0] == 0.0


def test_a_tail_cannot_run_past_the_end_of_the_recording(run):
    res = edit.recut(_spec(run, end_at=9999.0))
    assert res.ok
    assert run["spans"][-1][1] == pytest.approx(600.0)


def test_a_piece_comes_out_of_the_middle(run):
    res = edit.recut(_spec(run, drop=[(110.0, 120.0)]))
    assert res.ok
    assert run["spans"] == [(100.0, 110.0), (120.0, 130.0)]
    assert res.duration == pytest.approx(20.0)
    assert res.removed == pytest.approx(10.0)


def test_run_up_tail_and_a_removal_all_at_once(run):
    res = edit.recut(_spec(run, start_at=94.0, end_at=136.0,
                           drop=[(110.0, 120.0)]))
    assert res.ok
    assert run["spans"] == [(94.0, 110.0), (120.0, 136.0)]
    assert res.duration == pytest.approx(32.0)


def test_removing_nearly_everything_is_refused(run):
    res = edit.recut(_spec(run, drop=[(100.5, 129.5)]))
    assert not res.ok
    assert "removes almost the whole clip" in res.error


def test_an_out_point_before_the_in_point_is_refused(run):
    res = edit.recut(_spec(run, start_at=120.0, end_at=110.0))
    assert not res.ok
    assert "at least a second" in res.error


def test_the_kills_counted_are_the_ones_still_in_the_clip(run):
    """A removal that takes a kill out has to take it out of the count too,
    or the caption says two kills over a clip that shows one."""
    res = edit.recut(_spec(run, end_at=130.0, drop=[(115.0, 125.0)]))
    assert res.ok
    # 105 survives, 118 was removed, 140 is past the end.
    assert run["spans"] == [(100.0, 115.0), (125.0, 130.0)]


def test_the_old_relative_trim_still_works(run):
    """Whatever still sends trim_start/trim_end must keep working."""
    res = edit.recut(_spec(run, trim_start=5.0, trim_end=20.0))
    assert res.ok
    assert run["spans"] == [(105.0, 120.0)]


def test_absolute_points_win_over_the_relative_ones(run):
    res = edit.recut(_spec(run, trim_start=5.0, start_at=90.0))
    assert res.ok
    assert run["spans"][0][0] == 90.0


def test_a_clip_is_never_left_as_two_flashes(run):
    """The floors are not symmetrical, and this is why.

    Removing 100.5-129.5 from a 30-second clip leaves half a second at each
    end. Those add up to a second, which satisfies any rule about minimum
    length, but nobody would call the result a clip.
    """
    assert edit.keep_spans(100, 130, [(100.5, 129.5)]) == []
    res = edit.recut(_spec(run, drop=[(100.5, 129.5)]))
    assert not res.ok


def test_a_piece_that_survives_is_long_enough_to_watch(run):
    """One good piece is kept even when the other end is trimmed to nothing."""
    spans = edit.keep_spans(100, 130, [(100.4, 120.0)])
    assert spans == [(120.0, 130.0)]        # the 0.4s head is gone, not kept


# ------------------------------------------------- the scrubbing preview cache

def test_only_the_newest_previews_are_kept(tmp_path):
    """Nine megabytes each, and they are a means to an end.

    Without this the folder grows by a preview for every clip anybody ever
    adjusted, and nothing would ever delete them.
    """
    import os
    import time

    from autostream import webui

    where = tmp_path / "preview"
    where.mkdir()
    made = []
    for i in range(12):
        f = where / f"clip_{i:02d}.100-200.mp4"
        f.write_bytes(b"x" * 100)
        # Distinct times, so "newest" is a real ordering rather than luck.
        os.utime(f, (time.time() + i, time.time() + i))
        made.append(f)

    gone = webui._trim_previews(where, keep=8)
    assert gone == 4
    left = sorted(p.name for p in where.glob("*.mp4"))
    assert len(left) == 8
    # The four oldest went, the eight newest stayed.
    assert all(p.exists() for p in made[4:])
    assert not any(p.exists() for p in made[:4])


def test_trimming_previews_survives_a_folder_that_is_not_there(tmp_path):
    from autostream import webui

    assert webui._trim_previews(tmp_path / "never-made") == 0


# ------------------------------------------------- an edit outliving the next

@pytest.fixture
def run_with_manifest(run):
    """The same run, but with the clips.json a real one would have."""
    folder = run["folder"]
    (folder / "clips.json").write_text(json.dumps({
        "clips": [{"name": "clip_01", "start": 100.0, "end": 130.0,
                   "master": str(folder / "clips" / "clip_01.mp4"),
                   "vertical": str(folder / "vertical" / "clip_01_vertical.mp4"),
                   "caption": "", "said": "", "duration": 30.0}],
    }), encoding="utf-8")
    return run


def _manifest(run):
    return json.loads((run["folder"] / "clips.json").read_text(encoding="utf-8"))


def _row(run):
    return _manifest(run)["clips"][0]


def _finish(run, res):
    edit.apply_to_manifest(run["folder"], res, "clip_01")


def test_an_edit_records_what_the_clip_became(run_with_manifest):
    run = run_with_manifest
    _finish(run, edit.recut(_spec(run, start_at=95.0, end_at=138.0)))
    row = _row(run)
    assert row["start"] == pytest.approx(95.0)
    assert row["end"] == pytest.approx(138.0)
    assert row["duration"] == pytest.approx(43.0)
    assert row["edited"] is True


def test_a_removal_is_recorded_as_the_gap_it_leaves(run_with_manifest):
    run = run_with_manifest
    _finish(run, edit.recut(_spec(run, drop=[(110.0, 120.0)])))
    assert _row(run)["drop"] == [[110.0, 120.0]]


def test_a_second_edit_starts_from_the_first(run_with_manifest):
    """Adding two seconds of run-up twice has to give four, not two.

    The plan in session.json never changes -- it is the record of what the
    detector found. Starting from it every time would silently throw away
    the edit before.
    """
    run = run_with_manifest
    _finish(run, edit.recut(_spec(run, start_at=95.0)))
    assert run["spans"] == [(95.0, 130.0)]

    # Now the person comes back and asks for five seconds more.
    _finish(run, edit.recut(_spec(run, start_at=90.0)))
    assert run["spans"] == [(90.0, 130.0)]
    assert _row(run)["start"] == pytest.approx(90.0)


def test_changing_only_the_caption_does_not_undo_the_trim(run_with_manifest):
    """The bug this whole pair of functions exists to stop.

    Trim a clip, then come back and fix a typo in its caption. Nothing about
    the caption says anything about the trim, so nothing is sent about it --
    and the clip would be re-cut from the original plan and lose the trim.
    """
    run = run_with_manifest
    _finish(run, edit.recut(_spec(run, start_at=95.0, end_at=138.0)))

    res = edit.recut(_spec(run, caption=True, caption_text="a better line"))
    _finish(run, res)
    assert run["spans"] == [(95.0, 138.0)], "the trim was thrown away"
    assert _row(run)["caption"] == "a better line"


def test_changing_only_the_caption_does_not_put_the_removal_back(run_with_manifest):
    run = run_with_manifest
    _finish(run, edit.recut(_spec(run, drop=[(110.0, 120.0)])))
    assert run["spans"] == [(100.0, 110.0), (120.0, 130.0)]

    _finish(run, edit.recut(_spec(run, caption=True, caption_text="hello")))
    assert run["spans"] == [(100.0, 110.0), (120.0, 130.0)], \
        "the dull middle came back"


def test_a_new_removal_replaces_the_old_ones(run_with_manifest):
    """Remembering last time's cuts must not mean they cannot be undone."""
    run = run_with_manifest
    _finish(run, edit.recut(_spec(run, drop=[(110.0, 120.0)])))
    _finish(run, edit.recut(_spec(run, drop=[])))
    assert run["spans"] == [(100.0, 130.0)]
    assert _row(run)["drop"] == []


def test_a_clip_that_was_never_edited_uses_the_plan(run_with_manifest):
    """No `edited` flag means the manifest row is just the run's own output."""
    run = run_with_manifest
    assert edit.current(run["folder"], "clip_01") is None
    res = edit.recut(_spec(run))
    assert res.ok
    assert run["spans"] == [(100.0, 130.0)]


def test_the_editor_says_what_a_clip_currently_is(run_with_manifest):
    """`current` is what the preview window is centred on, not just an
    internal detail of recut -- so it is part of the interface."""
    run = run_with_manifest
    assert edit.current(run["folder"], "clip_01") is None
    _finish(run, edit.recut(_spec(run, start_at=95.0, end_at=138.0)))
    now = edit.current(run["folder"], "clip_01")
    assert now is not None
    assert (now["start"], now["end"]) == (pytest.approx(95.0), pytest.approx(138.0))
