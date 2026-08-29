"""One dead audio source among several.

The silence watchdog asks whether ANY sound reaches the encoder, so a live
game with a dead microphone passes it: the game is loud and the stream is not
silent. Nobody hears the streamer, though, which is its own failure and the
more common one -- a muted source, a device that vanished with a headset, or
one pointed at the wrong input.

That is not hypothetical either: on 29 August this app had a Desktop Audio
source and no microphone at all, and nothing said so until it was asked.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import cfg                                       # noqa: E402
import autostream.obs as obsmod                                  # noqa: E402
from autostream.engine import Engine                             # noqa: E402
from autostream.state import LIVE, State                         # noqa: E402


def an_obs(**heard):
    """An Obs whose metering is up, with each input last heard N seconds ago."""
    o = obsmod.Obs(cfg.load())
    o._audio_ok = True
    now = obsmod.time.monotonic()
    o._audio_since = now - 600
    o._audio_by_input = {n: (now - ago if ago is not None else 0.0)
                         for n, ago in heard.items()}
    o._audio_heard = now - min(a for a in heard.values() if a is not None)
    return o


def test_a_dead_mic_beside_a_loud_game_is_named():
    o = an_obs(**{"Desktop Audio": 1, "Mic": 400})
    assert o.quiet_inputs(300.0) == ["Mic"]


def test_everything_audible_reports_nothing():
    o = an_obs(**{"Desktop Audio": 1, "Mic": 4})
    assert o.quiet_inputs(300.0) == []


def test_a_wholly_silent_stream_is_not_reported_here():
    """That is silence, and silent_for already covers it. Naming every source
    would double the alarm and point at the wrong thing."""
    o = an_obs(**{"Desktop Audio": 400, "Mic": 400})
    assert o.quiet_inputs(300.0) == []


def test_metering_that_never_came_up_reports_nothing():
    o = obsmod.Obs(cfg.load())
    assert o._audio_ok is False
    assert o.quiet_inputs(300.0) == []


def test_a_source_never_heard_at_all_still_counts():
    """A microphone that has produced nothing since the stream began is the
    exact case -- it is not "recently quiet", it has never worked."""
    o = an_obs(**{"Desktop Audio": 1, "Mic": None})
    assert o.quiet_inputs(300.0) == ["Mic"]


# ------------------------------------------------------------- the engine

class Obs:
    def __init__(self, quiet):
        self.quiet = quiet
    def silent_for(self):
        return 1.0                       # the stream itself is fine
    def quiet_inputs(self, floor):
        return list(self.quiet)


def an_engine(quiet):
    eng = Engine.__new__(Engine)
    eng.state = State(phase=LIVE)
    eng.state.save = lambda: None        # type: ignore[method-assign]
    eng.obs = Obs(quiet)
    eng._silent_said = False
    eng._quiet_said = set()
    return eng


def test_the_engine_reports_a_dead_source_once():
    eng = an_engine(["Mic"])
    eng._check_audio()
    assert eng._quiet_said == {"Mic"}
    eng._check_audio()                   # still dead, still one report
    assert eng._quiet_said == {"Mic"}


def test_it_clears_when_the_source_comes_back():
    eng = an_engine(["Mic"])
    eng._check_audio()
    assert eng._quiet_said == {"Mic"}
    eng.obs.quiet = []
    eng._check_audio()
    assert eng._quiet_said == set()


def test_a_failure_asking_obs_never_breaks_the_tick():
    class Broken(Obs):
        def quiet_inputs(self, floor):
            raise RuntimeError("websocket went away")
    eng = an_engine([])
    eng.obs = Broken([])
    eng._check_audio()                   # must not raise
    assert eng._quiet_said == set()
