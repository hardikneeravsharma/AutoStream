"""Turn the log's worst lines into a sentence a stranger can act on.

WHY THIS EXISTS
    The Logs page was a raw tail of the daemon log: accurate, and useless to
    anyone who did not write it. 'OBS is not answering: [WinError 10061]'
    means "open OBS and switch its WebSocket server on", and only one of
    those two sentences tells the reader what to do. The redesign
    (docs/superpowers/specs/2026-10-29-ui-redesign-design.md) puts the
    explained problems above the log, each with the button that fixes it.

HOW A RULE IS WRITTEN
    `match` is a regex against the MESSAGE the app itself writes, so each rule
    names the module that writes it; tests/test_logexplain.py feeds the real
    format strings, and a reworded message fails there rather than going
    quietly unexplained. `fix.act` is what the page does: `setting:<path>`
    opens that one setting, `page:<id>` goes to a page.
"""
from __future__ import annotations

import re

PROBLEMS: list[dict] = [
    {   # engine.py, the OBS poll
        "match": r"OBS is not answering",
        "say": "OBS isn't answering. Check that it is open and that its WebSocket "
               "server is on (in OBS: Tools, WebSocket Server Settings).",
        "fix": {"label": "OBS settings", "act": "setting:obs.path"},
    },
    {   # youtube.py and every caller that hits the daily limit
        "match": r"quotaExceeded|quota (?:is )?exceeded",
        "say": "Today's YouTube API budget ran out. It resets at midnight Pacific; "
               "until then titles, thumbnails and chat can't change.",
        "fix": None,
    },
    {   # engine.py, the disk watch (both the warning and the stop)
        "match": r"GB free on the recording drive|not recording: \d+ GB free",
        "say": "The recording drive is nearly full. Free some space or record "
               "somewhere else.",
        "fix": {"label": "Change folder", "act": "setting:record.directory"},
    },
    {   # clips/jobs.py, a clip job with no ffmpeg
        "match": r"ffmpeg not found|ffmpeg (?:is )?not installed",
        "say": "ffmpeg isn't installed, so clips can't be cut.",
        "fix": {"label": "Install tools", "act": "page:clips"},
    },
    {   # youtube.py, the stored sign-in
        "match": r"token refresh failed|token\.json unreadable",
        "say": "The YouTube sign-in has expired. Sign in again to go live.",
        "fix": {"label": "Sign in", "act": "setting:youtube.platform"},
    },
]

_COMPILED = [(re.compile(p["match"], re.I), p) for p in PROBLEMS]


def explain(message: str) -> dict | None:
    """-> {say, fix} for a message one of the rules knows, else None."""
    text = str(message or "")
    for rx, p in _COMPILED:
        if rx.search(text):
            return {"say": p["say"], "fix": dict(p["fix"]) if p["fix"] else None}
    return None


def problems(lines: list[dict]) -> list[dict]:
    """The explained warnings and errors in a tail, newest first, each said once.

    `lines` are webui.parse_log_line() rows, oldest first. INFO lines are
    left out even when they match: a problem the app recovered from by itself
    is history, not something to act on.
    """
    out: list[dict] = []
    said: set[str] = set()
    for row in reversed(lines or []):
        if str(row.get("level") or "").upper() not in ("WARNING", "ERROR", "CRITICAL"):
            continue
        hit = explain(row.get("msg") or "")
        if hit and hit["say"] not in said:
            said.add(hit["say"])
            out.append(dict(hit, ts=row.get("ts"), line=row.get("msg")))
    return out
