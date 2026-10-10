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
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)

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
    """Run and raise with the tail of stderr rather than a bare exit code.

    THE ONE PLACE EVERY EXTERNAL PROCESS GOES THROUGH, which is why the
    diagnostic recorder is told about it here rather than at forty call sites.
    What it keeps is the exit code, the duration and the tail of stderr --
    the three things that are otherwise thrown away on the way to the
    six-line RuntimeError below. See clips/diag.py; when no diagnostic is
    running `note_process` returns immediately.
    """
    from . import diag

    began = time.monotonic()
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=_NO_WINDOW, **kw)
    diag.note_process(args, p.returncode, p.stderr or "",
                      time.monotonic() - began)
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").strip().splitlines()[-6:])
        raise RuntimeError(f"{Path(args[0]).name} failed ({p.returncode}):\n{tail}")
    return p


def ffmpeg(*args: str) -> subprocess.CompletedProcess:
    # -nostdin matters: without it ffmpeg can swallow the parent's stdin and
    # wedge when called in a loop.
    head = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin"]
    try:
        return run([*head, *args])
    except RuntimeError as e:
        soft = software_fallback(list(args))
        if soft is None:
            raise
        log.warning("hardware encode failed, using the CPU for the rest of this run: %s",
                    str(e).splitlines()[-1] if str(e) else e)
        return run([*head, *soft])


def ffmpeg_raw(args: list[str]) -> bytes:
    """Run ffmpeg and return stdout as bytes, for piped raw video.

    THE QUIET FAILURE. This one does not raise: a non-zero exit comes back as
    empty stdout, which every caller reads as "no frames" rather than "ffmpeg
    refused". That is exactly how an AMD machine reported finding no kills,
    so the recorder is told the exit code and how many bytes came out, which
    together distinguish the two.
    """
    from . import diag

    full = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error",
            "-nostdin", *args]
    began = time.monotonic()
    p = subprocess.run(full, capture_output=True, creationflags=_NO_WINDOW)
    diag.note_process(full, p.returncode,
                      (p.stderr or b"").decode("utf-8", "replace"),
                      time.monotonic() - began, stdout_bytes=len(p.stdout or b""))
    return p.stdout


def probe(path: str | Path) -> dict:
    # -v error, NOT -v quiet. `quiet` silences the reason as well as the
    # noise, so a file ffprobe refuses produced exactly "ffprobe failed (1):"
    # and then nothing -- in the log, in the toast and in a diagnostic report
    # whose whole purpose is to say WHY. `error` still prints no banner and
    # no stream listing; it prints the one line that says what is wrong with
    # the file, which is the entire question being asked here. stdout is the
    # JSON either way, so nothing that reads this changes.
    p = run([binary("ffprobe"), "-v", "error", "-print_format", "json",
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
    from . import diag

    full = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
            *args]
    began = time.monotonic()
    try:
        p = subprocess.run(full, capture_output=True,
                           timeout=_GPU_PROBE_TIMEOUT, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError, FfmpegMissing) as e:
        diag.note_process(full, -1, f"{e.__class__.__name__}: {e}",
                          time.monotonic() - began)
        return False
    # WHY THE PROBE ITSELF IS RECORDED. "nvenc=False" in a report is a
    # conclusion; the stderr of the run that reached it is the evidence, and
    # the difference between "no card" and "driver too old" lives there.
    diag.note_process(full, p.returncode,
                      (p.stderr or b"").decode("utf-8", "replace"),
                      time.monotonic() - began)
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


# ------------------------------------------------- AMD and Intel cards too
#
# EVERY GPU PATH HERE USED TO BE NVIDIA'S. Decode was `-hwaccel cuda` or
# nothing, encode was NVENC or libx264 -- so a Radeon user's clip job ran
# entirely on the CPU. Measured on a friend's RX 9070 XT run (v1.42, 50 min of
# 1440p): 20 minutes, of which 9 1/4 were libx264 encodes and 10 1/2 were CPU
# decodes for the scans, every core pinned throughout. Their ffmpeg (the same
# Gyan build this machine has) ships h264_amf and d3d11va; nothing asked for
# them.
#
# D3D11VA IS THE DECODER FOR EVERY CARD ON WINDOWS -- AMD, Intel and NVIDIA
# alike -- so it is the fallback under CUDA rather than an AMD special case.
# Each is probed the same way NVENC and CUDA are: listed AND used once.


@functools.lru_cache(maxsize=1)
def _encoders() -> str:
    try:
        return run([binary("ffmpeg"), "-hide_banner", "-encoders"]).stdout or ""
    except Exception:  # noqa: BLE001
        return ""


@functools.lru_cache(maxsize=1)
def has_amf() -> bool:
    """AMD's hardware encoder: listed by every Gyan/BtbN build, usable only on a Radeon."""
    if "h264_amf" not in _encoders():
        return False
    # With the flags a real clip uses, so a driver that refuses one of them
    # is found here and not forty clips into a job.
    if not _gpu_probe(["-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                       "-frames:v", "1", *_amf_args(20), "-f", "null", "-"]):
        return False
    # AND BEHIND THE DECODER A CUT WILL USE. Given a D3D11VA decode, h264_amf
    # builds its device from the decoder's -- and fails outright when that is
    # another vendor's card. Measured on a machine with an NVIDIA card driving
    # the display and a Radeon iGPU: AMF alone encodes, the pair exits with
    # "Failed to create derived AMF device". There, AMF is not used at all.
    if hw_decoder() == "d3d11va":
        sample = _tiny_h264()
        return bool(sample) and _gpu_probe(["-hwaccel", "d3d11va", "-i", sample, "-frames:v", "1",
                                            *_amf_args(20), "-f", "null", "-"])
    return True


@functools.lru_cache(maxsize=1)
def _tiny_h264() -> str:
    """A tenth of a second of H.264 to put through a hardware decoder. "" if none can be made."""
    import tempfile
    p = Path(tempfile.gettempdir()) / "autostream-probe-h264.mp4"
    if p.is_file() and p.stat().st_size > 0:
        return str(p)
    ok = _gpu_probe(["-y", "-f", "lavfi", "-i", "testsrc=s=256x256:d=0.2", "-c:v", "libx264",
                     "-pix_fmt", "yuv420p", str(p)])
    return str(p) if ok and p.is_file() else ""


@functools.lru_cache(maxsize=1)
def has_qsv() -> bool:
    """Intel's hardware encoder (Quick Sync), for an Intel GPU or iGPU."""
    if "h264_qsv" not in _encoders():
        return False
    return _gpu_probe(["-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                       "-frames:v", "1", *_qsv_args(20), "-f", "null", "-"])


@functools.lru_cache(maxsize=1)
def has_d3d11va() -> bool:
    """Whether the Windows video decoder (any vendor's card) can be opened."""
    try:
        p = run([binary("ffmpeg"), "-hide_banner", "-hwaccels"])
    except Exception:  # noqa: BLE001
        return False
    if "d3d11va" not in p.stdout:
        return False
    return _gpu_probe(["-init_hw_device", "d3d11va=gpu", "-f", "lavfi",
                       "-i", "nullsrc=s=64x64:d=0.1", "-frames:v", "1",
                       "-f", "null", "-"])


def hw_decoder() -> str:
    """The hardware decoder a scan or cut should use: "cuda", "d3d11va" or ""."""
    if has_cuda():
        return "cuda"
    if has_d3d11va():
        return "d3d11va"
    return ""


def decode_args() -> list[str]:
    """Input flags that decode on the card and hand frames back to system memory.

    No output format is asked for, so the frames arrive where the CPU crop,
    scale and fps filters expect them. A recording the card cannot decode (a
    10-bit or unusual profile) is decoded in software by ffmpeg itself.
    """
    hw = hw_decoder()
    return ["-hwaccel", hw] if hw else []


def gpu_frames_args() -> list[str]:
    """Input flags that keep decoded frames ON the card, for a chain that drops
    the ones it does not want and then `hwdownload`s the rest. [] without one."""
    hw = hw_decoder()
    if hw == "cuda":
        return ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    if hw == "d3d11va":
        return ["-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11"]
    return []


# A hardware encoder that passed its probe and then failed a real encode (a
# driver that runs out of sessions, a resolution it will not take) is not
# asked again this run: every later clip goes to the CPU instead of failing.
_HW_ENCODE_FAILED = False
# Each hardware encoder block handed out, and the libx264 block at the same
# quality that replaces it if the encode fails. See software_fallback().
_SOFT: dict[tuple[str, ...], list[str]] = {}


def software_fallback(argv: list[str]) -> list[str] | None:
    """`argv` with its hardware encoder swapped for libx264, or None if it has none.

    THE AMD PATH COULD NOT BE TESTED ON THE MACHINE IT WAS WRITTEN ON, so a
    failure must cost a clip its speed, not the clip. The probe proves AMF
    runs at all; this covers what a one-frame probe cannot.
    """
    global _HW_ENCODE_FAILED
    for hw, soft in _SOFT.items():
        n = len(hw)
        for i in range(len(argv) - n + 1):
            if tuple(argv[i:i + n]) == hw:
                _HW_ENCODE_FAILED = True
                return [*argv[:i], *soft, *argv[i + n:]]
    return None


def gpu_encoder() -> str:
    """The hardware encoder "auto" uses: "nvenc", "amf", "qsv" or "" for the CPU."""
    if _HW_ENCODE_FAILED:
        return ""
    if has_nvenc():
        return "nvenc"
    if has_amf():
        return "amf"
    if has_qsv():
        return "qsv"
    return ""


def video_codec_args(encoder: str = "auto", *, cq: int = 20) -> list[str]:
    """Encoder flags for a delivery-quality clip.

    A hardware encoder is several times faster than libx264 here and the
    quality difference at CQ 20 is not visible on gameplay footage, so the
    card's own leads when there is one. A named encoder the machine cannot run
    falls back to libx264 rather than failing the job.
    """
    soft = ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(cq), "-pix_fmt", "yuv420p"]
    if encoder == "auto":
        encoder = gpu_encoder() or "libx264"
    if _HW_ENCODE_FAILED:
        return soft
    hw: list[str] = []
    if encoder == "nvenc" and has_nvenc():
        hw = ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq",
              "-rc", "vbr", "-cq", str(cq), "-b:v", "0", "-pix_fmt", "yuv420p"]
    elif encoder == "amf" and has_amf():
        hw = _amf_args(cq)
    elif encoder == "qsv" and has_qsv():
        hw = _qsv_args(cq)
    if not hw:
        return soft
    _SOFT[tuple(hw)] = soft
    return hw


def _amf_args(cq: int) -> list[str]:
    # Constant QP is AMF's nearest to NVENC's -cq: the same number means about
    # the same picture. B-frames one step coarser, as x264 does.
    return ["-c:v", "h264_amf", "-usage", "transcoding", "-quality", "quality",
            "-rc", "cqp", "-qp_i", str(cq), "-qp_p", str(cq), "-qp_b", str(cq + 2),
            "-pix_fmt", "yuv420p"]


def _qsv_args(cq: int) -> list[str]:
    return ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", str(cq),
            "-pix_fmt", "nv12"]


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
