"""An append-only journal of finished sessions.

WHY THIS EXISTS
    Nothing in AutoStream remembered a stream after it ended. state.json holds
    only the CURRENT session and reset_session() wipes it, so once a broadcast
    completed there was no record that it ever happened -- not the game, not
    the broadcast id, not the URL. The only trace was the rotating text log,
    which is hard-capped at seven days.

    The Clips page needs exactly that missing answer: which game was played,
    on which broadcast, and where is the recording. So it gets written here.

WHY JSONL AND NOT SQLITE
    One line per session, appended, never updated in place. A few hundred rows
    a year does not need a database, and a plain text file survives a partial
    write with the loss of one line instead of the loss of the file. read()
    skips lines that do not parse rather than raising, which is the whole point
    of the format.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger("autostream.history")

# Read guard. Every line is loaded into memory to render the Clips page, and a
# corrupt or adversarially large file should not be able to hang the UI.
MAX_LINES = 5000


def _clean(entry: dict) -> dict:
    """Drop Nones so the file stays readable when opened by a human."""
    return {k: v for k, v in entry.items() if v is not None}


def append(entry: dict[str, Any]) -> None:
    """Add one finished session. Never raises -- journalling must not be able
    to break the end of a stream."""
    try:
        paths.HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(_clean(entry), ensure_ascii=False)
        with open(paths.HISTORY_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except Exception as e:  # noqa: BLE001
        log.warning("could not write history entry: %s", e)


def record_session(state, *, watch_url: str | None = None,
                   title: str | None = None,
                   recording_path: str | None = None) -> dict | None:
    """Build and append an entry from the live State.

    Must be called BEFORE State.reset_session(), which is the last moment
    broadcast_id, session_games, current_game and session_start all still
    exist.
    """
    if not state.broadcast_id and not recording_path:
        return None                       # nothing worth remembering

    size = None
    rec_seconds = None
    rec_started = None
    if recording_path:
        try:
            size = Path(recording_path).stat().st_size
        except OSError:
            size = None                   # file moved, or never finished
        rec_seconds = _probe_duration(recording_path)
        rec_started = _started_from_name(recording_path)

    entry = {
        "session": state.session_number,
        "broadcast_id": state.broadcast_id,
        "watch_url": watch_url,
        "title": title,
        "game": state.current_game,
        "game_key": state.current_key,
        "games": list(state.session_games) or None,
        "started": state.session_start,
        "ended": time.time(),
        "recording_path": recording_path,
        "recording_bytes": size,
        # The RECORDING's own clock, which is not the session's. OBS may have
        # been rolling before AutoStream armed -- start_recording() reuses an
        # existing output rather than interrupting one you started yourself --
        # so a file can cover far more than the session that adopted it. A
        # 46-minute recording was being listed as "1m" because the duration was
        # taken from the session instead of the file.
        "recording_started": rec_started,
        "recording_seconds": rec_seconds,
        # OBS was already recording when this session began, so `game`
        # describes only the tail of the file, not all of it.
        "recording_adopted": bool(getattr(state, "recording_adopted", False)),
    }
    append(entry)
    return entry


def _probe_duration(path: str) -> float | None:
    """The recording's real length, straight off the file.

    ffprobe rather than arithmetic on the session clock, because those are two
    different things and only one of them is what a viewer would scrub through.
    """
    try:
        from .clips.tools import media_info

        return round(float(media_info(path)["duration"]), 1) or None
    except Exception:  # noqa: BLE001 - ffmpeg is optional; the entry is still useful
        return None


def _started_from_name(path: str) -> float | None:
    """When OBS began writing, from its own filename stamp.

    OBS names recordings "YYYY-MM-DD HH-MM-SS", which is a more truthful start
    than the session's: it is when the picture in the file actually begins.
    """
    import re
    from datetime import datetime

    m = re.search(r"(\d{4})-(\d\d)-(\d\d) (\d\d)-(\d\d)-(\d\d)", Path(path).name)
    if not m:
        return None
    try:
        return datetime(*(int(g) for g in m.groups())).timestamp()
    except ValueError:
        return None


def read(limit: int | None = None) -> list[dict]:
    """Newest first. Unparseable lines are skipped, not fatal."""
    if not paths.HISTORY_FILE.exists():
        return []
    out: list[dict] = []
    try:
        with open(paths.HISTORY_FILE, "r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= MAX_LINES:
                    log.warning("history.jsonl exceeds %d lines; truncating the read",
                                MAX_LINES)
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    out.append(row)
    except OSError as e:
        log.warning("could not read history: %s", e)
        return []
    out.reverse()
    return out[:limit] if limit else out


def annotate(rows: list[dict]) -> list[dict]:
    """Add live filesystem facts the journal cannot know after the fact.

    A recording can be moved, renamed or deleted at any point after it was
    written, so whether the file is still there is decided now rather than
    trusted from the entry.
    """
    for r in rows:
        p = r.get("recording_path")
        r["has_recording"] = bool(p) and Path(p).exists()
        if r["has_recording"]:
            try:
                r["recording_bytes"] = Path(p).stat().st_size
            except OSError:
                r["has_recording"] = False

        # Entries written before recording_started/_seconds existed get them
        # filled in here, so an old journal shows correct times too.
        if r["has_recording"] and not r.get("recording_started"):
            r["recording_started"] = _started_from_name(p)
        if r["has_recording"] and not r.get("recording_seconds"):
            r["recording_seconds"] = _probe_duration(p)

        started, ended = r.get("started"), r.get("ended")
        session_len = (int(ended - started)
                       if started and ended and ended > started else None)
        r["session_seconds"] = session_len
        # The FILE's length is what the Clips page should show: it is what you
        # would be scrubbing through, and it can be far longer than the session
        # that happened to adopt it.
        r["duration"] = int(r["recording_seconds"]) if r.get("recording_seconds") \
            else session_len
        # Likewise the start: when the picture begins, not when AutoStream armed.
        r["display_started"] = r.get("recording_started") or started

        # How much of the file happened BEFORE AutoStream was watching. That
        # footage can be a different game entirely -- a 47-minute Delta Force
        # recording was labelled Counter-Strike 2 because a 1-minute CS2
        # session adopted it -- so `game` must not be presented as covering
        # the whole file when this is large.
        pre = None
        if r.get("recording_started") and started:
            pre = max(0, int(started - r["recording_started"]))
        r["pre_session_seconds"] = pre
        r["game_uncertain"] = bool(pre and pre > 60)
        # A game the user corrected by hand always wins over what was detected.
        if r.get("game_override"):
            r["game"] = r["game_override"]
            r["game_key"] = r.get("game_key_override") or r.get("game_key")
            r["game_uncertain"] = False
    return rows


def set_game(recording_path: str, game: str, game_key: str = "") -> bool:
    """Correct the game on a journalled session.

    Needed because the detected game only describes the part of a recording
    AutoStream was actually watching. Stored as an override rather than by
    editing `game`, so what was detected stays visible in the file.
    """
    # OBS reports outputPath with forward slashes while everything on the
    # Python side uses backslashes, so a literal string compare silently
    # matches nothing.
    def same(a: str, b: str) -> bool:
        try:
            return os.path.normcase(os.path.normpath(a)) == \
                   os.path.normcase(os.path.normpath(b))
        except (TypeError, ValueError):
            return a == b

    rows = read()
    hit = False
    for r in rows:
        if same(r.get("recording_path") or "", recording_path):
            r["game_override"] = game
            if game_key:
                r["game_key_override"] = game_key
            hit = True
    if hit:
        rewrite(rows)
    return hit


def rewrite(rows: list[dict]) -> None:
    """Replace the whole file. Only for deletions -- atomic, same pattern as
    state.save()."""
    paths.HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(_clean(r), ensure_ascii=False) + "\n"
                   for r in reversed(rows))       # read() reverses; undo that
    fd, tmp = tempfile.mkstemp(dir=paths.HISTORY_FILE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, paths.HISTORY_FILE)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
