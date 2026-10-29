"""A button that says what it fixes opens the setting that fixes it.

The idle Dashboard's 'Turn recording on' went to Settings searched for
"Record" -- and on a first visit the search ran before the page had loaded its
settings, so the user landed on Appearance, the first section, with nothing to
do there. Every fix button now names the SETTING it opens (set_open), which
waits for the page to load if it has to, then shows that setting's section and
puts the focus on it.
"""
from __future__ import annotations

import re

from autostream import logexplain, schema, ui
from tests import jsfn


def _paths() -> set[str]:
    return set(schema.FIELDS_BY_PATH)


def test_the_checklist_opens_the_setting_it_names():
    fix = re.search(r"const dash_FIX = \{(.*?)\n\};", ui.JS, re.S).group(1)
    assert "set_open('record.enabled')" in fix
    assert "set_open('obs.path')" in fix
    assert "set_search(" not in fix, "a search is not a place to land"


def test_every_setting_a_button_opens_exists():
    named = set(re.findall(r"set_open\('([a-z_.]+)'\)", ui.JS))
    for p in logexplain.PROBLEMS:
        act = (p["fix"] or {}).get("act", "")
        if act.startswith("setting:"):
            named.add(act.split(":", 1)[1])
    assert named, "no set_open links found"
    missing = named - _paths()
    assert not missing, missing


def test_the_logs_open_settings_by_setting_not_by_search():
    acts = [(p["fix"] or {}).get("act", "") for p in logexplain.PROBLEMS]
    assert not [a for a in acts if a.startswith("settings:")], acts
    assert "setting:record.directory" in acts and "setting:obs.path" in acts


def test_opening_before_the_page_has_loaded_waits_for_it():
    src = jsfn.source(ui.JS, "set_open")
    assert "set_state.loaded" in src and "set_state.openAfterLoad" in src
    load = jsfn.source(ui.JS, "set_load")
    assert "openAfterLoad" in load, "the load must finish the open it was asked for"


def test_ctrl_k_opens_the_setting_too():
    assert re.search(r"pal_source\('Settings'.*?set_open\(f\.path\)", ui.JS, re.S)
