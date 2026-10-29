"""The Library's two switches, and the cover beside each game.

RECORDS is whether AutoStream treats the executable as a game at all -- the
same question the watcher asks of games.yaml (`games:` says yes, `blocklist:`
says no, and the blocklist wins). GOES LIVE is the catalogue's `stream` flag,
which offers "Open + stream" on the row.

Both used to be hand edits to a YAML file, which is why the Library listed
Command Prompt and Character Map among the games with no way to move them.
"""
from __future__ import annotations

import types

import pytest
import yaml

from autostream import catalog, cfg, paths


class _Index:
    """The engine's GameIndex, as far as these routes reach it: a lookup the
    public list answers, and a reload the route must call so the running
    watcher sees the change without a restart."""

    def __init__(self, public=()):
        self.public = {e.lower() for e in public}
        self.reloads = 0

    def lookup(self, exe):
        return object() if (exe or "").lower() in self.public else None

    def reload(self):
        self.reloads += 1


APPS = [
    catalog.App(key="cs2", name="Counter-Strike 2", path="C:/g/cs2.exe",
                exe="cs2.exe", source="steam", stream=True),
    catalog.App(key="charmap", name="Character Map", path="C:/w/charmap.exe",
                exe="charmap.exe", source="shortcut", stream=False),
    catalog.App(key="steam", name="Steam", path="C:/s/steam.exe",
                exe="steam.exe", source="shortcut", stream=False),
]


@pytest.fixture
def lib(tmp_path, monkeypatch):
    games = tmp_path / "games.yaml"
    games.write_text(yaml.safe_dump({
        "games": {"cs2.exe": {"name": "Counter-Strike 2",
                              "thumbnail": "C:/art/cs2.png"}},
        "blocklist": ["steam.exe", "*banking*"],
        "never_stream_if_running": [],
    }), encoding="utf-8")
    monkeypatch.setattr(paths, "GAMES_FILE", games)
    saved: dict = {}
    apps = [catalog.App(**a.as_dict()) for a in APPS]
    monkeypatch.setattr(catalog, "load", lambda: apps)
    monkeypatch.setattr(catalog, "save", lambda xs: saved.update(apps=list(xs)))

    from fakes import LiveServer

    index = _Index(public=["cs2.exe"])
    srv = LiveServer(engine=types.SimpleNamespace(index=index))
    srv.index, srv.saved, srv.apps = index, saved, apps
    try:
        yield srv
    finally:
        srv.close()


def _row(srv, key):
    return next(a for a in srv.srv.apps_payload() if a["key"] == key)


# ------------------------------------------------------------------ Records

def test_records_off_blocks_the_exe_and_keeps_its_settings(lib):
    r = lib.post("/api/library/game", {"key": "cs2", "game": False})
    assert r.status == 200 and r.json()["ok"] is True
    data = cfg.load_games()
    assert "cs2.exe" in data["blocklist"]
    # The thumbnail and name stay: switching back on must not lose them.
    assert data["games"]["cs2.exe"]["thumbnail"] == "C:/art/cs2.png"
    assert _row(lib, "cs2")["game"] is False
    assert lib.index.reloads == 1


def test_records_on_makes_an_unknown_app_a_game_under_its_exe(lib):
    r = lib.post("/api/library/game", {"key": "charmap", "game": True})
    assert r.status == 200 and r.json()["ok"] is True
    data = cfg.load_games()
    # Keyed on the executable, which is what the watcher sees running.
    assert data["games"]["charmap.exe"]["name"] == "Character Map"
    assert _row(lib, "charmap")["game"] is True
    assert lib.index.reloads == 1


def test_records_on_takes_the_exe_off_the_blocklist(lib):
    assert _row(lib, "steam")["game"] is False
    r = lib.post("/api/library/game", {"key": "steam", "game": True})
    assert r.status == 200 and r.json()["ok"] is True
    assert "steam.exe" not in cfg.load_games()["blocklist"]
    assert _row(lib, "steam")["game"] is True


def test_records_off_then_on_round_trips(lib):
    lib.post("/api/library/game", {"key": "cs2", "game": False})
    lib.post("/api/library/game", {"key": "cs2", "game": True})
    data = cfg.load_games()
    assert "cs2.exe" not in data["blocklist"]
    assert data["games"]["cs2.exe"] == {"name": "Counter-Strike 2",
                                        "thumbnail": "C:/art/cs2.png"}
    assert _row(lib, "cs2")["game"] is True


def test_a_game_the_public_index_knows_is_not_given_an_override(lib):
    """An override changes how the watcher names the game, so one is only
    written when nothing else would recognise it."""
    data = cfg.load_games()
    del data["games"]["cs2.exe"]
    data["blocklist"].append("cs2.exe")
    cfg.save_games(data)
    lib.post("/api/library/game", {"key": "cs2", "game": True})
    assert "cs2.exe" not in cfg.load_games()["games"]
    assert _row(lib, "cs2")["game"] is True


def test_a_wildcard_block_is_named_rather_than_silently_kept(lib):
    lib.apps.append(catalog.App(key="bank", name="My Banking", path="C:/b.exe",
                                exe="mybanking.exe", source="shortcut"))
    r = lib.post("/api/library/game", {"key": "bank", "game": True})
    assert r.status == 409
    assert "*banking*" in r.json()["error"]
    assert _row(lib, "bank")["game"] is False


def test_a_wildcard_block_also_reads_as_not_a_game(lib):
    lib.apps.append(catalog.App(key="bank", name="My Banking", path="C:/b.exe",
                                exe="mybanking.exe", source="shortcut"))
    data = cfg.load_games()
    data["games"]["mybanking.exe"] = {"name": "My Banking"}
    cfg.save_games(data)
    assert _row(lib, "bank")["game"] is False


def test_records_refuses_an_app_that_is_not_in_the_library(lib):
    r = lib.post("/api/library/game", {"key": "nope", "game": True})
    assert r.status == 409 and "error" in r.json()
    r = lib.post("/api/library/game", {"key": "", "game": True})
    assert r.status == 400


# ---------------------------------------------------------------- Goes live

def test_goes_live_saves_the_stream_flag_on_that_app_alone(lib):
    r = lib.post("/api/library/stream", {"key": "cs2", "stream": False})
    assert r.status == 200 and r.json()["ok"] is True
    after = {a.key: a.stream for a in lib.saved["apps"]}
    assert after == {"cs2": False, "charmap": False, "steam": False}
    # Every other field of every app is written back as it was.
    assert [a.path for a in lib.saved["apps"]] == [a.path for a in APPS]


def test_goes_live_refuses_an_unknown_app(lib):
    r = lib.post("/api/library/stream", {"key": "nope", "stream": True})
    assert r.status == 409 and "error" in r.json()
    assert "apps" not in lib.saved
    assert lib.post("/api/library/stream", {"key": ""}).status == 400


# -------------------------------------------------------------------- cover

def test_the_cover_is_the_games_own_thumbnail(lib, tmp_path):
    from PIL import Image

    art = tmp_path / "cs2.png"
    Image.new("RGB", (8, 4), (10, 20, 30)).save(art)
    cfg.save_game_field("cs2.exe", "thumbnail", str(art))
    r = lib.get("/api/library/cover?key=cs2.exe")
    assert r.status == 200
    assert r.headers.get("Content-Type") == "image/png"
    assert r.body == art.read_bytes()


def test_the_cover_serves_only_what_games_yaml_names(lib, tmp_path):
    """A path in the query is ignored: the route reads the game's own entry,
    so it cannot be turned into a way to read any file on the disk."""
    r = lib.get("/api/library/cover?key=charmap.exe&path=C:/Windows/win.ini")
    assert r.status == 400
    # A thumbnail that is not an image is not served either.
    notes = tmp_path / "notes.png"
    notes.write_text("not an image", encoding="utf-8")
    cfg.save_game_field("cs2.exe", "thumbnail", str(notes))
    assert lib.get("/api/library/cover?key=cs2.exe").status == 400


# ------------------------------------------------------------- two at once

def test_two_switches_at_once_both_land(lib, monkeypatch):
    """The review's case: switching Records off down a list of system tools
    sends requests that overlap, and each read-modify-write of games.yaml
    used to overwrite the one before it. A slow save opens the window wide
    enough to hit every time."""
    import threading
    import time as _time

    real = cfg.save_games

    def slow(data):
        _time.sleep(0.15)
        real(data)

    monkeypatch.setattr(cfg, "save_games", slow)
    out = []
    ts = [threading.Thread(target=lambda k=k: out.append(
              lib.srv.library_set_game({"key": k, "game": False})))
          for k in ("cs2", "charmap")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert [s for _, s in out] == [200, 200]
    block = {str(b).lower() for b in cfg.load_games()["blocklist"]}
    assert {"cs2.exe", "charmap.exe"} <= block, block


def test_games_yaml_is_written_atomically(lib, monkeypatch):
    from autostream import atomic
    seen = []
    monkeypatch.setattr(atomic, "write_text", lambda p, t, **kw: seen.append(str(p)))
    cfg.save_games({"games": {}, "blocklist": [], "never_stream_if_running": []})
    assert seen and seen[0].endswith("games.yaml")


def test_a_string_false_is_not_true():
    from autostream import webui
    assert webui._as_bool("false") is False and webui._as_bool("0") is False
    assert webui._as_bool(True) is True and webui._as_bool("true") is True
