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


def info(root: Path, clip: str) -> dict:
    run = run_of(root, Path(clip))
    if not run:
        return {"ok": False, "error": "That is not a clip you added."}
    man, sess = _read(run / "clips.json"), _read(run / "session.json")
    row = (man.get("clips") or [{}])[0]
    return {"ok": True, "path": str(clip), "name": row.get("name") or "",
            "title": row.get("title") or "", "seconds": row.get("duration") or 0.0,
            "game": man.get("game") or "Other",
            "kills": [float(k["time"]) for k in sess.get("kills") or []
                      if isinstance(k, dict) and k.get("time") is not None],
            "presets": list(TITLE_PRESETS)}


def save(root: Path, clip: str, kills, title: str | None = None, game: str | None = None) -> dict:
    """Store the kills (clip seconds) and the title the player settled on."""
    run = run_of(root, Path(clip))
    if not run:
        return {"ok": False, "error": "That is not a clip you added."}
    man, sess = _read(run / "clips.json"), _read(run / "session.json")
    rows = man.get("clips") or [{}]
    row = rows[0]
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
    sess["kills"] = [{"time": t, "end": t, "score": 1.0, "count": 1, "record": True} for t in ks]
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
    _write(run / "session.json", sess)
    return {"ok": True, "kills": ks, "name": row["name"]}


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
