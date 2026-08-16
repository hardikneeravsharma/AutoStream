"""Frozen-app entry point.

When PyInstaller freezes the app, `__file__` points inside the bundle, which is
read-only and thrown away on upgrade. Config, secrets, logs and state must live
NEXT TO the exe instead, so we pin AUTOSTREAM_HOME before importing anything
that reads paths.
"""
from __future__ import annotations

import os
import sys


def _app_home() -> str:
    if getattr(sys, "frozen", False):
        # dist/AutoStream/AutoStream.exe -> dist/AutoStream
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


os.environ.setdefault("AUTOSTREAM_HOME", _app_home())

from autostream.__main__ import main  # noqa: E402

if __name__ == "__main__":
    # Double-clicking the exe passes no arguments — run the daemon.
    if len(sys.argv) == 1:
        sys.argv.append("run")
    try:
        sys.exit(main())
    except Exception:
        # No console in a windowed build: make crashes visible somewhere.
        import traceback

        home = _app_home()
        os.makedirs(os.path.join(home, "logs"), exist_ok=True)
        with open(os.path.join(home, "logs", "crash.log"), "a",
                  encoding="utf-8") as fh:
            traceback.print_exc(file=fh)
        raise
