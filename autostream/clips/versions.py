r"""Render versions: every render of a reel is its own file, and the reel is whichever one is promoted.

A RENDER USED TO REPLACE THE REEL. It wrote `<name>.part.mp4` beside it and
swapped it in at the end, so the reel before was gone the moment a new one
landed -- and the page had to let go of the video it was showing before every
render, because Windows will not replace a file that is open. Watching the old
reel while the new one rendered was impossible, and a render that came out
worse could not be taken back.

Now each render goes to a version file of its own under `reels/.versions/<stem>/`:

    v3.mp4          the render
    v3.reel.json    the project exactly as it was rendered, plus `made_from`

and only once it has finished is it PROMOTED: `reels/<stem>.mp4` and
`<stem>.reel.json` become it. Promotion is a hard link where the drive allows
one -- the reel costs no extra space -- and a copy where it does not. A version
file is never written again once it exists, so the page plays the version file
rather than the reel's own name, and a render finishing never fights the player
for it. A render that fails leaves the reel and every version as they were.

A REEL MADE BEFORE THIS has no versions. It is migrated on first read: its
current file becomes v1, by a hard link, so nothing is copied and nothing moves.

History lists the versions, each with what it was made from; any one can be
restored (promoted again) or saved as a reel of its own.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

DIR = ".versions"
KEEP = 8                        # versions kept per reel, the promoted one always among them
_NAME = re.compile(r"^v(\d{1,6})\.mp4$")


def folder(out: Path) -> Path:
    """Where a reel's versions live."""
    out = Path(out)
    return out.parent / DIR / out.stem


def _num(p: Path) -> int:
    m = _NAME.match(p.name)
    return int(m.group(1)) if m else 0


def _read(p: Path) -> dict:
    try:
        got = json.loads(p.read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _link_or_copy(src: Path, dst: Path) -> None:
    """dst becomes src's content: a hard link when the drive takes one, else a copy."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def numbers(out: Path) -> list[int]:
    d = folder(out)
    try:
        return sorted(n for n in (_num(p) for p in d.glob("v*.mp4")) if n)
    except OSError:
        return []


def adopt(out: Path) -> None:
    """MIGRATE ON READ: a reel with no versions gets its current file as v1. Never raises."""
    out = Path(out)
    if numbers(out) or not out.is_file():
        return
    d = folder(out)
    try:
        d.mkdir(parents=True, exist_ok=True)
        _link_or_copy(out, d / "v1.mp4")
        meta = _read(out.with_suffix(".reel.json"))
        if meta:
            meta.setdefault("made_from", made_from(meta))
            meta["render_version"] = 1
            (d / "v1.reel.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    except OSError as e:
        log.warning("versions: could not adopt %s as v1 (%s)", out.name, e)


def next_file(out: Path) -> tuple[int, Path]:
    """The number and the file a new render of `out` writes to. Adopts an old reel first."""
    adopt(out)
    n = (numbers(out) or [0])[-1] + 1
    d = folder(out)
    d.mkdir(parents=True, exist_ok=True)
    return n, d / f"v{n}.mp4"


def made_from(project: dict, derived: dict | None = None) -> dict:
    """What a render was made from, in the words History shows."""
    from . import editflow

    song = str(project.get("song") or "")
    start, end = editflow.plan_part(project)
    r = project.get("render") or {}
    return {"style": str(project.get("style") or ""), "format": str(project.get("format") or ""),
            "song": Path(song).stem if song else "", "part": [round(start, 2), round(end, 2)] if song else None,
            "shots": len(project.get("shots") or []),
            "length": round(float((derived or {}).get("length") or r.get("reel") or 0.0), 2),
            "spec": editflow.spec_rev(project),
            "plan": str(project.get("plan_sig") or ""),
            "edited": bool((derived or {}).get("edited")),
            "lyrics": ((project.get("lyrics") or {}).get("look") or "off") if isinstance(project.get("lyrics"), dict) else "off"}


def write_meta(out: Path, n: int, meta: dict) -> None:
    (folder(out) / f"v{n}.reel.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


def promote(out: Path, n: int, swap) -> None:
    """Make version `n` the reel. `swap(tmp, out)` puts a file in place, waiting out a reader."""
    out = Path(out)
    src = folder(out) / f"v{n}.mp4"
    tmp = out.with_name(out.stem + f".v{n}.promote.mp4")
    try:
        tmp.unlink()
    except OSError:
        pass
    _link_or_copy(src, tmp)
    try:
        swap(tmp, out)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    meta = _read(folder(out) / f"v{n}.reel.json")
    if meta:
        meta["output"] = str(out)
        out.with_suffix(".reel.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


def current(out: Path) -> int:
    """The version the reel is now: the one its project file names, else the newest."""
    meta = _read(Path(out).with_suffix(".reel.json"))
    try:
        n = int(meta.get("render_version") or 0)
    except (TypeError, ValueError):
        n = 0
    have = numbers(out)
    return n if n in have else (have[-1] if have else 0)


def listing(out: Path) -> list[dict]:
    """Every version of a reel, newest first, with what each was made from."""
    out = Path(out)
    adopt(out)
    now = current(out)
    rows = []
    for n in reversed(numbers(out)):
        f = folder(out) / f"v{n}.mp4"
        meta = _read(f.with_suffix(".reel.json"))
        try:
            st = f.stat()
        except OSError:
            continue
        r = meta.get("render") or {}
        checks = [c for c in meta.get("checks") or [] if isinstance(c, dict)]
        rows.append({"version": n, "file": str(f), "current": n == now,
                     "when": int(r.get("when") or st.st_mtime), "size": st.st_size,
                     "made_from": meta.get("made_from") or made_from(meta),
                     "hard": sum(1 for c in checks if c.get("level") == "hard"),
                     "name": str(meta.get("name") or out.stem)})
    return rows


def project_of(out: Path, n: int) -> dict:
    """The project version `n` was rendered from, or {}."""
    return _read(folder(out) / f"v{n}.reel.json")


def fork(out: Path, n: int, new_out: Path, name: str) -> dict:
    """SAVE AS NEW REEL: version `n` becomes a reel of its own at `new_out`, with its own v1."""
    out, new_out = Path(out), Path(new_out)
    src = folder(out) / f"v{n}.mp4"
    meta = project_of(out, n)
    if not src.is_file() or not meta:
        raise FileNotFoundError(f"Version {n} of this reel is not on disk any more.")
    d = folder(new_out)
    d.mkdir(parents=True, exist_ok=True)
    _link_or_copy(src, d / "v1.mp4")
    meta = dict(meta)
    meta["name"] = name or (str(meta.get("name") or "Reel") + " (copy)")
    meta["output"] = str(new_out)
    meta["render_version"] = 1
    (d / "v1.reel.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    _link_or_copy(d / "v1.mp4", new_out)
    new_out.with_suffix(".reel.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


def prune(out: Path, keep: int = KEEP) -> None:
    """The oldest versions go past `keep`; never the promoted one. Never raises."""
    have = numbers(out)
    if len(have) <= keep:
        return
    now = current(out)
    for n in have[:len(have) - keep]:
        if n == now:
            continue
        for f in (folder(out) / f"v{n}.mp4", folder(out) / f"v{n}.reel.json"):
            try:
                f.unlink()
            except OSError:
                pass


def remove(out: Path) -> None:
    """Every version of a reel, gone with the reel. Never raises."""
    try:
        shutil.rmtree(folder(out))
    except OSError:
        pass

