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


# --------------------------------------------- the picture follows the title

from autostream.engine import Engine                             # noqa: E402
from autostream.state import LIVE, State                         # noqa: E402
from autostream.gameindex import GameHit                         # noqa: E402
from autostream import cfg                                       # noqa: E402


def a_switching_engine():
    """An engine mid-session, about to be told a different game is running."""
    eng = Engine.__new__(Engine)
    c = cfg.load()
    raw = {k: (dict(v) if isinstance(v, dict) else v) for k, v in c.items()}
    raw["youtube"] = dict(raw["youtube"])
    raw["youtube"]["switch_policy"] = "rolling"
    eng.cfg = cfg.Config(raw)
    eng.state = State(phase=LIVE)
    eng.state.broadcast_id = "bid"
    eng.state.current_game = "Counter-Strike 2"
    eng.state.session_games = ["Counter-Strike 2"]
    eng.state.save = lambda: None            # type: ignore[method-assign]
    eng.streaming = True
    eng._switch_candidate = None
    eng.thumbs = []
    eng._set_thumbnail = lambda: eng.thumbs.append(eng.state.current_game)

    class Yt:
        retitled = []
        def retitle(self, bid, title, desc):
            Yt.retitled.append(title)
    eng.yt = Yt()

    class Obs:
        def set_scene(self, s): pass
        def set_overlay_text(self, t): pass
    eng.obs = Obs()
    return eng


def test_switching_game_updates_the_thumbnail_too():
    """It used to be set once at go-live and never again, so a session that
    started on one game kept its picture all night -- and a per-game image
    assigned to the SECOND game never appeared at all, which reads as the
    assignment silently not working.

    Drives the real _maybe_switch, twice: once to nominate the candidate and
    once past the debounce, which is how a switch actually happens.
    """
    eng = a_switching_engine()
    hit = GameHit(key="deltaforceclient-win64-shipping.exe", name="Delta Force",
                  source="test")

    eng._maybe_switch(hit)                       # nominates, does not switch
    assert eng.thumbs == []
    assert eng.state.current_game == "Counter-Strike 2"

    eng._switch_candidate = (hit.key, 0.0)       # debounce already served
    eng._maybe_switch(hit)

    assert eng.state.current_game == "Delta Force"
    assert eng.yt.retitled, "the broadcast was never retitled"
    assert "Delta Force" in eng.yt.retitled[-1]
    assert eng.thumbs == ["Delta Force"], "the picture did not follow the title"


def test_a_switch_still_happens_when_the_thumbnail_fails():
    """A thumbnail is decoration; the retitle is the thing viewers see in
    their subscriptions. One must not be able to take the other down."""
    eng = a_switching_engine()

    def boom():
        raise RuntimeError("no frame")
    eng._set_thumbnail = boom
    hit = GameHit(key="cs2.exe", name="Counter-Strike 2 Redux", source="test")
    eng._switch_candidate = (hit.key, 0.0)
    try:
        eng._maybe_switch(hit)
    except RuntimeError:
        raise AssertionError("a failing thumbnail broke the game switch")
    assert eng.state.current_game == "Counter-Strike 2 Redux"


# ------------------------------------- a template nobody could have saved
#
# The Settings page refuses to save "{game" -- unbalanced braces are caught by
# schema.validate. But the config is a YAML file people edit by hand, and until
# the upload and voice settings reached that page, editing it by hand was the
# only way to change some of them. So a broken template arriving at the
# renderer is reachable, and it used to raise ValueError out of _begin_session
# and stop the stream starting, over a missing bracket in a title.

def _stub(title="{game}", desc="{game}", max_len=100):
    import types

    return types.SimpleNamespace(
        title=types.SimpleNamespace(template=title, max_len=max_len),
        description=types.SimpleNamespace(template=desc))


def _vars():
    from datetime import datetime

    return titles.build_vars(
        game="Counter-Strike 2", hook="casual run",
        session_games=["Counter-Strike 2"],
        session_start=datetime(2026, 9, 2, 20, 30),
        session_number=1, blurb="b", username="YUVANETA")


def test_an_unbalanced_brace_does_not_stop_a_stream_starting():
    got = titles.render_title(_stub(title="{game"), _vars())
    assert got == "Counter-Strike 2"


def test_a_stray_closing_brace_is_survived_too():
    assert titles.render_title(_stub(title="}{"), _vars()) == "Counter-Strike 2"


def test_a_broken_description_comes_back_empty_rather_than_raising():
    assert titles.render_description(_stub(desc="{oops"), _vars()) == ""


def test_a_malformed_template_says_so_in_the_log(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="autostream.titles"):
        titles.render_title(_stub(title="{game"), _vars())
    assert "malformed" in caplog.text
    assert "Settings" in caplog.text, "the log should say where to fix it"


def test_an_unknown_token_costs_only_that_token():
    """Already true, and worth pinning: build_vars supplies "" for a token it
    does not have, so a typo does not take the rest of the title with it."""
    got = titles.render_title(_stub(title="{game} {typo} tonight"), _vars())
    assert got.startswith("Counter-Strike 2")
    assert "tonight" in got


def test_a_good_template_is_untouched():
    got = titles.render_title(_stub(title="{game} - {hook}"), _vars())
    assert got == "Counter-Strike 2 - casual run"
