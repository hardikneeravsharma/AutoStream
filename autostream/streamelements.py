r"""Reading a StreamElements channel's overlays, so a screen saver can be picked.

WHY THIS EXISTS
    clips/screens.py will take a URL for any of the three screen savers, and
    the URL of a StreamElements overlay is not something anybody knows by
    heart -- it is `/overlay/<24 hex characters>/<47 more>`, found by opening
    the overlay editor and copying it. Three of those, pasted by hand, is the
    kind of setup step that gets done wrong once and then blamed on the app.

    With a token the same three become a list to choose from.

WHAT THE TOKEN IS, AND WHY IT LIVES IN secrets\
    A channel-scoped JWT that StreamElements issues from the account page. It
    is not read-only: it can modify overlays, alerts and tips. So it goes in
    secrets\, which .gitignore excludes wholesale and the share-package build
    strips, exactly like the YouTube credentials -- never in config.yaml, which
    is meant to be readable and copied about.

THE JWT ALREADY KNOWS THE OTHER TWO
    Its payload carries `channel` (the account id) and `authToken` (the overlay
    token that appears in every overlay URL), so pasting the JWT is enough and
    the other two fields are derived. They can still be given explicitly for a
    token shaped differently to the ones seen so far.

    The payload is read WITHOUT verifying the signature, which is safe here
    because nothing is being authorised: the claims are only used to address
    the user's own channel, and if they are wrong the API call simply fails.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import paths

log = logging.getLogger("autostream.streamelements")

API = "https://api.streamelements.com/kappa/v2"
OVERLAY_URL = "https://streamelements.com/overlay/{id}/{token}"
CRED_FILE = paths.SECRETS_DIR / "streamelements.json"
TIMEOUT = 25

# Overlays change rarely and the Settings page polls; a short cache keeps a
# page refresh from being an API call every two seconds.
CACHE_SECONDS = 120
_CACHE: tuple[float, list["Overlay"]] | None = None

# Which screen saver an overlay is FOR, guessed from its name. Ordered, because
# the names overlap: "Be right back" would match a naive test for "back", and
# "Stream End Scene" contains "end" while "InGame" does not mean ending.
KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("paused", ("be right back", "brb", "berightback")),
    ("starting", ("start scene", "starting", "start soon", "starting soon")),
    ("ending", ("end scene", "stream end", "ending", "outro")),
    ("game", ("ingame", "in game", "in-game", "live scene")),
    ("talk", ("talk", "chat scene", "just chatting")),
)


@dataclass
class Overlay:
    id: str
    name: str
    width: int = 1920
    height: int = 1080
    kind: str = ""          # one of KINDS, or "" when the name says nothing

    def url(self, token: str) -> str:
        return OVERLAY_URL.format(id=self.id, token=token)

    def as_dict(self, token: str = "") -> dict:
        out = {"id": self.id, "name": self.name, "kind": self.kind,
               "width": self.width, "height": self.height}
        if token:
            out["url"] = self.url(token)
        return out


def kind_of(name: str) -> str:
    low = re.sub(r"\s+", " ", str(name or "")).strip().lower()
    for kind, needles in KINDS:
        if any(n in low for n in needles):
            return kind
    return ""


# ------------------------------------------------------------- credentials

def _claims(jwt: str) -> dict:
    """The JWT's payload, unverified. See the module docstring."""
    try:
        part = str(jwt or "").split(".")[1]
        part += "=" * (-len(part) % 4)          # base64url wants padding
        return json.loads(base64.urlsafe_b64decode(part).decode("utf-8"))
    except (IndexError, ValueError, binascii.Error, UnicodeDecodeError):
        return {}


def credentials() -> dict:
    """-> {channel_id, jwt, overlay_token}. Empty when nothing is stored."""
    try:
        raw = json.loads(CRED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    jwt = str(raw.get("jwt") or "")
    claims = _claims(jwt)
    return {
        "jwt": jwt,
        "channel_id": str(raw.get("channel_id") or claims.get("channel") or ""),
        "overlay_token": str(raw.get("overlay_token")
                             or claims.get("authToken") or ""),
    }


def save_credentials(jwt: str, channel_id: str = "",
                     overlay_token: str = "") -> bool:
    """Store the token. -> whether it was written.

    Written by the APP rather than pasted into a file by hand, so the one place
    a channel credential lands is the one directory built to hold them.
    """
    jwt = str(jwt or "").strip()
    if not jwt:
        return False
    claims = _claims(jwt)
    data = {
        "jwt": jwt,
        "channel_id": (channel_id or claims.get("channel") or "").strip(),
        "overlay_token": (overlay_token or claims.get("authToken") or "").strip(),
    }
    if not data["channel_id"]:
        log.warning("that token carries no channel id; give one explicitly")
        return False
    try:
        CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
        CRED_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as e:
        log.warning("could not store the StreamElements token: %s", e)
        return False
    forget()
    log.info("stored a StreamElements token for channel %s", data["channel_id"])
    return True


def available() -> bool:
    c = credentials()
    return bool(c.get("jwt") and c.get("channel_id"))


def expires_in(jwt: str = "") -> float:
    """Seconds until the token expires; 0 when it does not say."""
    exp = _claims(jwt or credentials().get("jwt", "")).get("exp")
    try:
        return max(0.0, float(exp) - time.time())
    except (TypeError, ValueError):
        return 0.0


def forget() -> None:
    global _CACHE
    _CACHE = None


# ------------------------------------------------------------------- the API

def _get(path: str, jwt: str):
    req = urllib.request.Request(
        API + path,
        headers={"Authorization": f"Bearer {jwt}",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def overlays(force: bool = False) -> list[Overlay]:
    """Every overlay on the channel. -> [] when there is no token or no reach.

    Never raises. This feeds a settings page, and a network blip there should
    read as an empty list with a reason in the log, not a stack trace over the
    form somebody is filling in.
    """
    global _CACHE
    if _CACHE and not force and time.time() - _CACHE[0] < CACHE_SECONDS:
        return _CACHE[1]
    cred = credentials()
    if not (cred.get("jwt") and cred.get("channel_id")):
        return []
    try:
        body = _get(f"/overlays/{cred['channel_id']}", cred["jwt"])
    except urllib.error.HTTPError as e:
        log.warning("StreamElements refused the overlay list (%s). The token "
                    "may have expired or been reset.", e.code)
        return []
    except Exception as e:  # noqa: BLE001
        log.warning("could not reach StreamElements: %s", e)
        return []

    out: list[Overlay] = []
    for doc in (body or {}).get("docs") or []:
        if not isinstance(doc, dict) or not doc.get("_id"):
            continue
        # The overlay carries the size it was DESIGNED at. Rendering a browser
        # source at anything else moves every absolutely positioned widget in
        # it, so this is read rather than assumed.
        size = doc.get("settings") if isinstance(doc.get("settings"), dict) else {}
        name = str(doc.get("name") or "")
        out.append(Overlay(
            id=str(doc["_id"]), name=name,
            width=int(size.get("width") or 1920),
            height=int(size.get("height") or 1080),
            kind=kind_of(name)))
    out.sort(key=lambda o: o.name.lower())
    _CACHE = (time.time(), out)
    log.info("found %d StreamElements overlay(s)", len(out))
    return out


def listing() -> dict:
    """What the settings page needs: the overlays, with their URLs."""
    cred = credentials()
    token = cred.get("overlay_token", "")
    items = overlays()
    if items and not token:
        # Without the overlay token the ids cannot be turned into URLs, and a
        # list of names nobody can use is worse than saying why.
        return {"error": "This token carries no overlay token, so the overlay "
                         "URLs cannot be built. Paste the Overlay Token as well.",
                "overlays": []}
    return {"channel_id": cred.get("channel_id", ""),
            "overlays": [o.as_dict(token) for o in items]}


def suggest() -> dict[str, str]:
    """The best URL for each screen saver, by name. -> {which: url}.

    A guess, offered rather than applied: a channel can hold two installs of
    the same theme -- this one does -- and which copy is the live one is not
    something a name can settle.
    """
    cred = credentials()
    token = cred.get("overlay_token", "")
    if not token:
        return {}
    out: dict[str, str] = {}
    for o in overlays():
        if o.kind in ("starting", "paused", "ending") and o.kind not in out:
            out[o.kind] = o.url(token)
    return out
