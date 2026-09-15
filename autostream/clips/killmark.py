"""The game's own kill confirmation, read off the screen: when a kill really happened.

WHY THIS EXISTS
    Reels put every kill on a beat, and a kill that is on screen half a second
    before or after its beat reads as out of sync however exact the grid is.
    Reviewing a finished reel frame by frame showed exactly that: the Valorant
    feed reader's kill times, measured against the kill emblem the game draws
    at the bottom of the screen, were a median 0.30 s late (10th-90th
    percentile -0.15 to +0.77 s), and in 25 of 63 kills in one run no emblem
    appeared anywhere near the time at all -- one "double kill" clip held
    nothing but a walk down a corridor, its one real kill two seconds from
    where the feed reader put it.

HOW IT IS READ
    Valorant draws the emblem at a fixed place for every kill, but its design
    depends on the weapon skin: a skull, a spade, a lettermark. What every
    design shares is a ring centred on the same point. So the detector does
    not match a picture; it measures how much of the edge energy on circles
    around that centre points radially -- a property of rings, independent of
    colour and of what is drawn inside them. Measured on 38 clips: 0.08-0.28
    for the game world, 0.45-0.62 while an emblem is up, for all four designs
    in the run.

MEASURED ON A WHOLE RECORDING
    70 minutes, scored against Riot's own records for the four matches in it:
    76 kills outside the match the run already had a record for. The feed
    alone read 67 of them, placed a median 0.07 s early (p10-p90 -0.26 to
    +0.40), and 15 kills that never happened. The emblems read 74, a median
    0.05 s early (-0.14 to +0.07). But 19 emblems no feed kill claimed held
    only 8 of the player's kills: the rest were team-mates' kills watched
    while dead -- see spectating() -- plus a settings menu and one ring in the
    scenery. With the spectated ones left out: 74 read, 4 that were not
    kills, and two of those show SINGLE KILL on screen.

WHAT IT CANNOT SEE
    A second kill while the first kill's emblem is still up. The emblem is
    replaced rather than raised again, so there is no new onset, and it stays
    up no longer than a single kill's does (2.1 s either way): two kills
    0.5 s apart -- the start of a 1v4 clutch -- read as one. Those were 2 of
    the 76. The emblem does draw the kill's number in the round, as brackets
    either side of the ring, one more pair per kill; nothing reads them yet.

Games without an emblem have no spec here, and nothing changes for them.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("autostream.clips.killmark")


@dataclass(frozen=True)
class Spec:
    """Where a game draws its kill emblem, as fractions of a 16:9 frame."""
    x0: float
    x1: float
    y0: float
    y1: float
    cx: float = 0.5        # the emblem's centre, as fractions of the region
    cy: float = 0.55
    # Where the spectator card's left rule is drawn -- see spectating() -- as
    # (x0, x1, y0, y1), and the band just above it where the rule must NOT be.
    card: tuple[float, float, float, float] | None = None
    card_above: tuple[float, float] | None = None


SPECS = {
    "valorant": Spec(x0=0.455, x1=0.545, y0=0.705, y1=0.86,
                     card=(0.008, 0.026, 0.735, 0.81), card_above=(0.64, 0.71)),
}

REGION_WIDTH = 160
FPS = 30
# Score while an emblem is up, and the level the rise is traced back to.
ON = 0.36
BASE = 0.28
# An emblem stays up well over a second; a real one holds at least this long.
HOLD = 0.4
# Where a detected kill may sit relative to its emblem: the feed reader ran
# from 0.35 s early to 2.0 s late on the run it was measured on.
EARLY, LATE = 0.8, 2.2


def spec_for(game: str) -> Spec | None:
    g = (game or "").lower()
    for key, spec in SPECS.items():
        if key in g:
            return spec
    return None


def _region(video: Path, spec: Spec, ff: str, t0: float = 0.0, seconds: float = 0.0,
            fps: float = FPS, hwaccel: bool = False):
    import numpy as np
    from .killfeed import _NO_WINDOW

    h = int(round(REGION_WIDTH * (spec.y1 - spec.y0) * 9 / 16 / (spec.x1 - spec.x0)))
    args = [ff, "-v", "error"]
    if hwaccel:
        args += ["-hwaccel", "auto"]
    if t0 > 0:
        args += ["-ss", f"{t0:.3f}"]
    args += ["-i", str(video)]
    if seconds > 0:
        args += ["-t", f"{seconds:.3f}"]
    args += ["-vf", f"fps={fps:g},crop=iw*{spec.x1 - spec.x0:.4f}:ih*{spec.y1 - spec.y0:.4f}:"
                    f"iw*{spec.x0:.4f}:ih*{spec.y0:.4f},scale={REGION_WIDTH}:{h},format=gray",
             "-f", "rawvideo", "-"]
    raw = subprocess.run(args, capture_output=True, timeout=600, creationflags=_NO_WINDOW).stdout
    n = len(raw) // (REGION_WIDTH * h)
    return np.frombuffer(raw, np.uint8)[:n * REGION_WIDTH * h].reshape(n, h, REGION_WIDTH).astype(np.float32)


def ring_scores(frames, cx: float = 0.5, cy: float = 0.55):
    """Per frame: the share of points on circles about the emblem centre whose edge points radially."""
    import numpy as np

    if len(frames) == 0:
        return np.zeros(0)
    a = frames
    gx = np.zeros_like(a)
    gy = np.zeros_like(a)
    gx[:, 1:-1, 1:-1] = ((a[:, 1:-1, 2:] - a[:, 1:-1, :-2]) * 2 + (a[:, :-2, 2:] - a[:, :-2, :-2])
                         + (a[:, 2:, 2:] - a[:, 2:, :-2]))
    gy[:, 1:-1, 1:-1] = ((a[:, 2:, 1:-1] - a[:, :-2, 1:-1]) * 2 + (a[:, 2:, :-2] - a[:, :-2, :-2])
                         + (a[:, 2:, 2:] - a[:, :-2, 2:]))
    n, H, W = a.shape
    base = np.sqrt(gx ** 2 + gy ** 2).mean((1, 2)) + 1e-6
    ang = np.linspace(0, 2 * np.pi, 96, endpoint=False)
    cos, sin = np.cos(ang), np.sin(ang)
    best = np.zeros(n)
    for dx in (-3, 0, 3):
        for dy in (-3, 0, 3):
            x0, y0 = W * cx + dx, H * cy + dy
            for r in np.arange(0.22, 0.48, 0.02) * W:
                xs = np.clip((x0 + r * cos).astype(int), 0, W - 1)
                ys = np.clip((y0 + r * sin).astype(int), 0, H - 1)
                rad = np.abs(gx[:, ys, xs] * cos + gy[:, ys, xs] * sin)
                best = np.maximum(best, (rad > 2.0 * base[:, None]).mean(1))
    return best


def onsets(scores, fps: float = FPS) -> list[float]:
    """Seconds at which an emblem appears: the start of each rise that holds."""
    out: list[float] = []
    hold = max(1, int(HOLD * fps))
    i, n = 0, len(scores)
    while i < n:
        if scores[i] >= ON and all(scores[j] >= ON * 0.85 for j in range(i, min(n, i + hold))) and i + hold <= n:
            k = i
            while k > 0 and scores[k - 1] >= BASE and i - k < int(0.25 * fps):
                k -= 1
            out.append(round(k / fps, 3))
            while i < n and scores[i] >= ON * 0.85:
                i += 1
        else:
            i += 1
    return out


def marks(video: Path, game: str, ff: str = "ffmpeg") -> list[float] | None:
    """Emblem onsets in a clip, in its own seconds. None for a game without an emblem."""
    spec = spec_for(game)
    if spec is None:
        return None
    try:
        frames = _region(Path(video), spec, ff)
    except (OSError, subprocess.SubprocessError) as e:
        log.info("kill emblems not read in %s: %s", Path(video).name, e)
        return None
    return onsets(ring_scores(frames, spec.cx, spec.cy))


# The spectator card's rule, read at a fixed size whatever the recording's.
CARD_W, CARD_H = 46, 245
# Share of the card's rows the rule must light, in every frame read.
CARD_ON = 0.5
# After the emblem rises: when the card, if there is one, is certainly up.
CARD_AT = (0.3, 0.9)


def card_rule(frame, spec: Spec) -> tuple[float, float]:
    """(how much of the card's rule is lit, how much of the band above it is), for one frame.

    `frame` is the CARD_W x CARD_H grey crop spanning card_above[0] to card[3].
    A rule is a column brighter than the pixels three columns either side of
    it; the column is the one brightest over the card's rows.
    """
    import numpy as np

    a = frame.astype(np.float32)
    y_top = spec.card_above[0]
    span = spec.card[3] - y_top
    r0 = int(round((spec.card[2] - y_top) / span * CARD_H))
    a0, a1 = 0, int(round((spec.card_above[1] - y_top) / span * CARD_H))
    lead = np.minimum(a[:, 3:-3] - a[:, :-6], a[:, 3:-3] - a[:, 6:])
    col = int(np.argmax(np.median(lead[r0:], axis=0)))
    lit = lead[:, col] > 25
    return float(lit[r0:].mean()), float(lit[a0:a1].mean())


def spectating(video: Path, at: float, game: str, ff: str = "ffmpeg") -> bool | None:
    """Whether the player was watching a team-mate when an emblem rose at `at`. None if unknown.

    A DEAD PLAYER SEES THEIR TEAM-MATES' EMBLEMS. Once the player dies the game
    shows the round through a team-mate's eyes, emblems included. Measured on a
    70-minute recording against Riot's record: 19 emblems no feed kill
    claimed, 8 of them the player's own kills and 8 a team-mate's while the
    player spectated -- every one of those 8 under the card the game draws
    bottom-left (portrait, name, SWITCH PLAYER).

    The card is found by the thin bright rule down its left edge, not by its
    words, which are in the player's language. Across 108 emblems that rule
    lit 0.66-0.98 of its rows on all 8 spectated ones and 0 on 93 of the 95
    real kills; the two exceptions were a glow down the whole screen edge,
    which lights the band above the card too, and a flicker in one frame.
    """
    import numpy as np
    from .killfeed import _NO_WINDOW

    spec = spec_for(game)
    if spec is None or spec.card is None:
        return None
    x0, x1, _, y1 = spec.card
    y0 = spec.card_above[0]
    seen = []
    for d in CARD_AT:
        try:
            raw = subprocess.run(
                [ff, "-v", "error", "-ss", f"{max(0.0, at + d):.3f}", "-i", str(video),
                 "-frames:v", "1", "-vf",
                 f"crop=iw*{x1 - x0:.4f}:ih*{y1 - y0:.4f}:iw*{x0:.4f}:ih*{y0:.4f},"
                 f"scale={CARD_W}:{CARD_H},format=gray", "-f", "rawvideo", "-"],
                capture_output=True, timeout=60, creationflags=_NO_WINDOW).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        if len(raw) < CARD_W * CARD_H:
            return None
        seen.append(card_rule(np.frombuffer(raw[:CARD_W * CARD_H], np.uint8)
                              .reshape(CARD_H, CARD_W), spec))
    return all(rule >= CARD_ON and above < CARD_ON for rule, above in seen)


def match(kills: list[float], found: list[float]) -> tuple[dict[int, int], list[int]]:
    """Pair detected kills with emblems. -> ({kill index: emblem index}, unclaimed emblem indices)

    Each emblem takes the nearest unclaimed detected kill that lies no more
    than EARLY before or LATE after it.
    """
    pairs = sorted(((abs(k - m), i, j) for i, k in enumerate(kills) for j, m in enumerate(found)
                    if -EARLY <= k - m <= LATE))
    got: dict[int, int] = {}
    used: set[int] = set()
    for _, i, j in pairs:
        if i in got or j in used:
            continue
        got[i] = j
        used.add(j)
    return got, [j for j in range(len(found)) if j not in used]


def confirm(kills: list[float], found: list[float] | None,
            theirs=None) -> tuple[list[float], int, int]:
    """Kill times moved onto the emblems that confirm them. -> (kills, dropped, added)

    A kill no emblem claims is dropped; an emblem no kill claims is a kill the
    reader missed and is added -- unless `theirs(t)` says it rose while the
    player was spectating (see spectating()). With no emblem information at
    all (None) the kills stay as they are.

    AN EMBLEM-LESS CLIP IS A CLIP WITHOUT A KILL. The first version kept the
    kills of a clip in which no emblem showed, in case the HUD was hidden. The
    player checked two of those clips by eye: neither held a kill -- one was the
    player opening the map, the other the player dying. Whether the HUD is
    shown at all is judged over a whole run, by the caller, not per clip.
    """
    if found is None:
        return sorted(kills), 0, 0
    got, unclaimed = match(kills, found)
    if theirs is not None:
        unclaimed = [j for j in unclaimed if not theirs(found[j])]
    out = sorted([found[j] for j in got.values()] + [found[j] for j in unclaimed])
    return out, len(kills) - len(got), len(unclaimed)


def scan(video: Path, game: str, *, start: float = 0.0, duration: float = 0.0, ff: str = "ffmpeg",
         chunk: float = 30.0, workers: int = 4, fps: float = 15.0,
         progress=None, cancelled=None) -> list[float] | None:
    """Emblem onsets across a stretch of a recording, in the recording's seconds.

    15 fps is enough to find an emblem (it stays up 1.7-1.9 s) and to place its
    onset within a frame of the 30 fps reading, measured on 37 emblems.
    Decoding is the cost: a 70-minute 1440p120 recording took 7 minutes with
    four decoders. None for a game without an emblem.
    """
    from concurrent.futures import ThreadPoolExecutor

    spec = spec_for(game)
    if spec is None or duration <= 0:
        return None
    starts = []
    t = start
    while t < start + duration - 0.05:
        starts.append(t)
        t += chunk
    done = [0]

    def one(t0: float) -> list[float]:
        if cancelled and cancelled():
            return []
        # A second of overlap so an emblem rising across a chunk boundary is
        # seen rising in one of them; duplicates are merged below.
        frames = _region(Path(video), spec, ff, t0=t0, seconds=min(chunk + 1.0, start + duration - t0),
                         fps=fps, hwaccel=True)
        got = [round(t0 + o, 3) for o in onsets(ring_scores(frames, spec.cx, spec.cy), fps)]
        done[0] += 1
        if progress:
            progress(done[0], len(starts))
        return got

    with ThreadPoolExecutor(max_workers=workers) as pool:
        found = sorted(o for part in pool.map(one, starts) for o in part)
    merged: list[float] = []
    for o in found:
        if not merged or o - merged[-1] > 0.6:
            merged.append(o)
    return merged
