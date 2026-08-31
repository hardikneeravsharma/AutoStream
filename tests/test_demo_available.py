"""Telling the user whether a replay exists for a recording.

With one, a Counter-Strike clip run reads twelve minutes instead of the whole
recording, and the clips carry real round context -- a 1v4 clutch rather than
"three kills". Without, it reads everything and reads the rounds off the screen.

The user had no way to know which they were getting, and the game deletes demos
after about a fortnight, so finding out late is finding out too late.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import cs2_demo                             # noqa: E402


def demo(folder: Path, name: str, when: float) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / name
    f.write_bytes(b"x")
    os.utime(f, (when, when))
    return f


STARTED = 1_700_000_000.0
HOUR = 3600.0


def test_a_demo_written_after_the_match_is_found(tmp_path):
    """Counter-Strike writes the file when the match ENDS."""
    demo(tmp_path, "match730_1.dem", STARTED + 40 * 60)
    got = cs2_demo.demo_for_recording(tmp_path, STARTED, 45 * 60)
    assert got == "match730_1.dem"


def test_a_demo_from_before_the_recording_is_not_it(tmp_path):
    """The case that cost 2.2 minutes of scanning: the newest demo predated
    the recording by two days."""
    demo(tmp_path, "match730_old.dem", STARTED - 48 * HOUR)
    assert cs2_demo.demo_for_recording(tmp_path, STARTED, 45 * 60) is None


def test_a_demo_from_long_after_is_not_it(tmp_path):
    """A match played the next day is a different match."""
    demo(tmp_path, "match730_later.dem", STARTED + 30 * HOUR)
    assert cs2_demo.demo_for_recording(tmp_path, STARTED, 45 * 60) is None


def test_the_newest_candidate_wins(tmp_path):
    demo(tmp_path, "match730_a.dem", STARTED + 10 * 60)
    demo(tmp_path, "match730_b.dem", STARTED + 40 * 60)
    assert cs2_demo.demo_for_recording(tmp_path, STARTED, 45 * 60) == "match730_b.dem"


def test_an_empty_folder_is_a_clear_no(tmp_path):
    assert cs2_demo.demo_for_recording(tmp_path, STARTED, 45 * 60) is None


def test_no_start_time_gives_no_answer(tmp_path):
    """Better to say nothing than to guess from a recording with no date."""
    demo(tmp_path, "match730_1.dem", STARTED)
    assert cs2_demo.demo_for_recording(tmp_path, 0, 0) is None


def test_a_missing_folder_is_not_an_error(tmp_path):
    assert cs2_demo.demo_for_recording(tmp_path / "nope", STARTED, 60) is None


# ------------------------------------------------- the end-of-session nudge

def test_the_reminder_is_not_shown_for_a_game_without_demos(monkeypatch):
    """"No demo" against Valorant reads as a fault rather than as not
    applicable."""
    from autostream.engine import Engine

    said = []
    import autostream.engine as em
    monkeypatch.setattr(em.notify, "toast", lambda *a, **k: said.append(a))

    eng = Engine.__new__(Engine)
    eng._remind_about_demo({"game_key": "valorant-win64-shipping.exe",
                            "game": "VALORANT", "started": STARTED})
    assert said == []


def test_the_reminder_never_breaks_the_journal(monkeypatch):
    """It runs while a session is being written down. A reminder is never
    worth failing that for."""
    from autostream.engine import Engine
    import autostream.clips.profiles as profiles

    def boom(*a, **k):
        raise RuntimeError("profiles exploded")
    monkeypatch.setattr(profiles, "for_game", boom)

    eng = Engine.__new__(Engine)
    eng._remind_about_demo({"game_key": "cs2.exe", "game": "Counter-Strike 2",
                            "started": STARTED})     # must not raise


# ------------------------------- listed, but the download never landed

def info(folder: Path, name: str, when: float) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / name
    f.write_bytes(b"")
    os.utime(f, (when, when))
    return f


def test_a_match_listed_without_its_file_is_its_own_answer(tmp_path):
    """Counter-Strike writes the .info when the match appears in the history
    and the .dem when the download completes -- about two minutes apart on a
    real one. Five .info files and no .dem is a download that never landed,
    which a user hit while believing they had downloaded it. Telling them "no
    demo" sends them looking for a match already in front of them."""
    info(tmp_path, "match730_1.dem.info", STARTED + 30 * 60)
    got = cs2_demo.demo_state(tmp_path, STARTED, 45 * 60)
    assert got["state"] == "listed"
    assert got["file"] is None


def test_the_file_landing_changes_the_answer(tmp_path):
    info(tmp_path, "match730_1.dem.info", STARTED + 30 * 60)
    demo(tmp_path, "match730_1.dem", STARTED + 32 * 60)
    got = cs2_demo.demo_state(tmp_path, STARTED, 45 * 60)
    assert got["state"] == "have"
    assert got["file"] == "match730_1.dem"


def test_nothing_at_all_is_still_none(tmp_path):
    assert cs2_demo.demo_state(tmp_path, STARTED, 45 * 60)["state"] == "none"


def test_an_old_info_does_not_count_as_listed(tmp_path):
    """A stub from a match played days earlier says nothing about this one."""
    info(tmp_path, "match730_old.dem.info", STARTED - 48 * HOUR)
    assert cs2_demo.demo_state(tmp_path, STARTED, 45 * 60)["state"] == "none"


def test_an_info_never_masks_a_real_demo(tmp_path):
    """The .dem is the answer whenever there is one, whatever stubs sit
    beside it."""
    info(tmp_path, "match730_a.dem.info", STARTED + 5 * 60)
    info(tmp_path, "match730_b.dem.info", STARTED + 6 * 60)
    demo(tmp_path, "match730_a.dem", STARTED + 10 * 60)
    assert cs2_demo.demo_state(tmp_path, STARTED, 45 * 60)["state"] == "have"
