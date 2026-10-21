"""What the Mac build does not do, and that the page is told so.

Nothing on a Mac may need a game installed: it clips footage recorded on a PC.
"""
from __future__ import annotations

import sys

import fakes
import pytest

from autostream import schema
from autostream.clips import cs2_demo
from autostream.macos import features


def test_bootstrap_names_what_is_missing_and_where_to_start():
    b = features.bootstrap()
    assert b["platform"] == "macos"
    assert {"streaming", "engine", "obs", "tray", "game_fetch"} <= set(b["unavailable"])
    assert b["hide_pages"] == ["dash", "library"]
    assert b["home"] == "clips"
    # Clips and Studio are the whole point: never hidden.
    assert "clips" not in b["hide_pages"] and "studio" not in b["hide_pages"]


def test_every_absence_has_a_reason():
    assert all(why.strip() for why in features.UNAVAILABLE.values())


def test_settings_lose_the_streaming_sections():
    got = {s["id"] for s in features.settings_schema(schema.CONFIG_SCHEMA)}
    assert not (got & features.HIDE_SECTIONS)
    assert {"appearance", "clips", "logging"} <= got


def test_settings_lose_the_stray_streaming_fields():
    paths = {f["path"] for s in features.settings_schema(schema.CONFIG_SCHEMA)
             for f in s["fields"]}
    assert not (paths & features.HIDE_FIELDS)
    assert "clips.output_dir" in paths and "ui.theme" in paths


def test_the_shared_schema_is_never_mutated():
    before = [dict(s, fields=[dict(f) for f in s["fields"]]) for s in schema.CONFIG_SCHEMA]
    features.settings_schema(schema.CONFIG_SCHEMA)
    assert before == [dict(s, fields=[dict(f) for f in s["fields"]])
                      for s in schema.CONFIG_SCHEMA]


def test_the_mac_encoder_menu_only_offers_values_windows_accepts():
    """A save is validated against the SHARED schema; a Mac-only value would
    be refused there."""
    shared = next(f for s in schema.CONFIG_SCHEMA for f in s["fields"]
                  if f["path"] == "clips.encoder")
    allowed = {o["value"] for o in shared["options"]}
    mac = next(f for s in features.settings_schema(schema.CONFIG_SCHEMA)
               for f in s["fields"] if f["path"] == "clips.encoder")
    assert {o["value"] for o in mac["options"]} <= allowed
    assert "VideoToolbox" in mac["help"]


def test_a_demo_is_never_fetched_through_the_game_on_a_mac(monkeypatch):
    """No game on a Mac to ask -- and `open steam://` would launch Steam."""
    opened = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(cs2_demo.subprocess, "Popen", lambda *a, **k: opened.append(a))
    assert cs2_demo.request_download("CSGO-Jojzi-QtbwS-xCf7V-jNcQK-G8MkO") is False
    assert not opened


# ------------------------------------------------------------ over HTTP

@pytest.fixture
def server():
    srv = fakes.LiveServer()
    yield srv
    srv.close()


def _boot(server):
    return server.get("/api/bootstrap").json()


def test_bootstrap_carries_the_mac_keys_on_a_mac(server, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    b = _boot(server)
    assert b["home"] == "clips" and "streaming" in b["unavailable"]


def test_bootstrap_is_unchanged_on_windows(server, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    b = _boot(server)
    assert not ({"platform", "unavailable", "hide_pages", "home"} & set(b))


def test_status_says_a_mac_is_not_streaming(server, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    st = server.get("/api/status").json()
    assert st["streaming"] is False and "tools" in st


def test_status_without_an_engine_is_unchanged_on_windows(server, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    st = server.get("/api/status").json()
    assert "streaming" not in st and "tools" not in st


def test_the_settings_route_filters_only_on_a_mac(server, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    mac = {s["id"] for s in server.get("/api/settings/schema").json()}
    monkeypatch.setattr(sys, "platform", "win32")
    win = {s["id"] for s in server.get("/api/settings/schema").json()}
    assert "obs" in win and "obs" not in mac
    assert win == {s["id"] for s in schema.CONFIG_SCHEMA}


def test_match_codes_are_refused_with_what_to_do_instead(server, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    body = server.post("/api/clips/demos",
                       {"text": "CSGO-Jojzi-QtbwS-xCf7V-jNcQK-G8MkO"}).json()
    assert ".dem" in body["error"] and "PC" in body["error"]


def test_the_wizard_offers_no_webview2_on_a_mac(server, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    got = server.post("/api/setup/webview2", {}).json()
    assert got["installed"] is True and "Microsoft" not in got["hint"]


def test_valorant_records_are_not_fetched_from_a_client_that_is_not_there(server, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    body = server.post("/api/clips/valorant/fetch", {}).json()
    assert "Riot Client" in body["error"] and "Movies/AutoStream/matches" in body["error"]
