"""The clipper's outside tools on a Mac: found where Homebrew puts them, and
installed with Homebrew when asked.

The Windows story in clips/deps.py is winget and a UAC prompt. The Mac one is
Homebrew, which installs into a prefix the user owns -- no password, no
prompt -- so offering to run it from the page is the same courtesy with less
ceremony. Nothing is installed without being asked for, exactly as there.

Without Homebrew the page names the commands instead, and links nothing: an
app that installs a package manager on somebody's behalf has overstepped.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

from ..clips import deps as _deps
from . import tools as _tools

log = logging.getLogger("autostream.macos.deps")

# What `brew install` is given for each tool. ffmpeg-full, not ffmpeg: the
# plain formula cannot draw text -- see macos/tools.py.
FORMULAE = {"ffmpeg": "ffmpeg-full", "tesseract": "tesseract"}

BREW_DIRS = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))

INSTALL_NOTE = ("AutoStream can install them for you with Homebrew. It needs no "
                "password, and can take several minutes.")
MANUAL_NOTE = ("Homebrew is not on this Mac, so these have to be installed by "
               "hand. Get Homebrew from brew.sh, then run:")


def brew() -> str:
    """Where Homebrew is, or ""."""
    found = shutil.which("brew")
    if found:
        return found
    for d in BREW_DIRS:
        if (d / "brew").is_file():
            return str(d / "brew")
    return ""


def tesseract() -> str:
    """Where Tesseract is. Raises ToolMissing with the Mac's fix."""
    found = _tools.find("tesseract")
    if found:
        return found
    raise _deps.ToolMissing(
        "Tesseract OCR was not found, and reading the kill feed needs it. "
        "Install it from the Clips page, or with:  " + _tools.TESSERACT_HINT)


def decorate(state: dict) -> dict:
    """deps.state() with the Mac's commands and wording in place of winget's.

    `install` on each tool and the two notes are read by the page in
    preference to its Windows defaults, so the Windows payload -- which has
    none of these keys -- renders exactly as it always has.
    """
    for t in state.get("tools", ()):
        t["install"] = "brew install " + FORMULAE.get(t["key"], t["key"])
    state["can_install"] = bool(brew())
    state["install_note"] = INSTALL_NOTE
    state["manual_note"] = MANUAL_NOTE
    ff = next((t for t in state.get("tools", ()) if t["key"] == "ffmpeg"), None)
    warning = _tools.text_warning(ff["path"]) if ff and ff.get("found") else ""
    if warning:
        state["text_warning"] = warning
    return state


class BrewInstaller(_deps.Installer):
    """deps.Installer, with Homebrew where winget was."""

    def start(self, keys: list[str]) -> tuple[bool, str]:
        if self.running:
            return False, "Something is already being installed."
        if not brew():
            return False, ("Homebrew is not on this Mac, so AutoStream cannot "
                           "install anything for you. Install the tools by "
                           "hand and reopen this page.")
        wanted = [t for t in _deps.TOOLS if t["key"] in keys]
        if not wanted:
            return False, "Nothing to install."
        self._set(state="running", tool="", message="Starting", error="",
                  done=[], started_at=time.time())
        self._thread = threading.Thread(target=self._run, args=(wanted,),
                                        name="autostream-deps", daemon=True)
        self._thread.start()
        return True, ""

    def _run(self, wanted: list[dict]) -> None:
        failed = []
        for t in wanted:
            self._set(tool=t["key"], message=f"Installing {t['label']} with Homebrew")
            ok, why = self._brew(t)
            _deps.forget()
            # Whether it is THERE now, not what brew printed -- the same rule,
            # and the same reason, as the winget path.
            if _deps._found(t["key"]):
                with self._lock:
                    self.done.append(t["key"])
                log.info("%s is installed%s", t["label"],
                         "" if ok else " (brew reported an error first)")
                continue
            failed.append(t["label"])
            log.warning("could not install %s: %s", t["label"], why)
            self._set(error=why or f"{t['label']} still is not there after installing.")
        if failed:
            self._set(state="failed", message=f"Could not install {', '.join(failed)}")
        else:
            self._set(state="done", tool="", error="",
                      message="Installed. Everything the clipper needs is here.")

    def _brew(self, tool: dict) -> tuple[bool, str]:
        formula = FORMULAE.get(tool["key"], tool["key"])
        try:
            p = subprocess.run([brew(), "install", formula], capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=3600)
        except subprocess.TimeoutExpired:
            return False, f"{tool['label']} took too long to install."
        except OSError as e:
            return False, f"Could not run Homebrew: {e}"
        if p.returncode == 0:
            # A different ffmpeg may now be the right one -- see tools.find.
            _tools.missing_filters.cache_clear()
            return True, ""
        out = f"{p.stdout or ''}\n{p.stderr or ''}"
        tail = "\n".join(x for x in out.strip().splitlines()[-4:] if x.strip())
        return False, f"Homebrew could not install {formula} ({p.returncode}).\n{tail}"[:600]
