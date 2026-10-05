r"""Settings that were on the page, and did nothing.

FIVE OF THEM, found by looking for what a feature depended on rather than by
any failing test -- nothing was failing, because there was nothing to fail.
Each appeared in `schema.py` with help text promising a behaviour, and in
`cfg.py` with a default, and NOWHERE ELSE in the product:

    record.auto_scan      "scan its recording for kill markers in the
                           background so the Clips page already has them
                           ready"  -- the engine set a flag nothing read
    logging.keep_days     "older files past this many days are deleted"
                          -- backupCount was hard-coded to 7
    ui.open_window        "off means AutoStream starts quietly in the
                           notification area" -- the window always opened
    title.fallback_game   "stands in for {game} when AutoStream can tell
                           something is running but has no name for it"
    record.warn_free_gb   "show a warning on the dashboard once free space
                           drops under this"

A setting that is on by default and does nothing is worse than one that is
missing. It is a promise in the product's own voice, and the person who reads
it, believes it, and plans around it has been misled by the page rather than
by a bug.

This file is the guard. A key that exists only in the schema and the defaults
is a feature that has not been built.
"""
from __future__ import annotations

import logging
import pathlib
import re
import types

import pytest
import yaml

from autostream import cfg


# ------------------------------------------------- the guard against more

#: Keys that legitimately have no reader in `autostream/`.
EXPLAINED: dict[str, str] = {
    # Read by scripts/build.ps1 and the installer, not by the app.
    # (none today -- kept so the next one has somewhere to go, with a reason)
}


def _flat(d, prefix=""):
    for k, v in d.items():
        p = f"{prefix}{k}"
        if isinstance(v, dict):
            yield from _flat(v, p + ".")
        else:
            yield p


def test_every_setting_the_page_offers_is_read_by_something():
    """THE WHOLE POINT OF THIS FILE. Five settings shipped promising
    behaviour that no code performed, and nothing could have caught it: the
    schema test checks a key has a default, the defaults test checks a
    default has a key, and both passed for every one of them."""
    root = pathlib.Path(__file__).resolve().parents[1] / "autostream"
    src = ""
    for f in sorted(root.rglob("*.py")):
        if f.name in ("cfg.py", "schema.py"):
            continue
        src += f.read_text(encoding="utf-8", errors="replace")

    dead = []
    for path in _flat(cfg.DEFAULTS):
        if path in EXPLAINED:
            continue
        _, _, key = path.partition(".")
        # Read as `.key`, as a string literal, or by its flat path.
        if re.search(rf"\.{re.escape(key)}\b", src):
            continue
        if f'"{key}"' in src or f"'{key}'" in src or path in src:
            continue
        dead.append(path)

    assert not dead, (
        "these settings are on the Settings page, have a default, and are "
        "read by nothing: " + ", ".join(sorted(dead)) +
        ". Either wire them up or add them to EXPLAINED with the reason.")


# ------------------------------------------- and each of the five, directly

@pytest.mark.parametrize("asked,kept", [(30, 30), (1, 1), (0, 7), (9999, 365)])
def test_the_log_is_kept_for_as_long_as_the_setting_says(tmp_path, monkeypatch,
                                                          asked, kept):
    """`backupCount=7`, hard-coded. Somebody who set thirty days to catch a
    fault that happens once a fortnight got seven, and the log that would have
    shown it had been deleted a week before they went looking.

    NO MODULE RELOADS. Reloading paths and cfg to point them at a temp home
    leaves the reloaded modules behind for every later test in the run -- it
    broke an unrelated journal test the first time this was written, and the
    same mistake cost an hour earlier in this project. The four things
    `setup_logging` touches are patched on the modules that are already
    imported.
    """
    import autostream.__main__ as main
    from autostream import paths

    before = logging.getLogger().handlers[:]
    monkeypatch.setattr(paths, "LOG_FILE", tmp_path / "autostream.log")
    monkeypatch.setattr(paths, "migrate_data_home", lambda: None)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: None)
    monkeypatch.setattr(paths, "seed_config", lambda: None)
    monkeypatch.setattr(
        cfg, "load",
        lambda: cfg.Config({**cfg.DEFAULTS,
                            "logging": {**cfg.DEFAULTS["logging"],
                                        "keep_days": asked}}))
    try:
        main.setup_logging("INFO", console=False)
        got = [h.backupCount for h in logging.getLogger().handlers
               if hasattr(h, "backupCount")]
        assert got == [kept], got
    finally:
        for h in logging.getLogger().handlers[:]:
            try:
                h.close()
            except Exception:                            # noqa: BLE001
                pass
        logging.getLogger().handlers[:] = before


def test_a_game_with_no_name_gets_the_fallback():
    """A game the index cannot name went out as a title with an empty
    {game} in it."""
    import fakes

    eng = fakes.engine()
    eng.cfg["title"] = dict(eng.cfg["title"])
    eng.cfg["title"]["fallback_game"] = "something good"
    eng.state.session_start = 1_790_000_000.0
    eng.state.session_games = []

    hit = types.SimpleNamespace(name="", blurb="", username="")
    assert eng._vars(hit)["game"] == "something good"


def test_a_game_with_a_name_keeps_it():
    import fakes

    eng = fakes.engine()
    eng.cfg["title"] = dict(eng.cfg["title"])
    eng.cfg["title"]["fallback_game"] = "something good"
    eng.state.session_start = 1_790_000_000.0
    eng.state.session_games = []

    hit = types.SimpleNamespace(name="VALORANT", blurb="", username="")
    assert eng._vars(hit)["game"] == "VALORANT"


def test_an_empty_fallback_still_produces_a_title():
    """The default is empty on some installs, and {game} resolving to nothing
    is how a stream goes out called " - Friday night"."""
    import fakes

    eng = fakes.engine()
    eng.cfg["title"] = dict(eng.cfg["title"])
    eng.cfg["title"]["fallback_game"] = ""
    eng.state.session_start = 1_790_000_000.0
    eng.state.session_games = []

    hit = types.SimpleNamespace(name="  ", blurb="", username="")
    assert eng._vars(hit)["game"].strip(), "the title would have a hole in it"


# ------------------------------------------------------- the disk warning

def _disk_engine(free_gb, warn_at, floor=10):
    import fakes

    eng = fakes.engine()
    eng.cfg["record"] = dict(eng.cfg["record"])
    eng.cfg["record"]["warn_free_gb"] = warn_at
    eng.cfg["record"]["min_free_gb"] = floor
    eng.state.recording = True
    eng._disk_checked = 0.0
    eng._disk_warned = False
    eng.disk_free_gb = None
    eng._free_gb = lambda: free_gb
    eng.toggle_recording = lambda why="": None
    return eng


def test_the_warning_level_is_reported(monkeypatch):
    """The only disk signal in the product was the floor at which the
    recording is ALREADY being stopped -- by which point a session is half
    saved, which is the thing a heads-up exists to avoid."""
    from autostream import engine as eng_mod

    said = []
    monkeypatch.setattr(eng_mod.notify, "toast",
                        lambda *a, **k: said.append(a))
    eng = _disk_engine(free_gb=60, warn_at=100, floor=10)
    eng._check_disk()

    assert eng.disk_free_gb == 60
    assert said, "nothing was said at 60 GB with a 100 GB warning level"


def test_plenty_of_space_says_nothing(monkeypatch):
    from autostream import engine as eng_mod

    said = []
    monkeypatch.setattr(eng_mod.notify, "toast",
                        lambda *a, **k: said.append(a))
    eng = _disk_engine(free_gb=400, warn_at=100)
    eng._check_disk()
    assert eng.disk_free_gb == 400
    assert said == []


def test_it_is_said_once_per_crossing_and_not_once_a_minute(monkeypatch):
    """A notification every sixty seconds for an hour is a notification
    nobody reads, and the dashboard carries the number continuously."""
    from autostream import engine as eng_mod

    said = []
    monkeypatch.setattr(eng_mod.notify, "toast",
                        lambda *a, **k: said.append(a))
    eng = _disk_engine(free_gb=60, warn_at=100)
    for _ in range(5):
        eng._disk_checked = 0.0
        eng._check_disk()
    assert len(said) == 1, f"{len(said)} notifications for one crossing"


def test_space_freed_and_lost_again_is_said_again(monkeypatch):
    from autostream import engine as eng_mod

    said = []
    monkeypatch.setattr(eng_mod.notify, "toast",
                        lambda *a, **k: said.append(a))
    eng = _disk_engine(free_gb=60, warn_at=100)
    eng._check_disk()
    eng._free_gb = lambda: 400
    eng._disk_checked = 0.0
    eng._check_disk()
    eng._free_gb = lambda: 60
    eng._disk_checked = 0.0
    eng._check_disk()
    assert len(said) == 2


def test_a_warning_level_of_zero_is_off(monkeypatch):
    from autostream import engine as eng_mod

    said = []
    monkeypatch.setattr(eng_mod.notify, "toast",
                        lambda *a, **k: said.append(a))
    eng = _disk_engine(free_gb=1, warn_at=0, floor=0)
    eng._check_disk()
    assert said == []


def test_the_floor_still_stops_the_recording(monkeypatch):
    """The warning must not have replaced the thing that actually acts."""
    from autostream import engine as eng_mod

    monkeypatch.setattr(eng_mod.notify, "toast", lambda *a, **k: None)
    stopped = []
    eng = _disk_engine(free_gb=5, warn_at=100, floor=10)
    eng.toggle_recording = lambda why="": stopped.append(why)
    eng._check_disk()
    assert stopped, "the drive is under the floor and the recording ran on"
