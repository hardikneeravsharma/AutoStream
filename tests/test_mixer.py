"""The dashboard's audio card: which microphone, and how loud against the game.

Driven against a fake obs-websocket client, since the suite never talks to a
real OBS. What matters is the contract the page leans on: the reading names
the mic device and both faders, a missing source is None rather than an
error, an unplugged headset stays visible, and a write is read back so the
page shows what OBS holds rather than what was asked for.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import cfg                                       # noqa: E402
import autostream.obs as obsmod                                  # noqa: E402


class FakeWs:
    """The handful of obs-websocket requests the mixer makes."""

    def __init__(self, mic=True, desktop=True, device="default"):
        self.inputs = []
        if desktop:
            self.inputs.append({"inputName": "Desktop Audio",
                                "inputKind": "wasapi_output_capture"})
        if mic:
            self.inputs.append({"inputName": "Mic/Aux",
                                "inputKind": "wasapi_input_capture"})
        self.inputs.append({"inputName": "Game", "inputKind": "game_capture"})
        self.db = {"Desktop Audio": -6.0, "Mic/Aux": 0.0}
        self.muted = {"Desktop Audio": False, "Mic/Aux": False}
        self.device = device
        self.devices = [("default", "Default"), ("{usb}", "USB Headset"),
                        ("{cam}", "Webcam Mic")]
        self.closed = False

    def get_input_list(self, kind=None):
        return SimpleNamespace(inputs=self.inputs)

    def get_input_volume(self, name):
        return SimpleNamespace(input_volume_db=self.db[name],
                               input_volume_mul=1.0)

    def set_input_volume(self, name, vol_mul=None, vol_db=None):
        self.db[name] = vol_db

    def get_input_mute(self, name):
        return SimpleNamespace(input_muted=self.muted[name])

    def set_input_mute(self, name, muted):
        self.muted[name] = muted

    def get_input_settings(self, name):
        return SimpleNamespace(input_settings=(
            {} if self.device == "default" else {"device_id": self.device}))

    def set_input_settings(self, name, settings, overlay):
        self.device = settings["device_id"]

    def get_input_properties_list_property_items(self, name, prop):
        return SimpleNamespace(property_items=[
            {"itemName": n, "itemValue": v, "itemEnabled": True}
            for v, n in self.devices])

    def disconnect(self):
        self.closed = True


def an_obs(ws):
    o = obsmod.Obs(cfg.load())
    o._side = lambda: ws
    return o


def test_the_reading_names_the_device_and_both_faders():
    ws = FakeWs()
    r = an_obs(ws).audio_mixer()
    assert r["ok"]
    assert r["mic"]["name"] == "Mic/Aux"
    assert r["mic"]["device"] == "default"      # absent from settings = default
    assert [d["id"] for d in r["mic"]["devices"]] == ["default", "{usb}", "{cam}"]
    assert r["desktop"] == {"name": "Desktop Audio", "db": -6.0, "muted": False}


class CountingObs(obsmod.Obs):
    """Counts handshakes, since OBS toasts every client that comes and goes."""

    def __init__(self, make):
        super().__init__(cfg.load())
        self.make, self.opened = make, []

    def _connect(self, timeout=5):
        ws = self.make()
        self.opened.append(ws)
        return ws


def test_the_dashboard_reuses_one_connection(monkeypatch):
    """Reading every 15s from each open tab used to connect and disconnect
    each time, and OBS flashed a notification for every one."""
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)
    monkeypatch.setattr(obsmod, "obsws", object())
    monkeypatch.setattr(FakeWs, "get_version",
                        lambda self: SimpleNamespace(obs_version="30"), raising=False)
    o = CountingObs(FakeWs)
    for _ in range(5):
        assert o.audio_mixer()["ok"]
    assert o.set_audio({"mic_db": -3})["ok"]
    assert len(o.opened) == 1 and not o.opened[0].closed


def test_a_dead_dashboard_connection_is_replaced(monkeypatch):
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)
    monkeypatch.setattr(obsmod, "obsws", object())
    monkeypatch.setattr(FakeWs, "get_version",
                        lambda self: SimpleNamespace(obs_version="30"), raising=False)
    o = CountingObs(FakeWs)
    o.audio_mixer()

    def gone(self):
        raise ConnectionError("OBS restarted")
    o.opened[0].get_version = gone.__get__(o.opened[0])
    assert o.audio_mixer()["ok"]
    assert len(o.opened) == 2 and o.opened[0].closed


def test_a_missing_source_is_none_not_an_error():
    r = an_obs(FakeWs(mic=False)).audio_mixer()
    assert r["ok"] and r["mic"] is None and r["desktop"]


def test_an_unplugged_headset_stays_visible():
    """OBS keeps pointing at a device that is gone, and that is the usual
    reason a mic goes quiet -- so it must not be shown as some other device."""
    r = an_obs(FakeWs(device="{gone}")).audio_mixer()
    assert r["mic"]["device"] == "{gone}"
    assert r["mic"]["devices"][-1] == {"id": "{gone}", "name": "Not connected - pick another",
                                       "missing": True}


def test_a_fader_pulled_right_down_reads_as_the_floor():
    ws = FakeWs()
    ws.db["Mic/Aux"] = None                      # -inf arrives as null
    assert an_obs(ws).audio_mixer()["mic"]["db"] == obsmod.Obs.MIXER_MIN_DB


def test_changes_are_applied_and_read_back():
    ws = FakeWs()
    r = an_obs(ws).set_audio({"mic_device": "{usb}", "mic_db": -3.5,
                              "desktop_db": -12, "desktop_muted": True})
    assert r["ok"]
    assert ws.device == "{usb}" and r["mic"]["device"] == "{usb}"
    assert r["mic"]["db"] == -3.5 and r["desktop"]["db"] == -12.0
    assert r["desktop"]["muted"] is True


def test_a_volume_is_held_inside_the_fader():
    ws = FakeWs()
    an_obs(ws).set_audio({"mic_db": 20, "desktop_db": -500})
    assert ws.db == {"Mic/Aux": 0.0, "Desktop Audio": -60.0}


def test_an_unknown_device_is_refused():
    ws = FakeWs()
    r = an_obs(ws).set_audio({"mic_device": "{nope}"})
    assert not r["ok"] and ws.device == "default"


def test_a_change_to_a_source_obs_lacks_says_so():
    r = an_obs(FakeWs(mic=False)).set_audio({"mic_db": -3})
    assert not r["ok"] and "microphone" in r["error"]


def test_obs_not_running_is_an_answer_not_a_crash():
    o = obsmod.Obs(cfg.load())

    def down():
        raise obsmod.ObsUnavailable("OBS is not running.")
    o._side = down
    assert o.audio_mixer() == {"ok": False, "error": "OBS is not running."}
    assert o.set_audio({"mic_db": 0})["ok"] is False


def test_the_route_reaches_the_mixer():
    from fakes import FakeEngine, LiveServer

    eng = FakeEngine()
    ws = FakeWs()
    eng.obs = an_obs(ws)
    srv = LiveServer(engine=eng)
    try:
        assert srv.get("/api/audio").json()["mic"]["name"] == "Mic/Aux"
        r = srv.post("/api/audio/set", {"mic_db": -9}).json()
        assert r["ok"] and ws.db["Mic/Aux"] == -9.0
    finally:
        srv.close()
