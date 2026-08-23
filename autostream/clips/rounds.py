r"""Turning a Counter-Strike 2 recording into rounds, and rounds into highlights.

WHY ROUNDS AND NOT KILLS
    The kill-based clipper is right for a respawn shooter: in Delta Force a
    triple is a triple whenever it happens. Counter-Strike is not like that.
    Three kills opening a round with five teammates alive is a good start; the
    same three kills alone against three opponents is the clip people watch.

    Worse, a kill-based ranking actively buries the best rounds. A 1v2 won with
    a single kill produces one kill and gets cut as a four-second single, ranked
    below every ordinary double in the session.

    So this layer reads the scoreboard (clips/hud.py), cuts the recording into
    rounds, and asks what happened in each.

HOW A ROUND BOUNDARY IS FOUND
    The score changing, not the timer resetting. The score is a discrete step
    that also says WHO WON, and it survives overtime and non-standard modes,
    whereas the timer pauses, turns red, is replaced by the bomb timer and
    resets during warm-up.

    A score is only believed after it has been read the same way several times
    running. That is not defensive programming for its own sake: a single
    misread turned 2-8 into 12-7 in a ten-minute test scan, and one bad frame
    must not be able to invent a round.

AND WHY A DEMO REPLACES ALL OF THAT WHERE THERE IS ONE
    Everything below this line is inference from pixels: the score from matched
    HUD digits, the alive counts beside them, the player's own side from
    correlating their deaths against those counts. It works, and it is the only
    option for a game that gives you nothing else.

    Counter-Strike does give you something else. `from_demo` builds the same
    Round objects out of Valve's own record of the match, where the score, the
    winner, every player's side per round and who was alive at any instant are
    facts rather than readings -- so 1vN is counted instead of inferred, and
    the half-time swap needs no detecting because the roster is simply re-read
    each round. See clips/cs2_demo.py.

HOW "MY SIDE" IS DECIDED
    Not by reading the player cards. When the player dies, THEIR side's alive
    count drops; when they get a kill, the other side's does. Both events are
    already known from the kill feed, so correlating them against the alive
    counters identifies the side without OCR-ing a single name.

    It is decided once per HALF, not per round. Per round was tried: a single
    round supplies too few events and the answer flipped almost every round,
    taking every win and loss with it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .hud import Reading

log = logging.getLogger("autostream.clips.rounds")

# How many consecutive readings must agree before a score is believed.
# Measured need: one misread in a 600-frame scan read 2-8 as 12-7.
SCORE_SETTLE = 3

# A round is at most this long. CS2 rounds are 1:55 plus freeze time and
# overtime; anything longer means the segmentation lost the thread (a menu, a
# map change) and the span should be dropped rather than reported as a round.
MAX_ROUND = 210.0

# ...and at least this long. Shorter spans are score corrections, not rounds.
MIN_ROUND = 8.0

# A round counts as fast when it ends inside this.
FAST_ROUND = 35.0

# ...and as chaotic only if that speed came with bloodshed. A raw count was
# tried first and does not discriminate: nearly every round in a real scan
# ended with 8-10 of the ten players dead, so the count passed every time and
# duration was doing all the work on its own. The RATE separates them -- a fast
# round with everyone dead ran about 0.2 deaths a second against 0.06 for an
# ordinary one.
CHAOS_RATE = 0.15

# Kills this close together are "quick".
FAST_WINDOW = 5.0
FAST_KILLS = 3

MULTI_KILLS = 4          # a "multi-kill round"
ACE_KILLS = 5


@dataclass
class Round:
    number: int
    started: float
    ended: float
    # WHOSE POINTS THESE ARE DEPENDS ON `source`. Read off the scoreboard they
    # are (left, right), because that is all a pixel knows; read from a demo
    # they are (mine, theirs), because it knows which side is the player's and
    # the scoreboard's left and right are then a detail of where the HUD drew
    # them.
    score_before: tuple[int, int]
    score_after: tuple[int, int]
    half: int = 0                       # which side-swap era this round is in
    # "l" | "r" off the scoreboard; "CT" | "T" from a demo, which names it.
    my_side: str | None = None
    won: bool | None = None
    my_kills: int = 0
    my_assists: int = 0
    my_deaths: int = 0
    kill_times: list[float] = field(default_factory=list)
    total_kills: int = 0                # both teams, from the alive counters
    min_my_alive: int | None = None
    kill_overcount: int = 0             # kills the scoreboard did not support
    last_stand_at: float | None = None  # when I became the last one alive
    enemies_at_last_stand: int | None = None
    labels: list[str] = field(default_factory=list)

    # Where this round came from: "hud" for the pixel path, "demo" for Valve's
    # own record. Everything below is demo-only -- the pixel path cannot see
    # any of it, and leaves it empty so the labels that depend on it never fire.
    source: str = "hud"
    reason: str = ""                    # "t_killed", "bomb_defused", ...
    flags: list[str] = field(default_factory=list)   # see _flags()
    headshots: int = 0
    opening_kill: bool = False          # I drew first blood in this round
    pistol: bool = False                # round 1, or the first of a half
    match_point: bool = False
    broke_streak: int = 0               # consecutive losses this win ended

    @property
    def duration(self) -> float:
        return max(0.0, self.ended - self.started)

    @property
    def survived(self) -> bool:
        return self.my_deaths == 0


# ------------------------------------------------------------- segmentation

def _settled(readings: Sequence[Reading], settle: int = SCORE_SETTLE):
    """Yield (time, score) only once a score has held for `settle` readings."""
    run_score, run_len, run_start = None, 0, 0.0
    emitted = None
    for r in readings:
        sc = r.score
        if sc is None:
            continue
        if sc == run_score:
            run_len += 1
        else:
            run_score, run_len, run_start = sc, 1, r.time
        if run_len == settle and run_score != emitted:
            emitted = run_score
            yield run_start, run_score


def halves(steps: Sequence[tuple[float, tuple[int, int]]]) -> list[float]:
    """When the two sides swapped ends. -> the times a new half begins.

    THE BUG THIS EXISTS FOR. At half time the scoreboard swaps sides, so the
    same match reads 2-10 before and 10-2 after. Without noticing, every round
    in the second half has the player on the wrong side and therefore every
    win recorded as a loss. It is invisible in a short test window, which is
    exactly why it has to be handled explicitly rather than hoped about.

    Measured on real footage the swap reads as a reversal with a transient in
    the middle -- (2,10) then a misread (11,11) then (10,2) -- so a reversal is
    looked for across a few steps rather than only between neighbours.
    """
    marks: list[float] = []
    for i, (t, s) in enumerate(steps):
        if s == (0, 0):
            marks.append(t)                     # a new match is a new half
            continue
        if s[0] == s[1]:
            continue                            # cannot tell a reversal apart
        for j in range(i + 1, min(i + 4, len(steps))):
            if steps[j][1] == (s[1], s[0]):
                marks.append(steps[j][0])
                break
    return sorted(set(marks))


def segment(readings: Iterable[Reading]) -> list[Round]:
    """Cut a recording into rounds on confirmed score changes."""
    rs = [r for r in readings if r.score is not None]
    rs.sort(key=lambda r: r.time)
    steps = list(_settled(rs))
    if len(steps) < 2:
        return []
    marks = halves(steps)
    if marks:
        log.info("%d side swap(s) or new match(es) at %s", len(marks),
                 ", ".join(f"{int(m)//60}m{int(m)%60:02d}s" for m in marks))

    def half_of(t: float) -> int:
        return sum(1 for m in marks if t >= m)

    out: list[Round] = []
    for (t0, s0), (t1, s1) in zip(steps, steps[1:]):
        d = (s1[0] - s0[0], s1[1] - s0[1])
        # Exactly one side gaining exactly one point is a round. Anything else
        # is a match change, a misread, or warm-up ending.
        if d not in ((1, 0), (0, 1)):
            continue
        span = t1 - t0
        if not (MIN_ROUND <= span <= MAX_ROUND):
            continue
        # A round that straddles a swap is not a round; the score either side
        # of it describes different ends of the map.
        if half_of(t0) != half_of(t1):
            continue
        out.append(Round(number=s0[0] + s0[1] + 1, started=t0, ended=t1,
                         score_before=s0, score_after=s1, half=half_of(t0)))
    log.info("segmented %d round(s) from %d scoreboard reading(s)",
             len(out), len(rs))
    return out


# --------------------------------------------------- which side is the player

def _alive_at(readings: Sequence[Reading], at: float,
              window: float = 2.0) -> Reading | None:
    best, gap = None, window
    for r in readings:
        if r.alive_l is None or r.alive_r is None:
            continue
        g = abs(r.time - at)
        if g <= gap:
            best, gap = r, g
    return best


def infer_side(readings: Sequence[Reading], deaths: Sequence[float],
               kills: Sequence[float]) -> str | None:
    """Which half of the scoreboard is the player's.

    My death drops MY side's count; my kill drops the other side's. Each event
    is one weak vote and the majority decides, because a single reading can be
    wrong and a single kill can coincide with a teammate's death.
    """
    votes = {"l": 0, "r": 0}
    for t, mine in [(t, True) for t in deaths] + [(t, False) for t in kills]:
        before = _alive_at(readings, t - 2.0)
        after = _alive_at(readings, t + 2.0)
        if not before or not after:
            continue
        dl = (before.alive_l or 0) - (after.alive_l or 0)
        dr = (before.alive_r or 0) - (after.alive_r or 0)
        if dl > 0 and dr <= 0:
            votes["l" if mine else "r"] += 1
        elif dr > 0 and dl <= 0:
            votes["r" if mine else "l"] += 1
    if votes["l"] == votes["r"]:
        return None
    return max(votes, key=votes.get)


# --------------------------------------------------------------- enrichment

def annotate(rounds: list[Round], readings: Sequence[Reading],
             events) -> list[Round]:
    """Fill each round in from the kill feed and the alive counters.

    `events` are killfeed.FeedEvent objects -- kills, assists and deaths.
    """
    rs = sorted(readings, key=lambda r: r.time)
    kills = [e.time for e in events if e.kind == "kill"]
    deaths = [e.time for e in events if e.kind == "death"]
    assists = [e.time for e in events if e.kind == "assist"]

    global_side = infer_side(rs, deaths, kills)
    if global_side:
        log.info("across the whole recording the player is on the %s",
                 "left" if global_side == "l" else "right")

    # One answer per half, from every event in that half.
    by_half: dict[int, str | None] = {}
    for h in sorted({r.half for r in rounds}):
        spans = [r for r in rounds if r.half == h]
        if not spans:
            continue
        lo = min(r.started for r in spans)
        hi = max(r.ended for r in spans)
        by_half[h] = infer_side(
            [r for r in rs if lo <= r.time <= hi],
            [t for t in deaths if lo <= t <= hi],
            [t for t in kills if lo <= t <= hi])
        log.info("half %d (%dm%02ds-%dm%02ds): player on the %s", h,
                 int(lo)//60, int(lo)%60, int(hi)//60, int(hi)%60,
                 {"l": "left", "r": "right"}.get(by_half[h], "unknown"))

    for rd in rounds:
        inside = [r for r in rs if rd.started <= r.time <= rd.ended]
        rd.kill_times = [t for t in kills if rd.started <= t <= rd.ended]
        rd.my_kills = len(rd.kill_times)
        rd.my_assists = sum(1 for t in assists if rd.started <= t <= rd.ended)
        rd.my_deaths = sum(1 for t in deaths if rd.started <= t <= rd.ended)

        # PER HALF, not per round. Deciding it per round was tried and is too
        # noisy to use: one round supplies only a handful of events, and the
        # side flipped almost every round in a real 88-minute scan -- which in
        # turn got the win or loss wrong wherever it flipped. A half has
        # dozens of events and cannot swap in the middle by definition.
        rd.my_side = by_half.get(rd.half) or global_side
        if rd.my_side:
            i = 0 if rd.my_side == "l" else 1
            rd.won = rd.score_after[i] > rd.score_before[i]

        mine = "alive_l" if rd.my_side == "l" else "alive_r"
        theirs = "alive_r" if rd.my_side == "l" else "alive_l"
        curve = [(r.time, getattr(r, mine), getattr(r, theirs)) for r in inside
                 if getattr(r, mine) is not None and getattr(r, theirs) is not None]
        if curve:
            rd.min_my_alive = min(c[1] for c in curve)
            # THE SCOREBOARD BOUNDS THE KILL FEED. The enemy team can lose at
            # most five players, so however many kills the feed reports, it
            # cannot exceed how far their alive count actually fell. This is a
            # completely independent measurement of the same events, and it
            # catches the kill feed's known failure -- an assist whose killer's
            # name is unreadable counting as a kill.
            #
            # Measured over 48 real rounds it fired once, on a round the feed
            # called a six-kill ace in a game where five is the maximum.
            enemy_died = max(c[2] for c in curve) - min(c[2] for c in curve)
            if rd.my_kills > enemy_died:
                log.info("round at %dm%02ds: feed says %d kills but the enemy "
                         "only lost %d players; trusting the scoreboard",
                         int(rd.started)//60, int(rd.started)%60,
                         rd.my_kills, enemy_died)
                rd.kill_overcount = rd.my_kills - enemy_died
                rd.my_kills = enemy_died
                rd.kill_times = rd.kill_times[:enemy_died]
            # Total bloodshed: how far both counts fell from their peak.
            rd.total_kills = ((max(c[1] for c in curve) - min(c[1] for c in curve))
                              + (max(c[2] for c in curve) - min(c[2] for c in curve)))
            # The last stand: the first moment only one of mine was left AND I
            # was still in it. Without the death check this fires for the last
            # teammate alive while the player spectates.
            for t, mn, th in curve:
                if mn == 1 and (rd.my_deaths == 0 or
                                all(d > t for d in deaths
                                    if rd.started <= d <= rd.ended)):
                    rd.last_stand_at = t
                    rd.enemies_at_last_stand = th
                    break
    return rounds


# ------------------------------------------------------------------- labels

def label(rounds: list[Round]) -> list[Round]:
    """Attach every label a round earns, strongest first."""
    for rd in rounds:
        got: list[str] = []
        if rd.my_kills >= ACE_KILLS:
            got.append("ACE")
        if rd.last_stand_at is not None and (rd.enemies_at_last_stand or 0) >= 2:
            n = rd.enemies_at_last_stand
            if rd.won:
                # A 1vN WON needs no kills of its own: defusing under the nose
                # of two opponents, or running the clock out, is the clip.
                got.append(f"CLUTCH 1v{n}")
            elif rd.my_kills >= 1:
                got.append(f"ALMOST 1v{n}")
            # A 1vN LOST with no kills is not a highlight, it is the end of a
            # bad round. Found by reading a demo, where alive counts are exact:
            # a real match produced "ALMOST 1v4" for a round in which the
            # player did nothing at all and then died. The pixel path could
            # never surface it, because it needed kills to infer the counts in
            # the first place.
        if ACE_KILLS > rd.my_kills >= MULTI_KILLS:
            got.append(f"{rd.my_kills} KILLS")
        if rd.last_stand_at is not None and (rd.enemies_at_last_stand or 0) < 2:
            got.append("LAST ALIVE")
        if fast_burst(rd.kill_times):
            got.append(f"{FAST_KILLS}K IN {int(FAST_WINDOW)}s")
        if (rd.duration <= FAST_ROUND and rd.my_kills >= 1 and rd.duration > 0
                and rd.total_kills / rd.duration >= CHAOS_RATE):
            got.append("CHAOS")
        if rd.survived and rd.won is False and rd.my_kills >= 1:
            got.append("SURVIVED THE LOSS")
        got.extend(_demo_labels(rd))
        # STRONGEST FIRST, by the same ranking that decides which round is worth
        # cutting at all. Everything downstream takes labels[0] as "what this
        # round was" -- the filename, the burned caption, the spoken hook -- and
        # before this they took whichever label happened to be appended first.
        # A round that was a kill through smoke in a fast, bloody round came out
        # named CHAOS, because CHAOS is tested earlier in this function.
        rd.labels = sorted(got, key=lambda l: rank_of([l]))
    return rounds


# Kill circumstances worth a label, and what to call them. Every one of these
# is a FLAG ON THE KILL in the demo and invisible to any detector, which is the
# point of reading the demo at all.
#
# They are labelled because they are rare, measured over one full match: 4
# smoke kills and 2 wallbangs in 115, against 48 headshots. A headshot is not
# on this list for exactly that reason -- 42% of kills is not a highlight.
FLAG_LABELS = (
    ("smoke", "THROUGH SMOKE"),
    ("noscope", "NO SCOPE"),
    ("wallbang", "WALLBANG"),
    ("knife", "KNIFE KILL"),
    ("zeus", "ZEUS"),
    ("grenade", "NADE KILL"),
    ("blind", "BLIND KILL"),
)

# A win only breaks a slide if there was one. Two losses is a bad patch; three
# in a row is the thing the round after it is worth watching for.
SLIDE = 3


def _demo_labels(rd: Round) -> list[str]:
    """Labels that only a demo can support. Empty for a scoreboard-read round.

    Guarded on the data rather than on `source`, so a partially filled Round
    cannot earn a label on a field nobody set.
    """
    got: list[str] = []
    for key, name in FLAG_LABELS:
        if key in rd.flags:
            got.append(name)
    if rd.won and rd.broke_streak >= SLIDE:
        got.append("STREAK BREAKER")
    if rd.match_point and rd.won and rd.my_kills >= 1:
        got.append("MATCH POINT")
    # A pistol round is only a highlight if the player did something in it --
    # every match has two, and labelling both regardless would put an ordinary
    # round at the front of the list twice a match.
    if rd.pistol and rd.my_kills >= 2:
        got.append("PISTOL ROUND")
    return got


def fast_burst(times: Sequence[float], n: int = FAST_KILLS,
               window: float = FAST_WINDOW) -> bool:
    """Were n of these kills inside `window` seconds of each other."""
    ts = sorted(times)
    return any(ts[i + n - 1] - ts[i] <= window for i in range(len(ts) - n + 1))


# Strongest first. A round gets ONE clip carrying every label it earned, and
# this decides which label names it -- otherwise a round that is an ace AND a
# 1v3 emits three overlapping clips of the same forty seconds.
RANK = ("ACE", "CLUTCH", "ALMOST", "KILLS", "LAST ALIVE", "K IN",
        # Demo-only, and deliberately below the multi-kills: a smoke kill is a
        # lovely detail, but "ACE" is what makes someone click.
        "NO SCOPE", "KNIFE", "ZEUS", "THROUGH SMOKE", "WALLBANG", "NADE",
        "BLIND", "STREAK BREAKER", "MATCH POINT", "PISTOL",
        "CHAOS", "SURVIVED")


def rank_of(labels: Sequence[str]) -> int:
    for i, key in enumerate(RANK):
        if any(key in l for l in labels):
            return i
    return len(RANK)


def highlights(rounds: list[Round]) -> list[Round]:
    """Only the rounds worth cutting, best first."""
    keep = [r for r in rounds if r.labels]
    keep.sort(key=lambda r: (rank_of(r.labels), -r.my_kills, r.started))
    return keep


# ------------------------------------------------------ rounds from a demo

# Weapons whose name is not enough on its own. Every CS2 knife except the
# bayonet has "knife" in its item name, and the Zeus is filed as a taser.
KNIVES = ("knife", "bayonet")
NADES = ("hegrenade", "molotov", "incgrenade", "inferno", "decoy", "flashbang")


def _flags(kills) -> list[str]:
    """The circumstances of a set of kills, as label keys. See FLAG_LABELS."""
    def weapon(k) -> str:
        return str(getattr(k, "weapon", "") or "").lower()

    got: list[str] = []
    for key, test in (
            ("smoke", lambda k: getattr(k, "thrusmoke", False)),
            ("blind", lambda k: getattr(k, "blinded", False)),
            ("wallbang", lambda k: getattr(k, "penetrated", False)),
            ("noscope", lambda k: getattr(k, "noscope", False)),
            ("knife", lambda k: any(w in weapon(k) for w in KNIVES)),
            ("zeus", lambda k: weapon(k) == "taser"),
            ("grenade", lambda k: weapon(k) in NADES)):
        if any(test(k) for k in kills):
            got.append(key)
    return got


def _same(a: str, b: str) -> bool:
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def from_demo(match, player: str, sync) -> list[Round]:
    """A demo -> the same labelled Rounds the pixel path produces.

    THE DIFFERENCE IS THAT NOTHING HERE IS INFERRED. Segmentation comes from
    round_start/round_end rather than from a score that had to be read the same
    way three times running; the player's side comes from the roster at each
    round's freeze end rather than from correlating their deaths against alive
    counters; and the alive counts themselves are counted down from the roster
    as the deaths land, so "last alive against three" is arithmetic.

    `sync` maps demo time onto the recording -- see cs2_demo.align. Passing an
    unaligned Sync would put every round in the wrong place, so an unusable one
    is refused here rather than quietly producing plausible nonsense.
    """
    if not getattr(sync, "ok", False):
        raise ValueError(f"the demo is not aligned to this recording: "
                         f"{getattr(sync, 'why', 'no alignment')}")
    me = (player or "").strip()
    if not me:
        raise ValueError("from_demo needs to know which player is the local one")

    ordered = sorted(match.rounds, key=lambda r: r.number)
    sides = {r.number: match.team_of(me, r.number) for r in ordered}
    # The first round of each half is a pistol round. Found from the roster
    # rather than from a rule about round 13, which is only true for one match
    # format -- the side the player is on changing IS the swap.
    pistols, half_of, half = set(), {}, 0
    previous = None
    for r in ordered:
        if sides.get(r.number) and previous and sides[r.number] != previous:
            half += 1
            pistols.add(r.number)
        if previous is None and sides.get(r.number):
            pistols.add(r.number)
        half_of[r.number] = half
        previous = sides.get(r.number) or previous

    out: list[Round] = []
    my_score = their_score = 0
    losses = 0
    for r in ordered:
        mine = sides.get(r.number)
        if not mine:
            log.info("round %d: cannot tell which side %s was on; skipped",
                     r.number, me)
            continue
        theirs = "T" if mine == "CT" else "CT"
        won = None if not r.winner else r.winner == mine

        roster = match.teams.get(r.number, {})
        my_alive = sum(1 for s in roster.values() if s == mine) or 5
        their_alive = sum(1 for s in roster.values() if s == theirs) or 5
        in_round = sorted((k for k in match.kills if k.round == r.number),
                          key=lambda k: k.time)

        alive_me = True
        min_my_alive = my_alive
        last_stand_at = enemies_at = None
        for k in in_round:
            side = k.victim_side or (mine if _same(k.victim, me) else "")
            if side == mine:
                my_alive -= 1
                if _same(k.victim, me):
                    alive_me = False
            elif side == theirs:
                their_alive -= 1
            min_my_alive = min(min_my_alive, my_alive)
            # The last stand: the first moment I am the only one of mine left
            # and there is still someone to beat. Counted, not inferred -- the
            # pixel path has to check that the player is not merely spectating
            # the last team-mate alive, and here that cannot happen.
            if (last_stand_at is None and my_alive == 1 and alive_me
                    and their_alive >= 1):
                last_stand_at = sync.to_vod(k.time)
                enemies_at = their_alive

        my_kills = [k for k in in_round if _same(k.killer, me)]
        my_deaths = [k for k in in_round if _same(k.victim, me)]
        my_assists = [k for k in in_round
                      if _same(getattr(k, "assister", ""), me)]

        before = (my_score, their_score)
        if won is True:
            my_score += 1
        elif won is False:
            their_score += 1

        out.append(Round(
            number=r.number,
            # `opens_at` is the freeze END, not round_start: freeze time is the
            # buy menu, and a clip allowed to open there opens on twenty
            # seconds of standing still.
            started=sync.to_vod(r.opens_at),
            ended=sync.to_vod(r.end or r.opens_at),
            score_before=before, score_after=(my_score, their_score),
            half=half_of.get(r.number, 0), my_side=mine, won=won,
            my_kills=len(my_kills), my_assists=len(my_assists),
            my_deaths=len(my_deaths),
            kill_times=[sync.to_vod(k.time) for k in my_kills],
            total_kills=len(in_round), min_my_alive=min_my_alive,
            last_stand_at=last_stand_at, enemies_at_last_stand=enemies_at,
            source="demo", reason=getattr(r, "reason", "") or "",
            flags=_flags(my_kills),
            headshots=sum(1 for k in my_kills if k.headshot),
            opening_kill=bool(in_round and _same(in_round[0].killer, me)),
            pistol=r.number in pistols,
            match_point=(getattr(match, "match_point", None) == r.number),
            broke_streak=losses if won else 0))
        # Only a round the demo says was LOST extends a slide. A round whose
        # winner could not be read is not evidence of anything, and counting it
        # would invent a streak-breaker out of a gap in the data.
        if won is True:
            losses = 0
        elif won is False:
            losses += 1

    label(out)
    log.info("%d round(s) from %s: %d-%d, %d worth cutting",
             len(out), getattr(match.path, "name", "the demo"),
             my_score, their_score, len(highlights(out)))
    return out


def analyse(readings: Sequence[Reading], events) -> list[Round]:
    """readings + kill feed -> labelled rounds. The whole pipeline."""
    rounds = label(annotate(segment(readings), readings, events))
    log.info("%d of %d round(s) earned a label", len(highlights(rounds)),
             len(rounds))
    return rounds
