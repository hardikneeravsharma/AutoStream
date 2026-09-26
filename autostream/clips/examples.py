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
# it has been cut. Sixty of them then weigh about what one reel does.
CARD_WIDTH = 480
CARD_FPS = 24
CARD_CRF = 30
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
            "folder": str(folder(root))}


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
    return {"ok": True, "taken": sorted(taken), "folder": str(here)}


def sources(root: Path, want: int = 2, game: str = "") -> list[dict]:
    """The clips an example is cut from: the shortest with a kill well inside.

    Short, because every example is re-cut from these and a 90-second clip
    makes ffmpeg seek through it each time; a kill with footage either side,
    because a card that opens on a body falling shows nothing. `game` keeps
    to one game's clips -- the stock set is cut from VALORANT alone.
    """
    lib = studio.library(Path(root))
    pool = [c for g in lib.get("games") or [] for f in g.get("folders") or []
            if not game or str(g.get("game") or "").lower() == game.lower()
            for c in f.get("clips") or []
            if (c.get("kills") or []) and float(c.get("duration") or 0) > 4.0
            and float(c["kills"][0]) > 1.5]
    pool.sort(key=lambda c: float(c.get("duration") or 0))
    return pool[:want]


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


def _shrink(out: Path) -> None:
    """Card-sized and silent, in place. A failed shrink keeps the big file."""
    import subprocess

    from .tools import binary

    small = out.with_name(out.stem + ".card.mp4")
    argv = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(out), "-an",
            "-vf", f"fps={CARD_FPS},scale={CARD_WIDTH}:-2:flags=lanczos",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(CARD_CRF),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(small)]
    try:
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode == 0 and small.is_file() and small.stat().st_size:
            small.replace(out)
            return
        log.info("examples: could not shrink %s: %s", out.name, (r.stderr or "")[-200:])
    except OSError as e:
        log.info("examples: could not shrink %s: %s", out.name, e)
    small.unlink(missing_ok=True)


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
