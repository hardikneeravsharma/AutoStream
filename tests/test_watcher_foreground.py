"""A background process must never be enough to start a public broadcast.

THE INCIDENT. Running `gh` in a terminal put a live stream on somebody's
YouTube channel, titled "Green Hell". The public game index matches on the
bare executable name and short names collide badly with ordinary tools:

    gh.exe      -> Green Hell        the GitHub CLI
    rg.exe      -> Retro Gadgets     ripgrep
    dotnet.exe  -> tModLoader        the .NET runtime, which idles on many PCs
    ninja.exe   -> Mini Ninjas       the build tool

Two things were wrong. The index called those tools games, and -- worse --
`active_game` fell back to the lowest-PID match when nothing recognised was in
the foreground, so a process with no window at all became "the game you are
playing". The README promises nothing goes public by surprise.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import watcher as w                             # noqa: E402
from autostream.gameindex import GameHit                        # noqa: E402


class FakeIndex:
    def is_veto(self, exe):
        return False

    def is_blocked(self, exe):
        return False

    def steam_name(self, appid):
        return None


def a_watcher(monkeypatch, seen, fg=None, title="", fg_ever=()):
    wt = w.Watcher.__new__(w.Watcher)
    wt.index = FakeIndex()
    wt._candidates, wt._unknown_seen, wt._last_running = {}, {}, {}
    wt._said_bg = wt._said_title = ""
    wt._fg_ever = set(fg_ever)
    monkeypatch.setattr(w.Watcher, "snapshot", lambda self: (seen, [], False))
    monkeypatch.setattr(w, "foreground_pid", lambda: fg)
    monkeypatch.setattr(w, "foreground_title", lambda: title)
    monkeypatch.setattr(w, "steam_running_appid", lambda: None)
    return wt


def test_a_background_public_match_is_not_a_game(monkeypatch):
    """The bug, exactly as it happened: gh.exe running with no window."""
    seen = {4242: GameHit(key="gh.exe", name="Green Hell", source="public")}
    assert a_watcher(monkeypatch, seen, fg=None).active_game() is None


def test_every_tool_that_collided_is_refused_in_the_background(monkeypatch):
    for exe, name in (("gh.exe", "Green Hell"), ("rg.exe", "Retro Gadgets"),
                      ("dotnet.exe", "tModLoader"), ("ninja.exe", "Mini Ninjas")):
        seen = {7: GameHit(key=exe, name=name, source="public")}
        got = a_watcher(monkeypatch, seen, fg=None).active_game()
        assert got is None, f"{exe} would still have gone live"


def test_the_same_match_IS_a_game_when_it_is_on_screen(monkeypatch):
    """The guard must not cost anything in the case it exists to serve: a game
    someone is actually playing owns the foreground window."""
    seen = {4242: GameHit(key="gh.exe", name="Green Hell", source="public")}
    got = a_watcher(monkeypatch, seen, fg=4242).active_game()
    assert got is not None and got.name == "Green Hell"


def test_an_override_gets_no_exemption_either(monkeypatch):
    """The hole that lost a three-hour Valorant session.

    The first fix exempted overrides, reasoning that an override is the user's
    own word. It is -- about the NAME. It says nothing about a stale copy still
    running being what you are playing now, and a leftover cs2.exe (an
    override) labelled 174 minutes of Valorant as Counter-Strike 2.
    """
    seen = {9: GameHit(key="cs2.exe", name="Counter-Strike 2", source="override")}
    got = a_watcher(monkeypatch, seen, fg=None).active_game()
    assert got is None


def test_a_game_you_alt_tabbed_away_from_is_still_the_game(monkeypatch):
    """The guard must not end a session because you opened Discord."""
    seen = {9: GameHit(key="cs2.exe", name="Counter-Strike 2", source="override")}
    wt = a_watcher(monkeypatch, seen, fg=None, fg_ever=["cs2.exe"])
    got = wt.active_game()
    assert got is not None and got.name == "Counter-Strike 2"


def test_being_in_front_once_is_remembered(monkeypatch):
    """It is the same journey in two ticks: in front, then behind."""
    seen = {9: GameHit(key="cs2.exe", name="Counter-Strike 2", source="override")}
    wt = a_watcher(monkeypatch, seen, fg=9)
    assert wt.active_game() is not None          # in front
    monkeypatch.setattr(w, "foreground_pid", lambda: None)
    assert wt.active_game() is not None          # now behind, still the game


# ------------------------------------------------- a game the OS hides

def test_valorant_is_found_by_its_window_title(monkeypatch):
    """Vanguard hides the process, so psutil never lists it. The only facts
    left are that something owns the foreground and what it is called."""
    class Idx(FakeIndex):
        def lookup(self, exe):
            return (GameHit(key=exe, name="VALORANT", source="override")
                    if exe == "valorant-win64-shipping.exe" else None)

    seen = {9: GameHit(key="cs2.exe", name="Counter-Strike 2", source="override")}
    wt = a_watcher(monkeypatch, seen, fg=None, title="VALORANT")
    wt.index = Idx()
    got = wt.active_game()
    assert got is not None and got.name == "VALORANT",         "the leftover cs2.exe won again"


def test_a_browser_reading_about_valorant_is_not_playing_it(monkeypatch):
    """A title is a far weaker signal than an executable name, so it has to
    match as a whole word and nothing else may lean on it."""
    class Idx(FakeIndex):
        def lookup(self, exe):
            return GameHit(key=exe, name="VALORANT", source="override")

    wt = a_watcher(monkeypatch, {}, fg=None,
                   title="valorantstrategies.gg - best crosshair codes")
    wt.index = Idx()
    assert wt._hidden_foreground() is None


def test_the_foreground_game_still_wins_over_an_older_process(monkeypatch):
    seen = {1: GameHit(key="a.exe", name="Older", source="public"),
            2: GameHit(key="b.exe", name="In Front", source="public")}
    got = a_watcher(monkeypatch, seen, fg=2).active_game()
    assert got is not None and got.name == "In Front"


def test_the_developer_tools_are_in_the_shipped_blocklist():
    """Defence in depth: the foreground rule stops the broadcast, and the
    blocklist stops them being considered at all."""
    import yaml

    raw = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "config" / "games.yaml")
        .read_text(encoding="utf-8")) or {}
    blocked = {str(x).lower() for x in (raw.get("blocklist") or [])}
    for exe in ("gh.exe", "rg.exe", "dotnet.exe", "ninja.exe"):
        assert exe in blocked, f"{exe} is not blocked"
