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
            status=(409,), expect=_has("error"), reject={"key": ""},
            why="an app that is not in the Library is refused before anything "
                "is queued, so the page can say so instead of toasting success"),
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
            query="folder=", acts=("songedit",), expect=lambda j: isinstance(j, (dict, list)),
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
            acts=("studio-preview", "studio-watch"),
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
    Control("/api/clips/valorant/fetch", "POST", STATIC,
            "Fetch match records now", "clips", acts=("fetch-matches",),
            why="reads the running Riot Client and calls Riot; no network "
                "in tests, so it is covered in test_valorant_match.py"),
    Control("/api/clips/valorant/explained", "POST", CALL,
            "Got it (match record notice)", "dashboard", body={}, expect=_has("ok"),
            acts=("dash-vmatch-ok",),
            why="one flag in games.yaml; the notice never shows again"),
    Control("/api/clips/calibrate", "POST", CALL, "Calibrate a game", "clips",
            body={}, expect=_dict, acts=("calibrate",),
            why="refuses a template that matches everything"),
    Control("/api/clips/cards/samples", "POST", CALL, "CS2 card samples",
            "clips", body={}, expect=_dict,
            acts=("demo-cards", "cards-open"),
            why="candidate frames for the kill-tally calibration. cards-open "
                "is the explicit button beside the reader choice; the panel "
                "used to open only by itself, so there was nothing to press "
                "when it was not on the page"),
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
            expect=_has("error"), acts=("reveal-src", "reveal-out", "studio-show"),
            why="a path that is not there is refused before Explorer is spawned"),
    Control("/api/clips/pick", "POST", STATIC, "Pick a local file", "clips",
            acts=("pick-local", "use-local", "reel-quick-song", "studio-song",
                  "studio-sg-pick", "studio-intro-add", "studio-imp-add", "studio-fc-attach"),
            why="opens a native Tk dialog ON THE SERVER and blocks the "
                "request thread until a human dismisses it"),
    Control("/api/clips/install", "POST", STATIC, "Install them", "clips",
            why="runs winget and raises a UAC prompt"),

    # ------------------------------------------------------------- reels
    # Every one of these answers 200 with ok:false rather than an HTTP error,
    # because each is a step in a five-step card: the page has to render the
    # reason beside the step the user is standing on, not replace the card
    # with an error.
    Control("/api/reel/song", "POST", CALL, "analyse the chosen song", "clips",
            body={"song": ""}, expect=_has("ok"),
            reject={"song": r"C:\verify\no\such\song.flac"}, reject_soft=True,
            acts=("reel-song",),
            why="tempo, phase, downbeat and the drum entry come from here; "
                "the page draws the whole grid off this one answer"),
    Control("/api/reel/plan", "POST", CALL, "where every kill would land",
            "clips", body={"song": "", "kills": []}, expect=_has("ok"),
            reject={"song": "", "kills": []}, reject_soft=True,
            acts=("reel-tpl", "reel-usemarks"),
            why="the same arithmetic the render uses, so the preview cannot "
                "disagree with the reel; no kills chosen is refused here "
                "rather than after an encode"),
    Control("/api/reel/run", "POST", CALL, "Make the reel", "clips",
            body={"song": "", "kills": [], "source": ""}, expect=_has("ok"),
            reject={"song": "", "kills": [], "source": ""}, reject_soft=True,
            acts=("reel-build", "reel-quick-again"),
            why="queues the encode; a missing recording is refused before "
                "ffmpeg is spawned"),
    Control("/api/reel/audio", "GET", STATIC, "the song, for the mark page",
            "clips",
            why="A WHITELIST OF EXACTLY ONE FILE -- the song this process has "
                "already analysed, because the song is chosen through the OS "
                "dialog and so cannot be root-confined like every other media "
                "route. With no song chosen that whitelist is empty, so the "
                "only honest answer to any path is 404 -- which is also what "
                "an unwired route answers. Calling it here could not tell the "
                "two apart, so its existence is asserted from the source"),

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
    Control("/api/setup/auth_link", "POST", CALL, "the sign-in link", "setup",
            body={}, expect=_has("ok", "url", "waiting"),
            why="polled while the sign-in waits, so the link can be shown"),
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
    # ------------------------------------------------------------- studio
    # Every clip on disk, and reels built from any of them on a timeline.
    Control("/api/studio/library", "GET", CALL, "every clip, by game and run", "studio",
            expect=_has("ok", "games", "clip_count"), acts=("studio-refresh",),
            why="read from each run's clips.json; an empty clips folder is an "
                "empty list, not an error"),
    Control("/api/studio/catalog", "GET", CALL, "parts and styles", "studio",
            expect=_has("parts", "styles", "default_style"),
            why="the page offers every choice from this one answer, and each "
                "style carries the reference measurements it is built on"),
    Control("/api/studio/job", "GET", CALL, "render progress", "studio",
            expect=_has("state"),
            why="idle when nothing has rendered in this process"),
    Control("/api/studio/project", "GET", CALL, "open a reel's timeline", "studio",
            query="path=", expect=_has("ok"), acts=("studio-open",),
            why="a blank path is refused with ok:false; a reel outside the "
                "reels folder is refused the same way"),
    Control("/api/studio/songs", "GET", CALL, "songs already downloaded", "studio",
            expect=_has("ok", "songs"), acts=("studio-sg-song",),
            why="what the song picker lists, so a song can be chosen without a "
                "file dialog; an empty songs folder is an empty list"),
    Control("/api/studio/intros", "GET", CALL, "intro clips already added", "studio",
            expect=_has("ok", "intros"), acts=("studio-intro-open", "studio-intro-pick"),
            why="the intro library the dialog lists, so a clip added once can be "
                "reused on every reel; an empty intros folder is an empty list"),
    Control("/api/studio/intro", "GET", CALL, "preview an intro clip", "studio",
            query="path=", status=(403, 404), expect=_has("error"),
            why="streams one intro so it can be trimmed by eye; only ever an mp4 "
                "inside the intros folder, so a blank path is refused"),
    Control("/api/studio/intro-add", "POST", CALL, "Add a GIF or video", "studio",
            body={"path": ""}, expect=_has("ok"),
            reject={"path": ""}, reject_soft=True,
            why="no file chosen is refused; the path comes from the OS dialog, and "
                "the file is re-encoded into the intros folder before it is used"),
    Control("/api/studio/intro-delete", "POST", CALL, "Delete an intro clip", "studio",
            body={"path": ""}, expect=_has("ok"),
            reject={"path": ""}, reject_soft=True,
            acts=("studio-intro-del",),
            why="only a file inside the intros folder can be deleted, and not while "
                "a reel is rendering"),
    Control("/api/studio/songview", "GET", CALL, "ways of seeing a song", "studio",
            query="song=", expect=_has("ok"),
            why="loudness, the three bands, onset strength and a spectrogram, "
                "with the kills the detector would cut to; only ever a file in "
                "the songs folder"),
    Control("/api/studio/songview.bin", "GET", CALL, "the lanes themselves", "studio",
            query="song=", status=(400,), expect=_has("error"),
            why="the bytes the page draws from; a song outside the songs "
                "folder is refused"),
    Control("/api/studio/favourite", "POST", CALL, "star a clip", "studio",
            body={"paths": []}, expect=_has("ok"),
            acts=("studio-fav", "studio-fav-selected"),
            why="a star is kept by clip id in the clips folder's own cache, so "
                "it survives a run being cut again; no paths is refused"),
    Control("/api/studio/examples", "GET", CALL, "the parts bin", "studio",
            expect=_has("ok", "examples", "missing"),
            why="every part the reel maker can use, and the example cut for it "
                "from this machine's own clips; a fresh install has none yet"),
    Control("/api/studio/example", "GET", CALL, "one part's example", "studio",
            query="id=", status=(400,), expect=_has("error"),
            why="only ever a file in the examples folder, named after a part "
                "the catalog knows; anything else is refused"),
    Control("/api/studio/import", "POST", CALL, "Add your own clip", "studio",
            body={"path": ""}, expect=_has("ok"),
            reject={"path": ""}, reject_soft=True,
            why="a file the player already has becomes a clip; the path comes from "
                "the OS dialog and anything that is not a video is refused"),
    Control("/api/studio/import/info", "POST", CALL, "open an added clip", "studio",
            body={"path": ""}, expect=_has("ok"), acts=("studio-imp-edit",),
            why="only a clip in an import- folder of the clips folder; anything "
                "else is refused"),
    Control("/api/studio/import/save", "POST", CALL, "save its kills and title", "studio",
            body={"path": "", "kills": []}, expect=_has("ok"), acts=("studio-imp-save",),
            why="only an added clip's own manifest is written, with its kills "
                "clamped to the clip"),
    Control("/api/studio/import/detect", "POST", CALL, "find the kills in an added clip", "studio",
            body={"path": ""}, expect=_has("state"), acts=("studio-imp-detect",),
            why="runs the chosen game's detector on its own thread; a path that "
                "is not an added clip fails at once"),
    Control("/api/studio/import/detect/status", "GET", CALL, "how the detection is going", "studio",
            expect=_has("state"),
            why="what the dialog polls while the detector reads the clip"),
    Control("/api/studio/import/detect/cancel", "POST", CALL, "stop finding kills", "studio",
            body={}, expect=_has("state"), acts=("studio-imp-close",),
            why="closing the dialog stops a detection it started"),
    Control("/api/studio/facecam", "GET", CALL, "the facecam links", "studio",
            expect=_has("ok", "links"),
            why="which sessions have a camera video and the box last drawn "
                "round an in-video camera"),
    Control("/api/studio/facecam/video", "GET", CALL, "play a camera video", "studio",
            query="path=", status=(403,), expect=_has("error"),
            why="only a file a facecam link names -- each written from the OS "
                "dialog -- so a blank or arbitrary path is refused"),
    Control("/api/studio/facecam/link", "POST", CALL, "attach a camera video", "studio",
            body={"key": "", "path": ""}, expect=_has("ok"),
            why="only a video file can be linked, and only to a named session"),
    Control("/api/studio/facecam/offset", "POST", CALL, "line the camera up", "studio",
            body={"key": "", "offset": 0}, expect=_has("ok"), acts=("studio-fc-nudge",),
            why="a key with no link is refused"),
    Control("/api/studio/facecam/unlink", "POST", CALL, "detach a camera video", "studio",
            body={"key": "verify-no-such-run"}, expect=_has("ok"), acts=("studio-fc-unlink",),
            why="removing a link that is not there changes nothing"),
    Control("/api/studio/facecam/inset", "POST", CALL, "remember the camera box", "studio",
            body={"box": [0.7, 0.0, 0.3, 0.3]}, expect=_has("ok", "inset"),
            why="the box is clamped inside the frame and kept for the next reel"),
    Control("/api/studio/facecam/sync", "POST", CALL, "line up by sound", "studio",
            body={"key": "", "clip": ""}, expect=_has("ok"), acts=("studio-fc-sync",),
            why="nothing to line up without a link and a clip in the clips folder"),
    Control("/api/studio/examples/build", "POST", CALL, "cut the examples again", "studio",
            body={}, expect=_has("ok", "build"), acts=("studio-bin-build",),
            why="renders the missing examples from the player's own clips in "
                "the background, so the page can watch it"),
    Control("/api/studio/examples/cancel", "POST", CALL, "stop cutting examples", "studio",
            body={}, expect=_has("ok", "build"), acts=("studio-bin-stop",),
            why="a few hundred examples is most of an hour; it stops after "
                "the part being cut"),
    Control("/api/studio/favourite-part", "POST", CALL, "star a part of the bin", "studio",
            body={"part": "", "on": True}, expect=_has("error"),
            acts=("studio-bin-fav",),
            why="with a hundred parts in a drawer the ones worth coming back to "
                "have to be findable; an unknown id is refused rather than stored"),
    Control("/api/studio/thumb", "GET", CALL, "library thumbnail", "studio",
            query="path=", status=(400,), expect=_has("error"),
            why="only ever a clip inside the clips folder; a blank path must "
                "not reach ffmpeg"),
    Control("/api/studio/plan", "POST", CALL, "Build and render", "studio",
            body={"clips": []}, expect=_has("ok"),
            reject={"clips": []}, reject_soft=True,
            acts=("studio-build", "studio-restyle"),
            why="no clips chosen is refused here, before a song is analysed"),
    Control("/api/studio/check", "POST", CALL, "apply a timeline edit", "studio",
            body={"project": None}, expect=_has("ok"),
            reject={"project": None}, reject_soft=True,
            acts=("studio-beats", "studio-move", "studio-remove", "studio-slip",
                  "studio-offset", "studio-rfmt", "studio-undo", "studio-fx-all",
                  "studio-tr-all"),
            why="every edit is clamped and re-derived by the server, so the page "
                "and the render can never disagree about where a kill lands"),
    Control("/api/studio/vary", "POST", CALL, "Mix kill effects / transitions", "studio",
            body={"project": None}, expect=_has("ok"),
            reject={"project": None}, reject_soft=True, acts=("studio-mix",),
            why="re-draws each shot's effects from the reel's pools without "
                "moving a cut; a project that is not one is refused"),
    Control("/api/studio/song", "POST", CALL, "Use this part", "studio",
            body={"project": None}, expect=_has("ok"),
            reject={"project": None}, reject_soft=True,
            acts=("studio-sg-apply", "studio-sg-none"),
            why="the song, the part of it and the kill marks are applied by the "
                "server, which re-times the cuts against what the footage allows"),
    Control("/api/studio/render", "POST", CALL, "Render", "studio",
            body={"project": None}, expect=_has("ok"),
            reject={"project": None}, reject_soft=True, acts=("studio-render",),
            why="a project with no usable clips is refused before ffmpeg starts"),
    Control("/api/studio/cancel", "POST", CALL, "Cancel the render", "studio",
            body={}, expect=_has("ok"), acts=("studio-cancel",),
            why="ok:false when nothing is rendering"),
    Control("/api/studio/songfetch", "POST", CALL, "Download a song from a YouTube link", "studio",
            body={"url": ""}, expect=_has("ok"),
            reject={"url": "https://example.com/not-youtube"}, reject_soft=True,
            acts=("studio-yt-go",),
            why="the link is checked before anything is fetched: a link that is not a "
                "YouTube video, or a playlist, is refused with what to paste instead"),
    Control("/api/studio/songfetch/status", "GET", CALL, "song download progress", "studio",
            expect=_has("ok", "fetch"),
            why="polled by the download dialog for its progress bar and its error"),
    Control("/api/studio/songfetch/cancel", "POST", CALL, "Stop the song download", "studio",
            body={}, expect=_has("ok"), acts=("studio-yt-close",),
            why="ok:false when nothing is downloading"),
    Control("/api/studio/delete", "POST", CALL, "Delete clips", "studio",
            body={"paths": []}, expect=_has("ok"),
            reject={"paths": []}, reject_soft=True,
            acts=("studio-delete", "studio-del-go"),
            why="no clips chosen is refused; only clips a run's clips.json lists "
                "can be deleted, dry_run says what would go, and a real delete is "
                "refused while a render, a clip job or an edit may be reading them"),
    Control("/api/studio/reel-delete", "POST", CALL, "Delete a reel", "studio",
            body={"paths": []}, expect=_has("ok"),
            reject={"paths": []}, reject_soft=True,
            acts=("studio-reel-del", "studio-rdel-go"),
            why="no reel chosen is refused; only an mp4 the reels folder lists can "
                "be deleted -- with its .reel.json and any part a dead render left "
                "-- the clips it was made from are never touched, dry_run says what "
                "would go, and a real delete is refused while a reel is rendering"),
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
    # --- the Studio page: selection, layout and the timeline's own view
    "studio-tab": "switches between the clip library and the timeline",
    "studio-game": "filters the library to one game",
    "studio-pick": "selects or unselects a clip (shift selects a range)",
    "studio-folder": "selects or unselects every clip in a run",
    "studio-clear": "empties the selection",
    "studio-make": "opens the make-a-reel dialog",
    "studio-make-cancel": "closes the make-a-reel dialog",
    "studio-preview-close": "closes the clip preview",
    "studio-style": "chooses a style in the dialog; sent with Build",
    "studio-bin-pick": "puts one part of the bin in the template; sent with Build",
    "studio-bin-favonly": "shows only the parts kept as favourites; never leaves the browser",
    "studio-shape": "nudges one of the shaping dials; sent with the next Build",
    "studio-shape-reset": "puts every shaping dial back to what the style measured",
    "studio-arrange": "chooses how the reel is ordered; sent with the next Build",
    "studio-pin": "pins a clip to the opener, the climax or the closer; sent with the next Build",
    "studio-hand-next": "steps a drawer of the dealt template to its next part",
    "studio-deal": "deals a random part from every drawer; sent with Build",
    "studio-deal-reset": "drops the dealt parts back to the style's own",
    "studio-bin-slot": "ticks a drawer in and out of the how-many-reels count",
    "studio-sg-win": "zooms the song's lanes",
    "studio-sg-lane": "shows or hides one way of seeing the song",
    "studio-nosong": "clears the chosen song in the dialog",
    "studio-fmt": "chooses landscape or vertical in the dialog; sent with Build",
    "studio-order": "chooses the clip order in the dialog; sent with Build",
    "studio-play": "plays or pauses the rendered reel",
    "studio-zoom": "zooms the timeline",
    "studio-seek": "moves the playhead of the rendered reel",
    "studio-select": "selects a shot, or the reel, in the inspector",
    "studio-edit-song": "opens the Song tab",
    "studio-sg-play": "plays or pauses the chosen part of the song",
    "studio-sg-mark": "adds a kill mark at the playhead; sent with Use this part",
    "studio-sg-fromkills": "fills the marks from where this reel's kills already are",
    "studio-sg-marknudge": "moves the chosen mark by half a beat or a beat",
    "studio-sg-markplay": "plays the bar the chosen mark sits in",
    "studio-sg-markdrop": "removes the chosen mark",
    "studio-sg-unmark": "removes the last kill mark",
    "studio-sg-clearmarks": "removes every kill mark",
    "studio-sg-nudge": "moves the part's start or end by a bar, a beat or 10 ms",
    "studio-sg-snapbar": "moves the part's start onto the nearest bar",
    "studio-sg-atdrop": "moves the part so it builds into the song's drop",
    "studio-sg-fit": "sets the part's end to the timeline's length",
    "studio-mk-mode": "chooses the part of the song or lets the planner choose; sent with Build",
    "studio-mk-nudge": "moves the chosen part's start or end by a bar; sent with Build",
    "studio-mk-preset": "moves the chosen part to the drums, into the drop, or to the whole song; sent with Build",
    "studio-mk-play": "plays or pauses the chosen part of the song in the dialog",
    "studio-mk-skip": "moves playback of the part back or forward five seconds",
    "studio-mk-restart": "moves playback to the start of the chosen part",
    "studio-yt": "opens the dialog for downloading a song from a YouTube link",
    "studio-add": "goes back to the library with the reel's clips selected, to add more and rebuild",
    "studio-add-cancel": "stops adding clips to a reel and empties the selection",
    "studio-del-cancel": "closes the delete confirmation without deleting",
    "studio-rdel-cancel": "closes the delete-a-reel confirmation without deleting",
    # --- the intro-clip dialog: everything here edits studio.intro, and only
    # "Use this intro" puts any of it on the project (which renders it).
    "studio-intro-off": "takes the intro clip off the reel",
    # --- the facecam tab and the added-clip dialog: page state until an edit
    # reaches the project (which renders it) or a save reaches the server.
    "studio-cam-src": "chooses where the facecam comes from; an edit to the project",
    "studio-tab-go": "switches the Studio's tab",
    "studio-fc-frame": "steps the frame the camera box is drawn on",
    "studio-fc-boxreset": "clears the camera box; an edit to the project",
    "studio-fc-lineup": "loads a session's game and camera side by side",
    "studio-fc-play": "plays the game and the camera together",
    "studio-imp-play": "plays or pauses the added clip in its dialog",
    "studio-imp-step": "steps the added clip by a frame or a second",
    "studio-imp-mark": "marks a kill at the playhead; saved with Save",
    "studio-imp-clear": "removes every marked kill; saved with Save",
    "studio-imp-drop": "removes one marked kill; saved with Save",
    "studio-imp-seek": "moves the playhead to a marked kill",
    "studio-imp-preset": "fills the title with a preset; saved with Save",
    "studio-intro-use": "puts the trimmed intro on the reel",
    "studio-intro-clear": "takes the intro clip off from inside the dialog",
    "studio-intro-cancel": "closes the intro dialog, changing nothing",
    "studio-intro-play": "plays the trimmed part of the intro in the dialog",
    "studio-intro-nudge": "moves the intro's in or out point by a step",
    "studio-intro-here": "sets the in or out point to the preview's playhead",
    "studio-intro-whole": "trims the intro back to the whole clip",
    "studio-intro-fit-lead": "trims the intro to the length of the reel's lead-in",
    "studio-intro-fit": "chooses whether the intro fills the frame or fits inside it",
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
    # --- the reel card. Opening it, picking moments and tapping a beat are
    # all local: nothing is sent until Make the reel, which is what lets a
    # person try four templates and re-tap the grid without queueing an
    # encode each time.
    "reel-open": "opens the reel card over the Clips page",
    "reel-close": "closes it; no state leaves the browser",
    "reel-all": "ticks every moment in the picker",
    "reel-none": "unticks every moment in the picker",
    "reel-best": "ticks the multi-kills and aces only",
    "reel-mark": "opens the tap-the-beat panel",
    "reel-tap": "records one tap against the playing song",
    "reel-play": "plays and pauses the song being marked",
    "reel-back": "steps the song back a second",
    "reel-fwd": "steps the song on a second",
    "reel-untap": "drops the last tap",
    "reel-clearmarks": "drops every tap",
    "reel-seedmarks": "fills the taps from the template, to correct rather "
                      "than start from nothing",
    "reel-show": "reveals the finished file in Explorer via clip_reveal",
    "reel-again": "returns the card to the moment picker for another take",
    # --- the straight path from the finished clips. The song edit is made
    # without asking anything, so the only choices left are about the song
    # itself, and both are answered in the browser until Make it again.
    "reel-quick-fix": "shows the part picker and the beat marker; nothing is "
                      "sent until Make it again",
    "reel-quick-love": "accepts the edit as it is; the file is already on disk",
}
