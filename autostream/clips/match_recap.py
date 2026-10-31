r"""A match cut the way a highlight channel cuts one, not the way a DVR does.

WHY THIS EXISTS
    `match_summary.py` keeps the whole match and takes the dead time out. On a
    real recording that kept 83% of it: 52 minutes, no transitions, no sound
    design, no beginning and no end. It is an honest watch-through and nobody
    asked for a watch-through.

WHAT THE SHAPE IS MEASURED AGAINST
    The genre, read off the channel the request named rather than invented
    here. "15 Times Shroud Was a Beast In VALORANT" is 6m32s: an 18-second
    intro, then fourteen moments of 15 to 50 seconds, averaging 28. Three
    other VALORANT uploads on the same channel run 9:58, 10:21 and 12:04, and
    the recent long-form ones 12 to 38 minutes. So the target is MINUTES --
    not the hour a watch-through runs, and not the ninety seconds a montage
    runs either.

    And every chapter there is named for what happened -- "Insanely quick 4K",
    "3 kills with 4 bullets", "Craziest site hold ace" -- never "Round 7".
    A chapter list that reads "Round 1, Round 2, Round 3" is a table of
    contents for a file, not for a video.

WHAT IS AND IS NOT DECIDED HERE
    Which seconds to keep, in what order, and what to call each one. The
    cutting, the whips, the whooshes, the hit flashes, the title and the outro
    are `clips/highlight.py`, which has done all of that for Marvel Rivals
    since v1.30 and was only ever coupled to that game by the two lines that
    asked a `rivals.Match` for its KOs.

    Everything below is arithmetic over rounds and kill times, so it is proved
    without a frame of footage.
"""
from __future__ import annotations

import logging

from . import rounds as rounds_mod

log = logging.getLogger("autostream.clips.match_recap")

# How long the finished recap should run. Eight minutes sits inside the band
# the genre actually occupies (6:32 to 12:04 over four uploads) and leaves
# room either side, since a match that had twelve good rounds should not be
# padded to length and one that had forty should not run to half an hour.
TARGET = 480.0
# A recap of a match with almost nothing in it is still a recap. Below this
# there is no video worth making and the caller is told so.
FLOOR = 45.0

# A moment opens this long before its first kill and closes this long after
# its last. PRE is the setup -- the walk in, the utility, the swing -- which
# is the part that makes a play readable; cutting it is why so many automatic
# highlights look like a slideshow of crosshairs snapping.
PRE = 8.0
POST = 4.0
# Kills closer together than this are one moment. Further apart and they are
# two things that happened in the same round.
CLUSTER = 12.0
# Clamps, from the measured range above: 15 to 50 seconds a moment.
MOMENT_MIN = 12.0
MOMENT_MAX = 50.0

# The opening shot, taken from the start of the first round so the video
# begins in the match rather than on a kill with no context. Roughly the
# 18 seconds the reference uses.
INTRO = 16.0
INTRO_SKIP = 2.0

# ONE MATCH IS 2.5 TO 4.5 MINUTES (ChatGPT's review of the first Valorant recap,
# 2026-11-01; docs/plans/2026-11-01-match-video-and-moments.md). The eight minutes
# above was measured on compilations of many matches; for one match the job asks
# for PER_MATCH a match, so a recording of two gets twice the room.
PER_MATCH = 270.0
# A LONE KILL IS NOT A HIGHLIGHT unless something makes it one -- a label, a
# reaction. It is dropped while at least this many other moments are on offer.
LONE_KILL_SPARE = 8
# The player's reactions (clips/reactions.py) in the recap: at most this many on
# their own, each REACT_PRE before its reaction to REACT_POST after it.
REACT_MOMENTS = 3
REACT_PRE = 10.0
REACT_POST = 4.0
# The cold open: this much of the strongest moment, around its last kill -- the kill
# inside the first two seconds (ChatGPT's second review: a teaser that opens on
# walking or the buy menu fails the one job it has).
COLD_OPEN_BEFORE = 1.5
COLD_OPEN_AFTER = 3.3


class Moment:
    """One stretch of the recording, and what to call it."""

    __slots__ = ("start", "end", "name", "kills", "round", "match", "score", "reaction")

    def __init__(self, start: float, end: float, *, name: str,
                 kills: list[float], rd=None, match: str = "", score: float = 0.0,
                 reaction: bool = False):
        self.start = float(start)
        self.end = float(end)
        self.name = name
        self.kills = list(kills)
        self.round = rd
        self.match = match
        self.score = float(score)
        self.reaction = bool(reaction)    # the player reacted in it (clips/reactions.py)

    @property
    def card(self) -> str:
        """The round's context, shown for two seconds as the moment opens: the round,
        the side, the score going in, the situation. Only what the record says --
        nothing inferred is put on screen as fact."""
        rd = self.round
        if rd is None or not getattr(rd, "number", None):
            return ""
        bits = [f"Round {int(rd.number)}"]
        side = str(getattr(rd, "my_side", "") or "").strip()
        if side:
            bits.append(side.title())
        sb = getattr(rd, "score_before", None)
        if sb and (sb[0] or sb[1] or int(rd.number) > 1):
            bits.append(f"{int(sb[0])}-{int(sb[1])}")
        enemies = getattr(rd, "enemies_at_last_stand", None)
        if getattr(rd, "last_stand_at", None) is not None and enemies:
            bits.append(f"1v{int(enemies)}")
        if getattr(rd, "match_point", False):
            bits.append("Match point")
        return "  ·  ".join(bits)

    @property
    def seconds(self) -> float:
        return max(0.0, self.end - self.start)

    def __repr__(self) -> str:                             # pragma: no cover
        return f"<Moment {self.start:.1f}-{self.end:.1f} {self.name!r}>"


def _bursts(times: list[float], gap: float = CLUSTER) -> list[list[float]]:
    """Kill times grouped into fights."""
    out: list[list[float]] = []
    for t in sorted(float(t) for t in times):
        if out and t - out[-1][-1] <= gap:
            out[-1].append(t)
        else:
            out.append([t])
    return out


def tidy_label(label: str) -> str:
    """One spelling for a label, whatever case it arrived in.

    The first run against real footage produced "LAST ALIVE 1v3", "Last Alive",
    "CLUTCH 1v2" and "Flawless" in the same chapter list, because the labels
    come from three places that each shout or not as they please. A chapter
    list that cannot agree with itself about capitals looks automatic, which
    is the one thing it must not look.

    Words are capitalised; a word with a digit in it is left exactly as it is,
    so "1v3" does not become "1V3" and a map name keeps its own spelling.
    """
    out = []
    for w in str(label).split():
        out.append(w if any(c.isdigit() for c in w) else w.capitalize())
    return " ".join(out)


def name_of(rd, kills: int) -> str:
    """What to call a moment. The play, never the round number.

    The round's own labels come first because they are the rare thing -- ACE,
    a clutch, a pistol round -- and `rounds.rank_of` already decides which of
    several wins. Only when a round earned nothing is the kill count used,
    and a single kill is not called "1 kill": it is called nothing, and the
    chapter takes the round's score instead.
    """
    labels = list(getattr(rd, "labels", None) or [])
    if labels:
        best = min(labels, key=lambda l: rounds_mod.rank_of([l]))
        return tidy_label(best)
    if kills >= 5:
        return "Ace"
    if kills >= 2:
        return f"{kills}K"
    return ""


def _score(rd, kills: int) -> float:
    """How much this moment deserves its place. Bigger is better.

    Rank first, kills second. A 1v3 clutch with two kills beats a quiet round
    with three, because the label is the reason anyone clicks -- which is the
    same order `rounds.highlights` already sorts by, kept deliberately so a
    recap and the clip list do not disagree about what the good rounds were.
    """
    labels = list(getattr(rd, "labels", None) or [])
    rank = rounds_mod.rank_of(labels) if labels else len(rounds_mod.RANK)
    return (len(rounds_mod.RANK) - rank) * 10.0 + kills


def moments(round_list, *, target: float = TARGET,
            source_duration: float | None = None,
            match_of=None, reactions=()) -> list[Moment]:
    """The moments of the recap, in the order they happened. May be empty.

    `match_of(round)` -> a name for the match a round belongs to, when the
    recording holds more than one. A recording with a deathmatch and then a
    competitive game is ordinary, and so is two competitive games back to
    back: the chapters then say which, because "Round 1" appearing twice in
    one video with no explanation is worse than no chapters.

    CHOSEN BY STRENGTH, PLAYED IN ORDER. Picking the best moments and then
    showing them in the order they happened is what makes it a recap of a
    match rather than a montage: the score moves forward, the halves swap,
    and the last moment is the one the match ended on.

    `reactions` are the player's own (clips/reactions.Reaction, strongest first). One
    inside a fight makes that fight a reaction moment and outranks its like; one outside
    every fight can be a moment of its own -- a missed clutch the player lost it over is
    exactly what a kill-only recap left out (2026-11-01: the hand-cut rage meme).
    """
    rounds_sorted = sorted(round_list, key=lambda r: float(getattr(r, "started", 0.0)))
    pool: list[Moment] = []
    for rd in rounds_sorted:
        times = [float(t) for t in (getattr(rd, "kill_times", None) or [])]
        if not times:
            continue
        lo = float(getattr(rd, "started", times[0]))
        hi = float(getattr(rd, "ended", times[-1]))
        for burst in _bursts(times):
            a = max(lo - PRE, burst[0] - PRE)
            b = min(hi + POST, burst[-1] + POST)
            if b - a < MOMENT_MIN:
                # Widen rather than drop: a one-kill round is 12 seconds of
                # footage and still a round that happened.
                b = a + MOMENT_MIN
            if b - a > MOMENT_MAX:
                # Keep the END of a long fight. The kills are at the end of a
                # round far more often than the start, and a moment trimmed
                # from the back would cut the thing it was chosen for.
                a = b - MOMENT_MAX
            a = max(0.0, a)
            if source_duration:
                b = min(b, float(source_duration))
            if b - a < MOMENT_MIN:
                continue
            n = len(burst)
            pool.append(Moment(a, b, name=name_of(rd, n), kills=burst, rd=rd,
                               match=(match_of(rd) if match_of else ""),
                               score=_score(rd, n)))
    # The reactions: into the fight they happened in, else (the strongest few) on their own.
    lo_all = min((float(r.started) for r in rounds_sorted if getattr(r, "started", None) is not None),
                 default=None)
    hi_all = max((float(r.ended) for r in rounds_sorted if getattr(r, "ended", None) is not None),
                 default=None)
    alone = 0
    # ONLY THE STRONG ONES COUNT. A talkative player reacts two or three times a minute
    # (100 times in the Bind match), so every fight had one and six of eleven moments
    # came out "+ reaction" -- a label on everything says nothing. The strongest quarter
    # of the session's reactions (by score, reactions.find's order), at least three.
    given = list(reactions or ())
    strong = given[:max(REACT_MOMENTS, len(given) // 4)]
    for x in strong:
        rs, re_ = float(x.start), float(x.end)
        if lo_all is not None and not (lo_all - 5.0 <= rs <= hi_all + 5.0):
            continue                      # not in this match
        home = next((m for m in pool if m.start <= rs <= m.end + 2.0), None)
        if home is not None:
            home.reaction = True
            home.end = max(home.end, min(re_ + 2.0, home.start + MOMENT_MAX))
            home.score += REACTION_BONUS
            continue
        if alone >= REACT_MOMENTS:
            continue
        # The round it belongs to: the one it is in, else the nearest -- a reaction in the
        # buy phase is about the round that just ended (the Bind match's 1360 s one had
        # none, and so no card).
        rd = (next((r for r in rounds_sorted if float(r.started) <= rs <= float(r.ended)), None)
              or next((r for r in reversed(rounds_sorted)
                       if float(r.ended) <= rs <= float(r.ended) + 30.0), None)
              or next((r for r in rounds_sorted
                       if float(r.started) - 30.0 <= rs <= float(r.started)), None))
        a = max(0.0, rs - REACT_PRE)
        b = re_ + REACT_POST
        if source_duration:
            b = min(b, float(source_duration))
        if b - a < MOMENT_MIN:
            b = a + MOMENT_MIN
        pool.append(Moment(a, b, name="", kills=[], rd=rd,
                           match=(match_of(rd) if (match_of and rd) else ""),
                           score=REACTION_ALONE, reaction=True))
        alone += 1
    if not pool:
        return []

    # A LONE KILL IS NOT A HIGHLIGHT (see LONE_KILL_SPARE): one unnamed kill, nobody
    # reacting, goes while there is enough else to make the video from.
    lone = [m for m in pool if len(m.kills) == 1 and not m.name and not m.reaction]
    if len(pool) - len(lone) >= LONE_KILL_SPARE:
        pool = [m for m in pool if m not in lone]

    # Strongest first, and ties broken by time so the choice is deterministic.
    ranked = sorted(pool, key=lambda m: (-m.score, m.start))
    keep: list[Moment] = []
    spent = 0.0
    for m in ranked:
        if keep and spent + m.seconds > target:
            continue
        keep.append(m)
        spent += m.seconds
        if spent >= target:
            break
    keep.sort(key=lambda m: m.start)
    return _names(_tidy(keep))


# A fight the player reacted in outranks one like it they did not; a reaction on its
# own sits with an ordinary 2K (rounds.RANK steps are 10, kills 1).
REACTION_BONUS = 5.0
REACTION_ALONE = 2.5


def _names(ms: list[Moment]) -> list[Moment]:
    """Every moment named, and no name twice (ChatGPT, 2026-11-01): three moments of the
    first Valorant recap had no name and so no chapter, and "Last Alive" and "Thrifty"
    each came twice. A blank is named by its round and what is known of it; a repeat
    gets its round number.

    THE REACTION IS NAMED FOR WHAT IS KNOWN -- that the player reacted -- and not for
    what it might have been: no Rage, Laugh or Hype until a classifier can say so with
    confidence (ChatGPT's second review). "Player Reacts" for one on its own, "+ Player
    Reaction" on a fight, "Between Rounds" when it fell in the buy phase."""
    for m in ms:
        n = int(getattr(m.round, "number", 0) or 0) if m.round is not None else 0
        between = (m.reaction and not m.kills and m.round is not None
                   and not (float(m.round.started) <= m.start + REACT_PRE <= float(m.round.ended)))
        if not m.name:
            what = (f"{len(m.kills)}K" if len(m.kills) >= 2 else
                    "Player Reacts" if m.reaction else ("1 kill" if m.kills else ""))
            m.name = ("Between Rounds - Player Reaction" if between else
                      f"Round {n:02d} - {what}" if n and what else
                      f"Round {n:02d}" if n else
                      ("Player Reaction" if m.reaction else what or "Moment"))
        elif m.reaction and "reaction" not in m.name.lower():
            m.name = f"{m.name} + Player Reaction"
    seen: dict[str, int] = {}
    for m in ms:
        seen[m.name] = seen.get(m.name, 0) + 1
    for m in ms:
        if seen[m.name] > 1 and m.round is not None and getattr(m.round, "number", None):
            m.name = f"{m.name} - Round {int(m.round.number):02d}"
    # Two fights in one round can still share a name ("Last Alive - Round 07" twice in
    # the Bind match): the later ones say which, in words.
    count: dict[str, int] = {}
    for m in ms:
        count[m.name] = count.get(m.name, 0) + 1
        if count[m.name] > 1:
            m.name = f"{m.name} - {ORDINALS.get(count[m.name], str(count[m.name]) + 'th')} Moment"
    return ms


ORDINALS = {2: "Second", 3: "Third", 4: "Fourth", 5: "Fifth"}


def _tidy(ms: list[Moment]) -> list[Moment]:
    """Moments that overlap are merged; the later name wins only if it ranks
    higher. Two bursts in one round can be chosen separately and still touch
    once PRE and POST are added, and a cut from a frame to the frame beside it
    reads as a stutter."""
    out: list[Moment] = []
    for m in ms:
        if out and m.start <= out[-1].end:
            prev = out[-1]
            prev.end = max(prev.end, m.end)
            prev.kills += m.kills
            prev.reaction = prev.reaction or m.reaction
            if m.score > prev.score:
                prev.name, prev.score = m.name, m.score
            continue
        out.append(m)
    return out


def intro(round_list, *, source_duration: float | None = None) -> Moment | None:
    """The opening shot: the start of the first round, under the title.

    Not a kill. A highlight that opens on a kill has no idea what it is
    looking at yet, and the title card needs somewhere to sit that is not
    already the point.
    """
    first = min((r for r in round_list
                 if getattr(r, "started", None) is not None),
                key=lambda r: float(r.started), default=None)
    if first is None:
        return None
    a = max(0.0, float(first.started) + INTRO_SKIP)
    b = a + INTRO
    if source_duration:
        b = min(b, float(source_duration))
    if b - a < 4.0:
        return None
    return Moment(a, b, name="Intro", kills=[], rd=first)


def chapters(ms: list[Moment], durations: list[float],
             offsets: list[float]) -> list[tuple[float, str]]:
    """YouTube chapters: where each moment lands and what it is called.

    `durations` and `offsets` come from the renderer, because the transitions
    overlap the shots and only it knows by how much.

    YouTube's rules, as everywhere else in this app: the first at 0:00, at
    least three, each at least ten seconds. Break one and it shows none.
    """
    marks: list[tuple[float, str]] = []
    seen = ""
    for m, off in zip(ms, offsets):
        # THE MAP NAME IS A CHAPTER ONCE, WHERE THE MATCH CHANGES -- not on
        # every moment in it. The first run against real footage produced
        # eight chapters in a row reading "Lotus", because a moment the
        # player got one kill in has no name of its own and the match name
        # was standing in for it. Eight identical chapters are worse than
        # none: they fill the list and say nothing.
        turn = bool(m.match) and m.match != seen
        name = m.name or ""
        if turn:
            name = f"{m.match} - {name}" if name else m.match
            seen = m.match
        if not name:
            continue
        if marks and off - marks[-1][0] < 10.0:
            continue
        marks.append((round(off, 2), name))
    if not marks:
        return []
    if marks[0][0] > 0.0:
        # After a cold open the first named shot is the intro itself, a few seconds in:
        # it moves to 0:00 rather than a second "Intro" being put in front of it.
        if marks[0][1] == "Intro" and marks[0][0] < 10.0:
            marks[0] = (0.0, "Intro")
        else:
            marks.insert(0, (0.0, "Intro"))
    return marks if len(marks) >= 3 else []


def title_of(game: str, round_list, *, when: str = "",
             matches: int = 1, map_name: str = "", agent: str = "") -> tuple[str, str]:
    """-> (title, subtitle) for the card over the opening shot.

    `matches` is how many games the recording holds. With more than one there
    is no scoreline to print: adding Lotus (won 13-10) to Sunset (lost 2-13)
    gives 15-23, which is not a result either game had, and a title card is
    the worst place in the video to put a number nobody can check.
    """
    kills = sum(int(getattr(r, "my_kills", 0) or 0) for r in round_list)
    won = sum(1 for r in round_list if getattr(r, "won", None) is True)
    lost = sum(1 for r in round_list if getattr(r, "won", None) is False)
    # THE MATCH'S SCORE, NOT THE RECORDING'S. A recording that starts at round 6 holds
    # 20 of a match's 24 rounds, and counting them made an 11-13 loss read "9-11" on the
    # title (the Bind match of 2026-10-25). The last round's running score is the
    # match's own -- Riot's record tallies it over every round, seen or not.
    last = max(round_list, key=lambda r: int(getattr(r, "number", 0) or 0), default=None)
    after = getattr(last, "score_after", None) if last is not None else None
    if after and (after[0] or after[1]) and sum(after) >= won + lost:
        won, lost = int(after[0]), int(after[1])
    head = (game or "Match").upper()
    # THE MAP AND THE RESULT, IN WORDS (ChatGPT, 2026-11-01: "VALORANT Bind | 9-10
    # Loss | 16 Kills"). The first Valorant card read "VALORANT | 9-10" -- a score
    # with no place and no verdict. A loss is not hidden: a close one is the story.
    if map_name and matches <= 1:
        head = f"{head} {map_name.upper()}"
    bits = []
    if matches > 1:
        bits.append(f"{matches} MATCHES")
    elif won or lost:
        verdict = "WIN" if won > lost else "LOSS" if lost > won else "DRAW"
        bits.append(f"{won}-{lost} {verdict}")
    if kills:
        bits.append(f"{kills} KILL{'' if kills == 1 else 'S'}")
    if agent and matches <= 1:
        bits.append(agent.upper())
    sub = "  -  ".join(bits) if bits else (when or "")
    return head, sub
