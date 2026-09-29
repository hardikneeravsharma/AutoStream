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

    `scan` reads the flash first -- see "The flash" below, which is scored
    against match demos. The width-only reader (`read_frame`, `collapse`) is
    what the calibration screens use to prove the box is on the tally.

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

# Decode only keyframes during the sweep. MEASURED AND REJECTED -- left here
# with its numbers so the idea is not had again.
#
# The speed is real and enormous. Decoding is the whole cost of this scan (raw
# decode of a 120s span is 9.7s against the scan's 8.2s), and skipping to
# keyframes decodes 35 frames instead of 7200: the full 30-minute recording
# read in 0.2 minutes at 121x realtime, against 2.4 minutes at 12.6x.
#
# It is also useless. Scored against Valve's own demo on that same recording:
#
#   full decode   reported 27   correct 19  invented 7  missed 5   P 70%  R 79%
#   keyframes     reported 10   correct  2  invented 8  missed 5   P 20%  R 29%
#
# The reasoning that made it look safe was wrong in one specific way. The
# tally does persist for the whole round, so the COUNT survives coarse
# sampling -- but the information only exists at keyframe boundaries, about
# 3.4s apart, and every constant downstream is tighter than that: MAX_GAP is
# 3.0s, CONFIRM_WINDOW 2.5s, and refine only looks 1.5s back for the flash.
# So a count change is located to worse than the tolerances that have to
# accept it, tracks break, and the kills that do survive are placed so badly
# that the demo fingerprint then aligns to the wrong match -- which is why the
# run above thinks the demo holds 7 kills when it holds 24.
#
# Making this work would mean retuning those three constants together and
# re-scoring, for a scan that already costs 2.4 minutes. Not worth it.
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

def _extract_two(video: Path, start: float, duration: float, fps: float,
                 a: tuple, b: tuple) -> Path:
    """One decode, two crops -- the card tally and the spectator panel.

    Separately they would decode the recording twice, and decoding is the whole
    cost here: the two crops together are under 1% of the frame.

    Kept for the calibration screens, which want real PNGs to show a person.
    The scan itself pipes raw frames instead -- see `_pipe_view`.
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


# ===================================================================
# The flash: WHEN each kill happened, not only how many
# ===================================================================
#
# WHY THE WIDTH WAS NOT ENOUGH. Scored against two match demos (45 kills),
# the width reader above caught 24 of Dust2's 30 and 5 of Inferno's 13 --
# because a count has to hold, unread by a flash, for two samples before it is
# believed, and a player who gets a kill and dies a second later never gives
# it that. Every one of those kills still FLASHED.
#
# THE FLASH IS THREE THINGS AT ONCE, measured on those 45 kills:
#
#   beam    a column in the HUD colour shooting up out of the top card.
#           Nothing above the fan at rest; 1050-1750 px of it for 0.6-1.1s
#           from 0.20s after the demo's kill tick, every time.
#   emblem  the rank emblem under the fan whitening: +440 px or more.
#   count   the fan settling one card wider when it is over.
#
# And one thing that is NOT a kill but looks exactly like one: the flash of a
# team-mate's kill while you are dead and watching them. 30 of those in the
# same two matches. What separates them is the emblem under the fan -- YOURS
# is the same picture all session, while spectating puts the watched player's
# avatar there -- so the reader learns what the player's own emblem looks like
# from the recording itself (see `own_emblems`) and needs no configuration.
#
# MEASURED on 2h36m holding those two matches: 45 of 45 kills, no extras,
# timing within 0.21s of the demo tick for 90% of them.

# Where everything sits, in 1080p pixels from the card band's top-left, so a
# calibrated band carries all of it along. From one 16:9 1080p HUD.
VIEW = (-154, -30, 210, 110)        # x0, y0, x1, y1 -- the whole crop
V_CARDS = (154, 30, 285, 93)        # x0, y0, x1, y1 inside the view
V_BEAM = (154, 0, 285, 30)
V_EMBLEM = (186, 84, 238, 136)
# The spectator panel's top edge crosses these rows, clear of the emblem
# on both sides.
V_PANEL_ROWS = (71, 78)
V_PANEL_COLS = ((0, 150), (280, 364))

FLASH_FPS = 10.0      # the beam lasts 0.6s+, so this sees every one 6 times
BEAM_ON = 600         # px of beam: a flash has started...
BEAM_QUIET = 100      # ...out of a beam this quiet in the half second before
BEAM_HELD = 300       # the level it has to stay above to count as lasting
FLASH_MIN = 0.5       # s. Kills: 0.6-1.1s. HUD blips that are not: <=0.4s
FLASH_MERGE = 0.6     # s. Onsets closer than this are one flash
EMBLEM_RISE = 250     # px of white. Kills: 442 or more. Not kills: 53 or less
WHITE_V, WHITE_S = 0.85, 0.25
# The beam onset trails the server's kill tick by this much -- the median of
# 45, spread p5 -0.01 to p95 +0.26 -- so it comes off every kill time.
FLASH_LAG = 0.20
REFINE_FPS = 60.0

# Own emblem vs somebody else's. Edge maps correlate at 0.88-1.00 with the
# player's own emblem on every kill, and at 0.42 at most for anything shown
# while spectating.
EMBLEM_GRID = 26
EMBLEM_SAME = 0.8     # clustering: same picture
EMBLEM_OWN = 0.6      # a flash is the player's own at or above this
EMBLEM_ENERGY = 4.0   # mean edge strength: something is drawn there at all
EMBLEM_SHARE = 0.02   # a cluster this common in the session is a candidate
PANEL_EDGE = 0.3      # ...unless the spectator panel sits over it this often
EMBLEM_FPS = 2.0
EMBLEM_BEFORE = 0.3   # s. Where a flash's emblem is looked at, before onset
EMBLEM_WHITED = 900   # px of white: mid-flash. At rest it reaches ~640

# Kills the flash could not be seen for: the screen whited out by a flashbang
# when it landed. The tally still moved, so a rise nothing explains is a kill.
OCCLUDED_WHITE = 2000  # px of white in the beam area: the screen is white
HIDDEN_HOLD = 1.0      # s a count must hold, unanimous and beam-free
HIDDEN_GAP = 10.0      # s. A rise over a longer gap is a new round, not this
LEVEL_TOL = 5          # px a steady width may sit off a real level

# Borderline flashes are doubtful, not decided -- a player name makes them
# checkable against the kill feed, which settles them.
DOUBT_FLASH = 0.3      # s: shorter than FLASH_MIN but this long is doubtful
DOUBT_EMBLEM = 0.45    # own-emblem score this high but under EMBLEM_OWN


@dataclass
class Geometry:
    """Pixel boxes for one recording and one card band."""
    crop: tuple[int, int, int, int]     # x, y, w, h of the view in the frame
    k: float                            # 1080p pixels -> this frame's pixels

    def box(self, v: tuple) -> tuple[slice, slice]:
        x0, y0, x1, y1 = (int(round(c * self.k)) for c in v)
        return slice(y0, y1), slice(x0, x1)

    @property
    def area(self) -> float:
        return self.k * self.k


def geometry(size: tuple[int, int], band: tuple = CARDS) -> Geometry:
    w, h = size
    # A calibrated band may be bigger or smaller than the shipped one -- a
    # different hud_scaling -- and everything around it scales with it.
    k = (h / REF_HEIGHT) * (band[2] - band[0]) / (CARDS[2] - CARDS[0])
    k = max(0.25, k)
    bx, by = band[0] * w, band[1] * h
    x0, y0 = int(round(bx + VIEW[0] * k)), int(round(by + VIEW[1] * k))
    x1, y1 = int(round(bx + VIEW[2] * k)), int(round(by + VIEW[3] * k))
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    return Geometry(crop=(x0, y0, x1 - x0, y1 - y0), k=k)


def _pipe_view(video: Path, start: float, duration: float, fps: float,
               crop: tuple[int, int, int, int]):
    """The view, as raw RGB arrays straight off ffmpeg's stdout, in order."""
    import subprocess

    from .killfeed import _NO_WINDOW
    from .tools import binary, has_cuda

    x, y, w, h = crop
    frame = w * h * 3
    proc = subprocess.Popen([
        binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
        *(["-hwaccel", "cuda"] if has_cuda() else []),
        "-ss", f"{start:.3f}",
        # -t BEFORE -i, as an input option: after it, it binds to the output.
        "-t", f"{max(0.05, duration):.3f}",
        "-i", str(video), "-an", "-sn",
        "-vf", f"fps={fps},crop={w}:{h}:{x}:{y}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=_NO_WINDOW)
    try:
        while True:
            buf = proc.stdout.read(frame)
            if len(buf) < frame:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
        proc.wait(timeout=10)


def emblem_map(crop: np.ndarray) -> tuple[np.ndarray, float]:
    """An emblem crop -> (normalised edge map, mean edge strength).

    EDGES, because the emblem is translucent: its fill takes on whatever is
    behind it, but where its outlines are does not change.
    """
    g = crop.astype(np.float32).mean(axis=2)
    n = EMBLEM_GRID * 2
    iy = np.linspace(0, g.shape[0] - 1, n).astype(int)
    ix = np.linspace(0, g.shape[1] - 1, n).astype(int)
    g = g[np.ix_(iy, ix)]
    gy, gx = np.gradient(g)
    m = np.hypot(gx, gy).reshape(EMBLEM_GRID, 2, EMBLEM_GRID, 2).mean(axis=(1, 3))
    energy = float(m.mean())
    return ((m - m.mean()) / (m.std() + 1e-6)).ravel().astype(np.float32), energy


def panel_edge(view: np.ndarray, geo: Geometry) -> float:
    """How much of a straight horizontal edge crosses the spectator panel rows.

    The panel shown while dead has a hard top edge right across the view at a
    fixed height; scenery does not draw one line at exactly that row.
    """
    g = view.astype(np.float32).mean(axis=2)
    cols = np.concatenate([np.arange(int(a * geo.k), min(g.shape[1], int(b * geo.k)))
                           for a, b in V_PANEL_COLS])
    d2 = max(1, int(round(2 * geo.k)))
    best = 0.0
    for y in range(int(V_PANEL_ROWS[0] * geo.k), int(V_PANEL_ROWS[1] * geo.k)):
        if y - d2 < 0 or y + d2 >= g.shape[0] or not len(cols):
            continue
        d = g[y + d2, cols] - g[y - d2, cols]
        s = np.sign(np.median(d)) or 1.0
        best = max(best, float(((d * s) > 6).mean()))
    return best


@dataclass
class Sweep:
    """Everything the flash reader needs, one row per sample."""
    fps: float
    t: np.ndarray
    beam: np.ndarray           # HUD-colour px above the fan
    white_beam: np.ndarray     # white px above the fan: a whited-out screen
    emblem_white: np.ndarray   # white px on the emblem
    width: np.ndarray          # the fan's width, px (0 = none)
    dark: np.ndarray           # the view is black
    # every EMBLEM_FPS: the emblem's edge map, its strength, the panel edge
    et: np.ndarray = field(default_factory=lambda: np.zeros(0))
    emaps: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))
    energy: np.ndarray = field(default_factory=lambda: np.zeros(0))
    panel: np.ndarray = field(default_factory=lambda: np.zeros(0))


def sweep(video: Path, start: float, duration: float, hue: float,
          geo: Geometry, *, fps: float = FLASH_FPS, chunk: float = 120.0,
          progress: Callable[[int, int], None] | None = None,
          cancelled: Callable[[], bool] | None = None) -> Sweep:
    """Read the view at `fps` across [start, start + duration)."""
    cy, cx = geo.box(V_CARDS)
    by, bx = geo.box(V_BEAM)
    ey, ex = geo.box(V_EMBLEM)
    min_col = max(2, int(MIN_COL * geo.k))
    every = max(1, int(round(fps / EMBLEM_FPS)))
    cols = {n: [] for n in ("t", "beam", "wb", "ew", "w", "dark")}
    et, emaps, energy, panel = [], [], [], []

    end = start + duration
    spans, t0 = [], float(start)
    while t0 < end:
        spans.append((t0, min(chunk, end - t0)))
        t0 += chunk
    if progress:
        progress(0, len(spans))
    n = 0
    for si, (at, dur) in enumerate(spans, 1):
        if cancelled and cancelled():
            break
        for i, f in enumerate(_pipe_view(video, at, dur, fps, geo.crop)):
            t = at + i / fps
            h, s, v = _hsv(f)
            dh = np.abs((h - hue + 180.0) % 360.0 - 180.0)
            m = (dh <= HUE_TOL) & (s >= SAT_MIN) & (v >= VAL_MIN)
            white = (v >= WHITE_V) & (s <= WHITE_S)
            mc = m[cy, cx]
            ok = np.nonzero(mc.sum(axis=0) >= min_col)[0]
            cols["t"].append(t)
            cols["beam"].append(int(m[by, bx].sum()))
            cols["wb"].append(int(white[by, bx].sum()))
            cols["ew"].append(int(white[ey, ex].sum()))
            cols["w"].append(int(ok.max() - ok.min() + 1) if len(ok) else 0)
            cols["dark"].append(bool(v.mean() < 0.06 or v.mean() > 0.9))
            if n % every == 0:
                e, en = emblem_map(f[ey, ex])
                et.append(t)
                emaps.append(e.astype(np.float16))
                energy.append(en)
                panel.append(panel_edge(f, geo))
            n += 1
        if progress:
            progress(si, len(spans))
    return Sweep(fps=fps, t=np.asarray(cols["t"], float),
                 beam=np.asarray(cols["beam"]), white_beam=np.asarray(cols["wb"]),
                 emblem_white=np.asarray(cols["ew"]), width=np.asarray(cols["w"]),
                 dark=np.asarray(cols["dark"], bool),
                 et=np.asarray(et, float),
                 emaps=np.asarray(emaps, np.float32).reshape(len(emaps), -1),
                 energy=np.asarray(energy, float), panel=np.asarray(panel, float))


def emblem_clusters(sw: Sweep, limit: int = 3000,
                    seed: int = 0) -> list[tuple[np.ndarray, np.ndarray]]:
    """Group the session's emblem samples into pictures. -> [(centroid, members)]

    Largest first. Sampled down to `limit` so a long session costs the same as
    a short one; seeded so the same recording always gives the same answer.
    """
    idx = np.nonzero(sw.energy > EMBLEM_ENERGY)[0]
    if not len(idx):
        return []
    idx = idx[np.random.default_rng(seed).permutation(len(idx))[:limit]]
    cents: list[np.ndarray] = []
    members: list[list[int]] = []
    d = sw.emaps.shape[1]
    for i in idx:
        v = sw.emaps[i]
        if cents:
            sims = np.asarray([float(v @ c) / d for c in cents])
            j = int(sims.argmax())
            if sims[j] >= EMBLEM_SAME:
                members[j].append(int(i))
                continue
        cents.append(v)
        members.append([int(i)])
    out = []
    for c, mem in zip(cents, members):
        mean = sw.emaps[mem].mean(axis=0)
        out.append((mean / (mean.std() + 1e-6), np.asarray(mem)))
    out.sort(key=lambda cm: -len(cm[1]))
    return out


def own_emblems(sw: Sweep, clusters=None) -> np.ndarray:
    """Candidate pictures of the player's OWN emblem. -> (n, d) array.

    Common in the session and not under the spectator panel. A menu or a
    loading screen can pass that too, which is why `scan` then keeps only the
    candidates a real kill flash was seen over -- a menu never flashes.
    """
    clusters = emblem_clusters(sw) if clusters is None else clusters
    total = sum(len(m) for _, m in clusters) or 1
    keep = [c for c, m in clusters
            if len(m) / total >= EMBLEM_SHARE
            and float(np.median(sw.panel[m])) < PANEL_EDGE]
    return np.asarray(keep, np.float32).reshape(len(keep), -1)


def emblem_score(sw: Sweep, own: np.ndarray, at: float,
                 area: float = 1.0) -> tuple[float, int]:
    """(best similarity to an own emblem, which one) as it last looked before `at`.

    Skipping samples where the emblem was whited out by a flash: a kill 1.2s
    after another would otherwise be judged on the first one's white-out,
    which matches nothing. Going back further than that is not safe -- a
    team-mate's trade kill can follow your death by a second.
    """
    if not len(own) or not len(sw.et):
        return 0.0, -1
    i = int(np.searchsorted(sw.et, at)) - 1
    for _ in range(4):
        if i < 0:
            return 0.0, -1
        k = min(len(sw.t) - 1, int(np.searchsorted(sw.t, sw.et[i])))
        if not len(sw.emblem_white) or sw.emblem_white[k] < EMBLEM_WHITED * area:
            break
        i -= 1
    s = own @ sw.emaps[i] / own.shape[1]
    j = int(s.argmax())
    return float(s[j]), j


@dataclass
class Flash:
    time: float                # the first sample over BEAM_ON
    length: float              # seconds the beam held
    rise: int                  # emblem whitening, px
    before: int | None         # steady count before
    after: int | None          # steady count after
    own: float = 0.0           # emblem similarity to the player's own
    which: int = -1            # ...to which own emblem
    kills: int = 0             # how many kills this flash is, once decided
    doubt: str = ""            # why it could not be decided from pixels alone


def _level(w: int, k: float) -> int | None:
    """A fan width -> a card count, only if it sits ON a real level."""
    if w == 0:
        return 0
    n = int(round((w - CARD_W0 * k) / (CARD_PITCH * k)))
    if 1 <= n <= MAX_KILLS and abs(w - (CARD_W0 + CARD_PITCH * n) * k) <= LEVEL_TOL * k:
        return n
    return None


def _count(sw: Sweep, k: float, a: float, b: float,
           occluded: np.ndarray) -> int | None:
    """The count the fan holds most over [a, b), or None if it is not steady."""
    i0 = max(0, int(np.searchsorted(sw.t, a)))
    i1 = int(np.searchsorted(sw.t, b))
    if i1 <= i0 or occluded[i0:i1].any():
        return None
    ks = [x for x in (_level(int(w), k) for w in sw.width[i0:i1]) if x is not None]
    if len(ks) < max(2, 0.4 * (i1 - i0)):
        return None
    v, c = np.unique(ks, return_counts=True)
    return int(v[c.argmax()])


def flashes(sw: Sweep, geo: Geometry) -> list[Flash]:
    """Every onset of the beam, with what surrounds it. Recall first."""
    a = geo.area
    on_px, quiet_px, held_px = BEAM_ON * a, BEAM_QUIET * a, BEAM_HELD * a
    b = sw.beam
    back = max(1, int(0.5 * sw.fps))
    occluded = (sw.white_beam > OCCLUDED_WHITE * a) | sw.dark
    starts = [i for i in np.nonzero((b[1:] >= on_px) & (b[:-1] < on_px))[0] + 1
              if b[max(0, i - back):i].min() < quiet_px]
    out: list[Flash] = []
    for n, i in enumerate(starts):
        x = float(sw.t[i])
        if out and x - out[-1].time < FLASH_MERGE:
            continue
        # how long it held, bridging dips shorter than 0.2s
        j, gap, lim = i, 0, min(len(b), i + int(3 * sw.fps))
        while j < lim:
            gap = gap + 1 if b[j] < held_px else 0
            if gap > 0.2 * sw.fps:
                break
            j += 1
        length = (j - gap - i) / sw.fps
        pre = sw.emblem_white[max(0, i - int(1.2 * sw.fps)):max(1, i - int(0.2 * sw.fps))]
        # Against the LEAST white the emblem was just before: a kill 1.2s
        # after another starts while the first one's white is still fading.
        rise = int(sw.emblem_white[i:i + int(sw.fps)].max() - (pre.min() if len(pre) else 0))
        nxt = [sw.t[s] for s in starts[n + 1:] if sw.t[s] > x + FLASH_MERGE]
        stop = min(x + 2.0, (float(nxt[0]) - 0.1) if nxt else x + 2.0)
        out.append(Flash(time=x, length=length, rise=rise,
                         before=_count(sw, geo.k, x - 1.2, x - 0.2, occluded),
                         after=_count(sw, geo.k, x + 1.0, stop, occluded)))
    return out


def judge(fl: list[Flash], sw: Sweep, own: np.ndarray,
          area: float = 1.0) -> np.ndarray:
    """Decide each flash from pixels alone; mark the borderline ones doubtful.

    -> the own emblems that some kill actually flashed over. Only those are
    trusted afterwards: a menu is common and panel-free, but never flashes.
    """
    used = set()
    for f in fl:
        # The emblem as it was BEFORE the flash: it starts whitening a frame
        # or two ahead of the beam, and a white emblem matches nothing.
        f.own, f.which = emblem_score(sw, own, f.time - EMBLEM_BEFORE, area)
        strong = f.rise >= EMBLEM_RISE * area
        if f.own >= EMBLEM_OWN and strong and f.length >= FLASH_MIN:
            f.kills = 1
            if f.before is not None and f.after is not None and f.after - f.before > 1:
                # two kills inside one flash: the fan knows how many
                f.kills = f.after - f.before
            used.add(f.which)
        elif strong and f.length >= DOUBT_FLASH and f.own >= DOUBT_EMBLEM:
            f.doubt = ("a short flash" if f.length < FLASH_MIN
                       else "an emblem that is not quite yours")
    keep = sorted(used)
    return own[keep] if keep else own[:0]


def hidden_kills(sw: Sweep, geo: Geometry, own: np.ndarray,
                 counted: list[float]) -> list[float]:
    """Kills the flash was never seen for, from rises nothing explains.

    Walks the count wherever it is steady for a full second on the player's
    own view. A rise that the flashes in between do not account for is a kill
    whose flash was hidden -- placed where the view was lost, since that is
    where it happened.
    """
    if not len(own):
        return []
    a = geo.area
    occluded = (sw.white_beam > OCCLUDED_WHITE * a) | sw.dark
    hold = max(2, int(HIDDEN_HOLD * sw.fps))
    out: list[float] = []
    cur, cur_t = None, 0.0
    i = 0
    while i + hold < len(sw.t):
        seg = slice(i, i + hold)
        ws = sw.width[seg]
        if (sw.beam[seg].max() > BEAM_QUIET * a or occluded[seg].any()
                or emblem_score(sw, own, float(sw.t[i]), a)[0] < EMBLEM_OWN):
            i += 1
            continue
        lv = [_level(int(w), geo.k) for w in ws]
        if any(x is None for x in lv) or len(set(lv)) != 1:
            i += 1
            continue
        k = lv[0]
        t = float(sw.t[i])
        if cur is not None and k > cur and t - cur_t < HIDDEN_GAP:
            seen = sum(1 for c in counted if cur_t - 0.5 <= c <= t + 0.5)
            lost = cur_t
            j = int(np.searchsorted(sw.t, cur_t))
            while j < i and not occluded[j]:
                j += 1
            if j < i:
                lost = float(sw.t[j])
            out += [lost] * max(0, k - cur - seen)
        cur, cur_t = k, float(sw.t[i + hold - 1])
        i += hold
    return out


def deaths(sw: Sweep, own: np.ndarray, within: float = 6.0,
           hold: int = 2) -> list[float]:
    """When the player died: their own emblem vanished, and the next thing
    under the fan was somebody else's, under the spectator panel.

    MEASURED against the demo: at every death the emblem is gone inside half
    a second -- the death cam has no HUD -- so the moment it goes is the
    death. A flashbang takes it too, and so does a round ending, which is why
    the spectator view has to follow within `within` seconds, before the
    player's own emblem does.
    """
    out: list[float] = []
    if not len(own):
        return out
    d = own.shape[1]
    sims = (sw.emaps @ own.T).max(axis=1) / d if len(sw.emaps) else np.zeros(0)
    mine = (sw.energy > EMBLEM_ENERGY) & (sims >= EMBLEM_OWN)
    other = (sw.energy > EMBLEM_ENERGY) & ~mine & (sw.panel >= PANEL_EDGE)
    i = 1
    while i < len(sw.et):
        if mine[i - 1] and not mine[i] and sw.energy[i] <= EMBLEM_ENERGY:
            gone = float(sw.et[i])
            j, run = i, 0
            while j < len(sw.et) and sw.et[j] - gone <= within and not mine[j]:
                run = run + 1 if other[j] else 0
                if run >= hold:
                    out.append(gone)
                    break
                j += 1
            i = j + 1
            continue
        i += 1
    return out


def refine_onsets(video: Path, times: list[float], hue: float, geo: Geometry,
                  cancelled: Callable[[], bool] | None = None) -> list[float]:
    """Each onset to the exact frame, at the recording's full rate."""
    by, bx = geo.box(V_BEAM)
    on_px = BEAM_ON * geo.area
    out = []
    for x in times:
        if cancelled and cancelled():
            out.append(x)
            continue
        start = max(0.0, x - 1.0 / FLASH_FPS - 0.05)
        best = x
        for i, f in enumerate(_pipe_view(video, start, x - start + 0.02,
                                         REFINE_FPS, geo.crop)):
            if hud_mask(f[by, bx], hue).sum() >= on_px:
                best = start + i / REFINE_FPS
                break
        out.append(min(best, x))
    return out


def confirm_in_feed(video: Path, feed_band, player: str,
                    around: float) -> float | None:
    """Is there a kill by `player` in the feed near `around`? -> its time.

    The kill feed is the expensive, certain check: OCR and a name. So it is
    asked only about what the pixels could not settle.
    """
    from . import killfeed

    try:
        got = killfeed.scan(video, feed_band, player,
                            start=max(0.0, around - 1.0), duration=5.0,
                            fps=4.0, workers=1)
    except Exception as e:                         # noqa: BLE001
        log.info("feed check at %.1fs could not run: %s", around, e)
        return None
    hits = [e.time for e in got if e.kind == "kill"]
    return min(hits, key=lambda h: abs(h - around)) if hits else None


def scan(video: Path, *, duration: float | None = None, start: float = 0.0,
         fps: float = FLASH_FPS, chunk: float = 120.0,
         hue: float | None = None, frame_height: int = REF_HEIGHT,
         band: tuple | None = None,
         player: str = "", feed_band: tuple | None = None,
         progress: Callable[[int, int], None] | None = None,
         cancelled: Callable[[], bool] | None = None) -> list[Event]:
    """Read every kill off the card tally, timed to its flash.

    -> kill and death events in time order. `player` and `feed_band` are
    optional: given them, the few flashes pixels cannot settle are checked
    against the kill feed; without them those few are left out.
    """
    from .killfeed import _sweep_stale_temp
    from .tools import media_info

    video = Path(video)
    info = media_info(video)
    total = duration if duration is not None else info["duration"]
    _sweep_stale_temp()
    if hue is None:
        hue = measure_hue(video, total, start=start)
        if hue is None:
            raise RuntimeError(
                "Could not work out your CS2 HUD colour from this recording. "
                "Set it by hand on the Clips page, or pick a recording with "
                "more gameplay in it.")
        log.info("measured CS2 HUD colour: hue %.0f", hue)

    size = (int(info["width"]), int(info["height"]))
    geo = geometry(size, band or CARDS)
    # Never slower than the flash needs. The profile's rate was set for the
    # width reader, which only had to see a count that holds for a round.
    sw = sweep(video, start, total, hue, geo, fps=max(fps, FLASH_FPS),
               chunk=chunk, progress=progress, cancelled=cancelled)
    if cancelled and cancelled():
        return []

    fl = flashes(sw, geo)
    own = judge(fl, sw, own_emblems(sw), geo.area)
    kills: list[float] = []
    for f in fl:
        kills += [f.time] * f.kills
    doubtful = [f for f in fl if f.doubt]
    checked = 0
    if doubtful and player and feed_band:
        for f in doubtful:
            if cancelled and cancelled():
                break
            if confirm_in_feed(video, feed_band, player, f.time) is not None:
                kills.append(f.time)
                checked += 1
    exact = refine_onsets(video, kills, hue, geo, cancelled)
    hidden = hidden_kills(sw, geo, own, exact)

    events = [Event(time=max(0.0, x - FLASH_LAG), running=0) for x in exact]
    events += [Event(time=x, running=0) for x in hidden]
    events += [Event(time=x, kind="death") for x in deaths(sw, own)]
    events.sort(key=lambda e: e.time)
    t = tally(events)
    log.info("%s: %d kill(s) and %d death(s) from the card tally -- %d flash(es), "
             "%d hidden kill(s) from the count, %d of %d doubtful flash(es) "
             "confirmed in the feed (%d samples, %d own emblem(s))",
             video.name, t["kill"], t["death"], len(fl), len(hidden), checked,
             len(doubtful), len(sw.t), len(own))
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
