"""VideoToolbox: the Mac's hardware encoder and decoder.

Every Mac since 2011 has one, Apple Silicon or Intel, and ffmpeg reaches both
through `h264_videotoolbox` and `-hwaccel videotoolbox`. None of the Windows
paths in tools.py apply -- NVENC, AMF and Quick Sync are all absent from a Mac
ffmpeg, so without this every clip went to libx264 on the CPU.

PROBED THE SAME WAY THE WINDOWS ENCODERS ARE: listed, and then used once on a
generated frame, because "built with" is not "runs on". And a probed encoder
that fails a real encode is swapped for libx264 at the same quality by
tools.software_fallback(), so a VideoToolbox failure costs a clip its speed,
never the clip.

QUALITY, NOT BITRATE, WHERE THE MACHINE ALLOWS IT. Constant quality (-q:v) is
an Apple Silicon feature; an Intel Mac's VideoToolbox refuses it. So the
quality form is probed first and a generous bitrate form is the fallback --
both through the same probe, so whichever this Mac takes is the one that ran.
"""
from __future__ import annotations

import functools

NAME = "videotoolbox"


def _quality(cq: int) -> int:
    """libx264's CRF onto VideoToolbox's 1-100 quality, higher is better.

    Matched by eye on gameplay footage at the CRF 20 every clip uses: q 65
    looks like it, and the slope keeps a step of CRF a step of q.
    """
    return max(1, min(100, round(100 - cq * 1.75)))


def quality_args(cq: int) -> list[str]:
    return ["-c:v", "h264_videotoolbox", "-q:v", str(_quality(cq)),
            "-profile:v", "high", "-pix_fmt", "yuv420p"]


def bitrate_args(cq: int) -> list[str]:
    # Generous on purpose: an Intel Mac has no constant-quality mode, and a
    # bitrate that starves a 1440p fight is worse than a larger file.
    mbps = max(8, 36 - cq)
    return ["-c:v", "h264_videotoolbox", "-b:v", f"{mbps}M",
            "-maxrate", f"{mbps * 3 // 2}M", "-bufsize", f"{mbps * 2}M",
            "-profile:v", "high", "-pix_fmt", "yuv420p"]


def _probe(args: list[str]) -> bool:
    from ..clips.tools import _gpu_probe

    return _gpu_probe(["-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                       "-frames:v", "1", *args, "-f", "null", "-"])


@functools.lru_cache(maxsize=1)
def _mode() -> str:
    """"quality", "bitrate" or "" -- which form of the encoder this Mac runs."""
    from ..clips.tools import _encoders

    if "h264_videotoolbox" not in _encoders():
        return ""
    if _probe(quality_args(20)):
        return "quality"
    if _probe(bitrate_args(20)):
        return "bitrate"
    return ""


def available() -> bool:
    return bool(_mode())


def args(cq: int) -> list[str]:
    """Encoder flags for a delivery-quality clip, or [] when there is none."""
    mode = _mode()
    if mode == "quality":
        return quality_args(cq)
    if mode == "bitrate":
        return bitrate_args(cq)
    return []


@functools.lru_cache(maxsize=1)
def decoder() -> str:
    """"videotoolbox" when the hardware decoder opens, else "".

    Frames come back to system memory (no -hwaccel_output_format), which is
    what the scans' CPU crop and scale expect.
    """
    from ..clips.tools import _gpu_probe, _tiny_h264, binary, run

    try:
        listed = run([binary("ffmpeg"), "-hide_banner", "-hwaccels"]).stdout or ""
    except Exception:                                   # noqa: BLE001
        return ""
    if NAME not in listed:
        return ""
    sample = _tiny_h264()
    if not sample:
        return ""
    ok = _gpu_probe(["-hwaccel", NAME, "-i", sample, "-frames:v", "1",
                     "-f", "null", "-"])
    return NAME if ok else ""


def forget() -> None:
    """Drop the cached answers. For tests, and a changed ffmpeg."""
    _mode.cache_clear()
    decoder.cache_clear()
