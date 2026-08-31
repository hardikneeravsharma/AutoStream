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
    eng._stopped_recording = None
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
    assert eng._stopped_recording == "C:/v/rec.mp4"


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
