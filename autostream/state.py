"""Crash-safe state persistence.

Every phase transition is flushed to state.json BEFORE the side effect fires,
so a power cut is always recoverable on next startup.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from . import paths

# phases
IDLE = "IDLE"
ARMING = "ARMING"
STARTING = "STARTING"
TESTING = "TESTING"
LIVE = "LIVE"
COOLDOWN = "COOLDOWN"
STOPPING = "STOPPING"


@dataclass
class State:
    phase: str = IDLE
    broadcast_id: str | None = None
    session_start: float | None = None       # epoch seconds
    session_number: int = 0
    hook: str | None = None
    current_game: str | None = None          # display name
    current_key: str | None = None           # exe key
    session_games: list[str] = field(default_factory=list)
    quota_spent: int = 0
    quota_date: str = ""                     # YYYY-MM-DD, Pacific-ish
    last_index_refresh: float = 0.0
    paused: bool = False
    # Set the moment recording starts, so a crash mid-session still leaves a
    # breadcrumb pointing at the file OBS was writing. load() filters unknown
    # keys, so an older state.json without this loads fine.
    recording: bool = False
    # True when OBS was ALREADY recording as the session began, so the file
    # covers footage this session knows nothing about.
    recording_adopted: bool = False

    # ---------- persistence ----------

    @classmethod
    def load(cls) -> "State":
        if not paths.STATE_FILE.exists():
            return cls()
        try:
            data: dict[str, Any] = json.loads(
                paths.STATE_FILE.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        """Atomic write — never leave a half-written state file behind."""
        paths.ensure_dirs()
        payload = json.dumps(asdict(self), indent=2)
        d = paths.STATE_FILE.parent
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, paths.STATE_FILE)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # ---------- helpers ----------

    def reset_session(self) -> None:
        self.phase = IDLE
        self.broadcast_id = None
        self.session_start = None
        self.hook = None
        self.current_game = None
        self.current_key = None
        self.session_games = []
        self.recording = False
        self.recording_adopted = False

    def roll_quota_day(self) -> None:
        """YouTube quota resets at midnight US/Pacific. Approximated by UTC-8."""
        from datetime import datetime, timedelta, timezone

        today = (datetime.now(timezone.utc) - timedelta(hours=8)).date().isoformat()
        if self.quota_date != today:
            self.quota_date = today
            self.quota_spent = 0

    def spend(self, units: int) -> None:
        self.roll_quota_day()
        self.quota_spent += units

    def quota_left(self, daily: int = 10000) -> int:
        self.roll_quota_day()
        return max(0, daily - self.quota_spent)
