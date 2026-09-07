"""Every route the app serves, and what a correct answer looks like.

This is the register that makes "does every button work" a question with an
answer. tests/verify/test_flows.py drives each row against a real
webui.Server on a real socket; tests/verify/test_surface.py asserts the
register is complete, so a route added to webui.py without a row here fails
the suite rather than shipping untested.

Three things every row carries and one it does not:

  probe=CALL    the route is invoked and its answer checked.
  probe=STATIC  the route must exist but must never be invoked, because
                invoking it opens a dialog, raises UAC, reaches the network,
                or replaces the running program. `why` says which.
  expect        what a valid request should come back with.

What a row does NOT carry is the work behind the route. Asserting that
/api/clips/run starts a real scan belongs in tier 4, against real footage;
here the question is only whether the button reaches the server and the server
answers the shape the page is written to read.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

CALL = "call"
STATIC = "static"


@dataclass(frozen=True)
class Control:
    path: str
    method: str = "POST"
    probe: str = CALL
    label: str = ""
    page: str = ""
    # Sent as the JSON body (POST) or appended as a query string (GET).
    body: dict | None = None
    query: str = ""
    # Statuses a valid request may legitimately answer with. Several routes
    # answer 200-with-an-error-key rather than an HTTP error, on purpose: the
    # page renders the message. Where that is the case it is noted in `why`.
    status: tuple[int, ...] = (200,)
    # A predicate on the decoded JSON. None means "any JSON body will do".
    expect: Callable[[Any], bool] | None = None
    # A predicate on the whole Response, for the routes whose valid answer is
    # not JSON or depends on what is installed on the machine. Takes
    # precedence over `expect` and over `status`.
    expect_resp: Callable[[Any], bool] | None = None
    # A body that should be rejected, and how. None means the route takes
    # anything (a no-argument action).
    reject: dict | None = None
    reject_status: tuple[int, ...] = (400,)
    # Set when the route answers 200 with ok:false instead of an HTTP error.
    reject_soft: bool = False
    why: str = ""
    acts: tuple[str, ...] = field(default_factory=tuple)


def _has(*keys: str) -> Callable[[Any], bool]:
    return lambda j: isinstance(j, dict) and all(k in j for k in keys)


def _ok(j: Any) -> bool:
    return isinstance(j, dict) and j.get("ok") is True


def _dict(j: Any) -> bool:
    return isinstance(j, dict)


# --------------------------------------------------------------- the page

CONTROLS: list[Control] = [
    Control("/", "GET", CALL, "the page itself", "shell", status=(200,),
            expect=None, why="served as HTML, not JSON"),
    Control("/index.html", "GET", CALL, "the page, by name", "shell",
            status=(200,), expect=None,
            why="the same document; a browser asks for either"),

    # ------------------------------------------------------------- shell
    Control("/api/bootstrap", "GET", CALL, "first paint", "shell",
            expect=_has("mode", "theme", "themes"),
            why="decides setup wizard vs dashboard"),
    Control("/api/status", "GET", CALL, "the 2s poll", "shell",
            expect=_has("phase", "apps", "clips"),
            why="every page reads its state off this one payload"),
    Control("/api/cmd", "POST", CALL, "Pause / Resume / Stop / Record / Quit",
            "shell", body={"command": "pause"}, expect=_ok,
            reject={"command": "definitely-not-a-command"},
            acts=("top-toggle", "rail-quit", "dash-btn-stop", "dash-btn-pause",
                  "dash-btn-record", "dash-btn-abort"),
            why="the whitelist is the only thing between a POST and the engine"),
    Control("/api/theme", "POST", CALL, "theme swatch", "settings",
            body={"theme": "midnight"}, expect=_ok,
            reject={"theme": "chartreuse"}, acts=("theme",),
            why="applies immediately, bypassing Save"),

    # --------------------------------------------------------- dashboard
    Control("/api/chat", "POST", CALL, "Send chat", "dashboard",
            body={"text": "hello from verify"}, expect=_ok,
            reject={"text": "   "},
            why="empty text must not reach the broadcast"),

    # ----------------------------------------------------------- library
    Control("/api/launch", "POST", CALL, "Open / Open + stream", "library",
            body={"key": "verify-nonexistent.exe", "stream": False},
            expect=_ok, reject={"key": ""},
            why="queued on the engine; nothing is launched by the fake"),
    Control("/api/apps/scan", "POST", CALL, "Rescan", "library",
            body={}, expect=_has("ok", "count", "apps"),
            why="reads Steam/Epic/Start Menu off disk; no network"),
    Control("/api/games/thumbnail", "POST", CALL, "Thumbnail", "library",
            body={"key": "verify.exe", "path": ""}, expect=_dict,
            reject={"key": ""},
            why="a path that is not a file is refused before it is saved"),

    # ---------------------------------------------------------- settings
    Control("/api/settings/schema", "GET", CALL, "renders the whole page",
            "settings", expect=lambda j: isinstance(j, (dict, list)) and bool(j),
            why="the Settings page is generated from this"),
    Control("/api/settings/values", "GET", CALL, "current values", "settings",
            expect=lambda j: isinstance(j, dict) and "ui.theme" in j,
            why="flattened dotted paths"),
    Control("/api/settings/save", "POST", CALL, "Save changes", "settings",
            body={"values": {"clips.min_kills": 2}}, expect=_ok,
            reject={"values": {"no.such.setting": 1}}, reject_soft=True,
            acts=("set-save",),
            why="all-or-nothing; a rejected field is 200 with ok:false"),
    Control("/api/diagnostics", "POST", CALL, "Build a report", "settings",
            body={}, expect=_has("ok", "text"), acts=("set-diag-get",),
            why="must never carry the OBS password or the web token"),
    Control("/api/screens/build", "POST", CALL, "Build screen scenes",
            "settings", body={}, expect=_dict, acts=("set-build-screens",),
            why="answers with an error when screens are off; no OBS needed"),
    Control("/api/se/overlays", "POST", CALL, "Fetch overlays", "settings",
            body={}, expect=_dict, acts=("set-se-fetch",),
            why="answers 'no token stored' offline, without reaching out"),
    Control("/api/se/connect", "POST", CALL, "Connect StreamElements",
            "settings", body={"jwt": "not-a-real-jwt"},
            status=(200, 400), expect=_dict, reject={"jwt": ""},
            why="the token is validated by shape before any request"),

    # -------------------------------------------------------------- logs
    Control("/api/logs/tail", "GET", CALL, "Refresh", "logs", query="n=5",
            expect=_has("lines", "path"), acts=("log-refresh", "log-auto"),
            why="n is clamped to 1..2000"),
    Control("/api/logs/open", "POST", STATIC, "Open log file", "logs",
            acts=("log-open",),
            why="os.startfile opens a text editor on the developer's desktop"),

    # ------------------------------------------------------------- clips
    Control("/api/clips/tools", "GET", CALL, "tool status card", "clips",
            expect=_has("ok"), acts=("install-tools",),
            why="ffmpeg/Tesseract discovery; cached, no install"),
    Control("/api/clips/games", "GET", CALL, "game list", "clips",
            expect=lambda j: isinstance(j, (dict, list)),
            why="resolved profiles, so the button is not greyed out"),
    Control("/api/clips/sessions", "GET", CALL, "past streams", "clips",
            expect=lambda j: isinstance(j, (dict, list)),
            why="reads history.jsonl"),
    Control("/api/clips/existing", "GET", CALL, "clips of a folder", "clips",
            query="folder=", expect=lambda j: isinstance(j, (dict, list)),
            why="an empty folder is a normal answer, not an error"),
    Control("/api/clips/sounds", "GET", CALL, "sound effects", "clips",
            expect=lambda j: isinstance(j, (dict, list)),
            why="lists the sounds dir; empty when there is none"),
    Control("/api/clips/voices", "GET", CALL, "voice catalogue", "clips",
            expect=lambda j: isinstance(j, (dict, list)),
            why="grouped; empty when Kokoro is not installed"),
    Control("/api/clips/window-ready", "GET", CALL, "filmstrip poll", "clips",
            query="path=", expect=_dict,
            why="polled after /api/clips/window"),
    Control("/api/clips/frame", "GET", CALL, "filmstrip thumbnail", "clips",
            query="path=&t=0&w=160", status=(400,), expect=_has("error"),
            why="a blank path must be refused, not read from disk"),
    Control("/api/clips/video", "GET", CALL, "clip playback", "clips",
            query="path=", status=(400, 403, 404), expect=_dict,
            why="path traversal guard: outside the clips dir is refused"),
    Control("/api/clips/sound", "GET", CALL, "sound preview", "clips",
            query="path=", status=(400, 403, 404), expect=_dict,
            why="same guard against the sounds dir"),
    # Environment-dependent on purpose. With no voice model on the machine
    # this is a 400 saying so; with Kokoro installed a blank name falls back
    # to the default voice and returns real audio. Pinning either one made the
    # row pass alone and fail in the full suite, because an earlier test warms
    # the model up -- so the row asserts the two shapes instead of the state.
    Control("/api/clips/voice_sample", "GET", CALL, "audition a voice",
            "clips", query="name=&line=", status=(200, 400),
            expect_resp=lambda r: (
                r.status == 200 and r.body[:4] == b"RIFF"
                or r.status == 400 and (r.json() or {}).get("error")),
            why="either real WAV audio or a refusal, never a half-answer"),
    Control("/api/clips/probe", "POST", CALL, "probe a picked file", "clips",
            body={"path": ""}, expect=_dict,
            why="documented never to error; answers about a missing file"),
    Control("/api/clips/window", "POST", CALL, "scan window preview", "clips",
            body={"path": "", "start": 0, "end": 0}, expect=_dict,
            acts=("way",), why="async; the answer is a handle, not the work"),
    Control("/api/clips/preview", "POST", CALL, "Preview (plan only)",
            "clips", body={"source": "", "recording_path": ""}, expect=_dict,
            acts=("reveal",),
            why="the server forces plan_only, so nothing is encoded"),
    Control("/api/clips/run", "POST", CALL, "Cut clips", "clips",
            body={"source": "", "recording_path": "", "plan_only": True},
            expect=_dict,
            why="plan_only in the body; a blank source is refused up front"),
    Control("/api/clips/cancel", "POST", CALL, "Cancel", "clips", body={},
            expect=_dict, acts=("cancel",),
            why="cooperative; answers even when nothing is running"),
    Control("/api/clips/edit", "POST", CALL, "re-render one clip", "clips",
            body={}, expect=_dict,
            why="refuses without a clip to edit rather than encoding"),
    Control("/api/clips/setgame", "POST", CALL, "correct the game", "clips",
            body={"recording_path": "", "game": "VALORANT",
                  "game_key": "valorant-win64-shipping.exe"},
            expect=_dict, reject={"game": ""}, acts=("setgame",),
            why="writes the correction into history"),
    Control("/api/clips/setname", "POST", CALL, "in-game name", "clips",
            body={}, expect=_dict, acts=("save-name",),
            why="persists to games.yaml so it is asked once, not per scan"),
    Control("/api/clips/forget", "POST", CALL, "Forget missing recordings",
            "clips", body={"recording_path": "", "session": -1,
                           "missing_only": True},
            expect=_dict, acts=("strip-all",),
            why="had no caller at all until the button was added"),
    Control("/api/clips/demos", "POST", CALL, "paste share codes", "clips",
            body={"text": ""}, expect=_dict,
            acts=("get-demos", "needsdemo-get"),
            why="parses codes into steam:// links; no download here"),
    Control("/api/clips/calibrate", "POST", CALL, "Calibrate a game", "clips",
            body={}, expect=_dict, acts=("calibrate",),
            why="refuses a template that matches everything"),
    Control("/api/clips/cards/samples", "POST", CALL, "CS2 card samples",
            "clips", body={}, expect=_dict, acts=("demo-cards",),
            why="candidate frames for the kill-tally calibration"),
    Control("/api/clips/cards/check", "POST", CALL, "CS2 card check", "clips",
            body={}, expect=_dict, acts=("cal-check",),
            why="a verdict before a six-minute scan, not after"),
    Control("/api/clips/upload", "POST", CALL, "Upload to YouTube", "clips",
            body={"clips": [], "folder": ""}, expect=_dict, acts=("upload",),
            why="refuses an empty selection; never uploads by itself"),
    Control("/api/clips/upload/cancel", "POST", CALL, "Stop uploading",
            "clips", body={}, expect=_has("ok"), acts=("upload-cancel",),
            why="answers ok:false when nothing is uploading"),
    # Called with a path that cannot exist, never a blank one. Path("") is
    # Path("."), which exists, so a blank path used to spawn an Explorer
    # window on the working directory -- this suite opened the repo folder
    # several times a run before that was fixed. The guard is what is under
    # test; opening a window is the thing to avoid while testing it.
    Control("/api/clips/open", "POST", CALL, "Reveal in Explorer", "clips",
            body={"path": r"C:\verify\no\such\folder\clip.mp4"},
            expect=_has("error"), acts=("reveal-src", "reveal-out"),
            why="a path that is not there is refused before Explorer is spawned"),
    Control("/api/clips/pick", "POST", STATIC, "Pick a local file", "clips",
            acts=("pick-local", "use-local"),
            why="opens a native Tk dialog ON THE SERVER and blocks the "
                "request thread until a human dismisses it"),
    Control("/api/clips/install", "POST", STATIC, "Install them", "clips",
            why="runs winget and raises a UAC prompt"),

    # ------------------------------------------------------------ update
    Control("/api/update/check", "GET", STATIC, "Check for updates",
            "settings", acts=("set-ver-check",),
            why="reaches GitHub; tests must not need the network"),
    Control("/api/update/download", "POST", STATIC, "Download", "settings",
            acts=("set-ver-get",), why="downloads a release asset"),
    Control("/api/update/install", "POST", STATIC, "Open the installer",
            "settings", acts=("set-ver-open",),
            why="launches the installer and quits the running app"),

    # ------------------------------------------------------------- setup
    Control("/api/setup/client_secret", "POST", CALL, "paste client secret",
            "setup", body={"json": ""}, expect=_dict,
            why="validated as JSON before it is written to secrets/"),
    Control("/api/setup/auth", "POST", STATIC, "Sign in with Google", "setup",
            why="opens a browser and blocks on an OAuth round trip"),
    Control("/api/setup/obs_detect", "POST", CALL, "Detect OBS", "setup",
            body={}, expect=_dict,
            why="reads the OBS profile off disk; does not connect"),
    Control("/api/setup/obs_test", "POST", STATIC, "Test", "setup",
            why="opens a websocket to OBS"),
    Control("/api/setup/save", "POST", CALL, "save a wizard step", "setup",
            body={"section": "timing", "values": {}}, expect=_dict,
            why="one section at a time, unlike /api/settings/save"),
    Control("/api/setup/scan", "POST", CALL, "Scan for games", "setup",
            body={}, expect=_dict, why="disk only"),
    Control("/api/setup/apps", "POST", CALL, "choose which stream", "setup",
            body={"apps": []}, expect=_dict, why="writes apps.yaml"),
    Control("/api/setup/finish", "POST", CALL, "Finish", "setup", body={},
            expect=_dict, acts=("finish",),
            why="flips is_configured mid-request; it once killed the socket"),
    Control("/api/setup/clips_only", "POST", CALL, "Just clips", "setup",
            body={}, expect=_dict,
            why="the supported route into youtube.enabled=false"),
    Control("/api/setup/webview2", "POST", CALL, "check WebView2", "setup",
            body={}, expect=_dict, why="registry read; no install"),
    Control("/api/setup/webview2/install", "POST", STATIC,
            "install WebView2", "setup",
            why="downloads and runs the Edge runtime installer"),
]

BY_PATH: dict[str, Control] = {c.path: c for c in CONTROLS}

# Every /api/cmd verb the whitelist accepts. Driven separately from the row
# above because the whitelist is the security boundary on the engine, and a
# verb quietly added to it should be a deliberate decision.
COMMANDS = ("stop", "pause", "resume", "toggle_pause", "record", "quit")

# Names that reach engine.submit() by other doors and must NOT be accepted
# here: `kill` is the global hotkey only, and `launch`/`chat` have their own
# routes that validate a payload first.
COMMANDS_REFUSED = ("kill", "launch", "chat", "", "QUIT", "stop; rm -rf")

# Controls that are real, and are deliberately not HTTP calls. Each is either
# handled entirely in the browser or is a plain link.
NOT_A_FLOW: dict[str, str] = {
    # --- navigation and layout
    "rail-btn": "client-side page switch; state lives in sessionStorage",
    "rail": "switches the Clips page sub-tab",
    "back": "steps the setup wizard backwards; no state leaves the browser",
    "pick": "selects a session row in the Clips list",
    # --- plain links and the clipboard
    "dash-btn-open": "a plain <a href> to the YouTube watch URL",
    "set-diag-copy": "clipboard only",
    "copy": "copies the diagnostics text to the clipboard",
    # --- graph controls
    "dash-stat-viewers-btn": "picks which metric the graph draws",
    "dash-stat-likes-btn": "picks which metric the graph draws",
    "dash-stat-views-btn": "picks which metric the graph draws",
    # --- Settings field widgets. Every one of these edits the dirty set and
    # nothing more: Save is the only thing on the page that posts, which is
    # what makes a half-applied settings change impossible.
    "toggle": "flips a boolean field into the dirty set",
    "tag-x": "removes one tag from a list field",
    "clear-time": "clears a quiet-hours time field",
    "set-discard": "drops the dirty set; never reaches the server",
    "log-filters": "client-side level filter over rows already fetched",
    # --- Clips run options, collected and sent later as part of the run body
    "montage": "toggles montage for the next /api/clips/run",
    "demo-anyway": "sets demo_fallback on the next /api/clips/run",
    "cal-reset": "clears the calibration box in the browser",
    "cal-close": "closes the calibration panel",
}
