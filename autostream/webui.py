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
import socket
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    """Setup is done when we have a token AND a permanent stream."""
    try:
        c = cfg.load()
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

    def do_GET(self):
        u = urlparse(self.path)
        if not self._authed(u.query):
            self._send(403, b"Add ?k=<token>. See the AutoStream log.",
                       "text/plain; charset=utf-8")
            return

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
                self._json({"phase": "IDLE", "apps": self.app.apps_payload()})
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
                if c not in ("stop", "pause", "resume", "toggle_pause", "quit"):
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

            # ---------- setup ----------
            elif p == "/api/setup/client_secret":
                self._json(self.app.setup.save_client_secret(str(b.get("json", ""))))
            elif p == "/api/setup/auth":
                self._json(self.app.setup.authorise())
            elif p == "/api/setup/obs_test":
                self._json(self.app.setup.test_obs(b))
            elif p == "/api/setup/save":
                self._json(self.app.setup.save_section(
                    str(b.get("section", "")), b.get("values") or {}))
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


class Server:
    def __init__(self, token: str, port: int = 8787, engine=None):
        self.token = token
        self.port = port
        self.engine = engine
        self.window = None            # set by cmd_run once the MainWindow exists
        self.httpd = None
        self._thread = None
        self._theme: str | None = None
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

        return [
            {"key": a.key, "name": a.name, "source": a.source, "stream": a.stream}
            for a in catalog.load()
        ]

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
            **self._phase_clock(),
        }

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

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:  # noqa: BLE001
                pass
            self.httpd = None
