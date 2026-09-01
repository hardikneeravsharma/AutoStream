"""The user's own files live where an update cannot reach them.

ROOT is where the program is; DATA_HOME is where the user's files are. They
used to be the same directory, which is the root cause of every upgrade problem
this app had: unzip over the old build and orphaned files stay behind, unzip
somewhere else and the config and the YouTube token are stranded in the old
folder, and a rebuild deletes the whole thing.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autostream import paths                           # noqa: E402

REPO = str(Path(__file__).resolve().parents[1])


@pytest.fixture(autouse=True)
def _restore_paths():
    """Put the module back the way the rest of the suite expects it.

    These tests reload autostream.paths to see what it decides under different
    environments, and a reload mutates the module GLOBALLY -- monkeypatch
    restores the environment but cannot undo the reload. Without this, every
    test that ran afterwards saw a paths module still pointing at a tmp_path.
    """
    yield
    os.environ["AUTOSTREAM_HOME"] = REPO
    if hasattr(sys, "frozen"):
        del sys.frozen
    importlib.reload(paths)


def _reload(monkeypatch, *, frozen: bool, home: str | None,
            localappdata: str | None):
    monkeypatch.delenv("AUTOSTREAM_HOME", raising=False)
    if home:
        monkeypatch.setenv("AUTOSTREAM_HOME", home)
    if localappdata:
        monkeypatch.setenv("LOCALAPPDATA", localappdata)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    if not frozen and hasattr(sys, "frozen"):
        monkeypatch.delattr(sys, "frozen", raising=False)
    return importlib.reload(paths)


# ------------------------------------------------------------ which root

def test_a_checkout_keeps_everything_together(monkeypatch, tmp_path):
    """Running from source must behave exactly as it always has."""
    p = _reload(monkeypatch, frozen=False, home=None, localappdata=str(tmp_path))
    assert p.DATA_HOME == p.ROOT
    assert p.CONFIG_DIR == p.ROOT / "config"


def test_a_frozen_build_puts_user_files_in_localappdata(monkeypatch, tmp_path):
    p = _reload(monkeypatch, frozen=True, home=None, localappdata=str(tmp_path))
    assert p.DATA_HOME == tmp_path / "AutoStream"
    assert p.CONFIG_DIR == tmp_path / "AutoStream" / "config"
    assert p.STATE_FILE == tmp_path / "AutoStream" / "state.json"
    # ...and the program's own folder is still where the defaults ship from.
    assert p.SEED_CONFIG_DIR == p.ROOT / "config"


def test_an_explicit_home_wins_even_when_frozen(monkeypatch, tmp_path):
    """Portable installs, a second profile, and the test suite all rely on it."""
    p = _reload(monkeypatch, frozen=True, home=str(tmp_path / "portable"),
                localappdata=str(tmp_path / "lad"))
    assert p.DATA_HOME == p.ROOT == tmp_path / "portable"


# ------------------------------------------------------------ migration

def _old_install(root: Path):
    (root / "config").mkdir(parents=True)
    (root / "secrets").mkdir(parents=True)
    (root / "logs").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("channel: mine\n", encoding="utf-8")
    (root / "config" / "clip_templates").mkdir()
    (root / "config" / "clip_templates" / "cs2.png").write_bytes(b"png")
    (root / "secrets" / "token.json").write_text('{"refresh_token": "keep me"}',
                                                 encoding="utf-8")
    (root / "logs" / "autostream.log").write_text("old line\n", encoding="utf-8")
    (root / "state.json").write_text('{"session_number": 7}', encoding="utf-8")


def test_an_older_install_brings_its_own_files_across(monkeypatch, tmp_path):
    old, data = tmp_path / "app", tmp_path / "data"
    _old_install(old)
    monkeypatch.setattr(paths, "ROOT", old)
    monkeypatch.setattr(paths, "DATA_HOME", data)
    monkeypatch.setattr(paths, "CONFIG_DIR", data / "config")
    monkeypatch.setattr(paths, "SECRETS_DIR", data / "secrets")
    monkeypatch.setattr(paths, "LOGS_DIR", data / "logs")

    moved = paths.migrate_data_home()

    assert (data / "secrets" / "token.json").exists(), "the YouTube token"
    assert (data / "config" / "config.yaml").read_text(encoding="utf-8") == "channel: mine\n"
    assert (data / "config" / "clip_templates" / "cs2.png").exists(), "calibration"
    assert (data / "logs" / "autostream.log").exists()
    assert (data / "state.json").exists()
    assert len(moved) == 5


def test_the_old_installation_is_left_working(monkeypatch, tmp_path):
    """Copied, not moved: an upgrade that goes wrong should leave the previous
    install able to start."""
    old, data = tmp_path / "app", tmp_path / "data"
    _old_install(old)
    monkeypatch.setattr(paths, "ROOT", old)
    monkeypatch.setattr(paths, "DATA_HOME", data)
    monkeypatch.setattr(paths, "CONFIG_DIR", data / "config")
    monkeypatch.setattr(paths, "SECRETS_DIR", data / "secrets")
    monkeypatch.setattr(paths, "LOGS_DIR", data / "logs")
    paths.migrate_data_home()
    assert (old / "secrets" / "token.json").exists()
    assert (old / "config" / "config.yaml").exists()


def test_what_is_already_there_is_never_overwritten(monkeypatch, tmp_path):
    """Anything in DATA_HOME is newer by definition than a folder we are
    migrating away from."""
    old, data = tmp_path / "app", tmp_path / "data"
    _old_install(old)
    (data / "config").mkdir(parents=True)
    (data / "config" / "config.yaml").write_text("channel: current\n", encoding="utf-8")
    monkeypatch.setattr(paths, "ROOT", old)
    monkeypatch.setattr(paths, "DATA_HOME", data)
    monkeypatch.setattr(paths, "CONFIG_DIR", data / "config")
    monkeypatch.setattr(paths, "SECRETS_DIR", data / "secrets")
    monkeypatch.setattr(paths, "LOGS_DIR", data / "logs")
    paths.migrate_data_home()
    assert (data / "config" / "config.yaml").read_text(encoding="utf-8") == "channel: current\n"


def test_migrating_twice_moves_nothing_the_second_time(monkeypatch, tmp_path):
    old, data = tmp_path / "app", tmp_path / "data"
    _old_install(old)
    monkeypatch.setattr(paths, "ROOT", old)
    monkeypatch.setattr(paths, "DATA_HOME", data)
    monkeypatch.setattr(paths, "CONFIG_DIR", data / "config")
    monkeypatch.setattr(paths, "SECRETS_DIR", data / "secrets")
    monkeypatch.setattr(paths, "LOGS_DIR", data / "logs")
    assert paths.migrate_data_home()
    assert paths.migrate_data_home() == []


def test_a_checkout_migrates_nothing(monkeypatch, tmp_path):
    """DATA_HOME is ROOT there, so there is nowhere to move to and nothing to
    move -- and copying a folder onto itself would be a fine way to lose it."""
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(paths, "DATA_HOME", tmp_path)
    assert paths.migrate_data_home() == []


# ------------------------------------------------------------ seeding

def test_a_fresh_install_is_seeded_from_what_ships(monkeypatch, tmp_path):
    seed, data = tmp_path / "app" / "config", tmp_path / "data" / "config"
    seed.mkdir(parents=True)
    (seed / "games.yaml").write_text("games: []\n", encoding="utf-8")
    (seed / "clip_templates").mkdir()
    (seed / "clip_templates" / "df.png").write_bytes(b"x")
    monkeypatch.setattr(paths, "SEED_CONFIG_DIR", seed)
    monkeypatch.setattr(paths, "CONFIG_DIR", data)
    made = paths.seed_config()
    assert (data / "games.yaml").exists()
    assert (data / "clip_templates" / "df.png").exists()
    assert len(made) == 2


def test_seeding_never_overwrites_the_users_own(monkeypatch, tmp_path):
    seed, data = tmp_path / "app" / "config", tmp_path / "data" / "config"
    seed.mkdir(parents=True)
    data.mkdir(parents=True)
    (seed / "games.yaml").write_text("shipped\n", encoding="utf-8")
    (data / "games.yaml").write_text("mine\n", encoding="utf-8")
    monkeypatch.setattr(paths, "SEED_CONFIG_DIR", seed)
    monkeypatch.setattr(paths, "CONFIG_DIR", data)
    assert paths.seed_config() == []
    assert (data / "games.yaml").read_text(encoding="utf-8") == "mine\n"


# --------------------------------------------- the startup path itself

def test_setup_logging_runs(tmp_path, monkeypatch):
    """IT DID NOT, AND NOTHING NOTICED. The migration was hooked into
    setup_logging, and the lines announcing it used a module-level `log` that
    this module does not have. Every command routes through setup_logging, so
    the frozen app died on launch with

        NameError: name 'log' is not defined

    while the whole test suite passed -- because nothing called it. A function
    every entry point depends on has to be exercised by something.
    """
    from autostream import __main__ as entry

    monkeypatch.setattr(paths, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(paths, "LOG_FILE", tmp_path / "logs" / "autostream.log")
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(paths, "SECRETS_DIR", tmp_path / "secrets")
    monkeypatch.setattr(paths, "DATA_HOME", tmp_path)
    monkeypatch.setattr(paths, "ROOT", tmp_path)

    entry.setup_logging("INFO", console=False)
    assert (tmp_path / "logs" / "autostream.log").exists()


def test_setup_logging_announces_a_migration(tmp_path, monkeypatch):
    """The line only appears on the run that actually moves something, and it
    exists because "where did my settings go" is the first question an upgrade
    of this kind provokes."""
    import logging

    from autostream import __main__ as entry

    monkeypatch.setattr(paths, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(paths, "LOG_FILE", tmp_path / "logs" / "autostream.log")
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(paths, "SECRETS_DIR", tmp_path / "secrets")
    monkeypatch.setattr(paths, "DATA_HOME", tmp_path)
    monkeypatch.setattr(paths, "migrate_data_home", lambda: ["secrets/token.json"])
    monkeypatch.setattr(paths, "seed_config", lambda: [])

    # Asserted against the LOG FILE, not caplog: setup_logging clears the root
    # handlers, which removes caplog's own -- and the file is what the user
    # actually reads anyway.
    entry.setup_logging("INFO", console=False)
    logging.shutdown()
    written = (tmp_path / "logs" / "autostream.log").read_text(encoding="utf-8")
    assert "your settings now live in" in written
