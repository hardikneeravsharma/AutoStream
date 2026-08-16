"""Optional system tray icon. Degrades to a no-op if pystray/Pillow missing."""
from __future__ import annotations

import logging
import os
import subprocess
import threading

from . import paths

log = logging.getLogger("autostream.tray")

try:  # pragma: no cover
    import pystray
    from PIL import Image, ImageDraw

    _HAS = True
except ImportError:  # pragma: no cover
    _HAS = False

PHASE_COLOURS = {
    "IDLE": (110, 125, 143),
    "ARMING": (210, 153, 34),
    "STARTING": (210, 153, 34),
    "TESTING": (163, 113, 247),
    "LIVE": (255, 77, 77),
    "COOLDOWN": (77, 159, 255),
    "STOPPING": (110, 125, 143),
}


def _icon_image(colour):  # pragma: no cover
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=colour)
    d.ellipse((22, 22, 42, 42), fill=(255, 255, 255, 230))
    return img


class Tray:
    """Runs pystray on its own thread; the engine keeps the main thread."""

    def __init__(self, engine, panel=None):
        self.engine = engine
        self.panel = panel
        self.window = None
        self.icon = None
        self._thread = None

    def start(self) -> None:
        if not _HAS or not self.engine.cfg.rules.tray_icon:
            log.info("tray icon disabled or unavailable")
            return
        menu = pystray.Menu(
            pystray.MenuItem(lambda i: f"Phase: {self.engine.state.phase}", None, enabled=False),
            pystray.MenuItem(lambda i: f"Game: {self.engine.state.current_game or '—'}",
                             None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open AutoStream", self._open_window, default=True),
            pystray.MenuItem("Show overlay", self._show_panel,
                             visible=self.panel is not None),
            pystray.MenuItem(
                lambda i: "Resume" if self.engine.state.paused else "Pause",
                self._toggle_pause),
            pystray.MenuItem("End stream", self._force_stop),
            pystray.MenuItem("Open logs", self._open_logs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit AutoStream", self._quit),
        )
        self.icon = pystray.Icon("autostream", _icon_image(PHASE_COLOURS["IDLE"]),
                                 "AutoStream", menu)
        self._thread = threading.Thread(target=self.icon.run, daemon=True)
        self._thread.start()
        log.info("tray icon started")

    def refresh(self) -> None:
        if self.icon is None:
            return
        try:
            phase = self.engine.state.phase
            self.icon.icon = _icon_image(PHASE_COLOURS.get(phase, (110, 125, 143)))
            self.icon.title = f"AutoStream — {phase}"
            self.icon.update_menu()
        except Exception:  # noqa: BLE001
            pass

    # --- menu handlers ---

    def _open_window(self, *_):
        if self.window is not None:
            self.window.request_show()

    def _show_panel(self, *_):
        # tkinter is not thread-safe; the panel polls this flag on its own thread
        if self.panel is not None:
            self.panel.show_requested = True

    def _toggle_pause(self, *_):
        self.engine.submit("toggle_pause")
        self.refresh()

    def _force_stop(self, *_):
        self.engine.submit("stop")
        self.refresh()

    def _open_logs(self, *_):
        try:
            if os.name == "nt":
                os.startfile(str(paths.LOG_FILE))  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(paths.LOG_FILE)])
        except Exception as e:  # noqa: BLE001
            log.warning("could not open logs: %s", e)

    def _quit(self, *_):
        # Order matters: the window owns the main thread, so it must be told to
        # go before anything waits on it.
        if self.window is not None:
            self.window.request_quit()
        self.engine.request_stop()
        if self.icon:
            self.icon.stop()
