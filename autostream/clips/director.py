"""Follow the song: a reel planned part by part, each clip used for what it is.

WHY THIS EXISTS. Every arrangement before this one put kills on hits and the
clips in an order, and that was all: the same ramp and freeze on every shot,
a clutch's three kills cut apart and dealt round the reel, and nothing that
changed when the song did. Told plainly what was wanted -- "the build-up is
good, but after the drop the reel is fast, so the style should have switched";
"use the clips consciously: ace, clutch and multi kills for the set-up, and the
single headshot kills more thoughtfully" -- and asked to direct it, ChatGPT
gave the rules this module is (projects/batch12/tempo/plan.md):

* THE SET-UP IS ONE TAKE. The best clutch, ace or multi-kill plays unbroken
  through the build, at real speed, and its LAST kill lands exactly on the
  drop. Its earlier kills fall where the fight put them -- that is the tension.
* AFTER THE DROP THE REEL CUTS ON THE DRUMS. Kill targets are the song's own
  hits (clips/rhythm.py), scored S = 0.45 kick + 0.30 snare + 0.10 hats + 0.15
  on-the-beat, about half a second apart (0.46-0.55 s; 0.69 s for the strong
  ones), never two awkward kills where one strong one will do.
* DOUBLES ARE RUNS. A two-kill clip whose kills can meet two targets inside
  0.75-1.6x plays as one shot that hits both, so the flurry is multi-kills cut
  fast rather than one kill after another.
* A HEADSHOT IS CHOSEN, NOT DEALT. Single kills go to the targets by quality --
  read as a headshot first -- the strongest on the strongest hits and the last
  one; a single kill that is not a headshot goes in only when nothing better is
  left.
* EVERY SHOT ENDS WHERE THE NEXT ONE'S RUN-UP BEGINS. With impacts t_i and
  run-ups p_i, shot i lasts (t_{i+1} - t_i) + p_i - p_{i+1}; p is 0.13-0.18 s
  on the fast cuts and 0.17-0.23 s on the strong ones.
* ONE PRIMARY EFFECT PER KILL, never the same twice running; hard cuts.

Pure planning, no ffmpeg: the shots it returns are ordinary Studio shots, so
the timeline edits, re-times and renders them like any other reel.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

BURST_GAP = 6.0            # s: kills further apart than this in a clip are separate fights
SAME_KILL = 0.10           # s: kills closer than this are one kill, read twice
# The take's first kill comes within 1.8 s: reviewed (ChatGPT, v1.79.8), a first kill at
# 2.35 s "leaves almost the entire hook window waiting for its payoff"; its general rule is
# the first compelling action inside 2 s.
TAKE_LEAD = (0.8, 1.8)     # s of the take before its first kill: at least, at most
TAKE_MAX = 14.0            # s: a set-up longer than this is cut down to its last kills
# THE WHOLE ROUND, WITH THE WAITING CUT OUT. An ACE chosen to build on played three
# of its five kills: the fourth came 13 s after the third, past BURST_GAP, so the
# round was split in two and the take was the first half. A chosen clip, or one
# named ACE or CLUTCH, is one round; where it waits longer than JUMP_GAP between
# kills the take jumps, keeping JUMP_AFTER of the one kill and JUMP_BEFORE of the next.
# A wait over 3 s is jumped too: reviewed, a 3.5 s gap between a take's kills "holds the
# same composition for a long time" -- its general rule, a build gap over 3 s gets a trim.
JUMP_GAP = 3.0
JUMP_AFTER = 1.0
JUMP_BEFORE = 1.4
SETUP_MIN_KILLS = 3        # ...or two, with a clutch / ace / last-alive name on it
PAIR_RATE = (0.75, 1.6)    # how far a double may be sped or slowed to meet two hits
PAIR_TOGETHER = 0.30       # s: closer than this, a double's kills share one hit
FAST_PRE = 0.15            # run-up of a fast cut
ANCHOR_PRE = 0.20          # ...and of a strong one
GAP_PREF = 0.52            # s: the flurry's gap, as near as the beat allows
GAP_RANGE = (0.42, 0.75)
# THE DROP'S KILL IS HELD, BUT NOT FOR A BAR. The first cut left 1.34 s after it on
# That Acid -- reviewed: it "costs momentum" on a drop that is already driving.
# The next kill comes 1.3-1.6 gaps on (0.67-1.0 s at 174 BPM), and no later than
# MAX_GAP unless one gap is longer than that.
DROP_HOLD = (1.3, 1.6)
MAX_GAP = 1.0              # s: no two kills after the drop further apart, a double's own two included
# AN ANCHOR EVERY FEW KILLS. Reviewed on Lalala (ChatGPT, 2026-10-22): a nearly uniform
# 0.46 s after the drop "becomes predictable over a long section". After every 4-6
# fast kills the run takes one longer step onto a strong hit -- the accent a hand edit
# gives a phrase -- and is nudged to (not forced) by the sixth. IN BEATS, NOT SECONDS
# (the second review): from 1.3 gaps to two beats, or 1.75 gaps where that is longer --
# 0.60-0.92 s at 130 BPM, 0.85-1.30 at 92 -- and only onto a hit at the 70th percentile
# or above of the hits within a bar of it.
ANCHOR_GAPS = (1.3, 1.75)
ANCHOR_BEATS = 2.0
ANCHOR_STRONG = 0.70
ANCHOR_EVERY = (4, 6)
ANCHOR_LATE = 0.25          # cost of each fast kill past the sixth without one
TAIL = 1.2                 # s the last kill is held for: OUTRO_FADE after it, then the fade
END_AFTER = 0.9            # s: the least the reel runs on after its last kill before the bar line it ends on
OUTRO_FADE = 0.6           # s: the ending's fade, which never starts before TAIL - OUTRO_FADE after the last kill
REEL_SECONDS = 28.0        # how long a reel runs when nothing else says
WEIGHTS = {"kick": 0.45, "snare": 0.30, "hats": 0.10, "grid": 0.15}
ON_BEAT = 0.025            # s: a cue this near a beat is on it
# NOTHING THAT BLURS OR WHITES OUT THE KILL ITSELF. The first cut rotated
# punch+blur (k21) in, and its gaussian blur covered the whole picture for the
# seven frames of the kill at 21.2 s; an inversion every 5 s turned the kill at
# 17.4 s into a white frame. Both read in review as the footage failing. A zoom
# punch or a shake leaves the hit visible; the inversion is kept for one moment.
FX_CYCLE = ("k01", "k02", "", "k01", "", "k02")         # zoom punch, shake, none
INVERT = "k12"
# Not "KILLS": every multi-kill file is named N-KILLS, so it made each double a
# set-up, and a reel from 48 clips built on a double with an ACE left unused.
BIG_WORDS = ("CLUTCH", "LAST-ALIVE", "LAST ALIVE", "1V", "ACE")


@dataclass
class Burst:
    clip: dict
    kills: list[float]
    hs: list[bool]

    @property
    def span(self) -> float:
        return self.kills[-1] - self.kills[0]

    @property
    def path(self) -> str:
        return str(self.clip["path"])

    @property
    def seconds(self) -> float:
        return float(self.clip.get("duration") or 0.0)

    def big(self) -> bool:
        text = " ".join([str(self.clip.get("name") or ""), *[str(x) for x in self.clip.get("labels") or []]]).upper()
        return any(w in text for w in BIG_WORDS)


@dataclass
class Plan:
    part: tuple[float, float]
    drop: float
    shots: list[dict]
    marks: list[float]                 # each shot's kill, song seconds
    kills: list[float] = field(default_factory=list)   # every kill shown, song seconds
    notes: list[str] = field(default_factory=list)


def bursts(clip: dict) -> list[Burst]:
    """A clip's kills split into fights."""
    ks = [float(k) for k in clip.get("kills") or []]
    hs = list(clip.get("hs") or [])
    hs = [bool(h) for h in hs] + [False] * (len(ks) - len(hs))
    out: list[Burst] = []
    for k, h in sorted(zip(ks, hs)):
        # ONE KILL READ TWICE IS ONE KILL. A 1v4's first kill was in the clip at 3.415 and
        # 3.417 s -- two readings of it -- and the take cut a shot two milliseconds long
        # between them and called the clutch four kills. Nobody kills twice in SAME_KILL.
        if out and k - out[-1].kills[-1] < SAME_KILL:
            out[-1].hs[-1] = out[-1].hs[-1] or h
            continue
        if out and k - out[-1].kills[-1] <= BURST_GAP:
            out[-1].kills.append(k)
            out[-1].hs.append(h)
        else:
            out.append(Burst(clip, [k], [h]))
    return out


def setup_score(b: Burst) -> float:
    return len(b.kills) * 2.0 + (3.0 if b.big() else 0.0) + 0.5 * sum(b.hs) - 0.15 * max(0.0, take_span(b.kills) - 8.0)


def single_score(b: Burst) -> float:
    labels = " ".join(str(x) for x in b.clip.get("labels") or []).upper()
    return 1.0 + (1.5 if b.hs[0] else 0.0) + (0.4 if any(w in labels for w in ("CLOSER", "FLAWLESS", "LAST")) else 0.0)


# A ROUND HAS AT MOST FIVE ENEMIES. A Valorant fight with more kills than that is not one
# round -- it is a Deathmatch run, or rounds run together -- so it is no clutch or ace,
# whatever the mode record says or fails to say. A clip from a mode with no rounds
# (`respawn`, from the match record) is no build either.
ROUND_KILLS = {"VALORANT": 5}


def round_based(clip: dict, kills: int) -> bool:
    if clip.get("respawn"):
        return False
    cap = next((n for g, n in ROUND_KILLS.items() if g in str(clip.get("game") or clip.get("name") or "").upper()), None)
    if cap is None:
        return True
    # a clip cut from no one round holds the run its fights were split from: 12 kills in two
    # minutes split into fights of three is still a Deathmatch run, not three clutches
    whole = len(clip.get("kills") or []) if clip.get("round") is None else 0
    return max(kills, whole) <= cap


def is_setup(b: Burst) -> bool:
    if not round_based(b.clip, len(b.kills)):
        return False
    return len(b.kills) >= SETUP_MIN_KILLS or (len(b.kills) >= 2 and b.big() and b.span > 1.0)


def can_build(clips: list[dict], build: str = "") -> bool:
    """Whether these clips give Build and drop a take: a set-up fight, a round, or the chosen clip."""
    for c in clips:
        if any(is_setup(b) for b in bursts(c)):
            return True
        r = round_of(c)
        if r is not None and (is_setup(r) or (build and r.path.lower() == str(build).lower()
                                               and round_based(c, len(r.kills)))):
            return True
    return False


# ------------------------------------------------------------------ the song

def preferred_gap(beat: float) -> float:
    """The half-beat multiple nearest GAP_PREF inside GAP_RANGE (the beat itself if none)."""
    if beat <= 0:
        return GAP_PREF
    cands = [k * beat / 2 for k in range(1, 9) if GAP_RANGE[0] <= k * beat / 2 <= GAP_RANGE[1]]
    return min(cands, key=lambda g: abs(g - GAP_PREF)) if cands else beat


def cue_scores(rhythm, beats: list[float]) -> list[tuple[float, float]]:
    """(time, S) for every cue: the layers weighted, plus a share for sitting on a beat."""
    b = np.asarray(beats or [0.0])
    out = []
    for c in rhythm.cues:
        t = float(c["t"])
        on = float(np.min(np.abs(b - t))) <= ON_BEAT
        s = (WEIGHTS["kick"] * c.get("kick", 0.0) + WEIGHTS["snare"] * c.get("snare", 0.0)
             + WEIGHTS["hats"] * c.get("hats", 0.0) + (WEIGHTS["grid"] if on else 0.0))
        out.append((t, s))
    return out


def targets(cues: list[tuple[float, float]], drop: float, end: float, gap: float,
            first_max: float = 1e9, beat: float | None = None) -> list[float]:
    """The kill targets after the drop: the best-scoring run of cues about `gap` apart.

    A longest-path over the cues, each step 0.8-1.6 gaps long and costed by
    how far it is from one gap, so the run keeps the pace and takes the
    strong hits, and an occasional longer step (an anchor) is allowed where a
    strong hit is worth waiting for. The first step after the drop is at least
    DROP_HOLD gaps: the drop's kill is held -- for as long as the set-up's clip
    has footage after it (`first_max`), and no less than one gap.
    """
    first = (DROP_HOLD[0] * gap, max(MAX_GAP, DROP_HOLD[1] * gap))
    if first_max < first[1]:
        first = (min(first[0], max(0.8 * gap, first_max - 0.3 * gap)), first_max)
    got = _run(cues, drop, end, gap, first, 1.6, beat)
    if not got:
        # NO HIT IN THE HOLD'S WINDOW. Notorious's first cue after its drop came
        # 0.66 s on, 4 ms before the window opened, and the next was 1.36 s on:
        # the run never started and the take played on for twenty seconds. A
        # wider first step, and longer steps where the song leaves a hole,
        # rather than no flurry at all.
        got = _run(cues, drop, end, gap, (0.9 * gap, max(first[1], 2.5 * gap)), 2.0, beat)
    return got


def _run(cues, drop: float, end: float, gap: float, first: tuple[float, float], longest: float,
         beat: float | None = None) -> list[float]:
    """The best run of targets, counting the fast kills since the last anchor (see ANCHOR).

    The state is (cue, kills since the drop or the last anchor): an anchor step --
    ANCHOR long and at least 1.3 gaps -- resets it once it has reached ANCHOR_EVERY[0],
    and every fast kill past ANCHOR_EVERY[1] costs ANCHOR_LATE, so the run takes an
    anchor where the song has a hit for one and keeps the pace where it has not."""
    pts = [(t, s) for t, s in cues if drop + first[0] <= t <= end]
    if not pts:
        return []
    T = np.array([drop] + [t for t, _ in pts])
    S = np.array([0.0] + [s for _, s in pts])
    n, C = len(T), ANCHOR_EVERY[1] + 1
    beat = beat or gap
    a_lo = ANCHOR_GAPS[0] * gap
    a_hi = max(ANCHOR_BEATS * beat, ANCHOR_GAPS[1] * gap)
    # a hit strong enough to anchor on: at the ANCHOR_STRONG percentile of those within a bar
    strong = np.array([S[k] >= np.quantile(S[1:][np.abs(T[1:] - T[k]) <= 2 * beat], ANCHOR_STRONG) - 1e-9
                       if k else False for k in range(len(T))])
    reach = max(longest * gap, a_hi)
    best = np.full((n, C), -np.inf)
    prev = np.full((n, C, 2), -1, int)
    best[0, 0] = 0.0
    for j in range(1, n):
        for i in range(j - 1, -1, -1):
            d = T[j] - T[i]
            if i > 0 and d > reach + 1e-9:
                continue                      # too far back; the drop itself may still reach
            for c in range(C):
                if best[i, c] == -np.inf:
                    continue
                if i == 0:
                    if not (first[0] <= d <= first[1]):
                        continue
                    nc, cost = 0, 0.0          # the drop's hold is the first accent
                elif c >= ANCHOR_EVERY[0] and a_lo <= d <= a_hi and strong[j]:
                    nc, cost = 0, 0.0          # an anchor, where it is due
                elif 0.8 * gap <= d <= longest * gap:
                    nc = min(c + 1, C - 1)
                    cost = (0.35 * abs(d - gap) / gap + (0.15 if d > 1.25 * gap else 0.0)
                            + (0.6 if d > 1.6 * gap else 0.0) + (ANCHOR_LATE if c + 1 > ANCHOR_EVERY[1] else 0.0))
                else:
                    continue
                v = best[i, c] + S[j] - cost
                if v > best[j, nc]:
                    best[j, nc] = v
                    prev[j, nc] = (i, c)
    # the path that ends latest among the good ones: a run that stops early wastes the part
    ends = [(j, c) for j in range(1, n) for c in range(C) if best[j, c] > -np.inf]
    if not ends:
        return []
    last_t = max(T[j] for j, _ in ends)
    j, c = max(((j, c) for j, c in ends if T[j] >= last_t - 2 * gap), key=lambda jc: best[jc])
    path = []
    while j > 0:
        path.append(float(T[j]))
        j, c = (int(x) for x in prev[j, c])
    return path[::-1]


def choose_drop(shape, rhythm, part: tuple[float, float] | None, need_before: float, need_after: float) -> float | None:
    """The drop the set-up lands on: inside the part when one was chosen, else the song's own."""
    drops = sorted(set([float(d) for d in (getattr(shape, "drops", None) or [])]
                       + ([float(shape.drop)] if getattr(shape, "drop", None) else [])))
    secs = [s for s in rhythm.sections if s.kind == "drop"]
    lo, hi = (part if part else (0.0, float(shape.seconds)))
    ok = [d for d in drops if lo + need_before <= d <= hi - need_after]
    if not ok:
        return None
    if part:
        return ok[0]
    # the drop that opens the loudest drop section; the song's own biggest on a tie

    def loud(d):
        s = next((s for s in secs if abs(s.start - d) <= 4 * shape.beat), None)
        return (s.energy if s else 0.0) + (0.05 if getattr(shape, "drop", None) and abs(d - shape.drop) < 0.1 else 0.0)
    return max(ok, key=loud)


# ------------------------------------------------------------------ the shots

def _shot(b: Burst, kill: float, kills: list[float], pre: float, duration: float, *, fx: list[str],
          anchors: list | None = None) -> dict:
    c = b.clip
    s = {"clip": b.path, "clip_id": str(c.get("id") or ""), "name": str(c.get("name") or Path(b.path).stem),
         "clip_seconds": round(b.seconds, 3), "kills": [round(k, 3) for k in kills], "kill": round(kill, 3),
         "duration": round(duration, 5), "pre": round(pre, 5), "speed": "s00", "fx": fx, "hero": False,
         "lead_in": False, "hero_fx": [], "camera": "c00", "transition": "t01", "tlen": 0.0, "caption": ""}
    if anchors:
        s["anchors"] = [[round(src, 4), round(o, 4)] for src, o in anchors]
    return s


def take_kills(b: Burst) -> list[float]:
    """The kills a set-up plays: all of them, or its last ones when that is too long a take."""
    ks = list(b.kills)
    while len(ks) > 2 and take_span(ks) > TAKE_MAX:
        ks = ks[1:]
    return ks


def gap_on_screen(a: float, c: float) -> float:
    """How long the take shows between two of its kills: all of it, or the jump's two ends."""
    return c - a if c - a <= JUMP_GAP else JUMP_AFTER + JUMP_BEFORE


def take_span(ks: list[float]) -> float:
    """First kill to last as the take shows it, the waits jumped."""
    return sum(gap_on_screen(a, c) for a, c in zip(ks, ks[1:]))


def round_of(clip: dict) -> Burst | None:
    """Every kill of a clip as one fight -- the round a chosen or ACE / CLUTCH clip is."""
    whole = bursts(clip)
    if len(whole) < 2:
        return None
    return Burst(clip, [k for f in whole for k in f.kills], [h for f in whole for h in f.hs])


def take_start(D: float, span: float, room: float, beats: list[float], downbeats: set[int]) -> float:
    """Where in the song the take begins: on a bar line if its lead allows, else a beat.

    The lead before the first kill may be anything from TAKE_LEAD[0] to as much
    footage as the clip has (at most TAKE_LEAD[1]); within that the start is
    put where the music starts something.
    """
    lo = D - span - min(TAKE_LEAD[1], room)
    hi = D - span - TAKE_LEAD[0]
    if hi < lo:
        return max(0.0, D - span - room)
    inside = [(i, b) for i, b in enumerate(beats) if lo - 1e-6 <= b <= hi + 1e-6]
    bars = [b for i, b in inside if i in downbeats]
    if bars:
        return max(0.0, min(bars))
    if inside:
        return max(0.0, inside[0][1])
    return max(0.0, lo)


def take(b: Burst, drop_reel: float, lead_range: tuple[float, float] = TAKE_LEAD) -> tuple[list[dict], float]:
    """The set-up as consecutive shots of one clip, its last kill at `drop_reel`.

    -> (shots, how far into the reel the take starts). One shot per kill, cut
    halfway between kills: the footage runs on across every cut, so it plays
    as one take, and each kill is still a shot of its own to give an effect or
    move by hand.
    """
    ks = take_kills(b)
    span = take_span(ks)
    lead = min(lead_range[1], max(lead_range[0], drop_reel - span), ks[0] - 0.05)
    start_src = ks[0] - lead
    begin = max(0.0, drop_reel - (span + lead))
    # each kill's shot: from halfway after the last kill, or the jump's far end, to the same before the next
    ins, outs = [start_src], []
    for a, c in zip(ks, ks[1:]):
        if c - a <= JUMP_GAP:
            outs.append((a + c) / 2)
            ins.append((a + c) / 2)
        else:
            outs.append(a + JUMP_AFTER)
            ins.append(c - JUMP_BEFORE)
    outs.append(None)
    shots = [{"k": k, "a": ins[j], "b": outs[j]} for j, k in enumerate(ks)]
    out = []
    for s in shots:
        out.append(_shot(b, s["k"], [s["k"]], s["k"] - s["a"], 0.0, fx=[]))
        out[-1]["_src"] = (s["a"], s["b"])
    return out, begin


FILLS = 0.85    # a loose part's plan this share of its length or more is full enough (feasible.SHORT_BY)


def _length(p: Plan) -> float:
    return sum(float(s["duration"]) for s in p.shots)


def plan(clips: list[dict], shape, rhythm, *, part: tuple[float, float] | None = None,
         seconds: float = REEL_SECONDS, seed: int = 0, build: str = "", loose: bool = False) -> Plan:
    """`_plan`, and where the page drew the part itself, the drop its plan can fill.

    THE PART WE PICK IS ONE OUR OWN PLAN CAN FILL. On JUST A BOY the page drew 30 s
    round the first drop (0:18.1); the build take covered 4.5 s before it and the song's
    hits after it stopped at 0:34.8, so every plan was 21 s, whatever was chosen, and
    the guide said "about 16 more quick kills" (2026-10-24). A part the player drew is
    theirs and is planned as drawn; a loose one is only a length and a place to start
    looking, so the song's other drops are tried, the same part moved with each, and
    the first that fills it -- else the longest -- is the reel.
    """
    first = None
    try:
        first = _plan(clips, shape, rhythm, part=part, seconds=seconds, seed=seed, build=build, loose=loose)
    except ValueError:
        if not (part and loose):
            raise
    if not (part and loose):
        return first
    want = float(part[1]) - float(part[0])
    if first is not None and _length(first) >= want * FILLS:
        return first
    here = first.drop if first is not None else float(part[0])
    drops = sorted(set([float(d) for d in (getattr(shape, "drops", None) or [])]
                       + ([float(shape.drop)] if getattr(shape, "drop", None) else [])))
    best = first
    for d in sorted(drops, key=lambda d: (abs(d - here), d)):
        if first is not None and abs(d - first.drop) < 0.05:
            continue
        lead = (first.drop - float(part[0])) if first is not None else want / 2
        lo = max(0.0, d - lead)
        moved = (lo, min(float(shape.seconds), lo + want))
        try:
            got = _plan(clips, shape, rhythm, part=moved, seconds=seconds, seed=seed, build=build, loose=True)
        except ValueError:
            continue
        if best is None or _length(got) > _length(best) + 0.5:
            best = got
        if _length(got) >= want * FILLS:
            break
    if best is None:
        raise ValueError("No drop in this song has room for a build before it.")
    if best is not first:
        best.notes.append(f"Planned round the drop at {best.drop:.1f} s: the part drawn round "
                          + (f"{first.drop:.1f} s made only {_length(first):.0f} s of reel."
                             if first is not None else "the first drop had no room for this build."))
    return best


def _plan(clips: list[dict], shape, rhythm, *, part: tuple[float, float] | None = None,
          seconds: float = REEL_SECONDS, seed: int = 0, build: str = "", loose: bool = False) -> Plan:
    """Shots for a reel that builds on its best set-up into the drop, then cuts on the drums.

    `build` is the clip the player chose to build on: its best fight is the
    take whenever it has two kills or more, whatever the scores say.

    `loose`: the part is the page's default, not the player's choice -- it
    says where to look for the drop and how long the reel is, not where it
    must end. Drawn with room for any build, it started 9 s before an ACE's
    take did, and a 30 s part made a 22 s reel."""
    rng = random.Random(seed)
    all_b = [b for c in clips for b in bursts(c)]
    clips_by_path = {str(c["path"]): c for c in clips}
    setups = sorted((b for b in all_b if is_setup(b)), key=setup_score, reverse=True)
    notes: list[str] = []
    rounds = [r for c in clips if (r := round_of(c)) is not None
              and (r.big() or (build and r.path.lower() == str(build).lower()))]
    setups = sorted(setups + [r for r in rounds if is_setup(r)], key=setup_score, reverse=True)
    theirs = sorted((b for b in all_b + rounds if build and b.path.lower() == str(build).lower()
                     and len(b.kills) >= 2 and round_based(b.clip, len(b.kills))), key=setup_score, reverse=True)
    if build and not theirs:
        notes.append(f"The clip chosen to build on has no two kills together, so the reel builds on "
                     f"{'the best one among the rest' if setups else 'nothing'} instead.")
    if not setups and not theirs:
        raise ValueError("None of these clips has a clutch, an ace or three kills together "
                         "to build into the drop with. Choose one that has.")
    gap = preferred_gap(shape.beat)
    # the best set-up -- or, between ones within a point of it, the seed's: "Mix them up"
    # and a rebuild should not open every reel on the same clutch
    if theirs:
        best = theirs[0]
        if best not in setups:
            setups.insert(0, best)
    else:
        close = [b for b in setups if setup_score(b) >= setup_score(setups[0]) - 1.0]
        best = close[rng.randrange(len(close))] if seed else setups[0]
    ks = take_kills(best)
    span = take_span(ks)
    D = choose_drop(shape, rhythm, part, need_before=span + TAKE_LEAD[0], need_after=4 * gap)
    if D is None:
        raise ValueError("This part of the song has no drop with room for a build before it.")
    # the part: the take's length before the drop, and on until the reel is long enough
    downbeats = {i for i in range(len(shape.beats)) if i % 4 == getattr(shape, "downbeat_pos", 0)}
    start = take_start(D, span, ks[0] - 0.05, list(shape.beats), downbeats)
    if part:
        start = max(start, float(part[0]))
    end_cap = float(part[1]) if part else float(shape.seconds)
    if part and loose:
        end_cap = min(float(shape.seconds), start + float(part[1]) - float(part[0]))
    end = min(end_cap, start + max(seconds, float(part[1]) - float(part[0]) if part and loose else 0.0))
    drop_sec = next((s for s in rhythm.sections if s.kind == "drop" and s.start - 0.2 <= D < s.end), None)
    if drop_sec and not part:
        end = min(end, max(drop_sec.end, D + 6.0))
    take_shots, begin = take(best, D - start)
    if begin > 1e-3:
        start += begin                     # the take could not reach back that far
    jumped = sum(c - a - JUMP_AFTER - JUMP_BEFORE for a, c in zip(ks, ks[1:]) if c - a > JUMP_GAP)
    notes.append(f"Builds on {best.clip.get('name')} ({len(ks)} kills in one take"
                 + (f", {jumped:.0f} s of waiting between them cut out" if jumped > 0.5 else "")
                 + f"), its last kill on the drop at {D:.1f} s.")

    return _after(all_b, clips_by_path, setups, best, ks, take_shots, D, start, end, gap, rng, notes,
                  shape, rhythm)


def _after(all_b, clips_by_path, setups, best, ks, take_shots, D, start, end, gap, rng, notes,
           shape, rhythm, fast_pre=FAST_PRE, anchor_pre=ANCHOR_PRE) -> Plan:
    """From the take's last kill on: the targets on the drums, who hits them, and the shots.

    Shared by Build and drop (after its take) and Montage (after its held opening);
    `fast_pre` and `anchor_pre` are the run-ups of the fast and the strong cuts."""
    # ---- after the drop: targets, then who hits them
    cues = cue_scores(rhythm, list(shape.beats))
    T = targets(cues, D, end - TAIL, gap, first_max=best.seconds - ks[-1] - 0.02 + fast_pre, beat=shape.beat)
    if not T:
        raise ValueError("The song has no drum hits after this drop to cut the kills to.")
    used = {id(best)}
    # ONE CLIP, ONE PLACE. Ids kept two kills of one file apart -- the same
    # LAST-ALIVE clip played at 17.4 s and again at 21.2 s. By path, it cannot.
    paths = {best.path}
    rest = [b for b in all_b if b.path != best.path]          # the take's clip is the take's
    pairs = [b for b in rest if len(b.kills) == 2]
    # A DOUBLE IS ALSO TWO SINGLES. Only lone kills could fill a hit, so a choice of
    # mostly 2-KILLS clips whose kills are too far apart to be a run ran out of
    # singles and ended the reel early. Each kill of a fight can be one, as long
    # as the fight's other kills stay out of its shot (see fits).
    singles = sorted([b for b in rest if len(b.kills) == 1]
                     + [Burst(b.clip, [k], [h]) for b in rest if len(b.kills) > 1 for k, h in zip(b.kills, b.hs)],
                     key=lambda b: (single_score(b), rng.random()), reverse=True)
    others = [b for b in setups if b.path != best.path]   # spare set-ups: their last two kills can be a run
    strength = dict(cues)

    def fits(b: Burst, kill: float, pre: float, after: float) -> bool:
        if not (kill - pre >= 0.02 and kill + after <= b.seconds - 0.02):
            return False
        if len(b.kills) == 1:              # a lone kill's shot shows no other kill, off its beat
            return not any(kill - pre - 0.05 < float(k) < kill + after + 0.05 and abs(float(k) - kill) > 1e-6
                           for k in b.clip.get("kills") or [])
        return True

    def after(j: int) -> float:
        """Footage a kill on target j must have after it: up to the next shot's run-up."""
        return (T[j + 1] - T[j] - fast_pre) if j + 1 < len(T) else TAIL

    flurry: list[tuple[Burst, list[float], list[float]]] = []    # (burst, kills used, targets)
    last_path = best.path
    j = 0
    pair_room = 1                      # a run every few targets, not every one
    while j < len(T):
        t = T[j]
        placed = False
        if pair_room <= 0 and j + 1 < len(T):
            for b in pairs + others:
                if id(b) in used or b.path in paths:
                    continue
                k0, k1 = b.kills[-2], b.kills[-1]
                sg = k1 - k0
                for step in (1, 2):
                    if j + step >= len(T):
                        continue
                    og = T[j + step] - t
                    rate = sg / og
                    if og > max(MAX_GAP, 1.6 * gap) + 1e-6:
                        continue
                    if sg >= PAIR_TOGETHER and PAIR_RATE[0] <= rate <= PAIR_RATE[1] \
                            and fits(b, k0, anchor_pre * rate, sg + after(j + step) * rate):
                        flurry.append((b, [k0, k1], [t, T[j + step]]))
                        used.add(id(b))
                        paths.add(b.path)
                        last_path = b.path
                        j += step + 1
                        placed = True
                        pair_room = 2 + rng.randint(0, 1)
                        break
                if placed:
                    break
        if placed:
            continue
        pick = next((b for b in singles if b.path not in paths
                     and fits(b, b.kills[0], anchor_pre, after(j))), None)
        if pick is None:
            pick = next((b for b in singles if b.path not in paths
                         and fits(b, b.kills[0], fast_pre, after(j))), None)
        if pick is None:
            break                          # out of clips: the reel ends here
        flurry.append((pick, [pick.kills[0]], [t]))
        used.add(id(pick))
        paths.add(pick.path)
        last_path = pick.path
        pair_room -= 1
        j += 1
    if j < len(T):
        notes.append(f"The clips ran out {len(T) - j} hits before the end of the part; "
                     f"the reel ends on the last one they reach.")

    # ---- the strongest singles on the strongest hits: swap so quality follows the music
    single_idx = [i for i, (b, ks, ts) in enumerate(flurry) if len(ks) == 1]
    pool = sorted((flurry[i][0] for i in single_idx), key=single_score, reverse=True)
    by_hit = sorted(single_idx, key=lambda i: (i == (len(flurry) - 1), strength.get(flurry[i][2][0], 0.0)),
                    reverse=True)
    tj = {t: j for j, t in enumerate(T)}
    for i in by_hit:
        t = flurry[i][2][0]
        near = {flurry[n][0].path for n in (i - 1, i + 1) if 0 <= n < len(flurry)}
        b = next((b for b in pool if b.path not in near and fits(b, b.kills[0], anchor_pre, after(tj[t]))), None) \
            or next((b for b in pool if fits(b, b.kills[0], anchor_pre, after(tj[t]))), None)
        if b is None:
            if flurry[i][0] in pool:
                pool.remove(flurry[i][0])
            continue
        pool.remove(b)
        flurry[i] = (b, [b.kills[0]], [t])
    seen: set[int] = set()
    for i, (b, _ks, _ts) in enumerate(flurry):
        if id(b) in seen:                  # the swap ran out of room: end before the repeat
            notes.append(f"The reel ends {len(flurry) - i} hits early: no other clip had the footage "
                         f"to fill them.")
            flurry = flurry[:i]
            break
        seen.add(id(b))

    # ---- reel times and run-ups
    rel = lambda t: t - start                                     # noqa: E731
    impacts = [rel(D)] + [rel(ts[0]) for _b, _ks, ts in flurry]
    pres = []
    for i, (b, ks, ts) in enumerate(flurry):
        g_before = impacts[i + 1] - impacts[i]
        pres.append(anchor_pre if g_before > 1.2 * gap or strength.get(ts[0], 0.0) >= 0.6 else fast_pre)

    shots: list[dict] = []
    marks: list[float] = []
    # the take: each shot's length from the cuts inside the clip, the last one up to the first flurry run-up
    first_cut = impacts[1] - pres[0] if flurry else rel(end)
    t0 = 0.0
    for n, s in enumerate(take_shots):
        a, b_ = s.pop("_src")
        k = s["kill"]
        reel_k = rel(D) - take_span([x["kill"] for x in take_shots if x["kill"] >= k - 1e-6])
        if b_ is None:
            dur = first_cut - (reel_k - s["pre"])
        else:
            dur = b_ - a
        s["duration"] = round(max(0.1, dur), 5)
        s["kills"] = [round(x, 3) for x in best.kills if a - 1e-6 <= x <= (b_ if b_ is not None else 1e9)]
        shots.append(s)
        marks.append(round(start + reel_k, 4))
        t0 += s["duration"]
    shots[-1]["fx"] = ["k01"]                                     # the drop: one primary, the punch

    fx_i = rng.randrange(len(FX_CYCLE))
    # the inversion: once, on the strongest hit well inside the flurry, if one is strong enough
    inner = [i for i in range(2, len(flurry) - 2) if len(flurry[i][1]) == 1]
    invert_at = max(inner, key=lambda i: strength.get(flurry[i][2][0], 0.0)) if inner else None
    if invert_at is not None and strength.get(flurry[invert_at][2][0], 0.0) < 0.7:
        invert_at = None
    for i, (b, ks, ts) in enumerate(flurry):
        p = pres[i]
        nxt = (impacts[i + 2] - pres[i + 1]) if i + 1 < len(flurry) else None
        here = impacts[i + 1]
        if len(ks) == 2:
            span_out = ts[1] - ts[0]
        else:
            span_out = 0.0
        if nxt is None:
            dur = p + span_out + TAIL
        else:
            dur = nxt - (here - p)
        # what the clip can give after its (last) kill
        room = b.seconds - ks[-1] - 0.02
        if len(ks) == 2:
            rate = (ks[1] - ks[0]) / span_out
            after_out = room / rate
        else:
            after_out = room
        dur = min(dur, p + span_out + after_out)
        fx = FX_CYCLE[fx_i % len(FX_CYCLE)]
        fx_i += 1
        if i == invert_at:
            fx = INVERT
        anchors = [(ks[1], p + span_out)] if len(ks) == 2 else None
        shots.append(_shot(b, ks[0], ks, p, max(0.1, dur), fx=[fx] if fx else [], anchors=anchors))
        marks.append(round(ts[0], 4))
    kills = sorted(set(marks) | {round(ts[1], 4) for _b, _ks, ts in flurry if len(ts) > 1})
    # THE ENDING ON A BAR LINE (F17). The reel stopped TAIL after its last kill, wherever in
    # the bar that fell -- reviewed, "the black tail feels like unused runtime" and JUST A BOY
    # "ended mid-section". The last shot now runs on to the first downbeat at least
    # END_AFTER past the last kill, as far as its clip has footage; where it has not, it ends
    # where the footage does (never later than the next bar but one).
    if shots and getattr(shape, "beats", None):
        last = shots[-1]
        end_now = start + sum(s["duration"] for s in shots)
        last_kill = max(kills) if kills else end_now
        bars = [b for i, b in enumerate(shape.beats)
                if i % 4 == getattr(shape, "downbeat_pos", 0) and b >= last_kill + END_AFTER]
        if bars and bars[0] - end_now < 2 * 4 * shape.beat:
            want = bars[0] - end_now
            rate = 1.0
            if last.get("anchors"):
                (src, out), = last["anchors"]
                rate = (src - last["kill"]) / max(1e-6, out - last["pre"])
            used = (last["duration"] - last["pre"]) * rate
            # ...and stops short of the clip's next kill, which would land off every beat
            more = [float(k) for k in clips_by_path.get(last["clip"], {}).get("kills") or []
                    if float(k) > max(last["kills"]) + 1e-6]
            stop = min([float(last["clip_seconds"]) - 0.02] + [k - 0.3 for k in more])
            room = (stop - last["kill"] - used) / rate
            grow = max(0.0, min(want, room))
            last["duration"] = round(last["duration"] + grow, 5)
    return Plan(part=(round(start, 4), round(start + sum(s["duration"] for s in shots), 4)), drop=D,
                shots=shots, marks=marks, notes=notes, kills=kills)


# ------------------------------------------------------------------ montage

# MONTAGE, AFTER ITS FIRST REVIEW (ChatGPT, 2026-10-22: 4.2/10 on the general planner -- a
# fixed 2.1 s cut, 30 shots from 10 of 60 clips, the same fight shown twice in eight of
# them, kills 1.9 and 5.7 s off their beats). "A varied anthology": a held opening, then a
# sustained flow of kills on the drums, multi-kills kept together, an accent every few,
# each clip once -- the flurry Build and drop already cuts, without its build:
# * THE UNIT is the beat multiple nearest the reference montages' median shot (1.18 s),
#   inside MONTAGE_UNIT -- measured in beats at every tempo, never a fixed 2.1 s.
# * THE OPENING is one strong kill held 1-2 bars (the references' first shot is 4.9 s),
#   its kill on the strongest hit in the second bar.
# * A RUN-UP OF MONTAGE_PRE before every kill: a montage's shots are twice a flurry's,
#   and the kill reads better with the approach in it.
MONTAGE_SHOT = 1.18
MONTAGE_UNIT = (0.85, 1.5)
MONTAGE_PRE = 0.35
MONTAGE_SECONDS = 36.0
# WHITE FLASHES ON ABOUT HALF THE CUTS: the references flash 14.8 times a minute against 28.3
# cuts (52 %), and the second review called them "part of the defined Montage style". Its
# general rule: a flash may only go where at least FLASH_CLEAR -- eight frames at 60 fps --
# of clean picture is left between its end and the kill; a transition is centred on its cut,
# so the kill must be more than half the flash plus that after the cut. Short of the share
# when that cannot be met, never a flash over a kill.
FLASH = "t02"
FLASH_LEN = 0.2
FLASH_SHARE = 0.52
FLASH_CLEAR = 8 / 60


def montage_unit(beat: float) -> float:
    """Seconds between a montage's kills: the whole-beat multiple nearest MONTAGE_SHOT."""
    ks = [k * beat for k in range(1, 7)]
    inside = [g for g in ks if MONTAGE_UNIT[0] <= g <= MONTAGE_UNIT[1]]
    return min(inside or ks, key=lambda g: abs(g - MONTAGE_SHOT))


def plan_montage(clips: list[dict], shape, rhythm, *, part: tuple[float, float] | None = None,
                 seconds: float = MONTAGE_SECONDS, seed: int = 0, loose: bool = False) -> Plan:
    """Shots for a montage: a held opening, then kills on the drums, each clip once."""
    rng = random.Random(seed)
    all_b = [b for c in clips for b in bursts(c)]
    if len({b.path for b in all_b}) < 4:
        raise ValueError("A montage needs at least four clips with a kill.")
    clips_by_path = {str(c["path"]): c for c in clips}
    setups = sorted((b for b in all_b if is_setup(b)), key=setup_score, reverse=True)
    notes: list[str] = []
    beat = float(shape.beat)
    bar = 4 * beat
    gap = montage_unit(beat)
    beats = list(shape.beats)
    downbeats = [b for i, b in enumerate(beats) if i % 4 == getattr(shape, "downbeat_pos", 0) % 4]
    lo, hi = (float(part[0]), float(part[1])) if part else (float(getattr(shape, "drums_in", None) or 0.0),
                                                           float(shape.seconds))
    start = next((b for b in downbeats if b >= lo - 1e-6), lo)
    want = (hi - lo) if (part and not loose) else (hi - lo if part else seconds)
    end = min(float(shape.seconds), start + want) if (not part or loose) else hi
    # the opening: the strongest single, held, its kill on the strongest hit of the second bar
    cues = cue_scores(rhythm, beats)
    window = [(t, sc) for t, sc in cues if start + bar - 1e-6 <= t <= start + 2 * bar + 1e-6]
    D = max(window, key=lambda x: x[1])[0] if window else start + 2 * bar
    singles = sorted((b for b in all_b if len(b.kills) == 1 and b.kills[0] >= 1.0),
                     key=lambda b: (single_score(b) + (1.0 if b.big() else 0.0), rng.random()), reverse=True)
    best = next((b for b in singles if b.kills[0] - 0.05 >= min(D - start, 2 * bar)), None) or (singles or all_b)[0]
    ks = [best.kills[0]]
    take_shots, begin = take(Burst(best.clip, ks, best.hs[:1]), D - start, lead_range=(bar, 2 * bar))
    if begin > 1e-3:
        start += begin
    notes.append(f"Montage: opens on {best.clip.get('name')}, held to its kill at {D:.1f} s, then a kill about "
                 f"every {gap / beat:.0f} beat(s) ({gap:.2f} s) on the drums, a longer accent every few, "
                 f"each clip once.")
    got = _after(all_b, clips_by_path, setups, Burst(best.clip, ks, best.hs[:1]), ks, take_shots, D, start, end,
                 gap, rng, notes, shape, rhythm, fast_pre=MONTAGE_PRE, anchor_pre=MONTAGE_PRE)
    acc = rng.random()
    for s in got.shots[1:]:
        acc += FLASH_SHARE
        if acc >= 1.0 and float(s["pre"]) - FLASH_LEN / 2 >= FLASH_CLEAR - 1e-9:
            s["transition"], s["tlen"] = FLASH, FLASH_LEN
            acc -= 1.0
    return got
