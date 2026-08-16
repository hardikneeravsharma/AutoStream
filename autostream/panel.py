"""Always-on-top control panel.

Runs on the MAIN thread (tkinter requires it); the engine runs on a worker
thread. The panel never calls YouTube or OBS directly — it posts commands to
engine.submit() and reads engine.state for display. That keeps every
side effect on the engine thread and avoids races.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
import webbrowser

from . import paths

log = logging.getLogger("autostream.panel")

try:
    import tkinter as tk
    from tkinter import font as tkfont

    _HAS_TK = True
except ImportError:  # pragma: no cover
    _HAS_TK = False

BG = "#11161d"
CARD = "#1a212b"
LINE = "#2a3441"
FG = "#e6edf3"
DIM = "#8b98a8"
BTN = "#232c38"
BTN_HOVER = "#2e3a49"

PHASE_COLOUR = {
    "IDLE": "#6e7d8f",
    "ARMING": "#d29922",
    "STARTING": "#d29922",
    "TESTING": "#a371f7",
    "LIVE": "#ff4d4d",
    "COOLDOWN": "#4d9fff",
    "STOPPING": "#8b98a8",
}
PHASE_LABEL = {
    "IDLE": "Idle",
    "ARMING": "Arming",
    "STARTING": "Starting",
    "TESTING": "Going live",
    "LIVE": "LIVE",
    "COOLDOWN": "Cooldown",
    "STOPPING": "Stopping",
}


def _fmt_elapsed(start: float | None) -> str:
    if not start:
        return "--:--:--"
    s = max(0, int(time.time() - start))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


class Button(tk.Frame if _HAS_TK else object):  # type: ignore[misc]
    """Flat button — ttk theming on Windows won't do dark backgrounds."""

    def __init__(self, parent, text, command, accent=None, width=13):
        super().__init__(parent, bg=BTN, highlightthickness=0, cursor="hand2")
        self._cmd = command
        self._enabled = True
        self._base = BTN
        self.label = tk.Label(self, text=text, bg=BTN, fg=accent or FG,
                              font=("Segoe UI", 9, "bold"), width=width,
                              pady=7, cursor="hand2")
        self.label.pack(fill="both", expand=True)
        for w in (self, self.label):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

    def _click(self, _e=None):
        if self._enabled:
            self._cmd()

    def _enter(self, _e=None):
        if self._enabled:
            self.config(bg=BTN_HOVER)
            self.label.config(bg=BTN_HOVER)

    def _leave(self, _e=None):
        self.config(bg=self._base)
        self.label.config(bg=self._base)

    def set_enabled(self, on: bool):
        self._enabled = on
        self.label.config(fg=FG if on else "#4a5563")


class ControlPanel:
    def __init__(self, engine):
        self.engine = engine
        self.root = None
        self._drag = (0, 0)
        # Set by the tray thread. tkinter is not thread-safe, so cross-thread
        # requests are flags polled by refresh() on the main thread.
        self.show_requested = False
        # set by cmd_run; opens the main window from the overlay
        self.open_window = None

    # ------------------------------------------------------------------

    def build(self):
        self.root = tk.Tk()
        r = self.root
        r.title("AutoStream")
        r.configure(bg=BG)
        r.attributes("-topmost", True)
        r.overrideredirect(False)
        r.resizable(False, False)
        try:
            r.attributes("-alpha", 0.97)
        except tk.TclError:
            pass

        # bottom-right of the primary screen
        w, h = 268, 232
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        r.geometry(f"{w}x{h}+{sw - w - 24}+{sh - h - 72}")

        outer = tk.Frame(r, bg=BG, padx=14, pady=12)
        outer.pack(fill="both", expand=True)

        # --- status row ---
        top = tk.Frame(outer, bg=BG)
        top.pack(fill="x")
        self.dot = tk.Canvas(top, width=12, height=12, bg=BG, highlightthickness=0)
        self.dot_id = self.dot.create_oval(1, 1, 11, 11, fill=PHASE_COLOUR["IDLE"], width=0)
        self.dot.pack(side="left", pady=(3, 0))
        self.phase_lbl = tk.Label(top, text="Idle", bg=BG, fg=FG,
                                  font=("Segoe UI", 12, "bold"))
        self.phase_lbl.pack(side="left", padx=(8, 0))
        self.viewers_lbl = tk.Label(top, text="", bg=BG, fg=DIM, font=("Segoe UI", 9))
        self.viewers_lbl.pack(side="right", pady=(4, 0))

        self.game_lbl = tk.Label(outer, text="no game", bg=BG, fg=DIM,
                                 font=("Segoe UI", 10), anchor="w")
        self.game_lbl.pack(fill="x", pady=(4, 0))

        self.elapsed_lbl = tk.Label(outer, text="--:--:--", bg=BG, fg=FG,
                                    font=("Consolas", 18), anchor="w")
        self.elapsed_lbl.pack(fill="x", pady=(2, 8))

        tk.Frame(outer, bg=LINE, height=1).pack(fill="x", pady=(0, 10))

        # --- buttons ---
        row1 = tk.Frame(outer, bg=BG)
        row1.pack(fill="x")
        self.btn_stop = Button(row1, "End stream", self._end, accent="#ff6b6b")
        self.btn_stop.pack(side="left")
        self.btn_pause = Button(row1, "Pause", self._toggle_pause)
        self.btn_pause.pack(side="right")

        row2 = tk.Frame(outer, bg=BG)
        row2.pack(fill="x", pady=(6, 0))
        self.btn_open = Button(row2, "Open stream", self._open_stream)
        self.btn_open.pack(side="left")
        Button(row2, "Dashboard", self._open_main).pack(side="right")

        # --- footer ---
        self.foot = tk.Label(outer, text="", bg=BG, fg="#5c6875",
                             font=("Segoe UI", 8), anchor="w")
        self.foot.pack(fill="x", pady=(10, 0))

        # drag anywhere on the background to move the window
        for w in (outer, self.phase_lbl, self.game_lbl, self.elapsed_lbl):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

        r.protocol("WM_DELETE_WINDOW", self._hide)
        r.bind("<Escape>", lambda _e: self._hide())
        return r

    # ------------------------------------------------------------------
    # actions - all go through the queue, none touch YouTube/OBS here
    # ------------------------------------------------------------------

    def _end(self):
        self.engine.submit("stop")

    def _toggle_pause(self):
        self.engine.submit("toggle_pause")

    def _open_stream(self):
        bid = self.engine.state.broadcast_id
        if bid:
            webbrowser.open(f"https://www.youtube.com/watch?v={bid}")

    def _open_main(self):
        if callable(self.open_window):
            self.open_window()

    def _open_logs(self):
        try:
            if os.name == "nt":
                os.startfile(str(paths.LOG_FILE))  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(paths.LOG_FILE)])
        except Exception as e:  # noqa: BLE001
            log.warning("could not open logs: %s", e)

    def _hide(self):
        """Closing the window hides it; the tray icon brings it back."""
        if self.root:
            self.root.withdraw()

    def show(self):
        if self.root:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)

    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    # ------------------------------------------------------------------

    def refresh(self):
        # shutdown was requested elsewhere (tray quit / SIGINT) — leave mainloop
        if getattr(self.engine, "_stop_requested", False):
            self.root.quit()
            return
        if self.show_requested:
            self.show_requested = False
            self.show()

        s = self.engine.state
        phase = s.phase
        live_ish = phase in ("STARTING", "TESTING", "LIVE", "COOLDOWN")

        colour = PHASE_COLOUR.get(phase, DIM)
        label = PHASE_LABEL.get(phase, phase)
        if s.paused:
            colour, label = "#d29922", "Paused"

        self.dot.itemconfig(self.dot_id, fill=colour)
        self.phase_lbl.config(text=label, fg=colour if phase == "LIVE" else FG)
        blocked = getattr(self.engine, "blocked_reason", None)
        if phase == "IDLE" and blocked:
            self.game_lbl.config(text=f"blocked: {blocked}", fg="#d29922")
        else:
            self.game_lbl.config(text=s.current_game or "no game", fg=DIM)
        self.elapsed_lbl.config(text=_fmt_elapsed(s.session_start))

        v = getattr(self.engine, "viewers", None)
        self.viewers_lbl.config(
            text=f"{v} watching" if (v is not None and phase == "LIVE") else "")

        self.btn_stop.set_enabled(live_ish)
        self.btn_open.set_enabled(bool(s.broadcast_id))
        self.btn_pause.label.config(text="Resume" if s.paused else "Pause")

        self.foot.config(
            text=f"session #{s.session_number}   ·   quota {s.quota_spent}/10000")

        # Other apps (and games entering borderless) can steal topmost. Re-assert
        # it every ~5s. This does NOT steal focus, so it is safe mid-game.
        # Note: nothing can float above EXCLUSIVE fullscreen — that is a Windows
        # compositor limitation, not something a window can override. Use
        # "Fullscreen Windowed" in the game for the panel to be visible.
        self._tick = getattr(self, "_tick", 0) + 1
        if self._tick % 5 == 0:
            try:
                self.root.attributes("-topmost", True)
            except tk.TclError:
                pass

        self.root.after(1000, self.refresh)

    def run(self):
        """Blocks on the tkinter main loop. Call from the main thread."""
        self.build()
        self.refresh()
        self.root.mainloop()

    def stop(self):
        if self.root:
            try:
                self.root.quit()
            except Exception:  # noqa: BLE001
                pass


def available() -> bool:
    return _HAS_TK
