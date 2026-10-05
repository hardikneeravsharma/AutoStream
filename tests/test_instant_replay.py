"""Instant replay: the clip that already exists when you press the key.

OBS keeps the last N seconds of output in memory and writes them out on
demand, so there is nothing to detect, nothing to scan and no wait -- which
is why this is the one clip feature that works in a game AutoStream cannot
read a word of.

No OBS. Every websocket call is replaced; what is worth asserting is the
decisions around them, and the one race that produces a plausible wrong
answer rather than an error.
"""
from __future__ import annotations

import pytest

from autostream.obs import Obs


class FakeWs:
    """Just enough OBS to answer the replay requests."""

    def __init__(self, *, active=True, path=None, start_raises=False):
        self.active = active
        self.path = path
        self.start_raises = start_raises
        self.calls: list[str] = []
        self.params: list[tuple] = []
        # How many polls before the saved file is named. OBS answers the save
        # request before it has finished muxing.
        self.mux_polls = 1
        self._polls = 0
        self.next_path = "C:/vid/Replay 2026-10-05 19-20-21.mkv"

    def get_replay_buffer_status(self):
        return type("R", (), {"output_active": self.active})()

    def start_replay_buffer(self):
        self.calls.append("start")
        if self.start_raises:
            raise RuntimeError("replay buffer is disabled in OBS")
        self.active = True

    def stop_replay_buffer(self):
        self.calls.append("stop")
        self.active = False

    def save_replay_buffer(self):
        self.calls.append("save")
        self._polls = 0

    def get_last_replay_buffer_replay(self):
        if "save" in self.calls:
            self._polls += 1
            if self._polls > self.mux_polls:
                return type("R", (), {"saved_replay_path": self.next_path})()
        return type("R", (), {"saved_replay_path": self.path or ""})()

    def set_profile_parameter(self, section, key, value):
        self.params.append((section, key, value))


@pytest.fixture
def obs(monkeypatch):
    o = Obs.__new__(Obs)
    o.ws = FakeWs()
    monkeypatch.setattr(Obs, "connect", lambda self, wait=False: None)
    return o


# ------------------------------------------------------------ starting it

def test_a_buffer_that_was_already_running_is_adopted(obs):
    """Somebody who runs their own replay buffer should not have it
    interrupted and restarted by a session beginning."""
    obs.ws.active = True
    assert obs.start_replay_buffer() is True
    assert "start" not in obs.ws.calls


def test_it_is_started_when_nothing_is_running(obs):
    obs.ws.active = False
    assert obs.start_replay_buffer() is False
    assert obs.ws.calls == ["start"]


def test_obs_refusing_is_not_fatal(obs):
    """OBS will not run a replay buffer unless it is switched on in its own
    Output settings. That is a thing to say, not a reason to abandon a
    session -- the recording and the stream are what the session is for."""
    obs.ws.active = False
    obs.ws.start_raises = True
    assert obs.start_replay_buffer() is False     # and does not raise


def test_stopping_a_buffer_that_is_not_running_does_nothing(obs):
    obs.ws.active = False
    obs.stop_replay_buffer()
    assert "stop" not in obs.ws.calls


# ------------------------------------------------- the file it writes out

def test_the_saved_file_is_the_one_that_was_just_saved(obs):
    """THE RACE THAT GIVES A PLAUSIBLE WRONG ANSWER. OBS answers the save
    request before it has finished muxing, so the filename is not available
    at that moment -- and asking immediately returns the PREVIOUS replay.
    That is worse than an error: a real path, to the wrong clip, which only
    shows up when somebody opens it and finds a different moment."""
    obs.ws.path = "C:/vid/an-older-replay.mkv"
    obs.ws.next_path = "C:/vid/the-one-just-asked-for.mkv"
    obs.ws.mux_polls = 3
    got = obs.save_replay(timeout=5.0)
    assert got == "C:/vid/the-one-just-asked-for.mkv"


def test_a_name_that_never_arrives_is_reported_as_unknown(obs):
    """It almost certainly saved. Claiming the previous clip is this one is
    the thing not to do."""
    obs.ws.mux_polls = 10_000
    assert obs.save_replay(timeout=0.8) is None


def test_saving_with_no_buffer_running_does_not_pretend(obs):
    obs.ws.active = False
    obs.ws.path = "C:/vid/left-over-from-last-time.mkv"
    assert obs.save_replay() is None
    assert "save" not in obs.ws.calls


# ------------------------------------------------------- the buffer length

def test_the_configured_length_is_pushed_to_obs(obs):
    """A profile parameter, not a websocket setting -- and pushed every
    session for the same reason the record directory is: the config is the
    source of truth and OBS is not. Left alone, "two minutes" in AutoStream
    would mean whatever OBS was last set to, silently."""
    obs.set_replay_seconds(120)
    assert ("SimpleOutput", "RecRBTime", "120") in obs.ws.params


def test_both_output_modes_are_written(obs):
    """OBS keeps it under a different section depending on whether the
    profile is in Simple or Advanced output mode."""
    obs.set_replay_seconds(45)
    assert {p[0] for p in obs.ws.params} == {"SimpleOutput", "AdvOut"}


@pytest.mark.parametrize("asked,written", [(3, "5"), (9999, "300"), (30, "30")])
def test_the_length_is_held_inside_what_obs_will_take(obs, asked, written):
    obs.set_replay_seconds(asked)
    assert obs.ws.params[0][2] == written


def test_an_unset_length_takes_the_default_rather_than_the_floor(obs):
    """0 in the config means nobody chose, not "as short as possible"."""
    obs.set_replay_seconds(0)
    assert obs.ws.params[0][2] == "30"


def test_a_profile_that_refuses_one_section_still_gets_the_other(obs,
                                                                 monkeypatch):
    """Only one of the two output modes is in use; the other refuses, which
    is not a problem worth failing over."""
    def picky(section, key, value):
        if section == "SimpleOutput":
            raise RuntimeError("no such parameter")
        obs.ws.params.append((section, key, value))

    monkeypatch.setattr(obs.ws, "set_profile_parameter", picky)
    obs.set_replay_seconds(60)
    assert obs.ws.params == [("AdvOut", "RecRBTime", "60")]


# ============================================ the engine's half of it

class _Obs:
    """An OBS whose replay calls are recorded rather than made."""

    def __init__(self, *, save=None):
        self.started = 0
        self.stopped = 0
        self.secs = None
        self.save_result = save
        self.saves = 0

    def start_replay_buffer(self):
        self.started += 1
        return False

    def stop_replay_buffer(self):
        self.stopped += 1

    def set_replay_seconds(self, n):
        self.secs = n

    def save_replay(self):
        self.saves += 1
        return self.save_result


@pytest.fixture
def eng(monkeypatch):
    import fakes
    from autostream import engine as eng_mod

    e = fakes.engine()
    e.obs = _Obs()
    e.replays = []
    monkeypatch.setattr(eng_mod.notify, "toast", lambda *a, **k: None)
    return e


def _set(eng, **kw):
    """Change record.* on a live Config.

    NOT `eng.cfg.record.replay_enabled = True`, and not `eng.cfg.record[k] =
    v` either: Section.__getattr__ wraps each nested dict in a NEW Section on
    every access, so the assignment lands on a throwaway. The section is also
    copied first, because cfg.load() merges over cfg.DEFAULTS and mutating it
    in place reaches the module-level defaults and leaks into every later
    test in the run.
    """
    eng.cfg["record"] = dict(eng.cfg["record"])
    for k, v in kw.items():
        eng.cfg["record"][k] = v


def test_the_buffer_is_not_started_when_the_feature_is_off(eng):
    """It is memory held for the whole session. Nobody who did not ask for it
    should be paying that."""
    _set(eng, replay_enabled=False)
    eng._start_replay_buffer()
    assert eng.obs.started == 0


def test_it_is_started_with_the_configured_length(eng):
    _set(eng, replay_enabled=True, replay_seconds=90)
    eng._start_replay_buffer()
    assert eng.obs.started == 1
    assert eng.obs.secs == 90


def test_a_buffer_that_will_not_start_does_not_stop_the_session(eng,
                                                                monkeypatch):
    _set(eng, replay_enabled=True)

    def boom():
        raise RuntimeError("OBS said no")

    monkeypatch.setattr(eng.obs, "start_replay_buffer", boom)
    eng._start_replay_buffer()                       # and does not raise


def test_saving_with_the_feature_off_says_so_rather_than_failing(eng):
    """The hotkey is bound whether or not the feature is on, so that turning
    it on in Settings works without a restart. A key that does nothing until
    you restart is indistinguishable from one that does not work."""
    _set(eng, replay_enabled=False)
    assert eng.save_replay() is None
    assert eng.obs.saves == 0


def test_a_saved_replay_is_remembered_for_the_session(eng):
    _set(eng, replay_enabled=True)
    eng.obs.save_result = "C:/vid/Replay 1.mkv"
    assert eng.save_replay() == "C:/vid/Replay 1.mkv"
    eng.obs.save_result = "C:/vid/Replay 2.mkv"
    eng.save_replay()
    assert eng.replays == ["C:/vid/Replay 1.mkv", "C:/vid/Replay 2.mkv"]


def test_a_save_that_produced_no_file_is_not_counted(eng):
    _set(eng, replay_enabled=True)
    eng.obs.save_result = None
    assert eng.save_replay() is None
    assert eng.replays == []


def test_the_replay_command_reaches_it(eng):
    _set(eng, replay_enabled=True)
    eng.obs.save_result = "C:/vid/by-hotkey.mkv"
    eng.submit("replay")
    eng._drain_commands()
    assert eng.replays == ["C:/vid/by-hotkey.mkv"]


def test_the_buffer_is_released_when_the_recording_stops(eng):
    """It is RAM, and a session that has ended has no use for it."""
    _set(eng, replay_enabled=True)
    eng.state.recording = True
    eng.obs.stop_recording = lambda: "C:/vid/session.mkv"
    eng._stop_recording()
    assert eng.obs.stopped == 1
