r"""A style, shown on YOUR kills.

WHY THIS EXISTS
    The Make page described each style in words and in statistics -- "Measured on 4
    edits: 53.3 cuts/min - 60.6 flashes/min - first shot 3.4 s" -- eleven times, in a
    wall. Nobody chooses a look from a flash rate. What tells Hype from Cinematic is
    watching them, and watching two styles on DIFFERENT footage tells you about the
    footage.

    So each style is cut, about twenty seconds of it, from the SAME clips and the same
    kills, and the page plays them side by side. The only thing that differs between two
    samples is the style.

WHAT IS AND IS NOT SHARED
    Same clips (the first SAMPLE_CLIPS the player chose, in their order), same format,
    same song and part when one was chosen. Everything the style decides -- cut pace,
    transitions, kill effects, grade -- is its own.

    No kill-emblem pass (`checks`): it costs about a minute a plan, and a sample shows a
    style's feel, not whether a kill is a frame early. The reel the player actually
    builds does make the checks.

CACHE
    By a key over the clips, their files, the format and the song, in
    `<clips>/.style_samples/<key>/<style>.mp4`. Bump SAMPLE_VERSION when what a sample
    looks like changes: a stale card would show a style as it used to be.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("autostream.clips.style_samples")

SAMPLE_SECONDS = 20.0
SAMPLE_CLIPS = 8
SAMPLE_VERSION = 1
FOLDER = ".style_samples"


def pick_clips(clips: list[dict]) -> list[dict]:
    """The clips every style is cut from: the same first few, in the order chosen."""
    return [c for c in clips if c and c.get("path")][:SAMPLE_CLIPS]


def key_of(clips: list[dict], fmt: str, song: str = "", part: tuple[float, float] | None = None) -> str:
    """A key over everything that decides what a sample shows, except the style."""
    rows = []
    for c in pick_clips(clips):
        try:
            mtime = Path(c["path"]).stat().st_mtime
        except OSError:
            mtime = 0.0
        rows.append([str(c["path"]).lower(), round(mtime, 1),
                     [round(float(k), 2) for k in (c.get("kills") or [])]])
    song_id = ""
    if song:
        try:
            song_id = f"{Path(song).name}:{Path(song).stat().st_mtime:.0f}"
        except OSError:
            song_id = str(song)
    blob = json.dumps([SAMPLE_VERSION, rows, fmt, song_id,
                       [round(part[0], 1), round(part[1], 1)] if part else None], sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def folder(root: Path, key: str) -> Path:
    return Path(root) / FOLDER / key


def path_for(root: Path, key: str, style: str) -> Path | None:
    f = folder(root, key) / f"{style}.mp4"
    try:
        return f if f.is_file() and f.stat().st_size > 0 else None
    except OSError:
        return None


def ready(root: Path, key: str, styles: list[str]) -> dict[str, str]:
    """{style: file name} for every sample already made."""
    return {s: f"{s}.mp4" for s in styles if path_for(root, key, s)}


def make(root: Path, clips: list[dict], style: str, fmt: str, out: Path, *,
         song: str = "", shape=None, part: tuple[float, float] | None = None) -> Path:
    """Plan and render ONE sample. Raises on failure; the caller records it."""
    from . import examples, studio

    chosen = pick_clips(clips)
    if not chosen:
        raise ValueError("There are no clips to cut a sample from.")
    proj, _notes = studio.plan(chosen, style, shape=shape, song=song if shape else "", fmt=fmt,
                               max_seconds=SAMPLE_SECONDS, part=part, name=f"{style} sample")
    proj, derived, _ = studio.normalise(proj, root)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part.mp4")
    job = studio.StudioJob(proj, derived, root, tmp)
    job.run()
    snap = job.snapshot()
    if snap["state"] != "done" or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(snap.get("error") or "The render failed.")
    examples._shrink(tmp, width=480 if fmt != "vertical" else 270, fps=24, crf=30)
    tmp.replace(out)
    return out


class _Runner:
    """Cuts the missing samples one after another in the background.

    One at a time, like the examples: it is ffmpeg-bound, and a second would only make
    both slow -- and it never starts while something the player asked for holds the encoder.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict = {"state": "idle"}
        self._stop = threading.Event()

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def busy(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def cancel(self) -> dict:
        self._stop.set()
        self._set(message="Stopping after this one...")
        return self.status()

    def _set(self, **kw) -> None:
        with self._lock:
            self._state.update(kw)

    def start(self, root: Path, clips: list[dict], fmt: str, styles: list[str], *,
              song: str = "", shape=None, part: tuple[float, float] | None = None) -> dict:
        key = key_of(clips, fmt, song, part)
        todo = [s for s in styles if not path_for(root, key, s)]
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return dict(self._state)
            self._state = {"state": "running" if todo else "done", "key": key, "done": 0,
                           "total": len(todo), "style": "", "failed": {},
                           "ready": ready(root, key, styles),
                           "message": "Starting" if todo else "Every style is already shown."}
        if not todo:
            return self.status()
        self._stop.clear()

        def work() -> None:
            began = time.monotonic()
            for i, style in enumerate(todo):
                if self._stop.is_set():
                    break
                left = ""
                if i >= 1:
                    each = (time.monotonic() - began) / i
                    mins = each * (len(todo) - i) / 60
                    left = ", about " + (f"{mins:.0f} min" if mins >= 1.5 else "a minute") + " left"
                self._set(done=i, style=style, message=f"Cutting {style} ({i + 1} of {len(todo)}{left})")
                try:
                    make(root, clips, style, fmt, folder(root, key) / f"{style}.mp4",
                         song=song, shape=shape, part=part)
                    with self._lock:
                        self._state["ready"][style] = f"{style}.mp4"
                except Exception as e:                   # noqa: BLE001
                    log.info("style sample %s failed: %s", style, e)
                    with self._lock:
                        self._state["failed"][style] = str(e)[:200]
            self._set(state="done", done=len(todo), style="",
                      message=("Stopped." if self._stop.is_set() else
                               f"{len(self._state['ready'])} style(s) shown"
                               + (f", {len(self._state['failed'])} failed" if self._state["failed"] else "")))

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
        return self.status()


_RUNNER: _Runner | None = None


def runner() -> _Runner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = _Runner()
    return _RUNNER
