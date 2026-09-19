r"""The reel watermark: the wordmark wipes out of the glyph, then folds back into it.

    0.00 - 0.35   nothing; the reel gets its first frames to itself
    0.35 - 0.60   the glyph fades up, bottom left
    0.60 - 1.05   the wordmark WIPES out of the glyph, left to right
    1.05 - 4.60   both held
    4.60 - 5.00   the wordmark folds back in, right to left
    5.00 - end    the glyph alone, at the resting opacity

WHY A WIPE AND NOT A SLIDE. A slide needs the wordmark to exist to the left of
where it ends up, so it has to cross the glyph. A wipe reveals the letters in
place: the glyph never moves and nothing passes under it, which is also why the
whole mark can be one premultiplied RGBA strip instead of two overlays arguing
over z-order.

WHY A SHADOW. The sampler measured every treatment against four grounds; the
drop shadow was the only one that held on both the bright map and the fire
wash, so the mark is white over a soft black copy of itself.

Frames are rendered once at the reel's own height and overlaid as a PNG
sequence for the animated seconds, then a single still for the rest -- one
extra input to the join, not a second pass over the video.

Usage:  python wm_anim.py [width] [height]
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

WORD = "AUTOSTREAM"
FOLDER = "mark"                        # under the clips folder's .studio cache

GLYPH_IN = (0.35, 0.60)
WIPE_OUT = (0.60, 1.05)
FOLD_IN = (4.60, 5.00)
FPS = 30.0
# How solid the mark ever gets, and where it settles once the wordmark is gone.
PEAK = 0.62
REST = 0.42
# Where it sits, as a share of the frame. Bottom left is the one corner
# Valorant leaves alone at every HUD scale.
PAD_X, PAD_Y = 0.035, 0.055
# How many pixels the wipe's edge is feathered over. A hard edge crawls one
# pixel at a time at 30 fps and reads as a stutter.
FEATHER = 3.0


def ease(x: float) -> float:
    """Out-cubic: fast off the mark, settling rather than stopping."""
    x = max(0.0, min(1.0, x))
    return 1.0 - (1.0 - x) ** 3


def glyph(size: int) -> np.ndarray:
    """The broadcast ring: a dot with two pairs of arcs opening either side."""
    s = size * 4                                    # drawn big, shrunk down
    im = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(im)
    c, w = s / 2, max(1, int(size * 0.075 * 4))
    d.ellipse([c - s * 0.10, c - s * 0.10, c + s * 0.10, c + s * 0.10], fill=255)
    for r, arc, fill in ((s * 0.27, 62, 255), (s * 0.42, 54, 155)):
        box = [c - r, c - r, c + r, c + r]
        d.arc(box, 180 - arc, 180 + arc, fill=fill, width=w)
        d.arc(box, -arc, arc, fill=fill, width=w)
    return np.asarray(im.resize((size, size), Image.LANCZOS), dtype=np.float32) / 255.0


class Mark:
    """One reel's watermark: its size, and a frame of it at any point."""

    def __init__(self, frame_h: int):
        self.gs = max(16, int(frame_h * 0.037))     # glyph side
        self.fs = max(12, int(frame_h * 0.0215))    # cap height of the wordmark
        self.font = ImageFont.truetype(_font_file(), self.fs)
        self.track = self.fs * 0.16                 # letter-spacing, drawn by hand
        self.widths = [self.font.getlength(ch) for ch in WORD]
        self.word_w = int(sum(self.widths) + self.track * (len(WORD) - 1))
        self.gap = int(self.gs * 0.42)
        self.pad = max(2, int(self.gs * 0.5))       # room for the shadow
        self.w = self.pad * 2 + self.gs + self.gap + self.word_w
        self.h = self.pad * 2 + self.gs
        self.ring = glyph(self.gs)
        self.x0 = self.pad + self.gs + self.gap     # where the wordmark starts

    def _word(self) -> np.ndarray:
        im = Image.new("L", (self.w, self.h), 0)
        d = ImageDraw.Draw(im)
        x = float(self.x0)
        top = self.pad + (self.gs - self.fs) / 2 - self.fs * 0.08
        for ch, w in zip(WORD, self.widths):
            d.text((x, top), ch, font=self.font, fill=255)
            x += w + self.track
        return np.asarray(im, dtype=np.float32) / 255.0

    def frame(self, reveal: float, alpha: float) -> Image.Image:
        """`reveal` is how much of the wordmark is out, 0..1."""
        a = np.zeros((self.h, self.w), dtype=np.float32)
        a[self.pad:self.pad + self.gs, self.pad:self.pad + self.gs] = self.ring
        if reveal > 0.004:
            cut = self.x0 + self.word_w * reveal
            xs = np.arange(self.w, dtype=np.float32)
            wipe = np.clip((cut - xs) / FEATHER, 0.0, 1.0)[None, :]
            a = np.maximum(a, self._word() * wipe)
        rgba = np.zeros((self.h, self.w, 4), dtype=np.float32)
        rgba[..., :3] = 1.0                         # white letters and ring
        rgba[..., 3] = a
        out = Image.fromarray((rgba * 255.0).astype(np.uint8), "RGBA")
        # The shadow is the same shape, darker and offset by a pixel.
        sh = np.zeros((self.h, self.w, 4), dtype=np.float32)
        sh[..., 3] = np.roll(np.roll(a, 1, axis=0), 1, axis=1) * 0.8
        base = Image.fromarray((sh * 255.0).astype(np.uint8), "RGBA")
        base.alpha_composite(out)
        faded = np.asarray(base, dtype=np.float32)
        faded[..., 3] *= alpha
        return Image.fromarray(faded.astype(np.uint8), "RGBA")


def timeline(t: float) -> tuple[float, float]:
    """-> (reveal, alpha) at reel time t."""
    if t < GLYPH_IN[0]:
        return 0.0, 0.0
    if t < GLYPH_IN[1]:
        return 0.0, PEAK * ease((t - GLYPH_IN[0]) / (GLYPH_IN[1] - GLYPH_IN[0]))
    if t < WIPE_OUT[0]:
        return 0.0, PEAK
    if t < WIPE_OUT[1]:
        return ease((t - WIPE_OUT[0]) / (WIPE_OUT[1] - WIPE_OUT[0])), PEAK
    if t < FOLD_IN[0]:
        return 1.0, PEAK
    if t < FOLD_IN[1]:
        k = ease((t - FOLD_IN[0]) / (FOLD_IN[1] - FOLD_IN[0]))
        return 1.0 - k, PEAK + (REST - PEAK) * k
    return 0.0, REST


def _font_file() -> str:
    """A bold sans that exists on the machine. The mark is a wordmark, so the
    face matters less than it being bold, wide and actually present."""
    here = Path(os.environ.get("WINDIR") or "C:/Windows") / "Fonts"
    for name in ("arialbd.ttf", "segoeuib.ttf", "calibrib.ttf", "tahomabd.ttf", "verdanab.ttf"):
        f = here / name
        if f.is_file():
            return str(f)
    raise FileNotFoundError("no bold font to draw the mark with")


def folder(root: Path, frame_h: int) -> Path:
    """Where this reel height's frames are cached."""
    return Path(root) / ".studio" / FOLDER / str(int(frame_h))


def place(frame_w: int, frame_h: int) -> tuple[int, int]:
    """Where the mark's top-left corner sits, in pixels."""
    m = Mark(frame_h)
    return int(frame_w * PAD_X), frame_h - m.h - int(frame_h * PAD_Y)


def build(root: Path, frame_w: int, frame_h: int) -> tuple[Path, Path, int, int]:
    """The mark's frames for this reel size, drawn once and kept.

    -> (animation folder, resting still, x, y). Cheap on every render after the
    first: 152 small PNGs for a height the machine has already made is a
    directory listing, not a redraw.
    """
    out = folder(root, frame_h)
    n = int(math.ceil(FOLD_IN[1] * FPS)) + 2
    still = out / "rest.png"
    done = out / "done.txt"
    x, y = place(frame_w, frame_h)
    if done.is_file() and still.is_file():
        return out, still, x, y
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    m = Mark(frame_h)
    for i in range(n):
        m.frame(*timeline(i / FPS)).save(out / f"f{i:04d}.png")
    m.frame(0.0, REST).save(still)
    # Written last: a half-made set must not look finished to the next render.
    done.write_text(f"{n} frames\n", encoding="utf-8")
    log.info("mark: drew %d frames at %dx%d", n, m.w, m.h)
    return out, still, x, y
