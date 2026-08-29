r"""One AutoStream at a time.

WHY THIS HAD TO EXIST
    Two copies running is not a degraded version of one -- it is a different,
    much worse thing. Each has its own engine, so each spots the game, each
    creates its OWN YouTube broadcast, and each tells the same OBS to start
    streaming. OBS can push one output, so the second start is a no-op and one
    of the two broadcasts never receives a frame. It waits ninety seconds,
    reports "YouTube never saw our ingestion", aborts, and after three of those
    pauses itself.

    None of those messages mentions the actual problem, and the log reads as
    one confused process rather than two coherent ones -- every line appearing
    twice, a few seconds apart, with different broadcast ids.

    It is easy to end up here: the Scheduled Task starts one at login and then
    somebody double-clicks the shortcut.

HOW
    A named Windows mutex, held for the life of the process. Not a pid file:
    a pid file survives a crash and then lies, and clearing a stale one is
    guesswork. Windows releases a mutex when the owning process dies, however
    it dies, which is exactly the semantics wanted.

    Falls back to a lock FILE off Windows, where the same argument does not
    apply but the feature still should.
"""
from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("autostream.single")

NAME = "AutoStream-single-instance"
_handle = None
_lockfile = None


def acquire() -> bool:
    """-> True if this process may run. False means another one already is."""
    global _handle, _lockfile

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            handle = kernel32.CreateMutexW(None, True, NAME)
            if not handle:
                return True                    # cannot tell; do not block
            if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                return False
            _handle = handle
            return True
        except Exception:  # noqa: BLE001 - never block startup on this
            return True

    try:
        from . import paths

        path = paths.ROOT / ".autostream.lock"
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR)
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            pass
        except OSError:
            os.close(fd)
            return False
        _lockfile = fd
        return True
    except Exception:  # noqa: BLE001
        return True


def release() -> None:
    global _handle, _lockfile
    if _handle is not None:
        try:
            import ctypes

            ctypes.windll.kernel32.ReleaseMutex(_handle)
            ctypes.windll.kernel32.CloseHandle(_handle)
        except Exception:  # noqa: BLE001
            pass
        _handle = None
    if _lockfile is not None:
        try:
            os.close(_lockfile)
        except OSError:
            pass
        _lockfile = None
