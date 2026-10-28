"""The idle Dashboard for a stranger: what will happen, and what is missing.

The old idle page was an empty graph, a dash for a clock and a platform
picker for an install that does not go live. The redesign replaces it with a
checklist built from real state (dash_checks), each unticked item carrying
the one button that fixes it, and a 'Ready' line once nothing is missing.
"""
from __future__ import annotations

import json

from autostream import ui
from tests import jsfn


def checks(status):
    return jsfn.call(ui.JS, ["dash_checks"], f"dash_checks({json.dumps(status)})")


FRESH = {"phase": "IDLE", "obs_found": False, "apps": [{"name": "Discord", "game": False}],
         "record_enabled": False, "streaming": False}


def test_a_fresh_install_shows_every_item_unticked_with_a_fix():
    got = checks(FRESH)
    need = [c for c in got if not c["optional"]]
    assert [c["key"] for c in need] == ["obs", "games", "record"]
    assert all(not c["ok"] and c["fix"] for c in need), got


def test_going_live_is_optional_and_says_it_is_off():
    live = [c for c in checks(FRESH) if c["key"] == "live"][0]
    assert live["optional"] is True and live["ok"] is False
    assert "off" in live["note"].lower()


def test_a_set_up_install_is_ready():
    s = dict(FRESH, obs_found=True, record_enabled=True, streaming=True, platform_ready=True,
             apps=[{"name": "VALORANT", "game": True}, {"name": "Counter-Strike 2", "game": True}])
    got = checks(s)
    assert all(c["ok"] for c in got), got
    games = [c for c in got if c["key"] == "games"][0]
    assert "2" in games["note"]


def test_the_ready_line_names_the_games():
    expr = "dash_readyLine([{name:'VALORANT',game:true},{name:'Counter-Strike 2',game:true}," \
           "{name:'Aim Lab',game:true},{name:'Discord',game:false}])"
    got = jsfn.call(ui.JS, ["dash_readyLine"], expr)
    assert got == "Waiting for a game. VALORANT, Counter-Strike 2 and 1 more start a recording."


def test_the_idle_panels_are_on_the_page():
    for el in ('id="dash-idle"', 'id="dash-setup"', 'id="dash-since"'):
        assert el in ui.BODY, el
