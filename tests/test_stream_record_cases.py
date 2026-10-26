"""Recording and streaming, every way the two can disagree.

Each of these was found by running the real engine against a fake OBS, after
a recording-only session on 2026-10-26 recorded an hour of the ending card.
Ten failed. The log of the week before showed four of them happening to the
player: a stream YouTube refused, three times, after which the app paused
itself with the game running and nothing being written; six ninety-second
files from failed starts that the Clips page never listed; and the ending
card held for 2m48s on a stream that had already died, written into the
recording and nowhere else.

The rule all of them come back to: the stream is optional, the recording is
not. A reason not to BROADCAST -- the setting, quiet hours, the battery, the
quota, a platform that says no -- is not a reason to lose the game.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from autostream import engine as engine_mod
from autostream.platforms import PlatformError
from autostream.state import IDLE, LIVE, STOPPING

from test_recording_scene import (BRB, ENDING, STARTING, VALORANT, _cfg,
                                  _live, _recording_only, _streaming)


@pytest.fixture(autouse=True)
def toasts(monkeypatch):
    said: list = []
    monkeypatch.setattr(engine_mod.notify, "toast",
                        lambda *a, **kw: said.append(" ".join(map(str, a))))
    return said


def _set(eng, path: str, value) -> None:
    section, _, key = path.partition(".")
    eng.cfg[section] = dict(eng.cfg[section])
    eng.cfg[section][key] = value


def _from_settings(eng) -> None:
    """Unpin `streaming`, so the engine reads youtube.enabled as the app
    does -- the fakes pin it."""
    eng._streaming_pinned = None
    eng._session_streaming = None


class _Refusing:
    """A platform that says no, as YouTube did on 2026-10-26 at 01:32."""

    caps = SimpleNamespace(has_video_tags=False, makes_broadcast=False)

    def __init__(self, error=PlatformError("403: the request cannot be completed")):
        self.error = error
        self.starts = 0

    def preflight(self, cost):
        pass

    def start(self, *a, **kw):
        self.starts += 1
        raise self.error


# ---------------------------------------- "Go live" changed in Settings


def test_go_live_switched_off_without_a_restart_is_honoured(tmp_path):
    eng, began_on = _streaming(tmp_path, left_on="Scene")
    _from_settings(eng)
    _set(eng, "youtube.enabled", False)          # Settings > Save, no restart
    eng.platform.start = lambda *a, **k: pytest.fail("went live")
    eng._begin_session(VALORANT)
    assert eng.state.phase == LIVE
    assert began_on == ["Scene"]
    assert eng.streaming is False


def test_go_live_switched_on_without_a_restart_is_honoured(tmp_path):
    eng, _ = _recording_only(tmp_path, left_on="Scene")
    _from_settings(eng)
    _set(eng, "youtube.enabled", True)
    assert eng.streaming is True, "the dashboard would still say recording only"


def test_a_session_keeps_the_mode_it_began_in(tmp_path):
    """Flipped mid-session, it lands when this session ends -- the platform
    switch's rule, for the same reason: a recording has no broadcast to go
    live on, and a broadcast cannot drop out halfway without ending."""
    eng, _ = _recording_only(tmp_path, left_on="Scene")
    _from_settings(eng)
    _set(eng, "youtube.enabled", False)
    eng._begin_session(VALORANT)
    _set(eng, "youtube.enabled", True)
    assert eng.streaming is False
    eng._stop_recording = lambda: None           # type: ignore[method-assign]
    eng._journal = lambda path=None: None        # type: ignore[method-assign]
    eng.state.phase = STOPPING
    eng._tick_stopping()
    assert eng.state.phase == IDLE
    assert eng.streaming is True


# ----------------------------------------------- a stream that is refused


def test_a_refused_stream_still_records_the_game(tmp_path, toasts):
    eng, began_on = _streaming(tmp_path, left_on="Scene")
    eng.platform = _Refusing()
    eng._begin_session(VALORANT)
    assert eng.state.phase == LIVE
    assert eng.state.recording, "the game is not being recorded"
    assert began_on == ["Scene"]
    assert eng.streaming is False
    assert any("Not streaming" in t or "not streaming" in t for t in toasts)


def test_an_unexpected_error_from_the_platform_still_records(tmp_path):
    """The 403 on 2026-10-26 was an HttpError, not a PlatformError: it went
    down the catch-all, which abandoned the session the same way."""
    eng, _ = _streaming(tmp_path, left_on="Scene")
    eng.platform = _Refusing(RuntimeError("<HttpError 403>"))
    eng._begin_session(VALORANT)
    assert eng.state.phase == LIVE and eng.state.recording


def test_a_refused_stream_is_not_retried_into_a_block(tmp_path):
    """Three refusals in ten seconds used to pause the app "until Resume".
    One refusal now makes a recording, and nothing is retried."""
    eng, _ = _streaming(tmp_path, left_on="Scene")
    eng.platform = _Refusing()
    eng._begin_session(VALORANT)
    assert eng.platform.starts == 1
    assert eng._start_failures == 0 and not eng._start_blocked


def test_with_recording_off_a_refused_stream_is_abandoned_as_before(tmp_path):
    eng, _ = _streaming(tmp_path, left_on="Scene")
    _set(eng, "record.enabled", False)
    eng.platform = _Refusing()
    eng._abandon_start = lambda: eng._goto(IDLE)      # type: ignore[method-assign]
    eng._begin_session(VALORANT)
    assert eng.state.phase == IDLE


def test_a_stream_that_will_not_go_live_keeps_recording(tmp_path):
    eng, _ = _streaming(tmp_path, left_on="Scene")
    eng._begin_session(VALORANT)
    assert eng.state.recording

    def refuse(session):
        raise RuntimeError("transition refused")
    eng.platform.go_live = refuse
    eng._go_live()
    assert eng.state.phase == LIVE and eng.state.recording
    assert eng.streaming is False


def test_a_failed_start_journals_the_file_it_wrote(tmp_path):
    """Six of these, ninety seconds each, sat in the recording folder from
    2026-10-25 with nothing on the Clips page pointing at them."""
    eng, _ = _streaming(tmp_path, left_on="Scene")
    eng.state.recording = True
    eng._earlier_files = ()
    eng._stop_recording = lambda: "C:/v/2026-10-25 17-57-08.mp4"  # type: ignore[method-assign]
    written = []
    eng._journal = lambda path=None: written.append(path)        # type: ignore[method-assign]
    eng._abandon_start()
    assert written == ["C:/v/2026-10-25 17-57-08.mp4"]


# ------------------------------------------------- reasons not to stream


def test_youtubes_quota_does_not_refuse_twitch(tmp_path):
    eng, _ = _streaming(tmp_path, left_on="Scene")
    _set(eng, "youtube.platform", "twitch")
    eng.state.quota_left = lambda daily: 0           # type: ignore[method-assign]
    assert eng._why_not_stream() is None


def test_youtubes_quota_still_refuses_youtube(tmp_path):
    eng, _ = _streaming(tmp_path, left_on="Scene")
    _set(eng, "youtube.platform", "youtube")
    eng.state.quota_left = lambda daily: 0           # type: ignore[method-assign]
    assert "quota" in (eng._why_not_stream() or "")


def test_out_of_quota_the_game_is_recorded(tmp_path):
    eng, began_on = _streaming(tmp_path, left_on="Scene")
    _set(eng, "youtube.platform", "youtube")
    eng.state.quota_left = lambda daily: 0           # type: ignore[method-assign]
    eng.platform.start = lambda *a, **k: pytest.fail("went live")
    eng._begin_session(VALORANT)
    assert eng.state.phase == LIVE and began_on == ["Scene"]


def test_open_with_streaming_off_records(tmp_path):
    """The Library's Open, with Go live off in Settings: nothing at all was
    recorded, because Open meant "not this one"."""
    eng, began_on = _recording_only(tmp_path, left_on="Scene")
    eng.launch_intent[VALORANT.key.lower()] = "silent"
    eng.watcher.armed_game = lambda: VALORANT        # type: ignore[attr-defined]
    eng.watcher.any_game_running = lambda: True      # type: ignore[attr-defined]
    eng.watcher.snapshot = lambda: ({1: VALORANT}, [], False)
    eng._intent_at = {}
    eng._intent_seen = set()
    eng.tick()
    eng.tick()
    assert began_on == ["Scene"]


# --------------------------------------------- the player stops the file


def test_stop_recording_in_a_recording_only_session_sticks(tmp_path, toasts):
    """It used to start again by itself about two and a half minutes later:
    the watchdog called the output dead, ended the session, and the next idle
    tick found the game still running."""
    eng, began_on = _recording_only(tmp_path, left_on="Scene")
    eng._begin_session(VALORANT)
    eng._marks = []
    eng.watcher.snapshot = lambda: ({1: VALORANT}, [], False)
    eng._stop_recording = lambda: (setattr(eng.state, "recording", False)  # type: ignore[method-assign]
                                   or "C:/v/f1.mp4")
    written = []
    eng._journal = lambda path=None: written.append(        # type: ignore[method-assign]
        [f["path"] for f in eng._earlier_files])
    eng.toggle_recording("record button")
    assert eng.state.phase == IDLE
    assert written == [["C:/v/f1.mp4"]], "the stopped file was not journalled"
    assert eng.launch_intent.get(VALORANT.key.lower()) == "stopped"
    eng.watcher.armed_game = lambda: VALORANT        # type: ignore[attr-defined]
    eng.watcher.any_game_running = lambda: True      # type: ignore[attr-defined]
    eng.tick()
    eng.tick()
    assert began_on == ["Scene"], "recording started again by itself"


def test_stop_recording_mid_stream_leaves_the_stream_up(tmp_path):
    eng, _ = _streaming(tmp_path, left_on="Scene")
    eng._begin_session(VALORANT)
    eng.state.phase = LIVE
    eng._marks = []
    eng._stop_recording = lambda: (setattr(eng.state, "recording", False)  # type: ignore[method-assign]
                                   or "C:/v/f1.mp4")
    eng.toggle_recording("record button")
    assert eng.state.phase == LIVE


# --------------------------------------------- the cards and the recording


def test_a_dead_stream_gets_no_ending_card(tmp_path):
    """Nobody can see it. Twice that week it was held for 2m48s over a
    stream that had died, and written into the recording."""
    eng, _ = _streaming(tmp_path, left_on="Scene", ending="e.mp4")
    eng.state.phase = STOPPING
    eng.state.broadcast_id = "b1"
    eng.session = eng.platform.start("t", "d")
    eng.state.recording = True
    eng.obs.streaming = False                        # what ended the session
    eng._unseen = False
    eng._stop_recording = lambda: None               # type: ignore[method-assign]
    eng._tick_stopping()
    assert eng.state.phase == IDLE, "held a card nobody could see"
    assert eng.obs.scene != ENDING


def _recorder_that_pauses(eng):
    """The real _card_up/_card_down against FakeObs's pause, with a
    recording that is actually running."""
    eng.obs.recording = True
    eng.state.recording = True


def test_the_starting_card_is_not_recorded(tmp_path):
    eng, _ = _streaming(tmp_path, left_on="Scene", starting="s.mp4")
    eng.obs.streaming = True
    eng._begin_session(VALORANT)
    assert eng.obs.scene == STARTING
    assert eng.obs.rec_paused, "the starting card is being recorded"
    eng._back_to_game()
    assert eng.obs.scene == "Scene"
    assert not eng.obs.rec_paused, "the game came back and was not recorded"


def test_the_ending_card_is_not_recorded(tmp_path):
    eng, _ = _streaming(tmp_path, left_on="Scene", ending="e.mp4")
    eng.state.phase = STOPPING
    eng.state.broadcast_id = "b1"
    eng.session = eng.platform.start("t", "d")
    eng.obs.streaming = True
    _recorder_that_pauses(eng)
    eng._unseen = False
    eng._tick_stopping()
    assert eng.obs.scene == ENDING
    assert eng.obs.rec_paused


def test_be_right_back_is_not_recorded_and_resume_records_again(tmp_path):
    eng, _ = _streaming(tmp_path, left_on="Scene", paused="b.mp4")
    eng.state.phase = LIVE
    eng.state.broadcast_id = "b1"
    _recorder_that_pauses(eng)
    eng.toggle_pause("pause button")
    assert eng.obs.scene == BRB and eng.obs.rec_paused
    eng.toggle_pause("resume button")
    assert eng.obs.scene == "Scene" and not eng.obs.rec_paused


def test_the_watchdog_taking_a_card_off_resumes_the_recording(tmp_path):
    eng, _ = _streaming(tmp_path, left_on="Scene", starting="s.mp4")
    eng.obs.streaming = True
    eng._begin_session(VALORANT)
    assert eng.obs.rec_paused
    _live(eng)
    eng._screen_until = None
    eng._tick_live()
    assert eng.obs.scene == "Scene" and not eng.obs.rec_paused


def test_a_refused_stream_after_the_starting_card_records_the_game(tmp_path):
    """The card went up and the recording paused; then the stream never
    reached ingest. The fallback must not leave the file paused on a card."""
    eng, _ = _streaming(tmp_path, left_on="Scene", starting="s.mp4")
    eng.obs.streaming = True
    eng._begin_session(VALORANT)
    assert eng.obs.rec_paused
    eng._starting_deadline = time.monotonic() - 1
    eng.platform.caps = SimpleNamespace(waits_for_ingest=True,
                                        has_video_tags=False)
    eng.platform.label = "YouTube"
    eng._tick_starting()
    assert eng.state.phase == LIVE
    assert eng.obs.scene == "Scene" and not eng.obs.rec_paused


def test_a_recording_only_session_never_pauses_for_a_card(tmp_path):
    eng, _ = _recording_only(tmp_path, left_on="Scene", starting="s.mp4")
    eng._begin_session(VALORANT)
    eng._card_up()
    assert not eng.obs.rec_paused


# ------------------------------------------------- said, not only logged


def test_a_recording_that_will_not_start_during_a_stream_is_said(
        tmp_path, toasts):
    eng, _ = _streaming(tmp_path, left_on="Scene")
    del eng._start_recording                         # the real one
    eng.obs.record_directory = lambda: ""
    eng.obs.set_record_directory = lambda d: None
    eng.obs.split_audio_tracks = lambda: None
    eng._free_gb = lambda: 500.0                     # type: ignore[method-assign]

    def boom():
        raise RuntimeError("encoder failed")
    eng.obs.start_recording = boom
    eng._start_recording()
    assert any("not recording" in t for t in toasts)


def test_a_crash_with_a_broadcast_up_sweeps_it_whatever_the_setting(tmp_path):
    """Go live switched off before the restart did not take the crashed
    session's broadcast off the channel."""
    eng, _ = _recording_only(tmp_path, left_on="Scene")
    _from_settings(eng)
    _set(eng, "youtube.enabled", False)
    swept = []
    eng.yt = SimpleNamespace(sweep_orphans=lambda: swept.append(1) or 1)
    eng.state.phase = LIVE
    eng.state.broadcast_id = "b1"
    eng._stop_recording = lambda: None               # type: ignore[method-assign]
    eng._adopt_recording = lambda start=None: None   # type: ignore[method-assign]
    eng._journal = lambda path=None: None            # type: ignore[method-assign]
    eng._recover()
    assert swept == [1]
