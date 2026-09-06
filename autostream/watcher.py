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


def foreground_title() -> str:
    """The title of the window in front. "" when it cannot be read."""
    if not _HAS_WIN32:
        return ""
    try:
        hwnd = win32gui.GetForegroundWindow()
        return win32gui.GetWindowText(hwnd) if hwnd else ""
    except Exception:  # noqa: BLE001
        return ""


# GAMES WHOSE PROCESS CANNOT BE SEEN AT ALL, matched on the window title
# instead. Valorant runs behind Vanguard, a kernel anti-cheat driver that hides
# the process from ordinary enumeration -- psutil simply never lists it. So the
# only two facts available are that SOMETHING owns the foreground window and
# what that window is called.
#
# This is not a general fallback and must not become one: a title is a much
# weaker signal than an executable name, and "VALORANT" in a browser tab would
# match. It is a short list of games that genuinely cannot be detected any
# other way, and every entry needs a reason.
#
# What it cost to not have: a 174-minute session was labelled Counter-Strike 2
# throughout, because a leftover cs2.exe was the only thing visible while
# Valorant was actually on screen. The stream was titled and thumbnailed for
# the wrong game, and -- worse -- Valorant's match records are only fetched
# while its own profile is the current game, so three hours of exact kill data
# was never asked for while the client sat there able to answer.
TITLE_HINTS: dict[str, str] = {
    "valorant": "valorant-win64-shipping.exe",
}


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
        # So the background-match line is logged once per exe, not every tick.
        self._said_bg = ""
        # Games that have owned the foreground window since AutoStream started.
        # A match that has never been in front is not what you are playing.
        self._fg_ever: set[str] = set()
        self._said_title = ""

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
            self._fg_ever.add(hit.key)
        elif (hidden := self._hidden_foreground()) is not None:
            hit = hidden
            self._fg_ever.add(hit.key)
        else:
            # NOTHING RECOGNISED IS ON SCREEN. What used to happen here was
            # that the longest-running match won, which meant a background
            # process with no window became "the game you are playing". Two
            # real incidents came out of that: `gh` in a terminal started a
            # public broadcast titled Green Hell, and a leftover cs2.exe
            # labelled a three-hour Valorant session as Counter-Strike 2.
            #
            # A game may legitimately be behind another window -- you alt-tab
            # to Discord mid-match -- so this cannot simply refuse. What it can
            # require is that the game was IN FRONT at some point since
            # AutoStream started. Alt-tabbing away does not change what you are
            # playing; a tool you never looked at was never a game.
            #
            # Deliberately not limited to public-index hits. The first version
            # of this exempted overrides, on the grounds that an override is
            # the user's own word -- but an override only says the NAME is
            # right, not that a stale copy of it is what you are playing now,
            # and the Valorant session above was lost to exactly that hole.
            live = {p: h for p, h in seen.items() if h.key in self._fg_ever}
            if not live:
                first = seen[min(seen)]
                if self._said_bg != first.key:
                    self._said_bg = first.key
                    log.info("%s (%s) is running but has never been the "
                             "foreground window, so it is not treated as the "
                             "game being played", first.name, first.key)
                return None
            hit = live[min(live)]
        self._said_bg = ""

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

    def _hidden_foreground(self) -> GameHit | None:
        """The foreground game when its process cannot be enumerated.

        Only for the handful in TITLE_HINTS, and only when the title is a
        whole word in the window name -- so a browser tab reading "valorant
        pro settings" does not count as playing it.
        """
        title = foreground_title().strip().lower()
        if not title:
            return None
        # WHOLE WORDS, not a substring. A browser tab reading
        # "valorantstrategies.gg" contains "valorant" and is not somebody
        # playing it. Split on anything not alphanumeric rather than reach
        # for a regex: the test that matters is membership, and this says so.
        words = set("".join(c if c.isalnum() else " " for c in title).split())

        for needle, exe in TITLE_HINTS.items():
            if needle not in words:
                continue
            if self.index.is_blocked(exe) or self.index.is_veto(exe):
                return None
            hit = self.index.lookup(exe)
            if hit:
                if self._said_title != exe:
                    self._said_title = exe
                    log.info("%s is the foreground window (%r); its process is "
                             "hidden by anti-cheat, so it is identified by "
                             "title", hit.name, title[:40])
                return hit
        return None

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
