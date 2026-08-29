"""Backend for the first-run setup wizard.

Each method maps to one wizard action and returns a JSON-able dict. Everything
is idempotent, so re-running setup never duplicates a stream or a token.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import shutil

from . import cfg, paths

log = logging.getLogger("autostream.setup")


class SetupFlow:
    def __init__(self):
        self._channel: str | None = None
        self._apps: list = []

    # ---------------- state shown to the UI ----------------

    def snapshot(self) -> dict:
        c = cfg.load()
        qh = c.rules.quiet_hours or []
        return {
            "client_secret": (paths.CLIENT_SECRET.name
                              if paths.CLIENT_SECRET.exists() else None),
            "channel": self._channel,
            "obs_password": c.obs.get("password", ""),
            "obs_port": c.obs.get("port", 4455),
            "obs_path": c.obs.get("path", ""),
            "privacy": c.youtube.privacy,
            "latency": c.youtube.latency,
            "switch_policy": c.youtube.switch_policy,
            "title": c.title.template,
            "arm_delay": c.timing.arm_delay,
            "abort_grace": c.timing.abort_grace,
            "cooldown": c.timing.cooldown,
            "max_session_hours": c.timing.max_session_hours,
            "quiet_from": (str(qh[0]) if len(qh) == 2 else ""),
            "quiet_to": (str(qh[1]) if len(qh) == 2 else ""),
            # as_dict() carries `exe`, which the branding step keys in-game
            # names on -- the same key the game index resolves a running game
            # with, so a name saved here is the one a detector looks up.
            "apps": [a.as_dict() for a in self._apps],
            "channel_name": c.thumbnail.channel_name,
            "logo": c.thumbnail.logo,
            "headline": c.thumbnail.headline,
            "subtitle": c.thumbnail.subtitle,
            "usernames": self._usernames(),
        }

    @staticmethod
    def _usernames() -> dict:
        """Whatever in-game names are already recorded, so stepping back
        through the wizard does not blank them."""
        try:
            games = (cfg.load_games().get("games") or {})
            return {k: v.get("username", "") for k, v in games.items()
                    if isinstance(v, dict) and v.get("username")}
        except Exception:  # noqa: BLE001
            return {}

    # ---------------- step 1: client secret ----------------

    def find_downloaded_secret(self) -> str | None:
        cands: list[str] = []
        for d in (os.path.expanduser("~/Downloads"), os.path.expanduser("~/Desktop")):
            cands += glob.glob(os.path.join(d, "client_secret*.json"))
        if not cands:
            return None
        return sorted(cands, key=os.path.getmtime, reverse=True)[0]

    def save_client_secret(self, raw: str) -> dict:
        raw = (raw or "").strip()
        if not raw:
            found = self.find_downloaded_secret()
            if found:
                paths.ensure_dirs()
                shutil.copy2(found, paths.CLIENT_SECRET)
                return {"ok": True, "setup": self.snapshot()}
            return {"ok": False, "error": "Paste the JSON, or download it first."}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"Not valid JSON ({e.msg})"}
        root = data.get("installed") or data.get("web")
        if not root or not root.get("client_id"):
            return {"ok": False,
                    "error": "That JSON has no client_id. Download the "
                             "Desktop app OAuth client, not an API key."}
        if data.get("web"):
            return {"ok": False,
                    "error": "That is a Web client. Create a Desktop app client instead."}
        paths.ensure_dirs()
        paths.CLIENT_SECRET.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            paths.CLIENT_SECRET.chmod(0o600)
        except OSError:
            pass
        return {"ok": True, "setup": self.snapshot()}

    # ---------------- step 2: OAuth ----------------

    def authorise(self) -> dict:
        from .state import State
        from .youtube import YouTube

        if not paths.CLIENT_SECRET.exists():
            return {"ok": False, "error": "No credentials saved yet."}
        try:
            yt = YouTube(cfg.load(), State.load())
            yt.authorise(interactive=True)
            self._channel = yt.channel_title()
            log.info("authorised as %s", self._channel)
            return {"ok": True, "setup": self.snapshot()}
        except Exception as e:  # noqa: BLE001
            log.exception("setup auth failed")
            return {"ok": False, "error": str(e)[:300]}

    # ---------------- the app window ----------------

    def webview2(self) -> dict:
        """Is the runtime here, and what does that mean for this user."""
        from . import webview2 as wv

        got = wv.version()
        return {"ok": True, "installed": bool(got), "version": got,
                "hint": ("AutoStream will open in its own window."
                         if got else
                         "AutoStream will open in your browser instead of its "
                         "own window. Everything works either way -- the app "
                         "window just needs a small Microsoft runtime that is "
                         "not on this PC.")}

    def install_webview2(self) -> dict:
        """Fetch and run Microsoft's installer, at the user's request."""
        from . import webview2 as wv

        r = wv.install()
        if r.get("ok"):
            r["hint"] = ("Installed. Restart AutoStream and it will open in "
                         "its own window.")
        return r

    # ---------------- step 3: OBS ----------------

    def test_obs(self, values: dict) -> dict:
        """Answer the wizard's Test button. Fast, or it is not a test.

        obs.probe() rather than obs.connect(): connect() retries three times
        with a twelve-second backoff and starts OBS if it cannot find it,
        which turned the first click a new user makes into a fifty-second
        freeze ending in a websocket error they cannot act on.
        """
        from .obs import Obs

        c = cfg.load()
        c["obs"] = dict(c["obs"])
        c["obs"]["password"] = str(values.get("password", ""))
        c["obs"]["port"] = int(values.get("port") or 4455)
        if values.get("path"):
            c["obs"]["path"] = str(values["path"])
        try:
            return Obs(cfg.Config(c)).probe()
        except Exception as e:  # noqa: BLE001 - a Test button never raises
            return {"ok": False, "reason": "error", "error": str(e)[:200]}

    # ---------------- generic section save ----------------

    def save_section(self, section: str, v: dict) -> dict:
        def _int(x, d):
            try:
                return int(str(x).strip())
            except (TypeError, ValueError):
                return d

        if section == "obs":
            cfg.save_field("obs", "password", str(v.get("password", "")))
            cfg.save_field("obs", "port", _int(v.get("port"), 4455))
            if v.get("path"):
                cfg.save_field("obs", "path", str(v["path"]))

        elif section == "stream":
            if v.get("privacy") in ("public", "unlisted", "private"):
                cfg.save_field("youtube", "privacy", v["privacy"])
            if v.get("latency") in ("normal", "low", "ultraLow"):
                cfg.save_field("youtube", "latency", v["latency"])
            if v.get("switch_policy") in ("rolling", "new_broadcast"):
                cfg.save_field("youtube", "switch_policy", v["switch_policy"])
            if v.get("title"):
                cfg.save_field("title", "template", str(v["title"])[:200])

        elif section == "timing":
            cfg.save_field("timing", "arm_delay", max(0, _int(v.get("arm_delay"), 30)))
            cfg.save_field("timing", "abort_grace", max(0, _int(v.get("abort_grace"), 20)))
            cfg.save_field("timing", "cooldown", max(0, _int(v.get("cooldown"), 300)))
            cfg.save_field("timing", "max_session_hours",
                           max(1, _int(v.get("max_session_hours"), 8)))
            a, b = str(v.get("quiet_from", "")).strip(), str(v.get("quiet_to", "")).strip()
            cfg.save_field("rules", "quiet_hours", [a, b] if (a and b) else [])
        elif section == "branding":
            fields = {
                "thumbnail.channel_name": str(v.get("channel_name", ""))[:80],
                "thumbnail.logo": str(v.get("logo", ""))[:400],
                "thumbnail.base_image": str(v.get("base_image", ""))[:400],
                "thumbnail.headline": str(v.get("headline", "") or "{game}")[:120],
                "thumbnail.subtitle": str(v.get("subtitle", ""))[:160],
                "thumbnail.enabled": bool(v.get("enabled")),
                "thumbnail.upload": bool(v.get("upload", True)),
            }
            cfg.save_fields(fields)
            # In-game names live in games.yaml beside the game they belong to,
            # not in config.yaml: they are per game, and a killfeed detector
            # has to look them up by the same key it resolved the game with.
            names = v.get("usernames") or {}
            if isinstance(names, dict) and names:
                games = cfg.load_games()
                table = games.setdefault("games", {})
                for key, who in names.items():
                    k = str(key).strip().lower()
                    if not k:
                        continue
                    entry = table.setdefault(k, {})
                    if isinstance(entry, dict):
                        entry["username"] = str(who).strip()[:60]
                cfg.save_games(games)
        else:
            return {"ok": False, "error": f"unknown section {section!r}"}
        return {"ok": True, "setup": self.snapshot()}

    # ---------------- step 4: apps ----------------

    def scan(self) -> dict:
        from . import catalog

        existing = {a.key: a for a in catalog.load()}
        found = catalog.discover_all()
        for a in found:
            if a.key in existing:
                a.stream = existing[a.key].stream
                a.scene = existing[a.key].scene
        self._apps = found
        log.info("scan found %d apps", len(found))
        return {"ok": True, "apps": [a.as_dict() for a in found]}

    def save_apps(self, apps: list) -> dict:
        from . import catalog

        keep = []
        known = set(catalog.App.__dataclass_fields__)
        for d in apps:
            if isinstance(d, dict) and d.get("name") and d.get("path"):
                keep.append(catalog.App(**{k: v for k, v in d.items() if k in known}))
        catalog.save(keep)
        self._apps = keep

        # keep games.yaml in step with what can auto-stream
        games = cfg.load_games()
        for a in keep:
            if a.stream and a.exe:
                games["games"].setdefault(a.exe, {"name": a.name, "scene": a.scene,
                                                  "blurb": ""})
        cfg.save_games(games)
        log.info("saved %d apps (%d streamable)", len(keep),
                 sum(1 for a in keep if a.stream))
        return {"ok": True, "count": len(keep)}

    # ---------------- step 5: finish ----------------

    def finish(self) -> dict:
        from .obs import Obs
        from .state import State
        from .youtube import YouTube

        c = cfg.load()
        state = State.load()
        try:
            yt = YouTube(c, state)
            yt.authorise(interactive=False)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"Not authorised: {str(e)[:200]}"}

        # reuse an existing stream if the id still resolves
        info = None
        if c.youtube.stream_id:
            info = yt.find_reusable_stream(c.youtube.stream_id)
        if info is None:
            try:
                info = yt.create_reusable_stream()
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": f"Could not create stream: {str(e)[:200]}"}
            cfg.save_field("youtube", "stream_id", info["id"])
            cfg.save_field("youtube", "ingestion_address", info["ingestion_address"])

        try:
            obs = Obs(cfg.load())
            obs.configure_stream(info["ingestion_address"], info["stream_key"])
            scenes = obs.scene_names()
            if scenes and not cfg.load().obs.default_scene:
                cfg.save_field("obs", "default_scene", scenes[0])
            obs.close()
        except Exception as e:  # noqa: BLE001
            return {"ok": False,
                    "error": f"Stream created, but OBS refused: {str(e)[:200]}"}

        try:
            from .gameindex import GameIndex

            idx = GameIndex(cfg.load())
            idx.refresh(force=True)
        except Exception:  # noqa: BLE001
            pass

        state.save()
        log.info("setup complete")
        return {"ok": True}
