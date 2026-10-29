"""Settings, grouped by what you are doing, with the config keys out of the way.

The approved redesign (docs/superpowers/specs/2026-10-29-ui-redesign-design.md,
"Settings -- picked: A, grouped sections") files twelve sections under four
headings -- App, Streaming, Making clips, Advanced -- and moves the dotted
config key (`ui.theme`) out of every row a stranger reads. Both are easy to
undo by accident: a section added without a group simply vanishes from the
nav, and a key printed unconditionally is one line of markup. So both are
pinned here, offline, with the page's own functions run in Node.
"""
from __future__ import annotations

import json

from autostream import schema, ui
from autostream.ui import settings as settings_page
from tests import jsfn


# ------------------------------------------------------------ the groups

def test_every_section_belongs_to_a_group():
    """A section with no group has nowhere to sit in the nav, so it would be
    on the page and unreachable."""
    known = [g["id"] for g in schema.GROUPS]
    assert known == ["app", "streaming", "clips", "advanced"]
    for sec in schema.CONFIG_SCHEMA:
        assert sec.get("group") in known, f"{sec['id']} is in no group"


def test_the_groups_are_named_in_plain_words():
    assert [g["label"] for g in schema.GROUPS] == [
        "App", "Streaming", "Making clips", "Advanced"]


def test_advanced_is_its_own_group_and_nothing_else_is_in_it():
    inside = [s["id"] for s in schema.CONFIG_SCHEMA if s["group"] == "advanced"]
    assert inside == ["advanced"]


def _grouped(sections):
    # Only what grouping reads: the whole schema does not fit on a command line.
    slim = [{"id": s["id"], "group": s.get("group")} for s in sections]
    expr = f"set_grouped({json.dumps(slim)}, {json.dumps(schema.GROUPS)})"
    return jsfn.call(ui.JS, ["set_grouped"], expr)


def test_the_nav_lists_the_groups_in_order_with_their_sections():
    got = _grouped(schema.CONFIG_SCHEMA)
    assert [g["label"] for g in got] == ["App", "Streaming", "Making clips", "Advanced"]
    flat = [s["id"] for g in got for s in g["sections"]]
    assert sorted(flat) == sorted(s["id"] for s in schema.CONFIG_SCHEMA)


def test_a_group_with_nothing_left_in_it_is_not_drawn():
    """The Mac build strips the streaming sections from the schema. A heading
    with nothing under it reads as a page that failed to load."""
    only = [s for s in schema.CONFIG_SCHEMA if s["group"] != "streaming"]
    got = _grouped(only)
    assert "Streaming" not in [g["label"] for g in got]


def test_a_section_from_a_newer_server_still_shows():
    """An old page against a newer schema: a group it has never heard of
    lands under Advanced rather than disappearing."""
    got = _grouped([{"id": "x", "label": "X", "group": "nope", "fields": []}])
    assert [s["id"] for g in got for s in g["sections"]] == ["x"]


# ------------------------------------------------------- the config keys

def _shown(sec, dev):
    return jsfn.call(ui.JS, ["set_keyShown"],
                     f"set_keyShown({json.dumps(sec)}, {json.dumps(dev)})")


def test_keys_are_hidden_outside_advanced():
    assert _shown("appearance", False) is False
    assert _shown("stream", False) is False
    assert _shown("advanced", False) is True
    # Developer mode is for the person who wants them everywhere.
    assert _shown("appearance", True) is True


def test_the_key_element_is_only_drawn_behind_the_guard():
    """A text scan, because the guard is one `if` and the leak is one line:
    the only place a `.field-key` is written is inside set_fieldHtml, and
    only after set_keyShown has said yes."""
    js = settings_page.SETTINGS_JS
    assert js.count("field-key") == 1, "a second place prints the config key"
    body = jsfn.source(js, "set_fieldHtml")
    assert "field-key" in body
    assert body.index("set_keyShown(") < body.index("field-key")


def test_the_search_still_finds_a_setting_by_its_key():
    """People paste keys out of the log. Hiding the key from the row must not
    hide it from the search."""
    body = jsfn.source(settings_page.SETTINGS_JS, "set_fieldHtml")
    find = body[body.index("data-find"):]
    assert "f.path" in find[:200]


# ------------------------------------------------------------- shortcuts

def _shortcuts(values, cmds, scopes):
    expr = (f"set_shortcutRows({json.dumps(values)}, {json.dumps(cmds)}, "
            f"{json.dumps(scopes)})")
    return jsfn.call(ui.JS, ["set_shortcutRows"], expr)


def test_shortcuts_lists_the_two_hotkeys_and_the_command_keys():
    from autostream.ui import commands
    slim = [{"label": c["label"], "scope": c["scope"], "keys": c["keys"]}
            for c in commands.COMMANDS]
    scopes = [{"id": s["id"], "label": s["label"]} for s in commands.SCOPES]
    got = _shortcuts({"rules.replay_hotkey": "F9", "rules.kill_switch_hotkey": ""},
                     slim, scopes)
    flat = [r for g in got for r in g["rows"]]
    replay = next(r for r in flat if r.get("path") == "rules.replay_hotkey")
    assert replay["keys"] == ["F9"]
    kill = next(r for r in flat if r.get("path") == "rules.kill_switch_hotkey")
    assert kill["keys"] == [], "an unset hotkey must say so, not invent one"
    assert any("Ctrl+K" in r["keys"] for r in flat)
    # Every bound command is listed, and only those with a key -- plus the two
    # hotkeys and the window's own keys (page size and Ctrl K, 4 rows).
    bound = sum(1 for c in commands.COMMANDS if c["keys"])
    assert len(flat) == bound + 2 + 4
    assert any("Ctrl+Scroll up" in r["keys"] for r in flat)


# ------------------------------------------------- first-run setup, named steps

def test_setup_names_its_steps_in_a_list_and_marks_the_current_one():
    """The pips say how far, not what is left. The list says both, and
    aria-current is how a screen reader is told which one this is."""
    from autostream.ui import setup
    assert '<ol class="setup-steps" id="setup-steplist" aria-label="Setup steps">' in setup.SETUP_HTML
    bar = jsfn.source(setup.SETUP_JS, "setup_bar")
    assert 'aria-current="step"' in bar
    # The progressbar the narrow layout uses is still there for the tests that drive it.
    assert 'id="setup-stepbar" role="progressbar"' in setup.SETUP_HTML
