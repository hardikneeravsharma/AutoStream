"""An output OBS calls active that is not running.

Measured on a real session: NVENC failed mid-game with NV_ENC_ERR_INVALID_DEVICE.
OBS finalised the recording and stopped sending the stream, yet kept reporting
both outputs active with their timecode and byte counts frozen -- while
StopStream and StopRecord answered 501 "not running". Nine minutes of dead air
went unnoticed, then three sessions in a row "reused" the dead output, timed
out waiting for YouTube to see it, and paused the engine.

Nothing here reaches a real OBS, and nothing here may kill one: process
discovery is replaced wherever a restart could be reached.
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


class _Status:
    def __init__(self, active=True, duration=0, nbytes=0, paused=False,
                 reconnecting=False):
        self.output_active = active
        self.output_duration = duration
        self.output_bytes = nbytes
        self.output_paused = paused
        self.output_reconnecting = reconnecting


class _Ws:
    """Hands out one status per call per output; the last one repeats."""

    def __init__(self, stream=(), record=()):
        self.stream, self.record = list(stream), list(record)
        self.calls: list[str] = []

    def _next(self, seq):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    def get_version(self):
        return type("V", (), {"obs_version": "32", "rpc_version": 1})()

    def get_stream_status(self):
        return self._next(self.stream)

    def get_record_status(self):
        return self._next(self.record)

    def start_stream(self):
        self.calls.append("start_stream")

    def start_record(self):
        self.calls.append("start_record")

    def get_scene_list(self):
        return type("R", (), {"scenes": []})()

    def disconnect(self):
        pass


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(obsmod.time, "monotonic", lambda: now["t"])
    monkeypatch.setattr(obsmod.time, "sleep", lambda s: now.__setitem__("t", now["t"] + s))
    return now


@pytest.fixture(autouse=True)
def no_real_obs(monkeypatch):
    """No test in this file may find -- let alone kill -- a real OBS."""
    monkeypatch.setattr(obsmod.psutil, "process_iter", lambda *a, **k: iter(()))
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)
    monkeypatch.setattr(Obs, "_launch", lambda self: None)


def _obs(ws) -> Obs:
    o = Obs(cfg.load())
    o.ws = ws
    return o


# ------------------------------------------------------- the running watchdog

def test_a_frozen_stream_stops_counting_as_streaming(clock):
    """The LIVE watchdog reads is_streaming(). outputActive alone kept it
    satisfied for the whole nine minutes the stream was dead air."""
    o = _obs(_Ws(stream=[_Status(duration=500, nbytes=9000)]))
    assert o.is_streaming()
    clock["t"] += Obs.STALL_AFTER - 1
    assert o.is_streaming(), "declared dead before STALL_AFTER"
    clock["t"] += 2
    assert not o.is_streaming(), "a frozen output still counted as streaming"


def test_a_moving_stream_stays_alive(clock):
    o = _obs(_Ws(stream=[_Status(duration=d, nbytes=d * 10)
                         for d in range(0, 100_000, 1000)]))
    for _ in range(60):
        assert o.is_streaming()
        clock["t"] += 5


def test_paused_and_reconnecting_are_not_frozen(clock):
    """Both stand still by design; neither is a dead encoder."""
    o = _obs(_Ws(stream=[_Status(duration=5, nbytes=5, reconnecting=True)],
                 record=[_Status(duration=5, nbytes=5, paused=True)]))
    for _ in range(3):
        assert o.is_streaming() and o.recording_active()
        clock["t"] += Obs.STALL_AFTER


def test_health_reports_a_frozen_recording_as_stopped(clock):
    """_poll_obs reads health()['recording'] to notice a recording that died."""
    o = _obs(_Ws(stream=[_Status(active=False)],
                 record=[_Status(duration=7, nbytes=70)]))
    assert o.health()["recording"]
    clock["t"] += Obs.STALL_AFTER + 1
    assert not o.health()["recording"]


# --------------------------------------------------------- the start paths

def test_starting_on_a_frozen_stream_restarts_obs(clock, monkeypatch):
    """THE INCIDENT. It used to log 'already streaming - reusing output'."""
    restarted = []
    monkeypatch.setattr(Obs, "_restart_frozen",
                        lambda self, kind: restarted.append(kind))
    frozen = _Status(duration=8_145_699, nbytes=10_364_253_022)
    _obs(_Ws(stream=[frozen])).start()
    assert restarted == ["stream"]


def test_starting_on_a_live_stream_still_adopts_it(clock, monkeypatch):
    """A stream the user started by hand is moving; reuse it, as before."""
    restarted = []
    monkeypatch.setattr(Obs, "_restart_frozen",
                        lambda self, kind: restarted.append(kind))
    ws = _Ws(stream=[_Status(duration=1000, nbytes=10), _Status(duration=4000, nbytes=40)])
    _obs(ws).start()
    assert restarted == [] and "start_stream" not in ws.calls


def test_starting_with_nothing_running_does_not_wait(clock):
    """The usual case: no output active, so no probe and no delay."""
    before = clock["t"]
    ws = _Ws(stream=[_Status(active=False)], record=[_Status(active=False)])
    o = _obs(ws)
    o.start()
    assert o.start_recording() is False
    assert clock["t"] == before
    assert ws.calls == ["start_stream", "start_record"]


def test_a_frozen_recording_is_not_adopted(clock, monkeypatch):
    """start_recording() says whether it adopted an output, so the journal
    does not claim a file that died before the session began."""
    ws = _Ws(record=[_Status(duration=2_724_083, nbytes=39_421_010_281)])

    def restart(self, kind):
        ws.record = [_Status(active=False)]
    monkeypatch.setattr(Obs, "_restart_frozen", restart)
    assert _obs(ws).start_recording() is False
    assert ws.calls == ["start_record"]


def test_an_obs_that_cannot_be_closed_says_what_to_do(monkeypatch):
    """An elevated OBS cannot be killed from an unelevated AutoStream."""
    class Proc:
        info = {"name": "obs64.exe"}

        def kill(self):
            raise obsmod.psutil.AccessDenied()

    monkeypatch.setattr(obsmod.psutil, "process_iter", lambda *a, **k: iter([Proc()]))
    with pytest.raises(ObsUnavailable, match="Restart OBS"):
        _obs(_Ws())._restart_frozen("stream")


def test_an_elevated_obs_that_was_killed_is_relaunched(clock, monkeypatch):
    """Measured: killing an elevated OBS works, but WAITING on it needs a
    handle it will not give, so psutil.wait_procs raised AccessDenied and the
    restart failed with OBS already gone. Gone is judged by name instead."""
    alive = {"obs": True}

    class Proc:
        info = {"name": "obs64.exe"}

        def kill(self):
            alive["obs"] = False

        def wait(self, timeout=None):
            raise obsmod.psutil.AccessDenied()

    monkeypatch.setattr(obsmod.psutil, "process_iter", lambda *a, **k: iter([Proc()]))
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: alive["obs"])
    connected = []
    monkeypatch.setattr(Obs, "connect", lambda self, wait=False: connected.append(wait))
    _obs(_Ws())._restart_frozen("stream")
    assert connected == [True], "OBS was not relaunched"
