"""Composes the single-page UI from the per-view modules.

The page is one HTML document, one <style> and one <script>. Splitting the
source across modules keeps each view editable on its own, but the browser
still receives a flat bundle, so two things matter here and nowhere else:

1. ORDER. Every JS fragment lands in ONE top-level scope. shell.SHELL_JS must
   come first because it declares the shared API/toast/go/icon/esc/STATUS that
   every view calls. View modules only add their own `PAGE_*` global and
   prefix everything else (dash_, lib_, set_, log_, setup_) so nothing
   collides — a duplicate top-level `const` is a SyntaxError that would take
   the whole page down, not just one view.

2. PLACEHOLDERS. SHELL_HTML owns the frame and marks where each view's markup
   goes with {{NAME}} tokens. Substituting here means the views never need to
   know how the frame is built.

No boot call is appended: shell schedules its own on a macrotask, by which
point the synchronously-parsed view modules have registered their PAGE objects.
"""
from __future__ import annotations

from .css import CSS
from .dashboard import DASH_HTML, DASH_JS
from .icons import ICONS, LOGO_LOCKUP, LOGO_MARK
from .library import LIBRARY_HTML, LIBRARY_JS
from .logs import LOGS_HTML, LOGS_JS
from .settings import SETTINGS_HTML, SETTINGS_JS
from .setup import SETUP_HTML, SETUP_JS
from .shell import SHELL_HTML, SHELL_JS

_VIEWS = {
    "{{DASH_HTML}}": DASH_HTML,
    "{{LIBRARY_HTML}}": LIBRARY_HTML,
    "{{SETTINGS_HTML}}": SETTINGS_HTML,
    "{{LOGS_HTML}}": LOGS_HTML,
    "{{SETUP_HTML}}": SETUP_HTML,
}


def _build_body() -> str:
    body = SHELL_HTML
    for token, markup in _VIEWS.items():
        if token not in body:
            raise RuntimeError(f"ui/shell.py is missing the {token} placeholder")
        body = body.replace(token, markup)
    return body


BODY = _build_body()

JS = "\n".join((
    SHELL_JS,          # must be first: declares the shared globals
    DASH_JS,
    LIBRARY_JS,
    SETTINGS_JS,
    LOGS_JS,
    SETUP_JS,
))

__all__ = ["BODY", "CSS", "ICONS", "JS", "LOGO_LOCKUP", "LOGO_MARK"]
