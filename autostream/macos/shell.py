"""Showing things in the Finder.

`open` is the Mac's os.startfile and its explorer.exe in one: `open DIR` opens
a Finder window on a folder, `open -R FILE` opens one with the file selected,
and `open FILE` hands it to its default app. Windows' `explorer /select,` and
Linux's `xdg-open` do not exist here, so the reveal and "Open log" buttons
failed with FileNotFoundError until they asked for this instead.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _shut() -> None:
    """NOTHING A TEST RUNS MAY OPEN A WINDOW. The same door, for the same
    reason, as webui.clips_pick: a Finder window opened by a sweep is still a
    window on somebody's screen. Raises OSError, which every caller turns into
    the error it already reports."""
    if os.environ.get("AUTOSTREAM_NO_DIALOGS") or os.environ.get("AUTOSTREAM_NO_WINDOW"):
        raise OSError("Finder windows are switched off in this run.")


def reveal(p: Path) -> None:
    """A folder opened, or a file selected in its folder. Raises OSError."""
    _shut()
    subprocess.Popen(["open", str(p)] if p.is_dir() else ["open", "-R", str(p)])


def open_path(target: str) -> None:
    """A file in its default app. Raises OSError."""
    _shut()
    subprocess.Popen(["open", str(target)])
