"""Cut clips out of a recording.

ON SEEKING
    -ss goes BEFORE -i so ffmpeg jumps via the index instead of decoding from
    zero. On a two-hour file that is the difference between a second and
    several minutes per clip.

ON WHY THIS RE-ENCODES INSTEAD OF STREAM-COPYING
    Because the cut then lands on an arbitrary frame rather than a keyframe.
    Stream-copy would silently shift the clip back to the previous keyframe,
    and on a stream encoded with two-second GOPs that is up to two seconds of
    missing run-up right where the action starts. Re-encoding costs seconds per
    clip on NVENC and gets the frame that was asked for.

ON AUDIO
    A recording made by AutoStream carries three tracks: 1 the mix, 2 the mic
    alone, 3 the game alone. Masters keep all of them, because the entire point
    of recording separate tracks is being able to rebalance the mic afterwards
    and the master is what goes into the editor. Verticals and montages keep
    only the mix -- they are finished exports, and no upload target does
    anything useful with extra tracks.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .plan import ClipPlan
from .tools import ffmpeg, has_cuda, media_info, video_codec_args

log = logging.getLogger("autostream.clips.cutter")


def master(source: Path, clip: ClipPlan, outdir: Path, *,
           encoder: str = "auto", cq: int = 20,
           keep_all_audio: bool = True) -> Path:
    """16:9 clip at source framing. The editing copy."""
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{clip.name}.mp4"

    audio: list[str] = []
    if keep_all_audio:
        # Explicit maps, because ffmpeg's default selection takes exactly ONE
        # audio stream and would quietly drop the isolated mic and game tracks.
        audio = ["-map", "0:v:0", "-map", "0:a"]

    ffmpeg(
        # Decode on the GPU where there is one. NVENC was already doing the
        # encoding, but every clip still decoded on the CPU: measured 5.33s
        # against 3.93s for one 15-second cut, and a run cuts dozens.
        *(["-hwaccel", "cuda"] if has_cuda() else []),
        "-ss", f"{clip.start:.3f}", "-i", str(source),
        "-t", f"{clip.duration:.3f}",
        *audio,
        *video_codec_args(encoder, cq=cq),
        "-c:a", "aac", "-b:a", "192k",
        # +faststart puts the index at the front so the file plays before it
        # has fully downloaded, which matters the moment it is uploaded.
        "-movflags", "+faststart",
        "-y", str(out),
    )
    return out


def vertical(master_path: Path, outdir: Path, *, mode: str = "crop",
             encoder: str = "auto", cq: int = 20) -> Path | None:
    """9:16 export, derived from the master rather than re-cut from the source
    so the expensive seek happens once per clip instead of twice.

    mode="crop": zoom to the centre. Keeps the crosshair and the action large
        and loses the killfeed and minimap at the edges. This is what gameplay
        Shorts do, and it is the right default for a shooter.
    mode="fit":  the whole 16:9 frame centred over a blurred copy of itself.
        Nothing is lost, but the gameplay occupies about a third of the height.
    """
    if mode in ("none", "", None):
        return None
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{master_path.stem}_vertical.mp4"

    if mode == "crop":
        vf = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=lanczos"
    elif mode == "fit":
        vf = ("split=2[bg][fg];"
              "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
              "crop=1080:1920,gblur=sigma=28[bgb];"
              "[fg]scale=1080:-2:flags=lanczos[fgs];"
              "[bgb][fgs]overlay=(W-w)/2:(H-h)/2")
    else:
        raise ValueError("vertical mode must be 'crop', 'fit' or 'none'")

    ffmpeg("-i", str(master_path),
           "-map", "0:v:0", "-map", "0:a:0",     # mix only; this is an export
           "-vf", vf,
           *video_codec_args(encoder, cq=cq),
           "-c:a", "aac", "-b:a", "160k",
           "-movflags", "+faststart", "-y", str(out))
    return out


def contact_sheet(source: Path, clip: ClipPlan, out_png: Path, n: int = 6) -> Path:
    """A strip of n frames across the clip, for judging it without opening it."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    step = max(0.1, clip.duration / n)
    ffmpeg("-ss", f"{clip.start:.3f}", "-i", str(source),
           "-t", f"{clip.duration:.3f}",
           "-vf", f"fps=1/{step:.3f},scale=320:-2,tile={n}x1",
           "-frames:v", "1", "-y", str(out_png))
    return out_png


def poster(source: Path, at: float, out_png: Path, width: int = 480) -> Path:
    """One frame, for a thumbnail."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-ss", f"{at:.3f}", "-i", str(source), "-frames:v", "1",
           "-vf", f"scale={width}:-2", "-y", str(out_png))
    return out_png


def probe_source(source: Path) -> dict:
    info = media_info(source)
    log.info("source %s: %dx%d @%.0f, %d audio track(s), %.0f min",
             Path(source).name, info["width"], info["height"], info["fps"],
             info["audio_tracks"], info["duration"] / 60)
    return info
