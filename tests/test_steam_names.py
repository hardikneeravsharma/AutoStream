"""Steam game names, now that Valve's app list is gone.

Every documented form of ISteamApps/GetAppList answers 404 -- v0002, v2 and v1,
with or without a User-Agent -- while the rest of api.steampowered.com answers
normally. So the endpoint was retired, not blocked.

Three requests failed on every start, logged three warnings, and left the appid
table empty. Nothing looked broken: the name lookup that depends on it simply
never fired, and a Steam game the public index did not recognise stayed named
after its executable.

The names were on disk the whole time.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import gameindex                                  # noqa: E402


MANIFEST = '''"AppState"
{
\t"appid"\t\t"%s"
\t"universe"\t\t"1"
\t"name"\t\t"%s"
\t"StateFlags"\t\t"4"
\t"installdir"\t\t"%s"
}
'''


def library(tmp_path: Path, games: dict) -> Path:
    apps = tmp_path / "steamapps"
    apps.mkdir(parents=True, exist_ok=True)
    for appid, name in games.items():
        (apps / f"appmanifest_{appid}.acf").write_text(
            MANIFEST % (appid, name, name.replace(" ", "")), encoding="utf-8")
    return tmp_path


def test_names_come_off_the_manifests(tmp_path, monkeypatch):
    library(tmp_path, {"730": "Counter-Strike 2", "2507950": "Delta Force"})
    monkeypatch.setattr(gameindex, "_steam_roots", lambda: [str(tmp_path)],
                        raising=False)
    import autostream.catalog as catalog
    monkeypatch.setattr(catalog, "_steam_roots", lambda: [str(tmp_path)])

    got = gameindex.steam_apps_from_disk()
    assert got["730"] == "Counter-Strike 2"
    assert got["2507950"] == "Delta Force"


def test_a_second_library_on_another_drive_is_read(tmp_path, monkeypatch):
    """Games are routinely installed on a second disk, and that library is
    only discoverable through libraryfolders.vdf."""
    main = library(tmp_path / "main", {"730": "Counter-Strike 2"})
    other = library(tmp_path / "d_drive", {"570": "Dota 2"})
    (main / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
        % str(other).replace("\\", "\\\\"), encoding="utf-8")

    import autostream.catalog as catalog
    monkeypatch.setattr(catalog, "_steam_roots", lambda: [str(main)])

    got = gameindex.steam_apps_from_disk()
    assert got.get("730") == "Counter-Strike 2"
    assert got.get("570") == "Dota 2", "the second library was not read"


def test_no_steam_at_all_is_not_an_error(tmp_path, monkeypatch):
    import autostream.catalog as catalog
    monkeypatch.setattr(catalog, "_steam_roots", lambda: [str(tmp_path / "nope")])
    assert gameindex.steam_apps_from_disk() == {}


def test_a_damaged_manifest_does_not_lose_the_others(tmp_path, monkeypatch):
    root = library(tmp_path, {"730": "Counter-Strike 2"})
    (root / "steamapps" / "appmanifest_999.acf").write_text(
        "this is not a manifest", encoding="utf-8")
    import autostream.catalog as catalog
    monkeypatch.setattr(catalog, "_steam_roots", lambda: [str(root)])

    got = gameindex.steam_apps_from_disk()
    assert got == {"730": "Counter-Strike 2"}


def test_a_nameless_manifest_is_skipped(tmp_path, monkeypatch):
    """Naming a game "" is worse than leaving it named after its exe."""
    root = library(tmp_path, {"730": "Counter-Strike 2"})
    (root / "steamapps" / "appmanifest_111.acf").write_text(
        MANIFEST % ("111", "", "x"), encoding="utf-8")
    import autostream.catalog as catalog
    monkeypatch.setattr(catalog, "_steam_roots", lambda: [str(root)])

    assert "111" not in gameindex.steam_apps_from_disk()


def test_the_dead_endpoints_are_gone():
    """Keeping them meant three failed requests and three warnings on every
    single start, for a table nothing could fill."""
    assert not hasattr(gameindex, "STEAM_APPLIST_SOURCES")
