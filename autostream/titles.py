"""Title and description rendering. Pure functions, no side effects."""
from __future__ import annotations

import random
import re
from datetime import datetime


def hashtagify(name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", "", name or "")
    return cleaned or "gaming"


def truncate(text: str, limit: int) -> str:
    """Cut at a word boundary, never mid-word, and never leave a dangling dash."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" -—|,:") + "…"


class SafeDict(dict):
    """Unknown {placeholders} render as empty instead of raising."""

    def __missing__(self, key):
        return ""


def build_vars(
    game: str,
    hook: str,
    session_games: list[str],
    session_start: datetime,
    session_number: int,
    blurb: str = "",
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now()
    return SafeDict(
        game=game,
        hook=hook,
        blurb=blurb,
        game_blurb=blurb,
        game_hashtag=hashtagify(game),
        session_games=", ".join(dict.fromkeys(session_games)) or game,
        day=now.strftime("%A"),
        date=now.strftime("%d %b %Y"),
        time=now.strftime("%H:%M"),
        start_local=session_start.strftime("%d %b %Y, %H:%M"),
        n=session_number,
    )


def render_title(cfg, variables: dict) -> str:
    raw = str(cfg.title.template).format_map(variables)
    return truncate(raw, int(cfg.title.max_len)) or str(variables.get("game", "Live"))


def render_description(cfg, variables: dict) -> str:
    return str(cfg.description.template).format_map(variables).strip()[:5000]


def pick_hook(cfg, rng: random.Random | None = None) -> str:
    hooks = list(cfg.title.hooks) or ["live"]
    return (rng or random).choice(hooks)
