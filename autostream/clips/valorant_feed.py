"""Valorant kill feed, read from the coloured bars rather than the text.

WHY NOT OCR, WHICH IS WHAT CS2 DOES
    Because it does not work here. Tesseract reads the local player's own name
    in 13-16% of the frames the row is actually on screen, and no preprocessing
    moves that: upscaling to x4 and x6, greyscale plus autocontrast, sharpening,
    a green-channel lift and inversion were each measured over 176 frames taken
    around rows known to be present, and they scored 13, 7, 14, 1, 14 and 16
    per cent. Over the whole 46-minute recording the name came back 24 times at
    a 0.62 match and 12 times at 0.90 -- roughly one read every two minutes, in
    a game where the player is in perhaps a fifth of all rows.

    A detector resting on that would miss most events, and miss them SILENTLY,
    which is the one failure a clipper cannot afford: it is indistinguishable
    from a quiet recording.

WHAT IS ACTUALLY THERE
    Valorant draws each feed row as a solid two-tone bar, and puts a bright
    yellow border around the LOCAL PLAYER's own segment. Measured over frames
    verified by eye:

        red     R 208  G 106  B  92     the enemy team's half of a row
        green   R 118  G 186  B 160     your team's half
        yellow  R 220  G 210  B 125     the border around your own segment

        G - R        green +68   red -102              tells the teams apart
        min(R,G)-B   yellow +85  red +14   green -42   tells yours from theirs

    Note the green is a TEAL -- B is 160 -- so `G - max(R, B)` comes out at 26,
    and a threshold anywhere near it fails on half the frames. That was the
    first attempt and it lost whole rows. G - R is the test that works.

    So the row is found by colour, and the verdict comes from which end of it
    the yellow is on. No name, no OCR, no Tesseract, and nothing to configure.

A ROW, LEFT TO RIGHT
    [assist tiles] [killer portrait] KILLER [weapon] [victim] [victim portrait]
    -- the killer's half in their team's colour, the victim's half in theirs
    -- every row RIGHT-ALIGNED to the same margin, measured 0.978-0.986 of the
       band across every row of every frame checked
    -- assists are never named: they appear only as small portrait tiles,
       DETACHED, sitting about 130px clear of the bar

    That last point is what keeps an assist from being clipped as a kill -- the
    confusion CS2's profile notes still apologise for. See `_verdict`.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger("autostream.clips.valorant_feed")

# --------------------------------------------------------------------- colour
# All three tests are RELATIVE within the pixel -- differences between channels,
# never absolute levels -- so they survive the translucent wash the bars are
# drawn over, and a re-encode that shifts the hue.
SAT_MIN = 35          # max(R,G,B) - min(R,G,B); below this it is scenery
YELLOW_MIN = 55       # min(R,G) - B.  yellow +85, red +14, green -42
TEAM_MIN = 30         # |G - R|.       green +68, red -102

# ------------------------------------------------------------------- geometry
# The reference height everything in pixels below was measured at. Bands are
# fractions of the frame, but a row's HEIGHT and the gaps around it are real
# pixels, so they are scaled by the frame height before use -- the same reason
# profiles carry ref_height for a template.
REF_HEIGHT = 1080

# A window INSIDE the bar, away from both ends: the left end moves with how long
# the two names are, and the right end is a photograph. Measured over three
# frames, coverage here runs 0.66-1.00 all the way down a row and falls to
# 0.14-0.28 between two, so 0.35 sits in a gap never narrower than 0.38.
#
# The obvious window -- the right-hand end, 0.84-1.00 -- does NOT work: the
# victim's portrait is a photograph rather than a flat colour, so it reads
# 0.31-0.74 inside a row and overlaps the gaps entirely.
DENSE_X = (0.70, 0.90)
# Not load-bearing for where a row's boundaries land: dropping it to 0.02 makes
# the gaps dense too, the three rows merge into one run, and _split_tall then
# puts every boundary back within a pixel of where it was. What it does earn is
# rejecting frames that hold no rows at all. Recorded because a mutation sweep
# showed no test could tell 0.35 from 0.02, and the reason is worth knowing
# rather than papering over with a test contrived to fail.
DENSE_MIN = 0.35

PITCH = 39            # px between the tops of consecutive rows; a row is 34
                      # tall, so two stacked leave about five scanlines of gap
MIN_ROW_H = 12
MAX_ROW_H = 46
JOIN_GAP = 2          # scanlines of slack when repairing one row
MIN_SEG = 8           # px; shorter column runs are icons, not segments

# Every row ends at the same margin -- measured 0.978-0.986 of the band. The
# left-anchored "X KILLED Y" banner never reaches it and neither does the
# netgraph overlay, so this single test excludes both without needing to know
# where either of them is drawn.
RIGHT_MIN = 0.95

# 1.5 row heights. The gap between the player's own portrait and their name
# segment measured 7-20px; the gap between a DETACHED ASSIST TILE and the
# segment measured 130px. An earlier 0.6 put the threshold at 19px and missed a
# real kill by one pixel, so it sits mid-gap instead.
TOUCH_ROWS = 1.5
# Yellow mass needed before a row is called the player's at all. Scaled by the
# row's HEIGHT and not by how long the segment happens to be: a long row does
# not need more yellow than a short one, and scaling by length put the floor at
# 210 against a real assist's 187.
# Per pixel of row HEIGHT. Measured over 705 sightings: real kills and deaths
# cluster at 16-27 with a median near 22, while the leakage that turned one
# assist into a kill sat at 6.4. A floor of 2.0 let that through; 10.0 sits in
# the gap. Not scaled by the segment's length -- a long row does not need more
# yellow to be the player's than a short one, and scaling by length once put
# the floor at 210 against a real assist's 187.
YELLOW_FLOOR = 10.0
MIN_YELLOW_RUN = 12   # px of yellow before a patch counts at all
# Detached yellow -- an assist tile -- needs more than the ends do, because at
# the ends the yellow is a border of known shape whereas out here anything
# warm will do. Measured: real assist tiles 187, 333, 445, 473; the wash on
# rows that were not the player's, 52-74.
ASIDE_FLOOR = 120

# A row is TWO-TONE and both tones are substantial: the killer's team colour and
# the victim's. That is not a fitted threshold but a property of the thing --
# any row involving the local player is their colour beside the other side's,
# because they killed someone or someone killed them.
#
# It is also what rejects scenery, which is the whole difficulty here. Measured
# over 12 rows verified by eye and 25 false positives from a brick wall and the
# agent-select screen:
#
#     real rows        red 0.19-0.60   green 0.16-0.54   pair 0.29-0.96
#     brick wall       red 0.03-0.21   green 0.00-0.06   pair 0.00
#     agent select     red 0.00        green 0.87-0.99   pair 0.00
#
# Warm brick reads as red and sky blue as green, so either colour ALONE finds
# hundreds of rows in scenery -- an unfiltered pass over the recording returned
# 347 kills and 497 deaths. Requiring both rejects every one of them.
MIN_TONE = 0.10       # of the row's area, each colour
MIN_PAIR = 0.15       # min(red, green) / max(red, green)
MIN_ROW_W = 150       # px. A row has to fit two names, a portrait and an icon.
# And an upper bound: real rows measured 202-529px wide across every verdict,
# so anything much beyond that is two things being read as one.
MAX_ROW_W = 560

# A settled row has BACKGROUND to its right -- it ends at frame x 1900-1906 on a
# 1920-wide frame, never flush with the edge. A bar that runs right off the side
# of the band is a row still sliding in, and its geometry is nonsense while it
# does: mid-animation frames measured x0 at 234 instead of 630, heights of 29
# and 43 against a settled 34, and yellow masses of 1304 and 3470 against a
# settled 856. Three of the false kills in the first audit were animation
# frames read as if they were rows.
#
# Assumes the band reaches the frame's right edge, which the built-in profile
# and the calibrator's "draw around the WHOLE feed" guidance both do.
EDGE_MARGIN = 6

# ----------------------------------------------------------- whose victim
#
# A row is [portrait] KILLER [icon] VICTIM [portrait], with each half in its
# owner's team colour -- so the colour of the VICTIM's half names the side that
# just lost a player. That is what the round layer needs and what no other
# signal here provides: `kind` only ever speaks about the local player, and
# most rows are other people killing each other.
#
# Two simpler readings were measured and rejected:
#
#   the last 28% of the row      157/157 kills right, but wrong on a self-kill.
#                                Agent portraits are photographs -- warm artwork
#                                that reads RED whichever team the player is on
#                                -- and on a self-kill the bar is green with a
#                                red portrait at each end.
#   the right half, portraits    straddles the boundary between the two halves,
#   excluded                     which moves with how long the two names are.
#                                Red and green came within 10% of each other and
#                                the winner was noise: 154/157 and 34/45.
#
# So: clear the portraits, then walk a narrow window in from the bar's right
# end until it sits confidently on one colour. Measured over 202 row sightings
# spread across the recording: 157/157 kills read the victim as an enemy and
# 43/45 deaths read the victim as the player's own side. Both misses are single
# frames of rows that read correctly in every other frame, so the per-event
# majority in `collapse` clears them.
PORTRAIT_ZONE = 0.18      # of the row, at each end
PROBE_W = 24              # px of row that has to agree with itself
PROBE_STEP = 8
PROBE_SURE = 3.0          # how far one colour must beat the other
PROBE_FLOOR = 40          # below this there is no bar here at all

SAMPLE_FPS = 2.0
# A row lives about five seconds, so two samples a second cannot miss one and
# gives every event several looks to agree over.
MERGE_GAP = 3.0


def masks(a: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """-> (red, green, yellow) boolean masks for one RGB band image."""
    a = a.astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    hot = (a.max(axis=2) - a.min(axis=2)) >= SAT_MIN
    yellow = hot & (np.minimum(r, g) - b >= YELLOW_MIN)
    rest = hot & ~yellow
    # `b <= g` matters: the ally colour is a TEAL, B 160 against G 186, so it
    # passes -- but sky blue does not, and the agent-select screen is a wall of
    # it. Without this the whole screen read as one enormous ally segment and
    # produced five bogus rows a frame.
    return rest & (r - g >= TEAM_MIN), rest & (g - r >= TEAM_MIN) & (b <= g), yellow


def _runs(flags: np.ndarray, gap: int = 0) -> list[tuple[int, int]]:
    """Contiguous True runs, tolerating gaps of up to `gap`."""
    idx = np.flatnonzero(flags)
    if not len(idx):
        return []
    out: list[tuple[int, int]] = []
    start = prev = int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - prev > gap + 1:
            out.append((start, prev + 1))
            start = i
        prev = i
    out.append((start, prev + 1))
    return out


def _split_tall(y0: int, y1: int, prof: np.ndarray, pitch: int,
                min_h: int) -> list[tuple[int, int]]:
    """Cut a run that is several rows stacked with no gap between them.

    Two rows usually leave a few scanlines of background, but not always: in one
    frame three rows ran together and the coverage never fell below 0.46 across
    the joins, so no threshold could separate them and both lower rows were
    lost entirely. What does separate them is the PITCH -- rows start every 39px
    against a row height of 34 -- so the count is arithmetic, and each boundary
    is then placed at the local minimum near where it is due.
    """
    height = y1 - y0
    n = max(1, int(round(height / pitch)))
    if n < 2:
        return [(y0, y1)]
    cuts = [y0]
    for k in range(1, n):
        want = y0 + int(round(k * height / n))
        lo = max(cuts[-1] + min_h, want - 7)
        hi = min(y1 - min_h, want + 7)
        cuts.append(int(lo + np.argmin(prof[lo:hi + 1])) if hi > lo else want)
    cuts.append(y1)
    return [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]


def _row_runs(flags: np.ndarray, max_h: int) -> list[tuple[int, int]]:
    """Scanline runs, joining a gap only when the result is still ONE row.

    Rows sit about five scanlines apart, and a row can lose a scanline or two in
    its middle where the weapon icon crosses it -- so the two cases cannot be
    told apart by the size of the gap. They can be told apart by the result: two
    rows joined come out at 76px against a row height of 34, so anything over
    max_h was never one row. Joining on gap size alone merged a real kill and a
    real death into one run and dropped both.
    """
    out: list[tuple[int, int]] = []
    for s, e in _runs(flags):
        if out and s - out[-1][1] <= JOIN_GAP and e - out[-1][0] <= max_h:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


@dataclass
class Row:
    """One feed row seen in one frame."""
    time: float
    kind: str           # "kill" | "death" | "assist" | "other"
    y0: int
    y1: int
    x0: int             # left edge of the name segment, band px
    x1: int             # right margin of the row, band px
    left: int = 0       # yellow mass at the killer end
    right: int = 0      # yellow mass at the victim end
    aside: int = 0      # yellow mass detached from the bar -- an assist tile
    # "mine" | "enemy" | "" -- which side lost the player. See PORTRAIT_ZONE.
    victim: str = ""

    @property
    def key(self) -> float:
        """What identifies this row across frames: where its segment starts.

        Not its y, which moves as rows above it expire, and not its kind, which
        is what is being decided. The segment's left edge is set by how long the
        two names are, so it holds still for as long as the row is on screen.
        """
        return float(self.x0)


def _two_tone(red: np.ndarray, green: np.ndarray, strip: slice,
              x0: int, x1: int) -> bool:
    """Is this a feed row at all, or is it scenery?

    See MIN_TONE. A row carries both team colours in quantity; a brick wall
    carries only red and the agent-select screen only blue-read-as-green.
    """
    area = max(1, (strip.stop - strip.start) * (x1 - x0))
    nr = int(red[strip, x0:x1].sum()) / area
    ng = int(green[strip, x0:x1].sum()) / area
    if nr < MIN_TONE or ng < MIN_TONE:
        return False
    return min(nr, ng) / max(nr, ng) >= MIN_PAIR


def _verdict(yellow: np.ndarray, strip: slice, mx0: int, mx1: int,
             row_h: int) -> tuple[str, int, int, int]:
    """Whose row is this, and did they kill or die?

    Each patch of yellow is assigned by WHAT IT TOUCHES rather than by where it
    falls in the row. On a kill the yellow overlaps the name segment's left
    edge; on a death it runs to the right margin; on an assist the player's
    portrait is a detached tile sitting well clear of the segment.

    By distance from the row's left edge the kill and the assist are only 14px
    apart, because how far a portrait sits from the name changes with the
    agent's picture. By adjacency they are 110px apart.
    """
    touch = max(8, int(row_h * TOUCH_ROWS))
    ycol = yellow[strip].sum(axis=0)
    left = right = aside = 0
    for s, e in _runs(ycol >= 2, 3):
        mass = int(ycol[s:e].sum())
        if mass < MIN_YELLOW_RUN:
            continue
        if e >= mx1 - touch:
            right += mass
        elif e >= mx0 - touch:
            left += mass
        else:
            aside += mass
    floor = max(60, int(YELLOW_FLOOR * row_h))
    if max(left, right) < floor:
        # Their portrait can still be on the row, as an assist tile beside
        # somebody else's kill. That is not a kill and must not be clipped as
        # one.
        return ("assist" if aside >= ASIDE_FLOOR else "other"), left, right, aside
    if min(left, right) >= floor:
        # The player is at BOTH ends: they killed themselves, with their own
        # ability or a fall. That is a death, and letting the two masses race
        # each other decided it on a 16-pixel margin -- the same row came out
        # "death" in two frames and "kill" in five, and the kill won.
        return "death", left, right, aside
    return ("death" if right > left else "kill"), left, right, aside


def victim_of(red: np.ndarray, green: np.ndarray, y0: int, y1: int,
              x0: int, x1: int, k: float = 1.0) -> str:
    """Which side the victim was on. "" when the row will not say."""
    strip = slice(y0, y1)
    span = x1 - x0
    lo = x0 + int(span * PORTRAIT_ZONE)
    hi = x1 - int(span * PORTRAIT_ZONE)
    probe = max(6, int(PROBE_W * k))
    step = max(2, int(PROBE_STEP * k))
    floor = PROBE_FLOOR * k * k
    r_cols = red[strip].sum(axis=0)
    g_cols = green[strip].sum(axis=0)
    at = hi
    while at - probe >= lo:
        r = float(r_cols[at - probe:at].sum())
        g = float(g_cols[at - probe:at].sum())
        if max(r, g) >= floor and max(r, g) >= PROBE_SURE * max(1.0, min(r, g)):
            return "enemy" if r > g else "mine"
        at -= step
    return ""


def read_frame(a: np.ndarray, at: float = 0.0, ref_height: int = REF_HEIGHT,
               frame_height: int | None = None) -> list[Row]:
    """Every feed row in one frame of the band. -> newest last."""
    red, green, yellow = masks(a)
    bar = red | green | yellow
    h, w = bar.shape
    # Pixel measurements were taken at REF_HEIGHT; scale them to this recording.
    k = (frame_height or ref_height) / REF_HEIGHT
    pitch = max(4, int(PITCH * k))
    min_h, max_h = max(3, int(MIN_ROW_H * k)), max(6, int(MAX_ROW_H * k))
    min_seg = max(2, int(MIN_SEG * k))

    lo, hi = int(w * DENSE_X[0]), int(w * DENSE_X[1])
    prof = bar[:, lo:hi].mean(axis=1)

    out: list[Row] = []
    for ry0, ry1 in _row_runs(prof >= DENSE_MIN, max_h):
        for y0, y1 in _split_tall(ry0, ry1, prof, pitch, min_h):
            if not (min_h <= y1 - y0 <= max_h):
                continue
            strip = slice(y0, y1)
            on = bar[strip].mean(axis=0) >= 0.30
            if not on.any():
                continue
            x1 = int(w - np.argmax(on[::-1]))
            if x1 / w < RIGHT_MIN or x1 > w - EDGE_MARGIN * k:
                continue
            # The left edge is the start of the row's LONGEST solid run, not its
            # leftmost coloured pixel -- the assist tiles are further left again.
            # Walking in from the right instead does not work: the victim's
            # portrait is a photograph, so it leaves a 40px hole that ends the
            # walk immediately.
            segs = [(s, e) for s, e in _runs(on) if e - s >= min_seg]
            if not segs:
                continue
            mx0, mx1 = max(segs, key=lambda r: r[1] - r[0])
            if not (MIN_ROW_W * k <= x1 - mx0 <= MAX_ROW_W * k):
                continue
            if not _two_tone(red, green, strip, mx0, x1):
                continue
            kind, left, right, aside = _verdict(yellow, strip, mx0, mx1,
                                                y1 - y0)
            out.append(Row(time=at, kind=kind, y0=y0, y1=y1, x0=int(mx0),
                           x1=x1, left=left, right=right, aside=aside,
                           victim=victim_of(red, green, y0, y1, mx0, x1, k)))
    return _drop_flash(out)


def _drop_flash(found: list[Row]) -> list[Row]:
    """Throw away a frame's death verdicts when it says the player died twice.

    In Valorant you die at most once a round, and rounds are half a minute
    apart, so two of your own death rows on screen together is not a thing that
    can happen -- unlike two kill rows, which is just a double kill.

    When it does happen, the cause is a whole-screen colour event: a flash, a
    spike detonation, an ability. Measured at 1196.5s, three rows that read
    "other" in the frames either side all turned "death" together for a single
    frame, each with 218-232 yellow at its right end. This is the false-death
    failure the design notes warned about, and it is caught here by the game's
    own rule rather than by a threshold that would have to be tuned.
    """
    if sum(1 for r in found if r.kind == "death") < 2:
        return found
    for r in found:
        if r.kind == "death":
            r.kind = "other"
    return found


# ------------------------------------------------------------------ collapsing
#
# A row lives about five seconds, so at 2 fps one event arrives as roughly ten
# sightings. Which of them is the event, and which sightings belong to the same
# row, is decided here rather than per frame -- the CS2 detector's one hard-won
# lesson is that no single frame's verdict should ever become an event.

X_TOL = 14            # px. How far a row's segment edge may wander frame to
                      # frame and still be the same row.
MAX_GAP = 2.0         # s. Longer than this and it is a new row, not the old one
                      # flickering.
# A row lives about five seconds. Without a cap a track walks from one row to
# the next for as long as their left edges happen to line up: tracks of 8.0,
# 8.5, 9.5 and 13.0 seconds were all several separate rows welded together,
# and the welded verdict was whatever won the combined vote.
MAX_LIFE = 7.0
SETTLE_GAP = 0.75     # s. One frame at the 2 fps this scans at, with slack.
# Frames that must agree before a row becomes an event. A row lives about five
# seconds -- ten frames at 2 fps -- and real events were seen holding a steady
# verdict for four to ten of them, so three is well clear of a one-frame
# artefact without being near a real row's length. This is the rule CS2 taught:
# no single frame's verdict may become an event.
MIN_SEEN = 3


@dataclass
class Event:
    """One kill or death, after repeated sightings have been collapsed."""
    time: float
    kind: str           # "kill" | "death" | "assist" | "other"
    end: float = 0.0
    seen: int = 1
    votes: str = ""     # what the individual frames said, for diagnostics
    x0: int = 0
    y0: int = 0         # where the row sat when last seen
    # Which side lost the player, by majority over the sightings. This is the
    # only thing here that speaks about rows the local player is not in, and so
    # the only thing a round's alive counts can be built from.
    victim: str = ""
    # So an Event can stand in for a killfeed.FeedEvent downstream, where the
    # score is only ever reported. There is no fuzzy match here to score --
    # confidence is `seen`, the number of frames that agreed.
    ratio: float = 1.0

    def __post_init__(self) -> None:
        if not self.end:
            self.end = self.time


def collapse(seen: list[Row], min_seen: int = MIN_SEEN) -> list[Event]:
    """Sightings -> events. One row on screen becomes exactly one event."""
    tracks: list[dict] = []
    for r in sorted(seen, key=lambda s: (s.time, s.y0)):
        cands = []
        for t in tracks:
            if r.time - t["last"] > MAX_GAP:
                continue
            # Normally a row is recognised by where its name segment starts.
            # But that edge is the start of the row's longest solid run, and
            # which run is longest can change: FROM FOOTAGE at 1m13s a kill
            # row's edge jumped 44px in half a second, its own track lost it on
            # the tolerance, and a stale track sitting at the new value took it
            # instead. So a row still in the SAME PLACE a moment later is the
            # same row, whatever its left edge did.
            same_spot = (r.time - t["last"] <= SETTLE_GAP
                         and abs(t["y0"] - r.y0) <= JOIN_GAP)
            if abs(t["x0"] - r.x0) > X_TOL and not same_spot:
                continue
            if r.time - t["t0"] > MAX_LIFE:
                continue
            # ONE sighting per frame. Two rows on screen at once often sit at
            # nearly the same left edge, and without this the second joins the
            # first -- the y test below cannot stop it, because rows in the
            # same frame share a timestamp and it only fires on a later one.
            # That is how a row reading "other" and a row reading "kill" became
            # a single 10-10 track, and the tie was then broken into a kill
            # that never happened.
            if r.time == t["last"]:
                continue
            # A row does not turn from a kill into a death. Either can settle
            # out of "other" -- that just means the yellow was not found in
            # some frames -- but a definite kill joining a track holding a
            # definite death means the track has walked onto a different row.
            # FROM FOOTAGE: a track voting "kkkkkdd" was a kill followed by a
            # death, and the majority reported the death as a kill.
            if r.kind in ("kill", "death") and t["hard"] not in (None, r.kind):
                continue
            # Rows only ever move UP, as the rows above them expire. Something
            # at the same x that has moved DOWN is a different row that happens
            # to be the same width.
            if r.time > t["last"] and r.y0 > t["y0"] + JOIN_GAP:
                continue
            cands.append(t)

        # The BEST candidate, not the first that fits. When a row expires the
        # row below slides up into the slot it vacated, and if the two have
        # similar left edges a stale track will happily claim the newcomer.
        # FROM FOOTAGE at 1m43s: a track of four "other" sightings absorbed a
        # real kill that had just moved up one pitch, and so reported that kill
        # four seconds early -- early enough to cut the clip before it happened.
        #
        # Preferring the track whose settled verdict already matches, and then
        # the one seen most recently, resolves it: the kill's own track had been
        # seen in the previous frame, while the expiring row had not.
        if cands:
            t = max(cands, key=lambda t: (t["hard"] == r.kind, t["last"],
                                          -abs(t["x0"] - r.x0)))
            t["last"] = r.time
            t["y0"] = r.y0
            t["x0"] = r.x0
            t["kinds"].append(r.kind)
            t["victims"].append(r.victim)
            if r.kind in ("kill", "death"):
                t["hard"] = r.kind
        else:
            tracks.append({"t0": r.time, "last": r.time, "y0": r.y0,
                           "x0": r.x0, "kinds": [r.kind],
                           "victims": [r.victim],
                           "hard": r.kind if r.kind in ("kill", "death") else None})

    out: list[Event] = []
    for t in tracks:
        kinds = t["kinds"]
        if len(kinds) < min_seen:
            continue
        # "other" is the NULL HYPOTHESIS -- it is what a frame says when it
        # found no yellow -- so a verdict has to beat it outright, and a tie
        # means not clipping. Letting the player's own verdicts win a tie was
        # tried and it manufactured kills on rows they were not even on.
        #
        # An "assist" reading only counts when there is no hard verdict at all.
        # A row whose left edge wanders late in its life starts reporting the
        # player's own portrait as a detached tile, so a real kill came back
        # "kkkaaa" -- three strong kill frames at 571-687 yellow, then three
        # degraded ones -- and a plain plurality threw the kill away on the
        # 3-3 tie.
        n_other = kinds.count("other")
        hard = max(("kill", "death"), key=kinds.count)
        if kinds.count(hard) > n_other:
            kind = hard
        elif kinds.count("assist") > n_other:
            kind = "assist"
        else:
            kind = "other"
        # The victim side by majority over the sightings that read one at all.
        # Two single frames out of 202 disagreed with their own row; a majority
        # is what makes those cost nothing.
        said = [v for v in t["victims"] if v]
        victim = max(("mine", "enemy"), key=said.count) if said else ""
        out.append(Event(time=t["t0"], kind=kind, end=t["last"],
                         seen=len(kinds), x0=t["x0"], y0=t["y0"],
                         victim=victim,
                         votes="".join(k[0] for k in kinds)))
    out.sort(key=lambda e: e.time)
    return out


def tally(events: list[Event]) -> dict[str, int]:
    out = {"kill": 0, "death": 0, "assist": 0, "other": 0}
    for e in events:
        out[e.kind] = out.get(e.kind, 0) + 1
    return out


# Sampling at 2 fps finds THAT a row appeared, not WHEN -- and here the gap is
# much wider than the sampling interval, because a row SLIDES IN over a second
# or more and its geometry is nonsense while it does, so the animation frames
# are rejected on purpose (see EDGE_MARGIN) and the first accepted sighting can
# be seconds late.
#
# Measured against two clips the player checked by eye: reported 1216.5 when the
# row was really there from 1214.7, and reported 2090.5 against 2087.6 -- lags
# of 1.8s and 2.9s. A clip cut 1.5s before the REPORTED time therefore started
# after the kill had already happened, and a clip labelled "2 kills" showed one.
#
# So every kill gets a second, much cheaper look: re-scan the seconds before it
# at a higher rate and take the row's real first appearance. Only kills are
# refined, because only kills decide where a clip starts.
REFINE_FPS = 8.0
# Bounded at 4s ON PURPOSE. The lag being corrected is the slide-in animation
# plus detection flicker, and that measured 1.8-3.4s at worst. Given a longer
# window the walk chains onto the PREVIOUS kill's row -- both are on screen at
# once and their left edges are within tolerance of each other -- and one kill
# was dragged 5.6s back onto the one before it. Four seconds covers every real
# lag measured and cannot reach a neighbouring kill.
REFINE_LOOKBACK = 4.0
REFINE_X_TOL = 60     # px. Wider than X_TOL: over seconds the segment edge
                      # wanders further than it does frame to frame.
# How long the row may go undetected before the walk decides it has left the
# row behind. Measured gaps inside one row's life reach 0.6s; distinct kills in
# a burst sit seconds apart. Erring EARLY is the safe direction -- a clip that
# starts a moment too soon is untidy, one that starts too late misses the kill
# it is named after.
REFINE_MAX_GAP = 1.0
# Only the FIRST kill of a burst is refined. Two reasons, and they point the
# same way:
#
#   * Only the first kill decides where a clip STARTS, which is the entire
#     point of refining.
#   * A kill soon after another cannot be refined reliably anyway. Both rows
#     are on screen together and their left edges are within tolerance, so the
#     walk chains onto the earlier one -- one kill went back 5.6s onto its
#     predecessor. Worse, refining both onto the SAME instant collapses the
#     burst's span to zero, and the window built from it then stops before the
#     second kill: a clip labelled "2 kills" showed one, which is the bug this
#     whole pass exists to fix.
#
# 9s = the 4s look-back plus the ~5s a row stays on screen, so a predecessor
# outside it cannot still be visible anywhere the walk can reach.
REFINE_MIN_SPACING = 9.0


def refine(video: Path, band, events: list[Event], *, fps: float = REFINE_FPS,
           look_back: float = REFINE_LOOKBACK,
           frame_height: int = REF_HEIGHT,
           kinds: tuple[str, ...] = ("kill",),
           cancelled: Callable[[], bool] | None = None) -> list[Event]:
    """Move each kill's timestamp back to when its row actually appeared."""
    from PIL import Image

    from .killfeed import _extract

    todo = sorted(events, key=lambda x: x.time)
    prev_same_kind: dict[str, float] = {}
    for e in todo:
        if e.kind not in kinds:
            continue
        before = prev_same_kind.get(e.kind)
        prev_same_kind[e.kind] = e.time
        if before is not None and e.time - before < REFINE_MIN_SPACING:
            continue                   # not the first of its burst
        if cancelled and cancelled():
            break
        start = max(0.0, e.time - look_back)
        tmp = _extract(Path(video), band, start, e.time - start + 0.2, fps)
        try:
            seen: dict[float, bool] = {}
            for png in sorted(tmp.glob("f_*.png")):
                at = start + (int(png.stem.split("_")[1]) - 1) / fps
                a = np.asarray(Image.open(png).convert("RGB"))
                seen[round(at, 3)] = any(
                    r.kind == e.kind and abs(r.x0 - e.x0) <= REFINE_X_TOL
                    for r in read_frame(a, at, frame_height=frame_height))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # Walk BACKWARDS from the reported time through frames that still show
        # the row, tolerating a GAP IN TIME rather than a number of frames.
        # Detection flickers: the same row was found, lost for half a second,
        # and found again while plainly on screen the whole while, so a
        # one-frame tolerance stopped at once and moved nothing. Gaps within a
        # single row's life measured up to 0.6s.
        #
        # Taking the earliest hit anywhere in the window instead would jump to
        # an unrelated kill seconds earlier that happened to sit at a similar
        # left edge, which is why this walks rather than scans.
        times = sorted(seen)
        best, last_hit = e.time, e.time
        for at in reversed(times):
            if at > e.time:
                continue
            if seen[at]:
                best = last_hit = at
            elif last_hit - at > REFINE_MAX_GAP:
                break
        if best < e.time:
            e.end = max(e.end, e.time)
            e.time = best
    events.sort(key=lambda x: x.time)
    return events


def _span(args) -> list[Row]:
    # frame_height is the height of THIS recording, not the height the pixel
    # constants were measured at -- that is REF_HEIGHT, and read_frame scales
    # between the two.
    video, band, start, dur, fps, frame_h = args
    from PIL import Image

    from .killfeed import _extract

    out: list[Row] = []
    tmp = _extract(Path(video), band, start, dur, fps)
    try:
        for png in sorted(tmp.glob("f_*.png")):
            at = start + (int(png.stem.split("_")[1]) - 1) / fps
            a = np.asarray(Image.open(png).convert("RGB"))
            out.extend(read_frame(a, at, frame_height=frame_h))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def scan(video: Path, band, *, duration: float | None = None,
         fps: float = SAMPLE_FPS, chunk: float = 120.0,
         frame_height: int = REF_HEIGHT,
         progress: Callable[[int, int], None] | None = None,
         cancelled: Callable[[], bool] | None = None) -> list[Event]:
    """Read the whole recording's feed. -> events in time order.

    No OCR, so this is decode-bound rather than CPU-bound: a 46-minute
    recording scanned in 135s of wall clock, about 20x real time, against the
    3.5x the OCR path manages.
    """
    from .killfeed import _sweep_stale_temp
    from .tools import media_info

    total = duration if duration is not None else media_info(video)["duration"]
    _sweep_stale_temp()
    spans, t = [], 0.0
    while t < total:
        spans.append((t, min(chunk, total - t)))
        t += chunk

    seen: list[Row] = []
    if progress:
        progress(0, len(spans))
    for i, (at, dur) in enumerate(spans, 1):
        if cancelled and cancelled():
            break
        seen.extend(_span((video, band, at, dur, fps, frame_height)))
        if progress:
            progress(i, len(spans))

    # Collapsed only once every span is in, so a row straddling a chunk
    # boundary is one event rather than two.
    events = collapse(seen)
    # Then each kill's time is pulled back to when its row really appeared.
    # Cheap next to the scan, and it is what keeps the kill inside the clip
    # that gets cut around it.
    if not (cancelled and cancelled()):
        refine(video, band, events, frame_height=frame_height,
               cancelled=cancelled)
    t = tally(events)
    log.info("%s: %d kill(s), %d death(s), %d assist(s) read from the feed "
             "bars (%d sightings)", Path(video).name, t["kill"], t["death"],
             t["assist"], len(seen))
    return events
