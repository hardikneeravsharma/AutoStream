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

    Per song at these settings: 61-90% of marks caught, 79% of all 662.

    THE BAND IS 30-150 Hz, NOT 0-150. Below 30 Hz is rumble, room and the
    file's own DC, and it drowned the kick in the songs that have little of
    one: dropping it took Ooo La La from 44% to 61% and Lalala from 84% to
    90%, at 143 hits a minute instead of 146. It cost two big hits in HIGHEST
    IN THE ROOM.

    Bass is not every song's pattern. Measured against the marks band by band,
    four of the seven songs are cut on the bass, two on the mids (Cradles 87%,
    Ooo La La 73%) and one on the hats (After Party 66%). Imagine Dragons'
    Believer, unmarked so far, repeats a one-bar hat figure 27 times clearer
    than anything in its bass. Choosing the band per song is the next step;
    this module is the bass one.

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
# ...and the floor of it. Below 30 Hz is rumble and room, not a kick: keeping
# it cost Ooo La La a third of its marks.
LOW_MIN_HZ = 30.0
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

# How far apart kills land, when nobody says otherwise. A style says
# otherwise: studio.plan passes 60 / the style's measured cuts-per-minute, so
# hype cuts every 1.1 s and story every 2.8 s on the same song.
TARGET_GAP = 1.0
# Hits closer together than this share of the gap are a "dense run" -- the
# player's "drums placed too close".
CLOSE_SHARE = 0.6
# A dense run this many gaps long is still cut kill-per-hit (quick cuts); a
# longer one is thinned and the hits between become accents.
QUICK_SHARE = 2.0
# The most hits a thinned run skips between kills. Every 2nd, 3rd or 4th was
# the player's rule, but a 160-hits-a-minute song at story's pace needs every
# 8th to keep kills 2.8 s apart, and a run of sixteenth notes twice that.
MAX_STEP = 16
# How far either side of where the next kill belongs to look for the loudest
# hit. Wider than this and the pace drifts; narrower and a strong hit just
# outside is missed.
WINDOW = (0.6, 1.5)

# ------------------------------------------------------------------ the bands
# Three bands, because the marks say kills are not always on the bass: of the
# eight songs marked, four are cut on the kick, two on the mids and one -- the
# hats of Believer -- on neither.
BANDS = {"bass": (LOW_MIN_HZ, LOW_HZ), "mid": (150.0, 2500.0), "hats": (5000.0, 16000.0)}
# A bar folded into this many steps: 32nd notes, fine enough for a swung or
# pushed accent.
STEPS = 32
# When a band's one-bar figure counts as the song's pattern: this much clearer
# than the bass's figure, and this clear in its own right. Measured over
# eleven songs, only Believer's hats pass -- 27x, against 6.4x for its own
# bass, whose hits land on 4% of the marks.
FIGURE_OVER_BASS = 3.0
FIGURE_CLEAR = 10.0
# A step of the figure quiet enough to be left out of it.
FIGURE_FLOOR = 0.25


def _band(x: np.ndarray, lo: float, hi: float) -> tuple[np.ndarray, float]:
    """Energy between `lo` and `hi` Hz per frame, in dB. -> (energy, frames/s)"""
    n = 1 + max(0, (len(x) - WIN) // HOP)
    if n < 8:
        return np.zeros(0), bs.SR / HOP
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    win = np.hanning(WIN).astype(np.float32)
    mag = np.abs(np.fft.rfft(x[idx] * win, axis=1))
    freqs = np.fft.rfftfreq(WIN, 1.0 / bs.SR)
    power = (mag[:, (freqs >= lo) & (freqs < hi)] ** 2).sum(axis=1)
    return 10.0 * np.log10(power + 1e-10), bs.SR / HOP


def _low_level(x: np.ndarray) -> tuple[np.ndarray, float]:
    """The kick/bass band. -> (energy, frames per second)"""
    return _band(x, LOW_MIN_HZ, LOW_HZ)


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


def bar_figure(x: np.ndarray, beat: float, lo: float, hi: float,
               ) -> tuple[float, float, np.ndarray]:
    """The one-bar figure a band repeats. -> (contrast, phase, the bar's steps)

    The band's energy is folded onto a single bar at STEPS steps, at the phase
    that makes the figure sharpest. `contrast` is the loudest step against the
    typical one: 27 for Believer's hats, which play a hit on every beat with
    the one on beat three two and a half times louder, and 6 for its bass,
    which has no figure at all.
    """
    energy, fps = _band(x, lo, hi)
    if energy.size < 8 or beat <= 0:
        return 0.0, 0.0, np.zeros(STEPS)
    # New energy arriving, not how loud the band is: a band that never goes
    # quiet folds flat. Believer's hats read 27 times their own typical step
    # this way and 4 times it from the raw level.
    lin = np.maximum(np.diff(energy, prepend=energy[0]), 0.0)
    seconds = len(lin) / fps
    bar = 4.0 * beat
    if seconds < 8 * bar:
        return 0.0, 0.0, np.zeros(STEPS)
    at = np.arange(len(lin)) / fps
    best = (0.0, 0.0, np.zeros(STEPS))
    for phase in np.arange(0.0, bar / STEPS, bar / STEPS / 12):
        v = np.interp(np.arange(phase, seconds - bar, bar / STEPS), at, lin)
        bars = len(v) // STEPS
        prof = v[:bars * STEPS].reshape(bars, STEPS).mean(axis=0)
        contrast = float(prof.max() / max(float(np.median(prof)), 1e-9))
        if contrast > best[0]:
            best = (contrast, float(phase), prof)
    return best


def figure_hits(x: np.ndarray, beat: float, seconds: float,
                ) -> tuple[list[float], list[float], str]:
    """A song whose pattern is a repeated bar, not a run of drum hits.

    Believer's kick is shapeless -- its hits sit on 4% of the marks -- but its
    hats play the same bar over and over, and the player marked beat three of
    every one of them. Where a band's figure is far clearer than the bass's,
    the hits are that figure laid down bar by bar: every step of it that is not
    quiet, each as strong as it is in the figure.

    -> (times, strengths, which band), or ([], [], "") when no band stands out.
    """
    if beat <= 0 or seconds < 16.0:
        return [], [], ""
    figures = {b: bar_figure(x, beat, lo, hi) for b, (lo, hi) in BANDS.items()}
    bass = figures["bass"][0]
    band = max(figures, key=lambda b: figures[b][0])
    contrast, phase, prof = figures[band]
    if band == "bass" or contrast < FIGURE_CLEAR or contrast < FIGURE_OVER_BASS * bass:
        return [], [], ""
    bar = 4.0 * beat
    top = float(prof.max()) or 1.0
    steps = [(i, float(prof[i]) / top) for i in range(STEPS) if prof[i] / top >= FIGURE_FLOOR]
    # The figure says WHERE in the bar; the band itself says exactly when. A
    # grid laid down for 106 bars drifts off a song that does not keep perfect
    # time, so each step lands on the real arrival nearest it.
    energy, fps = _band(x, *BANDS[band])
    rise = np.maximum(np.diff(energy, prepend=energy[0]), 0.0)
    slack = bar / STEPS / 2
    times: list[float] = []
    strengths: list[float] = []
    for n in range(int((seconds - phase) / bar)):
        for i, level in steps:
            t = phase + n * bar + i * bar / STEPS
            if t >= seconds:
                continue
            a = max(0, int((t - slack) * fps))
            b = min(len(rise), int((t + slack) * fps) + 1)
            if b > a:
                t = (a + int(np.argmax(rise[a:b]))) / fps
            times.append(round(float(t), 4))
            strengths.append(level)
    order = np.argsort(times)
    return [times[i] for i in order], [strengths[i] for i in order], band


def song_hits(x: np.ndarray, beat: float = 0.0, seconds: float = 0.0,
              ) -> tuple[list[float], list[float], str]:
    """Where this song's kills belong. -> (times, strengths, what was used)

    The bass hits, unless the song has no bass pattern and another band repeats
    a clear bar figure -- see figure_hits().
    """
    seconds = seconds or len(x) / bs.SR
    times, strengths, band = figure_hits(x, beat, seconds)
    if times:
        return times, strengths, f"{band} figure"
    times, strengths = bass_hits(x)
    return times, strengths, "bass hits"


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
        if rise < BIG_RISE or t < BIG_WINDOW:
            # A hit in the first two seconds has no "before" to rise out of --
            # the silence ahead of the file made Skechers' very first hit look
            # like its biggest arrival, and the planner opened on it.
            continue
        # One per arrival: the strongest rise in each BIG_APART seconds.
        if out and t - hits[out[-1]] < BIG_APART:
            if rise > rises[out[-1]]:
                out[-1] = i
            continue
        out.append(i)
    return [hits[i] for i in out], [rises[i] for i in out]


def _loudest_run(run: list[float], strength: list[float], gap: float,
                 ) -> tuple[list[float], list[float]]:
    """Walk a dense run, taking the loudest hit where the next kill belongs.

    Every Nth hit takes whatever sits on that count -- on Skechers that caught
    17% of the marks, on Lalala 16%. Taking the STRONGEST hit in the window
    instead catches 63% and 66%: an editor cuts on the hit that is loudest
    there, not on the one the count lands on.
    """
    kills = [run[int(np.argmax(strength[:max(1, sum(1 for t in run if t <= run[0] + gap))]))]]
    while True:
        last = kills[-1]
        inside = [i for i, t in enumerate(run) if last + WINDOW[0] * gap <= t <= last + WINDOW[1] * gap]
        if inside:
            kills.append(run[max(inside, key=lambda i: strength[i])])
            continue
        after = [t for t in run if t > last + WINDOW[1] * gap]
        if not after:
            break
        kills.append(after[0])
    chosen = set(kills)
    return kills, [t for t in run if t not in chosen]


def choose_kills(hits: list[float], strengths: list[float] | None = None, *,
                 target_gap: float = TARGET_GAP,
                 close: float = 0.0, quick_run: float = 0.0,
                 min_shot: float = 0.25) -> tuple[list[float], list[float]]:
    """Which hits carry a kill, and which are only accents. -> (kills, accents)

    `target_gap` is how far apart this reel's kills belong -- the style's own
    pace. Everything else follows from it, so one song gives a hype reel a kill
    every 1.1 s and a story reel one every 2.8 s, both on the same kicks.

    The player's rule for drums placed too close together:

      * a SHORT run of close hits is cut kill-per-hit -- quick cuts, one kill
        each -- as long as each shot still clears `min_shot`;
      * a LONG dense run takes every Nth hit, N chosen so kills land about
        `target_gap` apart, and the hits in between become accents: effects
        without a kill.
    """
    close = close or target_gap * CLOSE_SHARE
    quick_run = quick_run or target_gap * QUICK_SHARE
    order = sorted(range(len(hits or [])), key=lambda i: hits[i])
    strong = [float(strengths[i]) for i in order] if strengths and len(strengths) == len(hits) else []
    hits = [hits[i] for i in order]
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
        if strong:
            took, left = _loudest_run(run, strong[i - len(run):i], target_gap)
            kills.extend(took)
            accents.extend(left)
            continue
        step = int(round(target_gap / max(1e-6, float(np.median(gaps)))))
        step = max(2, min(MAX_STEP, step))
        for k, t in enumerate(run):
            (kills if k % step == 0 else accents).append(t)
    kills.sort()
    # A kill too close to the one before it cannot be its own shot.
    kept: list[float] = []
    for t in kills:
        if kept and t - kept[-1] < min_shot:
            accents.append(t)
            continue
        kept.append(t)
    return kept, sorted(accents)
