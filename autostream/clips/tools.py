r"""Finding ffmpeg, and running it without the usual Windows papercuts.

WHY NOT JUST PATH
    winget installs ffmpeg under a versioned package directory and only adds it
    to PATH for *newly opened* shells. AutoStream usually starts from a shortcut
    or a scheduled task, neither of which has seen that change, so PATH alone
    finds nothing on a machine where ffmpeg is plainly installed. Every known
    install location is checked, results are cached, and a genuine absence
    fails with a sentence the user can act on rather than
    FileNotFoundError: [WinError 2].
"""
from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
from pathlib import Path

# Windows only: keeps a console window from flashing up on every ffmpeg call.
# The frozen build is windowed, so without this each clip would blink a black
# box over whatever the user is doing.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_WINGET = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"

_HINTS: list[Path] = [
    _WINGET / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe",
    _WINGET / "Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe",
    _WINGET / "BtbN.FFmpeg.GPL_Microsoft.Winget.Source_8wekyb3d8bbwe",
    Path(r"C:/ffmpeg/bin"),
    Path(r"C:/Program Files/ffmpeg/bin"),
    Path(os.environ.get("ProgramData", r"C:/ProgramData")) / "chocolatey/bin",
]

INSTALL_HINT = "winget install --id Gyan.FFmpeg"

# Set from config (clips.ffmpeg_path) before anything else runs.
_override: Path | None = None


def set_override(folder: str | None) -> None:
    """Point discovery at an explicit folder. Clears the cache."""
    global _override
    _override = Path(folder) if folder else None
    binary.cache_clear()


class FfmpegMissing(RuntimeError):
    pass


@functools.lru_cache(maxsize=8)
def binary(name: str) -> str:
    exe = f"{name}.exe" if os.name == "nt" else name
    if _override:
        direct = _override / exe
        if direct.is_file():
            return str(direct)
    found = shutil.which(name)
    if found:
        return found
    for root in _HINTS:
        if not root.exists():
            continue
        direct = root / exe
        if direct.is_file():
            return str(direct)
        for hit in root.rglob(exe):        # winget nests under a version folder
            return str(hit)
    raise FfmpegMissing(
        f"{name} was not found. Install it with:  {INSTALL_HINT}\n"
        f"Then either reopen AutoStream, or set the ffmpeg folder in "
        f"Settings > Clips.")


def available() -> bool:
    try:
        binary("ffmpeg")
        binary("ffprobe")
        return True
    except FfmpegMissing:
        return False


def missing_reason() -> str | None:
    try:
        binary("ffmpeg")
        binary("ffprobe")
    except FfmpegMissing as e:
        return str(e)
    return None


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    """Run and raise with the tail of stderr rather than a bare exit code."""
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=_NO_WINDOW, **kw)
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").strip().splitlines()[-6:])
        raise RuntimeError(f"{Path(args[0]).name} failed ({p.returncode}):\n{tail}")
    return p


def ffmpeg(*args: str) -> subprocess.CompletedProcess:
    # -nostdin matters: without it ffmpeg can swallow the parent's stdin and
    # wedge when called in a loop.
    return run([binary("ffmpeg"), "-hide_banner", "-loglevel", "error",
                "-nostdin", *args])


def ffmpeg_raw(args: list[str]) -> bytes:
    """Run ffmpeg and return stdout as bytes, for piped raw video."""
    p = subprocess.run([binary("ffmpeg"), "-hide_banner", "-loglevel", "error",
                        "-nostdin", *args],
                       capture_output=True, creationflags=_NO_WINDOW)
    return p.stdout


def probe(path: str | Path) -> dict:
    p = run([binary("ffprobe"), "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)])
    return json.loads(p.stdout)


def media_info(path: str | Path) -> dict:
    """-> {duration, width, height, fps, vcodec, acodec, audio_tracks, size}"""
    d = probe(path)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), {})
    num, _, den = (v.get("r_frame_rate") or "0/1").partition("/")
    fps = (float(num) / float(den)) if den and float(den) else 0.0
    return {
        "duration": float(d["format"].get("duration", 0.0)),
        "width": int(v.get("width", 0)),
        "height": int(v.get("height", 0)),
        "fps": round(fps, 3),
        "vcodec": v.get("codec_name"),
        "acodec": a.get("codec_name"),
        "audio_tracks": sum(1 for s in d["streams"] if s["codec_type"] == "audio"),
        "size": int(d["format"].get("size", 0)),
    }


@functools.lru_cache(maxsize=1)
def has_nvenc() -> bool:
    try:
        p = run([binary("ffmpeg"), "-hide_banner", "-encoders"])
    except Exception:  # noqa: BLE001
        return False
    return "h264_nvenc" in p.stdout


@functools.lru_cache(maxsize=1)
def has_cuda() -> bool:
    """Whether CUDA decode is usable. Worth checking separately from nvenc --
    the scan is decode-bound and the cut is encode-bound."""
    try:
        p = run([binary("ffmpeg"), "-hide_banner", "-hwaccels"])
    except Exception:  # noqa: BLE001
        return False
    return "cuda" in p.stdout


def video_codec_args(encoder: str = "auto", *, cq: int = 20) -> list[str]:
    """Encoder flags for a delivery-quality clip.

    NVENC is several times faster than libx264 here and the quality difference
    at CQ 20 is not visible on gameplay footage, so it leads when present.
    """
    if encoder == "auto":
        encoder = "nvenc" if has_nvenc() else "libx264"
    if encoder == "nvenc" and has_nvenc():
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq",
                "-rc", "vbr", "-cq", str(cq), "-b:v", "0",
                "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(cq),
            "-pix_fmt", "yuv420p"]


def hms(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def stamp(seconds: float) -> str:
    """Compact position for a filename: 1h02m15s, or 12m48s under the hour."""
    s = max(0, int(seconds))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}h{m:02d}m{sec:02d}s" if h else f"{m}m{sec:02d}s"


def duration_label(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"
