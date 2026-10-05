r"""A Counter-Strike match as one video, with the dead time taken out.

WHAT THIS IS FOR
    A clip is thirty seconds around a fight. A match summary is the other
    thing people upload: the whole match, in order, with the buy time, the
    walking and the twenty seconds of nothing between rounds cut out. Marvel
    Rivals has had one since `clips/summary.py`; Counter-Strike has the better
    source material for it and had none.

WHY COUNTER-STRIKE AND NOT VALORANT FIRST
    Ground truth. `rounds.from_demo()` gives exact round starts, ends, scores
    and labels out of the `.dem` -- not read off a screen and not inferred.
    Everything below is arithmetic over those numbers, which is why it can be
    proved without a single frame of footage.

WHAT IS AND IS NOT DECIDED HERE
    Which seconds to keep, and what to call each chapter. The cutting itself
    is `cutter.master_segments`, which the Rivals summary already uses and
    which is proved against real files there -- this adds no new way to touch
    ffmpeg, on purpose.

THE JOIN IS NOT A CUT PER ROUND
    Rounds that nearly touch are kept as one span. A hard cut every round in a
    match that ran without a break between them is twenty-four joins where the
    footage was already continuous, and each one costs a keyframe and shows.
"""
from __future__ import annotations

import logging

log = logging.getLogger("autostream.clips.match_summary")

# Before a round's recorded start and after its end. The round clock starts
# after the buy, so a little lead catches the walk out of spawn; the tail
# catches the last kill's aftermath and the round-end banner.
PRE = 6.0
POST = 5.0

# Two spans closer than this are one span. Deliberately larger than PRE+POST
# so that back-to-back rounds do not produce a join of a second and a half.
MERGE_GAP = 12.0

# A round shorter than this is a reading error rather than a round. Read from
# a demo they never are; read off a scoreboard, a misread digit can start and
# end one in the same second -- and padding that by PRE and POST gives an
# eleven-second span and a "Round 7" chapter for a round that did not happen.
MIN_ROUND = 5.0

# YouTube's rules, as in clips/montage.py: the first at 0:00, at least three,
# each at least ten seconds. Break one and it shows none of them.
CHAPTER_MIN = 10.0
CHAPTER_LEAST = 3


def spans(rounds, *, pre: float = PRE, post: float = POST,
          gap: float = MERGE_GAP,
          source_duration: float | None = None) -> list[tuple[float, float]]:
    """-> the stretches of recording to keep, in order, non-overlapping.

    Ordered by time, NOT by how good the round was. A summary is the match as
    it happened; ranking belongs to clips, where the viewer is choosing one.
    """
    out: list[list[float]] = []
    for r in sorted(rounds, key=lambda x: float(getattr(x, "started", 0.0))):
        try:
            started, ended = float(r.started), float(r.ended)
        except (TypeError, ValueError):
            continue
        if ended - started < MIN_ROUND:
            log.info("round %s lasted %.1fs; not a round, leaving it out",
                     getattr(r, "number", "?"), max(0.0, ended - started))
            continue
        a, b = started - pre, ended + post
        if b <= a:
            continue
        a = max(0.0, a)
        if source_duration:
            b = min(b, float(source_duration))
        if b <= a:
            continue
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def to_output(spans_: list[tuple[float, float]], t: float) -> float | None:
    """Where a moment in the RECORDING lands in the finished video.

    -> None when it was cut out, which is a real answer: a chapter for a
    moment that is not in the video points at whatever happens to be there.
    """
    acc = 0.0
    for a, b in spans_:
        if a <= t <= b:
            return acc + (t - a)
        acc += b - a
    return None


def total(spans_: list[tuple[float, float]]) -> float:
    return sum(b - a for a, b in spans_)


def label_for(r) -> str:
    """What one round is called in the chapter list.

    THE SCORE IS THE POINT. Watching a match back, the question at every
    chapter is "where were we" -- so the score after the round leads, and what
    the round earned follows it when there is something to say.
    """
    n = int(getattr(r, "number", 0) or 0)
    head = f"Round {n}" if n else "Round"
    after = getattr(r, "score_after", None)
    if isinstance(after, (tuple, list)) and len(after) == 2:
        try:
            head += f"  {int(after[0])}-{int(after[1])}"
        except (TypeError, ValueError):
            pass
    marks = [str(x).replace("_", " ").title()
             for x in (getattr(r, "labels", None) or [])]
    if marks:
        return f"{head} - {', '.join(marks)}"
    kills = int(getattr(r, "my_kills", 0) or 0)
    if kills >= 2:
        return f"{head} - {kills} kills"
    return head


def chapters(rounds, spans_: list[tuple[float, float]]
             ) -> list[tuple[float, str]]:
    """-> [(seconds into the finished video, label)].

    The same three rules as every other chapter list in this package, and the
    same reason: YouTube shows NONE of them if one is broken, with no error
    anywhere. Spacing is fixed by dropping rather than by moving, because a
    chapter moved to satisfy a rule points at the wrong round.
    """
    if not spans_:
        return []
    marks: list[tuple[float, str]] = []
    for r in sorted(rounds, key=lambda x: float(getattr(x, "started", 0.0))):
        at = to_output(spans_, float(getattr(r, "started", 0.0)))
        if at is None:
            continue
        marks.append((at, label_for(r)))
    if not marks:
        return []

    # The first must be at 0:00. The first round's span starts `PRE` before it,
    # so its mark is a few seconds in -- moved to zero rather than dropped,
    # because those few seconds are that round's own run-up and belong to it.
    marks[0] = (0.0, marks[0][1])

    end = total(spans_)
    out: list[tuple[float, str]] = []
    for t, name in marks:
        if out and t - out[-1][0] < CHAPTER_MIN:
            continue
        if end - t < CHAPTER_MIN:
            continue
        out.append((t, name))
    return out if len(out) >= CHAPTER_LEAST else []


def describe(rounds, spans_: list[tuple[float, float]]) -> dict:
    """The numbers a title and a description are written from."""
    rs = list(rounds)
    won = sum(1 for r in rs if getattr(r, "won", None) is True)
    lost = sum(1 for r in rs if getattr(r, "won", None) is False)
    kills = sum(int(getattr(r, "my_kills", 0) or 0) for r in rs)
    deaths = sum(int(getattr(r, "my_deaths", 0) or 0) for r in rs)
    kept = total(spans_)
    covered = (rs and (max(float(r.ended) for r in rs)
                       - min(float(r.started) for r in rs))) or 0.0
    return {
        "rounds": len(rs),
        "won": won,
        "lost": lost,
        "kills": kills,
        "deaths": deaths,
        "duration": round(kept, 1),
        # How much of the match's own span survived. A summary that keeps
        # everything has cut nothing, which is worth noticing rather than
        # presenting as a summary.
        "kept_fraction": round(kept / covered, 3) if covered > 0 else 0.0,
    }


def title(game: str, rounds, when: str = "") -> str:
    """A title that says the result, because that is what a thumbnail cannot.

    RESULT FIRST, and no invented drama. The score is the fact; "INSANE
    COMEBACK" is a claim nothing here can check.
    """
    rs = list(rounds)
    won = sum(1 for r in rs if getattr(r, "won", None) is True)
    lost = sum(1 for r in rs if getattr(r, "won", None) is False)
    head = f"{game} {won}-{lost}" if (won or lost) else f"{game} match"
    if won and lost:
        head += " - win" if won > lost else (" - loss" if lost > won else " - draw")
    return f"{head}{(' | ' + when) if when else ''}"
