r"""The Edge WebView2 runtime: is it here, and offering to fetch it.

WHY THIS IS NOT INSTALLED SILENTLY AT SETUP
    It was the obvious idea and it is the wrong one, for three reasons.

    It cannot be silent anyway. A per-machine install needs elevation, so
    Windows raises a UAC prompt whatever the app does -- an unexplained one, if
    the app never mentioned it. Better to ask, and have the prompt make sense.

    AutoStream ships as a zip you unpack. Somebody who chose a portable app
    over an installer has said something about how they want software to
    behave on their machine, and quietly installing a system-wide Microsoft
    runtime the first time they open it is not that.

    And it is not needed. Without the runtime the UI opens in the real browser
    and every feature works; what is lost is a window in the taskbar. That is a
    preference, not a dependency, and preferences get offered rather than
    applied.

WHY NOT SHIP THE RUNTIME INSTEAD
    Microsoft distributes a "fixed version" build that needs no install at all.
    It is around 180 MB unpacked, against a 71 MB download -- so every user
    pays triple to spare the minority who lack it a two-megabyte fetch. The
    Evergreen bootstrapper below is that two megabytes, and it also keeps
    itself updated afterwards.

WHAT WINDOWS ALREADY HAS
    Windows 11 ships the runtime, and recent Windows 10 gets it with Edge. A
    machine without it is usually older Windows 10, or one where Edge has been
    stripped out.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

log = logging.getLogger("autostream.webview2")

# Microsoft's permanent link to the Evergreen Bootstrapper (about 2 MB). It
# downloads and installs the current runtime, then keeps it updated.
BOOTSTRAPPER = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"

# The runtime registers itself under EdgeUpdate with this fixed client id.
# Per-machine first, then per-user: both are real installs and either is
# enough for pywebview.
_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
_KEYS = (
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients" + "\\" + _GUID),
    ("HKLM", r"SOFTWARE\Microsoft\EdgeUpdate\Clients" + "\\" + _GUID),
    ("HKCU", r"SOFTWARE\Microsoft\EdgeUpdate\Clients" + "\\" + _GUID),
)


def version() -> str:
    """The installed runtime version, or "" if there is none.

    Read from the registry rather than by trying to open a window: the window
    can only be opened from the main thread, once, and a failed attempt is
    expensive and visible.
    """
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    hives = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    for hive, path in _KEYS:
        try:
            with winreg.OpenKey(hives[hive], path) as k:
                pv = str(winreg.QueryValueEx(k, "pv")[0] or "").strip()
                # An empty or 0.0.0.0 pv means the key is a leftover from an
                # uninstall, which is not a runtime.
                if pv and pv != "0.0.0.0":
                    return pv
        except OSError:
            continue
    return ""


def installed() -> bool:
    return bool(version())


def install(timeout: int = 600) -> dict:
    """Download Microsoft's bootstrapper and run it. -> {ok, version|error}.

    Runs the installer VISIBLY. It raises a UAC prompt of its own, and a
    prompt from a process the user cannot see is how software gets mistaken
    for something worse.
    """
    if sys.platform != "win32":
        return {"ok": False, "error": "The WebView2 runtime is Windows only."}
    if installed():
        return {"ok": True, "version": version(), "already": True}

    tmp = Path(tempfile.mkdtemp(prefix="as-wv2-")) / "MicrosoftEdgeWebview2Setup.exe"
    try:
        log.info("downloading the WebView2 bootstrapper")
        with urllib.request.urlopen(BOOTSTRAPPER, timeout=60) as r:
            data = r.read()
        # The bootstrapper is around 2 MB. Anything tiny is a redirect page or
        # a captive portal, and running it would be worse than not.
        if len(data) < 200_000:
            return {"ok": False,
                    "error": "That download does not look like the installer. "
                             "Check the internet connection and try again."}
        tmp.write_bytes(data)
    except Exception as e:  # noqa: BLE001
        return {"ok": False,
                "error": f"Could not download it: {str(e)[:160]}"}

    try:
        log.info("running the WebView2 installer")
        proc = subprocess.run([str(tmp), "/install"], timeout=timeout,
                              capture_output=True)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "The installer did not finish in time."}
    except OSError as e:
        # 740 is "requires elevation": the user declined the UAC prompt.
        if getattr(e, "winerror", None) == 740:
            return {"ok": False,
                    "error": "Windows asked for permission and it was declined. "
                             "The UI will keep opening in your browser."}
        return {"ok": False, "error": f"Could not run the installer: {e}"}
    finally:
        try:
            tmp.unlink()
            tmp.parent.rmdir()
        except OSError:
            pass

    got = version()
    if got:
        log.info("WebView2 runtime %s installed", got)
        return {"ok": True, "version": got}
    return {"ok": False,
            "error": f"The installer exited with code {proc.returncode} and no "
                     f"runtime was registered. The UI will keep opening in "
                     f"your browser."}
