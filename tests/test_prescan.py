"""Reading a finished session's kills before anyone asks for them.

`record.auto_scan` has been on by default since long before this file, and
promised "when a session ends, scan its recording for kill markers in the
background so the Clips page already has them ready when you open it".

IT DID NOTHING. The engine set `pending_scan` and nothing anywhere read it --
the whole feature was one assignment and a help text. A setting that is on by
default and does nothing is worse than one that is missing: the Clips page
looked slow for a reason that was never true, and anyone who turned it off to
save CPU saved nothing.
"""
from __future__ import annotations

import json
import types

import pytest

from autostream.clips import prescan


class _Prof:
    """A profile that is usable and reads nothing real."""

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.label = "Testing"

    def exists(self):
        return self.ok


class _Kill:
    def __init__(self, t):
        self.time = t
        self.end = t + 1.0
        self.score = 0.9
        self.count = 1


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A clips root, a recording on disk, and a detector that answers."""
    root = tmp_path / "clips"
    root.mkdir()
    rec = tmp_path / "session.mp4"
    rec.write_bytes(b"not really a video")

    monkeypatch.setattr(prescan, "_clips_root", lambda c: root)
    monkeypatch.setattr(prescan.profiles, "for_game",
                        lambda key, name=None: _Prof())

    scanned = []

    def fake_scan(video, prof, **kw):
        scanned.append(str(video))
        return [_Kill(10.0), _Kill(25.0), _Kill(26.0)]

    from autostream.clips import detect

    monkeypatch.setattr(detect, "scan", fake_scan)
    return types.SimpleNamespace(root=root, rec=rec, scanned=scanned,
                                 entry={"recording_path": str(rec),
                                        "game": "Testing",
                                        "game_key": "testing.exe",
                                        "started": 1_790_000_000.0})


def _cfg():
    return types.SimpleNamespace(clips=types.SimpleNamespace(output_dir=""))


def _sidecars(root):
    return sorted(root.glob("*/session.json"))


# ---------------------------------------------------------- it reads

def test_it_writes_the_kills_where_the_clips_page_looks(home):
    got = prescan.run(home.entry, _cfg())
    assert got is not None
    files = _sidecars(home.root)
    assert len(files) == 1, files
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert len(data["kills"]) == 3
    assert data["source"] == str(home.rec)


def test_the_kills_carry_what_a_run_would_have_recorded(home):
    """The next run reuses these, so they have to be the same shape a clip
    job writes -- `end` included, which is what a clip is cut against."""
    prescan.run(home.entry, _cfg())
    data = json.loads(_sidecars(home.root)[0].read_text(encoding="utf-8"))
    for k in data["kills"]:
        assert set(k) == {"time", "end", "score", "count"}
        assert k["end"] >= k["time"]


def test_it_records_that_it_read_the_whole_file(home):
    """[0, 0] is "the whole file" -- the same spelling a full run uses. A
    windowed list is complete only inside its window, and a reader that could
    not tell the difference would report "no kills" for everything outside
    it."""
    prescan.run(home.entry, _cfg())
    data = json.loads(_sidecars(home.root)[0].read_text(encoding="utf-8"))
    assert data["scanned"] == [0.0, 0.0]


def test_it_cuts_nothing(home):
    """THE LINE THIS MUST NOT CROSS. Cutting takes the GPU for minutes,
    writes files nobody asked for, and makes choices -- style, length,
    minimum kills -- that belong to the person and not to the end of a
    stream."""
    prescan.run(home.entry, _cfg())
    folder = _sidecars(home.root)[0].parent
    assert list(folder.glob("*.mp4")) == []
    assert not (folder / "clips").exists()
    assert not (folder / "vertical").exists()
    data = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    assert data["read_only"] is True


# --------------------------------------------------------- it refuses

def test_a_recording_that_is_gone_is_not_read(home):
    home.rec.unlink()
    assert prescan.run(home.entry, _cfg()) is None
    assert _sidecars(home.root) == []


def test_a_game_with_no_usable_profile_is_not_read(home, monkeypatch):
    """Most games. There is nothing to find and the scan would be minutes of
    decoding for an empty list."""
    monkeypatch.setattr(prescan.profiles, "for_game",
                        lambda key, name=None: None)
    assert prescan.run(home.entry, _cfg()) is None
    assert home.scanned == []


def test_a_profile_that_is_not_set_up_is_not_read(home, monkeypatch):
    monkeypatch.setattr(prescan.profiles, "for_game",
                        lambda key, name=None: _Prof(ok=False))
    assert prescan.run(home.entry, _cfg()) is None
    assert home.scanned == []


def test_a_recording_already_read_is_not_read_again(home):
    """A session that ends, restarts and ends again would otherwise be read
    twice -- and the scan is the expensive part."""
    prescan.run(home.entry, _cfg())
    assert len(home.scanned) == 1
    prescan.run(home.entry, _cfg())
    assert len(home.scanned) == 1, "it read the same recording twice"
    assert len(_sidecars(home.root)) == 1


def test_a_windowed_run_does_not_count_as_having_read_it(home):
    """Its kill list is complete only inside its window. Treating it as
    "already read" would leave everything outside permanently unread."""
    folder = home.root / "earlier"
    folder.mkdir()
    (folder / "session.json").write_text(json.dumps({
        "source": str(home.rec), "scanned": [600.0, 1200.0],
        "kills": [{"time": 700.0}]}), encoding="utf-8")

    assert prescan.run(home.entry, _cfg()) is not None
    assert home.scanned == [str(home.rec)]


def test_a_full_run_by_the_user_does_count(home):
    folder = home.root / "a-real-run"
    folder.mkdir()
    (folder / "session.json").write_text(json.dumps({
        "source": str(home.rec), "scanned": [0.0, 0.0],
        "kills": [{"time": 10.0}]}), encoding="utf-8")

    assert prescan.run(home.entry, _cfg()) is None
    assert home.scanned == []


def test_a_detector_that_throws_is_not_fatal(home, monkeypatch):
    """This runs on a thread nobody is watching, at the end of a stream."""
    from autostream.clips import detect

    def boom(*a, **k):
        raise RuntimeError("ffmpeg fell over")

    monkeypatch.setattr(detect, "scan", boom)
    assert prescan.run(home.entry, _cfg()) is None


# -------------------------------------------- it waits for the real runner

def test_it_waits_for_a_clip_job_the_user_started(home, monkeypatch):
    """They compete for the same decoder and the same disk, and a background
    read that makes a run the user is WATCHING take twice as long is a
    feature doing harm."""
    monkeypatch.setattr(prescan, "POLL", 0.01)
    monkeypatch.setattr(prescan, "WAIT_FOR_RUNNER", 0.05)
    busy = types.SimpleNamespace(busy=lambda: True)

    assert prescan.run(home.entry, _cfg(), busy) is None
    assert home.scanned == [], "it read anyway while a job was running"


def test_it_goes_ahead_once_the_runner_is_free(home, monkeypatch):
    monkeypatch.setattr(prescan, "POLL", 0.01)
    calls = {"n": 0}

    def busy():
        calls["n"] += 1
        return calls["n"] < 3

    assert prescan.run(home.entry, _cfg(),
                       types.SimpleNamespace(busy=busy)) is not None
    assert home.scanned == [str(home.rec)]


def test_a_runner_that_cannot_be_asked_does_not_block_it(home):
    class Broken:
        def busy(self):
            raise RuntimeError("no runner here")

    assert prescan.run(home.entry, _cfg(), Broken()) is not None


# ------------------------------------------------------------ one at a time

def test_only_one_read_runs_at_a_time(home, monkeypatch):
    """Two reads of the same recording competing for the same decoder is
    worse than one, and strictly slower than none."""
    import threading

    gate = threading.Event()
    from autostream.clips import detect

    def slow(video, prof, **kw):
        home.scanned.append(str(video))
        gate.wait(5.0)
        return []

    monkeypatch.setattr(detect, "scan", slow)

    assert prescan.start(home.entry, _cfg()) is True
    for _ in range(200):
        if prescan.busy():
            break
        import time as _t
        _t.sleep(0.01)
    assert prescan.start(home.entry, _cfg()) is False, "a second read started"
    gate.set()
    for _ in range(300):
        if not prescan.busy():
            break
        import time as _t
        _t.sleep(0.01)
    assert not prescan.busy()


def test_an_entry_with_no_recording_starts_nothing(home):
    assert prescan.start({"game": "Testing"}, _cfg()) is False


# ====================================== the link that was never there

def test_the_engine_starts_a_read_when_a_session_ends(monkeypatch):
    """THE WHOLE BUG. `pending_scan` was assigned and read by nothing, so the
    setting promised a background scan that no code anywhere performed."""
    import fakes
    from autostream import engine as eng_mod

    eng = fakes.engine()
    eng.cfg["record"] = dict(eng.cfg["record"])
    eng.cfg["record"]["auto_scan"] = True

    started = []
    monkeypatch.setattr(
        "autostream.clips.prescan.start",
        lambda entry, config, runner=None: started.append(entry) or True)

    entry = {"recording_path": "C:/vid/x.mp4", "game": "Testing"}
    eng._read_kills(entry)
    assert started == [entry], "the engine still reads nothing"


def test_a_read_that_will_not_start_does_not_break_the_end_of_a_session(
        monkeypatch):
    """A session that ended correctly must not report a failure because an
    optional background read did not start."""
    import fakes

    def boom(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr("autostream.clips.prescan.start", boom)
    fakes.engine()._read_kills({"recording_path": "C:/vid/x.mp4"})


def _journalling(monkeypatch, *, auto_scan: bool):
    """An engine at the moment a session is journalled. -> (engine, started)."""
    import fakes

    eng = fakes.engine()
    eng.cfg["record"] = dict(eng.cfg["record"])
    eng.cfg["record"]["auto_scan"] = auto_scan
    eng.state.broadcast_id = ""
    eng._last_title = "t"
    eng._marks = []
    eng.yt = types.SimpleNamespace(watch_url=lambda b: "")

    started = []
    monkeypatch.setattr(
        "autostream.clips.prescan.start",
        lambda entry, config, runner=None: started.append(entry) or True)
    monkeypatch.setattr("autostream.history.record_session",
                        lambda *a, **k: {"recording_path": "C:/vid/x.mp4",
                                         "game": "Testing"})
    monkeypatch.setattr(eng, "_remind_about_demo", lambda e: None)
    return eng, started


def test_journalling_a_session_starts_the_read(monkeypatch):
    """Through the real path, not by calling the helper -- `_journal` is where
    the dead assignment lived."""
    eng, started = _journalling(monkeypatch, auto_scan=True)
    eng._journal("C:/vid/x.mp4")
    assert len(started) == 1, "the end of a session still reads nothing"
    assert started[0]["recording_path"] == "C:/vid/x.mp4"


def test_the_setting_is_what_decides(monkeypatch):
    """Turning it off has to actually turn something off -- which, before
    this, it did not, because there was nothing on."""
    eng, started = _journalling(monkeypatch, auto_scan=False)
    eng._journal("C:/vid/x.mp4")
    assert started == [], "it read with the setting switched off"
