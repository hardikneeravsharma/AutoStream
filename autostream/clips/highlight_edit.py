"""The stream highlight, opened again: its cut list as a project the page edits.

WHY THIS EXISTS
    The player approved the stream highlight (stream_highlight.py, v2.8.0) and asked
    for it to open "in a timeline with editing options other than the song reel
    edit": which moments to keep, the facecam area, the facecam zoom, and the
    automatic captions. What he would change before uploading: "the moment to keep
    and remove, the auto generated captions and the part where the face cam is in
    focus". Of three ways to lay that out he chose a timeline with lanes AND the
    transcript beside it ("a mix of B and C"); docs/superpowers/specs/
    2026-11-01-highlight-editor-design.md has the rest.

WHAT IS EDITED
    The cut list, never pixels. The clip job writes PROJECT beside the video it
    renders -- every cut the planner chose, the moments they belong to, what was
    said around them -- and the page changes only what `merge` lets it: a cut's
    start, end, whether it is kept and whether it zooms on the face; a line's
    words, whether it is a caption, cut out of the video, or said on the face; the
    facecam box, the zoom, the captions. Where the recording is, where the video
    goes and what was chosen in the first place are the job's, and a request
    cannot move them.

    A cut line and a face line are FLAGS on the line, applied only when the cut list
    is built for a render (`pieces`), so switching one off gives back exactly what
    was there before.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from .. import atomic
from . import stream_highlight as sh

log = logging.getLogger("autostream.clips.highlight_edit")

VERSION = 1
SUFFIX = ".edit.json"
EDITED = "_edited"
LAYOUTS = ("game", "cam", "result")
LANGS = ("english", "said")
SHORTEST = 0.5             # sh.shape()'s floor: a piece shorter than this is a flash
TRIM_LEAST = 1.0           # a kept cut is never trimmed shorter than this
ZOOM_LEAST, ZOOM_MOST = 1.2, sh.CAM_ZOOM_MOST


def project_path(video: str | Path) -> Path:
    v = Path(video)
    return v.with_name(v.stem + SUFFIX)


def edited_path(video: str | Path) -> Path:
    v = Path(video)
    return v.with_name(v.stem + EDITED + v.suffix)


def _name(s: sh.Stretch) -> str:
    return f"Round {s.round} · {s.why}" if s.round else (s.why or "Moment")


def build(*, video: str | Path, source: str | Path, source_seconds: float, cuts: list[sh.Cut],
          chosen: list[sh.Stretch], labels: list[str], lines=None, cam_box=None,
          channel: str = "", game: str = "", language: str | None = None,
          size: tuple[int, int] = (1920, 1080)) -> dict:
    """The project for a video the job has just planned. `labels[i]` names the match
    stretch i is from ("MATCH 1 · COMPETITIVE · BIND · CYPHER")."""
    english = any(getattr(ln, "english", "") for ln in lines or [])
    return {
        "version": VERSION,
        "video": str(video),
        "source": str(source),
        "source_seconds": round(float(source_seconds), 3),
        "game": game, "channel": channel, "size": list(size),
        "cam_box": [round(float(v), 5) for v in cam_box] if cam_box else None,
        "cam_zoom": None,
        "language": language,
        "captions": {"on": False, "lang": "english" if english else "said"},
        "moments": [{"id": i, "name": _name(s),
                     "match": labels[i] if i < len(labels) else "", "round": s.round}
                    for i, s in enumerate(chosen)],
        "cuts": [{"id": i, "start": round(c.start, 3), "end": round(c.end, 3),
                  "planned": [round(c.start, 3), round(c.end, 3)],
                  "kind": c.kind, "stretch": c.stretch, "layout": c.layout,
                  "caption": c.caption, "punches": [round(p, 3) for p in c.punches],
                  "keep": True, "zoom": c.layout == "cam"}
                 for i, c in enumerate(cuts)],
        "lines": [{"id": i, "start": round(ln.start, 3), "end": round(ln.end, 3),
                   "text": ln.text, "english": getattr(ln, "english", "") or "",
                   "show": True, "cut": False, "face": False}
                  for i, ln in enumerate(lines or [])],
        "made": "",
    }


def save(project: dict) -> Path:
    p = project_path(project["video"])
    atomic.write_json(p, project, indent=1)
    return p


def load(video: str | Path) -> dict | None:
    import json
    p = project_path(video)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("version") == VERSION else None


def _num(v, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f == f and abs(f) != float("inf") else default


def merge(base: dict, edits: dict) -> dict:
    """`base` with the page's edits applied, each checked. Only what the editor can
    change is read from `edits`; anything else in it is ignored."""
    out = {**base, "cuts": [dict(c) for c in base.get("cuts") or []],
           "lines": [dict(ln) for ln in base.get("lines") or []]}
    top = _num(base.get("source_seconds"), 0.0) or float("inf")
    by_id = {c["id"]: c for c in out["cuts"]}
    for e in edits.get("cuts") or []:
        c = by_id.get(e.get("id")) if isinstance(e, dict) else None
        if c is None:
            continue
        a = max(0.0, min(_num(e.get("start"), c["start"]), top))
        b = max(0.0, min(_num(e.get("end"), c["end"]), top))
        if b - a >= TRIM_LEAST:
            c["start"], c["end"] = round(a, 3), round(b, 3)
        c["keep"] = bool(e.get("keep", c["keep"]))
        c["zoom"] = bool(e.get("zoom", c["zoom"]))
    by_line = {ln["id"]: ln for ln in out["lines"]}
    for e in edits.get("lines") or []:
        ln = by_line.get(e.get("id")) if isinstance(e, dict) else None
        if ln is None:
            continue
        for k in ("text", "english"):
            if isinstance(e.get(k), str):
                ln[k] = " ".join(e[k].split())[:400]
        for k in ("show", "cut", "face"):
            if k in e:
                ln[k] = bool(e[k])
    if "cam_box" in edits:
        b = edits.get("cam_box")
        if isinstance(b, (list, tuple)) and len(b) == 4:
            x, y, w, h = (_num(v, -1.0) for v in b)
            if 0 <= x and 0 <= y and 0.02 <= w and 0.02 <= h and x + w <= 1.001 and y + h <= 1.001:
                out["cam_box"] = [round(x, 5), round(y, 5), round(w, 5), round(h, 5)]
    if "cam_zoom" in edits:
        z = edits.get("cam_zoom")
        out["cam_zoom"] = None if z in (None, "", 0, "auto") else round(
            max(ZOOM_LEAST, min(_num(z, ZOOM_LEAST), ZOOM_MOST)), 2)
    cap = edits.get("captions")
    if isinstance(cap, dict):
        out["captions"] = {"on": bool(cap.get("on", (base.get("captions") or {}).get("on"))),
                           "lang": cap.get("lang") if cap.get("lang") in LANGS
                           else (base.get("captions") or {}).get("lang", "english")}
    return out


def _layouts(a: float, b: float, base: str, faces: list[tuple[float, float]]) -> list[tuple[float, float, str]]:
    """[a, b) as (start, end, layout): `base`, and "cam" over the face spans."""
    marks = sorted({a, b, *(x for f in faces for x in f if a < x < b)})
    segs: list[list] = []
    for x, y in zip(marks, marks[1:]):
        mid = (x + y) / 2
        lay = "cam" if any(f0 <= mid < f1 for f0, f1 in faces) else base
        if segs and segs[-1][2] == lay:
            segs[-1][1] = y
        else:
            segs.append([x, y, lay])
    # A sliver between two face lines, or before one, is not a layout of its own.
    k = 0
    while k < len(segs):
        if segs[k][1] - segs[k][0] < SHORTEST and len(segs) > 1:
            j = k - 1 if k > 0 else k + 1
            segs[j][0], segs[j][1] = min(segs[j][0], segs[k][0]), max(segs[j][1], segs[k][1])
            del segs[k]
            k = 0
            continue
        if k and segs[k - 1][2] == segs[k][2]:
            segs[k - 1][1] = segs[k][1]
            del segs[k]
            continue
        k += 1
    return [(x, y, lay) for x, y, lay in segs]


def caption_text(ln: dict, lang: str) -> str:
    if lang == "english" and ln.get("english"):
        return ln["english"]
    return ln.get("text") or ""


def pieces(project: dict) -> tuple[list[sh.Cut], list[list[tuple[float, float, str]]]]:
    """The edited video's cut list, in order, and each cut's captions (seconds into
    the cut). Captions come back whether or not they are to be burned in: the .srt
    is written from them either way."""
    lines = [ln for ln in project.get("lines") or [] if (ln.get("end") or 0) > (ln.get("start") or 0)]
    holes = [(ln["start"], ln["end"]) for ln in lines if ln.get("cut")]
    faces = sh._union([(ln["start"], ln["end"]) for ln in lines if ln.get("face") and not ln.get("cut")])
    lang = (project.get("captions") or {}).get("lang", "english")
    said = [ln for ln in lines if ln.get("show", True) and not ln.get("cut") and caption_text(ln, lang).strip()]
    cuts: list[sh.Cut] = []
    subs: list[list[tuple[float, float, str]]] = []
    for c in project.get("cuts") or []:
        if not c.get("keep", True) or c["end"] - c["start"] < SHORTEST:
            continue
        lay = c.get("layout") if c.get("layout") in LAYOUTS else "game"
        base = "cam" if c.get("zoom") else ("game" if lay == "cam" else lay)
        first = True
        for a, b in sh._minus([(c["start"], c["end"])], holes):
            if b - a < SHORTEST:
                continue
            for x, y, layout in _layouts(a, b, base, faces):
                cut = sh.Cut(x, y, punches=[p for p in c.get("punches") or [] if x <= p < y],
                             kind=c.get("kind") or "play", stretch=int(c.get("stretch", -1)),
                             caption=(c.get("caption") or "") if first else "", layout=layout)
                first = False
                cuts.append(cut)
                subs.append([(max(ln["start"], x) - x, min(ln["end"], y) - x, caption_text(ln, lang))
                             for ln in said if ln["start"] < y and ln["end"] > x
                             and min(ln["end"], y) - max(ln["start"], x) >= 0.3])
    return cuts, subs


def _stamp(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(cuts: list[sh.Cut], subs: list[list[tuple[float, float, str]]]) -> str:
    """The captions as SubRip, on the edited video's clock -- for YouTube's own
    captions, which a viewer can switch off and which are searchable."""
    rows, at = [], 0.0
    for c, ss in zip(cuts, subs):
        for a, b, text in ss:
            rows.append((at + a, at + b, text))
        at += c.length
    return "".join(f"{n}\n{_stamp(a)} --> {_stamp(b)}\n{text}\n\n"
                   for n, (a, b, text) in enumerate(rows, 1))


def length(project: dict) -> float:
    return sum(c.length for c in pieces(project)[0])


WAIT_POLL = 3.0            # how often a waiting render asks whether it may start


class Renderer:
    """One edited video at a time, with a snapshot the page polls.

    IT WAITS FOR THE BROADCAST. Make video saturates the encoder, and on a
    session that is live or recording that is dropped frames in the stream --
    so a render asked for then is held ("waiting", with the reason) and starts
    by itself once `held()` says nothing is in the way. The player's own word
    on the plan (2026-11-01): no Make video while live or recording; wait and
    say so."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.state, self.video, self.out, self.error, self.why = "idle", "", "", "", ""
        self.done, self.total, self.started = 0, 0, 0.0

    def busy(self) -> bool:
        with self._lock:
            t = self._thread
        return bool(t and t.is_alive())

    def encoding(self) -> bool:
        """Rendering now, as opposed to waiting for its turn."""
        with self._lock:
            return self.state == "running" and bool(self._thread and self._thread.is_alive())

    def start(self, project: dict, *, encoder: str = "auto", held=None) -> bool:
        """`held()` -> why the render may not start yet, "" when it may."""
        if self.busy():
            return False
        with self._lock:
            self._stop.clear()
            self.state, self.video, self.error, self.why = "running", project["video"], "", ""
            self.out, self.done, self.total, self.started = "", 0, 0, time.time()
            self._thread = threading.Thread(target=self._run, args=(project, encoder, held),
                                            name="autostream-highlight-edit", daemon=True)
            self._thread.start()
        return True

    def cancel(self) -> None:
        self._stop.set()

    def _wait(self, held) -> bool:
        """Until nothing holds the encoder. False when stopped while waiting."""
        while True:
            try:
                why = held() if held else ""
            except Exception:  # noqa: BLE001 - a check that fails holds nothing
                why = ""
            if not why:
                with self._lock:
                    self.state, self.why, self.started = "running", "", time.time()
                return True
            with self._lock:
                if self.state != "waiting":
                    log.info("edited highlight waiting: %s", why)
                self.state, self.why = "waiting", why
            if self._stop.wait(WAIT_POLL):
                return False

    def _run(self, project: dict, encoder: str, held=None) -> None:
        out = edited_path(project["video"])
        try:
            if not self._wait(held):
                raise InterruptedError("stopped while waiting")
            # From disk now, not as asked: edits saved while it waited are in.
            project = load(project["video"]) or project
            cuts, subs = pieces(project)
            if sum(c.length for c in cuts) < 5.0:
                raise ValueError("Nothing is kept: keep at least one moment.")

            def tick(done: int, total: int) -> None:
                with self._lock:
                    self.done, self.total = done, total

            tmp = out.with_name(out.stem + ".part.mp4")
            box = project.get("cam_box")
            sh.render(Path(project["source"]), cuts, tmp, size=tuple(project.get("size") or (1920, 1080)),
                      encoder=encoder, cq=23, channel=project.get("channel") or "",
                      game=project.get("game") or "", cam_box=tuple(box) if box else None,
                      progress=tick, cam_most=project.get("cam_zoom"),
                      subs=subs if (project.get("captions") or {}).get("on") else None,
                      cancelled=self._stop.is_set)
            tmp.replace(out)
            text = srt(cuts, subs)
            if text:
                out.with_suffix(".srt").write_text(text, encoding="utf-8")
            # From disk, not the copy this started with: the page may have saved
            # edits while it rendered.
            save({**(load(project["video"]) or project), "made": str(out)})
            with self._lock:
                self.state, self.out = "done", str(out)
            log.info("edited highlight: %s (%d cuts, %.0f s)", out.name, len(cuts),
                     sum(c.length for c in cuts))
        except InterruptedError:
            with self._lock:
                self.state, self.why = "idle", ""
            log.info("edited highlight stopped")
        except Exception as e:  # noqa: BLE001 - the page shows why
            log.exception("could not make the edited highlight: %s", e)
            with self._lock:
                self.state, self.error = "failed", str(e)[:400]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"state": self.state, "video": self.video, "out": self.out, "error": self.error,
                    "why": self.why,
                    "done": self.done, "total": self.total,
                    "percent": int(100 * self.done / self.total) if self.total else 0,
                    "elapsed": int(time.time() - self.started) if self.started else 0}


_RENDERER = Renderer()


def renderer() -> Renderer:
    return _RENDERER
