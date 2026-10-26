"""What OBS is showing while it records: the game, never one of our cards.

A recording-only session on 2026-10-26 wrote an hour and twelve minutes of the
"Stream ended" card instead of a Valorant match. The previous night's stream
had ended on that card, and nothing put the game back afterwards: a broadcast
picks its scene in obs.start(), but with streaming off start() is never called,
so the recording began on whatever OBS was last showing. The log said
"OBS StartRecord issued" and nothing about a scene at all.

Every way into a recording is a row here, with the scene OBS is on at the
moment the recording starts and while it runs. The cards -- starting, be right
back, ending -- belong on a broadcast somebody is watching, and only for as long
as AutoStream is holding them up. Anywhere else they are a lost recording.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

from autostream import cfg as cfgmod
from autostream.gameindex import GameHit
from autostream.state import COOLDOWN, IDLE, LIVE, STOPPING

from fakes import FakeObs, FakeYouTube, a_game, clips_only, engine

ENDING = "AutoStream Ending"
STARTING = "AutoStream Starting"
BRB = "AutoStream Be Right Back"
CARDS = {ENDING, STARTING, BRB}

VALORANT = GameHit(key="valorant-win64-shipping.exe", name="VALORANT",
                   source="t")


def _cfg(tmp_path, default_scene="Scene", **files):
    """The user's own setup: a default scene, and the cards they configured."""
    raw = cfgmod.load()
    data = {k: (dict(v) if isinstance(v, dict) else v) for k, v in raw.items()}
    data["obs"] = dict(data["obs"], default_scene=default_scene)
    data["screens"] = dict(data["screens"], enabled=True,
                           starting_file="", paused_file="", ending_file="")
    for which, name in files.items():
        card = tmp_path / name
        card.write_bytes(b"a file")
        data["screens"][f"{which}_file"] = str(card)
    data["rules"] = dict(data["rules"], quiet_hours=[], require_ac_power=False)
    # Set here, not taken from whatever config the machine has: the example
    # config ships with recording off, and the Record button then does nothing.
    data["record"] = dict(data["record"], enabled=True)
    return cfgmod.Config(data)


def _obs_left_on(scene: str) -> FakeObs:
    """OBS as the last session left it."""
    obs = FakeObs(recording=False)
    obs.scenes = ["Scene", "Valorant", STARTING, BRB, ENDING]
    obs.scene = scene
    return obs


def _recorder(eng) -> list:
    """Stand in for _start_recording, noting what was on screen when it ran."""
    began_on: list = []

    def start():
        began_on.append(eng.obs.scene)
        eng.obs.recording = True
        eng.state.recording = True
    eng._start_recording = start            # type: ignore[method-assign]
    return began_on


def _recording_only(tmp_path, left_on=ENDING, **kw):
    eng = clips_only()
    eng.cfg = _cfg(tmp_path, **kw)
    eng.obs = _obs_left_on(left_on)
    eng.watcher.active_game = lambda: VALORANT     # type: ignore[method-assign]
    return eng, _recorder(eng)


class _Platform:
    """Just enough of a platform for a broadcast to begin and end."""

    caps = SimpleNamespace(has_video_tags=False)

    def __init__(self):
        self.stopped = 0

    def preflight(self, cost):
        pass

    def start(self, title, desc, privacy="public", category=None):
        return SimpleNamespace(handle="b1", stream_key="", ingest_server="",
                               watch_url="https://example.invalid/b1")

    def stop(self, session):
        self.stopped += 1


def _streaming(tmp_path, left_on=ENDING, **kw):
    eng = engine(running=a_game())
    eng.streaming = True
    eng.cfg = _cfg(tmp_path, **kw)
    eng.obs = _obs_left_on(left_on)
    eng.obs.default_scene = eng.cfg.obs.default_scene or None
    eng.platform = _Platform()
    eng._apply_stream_limits = lambda: None        # type: ignore[method-assign]
    eng._restore_stream_limits = lambda: None      # type: ignore[method-assign]
    eng._journal = lambda path=None: None          # type: ignore[method-assign]
    eng.watcher.active_game = lambda: VALORANT     # type: ignore[method-assign]
    return eng, _recorder(eng)


# ------------------------------------------------- starting a recording


def test_the_incident_a_recording_only_session_after_a_stream_ended(tmp_path):
    """The reported session, exactly: OBS still on the ending card from the
    night before, streaming off, a Valorant match about to be recorded."""
    eng, began_on = _recording_only(tmp_path, left_on=ENDING,
                                    ending="e.mp4")
    eng._begin_session(VALORANT)
    assert eng.state.phase == LIVE
    assert began_on == ["Scene"], f"recorded {began_on} instead of the game"
    assert eng.obs.scene == "Scene"


def test_a_recording_only_session_left_on_the_be_right_back_card(tmp_path):
    eng, began_on = _recording_only(tmp_path, left_on=BRB, paused="b.mp4")
    eng._begin_session(VALORANT)
    assert began_on == ["Scene"]


def test_a_recording_only_session_uses_the_games_own_scene(tmp_path):
    eng, began_on = _recording_only(tmp_path)
    hit = GameHit(key=VALORANT.key, name="VALORANT", scene="Valorant",
                  source="t")
    eng._begin_session(hit)
    assert began_on == ["Valorant"]


def test_with_no_scene_configured_any_scene_of_the_users_beats_a_card(
        tmp_path):
    """A stranger who never set obs.default_scene. OBS's own first scene is
    a guess; the ending card is a certainty of the wrong thing."""
    eng, began_on = _recording_only(tmp_path, default_scene="")
    eng.obs.scenes = [ENDING, "My Game", STARTING]
    eng._begin_session(VALORANT)
    assert began_on == ["My Game"]


def test_a_recording_only_session_does_not_record_the_starting_card(tmp_path):
    """Nobody is watching a recording start. The card would be the first
    fifteen seconds of every file the clips are cut from."""
    eng, began_on = _recording_only(tmp_path, starting="s.mp4")
    eng._begin_session(VALORANT)
    assert began_on == ["Scene"]
    assert eng.obs.scene == "Scene"
    assert eng._screen_until is None


def test_a_recording_only_session_already_on_the_game_stays_there(tmp_path):
    eng, began_on = _recording_only(tmp_path, left_on="Scene")
    eng._begin_session(VALORANT)
    assert began_on == ["Scene"]


def test_a_stream_and_recording_after_a_stream_ended(tmp_path):
    """With streaming on, obs.start() picks the scene before StartRecord --
    the path that always worked, kept working."""
    eng, began_on = _streaming(tmp_path, left_on=ENDING, ending="e.mp4")
    eng._begin_session(VALORANT)
    assert eng.obs.started == 1
    assert began_on == ["Scene"]


def test_a_stream_opens_on_its_starting_card(tmp_path):
    """The one place a card belongs at the start: a broadcast, held by a
    deadline, with the game after it."""
    eng, began_on = _streaming(tmp_path, left_on=ENDING, starting="s.mp4")
    eng._begin_session(VALORANT)
    assert began_on == [STARTING]
    assert ENDING not in began_on


def test_record_pressed_on_the_idle_dashboard_takes_the_game(tmp_path):
    eng, began_on = _recording_only(tmp_path, left_on=ENDING)
    eng.toggle_recording("record button")
    assert began_on == ["Scene"]


def test_a_blocked_start_records_nothing(tmp_path):
    """start_blocked: three failures, then nothing starts until Resume."""
    eng, began_on = _recording_only(tmp_path, left_on=ENDING)
    eng._start_blocked = True
    eng.state.phase = "ARMING"
    eng.watcher.armed_game = lambda: VALORANT          # type: ignore[method-assign]
    eng.watcher.any_game_running = lambda: True        # type: ignore[method-assign]
    eng._intent_for = lambda hit: None                 # type: ignore[method-assign]
    eng._tick_arming()
    assert eng.state.phase == IDLE
    assert began_on == []


# ---------------------------------------------- while it is recording


def _live(eng):
    eng.state.phase = LIVE
    eng.state.current_key = VALORANT.key
    eng.state.session_start = time.time()
    eng.state.recording = True
    eng.obs.recording = True
    eng._check_picture = lambda: None              # type: ignore[method-assign]
    eng._check_camera = lambda: None               # type: ignore[method-assign]
    eng._check_audio = lambda: None                # type: ignore[method-assign]
    eng._poll_obs = lambda: None                   # type: ignore[method-assign]
    eng._check_disk = lambda: None                 # type: ignore[method-assign]
    eng._poll_live_extras = lambda: None           # type: ignore[method-assign]
    eng._scene_checked = 0.0


def test_a_card_that_appears_mid_recording_is_taken_off(tmp_path):
    """OBS restarted mid-session, or a scene clicked by mistake: the next
    check puts the game back rather than recording the card for an hour."""
    eng, _ = _recording_only(tmp_path, left_on="Scene")
    _live(eng)
    eng.obs.scene = ENDING
    eng._tick_live()
    assert eng.obs.scene == "Scene"


def test_obs_reconnecting_on_the_ending_card_is_corrected(tmp_path):
    eng, _ = _recording_only(tmp_path, left_on="Scene")
    _live(eng)
    eng.obs.reachable = False
    eng.obs.scene = ENDING                 # what a restarted OBS reopened on
    eng.obs.reachable = True
    eng._tick_live()
    assert eng.obs.scene == "Scene"


def test_the_ending_card_on_a_live_broadcast_is_taken_off(tmp_path):
    eng, _ = _streaming(tmp_path, left_on="Scene")
    _live(eng)
    eng.obs.streaming = True
    eng.obs.scene = ENDING
    eng._tick_live()
    assert eng.obs.scene == "Scene"


def test_the_be_right_back_card_is_left_alone_while_paused(tmp_path):
    eng, _ = _streaming(tmp_path, left_on=BRB, paused="b.mp4")
    _live(eng)
    eng.obs.streaming = True
    eng.state.paused = True
    eng._tick_live()
    assert eng.obs.scene == BRB


def test_the_starting_card_is_left_alone_while_it_is_due(tmp_path):
    eng, _ = _streaming(tmp_path, left_on=STARTING, starting="s.mp4")
    _live(eng)
    eng.obs.streaming = True
    eng._screen_until = time.monotonic() + 60
    eng._tick_live()
    assert eng.obs.scene == STARTING


def test_a_scene_of_the_users_own_is_never_touched(tmp_path):
    """Only AutoStream's own cards are taken off. A scene the player chose
    is theirs, whatever it shows."""
    eng, _ = _recording_only(tmp_path, left_on="Just Chatting")
    _live(eng)
    eng._tick_live()
    assert eng.obs.scene == "Just Chatting"


def test_the_game_closed_and_reopened_during_a_recording(tmp_path):
    eng, _ = _recording_only(tmp_path, left_on="Scene")
    _live(eng)
    eng.watcher.active_game = lambda: None         # type: ignore[method-assign]
    eng._tick_live()
    assert eng.state.phase == COOLDOWN
    eng.watcher.active_game = lambda: VALORANT     # type: ignore[method-assign]
    eng._tick_cooldown()
    assert eng.state.phase == LIVE
    eng._tick_live()
    assert eng.obs.scene == "Scene"
    assert eng.state.recording


# ------------------------------------------------- ending a session


def test_a_stream_that_ends_on_its_card_does_not_leave_obs_there(tmp_path):
    """The root of the incident: the ending card stayed up after the
    broadcast it was for had gone, waiting for the next recording."""
    eng, _ = _streaming(tmp_path, left_on="Scene", ending="e.mp4")
    eng.state.phase = STOPPING
    eng.state.broadcast_id = "b1"
    eng.session = eng.platform.start("t", "d")
    eng.state.recording = True
    eng._stop_recording = lambda: None             # type: ignore[method-assign]
    eng._tick_stopping()
    assert eng.obs.scene == ENDING                 # the card, while it is due
    eng._ending_until = time.monotonic() - 0.1
    eng._tick_stopping()
    assert eng.state.phase == IDLE
    assert eng.obs.scene == "Scene"


def test_a_recording_only_session_ends_without_a_card(tmp_path):
    eng, _ = _recording_only(tmp_path, left_on="Scene", ending="e.mp4")
    eng.state.phase = STOPPING
    eng._stop_recording = lambda: None             # type: ignore[method-assign]
    eng._journal = lambda path=None: None          # type: ignore[method-assign]
    eng._tick_stopping()
    assert eng.state.phase == IDLE
    assert eng.obs.scene == "Scene"


def test_a_crash_mid_session_then_a_recording_only_session(tmp_path):
    """App restarted mid-session: _recover closes the old one, and the next
    recording still starts on the game whatever OBS was left showing."""
    eng, began_on = _recording_only(tmp_path, left_on=ENDING)
    eng.state.phase = LIVE
    eng._stop_recording = lambda: None             # type: ignore[method-assign]
    eng._adopt_recording = lambda start=None: None  # type: ignore[method-assign]
    eng._journal = lambda path=None: None          # type: ignore[method-assign]
    eng._recover()
    assert eng.state.phase == IDLE
    eng._begin_session(VALORANT)
    assert began_on == ["Scene"]


def test_a_stream_ending_while_the_recording_carries_on(tmp_path):
    """The record button keeps a recording past its session; it must not
    carry on recording the ending card."""
    eng, began_on = _streaming(tmp_path, left_on="Scene", ending="e.mp4")
    eng.state.phase = STOPPING
    eng.state.broadcast_id = "b1"
    eng.session = eng.platform.start("t", "d")
    eng._stop_recording = lambda: None             # type: ignore[method-assign]
    eng._tick_stopping()
    eng._ending_until = time.monotonic() - 0.1
    eng._tick_stopping()
    eng.toggle_recording("record button")
    assert began_on == ["Scene"]


def test_youtube_is_never_asked_in_a_recording_only_session(tmp_path):
    eng, _ = _recording_only(tmp_path)
    eng.yt = FakeYouTube()
    eng._begin_session(VALORANT)
    assert eng.state.phase == LIVE
