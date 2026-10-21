"""Where a Mac keeps the user's files.

The Windows answers are %LOCALAPPDATA%\\AutoStream for settings and
~/Videos/AutoStream for footage. A Mac has a place for each of those too, and
an app that ignores them is one Time Machine, Spotlight and the Finder sidebar
all treat as a stranger:

    settings   ~/Library/Application Support/AutoStream
    footage    ~/Movies/AutoStream

Spelled out rather than taken from platformdirs: both are fixed by Apple, and
paths.py is imported before anything else, so it must not grow a dependency
that a stripped environment could lack.

The environment overrides keep working exactly as on Windows --
AUTOSTREAM_HOME, AUTOSTREAM_VIDEO_HOME and AUTOSTREAM_MODELS are read by
paths.py before it ever asks this module.

NO IMPORTS FROM THE PACKAGE. paths.py imports this, and everything imports
paths.py.
"""
from __future__ import annotations

from pathlib import Path

APP_NAME = "AutoStream"


def data_home() -> Path:
    """Settings, secrets, logs and state for a built .app."""
    return Path.home() / "Library" / "Application Support" / APP_NAME


def video_home() -> Path:
    """Clips, the session history and downloaded models."""
    return Path.home() / "Movies" / APP_NAME
