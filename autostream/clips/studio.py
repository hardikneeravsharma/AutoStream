r"""Studio: every clip the user has made, and reels built from any of them.

WHAT IS DIFFERENT FROM THE SONG EDIT ON THE CLIPS PAGE
    The song edit (reel.py) cuts one recording's KILLS to a song, straight from
    the recording. The Studio works from finished CLIPS -- any number, from any
    game and any run -- because clips are what a person keeps, and recordings
    are the thing that gets deleted to free a drive. Each clip is its own
    source file, and each one already knows where its kills are: a master is
    cut starting exactly at the clip's `start`, so a kill's place inside the
    file is its time on the recording minus that start.

A REEL IS A PROJECT, NOT JUST A FILE
    A render writes `<name>.mp4` and beside it `<name>.reel.json`: every shot,
    where its kill lands, its speed, its effects, the transition into it, the
    grade, the song and where in the song the reel starts. That file is the
    timeline the page edits, and rendering it again is how an edit is applied.
    Nothing about a reel lives only inside the mp4.

TWO STAGES, AND WHY
    Stage one renders each shot to its own short file with its speed and its
    effects. Stage two joins them with transitions, lays the music under the
    game audio and draws the overlays. Shots are cached by everything that went
    into them, so changing one shot's effect re-encodes that shot and the join
    -- not every shot in the reel. On a 20-shot reel that is the difference
    between an edit that answers in seconds and one that takes minutes.

EVERY CUT AND EVERY KILL ON THE GRID
    Shot lengths and run-ups are whole beats and reel time zero is a beat of
    the song, so every cut and every kill lands on the grid by construction.
    That is the lesson measured on the 162 BPM reel (see reel.pre_roll): kills
    exact and cuts a fifth of a beat off still reads as loose.

FRAMES, NOT SECONDS, WHEN IT IS JOINED
    Each shot's start is rounded to a frame once, from the exact reel time, so
    rounding never accumulates. Transitions overlap their two shots by handles
    taken from footage either side of the cut, so a crossfade is CENTRED on the
    cut and the shot after it still starts on its beat.

WHERE THE STYLES COME FROM
    studio_refs.py: 26 popular montage edits (25 Valorant, one Call of Duty cut
    to the same song as reel v9) and reel v9 itself, measured frame by frame. A
    style's PACE and FLASH RATE are the medians of the edits it is modelled on.
    Which other effects it mixes in is taste, not measurement -- the pools name
    the parts the editing tutorials those edits come from teach -- and the
    part ids are the ones in the Montage Parts Bin.

VARIETY, NOT A RUBBER STAMP
    A reel that puts the same punch and the same flicker on every kill reads
    as a template within five shots. Each style carries POOLS of kill effects,
    transitions, hero moments, camera moves and speeds, and every shot draws
    from them with a seeded generator that never repeats the last choice. The
    seed lives in the project, so a plan is reproducible and "mix them up" is
    just a new seed.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import logging
import math
import random
import re
import subprocess
import tempfile
import threading
import time
import zlib
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import hits as hits_mod, mark as mark_mod, parts as parts_mod, rulebook, studio_refs

log = logging.getLogger(__name__)

VERSION = 1
FPS = 60
SIZES = {"landscape": (1920, 1080), "vertical": (1080, 1920)}
NO_SONG_BPM = 120.0                  # the grid a reel without a song is cut to
MAX_SHOTS = 80
CACHE_DIR = ".studio"
MIN_SHOT = 0.25                      # s. Below this a shot is a flicker, not a shot
# How far a kill may sit from the song hit it was aimed at and still count as
# landing on it: three frames of the render, which is under what an ear hears
# as early or late and what the music lane draws in green.
ON_MARK = 3.0 / FPS
# An intro clip shorter than this is a flash nobody can read, and trimming one
# to nothing by dragging a handle should leave the reel alone rather than open
# with a single frame.
MIN_INTRO_SECONDS = 0.3
# How an intro clip fills the frame when its shape is not the reel's: crop to
# fill, or letterbox to show all of it. Both are wanted -- a 16:9 clip over a
# 9:16 reel is unwatchable cropped, and a logo sting is unwatchable boxed.
INTRO_FITS = ("cover", "contain")
# Windows caps a whole command line at 32,767 characters. Kept well under it:
# the paths in the line are the user's own and can be far longer here than on
# the machine this was measured on.
CMDLINE_SAFE = 24_000


# ============================================================== the library

_FOLDER_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})_(.+?)(?:_(\d+))?$")


def _folder_label(name: str) -> str:
    """"2026-09-14_0045_VALORANT_2" -> "14 Sep 2026, 00:45 · run 2"."""
    m = _FOLDER_RE.match(name)
    if not m:
        return name
    y, mo, d, hh, mm, rest, n = m.groups()
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    try:
        mon = months[int(mo) - 1]
    except (ValueError, IndexError):
        return name
    extra = rest.split("_", 1)[1].replace("-", " ") if "_" in rest else ""
    label = f"{int(d)} {mon} {y}, {hh}:{mm}"
    if extra:
        label += f" · {extra}"
    if n:
        label += f" · run {n}"
    return label


def _read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clip_id(path: str | Path) -> str:
    return hashlib.sha1(str(path).lower().encode("utf-8")).hexdigest()[:12]


# FAVOURITES. Kept beside the clips rather than inside each run's clips.json:
# that file is written by the clip job, and a re-cut of a recording rewrites it
# whole. A star has to survive that, and survive a clip being renamed by the
# player, so it is stored by clip id -- the hash of the path clip_id() makes --
# in the clips folder's own cache.
FAV_FILE = "favourites.json"


def _fav_path(root: Path) -> Path:
    return Path(root) / CACHE_DIR / FAV_FILE


def favourites(root: Path) -> set[str]:
    """The clip ids the player has starred."""
    got = _read_json(_fav_path(root))
    if isinstance(got, dict):
        got = got.get("clips")
    return {str(x) for x in got} if isinstance(got, list) else set()


def set_favourite(root: Path, paths: list[str], on: bool = True) -> dict:
    """Star or unstar clips, by path. -> {ok, favourites: [ids], changed: n}"""
    root = Path(root)
    have = favourites(root)
    before = len(have)
    ids = {clip_id(p) for p in paths if str(p).strip()}
    have = (have | ids) if on else (have - ids)
    f = _fav_path(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"clips": sorted(have)}, indent=1), encoding="utf-8")
    tmp.replace(f)
    return {"ok": True, "favourites": sorted(have), "changed": abs(len(have) - before)}


def library(root: Path) -> dict:
    """Every clip under the clips folder, by game and then by run folder.

    Read from each run's clips.json and session.json; nothing is decoded, so
    this stays fast for hundreds of clips. A clip whose master file has gone is
    left out rather than shown as something that cannot be used.
    """
    games: dict[str, dict] = {}
    total = 0
    starred = favourites(root)
    fav_count = 0
    try:
        folders = [f for f in root.iterdir() if f.is_dir()]
    except OSError:
        folders = []
    for folder in folders:
        if folder.name.startswith((".", "_")) or folder.name == "reels":
            continue
        man = _read_json(folder / "clips.json")
        if man is None:
            continue
        sess = _read_json(folder / "session.json") or {}
        rows = man if isinstance(man, list) else (man.get("clips") or [])
        game = (man.get("game") if isinstance(man, dict) else "") or sess.get("game") or "Other"
        rows_k = [k for k in (sess.get("kills") or [])
                  if isinstance(k, dict) and k.get("time") is not None]
        kills = sorted(float(k["time"]) for k in rows_k)
        # Riot's record, not a screen reading: the Studio must not move these.
        recorded = sorted(float(k["time"]) for k in rows_k if k.get("record"))
        try:
            pre = float(((sess.get("options") or {}).get("pre_roll")) or 3.5)
        except (TypeError, ValueError):
            pre = 3.5
        clips = []
        for c in rows:
            if not isinstance(c, dict):
                continue
            master = Path(str(c.get("master") or ""))
            if not master.is_file():
                # A moved clips folder keeps its own layout; the absolute path
                # in the manifest is from wherever it used to live.
                alt = folder / "clips" / master.name
                if master.name and alt.is_file():
                    master = alt
                else:
                    continue
            try:
                start, end = float(c.get("start") or 0.0), float(c.get("end") or 0.0)
                dur = float(c.get("duration") or max(0.0, end - start))
            except (TypeError, ValueError):
                continue
            if dur <= 0:
                continue
            offs = [round(k - start, 3) for k in kills if start - 0.05 <= k <= end + 0.05]
            offs = [min(max(0.0, o), dur) for o in offs]
            from_record = bool(offs) and len(offs) == sum(
                1 for k in recorded if start - 0.05 <= k <= end + 0.05)
            if not offs:
                # No per-kill times for this run: the kill is where the cutter
                # was told to put it, the pre-roll into the clip.
                offs = [round(min(pre, dur * 0.6), 3)]
            vert = Path(str(c.get("vertical") or ""))
            try:
                mtime = int(master.stat().st_mtime)
            except OSError:
                mtime = 0
            cid = clip_id(master)
            fav_count += cid in starred
            clips.append({
                "mtime": mtime,
                "id": cid,
                "fav": cid in starred,
                "name": str(c.get("name") or master.stem),
                "path": str(master),
                "vertical": str(vert) if vert.is_file() else "",
                "duration": round(dur, 3),
                "kills": offs,
                "kill_count": int(c.get("kills") or len(offs)),
                "caption": str(c.get("caption") or ""),
                "labels": [str(x) for x in (c.get("labels") or c.get("tags") or [])],
                "at": str(c.get("at") or ""),
                "rank": int(c.get("rank") or 0),
                "game": game,
                "round": c.get("round"),
                **({"recorded": True} if from_record else {}),
            })
        if not clips:
            continue
        clips.sort(key=lambda c: (c["rank"] or 999, c["name"]))
        try:
            when = int((folder / "clips.json").stat().st_mtime)
        except OSError:
            when = 0
        g = games.setdefault(game, {"game": game, "clips": 0, "folders": []})
        g["folders"].append({"folder": str(folder), "name": folder.name,
                             "label": _folder_label(folder.name), "when": when,
                             "clips": clips})
        g["clips"] += len(clips)
        total += len(clips)
    out = sorted(games.values(), key=lambda g: (-g["clips"], g["game"]))
    for g in out:
        g["folders"].sort(key=lambda f: -f["when"])
    return {"ok": True, "root": str(root), "clip_count": total, "games": out,
            "fav_count": fav_count, "reels": reels(root)}


def reels(root: Path) -> list[dict]:
    """Finished reels, newest first, and whether each can be opened as a timeline."""
    d = root / "reels"
    out = []
    try:
        files = list(d.glob("*.mp4"))
    except OSError:
        files = []
    for mp4 in files:
        if mp4.name.endswith((".part.mp4", ".loud.mp4")):
            continue                       # a render in progress, or one that died
        proj = mp4.with_suffix(".reel.json")
        meta = _read_json(proj) if proj.is_file() else None
        try:
            when = int(mp4.stat().st_mtime)
            size = mp4.stat().st_size
        except OSError:
            continue
        out.append({"name": (meta or {}).get("name") or mp4.stem, "path": str(mp4),
                    "project": str(proj) if meta else "", "when": when, "size": size,
                    "shots": len((meta or {}).get("shots") or []),
                    "length": (meta or {}).get("render", {}).get("length"),
                    "style": (meta or {}).get("style", "")})
    out.sort(key=lambda r: -r["when"])
    return out


def delete_reels(root: Path, paths: list[str], *, dry_run: bool = False) -> dict:
    """Delete finished reels -- each mp4, its project, and any half-written part.

    -> {"reels", "bytes", "names", "missing", "errors"}. With `dry_run` nothing
    is touched and the answer says what would be: what the confirmation shows.

    ONLY WHAT reels() LISTS. A path is deleted only when it is one of the mp4s
    that function found in the reels folder, so a crafted path cannot reach a
    recording, a clip, or anything else on the disk through this door.

    THE CLIPS ARE NOT TOUCHED, and neither is the segment cache. A reel is a
    render of clips that still exist; what goes is the render. The cache is
    shared between reels and prunes itself (`_prune`), so taking a reel's
    segments out here would only make the next render of a similar reel slower.
    """
    want = {_key(p) for p in paths if str(p).strip()}
    found: set[str] = set()
    names: list[str] = []
    files: list[Path] = []
    total = 0
    for r in reels(root):
        key = _key(r["path"])
        if key not in want:
            continue
        found.add(key)
        names.append(r["name"])
        mp4 = Path(r["path"])
        # The .part/.loud names are what a render leaves behind when it dies;
        # reels() hides them, so this is the only chance to clear them.
        for f in (mp4, mp4.with_suffix(".reel.json"),
                  mp4.with_name(mp4.stem + ".part.mp4"), mp4.with_name(mp4.stem + ".loud.mp4")):
            try:
                if f.is_file():
                    files.append(f)
                    total += f.stat().st_size
            except OSError:
                continue

    out = {"reels": len(found), "bytes": total, "names": names,
           "missing": len(want - found), "errors": []}
    if dry_run:
        return out

    freed = 0
    for f in files:
        try:
            size = f.stat().st_size
            f.unlink()
            freed += size
        except FileNotFoundError:
            pass
        except OSError as e:
            out["errors"].append(f"{f.name}: {e}")
    out["bytes"] = freed
    log.info("deleted %d reel(s), %.1f MB freed%s", out["reels"], freed / 1e6,
             f"; {len(out['errors'])} could not be removed" if out["errors"] else "")
    return out


def _key(p: Path | str) -> str:
    try:
        return str(Path(p).resolve()).lower()
    except OSError:
        return str(p).lower()


def delete_clips(root: Path, paths: list[str], *, dry_run: bool = False) -> dict:
    """Delete chosen clips -- the clip and its vertical copy -- and drop them from their run's clips.json.

    -> {"clips", "bytes", "reels", "missing", "errors"}. With `dry_run` nothing
    is touched and the answer says what would be: what the confirmation shows.

    ONLY WHAT THE LIBRARY LISTS. A path is deleted only when a run's clips.json
    names it, so nothing outside the clips folder -- and nothing a run did not
    make, like its session.json, which a re-cut needs -- can be reached.

    REELS ARE NOT TOUCHED. A rendered reel is its own file; what changes is
    that opening its timeline leaves these shots out. The answer names those
    reels so the confirmation can say so first.
    """
    root_r = root.resolve()
    want = {_key(p) for p in paths if str(p).strip()}
    found: set[str] = set()
    gone: list[Path] = []
    runs: list[tuple[Path, Any, list[tuple[dict, list[Path]]]]] = []
    total = 0
    try:
        folders = [f for f in root.iterdir() if f.is_dir()]
    except OSError:
        folders = []
    for folder in folders:
        if folder.name.startswith((".", "_")) or folder.name == "reels":
            continue
        man_path = folder / "clips.json"
        man = _read_json(man_path)
        if man is None:
            continue
        rows = man if isinstance(man, list) else (man.get("clips") or [])
        hits: list[tuple[dict, list[Path]]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            master = Path(str(row.get("master") or ""))
            if master.name and not master.is_file() and (folder / "clips" / master.name).is_file():
                master = folder / "clips" / master.name
            if not master.name or _key(master) not in want:
                continue
            found.add(_key(master))
            gone.append(master)
            files = []
            for f in (master, Path(str(row.get("vertical") or ""))):
                try:
                    if f.name and f.is_file() and f.resolve().is_relative_to(root_r):
                        files.append(f)
                        total += f.stat().st_size
                except OSError:
                    continue
            hits.append((row, files))
        if hits:
            runs.append((man_path, man, hits))

    reels_hit = []
    for r in reels(root):
        meta = _read_json(Path(r["project"])) if r.get("project") else None
        if meta and any(_key(s.get("clip") or "") in found for s in meta.get("shots") or []):
            reels_hit.append(r["name"])

    out = {"clips": len(found), "bytes": total, "reels": reels_hit,
           "missing": len(want - found), "errors": []}
    if dry_run:
        return out

    from .. import atomic

    freed = 0
    for man_path, man, hits in runs:
        dropped = set()
        for row, files in hits:
            ok = True
            for f in files:
                try:
                    size = f.stat().st_size
                    f.unlink()
                    freed += size
                except FileNotFoundError:
                    pass
                except OSError as e:
                    ok = False
                    out["errors"].append(f"{f.name}: {e}")
            # A row leaves the manifest only once its files are really gone,
            # so a clip still open in a player is not listed as deleted.
            if ok:
                dropped.add(id(row))
        rows = man if isinstance(man, list) else (man.get("clips") or [])
        kept = [r for r in rows if id(r) not in dropped]
        data = kept if isinstance(man, list) else dict(man, clips=kept)
        try:
            atomic.write_json(man_path, data)
        except OSError as e:
            out["errors"].append(f"{man_path.parent.name}/clips.json: {e}")
    out["bytes"] = freed
    # A star for a clip that is gone is dead weight in the file, and would come
    # back to life if a clip were ever cut to the same path again.
    if gone:
        set_favourite(root, [str(m) for m in gone], on=False)
    log.info("deleted %d clip(s) from the clips folder, %.1f MB freed%s", out["clips"], freed / 1e6,
             f"; {len(out['errors'])} could not be removed" if out["errors"] else "")
    return out


# ============================================================== the parts

# The catalogue's own type and its generated variants live in parts.py; the
# hand-written parts stay here, beside the renderer that draws them.
Part = parts_mod.Part

PARTS: tuple[Part, ...] = (
    Part("i00", "intro", "Straight in", "No intro effect; the first shot simply starts."),
    Part("i03", "intro", "Fade up from black", "Black resolves into the first shot over a second."),
    Part("i08", "intro", "Flash in", "The edit bursts out of white."),
    Part("i12", "intro", "Colour on the first kill", "Black and white until the first kill, then full colour."),
    Part("i05", "intro", "Blur to focus", "The first shot starts soft and sharpens."),

    Part("t01", "transition", "Hard cut", "No effect; the next shot starts on the beat."),
    Part("t02", "transition", "White flash", "The cut hides inside a couple of white frames."),
    Part("t03", "transition", "Dip to black", "Fade out to black and back up."),
    Part("t04", "transition", "Crossfade", "The two shots blend through each other."),
    Part("t05", "transition", "Zoom-through", "The first shot punches in and the next emerges."),
    Part("t06", "transition", "Whip blur", "A horizontal smear carries the cut, like a flick."),
    Part("t07", "transition", "Push", "The next shot shoves the last one off screen."),
    Part("t08", "transition", "Soft wipe", "A feathered edge wipes across."),
    Part("t09", "transition", "Iris open", "The next shot opens from a circle in the centre."),
    Part("t10", "transition", "Pixel dissolve", "Breaks into blocks and rebuilds."),
    Part("t11", "transition", "Radial sweep", "Revealed by a clock-hand sweep."),
    Part("t12", "transition", "Slice across", "The frame splits into bands that slide the next shot in."),
    Part("t13", "transition", "Squeeze", "The last shot squashes out sideways as the next opens."),
    Part("t14", "transition", "Diagonal wipe", "A corner-to-corner wipe carries the cut."),
    Part("t15", "transition", "Cover slide", "The next shot slides in over the last, which stays put."),
    Part("t16", "transition", "Grain dissolve", "The two shots trade places pixel by pixel."),
    Part("t17", "transition", "Colour drain", "Drains to grey through the cut and back."),

    Part("k01", "kill", "Zoom punch", "Jumps about 12% closer on the kill and settles."),
    Part("k02", "kill", "Screen shake", "The frame rattles for under half a second."),
    Part("k03", "kill", "White flash", "One or two frames blow out to white."),
    Part("k04", "kill", "Freeze frame", "Time stops on the kill for a moment."),
    Part("k06", "kill", "RGB split", "Red and blue tear apart for a few frames."),
    Part("k07", "kill", "Saturation pop", "Muted colour until the kill, then it floods in."),
    Part("k08", "kill", "Colour hit", "A red wash flashes across the frame."),
    Part("k11", "kill", "Contrast crunch", "Blacks crush and colour hardens on the kill."),
    Part("k12", "kill", "Invert frame", "A single negative frame."),
    Part("k14", "kill", "Blur snap", "Goes soft on the kill and snaps back sharp."),
    Part("k15", "kill", "Vignette pulse", "The edges darken hard on the kill."),
    Part("k16", "kill", "Flicker", "Brightness strobes for a quarter second."),
    Part("k17", "kill", "Punch out", "Held close through the run-up, released on the kill."),
    Part("k18", "kill", "Echo trail", "Bright movement smears behind itself for a moment."),
    Part("k19", "kill", "Rotation kick", "The frame knocks a degree or so and rights itself."),
    Part("k20", "kill", "Highlight bloom", "Bright parts bloom and glow on the kill."),
    Part("k21", "kill", "Zoom blur hit", "Punches in through a blur that clears at once."),
    Part("k22", "kill", "Tilt shake", "Rattles up and down only, not side to side."),

    Part("h01", "hero", "Double punch", "Two punches a sixth of a second apart."),
    Part("h02", "hero", "Freeze and push in", "Time stops while the camera pushes in."),
    Part("h03", "hero", "Spotlight", "Everything but the centre drops into darkness."),
    Part("h05", "hero", "Text slam", "The shot's caption slams in and settles."),

    Part("s00", "speed", "Real speed", "Plays as recorded."),
    Part("s01", "speed", "Half speed", "The whole shot at half speed."),
    Part("s02", "speed", "Ramp into the kill", "Fast approach, slowing to 0.3× on the kill."),
    Part("s03", "speed", "Ramp out of the kill", "Slow on the kill, then rushes away."),
    Part("s04", "speed", "Velocity", "Rushes in, hangs on the kill, rushes out."),
    Part("s05", "speed", "Slow build", "Half speed all the way in, real speed from just before the kill."),
    Part("s06", "speed", "Slow exit", "Real speed to the kill, then slows to a third as the shot leaves."),

    Part("c00", "camera", "Still", "No added camera movement."),
    Part("c01", "camera", "Slow push-in", "Drifts steadily closer through the shot."),
    Part("c03", "camera", "Handheld drift", "A gentle organic sway."),
    Part("c04", "camera", "Beat bounce", "Pulses closer on every beat."),
    Part("c05", "camera", "Slow pull-out", "Starts close and eases back through the shot."),
    Part("c06", "camera", "Roll drift", "Rotates by a degree or two across the shot."),
    Part("c07", "camera", "Parallax pan", "Drifts sideways, as if tracking past the scene."),
    Part("c08", "camera", "Breathing zoom", "Eases in and out again, like a held breath."),

    Part("g01", "grade", "Natural", "The game's own colours."),
    Part("g02", "grade", "Warm golden", "Amber highlights."),
    Part("g03", "grade", "Teal & orange", "Cool shadows, warm highlights."),
    Part("g04", "grade", "Cold blue", "Everything cools toward blue."),
    Part("g05", "grade", "Crunch", "Hard contrast, crisp detail."),
    Part("g06", "grade", "Bleach bypass", "Washed-out colour, harsh contrast."),
    Part("g07", "grade", "Monochrome", "Black and white."),
    Part("g08", "grade", "Neon pop", "Colour pushed toward neon."),
    Part("g09", "grade", "Faded film", "Lifted blacks and soft highlights."),
    Part("g10", "grade", "Radiant purple", "Valorant's own violet pushed through the shadows."),
    Part("g11", "grade", "Poster", "Colour flattened into bands, like cel shading."),
    Part("g12", "grade", "Night vision", "Everything green, blacks lifted, highlights hot."),

    # The drawer needs its empty card too: a template picks one part from
    # every drawer, and most reels carry no overlay at all.
    Part("o00", "overlay", "No overlay", "Nothing over the picture."),
    Part("o01", "overlay", "Cinematic bars", "Black bars top and bottom (landscape only)."),
    Part("o02", "overlay", "Kill counter", "A running count ticks up with each kill."),
    Part("o04", "overlay", "Film grain", "Fine moving grain over the whole reel."),
    Part("o05", "overlay", "Scanlines", "Fine horizontal lines, like an old monitor. "
         "Costs about a second of render for every second of reel."),
    Part("o08", "overlay", "Chromatic edges", "A constant hair of colour fringing at the edges."),
    Part("o07", "overlay", "Handle watermark", "Your handle in the corner."),
    Part("i04", "overlay", "Now-playing card", "Names the track for the first few seconds."),

    Part("e12", "outro", "Hard cut", "Stops dead on the last beat."),
    Part("e01", "outro", "Fade to black", "The last shot fades out."),
    Part("e05", "outro", "Flash to white", "Burns out to white."),
    Part("e02", "outro", "Freeze and fade colour", "The final second freezes and drains to grey."),
    Part("e03", "outro", "Slow-mo exit", "The last kill slows down and fades."),
)
PARTS = tuple(parts_mod.distinct(
    PARTS + tuple(parts_mod.variants({p.id: p.kind for p in PARTS}))))
PART = {p.id: p for p in PARTS}


def fam(pid: str) -> str:
    """Which family's filter draws this part. Unknown ids are their own family."""
    p = PART.get(pid)
    return p.family if p else pid


def knob(pid: str, name: str, default: float) -> float:
    """One of a part's numbers, or the family default for a hand-written part."""
    p = PART.get(pid)
    return p.knob(name, default) if p else default


def picked(fx, family: str) -> str:
    """The id in `fx` belonging to `family`, or "" -- so the renderer can ask
    "is there a punch here" without knowing which of the punches it is."""
    for pid in fx or ():
        if fam(pid) == family:
            return pid
    return ""
KINDS = ("intro", "transition", "kill", "hero", "speed", "camera", "grade", "overlay", "outro")


def ids_of(kind: str) -> list[str]:
    return [p.id for p in PARTS if p.kind == kind]


# A TEMPLATE IS ONE PICK FROM EVERY DRAWER. That is all a style is, so a
# template is a style with its picks replaced -- everything downstream (the
# effect mix, the flash budget, the climax) then works exactly as it does for
# a built-in style, and the reel maker can show the player each pick with its
# own example playing beside it.
DRAWERS: tuple[str, ...] = ("intro", "transition", "kill", "hero", "camera",
                            "speed", "grade", "overlay", "outro")


def _leads(pick: str, pool: tuple) -> tuple:
    """`pick` first and twice as likely, with the style's own pool behind it.

    A drawer that is picked is not a drawer emptied. The kill, transition and
    hero drawers are drawn from once per SHOT, and a pool of one put the same
    effect on every kill in a row -- which the reference edits never do and
    rulebook.budget exists to prevent. Listing a part twice is how a pool says
    "mostly this" (see Style.kill_pool).
    """
    # Distinct, because a style already lists a part twice to make it likelier
    # and that would dilute the pick against its own drawer.
    rest = tuple(dict.fromkeys(p for p in (pool or ()) if p != pick))
    # Twice as likely as anything else, and the style's own parts still behind
    # it. Not the pick alone, and not the pick against ONE alternate either:
    # _vary refuses to repeat the last two kill effects, so a pool of two runs
    # out of fresh choices and starts repeating anyway (k06 k01 k06 k06 k01).
    return (pick,) * max(2, len(rest)) + rest


def templated(style: "Style", picks: dict) -> "Style":
    """`style` with the picks a template makes. Unknown ids are ignored."""
    swap: dict = {}
    for kind in DRAWERS:
        pick = str((picks or {}).get(kind) or "").strip()
        if not pick or pick not in ids_of(kind):
            continue
        if kind == "intro":
            swap["intro"] = pick
        elif kind == "outro":
            swap["outro"] = pick
        elif kind == "grade":
            swap["grade"] = pick
        elif kind == "overlay":
            swap["overlays"] = () if pick in ("o00", "") else (pick,)
        elif kind == "transition":
            swap["cuts"] = (pick,)
            swap["transition_pool"] = _leads(pick, style.transition_pool)
        elif kind == "kill":
            swap["kill"] = (pick,)
            swap["kill_pool"] = _leads(pick, style.kill_pool)
        elif kind == "hero":
            swap["hero"] = (pick,)
            swap["hero_pool"] = _leads(pick, style.hero_pool)
        elif kind == "camera":
            swap["camera"] = pick
            swap["camera_pool"] = (pick,)
        elif kind == "speed":
            swap["speed"] = pick
            swap["speed_pool"] = (pick,)
    return dataclasses.replace(style, **swap) if swap else style


def picks_of(style: "Style") -> dict:
    """The template a style already is: one pick per drawer."""
    return {"intro": style.intro, "outro": style.outro, "grade": style.grade,
            "overlay": (style.overlays or ("o00",))[0],
            "transition": (style.cuts or ("t01",))[0], "kill": (style.kill or ("k01",))[0],
            "hero": (style.hero or ("h01",))[0], "camera": style.camera, "speed": style.speed}


XFADE = {"t02": "fadewhite", "t03": "fadeblack", "t04": "fade", "t05": "zoomin",
         "t06": "hblur", "t07": "slideleft", "t08": "smoothleft", "t09": "circleopen",
         "t10": "pixelize", "t11": "radial", "t12": "hlslice", "t13": "squeezeh",
         "t14": "diagtl", "t15": "coverleft", "t16": "dissolve", "t17": "fadegrays"}
def _xfade_name(pid: str) -> str:
    """The xfade preset a transition draws with, hand-written or generated."""
    if pid in XFADE:
        return XFADE[pid]
    return parts_mod.XFADE_NAMES[int(knob(pid, "preset", 0.0))]


def _cut_seconds(pid: str) -> float:
    """How long a cut runs."""
    if pid in TLEN:
        return TLEN[pid]
    return knob(pid, "secs", 0.32)


TLEN = {"t01": 0.0, "t02": 0.2, "t03": 0.4, "t04": 0.5, "t05": 0.3, "t06": 0.25,
        "t07": 0.3, "t08": 0.4, "t09": 0.4, "t10": 0.35, "t11": 0.4,
        # The fast ones stay under a third of a second: a slice or a squeeze
        # that outlasts the shot it joins reads as the effect, not the cut.
        "t12": 0.3, "t13": 0.3, "t14": 0.35, "t15": 0.3, "t16": 0.35, "t17": 0.4}

# (saturation, contrast, brightness, static filters)
GRADES = {
    "g01": (1.0, 1.0, 0.0, ""),
    "g02": (1.10, 1.02, 0.02, "colorbalance=rs=0.08:gs=0.02:bs=-0.08:rm=0.06:bm=-0.05"),
    "g03": (1.15, 1.04, 0.0, "colorbalance=rs=-0.12:bs=0.14:rh=0.12:bh=-0.12"),
    "g04": (0.90, 1.02, 0.0, "colorbalance=rs=-0.08:bs=0.12:rm=-0.05:bm=0.08"),
    "g05": (1.20, 1.22, -0.02, "unsharp=5:5:0.8"),
    "g06": (0.45, 1.25, 0.0, ""),
    "g07": (0.0, 1.2, 0.0, ""),
    "g08": (1.70, 1.10, 0.0, "colorbalance=bh=0.06:rh=0.04"),
    "g09": (0.85, 1.0, 0.0, "curves=all='0/0.08 0.5/0.5 1/0.92',colorbalance=rs=0.03:bs=-0.02"),
    # Valorant draws its own UI in this violet, so a grade that leans into it
    # sits on the game rather than on top of it.
    "g10": (1.25, 1.08, 0.0, "colorbalance=rs=0.10:bs=0.16:gs=-0.06:rh=0.04:bh=0.06"),
    # Banded by a lookup, not by elbg's vector quantiser: measured, elbg costs
    # 200 ms a frame at 1080p, which is six minutes on a one-minute reel.
    "g11": (1.35, 1.12, 0.0, "lutyuv=y='(floor(val/26))*26'"),
    "g12": (0.0, 1.15, 0.03, "colorchannelmixer=rr=0.18:rg=0.60:rb=0.10:"
                             "gr=0.18:gg=1.00:gb=0.10:br=0.10:bg=0.40:bb=0.10"),
}


def _grade_of(pid: str) -> tuple[float, float, float, str]:
    """A grade's numbers: the hand-written table, or a tint built from a hue.

    A generated tint is one colourbalance push plus saturation and contrast.
    Doing it off a hue wheel rather than by hand is what makes sixty of them
    possible; the strength knob is what keeps a wash from being a costume.
    """
    if pid in GRADES:
        return GRADES[pid]
    if fam(pid) != "tint":
        return GRADES["g01"]
    hue = knob(pid, "hue", 200.0)
    k = knob(pid, "strength", 0.55)
    # The push, as a shadow/highlight split: shadows toward the hue and
    # highlights away from it is what separates a GRADE from a colour filter.
    h = math.radians(hue)
    r, g, b = math.cos(h), math.cos(h - 2.0944), math.cos(h + 2.0944)
    def lvl(v: float, scale: float) -> float:
        return round(max(-0.9, min(0.9, v * k * scale)), 3)
    static = (f"colorbalance=rs={lvl(r, 0.22)}:gs={lvl(g, 0.22)}:bs={lvl(b, 0.22)}"
              f":rh={lvl(-r, 0.12)}:gh={lvl(-g, 0.12)}:bh={lvl(-b, 0.12)}")
    return (knob(pid, "sat", 1.12), knob(pid, "con", 1.06), 0.0, static)


# ============================================================== the styles

@dataclass(frozen=True)
class Style:
    key: str
    label: str
    blurb: str
    refs: tuple[str, ...]
    intro: str
    outro: str
    cuts: tuple[str, ...]          # transitions cycled through on ordinary cuts
    kill: tuple[str, ...]
    hero: tuple[str, ...]
    speed: str
    hero_speed: str
    camera: str
    grade: str
    vignette: bool
    overlays: tuple[str, ...] = ()
    pre_share: float = 0.5         # of each shot, how much comes before its kill
    drop: bool = False             # land a kill on the song's drop
    # What shots draw from. A part listed twice is drawn about twice as often.
    kill_pool: tuple[str, ...] = ("k01",)
    transition_pool: tuple[str, ...] = ("t01",)
    hero_pool: tuple[str, ...] = ("h01",)
    camera_pool: tuple[str, ...] = ("c00",)
    speed_pool: tuple[str, ...] = ("s00",)
    energy: float = 0.4            # chance a kill stacks a second effect


STYLES: tuple[Style, ...] = (
    Style("story", "Story",
          "A calm held opening, fights with room to breathe, few flashes and a slow fade — "
          "the shape of your reel v9.",
          ("v9", "RjCsmKbYY7g", "yBvW49SD20Y", "8KKGT4JXPVY", "8bQ-8ZnHG4A"),
          intro="i03", outro="e01", cuts=("t01", "t04", "t01"), kill=("k01",), hero=("h03",),
          speed="s00", hero_speed="s01", camera="c01", grade="g01", vignette=False,
          kill_pool=("k01", "k01", "k15", "k14", "k07", "k04", "k17", "k20"),
          transition_pool=("t01", "t01", "t04", "t01", "t03", "t08", "t17"),
          hero_pool=("h03", "h02"), camera_pool=("c01", "c03", "c00", "c05", "c08"),
          speed_pool=("s00", "s00", "s00", "s02"), energy=0.15),
    Style("montage", "Montage",
          "The shape of the most-watched Valorant montages: a held opening, a punch on every kill, "
          "flashes on most cuts and the odd zoom-through.",
          ("JsTJ60BPTfQ", "c1VjTbzcEds", "vQqU0F8vTOE", "DM3eKiZD3XE", "qAlD8eNIfr8", "fAyUxeDzKlI"),
          intro="i03", outro="e01", cuts=("t01", "t05", "t01", "t06"), kill=("k01", "k03"),
          hero=("h01",), speed="s00", hero_speed="s02", camera="c00", grade="g02", vignette=True,
          kill_pool=("k01", "k01", "k03", "k02", "k15", "k07", "k11", "k06", "k17", "k20"),
          transition_pool=("t01", "t01", "t05", "t06", "t01", "t06", "t15"),
          hero_pool=("h01", "h02", "h05"), camera_pool=("c00", "c00", "c01", "c04", "c05"),
          speed_pool=("s00", "s00", "s00", "s02"), energy=0.45),
    Style("velocity", "Velocity short",
          "Built like the short edits that go viral: every kill slows on its beat, everything "
          "between rushes, with flicker and hard flashes.",
          ("xrgExBQyHBc", "nqa8RP_R0cU", "Ro6MDXmB8uA", "oJDesm--wss", "H2N0eHGOi_w",
           "RmaACKww8do", "prevxQTdkGo", "-rkr4IpA3jM"),
          intro="i08", outro="e12", cuts=("t06", "t05"), kill=("k01", "k16"), hero=("h02",),
          speed="s04", hero_speed="s04", camera="c00", grade="g05", vignette=True,
          overlays=("o01",),
          kill_pool=("k01", "k16", "k06", "k03", "k02", "k14", "k11", "k12", "k19", "k21"),
          transition_pool=("t06", "t05", "t01", "t06", "t02", "t12", "t13"),
          hero_pool=("h02", "h01", "h05"), camera_pool=("c00", "c00", "c04", "c08"),
          speed_pool=("s04", "s04", "s02", "s03"), energy=0.75),
    Style("drop", "Build and drop",
          "Long shots through the build, a kill exactly on the song's drop, then quicker shots "
          "through it. Needs a song with a clear drop.",
          ("FEKdk-cPVmg", "nkAEXZE76II", "66zl0-VoWbg"),
          intro="i03", outro="e01", cuts=("t01",), kill=("k01",), hero=("h01",),
          speed="s00", hero_speed="s02", camera="c00", grade="g01", vignette=True, drop=True,
          kill_pool=("k01", "k01", "k03", "k15", "k02", "k07", "k20"),
          transition_pool=("t01", "t01", "t05", "t04", "t01", "t06", "t14"),
          hero_pool=("h01", "h02"), camera_pool=("c00", "c01", "c00", "c05"),
          speed_pool=("s00", "s00", "s02"), energy=0.35),
    Style("hype", "Hype",
          "Fast and loud like the busiest montages: a cut every couple of beats, shake on every "
          "kill, crunchy colour and a kill counter.",
          ("wlNmShwGaJY", "0OvnyxlKLeQ", "FEKdk-cPVmg", "66zl0-VoWbg"),
          intro="i08", outro="e05", cuts=("t01", "t01", "t05"), kill=("k01", "k02"),
          hero=("h01",), speed="s00", hero_speed="s02", camera="c04", grade="g05",
          vignette=True, overlays=("o02",),
          kill_pool=("k01", "k02", "k11", "k06", "k08", "k16", "k12", "k03", "k19", "k22", "k18"),
          transition_pool=("t01", "t05", "t01", "t06", "t02", "t12", "t13"),
          hero_pool=("h01", "h05", "h02"), camera_pool=("c04", "c00", "c04", "c03", "c07"),
          speed_pool=("s00", "s00", "s02", "s03"), energy=0.7),
    # ---- five more, each grouped by what its references MEASURE, not by taste.
    Style("clean", "Clean",
          "The calm end of the shelf: long shots, almost no effects, the game's own "
          "colours. Modelled on the edits that cut 17-21 times a minute and flash barely at all.",
          ("RjCsmKbYY7g", "yBvW49SD20Y", "8KKGT4JXPVY"),
          intro="i03", outro="e01", cuts=("t01", "t01", "t04"), kill=("k01soft",),
          hero=("h03",), speed="s00", hero_speed="s01", camera="c01soft", grade="g01",
          vignette=False, pre_share=0.55,
          kill_pool=("k01soft", "k01", "k01soft", "k17soft", "k14soft", "k15soft"),
          transition_pool=("t01", "t01", "t01", "t04", "t08", "t17"),
          hero_pool=("h03", "h02"), camera_pool=("c00", "c01soft", "c01hair", "c05soft"),
          speed_pool=("s00", "s00", "s00", "s05"), energy=0.08),
    Style("chaos", "Chaos",
          "Everything at once, the way the busiest edits do it: 45-58 cuts a minute and "
          "40-79 flashes. Loud on purpose, and not for every song.",
          ("nqa8RP_R0cU", "xrgExBQyHBc", "66zl0-VoWbg", "oJDesm--wss"),
          intro="i08", outro="e05", cuts=("t02", "t06", "t13"), kill=("k01snap", "k03wide"),
          hero=("h01", "h05"), speed="s04", hero_speed="s04", camera="c04hard", grade="g05",
          vignette=True, overlays=("o08",), pre_share=0.4,
          kill_pool=("k01snap", "k03wide", "k02hard", "k19hard", "k06wide", "k16hard",
                     "k21hard", "k12flash", "k22hard", "k18short"),
          transition_pool=("t02", "t06", "t13", "t12", "t05", "t01"),
          hero_pool=("h01", "h05", "h02"),
          camera_pool=("c04hard", "c04slam", "c00", "c06far"),
          speed_pool=("s04", "s04", "s03", "s02"), energy=0.9),
    Style("short", "Short", 
          "Built for a Short: under half a minute, a cut a second, and the mark of the "
          "vertical edits -- quick in, quick out, nothing held.",
          ("H2N0eHGOi_w", "DrC9DxQ27lI", "prevxQTdkGo", "8bQ-8ZnHG4A"),
          intro="i08", outro="e12", cuts=("t06", "t01", "t05"), kill=("k01hard", "k03"),
          hero=("h02",), speed="s02", hero_speed="s04", camera="c00", grade="g08",
          vignette=True, pre_share=0.45,
          kill_pool=("k01hard", "k03", "k02fast", "k14", "k19", "k07hard", "k20blink"),
          transition_pool=("t06", "t01", "t05", "t12", "t01"),
          hero_pool=("h02", "h01"), camera_pool=("c00", "c00", "c04soft", "c08soft"),
          speed_pool=("s02", "s04", "s00", "s03"), energy=0.6),
    Style("cinematic", "Cinematic",
          "Bars, a graded picture and a camera that never stops moving. The slower "
          "references, played like a trailer rather than a montage.",
          ("fAyUxeDzKlI", "8KKGT4JXPVY", "RjCsmKbYY7g"),
          intro="i03", outro="e02", cuts=("t04", "t01", "t17"), kill=("k01settle",),
          hero=("h02",), speed="s00", hero_speed="s01", camera="c01soft", grade="g03",
          vignette=True, overlays=("o01",), pre_share=0.6,
          kill_pool=("k01settle", "k01soft", "k15soft", "k20slow", "k14breath", "k17slow"),
          transition_pool=("t04", "t01", "t17", "t08", "t01", "t03"),
          hero_pool=("h02", "h03"),
          camera_pool=("c01soft", "c01in", "c05soft", "c08soft", "c06hair"),
          speed_pool=("s00", "s05", "s01", "s06"), energy=0.2),
    Style("retro", "Retro",
          "Grain, scanlines and faded colour over a mid-paced cut -- the look the "
          "2010s montages had, on the references that sit nearest that pace.",
          ("DM3eKiZD3XE", "qAlD8eNIfr8", "c1VjTbzcEds"),
          intro="i05", outro="e01", cuts=("t01", "t16", "t04"), kill=("k01", "k16soft"),
          hero=("h01",), speed="s00", hero_speed="s02", camera="c03soft", grade="g09",
          vignette=True, overlays=("o04heavy",), pre_share=0.5,
          kill_pool=("k01", "k16soft", "k06thin", "k12one", "k11flat", "k14", "k18faint"),
          transition_pool=("t01", "t16", "t04", "t01", "t10", "t03"),
          hero_pool=("h01", "h03"), camera_pool=("c03soft", "c00", "c01hair", "c03"),
          speed_pool=("s00", "s00", "s01", "s02"), energy=0.35),
)
STYLE = {s.key: s for s in STYLES}
DEFAULT_STYLE = "montage"


def favourite_parts() -> list[str]:
    """The PARTS marked as favourites, ignoring any whose id no longer exists.

    Not to be confused with favourites()/set_favourite() above, which star
    CLIPS in the library. Parts are starred per install and live in the config
    directory; clips are starred per clips folder.
    """
    from .. import paths

    return [p for p in parts_mod.load_favourites(paths.CONFIG_DIR) if p in PART]


def set_favourite_part(pid: str, on: bool) -> list[str]:
    """Mark or unmark one part. -> the list as it now stands.

    Marking appends rather than inserts, so the list reads in the order things
    were found -- which is the order a person remembers choosing them in.
    """
    from .. import paths

    if pid not in PART:
        raise ProjectError("There is no such part.")
    now = [p for p in favourite_parts() if p != pid]
    if on:
        now.append(pid)
    return parts_mod.save_favourites(paths.CONFIG_DIR, now)


def catalog() -> dict:
    """What the page needs to offer every choice, and why each style is what it is."""
    return {
        "ok": True,
        "parts": [p.__dict__ for p in PARTS],
        "favourite_parts": favourite_parts(),
        "kinds": list(KINDS), "drawers": list(DRAWERS),
        "styles": [{"key": s.key, "label": s.label, "blurb": s.blurb,
                    "measured": studio_refs.summary(s.refs),
                    "defaults": {"intro": s.intro, "outro": s.outro, "cuts": list(s.cuts),
                                 "kill": list(s.kill), "hero": list(s.hero), "speed": s.speed,
                                 "hero_speed": s.hero_speed, "camera": s.camera,
                                 "grade": s.grade, "vignette": s.vignette,
                                 "overlays": list(s.overlays)},
                    "pools": _style_pools(s), "energy": s.energy,
                    # The template this style already is: one pick per drawer,
                    # which the parts bin shows with an example each.
                    "picks": picks_of(s)}
                   for s in STYLES],
        "default_style": DEFAULT_STYLE,
    }


POOL_KINDS = {"kill": "kill", "transition": "transition", "hero": "hero",
              "camera": "camera", "speed": "speed"}


def _style_pools(style: "Style") -> dict:
    """The distinct parts each pool offers, in the style's order."""
    return {"kill": list(dict.fromkeys(style.kill_pool)),
            "transition": list(dict.fromkeys(style.transition_pool)),
            "hero": list(dict.fromkeys(style.hero_pool)),
            "camera": list(dict.fromkeys(style.camera_pool)),
            "speed": list(dict.fromkeys(style.speed_pool))}


# ============================================================== the grid

@dataclass
class Grid:
    """Beats in REEL time, and the song offset that produced them."""
    beat: float
    offset: float = 0.0
    beats: list[float] = field(default_factory=list)   # song seconds
    drop: float | None = None                            # song seconds
    drums_in: float | None = None
    seconds: float = 0.0                                  # song length; 0 = no song
    bpm: float = NO_SONG_BPM
    downbeat_pos: int = 0
    peaks: list[float] = field(default_factory=list)   # the song's loudness envelope
    hits: list[float] = field(default_factory=list)    # where the song hits, song seconds
    hit_strength: list[float] = field(default_factory=list)
    big: list[float] = field(default_factory=list)     # the strongest of them
    pattern: str = ""                                  # what those hits are

    @classmethod
    def none(cls) -> "Grid":
        return cls(beat=60.0 / NO_SONG_BPM, bpm=NO_SONG_BPM)

    @classmethod
    def of(cls, shape) -> "Grid":
        return cls(beat=shape.beat, beats=list(shape.beats), drop=shape.drop,
                   drums_in=shape.drums_in, seconds=shape.seconds, bpm=shape.bpm,
                   downbeat_pos=getattr(shape, "downbeat_pos", 0),
                   peaks=list(getattr(shape, "peaks", None) or []),
                   hits=list(getattr(shape, "hits", None) or []),
                   hit_strength=list(getattr(shape, "hit_strength", None) or []),
                   big=list(getattr(shape, "big", None) or []),
                   pattern=str(getattr(shape, "pattern", "") or ""))

    def index_at_or_after(self, t: float) -> int:
        for i, b in enumerate(self.beats):
            if b >= t - 1e-6:
                return i
        return max(0, len(self.beats) - 1)


def _pow2_beats(seconds: float, beat: float, lo: int = 1, hi: int = 16) -> int:
    """The power-of-two number of beats closest to `seconds`."""
    want = max(1e-6, seconds / beat)
    best = min((2 ** k for k in range(0, 5)), key=lambda n: abs(math.log(n / want)))
    return int(max(lo, min(hi, best)))


def _grid_step(raw, beat: float) -> float:
    """A project's grid step: the beat, or the half or quarter of it it was planned on."""
    try:
        step = float(raw)
    except (TypeError, ValueError):
        return round(beat, 6)
    if not math.isfinite(step) or step <= 0:
        return round(beat, 6)
    div = min((1, 2, 4), key=lambda d: abs(step - beat / d))
    return round(beat / div, 6)


def _grid_div(shot_seconds: float, beat: float) -> int:
    """How many grid steps make a beat, for a style that wants this shot length.

    A shot is never fewer than two steps once the phrase shape and the run-up
    have had their say, so the step has to be at most half the shot the style
    is aiming for. Whole beats until the target drops under a beat and a half,
    then half beats, then quarters -- which is as fine as the references go:
    the fastest of the 27 measured holds 0.43 s, a third of a beat at 45 BPM
    and rather more at the tempos these songs run at.
    """
    want = max(1e-6, shot_seconds / beat)
    if want >= 1.5:
        return 1
    return 2 if want >= 0.7 else 4


# ============================================================== speed

def pieces(speed: str, dur: float, pre: float,
           stretch=None) -> list[tuple[float, float, float]]:
    """Output-time pieces of one shot: (start, end, playback rate), covering [0, dur].

    `pre` is where the kill falls in the shot's output time. Every preset keeps
    the kill inside a slow piece or at real speed, so it is still on screen
    when it lands on its beat.

    `stretch` is (rate, real, hold): the run-up slowed to `rate` up to the
    last `real` seconds before the kill, which play as recorded, after the
    opening frame is held for `hold` seconds -- see stretch_to(). It is how a
    clip with three seconds of footage fills the ten seconds before its mark
    while its kill still lands exactly on it.
    """
    k = max(0.0, min(dur, pre))
    if stretch:
        rate, real = float(stretch[0]), max(0.0, min(k, float(stretch[1])))
        hold = max(0.0, min(k - real, float(stretch[2]) if len(stretch) > 2 else 0.0))
        # A held frame is a piece so slow that one source frame covers it:
        # the renderer's fps filter repeats that frame, which is a freeze,
        # and nothing downstream needs to know freezes exist.
        raw = [(0.0, hold, HOLD_RATE), (hold, k - real, rate), (k - real, dur, 1.0)]
    elif speed == "s01":
        raw = [(0.0, dur, 0.5)]
    elif speed == "s02":
        raw = [(0.0, k - 0.45, 1.6), (k - 0.45, k - 0.15, 0.7), (k - 0.15, k + 0.55, 0.3),
               (k + 0.55, dur, 1.0)]
    elif speed == "s03":
        raw = [(0.0, k - 0.15, 1.0), (k - 0.15, k + 0.5, 0.3), (k + 0.5, k + 0.8, 1.0),
               (k + 0.8, dur, 2.2)]
    elif speed == "s04":
        raw = [(0.0, k - 0.3, 2.2), (k - 0.3, k + 0.45, 0.3), (k + 0.45, dur, 2.2)]
    elif speed == "s05":
        raw = [(0.0, k - 0.15, 0.5), (k - 0.15, dur, 1.0)]
    elif speed in ("exit", "s06"):
        raw = [(0.0, k + 0.1, 1.0), (k + 0.1, dur, 0.35)]
    else:
        raw = [(0.0, dur, 1.0)]
    out = []
    for a, b, r in raw:
        a, b = max(0.0, a), min(dur, b)
        if b - a > 1e-4:
            out.append((round(a, 5), round(b, 5), r))
    if not out:
        out = [(0.0, dur, 1.0)]
    # Close any gap left by clipping so the pieces tile [0, dur] exactly.
    fixed = [out[0]]
    for a, b, r in out[1:]:
        fixed.append((fixed[-1][1], b, r))
    fixed[0] = (0.0, fixed[0][1], fixed[0][2])
    fixed[-1] = (fixed[-1][0], dur, fixed[-1][2])
    return fixed


def shot_pieces(shot: dict, dur: float | None = None, pre: float | None = None,
                speed: str | None = None) -> list[tuple[float, float, float]]:
    """pieces() for a shot as it stands, stretch included."""
    return pieces(speed or shot["speed"], shot["duration"] if dur is None else dur,
                  shot["pre"] if pre is None else pre, _stretch_of(shot))


def _stretch_of(shot: dict):
    st = shot.get("stretch")
    if not st:
        return None
    try:
        rate, real = float(st[0]), float(st[1])
        hold = float(st[2]) if len(st) > 2 else 0.0
    except (TypeError, ValueError, IndexError):
        return None
    return (rate, real, hold) if 0 < rate < 1 else None


def source_used(ps: list[tuple[float, float, float]], upto: float) -> float:
    """Seconds of source consumed by output time `upto`."""
    used = 0.0
    for a, b, r in ps:
        if upto <= a:
            break
        used += (min(b, upto) - a) * r
    return used


def output_at(ps: list[tuple[float, float, float]], src: float) -> float:
    """Output time at which `src` seconds of source (from the shot's start) is shown."""
    used = 0.0
    for a, b, r in ps:
        span = (b - a) * r
        if src <= used + span + 1e-9:
            return a + (src - used) / r
        used += span
    return ps[-1][1]


# ============================================================== planning

def _choose_offset(grid: Grid, first_kill_reel: float, style: Style,
                   drop_kill_reel: float | None, energy=None, build: bool = False) -> float:
    """Where in the song reel time zero sits. Always exactly on a beat."""
    if not grid.beats:
        return 0.0
    if style.drop and grid.drop and drop_kill_reel is not None:
        off = grid.drop - drop_kill_reel
        if off >= 0:
            i = grid.index_at_or_after(off)
            return grid.beats[i]
    if style.key == "story" and not build:
        return grid.beats[0]
    start = grid.drums_in or (rulebook.first_loud(energy, grid.beats, grid.beat, grid.downbeat_pos)
                              if energy is not None else grid.beats[0])
    i = grid.index_at_or_after(start)
    back = int(round(first_kill_reel / grid.beat))
    return grid.beats[max(0, i - back)]


def _first_kill(hits: list[float], big: list[float], *, earliest: float,
                drums_in: float = 0.0) -> float:
    """Where the reel's first kill belongs in the song.

    On the first BIG hit the song has to offer -- the first strong bass hit
    after a quiet stretch, which is where the player's own marks start. Before
    this, a story reel began at the song's first beat and put its opening kill
    7 s in, over an intro of Skechers that has no drums until 18 s and where
    the player marked no kills at all until 19.5.
    """
    want = max(earliest, drums_in)
    for t in big:
        if t >= want - 1e-6:
            return t
    for t in hits:
        if t >= want - 1e-6:
            return t
    return want


def _hit_slots(hits: list[float], strengths: list[float], *, first: float, end: float,
               gap: float, count: int) -> list[float]:
    """The song times this reel's kills land on: `count` of them from `first`."""
    keep = [i for i, t in enumerate(hits) if first - 1e-6 <= t <= end + 1e-6]
    if not keep:
        return [first]
    within = [hits[i] for i in keep]
    strong = [strengths[i] for i in keep] if len(strengths) == len(hits) else None
    kills, _accents = hits_mod.choose_kills(within, strong, target_gap=gap)
    # The opener is not up for grabs: choose_kills takes the loudest hit in
    # each window, and in the first window that is rarely the hit the reel was
    # aimed at -- on Skechers it moved the first kill 2.4 s past the drop.
    if kills and abs(kills[0] - first) > 1e-6:
        kills = [first] + [k for k in kills if k >= first + hits_mod.WINDOW[0] * gap]
    return kills[:count] if count else kills


# What the shaping dials mean, and how far each may be pushed. A dial is a
# MULTIPLIER on what the style's references measured, so 1.0 is "as the style
# has it" and every reel ever planned without them is unchanged.
#
# The ranges are not taste. Past about two thirds either way a reel stops being
# the style it says it is: the references a style is modelled on span roughly
# that much between their fastest and slowest, so a dial that went further
# would be offering a different style under the wrong name.
SHAPING = {
    "length": (0.55, 1.8, 1.0),    # how long the reel runs
    "pace": (0.55, 1.8, 1.0),      # how fast it cuts -- higher is faster
    "effects": (0.0, 2.0, 1.0),    # how often a kill gets an effect at all
    "flash": (0.0, 2.5, 1.0),      # how often a cut carries a white flash
}


def _arrangement(raw: dict | None) -> dict:
    """The ordering and the pins, clamped, as kwargs for rulebook.order.

    An unknown arrangement falls back to `build` rather than raising: this
    comes off the page, and a reel is worth more than a strict parse.
    """
    raw = raw or {}
    how = str(raw.get("arrange") or "build")
    if how not in rulebook.ARRANGEMENTS:
        how = "build"
    pins = {}
    got = raw.get("pins")
    if isinstance(got, dict):
        for slot in ("open", "climax", "close"):
            path = str(got.get(slot) or "").strip()
            if path:
                pins[slot] = path
    return {"arrange": how, "pins": pins,
            "seed": int(_num(raw.get("shuffle_seed"), 0, 2 ** 31 - 1, 0))}


def _shaping(raw: dict | None) -> dict:
    """The dials, clamped. Anything missing or unreadable is left centred."""
    out = {}
    for key, (lo, hi, mid) in SHAPING.items():
        out[key] = _num((raw or {}).get(key), lo, hi, mid)
    return out


def plan(clips: list[dict], style_key: str = DEFAULT_STYLE, *, shape=None,
         song: str = "", fmt: str = "landscape", name: str = "",
         max_seconds: float = 0.0, seed: int | None = None,
         measure=None, confirm=None, theirs=None,
         part: tuple[float, float] | None = None,
         template: dict | None = None,
         shape_it: dict | None = None) -> tuple[dict, list[str]]:
    """Build a project from chosen clips. -> (project, notes)

    `measure(path, t0, t1)` -> how much the picture moves between two clip
    times (see action()); None skips the check, which is what tests do.
    `confirm(path, game)` -> the game's own kill-emblem times in a clip (see
    kill_marks()), or None for a game without one; None skips it.
    `theirs(path, game, t)` -> whether an emblem at clip time t rose while the
    player was spectating a team-mate (see spectated()); None adds them all.

    `clips` are library entries in the order the reel should use them. `seed`
    decides the effect mix; the default is derived from the clips, so the same
    selection plans the same reel.

    `part` is (start, end) in song seconds: the stretch of the song the player
    chose to cut to. See the PART OF THE SONG comment below.
    """
    style = STYLE.get(style_key) or STYLE[DEFAULT_STYLE]
    if template:
        style = templated(style, template)
    # SHAPING THE REEL WITHOUT LEAVING THE STYLE. Each of these multiplies what
    # the style's references measured rather than replacing it, so "faster"
    # means faster than THIS style rather than a jump to another one, and a
    # reel at every dial centred is exactly the reel the style would have made.
    tw = _shaping(shape_it)
    # HOW THE REEL IS ORDERED, and anything the player pinned into a slot. Both
    # ride on the same dict the dials do, so one control panel carries all of
    # it and a rebuild keeps what was asked for.
    arrangement = _arrangement(shape_it)
    if tw["effects"] != 1.0:
        # Scaled on the style itself rather than at the draw: _vary() is called
        # from the page too, and a dial the page could not see would be lost
        # the first time somebody pressed "Mix them up".
        style = dataclasses.replace(style, energy=max(0.0, min(1.0, style.energy * tw["effects"])))
    grid = Grid.of(shape) if shape is not None else Grid.none()
    notes: list[str] = []
    meas = studio_refs.summary(style.refs)
    beat = grid.beat

    # PART OF THE SONG, CHOSEN BEFORE THE PLAN. Chosen afterwards, a part can
    # only take shots away: a reel of MONTERO at 72 BPM came out 24 s, because
    # the length rule snaps to whole 8-bar phrases -- 26.7 s each at that tempo
    # -- and the chosen clips were short of two phrases, so it cut to one and
    # left the weakest clips out. With the part known first it is the length
    # to fill: every clip goes in unless the part cannot hold them, and when
    # the clips are short of it each kill gets a longer run-up, as far as its
    # clip has footage, before the reel is allowed to end early.
    part_start = part_len = 0.0
    if part and song and grid.beats and grid.seconds:
        part_start = max(0.0, min(float(part[0]), grid.seconds - 1.0))
        end = float(part[1] or 0.0)
        end = min(end, grid.seconds) if end > part_start else grid.seconds
        part_len = end - part_start
        if part_len < rulebook.MIN_RUN_SECONDS + beat:
            part_start = part_len = 0.0

    # WHY EACH CHOSEN CLIP IS NOT IN THE REEL, first reason wins. The page used
    # to say "N of M moments" once, in a note nothing kept, so a clip that
    # silently fell out could not be found again. Recorded on the project.
    why_out: dict[str, str] = {}

    def left_out(paths, reason: str) -> None:
        for p in paths:
            why_out.setdefault(p, reason)

    # PACE FROM THE REFERENCES: the median cuts-per-minute of the edits this
    # style is modelled on, as a whole number of beats at this song's tempo --
    # times the pace dial, which has to be applied HERE rather than only to the
    # shot length. Measured: on a song with bass hits the kill placement sets
    # the durations and a dial that missed this line did nothing at all.
    cpm = (meas.get("cuts_per_min") or 30.0) * tw["pace"]
    # THE SHOT IS THE REFERENCES' MEDIAN, NOT A MINUTE DIVIDED BY THEIR CUTS.
    # Those are different numbers and the edits are skewed: Montage's cuts a
    # minute say 2.12 s a shot, its median shot is 1.18 s, because a montage
    # holds a few long shots and cuts fast between the rest. Aiming at the
    # average made every shot as long as the long ones -- montero1 came out at
    # 9 cuts a minute against a 21-33 band -- so the target is the median the
    # reel is scored against.
    want = (meas.get("median_shot") or 0.0) / tw["pace"] or (60.0 / cpm)
    # THE GRID IS AS FINE AS THE TARGET NEEDS. In whole beats the shortest shot
    # the rules allow is two of them, so a fast style on a half-time song could
    # not cut faster than 1.5 s and Hype, Velocity and Montage all came out at
    # the same three-beat shot -- measured over 19 reels. `div` is how many
    # steps make a beat, and everything from here down is counted in steps.
    div = _grid_div(want, beat)
    step = beat / div
    shot_beats = max(1, min(8 * div, int(round(want / step))))
    # The opening hold is left on the beat: it already lands inside the
    # references' band on 20 of 24 reels, so only its unit changes.
    open_beats = _pow2_beats(max(meas.get("first_shot") or 4.0, 2.0), beat, lo=2, hi=16) * div
    flash_share = min(0.9, (meas.get("flashes_per_min") or 0.0) / max(cpm, 1.0) * tw["flash"])

    # ONE ENTRY PER CLIP. Rebuilding a reel in another style sent the timeline's
    # shots back as the clip list, so a clip used in nine shots arrived nine
    # times, became nine sequences, and select() -- which ranks sequences --
    # took the same footage again and again while the clips that were only
    # asked for once were left out "to fit the reel's length". DRIPSKETCHERS1
    # came out as 23 shots of 4 clips from a selection of 20.
    offered = []
    seen: set[str] = set()
    for c in clips:
        if not c or not c.get("path"):
            continue
        k = str(c["path"]).lower()
        if k in seen:
            continue
        seen.add(k)
        offered.append(c)
    chosen = offered[:MAX_SHOTS]
    if len(offered) > MAX_SHOTS:
        notes.append(f"Only the first {MAX_SHOTS} clips were used.")
        left_out((c["path"] for c in offered[MAX_SHOTS:]), f"Only the first {MAX_SHOTS} clips can go in one reel.")

    # MOMENTS, NOT CLIPS -- see rulebook.
    run_b = max(1, int(math.ceil(max(rulebook.MIN_RUN_BEATS * beat, rulebook.MIN_RUN_SECONDS) / step - 1e-6)))

    if confirm is not None:
        before = [c["path"] for c in chosen]
        chosen, moved, dropped, added = _confirm_kills(chosen, confirm, theirs)
        kept_paths = {c["path"] for c in chosen}
        left_out((p for p in before if p not in kept_paths),
                 "No kill showed on screen: the game's kill icon never appeared in this clip.")
        if moved or dropped or added:
            notes.append(f"Kill times checked against the game's own kill emblem: {moved} moved onto it, "
                         f"{dropped} with no emblem left out, {added} the kill feed missed added.")
    all_moments = rulebook.moments(chosen, beat)
    with_moments = {m.clip["path"] for m in all_moments}
    left_out((c["path"] for c in chosen if c["path"] not in with_moments),
             "Too little footage before its kill to show the fight.")
    stats: dict[int, dict | None] = {}
    looks: dict[int, list[float]] = {}
    sat_trim = 1.0
    if measure is not None:
        stats = _measure_action(all_moments, measure)
        for m in all_moments:
            st = stats.get(id(m))
            if isinstance(st, dict) and st.get("hist") and m.group not in looks:
                looks[m.group] = st["hist"]
        sat_trim = rulebook.saturation_trim(
            [st.get("sat") for st in stats.values() if isinstance(st, dict)], style.grade)
        all_moments, still = rulebook.drop_still(all_moments, stats)
        if still:
            notes.append(f"{still} moment(s) left out: nothing moves on screen around the kill "
                         f"(a death camera, or standing still).")
        moving = {m.clip["path"] for m in all_moments}
        left_out((p for p in with_moments if p not in moving),
                 "Nothing moves on screen around its kill (a death camera, or standing still).")
    est = {id(m): (rulebook.FOLLOW_UP_BEATS * div if m.seq > 0 else shot_beats) for m in all_moments}
    available = sum(est.values()) * step
    if part_len:
        # Whole beats of the chosen part. select() below keeps every moment
        # when there is less material than this, and leaves out the weakest
        # only when the part cannot hold them all.
        target = math.floor(part_len / beat + 1e-6) * beat
    else:
        target = rulebook.phrase_seconds(beat, fmt, available, max_seconds)
        if tw["length"] != 1.0:
            # Scale the target that was worked out, rather than feeding a
            # `want` into phrase_seconds: that takes a different branch and
            # came out SHORTER for "longer" and "shorter" alike -- measured,
            # both gave 17.1 s. Whole phrases either way, because a reel that
            # ends mid-phrase is what the length rule exists to prevent.
            phrase = rulebook.PHRASE_BARS * 4 * beat
            n = max(1, int(round(target * tw["length"] / phrase)))
            target = min(n * phrase, rulebook.MAX_SECONDS.get(fmt, 86.0))
    # A reel with less material than one phrase uses all of it: the phrase
    # rule trims a surplus, it never throws away a short selection's clips.
    if not part_len and target < rulebook.PHRASE_BARS * 4 * beat - 1e-6 and not max_seconds:
        target = 0.0
        pool = list(all_moments)
    want_beats = int(round(target / step))
    if target:
        pool = rulebook.select(all_moments, target, lambda m: est[id(m)] * step)
    spare = [m for m in all_moments if m not in pool]

    # PACE FROM THE SONG -- see rulebook.pace. Reel zero is fixed first (the
    # opener's kill on the drums), so every later shot knows where in the song
    # it plays and how loud it is there.
    energy = rulebook.energy_profile(grid.peaks, grid.seconds) if song else (lambda a, b: 1.0)
    build = (bool(song) and not style.drop and style.outro != "e12"
             and rulebook.wants_build(energy, grid.drums_in, beat))
    if build and part_len:
        # Only a part that opens on the quiet stretch has anything to build
        # over; one that starts on the drums would open half speed over them.
        build = part_start + rulebook.INTRO_BARS * 4 * beat <= (grid.drums_in or 0.0) + beat
    if build:
        open_beats = (rulebook.INTRO_BARS * 4 + 1) * div
    closer_post = rulebook.ENDING_BEATS * div if style.outro in ("e01", "e03", "e02") else 0
    open_post = max(1, min(rulebook.MAX_TAIL_BEATS * div, open_beats // 4))
    if part_len:
        offset = part_start
    else:
        offset = _choose_offset(grid, max(run_b, open_beats - open_post) * step, style, None, energy,
                                build) if song else 0.0
    idx0 = grid.index_at_or_after(offset) if (song and grid.beats) else 0

    first_kill_b = max(run_b, open_beats - open_post)

    def opener_ok(m):
        if not build:
            return True
        # Half speed over the build: two bars of output need a bar of footage.
        return m.first >= rulebook.INTRO_BARS * 4 * beat * 0.5 + 0.2

    def plan_walk(ms, fixed=None, start=offset, first_index=idx0):
        ranked_ = sorted(range(len(ms)), key=lambda i: (-ms[i].strength, i))
        heroes_ = {i for i in ranked_[:max(1, len(ms) // 6)] if ms[i].caption}
        lens_ = rulebook.walk(ms, beat=step, energy=energy, song_start=start, base=shot_beats,
                              open_beats=open_beats, run_beats=run_b, pre_share=style.pre_share,
                              first_index=first_index * div, downbeat_pos=grid.downbeat_pos * div,
                              fixed=fixed, heroes=heroes_, closer_post=closer_post,
                              phrase_from=first_kill_b, div=div)
        return lens_, heroes_

    picked = rulebook.order(pool, looks, opener_ok, **arrangement)
    lens, hero_set = plan_walk(picked)
    # Settle the count: add the next-best sequence while the walk falls short
    # of the phrase, drop the weakest middle one while it runs a shot over.
    # A drop needs its build: the fourth shot is the one on the drop.
    min_groups = 5 if style.drop else 3
    for _ in range(24 if target else 0):
        total = sum(sum(x) for x in lens)
        if total < want_beats - 1 and spare:
            nxt = max(spare, key=lambda m: m.strength)
            grp = [m for m in spare if m.group == nxt.group]
            spare = [m for m in spare if m.group != nxt.group]
            picked = rulebook.order(picked + grp, looks, opener_ok, **arrangement)
        elif total > want_beats + shot_beats and len({m.group for m in picked}) > min_groups:
            # Whole sequences only, and never the opener's, the closer's or
            # the climax's: taking "the middle shots" once split the opener's
            # triple kill and left its last shot opening the reel alone,
            # captioned TRIPLE KILL.
            groups = {}
            for m in picked:
                groups.setdefault(m.group, []).append(m)
            best_group = max(picked, key=lambda m: m.strength).group
            keep = {picked[0].group, picked[-1].group, best_group}
            removable = [g for k, g in groups.items() if k not in keep]
            if not removable:
                break
            weakest = min(removable, key=lambda g: max(x.strength for x in g))
            # Ordered again, not filtered: the places were alternated around
            # what is now gone.
            picked = rulebook.order([m for m in picked if m not in weakest], looks, opener_ok,
                                    **arrangement)
            spare += weakest
        else:
            break
        lens, hero_set = plan_walk(picked)
    if style.drop and song and grid.drop and len(picked) > 3 and not part_len:
        # The build is walked once; reel zero then moves so the fourth shot's
        # kill lands exactly on the drop, and the rest is walked from there.
        # Not when the player chose the part: where it starts is theirs.
        drop_kill = sum(sum(x) for x in lens[:3]) + lens[3][0]
        off = grid.drop - drop_kill * beat
        if off >= 0:
            offset = min(grid.beats, key=lambda b: abs(b - off))
            idx0 = grid.index_at_or_after(offset)
            lens, hero_set = plan_walk(picked, fixed={i: lens[i] for i in range(4)},
                                       start=offset, first_index=idx0)
    if target and len(picked) < len(all_moments):
        notes.append(f"{len(picked)} of {len(all_moments)} moments fill {target:.0f} s "
                     f"({int(round(target / (4 * beat)))} bars); the weakest were left out.")
    in_plan = {m.clip["path"] for m in picked}
    left_out((m.clip["path"] for m in all_moments if m.clip["path"] not in in_plan),
             "The song part was full: the clips that went in were stronger." if part_len else
             "Left out to fit the reel's length: the clips that went in were stronger.")

    shots = []
    for i, m in enumerate(picked):
        c = m.clip
        dur_clip = float(c.get("duration") or 0.0)
        is_hero = i in hero_set
        pre_b, span_b, post_b = lens[i]
        speed = style.hero_speed if is_hero else style.speed
        shot = {"clip": c["path"], "clip_id": c.get("id") or clip_id(c["path"]),
                "name": c.get("name", ""), "clip_seconds": round(dur_clip, 3),
                "clip_mtime": int(c.get("mtime") or 0),
                "kills": list(m.kills), "kill": round(m.first, 3),
                "pre": round(pre_b * step, 5), "duration": round((pre_b + span_b + post_b) * step, 5),
                "speed": speed, "fx": list(style.kill), "hero": is_hero,
                "hero_fx": list(style.hero) if is_hero else [],
                "camera": style.camera, "transition": "t01", "tlen": 0.0,
                "caption": m.caption}
        _fit(shot, step, notes)
        shots.append(shot)

    if seed is None:
        seed = zlib.crc32(",".join(s["clip_id"] for s in shots).encode("utf-8")) & 0x7FFFFFFF
    pools = {k: list(style_pool) for k, style_pool in (
        ("kill", style.kill_pool), ("transition", style.transition_pool),
        ("hero", style.hero_pool), ("camera", style.camera_pool), ("speed", style.speed_pool))}
    _vary(shots, pools, style, seed, "all")
    rulebook.budget(shots, pools)
    clip_look = {m.clip["path"]: looks.get(m.group) for m in picked}
    def speed_ok(shot, speed):
        ps = pieces(speed, shot["duration"], shot["pre"])
        before = source_used(ps, shot["pre"])
        after = source_used(ps, shot["duration"]) - before
        return (before <= float(shot["kill"]) + 1e-6
                and float(shot["kill"]) + after <= float(shot.get("clip_seconds") or 0.0) + 1e-6)
    rulebook.climax(shots, [m.strength for m in picked], pools, speed_ok=speed_ok)
    if build and shots:
        shots[0]["speed"] = "s05"
        shots[0]["fx"] = shots[0]["fx"][:1]
    if closer_post and len(shots) > 1:
        # Slowed as it leaves, so the bar after the last kill has footage to fill.
        last = shots[-1]
        last["speed"] = "s06"
        last["duration"] = round(last["pre"] + (lens[-1][1] + closer_post) * step, 5)
    for s in shots:
        _fit(s, step, notes)
    if target:
        _fit_total(shots, step, target, run_b * step, rulebook.shot_cap(shot_beats, step) * step)
    if part_len and shots:
        want_b = int(round(target / step))
        before_b = int(round(sum(s["duration"] for s in shots) / step))
        _lengthen_run_ups(shots, step, want_b)
        have_b = int(round(sum(s["duration"] for s in shots) / step))
        if have_b > before_b:
            notes.append(f"The clips were short of the part, so their kills got longer run-ups "
                         f"({(have_b - before_b) * step:.0f} s more in all, as far as each clip has "
                         f"footage and never over {rulebook.MAX_LEAD_UP_SECONDS:.0f} s).")
        if have_b < want_b:
            notes.append(f"Your clips fill {have_b * step:.0f} s of the {target:.0f} s part, even with "
                         f"every kill given as much run-up as it can have, so the reel ends early. "
                         f"Add clips or choose a shorter part to fill it.")

    proj = {
        "version": VERSION, "name": name or f"{style.label} reel",
        "style": style.key, "format": fmt if fmt in SIZES else "landscape",
        "song": str(song or ""), "song_offset": 0.0,
        "intro": "i12" if build else style.intro,
        "outro": "e03" if style.outro == "e01" else style.outro, "grade": style.grade,
        "vignette": style.vignette, "overlays": list(style.overlays),
        "handle": "", "music_db": 0.0, "game_db": 6.0 if song else 0.0, "duck": True,
        "saturation": sat_trim,
        "beat": round(beat, 6), "step": round(step, 6),
        "shaping": tw, "arrange": arrangement["arrange"], "pins": arrangement["pins"],
        "seed": int(seed), "pools": pools, "shots": shots,
    }
    # Where in the song reel zero sits: chosen before the walk, so each shot's
    # length could follow the part of the song it plays over -- and settled
    # again now, because fitting a shot to its footage can take a beat off the
    # opener's run-up, and the opener's kill is what lands on the drums.
    if song and shots and not part_len:
        if style.drop and grid.drop and len(shots) > 3:
            off = grid.drop - (_starts(shots)[3] + shots[3]["pre"])
            if off >= 0:
                # The NEAREST beat: at-or-after once moved reel zero a whole beat
                # late when the exact answer sat a millisecond under a beat,
                # and Dracula's drop kill landed half a second after the drop.
                offset = min(grid.beats, key=lambda b: abs(b - off))
        else:
            offset = _choose_offset(grid, shots[0]["pre"], style, None, energy, build)
    proj["song_offset"] = round(offset, 5) if song else 0.0

    # KILLS ON THE SONG'S BASS HITS, AT THIS STYLE'S PACE.
    #
    # The beat grid says every beat is equal and one tempo covers the whole
    # song; neither is true of the songs the player marked (MONTERO read as
    # 71.9 BPM, its lines between the kicks). clips/hits.py finds the kicks
    # themselves, and choose_kills thins them to the pace this style's own
    # reference edits cut at -- 2.8 s for story, 1.1 s for hype -- so the same
    # song gives a story reel a third of the cuts of a hype one.
    #
    # The shots, their order, their captions and their effects are all decided
    # above exactly as before. This only moves the cuts, through apply_marks(),
    # the same path the player's hand-made marks take.
    if song and shots and grid.hits and not part_len:
        floor = 0.0
        first = _first_kill(grid.hits, grid.big, earliest=floor + run_b * step,
                            drums_in=grid.drums_in or 0.0)
        if style.drop and grid.drop and len(shots) > 3:
            # A drop reel's fourth kill lands ON the drop: the build is the
            # three shots before it. With the kills on hits the opener moves
            # to whichever hit puts the fourth slot on the drop's own hit.
            gap = 60.0 / max(cpm, 1.0)
            aim = min(grid.hits, key=lambda t: abs(t - grid.drop))
            best = None
            for c in grid.hits:
                if not aim - 14.0 <= c <= aim:
                    continue
                s4 = _hit_slots(grid.hits, grid.hit_strength, first=c, end=aim + 1.0,
                                gap=gap, count=4)
                if len(s4) < 4:
                    continue
                d = abs(s4[3] - aim)
                if best is None or d < best[0]:
                    best = (d, c)
            if best and best[0] < gap:
                first = best[1]
        offset = max(floor, first - shots[0]["pre"])
        first = max(first, offset + shots[0]["pre"])
    elif song and shots and grid.hits:
        floor = part_start
        first = _first_kill(grid.hits, [], earliest=floor + shots[0]["pre"])
    if song and shots and grid.hits:
        end = (part_start + part_len) if part_len else grid.seconds
        slots = _hit_slots(grid.hits, grid.hit_strength, first=first, end=end,
                           gap=60.0 / max(cpm, 1.0), count=len(shots))
        proj["song_offset"] = round(offset, 5)
        # The hits the kills were aimed at, kept in song seconds. Without them
        # the timeline could only redraw what a detector would pick *now*, at
        # its own default pace -- not the marks this reel was actually cut to,
        # which is the only set worth checking a kill against.
        proj["song_marks"] = [round(t, 4) for t in slots]
        notes += apply_marks(proj, [t - offset for t in slots])
        big_on = sum(1 for t in slots if any(abs(t - b) < 0.01 for b in grid.big))
        what = grid.pattern or "bass hits"
        notes.append(f"{len(slots)} kills land on the song's own {what}, a cut every "
                     f"{60.0 / max(cpm, 1.0):.1f} s at {style.label}'s pace"
                     + (f", {big_on} of them on a big hit" if big_on else "") + ".")
        if len(slots) < len(shots):
            notes.append(f"The song ran out of hits after {len(slots)} of {len(shots)} shots; "
                         f"the rest follow at their own length.")
    elif song and shots:
        notes.append("This song has no bass hits to cut to, so the reel follows the beat grid.")

    # THE CUTS ARE SETTLED, so now each one can be given its transition: which
    # bar a cut falls on is only known once the shots have been fitted to their
    # footage and moved onto the song's hits. Chosen from the planned lengths
    # instead, a velocity reel's flashes sat at beats 13, 19, 25 and 31 -- six
    # beats apart, on no bar line at all.
    shots = proj["shots"]
    starts_b = [int(round(t / step)) for t in _starts(shots)]
    rulebook.transitions(shots, starts_b, first_kill_beat=int(round(shots[0]["pre"] / step)) if shots else 0,
                         looks=clip_look, pools=pools, flash_share=flash_share, beat=step, div=div)
    if style.drop and song and not grid.drop:
        notes.append("This song has no clear drop, so the reel is paced as a build without one.")

    # The reel cannot outlast the song -- or the part of it that was chosen.
    if song and part_len:
        proj["part_end"] = round(part_start + part_len, 5)
        before = [s["clip"] for s in proj["shots"]]
        notes += fit_to_part(proj, min(part_len, grid.seconds - part_start - 0.5))
        kept_clips = {s["clip"] for s in proj["shots"]}
        left_out((c for c in before if c not in kept_clips), "The song part ends before this clip.")
    elif song and grid.seconds:
        room = grid.seconds - proj["song_offset"] - 0.5
        if max_seconds:
            room = min(room, max_seconds)
        kept, t = [], 0.0
        for s in shots:
            if t + s["duration"] > room and kept:
                break
            kept.append(s)
            t += s["duration"]
        if len(kept) < len(shots):
            notes.append(f"The song ends after {len(kept)} of {len(shots)} clips; the rest were left out.")
            left_out((s["clip"] for s in shots[len(kept):]), "The song ends before this clip.")
            proj["shots"] = kept
    elif max_seconds:
        kept, t = [], 0.0
        for s in shots:
            if t + s["duration"] > max_seconds and kept:
                break
            kept.append(s)
            t += s["duration"]
        proj["shots"] = kept
    in_reel = {s["clip"] for s in proj["shots"]}
    proj["selection"] = [{"clip": c["path"], "name": str(c.get("name") or Path(c["path"]).stem),
                          "why": "" if c["path"] in in_reel else
                          why_out.get(c["path"], "Left out to fit the reel's length.")}
                         for c in offered]
    return proj, notes


_MARK_CACHE: dict[tuple, list[float] | None] = {}


def kill_marks(path: str, game: str) -> list[float] | None:
    """The game's kill emblems in a clip, in clip seconds; None when the game draws none. Cached."""
    from . import killmark
    from .tools import binary

    if killmark.spec_for(game) is None:
        return None
    try:
        key = (str(path), Path(path).stat().st_mtime)
    except OSError:
        return None
    with _ACTION_LOCK:
        if key in _MARK_CACHE:
            return _MARK_CACHE[key]
    ff = binary("ffmpeg")
    got = killmark.marks(Path(path), game, ff) if ff else None
    with _ACTION_LOCK:
        if len(_MARK_CACHE) > 2000:
            _MARK_CACHE.clear()
        _MARK_CACHE[key] = got
    return got


def spectated(path: str, game: str, t: float) -> bool:
    """Whether the emblem at clip time t is a team-mate's, seen while spectating. See killmark.spectating."""
    from . import killmark
    from .tools import binary

    ff = binary("ffmpeg")
    return bool(ff and killmark.spectating(Path(path), t, game, ff))


def _confirm_kills(clips: list[dict], confirm, theirs=None) -> tuple[list[dict], int, int, int]:
    """Clips with their kills moved onto the game's emblems. -> (clips, moved, dropped, added)

    A clip whose every kill turned out to have no emblem is left out: there is
    no kill in it to show. A clip whose kills came from Riot's match record is
    left as it is: two kills half a second apart share one emblem, and the
    check would drop the second.
    """
    from concurrent.futures import ThreadPoolExecutor

    from . import killmark

    def one(c):
        if c.get("recorded"):
            return None
        return confirm(c["path"], c.get("game") or "")
    with ThreadPoolExecutor(max_workers=4) as pool:
        found = list(pool.map(one, clips))
    # Whether the HUD shows the emblem at all is a property of a RUN, not of a
    # clip: a run in which no clip shows one keeps its kills, while a clip with
    # no emblem in a run that shows them has no kill (checked by eye).
    shows = {c.get("folder") or Path(c["path"]).parent.parent.name
             for c, m in zip(clips, found) if m}
    out, moved, dropped, added = [], 0, 0, 0
    for c, marks in zip(clips, found):
        run = c.get("folder") or Path(c["path"]).parent.parent.name
        if marks is None or run not in shows:
            out.append(c)
            continue
        mate = (lambda t, c=c: theirs(c["path"], c.get("game") or "", t)) if theirs else None
        kills, d, a = killmark.confirm([float(k) for k in c.get("kills") or []], marks, mate)
        moved += sum(1 for k in kills if all(abs(k - old) > 0.05 for old in c.get("kills") or []))
        dropped += d
        added += a
        if kills:
            out.append(dict(c, kills=[round(k, 3) for k in kills], kill_count=len(kills)))
    return out, moved, dropped, added


_ACTION_CACHE: dict[tuple, float | None] = {}
_ACTION_LOCK = threading.Lock()


def action(path: str, t0: float, t1: float) -> dict | None:
    """What the footage between two clip times looks like, at 64x36 and 15 fps.

    -> {"action": 90th percentile of frame-to-frame change,
        "sat": mean colourfulness ((max-min)/max, as the references were measured),
        "hist": a 4x4x4 colour histogram, for telling one location from another}
    or None when it cannot be read.

    The 90th percentile, not the mean: a flick onto a target is a fifth of a
    second, and a mean over the run-up averages it away.
    """
    from .tools import binary

    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime, round(t0, 2), round(t1, 2))
    with _ACTION_LOCK:
        if key in _ACTION_CACHE:
            return _ACTION_CACHE[key]
    ff = binary("ffmpeg")
    val = None
    if ff:
        from .killfeed import _NO_WINDOW
        W, H = 64, 36
        try:
            raw = subprocess.run([ff, "-v", "error", "-ss", f"{max(0.0, t0):.3f}", "-i", str(path),
                                  "-t", f"{max(0.2, t1 - t0):.3f}", "-vf", f"fps=15,scale={W}:{H}",
                                  "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], capture_output=True,
                                 timeout=60, creationflags=_NO_WINDOW).stdout
            n = len(raw) // (W * H * 3)
            if n > 2:
                import numpy as np
                rgb = np.frombuffer(raw, np.uint8)[:n * W * H * 3].reshape(n, H, W, 3).astype(np.float32)
                fr = rgb.mean(3)
                d = np.abs(np.diff(fr, axis=0)).mean((1, 2))
                mx, mn = rgb.max(3), rgb.min(3)
                hist = np.histogramdd(rgb[::3].reshape(-1, 3), bins=(4, 4, 4), range=((0, 256),) * 3)[0].ravel()
                val = {"action": float(np.percentile(d, 90)),
                       "sat": float(np.mean((mx - mn) / (mx + 1e-6))),
                       "hist": [round(float(x), 4) for x in hist / max(1.0, hist.sum())]}
        except (OSError, subprocess.SubprocessError):
            val = None
    with _ACTION_LOCK:
        if len(_ACTION_CACHE) > 4000:
            _ACTION_CACHE.clear()
        _ACTION_CACHE[key] = val
    return val


def _measure_action(moments_: list, measure) -> dict[int, dict | None]:
    """What the footage around every moment's kills looks like, four at a time."""
    from concurrent.futures import ThreadPoolExecutor

    def one(m):
        return id(m), measure(m.clip["path"], max(0.0, m.first - 1.2), m.last + 0.3)
    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(pool.map(one, moments_))


def _fit_total(shots: list[dict], beat: float, target: float, run: float, cap: float = 4.0) -> None:
    """Make the reel end on its phrase: exactly `target` seconds, in whole beats.

    Selection fills to about the phrase; this settles the last few beats by
    shortening run-ups in the middle of the reel (never below `run`) or, when
    there is room in the footage, lengthening the opener's and the heroes'.
    """
    if not shots or target <= 0:
        return
    want = int(round(target / beat))

    def have() -> int:
        return int(round(sum(s["duration"] for s in shots) / beat))

    for _ in range(4 * len(shots) + 64):
        if have() <= want:
            break
        # 1e-4, not 1e-6: pre is stored rounded to 5 decimals, so two beats
        # minus one beat can read as a hair under one beat.
        # Heroes keep two beats of run-up: the climax is the last thing to
        # give up time so the phrase can end on its bar.
        def floor(s):
            if not s.get("hero"):
                return run
            return max(run, 2 * beat, math.ceil(rulebook.HERO_RUN_SECONDS / beat - 1e-6) * beat)
        middle = [s for s in shots[1:-1] if s["pre"] - beat >= floor(s) - 1e-4]
        pool = middle or [s for s in shots if s["pre"] - beat >= floor(s) - 1e-4]
        if not pool:
            break
        s = max(pool, key=lambda s: (s["pre"], -s.get("hero", False)))
        s["pre"] = round(s["pre"] - beat, 5)
        s["duration"] = round(s["duration"] - beat, 5)
    for _ in range(4 * len(shots) + 64):
        if have() >= want:
            break
        done = False
        # Spare beats go to the heroes' run-ups first, then to the shortest
        # shots: v9 gave them all to the first shot with footage, and two
        # double kills held for six seconds.
        grow = [s for s in shots if s.get("hero")] + sorted(
            (s for s in shots if not s.get("hero")), key=lambda s: s["duration"])
        grow = [s for s in grow if s["duration"] + beat <= cap + 1e-6]
        for s in grow:
            ps = pieces(s["speed"], s["duration"] + beat, s["pre"] + beat)
            if source_used(ps, s["pre"] + beat) <= float(s["kill"]) + 1e-6:
                s["pre"] = round(s["pre"] + beat, 5)
                s["duration"] = round(s["duration"] + beat, 5)
                done = True
                break
        if not done:
            break


def _lengthen_run_ups(shots: list[dict], beat: float, want_beats: int) -> None:
    """Give kills longer run-ups, a beat at a time, until the reel is `want_beats` long.

    The player's rule for a chosen part the clips cannot fill: more lead-up to
    each kill, as far as its clip has footage, before the reel ends early.

    THE SHORTEST RUN-UP GROWS FIRST, so the extra time is spread over every
    shot instead of piling onto one: the rulebook caps a shot at 4 s because a
    double kill once held for 5.8 s and read as padding.

    NEVER INTO FOOTAGE ANOTHER SHOT SHOWS. Round clips give several shots from
    one file -- kills 3.5 s, 12.3 s and 25.2 s into a 33 s clutch -- and a run-up
    grown back past the previous shot's end would play that kill twice.

    NEVER PAST rulebook.MAX_LEAD_UP_SECONDS, whatever the clip holds: the clip
    with the most footage otherwise soaked up every beat the others could not
    take. Every beat keeps cuts and kills on the grid.
    """
    if not shots or want_beats <= 0:
        return

    def have() -> int:
        return int(round(sum(s["duration"] for s in shots) / beat))

    for _ in range(64 * len(shots) + 256):
        if have() >= want_beats:
            return
        best = None
        for i, s in enumerate(shots):
            pre, dur = s["pre"] + beat, s["duration"] + beat
            if pre > rulebook.MAX_LEAD_UP_SECONDS + 1e-6:
                continue
            ps = pieces(s["speed"], dur, pre)
            start = float(s["kill"]) - source_used(ps, pre)
            if start < -1e-6:
                continue                              # the clip has no more footage before its kill
            was = _span(s)[0]                          # the footage this beat adds is [start, was)
            clash = False
            for j, o in enumerate(shots):
                if j != i and o["clip"] == s["clip"]:
                    a, b = _span(o)
                    if start < b - 1e-6 and was > a + 1e-6:
                        clash = True
                        break
            if clash:
                continue
            if best is None or s["pre"] < best["pre"] - 1e-9:
                best = s
        if best is None:
            return
        best["pre"] = round(best["pre"] + beat, 5)
        best["duration"] = round(best["duration"] + beat, 5)


def _flash_share(style: "Style") -> float:
    meas = studio_refs.summary(style.refs)
    cpm = meas.get("cuts_per_min") or 30.0
    return min(0.9, (meas.get("flashes_per_min") or 0.0) / max(cpm, 1.0))


def _vary(shots: list[dict], pools: dict, style: "Style", seed: int, what: str = "all") -> None:
    """Give every shot its own mix of effects, from the style's pools.

    NEVER THE SAME TWICE RUNNING: each draw avoids what the previous shot got
    (and, for kill effects, the one before that), so a reel cannot settle into
    punch-flicker-punch-flicker. Flashes still come at the rate the reference
    edits flash at, spread evenly; every other cut is drawn from the pool.
    Hero moments get a stronger effect and are never left bare.
    """
    rng = random.Random(int(seed))

    def pool(kind: str) -> list[str]:
        valid = set(ids_of(POOL_KINDS[kind]))
        got = [p for p in (pools.get(kind) or []) if p in valid]
        return got

    def draw(options: list[str], avoid: set[str]) -> str:
        fresh = [o for o in options if o not in avoid]
        return rng.choice(fresh or options)

    kills, trans, heroes = pool("kill"), pool("transition"), pool("hero")
    cams, speeds = pool("camera"), pool("speed")
    flash_share = _flash_share(style)
    recent: list[str] = []
    last_cam = last_speed = last_hero = last_trans = ""
    acc = 0.0
    for i, s in enumerate(shots):
        if what in ("all", "kill"):
            if kills:
                first = draw(kills, set(recent[-2:]))
                fx = [first]
                stack = style.energy + (0.3 if s.get("hero") else 0.0)
                others = [k for k in dict.fromkeys(kills) if k != first]
                if others and rng.random() < stack:
                    fx.append(draw(others, set(recent[-1:])))
                s["fx"] = fx
                recent.append(first)
            else:
                s["fx"] = []
        if what in ("all", "hero"):
            if s.get("hero") and heroes:
                last_hero = draw(heroes, {last_hero})
                s["hero_fx"] = [last_hero]
            elif not s.get("hero"):
                s["hero_fx"] = []
        if what in ("all", "camera") and cams:
            c = draw(cams, {last_cam} if last_cam != "c00" else set())
            s["camera"], last_cam = c, c
        if what in ("all", "speed") and speeds:
            if s.get("hero") and style.hero_speed in ids_of("speed"):
                s["speed"] = style.hero_speed
            else:
                sp = draw(speeds, {last_speed} if len(set(speeds)) > 1 and last_speed != "s00" else set())
                s["speed"], last_speed = sp, sp
        if what in ("all", "transition") and i > 0:
            acc += flash_share
            if acc >= 1.0 - 1e-9 and "t02" in ids_of("transition"):
                s["transition"], acc = "t02", acc - 1.0
            elif trans:
                # Against the last SOFT transition, not the last cut: a hard cut
                # between two dips-to-black does not stop them reading as a pair.
                softs = {t for t in trans if t not in ("t01", "t02")}
                t = draw(trans, {last_trans} if len(softs) > 1 and last_trans else set())
                s["transition"] = t
                if t not in ("t01", "t02"):
                    last_trans = t
            else:
                s["transition"] = "t01"
            s["tlen"] = _cut_seconds(s["transition"])
        elif i == 0:
            s["transition"], s["tlen"] = "t01", 0.0


def vary(project: dict, what: str = "all", seed: int | None = None) -> dict:
    """Mix a timeline's effects again without touching its shots or timing."""
    style = STYLE.get(project.get("style")) or STYLE[DEFAULT_STYLE]
    pools = project.get("pools") or {}
    if not any(pools.get(k) for k in POOL_KINDS):
        pools = _style_pools(style)
    if seed is None:
        seed = (int(project.get("seed") or 0) * 1103515245 + 12345) & 0x7FFFFFFF
    project["seed"] = int(seed)
    _vary(project["shots"], pools, style, seed, what if what in (*POOL_KINDS, "all") else "all")
    rulebook.budget(project["shots"], pools, what if what in POOL_KINDS else None)
    return project


# ============================================================== the song part

def max_pre(shot: dict, want: float) -> float:
    """The longest run-up, up to `want`, this shot's footage before its kill allows."""
    lo, hi = 0.0, max(0.0, want)
    big = max(60.0, want + 10.0)

    def fits(pre: float) -> bool:
        return source_used(pieces(shot["speed"], big, pre), pre) <= float(shot["kill"]) + 1e-6
    if fits(hi):
        return hi
    for _ in range(40):
        mid = (lo + hi) / 2
        if fits(mid):
            lo = mid
        else:
            hi = mid
    return lo


def max_post(shot: dict, pre: float, want: float) -> float:
    """The longest time after the kill, up to `want`, the footage after it allows."""
    room = max(0.0, float(shot["clip_seconds"]) - float(shot["kill"]))

    def fits(post: float) -> bool:
        ps = pieces(shot["speed"], pre + post, pre)
        return source_used(ps, pre + post) - source_used(ps, pre) <= room + 1e-6
    if fits(want):
        return want
    lo, hi = 0.0, want
    for _ in range(40):
        mid = (lo + hi) / 2
        if fits(mid):
            lo = mid
        else:
            hi = mid
    return lo


# The slowest a run-up is stretched to fill the time before its mark. Below this
# a clip reads as stills, not as play -- so what is still missing past it is a
# held opening frame instead, up to MAX_HOLD; past that the mark is given up.
MIN_STRETCH = 0.12
MAX_HOLD = 8.0
HOLD_RATE = 0.001
# Seconds before the kill that stay at real speed when a run-up is stretched:
# the action that leads into the kill plays as it happened.
STRETCH_REAL = 1.5


def stretch_to(shot: dict, pre: float) -> bool:
    """Give `shot` a run-up of `pre` seconds, slowing its footage if it has too little.

    THE KILL IS THE FIXED POINT. A mark says where the kill lands, so when the
    clip holds fewer seconds before its kill than the mark leaves room for, the
    kill does not move and neither does the cut -- the run-up is slowed
    instead: the last STRETCH_REAL seconds before the kill play as recorded,
    and everything before them is stretched to fill what is left. Three seconds
    of footage in front of a mark ten seconds in plays as 8.5 s of slow approach
    and 1.5 s of real action, and the kill frame is on the mark.

    -> whether the run-up now reaches `pre` (False only when it would have to
    run slower than MIN_STRETCH, and then the shot is left as it was).
    """
    shot.pop("stretch", None)
    pre = max(0.0, float(pre))
    if max_pre(shot, pre) >= pre - 1.0 / FPS:
        return True
    have = float(shot["kill"])                 # source seconds before the kill
    real = min(STRETCH_REAL, have * 0.5, pre * 0.5)
    if pre - real <= 1e-6 or have - real <= 1e-6:
        return False
    rate, hold = (have - real) / (pre - real), 0.0
    if rate < MIN_STRETCH:
        rate = MIN_STRETCH
        hold = pre - real - (have - real) / rate
        if hold > MAX_HOLD:
            return False
    shot["speed"] = "s00"
    # A hair slower than exact, so rounding never asks for a frame the clip
    # does not have before its kill.
    shot["stretch"] = [round(rate * 0.995, 4), round(real, 4), round(hold, 4)]
    return True


def apply_marks(project: dict, marks: list[float]) -> list[str]:
    """Re-time the timeline so the shots' kills land on the marks (reel seconds).

    Cuts move, never the marks: each shot starts as far before its mark as its
    own run-up wants and its footage allows, and the shot before it runs up to
    that cut. Shots past the last mark keep their lengths and follow on.

    Usually shot N takes mark N. The exception is an opener whose footage
    cannot reach the first mark -- see below: it becomes the reel's lead-in
    and the marks shift one shot along, so the mark still gets a kill.
    """
    notes: list[str] = []
    shots = project["shots"]
    marks = sorted(m for m in marks if m >= 0)
    if not marks or not shots:
        return notes

    # THE MARK GETS ITS KILL, EVEN WHEN THE OPENER CANNOT REACH IT.
    #
    # The opener is the one shot that cannot be moved to meet a mark: the reel
    # starts at reel zero, so its run-up is whatever footage sits before its
    # kill and not a frame more. Pinning it to the first mark anyway and
    # letting it land early spends that mark on a kill that never arrives
    # there -- measured on QUATROKAV2, where a part chosen from 2.0 s put the
    # first mark on the song's arrival at 12.12 s, the opener had 3.50 s of
    # footage before its kill, and the result was one shot stretched over the
    # whole arrival with its kill 6.63 s early. The drop, the loudest thing in
    # the part, got no cut at all.
    #
    # So an unreachable first mark is not consumed. The opener plays out its
    # own run-up unmarked -- the lead-in the intro effect covers -- and the
    # mark passes to the shot behind it, which starts wherever it needs to.
    # WHICH kill lands on the drop matters far less than that one does.
    lead = 0
    slack = max(0.25, float(project.get("beat") or 0.5))
    for s in shots:
        s.pop("stretch", None)              # the marks decide every stretch afresh
    if len(shots) > 1 and max_pre(shots[0], marks[0]) < marks[0] - slack             and not stretch_to(dict(shots[0]), marks[0]):
        lead = 1
    n = min(len(marks), len(shots) - lead)
    if n <= 0:
        return notes
    if len(marks) > len(shots) - lead:
        notes.append(f"{len(marks)} kills were marked but the reel has {len(shots) - lead} shots to "
                     f"put on them; the last {len(marks) - n} marks were not used.")
    cuts = []
    pres = []
    if lead:
        s0 = shots[0]
        # EVERY FRAME IT HAS, not the run-up it was planned with: footage
        # before the kill is lead-in, footage after it is a shot holding on
        # past its own point. The mark is the ceiling, and lead is only set
        # when the footage falls short of it.
        pre0 = max_pre(s0, marks[0])
        cuts.append(0.0)
        pres.append(pre0)
        notes.append(f"Shot 1 has only {pre0:.2f} s of footage before its kill and the first mark is "
                     f"{marks[0]:.2f} s in, so it opens the reel as the lead-in and shot 2's kill "
                     f"lands on that mark instead.")
    for i in range(n):
        s = shots[lead + i]
        k = marks[i]
        if i == 0 and not lead:
            pre = max_pre(s, k)
            if pre < k - 1.0 / FPS:
                if stretch_to(s, k):
                    notes.append(f"Shot 1 has {float(s['kill']):.2f} s of footage before its kill; "
                                 f"its run-up is slowed to fill the {k:.2f} s before the first mark.")
                    pre = k
                else:
                    notes.append(f"Shot 1 has only {pre:.2f} s of footage before its kill, so it lands "
                                 f"{k - pre:.2f} s before the first mark.")
            cuts.append(0.0)
            pres.append(pre)
            continue
        gap = k - (marks[i - 1] if i else pres[0])
        j = lead + i                                   # where this shot sits in the reel
        want = min(float(s["pre"]) if s["pre"] > 0 else gap / 2, max(0.0, gap - 0.22))
        pre = max_pre(s, want)
        cut = k - pre
        prev = shots[j - 1]
        need = cut - (cuts[j - 1] + pres[j - 1])       # time after the previous kill
        room = max_post(prev, pres[j - 1], need)
        if room < need - 1.0 / FPS:
            # The previous shot runs out: start this one earlier -- on its own
            # footage if it has enough, slowed if it has not -- so the gap is
            # filled with this shot's approach and its kill stays on the mark.
            reach = max(0.0, k - (cuts[j - 1] + pres[j - 1] + room))
            longer = max_pre(s, reach)
            if longer < reach - 1.0 / FPS and stretch_to(s, reach):
                longer = reach
            cut = k - longer
            pre = longer
            if cut > cuts[j - 1] + pres[j - 1] + room + 1.0 / FPS:
                notes.append(f"Shot {j} runs out of footage before shot {j + 1}'s mark; "
                             f"shot {j + 1} may land early.")
        cuts.append(max(cut, cuts[j - 1] + pres[j - 1] + 1.0 / FPS))
        pres.append(k - cuts[-1])
    for s in shots:
        s.pop("lead_in", None)
    if lead:
        shots[0]["lead_in"] = True
    for i in range(lead + n):
        s = shots[i]
        s["pre"] = round(pres[i], 5)
        if i < lead + n - 1:
            s["duration"] = round(cuts[i + 1] - cuts[i], 5)
        else:
            post = max(0.22, float(s["duration"]) - float(s["pre"]) if s["duration"] > s["pre"] else 0.5)
            s["duration"] = round(pres[i] + post, 5)
    return notes


def fit_to_part(project: dict, seconds: float) -> list[str]:
    """Leave out the shots the chosen part of the song cannot hold."""
    notes: list[str] = []
    if seconds <= 0:
        return notes
    kept, t = [], 0.0
    for s in project["shots"]:
        if t >= seconds - MIN_SHOT:
            break
        room = seconds - t
        if s["duration"] > room:
            if s["pre"] + 0.22 > room:
                break
            s["duration"] = round(room, 5)
        kept.append(s)
        t += s["duration"]
    dropped = len(project["shots"]) - len(kept)
    if dropped and kept:
        notes.append(f"The part of the song you chose holds {len(kept)} shots; "
                     f"the last {dropped} were left out.")
        project["shots"] = kept
    return notes


def apply_song(project: dict, shape, song: str, start: float, end: float = 0.0,
               marks: list[float] | None = None) -> list[str]:
    """Put a song, the part of it to use and any marked kills onto a timeline.

    `start`/`end` and `marks` are song seconds. Reel zero is `start` exactly --
    it is NOT snapped, because fine-tuning it by a few milliseconds is the
    point of the control.
    """
    notes: list[str] = []
    project["song"] = song
    # The new song's beat, and the same grid under it: how finely this reel
    # cuts is the style's, not the song's, so a new song keeps the division.
    was = float(project.get("beat") or 0.0)
    div = min((1, 2, 4), key=lambda d: abs(float(project.get("step") or was or 1.0) - was / d)) if was else 1
    project["beat"] = round(float(shape.beat), 6)
    project["step"] = round(float(shape.beat) / div, 6)
    start = max(0.0, min(float(start), max(0.0, shape.seconds - 1.0)))
    project["song_offset"] = round(start, 4)
    part = (min(float(end), shape.seconds) - start) if end and end > start else shape.seconds - start
    if marks:
        kept = [m for m in marks if start <= m <= start + part]
        project["song_marks"] = [round(m, 4) for m in sorted(kept)]
        notes += apply_marks(project, [m - start for m in kept])
    notes += fit_to_part(project, part)
    return notes


def _starts(shots: list[dict]) -> list[float]:
    out, t = [], 0.0
    for s in shots:
        out.append(t)
        t += float(s["duration"])
    return out


def _fit(shot: dict, beat: float, notes: list[str] | None = None) -> None:
    """Shrink a shot's run-up and tail, in whole beats, to the footage it has.

    Speed ramps eat source faster than real time, so this checks the source
    the pieces would actually consume -- not the output length.
    """
    dur_clip = float(shot.get("clip_seconds") or 0.0)
    if dur_clip <= 0:
        return
    kill = min(max(0.0, float(shot["kill"])), dur_clip)
    for _ in range(64):
        ps = shot_pieces(shot)
        before = source_used(ps, shot["pre"])
        after = source_used(ps, shot["duration"]) - before
        ok_head = kill - before >= -1e-6
        ok_tail = kill + after <= dur_clip + 1e-6
        if ok_head and ok_tail:
            return
        step = beat if beat >= MIN_SHOT else MIN_SHOT
        if not ok_head and shot["pre"] > 1e-6:
            cut = min(step, shot["pre"])
            shot["pre"] = round(shot["pre"] - cut, 5)
            shot["duration"] = round(shot["duration"] - cut, 5)
        elif not ok_tail and shot["duration"] - shot["pre"] > step:
            shot["duration"] = round(shot["duration"] - step, 5)
        elif shot.get("stretch"):
            shot.pop("stretch", None)       # a stretch that no longer fits is dropped
        elif shot["speed"] != "s00":
            shot["speed"] = "s00"           # a clip too short to ramp plays straight
        else:
            # Less than a beat either side: keep whatever real footage there is.
            shot["pre"] = round(min(shot["pre"], kill), 5)
            shot["duration"] = round(max(MIN_SHOT, min(shot["duration"],
                                                       shot["pre"] + dur_clip - kill)), 5)
            if notes is not None:
                notes.append(f"{shot.get('name') or 'A clip'} is too short for the beat grid; it was trimmed to fit.")
            return


# ============================================================== checking

class ProjectError(ValueError):
    pass


def _num(v, lo: float, hi: float, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return max(lo, min(hi, f))


def _probe_seconds(path: Path) -> float:
    try:
        from .tools import media_info
        return float(media_info(path).get("duration") or 0.0)
    except Exception:                                   # noqa: BLE001
        return 0.0


def normalise(project: dict, root: Path, *, probe=_probe_seconds) -> tuple[dict, dict, list[str]]:
    """Make a project safe to render, and work out everything derived from it.

    Anything the page sends is untrusted: a clip must be inside the clips
    folder, every part id must exist, every number is clamped. -> (project,
    derived, notes). Raises ProjectError when there is nothing renderable.
    """
    if not isinstance(project, dict):
        raise ProjectError("No project was sent.")
    notes: list[str] = []
    root_r = root.resolve()
    out: dict[str, Any] = {
        "version": VERSION,
        "name": str(project.get("name") or "Reel")[:80],
        "style": str(project.get("style") or DEFAULT_STYLE) if str(project.get("style") or "") in STYLE else DEFAULT_STYLE,
        "format": project.get("format") if project.get("format") in SIZES else "landscape",
        "song": "", "song_offset": 0.0,
        "intro": project.get("intro") if project.get("intro") in ids_of("intro") else "i00",
        "outro": project.get("outro") if project.get("outro") in ids_of("outro") else "e12",
        # The DRAWER, not the hand-written GRADES table: a generated tint is a
        # real grade with no row in it, and checking the table quietly turned
        # every one of them back into g01.
        "grade": project.get("grade") if project.get("grade") in ids_of("grade") else "g01",
        "vignette": bool(project.get("vignette")),
        "overlays": [o for o in dict.fromkeys(project.get("overlays") or []) if o in ids_of("overlay")],
        "handle": re.sub(r"[\r\n]", " ", str(project.get("handle") or ""))[:40],
        "music_db": _num(project.get("music_db"), -30, 12, 0.0),
        "game_db": _num(project.get("game_db"), -30, 12, 0.0),
        "duck": bool(project.get("duck", True)),
        "saturation": round(_num(project.get("saturation"), 0.3, 1.5, 1.0), 3),
        "kill_sound": bool(project.get("kill_sound", True)),
        "beat": _num(project.get("beat"), 0.2, 2.0, 60.0 / NO_SONG_BPM),
        "seed": int(_num(project.get("seed"), 0, 2 ** 31 - 1, 0)),
        "pools": {},
        "output": "",
        "shots": [],
    }
    # The grid a fast style was planned on. A reel made before the grid could
    # be finer than a beat has no step, and a whole beat is what it was built
    # on -- so that is the default, and trimming a shot never knocks it off its
    # own grid.
    out["step"] = _grid_step(project.get("step"), out["beat"])
    out["shaping"] = _shaping(project.get("shaping"))
    arranged = _arrangement({"arrange": project.get("arrange"), "pins": project.get("pins")})
    out["arrange"], out["pins"] = arranged["arrange"], arranged["pins"]
    raw_pools = project.get("pools") if isinstance(project.get("pools"), dict) else {}
    for kind, part_kind in POOL_KINDS.items():
        valid = set(ids_of(part_kind))
        out["pools"][kind] = [p for p in (raw_pools.get(kind) or []) if p in valid][:40]
    song = str(project.get("song") or "")
    if song:
        sp = Path(song)
        if sp.is_file() and sp.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"):
            out["song"] = str(sp)
            out["song_offset"] = _num(project.get("song_offset"), 0.0, 36000.0, 0.0)
            # Where the chosen part ends, so the Song tab and a rebuild reopen
            # on the part the player picked rather than on the reel's length.
            end = _num(project.get("part_end"), 0.0, 36000.0, 0.0)
            if end > out["song_offset"]:
                out["part_end"] = round(end, 5)
            # The song's own hits this reel's kills were put on, so the
            # timeline can draw them under the kills and show the drift.
            marks = [round(_num(m, 0.0, 36000.0, -1.0), 4)
                     for m in (project.get("song_marks") or [])[:MAX_SHOTS * 2]]
            marks = sorted({m for m in marks if m >= 0})
            if marks:
                out["song_marks"] = marks
        else:
            notes.append("The song is no longer on disk, so this reel has no music.")
    output = str(project.get("output") or "")
    if output:
        op = Path(output)
        try:
            if op.suffix.lower() == ".mp4" and op.resolve().is_relative_to((root_r / "reels").resolve()):
                out["output"] = str(op)
        except OSError:
            pass

    seconds_cache: dict[str, float] = {}
    for raw in (project.get("shots") or [])[:MAX_SHOTS]:
        if not isinstance(raw, dict):
            continue
        cp = Path(str(raw.get("clip") or ""))
        try:
            inside = cp.resolve().is_relative_to(root_r)
        except OSError:
            inside = False
        if not inside or cp.suffix.lower() not in (".mp4", ".m4v", ".mov", ".mkv") or not cp.is_file():
            notes.append(f"{cp.name or 'A shot'} is not a clip in the clips folder, so it was left out.")
            continue
        key = str(cp)
        try:
            mtime = int(cp.stat().st_mtime)
        except OSError:
            mtime = 0
        if key not in seconds_cache:
            given = _num(raw.get("clip_seconds"), 0.0, 36000.0, 0.0)
            # Trust the stored length only for the file it was measured on. A
            # clip re-cut on the Clips page keeps its path and changes length.
            same = int(_num(raw.get("clip_mtime"), 0, 2 ** 40, 0)) == mtime
            seconds_cache[key] = given if (given > 0 and same) else probe(cp)
        cs = seconds_cache[key]
        if cs <= 0:
            notes.append(f"{cp.name} could not be read, so it was left out.")
            continue
        kills = [round(_num(k, 0.0, cs, 0.0), 3) for k in (raw.get("kills") or [])][:12]
        shot = {
            "clip": key, "clip_id": clip_id(cp), "name": str(raw.get("name") or cp.stem)[:120],
            "clip_seconds": round(cs, 3), "clip_mtime": mtime, "kills": kills or [round(cs / 2, 3)],
            "kill": round(_num(raw.get("kill"), 0.0, cs, kills[0] if kills else cs / 2), 3),
            "duration": round(_num(raw.get("duration"), MIN_SHOT, 60.0, 2.0), 5),
            "pre": 0.0,
            "speed": raw.get("speed") if raw.get("speed") in ids_of("speed") else "s00",
            "fx": [f for f in dict.fromkeys(raw.get("fx") or []) if f in ids_of("kill")],
            "hero": bool(raw.get("hero")),
            # Set by apply_marks on an opener that cannot reach the first
            # mark: it is the lead-in, so the timeline must not score its kill
            # against a mark it was never aimed at.
            "lead_in": bool(raw.get("lead_in")),
            "hero_fx": [f for f in dict.fromkeys(raw.get("hero_fx") or []) if f in ids_of("hero")],
            "camera": raw.get("camera") if raw.get("camera") in ids_of("camera") else "c00",
            "transition": raw.get("transition") if raw.get("transition") in ids_of("transition") else "t01",
            "tlen": 0.0,
            "_want": _num(raw.get("tlen"), 0.0, 1.5, -1.0),
            "caption": re.sub(r"[\r\n]", " ", str(raw.get("caption") or ""))[:40],
        }
        shot["pre"] = round(_num(raw.get("pre"), 0.0, shot["duration"], shot["duration"] / 2), 5)
        st = raw.get("stretch")
        if isinstance(st, (list, tuple)) and len(st) in (2, 3):
            rate = _num(st[0], MIN_STRETCH * 0.99, 1.0, 1.0)
            if rate < 0.999:
                shot["stretch"] = [round(rate, 4), round(_num(st[1], 0.0, 60.0, 0.0), 4),
                                   round(_num(st[2] if len(st) > 2 else 0, 0.0, MAX_HOLD + 0.01, 0.0), 4)]
        before = (shot["pre"], shot["duration"], shot["speed"])
        _fit(shot, out["step"])
        if (shot["pre"], shot["duration"], shot["speed"]) != before:
            notes.append(f"{shot['name']}: trimmed to the footage the clip has.")
        out["shots"].append(shot)

    if not out["shots"]:
        raise ProjectError("There are no usable clips in this reel.")

    # The clips that were chosen for this reel and why any are not in it: what
    # "Add clips" rebuilds from. Only for display and for a new plan, which
    # checks every path against the library again.
    sel = []
    for row in (project.get("selection") or [])[:MAX_SHOTS * 2]:
        if isinstance(row, dict) and str(row.get("clip") or ""):
            sel.append({"clip": str(row["clip"])[:1000],
                        "name": re.sub(r"[\r\n]", " ", str(row.get("name") or Path(str(row["clip"])).stem))[:120],
                        "why": re.sub(r"[\r\n]", " ", str(row.get("why") or ""))[:200]})
    if sel:
        out["selection"] = sel
    if isinstance(project.get("plan_sig"), str) and re.fullmatch(r"[0-9a-f]{8}", project["plan_sig"]):
        out["plan_sig"] = project["plan_sig"]
    # What the planner said when it made this reel -- "the reel ends early",
    # "the weakest were left out". Kept on the project: said only in the reply
    # to the plan, it was replaced a moment later by the render's reply, so
    # nobody ever read why their clips were missing.
    said = [re.sub(r"[\r\n]", " ", str(n))[:300] for n in (project.get("plan_notes") or [])
            if isinstance(n, str) and n.strip()][:20]
    if said:
        out["plan_notes"] = said

    # Transitions need footage either side of the cut; shorten them to fit.
    shots = out["shots"]
    shots[0]["transition"], shots[0]["tlen"] = "t01", 0.0
    shots[0].pop("_want", None)
    for i in range(1, len(shots)):
        s, prev = shots[i], shots[i - 1]
        t = s["transition"]
        want = s.pop("_want", -1.0)
        want = _cut_seconds(t) if want is None or want <= 0 else want
        if t == "t01" or want <= 0:
            s["transition"], s["tlen"] = "t01", 0.0
            continue
        want = min(want, 1.5, s["duration"] * 0.8, prev["duration"] * 0.8)
        head_room = _head_room(s)
        tail_room = _tail_room(prev)
        half = min(want / 2, head_room, tail_room)
        if half < 1.0 / FPS:
            s["transition"], s["tlen"] = "t01", 0.0
            notes.append(f"{s['name']}: not enough footage around the cut for a transition, so it is a hard cut.")
            continue
        s["tlen"] = round(half * 2, 4)

    # THE INTRO CLIP, LAST, BECAUSE IT IS MEASURED AGAINST THE FINISHED REEL.
    # It plays in front of the reel, so it cannot swallow anything and its
    # length is its own business -- intros.MAX_SECONDS is the only cap, and
    # import already applied it. What is still worth saying is when the opener
    # is longer than the reel behind it, which is nearly always a mistrim.
    out["intro_clip"] = None
    raw = project.get("intro_clip")
    if isinstance(raw, dict) and str(raw.get("path") or "").strip():
        from . import intros

        got = intros.entry(str(raw.get("path")))
        if got is None:
            notes.append("The intro clip is not in your intros folder any more, "
                         "so the reel opens without it.")
        else:
            src = float(got["seconds"]) or 0.0
            a = _num(raw.get("start"), 0.0, max(0.0, src), 0.0)
            b = _num(raw.get("end"), 0.0, max(0.0, src), src)
            if b <= a:
                b = src
            reel = sum(float(s["duration"]) for s in shots)
            if b - a > reel:
                notes.append(f"The intro runs {b - a:.1f} s, longer than the "
                             f"{reel:.1f} s reel behind it. It still plays in full.")
            if b - a < MIN_INTRO_SECONDS:
                notes.append("The intro was too short to see, so the reel opens without it.")
            else:
                out["intro_clip"] = {
                    "path": got["path"], "name": got["name"],
                    "start": round(a, 3), "end": round(b, 3),
                    # What the user asked for, and what the file can actually
                    # do. Kept apart so turning sound on for a silent GIF is
                    # remembered rather than silently rewritten.
                    "audio": bool(raw.get("audio")), "has_audio": bool(got["has_audio"]),
                    "fit": raw.get("fit") if raw.get("fit") in INTRO_FITS else "cover"}
    return out, derive(out), notes


def _span(shot: dict) -> tuple[float, float]:
    """Source seconds the shot's own (handle-free) footage covers."""
    ps = shot_pieces(shot)
    start = shot["kill"] - source_used(ps, shot["pre"])
    return start, start + source_used(ps, shot["duration"])


def _head_room(shot: dict) -> float:
    return max(0.0, _span(shot)[0])


def _tail_room(shot: dict) -> float:
    return max(0.0, float(shot["clip_seconds"]) - _span(shot)[1])


def derive(project: dict) -> dict:
    """Everything the timeline draws that follows from the project."""
    shots = project["shots"]
    starts = _starts(shots)
    length = starts[-1] + shots[-1]["duration"] if shots else 0.0
    kills_reel = []
    rows = []
    for i, (s, t0) in enumerate(zip(shots, starts)):
        ps = shot_pieces(s)
        a, b = _span(s)
        inside = []
        for k in s["kills"]:
            if a - 1e-6 <= k <= b + 1e-6:
                inside.append(round(t0 + output_at(ps, k - a), 4))
        kills_reel.extend(inside)
        rows.append({"index": i, "start": round(t0, 5), "end": round(t0 + s["duration"], 5),
                     "kill_reel": round(t0 + s["pre"], 5), "kills_reel": inside,
                     "lead_in": bool(s.get("lead_in")),
                     "source_in": round(a, 4), "source_out": round(b, 4),
                     "pieces": [[round(x, 4), round(y, 4), r] for x, y, r in ps]})
    beat = float(project.get("beat") or 60.0 / NO_SONG_BPM)
    beats = [round(k * beat, 4) for k in range(int(length / beat) + 2) if k * beat <= length + 1e-6]
    # WHERE THE SONG SAID EACH KILL SHOULD LAND. The marks are song seconds and
    # reel zero is song_offset, so one subtraction -- the same one the render
    # does -- puts them on the timeline's axis. Every shot then knows the mark
    # nearest its kill and how far off it is, which is what the music lane
    # draws: a kill on its hit is the whole claim the reel makes.
    offset = float(project.get("song_offset") or 0.0)
    marks = sorted(round(m - offset, 4) for m in (project.get("song_marks") or [])
                   if -0.5 <= float(m) - offset <= length + 0.5)
    on_marks = 0
    for row in rows:
        near = (min(marks, key=lambda m: abs(m - row["kill_reel"]))
                if marks and not shots[row["index"]].get("lead_in") else None)
        row["mark"] = near
        row["drift"] = round(row["kill_reel"] - near, 4) if near is not None else None
        if near is not None and abs(row["drift"]) <= ON_MARK:
            on_marks += 1
    in_reel = {str(s["clip"]).lower() for s in shots}
    selection = [{"clip": r["clip"], "name": r["name"],
                  "in": str(r["clip"]).lower() in in_reel,
                  "why": "" if str(r["clip"]).lower() in in_reel else (r.get("why") or "Removed on the timeline.")}
                 for r in project.get("selection") or []]
    # THE HOLE AN INTRO IS FOR. A lead-in opener holds from reel zero until the
    # song reaches the first mark, and that hold is the dead air the user wants
    # covered -- so the page can offer "fit the lead-in" as one button instead
    # of asking them to work the number out from the timeline.
    lead_in = round(float(shots[0]["pre"]), 4) if shots and shots[0].get("lead_in") else 0.0
    ic = project.get("intro_clip") or None
    intro_clip = {"path": ic["path"], "name": ic.get("name") or "",
                  "seconds": round(float(ic["end"]) - float(ic["start"]), 4),
                  "start": ic["start"], "end": ic["end"],
                  "audio": bool(ic.get("audio")) and bool(ic.get("has_audio")),
                  "has_audio": bool(ic.get("has_audio")),
                  "fit": ic.get("fit") or "cover"} if ic else None
    return {"length": round(length, 4), "shots": rows, "kills": sorted(kills_reel),
            "beats": beats, "beat": beat, "bpm": round(60.0 / beat, 2),
            "marks": marks, "on_marks": on_marks, "on_mark_window": ON_MARK,
            "selection": selection, "lead_in": lead_in, "intro_clip": intro_clip,
            "edited": bool(project.get("plan_sig")) and signature(shots) != project.get("plan_sig")}


def signature(shots: list[dict]) -> str:
    """What a rebuild would replace: every choice on the timeline, as eight hex digits.

    Stored when a reel is planned; a timeline whose shots no longer match it
    has been edited, and "Add clips" says so before re-planning over the edits.
    """
    keys = ("clip", "kill", "pre", "duration", "speed", "fx", "hero", "hero_fx", "camera",
            "transition", "caption")
    raw = json.dumps([[s.get(k) for k in keys] for s in shots], sort_keys=True)
    return f"{zlib.crc32(raw.encode('utf-8')) & 0xFFFFFFFF:08x}"


# ============================================================== rendering

def _font() -> str:
    for name in ("bahnschrift.ttf", "arialbd.ttf", "arial.ttf", "segoeuib.ttf"):
        p = Path("C:/Windows/Fonts") / name
        if p.is_file():
            return "fontfile='" + str(p).replace("\\", "/").replace(":", "\\:") + "':"
    return ""


def _path_arg(p: Path) -> str:
    """A file path as a quoted drawtext option: C\\:/like/this."""
    return "'" + str(p).replace("\\", "/").replace(":", "\\:") + "'"


def text_file(folder: Path | None, text: str) -> Path:
    """Write `text` to a file drawtext can read, and return its path.

    THROUGH A FILE, NEVER INLINE. Inline text has to survive two levels of
    ffmpeg escaping, and measured: a caption as ordinary as "it's" failed the
    whole render, and the escaping that got past the parser drew nothing at
    all. A file carries any character exactly.
    """
    folder = Path(folder) if folder else Path(tempfile.gettempdir()) / "autostream-studio-text"
    folder.mkdir(parents=True, exist_ok=True)
    data = str(text).encode("utf-8")
    p = folder / f"{hashlib.sha1(data).hexdigest()[:16]}.txt"
    if not p.is_file():
        p.write_bytes(data)
    return p


def _between(a: float, b: float) -> str:
    return f"between(t,{a:.4f},{b:.4f})"


def _fade_seconds(pid: str, default: float) -> float:
    """How long a generated fade runs; hand-written intros keep their own."""
    return knob(pid, "secs", default)


def _fade_colour(pid: str) -> str:
    """What a generated fade goes through."""
    i = int(knob(pid, "colour", 0.0))
    hexes = parts_mod.FADE_HEX
    return hexes[i] if 0 <= i < len(hexes) else "black"


def _wash_colour(hue: float) -> str:
    """A hue in degrees as a hex colour for drawbox. -1 means white."""
    if hue < 0:
        return "0xffffff"
    h = (hue % 360.0) / 60.0
    c, x = 1.0, 1.0 - abs(h % 2.0 - 1.0)
    rgb = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h) % 6]
    # Lifted off pure, because a fully saturated wash reads as a broken frame
    # rather than a hit: the reference edits' colour hits all sit off the edge
    # of the gamut.
    return "0x" + "".join(f"{int(round((0.18 + 0.82 * v) * 255)):02x}" for v in rgb)


def _pulse(var: str, at: float, amount: float, fall: float) -> str:
    """`amount` at `at`, decaying linearly to nothing over `fall` seconds."""
    return f"{amount}*gte({var},{at:.4f})*max(0,1-({var}-{at:.4f})/{fall})"


@dataclass
class Segment:
    """Everything that decides one shot's render -- and so its cache key."""
    index: int
    clip: str
    clip_mtime: float
    width: int
    height: int
    fmt: str
    head: int          # frames of handle before the shot
    body: int          # frames of the shot itself
    tail: int          # frames of handle after it
    src_start: float   # source seconds at the first handle frame
    pieces: list       # output seconds (handle-relative) -> rate
    kill_at: float     # seconds into the segment
    fx: list
    hero_fx: list
    camera: str
    grade: str
    vignette: bool
    caption: str
    beats: list        # beat times inside the segment, segment seconds
    freeze: float      # seconds of freeze inserted at the kill
    freeze_push: bool
    has_audio: bool
    outro_freeze: float = 0.0
    sat_trim: float = 1.0
    kill_times: list = field(default_factory=list)   # every kill shown, segment seconds
    game_gate: bool = False                          # game sound only around the kills

    def key(self) -> str:
        d = dict(self.__dict__)
        d.pop("index", None)
        blob = json.dumps(d, sort_keys=True, default=str)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:20]

    @property
    def frames(self) -> int:
        return self.head + self.body + self.tail


def segments(project: dict, derived: dict, *, has_audio=lambda p: True,
             song_beats: list[float] | None = None) -> list[Segment]:
    """The shot renders a project needs, with the handles its transitions use."""
    W, H = SIZES[project["format"]]
    shots = project["shots"]
    starts = [round(r["start"] * FPS) for r in derived["shots"]]
    ends = starts[1:] + [round(derived["length"] * FPS)]
    out = []
    for i, s in enumerate(shots):
        head = round(s["tlen"] / 2 * FPS) if i > 0 else 0
        tail = round(shots[i + 1]["tlen"] / 2 * FPS) if i + 1 < len(shots) else 0
        body = max(1, ends[i] - starts[i])
        dur = body / FPS
        speed = s["speed"]
        if i == len(shots) - 1 and project["outro"] == "e03":
            speed = "exit"
        ps = pieces(speed, dur, min(s["pre"], dur), _stretch_of(s))
        src_body_start = s["kill"] - source_used(ps, min(s["pre"], dur))
        hsec, tsec = head / FPS, tail / FPS
        seg_ps = []
        if head:
            seg_ps.append((0.0, hsec, 1.0))
        seg_ps += [(a + hsec, b + hsec, r) for a, b, r in ps]
        if tail:
            seg_ps.append((hsec + dur, hsec + dur + tsec, 1.0))
        freeze = 0.0
        push = False
        if "k04" in s["fx"]:
            freeze = 0.4
        # By FAMILY, not by id: "h02" is only the middle of the freeze family,
        # and an exact match left "Freeze and push in (a long beat)" offered,
        # picked and doing nothing at all.
        if s["hero"] and (pid := picked(s["hero_fx"], "h02")):
            freeze, push = max(freeze, knob(pid, "hold", 0.75)), True
        kill_at = hsec + min(s["pre"], dur)
        # Every kill this shot shows, where it plays in the segment -- through
        # the speed map, so a slowed kill is still gated at the right moment.
        k_src = source_used(ps, min(s["pre"], dur))
        kill_times = sorted({round(hsec + output_at(ps, max(0.0, k_src + (k - s["kill"]))), 4)
                             for k in s["kills"] if s["kill"] - 1e-6 <= k <= s["kill"] + dur})
        seg_beats = []
        if song_beats is not None:
            seg_beats = [round(b - (starts[i] / FPS - hsec), 4) for b in song_beats
                         if starts[i] / FPS - hsec <= b <= starts[i] / FPS + dur + tsec][:32]
        try:
            mtime = Path(s["clip"]).stat().st_mtime
        except OSError:
            mtime = 0.0
        out.append(Segment(
            index=i, clip=s["clip"], clip_mtime=mtime, width=W, height=H, fmt=project["format"],
            head=head, body=body, tail=tail, src_start=round(src_body_start - hsec, 4),
            pieces=[[round(a, 5), round(b, 5), r] for a, b, r in seg_ps], kill_at=round(kill_at, 5),
            fx=list(s["fx"]), hero_fx=list(s["hero_fx"]) if s["hero"] else [],
            camera=s["camera"], grade=project["grade"], vignette=project["vignette"],
            caption=s["caption"] if (s["hero"] and picked(s["hero_fx"], "h05")) else "",
            beats=seg_beats if fam(s["camera"]) == "c04" else [],
            freeze=freeze, freeze_push=push, has_audio=has_audio(s["clip"]),
            outro_freeze=1.0 if (i == len(shots) - 1 and project["outro"] == "e02") else 0.0,
            sat_trim=float(project.get("saturation", 1.0)),
            kill_times=kill_times or [round(kill_at, 4)],
            game_gate=bool(project.get("song")) and bool(project.get("kill_sound", True))))
    return out


def _setpts_expr(ps: list) -> str:
    """Source seconds -> output seconds, piecewise, as one setpts expression."""
    x = "(T-STARTT)"
    src0, parts = 0.0, []
    for a, b, r in ps:
        src1 = src0 + (b - a) * r
        parts.append((src1, f"({a:.6f}+({x}-{src0:.6f})/{r})"))
        src0 = src1
    expr = parts[-1][1]
    for src1, e in reversed(parts[:-1]):
        expr = f"if(lt({x},{src1:.6f}),{e},{expr})"
    return f"setpts='({expr})/TB'"


def segment_command(seg: Segment, out: Path, ff: str = "ffmpeg", encoder_args=None,
                    textdir: Path | None = None) -> list[str]:
    """ffmpeg argv that renders one shot, handles included, to `out`."""
    W, H, F = seg.width, seg.height, FPS
    total = seg.frames                  # a freeze replaces footage; it never lengthens a shot
    total_s = total / F
    kt = seg.kill_at
    src_len = sum((b - a) * r for a, b, r in seg.pieces)
    start = max(0.0, seg.src_start)
    lead = start - seg.src_start          # > 0 only if the clip starts late; padded below

    v = [_setpts_expr(seg.pieces), f"fps={F}"]
    if lead > 1e-3:
        v.append(f"tpad=start_duration={lead:.4f}:start_mode=clone")
    if seg.freeze > 0:
        v.append(f"loop=loop={round(seg.freeze * F)}:size=1:start={round(kt * F)}")
        v.append(f"setpts=N/{F}/TB")
    if seg.outro_freeze > 0:
        n = round(seg.outro_freeze * F)
        v.append(f"loop=loop={n}:size=1:start={max(0, total - n)}")
        v.append(f"setpts=N/{F}/TB")
    if seg.fmt == "vertical":
        v.append(f"crop='min(iw,ih*9/16)':ih,scale={W}:{H}:flags=lanczos")
    else:
        v.append(f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}")
    v.append("setsar=1")

    hold = seg.freeze
    T = "in_time"                       # zoompan's clock; every other filter uses t
    z_terms = []
    if (pid := picked(seg.fx, "k01")):
        z_terms.append(_pulse(T, kt, knob(pid, "amt", 0.12), knob(pid, "fall", 0.35)))
    if (pid := picked(seg.hero_fx, "h01")):
        gap = knob(pid, "gap", 0.16)
        z_terms.append(_pulse(T, kt, 0.10, 0.18))
        z_terms.append(_pulse(T, kt + gap, 0.16, 0.35))
    if seg.freeze_push:
        z_terms.append(f"if(between({T},{kt:.4f},{kt + hold:.4f}),0.4*({T}-{kt:.4f})/{hold:.4f},"
                       f"{_pulse(T, kt + hold, 0.4, 0.25)})")
    if (pid := picked(seg.fx, "k17")):
        # Held close through the run-up and let go ON the kill: the release is
        # the beat, where k01's arrival is. A reel that only ever punches in
        # reads as one effect however often the pool is redrawn.
        z_terms.append(f"{knob(pid, 'amt', 0.12)}*(1-min(1,max(0,({T}-{kt:.4f})"
                       f"/{knob(pid, 'rise', 0.30):.3f})))")
    if (pid := picked(seg.fx, "k21")):
        z_terms.append(_pulse(T, kt, knob(pid, "amt", 0.18), 0.22))
    cam = fam(seg.camera)
    # HOW A MOVE GETS WHERE IT IS GOING, as an expression in 0..1 over the shot.
    # Even is a dolly; slow-in creeps then commits; slow-out leaves at once and
    # settles. See parts.CAMERA_CURVES.
    span = max(total_s, 0.1)
    def eased(var: str) -> str:
        u = f"min(1,max(0,{var}/{span:.4f}))"
        c = int(knob(seg.camera, "curve", 0.0))
        if c == 1:
            return f"pow({u},2)"
        if c == 2:
            return f"(1-pow(1-{u},2))"
        return u
    if cam == "c01":
        z_terms.append(f"{knob(seg.camera, 'amt', 0.12)}*{eased(T)}")
    if cam == "c05":
        z_terms.append(f"{knob(seg.camera, 'amt', 0.14)}*(1-{eased(T)})")
    if cam == "c08":
        # One breath over the shot, never a loop: a sine that repeats reads as
        # a wobble rather than a camera.
        z_terms.append(f"{knob(seg.camera, 'amt', 0.07)}*sin(PI*{eased(T)})")
    if cam == "c04":
        for b in seg.beats:
            z_terms.append(_pulse(T, b, knob(seg.camera, "amt", 0.06), 0.18))
    if z_terms:
        v.append(f"zoompan=z='1+{'+'.join(z_terms)}'"
                 f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={F}")
    # EVERYTHING THAT MOVES THE FRAME SHARES ONE OVERSIZE. Shake, drift, pan
    # and rotation all need slack around the picture to move into; giving each
    # its own scale/crop pair would resample the frame once per effect and
    # stack their crops. One scale, one optional rotate, one crop.
    shake_id, tilt_id = picked(seg.fx, "k02"), picked(seg.fx, "k22")
    rot_id = picked(seg.fx, "k19")
    turns = bool(rot_id) or cam == "c06"
    if shake_id or tilt_id or turns or cam in ("c03", "c07"):
        # A degree of rotation throws a 1080-tall frame's corners about 16 px;
        # 1.12 leaves 115 px a side, so nothing black ever reaches the crop.
        over = 1.12 if turns else 1.08
        sx, sy = round(W * over) // 2 * 2, round(H * over) // 2 * 2
        mx, my = (sx - W) / 2, (sy - H) / 2
        xs, ys = [f"{mx:.1f}"], [f"{my:.1f}"]
        if shake_id:
            amp, fall = knob(shake_id, "amp", 0.7), knob(shake_id, "fall", 0.45)
            hz = knob(shake_id, "freq", 70.0)
            env = f"gte(t,{kt:.4f})*max(0,1-(t-{kt:.4f})/{fall:.3f})"
            xs.append(f"{mx * amp:.1f}*sin(t*{hz:.1f})*{env}")
            ys.append(f"{my * amp:.1f}*cos(t*{hz * 1.19:.1f})*{env}")
        if tilt_id:
            # Up and down only. A sideways rattle reads as the player flicking;
            # a vertical one reads as the hit landing.
            amp, fall = knob(tilt_id, "amp", 0.85), knob(tilt_id, "fall", 0.40)
            env = f"gte(t,{kt:.4f})*max(0,1-(t-{kt:.4f})/{fall:.3f})"
            ys.append(f"{my * amp:.1f}*sin(t*64)*{env}")
        if cam == "c03":
            a = knob(seg.camera, "amp", 0.6)
            xs.append(f"{mx * a:.1f}*sin(t*1.3)+{mx * a / 3:.1f}*sin(t*3.7)")
            ys.append(f"{my * a:.1f}*cos(t*1.1)")
        if cam == "c07":
            # All the way across the slack, once, over the whole shot.
            a = knob(seg.camera, "amp", 0.9)
            xs.append(f"{mx * a:.1f}*(2*t/{max(total_s, 0.1):.4f}-1)")
        turn = []
        if rot_id:
            turn.append(f"{knob(rot_id, 'rad', 0.026)}*gte(t,{kt:.4f})"
                        f"*max(0,1-(t-{kt:.4f})/{knob(rot_id, 'fall', 0.35):.3f})")
        if cam == "c06":
            turn.append(f"{knob(seg.camera, 'rad', 0.030)}*(t/{max(total_s, 0.1):.4f}-0.5)")
        chain = [f"scale={sx}:{sy}"]
        if turn:
            chain.append(f"rotate=a='{'+'.join(turn)}':ow={sx}:oh={sy}:c=none")
        chain.append(f"crop={W}:{H}:x='{'+'.join(xs)}':y='{'+'.join(ys)}'")
        v.append(",".join(chain))

    sat, con, bri, static = _grade_of(seg.grade)
    b_terms, c_terms, s_terms = [f"{bri}"], [f"{con}"], [f"{sat * seg.sat_trim:.3f}"]
    if (pid := picked(seg.fx, "k03")):
        b_terms.append(f"{knob(pid, 'amt', 0.55)}*gte(t,{kt:.4f})"
                       f"*max(0,1-(t-{kt:.4f})/{knob(pid, 'fall', 0.12):.3f})")
    if (pid := picked(seg.fx, "k16")):
        per = max(2.0, knob(pid, "period", 4.0))
        b_terms.append(f"{knob(pid, 'amt', 0.35)}*{_between(kt, kt + knob(pid, 'dur', 0.25))}"
                       f"*lt(mod(t*{F},{per:.0f}),{per / 2:.0f})")
    s_expr = "+".join(s_terms)
    if (pid := picked(seg.fx, "k07")):
        lo, hi = knob(pid, "from", 0.4), knob(pid, "to", 1.45)
        s_expr = (f"({s_expr})*if(lt(t,{kt:.4f}),{lo},{hi}-{hi - 1.0:.3f}"
                  f"*min(1,(t-{kt:.4f})/{knob(pid, 'fall', 0.6):.3f}))")
    c_expr = "+".join(c_terms)
    if (pid := picked(seg.fx, "k11")):
        win = _between(kt, kt + knob(pid, "dur", 0.3))
        c_expr = f"({c_expr})*if({win},{knob(pid, 'con', 1.45)},1)"
        s_expr = f"({s_expr})*if({win},{knob(pid, 'sat', 1.2)},1)"
    if picked(seg.hero_fx, "h03"):
        s_expr = f"({s_expr})*if({_between(kt, kt + 0.8)},0.7,1)"
    v.append(f"eq=brightness='{'+'.join(b_terms)}':contrast='{c_expr}':saturation='{s_expr}':eval=frame")
    if static:
        v.append(static)
    if (pid := picked(seg.fx, "k06")):
        px = int(knob(pid, "px", 9.0))
        v.append(f"rgbashift=rh={px}:bh=-{px}:enable='{_between(kt, kt + knob(pid, 'dur', 0.18))}'")
    if (pid := picked(seg.fx, "k08")):
        v.append(f"drawbox=x=0:y=0:w=iw:h=ih:color={_wash_colour(knob(pid, 'hue', 0.0))}"
                 f"@{knob(pid, 'alpha', 0.3)}:t=fill:"
                 f"enable='{_between(kt, kt + knob(pid, 'dur', 0.15))}'")
    if (pid := picked(seg.fx, "k12")):
        v.append(f"negate=enable='{_between(kt, kt + knob(pid, 'dur', 0.05))}'")
    if (pid := picked(seg.fx, "k14")):
        v.append(f"boxblur={int(knob(pid, 'r', 6.0))}:1:"
                 f"enable='{_between(kt, kt + knob(pid, 'dur', 0.25))}'")
    if (pid := picked(seg.fx, "k21")):
        # Shorter and harder than the blur snap: it clears while the punch is
        # still settling, so the frame arrives sharp on the beat.
        v.append(f"gblur=sigma={knob(pid, 'sigma', 14.0)}:"
                 f"enable='{_between(kt, kt + knob(pid, 'dur', 0.10))}'")
    if (pid := picked(seg.fx, "k20")):
        # Lift the highlights, then spill them: a negative unsharp is the
        # cheapest glow there is, and it only ever touches what is already bright.
        win = _between(kt, kt + knob(pid, "dur", 0.30))
        v.append(f"curves=all='0/0 0.55/{knob(pid, 'lift', 0.68)} 1/1':enable='{win}'")
        v.append(f"unsharp=9:9:-1.4:enable='{win}'")
    if (pid := picked(seg.fx, "k18")):
        # lagfun keeps the brighter of this frame and a decayed last one, so
        # only movement against a dark ground trails -- muzzle flash and tracer,
        # not the wall behind them.
        v.append(f"lagfun=decay={knob(pid, 'decay', 0.88)}:"
                 f"enable='{_between(kt, kt + knob(pid, 'dur', 0.35))}'")
    angle = []
    if seg.vignette:
        angle.append("PI/10")
    if (pid := picked(seg.fx, "k15")):
        angle.append(f"{knob(pid, 'amt', 0.6)}*gte(t,{kt:.4f})"
                     f"*max(0,1-(t-{kt:.4f})/{knob(pid, 'fall', 0.4):.3f})")
    if (pid := picked(seg.hero_fx, "h03")):
        angle.append(f"{knob(pid, 'amt', 0.9)}*{_between(kt, kt + 0.8)}")
    if angle:
        expr = "+".join(angle)
        dyn = "t" in expr.replace("PI", "")
        v.append(f"vignette=angle='min(1.5,{expr})'" + (":eval=frame" if dyn else ""))
    if seg.caption:
        # Sized to the frame's WIDTH as well as its height: on a vertical
        # reel the slam's first frames drew "RIPLE KIL" -- 1.9x of a size
        # chosen from the 1920-pixel height is wider than 1080 pixels.
        fit = W * 0.9 / max(1, len(seg.caption) * 0.62)
        size = int(min(max(28, round(H * 0.075)), fit))
        # How far it slams in from is the slam family's own knob, so "gently"
        # and "hard" are different edits rather than three names for 1.9x.
        big = int(min(round(size * knob(picked(seg.hero_fx, "h05"), "scale", 1.9)), fit))
        v.append(f"drawtext={_font()}expansion=none:textfile={_path_arg(text_file(textdir, seg.caption))}:"
                 f"fontcolor=white:borderw=3:"
                 f"bordercolor=black@0.55:fontsize='if(lt(t-{kt:.4f},0.1),{big}-{(big - size) * 10}*(t-{kt:.4f}),{size})':"
                 f"x=(w-tw)/2:y=h*0.68:enable='{_between(kt, kt + 1.4)}'")
    v.append(f"format=yuv420p,trim=end_frame={total},setpts=PTS-STARTPTS")
    vchain = "[0:v]" + ",".join(v) + "[v]"

    # Game audio: the clip's own sound at real speed; silence where the
    # footage is slowed or sped (a stretched gunshot sounds broken, and the
    # music carries those moments in every reference edit).
    a_parts, labels = [], []
    real = [j for j, (_, _, r) in enumerate(seg.pieces) if abs(r - 1.0) < 1e-6] if seg.has_audio else []
    if len(real) > 1:
        a_parts.append("[0:a:0]asplit=" + str(len(real)) + "".join(f"[ga{j}]" for j in real))
    feed = {j: (f"[ga{j}]" if len(real) > 1 else "[0:a:0]") for j in real}
    src = 0.0
    for j, (a, b, r) in enumerate(seg.pieces):
        n = b - a
        s0, s1 = src, src + n * r
        src = s1
        lab = f"p{j}"
        if j in feed:
            a_parts.append(f"{feed[j]}atrim=start={max(0.0, s0 - lead):.5f}:end={max(0.0, s1 - lead):.5f},"
                           f"asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                           f"apad=whole_dur={n:.5f},atrim=0:{n:.5f}[{lab}]")
        else:
            a_parts.append(f"aevalsrc=0|0:s=48000:d={n:.5f},aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[{lab}]")
        labels.append(f"[{lab}]")
    achain = ";".join(a_parts) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[ac]"
    if seg.freeze > 0:
        achain += (f";[ac]asplit[aa][ab];[aa]atrim=0:{kt:.5f}[a1];"
                   f"aevalsrc=0|0:s=48000:d={seg.freeze:.5f},aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a2];"
                   f"[ab]atrim=start={kt:.5f},asetpts=PTS-STARTPTS[a3];[a1][a2][a3]concat=n=3:v=0:a=1[ad]")
        last = "[ad]"
    else:
        last = "[ac]"
    if seg.game_gate:
        # THE KILL IS WHAT YOU HEAR. Game sound under the whole reel -- steps,
        # reloads, voice lines -- kept the music ducked all the time and left
        # 1.1 LU of loudness range. Gated to the shots that land, the music is
        # clean between kills and each kill cuts through it (see rulebook).
        gates = [f"clip((t-{k - rulebook.KILL_SOUND_BEFORE:.4f})/0.03,0,1)*clip(({k + rulebook.KILL_SOUND_AFTER:.4f}-t)/0.08,0,1)"
                 for k in seg.kill_times]
        expr = gates[0]
        for gexp in gates[1:]:
            expr = f"max({expr},{gexp})"
        bed = rulebook.GAME_BED
        achain += f";{last}volume='{bed}+{1 - bed:.3f}*({expr})':eval=frame[ag]"
        last = "[ag]"
    achain += f";{last}apad=whole_dur={total_s:.5f},atrim=0:{total_s:.5f}[a]"

    enc = encoder_args if encoder_args is not None else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p"]
    return [ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-ss", f"{start:.4f}", "-t", f"{src_len + 0.5:.4f}", "-i", seg.clip,
            "-filter_complex", vchain + ";" + achain,
            "-map", "[v]", "-map", "[a]", "-r", str(F), *enc,
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-frames:v", str(total), str(out)]


def assemble_command(project: dict, derived: dict, segs: list[Segment], files: list[Path],
                     out: Path, ff: str = "ffmpeg", encoder_args=None,
                     textdir: Path | None = None, mark_at=None) -> list[str]:
    """ffmpeg argv that joins the shot renders into the finished reel.

    `mark_at` is (animation folder, resting still, x, y) for the AutoStream
    mark, or None when it cannot be drawn. See THE MARK below.
    """
    W, H, F = SIZES[project["format"]][0], SIZES[project["format"]][1], FPS
    L = derived["length"]
    Lf = round(L * F)
    n = len(segs)
    args = [ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    for p in files:
        args += ["-i", str(p)]
    song = project.get("song") or ""
    if song:
        args += ["-ss", f"{project['song_offset']:.4f}", "-t", f"{L + 1.0:.4f}", "-i", song]
    # THE INTRO CLIP IS NOT IN THIS PASS. It used to be one more input, laid
    # over the head of the reel for its own length -- which meant that whatever
    # the reel opened with played underneath it and was lost. On a reel that
    # opens on a kill, that is the kill. It is joined in front of the finished
    # reel instead, by StudioJob._prepend_intro, so the reel keeps every frame
    # it was cut to have and the intro plays before the first of them.
    #
    # THE MARK IS TWO MORE INPUTS, last of all, so the segment and song indices
    # below them do not move. The animated strip covers the first seconds and
    # the still covers the rest, each gated by `enable`, so nothing is decoded
    # that is not on screen.
    mark_i = n + (1 if song else 0)
    if mark_at:
        mfolder, mstill, _mx, _my = mark_at
        args += ["-framerate", f"{mark_mod.FPS:g}", "-i", str(Path(mfolder) / "f%04d.png")]
        args += ["-loop", "1", "-t", f"{L + 1.0:.4f}", "-i", str(mstill)]

    g = []
    for i in range(n):
        # fps FIRST: it resets the timebase, and xfade refuses two inputs on
        # different ones -- a concat's output and a raw segment otherwise are.
        g.append(f"[{i}:v]fps={F},settb=AVTB,setsar=1,format=yuv420p[s{i}]")
    starts = [round(r["start"] * F) for r in derived["shots"]]
    acc_label, acc = "s0", segs[0].frames
    for i in range(1, n):
        seg = segs[i]
        frames_i = seg.frames
        t = project["shots"][i]["transition"]
        T = segs[i - 1].tail + seg.head
        lab = f"j{i}"
        if t == "t01" or T <= 0:
            g.append(f"[{acc_label}][s{i}]concat=n=2:v=1:a=0,settb=AVTB[{lab}]")
            acc += frames_i
        else:
            off = (acc - T) / F
            g.append(f"[{acc_label}][s{i}]xfade=transition={_xfade_name(t)}:"
                     f"duration={T / F:.5f}:offset={off:.5f},settb=AVTB[{lab}]")
            acc += frames_i - T
        acc_label = lab

    post = []
    intro, outro = project["intro"], project["outro"]
    # AN INTRO AS LONG AS WHAT IT HAS TO COVER. Normally its own length: a
    # second of fade, a third of a second of flash, over an opener that reaches
    # its kill in two or three. But a LEAD-IN opener (see apply_marks) holds
    # for however long it takes the song to reach the first mark, and a
    # one-second fade over a nine-second hold leaves eight seconds in which
    # nothing has happened and the reel does not look started. So the effect is
    # stretched over the run-up instead -- each to the point where it stops
    # reading as an intro, which is why the caps differ: a fade from black can
    # take three seconds and still be a fade, a white flash that burns for
    # three is a fault.
    opener = (project["shots"] or [{}])[0]
    lead = float(opener.get("pre") or 0.0) if opener.get("lead_in") else 0.0

    def over(own: float, share: float, cap: float) -> float:
        return round(min(max(own, lead * share), cap), 3)

    if fam(intro) == "fade_in":
        post.append(f"fade=in:st=0:d={over(_fade_seconds(intro, 0.7), 0.6, 3.0)}"
                    f":color={_fade_colour(intro)}")
    elif intro == "i03":
        post.append(f"fade=in:st=0:d={over(1.0, 0.6, 3.0)}")
    elif intro == "i08":
        d = over(0.35, 0.25, 1.2)
        post.append(f"eq=brightness='max(0,0.85*(1-t/{d}))':eval=frame")
    elif intro == "i12":
        k1 = derived["kills"][0] if derived["kills"] else 0.0
        post.append(f"eq=saturation='if(lt(t,{k1:.4f}),0.15,1)':eval=frame")
        post.append(f"fade=in:st=0:d={over(0.6, 0.5, 2.5)}")
    end_fade = rulebook.ending_fade(project["beat"])
    if fam(outro) == "fade_out":
        d = _fade_seconds(outro, 0.7)
        post.append(f"fade=out:st={max(0.0, L - d):.4f}:d={d:.4f}:color={_fade_colour(outro)}")
    elif outro == "e01" or outro == "e03":
        post.append(f"fade=out:st={max(0.0, L - end_fade):.4f}:d={end_fade:.4f}")
    elif outro == "e05":
        post.append(f"fade=out:st={max(0.0, L - 0.35):.4f}:d=0.35:color=white")
    elif outro == "e02":
        post.append(f"hue=s='if(gt(t,{L - 1.0:.4f}),max(0,1-(t-{L - 1.0:.4f})/0.8),1)'")
    ov = project["overlays"]
    if (pid := picked(ov, "o04")):
        post.append(f"noise=alls={int(knob(pid, 'amt', 10.0))}:allf=t")
    if (pid := picked(ov, "o05")):
        # Every other line darkened by a tenth. Drawn from the frame's own
        # height rather than a fixed pitch, so 1080p and 1440p look alike and
        # neither moirés against the encoder.
        pitch = max(1, int(knob(pid, "pitch", 2.0) * max(1, round(H / 1080))))
        post.append(f"geq=lum='lum(X,Y)*(1-0.10*lt(mod(Y,{pitch * 2}),{pitch}))':"
                    f"cb='cb(X,Y)':cr='cr(X,Y)'")
    if (pid := picked(ov, "o08")):
        px = int(knob(pid, "px", 2.0))
        post.append(f"rgbashift=rh={px}:bh=-{px}")
    if (pid := picked(ov, "o01")) and project["format"] == "landscape":
        bar = round(H * knob(pid, "h", 0.125))
        post.append(f"drawbox=x=0:y=0:w=iw:h={bar}:color=black:t=fill,drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color=black:t=fill")
    font = _font()
    if "o02" in ov and derived["kills"]:
        ks = derived["kills"] + [L + 1]
        size = max(24, round(H * 0.05))
        for j in range(len(ks) - 1):
            post.append(f"drawtext={font}expansion=none:textfile={_path_arg(text_file(textdir, f'x{j + 1}'))}:"
                        f"fontsize={size}:fontcolor=white:borderw=2:"
                        f"bordercolor=black@0.5:x=w-tw-{round(W * 0.03)}:y={round(H * 0.04)}:"
                        f"enable='{_between(ks[j], ks[j + 1])}'")
    if "o07" in ov and project.get("handle"):
        size = max(18, round(H * 0.032))
        post.append(f"drawtext={font}expansion=none:textfile={_path_arg(text_file(textdir, project['handle']))}:"
                    f"fontsize={size}:fontcolor=white@0.7:"
                    f"x=w-tw-{round(W * 0.025)}:y=h-th-{round(H * 0.03)}")
    if "i04" in ov and song:
        from .reel import NOWPLAYING_FROM, NOWPLAYING_SECONDS, song_tags
        tags = song_tags(Path(song))
        line = f"{tags['artist']} - {tags['title']}" if tags["artist"] else tags["title"]
        size, pad = max(16, int(H * 0.026)), int(H * 0.030)
        a, b = NOWPLAYING_FROM, NOWPLAYING_FROM + NOWPLAYING_SECONDS
        alpha = (f"if(lt(t,{a}),0,if(lt(t,{a + 0.4:.2f}),(t-{a})/0.4,"
                 f"if(lt(t,{b - 0.6:.2f}),1,if(lt(t,{b}),({b}-t)/0.6,0))))")
        post.append(f"drawtext={font}expansion=none:textfile={_path_arg(text_file(textdir, line))}:"
                    f"fontcolor=white:fontsize={size}:x={pad}:y=h-{pad}-{size}:box=1:"
                    f"boxcolor=black@0.45:boxborderw=10:alpha='{alpha}'")
    if intro == "i05":
        b = over(1.2, 0.7, 4.0)
        chain_in = (f"[{acc_label}]split[bs][bb];[bb]gblur=sigma=18[bg];"
                    f"[bs][bg]blend=all_expr='A*min(1,T/{b})+B*(1-min(1,T/{b}))'[bl]")
        g.append(chain_in)
        acc_label = "bl"
    post.append(f"trim=end_frame={Lf},format=yuv420p")
    if mark_at:
        # Above everything the post chain drew: a mark under the film grain or
        # behind the cinematic bars is not a mark.
        _f, _s, mx, my = mark_at
        g.append(f"[{acc_label}]" + ",".join(post) + "[vpre]")
        g.append(f"[vpre][{mark_i}:v]overlay=x={mx}:y={my}:eof_action=pass:"
                 f"enable='lt(t,{mark_mod.FOLD_IN[1]:.2f})'[vmk]")
        g.append(f"[vmk][{mark_i + 1}:v]overlay=x={mx}:y={my}:shortest=0:"
                 f"enable='gte(t,{mark_mod.FOLD_IN[1]:.2f})'[v]")
    else:
        g.append(f"[{acc_label}]" + ",".join(post) + "[v]")

    # Audio: each shot's own sound where it plays, the song under it all.
    for i, seg in enumerate(segs):
        at = max(0, (starts[i] - seg.head)) / F
        g.append(f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                 f"adelay=delays={round(at * 1000)}:all=1[g{i}]")
    game = "".join(f"[g{i}]" for i in range(n))
    g.append(f"{game}amix=inputs={n}:normalize=0:duration=longest,volume={project['game_db']}dB,"
             f"apad=whole_dur={L:.4f},atrim=0:{L:.4f}[game]")
    if song:
        fades = []
        if intro in ("i03", "i05") or fam(intro) == "fade_in":
            fades.append("afade=t=in:st=0:d=1.0")
        if outro in ("e01", "e03", "e02") or fam(outro) == "fade_out":
            fades.append(f"afade=t=out:st={max(0.0, L - end_fade):.4f}:d={end_fade:.4f}")
        # A BREATH BEFORE THE BIG ONE: the music drops away for the half beat
        # before each hero kill and comes back on it.
        holes, hits = [], []
        half = project["beat"] / 2
        gated = project.get("duck", True) and project.get("kill_sound", True)
        for i, sh in enumerate(project["shots"]):
            k = derived["shots"][i]["kill_reel"]
            if sh.get("hero") and i > 0:
                holes.append(f"clip((t-{k - half:.4f})/0.04,0,1)*clip(({k:.4f}-t)/0.02,0,1)")
        if gated:
            for k in derived.get("kills") or []:
                # Before the kill, not on it: the kill sits on a beat, and ducking
                # the beat itself took its punch away (measured: kills came out
                # 2 dB quieter than the moment before them). The gunfire plays
                # into the gap and the beat lands with the kill.
                hits.append(f"clip((t-{k - rulebook.KILL_DUCK_SECONDS:.4f})/0.05,0,1)*clip(({k - 0.01:.4f}-t)/0.015,0,1)")

        def anyof(gs):
            e = gs[0]
            for x in gs[1:]:
                e = f"max({e},{x})"
            return e
        dip = ""
        if holes or hits:
            terms = []
            if hits:
                terms.append(f"{1 - rulebook.KILL_DUCK:.3f}*({anyof(hits)})")
            if holes:
                terms.append(f"{1 - rulebook.HERO_DIP:.3f}*({anyof(holes)})")
            dip = f",volume='max({rulebook.HERO_DIP},1-{'-'.join(terms)})':eval=frame"
        mchain = (f"[{n}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                  f"atrim=0:{L:.4f},asetpts=PTS-STARTPTS,volume={project['music_db']}dB" + dip
                  + ("," + ",".join(fades) if fades else "") + "[music]")
        g.append(mchain)
        if project.get("duck", True) and not project.get("kill_sound", True):
            g.append("[game]asplit[gmix][gkey];[music][gkey]sidechaincompress=threshold=0.16:ratio=5:"
                     "attack=4:release=220:level_sc=1[ducked];[ducked][gmix]amix=inputs=2:normalize=0:"
                     "duration=first[mixed]")
        else:
            g.append("[music][game]amix=inputs=2:normalize=0:duration=first[mixed]")
        last = "[mixed]"
    else:
        last = "[game]"
    # The intro's own sound travels with the intro, in the join that puts it in
    # front of this reel. Mixing it in here would have played it over the
    # reel's opening, which is the picture problem in the other track.
    g.append(f"{last}alimiter=limit=0.9:level=disabled,aresample=48000,"
             f"apad=whole_dur={L:.4f},atrim=0:{L:.4f}[a]")

    enc = encoder_args if encoder_args is not None else ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
    graph = ";".join(g)
    tail = ["-map", "[v]", "-map", "[a]", "-r", str(F), *enc,
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
            "-movflags", "+faststart", "-t", f"{L:.4f}", str(out)]

    # A LONG REEL WILL NOT FIT ON A WINDOWS COMMAND LINE. CreateProcess caps
    # the whole line at 32,767 characters, and the filter graph grows with the
    # shot count: measured on a real 50-shot reel, the graph alone was 28,394
    # characters and the command 33,144 -- 379 over, so it died with
    # "[WinError 206] The filename or extension is too long" AFTER all 50
    # shots had been encoded. MAX_SHOTS is 80, so the app was offering nearly
    # twice what it could deliver.
    #
    # ffmpeg will read the graph out of a file instead, which takes those
    # 28,394 characters off the line. Only when it is needed: the inline form
    # is what every normal reel uses and what is easiest to read in a log.
    if sum(len(a) + 3 for a in args + ["-filter_complex", graph] + tail) > CMDLINE_SAFE:
        from .tools import filter_script_flag

        script = text_file(textdir, graph)
        return args + [filter_script_flag(), str(script)] + tail
    return args + ["-filter_complex", graph] + tail


def intro_head_command(project: dict, head: Path, ff: str = "ffmpeg",
                       encoder_args=None) -> list[str]:
    """ffmpeg argv that renders the intro clip to the reel's own shape.

    The product is one short file matching the reel frame for frame -- size,
    rate, pixel format, one stereo track -- so that the two can be spliced
    without re-encoding the reel. Trimmed on the way in, so only the chosen
    part is ever decoded. -> [] when there is no intro to render.

    WHAT THE INTRO IS HEARD OVER. Its own sound when that was asked for and
    there is any. Otherwise THE SONG, taken from the seconds BEFORE the reel's
    own start -- so the reel still begins on song_offset, exactly where its beat
    grid was built, and the intro carries the run-up into it. An intro over
    silence followed by a reel that starts the song from nothing is the seam
    this removes: the song is already playing when the first kill lands.
    """
    ic = project.get("intro_clip") or None
    seconds = round(float(ic["end"]) - float(ic["start"]), 4) if ic else 0.0
    if not ic or seconds <= 0:
        return []
    W, H = SIZES[project["format"]]
    fit = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
           if ic.get("fit", "cover") == "cover" else
           f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
           f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black")
    keep = bool(ic.get("audio") and ic.get("has_audio"))
    song = "" if keep else str(project.get("song") or "")
    # How much song there is before the reel starts. A reel cut to the first
    # bars has less run-up than the intro is long; the head then opens on
    # silence and the song joins partway through it, still landing on
    # song_offset at the cut. Never negative, never more than the intro.
    offset = float(project.get("song_offset") or 0.0)
    lead = round(min(seconds, max(0.0, offset)), 4) if song else 0.0
    enc = encoder_args if encoder_args is not None else [
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
    args = [ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-ss", f"{float(ic['start']):.4f}", "-t", f"{seconds:.4f}", "-i", str(ic["path"])]
    afilter = None
    if keep:
        amap = "0:a:0"
    elif lead > 0:
        args += ["-ss", f"{offset - lead:.4f}", "-t", f"{lead:.4f}", "-i", song]
        amap = "[ia]"
        # adelay when the song is shorter than the intro: it has to END on the
        # cut, not start on it, or the run-up lands in the wrong place.
        pad = round(seconds - lead, 4)
        delay = f"adelay={int(pad * 1000)}:all=1," if pad > 0.001 else ""
        afilter = (f"[1:a]aformat=sample_fmts=fltp:sample_rates=48000:"
                   f"channel_layouts=stereo,asetpts=PTS-STARTPTS,{delay}"
                   f"volume={project.get('music_db', 0.0)}dB,"
                   f"apad=whole_dur={seconds:.4f},atrim=0:{seconds:.4f}[ia]")
    else:
        # The reel always carries exactly one stereo track, so a silent intro
        # has to carry one too: concat lines streams up by position and refuses
        # a pair that does not match.
        args += ["-f", "lavfi", "-t", f"{seconds:.4f}", "-i",
                 "anullsrc=channel_layout=stereo:sample_rate=48000"]
        amap = "1:a:0"
    if afilter:
        args += ["-filter_complex", afilter]
    return args + ["-map", "0:v:0", "-map", amap,
                   "-vf", f"fps={FPS},{fit},setsar=1,format=yuv420p", *enc,
                   "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
                   "-movflags", "+faststart", str(head)]


# ============================================================== the job

class Cancelled(RuntimeError):
    pass


_JOB_IDS = itertools.count(1)


class StudioJob:
    """One reel render: the shots that are not cached, then the join."""

    def __init__(self, project: dict, derived: dict, root: Path, out: Path, *,
                 shape_beats: list[float] | None = None):
        self.id = next(_JOB_IDS)
        self.project, self.derived, self.root, self.out = project, derived, root, out
        self.shape_beats = shape_beats
        self.state = "queued"
        self.step = "shots"
        self.done = 0
        self.total = 0
        self.message = ""
        self.error = ""
        self.started = time.time()
        self.finished = 0.0
        self.cached = 0
        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        with self._lock:
            pct = int(100 * self.done / self.total) if self.total else 0
            return {"id": self.id, "state": self.state, "step": self.step, "done": self.done,
                    "total": self.total,
                    "percent": max(0, min(100, pct)), "message": self.message, "error": self.error,
                    "output": str(self.out), "project": str(self.out.with_suffix(".reel.json")),
                    "elapsed": int((self.finished or time.time()) - self.started),
                    "cached": self.cached, "name": self.project.get("name", "")}

    def cancel(self) -> None:
        self._cancel.set()
        p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass

    def _set(self, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def _run_ff(self, argv: list[str], *, capture: bool = False) -> str:
        """Run ffmpeg where Cancel can reach it. -> its stderr when `capture`."""
        from .killfeed import _NO_WINDOW
        if self._cancel.is_set():
            raise Cancelled("cancelled")
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                creationflags=_NO_WINDOW)
        self._proc = proc
        # Cancel may have landed between the check above and the assignment.
        if self._cancel.is_set():
            proc.terminate()
        _, err = proc.communicate()
        code = proc.returncode
        self._proc = None
        if self._cancel.is_set():
            raise Cancelled("cancelled")
        text = (err or b"").decode("utf-8", "replace")
        if code != 0:
            raise RuntimeError(text[-1500:] or f"ffmpeg exited {code}")
        return text if capture else ""

    def _loudness(self, ff: str, path: Path, target: float = rulebook.LOUDNESS) -> None:
        """Bring the finished reel to `target` LUFS with a measured second pass.

        One pass of loudnorm guesses as it goes and measured 1.2 LU hot on the
        first reels made here; measuring the whole mix first and then applying
        it linearly lands on the target. Audio only -- the video is copied, so
        this costs seconds.
        """
        fixed = path.with_name(path.stem + ".loud.mp4")

        def measured(p: Path) -> tuple[float, float]:
            """(integrated LUFS, true peak dBTP) of a file's audio."""
            err = self._run_ff([ff, "-hide_banner", "-nostdin", "-i", str(p), "-vn", "-af",
                                "loudnorm=print_format=json", "-f", "null", "-"], capture=True)
            m = json.loads(err[err.rindex("{"): err.rindex("}") + 1])
            return float(m["input_i"]), float(m["input_tp"])
        try:
            # GAIN AND A LIMITER, NOT A NORMALISER. loudnorm reaching -10 LUFS
            # has to compress, and it compressed the kill accents flat again
            # (measured: kills 0.4 dB above the bars between them). A fixed gain
            # into a peak limiter keeps them, and a second measurement corrects
            # for what the limiter took off.
            #
            # AND THE PEAK IS MEASURED TOO. The limiter works on samples; the
            # encoded file's true peak can still overshoot (one reel measured
            # +2.7 dBTP), so the ceiling comes down by the overshoot and the
            # pass runs again.
            now, peak = measured(path)
            if abs(target - now) < 0.3 and peak <= rulebook.TRUE_PEAK_MAX:
                return
            gain, limit = target - now, rulebook.PEAK_LIMIT
            for _ in range(6):
                af = f"volume={gain:.2f}dB,alimiter=limit={limit:.4f}:attack=3:release=60:level=disabled"
                self._run_ff([ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(path),
                              "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-af", af, "-ar", "48000",
                              "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(fixed)])
                got, peak = measured(fixed)
                level_ok, peak_ok = abs(got - target) < 0.4, peak <= rulebook.TRUE_PEAK_MAX
                if level_ok and peak_ok:
                    break
                # Both corrections in one pass: a lower ceiling costs loudness,
                # which the gain makes back on the next.
                if not peak_ok:
                    limit = max(0.3, limit * 10 ** ((rulebook.TRUE_PEAK_MAX - 0.3 - peak) / 20))
                if not level_ok:
                    gain += target - got
            if fixed.is_file():
                fixed.replace(path)
        except Cancelled:
            raise
        except Exception as e:                              # noqa: BLE001
            # Loudness is a finish, not the reel: keep the render and say why.
            log.info("studio loudness pass skipped: %s", e)
        finally:
            _unlink(fixed)

    def _prepend_intro(self, ff: str, path: Path) -> None:
        """Join the intro clip in front of the finished reel.

        The intro used to be laid OVER the reel's first seconds. That was meant
        for a reel whose song takes a long time to arrive, where the opening is
        a single held shot and there is nothing to cover -- but on a reel that
        opens on a kill it covered the kill, and those seconds were gone.

        Joining costs one encode of the intro alone. The reel itself is copied,
        so not a frame of what it was cut to have moves, softens or re-encodes.
        """
        from .tools import video_codec_args

        if not self.project.get("intro_clip"):
            return
        head = path.with_name(path.stem + ".intro.mp4")
        listing = path.with_name(path.stem + ".join.txt")
        joined = path.with_name(path.stem + ".joined.mp4")
        args = intro_head_command(self.project, head, ff, video_codec_args("auto", cq=19))
        if not args:
            return
        try:
            self._run_ff(args)
            listing.write_text(f"file '{head.as_posix()}'\nfile '{path.as_posix()}'\n",
                               encoding="utf-8")
            base = [ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "concat", "-safe", "0", "-i", str(listing)]
            try:
                # Stream copy: the intro was just written with the same encoder
                # settings as the reel, so the two should splice untouched.
                self._run_ff([*base, "-c", "copy", "-movflags", "+faststart", str(joined)])
            except Cancelled:
                raise
            except RuntimeError as e:
                # They did not splice -- a hardware encoder that varies its
                # headers, most likely. Re-encoding the join is slower, but an
                # intro that was asked for is not optional.
                log.info("studio: the intro would not splice (%s); joining the long way", e)
                self._run_ff([*base, *video_codec_args("auto", cq=19),
                              "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
                              "-movflags", "+faststart", str(joined)])
            joined.replace(path)
        finally:
            _unlink(head)
            _unlink(listing)
            _unlink(joined)

    def run(self) -> None:
        from .tools import binary, media_info, video_codec_args
        self._set(state="running")
        try:
            ff = binary("ffmpeg")
            cache = self.root / CACHE_DIR / "segments"
            cache.mkdir(parents=True, exist_ok=True)
            textdir = self.root / CACHE_DIR / "text"
            _prune(cache)

            def audio_of(p: str) -> bool:
                try:
                    return media_info(p).get("audio_tracks", 0) > 0
                except Exception:                           # noqa: BLE001
                    return True
            segs = segments(self.project, self.derived, has_audio=audio_of,
                            song_beats=self.derived.get("beats"))
            files = [cache / f"{s.key()}.mp4" for s in segs]
            todo = [(s, f) for s, f in zip(segs, files) if not f.is_file()]
            self._set(total=len(todo) + 2, cached=len(segs) - len(todo),
                      message=f"Rendering {len(todo)} of {len(segs)} shots")
            enc_seg = video_codec_args("auto", cq=16)
            for j, (s, f) in enumerate(todo):
                self._set(step="shots", message=f"Shot {s.index + 1} of {len(segs)}")
                tmp = f.with_suffix(".part.mp4")
                try:
                    self._run_ff(segment_command(s, tmp, ff, enc_seg, textdir))
                except Cancelled:
                    # A subclass of RuntimeError: re-wrapped below, a Cancel
                    # the user pressed was reported as a failed render.
                    raise
                except RuntimeError as e:
                    raise RuntimeError(f"Shot {s.index + 1} ({Path(s.clip).name}): {e}") from e
                finally:
                    if not tmp.is_file() or self._cancel.is_set():
                        _unlink(tmp)
                tmp.replace(f)
                self._set(done=j + 1)
            self._set(step="join", message="Joining the shots and mixing the sound")
            self.out.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.out.with_name(self.out.stem + ".part.mp4")
            try:
                try:
                    # EVERY REEL CARRIES THE MARK. Drawn once per reel height
                    # and cached beside the examples, so this is a directory
                    # listing on every render after the first. If it cannot be
                    # drawn -- no bold font on the machine, no Pillow -- the
                    # reel is rendered without it rather than failing: a
                    # watermark is not worth losing someone's reel over.
                    try:
                        mw, mh = SIZES[self.project["format"]]
                        mark_at = mark_mod.build(self.root, mw, mh)
                    except Exception as e:
                        log.warning("studio: the mark could not be drawn (%s)", e)
                        mark_at = None
                    self._run_ff(assemble_command(self.project, self.derived, segs, files, tmp, ff,
                                                  video_codec_args("auto", cq=19), textdir,
                                                  mark_at=mark_at))
                except Cancelled:
                    raise
                except RuntimeError as e:
                    raise RuntimeError(f"Joining the shots: {e}") from e
                # BEFORE the loudness pass, so the intro is measured with the
                # reel rather than left sitting at its own level in front of it.
                if self.project.get("intro_clip"):
                    self._set(step="join", message="Putting the intro in front")
                    self._prepend_intro(ff, tmp)
                self._set(step="sound", message="Matching loudness")
                self._loudness(ff, tmp)
                tmp.replace(self.out)
            finally:
                # A cancelled or failed join leaves a headerless mp4 that would
                # otherwise sit in the reels folder looking like a reel.
                _unlink(tmp)
            meta = dict(self.project)
            meta["output"] = str(self.out)
            # The intro is in front of the reel, not over it, so the file on
            # disk is longer than the reel the timeline describes. `length` is
            # what was rendered; `reel` stays the cut the beat grid was built
            # from, which is what every time in the project is measured against.
            ic = self.project.get("intro_clip") or None
            intro = round(float(ic["end"]) - float(ic["start"]), 3) if ic else 0.0
            meta["render"] = {"length": round(self.derived["length"] + intro, 3),
                              "reel": self.derived["length"], "intro": intro,
                              "when": int(time.time()),
                              "shots": len(segs), "cached": len(segs) - len(todo)}
            self.out.with_suffix(".reel.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
            self._set(state="done", step="done", done=self.total, message="Reel ready",
                      finished=time.time())
        except Cancelled:
            self._set(state="cancelled", message="Cancelled", finished=time.time())
        except Exception as e:                              # noqa: BLE001
            log.warning("studio render failed: %s", e)
            self._set(state="failed", error=str(e)[-800:], message="The render failed",
                      finished=time.time())


def _unlink(p: Path) -> None:
    try:
        Path(p).unlink()
    except OSError:
        pass


def _prune(cache: Path, keep: int = 400, days: float = 21.0) -> None:
    """Keep the shot cache from growing forever: oldest first, by age then count."""
    try:
        files = sorted(cache.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    now = time.time()
    for i, p in enumerate(files):
        try:
            old = now - p.stat().st_mtime > days * 86400
            if old or i < len(files) - keep or p.name.endswith(".part.mp4"):
                p.unlink()
        except OSError:
            pass


class Runner:
    """At most one reel render at a time: they saturate the encoder."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.job: StudioJob | None = None
        # A render is prepared before it is started, and the page offers its
        # Cancel button for that whole gap. A cancel landing in the gap used to
        # find no job, return False, and the render began anyway a moment
        # later. A claim is taken before the preparation so that cancel has
        # something to void.
        self._claims = 0
        self._preparing: set[int] = set()
        self._voided: set[int] = set()

    def busy(self) -> bool:
        with self._lock:
            return self.job is not None and self.job.state in ("queued", "running")

    def claim(self) -> int:
        """Take a ticket before preparing a render, to hand to `start`."""
        with self._lock:
            self._claims += 1
            self._preparing.add(self._claims)
            return self._claims

    def release(self, claim: int) -> None:
        """Drop a claim whose render never got as far as a job."""
        with self._lock:
            self._preparing.discard(claim)
            self._voided.discard(claim)

    def start(self, job: StudioJob, claim: int = 0) -> str:
        """-> "" once the job is running, else why it is not."""
        with self._lock:
            if claim:
                self._preparing.discard(claim)
                if claim in self._voided:
                    self._voided.discard(claim)
                    return "The render was cancelled before it started."
            if self.job is not None and self.job.state in ("queued", "running"):
                return "A reel is already rendering."
            self.job = job
        threading.Thread(target=job.run, name="autostream-studio", daemon=True).start()
        return ""

    def status(self) -> dict | None:
        with self._lock:
            job = self.job
        return job.snapshot() if job else None

    def cancel(self) -> bool:
        with self._lock:
            job = self.job
            if job is None or job.state not in ("queued", "running"):
                # Nothing is running, but a render may be between its claim and
                # its start. Voiding the outstanding claims stops it there.
                if not self._preparing:
                    return False
                self._voided |= self._preparing
                self._preparing.clear()
                return True
        job.cancel()
        return True


_RUNNER: Runner | None = None
_RUNNER_LOCK = threading.Lock()


def runner() -> Runner:
    """The one Runner. Built under a lock: two requests arriving together on a
    fresh daemon would otherwise each get their own, and two renders."""
    global _RUNNER
    if _RUNNER is None:
        with _RUNNER_LOCK:
            if _RUNNER is None:
                _RUNNER = Runner()
    return _RUNNER


def thumb(root: Path, clip: Path, at: float = -1.0, width: int = 360) -> Path:
    """A cached still of a clip for the library grid. Raises on a bad path."""
    root_r = root.resolve()
    if not clip.resolve().is_relative_to(root_r) or not clip.is_file():
        raise FileNotFoundError("That clip is not in the clips folder.")
    st = clip.stat()
    key = hashlib.sha1(f"{clip}|{st.st_mtime}|{st.st_size}|{at}|{width}".encode()).hexdigest()[:20]
    out = root / CACHE_DIR / "thumbs" / f"{key}.jpg"
    if out.is_file():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    from .killfeed import _NO_WINDOW
    from .tools import binary
    t = at if at >= 0 else 0.0
    # One temp per request: the grid asks for the same still from two tabs at
    # once, and a shared temp promoted half-written is a broken tile for ever.
    tmp = out.with_name(f"{out.stem}.{threading.get_ident()}.{time.monotonic_ns()}.part.jpg")
    subprocess.run([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-ss", f"{t:.3f}", "-i", str(clip), "-frames:v", "1",
                    "-vf", f"scale={width}:-2", "-q:v", "5", str(tmp)],
                   capture_output=True, timeout=30, creationflags=_NO_WINDOW)
    if not tmp.is_file():
        raise RuntimeError("Could not read a frame from that clip.")
    try:
        tmp.replace(out)
    except OSError:
        _unlink(tmp)
        if not out.is_file():
            raise
    return out
