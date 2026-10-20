"""A shot's speed changes, rendered so they look like a camera did them.

WHY THIS EXISTS. A shot's speed is `pieces` -- (start, end, rate) in output
seconds -- and until now it was rendered as exactly that: one setpts map whose
rate JUMPS at every boundary, slow motion as `minterpolate=blend` (cross-fading
two real frames, which ghosts), and speed-ups as a `tmix` over the whole clip
(which smears the real-speed parts too). Looked at side by side with the same
reels cut by hand, the verdict was "the velocity ramp has no smoothness, it
looks blended and fast-forwarded; the slow motion is not smooth". Three things
fixed it in the prototype that reel was compared against, and are done here:

* THE SPEED EASES. Every change of rate is a smoothstep across the boundary
  instead of a step. Symmetric about the boundary, so the source time it
  reaches by the end of the ease is exactly what the step reached: outside the
  eases the map is the pieces' own, and an ease is never laid over a kill, so
  every kill is on the frame it was planned on. derive(), preview_at() and the
  page's preview keep using the pieces and stay right.
* SLOW MOTION IS OPTICAL FLOW. Where the rate is below real speed, frames come
  from a motion-compensated copy of that span at 120 or 240 fps (minterpolate
  mci/aobmc/bidir), blended between its two nearest frames. Measured on a
  1080p Valorant clip: 0.6 s of source costs 15 s at 1080p/120 and 7 s at
  720p/120 -- paid only on the spans that are slowed, at the size the reel
  actually shows.
* SPEED-UPS GET A SHUTTER. Above 2x each output frame averages the source
  frames a 180-degree shutter would have seen, so fast reads as motion rather
  than as frames missing. At 2x and under it is the nearest frame.

The result is a plain 60 fps clip, one frame per output frame, that the shot's
ffmpeg graph takes in place of the setpts map; everything after the re-time --
freeze, effects, camera, layout -- is unchanged.
"""
from __future__ import annotations

import logging
import math
import subprocess
import time
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

FPS = 60
TAG = "flow1"              # in a segment's cache key whenever it is re-timed here
EASE = 0.22                # s: the longest half-width of a speed change's ease
EASE_SHARE = 0.45          # ...and never more than this share of either piece beside it
KILL_CLEAR = 1.5 / FPS     # an ease stops this far short of a kill
REAL = 0.97                # at or above this (and under 1/REAL) a rate is real speed
SHUTTER = 0.5              # 180 degrees
FINE = 1.0 / 1200          # the integration step
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def needed(pieces: list) -> bool:
    """Whether any of a shot's pieces plays at other than real speed."""
    return any(abs(float(r) - 1.0) > 1e-6 for _a, _b, r in pieces)


def smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def eases(pieces: list, kills: list[float] = ()) -> list[tuple[float, float, float, float]]:
    """(centre, half-width, rate before, rate after) for every change of rate."""
    out = []
    for (a0, b0, r0), (a1, b1, r1) in zip(pieces, pieces[1:]):
        if abs(float(r0) - float(r1)) < 1e-9:
            continue
        c = float(b0)
        h = min(EASE, EASE_SHARE * (b0 - a0), EASE_SHARE * (b1 - a1))
        for k in kills:
            h = min(h, abs(c - float(k)) - KILL_CLEAR)
        if h > 0.5 / FPS:
            out.append((c, h, float(r0), float(r1)))
    return out


def rate_curve(pieces: list, t: np.ndarray, kills: list[float] = ()) -> np.ndarray:
    """The eased playback rate at output times t."""
    r = np.ones_like(t, dtype=np.float64)
    for a, b, rate in pieces:
        r[(t >= a) & (t < b)] = float(rate)
    if len(pieces):
        r[t >= pieces[-1][1]] = float(pieces[-1][2])
        r[t < pieces[0][0]] = float(pieces[0][2])
    for c, h, r0, r1 in eases(pieces, kills):
        m = (t >= c - h) & (t < c + h)
        r[m] = r0 + (r1 - r0) * smoothstep((t[m] - (c - h)) / (2 * h))
    return r


def frame_map(pieces: list, frames: int, kills: list[float] = (), fps: int = FPS
              ) -> tuple[np.ndarray, np.ndarray]:
    """Source seconds (from the segment's first source second) and rate, per output frame.

    Output frame i is the picture at output time i/fps -- what setpts and the
    fps filter show there.
    """
    total = max(float(pieces[-1][1]) if len(pieces) else 0.0, frames / fps)
    grid = np.arange(0.0, total + 2 * FINE, FINE)
    rates = rate_curve(pieces, grid, kills)
    cum = np.concatenate([[0.0], np.cumsum((rates[:-1] + rates[1:]) / 2 * FINE)])
    ts = np.arange(frames) / fps
    return np.interp(ts, grid, cum), np.interp(ts, grid, rates)


def stepped(pieces: list, t: float) -> float:
    """Source seconds the plain pieces reach by output time t."""
    used = 0.0
    for a, b, r in pieces:
        if t <= a:
            break
        used += (min(b, t) - a) * r
    return used


# ------------------------------------------------------------------ frames

class Frames:
    """Frames of a video from `start` at `fps`, by index, decoded forward with a small cache."""

    def __init__(self, path: str, start: float, fps: int, length: float, size: tuple[int, int],
                 ff: str = "ffmpeg", scale: bool = True):
        self.path, self.start, self.fps, self.length = str(path), start, fps, length
        self.w, self.h = size
        self.ff, self.scale = ff, scale
        self.proc = None
        self.next = 0
        self.cache: dict[int, np.ndarray] = {}
        self.last: np.ndarray | None = None

    def _open(self, idx: int) -> None:
        self.close()
        t = self.start + idx / self.fps
        vf = f"scale={self.w}:{self.h}:flags=bicubic" if self.scale else "null"
        self.proc = subprocess.Popen(
            [self.ff, "-v", "error", "-nostdin", "-ss", f"{max(0.0, t):.4f}", "-i", self.path,
             "-t", f"{max(0.1, self.length - idx / self.fps + 0.5):.3f}", "-an", "-vf", vf,
             "-r", str(self.fps), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW,
            bufsize=self.w * self.h * 3 * 4)
        self.next = idx

    def frame(self, idx: int) -> np.ndarray:
        idx = max(0, int(idx))
        if idx in self.cache:
            return self.cache[idx]
        if self.proc is None or idx < self.next or idx > self.next + 400:
            self.cache.clear()
            self._open(idx)
        n = self.w * self.h * 3
        while self.next <= idx:
            raw = self.proc.stdout.read(n)
            if len(raw) < n:
                break                       # past the end of the file: the last frame stands
            f = np.frombuffer(raw, np.uint8).reshape(self.h, self.w, 3)
            self.cache[self.next] = f
            self.last = f
            self.next += 1
            if len(self.cache) > 90:
                for k in sorted(self.cache)[:30]:
                    del self.cache[k]
        if idx in self.cache:
            return self.cache[idx]
        if self.last is not None:
            return self.last
        return np.zeros((self.h, self.w, 3), np.uint8)

    def close(self) -> None:
        if self.proc:
            try:
                self.proc.kill()
                self.proc.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
            self.proc = None


def flow_copy(ff: str, clip: str, a: float, b: float, hi: int, size: tuple[int, int], out: Path) -> Path:
    """The source span a..b at `hi` fps, motion compensated, near-lossless."""
    w, h = size
    r = subprocess.run(
        [ff, "-v", "error", "-nostdin", "-y", "-ss", f"{max(0.0, a):.4f}", "-t", f"{max(0.05, b - a):.4f}",
         "-i", clip, "-an", "-vf",
         f"scale={w}:{h}:flags=bicubic,minterpolate=fps={hi}:mi_mode=mci:mc_mode=aobmc:"
         f"me_mode=bidir:me=epzs:vsbmc=1:scd=none",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "10", "-pix_fmt", "yuv420p", str(out)],
        capture_output=True, text=True, errors="replace", creationflags=_NO_WINDOW)
    if r.returncode:
        raise RuntimeError(f"optical flow: {r.stderr[-800:]}")
    return out


def slow_spans(src: np.ndarray, rate: np.ndarray, pad: float = 0.06) -> list[tuple[float, float, float]]:
    """(source from, source to, slowest rate) of each run of frames below real speed."""
    slow = np.abs(rate) < REAL
    out, i0 = [], None
    for j, f in enumerate(list(slow) + [False]):
        if f and i0 is None:
            i0 = j
        elif not f and i0 is not None:
            out.append((float(src[i0:j].min()) - pad, float(src[i0:j].max()) + pad,
                        float(np.abs(rate[i0:j]).min())))
            i0 = None
    return out


def work_size(src_w: int, src_h: int, height: int) -> tuple[int, int]:
    """The source's own aspect at no more than `height` rows (and never more than it has)."""
    h = min(src_h or height, height)
    w = int(round((src_w or h * 16 / 9) * h / max(1, src_h or h) / 2)) * 2
    return max(2, w), max(2, h // 2 * 2)


def render(clip: str, src_start: float, pieces: list, frames: int, out: Path, *,
           kills: list[float] = (), size: tuple[int, int], ff: str = "ffmpeg", work: Path,
           cancelled: Callable[[], bool] = lambda: False,
           zoom: Callable[[float], float] | None = None) -> Path:
    """Write the shot's footage, re-timed, as a 60 fps clip of exactly `frames` frames.

    `src_start` is the clip's second at the segment's first frame (it may be
    negative: a clip that starts late is held on its first frame, as the tpad
    of the plain path did).

    `zoom(t)` is a scale about the centre at segment second t -- the groove's
    bounce (fx_schedule) -- drawn here, sub-pixel, because this is where the
    game picture exists on its own. zoompan in the graph rounds to whole
    pixels, and a 0.4 % bounce is three of them.
    """
    rel, rate = frame_map(pieces, frames, kills)
    src = rel + src_start
    w, h = size
    a = max(0.0, float(src.min()) - 0.1)
    b = float(src.max()) + 0.1
    main = Frames(clip, a, FPS, b - a + 0.2, size, ff)
    work.mkdir(parents=True, exist_ok=True)
    flows = []
    try:
        for k, (fa, fb, slowest) in enumerate(slow_spans(src, rate)):
            fa = max(0.0, fa)
            hi = 120 if slowest >= 0.25 else 240
            f = flow_copy(ff, clip, fa, fb, hi, size, work / f"{out.stem}.flow{k}.mp4")
            flows.append((fa, fb, hi, Frames(str(f), 0.0, hi, fb - fa + 0.1, size, ff, scale=False), f))
        enc = subprocess.Popen(
            [ff, "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
             "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
             "-pix_fmt", "yuv420p", "-frames:v", str(frames), str(out)],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
        try:
            for j in range(frames):
                if cancelled():
                    raise RuntimeError("cancelled")
                img = _frame_at(float(src[j]), float(rate[j]), a, main, flows)
                if zoom is not None:
                    img = scaled(img, zoom(j / FPS))
                enc.stdin.write(np.ascontiguousarray(img).tobytes())
            enc.stdin.close()
            err = enc.stderr.read().decode(errors="replace")
            if enc.wait():
                raise RuntimeError(f"re-time encode: {err[-800:]}")
        except BaseException:
            enc.kill()
            raise
    finally:
        main.close()
        for *_x, fr, f in flows:
            fr.close()
            _remove(f)
    return out


def _remove(f: Path, tries: int = 20) -> None:
    """Delete a flow copy, waiting out Windows' release of it.

    The reader was killed a moment ago, and Windows refuses to delete a file
    until every handle on it is gone -- which lags the kill. Tried once, the
    delete failed silently and every slow-motion shot left its copy behind.
    """
    for _ in range(tries):
        try:
            f.unlink(missing_ok=True)
            return
        except OSError:
            time.sleep(0.1)
    log.warning("could not remove the optical-flow copy %s", f)


def _frame_at(s: float, r: float, base: float, main: Frames, flows: list) -> np.ndarray:
    if abs(r) < REAL:
        for fa, fb, hi, fr, _f in flows:
            if fa <= s <= fb:
                x = max(0.0, (s - fa) * hi)
                x0 = int(math.floor(x))
                wgt = x - x0
                f0 = fr.frame(x0)
                if wgt < 0.02:
                    return f0
                f1 = fr.frame(x0 + 1)
                return (f0.astype(np.float32) * (1 - wgt) + f1.astype(np.float32) * wgt).astype(np.uint8)
    x = (s - base) * FPS
    span = abs(r) * SHUTTER
    if span <= 1.0:
        return main.frame(int(round(x)))
    lo, hi = (x - span, x) if r > 0 else (x, x + span)
    acc, wsum = None, 0.0
    for k in range(int(math.floor(lo)), int(math.ceil(hi)) + 1):
        wk = max(0.0, min(hi, k + 0.5) - max(lo, k - 0.5))
        if wk > 0:
            f = main.frame(k).astype(np.float32) * wk
            acc = f if acc is None else acc + f
            wsum += wk
    return (acc / max(wsum, 1e-6)).astype(np.uint8)


def scaled(img: np.ndarray, z: float) -> np.ndarray:
    """img scaled by z about its centre, cropped back to its size, sub-pixel."""
    if abs(z - 1.0) < 1e-5:
        return img
    from PIL import Image

    h, w = img.shape[:2]
    a = 1.0 / z
    out = Image.fromarray(img).transform((w, h), Image.AFFINE, (a, 0, w / 2 * (1 - a), 0, a, h / 2 * (1 - a)),
                                         resample=Image.BILINEAR)
    return np.asarray(out)
