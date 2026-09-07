"""The stand-ins the suite shares.

These lived in tests/test_engine.py, where four other files reached across to
borrow them and two more kept their own near-copies that had already drifted.
One home means a fake that gains a method gains it for everybody, and a fake
that stops matching the real object fails loudly in one place instead of
quietly in five.

Nothing in here touches OBS, YouTube, the network or a real recording. The
fakes are deliberately strict rather than permissive: FakeYouTube raises on
every attribute so a call that should never happen fails by name, and FakeObs
reports "cannot tell" (None) where the real OBS would, because a fake that
answers confidently teaches the code the wrong lesson.
"""
from __future__ import annotations

import collections
import contextlib
import json
import queue
import socket
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from autostream import cfg
from autostream.engine import Engine
from autostream.gameindex import GameHit
from autostream.state import IDLE, State

# --------------------------------------------------------------- OBS


class FakeObs:
    def __init__(self, recording=True, streaming=False, can_pause=True):
        self.recording, self.streaming = recording, streaming
        # can_pause=False stands in for an OBS that refuses the verb, which is
        # the only route back to "pausing stops the session instead".
        self.can_pause, self.rec_paused = can_pause, False
        self.audio_watching = False
        self.started = self.stopped = 0
        self.scene = None
        self.built = []

    def is_streaming(self):
        return self.streaming

    def recording_active(self):
        return self.recording

    def recording_paused(self):
        return self.rec_paused

    def pause_recording(self):
        if not self.recording or not self.can_pause:
            return False
        self.rec_paused = True
        return True

    def resume_recording(self):
        if not self.recording:
            return False
        self.rec_paused = False
        return True

    def set_overlay_text(self, text):
        pass

    def audio_watch_start(self):
        self.audio_watching = True

    def audio_watch_stop(self):
        self.audio_watching = False

    def silent_for(self):
        # None is "cannot tell", which is what an OBS with no metering
        # reports -- and what must never read as silence.
        return None

    def screenshot(self, width=160, height=90, scene=None):
        # None short-circuits the black-output check, which is a real OBS
        # answer (no frame available) and not a case worth faking pixels for.
        return None

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


class FakeYouTube:
    """Every call is a failure, because none of them should happen."""

    def __getattr__(self, name):
        def boom(*a, **kw):
            raise AssertionError(f"YouTube.{name} called with streaming off")
        return boom


# --------------------------------------------------------------- engine


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
    eng._blank_checked = 0.0
    eng._blank_strikes = 0
    # tick() drains the command queue before it does anything else, so an
    # engine built this way could not be ticked at all without these two.
    eng._commands = queue.Queue()
    eng._stop_requested = False
    return eng


def clips_only(phase: str = IDLE, **kw) -> Engine:
    """An engine with youtube.enabled off: recording, no broadcast."""
    eng = engine(phase=phase, **kw)
    eng.streaming = False
    eng.yt = FakeYouTube()
    eng.index = None
    eng._start_failures = 0
    eng._phase_since = 0.0
    eng._obs_down_since = None
    eng._switch_candidate = None
    return eng


def a_game(exe: str = "cs2.exe", name: str = "Counter-Strike 2") -> dict:
    return {1234: GameHit(key=exe, name=name, source="test")}


class FakeEngine:
    """What webui.Server reads off an engine, and nothing else.

    Commands are recorded rather than executed: the flow tests are asking
    whether the route reaches the engine with the right payload, which is a
    different question from what the engine then does with it. Tier 3 drives a
    real Engine for that.
    """

    def __init__(self, phase: str = IDLE, streaming: bool = True):
        self.state = State(phase=phase)
        self.state.save = lambda: None       # type: ignore[method-assign]
        self.streaming = streaming
        self.viewers = self.likes = self.views = None
        self.blocked_reason = None
        self.obs_health: dict = {}
        self.chat: collections.deque = collections.deque(maxlen=120)
        self.client_seen = 0.0
        self.pending_scan = None
        self.submitted: list = []
        self.stop_requests = 0
        self._phase_since = 0.0
        c = cfg.load()
        self.cfg = cfg.Config(c)

    def submit(self, command) -> None:
        self.submitted.append(command)

    def request_stop(self) -> None:
        self.stop_requests += 1

    # The command names that reached the engine, with any payload dropped, so
    # a test can say `"record" in eng.commands` without unpacking tuples.
    @property
    def commands(self) -> list[str]:
        return [c[0] if isinstance(c, tuple) else c for c in self.submitted]


# --------------------------------------------------------------- the server


class LiveServer:
    """A real webui.Server on a real socket, for the flow tests.

    Binds 127.0.0.1 rather than going through Server.start(), which binds
    0.0.0.0 and would raise a Windows Firewall prompt on a developer machine
    every time the suite ran. Everything else -- the handler, the auth check,
    the JSON encoding, the 1 MiB body cap -- is the shipped code path.

    Port 0 lets the OS pick, so a run does not collide with the daemon on 8787
    or with a second copy of the suite.
    """

    def __init__(self, engine=None, token: str = "test-token-abc"):
        from autostream import webui

        self.srv = webui.Server.__new__(webui.Server)
        self.srv.token = token
        self.srv.engine = engine
        self.srv.window = None
        self.srv.httpd = None
        self.srv._thread = None
        self.srv._theme = None
        self.srv._busy_lock = threading.Lock()
        self.srv._in_flight = 0
        self.srv._idle_since = 0.0
        from autostream.setup_flow import SetupFlow
        self.srv.setup = SetupFlow()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                         partial(webui._Handler, self.srv))
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.srv.port = self.port
        self.token = token
        # serve_forever polls its shutdown flag every 0.5s by default, so
        # close() blocked for half a second per test -- two minutes across the
        # flow suite, all of it teardown. The poll interval costs nothing.
        self._thread = threading.Thread(target=self.httpd.serve_forever,
                                        kwargs={"poll_interval": 0.02},
                                        name="verify-web", daemon=True)
        self._thread.start()

    # ------------- requests -------------

    def url(self, path: str, *, key: bool = True) -> str:
        sep = "&" if "?" in path else "?"
        base = f"http://127.0.0.1:{self.port}{path}"
        return f"{base}{sep}k={self.token}" if key else base

    def get(self, path: str, *, key: bool = True, timeout: float = 10.0):
        return self._call("GET", path, None, key, timeout)

    def post(self, path: str, body: Any = None, *, key: bool = True,
             timeout: float = 10.0, raw: bytes | None = None):
        return self._call("POST", path, body, key, timeout, raw=raw)

    def _call(self, method: str, path: str, body, key: bool, timeout: float,
              raw: bytes | None = None):
        data = None
        if method == "POST":
            data = raw if raw is not None else json.dumps(
                body if body is not None else {}).encode("utf-8")
        # ThreadingHTTPServer keeps connections alive, and a handler that
        # answers early and closes (a 403, which is decided before the body is
        # read) can drop a pooled socket under the client mid-request. That
        # surfaces as ConnectionAborted on Windows and has nothing to do with
        # what is under test, so one retry on a NEW connection settles it.
        # Only the transport error is retried: an HTTP status is an answer.
        for attempt in (1, 2):
            req = urllib.request.Request(self.url(path, key=key), data=data,
                                         method=method)
            req.add_header("Connection", "close")
            if data is not None:
                req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return Response(r.status, r.read(), dict(r.headers))
            except urllib.error.HTTPError as e:
                # A 403 or a 400 is an answer under test, not a failure to
                # reach the server, so it comes back as a Response like
                # anything else.
                return Response(e.code, e.read(), dict(e.headers))
            except (ConnectionAbortedError, ConnectionResetError,
                    urllib.error.URLError):
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.httpd.shutdown()
        with contextlib.suppress(Exception):
            self.httpd.server_close()


class Response:
    def __init__(self, status: int, body: bytes, headers: dict):
        self.status = status
        self.body = body
        self.headers = headers

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self) -> Any:
        """The parsed body, or None when it was never JSON.

        Returning None rather than raising keeps a caller that is checking a
        status code from having to know whether the route answers JSON: the
        page routes and the media routes do not.
        """
        try:
            return json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    @property
    def is_json(self) -> bool:
        return "json" in (self.headers.get("Content-Type") or "")


def free_port() -> int:
    """A port nothing is listening on, for the tests that spawn a process."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def seed_home(root: Path, **overrides: Any) -> Path:
    """A throwaway AUTOSTREAM_HOME with a minimal, offline config.

    youtube.enabled off is the supported no-op mode (engine.py: `self.streaming
    = config.youtube.enabled`): no broadcast, no OAuth, no quota, and
    webui.is_configured() returns True so the setup wizard is skipped. That is
    what makes a spawned daemon safe to run unattended.
    """
    import yaml

    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "secrets").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    values: dict[str, Any] = {
        "youtube": {"enabled": False},
        "record": {"enabled": False},
        "rules": {"web_token": "verify-token", "tray_icon": False,
                  "kill_switch_hotkey": ""},
        "obs": {"host": "127.0.0.1", "port": 4455, "password": ""},
    }
    for section, fields in overrides.items():
        values.setdefault(section, {}).update(fields)
    (root / "config" / "config.yaml").write_text(
        yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    return root
