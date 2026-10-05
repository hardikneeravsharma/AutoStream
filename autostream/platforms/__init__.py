r"""Where a broadcast goes: YouTube, Twitch, Kick.

WHY A SEAM AT ALL. `engine.py` is the state machine, and it was written against
YouTube directly -- `self.yt`, `cfg.youtube.*`, and a lifecycle shaped exactly
like YouTube's liveBroadcasts API. That is not a general shape. It is one
platform's, and the other two do not have it.

THE DIFFERENCE IS NOT COSMETIC, which is why this is a protocol and not a
subclass of YouTube:

    YouTube   a broadcast is an OBJECT you create, bind to an ingest stream,
              transition testing -> live -> complete, and may delete. You are
              live when you say you are. Costs quota: 50 units to create, 50
              to bind, 50 to delete.

    Twitch    there is no broadcast object and no API that starts one. You are
              live the moment OBS pushes RTMP to your persistent key. Title
              and category are a PATCH on the channel, which works whether you
              are live or not. No quota.

    Kick      the same, plus OAuth 2.1 with PKCE and a two-hour token.

So the seam models what the ENGINE needs -- go live, know when it is live,
retitle, stop, say where to watch -- and lets each platform answer in its own
terms. Forcing Twitch into create/bind/transition would mean three no-op
methods and a lie about what is happening.

WHAT STAYS OUT. Chat, thumbnails, quota and orphan sweeping are YouTube's
alone today. They are reached through `caps` rather than through methods every
platform must stub, so adding a platform does not mean writing five functions
that return None.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = ["Capabilities", "Session", "Platform", "PlatformError",
           "NotConfigured"]


class PlatformError(RuntimeError):
    """The platform refused or could not be reached."""


class NotConfigured(PlatformError):
    """Credentials are missing or incomplete. The user must act."""


@dataclass(frozen=True)
class Capabilities:
    """What this platform can do, so the engine can skip what it cannot.

    Flags rather than methods returning None: a caller that must ask
    `if p.caps.has_chat` before reading chat is harder to get wrong than one
    that calls `p.chat_messages()` and has to know that None means
    "unsupported" rather than "nothing new".
    """

    # The engine must wait for the platform to SEE the ingest before it can
    # go live. True for YouTube, whose broadcast will not transition until
    # the stream is active; false for Twitch and Kick, where pushing RTMP is
    # itself going live.
    waits_for_ingest: bool = False
    # There is a preview state between started and public -- YouTube's
    # `testing`. The kill switch's grace period only means something here.
    has_preview: bool = False
    # Starting costs API quota that can run out.
    has_quota: bool = False
    has_chat: bool = False
    has_thumbnail: bool = False
    # The stream key is fetched over the API rather than typed in. True for
    # Kick, which grants a `streamkey:read` scope; false for Twitch, which
    # has no such endpoint, and for YouTube, which binds an ingest object
    # instead of handing over a key.
    fetches_stream_key: bool = False


@dataclass
class Session:
    """One live session, as the platform sees it.

    `handle` is whatever the platform needs to address it again -- a
    broadcast id on YouTube, the channel id on Twitch and Kick. The engine
    keeps it and hands it back; it never reads it.
    """

    handle: str
    watch_url: str = ""
    # Where OBS should push, when the platform wants to be told. YouTube
    # leaves this empty: it binds an ingest object and OBS is already
    # configured for the service.
    ingest_server: str = ""
    stream_key: str = ""
    extra: dict = field(default_factory=dict)


@runtime_checkable
class Platform(Protocol):
    """What the engine needs from somewhere to broadcast to.

    Every method may raise PlatformError. None of them may block for longer
    than a few seconds: the engine calls them from its own thread, and a
    platform that hangs stops the state machine.
    """

    name: str                      # "youtube" | "twitch" | "kick"
    label: str                     # "YouTube" | "Twitch" | "Kick"
    caps: Capabilities

    def configured(self) -> bool:
        """Are the credentials present? Cheap; no network."""
        ...

    def preflight(self, cost: int = 0) -> None:
        """Raise if this session cannot start. Quota, auth, anything.

        Called BEFORE anything is created, because on YouTube finding out
        afterwards costs 150 units and leaves a real broadcast behind.
        """
        ...

    def ingest(self) -> tuple[str, str]:
        """-> (rtmp server, stream key) for OBS, without starting anything.

        SETUP NEEDS THIS AND A SESSION DOES NOT. Twitch and Kick push to a
        persistent key, so the whole of "configure OBS" can be done once at
        install time -- which is what the first-run wizard wants, and what
        made a second platform feel like a different product to set up rather
        than the same one.

        YouTube has nothing to answer with: its ingest is created by the
        wizard's own finish step and the key is never stored, so it returns
        empty and the wizard keeps its own path for that one.
        """
        ...

    def ready(self) -> tuple[bool, str]:
        """-> (can this go live, why not). Cheap, and changes nothing.

        SEPARATE FROM `preflight` because the two are asked at different
        moments for different reasons. `preflight` is asked once, at the top
        of a session, and may log, spend quota or warn. This is asked by the
        dashboard on every two-second poll, so it may do none of those -- the
        first version called `preflight` there and Twitch's "not connected"
        warning went into the log thirty times a minute.

        It is here rather than computed by the caller so that each platform's
        rule lives with the platform. Twitch can stream on the key alone;
        Kick cannot, because its key comes from the API.
        """
        ...

    def start(self, title: str, description: str = "", *,
              privacy: str = "public", category: str = "") -> Session:
        """Make ready to broadcast. -> the session.

        YouTube creates and binds a broadcast. Twitch and Kick set the title
        and category on the channel and hand back where OBS should push. In
        neither case is anything public yet.
        """
        ...

    def ingest_live(self, session: Session) -> bool:
        """Is the platform receiving video? Only asked when waits_for_ingest."""
        ...

    def go_preview(self, session: Session) -> None:
        """Enter the preview state. Only called when has_preview."""
        ...

    def go_live(self, session: Session) -> None:
        """Make it public. A no-op where pushing RTMP already did that."""
        ...

    def retitle(self, session: Session, title: str,
                description: str = "", *, category: str = "") -> bool:
        """Change the title mid-session, when the game changes."""
        ...

    def stop(self, session: Session) -> None:
        """End it. Must not raise on an already-ended session."""
        ...
