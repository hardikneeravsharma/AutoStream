"""`autostream run` on a Mac: the clipper and the Studio, and nothing else.

WHAT STARTS
    The web server and the window. That is the whole app on a Mac (issue
    #193): no Engine, so no game watcher, no OBS, no YouTube; no tray; no
    overlay; no hotkeys. cmd_run's Windows path is not touched -- __main__
    hands over to run() here from behind sys.platform == "darwin" before any
    of it begins.

WHY THE SERVER CAN RUN WITHOUT AN ENGINE
    It already does, on Windows, during first-run setup: every Clips and Studio
    route works with `engine=None`, `/api/status` answers for a missing engine,
    and clip jobs and renders run on their own threads. This is that mode,
    made permanent.

FIRST RUN
    Unconfigured, the page opens the setup wizard as it does on Windows -- but
    with only "Just make clips" on offer (ui/setup.py reads `unavailable` from
    /api/bootstrap), which checks for ffmpeg and Tesseract and says how to get
    them. There is no engine to start afterwards, so the wizard's reload lands
    straight on the Clips page.

ONE AT A TIME
    single.py holds a Windows mutex, and off Windows a lock file in the
    PROGRAM folder -- which inside a signed .app is read-only, and which
    ignores AUTOSTREAM_INSTANCE. This takes its own flock in the DATA folder,
    suffixed the same way, so the browser test tier can still run beside the
    user's own copy.
"""
from __future__ import annotations

import logging
import os
import secrets
import signal
import time

from .. import cfg, paths
from . import tools as _tools

log = logging.getLogger("autostream.macos")

LOCK_NAME = ".autostream.lock"
_lock_fd: int | None = None


def _lock_path():
    extra = os.environ.get("AUTOSTREAM_INSTANCE", "").strip()
    return paths.DATA_HOME / (f"{LOCK_NAME}-{extra}" if extra else LOCK_NAME)


def acquire() -> bool:
    """-> True if this process may run. False means another one already is.

    flock, not a pid file: the kernel drops it when the process dies, however
    it dies, which is the property single.py wanted from the Windows mutex.
    """
    global _lock_fd
    import fcntl

    try:
        paths.DATA_HOME.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(_lock_path()), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return True                       # cannot tell; do not block
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    _lock_fd = fd
    return True


def release() -> None:
    global _lock_fd
    if _lock_fd is not None:
        try:
            os.close(_lock_fd)
        except OSError:
            pass
        _lock_fd = None


def _show_running(port: int, token: str) -> bool:
    """Ask the copy that is already running to come forward."""
    import json
    import urllib.request

    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/cmd?k={token}",
            data=json.dumps({"command": "show"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except Exception as e:                              # noqa: BLE001
        log.debug("could not ask the running copy to show itself: %s", e)
        return False


def busy(server) -> str:
    """What a quit would destroy, in a few words, or "" when nothing.

    The same two things scripts/handoff.py waits for before it closes the
    Windows app for a rebuild: a clip job and a reel render.
    """
    try:
        clips = server._clips_status() or {}            # noqa: SLF001
        if isinstance(clips, dict) and clips.get("state") in ("running", "queued"):
            return "a clip job"
        job = server.studio_job() or {}
        if job.get("state") in ("running", "queued"):
            return "a reel render"
    except Exception:                                   # noqa: BLE001
        pass
    return ""


def run(args, setup_logging) -> int:
    """The Mac's cmd_run. `setup_logging` is __main__'s, passed in so this
    module never imports __main__ (which `python -m` runs as a script)."""
    from ..webui import Server, is_configured
    from .window import MacWindow

    # Before anything looks for ffmpeg: a Finder launch has no Homebrew PATH.
    _tools.extend_path()

    config = cfg.load()
    setup_logging("DEBUG" if args.verbose else config.logging.level,
                  console=not args.quiet)
    log.info("AutoStream for macOS: clips and Studio only (no streaming)")

    token = config.rules.web_token
    if not token:
        token = secrets.token_urlsafe(12)
        cfg.save_field("rules", "web_token", token)
    port = int(config.rules.web_port or 8787)

    if not acquire():
        shown = _show_running(port, token)
        log.error("AutoStream is already running%s. It is at %s",
                  " - brought it to the front" if shown else "",
                  f"http://127.0.0.1:{port}/")
        return 1

    if not is_configured():
        log.info("no configuration found - the setup wizard offers the clipper")

    # lan=False: the LAN dashboard is for watching a stream from a phone, and
    # binding every interface makes macOS ask the user about incoming
    # connections the moment the app opens.
    server = Server(token, port, None, lan=False)
    if server.start() is None:
        log.error("could not start the UI server on port %d", port)
        release()
        return 1

    win = MacWindow(server.local_url(), busy=lambda: busy(server))
    server.window = win

    def _sig(_signum, _frame):
        log.info("signal received - stopping")
        win.request_quit("shutting down")

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, _sig)
        except (ValueError, AttributeError):
            pass

    # Blocks on the main thread until the window closes; returns at once
    # with `fell_back` when there is no native window to block on.
    win.run(hidden=bool(os.environ.get("AUTOSTREAM_NO_WINDOW")))
    if win.fell_back:
        log.info("the UI is in your browser at %s", server.url())
    try:
        while not win._quit:                            # noqa: SLF001
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass

    server.stop()
    release()
    log.info("AutoStream exited cleanly")
    return 0
