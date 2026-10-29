"""The sidebar's state line: what the app is doing, said as a sentence.

It replaced a caps pill and a clock in the top bar, and it is the one place
every page shows the app's state, so what it says for each state is pinned.
"""
from __future__ import annotations

from autostream import ui
from tests import jsfn

PRELUDE = """
const SHELL_PHASE = {IDLE:{label:'Idle'},ARMING:{label:'Getting ready'},STARTING:{label:'Starting'},
  TESTING:{label:'Going live'},LIVE:{label:'Live'},COOLDOWN:{label:'Wrapping up'},STOPPING:{label:'Stopping'}};
"""


def line(status: dict) -> dict:
    import json
    return jsfn.call(ui.JS, ["shell_stateLine", "shell_clock"],
                     f"shell_stateLine({json.dumps(status)})", PRELUDE)


def test_idle_says_it_is_not_recording():
    assert line({"phase": "IDLE"}) == {"mark": "idle", "text": "Idle, not recording"}


def test_live_says_how_long():
    assert line({"phase": "LIVE", "elapsed": 5047}) == {"mark": "live", "text": "Live, 1:24:07"}


def test_live_without_a_stream_is_recording():
    assert line({"phase": "LIVE", "streaming": False, "elapsed": 760}) == {
        "mark": "live", "text": "Recording, 12:40"}


def test_a_hand_started_recording_while_idle_is_recording():
    assert line({"phase": "IDLE", "recording": True, "elapsed": 30})["text"] == "Recording, 0:30"


def test_paused_and_blocked_need_you():
    assert line({"phase": "LIVE", "paused": True}) == {"mark": "need", "text": "Paused"}
    assert line({"phase": "IDLE", "blocked": "outside streaming hours"}) == {
        "mark": "need", "text": "Held back: outside streaming hours"}


def test_transitions_are_working_and_named():
    assert line({"phase": "TESTING"}) == {"mark": "work", "text": "Going live"}


def test_the_app_opens_on_the_dashboard():
    assert "SHELL_BOOT.home || 'dash'" in ui.JS


def test_the_sidebar_is_open_unless_collapsed_by_hand():
    src = jsfn.source(ui.JS, "shell_rail")
    assert "shell_page !== 'dash'" not in src


def test_only_the_words_are_announced_not_the_clock():
    """The clock ticks every poll; inside a live region it was read out every
    two seconds for a whole stream."""
    import re
    body = ui.BODY
    assert re.search(r'id="rail-state-text"[^>]*aria-live="polite"', body)
    assert re.search(r'id="rail-state-clock"[^>]*aria-hidden="true"', body)
    assert 'id="rail-state" role="status"' not in body


def test_the_palette_keeps_its_keys_to_itself():
    """Escape in Ctrl K also reached the Studio, which closed the reel maker."""
    assert "stopImmediatePropagation" in jsfn.source(ui.JS, "pal_key")


def test_the_log_problems_are_not_rewritten_when_unchanged():
    assert "log_problemsKey" in jsfn.source(ui.JS, "log_problems")
