"""The silent-stream watchdog.

A stream can be healthy by every readout OBS offers -- output active, no
dropped frames, a bright picture -- and still be going out silent, because the
scene collection has no audio device in it. That is not hypothetical: it is how
a session went out on 26 August 2026, and nothing in the app said a word.

The hard requirement is the negative one. Metering that never came up must not
read as silence, or every stream on an older OBS raises a false alarm.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import cfg                                      # noqa: E402
from autostream.obs import Obs                                  # noqa: E402
from autostream.engine import Engine                            # noqa: E402
from autostream.state import LIVE, State                        # noqa: E402


def an_obs() -> Obs:
    return Obs(cfg.load())


# ------------------------------------------------------------- silent_for

def test_no_metering_is_not_silence():
    """The false-alarm guard. None means "cannot tell", never "quiet"."""
    o = an_obs()
    assert o._audio_ok is False
    assert o.silent_for() is None


def test_silence_is_measured_from_when_listening_began(monkeypatch):
    """A stream silent from its very first second still has to be caught, so
    "connected, nothing heard yet" cannot mean "unknown"."""
    import autostream.obs as obsmod

    o = an_obs()
    o._audio_ok = True
    o._audio_heard = None
    o._audio_since = obsmod.time.monotonic() - 42.0
    quiet = o.silent_for()
    assert quiet is not None and 41.0 < quiet < 60.0


def test_sound_resets_the_clock(monkeypatch):
    import autostream.obs as obsmod

    o = an_obs()
    o._audio_ok = True
    o._audio_since = obsmod.time.monotonic() - 500.0
    o._audio_heard = obsmod.time.monotonic() - 3.0
    quiet = o.silent_for()
    assert quiet is not None and quiet < 10.0


# --------------------------------------------------------------- the engine

class Quiet:
    """An Obs whose stream has been silent for a given number of seconds."""
    def __init__(self, quiet):
        self.quiet = quiet

    def silent_for(self):
        return self.quiet


def an_engine(quiet) -> Engine:
    eng = Engine.__new__(Engine)
    eng.state = State(phase=LIVE)
    eng.state.save = lambda: None            # type: ignore[method-assign]
    eng.obs = Quiet(quiet)
    eng._silent_said = False
    return eng


def test_a_quiet_moment_is_not_a_fault(caplog):
    """A menu, a held breath, a reload. Only a long silence is news."""
    eng = an_engine(10.0)
    eng._check_audio()
    assert eng._silent_said is False


def test_a_long_silence_is_reported_once(caplog):
    eng = an_engine(Engine.SILENT_AFTER + 5)
    eng._check_audio()
    assert eng._silent_said is True
    eng._check_audio()                       # still silent, still one report
    assert eng._silent_said is True


def test_unavailable_metering_never_reports(caplog):
    """The whole reason silent_for() can return None."""
    eng = an_engine(None)
    for _ in range(5):
        eng._check_audio()
    assert eng._silent_said is False


def test_audio_coming_back_clears_it():
    eng = an_engine(Engine.SILENT_AFTER + 5)
    eng._check_audio()
    assert eng._silent_said is True
    eng.obs.quiet = 1.0
    eng._check_audio()
    assert eng._silent_said is False
