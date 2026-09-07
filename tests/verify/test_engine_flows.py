"""Every way a session can move, taken.

Tier 3. A real Engine, a real State, the shipped tick methods -- with OBS,
YouTube and the game watcher replaced. Tier 2 asked whether a button reaches
the engine; this asks what the engine does when it gets there.

The phase graph is not written down anywhere in engine.py: it exists only as
nineteen calls to _goto scattered through the tick methods. surface.transitions()
derives it, and test_every_transition_has_a_scenario below fails when an edge
appears that nothing here drives -- so the graph cannot grow untested.

Every edge is reached by setting up the condition and calling the real tick,
never by calling _goto. A test that moved the phase itself would pass whatever
the engine did.
"""
from __future__ import annotations

import time

import pytest
import surface
from autostream import engine as engine_mod
from autostream import state as st
from autostream.gameindex import GameHit
from fakes import FakeObs, engine as base_engine

# --------------------------------------------------------------- fakes


class Watcher:
    """The game watcher, with the four questions the engine asks it."""

    def __init__(self, active=None, armed=None, running=None):
        self._active = active
        self._armed = armed
        self._running = running
        self.debounce_resets = 0

    def active_game(self):
        return self._active

    def armed_game(self):
        return self._armed

    def any_game_running(self):
        return (self._running if self._running is not None
                else self._active is not None)

    def reset_debounce(self):
        self.debounce_resets += 1

    def snapshot(self):
        seen = {1: self._active} if self._active else {}
        return seen, [], False


class YT:
    """YouTube, recording what it was asked to do.

    Answers plausibly rather than raising, because the failure paths are
    driven by setting `fail` on the specific call under test. A fake that
    raises everywhere would make every test a failure test.
    """

    def __init__(self, status="active", health="good"):
        self.status, self.health = status, health
        self.created, self.bound, self.transitions, self.deleted = [], [], [], []
        self.fail: set[str] = set()

    def _maybe(self, name):
        if name in self.fail:
            raise RuntimeError(f"{name} failed on purpose")

    def check_budget(self, cost):
        self._maybe("check_budget")

    def create_broadcast(self, title, desc, privacy="private"):
        self._maybe("create_broadcast")
        self.created.append((title, privacy))
        return f"bid-{len(self.created)}"

    def bind(self, bid, stream_id):
        self._maybe("bind")
        self.bound.append((bid, stream_id))

    def stream_status(self, stream_id):
        self._maybe("stream_status")
        return self.status, self.health

    def transition(self, bid, to):
        self._maybe(f"transition:{to}")
        self.transitions.append((bid, to))

    def delete_broadcast(self, bid):
        self.deleted.append(bid)

    def watch_url(self, bid):
        return f"https://www.youtube.com/watch?v={bid}"

    def retitle(self, *a, **kw):
        self.transitions.append(("retitle", a))


def a_hit(key="cs2.exe", name="Counter-Strike 2") -> GameHit:
    return GameHit(key=key, name=name, source="test")


@pytest.fixture(autouse=True)
def no_toasts(monkeypatch):
    """Windows toast notifications are a side effect on the desktop."""
    monkeypatch.setattr(engine_mod.notify, "toast", lambda *a, **kw: None)


def session_engine(phase=st.IDLE, *, streaming=True, active=None, armed=None,
                   running=None, recording=True, **kw):
    """A wired Engine: fake watcher, fake OBS, fake YouTube, no real clock.

    The recording and journal seams are stubbed because they talk to OBS and
    write history.jsonl; what they DID is asserted through the flags they set,
    which is what the rest of the engine reads anyway.
    """
    eng = base_engine(phase=phase, **kw)
    eng.streaming = streaming
    eng.watcher = Watcher(active=active, armed=armed, running=running)
    eng.obs = FakeObs(recording=recording, streaming=streaming)
    eng.yt = YT()
    eng._starting_deadline = None
    eng._silent_said = False
    eng._quiet_said = set()
    eng._marks = []
    eng._mark_seen = {}
    eng.journalled = []

    def _start_recording():
        eng.state.recording = bool(recording)

    def _stop_recording():
        eng.state.recording = False
        return "C:/verify/rec.mp4"

    eng._start_recording = _start_recording
    eng._stop_recording = _stop_recording
    eng._journal = lambda path: eng.journalled.append(path)
    # Picture, audio and the live extras each reach OBS or YouTube on a timer
    # of their own; they are separately tested and are noise here.
    eng._check_picture = lambda: None
    eng._check_audio = lambda: None
    eng._poll_live_extras = lambda: None
    eng._collect_matches = lambda: None
    eng._show_starting = lambda: None
    eng._tick_screen = lambda: None
    return eng


def at_phase(eng, seconds: float) -> None:
    """Pretend the current phase started `seconds` ago."""
    eng._phase_since = time.monotonic() - seconds


def set_cfg(eng, path: str, value) -> None:
    """Change one setting on a live Config.

    Not `eng.cfg.timing.cooldown = 60`, which looks right and silently does
    nothing: cfg.Section.__getattr__ wraps each nested dict in a NEW Section
    on every access, so the assignment lands on a throwaway object and is
    discarded. Five tests here passed for the wrong reason before that was
    noticed -- they were asserting the default, not the value they set.

    The dict is copied before it is written to because cfg.load() merges over
    cfg.DEFAULTS, and mutating a section in place can reach the module-level
    defaults and leak into every later test in the run.
    """
    section, _, key = path.partition(".")
    eng.cfg[section] = dict(eng.cfg[section])
    eng.cfg[section][key] = value
    assert getattr(getattr(eng.cfg, section), key) == value, (
        f"{path} did not take - the config write went nowhere")


# ==================================================== the edges

def test_idle_arms_when_a_game_appears():
    eng = session_engine(st.IDLE, active=a_hit())
    eng.tick()
    assert eng.state.phase == st.ARMING


def test_arming_starts_the_session_once_the_game_has_survived_the_delay():
    hit = a_hit()
    eng = session_engine(st.ARMING, active=hit, armed=hit)
    eng.tick()
    assert eng.state.phase == st.STARTING
    assert eng.yt.created, "no broadcast was created"


def test_arming_returns_to_idle_when_the_game_goes_away():
    """A game that vanishes before the arm delay expires was a false start --
    an installer, a launcher, a menu that closed itself."""
    eng = session_engine(st.ARMING, active=None, armed=None, running=False)
    eng.tick()
    assert eng.state.phase == st.IDLE


def test_arming_returns_to_idle_when_something_starts_blocking():
    """The preflight is re-checked at arming, not only at idle: quiet hours
    can begin, or the disk can fill, during the arm delay."""
    hit = a_hit()
    eng = session_engine(st.ARMING, active=hit, armed=hit)
    eng.state.paused = True                    # the kill switch
    eng.tick()
    assert eng.state.phase == st.IDLE


def test_arming_skips_the_delay_for_an_explicit_open_and_stream():
    """The arm delay exists to filter accidental launches. Someone who pressed
    Open + stream has already said what they want."""
    hit = a_hit()
    eng = session_engine(st.ARMING, active=hit, armed=None)
    eng.launch_intent[hit.key] = "stream"
    eng.tick()
    assert eng.state.phase == st.STARTING


def test_a_session_with_no_broadcast_goes_straight_to_live():
    """STARTING and TESTING exist to wait for ingestion and to hold a grace
    period. With no broadcast there is nothing to wait for."""
    hit = a_hit()
    eng = session_engine(st.ARMING, streaming=False, active=hit, armed=hit)
    eng.tick()
    assert eng.state.phase == st.LIVE
    assert eng.state.recording is True


def test_starting_moves_to_testing_once_youtube_sees_the_stream():
    eng = session_engine(st.STARTING)
    eng.state.broadcast_id = "bid-1"
    set_cfg(eng, "timing.abort_grace", 30)
    eng.tick()
    assert eng.state.phase == st.TESTING
    assert ("bid-1", "testing") in eng.yt.transitions


def test_starting_goes_straight_live_when_there_is_no_grace_period():
    eng = session_engine(st.STARTING)
    eng.state.broadcast_id = "bid-1"
    set_cfg(eng, "timing.abort_grace", 0)
    eng.tick()
    assert eng.state.phase == st.LIVE
    assert ("bid-1", "live") in eng.yt.transitions


def test_starting_still_goes_live_when_the_testing_transition_fails():
    """A failed testing transition must not strand a session that YouTube can
    already see: the ingestion is up, so the stream is real."""
    eng = session_engine(st.STARTING)
    eng.state.broadcast_id = "bid-1"
    set_cfg(eng, "timing.abort_grace", 30)
    eng.yt.fail.add("transition:testing")
    eng.tick()
    assert eng.state.phase == st.LIVE


def test_starting_gives_up_when_youtube_never_sees_the_stream():
    eng = session_engine(st.STARTING)
    eng.state.broadcast_id = "bid-1"
    eng._starting_deadline = time.monotonic() - 1
    eng.tick()
    assert eng.state.phase == st.IDLE
    assert eng.yt.deleted == ["bid-1"], "the dead broadcast was left behind"


def test_three_failed_starts_in_a_row_pause_the_app():
    """Otherwise a broken OBS retries every few seconds forever, and each
    attempt creates and deletes a broadcast against the daily quota."""
    eng = session_engine(st.STARTING)
    for _ in range(3):
        eng.state.phase = st.STARTING
        eng.state.broadcast_id = "bid-x"
        eng._starting_deadline = time.monotonic() - 1
        eng.tick()
    assert eng.state.paused is True
    assert eng._start_failures >= 3


def test_a_successful_start_clears_the_failure_count():
    """Two bad nights followed by a good one must not pause the app on the
    next failure."""
    eng = session_engine(st.STARTING)
    eng._start_failures = 2
    eng.state.broadcast_id = "bid-1"
    set_cfg(eng, "timing.abort_grace", 0)
    eng.tick()
    assert eng._start_failures == 0


def test_testing_holds_the_grace_period_before_going_public():
    """The whole point of the grace period is that it can be aborted."""
    eng = session_engine(st.TESTING)
    eng.state.broadcast_id = "bid-1"
    set_cfg(eng, "timing.abort_grace", 30)
    at_phase(eng, 5)
    eng.tick()
    assert eng.state.phase == st.TESTING, "went public inside the grace period"
    at_phase(eng, 31)
    eng.tick()
    assert eng.state.phase == st.LIVE


def test_a_failed_live_transition_abandons_rather_than_pretending():
    eng = session_engine(st.TESTING)
    eng.state.broadcast_id = "bid-1"
    set_cfg(eng, "timing.abort_grace", 0)
    eng.yt.fail.add("transition:live")
    at_phase(eng, 1)
    eng.tick()
    assert eng.state.phase == st.IDLE
    assert eng.yt.deleted == ["bid-1"]


def test_live_enters_cooldown_when_the_game_closes():
    """Cooldown, not stop: alt-tabbing out of a game or a map change should
    not end the stream."""
    eng = session_engine(st.LIVE, active=None)
    eng.state.session_start = time.time()
    eng.tick()
    assert eng.state.phase == st.COOLDOWN


def test_live_stops_at_the_maximum_session_length():
    eng = session_engine(st.LIVE, active=a_hit())
    set_cfg(eng, "timing.max_session_hours", 1)
    eng.state.session_start = time.time() - 7200
    eng.tick()
    assert eng.state.phase == st.STOPPING


def test_live_stops_when_the_pause_flag_file_appears(tmp_path):
    """The flag FILE is different from the pause button: it is a 'do not
    stream' switch meant to be left in place, so it ends the session rather
    than parking it on a card."""
    flag = tmp_path / "paused.flag"
    flag.write_text("x", encoding="utf-8")
    eng = session_engine(st.LIVE, active=a_hit())
    eng.state.session_start = time.time()
    eng._paused = lambda: True
    eng.tick()
    assert eng.state.phase == st.STOPPING


def test_live_stops_after_a_sustained_obs_outage():
    """Only after a sustained one -- OBS is allowed to reconnect first."""
    eng = session_engine(st.LIVE, active=a_hit())
    eng.state.session_start = time.time()
    eng.obs.streaming = False
    eng.tick()
    assert eng.state.phase == st.LIVE, "gave up on the first missed tick"
    eng._obs_down_since = time.monotonic() - 121
    eng.tick()
    assert eng.state.phase == st.STOPPING


def test_a_recording_only_session_watches_the_recording_not_the_stream():
    """FROM A BUG. With streaming off there is no stream output to watch, so
    is_streaming() reported a dead output every tick and ended every
    recording-only session after two minutes."""
    eng = session_engine(st.LIVE, streaming=False, active=a_hit())
    eng.state.session_start = time.time()
    eng.obs.streaming = False          # correct: nothing is being streamed
    eng.obs.recording = True
    eng._obs_down_since = time.monotonic() - 300
    eng.tick()
    assert eng.state.phase == st.LIVE


def test_a_paused_session_stays_live():
    """Pause keeps the broadcast up: a be-right-back card is a promise to come
    back, and it can only be kept if there is a stream to come back to."""
    eng = session_engine(st.LIVE, active=a_hit())
    eng.state.session_start = time.time()
    eng.state.paused = True
    eng.tick()
    assert eng.state.phase == st.LIVE


def test_cooldown_returns_to_live_when_the_game_comes_back():
    hit = a_hit()
    eng = session_engine(st.COOLDOWN, active=hit)
    eng.state.current_key = hit.key
    eng.tick()
    assert eng.state.phase == st.LIVE


def test_cooldown_stops_once_it_expires():
    eng = session_engine(st.COOLDOWN, active=None)
    set_cfg(eng, "timing.cooldown", 60)
    at_phase(eng, 61)
    eng.tick()
    assert eng.state.phase == st.STOPPING


def test_cooldown_does_not_stop_early():
    eng = session_engine(st.COOLDOWN, active=None)
    set_cfg(eng, "timing.cooldown", 60)
    at_phase(eng, 10)
    eng.tick()
    assert eng.state.phase == st.COOLDOWN


def test_stopping_completes_the_broadcast_and_returns_to_idle():
    eng = session_engine(st.STOPPING)
    eng.state.broadcast_id = "bid-1"
    eng.state.session_start = time.time()
    eng.tick()
    assert eng.state.phase == st.IDLE
    assert ("bid-1", "complete") in eng.yt.transitions


def test_stopping_writes_the_journal_before_the_session_is_cleared():
    """reset_session() is the last instant broadcast_id, session_games and
    session_start all still exist, and the Clips page needs every one."""
    eng = session_engine(st.STOPPING)
    eng.state.broadcast_id = "bid-1"
    eng.state.session_start = time.time()
    eng.tick()
    assert eng.journalled == ["C:/verify/rec.mp4"]


def test_stopping_serves_a_full_arm_delay_to_the_next_session():
    eng = session_engine(st.STOPPING)
    eng.state.session_start = time.time()
    before = eng.watcher.debounce_resets
    eng.tick()
    assert eng.watcher.debounce_resets > before


def test_force_stop_moves_to_stopping_and_suppresses_the_game():
    eng = session_engine(st.LIVE, active=a_hit(), running={"cs2.exe": 1})
    eng.watcher._active = a_hit()
    eng.force_stop("control panel")
    assert eng.launch_intent.get("cs2.exe") == "stopped"


def test_a_game_switch_restarts_the_broadcast_under_that_policy():
    """youtube.switch_policy = new_broadcast means a different game gets its
    own VOD rather than a retitle halfway through."""
    eng = session_engine(st.LIVE, active=a_hit("valorant.exe", "VALORANT"))
    eng.state.session_start = time.time()
    eng.state.broadcast_id = "bid-1"
    eng.state.current_key = "cs2.exe"
    set_cfg(eng, "youtube.switch_policy", "new_broadcast")
    eng._restart_broadcast(a_hit("valorant.exe", "VALORANT"))
    assert eng.state.phase in (st.STARTING, st.STOPPING)


def test_an_unknown_phase_resets_rather_than_wedging():
    """state.json is written by an older version, or corrupted. A phase the
    engine does not know would otherwise match no branch and tick forever."""
    eng = session_engine("BANANA")
    eng.tick()
    assert eng.state.phase != "BANANA"


# ==================================================== the preflight

def _blocked(eng) -> str | None:
    eng.tick()
    return eng.blocked_reason


def test_the_kill_switch_blocks_a_start():
    eng = session_engine(st.IDLE, active=a_hit())
    eng.state.paused = True
    assert _blocked(eng) == "paused via kill switch"
    assert eng.state.phase == st.IDLE


def test_the_flag_file_blocks_a_start():
    eng = session_engine(st.IDLE, active=a_hit())
    eng._paused = lambda: True
    assert "paused (" in (_blocked(eng) or "")


def test_quiet_hours_block_a_start():
    eng = session_engine(st.IDLE, active=a_hit())
    eng._in_quiet_hours = lambda now=None: True
    assert _blocked(eng) == "inside quiet hours"


def test_a_full_disk_blocks_a_start(monkeypatch):
    import shutil as _sh

    eng = session_engine(st.IDLE, active=a_hit())
    set_cfg(eng, "rules.min_free_disk_gb", 500)
    monkeypatch.setattr(
        _sh, "disk_usage",
        lambda p: type("U", (), {"free": 1 * 1024 ** 3, "total": 0, "used": 0})())
    assert "GB free" in (_blocked(eng) or "")
    assert eng.state.phase == st.IDLE


def test_an_exhausted_quota_blocks_a_start():
    eng = session_engine(st.IDLE, active=a_hit())
    eng.state.roll_quota_day()
    eng.state.quota_spent = 10 ** 9
    assert "quota too low" in (_blocked(eng) or "")


def test_quota_does_not_block_a_session_that_never_streams():
    """Quota is a YouTube concept. A user who only records would otherwise be
    refused a recording because of an API budget they never spend."""
    eng = session_engine(st.IDLE, streaming=False, active=a_hit())
    eng.state.roll_quota_day()
    eng.state.quota_spent = 10 ** 9
    eng.tick()
    assert eng.state.phase == st.ARMING


def test_opening_without_streaming_says_so_rather_than_sitting_silent():
    eng = session_engine(st.IDLE, active=a_hit())
    eng.launch_intent["cs2.exe"] = "silent"
    assert _blocked(eng) == "opened without streaming"
    assert eng.state.phase == st.IDLE


def test_a_manual_stop_says_how_to_undo_itself():
    eng = session_engine(st.IDLE, active=a_hit())
    eng.launch_intent["cs2.exe"] = "stopped"
    assert "close the game" in (_blocked(eng) or "")


def test_an_explicit_open_and_stream_overrides_the_convenience_guards():
    """Quiet hours and battery are conveniences; someone who pressed the
    button has overruled them. Disk, quota and paused are safety, and stay."""
    eng = session_engine(st.IDLE, active=a_hit())
    eng._in_quiet_hours = lambda now=None: True
    eng.launch_intent["cs2.exe"] = "stream"
    eng.tick()
    assert eng.state.phase == st.ARMING


def test_an_explicit_open_and_stream_does_not_override_the_kill_switch():
    eng = session_engine(st.IDLE, active=a_hit())
    eng.state.paused = True
    eng.launch_intent["cs2.exe"] = "stream"
    eng.tick()
    assert eng.state.phase == st.IDLE


def test_the_block_clears_when_the_game_goes_away():
    eng = session_engine(st.IDLE, active=a_hit())
    eng.state.paused = True
    eng.tick()
    assert eng.blocked_reason
    eng.watcher._active = None
    eng.tick()
    assert eng.blocked_reason is None


# ==================================================== completeness

# Every edge the engine can take, and the test above that takes it. Keyed by
# the (method, target phase) pair surface.transitions() derives from the
# source, so this cannot drift out of step with engine.py without failing.
SCENARIOS: dict[tuple[str, str], str] = {
    ("_tick_idle", "ARMING"): "test_idle_arms_when_a_game_appears",
    ("_tick_arming", "IDLE"): "test_arming_returns_to_idle_when_the_game_goes_away",
    ("_begin_session", "STARTING"):
        "test_arming_starts_the_session_once_the_game_has_survived_the_delay",
    ("_begin_recording_only", "LIVE"):
        "test_a_session_with_no_broadcast_goes_straight_to_live",
    ("_tick_starting", "TESTING"):
        "test_starting_moves_to_testing_once_youtube_sees_the_stream",
    ("_go_live", "LIVE"): "test_testing_holds_the_grace_period_before_going_public",
    ("_abandon_start", "IDLE"):
        "test_starting_gives_up_when_youtube_never_sees_the_stream",
    ("_tick_live", "COOLDOWN"): "test_live_enters_cooldown_when_the_game_closes",
    ("_tick_live", "STOPPING"): "test_live_stops_at_the_maximum_session_length",
    ("_tick_cooldown", "LIVE"):
        "test_cooldown_returns_to_live_when_the_game_comes_back",
    ("_tick_cooldown", "STOPPING"): "test_cooldown_stops_once_it_expires",
    ("_tick_stopping", "IDLE"):
        "test_stopping_completes_the_broadcast_and_returns_to_idle",
    ("force_stop", "STOPPING"):
        "test_force_stop_moves_to_stopping_and_suppresses_the_game",
    ("_restart_broadcast", "STARTING"):
        "test_a_game_switch_restarts_the_broadcast_under_that_policy",
    ("_restart_broadcast", "STOPPING"):
        "test_a_game_switch_restarts_the_broadcast_under_that_policy",
}


def test_every_transition_has_a_scenario():
    """An edge added to engine.py without a test fails here by name.

    This is the check that makes tier 3 a statement about the whole state
    machine rather than about the fifteen edges somebody thought of.
    """
    edges = set(surface.transitions())
    assert len(edges) >= 15, "the transition extractor stopped matching"
    missing = sorted(edges - set(SCENARIOS))
    assert missing == [], (
        "these phase transitions exist in engine.py and nothing drives them: "
        + str(missing))


def test_no_scenario_names_an_edge_that_no_longer_exists():
    stale = sorted(set(SCENARIOS) - set(surface.transitions()))
    assert stale == [], f"scenarios for transitions that were removed: {stale}"


def test_every_named_scenario_is_a_real_test_in_this_file():
    here = set(globals())
    missing = sorted({n for n in SCENARIOS.values()} - here)
    assert missing == [], f"named but not defined: {missing}"


def test_every_preflight_reason_has_a_test():
    """Each of these is text the dashboard shows the user verbatim when it
    refuses to start, and none of it is covered anywhere else."""
    reasons = surface.preflight_reasons()
    assert len(reasons) >= 6, "the preflight extractor stopped matching"
    covered = {
        "paused via kill switch": "test_the_kill_switch_blocks_a_start",
        "paused ({self.cfg.rules.paused_flag_file} present)":
            "test_the_flag_file_blocks_a_start",
        "inside quiet hours": "test_quiet_hours_block_a_start",
        "only {free_gb:.1f} GB free": "test_a_full_disk_blocks_a_start",
        "quota too low ({self.state.quota_left(DAILY_QUOTA)} units left)":
            "test_an_exhausted_quota_blocks_a_start",
        "on battery power": "test_running_on_battery_blocks_a_start",
    }
    missing = sorted(reasons - set(covered))
    assert missing == [], f"preflight can refuse for reasons nothing tests: {missing}"


def test_running_on_battery_blocks_a_start(monkeypatch):
    """A laptop that starts streaming on its way to a meeting."""
    eng = session_engine(st.IDLE, active=a_hit())
    set_cfg(eng, "rules.require_ac_power", True)
    monkeypatch.setattr(
        engine_mod.psutil, "sensors_battery",
        lambda: type("B", (), {"power_plugged": False, "percent": 50})())
    assert _blocked(eng) == "on battery power"
