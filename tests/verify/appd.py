r"""Start the REAL built app for a test, and give it something to work with.

Shared by tier 5 (drives it over HTTP) and tier 7 (drives it in a browser).
Both need the same thing: dist\AutoStream\AutoStream.exe, running against a
throwaway home so nothing of the user's is touched, answering on a free port.

youtube.enabled is off -- the app's own supported no-op mode: no broadcast, no
OAuth, no quota, and is_configured() is true so the setup wizard is skipped.
"""
from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUILT = REPO / "dist" / "AutoStream" / "AutoStream.exe"
TOKEN = "verify-build-token"
BOOT_TIMEOUT = 90.0


def running() -> list[str]:
    """Is the user's own AutoStream up? Checked, never killed -- it may be live."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq AutoStream.exe", "/NH"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln for ln in out.splitlines() if "AutoStream.exe" in ln]


def why_not() -> str:
    """Empty when the built app can be started here, else what is in the way."""
    if not BUILT.is_file():
        return f"no build at {BUILT} - run scripts\build.ps1 first"
    if running():
        return ("AutoStream is already running; quit it first "
                '(POST /api/cmd {"command":"quit"}). It is not killed here '
                "because it may be live or cutting clips.")
    return ""


def seed_home(home: Path, port: int, **extra) -> Path:
    import yaml

    for d in ("config", "secrets", "logs"):
        (home / d).mkdir(parents=True, exist_ok=True)
    values = {
        "youtube": {"enabled": False},
        "record": {"enabled": False},
        "rules": {"web_token": TOKEN, "web_port": port,
                  "tray_icon": False, "kill_switch_hotkey": ""},
        "logging": {"level": "INFO"},
    }
    for section, fields in extra.items():
        values.setdefault(section, {}).update(fields)
    (home / "config" / "config.yaml").write_text(
        yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    return home


def click_track(path: Path, seconds: float = 20.0, bpm: float = 120.0,
                rate: int = 22050) -> Path:
    """A WAV with a click on every beat. Something the reel can find a tempo in.

    Written here rather than shipped as a fixture file: a binary blob in the
    repo would be one more thing nobody can read in a diff, and this is eight
    lines of arithmetic.
    """
    beat = 60.0 / bpm
    n = int(seconds * rate)
    frames = bytearray()
    for i in range(n):
        t = i / rate
        since = t % beat
        # a short decaying tone on the beat, silence between
        v = math.sin(2 * math.pi * 1200 * t) * math.exp(-since * 60) if since < 0.05 else 0.0
        frames += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 20000))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return path


# NO CONSOLE WINDOW. Every subprocess a test starts -- the app, and the ffmpeg
# runs that seed it with footage -- pops a console on Windows unless it is told
# not to. A verify run makes dozens of them, so they flash over whatever the
# person at the keyboard is doing. The app suppresses its own the same way;
# see clips/killfeed.py _NO_WINDOW.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def start(home: Path, port: int, video_home: Path | None = None):
    """-> (base url, process). Raises RuntimeError if it never answers."""
    env = dict(os.environ)
    env["AUTOSTREAM_HOME"] = str(home)
    env["AUTOSTREAM_VIDEO_HOME"] = str(video_home or (home / "video"))
    # NO NATIVE DIALOGS, EVER, under test. Eight controls across four pages
    # reach the OS file picker, and an automated run presses controls it was
    # not told about -- so a list of ones to avoid fails open the day a ninth
    # is added. A picker also has no parent window here, so it opens over
    # whatever the person at the keyboard is doing AND blocks the thread
    # serving the page, which hangs the run rather than failing it.
    #
    # The app refuses to open one when this is set; see webui.clips_pick.
    env["AUTOSTREAM_NO_DIALOGS"] = "1"
    # Output goes to a FILE, not a pipe. A pipe nobody drains fills at 64KB and
    # then blocks the app mid-write: it stops answering, Quit included, and the
    # symptom is a test reporting that the app ignored Quit when the test was
    # the thing holding it shut. The file keeps the diagnostics either way.
    boot = home / "logs" / "boot.log"
    boot.parent.mkdir(parents=True, exist_ok=True)
    out = boot.open("wb")
    proc = subprocess.Popen([str(BUILT), "run"], env=env, cwd=str(BUILT.parent),
                            stdout=out, stderr=subprocess.STDOUT,
                            creationflags=NO_WINDOW)
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + BOOT_TIMEOUT
    last = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            said = boot.read_text(encoding="utf-8", errors="replace")
            raise RuntimeError(f"the built app exited with {proc.returncode} "
                               f"before it served anything:\n{out[-3000:]}")
        try:
            with urllib.request.urlopen(f"{base}/api/status?k={TOKEN}", timeout=3) as r:
                if r.status == 200:
                    return base, proc
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last = str(e)
        time.sleep(1.0)
    proc.kill()
    raise RuntimeError(f"the built app never answered on {base} in "
                       f"{BOOT_TIMEOUT:.0f}s (last: {last})")


def answering(base: str, timeout: float = 4.0) -> bool:
    """Is the app still serving? -> True/False, never raises.

    THE SYMPTOM OF A WINDOW. A modal dialog opened by the request thread --
    a file picker is the one that has done this -- blocks that thread, so the
    app stops answering while the window sits on the user's screen waiting to
    be clicked. The run then waits on a page that will never load, which looks
    like a slow test rather than something covering their desktop.
    """
    try:
        with urllib.request.urlopen(f"{base}/api/status?k={TOKEN}",
                                    timeout=timeout) as r:
            return r.status == 200
    except Exception:                                        # noqa: BLE001
        return False


def stop(base: str, proc) -> None:
    """Its own Quit -- what the tray and the rail button use. Killed only if it will not go."""
    try:
        req = urllib.request.Request(
            f"{base}/api/cmd?k={TOKEN}", data=json.dumps({"command": "quit"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:                                        # noqa: BLE001
        pass
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    # NOTHING LEFT ON SCREEN. A process blocked on a modal window ignores
    # Quit, and killing the parent leaves the window orphaned -- so the tree
    # goes, not just the process. This is the last thing standing between a
    # failed run and a dialog nobody can close.
    _kill_tree(proc)


def _kill_tree(proc) -> None:
    if proc.poll() is None or sys.platform != "win32":
        try:
            proc.kill()
        except Exception:                                    # noqa: BLE001
            pass
    if sys.platform != "win32":
        return
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=20,
                       creationflags=NO_WINDOW)
    except Exception:                                        # noqa: BLE001
        pass
