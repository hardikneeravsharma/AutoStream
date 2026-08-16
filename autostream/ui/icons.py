"""AutoStream visual identity: the logo mark, the wordmark lockup, and the icon set.

Everything here is a plain Python string of SVG markup because the UI has no build
step and no network access -- there is no sprite sheet to fetch and no icon font to
load, so the glyphs have to travel inside the page itself.

WHY THE MARK LOOKS LIKE THIS
    AutoStream notices a game and puts it on air without being asked. The mark is a
    "tally": a solid core (the source that is live) inside two concentric rings that
    are broken on a single diagonal axis (the signal leaving, and repeating). The
    break is deliberate -- an unbroken pair of rings reads as a target or a record
    button, while the gaps give the mark rotation and a quiet nod to the IEC power
    glyph, i.e. something that switches itself on. It is four arcs and one dot, so it
    survives being shrunk to a 16px tray icon and a favicon.

WHY EVERY ELEMENT CARRIES ITS OWN STROKE ATTRIBUTES
    ICONS values are inner markup: the shell wraps them in its own <svg>. Repeating
    stroke/fill on each element means a glyph renders identically no matter what the
    wrapper does or does not set, which is cheaper than debugging one icon that
    inherited a fill from somewhere.

GEOMETRY RULES (kept uniform so the set reads as one family)
    24x24 viewBox, all geometry inside a 20x20 live area (2px padding on every side),
    1.5 stroke, round caps and joins, and a shared corner-radius feel of ~2-2.5 units.
    Colour is always currentColor -- no hex anywhere in this module.
"""
from __future__ import annotations

# Shared presentation attributes. Repeated on every element on purpose (see docstring).
_STROKE = (
    ' fill="none" stroke="currentColor" stroke-width="1.5"'
    ' stroke-linecap="round" stroke-linejoin="round"'
)
_SOLID = ' fill="currentColor" stroke="none"'


def _path(d: str) -> str:
    return f'<path d="{d}"{_STROKE}/>'


def _circle(cx: float, cy: float, r: float) -> str:
    return f'<circle cx="{cx}" cy="{cy}" r="{r}"{_STROKE}/>'


def _rect(x: float, y: float, w: float, h: float, rx: float) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"{_STROKE}/>'
    )


def _dot(cx: float, cy: float, r: float) -> str:
    """A filled dot. Used only where solidity carries meaning (a live/tally point)."""
    return f'<circle cx="{cx}" cy="{cy}" r="{r}"{_SOLID}/>'


# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------

# Emitting core plus two broken concentric rings, centred on (16,16) in a 32 box.
# Ring gaps sit on the up-left / down-right diagonal; the outer arcs are shorter
# than the inner ones so the signal visibly opens out as it travels. Arc endpoints
# were taken off circles of r=8.5 (140 degree sweeps) and r=13 (96 degree sweeps).
_MARK_BODY = (
    '<circle cx="16" cy="16" r="3.5" fill="currentColor" class="mark-core"/>'
    '<path d="M12.41 8.3A8.5 8.5 0 0 1 23.7 19.59"'
    ' fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>'
    '<path d="M19.59 23.7A8.5 8.5 0 0 1 8.3 12.41"'
    ' fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>'
    '<path d="M15.32 3.02A13 13 0 0 1 28.98 16.68"'
    ' fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>'
    '<path d="M16.68 28.98A13 13 0 0 1 3.02 15.32"'
    ' fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>'
)

LOGO_MARK: str = (
    '<svg viewBox="0 0 32 32" width="32" height="32" role="img"'
    ' aria-label="AutoStream" focusable="false">'
    + _MARK_BODY
    + "</svg>"
)

# Font stack is inlined rather than inherited: SVG <text> in a detached context does
# not always pick up the page font, and there is no webfont fallback available.
_WORDMARK_FONT = (
    "'Segoe UI Variable Display','Segoe UI',system-ui,sans-serif"
)

LOGO_LOCKUP: str = (
    '<svg viewBox="0 0 146 32" width="146" height="32" role="img"'
    ' aria-label="AutoStream" focusable="false">'
    + _MARK_BODY
    + '<text x="43" y="22" fill="currentColor" stroke="none"'
    + f' font-family="{_WORDMARK_FONT}"'
    + ' font-size="18" letter-spacing="-0.35">'
    + '<tspan font-weight="650">Auto</tspan>'
    + '<tspan font-weight="420">Stream</tspan>'
    + "</text></svg>"
)


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------

# settings: a real 6-tooth gear, not sliders. Points alternate between an outer
# radius of 9.2 (tooth tips) and a root radius of 6.7 (valley floors) around
# (12,12); the flanks are the straight runs between the two radii.
_GEAR = (
    "M20.93 9.77L20.93 14.23L18.26 14.4L17.21 16.22L18.39 18.62L14.54 20.84"
    "L13.05 18.62L10.95 18.62L9.46 20.84L5.61 18.62L6.79 16.22L5.74 14.4"
    "L3.07 14.23L3.07 9.77L5.74 9.6L6.79 7.78L5.61 5.38L9.46 3.16L10.95 5.38"
    "L13.05 5.38L14.54 3.16L18.39 5.38L17.21 7.78L18.26 9.6Z"
)

ICONS: dict[str, str] = {
    # -- navigation ---------------------------------------------------------
    # A gauge with a needle: a status dial, not a tile grid. Reads "what is it
    # doing right now" at a glance, which is exactly what the dashboard answers.
    "dashboard": (
        _path("M2.82 18.46A9.5 9.5 0 1 1 21.18 18.46")
        + _path("M12 16L16.02 10.27")
        + _dot(12, 16, 1.25)
    ),
    # Three tiles at gallery proportions: one tall, two stacked. Reads as a
    # collection of app cards rather than a generic four-square grid.
    "library": (
        _rect(3, 4, 8, 16, 2)
        + _rect(13, 4, 8, 7, 2)
        + _rect(13, 13, 8, 7, 2)
    ),
    "settings": _path(_GEAR) + _circle(12, 12, 3.3),
    "logs": (
        _rect(4.5, 3, 15, 18, 2.5)
        + _path("M8 8.5H16")
        + _path("M8 12H16")
        + _path("M8 15.5H13.5")
    ),
    # Standard IEC 5009: broken ring with a vertical stem through the gap.
    "power": (
        _path("M16.7 5.88A8.2 8.2 0 1 1 7.3 5.88")
        + _path("M12 2.8V11.6")
    ),

    # -- transport ----------------------------------------------------------
    "play": _path("M8.5 5.4L19.6 12L8.5 18.6Z"),
    "stop": _rect(6, 6, 12, 12, 2.5),
    "pause": _path("M9.5 5.5V18.5") + _path("M14.5 5.5V18.5"),
    # Ringed play, so resume never gets mistaken for the bare launch/play action.
    "resume": _circle(12, 12, 9) + _path("M10.1 8.2L16.5 12L10.1 15.8Z"),

    # -- actions ------------------------------------------------------------
    "search": _circle(10.8, 10.8, 6.8) + _path("M15.9 15.9L21 21"),
    "refresh": (
        _path("M20.4 12A8.4 8.4 0 1 1 17.94 6.06")
        + _path("M14.26 5.5L17.94 6.06L17.38 2.38")
    ),
    "external": (
        _path(
            "M13.5 4.5H6A2.2 2.2 0 0 0 3.8 6.7V18A2.2 2.2 0 0 0 6 20.2"
            "H17.3A2.2 2.2 0 0 0 19.5 18V10.5"
        )
        + _path("M13.2 10.8L20.2 3.8")
        + _path("M15.2 3.8H20.2V8.8")
    ),
    "check": _path("M4.5 12.5L9.8 17.8L19.5 6.6"),
    "x": _path("M6.2 6.2L17.8 17.8") + _path("M17.8 6.2L6.2 17.8"),
    "plus": _path("M12 4.5V19.5") + _path("M4.5 12H19.5"),
    "trash": (
        _path("M3.5 6.5H20.5")
        + _path(
            "M5.8 6.5L7 19.6A1.8 1.8 0 0 0 8.8 21.2H15.2"
            "A1.8 1.8 0 0 0 17 19.6L18.2 6.5"
        )
        + _path("M9.5 6.5V4.6A1.6 1.6 0 0 1 11.1 3H12.9A1.6 1.6 0 0 1 14.5 4.6V6.5")
        + _path("M10.2 10.5V17.5")
        + _path("M13.8 10.5V17.5")
    ),
    "copy": (
        _path(
            "M8.5 8.5V5.2A2.2 2.2 0 0 1 10.7 3H18.8A2.2 2.2 0 0 1 21 5.2"
            "V13.3A2.2 2.2 0 0 1 18.8 15.5H15.5"
        )
        + _rect(3, 8.5, 12.5, 12.5, 2.2)
    ),
    "folder": _path(
        "M2.8 18.2V6A2 2 0 0 1 4.8 4H9.2L11.6 7.2H19.2A2 2 0 0 1 21.2 9.2"
        "V18.2A2 2 0 0 1 19.2 20.2H4.8A2 2 0 0 1 2.8 18.2Z"
    ),
    "save": (
        _path(
            "M4.9 3H16.2L21 7.8V19.1A1.9 1.9 0 0 1 19.1 21H4.9"
            "A1.9 1.9 0 0 1 3 19.1V4.9A1.9 1.9 0 0 1 4.9 3Z"
        )
        + _path("M7.6 21V14.6H16.4V21")
        + _path("M7.6 3V8.4H14.6V3")
    ),

    # -- feedback -----------------------------------------------------------
    # "h.01" is a zero-length segment: with a round cap it paints a clean dot and
    # keeps the element a stroked path like everything else in the set.
    "alert": (
        _path("M12 4L21.5 20.5H2.5Z")
        + _path("M12 10V14.2")
        + _path("M12 17.6h.01")
    ),
    "info": (
        _circle(12, 12, 9)
        + _path("M12 11V16.5")
        + _path("M12 7.6h.01")
    ),
    "chevron-right": _path("M9.5 5.5L16 12L9.5 18.5"),
    "chevron-down": _path("M5.5 9.5L12 16L18.5 9.5"),
    "eye": (
        _path("M2.8 12A9.4 6.4 0 0 1 21.2 12A9.4 6.4 0 0 1 2.8 12Z")
        + _circle(12, 12, 3.1)
    ),
    "eye-off": (
        _path("M2.8 12A9.4 6.4 0 0 1 21.2 12A9.4 6.4 0 0 1 2.8 12Z")
        + _circle(12, 12, 3.1)
        + _path("M4.2 19.8L19.8 4.2")
    ),
}
