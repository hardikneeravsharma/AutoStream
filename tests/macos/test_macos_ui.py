"""The page's half of the Mac build: pages and choices taken away when, and
only when, /api/bootstrap says so. The browser tier exercises it for real; this
pins the wiring so a refactor cannot quietly drop it."""
from __future__ import annotations

import re

from autostream import ui
from autostream.ui import setup as setup_page
from autostream.ui import shell


def test_the_shell_drops_pages_the_bootstrap_names():
    js = ui.JS
    assert "shell_dropPages(SHELL_BOOT.hide_pages || [])" in js
    assert "page = SHELL_BOOT.home || 'dash'" in js
    assert "let start = SHELL_BOOT.home || 'dash';" in js


def test_on_windows_nothing_is_dropped_and_dash_is_home():
    """No hide_pages and no home in a Windows bootstrap: the fallbacks above
    are exactly the old 'dash' and an empty list."""
    js = ui.JS
    body = js[js.index("function shell_dropPages"):]
    body = body[:body.index("\n}\n")]
    assert "for (let i = 0; i < pages.length" in body


def test_the_wizard_offers_only_the_clipper_when_streaming_is_unavailable():
    js = ui.JS
    assert "(b.unavailable || []).indexOf('streaming') < 0" in js
    for sel in ('[data-act="wantStream"]', "#setup-streamnote", "#setup-golive"):
        assert sel in js, sel


def test_the_ids_the_wizard_removes_exist_in_its_cards():
    src = open(setup_page.__file__, encoding="utf-8").read()
    for ident in ("setup-streamnote", "setup-golive"):
        assert f'id="{ident}"' in src, ident
    assert 'data-act="wantStream"' in src


def test_tool_hints_prefer_the_servers_words():
    """Homebrew's commands on a Mac; the winget line, unchanged, otherwise."""
    js = ui.JS
    assert "x.install || 'winget install --id ' + x.winget" in js
    assert "t.install || 'winget install --id ' + t.winget" in js
    assert "t.install_note ||" in js and "r.manual_note ||" in js


def test_the_rail_still_lists_every_page():
    """Taken away at boot, never at build: one page, both platforms."""
    pages = [n[0] for n in shell._NAV]
    assert pages == ["dash", "library", "clips", "studio", "settings", "logs"]
    assert re.search(r"const SHELL_PAGES = \['dash', 'library', 'clips'", ui.JS)
