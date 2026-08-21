r"""Render the AutoStream mark to a Windows .ico.

WHY THIS IS GENERATED RATHER THAN DRAWN
    The mark already exists, in autostream/ui/icons.py as LOGO_MARK: an
    emitting core inside two broken concentric rings, gaps on the up-left /
    down-right diagonal, the outer arcs shorter than the inner ones so the
    signal visibly opens out as it travels. Hand-drawing a second, slightly
    different logo for the desktop would split the app's identity across two
    marks that never quite agree. This reads the same geometry and the same
    palette token and rasterises it.

TWO THINGS THAT MATTER AT ICON SIZES

    Anti-aliasing. Pillow's ImageDraw has NONE for arc/ellipse/rounded_
    rectangle, and a 2px ring drawn straight at 32x32 comes out as a staircase.
    Everything is drawn at SS times the target and LANCZOS-downsampled.

    Legibility. The full mark has three concentric elements. At 16px those
    would land inside about five pixels of radius and turn into a blue smudge,
    so the small sizes drop the outer ring and thicken what is left. Real icon
    sets do this; a single scaled bitmap is what makes tiny icons mush.

Run:  .venv\Scripts\python scripts\make_icon.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autostream import theme  # noqa: E402

OUT_ICO = ROOT / "autostream" / "ui" / "assets" / "autostream.ico"
OUT_PNG = ROOT / "docs" / "img" / "logo.png"

# Supersample factor. 8 is comfortably past the point where more stops helping,
# and the largest canvas here is still only 2048px.
SS = 8

# Windows asks for these; anything missing gets scaled by the shell, badly.
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

# Three tiers, because one bitmap scaled down is what makes small icons mush.
#
#   >= 64   the full mark, exactly as the UI draws it
#   32-63   the outer ring dropped; at 32px its 2.2-unit stroke is 1.8px and it
#           closes up against the inner ring instead of reading as a ring
#   < 32    a bolder mark with its own proportions. At 16px the whole 32-unit
#           box maps to about 13 pixels, so the original 2.2-unit stroke is
#           SUB-PIXEL -- which is exactly why scaling the real mark down here
#           produces a blue smudge rather than a small logo.
FULL_AT = 64
MEDIUM_AT = 32

# Proportions for the smallest tier, as fractions of the mark's span rather
# than of the 32-unit box, so they are readable as target pixels.
TINY_CORE = 0.17
TINY_RING = 0.37
TINY_STROKE = 0.155

# The mark's own coordinate system, from icons.py: a 32x32 box centred (16,16).
VB = 32.0
CORE_R = 3.5
INNER_R, INNER_W = 8.5, 2.2
OUTER_R, OUTER_W = 13.0, 2.2

# Endpoints lifted straight from _MARK_BODY so the arcs match the UI exactly.
INNER_ARCS = (((12.41, 8.30), (23.70, 19.59)), ((19.59, 23.70), (8.30, 12.41)))
OUTER_ARCS = (((15.32, 3.02), (28.98, 16.68)), ((16.68, 28.98), (3.02, 15.32)))


def _rgb(token: str) -> tuple[int, int, int]:
    """A theme token as RGB. The icon must not drift from the running app."""
    return theme.rgb("midnight", token)


def _angle(pt: tuple[float, float]) -> float:
    """Point on the mark -> Pillow arc angle.

    Pillow measures from 3 o'clock and increases clockwise, which is what
    atan2 gives directly once y already points down -- as it does in both SVG
    and raster coordinates. No sign flip needed, and adding one is the usual
    way these arcs come out mirrored.
    """
    return math.degrees(math.atan2(pt[1] - VB / 2, pt[0] - VB / 2)) % 360.0


def _arc(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, w: float,
         ends: tuple, colour: tuple[int, int, int]) -> None:
    """One stroked arc with round caps. `r` is the CENTRELINE radius."""
    start, end = (_angle(p) for p in ends)
    h = w / 2.0
    # Pillow strokes an arc INWARD from the bounding box, so the box has to be
    # the outer edge -- r + w/2 -- for the centreline to land on r. Passing r
    # directly puts the whole stroke inside the intended radius, and then the
    # caps below sit proud of it and read as beads on a wire.
    ro = r + h
    d.arc([cx - ro, cy - ro, cx + ro, cy + ro], start, end, fill=colour,
          width=max(1, round(w)))
    # Pillow's arc has butt ends; the mark is drawn with round caps, and at
    # icon sizes a squared-off ring end is a visible notch.
    for ang in (start, end):
        px = cx + r * math.cos(math.radians(ang))
        py = cy + r * math.sin(math.radians(ang))
        d.ellipse([px - h, py - h, px + h, py + h], fill=colour)


def render(size: int, *, tile: bool = True) -> Image.Image:
    """The mark at `size` px, optionally on its app tile."""
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    accent = _rgb("accent")
    core_c = _rgb("accent-hover")          # core reads a touch brighter

    if tile:
        # A vertical wash rather than a flat fill: on a dark taskbar a flat
        # tile disappears into the background, and the gradient keeps an edge.
        top, bottom = _rgb("surface-raised"), _rgb("chrome")
        wash = Image.new("RGBA", (1, n))
        for y in range(n):
            t = y / max(1, n - 1)
            wash.putpixel((0, y), tuple(
                round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
        wash = wash.resize((n, n))

        mask = Image.new("L", (n, n), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, n - 1, n - 1], radius=round(n * 0.22), fill=255)
        img.paste(wash, (0, 0), mask)

        # A hairline rim, the same trick the UI uses to lift a raised surface.
        ImageDraw.Draw(img).rounded_rectangle(
            [0, 0, n - 1, n - 1], radius=round(n * 0.22),
            outline=_rgb("border-strong"), width=max(1, round(n * 0.006)))

    # Less tile padding at small sizes -- there is simply less room to give away.
    pad = 0.82 if size >= MEDIUM_AT else 0.90
    span = n * (pad if tile else 1.0)
    k = span / VB
    cx = cy = n / 2.0

    def s(v: float) -> float:
        return v * k

    if size >= FULL_AT:
        for ends in OUTER_ARCS:
            _arc(d, cx, cy, s(OUTER_R), s(OUTER_W), ends, accent)
        for ends in INNER_ARCS:
            _arc(d, cx, cy, s(INNER_R), s(INNER_W), ends, accent)
        r = s(CORE_R)
    elif size >= MEDIUM_AT:
        for ends in INNER_ARCS:
            _arc(d, cx, cy, s(INNER_R), s(INNER_W * 1.25), ends, accent)
        r = s(CORE_R * 1.05)
    else:
        # Own proportions, not a scaled copy: the ring is pushed out and the
        # core pulled in so a whole background pixel survives between them.
        # Without that gap the two merge into one blob at 16px.
        for ends in INNER_ARCS:
            _arc(d, cx, cy, span * TINY_RING, span * TINY_STROKE, ends, accent)
        r = span * TINY_CORE

    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=core_c)
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUT_ICO.parent.mkdir(parents=True, exist_ok=True)
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)

    frames = [render(s) for s in SIZES]
    # Pillow writes every `sizes` entry from the image it is called on, so the
    # largest frame is the base and append_images carries the hand-tuned
    # smaller ones. Without append_images the 16px entry would be a downscale
    # of the full mark, which is the thing this script exists to avoid.
    frames[-1].save(OUT_ICO, format="ICO",
                    sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])

    render(512).save(OUT_PNG)

    with Image.open(OUT_ICO) as ico:
        got = sorted(ico.info.get("sizes", []))
    print(f"wrote {OUT_ICO.relative_to(ROOT)}  "
          f"({OUT_ICO.stat().st_size / 1024:.0f} KB)")
    print(f"  sizes: {', '.join(f'{w}x{h}' for w, h in got)}")
    print(f"wrote {OUT_PNG.relative_to(ROOT)}  512x512")

    missing = {(s, s) for s in SIZES} - set(got)
    if missing:
        print(f"  WARNING: missing {sorted(missing)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
