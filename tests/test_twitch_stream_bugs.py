"""Four things a Twitch test stream turned up on 2026-10-24, and a fifth.

1. The webcam did not start when AutoStream launched OBS -- OBS's own log:
   "DShow: Run failed (0x800705AA): Insufficient system resources" -- and
   the facecam frame stayed empty until the player re-applied it by hand.
2. A Twitch session uploaded a thumbnail to YouTube, addressed by the Twitch
   channel id (`thumbnails/set?videoId=589697189`, HTTP 500).
3. "No sound from Facecam / Game Capture / Rank Bar" -- three sources that
   never carry sound -- ten times over, re-armed after every quiet gap.
4. 2560x1440 at 9,000 kbps, which Twitch did not play to viewers.
5. "GetReplayBufferStatus returned code 604" as an ERROR with a traceback at
   every session end, with instant replay off.

No OBS, no network, no account: every OBS answer here is a fake websocket.
"""
from __future__ import annotations

import base64
import io
from types import SimpleNamespace as NS

import pytest

import fakes
from autostream import cfg
from autostream import engine as eng_mod
import autostream.obs as obsmod
from autostream.platforms.twitch import Twitch
from autostream.platforms.youtube_platform import YouTubePlatform


@pytest.fixture(autouse=True)
def no_toasts(monkeypatch):
    said = []
    monkeypatch.setattr(eng_mod.notify, "toast", lambda *a, **k: said.append(a))
    return said


def _twitch(eng):
    """The engine follows the config's platform, so both are set."""
    eng.cfg["youtube"] = dict(eng.cfg["youtube"])
    eng.cfg["youtube"]["platform"] = "twitch"
    eng.platform = Twitch(eng.cfg)
    return eng


# ================================================================ 1. webcam

def _png(level: int) -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("L", (64, 36), level).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class CamWs:
    """A websocket with a webcam, a game capture and a browser source."""

    def __init__(self, cams: dict, *, on_air=None):
        # cams: {name: brightness, or None for "OBS refuses the screenshot"}
        self.cams = cams
        self.on_air = set(cams) if on_air is None else set(on_air)
        self.applied = []

    def get_version(self):
        return NS(obs_version="32", rpc_version=1)

    def get_input_list(self):
        inputs = [{"inputName": n, "inputKind": "dshow_input"} for n in self.cams]
        inputs += [{"inputName": "Game Capture", "inputKind": "game_capture"},
                   {"inputName": "Rank Bar", "inputKind": "browser_source"}]
        return NS(inputs=inputs)

    def get_source_active(self, name):
        return NS(video_active=name in self.on_air)

    def get_source_screenshot(self, name, fmt, w, h, q):
        level = self.cams[name]
        if level is None:
            raise RuntimeError("Failed to render screenshot")
        return NS(image_data=_png(level))

    def get_input_settings(self, name):
        return NS(input_settings={"video_device_id": "Lenovo FHD Webcam:..."})

    def set_input_settings(self, name, settings, overlay):
        self.applied.append((name, settings, overlay))


def an_obs(ws) -> obsmod.Obs:
    o = obsmod.Obs(cfg.load())
    o.ws = ws
    return o


def test_a_camera_that_never_opened_reads_as_no_picture():
    """A failed dshow device has no size and OBS refuses to screenshot it;
    that is the same answer as black, not "cannot tell"."""
    o = an_obs(CamWs({"Facecam": None}))
    assert o.camera_pictures() == {"Facecam": False}


def test_a_working_camera_has_a_picture_and_other_sources_are_not_asked():
    o = an_obs(CamWs({"Facecam": 120}))
    assert o.camera_pictures() == {"Facecam": True}


def test_a_camera_not_on_air_is_left_out():
    """The starting card hides the facecam; black there is not a fault."""
    o = an_obs(CamWs({"Facecam": None}, on_air=[]))
    assert o.camera_pictures() == {}


def test_restarting_re_applies_the_sources_own_settings():
    ws = CamWs({"Facecam": None})
    assert an_obs(ws).restart_input("Facecam") is True
    assert ws.applied == [("Facecam", {"video_device_id": "Lenovo FHD Webcam:..."},
                           True)]


class CamObs(fakes.FakeObs):
    def __init__(self, answers):
        super().__init__()
        self.answers = list(answers)      # one camera_pictures answer per look
        self.restarts = []

    def camera_pictures(self, level=6.0):
        return self.answers.pop(0) if self.answers else self._last

    @property
    def _last(self):
        return {"Facecam": False}

    def restart_input(self, name):
        self.restarts.append(name)
        return True


def _look(eng, times):
    """Run the camera check `times` times, each one due."""
    for _ in range(times):
        if eng._camera_next is None:
            break
        eng._camera_next = 0.0
        eng._check_camera()


def test_a_dead_camera_is_restarted_and_the_check_ends_once_it_has_a_picture(caplog):
    import logging

    eng = fakes.engine()
    eng.obs = CamObs([{"Facecam": False}, {"Facecam": True}])
    eng._arm_camera_check()
    with caplog.at_level(logging.INFO):
        _look(eng, 5)
    assert eng.obs.restarts == ["Facecam"]
    assert eng._camera_next is None, "kept looking at a camera that works"
    assert "has a picture after 1 restart" in caplog.text


def test_restarts_are_bounded_and_said_once(no_toasts):
    """NEVER A LOOP. Three restarts, one notice, then left alone."""
    eng = fakes.engine()
    eng.obs = CamObs([])                  # always dead
    eng._arm_camera_check()
    _look(eng, 20)
    assert eng.obs.restarts == ["Facecam"] * eng.CAMERA_TRIES
    assert eng._camera_next is None
    assert sum("no picture from Facecam" in t[0] for t in no_toasts) == 1


def test_a_camera_that_is_fine_from_the_start_is_never_restarted():
    eng = fakes.engine()
    eng.obs = CamObs([{"Facecam": True}])
    eng._arm_camera_check()
    _look(eng, 3)
    assert eng.obs.restarts == []
    assert eng._camera_next is None


def test_no_camera_on_air_yet_keeps_waiting_but_only_for_the_window():
    eng = fakes.engine()
    eng.obs = CamObs([{}] * 50)
    eng._arm_camera_check()
    _look(eng, 3)
    assert eng._camera_next is not None   # the starting card may still be up
    eng._camera_until = 0.0               # the window has passed
    _look(eng, 1)
    assert eng._camera_next is None
    assert eng.obs.restarts == []


def test_going_live_arms_the_check():
    eng = fakes.engine()
    eng._camera_next = None
    eng._arm_camera_check()
    assert eng._camera_next is not None


# ============================================================ 2. thumbnail

def test_twitch_declares_no_thumbnails_and_youtube_does():
    assert Twitch().caps.has_thumbnail is False
    assert Twitch().caps.has_video_tags is False
    yt = YouTubePlatform(cfg.load(), lambda: None)
    assert yt.caps.has_thumbnail is True
    assert yt.caps.has_video_tags is True


class _YT:
    def __init__(self):
        self.thumbs, self.metas = [], []

    def set_thumbnail(self, vid, path):
        self.thumbs.append(vid)

    def set_video_meta(self, vid, tags):
        self.metas.append(vid)


@pytest.fixture
def thumbs(monkeypatch, tmp_path):
    from autostream import thumbnail

    made = []
    pic = tmp_path / "t.jpg"
    pic.write_bytes(b"x")

    def build(*a, **k):
        made.append(1)
        return pic
    monkeypatch.setattr(thumbnail, "build_for_session", build)
    return made


def _thumb_engine(platform):
    eng = fakes.engine()
    eng.cfg["thumbnail"] = dict(eng.cfg["thumbnail"], enabled=True, upload=True)
    eng.yt = _YT()
    eng.state.broadcast_id = "589697189"
    eng.state.current_key = None
    eng._username_for = lambda key: ""
    eng.watcher.active_game = lambda: None
    if platform == "twitch":
        _twitch(eng)
    return eng


def test_a_twitch_session_never_uploads_a_thumbnail_to_youtube(thumbs):
    """THE REPORTED SHAPE: videoId=589697189 is the Twitch channel id."""
    eng = _thumb_engine("twitch")
    eng._set_thumbnail()
    assert eng.yt.thumbs == []
    assert thumbs == [], "composed a thumbnail nothing will use"


def test_a_youtube_session_still_does(thumbs):
    eng = _thumb_engine("youtube")
    eng._set_thumbnail()
    assert eng.yt.thumbs == ["589697189"]


class _Deletes:
    def __init__(self):
        self.deleted = []

    def delete_broadcast(self, bid):
        self.deleted.append(bid)


@pytest.mark.parametrize("platform, deleted", [("twitch", []), ("youtube", ["589697189"])])
def test_a_failed_start_deletes_a_broadcast_only_where_one_was_made(platform, deleted):
    """Same class as the thumbnail: an abandoned Twitch start asked YouTube to
    delete "broadcast" 589697189 -- the Twitch channel id."""
    eng = _thumb_engine(platform)
    eng.yt = _Deletes()
    eng._stop_recording = lambda *a, **k: None
    eng._abandon_start()
    assert eng.yt.deleted == deleted


# ================================================================ 3. sound

def _metered(**heard) -> obsmod.Obs:
    from test_quiet_input import an_obs as quiet_obs

    return quiet_obs(**heard)


def test_sources_that_never_carry_sound_are_not_called_silent():
    """THE REPORTED SHAPE. The facecam, the game capture and the rank bar are
    metered by OBS and had never made a sound; Desktop Audio was loud."""
    o = _metered(**{"Desktop Audio": 1, "Mic": 2, "Facecam": None,
                    "Game Capture": None, "Rank Bar": None})
    assert o.quiet_inputs(300.0) == []


def test_a_microphone_that_never_worked_is_still_named():
    o = _metered(**{"Desktop Audio": 1, "Mic": None, "Facecam": None})
    assert o.quiet_inputs(300.0) == ["Mic"]


def test_a_video_source_that_had_sound_and_lost_it_is_named():
    """A capture card whose audio was carrying the game and then stopped is
    a real fault -- it was heard, so it carries audio."""
    o = _metered(**{"Desktop Audio": 1, "Game Capture": 400})
    assert o.quiet_inputs(300.0) == ["Game Capture"]


def test_an_unknown_kind_is_treated_like_a_webcam():
    o = _metered(**{"Desktop Audio": 1, "Something": None})
    o._audio_kinds_seen = {}
    assert o.quiet_inputs(300.0) == []


def test_a_wholly_quiet_mix_is_cannot_tell_not_all_clear():
    o = _metered(**{"Desktop Audio": 30, "Mic": 30})
    assert o.quiet_inputs(300.0) is None


class _QuietObs:
    def __init__(self):
        self.answers = []

    def silent_for(self):
        return 1.0

    def quiet_inputs(self, floor):
        return self.answers.pop(0)


def test_a_quiet_gap_neither_clears_nor_re_arms_the_warning(no_toasts, caplog):
    """On 2026-10-24 every quiet stretch cleared the warning ("is audible
    again") and the next sound re-armed it: ten pop-ups for one fault."""
    eng = fakes.engine()
    eng._obs_reachable = True
    eng._silent_said = False
    eng._quiet_said = set()
    eng.obs = _QuietObs()
    eng.obs.answers = [["Mic"], None, ["Mic"], None, ["Mic"]]
    for _ in range(5):
        eng._check_audio()
    assert sum("no sound from Mic" in t[0] for t in no_toasts) == 1
    assert "audible again" not in caplog.text
    assert eng._quiet_said == {"Mic"}


# ======================================================= 4. Twitch's ceiling

def test_twitch_declares_1080p_and_6000_kbps_and_youtube_no_ceiling():
    c = Twitch().caps
    assert (c.max_height, c.max_video_kbps) == (1080, 6000)
    y = YouTubePlatform(cfg.load(), lambda: None).caps
    assert (y.max_height, y.max_video_kbps) == (0, 0)


class OutWs:
    """OBS's output settings, as obs-websocket reads and writes them."""

    def __init__(self, mode="Simple", out=(2560, 1440), kbps=9000,
                 rescale="false", rescale_res="", refuse_resize=False):
        self.params = {("Output", "Mode"): mode,
                       ("SimpleOutput", "VBitrate"): str(kbps),
                       ("AdvOut", "Rescale"): rescale,
                       ("AdvOut", "RescaleRes"): rescale_res}
        self.out = out
        self.refuse_resize = refuse_resize
        self.resized = []

    def get_version(self):
        return NS(obs_version="32", rpc_version=1)

    def get_profile_parameter(self, section, key):
        return NS(parameter_value=self.params.get((section, key)))

    def set_profile_parameter(self, section, key, value):
        self.params[(section, key)] = value

    def get_video_settings(self):
        return NS(fps_numerator=60, fps_denominator=1, base_width=2560,
                  base_height=1440, output_width=self.out[0],
                  output_height=self.out[1])

    def set_video_settings(self, num, den, bw, bh, ow, oh):
        if self.refuse_resize:
            raise RuntimeError("an output is active")
        self.resized.append((ow, oh))
        self.out = (ow, oh)


def test_simple_mode_is_capped_and_put_back_exactly():
    ws = OutWs()
    o = an_obs(ws)
    saved = o.cap_stream_output(1080, 6000)
    assert ws.out == (1920, 1080)
    assert ws.params[("SimpleOutput", "VBitrate")] == "6000"
    assert o.restore_stream_output(saved) == {}
    assert ws.out == (2560, 1440)
    assert ws.params[("SimpleOutput", "VBitrate")] == "9000"


def test_under_the_ceiling_nothing_is_written():
    ws = OutWs(out=(1920, 1080), kbps=4500)
    assert an_obs(ws).cap_stream_output(1080, 6000) == {}
    assert ws.resized == []
    assert ws.params[("SimpleOutput", "VBitrate")] == "4500"


def test_no_ceiling_touches_nothing():
    ws = OutWs()
    assert an_obs(ws).cap_stream_output(0, 0) == {}
    assert ws.out == (2560, 1440)


def test_advanced_mode_rescales_the_stream_alone():
    ws = OutWs(mode="Advanced")
    o = an_obs(ws)
    saved = o.cap_stream_output(1080, 6000)
    assert ws.params[("AdvOut", "Rescale")] == "true"
    assert ws.params[("AdvOut", "RescaleRes")] == "1920x1080"
    assert ws.resized == [], "the canvas -- and so the recording -- was resized"
    o.restore_stream_output(saved)
    assert ws.params[("AdvOut", "Rescale")] == "false"


def test_a_refused_resize_still_caps_the_bitrate_and_says_so(caplog):
    ws = OutWs(refuse_resize=True)
    saved = an_obs(ws).cap_stream_output(1080, 6000)
    assert ws.params[("SimpleOutput", "VBitrate")] == "6000"
    assert saved == {"mode": "Simple", "kbps": 9000}
    assert "could not lower the stream to 1080p" in caplog.text


def test_what_cannot_be_put_back_yet_is_handed_back():
    ws = OutWs()
    o = an_obs(ws)
    saved = o.cap_stream_output(1080, 6000)
    ws.refuse_resize = True               # the outputs are still closing
    left = o.restore_stream_output(saved)
    assert left == {"mode": "Simple", "output": [2560, 1440]}
    assert ws.params[("SimpleOutput", "VBitrate")] == "9000"
    ws.refuse_resize = False
    assert o.restore_stream_output(left) == {}
    assert ws.out == (2560, 1440)


class LimitObs(fakes.FakeObs):
    def __init__(self, cap_answer=None, restore_answer=None):
        super().__init__()
        self.caps_asked, self.restored = [], []
        self.cap_answer = cap_answer or {}
        self.restore_answer = restore_answer or {}

    def cap_stream_output(self, max_height=0, max_kbps=0):
        self.caps_asked.append((max_height, max_kbps))
        return dict(self.cap_answer)

    def restore_stream_output(self, saved):
        self.restored.append(dict(saved))
        return dict(self.restore_answer)


SAVED = {"mode": "Simple", "kbps": 9000, "output": [2560, 1440]}


def test_a_twitch_session_caps_obs_and_remembers_what_it_changed():
    eng = _twitch(fakes.engine())
    eng.obs = LimitObs(cap_answer=SAVED)
    eng._apply_stream_limits()
    assert eng.obs.caps_asked == [(1080, 6000)]
    assert eng.state.output_restore == SAVED


def test_a_youtube_session_is_unchanged():
    eng = fakes.engine()
    eng.obs = LimitObs(cap_answer=SAVED)
    eng._apply_stream_limits()
    assert eng.obs.caps_asked == []
    assert eng.obs.restored == []


def test_a_youtube_session_after_a_crashed_twitch_one_puts_obs_back():
    """On disk, so a crash mid-Twitch does not leave YouTube at 1080p."""
    eng = fakes.engine()
    eng.state.output_restore = dict(SAVED)
    eng.obs = LimitObs()
    eng._apply_stream_limits()
    assert eng.obs.restored == [SAVED]
    assert eng.state.output_restore == {}


def test_a_second_twitch_session_keeps_the_players_own_values():
    """Today's reading may be the last session's cap; the stored value is
    what the player had before any of it."""
    eng = _twitch(fakes.engine())
    eng.state.output_restore = dict(SAVED)
    eng.obs = LimitObs(cap_answer={"mode": "Simple", "kbps": 7000})
    eng._apply_stream_limits()
    assert eng.state.output_restore["kbps"] == 9000


def test_the_session_end_puts_obs_back_and_idle_retries_what_is_left(monkeypatch):
    eng = _twitch(fakes.engine())
    eng.state.output_restore = dict(SAVED)
    eng.obs = LimitObs(restore_answer={"mode": "Simple", "output": [2560, 1440]})
    eng._restore_stream_limits()
    assert eng.state.output_restore == {"mode": "Simple", "output": [2560, 1440]}
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: True)
    eng.obs.restore_answer = {}
    eng._restore_tried = 0.0
    eng.RESTORE_EVERY = 0.0
    eng._retry_stream_restore()
    assert eng.state.output_restore == {}


def test_idle_does_not_knock_on_a_closed_obs(monkeypatch):
    eng = fakes.engine()
    eng.state.output_restore = dict(SAVED)
    eng.obs = LimitObs()
    monkeypatch.setattr(obsmod, "_obs_process_alive", lambda: False)
    eng._restore_tried = -1e9
    eng._retry_stream_restore()
    assert eng.obs.restored == []


def test_output_restore_survives_the_session_reset():
    from autostream.state import State

    s = State()
    s.output_restore = dict(SAVED)
    s.reset_session()
    assert s.output_restore == SAVED


# ====================================================== 5. replay buffer 604

class _ReplayObs(fakes.FakeObs):
    def __init__(self):
        super().__init__()
        self.stops = 0

    def set_replay_seconds(self, n):
        pass

    def start_replay_buffer(self):
        return False

    def stop_replay_buffer(self):
        self.stops += 1


def _replay(eng, on):
    eng.cfg["record"] = dict(eng.cfg["record"])
    eng.cfg["record"]["replay_enabled"] = on


def test_with_instant_replay_off_obs_is_not_asked_about_the_buffer():
    eng = fakes.engine()
    eng.obs = _ReplayObs()
    eng.replays = []
    _replay(eng, False)
    eng._start_replay_buffer()
    eng._stop_replay_buffer()
    assert eng.obs.stops == 0


def test_a_buffer_the_session_started_is_still_stopped():
    eng = fakes.engine()
    eng.obs = _ReplayObs()
    eng.replays = []
    _replay(eng, True)
    eng._start_replay_buffer()
    eng._stop_replay_buffer()
    assert eng.obs.stops == 1


def test_a_604_is_not_logged_as_an_error(caplog):
    """obsws-python logs every refused request at ERROR before raising it."""
    import logging

    class Ws:
        def get_version(self):
            return NS()

        def get_replay_buffer_status(self):
            logging.getLogger("obsws_python.reqs.ReqClient").error(
                "OBSSDKRequestError: code 604")
            raise RuntimeError("604")

    o = an_obs(Ws())
    with caplog.at_level(logging.DEBUG):
        assert o.replay_active() is False
    assert "604" not in caplog.text
