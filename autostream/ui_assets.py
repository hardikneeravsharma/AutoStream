"""Backwards-compatible re-export of the UI bundle.

The CSS/HTML/JS used to live here as three long string literals. It now lives
in the `ui` package, one module per view, because a four-page app with a full
settings form outgrew a single file. webui.page() still reads
ui_assets.CSS/BODY/JS, so this module keeps that name stable rather than
rippling the change through the server.

New code should import from `autostream.ui` directly.
"""
from __future__ import annotations

from .ui import BODY, CSS, JS

__all__ = ["BODY", "CSS", "JS"]
