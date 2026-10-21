"""The app window on a Mac: WKWebView through pywebview's Cocoa backend.

WHAT IS DIFFERENT FROM window.MainWindow, AND WHY
    On Windows, closing or minimising HIDES the window and the tray icon
    brings it back. The Mac build has no tray (issue #193), so a hidden window
    would be a running app with no way back to it -- the exact "looks like it
    failed to start" that window.py goes to such lengths to avoid. Here:

      * closing quits, as a single-window Mac app does;
      * minimising goes to the Dock like any other window, and is left alone;
      * and a close while a clip job or a reel render is running ASKS first,
        because quitting destroys either, and Cmd-W is one keystroke away
        from forty minutes of work.

    Everything else -- geometry, the quit-before-the-window-exists guard, the
    AUTOSTREAM_NO_WINDOW door, the browser fallback -- is MainWindow's own,
    unchanged.

THE QUESTION IS AN NSAlert, ASKED ON THE MAIN THREAD. pywebview calls the
`closing` handler from windowShouldClose:, which Cocoa runs on the main
thread, so a modal alert there is legal. pywebview's own
create_confirmation_dialog is not: it dispatches TO the main thread and waits,
which from the main thread is a deadlock. If the handler is ever called from
another thread the close is allowed rather than risking either.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from .. import window as _window

log = logging.getLogger("autostream.macos.window")


def screen() -> tuple[int, int, int, int]:
    """Every display's union, (left, top, width, height), in window points.

    window._screen() asks user32 on Windows and assumes 1920x1080 elsewhere,
    which on a Mac with a display above or left of the main one turns a
    perfectly reachable saved position into "off screen". AppKit's origin is
    bottom-left; pywebview's window coordinates are top-left from the main
    display, so the vertical extent is flipped against the main screen.
    """
    try:
        from AppKit import NSScreen  # type: ignore

        screens = list(NSScreen.screens() or ())
        if not screens:
            raise RuntimeError("no screens")
        main_h = screens[0].frame().size.height
        left = min(s.frame().origin.x for s in screens)
        right = max(s.frame().origin.x + s.frame().size.width for s in screens)
        top = min(main_h - (s.frame().origin.y + s.frame().size.height) for s in screens)
        bottom = max(main_h - s.frame().origin.y for s in screens)
        return (int(left), int(top), int(right - left), int(bottom - top))
    except Exception:                                   # noqa: BLE001
        return (0, 0, 1920, 1080)


def name_this_app() -> bool:
    """Call the menu-bar app "AutoStream" when running from source.

    A built .app is named by its Info.plist. From a checkout the process is
    Python, and the menu bar says so; setting the bundle name before the
    application object exists is the documented way round it.
    """
    try:
        from Foundation import NSBundle  # type: ignore

        info = NSBundle.mainBundle().infoDictionary()
        if info is not None and info.get("CFBundleName") != "AutoStream":
            info["CFBundleName"] = "AutoStream"
        return True
    except Exception as e:                              # noqa: BLE001
        log.debug("could not name the app: %s", e)
        return False


def _ask_to_quit(why: str) -> bool:
    """A modal "quit anyway?". -> True to quit. Main thread only."""
    try:
        from AppKit import NSAlert, NSAlertFirstButtonReturn  # type: ignore

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Quit AutoStream?")
        alert.setInformativeText_(f"{why[0].upper()}{why[1:]} is still running, "
                                  "and quitting now throws it away.")
        alert.addButtonWithTitle_("Keep working")
        alert.addButtonWithTitle_("Quit anyway")
        return alert.runModal() != NSAlertFirstButtonReturn
    except Exception as e:                              # noqa: BLE001
        log.debug("could not ask before quitting: %s", e)
        return True


class MacWindow(_window.MainWindow):
    """MainWindow with Mac manners. See the module docstring."""

    def __init__(self, url: str, title: str = "AutoStream",
                 busy: Callable[[], str] | None = None):
        super().__init__(url, title)
        # -> "" when idle, else what a quit would destroy ("a clip job").
        self._busy = busy or (lambda: "")

    def _on_closing(self):
        _window.save_geometry(self.win)
        if self._quit:
            return True
        why = ""
        try:
            why = self._busy()
        except Exception:                               # noqa: BLE001
            why = ""
        if why and threading.current_thread() is threading.main_thread():
            if not _ask_to_quit(why):
                log.info("quit cancelled: %s is still running", why)
                return False
        log.info("window closed - quitting%s", f" ({why} abandoned)" if why else "")
        self._asked_to_quit = True
        self._quit = True
        self._show.set()
        return True

    def _on_minimized(self):
        """To the Dock, like any Mac window. Not hidden: nothing could unhide it."""
        return None

    def run(self, hidden: bool = False) -> None:
        name_this_app()
        super().run(hidden=hidden)
