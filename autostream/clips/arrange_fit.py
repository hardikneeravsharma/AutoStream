"""Perfect fit: the reel's order and its kills' places in the song, searched together.

A RESEARCH PROTOTYPE, NOT YET WIRED TO THE PAGE. It takes exactly what
studio.plan() takes and returns a project studio.normalise(), derive() and the
render accept, so the two can be compared reel for reel.

MEASURED, re-planning five of the player's own reels from their selections
(the same emblem check, action check and song analysis for both planners):

    reel (style)         clips kept     kills kept     kills of 3-4-kill clips
                         plan -> fit    plan -> fit    plan -> fit
    dwayIR (hype)        14 -> 25/25    30 -> 42/42    10 -> 11/11
    Aftrhrs (story)      17 -> 27/27    38 -> 49/49    17 -> 18/18
    ambiforcash (hype)   13 -> 13/13    25 -> 25/25    13 -> 13/13
    Can't Hold Us (vel)   8 ->  8/8     14 -> 14/14     6 ->  6/6
    Cradles (short)      10 -> 11/11    16 -> 17/17     3 ->  3/3

Every shot's kill on a hit to the frame on all five (plan: 26/28 and 22/23
on two of them), no footage played twice, no run-up under the minimum (plan:
five on Can't Hold Us), no kill inside a ramp. The cost is time -- 15-35 s of
order search against plan()'s milliseconds; the programme alone is 0.1-0.3 s
-- and longer reels, because nothing is left out: dwayIR 43 -> 52 s,
Aftrhrs 99 -> 118 s.

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
        it, at real speed, wherever the footage puts it. Only kills within
        studio.OWN_KILLS_WITHIN of the one before may ride.

    Given an order of clips, the best choice of anchor/rider for every event
    and the best hit for every anchor is an exact dynamic programme over
    (event, which kill anchors the shot it is in, which hit that anchor is on).
    Every hard rule is a feasibility test on one transition, so the programme
    never produces a reel that breaks one:

      * a cut exists between two anchors that leaves the shot before its
        footage up to its own last kill plus a hold, and the shot after at
        least the minimum run-up, inside what each clip has;
      * two shots of one clip never overlap in the footage: the reel gap
        between their anchors is at most the footage gap, so a jump cut only
        ever REMOVES footage;
      * a whole clip may be left out only when it has fewer than MUST_KILLS
        kills -- a clip with a triple or a quadra is shown whole or the
        search reports it cannot be.

    The ORDER is then searched around that programme: simulated annealing over
    swaps, moves and reversals of the clips, starting from the rulebook's own
    build order, each candidate scored by the programme plus terms for the
    opener, the closer, the climax two thirds in and neighbouring clips that
    look alike. Seconds rather than milliseconds -- slow is acceptable here.
"""
from __future__ import annotations

import dataclasses
import math
import random
import time
import zlib
from dataclasses import dataclass, field

import numpy as np

from . import rulebook, studio, studio_refs

FRAME = 1.0 / studio.FPS
NEG = -1e15

# ------------------------------------------------------------------ the hard rules

# Kills this close in the footage may share one continuous shot.
JOIN_WITHIN = studio.OWN_KILLS_WITHIN
# Held after the last kill of a shot: one kill gets reel.MIN_AFTER, several get
# the hold the planner already gives a shot's own later kills.
HOLD_ONE = 0.22
HOLD_LAST = studio.OWN_KILL_HOLD
# A jump cut inside one clip that removes less footage than this is a stutter,
# not a cut: allowed (it keeps a kill on its hit) but scored down.
MIN_JUMP = 0.25
# The longest a shot may run on after its last kill.
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
    "short": 2.0,        # a run-up under the readable one, as a share of it
    "long": 0.4,         # per second of run-up past the style's long shot
    "glitch": 1.5,       # a jump cut removing under MIN_JUMP of footage
    "open": 2.0,         # the opener's strength
    "close": 2.0,        # the closer's strength
    "climax": 3.0,       # the strongest clip's distance from two thirds in
    "look": 1.0,         # two neighbouring clips in the same place
    "shape": 0.3,        # two neighbouring clips with the same number of kills
    "length": 0.3,       # per second past the format's longest reel
    "late": 0.3,         # per second the opener lands after the song's first big hit
}


@dataclass
class Block:
    """One chosen clip: the kills the reel must show, in footage order."""
    clip: dict
    kills: list[float]                 # anchor-able kills, ascending
    leads: list[float]                 # kills shown only inside the first kill's run-up
    seconds: float
    strength: float = 0.0              # 0..1 within the selection
    look: list[float] | None = None
    first_run: float = 0.0             # the first kill's minimum run-up

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
    run_min: float             # the least run-up any kill gets
    readable: float            # a run-up this long reads as a fight
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


# ------------------------------------------------------------------ the programme

class Fitter:
    """The exact programme for one order, and the order search around it."""

    def __init__(self, blocks: list[Block], song: Song, rules: Rules, weights: dict | None = None,
                 strict: bool = True):
        self.blocks = blocks
        self.song = song
        self.r = rules
        self.w = dict(WEIGHTS, **(weights or {}))
        # Strict: a clip of MUST_KILLS or more is never left out. Relaxed only
        # when no reel at all keeps every one of them -- a part too short.
        self.strict = strict
        self.evals = 0
        w = self.w
        # Per-position parts of an anchor's score that do not depend on the clip.
        self.node_hit = np.where(song.hit, w["hit"] * song.s, w["off_hit"])
        self.node_str = w["match"] * song.s + w["big"] * song.big + w["drop"] * song.drop
        self._ride_cache: dict[float, np.ndarray] = {}
        looks = [b.look for b in blocks]
        n = len(blocks)
        self.same_place = np.zeros((n, n), bool)
        for i in range(n):
            for j in range(n):
                if i != j:
                    self.same_place[i, j] = rulebook.look_similarity(looks[i], looks[j]) >= rulebook.LOOK_SAME

    # -------------------------------------------------- pieces of the score

    def _ride(self, delta: float) -> np.ndarray:
        key = round(delta, 4)
        got = self._ride_cache.get(key)
        if got is None:
            d = self.song.hit_dist(self.song.T + delta)
            got = np.where(d <= FRAME + 1e-6, self.w["ride1"], np.where(d <= 3 * FRAME + 1e-6, self.w["ride3"], 0.0))
            self._ride_cache[key] = got
        return got

    def _node(self, b: Block) -> np.ndarray:
        return self.node_hit + (0.5 + b.strength) * self.node_str

    def edge(self, ev: list[tuple], q: int, r: int, e: int, Tp, Tq):
        """Score and cut of a cut from shot (anchor q - r, last kill q) to anchor e.

        Tp and Tq are the two anchors' song times, any matching shapes.
        -> (score, cut), score NEG where the cut is impossible.
        """
        R, w = self.r, self.w
        bq, kq = ev[q][0], ev[q][2]
        ka = ev[q - r][2]
        be, ke = ev[e][0], ev[e][2]
        lastoff = kq - ka
        tail_need = HOLD_LAST if r > 0 else HOLD_ONE
        G = Tq - Tp
        run_min = self.blocks[be].first_run if ev[e][1] == 0 else R.run_min
        if bq == be:
            src = ke - ka
            lo = Tp + lastoff + tail_need
            hi = Tq - run_min
            ok = (G <= src + 1e-6) & (lo <= hi + 1e-9)
            removed = src - G
            glitch = (removed > FRAME) & (removed < MIN_JUMP)
        else:
            D = self.blocks[bq].seconds
            tail_need = min(tail_need, max(0.0, D - kq))
            lo = np.maximum(Tp + lastoff + tail_need, Tq - min(ke, R.max_lead))
            hi = np.minimum(np.minimum(Tp + (D - ka) - 1e-4, Tq - run_min), Tp + lastoff + TAIL_MAX)
            ok = lo <= hi + 1e-9
            glitch = False
        cut = np.clip(Tp + lastoff + max(tail_need, R.tail_pref), lo, np.maximum(lo, hi))
        run = Tq - cut
        tail = cut - Tp - lastoff
        gstar = max(R.gap, lastoff + tail_need + run_min)
        with np.errstate(divide="ignore", invalid="ignore"):
            pace = np.log(np.maximum(G, 1e-3) / gstar) ** 2
        sc = (-w["pace"] * pace
              - w["tail"] * np.maximum(0.0, tail - max(tail_need, R.tail_pref))
              - w["short"] * np.maximum(0.0, R.readable - run) / R.readable
              - w["long"] * np.maximum(0.0, run - R.run_cap)
              - w["glitch"] * glitch)
        if bq != be:
            sc = sc - w["look"] * self.same_place[bq, be] - w["shape"] * (
                self.blocks[bq].total == self.blocks[be].total)
        return np.where(ok, sc, NEG), cut

    def end(self, ev: list[tuple], q: int, r: int, Tp, offset_est: float):
        """Score and reel end of finishing on shot (anchor q - r, last kill q). -> (score, end)"""
        R, w = self.r, self.w
        bq, kq = ev[q][0], ev[q][2]
        ka = ev[q - r][2]
        D = self.blocks[bq].seconds
        room = max(0.0, D - kq)
        need = min(HOLD_LAST if r > 0 else HOLD_ONE, room)
        tail = min(max(need, R.close_want), room)
        stop = Tp + (kq - ka) + tail
        sc = -w["length"] * np.maximum(0.0, stop - offset_est - R.soft_max)
        return np.where(stop <= R.end_cap + 1e-6, sc, NEG), stop

    def start(self, ev: list[tuple]):
        """-> (score, run-up) for the opener's anchor at each position."""
        R, w, T = self.r, self.w, self.song.T
        b = self.blocks[ev[0][0]]
        k0 = ev[0][2]
        pre = np.minimum(np.minimum(k0, R.open_want), np.minimum(T - R.floor, R.max_lead))
        ok = (pre >= b.first_run - 1e-9) & (T >= R.first - 0.3) & (T <= R.first + R.start_window)
        sc = -w["late"] * np.maximum(0.0, T - R.first)
        return np.where(ok, sc, NEG), pre

    # -------------------------------------------------- the programme itself

    def events(self, order: list[int]) -> list[tuple]:
        """(block, index in block, kill time) for every event, in reel order."""
        return [(bi, j, k) for bi in order for j, k in enumerate(self.blocks[bi].kills)]

    def solve(self, order: list[int], want_path: bool = False):
        """The best reel for this order of clips. -> (score, path or None)

        path: [(event, r, position)] for every event that was placed, in reel
        order, where r is how many kills back its shot's anchor is (0 = it is
        the anchor) -- plus the events of left-out clips are absent.
        """
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
        V: list[np.ndarray] = []
        back: list[tuple | None] = []
        s0, _pre0 = self.start(ev)
        V.append((s0 + self._node(self.blocks[ev[0][0]]))[None, :])
        back.append(None)
        arP = np.arange(P)
        for e in range(1, len(ev)):
            be, je, ke = ev[e]
            b = self.blocks[be]
            # Riders: the same continuous shot as the kill before.
            rmax = 0
            if je > 0 and ke - ev[e - 1][2] <= JOIN_WITHIN + 1e-9:
                rmax = min(MAX_RIDERS, V[e - 1].shape[0])
            Ve = np.full((rmax + 1, P), NEG)
            for r in range(1, rmax + 1):
                a = e - r
                Ve[r] = V[e - 1][r - 1] + self._ride(ke - ev[a][2])
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
                    pen += w["kill"] * self.blocks[skipped].total
                    q = first_of[skipped] - 1
                    if q < 0:
                        break
                    preds.append((q, pen))
            best = np.full(P, NEG)
            bq = np.zeros(P, int)
            br = np.zeros(P, int)
            bp = np.zeros(P, int)
            Tq = song.T[:, None]
            Tp = song.T[song.IDX]
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
                pen += w["kill"] * self.blocks[gone].total
            q = last_of[order[n - 1 - s]]
            for r in range(V[q].shape[0]):
                sc, _stop = self.end(ev, q, r, T, off_est)
                tot = V[q][r] + sc - pen
                p = int(tot.argmax())
                if tot[p] > best_sc:
                    best_sc, best_state = float(tot[p]), (q, r, p)
        if best_state is None or best_sc <= NEG / 2:
            return NEG, None
        best_sc += self.order_score(order)
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
               iterations: int = 600, budget: float = 30.0, seed: int = 0) -> tuple[float, list[int]]:
        """Simulated annealing over the order. `fixed` pins block -> position."""
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
        began = time.perf_counter()
        for it in range(iterations):
            if time.perf_counter() - began > budget:
                break
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
                            look=looks.get(path), first_run=first_run))
    top = max((b.strength for b in blocks), default=1.0) or 1.0
    for b in blocks:
        b.strength = b.strength / top
    return blocks, why, lost


def plan(clips: list[dict], style_key: str = studio.DEFAULT_STYLE, *, shape=None,
         song: str = "", fmt: str = "landscape", name: str = "",
         max_seconds: float = 0.0, seed: int | None = None,
         measure=None, confirm=None, theirs=None,
         part: tuple[float, float] | None = None,
         template: dict | None = None, shape_it: dict | None = None,
         iterations: int = 600, budget: float = 40.0, weights: dict | None = None,
         ) -> tuple[dict, list[str]]:
    """studio.plan()'s signature and result, with the order and timing searched together.

    Without a song that has hits there is nothing to fit, and studio.plan()
    makes the reel as it always has.
    """
    if shape is None or not song or not getattr(shape, "hits", None):
        return studio.plan(clips, style_key, shape=shape, song=song, fmt=fmt, name=name,
                           max_seconds=max_seconds, seed=seed, measure=measure, confirm=confirm,
                           theirs=theirs, part=part, template=template, shape_it=shape_it)
    style = studio.STYLE.get(style_key) or studio.STYLE[studio.DEFAULT_STYLE]
    if template:
        style = studio.templated(style, template)
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

    # ---- the rules for this reel
    floor = part_start if part_len else 0.0
    end_cap = (part_start + part_len) if part_len else grid.seconds - 0.5
    if part_len:
        first = studio._first_kill(grid.hits, [], earliest=floor + run_min)
    else:
        first = studio._first_kill(grid.hits, grid.big, earliest=run_b_seconds(run_min, step),
                                   drums_in=grid.drums_in or 0.0)
    open_want = max(run_min, max(meas.get("first_shot") or 2.0, 2.0) * 0.8)
    closer = rulebook.ENDING_BEATS * beat if style.outro in ("e01", "e03", "e02") else max(HOLD_ONE, beat)
    soft_max = max_seconds or rulebook.MAX_SECONDS.get(fmt, 86.0)
    if part_len:
        soft_max = min(soft_max, part_len)
    rules = Rules(gap=gap, run_min=run_min, readable=max(run_min, min(1.0, 0.6 * gap)),
                  run_cap=max(1.5, 2.0 * gap), max_lead=rulebook.MAX_LEAD_UP_SECONDS,
                  tail_pref=min(beat, 0.4 * gap), open_want=open_want, close_want=closer,
                  floor=floor, end_cap=end_cap, first=first, start_window=max(2.0 * gap, 2.0 * beat),
                  soft_max=soft_max)
    reach = rulebook.MAX_LEAD_UP_SECONDS + TAIL_MAX + JOIN_WITHIN * 2
    tune = Song.of(grid, max(floor, first - rules.max_lead - 1.0), end_cap, reach)
    fit = Fitter(blocks, tune, rules, weights)

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
    if seed is None:
        seed = zlib.crc32(",".join(str(b.clip["path"]) for b in blocks).encode("utf-8")) & 0x7FFFFFFF
    def arrange():
        if arrangement["arrange"] == "time":
            return starts[2]
        return fit.search(starts, fixed, iterations=iterations, budget=budget, seed=seed)[1]
    order = arrange()
    _sc, got = fit.solve(order, want_path=True)
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
        proj, more = studio.plan(clips, style_key, shape=shape, song=song, fmt=fmt, name=name,
                                 max_seconds=max_seconds, seed=seed, measure=measure, confirm=confirm,
                                 theirs=theirs, part=part, template=template, shape_it=shape_it)
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
    q0, _, p0 = anchors[0]
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
            "speed": "s00", "fx": list(style.kill), "hero": False, "hero_fx": [],
            "camera": style.camera, "transition": "t01", "tlen": 0.0, "caption": "",
            "_block": bi,
        })
    # Captions on each clip's last shot, as the planner does; heroes are the
    # strongest captioned clips.
    for n, s in enumerate(shots):
        if n == len(shots) - 1 or shots[n + 1]["_block"] != s["_block"]:
            total = sum(len(x["kills"]) for x in shots if x["_block"] == s["_block"])
            if total >= 2:
                s["caption"] = rulebook.label_for(total)
    # Ranked among the CAPTIONED shots: ranked among all of them, a quadra's
    # four shots took four of dwayIR's six hero places and only one could be
    # a hero, so neither quadra was.
    ranked = sorted((i for i, s in enumerate(shots) if s["caption"]),
                    key=lambda i: (-blocks[shots[i]["_block"]].strength, i))
    for i in ranked[:max(1, len(shots) // 6)]:
        shots[i]["hero"] = True
        shots[i]["hero_fx"] = list(style.hero)
        shots[i]["speed"] = style.hero_speed
    for s in shots:
        if not s["hero"]:
            s["speed"] = style.speed
    pools = {k: list(v) for k, v in (
        ("kill", style.kill_pool), ("transition", style.transition_pool),
        ("hero", style.hero_pool), ("camera", style.camera_pool), ("speed", style.speed_pool))}
    studio._vary(shots, pools, style, seed, "all")
    rulebook.budget(shots, pools)
    index = {id(s): i for i, s in enumerate(shots)}

    def speed_ok(shot, speed):
        was = shot["speed"]
        shot["speed"] = speed
        ok = _valid(shots, index[id(shot)])
        shot["speed"] = was
        return ok
    rulebook.climax(shots, [blocks[s["_block"]].strength for s in shots], pools, speed_ok=speed_ok)
    if style.outro in ("e01", "e03", "e02") and len(shots) > 1:
        shots[-1]["speed"] = "s06"
    _settle(shots, notes, pools["speed"])
    starts_b = [int(round(t / step)) for t in studio._starts(shots)]
    looks = {b.clip["path"]: b.look for b in blocks}
    rulebook.transitions(shots, starts_b, first_kill_beat=int(round(shots[0]["pre"] / step)),
                         looks=looks, pools=pools, flash_share=flash_share, beat=step, div=div)
    for s in shots:
        s.pop("_block", None)
    marks = [round(float(T[p]), 4) for _a, _r, p in anchors]
    return {
        "version": studio.VERSION, "name": name or f"{style.label} reel",
        "style": style.key, "format": fmt if fmt in studio.SIZES else "landscape",
        "song": str(song or ""), "song_offset": round(offset, 5),
        "intro": style.intro, "outro": "e03" if style.outro == "e01" else style.outro,
        "grade": style.grade, "vignette": style.vignette, "overlays": list(style.overlays),
        "handle": "", "music_db": 0.0, "game_db": 6.0, "duck": True, "saturation": 1.0,
        "beat": round(grid.beat, 6), "step": round(step, 6),
        "shaping": tw, "arrange": arrangement["arrange"], "pins": arrangement["pins"],
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
    """Take back any speed or freeze the effects mix gave a shot it cannot carry.

    Every shot was fitted at real speed, so real speed always fits; a ramp, a
    slow exit or a freeze is kept only where it still shows every kill. A ramp
    that does not fit is swapped for another of the style's ramps that does
    before the shot is given up to real speed: velocity's s04 rushes the run-up
    at 2.2x and needs twice the footage, while s03 rushes only after the kill.
    """
    undone = 0
    others = list(dict.fromkeys([p for p in (pool or []) if p != "s00"] + ["s03", "s05"]))
    for _ in range(3):
        changed = False
        for i, s in enumerate(shots):
            if _valid(shots, i):
                continue
            changed = True
            if s["speed"] != "s00" or s.get("stretch"):
                was = s["speed"]
                s.pop("stretch", None)
                for sp in [x for x in others if x != was] + ["s00"]:
                    s["speed"] = sp
                    if _valid(shots, i):
                        break
                if s["speed"] == "s00":
                    undone += 1
                if _valid(shots, i):
                    continue
            s["hero_fx"] = [h for h in s.get("hero_fx") or [] if studio.fam(h) != "h02"]
            s["fx"] = [f for f in s.get("fx") or [] if studio.fam(f) != "k04"]
        if not changed:
            break
    if undone:
        notes.append(f"{undone} speed ramp(s) were taken back to real speed: they would have rushed "
                     f"past a kill or into footage another shot shows.")
