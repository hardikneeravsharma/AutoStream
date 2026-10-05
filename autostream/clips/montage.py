"""Join clips into one montage with transitions.

THE ARITHMETIC THAT MATTERS
    Every xfade OVERLAPS its two inputs by the transition duration, so the
    timeline gets shorter with each join. The offset for join i is therefore
    cumulative, not `i * clip_length`:

        acc = d0
        for i in 1..n-1:
            offset_i = acc - D
            acc      = acc + d_i - D

    Writing `offset = i * d` instead is the classic way to get a montage where
    the first join looks right and everything after it drifts progressively
    further out of place.

    D must also be shorter than the shortest clip, or the offset goes negative
    and ffmpeg fails with a filtergraph error that says nothing about the real
    cause. It is clamped, not validated -- a short clip should shorten the
    transition, not refuse the montage.

WHY AUDIO NEEDS NO OFFSETS
    acrossfade overlaps its two inputs by exactly D as well, so chaining them
    in the same order produces the identical timeline with no arithmetic. The
    two chains stay locked together for free.

ON "SWIRL"
    ffmpeg's xfade has 58 transitions and none of them is a swirl. `radial`
    sweeps around the centre like a clock hand and is the closest thing to it,
    so that is what the label maps to. Naming it honestly in the menu and
    mapping it to the nearest real effect beats either silently substituting
    something unrelated or refusing the request.
"""
from __future__ import annotations

import logging
import random
from pathlib import Path

from .tools import ffmpeg, media_info, video_codec_args

log = logging.getLogger("autostream.clips.montage")

# label -> real xfade transition name.
TRANSITIONS: dict[str, str] = {
    "fade": "fade",
    "fadeblack": "fadeblack",
    "dissolve": "dissolve",
    "radial": "radial",          # shown as "Swirl"
    "zoomin": "zoomin",
    "slideleft": "slideleft",
    "pixelize": "pixelize",
    "wipeleft": "wipeleft",
}

# What "Mixed" draws from. Deliberately excludes pixelize and zoomin: used
# every few seconds they read as a glitch rather than as an edit.
MIXED_POOL = ["fade", "fadeblack", "dissolve", "radial", "slideleft", "wipeleft"]

# A transition may not eat more than this fraction of the shortest clip.
MAX_TRANSITION_FRACTION = 0.4


def _plan_offsets(durations: list[float], d: float) -> list[float]:
    """Cumulative xfade offsets. See the module docstring."""
    offsets: list[float] = []
    acc = durations[0]
    for i in range(1, len(durations)):
        offsets.append(acc - d)
        acc += durations[i] - d
    return offsets


def expected_duration(durations: list[float], d: float) -> float:
    return sum(durations) - d * (len(durations) - 1)


# YOUTUBE'S RULES FOR CHAPTERS, which are not advice: break one and it shows
# none of them at all, with no error anywhere.
#
#   the first must be at 0:00
#   there must be at least three
#   each must run for at least ten seconds
#
# All three are enforced here rather than hoped for, because the failure is
# silent: a description full of timestamps and a video with no chapter bar,
# which looks like YouTube being slow rather than like a rule being broken.
CHAPTER_MIN = 10.0
CHAPTER_LEAST = 3


def chapter_marks(durations: list[float], d: float,
                  labels: list[str]) -> list[tuple[float, str]]:
    """-> [(seconds into the montage, label)], or [] if there cannot be any.

    EXACT, NOT ESTIMATED. The offsets are the same arithmetic `_plan_offsets`
    gives ffmpeg to place the crossfades with, so a chapter lands on the frame
    the clip starts on rather than near it. A montage is otherwise the one
    output of this app with no way into the middle of it: forty clips joined
    into eight minutes, and the good one is somewhere in there.
    """
    if len(durations) < 2 or len(durations) != len(labels):
        return []
    # Clip 0 starts at 0; each one after it starts where the crossfade into it
    # does. Same recurrence as _plan_offsets, kept beside it on purpose.
    marks: list[tuple[float, str]] = [(0.0, labels[0])]
    acc = durations[0]
    for i in range(1, len(durations)):
        marks.append((max(0.0, acc - d), labels[i]))
        acc += durations[i] - d

    # TEN SECONDS APART, by dropping rather than by moving: a chapter moved to
    # satisfy the rule points at the wrong moment, which is worse than one
    # chapter fewer. The last is checked against the montage's end for the
    # same reason -- a final chapter three seconds from the end is one YouTube
    # will not show.
    total = expected_duration(durations, d)
    out: list[tuple[float, str]] = []
    for t, name in marks:
        if out and t - out[-1][0] < CHAPTER_MIN:
            continue
        if total - t < CHAPTER_MIN:
            continue
        out.append((t, name))
    return out if len(out) >= CHAPTER_LEAST else []


def clamp_transition(durations: list[float], seconds: float) -> float:
    if len(durations) < 2:
        return 0.0
    return max(0.05, min(seconds, MAX_TRANSITION_FRACTION * min(durations)))


def build(clips: list[Path], out: Path, *, transition: str = "fade",
          transition_ms: int = 500, encoder: str = "auto",
          cq: int = 20, seed: int | None = None) -> Path:
    """Concatenate clips into one file. -> the output path."""
    clips = [Path(c) for c in clips if Path(c).exists()]
    if not clips:
        raise ValueError("no clips to join")
    out.parent.mkdir(parents=True, exist_ok=True)

    if len(clips) == 1:
        ffmpeg("-i", str(clips[0]), "-map", "0:v:0", "-map", "0:a:0",
               "-c", "copy", "-y", str(out))
        return out

    durations = [media_info(c)["duration"] for c in clips]

    if transition == "cut" or transition_ms <= 0:
        return _hard_cut(clips, out, encoder=encoder, cq=cq)

    d = clamp_transition(durations, transition_ms / 1000.0)
    rng = random.Random(seed)
    if transition == "mixed":
        names = [rng.choice(MIXED_POOL) for _ in range(len(clips) - 1)]
    else:
        names = [TRANSITIONS.get(transition, "fade")] * (len(clips) - 1)

    offsets = _plan_offsets(durations, d)

    # Normalise before joining. xfade demands identical width, height, pixel
    # format, SAR and frame rate on both inputs, and clips cut from one
    # recording only *usually* satisfy that -- a single differently sized
    # source would otherwise fail the whole montage at the last step.
    info = media_info(clips[0])
    w, h = info["width"], info["height"]
    fps = int(round(info["fps"])) or 60

    parts: list[str] = []
    for i in range(len(clips)):
        parts.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},"
            f"format=yuv420p[v{i}]")
        parts.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{i}]")

    vprev, aprev = "v0", "a0"
    for i in range(1, len(clips)):
        vout, aout = f"vx{i}", f"ax{i}"
        parts.append(f"[{vprev}][v{i}]xfade=transition={names[i-1]}"
                     f":duration={d:.3f}:offset={offsets[i-1]:.3f}[{vout}]")
        parts.append(f"[{aprev}][a{i}]acrossfade=d={d:.3f}[{aout}]")
        vprev, aprev = vout, aout

    args: list[str] = []
    for c in clips:
        args += ["-i", str(c)]
    args += ["-filter_complex", ";".join(parts),
             "-map", f"[{vprev}]", "-map", f"[{aprev}]",
             *video_codec_args(encoder, cq=cq),
             "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", "-y", str(out)]

    log.info("montage: %d clips, %s, %.2fs transitions -> %.1fs",
             len(clips), transition, d, expected_duration(durations, d))
    ffmpeg(*args)
    return out


def _hard_cut(clips: list[Path], out: Path, *, encoder: str, cq: int) -> Path:
    """No transition. Still re-encoded through the concat FILTER rather than
    the concat demuxer, because the demuxer needs byte-identical encoding
    parameters and silently produces a broken timeline when they differ."""
    info = media_info(clips[0])
    w, h = info["width"], info["height"]
    fps = int(round(info["fps"])) or 60

    parts, labels = [], []
    for i in range(len(clips)):
        parts.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                     f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},"
                     f"format=yuv420p[v{i}]")
        parts.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    parts.append("".join(labels) + f"concat=n={len(clips)}:v=1:a=1[vo][ao]")

    args: list[str] = []
    for c in clips:
        args += ["-i", str(c)]
    args += ["-filter_complex", ";".join(parts), "-map", "[vo]", "-map", "[ao]",
             *video_codec_args(encoder, cq=cq),
             "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", "-y", str(out)]
    ffmpeg(*args)
    return out
