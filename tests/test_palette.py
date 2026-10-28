"""Ctrl K, from any page: one box that finds clips, reels, games and settings
and runs commands.

The Studio had a command palette that only existed inside the Studio. The
redesign makes it the app's: the shell owns the box, and each page registers
what it can find (pal_source). These pin the parts that can be checked
without a browser.
"""
from __future__ import annotations

import json
import re

from autostream import ui
from autostream.ui import commands
from tests import jsfn


def test_every_page_registers_what_it_can_find():
    names = set(re.findall(r"pal_source\('([^']+)'", ui.JS))
    assert {"Clips", "Reels", "Games", "Settings", "Actions"} <= names, names


def test_ctrl_k_is_the_apps_not_the_studios():
    pal = [c for c in commands.COMMANDS if "Ctrl+K" in c["keys"]]
    assert pal and all(c["id"] == "studio.palette" for c in pal)
    # the shell listens for it, so it works on every page
    assert "pal_open" in jsfn.source(ui.JS, "pal_key")


def _collect(q, sources):
    srcs = ", ".join(
        "{name: %s, fn: function(q){ return %s; }}" % (json.dumps(n), json.dumps(rows))
        for n, rows in sources)
    return jsfn.call(ui.JS, ["pal_collect"], f"pal_collect({json.dumps(q)}, [{srcs}])",
                     "const PAL_GROUPS = ['Clips','Reels','Games','Actions','Settings'];")


def test_results_come_grouped_in_a_fixed_order():
    rows = _collect("x", [("Settings", [{"label": "s"}]), ("Clips", [{"label": "c"}]),
                          ("Actions", [{"label": "a"}])])
    assert [r["group"] for r in rows] == ["Clips", "Actions", "Settings"]


def test_no_group_floods_the_list():
    rows = _collect("x", [("Clips", [{"label": str(i)} for i in range(20)])])
    assert len(rows) == 6


def test_a_source_that_throws_does_not_empty_the_box():
    js_sources = ("[{name:'Clips', fn:function(){ throw new Error('boom'); }},"
                  " {name:'Games', fn:function(){ return [{label:'Valorant'}]; }}]")
    rows = jsfn.call(ui.JS, ["pal_collect"], f"pal_collect('v', {js_sources})",
                     "const PAL_GROUPS = ['Clips','Reels','Games','Actions','Settings'];")
    assert [r["label"] for r in rows] == ["Valorant"]


def test_matching_takes_every_word_in_any_order():
    expr = ("[pal_match('clutch bind', '1v3 clutch, Bind'), pal_match('bind 1v3', '1v3 clutch, Bind'),"
            " pal_match('ace', '1v3 clutch, Bind'), pal_match('', 'anything')]")
    assert jsfn.call(ui.JS, ["pal_match"], expr) == [True, True, False, True]
