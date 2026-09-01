"""Write a file so that an interrupted write cannot destroy the old one.

WHY THIS EXISTS AS A SHARED THING
    config.yaml, state.json and history.jsonl were already written this way --
    to a temporary file in the same directory, then renamed over the target,
    which on Windows and POSIX alike is the closest thing to an atomic swap a
    filesystem offers. So the reasoning was already accepted here; it just had
    not reached the files the Clips page depends on.

    Those were written with a plain write_text(), which truncates the target
    first. Killed in that window -- and this app is killed routinely, by a
    rebuild, by the tray, by a crash -- the file is left empty or half-written:

      * clips.json holds the YouTube ids of clips already uploaded. Lose it and
        the app no longer knows what went up, so the next batch uploads them
        AGAIN. An upload is the one action here that cannot be undone quietly.
      * session.json holds the plan a run was cut from. Lose it and no clip in
        that folder can be re-rendered, because there is nothing left to say
        where in the recording it came from.
      * a cached Valorant match record cannot be fetched again once the Riot
        Client has closed, so a truncated one is gone for good.

    None of that announces itself. The file parses as invalid JSON at some
    later moment, and the feature simply has no data.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger("autostream.atomic")


def write_text(path: Path | str, text: str, *, encoding: str = "utf-8") -> None:
    """Replace `path` with `text`, or leave it exactly as it was.

    The temporary file is made in the TARGET'S OWN DIRECTORY, because
    os.replace cannot move across volumes and a clips folder on another drive
    is the ordinary case here rather than an exotic one.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp",
                               prefix=target.name + ".")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        # Including BaseException: a KeyboardInterrupt mid-write should not
        # leave a stray .tmp beside the file it was protecting.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path: Path | str, data: Any, *, indent: int | None = 2) -> None:
    """Replace `path` with `data` as JSON, or leave it exactly as it was."""
    write_text(path, json.dumps(data, indent=indent))
