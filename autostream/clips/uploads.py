r"""Clips the player brings: a video file that was never a recording here.

WHY
    The Studio used to know only clips AutoStream had cut itself. Plenty of
    players already have their best moments as files -- saved by the game,
    by Medal or ShadowPlay, sent by a friend -- and the reel maker had no way
    to use them. So a file can be added to the Studio's library directly.

ONE RUN FOLDER PER IMPORTED CLIP
    The library reads clips out of run folders (clips/<run>/clips.json and
    session.json), and a run's kills are session times shared by every clip in
    it. An imported clip has no session: its kills are its own. Giving each one
    its own run folder keeps its kills apart from every other clip's without
    teaching the library a second format, and deleting it is the ordinary
    delete. The folder is `import-<date>-<name>`, and session.json carries
    `"imported": true` so the page can say where it came from.

WHERE THE KILLS COME FROM
    Two ways, and the page offers both:
      - the detector for the game the player names, run over the whole file
        (Valorant's feed reader, Counter-Strike's card reader) -- see detect();
      - marking by hand while it plays, the same K-on-the-beat gesture the
        Song tab uses for music.
    Whatever the detector finds is only a proposal: the marks the player saves
    are what the reel is cut to.

THE TITLE
    "4K", "1v3 clutch", "ACE" -- what the clip IS. Stored as the clip's name,
    which is what the Studio shows and what a reel's shot is called; it is not
    drawn on the video.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

PREFIX = "import-"
VIDEO_EXTS = (".mp4", ".m4v", ".mov", ".mkv")
MAX_KILLS = 12
TITLE_PRESETS = ("ACE", "4K", "3K", "Double kill", "1v2 clutch", "1v3 clutch",
                 "1v4 clutch", "1v5 clutch", "Headshot", "Wallbang", "Knife kill",
                 "Flick", "Collateral", "Ninja defuse")


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return (s or "clip")[:40]


def _read(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(p: Path, data: dict) -> None:
    from ..atomic import write_text
    write_text(p, json.dumps(data, indent=1))


def run_of(root: Path, clip: Path) -> Path | None:
    """The import folder a clip lives in, or None if it is not an imported clip."""
    try:
        clip = Path(clip).resolve()
        run = clip.parent.parent
        if clip.parent.name != "clips" or not run.name.startswith(PREFIX):
            return None
        if not run.is_relative_to(Path(root).resolve()):
            return None
    except OSError:
        return None
    return run


def add(root: Path, src: str, game: str = "", title: str = "") -> dict:
    """Bring one video file into the library. -> {ok, clip} or {ok: False, error}.

    Linked rather than copied where the file is on the same drive, because a
    hard link costs nothing and these can be large; copied otherwise. Either
    way the Studio then owns a path inside the clips folder, which is what
    every other part of it checks for.
    """
    from . import tools
    s = Path(str(src or ""))
    if s.suffix.lower() not in VIDEO_EXTS or not s.is_file():
        return {"ok": False, "error": "Choose an .mp4, .mov, .m4v or .mkv video."}
    root = Path(root)
    stamp = time.strftime("%Y-%m-%d_%H%M")
    base = f"{PREFIX}{stamp}-{_slug(s.stem)}"
    run, n = root / base, 2
    while run.exists():
        run, n = root / f"{base}-{n}", n + 1
    (run / "clips").mkdir(parents=True)
    dst = run / "clips" / (_slug(s.stem) + s.suffix.lower())
    try:
        try:
            os.link(s, dst)
        except OSError:
            shutil.copy2(s, dst)
    except OSError as e:
        shutil.rmtree(run, ignore_errors=True)
        return {"ok": False, "error": f"Could not add that file: {e}"}
    try:
        seconds = float(tools.media_info(dst)["duration"])
    except Exception:                                    # noqa: BLE001
        seconds = 0.0
    if seconds <= 0:
        shutil.rmtree(run, ignore_errors=True)
        return {"ok": False, "error": "That file has no video AutoStream can read."}
    name = (title or s.stem).strip()[:80]
    _write(run / "clips.json", {"game": game or "Other", "clips": [{
        "name": name, "master": str(dst), "start": 0.0, "end": round(seconds, 3),
        "duration": round(seconds, 3), "kills": 0, "title": title.strip()[:80]}]})
    _write(run / "session.json", {"game": game or "Other", "imported": True,
                                  "source": str(s), "kills": [],
                                  "options": {"pre_roll": 0.0}})
    return {"ok": True, "clip": {"path": str(dst), "name": name, "seconds": round(seconds, 3),
                                 "game": game or "Other", "kills": [], "title": title}}


def any_run(root: Path, clip: Path) -> Path | None:
    """The run folder a clip lives in, imported or cut by AutoStream.

    `run_of` answers only for imports, because that is all the marker could
    open. The marker works on any path -- `studio_impOpen(path)` never cared
    where a clip came from -- and what was missing was the way in: a clip
    AutoStream cut for itself had no Edit button at all, so a kill the
    detector put half a second late could not be corrected and a clip could
    not be retitled.
    """
    try:
        clip = Path(clip).resolve()
        run = clip.parent.parent
        if clip.parent.name != "clips":
            return None
        if not run.is_relative_to(Path(root).resolve()):
            return None
        if not (run / "clips.json").is_file():
            return None
    except OSError:
        return None
    return run


def _row_for(man: dict, clip: Path) -> tuple[dict | None, int]:
    """The manifest row for one clip. -> (row, index).

    AN IMPORT HAS ONE ROW AND A RUN HAS FORTY, so the first row is the right
    answer for exactly one of the two. Matched on the file name, which is what
    the manifest records and what the page hands back.
    """
    rows = man.get("clips") or []
    want = Path(clip).name.lower()
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        master = Path(str(r.get("master") or "")).name.lower()
        if master == want:
            return r, i
    return (rows[0], 0) if rows and isinstance(rows[0], dict) else (None, -1)


def _clip_kills(sess: dict, row: dict) -> list[float]:
    """This clip's kills, in CLIP seconds.

    THE TWO HALVES STORE THEM DIFFERENTLY, which is the whole reason this
    exists. An imported clip's `session.json` holds one clip and its kills are
    already clip-relative. A run's holds the kills of the whole RECORDING, so
    a clip that starts 42 minutes in has its first kill at 2520 seconds. The
    same arithmetic the Studio page already does to draw the kill pips.

    A correction written by the marker wins over both: it is the only one a
    person typed.
    """
    marks = row.get("marks")
    if isinstance(marks, list):
        out = []
        for m in marks:
            try:
                out.append(float(m))
            except (TypeError, ValueError):
                continue
        return sorted(out)

    raw = [float(k["time"]) for k in sess.get("kills") or []
           if isinstance(k, dict) and k.get("time") is not None]
    try:
        start = float(row.get("start") or 0.0)
        end = float(row.get("end") or 0.0)
        dur = float(row.get("duration") or max(0.0, end - start))
    except (TypeError, ValueError):
        return sorted(raw)
    # An import records start 0 and holds only its own kills, so this is the
    # identity for one and the mapping for the other.
    if end <= 0 and start <= 0:
        return sorted(raw)
    out = [round(k - start, 3) for k in raw if start - 0.05 <= k <= end + 0.05]
    return sorted(min(max(0.0, o), dur) for o in out)


def info(root: Path, clip: str) -> dict:
    run = any_run(root, Path(clip))
    if not run:
        return {"ok": False, "error": "That clip is not in the clips folder."}
    man, sess = _read(run / "clips.json"), _read(run / "session.json")
    row, _i = _row_for(man, Path(clip))
    if row is None:
        return {"ok": False, "error": "That clip is not in its run's manifest."}
    return {"ok": True, "path": str(clip), "name": row.get("name") or "",
            "title": row.get("title") or "", "seconds": row.get("duration") or 0.0,
            "game": man.get("game") or "Other",
            "kills": _clip_kills(sess, row),
            # So the marker can say what it is editing. An AutoStream clip's
            # marks are a correction to what a detector found; an import's are
            # the only ones there have ever been.
            "imported": bool(run.name.startswith(PREFIX)),
            "presets": list(TITLE_PRESETS)}


def save(root: Path, clip: str, kills, title: str | None = None, game: str | None = None) -> dict:
    """Store the kills (clip seconds) and the title the player settled on."""
    run = any_run(root, Path(clip))
    if not run:
        return {"ok": False, "error": "That clip is not in the clips folder."}
    man, sess = _read(run / "clips.json"), _read(run / "session.json")
    rows = man.get("clips") or [{}]
    row, _i = _row_for(man, Path(clip))
    if row is None:
        row = rows[0]
    imported = run.name.startswith(PREFIX)
    dur = float(row.get("duration") or 0.0)
    ks = []
    for k in kills or []:
        try:
            t = float(k)
        except (TypeError, ValueError):
            continue
        if 0.0 <= t <= dur + 0.05:
            ks.append(round(min(t, dur), 3))
    ks = sorted(set(ks))[:MAX_KILLS]
    # WRITTEN WHERE IT CANNOT HARM THE OTHER FORTY. An import's session.json
    # describes that one clip, so its kills ARE the session's. A run's
    # describes the whole recording and forty clips read from it -- so a
    # correction to one clip goes on that clip's row, in clip seconds, and the
    # recording's kill list is left exactly as the detector found it.
    #
    # Overwriting the session there would have moved every other clip's pips
    # and broken the next re-cut, from a dialog that said "Save".
    if imported:
        sess["kills"] = [{"time": t, "end": t, "score": 1.0, "count": 1,
                          "record": True} for t in ks]
    row["marks"] = ks
    row["kills"] = len(ks)
    if title is not None:
        t = re.sub(r"[\r\n]", " ", str(title)).strip()[:80]
        row["title"] = t
        row["name"] = t or Path(str(row.get("master") or clip)).stem
        row["caption"] = t
    if game:
        man["game"] = sess["game"] = str(game)[:60]
    man["clips"] = rows
    _write(run / "clips.json", man)
    if imported:
        _write(run / "session.json", sess)
    return {"ok": True, "kills": ks, "name": row["name"]}


# -------------------------------------------------------------- cutting a bit out

def trim(root: Path, clip: str, start: float, end: float) -> dict:
    """Take [start, end] OUT of a clip and keep the rest. -> {ok, seconds, kills}.

    SAID AS "REMOVE", NOT AS "KEEP", because that is what somebody watching a
    clip wants to do: there is a bit at the front where nothing happens, or a
    death at the end, and they want it gone. Phrasing it as a keep-range
    forces them to work out the complement of the thing they can see.

    It therefore handles a middle as naturally as an end. Taking out the
    middle leaves two spans, and `cutter.master_segments` joins them by
    stream copy, so removing a bit costs no quality anywhere -- including in
    the isolated mic and game audio tracks, which a filter-graph join would
    have flattened.

    THE KILL MARKS MOVE WITH IT. A kill at 12s with seconds 5 to 10 removed is
    at 7s afterwards, and one INSIDE the removed span is gone. Leaving them
    where they were would silently point every mark in the clip at the wrong
    moment, and the only sign would be a reel cutting to nothing.

    The original is kept beside the new file until the next trim, so a cut
    somebody regrets is one rename away rather than gone.
    """
    from . import cutter, tools

    run = any_run(root, Path(clip))
    if not run:
        return {"ok": False, "error": "That clip is not in the clips folder."}
    src = Path(clip)
    if not src.is_file():
        return {"ok": False, "error": "That clip is not on disk any more."}

    man, sess = _read(run / "clips.json"), _read(run / "session.json")
    row, _i = _row_for(man, src)
    if row is None:
        return {"ok": False, "error": "That clip is not in its run's manifest."}

    try:
        total = float(tools.media_info(src)["duration"])
    except Exception as e:                               # noqa: BLE001
        return {"ok": False, "error": f"Could not read that clip: {str(e)[:120]}"}

    a, b = max(0.0, float(start)), min(float(total), float(end))
    if b - a < 0.05:
        return {"ok": False, "error": "Choose a longer piece to remove."}

    keep = [(x, y) for x, y in ((0.0, a), (b, total)) if y - x > 0.04]
    if not keep:
        return {"ok": False,
                "error": "That would remove the whole clip. Delete it instead."}
    kept = sum(y - x for x, y in keep)
    if kept < 0.5:
        return {"ok": False, "error": "Less than half a second would be left."}

    tmp_name = src.stem + "-trim"
    try:
        out = cutter.master_segments(src, keep, tmp_name, src.parent)
    except Exception as e:                               # noqa: BLE001
        return {"ok": False, "error": f"Could not cut that out: {str(e)[:160]}"}

    # THE ORIGINAL IS KEPT, once. Overwriting it on every trim would make the
    # backup a copy of the last cut rather than of what the user brought in.
    backup = src.with_suffix(src.suffix + ".original")
    try:
        if not backup.exists():
            os.replace(src, backup)
        else:
            src.unlink(missing_ok=True)
        os.replace(out, src)
    except OSError as e:
        return {"ok": False, "error": f"Could not replace the clip: {e}"}

    moved = shift_marks(_clip_kills(sess, row), a, b)
    row["marks"] = moved
    row["kills"] = len(moved)
    row["duration"] = round(kept, 3)
    row["end"] = round(float(row.get("start") or 0.0) + kept, 3)
    if run.name.startswith(PREFIX):
        sess["kills"] = [{"time": t, "end": t, "score": 1.0, "count": 1,
                          "record": True} for t in moved]
        _write(run / "session.json", sess)
    man["clips"] = man.get("clips") or [row]
    _write(run / "clips.json", man)
    log.info("trimmed %.2f-%.2fs out of %s; %.1fs left, %d mark(s) kept",
             a, b, src.name, kept, len(moved))
    return {"ok": True, "seconds": round(kept, 3), "kills": moved,
            "removed": [round(a, 3), round(b, 3)]}


def shift_marks(marks, a: float, b: float) -> list[float]:
    """Kill marks after [a, b] is removed.

    Inside the cut they are gone -- there is no moment left for them to point
    at. After it they move back by exactly the length removed.
    """
    out = []
    for m in marks or []:
        try:
            t = float(m)
        except (TypeError, ValueError):
            continue
        if a <= t <= b:
            continue
        out.append(round(t - (b - a), 3) if t > b else round(t, 3))
    return sorted(out)


# ------------------------------------------------------------------ detection

class _Detector:
    """One detection at a time, on its own thread, watched through status()."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict = {"state": "idle"}
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def _set(self, **kw) -> None:
        with self._lock:
            self._state.update(kw)

    def cancel(self) -> dict:
        self._cancel.set()
        return self.status()

    def start(self, root: Path, clip: str, game_key: str, game_name: str) -> dict:
        from . import profiles
        run = run_of(root, Path(clip))
        if not run:
            return {"state": "failed", "message": "That is not a clip you added."}
        prof = profiles.for_game(game_key or None, game_name or None)
        if prof is None:
            return {"state": "failed",
                    "message": f"AutoStream has no kill detector for {game_name or 'that game'}. "
                               "Mark the kills by hand while it plays."}
        why = prof.why_not()
        if why:
            return {"state": "failed", "message": why}
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return dict(self._state)
            self._state = {"state": "running", "clip": str(clip), "done": 0, "total": 0,
                           "message": "Reading the kills", "kills": []}
        self._cancel.clear()

        def work() -> None:
            from . import detect
            try:
                found = detect.scan(Path(clip), prof,
                                    progress=lambda d, t: self._set(done=d, total=t),
                                    cancelled=self._cancel.is_set)
                kills = sorted({round(float(k.time), 3) for k in found})
                self._set(state="done", kills=kills,
                          message=(f"Found {len(kills)} kill" + ("" if len(kills) == 1 else "s")
                                   + ". Check them, then save.") if kills else
                          "No kills found. Mark them by hand while it plays.")
            except Exception as e:                       # noqa: BLE001
                log.info("uploads: detection failed: %s", e)
                self._set(state="failed", message=str(e)[:200] or "Detection failed.")

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
        return self.status()


_DETECTOR: _Detector | None = None


def detector() -> _Detector:
    global _DETECTOR
    if _DETECTOR is None:
        _DETECTOR = _Detector()
    return _DETECTOR
