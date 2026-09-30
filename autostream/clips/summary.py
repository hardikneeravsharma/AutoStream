"""Cut a recording's Marvel Rivals matches into videos, from clips/rivals.py's plan.

Two videos per match, each optional:

  summary    the whole match in order with the dead time out, every audio
             track kept, YouTube chapters beside it
  highlight  only the fights, themed -- see clips/highlight.py

One file per match, not one per session. A recording routinely holds two or
three matches with menus between them, and both kinds of video are about ONE
match -- the thing the uploads they are modelled on are.

The summary cut is cutter.master_segments: every span encoded on its own and
joined by the concat demuxer, with ALL audio tracks kept. That matters more
here than anywhere: a summary is minutes of the player's own voice over the
game, and the isolated mic and game tracks are what let it be rebalanced
afterwards.

WHAT THE WORK COSTS, so the page can say how long is left rather than
counting matches. Measured on the machine this was built on (NVENC, 1080p60
sources): a summary is cut at 4.4 seconds of video per second of work -- 10m04s
in 137 s -- and a highlight rendered at 2.4 -- 5m01s in 123 s, 3m56s in 95 s --
plus a few seconds for the outro and the final join. `plan()` turns those
into a cost per video; the job reports progress in them, so a match that is
twice as long counts twice.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import cutter, highlight, rivals
from .detect import Cancelled
from .plan import slug
from .tools import hms, stamp

log = logging.getLogger("autostream.clips.summary")

SUMMARY_SPEED = 4.4
HIGHLIGHT_SPEED = 2.4
HIGHLIGHT_FIXED = 8.0


def chapter_text(marks: list[tuple[float, str]]) -> str:
    """YouTube's format: one "m:ss Title" a line, the first at 0:00."""
    lines = []
    for t, name in marks:
        s = int(t)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        at = f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
        lines.append(f"{at} {name}")
    return "\n".join(lines) + "\n"


def title(game: str, m: rivals.Match, index: int, count: int) -> str:
    what = m.result.capitalize() if m.result else "Match"
    if count > 1:
        return f"{game} — {what} (match {index} of {count})"
    return f"{game} — {what}"


def describe(r: rivals.Readings, m: rivals.Match,
             spans: list[tuple[float, float]]) -> dict:
    kept = sum(b - a for a, b in spans)
    return {
        "start": round(m.start, 2), "end": round(m.end, 2),
        "match_seconds": round(m.seconds, 1),
        "duration": round(kept, 2),
        "cut_seconds": round(max(0.0, m.seconds - kept), 1),
        "deaths": len(m.deaths), "ults": len(m.casts), "kills": len(m.kills),
        "kos": len(highlight.kos(m)),
        "frozen_seconds": round(sum(b - a for a, b in m.frozen), 1),
        "phases": len(m.phases) + 1,
        "result": m.result,
        "spans": [[round(a, 2), round(b, 2)] for a, b in spans],
    }


@dataclass
class Job:
    """One video to make: what, from which match, and what it costs."""
    kind: str                       # summary | highlight
    index: int                      # the match, from 1
    match: rivals.Match
    spans: list = field(default_factory=list)      # summary: recording spans
    shots: list = field(default_factory=list)      # highlight: highlight.Shot
    seconds: float = 0.0            # how long the video will be
    cost: float = 0.0               # estimated seconds of work


def plan(r: rivals.Readings, ms: list[rivals.Match], *, summaries: bool = True,
         highlights: bool = True) -> list[Job]:
    jobs: list[Job] = []
    for i, m in enumerate(ms, start=1):
        if summaries:
            spans = rivals.plan(r, m)
            kept = sum(b - a for a, b in spans)
            jobs.append(Job("summary", i, m, spans=spans, seconds=kept,
                            cost=kept / SUMMARY_SPEED))
        if highlights:
            shots = highlight.plan(r, m)
            if shots:
                secs = sum(s.seconds for s in shots) - highlight.T * (len(shots) - 1)
                jobs.append(Job("highlight", i, m, shots=shots, seconds=secs,
                                cost=secs / HIGHLIGHT_SPEED + HIGHLIGHT_FIXED))
    return jobs


def _name(game: str, day: str, i: int, m: rivals.Match, what: str, secs: float) -> str:
    return "_".join(x for x in (
        slug(game), day, f"match{i}", m.result or "", what,
        f"{int(secs // 60)}m{int(secs % 60):02d}s") if x)


def build(source: Path, r: rivals.Readings, outdir: Path, *, game: str,
          when: float | None = None, encoder: str = "auto",
          summaries: bool = True, highlights: bool = True,
          outro: str | Path | None = None,
          progress: Callable[[dict], None] | None = None,
          check: Callable[[], None] | None = None) -> list[dict]:
    """Make every video the readings call for. -> one result row per video.

    `progress` gets a dict before each video -- which one, and the cost done
    and to do -- and once more at the end. A highlight that fails is reported
    in its row and the run goes on: the summary beside it is already made,
    and losing it to an effect that would not render helps nobody.
    """
    ms = rivals.matches(r)
    day = datetime.fromtimestamp(when or datetime.now().timestamp()).strftime("%Y-%m-%d")
    todo = plan(r, ms, summaries=summaries, highlights=highlights)
    total = sum(j.cost for j in todo) or 1.0
    done = 0.0
    out: list[dict] = []
    for j in todo:
        if check:
            check()
        m, i = j.match, j.index
        head = title(game, m, i, len(ms))
        if progress:
            progress({"kind": j.kind, "match": i, "matches": len(ms),
                      "cost": j.cost, "done": done, "total": total,
                      "seconds": j.seconds, "match_seconds": m.seconds})
        base = {"match": i, "matches": len(ms), "result": m.result,
                "start": round(m.start, 2), "end": round(m.end, 2),
                "at": stamp(m.start), "rank": i, "vertical": None,
                "kos": len(highlight.kos(m)), "ults": len(m.casts),
                "deaths": len(m.deaths), "match_seconds": round(m.seconds, 1)}
        if j.kind == "summary":
            about = describe(r, m, j.spans)
            name = _name(game, day, i, m, "summary", about["duration"])
            master = cutter.master_segments(source, j.spans, name, outdir,
                                            encoder=encoder)
            marks = rivals.chapters(j.spans, m)
            text = chapter_text(marks)
            chapters = master.with_suffix(".chapters.txt")
            chapters.write_text(text, encoding="utf-8")
            master.with_suffix(".json").write_text(json.dumps({
                "title": head, **about,
                "chapters": [[round(t, 2), n] for t, n in marks],
                "deaths_at": [[round(a, 2), round(b, 2)] for a, b in m.deaths],
                "ults_at": [round(c, 2) for c in m.casts],
                "kills_at": [round(k, 2) for k in m.kills],
                "kos_at": [round(k, 2) for k in m.kos],
                "frozen": [[round(a, 2), round(b, 2)] for a, b in m.frozen],
                "source": str(source),
            }, indent=2), encoding="utf-8")
            log.info("summary %d/%d: %s -> %s (%d spans, %d deaths, %d ults, %s)",
                     i, len(ms), hms(m.seconds), hms(about["duration"]),
                     len(j.spans), len(m.deaths), len(m.casts),
                     m.result or "no result")
            out.append({**about, **base, "kind": "summary", "name": name,
                        "caption": head, "master": str(master),
                        "chapters": str(chapters), "chapters_text": text,
                        "chapter_marks": [[round(t, 2), n] for t, n in marks]})
        else:
            name = _name(game, day, i, m, "highlight", j.seconds)
            row = {**base, "kind": "highlight", "name": name,
                   "caption": f"{head} — highlight", "kills": len(highlight.kos(m)),
                   "duration": round(j.seconds, 2), "cut_seconds": 0.0,
                   "outro": bool(outro and Path(outro).is_file())}
            try:
                hl = highlight.render(
                    source, j.shots, m, outdir / f"{name}.mp4",
                    title=game.upper(), subtitle=highlight.subtitle_for(m),
                    encoder=encoder, outro=outro or None, check=check)
                row["master"] = str(hl)
                try:
                    from .tools import media_info
                    row["duration"] = round(float(media_info(hl)["duration"]), 2)
                except Exception:                              # noqa: BLE001
                    pass
            except Cancelled:
                raise
            except Exception as e:                             # noqa: BLE001
                log.exception("the highlight of match %d failed", i)
                row.update(master="", error=str(e)[:300])
            out.append(row)
        done += j.cost
    if progress:
        progress({"kind": "done", "match": len(ms), "matches": len(ms), "cost": 0.0,
                  "done": total, "total": total, "seconds": 0.0, "match_seconds": 0.0})
    return out


def overview(rows: list[dict[str, Any]]) -> dict:
    """What a run made, in the numbers the page shows."""
    summaries = [x for x in rows if x.get("kind") == "summary"]
    highlights = [x for x in rows if x.get("kind") == "highlight"]
    per_match: dict[int, dict] = {}
    for x in rows:
        per_match.setdefault(int(x.get("match") or 0), x)
    return {
        "matches": len(per_match),
        "videos": sum(1 for x in rows if x.get("master")),
        "summaries": sum(1 for x in summaries if x.get("master")),
        "highlights": sum(1 for x in highlights if x.get("master")),
        "failed": sum(1 for x in rows if x.get("error")),
        "kos": sum(int(x.get("kos") or 0) for x in per_match.values()),
        "ults": sum(int(x.get("ults") or 0) for x in per_match.values()),
        "deaths": sum(int(x.get("deaths") or 0) for x in per_match.values()),
        "wins": sum(1 for x in per_match.values() if x.get("result") == "victory"),
        "cut_seconds": round(sum(float(x.get("cut_seconds") or 0) for x in summaries), 1),
        "match_seconds": round(sum(float(x.get("match_seconds") or 0)
                                   for x in per_match.values()), 1),
    }
