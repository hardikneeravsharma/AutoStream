"""Web UI server: themed dashboard + first-run setup wizard.

Replaces the old web.py. Serves one page that switches between "setup" and
"dashboard" depending on whether the app is configured.

Threading: runs on a daemon thread. Control actions post to engine.submit() and
are executed on the engine thread. Setup actions run inline on the request
thread — the engine is not running yet during setup, so there is nothing to
race with.

SECURITY: plain HTTP on the LAN with a token in the URL. Fine for a home
network, nothing more. Do not port-forward it.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import cfg, paths, schema, theme, ui_assets

log = logging.getLogger("autostream.webui")

# Mirrors setup_logging()'s formatter in __main__.py:
#   "%(asctime)s %(levelname)-7s %(name)-18s %(message)s"  /  "%Y-%m-%d %H:%M:%S"
_LOG_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) +([A-Z]+) +(\S+) +(.*)$")

_TAIL_MAX = 2000        # a page cannot usefully render more, and the JSON is capped with it
_TAIL_CHUNK = 65536


def is_configured() -> bool:
    """Setup is done when we have a token AND a permanent stream.

    ...unless streaming is off, in which case there is nothing to sign in to
    and nothing to bind. Sending a clips-only user through a Google OAuth flow
    to reach a page that cuts video files locally is the kind of thing that
    makes people close the app.
    """
    try:
        c = cfg.load()
        if not getattr(c.youtube, "enabled", True):
            return True
        return bool(c.youtube.stream_id) and paths.TOKEN_FILE.exists()
    except Exception:  # noqa: BLE001
        return False


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _int(value, fallback: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _float(value, fallback: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def tail_lines(path, n: int) -> list[str]:
    """Last `n` lines of a file, read by seeking from the end.

    The log rotates at midnight but a chatty day still runs to megabytes, and
    the Logs page polls this — read_text() would pull the whole file into
    memory on every request.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return []
    buf = b""
    pos = size
    try:
        with open(path, "rb") as f:
            # One extra line: the first one read is usually sliced mid-way.
            while pos > 0 and buf.count(b"\n") <= n:
                step = min(_TAIL_CHUNK, pos)
                pos -= step
                f.seek(pos)
                buf = f.read(step) + buf
    except OSError:
        return []
    lines = buf.decode("utf-8", "replace").splitlines()
    if pos > 0 and lines:
        lines = lines[1:]
    return lines[-n:]


def parse_log_line(line: str) -> dict:
    m = _LOG_LINE.match(line)
    if not m:
        # Tracebacks and bare prints are part of the story. Show them with no
        # level rather than dropping them; the UI styles level-less rows as
        # continuations of the record above.
        return {"ts": None, "level": None, "name": None, "msg": line}
    ts, level, name, msg = m.groups()
    return {"ts": ts, "level": level, "name": name, "msg": msg}


def page(theme_id: str) -> str:
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'>"
        f"<meta name='theme-color' content='{theme.get(theme_id)['vars']['bg']}'>"
        "<title>AutoStream</title><style>:root{\n"
        + theme.css_vars(theme_id)
        + "\n}\n" + ui_assets.CSS + "</style></head><body>"
        + ui_assets.BODY
        + "<script>" + ui_assets.JS + "</script></body></html>"
    )


# What each extension is served as. A browser will usually sniff it anyway,
# but an <audio> handed video/mp4 can refuse before it tries.
_CONTENT_TYPES = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".ogg": "audio/ogg", ".opus": "audio/ogg", ".flac": "audio/flac",
    ".aac": "audio/aac",
}


class _Handler(BaseHTTPRequestHandler):
    server_version = "AutoStream"
    protocol_version = "HTTP/1.1"

    def __init__(self, app, *args, **kwargs):
        self.app = app                  # the Server instance
        super().__init__(*args, **kwargs)

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    # ---------------- plumbing ----------------

    def _authed(self, query) -> bool:
        """Is the request carrying the right token?

        COMPARED AS BYTES, NOT TEXT. hmac.compare_digest raises TypeError on
        str arguments containing non-ASCII characters, so a URL with an accent
        or an emoji anywhere in ?k= did not come back 403 -- it raised inside
        the handler, dropped the connection with no response at all, and wrote
        a traceback. Anyone who could reach the port could do it by mistake.

        Encoding both sides first keeps the comparison constant-time and makes
        every wrong token, however written, an ordinary refusal.
        """
        given = (parse_qs(query).get("k") or [""])[0]
        return hmac.compare_digest(given.encode("utf-8", "surrogatepass"),
                                   self.app.token.encode("utf-8", "surrogatepass"))

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode())

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(min(n, 1 << 20)) or b"{}")
        except (ValueError, TypeError):
            return {}

    # ---------------- GET ----------------

    # Every request, tracked. cmd_run stops this server the moment setup
    # completes, and "the moment" used to include the two seconds in which the
    # response saying so was still being written -- see Server.idle_for.
    def handle_one_request(self):
        self.app.request_started()
        try:
            super().handle_one_request()
        finally:
            self.app.request_finished()

    def _video(self, path: str) -> None:
        """Stream one clip to a <video> tag."""
        self._media(path, self.app._clips_dir(cfg.load()),
                    (".mp4", ".m4v", ".webm"), "video")

    def _sound(self, path: str) -> None:
        """Stream one sound effect, so the effects preview can play it.

        Its own root and its own list of types. The alternative was letting
        _video serve the sounds folder too, which widens the thing that
        streams files to a second directory for the sake of one <audio> tag --
        and every widening of that is one more place to be careful about
        forever. A parameter costs nothing.
        """
        self._media(path, self.app.sounds_dir(cfg.load()),
                    self.app.SOUND_TYPES, "audio")

    def _media(self, path: str, root: Path, kinds, what: str) -> None:
        """Stream a file from `root` to a media tag, honouring Range.

        RANGE IS NOT OPTIONAL HERE. Without it the browser can play a clip from
        the start and nothing else: dragging the scrub bar, stepping a frame,
        or starting anywhere but zero all need a byte range, and a player that
        cannot seek is not a player. Chrome also re-requests the tail of an mp4
        to find the moov atom before it will play at all.

        RANGE IS NOT OPTIONAL HERE. Without it the browser can play a clip from
        the start and nothing else: dragging the scrub bar, stepping a frame,
        or starting anywhere but zero all need a byte range, and a player that
        cannot seek is not a player. Chrome also re-requests the tail of an mp4
        to find the moov atom before it will play at all.
        """
        p = Path(path)
        # Only ever inside the folder the caller named. The page builds these
        # paths, but the page is not the only thing that can call this.
        #
        # For clips, the RECORDINGS folder is deliberately not among them.
        # Adjusting where a clip starts needs footage either side of it, but
        # that arrives as a small preview cut into the run's own folder -- so
        # nothing here has to reach a 47 GB source file, and this guard stays
        # as narrow as it has always been.
        try:
            here = p.resolve()
            inside = here.is_relative_to(root.resolve())
        except OSError:
            self._json({"error": "No such file."}, 404)
            return
        if not inside:
            self._json({"error": f"That file is not in the {what} folder."}, 403)
            return
        if not p.is_file() or p.suffix.lower() not in kinds:
            self._json({"error": f"No such {what}."}, 404)
            return

        size = p.stat().st_size
        ctype = _CONTENT_TYPES.get(p.suffix.lower(),
                                   "video/mp4" if what == "video" else "audio/mpeg")
        rng = self.headers.get("Range", "")
        start, end = 0, size - 1
        partial = False
        if rng.startswith("bytes="):
            spec = rng[6:].split(",")[0].strip()
            lo, _, hi = spec.partition("-")
            try:
                if lo:
                    start = int(lo)
                    end = int(hi) if hi else size - 1
                elif hi:                      # "bytes=-500": the last 500
                    start = max(0, size - int(hi))
                partial = True
            except ValueError:
                partial = False
        if start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        end = min(end, size - 1)
        length = end - start + 1

        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        # A clip is rewritten in place when it is edited, so it must not be
        # cached: the player would keep showing the version before the edit.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            with p.open("rb") as fh:
                fh.seek(start)
                left = length
                while left > 0:
                    chunk = fh.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass          # the page seeked away or closed the player

    def do_GET(self):
        u = urlparse(self.path)
        if not self._authed(u.query):
            self._send(403, b"Add ?k=<token>. See the AutoStream log.",
                       "text/plain; charset=utf-8")
            return
        try:
            self._get(u)
        except Exception as e:  # noqa: BLE001 - never fail silently at the user
            # WITHOUT THIS A FAILING GET IS INVISIBLE. do_POST has logged its
            # failures since it was written; do_GET did not, so an exception
            # went to the base handler, which writes to a stderr a windowed
            # build does not have and then drops the connection. The browser
            # sees "connection closed" and the log says nothing at all.
            log.exception("GET %s failed: %s", u.path, e)
            try:
                self._json({"error": str(e)}, 500)
            except Exception:  # noqa: BLE001 - the socket is already gone
                pass

    def _get(self, u):
        if u.path in ("/", "/index.html"):
            self._send(200, page(self.app.theme_id()).encode("utf-8"),
                       "text/html; charset=utf-8")
        elif u.path == "/api/bootstrap":
            setup_mode = not is_configured()
            self._json({
                "mode": "setup" if setup_mode else "dash",
                "theme": self.app.theme_id(),
                "themes": theme.listing(),
                "setup": self.app.setup.snapshot() if setup_mode else {},
            })
        elif u.path == "/api/status":
            if self.app.engine is None:
                # No engine yet (setup, or a headless server) still has to
                # carry clip progress: a clip job runs on its own thread and
                # the Clips page reads it from here, engine or not.
                # `upload` rides along for the same reason, so the page reads
                # one payload shape whether or not an engine exists.
                self._json({"phase": "IDLE", "apps": self.app.apps_payload(),
                            "clips": self.app._clips_status(),
                            "edit": self.app._edit_status(),
                            "update": self.app.update_status(),
                            "upload": self.app._upload_status()})
                return
            self.app.engine.client_seen = time.monotonic()
            self._json(self.app.status())
        elif u.path == "/api/settings/schema":
            self._json(schema.CONFIG_SCHEMA)
        elif u.path == "/api/settings/values":
            self._json(schema.flatten(cfg.load()))
        elif u.path == "/api/logs/tail":
            n = _int((parse_qs(u.query).get("n") or [""])[0], 300)
            self._json({
                "lines": [parse_log_line(x)
                          for x in tail_lines(paths.LOG_FILE, max(1, min(n, _TAIL_MAX)))],
                "path": str(paths.LOG_FILE),
            })
        elif u.path == "/api/clips/tools":
            self._json(self.app.clips_tools())
        elif u.path == "/api/clips/games":
            self._json(self.app.clips_games())
        elif u.path == "/api/clips/sessions":
            self._json(self.app.clips_sessions())
        elif u.path == "/api/clips/video":
            q = parse_qs(u.query)
            self._video((q.get("path") or [""])[0])
        elif u.path == "/api/clips/existing":
            q = parse_qs(u.query)
            self._json(self.app.clips_existing((q.get("folder") or [""])[0]))
        elif u.path == "/api/clips/sound":
            self._sound((parse_qs(u.query).get("path") or [""])[0])
        elif u.path == "/api/clips/sounds":
            self._json(self.app.clips_sounds())
        elif u.path == "/api/clips/window-ready":
            self._json(self.app.clips_window_ready(
                (parse_qs(u.query).get("path") or [""])[0]))
        elif u.path == "/api/update/check":
            self._json(self.app.update_check())
        elif u.path == "/api/clips/voices":
            self._json(self.app.clips_voices())
        elif u.path == "/api/clips/voice_sample":
            q = parse_qs(u.query)
            wav, err = self.app.voice_sample(
                (q.get("name") or [""])[0], (q.get("line") or [""])[0])
            if err:
                self._json({"error": err}, 400)
            else:
                self._send(200, wav, "audio/wav")
        elif u.path == "/api/clips/frame":
            q = parse_qs(u.query)
            png, err = self.app.clip_frame(
                (q.get("path") or [""])[0], _float((q.get("t") or ["0"])[0], 0.0),
                _int((q.get("w") or ["0"])[0], 0))
            if err:
                self._json({"error": err}, 400)
            else:
                self._send(200, png, "image/png")
        else:
            self._json({"error": "not found"}, 404)

    # ---------------- POST ----------------

    def do_POST(self):
        u = urlparse(self.path)
        if not self._authed(u.query):
            self._json({"error": "forbidden"}, 403)
            return
        b = self._body()
        p = u.path

        try:
            if p == "/api/theme":
                t = str(b.get("theme", ""))
                if t not in theme.THEMES:
                    self._json({"error": "unknown theme"}, 400)
                    return
                cfg.save_field("ui", "theme", t)
                self.app._theme = t
                self._json({"ok": True})

            elif p == "/api/cmd":
                c = str(b.get("command", ""))
                if c not in ("stop", "pause", "resume", "toggle_pause",
                             "record", "quit"):
                    self._json({"error": "unknown command"}, 400)
                    return
                if c == "quit":
                    # Same order as the tray's Quit: tell the engine first, then
                    # the window (which owns the main thread and unblocks it).
                    if self.app.engine:
                        self.app.engine.request_stop()
                    if self.app.window:
                        self.app.window.request_quit("the Quit button in the app")
                elif self.app.engine:
                    self.app.engine.submit(c)
                self._json({"ok": True})

            elif p == "/api/chat":
                t = str(b.get("text", "")).strip()
                if not t:
                    self._json({"error": "empty"}, 400)
                    return
                if self.app.engine:
                    self.app.engine.submit(("chat", t[:200]))
                self._json({"ok": True})

            elif p == "/api/launch":
                key = str(b.get("key", ""))
                if not key:
                    self._json({"error": "no key"}, 400)
                    return
                if self.app.engine:
                    self.app.engine.submit(
                        ("launch", {"key": key, "stream": bool(b.get("stream"))}))
                self._json({"ok": True})

            elif p == "/api/apps/scan":
                # Re-scan from the dashboard. Needed whenever a new game is
                # installed - setup is not the only time the list can change.
                from . import catalog

                existing = {a.key: a for a in catalog.load()}
                found = catalog.discover_all()
                for a in found:
                    prev = existing.get(a.key)
                    if prev:                      # keep the user's choices
                        a.stream = prev.stream
                        a.scene = prev.scene
                        a.favourite = prev.favourite
                catalog.save(found)
                log.info("rescan found %d apps", len(found))
                self._json({"ok": True, "count": len(found),
                            "apps": self.app.apps_payload()})

            elif p == "/api/settings/save":
                res = self.app.save_settings(b.get("values"))
                # A rejected field is a normal answer the form must render, so
                # only a body with nothing usable in it is an HTTP error.
                self._json(res, 200 if (res["ok"] or res["errors"]) else 400)

            elif p == "/api/logs/open":
                try:
                    if os.name == "nt":
                        os.startfile(str(paths.LOG_FILE))  # noqa: S606
                    else:
                        import subprocess

                        subprocess.Popen(["xdg-open", str(paths.LOG_FILE)])
                    self._json({"ok": True})
                except OSError as e:
                    self._json({"error": str(e)}, 500)

            # ---------- clips ----------
            # Every one of these returns immediately. The actual work runs on a
            # worker thread and reports through /api/status, which the shell is
            # already polling - see clips/jobs.py.
            elif p == "/api/clips/window":
                self._json(self.app.clips_window(b))
            elif p == "/api/update/install":
                self._json(self.app.update_install())
            elif p == "/api/update/download":
                self._json(self.app.update_download())
            elif p == "/api/clips/edit":
                self._json(self.app.clips_edit(b))
            elif p == "/api/clips/preview":
                b["plan_only"] = True
                self._json(self.app.clips_run(b))
            elif p == "/api/clips/run":
                self._json(self.app.clips_run(b))
            elif p == "/api/clips/upload":
                self._json(self.app.clips_upload(b))
            elif p == "/api/clips/upload/cancel":
                from .clips import upload as up
                self._json({"ok": up.runner().cancel()})
            elif p == "/api/clips/cancel":
                self._json(self.app.clips_cancel())
            elif p == "/api/clips/open":
                self._json(self.app.reveal(str(b.get("path", ""))))
            elif p == "/api/clips/calibrate":
                self._json(self.app.clips_calibrate(b))
            elif p == "/api/clips/setgame":
                from . import history as _h
                from .clips import profiles as _pf

                name = str(b.get("game", "")).strip()
                key = str(b.get("game_key", "")).strip().lower()
                if not name:
                    self._json({"error": "no game given"}, 400)
                    return
                ok = _h.set_game(str(b.get("recording_path", "")), name, key)
                prof = _pf.for_game(key, name)
                self._json({"ok": ok, "profile": prof.label if prof else None}
                           if ok else {"error": "no matching session"})
            elif p == "/api/games/thumbnail":
                key = str(b.get("key", "")).strip().lower()
                path = str(b.get("path", "")).strip().strip('"')
                if not key:
                    self._json({"error": "no game given"}, 400)
                    return
                if path and not Path(path).is_file():
                    self._json({"error": f"no file at {path}"}, 400)
                    return
                ok = cfg.save_game_field(key, "thumbnail", path)
                self._json({"ok": ok, "path": path}
                           if ok else {"error": "could not save"})
            elif p == "/api/se/connect":
                from . import streamelements as se

                jwt = str(b.get("jwt", "")).strip()
                if not jwt:
                    self._json({"error": "no token given"}, 400)
                    return
                if not se.save_credentials(jwt, str(b.get("channel_id", "")),
                                           str(b.get("overlay_token", ""))):
                    self._json({"error": "That does not look like a "
                                         "StreamElements token."}, 400)
                    return
                self._json(se.listing())
            elif p == "/api/se/overlays":
                from . import streamelements as se

                if not se.available():
                    self._json({"error": "no token stored", "overlays": []})
                    return
                out = se.listing()
                out["suggest"] = se.suggest()
                out["expires_days"] = round(se.expires_in() / 86400)
                self._json(out)
            elif p == "/api/screens/build":
                self._json(self.app.build_screens())
            elif p == "/api/clips/forget":
                self._json(self.app.clips_forget(
                    str(b.get("recording_path", "")),
                    _int(b.get("session"), -1),
                    missing_only=bool(b.get("missing_only"))))

            # ---------- setup ----------
            elif p == "/api/setup/client_secret":
                self._json(self.app.setup.save_client_secret(str(b.get("json", ""))))
            elif p == "/api/setup/auth":
                self._json(self.app.setup.authorise())
            elif p == "/api/setup/obs_detect":
                self._json(self.app.setup.detect_obs())
            elif p == "/api/setup/webview2":
                self._json(self.app.setup.webview2())
            elif p == "/api/setup/webview2/install":
                self._json(self.app.setup.install_webview2())
            elif p == "/api/setup/obs_test":
                self._json(self.app.setup.test_obs(b))
            elif p == "/api/setup/save":
                self._json(self.app.setup.save_section(
                    str(b.get("section", "")), b.get("values") or {}))
            elif p == "/api/setup/clips_only":
                self._json(self.app.setup.clips_only())
            elif p == "/api/clips/demos":
                self._json(self.app.clips_demos(b))
            elif p == "/api/clips/setname":
                self._json(self.app.clips_setname(b))
            elif p == "/api/diagnostics":
                self._json(self.app.diagnostics())
            elif p == "/api/clips/pick":
                self._json(self.app.clips_pick())
            elif p == "/api/clips/probe":
                self._json(self.app.clips_probe(b))
            elif p == "/api/clips/install":
                self._json(self.app.clips_install(b))
            elif p == "/api/setup/scan":
                self._json(self.app.setup.scan())
            elif p == "/api/setup/apps":
                self._json(self.app.setup.save_apps(b.get("apps") or []))
            elif p == "/api/setup/finish":
                self._json(self.app.setup.finish())
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001 - never 500 silently at the user
            log.exception("POST %s failed: %s", p, e)
            self._json({"error": str(e)}, 500)


def _rec_seconds(row: dict) -> float:
    """How long a session's recording is, whatever the row calls it.

    THE KEY IS "recording_seconds". Two callers asked for "rec_seconds", which
    is the name of the LOCAL VARIABLE that produces it in history.py and not of
    the field -- so both silently got zero. For the Valorant match lookup that
    made the search window a hundred and eighty seconds wide instead of the
    length of the stream, so a match played twenty minutes in was reported as
    having no record at all.
    """
    for key in ("recording_seconds", "rec_seconds", "duration"):
        got = row.get(key)
        if got:
            try:
                return float(got)
            except (TypeError, ValueError):
                continue
    return 0.0


# Scrubbing previews are about nine megabytes each and are a means to an end,
# not a result. A handful is enough to move between clips without waiting; a
# folder of forty is just disk that nobody asked to spend.
KEEP_PREVIEWS = 8


def _trim_previews(where: Path, keep: int = KEEP_PREVIEWS) -> int:
    """Delete all but the `keep` newest previews. -> how many went."""
    try:
        found = sorted(where.glob("*.mp4"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
    except OSError:
        return 0
    gone = 0
    for old in found[keep:]:
        try:
            old.unlink()
            gone += 1
        except OSError:
            pass
    if gone:
        log.info("cleared %d old preview(s) from %s", gone, where.parent.name)
    return gone


class Server:
    def __init__(self, token: str, port: int = 8787, engine=None):
        self.token = token
        self.port = port
        self.engine = engine
        self.window = None            # set by cmd_run once the MainWindow exists
        self.httpd = None
        self._thread = None
        self._theme: str | None = None
        # See idle_for: the setup wizard's own success used to stop this
        # server while it was still answering the request that caused it.
        self._busy_lock = threading.Lock()
        self._in_flight = 0
        self._idle_since = time.monotonic()
        from .setup_flow import SetupFlow
        self.setup = SetupFlow()

    # ---------------- data ----------------

    def theme_id(self) -> str:
        if self._theme is None:
            try:
                self._theme = cfg.load().get("ui", {}).get("theme") or theme.DEFAULT
            except Exception:  # noqa: BLE001
                self._theme = theme.DEFAULT
        return self._theme

    def save_settings(self, values: Any) -> dict:
        """Validate every submitted path, then write once — or write nothing.

        All-or-nothing on purpose. A half-applied save leaves the daemon in a
        configuration the user never chose, and the form would show the
        rejected field beside its neighbours that did land.
        """
        out: dict[str, Any] = {"ok": False, "saved": [], "errors": {},
                               "restart_required": False}
        if not isinstance(values, dict) or not values:
            # _body() returns {} for malformed JSON, so an unparseable payload
            # would otherwise look like a successful save of nothing.
            out["error"] = "No settings were submitted."
            return out

        errors: dict[str, str] = {}
        clean: dict[str, Any] = {}
        for path, raw in values.items():
            key = str(path)
            field = schema.FIELDS_BY_PATH.get(key)
            if field is None:
                # The only gate between a POST body and config.yaml.
                errors[key] = "Unknown setting."
                continue
            if field.get("control") == "readonly":
                errors[key] = "AutoStream writes this value; it cannot be edited here."
                continue
            err = schema.validate(key, raw)
            if err:
                errors[key] = err
                continue
            clean[key] = schema.coerce(key, raw)
        if errors:
            out["errors"] = errors
            return out

        # config.yaml stays a sparse overlay on cfg.DEFAULTS: writing back a
        # value that already matches would pin it, so a later change to the
        # default would silently not reach anyone who ever pressed Save.
        current = schema.flatten(cfg.load())
        changed = {k: v for k, v in clean.items() if current.get(k) != v}
        if changed:
            cfg.save_fields(changed)

        out["ok"] = True
        out["saved"] = sorted(clean)
        out["restart_required"] = any(
            schema.FIELDS_BY_PATH[k].get("restart") for k in changed)
        # theme_id() caches; without this the next full page load paints the
        # old palette while /api/bootstrap reports the new id.
        self._theme = str(clean["ui.theme"]) if "ui.theme" in clean else None
        # Push the new values into the Config instance the daemon is holding.
        # Without this every non-`restart` field is inert until the process is
        # restarted, and the UI would be reporting a change that never happened.
        if self.engine is not None:
            try:
                cfg.refresh_in_place(self.engine.cfg)
            except Exception as e:  # noqa: BLE001 - the write already succeeded
                log.warning("saved, but could not reload the live config: %s", e)
                out["restart_required"] = True
        return out

    def apps_payload(self) -> list[dict]:
        from . import catalog

        # games.yaml, not the catalog: the thumbnail is a per-game SETTING and
        # the catalog is a list of what is installed. Read once per payload
        # rather than per row.
        try:
            games = cfg.load_games().get("games", {}) or {}
        except Exception:  # noqa: BLE001
            games = {}

        def thumb(key: str) -> str:
            row = games.get((key or "").lower())
            return str(row.get("thumbnail") or "") if isinstance(row, dict) else ""

        # THE EXE, NOT THE CATALOG KEY. games.yaml is keyed on the executable
        # because that is what the watcher sees running -- Counter-Strike is
        # `cs2.exe` there and `counter-strike-global-offensive` in the Steam
        # catalog. Saving under the wrong one writes a perfectly good entry
        # that nothing ever reads, and the mistake only shows up as a missing
        # thumbnail at go-live.
        return [
            {"key": a.key, "name": a.name, "source": a.source, "stream": a.stream,
             "game_key": (a.exe or a.key).lower(),
             "thumbnail": thumb(a.exe or a.key)}
            for a in catalog.load()
        ]

    def build_screens(self) -> dict:
        """Create or update the screen-saver scenes in OBS now.

        Exposed as a button because the alternative is building them at the
        moment of going live, where a failure would be discovered by the
        audience rather than by the user.
        """
        from . import screens

        c = cfg.load()
        if not c.screens.enabled:
            return {"error": "Screen savers are switched off."}
        gaps = screens.missing(c)
        if gaps:
            return {"error": "; ".join(gaps)}
        try:
            made = screens.ensure_all(c, self.engine.obs)
        except Exception as e:  # noqa: BLE001
            return {"error": f"OBS said no: {e}"}
        if not made:
            return {"error": "Nothing to build - no files are set."}
        return {"ok": True, "scenes": sorted(made.values())}

    def status(self) -> dict:
        e = self.engine
        s = e.state
        return {
            "phase": s.phase,
            "game": s.current_game,
            "paused": s.paused,
            "session": s.session_number,
            "quota_spent": s.quota_spent,
            "viewers": getattr(e, "viewers", None),
            "likes": getattr(e, "likes", None),
            "views": getattr(e, "views", None),
            "blocked": getattr(e, "blocked_reason", None),
            "obs": getattr(e, "obs_health", {}) or {},
            "chat": list(getattr(e, "chat", []))[-60:],
            "apps": self.apps_payload(),
            "elapsed": (int(time.time() - s.session_start) if s.session_start else None),
            "url": (f"https://www.youtube.com/watch?v={s.broadcast_id}"
                    if s.broadcast_id else None),
            "recording": bool(getattr(s, "recording", False)),
            # So the button can say Record or Stop recording, and disable
            # itself when recording is switched off entirely rather than
            # offering something that would do nothing.
            "record_enabled": bool(cfg.load().record.enabled),
            # So the UI can stop saying LIVE about a session that is only
            # recording, and hide the things a broadcast would have.
            "streaming": bool(getattr(e, "streaming", True)),
            # The Clips page rides this poll rather than having its own. It
            # costs nothing when idle and means progress survives a reload.
            "clips": self._clips_status(),
            # None until something has actually been installed this run, so an
            # idle poll carries nothing extra.
            "tools": self._tools_status(),
            "edit": self._edit_status(),
            "update": self.update_status(),
            "upload": self._upload_status(),
            **self._phase_clock(),
        }

    # ================= clips =================

    def _clips_status(self) -> dict | None:
        from . import clips

        r = clips.runner()
        snap = r.status()
        if snap is None:
            return None
        # Only the live job needs the two-second heartbeat. A finished one is
        # kept so a reload still shows the result, but it must not look busy.
        return snap

    def _tools_status(self) -> dict | None:
        from .clips import deps

        return deps.installer().status()

    def clips_tools(self) -> dict:
        """What the clipper needs from outside Python, and what is here.

        Carries the install job too. The Clips page reads progress off the
        status poll it already makes, but the setup wizard runs before there
        is a configured engine to poll -- so one endpoint answers both.
        """
        from .clips import deps

        deps.forget()          # so a hand-install is seen without a restart
        return {"ok": True, **deps.state(), "job": deps.installer().status()}

    def clips_install(self, body: dict) -> dict:
        """Install the named tools with winget, at the user's request.

        Never on its own initiative: these are machine-wide installs that
        raise a UAC prompt, and a prompt from a process the user did not ask
        anything of is how software gets mistaken for something worse.
        """
        from .clips import deps

        want = body.get("tools")
        keys = ([str(x) for x in want] if isinstance(want, list) and want
                else deps.missing_keys())
        if not keys:
            return {"ok": True, "already": True,
                    "hint": "Everything the clipper needs is already here."}
        started, why = deps.installer().start(keys)
        if not started:
            return {"error": why}
        log.info("installing clip tools: %s", ", ".join(keys))
        names = [t["label"] for t in deps.TOOLS if t["key"] in keys]
        return {"ok": True, "installing": keys,
                "hint": (f"Installing {' and '.join(names)}. Windows will ask "
                         f"for permission - say yes. This page shows the "
                         f"progress.")}

    def _upload_status(self) -> dict | None:
        from .clips import upload as up

        return up.runner().status()

    def clips_upload(self, body: dict) -> dict:
        """Publish selected clips. Never happens without this call.

        Refuses rather than half-publishes: quota, the daily cap and an empty
        selection are all settled before a byte goes up.
        """
        from .clips import upload as up

        if self.engine is None or not getattr(self.engine, "streaming", True):
            return {"error": "Uploading needs YouTube switched on. "
                             "Settings > YouTube > Go live on YouTube."}
        runner = up.runner()
        if runner.busy():
            return {"error": "An upload is already running."}

        clips = [c for c in (body.get("clips") or []) if isinstance(c, dict)]
        if not clips:
            return {"error": "No clips selected."}
        c = cfg.load()
        privacy = str(body.get("privacy") or c.clips.upload_privacy)
        if privacy not in ("public", "unlisted", "private"):
            privacy = "unlisted"

        folder = Path(str(body.get("folder") or ""))
        job = up.UploadJob(
            clips, yt=self.engine.yt,
            game=str(body.get("game") or "Session"),
            folder=folder,
            privacy=privacy,
            title_template=str(body.get("title") or c.clips.upload_title),
            description_template=str(body.get("description")
                                     or c.clips.upload_description),
            tags=list(c.description.tags or []),
            daily_max=int(getattr(c.rules, "upload_daily_max", 5)),
            channel=str(c.thumbnail.channel_name or ""))
        if not runner.start(job):
            return {"error": "An upload is already running."}
        # Remembered so the next batch offers what the last one used.
        try:
            cfg.save_field("clips", "upload_privacy", privacy)
        except Exception:  # noqa: BLE001
            pass
        log.info("upload job started: %d clip(s), %s", len(clips), privacy)
        return {"ok": True, "count": len(clips)}

    def _profile_rows(self) -> list[dict]:
        """profiles.listing(), told what this machine can actually do."""
        from .clips import profiles

        rows = profiles.listing()
        for row in rows:
            prof = profiles.for_game(row["key"])
            ready, why, ocr = self._scan_ready(prof)
            row["ready"] = ready
            row["blocked"] = why
            row["needs_ocr"] = ocr
            row["scan_rate"] = self._scan_rate(prof)
            row["counts_assists"] = bool(prof and prof.counts_assists)
        return rows

    @staticmethod
    def _scan_rate(prof) -> float:
        """How fast this profile reads footage, for the page's estimate.

        Round mode is a different and much slower pass -- the scoreboard is
        read alongside the feed -- so a profile that supports rounds is quoted
        at that rate. The page would otherwise repeat a rule of thumb that was
        three times too optimistic for exactly the game people use it on.
        """
        if prof is None:
            return 0.0
        from .clips.jobs import scan_rate

        return scan_rate(prof.mode, bool(getattr(prof, "rounds", False)))

    @staticmethod
    def _scan_ready(prof) -> tuple[bool, str, bool]:
        """Can this profile be run on THIS machine? -> (yes, why not, ocr).

        Two different questions, answered together because the page only has
        one button to grey out. `prof.exists()` is about the profile's own
        configuration -- is there a template, is there an in-game name -- and
        travels with the profile. Tesseract is about the PC, and until now was
        discovered several minutes into a scan, after the file had been picked
        and the run started.

        The third value says which it was, because they need different
        buttons: a missing name is typed in, a missing tool is installed.
        """
        if prof is None:
            return False, "", False
        if not prof.exists():
            return False, prof.why_not(), False
        if getattr(prof, "needs_ocr", False):
            from . import clips as clips_mod

            if not clips_mod.ocr_ready():
                return False, (
                    f"{prof.label} finds your kills by reading the kill feed, "
                    f"which needs Tesseract OCR. It is not on this PC yet - "
                    f"AutoStream can install it for you."), True
        return True, "", False

    def clips_sessions(self) -> dict:
        """Past streams, plus what the Clips page needs to decide about each."""
        from . import clips, history
        from .clips import profiles

        cfg_now = cfg.load()
        clips.set_ffmpeg_path(cfg_now.clips.ffmpeg_path or None)

        rows = history.annotate(history.read(limit=200))
        table = profiles.load_all()
        # ONE PASS. Both of these read every run's session.json, and they used
        # to do it separately -- twenty-five folders of twenty-kilobyte JSON,
        # parsed twice, every time this page is opened or refreshed.
        found, runs = self._scan_runs(cfg_now)
        # The match cache is read once here too, for the same reason: state()
        # reads every cached match, and calling it per session row made that
        # every match times every Valorant stream.
        vmatches = None
        for r in rows:
            prof = profiles.for_game(r.get("game_key"), r.get("game"))
            r["profile"] = prof.label if prof else None
            ready, why, ocr = self._scan_ready(prof)
            r["can_scan"] = ready
            r["needs_ocr"] = ocr
            here = self._same_file(r.get("recording_path") or "")
            r["kills_known"] = found.get(here)
            # What a previous run already produced. Cutting a stream again is
            # usually a mistake made for want of knowing it was cut already --
            # eight minutes of scanning to arrive back where you started.
            made = runs.get(here)
            r["made_clips"] = made["clips"] if made else 0
            r["made_folder"] = made["folder"] if made else ""
            r["made_when"] = made["when"] if made else 0
            # Games can only be counted, not distinguished from assists.
            r["counts_assists"] = bool(prof and prof.counts_assists)
            # How this game's kills are found, so the page can say. "killfeed"
            # is slow enough to be worth warning about, and its usual failure
            # is a missing in-game name rather than a missing template -- which
            # would otherwise show as "Not calibrated" and send the user off to
            # draw a box that already exists.
            r["scan_mode"] = prof.mode if prof else None
            # Whether this game is clipped by round rather than by kill burst.
            r["rounds"] = bool(prof and getattr(prof, "rounds", False))
            # Seconds of recording read per second of work, so the page can
            # quote a real number for the part of the file that is selected
            # rather than a rule of thumb that is wrong for this mode.
            r["scan_rate"] = self._scan_rate(prof)
            r["blocked"] = why
            # Whether a replay for this match looks to be on disk. Only games
            # that HAVE replays get an answer -- "no demo" against Valorant
            # would read as a fault rather than as not applicable.
            if prof and getattr(prof, "demos", False):
                from .clips import cs2_demo

                got = cs2_demo.demo_state(
                    cs2_demo.demo_folder(""),
                    float(r.get("started") or 0),
                    _rec_seconds(r))
                r["demo_state"] = got["state"]
                r["demo_file"] = got["file"]
                r["has_demo"] = got["state"] == "have"
            else:
                r["has_demo"] = None
            # The same question for a game that keeps a server-side record
            # instead of writing a replay file.
            if prof and getattr(prof, "matches", False):
                from .clips import valorant_match

                if vmatches is None:
                    vmatches = valorant_match.cached()
                got = valorant_match.state(float(r.get("started") or 0),
                                           _rec_seconds(r), matches=vmatches)
                r["match_state"] = got["state"]
                r["match_count"] = got["matches"]
                r["match_why"] = got.get("why", "")
            else:
                r["match_state"] = None
            # So the calibrator can prefill it rather than asking again.
            r["player"] = (prof.player if prof else "") or                 profiles.username_for(r.get("game_key"), r.get("game"))
            # No profile yet? Hand the calibrator a starting box so the user is
            # adjusting a rectangle rather than hunting for one.
            r["seed"] = None if prof else profiles.seed_for(r.get("game_key"),
                                                            r.get("game"))
        return {
            "sessions": rows,
            # ONE ANSWER TO "CAN THIS GAME BE SCANNED". The listing knows
            # about the profile; only here is it known whether this PC has the
            # OCR a kill feed needs, and at what rate it would read. Two
            # payloads describing the same game differently is how the game
            # dropdown came to grey out a button the game list had just
            # enabled.
            "profiles": self._profile_rows(),
            "status": clips.status(),
            "defaults": {k: v for k, v in schema.flatten(cfg_now).items()
                         if k.startswith("clips.")},
            "output_dir": str(self._clips_dir(cfg_now)),
            "games": sorted({r["game"] for r in rows if r.get("game")}),
            "known": len(table),
            "last_job": self._last_manifest(cfg_now),
            # Uploading needs a channel to upload TO. A clips-only install has
            # none, and offering the button there would be a lie.
            "can_upload": bool(self.engine is not None
                               and getattr(self.engine, "streaming", True)
                               and cfg_now.youtube.stream_id),
            # Whether this install streams at all. A clips-only one never
            # will, so the page must not explain an empty stream list by
            # telling the user to go and stream.
            "streaming": bool(cfg_now.youtube.enabled),
            "upload_daily_max": int(getattr(cfg_now.rules, "upload_daily_max", 5)),
            "upload_privacy": cfg_now.clips.upload_privacy,
            "upload_title": cfg_now.clips.upload_title,
        }

    @staticmethod
    def _same_file(raw: str) -> str:
        """One spelling for a path, so two records of it can be compared.

        The history writes a recording as "C:/Users/.../x.mp4" and a run's
        session.json writes the same file with backslashes instead. Compared
        as strings they never match, which is why the Clips page could not say
        how many kills a previous run had found, and later could not say a
        stream had already been clipped -- both looked up a key that could not
        exist.
        """
        try:
            return str(Path(raw)).casefold() if raw else ""
        except (OSError, ValueError):
            return (raw or "").casefold()

    def _scan_runs(self, config=None) -> tuple[dict[str, int], dict[str, dict]]:
        """One walk over every run's session.json.

        -> (kills found per recording, newest finished run per recording)

        Both answers come from the same files, and reading them twice cost a
        second walk over every folder for nothing. Newest first, so the newest
        run of a recording is the one that answers -- the oldest run of a
        recording is the one whose clips are most likely to be wrong.
        """
        kills: dict[str, int] = {}
        runs: dict[str, dict] = {}
        root = self._clips_dir(config or cfg.load())
        try:
            sidecars = sorted(root.glob("*/session.json"),
                              key=lambda f: f.stat().st_mtime, reverse=True)
        except OSError:
            return kills, runs
        for sidecar in sidecars:
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            src = self._same_file(data.get("source") or "")
            if not src:
                continue
            kills[src] = max(kills.get(src, 0), len(data.get("kills") or []))
            if src in runs:
                continue                  # a newer run already answered
            folder = sidecar.parent
            made = 0
            try:
                made = len(list((folder / "vertical").glob("*.mp4"))) or \
                    len(list((folder / "clips").glob("*.mp4")))
            except OSError:
                pass
            if made:
                runs[src] = {"folder": str(folder), "clips": made,
                             "when": int(sidecar.stat().st_mtime)}
        return kills, runs

    def clips_existing(self, folder: str) -> dict:
        """One finished run's clips, for looking at before cutting again."""
        if not folder:
            return {"error": "No folder given."}
        f = Path(folder)
        # Confined the way the video and edit endpoints are. Without it this
        # would read a clips.json from anywhere on disk and hand its contents
        # back -- the page only ever passes folders it was given, but the page
        # is not the only thing that can call this.
        try:
            if not f.resolve().is_relative_to(self._clips_dir(cfg.load()).resolve()):
                return {"error": "That folder is not in the clips folder."}
        except OSError:
            return {"error": "That folder is gone."}
        man, sess = f / "clips.json", f / "session.json"
        if not man.exists():
            return {"error": "That run has no clip list."}
        try:
            data = json.loads(man.read_text(encoding="utf-8"))
            plan = json.loads(sess.read_text(encoding="utf-8")) if sess.exists() else {}
        except (OSError, ValueError, json.JSONDecodeError) as e:
            return {"error": f"Could not read that run: {e}"}
        clips = data if isinstance(data, list) else (data.get("clips") or [])
        return {"ok": True, "folder": str(f),
                "source": plan.get("source", ""),
                # The page needs this to know how far past the clip it may
                # scrub. Without it the window would be guesswork and asking
                # for a tail near the end of a recording would fail at the
                # re-render rather than being clamped on screen.
                "source_seconds": self._source_seconds(plan),
                "game": plan.get("game", ""),
                "when": int(man.stat().st_mtime),
                "montage": (data or {}).get("montage") if isinstance(data, dict) else None,
                "clips": clips}

    _probed: dict = {}

    def _source_seconds(self, plan: dict) -> float:
        """How long a run's recording is. Cached: probing costs a subprocess
        and the answer cannot change for a file that has stopped growing."""
        src = str(plan.get("source") or "")
        if not src:
            return 0.0
        for key in ("recording_seconds", "source_seconds", "duration"):
            try:
                got = float(plan.get(key) or 0.0)
            except (TypeError, ValueError):
                got = 0.0
            if got > 0:
                return got
        if src in self._probed:
            return self._probed[src]
        got = 0.0
        try:
            from .clips import cutter
            got = float((cutter.probe_source(Path(src)) or {}).get("duration") or 0.0)
        except Exception as e:                          # noqa: BLE001
            log.info("could not measure %s: %s", Path(src).name, e)
        self._probed[src] = got
        return got

    _windowing: dict = {}

    SOUND_TYPES = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus")

    @staticmethod
    def sounds_dir(config=None) -> Path:
        """Where a person's own sound effects live.

        A FOLDER, and the only place a clip's sounds may come from. The page
        sends a path and the app hands it to ffmpeg, so without somewhere to
        confine it that would read any file on the disk -- the same reasoning
        as the video endpoint. Made rather than merely checked, because an
        empty folder is a usable answer and a missing one is a puzzle.
        """
        c = config or cfg.load()
        where = Path(str(dict(c.clips).get("sounds_dir") or "")
                     or paths.VIDEO_HOME / "sounds")
        try:
            where.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.info("could not make the sounds folder %s: %s", where, e)
        return where

    def clips_sounds(self) -> dict:
        """What is in the sounds folder, for the page to offer."""
        where = self.sounds_dir()
        found = []
        try:
            for f in sorted(where.iterdir()):
                if f.is_file() and f.suffix.lower() in self.SOUND_TYPES:
                    found.append({"name": f.stem, "file": f.name,
                                  "path": str(f),
                                  "bytes": f.stat().st_size})
        except OSError as e:
            return {"error": f"Could not read {where}: {e}"}
        return {"ok": True, "folder": str(where), "sounds": found}

    def _effects(self, raw) -> tuple[object, str]:
        """The page's effects JSON -> an Effects, or a reason it cannot be.

        None means "the page said nothing about effects", which recut reads as
        leave them alone. An empty dict means "there are none now", which
        clears them. Those are different answers and the difference matters:
        the first is what a caption-only edit sends.
        """
        from .clips import effects as fx

        if raw is None:
            return None, ""
        if not isinstance(raw, dict):
            return None, "Effects have to be an object."

        def num(v, fallback, lo, hi, what):
            try:
                got = float(v) if v is not None else fallback
            except (TypeError, ValueError):
                raise ValueError(f"{what} is not a number.") from None
            if not lo <= got <= hi:
                raise ValueError(f"{what} has to be between {lo} and {hi}.")
            return got

        def rows(key):
            got = raw.get(key) or []
            if not isinstance(got, list):
                raise ValueError(f"{key} has to be a list.")
            return [r for r in got if isinstance(r, dict)]

        sounds_root = self.sounds_dir().resolve()
        try:
            captions = [
                fx.Caption(text=str(c.get("text") or "")[:200],
                           at=num(c.get("at"), 0.0, 0, 36000, "A caption's start"),
                           until=num(c.get("until"), 3.0, 0, 36000,
                                     "A caption's end"),
                           where=str(c.get("where") or "top"),
                           size=num(c.get("size"), 1.0, 0.4, 2.0,
                                    "A caption's size"))
                for c in rows("captions")]
            zooms = [
                fx.Zoom(at=num(z.get("at"), 0.0, 0, 36000, "A zoom's start"),
                        until=num(z.get("until"), 2.0, 0, 36000, "A zoom's end"),
                        to=num(z.get("to"), 1.35, fx.ZOOM_MIN, fx.ZOOM_MAX,
                               "A zoom's amount"))
                for z in rows("zooms")]
            freezes = [
                fx.Freeze(at=num(f.get("at"), 0.0, 0, 36000, "A freeze's time"),
                          seconds=num(f.get("seconds"), 0.7, fx.FREEZE_MIN,
                                      fx.FREEZE_MAX, "A freeze's length"))
                for f in rows("freezes")]

            sounds = []
            for snd in rows("sounds"):
                p = Path(str(snd.get("path") or ""))
                # Confined to the sounds folder. The page picks from a list
                # this app produced, but the page is not the only thing that
                # can call this, and the path goes straight to ffmpeg.
                try:
                    inside = p.resolve().is_relative_to(sounds_root)
                except OSError:
                    inside = False
                if not inside:
                    return None, ("Sounds have to come from your sound effects "
                                  "folder. Put the file there and try again.")
                if p.suffix.lower() not in self.SOUND_TYPES:
                    return None, f"{p.name} is not a sound file."
                sounds.append(fx.Sound(
                    path=p,
                    at=num(snd.get("at"), 0.0, 0, 36000, "A sound's time"),
                    gain=num(snd.get("gain"), 1.0, 0.01, fx.SOUND_GAIN_MAX,
                             "A sound's volume")))
        except ValueError as e:
            return None, str(e)

        for c in captions:
            if c.where not in fx.WHERE:
                return None, f"A caption asks to sit {c.where!r}."

        return fx.Effects(captions=captions, zooms=zooms, freezes=freezes,
                          sounds=sounds), ""

    def clips_window(self, body: dict) -> dict:
        """A seekable preview of the footage either side of one clip.

        Returns where the preview STARTS in the recording, because that is
        what turns a position in the preview back into a position in the
        recording -- which is the number an edit is expressed in.
        """
        from .clips import cutter

        folder = Path(str(body.get("folder") or ""))
        name = str(body.get("name") or "")
        try:
            headroom = float(body.get("headroom") or 20.0)
        except (TypeError, ValueError):
            headroom = 20.0
        headroom = max(0.0, min(headroom, 120.0))
        if not name:
            return {"error": "No clip given."}
        try:
            if not folder.resolve().is_relative_to(
                    self._clips_dir(cfg.load()).resolve()):
                return {"error": "That folder is not in the clips folder."}
        except OSError:
            return {"error": "That folder is gone."}

        sess = folder / "session.json"
        if not sess.exists():
            return {"error": "That run has no session.json, so its plan is gone."}
        try:
            plan = json.loads(sess.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return {"error": f"Could not read that run: {e}"}

        row = None
        for candidate in (plan.get("plans") or []) + (plan.get("promo_clips") or []):
            if candidate.get("name") == name:
                row = candidate
                break
        if row is None:
            return {"error": "There is no clip by that name in this run."}

        # Centre the window on what the clip IS, not on what the run first cut.
        # A clip already stretched to the edge of its old window would
        # otherwise open in a window that does not contain all of it.
        from .clips import edit as edit_mod
        row = edit_mod.current(folder, name) or row

        source = Path(str(plan.get("source") or ""))
        if not source.exists():
            return {"error": "The recording this run was cut from is gone."}

        limit = self._source_seconds(plan)
        start = max(0.0, float(row["start"]) - headroom)
        end = float(row["end"]) + headroom
        if limit > 0:
            end = min(end, limit)
        if end - start < 1.0:
            return {"error": "There is not enough recording around that clip."}

        # Named for the window, so asking for the same one twice is free and
        # asking for a different one does not collide with it.
        out = (folder / "preview" /
               f"{name}.{int(start)}-{int(end)}.mp4")
        answer = {"ok": True, "path": str(out), "start": start, "end": end,
                  "was_start": float(row["start"]), "was_end": float(row["end"]),
                  "source_seconds": limit}
        if out.is_file() and out.stat().st_size > 0:
            return dict(answer, cached=True)

        key = str(out)
        if self._windowing.get(key) == "running":
            return dict(answer, building=True)
        self._windowing[key] = "running"

        def run():
            try:
                cutter.preview(source, start, end, out)
                log.info("preview for %s: %.0f-%.0f", name, start, end)
                _trim_previews(out.parent)
            except Exception as e:                      # noqa: BLE001
                log.warning("could not build a preview for %s: %s", name, e)
            finally:
                self._windowing.pop(key, None)

        threading.Thread(target=run, name="autostream-preview",
                         daemon=True).start()
        return dict(answer, building=True)

    def clips_window_ready(self, path: str) -> dict:
        """Is that preview finished? The page polls this while it waits."""
        p = Path(path)
        try:
            if not p.resolve().is_relative_to(
                    self._clips_dir(cfg.load()).resolve()):
                return {"error": "That file is not in the clips folder."}
        except OSError:
            return {"error": "No such file."}
        if self._windowing.get(str(p)) == "running":
            return {"ok": True, "ready": False}
        if p.is_file() and p.stat().st_size > 0:
            return {"ok": True, "ready": True}
        return {"ok": True, "ready": False,
                "error": "The preview could not be made."}

    def _last_manifest(self, config) -> dict | None:
        """The most recent finished run's clip list, read from its folder.

        Kept on disk rather than in memory so the results survive a restart -
        the folder is the real record of what was produced.
        """
        root = self._clips_dir(config)
        try:
            found = sorted(root.glob("*/clips.json"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return None
        for p in found[:1]:
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                return None
        return None

    @staticmethod
    def _clips_dir(config) -> Path:
        return Path(config.clips.output_dir or paths.CLIPS_DIR)

    def clips_run(self, body: dict) -> dict:
        from . import clips, history
        from .clips.jobs import ClipJob

        c = cfg.load()
        clips.set_ffmpeg_path(c.clips.ffmpeg_path or None)
        st = clips.status()
        if not st["ok"]:
            return {"error": st["detail"] or "ffmpeg or numpy is missing."}

        runner = clips.runner()
        if runner.busy():
            return {"error": "A clip job is already running."}
        # An edit is an encode too. clips_edit refuses while a job runs; this is
        # the other half of that, so the two cannot fight over the machine.
        from .clips import edit as edit_mod

        if edit_mod.editor().busy():
            return {"error": "A clip is being re-rendered; wait for it to finish."}

        src = str(body.get("source") or "")
        session: dict = {}
        if not src:
            # Identified by recording path rather than by index: the history
            # list is re-read on every poll and an index would race a new entry.
            want = str(body.get("recording_path") or "")
            for row in history.read(limit=200):
                if row.get("recording_path") == want:
                    session = row
                    break
            if not session:
                return {"error": "That stream is no longer in the history."}
            src = session.get("recording_path") or ""

        path = Path(src)
        if not path.exists():
            return {"error": f"The recording is gone: {src}"}

        from .clips import plan as clip_plan

        # A style presets the three timings; "custom" leaves whatever the
        # request and config already say. Resolved here rather than in the job
        # so session.json records the numbers actually used, not a style name
        # whose meaning could change under it later.
        timings = clip_plan.style_values(
            body.get("style") or c.clips.style,
            {
                "clip_seconds": str(body.get("clip_seconds") or c.clips.clip_seconds),
                "pre_roll": _float(body.get("pre_roll"), _float(c.clips.pre_roll, 1.5)),
                "tail": _float(body.get("tail_seconds"),
                               _float(c.clips.tail_seconds, 2)),
            })

        opt = {
            "min_kills": _int(body.get("min_kills"), _int(c.clips.min_kills, 2)),
            "style": str(body.get("style") or c.clips.style),
            "clip_seconds": str(timings["clip_seconds"]),
            "pre_roll": float(timings["pre_roll"]),
            "tail_seconds": float(timings["tail"]),
            "vertical_mode": str(body.get("vertical_mode") or c.clips.vertical_mode),
            "transition": str(body.get("transition") or c.clips.transition),
            "transition_ms": _int(body.get("transition_ms"),
                                  _int(c.clips.transition_ms, 500)),
            "encoder": str(body.get("encoder") or c.clips.encoder),
            "montage": bool(body.get("montage", True)),
            "voice": bool(body.get("voice", c.clips.voice)),
            "voice_name": str(body.get("voice_name") or c.clips.voice_name),
            "music": str(body.get("music") or c.clips.music),
            "arc": bool(body.get("arc", c.clips.arc)),
            "order": str(body.get("order") or c.clips.order),
            "promo": bool(body.get("promo", c.clips.promo)),
            "promo_caption": str(body.get("promo_caption")
                                 or c.clips.promo_caption),
        }
        # WHICH PART OF THE FILE. Chosen on the Clips page against a filmstrip
        # of the recording, because one file routinely holds more than one
        # game. Absent or zero means the whole thing, which is what every run
        # did before this existed. The job sanitises the pair -- backwards,
        # negative or absurdly short windows are ignored there, in one place.
        start = _float(body.get("scan_start"), 0.0)
        end = _float(body.get("scan_end"), 0.0)
        if start > 0 or end > 0:
            opt["scan_start"] = max(0.0, start)
            opt["scan_end"] = max(0.0, end)
        # "Read the screen anyway." A Counter-Strike run stops rather than
        # spending forty minutes on OCR when no replay matched, so this is how
        # the page says the user has chosen that cost with their eyes open.
        if body.get("demo_fallback"):
            opt["demo_fallback"] = True
        # Round mode, for games whose profile reads the scoreboard. Absent for
        # every other game, so nothing changes for them.
        if body.get("rounds") is not None:
            opt["rounds"] = bool(body.get("rounds"))
        if body.get("whole_round") is not None:
            opt["whole_round"] = bool(body.get("whole_round"))
        want = body.get("round_types")
        if isinstance(want, list) and want:
            opt["round_types"] = [str(x) for x in want][:16]
        # What chat asked for during the stream. The request may override, so
        # the Clips page can offer them as a switch.
        marks = body.get("marks")
        if marks is None:
            marks = session.get("marks")
        if marks:
            opt["marks"] = [m for m in marks if isinstance(m, dict)][:300]

        # Per-clip caption and voice settings, from reviewing the plan. Keyed
        # on the clip's start time to a tenth of a second -- see jobs.clip_key.
        per = body.get("per_clip")
        if isinstance(per, dict):
            opt["per_clip"] = {str(k): v for k, v in list(per.items())[:200]
                               if isinstance(v, dict)}
        if body.get("plan_only"):
            # Plan and stop, so the clips can be reviewed before any encoding
            # happens. Everything else about the run is identical, which is
            # what makes the review honest: the same plan gets cut.
            opt["plan_only"] = True

        cached = self._cached_kills(
            path, c, (opt.get("scan_start", 0.0), opt.get("scan_end", 0.0)))
        if cached and not body.get("rescan") and not opt.get("rounds"):
            # Not reused in round mode: the cache holds kills, and a round also
            # needs the scoreboard, which is only read during a scan.
            opt["kills"] = cached

        job = ClipJob(
            path,
            game=str(body.get("game") or session.get("game") or "Session"),
            game_key=body.get("game_key") or session.get("game_key"),
            outdir=self._clips_dir(c),
            options=opt,
            started=session.get("started"),
            session=session,
        )
        if not runner.start(job):
            return {"error": "A clip job is already running."}
        log.info("clip job started: %s", path.name)
        return {"ok": True, "folder": str(job.folder),
                "reused_kills": bool(cached and not body.get("rescan"))}

    def _cached_kills(self, source: Path, config=None,
                      window: tuple[float, float] | None = None) -> list | None:
        """Kills found by an earlier run of the same recording.

        Scanning is by far the slowest step, so re-cutting the same stream with
        different lengths or thresholds should not pay for it twice.

        `window` is the part of the file this run cares about. A scan that
        only read part of the file has a kill list that is complete only
        inside that part, so it is reused only when it covers the whole of
        what is being asked for now -- otherwise the run would be handed an
        empty-looking stretch and report "no kills" for footage it never read.
        """
        root = self._clips_dir(config or cfg.load())
        want_a, want_b = window or (0.0, 0.0)
        try:
            # NEWEST FIRST. Sorted by name, the first match is the run whose
            # folder has no "_2" suffix -- the OLDEST scan of that recording.
            # So every re-cut reused the oldest kills there had ever been, and
            # after the Valorant feed reader was fixed a re-cut quietly
            # reproduced the old, wrong kill list: five clips labelled "2
            # kills" holding one, from a scan that no longer said that.
            for sidecar in sorted(root.glob("*/session.json"),
                                  key=lambda f: f.stat().st_mtime,
                                  reverse=True):
                data = json.loads(sidecar.read_text(encoding="utf-8"))
                # Compared the way everything else compares a path, because
                # Windows does not care about case and the journal and OBS do
                # not agree on it -- see _same_file.
                if (self._same_file(data.get("source") or "")
                        != self._same_file(str(source)) or not data.get("kills")):
                    continue
                # [0, 0], or no key at all, means the whole file was read --
                # which is what every run before windows existed did, so an
                # old sidecar reads correctly without being rewritten.
                got = data.get("scanned") or [0.0, 0.0]
                if len(got) == 2 and (got[0] or got[1]):
                    # want_b of 0 means "to the end of the file", which no
                    # windowed scan can cover.
                    covers = got[0] <= want_a and want_b and got[1] >= want_b
                    if not covers:
                        log.info("%s only read %.0fs-%.0fs of that recording, "
                                 "which does not cover this run -- scanning "
                                 "again", sidecar.parent.name, got[0], got[1])
                        continue
                return data["kills"]
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return None

    def clips_cancel(self) -> dict:
        from . import clips

        return {"ok": clips.runner().cancel()}

    def _edit_status(self) -> dict:
        from .clips import edit as edit_mod

        return edit_mod.editor().snapshot()

    def clips_edit(self, body: dict) -> dict:
        """Re-render one already-cut clip with new settings."""
        from . import clips
        from .clips import edit as edit_mod

        c = cfg.load()
        clips.set_ffmpeg_path(c.clips.ffmpeg_path or None)
        st = clips.status()
        if not st["ok"]:
            return {"error": st["detail"] or "ffmpeg or numpy is missing."}

        folder = Path(str(body.get("folder") or ""))
        name = str(body.get("name") or "")
        if not folder.is_dir() or not name:
            return {"error": "Which clip? A folder and a clip name are needed."}
        try:
            if not folder.resolve().is_relative_to(
                    self._clips_dir(c).resolve()):
                return {"error": "That folder is not in the clips folder."}
        except OSError:
            return {"error": "That folder is gone."}

        ed = edit_mod.editor()
        if ed.busy():
            return {"error": "Another clip is being re-rendered."}
        runner = clips.runner()
        if runner.busy():
            return {"error": "A clip job is running; wait for it to finish."}

        def _flag(key):
            v = body.get(key)
            return None if v is None else bool(v)

        def _num(key):
            v = body.get(key)
            try:
                return None if v is None or v == "" else float(v)
            except (TypeError, ValueError):
                return None

        mode = str(body.get("vertical_mode") or "") or None
        if mode is not None and mode not in ("crop", "fit"):
            return {"error": "A vertical is either cropped or fitted."}

        # Stretches to take out of the middle, as [[from, to], ...] in
        # recording seconds. Anything unreadable is rejected here rather than
        # silently ignored: a removal that quietly does not happen means the
        # clip that gets published still has the dead half-minute in it.
        drop: list[tuple[float, float]] | None = None
        raw = body.get("drop")
        if raw is not None:
            if not isinstance(raw, list):
                return {"error": "Removals have to be a list of ranges."}
            drop = []
            for pair in raw:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    return {"error": "Each removal is a pair of times."}
                try:
                    drop.append((float(pair[0]), float(pair[1])))
                except (TypeError, ValueError):
                    return {"error": "A removal has a time that is not a number."}

        fx_spec, why = self._effects(body.get("effects"))
        if why:
            return {"error": why}

        spec = edit_mod.Spec(
            folder=folder, name=name,
            caption=_flag("caption"),
            caption_text=(None if body.get("caption_text") is None
                          else str(body["caption_text"])),
            speak=_flag("voice"),
            voice_text=(None if body.get("voice_text") is None
                        else str(body["voice_text"])),
            voice_name=str(body.get("voice_name") or "") or None,
            vertical_mode=mode,
            trim_start=_num("trim_start"), trim_end=_num("trim_end"),
            start_at=_num("start_at"), end_at=_num("end_at"),
            drop=drop, effects=fx_spec)
        if not ed.start(spec):
            return {"error": "Another clip is being re-rendered."}
        log.info("re-rendering %s in %s", name, folder.name)
        return {"ok": True, "name": name}

    # The last check, so the page can ask freely without the button becoming a
    # way to spend GitHub's 60-requests-an-hour allowance.
    _update_seen: dict = {}
    _update_job: dict = {}

    def update_check(self, force: bool = False) -> dict:
        """Is there a newer AutoStream? -> what the page needs to say so."""
        from . import __version__, updates

        now = time.time()
        cached = self._update_seen
        if (not force and cached.get("at")
                and now - cached["at"] < updates.MIN_SECONDS_BETWEEN_CHECKS):
            return dict(cached["answer"], cached=True)

        answer: dict
        try:
            rel = updates.latest()
        except RuntimeError as e:
            # Not being able to check is not an error state for the app; it is
            # a sentence on a page. Cached like a success so a machine that is
            # offline does not retry every time the page is opened.
            answer = {"ok": True, "checked": True, "available": False,
                      "current": __version__, "why": str(e)}
        else:
            answer = {
                "ok": True, "checked": True,
                "current": __version__,
                "latest": rel.version,
                "available": bool(rel.usable
                                  and updates.is_newer(rel.version, __version__)),
                "notes": rel.notes[:4000],
                "url": rel.url,
                "bytes": rel.asset_bytes,
                "verifiable": bool(rel.sha256_url),
                # An installer can replace a running program; a zip cannot,
                # so the page has to offer a different ending for each.
                "installable": bool(rel.installable),
                "asset": rel.asset_name,
                "published": rel.published,
            }
        self._update_seen = {"at": now, "answer": answer}
        return dict(answer, cached=False)

    def update_download(self) -> dict:
        """Fetch the newer package, verify it, and say where it landed.

        Deliberately stops there. Replacing a running program is the
        installer's job, and this app has one -- so what a person gets is a
        verified file and a button that opens it, not a surprise restart.
        """
        from . import __version__, updates

        job = self._update_job
        if job.get("state") == "downloading":
            return {"error": "That download is already running."}

        try:
            rel = updates.latest()
        except RuntimeError as e:
            return {"error": str(e)}
        if not rel.usable:
            return {"error": "That release has no package to download."}
        if not updates.is_newer(rel.version, __version__):
            return {"error": f"You already have {__version__}, which is the "
                             f"newest there is."}

        into = paths.DATA_HOME / "updates"
        self._update_job = {"state": "downloading", "version": rel.version,
                            "done": 0, "total": rel.asset_bytes, "path": "",
                            "installable": bool(rel.installable), "error": ""}

        def run():
            def progress(done, total):
                self._update_job.update(done=done, total=total or rel.asset_bytes)
            try:
                got = updates.download(rel, into, on_progress=progress)
            except RuntimeError as e:
                self._update_job.update(state="failed", error=str(e))
                log.warning("update download failed: %s", e)
                return
            self._update_job.update(state="ready", path=str(got))
            log.info("update %s downloaded to %s", rel.version, got)

        threading.Thread(target=run, name="autostream-update",
                         daemon=True).start()
        log.info("downloading AutoStream %s", rel.version)
        return {"ok": True, "version": rel.version}

    def update_install(self) -> dict:
        """Hand the downloaded installer over and get out of its way.

        A PROGRAM CANNOT REPLACE ITS OWN RUNNING FILES, so this does not try.
        The installer is launched detached and then AutoStream quits; the
        installer waits for the exit, swaps the files and starts the new
        version. That is what its CloseApplications/RestartApplications
        settings are for.

        Refused while anything is in flight: an update that interrupts a clip
        job or a live broadcast would be a worse bug than any it fixes.
        """
        from . import clips
        from .clips import edit as edit_mod

        job = self._update_job
        if job.get("state") != "ready" or not job.get("path"):
            return {"error": "There is nothing downloaded to install."}
        installer = Path(job["path"])
        if not installer.is_file():
            return {"error": "The downloaded file is no longer there."}

        if self.engine is not None and getattr(self.engine.state, "phase", "IDLE") != "IDLE":
            return {"error": "A session is running. Stop it before updating."}
        if clips.runner().busy():
            return {"error": "A clip job is running. Wait for it to finish."}
        if edit_mod.editor().busy():
            return {"error": "A clip is being re-rendered. Wait for it to finish."}

        # The zip has no installer to run; it is extracted by hand. Say so
        # rather than trying to execute an archive.
        if installer.suffix.lower() != ".exe":
            return {"error": f"{installer.name} is a zip. Unzip it over your "
                             f"installation yourself, or download the "
                             f"installer instead."}
        try:
            subprocess.Popen(
                [str(installer), "/SILENT", "/CLOSEAPPLICATIONS",
                 "/RESTARTAPPLICATIONS", "/NORESTART"],
                cwd=str(installer.parent),
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        except OSError as e:
            return {"error": f"Could not start the installer: {e}"}
        log.info("handing over to the installer: %s", installer.name)

        # Quit a moment later, not here. Closing the app inside the request
        # that asked for it means the reply never arrives, so the page cannot
        # say what is happening before the window vanishes. The installer is
        # already waiting for this process either way.
        def leave():
            time.sleep(1.5)
            if self.window is not None:
                self.window.request_quit("an update is being installed")

        threading.Thread(target=leave, name="autostream-handover",
                         daemon=True).start()
        return {"ok": True, "version": job.get("version", "")}

    def update_status(self) -> dict:
        return dict(self._update_job) or {"state": "idle"}

    def clips_voices(self) -> dict:
        """The voices installed, grouped, so one can be chosen by ear."""
        from .clips import voice as v

        if not v.available():
            return {"ok": True, "available": False, "why": v.why_not(),
                    "groups": {}, "default": v.VOICE,
                    "sample_line": v.SAMPLE_LINE}
        groups = {}
        for prefix, names in v.catalogue().items():
            groups[v.GROUPS.get(prefix, prefix)] = list(names)
        return {"ok": True, "available": True, "why": "", "groups": groups,
                "default": v.VOICE, "sample_line": v.SAMPLE_LINE}

    # One rendered sample per voice, kept between requests. Kokoro takes about
    # a second a line and the model a second to load, and choosing a voice
    # means playing several of them repeatedly.
    _voice_samples: dict[tuple[str, str], bytes] = {}

    def voice_sample(self, name: str, line: str = "") -> tuple[bytes, str | None]:
        """One voice saying one line, as a wav. For choosing by ear."""
        from .clips import voice as v

        name = (name or v.VOICE).strip()
        if name not in v.voices():
            return b"", f"There is no voice called {name!r}."
        line = (line or "").strip()[:200]
        key = (name, line)
        got = self._voice_samples.get(key)
        if got:
            return got, None
        if not v.available():
            return b"", v.why_not()
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="asvoice_"))
        try:
            made = v.samples(tmp, line, names=[name])
            if not made:
                return b"", f"Could not render {name}."
            data = made[0].read_bytes()
            if len(self._voice_samples) > 60:
                self._voice_samples.clear()
            self._voice_samples[key] = data
            return data, None
        except Exception as e:  # noqa: BLE001
            return b"", str(e)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def clip_frame(self, path: str, at: float,
                   width: int = 0) -> tuple[bytes, str | None]:
        """One PNG frame, for the calibrator's frame picker.

        `width` because the filmstrip asks for twelve of these at once and a
        960px still is about 900 KB. At 240 they are a tenth of that, which is
        the difference between a strip that appears and one that crawls in.
        """
        from . import clips

        clips.set_ffmpeg_path(cfg.load().clips.ffmpeg_path or None)
        if not clips.available():
            return b"", "ffmpeg is not available."
        # Path("") is the CURRENT DIRECTORY, and a directory exists -- so an
        # empty path passed the check below and reached ffmpeg, which answered
        # with "ffmpeg.EXE failed (4294967283)". That is a true statement about
        # ffmpeg and says nothing at all about the request.
        if not str(path).strip():
            return b"", "No recording given."
        src = Path(path)
        if not src.is_file():
            return b"", "That recording is no longer on disk."
        import tempfile

        from .clips.cutter import poster

        tmp = Path(tempfile.mkdtemp(prefix="asframe_"))
        try:
            png = poster(src, max(0.0, at), tmp / "f.png",
                         width=min(1920, width) if width > 0 else 960)
            return png.read_bytes(), None
        except Exception as e:  # noqa: BLE001
            return b"", str(e)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # Stripped BOTH ways, because neither alone is enough.
    #
    # By name, for config.yaml -- these are the keys that must never reach a
    # chat window. And by value over the whole report, because the log carries
    # them in prose: the startup banner prints the dashboard URL with the web
    # token in the query string, and the first version of this leaked it
    # exactly that way.
    SECRET_KEYS = ("password", "web_token", "stream_id", "ingestion_address")

    def diagnostics(self) -> dict:
        """One paste-able report about this install. -> {ok, text}.

        Turns "it does not work" into something answerable. Every problem this
        app has had reported to it arrived as a photograph of a screen, and a
        photograph cannot say which OBS version, which build, or what the log
        said thirty seconds earlier.
        """
        import platform

        from . import __version__

        c = cfg.load()
        lines = [
            f"AutoStream {__version__}",
            f"Python      {platform.python_version()}  ({sys.platform})",
            f"OS          {platform.platform()}",
            f"Home        {paths.ROOT}",
            f"Frozen      {bool(getattr(sys, 'frozen', False))}",
        ]

        try:
            from .obs import discover_websocket, find_obs_exe, _obs_process_alive

            exe = c.obs.path or find_obs_exe()
            ws = discover_websocket(exe)
            lines += [
                "",
                f"OBS exe     {exe or '(not found)'}",
                f"OBS running {_obs_process_alive()}",
                f"OBS ws      found={ws['found']} enabled={ws['enabled']} "
                f"port={ws['port']} auth={ws['auth_required']}",
            ]
        except Exception as e:  # noqa: BLE001
            lines += ["", f"OBS         could not be inspected: {e}"]

        try:
            from . import clips as clipsmod

            st = clipsmod.status()
            lines.append(f"ffmpeg      ok={st.get('ok')} {st.get('detail') or ''}".rstrip())
        except Exception as e:  # noqa: BLE001
            lines.append(f"ffmpeg      could not be checked: {e}")

        lines += [
            "",
            f"streaming   {bool(c.youtube.enabled)}",
            f"recording   {bool(c.record.enabled)}",
            f"token       {'present' if paths.TOKEN_FILE.exists() else 'MISSING'}",
            f"client id   {'present' if paths.CLIENT_SECRET.exists() else 'MISSING'}",
            f"screens     enabled={bool(c.screens.enabled)}",
        ]
        if self.engine is not None:
            s_ = self.engine.state
            lines += [
                f"phase       {s_.phase} paused={s_.paused}",
                f"quota spent {s_.quota_spent} on {s_.quota_date}",
            ]

        lines += ["", "--- config (secrets removed) ---"]
        for section, body in sorted((cfg.load_raw() or {}).items()):
            if not isinstance(body, dict):
                lines.append(f"{section}: {body}")
                continue
            for key, value in sorted(body.items()):
                if any(k in key for k in self.SECRET_KEYS):
                    value = "(removed)" if value else "(empty)"
                lines.append(f"{section}.{key} = {value}")

        lines += ["", "--- last 40 log lines ---"]
        try:
            lines += [ln.rstrip() for ln in tail_lines(paths.LOG_FILE, 40)]
        except Exception as e:  # noqa: BLE001
            lines.append(f"(could not read the log: {e})")

        return {"ok": True, "text": self._scrub(chr(10).join(lines), c)}

    def _scrub(self, text: str, config) -> str:
        """Remove secret VALUES wherever they appear, prose included."""
        for value in (config.obs.password, config.rules.web_token,
                      config.youtube.stream_id, config.youtube.ingestion_address,
                      config.obs.get("password_env", "")):
            v = str(value or "")
            if len(v) >= 6:          # short values would scrub ordinary words
                text = text.replace(v, "(removed)")
        # Any token-bearing URL, including one from a config this process has
        # not loaded -- an older log line, or a second install.
        return re.sub(r"([?&]k=)[^\s&\"']+",
                      lambda m: m.group(1) + "(removed)", text)

    def clips_pick(self) -> dict:
        """Ask the OS for a video file. -> {ok, path} or {error}.

        A browser file input hands back a NAME, never a path, and these files
        run to tens of gigabytes so uploading one is not an option either. The
        server and the page are always the same machine, so the dialog opens
        here and only the path crosses.

        Tk rather than pywebview's dialog: the native window is not always
        there -- plenty of machines fall back to a browser -- and Tk is already
        bundled for the overlay panel.
        """
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            return {"error": "No file picker on this machine. Paste the path instead."}
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)   # or it opens behind the browser
            chosen = filedialog.askopenfilename(
                parent=root,
                title="Choose a video to clip",
                filetypes=[("Video", "*.mp4 *.mkv *.mov *.flv *.avi *.ts *.webm"),
                           ("All files", "*.*")])
            root.destroy()
        except Exception as e:  # noqa: BLE001
            return {"error": f"Could not open the file picker: {str(e)[:160]}"}
        if not chosen:
            return {"ok": True, "path": ""}          # cancelled, not an error
        path = Path(chosen)
        if not path.is_file():
            return {"error": "That file is not there any more."}
        out = {"ok": True, "path": str(path), "name": path.name,
               "bytes": path.stat().st_size,
               "size_mb": round(path.stat().st_size / (1024 * 1024))}
        out.update(self.clips_probe({"path": str(path)}))
        return out

    def clips_probe(self, body: dict) -> dict:
        """What a file the user picked is, without starting anything.

        The page needs three things before it can offer the same options a
        recorded session gets: how long the file is (the timeline and the
        calibrator are both ranges over it), when it was recorded (which is
        what finds a replay for it), and whether a replay looks to be there.

        Never an error. A file that cannot be probed is still perfectly
        clippable -- the run probes it again itself -- so a failure here costs
        the timeline and nothing else.
        """
        from . import history

        src = Path(str(body.get("path") or ""))
        out: dict = {"duration": 0.0, "started": None}
        if not src.is_file():
            return out

        c = cfg.load()
        from . import clips

        clips.set_ffmpeg_path(c.clips.ffmpeg_path or None)
        try:
            from .clips.tools import media_info

            out["duration"] = float(media_info(src).get("duration") or 0.0)
        except Exception as e:  # noqa: BLE001
            log.info("could not probe %s: %s", src.name, e)

        # WHEN IT WAS RECORDED, not when the file was written. OBS stamps its
        # filenames, which is exact; mtime is when writing FINISHED, so the
        # duration comes off it to get back to the start. Without that
        # subtraction a two-hour recording looks two hours newer than it is,
        # and every demo played during it is rejected as "written before the
        # match" -- see cs2_demo.demo_state.
        started = history._started_from_name(str(src))       # noqa: SLF001
        if started is None:
            try:
                started = src.stat().st_mtime - (out["duration"] or 0.0)
            except OSError:
                started = None
        out["started"] = started

        # Only for a game that HAS replays, and only once one is chosen -- the
        # page asks again with the game once the user picks it.
        key = str(body.get("game_key") or "")
        if key and started:
            from .clips import profiles

            prof = profiles.for_game(key)
            if prof is not None and getattr(prof, "demos", False):
                from .clips import cs2_demo

                got = cs2_demo.demo_state(cs2_demo.demo_folder(""), started,
                                          out["duration"])
                out["demo_state"] = got["state"]
                out["demo_file"] = got["file"]
                out["has_demo"] = got["state"] == "have"
            else:
                out["demo_state"] = None
                out["has_demo"] = None
            # The same question for a game whose record of the match lives on
            # the publisher's servers rather than in a file. A recorded
            # session got this answer and a picked file did not, which is the
            # same gap the demo box had.
            if prof is not None and getattr(prof, "matches", False):
                from .clips import valorant_match

                got = valorant_match.state(started, out["duration"])
                out["match_state"] = got["state"]
                out["match_count"] = got["matches"]
                out["match_why"] = got.get("why", "")
            else:
                out["match_state"] = None
        return out

    def clips_games(self) -> dict:
        """Games the clipper can read, for the local-file picker.

        Carries the same per-game fields clips_sessions attaches to a recorded
        session, so a file the user picked can drive the identical options card
        instead of a second, poorer one.
        """
        from .clips import profiles

        out = []
        for row in profiles.listing():
            prof = profiles.for_game(row["key"])
            if prof is None:
                continue
            ready, why, ocr = self._scan_ready(prof)
            out.append({
                "game_key": prof.key,
                "game": prof.label,
                "profile": prof.label,
                "can_scan": ready,
                "needs_ocr": ocr,
                "demos": bool(getattr(prof, "demos", False)),
                "scan_mode": prof.mode,
                "scan_rate": self._scan_rate(prof),
                "rounds": bool(getattr(prof, "rounds", False)),
                "counts_assists": bool(prof.counts_assists),
                "blocked": why,
                "player": prof.player or profiles.username_for(prof.key, prof.label),
                # Killfeed games are blocked by a MISSING NAME, not a missing
                # template, and the two have completely different fixes. Saying
                # "needs calibrating" for this one sends people to draw a box
                # that was never the problem.
                "needs_name": (prof.mode == "killfeed"
                               and not (prof.player
                                        or profiles.username_for(prof.key, prof.label))),
                "builtin": row["builtin"],
            })
        return {"games": out}

    def clips_demos(self, body: dict) -> dict:
        """Ask Counter-Strike to download the matches the user pasted.

        The share code is the only handle on a demo a person can copy out of
        the game, and the steam:// link makes their OWN client fetch it -- no
        Steam credentials, no API key, no game-coordinator protocol.
        AutoStream never downloads anything itself.

        Several at once because a live session routinely spans more than one
        match, and pasting them one at a time would be the tedious way to say
        the same thing.
        """
        from .clips import cs2_demo

        codes = cs2_demo.share_codes(str(body.get("text") or ""))
        if not codes:
            return {"error": "No match codes in that. Copy the sharing code "
                             "from a match in Counter-Strike (or the whole "
                             "steam:// link) and paste it here."}
        before = set()
        folder = cs2_demo.demo_folder("")
        if folder:
            try:
                before = {p.name for p in Path(folder).glob("*.dem")}
            except OSError:
                pass

        sent, failed = [], []
        for code in codes[:20]:
            (sent if cs2_demo.request_download(code) else failed).append(code)
        if not sent:
            return {"error": "Windows would not open the Steam link. Is Steam "
                             "installed?"}
        log.info("asked Counter-Strike for %d demo(s)", len(sent))
        return {
            "ok": True, "sent": len(sent), "failed": len(failed),
            "have": len(before),
            # Counter-Strike does the downloading on its own schedule, and the
            # file appearing is the only completion signal there is.
            "hint": (f"Counter-Strike is downloading {len(sent)} match"
                     f"{'' if len(sent) == 1 else 'es'}. It has to be running, "
                     f"and the files appear in your replays folder when it is "
                     f"done - refresh this page then."),
        }

    def clips_setname(self, body: dict) -> dict:
        """Record an in-game name, so a killfeed game can be scanned.

        Until now the only writers were the calibrator and the setup wizard.
        The wizard lists Steam and Epic games only, so a game that arrives as a
        shortcut could never be given one there -- and a clips-only user, who
        may never open either, hit a profile that simply refused to run.
        """
        from .clips import profiles

        key = str(body.get("game_key") or "").strip()
        name = str(body.get("name") or "").strip()
        if not key:
            return {"error": "No game given."}
        if not name:
            return {"error": "Type the name exactly as the kill feed shows it."}
        if len(name) > 64:
            return {"error": "That is too long to be an in-game name."}
        if not profiles.save_username(key, name, str(body.get("label") or "")):
            return {"error": "Could not save that name."}
        log.info("in-game name recorded for %s", key)
        return {"ok": True, **self.clips_games()}

    def clips_calibrate(self, body: dict) -> dict:
        from .clips import calibrate

        return calibrate.from_request(body)

    def clips_forget(self, recording_path: str, session: int,
                     missing_only: bool = False) -> dict:
        """Drop history rows. NEVER deletes video.

        Two modes. Named, which drops one entry, and missing_only, which drops
        every entry whose recording is no longer on disk -- because deleting
        old footage is normal and the list otherwise fills up with streams
        that can never be cut again and cannot be dismissed.

        The file is checked NOW rather than trusted from the entry: a
        recording on a drive that happens to be unplugged is not gone, and
        forgetting it would lose the record of a stream that still exists.
        """
        from . import history

        rows = history.read()
        if missing_only:
            keep = [r for r in rows
                    if not r.get("recording_path")
                    or Path(str(r["recording_path"])).exists()]
            if len(keep) == len(rows):
                return {"ok": True, "removed": 0,
                        "detail": "Every stream still has its recording."}
        else:
            if not recording_path:
                return {"error": "No recording given."}
            keep = [r for r in rows
                    if not (r.get("recording_path") == recording_path
                            and (session < 0 or r.get("session") == session))]
            if len(keep) == len(rows):
                return {"error": "No matching entry."}
        history.rewrite(keep)
        gone = len(rows) - len(keep)
        log.info("forgot %d stream(s) whose recording was gone", gone)
        return {"ok": True, "removed": gone}

    def reveal(self, path: str) -> dict:
        """Open a folder (or select a file) in Explorer."""
        p = Path(path)
        if not p.exists():
            return {"error": "That path no longer exists."}
        try:
            if p.is_dir():
                subprocess.Popen(["explorer", str(p)])
            else:
                subprocess.Popen(["explorer", "/select,", str(p)])
        except OSError as e:
            return {"error": str(e)}
        return {"ok": True}

    # Phases that run against a deadline. The dashboard draws a countdown ring
    # from these, so the timing comes from the engine's own clock rather than
    # the browser guessing when the phase changed - a page opened mid-ARMING
    # would otherwise show a full ring and a wrong "goes live in".
    _PHASE_LIMIT = {
        "ARMING": ("timing", "arm_delay"),
        "TESTING": ("timing", "abort_grace"),
        "STARTING": ("timing", "ingestion_timeout"),
        "COOLDOWN": ("timing", "cooldown"),
    }

    def _phase_clock(self) -> dict:
        e = self.engine
        since = getattr(e, "_phase_since", None)
        limit = self._PHASE_LIMIT.get(e.state.phase)
        if since is None or limit is None:
            return {"phase_elapsed": None, "phase_total": None}
        try:
            total = float(getattr(getattr(e.cfg, limit[0]), limit[1]))
        except (AttributeError, TypeError, ValueError):
            return {"phase_elapsed": None, "phase_total": None}
        if total <= 0:
            return {"phase_elapsed": None, "phase_total": None}
        return {"phase_elapsed": round(max(0.0, time.monotonic() - since), 1),
                "phase_total": total}

    # ---------------- lifecycle ----------------

    def url(self, host: str | None = None) -> str:
        return f"http://{host or lan_ip()}:{self.port}/?k={self.token}"

    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?k={self.token}"

    def start(self) -> str | None:
        try:
            self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port),
                                             partial(_Handler, self))
        except OSError as e:
            log.error("web UI could not bind port %d: %s", self.port, e)
            return None
        self.httpd.daemon_threads = True
        self._thread = threading.Thread(target=self.httpd.serve_forever,
                                        name="autostream-web", daemon=True)
        self._thread.start()
        log.info("=" * 60)
        log.info("AutoStream UI: %s", self.url())
        log.info("=" * 60)
        return self.url()

    def request_started(self) -> None:
        with self._busy_lock:
            self._in_flight += 1

    def request_finished(self) -> None:
        with self._busy_lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._idle_since = time.monotonic()

    def idle_for(self) -> float:
        """Seconds since the last request finished. 0.0 while any is running.

        Read before shutting the server down: closing the socket out from
        under a response in flight reaches the browser as a connection reset,
        and the page cannot tell that apart from the request having failed.
        """
        with self._busy_lock:
            if self._in_flight > 0:
                return 0.0
            return time.monotonic() - self._idle_since

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:  # noqa: BLE001
                pass
            self.httpd = None
