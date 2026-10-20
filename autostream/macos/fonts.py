"""The Mac's answer to every font the clipper asks Windows for by file name.

WHY THIS IS A TABLE AND NOT A SEARCH
    The renderers name fonts the way Windows stores them -- impact.ttf,
    arialbd.ttf, segoeuib.ttf -- and look in C:\\Windows\\Fonts. On a Mac that
    directory does not exist, so every lookup came back empty and the caption,
    the handle, the spoken-hook subtitle and the studio's titles were all
    silently left out of the graph: drawtext is only added when a font is
    found. Measured, not guessed -- the offline suite's caption tests fail on a
    Mac for exactly this reason.

    Each Windows name maps to the same face where macOS ships it (Impact,
    Arial, Tahoma and Verdana are all in /System/Library/Fonts/Supplemental),
    and to a bundled font of the same character where it does not -- Segoe UI
    and Bahnschrift are Microsoft's and never on a Mac. The bundled fonts are in
    the package, so the last entry of every row always exists: a caption is
    never dropped for want of a face.

PATHS WITH SPACES
    "Arial Bold.ttf" has a space in it and so does "Application Support". Every
    caller already puts the path inside single quotes in the filter graph, and
    a space inside quotes is fine to ffmpeg.
"""
from __future__ import annotations

from pathlib import Path

SYSTEM = Path("/System/Library/Fonts")
SUPPLEMENTAL = SYSTEM / "Supplemental"
LIBRARY = Path("/Library/Fonts")
BUNDLED = Path(__file__).resolve().parent.parent / "clips" / "fonts"

# Windows file name -> where to find the same job done on a Mac, best first.
# The bundled entry closes every row so the answer is never "nothing".
_BOLD_SANS = BUNDLED / "Poppins-ExtraBold.ttf"
_CONDENSED = BUNDLED / "Anton-Regular.ttf"
SUBSTITUTES: dict[str, tuple[Path, ...]] = {
    "impact.ttf": (SUPPLEMENTAL / "Impact.ttf", LIBRARY / "Impact.ttf", _CONDENSED),
    "arialbd.ttf": (SUPPLEMENTAL / "Arial Bold.ttf", LIBRARY / "Arial Bold.ttf", _BOLD_SANS),
    "arial.ttf": (SUPPLEMENTAL / "Arial.ttf", LIBRARY / "Arial.ttf",
                  BUNDLED / "Kanit-Medium.ttf"),
    "segoeuib.ttf": (_BOLD_SANS,),
    "seguivar.ttf": (_BOLD_SANS,),
    "bahnschrift.ttf": (BUNDLED / "Kanit-Medium.ttf",),
    "calibrib.ttf": (_BOLD_SANS,),
    "tahomabd.ttf": (SUPPLEMENTAL / "Tahoma Bold.ttf", _BOLD_SANS),
    "verdanab.ttf": (SUPPLEMENTAL / "Verdana Bold.ttf", _BOLD_SANS),
}

# Segoe UI Emoji's Mac counterpart. Both are bitmap-strike fonts that render
# blank at a size they do not carry, so the strike travels with the path: 160
# is the largest Apple ships, and the caller scales from it as it does from
# Windows' 109.
EMOJI = SYSTEM / "Apple Color Emoji.ttc"
EMOJI_STRIKE = 160


def find(name: str) -> Path | None:
    """The Mac file standing in for Windows' `name`, or None if none exists."""
    for p in SUBSTITUTES.get(name.lower(), ()):
        if p.is_file():
            return p
    return None


def first(names) -> str | None:
    """The first of `names`, in the caller's order, that this Mac can supply."""
    for n in names:
        p = find(n)
        if p is not None:
            return str(p)
    return None


def emoji() -> tuple[Path, int] | None:
    """(font, strike size) for colour emoji, or None on a Mac without it."""
    return (EMOJI, EMOJI_STRIKE) if EMOJI.is_file() else None
