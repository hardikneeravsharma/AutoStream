"""Connecting to OBS, and the difference between waiting and hanging.

The engine is right to wait for OBS: a session depends on it and it may still
be starting. The setup wizard's Test button is not, and shared the same code --
so the first click a new user made froze for the better part of a minute and
then reported a websocket error they could not act on. Both behaviours are
pinned here because the symptom is a stopwatch, not an exception.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest                                                # noqa: E402

from autostream import cfg, obs as obsmod                     # noqa: E402
from autostream.obs import Obs, ObsUnavailable                # noqa: E402


def an_obs() -> Obs:
    return Obs(cfg.load())


@pytest.fixture
def no_sleep(monkeypatch):
    """Record every backoff instead of serving it."""
    slept: list[float] = []
    monkeypatch.setattr(obsmod.time, "sleep", lambda s: slept.append(s))
    return slept


# ------------------------------------------------------------------ probe

def test_probe_does_not_launch_obs(monkeypatch):
    """A button called Test must not start an application.

    connect() launches OBS when it cannot find it, which is right for the
    engine and startling from a wizard -- and on a machine where OBS needs
    elevation it raises a UAC prompt in front of somebody who only asked
    whether their password was correct.
    """
    launched = []
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: False)
    monkeypatch.setattr(Obs, "_launch", lambda self: launched.append(1))

    r = an_obs().probe()
    assert r["ok"] is False
    assert r["reason"] == "not_running"
    assert launched == [], "probe launched OBS"


def test_probe_never_sleeps(no_sleep, monkeypatch):
    """The whole point. Any backoff here is a freeze in front of a person."""
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)

    def boom(self, timeout=5):
        raise OSError("[WinError 10061] connection refused")
    monkeypatch.setattr(Obs, "_connect", boom)

    r = an_obs().probe()
    assert r["ok"] is False
    assert no_sleep == [], f"probe slept {no_sleep}"


def test_probe_names_the_fix_not_the_symptom(monkeypatch):
    """"could not reach obs-websocket" tells a new user nothing to do."""
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)

    cases = {
        "authentication failed": "auth",
        "[WinError 10061] connection refused": "closed",
        "something else entirely": "error",
    }
    for message, reason in cases.items():
        def boom(self, timeout=5, _m=message):
            raise OSError(_m)
        monkeypatch.setattr(Obs, "_connect", boom)
        r = an_obs().probe()
        assert r["reason"] == reason, f"{message!r} -> {r['reason']}"
        assert r["error"], "every failure has to say something"


# ---------------------------------------------------------------- connect

def test_connect_does_not_sleep_after_its_last_attempt(no_sleep, monkeypatch):
    """It used to, which added a whole retry interval to every failure and
    changed nothing about it -- the caller is already out of attempts.

    wait=True because retrying is now what a session START does, not what
    every call does; see the fast-fail tests below.
    """
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)

    def boom(self, timeout=5):
        raise OSError("nope")
    monkeypatch.setattr(Obs, "_connect", boom)

    with pytest.raises(ObsUnavailable):
        an_obs().connect(wait=True)

    assert len(no_sleep) == Obs.ATTEMPTS - 1, (
        f"{Obs.ATTEMPTS} attempts should serve {Obs.ATTEMPTS - 1} backoffs, "
        f"got {len(no_sleep)}")


def test_connect_still_retries_for_the_engine(no_sleep, monkeypatch):
    """OBS may be mid-launch when a session starts, so the retry loop stays."""
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)
    calls = []

    class Ws:
        def get_version(self):
            return type("V", (), {"obs_version": "32", "rpc_version": 1})()

    def flaky(self, timeout=5):
        calls.append(1)
        if len(calls) < 2:
            raise OSError("not up yet")
        return Ws()
    monkeypatch.setattr(Obs, "_connect", flaky)

    an_obs().connect(wait=True)
    assert len(calls) == 2
    assert len(no_sleep) == 1, "one failed attempt, one backoff"


# ------------------------------------------------- not waiting, by default

def test_an_ordinary_call_does_not_retry(no_sleep, monkeypatch):
    """THE STUCK SESSION. Every call used to spend the full retry budget --
    three attempts twelve seconds apart, plus a launch -- whenever OBS was not
    answering. The engine loop is serial, so half a minute of that blocked the
    tick, the ingestion timeout, and every button. End stream was pressed seven
    times against a session that could not get a turn to end."""
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)
    tries = []

    def boom(self, timeout=5):
        tries.append(1)
        raise OSError("refused")
    monkeypatch.setattr(Obs, "_connect", boom)

    with pytest.raises(ObsUnavailable):
        an_obs().connect()
    assert len(tries) == 1, "an ordinary call retried"
    assert no_sleep == [], "an ordinary call slept"


def test_an_ordinary_call_never_launches_obs(monkeypatch):
    """Starting OBS from a status poll would relaunch it behind the user."""
    launched = []
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: False)
    monkeypatch.setattr(Obs, "_launch", lambda self: launched.append(1))
    monkeypatch.setattr(Obs, "_connect",
                        lambda self, timeout=5: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(ObsUnavailable):
        an_obs().connect()
    assert launched == []


def test_a_failure_is_remembered_so_the_next_call_is_instant(monkeypatch):
    """One dead websocket should cost one handshake, not one per call."""
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)
    tries = []

    def boom(self, timeout=5):
        tries.append(1)
        raise OSError("refused")
    monkeypatch.setattr(Obs, "_connect", boom)

    o = an_obs()
    for _ in range(5):
        with pytest.raises(ObsUnavailable):
            o.connect()
    assert len(tries) == 1, "it kept re-running a doomed handshake"


def test_a_waiting_call_ignores_the_remembered_failure(no_sleep, monkeypatch):
    """Starting a session must still try, even seconds after a failed poll --
    that is exactly when OBS is being launched and is not up yet."""
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)
    tries = []

    def boom(self, timeout=5):
        tries.append(1)
        raise OSError("refused")
    monkeypatch.setattr(Obs, "_connect", boom)

    o = an_obs()
    with pytest.raises(ObsUnavailable):
        o.connect()
    with pytest.raises(ObsUnavailable):
        o.connect(wait=True)
    assert len(tries) == 1 + Obs.ATTEMPTS


def test_coming_back_clears_the_memory(monkeypatch):
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)
    state = {"up": False}

    class Ws:
        def get_version(self):
            return type("V", (), {"obs_version": "32", "rpc_version": 1})()

    def flaky(self, timeout=5):
        if not state["up"]:
            raise OSError("refused")
        return Ws()
    monkeypatch.setattr(Obs, "_connect", flaky)

    o = an_obs()
    with pytest.raises(ObsUnavailable):
        o.connect()
    state["up"] = True
    o.ws = None
    o._down_until = 0.0          # as it would be once the window passed
    o.connect()
    assert o.ws is not None


def test_starting_a_recording_may_launch_obs(monkeypatch, no_sleep):
    """The record-only session's start, and it has to be allowed to open OBS.

    With streaming off there is no start() call, so this is the only thing
    that reaches OBS when a session begins. It used to connect without
    waiting, which never launches -- so on a machine where OBS was not already
    open, recording could not start at all. The engine gave up after three
    tries and paused itself, having told the user to check an application it
    had never asked to run.
    """
    launched = []
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: False)
    monkeypatch.setattr(Obs, "_launch", lambda self: launched.append(1))
    monkeypatch.setattr(Obs, "_connect",
                        lambda self, timeout=5: (_ for _ in ()).throw(OSError("no")))

    with pytest.raises(ObsUnavailable):
        an_obs().start_recording()

    assert launched, "starting a recording did not launch OBS"


def test_starting_a_recording_ignores_a_remembered_failure(monkeypatch, no_sleep):
    """A failure moments earlier must not veto the session's own attempt.

    Every call in _start_recording -- reading the directory, setting it,
    asking whether OBS is already rolling -- runs before this one and arms the
    remembered-failure shortcut. If start_recording honoured it too, the
    attempt that is allowed to launch OBS would be skipped every time, which
    is exactly how it failed in practice.
    """
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)
    tries = []

    def boom(self, timeout=5):
        tries.append(1)
        raise OSError("refused")
    monkeypatch.setattr(Obs, "_connect", boom)

    o = an_obs()
    with pytest.raises(ObsUnavailable):
        o.connect()                      # arms the shortcut
    assert len(tries) == 1
    with pytest.raises(ObsUnavailable):
        o.start_recording()
    assert len(tries) > 1, "the session's own attempt was skipped"
