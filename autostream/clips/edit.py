"""Re-render ONE clip that has already been cut.

WHY THIS EXISTS SEPARATELY FROM jobs.py
    A clip job is a pipeline over a whole recording: scan, plan, cut, caption,
    speak, join. Changing the caption on clip four does not need any of that,
    and rerunning the job to get it would re-encode nine clips that were
    already right -- three minutes of work to change six words.

    So this does the last few steps for a single clip, from the recording and
    the plan that produced it. The plan is read back out of session.json, which
    is why the folder is the real record of a run rather than a by-product.

WHAT CAN CHANGE
    The caption, the spoken line and its voice, whether the vertical is cropped
    or fitted, and the in and out points. Everything else about the clip -- how
    it was found, where it sits in the ranking, what it is called -- belongs to
    the run and is left alone.

ONE AT A TIME
    Encoding is the expensive thing on this machine and a clip job may be
    running too, so an edit takes a slot rather than a thread pool. The UI
    disables the button while one is in flight.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import cutter, overlay, plan, voice

log = logging.getLogger("autostream.clips.edit")


@dataclass
class Spec:
    """What to change about one clip. Anything left None is left alone."""
    folder: Path
    name: str                        # the clip's plan name, without extension
    caption: bool | None = None
    caption_text: str | None = None
    speak: bool | None = None
    voice_text: str | None = None
    voice_name: str | None = None
    vertical_mode: str | None = None
    trim_start: float | None = None   # seconds INTO the clip
    trim_end: float | None = None     # seconds into the clip, from its start


@dataclass
class Result:
    ok: bool
    error: str = ""
    vertical: str = ""
    master: str = ""
    caption: str = ""
    said: str = ""
    duration: float = 0.0


def _session(folder: Path) -> dict:
    f = folder / "session.json"
    if not f.exists():
        raise FileNotFoundError("that run has no session.json, so its plan is gone")
    return json.loads(f.read_text(encoding="utf-8"))


def _find(data: dict, name: str) -> dict:
    for p in data.get("plans") or []:
        if p.get("name") == name:
            return p
    for p in data.get("promo_clips") or []:
        if p.get("name") == name:
            return p
    raise KeyError(f"no clip called {name!r} in this run")


def recut(spec: Spec) -> Result:
    """Apply `spec` to one clip. -> what it now is."""
    data = _session(spec.folder)
    row = _find(data, spec.name)
    source = Path(data.get("source") or "")
    if not source.exists():
        return Result(False, error=f"the recording is gone: {source}")

    opt = data.get("options") or {}
    enc = str(opt.get("encoder", "auto"))
    handle = str(opt.get("handle") or "@YuvaNeta")
    mode = spec.vertical_mode or str(opt.get("vertical_mode") or "crop")

    # The in and out points are measured from the clip, not from the recording,
    # because that is what a viewer of the clip can see and reason about.
    was_start, was_end = float(row["start"]), float(row["end"])
    start = was_start + max(0.0, float(spec.trim_start or 0.0))
    end = (was_start + float(spec.trim_end)
           if spec.trim_end is not None else was_end)
    if end - start < 1.0:
        return Result(False, error="a clip has to be at least a second long")

    kills = [k for k in (data.get("kills") or [])
             if start <= float(k["time"]) <= end]
    fresh = plan.ClipPlan(
        rank=int(row.get("rank", 1)), start=start, end=end,
        kills=len(kills) or int(row.get("kills", 0)),
        burst_kills=int(row.get("burst_kills", 0)),
        peak_score=float(row.get("score", 0.0) or 0.0),
        name=spec.name,
        labels=list(row.get("labels") or []),
        round_number=row.get("round"),
        won=row.get("won"))

    # ---- the caption
    want_cap = opt.get("captions", True) if spec.caption is None else spec.caption
    caption = ""
    if want_cap:
        caption = (spec.caption_text or "").strip() or \
            overlay.caption_for(fresh, kills, list(row.get("tags") or []))

    # ---- the spoken line
    want_say = bool(opt.get("voice")) if spec.speak is None else spec.speak
    said, speech = "", None
    if want_say:
        said = (spec.voice_text or "").strip() or voice.line_for(fresh)
        if said and voice.available():
            # The wav lands beside the vertical, and the speech is synthesised
            # BEFORE the re-cut -- so on a clip that has no vertical yet the
            # directory does not exist and the write fails, losing the line for
            # a reason that has nothing to do with speech.
            (spec.folder / "vertical").mkdir(parents=True, exist_ok=True)
            try:
                speech = voice.say(
                    said, spec.folder / "vertical" / f"{spec.name}.hook.wav",
                    voice=(spec.voice_name or str(opt.get("voice_name") or "")
                           or voice.VOICE))
            except Exception as e:                     # noqa: BLE001
                log.warning("could not say %r: %s", said, e)
                said, speech = "", None
        elif said:
            log.info("no spoken hook: %s", voice.why_not())
            said = ""

    # ---- re-cut, from the recording. The master is re-made because a trim
    # changes it, and because deriving the vertical from a stale master would
    # silently keep the old in-point.
    master = cutter.master(source, fresh, spec.folder / "clips", encoder=enc)
    vert = cutter.vertical(master, spec.folder / "vertical", mode=mode,
                           encoder=enc)
    if vert is None:
        return Result(True, master=str(master), caption=caption,
                      duration=end - start)

    if caption:
        tmp = vert.with_suffix(".tmp.mp4")
        try:
            overlay.apply(vert, tmp, caption=caption, handle=handle,
                          encoder=enc, subtitle=said,
                          subtitle_until=(voice.LEAD_IN + speech.duration
                                          if speech else 0.0))
            vert.unlink(missing_ok=True)
            tmp.rename(vert)
        except Exception as e:                          # noqa: BLE001
            log.warning("could not caption %s: %s", vert.name, e)
            tmp.unlink(missing_ok=True)

    if speech:
        if not voice.lay_over(vert, speech):
            said = ""
        speech.path.unlink(missing_ok=True)

    log.info("re-cut %s: %s, caption %r%s", spec.name, mode, caption,
             f", says {said!r}" if said else "")
    return Result(True, vertical=str(vert), master=str(master),
                  caption=caption, said=said, duration=end - start)


def apply_to_manifest(folder: Path, res: Result, name: str) -> None:
    """Write the new caption and spoken line back into clips.json.

    The manifest is what the Clips page and the uploader read, so an edit that
    only changed the file would show the old caption next to the new video.
    """
    f = folder / "clips.json"
    if not f.exists():
        return
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    rows = data if isinstance(data, list) else (data.get("clips") or [])
    for row in rows:
        if Path(str(row.get("vertical") or "")).stem == f"{name}_vertical" \
                or Path(str(row.get("master") or "")).stem == name:
            row["caption"] = res.caption
            row["said"] = res.said
            if res.duration:
                row["duration"] = round(res.duration, 2)
            break
    try:
        f.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as e:
        log.warning("could not update %s: %s", f.name, e)


class Editor:
    """One edit at a time, with a snapshot the page can poll."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.state = "idle"          # idle|running|done|failed
        self.name = ""
        self.error = ""
        self.result: dict[str, Any] = {}
        self.started_at = 0.0

    def busy(self) -> bool:
        with self._lock:
            t = self._thread
        return bool(t and t.is_alive())

    def start(self, spec: Spec) -> bool:
        if self.busy():
            return False
        with self._lock:
            self.state, self.name, self.error = "running", spec.name, ""
            self.result, self.started_at = {}, time.time()
            self._thread = threading.Thread(
                target=self._run, args=(spec,), name="autostream-edit",
                daemon=True)
            self._thread.start()
        return True

    def _run(self, spec: Spec) -> None:
        try:
            res = recut(spec)
        except Exception as e:                          # noqa: BLE001
            log.exception("edit failed: %s", e)
            with self._lock:
                self.state, self.error = "failed", str(e)
            return
        if not res.ok:
            with self._lock:
                self.state, self.error = "failed", res.error
            return
        apply_to_manifest(spec.folder, res, spec.name)
        with self._lock:
            self.state = "done"
            self.result = {"vertical": res.vertical, "master": res.master,
                           "caption": res.caption, "said": res.said,
                           "duration": round(res.duration, 2)}

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self.state, "name": self.name,
                    "error": self.error, "result": dict(self.result),
                    "elapsed": int(time.time() - self.started_at)
                    if self.started_at else 0}


_EDITOR = Editor()


def editor() -> Editor:
    return _EDITOR
