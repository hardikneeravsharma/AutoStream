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

import atexit
import logging
import shutil
from pathlib import Path

from collections.abc import Callable

from .plan import ClipPlan
from .tools import decode_args, ffmpeg, media_info, video_codec_args

log = logging.getLogger("autostream.clips.cutter")


def _cut(source: Path, start: float, duration: float, out: Path, *,
         encoder: str = "auto", cq: int = 20,
         keep_all_audio: bool = True) -> Path:
    """One continuous span of the recording, encoded to `out`."""
    audio: list[str] = []
    if keep_all_audio:
        # Explicit maps, because ffmpeg's default selection takes exactly ONE
        # audio stream and would quietly drop the isolated mic and game tracks.
        audio = ["-map", "0:v:0", "-map", "0:a"]

    ffmpeg(
        # Decode on the GPU where there is one. NVENC was already doing the
        # encoding, but every clip still decoded on the CPU: measured 5.33s
        # against 3.93s for one 15-second cut, and a run cuts dozens.
        *decode_args(),
        "-ss", f"{start:.3f}", "-i", str(source),
        "-t", f"{duration:.3f}",
        *audio,
        *video_codec_args(encoder, cq=cq),
        "-c:a", "aac", "-b:a", "192k",
        # +faststart puts the index at the front so the file plays before it
        # has fully downloaded, which matters the moment it is uploaded.
        "-movflags", "+faststart",
        "-y", str(out),
    )
    return out


def master(source: Path, clip: ClipPlan, outdir: Path, *,
           encoder: str = "auto", cq: int = 20,
           keep_all_audio: bool = True) -> Path:
    """16:9 clip at source framing. The editing copy."""
    outdir.mkdir(parents=True, exist_ok=True)
    return _cut(source, clip.start, clip.duration, outdir / f"{clip.name}.mp4",
                encoder=encoder, cq=cq, keep_all_audio=keep_all_audio)


# HOW MUCH OF THE WORK THE JOIN IS. Measured on a real 52-minute Valorant
# match: 21 encoded pieces took about 600 seconds and the stream-copy join
# took 170, so the join is roughly another quarter on top. Counted as one
# more piece it would leave a caller's progress bar at 95% for three minutes,
# which is the complaint this whole callback exists to answer.
JOIN_SHARE = 0.28


def master_segments(source: Path, spans: list[tuple[float, float]], name: str,
                    outdir: Path, *, encoder: str = "auto", cq: int = 20,
                    keep_all_audio: bool = True,
                    progress: Callable[[int, int], None] | None = None) -> Path:
    """One clip made of several spans of the recording, joined in order.

    `progress(done, total)` is called before each piece and again before the
    join. A 52-minute match is thirteen minutes of work, and without this the
    caller has nothing to report for the whole of it.

    This is what "cut the bit in the middle out" needs: the dead thirty
    seconds between two fights comes out and the two halves become one clip.

    HOW THE JOIN IS DONE, AND WHY NOT THE OTHER WAY
        Each span is encoded separately and the pieces are then stream-copied
        together with the concat demuxer. Every piece therefore begins on a
        keyframe of its own and carries identical codec parameters, which is
        the condition the demuxer needs -- and the join itself copies rather
        than re-encodes, so removing a middle costs no more quality than a
        plain cut does.

        The alternative, the concat FILTER, decodes everything and re-encodes
        once. That sounds tidier but it would have to rebuild all three audio
        tracks through a filter graph, and a master that quietly lost its
        isolated mic track would defeat the reason masters exist.

    A single span is not a join at all, so it takes the ordinary path and
    never pays for the extra copy.
    """
    keep = [(float(a), float(b)) for a, b in spans if float(b) - float(a) > 0.04]
    if not keep:
        raise ValueError("a clip needs at least one span")
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{name}.mp4"
    if len(keep) == 1:
        a, b = keep[0]
        return _cut(source, a, b - a, out, encoder=encoder, cq=cq,
                    keep_all_audio=keep_all_audio)

    work = outdir / f".{name}.parts"
    work.mkdir(parents=True, exist_ok=True)
    units = len(keep) + max(1, round(len(keep) * JOIN_SHARE))
    try:
        parts = []
        for i, (a, b) in enumerate(keep):
            if progress:
                progress(i, units)
            parts.append(_cut(source, a, b - a, work / f"{i:03d}.mp4",
                              encoder=encoder, cq=cq,
                              keep_all_audio=keep_all_audio))
        if progress:
            progress(len(keep), units)
        # Relative names in the list file: the concat demuxer resolves them
        # against the list's own directory, which sidesteps every question
        # about quoting a Windows path containing spaces or an apostrophe.
        listing = work / "parts.txt"
        listing.write_text("".join(f"file '{p.name}'\n"
                                   for p in parts),
                           encoding="utf-8")
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing),
               # The pieces each start their timestamps at zero, so the joined
               # file needs fresh ones or players see time run backwards.
               "-fflags", "+genpts",
               "-map", "0", "-c", "copy",
               "-movflags", "+faststart", "-y", str(out))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    log.info("joined %d spans into %s", len(keep), out.name)
    return out


def preview(source: Path, start: float, end: float, out: Path, *,
            width: int = 960) -> Path:
    """A small, seekable copy of one stretch of the recording.

    WHY THIS EXISTS AT ALL
        AutoStream's recordings are FRAGMENTED mp4 with no seek index: the
        moov at the front is two kilobytes and the timing lives in a moof
        before every chunk. A browser cannot seek in that. Pointing a <video>
        at a two-hour recording and asking it to jump an hour in would mean
        reading the whole file from the beginning, and the file is 47 GB.

        So adjusting where a clip starts plays THIS instead: the twenty
        seconds either side of the clip, re-encoded small, with the index at
        the front. It seeks instantly and costs a couple of seconds to make.

        Deliberately not the master and not a vertical -- it is a scrubbing
        aid that gets deleted, so it is 960 wide, one audio track, and encoded
        for speed rather than for looking at.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        *decode_args(),
        "-ss", f"{start:.3f}", "-i", str(source),
        "-t", f"{max(0.1, end - start):.3f}",
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"scale={width}:-2:flags=fast_bilinear",
        # Always libx264 here. NVENC's minimum quality is higher than this
        # needs and the preview is watched once and thrown away; what matters
        # is that it appears quickly and seeks exactly.
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-g", "30",                      # a keyframe every half second, so
        "-keyint_min", "15",             # scrubbing lands where it is asked
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-y", str(out),
    )
    return out


# The playable copy: what the part player shows when it cannot decode the
# recording itself. 720p at 30 fps is enough to find a moment by eye, and it is
# what makes the copy affordable -- measured on a 2560x1440 60 fps AV1 stream
# on an M2: 5.7x real time and 28 MB a minute, against 2x and 113 MB at full
# size. Detection and cutting never read it; they read the original.
PLAYABLE_HEIGHT = 720
PLAYABLE_FPS = 30
PLAYABLE_SUFFIX = ".playable.mp4"


# The copies' ffmpeg processes, killed when the app exits. A copy writes its
# video to a FILE, so unlike a scan's piped decoder nothing breaks when the app
# goes: it was found still running, orphaned, an hour after its app had quit.
_COPYING: set = set()


def _stop_copies() -> None:
    for proc in list(_COPYING):
        try:
            proc.kill()
        except OSError:
            pass


atexit.register(_stop_copies)


def playable_path(source: Path) -> Path:
    """Where `source`'s playable copy goes: beside it, or -- when that folder
    cannot be written -- in the app's own video folder."""
    import hashlib
    import os

    from .. import paths

    if os.access(source.parent, os.W_OK):
        return source.with_name(source.stem + PLAYABLE_SUFFIX)
    tag = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:8]
    return paths.VIDEO_HOME / "playable" / f"{source.stem[:60]}.{tag}{PLAYABLE_SUFFIX}"


def playable_ready(source: Path) -> Path | None:
    """The finished copy of `source`, or None. A copy older than its source is
    a copy of something else."""
    out = playable_path(source)
    try:
        if out.is_file() and out.stat().st_mtime >= source.stat().st_mtime:
            return out
    except OSError:
        pass
    return None


def playable_copy(source: Path, out: Path, *,
                  on_progress: Callable[[float], None] | None = None,
                  cancelled: Callable[[], bool] | None = None) -> Path:
    """Re-encode `source` into something every player can show. -> out.

    Written to a .part name and renamed when complete, so a copy that exists
    is a copy that finished: a quit half way leaves nothing that looks done.
    `on_progress` is told the fraction done, from ffmpeg's own -progress.
    Raises RuntimeError on failure, with the tail of what ffmpeg said.
    """
    import subprocess

    from .tools import _NO_WINDOW, binary, software_fallback

    total = float(media_info(source).get("duration") or 0.0)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    args = ["-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", f"scale=-2:{PLAYABLE_HEIGHT},fps={PLAYABLE_FPS}",
            *video_codec_args("auto", cq=26),
            "-c:a", "aac", "-b:a", "128k", "-f", "mp4", "-y", str(part)]

    def attempt(argv: list[str]) -> tuple[int, str]:
        proc = subprocess.Popen(
            [binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
             "-progress", "pipe:1", "-nostats", *argv],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=_NO_WINDOW)
        _COPYING.add(proc)
        try:
            return _follow(proc)
        finally:
            _COPYING.discard(proc)

    def _follow(proc) -> tuple[int, str]:
        for line in proc.stdout:            # a line about every half second
            if cancelled and cancelled():
                proc.kill()
                break
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and value.isdigit() and total and on_progress:
                on_progress(min(1.0, int(value) / 1e6 / total))
        err = proc.stderr.read()
        return proc.wait(), err

    try:
        code, err = attempt(args)
        if code and not (cancelled and cancelled()):
            soft = software_fallback(args)          # a hardware encoder that gave up
            if soft is not None:
                code, err = attempt(soft)
        if cancelled and cancelled():
            raise RuntimeError("cancelled")
        if code:
            tail = "\n".join(err.strip().splitlines()[-4:])
            raise RuntimeError(f"ffmpeg failed ({code}): {tail}")
        part.replace(out)
    finally:
        part.unlink(missing_ok=True)
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


def save_part(source: Path, start: float, end: float, out: Path) -> Path:
    """Write one stretch of a recording to a file the user keeps.

    STREAM COPY, NOT A RE-ENCODE. Trimming an hour off a 20 GB recording by
    re-encoding is tens of minutes and loses a generation of quality for no
    reason: the frames wanted are already there and already encoded. Copying
    them is disk-speed and lossless.

    The cost is that a copy can only cut on a keyframe, so the start lands on
    the keyframe at or before the chosen moment -- up to a couple of seconds
    early on an OBS recording. Early is the right direction to be wrong in for
    this: the part asked for is always wholly inside what comes out, and a
    scan reading those extra seconds finds nothing it would not have found.
    `-avoid_negative_ts make_zero` keeps the timestamps starting at zero, so
    the result seeks normally rather than carrying the source's offsets.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        # -ss BEFORE -i, which seeks by index instead of decoding to the point.
        # After it, trimming two hours in reads two hours of video first.
        "-ss", f"{max(0.0, start):.3f}",
        "-i", str(source),
        "-t", f"{max(0.1, end - start):.3f}",
        "-map", "0:v:0", "-map", "0:a?",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        # The index at the front, so the saved file can be scrubbed in a
        # player -- the recordings this is cut from cannot be.
        "-movflags", "+faststart",
        "-y", str(out),
    )
    return out
