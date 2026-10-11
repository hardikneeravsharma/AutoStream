r"""One short example of every part, cut from the player's own clips.

WHY THIS EXISTS
    The reel maker used to offer its parts as a list of names: "k04 Freeze",
    "t05 Zoom through", "c04 Beat pulse". Nobody can pick an edit from a list
    of names -- an editor picks by watching. So every part the Studio can put
    in a reel has a two-second example beside it, playing on a loop, and a
    template is one pick from every drawer with its examples shown together.

FROM THE PLAYER'S OWN FOOTAGE, NEVER SHIPPED
    An example is rendered from the clips on this machine, by the same
    code that renders the reel -- StudioJob over a two-shot project with that
    one part set. So what the card shows is what the reel will do, and a
    stranger who installs AutoStream gets examples of their own game, not
    somebody else's. They live in the clips folder's own cache
    (<clips>\.studio\examples) and are never committed: the repo is public and
    the footage is not.

    Files are whatever was put there -- .mp4 from a rebuild, .gif from an
    earlier batch -- and the page plays either.

UNTIL THEN, STOCK ONES
    A new install has no clips, and cutting examples needs two -- so the bin
    was a wall of empty cards for exactly the person who most needed to see
    what each part does. A stock set ships with the app
    (clips/stock_examples, made by scripts/make_stock_examples.py). It was
    first cut from footage that script drew -- a skyline and a strafing
    blob -- and nobody could judge a grade or a kill effect on that; the
    maintainer gave two of their own VALORANT clips for it instead, used for
    these cards and nothing else. Any card cut from the player's own clips
    replaces its stock one, and the page says which it is showing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from pathlib import Path

from . import studio

log = logging.getLogger(__name__)

FOLDER = "examples"
# What a browser can play back-to-back on a card.
TYPES = {".mp4": "video/mp4", ".webm": "video/webm", ".gif": "image/gif"}
# Two shots, so a transition has something to cut between, and short enough
# that a wall of them stays light: the whole set is about a minute of video.
SHOT_SECONDS = 1.8
# What a card is finally kept as. A reel renders at 1920x1080 and CQ 16 --
# 5 MB for one example, 300 MB for the bin -- so each is shrunk to this once
# it has been cut.
#
# These are measured, not taste. A 3.6 s card off the maintainer's own footage:
# 480/24/CRF30 was 121 KB (68 MB for all 562) and visibly mushy -- grain and
# scanlines turned to porridge, which is the one thing these cards exist to
# show. 640/30/CRF26 is 353 KB (~195 MB), and 720/CRF24 was 560 KB (~315 MB)
# for no gain anyone can see: a card is 360-480 CSS px on screen, so past 640
# the extra bytes are thrown away by the browser's own scaler. The sharp copy
# below is what a closer look gets.
CARD_WIDTH = 640
CARD_FPS = 30
CARD_CRF = 26
# THE ONE ON THE STAGE, SHARP. The picker shows the option under the pointer
# large, in the middle, so the difference between two can be seen -- and at
# card size there is none to see: fine and coarse grain, fine and wide
# scanlines, side by side at 360 wide, are the same picture (measured on the
# stock set). So the one being looked at is cut again at this size when it is
# first shown, and kept. Only the parts somebody has looked at are ever made.
LARGE_FOLDER = "large"
LARGE_WIDTH = 1280
LARGE_FPS = 30
LARGE_CRF = 20
LARGE_RETRY = 120.0            # seconds before a part that could not be made is tried again
# Parts that are the absence of an effect. An example of "no camera move" is
# an empty card, so nothing is rendered for them and they are not counted
# missing. A hard cut is NOT one of these: seeing two shots meet with nothing
# between them is the point of that card.
NOTHING = {"i00", "s00", "c00", "o00"}


def folder(root: Path) -> Path:
    return Path(root) / studio.CACHE_DIR / FOLDER


# Shipped beside this module, so a frozen build finds it the same way.
STOCK = Path(__file__).resolve().parent / "stock_examples"


def stock_path(part: str) -> Path | None:
    f = STOCK / f"{part}.mp4"
    return f if part in known() and f.is_file() else None


def known() -> dict[str, str]:
    """Every part the Studio can use. -> {id: kind}"""
    return {p["id"]: p["kind"] for p in studio.catalog()["parts"]}


def path_for(root: Path, part: str, stock: bool = True) -> Path | None:
    """The example file for one part, or None. Never leaves the folder.

    The player's own example first; the stock one only where there is none,
    and not at all with `stock=False` -- which is how a rebuild asks what is
    still missing, since a stock card is not one of theirs.
    """
    if part not in known():
        return None
    here = folder(root)
    for ext in TYPES:
        f = here / f"{part}{ext}"
        if f.is_file():
            return f
    return stock_path(part) if stock else None


def manifest(root: Path) -> dict:
    """What the page needs to draw the parts bin: every part, and its example."""
    parts = known()
    have: dict[str, dict] = {}
    for part in parts:
        f = path_for(root, part)
        if not f:
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        have[part] = {"file": f.name, "type": TYPES.get(f.suffix.lower(), "video/mp4"),
                      "bytes": st.st_size, "when": int(st.st_mtime),
                      "stock": f.parent == STOCK}
    # Missing means "not cut from your clips yet": a rebuild's job, whether or
    # not a stock card is standing in for it.
    missing = sorted(p for p in parts if p not in NOTHING
                     and (p not in have or have[p]["stock"]))
    return {"ok": True, "examples": have, "missing": missing,
            "nothing": sorted(p for p in parts if p in NOTHING),
            "folder": str(folder(root)),
            # Which clips the set standing there was cut from, so a page can
            # say so and a changed choice can be noticed. {} before a rebuild,
            # and for a stock set, which was cut from nobody's clips here.
            "cut_from": cut_from(root)}


def take_from(root: Path, src: Path) -> dict:
    """Adopt examples rendered elsewhere: <part id>.<ext> for parts we know."""
    parts = known()
    here = folder(root)
    here.mkdir(parents=True, exist_ok=True)
    taken = []
    try:
        files = sorted(Path(src).iterdir())
    except OSError as e:
        return {"ok": False, "error": f"Could not read {src}: {e}"}
    for f in files:
        if f.suffix.lower() not in TYPES or f.stem not in parts:
            continue
        try:
            shutil.copy2(f, here / f.name)
        except OSError as e:
            log.info("examples: could not take %s: %s", f.name, e)
            continue
        taken.append(f.stem)
    if taken:
        # These came from somewhere else, so whatever the last rebuild noted
        # about its source clips no longer describes what is in the folder.
        # No note is honest; a stale one is the thing this exists to prevent.
        (here / SOURCES_FILE).unlink(missing_ok=True)
    return {"ok": True, "taken": sorted(taken), "folder": str(here)}


def sources(root: Path, want: int = 2, game: str = "") -> list[dict]:
    """The clips an example is cut from: the player's starred ones first.

    Every card in the bin is cut from these two, so they are the footage a
    stranger judges every part by -- and the rule used to be "the two
    shortest", which is a proxy for cheap to seek, not for good to look at.
    The clips somebody has starred are the ones they already think are worth
    watching, so those come first (`fav`, which the library sets from
    studio.favourites). Whatever is left behind them is still ordered shortest
    first, so a library with nothing starred gets exactly what it got before.

    The hard requirements are unchanged either way: a kill with footage either
    side, because a card that opens on a body falling shows nothing, and long
    enough for two shots. `game` keeps to one game's clips -- the stock set is
    cut from VALORANT alone.

    Deterministic: ties on duration are broken by clip id, so the same library
    always gives the same two and a rebuild does not quietly re-cut the bin
    from other footage.
    """
    lib = studio.library(Path(root))
    pool = [c for g in lib.get("games") or [] for f in g.get("folders") or []
            if not game or str(g.get("game") or "").lower() == game.lower()
            for c in f.get("clips") or []
            if (c.get("kills") or []) and float(c.get("duration") or 0) > 4.0
            and float(c["kills"][0]) > 1.5]
    pool.sort(key=lambda c: (not c.get("fav"), float(c.get("duration") or 0),
                             str(c.get("id") or ""), str(c.get("path") or "")))
    return pool[:want]


def sources_key(clips: list[dict]) -> str:
    """A short key for one choice of source clips. Changes when the choice does."""
    ids = [str(c.get("id") or c.get("path") or "") for c in clips]
    return hashlib.sha1("|".join(ids).lower().encode("utf-8")).hexdigest()[:12]


SOURCES_FILE = "sources.json"


def _write_sources(root: Path, clips: list[dict]) -> None:
    """Note beside the cards which clips they were cut from.

    A bin is only honest about itself if it says what it is showing: a player
    who stars better footage later, or deletes what these were cut from, has a
    set that no longer matches their library, and nothing could tell. The key
    is what a later run compares against; the names are what a page can say.
    """
    rec = {"key": sources_key(clips), "when": int(time.time()),
           "clips": [Path(str(c.get("path") or "")).name or str(c.get("name") or "")
                     for c in clips],
           "fav": [bool(c.get("fav")) for c in clips]}
    f = folder(root) / SOURCES_FILE
    try:
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
        tmp.replace(f)
    except OSError as e:
        log.info("examples: could not note the sources: %s", e)


def cut_from(root: Path) -> dict:
    """What the examples on disk were cut from, or {} if it was never noted."""
    try:
        got = json.loads((folder(root) / SOURCES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _project(part: str, kind: str, clips: list[dict]) -> dict | None:
    """A two-shot reel that shows one part and nothing else of its own."""
    style = "hype" if kind in ("speed", "camera") else studio.DEFAULT_STYLE
    # No max_seconds: it trims shots off the end, and a transition with only
    # one shot left has nothing to cut between. The trimming is done below.
    proj, _notes = studio.plan(clips[:2], style, name=f"example {part}")
    shots = proj.get("shots") or []
    if len(shots) < 2:
        return None
    del shots[2:]
    for s in shots:
        s["duration"] = round(min(float(s["duration"]), SHOT_SECONDS), 4)
        s["pre"] = round(min(float(s["pre"]), s["duration"] * 0.55), 4)
        # Nothing but the part being shown: a card for a transition must not
        # also freeze, and one for a grade must not also shake.
        s["fx"], s["hero"], s["hero_fx"] = [], False, []
        s["camera"], s["speed"], s["transition"], s["tlen"] = "c00", "s00", "t01", 0.0
    proj["intro"], proj["outro"], proj["overlays"] = "i00", "e00", []
    if kind == "intro":
        proj["intro"] = part
    elif kind == "outro":
        proj["outro"] = part
    elif kind == "grade":
        proj["grade"] = part
    elif kind == "overlay":
        proj["overlays"] = [part]
        # The watermark draws the reel's handle, and a project without one
        # draws nothing -- so that card was an unmarked shot. A placeholder is
        # honest here: the card is showing where the handle sits, not whose.
        proj["handle"] = proj.get("handle") or "@yourhandle"
    elif kind == "transition":
        if len(shots) < 2:
            return None
        shots[1]["transition"] = part
    elif kind == "hero":
        shots[0]["hero"], shots[0]["hero_fx"] = True, [part]
        # The Text slam draws the shot's caption, and the clips an example is
        # cut from are single kills, which carry none -- so those cards came
        # out as a plain shot with nothing slamming into it. Give the hero
        # shot the caption a multi-kill would have earned.
        shots[0]["caption"] = shots[0].get("caption") or "DOUBLE KILL"
    else:                                   # kill, speed, camera
        key = {"kill": "fx", "speed": "speed", "camera": "camera"}[kind]
        for s in shots:
            s[key] = [part] if key == "fx" else part
    return proj


def _shrink(out: Path, width: int = CARD_WIDTH, fps: int = CARD_FPS, crf: int = CARD_CRF) -> None:
    """Card-sized and silent, in place. A failed shrink keeps the big file."""
    import subprocess

    from .tools import _NO_WINDOW, binary

    small = out.with_name(out.stem + ".card.mp4")
    argv = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(out), "-an",
            "-vf", f"fps={fps},scale={width}:-2:flags=lanczos",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(small)]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, creationflags=_NO_WINDOW)
        if r.returncode == 0 and small.is_file() and small.stat().st_size:
            small.replace(out)
            return
        log.info("examples: could not shrink %s: %s", out.name, (r.stderr or "")[-200:])
    except OSError as e:
        log.info("examples: could not shrink %s: %s", out.name, e)
    small.unlink(missing_ok=True)


def large_path(root: Path, part: str) -> Path | None:
    """The sharp copy of one part's example, if one is made and still current.

    A card cut again since (a rebuild from newer clips) makes it stale: the
    stage would show other footage than the card it stands for.
    """
    if part not in known() or part in NOTHING:
        return None
    f = folder(root) / LARGE_FOLDER / f"{part}.mp4"
    own = path_for(root, part, stock=False)
    try:
        if not f.is_file() or (own and own.stat().st_mtime > f.stat().st_mtime):
            return None
    except OSError:
        return None
    return f


def make_large(root: Path, part: str) -> dict:
    """Cut the sharp copy of one part's example. -> {"ok", "file"} | {"ok": False, "error"}

    The same two-shot project a card is cut from, rendered by the same
    StudioJob, shrunk to LARGE_WIDTH instead of CARD_WIDTH. The shots are
    usually in the render cache already, from the card, so most of the time
    this is the join and one scale.
    """
    root = Path(root)
    parts = known()
    if part not in parts or part in NOTHING:
        return {"ok": False, "error": "Nothing to show for that part."}
    clips = sources(root)
    if len(clips) < 2:
        return {"ok": False, "error": "Two clips with a kill are needed to cut a large example."}
    here = folder(root) / LARGE_FOLDER
    here.mkdir(parents=True, exist_ok=True)
    out = here / f"{part}.mp4"
    tmp = here / f"{part}.cut.mp4"
    try:
        proj = _project(part, parts[part], clips)
        if proj is None:
            return {"ok": False, "error": "No shot could be cut for it."}
        proj, derived, _notes = studio.normalise(proj, root)
        job = studio.StudioJob(proj, derived, root, tmp)
        job.run()
        snap = job.snapshot()
        if snap["state"] != "done" or not tmp.is_file():
            return {"ok": False, "error": snap.get("error") or "The render failed."}
        _shrink(tmp, LARGE_WIDTH, LARGE_FPS, LARGE_CRF)
        tmp.replace(out)
        return {"ok": True, "file": out.name}
    except Exception as e:                           # noqa: BLE001
        log.info("examples: large %s failed: %s", part, e)
        return {"ok": False, "error": str(e)[:200]}
    finally:
        tmp.unlink(missing_ok=True)
        tmp.with_suffix(".reel.json").unlink(missing_ok=True)


class _Large:
    """Sharp copies, made one at a time, the newest ask first.

    The picker asks for whichever part is on its stage; a pointer run down
    the list asks for a dozen in a second. Only the last one asked for is
    worth making next, so the queue is one deep: a newer ask replaces it.
    """

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread = None
        self._next: tuple[Path, str] | None = None
        self._doing = ""
        # A failure is remembered for a while, not for ever: clips added since
        # (the usual reason) should be tried.
        self._failed: dict[str, tuple[float, str]] = {}

    def ask(self, root: Path, part: str) -> dict:
        """-> {"state": "ready"|"making"|"failed", ...} for `part`."""
        import threading

        f = large_path(root, part)
        if f is not None:
            return {"state": "ready", "when": int(f.stat().st_mtime)}
        with self._lock:
            when, why = self._failed.get(part, (0.0, ""))
            if time.monotonic() - when < LARGE_RETRY:
                return {"state": "failed", "error": why}
            if self._doing != part:
                self._next = (Path(root), part)
                self._wake.set()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._work, daemon=True)
                self._thread.start()
        return {"state": "making"}

    def _work(self) -> None:
        while True:
            if not self._wake.wait(30):
                with self._lock:
                    if self._next is None:
                        self._thread = None
                        return
            with self._lock:
                job, self._next = self._next, None
                self._wake.clear()
                if job is None:
                    continue
                self._doing = job[1]
            out = make_large(*job)
            with self._lock:
                self._doing = ""
                if not out.get("ok"):
                    self._failed[job[1]] = (time.monotonic(), out.get("error") or "It could not be made.")


_LARGE: _Large | None = None


def large() -> _Large:
    global _LARGE
    if _LARGE is None:
        _LARGE = _Large()
    return _LARGE


def build(root: Path, only: list[str] | None = None, on_step=None,
          should_stop=None) -> dict:
    """Render an example for every part that has none. -> what was made.

    `on_step(done, total, part)` is called before each one, so a page can show
    progress; it is the only way this reports itself, and it is slow -- about
    a second a part on a machine with a GPU encoder, and about four without:
    562 missing parts measured 37 minutes. `should_stop()` is asked between
    parts, so that can be ended without quitting the app.
    """
    root = Path(root)
    parts = known()
    want = [p for p in (only or sorted(parts)) if p in parts and p not in NOTHING]
    if not only:
        want = [p for p in want if not path_for(root, p, stock=False)]
    if not want:
        return {"ok": True, "made": [], "failed": {}, "message": "Every part already has one."}
    clips = sources(root)
    if len(clips) < 2:
        return {"ok": False, "error": "Two clips with a kill are needed to cut examples from."}
    here = folder(root)
    here.mkdir(parents=True, exist_ok=True)
    _write_sources(root, clips)
    made: list[str] = []
    failed: dict[str, str] = {}
    for i, part in enumerate(want):
        if should_stop and should_stop():
            return {"ok": True, "made": made, "failed": failed, "stopped": True,
                    "message": f"Stopped. {len(made)} example(s) cut, "
                               f"{len(want) - i} left for next time."}
        if on_step:
            on_step(i, len(want), part)
        out = here / f"{part}.mp4"
        try:
            proj = _project(part, parts[part], clips)
            if proj is None:
                failed[part] = "No shot could be cut for it."
                continue
            proj, derived, _notes = studio.normalise(proj, root)
            job = studio.StudioJob(proj, derived, root, out)
            job.run()
            snap = job.snapshot()
            if snap["state"] != "done" or not out.is_file():
                failed[part] = snap.get("error") or "The render failed."
                continue
            _shrink(out)
            for stale in (".gif", ".webm"):          # one file per part
                (here / f"{part}{stale}").unlink(missing_ok=True)
            made.append(part)
        except Exception as e:                       # noqa: BLE001
            log.info("examples: %s failed: %s", part, e)
            failed[part] = str(e)[:200]
    if on_step:
        on_step(len(want), len(want), "")
    return {"ok": True, "made": made, "failed": failed,
            "message": f"{len(made)} example(s) cut" + (f", {len(failed)} failed" if failed else "")}


class _Runner:
    """The rebuild, in the background, so the page can watch it.

    One at a time: it is ffmpeg-bound, and a second would only make both slow.
    """

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._thread = None
        self._state = {"state": "idle"}
        self._stop = threading.Event()

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def busy(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def cancel(self) -> dict:
        """Stop after the part being cut. -> the status."""
        self._stop.set()
        self._set(message="Stopping after this one...")
        return self.status()

    def _set(self, **kw) -> None:
        with self._lock:
            self._state.update(kw)

    def start(self, root: Path, only: list[str] | None = None) -> dict:
        import threading

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return dict(self._state)
            self._state = {"state": "running", "done": 0, "total": 0, "part": "",
                           "made": [], "failed": {}, "message": "Starting"}
        self._stop.clear()
        began = time.monotonic()

        def work() -> None:
            def step(done: int, total: int, part: str) -> None:
                if self._stop.is_set():
                    return
                left = ""
                if done >= 3 and total > done:
                    # Measured off this run, not assumed: an encoder on a GPU
                    # is four times quicker than one on the CPU.
                    each = (time.monotonic() - began) / done
                    mins = each * (total - done) / 60
                    left = (", about " + (f"{mins:.0f} min" if mins >= 1.5
                                          else "a minute") + " left")
                self._set(done=done, total=total, part=part,
                          message=(f"Cutting {part} ({done + 1} of {total}{left})"
                                   if part else "Finishing"))
            try:
                out = build(root, only, step, self._stop.is_set)
            except Exception as e:                   # noqa: BLE001
                log.info("examples: rebuild failed: %s", e)
                self._set(state="failed", message=str(e)[:200])
                return
            self._set(state="done" if out.get("ok") else "failed",
                      made=out.get("made") or [], failed=out.get("failed") or {},
                      message=out.get("message") or out.get("error") or "")

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
        return self.status()


_RUNNER: _Runner | None = None


def runner() -> _Runner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = _Runner()
    return _RUNNER
