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
"""
from __future__ import annotations

import logging
import threading
import time
import webbrowser

log = logging.getLogger("autostream.window")

try:
    import webview  # type: ignore

    _HAS = True
except ImportError:  # pragma: no cover
    _HAS = False

VETO_LIMIT = 4          # consecutive vetoes before we stop fighting the user
VETO_WINDOW = 8.0       # seconds


def available() -> bool:
    return _HAS


class MainWindow:
    def __init__(self, url: str, title: str = "AutoStream"):
        self.url = url
        self.title = title
        self.win = None
        self._visible = True
        self._show = threading.Event()
        self._hide = threading.Event()
        self._quit = False
        self._veto_times: list[float] = []

    # ---------------- cross-thread requests ----------------

    def request_show(self) -> None:
        self._show.set()

    def request_hide(self) -> None:
        self._hide.set()

    def request_quit(self) -> None:
        """The only way the window is allowed to close for good."""
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

    def run(self, hidden: bool = False) -> None:
        """Blocks until the window is destroyed. Call from the MAIN thread."""
        if not _HAS:
            log.info("pywebview not installed - opening the UI in your browser")
            try:
                webbrowser.open(self.url)
            except Exception:  # noqa: BLE001
                pass
            return

        try:
            self.win = webview.create_window(
                self.title, self.url,
                width=1120, height=860, min_size=(420, 560),
                hidden=hidden, background_color="#0d1117",
            )
        except Exception as e:  # noqa: BLE001
            log.error("could not create the window (%s) - using the browser", e)
            webbrowser.open(self.url)
            return

        self._visible = not hidden
        for name, handler in (("closing", self._on_closing),
                              ("minimized", self._on_minimized)):
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
            try:
                webbrowser.open(self.url)
            except Exception:  # noqa: BLE001
                pass
        finally:
            self._quit = True
            log.info("native window closed")
