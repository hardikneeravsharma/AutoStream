"""YouTube Data API v3 wrapper: auth, reusable stream, broadcast lifecycle.

Quota model: write ops = 50 units, list ops = 1 unit, default 10,000/day.
Every call goes through _spend() so we can refuse to start a session we
wouldn't be able to cleanly finish.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import paths

log = logging.getLogger("autostream.yt")

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

COST_WRITE = 50
COST_LIST = 1
# thumbnails.set is billed as a write. Worth its own name because it is opt-in
# and adds 50 units to every session that uses it -- 300 instead of 250, which
# is 33 sessions a day against the default 10,000 quota rather than 40.
COST_THUMBNAIL = 50
DAILY_QUOTA = 10000

# videos.insert. Historically 1600 units against a 10,000/day default -- six
# uploads a day. Reporting since December 2025 says Google cut it to about 100
# and moved uploads into a separate daily bucket, and sources published since
# still disagree with one another.
#
# So: assume the EXPENSIVE case and correct it from evidence. upload_video
# logs the quota actually consumed, and rules.upload_daily_max caps the count
# independently of this arithmetic -- a wrong estimate must not be able to
# quietly burn a day's streaming.
UPLOAD_COST = 1600
UPLOAD_CHUNK = 4 * 1024 * 1024
TITLE_MAX = 100
DESCRIPTION_MAX = 5000


class QuotaExhausted(RuntimeError):
    pass


class NotAuthorised(RuntimeError):
    pass


class Cancelled(RuntimeError):
    """The user stopped an upload between chunks."""


class _Prompt(str):
    """The message run_local_server prints, which is also the only place it
    lets the sign-in URL out: it calls .format(url=...) on this after opening
    the browser and before it starts waiting. Handing the URL on from there
    means a page can offer the link itself when no browser opened."""

    def __new__(cls, text: str, on_url=None):
        obj = super().__new__(cls, text)
        obj.on_url = on_url
        return obj

    def format(self, *args, **kwargs):  # noqa: A003 - str's own name
        if self.on_url and kwargs.get("url"):
            try:
                self.on_url(kwargs["url"])
            except Exception:  # noqa: BLE001 - a display hook must not break sign-in
                pass
        return str(self)


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- sign-in age
#
# WHY THIS IS INFERRED AND NOT ASKED
#     An OAuth consent screen left in Testing issues refresh tokens that die
#     after about seven days. The symptom is streaming that silently stops
#     working days after a setup that went perfectly, and the cause is one
#     button in a console nobody has open any more. It is the single most
#     expensive avoidable failure in this product.
#
#     Google does not tell the client whether the app is published. There is
#     no field, no endpoint and no scope for it -- so "refuse to finish setup
#     while it is in Testing" cannot be built, however much one would want it.
#
#     What CAN be known is the thing that actually matters. A published app's
#     refresh token does not expire. So a token that is still being refreshed
#     nine days after it was granted PROVES the app is published, and the
#     question is settled by evidence rather than by asking somebody to
#     confirm something they may have misremembered.
#
#     Until that proof exists, the days between 5 and 7 are worth a word --
#     while the fix is still a button rather than a sign-in.
GRANT_FILE_NAME = "token_granted.json"
TESTING_TOKEN_DAYS = 7.0
WARN_AFTER_DAYS = 5.0
PROVEN_AFTER_DAYS = 9.0


def _grant_file():
    return paths.TOKEN_FILE.with_name(GRANT_FILE_NAME)


def _note_grant(*, fresh: bool) -> None:
    """Record when this sign-in was granted, and whether it has outlived a
    Testing-mode token. Never raises: this is a note, not a credential."""
    import json as _json
    import time as _time

    f = _grant_file()
    try:
        data = _json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    now = _time.time()
    if fresh or not data.get("granted_at"):
        data = {"granted_at": now, "long_lived": False}
    elif not data.get("long_lived"):
        # A REFRESH THAT WORKED THIS LATE IS THE PROOF. A Testing-mode token
        # would have been rejected days ago.
        age = (now - float(data.get("granted_at") or now)) / 86400.0
        if age >= PROVEN_AFTER_DAYS:
            data["long_lived"] = True
            log.info("the Google sign-in has outlived a Testing-mode token; "
                     "this app is published")
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(_json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def sign_in_health() -> dict:
    """-> {days, long_lived, warn, why}. Never raises, never asks Google."""
    import json as _json
    import time as _time

    out = {"days": 0.0, "long_lived": False, "warn": False, "why": ""}
    f = _grant_file()
    if not paths.TOKEN_FILE.exists() or not f.is_file():
        return out
    try:
        data = _json.loads(f.read_text(encoding="utf-8"))
        at = float(data.get("granted_at") or 0)
    except (OSError, ValueError, TypeError):
        return out
    if not at:
        return out
    out["days"] = round(max(0.0, (_time.time() - at) / 86400.0), 1)
    out["long_lived"] = bool(data.get("long_lived"))
    if out["long_lived"] or out["days"] < WARN_AFTER_DAYS:
        return out
    left = max(0.0, TESTING_TOKEN_DAYS - out["days"])
    out["warn"] = True
    out["why"] = (
        f"Your Google sign-in is {out['days']:.0f} days old. If the OAuth "
        f"consent screen is still in Testing it expires at about seven days "
        f"{'(roughly %.0f left)' % left if left else '(any time now)'} and "
        f"streaming stops with no warning. Google Cloud Console -> Google "
        f"Auth Platform -> Audience -> Publish app. If it is already "
        f"published this notice goes away by itself once the sign-in has "
        f"outlived a Testing token.")
    return out


class YouTube:
    def __init__(self, config, state=None):
        self.cfg = config
        self.state = state
        self._svc = None

    # ---------------- auth ----------------

    def authorise(self, interactive: bool = False, *,
                  timeout: float | None = None, on_url=None):
        """`timeout` bounds the wait for the browser; `on_url` is handed the
        sign-in link as soon as it exists, so a page can show it on a machine
        whose default browser never opened."""
        creds = None
        fresh_consent = False
        if paths.TOKEN_FILE.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(paths.TOKEN_FILE), SCOPES)
            except (ValueError, KeyError) as e:
                log.warning("token.json unreadable (%s) — will re-authorise", e)

        if creds and creds.valid:
            pass
        elif creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                log.info("refreshed access token")
            except Exception as e:  # noqa: BLE001
                log.error("token refresh failed: %s", e)
                if not interactive:
                    raise NotAuthorised(
                        "Refresh token rejected. If your Google Cloud OAuth consent "
                        "screen is still in Testing mode, tokens expire after ~7 days "
                        "— publish the app (Google Auth Platform -> Audience -> "
                        "Publish App), then run: python -m autostream auth"
                    ) from e
                creds = None
        else:
            creds = None

        if creds is None:
            if not interactive:
                raise NotAuthorised("No valid credentials. Run: python -m autostream auth")
            if not paths.CLIENT_SECRET.exists():
                raise NotAuthorised(f"Missing {paths.CLIENT_SECRET}")
            fresh_consent = True
            flow = InstalledAppFlow.from_client_secrets_file(str(paths.CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(
                port=0,
                prompt="consent",
                access_type="offline",
                timeout_seconds=timeout,
                authorization_prompt_message=_Prompt(
                    "\nOpening your browser to authorise AutoStream.\n"
                    "You WILL see 'Google hasn't verified this app' — that is expected "
                    "for a personal app.\nClick Advanced -> Go to <app> (unsafe).\n",
                    on_url),
            )

        paths.ensure_dirs()
        _note_grant(fresh=fresh_consent)
        paths.TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        try:
            paths.TOKEN_FILE.chmod(0o600)
        except OSError:
            pass

        self._svc = build("youtube", "v3", credentials=creds, cache_discovery=False)
        return self._svc

    @property
    def svc(self):
        if self._svc is None:
            self.authorise(interactive=False)
        return self._svc

    # ---------------- quota ----------------

    def _spend(self, units: int) -> None:
        if self.state is None:
            return
        self.state.spend(units)
        self.state.save()

    def quota_left(self) -> int:
        return self.state.quota_left(DAILY_QUOTA) if self.state else DAILY_QUOTA

    def check_budget(self, need: int) -> None:
        reserve = self.cfg.rules.quota_reserve
        if self.quota_left() < need + reserve:
            raise QuotaExhausted(
                f"only {self.quota_left()} units left (need {need} + {reserve} reserve)"
            )

    # ---------------- uploading a finished clip ----------------

    def upload_video(self, path, *, title: str, description: str = "",
                     privacy: str = "unlisted", tags=None,
                     category_id: str = "20",
                     on_progress=None, should_stop=None) -> dict:
        """Upload one file. -> {id, url}. Resumable, cancellable, chunked.

        RESUMABLE ON PURPOSE. A forty-megabyte clip on a domestic uplink is not
        instant, and a plain upload that dies at ninety percent starts again
        from nothing. Chunks also give the only honest progress there is, and
        the only place a cancel can be honoured -- between chunks, cooperatively,
        exactly as ClipJob does it.

        The title is checked HERE rather than by YouTube, because YouTube
        rejects the whole request on a long title and it does so only after the
        file has finished uploading.
        """
        from googleapiclient.http import MediaFileUpload

        title = str(title or "").strip()
        if not title:
            raise ValueError("A video needs a title.")
        if len(title) > TITLE_MAX:
            raise ValueError(
                f"That title is {len(title)} characters; YouTube's limit is "
                f"{TITLE_MAX}, and it rejects the whole upload after the file "
                f"has already gone up.")
        if privacy not in ("public", "unlisted", "private"):
            privacy = "unlisted"

        src = Path(path)
        if not src.is_file():
            raise FileNotFoundError(f"{src} is not there")

        self.check_budget(UPLOAD_COST)
        before = self.quota_left()

        body = {
            "snippet": {
                "title": title,
                "description": str(description or "")[:DESCRIPTION_MAX],
                "categoryId": str(category_id or "20"),
                "tags": [str(t)[:60] for t in (tags or [])][:15],
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": bool(self.cfg.youtube.made_for_kids),
            },
        }
        media = MediaFileUpload(str(src), chunksize=UPLOAD_CHUNK,
                                resumable=True, mimetype="video/*")
        request = self.svc.videos().insert(part="snippet,status", body=body,
                                           media_body=media)
        # Charged once, up front. An upload that fails halfway has still spent
        # the units, and pretending otherwise would let a failing batch loop
        # against a quota the app believes is intact.
        self._spend(UPLOAD_COST)

        response = None
        while response is None:
            if should_stop is not None and should_stop():
                raise Cancelled("upload cancelled")
            status, response = request.next_chunk()
            if status is not None and on_progress is not None:
                try:
                    on_progress(float(status.progress()))
                except Exception:  # noqa: BLE001 - progress must never fail an upload
                    pass

        vid = str(response.get("id") or "")
        if not vid:
            raise RuntimeError("YouTube accepted the upload but returned no id.")
        log.info("uploaded %s as %s (%s) -- quota %d -> %d",
                 src.name, vid, privacy, before, self.quota_left())
        return {"id": vid, "url": f"https://www.youtube.com/watch?v={vid}",
                "shorts_url": f"https://www.youtube.com/shorts/{vid}",
                "privacy": privacy, "title": title}

    # ---------------- channel ----------------

    def channel_title(self) -> str:
        r = self.svc.channels().list(part="snippet", mine=True).execute()
        self._spend(COST_LIST)
        items = r.get("items") or []
        return items[0]["snippet"]["title"] if items else "(unknown)"

    def live_enabled(self) -> tuple[bool, str]:
        """Can this channel go live at all? -> (yes, why not).

        ASKED AT SETUP, NOT AT GO-LIVE. Live streaming is off by default on a
        new YouTube channel and turning it on takes up to 24 hours to come
        through. Found out at the first session, that is an evening wasted and
        an error that says nothing about what to do -- found out during setup,
        it is a sentence and a wait that runs while everything else is being
        set up anyway.

        ONE UNIT. `liveBroadcasts.list` is the cheapest call that goes through
        the live-streaming permission check, so this costs 1 of 10,000 against
        the 50 a broadcast costs to discover the same thing the hard way.
        """
        try:
            self.svc.liveBroadcasts().list(
                part="id", mine=True, maxResults=1).execute()
            self._spend(COST_LIST)
            return True, ""
        except Exception as e:                           # noqa: BLE001
            low = str(e).lower()
            self._spend(COST_LIST)
            if "livestreamingnotenabled" in low or "not enabled for live" in low:
                return False, (
                    "Live streaming is not switched on for this channel. Go to "
                    "youtube.com/features, enable it, and verify your phone "
                    "number if it asks -- then it can take up to 24 hours to "
                    "come through. Everything else here can be set up while "
                    "you wait.")
            if "livepermissionblocked" in low or "blocked" in low:
                return False, (
                    "YouTube has blocked live streaming on this channel, "
                    "usually for a recent Community Guidelines strike. Check "
                    "youtube.com/features -- it says there when it lifts.")
            # Anything else is not an answer to this question, and refusing to
            # finish setup over a network blip would be worse than not asking.
            log.info("could not check live streaming: %s", str(e)[:200])
            return True, ""

    # ---------------- the permanent reusable stream ----------------

    def create_reusable_stream(self, title: str = "AutoStream permanent ingest") -> dict:
        body = {
            "snippet": {"title": title},
            "cdn": {
                "frameRate": "variable",
                "ingestionType": "rtmp",
                "resolution": "variable",
            },
            "contentDetails": {"isReusable": True},
        }
        r = self.svc.liveStreams().insert(
            part="snippet,cdn,contentDetails", body=body).execute()
        self._spend(COST_WRITE)
        info = r["cdn"]["ingestionInfo"]
        return {
            "id": r["id"],
            "stream_key": info["streamName"],
            "ingestion_address": info.get("rtmpsIngestionAddress") or info["ingestionAddress"],
        }

    def find_reusable_stream(self, stream_id: str) -> dict | None:
        try:
            r = self.svc.liveStreams().list(
                part="id,snippet,cdn,contentDetails", id=stream_id).execute()
        except HttpError:
            return None
        self._spend(COST_LIST)
        items = r.get("items") or []
        if not items:
            return None
        info = items[0]["cdn"]["ingestionInfo"]
        return {
            "id": items[0]["id"],
            "stream_key": info["streamName"],
            "ingestion_address": info.get("rtmpsIngestionAddress") or info["ingestionAddress"],
        }

    def stream_status(self, stream_id: str) -> tuple[str, str]:
        r = self.svc.liveStreams().list(part="status", id=stream_id).execute()
        self._spend(COST_LIST)
        items = r.get("items") or []
        if not items:
            return "notFound", "noData"
        st = items[0]["status"]
        return st.get("streamStatus", "?"), st.get("healthStatus", {}).get("status", "?")

    # ---------------- broadcasts ----------------

    def create_broadcast(self, title: str, description: str, privacy: str | None = None) -> str:
        use_monitor = self.cfg.timing.abort_grace > 0
        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "scheduledStartTime": _now_rfc3339(),
            },
            "status": {
                "privacyStatus": privacy or self.cfg.youtube.privacy,
                "selfDeclaredMadeForKids": bool(self.cfg.youtube.made_for_kids),
            },
            "contentDetails": {
                "enableAutoStart": False,
                "enableAutoStop": True,          # server-side net if we crash
                "enableDvr": True,
                "recordFromStart": True,
                "latencyPreference": self.cfg.youtube.latency,
                "monitorStream": {
                    "enableMonitorStream": use_monitor,
                    "broadcastStreamDelayMs": 0,
                },
            },
        }
        r = self.svc.liveBroadcasts().insert(
            part="snippet,status,contentDetails", body=body).execute()
        self._spend(COST_WRITE)
        log.info("created broadcast %s: %s", r["id"], title)
        return r["id"]

    def bind(self, broadcast_id: str, stream_id: str) -> None:
        self.svc.liveBroadcasts().bind(
            id=broadcast_id, part="id,contentDetails", streamId=stream_id).execute()
        self._spend(COST_WRITE)

    def transition(self, broadcast_id: str, status: str) -> None:
        self.svc.liveBroadcasts().transition(
            broadcastStatus=status, id=broadcast_id, part="id,status").execute()
        self._spend(COST_WRITE)
        log.info("broadcast %s -> %s", broadcast_id, status)

    def get_broadcast(self, broadcast_id: str) -> dict | None:
        r = self.svc.liveBroadcasts().list(
            part="snippet,status", id=broadcast_id).execute()
        self._spend(COST_LIST)
        items = r.get("items") or []
        return items[0] if items else None

    def retitle(self, broadcast_id: str, title: str, description: str | None = None) -> bool:
        """Patch title/description in place on a LIVE broadcast.

        snippet.scheduledStartTime is mandatory on a snippet update — omitting it
        is rejected — so we read the current snippet back first.
        """
        cur = self.get_broadcast(broadcast_id)
        if not cur:
            log.warning("retitle: broadcast %s vanished", broadcast_id)
            return False
        snip = cur["snippet"]
        body = {
            "id": broadcast_id,
            "snippet": {
                "title": title[:100],
                "description": (description if description is not None
                                else snip.get("description", ""))[:5000],
                "scheduledStartTime": snip["scheduledStartTime"],
            },
        }
        self.svc.liveBroadcasts().update(part="snippet", body=body).execute()
        self._spend(COST_WRITE)
        log.info("retitled %s -> %s", broadcast_id, title)
        return True

    def set_video_meta(self, video_id: str, tags: list[str] | None = None) -> None:
        """Category + tags live on the video resource, not the broadcast."""
        try:
            r = self.svc.videos().list(part="snippet", id=video_id).execute()
            self._spend(COST_LIST)
            items = r.get("items") or []
            if not items:
                return
            snip = items[0]["snippet"]
            snip["categoryId"] = str(self.cfg.youtube.category_id)
            if tags:
                snip["tags"] = tags[:30]
            self.svc.videos().update(
                part="snippet", body={"id": video_id, "snippet": snip}).execute()
            self._spend(COST_WRITE)
        except HttpError as e:
            log.warning("set_video_meta failed (non-fatal): %s", e)

    def set_thumbnail(self, video_id: str, path) -> bool:
        """Upload a custom thumbnail. -> True if YouTube accepted it.

        Costs 50 units, and needs a VERIFIED channel: an unverified one is
        rejected outright. Both are reasons this must never be able to break a
        broadcast that is already live, so every failure is logged and
        swallowed -- the file is on disk either way and can be set by hand.
        """
        from pathlib import Path

        p = Path(path)
        if not p.is_file():
            return False
        try:
            from googleapiclient.http import MediaFileUpload

            self.svc.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(p), mimetype="image/jpeg"),
            ).execute()
            self._spend(COST_THUMBNAIL)
            log.info("thumbnail set on %s (%s)", video_id, p.name)
            return True
        except HttpError as e:
            # 403 here is nearly always "channel not eligible for custom
            # thumbnails" rather than an auth problem, so say so plainly.
            hint = ""
            if getattr(e, "status_code", None) == 403 or "403" in str(e):
                hint = (" - the channel may not be verified for custom "
                        "thumbnails; the image is still saved on disk")
            log.warning("thumbnail upload failed%s: %s", hint, e)
        except Exception as e:  # noqa: BLE001
            log.warning("thumbnail upload failed: %s", e)
        return False

    def live_details(self, broadcast_id: str | None) -> dict:
        """Viewers + likes + views + the chat id, in ONE 1-unit call.

        Cheaper than asking for each separately, which is why the chat id is
        fetched here rather than on demand.
        """
        out: dict = {"viewers": None, "likes": None, "views": None, "chat_id": None}
        if not broadcast_id:
            return out
        try:
            r = self.svc.videos().list(
                part="liveStreamingDetails,statistics", id=broadcast_id).execute()
            self._spend(COST_LIST)
            items = r.get("items") or []
            if not items:
                return out
            lsd = items[0].get("liveStreamingDetails", {}) or {}
            stats = items[0].get("statistics", {}) or {}
            def _int(v):
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return None
            out["viewers"] = _int(lsd.get("concurrentViewers"))
            out["chat_id"] = lsd.get("activeLiveChatId")
            out["likes"] = _int(stats.get("likeCount"))
            out["views"] = _int(stats.get("viewCount"))
        except HttpError as e:
            log.debug("live_details failed: %s", e)
        return out

    # kept for callers that only want the number
    def viewer_count(self, broadcast_id: str | None) -> int | None:
        return self.live_details(broadcast_id)["viewers"]

    def chat_messages(self, chat_id: str | None, page_token: str | None = None):
        """(messages, next_page_token, polling_interval_ms). 1 unit per call."""
        if not chat_id:
            return [], None, 5000
        try:
            req = self.svc.liveChatMessages().list(
                liveChatId=chat_id, part="snippet,authorDetails",
                maxResults=50, pageToken=page_token or None)
            r = req.execute()
            self._spend(COST_LIST)
        except HttpError as e:
            # 403/404 here usually means chat ended or is disabled - back off
            log.debug("chat_messages failed: %s", e)
            return [], page_token, 15000

        msgs = []
        for it in r.get("items", []):
            sn = it.get("snippet", {}) or {}
            au = it.get("authorDetails", {}) or {}
            text = sn.get("displayMessage") or ""
            if not text:
                continue
            msgs.append({
                "id": it.get("id"),
                "author": au.get("displayName", "?"),
                "text": text,
                "owner": bool(au.get("isChatOwner")),
                "mod": bool(au.get("isChatModerator")),
                "at": sn.get("publishedAt"),
            })
        return (msgs, r.get("nextPageToken"),
                int(r.get("pollingIntervalMillis") or 5000))

    def send_chat(self, chat_id: str | None, text: str) -> bool:
        """Post a message as the channel owner. 50 units."""
        if not chat_id or not text.strip():
            return False
        try:
            self.svc.liveChatMessages().insert(part="snippet", body={
                "snippet": {
                    "liveChatId": chat_id,
                    "type": "textMessageEvent",
                    "textMessageDetails": {"messageText": text[:200]},
                }}).execute()
            self._spend(COST_WRITE)
            log.info("chat sent: %s", text[:60])
            return True
        except HttpError as e:
            log.warning("send_chat failed: %s", e)
            return False

    def delete_broadcast(self, broadcast_id: str) -> None:
        try:
            self.svc.liveBroadcasts().delete(id=broadcast_id).execute()
            self._spend(COST_WRITE)
        except HttpError as e:
            log.warning("delete_broadcast failed: %s", e)

    # ---------------- recovery ----------------

    def sweep_orphans(self, keep: str | None = None) -> int:
        """Complete any broadcast still marked active/testing after a crash."""
        killed = 0
        for status in ("active", "testing"):
            try:
                r = self.svc.liveBroadcasts().list(
                    part="id,snippet,status", broadcastStatus=status,
                    broadcastType="all", maxResults=50).execute()
                self._spend(COST_LIST)
            except HttpError as e:
                log.warning("orphan sweep list failed: %s", e)
                continue
            for item in r.get("items") or []:
                bid = item["id"]
                if keep and bid == keep:
                    continue
                log.warning("orphan broadcast %s (%s) — completing",
                            bid, item["snippet"].get("title"))
                try:
                    self.transition(bid, "complete")
                    killed += 1
                except HttpError as e:
                    log.warning("could not complete orphan %s: %s", bid, e)
        return killed

    @staticmethod
    def watch_url(broadcast_id: str) -> str:
        return f"https://www.youtube.com/watch?v={broadcast_id}"
