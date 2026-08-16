"""Process polling + game resolution. Does no network I/O, ever.

Four layered signals:
  1. process name match against the index        (primary)
  2. Steam RunningAppID registry key             (confirm / fill gaps)
  3. foreground window owner                     (which game are you ACTUALLY playing)
  4. unknown-exe reporting                       (suggestions for games.yaml)
"""
from __future__ import annotations

import logging
import time

import psutil

from .gameindex import GameHit, GameIndex

log = logging.getLogger("autostream.watch")

# Windows-only bits, imported lazily so the module stays importable elsewhere
try:  # pragma: no cover - platform dependent
    import win32gui
    import win32process

    _HAS_WIN32 = True
except ImportError:  # pragma: no cover
    _HAS_WIN32 = False

try:  # pragma: no cover
    import winreg

    _HAS_REG = True
except ImportError:  # pragma: no cover
    _HAS_REG = False


def foreground_pid() -> int | None:
    if not _HAS_WIN32:
        return None
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        return win32process.GetWindowThreadProcessId(hwnd)[1]
    except Exception:  # noqa: BLE001
        return None


def steam_running_appid() -> str | None:
    """Non-zero means Steam believes a game is running."""
    if not _HAS_REG:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            val, _ = winreg.QueryValueEx(k, "RunningAppID")
            return str(val) if val else None
    except OSError:
        return None


class Watcher:
    def __init__(self, config, index: GameIndex):
        self.cfg = config
        self.index = index
        self._candidates: dict[str, float] = {}   # game key -> first seen (monotonic)
        self._unknown_seen: dict[str, float] = {}
        self._last_running: dict[str, GameHit] = {}

    # ------------------------------------------------------------------

    def snapshot(self) -> tuple[dict[int, GameHit], list[str], bool]:
        """Return (pid -> hit, unknown_exes, veto_active) for this instant."""
        seen: dict[int, GameHit] = {}
        unknown: list[str] = []
        veto = False

        for p in psutil.process_iter(["pid", "name"]):
            try:
                exe = (p.info.get("name") or "").lower()
            except (psutil.Error, KeyError):
                continue
            if not exe:
                continue

            if self.index.is_veto(exe):
                veto = True
                continue
            if self.index.is_blocked(exe):
                continue

            hit = self.index.lookup(exe)
            if hit:
                seen[p.info["pid"]] = hit
            elif exe.endswith(".exe"):
                unknown.append(exe)

        return seen, unknown, veto

    # ------------------------------------------------------------------

    def active_game(self) -> GameHit | None:
        """The game we should be streaming RIGHT NOW, ignoring debounce.

        Foreground window wins; otherwise the longest-running match.
        """
        seen, unknown, veto = self.snapshot()
        self._note_unknown(unknown)

        if veto:
            log.warning("veto process running — refusing to consider any game")
            return None
        if not seen:
            self._last_running = {}
            return None

        fg = foreground_pid()
        if fg is not None and fg in seen:
            hit = seen[fg]
        else:
            hit = seen[min(seen)]   # lowest PID ~= earliest started

        # Steam can name a game our index missed
        if hit.source == "public" or hit.name.lower().endswith(".exe"):
            appid = steam_running_appid()
            if appid and appid != "0":
                sname = self.index.steam_name(appid)
                if sname:
                    hit = GameHit(key=hit.key, name=sname, scene=hit.scene,
                                  blurb=hit.blurb, privacy=hit.privacy, source="steam")

        self._last_running = {h.key: h for h in seen.values()}
        return hit

    def armed_game(self) -> GameHit | None:
        """Same as active_game(), but only after it survives arm_delay."""
        hit = self.active_game()
        now = time.monotonic()

        if hit is None:
            self._candidates.clear()
            return None

        first = self._candidates.setdefault(hit.key, now)
        # forget candidates that vanished
        for k in list(self._candidates):
            if k not in self._last_running:
                self._candidates.pop(k, None)

        if now - first < self.cfg.timing.arm_delay:
            log.debug("arming %s (%.0fs / %ds)", hit.name,
                      now - first, self.cfg.timing.arm_delay)
            return None
        return hit

    def reset_debounce(self) -> None:
        """Forget in-progress arm timers.

        Called when a session ends so the NEXT one has to serve the full
        arm_delay again, instead of inheriting a timer that already expired.
        """
        self._candidates.clear()

    def any_game_running(self) -> bool:
        seen, _, _ = self.snapshot()
        return bool(seen)

    # ------------------------------------------------------------------

    def _note_unknown(self, unknown: list[str]) -> None:
        """Track unindexed exes so `detect` can suggest games.yaml entries."""
        now = time.monotonic()
        for exe in unknown:
            self._unknown_seen.setdefault(exe, now)

    def unknown_candidates(self, min_seconds: int = 120) -> list[str]:
        now = time.monotonic()
        return sorted(e for e, t in self._unknown_seen.items() if now - t >= min_seconds)
