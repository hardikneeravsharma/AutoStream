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
# How long a reel is when nobody says: whole 8-bar phrases, near these lengths.
TARGET_SECONDS = {"landscape": 46.0, "vertical": 30.0}
# ...and the longest it grows to hold clips the player picked by hand. The
# reference edits run 48 to 86 s, so a landscape reel may reach the longest of
# them; a vertical one stops short of the 60 s a Short is allowed.
MAX_SECONDS = {"landscape": 86.0, "vertical": 58.0}
PHRASE_BARS = 8


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


def moments(clips: list[dict], beat: float) -> list[Moment]:
    """Every usable moment in the chosen clips, in clip order.

    Kills within GROUP_BEATS of each other share a moment. A moment whose clip
    holds less than MIN_RUN of footage before its first kill is folded into
    the next one when it can be, and dropped when it cannot -- there is
    nothing to show before it.
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
            if g[0] < run:
                # Not enough footage before it: show it only as part of the
                # next kill's shot, and only if that one is close enough.
                if len(g) > 1 and g[-1] - g[0] <= GROUP_BEATS * beat * 2:
                    usable.append(g)
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


def drop_still(moments_: list[Moment], stats: dict[int, dict | float | None]) -> tuple[list[Moment], int]:
    """Moments with action around their kill, and how many were dropped.

    `stats` maps id(moment) to what was measured around it (see studio.action);
    a moment with no measurement is kept (nothing is known against it).
    Surviving moments gain strength from their action, so of two double kills
    the one where something visibly happens wins.
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
    t = 0
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
        run = div if m.seq > 0 else run_beats
        # The kills' own span is added to the shot, not taken out of its
        # run-up: v9's climax triple (three kills in half a second) was left
        # one beat of run-up because the span came out of it.
        if heroes and i in heroes:
            run = max(run, 2 * div, int(math.ceil(HERO_RUN_SECONDS / beat - 1e-6)))
        pre = max(run, nb - post)
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
            cap = max(run + span + post, shot_cap(base, beat))
            pre = max(run, min(pre, cap - span - post))
        out.append((pre, span, post))
        t += pre + span + post
    return out


def order(moments_: list[Moment], looks: dict[int, list[float]] | None = None,
          opener_ok=None) -> list[Moment]:
    """A build, not a list: a strong opener, rising middle, the best at the climax, a strong close.

    Sequences stay together. The strongest sequence goes about two thirds of
    the way in, the second strongest opens, the third closes. With `looks`
    (clip group -> colour histogram) the middle is then spread so two shots
    that look alike -- the same walls, the same light -- are not back to back.
    """
    seqs: dict[int, list[Moment]] = {}
    for m in moments_:
        seqs.setdefault(m.group, []).append(m)
    ranked = sorted(seqs.values(), key=lambda s: (-max(x.strength for x in s), s[0].group))
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
                flash_share: float = 0.0, beat: float = 0.5, div: int = 1) -> None:
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
    # soft transitions -- Story's crossfades and dips, not a hard cut forever.
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
        near_bright = ((any(k in BRIGHT_KILL for k in prev["fx"]) and prev["duration"] - prev["pre"] < BRIGHT_GAP)
                       or (any(k in BRIGHT_KILL for k in s["fx"]) and s["pre"] < BRIGHT_GAP))
        other_place = look_similarity(looks.get(prev["clip"]), looks.get(s["clip"])) < LOOK_SAME
        if prev["clip"] == s["clip"]:
            t = "t01"
        elif zoom and i in marks:
            t = zoom
        elif on_bar and owed >= 1.0 - 1e-6 and not near_bright:
            t, owed = "t02", owed - 1.0
        elif whip and last_soft != whip and other_place:
            t = whip
        else:
            t = "t01"
        s["transition"], s["tlen"] = t, 0.0          # 0: the part's own length, set when checked
        if t not in ("t01", "t02"):
            last_soft = t


def climax(shots: list[dict], strengths: list[float], pools: dict[str, list[str]],
           speed_ok=None) -> None:
    """The strongest hero moment stops time: a freeze with a push-in, slowed into its kill. In place.

    v1-v6 played the best kill at the speed of every other kill; the
    references hold their big moment (still frames 5-15% of the edit).
    """
    heroes = [i for i, s in enumerate(shots) if s.get("hero")]
    if not heroes:
        return
    best = max(heroes, key=lambda i: (strengths[i] if i < len(strengths) else 0.0, i))
    # Only the climax freezes: v8 froze the opener's triple too, from the
    # pool, and the climax stopped being the moment time stops.
    others = [h for h in (pools.get("hero") or []) if h != "h02"] or ["h01"]
    for i in heroes:
        if i != best and "h02" in shots[i]["hero_fx"]:
            shots[i]["hero_fx"] = [others[i % len(others)]] + [h for h in shots[i]["hero_fx"] if h not in ("h02", others[i % len(others)])]
    s = shots[best]
    if "h02" not in s["hero_fx"]:
        s["hero_fx"] = ["h02"] + (["h05"] if "h05" in s["hero_fx"] else [])
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
