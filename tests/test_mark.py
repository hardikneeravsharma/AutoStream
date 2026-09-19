"""The mark every reel carries: its timing, its place, and that the join draws it.

No ffmpeg here -- what the filter graph DOES is measured in
tests/verify/test_studio_render.py. These pin the arithmetic: that the
animation is the shape it is meant to be, that the mark lands in the corner
Valorant leaves empty, and that a reel whose mark cannot be drawn still renders.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from autostream.clips import mark, studio


# ------------------------------------------------------------------ timing

def test_the_reel_gets_its_first_frames_to_itself():
    reveal, alpha = mark.timeline(0.0)
    assert (reveal, alpha) == (0.0, 0.0)
    assert mark.timeline(mark.GLYPH_IN[0] - 0.01)[1] == 0.0


def test_the_glyph_arrives_before_the_wordmark_does():
    """Through the fade-up the ring is alone: a wordmark that wipes out of
    nothing has nothing to wipe out of."""
    mid = (mark.GLYPH_IN[0] + mark.GLYPH_IN[1]) / 2
    reveal, alpha = mark.timeline(mid)
    assert reveal == 0.0 and 0.0 < alpha < mark.PEAK


def test_the_wordmark_wipes_out_and_folds_back_in():
    assert mark.timeline(mark.WIPE_OUT[0])[0] == 0.0
    part = mark.timeline((mark.WIPE_OUT[0] + mark.WIPE_OUT[1]) / 2)[0]
    assert 0.0 < part < 1.0, "mid-wipe should be neither hidden nor whole"
    assert mark.timeline(mark.WIPE_OUT[1] + 0.01)[0] == pytest.approx(1.0)
    assert mark.timeline((mark.FOLD_IN[0] + mark.FOLD_IN[1]) / 2)[0] < 1.0


def test_the_ring_stays_for_the_rest_of_the_reel():
    for t in (mark.FOLD_IN[1] + 0.01, 30.0, 600.0):
        reveal, alpha = mark.timeline(t)
        assert reveal == 0.0
        assert alpha == pytest.approx(mark.REST)


def test_it_never_gets_louder_than_it_is_allowed_to():
    """Sampled across the whole animation: nothing may exceed PEAK, which is
    what 'subtle' is defined as everywhere else."""
    for i in range(0, 700):
        assert mark.timeline(i / 100.0)[1] <= mark.PEAK + 1e-9


# ------------------------------------------------------------------- place

@pytest.mark.parametrize("w,h", [(1920, 1080), (2560, 1440), (1080, 1920)])
def test_the_mark_sits_inside_the_frame_at_every_size(w, h):
    x, y = mark.place(w, h)
    m = mark.Mark(h)
    assert 0 < x and x + m.w < w, "runs off the side"
    assert 0 < y and y + m.h < h, "runs off the bottom"
    # Bottom left, not just somewhere: the one corner Valorant leaves alone.
    assert x < w * 0.25 and y > h * 0.5


def test_the_mark_scales_with_the_frame_not_with_pixels():
    """1080p and 1440p must read the same, so the box grows with the height."""
    small, big = mark.Mark(1080), mark.Mark(1440)
    assert big.h > small.h
    assert big.h / small.h == pytest.approx(1440 / 1080, rel=0.08)


# -------------------------------------------------------------- the render

def _one_shot(tmp_path):
    """The smallest thing assemble_command will join: one real Segment."""
    shot = {"clip": str(tmp_path / "a.mp4"), "duration": 2.0, "pre": 1.0,
            "kills": [1.0], "hero": False, "caption": ""}
    seg = studio.Segment(
        index=0, clip=shot["clip"], clip_mtime=0, width=1920, height=1080,
        fmt="landscape", head=0, body=60, tail=0, src_start=0.0,
        pieces=((0.0, 2.0, 1.0),), kill_at=1.0, fx=(), hero_fx=(), camera="c00",
        grade="g01", vignette=False, caption="", beats=(), freeze=0.0,
        freeze_push=False, has_audio=False)
    project = {"format": "landscape", "song": "", "song_offset": 0.0, "beat": 0.5,
               "intro": "i00", "outro": "e12", "grade": "g01", "vignette": False,
               "overlays": [], "handle": "", "music_db": 0.0, "game_db": 0.0,
               "duck": False, "kill_sound": False, "saturation": 1.0,
               "shots": [shot]}
    derived = {"length": 2.0, "kills": [1.0],
               "shots": [{"start": 0.0, "end": 2.0, "kill_reel": 1.0}]}
    return project, derived, [seg], [tmp_path / "s0.mp4"]


def test_the_join_draws_the_mark_when_it_has_one(tmp_path):
    """Two inputs and two overlays, the animation gated to its own seconds."""
    folder, still = tmp_path / "mark", tmp_path / "mark" / "rest.png"
    folder.mkdir()
    still.write_bytes(b"")
    project, derived, segs, files = _one_shot(tmp_path)
    argv = studio.assemble_command(
        project, derived, segs, files,
        tmp_path / "out.mp4", ff="ffmpeg", mark_at=(folder, still, 67, 944))
    line = " ".join(argv)
    assert "f%04d.png" in line and "rest.png" in line
    assert "overlay=x=67:y=944" in line
    assert f"lt(t,{mark.FOLD_IN[1]:.2f})" in line, "the animation must stop"
    assert f"gte(t,{mark.FOLD_IN[1]:.2f})" in line, "the ring must carry on"


def test_a_reel_still_renders_when_the_mark_cannot_be_drawn(tmp_path):
    """A watermark is not worth losing someone's reel over."""
    project, derived, segs, files = _one_shot(tmp_path)
    argv = studio.assemble_command(
        project, derived, segs, files,
        tmp_path / "out.mp4", ff="ffmpeg", mark_at=None)
    line = " ".join(argv)
    assert "overlay=x=" not in line
    assert "[v]" in line, "the video still has to come out somewhere"


def test_the_frames_are_drawn_once_and_kept(tmp_path):
    folder, still, x, y = mark.build(tmp_path, 1920, 1080)
    n = len(list(Path(folder).glob("f*.png")))
    assert n > 100 and Path(still).is_file()
    stamp = Path(still).stat().st_mtime_ns
    again = mark.build(tmp_path, 1920, 1080)
    assert again[0] == folder
    assert Path(still).stat().st_mtime_ns == stamp, "a cached set was redrawn"


def test_a_half_made_set_is_not_mistaken_for_a_finished_one(tmp_path):
    """`done` is written last, so an interrupted draw is drawn again."""
    folder, still, _x, _y = mark.build(tmp_path, 1920, 1080)
    (Path(folder) / "done.txt").unlink()
    stamp = Path(still).stat().st_mtime_ns
    mark.build(tmp_path, 1920, 1080)
    assert Path(still).stat().st_mtime_ns != stamp, "it should have been redrawn"
