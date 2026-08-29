"""A recording nothing remembers making.

The Clips page lists journalled SESSIONS, not files on disk. After an unclean
shutdown _stop_recording() answers None -- OBS outlives AutoStream and may have
been closed since -- and the session was journalled with recording_path=None.
The file stayed on disk, unreachable, with nothing anywhere saying so.

That is how a 44.6 GB recording went missing. It was found by matching OBS's
own filename stamp against the session's start, which is what this does.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import cfg                                       # noqa: E402
from autostream.engine import Engine                             # noqa: E402
from autostream.state import LIVE, State                         # noqa: E402


def rec(folder: Path, when: datetime, name=None) -> Path:
    """A file named the way OBS names recordings."""
    f = folder / (name or when.strftime("%Y-%m-%d %H-%M-%S") + ".mp4")
    f.write_bytes(b"x")
    return f


def an_engine(tmp_path, started: datetime) -> Engine:
    eng = Engine.__new__(Engine)
    c = cfg.load()
    raw = {k: (dict(v) if isinstance(v, dict) else v) for k, v in c.items()}
    raw["record"] = dict(raw["record"])
    raw["record"]["directory"] = str(tmp_path)
    eng.cfg = cfg.Config(raw)
    eng.state = State(phase=LIVE)
    eng.state.session_start = started.timestamp()
    eng.state.save = lambda: None            # type: ignore[method-assign]
    return eng


def test_the_recording_is_found_by_its_filename_stamp(tmp_path):
    started = datetime(2026, 8, 27, 22, 59, 18)
    want = rec(tmp_path, started)
    eng = an_engine(tmp_path, started)
    assert eng._adopt_recording() == str(want)


def test_a_few_seconds_of_drift_is_still_the_same_recording(tmp_path):
    """The session starts, then OBS is told to record: they differ by however
    long that took."""
    started = datetime(2026, 8, 27, 22, 59, 18)
    want = rec(tmp_path, datetime(2026, 8, 27, 22, 59, 25))
    eng = an_engine(tmp_path, started)
    assert eng._adopt_recording() == str(want)


def test_an_unrelated_recording_is_not_stolen(tmp_path):
    """A file from hours earlier belongs to another session, and claiming it
    would attach the wrong footage to this one -- worse than none."""
    started = datetime(2026, 8, 27, 22, 59, 18)
    rec(tmp_path, datetime(2026, 8, 27, 18, 3, 0))
    eng = an_engine(tmp_path, started)
    assert eng._adopt_recording() is None


def test_the_closest_one_wins(tmp_path):
    started = datetime(2026, 8, 27, 22, 59, 18)
    rec(tmp_path, datetime(2026, 8, 27, 22, 58, 0))
    want = rec(tmp_path, datetime(2026, 8, 27, 22, 59, 20))
    eng = an_engine(tmp_path, started)
    assert eng._adopt_recording() == str(want)


def test_files_that_are_not_recordings_are_ignored(tmp_path):
    started = datetime(2026, 8, 27, 22, 59, 18)
    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / "no-stamp-here.mp4").write_bytes(b"x")
    eng = an_engine(tmp_path, started)
    assert eng._adopt_recording() is None


def test_an_empty_folder_is_not_an_error(tmp_path):
    eng = an_engine(tmp_path, datetime(2026, 8, 27, 22, 59, 18))
    assert eng._adopt_recording() is None


def test_no_session_start_means_nothing_to_match(tmp_path):
    rec(tmp_path, datetime(2026, 8, 27, 22, 59, 18))
    eng = an_engine(tmp_path, datetime(2026, 8, 27, 22, 59, 18))
    eng.state.session_start = None
    assert eng._adopt_recording() is None


def test_mkv_is_found_too(tmp_path):
    """OBS records mkv by default in many setups, precisely because it
    survives a crash -- which is the case this whole function is for."""
    started = datetime(2026, 8, 27, 22, 59, 18)
    want = rec(tmp_path, started, name="2026-08-27 22-59-18.mkv")
    eng = an_engine(tmp_path, started)
    assert eng._adopt_recording() == str(want)
