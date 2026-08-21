"""Catalogue of launchable apps and games.

Discovers what is installed (Steam, Epic, Start Menu shortcuts) and records a
launch path for each, so the dashboard can offer "Open" and "Open & stream".

Stored in config/apps.yaml, which is a plain list the user can hand-edit.
"""
from __future__ import annotations

import fnmatch
import json
import logging
import ntpath
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field

import yaml

from . import paths

log = logging.getLogger("autostream.catalog")

APPS_FILE = paths.CONFIG_DIR / "apps.yaml"

# Executables that are never the thing a human means by "launch this"
HELPER_MARKERS = (
    "unins", "setup", "install", "vcredist", "dxsetup", "directx",
    "crashreport", "crashhandler", "errorreporter", "helper", "redist",
    "dotnet", "oalinst", "vconsole", "editor", "benchmark",
    "updater", "update", "patch", "service", "activation", "cleanup",
    "diagnos", "report", "anticheat", "battleye", "prereq", "dependencies",
    "touchup", "webview", "notification",
)


# Executables that are not games but launch one when given arguments. Their
# Start Menu shortcuts are how you actually start the game, so they must not be
# filtered out -- and RiotClientServices.exe is filtered by the plain helper
# rules, because "service" is a helper marker. That single substring is why
# VALORANT never appeared in the Library despite being installed.
#
# Every one of these takes the title as an argument and opens its own home
# screen without it, which is why discover_shortcuts has to keep sc.Arguments.
GAME_LAUNCHERS = {
    "riotclientservices.exe",       # Valorant, League of Legends
    "battle.net.exe",               # Blizzard
    "eadesktop.exe", "ealauncher.exe", "eadesktoplauncher.exe",
    "upc.exe", "ubisoftconnect.exe",
    "epicgameslauncher.exe",
    "steam.exe",
    "galaxyclient.exe",             # GOG
    "rockstarservice.exe", "launcher.exe",
}


def is_launcher(target: str) -> bool:
    return ntpath.basename(target or "").lower() in GAME_LAUNCHERS


def is_helper(name: str) -> bool:
    low = name.lower()
    if low.endswith(("-win64-shipping.exe", "-win32-shipping.exe")):
        return False
    return any(m in low for m in HELPER_MARKERS)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "app"


@dataclass
class App:
    key: str                 # stable id
    name: str                # display name
    path: str = ""           # exe or shortcut to launch
    args: str = ""
    exe: str = ""            # basename used to match a running process
    source: str = "manual"   # steam | epic | shortcut | manual
    stream: bool = True      # offer "Open & stream" for this one
    scene: str | None = None
    favourite: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- discovery

STEAM_LIB_RE = re.compile(r'"path"\s+"([^"]+)"')


# How deep to look inside a Steam game folder for its executable.
#
# This was 3, and 3 is not enough. Unreal titles that ship a launcher stub nest
# the real binary at Game\<Name>\Binaries\Win64\ -- depth 4 -- and Delta Force
# is exactly that shape: a 247 KB DeltaForceClient.exe at depth 1, which the
# 1 MB size floor correctly rejects, and the actual 551 MB
# DeltaForceClient-Win64-Shipping.exe at depth 4, which the walk never reached.
# The game was installed and simply never appeared.
#
# The cost of going deeper is bounded: the walk prunes below the limit, and
# only .exe names are stat-ed.
STEAM_WALK_DEPTH = 5


def _steam_roots() -> list[str]:
    roots: list[str] = []
    try:
        import winreg

        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ("SteamPath", "InstallPath"):
                        try:
                            roots.append(winreg.QueryValueEx(k, name)[0])
                        except OSError:
                            pass
            except OSError:
                pass
    except ImportError:
        pass
    for guess in (r"C:\Program Files (x86)\Steam", r"C:\Steam"):
        if os.path.isdir(guess):
            roots.append(guess)
    return list(dict.fromkeys(roots))


def discover_steam() -> list[App]:
    out: list[App] = []
    libs: list[str] = []
    for root in _steam_roots():
        common = os.path.join(root, "steamapps", "common")
        if os.path.isdir(common):
            libs.append(common)
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            try:
                txt = open(vdf, encoding="utf-8", errors="ignore").read()
                for p in STEAM_LIB_RE.findall(txt):
                    c = os.path.join(p.replace("\\\\", "\\"), "steamapps", "common")
                    if os.path.isdir(c):
                        libs.append(c)
            except OSError:
                pass

    # The registry hands back "c:/program files (x86)/steam" while the fallback
    # guess is "C:\Program Files (x86)\Steam". dict.fromkeys sees two different
    # strings and every library gets walked twice.
    seen_libs: set[str] = set()
    for lib in libs:
        canon = os.path.normcase(os.path.normpath(lib))
        if canon in seen_libs:
            continue
        seen_libs.add(canon)
        try:
            entries = os.listdir(lib)
        except OSError:
            continue
        for folder in entries:
            gdir = os.path.join(lib, folder)
            if not os.path.isdir(gdir):
                continue
            best: tuple[int, str] | None = None
            for root, dirs, files in os.walk(gdir):
                depth = root[len(gdir):].count(os.sep)
                if depth > STEAM_WALK_DEPTH:
                    dirs[:] = []
                    continue
                for f in files:
                    if not f.lower().endswith(".exe") or is_helper(f):
                        continue
                    full = os.path.join(root, f)
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        continue
                    # Unreal shipping binaries win outright
                    score = size + (10 ** 12 if f.lower().endswith("-shipping.exe") else 0)
                    if best is None or score > best[0]:
                        best = (score, full)
            if best and os.path.getsize(best[1]) > 1_000_000:
                out.append(App(key=slug(folder), name=folder, path=best[1],
                               exe=ntpath.basename(best[1]).lower(), source="steam"))
    return out


def discover_epic() -> list[App]:
    out: list[App] = []
    man = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                       "Epic", "EpicGamesLauncher", "Data", "Manifests")
    if not os.path.isdir(man):
        return out
    for f in os.listdir(man):
        if not f.lower().endswith(".item"):
            continue
        try:
            d = json.load(open(os.path.join(man, f), encoding="utf-8", errors="ignore"))
        except (OSError, json.JSONDecodeError):
            continue
        name = d.get("DisplayName")
        loc = d.get("InstallLocation")
        exe = d.get("LaunchExecutable")
        if not (name and loc and exe):
            continue
        full = os.path.join(loc, exe.replace("/", os.sep))
        if os.path.isfile(full):
            out.append(App(key=slug(name), name=name, path=full,
                           exe=ntpath.basename(full).lower(), source="epic"))
    return out


def discover_shortcuts(limit: int = 80) -> list[App]:
    """Start Menu .lnk targets — this is what surfaces non-game apps."""
    out: list[App] = []
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return out

    roots = [
        os.path.join(os.environ.get("APPDATA", ""),
                     r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("PROGRAMDATA", ""),
                     r"Microsoft\Windows\Start Menu\Programs"),
    ]
    shell = win32com.client.Dispatch("WScript.Shell")
    seen: set[str] = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if not f.lower().endswith(".lnk") or len(out) >= limit:
                    continue
                name = os.path.splitext(f)[0]
                # Skip our own shortcut. Offering "Open + stream" on AutoStream
                # itself is nonsense, and it appears the moment
                # scripts\make_shortcut.ps1 has been run.
                if is_helper(name) or name.lower() == "autostream":
                    continue
                lnk = os.path.join(dirpath, f)
                try:
                    sc = shell.CreateShortcut(lnk)
                    target = sc.TargetPath or ""
                    args = (sc.Arguments or "").strip()
                except Exception:  # noqa: BLE001
                    continue
                if (not target or not target.lower().endswith(".exe")
                        or not os.path.isfile(target)):
                    continue
                proxy = is_launcher(target) and bool(args)
                # A launcher invoked WITH arguments is starting a specific
                # title, so the helper rules do not apply to it. Without
                # arguments it is just the launcher's own shortcut, and the
                # ordinary rules should still reject it.
                if not proxy and is_helper(target):
                    continue

                launcher_exe = ntpath.basename(target).lower()
                # De-dupe on the GAME, not on the launcher. Keying on the
                # target would let Valorant and League collapse into one entry,
                # since both shortcuts point at RiotClientServices.exe.
                dedupe = f"{launcher_exe}|{args.lower()}" if proxy else launcher_exe
                if dedupe in seen:
                    continue
                seen.add(dedupe)

                # What to WATCH for is not what to launch. The launcher exits
                # or idles while the game runs under its own name, so keying
                # the launch intent on the launcher would mean "Open + stream"
                # started the game and then never went live.
                exe = _game_exe(name, target) if proxy else launcher_exe
                out.append(App(key=slug(name), name=name, path=target, args=args,
                               exe=exe, source="shortcut", stream=False))
    return out


def _game_exe(name: str, launcher: str) -> str:
    """Best guess at the process a launcher-started game will run under.

    Asked of the game index first, which already maps ~10,000 executables to
    display names and therefore knows that VALORANT runs as
    VALORANT-Win64-Shipping.exe. Falling back to the launcher's own name keeps
    the entry usable for plain launching even when the guess fails.
    """
    want = slug(name)
    try:
        from . import cfg, gameindex

        idx = gameindex.GameIndex(cfg.load())
        idx.reload()
        for exe, title in idx.public.items():
            if slug(title) == want:
                return exe.lower()
        for exe, ov in idx.overrides.items():
            if slug((ov or {}).get("name") or "") == want:
                return exe.lower()
    except Exception as e:  # noqa: BLE001 - a guess failing must not lose the app
        log.debug("could not resolve a game exe for %r: %s", name, e)
    return ntpath.basename(launcher).lower()


def discover_all() -> list[App]:
    apps: list[App] = []
    for fn in (discover_steam, discover_epic, discover_shortcuts):
        try:
            apps.extend(fn())
        except Exception as e:  # noqa: BLE001
            log.warning("%s failed: %s", fn.__name__, e)
    # de-dupe on executable, preferring games over shortcuts
    order = {"steam": 0, "epic": 1, "shortcut": 2, "manual": 3}
    best: dict[str, App] = {}
    for a in sorted(apps, key=lambda x: order.get(x.source, 9)):
        if a.exe and a.exe not in best:
            best[a.exe] = a
    return sorted(best.values(), key=lambda a: a.name.lower())


# ---------------------------------------------------------------- storage

def load() -> list[App]:
    if not APPS_FILE.exists():
        return []
    try:
        raw = yaml.safe_load(APPS_FILE.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        log.error("apps.yaml unreadable: %s", e)
        return []
    known = set(App.__dataclass_fields__)
    out = []
    for d in (raw.get("apps") or []):
        if isinstance(d, dict) and d.get("name"):
            out.append(App(**{k: v for k, v in d.items() if k in known}))
    return out


def save(apps: list[App]) -> None:
    paths.ensure_dirs()
    APPS_FILE.write_text(
        yaml.safe_dump({"apps": [a.as_dict() for a in apps]},
                       sort_keys=False, allow_unicode=True),
        encoding="utf-8")


# ---------------------------------------------------------------- launching

def launch(app: App) -> bool:
    """Start the app detached, so it outlives us."""
    if not app.path or not os.path.exists(app.path):
        log.error("cannot launch %s: %r does not exist", app.name, app.path)
        return False
    cmd = [app.path] + ([a for a in app.args.split()] if app.args else [])
    try:
        subprocess.Popen(
            cmd,
            cwd=os.path.dirname(app.path) or None,
            creationflags=(getattr(subprocess, "DETACHED_PROCESS", 0)
                           | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
            close_fds=True,
        )
        log.info("launched %s (%s)", app.name, app.path)
        return True
    except OSError as e:
        log.error("launch failed for %s: %s", app.name, e)
        return False


def find(apps: list[App], key: str) -> App | None:
    for a in apps:
        if a.key == key:
            return a
    return None
