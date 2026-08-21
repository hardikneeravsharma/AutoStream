"""Turn a list of kill timestamps into a list of clips worth cutting.

THREE DECISIONS LIVE HERE

1. WHERE ONE FIGHT ENDS AND THE NEXT BEGINS
   Kills arrive as individual timestamps. A fight is a run of them close
   together, so anything within CLUSTER_GAP of the previous kill joins the same
   burst. 22 seconds was measured against a real two-hour session: it produced
   88 distinct moments from 219 kills, which matches how the session actually
   played. Shorter and single fights split in two; longer and separate
   engagements merge.

2. WHICH PART OF A FIGHT TO KEEP
   A burst can be far longer than the clip you want -- the longest in that
   session ran 15 kills over 166 seconds. Truncating at the front would open
   mid-fight and cut the ending, so instead a window of the requested length is
   slid across the burst and the position holding the most kills wins. The
   count that ends up in the filename is then the count actually inside the
   clip, not the count in the fight it came from.

3. WHAT TO CALL IT
   Clips get dragged into editors and uploaded, and the folder they came from
   is lost the moment they are. So the game, the rank, the kill count, where it
   sat in the source, and how long it runs all live in the filename itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .tools import duration_label, hms, stamp

# Kills closer together than this belong to the same fight.
CLUSTER_GAP = 22.0

# Trailing room after the last kill in a burst, for "whole moment" clips. Short
# on purpose: the payoff has already happened and dead air reads as padding.
POST_ROLL = 4.0

# Guaranteed room after the last kill, measured from when its marker LEAVES the
# screen rather than when it appeared. Below this a clip cuts while the kill
# feed is still running, which reads as a mistake even when the kill itself is
# fully in shot.
TAIL_MIN = 2.0

MIN_CLIP = 4.0

# Named timing styles: pre-roll, tail, clip length.
#
# The numbers come from how gaming clips are actually cut, not from taste. The
# consistent advice is to trim to ONE OR TWO seconds before the peak and about
# two after -- roughly 1:1 -- because 50-60% of viewers who leave a short do so
# inside the first three seconds, and a clip that opens on run-up spends its
# whole hook budget on nothing happening. Dead air at the END is what stops a
# short looping, which is the cheapest retention there is.
#
# AutoStream's original default was 6s of run-up against a 2s tail: 3:1, with
# the weight on precisely the wrong end.
#
# "Montage cut" is tighter again because a clip inside a montage is advised at
# 3-8 seconds -- it only has to carry the kill, the montage carries the pacing.
STYLES: dict[str, dict] = {
    "shortform": {
        "label": "Short-form",
        "pre_roll": 1.5, "tail": 2.0, "clip_seconds": "15",
        "blurb": "Opens on the action. Sized for Shorts and Reels.",
    },
    "montage": {
        "label": "Montage cut",
        "pre_roll": 1.0, "tail": 1.5, "clip_seconds": "6",
        "blurb": "Short enough to cut together without dragging.",
    },
    "context": {
        "label": "Full context",
        "pre_roll": 6.0, "tail": 4.0, "clip_seconds": "30",
        "blurb": "Keeps the run-up. Better for watching back than posting.",
    },
}

DEFAULT_STYLE = "shortform"


def style_values(style: str | None, fallback: dict | None = None) -> dict:
    """-> {pre_roll, tail, clip_seconds} for a style name.

    "custom" (or anything unknown) returns the caller's own values untouched,
    so the individual settings stay authoritative when no style is chosen.
    """
    base = dict(fallback or {})
    s = STYLES.get(str(style or "").lower())
    if not s:
        return base
    base.update({k: s[k] for k in ("pre_roll", "tail", "clip_seconds")})
    return base


def style_listing() -> list[dict]:
    """For the UI: every style with the numbers it applies, so the trade-off is
    visible rather than hidden behind a name."""
    out = [{"id": k, **{f: v[f] for f in ("label", "blurb", "pre_roll", "tail",
                                          "clip_seconds")}}
           for k, v in STYLES.items()]
    out.append({"id": "custom", "label": "Custom", "blurb": "Use the settings below.",
                "pre_roll": None, "tail": None, "clip_seconds": None})
    return out


@dataclass
class Burst:
    start: float                      # first kill
    end: float                        # last kill
    times: list[float] = field(default_factory=list)
    skulls: int = 0                   # markers seen, >= len(times) in multikills
    # Per-kill "marker gone" times, index-aligned with `times`. A clip has to
    # clear these, not `times` -- see TAIL_MIN.
    offs: list[float] = field(default_factory=list)

    @property
    def kills(self) -> int:
        return len(self.times)

    @property
    def span(self) -> float:
        return self.end - self.start

    def off_at(self, t: float) -> float:
        """When the marker for the kill recorded at `t` left the screen."""
        for a, b in zip(self.times, self.offs):
            if a == t:
                return max(a, b)
        return t


@dataclass
class ClipPlan:
    rank: int
    start: float
    end: float
    kills: int
    burst_kills: int                  # how many the whole fight had
    peak_score: float
    name: str                         # filename stem, no extension
    # Round clips only: what the round earned, and its context. Empty for
    # burst clips, so nothing downstream has to know which mode made it.
    labels: list[str] = field(default_factory=list)
    round_number: int | None = None
    won: bool | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start

    def describe(self) -> str:
        extra = "" if self.kills == self.burst_kills else f" of {self.burst_kills}"
        return (f"{hms(self.start)}  {self.duration:4.1f}s  "
                f"{self.kills} kill{'s' if self.kills != 1 else ''}{extra}")

    def as_dict(self) -> dict:
        return {
            "rank": self.rank, "start": round(self.start, 2),
            "end": round(self.end, 2), "duration": round(self.duration, 2),
            "kills": self.kills, "burst_kills": self.burst_kills,
            "score": round(self.peak_score, 3), "name": self.name,
            "at": stamp(self.start),
            **({"labels": list(self.labels)} if self.labels else {}),
            **({"round": self.round_number} if self.round_number else {}),
            **({"won": self.won} if self.won is not None else {}),
        }


def slug(s: str) -> str:
    """A filename-safe, human-readable token. CamelCase words survive."""
    s = re.sub(r"[^\w\s-]", "", str(s or "")).strip()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:40] or "Game"


def cluster(kills, gap: float = CLUSTER_GAP) -> list[Burst]:
    """Group kill events into fights. `kills` may be Kill objects or dicts."""
    out: list[Burst] = []
    for k in sorted(kills, key=lambda k: _t(k)):
        t, c, s, off = _t(k), _count(k), _score(k), _off(k)
        if out and t - out[-1].end <= gap:
            b = out[-1]
            b.end = t
            b.times.append(t)
            b.offs.append(off)
            b.skulls += c
            b.peak = max(getattr(b, "peak", 0.0), s)
        else:
            b = Burst(start=t, end=t, times=[t], offs=[off], skulls=c)
            b.peak = s                                   # type: ignore[attr-defined]
            out.append(b)
    return out


def _t(k) -> float:
    return float(k["time"] if isinstance(k, dict) else k.time)


def _off(k) -> float:
    """When the marker left the screen. Falls back to the appearance time for
    kills recorded before detect.py started tracking it."""
    v = k.get("end") if isinstance(k, dict) else getattr(k, "end", None)
    return max(_t(k), float(v)) if v else _t(k)


def _count(k) -> int:
    return int(k.get("count", 1) if isinstance(k, dict) else getattr(k, "count", 1))


def _score(k) -> float:
    return float(k.get("score", 0.0) if isinstance(k, dict) else getattr(k, "score", 0.0))


def _best_window(burst: Burst, length: float, pre: float,
                 tail: float) -> tuple[float, float, int]:
    """Choose a window of `length` over a fight; -> (start, end, kills inside).

    Returns the END as well as the start, and the caller must use it rather
    than recomputing start + length. Near the beginning of a recording the
    start clamps to zero, and recomputing from the clamped value pushes the end
    later than the anchor intended -- which quietly pulls a following kill into
    the clip and cuts it off, the exact bug this function exists to prevent.

    ANCHORED ON THE LAST KILL, NOT THE FIRST. Anchoring the start `pre` seconds
    before a kill says nothing about where the window ENDS, so whatever landed
    near the end got sliced -- a real clip came out with its third kill 0.5s
    before the cut, feed still running.

    So instead: every kill is tried as the LAST one in the clip, the window is
    laid out to end `tail` seconds after that kill's marker clears, and any
    candidate with another kill inside that tail is rejected outright. The
    guarantee then holds by construction rather than by adjustment afterwards.

    This can return fewer kills than the old rule. Three kills spanning 8.5s do
    not fit in a 10-second clip once 2 seconds at the end are reserved, and
    pretending otherwise is what produced the clipped feed.
    """
    times = burst.times
    best: tuple[float, float, int, float] | None = None   # start, end, n, run-up
    for last in times:
        end = burst.off_at(last) + tail
        # A kill inside the reserved tail means this candidate would cut it off.
        if any(last < t <= end for t in times):
            continue
        # `length` is a CEILING, not a quota to fill. Laying the window out
        # backwards from the last kill and taking the full length meant a
        # single-kill 15-second clip opened with ELEVEN seconds of run-up --
        # the exact dead air the short-form style exists to remove, and it made
        # pre_roll decorative. So take the later of "as long as allowed" and
        # "pre_roll before the first kill", and let short clips be short.
        floor = max(0.0, end - length)
        inside = [t for t in times if floor <= t <= last]
        if not inside:
            continue
        start = max(floor, inside[0] - pre)
        # A lone kill under a tight style lands at pre + tail seconds, which can
        # fall under MIN_CLIP and get the whole moment thrown away further down.
        # Give it more run-up rather than lose it -- the tail is what must not
        # move, and `floor` still caps the total at the requested length.
        start = max(floor, min(start, end - MIN_CLIP))
        n = len(inside)                    # start <= inside[0], so none are lost
        run_up = inside[0] - start
        # Most kills wins; ties go to whichever opens with more run-up, so a
        # clip does not start on the shot already being fired.
        if best is None or (n, run_up) > (best[2], best[3]):
            best = (start, end, n, run_up)

    if best is None:
        # Every candidate was rejected -- a continuous stream of kills closer
        # together than the tail. Fall back to the last kill in the fight and
        # let the tail guarantee win over the length.
        end = burst.off_at(times[-1]) + tail
        start = max(0.0, end - length)
        return start, end, sum(1 for t in times if start <= t <= times[-1])
    return best[0], best[1], best[2]


def build(kills, *, game: str, min_kills: int = 2,
          clip_seconds: str | int = "30", pre_roll: float = 6.0,
          source_duration: float | None = None,
          gap: float = CLUSTER_GAP,
          tail: float = TAIL_MIN) -> list[ClipPlan]:
    """-> clips ranked by kill count, best first."""
    want = max(1, int(min_kills))
    # Filter on kills IN THE CLIP, not kills in the fight. A five-kill fight
    # spread over ninety seconds contributes maybe two kills to a twenty-second
    # window, and a setting called "minimum kills per clip" that yields
    # two-kill clips is simply wrong. Bursts are therefore only pre-filtered by
    # the weaker condition -- a fight cannot put more kills in a clip than it
    # contains -- and the real test happens after the window is chosen.
    bursts = [b for b in cluster(kills, gap) if b.kills >= want]
    if not bursts:
        return []

    fixed = None if str(clip_seconds).lower() in ("auto", "", "0") else float(clip_seconds)
    tag = slug(game)

    tail = max(0.0, float(tail))
    scored: list[tuple[Burst, float, float, int]] = []
    for b in bursts:
        if fixed:
            start, end, n = _best_window(b, fixed, pre_roll, tail)
        else:
            # "Whole moment" measures its tail from the last marker clearing
            # too, so the two modes cut at the same place relative to the
            # action rather than one of them being tighter by accident.
            start = b.start - pre_roll
            end = b.off_at(b.end) + max(POST_ROLL, tail)
            n = b.kills
        if n < want:
            continue
        start = max(0.0, start)
        if source_duration:
            # Truncating at the end of the recording can eat the tail, but the
            # alternative is asking ffmpeg for frames that do not exist.
            end = min(end, source_duration)
        if end - start < MIN_CLIP:
            continue
        scored.append((b, start, end, n))

    # Rank by what is in the clip, then by how long the fight was, then by
    # when it happened -- so the order is stable across reruns.
    scored.sort(key=lambda r: (-r[3], -r[0].kills, r[1]))

    plans: list[ClipPlan] = []
    for i, (b, start, end, n) in enumerate(scored, 1):
        name = (f"{tag}_{i:02d}_{n}kill{'s' if n != 1 else ''}"
                f"_{stamp(start)}_{duration_label(end - start)}")
        plans.append(ClipPlan(
            rank=i, start=start, end=end, kills=n, burst_kills=b.kills,
            peak_score=getattr(b, "peak", 0.0), name=name))
    return plans


def build_rounds(highlights, *, game: str, pre_roll: float = 3.0,
                 tail: float = 3.0, whole_round: bool = True,
                 clip_seconds: str | int = "auto",
                 source_duration: float | None = None) -> list[ClipPlan]:
    """Round highlights -> clips. A different windowing model to build().

    build() finds a burst of kills and slides a window over it. A round is not
    a burst: what makes it worth watching can be a single kill at the end of a
    1v3, and the run-up is the point rather than dead air. So a round clip is
    anchored on the ROUND, not on the kills in it.

    whole_round=True keeps the round from its first interesting moment to its
    end, which is what you want to watch back. False trims to the action, which
    is what fits in a Short -- a round runs 30-115 seconds against a 15-second
    short-form cap.
    """
    tag = slug(game)
    fixed = None if str(clip_seconds).lower() in ("auto", "", "0")         else float(clip_seconds)

    plans: list[ClipPlan] = []
    for i, rd in enumerate(highlights, 1):
        # Where the interesting part starts. A last stand is the moment the
        # round became a story; failing that, the first kill; failing that, the
        # round itself.
        anchor_at = rd.last_stand_at
        if anchor_at is None and rd.kill_times:
            anchor_at = min(rd.kill_times)
        if anchor_at is None:
            anchor_at = rd.started

        if whole_round:
            start = max(rd.started, anchor_at - pre_roll)
            end = rd.ended + tail
        else:
            length = fixed or 15.0
            # Keep the END of the round: in Counter-Strike the resolution is
            # the payoff, so a trimmed clip loses the opening, not the finish.
            end = rd.ended + tail
            start = max(rd.started, end - length)
            # ...but never open on dead air. If nothing happened until well
            # after that point, start at the action instead and let the clip
            # come out shorter than the cap.
            if anchor_at - pre_roll > start:
                start = anchor_at - pre_roll

        start = max(0.0, start)
        if source_duration:
            end = min(end, source_duration)
        if end - start < MIN_CLIP:
            continue

        label = rd.labels[0] if rd.labels else "ROUND"
        plans.append(ClipPlan(
            rank=i, start=start, end=end, kills=rd.my_kills,
            burst_kills=rd.my_kills, peak_score=0.0,
            name=(f"{tag}_{i:02d}_{slug(label)}"
                  f"_r{rd.number}_{stamp(start)}"
                  f"_{duration_label(end - start)}"),
            labels=list(rd.labels), round_number=rd.number, won=rd.won))
    return plans


def montage_name(game: str, plans: list[ClipPlan], when: str,
                 total: float) -> str:
    kills = sum(p.kills for p in plans)
    return (f"{slug(game)}_{when}_montage_{len(plans)}clips"
            f"_{kills}kills_{duration_label(total)}")


def summarise(kills, plans: list[ClipPlan]) -> dict:
    """Headline numbers for the UI, so it never has to recompute them."""
    total_kills = len(list(kills))
    covered = sum(p.kills for p in plans)
    return {
        "kills": total_kills,
        "clips": len(plans),
        "covered": covered,
        "coverage": round(100 * covered / total_kills) if total_kills else 0,
        "runtime": round(sum(p.duration for p in plans)),
    }
