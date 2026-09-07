"""What the app actually exposes, read out of the source.

The dashboard is one HTML document built by concatenating string constants in
autostream/ui/*.py, and every action it can take is an HTTP call to
autostream/webui.py. Neither side declares itself: there is no route table and
no control registry, so "does every button work" has never had an answer that
survived the next commit.

This module derives both sides mechanically. tests/verify/test_surface.py then
asserts they close against the catalogue -- a button that calls a route nobody
serves, or a route nobody catalogued, fails the suite.

Reading source with regexes is the same technique tests/test_ui_wiring.py and
tests/test_settings_coverage.py already use, and it carries the same hazard:
a pattern that quietly stops matching leaves the check green while it inspects
nothing. So every extractor here returns something a caller can count, and the
tests assert floors on those counts.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UI_DIR = REPO / "autostream" / "ui"
WEBUI = REPO / "autostream" / "webui.py"

# The pages that make up the single-document UI. shell is the frame; the rest
# are the views the rail switches between, plus the first-run wizard.
PAGES = ("shell", "settings", "clips", "dashboard", "library", "logs", "setup")


@lru_cache(maxsize=1)
def ui_source() -> dict[str, str]:
    """Every rendered string each UI module exposes, keyed by page."""
    out = {}
    for name in PAGES:
        text = (UI_DIR / f"{name}.py").read_text(encoding="utf-8", errors="ignore")
        out[name] = text
    return out


# ------------------------------------------------------------- endpoints

# Any quoted literal that looks like a route, wherever it appears. Deliberately
# not keyed to a helper name: the UI reaches the server through API.post,
# API.get, setup.py's own setup_post wrapper, and bare src=/href= URLs on media
# elements. A regex per helper would silently miss the next one somebody adds.
_ROUTE_LITERAL = re.compile(r"""['"](/api/[A-Za-z0-9_/-]*)[^'"]*['"]""")


@lru_cache(maxsize=1)
def ui_endpoints() -> dict[str, set[str]]:
    """Route path -> the set of pages that reference it.

    Query strings are stripped: the UI writes '/api/logs/tail?n=300' and the
    server dispatches on u.path alone.
    """
    found: dict[str, set[str]] = {}
    for page, text in ui_source().items():
        for m in _ROUTE_LITERAL.finditer(text):
            path = m.group(1).rstrip("?&")
            found.setdefault(path, set()).add(page)
    return found


# ------------------------------------------------------------- controls

# data-act is the delegated-dispatch vocabulary: one listener per page reads
# the attribute off the clicked element and switches on it. Every value is an
# action a user can take.
_DATA_ACT = re.compile(r"""data-act=["']([a-z0-9][a-z0-9 _-]*)["']""")


@lru_cache(maxsize=1)
def ui_actions() -> dict[str, set[str]]:
    """data-act token -> the pages that define it."""
    found: dict[str, set[str]] = {}
    for page, text in ui_source().items():
        for m in _DATA_ACT.finditer(text):
            for token in m.group(1).split():
                found.setdefault(token, set()).add(page)
    return found


# Ids that look like something a user operates, as opposed to a container the
# script writes into. Both are declared the same way in the markup, so the
# distinction is the naming convention the codebase already follows.
_ID_DEF = re.compile(r"""id=["']([A-Za-z0-9_-]+)["']""")
_OPERABLE = re.compile(
    r"(?:^|-)(?:btn|button|save|discard|check|get|open|copy|fetch|build|"
    r"refresh|send|cancel|toggle|quit|install|reset|close|auto|input)(?:-|$)")


@lru_cache(maxsize=1)
def ui_operable_ids() -> dict[str, set[str]]:
    """Element id -> pages, for ids whose name says a user operates them."""
    found: dict[str, set[str]] = {}
    for page, text in ui_source().items():
        for m in _ID_DEF.finditer(text):
            el = m.group(1)
            if _OPERABLE.search(el):
                found.setdefault(el, set()).add(page)
    return found


def names_the_ui_still_uses(name: str) -> bool:
    """Does this control name appear anywhere in the rendered UI at all?

    Deliberately looser than the extractors above. It answers one question --
    "is this thing still real" -- for the exemption list, where the hazard is
    a note about a button that was deleted three releases ago quietly covering
    for the next button to take the same name. A class (`rail-btn`), an id
    (`log-filters`) and a data-act token are all legitimate answers, so
    matching the raw source is the honest test rather than guessing which
    extractor should have caught it.
    """
    return any(name in text for text in ui_source().values())


# ------------------------------------------------------------- the server

# webui dispatches with a chain of string comparisons rather than a table:
#   if u.path == "/api/status":      (GET, via _get)
#   elif p == "/api/cmd":            (POST, via do_POST, path bound to p)
# plus one tuple membership test for the page itself.
_EQ = re.compile(r"""(?:u\.path|p)\s*==\s*['"](/[^'"]*)['"]""")
_IN_TUPLE = re.compile(r"""u\.path\s+in\s+\(([^)]*)\)""")


@lru_cache(maxsize=1)
def server_routes() -> set[str]:
    """Every path webui.py answers."""
    src = WEBUI.read_text(encoding="utf-8", errors="ignore")
    routes = set(_EQ.findall(src))
    for group in _IN_TUPLE.findall(src):
        for lit in re.findall(r"""['"](/[^'"]*)['"]""", group):
            routes.add(lit)
    return routes


@lru_cache(maxsize=1)
def server_methods() -> dict[str, set[str]]:
    """Route -> {'GET'} / {'POST'}, by which dispatcher the literal sits in.

    _get() handles reads and do_POST() handles writes; the file has no shared
    dispatch, so which function body a comparison falls inside is the method.
    """
    src = WEBUI.read_text(encoding="utf-8", errors="ignore")
    get_at = src.index("    def _get(self, u):")
    post_at = src.index("    def do_POST(self):")
    lo, hi = min(get_at, post_at), max(get_at, post_at)
    first, second = ("GET", "POST") if get_at < post_at else ("POST", "GET")

    out: dict[str, set[str]] = {}
    for method, chunk in ((first, src[lo:hi]), (second, src[hi:])):
        for path in _EQ.findall(chunk):
            out.setdefault(path, set()).add(method)
        for group in _IN_TUPLE.findall(chunk):
            for lit in re.findall(r"""['"](/[^'"]*)['"]""", group):
                out.setdefault(lit, set()).add(method)
    return out
