"""Counter-Strike 2 kills, read from the card tally under the crosshair.

WHAT THIS READS
    CS2 draws your kills for the CURRENT ROUND as a fan of playing cards just
    above the rank emblem at the bottom of the screen -- one card per kill, with
    the count printed on the front card. It is absent at zero kills and resets
    every round.

WHY IT BEATS READING THE KILL FEED
    The feed needs OCR, fuzzy name matching against your in-game name, and slot
    logic to tell a kill from an assist -- and CS2's profile notes still
    apologise for counting an unreadable assist as a kill. The card tally has
    none of those problems:

      * it is YOUR kills and nothing else, so assists cannot leak in
      * it needs no name, so there is nothing to configure
      * it needs no OCR, so Tesseract is not required at all
      * it persists for the whole round, so a missed frame costs TIMING but
        never the COUNT -- unlike a feed row, which is gone in five seconds

    And the region is tiny -- 130x62 px against the feed band's 768x292 -- so
    the scan is decode-bound rather than OCR-bound.

TWO SIGNALS, WHICH IS THE POINT
    Each kill also makes the card FLASH: the tally briefly scales up and
    brightens, measured at 250 -> 1748 mask pixels for about 0.9s before
    settling. So the flash says WHEN a kill happened and the settled width says
    HOW MANY have happened, and the two check each other. If the count jumps by
    two with only one flash, a flash was missed and the count still knows.

MEASURED, on 1920x1080 footage, steady (non-flash) frames:

        1 card   width 34 px      3 cards  width 66 px
        2 cards  width 50 px      -> width = 18 + 16 x kills, exactly

    Every sample of a given count measured the identical width. Width during a
    FLASH does not obey this at all -- a single kill measured 76px mid-flash,
    wider than a genuine three -- which is why flash frames are discarded
    rather than interpreted.

THE HUD COLOUR IS A USER SETTING
    It cannot be hard-coded: this player's is magenta, and the shipped default
    is not. It is measured instead -- see `hud_hue` -- from the fact that HUD
    elements hold still while the scenery behind them does not.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger("autostream.clips.cs2_cards")

REF_HEIGHT = 1080

# --------------------------------------------------------------------- where
# The card fan, just above the rank emblem. Kept clear of the emblem below,
# which is gold rather than the HUD colour and would otherwise be counted.
CARDS = (0.470, 0.878, 0.538, 0.936)
# A patch inside the spectator panel, left of the portrait and clear of the
# emblem. See `spectating`.
PANEL = (0.395, 0.938, 0.455, 0.972)
# Where the HUD colour is measured from: the whole bottom strip, which is full
# of HUD elements whatever the player has bound.
HUD_STRIP = (0.0, 0.86, 1.0, 1.0)

# --------------------------------------------------------------------- colour
# A HUE DISTANCE, not a projection onto the hue's direction. The projection was
# tried first and cannot do this job: Anubis's orange sandstone scores 35-44 on
# a magenta axis against a real card's 46-68, so bright desert read as a tally
# and one scan reported four kills in a single frame. Hue distance separates
# them -- magenta and sandstone are 50 degrees apart -- as long as the
# saturation floor stays LOW, because the cards are translucent and their
# colour is genuinely part background.
#
# Swept against nine frames of known count and ten more checked by eye:
# tol 25-35 with sat 0.18 and val 0.30 got all nineteen right.
HUE_TOL = 30.0
SAT_MIN = 0.18
VAL_MIN = 0.30
MASK_MIN = 60         # px before the tally counts as present at all

# ------------------------------------------------------------------- geometry
CARD_W0 = 18          # px at REF_HEIGHT
CARD_PITCH = 16
WIDTH_TOL = 3         # a width must land this close to a real level. Measured
                      # variance at a given count was ZERO, so this only has to
                      # absorb antialiasing -- everything else is a flash.
MAX_KILLS = 5
# Columns are counted only where at least this many pixels are masked. Without
# it the width is not stable against the measured hue: the same one-card tally
# came out 34px at hue 338 and 48px at 348, because the redder end of the
# tolerance starts admitting Anubis's orange sandstone. Requiring five stacked
# pixels ignores that speckle, and the widths then measured 34 / 50 / 66 for
# one, two and three cards at EVERY hue from 333 to 348.
MIN_COL = 5

# Mean horizontal gradient inside the spectator panel. The panel carries the
# spectated player's NAME and ADR, so it is full of vertical text edges;
# gameplay in the same spot is smooth. Measured: spectating 7.8-15.3, alive
# 0.9-3.3, so this sits in a gap more than twice as wide as either side.
SPECTATE_DX = 5.5

SAMPLE_FPS = 2.0
# The tally holds for the rest of the round, so two samples a second cannot
# lose a count. It can lose the exact instant, which `refine` recovers.
MAX_GAP = 3.0
CONFIRM_WINDOW = 2.5  # s. How long a count has, to say itself twice.
# Readings the spectator panel must hold for before a death is believed. Being
# dead lasts until the round ends, so a real one is never brief -- but the
# panel test does flicker, and undebounced it reported 73 deaths in a match
# with about 25 rounds in it.
SPECTATE_HOLD = 4

# Decode only keyframes during the sweep. See _pipe_two: eight times faster --
# 1.2s against 9.7s for a 120s span -- at the cost of seeing the tally every
# few seconds rather than twice a second.
#
# OFF UNTIL IT IS SCORED. The speed is measured; the ACCURACY is not, and this
# reader now has a baseline to be judged against (precision 70%, recall 79%
# over a 30-minute match against Valve's own demo). Turning on an
# accuracy-affecting default without scoring it is the exact mistake that
# nearly shipped a Valorant threshold tuned on a single match. Flip this to
# True only with the numbers beside it.
KEYFRAME_SCAN = False


def _hsv(a: np.ndarray):
    """-> (hue in degrees, saturation, value), all 0-1 except hue."""
    x = a.astype(np.float32) / 255.0
    mx, mn = x.max(axis=2), x.min(axis=2)
    d = np.where(mx - mn == 0, 1, mx - mn)
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    h = np.where(mx == r, ((g - b) / d) % 6,
                 np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60.0
    return h, mx - mn, mx


def hud_mask(a: np.ndarray, hue: float) -> np.ndarray:
    """Pixels drawn in the player's HUD colour."""
    h, s, v = _hsv(a)
    dh = np.abs((h - hue + 180.0) % 360.0 - 180.0)
    return (dh <= HUE_TOL) & (s >= SAT_MIN) & (v >= VAL_MIN)


def hud_hue(frames: list[np.ndarray]) -> float | None:
    """The player's HUD colour, measured rather than asked for.

    What separates HUD from gameplay is not the hue but the STILLNESS: HUD
    elements are drawn at the same pixels in the same colour every frame, while
    the scenery behind them moves constantly. So keep the pixels that are
    consistently saturated AND consistently the same hue, and report their
    colour.

    Needs several frames from well apart in the recording; returns None if it
    cannot find enough steady pixels to be sure, so the caller can fall back
    rather than scan with a wrong colour.
    """
    if len(frames) < 4:
        return None
    a = np.stack([f.astype(np.float32) / 255.0 for f in frames])
    mx, mn = a.max(axis=3), a.min(axis=3)
    sat, val = mx - mn, mx
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    d = np.where(mx - mn == 0, 1, mx - mn)
    h = np.where(mx == r, ((g - b) / d) % 6,
                 np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60.0
    bright = (sat >= 0.25) & (val >= 0.45)
    rad = np.deg2rad(h)
    seen = np.maximum(1, bright.sum(axis=0))
    cx = np.where(bright, np.cos(rad), 0).sum(axis=0) / seen
    cy = np.where(bright, np.sin(rad), 0).sum(axis=0) / seen
    # bright in most frames, and agreeing with itself on the hue
    steady = (bright.mean(axis=0) >= 0.5) & (np.hypot(cx, cy) >= 0.9)
    if int(steady.sum()) < 200:
        return None
    return float(np.rad2deg(np.arctan2(cy[steady].sum(),
                                       cx[steady].sum())) % 360)


def spectating(panel: np.ndarray) -> bool:
    """Is this the player's own tally, or somebody else's?

    While dead you watch a team-mate, and the tally then shows THEIR kills --
    so counting it would invent kills the player never got. The give-away is
    the spectator panel: it carries the watched player's name and ADR, so the
    patch is full of vertical text edges where gameplay is smooth.
    """
    if panel.size == 0:
        return False
    g = panel.astype(np.float32).mean(axis=2)
    return float(np.abs(np.diff(g, axis=1)).mean()) >= SPECTATE_DX


@dataclass
class Reading:
    """One frame's view of the tally."""
    time: float
    kills: int | None   # None = could not be trusted (flash, or spectating)
    width: int = 0
    mask: int = 0
    why: str = ""       # "" | "flash" | "spectating"


def read_frame(cards: np.ndarray, panel: np.ndarray | None, hue: float,
               at: float = 0.0, frame_height: int = REF_HEIGHT) -> Reading:
    """Read the tally from one frame's crops."""
    if panel is not None and spectating(panel):
        return Reading(time=at, kills=None, why="spectating")

    k = frame_height / REF_HEIGHT
    m = hud_mask(cards, hue)
    n = int(m.sum())
    if n < MASK_MIN * k * k:
        return Reading(time=at, kills=0, mask=n)

    cols = np.nonzero(m.sum(axis=0) >= max(2, int(MIN_COL * k)))[0]
    if not len(cols):
        return Reading(time=at, kills=0, mask=n)
    w = int(cols.max() - cols.min() + 1)
    # width -> count, but ONLY if the width is actually one of the real levels.
    # Mid-flash the card scales up and lands between them -- a single kill
    # measured 76px, which would otherwise read as four.
    exact = (w - CARD_W0 * k) / (CARD_PITCH * k)
    kills = int(round(exact))
    if not (1 <= kills <= MAX_KILLS):
        return Reading(time=at, kills=None, width=w, mask=n, why="flash")
    if abs(exact - kills) * CARD_PITCH * k > WIDTH_TOL * k:
        return Reading(time=at, kills=None, width=w, mask=n, why="flash")
    return Reading(time=at, kills=kills, width=w, mask=n)


@dataclass
class Event:
    time: float
    kind: str = "kill"
    end: float = 0.0
    running: int = 0      # the tally after this kill, for diagnostics
    ratio: float = 1.0    # so this can stand in for a killfeed FeedEvent

    def __post_init__(self) -> None:
        if not self.end:
            self.end = self.time


def collapse(readings: list[Reading], max_gap: float = MAX_GAP) -> list[Event]:
    """Readings -> kill events, one per increase in the tally.

    The rules come from what the tally can and cannot do:

      * it only ever RISES within a round, so a rise is kills and the size of
        the rise is how many
      * it resets to nothing between rounds, so a fall is a round boundary and
        never a kill
      * after any break in continuity -- a spectated team-mate, a flash, the
        scoreboard covering the HUD -- the new value is ADOPTED rather than
        counted. Emitting on that would invent kills every time the HUD was
        hidden mid-round, which is the one mistake worth being paranoid about.
    """
    rs = [r for r in sorted(readings, key=lambda x: x.time) if r.kills is not None]

    # A count has to PERSIST before it is believed. The tally flashes as a kill
    # lands -- scaling up for about 0.9s -- and mid-flash it can land on a width
    # that reads as a perfectly valid but wrong count: a two-kill tally measured
    # 66px, exactly a real three, for a single frame. A real count holds for the
    # rest of the round, so requiring it twice inside a couple of seconds costs
    # nothing and discards every flash.
    ok: list[Reading] = []
    for i, r in enumerate(rs):
        if r.kills == 0:
            ok.append(r)
            continue
        for other in rs[i + 1:]:
            if other.time - r.time > CONFIRM_WINDOW:
                break
            if other.kills == r.kills:
                ok.append(r)
                break

    # Deaths come free with the spectator test. You watch a team-mate only
    # because you are dead, so the moment the panel appears is the moment you
    # died -- and the round layer needs deaths for LAST ALIVE, SURVIVED and
    # clutch detection. Only the FIRST frame of each spectating run counts;
    # the rest is the same death still being dead.
    out: list[Event] = []
    watching = False
    run: list[Reading] = []
    ordered = sorted(readings, key=lambda x: x.time)
    for r in ordered:
        if r.why == "spectating":
            run.append(r)
            # DEBOUNCED. The panel test flickers frame to frame -- an
            # undebounced version reported 73 deaths across 25 rounds, which is
            # not a thing that can happen. Being dead lasts the rest of the
            # round, so a real one is never brief.
            if not watching and len(run) >= SPECTATE_HOLD:
                out.append(Event(time=run[0].time, kind="death"))
                watching = True
        else:
            if watching and len(run) == 0:
                pass
            run = []
            watching = False

    cur: int | None = None
    last_t = None
    for r in ok:
        gap = last_t is None or (r.time - last_t) > max_gap
        if cur is not None and not gap and r.kills > cur:
            for i in range(cur + 1, r.kills + 1):
                out.append(Event(time=r.time, running=i))
        # After a break -- a spectated team-mate, the scoreboard covering the
        # HUD, a new round -- the value is ADOPTED, never counted. Emitting
        # there would invent a kill every time the HUD was hidden mid-round.
        cur, last_t = r.kills, r.time
    out.sort(key=lambda e: e.time)
    return out


def tally(events: list[Event]) -> dict[str, int]:
    got = {"kill": 0, "death": 0}
    for e in events:
        got[e.kind] = got.get(e.kind, 0) + 1
    return got


# ------------------------------------------------------------------ scanning

def _pipe_two(video: Path, start: float, duration: float, fps: float,
              a: tuple, b: tuple, size: tuple[int, int],
              keyframes: bool = False):
    """The two crops as raw arrays, straight off ffmpeg's stdout.

    NO FILES. This used to write a PNG per crop per sampled frame and read
    them back with PIL -- for a 45-minute recording at 2 fps that is about
    eleven thousand files encoded, written, read and deleted, to carry regions
    of 130x62 and 115x37 pixels. The encode was costing more than the decode it
    was there to serve.

    The two crops are padded to a common width and stacked into one frame so a
    single output stream carries both; the exact rows and columns are known
    here, so numpy slices them back apart with nothing resampled. Card widths
    are measured in pixels against calibrated levels, so nothing may scale.

    -> yields (cards, panel) RGB arrays in order.
    """
    import subprocess

    from .killfeed import _NO_WINDOW
    from .tools import binary, has_cuda

    w, h = size

    def box(band):
        x1, y1, x2, y2 = band
        return (max(1, int(w * (x2 - x1))), max(1, int(h * (y2 - y1))),
                int(w * x1), int(h * y1))

    aw, ah, ax, ay = box(a)
    bw, bh, bx, by = box(b)
    pad = max(aw, bw)
    row = pad * 3
    frame_bytes = row * (ah + bh)

    proc = subprocess.Popen([
        binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
        *(["-hwaccel", "cuda"] if has_cuda() else []),
        # DECODE ONLY KEYFRAMES, AND LET THE fps FILTER FILL IN. Decoding is
        # the whole cost of this scan -- raw decode of a 120s span takes 9.7s
        # against the scan's 8.2s -- and only about one frame in 200 is
        # actually sampled. Skipping to keyframes decodes 35 frames instead of
        # 7200 for that span: 1.2s against 9.7s, eight times faster.
        #
        # The fps filter then duplicates each keyframe forward, so the output
        # is still evenly spaced and every constant downstream -- MAX_GAP,
        # CONFIRM_WINDOW, SPECTATE_HOLD -- keeps the meaning it was measured
        # with. What is genuinely lost is temporal resolution: the tally is
        # seen every ~3.4s rather than every 0.5s. That costs nothing on the
        # COUNT, which is what this reader is for and which holds for the whole
        # round, and `refine` re-scans each kill at 8 fps for the timing.
        *(["-skip_frame", "nokey"] if keyframes else []),
        "-ss", f"{start:.3f}",
        # -t BEFORE -i, as an input option: after it, it binds to the output.
        "-t", f"{max(0.5, duration):.3f}",
        "-i", str(video), "-an", "-sn",
        "-filter_complex",
        f"[0:v]fps={fps},split=2[p][q];"
        f"[p]crop={aw}:{ah}:{ax}:{ay},pad={pad}:{ah}:0:0[at];"
        f"[q]crop={bw}:{bh}:{bx}:{by},pad={pad}:{bh}:0:0[bt];"
        f"[at][bt]vstack=inputs=2[out]",
        "-map", "[out]", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=_NO_WINDOW)
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            f = np.frombuffer(buf, np.uint8).reshape(ah + bh, pad, 3)
            yield f[:ah, :aw], f[ah:, :bw]
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
        proc.wait(timeout=10)


def _extract_two(video: Path, start: float, duration: float, fps: float,
                 a: tuple, b: tuple) -> Path:
    """One decode, two crops -- the card tally and the spectator panel.

    Separately they would decode the recording twice, and decoding is the whole
    cost here: the two crops together are under 1% of the frame.

    Kept for the calibration screens, which want real PNGs to show a person.
    The scan itself pipes raw frames instead -- see `_pipe_two`.
    """
    import subprocess
    import tempfile

    from .killfeed import _NO_WINDOW
    from .tools import binary, has_cuda

    def crop(band):
        x1, y1, x2, y2 = band
        return (f"crop=iw*{x2 - x1:.6f}:ih*{y2 - y1:.6f}"
                f":iw*{x1:.6f}:ih*{y1:.6f}")

    tmp = Path(tempfile.mkdtemp(prefix="cs2c_"))
    subprocess.run([
        binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
        *(["-hwaccel", "cuda"] if has_cuda() else []),
        "-ss", f"{start:.3f}",
        # -t BEFORE -i. After it, it is an output option and binds only to the
        # FIRST output, leaving the second to decode to end of file.
        "-t", f"{max(0.5, duration):.3f}",
        "-i", str(video), "-an", "-sn",
        "-filter_complex",
        f"[0:v]fps={fps},split=2[p][q];"
        f"[p]{crop(a)}[aout];[q]{crop(b)}[bout]",
        "-map", "[aout]", str(tmp / "c_%05d.png"),
        "-map", "[bout]", str(tmp / "p_%05d.png"),
    ], capture_output=True, check=False, creationflags=_NO_WINDOW)
    return tmp


def measure_hue(video: Path, duration: float, samples: int = 12,
                start: float = 0.0) -> float | None:
    """Sample frames spread across the recording and measure the HUD colour.

    `start` keeps the samples inside the part being scanned. On a file holding
    two games, frames from the other one carry a different HUD -- or none --
    and measuring the colour off those is measuring the wrong game.
    """
    from PIL import Image

    from .killfeed import _extract

    step = max(30.0, duration / (samples + 1))
    frames = []
    for i in range(1, samples + 1):
        at = start + min(duration - 1.0, step * i)
        tmp = _extract(video, HUD_STRIP, at, 0.5, 1.0)
        try:
            got = sorted(tmp.glob("f_*.png"))
            if got:
                frames.append(np.asarray(Image.open(got[0]).convert("RGB")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return hud_hue(frames)


def _span(video: Path, start: float, dur: float, fps: float, hue: float,
          frame_height: int, size: tuple[int, int] | None = None,
          keyframes: bool = False,
          band: tuple = CARDS) -> list[Reading]:
    if size is None:
        from .tools import media_info

        info = media_info(video)
        size = (int(info["width"]), int(info["height"]))
    out: list[Reading] = []
    for i, (c, p) in enumerate(
            _pipe_two(video, start, dur, fps, band, PANEL, size, keyframes)):
        out.append(read_frame(c, p, hue, start + i / fps, frame_height))
    return out


# A kill makes the tally FLASH -- it scales up and brightens for about 0.9s,
# measured 250 -> 1748 mask pixels. Sampling at 2 fps finds the kill to within
# half a second; re-scanning that half second at 8 fps finds the flash itself,
# which is the kill. Only kills are refined, because only kills decide where a
# clip starts.
REFINE_FPS = 8.0
REFINE_BACK = 1.5


def refine(video: Path, events: list[Event], hue: float, *,
           fps: float = REFINE_FPS, look_back: float = REFINE_BACK,
           frame_height: int = REF_HEIGHT,
           cancelled: Callable[[], bool] | None = None) -> list[Event]:
    """Move each kill back to the frame its flash began on."""
    from PIL import Image

    from .killfeed import _extract

    for e in events:
        if e.kind != "kill":
            continue
        if cancelled and cancelled():
            break
        start = max(0.0, e.time - look_back)
        tmp = _extract(video, CARDS, start, e.time - start + 0.2, fps)
        try:
            best = None
            base = None
            for png in sorted(tmp.glob("c_*.png")) or sorted(tmp.glob("f_*.png")):
                at = start + (int(png.stem.split("_")[1]) - 1) / fps
                n = int(hud_mask(np.asarray(Image.open(png).convert("RGB")),
                                 hue).sum())
                if base is None:
                    base = n
                # the flash is several times the settled size, so it needs no
                # threshold of its own -- it is simply far above what came before
                if n >= max(300, base * 2.5) and best is None:
                    best = at
                base = min(base, n) if base else n
            if best is not None and best < e.time:
                e.end = max(e.end, e.time)
                e.time = best
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    events.sort(key=lambda x: x.time)
    return events


def scan(video: Path, *, duration: float | None = None, start: float = 0.0,
         fps: float = SAMPLE_FPS, chunk: float = 120.0,
         hue: float | None = None, frame_height: int = REF_HEIGHT,
         band: tuple | None = None,
         keyframes: bool = KEYFRAME_SCAN,
         progress: Callable[[int, int], None] | None = None,
         cancelled: Callable[[], bool] | None = None) -> list[Event]:
    """Read the whole recording's kill tally. -> events in time order."""
    from .killfeed import _sweep_stale_temp
    from .tools import media_info

    video = Path(video)
    total = duration if duration is not None else media_info(video)["duration"]
    _sweep_stale_temp()
    if hue is None:
        hue = measure_hue(video, total, start=start)
        if hue is None:
            raise RuntimeError(
                "Could not work out your CS2 HUD colour from this recording. "
                "Set it by hand on the Clips page, or pick a recording with "
                "more gameplay in it.")
        log.info("measured CS2 HUD colour: hue %.0f", hue)

    # `start` shifts the window; every event still carries its position in
    # the recording, so nothing downstream has to know a window was used.
    end = start + total
    spans, t = [], float(start)
    while t < end:
        spans.append((t, min(chunk, end - t)))
        t += chunk
    seen: list[Reading] = []
    if progress:
        progress(0, len(spans))
    # Once, not once per chunk: the crop geometry is fixed for the file, and
    # media_info is a subprocess.
    info = media_info(video)
    size = (int(info["width"]), int(info["height"]))
    for i, (at, dur) in enumerate(spans, 1):
        if cancelled and cancelled():
            break
        seen.extend(_span(video, at, dur, fps, hue, frame_height,
                          size, keyframes, band or CARDS))
        if progress:
            progress(i, len(spans))

    events = collapse(seen)
    if not (cancelled and cancelled()):
        refine(video, events, hue, frame_height=frame_height,
               cancelled=cancelled)
    t = tally(events)
    log.info("%s: %d kill(s) and %d death(s) from the card tally (%d frames)",
             video.name, t["kill"], t["death"], len(seen))
    return events


# ===================================================================
# Calibration: proving the reader works on THIS person's footage
# ===================================================================
#
# WHY THIS EXISTS. The card region is a fraction of the frame, measured on one
# person's 16:9 1080p HUD. A different aspect ratio -- 4:3 stretched is normal
# in Counter-Strike -- or a different hud_scaling puts the tally somewhere the
# crop does not look, and the scan then reports almost nothing. It did exactly
# that for a real user: 2 kills out of 17, and the two were wrong.
#
# Nothing in the run said so. A scan that finds nothing looks identical to a
# quiet session, so the first sign was clips that were not there. These two
# functions make it visible BEFORE the scan: one finds frames likely to hold a
# tally so a person can see what the reader sees, and the other says whether
# the reader can actually read them.

SAMPLE_TRIES = 40         # single-frame seeks across the recording
# MEASURED, not chosen. On a 30-minute match with the region and hue correct,
# 24 seeks found HUD colour in 8 frames and read a real tally from 3 of them --
# most seeks land between rounds, or on a round with no kills yet. The same 24
# seeks against a wrong hue, a region shifted 12% left, and a region moved up
# into the HUD bar read a tally from ZERO. So the discriminator is that a tally
# was read at all, not the share: a width has to land within 3px of one of five
# levels, which junk does about a quarter of the time, so three of them is a
# bar chance does not clear.
CHECK_MIN_READ = 3
CHECK_MIN_SHARE = 0.25


@dataclass
class Sighting:
    """One sampled frame, and what the reader made of it."""
    time: float
    kills: int | None
    width: int
    mask: int
    why: str = ""


@dataclass
class Check:
    """Whether the card reader works on this recording."""
    ok: bool
    why: str
    hue: float = 0.0
    looked: int = 0        # frames sampled
    present: int = 0       # frames with something in the HUD colour there
    read: int = 0          # ...of those, frames that gave a usable count
    counts: dict = field(default_factory=dict)
    sightings: list = field(default_factory=list)

    @property
    def share(self) -> float:
        """How often a tally that was THERE could actually be read.

        The number that matters. A region pointed at the wrong part of the
        screen still catches HUD-coloured pixels -- the health number, the
        ammo counter -- so "present" alone proves nothing. Only a width that
        lands on a real card level says the reader is looking at the tally.
        """
        return (self.read / self.present) if self.present else 0.0


def _one_frame(video: Path, at: float, band: tuple,
               size: tuple[int, int]) -> np.ndarray | None:
    """One frame's crop, by seek. Fast: no decoding up to it."""
    import subprocess

    from .killfeed import _NO_WINDOW
    from .tools import binary

    w, h = size
    x1, y1, x2, y2 = band
    cw, ch = max(1, int(w * (x2 - x1))), max(1, int(h * (y2 - y1)))
    cx, cy = int(w * x1), int(h * y1)
    try:
        p = subprocess.run([
            binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", f"{at:.3f}", "-i", str(video), "-an", "-sn",
            "-frames:v", "1", "-filter:v", f"crop={cw}:{ch}:{cx}:{cy}",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ], capture_output=True, check=False, creationflags=_NO_WINDOW)
    except OSError:
        return None
    if len(p.stdout) < cw * ch * 3:
        return None
    return np.frombuffer(p.stdout[:cw * ch * 3], np.uint8).reshape(ch, cw, 3)


def sample_tallies(video: Path, duration: float, hue: float, *,
                   band: tuple = CARDS, start: float = 0.0,
                   tries: int = SAMPLE_TRIES, want: int = 6,
                   size: tuple[int, int] | None = None,
                   frame_height: int = REF_HEIGHT,
                   cancelled: Callable[[], bool] | None = None
                   ) -> list[Sighting]:
    """Find moments the tally is likely on screen, best first.

    Sampled by SEEK rather than by decoding the file, because this runs in
    front of somebody waiting: forty seeks across a 45-minute recording cost
    seconds where a decode costs minutes.

    Sorted by how much of the tally is showing, so the frames handed to a
    person to look at are the ones with the most cards in them -- a one-kill
    tally is a poor thing to calibrate against, and an empty one is useless.
    """
    if size is None:
        from .tools import media_info

        info = media_info(video)
        size = (int(info["width"]), int(info["height"]))
    out: list[Sighting] = []
    # Skipping the first and last slice: a match starts in a warm-up and ends
    # on a scoreboard, and neither has a tally.
    step = max(1.0, duration / (tries + 2))
    for i in range(1, tries + 1):
        if cancelled and cancelled():
            break
        at = start + step * (i + 0.5)
        a = _one_frame(video, at, band, size)
        if a is None:
            continue
        r = read_frame(a, None, hue, at, frame_height)
        out.append(Sighting(time=at, kills=r.kills, width=r.width,
                            mask=r.mask, why=r.why))
    # A real tally first, biggest first; then anything that at least had HUD
    # colour in it, so a failed calibration still has something to show.
    out.sort(key=lambda s: (s.kills or 0, s.mask), reverse=True)
    return out[:want] if want else out


def check(video: Path, duration: float, hue: float, *,
          band: tuple = CARDS, start: float = 0.0,
          tries: int = SAMPLE_TRIES,
          size: tuple[int, int] | None = None,
          frame_height: int = REF_HEIGHT,
          cancelled: Callable[[], bool] | None = None) -> Check:
    """Can the card reader read THIS recording? -> a Check, never raises.

    The test is the reader's own strongest invariant: a real tally is exactly
    `CARD_W0 + CARD_PITCH * kills` pixels wide, and every sample of a given
    count measures the identical width. Point the region somewhere else, or
    give it the wrong hue, and HUD-coloured pixels are still found -- but
    their width lands between the levels, which `read_frame` already rejects
    as a flash. So the share of sightings that produce a usable count
    separates a working calibration from a broken one, with nothing to tune.
    """
    try:
        seen = sample_tallies(video, duration, hue, band=band, start=start,
                              tries=tries, want=0, size=size,
                              frame_height=frame_height, cancelled=cancelled)
    except Exception as e:                          # noqa: BLE001
        return Check(ok=False, why=f"could not read the recording: {e}",
                     hue=hue)

    present = [s for s in seen if s.mask >= MASK_MIN or s.width]
    read = [s for s in present if s.kills]
    counts: dict[int, int] = {}
    for s in read:
        counts[s.kills] = counts.get(s.kills, 0) + 1

    got = Check(ok=False, why="", hue=hue, looked=len(seen),
                present=len(present), read=len(read), counts=counts,
                sightings=seen[:12])
    if not seen:
        got.why = ("Nothing could be read from this recording at all -- "
                   "check the file plays.")
    elif not present:
        got.why = ("No part of the card area is in your HUD colour. Either "
                   "the area is in the wrong place for your HUD scale or "
                   "aspect ratio, or the colour is wrong.")
    elif len(read) < CHECK_MIN_READ:
        got.why = (f"Found HUD colour in the card area {len(present)} time(s) "
                   f"but could only read a kill tally from {len(read)}. That "
                   f"usually means the area is near the tally but not on it.")
    elif got.share < CHECK_MIN_SHARE:
        got.why = (f"Only {got.share:.0%} of what was found reads as a real "
                   f"tally, so the area is probably catching something else "
                   f"on the HUD as well.")
    else:
        got.ok = True
        shown = ", ".join(
            "{} kill{} x{}".format(k, "s" if k > 1 else "", n)
            for k, n in sorted(counts.items()))
        got.why = ("Read a kill tally in {} of {} frames that had HUD colour "
                   "in them ({}).".format(len(read), len(present), shown))
    return got
