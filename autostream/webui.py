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
        given = (parse_qs(query).get("k") or [""])[0]
        return hmac.compare_digest(given, self.app.token)

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
        """Stream one clip to a <video> tag, honouring Range.

        RANGE IS NOT OPTIONAL HERE. Without it the browser can play a clip from
        the start and nothing else: dragging the scrub bar, stepping a frame,
        or starting anywhere but zero all need a byte range, and a player that
        cannot seek is not a player. Chrome also re-requests the tail of an mp4
        to find the moov atom before it will play at all.
        """
        p = Path(path)
        # Only ever inside the clips folder. The page builds these paths, but
        # the page is not the only thing that can call this.
        root = self.app._clips_dir(cfg.load()).resolve()
        try:
            if not p.resolve().is_relative_to(root):
                self._json({"error": "That file is not in the clips folder."}, 403)
                return
        except OSError:
            self._json({"error": "No such file."}, 404)
            return
        if not p.is_file() or p.suffix.lower() not in (".mp4", ".m4v", ".webm"):
            self._json({"error": "No such clip."}, 404)
            return

        size = p.stat().st_size
        ctype = "video/webm" if p.suffix.lower() == ".webm" else "video/mp4"
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
                (q.get("path") or [""])[0], _float((q.get("t") or ["0"])[0], 0.0))
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
                        self.app.window.request_quit()
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
                self._json(self.app.clips_forget(str(b.get("recording_path", "")),
                                                 _int(b.get("session"), -1)))

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
            "edit": self._edit_status(),
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

    def clips_sessions(self) -> dict:
        """Past streams, plus what the Clips page needs to decide about each."""
        from . import clips, history
        from .clips import profiles

        cfg_now = cfg.load()
        clips.set_ffmpeg_path(cfg_now.clips.ffmpeg_path or None)

        rows = history.annotate(history.read(limit=200))
        table = profiles.load_all()
        found = self._kills_by_source(cfg_now)
        runs = self._runs_by_source(cfg_now)
        for r in rows:
            prof = profiles.for_game(r.get("game_key"), r.get("game"))
            r["profile"] = prof.label if prof else None
            r["can_scan"] = bool(prof and prof.exists())
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
            r["blocked"] = prof.why_not() if prof else ""
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

                got = valorant_match.state(float(r.get("started") or 0),
                                           _rec_seconds(r))
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
            "profiles": profiles.listing(),
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

    def _kills_by_source(self, config=None) -> dict[str, int]:
        """How many kills a previous run already found per recording, so the
        list can say so and the next run can skip the slowest step.

        Looks in the CONFIGURED output folder, not paths.CLIPS_DIR. Those two
        diverge the moment clips.output_dir is set, and the symptom is silent:
        every rescan pays the slowest step again for no visible reason.
        """
        out: dict[str, int] = {}
        root = self._clips_dir(config or cfg.load())
        try:
            for sidecar in root.glob("*/session.json"):
                data = json.loads(sidecar.read_text(encoding="utf-8"))
                src = self._same_file(data.get("source") or "")
                if src:
                    out[src] = max(out.get(src, 0), len(data.get("kills") or []))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return out

    def _runs_by_source(self, config=None) -> dict[str, dict]:
        """The NEWEST finished run per recording. -> {source: {folder, clips, when}}

        Newest by modification time, for the same reason the kill cache is --
        see _cached_kills. The oldest run of a recording is the one whose
        clips are most likely to be wrong.
        """
        out: dict[str, dict] = {}
        root = self._clips_dir(config or cfg.load())
        try:
            sidecars = sorted(root.glob("*/session.json"),
                              key=lambda f: f.stat().st_mtime, reverse=True)
        except OSError:
            return out
        for sidecar in sidecars:
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            src = self._same_file(data.get("source") or "")
            if not src or src in out:
                continue          # a newer run already answered for this one
            folder = sidecar.parent
            made = 0
            try:
                made = len(list((folder / "vertical").glob("*.mp4"))) or \
                    len(list((folder / "clips").glob("*.mp4")))
            except OSError:
                pass
            if made:
                out[src] = {"folder": str(folder), "clips": made,
                            "when": int(sidecar.stat().st_mtime)}
        return out

    def clips_existing(self, folder: str) -> dict:
        """One finished run's clips, for looking at before cutting again."""
        if not folder:
            return {"error": "No folder given."}
        f = Path(folder)
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
                "game": plan.get("game", ""),
                "when": int(man.stat().st_mtime),
                "montage": (data or {}).get("montage") if isinstance(data, dict) else None,
                "clips": clips}

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

        cached = self._cached_kills(path, c)
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

    def _cached_kills(self, source: Path, config=None) -> list | None:
        """Kills found by an earlier run of the same recording.

        Scanning is by far the slowest step, so re-cutting the same stream with
        different lengths or thresholds should not pay for it twice.
        """
        root = self._clips_dir(config or cfg.load())
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
                        == self._same_file(str(source)) and data.get("kills")):
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
            trim_start=_num("trim_start"), trim_end=_num("trim_end"))
        if not ed.start(spec):
            return {"error": "Another clip is being re-rendered."}
        log.info("re-rendering %s in %s", name, folder.name)
        return {"ok": True, "name": name}

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

    def clip_frame(self, path: str, at: float) -> tuple[bytes, str | None]:
        """One PNG frame, for the calibrator's frame picker."""
        from . import clips

        clips.set_ffmpeg_path(cfg.load().clips.ffmpeg_path or None)
        if not clips.available():
            return b"", "ffmpeg is not available."
        src = Path(path)
        if not src.exists():
            return b"", "That recording is no longer on disk."
        import tempfile

        from .clips.cutter import poster

        tmp = Path(tempfile.mkdtemp(prefix="asframe_"))
        try:
            png = poster(src, max(0.0, at), tmp / "f.png", width=960)
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
        return {"ok": True, "path": str(path), "name": path.name,
                "size_mb": round(path.stat().st_size / (1024 * 1024))}

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
            out.append({
                "game_key": prof.key,
                "game": prof.label,
                "profile": prof.label,
                "can_scan": prof.exists(),
                "scan_mode": prof.mode,
                "rounds": bool(getattr(prof, "rounds", False)),
                "counts_assists": bool(prof.counts_assists),
                "blocked": prof.why_not(),
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

    def clips_forget(self, recording_path: str, session: int) -> dict:
        """Drop a history row whose recording is gone. Never deletes video."""
        from . import history

        rows = history.read()
        keep = [r for r in rows
                if not (r.get("recording_path") == recording_path
                        and (session < 0 or r.get("session") == session))]
        if len(keep) == len(rows):
            return {"error": "No matching entry."}
        history.rewrite(keep)
        return {"ok": True, "removed": len(rows) - len(keep)}

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
