"""Starting and stopping the recording without touching the stream.

Recording began and ended with the session and could not be reached in between,
so the only way to stop writing a file was to end the broadcast. They are
separate things: the recording is the master the clips are cut from, and a
streamer may want it running for a session they are not broadcasting, or
stopped for a stretch they would rather not keep.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import cfg                                        # noqa: E402
from autostream.engine import Engine                              # noqa: E402
from autostream.state import LIVE, State                          # noqa: E402


class Obs:
    def __init__(self, path="C:/v/rec.mp4"):
        self.path, self.started, self.stopped = path, 0, 0

    def stop_recording(self):
        self.stopped += 1
        return self.path


def an_engine(recording=True, enabled=True) -> Engine:
    eng = Engine.__new__(Engine)
    c = cfg.load()
    raw = {k: (dict(v) if isinstance(v, dict) else v) for k, v in c.items()}
    raw["record"] = dict(raw["record"])
    raw["record"]["enabled"] = enabled
    eng.cfg = cfg.Config(raw)
    eng.state = State(phase=LIVE)
    eng.state.recording = recording
    eng.state.save = lambda: None            # type: ignore[method-assign]
    eng.obs = Obs()
    eng._marks = []
    eng._start_recording = lambda: setattr(eng.state, "recording", True)
    return eng


def test_stopping_leaves_the_stream_alone():
    eng = an_engine(recording=True)
    assert eng.toggle_recording("test") is False
    assert eng.state.recording is False
    assert eng.state.phase == LIVE, "stopping the recording ended the session"


def test_the_stopped_file_is_remembered():
    """The journal is written at the far end of the session from whatever
    _stop_recording returns, and by then OBS has forgotten this file. Without
    remembering it, a recording the user stopped by hand would be journalled as
    no recording at all and vanish from the Clips page."""
    eng = an_engine(recording=True)
    eng.toggle_recording("test")
    assert [f["path"] for f in eng._earlier_files] == ["C:/v/rec.mp4"]


def test_starting_again_sets_it_recording():
    eng = an_engine(recording=False)
    assert eng.toggle_recording("test") is True
    assert eng.state.recording is True


def test_it_refuses_when_recording_is_switched_off():
    """Offering a button that would do nothing is worse than saying why."""
    eng = an_engine(recording=False, enabled=False)
    assert eng.toggle_recording("test") is False
    assert eng.state.recording is False


def test_stopping_still_works_when_recording_is_switched_off():
    """The setting governs starting, not stopping -- a file already being
    written must always be stoppable."""
    eng = an_engine(recording=True, enabled=False)
    assert eng.toggle_recording("test") is False
    assert eng.state.recording is False


def test_the_command_is_accepted_by_the_engine():
    """The dispatch table is a literal list; a button wired to a name that is
    not in it fails silently."""
    import inspect

    from autostream import engine as em

    src = inspect.getsource(em.Engine._drain_commands)
    assert '"record"' in src


def test_the_api_accepts_the_record_command():
    import inspect

    from autostream import webui

    src = inspect.getsource(webui._Handler.do_POST)
    assert '"record"' in src, "the endpoint would reject the button"


# ------------------------------------- Record pressed with no session running

class HealthObs(Obs):
    def __init__(self, recording=True):
        super().__init__()
        self.recording = recording

    def health(self):
        return {"recording": self.recording, "active": False}


def a_loose_recording() -> Engine:
    """Stop, then Record, with the game still open: the phase stays IDLE."""
    from autostream.state import IDLE

    eng = an_engine(recording=True)
    eng.state.phase = IDLE
    eng.obs = HealthObs()
    eng.obs_health = {}
    eng._obs_checked = 0.0
    eng._obs_reachable = True
    eng._rec_missing = 0
    eng._stop_requested = False
    eng._drain_commands = lambda: None       # type: ignore[method-assign]
    eng._tick_idle = lambda: None            # type: ignore[method-assign]
    return eng


def test_an_idle_recording_is_reported_from_obs():
    """THE REPORT. The file grew by gigabytes while the dashboard said Not
    recording: OBS was only asked how it was during a session."""
    eng = a_loose_recording()
    eng.tick()
    assert eng.obs_health.get("recording") is True


def test_an_idle_recording_is_not_watchdogged():
    """Health only. The watchdog's set-asides are journalled at the end of a
    session, and a loose recording has none to end."""
    eng = a_loose_recording()
    eng.obs.recording = False
    lost = []
    eng._recording_lost = lambda **kw: lost.append(kw)   # type: ignore[method-assign]
    for _ in range(3):
        eng._obs_checked = 0.0
        eng.tick()
    assert lost == [] and eng.state.recording is True


def test_stopping_an_idle_recording_clears_the_report():
    """Or the dashboard keeps saying Recording off the last poll."""
    eng = a_loose_recording()
    eng.tick()
    eng._journal_loose = lambda path: None   # type: ignore[method-assign]
    assert eng.toggle_recording("test") is False
    assert eng.obs_health == {}


def test_the_timer_counts_an_idle_recording():
    """No session, so no session_start: the timer read --:--:--."""
    import time
    from types import SimpleNamespace

    from autostream import webui

    eng = SimpleNamespace(state=State(), _rec_began=time.time() - 65)
    srv = SimpleNamespace(engine=eng)
    eng.state.recording = True
    assert webui.Server._elapsed(srv) in (65, 66)
    eng.state.recording = False
    assert webui.Server._elapsed(srv) is None
    eng.state.session_start = time.time() - 10
    assert webui.Server._elapsed(srv) in (10, 11)


# ------------------------------------------------- the recording drive fills

def a_live_engine_with(free_gb, recording=True):
    eng = an_engine(recording=recording)
    eng._disk_checked = 0.0
    eng.disk_free_gb = None
    eng._disk_warned = False
    eng._free_gb = lambda: free_gb
    return eng


def test_a_drive_below_the_floor_stops_the_recording_not_the_stream():
    """min_free_gb was only checked when a recording started, so a long
    session could fill the drive. Below it the file stops; the broadcast
    costs no disk and carries on."""
    eng = a_live_engine_with(10.0)          # the floor is 50 by default
    eng._check_disk()
    assert eng.state.recording is False
    assert eng.state.phase == LIVE
    assert [f["path"] for f in eng._earlier_files] == ["C:/v/rec.mp4"]


def test_a_roomy_drive_leaves_the_recording_alone():
    eng = a_live_engine_with(500.0)
    eng._check_disk()
    assert eng.state.recording is True and eng.obs.stopped == 0


def test_the_drive_is_not_asked_every_tick():
    eng = a_live_engine_with(500.0)
    asked = []
    eng._free_gb = lambda: asked.append(1) or 500.0
    eng._check_disk()
    eng._check_disk()
    assert len(asked) == 1


def test_nothing_is_checked_when_not_recording():
    eng = a_live_engine_with(1.0, recording=False)
    eng._check_disk()
    assert eng.obs.stopped == 0
