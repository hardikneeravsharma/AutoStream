"""The Mac app updating itself: the .dmg in, the running .app swapped out.

The check, the download and the checksum are the Windows updater's own
(updates.py, webui.update_check/update_download): on a Mac updates.latest()
simply chooses this Mac's .dmg instead of the Windows installer. What a Mac
lacks is an installer to hand over to, so this is that step:

  1. mount the downloaded .dmg and copy the new AutoStream.app beside the
     running one -- the same folder, so the swap below is a rename, never a
     copy that can be caught half-done;
  2. start a small script, detached, that waits for this process to exit,
     renames the old app aside, the new one into place, deletes the old one,
     and opens the new one -- putting the old one back if the rename fails;
  3. quit, exactly as the Windows path does after starting its installer.

WHY NO NOTARISATION IS NEEDED. Gatekeeper checks apps that carry the
quarantine flag, which a browser adds to what it downloads. A file fetched by
this process gets none, so the swapped-in app opens without "Open Anyway" --
the flag is also stripped from the copy, in case anything added one. The app
is ad-hoc signed, which is all Apple Silicon asks to run it.

THE COST OF AN AD-HOC SIGNATURE. macOS ties folder-access grants (Documents,
Desktop, Downloads) to the app's signature, and an ad-hoc one changes every
build, so it may ask for those again after an update. A Developer ID removes
that; nothing here can.
"""
from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .. import paths

log = logging.getLogger("autostream.macos.updates")

# This Mac's release asset: AutoStream-<v>-macos-<arch>.dmg from v1.78.2
# (scripts/release_assets.py), AutoStream-macos-<arch>.dmg in v1.78.1.
ARCH = "arm64" if platform.machine() == "arm64" else "x86_64"
DMG = re.compile(rf"^AutoStream-(?:[\d.]+-)?macos-{ARCH}\.dmg$", re.I)
STAGED = ".AutoStream-update.app"

# Waits for the old process (at most two minutes), then swaps. "$1" pid,
# "$2" the running app, "$3" the staged one. Rolls back if the rename fails.
SWAP = """#!/bin/sh
pid="$1"; app="$2"; new="$3"; n=0
while kill -0 "$pid" 2>/dev/null; do
  n=$((n + 1)); [ "$n" -gt 240 ] && exit 1
  sleep 0.5
done
old="$app.old-$$"
mv "$app" "$old" || exit 1
if mv "$new" "$app"; then rm -rf "$old"; else mv "$old" "$app"; exit 1; fi
[ -n "$AUTOSTREAM_NO_RELAUNCH" ] || open "$app"
"""


def pick(names) -> str | None:
    """This Mac's .dmg among a release's file names, the newest if several."""
    from ..updates import version_of

    found = [n for n in names if DMG.match(n)]
    return max(found, key=version_of, default=None)


def running_app() -> Path | None:
    """The .app this process runs from, or None from a source checkout."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()        # .app/Contents/MacOS/AutoStream
    app = exe.parents[2] if len(exe.parents) > 2 else exe
    return app if app.suffix == ".app" else None


def stage(dmg: Path, into: Path) -> None:
    """Copy the AutoStream.app inside `dmg` to `into`. Raises RuntimeError."""
    mount = Path(tempfile.mkdtemp(prefix="autostream-update-"))
    try:
        r = subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-quiet",
                            "-mountpoint", str(mount), str(dmg)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode:
            raise RuntimeError(f"could not open the download: {r.stderr.strip()[:200]}")
        try:
            src = mount / "AutoStream.app"
            if not src.is_dir():
                raise RuntimeError("the download has no AutoStream.app in it")
            subprocess.run(["rm", "-rf", str(into)], check=False)
            # ditto, not shutil: it keeps the symlinks and the executable
            # bits an .app is made of.
            r = subprocess.run(["ditto", str(src), str(into)],
                               capture_output=True, text=True, timeout=600)
            if r.returncode:
                raise RuntimeError(f"could not copy the new version: {r.stderr.strip()[:200]}")
        finally:
            subprocess.run(["hdiutil", "detach", "-quiet", str(mount)],
                           capture_output=True, timeout=120)
    finally:
        try:
            mount.rmdir()
        except OSError:
            pass
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(into)],
                   capture_output=True)


def install(server, dmg: Path, version: str) -> dict:
    """webui.update_install's last step on a Mac: stage, hand over, quit."""
    app = running_app()
    if app is None:
        return {"error": "This is AutoStream running from source, which updates "
                         "with git pull rather than from a release."}
    if dmg.suffix.lower() != ".dmg":
        return {"error": f"{dmg.name} is not a Mac disk image."}
    if not os.access(app.parent, os.W_OK):
        return {"error": f"AutoStream cannot write to {app.parent}, so it cannot "
                         f"replace itself. Open {dmg.name} and drag the new "
                         f"version to Applications yourself."}
    new = app.parent / STAGED
    try:
        stage(dmg, new)
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        return {"error": f"Could not prepare the update: {e}"}
    script = paths.DATA_HOME / "updates" / "swap.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(SWAP, encoding="utf-8")
    try:
        subprocess.Popen(["/bin/sh", str(script), str(os.getpid()), str(app), str(new)],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return {"error": f"Could not start the update: {e}"}
    log.info("handing over to the swap script: %s -> %s", new.name, app)

    # A moment later, not here, for the reason webui.update_install gives:
    # the reply has to reach the page before the window goes.
    def leave():
        time.sleep(1.5)
        if getattr(server, "window", None) is not None:
            server.window.request_quit("an update is being installed")

    threading.Thread(target=leave, name="autostream-handover", daemon=True).start()
    return {"ok": True, "version": version}
