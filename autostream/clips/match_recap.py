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


class Moment:
    """One stretch of the recording, and what to call it."""

    __slots__ = ("start", "end", "name", "kills", "round", "match", "score")

    def __init__(self, start: float, end: float, *, name: str,
                 kills: list[float], rd=None, match: str = "", score: float = 0.0):
        self.start = float(start)
        self.end = float(end)
        self.name = name
        self.kills = list(kills)
        self.round = rd
        self.match = match
        self.score = float(score)

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
        return best.title() if best.isupper() else best
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
            match_of=None) -> list[Moment]:
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
    """
    pool: list[Moment] = []
    for rd in sorted(round_list, key=lambda r: float(getattr(r, "started", 0.0))):
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
    if not pool:
        return []

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
    return _tidy(keep)


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
    for m, off in zip(ms, offsets):
        name = m.name or ""
        if m.match:
            name = f"{m.match} - {name}" if name else m.match
        if not name:
            continue
        if marks and off - marks[-1][0] < 10.0:
            continue
        marks.append((round(off, 2), name))
    if not marks:
        return []
    if marks[0][0] > 0.0:
        marks.insert(0, (0.0, "Intro"))
    return marks if len(marks) >= 3 else []


def title_of(game: str, round_list, *, when: str = "") -> tuple[str, str]:
    """-> (title, subtitle) for the card over the opening shot."""
    kills = sum(int(getattr(r, "my_kills", 0) or 0) for r in round_list)
    won = sum(1 for r in round_list if getattr(r, "won", None) is True)
    lost = sum(1 for r in round_list if getattr(r, "won", None) is False)
    head = (game or "Match").upper()
    bits = []
    if won or lost:
        bits.append(f"{won}-{lost}")
    if kills:
        bits.append(f"{kills} KILL{'' if kills == 1 else 'S'}")
    sub = "  -  ".join(bits) if bits else (when or "")
    return head, sub
