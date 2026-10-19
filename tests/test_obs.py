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


# ------------------------------------------------- audio tracks

class _FakeWs:
    """Enough of obs-websocket to exercise the track split."""

    def __init__(self, tracks=None):
        self.inputs = [
            {"inputName": "Mic", "inputKind": "wasapi_input_capture"},
            {"inputName": "Desktop Audio", "inputKind": "wasapi_output_capture"},
            {"inputName": "Game Capture", "inputKind": "game_capture"},
        ]
        all_on = {str(i): True for i in range(1, 7)}
        self.tracks = tracks or {"Mic": dict(all_on),
                                 "Desktop Audio": dict(all_on)}
        self.writes = []

    def get_version(self):
        return type("V", (), {"obs_version": "30", "rpc_version": 1})()

    def get_input_list(self):
        return type("R", (), {"inputs": self.inputs})()

    def get_input_audio_tracks(self, name):
        return type("R", (), {"input_audio_tracks": self.tracks[name]})()

    def set_input_audio_tracks(self, name, want):
        self.writes.append((name, want))
        self.tracks[name] = dict(want)


def _obs_with(ws):
    o = an_obs()
    o.ws = ws
    return o


def test_the_mic_and_the_game_get_their_own_tracks():
    """OBS ships both inputs on all six tracks, which makes a three-track
    recording the same mix three times over -- and the one thing that could
    rescue a quiet mic afterwards is then not in the file."""
    ws = _FakeWs()
    _obs_with(ws).split_audio_tracks()

    assert ws.tracks["Mic"]["2"] is True and ws.tracks["Mic"]["3"] is False
    assert ws.tracks["Desktop Audio"]["3"] is True
    assert ws.tracks["Desktop Audio"]["2"] is False
    # Track 1 stays the mix, which is what every player and the clipper read.
    assert ws.tracks["Mic"]["1"] is True and ws.tracks["Desktop Audio"]["1"] is True


def test_nothing_is_written_when_the_tracks_are_already_right():
    """It runs at the start of every session, so the usual case is a read."""
    ws = _FakeWs()
    _obs_with(ws).split_audio_tracks()
    ws.writes.clear()

    _obs_with(ws).split_audio_tracks()
    assert ws.writes == []


def test_a_source_that_is_not_audio_is_left_alone():
    ws = _FakeWs()
    _obs_with(ws).split_audio_tracks()
    assert all(name != "Game Capture" for name, _ in ws.writes)


def test_the_split_never_raises(monkeypatch):
    """It runs inside the session start; a failure here must not stop it."""
    class Boom(_FakeWs):
        def get_input_list(self):
            raise OSError("obs went away")

    _obs_with(Boom()).split_audio_tracks()      # no exception


# ------------------------------------------- screens: a page becomes a file

class _ScreensWs:
    """obs-websocket as the screen savers see it, with OBS 32's habit that was
    the whole bug: RemoveInput answers at once, but the source -- name and
    all -- stays for as long as a scene item still holds it (measured: still
    there ten seconds later). Taking its last item out is what releases it."""

    def __init__(self, inputs=None, items=()):
        self.scenes = {"AutoStream Starting", "Gaming"}
        self.inputs = dict(inputs or {})          # name -> {"kind", "settings"}
        self.items = {}                           # (scene, name) -> id
        self.removed = set()                      # asked to go, still held
        self.calls = []
        for scene, name in items:
            self._add_item(scene, name)

    def _add_item(self, scene, name):
        self.items[(scene, name)] = len(self.items) + 100

    def get_version(self):
        return type("V", (), {"obs_version": "32", "rpc_version": 1})()

    def get_scene_list(self):
        return type("R", (), {"scenes": [{"sceneName": s} for s in sorted(self.scenes)]})()

    def create_scene(self, name):
        self.scenes.add(name)

    def get_input_list(self):
        return type("R", (), {"inputs": [{"inputName": n, "inputKind": v["kind"]}
                                         for n, v in self.inputs.items()]})()

    def get_scene_item_list(self, scene):
        return type("R", (), {"scene_items": [{"sourceName": n, "sceneItemId": i}
                                              for (s, n), i in self.items.items() if s == scene]})()

    def remove_scene_item(self, scene, item):
        name = next(n for (s, n), i in self.items.items() if s == scene and i == item)
        self.calls.append(("unplace", scene, name))
        del self.items[(scene, name)]
        if not any(n == name for (_, n) in self.items):
            self.inputs.pop(name, None)           # its last holder went: released
            self.removed.discard(name)

    def set_input_name(self, name, new):
        assert new not in self.inputs, "OBS refuses a name that is in use"
        self.calls.append(("rename", name, new))
        self.inputs[new] = self.inputs.pop(name)
        for key in [k for k in self.items if k[1] == name]:
            self.items[(key[0], new)] = self.items.pop(key)

    def remove_input(self, name):
        if name not in self.inputs:
            raise RuntimeError("No source was found by the name of " + name)
        self.calls.append(("remove", name))
        if any(n == name for (_, n) in self.items):
            self.removed.add(name)                # ...and it stays
        else:
            self.inputs.pop(name)

    def set_input_settings(self, name, settings, overlay):
        self.calls.append(("settings", name, self.inputs[name]["kind"]))
        self.inputs[name]["settings"].update(settings)

    def create_input(self, scene, name, kind, settings, enabled):
        assert name not in self.inputs, "OBS refuses a name that is in use"
        self.calls.append(("create", name, kind))
        self.inputs[name] = {"kind": kind, "settings": dict(settings)}
        self._add_item(scene, name)

    def get_video_settings(self):
        return type("R", (), {"base_width": 2560, "base_height": 1440})()

    def get_scene_item_id(self, scene, name):
        return type("R", (), {"scene_item_id": self.items[(scene, name)]})()

    def set_scene_item_transform(self, scene, item, transform):
        self.calls.append(("fit", scene))

    def live(self, name):
        """The source a viewer would see under this name, if any."""
        return None if name in self.removed else self.inputs.get(name)


SCENE, SOURCE = "AutoStream Starting", "AutoStream Starting media"


def _page_screen(also_in=()):
    return _ScreensWs({SOURCE: {"kind": "browser_source",
                                "settings": {"url": "https://overlay.example/start"}}},
                      items=[(SCENE, SOURCE)] + [(s, SOURCE) for s in also_in])


def test_a_screen_moved_from_a_page_to_a_file_shows_the_file(no_sleep):
    """The reported bug: Settings said starting_file was an MP4, OBS kept the
    old overlay page, and the build said it had worked. A browser source given
    a local_file is still a browser source."""
    ws = _page_screen()
    assert _obs_with(ws).ensure_media_scene(SCENE, SOURCE, r"C:\screens\start.mp4")

    now = ws.live(SOURCE)
    assert now["kind"] == "ffmpeg_source"
    assert now["settings"]["local_file"] == r"C:\screens\start.mp4"
    assert ("fit", SCENE) in ws.calls, "the new source was not fitted to the canvas"
    assert not any(c[0] == "settings" and c[2] == "browser_source" for c in ws.calls), \
        "a file's settings were written onto the browser source"
    assert no_sleep == [], "the engine tick waited on OBS"


def test_the_old_page_is_really_gone():
    """RemoveInput on its own left the page in OBS -- and in the scene -- with
    the name still taken. Renamed, taken out of its scenes, then removed, it
    is released at once and nothing named '(replaced ...)' stays behind."""
    ws = _page_screen()
    _obs_with(ws).ensure_media_scene(SCENE, SOURCE, "start.mp4")
    assert [n for n in ws.inputs if "replaced" in n] == []
    assert [n for (_, n) in ws.items] == [SOURCE]
    order = [c[0] for c in ws.calls]
    assert order.index("rename") < order.index("unplace") < order.index("create")


def test_the_old_page_leaves_every_scene_it_was_put_in():
    """A user who also dropped the card into their own scene must not keep a
    stale '(replaced 1)' page there."""
    ws = _page_screen(also_in=["Gaming"])
    _obs_with(ws).ensure_media_scene(SCENE, SOURCE, "start.mp4")
    assert ("Gaming", SOURCE + " (replaced 1)") not in ws.items
    assert [n for n in ws.inputs if "replaced" in n] == []


def test_switching_back_and_forth_leaves_nothing_behind():
    ws = _page_screen()
    o = _obs_with(ws)
    assert o.ensure_media_scene(SCENE, SOURCE, "start.mp4")
    assert o.ensure_browser_scene(SCENE, SOURCE, "https://overlay.example/start")
    assert ws.live(SOURCE)["kind"] == "browser_source"
    assert sorted(ws.inputs) == [SOURCE]


def test_and_back_from_a_file_to_a_page():
    ws = _ScreensWs({SOURCE: {"kind": "ffmpeg_source", "settings": {"local_file": "a.mp4"}}},
                    items=[(SCENE, SOURCE)])
    assert _obs_with(ws).ensure_browser_scene(SCENE, SOURCE, "https://overlay.example/start")
    assert ws.live(SOURCE)["kind"] == "browser_source"
    assert ws.live(SOURCE)["settings"]["url"] == "https://overlay.example/start"


def test_a_new_file_of_the_same_kind_is_still_an_edit_in_place():
    """Kept on purpose: the source may have been moved or filtered by hand,
    and changing the file must not throw that away."""
    ws = _ScreensWs({SOURCE: {"kind": "ffmpeg_source", "settings": {"local_file": "old.mp4"}}},
                    items=[(SCENE, SOURCE)])
    assert _obs_with(ws).ensure_media_scene(SCENE, SOURCE, "new.mp4")
    assert [c[0] for c in ws.calls] == ["settings"]
    assert ws.live(SOURCE)["settings"]["local_file"] == "new.mp4"


def test_a_page_no_scene_held_is_removed_outright():
    """Taking items out releases a held source; one that sat in no scene has
    nothing to release it, so that one is asked to go directly."""
    ws = _ScreensWs({SOURCE: {"kind": "browser_source", "settings": {}}})
    assert _obs_with(ws).ensure_media_scene(SCENE, SOURCE, "start.mp4")
    assert ("remove", SOURCE + " (replaced 1)") in ws.calls
    assert sorted(ws.inputs) == [SOURCE]
