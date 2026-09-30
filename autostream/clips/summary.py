"""Cut match summaries out of a recording, from the plan clips/rivals.py makes.

One file per match, not one per session. A recording routinely holds two or
three matches with menus between them, and a summary is a video of ONE match --
the thing the uploads it is modelled on are. Each gets its YouTube chapters
beside it as text, ready to paste into a description.

The cut itself is cutter.master_segments: every span encoded on its own and
joined by the concat demuxer, with ALL audio tracks kept. That matters more
here than anywhere: a summary is minutes of the player's own voice over the
game, and the isolated mic and game tracks are what let it be rebalanced
afterwards.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import cutter, highlight, rivals
from .plan import slug
from .tools import hms, stamp

log = logging.getLogger("autostream.clips.summary")


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
        "kos": len(m.kos),
        "frozen_seconds": round(sum(b - a for a, b in m.frozen), 1),
        "phases": len(m.phases) + 1,
        "result": m.result,
        "spans": [[round(a, 2), round(b, 2)] for a, b in spans],
    }


def build(source: Path, r: rivals.Readings, outdir: Path, *, game: str,
          when: float | None = None, encoder: str = "auto",
          highlights: bool = True, outro: str | Path | None = None,
          progress: Callable[[int, int, str], None] | None = None,
          check: Callable[[], None] | None = None) -> list[dict]:
    """Cut every match the readings contain. -> one result dict per match."""
    ms = rivals.matches(r)
    day = datetime.fromtimestamp(when or datetime.now().timestamp()).strftime("%Y-%m-%d")
    out: list[dict] = []
    for i, m in enumerate(ms, start=1):
        if check:
            check()
        spans = rivals.plan(r, m)
        about = describe(r, m, spans)
        name = "_".join(x for x in (
            slug(game), day, f"match{i}", m.result or "",
            f"{int(about['duration'] // 60)}m{int(about['duration'] % 60):02d}s") if x)
        if progress:
            progress(i - 1, len(ms), f"Cutting match {i} of {len(ms)} "
                                     f"({hms(about['duration'])} of {hms(m.seconds)})")
        master = cutter.master_segments(source, spans, name, outdir,
                                        encoder=encoder)
        marks = rivals.chapters(spans, m)
        chapters = master.with_suffix(".chapters.txt")
        chapters.write_text(chapter_text(marks), encoding="utf-8")
        head = title(game, m, i, len(ms))
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
                 len(spans), len(m.deaths), len(m.casts), m.result or "no result")
        out.append({
            **about,
            "rank": i,
            "name": name,
            "at": stamp(m.start),
            "caption": head,
            "master": str(master),
            "vertical": None,
            "chapters": str(chapters),
        })
        if not highlights:
            continue
        # The highlight: the same match, only its fights, with the theme on.
        shots = highlight.plan(r, m)
        if not shots:
            log.info("match %d: no fights to make a highlight of", i)
            continue
        if progress:
            progress(i - 1, len(ms), f"Making the highlight of match {i} of {len(ms)}")
        hl = highlight.render(
            source, shots, m, outdir / f"{name}_highlight.mp4",
            title=game.upper(), subtitle=highlight.subtitle_for(m), encoder=encoder,
            outro=outro or None, check=check)
        hl_seconds = sum(s.seconds for s in shots) - highlight.T * (len(shots) - 1)
        out.append({
            "kind": "highlight", "rank": i, "name": hl.stem,
            "at": stamp(m.start), "start": round(m.start, 2), "end": round(m.end, 2),
            "duration": round(hl_seconds, 2),
            "caption": f"{head} — highlights", "kills": len(highlight.kos(m)),
            "ults": len(m.casts), "deaths": 0, "cut_seconds": 0.0,
            "master": str(hl), "vertical": None,
        })
    if progress:
        progress(len(ms), max(1, len(ms)), "Done")
    return out
