r"""The facecam: where it comes from, and where it goes in a reel.

TWO KINDS OF FACECAM FOOTAGE
    Streamers record their camera one of two ways, and both are common:

    inset   The camera is already IN the recording, composited by OBS into a
            corner of the game. Nothing to line up -- it is the same frame --
            but it has to be cut out of the picture, so the user draws a box
            round it once on one frame of their own footage. The box is a
            fraction of the frame, so it holds for every clip recorded with
            that scene, and it is remembered for the next reel.

    file    The camera is its own video: OBS "source record", a second
            recorder, a phone. Then it must be LINED UP with the gameplay, which
            is the whole difficulty: an offset that is half a second out puts a
            laugh before the kill that caused it. `sync()` finds the offset from
            the sound both files share (the room mic in one, the game audio or
            the same mic in the other), and the page lets it be nudged by ear.

WHERE A LINK LIVES
    A facecam file belongs to what it was recorded beside: a whole session
    (a run folder, cut from one recording) or a single clip (one the user
    imported, with no recording behind it). Links are kept in the clips
    folder's own cache, `.studio/facecam.json`, so they outlive any one reel,
    and only a path that came through the OS file dialog is ever written there
    -- which is what lets `studio.normalise()` trust a facecam path that sits
    outside the clips folder: it must be one this file links.

    For a run, the offset is between the RECORDING and the camera:
    camera_time = recording_time + offset. A clip knows where it starts in its
    recording (clips.json `start`), so a clip's own offset is that plus the
    run's. For an imported clip the recording IS the clip, and start is 0.

LAYOUTS
    Vertical   stack   the camera across the top, the game below it -- the
                       usual Shorts look. `split` is the camera's share of the
                       height.
               corner  the game fills the frame, the camera sits in a corner.
    Landscape  corner  (a stack in 16:9 would squash the game to a strip).

    `layout()` turns those choices into pixel boxes for the renderer, which is
    the only place the arithmetic is done.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

FILE = "facecam.json"
SOURCES = ("none", "inset", "file")
LAYOUTS = ("stack", "corner")
VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".m4v", ".webm", ".avi", ".flv")
# A sync that cannot tell its best lag from its second best is a guess, and a
# guessed offset is worse than none: it looks right on the timeline.
SYNC_CONFIDENCE = 3.0


def _path(root: Path) -> Path:
    from .studio import CACHE_DIR
    return Path(root) / CACHE_DIR / FILE


def load(root: Path) -> dict:
    try:
        d = json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    links = d.get("links") if isinstance(d.get("links"), dict) else {}
    return {"inset": box(d.get("inset")) if d.get("inset") else None, "links": links}


def save(root: Path, data: dict) -> None:
    from ..atomic import write_text
    p = _path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_text(p, json.dumps(data, indent=1))


def box(v, default=(0.0, 0.0, 1.0, 1.0)) -> list[float]:
    """A crop box as fractions of the frame, clamped so it stays inside it."""
    try:
        x, y, w, h = (float(n) for n in v)
    except (TypeError, ValueError):
        x, y, w, h = default
    w = max(0.03, min(1.0, w))
    h = max(0.03, min(1.0, h))
    x = max(0.0, min(1.0 - w, x))
    y = max(0.0, min(1.0 - h, y))
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def settings(raw) -> dict:
    """The project's `cam`, clamped. Anything the page sends is untrusted."""
    raw = raw if isinstance(raw, dict) else {}
    pos = raw.get("pos")
    try:
        px, py = (max(0.0, min(1.0, float(n))) for n in pos)
    except (TypeError, ValueError):
        px, py = 0.0, 0.0

    def num(k, lo, hi, d):
        try:
            return round(max(lo, min(hi, float(raw.get(k)))), 4)
        except (TypeError, ValueError):
            return d
    return {
        "source": raw.get("source") if raw.get("source") in SOURCES else "none",
        "box": box(raw.get("box")),
        "layout": raw.get("layout") if raw.get("layout") in LAYOUTS else "stack",
        "split": num("split", 0.2, 0.6, 0.38),
        "pos": [round(px, 4), round(py, 4)],
        "size": num("size", 0.12, 0.6, 0.3),
        "border": bool(raw.get("border", True)),
    }


# ------------------------------------------------------------------ links

def key_for(clip: Path) -> str:
    """The run a clip was cut in: clips/<run>/clips/<file>."""
    clip = Path(clip)
    return clip.parent.parent.name if clip.parent.name == "clips" else clip.parent.name


def clip_start(clip: Path) -> float:
    """Where a clip starts in the recording it was cut from, from its run's manifest."""
    clip = Path(clip)
    run = clip.parent.parent if clip.parent.name == "clips" else clip.parent
    try:
        man = json.loads((run / "clips.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0.0
    rows = man if isinstance(man, list) else (man.get("clips") or [])
    for r in rows:
        if isinstance(r, dict) and Path(str(r.get("master") or "")).name == clip.name:
            try:
                return float(r.get("start") or 0.0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def link(root: Path, key: str, file: str, offset: float = 0.0) -> dict:
    f = Path(str(file or ""))
    if not key:
        return {"ok": False, "error": "Nothing to attach the facecam to."}
    if f.suffix.lower() not in VIDEO_EXTS or not f.is_file():
        return {"ok": False, "error": "That is not a video file."}
    d = load(root)
    d["links"][str(key)] = {"file": str(f), "offset": round(float(offset), 3)}
    save(root, d)
    return {"ok": True, "links": d["links"]}


def set_offset(root: Path, key: str, offset: float) -> dict:
    d = load(root)
    if key not in d["links"]:
        return {"ok": False, "error": "No facecam is attached there."}
    d["links"][key]["offset"] = round(float(offset), 3)
    save(root, d)
    return {"ok": True, "links": d["links"]}


def unlink(root: Path, key: str) -> dict:
    d = load(root)
    d["links"].pop(str(key), None)
    save(root, d)
    return {"ok": True, "links": d["links"]}


def remember_inset(root: Path, b) -> dict:
    d = load(root)
    d["inset"] = box(b)
    save(root, d)
    return {"ok": True, "inset": d["inset"]}


def linked_files(root: Path) -> set[str]:
    return {str(Path(v.get("file") or "")).lower()
            for v in load(root)["links"].values() if isinstance(v, dict)}


def for_clip(root: Path, clip: Path, links: dict | None = None) -> tuple[str, float] | None:
    """(facecam file, camera seconds at clip second 0) for one clip, or None.

    A link on the clip itself wins over one on its run: an imported clip has
    no run worth the name, and one clip of a session may have been recorded
    with a different camera.
    """
    from .studio import clip_id
    links = links if links is not None else load(root)["links"]
    own = links.get(clip_id(Path(clip)))
    if isinstance(own, dict) and Path(str(own.get("file") or "")).is_file():
        return str(own["file"]), float(own.get("offset") or 0.0)
    run = links.get(key_for(clip))
    if isinstance(run, dict) and Path(str(run.get("file") or "")).is_file():
        return str(run["file"]), float(run.get("offset") or 0.0) + clip_start(clip)
    return None


# ------------------------------------------------------------------ layout

def _even(v: float) -> int:
    return max(2, int(round(v / 2.0)) * 2)


def layout(fmt: str, W: int, H: int, cam: dict, fit: str, has_cam: bool,
           src_aspect: float = 16 / 9) -> dict:
    """Pixel boxes for one shot. -> {"fit", "game": [x,y,w,h], "cam": [x,y,w,h]|None, "crop"}

    `src_aspect` is the width/height of the footage the camera is cut from,
    so a box drawn on it keeps its shape in the reel.
    """
    out = {"fit": "fit" if fit == "fit" else "zoom", "game": [0, 0, W, H], "cam": None,
           "crop": list(cam.get("box") or [0, 0, 1, 1]), "border": bool(cam.get("border", True))}
    if not has_cam or cam.get("source") == "none":
        return out
    if fmt == "vertical" and cam.get("layout", "stack") == "stack":
        ch = _even(H * float(cam.get("split", 0.38)))
        out["cam"] = [0, 0, W, ch]
        out["game"] = [0, ch, W, H - ch]
        return out
    bx = out["crop"]
    aspect = (bx[3] / max(bx[2], 1e-3)) / max(src_aspect, 1e-3)   # height / width of the cut
    cw = _even(W * float(cam.get("size", 0.3)))
    ch = _even(cw * aspect)
    if ch > H * 0.7:                        # a tall slice would swallow the game
        ch = _even(H * 0.7)
        cw = _even(ch / max(aspect, 1e-3))
    m = _even(min(W, H) * 0.03)
    px, py = cam.get("pos") or [0.0, 0.0]
    x = _even(m + (W - cw - 2 * m) * float(px))
    y = _even(m + (H - ch - 2 * m) * float(py))
    out["cam"] = [min(x, W - cw), min(y, H - ch), cw, ch]
    return out


# ------------------------------------------------------------------ sync

def _envelope(path: Path, start: float, seconds: float, rate: int = 100):
    """Loudness at `rate` Hz, from a mono 8 kHz decode. None when there is no sound."""
    import subprocess

    import numpy as np

    from .tools import binary
    argv = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", f"{max(0.0, start):.3f}", "-t", f"{seconds:.3f}", "-i", str(path),
            "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
    try:
        raw = subprocess.run(argv, capture_output=True, timeout=180).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if a.size < 8000:
        return None
    hop = 8000 // rate
    n = a.size // hop
    env = np.abs(a[: n * hop]).reshape(n, hop).mean(axis=1)
    # Onsets, not loudness: two microphones at different levels agree on WHEN
    # something got louder far better than on how loud it was.
    env = np.maximum(0.0, np.diff(np.log1p(env), prepend=0.0))
    env -= env.mean()
    sd = env.std()
    return env / sd if sd > 1e-6 else None


def sync(game: Path, game_t: float, cam: Path, guess: float = 0.0,
         window: float = 40.0, search: float = 120.0) -> dict:
    """Find camera_time - game_time from the sound both share.

    Reads `window` seconds of the game from `game_t`, and `window + 2*search`
    of the camera around where `guess` says they are, and cross-correlates
    their onset envelopes. -> {"ok", "offset", "confidence"} or an error.
    """
    import numpy as np
    rate = 100
    g = _envelope(game, game_t, window, rate)
    c0 = game_t + guess - search
    c = _envelope(cam, max(0.0, c0), window + 2 * search, rate)
    if g is None or c is None:
        return {"ok": False, "error": "One of the two has no sound to line them up by."}
    if c0 < 0:                              # the camera cannot start before 0
        # Silence for the stretch before the camera started, so index 0 is
        # still time c0.
        c = np.concatenate([np.zeros(int(round(-c0 * rate))), c])
    if c.size <= g.size:
        return {"ok": False, "error": "The facecam video is too short to line up."}
    n = 1 << int(np.ceil(np.log2(c.size + g.size)))
    corr = np.fft.irfft(np.fft.rfft(c, n) * np.conj(np.fft.rfft(g, n)), n)[: c.size - g.size + 1]
    corr /= g.size
    best = int(np.argmax(corr))
    top = float(corr[best])
    # Confidence: the peak against the rest, away from the peak itself.
    mask = np.ones(corr.size, bool)
    mask[max(0, best - rate):best + rate] = False
    rest = corr[mask]
    conf = (top - float(rest.mean())) / max(float(rest.std()), 1e-6) if rest.size else 0.0
    offset = (c0 + best / rate) - game_t
    if conf < SYNC_CONFIDENCE:
        return {"ok": False, "offset": round(offset, 3), "confidence": round(conf, 2),
                "error": "The sound did not line up clearly. Set the offset by ear instead."}
    return {"ok": True, "offset": round(offset, 3), "confidence": round(conf, 2)}
