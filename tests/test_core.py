"""Offline tests for the platform-independent logic.

Run:  python -m pytest tests/ -q      (or just: python tests/test_core.py)
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import cfg, titles  # noqa: E402
from autostream.gameindex import GameHit, _basename  # noqa: E402
from autostream.state import IDLE, LIVE, State  # noqa: E402

FAILS: list[str] = []


def check(label: str, cond: bool, extra: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('  -> ' + extra) if extra and not cond else ''}")
    if not cond:
        FAILS.append(label)


# ---------------------------------------------------------------- config

def test_config():
    print("\nconfig")
    c = cfg.load()
    check("loads config.yaml", isinstance(c, dict))
    check("dotted access", c.timing.poll_interval == 3, str(c.timing.poll_interval))
    check("nested defaults merge", c.rules.quota_reserve == 500)
    check("obs password from env falls back to ''", isinstance(c.obs_password, str))
    os.environ["AUTOSTREAM_OBS_PW"] = "hunter2"
    c2 = cfg.load()
    check("obs password read from env", c2.obs_password == "hunter2", c2.obs_password)
    del os.environ["AUTOSTREAM_OBS_PW"]

    games = cfg.load_games()
    check("games.yaml has blocklist", len(games["blocklist"]) > 10)
    check("launchers blocked", "steam.exe" in games["blocklist"])
    check("obs blocked", "obs64.exe" in games["blocklist"])


# ---------------------------------------------------------------- titles

def test_titles():
    print("\ntitles")
    c = cfg.load()
    v = titles.build_vars(
        game="ELDEN RING", hook="grinding it out",
        session_games=["ELDEN RING", "Factorio"],
        session_start=datetime(2026, 8, 14, 21, 30),
        session_number=47, blurb="NG+2",
        now=datetime(2026, 8, 14, 21, 30),
    )
    t = titles.render_title(c, v)
    check("renders game name", "ELDEN RING" in t, t)
    check("renders hook", "grinding it out" in t, t)
    check("renders weekday", "Friday" in t, t)
    check("under 100 chars", len(t) <= 100, str(len(t)))

    d = titles.render_description(c, v)
    check("description has both games", "Factorio" in d and "ELDEN RING" in d)
    check("hashtag stripped", "#ELDENRING" in d, d)

    check("truncate word boundary",
          titles.truncate("a" * 10 + " bbbb cccc dddd", 20) == "aaaaaaaaaa bbbb…",
          titles.truncate("a" * 10 + " bbbb cccc dddd", 20))
    check("truncate no-op when short", titles.truncate("hello", 100) == "hello")
    check("truncate trims dangling dash", not titles.truncate("Game — hook here", 9).endswith("—"),
          titles.truncate("Game — hook here", 9))
    check("hashtagify strips symbols", titles.hashtagify("Baldur's Gate 3!") == "BaldursGate3")
    check("hashtagify empty fallback", titles.hashtagify("!!!") == "gaming")

    # unknown placeholder must not raise
    class FakeCfg(dict):
        pass
    c3 = cfg.load()
    c3["title"] = dict(c3["title"])
    c3["title"]["template"] = "{game} {nonexistent} x"
    out = titles.render_title(cfg.Config(c3), v)
    check("unknown placeholder renders empty", "ELDEN RING" in out and "{" not in out, out)


# ---------------------------------------------------------------- index

def test_index_helpers():
    print("\ngameindex")
    check("basename windows path",
          _basename("steamapps/common/Elden Ring/eldenring.exe") == "eldenring.exe")
    check("basename backslash",
          _basename(r"C:\Games\X\Game.EXE") == "game.exe")
    check("basename bare", _basename("game.exe") == "game.exe")
    a = GameHit(key="x.exe", name="A")
    b = GameHit(key="x.exe", name="B")
    check("hits compare by key", a == b)


# ---------------------------------------------------------------- state

def test_state():
    print("\nstate")
    from autostream import paths

    with tempfile.TemporaryDirectory() as td:
        orig = paths.STATE_FILE
        paths.STATE_FILE = Path(td) / "state.json"
        try:
            s = State()
            check("default phase IDLE", s.phase == IDLE)
            s.phase = LIVE
            s.broadcast_id = "abc123"
            s.session_games = ["A", "B"]
            s.save()
            check("state file written", paths.STATE_FILE.exists())

            s2 = State.load()
            check("round-trips phase", s2.phase == LIVE)
            check("round-trips broadcast", s2.broadcast_id == "abc123")
            check("round-trips list", s2.session_games == ["A", "B"])

            s2.reset_session()
            check("reset clears broadcast", s2.broadcast_id is None and s2.phase == IDLE)

            s2.spend(50)
            s2.spend(200)
            check("quota accumulates", s2.quota_spent == 250, str(s2.quota_spent))
            check("quota_left correct", s2.quota_left(10000) == 9750, str(s2.quota_left(10000)))

            # unknown keys in an old state file must not explode
            paths.STATE_FILE.write_text('{"phase":"LIVE","bogus_key":1}')
            s3 = State.load()
            check("tolerates unknown keys", s3.phase == LIVE)

            paths.STATE_FILE.write_text("{ not json")
            s4 = State.load()
            check("tolerates corrupt file", s4.phase == IDLE)
        finally:
            paths.STATE_FILE = orig


# ---------------------------------------------------------------- engine gating

def test_quiet_hours():
    print("\nengine gating")
    from autostream.engine import Engine

    c = cfg.load()
    c["rules"] = dict(c["rules"])
    c["rules"]["quiet_hours"] = ["01:30", "09:00"]
    eng = Engine.__new__(Engine)          # no __init__ — we only test the predicate
    eng.cfg = cfg.Config(c)

    cases = [
        (datetime(2026, 8, 14, 2, 0), True, "02:00 inside overnight window"),
        (datetime(2026, 8, 14, 8, 59), True, "08:59 inside"),
        (datetime(2026, 8, 14, 9, 0), False, "09:00 boundary is outside"),
        (datetime(2026, 8, 14, 21, 0), False, "21:00 outside"),
        (datetime(2026, 8, 14, 1, 29), False, "01:29 just before"),
        (datetime(2026, 8, 14, 1, 30), True, "01:30 boundary is inside"),
    ]
    for when, expected, label in cases:
        check(label, eng._in_quiet_hours(when) is expected)

    c["rules"]["quiet_hours"] = ["09:00", "17:00"]
    eng.cfg = cfg.Config(c)
    check("daytime window: 12:00 inside", eng._in_quiet_hours(datetime(2026, 8, 14, 12, 0)))
    check("daytime window: 20:00 outside",
          not eng._in_quiet_hours(datetime(2026, 8, 14, 20, 0)))

    c["rules"]["quiet_hours"] = []
    eng.cfg = cfg.Config(c)
    check("empty quiet_hours disables", not eng._in_quiet_hours(datetime(2026, 8, 14, 3, 0)))


# ---------------------------------------------------------------- watcher

def test_watcher_debounce():
    print("\nwatcher debounce")
    from autostream.watcher import Watcher

    class FakeIndex:
        def is_veto(self, exe): return False
        def is_blocked(self, exe): return exe in ("steam.exe",)
        def lookup(self, exe):
            return GameHit(key=exe, name="Test Game") if exe == "game.exe" else None
        def steam_name(self, appid): return None

    c = cfg.load()
    c["timing"] = dict(c["timing"])
    c["timing"]["arm_delay"] = 30
    w = Watcher(cfg.Config(c), FakeIndex())

    hit = GameHit(key="game.exe", name="Test Game")
    w.active_game = lambda: hit                    # type: ignore[method-assign]
    w._last_running = {"game.exe": hit}

    check("not armed immediately", w.armed_game() is None)
    w._candidates["game.exe"] -= 31                # pretend 31s elapsed
    check("armed after arm_delay", w.armed_game() is not None)

    w.active_game = lambda: None                   # type: ignore[method-assign]
    check("clears candidates when game gone", w.armed_game() is None)
    check("candidate dict emptied", w._candidates == {})


def test_detectable_parser():
    print("\ngameindex parser (schema drift tolerance)")
    from autostream.gameindex import _parse_detectable

    discord = [
        {"name": "ELDEN RING",
         "executables": [{"name": "eldenring.exe", "os": "win32"},
                         {"name": "start_protected_game.exe", "os": "win32",
                          "is_launcher": True},
                         {"name": "eldenring", "os": "darwin"}]},
        {"name": "Factorio",
         "executables": [{"name": "bin/x64/factorio.exe", "os": "win32"}]},
        {"name": "", "executables": [{"name": "junk.exe", "os": "win32"}]},
    ]
    out = _parse_detectable(discord)
    check("parses discord shape", out.get("eldenring.exe") == "ELDEN RING", str(out))
    check("strips path prefix", out.get("factorio.exe") == "Factorio", str(out))
    check("skips launchers", "start_protected_game.exe" not in out)
    check("skips non-win32", len([k for k in out if not k.endswith(".exe")]) == 0)
    check("skips nameless apps", "junk.exe" not in out)

    check("tolerates dict wrapper",
          _parse_detectable({"applications": discord}).get("factorio.exe") == "Factorio")
    check("tolerates plain string execs",
          _parse_detectable([{"name": "X", "executables": "x.exe"}]).get("x.exe") == "X")
    check("tolerates garbage", _parse_detectable("nonsense") == {})
    check("tolerates None", _parse_detectable(None) == {})
    check("tolerates list of junk", _parse_detectable([1, "a", None]) == {})


def test_coverage_warning():
    print("\ngameindex coverage warning")
    from autostream.gameindex import GameIndex

    idx = GameIndex.__new__(GameIndex)
    idx.overrides, idx.public = {}, {}
    check("warns when totally empty", idx.coverage_warning() is not None)
    idx.public = {"a.exe": "A"}
    check("silent with public index", idx.coverage_warning() is None)
    idx.public, idx.overrides = {}, {"a.exe": {"name": "A"}}
    check("silent with overrides only", idx.coverage_warning() is None)


def main() -> int:
    print("=" * 60)
    print("  AutoStream offline test suite")
    print("=" * 60)
    test_config()
    test_titles()
    test_index_helpers()
    test_detectable_parser()
    test_coverage_warning()
    test_state()
    test_quiet_hours()
    test_watcher_debounce()
    print("\n" + "=" * 60)
    if FAILS:
        print(f"  {len(FAILS)} FAILED:")
        for f in FAILS:
            print(f"    - {f}")
        return 1
    print("  ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
