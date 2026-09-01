"""Frozen-app entry point.

When PyInstaller freezes the app, `__file__` points inside the bundle, which is
read-only and thrown away on upgrade -- so paths cannot work out where the
program is from its own source file. This pins it, before anything that reads
paths is imported.

AUTOSTREAM_APP_DIR, NOT AUTOSTREAM_HOME. It used to set AUTOSTREAM_HOME, which
is the variable a USER sets to say "keep everything in this one folder". Once
paths learned to put the user's files in %LOCALAPPDATA%, that conflation meant
every frozen build looked like it had been given an explicit override -- so the
new location was never used and nothing ever migrated. The launcher is saying
where the PROGRAM is; only a person can say where their FILES should go.
"""
from __future__ import annotations

import os
import sys


def _app_home() -> str:
    if getattr(sys, "frozen", False):
        # dist/AutoStream/AutoStream.exe -> dist/AutoStream
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


os.environ.setdefault("AUTOSTREAM_APP_DIR", _app_home())

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
