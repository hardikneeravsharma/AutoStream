r"""One breakpoint scale, and no two rules sharing a pixel.

THE BUG A SCALE PREVENTS. `@media (max-width:900px)` and
`@media (min-width:900px)` BOTH apply at exactly 900px. Written that way the
page has no answer at its own boundary, and which rule wins is whichever
happens to appear later in the stylesheet -- a property of file order, not of
intent. Four pairs were written that way (720, 760, 900 twice, 980).

The convention is the one the layout section already used: a rule that
applies *below* a point is `max-width: N-1`, a rule that applies *from* it is
`min-width: N`.

WHY THE STRAYS ARE LISTED RATHER THAN FIXED. 620, 880 and 1100 are each
within twenty pixels of a scale point. Snapping them would move real layout
on real screens, which is a change that needs eyes on it rather than a
regex. Listing them keeps them visible: this file fails the day a new one
appears, and the list is short enough to read.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSS = ROOT / "autostream" / "ui" / "css.py"

# The scale. A `min-width` lands on one of these; a `max-width` lands one
# below one of these.
SCALE = (480, 560, 640, 720, 760, 900, 980, 1000, 1120, 1560)

# Not on the scale, each within 20px of a point on it. Snapping them moves
# layout, so they are debt rather than a bug -- and debt that is written
# down. Shrink this list; never add to it without a reason beside it.
STRAYS = {
    620: "the clip stage rail's cramped spacing; 640 is the scale point",
    880: "the Clips page's one-column fold; 900 is the scale point",
    1100: "the Studio's edit and facecam grids; 1120 is the scale point",
}


@pytest.fixture(scope="module")
def css() -> str:
    return CSS.read_text(encoding="utf-8")


def _widths(css: str, kind: str) -> list[int]:
    return [int(n) for n in
            re.findall(rf"@media\s*\(\s*{kind}\s*:\s*(\d+)px", css)]


# ------------------------------------------- no two rules share a pixel

def test_no_width_is_both_a_floor_and_a_ceiling(css):
    """THE BUG. At exactly N, `max-width:N` and `min-width:N` both apply."""
    both = sorted(set(_widths(css, "max-width")) & set(_widths(css, "min-width")))
    assert both == [], (
        "these widths are written as both a max-width and a min-width, so at "
        "exactly that pixel both rules apply and file order decides: "
        f"{both}. Use max-width: N-1 for the rule that applies below N.")


def test_every_max_width_sits_one_below_a_scale_point(css):
    """A max-width that is not N-1 is a boundary nobody chose."""
    allowed = {n - 1 for n in SCALE} | set(STRAYS)
    stray = sorted(w for w in set(_widths(css, "max-width")) if w not in allowed)
    assert stray == [], (
        f"max-widths off the scale: {stray}. The scale is {SCALE}; a rule "
        "that applies below N is `max-width: N-1`. If one of these is "
        "deliberate, add it to STRAYS with the reason.")


def test_every_min_width_is_a_scale_point(css):
    allowed = set(SCALE) | set(STRAYS)
    stray = sorted(w for w in set(_widths(css, "min-width")) if w not in allowed)
    assert stray == [], (
        f"min-widths off the scale: {stray}. The scale is {SCALE}.")


# ------------------------------------------------- the strays, kept honest

def test_every_stray_is_still_in_the_stylesheet(css):
    """An entry for a width nobody uses any more is a note that will never
    be deleted, and it hides the next stray that takes the same number."""
    used = set(_widths(css, "max-width")) | set(_widths(css, "min-width"))
    gone = sorted(w for w in STRAYS if w not in used)
    assert gone == [], f"listed as a stray but no longer in the CSS: {gone}"


def test_every_stray_says_why_it_is_still_there(css):
    blank = sorted(w for w, why in STRAYS.items() if not why.strip())
    assert blank == [], f"strays with no reason given: {blank}"


def test_the_strays_do_not_grow(css):
    """The list is debt. It is allowed to shrink."""
    assert len(STRAYS) <= 3, (
        "the breakpoint strays have grown; the point of the scale is that "
        "this list gets shorter")


# ------------------------------------------------ the scale is written down

def test_the_scale_is_documented_beside_the_rules(css):
    """A convention nobody can find is a convention nobody follows."""
    assert "ONE SCALE, AND max-width IS ALWAYS ONE LESS THAN min-width" in css
    for n in SCALE:
        assert str(n) in css, f"{n} is in the scale but not in the stylesheet"


def test_the_four_pairs_that_were_broken_stay_fixed(css):
    """Named, because a regex that stops matching is a test that stops
    testing. These four each had a max-width equal to a min-width."""
    for n in (720, 760, 900, 980):
        assert f"@media (max-width:{n}px)" not in css, (
            f"max-width:{n}px is back, and min-width:{n}px also exists")
