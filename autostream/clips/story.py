r"""Arranging clips into an arc, and pinning that arc to the music.

WHAT "STORY" MEANS HERE
    A chronological account of the session with the best moment at the PEAK
    rather than at the front. Those two goals fight each other, and how they are
    reconciled is the whole idea in this module:

        opening      first blood, or the pistol round      sets the stakes
        the slide    the rounds in between, compressed     tension
        THE TURN     the streak-breaker                    the centrepiece
        the push     escalating, shorter cuts              acceleration
        match point  the last round                        resolution

    clips/beatsync.py already lays clips on a beat grid and already knows where
    the drop is. What it did with that was move the best clip INTO the drop's
    slot, which puts the end of the match in the middle of the reel and reads as
    a shuffle rather than a story.

    So this module does the opposite: the clips stay in the order they happened,
    and the MUSIC is slid instead. The arrangement is offset so that the turn's
    slot is the one containing the drop. Nothing is reordered, and the drop
    still lands on the moment worth building to.

THREE THINGS THE PACING NEEDS, ALL OF THEM MEASURED IN BEATS
    Phrase awareness. An act that begins three beats into a four-beat phrase
    sounds like a mistake even when every cut is on a beat, so each act is
    padded to a whole number of phrases and every act therefore begins on one.

    A density ramp. Slots shorten as the arc builds -- eight beats to open, two
    at the end of the push. The clips do not change; the room they get does.

    Intensity matching. A 1v3 in a quiet passage is a wasted 1v3. `intensity()`
    scores every clip from the labels the round layer already earned, and the
    biggest number is what the drop is aligned to.

WHEN THERE IS NOTHING TO BUILD TO
    A track with no drop, or a session with one clip in it, gets an arrangement
    starting at the first beat. That is not a failure mode worth special-casing
    away: an arc of one act is just a clip on a beat grid.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from .beatsync import Slot, Track

log = logging.getLogger("autostream.clips.story")

# What a label is worth, strongest first. The same ordering as rounds.RANK,
# scored rather than ranked because the peak is chosen by comparing clips and
# ties are common -- two clutches in a session are not unusual, and the kill
# count then has to break it.
WEIGHTS: tuple[tuple[str, int], ...] = (
    ("ACE", 10),
    ("CLUTCH", 9),
    ("STREAK BREAKER", 8),
    ("MATCH POINT", 7),
    ("KNIFE", 7),
    ("ZEUS", 7),
    ("ALMOST", 6),
    ("KILLS", 5),
    ("K IN", 5),
    ("NO SCOPE", 5),
    ("THROUGH SMOKE", 4),
    ("WALLBANG", 4),
    ("NADE", 3),
    ("BLIND", 3),
    ("LAST ALIVE", 3),
    ("CHAOS", 2),
    ("PISTOL", 2),
    ("SURVIVED", 1),
)

# The arc. `beats` is how much room a clip in that act gets, and the ramp
# inside an act is applied on top -- see _widths.
#
# 16 beats for the turn is four bars, which at 128 BPM is seven and a half
# seconds: enough to show a whole 1vN without the reel stalling. Two beats in
# the push is under a second, which is a flash cut and meant to be.
ACTS: dict[str, dict] = {
    "open":  {"beats": 8,  "label": "opening"},
    "slide": {"beats": 4,  "label": "the slide"},
    "turn":  {"beats": 16, "label": "THE TURN"},
    "push":  {"beats": 4,  "label": "the push"},
    "close": {"beats": 8,  "label": "match point"},
}

# A round that was LOST gets half the room in the slide. The slide is the part
# the viewer is waiting to get past, and a loss is what it is made of.
SLIDE_LOST = 2

# The push shortens towards the end: the last clips get this instead.
PUSH_FAST = 2

# One phrase. Acts are padded to a multiple of this so every act change lands
# on one, and the arrangement is offset by a multiple of it so the acts sit on
# the track's own phrases rather than merely on its beats.
PHRASE = 4

# A slot this short has no room for a run-up; the cut is the effect.
FAST_BEATS = 2
FAST_PRE = 0.18

# HOW THE ARC IS ORDERED. Three editorial theories, and the only honest way to
# choose between them is to cut all three and watch them:
#
#   "story"  chronological. The session as it happened, peak wherever it fell.
#   "build"  weakest to strongest. A pure escalation; the peak is always last.
#   "hook"   peak FIRST, then the rest. Spends the best moment on the opening
#            two seconds, which is where a Short is won or lost.
ORDERS = ("story", "build", "hook")

# THE TURN IS SIZED BY WHAT HAPPENED IN IT, not by a constant.
#
# A fixed 16 beats put the drop on the last kill correctly and still cut the
# clip open two kills into a three-kill clutch -- the round's kills spanned 13
# seconds and the slot was 12. So the run-up is measured from the round's own
# kill sequence: the slot opens before its FIRST kill and its LAST kill lands
# on the drop.
TURN_RUN_UP = 2.5          # before the first kill of the sequence
TURN_TAIL = 2.5            # after the last one, so the reel does not cut on the drop
# ...within reason. A round whose kills are half a minute apart is not a
# sequence, it is two moments, and the reel shows the second one.
MAX_TURN_LEAD = 16.0
TURN_MIN_BEATS = 12
TURN_MAX_BEATS = 32

# The anchor kill lands this much BEFORE the drop rather than exactly on it.
#
# Asymmetric on purpose: a beat that arrives a fraction after the kill reads as
# the music answering it, and a beat that arrives a fraction before reads as a
# mistake. Two frames at 60fps is under the threshold where anyone would call
# it late, and comfortably clear of the quarter-second the arrival detector
# can still be out by.
TURN_BIAS = 0.10

# An arrival within this of a beat is taken to BE that beat. Produced music
# drops on a downbeat; when the grid agrees, using the grid's own time keeps
# the drop and the cuts on one clock.
DROP_SNAP = 0.20

# A slot with at least this many beats puts its kill on a beat as well as its
# cut -- the run-up is rounded to a whole number of beats, so both land on the
# grid. Shorter slots keep a natural lead.
#
# NOT every slot, deliberately. Landing every cut AND every kill on the grid is
# mechanical: the reel stops feeling edited to the music and starts feeling
# generated by it.
QUANTISE_MIN_BEATS = 4

# ...but a clip worth this much is never flash-cut, wherever the ramp puts it.
# Intensity matching, and the reason it is needed: with the ramp alone a 1v2
# clutch that happened to fall late in the push got 0.9 seconds, which is the
# one clip in the session nobody would cut that way.
BIG = 6.0


def intensity(plan) -> float:
    """How big a moment this clip is. Bigger is nearer the peak.

    Labels first, because they say what happened; the kill count only breaks
    ties, since a two-kill clutch beats a four-kill round that was never in
    doubt.
    """
    labels = [str(x).upper() for x in (getattr(plan, "labels", None) or [])]
    best = 0
    for key, weight in WEIGHTS:
        if any(key in label for label in labels):
            best = max(best, weight)
    return best + 0.5 * int(getattr(plan, "kills", 0) or 0)


@dataclass
class Arc:
    """An arrangement: which clip is in which act, and where on the track."""
    slots: list[Slot] = field(default_factory=list)
    turn: int = -1              # index into slots
    drop_at: int = -1           # index of the slot the drop lands in
    dropped: list[Any] = field(default_factory=list)   # clips that did not fit
    start_beat: int = 0
    order: str = "story"
    drop: float | None = None   # the arrival actually aimed at

    def describe(self) -> str:
        return " -> ".join(
            f"{s.act}:{s.length:.1f}s" for s in self.slots) or "empty"


def _turn_index(plans: Sequence[Any]) -> int:
    """Which clip is the centrepiece: the most intense one.

    A STREAK BREAKER DOES NOT WIN OUTRIGHT, though it was written that way
    first. The streak-breaker is the turn of the MATCH, and making it the turn
    of the REEL put a session's best clip -- a 1v2 clutch, scoring 10.5 against
    the breaker's 8.5 -- into a 0.9-second flash cut in the push. The reel's
    centrepiece is its biggest moment; a breaker only wins ties, where it is
    the better story of two equals.
    """
    def key(i: int) -> tuple:
        p = plans[i]
        breaker = any("STREAK BREAKER" in str(l).upper()
                      for l in (getattr(p, "labels", None) or []))
        # Later beats earlier among equals: a peak two thirds of the way in
        # leaves the reel somewhere to go.
        return (intensity(p), breaker, i)

    return max(range(len(plans)), key=key) if plans else 0


def _kill_times(plan, kills: Sequence[Any]) -> list[float]:
    """The kill timestamps inside one clip, in order."""
    lo, hi = getattr(plan, "start", 0.0), getattr(plan, "end", 0.0)
    out = []
    for k in kills or ():
        t = float(k["time"] if isinstance(k, dict) else getattr(k, "time", 0.0))
        if lo <= t <= hi:
            out.append(t)
    return sorted(out)


def _turn_shape(plan, kills: Sequence[Any], bpm: float) -> tuple[int, float]:
    """-> (beats for the turn's slot, seconds of it before the drop).

    The drop lands on the LAST kill, and everything from `TURN_RUN_UP` before
    the FIRST one plays in front of it.
    """
    beat = 60.0 / (bpm or 120.0)
    times = _kill_times(plan, kills)
    span = (times[-1] - times[0]) if len(times) > 1 else 0.0
    lead = min(MAX_TURN_LEAD, span + TURN_RUN_UP)
    beats = int(-(-(lead + TURN_TAIL) // beat))          # ceil
    beats += (-beats) % PHRASE                            # up to a whole phrase
    beats = max(TURN_MIN_BEATS, min(TURN_MAX_BEATS, beats))
    # If the cap bit, the run-up is what gives way -- never the tail, and never
    # the last kill's place on the drop.
    lead = min(lead, beats * beat - TURN_TAIL)
    return beats, max(0.0, lead)


def _sequence(plans: Sequence[Any], order: str) -> list[Any]:
    """The clips in the order this arrangement plays them."""
    if order == "build":
        # Pure escalation. Ties break on when it happened, so a session with
        # two equal clutches still plays them in the order they occurred.
        return sorted(plans, key=lambda p: (intensity(p), getattr(p, "start", 0.0)))
    if order == "hook":
        best = max(plans, key=lambda p: (intensity(p), getattr(p, "start", 0.0)))
        rest = [p for p in plans if p is not best]
        return [best] + sorted(rest, key=lambda p: getattr(p, "start", 0.0))
    return sorted(plans, key=lambda p: getattr(p, "start", 0.0))


def _acts(plans: Sequence[Any], turn: int) -> list[str]:
    """One act name per clip, chronological. `turn` is the peak's index."""
    last = len(plans) - 1
    out = []
    for i, p in enumerate(plans):
        if i == turn:
            out.append("turn")
        elif i == 0 and turn != 0:
            out.append("open")
        elif i < turn:
            out.append("slide")
        elif i == last and _is_close(p):
            out.append("close")
        else:
            out.append("push")
    # Whatever happens last is the resolution, even if it is not match point:
    # ending on a flash cut from the push leaves the reel without a landing.
    if out and out[-1] == "push" and last > turn:
        out[-1] = "close"
    return out


def _is_close(plan) -> bool:
    labels = [str(x).upper() for x in (getattr(plan, "labels", None) or [])]
    return any("MATCH POINT" in label for label in labels)


def _widths(plans: Sequence[Any], acts: Sequence[str],
            turn_beats: int | None = None) -> list[int]:
    """How many beats each clip gets, phrase-padded per act.

    Three rules, in this order:

      * the density ramp -- the back half of the run LEADING INTO the turn and
        the back half of the push both drop to a flash cut, and a lost round in
        the slide is short wherever it sits. Acceleration lives in whichever
        act leads into the turn, which is not always the push: a session whose
        best moment is the second-to-last round has a long slide and no push at
        all, and it should still speed up on the way in.
      * intensity matching -- a clip worth BIG or more keeps a full bar however
        the ramp would have cut it
      * phrase padding -- each act's total is rounded up to a whole phrase and
        the extra goes on its FIRST slot, so the next act starts on a phrase
        boundary without any clip losing time. On the LAST slot, which is where
        it went first, the padding lands on exactly the slot the ramp just made
        shortest and cancels the acceleration it was there to create.
    """
    out = []
    runs = _runs(acts)
    for i, (plan, act) in enumerate(zip(plans, acts)):
        beats = ACTS[act]["beats"]
        if act == "turn" and turn_beats:
            beats = turn_beats
        at, size = runs[i]
        if act in ("slide", "push") and size > 1 and at >= size / 2:
            beats = PUSH_FAST
        if act == "slide" and getattr(plan, "won", None) is False:
            beats = min(beats, SLIDE_LOST)
        # Intensity matching. The ramp decides pacing; this decides that
        # pacing does not get to throw away the moment.
        if beats < PHRASE and intensity(plan) >= BIG:
            log.info("clip %d scores %.1f, so it keeps a full bar rather than "
                     "the %d beats the ramp would give it",
                     i + 1, intensity(plan), beats)
            beats = PHRASE
        out.append(beats)

    # Pad each run of one act up to a whole phrase.
    i = 0
    while i < len(out):
        j = i
        while j + 1 < len(out) and acts[j + 1] == acts[i]:
            j += 1
        total = sum(out[i:j + 1])
        short = (-total) % PHRASE
        if short:
            out[i] += short
        i = j + 1
    return out


def _runs(acts: Sequence[str]) -> list[tuple[int, int]]:
    """-> (position in its run, length of that run) for each clip."""
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(acts):
        j = i
        while j + 1 < len(acts) and acts[j + 1] == acts[i]:
            j += 1
        size = j - i + 1
        out.extend((k, size) for k in range(size))
        i = j + 1
    return out


def _reachable_drop(track: Track, turn_at: int, lead: float) -> float | None:
    """The biggest arrival in the track that this arrangement can reach.

    `turn_at` beats of material have to play before the turn, and `lead`
    seconds of the turn's own slot before the drop lands in it. A drop earlier
    than that cannot be hit without deleting clips -- which is the wrong trade,
    because the clips are the content and the track has other arrivals.

    Measured on a real track: the biggest rise in Timeless is 20.0s in, about
    27 beats, which cannot hold an eight-clip build-up. Aiming there silently
    dropped three clips; the next arrival that fits is later and costs nothing.
    """
    if not track.beats:
        return None
    need = turn_at
    candidates = track.drops or ([(track.drop, 0.0)] if track.drop else [])
    for at, _gain in candidates:
        want = at - max(0.0, lead)
        di = min(range(len(track.beats)),
                 key=lambda i: abs(track.beats[i] - want))
        if di - need >= 0:
            return at
    return track.drop


def _start_beat(track: Track, turn_at: int, total: int, *,
                lead: float = 0.0, aim: float | None = None) -> int:
    """Which beat the arrangement starts on, so the drop lands on the turn.

    `lead` is how many SECONDS of the turn's slot should play before the drop.
    Aiming the slot's start at the drop itself was the first version and it is
    subtly wrong: the drop then coincides with the beginning of the clip rather
    than with anything in it. On a 1v2 clutch that put the drop on the defuse
    afterwards -- two seconds past the kill that actually won the round.

    Floored to a phrase so the acts sit on the track's phrases and not merely
    on its beats. A negative answer means there is more material before the
    turn than there is music before the drop, and the caller trims.
    """
    beats = track.beats
    if track.drop is None or not beats:
        return 0
    want = (aim if aim is not None else track.drop) - max(0.0, lead)
    di = min(range(len(beats)), key=lambda i: abs(beats[i] - want))
    start = di - turn_at
    start -= start % PHRASE                      # floor to a phrase boundary
    if start + total > len(beats) - 1:
        # Not enough track left after the drop. Pull back to whatever fits
        # rather than running off the end of the grid mid-act.
        start = max(0, len(beats) - 1 - total)
        start -= start % PHRASE
    return start


def arrange(plans: Sequence[Any], track: Track, *, lead: float = 0.45,
            order: str = "story", kills: Sequence[Any] = ()) -> Arc:
    """Clips + a track -> an Arc, with the drop landing on the turn's last kill.

    `order` picks between the three theories in ORDERS. "story" is the default
    because it is the only one that tells the viewer what the session was; the
    others exist to be compared against it on real footage.
    """
    beats = track.beats
    order = order if order in ORDERS else "story"
    ordered = _sequence(plans, order)
    if not ordered or len(beats) < PHRASE * 2:
        return Arc()

    dropped: list[Any] = []
    while True:
        turn = _turn_index(ordered)
        acts = _acts(ordered, turn)
        turn_beats, lead_s = _turn_shape(ordered[turn], kills, track.bpm)
        widths = _widths(ordered, acts, turn_beats)
        turn_at = sum(widths[:turn])
        aim = _reachable_drop(track, turn_at, lead_s)
        if aim is not None and beats:
            near = min(beats, key=lambda b: abs(b - aim))
            if abs(near - aim) <= DROP_SNAP:
                aim = near
        start = _start_beat(track, turn_at, sum(widths), lead=lead_s, aim=aim)
        if start >= 0 or len(ordered) <= 1:
            break
        # More material before the turn than music before the drop. The slide
        # is what goes: it is the part of the arc whose job is to be got past,
        # and losing its earliest clip costs the reel least.
        loser = next((i for i, a in enumerate(acts) if a == "slide"), None)
        if loser is None:
            break
        dropped.append(ordered.pop(loser))

    start = max(0, start)
    slots: list[Slot] = []
    at = start
    for plan, act, width in zip(ordered, acts, widths):
        if at + width > len(beats) - 1:
            dropped.append(plan)
            continue
        s0, s1 = beats[at], beats[at + width]
        fast = width <= FAST_BEATS
        if act == "turn" and aim is not None:
            # THE KILL LANDS ON THE DROP -- a hair before it, never after. `pre`
            # is measured from where the drop actually falls inside this slot
            # rather than assumed, so the snapped beat grid cannot shift it.
            # Clamped to leave half a second of clip after the kill.
            pre = max(0.0, min((s1 - s0) - 0.5, aim - s0 - TURN_BIAS))
        elif fast:
            pre = min(FAST_PRE, (s1 - s0) * 0.15)
        elif width >= QUANTISE_MIN_BEATS and at + width < len(beats):
            # Cut on a beat AND kill on a beat: round the run-up to whole beats
            # off the same grid the slot starts on.
            n = max(1, min(width - 2, round(lead / (60.0 / (track.bpm or 120.0)))))
            pre = beats[at + n] - s0
        else:
            pre = lead
        slots.append(Slot(
            plan=plan, start=s0, length=s1 - s0, act=act, pre=pre,
            # The turn is anchored on the LAST kill: a clutch is won by its
            # last one, and anchoring on the first put the drop on the defuse
            # two seconds afterwards. A short slot shows the busiest kill --
            # there is only room for one.
            anchor="last" if act == "turn" else
                   ("busiest" if fast else "first")))
        at += width

    turn_slot = next((i for i, s in enumerate(slots) if s.act == "turn"), -1)
    arc = Arc(slots=slots, turn=turn_slot, start_beat=start, dropped=dropped,
              order=order, drop=aim)
    if aim is not None:
        arc.drop_at = next((i for i, s in enumerate(slots)
                            if s.start <= aim < s.start + s.length), -1)
    log.info("%s arc over %d clip(s) from beat %d: %s", order, len(slots),
             start, arc.describe())
    if turn_slot >= 0:
        log.info("the turn is clip %d (%s), %.1fs into the track; the drop is "
                 "at %s", turn_slot + 1,
                 ", ".join(getattr(slots[turn_slot].plan, "labels", None) or
                           [f"{getattr(slots[turn_slot].plan, 'kills', 0)} kills"]),
                 slots[turn_slot].start,
                 f"{aim:.1f}s" if aim is not None else "no drop")
    if arc.drop_at >= 0 and arc.drop_at != turn_slot:
        # Said out loud rather than silently accepted: it means the music ran
        # out of room before the turn, and the reel will not land as designed.
        log.info("the drop landed on clip %d, not the turn -- the track is "
                 "too short before its drop for this many clips",
                 arc.drop_at + 1)
    if dropped:
        log.info("%d clip(s) left out: the track has %d beats and the arc "
                 "needed more", len(dropped), len(beats))
    return arc
