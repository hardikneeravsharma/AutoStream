"""Marvel Rivals, `mode: summary`: read a recording's HUD and plan a MATCH SUMMARY.

WHAT A SUMMARY IS, AND WHY IT IS NOT A HIGHLIGHT REEL
    Every other game here is clipped around kills. The Marvel Rivals videos
    people actually watch are something else: ONE match, start to finish, in
    order, with the dead time taken out. Measured on YouTube before any of
    this was written -- req's 68-elim Spider-Man game (89k views) runs 23
    minutes nearly uncut, TimTheTatman's rank-up game 15, and Necros' editor
    made about ten hard cuts in 17 minutes. The frames either side of those
    cuts are a respawn countdown, hero select and the walk back to the fight.
    Every fight stays. So this module finds matches and dead time, not kills.

WHAT THE HUD GIVES, AND WHAT IT IS USED FOR
    All measured on 1080p recordings made by AutoStream, at the default HUD:

      ult meter, bottom right   The percentage is drawn in large clean digits,
                                read by correlation against ten glyphs cut
                                from real footage (rivals-digits.npy). It
                                climbs while you deal damage or heal and barely
                                moves otherwise, which makes it the best
                                "you are fighting" signal there is: AUC 0.91
                                against hand-labelled fight/quiet time, where
                                game loudness scored 0.44 -- no better than a
                                coin, because walking and music are loud too.
                                At 100 the digits give way to a yellow icon;
                                that icon going back to a number is an ult.
      health bar, bottom centre Whether it is full. Not full is a fight
                                (0.92 on the same labels).
      objective line, top left  A small white square and two lines of text.
                                The square is absent while you are dead; the
                                text changing is a new phase of the match.
      progress bar, top centre  Present in a match, absent in the practice
                                range -- which has the rest of the HUD and
                                would otherwise read as a match.

    Nothing here needs a name, a colour or Tesseract: the HUD is the same for
    everyone. What it does assume is the DEFAULT HUD SCALE on a 16:9 frame --
    the references were cut at it -- and `hud_found()` says so up front rather
    than letting a scan read nothing for ten minutes.

HOW A MATCH IS CUT (see plan())
    Kept: everything from the first second of the match to the last, then the
    VICTORY/DEFEAT screen. Taken out:
      * the setup in spawn, up to a few seconds before the first engagement;
      * each death, from a few seconds after it (you see what killed you) to a
        few seconds before you are fighting again -- the spectating, the
        respawn and the walk back as one cut.
    "Fighting again" is the first of: the ult meter rising, the health bar
    dropping, or the heal/damage border. Against hand labels on two matches it
    lands 1-4 s from where a person would put it, and the cut stops LEAD
    seconds before it so the fight opens with its run-up.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .tools import _NO_WINDOW, binary, has_cuda, media_info

log = logging.getLogger("autostream.clips.rivals")

FPS = 2.0
SPAN_SECONDS = 300.0

# The frame is read at HALF of 1080p -- 960x540 -- except the ult digits, which
# are cropped at full 1080p scale first: at half size a digit is 18 px tall and
# 6 and 8 start to merge. Both come out of ONE decode as one composite frame,
# the half-size picture with the digit crop pasted underneath.
W, H = 960, 540
ULT_FULL = (1720 / 1920, 940 / 1080, 196 / 1920, 136 / 1080)   # x, y, w, h
UW, UH = 196, 136
FRAME_H = H + UH

# Half-size crops, (x0, y0, x1, y1).
TL = (0, 0, 480, 64)          # objective line, death countdown, result title
TC = (330, 0, 630, 70)        # timer and progress bar
ULT = (860, 470, 958, 538)    # the ult meter
HP = (370, 480, 590, 530)     # the health bar

# The objective's square: a flat white block at the very start of the line.
BULLET = (1, 22, 10, 29)      # x0, y0, x1, y1 inside TL
# The line of text under it, downsampled 2x for comparing phases.
LINE = (12, 30, 470, 44)

# The digits inside the full-scale ult crop.
DIGITS = (40, 28, 118, 72)    # x0, y0, x1, y1
GLYPH_W, GLYPH_H = 14, 24

# Correlation floors, from the histograms of the three HUD references over a
# 38-minute recording: in a match they sit at 0.75-0.95, in menus below 0.1,
# and a dead player's dimmed HUD in between -- 0.25-0.6.
HUD_FULL = 0.6
HUD_ULT_PART, HUD_HP_PART = 0.25, 0.35
PROGRESS_MIN = 0.3            # practice range: ~0.0; a match: 0.5-0.85


@dataclass
class Readings:
    """One row per sampled frame. Everything planning needs, and nothing else."""
    t: np.ndarray
    bullet: np.ndarray         # bool: the objective square is drawn
    ult_ncc: np.ndarray
    hp_ncc: np.ndarray
    tc_ncc: np.ndarray
    ult: np.ndarray            # int: the ult percentage, -1 unreadable
    ready: np.ndarray          # yellow fraction in the ult box (ult ready)
    hpfrac: np.ndarray         # how full the health bar is, 0-1
    green: np.ndarray          # heal border
    red: np.ndarray            # low-health border
    tall: np.ndarray           # rows of large bright text, top left (a result title)
    tl_yellow: np.ndarray      # yellow behind that title (VICTORY is yellow)
    line: np.ndarray           # packed bits of the objective line

    def __len__(self) -> int:
        return len(self.t)

    def save(self, path: Path) -> None:
        np.savez_compressed(path, **{k: getattr(self, k) for k in self.__dataclass_fields__})

    @classmethod
    def load(cls, path: Path) -> "Readings":
        with np.load(path) as z:
            return cls(**{k: z[k] for k in cls.__dataclass_fields__})

    @classmethod
    def join(cls, parts: list["Readings"]) -> "Readings":
        keys = list(cls.__dataclass_fields__)
        if not parts:
            return cls(**{k: np.zeros((0,) if k != "line" else (0, 1), np.float32)
                          for k in keys})
        return cls(**{k: np.concatenate([getattr(p, k) for p in parts])
                      for k in keys})


# ---------------------------------------------------------------- references

_REF: dict[str, np.ndarray] = {}
_REF_LOCK = threading.Lock()


def _templates() -> Path:
    from .. import paths
    return paths.CLIP_TEMPLATES_BUILTIN


def refs() -> dict[str, np.ndarray]:
    """The shipped HUD references. Cut from real footage; see the module doc."""
    with _REF_LOCK:
        if not _REF:
            d = _templates()
            for k in ("ult", "hp", "tc", "digits"):
                _REF[k] = np.load(d / f"rivals-{k}.npy").astype(np.float32)
        return _REF


def _edges(g: np.ndarray) -> np.ndarray:
    g = g.astype(np.float32)
    gx = np.abs(np.diff(g, axis=1))[:-1, :]
    gy = np.abs(np.diff(g, axis=0))[:, :-1]
    return gx + gy


def _ncc(a: np.ndarray, ref: np.ndarray) -> float:
    """Normalised correlation of an EDGE map against a normalised reference.

    Edges rather than pixels because the HUD is drawn over the world: the
    meter's frame is the same shape over a sunlit wall and a dark corridor,
    its brightness is not.
    """
    e = _edges(a)
    s = e.std()
    if s < 1e-6:
        return 0.0
    return float(((e - e.mean()) / s * ref).mean())


def _crop(a: np.ndarray, box) -> np.ndarray:
    x0, y0, x1, y1 = box
    return a[y0:y1, x0:x1]


# ------------------------------------------------------------------- digits

def glyphs(region: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """Split the ult digits into single glyphs. -> [(x, grey patch)]

    The digits are white on the meter's dark blue, so a column with bright
    pixels in it belongs to a digit; runs of such columns are the digits.
    A glyph is 28-42 px tall at 1080p scale, 6-26 wide ("1" to "0").
    """
    on = region > 190
    rows = on.sum(1)
    if rows.max(initial=0) < 3:
        return []
    ys = np.where(rows >= 2)[0]
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    if not 28 <= y1 - y0 <= 42:
        return []
    cols = on[y0:y1].sum(0) >= 2
    out = []
    i, n = 0, len(cols)
    while i < n:
        if not cols[i]:
            i += 1
            continue
        j = i
        while j < n and cols[j]:
            j += 1
        if 6 <= j - i <= 26:
            out.append((i, region[y0:y1, i:j].astype(np.float32)))
        i = j
    return out


def _norm_glyph(g: np.ndarray) -> np.ndarray:
    ys = (np.arange(GLYPH_H) * g.shape[0] / GLYPH_H).astype(int)
    xs = (np.arange(GLYPH_W) * g.shape[1] / GLYPH_W).astype(int)
    r = g[ys][:, xs]
    return ((r - r.mean()) / (r.std() + 1e-6)).ravel()


def read_ult(full: np.ndarray, floor: float = 0.70) -> int:
    """The ult percentage from the full-scale meter crop (grey), or -1.

    Measured: a clean monotonic climb frame to frame across whole lives, with
    an isolated misread (a dropped digit) every minute or so -- which is why
    planning never looks at one reading alone (see _smooth_ult).
    """
    T = refs()["digits"].reshape(10, -1)
    x0, y0, x1, y1 = DIGITS
    ds = []
    for _x, g in glyphs(full[y0:y1, x0:x1]):
        v = _norm_glyph(g)
        s = T @ v / len(v)
        j = int(s.argmax())
        if s[j] >= floor:
            ds.append(j)
    if not ds or len(ds) > 3:
        return -1
    val = int("".join(map(str, ds)))
    return val if val <= 100 else -1


# -------------------------------------------------------------- one frame

def read_frame(img: np.ndarray) -> tuple:
    """Every reading from one composite frame (see W/H/UW/UH)."""
    R = refs()
    half = img[:H]
    grey = half.astype(np.uint16).sum(2) // 3
    tl = _crop(grey, TL)
    sq = _crop(tl, BULLET).astype(np.float32)
    bullet = bool(sq.min() > 190 and sq.std() < 25)

    ult_rgb = _crop(half, ULT).astype(np.int16)
    ult_ncc = _ncc(ult_rgb.mean(2), R["ult"])
    rr, gg, bb = ult_rgb[..., 0], ult_rgb[..., 1], ult_rgb[..., 2]
    ready = float(((rr > 180) & (gg > 140) & (bb < 100)).mean())

    hp = _crop(grey, HP)
    hp_ncc = _ncc(hp, R["hp"])
    tc_ncc = _ncc(_crop(grey, TC), R["tc"])

    # Health: the bar is rows 24-28 of the crop, x 20-202; filled is bright.
    bar = hp[24:29, 20:202] > 170
    colon = bar.mean(0) > 0.6
    hpfrac = float((np.where(colon)[0].max() + 1) / len(colon)) if colon.any() else 0.0

    # The screen edge: the heal border is green, low health is red.
    sm = half[::10, ::10].astype(np.int16)
    edge = np.concatenate([sm[:4].reshape(-1, 3), sm[-4:].reshape(-1, 3),
                           sm[:, :4].reshape(-1, 3), sm[:, -4:].reshape(-1, 3)])
    er, eg, eb = edge[:, 0], edge[:, 1], edge[:, 2]
    green = float(((eg > 120) & (eg > er + 30) & (eg > eb + 30)).mean())
    red = float(((er > 130) & (er > eg + 60) & (er > eb + 60)).mean())

    # A result title: 26+ rows of big bright text where the objective goes.
    big = tl[6:60, 8:200] > 215
    tall = int((big.mean(1) > 0.08).sum())
    corner = sm[0:12, 0:30]
    tl_yellow = float(((corner[..., 0] > 170) & (corner[..., 1] > 140)
                       & (corner[..., 2] < 90)).mean())

    x0, y0, x1, y1 = LINE
    line = np.packbits((tl[y0:y1:2, x0:x1:2] > 200).ravel())

    ult = read_ult(img[H:H + UH, :UW].astype(np.uint16).sum(2) // 3)
    return (bullet, ult_ncc, hp_ncc, tc_ncc, ult, ready, hpfrac, green, red,
            tall, tl_yellow, line)


def _pack(t: list[float], rows: list[tuple]) -> Readings:
    cols = list(zip(*rows)) if rows else [[]] * 12
    f32 = lambda c: np.asarray(c, np.float32)  # noqa: E731
    return Readings(
        t=np.asarray(t, np.float64),
        bullet=np.asarray(cols[0], bool),
        ult_ncc=f32(cols[1]), hp_ncc=f32(cols[2]), tc_ncc=f32(cols[3]),
        ult=np.asarray(cols[4], np.int16),
        ready=f32(cols[5]), hpfrac=f32(cols[6]),
        green=f32(cols[7]), red=f32(cols[8]),
        tall=np.asarray(cols[9], np.int16), tl_yellow=f32(cols[10]),
        line=(np.stack(cols[11]) if rows else np.zeros((0, 1), np.uint8)),
    )


# -------------------------------------------------------------- the decode

def _chain(on_gpu: bool) -> str:
    x, y, w, h = ULT_FULL
    head = f"fps={FPS},hwdownload,format=nv12," if on_gpu else f"fps={FPS},"
    return (f"{head}split[a][b];"
            f"[a]scale={W}:{H}[s];"
            f"[b]crop=iw*{w:.6f}:ih*{h:.6f}:iw*{x:.6f}:ih*{y:.6f},scale={UW}:{UH}[u];"
            f"[s]pad={W}:{FRAME_H}[p];[p][u]overlay=0:{H},format=rgb24")


def _args(video: Path, start: float, dur: float, on_gpu: bool) -> list[str]:
    pre = (["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if on_gpu
           else (["-hwaccel", "cuda"] if has_cuda() else []))
    return [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
            *pre, "-ss", f"{start:.3f}", "-i", str(video),
            "-t", f"{max(0.5, dur):.3f}", "-an", "-sn",
            "-filter_complex", _chain(on_gpu),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]


def _frames(video: Path, start: float, dur: float, on_gpu: bool,
            cancelled: Callable[[], bool] | None = None):
    size = W * FRAME_H * 3
    proc = subprocess.Popen(_args(video, start, dur, on_gpu),
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=_NO_WINDOW)
    try:
        i = 0
        while True:
            if cancelled and cancelled():
                break
            buf = proc.stdout.read(size)
            if not buf or len(buf) < size:
                break
            yield start + i / FPS, np.frombuffer(buf, np.uint8).reshape(FRAME_H, W, 3)
            i += 1
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
        proc.terminate()
        proc.wait(timeout=10)


def _gpu_works(video: Path) -> bool:
    """Whether frames can be dropped on the card. Probed, not assumed."""
    if not has_cuda():
        return False
    try:
        out = subprocess.run(_args(video, 0.0, 0.6, True), capture_output=True,
                             timeout=120, creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return len(out) >= W * FRAME_H * 3


def _span(args) -> tuple[float, Readings]:
    video, start, dur, on_gpu, cancelled = args
    t, rows = [], []
    for at, img in _frames(video, start, dur, on_gpu, cancelled):
        t.append(at)
        rows.append(read_frame(img))
    return start, _pack(t, rows)


def scan(video: Path, *, start: float = 0.0, duration: float | None = None,
         workers: int = 4, progress: Callable[[int, int], None] | None = None,
         cancelled: Callable[[], bool] | None = None) -> Readings:
    """Read the whole window at FPS. -> Readings

    Spans run four at a time, as Valorant's do: the decode is the cost and one
    ffmpeg does not saturate a GPU decoder. Measured on a 38-minute 1080p60
    recording: 2 min 19 s (16x) for the same crops.
    """
    video = Path(video)
    total = float(duration if duration is not None
                  else media_info(video).get("duration") or 0.0)
    on_gpu = _gpu_works(video)
    spans = []
    s = 0.0
    while s < total:
        spans.append((video, start + s, min(SPAN_SECONDS, total - s), on_gpu, cancelled))
        s += SPAN_SECONDS
    done = 0
    parts: list[tuple[float, Readings]] = []
    with ThreadPoolExecutor(max(1, workers)) as ex:
        for got in ex.map(_span, spans):
            parts.append(got)
            done += 1
            if progress:
                progress(done, len(spans))
    parts.sort(key=lambda p: p[0])
    return Readings.join([p for _s, p in parts])


def hud_found(r: Readings) -> bool:
    """Whether the recording shows the HUD these references were cut from.

    A minute of in-match HUD is the bar: every real match has ten, and a
    recording at another HUD scale or aspect ratio has none at all.
    """
    return int(((r.ult_ncc > HUD_FULL) | (r.hp_ncc > HUD_FULL)).sum()) >= 60 * FPS


# ----------------------------------------------------------------- analysis

def runs(x: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index pairs of the True runs."""
    x = np.asarray(x, bool)
    if not len(x):
        return []
    d = np.diff(np.r_[0, x.astype(np.int8), 0])
    return list(zip(np.where(d == 1)[0].tolist(), np.where(d == -1)[0].tolist()))


def _smooth(x: np.ndarray, w: int) -> np.ndarray:
    return np.convolve(np.asarray(x, float), np.ones(w) / w, mode="same")


def _smooth_ult(v: np.ndarray, w: int = 5) -> np.ndarray:
    """Median of the readable values around each sample; -1 where too few."""
    v = np.asarray(v, float)
    out = np.full(len(v), -1.0)
    h = w // 2
    for i in range(len(v)):
        seg = v[max(0, i - h): i + h + 1]
        seg = seg[seg >= 0]
        if len(seg) >= 2:
            out[i] = float(np.median(seg))
    return out


@dataclass
class Match:
    start: float
    end: float
    deaths: list[tuple[float, float]] = field(default_factory=list)
    casts: list[float] = field(default_factory=list)
    phases: list[float] = field(default_factory=list)   # objective changes
    result: str = ""                                    # victory | defeat | ""
    result_at: float = 0.0

    @property
    def seconds(self) -> float:
        return self.end - self.start


# Gaps inside a match that are not the end of it: a round change goes dark for
# 4-20 s, a death dims the HUD for ~10. The gap between two matches is minutes
# of results, menus and hero select.
MATCH_GAP = 40.0
MATCH_MIN = 180.0
DEATH_MIN, DEATH_MAX = 5.0, 30.0


def matches(r: Readings) -> list[Match]:
    n = len(r)
    if not n:
        return []
    hud = (r.ult_ncc > HUD_FULL) | (r.hp_ncc > HUD_FULL)
    part = (r.ult_ncc > HUD_ULT_PART) | (r.hp_ncc > HUD_HP_PART)
    progress = _smooth(r.tc_ncc > PROGRESS_MIN, 21) > 0.3
    live = part & progress
    for a, b in runs(~live):
        if 0 < a and b < n and (r.t[b - 1] - r.t[a]) <= MATCH_GAP:
            live[a:b] = True
    out = []
    for a, b in runs(live):
        if r.t[b - 1] - r.t[a] < MATCH_MIN or hud[a:b].mean() <= 0.5:
            continue
        m = Match(start=float(r.t[a]), end=float(r.t[b - 1]))
        m.deaths = _deaths(r, a, b)
        # The ready icon also goes out when you DIE with the ult charged, and a
        # dead player's dimmed digits misread -- on the 90-minute test
        # recording two of four "ults" in one match were deaths. An ult inside
        # a death is not one.
        m.casts = [c for c in _casts(r, a, b)
                   if not any(d0 - 1.0 <= c <= d1 for d0, d1 in m.deaths)]
        m.phases = _phases(r, a, b)
        m.result, m.result_at = _result(r, b)
        out.append(m)
    return out


def _deaths(r: Readings, a: int, b: int) -> list[tuple[float, float]]:
    """Dead: the objective square gone for 5-30 s under a DIMMED HUD.

    The dim matters. The square also goes for 2-4 s under a banner or the
    hero-info page, with the HUD at full strength (0.9) -- and a dead player's
    HUD reads 0.4-0.5. All eight deaths in a hand-checked match, no others.
    """
    out = []
    for x, y in runs(~r.bullet[a:b]):
        dur = r.t[a + y - 1] - r.t[a + x]
        if DEATH_MIN <= dur <= DEATH_MAX and r.ult_ncc[a + x:a + y].mean() < 0.7:
            out.append((float(r.t[a + x]), float(r.t[a + y - 1])))
    return out


def _casts(r: Readings, a: int, b: int) -> list[float]:
    """An ult: the ready icon (yellow, 0.1-0.3 of the box) for a second or
    more, then a number under 40 within four seconds."""
    part = (r.ult_ncc > HUD_ULT_PART) | (r.hp_ncc > HUD_HP_PART)
    ready = (r.ready > 0.1) & (r.ready < 0.3) & part
    u = _smooth_ult(r.ult)
    out = []
    for x, y in runs(ready[a:b]):
        if (y - x) / FPS < 1:
            continue
        nxt = u[a + y:a + y + int(4 * FPS)]
        vals = nxt[nxt >= 0]
        if len(vals) and vals[0] < 40:
            out.append(float(r.t[min(a + y, len(r) - 1)]))
    return out


def _phases(r: Readings, a: int, b: int, hold: float = 5.0) -> list[float]:
    """When the objective line changes and the new text holds for `hold` s."""
    bits = np.unpackbits(r.line[a:b], axis=1).astype(bool)

    def sim(p, q):
        u = (p | q).sum()
        return (p & q).sum() / u if u else 1.0

    cur = cand = None
    count = 0
    out = []
    settle = r.t[a] + 20.0     # the line is still being drawn as a match opens
    for i in range(b - a):
        if r.t[a + i] < settle or not r.bullet[a + i] or bits[i].sum() < 30:
            continue
        x = bits[i]
        if cur is None:
            cur = x
            continue
        if sim(x, cur) > 0.5:
            cand, count = None, 0
            continue
        if cand is not None and sim(x, cand) > 0.5:
            count += 1
        else:
            cand, count = x, 1
        if count >= hold * FPS:
            cur, cand, count = cand, None, 0
            out.append(float(r.t[a + i]) - hold)
    return out


def _result(r: Readings, end: int, look: float = 60.0) -> tuple[str, float]:
    """VICTORY or DEFEAT: a big title top left, held, with no HUD.

    Measured: the title arrives 10-12 s after the last in-match frame and
    holds for 25 s or more; VICTORY has a yellow band behind it (0.19 of the
    corner) and DEFEAT none (0.00).
    """
    hud = (r.ult_ncc > HUD_FULL) | (r.hp_ncc > HUD_FULL)
    stop = end
    while stop < len(r) and r.t[stop] - r.t[end - 1] <= look:
        stop += 1
    title = (r.tall[end:stop] >= 24) & ~hud[end:stop]
    for x, y in runs(title):
        if (y - x) / FPS >= 3:
            yellow = float(np.median(r.tl_yellow[end + x:end + y]))
            return ("victory" if yellow >= 0.1 else "defeat"), float(r.t[end + x])
    return "", 0.0


# --------------------------------------------------------------- planning

LEAD = 3.0            # a fight opens this long before it is detected
DEATH_KEEP = 3.0      # of a death, this much stays: what killed you
INTRO = 4.0           # the first seconds of a match: the map and the hero
ENGAGE_HOLD = 4.0     # ignore the first seconds after a respawn: the HUD settles
# How far to look for the next fight. After a respawn the walk back is 10-25 s;
# at the start of a match the setup countdown comes first, and the first fight
# was 53 s in on a hand-checked one.
ENGAGE_HORIZON = 45.0
START_HORIZON = 120.0
CAST_GUARD = (6.0, 8.0)
RESULT_KEEP = 6.0
END_KEEP = 6.0
MIN_PIECE = 1.5


def engage(r: Readings, at: float, u: np.ndarray | None = None,
           horizon: float = ENGAGE_HORIZON) -> float | None:
    """The first sign of a fight after `at`, or None within the horizon."""
    if u is None:
        u = _smooth_ult(r.ult)
    i = int(np.searchsorted(r.t, at + ENGAGE_HOLD))
    stop = int(np.searchsorted(r.t, at + horizon))
    k = int(4 * FPS)
    while i < min(stop, len(r) - k):
        # The meter rises: only damage and healing move it more than ~1 in 4 s.
        if u[i] >= 0 and u[i + k] >= 0 and 2 <= u[i + k] - u[i] <= 25:
            return float(r.t[i])
        hp = r.hpfrac[i:i + 4]
        if (hp < 0.9).all() and (hp > 0.05).all():
            return float(r.t[i])
        if r.green[i] > 0.15 or r.red[i] > 0.15:
            return float(r.t[i])
        i += 1
    return None


def plan(r: Readings, m: Match) -> list[tuple[float, float]]:
    """The spans of the recording that make up this match's summary."""
    u = _smooth_ult(r.ult)
    cuts: list[tuple[float, float]] = []

    first = engage(r, m.start, u, START_HORIZON)
    if first is not None and first - LEAD > m.start + INTRO + 2:
        cuts.append((m.start + INTRO, first - LEAD))
    for d0, d1 in m.deaths:
        back = engage(r, d1, u)
        until = max(d1, back - LEAD) if back is not None else d1
        if until > d0 + DEATH_KEEP:
            cuts.append((d0 + DEATH_KEEP, until))

    # An ult is never cut into, whatever the rules above decided.
    guarded = []
    for a, b in cuts:
        pieces = [(a, b)]
        for c in m.casts:
            g0, g1 = c - CAST_GUARD[0], c + CAST_GUARD[1]
            nxt = []
            for p, q in pieces:
                if q <= g0 or p >= g1:
                    nxt.append((p, q))
                    continue
                if p < g0:
                    nxt.append((p, g0))
                if q > g1:
                    nxt.append((g1, q))
            pieces = nxt
        guarded += pieces

    keep: list[tuple[float, float]] = []
    pos = m.start
    for a, b in sorted(guarded):
        if a > pos:
            keep.append((pos, a))
        pos = max(pos, b)
    keep.append((pos, m.end + END_KEEP))
    if m.result:
        keep.append((m.result_at, m.result_at + RESULT_KEEP))

    merged: list[tuple[float, float]] = []
    for a, b in keep:
        if merged and a - merged[-1][1] < MIN_PIECE:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return [(round(a, 3), round(b, 3)) for a, b in merged if b - a >= MIN_PIECE]


def to_output(spans: list[tuple[float, float]], at: float) -> float | None:
    """Where recording time `at` lands in the summary.

    A moment that was cut lands where the summary picks up again -- a new
    objective announced during a walk back is still the start of that part of
    the match. None only past the end.
    """
    pos = 0.0
    for a, b in spans:
        if at < a:
            return pos
        if at <= b:
            return pos + at - a
        pos += b - a
    return None


def chapters(spans: list[tuple[float, float]], m: Match) -> list[tuple[float, str]]:
    """YouTube chapters: the match, each new objective, the result.

    YouTube needs the first at 0:00 and each at least ten seconds apart;
    anything that would break that is dropped rather than moved.
    """
    marks: list[tuple[float, str]] = [(0.0, "Match start")]
    for i, p in enumerate(m.phases, start=2):
        o = to_output(spans, p)
        if o is not None:
            marks.append((o, f"Objective {i}"))
    if m.result:
        o = to_output(spans, m.result_at)
        if o is not None:
            marks.append((o, m.result.capitalize()))
    out: list[tuple[float, str]] = []
    for t, name in sorted(marks):
        if not out or t - out[-1][0] >= 10:
            out.append((t, name))
    return out
