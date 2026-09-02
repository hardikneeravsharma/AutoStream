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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .. import atomic
from . import cutter, effects as fx, overlay, plan, voice

log = logging.getLogger("autostream.clips.edit")

# Two different floors, because keeping and removing are not symmetrical.
#
# A removal shorter than MIN_REMOVAL is not worth splitting a clip in two for:
# it would cost an extra encode and a join to take out three frames nobody can
# see. It is treated as though it had not been asked for.
#
# A surviving piece shorter than MIN_PIECE is not footage, it is a flash. Two
# half-second fragments joined together satisfy any "the clip is at least a
# second long" rule while being unwatchable, so short pieces are discarded
# outright -- and if that leaves nothing, the edit is refused.
MIN_REMOVAL = 0.2
MIN_PIECE = 1.0


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

    # In and out measured in RECORDING seconds, which is the only way to ask
    # for more than the clip already contains. trim_start/trim_end can only
    # ever shrink what was cut; these can start the clip earlier and end it
    # later, bounded by the recording itself.
    start_at: float | None = None
    end_at: float | None = None
    # Stretches to take OUT of the middle, also in recording seconds. The
    # remaining pieces are joined in order, so the dead half-minute between
    # two fights can come out and leave one clip rather than two.
    drop: list[tuple[float, float]] | None = None

    # Captions, punch-ins, freezes and sounds a person placed by hand, in
    # seconds into the FINISHED VERTICAL -- which is what the player shows, so
    # it is the only timeline they can point at. Built at the API boundary so
    # nothing further in has to parse anything.
    effects: "fx.Effects | None" = None


@dataclass
class Result:
    ok: bool
    error: str = ""
    vertical: str = ""
    master: str = ""
    caption: str = ""
    said: str = ""
    duration: float = 0.0
    spans: list[tuple[float, float]] = field(default_factory=list)
    removed: float = 0.0             # seconds taken out of the middle
    # The vertical can be LONGER than the master: a freeze holds a frame, and
    # effects are applied to the vertical alone. Reported separately because
    # `duration` is what was cut out of the recording and this is what plays.
    vertical_seconds: float = 0.0
    effects: dict = field(default_factory=dict)


def _session(folder: Path) -> dict:
    f = folder / "session.json"
    if not f.exists():
        raise FileNotFoundError("that run has no session.json, so its plan is gone")
    return json.loads(f.read_text(encoding="utf-8"))


def current(folder: Path, name: str) -> dict | None:
    """What the clip is NOW, from the manifest, if it has been edited before.

    session.json holds the plan the run produced and never changes -- it is
    the record of what the detector found. clips.json holds what the clips
    have since become. Editing has to start from the second, or every edit
    silently reverts the one before it.
    """
    f = folder / "clips.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = data if isinstance(data, list) else (data.get("clips") or [])
    for row in rows:
        if not row.get("edited"):
            continue
        if Path(str(row.get("vertical") or "")).stem == f"{name}_vertical" \
                or Path(str(row.get("master") or "")).stem == name:
            return row
    return None


def _find(data: dict, name: str) -> dict:
    for p in data.get("plans") or []:
        if p.get("name") == name:
            return p
    for p in data.get("promo_clips") or []:
        if p.get("name") == name:
            return p
    raise KeyError(f"no clip called {name!r} in this run")


def to_manifest(e: "fx.Effects") -> dict:
    """An Effects -> plain JSON for clips.json."""
    return {
        "captions": [{"text": c.text, "at": round(c.at, 3),
                      "until": round(c.until, 3), "where": c.where,
                      "size": c.size} for c in e.captions],
        "zooms": [{"at": round(z.at, 3), "until": round(z.until, 3),
                   "to": z.to} for z in e.zooms],
        "freezes": [{"at": round(f.at, 3), "seconds": f.seconds}
                    for f in e.freezes],
        "sounds": [{"path": str(s.path), "at": round(s.at, 3),
                    "gain": s.gain} for s in e.sounds],
    }


def from_manifest(d: dict) -> "fx.Effects":
    """...and back. Anything unreadable is dropped rather than raised on.

    This reads what a PREVIOUS run wrote, so a bad value here is a bug in this
    app, not a person making a mistake -- and refusing to edit a clip because
    its own record is malformed helps nobody. What arrives from the page is
    checked properly, at the boundary, where a person can be told.
    """
    def num(v, fallback=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return fallback

    d = d or {}
    return fx.Effects(
        captions=[fx.Caption(text=str(c.get("text") or ""), at=num(c.get("at")),
                             until=num(c.get("until"), 3.0),
                             where=str(c.get("where") or "top"),
                             size=num(c.get("size"), 1.0))
                  for c in (d.get("captions") or []) if isinstance(c, dict)],
        zooms=[fx.Zoom(at=num(z.get("at")), until=num(z.get("until"), 2.0),
                       to=num(z.get("to"), 1.35))
               for z in (d.get("zooms") or []) if isinstance(z, dict)],
        freezes=[fx.Freeze(at=num(f.get("at")), seconds=num(f.get("seconds"), 0.7))
                 for f in (d.get("freezes") or []) if isinstance(f, dict)],
        sounds=[fx.Sound(path=Path(str(s.get("path") or "")), at=num(s.get("at")),
                         gain=num(s.get("gain"), 1.0))
                for s in (d.get("sounds") or []) if isinstance(s, dict)],
    )


def keep_spans(start: float, end: float,
               drop: list[tuple[float, float]] | None) -> list[tuple[float, float]]:
    """[start, end] with `drop` taken out of it. -> the pieces that survive.

    Overlapping and out-of-order removals are normalised rather than rejected:
    a person dragging two handles over the same second means "take this out",
    not "here is a malformed request". Slivers are
    Pieces shorter than MIN_PIECE are discarded and removals shorter than
    MIN_REMOVAL are ignored -- see those two constants for why the floors
    differ.
    """
    ranges = []
    for a, b in (drop or []):
        a, b = float(a), float(b)
        if b < a:
            a, b = b, a
        a, b = max(a, start), min(b, end)
        # A removal too short to see is not worth splitting a clip in two for:
        # it would cost an extra encode and a join to take out three frames.
        if b - a >= MIN_REMOVAL:
            ranges.append((a, b))
    ranges.sort()

    merged: list[list[float]] = []
    for a, b in ranges:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])

    spans, at = [], start
    for a, b in merged:
        if a - at >= MIN_PIECE:
            spans.append((at, a))
        at = max(at, b)
    if end - at >= MIN_PIECE:
        spans.append((at, end))
    return spans


def _source_seconds(data: dict, source: Path) -> float:
    """How long the recording is, so an out-point cannot run off the end."""
    for key in ("recording_seconds", "source_seconds", "duration"):
        try:
            got = float(data.get(key) or 0.0)
        except (TypeError, ValueError):
            got = 0.0
        if got > 0:
            return got
    try:
        info = cutter.probe_source(source)
        return float(info.get("duration") or 0.0)
    except Exception:                                   # noqa: BLE001
        return 0.0


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

    # Two ways of saying where the clip begins and ends. start_at/end_at are
    # recording seconds and can reach OUTSIDE what was originally cut, which
    # is what asking for a run-up means. trim_start/trim_end are the older
    # form, measured from the clip, and can only ever shrink it.
    # Where the clip currently begins and ends -- which is what a previous
    # edit left it as, if there was one, and the original plan otherwise.
    now = current(spec.folder, spec.name) or row
    was_start, was_end = float(now["start"]), float(now["end"])
    # Removals made last time are still removals, unless this edit replaces
    # them. Otherwise saving a new caption would put the dull middle back.
    if spec.drop is None and now.get("drop"):
        spec = replace(spec, drop=[(float(a), float(b))
                                   for a, b in now["drop"]])
    # Same reasoning as the removals: an edit that says nothing about the
    # effects means "leave them", not "throw them away". Fixing a typo in a
    # caption must not delete the freeze somebody placed last time.
    if spec.effects is None and now.get("effects"):
        spec = replace(spec, effects=from_manifest(now["effects"]))
    if spec.start_at is not None:
        start = float(spec.start_at)
    else:
        start = was_start + max(0.0, float(spec.trim_start or 0.0))
    if spec.end_at is not None:
        end = float(spec.end_at)
    elif spec.trim_end is not None:
        end = was_start + float(spec.trim_end)
    else:
        end = was_end

    # Bounded by the recording, not by the original clip. Asking for four
    # seconds of run-up on a clip that starts three seconds into the file
    # gets three, rather than an error about a negative timestamp.
    limit = _source_seconds(data, source)
    start = max(0.0, start)
    if limit > 0:
        end = min(end, limit)
    if end - start < 1.0:
        return Result(False, error="a clip has to be at least a second long")

    spans = keep_spans(start, end, spec.drop)
    kept = sum(b - a for a, b in spans)
    if not spans or kept < 1.0:
        return Result(False, error="that removes almost the whole clip")
    removed = (end - start) - kept

    # Checked BEFORE anything is encoded. fx.apply checks again on the real
    # file, but by then a minute of encoding has been spent to be told that a
    # caption is past the end of the clip -- which is knowable right here.
    if spec.effects is not None and spec.effects.any():
        wrong = fx.problems(spec.effects, kept)
        if wrong:
            return Result(False, error=" ".join(wrong))

    kills = [k for k in (data.get("kills") or [])
             if any(a <= float(k["time"]) <= b for a, b in spans)]
    # The plan describes the clip as it will EXIST, so its length is what
    # survives the removals: a caption claiming forty seconds on a clip that
    # is now twelve is worse than no caption.
    fresh = plan.ClipPlan(
        rank=int(row.get("rank", 1)), start=start, end=start + kept,
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
        # AN EMPTY BOX MEANS NO CAPTION, NOT "PICK ONE FOR ME".
        #
        # This used to be `text.strip() or caption_for(...)`, which reads
        # nicely and is wrong: clearing the caption and re-rendering put the
        # app's own caption straight back, so the words somebody had just
        # deleted reappeared burnt into the clip. Nothing distinguished that
        # from the feature simply not working.
        #
        # None and "" are different answers. None is a caller that said
        # nothing about the caption -- the first cut of a clip, or an edit
        # that only touches the trim -- and that is when choosing one is
        # wanted. "" is a person who cleared the box.
        if spec.caption_text is None:
            caption = overlay.caption_for(fresh, kills,
                                          list(row.get("tags") or []))
        else:
            caption = spec.caption_text.strip()

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
    master = cutter.master_segments(source, spans, spec.name,
                                    spec.folder / "clips", encoder=enc)
    vert = cutter.vertical(master, spec.folder / "vertical", mode=mode,
                           encoder=enc)
    if vert is None:
        # No vertical to put anything on. Effects belong to the export, so
        # asking for both is asking for two things that cannot both happen --
        # said out loud rather than rendered without them, because a freeze
        # that quietly did not occur is indistinguishable from one that did
        # not save.
        if spec.effects is not None and spec.effects.any():
            return Result(False, error="Effects go on the vertical export, and "
                                       "this clip is set to make none. Choose "
                                       "a vertical framing, or remove the "
                                       "effects.")
        return Result(True, master=str(master), caption=caption,
                      duration=kept, spans=spans, removed=removed)

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

    # LAST, on the finished vertical. Everything the app adds by itself --
    # branding, the caption it wrote, the spoken hook -- is already in place,
    # so what a person places lands on top of what they were actually looking
    # at in the player. Any other order would mean effect times referred to a
    # version of the clip that was never on screen.
    vert_seconds = kept
    applied: dict = {}
    if spec.effects is not None:
        # Written whether or not there are any. An empty SHAPE means "none on
        # this clip"; a missing key means "nobody has said". Collapsing the
        # two would make removing the last effect indistinguishable from never
        # having had one, and the next edit would put it back.
        applied = to_manifest(spec.effects)
    if spec.effects is not None and spec.effects.any():
        try:
            fx.apply(vert, vert, spec.effects, encoder=enc)
            vert_seconds = fx.output_seconds(kept, spec.effects.freezes)
        except ValueError as e:
            return Result(False, error=str(e))
        except Exception as e:                          # noqa: BLE001
            log.exception("effects failed on %s", spec.name)
            return Result(False, error=f"The effects could not be applied: {e}")

    log.info("re-cut %s: %.1fs of recording %.1f-%.1f%s, %s, caption %r%s",
             spec.name, kept, start, end,
             f", less {removed:.1f}s in {len(spans) - 1} cut" if removed else "",
             mode, caption, f", says {said!r}" if said else "")
    return Result(True, vertical=str(vert), master=str(master),
                  caption=caption, said=said, duration=kept,
                  spans=spans, removed=removed,
                  vertical_seconds=vert_seconds, effects=applied)


def apply_to_manifest(folder: Path, res: Result, name: str) -> None:
    """Write what the clip has BECOME back into clips.json.

    The manifest is what the Clips page and the uploader read, so an edit that
    only changed the file would show the old caption next to the new video.

    The span matters just as much. Without it the second edit of a clip starts
    from the original cut again: adding two seconds of run-up and then coming
    back to add two more would quietly throw the first two away, and changing
    only the caption afterwards would revert the trim entirely. The manifest
    is where "what this clip is now" lives, so that is where it is recorded.
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
            # Written even when empty, so clearing every effect is recorded
            # as "none" rather than read back as "unchanged" next time.
            row["effects"] = res.effects
            if res.vertical_seconds:
                row["vertical_seconds"] = round(res.vertical_seconds, 2)
            if res.spans:
                row["start"] = round(res.spans[0][0], 3)
                row["end"] = round(res.spans[-1][1], 3)
                # The gaps between the pieces, which is what was taken out.
                # Kept so the page can show them again and the next edit can
                # start from what the clip is rather than what it was.
                row["drop"] = [[round(a[1], 3), round(b[0], 3)]
                               for a, b in zip(res.spans, res.spans[1:])]
                row["edited"] = True
            break
    try:
        atomic.write_json(f, data)
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
                           "duration": round(res.duration, 2),
                           "removed": round(res.removed, 2),
                           "pieces": len(res.spans),
                           # Where the clip now sits in the recording, so the
                           # page can carry on editing from what it has become
                           # rather than from what the run originally cut.
                           "start": round(res.spans[0][0], 3) if res.spans else 0,
                           "end": round(res.spans[-1][1], 3) if res.spans else 0,
                           "drop": [[round(a[1], 3), round(b[0], 3)]
                                    for a, b in zip(res.spans, res.spans[1:])],
                           "effects": res.effects,
                           "vertical_seconds": round(res.vertical_seconds, 2)}

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self.state, "name": self.name,
                    "error": self.error, "result": dict(self.result),
                    "elapsed": int(time.time() - self.started_at)
                    if self.started_at else 0}


_EDITOR = Editor()


def editor() -> Editor:
    return _EDITOR
