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
    changed nothing about it -- the caller is already out of attempts."""
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)

    def boom(self, timeout=5):
        raise OSError("nope")
    monkeypatch.setattr(Obs, "_connect", boom)

    with pytest.raises(ObsUnavailable):
        an_obs().connect()

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

    an_obs().connect()
    assert len(calls) == 2
    assert len(no_sleep) == 1, "one failed attempt, one backoff"
