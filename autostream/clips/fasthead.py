"""Fast-paced headshot: a reel planned section by section, every kill a headshot on a beat.

WHY THIS EXISTS. The style ran on the general planner with a fixed 2.0 s pace,
and the render gate failed it on every song it was tried on: on That Acid
(174 BPM) nine shots in 43 s, shots of 4-9 s and kills 8-14 s off their marks;
on Skechers 33 shots from 12 files with nine fights shown twice. Its own spec
(docs/STYLE-FAST-PACED-HEADSHOT.md, measured off a hand-cut reference) has a
structure the general planner cannot express, and asked to turn that into
rules, ChatGPT gave the ones this module is (2026-10-21 review):

* IMPACT-LOCKED. Every kill lands on a beat; the cut is a run-up before it.
  The run-up is the spec's 0.62 of a shot, rounded to whole beats, so the cut
  is on a beat as well (120 BPM: 1 beat; 174: 2; 100: 1).
* THE UNIT IS THE BEAT MULTIPLE NEAREST ONE SECOND, 0.8-1.3 s: 2 beats at 100
  and 120 BPM, 3 at 174. Not a fixed 2.0 s, and not a fixed 18 bars.
* SECTIONS FIRST, CLIPS SECOND. Two bars of build (four kills two beats
  apart) into the drop; the body at the unit from the drop; a burst of about
  ten at half the unit (a 3-beat unit bursts at 1 and 2 beats, alternately,
  so every kill stays on a whole beat); ONE slow-motion kill on a bar line;
  and the finale, a real headshot double from one clip as one continuous
  shot, the longest of the reel, ending on a bar line. The body is sized so
  the whole reel is about 36 s, or the part chosen.
* HARD CONSTRAINTS, NOT PREFERENCES. Headshots only -- never a body kill to
  fill a gap; each clip once; no other kill of the clip inside a shot (it
  would land off the beat, and could be a kill shown twice); a finale is a
  real double or the reel says it has none.

Pure planning, no ffmpeg: ordinary Studio shots, which the timeline edits and
renders like any other reel.
"""
from __future__ import annotations

import random

from .director import Burst, Plan, _shot, END_AFTER

UNIT_TARGET = 1.0          # s: the body's shot, as near as the beat allows
UNIT_RANGE = (0.8, 1.3)
PRE_SHARE = 0.62           # of a shot before its kill, from the reference
BUILD_KILLS = 4            # two bars, a kill every two beats
BURST_SHOTS = 10
BURST_PRE = 0.30           # s: the burst's run-up, at most
AFTER_MIN = 0.15           # s every kill is held before the next shot's run-up
SLOW_PRE_BEATS = 2         # the slow-motion shot: two beats either side of its kill
SLOW_POST_BEATS = 2
SLOW_RATE = 0.5            # s01, half speed
# THE SLOW KILL AND THE FINALE ARE ONE BAR APART, at any tempo: the slow kill on a bar
# line, the finale's first kill on the next, its run-up the two beats the slow shot
# leaves. With three beats of run-up the gap between them read as time the director
# had left over (ChatGPT's review: "an explicit purpose and duration").
FINALE_PRE_BEATS = 2
FINALE_BEATS = 6           # at least, then on to the bar line
DOUBLE = (0.25, 2.5)       # s between a double's two headshots
REEL_SECONDS = 36.0
FX = ["k01snap"]           # one kill effect: the beat engine (o10) carries the rest
BIG = ("ACE", "CLUTCH", "LAST-ALIVE", "LAST ALIVE", "1V", "FLAWLESS")


def unit_beats(beat: float) -> int:
    """Beats in a body shot: the multiple nearest UNIT_TARGET, inside UNIT_RANGE if any is."""
    ks = list(range(1, 7))
    inside = [k for k in ks if UNIT_RANGE[0] <= k * beat <= UNIT_RANGE[1]]
    return min(inside or ks, key=lambda k: abs(k * beat - UNIT_TARGET))


def pre_beats(unit: int) -> int:
    """The run-up of a `unit`-beat shot, in whole beats: PRE_SHARE of it, at least one."""
    return max(1, min(unit - 1, round(PRE_SHARE * unit))) if unit > 1 else 1


def burst_steps(unit: int, n: int) -> list[int]:
    """Beats between burst kills: half the unit, on whole beats -- alternating when it is odd."""
    if unit % 2 == 0 or unit == 1:
        return [max(1, unit // 2)] * n
    lo, hi = unit // 2, unit // 2 + 1
    return [lo if i % 2 == 0 else hi for i in range(n)]


def headshots(clip: dict) -> list[float]:
    return [float(k) for k, h in zip(clip.get("kills") or [], list(clip.get("hs") or []) + [None] * 99)
            if h is True]


def score(clip: dict) -> float:
    text = " ".join([str(clip.get("name") or ""), *[str(x) for x in clip.get("labels") or []]]).upper()
    return 1.0 + (1.0 if any(w in text for w in BIG) else 0.0) + (0.5 if clip.get("fav") else 0.0)


def clear(clip: dict, kill: float, before: float, after: float) -> bool:
    """The clip has the footage, and no other kill inside it."""
    if kill - before < 0.02 or kill + after > float(clip.get("duration") or 0.0) - 0.02:
        return False
    return not any(kill - before - 0.05 < float(k) < kill + after + 0.05 and abs(float(k) - kill) > 1e-6
                   for k in clip.get("kills") or [])


def doubles(clip: dict) -> list[tuple[float, float]]:
    """Two headshots of one clip DOUBLE apart, nothing between them: a real multi-kill."""
    ks = sorted(float(k) for k in clip.get("kills") or [])
    hs = set(headshots(clip))
    return [(a, b) for a, b in zip(ks, ks[1:]) if a in hs and b in hs and DOUBLE[0] <= b - a <= DOUBLE[1]]


def choose_drop(shape, part, lead: float, loose: bool) -> float:
    """Where the body starts: the song's drop inside the part, else where the drums come in."""
    lo, hi = (part if part else (0.0, float(shape.seconds)))
    drops = sorted({float(d) for d in (getattr(shape, "drops", None) or [])}
                   | ({float(shape.drop)} if getattr(shape, "drop", None) else set()))
    ok = [d for d in drops if lo + lead <= d < hi - 8.0]
    main = getattr(shape, "drop", None)
    if ok:
        if (loose or not part) and main and any(abs(d - main) < 0.1 for d in ok):
            return float(main)
        return ok[0]
    di = getattr(shape, "drums_in", None)
    if di and lo + lead <= di < hi - 8.0:
        return float(di)
    return lo + lead


def plan(clips: list[dict], shape, rhythm=None, *, part: tuple[float, float] | None = None,
         seconds: float = REEL_SECONDS, seed: int = 0, loose: bool = False) -> Plan:
    """The reel's shots: build, body, burst, slow motion and the finale, each kill a headshot on a beat."""
    beats = [float(b) for b in shape.beats]
    if len(beats) < 16:
        raise ValueError("Fast-paced headshot needs a song with a beat to cut on.")
    beat = float(shape.beat)
    rng = random.Random(seed)
    pool = [c for c in clips if headshots(c)]
    if len(pool) < 8:
        raise ValueError(f"Fast-paced headshot is headshots only, and only {len(pool)} of these clips have "
                         f"a kill read as a headshot; it needs at least 8.")
    notes: list[str] = []
    unit = unit_beats(beat)
    downbeats = {i for i in range(len(beats)) if i % 4 == getattr(shape, "downbeat_pos", 0) % 4}
    D = choose_drop(shape, part, (2 * BUILD_KILLS + 2) * beat, loose)
    iD = min(range(len(beats)), key=lambda i: abs(beats[i] - D))
    want = (float(part[1]) - float(part[0])) if part else seconds
    if part and not loose:
        want = min(want, float(part[1]) - (beats[iD] - 2 * BUILD_KILLS * beat))
    want = min(want, float(shape.seconds) - (beats[iD] - (2 * BUILD_KILLS + 1) * beat))   # the song ends
    finale = sorted(((c, d) for c in pool for d in doubles(c)), key=lambda x: (x[1][1] - x[1][0], -score(x[0])))

    # ---- the body sized to the reel: build + body + burst + slow + finale ~ want
    fixed = 2 * BUILD_KILLS + sum(burst_steps(unit, BURST_SHOTS)) + 4 + SLOW_PRE_BEATS + FINALE_PRE_BEATS + FINALE_BEATS
    n_body = max(4, int((want / beat - fixed) // unit))
    singles = len(pool) - (1 if finale else 0)
    n_burst = BURST_SHOTS
    spare = singles - (BUILD_KILLS + 1)              # the build and the slow-motion kill
    # the headshot clips the shape is short of, which the page's "Add N more" adds (director.Plan.missing)
    missing = max(0, n_body + n_burst - spare)
    if spare < n_body + n_burst:
        n_burst = max(0, min(n_burst, spare // 3))
        n_body = max(1, spare - n_burst)
        notes.append(f"Only {singles} clips have a headshot to give, so the reel is shorter than "
                     f"{want:.0f} s: every clip plays once.")

    # A SHORT SONG GETS A SHORTER SHAPE, NOT THE GENERAL PLANNER. Espresso is 21 s: the
    # whole template cannot fit, so the burst shrinks, then the slow-motion kill goes,
    # then the body gives way a shot at a time -- and the reel says what it left out.
    # The body keeps at least four shots before the burst and the slow kill are given up.
    got = None
    variants = ((n_burst, True), (min(n_burst, 4), True), (min(n_burst, 4), False), (0, False))
    for floor in (min(4, n_body), 1):
        for burst, slow in variants:
            for nb in range(n_body, floor - 1, -1):
                got = _try(pool, finale, beats, beat, downbeats, iD, unit, nb, burst, rng, part, loose, slow)
                if got is not None:
                    break
            if got is not None:
                break
        if got is not None:
            break
    if got is None:
        raise ValueError("Fast-paced headshot could not fit these clips to the song.")
    shots, marks, kills, start, end, fin = got
    kinds = [s.pop("_kind") for s in shots]
    n_bu, has_slow = kinds.count("burst"), "slow" in kinds
    parts = [f"a cut every {unit} beat(s) ({unit * beat:.2f} s) from the drop at {beats[iD]:.1f} s"]
    if n_bu:
        parts.append(f"a burst of {n_bu} at half that")
    if has_slow:
        parts.append("one kill in slow motion")
    parts.append(f"{fin} to finish" if fin else
                 f"a single kill held to finish: none of these clips has two headshots within "
                 f"{DOUBLE[1]:.1f} s of each other, so there is no real multi-kill to end on")
    notes.insert(0, f"Fast-paced headshot: {len(shots)} headshots; " + ", ".join(parts) + ".")
    if n_bu < BURST_SHOTS or not has_slow:
        notes.append("The song or the part is too short for the whole shape, so "
                     + ("the burst is shorter" if n_bu else "there is no burst")
                     + ("" if has_slow else " and there is no slow-motion kill") + ".")
    return Plan(part=(round(start, 4), round(end, 4)), drop=beats[iD], shots=shots, marks=marks,
                kills=kills, notes=notes, missing=missing)


def _try(pool, finale, beats, beat, downbeats, iD, unit, n_body, n_burst, rng, part, loose, slow=True):
    """One attempt at the whole reel with these counts, or None when a slot cannot be filled."""
    pb = pre_beats(unit)
    # ---- the kill on each slot, as a beat index, and its run-up and kind
    slots: list[dict] = []
    for j in range(BUILD_KILLS):
        slots.append({"i": iD - 2 * (BUILD_KILLS - j), "pre": pre_beats(2) * beat, "kind": "build"})
    for j in range(n_body):
        slots.append({"i": iD + j * unit, "pre": pb * beat, "kind": "drop" if j == 0 else "body"})
    i = iD + (n_body - 1) * unit
    for s in burst_steps(unit, n_burst):
        i += s
        slots.append({"i": i, "pre": BURST_PRE, "kind": "burst"})
    if slow:
        i_slow = next((k for k in range(i + SLOW_PRE_BEATS + 1, len(beats)) if k in downbeats), None)
        if i_slow is None:
            return None
        slots.append({"i": i_slow, "pre": SLOW_PRE_BEATS * beat, "kind": "slow"})
        i_fin = i_slow + SLOW_POST_BEATS + FINALE_PRE_BEATS
    else:
        i_fin = i + FINALE_PRE_BEATS + 1
    if i_fin >= len(beats) or slots[0]["i"] < 1:
        return None
    if part and not loose and beats[i_fin] + (FINALE_BEATS - FINALE_PRE_BEATS) * beat > float(part[1]) + 1e-6:
        return None
    slots.append({"i": i_fin, "pre": FINALE_PRE_BEATS * beat, "kind": "finale"})
    T = [beats[s["i"]] for s in slots]
    # every run-up leaves the kill before it AFTER_MIN on screen
    for n in range(1, len(slots)):
        slots[n]["pre"] = max(0.08, min(slots[n]["pre"], T[n] - T[n - 1] - AFTER_MIN))
    start = T[0] - slots[0]["pre"]
    if part and not loose and start < float(part[0]) - 1e-6:
        return None

    # ---- who fills each slot: the finale's double first, the drop next, then in order
    used: set[str] = set()
    picks: list[tuple[dict, list[float]] | None] = [None] * len(slots)
    fin_name = ""
    n_fin = len(slots) - 1
    fin_need_after = None
    for c, (a, b) in finale:
        after = max(FINALE_BEATS * beat - FINALE_PRE_BEATS * beat, (b - a) + END_AFTER)
        if clear_double(c, a, b, slots[n_fin]["pre"], after):
            picks[n_fin] = (c, [a, b])
            used.add(c["path"])
            fin_name = f"{c.get('name') or 'a'}'s double"
            fin_need_after = after
            break
    order = sorted(pool, key=lambda c: (score(c), rng.random()), reverse=True)
    rank = [n for n, s in enumerate(slots) if s["kind"] == "drop"] + \
           [n for n, s in enumerate(slots) if s["kind"] not in ("drop", "finale")] + \
           ([n_fin] if picks[n_fin] is None else [])
    for n in rank:
        before, after = _window(slots, T, n, beat, fin_need_after)
        rate = SLOW_RATE if slots[n]["kind"] == "slow" else 1.0
        pick = None
        for c in order:
            if c["path"] in used:
                continue
            k = next((k for k in headshots(c) if clear(c, k, before * rate, after * rate)), None)
            if k is not None:
                pick = (c, [k])
                break
        if pick is None:
            return None
        picks[n] = pick
        used.add(pick[0]["path"])

    # ---- the shots: each ends where the next one's run-up begins; the last on a bar line
    shots, marks, kills = [], [], []
    for n, (s, (c, ks)) in enumerate(zip(slots, picks)):
        if n + 1 < len(slots):
            dur = (T[n + 1] - slots[n + 1]["pre"]) - (T[n] - s["pre"])
        else:
            last = T[n] + (ks[-1] - ks[0])
            need = max(last + END_AFTER, T[n] + (FINALE_BEATS - FINALE_PRE_BEATS) * beat)
            # on the bar line, unless that holds it more than two beats past the finale's length
            bar = next((beats[k] for k in range(s["i"], len(beats))
                        if k in downbeats and beats[k] >= need and beats[k] - need <= 2 * beat + 1e-6),
                       next((beats[k] for k in range(s["i"], len(beats)) if beats[k] >= need), need))
            room = float(c.get("duration") or 0.0) - 0.02 - ks[0]
            dur = s["pre"] + min(bar - T[n], room)
        b = Burst(c, list(ks), [True] * len(ks))
        shot = _shot(b, ks[0], ks, s["pre"], max(0.1, dur), fx=list(FX))
        if s["kind"] == "slow":
            shot["speed"] = "s01"
        shot["_kind"] = s["kind"]
        shots.append(shot)
        marks.append(round(T[n], 4))
        kills += [round(T[n] + (k - ks[0]), 4) for k in ks]
    end = start + sum(s["duration"] for s in shots)
    return shots, marks, sorted(kills), start, end, fin_name


def _window(slots, T, n, beat, fin_after):
    """Footage a slot's kill needs before and after it, in output seconds."""
    before = slots[n]["pre"]
    if n + 1 < len(slots):
        after = T[n + 1] - slots[n + 1]["pre"] - T[n]
    else:
        after = fin_after if fin_after is not None else (FINALE_BEATS - FINALE_PRE_BEATS) * beat + END_AFTER
    return before, after


def clear_double(clip: dict, a: float, b: float, before: float, after: float) -> bool:
    """A double's clip has the footage, and no third kill inside the shot."""
    if a - before < 0.02 or a + after > float(clip.get("duration") or 0.0) - 0.02:
        return False
    return not any(a - before - 0.05 < float(k) < a + after + 0.05 and abs(float(k) - a) > 1e-6
                   and abs(float(k) - b) > 1e-6 for k in clip.get("kills") or [])
