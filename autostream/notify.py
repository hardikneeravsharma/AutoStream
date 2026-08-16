"""Desktop notifications. Silently degrades to logging if unavailable."""
from __future__ import annotations

import logging

log = logging.getLogger("autostream.notify")

try:  # pragma: no cover
    from winotify import Notification

    _HAS = True
except ImportError:  # pragma: no cover
    _HAS = False


def toast(title: str, message: str, url: str | None = None) -> None:
    log.info("NOTIFY: %s — %s", title, message)
    if not _HAS:
        return
    try:
        n = Notification(app_id="AutoStream", title=title, msg=message)
        if url:
            n.add_actions(label="Open stream", launch=url)
        n.show()
    except Exception as e:  # noqa: BLE001
        log.debug("toast failed: %s", e)
