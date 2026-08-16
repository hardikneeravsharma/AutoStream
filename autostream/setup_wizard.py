"""Interactive one-time setup.

  1. OAuth  -> secrets/token.json
  2. Create the permanent reusable liveStream, save its id
  3. Push the stream key into OBS via obs-websocket
  4. Download the public game index
  5. Pre-seed games.yaml from your Steam / Epic libraries
  6. 60-second end-to-end smoke test on a PRIVATE broadcast
"""
from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import sys
import time

from . import cfg, paths
from .gameindex import GameIndex
from .obs import Obs, ObsUnavailable
from .state import State
from .youtube import YouTube

log = logging.getLogger("autostream.setup")

OK, BAD, INFO = "  [ok]", "  [!!]", "  [--]"


def _hr(title: str) -> None:
    print(f"\n{'=' * 62}\n  {title}\n{'=' * 62}")


def _ask(prompt: str, default: str = "y") -> bool:
    ans = input(f"{prompt} [{'Y/n' if default == 'y' else 'y/N'}] ").strip().lower()
    return (ans or default) in ("y", "yes")


# --------------------------------------------------------------------
# step 0 - client_secret.json
# --------------------------------------------------------------------

def step_client_secret() -> bool:
    _hr("1/6  OAuth client secret")
    if paths.CLIENT_SECRET.exists():
        print(f"{OK} found {paths.CLIENT_SECRET}")
        return True

    candidates: list[str] = []
    for d in (os.path.expanduser("~/Downloads"), os.path.expanduser("~/Desktop"), os.getcwd()):
        candidates += glob.glob(os.path.join(d, "client_secret*.json"))
    candidates = sorted(set(candidates), key=lambda p: os.path.getmtime(p), reverse=True)

    if candidates:
        src = candidates[0]
        print(f"{INFO} found a downloaded client secret:\n       {src}")
        if _ask("  Copy it into secrets/ ?"):
            paths.ensure_dirs()
            shutil.copy2(src, paths.CLIENT_SECRET)
            try:
                paths.CLIENT_SECRET.chmod(0o600)
            except OSError:
                pass
            print(f"{OK} copied to {paths.CLIENT_SECRET}")
            return True

    print(f"{BAD} No client_secret.json.")
    print("       Google Cloud Console -> Google Auth Platform -> Clients")
    print("       -> Create client -> Desktop app -> Download JSON")
    print(f"       Save it as: {paths.CLIENT_SECRET}")
    return False


# --------------------------------------------------------------------
# step 1 - auth
# --------------------------------------------------------------------

def step_auth(config, state) -> YouTube | None:
    _hr("2/6  Authorise with YouTube")
    yt = YouTube(config, state)
    try:
        yt.authorise(interactive=True)
        print(f"{OK} authorised as channel: {yt.channel_title()}")
        print(f"{INFO} token saved to {paths.TOKEN_FILE}")
        print(f"{INFO} REMINDER: publish your OAuth consent screen "
              "(Google Auth Platform -> Audience -> Publish App)")
        print("       or this token stops working in ~7 days.")
        return yt
    except Exception as e:  # noqa: BLE001
        print(f"{BAD} authorisation failed: {e}")
        return None


# --------------------------------------------------------------------
# step 2 - permanent stream
# --------------------------------------------------------------------

def step_stream(config, yt: YouTube) -> dict | None:
    _hr("3/6  Permanent reusable ingestion stream")
    existing = config.youtube.stream_id
    if existing:
        info = yt.find_reusable_stream(existing)
        if info:
            print(f"{OK} reusing existing stream {existing}")
            return info
        print(f"{INFO} configured stream {existing} no longer exists — creating a new one")

    try:
        info = yt.create_reusable_stream()
    except Exception as e:  # noqa: BLE001
        print(f"{BAD} could not create stream: {e}")
        return None

    cfg.save_field("youtube", "stream_id", info["id"])
    cfg.save_field("youtube", "ingestion_address", info["ingestion_address"])
    print(f"{OK} created stream {info['id']}")
    print(f"{INFO} ingest: {info['ingestion_address']}")
    print(f"{INFO} key   : {info['stream_key'][:6]}…{info['stream_key'][-4:]}")
    return info


# --------------------------------------------------------------------
# step 3 - OBS
# --------------------------------------------------------------------

def step_obs(config, stream: dict) -> Obs | None:
    _hr("4/6  Configure OBS")
    if not config.obs_password:
        print(f"{BAD} No obs-websocket password configured.")
        print("       OBS -> Tools -> WebSocket Server Settings -> enable + set password")
        print("       Then put it in config.yaml under obs.password, or set the env var")
        print(f"       {config.obs.password_env}")
        return None

    obs = Obs(config)
    try:
        obs.connect()
    except ObsUnavailable as e:
        print(f"{BAD} {e}")
        print("       Is OBS running? Is the WebSocket server enabled on port "
              f"{config.obs.port}?")
        return None

    obs.configure_stream(stream["ingestion_address"], stream["stream_key"])
    print(f"{OK} OBS stream settings written ({config.obs.service_mode})")

    scenes = obs.scene_names()
    print(f"{INFO} scenes found: {', '.join(scenes) or '(none)'}")

    games = cfg.load_games()
    missing = {v.get("scene") for v in (games.get("games") or {}).values()
               if v.get("scene")} - set(scenes)
    if config.obs.default_scene and config.obs.default_scene not in scenes:
        missing.add(config.obs.default_scene)
    if missing:
        print(f"{BAD} these scenes are referenced in config but do NOT exist in OBS:")
        for m in sorted(missing):
            print(f"       - {m}")
    return obs


# --------------------------------------------------------------------
# step 4 - game index + library scan
# --------------------------------------------------------------------

STEAM_LIB_RE = re.compile(r'"path"\s+"([^"]+)"')

# Substrings that mark an executable as tooling rather than the game itself.
# Anything matching is never a candidate for the game index.
HELPER_MARKERS = (
    "unins", "setup", "install", "vcredist", "dxsetup", "directx",
    "crashreport", "crashhandler", "errorreporter", "helper", "redist",
    "dotnet", "oalinst", "vconsole", "console", "editor", "server",
    "benchmark", "config", "updater", "update", "patch", "service",
    "activation", "cleanup", "diagnos", "report", "anticheat", "battleye",
    "easyanticheat", "prereq", "dependencies", "touchup", "shipping-cmd",
)


def _is_helper_exe(low: str) -> bool:
    """True for tooling/installer/service executables that are never the game.

    UE shipping binaries are exempt: 'DeltaForceClient-Win64-Shipping.exe'
    contains no marker, but something like 'VersionService.exe' does.
    """
    if low.endswith(("-win64-shipping.exe", "-win32-shipping.exe")):
        return False
    return any(m in low for m in HELPER_MARKERS)


def _steam_libraries() -> list[str]:
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

    libs: list[str] = []
    for root in dict.fromkeys(roots):
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
    return list(dict.fromkeys(libs))


def step_index(config) -> GameIndex:
    _hr("5/6  Game index + library scan")
    index = GameIndex(config)
    print(f"{INFO} downloading public game index…")
    index.refresh(force=True)
    index.reload()
    print(f"{OK} {len(index.public)} known executables, {len(index.steam_apps)} steam apps")

    libs = _steam_libraries()
    if not libs:
        print(f"{INFO} no Steam libraries found — add games to games.yaml by hand")
        return index
    print(f"{INFO} scanning {len(libs)} Steam library folder(s)…")

    found: dict[str, str] = {}       # exe -> source folder name
    unidentified: list[str] = []

    for lib in libs:
        try:
            game_dirs = os.listdir(lib)
        except OSError:
            continue
        for gd in game_dirs:
            gpath = os.path.join(lib, gd)
            if not os.path.isdir(gpath):
                continue

            exes: list[tuple[int, str]] = []
            for root, dirs, files in os.walk(gpath):
                if root[len(gpath):].count(os.sep) > 3:
                    dirs[:] = []
                    continue
                for f in files:
                    low = f.lower()
                    if not low.endswith(".exe") or _is_helper_exe(low):
                        continue
                    try:
                        exes.append((os.path.getsize(os.path.join(root, f)), low))
                    except OSError:
                        continue
            if not exes:
                continue

            # 1. an executable the public index already recognises is
            #    definitive - this is the ONLY fully trustworthy signal
            known = [e for _, e in exes if e in index.public]
            if known:
                for e in known:
                    found[e] = gd
                continue

            # 2. an Unreal shipping binary is a strong game signal; the Steam
            #    folder name is then a reliable title
            shipping = [e for _, e in exes if e.endswith(("-win64-shipping.exe",
                                                          "-win32-shipping.exe",
                                                          "-shipping.exe"))]
            if shipping:
                found[max(shipping, key=len)] = gd
                continue

            # 3. otherwise DON'T GUESS. "biggest .exe in the folder" picks
            #    debug consoles, installers and update services, and a wrong
            #    override is worse than no override because overrides win.
            unidentified.append(gd)

    games = cfg.load_games()
    blocked = {b.lower() for b in games.get("blocklist", [])}
    added = 0
    for exe, folder in sorted(found.items()):
        if exe in games["games"] or exe in blocked:
            continue
        games["games"][exe] = {
            "name": index.public.get(exe) or folder,
            "scene": None,
            "blurb": "",
        }
        added += 1

    if added:
        cfg.save_games(games)
        print(f"{OK} added {added} verified game executable(s) to config/games.yaml")
        print(f"{INFO} set `scene:` per game once you have more than one OBS scene")
    else:
        print(f"{INFO} nothing new to add")

    if unidentified:
        print(f"{INFO} {len(unidentified)} folder(s) had no recognisable game exe "
              "- skipped rather than guessed:")
        for u in sorted(unidentified)[:12]:
            print(f"         {u}")
        print(f"{INFO} run `detect`, launch one, and add the exe it prints by hand")

    index.reload()
    return index


# --------------------------------------------------------------------
# step 5 - smoke test
# --------------------------------------------------------------------

def step_smoke_test(config, yt: YouTube, obs: Obs) -> bool:
    _hr("6/6  End-to-end smoke test")
    if not _ask("  Run a 60-second PRIVATE test stream now?"):
        print(f"{INFO} skipped")
        return True

    bid = None
    try:
        bid = yt.create_broadcast("AutoStream smoke test — ignore",
                                  "Automated setup verification.", privacy="private")
        yt.bind(bid, config.youtube.stream_id)
        print(f"{OK} test broadcast {bid} created and bound")

        obs.start(scene=config.obs.default_scene or None)
        print(f"{INFO} OBS streaming — waiting for YouTube to see the bytes…")

        deadline = time.time() + config.timing.ingestion_timeout
        ok = False
        while time.time() < deadline:
            status, health = yt.stream_status(config.youtube.stream_id)
            sys.stdout.write(f"\r       status={status:<12} health={health:<8}")
            sys.stdout.flush()
            if status == "active":
                ok = True
                break
            time.sleep(3)
        print()

        if not ok:
            print(f"{BAD} YouTube never received the stream.")
            print("       Check: OBS stream key set? Firewall? Live streaming enabled")
            print("       on the channel (can take 24h to activate)?")
            return False

        print(f"{OK} ingestion active — holding 15s")
        time.sleep(15)
        print(f"{OK} smoke test passed")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"{BAD} smoke test failed: {e}")
        return False
    finally:
        try:
            obs.stop()
        except Exception:  # noqa: BLE001
            pass
        if bid:
            try:
                yt.delete_broadcast(bid)
                print(f"{INFO} test broadcast deleted")
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------

def run() -> int:
    paths.ensure_dirs()
    config = cfg.load()
    state = State.load()

    print("\n" + "*" * 62)
    print("  AutoStream setup")
    print("*" * 62)

    if not step_client_secret():
        return 1
    yt = step_auth(config, state)
    if yt is None:
        return 1

    config = cfg.load()
    stream = step_stream(config, yt)
    if stream is None:
        return 1

    config = cfg.load()
    obs = step_obs(config, stream)
    step_index(config)

    if obs is not None:
        step_smoke_test(config, yt, obs)
    else:
        print(f"\n{BAD} Skipping smoke test — OBS was not reachable.")

    state.save()
    _hr("Setup complete")
    print("  Next:")
    print("    python -m autostream detect     # watch detection for an evening")
    print("    python -m autostream run        # run the daemon in the foreground")
    print("    powershell -File scripts\\register_task.ps1   # start on login")
    print()
    print("  Privacy is currently:", config.youtube.privacy)
    print("  Leave it on 'unlisted' for the first week.\n")
    return 0
