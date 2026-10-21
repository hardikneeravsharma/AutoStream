"""What a finished reel is checked against, before anyone is shown it.

WHY THIS EXISTS. Every real defect found in the first Follow-the-song reels was
found by measuring the render -- three kills under a blur, a kill whited out, a
clip played twice, a 20-second shot, a last kill under the ending fade -- and
every one of those measurements was run by hand. A reviewer (ChatGPT, asked to
rate the roadmap) put it plainly: build the gate before the wizard, because a
guided flow on top of an engine that sometimes makes a bad reel only makes bad
reels easier to make. This is the gate, in three layers kept apart:

* the PLAN checks (`plan_findings`) read the project and what derive() says of
  it -- no ffmpeg, so the check engine can run them on a plan it has not
  rendered, and a test can run them on a hand-built one;
* the RENDER checks (`render_findings`) read the finished file: it decodes, it
  is as long as the plan, every kill frame has detail;
* a finding is HARD (the reel is not shown as ready) or SOFT (said only when
  there is something to do about it). A check that could not run is a hard
  finding of its own -- not evidence of quality.

Nothing here scores a reel. A handful of independent checks, each with a
reason, is what can be acted on.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

log = logging.getLogger(__name__)

HARD, SOFT = "hard", "soft"

# What the checks compare against. Each number is a measurement, not a taste:
FAST_MAX_SHOT = 6.0        # s. The Notorious reel's 20 s shot; a build take's shots run to 3 s
FAST_MAX_GAP = 1.0         # s between two kills after the drop (director.MAX_GAP)
SHARP_MIN = 0.35           # a kill frame's detail vs the reel's median: three blurred kills read 0.00-0.17
SHARP_RADIUS = (2, 5)      # frames before and after the kill whose median must clear SHARP_MIN
LENGTH_TOLERANCE = 0.25    # s a render may differ from the plan
MAX_FROM_ONE_FILE = 4      # R13: no file gives a reel more shots than this
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class Finding:
    level: str            # HARD or SOFT
    code: str             # a short stable name tests and the page can key on
    message: str          # one sentence for the person
    at: float | None = None   # reel seconds, when it is about a moment

    def as_dict(self) -> dict:
        return asdict(self)


def ready(findings: list[Finding]) -> bool:
    """Whether the reel may be shown as ready: no hard finding."""
    return not any(f.level == HARD for f in findings)


# ------------------------------------------------------------------ the plan

def plan_findings(project: dict, derived: dict, *, fast: bool = True) -> list[Finding]:
    """Checks that need no render. `fast` is the style's reuse rule: a clip appears
    once (fast styles), or a file may give several shots but never the same fight
    twice and never back to back (the slower ones)."""
    out: list[Finding] = []
    shots = project.get("shots") or []
    rows = derived.get("shots") or []
    if not shots:
        return [Finding(HARD, "no-shots", "The reel has no shots.")]

    # every kill on its mark
    marks = derived.get("marks") or []
    if marks:
        for r in rows:
            d = r.get("drift")
            if d is not None and abs(d) > derived.get("on_mark_window", 0.05):
                out.append(Finding(HARD, "off-mark", f"A kill is {abs(d) * 1000:.0f} ms from its beat.", r.get("kill_reel")))

    # a clip, or a fight, shown twice
    by_clip: dict[str, list[int]] = {}
    for i, s in enumerate(shots):
        by_clip.setdefault(str(s["clip"]).lower(), []).append(i)
    for clip, idx in by_clip.items():
        if len(idx) < 2:
            continue
        name = Path(clip).stem
        if fast:
            lead = [i for i in idx if not _same_take(shots, idx[0], i)]
            if lead:
                out.append(Finding(HARD, "repeat", f"{name} is used twice.", rows[idx[1]]["kill_reel"] if rows else None))
        else:
            seen: list[float] = []
            for i in idx:
                for k in shots[i].get("kills") or []:
                    if any(abs(float(k) - p) < 3.0 for p in seen):
                        out.append(Finding(HARD, "repeat-fight", f"The same fight in {name} is shown twice.", rows[i]["kill_reel"]))
                    seen.append(float(k))
            if any(b - a == 1 for a, b in zip(idx, idx[1:])) and not all(_same_take(shots, idx[0], i) for i in idx):
                out.append(Finding(SOFT, "back-to-back", f"{name} plays twice in a row.", rows[idx[0]]["kill_reel"]))
            if len(idx) > MAX_FROM_ONE_FILE:
                out.append(Finding(HARD, "too-many-from-one", f"{name} gives {len(idx)} shots (the limit is {MAX_FROM_ONE_FILE}).", None))

    # one very long shot in a fast style
    if fast:
        for i, s in enumerate(shots):
            if float(s["duration"]) > FAST_MAX_SHOT and i not in _take_indexes(shots):
                out.append(Finding(HARD, "long-shot", f"One shot runs {float(s['duration']):.0f} s in a fast-cut reel.", rows[i]["start"] if rows else None))

    # the ending
    kills = derived.get("kills") or []
    if kills:
        length = float(derived.get("length") or 0.0)
        fade = float(derived.get("outro_fade") or 0.0)
        from . import studio
        if fade and length - fade < max(kills) + studio.OUTRO_AFTER_KILL - 1e-3:
            out.append(Finding(HARD, "fade-over-kill", "The ending fade starts before the last kill has played.", max(kills)))
        if length - max(kills) < 0.3:
            out.append(Finding(HARD, "no-room-after-kill", "The reel ends within a third of a second of its last kill.", max(kills)))

    # pace after the drop
    drop = project.get("song_drop")
    # Fast-paced headshot holds a cut of about a second by design (clips/fasthead.py)
    if fast and drop is not None and kills and project.get("style") != "fasthead":
        off = float(project.get("song_offset") or 0.0)
        after = [k for k in kills if k > float(drop) - off + 0.01]
        for a, b in zip(after, after[1:]):
            if b - a > FAST_MAX_GAP + 1e-6:
                out.append(Finding(SOFT, "slow-pace", f"{b - a:.1f} s between two kills after the drop.", a))
    return out


def _take_indexes(shots: list[dict]) -> set[int]:
    """The shots of the opening take: consecutive shots of one clip from the first shot on."""
    if not shots:
        return set()
    first = shots[0]["clip"]
    n = 0
    while n < len(shots) and shots[n]["clip"] == first:
        n += 1
    return set(range(n))


def _same_take(shots: list[dict], a: int, b: int) -> bool:
    take = _take_indexes(shots)
    return a in take and b in take


# ---------------------------------------------------------------- the render

def _lap(frames) -> list[float]:
    import numpy as np

    return [float(np.var(f[1:-1, 1:-1] * 4 - f[:-2, 1:-1] - f[2:, 1:-1] - f[1:-1, :-2] - f[1:-1, 2:])) for f in frames]


def _frames(ff: str, mp4: Path, crop: str, size: tuple[int, int]):
    import numpy as np

    w, h = size
    raw = subprocess.run([ff, "-v", "error", "-nostdin", "-i", str(mp4), "-vf", f"{crop},scale={w}:{h},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, creationflags=_NO_WINDOW, timeout=900).stdout
    n = len(raw) // (w * h)
    return np.frombuffer(raw[:n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)


def render_findings(mp4: Path, project: dict, derived: dict, ff: str = "ffmpeg") -> list[Finding]:
    """Checks on the finished file. Any failure to check is itself a hard finding."""
    out: list[Finding] = []
    try:
        mp4 = Path(mp4)
        if not mp4.is_file() or mp4.stat().st_size < 10_000:
            return [Finding(HARD, "no-file", "The reel file is missing or empty.")]
        from .tools import media_info

        dur = float(media_info(mp4).get("duration") or 0.0)
        if abs(dur - float(derived.get("length") or 0.0)) > LENGTH_TOLERANCE:
            out.append(Finding(HARD, "wrong-length", f"The reel is {dur:.1f} s; the plan was {float(derived['length']):.1f} s."))
        # the game's own picture sits in the middle band of a 9:16 fit layout; in a plain frame it is the frame
        vertical = project.get("format") == "vertical"
        band = {"fit": 608, "near": 810}.get(project.get("vfit") or "") if vertical else None
        crop = f"crop=iw:iw*{band}/1080:0:(ih-iw*{band}/1080)/2" if band else "crop=iw:ih:0:0"
        frames = _frames(ff, mp4, crop, (540, 304))
        if not len(frames):
            return out + [Finding(HARD, "does-not-decode", "The reel could not be read back.")]
        lap = _lap(frames)
        import numpy as np

        med = float(np.median(lap)) or 1.0
        for k in derived.get("kills") or []:
            i = int(round((float(k) + float(derived.get("offset") or 0.0)) * 60))
            win = lap[max(0, i - SHARP_RADIUS[0]):i + SHARP_RADIUS[1] + 1]
            if win and sorted(win)[len(win) // 2] / med < SHARP_MIN:
                out.append(Finding(HARD, "kill-not-sharp", "A kill is blurred or washed out where it lands.", float(k)))
    except Exception as e:                                     # noqa: BLE001
        log.info("reel check could not run: %s", e)
        out.append(Finding(HARD, "check-failed", f"The reel could not be checked ({e})."))
    return out


def check(project: dict, derived: dict, mp4: Path | None = None, *, fast: bool = True, ff: str = "ffmpeg") -> list[Finding]:
    """Plan checks, then render checks when there is a render."""
    found = plan_findings(project, derived, fast=fast)
    if mp4 is not None:
        found += render_findings(mp4, project, derived, ff)
    return found
