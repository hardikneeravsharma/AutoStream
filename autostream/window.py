"""Native desktop window hosting the web UI.

Uses pywebview, which on Windows renders through Edge WebView2. Closing or
minimising HIDES the window; the tray icon and the overlay panel bring it back.

pywebview owns the MAIN thread, so the engine and the tkinter overlay each run
on their own thread. If pywebview is unavailable we open the UI in the default
browser instead and the app is fully usable either way.

Two hard-won rules live here:

1. NEVER call win.hide() from inside the `closing` handler. pywebview re-fires
   `closing` when the window state changes, so hiding from within the handler
   is an infinite loop. Set a flag; a worker thread does the hiding.

2. Something must be able to actually quit. `request_quit()` is the only path
   that lets a close through, and it is wired to the tray's Quit and to SIGINT.
   As a backstop, repeatedly vetoing a close gives up and lets the window shut,
   so a user can always escape.

The window also remembers its size and position between runs, and refuses to
restore one that is no longer reachable -- a saved position outlives the
monitor it was saved on, and a window restored onto a screen that has been
unplugged looks exactly like an app that failed to start.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import webbrowser

from . import atomic, paths

log = logging.getLogger("autostream.window")

try:
    import webview  # type: ignore

    _HAS = True
except ImportError:  # pragma: no cover
    _HAS = False

VETO_LIMIT = 4          # consecutive vetoes before we stop fighting the user
VETO_WINDOW = 8.0       # seconds

# Windows groups taskbar buttons, pins them and picks their icon by this
# string. Without one, a Python process gets the interpreter's identity: the
# button says Python, carries Python's icon, and pinning it pins Python.
APP_ID = "YuvaNeta.AutoStream"

DEFAULT_SIZE = (1120, 860)
MIN_SIZE = (420, 560)
GEOMETRY_FILE = "window.json"


def available() -> bool:
    return _HAS


def name_this_app() -> bool:
    """Tell Windows which app this process is. -> whether it worked.

    Has to happen before any window exists, so the taskbar button is created
    with the right identity rather than inheriting the interpreter's.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        return True
    except Exception as e:                              # noqa: BLE001
        log.debug("could not set the taskbar identity: %s", e)
        return False


def _screen() -> tuple[int, int, int, int]:
    """The whole desktop across every monitor: (left, top, width, height)."""
    if os.name == "nt":
        try:
            import ctypes

            m = ctypes.windll.user32.GetSystemMetrics
            # 76/77 are the virtual screen origin, 78/79 its size. The origin
            # is NEGATIVE when a second monitor sits left of the primary one,
            # which is exactly the case a naive 0,0-based check gets wrong.
            return (m(76), m(77), m(78), m(79))
        except Exception:                               # noqa: BLE001
            pass
    return (0, 0, 1920, 1080)


def on_screen(x: int, y: int, w: int, h: int) -> bool:
    """Would a window there actually be reachable?

    A saved position outlives the monitor it was saved on. Restoring a window
    onto a screen that has since been unplugged puts it somewhere the user
    cannot see or drag it back from, and the app looks like it failed to
    start. Requiring a decent piece of the title bar to be on the desktop is
    enough: a window that overhangs an edge can still be moved.
    """
    left, top, sw, sh = _screen()
    right, bottom = left + sw, top + sh
    # At least this much of the top strip has to be visible to grab it.
    need_w, bar = 120, 32
    return (x + w - need_w > left and x + need_w < right
            and y + bar > top and y < bottom - bar)


def _geometry_path():
    return paths.DATA_HOME / GEOMETRY_FILE


def load_geometry() -> dict:
    """Where the window was last time, or {} for anything unusable."""
    f = _geometry_path()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    try:
        w = int(data["width"])
        h = int(data["height"])
        x = int(data["x"])
        y = int(data["y"])
    except (KeyError, TypeError, ValueError):
        return {}
    if w < MIN_SIZE[0] or h < MIN_SIZE[1]:
        return {}
    left, top, sw, sh = _screen()
    if w > sw or h > sh:
        return {}
    if not on_screen(x, y, w, h):
        log.info("the window was last on a screen that is not here now, "
                 "so it opens in the middle again")
        return {"width": w, "height": h}
    return {"width": w, "height": h, "x": x, "y": y}


def save_geometry(win) -> bool:
    """Remember where the window is. -> whether anything was written."""
    try:
        w, h = int(win.width), int(win.height)
        x, y = int(win.x), int(win.y)
    except (AttributeError, TypeError, ValueError):
        return False
    if w < MIN_SIZE[0] or h < MIN_SIZE[1]:
        return False           # a minimised window reports nonsense
    try:
        atomic.write_json(_geometry_path(),
                          {"width": w, "height": h, "x": x, "y": y})
        return True
    except OSError as e:
        log.debug("could not remember the window position: %s", e)
        return False


class MainWindow:
    def __init__(self, url: str, title: str = "AutoStream"):
        self.url = url
        self.title = title
        self.win = None
        self._visible = True
        self._show = threading.Event()
        self._hide = threading.Event()
        self._quit = False
        # True once the UI has been handed to the real browser because no
        # native window could be had. The caller has nothing to block on then,
        # and must hold the process open itself -- see cmd_run.
        self.fell_back = False
        self._veto_times: list[float] = []

    # ---------------- cross-thread requests ----------------

    def request_show(self) -> None:
        self._show.set()

    def request_hide(self) -> None:
        self._hide.set()

    def request_quit(self, reason: str = "") -> None:
        """The only way the window is allowed to close for good.

        `reason` is logged. WHY THAT MATTERS: closing the window is vetoed and
        hides to the tray, so the app only ever exits because something called
        this -- and nothing said which something. An exit therefore looked
        identical in the log whether the Quit button was pressed, the tray menu
        was used, or a shutdown was under way. Working out which cost an hour
        of reading pywebview's event internals to rule out a veto that had
        never failed.
        """
        log.info("quit requested: %s", reason or "no reason given")
        save_geometry(self.win)
        self._quit = True
        self._show.set()          # wake the worker so it exits promptly
        try:
            if self.win is not None:
                self.win.destroy()
        except Exception as e:  # noqa: BLE001
            log.debug("destroy failed (already gone?): %s", e)

    # ---------------- pywebview events ----------------

    def _on_closing(self):
        """Return False to veto. MUST NOT touch the window itself."""
        # Reading position is not touching it, and this is the last moment the
        # window is still where the user put it.
        save_geometry(self.win)
        if self._quit:
            return True

        now = time.monotonic()
        self._veto_times = [t for t in self._veto_times if now - t < VETO_WINDOW]
        self._veto_times.append(now)
        if len(self._veto_times) > VETO_LIMIT:
            log.warning("close vetoed %d times in %.0fs - letting it close so you "
                        "are not stuck", len(self._veto_times), VETO_WINDOW)
            self._quit = True
            return True

        self._hide.set()
        return False

    def _on_minimized(self):
        self._hide.set()

    def _on_moved(self, *_):
        """Remembered on the way, not only on the way out.

        Closing is not the only way this window stops existing -- a machine
        that sleeps badly, an update that restarts the app, or a crash all end
        it without a `closing` event. Saving as it moves means the position
        survives those too.
        """
        save_geometry(self.win)

    # ---------------- worker ----------------

    def _worker(self):
        """Owns every show/hide call, so the event handlers never re-enter."""
        while not self._quit:
            if self._hide.wait(timeout=0.25):
                self._hide.clear()
                if self._visible and not self._quit:
                    try:
                        self.win.hide()
                        self._visible = False
                        self._veto_times.clear()
                        log.info("main window hidden - still running in the tray")
                    except Exception as e:  # noqa: BLE001
                        log.debug("hide failed: %s", e)
            if self._show.is_set():
                self._show.clear()
                if self._quit:
                    return
                try:
                    self.win.show()
                    try:
                        self.win.restore()
                    except Exception:  # noqa: BLE001 - not on every backend
                        pass
                    self._visible = True
                    self._veto_times.clear()
                except Exception as e:  # noqa: BLE001
                    log.debug("show failed: %s", e)

    # ---------------- lifecycle ----------------

    def _to_browser(self) -> None:
        """Hand the UI to the real browser. NOT a quit.

        `_quit` means a PERSON asked to leave. Setting it because the window
        backend was unavailable was the bug behind a first run that ended in
        ERR_CONNECTION_REFUSED: run() opened the browser, set `_quit` in its
        `finally`, and cmd_run's hold loop read that as "the user closed the
        window" and stopped the server a fraction of a second later -- before
        the page it had just opened could load.
        """
        self.fell_back = True
        try:
            webbrowser.open(self.url)
        except Exception:  # noqa: BLE001
            pass

    def run(self, hidden: bool = False) -> None:
        """Blocks until the window is destroyed. Call from the MAIN thread.

        Returns AT ONCE when there is no native window to block on, with
        `fell_back` set. Windows without the WebView2 runtime take that path,
        and a clean install is exactly where it is missing.
        """
        if not _HAS:
            log.info("pywebview not installed - opening the UI in your browser")
            self._to_browser()
            return

        name_this_app()
        where = load_geometry()
        try:
            self.win = webview.create_window(
                self.title, self.url,
                width=where.get("width", DEFAULT_SIZE[0]),
                height=where.get("height", DEFAULT_SIZE[1]),
                # Omitted rather than passed as None: pywebview centres the
                # window when there is no x/y, which is what a first run and a
                # vanished monitor should both get.
                **({"x": where["x"], "y": where["y"]} if "x" in where else {}),
                min_size=MIN_SIZE,
                hidden=hidden, background_color="#0d1117",
            )
        except Exception as e:  # noqa: BLE001
            log.error("could not create the window (%s) - using the browser", e)
            self._to_browser()
            return

        self._visible = not hidden
        for name, handler in (("closing", self._on_closing),
                              ("minimized", self._on_minimized),
                              ("moved", self._on_moved),
                              ("resized", self._on_moved)):
            try:
                getattr(self.win.events, name).__iadd__(handler)
            except (AttributeError, TypeError):
                log.debug("pywebview has no %r event on this version", name)

        threading.Thread(target=self._worker, name="autostream-window",
                         daemon=True).start()
        try:
            webview.start()
        except Exception as e:  # noqa: BLE001
            log.error("native window failed (%s) - falling back to the browser", e)
            self._to_browser()
            return
        # Only here: webview.start() returning means the window really was
        # opened and has really been closed.
        # A close the user asked for was vetoed and hidden, so reaching here
        # means either a quit was requested or the window was destroyed from
        # outside. Saying which is the difference between "expected" and
        # "something killed the window".
        if self._quit:
            log.info("native window closed after a quit was requested")
        else:
            log.warning("the native window was destroyed without a quit being "
                        "requested - the app will exit")
            self._quit = True
