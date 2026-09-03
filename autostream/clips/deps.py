r"""The tools the clipper needs from outside Python, and putting them there.

WHY THIS EXISTS
    Two of the clipper's dependencies are not pip packages: ffmpeg, which
    every clip needs, and Tesseract, which games whose kills are READ off the
    kill feed need. Both were discovered at the moment they were first
    used -- which for Tesseract is several minutes into a scan, after the file
    was picked, the game chosen and the run started. "Tesseract OCR was not
    found" at that point is a true sentence delivered at the least useful
    moment there is, and the fix it named was a command line to paste.

    So they are checked BEFORE anything is offered, and installed from the app.

WHY WINGET AND NOT A BUNDLED COPY
    ffmpeg is about 80 MB and Tesseract about 50, against a 30 MB app. Putting
    them in the download would roughly quadruple it for features not everyone
    uses -- the same reasoning that keeps numpy and ffmpeg optional in the
    first place. winget ships with Windows 10 1809 and later, installs the
    same builds the README already recommends, and keeps them updated.

WHY NOT SILENTLY
    Both are machine-wide installs and Windows raises a UAC prompt for them.
    A prompt from a process the user cannot see is how software gets mistaken
    for something worse, so nothing here starts without being asked for, and
    what is about to be installed is named before it is.

IMPORT-LIGHT ON PURPOSE
    `clips.status()` calls into here on every Clips page load, and the whole
    point of that function is to answer before numpy is imported. Nothing in
    this module imports anything heavy.
"""
from __future__ import annotations

import functools
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("autostream.clips.deps")

# Windows only: keeps a console window from flashing up over whatever the user
# is doing. The frozen build is windowed, so without it every probe blinks a
# black box.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Where the UB-Mannheim installer -- the usual Windows Tesseract build -- puts
# itself. It does NOT add itself to PATH, so shutil.which finds nothing on a
# machine where it is plainly installed.
_TESSERACT_DIRS = (
    Path(r"C:/Program Files/Tesseract-OCR"),
    Path(r"C:/Program Files (x86)/Tesseract-OCR"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Tesseract-OCR",
)


class ToolMissing(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def tesseract() -> str:
    """Where Tesseract is. Raises ToolMissing with what to do about it.

    Not tools.binary(): that one searches ffmpeg's install locations and its
    failure message tells you to install ffmpeg, which would be actively
    misleading here.
    """
    found = shutil.which("tesseract")
    if found:
        return found
    exe = "tesseract.exe" if os.name == "nt" else "tesseract"
    for root in _TESSERACT_DIRS:
        if (root / exe).is_file():
            return str(root / exe)
    raise ToolMissing(
        "Tesseract OCR was not found, and reading the kill feed needs it. "
        "Install it from the Clips page, or with:  "
        "winget install --id UB-Mannheim.TesseractOCR")


def have_tesseract() -> bool:
    try:
        tesseract()
        return True
    except ToolMissing:
        return False


def have_pytesseract() -> bool:
    """The Python wrapper, which is a pip package and is bundled in a build."""
    try:
        import pytesseract  # noqa: F401
        return True
    except ImportError:
        return False


def ocr_ready() -> bool:
    """Both halves. Either one missing means a kill feed cannot be read."""
    return have_tesseract() and have_pytesseract()


def ocr_why_not() -> str:
    """Empty when a feed can be read, otherwise what is in the way."""
    if not have_tesseract():
        return ("Tesseract OCR is not installed on this PC, and reading a "
                "kill feed needs it.")
    if not have_pytesseract():
        return ("The pytesseract package is missing from this install of "
                "AutoStream, and reading a kill feed needs it.")
    return ""


def _ffmpeg() -> str:
    from .tools import FfmpegMissing, binary

    try:
        return binary("ffmpeg")
    except FfmpegMissing:
        return ""


# Everything the clipper needs that pip cannot provide. `blocks` says what
# stops working without it, which is the difference between a wall and a
# footnote: no ffmpeg means no clips at all, no Tesseract means no clips for
# ONE family of games and no effect whatsoever on the rest.
TOOLS: tuple[dict, ...] = (
    {
        "key": "ffmpeg",
        "label": "FFmpeg",
        "winget": "Gyan.FFmpeg",
        "size_mb": 80,
        "blocks": "all",
        "why": "Reads your recording and writes every clip. Nothing on the "
               "Clips page works without it.",
    },
    {
        "key": "tesseract",
        "label": "Tesseract OCR",
        "winget": "UB-Mannheim.TesseractOCR",
        "size_mb": 50,
        "blocks": "killfeed",
        "why": "Reads the kill feed, which is how Counter-Strike 2 kills are "
               "found. Games with a kill marker on screen -- Delta Force -- "
               "and games that mark your own rows -- VALORANT -- do not need "
               "it.",
    },
)


def _found(key: str) -> str:
    if key == "ffmpeg":
        return _ffmpeg()
    if key == "tesseract":
        try:
            return tesseract()
        except ToolMissing:
            return ""
    return ""


def winget() -> str:
    """Where winget is, or "" -- which is a real answer on Windows 10 1803."""
    return shutil.which("winget") or ""


def missing_keys() -> list[str]:
    """Which tools are not on this PC."""
    return [t["key"] for t in TOOLS if not _found(t["key"])]


def state() -> dict:
    """What is installed, what is not, and what each absence costs.

    -> {ok, tools: [...], missing: [...], can_install, installing}

    `ok` is about ffmpeg alone. A missing Tesseract is reported in full but
    does not make the page unusable, because for most games it changes
    nothing -- calling that "not ready" would be a lie told to every Delta
    Force user on the machine.
    """
    tools = []
    for t in TOOLS:
        path = _found(t["key"])
        tools.append({**t, "found": bool(path), "path": path})
    missing = [t["key"] for t in tools if not t["found"]]
    return {
        "ok": "ffmpeg" not in missing,
        "tools": tools,
        "missing": missing,
        # No winget means the buttons would fail rather than work, so the page
        # falls back to naming the download instead of offering to run it.
        "can_install": bool(winget()) and sys.platform == "win32",
        "installing": installer().running,
    }


def forget() -> None:
    """Drop the cached lookups, so a fresh install is seen without a restart.

    Both caches exist because discovery walks directories, and both would
    otherwise keep answering "missing" for the rest of the session -- which
    is precisely the moment the answer has just changed.
    """
    tesseract.cache_clear()
    try:
        from .tools import binary

        binary.cache_clear()
    except ImportError:
        pass


class Installer:
    """Runs winget on a worker thread and publishes what it is doing.

    NOT ON THE REQUEST THREAD. A winget install is minutes, and the server
    speaks HTTP/1.1 with keep-alive to a browser that opens about six
    connections -- pinning one open for that long is indistinguishable from a
    hang. The POST starts this and returns; the page reads progress off the
    status poll it already makes every two seconds, so it also survives a
    reload.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.state = "idle"          # idle|running|done|failed
        self.tool = ""
        self.message = ""
        self.error = ""
        self.done: list[str] = []
        self.started_at = 0.0

    @property
    def running(self) -> bool:
        t = self._thread
        return bool(t and t.is_alive())

    def status(self) -> dict | None:
        """None when it has never run, so the status poll stays empty."""
        with self._lock:
            if self.state == "idle":
                return None
            return {
                "state": self.state,
                "tool": self.tool,
                "message": self.message,
                "error": self.error,
                "done": list(self.done),
                "elapsed": int(time.time() - self.started_at)
                if self.started_at else 0,
            }

    def _set(self, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def start(self, keys: list[str]) -> tuple[bool, str]:
        """Begin installing. -> (started, why not)."""
        if self.running:
            return False, "Something is already being installed."
        if sys.platform != "win32":
            return False, "Installing from here is Windows only."
        if not winget():
            return False, ("winget is not on this PC, so AutoStream cannot "
                           "install anything for you. Install the tools by "
                           "hand and reopen this page.")
        wanted = [t for t in TOOLS if t["key"] in keys]
        if not wanted:
            return False, "Nothing to install."
        self._set(state="running", tool="", message="Starting", error="",
                  done=[], started_at=time.time())
        self._thread = threading.Thread(
            target=self._run, args=(wanted,),
            name="autostream-deps", daemon=True)
        self._thread.start()
        return True, ""

    def _run(self, wanted: list[dict]) -> None:
        failed = []
        for t in wanted:
            self._set(tool=t["key"],
                      message=f"Installing {t['label']} - Windows may ask for "
                              f"permission")
            ok, why = self._winget(t)
            forget()
            # WHETHER THE TOOL IS THERE NOW, not what winget printed. The two
            # disagree in both directions: winget reports failure for a package
            # it had already installed, and reports success for a machine-scope
            # install whose PATH change this process will never see. Discovery
            # looks in the install directories themselves, so it is the only
            # answer that means anything here.
            if _found(t["key"]):
                with self._lock:
                    self.done.append(t["key"])
                log.info("%s is installed%s", t["label"],
                         "" if ok else " (winget reported an error first)")
                continue
            failed.append(t["label"])
            log.warning("could not install %s: %s", t["label"],
                        why or "winget succeeded but it is still not findable")
            self._set(error=why or f"{t['label']} still is not there after "
                                   f"installing. Restart AutoStream - some "
                                   f"installers only take effect for programs "
                                   f"started afterwards.")
        if failed:
            self._set(state="failed",
                      message=f"Could not install {', '.join(failed)}")
        else:
            self._set(state="done", tool="", error="",
                      message="Installed. Everything the clipper needs is here.")

    def _winget(self, tool: dict) -> tuple[bool, str]:
        args = [winget(), "install", "--id", tool["winget"], "-e",
                "--accept-package-agreements", "--accept-source-agreements",
                "--disable-interactivity"]
        try:
            p = subprocess.run(args, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=1800, creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired:
            return False, f"{tool['label']} took too long to install."
        except OSError as e:
            return False, f"Could not run winget: {e}"
        out = f"{p.stdout or ''}\n{p.stderr or ''}"
        if p.returncode == 0:
            return True, ""
        if "0x80070005" in out or p.returncode == 740:
            return False, ("Windows asked for permission and it was declined. "
                           f"{tool['label']} was not installed.")
        tail = "\n".join(x for x in out.strip().splitlines()[-4:] if x.strip())
        return False, (f"winget could not install {tool['label']} "
                       f"({p.returncode}).\n{tail}")[:600]


_installer: Installer | None = None


def installer() -> Installer:
    global _installer
    if _installer is None:
        _installer = Installer()
    return _installer
