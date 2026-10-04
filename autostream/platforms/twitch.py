r"""Twitch, which has no broadcast to create.

THE WHOLE LIFECYCLE IS THREE THINGS. There is no `liveBroadcasts` equivalent
and Twitch does not need one: the channel is live the moment OBS pushes RTMP
to the persistent stream key. So going live is

    1. point OBS at Twitch's ingest with the key
    2. PATCH the channel's title and category
    3. start the output

and stopping is stopping the output. No create, no bind, no transition, no
delete, and no quota to run out of -- which is why this file is a fifth the
size of youtube.py for the same job.

WHAT IT CANNOT DO, and does not pretend to:

    the stream key    Twitch has no endpoint that hands it over. It is typed
                      in once and kept in secrets/twitch.json. Kick DOES have
                      one, which is why `fetches_stream_key` is a capability
                      rather than an assumption.
    chat              IRC or EventSub, neither of which is the Helix call this
                      file makes. caps.has_chat is False.
    thumbnails        no per-broadcast thumbnail exists to set.

THE CATEGORY IS AN ID, NOT A NAME. `PATCH /helix/channels` takes
`game_id`, so a name has to be looked up through `GET /helix/games` first.
That lookup is cached for the session: the same game is set at every retitle,
and a stream that switches back and forth would otherwise ask each time.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import paths
from . import Capabilities, NotConfigured, Platform, PlatformError, Session

log = logging.getLogger("autostream.platforms.twitch")

CRED_FILE = paths.SECRETS_DIR / "twitch.json"
TOKEN_FILE = paths.SECRETS_DIR / "twitch_token.json"

API = "https://api.twitch.tv/helix"
AUTH = "https://id.twitch.tv/oauth2"

# The one scope this needs. `channel:manage:broadcast` is what authorises the
# PATCH that sets a title and category; nothing here reads chat or moderates,
# so nothing here asks to.
SCOPES = ("channel:manage:broadcast",)

# Twitch's ingest. The RTMP host is stable and documented; the "auto"
# recommendation endpoint exists but needs no auth and adds a round trip to
# pick a nearer edge, which OBS already does for itself.
INGEST = "rtmp://live.twitch.tv/app"

TIMEOUT = 10.0


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = (e.read() or b"").decode("utf-8", "replace")[:300]
        raise PlatformError(f"Twitch refused ({e.code}): {detail}") from e
    except OSError as e:
        raise PlatformError(f"Twitch could not be reached: {e}") from e


class Twitch:
    """A Platform for Twitch. See the module docstring for what it is not."""

    name = "twitch"
    label = "Twitch"
    caps = Capabilities(
        # Pushing RTMP IS going live, so there is nothing to wait to be seen
        # and no preview state between started and public.
        waits_for_ingest=False,
        has_preview=False,
        has_quota=False,
        has_chat=False,
        has_thumbnail=False,
        fetches_stream_key=False,
    )

    def __init__(self, config=None) -> None:
        self.cfg = config
        self._creds: dict | None = None
        self._token: dict | None = None
        self._games: dict[str, str] = {}      # lowercased name -> game_id

    # ---- credentials -------------------------------------------------

    def creds(self) -> dict:
        if self._creds is None:
            try:
                self._creds = json.loads(CRED_FILE.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise NotConfigured(
                    f"Twitch is not set up: {CRED_FILE} is missing. It wants "
                    f"a client_id, a client_secret and a stream_key.") from None
            except (OSError, ValueError) as e:
                raise NotConfigured(f"Could not read {CRED_FILE}: {e}") from e
        return self._creds

    def configured(self) -> bool:
        try:
            c = self.creds()
        except NotConfigured:
            return False
        return bool(c.get("client_id") and c.get("client_secret")
                    and c.get("stream_key"))

    # ---- the user token ----------------------------------------------
    #
    # A USER token, not an app token. `channel:manage:broadcast` is a
    # permission over somebody's channel, so an app-only token cannot carry
    # it -- client credentials would authenticate the application and
    # authorise nothing.

    def _stored_token(self) -> dict | None:
        if self._token is None:
            try:
                self._token = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        return self._token

    def _save_token(self, tok: dict) -> None:
        tok = dict(tok)
        tok["obtained_at"] = time.time()
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(tok, indent=2), encoding="utf-8")
        self._token = tok

    def _fresh(self, tok: dict) -> bool:
        """Is it good for at least another two minutes?

        The margin matters: a token that expires between the check and the
        request fails the request, and the failure is a 401 that looks like a
        revoked authorisation rather than a stale clock.
        """
        got = float(tok.get("obtained_at") or 0)
        life = float(tok.get("expires_in") or 0)
        return bool(tok.get("access_token")) and (got + life - 120) > time.time()

    def token(self) -> str:
        tok = self._stored_token()
        if tok and self._fresh(tok):
            return str(tok["access_token"])
        if tok and tok.get("refresh_token"):
            c = self.creds()
            got = _post_form(f"{AUTH}/token", {
                "grant_type": "refresh_token",
                "refresh_token": tok["refresh_token"],
                "client_id": c["client_id"],
                "client_secret": c["client_secret"],
            })
            # A REFRESH MAY NOT RETURN A NEW REFRESH TOKEN. Twitch usually
            # does; when it does not, keeping the old one is the difference
            # between a session that renews itself and one that asks the user
            # to sign in again tomorrow.
            got.setdefault("refresh_token", tok["refresh_token"])
            self._save_token(got)
            return str(got["access_token"])
        raise NotConfigured(
            "Twitch has not been authorised yet. Connect it on the Settings "
            "page -- it opens a browser once and then renews itself.")

    def _headers(self) -> dict:
        return {"Client-Id": self.creds()["client_id"],
                "Authorization": f"Bearer {self.token()}"}

    def _call(self, method: str, path: str, *, params: dict | None = None,
              body: dict | None = None) -> dict:
        url = f"{API}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        headers = self._headers()
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
                # 204 on a successful PATCH, with no body to parse.
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = (e.read() or b"").decode("utf-8", "replace")[:300]
            if e.code in (401, 403):
                raise NotConfigured(
                    f"Twitch rejected the authorisation ({e.code}). Connect "
                    f"Twitch again on the Settings page. {detail}") from e
            raise PlatformError(f"Twitch {method} {path} failed "
                                f"({e.code}): {detail}") from e
        except OSError as e:
            raise PlatformError(f"Twitch could not be reached: {e}") from e

    # ---- who we are ---------------------------------------------------

    def channel_id(self) -> str:
        c = self.creds()
        if c.get("broadcaster_id"):
            return str(c["broadcaster_id"])
        got = self._call("GET", "/users")
        rows = got.get("data") or []
        if not rows:
            raise PlatformError("Twitch did not say which channel this is.")
        cid = str(rows[0]["id"])
        # Kept, so every later session is one request shorter.
        c["broadcaster_id"] = cid
        c["login"] = rows[0].get("login", "")
        try:
            CRED_FILE.write_text(json.dumps(c, indent=2), encoding="utf-8")
        except OSError:
            pass                       # a cache, not a requirement
        return cid

    def login(self) -> str:
        c = self.creds()
        if not c.get("login"):
            self.channel_id()
        return str(self.creds().get("login") or "")

    # ---- the category --------------------------------------------------

    def game_id(self, name: str) -> str:
        """A game's name -> Twitch's id for it, or "" if it has none.

        An unknown game is not an error. Twitch's directory does not carry
        everything, and a stream with the right title under the wrong
        category is better than a stream that refused to start.
        """
        if not name:
            return ""
        key = name.strip().lower()
        if key in self._games:
            return self._games[key]
        try:
            got = self._call("GET", "/games", params={"name": name})
        except PlatformError as e:
            log.info("could not look up the Twitch category for %r: %s", name, e)
            return ""
        rows = got.get("data") or []
        gid = str(rows[0]["id"]) if rows else ""
        if not gid:
            log.info("Twitch has no category called %r -- leaving it alone", name)
        self._games[key] = gid
        return gid

    # ---- the Platform protocol -----------------------------------------

    def preflight(self, cost: int = 0) -> None:
        if not self.configured():
            raise NotConfigured(
                "Twitch needs a client id, a client secret and a stream key.")
        self.token()               # raises NotConfigured if never authorised

    def start(self, title: str, description: str = "", *,
              privacy: str = "public", category: str = "") -> Session:
        """Set the channel's title and category, and say where OBS pushes.

        NOTHING GOES PUBLIC HERE. The channel is live when OBS starts
        pushing, which the engine does next -- so this runs first, and the
        title is already right at the moment anyone can see it.
        """
        cid = self.channel_id()
        self._patch_channel(cid, title, category)
        key = str(self.creds().get("stream_key") or "")
        return Session(handle=cid,
                       watch_url=f"https://twitch.tv/{self.login()}",
                       ingest_server=INGEST, stream_key=key,
                       extra={"category": category})

    def _patch_channel(self, cid: str, title: str, category: str) -> bool:
        body: dict = {}
        if title:
            # Twitch's limit. Cut rather than refused: a title one character
            # over is not a reason to not go live.
            body["title"] = title[:140]
        gid = self.game_id(category) if category else ""
        if gid:
            body["game_id"] = gid
        if not body:
            return False
        self._call("PATCH", "/channels", params={"broadcaster_id": cid},
                   body=body)
        return True

    def ingest_live(self, session: Session) -> bool:
        """Asked only when waits_for_ingest, which is False here.

        Answered honestly anyway, because the Settings page uses it to show
        whether Twitch can see the stream.
        """
        got = self._call("GET", "/streams",
                         params={"user_id": session.handle})
        return bool(got.get("data"))

    def go_preview(self, session: Session) -> None:
        """No preview state on Twitch: you are live or you are not."""

    def go_live(self, session: Session) -> None:
        """Already live. OBS pushing RTMP is what made it so."""

    def retitle(self, session: Session, title: str, description: str = "", *,
                category: str = "") -> bool:
        return self._patch_channel(session.handle, title, category)

    def stop(self, session: Session) -> None:
        """Nothing to end. Stopping the OBS output ends the stream.

        Deliberately not the `POST /streams/:id/markers` or the raid flow --
        stopping a session is not an event Twitch has, and inventing one
        would mean the engine's stop path behaved differently per platform.
        """


def platform(config=None) -> Platform:
    return Twitch(config)
