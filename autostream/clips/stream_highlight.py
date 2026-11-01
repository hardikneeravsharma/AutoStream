"""Stream highlights: long, continuous stretches of the stream, the way creators cut them.

WHY THIS EXISTS
    The match recap (match_video.py) is a broadcast product: twelve short moments,
    a title card, round cards, a score bar, a half-time card, a result card. The
    player watched it at full quality and said it was "nowhere near" the videos he
    measures it against -- Sinatraa's and Subroza's single-stream highlights -- and
    ChatGPT, shown both at 1080p, agreed it was "fundamentally the wrong editing
    format" (2026-11-01, 4.7/10 against the references' 8.9 for this format).

    What those videos do, measured on "HOW IS THIS RADIANT?? (30+ KILLS)" and
    "TERRORIZING Valorant Ranked With Mooda": about three matches in 14-25
    minutes; long real-time stretches, deaths and scoreboard and all; rounds
    compressed by cutting what is dead, never by a card; no title, round, score
    or result graphics at all; the face and the voice carry it; edits react to
    something (a punch-in, a cut to the face) rather than decorate every kill.

    So the question this asks is not "which twelve moments represent the match"
    but "which continuous parts of this stream are worth watching, and how much
    of what is around them does a viewer need".

HOW
    Everything the clipper already knows becomes an EVENT on the recording's
    clock: the player's kills, their deaths, their reactions on the microphone.
    Events close together are one STRETCH, scored. A stretch starts where the
    SITUATION started -- the first contact of the fight it belongs to, the moment
    the player was left alone, the plant -- not a fixed number of seconds before
    its best event: v1 did that and opened its best stretch on six seconds of the
    player holding an angle (ChatGPT, v1 review: 6.7/10, "start at the beginning
    of the interesting situation"). It ends when the round is decided and the
    player has finished reacting, and never runs on into the next round. Inside a
    stretch only DEAD time is cut, and dead means quiet on the mic AND in the game
    with no fight brewing -- a silent clutch is tension, not dead air.

    The output is a list of CUTS (spans of the source) and where in them to
    punch in. Nothing here draws text.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger("autostream.clips.stream_highlight")

HZ = 20.0                  # the level tracks' frame rate (reactions.HZ)
VOICED_DB = -60.0          # reactions.VOICED_DB: the mic is gated, so above this is speech
SPEECH_JOIN = 1.0          # words closer than this are one run of talking

# WHERE A STRETCH STARTS. The fight it belongs to is found by walking back from
# its first event through the round's kills -- anyone's -- while they come within
# CHAIN of each other: the first of them is first contact. SETUP seconds of the
# walk-in are kept before that (ChatGPT: 2-6 s of visual setup). When the player
# is talking into the start, it moves back to where the talking began, by at most
# SPEECH_BACK: talk is context worth keeping, never a reason on its own.
CLUSTER_GAP = 12.0         # events closer than this belong to one stretch
CHAIN = 10.0
SETUP = 6.0
STATE_SETUP = 2.0          # before a last-alive or plant moment: "1-3 s of preceding context"
SITUATION_BACK = 30.0      # a plant or last-alive this long before still frames the stretch
SPEECH_BACK = 6.0
BEFORE_BARRIER = 2.0       # a stretch does not start further into the buy phase than this...
BUY_TALK = 12.0            # ...unless the player is talking, up to this far
REACTION_SETUP = 6.0       # a reaction with no fight before it: this much of what led to it

# WHERE IT ENDS. TAIL after the last play; a reaction is its own landing and needs
# only REACTION_TAIL. A round decided within RESOLVE of that is played to its
# result; the match's last round is played to the game's own VICTORY / DEFEAT
# screen. Nothing runs past AFTER_ROUND into the next round's buy phase.
TAIL = 3.0
REACTION_TAIL = 1.5
# The aftermath of a reaction is often the entertaining part -- the disbelief, the
# laugh after the scream (ChatGPT, v2 review: round 10 at 22 s was "probably too
# tight"). Turns of talk that follow within AFTER_TURN_GAP are one continuation,
# kept to REACTION_TALK past the loud part, with AFTER_TALK after the last word.
REACTION_TALK = 10.0
AFTER_TURN_GAP = 1.5
AFTER_TALK = 3.0
RESOLVE = 8.0
FINAL_REACH = 45.0         # the last round is played to its result from this far: it ends the video
RESULT_HOLD = 2.5
FINAL_HOLD = 7.0
AFTER_ROUND = 7.0
MERGE_GAP = 6.0            # stretches closer than this are played through, not cut between

# WHAT THE VIEWER SEES (shape()). After the player dies the game keeps
# CAM_AFTER_DEATH for the kill and the combat report; their talk after that is the
# CAM layout, for at most CAM_LONGEST, and a turn under CAM_SHORTEST is not worth a
# layout change. The round's own WON / LOST banner, RESULT_IN to RESULT_OUT after
# it was decided, closes every round that does not already show it (it is up from
# about 1 s to 5 s after; RESULT_SEEN into it counts as shown).
CAM_AFTER_DEATH = 2.5
CAM_LONGEST = 20.0
CAM_SHORTEST = 2.0
RESULT_IN = 0.8
RESULT_OUT = 3.3
RESULT_SEEN = 1.5
SNAP = 6.0                 # how far a cut moves to a sentence's edge (snap())
SHORTEST = 8.0

# DEAD TIME: DEAD seconds or more with no speech, no game-audio activity, no event,
# and nothing brewing -- the seconds before any contact, a post-plant, a last-alive
# stand are all protected. Each side keeps a little so the cut lands on movement.
DEAD = 6.0
DEAD_KEEP_IN = 1.5
DEAD_KEEP_OUT = 2.0
HOLD_BEFORE_CONTACT = 4.0
GAME_RISE_DB = 6.0         # game audio this far over its own rolling median is activity
GAME_WINDOW = 5.0          # seconds of that rolling median

# HOW MUCH VIDEO A MATCH EARNS. ChatGPT's targets from the references: one strong
# match 5-8 minutes, a quiet one 3-5. These are ceilings; a stretch has to score
# MIN_SCORE to be kept at all, and nothing is padded to reach a length.
PER_MATCH = 420.0
MIN_SCORE = 2.0
# A SESSION -- one recording, several matches -- is the references' own shape:
# about three matches in 14-25 minutes; ChatGPT's target 12-18. The best
# SESSION_MATCHES are covered, each given MATCH_LEAST to MATCH_MOST by how good it
# is against the session's best, and the rest are left out whole rather than every
# match thinned. A match whose best stretches add up to under MATCH_FLOOR has
# nothing in it worth a viewer's time.
FLOOR = 45.0               # less than this in a whole recording is not a video
SESSION_MATCHES = 3
MATCH_LEAST = 240.0
MATCH_MOST = 360.0
MATCH_FLOOR = 8.0
# A DEATHMATCH has no rounds and a kill every few seconds: clustered at 12 s, the
# Drift TDM of 2026-10-25 came out as one five-minute stretch. Its fights are
# shorter apart, and a kill there is cheaper than one in a round that counts.
RESPAWN_GAP = 5.0
RESPAWN_KILL = 0.5
SPAN_BEFORE = 60.0         # before a match's first kill: the buy phase and the walk out
SPAN_AFTER = 30.0          # after its last: the result screen and what was said about it

# SCORING. A kill is the unit. Kills close together are worth more than apart; a
# reaction by how hard the player reacted (reactions.Reaction.score is dB-seconds
# over their own speaking level; the rage scream of 2026-10-25 was 24). How much
# the round mattered is a BOUNDED nudge -- this is a creator video, not a match
# recap: "a strong 3K with rage should beat an isolated 2K at an important score".
# How much the player TALKED is not scored at all: talking is context, a reaction
# is the evidence (ChatGPT, v1 review).
KILL = 1.0
MULTI = 1.0                # per kill beyond the first inside MULTI_SPAN
MULTI_SPAN = 6.0
LABEL_BONUS = {"ACE": 3.0, "CLUTCH": 2.5, "LAST ALIVE": 2.0}
REACTION_FLOOR = 6.0       # weaker reactions are ordinary talking, not events
REACTION_UNIT = 6.0        # this many dB-seconds is worth one kill
DEATH = 0.3
ROUND_WEIGHT = 1.0         # times the round's importance (match_story.Story.importance)

# THE PUNCH-IN. Event-driven, never on an ordinary kill: on the last kill of three
# or more close together. ChatGPT's numbers: 1.08-1.12x, 8-10 frames in, 0.5-0.9 s
# hold, 10-14 frames out, at most one per 30 s.
PUNCH_KILLS = 3
PUNCH_ZOOM = 1.12
PUNCH_IN = 9 / 60
PUNCH_HOLD = 0.8
PUNCH_OUT = 12 / 60
PUNCH_LEAD = 0.15          # the zoom starts this long before the kill lands
PUNCH_SPACING = 30.0

# THE COLD OPEN starts inside the strongest action: the best stretch's last kill
# (or its reaction, when that comes later), a few seconds either side.
COLD_BEFORE = 3.0
COLD_AFTER = 2.5
COLD_LONGEST = 8.0

# THE LOWER THIRD, once per match in a session video and never in a one-match one:
# ChatGPT's rule -- 1.2-1.5 s, small white text with one accent, a 4-6 frame fade,
# over gameplay, never over the strongest action. A stretch starts SETUP before its
# first contact, so LOWER_AT into its first cut is the walk-in.
LOWER_SIZE = 0.024
LOWER_X = 0.285
LOWER_Y = 0.80
LOWER_AT = 0.4
LOWER_SECONDS = 1.4
LOWER_FADE = 5 / 60

# THE CAM LAYOUT (cam_zoom): the frame pushes in on the facecam until it fills the
# frame with CAM_PAD to spare, at most CAM_ZOOM_MOST, easing in and out over CAM_EASE.
CAM_PAD = 1.12
CAM_ZOOM_MOST = 3.2
CAM_EASE = 0.35

# THE END SCREEN, after the game's own result screen and never instead of it:
# the channel's name, a thank-you, and the two places for YouTube's end-screen
# elements. 5-7 s (ChatGPT); YouTube needs at least 5 for its elements.
END_SECONDS = 6.0
END_FADE_IN = 0.25
END_FADE_OUT = 0.5
END_LINE = "More {game}highlights and streams."

FPS = 60
FADE_OUT = 1.0
EDGE_FADE = 0.03           # each cut's audio fades in and out this fast, so a cut does not click


@dataclass
class Event:
    t: float
    kind: str                  # "kill" / "death" / "reaction"
    weight: float
    end: float = 0.0           # a reaction's end
    round: int | None = None


@dataclass
class Stretch:
    start: float
    end: float
    score: float
    events: list[Event] = field(default_factory=list)
    round: int | None = None
    why: str = ""
    cuts: list[tuple[float, float]] = field(default_factory=list)   # after dead time is taken out
    punches: list[float] = field(default_factory=list)              # source times to punch in at
    shaped: list[tuple[float, float, str]] = field(default_factory=list)   # the cuts with layouts: shape()
    result: str = ""                                                # "ROUND 10 · LOST · 4-6", on its result cut

    @property
    def length(self) -> float:
        if self.shaped:
            return sum(b - a for a, b, _ in self.shaped)
        return sum(b - a for a, b in self.cuts) if self.cuts else self.end - self.start

    @property
    def hook(self) -> float:
        """How strong the stretch's own action is, for choosing the cold open. Not
        its score: a match-point round full of talking scores high and opens weakly;
        three kills and a scream is what makes someone keep watching."""
        kills = sorted(e.t for e in self.events if e.kind == "kill")
        rx = max((e.weight for e in self.events if e.kind == "reaction"), default=0.0)
        return len(kills) * KILL + _multi_bonus(kills) + rx

    @property
    def peak(self) -> float:
        """Where the stretch pays off: its last kill, or a later reaction to it."""
        kills = [e.t for e in self.events if e.kind == "kill"]
        rx = [e for e in self.events if e.kind == "reaction"]
        best_rx = max(rx, key=lambda e: e.weight).t if rx else None
        if kills and best_rx is not None and 0 <= best_rx - kills[-1] <= 4.0:
            return best_rx
        if kills:
            return kills[-1]
        return best_rx if best_rx is not None else (self.start + self.end) / 2


@dataclass
class Cut:
    start: float
    end: float
    punches: list[float] = field(default_factory=list)   # source times
    kind: str = "play"                                    # "cold" / "play"
    stretch: int = -1
    caption: str = ""                                     # the lower third, on a match's first cut
    layout: str = "game"                                  # "game" / "cam" / "result" -- see shape()

    @property
    def length(self) -> float:
        return self.end - self.start


def _runs(on: np.ndarray, offset: float, hz: float, join: float) -> list[tuple[float, float]]:
    edges = np.diff(np.r_[0, on.astype(np.int8), 0])
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    out: list[list[float]] = []
    for a, b in zip(starts, ends):
        s, e = offset + a / hz, offset + b / hz
        if out and s - out[-1][1] < join:
            out[-1][1] = e
        else:
            out.append([s, e])
    return [(a, b) for a, b in out]


def speech_runs(lv: np.ndarray, offset: float = 0.0, hz: float = HZ) -> list[tuple[float, float]]:
    """Where the player is talking, from the mic level (the gate makes this a threshold)."""
    if lv is None or not len(lv):
        return []
    return _runs(np.asarray(lv) > VOICED_DB, offset, hz, SPEECH_JOIN)


def game_activity(lv: np.ndarray, offset: float = 0.0, hz: float = HZ) -> list[tuple[float, float]]:
    """Where the game is busy -- gunfire, abilities, footsteps close by -- from the game
    track's level: GAME_RISE_DB over its own rolling median."""
    if lv is None or len(lv) < 3:
        return []
    lv = np.asarray(lv, dtype=np.float32)
    k = max(3, int(GAME_WINDOW * hz) | 1)
    pad = np.pad(lv, (k // 2, k // 2), mode="edge")
    # A rolling median by strides: the level tracks are 20 Hz, so even a whole
    # match is a few tens of thousands of windows.
    win = np.lib.stride_tricks.sliding_window_view(pad, k)
    base = np.median(win, axis=1)
    return _runs(lv - base[:len(lv)] >= GAME_RISE_DB, offset, hz, 1.5)


def _overlap(runs: list[tuple[float, float]], a: float, b: float) -> float:
    return sum(max(0.0, min(e, b) - max(s, a)) for s, e in runs)


def _round_of(rounds, t: float) -> dict | None:
    """The round `t` belongs to: from its buy phase to a few seconds after it is decided."""
    for r in rounds or []:
        if r["start"] - 35.0 <= t <= r["end"] + AFTER_ROUND + 3.0:
            return r
    return None


def events(*, kills: list[float], deaths: list[float], reactions: list, rounds=None,
           kill_weight: float = KILL) -> list[Event]:
    """Everything worth a stretch, on the recording's clock, in order."""
    out: list[Event] = []
    for t in kills:
        r = _round_of(rounds, t)
        out.append(Event(float(t), "kill", kill_weight, round=r["number"] if r else None))
    for t in deaths:
        r = _round_of(rounds, t)
        out.append(Event(float(t), "death", DEATH, round=r["number"] if r else None))
    for x in reactions:
        if x.score < REACTION_FLOOR:
            continue
        r = _round_of(rounds, x.start)
        out.append(Event(float(x.start), "reaction", float(x.score) / REACTION_UNIT, end=float(x.end),
                         round=r["number"] if r else None))
    out.sort(key=lambda e: e.t)
    return out


def _multi_bonus(kills: list[float]) -> float:
    """MULTI per kill beyond the first, for kills inside MULTI_SPAN of each other."""
    best = 0
    for i, t in enumerate(kills):
        n = sum(1 for u in kills[i:] if u - t <= MULTI_SPAN)
        best = max(best, n)
    return MULTI * max(0, best - 1)


def _label_bonus(labels) -> tuple[float, str]:
    best, why = 0.0, ""
    for lab in labels or []:
        for key, v in LABEL_BONUS.items():
            if key in str(lab).upper() and v > best:
                best, why = v, str(lab)
    return best, why


def situation_start(first: float, r: dict | None) -> tuple[float, float]:
    """Where the situation that `first` belongs to began, and how much lead-in it
    wants: first contact of its fight (SETUP of the walk-in before it), or the
    moment the player was left last alive (STATE_SETUP: the situation is the start)."""
    if not r:
        return first, SETUP
    at, lead = first, SETUP
    for c in sorted((c for c in r.get("contacts") or [] if c <= first), reverse=True):
        if at - c <= CHAIN:
            at = c
        else:
            break
    # Not the plant: v2 started round 10's 3K at its plant, 22 s early, and those
    # seconds were the post-plant hold v1 was already marked down for. A plant
    # protects its hold from being cut (see `protected`); it does not start a stretch.
    x = r.get("last_stand")
    if x is not None and x <= first and first - x <= SITUATION_BACK and x < at:
        at, lead = x, STATE_SETUP
    return at, lead


def bounds(g: list[Event], r: dict | None, speech: list[tuple[float, float]],
           next_start: float | None = None) -> tuple[float, float]:
    """The span a group of events needs: from where its situation began to where the
    round was decided and the player stopped reacting."""
    plays = [e for e in g if e.kind != "reaction"]
    rxs = [e for e in g if e.kind == "reaction"]
    first = g[0].t
    if plays:
        c, lead = situation_start(plays[0].t, r)
        start = min(c - lead, first - 1.0)
    else:
        # A reaction with no play of the player's: whatever fight just happened
        # around them (a team-mate's death, a clutch lost) is what they react to.
        c, lead = situation_start(first, r)
        start = (c - lead) if c < first else first - REACTION_SETUP
    floor = r["start"] - BEFORE_BARRIER if r else None
    # Cutting in mid-sentence is worse than a second more of walking: a turn of
    # talk the start would land in moves it back to where the turn began -- a
    # little way, never a minute of chat because the mic was on.
    talking = next(((s, e) for s, e in speech if s < start <= e + SPEECH_JOIN and start - s <= SPEECH_BACK), None)
    if talking:
        start = talking[0] - 0.3
        if floor is not None:
            floor = r["start"] - BUY_TALK
    if floor is not None and start < floor <= first:
        start = floor
    end = 0.0
    if plays:
        end = max(e.t for e in plays) + TAIL
    rx_end = 0.0
    if rxs:
        # The loud part is the reaction's peak, not its end: the player goes on
        # about it. The rage of 2026-10-25 was loud for 5 s and the hand-cut meme
        # kept 11 s more of him talking it out -- so the turn of talk the reaction
        # is in plays out, up to REACTION_TALK.
        last = max(e.end for e in rxs)
        turn = last
        for s, e in speech:
            if s <= turn + AFTER_TURN_GAP and e > turn:
                turn = e
        rx_end = min(turn, last + REACTION_TALK) + (AFTER_TALK if turn > last else REACTION_TAIL)
        end = max(end, rx_end)
    if r and plays:
        # Played on to the round's result when the round is decided soon after --
        # and the match's last round to the game's own VICTORY / DEFEAT screen.
        last_play = max(e.t for e in plays)
        if r["end"] >= last_play and r["end"] - end <= (FINAL_REACH if r.get("final") else RESOLVE):
            end = max(end, r["end"] + (FINAL_HOLD if r.get("final") else RESULT_HOLD))
    if r and not r.get("final"):
        end = min(end, max(r["end"] + AFTER_ROUND, rx_end))
    if next_start is not None:
        end = min(end, next_start - 1.0)
    if end - start < SHORTEST:
        end = start + SHORTEST
    return max(0.0, start), end


def stretches(evs: list[Event], *, speech: list[tuple[float, float]], rounds=None, story=None,
              source_duration: float | None = None, cluster_gap: float = CLUSTER_GAP) -> list[Stretch]:
    """Events grouped into stretches, bounded by their situation, scored. In order."""
    groups: list[list[Event]] = []
    for e in evs:
        last = groups[-1][-1] if groups else None
        same_round = last is None or last.round == e.round or None in (last.round, e.round)
        if last and same_round and e.t - max(last.t, last.end) <= cluster_gap:
            groups[-1].append(e)
        else:
            groups.append([e])
    by_num = {r["number"]: r for r in rounds or []}
    out: list[Stretch] = []
    for g in groups:
        # A stretch of nothing but deaths is the player losing a fight and moving
        # on -- unless they reacted to it, which makes it a reaction stretch.
        if all(e.kind == "death" for e in g):
            continue
        rnum = next((e.round for e in g if e.kind != "reaction" and e.round is not None),
                    next((e.round for e in g if e.round is not None), None))
        r = by_num.get(rnum)
        nxt = by_num.get(rnum + 1) if rnum else None
        # The next round's buy phase may carry the player still talking this one
        # out; its fight may not.
        start, end = bounds(g, r, speech, next_start=nxt["start"] - BEFORE_BARRIER if nxt else None)
        if source_duration:
            end = min(end, source_duration)
        kills = [e.t for e in g if e.kind == "kill"]
        score = sum(e.weight for e in g) + _multi_bonus(kills)
        bonus, why = _label_bonus(r.get("labels") if r else None)
        if kills:
            score += bonus
        if story is not None and rnum:
            imp, reason = story.importance(rnum)
            score += ROUND_WEIGHT * imp
            why = why or reason
        if not why:
            n = len(kills)
            why = f"{n} kill{'s' if n != 1 else ''}" if n else "Reaction"
        out.append(Stretch(start=start, end=end, score=round(score, 3), events=g, round=rnum, why=why))
    # In a deathmatch every fight touches the next; merged, they were one five-minute
    # stretch the selector could only take or leave whole. Kept apart, they still
    # play seamlessly when neighbours are both chosen.
    return _merge(out, merge=cluster_gap >= CLUSTER_GAP)


def _merge(sts: list[Stretch], merge: bool = True) -> list[Stretch]:
    """Stretches of one round that touch are one: a cut between them would only skip
    seconds. Stretches of different rounds stay apart -- the buy phase between them
    is exactly what gets cut."""
    out: list[Stretch] = []
    for s in sorted(sts, key=lambda x: x.start):
        p = out[-1] if out else None
        if (merge and p and s.start - p.end <= MERGE_GAP
                and (p.round == s.round or None in (p.round, s.round))):
            better = p if p.score >= s.score else s
            out[-1] = Stretch(start=p.start, end=max(p.end, s.end), score=p.score + s.score,
                              events=p.events + s.events, round=p.round or s.round, why=better.why)
        elif p and s.start < p.end:
            s.start = p.end                     # rounds never overlap on screen
            if s.end - s.start >= SHORTEST:
                out.append(s)
        else:
            out.append(s)
    return out


def protected(s: Stretch, r: dict | None) -> list[tuple[float, float]]:
    """Spans inside a stretch that are never cut however quiet: the build-up to every
    contact, and a post-plant or last-alive stand to the round's end."""
    out = [(e.t - HOLD_BEFORE_CONTACT, max(e.t, e.end) + 0.5) for e in s.events]
    if r:
        out += [(c - HOLD_BEFORE_CONTACT, c + 1.0) for c in r.get("contacts") or []]
        for key in ("plant", "last_stand"):
            if r.get(key) is not None:
                out.append((r[key], r["end"]))
    return out


def trim_dead(s: Stretch, speech: list[tuple[float, float]], game: list[tuple[float, float]] | None = None,
              r: dict | None = None) -> list[tuple[float, float]]:
    """The stretch with its dead time cut out."""
    busy = sorted([(a, b) for a, b in list(speech) + list(game or []) + protected(s, r)
                   if b > s.start and a < s.end])
    gaps: list[tuple[float, float]] = []
    at = s.start
    for a, b in busy:
        if a - at >= DEAD:
            gaps.append((at, a))
        at = max(at, b)
    if s.end - at >= DEAD:
        gaps.append((at, s.end))
    cuts, at = [], s.start
    for a, b in gaps:
        lo = a + DEAD_KEEP_IN if a > s.start else a
        hi = b - DEAD_KEEP_OUT if b < s.end else b
        if hi - lo < 2.0:
            continue
        if lo > at:
            cuts.append((at, lo))
        at = hi
    if s.end > at:
        cuts.append((at, s.end))
    return [(a, b) for a, b in cuts if b - a >= 1.0]


def punches(s: Stretch) -> list[float]:
    """Source times to punch in at: the last kill of PUNCH_KILLS or more close together."""
    kills = sorted(e.t for e in s.events if e.kind == "kill")
    out: list[float] = []
    i = 0
    while i < len(kills):
        j = i
        while j + 1 < len(kills) and kills[j + 1] - kills[j] <= MULTI_SPAN:
            j += 1
        if j - i + 1 >= PUNCH_KILLS and (not out or kills[j] - out[-1] >= PUNCH_SPACING):
            out.append(kills[j])
        i = j + 1
    return out


def select(sts: list[Stretch], *, budget: float = PER_MATCH, must: list[int] | None = None) -> list[Stretch]:
    """The best stretches that fit the budget, in the order they happened. A round in
    `must` (the final round) is kept when it has a stretch at all."""
    chosen: list[Stretch] = []
    used = 0.0
    forced = [s for s in sts if must and s.round in must]
    for s in forced + sorted((s for s in sts if s not in forced), key=lambda s: -s.score):
        if s in chosen:
            continue
        if s not in forced and s.score < MIN_SCORE:
            continue
        if used + s.length > budget and s not in forced:
            continue
        chosen.append(s)
        used += s.length
    return sorted(chosen, key=lambda s: s.start)


def _cuts(chosen: list[Stretch], cold_open: bool) -> list[Cut]:
    """The stretches as cuts, in order, after a cold open inside the strongest action."""
    cuts: list[Cut] = []
    if cold_open and chosen:
        best = max(chosen, key=lambda s: s.hook)
        pk = best.peak
        kills_in = [e.t for e in best.events if e.kind == "kill"]
        a = (kills_in[-1] if kills_in else pk) - COLD_BEFORE
        b = min(a + COLD_LONGEST, max(pk, a + COLD_BEFORE) + COLD_AFTER)
        cuts.append(Cut(max(0.0, a), b, kind="cold", stretch=chosen.index(best)))
    for i, s in enumerate(chosen):
        # A round with a later stretch of its own ends on that one: the first of two
        # stretches in round 7 cut to round 7's banner and then went back in time.
        later = any(t.round == s.round and t.round is not None and 0 < t.start - s.start < 200.0
                    for t in chosen[i + 1:])
        for a, b, layout in s.shaped or [(a, b, "game") for a, b in s.cuts]:
            if later and layout == "result":
                continue
            cuts.append(Cut(a, b, punches=[p for p in s.punches if a <= p < b], stretch=i, layout=layout,
                            caption=s.result if layout == "result" else ""))
    return cuts


def _union(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _minus(spans: list[tuple[float, float]], holes: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """`spans` with `holes` taken out of them."""
    out = []
    for a, b in spans:
        parts = [(a, b)]
        for x, y in holes:
            nxt = []
            for p, q in parts:
                if y <= p or x >= q:
                    nxt.append((p, q))
                    continue
                if x > p:
                    nxt.append((p, x))
                if y < q:
                    nxt.append((y, q))
            parts = nxt
        out += parts
    return out


def _talk_after(t: float, speech: list[tuple[float, float]], limit: float) -> list[tuple[float, float]]:
    """The turns of talk that run on from `t`, each following the last within
    AFTER_TURN_GAP, cut at `limit`; spans under CAM_SHORTEST dropped."""
    out: list[list[float]] = []
    at = t
    for a, b in sorted(speech):
        if b <= t:
            continue
        if a > at + AFTER_TURN_GAP or a >= limit:
            break
        a, b = max(a, t), min(b, limit)
        if out and a - out[-1][1] < AFTER_TURN_GAP:
            out[-1][1] = b
        else:
            out.append([a, b])
        at = b
    return [(a, b) for a, b in out if b - a >= CAM_SHORTEST]


def shape(s: Stretch, r: dict | None, speech: list[tuple[float, float]],
          next_start: float | None = None) -> list[tuple[float, float, str]]:
    """What the viewer sees through a stretch: (start, end, layout) in order.

    Two things the player asked for (2026-11-01) after watching the first session
    video: "there is no clear indication of when the round ends and the next starts
    -- when I die, suddenly in the next second I am alive", and "when I am talking
    and no gameplay is worth showing, enlarge the facecam".

    So:
      * talk in the buy phase before a round's fight is the CAM layout;
    and in a round that is not the match's last:
      * once the player is dead, the game keeps CAM_AFTER_DEATH (the kill and the
        combat report); after that, a team-mate's fight stays on the game, and the
        rest of spectating is not worth showing -- while they keep talking it is the
        CAM layout, and when they stop it is over;
      * the round always ENDS ON SCREEN: unless the stretch already shows the
        game's own WON / LOST banner, RESULT_IN to RESULT_OUT after the round was
        decided is cut in (measured on three Bind rounds: the banner is up from
        1 s to 5 s after the deciding moment). It is the game's banner, not a card.
    The match's last round plays as it is: it ends on the game's result screen."""
    pieces = [(a, b, "game") for a, b in s.cuts]
    if not r or not pieces:
        return pieces
    if r.get("start") is not None and pieces[0][0] < r["start"] - 0.5:
        lead = r["start"] - 0.5
        talk = [(max(a, pieces[0][0]), min(b, lead)) for a, b in speech if a < lead and b > pieces[0][0]]
        out = []
        for a, b, lay in pieces:
            if b <= lead:
                out += [(x, y, "cam") for x, y in talk if a <= x < b and y - x >= CAM_SHORTEST]
            elif a < lead:
                out += [(x, min(y, lead), "cam") for x, y in talk if a <= x < lead and min(y, lead) - x >= CAM_SHORTEST]
                out.append((lead, b, lay))
            else:
                out.append((a, b, lay))
        pieces = out or pieces
    if r.get("final"):
        return [(a, b, lay) for a, b, lay in pieces if b - a >= 0.5]
    deaths = sorted(e.t for e in s.events if e.kind == "death")
    if deaths:
        d = deaths[0] + CAM_AFTER_DEATH
        limit = d + CAM_LONGEST
        if next_start is not None:
            limit = min(limit, next_start - 1.0)
        kept = [(a, min(b, d), lay) for a, b, lay in pieces if a < d]
        # A team-mate still fighting is gameplay, not spectating: "do not equate
        # spectating with uninteresting footage" (ChatGPT, on the first CAM render).
        # Every fight after the death, up to the round's end, stays on the game --
        # talked over or not -- and the talk around it is the CAM.
        fights = _union([(max(d, c - HOLD_BEFORE_CONTACT), c + 1.0) for c in r.get("contacts") or []
                         if d < c <= min(r["end"], limit)])
        cam = _minus(_talk_after(d, speech, limit), fights)
        pieces = sorted(kept + [(a, b, "game") for a, b in fights]
                        + [(a, b, "cam") for a, b in cam if b - a >= CAM_SHORTEST])
    shown = any(lay == "game" and a <= r["end"] + RESULT_SEEN <= b for a, b, lay in pieces)
    ra, rb = r["end"] + RESULT_IN, r["end"] + RESULT_OUT
    if not shown and (next_start is None or rb < next_start):
        out = []
        for a, b, lay in pieces:
            if b <= ra or a >= rb:
                out.append((a, b, lay))
                continue
            if a < ra:
                out.append((a, ra, lay))
            if b > rb:
                out.append((rb, b, lay))
        pieces = sorted(out + [(ra, rb, "result")])
    return [(a, b, lay) for a, b, lay in pieces if b - a >= 0.5]


def snap(cuts: list[Cut], lines) -> list[Cut]:
    """Cuts moved to the edges of what the player said (speech.transcribe's lines): a
    cut that would land inside a sentence moves out to its start or its end, by at
    most SNAP. The cold open and the round-result cuts keep their times -- one is
    action, the other the game's banner. Never into the cut before it."""
    if not lines:
        return cuts
    out: list[Cut] = []
    for c in cuts:
        if c.kind == "play" and c.layout != "result":
            for ln in lines:
                if ln.start < c.start < ln.end and c.start - ln.start <= SNAP:
                    c.start = ln.start - 0.15
                if ln.start < c.end < ln.end and ln.end - c.end <= SNAP:
                    c.end = ln.end + 0.25
        prev = out[-1] if out else None
        if prev is not None and prev.kind == "play" and c.start < prev.end and prev.stretch == c.stretch:
            c.start = prev.end
        if c.end - c.start >= 0.5:
            out.append(c)
    return out


def result_line(r: dict | None) -> str:
    """What the round-result cut says over the game's own banner, in case a held
    scoreboard or a spectated team-mate hides it: "ROUND 10 · LOST · 4-6"."""
    if not r or r.get("won") is None or not r.get("score"):
        return ""
    a, b = r["score"]
    return f"ROUND {r['number']} · {'WON' if r['won'] else 'LOST'} · {a}-{b}"


def plan(*, kills: list[float], deaths: list[float], reactions: list, speech: list[tuple[float, float]],
         game: list[tuple[float, float]] | None = None, rounds=None, story=None,
         source_duration: float | None = None, budget: float = PER_MATCH,
         cold_open: bool = True, respawn: bool = False) -> tuple[list[Cut], list[Stretch]]:
    """The cuts of one match's highlights, cold open first, then in order.

    `rounds` are valorant_match.round_times() dicts (a "labels" list may be added);
    without them a stretch is bounded by fixed margins around its events."""
    evs = events(kills=kills, deaths=deaths, reactions=reactions, rounds=rounds,
                 kill_weight=RESPAWN_KILL if respawn else KILL)
    sts = stretches(evs, speech=speech, rounds=rounds, story=story, source_duration=source_duration,
                    cluster_gap=RESPAWN_GAP if respawn else CLUSTER_GAP)
    by_num = {r["number"]: r for r in rounds or []}
    for s in sts:
        r = by_num.get(s.round)
        s.cuts = trim_dead(s, speech, game, r)
        s.punches = punches(s)
        nxt = by_num.get(s.round + 1) if s.round else None
        s.shaped = shape(s, r, speech, next_start=nxt["start"] if nxt else None)
        s.result = result_line(r)
    final = [r["number"] for r in rounds or [] if r.get("final")]
    chosen = select(sts, budget=budget, must=final or None)
    return _cuts(chosen, cold_open), chosen


@dataclass
class Match:
    """One match's worth of what the clipper knows, on the recording's clock."""
    kills: list[float]
    deaths: list[float] = field(default_factory=list)
    rounds: list[dict] | None = None          # valorant_match.round_times(), labels added
    story: object | None = None               # match_story.Story
    label: str = ""                           # "MATCH 03 · COMPETITIVE · BIND · CYPHER"
    respawn: bool = False                     # deathmatch / team deathmatch
    span: tuple[float, float] | None = None   # where the match is on the recording

    def holds(self, a: float, b: float) -> bool:
        """Whether [a, b] is this match's: from its agent select to just after it ends.
        A recording's reactions and talk belong to whichever match they happened in --
        the first session plan gave every match the scream from the end of the stream."""
        if self.span is None:
            return True
        return self.span[0] - SPAN_BEFORE <= a and b <= self.span[1] + SPAN_AFTER


def strength(chosen: list[Stretch]) -> float:
    """How good a match is for this video: its best few stretches, not its length."""
    return sum(sorted((s.score for s in chosen), reverse=True)[:5])


def choose_matches(found: dict[int, tuple[bool, float]]) -> list[int]:
    """Which matches a session video covers. `found` is {match: (respawn, strength)}.

    The strongest round-based matches, up to SESSION_MATCHES; a deathmatch only in
    place of a weaker round-based one, when its own moments are stronger -- not
    because it is there (ChatGPT: "don't automatically include both TDM matches
    just because they exist")."""
    by_rounds = sorted((i for i, (rs, _) in found.items() if not rs), key=lambda i: -found[i][1])
    picked = by_rounds[:SESSION_MATCHES]
    for i in sorted((i for i, (rs, _) in found.items() if rs), key=lambda i: -found[i][1]):
        if len(picked) < SESSION_MATCHES:
            picked.append(i)
        else:
            weakest = min(picked, key=lambda k: found[k][1])
            if found[i][1] > found[weakest][1]:
                picked[picked.index(weakest)] = i
        break                                   # one deathmatch at most
    return sorted(picked)


def plan_session(matches: list[Match], *, reactions: list, speech: list[tuple[float, float]],
                 game: list[tuple[float, float]] | None = None, source_duration: float | None = None,
                 cold_open: bool = True) -> tuple[list[Cut], list[Stretch], list[int]]:
    """A whole recording's highlights: the best matches, each given time by how good
    it is, one cold open for all of it.
    -> (cuts, the stretches they come from, the match index of each stretch)."""
    def run(i: int, budget: float) -> list[Stretch]:
        m = matches[i]
        return plan(kills=m.kills, deaths=m.deaths,
                    reactions=[x for x in reactions if m.holds(x.start, x.end)],
                    speech=[(a, b) for a, b in speech if m.holds(a, b)],
                    game=[(a, b) for a, b in game or [] if m.holds(a, b)],
                    rounds=m.rounds, story=m.story, source_duration=source_duration,
                    budget=budget, cold_open=False, respawn=m.respawn)[1]

    first = {i: run(i, PER_MATCH) for i in range(len(matches))}
    found = {i: (matches[i].respawn, strength(ch)) for i, ch in first.items()
             if ch and strength(ch) >= MATCH_FLOOR}
    picked = choose_matches(found) if len(found) > 1 else list(found)
    best = max((found[i][1] for i in picked), default=1.0) or 1.0
    planned: list[tuple[int, list[Stretch]]] = []
    for i in picked:
        # The session's best match MATCH_MOST, the others less by how much weaker
        # they are: ChatGPT's allocation (good 2.5-4 min, strong 4-5, exceptional
        # 5-7), relative to this session. One match alone has PER_MATCH.
        budget = (PER_MATCH if len(picked) == 1
                  else MATCH_LEAST + (MATCH_MOST - MATCH_LEAST) * found[i][1] / best)
        planned.append((i, first[i] if budget >= PER_MATCH else run(i, budget)))
    chosen = [s for _, ch in planned for s in ch]
    owner = [i for i, ch in planned for _ in ch]
    order = sorted(range(len(chosen)), key=lambda k: chosen[k].start)
    chosen, owner = [chosen[k] for k in order], [owner[k] for k in order]
    cuts = _cuts(chosen, cold_open)
    if len(planned) > 1:
        seen: set[int] = set()
        for c in cuts:
            if c.kind == "play" and owner[c.stretch] not in seen:
                seen.add(owner[c.stretch])
                c.caption = matches[owner[c.stretch]].label
    return cuts, chosen, owner


# ---------------------------------------------------------------- rendering

def zoom_expr(punch_times: list[float], zoom: float = PUNCH_ZOOM) -> str:
    """zoompan's z for punches at these times (seconds into the cut): a smoothstep in
    over PUNCH_IN, a hold, a smoothstep out. 1 everywhere else."""
    if not punch_times:
        return "1"
    terms = []
    for p in punch_times:
        t0 = p - PUNCH_LEAD
        t1 = t0 + PUNCH_IN + PUNCH_HOLD
        up = f"clip((it-{t0:.4f})/{PUNCH_IN:.4f},0,1)"
        dn = f"clip((it-{t1:.4f})/{PUNCH_OUT:.4f},0,1)"
        terms.append(f"({up}*{up}*(3-2*{up})-{dn}*{dn}*(3-2*{dn}))")
    return f"1+{zoom - 1:.4f}*({'+'.join(terms)})"


def lower_third(text: str, size: tuple[int, int] = (1920, 1080)):
    """The one piece of text a session video carries: which match the next footage is
    from, small, white, the match number the only accent. A transparent full-frame PNG.

    Beside the facecam rather than under it: the bottom-left of a Valorant stream is
    the camera and the player's own HUD, the top is the score and the kill feed."""
    from PIL import Image, ImageDraw
    from . import match_video as mv
    w, h = size
    px = max(12, round(h * LOWER_SIZE))
    head, _, rest = text.partition(" · ")
    f = mv.face("text", px, text)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    gap = round(px * 0.5)
    hw = d.textlength(head, font=f)
    tail = f"·  {rest}" if rest else ""
    rw = d.textlength(tail, font=f) if rest else 0
    pad_x, pad_y = round(px * 0.7), round(px * 0.45)
    x, y = round(w * LOWER_X), round(h * LOWER_Y)
    asc, desc = f.getmetrics()
    d.rounded_rectangle((x - pad_x, y - pad_y, x + hw + (gap + rw if rest else 0) + pad_x, y + asc + desc + pad_y),
                        radius=round(px * 0.35), fill=mv.PLATE)
    d.text((x, y), head, font=f, fill=mv.GOLD)
    if rest:
        d.text((x + hw + gap, y), tail, font=f, fill=mv.OFF_WHITE)
    return img


def cam_zoom(box, length: float) -> tuple[str, str, str]:
    """The CAM layout as zoompan's (z, x, y): the frame itself pushes in on the
    player's facecam where it sits, eases in over CAM_EASE, holds, and eases back out
    at the end. `box` is the facecam's place in the frame, x y w h as fractions
    (facecam.load()["inset"]).

    The player's word on the first CAM layout, a separate composition with the cam
    large and the game inset (2026-11-01): "not good, just zoom on the place where
    the facecam is instead of making a different layout". The stream stays the
    stream; the camera moves."""
    bx, by, bw, bh = box
    z = max(1.0, min(1.0 / (bw * CAM_PAD), 1.0 / (bh * CAM_PAD), CAM_ZOOM_MOST))
    e = min(CAM_EASE, length / 3)
    up = f"clip(it/{e:.4f},0,1)"
    dn = f"clip((it-{length - e:.4f})/{e:.4f},0,1)"
    zexpr = f"1+{z - 1:.4f}*({up}*{up}*(3-2*{up}))*(1-{dn}*{dn}*(3-2*{dn}))"
    cx, cy = bx + bw / 2, by + bh / 2
    x = f"clip({cx:.5f}*iw-iw/zoom/2,0,iw-iw/zoom)"
    y = f"clip({cy:.5f}*ih-ih/zoom/2,0,ih-ih/zoom)"
    return zexpr, x, y


def _cut_one(source: Path, c: Cut, out: Path, *, size: tuple[int, int], encoder: str, cq: int,
             last: bool = False, cam_box=None) -> None:
    from .tools import decode_args, ffmpeg, filter_script_flag, video_codec_args
    w, h = size
    vf = [f"fps={FPS}"]
    zoom = None
    if c.layout == "cam" and cam_box:
        zoom = cam_zoom(cam_box, c.length)
    elif c.punches:
        zoom = (zoom_expr([p - c.start for p in c.punches]), "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)")
    if zoom:
        z, x, y = zoom
        # Over-sampled first: zoompan rounds its window to whole pixels, which
        # shimmers on a slow zoom at the source's own size.
        vf += [f"scale={w * 2}:{h * 2}:flags=bicubic",
               f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={w}x{h}:fps={FPS}"]
    vf += [f"scale={w}:{h}:flags=lanczos", "format=yuv420p"]
    fade = FADE_OUT if last else EDGE_FADE
    af = f"afade=t=in:d={EDGE_FADE},afade=t=out:st={max(0.0, c.length - fade):.3f}:d={fade}"
    graph = [f"[0:v]{','.join(vf)}[v]"]
    at = "v"
    inputs = ["-ss", f"{c.start:.3f}", "-t", f"{c.length:.3f}", "-i", str(source)]
    if c.caption:
        png = out.with_suffix(".lower.png")
        lower_third(c.caption, size).save(png)
        a = LOWER_AT
        b = min(c.length - 0.2, a + LOWER_SECONDS)
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{c.length:.3f}", "-i", str(png)]
        graph.append(f"[1:v]format=rgba,fade=t=in:st={a:.3f}:d={LOWER_FADE:.3f}:alpha=1,"
                     f"fade=t=out:st={b - LOWER_FADE:.3f}:d={LOWER_FADE:.3f}:alpha=1[l];"
                     f"[{at}][l]overlay=0:0:shortest=1:enable='between(t,{a:.3f},{b:.3f})'[lo]")
        at = "lo"
    if last:
        graph.append(f"[{at}]fade=t=out:st={max(0.0, c.length - FADE_OUT):.3f}:d={FADE_OUT}[fo]")
        at = "fo"
    graph.append(f"[{at}]null[vout];[0:a:0]{af}[aout]")
    script = out.with_suffix(".graph.txt")
    script.write_text(";".join(graph), encoding="utf-8")
    ffmpeg(*decode_args(), *inputs, filter_script_flag(), str(script), "-map", "[vout]", "-map", "[aout]",
           *video_codec_args(encoder, cq=cq), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-y", str(out))


def _loudness(path: Path) -> dict | None:
    """loudnorm's first-pass measurement of a file's audio."""
    import subprocess
    from .tools import binary
    p = subprocess.run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-i", str(path), "-vn",
                        "-af", "loudnorm=I=-16:TP=-1:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr or "")
    return json.loads(m.group(0)) if m else None


def end_screen(channel: str, background, size: tuple[int, int] = (1920, 1080), game: str = ""):
    """The channel's end screen, ChatGPT's spec: the name, "Thanks for watching.", a
    line under it, and the two places YouTube's own end-screen elements go -- a video
    and the subscribe button -- marked out for the creator to drop them onto in
    Studio. Over the video's last frame, blurred and darkened; no statistics, no
    facecam. A full-frame RGB image."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
    from . import match_video as mv
    w, h = size
    if background is None:
        img = Image.new("RGB", (w, h), (10, 12, 16))
    else:
        img = background.convert("RGB").resize((w, h))
        img = ImageEnhance.Brightness(img.filter(ImageFilter.GaussianBlur(h * 0.02))).enhance(0.3)
    d = ImageDraw.Draw(img, "RGBA")
    name = channel.upper()
    big = mv.face("title", round(h * 0.075), name)
    d.text((w / 2, h * 0.17), name, font=big, fill=mv.OFF_WHITE, anchor="mm")
    say = mv.face("text", round(h * 0.034), "Thanks for watching.")
    d.text((w / 2, h * 0.27), "Thanks for watching.", font=say, fill=mv.GOLD, anchor="mm")
    more = END_LINE.format(game=f"{game.upper()} " if game else "")
    sub = mv.face("text", round(h * 0.024), more)
    d.text((w / 2, h * 0.325), more, font=sub, fill=(200, 202, 206, 255), anchor="mm")
    label = mv.face("text", round(h * 0.02), "NEXT VIDEO SUBSCRIBE")
    line = (242, 242, 238, 110)
    # YouTube's video element is 16:9 and its subscribe element a circle; these are
    # where they sit, both inside the safe area Studio allows.
    vw = round(w * 0.36)
    vh = round(vw * 9 / 16)
    vx, vy = round(w * 0.56), round(h * 0.43)
    d.rounded_rectangle((vx, vy, vx + vw, vy + vh), radius=round(h * 0.012), outline=line, width=3)
    d.text((vx + vw / 2, vy + vh / 2), "NEXT VIDEO", font=label, fill=line, anchor="mm")
    r = round(h * 0.13)
    cx, cy = round(w * 0.30), vy + vh // 2
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=line, width=3)
    d.text((cx, cy), "SUBSCRIBE", font=label, fill=line, anchor="mm")
    return img


def _end_clip(still: Path, out: Path, *, encoder: str, cq: int) -> None:
    """END_SECONDS of the end screen, with silence, encoded like every cut so the
    join can copy it."""
    from .tools import ffmpeg, video_codec_args
    ffmpeg("-loop", "1", "-framerate", str(FPS), "-t", f"{END_SECONDS:.3f}", "-i", str(still),
           "-f", "lavfi", "-t", f"{END_SECONDS:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
           "-vf", f"format=yuv420p,fade=t=in:d={END_FADE_IN},fade=t=out:st={END_SECONDS - END_FADE_OUT:.3f}:d={END_FADE_OUT}",
           "-map", "0:v", "-map", "1:a", *video_codec_args(encoder, cq=cq),
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-y", str(out))


def render(source: Path, cuts: list[Cut], out: Path, *, size: tuple[int, int] = (1920, 1080),
           encoder: str = "auto", cq: int = 19, channel: str = "", game: str = "", cam_box=None,
           progress: Callable[[int, int], None] | None = None) -> Path:
    """Cut, join, and bring the loudness to -16 LUFS without flattening it. With a
    `channel`, the video ends on its end screen.

    The loudness is measured on the joined video and applied in a second pass as
    one linear gain (loudnorm's linear mode): a live recording's dynamics -- a
    whisper before the scream -- are the content, and the one-pass dynamic mode
    compresses exactly that."""
    from .tools import ffmpeg
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent / f".{out.stem}.parts"
    work.mkdir(parents=True, exist_ok=True)
    try:
        names = []
        for i, c in enumerate(cuts):
            if progress:
                progress(i, len(cuts) + 2)
            f = work / f"c{i:03d}.mp4"
            # With an end screen the last cut hands over to it rather than fading.
            _cut_one(source, c, f, size=size, encoder=encoder, cq=cq,
                     last=i == len(cuts) - 1 and not channel, cam_box=cam_box)
            names.append(f.name)
        if channel and cuts:
            from . import match_video as mv
            bg = mv._frame(source, cuts[-1].end - 0.2)
            end_screen(channel, bg, size, game).save(work / "end.png")
            _end_clip(work / "end.png", work / "end.mp4", encoder=encoder, cq=cq)
            names.append("end.mp4")
        (work / "list.txt").write_text("".join(f"file '{n}'\n" for n in names), encoding="utf-8")
        joined = work / "joined.mp4"
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(work / "list.txt"), "-c", "copy", "-y", str(joined))
        if progress:
            progress(len(cuts), len(cuts) + 2)
        m = _loudness(joined)
        norm = "loudnorm=I=-16:TP=-1:LRA=11"
        if m:
            norm += (f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
                     f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
        tmp = out.with_suffix(".tmp.mp4")
        # The picture is copied: it was encoded once, from the source, and a
        # second encode would only cost quality for an audio change.
        ffmpeg("-i", str(joined), "-map", "0:v", "-map", "0:a", "-c:v", "copy",
               # loudnorm falls back to its own dynamic mode when the linear gain
               # would breach the peak, and that limiter is not a true-peak one: the
               # Bind render measured +0.3 dBTP. A limiter after it holds the line.
               "-af", f"{norm},aresample=48000,alimiter=limit=0.84:attack=1:release=60:level=false",
               "-c:a", "aac", "-b:a", "192k",
               "-movflags", "+faststart", "-y", str(tmp))
        os.replace(tmp, out)
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def chapters(cuts: list[Cut], chosen: list[Stretch], prefix: list[str] | None = None) -> list[tuple[float, str]]:
    """(seconds into the video, name) for each stretch, for the description.
    `prefix[i]` goes before stretch i's name ("Match 2")."""
    out, at, seen = [], 0.0, set()
    for c in cuts:
        if c.kind == "play" and c.stretch not in seen:
            seen.add(c.stretch)
            s = chosen[c.stretch]
            name = f"Round {s.round} - {s.why}" if s.round else s.why
            if prefix:
                name = f"{prefix[c.stretch]} · {name}"
            if not out or at - out[-1][0] >= 10:
                out.append((at, name))
        at += c.length
    if out:
        out[0] = (0.0, out[0][1])
    return out
