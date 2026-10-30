"""kills.json: every kill a clip job found, for other tools to read later.

SEPARATE FROM session.json ON PURPOSE. session.json is this app's own record
-- the next run reuses its kills, the Studio reads them, the stream list says
"made before" from it -- and anything added there is something every one of
those readers has to tolerate. kills.json is the outward-facing one: a stable,
versioned list of moments a highlight tool can pick up without knowing how
AutoStream cuts clips.

The kill dicts the job passes around carry extra keys for this file only
(SIDE_KEYS): how many frames a row was read in, what each frame called it, and
whether the kill came from a Counter-Strike demo. for_session() strips them,
so session.json is byte-for-byte what it was.
"""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from .. import atomic
from . import plan
from .tools import _NO_WINDOW

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FILENAME = "kills.json"
SIDE_KEYS = ("seen", "votes", "demo")   # carried on kill dicts for kills.json only; never written to session.json
_VOTE_LETTERS = set("kdao")             # valorant_feed.collapse: kill, death, assist, other


def _recorded(k: dict) -> bool:
    # Riot's match record marks its kills "record"; a Counter-Strike demo's
    # cannot, because session.json must not change, so it rides as "demo".
    return bool(k.get("record") or k.get("demo"))


def source_of(k: dict) -> str:
    """Where a kill came from: the game's own record, its emblem, or the screen."""
    return "record" if _recorded(k) else "emblem" if k.get("emblem") else "screen"


def confidence(k: dict) -> float | None:
    """The share of sightings that called it a kill, 1.0 for a record.

    None when nothing was measured -- kills reused from an older session.json
    carry no votes, and a made-up number would read as a measurement.
    """
    if _recorded(k):
        return 1.0
    votes = k.get("votes") or ""
    # Only frame-by-frame votes (k/d/a/o) are a share. The OCR second look
    # marks the kills it adds "ocr", which counted as letters would read as
    # a reader sure the row was NOT a kill.
    if votes and set(votes) <= _VOTE_LETTERS:
        return round(votes.count("k") / len(votes), 3)
    return None


def for_session(kills: list[dict]) -> list[dict]:
    """The kills as session.json has always had them."""
    return [{n: v for n, v in k.items() if n not in SIDE_KEYS} for k in kills]


def events(kills: list[dict]) -> list[dict]:
    """One entry per kill, in time order, with the burst the planner puts it in."""
    ordered = sorted(kills, key=lambda k: float(k.get("time") or 0.0))
    # The planner's own grouping, so "burst" here means what a clip means.
    # cluster() sorts the same way and appends one time per kill, so walking
    # both in step pairs each kill with its burst.
    owner = [(i, b.kills) for i, b in enumerate(plan.cluster(ordered)) for _ in b.times]
    out = []
    for k, (bid, size) in zip(ordered, owner):
        t = float(k.get("time") or 0.0)
        out.append({
            # Always "kill" today. There so deaths and assists can be added
            # later without a new schema_version.
            "kind": "kill",
            "time": round(t, 3),
            "end": round(max(t, float(k.get("end") or t)), 3),
            "headshot": bool(k["hs"]) if "hs" in k else None,
            "round": int(k["round"]) if k.get("round") else None,
            "source": source_of(k),
            "confidence": confidence(k),
            "seen": int(k["seen"]) if k.get("seen") else None,
            "burst_id": bid, "burst_size": size,
        })
    return out


_commit: list = []   # [sha or None] once looked up


def _commit_sha() -> str | None:
    """The checkout's short commit, or None in a frozen build or on any trouble."""
    if not _commit:
        sha = None
        root = Path(__file__).resolve().parents[2]
        # A worktree's .git is a file, so exists() rather than is_dir().
        if (root / ".git").exists():
            try:
                got = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                                     capture_output=True, text=True, timeout=2,
                                     creationflags=_NO_WINDOW)
                if got.returncode == 0:
                    sha = got.stdout.strip() or None
            except (OSError, subprocess.SubprocessError):
                sha = None
        _commit.append(sha)
    return _commit[0]


def build(*, kind: str, source, duration: float, game: str, game_key: str | None,
          started_at: float, kills: list[dict], scanned: list[float] | None = None) -> dict:
    from .. import __version__

    return {
        "schema_version": SCHEMA_VERSION, "kind": kind,
        "status": "ok" if kills else "no_kills",
        "source": str(source), "duration": round(float(duration or 0.0), 3),
        "game": game, "game_key": game_key,
        "started_at": datetime.fromtimestamp(started_at).astimezone().isoformat(timespec="seconds"),
        "autostream": {"version": __version__, "commit": _commit_sha()},
        "scanned": list(scanned) if scanned is not None else None,
        "events": events(kills),
    }


def write(folder, doc: dict) -> Path | None:
    """Write kills.json into a job folder. Never raises: it is an extra, and an
    extra that fails the run it describes is worse than no extra."""
    try:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / FILENAME
        atomic.write_json(out, doc)
        return out
    except Exception as e:                                   # noqa: BLE001
        log.warning("could not write %s: %s", FILENAME, e)
        return None
