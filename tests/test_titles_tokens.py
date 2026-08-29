"""What a stream gets called.

Two faults, both reported off a real broadcast:

    a stream that started at 16:38 announced itself as a "night stream",
    because the template the wizard hands every new user says "night" outright;

    and a session covering Counter-Strike 2 and Delta Force was titled with
    only Delta Force, because {game} is the CURRENT game and a retitle on the
    second one forgets the first.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import titles                                   # noqa: E402


def vars_for(start: datetime, games=("Delta Force",), game=None):
    return titles.build_vars(
        game=game or games[-1], hook="no commentary",
        session_games=list(games), session_start=start, session_number=7)


# ------------------------------------------------------------- the daypart

def test_an_afternoon_stream_is_not_a_night_stream():
    """The reported case: a broadcast that went up at 16:38."""
    assert vars_for(datetime(2026, 8, 29, 16, 38))["daypart"] == "afternoon"


def test_each_part_of_the_day():
    cases = {6: "morning", 11: "morning", 12: "afternoon", 16: "afternoon",
             17: "evening", 20: "evening", 21: "night", 23: "night",
             2: "night", 4: "night"}
    for hour, want in cases.items():
        got = titles.daypart_of(datetime(2026, 8, 29, hour, 0))
        assert got == want, f"{hour:02d}:00 gave {got}, expected {want}"


def test_the_small_hours_are_night_not_morning():
    """The clock says 01:00 is morning. Nobody describing a stream does."""
    assert titles.daypart_of(datetime(2026, 8, 29, 1, 0)) == "night"


# --------------------------------------------------------- every game played

def test_games_lists_all_of_them():
    v = vars_for(datetime(2026, 8, 27, 22, 59),
                 games=("Counter-Strike 2", "Delta Force"))
    assert v["games"] == "Counter-Strike 2 and Delta Force"
    assert v["game"] == "Delta Force"        # {game} is still the current one


def test_three_games_read_as_a_list():
    v = vars_for(datetime(2026, 8, 27, 20, 0),
                 games=("VALORANT", "Counter-Strike 2", "Delta Force"))
    assert v["games"] == "VALORANT, Counter-Strike 2 and Delta Force"


def test_one_game_has_no_stray_and():
    assert vars_for(datetime(2026, 8, 27, 20, 0))["games"] == "Delta Force"


def test_a_repeated_game_is_not_listed_twice():
    """Alt-tabbing away and back is one game, not two."""
    v = vars_for(datetime(2026, 8, 27, 20, 0),
                 games=("Delta Force", "Counter-Strike 2", "Delta Force"))
    assert v["games"] == "Delta Force and Counter-Strike 2"


# ------------------------------------------------- the day the session began

def test_the_day_comes_from_the_session_not_from_now():
    """A stream that starts 23:50 Wednesday and is retitled at 00:10 is still
    Wednesday's stream. Renaming it mid-session renames it under the people
    already watching."""
    v = titles.build_vars(
        game="Delta Force", hook="h", session_games=["Delta Force"],
        session_start=datetime(2026, 8, 26, 23, 50), session_number=1,
        now=datetime(2026, 8, 27, 0, 10))
    assert v["day"] == "Wednesday"
    assert v["daypart"] == "night"
    assert v["date"] == "26 Aug 2026"
