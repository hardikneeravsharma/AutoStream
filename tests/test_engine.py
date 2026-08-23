"""Pause, resume, and running without streaming.

Both of the things in here are states a user can get stuck in, and neither
produces an error while it happens -- the app carries on looking healthy while
refusing to do the one thing that was asked of it. So they are pinned with what
went wrong in the docstring, because the symptom ("Resume does nothing") is
several steps away from the cause.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import cfg                                   # noqa: E402
from autostream.engine import Engine                         # noqa: E402
from autostream.gameindex import GameHit                      # noqa: E402
from autostream.state import IDLE, LIVE, State                # noqa: E402


class FakeObs:
    def __init__(self, recording=True, streaming=False):
        self.recording, self.streaming = recording, streaming
        self.started = self.stopped = 0
        self.scene = None
        self.built = []

    def is_streaming(self):
        return self.streaming

    def recording_active(self):
        return self.recording

    def set_overlay_text(self, text):
        pass

    def set_scene(self, scene):
        self.scene = scene

    def ensure_media_scene(self, scene, source, path, loop=True):
        self.built.append(("media", scene, path))
        return True

    def ensure_browser_scene(self, scene, source, url):
        self.built.append(("browser", scene, url))
        return True

    def start(self, scene=None, overlay=None):
        self.started += 1
        self.streaming = True

    def stop(self):
        self.stopped += 1
        self.streaming = False


class FakeWatcher:
    def __init__(self, running: dict | None = None):
        self.running = running or {}
        self.debounce_resets = 0

    def reset_debounce(self):
        self.debounce_resets += 1

    def snapshot(self):
        return self.running, [], False


def engine(phase: str = IDLE, paused: bool = False,
           running: dict | None = None) -> Engine:
    """An Engine with no __init__: only the pause machinery is under test."""
    eng = Engine.__new__(Engine)
    # The convenience guards are switched off so these tests say the same thing
    # at three in the morning on a laptop as they do at noon on a desktop.
    c = cfg.load()
    c["rules"] = dict(c["rules"])
    c["rules"]["quiet_hours"] = []
    c["rules"]["require_ac_power"] = False
    eng.cfg = cfg.Config(c)
    eng.state = State(phase=phase, paused=paused)
    eng.state.save = lambda: None            # type: ignore[method-assign]
    eng.launch_intent = {}
    eng.watcher = FakeWatcher(running)
    eng.blocked_reason = None
    eng._screen_until = None
    eng._ending_until = None
    eng.obs = FakeObs()
    # The plain attributes __init__ sets and the tick path reads. Listed here
    # rather than per test so a new test does not fail on bookkeeping.
    import collections
    eng.streaming = True
    eng._obs_down_since = None
    eng._switch_candidate = None
    eng._start_failures = 0
    eng._phase_since = 0.0
    eng.viewers = eng.likes = eng.views = None
    eng.obs_health = {}
    eng.chat = collections.deque(maxlen=120)
    eng._chat_id = eng._chat_token = None
    eng._details_checked = 0.0
    eng.pending_scan = None
    eng._last_title = None
    return eng


def a_game(exe: str = "cs2.exe", name: str = "Counter-Strike 2") -> dict:
    return {1234: GameHit(key=exe, name=name, source="test")}


# ------------------------------------------------------------------ pausing

def test_pausing_does_not_mark_the_running_game_as_stopped():
    """THE BUG. `force_stop` marks every open game "do not restart", because a
    human pressing End stream means "stop streaming THIS". Pause borrowed that
    path, and the flag it left behind is only cleared when the game exits -- so
    Pause ended the stream and Resume then did nothing at all. The only way out
    was to close the game or restart AutoStream."""
    eng = engine(running=a_game())
    eng.toggle_pause("pause button")
    assert eng.state.paused is True
    assert eng.launch_intent == {}, "pausing must not suppress the running game"


def test_ending_the_stream_still_marks_it():
    # The suppression is right for End stream, and stays.
    eng = engine(running=a_game())
    eng.force_stop("control panel")
    assert eng.launch_intent.get("cs2.exe") == "stopped"


def test_resuming_clears_a_manual_stop_so_the_game_can_stream_again():
    """Resume is the button a user presses to mean "carry on".

    It also digs anyone out who is already stuck in the old state, which
    matters because that flag survives in a running process.
    """
    eng = engine(paused=True, running=a_game())
    eng.launch_intent["cs2.exe"] = "stopped"
    eng.toggle_pause("resume button")
    assert eng.state.paused is False
    assert "cs2.exe" not in eng.launch_intent


def test_resuming_leaves_a_deliberate_silent_launch_alone():
    # "silent" is the user having pressed Open rather than Open & stream. That
    # is a choice about this launch, not something to undo.
    eng = engine(paused=True, running=a_game())
    eng.launch_intent["cs2.exe"] = "silent"
    eng.toggle_pause("resume button")
    assert eng.launch_intent["cs2.exe"] == "silent"


def test_resuming_arms_from_scratch():
    """A fresh arm_delay rather than a timer inherited from before the pause,
    which could otherwise start a session on the very next tick."""
    eng = engine(paused=True, running=a_game())
    before = eng.watcher.debounce_resets
    eng.toggle_pause("resume button")
    assert eng.watcher.debounce_resets > before


def _with_brb(eng, tmp_path):
    """Point the be-right-back screen at a file that exists."""
    card = tmp_path / "brb.mp4"
    card.write_bytes(b"not really a video, but it is a file")
    from autostream import cfg as cfgmod
    raw = cfgmod.load()
    data = {k: (dict(v) if isinstance(v, dict) else v) for k, v in raw.items()}
    data["screens"] = dict(data["screens"])
    data["screens"]["enabled"] = True
    data["screens"]["paused_file"] = str(card)
    eng.cfg = cfgmod.Config(data)
    return eng


def test_pausing_a_live_session_keeps_it_live_on_the_card(tmp_path):
    """THE POINT of the be-right-back screen.

    A card that says "be right back" is a promise to come back, and it can only
    be kept if there is still a broadcast to come back to. Ending it and
    starting a fresh one loses the URL, the chat and everyone watching.
    """
    stopped = []
    eng = _with_brb(engine(phase=LIVE, running=a_game()), tmp_path)
    eng.force_stop = lambda *a, **kw: stopped.append(True)  # type: ignore[assignment]
    assert eng.toggle_pause("pause button") is True
    assert stopped == [], "the broadcast must stay up"
    assert eng.obs.scene == "AutoStream Be Right Back"
    assert eng.state.phase == LIVE


def test_resuming_puts_the_game_back_on_air(tmp_path):
    eng = _with_brb(engine(phase=LIVE, paused=True, running=a_game()), tmp_path)
    eng.watcher.active_game = lambda: GameHit(          # type: ignore[method-assign]
        key="cs2.exe", name="CS2", scene="Game", source="t")
    eng.toggle_pause("resume button")
    assert eng.state.paused is False
    assert eng.obs.scene == "Game"


def test_pausing_with_no_card_stops_instead_of_pretending(tmp_path):
    """A paused stream still showing the game is not paused, it is unattended.

    With nothing to switch to there is no honest way to hold it, so the session
    stops -- and says why in the log.
    """
    stopped = {}
    eng = engine(phase=LIVE, running=a_game())          # screens off by default
    eng.force_stop = lambda reason="", suppress=True: stopped.update(
        reason=reason, suppress=suppress)                # type: ignore[assignment]
    eng.toggle_pause("pause button")
    assert stopped["suppress"] is False


def test_the_kill_switch_still_stops_everything(tmp_path):
    """Pause holds a stream up now, so the hotkey needed its own command.

    A kill switch that parks the stream on a card is not a kill switch, and the
    hotkey is documented as one.
    """
    stopped = {}
    eng = _with_brb(engine(phase=LIVE, running=a_game()), tmp_path)
    eng.force_stop = lambda reason="", suppress=True: stopped.update(
        reason=reason, suppress=suppress)                # type: ignore[assignment]
    eng.kill("hotkey")
    assert eng.state.paused is True
    assert stopped["suppress"] is False


def test_pause_and_resume_round_trip():
    # IDLE, so there is no live session either way: what is checked here is
    # only that the flag flips back and nothing is left suppressed.
    eng = engine(running=a_game())
    assert eng.toggle_pause("t") is True
    assert eng.toggle_pause("t") is False
    assert eng.launch_intent == {}


# ------------------------------------------------------- clips-only mode

class FakeYouTube:
    """Every call is a failure, because none of them should happen."""
    def __getattr__(self, name):
        def boom(*a, **kw):
            raise AssertionError(f"YouTube.{name} called with streaming off")
        return boom


def clips_only(phase: str = IDLE, **kw) -> Engine:
    eng = engine(phase=phase, **kw)
    eng.streaming = False
    eng.yt = FakeYouTube()
    eng.index = None
    eng._start_failures = 0
    eng._phase_since = 0.0
    eng._obs_down_since = None
    eng._switch_candidate = None
    return eng


def test_a_clips_only_session_never_calls_youtube():
    """FakeYouTube raises on every attribute, so anything reaching the API
    fails the test by name rather than by a mystery quota charge."""
    eng = clips_only()
    eng._start_recording = lambda: setattr(eng.state, "recording", True)
    eng._begin_recording_only(GameHit(key="cs2.exe", name="CS2", source="t"))
    assert eng.state.phase == LIVE


def test_a_clips_only_session_does_not_start_the_obs_stream_output():
    # OBS is asked to record. It is not asked to stream, because there is
    # nowhere for that to go.
    eng = clips_only()
    eng._start_recording = lambda: setattr(eng.state, "recording", True)
    eng._begin_recording_only(GameHit(key="cs2.exe", name="CS2", source="t"))
    assert eng.obs.started == 0


def test_a_clips_only_session_that_cannot_record_is_abandoned():
    """The recording IS the session. A LIVE phase with nothing being written
    would sit there looking healthy and produce nothing to clip."""
    eng = clips_only()
    eng._start_recording = lambda: None            # recording stays False
    abandoned = []
    eng._abandon_start = lambda: abandoned.append(True)
    eng._begin_recording_only(GameHit(key="cs2.exe", name="CS2", source="t"))
    assert abandoned == [True]
    assert eng.state.phase != LIVE


def _spend_the_quota(eng) -> None:
    # roll_quota_day() zeroes the spend when the stamp is not today's, so the
    # stamp has to be set as well as the number.
    eng.state.roll_quota_day()
    eng.state.quota_spent = 10 ** 9


def test_quota_does_not_gate_a_clips_only_session():
    """Quota is a YouTube concept. Left in, a user who never streams would be
    refused a recording because of an API budget they never spend."""
    eng = clips_only()
    _spend_the_quota(eng)
    assert eng._preflight() is None


def test_quota_still_gates_a_streaming_session():
    eng = engine()
    eng.streaming = True
    _spend_the_quota(eng)
    assert "quota" in (eng._preflight() or "")


def test_the_watchdog_watches_the_recording_when_there_is_no_stream():
    """is_streaming() is False all session in clips-only mode, so the
    stream-health watchdog would have declared the output dead and ended every
    session after two minutes."""
    eng = clips_only(phase=LIVE)
    eng.obs = FakeObs(recording=True, streaming=False)
    eng.state.session_start = None
    eng._check_picture = lambda: None
    eng.watcher.active_game = lambda: GameHit(key="cs2.exe", name="CS2",
                                              source="t")   # type: ignore[method-assign]
    eng.state.current_key = "cs2.exe"
    eng._tick_live()
    assert eng.state.phase == LIVE
    assert eng._obs_down_since is None


def test_setup_is_already_done_when_streaming_is_off():
    """Sending a clips-only user through Google OAuth to reach a page that
    cuts video files locally is how you get an app closed."""
    from autostream import webui

    c = cfg.load()
    c["youtube"] = dict(c["youtube"])
    c["youtube"]["enabled"] = False
    import autostream.cfg as cfgmod
    real = cfgmod.load
    cfgmod.load = lambda *a, **kw: cfg.Config(c)
    try:
        assert webui.is_configured() is True
    finally:
        cfgmod.load = real


# ---------------------------------------------------------- screen savers

def _cfg_with_screens(tmp_path, **files):
    """A config with the screens on and pointed at files that exist."""
    from autostream import cfg as cfgmod

    raw = cfgmod.load()
    data = {k: (dict(v) if isinstance(v, dict) else v) for k, v in raw.items()}
    data["screens"] = dict(data["screens"])
    data["screens"]["enabled"] = True
    for which, name in files.items():
        card = tmp_path / name
        card.write_bytes(b"a file")
        data["screens"][f"{which}_file"] = str(card)
    return cfgmod.Config(data)


def test_a_screen_pointed_at_nothing_is_not_configured(tmp_path):
    """The file check is the point.

    A path that has been moved would otherwise produce a scene showing
    nothing, which on a live stream is worse than never switching to it.
    """
    from autostream import cfg as cfgmod, screens

    c = _cfg_with_screens(tmp_path, starting="a.mp4")
    assert screens.configured(c, screens.STARTING) is True
    assert screens.configured(c, screens.PAUSED) is False

    raw = {k: (dict(v) if isinstance(v, dict) else v) for k, v in cfgmod.load().items()}
    raw["screens"] = dict(raw["screens"])
    raw["screens"]["enabled"] = True
    raw["screens"]["starting_file"] = str(tmp_path / "gone.mp4")
    assert screens.configured(cfgmod.Config(raw), screens.STARTING) is False


def test_screens_off_builds_nothing(tmp_path):
    from autostream import cfg as cfgmod, screens

    c = cfgmod.load()
    assert c.screens.enabled is False
    assert screens.ensure_all(c, FakeObs()) == {}


def test_the_scene_names_follow_the_prefix(tmp_path):
    from autostream import screens

    c = _cfg_with_screens(tmp_path, starting="a.mp4")
    assert screens.scene_name(c, screens.PAUSED) == "AutoStream Be Right Back"
    assert screens.source_name(c, screens.PAUSED).startswith(
        "AutoStream Be Right Back")


# ------------------------------------------------------- the session flow

def test_the_starting_card_gives_way_to_the_game(tmp_path):
    """Held by a deadline, not a sleep.

    The engine loop is strictly serial, so sleeping in it would stop the OBS
    watchdog and chat for as long as the card is up.
    """
    import time as _t

    eng = engine(phase=LIVE, running=a_game())
    eng.cfg = _cfg_with_screens(tmp_path, starting="s.mp4")
    eng.watcher.active_game = lambda: GameHit(          # type: ignore[method-assign]
        key="cs2.exe", name="CS2", scene="Game", source="t")

    eng._show_starting()
    assert eng.obs.scene == "AutoStream Starting"
    assert eng._screen_until is not None

    eng._tick_screen()                       # too early
    assert eng.obs.scene == "AutoStream Starting"

    eng._screen_until = _t.monotonic() - 0.1
    eng._tick_screen()
    assert eng.obs.scene == "Game"
    assert eng._screen_until is None


def test_the_starting_card_is_not_pulled_off_while_paused(tmp_path):
    """The be-right-back card is held by the pause, not by a timer.

    Without this check a pause during the opening ten seconds would be undone
    by the starting card's own deadline.
    """
    import time as _t

    eng = engine(phase=LIVE, paused=True, running=a_game())
    eng.cfg = _cfg_with_screens(tmp_path, starting="s.mp4", paused="b.mp4")
    eng.obs.scene = "AutoStream Be Right Back"
    eng._screen_until = _t.monotonic() - 5
    eng._tick_screen()
    assert eng.obs.scene == "AutoStream Be Right Back"


def test_the_ending_card_is_held_before_the_broadcast_is_completed(tmp_path):
    """The only window it can be seen in.

    Afterwards the broadcast is complete and there is nothing to show it on.
    """
    import time as _t

    eng = engine(phase="STOPPING", running=a_game())
    eng.cfg = _cfg_with_screens(tmp_path, ending="e.mp4")
    eng.state.broadcast_id = "abc123"
    eng.streaming = True
    eng.yt = FakeYouTube()
    finished = []
    eng._journal = lambda path=None: finished.append(True)  # type: ignore[method-assign]
    eng._stop_recording = lambda: None                      # type: ignore[method-assign]

    eng._tick_stopping()                     # puts the card up and returns
    assert eng.obs.scene == "AutoStream Ending"
    assert finished == [], "nothing may be torn down yet"

    eng._tick_stopping()                     # still holding
    assert finished == []

    eng._ending_until = _t.monotonic() - 0.1
    eng._tick_stopping()
    assert finished == [True]


def test_no_ending_card_means_no_delay(tmp_path):
    eng = engine(phase="STOPPING", running=a_game())
    eng.state.broadcast_id = "abc123"
    eng.streaming = False
    finished = []
    eng._journal = lambda path=None: finished.append(True)  # type: ignore[method-assign]
    eng._stop_recording = lambda: None                      # type: ignore[method-assign]
    eng._tick_stopping()
    assert finished == [True]


# ------------------------------------------------- the per-game thumbnail

def test_the_library_saves_under_the_key_the_engine_reads():
    """THE BUG this pins.

    games.yaml is keyed on the EXECUTABLE, because that is what the watcher
    sees running. The installed-games catalog is keyed on the store's id, and
    for Counter-Strike those differ: `cs2.exe` against
    `counter-strike-global-offensive`. Saving under the catalog key writes a
    perfectly good entry that nothing ever reads, and the mistake shows up as a
    missing thumbnail at go-live and nowhere earlier.
    """
    from autostream import catalog

    for a in catalog.load():
        sent = (a.exe or a.key).lower()
        if a.exe:
            assert sent == a.exe.lower(), a.name


def test_an_assigned_thumbnail_is_used_exactly_as_given(tmp_path):
    from autostream import thumbnail

    img = tmp_path / "mine.png"
    img.write_bytes(b"\x89PNG" + b"padding" * 8)
    assert thumbnail.use_as_is(img) == img


def test_a_missing_assigned_thumbnail_falls_back_rather_than_failing(tmp_path):
    """Going live with no thumbnail at all is worse than composing one."""
    from autostream import thumbnail

    assert thumbnail.use_as_is(tmp_path / "gone.png") is None


# ------------------------------------------- a screen saver that is a URL

def test_a_url_becomes_a_browser_source_and_a_path_a_media_source(tmp_path):
    """One setting, two OBS source types.

    To the person filling it in both are "the be right back card"; which kind
    of source that needs is not their problem.
    """
    from autostream import screens

    card = tmp_path / "brb.mp4"
    card.write_bytes(b"a file")
    c = _cfg_with_screens(tmp_path, starting="s.mp4")
    data = {k: (dict(v) if isinstance(v, dict) else v) for k, v in c.items()}
    data["screens"] = dict(data["screens"])
    data["screens"]["paused_file"] = "https://example.com/overlay/abc"
    from autostream import cfg as cfgmod
    c = cfgmod.Config(data)

    obs = FakeObs()
    screens.ensure_all(c, obs)
    assert ("browser", "AutoStream Be Right Back",
            "https://example.com/overlay/abc") in obs.built
    assert any(k == "media" for k, _s, _w in obs.built)


def test_only_a_scheme_makes_it_a_url():
    """Guessing from a dot or a slash misreads ordinary Windows paths."""
    from autostream import screens

    assert screens.is_url("https://example.com/x")
    assert screens.is_url("HTTP://example.com/x")
    assert not screens.is_url(r"C:\Users\me\my.site.com\brb.mp4")
    assert not screens.is_url(r"\\nas\share\brb.mp4")
    assert not screens.is_url("")


def test_a_url_is_taken_on_trust_but_a_path_must_exist(tmp_path):
    """Reaching out to check a URL would put a network round trip in front of
    going live, and an overlay needing a browser session answers unhelpfully to
    anything else anyway."""
    from autostream import cfg as cfgmod, screens

    raw = cfgmod.load()
    data = {k: (dict(v) if isinstance(v, dict) else v) for k, v in raw.items()}
    data["screens"] = dict(data["screens"])
    data["screens"]["enabled"] = True
    data["screens"]["paused_file"] = "https://example.com/nothing-here"
    data["screens"]["starting_file"] = str(tmp_path / "gone.mp4")
    c = cfgmod.Config(data)

    assert screens.configured(c, screens.PAUSED) is True
    assert screens.configured(c, screens.STARTING) is False
    # ...and only the missing FILE is reported to the user.
    gaps = screens.missing(c)
    assert len(gaps) == 1 and "gone.mp4" in gaps[0]
