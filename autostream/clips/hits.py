"""Where a song hits: the moments a kill belongs on.

WHY THIS EXISTS
    Reels used to put kills on the beat finder's grid -- one tempo and phase
    for the whole song. On the player's own songs that grid is wrong (MONTERO
    reads as 71.9 BPM, its lines falling between the kicks), and even when it
    is right a grid says every beat is equal, which is not how an editor cuts.

    So the player marked 662 kills across 7 songs by ear, in Kill Marks
    (scripts/kill_marks/). Measured against those marks:

        the kick/bass band at a mark    97th percentile of the song (random: 60th)
        the whole spectrum's brightness 97th percentile           (random: 67th)
        within 60 ms of a kick peak     70% of marks              (random: 17%)
        mark minus that peak            median +2 ms (p10 -89, p90 +96)

    So: kills go on the bass hits, and this module finds them.

WHAT A HIT IS: A PEAK IN THE BASS, NOT A RISE IN IT
    The first version looked for rising energy under 150 Hz, the usual way to
    find an onset. Scored against the marks it caught 83% of them but fired
    8025 times across the 7 songs -- five or six times per kick -- and
    tightening it collapsed to 58%. Peaks of the bass LEVEL do far better at
    the same density: 73% of the marks at 146 hits a minute, which is the
    ceiling the measurement above implies (only 70% of the marks are within
    60 ms of any bass peak at all). Timing lands within 30 ms on every song.

    Per song at these settings: 61-84% of marks caught, except Ooo La La at
    44% -- the song whose marks are NOT on the bass (10% of them sit on a bass
    peak, no better than chance). That is the second pattern, still to be
    found; nothing here pretends to cover it.

JUDGED AGAINST ITS OWN PART OF THE SONG
    The player's words: "in a song each part has different high". A verse's
    kicks are quieter than the chorus's, so a peak is measured against the six
    seconds around it -- between the quiet floor and the loud ceiling there --
    not against the whole song.

BIG HITS
    Where the song comes back in after a quiet stretch; the player marked
    those as the biggest kills. Measured on their 38 big marks: the loudness
    of the 2 s after, minus the 2 s before, jumps 0.12 of the song's loudness
    at a big mark against 0.005 at an ordinary one. Taking hits over 0.04 and
    keeping the strongest in each 4 s catches 71% of the big marks.

No files and no ffmpeg here: this reads the samples beatsync already decoded.
"""
from __future__ import annotations

import numpy as np

from . import beatsync as bs

# The band a kick lives in -- and what the marks were measured against.
LOW_HZ = 150.0
# 5.8 ms a frame: fine enough to place a kick well inside the 60 ms the marks
# are scored at, and cheap (a 4-minute song is 41k frames).
HOP = 128
WIN = 1024

# The stretch a hit is judged against. Six seconds is a bar or two: long
# enough to know the quiet floor of this part of the song, short enough that a
# verse is not measured against a chorus.
LOCAL_SECONDS = 6.0
# How high in that stretch's range the bass has to be. 0 is the quiet floor
# (10th percentile), 1 the loud ceiling (95th). Swept against the marks:
# 0.75 -> 73% at 155 hits/min, 0.8 -> 73% at 146, 0.9 -> 71% at 121.
LEVEL = 0.8
# Two peaks closer than this are one hit. Swept: 0.12 s -> 76% at 167/min,
# 0.14 -> 73% at 146, 0.16 -> 71% at 134.
MIN_GAP = 0.14

# A big hit: how much louder the next BIG_WINDOW seconds are than the last,
# as a share of the song's own loudness, and how far apart big hits must be.
BIG_WINDOW = 2.0
BIG_RISE = 0.04
BIG_APART = 4.0

# Hits closer together than this are a "dense run" -- the player's "drums
# placed too close".
CLOSE = 0.5
# A dense run this short is cut kill-per-hit (quick cuts); a longer one is
# thinned to TARGET_GAP and the rest become accents. Two seconds is about a
# bar at 120 BPM.
QUICK_RUN = 2.0
# The player's rule for a long dense run: "keep kills about a second apart".
TARGET_GAP = 1.0


def _low_level(x: np.ndarray) -> tuple[np.ndarray, float]:
    """Energy under LOW_HZ per frame, in dB. -> (energy, frames per second)"""
    n = 1 + max(0, (len(x) - WIN) // HOP)
    if n < 8:
        return np.zeros(0), bs.SR / HOP
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    win = np.hanning(WIN).astype(np.float32)
    mag = np.abs(np.fft.rfft(x[idx] * win, axis=1))
    freqs = np.fft.rfftfreq(WIN, 1.0 / bs.SR)
    power = (mag[:, freqs < LOW_HZ] ** 2).sum(axis=1)
    return 10.0 * np.log10(power + 1e-10), bs.SR / HOP


def _rolling(v: np.ndarray, frames: int, q: float) -> np.ndarray:
    """The qth percentile of `v` around each frame.

    Taken on a coarse grid and interpolated back: an exact percentile per frame
    costs a sort per frame and says nothing more about a six-second window.
    """
    step = max(1, frames // 8)
    mids = np.arange(0, len(v), step)
    out = np.empty(len(mids))
    for i, m in enumerate(mids):
        seg = v[max(0, m - frames // 2): m + frames // 2]
        out[i] = float(np.percentile(seg, q)) if seg.size else 0.0
    return np.interp(np.arange(len(v), dtype=float), mids.astype(float), out)


def bass_hits(x: np.ndarray) -> tuple[list[float], list[float]]:
    """Every bass hit in the song. -> (times, strengths)

    `strength` is where the hit sits in its own stretch of the song, 0 at the
    quiet floor and 1 at the loud ceiling, so a verse hit and a chorus hit can
    be compared.
    """
    energy, fps = _low_level(x)
    if energy.size < 8:
        return [], []
    frames = int(LOCAL_SECONDS * fps)
    floor = _rolling(energy, frames, 10)
    ceiling = _rolling(energy, frames, 95)
    level = (energy - floor) / np.maximum(ceiling - floor, 1e-3)

    gap = max(1, int(MIN_GAP * fps))
    rising = (level[1:-1] >= level[:-2]) & (level[1:-1] > level[2:])
    peaks: list[int] = []
    for i in np.where(rising)[0] + 1:
        if level[i] < LEVEL:
            continue
        # Two peaks inside MIN_GAP are one drum: keep the higher.
        if peaks and i - peaks[-1] < gap:
            if level[i] > level[peaks[-1]]:
                peaks[-1] = int(i)
            continue
        peaks.append(int(i))
    return [p / fps for p in peaks], [float(level[p]) for p in peaks]


def big_hits(x: np.ndarray, hits: list[float]) -> tuple[list[float], list[float]]:
    """The hits where the song comes back in after a quiet stretch. -> (times, rises)"""
    if not hits:
        return [], []
    loud = np.abs(x).astype(np.float64)
    csum = np.concatenate([[0.0], np.cumsum(loud)])
    span = float(np.percentile(loud, 99)) or 1.0

    def mean_loud(a: float, b: float) -> float:
        ia = max(0, int(a * bs.SR))
        ib = min(len(loud), int(b * bs.SR))
        return float((csum[ib] - csum[ia]) / max(1, ib - ia)) if ib > ia else 0.0

    rises = [(mean_loud(t, t + BIG_WINDOW) - mean_loud(t - BIG_WINDOW, t)) / span for t in hits]
    out: list[int] = []
    for i, (t, rise) in enumerate(zip(hits, rises)):
        if rise < BIG_RISE:
            continue
        # One per arrival: the strongest rise in each BIG_APART seconds.
        if out and t - hits[out[-1]] < BIG_APART:
            if rise > rises[out[-1]]:
                out[-1] = i
            continue
        out.append(i)
    return [hits[i] for i in out], [rises[i] for i in out]


def choose_kills(hits: list[float], *, target_gap: float = TARGET_GAP,
                 close: float = CLOSE, quick_run: float = QUICK_RUN,
                 min_shot: float = 0.25) -> tuple[list[float], list[float]]:
    """Which hits carry a kill, and which are only accents. -> (kills, accents)

    The player's rule for drums placed too close together:

      * a SHORT run of close hits is cut kill-per-hit -- quick cuts, one kill
        each -- as long as each shot still clears `min_shot`;
      * a LONG dense run takes every Nth hit, N chosen so kills land about
        `target_gap` apart, and the hits in between become accents: effects
        without a kill.
    """
    hits = sorted(hits or [])
    if not hits:
        return [], []
    kills: list[float] = []
    accents: list[float] = []
    i = 0
    while i < len(hits):
        j = i
        while j + 1 < len(hits) and hits[j + 1] - hits[j] <= close:
            j += 1
        run = hits[i:j + 1]
        i = j + 1
        if len(run) == 1:
            kills.append(run[0])
            continue
        gaps = np.diff(run)
        if run[-1] - run[0] <= quick_run and float(gaps.min()) >= min_shot:
            kills.extend(run)                     # short enough to cut one kill each
            continue
        step = int(round(target_gap / max(1e-6, float(np.median(gaps)))))
        step = max(2, min(4, step))
        for k, t in enumerate(run):
            (kills if k % step == 0 else accents).append(t)
    # A kill too close to the one before it cannot be its own shot.
    kept: list[float] = []
    for t in kills:
        if kept and t - kept[-1] < min_shot:
            accents.append(t)
            continue
        kept.append(t)
    return kept, sorted(accents)
