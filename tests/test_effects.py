"""Effects a person places by hand: text, punch-ins, freezes, sounds.

The arithmetic is separated from the rendering so it can be tested
exhaustively in microseconds, which is where every off-by-one lives. The
rendering itself was checked against real footage -- length, whether the
frozen frame is actually frozen, whether the caption is on screen only inside
its window, and whether the sound is audible where it was put.

THE ONE RULE EVERYTHING ELSE FOLLOWS
    Effect times are positions in the CLIP, never in the output. A freeze makes
    the output longer, so the two stop agreeing the moment one is added -- and
    the clip is what was on screen when the person scrubbed to a spot and put
    something there.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import effects as fx  # noqa: E402


# ------------------------------------------------------------- the timeline

def test_with_no_freezes_the_two_timelines_are_the_same():
    for t in (0.0, 1.5, 99.0):
        assert fx.at_output(t, []) == t
    assert fx.output_seconds(10.0, []) == 10.0


def test_a_freeze_moves_everything_after_it_later():
    f = [fx.Freeze(at=3.0, seconds=1.0)]
    assert fx.at_output(2.9, f) == pytest.approx(2.9)
    assert fx.at_output(4.0, f) == pytest.approx(5.0)
    assert fx.output_seconds(8.0, f) == pytest.approx(9.0)


def test_something_placed_ON_a_freeze_lands_during_it_not_after():
    """The whole point of putting a caption on a freeze.

    Counting the freeze as before it would put the caption on screen at the
    moment the picture starts moving again -- precisely the wrong side, and
    invisible as a bug because a caption would still appear, just late.
    """
    f = [fx.Freeze(at=3.0, seconds=1.0)]
    assert fx.at_output(3.0, f) == pytest.approx(3.0)
    assert fx.at_output(3.001, f) == pytest.approx(4.001)


def test_a_caption_spanning_a_freeze_still_spans_it():
    f = [fx.Freeze(at=3.0, seconds=1.0)]
    assert fx.at_output(2.0, f) == pytest.approx(2.0)
    assert fx.at_output(5.0, f) == pytest.approx(6.0)


def test_several_freezes_add_up():
    f = [fx.Freeze(at=2.0, seconds=1.0), fx.Freeze(at=5.0, seconds=0.5)]
    assert fx.at_output(1.0, f) == pytest.approx(1.0)
    assert fx.at_output(3.0, f) == pytest.approx(4.0)
    assert fx.at_output(6.0, f) == pytest.approx(7.5)
    assert fx.output_seconds(10.0, f) == pytest.approx(11.5)


def test_freezes_given_out_of_order_still_add_up():
    a = [fx.Freeze(at=5.0, seconds=0.5), fx.Freeze(at=2.0, seconds=1.0)]
    b = [fx.Freeze(at=2.0, seconds=1.0), fx.Freeze(at=5.0, seconds=0.5)]
    assert fx.at_output(6.0, a) == fx.at_output(6.0, b)


def test_a_freeze_past_the_end_does_not_lengthen_anything():
    """_freeze_graph never renders one, so counting it would report a length
    the file does not have."""
    f = [fx.Freeze(at=99.0, seconds=2.0)]
    assert fx.output_seconds(8.0, f) == pytest.approx(8.0)


def test_a_freeze_too_short_to_see_is_ignored():
    assert fx.ordered_freezes([fx.Freeze(at=1.0, seconds=0.01)]) == []
    assert fx.output_seconds(8.0, [fx.Freeze(at=1.0, seconds=0.01)]) == 8.0


def test_a_freeze_longer_than_the_limit_is_capped_not_obeyed():
    f = [fx.Freeze(at=1.0, seconds=60.0)]
    assert fx.output_seconds(8.0, f) == pytest.approx(8.0 + fx.FREEZE_MAX)


# ------------------------------------------------------------- what it refuses

def _fine():
    return fx.Effects(captions=[fx.Caption(text="hi", at=1.0, until=3.0)])


def test_a_reasonable_set_has_nothing_wrong_with_it():
    assert fx.problems(_fine(), 10.0) == []


def test_an_effect_outside_the_clip_is_reported_not_moved():
    """Silently clamping it would put it somewhere it was not placed, and
    nobody re-watches the clip to check."""
    e = fx.Effects(captions=[fx.Caption(text="hi", at=30.0, until=32.0)])
    said = fx.problems(e, 10.0)
    assert said and "outside" in said[0]


def test_a_caption_with_no_words_is_reported():
    e = fx.Effects(captions=[fx.Caption(text="   ", at=1.0, until=2.0)])
    assert any("no text" in s for s in fx.problems(e, 10.0))


def test_a_caption_that_ends_before_it_starts_is_reported():
    e = fx.Effects(captions=[fx.Caption(text="hi", at=5.0, until=2.0)])
    assert any("ends before" in s for s in fx.problems(e, 10.0))


def test_an_impossible_zoom_is_reported():
    e = fx.Effects(zooms=[fx.Zoom(at=1.0, until=3.0, to=40.0)])
    assert any("between" in s for s in fx.problems(e, 10.0))


def test_a_sound_file_that_is_not_there_is_reported(tmp_path):
    e = fx.Effects(sounds=[fx.Sound(path=tmp_path / "gone.wav", at=1.0)])
    assert any("not there" in s for s in fx.problems(e, 10.0))


def test_every_problem_is_reported_at_once_not_one_at_a_time(tmp_path):
    """Fixing four things one render at a time is four renders."""
    e = fx.Effects(
        captions=[fx.Caption(text="", at=99.0, until=1.0)],
        zooms=[fx.Zoom(at=1.0, until=0.5, to=99.0)],
        sounds=[fx.Sound(path=tmp_path / "nope.wav", at=99.0)])
    assert len(fx.problems(e, 10.0)) >= 4


# --------------------------------------------------------------- the graph

def _graph(e, **kw):
    kw.setdefault("width", 1080)
    kw.setdefault("height", 1920)
    kw.setdefault("clip_seconds", 8.0)
    kw.setdefault("fps", 60.0)
    kw.setdefault("has_audio", True)
    return fx.build(e, **kw)


def test_nothing_asked_for_produces_no_graph():
    graph, inputs, _, _ = _graph(fx.Effects())
    assert graph == "" and inputs == []


def test_a_freeze_becomes_a_held_frame_and_a_join():
    graph, _, vlabel, alabel = _graph(
        fx.Effects(freezes=[fx.Freeze(at=3.0, seconds=1.0)]))
    assert "tpad=stop_mode=clone:stop_duration=1.000" in graph
    assert "concat=n=3:v=1:a=1" in graph
    assert vlabel == "vcat" and alabel == "acat"


def test_the_held_frame_is_silent_rather_than_carrying_the_clips_audio():
    """Sound continuing over a stopped picture reads as a dropped feed."""
    graph, _, _, _ = _graph(
        fx.Effects(freezes=[fx.Freeze(at=3.0, seconds=1.0)]))
    assert "anullsrc" in graph
    assert "atrim=duration=1.000" in graph


def test_a_freeze_on_a_clip_with_no_audio_does_not_ask_for_any():
    graph, _, _, alabel = _graph(
        fx.Effects(freezes=[fx.Freeze(at=3.0, seconds=1.0)]), has_audio=False)
    assert "anullsrc" not in graph
    assert "concat=n=3:v=1:a=0" in graph
    assert alabel == ""


def test_a_zoom_scales_up_and_crops_back():
    """An animated crop is not possible -- a filter's output size is fixed when
    it is set up -- so the punch-in is done the other way round."""
    graph, _, vlabel, _ = _graph(
        fx.Effects(zooms=[fx.Zoom(at=1.0, until=3.0, to=1.4)]))
    assert "scale=w=" in graph and "eval=frame" in graph
    assert "crop=1080:1920" in graph
    assert vlabel == "zoomed"


def test_a_zoom_ramps_in_and_out_rather_than_snapping():
    """A punch-in that arrives on one frame is a glitch; one that never lets
    go leaves the rest of the clip cropped.

    Asserted on the expression rather than on the graph: the graph carries it
    twice, once for the width and once for the height, so counting there
    measures the plumbing instead of the shape.
    """
    expr = fx._zoom_expr([fx.Zoom(at=1.0, until=3.0, to=1.4)], [])
    assert expr.count("min(1,max(0,") == 2, expr
    assert expr.startswith("1+"), "it has to sit at 1x outside the range"


def test_the_larger_zoom_wins_where_two_overlap():
    expr = fx._zoom_expr([fx.Zoom(at=1.0, until=4.0, to=1.2),
                          fx.Zoom(at=2.0, until=3.0, to=1.8)], [])
    assert expr.startswith("1+max(")


def test_a_zoom_shorter_than_two_ramps_still_ramps():
    """Its ramp is halved rather than overshooting past the end."""
    expr = fx._zoom_expr([fx.Zoom(at=1.0, until=1.4, to=1.4)], [])
    assert "0.200" in expr, expr


def test_a_zoom_of_one_times_is_not_a_zoom():
    assert fx._zoom_expr([fx.Zoom(at=1.0, until=3.0, to=1.0)], []) == ""


def test_zoom_times_are_shifted_by_a_freeze_before_them():
    graph, _, _, _ = _graph(fx.Effects(
        freezes=[fx.Freeze(at=1.0, seconds=2.0)],
        zooms=[fx.Zoom(at=4.0, until=6.0, to=1.4)]))
    assert "6.000" in graph and "8.000" in graph


def test_each_caption_is_gated_to_its_own_window():
    e = fx.Effects(captions=[
        fx.Caption(text="one", at=0.5, until=2.0),
        fx.Caption(text="two", at=4.0, until=6.0)])
    for i, c in enumerate(e.captions):
        c._file = Path(f"cap{i}.txt")
    graph, _, _, _ = _graph(e)
    assert "between(t,0.500,2.000)" in graph
    assert "between(t,4.000,6.000)" in graph


def test_a_caption_with_no_words_draws_nothing():
    e = fx.Effects(captions=[fx.Caption(text="  ", at=1.0, until=2.0)])
    e.captions[0]._file = Path("x.txt")
    graph, _, _, _ = _graph(e)
    assert "drawtext" not in graph


def test_a_sound_is_delayed_to_where_it_was_put(tmp_path):
    beep = tmp_path / "beep.wav"
    beep.write_bytes(b"RIFF....WAVE")
    graph, inputs, _, alabel = _graph(
        fx.Effects(sounds=[fx.Sound(path=beep, at=2.5, gain=1.0)]))
    assert "adelay=2500:all=1" in graph
    assert inputs == ["-i", str(beep)]
    assert alabel == "amixed"


def test_a_sound_lands_after_a_freeze_that_precedes_it(tmp_path):
    beep = tmp_path / "beep.wav"
    beep.write_bytes(b"RIFF....WAVE")
    graph, _, _, _ = _graph(fx.Effects(
        freezes=[fx.Freeze(at=1.0, seconds=2.0)],
        sounds=[fx.Sound(path=beep, at=4.0)]))
    assert "adelay=6000:all=1" in graph


def test_the_mix_does_not_duck_the_clips_own_audio(tmp_path):
    """amix normalises by default, so adding a sound effect would quieten the
    gunfire it is meant to sit on top of."""
    beep = tmp_path / "beep.wav"
    beep.write_bytes(b"RIFF....WAVE")
    graph, _, _, _ = _graph(fx.Effects(sounds=[fx.Sound(path=beep, at=1.0)]))
    assert "normalize=0" in graph


def test_a_sound_on_a_clip_with_no_audio_is_skipped(tmp_path):
    beep = tmp_path / "beep.wav"
    beep.write_bytes(b"RIFF....WAVE")
    graph, inputs, _, alabel = _graph(
        fx.Effects(sounds=[fx.Sound(path=beep, at=1.0)]), has_audio=False)
    assert "amix" not in graph
    assert inputs == []
    assert alabel == ""


def test_everything_at_once_produces_one_graph_and_one_encode(tmp_path):
    """Five effects as five passes is five generations of h264."""
    beep = tmp_path / "beep.wav"
    beep.write_bytes(b"RIFF....WAVE")
    e = fx.Effects(
        captions=[fx.Caption(text="hi", at=0.5, until=2.0)],
        zooms=[fx.Zoom(at=2.5, until=4.5, to=1.4)],
        freezes=[fx.Freeze(at=3.0, seconds=1.0)],
        sounds=[fx.Sound(path=beep, at=3.0)])
    e.captions[0]._file = tmp_path / "cap0.txt"
    graph, inputs, vlabel, alabel = _graph(e)
    for expected in ("tpad", "concat", "scale=w=", "drawtext", "amix"):
        assert expected in graph, f"{expected} is missing from the graph"
    assert vlabel.startswith("cap") and alabel == "amixed"
