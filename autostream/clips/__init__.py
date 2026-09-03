"""Clip production: find the kills in a recording and cut them out.

OPTIONAL BY DESIGN
    This package needs numpy and ffmpeg, and AutoStream ships as a zip that
    people download and run. Bundling ffmpeg would roughly quadruple that
    download for a feature not everyone wants, and a hard numpy import at
    startup would turn a missing optional dependency into an app that will not
    open at all.

    So nothing here is imported until it is used. `status()` reports what is
    missing in words the Clips page can show, and every other part of
    AutoStream carries on regardless.
"""
from __future__ import annotations

import importlib
import logging
import sys

log = logging.getLogger("autostream.clips")

__all__ = ["available", "status", "set_ffmpeg_path", "runner", "ocr_ready"]

_runner = None


def _numpy_ok() -> bool:
    try:
        importlib.import_module("numpy")
        return True
    except ImportError:
        return False


def set_ffmpeg_path(folder: str | None) -> None:
    """Apply the clips.ffmpeg_path setting. Safe to call before any check."""
    try:
        from .tools import set_override
        set_override(folder or None)
    except ImportError:
        pass


def available() -> bool:
    if not _numpy_ok():
        return False
    from .tools import available as ff_available
    return ff_available()


def status() -> dict:
    """-> {ok, missing: [...], detail: str} for the setup card."""
    missing: list[str] = []
    detail = ""

    if not _numpy_ok():
        missing.append("numpy")
        # A packaged build has no pip, so "pip install numpy" would be advice
        # nobody could act on. numpy ships inside the bundle, so its absence
        # there means a broken install rather than a missing extra.
        detail = (
            "numpy is missing from this build, which should not happen - "
            "try reinstalling AutoStream."
            if getattr(sys, "frozen", False) else
            "numpy is missing. Install it into AutoStream's environment with:"
            "\n    .venv\\Scripts\\python -m pip install numpy")

    try:
        from .tools import missing_reason
        reason = missing_reason()
        if reason:
            missing.append("ffmpeg")
            detail = reason if not detail else detail + "\n\n" + reason
    except ImportError:
        missing.append("ffmpeg")

    out: dict = {"ok": not missing, "missing": missing, "detail": detail}

    # THE OUTSIDE TOOLS, REPORTED WHETHER OR NOT ANYTHING IS WRONG. Tesseract
    # is deliberately NOT added to `missing`: without it exactly one family of
    # games cannot be read, and folding that into the page's "one thing
    # missing" card would tell every Delta Force user that the clipper does
    # not work when it works perfectly. The page decides what to say with it.
    from . import deps

    out["tools"] = deps.state()
    out["ocr"] = deps.have_tesseract() and deps.have_pytesseract()

    if not missing:
        from .tools import binary, has_nvenc
        out["ffmpeg"] = binary("ffmpeg")
        out["nvenc"] = has_nvenc()
    return out


def ocr_ready() -> bool:
    """Can a kill feed be read on this machine right now?"""
    from . import deps

    return deps.ocr_ready()


def runner():
    """The process-wide JobRunner. Created on first use."""
    global _runner
    if _runner is None:
        from .jobs import JobRunner
        _runner = JobRunner()
    return _runner
