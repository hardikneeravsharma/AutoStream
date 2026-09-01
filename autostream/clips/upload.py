r"""Publishing finished clips to YouTube as Shorts.

NOTHING UPLOADS BY ITSELF
    Recording and clipping are safe to automate because they are local.
    Publishing is not: it is public, attributed and awkward to undo. So an
    upload happens because a person pressed a button, never because a session
    ended -- the same rule as the twenty-second cancel window before a stream
    goes live. There is deliberately no auto_upload setting.

WHY A SECOND RUNNER
    A clip cut and an upload have nothing to fight over -- one saturates the
    GPU encoder, the other the uplink -- so they run on separate runners and
    report separately. Sharing one would mean that cutting a reel blocked
    publishing the last one for twenty minutes.

WHAT MAKES A SHORT A SHORT
    Since October 2024: vertical or square, three minutes or under, and
    YouTube classifies it itself. The verticals this app already writes qualify
    on both counts, so nothing is re-encoded and "#Shorts" is NOT bolted onto
    the title -- it has not been required for years and reads as superstition.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from .. import atomic

log = logging.getLogger("autostream.clips.upload")

STEPS = ("check", "upload", "verify")


def render(template: str, tokens: dict, *, limit: int) -> str:
    """Fill a template, then hard-cap it.

    Capped HERE rather than by YouTube: an over-long title makes YouTube reject
    the whole request, and it does that only after the file has finished
    uploading. Trimmed on a word boundary where there is one, because a title
    cut mid-word looks like a bug to everybody who sees it.
    """
    out = str(template or "")
    for key, value in tokens.items():
        out = out.replace("{" + key + "}", str(value if value is not None else ""))
    out = " ".join(out.split())
    # A template whose caption token came back empty leaves its separator
    # stranded at the front: "- Counter-Strike 2".
    for junk in ("- ", "| ", ": "):
        while out.startswith(junk):
            out = out[len(junk):].lstrip()
    if len(out) <= limit:
        return out
    cut = out[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit * 0.6 else cut).rstrip(" -|,")


class _Refused(RuntimeError):
    """A batch that must not start. Its message is shown to the user as-is."""


class UploadJob:
    """One batch of clips, uploaded one at a time. ClipJob's contract."""

    def __init__(self, clips: list[dict], *, yt, game: str, folder: Path,
                 privacy: str = "unlisted", title_template: str = "",
                 description_template: str = "", tags=None,
                 daily_max: int = 5, channel: str = ""):
        self.clips = list(clips)
        self.yt = yt
        self.game = game or "Session"
        self.folder = Path(folder)
        self.privacy = privacy
        self.title_template = title_template or "{caption} - {game}"
        self.description_template = description_template or ""
        self.tags = list(tags or [])
        self.daily_max = int(daily_max)
        self.channel = channel

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.state = "queued"
        self.step = "check"
        self.done = 0
        self.total = len(self.clips)
        self.message = ""
        self.error = ""
        self.results: list[dict] = []
        self.failures: list[dict] = []
        self.chunk = 0.0
        self.started_at = time.time()
        self.finished_at: float | None = None

    # ---------------- state ----------------

    def _set(self, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def cancel(self) -> None:
        self._stop.set()

    def cancelled(self) -> bool:
        return self._stop.is_set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            # Per-chunk progress folded into the count, so the meter moves
            # during one large clip instead of sitting still for a minute.
            done = self.done + (self.chunk if self.state == "running" else 0.0)
            pct = int(100 * done / self.total) if self.total else 0
            return {
                "state": self.state,
                "step": self.step,
                "step_index": STEPS.index(self.step) if self.step in STEPS else 0,
                "done": self.done,
                "total": self.total,
                "percent": max(0, min(100, pct)),
                "message": self.message,
                "error": self.error,
                "game": self.game,
                "folder": str(self.folder),
                "uploaded": list(self.results),
                "failed": list(self.failures),
                "elapsed": int(time.time() - self.started_at),
            }

    # ---------------- the run ----------------

    def run(self) -> None:
        try:
            self._set(state="running", step="check")
            self._check()
            self._upload_all()
            if self.state == "cancelled":
                return
            self._record()
            self._set(state="done", step="verify", done=len(self.results),
                      message=self._summary())
        except _Refused as e:
            self._set(state="failed", error=str(e), message=str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("upload job failed")
            self._set(state="failed", error=str(e), message="Failed - see the log")
        finally:
            self._set(finished_at=time.time(), chunk=0.0)

    def _check(self) -> None:
        """Refuse before anything uploads, so a batch cannot die half-published."""
        from ..youtube import UPLOAD_COST

        if not self.clips:
            raise _Refused("Nothing selected to upload.")
        if self.daily_max <= 0:
            raise _Refused("Uploading is switched off: uploads per day is 0 in "
                           "Settings.")
        if len(self.clips) > self.daily_max:
            raise _Refused(
                f"{len(self.clips)} clips selected, but the limit is "
                f"{self.daily_max} a day. Select fewer, or raise the limit in "
                f"Settings.")
        need = UPLOAD_COST * len(self.clips)
        left = self.yt.quota_left()
        if left < need:
            raise _Refused(
                f"That needs about {need} units of YouTube quota and only "
                f"{left} are left today. The quota resets at midnight Pacific.")

    def _upload_all(self) -> None:
        self._set(step="upload")
        for i, clip in enumerate(self.clips, 1):
            if self.cancelled():
                self._set(state="cancelled", message="Cancelled")
                return
            path = Path(clip.get("path") or "")
            name = path.name or f"clip {i}"
            if not path.is_file():
                # Skipped, never fatal: the rest of the batch is still good.
                self.failures.append({"name": name, "error": "The file is gone."})
                log.warning("upload: %s is missing, skipping", path)
                continue
            if clip.get("video_id"):
                self.failures.append({
                    "name": name,
                    "error": "Already uploaded. Delete it on YouTube first if "
                             "you meant to replace it."})
                continue

            title, description = self._text_for(clip, i)
            self._set(message=f"Uploading {name}", chunk=0.0)
            try:
                got = self.yt.upload_video(
                    path, title=title, description=description,
                    privacy=self.privacy, tags=self.tags,
                    category_id=str(getattr(self.yt.cfg.youtube,
                                            "category_id", "20")),
                    on_progress=lambda f: self._set(chunk=max(0.0, min(1.0, f))),
                    should_stop=self.cancelled)
            except Exception as e:  # noqa: BLE001
                if self.cancelled():
                    self._set(state="cancelled", message="Cancelled")
                    return
                # One clip failing keeps the successes and names the casualty.
                self.failures.append({"name": name, "error": str(e)[:200]})
                log.warning("upload of %s failed: %s", name, e)
                continue
            got["name"] = name
            got["source"] = str(path)
            self.results.append(got)
            self._set(done=len(self.results), chunk=0.0)

    def _text_for(self, clip: dict, n: int) -> tuple[str, str]:
        from ..youtube import DESCRIPTION_MAX, TITLE_MAX

        caption = str(clip.get("caption") or "").strip()
        kills = clip.get("kills")
        tokens = {
            "caption": caption,
            "game": self.game,
            "kills": kills if kills is not None else "",
            "at": clip.get("at") or "",
            "channel": self.channel,
            "date": time.strftime("%d %b %Y"),
            "n": n,
        }
        title = render(self.title_template, tokens, limit=TITLE_MAX)
        if not title:
            # Every fallback still names the game: a title that is only a
            # number is worse than having no template at all.
            title = (f"{kills} kills - {self.game}" if kills
                     else f"{self.game} highlight")[:TITLE_MAX]
        return title, render(self.description_template, tokens,
                             limit=DESCRIPTION_MAX)

    def _record(self) -> None:
        """Write the ids back into the run's clips.json.

        So the page can show links, and so uploading the same clip twice is
        recognised as the duplicate it is rather than quietly publishing again.
        """
        self._set(step="verify")
        manifest = self.folder / "clips.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        rows = data.get("clips") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return
        by_path = {r["source"]: r for r in self.results if r.get("source")}
        for row in rows:
            got = by_path.get(str(row.get("path") or ""))
            if got:
                row["video_id"] = got["id"]
                row["url"] = got["url"]
                row["shorts_url"] = got["shorts_url"]
        try:
            # THE MOST IMPORTANT ONE. This is where the YouTube ids of
            # clips already uploaded are written back. A truncated write here
            # means the app forgets what went up, and the next batch sends the
            # same clips to the channel AGAIN.
            atomic.write_json(manifest, data)
        except OSError as e:
            log.warning("could not record the upload ids: %s", e)

    def _summary(self) -> str:
        n = len(self.results)
        out = f"{n} clip{'s' if n != 1 else ''} uploaded"
        if self.failures:
            out += f", {len(self.failures)} skipped"
        return out


class UploadRunner:
    """One batch at a time, kept apart from the cutting runner."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current: UploadJob | None = None
        self.last: UploadJob | None = None

    def busy(self) -> bool:
        with self._lock:
            return (self.current is not None
                    and self.current.state in ("queued", "running"))

    def start(self, job: UploadJob) -> bool:
        with self._lock:
            if self.current is not None and self.current.state in ("queued", "running"):
                return False
            self.current = job
        threading.Thread(target=self._run, args=(job,),
                         name="autostream-upload", daemon=True).start()
        return True

    def _run(self, job: UploadJob) -> None:
        try:
            job.run()
        finally:
            with self._lock:
                self.last = job
                if self.current is job:
                    self.current = None

    def cancel(self) -> bool:
        with self._lock:
            job = self.current
        if job is None:
            return False
        job.cancel()
        return True

    def status(self) -> dict | None:
        with self._lock:
            job = self.current or self.last
        return job.snapshot() if job else None


_runner: UploadRunner | None = None


def runner() -> UploadRunner:
    """The process-wide UploadRunner. Created on first use."""
    global _runner
    if _runner is None:
        _runner = UploadRunner()
    return _runner
