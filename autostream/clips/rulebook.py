"""The editor's rulebook: how a pile of kills becomes a reel that reads as edited.

Every rule here came out of making the same reel again and again from one
70-minute Valorant recording, reviewing each version against popular YouTube
edits cut to the same song, writing down what was wrong, and fixing it. Each
rule says what went wrong without it. The studio's planner calls these; they
hold no state and touch no files, so each one is tested on its own.

MOMENTS, NOT CLIPS
    A clip is how the cutter packaged a stretch of footage. A reel is made of
    MOMENTS: a kill with enough run-up to see the fight. A clip with three kills
    nine seconds apart is three moments -- shown as a quick sequence with the
    walking between them cut out -- not one shot that shows the first kill and
    captions it TRIPLE KILL.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# Kills closer than this (in beats, or GROUP_SECONDS, whichever is longer) stay
# in one shot: both are on screen and a cut between them would chop the fight
# in half. Beats alone split every double kill at 134 BPM, where 2.5 beats is
# 1.1 s, and v10's middle became seven identical two-shot sequences.
GROUP_BEATS = 2.5
GROUP_SECONDS = 1.8
# The least run-up a moment may have. A shot that opens ON its kill shows a
# body falling and no fight: measured in v1, shot 7 did exactly that.
MIN_RUN_BEATS = 1.0
MIN_RUN_SECONDS = 0.5
# How long a shot may run on after its last kill. Every tail longer than this
# in v1 wandered into reloading, the player's own death or a death-recap card.
MAX_TAIL_BEATS = 2
# ...and how long it ORDINARILY runs on, the rest going to the next shot's
# run-up. The frames after a kill are the least interesting in any shot -- a
# body falling, a reload, a walk away -- while the frames before the next kill
# are the fight building, which is what makes the kill read. So an ordinary
# shot cuts a beat after its kill and hands what it saved forward. The reel
# does not get shorter: the same time is spent where it shows something.
# MAX_TAIL_BEATS already stopped tails wandering into a death recap; this
# spends what was left of them. The closer keeps its full tail -- the last kill
# is meant to hang -- and so does a jump cut inside a sequence, which has no
# next run-up to give to.
TAIL_BEATS = 1
# How long a reel is when nobody says: whole 8-bar phrases, near these lengths.
TARGET_SECONDS = {"landscape": 46.0, "vertical": 30.0}
# ...and the longest it grows to hold clips the player picked by hand. The
# reference edits run 48 to 86 s, so a landscape reel may reach the longest of
# them; a vertical one stops short of the 60 s a Short is allowed.
MAX_SECONDS = {"landscape": 86.0, "vertical": 58.0}
PHRASE_BARS = 8
# HOW LONG, ASKED FOR. The style's length is the default and every reel ever
# planned without a choice. "part" fills the stretch of song the player chose;
# "all" puts every chosen clip in, at the style's pace, however long that runs.
# Either way the style keeps the feel -- pace, effects, flashes -- and stops
# deciding the length: dwayIR, 25 clips and a long part picked, came out a 43 s
# Hype reel with 11 clips "left out to fit the reel's length".
FILLS = ("style", "part", "all")
# The closest two kills are put when every kill must fit a length: a run-up of
# MIN_RUN_SECONDS and a quarter second of the kill landing. Under this a cut is
# a flicker, not a fight.
MIN_KILL_GAP_SECONDS = MIN_RUN_SECONDS + 0.25


@dataclass
class Moment:
    """One thing the reel shows: a kill, or kills close together, from one clip."""
    clip: dict
    kills: list[float]                # seconds into the clip, all shown in this shot
    group: int                        # index of the clip this came from
    seq: int = 0                      # position in the clip's sequence of moments
    seq_len: int = 1
    caption: str = ""
    strength: float = 0.0

    @property
    def first(self) -> float:
        return self.kills[0]

    @property
    def last(self) -> float:
        return self.kills[-1]


def label_for(kills: int) -> str:
    return {2: "DOUBLE KILL", 3: "TRIPLE KILL", 4: "QUADRA KILL"}.get(kills, "ACE" if kills >= 5 else "")


def moments(clips: list[dict], beat: float, *, keep_short: bool = False,
            dropped: list[tuple[str, float]] | None = None) -> list[Moment]:
    """Every usable moment in the chosen clips, in clip order.

    Kills within GROUP_BEATS of each other share a moment. A moment whose clip
    holds less than MIN_RUN of footage before its first kill is folded into
    the next one when it can be, and dropped when it cannot -- there is
    nothing to show before it.

    KEEP EVERY KILL (`keep_short`) keeps it instead: the shot starts on the
    clip's first frame, with what run-up there is, and the planner may slow
    that run-up to reach its mark (studio.stretch_to). Measured on dwayIR and
    Aftrhrs, "too little run-up" was how a kill most often went missing from a
    clip the player had chosen for it. `dropped` collects (clip path, kill) for
    every kill that is still left out, so the page can say which and why.
    """
    run = max(MIN_RUN_BEATS * beat, MIN_RUN_SECONDS)
    out: list[Moment] = []
    for gi, c in enumerate(clips):
        dur = float(c.get("duration") or 0.0)
        ks = sorted(float(k) for k in (c.get("kills") or []) if 0.0 <= float(k) <= dur + 1e-6)
        if not ks:
            ks = [dur * 0.5]
        groups: list[list[float]] = [[ks[0]]]
        for k in ks[1:]:
            if k - groups[-1][-1] <= max(GROUP_BEATS * beat, GROUP_SECONDS):
                groups[-1].append(k)
            else:
                groups.append([k])
        usable: list[list[float]] = []
        carry: list[float] = []
        for g in groups:
            g = carry + g
            carry = []
            if g[0] < run and not keep_short:
                # Not enough footage before it: show it only as part of the
                # next kill's shot, and only if that one is close enough.
                if len(g) > 1 and g[-1] - g[0] <= GROUP_BEATS * beat * 2:
                    usable.append(g)
                elif dropped is not None:
                    dropped.extend((c.get("path", ""), k) for k in g)
                continue
            usable.append(g)
        total = sum(len(g) for g in usable)
        for si, g in enumerate(usable):
            m = Moment(clip=c, kills=g, group=gi, seq=si, seq_len=len(usable))
            if si == len(usable) - 1 and total >= 2:
                m.caption = label_for(total)
            m.strength = total * 2.0 + len(g)
            out.append(m)
    return out


def phrase_seconds(beat: float, fmt: str, available: float, want: float = 0.0) -> float:
    """How long the reel is: whole 8-bar phrases near the format's usual length.

    v1 used every clip and ran 127 s against references of 48 and 86 s. When
    there is less material than one phrase, the reel is as long as the material.

    THE CLIPS WERE PICKED, so with nobody asking for a length the reel is as
    long as it takes to hold them, rounded UP to a whole phrase and capped at
    MAX_SECONDS. Aiming at the format's usual 46 s instead left ten of twenty
    hand-picked clips out of DRIPSKETCHERS1 "to fit the reel's length", and
    rebuilding it as hype -- whose shots are shorter, so the same clips read as
    less material -- shrank it to one 14 s phrase of three clips. A reel is
    never shortened to drop clips the player chose; only the cap does that.
    """
    bar = 4.0 * beat
    phrase = PHRASE_BARS * bar
    if want:
        n = max(1, int(round(want / phrase)))
        seconds = n * phrase
        while seconds > available + 1e-6 and n > 1:
            n -= 1
            seconds = n * phrase
        return seconds if seconds <= available + 1e-6 else available
    if available + 1e-6 < phrase:
        return available
    n = max(1, math.ceil(available / phrase - 1e-6))
    return min(n, max(1, int(MAX_SECONDS.get(fmt, 86.0) // phrase))) * phrase


def select(moments_: list[Moment], seconds: float, length_of) -> list[Moment]:
    """The strongest moments that fill `seconds`, keeping each clip's sequence whole.

    `length_of(moment)` is the planned shot length. A sequence is taken or left
    as a unit, so a TRIPLE KILL never shows two of its three kills.
    """
    seqs: dict[int, list[Moment]] = {}
    for m in moments_:
        seqs.setdefault(m.group, []).append(m)
    ranked = sorted(seqs.values(), key=lambda s: (-max(x.strength for x in s), s[0].group))
    chosen: list[list[Moment]] = []
    used = 0.0
    for s in ranked:
        if used >= seconds - 1e-6:
            break
        chosen.append(s)
        used += sum(length_of(m) for m in s)
    return [m for s in chosen for m in s]


def select_fit(moments_: list[Moment], seconds: float, length_of) -> list[Moment]:
    """The strongest sequences that FIT in `seconds`, whole, in clip order.

    select() takes the strongest until the length is reached, so it runs over
    by up to a sequence -- right for a soft length, wrong for the end of a
    chosen part, where the overrun is cut off the reel's end. This skips a
    sequence that would not fit and tries the next, so a short part keeps as
    many kills as it can hold rather than stopping at the first ace that
    would not go in.
    """
    seqs: dict[int, list[Moment]] = {}
    for m in moments_:
        seqs.setdefault(m.group, []).append(m)
    ranked = sorted(seqs.values(), key=lambda s: (-max(x.strength for x in s), s[0].group))
    took: set[int] = set()
    used = 0.0
    for s in ranked:
        need = sum(length_of(m) for m in s)
        if used + need <= seconds + 1e-6:
            took.add(s[0].group)
            used += need
    return [m for m in moments_ if m.group in took]


# ------------------------------------------------------------------ action

# A moment whose footage around the kill moves less than this share of the
# reel's typical moment is not a fight on screen. Measured in v2: the two
# lowest of 57 were the player's own death camera (a kill read off the feed
# while lying dead, p90 frame change 4.9) and a player standing still who died
# a moment later (4.1). The median moment was 14.
MIN_ACTION_SHARE = 0.45


def _action_of(v) -> float | None:
    if isinstance(v, dict):
        v = v.get("action")
    return float(v) if v is not None else None


def drop_still(moments_: list[Moment], stats: dict[int, dict | float | None],
               keep_all: bool = False) -> tuple[list[Moment], int]:
    """Moments with action around their kill, and how many were dropped.

    `stats` maps id(moment) to what was measured around it (see studio.action);
    a moment with no measurement is kept (nothing is known against it).
    Surviving moments gain strength from their action, so of two double kills
    the one where something visibly happens wins.

    With `keep_all` (the player asked to keep every kill) a still moment stays
    in, at the bottom of the ranking: the measure says it is dull, not that it
    is not a kill, and the player chose that clip for it.
    """
    action = {k: _action_of(v) for k, v in stats.items()}
    known = sorted(v for v in action.values() if v is not None)
    if len(known) < 4:
        return moments_, 0
    med = known[len(known) // 2]
    keep = []
    for m in moments_:
        a = action.get(id(m))
        if a is not None and a < MIN_ACTION_SHARE * med:
            if keep_all:
                m.strength -= 1.0
                keep.append(m)
            continue
        if a is not None:
            m.strength += min(2.0, a / max(med, 1e-6)) - 1.0
        keep.append(m)
    # A sequence that lost a moment keeps its caption only if the kills it
    # still shows are the number it claims.
    groups: dict[int, list[Moment]] = {}
    for m in keep:
        groups.setdefault(m.group, []).append(m)
    for g in groups.values():
        total = sum(len(m.kills) for m in g)
        for j, m in enumerate(g):
            m.seq, m.seq_len = j, len(g)
            m.caption = label_for(total) if j == len(g) - 1 and total >= 2 else ""
    return keep, len(moments_) - len(keep)


# ------------------------------------------------------------------ pace

def energy_profile(peaks: list[float], seconds: float):
    """-> e(t0, t1): how loud the song is between two song times, 1.0 = typical.

    Typical is the median of the song's non-silent envelope, so a song that is
    loud throughout reads as 1.0 throughout and changes nothing.
    """
    if not peaks or seconds <= 0:
        return lambda a, b: 1.0
    n = len(peaks)
    per = seconds / n
    body = sorted(p for p in peaks if p > 0.05) or [1.0]
    med = body[len(body) // 2] or 1.0

    def e(a: float, b: float) -> float:
        i, j = max(0, int(a / per)), min(n, max(int(a / per) + 1, int(b / per)))
        if j <= i:
            return 1.0
        return (sum(peaks[i:j]) / (j - i)) / med
    return e


# Where a shot falls inside its 8-bar phrase changes its length: the first two
# bars establish (longer shots), the last bar runs into the next phrase (shorter
# ones). v10's energy was flat after the drums, so every shot in 20 seconds was
# the same length and the kills came evenly spaced like a metronome.
PHRASE_SHAPE = ((8, 1.5), (24, 1.0), (32, 0.5))
# No shot but the opener's build and the closer's exit holds longer than this.
# With the phrase shape at double length, v11 held one double kill for 5.8 s.
MAX_SHOT_SECONDS = 4.0
# The longest run-up a kill may be given when a chosen song part is longer
# than the clips fill (see studio._lengthen_run_ups). Uncapped, "as far as the
# clip has footage" gave one kill of a 90 s MONTERO part a 31.7 s run-up -- a
# 1m23s round clip's walk to site -- while the 27 reference edits' median shot
# runs 0.43-2.67 s and their longest opening shot 15 s. Twice the shot limit
# above is enough to see the fight build; past it the reel ends early instead.
MAX_LEAD_UP_SECONDS = 2 * MAX_SHOT_SECONDS
# No shot is shorter than this, whatever the grid. The fastest reference edit
# holds a median shot of 0.43 s (Young Girl A, 45 cuts a minute), so this sits
# under every edit measured and only ever stops a shot becoming a flicker.
MIN_SHOT_SECONDS = 0.4


def shot_cap(base: int, beat: float) -> int:
    """The longest a middle shot may be, in beats: 4 s, or twice the style's
    shot if that is shorter. 4 s alone is 11 beats at 162 BPM, and v13's
    velocity short held a triple kill's run-up for ten of them."""
    return max(2, min(int(MAX_SHOT_SECONDS / beat), 2 * base))


def phrase_factor(steps_in_phrase: int, div: int = 1) -> float:
    for end, factor in PHRASE_SHAPE:
        if steps_in_phrase < end * div:
            return factor
    return 1.0


def pace(e: float, base: int, floor: int = 2, cap: int = 16) -> int:
    """Shot length in grid steps for a stretch of song this loud.

    Quieter than 70% of typical -> twice the style's shot; louder than 110% ->
    half of it, never under `floor`. v2 cut every shot at 4 beats through the
    intro, the drums arriving and the breakdown alike: flow_corr 0.04 against
    0.29-0.49 for the references.
    """
    if e < 0.7:
        return min(cap, base * 2)
    if e > 1.1:
        return max(floor, base // 2)
    return base


# A hero moment's run-up is at least this long, whatever the tempo: at 83 BPM
# the montage pace is two-beat shots, and v9's climax got one beat of run-up.
HERO_RUN_SECONDS = 1.2

# A follow-up in a multi-kill sequence is a jump cut: the fight is already
# established, so it gets a beat in and a beat out, not a full shot. v2 played
# a triple kill as three 3-second shots of the same corridor.
FOLLOW_UP_BEATS = 2


def walk(moments_: list[Moment], *, beat: float, energy, song_start: float,
         base: int, open_beats: int, run_beats: int, pre_share: float,
         first_index: int = 0, downbeat_pos: int = 0, fixed: dict[int, tuple[int, int, int]] | None = None,
         heroes: set[int] | None = None, closer_post: int = 0,
         phrase_from: int | None = None, div: int = 1) -> list[tuple[int, int, int]]:
    """(pre, span, post) in GRID STEPS for each moment, walking the song.

    `beat` is the length of one step and `div` how many steps make a musical
    beat, so every length here is a whole step and a bar is `4 * div` of them.
    Everything the caller passes in -- `base`, `open_beats`, `run_beats`,
    `first_index`, `downbeat_pos`, `closer_post`, `phrase_from` -- is in steps.

    WHY THE GRID IS FINER THAN A BEAT FOR FAST STYLES. In whole beats the
    shortest shot the rules allow is two of them, so at 78 BPM nothing could be
    shorter than 1.54 s while the edits that style copies hold 0.6-0.9 s. All
    five styles collapsed onto the same three-beat shot: measured over 19
    reels, the median shot was 2.99 beats whatever the style, against 0.82
    beats for Hype's references and 2.36 for Montage's. The references
    themselves cut off the beat -- 26 of the 27 measured edits land more cuts
    on half beats than on beats (median 0.53 against 0.29) -- so a half- or
    quarter-beat step is what they are actually built on.

    Each shot's length comes from how loud the song is where it plays. Shots of
    a bar or more are nudged by their run-up so the cut after them lands on a
    bar line: the long shots are the ones a listener hears the cut of.
    `first_index` is the song's step index at reel zero; `fixed` pins the
    lengths of chosen shots (the build before a drop).
    """
    out: list[tuple[int, int, int]] = []
    bar = 4 * div
    phrase = PHRASE_BARS * bar
    tail_max = MAX_TAIL_BEATS * div
    follow_max = FOLLOW_UP_BEATS * div
    # A step may be well under MIN_SHOT_SECONDS, so the floor is counted in
    # steps rather than assumed to be one of them.
    floor = max(1, int(math.ceil(MIN_SHOT_SECONDS / beat - 1e-6)))
    keep_tail = max(1, TAIL_BEATS * div)
    t = 0
    # What the shot before cut short of its tail, waiting to be spent on this
    # shot's run-up. See TAIL_BEATS.
    carry = 0
    for i, m in enumerate(moments_):
        if fixed and i in fixed:
            p = fixed[i]
            out.append(p)
            t += sum(p)
            continue
        if i == 0:
            nb = open_beats
        else:
            a = song_start + t * beat
            # Eight musical beats of song, not eight steps: how loud the song is
            # here is a question about the music, not about the grid.
            nb = pace(energy(a, a + 8 * beat * div), base, floor, 16 * div)
        # Quiet is the SONG being quiet -- decided before the phrase shape
        # lengthens a shot, or every follow-up in a phrase's first bars stayed
        # long (v11).
        quiet = i > 0 and nb > base
        if i > 0 and phrase_from is not None and t >= phrase_from:
            f = phrase_factor((t - phrase_from) % phrase, div)
            nb = max(floor, int(round(nb * f)))
        if heroes and i in heroes:
            nb = max(nb, base)                 # a hero moment is never a flicker
        elif m.seq > 0 and not quiet:
            nb = min(nb, follow_max)           # a quiet stretch still gets its long shots
        span = int(math.ceil((m.last - m.first) / beat - 1e-6)) if len(m.kills) > 1 else 0
        if i == 0:
            post = max(1, min(tail_max, nb // 4))
        elif closer_post and i == len(moments_) - 1:
            post = closer_post                 # the last kill gets a bar to land in
        elif m.seq > 0:
            post = div                         # a jump cut gets a beat out, at any grid
        else:
            post = min(tail_max, max(1, int(round(nb * (1.0 - pre_share)))))
        # Cut just after the kill and hand the rest to the next run-up. A
        # follow-up neither gives nor takes: its fight is already established,
        # so it stays the tight jump cut FOLLOW_UP_BEATS makes it and passes
        # the time on to the next shot that opens a fight. The closer keeps its
        # tail, which is the ending.
        take = 0
        if i > 0 and m.seq == 0:
            take, carry = carry, 0
            if post > keep_tail and not (closer_post and i == len(moments_) - 1):
                carry = post - keep_tail
                post = keep_tail
        run = div if m.seq > 0 else run_beats
        # The kills' own span is added to the shot, not taken out of its
        # run-up: v9's climax triple (three kills in half a second) was left
        # one beat of run-up because the span came out of it.
        if heroes and i in heroes:
            run = max(run, 2 * div, int(math.ceil(HERO_RUN_SECONDS / beat - 1e-6)))
        # `take` lengthens the run-up only: the tail was computed from the
        # shot's own length, so handing time forward must not grow it back.
        pre = max(run, nb - post) + take
        # Never the opener: its kill is what reel zero was placed by. The nudge
        # is up to a beat either way, whatever the step.
        if nb >= bar and i > 0:
            end = first_index + t + pre + span + post
            delta = (downbeat_pos - end) % bar
            if 0 < delta <= div:
                pre += delta
            elif 0 < bar - delta <= div and pre - (bar - delta) >= run:
                pre -= bar - delta
        if 0 < i < len(moments_) - 1:
            # The cap rises by what was handed forward, or the carry would be
            # clipped away again and the tail given up for nothing.
            cap = max(run + span + post, shot_cap(base, beat) + take)
            pre = max(run, min(pre, cap - span - post))
        out.append((pre, span, post))
        t += pre + span + post
    return out


# How the reel may be arranged. `build` is what every reel has always been and
# stays the default; the others answer questions it cannot -- "show me what
# actually happened", "open on the best one", "give me a different draw".
# `hits` -- "Best order" on the page -- puts the biggest moments on the song's
# biggest hits; see best_order().
ARRANGEMENTS = ("build", "time", "best", "shuffle", "hits",
                # "Perfect fit (slower)": not an order() shape at all --
                # studio.plan() hands the whole reel to arrange_fit.plan(),
                # which searches the order and the song together. Here it is
                # only a name normalise() keeps; order() treats it as build.
                "fit",
                # "Follow the song": the same, handed to director.plan() --
                # a set-up take into the drop, the drums after it.
                "sections")
# Where the climax sits when a reel is built rather than ordered by hand: about
# two thirds in, which is where the reference edits put theirs.
CLIMAX_AT = 2 / 3


def _at_seconds(at: str) -> float:
    """"1h04m20s" / "43m43s" / "57s" -> seconds. Anything else sorts first."""
    total, num = 0.0, ""
    for ch in str(at or ""):
        if ch.isdigit():
            num += ch
            continue
        if num and ch in "hms":
            total += int(num) * {"h": 3600, "m": 60, "s": 1}[ch]
        num = ""
    return total


def _when(seq: list[Moment]) -> tuple:
    """When a fight happened, for chronological order. Run first, then the
    time inside it: two runs on the same day are told apart by the recording's
    own mtime, which is the only thing that orders them."""
    c = seq[0].clip
    return (int(c.get("mtime") or 0), _at_seconds(c.get("at")),
            int(c.get("round") or 0), seq[0].group)


def _strength(seq: list[Moment]) -> float:
    return max(x.strength for x in seq)


def arrange_seqs(ranked: list[list[Moment]], how: str, seed: int = 0) -> list[list[Moment]]:
    """The sequences in the asked-for order. `ranked` is strongest first."""
    if how == "time":
        return sorted(ranked, key=_when)
    if how == "best":
        return list(ranked)
    if how == "shuffle":
        import random

        out = list(ranked)
        random.Random(seed or 1).shuffle(out)
        return out
    return list(ranked)


def spread_clips(seqs: list[list[Moment]]) -> list[list[Moment]]:
    """Keep two bursts of the SAME CLIP off each other's heels.

    The strongest moments cluster: a two-minute clip with twelve kills offers
    six of the best bursts in the pack, so an order built on strength alone
    puts them side by side. On screen that is not a cut at all -- it is the
    same corner of the same map twice, seconds apart in real time, and it
    reads as a stutter. Measured on a 41-shot reel: 21 of its 40 cuts went
    from a clip straight back to itself.

    Each run of same-clip neighbours is broken by pulling the nearest later
    sequence from another clip in front of it. Nothing is dropped, nothing is
    reordered beyond the swap, and a burst stays whole -- a TRIPLE KILL is one
    sequence and moves as one. Where there is nothing to swap with (a reel cut
    from two clips) the order stands: the alternative is refusing to make a
    reel at all.
    """
    out = list(seqs)
    for i in range(1, len(out)):
        if out[i][0].group != out[i - 1][0].group:
            continue
        # Bring the next sequence from a different clip in between. The two
        # same-clip sequences keep their order relative to each other; only
        # something else is placed between them.
        for j in range(i + 1, len(out)):
            if out[j][0].group != out[i - 1][0].group:
                out.insert(i, out.pop(j))
                break

    # Anything the forward pass could not reach -- a clash in the last pair has
    # nothing left in front of it to borrow -- is settled by a swap: find any
    # place whose neighbours do not mind this sequence, and whose own occupant
    # this spot does not mind either.
    def fits(sq, at: int, skip: int) -> bool:
        for n in (at - 1, at + 1):
            if n == skip or not 0 <= n < len(out):
                continue
            if out[n][0].group == sq[0].group:
                return False
        return True

    for i in range(1, len(out)):
        if out[i][0].group != out[i - 1][0].group:
            continue
        for k in range(len(out)):
            if k in (i, i - 1):
                continue
            if fits(out[i], k, i) and fits(out[k], i, k):
                out[i], out[k] = out[k], out[i]
                break

    # AND A CLIP'S OWN BURSTS STAY IN THE ORDER THEY HAPPENED. Ranking each
    # burst separately lets a later, stronger one outrank an earlier one --
    # and then a shot can replay footage a shot before it already showed,
    # which is the thing `_lengthen_run_ups` and the follow-up fold exist to
    # prevent. The places are kept; what sits in them is put back in clip
    # order, so the spread above survives and the invariant does too.
    where: dict[int, list[int]] = {}
    for i, sq in enumerate(out):
        where.setdefault(sq[0].group, []).append(i)
    for group, at in where.items():
        if len(at) < 2:
            continue
        in_order = sorted((out[i] for i in at), key=lambda sq: sq[0].seq)
        for i, sq in zip(at, in_order):
            out[i] = sq
    return out


def pin_seqs(seq: list[list[Moment]], pins: dict) -> list[list[Moment]]:
    """Move pinned sequences to the slots they were pinned to.

    `pins` maps "open" / "climax" / "close" to a clip path. A pin is a promise
    the player made to themselves, so it beats every rule above it -- including
    the one that puts the strongest moment at the climax.
    """
    if not pins or len(seq) < 3:
        return seq
    want = {k: str(v).lower() for k, v in pins.items() if v}
    if not want:
        return seq

    def find(path: str):
        for s in seq:
            if str(s[0].clip.get("path", "")).lower() == path:
                return s
        return None

    taken, slots = [], {}
    for slot in ("open", "climax", "close"):
        got = find(want[slot]) if slot in want else None
        if got is not None and got not in taken:
            slots[slot] = got
            taken.append(got)
    rest = [s for s in seq if s not in taken]
    out = list(rest)
    if "climax" in slots:
        out.insert(max(0, min(len(out), int(round(len(out) * CLIMAX_AT)))), slots["climax"])
    if "open" in slots:
        out.insert(0, slots["open"])
    if "close" in slots:
        out.append(slots["close"])
    return out


# What makes a moment big, past its kill count: a clutch or an ace says so in
# the clip's own caption or labels (VALORANT_25_LAST-ALIVE-1v3, TEAM-ACE). Worth
# about one more kill: a 1v3 with two kills ranks with a triple, not above a 4K.
BIG_WORDS = ("CLUTCH", "LAST-ALIVE", "LAST ALIVE", "1V", "ACE")
BIG_BONUS = 2.5


def impact(seq: list[Moment]) -> float:
    """How big a sequence is, for putting it on a big hit."""
    c = seq[0].clip
    text = " ".join([str(c.get("caption") or ""), str(c.get("name") or "")]
                    + [str(x) for x in (c.get("labels") or [])]).upper()
    return _strength(seq) + (BIG_BONUS if any(w in text for w in BIG_WORDS) else 0.0)


def arc_weights(n: int) -> list[float]:
    """Slot weights without a song to read them off: the build's shape -- a
    strong open, rising to the climax two thirds in, a strong close."""
    if n <= 0:
        return []
    peak = max(0, int(round((n - 1) * CLIMAX_AT)))
    # Rising to the climax, falling back a little after it.
    out = [0.3 + 0.6 * i / peak if i <= peak and peak else 0.5 for i in range(n)]
    out[0] = max(out[0], 0.8)
    out[-1] = max(out[-1], 0.85)
    out[peak] = 1.0
    return out


# A measure of the song across a reel's slots that varies by less than this
# share of its largest value says nothing about where the big moments belong.
FLAT_SPREAD = 0.2

# Each costs about what putting the biggest moment on an ordinary hit does.
SAME_PLACE_COST = 0.6
SAME_SHAPE_COST = 0.25
WEAK_OPENER_COST = 1.0


def best_order(ranked: list[list[Moment]], weights: list[float] | None,
               looks: dict[int, list[float]] | None = None, opener_ok=None) -> list[list[Moment]]:
    """BEST ORDER: the biggest moments on the song's biggest hits. `ranked` is strongest first.

    `weights[i]` is how big the hit the i-th kill of the reel lands on is --
    the planner reads it off the song (its bass hits, the big ones, how loud it
    is there); without a song the build's own arc stands in. A sequence keeps
    its kills together and in the order they happened, and is scored on the
    hit its LAST kill lands on: that is the one captioned TRIPLE KILL.

    Then no two alike back to back: the same place (the colour histograms
    spread_looks reads) or the same multi-kill shape twice running costs
    about what a big moment on an ordinary hit does. The opener still has to
    carry a build when the song has one.

    A heuristic, not a search: deal the biggest sequences to the biggest
    slots, then keep any move of one sequence, or swap of two, that scores
    better until none does -- and the build itself if that scores better
    still. Swaps alone stuck: two sequences of different lengths shift every
    slot between them, and on dwayIR the strongest double kill finished on
    one of the weakest slots. Fast enough to run on every plan; arrange_fit
    is where an exact answer would live.
    """
    seqs = list(ranked)
    if len(seqs) <= 1:
        return seqs
    n = sum(len(s) for s in seqs)
    w = list(weights or [])[:n]
    if not w:
        w = arc_weights(n)
    if len(w) < n:
        w += [sum(w) / len(w)] * (n - len(w))
    lo, hi = min(w), max(w)
    w = [(x - lo) / (hi - lo) if hi > lo else 0.5 for x in w]
    imp = {id(s): impact(s) for s in seqs}
    a, b = min(imp.values()), max(imp.values())
    big = {k: ((v - a) / (b - a) if b > a else 0.5) for k, v in imp.items()}
    place = places([s[0].group for s in seqs], looks) if looks else {}

    def score(order_: list[list[Moment]]) -> float:
        total, pos = 0.0, 0
        for k, s in enumerate(order_):
            v = big[id(s)]
            for j in range(len(s)):
                total += v * w[pos + j] * (1.0 if j == len(s) - 1 else 0.25)
            pos += len(s)
            if k:
                prev = order_[k - 1]
                if place and place[prev[0].group] == place[s[0].group]:
                    total -= SAME_PLACE_COST
                if len(s) > 1 and len(prev) == len(s):
                    total -= SAME_SHAPE_COST
        if opener_ok is not None and not opener_ok(order_[0][0]):
            total -= WEAK_OPENER_COST
        return total

    # The deal: the k-th biggest sequence aims its last kill at the k-th
    # biggest slot, and the sequences are laid out in the order of their aims.
    by_weight = sorted(range(n), key=lambda i: (-w[i], i))
    by_size = sorted(seqs, key=lambda s: (-big[id(s)], s[0].group))
    aim = {id(s): by_weight[k] for k, s in enumerate(by_size)}
    dealt = sorted(seqs, key=lambda s: (aim[id(s)], s[0].group))
    # The build is the other start: strong open, climax, close.
    flat = order([m for s in seqs for m in s], looks, opener_ok)
    by_group = {s[0].group: s for s in seqs}
    built = [by_group[g] for g in dict.fromkeys(m.group for m in flat)]

    def climb(cur: list[list[Moment]]) -> tuple[float, list[list[Moment]]]:
        best = score(cur)
        for _ in range(8):
            better = False
            for i in range(len(cur)):
                # Move sequence i to every other place...
                for j in range(len(cur)):
                    if j == i:
                        continue
                    trial = cur[:i] + cur[i + 1:]
                    trial.insert(j, cur[i])
                    got = score(trial)
                    if got > best + 1e-9:
                        best, cur, better = got, trial, True
                        break
            for i in range(len(cur)):
                # ...and swap it with every other.
                for j in range(i + 1, len(cur)):
                    cur[i], cur[j] = cur[j], cur[i]
                    got = score(cur)
                    if got > best + 1e-9:
                        best, better = got, True
                    else:
                        cur[i], cur[j] = cur[j], cur[i]
            if not better:
                break
        return best, cur

    a_score, a = climb(dealt)
    b_score, b = climb(built)
    return a if a_score >= b_score else b


def order(moments_: list[Moment], looks: dict[int, list[float]] | None = None,
          opener_ok=None, arrange: str = "build", pins: dict | None = None,
          seed: int = 0, slot_weights: list[float] | None = None) -> list[Moment]:
    """A build, not a list: a strong opener, rising middle, the best at the climax, a strong close.

    Sequences stay together. The strongest sequence goes about two thirds of
    the way in, the second strongest opens, the third closes. With `looks`
    (clip group -> colour histogram) the middle is then spread so two shots
    that look alike -- the same walls, the same light -- are not back to back.

    `arrange` replaces that shape with a plainer one -- see ARRANGEMENTS -- and
    `pins` forces chosen clips into the opener, climax or closer whichever
    shape is in use. Both leave the sequences themselves whole: a TRIPLE KILL
    never shows two of its three kills, however the reel is ordered.
    """
    # A SEQUENCE IS A BURST, NOT A CLIP. `group` is the clip a moment came
    # from, and keying on it alone kept every kill of a clip together -- so a
    # two-minute clip with twelve kills contributed six moments that played
    # back to back, minutes of real time apart, looking like the same corner
    # six times. Measured on a 41-shot reel: 21 of its 40 cuts went from a
    # clip straight back to itself.
    #
    # `seq` is the burst within the clip, already split by proximity (kills
    # closer than GROUP_BEATS/GROUP_SECONDS). Keying on both keeps a TRIPLE
    # KILL whole -- which is the promise this function makes -- while letting
    # two unrelated bursts from one clip be spread across the reel.
    seqs: dict[tuple[int, int], list[Moment]] = {}
    for m in moments_:
        seqs.setdefault((m.group, m.seq), []).append(m)
    ranked = sorted(seqs.values(), key=lambda s: (-_strength(s), s[0].group, s[0].seq))
    if arrange == "hits":
        out = pin_seqs(spread_clips(best_order(ranked, slot_weights, looks, opener_ok)), pins or {})
        return [m for s in out for m in s]
    if arrange in ("time", "best", "shuffle"):
        out = pin_seqs(spread_clips(arrange_seqs(ranked, arrange, seed)), pins or {})
        return [m for s in out for m in s]
    if len(ranked) <= 2:
        return [m for s in ranked[::-1] for m in s]
    best = ranked[0]
    # The opener carries the build over the intro, so it must have the footage
    # for it: v10's opener had 2.0 s before its kill and the two-bar build
    # came out 1.8 s long.
    candidates = ranked[1:]
    if opener_ok is not None:
        good = [c for c in candidates if opener_ok(c[0])]
        if good:
            candidates = good + [c for c in candidates if c not in good]
    opener = candidates[0]
    others = [c for c in ranked[1:] if c is not opener]
    closer = others[0]
    rest = sorted(others[1:], key=lambda s: (max(x.strength for x in s), s[0].group))
    at = max(0, int(round(len(rest) * 2 / 3)))
    middle = rest[:at] + [best] + rest[at:]
    seq = [opener] + middle + [closer]
    if looks:
        seq = spread_looks(seq, looks)
    # Pins last: spreading the looks moves sequences about, and a pin that was
    # applied before it would not have survived the move. Clips are spread
    # just before them, for the same reason.
    seq = pin_seqs(spread_clips(seq), pins or {})
    return [m for s in seq for m in s]


# Two clips whose colour histograms overlap this much are the same place: the
# same map under the same light. Measured over all 703 pairs of the 38 clips:
# median 0.55, top tenth above 0.72. Places are CLUSTERS, not pairs -- in v7 the
# opener's five clips were 0.53-0.76 from each other (one deathmatch map) and
# 0.32-0.47 from the other three (another), so checking neighbours pairwise at
# 0.72 swapped one orange corridor for another.
LOOK_SAME = 0.6


def look_similarity(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    return float(sum(min(x, y) for x, y in zip(a, b)))


def places(groups: list[int], looks: dict[int, list[float]]) -> dict[int, int]:
    """Clip group -> place id. Unknown looks are their own place.

    Each place is anchored on its first clip and a clip joins the first place
    whose anchor it resembles. Not single linkage: one in-between clip (0.66
    from one map, 0.69 from the other) chained both maps into one place.
    """
    anchors: list[int] = []
    place: dict[int, int] = {}
    for g in groups:
        if g in place:
            continue
        for n, a in enumerate(anchors):
            if look_similarity(looks.get(a), looks.get(g)) >= LOOK_SAME:
                place[g] = n
                break
        else:
            place[g] = len(anchors)
            anchors.append(g)
    return place


def spread_looks(seqs: list[list[Moment]], looks: dict[int, list[float]]) -> list[list[Moment]]:
    """Alternate places -- and shapes -- through the middle, when the material allows.

    The opener, the climax and the closer keep their positions. A middle
    sequence that repeats the one before it -- the same place, or the same
    shape (a single kill, a two-shot jump cut, a three-shot run) -- swaps with
    the nearest later one that repeats neither. Places first: v7 opened on five
    shots of one map. Shapes too: v11's first phrase was four double kills in a
    row, each a 4-beat shot and a 2-beat jump cut.
    """
    if len(seqs) < 4:
        return seqs
    place = places([s[0].group for s in seqs], looks)
    best = max(range(len(seqs)), key=lambda i: max(m.strength for m in seqs[i]))
    fixed = {0, len(seqs) - 1, best}
    out = list(seqs)

    def clash(a: list[Moment], b: list[Moment]) -> int:
        return (place[a[0].group] == place[b[0].group]) * 2 + (len(a) == len(b))
    for i in range(1, len(out)):
        if i in fixed or not clash(out[i - 1], out[i]):
            continue
        here = clash(out[i - 1], out[i])
        for j in range(i + 1, len(out)):
            if j not in fixed and clash(out[i - 1], out[j]) < here:
                out[i], out[j] = out[j], out[i]
                break
    return out


# ------------------------------------------------------------------ effects

# Effects that fill the frame with light. Two of them within a second of each
# other -- a white-flash cut into a white-flash kill -- is a white frame, not
# an effect: v3's shot 15 was one.
BRIGHT_KILL = ("k03", "k16", "k12")
BRIGHT_CUT = ("t02",)
BRIGHT_GAP = 1.0


def budget(shots: list[dict], pools: dict[str, list[str]], only: str | None = None) -> None:
    """Size every shot's effects to the moment. In place.

    - An ordinary kill gets one effect. Two stacked on every kill (v1-v3) reads
      as a template; the stack is kept for hero moments and captioned kills.
    - A follow-up in a sequence (the same clip as the shot before) is a jump
      cut: no transition effect, never a bright effect, and real speed.
    - Two ramped shots never touch unless the second is a hero.
    - No bright cut within BRIGHT_GAP of a bright kill, either way round.

    `only` ("kill", "transition", "speed") limits the rules to that kind, so
    mixing one kind again never changes another: a conflict is then resolved
    by changing the kind being mixed. A replacement effect is never the one the
    shots either side opened with.
    """
    def may(kind: str) -> bool:
        return only is None or only == kind

    calm = [k for k in pools.get("kill") or [] if k not in BRIGHT_KILL] or ["k01"]

    def calmer(i: int, fx: list[str]) -> list[str]:
        # Neither neighbour's opening effect: replacing the shot BEFORE a
        # conflict once handed it the effect the shot after already had.
        near = {shots[x]["fx"][0] for x in (i - 1, i + 1) if 0 <= x < len(shots) and shots[x]["fx"]}
        out = []
        for j, k in enumerate(fx):
            if k in BRIGHT_KILL:
                choices = [c for c in calm if c not in near and c not in out] or calm
                k = choices[(i + j) % len(choices)]
            out.append(k)
        return out

    for i, s in enumerate(shots):
        follow = i > 0 and shots[i - 1]["clip"] == s["clip"]
        # RAMPS MARK MOMENTS. A velocity pool of nothing but ramps put a speed
        # ramp on every one of v13's twenty shots, so none of them stood out.
        ramp = s.get("speed") not in (None, "s00")
        if may("speed") and ramp and not s.get("hero") and i < len(shots) - 1 and (
                follow or (i > 0 and shots[i - 1].get("speed") not in (None, "s00"))):
            s["speed"] = "s00"
        if may("kill") and not s.get("hero") and not s.get("caption"):
            s["fx"] = s["fx"][:1]
        if follow:
            if may("transition"):
                s["transition"], s["tlen"] = "t01", 0.0
            if may("kill"):
                s["fx"] = calmer(i, s["fx"])
        if i > 0 and s["transition"] in BRIGHT_CUT:
            prev = shots[i - 1]
            prev_bright = any(k in BRIGHT_KILL for k in prev["fx"]) and prev["duration"] - prev["pre"] < BRIGHT_GAP
            mine_bright = any(k in BRIGHT_KILL for k in s["fx"]) and s["pre"] < BRIGHT_GAP
            if mine_bright and may("kill") and only != "transition":
                s["fx"] = calmer(i, s["fx"])
            elif (prev_bright or mine_bright) and may("transition"):
                s["transition"], s["tlen"] = "t01", 0.0
            elif prev_bright and may("kill"):
                prev["fx"] = calmer(i - 1, prev["fx"])
        s["fx"] = list(dict.fromkeys(s["fx"]))


# ------------------------------------------------------------------ look

# The references' colourfulness, measured the same way on all 26: median 0.309,
# middle half 0.267-0.352. v3 measured 0.411. Aimed a little above the median
# so a warm or neon grade still reads as itself.
TARGET_SATURATION = 0.32

# How much each grade multiplies colourfulness at full saturation, and how much
# colourfulness each 1.0 of saturation trim takes away -- measured by pushing
# frames from 13 of the clips through each grade's filters at trims 1.0, 0.85
# and 0.7 (the loss was 0.71-0.76 per unit for every colour grade).
GRADE_COLOUR = {"g01": 1.0, "g02": 1.252, "g03": 1.404, "g04": 0.969, "g05": 1.415,
                "g06": 0.665, "g07": 0.132, "g08": 1.518, "g09": 0.726}
TRIM_SLOPE = 0.73


def saturation_trim(sats: list[float], grade: str) -> float:
    """The saturation multiplier that brings this footage, under this grade, to the references' level.

    Deliberately washed-out grades (bleach, monochrome, faded film) are left
    alone: their low colour is the point of choosing them.
    """
    known = sorted(x for x in sats if x)
    gain = GRADE_COLOUR.get(grade, 1.0)
    if not known or gain < 0.8:
        return 1.0
    footage = known[len(known) // 2]
    want = TARGET_SATURATION / max(footage, 1e-3)
    trim = 1.0 - (gain - want) / TRIM_SLOPE
    return round(max(0.6, min(1.15, trim)), 3)


# ------------------------------------------------------------------ sound

# Game sound plays from this long before each kill to this long after it, and
# at GAME_BED (a fraction) everywhere else. v1-v4 laid the whole clip's audio
# under the song: footsteps and reloads kept the music ducked throughout and
# the reel measured 1.1 LU of loudness range against the references' 5.
KILL_SOUND_BEFORE = 0.3
KILL_SOUND_AFTER = 0.35
GAME_BED = 0.12
# The music's level for the half beat before a hero kill: nearly gone, so the
# kill lands into a gap.
HERO_DIP = 0.15
# Integrated loudness of the finished reel. The references measure -10.75 to
# -8.5 LUFS in their middle half; v1-v4 were normalised to -14 and played
# about 4.5 dB quieter than the edits beside them.
LOUDNESS = -10.0
# The music dips to this fraction for the KILL_DUCK_SECONDS before every kill
# and is back at full level on it: the gunfire plays into the gap and the beat
# lands with the kill. A compressor keyed on the game sound pumped on every
# footstep; a dip ON the kill took the beat's punch away.
KILL_DUCK = 0.5
KILL_DUCK_SECONDS = 0.3
# The limiter's ceiling on the master (about -1.5 dBFS): the loud references
# peak above 0 dBTP and AAC overshoots, so the headroom is left here.
PEAK_LIMIT = 0.84


# ------------------------------------------------------------------ open and close

# A song that is quiet before its drums gets a build: the opener's run-up
# covers the last INTRO_BARS of the intro at half speed, drained of colour,
# and the colour and the first kill arrive with the drums. v1-v5 threw the
# intro away and opened on a second and a half of walking out of a fade; both
# Timeless references open with four to five seconds before anything happens.
INTRO_BARS = 2
INTRO_QUIET = 0.7
# The last kill lands a bar before the end and the reel slows and fades over
# that bar. v1-v5 ended two beats after an ordinary kill with the music cut.
ENDING_BEATS = 4


def wants_build(energy, drums_in: float | None, beat: float) -> bool:
    """Whether the song has a quiet stretch before its drums worth building over."""
    if not drums_in or drums_in < INTRO_BARS * 4 * beat:
        return False
    return energy(drums_in - INTRO_BARS * 4 * beat, drums_in) < INTRO_QUIET


def ending_fade(beat: float) -> float:
    """How long the picture and the music take to fade out: most of a bar."""
    return round(max(1.2, min(2.2, 3.0 * beat)), 3)


# ------------------------------------------------------------------ cuts and time

def transitions(shots: list[dict], starts: list[int], *, first_kill_beat: int,
                looks: dict[str, list[float] | None], pools: dict[str, list[str]],
                flash_share: float = 0.0, beat: float = 0.5, div: int = 1,
                flash_ok=None) -> None:
    """Choose each cut's transition from where it falls in the music and what it joins. In place.

    - A follow-up in a sequence is a hard jump cut.
    - The cut NEAREST each new 8-bar phrase (counted from the first kill, which
      sits on the drums) is marked: a zoom-through, or a flash without one.
    - A cut to somewhere that looks different is a whip, but never two whips in
      a row -- counting soft cuts only, since a hard cut between two whips does
      not stop the pair reading as a stamp.
    - Cuts on the grid between places carry a white flash, spaced to the rate
      the style's reference edits flash at, never within a second of a bright
      kill.

    v1-v6 drew from the pool at random, and push, iris and pixel dissolves
    landed mid-phrase between two shots of the same wall. v7 kept only flashes
    the mix happened to draw on a bar line: 3.9 a minute against the
    references' 12-33.

    WHY NEITHER MARK ASKS FOR AN EXACT HIT ANY MORE. Both used to: the phrase
    zoom wanted a cut exactly on the phrase, the flash a cut exactly on a bar.
    That worked only because a style's shot was rounded to a power of two
    beats, which put every cut on a bar line and cost up to 39% of the shot
    length the style's references actually hold. With the pace taken from the
    references instead, a three-beat shot walks through the bar -- and a
    velocity reel of twenty cuts came out with no flash at all, because not one
    cut landed on a bar. So the phrase mark takes the nearest cut, and the
    flash falls back to the beat when the bars cannot carry the style's rate.
    """
    order_ = list(dict.fromkeys(pools.get("transition") or []))
    pool = set(order_)
    soft = [t for t in order_ if t not in ("t01", "t02")]
    # A style without a zoom or a whip marks phrases and places with its own
    # soft transitions -- Clean's crossfades and dips, not a hard cut forever.
    zoom = "t05" if "t05" in pool else ("t02" if "t02" in pool else (soft[-1] if soft else None))
    whip = "t06" if "t06" in pool else (soft[0] if soft else None)
    bar = 4 * div
    phrase = PHRASE_BARS * bar
    last_soft = None
    cuts = max(1, len(shots) - 1)
    owed = 0.0
    # The cut nearest each phrase, within half a bar of it.
    marks: set[int] = set()
    if len(shots) > 1:
        at = first_kill_beat + phrase
        while at <= starts[-1] + bar:
            near = min(range(1, len(shots)), key=lambda i: (abs(starts[i] - at), i))
            if abs(starts[near] - at) <= bar / 2:
                marks.add(near)
            at += phrase
    # Bar lines while there are enough of them to carry the style's flash rate,
    # the beat when there are not.
    on_bars = sum(1 for i in range(1, len(shots)) if starts[i] % bar == first_kill_beat % bar)
    unit = bar if on_bars >= flash_share * cuts else div
    for i in range(1, len(shots)):
        s, prev = shots[i], shots[i - 1]
        b = starts[i]
        owed += flash_share
        on_bar = b % unit == first_kill_beat % unit
        if flash_ok is not None:
            # A style that flashes at every tempo measures the clean picture either side of
            # the flash instead of keeping a second from any bright kill (studio.flash_clear),
            # and flashes on any cut, not only one on the beat: its cuts are on the song's
            # hits already, and at 100 BPM most of them fall on the off-beat -- 7 flashes on
            # 41 cuts of Skechers, against 28 on 32 at 160 BPM.
            near_bright = not flash_ok(i)
            on_bar = True
        else:
            near_bright = ((any(k in BRIGHT_KILL for k in prev["fx"]) and prev["duration"] - prev["pre"] < BRIGHT_GAP)
                           or (any(k in BRIGHT_KILL for k in s["fx"]) and s["pre"] < BRIGHT_GAP))
        other_place = look_similarity(looks.get(prev["clip"]), looks.get(s["clip"])) < LOOK_SAME
        if prev["clip"] == s["clip"]:
            t = "t01"
        elif zoom and i in marks:
            # Two phrase marks close together would otherwise stamp the same
            # soft cut twice running -- which is the thing `last_soft` exists to
            # stop, and a phrase mark is no more exempt from it than a whip is.
            t = zoom
            if t == last_soft:
                t = next((x for x in soft if x != last_soft), "t01")
        elif on_bar and owed >= 1.0 - 1e-6 and not near_bright:
            t, owed = "t02", owed - 1.0
        elif whip and last_soft != whip and other_place:
            t = whip
        else:
            t = "t01"
        s["transition"], s["tlen"] = t, 0.0          # 0: the part's own length, set when checked
        if t not in ("t01", "t02"):
            last_soft = t


# THE CLIMAX'S HERO TREATMENT, loudest first: the double punch is two hits on
# the one kill, the spotlight a quieter one. The first family the reel's pool
# holds is the one the climax gets.
CLIMAX_HEROES = ("h01", "h03")


def climax(shots: list[dict], strengths: list[float], pools: dict[str, list[str]],
           speed_ok=None) -> None:
    """The strongest hero moment is the reel's big one: rushed in, slowed on its kill, and
    given the loudest hero treatment the pool holds. In place.

    v1-v6 played the best kill at the speed of every other kill; the
    references hold their big moment. It used to hold it by stopping time --
    a freeze with a push-in -- until the player had the freezes taken
    out on 2026-10-24. It never freezes now: what sets it apart is the speed,
    the one run in the reel that accelerates and then hangs on its kill.
    """
    heroes = [i for i, s in enumerate(shots) if s.get("hero")]
    if not heroes:
        return
    best = max(heroes, key=lambda i: (strengths[i] if i < len(strengths) else 0.0, i))
    s = shots[best]
    # The pool's own entry for the family, so a style that draws a variant
    # (h01tight) gives the climax that one rather than the plain part.
    pool = list(pools.get("hero") or [])
    top = next((p for fam in CLIMAX_HEROES for p in pool if p[:3] == fam), "")
    have = list(s.get("hero_fx") or [])
    if top and not any(h[:3] == top[:3] for h in have):
        s["hero_fx"] = [top] + (["h05"] if "h05" in have else [])
    # It rushes in and hangs on the kill: the run into the best moment is the
    # one place the reel accelerates (v8 ran into it at the speed of every
    # other shot). Rushing eats footage 2.2 times as fast, so a clip without
    # the run-up for it slows into its kill instead -- v9's climax lost a beat
    # of its run-up to the rush and came out shorter than an ordinary shot.
    s["speed"] = "s04" if speed_ok is None or speed_ok(s, "s04") else "s02"


def first_loud(energy, beats: list[float], beat: float, downbeat_pos: int = 0) -> float:
    """The first downbeat where the song is at its typical loudness for a whole phrase.

    Where a song has no clear moment the drums come in, the first kill goes
    here. v12 found no drums in its song and started at the first beat of a
    quiet sixteen-second intro, so a short spent its opening seconds waiting.
    """
    if not beats:
        return 0.0
    phrase = PHRASE_BARS * 4 * beat
    for i, b in enumerate(beats):
        if i % 4 != downbeat_pos:
            continue
        if energy(b, b + phrase) >= 0.95:
            return b
    return beats[0]
# The highest true peak the finished file may measure. The limiter's ceiling is
# lowered by any overshoot and the master runs again.
TRUE_PEAK_MAX = -0.5


# VARIETY IN A MONTAGE IS THE BACKDROP CHANGING. Six shots from one round reads
# as one long round however they are cut, because the map, the lighting and the
# angle barely move. The reference reel for the fast-paced headshot style took
# 38 shots from 41 clips and never more than three from any of them.
#
# Off by default: a reel built from four clips genuinely needs more than three
# shots from each, and capping that would leave it short of its own length.
# See docs/STYLE-FAST-PACED-HEADSHOT.md section 4.3.
CLIP_SHOTS_CAP = 3


FIGHT_GAP = 6.0     # s: a clip's kills further apart than this are separate fights


def one_fight_per_clip(moments: list[Moment], dropped: list[tuple[str, float]] | None = None,
                       gap: float = FIGHT_GAP) -> list[Moment]:
    """Each clip's strongest fight only -- the fast styles' repeat rule (decided 2026-10-21).

    A fight is the clip's moments with no more than `gap` between one and the next. Two
    fights of one file cut half a second apart read as the same scene twice (same map, same
    round, same skin): the first That Acid render had one, and the review called it a repeat.
    The slower styles keep R13's cap instead.
    """
    by_clip: dict[int, list[list[Moment]]] = {}
    for m in sorted(moments, key=lambda m: (m.group, m.first)):
        fights = by_clip.setdefault(m.group, [])
        if fights and m.first - fights[-1][-1].last <= gap:
            fights[-1].append(m)
        else:
            fights.append([m])
    # AND THE FIGHT IS ONE SHOT. Kept as separate moments, the order dealt them round the
    # reel: a Fast-paced headshot render showed one clip's three kills at 0:02, 1:00 and 1:04
    # with other clips between, which is the same scene three times. Merged, the fight plays
    # once, its kills in the order they happened -- a multi-kill as one take.
    merged: dict[int, Moment] = {}
    for fights in by_clip.values():
        best = max(fights, key=lambda f: (sum(m.strength for m in f), len(f)))
        kills = sorted(k for m in best for k in m.kills)
        head = best[0]
        merged[id(head)] = Moment(clip=head.clip, kills=kills, group=head.group, seq=head.seq,
                                  seq_len=1, caption=label_for(len(kills)) if len(kills) > 1 else head.caption,
                                  strength=sum(m.strength for m in best))
        if dropped is not None:
            for f in fights:
                if f is not best:
                    dropped += [(m.clip["path"], k) for m in f for k in m.kills]
    return [merged[id(m)] for m in moments if id(m) in merged]


# TWO SHOTS OF ONE CLIP CLOSER THAN THIS ARE THE SAME FIGHT SHOWN TWICE: what the
# render gate calls a repeat (reelcheck, "repeat-fight"), and the same reach
# studio.OWN_KILLS_WITHIN gives a shot's own later kills -- so a kill this close
# to another is either in that shot or in no other.
REPEAT_FIGHT_GAP = 3.0
# ...and the longest a run of such kills may be and still be one shot: a run-up
# and a landing short of MAX_SHOT_SECONDS. Past it the run is cut, not the rule.
FIGHT_SPAN = MAX_SHOT_SECONDS - MIN_RUN_SECONDS


def one_shot_per_fight(moments_: list[Moment], dropped: list[tuple[str, float]] | None = None,
                       gap: float = REPEAT_FIGHT_GAP, span: float = FIGHT_SPAN) -> list[Moment]:
    """Moments of one clip whose kills are closer than `gap` become ONE moment.

    moments() splits a clip's kills into bursts GROUP_SECONDS apart (1.8 s), and
    each burst is its own shot -- so two kills 2.3 s apart in a clutch went into
    two shots, the order put other clips between them, and the reel showed the
    same fight twice. Measured on the Velocity reel of Skechers: three such pairs
    (1.85 s, 2.32 s and 2.90 s apart) failed the render gate's repeat-fight check.
    The gate only flags it; this is the rule that makes it not happen.

    Merged while the merged run spans no more than `span`; past that the weaker of
    the two moments is left out, because its kills cannot go in a shot of their
    own without being the same fight again. `dropped` collects (clip, kill) for those.
    """
    by_clip: dict[int, list[Moment]] = {}
    for m in moments_:
        by_clip.setdefault(m.group, []).append(m)
    keep: dict[int, Moment] = {}           # id(original head) -> the moment that stands for it
    for group in by_clip.values():
        group = sorted(group, key=lambda m: m.first)
        runs: list[list[Moment]] = []
        for m in group:
            if runs and m.first - runs[-1][-1].last < gap:
                runs[-1].append(m)
            else:
                runs.append([m])
        for run in runs:
            if len(run) == 1:
                keep[id(run[0])] = run[0]
                continue
            # Merge from the strongest outwards while the span allows; the rest go.
            ranked = sorted(run, key=lambda m: (-m.strength, m.first))
            took = [ranked[0]]
            for m in ranked[1:]:
                lo = min(x.first for x in took + [m])
                hi = max(x.last for x in took + [m])
                if hi - lo <= span + 1e-9:
                    took.append(m)
                elif dropped is not None:
                    dropped.extend((m.clip.get("path", ""), k) for k in m.kills)
            took.sort(key=lambda m: m.first)
            head = took[0]
            if len(took) == 1:
                keep[id(head)] = head
                continue
            kills = sorted(k for m in took for k in m.kills)
            caption = next((m.caption for m in took if m.caption), "")
            keep[id(head)] = Moment(clip=head.clip, kills=kills, group=head.group, seq=head.seq,
                                    seq_len=head.seq_len, caption=caption,
                                    strength=max(m.strength for m in took) + len(kills) - len(head.kills))
    return [keep[id(m)] for m in moments_ if id(m) in keep]


# A SHOT HOLDS ITS OWN LATER KILLS ONLY AS FAR AS THE REEL'S PACE ALLOWS: each
# within this many of the style's kill gaps of the one before. A double kill 2.4 s
# apart is one shot of a story reel and two seconds of nothing in a Hype one,
# whose kills land 0.75 s apart: held, it passed three marks by and the reel's
# cut rate halved (28 cuts a minute against the references' 54).
HOLD_GAPS = 2.0


def hold_within(moments_: list[Moment], reach: float,
                dropped: list[tuple[str, float]] | None = None) -> list[Moment]:
    """Each moment's kills cut to the run its shot will hold: every next one within `reach`.

    The kills after the run are left out of the moment -- not given a shot of
    their own, which would be the same fight twice (REPEAT_FIGHT_GAP) -- and
    collected in `dropped`.
    """
    out = []
    for m in moments_:
        ks = list(m.kills)
        n = 1
        while n < len(ks) and ks[n] - ks[n - 1] <= reach + 1e-9:
            n += 1
        if n == len(ks):
            out.append(m)
            continue
        if dropped is not None:
            dropped.extend((m.clip.get("path", ""), k) for k in ks[n:])
        out.append(Moment(clip=m.clip, kills=ks[:n], group=m.group, seq=m.seq, seq_len=m.seq_len,
                          caption=m.caption, strength=m.strength))
    return out


def space_apart(items: list, key, when=None, apart: int = 3, fixed: tuple[int, ...] = (0,)) -> list:
    """`items` reordered so two of one clip (`key`) are at least `apart` places apart, where they can be.

    NO PING-PONG. The build order ranks every burst of a clip at the clip's own
    strength, so the two biggest clips' bursts all sort to the end together, and
    spread_clips -- which only stops a clip following itself -- dealt them out
    A B A B A B: the last six shots of the Velocity reel of Skechers played two
    clips by turns. Each shot that sits within `apart` of another of its clip is
    swapped with the nearest one that sits well in both places. Positions in
    `fixed` (the opener) are not moved. Where there is nothing to swap with --
    a reel of two clips -- the order stands.

    `when(item)` orders one clip's own items: they are put back in the order
    they happened, into the places the clip now holds, so no shot replays
    footage an earlier one showed.
    """
    out = list(items)
    n = len(out)

    def clear(at: int, k, skip: int, gap: int) -> bool:
        for j in range(at - gap + 1, at + gap):
            if j in (at, skip) or not 0 <= j < n:
                continue
            if key(out[j]) == k:
                return False
        return True

    # As far apart as asked where the clips allow it; where they do not -- a
    # dozen shots from four clips -- at least never back to back.
    for gap in range(apart, 1, -1):
        for i in range(n):
            if i in fixed or clear(i, key(out[i]), i, gap):
                continue
            for j in sorted(range(n), key=lambda j: (abs(j - i), j)):
                if j == i or j in fixed or key(out[j]) == key(out[i]):
                    continue
                if clear(j, key(out[i]), i, gap) and clear(i, key(out[j]), j, gap):
                    out[i], out[j] = out[j], out[i]
                    break
    if when is not None:
        where: dict = {}
        for i, it in enumerate(out):
            where.setdefault(key(it), []).append(i)
        for at in where.values():
            if len(at) > 1:
                for i, it in zip(at, sorted((out[i] for i in at), key=when)):
                    out[i] = it
    return out


def cap_per_clip(moments: list[Moment], limit: int,
                 dropped: list[tuple[str, float]] | None = None) -> list[Moment]:
    """At most `limit` shots from any one clip, keeping the strongest.

    Order is preserved: the ones that stay play in the order they happened in
    the clip, because a clip's own moments cut out of sequence replay footage
    the shot before has already shown.
    """
    if limit <= 0:
        return list(moments)
    by_clip: dict[int, list[Moment]] = {}
    for m in moments:
        by_clip.setdefault(m.group, []).append(m)
    keep: set[int] = set()
    for group in by_clip.values():
        if len(group) <= limit:
            keep.update(id(m) for m in group)
            continue
        best = sorted(group, key=lambda m: (-m.strength, m.seq))[:limit]
        keep.update(id(m) for m in best)
        if dropped is not None:
            for m in group:
                if id(m) not in keep:
                    dropped += [(m.clip["path"], k) for k in m.kills]
    return [m for m in moments if id(m) in keep]
