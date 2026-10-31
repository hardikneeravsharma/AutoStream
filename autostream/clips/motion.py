"""Which way the camera is moving at a moment of a clip (F14).

WHY THIS EXISTS
    Build and drop chose the shots after the drop one target at a time, by kill
    score alone, so a cut could join a camera swinging right to one swinging
    left -- the eye is thrown one way and yanked back. ChatGPT's review of the
    planner called it greedy picking. The planner now looks a few shots ahead
    and, among candidates whose kills are as good, prefers cuts where the
    picture keeps moving the same way. This module is the measurement.

WHAT IS MEASURED (agreed with ChatGPT, 2026-11-01)
    Screen-space horizontal motion of the background, the camera as the viewer
    sees it -- not what the player pressed. A small grey copy of the clip is read
    at FPS frames a second; between each pair of frames the shift of a band of
    the picture is found by phase correlation. The band leaves out what moves
    with the screen rather than the world: the top strip (score, kill feed,
    minimap), the lower half (weapon, abilities, health) and the crosshair box.

    A window's motion is the shifts summed over it, as a share of the frame's
    width. It counts as MOVING when that is at least MOVING_FRAC and at least
    CONSISTENT of the pairs in it agree on the direction and were confidently
    measured; anything less is UNKNOWN, which the planner treats as neutral --
    never a reason to drop a clip.

COST
    Only the 3.5 s around a candidate's kill, at 192x108 grey, and only for the
    candidates the planner is actually weighing against each other. Kept in the
    clips folder's .studio cache by path, size, modification time and stretch,
    so a stretch is read once however often it is planned.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

FPS = 20
W, H = 192, 108
# The band: rows 25-60 % of the height, columns 5-95 % of the width, with the
# crosshair's box (columns 42-58 %, rows 38-60 %) flattened to the band's mean.
BAND_ROWS = (0.25, 0.60)
BAND_COLS = (0.05, 0.95)
CROSS_COLS = (0.42, 0.58)
CROSS_ROWS = (0.38, 0.60)
WINDOW = 0.25                 # seconds either side of a cut
MOVING_FRAC = 0.01            # of the frame's width, over the window
CONSISTENT = 0.60             # share of the window's pairs that must agree
PEAK_MIN = 0.08               # phase-correlation peak below this is no measurement
VERSION = 1


def _frames(path: str, start: float = 0.0, seconds: float | None = None) -> np.ndarray:
    from .tools import ffmpeg_raw

    span = ["-ss", f"{max(0.0, start):.3f}"] if start > 0 else []
    if seconds is not None:
        span += ["-t", f"{seconds:.3f}"]
    raw = ffmpeg_raw([*span, "-i", str(path), "-an", "-sn",
                      "-vf", f"fps={FPS},scale={W}:{H}:flags=area,format=gray",
                      "-f", "rawvideo", "-"])
    n = len(raw) // (W * H)
    if n < 2:
        return np.zeros((0, H, W), dtype=np.float32)
    return np.frombuffer(raw[:n * W * H], dtype=np.uint8).reshape(n, H, W).astype(np.float32)


def _band(f: np.ndarray) -> np.ndarray:
    r0, r1 = int(H * BAND_ROWS[0]), int(H * BAND_ROWS[1])
    c0, c1 = int(W * BAND_COLS[0]), int(W * BAND_COLS[1])
    b = f[r0:r1, c0:c1].copy()
    cr0, cr1 = int(H * CROSS_ROWS[0]) - r0, int(H * CROSS_ROWS[1]) - r0
    cc0, cc1 = int(W * CROSS_COLS[0]) - c0, int(W * CROSS_COLS[1]) - c0
    b[max(0, cr0):cr1, max(0, cc0):cc1] = b.mean()
    b -= b.mean()
    return b * np.outer(np.hanning(b.shape[0]), np.hanning(b.shape[1]))


def _shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """How far b's picture sits to the right of a's, in pixels, and how sure.

    Phase correlation: the normalised cross-power spectrum's inverse peaks at
    the translation; its height (0..1) is the confidence. Sub-pixel by a
    parabola through the peak and its neighbours."""
    A, B = np.fft.rfft2(a), np.fft.rfft2(b)
    R = B * np.conj(A)
    R /= np.abs(R) + 1e-9
    c = np.fft.irfft2(R, s=a.shape)
    y, x = np.unravel_index(int(np.argmax(c)), c.shape)
    peak = float(c[y, x])
    n = c.shape[1]
    left, right = c[y, (x - 1) % n], c[y, (x + 1) % n]
    den = left - 2 * peak + right
    sub = 0.5 * (left - right) / den if abs(den) > 1e-12 else 0.0
    dx = x + sub
    if dx > n / 2:
        dx -= n
    return float(dx), peak


def track(path: str, start: float = 0.0, seconds: float | None = None) -> dict:
    """{"start", "fps", "width", "dx": [per pair, pixels], "conf": [per pair]} for the
    stretch of a clip from `start` (clip seconds), or the whole clip."""
    frames = _frames(path, start, seconds)
    bands = [_band(f) for f in frames]
    dx, conf = [], []
    for a, b in zip(bands, bands[1:]):
        d, p = _shift(a, b)
        dx.append(round(d, 3))
        conf.append(round(p, 3))
    return {"version": VERSION, "start": round(max(0.0, start), 3), "fps": FPS, "width": W,
            "dx": dx, "conf": conf}


def window(tr: dict | None, t0: float, t1: float) -> tuple[float, float]:
    """(motion as a share of the width, +right / -left, agreement 0..1) over clip seconds [t0, t1]."""
    if not tr or not tr.get("dx"):
        return 0.0, 0.0
    fps = float(tr.get("fps") or FPS)
    s = float(tr.get("start") or 0.0)
    i0 = max(0, int(round((t0 - s) * fps)))
    i1 = min(len(tr["dx"]), max(i0 + 1, int(round((t1 - s) * fps))))
    if i0 >= len(tr["dx"]):
        return 0.0, 0.0
    dx = np.asarray(tr["dx"][i0:i1], dtype=float)
    conf = np.asarray(tr["conf"][i0:i1], dtype=float)
    if not len(dx):
        return 0.0, 0.0
    total = float(dx.sum()) / float(tr.get("width") or W)
    sign = np.sign(total)
    agree = float(np.mean((np.sign(dx) == sign) & (conf >= PEAK_MIN))) if sign else 0.0
    return total, agree


def direction(tr: dict | None, t0: float, t1: float) -> int:
    """+1 / -1 when the window is moving that way on screen, 0 when it is not or cannot be told."""
    total, agree = window(tr, t0, t1)
    if abs(total) >= MOVING_FRAC and agree >= CONSISTENT:
        return 1 if total > 0 else -1
    return 0


def cut_cost(out_dir: int, in_dir: int) -> float:
    """What a cut from a shot leaving in `out_dir` into one arriving in `in_dir` costs:
    1 when both move and disagree, -0.5 when both move the same way, else nothing."""
    if not out_dir or not in_dir:
        return 0.0
    return 1.0 if out_dir != in_dir else -0.5


# The stretch read around a kill: the earliest cut-in (the longest run-up) to the
# latest cut-out (the longest a shot runs on after its kill), with a window to spare.
BEFORE_KILL = 1.5
AFTER_KILL = 2.0
PREFETCH_BUDGET = 8.0         # seconds a plan may spend reading motion, all of it


class Cache:
    """Tracks by clip and kill, read once, kept on disk beside the other .studio caches.

    Only the few seconds around a kill are read -- a whole-clip decode ran at about
    13x real time, three seconds a clip, and a plan weighs dozens of clips."""

    def __init__(self, folder: Path | None):
        self.folder = Path(folder) / "motion" if folder else None
        self.mem: dict[tuple, dict | None] = {}

    def _key(self, path: str, start: float) -> str | None:
        try:
            st = Path(path).stat()
        except OSError:
            return None
        h = hashlib.sha1(f"{Path(path).resolve()}|{st.st_size}|{int(st.st_mtime)}|{start:.2f}|{VERSION}"
                         .encode("utf-8")).hexdigest()[:20]
        return h

    def around(self, path: str, kill: float) -> dict | None:
        """The track of the stretch of `path` around a kill at `kill` clip seconds."""
        start = round(max(0.0, float(kill) - BEFORE_KILL), 2)
        mk = (path, start)
        if mk in self.mem:
            return self.mem[mk]
        key = self._key(path, start)
        tr = None
        f = self.folder / f"{key}.json" if (self.folder and key) else None
        if f is not None and f.is_file():
            try:
                tr = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                tr = None
        if tr is None and key:
            try:
                tr = track(path, start, BEFORE_KILL + AFTER_KILL)
            except Exception as e:  # noqa: BLE001 - unknown motion is neutral, never an error
                log.info("no motion track for %s: %s", Path(path).name, e)
                tr = None
            if tr is not None and f is not None:
                try:
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_text(json.dumps(tr), encoding="utf-8")
                except OSError:
                    pass
        self.mem[mk] = tr
        return tr

    def prefetch(self, pairs, budget: float = PREFETCH_BUDGET, workers: int = 6) -> int:
        """Read the stretches around these (path, kill) pairs, several at once, for at
        most `budget` seconds. -> how many are ready. What is still reading when the
        budget runs out finishes in the background and is there for the next plan; this
        plan treats it as unknown. A first plan was otherwise ~0.5 s per candidate longer."""
        from concurrent.futures import ThreadPoolExecutor, wait

        todo = list(dict.fromkeys((str(p), round(max(0.0, float(k) - BEFORE_KILL), 2), float(k))
                                  for p, k in pairs))
        todo = [(p, k) for p, s, k in todo if (p, s) not in self.mem]
        if todo:
            pool = ThreadPoolExecutor(max_workers=workers)
            futures = [pool.submit(self.around, p, k) for p, k in todo]
            wait(futures, timeout=budget)
            pool.shutdown(wait=False)
        return sum(1 for p, k in pairs
                   if self.mem.get((str(p), round(max(0.0, float(k) - BEFORE_KILL), 2))) is not None)

    def direction(self, path: str, kill: float, t0: float, t1: float) -> int:
        """direction() over clip seconds [t0, t1] of the stretch round `kill`, if it has been
        read; 0 -- unknown, neutral -- if not. Never reads: prefetch() does that."""
        tr = self.mem.get((str(path), round(max(0.0, float(kill) - BEFORE_KILL), 2)))
        return direction(tr, t0, t1)
