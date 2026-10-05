"""Switching OBS's WebSocket server on for somebody.

THE STEP PEOPLE STOP AT. The OBS page of setup is six instructions about a
dialog in another application -- Tools, WebSocket Server Settings, tick the
box, Apply, Show Connect Info, copy the password -- and the last of them fails
silently, because one wrong character in a generated password looks exactly
like OBS not running.

Every one of those clicks writes a single JSON file. This writes it instead.

IT IS SOMEBODY ELSE'S APPLICATION'S SETTINGS, so most of what is asserted here
is about not breaking them: not while OBS is open, not losing the keys we do
not understand, not turning authentication off, and a copy of the original
before the first change.
"""
from __future__ import annotations

import json

import pytest

from autostream import obs as obs_mod


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    """A fake OBS profile, with the process reported as closed."""
    path = tmp_path / "plugin_config" / "obs-websocket" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(obs_mod, "_ws_config_paths", lambda exe="": [path])
    monkeypatch.setattr(obs_mod, "_obs_process_alive", lambda: False)
    return path


def _write(path, **fields):
    path.write_text(json.dumps(fields), encoding="utf-8")


# ------------------------------------------------- not while OBS is open

def test_it_refuses_while_obs_is_running(cfg_file, monkeypatch):
    """THE REASON THE FUNCTION IS SHAPED THIS WAY. OBS reads this file at
    startup and WRITES IT BACK from memory when it quits, so a change made
    underneath a running OBS is thrown away -- silently, minutes later, long
    after setup has said it worked."""
    monkeypatch.setattr(obs_mod, "_obs_process_alive", lambda: True)
    _write(cfg_file, server_enabled=False)

    got = obs_mod.enable_websocket()

    assert got["ok"] is False
    assert "close obs" in got["why"].lower()
    # And it really did not touch the file.
    assert json.loads(cfg_file.read_text(encoding="utf-8")) == {
        "server_enabled": False}


# ----------------------------------------------------- what it writes

def test_it_switches_the_server_on(cfg_file):
    _write(cfg_file, server_enabled=False, server_port=4455)
    got = obs_mod.enable_websocket()
    assert got["ok"] is True
    saved = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert saved["server_enabled"] is True


def test_authentication_stays_on(cfg_file):
    """A WebSocket server with auth off accepts anything that reaches the
    port, and this one can start and stop recordings. Setting it up for
    somebody is not a licence to leave their machine less safe than it was."""
    _write(cfg_file, server_enabled=False, auth_required=False,
           server_password="")
    got = obs_mod.enable_websocket()
    saved = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert saved["auth_required"] is True
    assert saved["server_password"], "auth on with no password locks us out"
    assert got["password"] == saved["server_password"]


def test_a_password_that_is_already_there_is_kept(cfg_file):
    """Changing it would break every other thing connected to this OBS --
    a Stream Deck, a chat bot, somebody's own script."""
    _write(cfg_file, server_enabled=False, server_password="theirs-already")
    got = obs_mod.enable_websocket()
    assert got["password"] == "theirs-already"
    assert json.loads(cfg_file.read_text(encoding="utf-8"))[
        "server_password"] == "theirs-already"


def test_a_generated_password_is_not_guessable(cfg_file):
    _write(cfg_file, server_enabled=False)
    seen = set()
    for _ in range(5):
        cfg_file.write_text("{}", encoding="utf-8")
        seen.add(obs_mod.enable_websocket()["password"])
    assert len(seen) == 5
    assert all(len(p) >= 12 for p in seen)


def test_the_port_that_is_already_set_is_kept(cfg_file):
    _write(cfg_file, server_enabled=False, server_port=4499)
    assert obs_mod.enable_websocket()["port"] == 4499


def test_a_profile_with_no_port_gets_the_obs_default(cfg_file):
    _write(cfg_file, server_enabled=False)
    assert obs_mod.enable_websocket()["port"] == 4455


def test_keys_it_does_not_understand_are_left_alone(cfg_file):
    """Read-modify-write, not write. This file belongs to a plugin that gains
    settings between versions, and dropping one is a change to their OBS that
    nothing here would ever report."""
    _write(cfg_file, server_enabled=False, some_future_setting="keep me",
           alerts_enabled=True, nested={"a": 1})
    obs_mod.enable_websocket()
    saved = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert saved["some_future_setting"] == "keep me"
    assert saved["nested"] == {"a": 1}
    assert saved["alerts_enabled"] is True, "an existing value was overwritten"


def test_a_profile_that_does_not_exist_yet_is_created(cfg_file):
    """OBS writes this file the first time the dialog is committed, so on a
    fresh install there is nothing to read -- which is exactly the machine
    this feature is for."""
    assert not cfg_file.exists()
    got = obs_mod.enable_websocket()
    assert got["ok"] is True
    assert cfg_file.is_file()
    assert json.loads(cfg_file.read_text(encoding="utf-8"))["server_enabled"] is True


# --------------------------------------------------------- the backup

def test_the_original_is_kept(cfg_file):
    """The cost of being wrong here is somebody else's OBS not starting."""
    _write(cfg_file, server_enabled=False, theirs="original")
    obs_mod.enable_websocket()
    backup = cfg_file.with_suffix(".json.autostream-bak")
    assert backup.is_file()
    assert json.loads(backup.read_text(encoding="utf-8")) == {
        "server_enabled": False, "theirs": "original"}


def test_the_backup_is_of_what_they_had_not_of_our_last_write(cfg_file):
    """Taken once. Refreshed every time, it would become a copy of our own
    previous write -- which is no use at all as the thing to go back to."""
    _write(cfg_file, server_enabled=False, theirs="original")
    obs_mod.enable_websocket()
    obs_mod.enable_websocket()
    obs_mod.enable_websocket()
    backup = cfg_file.with_suffix(".json.autostream-bak")
    assert json.loads(backup.read_text(encoding="utf-8")) == {
        "server_enabled": False, "theirs": "original"}


def test_nothing_is_backed_up_when_there_was_nothing_there(cfg_file):
    obs_mod.enable_websocket()
    assert not cfg_file.with_suffix(".json.autostream-bak").exists()


# ------------------------------------------------------ when it cannot

def test_unreadable_json_is_reported_rather_than_overwritten(cfg_file):
    """A file this cannot parse may still be one OBS can. Replacing it would
    turn "AutoStream could not read your settings" into "your OBS settings are
    gone", which is a much worse outcome for the same cause."""
    cfg_file.write_text("{ not json at all", encoding="utf-8")
    got = obs_mod.enable_websocket()
    assert got["ok"] is False
    assert "could not read" in got["why"].lower()
    assert cfg_file.read_text(encoding="utf-8") == "{ not json at all"


def test_nowhere_to_write_is_an_answer_not_an_exception(monkeypatch):
    monkeypatch.setattr(obs_mod, "_ws_config_paths", lambda exe="": [])
    monkeypatch.setattr(obs_mod, "_obs_process_alive", lambda: False)
    got = obs_mod.enable_websocket()
    assert got["ok"] is False
    assert got["why"]


# ------------------------------------- and the wizard reads it back

def test_what_was_written_is_what_discover_reads(cfg_file):
    """The two halves have to agree: the whole point is that the next step of
    the wizard finds what this put there."""
    _write(cfg_file, server_enabled=False)
    wrote = obs_mod.enable_websocket()
    found = obs_mod.discover_websocket()
    assert found["found"] is True
    assert found["enabled"] is True
    assert found["port"] == wrote["port"]
    assert found["password"] == wrote["password"]
    assert found["auth_required"] is True
