"""Finding ffmpeg, ffprobe and Tesseract on a Mac -- and the right ffmpeg.

TWO WAYS A MAC GETS THIS WRONG
    1. An app opened from the Finder or the Dock does not see the shell's PATH.
       launchd hands it /usr/bin:/bin:/usr/sbin:/sbin, and Homebrew lives in
       /opt/homebrew/bin (Apple Silicon) or /usr/local/bin (Intel). So
       shutil.which finds nothing on a machine where `ffmpeg` works in every
       terminal -- the Mac version of the winget-PATH problem tools.py was
       written for.

    2. Homebrew's plain `ffmpeg` formula is built without libass and
       freetype. It has no `ass` filter and no `drawtext`, so the lyrics, the
       captions, the handle and the spoken-hook subtitle cannot be drawn.
       Measured on Homebrew's ffmpeg 9.0.2: "No such filter: 'ass'". The
       `ffmpeg-full` formula has both, but it is keg-only -- installed, and on
       no PATH at all. So its keg is looked in FIRST, ahead of PATH, and a
       found ffmpeg that cannot draw text is reported rather than trusted.

NO WINDOWS PATHS HERE, AND NO MAC PATHS THERE. tools.binary() asks this module
only from behind sys.platform == "darwin".
"""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path

# ffmpeg-full first: it is the build that can draw text. Then the ordinary
# Homebrew prefixes, then MacPorts.
FFMPEG_FULL = (
    Path("/opt/homebrew/opt/ffmpeg-full/bin"),
    Path("/usr/local/opt/ffmpeg-full/bin"),
)
PREFIXES = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path("/opt/local/bin"),
)

INSTALL_HINT = "brew install ffmpeg-full"
TESSERACT_HINT = "brew install tesseract"

# What the clipper's text needs from ffmpeg. Without these a clip still cuts;
# its words are what go missing.
TEXT_FILTERS = ("drawtext", "ass")


def extend_path() -> None:
    """Put the Homebrew and MacPorts prefixes on PATH for this process.

    For everything that shells out by name -- yt-dlp's own ffmpeg lookup,
    pytesseract's `tesseract` -- and not only for the lookups below. Appended,
    so a PATH the user did set still wins.
    """
    have = os.environ.get("PATH", "").split(os.pathsep)
    extra = [str(p) for p in PREFIXES if str(p) not in have]
    if extra:
        os.environ["PATH"] = os.pathsep.join([*filter(None, have), *extra])


def find(name: str) -> str:
    """Where `name` is on this Mac, or "". ffmpeg-full's keg wins."""
    if name in ("ffmpeg", "ffprobe"):
        for d in FFMPEG_FULL:
            if (d / name).is_file():
                return str(d / name)
    found = shutil.which(name)
    if found:
        return found
    for d in PREFIXES:
        if (d / name).is_file():
            return str(d / name)
    return ""


@functools.lru_cache(maxsize=4)
def missing_filters(ffmpeg: str) -> tuple[str, ...]:
    """The TEXT_FILTERS this ffmpeg lacks. () when it has them, or cannot say."""
    try:
        p = subprocess.run([ffmpeg, "-hide_banner", "-filters"],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ()
    names = {ln.split()[1] for ln in (p.stdout or "").splitlines()
             if len(ln.split()) > 2}
    return tuple(f for f in TEXT_FILTERS if f not in names)


def text_warning(ffmpeg: str) -> str:
    """A sentence for the page when this ffmpeg cannot draw text, else ""."""
    gone = missing_filters(ffmpeg) if ffmpeg else ()
    if not gone:
        return ""
    return ("This ffmpeg was built without " + " and ".join(gone) + ", so "
            "captions, lyrics and the handle will be left off your clips. "
            f"Install the full build with:  {INSTALL_HINT}")
