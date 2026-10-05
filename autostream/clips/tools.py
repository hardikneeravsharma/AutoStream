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


# BUILT WITH IS NOT RUNS ON. The usual Windows ffmpeg builds (Gyan, BtbN) list
# `cuda` among their hwaccels and `h264_nvenc` among their encoders on every
# machine, NVIDIA card or not -- they only load the driver when asked. On an
# AMD or Intel card, asking makes ffmpeg exit 255 before reading a frame, and
# every caller here discards stderr: a friend's Radeon got "0 samples" from
# the CS2 tally, an empty calibrator and a failed job, with nothing in the log
# naming the GPU. So each check below lists the capability AND then uses it
# once on a synthetic frame, and only a run that succeeds counts.
_GPU_PROBE_TIMEOUT = 20.0


def _gpu_probe(args: list[str]) -> bool:
    """Whether ffmpeg runs `args` on a tiny generated input. Never raises."""
    try:
        p = subprocess.run(
            [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
             *args],
            capture_output=True, timeout=_GPU_PROBE_TIMEOUT,
            creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError, FfmpegMissing):
        return False
    return p.returncode == 0


@functools.lru_cache(maxsize=1)
def has_nvenc() -> bool:
    try:
        p = run([binary("ffmpeg"), "-hide_banner", "-encoders"])
    except Exception:  # noqa: BLE001
        return False
    if "h264_nvenc" not in p.stdout:
        return False
    # 256x256: NVENC refuses frames below its minimum size, which would read
    # as "no card" on a machine that has one.
    return _gpu_probe(["-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                       "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null", "-"])


@functools.lru_cache(maxsize=1)
def filter_script_flag() -> str:
    """The flag this ffmpeg takes a filter graph in a FILE with.

    A long reel's graph does not fit on a Windows command line (32,767
    characters; a measured 50-shot reel needed 33,144), so it has to go in a
    file -- and the two ffmpeg generations spell that differently:

        <= 7.0   -filter_complex_script FILE
        >= 7.1   -/filter_complex FILE      (the generic "value from a file")

    ASKED, NOT PARSED. Version strings in the wild are `9.0-full_build`,
    `N-121254-g8a3bb4`, `4.4.2-0ubuntu0.22.04.1`; `-h full` simply stops
    listing the option once it is gone, which is the thing actually being
    asked about. Probed once per process, like the encoder checks above.
    """
    try:
        p = run([binary("ffmpeg"), "-hide_banner", "-h", "full"])
        text = (p.stdout or "") + (p.stderr or "")
    except Exception:                                        # noqa: BLE001
        return "-/filter_complex"
    return "-filter_complex_script" if "filter_complex_script" in text else "-/filter_complex"


@functools.lru_cache(maxsize=1)
def has_cuda() -> bool:
    """Whether CUDA decode is usable. Worth checking separately from nvenc --
    the scan is decode-bound and the cut is encode-bound."""
    try:
        p = run([binary("ffmpeg"), "-hide_banner", "-hwaccels"])
    except Exception:  # noqa: BLE001
        return False
    if "cuda" not in p.stdout:
        return False
    # Opening the device is the step that fails without a card; see above.
    return _gpu_probe(["-init_hw_device", "cuda=gpu", "-f", "lavfi",
                       "-i", "nullsrc=s=64x64:d=0.1", "-frames:v", "1",
                       "-f", "null", "-"])


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
