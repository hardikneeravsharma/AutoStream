r"""YouTube, behind the Platform seam.

AN ADAPTER, NOT A REWRITE. `youtube.py` keeps every line it had: the quota
accounting, the orphan sweep, the chat paging, the thumbnail upload. This maps
the five things the engine does in a session onto the calls that file already
exposes, so moving the engine onto the seam changes which object it talks to
and nothing about what happens.

The mapping is the whole file:

    preflight    check_budget
    start        create_broadcast + bind
    ingest_live  stream_status on the reusable ingest
    go_preview   transition "testing"
    go_live      transition "live"
    retitle      retitle
    stop         transition "complete"

`yt` stays reachable as an attribute, because chat, thumbnails, quota and the
orphan sweep are YouTube's alone and the engine reaches them through the
capability flags rather than through methods every platform would have to stub.
"""
from __future__ import annotations

import logging

from . import Capabilities, NotConfigured, Platform, PlatformError, Session

log = logging.getLogger("autostream.platforms.youtube")


class YouTubePlatform:
    """A Platform for YouTube, wrapping the existing YouTube client."""

    name = "youtube"
    label = "YouTube"
    caps = Capabilities(
        # The broadcast will not transition until YouTube sees the ingest, so
        # the engine has to wait and watch rather than assume.
        waits_for_ingest=True,
        # `testing` is what the kill switch's grace period happens in.
        has_preview=True,
        has_quota=True,
        has_chat=True,
        has_thumbnail=True,
        # YouTube binds an ingest object rather than handing over a key.
        fetches_stream_key=False,
    )

    def __init__(self, config, yt) -> None:
        """`yt` may be the client or a callable returning it.

        A CALLABLE, because capturing the client at construction makes this
        object stale the moment it is replaced -- and it is replaced: by
        re-authorisation, and by every test that swaps in a fake. A platform
        that answers from a client nobody is using any more fails in the way
        that is hardest to see, by doing nothing wrong with the wrong object.
        """
        self.cfg = config
        self._yt = yt

    @property
    def yt(self):
        return self._yt() if callable(self._yt) else self._yt

    def configured(self) -> bool:
        from .. import paths

        return paths.CLIENT_SECRET.exists()

    def preflight(self, cost: int = 0) -> None:
        """Quota first, because finding out afterwards is expensive.

        A broadcast is 50 units to create, 50 to bind and 50 to delete again.
        An attempt that runs out halfway has already spent them and left a
        real broadcast behind.
        """
        from ..youtube import NotAuthorised, QuotaExhausted

        try:
            if cost:
                self.yt.check_budget(cost)
        except QuotaExhausted as e:
            raise PlatformError(str(e)) from e
        except NotAuthorised as e:
            raise NotConfigured(str(e)) from e

    def ready(self) -> tuple[bool, str]:
        """A permanent stream and a Google credential, which is what setup
        writes. Asked on every poll, so nothing here reaches the network.
        """
        from .. import paths

        if not getattr(self.cfg.youtube, "stream_id", ""):
            return False, ("YouTube has no permanent stream bound yet. Finish "
                           "setup on the Settings page.")
        if not paths.TOKEN_FILE.exists():
            return False, ("YouTube is not signed in. Connect it on the "
                           "Settings page.")
        return True, ""

    def start(self, title: str, description: str = "", *,
              privacy: str = "public", category: str = "") -> Session:
        """Create the broadcast and bind it to the reusable ingest.

        `category` is ignored: YouTube takes a category id on the video after
        the fact, not on the broadcast, and the engine already sets video
        metadata separately once it is live.
        """
        from ..youtube import NotAuthorised, QuotaExhausted

        try:
            bid = self.yt.create_broadcast(title, description, privacy=privacy)
            self.yt.bind(bid, self.cfg.youtube.stream_id)
        except QuotaExhausted as e:
            raise PlatformError(str(e)) from e
        except NotAuthorised as e:
            raise NotConfigured(str(e)) from e
        return Session(handle=bid, watch_url=self.yt.watch_url(bid))

    def ingest_live(self, session: Session) -> bool:
        status, health = self.yt.stream_status(self.cfg.youtube.stream_id)
        log.debug("ingestion status=%s health=%s", status, health)
        if status != "active":
            return False
        if health not in ("good", "ok", "noData"):
            # REPORTED, NOT REFUSED. A health YouTube is unsure about is
            # usually a moment of bitrate wobble at the start, and refusing
            # to go live over it would cost the session.
            log.warning("ingestion health is %s - continuing anyway", health)
        return True

    def go_preview(self, session: Session) -> None:
        self.yt.transition(session.handle, "testing")

    def go_live(self, session: Session) -> None:
        self.yt.transition(session.handle, "live")

    def retitle(self, session: Session, title: str, description: str = "", *,
                category: str = "") -> bool:
        return bool(self.yt.retitle(session.handle, title, description or None))

    def stop(self, session: Session) -> None:
        """Complete the broadcast. Never raises on one already gone.

        A session can end after the broadcast has been completed from the
        YouTube side, or deleted, and an exception here would stop the engine
        finishing its own shutdown -- which is how OBS got left streaming an
        ending card.
        """
        try:
            self.yt.transition(session.handle, "complete")
        except Exception as e:                               # noqa: BLE001
            log.info("could not complete broadcast %s: %s", session.handle, e)


def platform(config, yt) -> Platform:
    return YouTubePlatform(config, yt)
