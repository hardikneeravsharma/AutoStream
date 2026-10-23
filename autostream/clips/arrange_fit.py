"""Perfect fit: the reel's order and its kills' places in the song, searched together.

The "Perfect fit (slower)" arrangement. studio.plan() hands over to plan() here
when the player picks it; it takes exactly what studio.plan() takes and returns
a project studio.normalise(), derive() and the render accept.

MEASURED, re-planning five of the player's own reels from their selections
(the same emblem check, action check and song analysis for both planners;
ordinary plan -> perfect fit):

    reel (style)          clips      kills      kills of 3-4-kill clips  cuts/min    planning
    dwayIR (hype)         14 -> 25   30 -> 42   10 -> 11 of 11           37.8 -> 39.6   22 s
    Aftrhrs (story)       17 -> 27   38 -> 49   17 -> 18 of 18           18.8 -> 24.9   24 s
    ambiforcash (hype)    13 -> 13   25 -> 25   13 -> 13 of 13           38.3 -> 30.7    9 s
    Can't Hold Us (vel)    8 ->  8   14 -> 14    6 ->  6 of 6            44.1 -> 44.5   11 s
    Cradles (short)       10 -> 11   16 -> 17    3 ->  3 of 3            23.8 -> 27.6   13 s

On all five: every shot's kill on its mark to the frame (on a bass hit for
all but one, on a beat for that one), no footage played twice, no run-up under
the minimum (the ordinary plan had five on Can't Hold Us), no kill inside a
ramp, and normalise() changes nothing. The two drop reels on disk land their
fourth kill on the drop's hit (G04: 0.03 s from the drop, against 0.34 s).
Planning time is the search alone; the ffmpeg action check before it costs
both planners the same.

WHAT studio.plan() DOES, AND WHY IT LOSES KILLS
    plan() decides in stages, and no stage can see the next: select() keeps the
    strongest sequences that fill a phrase, order() places them, walk() gives
    each a length on the beat grid, and only then _hit_slots() thins the song's
    hits to the style's pace and apply_marks() moves each kill onto the next
    one. When a mark comes too soon after a shot's own later kills, the next
    shot takes the mark after; when a follow-up from the same clip cannot reach
    its mark without replaying footage, it is folded in or lands early. Each of
    those is a repair to a plan made without the song in view -- and the first
    stage has already left out every sequence the phrase could not hold.

WHAT THIS DOES INSTEAD
    The reel is one optimisation. Every kill of every chosen clip is an EVENT,
    in clip order, and every event is either

      * an ANCHOR -- it opens a shot (or a jump cut inside its clip's sequence)
        and lands exactly on one of the song's hits, or
      * a RIDER -- it plays on in the same continuous shot as the kill before
        it, wherever the footage puts it. Only kills within
        studio.OWN_KILLS_WITHIN of the one before may ride.

    Given an order of clips, the best choice of anchor/rider for every event
    and the best hit for every anchor is an exact dynamic programme over
    (event, which kill anchors the shot it is in, which hit that anchor is on).
    Every hard rule is a feasibility test on one transition, so the programme
    never produces a reel that breaks one:

      * a cut exists between two anchors that leaves the shot before its
        footage up to its own last kill plus a hold, and the shot after at
        least the minimum run-up, inside what each clip has;
      * two shots of one clip never overlap in the footage: what the shot
        before plays after its kill and what the shot after plays before its
        own add up to no more than the footage between them, so a jump cut
        only ever REMOVES footage;
      * a whole clip may be left out only when it has fewer than MUST_KILLS
        kills -- a clip with a triple or a quadra is shown whole or the
        search reports it cannot be.

AT EACH SHOT'S OWN SPEED
    Every shot's speed is chosen BEFORE the programme runs -- drawn from the
    style's pool, per clip, from the reel's seed -- and the programme measures
    every run-up and every tail through that speed's own time map (Ramp, from
    studio.pieces()). Planned at real speed and given its ramps afterwards, a
    velocity reel lost them: s04 rushes the run-up at 2.2x and needs more than
    twice the footage, so most of them no longer fitted and were taken back.

    The ORDER is then searched around that programme: simulated annealing over
    swaps, moves and reversals of the clips, starting from the rulebook's own
    build order, each candidate scored by the programme plus terms for the
    opener, the closer, the climax two thirds in and neighbouring clips that
    look alike. A fixed number of tries, never a clock, so the same clips and
    song plan the same reel on any machine.
"""
from __future__ import annotations

import dataclasses
import logging
import math
import random
import zlib
from dataclasses import dataclass, field

import numpy as np

from . import rulebook, studio, studio_refs

log = logging.getLogger(__name__)

FRAME = 1.0 / studio.FPS
NEG = -1e15

# ------------------------------------------------------------------ the hard rules

# Kills this close in the footage may share one continuous shot.
JOIN_WITHIN = studio.OWN_KILLS_WITHIN
# Held after the last kill of a shot: one kill gets reel.MIN_AFTER, several get
# the hold the planner already gives a shot's own later kills. Footage seconds.
HOLD_ONE = 0.22
HOLD_LAST = studio.OWN_KILL_HOLD
# A jump cut inside one clip that removes less footage than this is a stutter,
# not a cut: allowed (it keeps a kill on its hit) but scored down.
MIN_JUMP = 0.25
# The longest a shot may run on after its last kill, in reel seconds.
TAIL_MAX = 2.5
# A kill shown in the next kill's run-up -- one too near the start of its clip
# to have a run-up of its own -- appears at least this long into the shot.
LEAD_GAP = 0.15
# The most kills one continuous shot may carry after its anchor.
MAX_RIDERS = 6
# A clip with at least this many kills is never left out.
MUST_KILLS = 3
# How many clips in a row the programme may leave out at one place.
MAX_SKIP = 2
# Footage seconds kept back from either end of a clip. A run-up planned to
# use every frame before its kill, rounded to five places and rushed at 2.2x,
# asked studio._fit() for 10 microseconds the clip does not have -- and _fit
# took a whole grid step off it, which moved every cut after it off its hit.
SAFE = 3e-4
# How many orders the search tries. A count, not a clock: a wall-clock budget
# gave a slower machine a different reel. 400 measured at 22 s on dwayIR (25
# clips, 42 kills) and keeps the same kills, hits and clips as 600 did.
ITERATIONS = 400
# A drop reel's build: the opener lands at most this long before the drop,
# and the drop is its fourth kill -- studio.plan()'s own window.
DROP_BUILD = 14.0

# ------------------------------------------------------------------ the score

WEIGHTS = {
    "kill": 12.0,        # per kill of a clip left out
    "hit": 0.5,          # an anchor on a hit, times the hit's strength rank (0..1)
    "off_hit": -3.0,     # an anchor on a beat that is not a hit (the fallback)
    "big": 2.0,          # an anchor on a big hit, times (0.5 + the clip's strength)
    "match": 1.5,        # strong clip x strong hit
    "drop": 3.0,         # the song's drop, times the clip's strength
    "ride1": 1.0,        # a rider within one frame of a hit
    "ride3": 0.4,        # ...within three
    # Squared log-ratio of the anchor gap to the style's. At 2.0 the strength
    # of the hits outbid it and a velocity reel (Can't Hold Us) cut 26 times a
    # minute against its references' 45; at 4.0 it cuts 32 and every kill is
    # still on a hit.
    "pace": 4.0,
    "tail": 0.6,         # per second of tail past the preferred one
    "short": 2.0,        # a run-up (in FOOTAGE seconds) under the readable one, as a share of it
    "long": 0.4,         # per second of run-up past the style's long shot
    "glitch": 1.5,       # a jump cut removing under MIN_JUMP of footage
    "open": 2.0,         # the opener's strength
    "close": 2.0,        # the closer's strength
    "climax": 3.0,       # the strongest clip's distance from two thirds in
    "look": 1.0,         # two neighbouring clips in the same place
    "shape": 0.3,        # two neighbouring clips with the same number of kills
    "length": 0.3,       # per second past the format's longest reel
    "late": 0.3,         # per second the opener lands after the song's first big hit
    "build": 1.0,        # per second the opener's build falls short of the intro
    "aim": 1.0,          # the anchor gap aimed at, as a share of a minute over the style's cuts
}


# ------------------------------------------------------------------ speeds

class Ramp:
    """One speed preset's time map either side of its kill, as tables.

    `pre_src(r)`: footage seconds an r-second run-up plays. `post_src(t, own)`:
    footage seconds the first t seconds after the kill play, with `own` seconds
    of the shot's own later kills kept at real speed (studio._own_after). Both
    straight from studio.pieces(), so what is planned is what renders.
    """
    STEP = 0.005
    REACH = 12.0

    def __init__(self, speed: str):
        self.speed = speed
        R = np.arange(0.0, self.REACH + self.STEP / 2, self.STEP)
        pre = np.array([studio.source_used(studio.pieces(speed, r + 30.0, r), r) for r in R])
        # Only the corners: the map is piecewise linear, and interpolating over
        # five points instead of 2,400 was most of the programme's time.
        bend = np.abs(np.diff(pre, 2)) > 1e-7
        keep = np.concatenate([[True], bend, [True]]) | np.concatenate([[True], [False], bend])
        self.R, self.pre = R[keep], pre[keep]
        self.identity = speed == "s00"
        self._post: dict[float, tuple[np.ndarray, np.ndarray]] = {}
        k = 20.0
        self.rushes_in = any(r > 1.0 + 1e-9 for a, b, r in studio.pieces(speed, k + 1.0, k) if b <= k + 1e-9)

    def pre_src(self, r):
        if self.identity:
            return np.minimum(r, self.REACH)
        return np.interp(r, self.R, self.pre)

    def pre_out(self, src):
        if self.identity:
            return np.minimum(src, self.REACH)
        return np.interp(src, self.pre, self.R)

    def _tab(self, own: float):
        key = round(float(own), 3)
        got = self._post.get(key)
        if got is None:
            k = 20.0
            xs, ys = [0.0], [0.0]
            for a, b, r in studio.pieces(self.speed, k + self.REACH, k, own=key):
                if b <= k + 1e-9:
                    continue
                a = max(a, k)
                xs.append(b - k)
                ys.append(ys[-1] + (b - a) * r)
            got = (np.asarray(xs), np.asarray(ys))
            self._post[key] = got
        return got

    def post_src(self, t, own: float = 0.0):
        xs, ys = self._tab(own)
        return np.interp(t, xs, ys)

    def post_out(self, src, own: float = 0.0):
        xs, ys = self._tab(own)
        return np.interp(src, ys, xs)


_RAMPS: dict[str, Ramp] = {}


def ramp(speed: str) -> Ramp:
    got = _RAMPS.get(speed)
    if got is None:
        got = _RAMPS[speed] = Ramp(speed)
    return got


# ------------------------------------------------------------------ the pieces of a plan

@dataclass
class Block:
    """One chosen clip: the kills the reel must show, in footage order."""
    clip: dict
    kills: list[float]                 # anchor-able kills, ascending
    leads: list[float]                 # kills shown only inside the first kill's run-up
    seconds: float
    strength: float = 0.0              # 0..1 within the selection
    look: list[float] | None = None
    first_run: float = 0.0             # the first kill's minimum run-up, footage seconds
    speeds: list[str] = field(default_factory=list)   # each kill's speed as an anchor
    hero: bool = False

    @property
    def total(self) -> int:
        return len(self.kills) + len(self.leads)

    @property
    def must(self) -> bool:
        return self.total >= MUST_KILLS


@dataclass
class Song:
    """Where a kill may land: every hit, and every beat as a weaker fallback."""
    T: np.ndarray                      # song seconds, ascending
    hit: np.ndarray                    # bool
    s: np.ndarray                      # hit strength rank, 0..1 (0 off a hit)
    big: np.ndarray                    # bool
    drop: np.ndarray                   # bool
    hits: np.ndarray                   # the hits alone, ascending
    IDX: np.ndarray = field(default=None)   # (P, D): predecessor index p - d - 1
    GM: np.ndarray = field(default=None)    # (P, D): T[p] - T[IDX]
    VM: np.ndarray = field(default=None)    # (P, D): IDX valid

    @classmethod
    def of(cls, grid, lo: float, hi: float, reach: float) -> "Song":
        hits = np.asarray(grid.hits, dtype=float)
        strength = np.asarray(grid.hit_strength if len(grid.hit_strength) == len(grid.hits)
                              else [1.0] * len(grid.hits), dtype=float)
        rank = np.zeros(len(hits))
        if len(hits):
            order = np.argsort(strength, kind="stable")
            rank[order] = np.arange(len(hits)) / max(1, len(hits) - 1)
        keep = (hits >= lo - 1e-6) & (hits <= hi + 1e-6)
        hits_in, rank_in = hits[keep], rank[keep]
        beats = np.asarray([b for b in grid.beats if lo - 1e-6 <= b <= hi + 1e-6], dtype=float)
        # A beat within two frames of a hit IS that hit.
        if len(hits_in) and len(beats):
            j = np.searchsorted(hits_in, beats)
            near = np.minimum(np.abs(beats - hits_in[np.clip(j - 1, 0, len(hits_in) - 1)]),
                              np.abs(beats - hits_in[np.clip(j, 0, len(hits_in) - 1)]))
            beats = beats[near > 2 * FRAME]
        T = np.concatenate([hits_in, beats])
        hit = np.concatenate([np.ones(len(hits_in), bool), np.zeros(len(beats), bool)])
        s = np.concatenate([rank_in, np.zeros(len(beats))])
        o = np.argsort(T, kind="stable")
        T, hit, s = T[o], hit[o], s[o]
        big = np.zeros(len(T), bool)
        for b in grid.big or []:
            if lo - 1e-6 <= b <= hi + 1e-6 and len(T):
                i = int(np.argmin(np.abs(T - b)))
                if abs(T[i] - b) < 0.01:
                    big[i] = True
        drop = np.zeros(len(T), bool)
        if grid.drop is not None and len(T):
            cand = np.where(hit)[0]
            if len(cand):
                i = cand[int(np.argmin(np.abs(T[cand] - grid.drop)))]
                if abs(T[i] - grid.drop) < 0.5:
                    drop[i] = True
        out = cls(T=T, hit=hit, s=s, big=big, drop=drop, hits=np.asarray(sorted(grid.hits), float))
        P = len(T)
        D = 1
        if P:
            D = int(max(1, np.max(np.searchsorted(T, T + reach, side="right") - np.arange(P))))
        d = np.arange(1, D + 1)
        idx = np.arange(P)[:, None] - d[None, :]
        out.VM = idx >= 0
        out.IDX = np.where(out.VM, idx, 0)
        out.GM = np.where(out.VM, T[:, None] - T[out.IDX], 1e9)
        return out

    def hit_dist(self, t: np.ndarray) -> np.ndarray:
        """Distance from each time to the nearest hit."""
        h = self.hits
        if not len(h):
            return np.full(np.shape(t), 9.0)
        j = np.searchsorted(h, t)
        a = np.abs(t - h[np.clip(j - 1, 0, len(h) - 1)])
        b = np.abs(t - h[np.clip(j, 0, len(h) - 1)])
        return np.minimum(a, b)


@dataclass
class Rules:
    """The numbers one reel is fitted with, from its style, its song and its dials."""
    gap: float                 # the style's anchor gap: a minute over its cuts
    run_min: float             # the least run-up any kill gets, reel seconds
    readable: float            # a run-up showing this much footage reads as a fight
    run_cap: float             # past this a run-up is scored down
    max_lead: float            # and past this it is not allowed
    tail_pref: float           # how long a shot ordinarily runs on after its kill
    open_want: float           # the opener's run-up, as the style's references hold it
    close_want: float          # the closer's tail
    floor: float               # song seconds reel zero may not go before
    end_cap: float             # song seconds the reel must end by
    first: float               # where the opener's kill belongs
    start_window: float        # how far past `first` the opener may land
    soft_max: float            # reel seconds past which length is scored down
    build: bool = False        # the opener builds at half speed over a quiet intro


# ------------------------------------------------------------------ the programme

class Fitter:
    """The exact programme for one order, and the order search around it."""

    def __init__(self, blocks: list[Block], song: Song, rules: Rules, weights: dict | None = None,
                 strict: bool = True, drop_pos: int | None = None):
        self.blocks = blocks
        self.song = song
        self.r = rules
        self.w = dict(WEIGHTS, **(weights or {}))
        # Strict: a clip of MUST_KILLS or more is never left out. Relaxed only
        # when no reel at all keeps every one of them -- a part too short.
        self.strict = strict
        # A drop reel: the fourth event is an anchor on this position, and the
        # three before it are anchors too, so it is the reel's fourth kill.
        self.drop_pos = drop_pos
        self.evals = 0
        self._memo: dict[tuple, float] = {}
        w = self.w
        # Per-position parts of an anchor's score that do not depend on the clip.
        self.node_hit = np.where(song.hit, w["hit"] * song.s, w["off_hit"])
        self.node_str = w["match"] * song.s + w["big"] * song.big + w["drop"] * song.drop
        self._ride_cache: dict[tuple, np.ndarray] = {}
        looks = [b.look for b in blocks]
        n = len(blocks)
        self.same_place = np.zeros((n, n), bool)
        for i in range(n):
            for j in range(n):
                if i != j:
                    self.same_place[i, j] = rulebook.look_similarity(looks[i], looks[j]) >= rulebook.LOOK_SAME

    # -------------------------------------------------- speeds

    def speed(self, ev: list[tuple], e: int) -> str:
        """The speed event e's shot plays at when e is its anchor."""
        if e == 0 and self.r.build:
            return "s05"                       # half speed over the quiet intro
        bi, j, _k = ev[e]
        sp = self.blocks[bi].speeds
        return sp[j] if j < len(sp) else "s00"

    def run_floor(self, ev: list[tuple], e: int, rp: Ramp) -> float:
        """The least run-up, in reel seconds, event e's shot may open with."""
        bi, j, _k = ev[e]
        if j == 0:
            return max(self.r.run_min, float(rp.pre_out(self.blocks[bi].first_run)))
        return self.r.run_min

    # -------------------------------------------------- pieces of the score

    def _ride(self, rp: Ramp, delta: float) -> np.ndarray:
        """A rider's score at every anchor position: is it on a hit too?"""
        key = (rp.speed, round(delta, 4))
        got = self._ride_cache.get(key)
        if got is None:
            land = float(rp.post_out(delta, delta + HOLD_LAST))
            d = self.song.hit_dist(self.song.T + land)
            got = np.where(d <= FRAME + 1e-6, self.w["ride1"],
                           np.where(d <= 3 * FRAME + 1e-6, self.w["ride3"], 0.0))
            self._ride_cache[key] = got
        return got

    def _node(self, b: Block) -> np.ndarray:
        return self.node_hit + (0.5 + b.strength) * self.node_str

    def _tail(self, ev, q: int, r: int):
        """(ramp, own, the last kill's reel offset from the anchor, the least tail, the most)"""
        a = q - r
        ka, kq = ev[a][2], ev[q][2]
        rp = ramp(self.speed(ev, a))
        lastsrc = kq - ka
        own = lastsrc + HOLD_LAST if r > 0 else 0.0
        hold = HOLD_LAST if r > 0 else HOLD_ONE
        room = max(0.0, self.blocks[ev[q][0]].seconds - ka - SAFE)
        lastoff = float(rp.post_out(lastsrc, own)) if r > 0 else 0.0
        need = float(rp.post_out(min(lastsrc + hold, room), own))
        most = float(rp.post_out(room, own))
        return rp, own, lastoff, need, most

    def edge(self, ev: list[tuple], q: int, r: int, e: int, Tp, Tq):
        """Score and cut of a cut from shot (anchor q - r, last kill q) to anchor e.

        Tp and Tq are the two anchors' song times, any matching shapes.
        -> (score, cut), score NEG where the cut is impossible.
        """
        R, w = self.r, self.w
        a = q - r
        bq, ka = ev[q][0], ev[a][2]
        be, _je, ke = ev[e]
        ra, own, lastoff, tneed, most = self._tail(ev, q, r)
        re_ = ramp(self.speed(ev, e))
        rmin = self.run_floor(ev, e, re_)
        G = Tq - Tp
        pref = Tp + max(tneed, lastoff + R.tail_pref)
        if bq == be:
            lo = Tp + tneed
            hi = Tq - rmin
            cut = np.clip(pref, lo, np.maximum(lo, hi))
            # What the shot before plays after its kill and what this one plays
            # before its own, through their own speeds, fit in the footage
            # between the two kills: nothing is shown twice.
            used = ra.post_src(cut - Tp, own) + re_.pre_src(Tq - cut)
            ok = (lo <= hi + 1e-9) & (used <= ke - ka + 1e-6)
            removed = (ke - ka) - used
            glitch = (removed > FRAME) & (removed < MIN_JUMP)
        else:
            avail_pre = min(float(re_.pre_out(ke - SAFE)), R.max_lead)
            lo = np.maximum(Tp + tneed, Tq - avail_pre)
            hi = np.minimum(np.minimum(Tp + most - 1e-4, Tq - rmin), Tp + lastoff + TAIL_MAX)
            ok = lo <= hi + 1e-9
            cut = np.clip(pref, lo, np.maximum(lo, hi))
            glitch = False
        run = Tq - cut
        seen = re_.pre_src(run)
        tail = cut - Tp - lastoff
        gstar = max(R.gap, tneed + rmin)
        with np.errstate(divide="ignore", invalid="ignore"):
            pace = np.log(np.maximum(G, 1e-3) / gstar) ** 2
        sc = (-w["pace"] * pace
              - w["tail"] * np.maximum(0.0, tail - max(tneed - lastoff, R.tail_pref))
              - w["short"] * np.maximum(0.0, R.readable - seen) / R.readable
              - w["long"] * np.maximum(0.0, run - R.run_cap)
              - w["glitch"] * glitch)
        if bq != be:
            sc = sc - w["look"] * self.same_place[bq, be] - w["shape"] * (
                self.blocks[bq].total == self.blocks[be].total)
        return np.where(ok, sc, NEG), cut

    def end(self, ev: list[tuple], q: int, r: int, Tp, offset_est: float):
        """Score and reel end of finishing on shot (anchor q - r, last kill q). -> (score, end)"""
        R, w = self.r, self.w
        _rp, _own, lastoff, tneed, most = self._tail(ev, q, r)
        tail = min(max(tneed, lastoff + R.close_want), most)
        stop = Tp + tail
        sc = -w["length"] * np.maximum(0.0, stop - offset_est - R.soft_max)
        return np.where(stop <= R.end_cap + 1e-6, sc, NEG), stop

    def start(self, ev: list[tuple]):
        """-> (score, run-up) for the opener's anchor at each position."""
        R, w, T = self.r, self.w, self.song.T
        rp = ramp(self.speed(ev, 0))
        k0 = ev[0][2]
        rmin = self.run_floor(ev, 0, rp)
        pre = np.minimum(np.minimum(float(rp.pre_out(k0 - SAFE)), R.open_want), np.minimum(T - R.floor, R.max_lead))
        ok = pre >= rmin - 1e-9
        if self.drop_pos is not None and len(ev) > 3:
            drop_t = T[self.drop_pos]
            ok &= (T >= drop_t - DROP_BUILD) & (T < drop_t - 1e-6)
            sc = np.zeros(len(T))
        else:
            ok &= (T >= R.first - 0.3) & (T <= R.first + R.start_window)
            sc = -w["late"] * np.maximum(0.0, T - R.first)
        if R.build:
            sc = sc - w["build"] * np.maximum(0.0, R.open_want - pre)
        return np.where(ok, sc, NEG), pre

    # -------------------------------------------------- the programme itself

    def events(self, order: list[int]) -> list[tuple]:
        """(block, index in block, kill time) for every event, in reel order."""
        return [(bi, j, k) for bi in order for j, k in enumerate(self.blocks[bi].kills)]

    def solve(self, order: list[int], want_path: bool = False):
        """The best reel for this order of clips. -> (score, path or None)

        path: [(event, r, position)] for every event that was placed, in reel
        order, where r is how many kills back its shot's anchor is (0 = it is
        the anchor). The events of left-out clips are absent.
        """
        key = tuple(order)
        if not want_path and key in self._memo:
            return self._memo[key], None
        self.evals += 1
        song, w = self.song, self.w
        ev = self.events(order)
        if not ev:
            return NEG, None
        P = len(song.T)
        first_of: dict[int, int] = {}
        last_of: dict[int, int] = {}
        for i, (bi, j, _k) in enumerate(ev):
            first_of.setdefault(bi, i)
            last_of[bi] = i
        pos_of = {bi: n for n, bi in enumerate(order)}
        drop = self.drop_pos is not None and len(ev) > 3
        V: list[np.ndarray] = []
        back: list[tuple | None] = []
        s0, _pre0 = self.start(ev)
        V.append((s0 + self._node(self.blocks[ev[0][0]]))[None, :])
        back.append(None)
        arP = np.arange(P)
        Tq = song.T[:, None]
        Tp = song.T[song.IDX]
        for e in range(1, len(ev)):
            be, je, ke = ev[e]
            b = self.blocks[be]
            # Riders: the same continuous shot as the kill before. Not in a
            # drop reel's build, whose first four kills are four shots.
            rmax = 0
            if je > 0 and ke - ev[e - 1][2] <= JOIN_WITHIN + 1e-9 and not (drop and e <= 3):
                rmax = min(MAX_RIDERS, V[e - 1].shape[0])
            Ve = np.full((rmax + 1, P), NEG)
            for r in range(1, rmax + 1):
                a = e - r
                Ve[r] = V[e - 1][r - 1] + self._ride(ramp(self.speed(ev, a)), ke - ev[a][2])
            # Anchors: from the event before, or -- for a clip's first kill --
            # from the end of a clip further back, leaving out the ones between.
            preds = [(e - 1, 0.0)]
            if je == 0:
                n = pos_of[be]
                pen = 0.0
                for s in range(1, MAX_SKIP + 1):
                    skipped = order[n - s] if n - s >= 1 else None
                    if skipped is None or (self.strict and self.blocks[skipped].must):
                        break
                    if drop and first_of[skipped] <= 3:
                        break                      # the build's four kills are counted
                    pen += w["kill"] * self.blocks[skipped].total
                    q = first_of[skipped] - 1
                    if q < 0:
                        break
                    preds.append((q, pen))
            best = np.full(P, NEG)
            bq = np.zeros(P, int)
            br = np.zeros(P, int)
            bp = np.zeros(P, int)
            for q, pen in preds:
                for r in range(V[q].shape[0]):
                    vq = V[q][r]
                    if vq.max() <= NEG / 2:
                        continue
                    sc, _cut = self.edge(ev, q, r, e, Tp, Tq)
                    C = vq[song.IDX] + np.where(song.VM, sc, NEG) - pen
                    d = C.argmax(1)
                    m = C[arP, d]
                    upd = m > best
                    if upd.any():
                        best[upd] = m[upd]
                        bq[upd], br[upd] = q, r
                        bp[upd] = song.IDX[arP, d][upd]
            ok = best > NEG / 2
            if drop and e == 3:
                ok &= arP == self.drop_pos
            Ve[0] = np.where(ok, best + self._node(b), NEG)
            V.append(Ve)
            back.append((bq, br, bp))
        # The end: the last clip, or a clip before it with the rest left out.
        T = song.T
        off_est = self.r.first - self.r.open_want
        best_sc, best_state = NEG, None
        n = len(order)
        pen = 0.0
        for s in range(0, MAX_SKIP + 1):
            if n - 1 - s < 0:
                break
            if s:
                gone = order[n - s]
                if self.strict and self.blocks[gone].must:
                    break
                if drop and first_of[gone] <= 3:
                    break
                pen += w["kill"] * self.blocks[gone].total
            q = last_of[order[n - 1 - s]]
            for r in range(V[q].shape[0]):
                sc, _stop = self.end(ev, q, r, T, off_est)
                tot = V[q][r] + sc - pen
                p = int(tot.argmax())
                if tot[p] > best_sc:
                    best_sc, best_state = float(tot[p]), (q, r, p)
        if best_state is None or best_sc <= NEG / 2:
            self._memo[key] = NEG
            return NEG, None
        best_sc += self.order_score(order)
        self._memo[key] = best_sc
        if not want_path:
            return best_sc, None
        path = []
        q, r, p = best_state
        while True:
            path.append((q, r, p))
            if r > 0:
                q, r = q - 1, r - 1
                continue
            if q == 0:
                break
            bq, br, bp = back[q]
            q, r, p = int(bq[p]), int(br[p]), int(bp[p])
        path.reverse()
        return best_sc, (ev, path)

    def order_score(self, order: list[int]) -> float:
        w, bl = self.w, self.blocks
        n = len(order)
        if n == 0:
            return 0.0
        sc = w["open"] * bl[order[0]].strength + w["close"] * bl[order[-1]].strength
        if n > 2:
            top = max(range(n), key=lambda i: (bl[order[i]].strength, -i))
            sc -= w["climax"] * abs(top / (n - 1) - rulebook.CLIMAX_AT)
        return sc

    # -------------------------------------------------- the order search

    def search(self, start_orders: list[list[int]], fixed: dict[int, int] | None = None,
               iterations: int = ITERATIONS, seed: int = 0) -> tuple[float, list[int]]:
        """Simulated annealing over the order. `fixed` pins block -> position.

        Deterministic: a seeded generator and a fixed number of tries.
        """
        rng = random.Random(seed or 1)
        fixed = fixed or {}
        best, best_order = NEG, None
        for o in start_orders:
            sc, _ = self.solve(o)
            if sc > best:
                best, best_order = sc, list(o)
        if best_order is None or len(best_order) < 3 or iterations <= 0:
            return best, best_order or start_orders[0]
        free = [i for i in range(len(best_order)) if best_order[i] not in fixed]
        if len(free) < 2:
            return best, best_order
        cur, cur_sc = list(best_order), best
        t0, t1 = 3.0, 0.05
        for it in range(iterations):
            temp = t0 * (t1 / t0) ** (it / max(1, iterations - 1))
            cand = list(cur)
            move = rng.random()
            if move < 0.4:
                i, j = rng.sample(free, 2)
                cand[i], cand[j] = cand[j], cand[i]
            elif move < 0.8:
                i, j = rng.sample(free, 2)
                x = cand.pop(i)
                cand.insert(j, x)
                if any(cand[p] != cur[p] for p in range(len(cand)) if cur[p] in fixed):
                    continue
            else:
                i, j = sorted(rng.sample(free, 2))
                seg = [p for p in free if i <= p <= j]
                vals = [cand[p] for p in seg][::-1]
                for p, v in zip(seg, vals):
                    cand[p] = v
            sc, _ = self.solve(cand)
            if sc > cur_sc or (sc > NEG / 2 and rng.random() < math.exp((sc - cur_sc) / max(temp, 1e-6))):
                cur, cur_sc = cand, sc
                if sc > best:
                    best, best_order = sc, list(cand)
        return best, best_order


# ------------------------------------------------------------------ the plan

def _blocks(chosen: list[dict], kept_kills: dict[str, list[float]], strengths: dict[str, float],
            looks: dict[str, list[float]], run_min: float) -> tuple[list[Block], dict[str, str], int]:
    """A Block per clip with something to show. -> (blocks, why each other clip is out, kills unshowable)"""
    blocks, why, lost = [], {}, 0
    for c in chosen:
        path = c["path"]
        D = round(float(c.get("duration") or 0.0), 3)
        ks = sorted(round(float(k), 3) for k in kept_kills.get(path, []) if 0.0 <= float(k) <= D + 1e-6)
        if not ks:
            why.setdefault(path, "Nothing moves on screen around its kill (a death camera, or standing still).")
            continue
        # A kill too near the start of its clip for a run-up is shown in the
        # next kill's run-up when that one is close enough -- never dropped
        # while there is a way to show it.
        leads: list[float] = []
        while ks and ks[0] < run_min - 1e-9:
            if len(ks) > 1 and ks[1] - ks[0] <= JOIN_WITHIN and ks[1] >= ks[0] + LEAD_GAP:
                leads.append(ks.pop(0))
            else:
                ks.pop(0)
                lost += 1
        if not ks:
            why.setdefault(path, "Too little footage before its kill to show the fight.")
            continue
        first_run = run_min if not leads else max(run_min, ks[0] - leads[0] + LEAD_GAP)
        blocks.append(Block(clip=c, kills=ks, leads=leads, seconds=D, strength=strengths.get(path, 0.0),
                            look=looks.get(path), first_run=first_run, speeds=["s00"] * len(ks)))
    top = max((b.strength for b in blocks), default=1.0) or 1.0
    for b in blocks:
        b.strength = b.strength / top
    return blocks, why, lost


def _choose_speeds(blocks: list[Block], style, seed: int, run_min: float) -> None:
    """Each kill's speed as an anchor, decided before the programme so it plans through it.

    The opening kill of every clip draws from the style's pool -- per clip,
    from the reel's seed, so the order does not change it. A follow-up inside
    a clip is a jump cut at real speed, as rulebook.budget() makes it, except
    a hero clip's last kill, which takes the style's hero speed. A speed the
    footage cannot carry -- or a run-up rush with an earlier kill riding in it
    -- is real speed instead.
    """
    valid = set(studio.ids_of("speed"))
    pool = [p for p in style.speed_pool if p in valid] or ["s00"]
    hero_speed = style.hero_speed if style.hero_speed in valid else "s00"
    for b in blocks:
        rng = random.Random(zlib.crc32(f"{seed}:{b.clip['path']}".encode("utf-8")))
        out = []
        for j, k in enumerate(b.kills):
            if b.hero and j == len(b.kills) - 1:
                sp = hero_speed
            elif j == 0:
                sp = rng.choice(pool)
            else:
                sp = "s00"
            rp = ramp(sp)
            floor = max(run_min, b.first_run if j == 0 else run_min)
            if j == 0 and b.leads and rp.rushes_in:
                sp = "s00"
            elif float(rp.pre_out(k)) < max(run_min, float(rp.pre_out(floor))) - 1e-9:
                sp = "s00"
            out.append(sp)
        b.speeds = out


def _ordinary(clips, style_key, shape_it, **kw):
    """studio.plan() as the other arrangements have it -- never back into this module."""
    shaped = dict(shape_it or {})
    shaped["arrange"] = "build"
    proj, notes = studio.plan(clips, style_key, shape_it=shaped, **kw)
    proj["arrange"] = "fit"                    # the choice survives a rebuild
    return proj, notes


def plan(clips: list[dict], style_key: str = studio.DEFAULT_STYLE, *, shape=None,
         song: str = "", fmt: str = "landscape", name: str = "",
         max_seconds: float = 0.0, seed: int | None = None,
         measure=None, confirm=None, theirs=None, refine=None, checks: bool = False,
         part: tuple[float, float] | None = None,
         template: dict | None = None, shape_it: dict | None = None,
         iterations: int = ITERATIONS, weights: dict | None = None,
         ) -> tuple[dict, list[str]]:
    """studio.plan()'s signature and result, with the order and timing searched together.

    Without a song that has hits there is nothing to fit, and the reel is
    planned the ordinary way.
    """
    if checks:
        # The same four checks studio.plan() makes -- see studio.plan_checks.
        have = studio.plan_checks()
        measure, confirm = measure or have.get("measure"), confirm or have.get("confirm")
        theirs, refine = theirs or have.get("theirs"), refine or have.get("refine")
    kw = dict(shape=shape, song=song, fmt=fmt, name=name, max_seconds=max_seconds, seed=seed,
              measure=measure, confirm=confirm, theirs=theirs, refine=refine, part=part,
              template=template)
    if shape is None or not song or not getattr(shape, "hits", None):
        proj, notes = _ordinary(clips, style_key, shape_it, **kw)
        return proj, ["Perfect fit needs a song with beats to fit the kills to; this reel was "
                      "planned the usual way."] + notes
    style = studio.STYLE.get(style_key) or studio.STYLE[studio.DEFAULT_STYLE]
    # One transition, one kill effect, real speed -- before the template, so a choice wins.
    if studio.fast_reel(style, getattr(shape, "bpm", None)):
        style = studio.fast_rules(style)
    if template:
        style = studio.templated(style, template,
                                exact=studio.fast_reel(studio.STYLE.get(style_key), getattr(shape, "bpm", None)))
    tw = studio._shaping(shape_it)
    arrangement = studio._arrangement(shape_it)
    hs_only = arrangement.pop("hs_only")
    if tw["effects"] != 1.0:
        style = dataclasses.replace(style, energy=max(0.0, min(1.0, style.energy * tw["effects"])))
    grid = studio.Grid.of(shape)
    notes: list[str] = []
    meas = studio_refs.summary(style.refs)
    beat = grid.beat
    cpm = (meas.get("cuts_per_min") or 30.0) * tw["pace"]
    want = (meas.get("median_shot") or 0.0) / tw["pace"] or (60.0 / cpm)
    div = studio._grid_div(want, beat)
    step = beat / div
    gap = 60.0 / max(cpm, 1.0)
    flash_share = min(0.9, (meas.get("flashes_per_min") or 0.0) / max(cpm, 1.0) * tw["flash"])

    part_start = part_len = 0.0
    if part and grid.seconds:
        part_start = max(0.0, min(float(part[0]), grid.seconds - 1.0))
        end = float(part[1] or 0.0)
        end = min(end, grid.seconds) if end > part_start else grid.seconds
        part_len = end - part_start

    why_out: dict[str, str] = {}

    def left_out(paths, reason: str) -> None:
        for p in paths:
            why_out.setdefault(p, reason)

    offered, seen = [], set()
    for c in clips:
        if not c or not c.get("path"):
            continue
        k = str(c["path"]).lower()
        if k in seen:
            continue
        seen.add(k)
        offered.append(c)
    chosen = offered[:studio.MAX_SHOTS]
    left_out((c["path"] for c in offered[studio.MAX_SHOTS:]), f"Only the first {studio.MAX_SHOTS} clips can go in one reel.")
    run_min = max(rulebook.MIN_RUN_BEATS * beat, rulebook.MIN_RUN_SECONDS)

    if hs_only:
        chosen, no_hs, dropped_k = studio._headshots_only(chosen)
        left_out(no_hs, "No kill in this clip was read as a headshot.")
        if not chosen:
            raise studio.ProjectError("None of the chosen clips has a kill read as a headshot.")
    if confirm is not None:
        before = [c["path"] for c in chosen]
        chosen, moved, dropped, added = studio._confirm_kills(chosen, confirm, theirs)
        if hs_only:
            for c in chosen:
                if c.get("_hs_times"):
                    c["kills"] = [k for k in c["kills"]
                                  if any(abs(k - h) <= studio.SNAP_AFTER + 0.05 for h in c["_hs_times"])] or c["kills"][:0]
            chosen = [c for c in chosen if c.get("kills")]
        kept_paths = {c["path"] for c in chosen}
        left_out((p for p in before if p not in kept_paths),
                 "No kill showed on screen: the game's kill icon never appeared in this clip.")
    if refine is not None:
        # After every check that decides WHETHER a kill happened -- see studio.plan.
        chosen, _got = studio._refine_kills(chosen, refine)

    # The same moments, action check and looks the planner uses -- so both
    # start from the same kills and only the arranging differs.
    all_moments = rulebook.moments(chosen, beat)
    looks: dict[str, list[float]] = {}
    still_kills: dict[str, set[float]] = {}
    sat_trim = 1.0
    if measure is not None:
        stats = studio._measure_action(all_moments, measure)
        sat_trim = rulebook.saturation_trim(
            [st.get("sat") for st in stats.values() if isinstance(st, dict)], style.grade)
        for m in all_moments:
            st = stats.get(id(m))
            if isinstance(st, dict) and st.get("hist") and m.clip["path"] not in looks:
                looks[m.clip["path"]] = st["hist"]
        kept, _still = rulebook.drop_still(all_moments, stats)
        keep_ids = {id(m) for m in kept}
        # NOT IN A MULTI-KILL CLIP. Holding an angle is standing still too:
        # dwayIR's VALORANT_05 quadra lost its third kill (63.47 s) to this
        # check, and by eye it is a clean kill through a doorway with the
        # feed and the emblem on screen. A clip whose kills were confirmed
        # and number three or more is shown whole.
        must = {c["path"] for c in chosen if len(c.get("kills") or []) >= MUST_KILLS}
        still = kept_still = 0
        for m in all_moments:
            if id(m) in keep_ids:
                continue
            if m.clip["path"] in must:
                kept_still += 1
                kept.append(m)
                continue
            still += 1
            still_kills.setdefault(m.clip["path"], set()).update(round(k, 3) for k in m.kills)
        all_moments = kept
        if still:
            notes.append(f"{still} moment(s) left out: nothing moves on screen around the kill "
                         f"(a death camera, or standing still).")
        if kept_still:
            notes.append(f"{kept_still} kill(s) with little movement around them were kept: they "
                         f"belong to a clip of {MUST_KILLS} or more kills, which is shown whole.")
    strengths: dict[str, float] = {}
    for m in all_moments:
        strengths[m.clip["path"]] = max(strengths.get(m.clip["path"], 0.0), m.strength)
    kept_kills = {}
    for c in chosen:
        bad = still_kills.get(c["path"], set())
        kept_kills[c["path"]] = [k for k in (c.get("kills") or []) if round(float(k), 3) not in bad]
    for c in chosen:
        strengths.setdefault(c["path"], 2.0 * len(kept_kills[c["path"]]))
    blocks, why, lost = _blocks(chosen, kept_kills, strengths, looks, run_min)
    for p, reason in why.items():
        left_out([p], reason)
    if lost:
        notes.append(f"{lost} kill(s) sit too near the start of their clip to have any run-up, "
                     f"and no later kill is close enough to show them in its own.")
    if not blocks:
        raise studio.ProjectError("None of the chosen clips has a kill with footage before it.")
    if seed is None:
        seed = zlib.crc32(",".join(str(b.clip["path"]) for b in blocks).encode("utf-8")) & 0x7FFFFFFF

    # HEROES BEFORE THE PLAN, because a hero plays at the style's hero speed
    # and the programme has to plan through it: the strongest multi-kill
    # clips, about one shot in six as studio.plan() has it.
    events_n = sum(len(b.kills) for b in blocks)
    multi = sorted((i for i, b in enumerate(blocks) if b.total >= 2), key=lambda i: (-blocks[i].strength, i))
    for i in multi[:max(1, events_n // 6)]:
        blocks[i].hero = True
    _choose_speeds(blocks, style, seed, run_min)

    # ---- the rules for this reel
    floor = part_start if part_len else 0.0
    end_cap = (part_start + part_len) if part_len else grid.seconds - 0.5
    if part_len:
        first = studio._first_kill(grid.hits, [], earliest=floor + run_min)
    else:
        first = studio._first_kill(grid.hits, grid.big, earliest=run_b_seconds(run_min, step),
                                   drums_in=grid.drums_in or 0.0)
    open_want = max(run_min, max(meas.get("first_shot") or 2.0, 2.0) * 0.8)
    # THE BUILD, as studio.plan() decides it: a song with a quiet stretch
    # before its drums opens on two bars of half-speed run-up over it, and the
    # opener's kill lands with the drums.
    energy = rulebook.energy_profile(grid.peaks, grid.seconds)
    build = (not style.drop and style.outro != "e12"
             and rulebook.wants_build(energy, grid.drums_in, beat))
    if build and part_len:
        build = part_start + rulebook.INTRO_BARS * 4 * beat <= (grid.drums_in or 0.0) + beat
    if build:
        open_want = (rulebook.INTRO_BARS * 4 - 1) * beat
    closer = rulebook.ENDING_BEATS * beat if style.outro in ("e01", "e03", "e02") else max(HOLD_ONE, beat)
    soft_max = max_seconds or rulebook.MAX_SECONDS.get(fmt, 86.0)
    if part_len:
        soft_max = min(soft_max, part_len)
    # THE GAP AIMED AT sits between the style's two measures of pace: a minute
    # over its cuts (velocity 1.35 s) counts the long opener and the held
    # ending, and aimed at alone a velocity reel cut 34 times a minute against
    # its references' 45; the references' median shot (0.76 s) is what the
    # ordinary planner walks at -- so the aim is their geometric mean...
    gap = math.sqrt(gap * max(want, 0.2)) * dict(WEIGHTS, **(weights or {}))["aim"]
    # ...LESS THE TIME ITS SLOW MOTION TAKES. A ramp spends half a second or
    # more of the reel at 0.3x around each kill, and a minimum run-up plus that
    # makes every ramped shot longer than a real-speed one; aimed at the same
    # gap, a velocity reel (every speed in its pool a ramp) still cut at 39.5
    # a minute. A quarter off for a pool of nothing but ramps put it at 44.4,
    # the ordinary planner's 44.1 without its five run-ups under the minimum.
    speeds = [p for p in style.speed_pool if p in studio.ids_of("speed")] or ["s00"]
    gap *= 1.0 - 0.25 * sum(1 for p in speeds if p != "s00") / len(speeds)
    rules = Rules(gap=gap, run_min=run_min, readable=max(run_min, min(1.0, 0.6 * gap)),
                  run_cap=max(1.5, 2.0 * gap), max_lead=rulebook.MAX_LEAD_UP_SECONDS,
                  tail_pref=min(beat, 0.4 * gap), open_want=open_want, close_want=closer,
                  floor=floor, end_cap=end_cap, first=first, start_window=max(2.0 * gap, 2.0 * beat),
                  soft_max=soft_max, build=build)
    reach = rulebook.MAX_LEAD_UP_SECONDS + TAIL_MAX + JOIN_WITHIN * 2
    lo = max(floor, first - rules.max_lead - 1.0)
    # A drop reel's opener may land up to DROP_BUILD before the drop, which
    # can be before the first big hit -- and never when the part was chosen,
    # whose start is the player's (as in studio.plan()).
    drop_on = bool(style.drop and grid.drop and not part_len and sum(len(b.kills) for b in blocks) > 3)
    if drop_on:
        lo = max(floor, min(lo, grid.drop - DROP_BUILD - rules.max_lead - 1.0))
    tune = Song.of(grid, lo, end_cap, reach)
    drop_pos = None
    if drop_on and tune.drop.any():
        drop_pos = int(np.argmax(tune.drop))
    fit = Fitter(blocks, tune, rules, weights, drop_pos=drop_pos)

    # ---- the order: the rulebook's own shapes to start from, then the search
    ms = [rulebook.Moment(clip=b.clip, kills=b.kills, group=i, strength=b.strength) for i, b in enumerate(blocks)]
    look_by_group = {i: b.look for i, b in enumerate(blocks) if b.look}
    starts = []
    for how in ("build", "best", "time"):
        o = rulebook.order(ms, look_by_group, None, arrange=how, pins=arrangement["pins"])
        starts.append(list(dict.fromkeys(m.group for m in o)))
    fixed = {}
    if arrangement["pins"]:
        pinned = {str(v).lower() for v in arrangement["pins"].values()}
        o = starts[0]
        fixed = {bi: o.index(bi) for bi in o if str(blocks[bi].clip["path"]).lower() in pinned}

    def arrange():
        fit._memo.clear()
        return fit.search(starts, fixed, iterations=iterations, seed=seed)[1]
    order = arrange()
    _sc, got = fit.solve(order, want_path=True)
    if got is None and fit.drop_pos is not None:
        fit.drop_pos = None
        order = arrange()
        _sc, got = fit.solve(order, want_path=True)
        if got is not None:
            notes.append("No order of these clips puts the fourth kill on the song's drop with every "
                         "kill on a hit, so the drop is a bonus here rather than a rule.")
    if got is None:
        # A part too short to hold every multi-kill clip whole: say so, and
        # let the search leave one out rather than give up the fit.
        fit.strict = False
        order = arrange()
        _sc, got = fit.solve(order, want_path=True)
        if got is not None:
            notes.append(f"The song part is too short to hold every clip of {MUST_KILLS} or more "
                         f"kills with each kill on a hit, so some were left out. Choose a longer part "
                         f"to keep them all.")
    if got is None:
        proj, more = _ordinary(clips, style_key, shape_it, **kw)
        return proj, ["No arrangement fits these clips to this part of the song, so the reel was "
                      "planned the usual way."] + more
    ev, path = got
    proj = _assemble(fit, ev, path, style, grid, tw, arrangement, hs_only, fmt, name, song, seed,
                     step, div, flash_share, notes)
    proj["saturation"] = sat_trim
    placed = {ev[e][0] for e, _r, _p in path}
    for bi in order:
        if bi not in placed:
            left_out([blocks[bi].clip["path"]],
                     "The song could not hold it with every kill on a hit; the clips that went in were stronger.")
    in_reel = {s["clip"] for s in proj["shots"]}
    proj["selection"] = [{"clip": c["path"], "name": str(c.get("name") or c["path"]),
                          "why": "" if c["path"] in in_reel else why_out.get(c["path"], "Left out to fit the reel's length.")}
                         for c in offered]
    shown = len(path) + sum(len(blocks[bi].leads) for bi in placed)
    if fit.drop_pos is not None:
        notes.append("The fourth kill lands on the song's drop; the three before it are the build.")
    notes.append(f"Perfect fit: {shown} kills from {len(placed)} clips, "
                 f"{sum(1 for _e, r, _p in path if r == 0)} cuts on the song's hits, "
                 f"after {fit.evals} arrangements were tried.")
    return proj, notes


def run_b_seconds(run_min: float, step: float) -> float:
    """The planner's opener run-up floor: the minimum run-up in whole grid steps."""
    return max(1, int(math.ceil(run_min / step - 1e-6))) * step


# ------------------------------------------------------------------ the project

def _assemble(fit: Fitter, ev, path, style, grid, tw, arrangement, hs_only, fmt, name, song, seed,
              step, div, flash_share, notes) -> dict:
    T = fit.song.T
    blocks = fit.blocks
    shots_ev: list[list[tuple]] = []        # each shot: [(event, r, p)]
    for st in path:
        if st[1] == 0:
            shots_ev.append([st])
        else:
            shots_ev[-1].append(st)
    anchors = [(grp[0][0], len(grp) - 1, grp[0][2]) for grp in shots_ev]
    # Cuts: reel zero, then the same cut the programme scored between each pair.
    _q0, _, p0 = anchors[0]
    _s0, pre0 = fit.start(ev)
    offset = float(T[p0] - pre0[p0])
    cuts = [offset]
    for (a, r, p), (e, _r2, p2) in zip(anchors, anchors[1:]):
        q = a + r
        _sc, cut = fit.edge(ev, q, r, e, np.array([T[p]]), np.array([T[p2]]))
        cuts.append(float(cut[0]))
    a, r, p = anchors[-1]
    _sc, stop = fit.end(ev, a + r, r, np.array([T[p]]), offset)
    cuts.append(float(stop[0]))
    shots = []
    for n, ((a, r, p), grp) in enumerate(zip(anchors, shots_ev)):
        bi, j, ka = ev[a]
        b = blocks[bi]
        c = b.clip
        kills = [ev[x][2] for x, _r, _p in grp]
        if j == 0:
            kills = b.leads + kills
        shots.append({
            "clip": c["path"], "clip_id": c.get("id") or studio.clip_id(c["path"]),
            "name": c.get("name", ""), "clip_seconds": b.seconds,
            "clip_mtime": int(c.get("mtime") or 0),
            "kills": [round(k, 3) for k in kills], "kill": round(ka, 3),
            "pre": round(float(T[p]) - cuts[n], 5), "duration": round(cuts[n + 1] - cuts[n], 5),
            "speed": fit.speed(ev, a), "fx": list(style.kill), "hero": False, "hero_fx": [],
            "camera": style.camera, "transition": "t01", "tlen": 0.0, "caption": "",
            "_block": bi, "_planned": fit.speed(ev, a), "_riders": len(grp) > 1,
        })
    # Captions on each clip's last shot, as the planner does; the hero clips'
    # captioned shots are the heroes.
    for n, s in enumerate(shots):
        if n == len(shots) - 1 or shots[n + 1]["_block"] != s["_block"]:
            total = sum(len(x["kills"]) for x in shots if x["_block"] == s["_block"])
            if total >= 2:
                s["caption"] = rulebook.label_for(total)
                if blocks[s["_block"]].hero:
                    s["hero"] = True
                    s["hero_fx"] = list(style.hero)
    pools = {k: list(v) for k, v in (
        ("kill", style.kill_pool), ("transition", style.transition_pool),
        ("hero", style.hero_pool), ("camera", style.camera_pool), ("speed", style.speed_pool))}
    studio._vary(shots, pools, style, seed, "all")
    # The speeds were the programme's to choose, and it planned through them.
    for s in shots:
        s["speed"] = s["_planned"]
    rulebook.budget(shots, pools)
    for s in shots:
        if s["_riders"]:
            s["speed"] = s["_planned"]         # its riders were put on hits at this speed
    index = {id(s): i for i, s in enumerate(shots)}

    def speed_ok(shot, speed):
        was = shot["speed"]
        shot["speed"] = speed
        ok = _valid(shots, index[id(shot)])
        shot["speed"] = was
        return ok
    if not studio.fast_reel(style, getattr(grid, "bpm", None)) and not style.speed_profile:     # see studio.plan
        rulebook.climax(shots, [blocks[s["_block"]].strength for s in shots], pools, speed_ok=speed_ok)
    if style.outro in ("e01", "e03", "e02") and len(shots) > 1 and speed_ok(shots[-1], "s06"):
        shots[-1]["speed"] = "s06"             # slowed as it leaves, as studio.plan() ends
    if fit.r.build and shots:
        shots[0]["fx"] = shots[0]["fx"][:1]
    _settle(shots, notes, pools["speed"])
    starts_b = [int(round(t / step)) for t in studio._starts(shots)]
    looks = {b.clip["path"]: b.look for b in blocks}
    rulebook.transitions(shots, starts_b, first_kill_beat=int(round(shots[0]["pre"] / step)),
                         looks=looks, pools=pools, flash_share=flash_share, beat=step, div=div)
    for s in shots:
        for k in ("_block", "_planned", "_riders"):
            s.pop(k, None)
    # Velocity's speed shape and Hype's shake, as studio.plan gives them: the style
    # is the same whichever planner laid the cuts.
    studio.speed_curves(shots, style)
    studio.signature_fx(shots, style)
    studio.signature_guard(shots, style)
    marks = [round(float(T[p]), 4) for _a, _r, p in anchors]
    return {
        "version": studio.VERSION, "name": name or f"{style.label} reel",
        "style": style.key, "format": fmt if fmt in studio.SIZES else "landscape",
        "song": str(song or ""), "song_offset": round(offset, 5),
        # The song's drop, for the beat engine -- see studio.plan, which sets
        # the same field. Two planners build this dict and a field added to one
        # of them is a field half the reels do not have.
        "song_drop": (round(float(grid.drop), 4)
                      if song and getattr(grid, "drop", None) else None),
        "intro": "i12" if fit.r.build else style.intro,
        "outro": "e03" if style.outro == "e01" else style.outro,
        "grade": style.grade, "vignette": style.vignette, "overlays": list(style.overlays),
        "handle": "", "music_db": 0.0, "game_db": 6.0, "duck": True, "saturation": 1.0,
        "beat": round(grid.beat, 6), "step": round(step, 6),
        "shaping": tw, "arrange": "fit", "pins": arrangement["pins"],
        "hs_only": hs_only, "seed": int(seed), "pools": pools, "shots": shots,
        "song_marks": marks,
    }


def _valid(shots: list[dict], i: int) -> bool:
    """Whether shot i, at its speed, shows every kill it lists once, at real speed or slower,
    inside its clip, without touching footage its neighbours from the same clip show."""
    s = shots[i]
    ps = studio.shot_pieces(s)
    a, b = studio._span(s)
    if a < -1e-4 or b > float(s["clip_seconds"]) + 1e-4:
        return False
    for k in s["kills"]:
        if not a - 1e-6 <= k <= b + 1e-6:
            return False
        out = studio.output_at(ps, k - a)
        rate = next((r for x, y, r in ps if x - 1e-9 <= out <= y + 1e-9), 1.0)
        if rate > 1.0 + 1e-6:
            return False
    for j in (i - 1, i + 1):
        if 0 <= j < len(shots) and shots[j]["clip"] == s["clip"]:
            a2, b2 = studio._span(shots[j])
            if min(b, b2) - max(a, a2) > FRAME:
                return False
    return True


def _settle(shots: list[dict], notes: list[str], pool: list[str] | None = None) -> None:
    """Take back any speed or freeze the effects pass gave a shot it cannot carry.

    The speed the programme planned a shot at always fits -- that is what it
    planned. Anything else the effects pass gave it (the climax's rush, the
    closer's slow exit, budget()'s real speed where a slowed shot had less
    footage) is kept only where it still shows every kill once; otherwise the
    planned speed comes back, and a freeze that no longer fits comes off.
    """
    undone = 0
    for _ in range(3):
        changed = False
        for i, s in enumerate(shots):
            if _valid(shots, i):
                continue
            changed = True
            planned = s.get("_planned") or "s00"
            s.pop("stretch", None)
            for sp in list(dict.fromkeys([planned] + [p for p in (pool or []) if p != "s00"] + ["s00"])):
                s["speed"] = sp
                if _valid(shots, i):
                    break
            if s["speed"] != planned:
                undone += 1
            if _valid(shots, i):
                continue
            # Not even the planned speed fits, so it is the freeze that does
            # not: it comes off and the planned speed goes back on.
            s["hero_fx"] = [h for h in s.get("hero_fx") or [] if studio.fam(h) != "h02"]
            s["fx"] = [f for f in s.get("fx") or [] if studio.fam(f) != "k04"]
            s["speed"] = planned
        if not changed:
            break
    if undone:
        notes.append(f"{undone} shot(s) changed speed: the one planned would have rushed past a kill "
                     f"or into footage another shot shows once its effects were on.")
