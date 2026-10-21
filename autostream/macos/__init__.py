"""Everything AutoStream does differently on macOS, in one place.

WHY A PACKAGE OF ITS OWN
    The Windows build is the one people stream with, and it works. The macOS
    port (issue #193) is the clipper and the Studio only -- a video file,
    ffmpeg and Python -- so the rule it is written to is that no Windows code
    path changes. Every macOS behaviour lives in a module under here, and the
    shared code reaches it only from behind ``sys.platform == "darwin"``. A
    Windows run never imports this package at all.

WHAT IS NOT HERE, AND WHY
    The engine, the game watcher, the tray, the overlay, the kill switch, OBS
    control, recording setup, screen savers, thumbnails, the YouTube API and
    start-at-login. The games those exist for mostly do not run on a Mac, so a
    Mac is where footage recorded on a Windows PC gets clipped, not where it is
    streamed from. ``features.UNAVAILABLE`` names each one and says why, so the
    page can explain an absence rather than show a button that does nothing.
"""
from __future__ import annotations
