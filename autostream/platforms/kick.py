r"""Kick, which is Twitch's shape with two differences that matter.

THE SAME LIFECYCLE. No broadcast object, no transition, no quota: the channel
is live when OBS pushes RTMP to the key, and title and category are a PATCH on
the channel. Everything the Twitch module says about why that is not YouTube's
shape applies here unchanged.

WHAT IS DIFFERENT, and why neither could be a subclass of the other:

    the token      OAuth 2.1 with PKCE, and it lasts 7200 seconds. Twitch's
                   lasts about sixty days. Refresh is not an optimisation
                   here -- a session longer than two hours outlives its own
                   token, so a retitle at hour three fails unless the token
                   was renewed in between. Every call checks.

    the stream key the API hands it over, under `streamkey:read`. Twitch has
                   no such endpoint and never will, which is why
                   `fetches_stream_key` is a capability and not an
                   assumption. It means a user who connects Kick never types
                   a key at all.

PKCE IS NOT OPTIONAL on 2.1, so the authorisation step needs a verifier and a
challenge rather than just a client secret. `pkce_pair` is here for whatever
drives the browser; this module only spends the result.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import paths
from . import Capabilities, NotConfigured, Platform, PlatformError, Session

log = logging.getLogger("autostream.platforms.kick")

CRED_FILE = paths.SECRETS_DIR / "kick.json"
TOKEN_FILE = paths.SECRETS_DIR / "kick_token.json"

API = "https://api.kick.com/public/v1"
AUTH = "https://id.kick.com/oauth"

SCOPES = ("user:read", "channel:read", "channel:write", "streamkey:read")

# Kick's ingest. The key comes from the API, so unlike Twitch nothing here is
# typed in by hand.
INGEST = "rtmps://fa723fc1b171.global-contribute.live-video.net"

TIMEOUT = 10.0

# How long before expiry a token is renewed. Larger than Twitch's margin
# because the whole life is two hours: a token refreshed at the last second
# would be renewed on almost every call during a long stream.
RENEW_MARGIN = 300.0


def pkce_pair() -> tuple[str, str]:
    """-> (verifier, challenge) for an OAuth 2.1 authorisation.

    S256, which is the only method 2.1 allows. Kept here rather than in
    whatever opens the browser so that the verifier's length and alphabet are
    decided once, next to the exchange that has to match them.
    """
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _clean(value: str, field: str, label: str) -> str:
    """A credential with whitespace in it is a label pasted with the value.

    FROM A REAL HOUR LOST. A notes file held `<id> - twitch client ID` on each
    line, the suffix went into the JSON with the value, and the authorize URL
    carried `client_id=ckldy...+-+twitch+client+ID`. Twitch answered
    `{"status":400,"message":"invalid client"}`, which is true and says
    nothing about the cause.

    No credential either platform issues contains a space, so this is never a
    false positive -- and saying so here costs one line against a 400 that
    sends somebody back to the developer console to re-copy a value that was
    always correct.
    """
    v = (value or "").strip()
    if not v:
        return v
    if any(c.isspace() for c in v):
        head = v.split()[0]
        raise NotConfigured(
            f"The {label} {field} has something after it: "
            f"{v[:len(head) + 12]!r}... That looks like a label pasted with "
            f"the value. It should be {len(head)} characters with no spaces.")
    return v


class Kick:
    """A Platform for Kick. See the module docstring for the two differences."""

    name = "kick"
    label = "Kick"
    caps = Capabilities(
        waits_for_ingest=False,
        has_preview=False,
        has_quota=False,
        has_chat=False,
        has_thumbnail=False,
        # The one capability Twitch does not have.
        fetches_stream_key=True,
    )

    def __init__(self, config=None) -> None:
        self.cfg = config
        self._creds: dict | None = None
        self._token: dict | None = None
        self._categories: dict[str, str] = {}

    # ---- credentials -------------------------------------------------

    def creds(self) -> dict:
        if self._creds is None:
            try:
                self._creds = json.loads(CRED_FILE.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise NotConfigured(
                    f"Kick is not set up: {CRED_FILE} is missing. It wants a "
                    f"client_id and a client_secret.") from None
            except (OSError, ValueError) as e:
                raise NotConfigured(f"Could not read {CRED_FILE}: {e}") from e
            for key in ("client_id", "client_secret", "stream_key"):
                if key in self._creds:
                    self._creds[key] = _clean(self._creds[key], key, "Kick")
        return self._creds

    def configured(self) -> bool:
        try:
            c = self.creds()
        except NotConfigured:
            return False
        # NO STREAM KEY IN THE TEST. Kick hands it over under
        # `streamkey:read`, so requiring one here would refuse to start an
        # install that is correctly set up.
        return bool(c.get("client_id") and c.get("client_secret"))

    # ---- the token ----------------------------------------------------

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
        got = float(tok.get("obtained_at") or 0)
        life = float(tok.get("expires_in") or 0)
        return (bool(tok.get("access_token"))
                and (got + life - RENEW_MARGIN) > time.time())

    def token(self) -> str:
        """A usable access token, renewed if this one is nearly out.

        CHECKED ON EVERY CALL, because two hours is shorter than a stream. A
        token taken at go-live is dead by the third game switch, and the
        symptom would be a retitle that silently stopped working partway
        through a long session.
        """
        tok = self._stored_token()
        if tok and self._fresh(tok):
            return str(tok["access_token"])
        if tok and tok.get("refresh_token"):
            c = self.creds()
            got = self._form(f"{AUTH}/token", {
                "grant_type": "refresh_token",
                "refresh_token": tok["refresh_token"],
                "client_id": c["client_id"],
                "client_secret": c["client_secret"],
            })
            got.setdefault("refresh_token", tok["refresh_token"])
            self._save_token(got)
            return str(got["access_token"])
        raise NotConfigured(
            "Kick has not been authorised yet. Connect it on the Settings "
            "page -- it opens a browser once and then renews itself.")

    @staticmethod
    def _form(url: str, data: dict) -> dict:
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            detail = (e.read() or b"").decode("utf-8", "replace")[:300]
            raise PlatformError(f"Kick refused ({e.code}): {detail}") from e
        except OSError as e:
            raise PlatformError(f"Kick could not be reached: {e}") from e

    def _call(self, method: str, path: str, *, params: dict | None = None,
              body: dict | None = None) -> dict:
        url = f"{API}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self.token()}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = (e.read() or b"").decode("utf-8", "replace")[:300]
            if e.code in (401, 403):
                raise NotConfigured(
                    f"Kick rejected the authorisation ({e.code}). Connect "
                    f"Kick again on the Settings page. {detail}") from e
            raise PlatformError(f"Kick {method} {path} failed "
                                f"({e.code}): {detail}") from e
        except OSError as e:
            raise PlatformError(f"Kick could not be reached: {e}") from e

    # ---- connecting it, once -------------------------------------------

    def authorize_url(self, state: str, challenge: str,
                      redirect_uri: str = "") -> str:
        """Where to send the browser. PKCE is mandatory on OAuth 2.1."""
        c = self.creds()
        return f"{AUTH}/authorize?" + urllib.parse.urlencode({
            "client_id": c["client_id"],
            "redirect_uri": redirect_uri or c.get("redirect_uri", ""),
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })

    def exchange(self, code: str, verifier: str,
                 redirect_uri: str = "") -> None:
        """Code plus the verifier whose challenge started this. Kept."""
        c = self.creds()
        got = self._form(f"{AUTH}/token", {
            "client_id": c["client_id"],
            "client_secret": c["client_secret"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri or c.get("redirect_uri", ""),
            "code_verifier": verifier,
        })
        if not got.get("access_token"):
            raise PlatformError("Kick returned no access token.")
        self._save_token(got)
        log.info("Kick connected")

    def connected(self) -> bool:
        tok = self._stored_token()
        return bool(tok and (tok.get("access_token") or tok.get("refresh_token")))

    # ---- who we are, and where to push --------------------------------

    def channel(self) -> dict:
        got = self._call("GET", "/channels")
        rows = got.get("data") or []
        if not rows:
            raise PlatformError("Kick did not say which channel this is.")
        return rows[0]

    def stream_key(self) -> str:
        """The key, from the API. Twitch has no equivalent.

        Empty rather than raising when the scope was not granted: a user who
        ticked three of the four boxes should be told what to fix, not have
        the session fail on an exception from a helper.
        """
        try:
            got = self._call("GET", "/channels/stream-key")
        except NotConfigured:
            raise
        except PlatformError as e:
            log.info("could not read the Kick stream key: %s", e)
            return ""
        data = got.get("data") or {}
        return str(data.get("stream_key") or data.get("key") or "")

    # ---- the category --------------------------------------------------

    def category_id(self, name: str) -> str:
        if not name:
            return ""
        key = name.strip().lower()
        if key in self._categories:
            return self._categories[key]
        try:
            got = self._call("GET", "/categories", params={"q": name})
        except PlatformError as e:
            log.info("could not look up the Kick category for %r: %s", name, e)
            return ""
        rows = got.get("data") or []
        cid = str(rows[0]["id"]) if rows else ""
        if not cid:
            log.info("Kick has no category called %r -- leaving it alone", name)
        self._categories[key] = cid
        return cid

    # ---- the Platform protocol -----------------------------------------

    def preflight(self, cost: int = 0) -> None:
        """Kick needs the token to go live at all, unlike Twitch.

        The key comes FROM the API, so there is no going live without an
        authorisation -- there is nothing to push with. A user who pasted a
        key into kick.json is the one exception, and is allowed through.
        """
        if not self.configured():
            raise NotConfigured("Kick needs a client id and a client secret.")
        if not self.connected() and not self.creds().get("stream_key"):
            raise NotConfigured(
                "Kick has not been connected yet, and Kick hands over the "
                "stream key through the API -- so there is nothing to stream "
                "with until you connect it on the Settings page.")

    def start(self, title: str, description: str = "", *,
              privacy: str = "public", category: str = "") -> Session:
        ch = self.channel()
        handle = str(ch.get("broadcaster_user_id") or ch.get("id") or "")
        slug = str(ch.get("slug") or "")
        self._patch_channel(title, category)
        key = str(self.creds().get("stream_key") or "") or self.stream_key()
        return Session(
            handle=handle,
            watch_url=f"https://kick.com/{slug}" if slug else "https://kick.com",
            ingest_server=INGEST, stream_key=key,
            extra={"slug": slug, "category": category})

    def _patch_channel(self, title: str, category: str) -> bool:
        body: dict = {}
        if title:
            body["stream_title"] = title[:255]
        cid = self.category_id(category) if category else ""
        if cid:
            body["category_id"] = int(cid) if cid.isdigit() else cid
        if not body:
            return False
        self._call("PATCH", "/channels", body=body)
        return True

    def ingest_live(self, session: Session) -> bool:
        got = self._call("GET", "/livestreams",
                         params={"broadcaster_user_id": session.handle})
        return bool(got.get("data"))

    def go_preview(self, session: Session) -> None:
        """No preview state on Kick."""

    def go_live(self, session: Session) -> None:
        """Already live: OBS pushing RTMP is what made it so."""

    def retitle(self, session: Session, title: str, description: str = "", *,
                category: str = "") -> bool:
        return self._patch_channel(title, category)

    def stop(self, session: Session) -> None:
        """Nothing to end. Stopping the OBS output ends the stream."""


def platform(config=None) -> Platform:
    return Kick(config)
