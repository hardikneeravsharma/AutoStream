r"""Finding the loud moments in a recording, whatever game made it.

WHY THIS EXISTS
    Every other detector in this package reads something drawn on the screen:
    Delta Force's skull, Valorant's feed bars, CS2's round tally, Marvel
    Rivals' KO notice. Each one is a few days of calibration against real
    footage and is worth nothing for the next game. Four titles are supported
    and there are thousands.

    Audio is the one signal every shooter has in common and nothing has to be
    taught. A kill, an explosion, a round win and a teammate shouting are all
    the same shape: a sharp rise above whatever that game normally sounds
    like. It will never be as exact as reading the kill feed -- it cannot tell
    a kill from a death, or your grenade from theirs -- and that is the trade
    this is for. A rough shortlist in a game nobody has calibrated beats
    nothing at all, which is what was on offer before.

WHY A ROLLING BASELINE AND NOT A FIXED THRESHOLD
    Games are mixed differently, people set their own volumes, and a recording
    may have the desktop at -6 dB and the game at -20. A fixed "louder than
    X dBFS" finds everything in one recording and nothing in the next.

    What is constant is the SHAPE: a highlight is loud relative to the minute
    around it. So the test is against a rolling baseline taken from a window
    either side, which also means a long firefight raises its own floor --
    exactly right, because the whole of it is not one highlight.

WHY THE MEDIAN AND NOT THE MEAN
    The baseline is there to describe the quiet background, and the mean of a
    window containing a four-second explosion is dragged up by the explosion.
    The median is not: it still answers "what does this normally sound like"
    with the loud part included, which is the whole job.

WHY RMS AND NOT PEAK
    One sample of clipping is not a highlight. RMS over a window is energy
    over time, which is what a burst of gunfire is and what a single codec
    artefact is not.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import numpy as np

from .tools import FfmpegMissing, binary

log = logging.getLogger("autostream.clips.loudness")

# The envelope's resolution. 20 Hz is a reading every 50 ms, which is finer
# than any editing decision made from it and still only 72,000 floats for an
# hour of footage.
HZ = 20.0

# Mono, 8 kHz. Everything below is energy over tens of milliseconds, and no
# part of it looks at frequency -- so a higher rate is bytes off the disk for
# an answer that does not change.
RATE = 8000

# How far either side the baseline is taken from. Long enough that a firefight
# cannot be its own background, short enough to follow a recording that moves
# between a menu, a lobby and a match.
BASELINE_WINDOW = 45.0

# How far above the baseline counts. Measured in dB because loudness is
# multiplicative: +9 dB is "about three times the amplitude of its
# surroundings", which means the same thing in a quiet game and a loud one.
RISE_DB = 9.0

# Nothing below this is a highlight however far above its neighbours it is.
# A room-tone recording has a baseline near silence, and +9 dB above silence
# is still silence.
FLOOR_DB = -45.0

# Two peaks closer than this are one moment. A firefight is not twelve
# highlights.
MERGE_GAP = 6.0

# How long after the peak the moment is still going. Used as the marker's
# `end`, which is what a clip is cut against.
TAIL = 2.0


def envelope(video: str | Path, start: float = 0.0,
             duration: float | None = None, hz: float = HZ) -> np.ndarray:
    """-> RMS level in dBFS, one value every 1/hz seconds.

    Decoded straight to raw mono PCM and reduced as it arrives. An hour of
    8 kHz mono is 57 MB, which is read in chunks rather than held: the result
    is 72,000 floats.
    """
    args = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start > 0:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(video)]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    # -vn because this is the audio alone, and decoding the video to throw it
    # away is most of the cost of the whole scan.
    args += ["-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"]

    step = max(1, int(RATE / hz))
    out: list[float] = []
    carry = np.empty(0, dtype=np.int16)
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=no_window)
    try:
        while True:
            # A multiple of the sample size: a chunk that splits a sample in
            # half would shift every value after it by one byte.
            raw = p.stdout.read(step * 2 * 64)
            if not raw:
                break
            block = np.frombuffer(raw, dtype=np.int16)
            if carry.size:
                block = np.concatenate([carry, block])
            whole = (block.size // step) * step
            carry = block[whole:].copy()
            if not whole:
                continue
            frames = block[:whole].astype(np.float32).reshape(-1, step)
            rms = np.sqrt(np.mean(np.square(frames / 32768.0), axis=1))
            out.extend(rms.tolist())
    finally:
        try:
            p.stdout.close()
        except Exception:                                    # noqa: BLE001
            pass
        p.wait(timeout=30)

    if not out:
        # A recording with no audio track at all is a real thing -- OBS can be
        # configured that way -- and it is a reason to say so, not to crash.
        return np.empty(0, dtype=np.float32)
    arr = np.asarray(out, dtype=np.float32)
    # -120 dB for true silence rather than -inf, which poisons every later
    # mean, median and comparison it touches.
    return 20.0 * np.log10(np.maximum(arr, 1e-6))


def _baseline(level: np.ndarray, hz: float, window: float) -> np.ndarray:
    """A rolling median: what the recording normally sounds like, here.

    Taken on a COARSE grid and interpolated back. An exact rolling median over
    72,000 points is a sort per point; on a grid one second apart it is 3,600
    sorts and the answer differs by less than the threshold it is compared
    against.
    """
    n = level.size
    half = max(1, int(window * hz / 2))
    stride = max(1, int(hz))                       # one anchor per second
    idx = np.arange(0, n, stride)
    vals = np.empty(idx.size, dtype=np.float32)
    for i, c in enumerate(idx):
        lo = max(0, c - half)
        hi = min(n, c + half)
        vals[i] = float(np.median(level[lo:hi]))
    if idx.size == 1:
        return np.full(n, vals[0], dtype=np.float32)
    return np.interp(np.arange(n), idx, vals).astype(np.float32)


def peaks(level: np.ndarray, hz: float = HZ, *, rise_db: float = RISE_DB,
          floor_db: float = FLOOR_DB, merge_gap: float = MERGE_GAP,
          window: float = BASELINE_WINDOW,
          limit: int = 0) -> list[tuple[float, float, float]]:
    """-> [(time, score, end)] for each loud moment, in time order.

    `score` is how many dB above the local baseline the moment reached, which
    is the only ranking available here and is a real one: a shortlist of the
    five loudest minutes of a recording is a useful thing to be handed.
    """
    if level.size < 2:
        return []
    base = _baseline(level, hz, window)
    above = (level > base + rise_db) & (level > floor_db)
    if not above.any():
        return []

    # Contiguous runs of "above", each collapsed to its loudest point.
    edges = np.diff(above.astype(np.int8))
    starts = list(np.flatnonzero(edges == 1) + 1)
    ends = list(np.flatnonzero(edges == -1) + 1)
    if above[0]:
        starts.insert(0, 0)
    if above[-1]:
        ends.append(level.size)

    found: list[tuple[float, float, float]] = []
    for a, b in zip(starts, ends):
        seg = level[a:b] - base[a:b]
        top = int(np.argmax(seg))
        found.append(((a + top) / hz, float(seg[top]), b / hz))
    if not found:
        return []

    # MERGED BY TIME, KEEPING THE LOUDEST. A firefight is one moment, not
    # twelve, and the one to keep is the loudest rather than the first --
    # the first is usually the opening shot and the clip wants the kill.
    merged: list[list[float]] = [list(found[0])]
    for t, score, end in found[1:]:
        last = merged[-1]
        if t - last[0] <= merge_gap:
            last[2] = max(last[2], end)
            if score > last[1]:
                last[0], last[1] = t, score
        else:
            merged.append([t, score, end])

    out = [(t, s, max(e, t + TAIL)) for t, s, e in merged]
    if limit and len(out) > limit:
        # The loudest `limit`, then put back in time order -- a shortlist is
        # ranked for choosing and watched in order.
        out = sorted(sorted(out, key=lambda r: -r[1])[:limit], key=lambda r: r[0])
    return out


def find(video: str | Path, *, start: float = 0.0,
         duration: float | None = None, rise_db: float = RISE_DB,
         merge_gap: float = MERGE_GAP,
         limit: int = 0) -> list[tuple[float, float, float]]:
    """The whole thing: -> [(time in the file, score, end)].

    Times are offsets into the FILE, not into the window, so a caller that
    scanned part of a recording does not have to add `start` back on -- which
    is the kind of arithmetic that goes wrong once and is never noticed.
    """
    try:
        level = envelope(video, start, duration)
    except FfmpegMissing:
        raise
    except Exception as e:                                   # noqa: BLE001
        log.warning("could not read the audio of %s: %s", Path(video).name, e)
        return []
    if level.size < 2:
        log.info("%s has no audio to read", Path(video).name)
        return []
    got = peaks(level, HZ, rise_db=rise_db, merge_gap=merge_gap, limit=limit)
    log.info("%s: %d loud moment(s) from %.0fs of audio",
             Path(video).name, len(got), level.size / HZ)
    return [(t + start, s, e + start) for t, s, e in got]
