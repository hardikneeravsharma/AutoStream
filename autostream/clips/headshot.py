"""Was a Valorant kill a headshot? Read off the kill feed, only around the kill.

WHAT IS THERE
    A headshot puts a small crosshair icon in the kill feed row, between the
    weapon and the victim's name. A body or leg kill does not. The player's own
    rows carry the yellow border valorant_feed already reads, so the kill's row
    is one of those, and the icon is white on the row's teal or red.

WHY ONLY AROUND THE KILL
    The kill is already found -- by Riot's record, the kill emblem or the
    player's own marks -- so there is no scan to do: three single frames a
    moment after each kill (LOOKS), the band cropped, decoded on the card when
    there is one. Nothing here runs over the whole recording.

WHICH ROW IS THIS KILL'S
    The feed adds new rows at the BOTTOM. So a moment after a kill, its row is
    the lowest of the player's own rows -- unless more of the player's kills
    landed in between, in which case it is that many rows up. Tracking rows
    from frame to frame was tried first and was worse: two kills a second apart
    swapped rows, which is the case that matters most.

THE ICON
    Matched against a template measured from the player's own recordings
    (templates/valorant_headshot.npy: the median of 30 headshot rows), slid
    along the row and scored by normalised correlation.

MEASURED against Riot's own record. A kill counts as a headshot when every hit
the player landed on that victim that round was a headshot, and as a body
kill when none was; mixed rounds say nothing about the killing shot and were
left out. Over 92 such kills on five recordings (08-27 to 10-10): a row was
found for 85, and 82 of those were read right -- headshots scored 0.55-0.92,
body kills 0.03-0.40, so THRESHOLD sits in the gap. Two of the three misses
were kills under a second apart, where Riot's own time is too coarse to say
which row is which.
"""
from __future__ import annotations

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

log = logging.getLogger("autostream.clips.headshot")

TEMPLATE = Path(__file__).resolve().parent / "templates" / "valorant_headshot.npy"
# The Valorant profile's own feed band, so this reads exactly what the scan reads.
BAND = (0.50, 0.070, 1.00, 0.235)
LOOKS = (0.5, 0.9, 1.3)       # s after the kill: the row is up and has settled
THRESHOLD = 0.45
ICON_W = 0.68                 # the icon's width, as a share of the row's height
WHITE = 200                   # min(R, G, B) above this is the icon's white
WORKERS = 4

_template: np.ndarray | None = None


def _tmpl() -> np.ndarray:
    global _template
    if _template is None:
        _template = np.load(TEMPLATE).astype(np.float32)
    return _template


def _resize(t: np.ndarray, w: int, h: int) -> np.ndarray:
    from PIL import Image
    img = Image.fromarray((np.clip(t, 0, 1) * 255).astype(np.uint8))
    return np.asarray(img.resize((max(1, w), max(1, h)), Image.BILINEAR), dtype=np.float32) / 255.0


def _yellow_rows(a: np.ndarray, frame_height: int) -> list[tuple[int, int, int, int]]:
    """Own rows found by their yellow border lines alone: (y0, y1, x0, x1).

    The second way in, for a row the feed reader does not return -- measured
    on a reddish wall and under the network overlay, where its two-tone test
    lost the row although the border was plain to see.
    """
    from .valorant_feed import masks
    k = frame_height / 1080
    yel = masks(a)[2]
    lines = np.flatnonzero(yel.sum(axis=1) >= 60 * k)
    groups: list[list[int]] = []
    for y in lines:
        if groups and y - groups[-1][-1] <= 2:
            groups[-1].append(int(y))
        else:
            groups.append([int(y)])
    out, i = [], 0
    while i + 1 < len(groups):
        top, bot = groups[i], groups[i + 1]
        if 22 * k <= bot[0] - top[-1] <= 44 * k:
            xs = np.flatnonzero(yel[top[0]:top[-1] + 1].sum(axis=0) > 0)
            if len(xs):
                out.append((top[0], bot[-1] + 1, int(xs.min()), int(xs.max()) + 1))
            i += 2
        else:
            i += 1
    return out


def own_rows(a: np.ndarray, frame_height: int) -> list[tuple[int, int, int, int]]:
    """The player's own kill rows in one frame of the band, top to bottom."""
    from .valorant_feed import read_frame
    out = [(r.y0, r.y1, r.x0, r.x1) for r in read_frame(a, frame_height=frame_height)
           if r.kind == "kill"]
    for y0, y1, x0, x1 in _yellow_rows(a, frame_height):
        if not any(min(y1, b1) - max(y0, b0) > 0.5 * (y1 - y0) for b0, b1, _, _ in out):
            out.append((y0, y1, x0, x1))
    return sorted(out)


def icon_score(a: np.ndarray, row: tuple[int, int, int, int]) -> float:
    """How well the headshot icon fits anywhere along this row: -1 to 1."""
    y0, y1, x0, _x1 = row
    h = y1 - y0
    w = int(round(ICON_W * h))
    if h < 8 or w < 4:
        return -1.0
    m = (a[y0:y1].min(axis=2) > WHITE).astype(np.float32)
    if m.shape[1] - x0 < w:
        return -1.0
    t = _resize(_tmpl(), w, h)
    tz = t - t.mean()
    tn = float(np.sqrt((tz ** 2).sum())) or 1.0
    win = np.lib.stride_tricks.sliding_window_view(m[:, x0:], (h, w))[0]   # (n, h, w)
    pz = win - win.mean(axis=(1, 2), keepdims=True)
    pn = np.sqrt((pz ** 2).sum(axis=(1, 2)))
    num = (pz * tz).sum(axis=(1, 2))
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.where(pn > 0, num / (pn * tn), -1.0)
    return float(s.max()) if s.size else -1.0


def _frame(video: str, t: float, size: tuple[int, int]) -> tuple[np.ndarray | None, int]:
    from .tools import _NO_WINDOW, binary, decode_args
    W, H = size
    x0, y0 = int(W * BAND[0]), int(H * BAND[1])
    w, h = int(W * BAND[2]) - x0, int(H * BAND[3]) - y0
    p = subprocess.run([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
                        *decode_args(), "-ss", f"{max(0.0, t):.3f}", "-i", str(video),
                        "-frames:v", "1", "-an", "-sn", "-vf", f"crop={w}:{h}:{x0}:{y0}",
                        "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                       capture_output=True, creationflags=_NO_WINDOW)
    raw = p.stdout or b""
    if len(raw) < w * h * 3:
        return None, H
    return np.frombuffer(raw[:w * h * 3], np.uint8).reshape(h, w, 3), H


def _one(video: str, t: float, others: list[float], size: tuple[int, int]) -> bool | None:
    best = None
    for dt in LOOKS:
        a, H = _frame(video, t + dt, size)
        if a is None:
            continue
        rows = own_rows(a, H)
        # Kills of the player's own after this one and before this frame each
        # added a row below it.
        after = sum(1 for u in others if t < u <= t + dt - 0.15)
        i = len(rows) - 1 - after
        if i < 0:
            continue
        s = icon_score(a, rows[i])
        best = s if best is None else max(best, s)
    return None if best is None else best >= THRESHOLD


def read(video: str | Path, times: list[float]) -> list[bool | None]:
    """For each kill time (seconds into `video`): True a headshot, False not, None unread."""
    from .tools import media_info
    times = [float(t) for t in times]
    if not times:
        return []
    try:
        info = media_info(str(video))
        size = (int(info["width"]), int(info["height"]))
    except Exception as e:                                   # noqa: BLE001
        log.info("headshot: cannot read %s (%s)", video, e)
        return [None] * len(times)
    if size[0] <= 0 or size[1] <= 0:
        return [None] * len(times)

    def job(i: int) -> bool | None:
        try:
            return _one(str(video), times[i], times[:i] + times[i + 1:], size)
        except Exception as e:                               # noqa: BLE001
            log.info("headshot: kill at %.1fs unread (%s)", times[i], e)
            return None
    with ThreadPoolExecutor(WORKERS) as ex:
        return list(ex.map(job, range(len(times))))


def is_valorant(game: str) -> bool:
    return "valorant" in str(game or "").lower()


def annotate(video: str | Path, kills: list[dict]) -> int:
    """Set "hs" on each kill dict that has a time. -> how many were read either way."""
    rows = [k for k in kills if isinstance(k, dict) and k.get("time") is not None]
    got = read(video, [float(k["time"]) for k in rows])
    n = 0
    for k, hs in zip(rows, got):
        if hs is not None:
            k["hs"] = bool(hs)
            n += 1
    return n
