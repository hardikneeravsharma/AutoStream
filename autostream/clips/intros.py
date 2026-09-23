"""The intro clips a reel can open with -- a GIF or a video the user supplies.

WHY THIS EXISTS
    A reel cut to a song starts where the song starts, and some songs take a
    long time to arrive. `apply_marks` already refuses to spend the first kill
    mark on an opener that cannot reach it, so the opener simply holds until
    the song does -- nine seconds of one shot, on some tracks, before anything
    happens. The built-in intro effects (a fade, a flash) are a second long and
    were never meant to cover that. Something has to be ON SCREEN during the
    build, and the honest answer is: whatever the user wants there.

WHAT AN INTRO CLIP IS, AND IS NOT
    It is NOT a shot. Shots carry kills, land on beats, and every time in the
    reel is derived from them; threading a clip with no kill through that would
    touch every calculation in studio.py. An intro clip is joined in FRONT of
    the finished reel instead -- its own seconds, then the reel entire. The
    reel's length, its cuts, its kills and its beat grid are all untouched,
    which is why this module can be small.

    It used to be laid OVER the reel's first seconds rather than in front of
    them, which is the same small-module trick and looks identical on a reel
    that opens on a held shot. On a reel that opens on a kill it covered the
    kill, and those seconds were gone from the render with nothing to say so.
    Joining costs one encode of the intro alone: see studio.intro_head_command
    and StudioJob._prepend_intro, which splice the two without the reel being
    re-encoded at all.

WHY FILES ARE COPIED IN AND RE-ENCODED
    Reusable was the requirement, and a path to somewhere on the user's disk is
    not reusable: it breaks the first time they tidy their Downloads folder. So
    an intro is copied into VIDEO_HOME/intros and becomes the app's own.

    It is re-encoded on the way in, to h264/yuv420p in an mp4, for three
    reasons that all turn out to be the same reason. A GIF cannot be scrubbed
    in a <video> tag, so it could not be trimmed by eye. A .mkv or .avi may not
    decode in the webview at all, so it could not be previewed. And an intro
    whose codec or frame rate the render has to special-case is an intro that
    fails at render time rather than at import time. One normalised mp4 per
    intro and every one of those problems is gone.

    A sidecar `<stem>.json` holds what the page needs -- length, size, whether
    it has sound -- because listing the folder otherwise means an ffprobe per
    file on every page load.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any

from .. import paths

log = logging.getLogger("autostream.intros")

# What the file dialog offers and what add() will take. GIF and WebP are here
# because "upload a gif" was the ask; the rest is what a screen recorder or a
# phone is likely to hand over.
TYPES: tuple[str, ...] = (".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi",
                          ".gif", ".webp", ".apng")

# AN INTRO IS SHORT BY DEFINITION. The cap is not about disk -- it is that a
# three-minute file is a video the user meant to clip, not an intro, and
# silently accepting it means silently transcoding it for a minute.
MAX_SECONDS = 120.0

# Nothing in the reel is larger than 1920 on its long edge, so a 4K source is
# re-encoded down: it costs nothing to look at and everything to decode.
MAX_EDGE = 1920
FPS_CAP = 60


def folder() -> Path:
    """VIDEO_HOME/intros, made if it is not there.

    Read through `paths.` at call time, never imported as a constant: the test
    fixtures rebase paths' attributes to a temp home and a captured constant
    would point at the developer's own videos folder.
    """
    d = paths.VIDEO_HOME / "intros"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sidecar(mp4: Path) -> Path:
    return mp4.with_suffix(".json")


def _read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _safe_stem(name: str) -> str:
    """A file name that survives Windows, keeps what the user recognises it by."""
    stem = re.sub(r"[^A-Za-z0-9 ._-]+", "_", Path(name).stem).strip(" ._")
    return (stem or "intro")[:60]


def _free_path(stem: str) -> Path:
    d = folder()
    p = d / f"{stem}.mp4"
    n = 2
    while p.exists():
        p = d / f"{stem} ({n}).mp4"
        n += 1
    return p


def inside(path: str | Path) -> Path | None:
    """The intro at `path`, or None if it is not one of ours.

    THE GUARD EVERY DOOR USES. A project arrives from the page and names a
    file; the media route is handed a query string. Both come here, and both
    get the same answer: an mp4 that really sits in the intros folder, or
    nothing. Without this, "play my intro" is a request to read any file on
    the disk.
    """
    if not str(path).strip():
        return None
    p = Path(path)
    try:
        if not p.is_file() or p.suffix.lower() != ".mp4":
            return None
        if not p.resolve().is_relative_to(folder().resolve()):
            return None
    except OSError:
        return None
    return p


def entry(path: str | Path) -> dict | None:
    """One intro as the page sees it, or None."""
    p = inside(path)
    if p is None:
        return None
    meta = _read_json(_sidecar(p)) or {}
    try:
        st = p.stat()
    except OSError:
        return None
    return {"path": str(p), "name": str(meta.get("name") or p.stem),
            "seconds": round(float(meta.get("seconds") or 0.0), 3),
            "width": int(meta.get("width") or 0), "height": int(meta.get("height") or 0),
            "has_audio": bool(meta.get("has_audio")),
            "when": int(meta.get("when") or st.st_mtime), "size": st.st_size}


def listing() -> list[dict]:
    """Every intro in the library, newest first."""
    try:
        files = sorted(folder().glob("*.mp4"))
    except OSError:
        return []
    out = [e for e in (entry(f) for f in files) if e]
    out.sort(key=lambda e: -e["when"])
    return out


def _measure(src: Path) -> dict:
    from .tools import media_info

    return media_info(src)


def add(src: str | Path, *, measure=_measure, encode=None) -> dict:
    """Copy a GIF or video into the library as a normalised mp4. -> the entry.

    Raises ValueError with something worth showing the user. `measure` and
    `encode` are seams for the tests, which have no ffmpeg.
    """
    p = Path(str(src))
    if not p.is_file():
        raise ValueError("That file is not there.")
    if p.suffix.lower() not in TYPES:
        raise ValueError(f"{p.suffix or 'That file'} is not a video or a GIF.")
    try:
        info = measure(p)
    except Exception as e:                                   # noqa: BLE001
        raise ValueError(f"That file could not be read: {str(e)[:160]}") from e
    seconds = float(info.get("duration") or 0.0)
    if seconds <= 0.05:
        raise ValueError("That file has no video in it.")
    if seconds > MAX_SECONDS:
        raise ValueError(f"That is {seconds / 60:.0f} minutes long. An intro is "
                         f"at most {MAX_SECONDS / 60:.0f} minutes -- trim it first.")
    out = _free_path(_safe_stem(p.name))
    keep_audio = int(info.get("audio_tracks") or 0) > 0
    (encode or _encode)(p, out, keep_audio=keep_audio)
    if not out.is_file():
        raise ValueError("The intro could not be converted.")
    got = {}
    try:
        got = measure(out)
    except Exception:                                        # noqa: BLE001
        got = {}
    meta = {"name": _safe_stem(p.name),
            "seconds": round(float(got.get("duration") or seconds), 3),
            "width": int(got.get("width") or info.get("width") or 0),
            "height": int(got.get("height") or info.get("height") or 0),
            # What the FINISHED file has, not the source: a source with a
            # silent audio track that the encode dropped must not offer sound.
            "has_audio": int(got.get("audio_tracks") or 0) > 0 if got else keep_audio,
            "when": int(time.time()), "source": str(p)}
    try:
        _sidecar(out).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    except OSError:
        pass
    log.info("added intro %s (%.1fs, %s)", out.name, meta["seconds"],
             "with sound" if meta["has_audio"] else "silent")
    return entry(out) or {"path": str(out), **meta}


def _encode(src: Path, out: Path, *, keep_audio: bool) -> None:
    """Source -> a normalised mp4 the page can scrub and the render can trust."""
    from .tools import binary, run

    scale = (f"scale='min({MAX_EDGE},iw)':'min({MAX_EDGE},ih)'"
             f":force_original_aspect_ratio=decrease,"
             f"scale=trunc(iw/2)*2:trunc(ih/2)*2")
    argv = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    # -ignore_loop 1 means "ignore the loop flag in the file", i.e. play it
    # ONCE. It reads like the opposite and is not: measured, a 4 s GIF
    # imported with `-ignore_loop 0` came back 120 s long, because 0 honours
    # the loop and the -t cap below was the only thing that ended it.
    if src.suffix.lower() in (".gif", ".webp", ".apng"):
        argv += ["-ignore_loop", "1"]
    argv += ["-i", str(src), "-t", f"{MAX_SECONDS:.2f}",
             "-vf", f"fps=fps={FPS_CAP},{scale},format=yuv420p",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-movflags", "+faststart"]
    argv += (["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
             if keep_audio else ["-an"])
    argv += [str(out)]
    p = run(argv)
    if p.returncode != 0:
        _unlink(out)
        raise ValueError((p.stderr or "ffmpeg could not convert that file.").strip()[-300:])


def _unlink(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass


def remove(path: str | Path) -> dict:
    """Delete one intro and its sidecar. -> {"ok", "name"} or raises ValueError.

    Only ever a file `inside()` vouched for, so this cannot be pointed at a
    recording by a crafted path.
    """
    p = inside(path)
    if p is None:
        raise ValueError("That intro is not in your intros folder.")
    name = (entry(p) or {}).get("name") or p.stem
    _unlink(_sidecar(p))
    try:
        p.unlink()
    except OSError as e:
        raise ValueError(f"Could not delete it: {e}") from e
    log.info("deleted intro %s", p.name)
    return {"ok": True, "name": name}
