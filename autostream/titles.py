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


# When a session actually happened, in the words a title would use. The
# shipped template used to say "night" outright, so a stream that went up at
# two in the afternoon announced itself as a night stream.
#
# Boundaries chosen for how people describe streams rather than for astronomy:
# an 8pm start is an evening stream and a 10pm one is a night stream, and
# nobody calls 1am "morning" even though the clock does.
def daypart_of(when: datetime) -> str:
    h = when.hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 21:
        return "evening"
    return "night"


def build_vars(
    game: str,
    hook: str,
    session_games: list[str],
    session_start: datetime,
    session_number: int,
    blurb: str = "",
    username: str = "",
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now()
    return SafeDict(
        game=game,
        hook=hook,
        blurb=blurb,
        game_blurb=blurb,
        game_hashtag=hashtagify(game),
        # Your in-game name for this title, from games.yaml. Empty unless set.
        username=username,
        session_games=", ".join(dict.fromkeys(session_games)) or game,
        # Every game this session, written the way a person would say it.
        # {game} is only ever the CURRENT one, so a title built from it forgets
        # the first two games the moment a third starts.
        games=_and_list(dict.fromkeys(session_games)) or game,
        # From the SESSION's start, not from now. A stream that begins at
        # 23:50 and is retitled at 00:10 is still Wednesday's night stream, and
        # deciding otherwise mid-session renames it under the people watching.
        day=session_start.strftime("%A"),
        date=session_start.strftime("%d %b %Y"),
        daypart=daypart_of(session_start),
        time=now.strftime("%H:%M"),
        start_local=session_start.strftime("%d %b %Y, %H:%M"),
        n=session_number,
    )


def _and_list(names) -> str:
    """['a'] -> 'a';  ['a','b'] -> 'a and b';  ['a','b','c'] -> 'a, b and c'."""
    names = [str(n) for n in names if n]
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


def render_title(cfg, variables: dict) -> str:
    raw = str(cfg.title.template).format_map(variables)
    return truncate(raw, int(cfg.title.max_len)) or str(variables.get("game", "Live"))


def render_description(cfg, variables: dict) -> str:
    return str(cfg.description.template).format_map(variables).strip()[:5000]


def pick_hook(cfg, rng: random.Random | None = None) -> str:
    hooks = list(cfg.title.hooks) or ["live"]
    return (rng or random).choice(hooks)
