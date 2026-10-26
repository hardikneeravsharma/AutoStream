"""Choosing a file on a Mac.

WHY NOT THE TK PICKER webui.clips_pick USES ON WINDOWS
    Cocoa only lets the MAIN thread create a window, and on a Mac the main
    thread belongs to pywebview's run loop. clips_pick runs on an HTTP request
    thread, so tk.Tk() there is not a degraded picker -- it is an
    NSInternalInconsistencyException that takes the whole app down.

    So: pywebview's own dialog when the native window is up (it marshals onto
    the main thread itself and opens as a sheet on the window), and
    AppleScript's `choose file` otherwise -- osascript is its own process, so
    it has its own main thread, and it needs no window of ours at all. That
    second path is what a browser fallback gets.

WHAT HAPPENS AFTER THE DIALOG
    answer() is clips_pick's tail -- registering every path so the page may
    stream it back, and probing a video -- written out again rather than
    shared. Sharing it meant moving Windows code into a helper, and #193's
    rule is that the Windows path is not edited. If clips_pick's tail changes,
    change this with it; test_macos_dialogs pins the two to the same answer.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger("autostream.macos.dialogs")

# kind -> (title, extensions). Mirrors the filters clips_pick gives Tk.
VIDEO = ("mp4", "mkv", "mov", "flv", "avi", "ts", "webm")
AUDIO = ("mp3", "flac", "m4a", "wav", "aac", "ogg", "opus")
OUTRO = ("mp4", "mov", "mkv", "webm")


def _filter(kind: str) -> tuple[str, str, tuple[str, ...]]:
    """-> (title, label, extensions) for one kind of pick."""
    if kind == "intro":
        from ..clips import intros

        return ("Choose a GIF or video for the intro", "Video or GIF",
                tuple(t.lstrip(".") for t in intros.TYPES))
    if kind == "outro":
        return "Choose your channel's outro video", "Video", OUTRO
    if kind == "audio":
        return "Choose a track for the reel", "Audio", AUDIO
    return "Choose a video to clip", "Video", VIDEO


def _webview(win, kind: str, multi: bool) -> list[str] | None:
    """The native window's own dialog. None when there is no window to use."""
    if win is None or getattr(win, "win", None) is None or getattr(win, "fell_back", False):
        return None
    try:
        import webview
    except ImportError:
        return None
    _title, label, exts = _filter(kind)
    kind_open = getattr(getattr(webview, "FileDialog", None), "OPEN", None)
    if kind_open is None:                      # pywebview < 5
        kind_open = getattr(webview, "OPEN_DIALOG", 10)
    types = (f"{label} ({';'.join('*.' + e for e in exts)})", "All files (*.*)")
    got = win.win.create_file_dialog(kind_open, allow_multiple=multi, file_types=types)
    return [str(p) for p in (got or ())]


def _osascript(kind: str, multi: bool) -> list[str]:
    """AppleScript's picker, for when there is no native window."""
    title, _label, exts = _filter(kind)
    types = ", ".join(f'"{e}"' for e in exts)
    many = " with multiple selections allowed" if multi else ""
    script = (f'set picked to choose file with prompt "{title}" '
              f'of type {{{types}}}{many}\n'
              'set out to ""\n'
              'if class of picked is list then\n'
              '  repeat with f in picked\n'
              '    set out to out & POSIX path of f & linefeed\n'
              '  end repeat\n'
              'else\n'
              '  set out to POSIX path of picked\n'
              'end if\n'
              'return out')
    p = subprocess.run(["osascript", "-e", script], capture_output=True,
                       text=True, timeout=3600)
    # -128 is "User canceled": an answer, not a failure.
    if p.returncode != 0:
        if "-128" in (p.stderr or ""):
            return []
        raise RuntimeError((p.stderr or "osascript failed").strip()[:160])
    return [ln for ln in (p.stdout or "").splitlines() if ln.strip()]


def pick(win, kind: str = "video", multi: bool = False) -> tuple[list[str], str]:
    """-> (chosen paths, error). Empty paths and no error means cancelled."""
    try:
        got = _webview(win, kind, multi)
        if got is None:
            got = _osascript(kind, multi)
        return got, ""
    except Exception as e:                              # noqa: BLE001
        log.warning("the file picker failed: %s", e)
        return [], f"Could not open the file picker: {str(e)[:160]}"


def answer(server, picked: list[str], kind: str) -> dict:
    """What clips_pick returns for `picked`. Mirrors its tail; see above."""
    if not picked:
        return {"ok": True, "path": "", "paths": []}   # cancelled
    gone = [p for p in picked if not Path(p).is_file()]
    picked = [p for p in picked if Path(p).is_file()]
    if not picked:
        return {"error": "That file is not there any more."}
    for one in picked:
        server._picked.add(str(Path(one)).lower())   # noqa: SLF001
    path = Path(picked[0])
    out = {"ok": True, "path": str(path), "name": path.name,
           "paths": [str(Path(one)) for one in picked],
           "bytes": path.stat().st_size,
           "size_mb": round(path.stat().st_size / (1024 * 1024))}
    if gone:
        out["missing"] = [Path(g).name for g in gone]
    if kind not in ("intro", "outro", "background"):
        out.update(server.clips_probe({"path": str(path)}))
    return out
