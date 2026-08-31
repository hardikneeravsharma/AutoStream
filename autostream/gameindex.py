"""exe -> game name resolution.

Three sources, merged in priority order (yours always wins):
  1. config/games.yaml            -- hand written, authoritative
  2. Discord's detectable app list -- thousands of exe->name pairs
  3. Steam app list                -- appid -> name, for RunningAppID lookups
"""
from __future__ import annotations

import fnmatch
import json
import logging
import ntpath
import re
import time
from pathlib import Path
from dataclasses import dataclass

import requests

from . import cfg, paths

log = logging.getLogger("autostream.index")

# Discord's public detectable-apps endpoint, plus community mirrors as fallback.
DISCORD_SOURCES = [
    "https://discord.com/api/v9/applications/detectable",
    "https://discord.com/api/v10/applications/detectable",
]
# Steam's public app list is gone -- see steam_apps_from_disk. Names come from
# the install manifests instead, so there is nothing to fetch.

UA = {"User-Agent": "AutoStream/1.0 (+local game detection)"}


@dataclass
class GameHit:
    key: str                 # normalised exe name, e.g. "eldenring.exe"
    name: str                # display name
    scene: str | None = None
    blurb: str = ""
    privacy: str | None = None
    source: str = "override"
    # Your in-game name for THIS game. Per game because they genuinely differ,
    # and a killfeed-based kill detector needs the right one to tell your kills
    # from everyone else's. Also available to title and thumbnail templates.
    username: str = ""
    # A finished thumbnail for THIS game, used exactly as given -- nothing is
    # drawn over it. If you have made artwork for a game, the app has no
    # business compositing a headline across it. Games without one keep the
    # composite built from a live OBS frame.
    thumbnail: str = ""

    def __eq__(self, other):
        return isinstance(other, GameHit) and other.key == self.key


def _basename(p: str) -> str:
    p = (p or "").replace("\\", "/").strip().lower()
    return ntpath.basename(p.replace("/", "\\"))


def _parse_detectable(payload) -> dict[str, str]:
    """Turn a detectable-apps payload into {exe: game name}.

    Tolerant of schema drift and of community mirrors that wrap the list in an
    object — an index source going weird must degrade, never raise.
    """
    if isinstance(payload, dict):
        for k in ("applications", "games", "data", "items"):
            if isinstance(payload.get(k), list):
                payload = payload[k]
                break
    if not isinstance(payload, list):
        return {}

    out: dict[str, str] = {}
    for app in payload:
        if not isinstance(app, dict):
            continue
        name = str(app.get("name") or app.get("title") or "").strip()
        if not name:
            continue
        execs = app.get("executables") or app.get("aliases") or []
        if isinstance(execs, str):
            execs = [execs]
        for ex in execs:
            if isinstance(ex, str):
                exe_name, is_launcher, os_name = ex, False, "win32"
            elif isinstance(ex, dict):
                exe_name = ex.get("name") or ex.get("executable") or ""
                is_launcher = bool(ex.get("is_launcher"))
                os_name = ex.get("os", "win32")
            else:
                continue
            if is_launcher or os_name not in (None, "win32", "windows"):
                continue
            b = _basename(exe_name)
            if b.endswith(".exe"):
                out.setdefault(b, name)
    return out


def steam_apps_from_disk() -> dict[str, str]:
    """appid -> name, read from Steam's own install manifests.

    REPLACES A WEB ENDPOINT THAT NO LONGER EXISTS. Every documented form of
    ISteamApps/GetAppList now answers 404 -- v0002, v2 and v1, with or without
    a User-Agent -- while the rest of api.steampowered.com answers normally, so
    Valve retired it rather than the host being unreachable. Three requests
    failed on every start, logged three warnings, and left the appid table
    empty; the name lookup that depends on it then never fired, silently, and
    a Steam game the public index did not recognise stayed named after its
    executable.

    Every installed game already carries its name in
    steamapps/appmanifest_<appid>.acf, which is better than the web list ever
    was for this purpose: it is instant, it needs no network, it cannot be
    retired, and it covers exactly the games that could actually be running.

    The .acf is Valve's key-value text. Parsed with a regex rather than a VDF
    library, because two quoted tokens on a line is the whole grammar being
    used here and a dependency for that would be silly.
    """
    from .catalog import _steam_roots

    out: dict[str, str] = {}
    seen: set[str] = set()
    libs: list[Path] = []
    for root in _steam_roots():
        base = Path(root) / "steamapps"
        if base.is_dir():
            libs.append(base)
        # Games are routinely on a second drive; libraryfolders.vdf lists them.
        vdf = base / "libraryfolders.vdf"
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for extra in re.findall(r'"path"\s+"([^"]+)"', text):
            more = Path(extra.replace("\\\\", "\\")) / "steamapps"
            if more.is_dir():
                libs.append(more)

    for lib in libs:
        key = str(lib).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            manifests = list(lib.glob("appmanifest_*.acf"))
        except OSError:
            continue
        for man in manifests:
            try:
                text = man.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            name = re.search(r'"name"\s+"([^"]*)"', text)
            if appid and name and name.group(1).strip():
                out[appid.group(1)] = name.group(1).strip()
    return out


class GameIndex:
    def __init__(self, config):
        self.cfg = config
        self.overrides: dict[str, dict] = {}
        self.blocklist: set[str] = set()
        self.veto_patterns: list[str] = []
        self.public: dict[str, str] = {}      # exe -> name
        self.steam_apps: dict[str, str] = {}  # appid -> name
        self.reload()

    # ---------------- loading ----------------

    def reload(self) -> None:
        g = cfg.load_games()
        self.overrides = {k.lower(): (v or {}) for k, v in (g.get("games") or {}).items()}
        self.blocklist = {str(x).lower() for x in (g.get("blocklist") or [])}
        self.veto_patterns = [str(x).lower() for x in (g.get("never_stream_if_running") or [])]
        self._load_cache()
        log.info(
            "index: %d overrides, %d public entries, %d blocked",
            len(self.overrides), len(self.public), len(self.blocklist),
        )

    def _load_cache(self) -> None:
        if not paths.INDEX_CACHE.exists():
            self.public, self.steam_apps = {}, {}
            return
        try:
            data = json.loads(paths.INDEX_CACHE.read_text(encoding="utf-8"))
            self.public = data.get("executables", {}) or {}
            self.steam_apps = data.get("steam_apps", {}) or {}
        except (json.JSONDecodeError, OSError) as e:
            log.warning("index cache unreadable (%s) — starting empty", e)
            self.public, self.steam_apps = {}, {}

    # ---------------- refresh ----------------

    def refresh(self, force: bool = False) -> bool:
        """Fetch public sources. Returns True if anything was written."""
        max_age = self.cfg.timing.index_refresh_days * 86400
        if not force and paths.INDEX_CACHE.exists():
            if time.time() - paths.INDEX_CACHE.stat().st_mtime < max_age:
                return False

        log.info("refreshing public game index…")
        execs: dict[str, str] = {}
        for url in DISCORD_SOURCES:
            try:
                r = requests.get(url, timeout=(5, 12), headers=UA)
                r.raise_for_status()
                execs.update(_parse_detectable(r.json()))
                if execs:
                    log.info("fetched %d executables from %s", len(execs), url)
                    break
                log.warning("source %s returned no usable entries", url)
            except Exception as e:  # noqa: BLE001 - any network/parse failure is non-fatal
                log.warning("game index source failed (%s): %s", url, e)

        try:
            steam = steam_apps_from_disk()
        except Exception as e:  # noqa: BLE001 - naming is a nicety, not the job
            log.info("could not read Steam's install manifests (%s)", e)
            steam = {}
        if steam:
            log.info("read %d installed steam game(s) from Steam's own "
                     "manifests", len(steam))

        if not execs and not steam:
            log.warning("index refresh produced nothing — keeping existing cache")
            return False

        # Never lose data on a partial fetch
        merged_exec = {**self.public, **execs}
        merged_steam = {**self.steam_apps, **steam}
        paths.ensure_dirs()
        paths.INDEX_CACHE.write_text(
            json.dumps(
                {"fetched": time.time(), "executables": merged_exec, "steam_apps": merged_steam},
                indent=0,
            ),
            encoding="utf-8",
        )
        self.public, self.steam_apps = merged_exec, merged_steam
        return True

    # ---------------- lookup ----------------

    def is_blocked(self, exe: str) -> bool:
        exe = exe.lower()
        if exe in self.blocklist:
            return True
        return any(fnmatch.fnmatch(exe, p) for p in self.blocklist if "*" in p)

    def is_veto(self, exe: str) -> bool:
        exe = exe.lower()
        return any(fnmatch.fnmatch(exe, p) if "*" in p else exe == p
                   for p in self.veto_patterns)

    def lookup(self, exe: str) -> GameHit | None:
        exe = exe.lower()
        if exe in self.overrides:
            o = self.overrides[exe]
            # An override may set only SOME fields -- saving an in-game name
            # creates an entry with a username and nothing else. Falling
            # straight through to a title-cased executable there would rename
            # VALORANT to "Valorant-Win64-Shipping", so the public index is
            # consulted before that last resort.
            return GameHit(
                key=exe,
                name=(o.get("name") or o.get("title_as") or self.public.get(exe)
                      or exe.removesuffix(".exe").title()),
                scene=o.get("scene"),
                blurb=o.get("blurb", ""),
                privacy=o.get("privacy"),
                source="override",
                username=str(o.get("username") or ""),
                thumbnail=str(o.get("thumbnail") or ""),
            )
        if exe in self.public:
            return GameHit(key=exe, name=self.public[exe], source="public")
        return None

    def steam_name(self, appid: str) -> str | None:
        return self.steam_apps.get(str(appid))

    def coverage_warning(self) -> str | None:
        """Detection is blind if we know about zero games. Say so loudly."""
        if self.overrides:
            return None
        if self.public:
            return None
        return (
            "Game index is EMPTY — nothing will ever be detected. The public "
            "index download failed and config/games.yaml has no entries. Fix with: "
            "`python -m autostream refresh`, or add your games by hand to "
            "config/games.yaml (run `python -m autostream detect` to see exe names)."
        )
