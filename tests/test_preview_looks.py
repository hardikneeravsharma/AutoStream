"""What the Studio's preview shows before a render, and the picker's stage.

- The lyrics over the preview are the render's own subtitle script, drawn
  alone into a transparent video (lyrics.overlay). libass cannot draw alpha,
  so it is drawn twice -- as it is, and in white -- and divided; these check
  the white copy keeps every alpha and loses every colour, and that the
  video that comes out is see-through where nothing is sung.
- The picker's stage plays a sharp copy of the example (examples.make_large),
  made one at a time with the newest ask first, and never a stale one.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from autostream.clips import examples, lyrics
from autostream.clips.tools import FfmpegMissing, binary

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@pytest.fixture(scope="module")
def ff():
    try:
        return binary("ffmpeg")
    except FfmpegMissing as e:
        pytest.skip(str(e))


# ------------------------------------------------------------- the white copy

def test_the_white_copy_keeps_every_alpha_and_loses_every_colour():
    ass = lyrics.build_ass("stamp", [[{"w": "red", "a": 0.0, "b": 1.0, "hook": True},
                                      {"w": "blue", "a": 1.0, "b": 2.0}]], 1080, 1920)
    white = lyrics.mask_ass(ass)
    style = next(ln for ln in white.splitlines() if ln.startswith("Style:"))
    # Every colour field white, its alpha byte (&H96 on the shadow) untouched.
    assert "&H96FFFFFF" in style and "&H00301808" not in style
    body = [ln for ln in white.splitlines() if ln.startswith("Dialogue:")]
    assert body and not any("3A26E0" in ln or "D6EFFF" in ln.upper() for ln in body)
    assert all("\\1c&HFFFFFF&" in ln for ln in body if "\\1c" in ln)
    # A clip is a shape, not a colour: the bands of the stamp stay where they are.
    assert sum("\\clip(" in ln for ln in body) == sum("\\clip(" in ln for ln in ass.splitlines())


def test_eight_digit_colours_are_whitened_too():
    """\\1c&H003A26E0& -- the red the hook word is drawn in -- carries its
    alpha byte inline. The first copy of this matched six digits and left it
    red, so the overlay came out at a third of its brightness."""
    line = "Dialogue: 0,0:00:00.00,0:00:01.00,Glow,,0,0,0,,{\\1c&H003A26E0&\\3c&H003A26E0&}MONEY\n"
    assert lyrics.mask_ass(line) == ("Dialogue: 0,0:00:00.00,0:00:01.00,Glow,,0,0,0,,"
                                     "{\\1c&HFFFFFF&\\3c&HFFFFFF&}MONEY\n")


def test_the_overlay_is_half_the_short_side_and_the_reels_shape():
    assert lyrics.overlay_size(1080, 1920) == (540, 960)
    assert lyrics.overlay_size(1920, 1080) == (960, 540)


def test_the_overlay_is_see_through_where_nothing_is_sung(ff, tmp_path):
    import numpy as np

    ass = tmp_path / "a.ass"
    ass.write_text(lyrics.build_ass("glow", [[{"w": "word", "a": 0.5, "b": 1.5, "hook": True}]], 1920, 1080),
                   encoding="utf-8")
    out = lyrics.overlay(ass, 1920, 1080, 2.0, tmp_path / "a.webm")
    assert out.is_file()

    def frame(t: float):
        raw = subprocess.run([ff, "-v", "error", "-c:v", "libvpx-vp9", "-ss", str(t), "-i", str(out),
                              "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                             capture_output=True, creationflags=NO_WINDOW).stdout
        return np.frombuffer(raw, np.uint8).reshape(540, 960, 4)

    empty, sung = frame(0.2), frame(1.0)
    assert empty[..., 3].max() < 8, "the overlay hides the picture where nothing is sung"
    ink = sung[..., 3] > 200
    assert ink.sum() > 500, "nothing drawn while the word is sung"
    # The hook word is red: once the coverage is divided out, the colour is.
    r, g, b = (sung[..., i][ink].mean() for i in range(3))
    assert r > 150 and r > g * 2 and r > b * 2, (r, g, b)


# ------------------------------------------------------------ the sharp copy

@pytest.fixture
def parts(monkeypatch):
    monkeypatch.setattr(examples, "known", lambda: {"k04": "kill", "o04fine": "overlay", "c00": "camera"})


def test_a_sharp_copy_older_than_its_card_is_not_served(tmp_path, parts):
    here = examples.folder(tmp_path)
    (here / examples.LARGE_FOLDER).mkdir(parents=True)
    big = here / examples.LARGE_FOLDER / "k04.mp4"
    big.write_bytes(b"x")
    assert examples.large_path(tmp_path, "k04") == big
    card = here / "k04.mp4"
    card.write_bytes(b"y")
    os.utime(big, (time.time() - 60, time.time() - 60))
    assert examples.large_path(tmp_path, "k04") is None, "a card cut again since is a different shot"
    assert examples.large_path(tmp_path, "c00") is None, "no camera move has nothing to show"
    assert examples.large_path(tmp_path, "nope") is None


def test_only_the_newest_ask_is_made_next(tmp_path, parts, monkeypatch):
    import threading

    made, gate = [], threading.Event()

    def make(root, part):
        made.append(part)
        if part == "k04":
            gate.wait(5)                  # the first is still being cut...
        return {"ok": part != "o04fine", "error": "no clips"}

    monkeypatch.setattr(examples, "make_large", make)
    q = examples._Large()
    assert q.ask(tmp_path, "k04") == {"state": "making"}
    for _ in range(50):
        if made:
            break
        time.sleep(0.02)
    q.ask(tmp_path, "c00")               # ...while the pointer runs down the list
    q.ask(tmp_path, "o04fine")
    gate.set()
    for _ in range(100):
        if len(made) >= 2 and q.ask(tmp_path, "o04fine")["state"] == "failed":
            break
        time.sleep(0.02)
    assert made == ["k04", "o04fine"], f"asks passed over were made anyway: {made}"
    assert q.ask(tmp_path, "o04fine") == {"state": "failed", "error": "no clips"}
