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

import copy
import hashlib
import itertools
import json
import logging
import math
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
import zlib
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import (facecam, hits as hits_mod, lyrics as lyrics_mod, mark as mark_mod,
               fx_schedule, parts as parts_mod, reelcheck, retime, rulebook, studio_refs, valorant_match)

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
# How a 16:9 game fills a 9:16 reel: the middle cropped to fill it, all of it over a
# blurred copy, or the middle three quarters of it over the same -- a third taller.
VFITS = ("zoom", "fit", "near")
NEAR_KEEP = 0.75
# Windows caps a whole command line at 32,767 characters. Kept well under it:
# the paths in the line are the user's own and can be far longer here than on
# the machine this was measured on.
CMDLINE_SAFE = 24_000


# ============================================================== the library

_FOLDER_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})_(.+?)(?:_(\d+))?$")


def _folder_label(name: str) -> str:
    """"2026-09-14_0045_VALORANT_2" -> "14 Sep 2026, 00:45 · run 2"."""
    if name.startswith("import-"):
        # import-2026-09-26_0801-my-ace -> "Added · my ace"
        rest = name[len("import-"):]
        rest = rest.split("-", 3)[-1] if rest[:4].isdigit() else rest
        rest = rest.split("-", 1)[1] if "_" in rest.split("-", 1)[0] else rest
        return "Added · " + rest.replace("-", " ")
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


def _match_groups(sess: dict, clips: list[dict]) -> list[dict]:
    """The matches a run's clips were cut from, in the order they were played.

    BOTH HALVES OF THIS ARE ALREADY ON DISK and neither costs a frame of
    video. The run's own session.json says where each match starts in the
    recording -- `demo.matches`, written when the detected kills were aligned
    against Riot's record -- and the record the Clips page already fetched has
    the map, the mode and the score. Checked against each other on the 10 Oct
    run before this was built: the four spans take 10 + 4 + 15 + 9 of its 38
    clips, and the kills in each group are 18 / 23 / 24 / 27, exactly what
    Riot says the player got on Lotus, Drift, Haven and Piazza.

    Each clip inside a match is given that group's index in `match`. A run with
    no records -- CS2, Delta Force, anything imported -- gets no groups, and
    the page shows the one grid it always did.
    """
    demo = sess.get("demo")
    if not isinstance(demo, dict):
        return []
    rows = demo.get("matches")
    if not isinstance(rows, list):
        # One match aligned, before runs recorded a list of them.
        rows = [demo] if demo.get("match") else []
    spans = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("match"):
            continue
        try:
            spans.append((float(row.get("offset") or 0.0), str(row["match"])))
        except (TypeError, ValueError):
            continue
    spans.sort()
    if not spans:
        return []
    out = []
    for i, (at, mid) in enumerate(spans):
        end = spans[i + 1][0] if i + 1 < len(spans) else float("inf")
        inside = [c for c in clips if at <= c["start"] < end]
        if not inside:
            continue
        match = valorant_match.one(mid)
        if match is None:
            # The record has been deleted since the clips were cut. The span is
            # still real, so the clips stay grouped -- without a map name.
            row = {"id": mid}
        else:
            row = valorant_match.summary(match)
        for c in inside:
            c["match"] = len(out)
        # `kills` and `seconds` on a summary are Riot's -- the player's kills
        # in the match and how long it ran. What the clips add up to is its
        # own pair of keys, so neither can be mistaken for the other.
        out.append({**row, "at": round(at, 2), "clips": len(inside),
                    "clip_kills": sum(c["kill_count"] for c in inside),
                    "clip_seconds": round(sum(c["duration"] for c in inside), 1)})
    return out


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
        # Whether each kill was a headshot, where it was read (Valorant): True,
        # False, or absent when it was not. Looked up by time below.
        hs_at = {round(float(k["time"]), 3): k["hs"] for k in rows_k if isinstance(k.get("hs"), bool)}
        # Riot's record, not a screen reading: the Studio must not move these.
        recorded = sorted(float(k["time"]) for k in rows_k if k.get("record"))
        # Kills the clip job already put on the game's emblem (jobs._confirm_emblems).
        on_emblem = {round(float(k["time"]), 3) for k in rows_k if k.get("emblem")}
        try:
            pre = float(((sess.get("options") or {}).get("pre_roll")) or 3.5)
        except (TypeError, ValueError):
            pre = 3.5
        clips = []
        for c in rows:
            if not isinstance(c, dict):
                continue
            # Match videos are finished long-form videos -- a ten-minute
            # summary is not a shot for a thirty-second reel -- and listing
            # them put two of them among the clips with a made-up kill each.
            if c.get("kind") in ("summary", "highlight"):
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
            inside = [k for k in kills if start - 0.05 <= k <= end + 0.05]
            offs = [round(k - start, 3) for k in inside]
            offs = [min(max(0.0, o), dur) for o in offs]
            hs = [hs_at.get(round(k, 3)) for k in inside]
            from_record = bool(offs) and len(offs) == sum(
                1 for k in recorded if start - 0.05 <= k <= end + 0.05)
            # A CLIP THE MANIFEST SAYS HAS NO KILLS HAS NONE. The guess below
            # used to give it one, so a round cut for a team label alone showed
            # as "1 kill", added one to its match's total (26 kills read as 34
            # on a Corrode with eight such rounds), and gave a song edit a kill
            # to land a drop on where nobody died.
            no_kills = c.get("kills") == 0
            if not offs and not no_kills:
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
                "kill_count": 0 if no_kills else int(c.get("kills") or len(offs)),
                # Per kill, beside `kills`: True a headshot, False not, None unread.
                **({"hs": hs} if any(v is not None for v in hs) else {}),
                "caption": str(c.get("caption") or ""),
                "labels": [str(x) for x in (c.get("labels") or c.get("tags") or [])],
                "at": str(c.get("at") or ""),
                "rank": int(c.get("rank") or 0),
                "game": game,
                "round": c.get("round"),
                # Where the clip starts in its recording: what lines a facecam
                # attached to the whole session up with this one clip.
                "start": round(start, 3),
                **({"recorded": True} if from_record else {}),
                # EVERY KILL ALREADY ON ITS EMBLEM: the job checked them against the
                # whole recording, so the plan need not decode the clip to check again.
                **({"emblems": True} if inside and not from_record
                   and all(round(k, 3) in on_emblem for k in inside) else {}),
                # A file the player added (clips/uploads.py), and whether its
                # kills have been marked yet -- until they are, the one "kill"
                # above is only the clip's first frame.
                **({"imported": True, "unmarked": not rows_k} if sess.get("imported") else {}),
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
                             "matches": _match_groups(sess, clips),
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
        m = meta or {}
        shots = m.get("shots") or []
        render = m.get("render") or {}
        # THE POSTER IS THE FIRST KILL, not frame zero: frame zero of a reel is
        # a fade from black or an intro card, and eighty of those in a grid
        # are eighty black rectangles.
        try:
            poster = float(render.get("intro") or 0.0) + float(shots[0].get("pre") or 0.0) if shots else 1.0
        except (TypeError, ValueError, AttributeError):
            poster = 1.0
        out.append({"name": m.get("name") or mp4.stem, "path": str(mp4),
                    "project": str(proj) if meta else "", "when": when, "size": size,
                    "shots": len(shots),
                    "length": render.get("length"),
                    "style": m.get("style", ""),
                    "format": m.get("format") if m.get("format") in SIZES else "",
                    "song": Path(str(m.get("song") or "")).stem if m.get("song") else "",
                    "lyrics": ((m.get("lyrics") or {}).get("look") or "") if isinstance(m.get("lyrics"), dict) else "",
                    "poster": round(max(0.0, poster), 2),
                    "checks": [c for c in (m.get("checks") or []) if isinstance(c, dict)]})
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
    Part("g13", "grade", "Hard monochrome",
         "Black and white with almost no middle: an S-curve steep enough that "
         "shadows go to black and highlights run to white."),

    # The drawer needs its empty card too: a template picks one part from
    # every drawer, and most reels carry no overlay at all.
    Part("o00", "overlay", "No overlay", "Nothing over the picture."),
    Part("o01", "overlay", "Cinematic bars", "Black bars top and bottom (landscape only)."),
    Part("o02", "overlay", "Kill counter", "A running count ticks up with each kill."),
    Part("o04", "overlay", "Film grain", "Fine moving grain over the whole reel."),
    Part("o05", "overlay", "Scanlines", "Fine horizontal lines, like an old monitor. "
         "Costs about a second of render for every second of reel."),
    Part("o08", "overlay", "Chromatic edges", "A constant hair of colour fringing at the edges."),
    Part("o09", "overlay", "Beat flip",
         "The picture snaps to negative on every beat, and harder on the bar. "
         "Needs a song: it keys off the beat grid, not off the kills.",
         knobs=(("beat", 1.0), ("kick", 0.029))),
    # BAR LINES ONLY, AND WHY IT IS ITS OWN PART. Over flat letterbox bands a
    # whole-frame invert twice a second is a full-screen strobe -- 64 of them
    # in 36 seconds -- which is punishing to watch and a photosensitivity
    # concern. On bar lines it is 18, which still reads. Offered as a choice
    # rather than inferred from the framing, because the two are otherwise
    # independent and a control that changes itself is a control nobody trusts.
    Part("o10", "overlay", "Beat flip (bars only)",
         "The picture snaps to negative once a bar instead of every beat. "
         "Gentler, and what a letterboxed reel wants.",
         base="o09", knobs=(("beat", 0.0), ("kick", 0.029))),
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
GROUPS = parts_mod.groups(PARTS)
GROUP_SIZE: dict[tuple[str, str], int] = {}
for _p in PARTS:
    GROUP_SIZE[GROUPS[_p.id][0], _p.kind] = GROUP_SIZE.get((GROUPS[_p.id][0], _p.kind), 0) + 1


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


def _picked(value, kind: str) -> list[str]:
    """The ids a template names for one drawer, in order, unknown ones dropped.

    A string is one pick. A LIST is a set to draw from, and an id listed twice is drawn about
    twice as often -- which is the weight the Make page shows as a number beside it.
    """
    raw = value if isinstance(value, (list, tuple)) else [value]
    known = set(ids_of(kind))
    return [str(x).strip() for x in raw if str(x or "").strip() in known][:12]


def templated(style: "Style", picks: dict, exact: bool = False) -> "Style":
    """`style` with the picks a template makes. Unknown ids are ignored.

    `exact`: a single pick is the ONLY one, not the first of the style's own pool -- what a
    fast-cut reel wants, where "one kill effect" has to mean one.
    """
    swap: dict = {}
    for kind in DRAWERS:
        chosen = _picked((picks or {}).get(kind), kind)
        if not chosen:
            continue
        pick = chosen[0]
        many = len(chosen) > 1
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
            swap["transition_pool"] = (tuple(chosen) if (many or exact)
                                       else _leads(pick, style.transition_pool))
        elif kind == "kill":
            swap["kill"] = (pick,)
            swap["kill_pool"] = tuple(chosen) if (many or exact) else _leads(pick, style.kill_pool)
        elif kind == "hero":
            swap["hero"] = (pick,)
            swap["hero_pool"] = tuple(chosen) if (many or exact) else _leads(pick, style.hero_pool)
        elif kind == "camera":
            swap["camera"] = pick
            swap["camera_pool"] = tuple(chosen)
        elif kind == "speed":
            swap["speed"] = pick
            swap["speed_pool"] = tuple(chosen)
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
    # HARD MONOCHROME, AND NOT g07. g07 desaturates and leaves a normal tone
    # curve, which lands around 30-35% midtones with no crush; this is a steep
    # S whose midsection slope is about 1.97, so almost nothing survives in the
    # middle. The numbers are MEASURED against an anime edit rather than
    # chosen -- see docs/STYLE-FAST-PACED-HEADSHOT.md section 6, which also
    # carries the acceptance ranges this was tuned to. g07 is left alone
    # because existing projects reference it.
    #
    # The gamma of 1.005 the reference chain carries has no slot in this tuple
    # and is within a rounding error of 1.0, so it is dropped rather than
    # widening every row for it.
    # THE WHOLE CHAIN IS THE STATIC STRING, and the tuple's own numbers are
    # left neutral, because the ORDER is the grade. Measured over six samples
    # of a real recording: desaturate, then curve, then contrast lands black at
    # 28.9% and white at 9.8%; doing contrast first, which is what the tuple's
    # numbers would mean, gives 21.4% and 8.6% -- a different look, not a
    # rounding difference.
    #
    # And it is `hue=s=0`, not the tuple's saturation. Measured on the same
    # samples: raw footage is 0.378 mean saturation, `eq=saturation=0` leaves
    # 0.045 and `hue=s=0` leaves 0.000. (g07 "Monochrome" is built on the
    # former and is therefore not quite monochrome. Left alone on purpose --
    # existing projects reference it.)
    "g13": (0.0, 1.0, 0.0,
            "hue=s=0,"
            "curves=all='0/0.0155 0.200/0.0965 0.475/0.5635 0.690/0.988 1/1',"
            "eq=contrast=1.265:brightness=0.0195,"
            "unsharp=3:3:0.55:3:3:0.0"),
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
    # AT MOST THIS MANY SHOTS FROM ANY ONE CLIP; 0 is no limit, which is the
    # default because a reel built from four clips genuinely needs more than
    # three from each and capping that would leave it short of its own length.
    # Variety in a montage is the backdrop changing, so a style that can
    # afford to be picky says so. See rulebook.cap_per_clip.
    max_per_clip: int = 0
    # WHERE THIS STYLE'S NUMBERS CAME FROM, when they did not come from `refs`.
    # Every other style is measured against three or more public reel ids, and
    # a test enforces that so a style cannot be invented by taste. One is
    # measured instead against a reel cut by hand outside the app, which is a
    # private file with no id -- so it names the document that holds the
    # measurements. Empty means `refs` is the provenance, which is the usual
    # case; it is never both and never neither.
    provenance: str = ""
    # A STYLE WHOSE CUTS ARE FAST ENOUGH THAT VARIETY STOPS HELPING. On a high-BPM
    # song at a cut every second or so, a different transition and a different kill
    # effect on every shot reads as noise, and a speed ramp around a kill makes its
    # hit arrive late. Such a style keeps ONE transition, ONE kill effect and real
    # speed -- see fast_rules -- unless the player chooses otherwise on the Make
    # page, which always wins.
    fast_cuts: bool = False


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
          hero_pool=("h01", "h02", "h03"), camera_pool=("c00", "c00", "c01", "c04", "c05"),
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
          hero_pool=("h02", "h01", "h03"), camera_pool=("c00", "c00", "c04", "c08"),
          speed_pool=("s04", "s04", "s02", "s03"), energy=0.75),
    Style("drop", "Build and drop",
          "Your best clutch plays as one take through the build and its last kill lands on the "
          "drop; then quick kills on the drums. Needs a song with a clear drop.",
          ("FEKdk-cPVmg", "nkAEXZE76II", "66zl0-VoWbg"),
          intro="i03", outro="e01", cuts=("t01",), kill=("k01",), hero=("h01",),
          speed="s00", hero_speed="s02", camera="c00", grade="g01", vignette=True, drop=True,
          kill_pool=("k01", "k01", "k03", "k15", "k02", "k07", "k20"),
          transition_pool=("t01", "t01", "t05", "t04", "t01", "t06", "t14"),
          hero_pool=("h01", "h02"), camera_pool=("c00", "c01", "c00", "c05"),
          speed_pool=("s00", "s00", "s02"), energy=0.35),
    # FAST-PACED HEADSHOT. Reverse-engineered from an anime edit, cut by hand
    # outside the app and measured until it matched; docs/STYLE-FAST-PACED-
    # HEADSHOT.md is the whole specification and every number in it came off
    # that reel.
    #
    # energy=0.0 AND SINGLE-ENTRY POOLS ARE THE POINT, not an oversight. This
    # style's effects do not come from the parts bin at all -- they come from
    # the beat engine, which keys off the song's grid rather than off each
    # kill. Leaving the pools rich would stack a per-kill effect on top of a
    # per-beat one and muddy both. ON THE BAR, NOT EVERY BEAT (o10): reviewed
    # with the kills on the beat, a whole-frame negative on every beat "competes
    # with the kill impact and rapidly becomes fatiguing"; and the ending fades
    # to black -- burnt out to white, the last frame read as the reel breaking off.
    Style("fasthead", "Fast-paced headshot",
          "Headshots only, in hard black and white, snapping to negative on the bar. "
          "Cuts at one or two beats and a real multi-kill to close. Needs a song.",
          (),                       # the reference is a private file, not a public id
          intro="i08", outro="e01", cuts=("t01",), kill=("k01snap",), hero=("h01",),
          speed="s00", hero_speed="s00", camera="c00", grade="g13", vignette=True,
          overlays=("o10",), pre_share=0.62,
          kill_pool=("k01snap",), transition_pool=("t01",), hero_pool=("h01",),
          camera_pool=("c00",), speed_pool=("s00",), energy=0.0,
          max_per_clip=rulebook.CLIP_SHOTS_CAP,
          provenance="docs/STYLE-FAST-PACED-HEADSHOT.md", fast_cuts=True),
    Style("hype", "Hype",
          "Fast and loud like the busiest montages: a cut every couple of beats, shake on every "
          "kill, crunchy colour and a kill counter.",
          ("wlNmShwGaJY", "0OvnyxlKLeQ", "FEKdk-cPVmg", "66zl0-VoWbg"),
          intro="i08", outro="e05", cuts=("t01", "t01", "t05"), kill=("k01", "k02"),
          hero=("h01",), speed="s00", hero_speed="s02", camera="c04", grade="g05",
          vignette=True, overlays=("o02",),
          kill_pool=("k01", "k02", "k11", "k06", "k08", "k16", "k12", "k03", "k19", "k22", "k18"),
          transition_pool=("t01", "t05", "t01", "t06", "t02", "t12", "t13"),
          hero_pool=("h01", "h02", "h03"), camera_pool=("c04", "c00", "c04", "c03", "c07"),
          speed_pool=("s00", "s00", "s02", "s03"), energy=0.7, fast_cuts=True),
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
          hero=("h01",), speed="s04", hero_speed="s04", camera="c04hard", grade="g05",
          vignette=True, overlays=("o08",), pre_share=0.4,
          kill_pool=("k01snap", "k03wide", "k02hard", "k19hard", "k06wide", "k16hard",
                     "k21hard", "k12flash", "k22hard", "k18short"),
          transition_pool=("t02", "t06", "t13", "t12", "t05", "t01"),
          hero_pool=("h01", "h02", "h03"),
          camera_pool=("c04hard", "c04slam", "c00", "c06far"),
          speed_pool=("s04", "s04", "s03", "s02"), energy=0.9, fast_cuts=True),
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
        # Each part says which effect it is a version of, and whether it is the one a
        # list shows for that effect -- see parts.groups.
        "parts": [dict(p.__dict__, group=GROUPS[p.id][0], lead=GROUPS[p.id][1] == p.id,
                       versions=GROUP_SIZE[GROUPS[p.id][0], p.kind],
                       group_label=parts_mod.GROUP_LABEL.get(GROUPS[p.id][0], ""))
                  for p in PARTS],
        "favourite_parts": favourite_parts(),
        "kinds": list(KINDS), "drawers": list(DRAWERS),
        "styles": [{"key": s.key, "label": s.label, "blurb": s.blurb,
                    "measured": studio_refs.summary(s.refs),
                    "provenance": s.provenance, "fast_cuts": s.fast_cuts, "drop": bool(s.drop),
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
        "lyrics": lyrics_mod.catalog(),
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
    # Every drop in the song, not only the biggest: a reel plays a stretch of it, and
    # the drop that matters is the one INSIDE that stretch. See drop_in().
    drops: list[float] = field(default_factory=list)
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
                   drops=list(getattr(shape, "drops", None) or []),
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
           stretch=None, own: float = 0.0) -> list[tuple[float, float, float]]:
    """Output-time pieces of one shot: (start, end, playback rate), covering [0, dur].

    `pre` is where the kill falls in the shot's output time. Every preset keeps
    the kill inside a slow piece or at real speed, so it is still on screen
    when it lands on its beat.

    `own` is how many source seconds after that kill the shot's OWN later
    kills need (see _own_after). A ramp that rushes away from the kill waits
    until they have played at real speed. Measured on Aftrhrs: the climax's
    quadra was 17.6 s and 18.433 s into its clip, s04 rushed out at 2.2x from
    0.45 s after the first, and the fourth kill went by in a third of a second.

    `stretch` is (rate, real, hold): the run-up slowed to `rate` up to the
    last `real` seconds before the kill, which play as recorded, after the
    opening frame is held for `hold` seconds -- see stretch_to(). It is how a
    clip with three seconds of footage fills the ten seconds before its mark
    while its kill still lands exactly on it.
    """
    k = max(0.0, min(dur, pre))
    own = max(0.0, float(own or 0.0))
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
        # 0.45 s of source has played by k + 0.8 (0.15 slowed, 0.3 real).
        out_at = k + 0.8 + max(0.0, own - 0.45)
        raw = [(0.0, k - 0.15, 1.0), (k - 0.15, k + 0.5, 0.3), (k + 0.5, out_at, 1.0),
               (out_at, dur, 2.2)]
    elif speed == "s04":
        # 0.135 s of source has played by k + 0.45 (0.45 s at 0.3).
        out_at = k + 0.45 + max(0.0, own - 0.135)
        raw = [(0.0, k - 0.3, 2.2), (k - 0.3, k + 0.45, 0.3), (k + 0.45, out_at, 1.0),
               (out_at, dur, 2.2)]
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
    """pieces() for a shot as it stands, stretch and its own later kills included.

    A shot with `anchors` is timed by them, as segments() renders it: derive()
    and the preview used the speed part instead, so a dragged kill -- or a
    double the director put on two hits -- previewed and drew where it was not.
    """
    d = shot["duration"] if dur is None else dur
    p = shot["pre"] if pre is None else pre
    if shot.get("anchors") and speed is None:
        pts = [(min(p, d), float(shot["kill"]))] + [(float(o), float(src)) for src, o in shot["anchors"]
                                                    if 0.0 <= float(o) <= d]
        return fit_pieces(pts, d)[0]
    return pieces(speed or shot["speed"], d, p, _stretch_of(shot), _own_after(shot))


def _own_after(shot: dict) -> float:
    """Source seconds after the main kill that the shot's own later kills need, held.

    0 when it has none. Its own are the kills that follow the main one in a
    chain, each within OWN_KILLS_WITHIN of the one before: the rest of a double
    or a triple, and the kill of a follow-up folded into it by apply_marks. A
    kill further on is another fight a hand-built shot happened to list.
    """
    k0 = float(shot["kill"])
    last = k0
    for k in sorted(float(x) for x in shot.get("kills") or []):
        if k <= last + 1e-6:
            continue
        if k - last > OWN_KILLS_WITHIN:
            break
        last = k
    return last - k0 + OWN_KILL_HOLD if last > k0 else 0.0


def _freeze_of(shot: dict) -> float:
    """Seconds of freeze the render inserts at this shot's kill.

    A freeze REPLACES footage -- the shot is not lengthened by it -- so it is
    taken out of what plays after the kill, and the planner has to leave room
    for it when the shot has later kills of its own to show.
    """
    freeze = 0.4 if "k04" in (shot.get("fx") or []) else 0.0
    # By FAMILY, not by id: "h02" is only the middle of the freeze family,
    # and an exact match left "Freeze and push in (a long beat)" offered,
    # picked and doing nothing at all.
    if shot.get("hero") and (pid := picked(shot.get("hero_fx") or [], "h02")):
        freeze = max(freeze, knob(pid, "hold", 0.75))
    return freeze


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


# How far before the end of the opener's planned run-up its kill's hit may be,
# as a share of the grid step. See plan(): the hit on the beat where the run-up
# ends is that beat's, whichever side of it the bass peaks.
FIRST_HIT_SLACK = 0.25


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
               gap: float, count: int, even: bool = False) -> list[float]:
    """The song times this reel's kills land on: `count` of them from `first`.

    `even`: no quick runs of a kill per hit -- every kill at least most of `gap` from the
    one before. A drop cut one kill a beat wants that; a short run of close hits cut
    kill-per-hit (the player's rule elsewhere) put kills 0.35 s apart at 171 BPM.
    """
    keep = [i for i, t in enumerate(hits) if first - 1e-6 <= t <= end + 1e-6]
    if not keep:
        return [first]
    within = [hits[i] for i in keep]
    strong = [strengths[i] for i in keep] if len(strengths) == len(hits) else None
    kills, _accents = hits_mod.choose_kills(within, strong, target_gap=gap,
                                            **({"min_shot": 0.8 * gap} if even else {}))
    # The opener is not up for grabs: choose_kills takes the loudest hit in
    # each window, and in the first window that is rarely the hit the reel was
    # aimed at -- on Skechers it moved the first kill 2.4 s past the drop.
    if kills and abs(kills[0] - first) > 1e-6:
        kills = [first] + [k for k in kills if k >= first + hits_mod.WINDOW[0] * gap]
    return kills[:count] if count else kills


def _spread_slots(hits: list[float], strengths: list[float], big: list[float], *,
                  first: float, last: float, count: int, min_gap: float) -> list[float]:
    """`count` song times from `first` to about `last`, evenly spread, each on a hit.

    For a reel asked to FILL a length rather than run at its style's pace.
    _hit_slots thins the hits to the style's gap, so a Hype reel put its kills
    1.1 s apart whatever part of the song was chosen: dwayIR's 93 s part came
    out 63 s long while the plan said the run-ups had been lengthened to fill
    it. Here the gap is the part's: each kill takes the strongest hit near its
    even share of it, a big hit first, never closer than `min_gap` to the one
    before -- so the kills are spread over the part and still land on the bass.
    """
    if count <= 0:
        return []
    if count == 1 or last <= first:
        return [first]
    top = max(strengths) if strengths and len(strengths) == len(hits) else 0.0
    pool = sorted((t, (strengths[i] / top if top > 0 else 1.0)
                   + (1.0 if any(abs(t - b) < 0.01 for b in big) else 0.0))
                  for i, t in enumerate(hits) if first - 1e-6 <= t <= last + 1e-6)
    share = (last - first) / (count - 1)
    out = [first]
    for n in range(1, count):
        aim = first + n * share
        lo = out[-1] + min_gap
        near = [(t, s) for t, s in pool if lo - 1e-6 <= t and abs(t - aim) <= share / 2]
        if near:
            # Strength first, then closeness: a big hit a third of a share away
            # beats an ordinary one on the aim.
            t = max(near, key=lambda x: (x[1] - abs(x[0] - aim) / max(share, 1e-6), -x[0]))[0]
        else:
            later = [t for t, _ in pool if t >= lo - 1e-6]
            t = min(later, key=lambda x: abs(x - aim)) if later else max(lo, aim)
        out.append(t)
    return out


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
    fill = str(raw.get("fill") or "")
    return {"arrange": how, "pins": pins,
            "seed": int(_num(raw.get("shuffle_seed"), 0, 2 ** 31 - 1, 0)),
            # Only kills read as headshots go in. See _headshots_only().
            "hs_only": bool(raw.get("hs_only")),
            # How long, and whether a kill may be left out for its run-up, its
            # stillness or the length. Like hs_only, not an ordering: plan()
            # takes both off before rulebook.order sees the rest. "" is "as it
            # always was": the part when one was chosen, else the style.
            "fill": fill if fill in rulebook.FILLS else "",
            "keep_all": bool(raw.get("keep_all"))}


def _same_clip(path) -> tuple:
    """What makes two rows the same clip. NOT the path.

    A re-cut writes a second run folder beside the first -- `..._1918_VALORANT`
    and `..._1918_VALORANT_2` -- holding the SAME clips, byte for byte.
    Measured on this machine: 430 clip files, 389 distinct names, **35 names
    present in more than one run**, every duplicate identical in size. Keyed by
    path they are two clips, and a reel built from both shows the same kill
    twice; one earlier reel showed three kills twice, two of them inside its
    last four seconds.

    THE NAME, AND ONLY THE NAME. The first attempt added the file size, on the
    reasoning that a clip imported from somewhere else could collide. Measured
    on this machine, that reasoning was wrong and expensive:
    `VALORANT_01_CLUTCH-1v2_r13_50m52s_32s.mp4` exists in THREE run folders at
    101429422, 101309669 and 101309669 bytes -- a re-cut re-encodes, so the
    same moment of the same recording comes out a different size. Two of the
    three merged, one did not, and the reel showed that round six times.

    The name is the identity: it carries the game, the clip's index in the run,
    the label, the round, the moment in the recording and the length. Two files
    called that are the same moment, whatever they weigh.
    """
    return Path(path).name.lower()


def is_clutch(clip: dict) -> bool:
    """A clip whose name or labels say it was a clutch, a last-alive, a 1vN or an ace."""
    text = " ".join([str(clip.get("caption") or ""), str(clip.get("name") or ""),
                     Path(str(clip.get("path") or "")).stem]
                    + [str(x) for x in (clip.get("labels") or [])]).upper()
    return any(w in text for w in rulebook.BIG_WORDS)


# THE CLUTCH IS THE BUILD, AS ONE TAKE (R9). The hand-cut Espresso reel played a 1v3
# unbroken through the build and landed its last kill on the drop. The planner cut a
# clutch into single shots wherever the order put them. Here, a Build and drop reel
# whose clips hold one gives its kills consecutive slots ending ON the drop, each
# slot exactly as far before the drop as the kill is before the last one in the clip
# -- so the shots meet where the footage does and it plays as one take.
CLUTCH_LEAD = 0.8           # s of the take before its first kill, at least
CLUTCH_GAP = 1.0            # s kept clear between the last build kill and the take


def clutch_take(shots: list[dict], slots: list[float], drop: float, start: float):
    """-> (order of shot indexes, kill slots) with a clutch's kills ending on the drop.

    Unchanged when there is no drop slot or no clutch clip with two or more shots in
    the reel whose kills fit in the build.
    """
    d = next((i for i, x in enumerate(slots) if abs(x - drop) < 1e-3), None)
    if d is None:
        return list(range(len(shots))), list(slots)
    by_clip: dict[str, list[int]] = {}
    for i, s in enumerate(shots):
        by_clip.setdefault(s["clip"], []).append(i)
    best = None
    for clip, idx in by_clip.items():
        if len(idx) < 2 or not is_clutch({"path": clip, "name": shots[idx[0]].get("name")}):
            continue
        idx = sorted(idx, key=lambda i: float(shots[i]["kill"]))
        last = float(shots[idx[-1]]["kill"])
        run = [idx[-1]]
        for i in reversed(idx[:-1]):
            if drop - (last - float(shots[i]["kill"])) - CLUTCH_LEAD < start - 1e-6:
                break
            run.insert(0, i)
        if len(run) >= 2 and (best is None or len(run) > len(best)):
            best = run
    if not best:
        return list(range(len(shots))), list(slots)
    last = float(shots[best[-1]]["kill"])
    take = [drop - (last - float(shots[i]["kill"])) for i in best]
    kept = [x for x in slots[:d] if x <= take[0] - CLUTCH_GAP + 1e-6]
    others = [i for i in range(len(shots)) if i not in best]
    order = others[:len(kept)] + best + others[len(kept):]
    for k, i in enumerate(best):
        # Every run-up as long as the slot allows: the first opens the take, each
        # later one meets the shot before it where the footage does.
        shots[i]["pre"] = 60.0 if k else max(float(shots[i]["pre"]), take[0] - (kept[-1] if kept else start))
        shots[i]["transition"], shots[i]["tlen"] = "t01", 0.0
    return order, kept + [round(x, 4) for x in take] + list(slots[d + 1:])


KILL_BLURS = ("k14", "k21")  # blur snap, zoom blur hit: soft at the very frame the kill lands
DEFAULT_CLIP_SHOTS = 4      # shots a clip may give a reel when its style sets no cap (R13)
CAP_FROM_CLIPS = 5          # ...applied only from this many clips up


def shown_kills(shot: dict) -> int:
    """How many of a shot's clip's kills fall inside the footage the shot plays."""
    ps = shot_pieces(shot)
    pre, dur = float(shot["pre"]), float(shot["duration"])
    lo = float(shot["kill"]) - source_used(ps, pre)
    hi = float(shot["kill"]) + source_used(ps, dur) - source_used(ps, pre)
    return sum(1 for k in shot.get("kills") or [] if lo - 0.05 <= float(k) <= hi + 0.05)


def honest_captions(shots: list[dict]) -> None:
    """A caption names the kills its shot SHOWS (R12). In place.

    The caption came from the clip -- TRIPLE KILL on the last of the clip's shots --
    and the shot under it often showed one kill: the JUST A BOY reel had TRIPLE KILL
    and ACE on single-kill shots. Now it says what plays, or nothing.
    """
    for s in shots:
        if s.get("caption"):
            s["caption"] = rulebook.label_for(shown_kills(s))


def _headshots_only(chosen: list[dict]) -> tuple[list[dict], list[str], int]:
    """Each clip with only its headshot kills. -> (clips, paths with none, kills dropped)

    A kill counts only when it was READ as a headshot: one the reader could
    not see is left out rather than guessed in, because the player asked for
    headshots and an unread kill is as likely as not to be a body shot. A clip
    with no headshot reading at all keeps nothing.
    """
    kept, none, dropped = [], [], 0
    for c in chosen:
        hs = list(c.get("hs") or [])
        ks = list(c.get("kills") or [])
        if is_clutch(c) and len(ks) > 1:
            # A CLUTCH STAYS WHOLE (asked 2026-10-17): it is the build's one take, and
            # a 1v3 that drops its body-shot kill is a 1v2 that never happened.
            kept.append(dict(c))
            continue
        good = [k for k, h in zip(ks, hs) if h is True]
        dropped += len(ks) - len(good)
        if good:
            kept.append(dict(c, kills=good, hs=[True] * len(good), _hs_times=good,
                             kill_count=len(good)))
        else:
            none.append(c["path"])
    return kept, none, dropped


def _shaping(raw: dict | None) -> dict:
    """The dials, clamped. Anything missing or unreadable is left centred."""
    out = {}
    for key, (lo, hi, mid) in SHAPING.items():
        out[key] = _num((raw or {}).get(key), lo, hi, mid)
    return out


def _plan_fit(clips: list[dict], style_key: str, *, shape_it: dict, **kw) -> tuple[dict, list[str]]:
    """PERFECT FIT (SLOWER): the order and the song searched together -- see arrange_fit.

    Kept to this one door so plan() itself is untouched by it. Anything that
    goes wrong in there plans the ordinary way and says so, rather than
    leaving the player with no reel at all; a ProjectError (nothing usable
    chosen) is the player's to read either way.
    """
    from . import arrange_fit

    try:
        return arrange_fit.plan(clips, style_key, shape_it=shape_it, **kw)
    except ProjectError:
        raise
    except Exception as e:                              # noqa: BLE001
        log.warning("studio: perfect fit failed, planning the usual way: %s", e, exc_info=True)
        proj, notes = plan(clips, style_key, shape_it=dict(shape_it, arrange="build"), **kw)
        proj["arrange"] = "fit"                         # a rebuild tries the fit again
        return proj, ["Perfect fit could not plan this reel, so it was planned the usual way."] + notes


def _plan_sections(clips: list[dict], style_key: str, *, shape, song: str, part, seed,
                   checks: bool, confirm, theirs, refine, shape_it: dict, which: str = "drop",
                   **kw) -> tuple[dict, list[str]]:
    """FOLLOW THE SONG: the set-up builds into the drop, the drums cut the rest -- see director.

    The project around the shots -- look, sound, overlays, lyrics -- is the
    style's, from an ordinary plan of the same clips; the shots, the part and
    the marks are the director's. Without a song, or with nothing in the clips
    to build with, it plans Best order and says why.

    `which` is the director: "drop" (director.py) or "fasthead" (fasthead.py,
    the same loop of kill checks around a planner of its own).
    """
    from . import director, fasthead, rhythm

    label = STYLE[style_key].label if style_key in STYLE else "This style"
    way = "the usual build-and-drop way" if which == "drop" else "the usual way"

    base_it = dict(shape_it or {}, arrange="hits")
    was = str((shape_it or {}).get("arrange") or "") or "build"
    if not song or shape is None or not getattr(shape, "beats", None):
        proj, notes = plan(clips, style_key, shape=shape, song=song, part=part, seed=seed, checks=checks,
                           confirm=confirm, theirs=theirs, refine=refine, shape_it=base_it, _direct=False, **kw)
        proj["arrange"] = was
        return proj, [f"{label} needs a song to follow; this reel was planned without one."] + notes
    # The project around the shots only: no kill checks, which decode every clip.
    proj, notes = plan(clips, style_key, shape=shape, song=song, part=part, seed=seed,
                       shape_it=base_it, _direct=False, **{k: v for k, v in kw.items() if k != "measure"})
    proj["arrange"] = was
    chosen = {c["path"]: dict(c) for c in clips if c and c.get("path")}
    hs_at = {(p, round(float(k), 3)): bool(h) for p, c in chosen.items()
             for k, h in zip(c.get("kills") or [], list(c.get("hs") or []) + [False] * 99)}
    if checks:
        have = plan_checks()
        confirm, theirs, refine = (confirm or have.get("confirm"), theirs or have.get("theirs"),
                                   refine or have.get("refine"))
    # THE KILL CHECKS ON THE CLIPS IT USES, NOT ALL OF THEM. The ordinary plan reads
    # every chosen clip's kill emblem; asked to make a reel from 150 favourites that
    # took 13 minutes, for the 25 that went in. So: plan, check the clips used, plan
    # again with what the checks said, until the clips used have all been checked.
    clarity = kill_clarity if checks else None
    hidden = 0
    checked: set[str] = set()
    seed_n = int(seed if seed is not None else proj.get("seed") or 0)
    try:
        rh = rhythm.for_song(shape)
    except (AttributeError, OSError) as e:           # a song that cannot be read again: the usual way
        log.info("studio: no rhythm for the song (%s)", e)
        return proj, [f"The song could not be read for its drum hits; planned {way}."] + notes
    # the clip the player chose to build on, in the guided maker's build slot
    build = str((shape_it or {}).get("build_clip") or "")
    # the part the page drew by itself, which the player never touched: a length, not an end
    loose = bool((shape_it or {}).get("part_auto"))
    got = None

    def direct():
        if which == "fasthead":
            return fasthead.plan(list(chosen.values()), shape, rh, part=part, seed=seed_n, loose=loose)
        return director.plan(list(chosen.values()), shape, rh, part=part, seed=seed_n, build=build, loose=loose)
    for _ in range(4):
        try:
            got = direct()
        except ValueError as e:
            return proj, [f"{e} It was planned {way} instead."] + notes
        todo = [chosen[s["clip"]] for s in got.shots if s["clip"] not in checked and s["clip"] in chosen]
        todo = list({c["path"]: c for c in todo}.values())
        if not todo or (confirm is None and refine is None and clarity is None):
            break
        fixed = todo
        if confirm is not None:
            fixed = _confirm_kills(fixed, confirm, theirs)[0]
        if refine is not None:
            fixed = _refine_kills(fixed, refine)[0]
        if clarity is not None:
            # a kill taken through a flash is not one to cut to (see CLEAR_MIN)
            for c in fixed:
                clear = [k for k in c.get("kills") or []
                         if (q := clarity(c["path"], float(k))) is None or q >= CLEAR_MIN]
                hidden += len(c.get("kills") or []) - len(clear)
                c["kills"] = clear
            fixed = [c for c in fixed if c.get("kills")]
        for c in todo:
            checked.add(c["path"])
            chosen.pop(c["path"], None)       # an emblem check that found no kill drops the clip
        for c in fixed:
            own = [(k, h) for (p, k), h in hs_at.items() if p == c["path"]]
            c["hs"] = [any(h for k0, h in own if abs(k0 - float(k)) <= SNAP_AFTER + 0.05)
                       for k in c.get("kills") or []]
            chosen[c["path"]] = c
    else:
        try:
            got = direct()
        except ValueError as e:
            return proj, [f"{e} It was planned {way} instead."] + notes
    proj["shots"] = got.shots
    proj["song_offset"] = round(got.part[0], 5)
    proj["song_marks"] = [round(t, 4) for t in got.marks]
    proj["part_end"] = round(got.part[1], 5)
    proj["song_drop"] = round(got.drop, 4)
    proj["intro"] = "i00"                    # the take is the opening; nothing is laid over it
    # THE LAST KILL IS NOT FADED. The style's fade is most of a bar (1.2-2.2 s) and
    # ran over the last kill of two of the first four reels; a short one, which
    # derive() holds back until OUTRO_AFTER_KILL after the kill, does not.
    proj["outro_len"] = director.OUTRO_FADE
    if which == "fasthead":
        # the style's look IS the beat engine (o10), keyed off the grid and the drop; no groove on top
        proj["groove"] = {}
        proj["hs_only"] = True
    else:
        # the other layers drive the camera and the light; the beat engine's flips would fight them
        proj["groove"] = fx_schedule.schedule(rh, got.part[0], got.part[1], got.kills, got.drop)
        proj["overlays"] = [o for o in proj.get("overlays") or [] if fam(o) != "o09"]
    used = {s["clip"] for s in got.shots}
    proj["selection"] = [{"clip": c["path"], "name": str(c.get("name") or Path(c["path"]).stem),
                          "why": "" if c["path"] in used else
                          ("Not needed: every headshot slot was filled by other clips, or this clip's "
                           "headshots had another kill too close to cut around."
                           if which == "fasthead" else
                           "Not needed: the set-up and the hits after the drop were filled by other clips.")
                          if c["path"] in chosen else
                          "No kill showed on screen: the game's kill icon never appeared in this clip."}
                         for c in clips if c and c.get("path")]
    if hidden:
        got.notes.append(f"{hidden} kill(s) were left out because the screen was washed out at the kill "
                         f"(a flash or smoke): it could not be seen.")
    return proj, got.notes


# THE FAST-CUT RULES (K2, K3, K4), all measured on one reel: headshot3, Hype, 150 BPM.
#
#   * The misses. Six shots the player flagged as missing their kill were read by eye:
#     four had 0.22 s after the kill with a crossfade overlapping the last part of
#     it (0.07-0.12 s actually seen), two had a speed ramp that made the hit arrive
#     late. 14 of the reel's 30 shots had exactly 0.22 s after the kill.
#   * Where 0.22 came from. apply_marks gave each shot's run-up everything in the gap
#     between two kills except 0.22 s. With kills 0.8 s apart that is 0.58 s of
#     lead-up and 0.22 s of the kill itself.
#   * The 0.40 s floor that came out of this (K3) is gone again (2026-10-17). At
#     one kill a beat with the cut half a beat before it, 0.40 s after each kill
#     leaves 0.17 s of run-up at 104 BPM -- the enemy is never seen before he
#     dies. The hand-cut Espresso reel gave every kill half a beat (0.29 s) after
#     it, hard cuts at real speed, and it reads; the player asked for the rule to
#     go. Every style has the floor it always had.
FAST_BPM = 110.0           # below this a cut every second is not fast, and variety is fine
SLOW_AFTER = 0.22          # the least any kill has after it
BUILD_BEATS = 4            # a cut every this many beats while the song builds to its drop


def fast_reel(style, bpm: float | None) -> bool:
    """Whether the fast-cut rules apply: a style that asks for them, on a song fast enough.

    Build and drop always: its build is plain cuts and its drop is one kill a beat, at any
    tempo. Behind the 110 BPM gate its drop logic never ran -- Espresso, at 104, came out a
    plain montage with a kill every two beats, white dissolves and slow motion on the kills.
    """
    if getattr(style, "drop", False):
        return True
    return bool(getattr(style, "fast_cuts", False)) and float(bpm or NO_SONG_BPM) >= FAST_BPM


# A SONG THIS SHORT IS PLAYED WHOLE when no part was chosen: it is a Short's own
# audio, cut to its length already, and the planner's own start -- the first loud
# bass hit -- dropped Espresso's first 3 s, the build the reference edit is cut
# over, and its last second.
SHORT_SONG_SECONDS = 45.0
DROP_FLASH = "k03"          # the white flash the kill on the drop gets
DROP_KILL_GAP = 0.55        # about how far apart the drop's kills are: the hand-cut reel's beat at 104 BPM
DROP_LEAD_BARS = 4          # Build and drop on a long song: this much build before the drop...
DROP_AFTER_BEATS = 32       # ...and this much after it, or up to the next drop if that is nearer


def auto_part(grid: "Grid", style: "Style") -> tuple[float, float] | None:
    """The stretch of song a reel plays when the player chose none, or None for the planner's own.

    A short song plays whole. Build and drop on a long one plays DROP_LEAD_BARS of build into
    the first drop with room for them, and on to the next drop or DROP_AFTER_BEATS past it --
    what the Make page's "Build into the drop" button sets, made the default for the style
    that is about a drop.
    """
    if not grid.beats or not grid.seconds:
        return None
    if grid.seconds <= SHORT_SONG_SECONDS:
        return 0.0, float(grid.seconds)
    if not style.drop or not grid.hits:
        # Without hits there is nothing to land the drop's kill on but the grid, and
        # the planner's own drop path (the fourth kill on the drop) does that already.
        return None
    lead = DROP_LEAD_BARS * 4 * grid.beat
    drops = sorted(grid.drops) or ([float(grid.drop)] if grid.drop else [])
    for d in drops:
        if d < lead or d > grid.seconds - 4 * grid.beat:
            continue
        start = min(grid.beats, key=lambda b: abs(b - (d - lead)))
        later = [n for n in drops if d + 8 * grid.beat < n <= d + 2 * DROP_AFTER_BEATS * grid.beat]
        end = later[0] if later else d + DROP_AFTER_BEATS * grid.beat
        return float(start), float(min(grid.seconds, end))
    return None


def fast_rules(style: "Style") -> "Style":
    """`style` with one transition, one kill effect, one hero treatment and real speed.

    Applied BEFORE the player's template, so anything they chose on the Make page
    still wins -- including a deliberate set of several, which is the point of
    letting them choose a set.
    """
    return dataclasses.replace(
        style,
        cuts=("t01",), transition_pool=("t01",),
        kill=(style.kill[0],), kill_pool=(style.kill[0],),
        hero=(style.hero[0],), hero_pool=(style.hero[0],),
        speed="s00", hero_speed="s00", speed_pool=("s00",),
        camera_pool=(style.camera,),
        energy=0.0)


def after_floor(project: dict) -> float:
    """The least a kill may have after it in this reel, in seconds. The same for every style."""
    return SLOW_AFTER


def drop_in(grid: "Grid", lo: float, hi: float) -> float | None:
    """The drop of the stretch of song a reel plays, or None. Song seconds.

    Of the drops the detector found, the first with room for a build before it and
    for the drop to be heard after it. NOT the biggest in the whole song: headshot3
    plays 2:29-3:31, its song's biggest drop is at 4:33, and the reel never
    reached it -- so it had no build and no drop at all.
    """
    for d in sorted(grid.drops):
        if lo + 2 * BUILD_BEATS * grid.beat <= d <= hi - 3 * grid.beat:
            return d
    if grid.drop and lo + 2 * BUILD_BEATS * grid.beat <= grid.drop <= hi - 3 * grid.beat:
        return float(grid.drop)
    return None


def build_then_drop(hits: list[float], strengths: list[float], *, first: float, drop: float,
                    count: int, beat: float, gap: float, end: float, even: bool = False) -> list[float]:
    """Kill times (song seconds) for a reel that builds, then drops.

    Slow, plain cuts -- one every BUILD_BEATS beats -- until the drop; the first kill
    EXACTLY on it; then a cut every hit at the style's own pace. headshot3 had its
    kill 0.36 s after the drop, nearly a beat off, because the kills were laid on the
    song's hits and the drop is not on one.
    """
    step = BUILD_BEATS * beat
    loud = dict(zip(hits, strengths)) if len(strengths) == len(hits) else {}

    def on_hit(t: float, after: float) -> float:
        # THE LOUDEST HIT IN THIS KILL'S STRETCH OF THE BUILD, not the one nearest a
        # grid point: an editor cuts the build on its accents, and the nearest hit
        # is whichever the count happens to land by (see hits._loudest_run).
        near = [h for h in hits if t - step / 2 <= h < t + step / 2 and h >= after + beat - 1e-6
                and h <= drop - beat + 1e-6]
        if not near:
            return t
        return max(near, key=lambda h: (loud.get(h, 0.0), -abs(h - t)))

    out: list[float] = []
    t = first
    while t < drop - 0.75 * step and len(out) < count - 1:
        out.append(round(on_hit(t, out[-1] if out else -1e9), 4))
        t += step
    out.append(round(drop, 4))
    rest = count - len(out)
    if rest > 0:
        out += _hit_slots(hits, strengths, first=drop + gap, end=end, gap=gap, count=rest, even=even)
    return sorted(set(out))


def plan(clips: list[dict], style_key: str = DEFAULT_STYLE, *, shape=None,
         song: str = "", fmt: str = "landscape", name: str = "",
         max_seconds: float = 0.0, seed: int | None = None,
         measure=None, confirm=None, theirs=None, refine=None, checks: bool = False,
         part: tuple[float, float] | None = None,
         template: dict | None = None,
         shape_it: dict | None = None, _direct: bool = True) -> tuple[dict, list[str]]:
    """Build a project from chosen clips. -> (project, notes)

    `refine(path, game, t)` -> when the game's kill emblem first shows nearest t,
    or None (see kill_appearance). `checks=True` fills in whichever of `measure`,
    `confirm`, `theirs` and `refine` were left None from plan_checks(), so a
    caller that is not the web page gets the same checks the page does.

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

    `shape_it` is the dials plus how the reel is made: `arrange` (see
    rulebook.ARRANGEMENTS; "hits" is Best order), `pins`, `hs_only`, `fill`
    (How long: "style", "part", "all"; "" is the part when one was chosen) and
    `keep_all` (Keep every kill). All of them are kept on the project.
    """
    if str((shape_it or {}).get("arrange") or "") == "fit":
        return _plan_fit(clips, style_key, shape=shape, song=song, fmt=fmt, name=name,
                         max_seconds=max_seconds, seed=seed, measure=measure, confirm=confirm,
                         theirs=theirs, refine=refine, checks=checks, part=part,
                         template=template, shape_it=shape_it)
    # BUILD AND DROP PLANS ITSELF (clips/director.py). The style used to get the
    # new planner only when "Follow the song" was ALSO chosen under Order -- a
    # wrong combination nothing warned about -- so the style that makes the best
    # reels gave the old logic to anyone who touched nothing else. Now the style
    # decides its own order; `_direct=False` is the way back for the fallbacks
    # inside _plan_sections (no clip to build with, no drop, no song).
    asked = str((shape_it or {}).get("arrange") or "")
    if _direct and asked != "fit" and (asked == "sections" or (STYLE.get(style_key) and STYLE[style_key].drop)):
        return _plan_sections(clips, style_key, shape=shape, song=song, fmt=fmt, name=name,
                              max_seconds=max_seconds, seed=seed, measure=measure, confirm=confirm,
                              theirs=theirs, refine=refine, checks=checks, part=part,
                              template=template, shape_it=shape_it)
    # FAST-PACED HEADSHOT PLANS ITSELF TOO (clips/fasthead.py): the general planner's
    # fixed 2.0 s pace failed the render gate on every song it was tried on.
    if _direct and asked != "fit" and style_key == "fasthead" and song:
        return _plan_sections(clips, style_key, shape=shape, song=song, fmt=fmt, name=name,
                              max_seconds=max_seconds, seed=seed, measure=measure, confirm=confirm,
                              theirs=theirs, refine=refine, checks=checks, part=part,
                              template=template, shape_it=shape_it, which="fasthead")
    style = STYLE.get(style_key) or STYLE[DEFAULT_STYLE]
    fast = fast_reel(style, getattr(shape, "bpm", None))
    if fast:
        style = fast_rules(style)
    if template:
        style = templated(style, template, exact=fast)
    # SHAPING THE REEL WITHOUT LEAVING THE STYLE. Each of these multiplies what
    # the style's references measured rather than replacing it, so "faster"
    # means faster than THIS style rather than a jump to another one, and a
    # reel at every dial centred is exactly the reel the style would have made.
    tw = _shaping(shape_it)
    # HOW THE REEL IS ORDERED, and anything the player pinned into a slot. Both
    # ride on the same dict the dials do, so one control panel carries all of
    # it and a rebuild keeps what was asked for.
    arrangement = _arrangement(shape_it)
    # Not an ordering: which kills may go in at all. Kept apart from the
    # kwargs rulebook.order takes.
    hs_only = arrangement.pop("hs_only")
    fill = arrangement.pop("fill")
    keep_all = arrangement.pop("keep_all")
    if tw["effects"] != 1.0:
        # Scaled on the style itself rather than at the draw: _vary() is called
        # from the page too, and a dial the page could not see would be lost
        # the first time somebody pressed "Mix them up".
        style = dataclasses.replace(style, energy=max(0.0, min(1.0, style.energy * tw["effects"])))
    grid = Grid.of(shape) if shape is not None else Grid.none()
    notes: list[str] = []
    if fast:
        notes.append(f"{STYLE[style_key].label} is a fast-cut style at {grid.bpm:.0f} BPM, so every "
                     f"cut is a hard cut, every kill has the same effect and the footage plays at "
                     f"real speed. Choose effects yourself on the Make page to mix them.")
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
    if not part and song and not fill:
        # Only when the player left "How long" alone: asked for the style's length,
        # or every clip, that is what they get.
        part = auto_part(grid, style)
        if part and grid.seconds <= SHORT_SONG_SECONDS:
            notes.append(f"The song is {grid.seconds:.0f} s, so the reel plays all of it.")
        elif part:
            notes.append(f"{style.label} plays {part[1] - part[0]:.0f} s of the song: the build from "
                         f"{part[0]:.1f} s into the drop, and on from there.")
    if part and song and grid.beats and grid.seconds:
        part_start = max(0.0, min(float(part[0]), grid.seconds - 1.0))
        end = float(part[1] or 0.0)
        end = min(end, grid.seconds) if end > part_start else grid.seconds
        part_len = end - part_start
        if part_len < rulebook.MIN_RUN_SECONDS + beat:
            part_start = part_len = 0.0
    # HOW LONG. Unasked, it is what it always was: a chosen part is filled,
    # otherwise the style decides. Asked, the style keeps only the feel.
    asked_fill = fill
    if not fill:
        fill = "part" if part_len else "style"
    if fill == "part" and not part_len:
        fill = "style"
        notes.append("No part of the song was chosen to fill, so the reel is the style's length.")

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
    if style.drop and part_len:
        # Most of a Build and drop reel is the drop, one kill a beat: sized at the
        # references' 1.2 s a shot it chose 11 of 27 moments for 21 s of Espresso and
        # ran out of kills two seconds before the end.
        want = beat
    # THE GRID IS AS FINE AS THE TARGET NEEDS. In whole beats the shortest shot
    # the rules allow is two of them, so a fast style on a half-time song could
    # not cut faster than 1.5 s and Hype, Velocity and Montage all came out at
    # the same three-beat shot -- measured over 19 reels. `div` is how many
    # steps make a beat, and everything from here down is counted in steps.
    div = 1 if (style.drop and part_len) else _grid_div(want, beat)
    step = beat / div
    shot_beats = max(1, min(8 * div, int(round(want / step))))
    # The opening hold is left on the beat: it already lands inside the
    # references' band on 20 of 24 reels, so only its unit changes.
    open_beats = _pow2_beats(max(meas.get("first_shot") or 4.0, 2.0), beat, lo=2, hi=16) * div
    # No flash cuts in a fast-cut reel: a white flash on a share of the cuts is a second
    # transition, and the rule is one. (The flash is what t02 is.)
    flash_share = 0.0 if fast else min(0.9, (meas.get("flashes_per_min") or 0.0) / max(cpm, 1.0) * tw["flash"])

    # ONE ENTRY PER CLIP. Rebuilding a reel in another style sent the timeline's
    # shots back as the clip list, so a clip used in nine shots arrived nine
    # times, became nine sequences, and select() -- which ranks sequences --
    # took the same footage again and again while the clips that were only
    # asked for once were left out "to fit the reel's length". DRIPSKETCHERS1
    # came out as 23 shots of 4 clips from a selection of 20.
    offered = []
    seen: set[tuple] = set()
    for c in clips:
        if not c or not c.get("path"):
            continue
        k = _same_clip(c["path"])
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

    if hs_only:
        chosen, no_hs, dropped_k = _headshots_only(chosen)
        left_out(no_hs, "No kill in this clip was read as a headshot.")
        if dropped_k:
            notes.append(f"Headshots only: {dropped_k} kill(s) that were not headshots, or could "
                         f"not be read, were left out.")
        if not chosen:
            raise ProjectError("None of the chosen clips has a kill read as a headshot.")

    if checks:
        have = plan_checks()
        measure = measure or have.get("measure")
        confirm = confirm or have.get("confirm")
        theirs = theirs or have.get("theirs")
        refine = refine or have.get("refine")
    if confirm is not None:
        before = [c["path"] for c in chosen]
        chosen, moved, dropped, added = _confirm_kills(chosen, confirm, theirs)
        if hs_only:
            # The emblem check may move a kill a few frames, or add one the
            # feed missed. A moved headshot is still that headshot; an added
            # kill was never read, so it does not go in.
            for c in chosen:
                if c.get("_hs_times"):
                    c["kills"] = [k for k in c["kills"]
                                  if any(abs(k - h) <= SNAP_AFTER + 0.05 for h in c["_hs_times"])] or c["kills"][:0]
            chosen = [c for c in chosen if c.get("kills")]
        kept_paths = {c["path"] for c in chosen}
        left_out((p for p in before if p not in kept_paths),
                 "No kill showed on screen: the game's kill icon never appeared in this clip.")
        if moved or dropped or added:
            notes.append(f"Kill times checked against the game's own kill emblem: {moved} moved onto it, "
                         f"{dropped} with no emblem left out, {added} the kill feed missed added.")
    if refine is not None:
        # THE LAST WORD ON WHEN A KILL HAPPENS, after every check that decides WHETHER
        # it did. Run after the headshot and emblem filters, not before: those match
        # kills to readings by time, and moving a kill first would unmatch them.
        chosen, got = _refine_kills(chosen, refine)
        if got["moved"]:
            sh = sorted(got["shifts"])
            notes.append(
                f"Kill times read from the first frame of the game's own kill emblem: "
                f"{got['moved']} of {got['seen']} moved (median {sh[len(sh) // 2]:+.2f} s, "
                f"{sh[0]:+.2f} to {sh[-1]:+.2f} s)"
                + (f"; {got['total'] - got['seen']} had no emblem to read and kept their time."
                   if got["total"] > got["seen"] else "."))
    # A KILL THROUGH A FLASH IS NOT ONE TO CUT TO (F2, every style): the same check the
    # director runs on its clips (kill_clarity, CLEAR_MIN), here on every kill offered.
    washed: list[tuple[str, float]] = []
    if checks:
        kept_clips = []
        for c in chosen:
            ks = list(c.get("kills") or [])
            hs = list(c.get("hs") or [])
            ok = [(q := kill_clarity(c["path"], float(k))) is None or q >= CLEAR_MIN for k in ks]
            if all(ok):
                kept_clips.append(c)
                continue
            washed += [(c["path"], k) for k, good in zip(ks, ok) if not good]
            c = dict(c, kills=[k for k, good in zip(ks, ok) if good])       # a copy: the library's row stays whole
            if hs:
                c["hs"] = [h for h, good in zip(hs + [None] * len(ks), ok) if good]
            if c["kills"]:
                kept_clips.append(c)
        chosen = kept_clips
        if washed:
            notes.append(f"{len(washed)} kill(s) were left out because the screen was washed out at the "
                         f"kill (a flash or smoke): it could not be seen.")
    # WHY EACH KILL OF A CLIP THAT WENT IN IS NOT IN IT. A clip's row said
    # nothing when one of its three kills fell out, so a missing kill looked
    # like a bug rather than a decision. (clip path, kill) -> reason.
    kill_why: dict[tuple[str, float], str] = {}
    short: list[tuple[str, float]] = []
    all_moments = rulebook.moments(chosen, beat, keep_short=keep_all, dropped=short)
    for key in short:
        kill_why.setdefault(key, "too little footage before it to show the fight")
    # NO CLIP TAKES OVER THE REEL (R13). A style that sets no cap of its own still
    # holds each clip to DEFAULT_CLIP_SHOTS when there are clips enough to fill the
    # reel without it: the JUST A BOY reel put one 8-kill clip in 7 of its 36 shots
    # and another in 6, from 29 clips. Never with "Keep every kill", which asks for
    # all of them, and never on a handful of clips, which need every shot they have.
    cap = style.max_per_clip or (DEFAULT_CLIP_SHOTS if (not keep_all and
                                 len({m.group for m in all_moments}) >= CAP_FROM_CLIPS) else 0)
    if cap:
        before_cap = list(all_moments)
        capped: list[tuple[str, float]] = []
        all_moments = rulebook.cap_per_clip(all_moments, cap, capped)
        for key in capped:
            kill_why.setdefault(key, f"this clip already gives the reel {cap} shots")
        if len(before_cap) != len(all_moments):
            notes.append(f"{len(before_cap) - len(all_moments)} moment(s) left out: no clip "
                         f"gives this reel more than {cap} shots, so the "
                         f"weakest of a clip's own go first.")
    # ONE CLIP, ONE FIGHT in the fast styles (F2): at a cut every beat, two fights of one
    # file read as the same scene twice. Not with Keep every kill, and not on a handful.
    if fast and not keep_all and len({m.group for m in all_moments}) >= CAP_FROM_CLIPS:
        before_fight = len(all_moments)
        refought: list[tuple[str, float]] = []
        all_moments = rulebook.one_fight_per_clip(all_moments, refought)
        for key in refought:
            kill_why.setdefault(key, "another fight of this clip is already in the reel")
        if len(all_moments) < before_fight:
            notes.append(f"{before_fight - len(all_moments)} moment(s) left out: a fast reel shows one "
                         f"fight from each clip, so the same scene never comes round twice.")
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
        before_still = list(all_moments)
        all_moments, still = rulebook.drop_still(all_moments, stats, keep_all=keep_all)
        if style.drop:
            # A clutch's quiet kill is still its kill: the 1v3's last one is a long
            # shot down a lane, and leaving it out cut the take short of the drop.
            back = [m for m in before_still if m not in all_moments and is_clutch(m.clip)]
            if back:
                all_moments = [m for m in before_still if m in all_moments or m in back]
                still -= len(back)
        stayed = {id(m) for m in all_moments}
        for m in before_still:
            if id(m) not in stayed:
                for k in m.kills:
                    kill_why.setdefault((m.clip["path"], k), "nothing moves on screen around it")
        if still:
            notes.append(f"{still} moment(s) left out: nothing moves on screen around the kill "
                         f"(a death camera, or standing still).")
        moving = {m.clip["path"] for m in all_moments}
        left_out((p for p in with_moments if p not in moving),
                 "Nothing moves on screen around its kill (a death camera, or standing still).")
    est = {id(m): (rulebook.FOLLOW_UP_BEATS * div if m.seq > 0 and not (style.drop and part_len)
                   else shot_beats) for m in all_moments}
    available = sum(est.values()) * step
    # The chosen part's end is the one length no setting may pass.
    hard = math.floor(part_len / beat + 1e-6) * beat if part_len else 0.0
    if fill == "part":
        # Whole beats of the chosen part. select() below keeps every moment
        # when there is less material than this, and leaves out the weakest
        # only when the part cannot hold them all.
        target = hard
    elif fill == "all":
        target = 0.0
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
        if hard:
            target = min(target, hard)
    # A reel with less material than one phrase uses all of it: the phrase
    # rule trims a surplus, it never throws away a short selection's clips.
    # "Every clip I chose" is the same rule with no phrase to round to.
    if fill == "all" or (not part_len and target < rulebook.PHRASE_BARS * 4 * beat - 1e-6
                         and not max_seconds):
        target = 0.0
        pool = list(all_moments)
    want_beats = int(round(target / step))
    if target:
        pool = rulebook.select(all_moments, target, lambda m: est[id(m)] * step)
    min_gap = rulebook.MIN_KILL_GAP_SECONDS
    if keep_all:
        # KEEP EVERY KILL: nothing is left out to fit a length. The kills are
        # put closer together instead (see the marks below), down to
        # MIN_KILL_GAP_SECONDS apart -- and only a chosen part too short to
        # hold them even then loses its weakest (see room_for below), because
        # its end is the one length the player fixed.
        pool = list(all_moments)
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
    # a fast-cut reel plays at real speed to the end (K2): no slowed exit on its last shot
    closer_post = rulebook.ENDING_BEATS * div if style.outro in ("e01", "e03", "e02") and not fast else 0
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
        # THE PEAKS, AND THEY NO LONGER DEPEND ON A CAPTION. A moment was
        # only allowed to be a hero if it carried one, and a caption is set
        # only on the last burst of a clip that gave up two or more kills --
        # so a reel of single headshots had almost none. Measured on a
        # 41-shot headshot reel: ONE hero moment in the whole thing, which is
        # a montage with no peaks in it.
        #
        # The caption was there to be drawn by the Text slam, and the slam is
        # gone, so the coupling now has nothing behind it at all: the
        # strongest sixth of the moments are the peaks, captioned or not.
        heroes_ = set(ranked_[:max(1, len(ms) // 6)])
        lens_ = rulebook.walk(ms, beat=step, energy=energy, song_start=start, base=shot_beats,
                              open_beats=open_beats, run_beats=run_b, pre_share=style.pre_share,
                              first_index=first_index * div, downbeat_pos=grid.downbeat_pos * div,
                              fixed=fixed, heroes=heroes_, closer_post=closer_post,
                              phrase_from=first_kill_b, div=div)
        return lens_, heroes_

    # WHERE THE KILLS LAND, as a rule both the ordering and the cut use. At the
    # style's pace unless a length was asked for: then spread over the part,
    # or -- keeping every kill -- closed up to fit the style's length.
    gap_style = 60.0 / max(cpm, 1.0)
    end_at = (part_start + part_len) if (part_len and fill != "all") else grid.seconds
    tail_s = max(1.0, closer_post * step)

    def spread_to(first: float, count: int) -> float | None:
        if fill == "part" and part_len:
            return end_at - tail_s
        if keep_all and target and count > 1:
            # Closed up only when the style's own pace cannot fit them all in
            # the style's length -- and never past the part's end.
            span = target - first_kill_b * step - tail_s
            natural = _hit_slots(grid.hits, grid.hit_strength, first=first, end=first + span,
                                 gap=gap_style, count=count)
            if len(natural) < count:
                return min(end_at - tail_s, first + max(span, (count - 1) * min_gap))
        return None

    # THE BUILD AND THE DROP (K4), for a fast-cut reel over a part the player chose.
    # Only with a chosen part: without one the planner picks where in the song to
    # start for its own reasons, and the part is how somebody says "this build into
    # this drop" -- which is also what the "Build into the drop" button sets.
    drop_t = drop_in(grid, part_start, end_at) if (fast and song and grid.hits and part_len) else None
    # One kill a beat after the drop -- or every other beat on a fast song: at 171 BPM a
    # beat is 0.35 s, and a shot that short opens 0.13 s before its kill.
    drop_gap = grid.beat * max(1, int(round(DROP_KILL_GAP / max(grid.beat, 1e-3))))
    drop_shot = None

    def kill_slots(first: float, count: int, last: float | None = None) -> list[float]:
        if drop_t is not None and drop_t - first >= 0.75 * BUILD_BEATS * grid.beat:
            # Build and drop: from the drop on, a kill every beat -- the hand-cut Espresso
            # reel's 16 kills on 16 beats -- not the style's references' 1.2 s.
            return build_then_drop(grid.hits, grid.hit_strength, first=first, drop=drop_t, count=count,
                                   beat=grid.beat, gap=drop_gap if style.drop else gap_style,
                                   end=end_at, even=bool(style.drop))
        last = spread_to(first, count) if last is None else last
        if last is None:
            return _hit_slots(grid.hits, grid.hit_strength, first=first, end=end_at,
                              gap=gap_style, count=count)
        return _spread_slots(grid.hits, grid.hit_strength, grid.big, first=first,
                             last=min(last, end_at), count=count, min_gap=min_gap)

    # Where the first kill will land, worked out before the shots are, as the
    # cut below works it out. For what follows, not for the cut itself.
    first0 = 0.0
    room_full = False
    if song and grid.hits:
        if part_len:
            first0 = _first_kill(grid.hits, [], earliest=part_start + first_kill_b * step)
        else:
            first0 = _first_kill(grid.hits, grid.big, earliest=run_b * step, drums_in=grid.drums_in or 0.0)
    if keep_all and part_len and fill != "all" and song and grid.hits:
        # How many kills the part can hold at the closest they may be: hits,
        # not seconds, because a kill only lands on a hit and the song's hits
        # are where they are. A part that cannot hold every kill even then
        # loses its weakest sequences, whole.
        inside = [t for t in grid.hits if first0 - 1e-6 <= t <= end_at - tail_s + 1e-6]
        dt = (sorted(b - a for a, b in zip(inside, inside[1:]))[(len(inside) - 1) // 2]
              if len(inside) > 2 else beat)

        def need(m) -> float:
            # A kill lands on a hit, at least min_gap after the one before,
            # and a moment's own later kills play out before the next.
            own = (m.last - m.first) + OWN_KILL_HOLD + rulebook.MIN_RUN_SECONDS if len(m.kills) > 1 else 0.0
            return math.ceil(max(min_gap, own) / max(dt, 1e-3) - 1e-6) * dt
        room = end_at - tail_s - first0 + dt
        if sum(need(m) for m in pool) > room + 1e-6:
            pool = rulebook.select_fit(all_moments, room, need)
            spare = [m for m in all_moments if m not in pool]
            room_full = True
            notes.append(f"The part you chose holds {len(pool)} of the {len(all_moments)} moments even with "
                         f"their kills as close as {min_gap:.2f} s; the weakest were left out.")
    if arrangement["arrange"] == "hits" and song and grid.hits:
        # BEST ORDER needs to know how big each slot's hit is before it can
        # put the biggest moments on the biggest ones. The slots are worked
        # out here as the cut will work them out below, from where the first
        # kill will land; a fold or a skipped mark can shift a later one by a
        # slot, which costs the heuristic a little and nothing else.
        #
        # What a slot is worth: how hard its hit is and how loud the song is
        # around it (the chorus against the verse), each RANKED across the
        # reel's own slots, plus a whole step for a big hit. Ranked because
        # the slots are already the loudest hit in each window: raw, they sit
        # within a few percent of each other and the big moments went nowhere
        # in particular (dwayIR: impact against hit, rho +0.08 for the build).
        #
        # A FLAT SONG IS NOT A SIGNAL, though. Aftrhrs is loud end to end --
        # every slot within 10% of the next -- and ranking that noise put its
        # biggest moments worse than the build did. Where a measure varies by
        # less than FLAT across the slots, the build's arc stands in for it.
        ts = kill_slots(first0, len(all_moments))
        has_s = len(grid.hit_strength) == len(grid.hits)
        arc = rulebook.arc_weights(len(ts))

        def ranked_or_arc(xs: list[float]) -> list[float]:
            lo, hi = min(xs), max(xs)
            if hi - lo < rulebook.FLAT_SPREAD * max(abs(hi), 1e-6):
                lo_a, hi_a = min(arc), max(arc)
                return [(a - lo_a) / max(hi_a - lo_a, 1e-6) for a in arc]
            order_ = sorted(range(len(xs)), key=lambda i: xs[i])
            out = [0.0] * len(xs)
            for r, i in enumerate(order_):
                out[i] = r / max(1, len(xs) - 1)
            return out
        hit_s = [grid.hit_strength[min(range(len(grid.hits)), key=lambda j: abs(grid.hits[j] - t))]
                 if has_s else 0.0 for t in ts]
        loud = [energy(t - 1.0, t + 1.0) for t in ts]
        arrangement["slot_weights"] = [
            0.4 * a + 0.6 * b + (1.0 if any(abs(t - x) < 0.01 for x in grid.big) else 0.0)
            for a, b, t in zip(ranked_or_arc(hit_s), ranked_or_arc(loud), ts)]

    drop_count = 0
    if style.drop and drop_t is not None and song and grid.hits and not keep_all:
        # A BUILD AND DROP REEL HAS AS MANY SHOTS AS ITS SONG HAS SLOTS: a few in the
        # build, then one a beat. The walk below sizes shots by the style's own
        # length and settled Espresso's 21 s at 13 of 27 moments, so the drop ran
        # out of kills; here the strongest sequences are taken, whole, until every
        # slot has one.
        drop_count = len(kill_slots(first0, len(all_moments)))
        seqs: dict[int, list] = {}
        for m in all_moments:
            seqs.setdefault(m.group, []).append(m)
        took: list = []
        for s in sorted(seqs.values(), key=lambda s: (-max(x.strength for x in s), s[0].group)):
            if len(took) >= drop_count:
                break
            took += s
        pool = [m for m in all_moments if m in took]
        spare = [m for m in all_moments if m not in pool]
    picked = rulebook.order(pool, looks, opener_ok, **arrangement)
    lens, hero_set = plan_walk(picked)
    # Settle the count: add the next-best sequence while the walk falls short
    # of the phrase, drop the weakest middle one while it runs a shot over.
    # A drop needs its build: the fourth shot is the one on the drop.
    min_groups = 5 if style.drop else 3
    for _ in range(24 if target and not keep_all and not drop_count else 0):
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
    if target and len(picked) < len(all_moments) and not room_full:
        notes.append(f"{len(picked)} of {len(all_moments)} moments fill {target:.0f} s "
                     f"({int(round(target / (4 * beat)))} bars); the weakest were left out.")
    in_plan = {m.clip["path"] for m in picked}
    if keep_all and part_len and fill != "all":
        why_full = (f"The song part was full even with the kills {min_gap:.2f} s apart: "
                    f"the clips that went in were stronger.")
    elif fill == "part":
        why_full = "The song part was full: the clips that went in were stronger."
    else:
        why_full = ("Left out to fit the reel's length: the clips that went in were stronger. "
                    "\"Every clip I chose\" under How long puts it in.")
    left_out((m.clip["path"] for m in all_moments if m.clip["path"] not in in_plan), why_full)

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
    # NOTHING THAT BLURS THE KILL (F2, every style), unless the player chose it: a blur on
    # the kill hid three kills of the first That Acid render for seven frames each.
    if not (template and template.get("kill")):
        kept = [p for p in pools["kill"] if fam(p) not in KILL_BLURS]
        pools["kill"] = kept or pools["kill"]
        for s in shots:
            s["fx"] = [f for f in s["fx"] if fam(f) not in KILL_BLURS]
    _vary(shots, pools, style, seed, "all")
    rulebook.budget(shots, pools)
    mix_free = chosen_sets(template)
    clip_look = {m.clip["path"]: looks.get(m.group) for m in picked}
    def speed_ok(shot, speed):
        ps = pieces(speed, shot["duration"], shot["pre"], own=_own_after(shot))
        before = source_used(ps, shot["pre"])
        after = source_used(ps, shot["duration"]) - before
        return (before <= float(shot["kill"]) + 1e-6
                and float(shot["kill"]) + after <= float(shot.get("clip_seconds") or 0.0) + 1e-6)
    # THE CLIMAX STOPS TIME, and a fast-cut reel plays at real speed: one freeze and a
    # velocity ramp on the best shot is a second kind of effect and a late hit. Found on
    # headshot3, whose shot 20 came out with h02 and s04 in a reel built to have neither.
    if not fast:
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
    fills_part = fill == "part" and bool(part_len)
    if fills_part and shots:
        want_b = int(round(target / step))
        before_b = int(round(sum(s["duration"] for s in shots) / step))
        _lengthen_run_ups(shots, step, want_b)
        have_b = int(round(sum(s["duration"] for s in shots) / step))
        if have_b > before_b:
            notes.append(f"The clips were short of the part, so their kills got longer run-ups "
                         f"({(have_b - before_b) * step:.0f} s more in all, as far as each clip has "
                         f"footage and never over {rulebook.MAX_LEAD_UP_SECONDS:.0f} s).")
        if have_b < want_b and not (song and grid.hits):
            # With hits to cut to, the cut below decides the length; this is
            # said there, against what actually came out.
            notes.append(f"Your clips fill {have_b * step:.0f} s of the {target:.0f} s part, even with "
                         f"every kill given as much run-up as it can have, so the reel ends early. "
                         f"Add clips or choose a shorter part to fill it.")

    proj = {
        "version": VERSION, "name": name or f"{style.label} reel",
        "style": style.key, "format": fmt if fmt in SIZES else "landscape",
        "song": str(song or ""), "song_offset": 0.0,
        # WHERE THE BASS LANDS, in SONG seconds. Kept on the project because
        # the beat engine needs it at assemble time and finding it means
        # decoding the song, which is a thing to do once. Set HERE as well as
        # in apply_song because a reel planned with a song never goes through
        # apply_song at all -- and a first attempt left a literal None in this
        # dict below the computed one, so every reel's grid still started at
        # the first frame with no build and no punctuation into the drop.
        # Found by rendering a reel and reading the project back.
        # The drop of the stretch this reel plays when it knows one (see drop_in), else the
        # song's biggest. Both are "where the bass lands" and only the first is where THIS
        # reel's bass lands.
        "song_drop": (round(float(drop_t if drop_t is not None else grid.drop), 4)
                      if song and (drop_t is not None or getattr(grid, "drop", None)) else None),
        "intro": "i12" if build else style.intro,
        "outro": "e03" if style.outro == "e01" else style.outro, "grade": style.grade,
        "vignette": style.vignette, "overlays": list(style.overlays),
        "handle": "", "music_db": 0.0, "game_db": 6.0 if song else 0.0, "duck": True,
        "saturation": sat_trim,
        "beat": round(beat, 6), "step": round(step, 6),
        "shaping": tw, "arrange": arrangement["arrange"], "pins": arrangement["pins"],
        "hs_only": hs_only,
        # As asked, not as resolved: a rebuild with a new part should fill it
        # if the player never chose, and keep their choice if they did.
        "fill": asked_fill, "keep_all": keep_all,
        "seed": int(seed), "pools": pools, "shots": shots, "mix_free": sorted(mix_free),
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
        # A HIT A HAIR BEFORE THE OPENER'S RUN-UP ENDS IS STILL ITS HIT. The
        # run-up is whole beats, so it ends on a beat, and the hit on that
        # beat sits either side of it by a few milliseconds. Asked for "at or
        # after", ambiforcashlyrics missed the hit on bar 2's downbeat by 26 ms
        # (13.68 s against 13.706), took the off-beat one 0.6 s later, and had
        # to slow its opener to fill the extra time. A shorter run-up always
        # fits the footage the longer one did.
        first = _first_kill(grid.hits, [], earliest=floor + max(0.0, shots[0]["pre"] - FIRST_HIT_SLACK * step))
    if song and shots and grid.hits:
        last = spread_to(first, len(shots))
        spread = last is not None
        # A FILLED PART ENDS ON ITS END, NOT PAST IT. A shot whose mark comes
        # too soon after another's later kills takes the mark after (see
        # apply_marks), so the last shots can run past the last mark: on
        # dwayIR's 93 s part two of them did and were cut off by the part's
        # end. Aim the last kill earlier by what ran over and place again.
        # Never closer than min_gap: past that the shots that do not fit are
        # the part's to cut, below.
        floor_last = first + (len(shots) - 1) * min_gap
        hard_end = bool(part_len) and fill != "all"
        for attempt in range(5):
            slots = kill_slots(first, len(shots), last)
            pool_shots = copy.deepcopy(shots)
            order = list(range(len(pool_shots)))
            if style.drop and drop_t is not None:
                order, slots = clutch_take(pool_shots, slots, drop_t, part_start)
            trial = {**proj, "shots": [pool_shots[i] for i in order]}
            if style.drop and drop_t is not None:
                # AFTER THE DROP EACH SHOT OPENS HALF A BEAT BEFORE ITS KILL, so the
                # kill has the other half after it: a cut on the off-beat, the kill
                # on the beat. The hand-cut reel's 0.28 s / 0.30 s at 104 BPM.
                for s, t in zip(trial["shots"], slots):
                    if t > drop_t + 1e-6:
                        s["pre"] = round(drop_gap / 2, 5)
            got_notes = apply_marks(trial, [t - offset for t in slots])
            over = sum(s["duration"] for s in trial["shots"]) - (end_at - offset)
            if not hard_end or over <= 0.05 or attempt == 4:
                break
            if last is None:
                if not slots:
                    break
                last = slots[-1]
            if last <= floor_last + 1e-6:
                break
            last, spread = max(floor_last, last - over), True
        proj["shots"] = shots = trial["shots"]
        proj["song_offset"] = round(offset, 5)
        # The hits the kills were aimed at, kept in song seconds. Without them
        # the timeline could only redraw what a detector would pick *now*, at
        # its own default pace -- not the marks this reel was actually cut to,
        # which is the only set worth checking a kill against.
        proj["song_marks"] = [round(t, 4) for t in slots]
        notes += got_notes
        honest_captions(shots)
        if style.drop and drop_t is not None:
            # Which shot lands on the drop, read off where each kill really landed: a mark
            # can pass to the next shot (see apply_marks), so the slot's index is not the
            # shot's. It flashes once the effects are settled below.
            at, landed = 0.0, []
            for s in shots:
                landed.append(at + float(s["pre"]) + offset)
                at += float(s["duration"])
            near = min(range(len(landed)), key=lambda i: abs(landed[i] - drop_t)) if landed else None
            drop_shot = near if near is not None and abs(landed[near] - drop_t) < 0.05 else None
        big_on = sum(1 for t in slots if any(abs(t - b) < 0.01 for b in grid.big))
        what = grid.pattern or "bass hits"
        every = (slots[-1] - slots[0]) / (len(slots) - 1) if len(slots) > 1 else gap_style
        if spread and every > gap_style * 1.15:
            notes.append(f"{len(slots)} kills are spread over the part you chose, on the song's own "
                         f"{what}: a cut every {every:.1f} s, slower than {style.label}'s "
                         f"{gap_style:.1f} s because there are not enough kills to cut faster. "
                         f"Add clips to cut faster, or choose \"Every clip I chose\" under How long "
                         f"for a shorter reel at {style.label}'s pace"
                         + (f"; {big_on} kills are on a big hit." if big_on else "."))
        elif spread and every < gap_style * 0.87:
            notes.append(f"{len(slots)} kills land on the song's own {what}, closer together than "
                         f"{style.label}'s pace -- a cut every {every:.1f} s against {gap_style:.1f} s -- "
                         f"so that every kill fits"
                         + (f"; {big_on} of them on a big hit." if big_on else "."))
        else:
            notes.append(f"{len(slots)} kills land on the song's own {what}, a cut every "
                         f"{gap_style:.1f} s at {style.label}'s pace"
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
    calm_mix(shots, mix_free)
    if drop_shot is not None and drop_shot < len(shots) and DROP_FLASH not in shots[drop_shot]["fx"]:
        # THE DROP FLASHES WHITE, as the reference edits do on theirs: on the kill that
        # lands on it, on top of that kill's own effect. After the mix is held to two
        # kill effects, so the flash is not counted as one and spread to every other kill.
        shots[drop_shot]["fx"] = list(shots[drop_shot]["fx"]) + [DROP_FLASH]
        notes.append(f"The kill on the drop, {drop_t:.2f} s into the song, flashes white.")
    if style.drop and song and not grid.drop:
        notes.append("This song has no clear drop, so the reel is paced as a build without one.")

    # The reel cannot outlast the song -- or the part of it that was chosen.
    if song and part_len:
        proj["part_end"] = round(part_start + part_len, 5)
        before = [s["clip"] for s in proj["shots"]]
        # "Every clip I chose" runs on past the part's end; the song's is the limit.
        room = grid.seconds - part_start - 0.5
        notes += fit_to_part(proj, room if fill == "all" else min(part_len, room))
        kept_clips = {s["clip"] for s in proj["shots"]}
        left_out((c for c in before if c not in kept_clips),
                 "The song ends before this clip." if fill == "all" else "The song part ends before this clip.")
        have = sum(s["duration"] for s in proj["shots"])
        if fills_part and grid.hits and have < part_len - 4 * beat:
            notes.append(f"Your clips fill {have:.0f} s of the {part_len:.0f} s part, even with every "
                         f"kill given as much run-up as its footage allows, so the reel ends early. "
                         f"Add clips or choose a shorter part to fill it.")
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
    # Every kill of a clip that went in, and whether the reel shows it.
    shown: dict[str, list[float]] = {}
    for s in proj["shots"]:
        a, b = _span(s)
        shown.setdefault(s["clip"], []).extend(float(k) for k in s["kills"] if a - 1e-3 <= float(k) <= b + 1e-3)
    missing: dict[str, list[dict]] = {}
    for c in chosen:
        if c["path"] not in in_reel:
            continue
        for k in c.get("kills") or []:
            if not any(abs(float(k) - x) < 0.01 for x in shown.get(c["path"], [])):
                missing.setdefault(c["path"], []).append(
                    {"kill": round(float(k), 3),
                     "why": kill_why.get((c["path"], k), "its shot ends before it")})
    if missing:
        n = sum(len(v) for v in missing.values())
        reasons = sorted({x["why"] for v in missing.values() for x in v})
        notes.append(f"{n} kill(s) in clips that went in are not shown: {'; '.join(reasons)}."
                     + ("" if keep_all else " \"Keep every kill\" puts them in."))
    proj["selection"] = [{"clip": c["path"], "name": str(c.get("name") or Path(c["path"]).stem),
                          "why": "" if c["path"] in in_reel else
                          why_out.get(c["path"], "Left out to fit the reel's length."),
                          **({"kills_out": missing[c["path"]]} if c["path"] in missing else {})}
                         for c in offered]
    return proj, notes


_MARK_CACHE: dict[tuple, list[float] | None] = {}

# KILL CHECKS KEPT ACROSS RESTARTS. A Build and drop plan from 48 clips spent 91 of
# its 131 s reading kill emblems (killmark.marks) and most of the rest finding when
# each first shows -- the same answer every time the same file is read, and read
# again after every restart, which every update is. Kept on disk once the app says
# where (use_check_cache; nothing is written until it does, so a test or a script
# never touches the player's folders), keyed by the file's path, size and time.
# Bump KILL_CHECKS_VERSION whenever what killmark or kill_clarity reads changes.
KILL_CHECKS_VERSION = 1
KILL_CHECKS_FILE = "kill-checks.json"
KILL_CHECKS_MAX = 20000


class _CheckDisk:
    def __init__(self):
        self.path: Path | None = None
        self.data: dict | None = None
        self.lock = threading.Lock()

    def use(self, path) -> None:
        with self.lock:
            p = Path(path) if path else None
            if p != self.path:
                self.path, self.data = p, None

    def _loaded(self) -> dict:
        if self.data is None:
            got = {}
            try:
                raw = json.loads(self.path.read_text("utf-8"))
                if raw.get("version") == KILL_CHECKS_VERSION and isinstance(raw.get("entries"), dict):
                    got = raw["entries"]
            except (OSError, ValueError, AttributeError):
                pass
            self.data = got
        return self.data

    @staticmethod
    def key(kind: str, path: str, extra="") -> str | None:
        try:
            st = Path(path).stat()
        except OSError:
            return None
        return f"{kind}|{Path(path).resolve()}|{st.st_size}|{st.st_mtime:.3f}|{extra}"

    def get(self, key: str | None):
        """(True, value) when this was read before, else (False, None)."""
        with self.lock:
            if self.path is None or key is None:
                return False, None
            d = self._loaded()
            return (True, d[key]) if key in d else (False, None)

    def put(self, key: str | None, value) -> None:
        with self.lock:
            if self.path is None or key is None or value is None:
                return                    # an unread answer is read again next time
            d = self._loaded()
            d[key] = value
            if len(d) > KILL_CHECKS_MAX:
                for k in list(d)[:len(d) // 2]:
                    d.pop(k, None)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_name(self.path.name + ".tmp")
                tmp.write_text(json.dumps({"version": KILL_CHECKS_VERSION, "entries": d}), "utf-8")
                tmp.replace(self.path)
            except OSError as e:          # a cache that cannot be written is only slower
                log.info("studio: kill checks not kept on disk: %s", e)


_CHECK_DISK = _CheckDisk()


def use_check_cache(path) -> None:
    """Keep kill checks in this file across restarts; None keeps them in memory only."""
    _CHECK_DISK.use(path)


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
    dk = _CheckDisk.key("marks", path, game)
    hit, got = _CHECK_DISK.get(dk)
    if not hit:
        ff = binary("ffmpeg")
        got = killmark.marks(Path(path), game, ff) if ff else None
        _CHECK_DISK.put(dk, got)
    with _ACTION_LOCK:
        if len(_MARK_CACHE) > 2000:
            _MARK_CACHE.clear()
        _MARK_CACHE[key] = got
    return got


_GLYPH_CACHE: dict[tuple, float | None] = {}


def kill_appearance(path: str, game: str, near: float) -> float | None:
    """When the game's kill emblem FIRST shows, nearest `near`, in clip seconds. Cached.

    The moment a viewer sees the kill. See killmark.appearance for why this and
    not the time a clip was marked at, and not the emblem ring's onset either.
    None when the game draws none, there is none in reach, or it cannot be read.
    """
    from . import killmark
    from .tools import binary

    if killmark.spec_for(game) is None:
        return None
    try:
        key = (str(path), Path(path).stat().st_mtime, round(float(near), 2))
    except OSError:
        return None
    with _ACTION_LOCK:
        if key in _GLYPH_CACHE:
            return _GLYPH_CACHE[key]
    dk = _CheckDisk.key("appear", path, f"{game}|{round(float(near), 2)}")
    hit, got = _CHECK_DISK.get(dk)
    if not hit:
        ff = binary("ffmpeg")
        got = killmark.appearance(Path(path), game, float(near), ff) if ff else None
        _CHECK_DISK.put(dk, got)
    with _ACTION_LOCK:
        if len(_GLYPH_CACHE) > 4000:
            _GLYPH_CACHE.clear()
        _GLYPH_CACHE[key] = got
    return got


def plan_checks() -> dict:
    """The four checks a plan makes of its footage, ready to hand to plan().

    Every caller that builds a reel needs the SAME four -- how much moves around
    a kill (`measure`), the game's kill emblem (`confirm`), whether it was a
    team-mate's seen while spectating (`theirs`), and the first frame of the
    emblem (`refine`) -- and the web page was the only one passing them. A reel
    planned from anywhere else (a script, a test, the next feature) was cut from
    raw times, which are early by 0.4 s in one clip and late by 0.7 s in
    another. Without ffmpeg there is nothing to check with, and the plan is
    made without them, as it always was.
    """
    from .. import clips as clips_mod

    if not clips_mod.available():
        return {}
    return {"measure": action, "confirm": kill_marks, "theirs": spectated,
            "refine": kill_appearance}


# CAN THE KILL BE SEEN. A kill label says a kill happened, not that the picture
# shows it: two kills in the reviewed That Acid render were taken through a
# flash -- the whole screen one flat beige or green -- and read as the edit
# blurring them. The middle of the picture's detail (the variance of its
# Laplacian, the middle 60 % at 480x270, median of the six frames from just
# before the kill) measured 27 and 115 on those two and 190-1380 on the 29 other
# kills of the reel. Under CLEAR_MIN the kill is not one to cut to.
CLEAR_MIN = 150.0
_CLEAR_CACHE: dict[tuple, float | None] = {}


def kill_clarity(path: str, t: float) -> float | None:
    """How much detail the picture has at a kill (see CLEAR_MIN); None if it cannot be read. Cached."""
    import numpy as np
    from .tools import binary

    try:
        key = (str(path), Path(path).stat().st_mtime, round(float(t), 3))
    except OSError:
        return None
    with _ACTION_LOCK:
        if key in _CLEAR_CACHE:
            return _CLEAR_CACHE[key]
    dk = _CheckDisk.key("clear", path, round(float(t), 3))
    hit, got = _CHECK_DISK.get(dk)
    if hit:
        with _ACTION_LOCK:
            _CLEAR_CACHE[key] = got
        return got
    got = None
    try:
        raw = subprocess.run(
            [binary("ffmpeg"), "-v", "error", "-nostdin", "-ss", f"{max(0.0, t - 0.05):.3f}", "-i", str(path),
             "-frames:v", "6", "-vf", "scale=480:270,crop=288:162:96:54,format=gray", "-f", "rawvideo", "-"],
            capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        v = np.frombuffer(raw, np.uint8)
        if v.size >= 162 * 288:
            v = v[:v.size // (162 * 288) * 162 * 288].reshape(-1, 162, 288).astype(np.float32)
            lap = [float(np.var(f[1:-1, 1:-1] * 4 - f[:-2, 1:-1] - f[2:, 1:-1] - f[1:-1, :-2] - f[1:-1, 2:]))
                   for f in v]
            got = float(np.median(lap))
    except (OSError, subprocess.SubprocessError, ValueError):
        got = None
    _CHECK_DISK.put(dk, got)
    with _ACTION_LOCK:
        if len(_CLEAR_CACHE) > 4000:
            _CLEAR_CACHE.clear()
        _CLEAR_CACHE[key] = got
    return got


def spectated(path: str, game: str, t: float) -> bool:
    """Whether the emblem at clip time t is a team-mate's, seen while spectating. See killmark.spectating."""
    from . import killmark
    from .tools import binary

    ff = binary("ffmpeg")
    return bool(ff and killmark.spectating(Path(path), t, game, ff))


# A glyph further than this from the time a kill was marked at is a different kill's.
REFINE_REACH = 1.2


def _refine_kills(clips: list[dict], refine) -> tuple[list[dict], dict]:
    """Every kill moved onto the first frame of its emblem, where one can be read.

    -> (clips, {"seen": kills with a glyph, "total": kills asked, "moved": kills
    that moved more than a frame, "shifts": the signed moves}). A kill with no
    glyph in reach keeps the time it had.
    """
    from concurrent.futures import ThreadPoolExecutor

    jobs = [(i, j, float(k)) for i, c in enumerate(clips)
            for j, k in enumerate(c.get("kills") or [])]
    if not jobs:
        return clips, {"seen": 0, "total": 0, "moved": 0, "shifts": []}

    def one(job):
        i, _j, k = job
        c = clips[i]
        try:
            return refine(c["path"], c.get("game") or "", k)
        except Exception:                                   # noqa: BLE001
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        found = list(pool.map(one, jobs))
    new = {i: list(c.get("kills") or []) for i, c in enumerate(clips)}
    seen = 0
    shifts: list[float] = []
    for (i, j, k), a in zip(jobs, found):
        if a is None or abs(a - k) > REFINE_REACH:
            continue
        seen += 1
        if abs(a - k) > 1.0 / FPS:
            shifts.append(round(a - k, 3))
        new[i][j] = round(float(a), 3)
    out = []
    for i, c in enumerate(clips):
        if new[i] == list(c.get("kills") or []):
            out.append(c)
            continue
        d = dict(c, kills=new[i])
        # The headshot readings follow the kills they are about, by place.
        if c.get("_hs_times") is not None and len(c["_hs_times"]) == len(new[i]):
            d["_hs_times"] = list(new[i])
        out.append(d)
    return out, {"seen": seen, "total": len(jobs), "moved": len(shifts), "shifts": shifts}


def _confirm_kills(clips: list[dict], confirm, theirs=None) -> tuple[list[dict], int, int, int]:
    """Clips with their kills moved onto the game's emblems. -> (clips, moved, dropped, added)

    A clip whose every kill turned out to have no emblem is left out: there is
    no kill in it to show. A clip whose kills came from Riot's match record is
    never dropped from or added to -- two kills half a second apart share one
    emblem, and the check would drop the second -- but each of its kills is
    moved onto its own emblem when one is close. See _snap_recorded.
    """
    from concurrent.futures import ThreadPoolExecutor

    from . import killmark

    # A clip the job already confirmed is not decoded again: on a MacBook Air that
    # whole-clip read was most of a minute-long plan, and it finds the same emblems.
    def one(c):
        return None if c.get("emblems") else confirm(c["path"], c.get("game") or "")
    with ThreadPoolExecutor(max_workers=4) as pool:
        found = list(pool.map(one, clips))
    # RIOT'S TIME IS NOT THE MOMENT ON SCREEN. A recorded kill is the server's
    # clock lined up with the video, and measured on Aftrhrs it sat -0.17 to
    # +0.53 s from the kill emblem the viewer sees (median +0.13): a story
    # reel, which has no punch on the kill to hide it, landed the visible kill
    # off its beat. So each recorded kill moves onto its own emblem when one is
    # close -- one emblem per kill, nothing dropped, nothing added, which keeps
    # the reason recorded clips were skipped (two kills half a second apart
    # sharing one emblem must not lose the second).
    out, moved, dropped, added = [], 0, 0, 0
    # Whether the HUD shows the emblem at all is a property of a RUN, not of a
    # clip: a run in which no clip shows one keeps its kills, while a clip with
    # no emblem in a run that shows them has no kill (checked by eye).
    shows = {c.get("folder") or Path(c["path"]).parent.parent.name
             for c, m in zip(clips, found) if m}
    for c, marks in zip(clips, found):
        if c.get("emblems"):
            out.append(c)
            continue
        if c.get("recorded"):
            ks, n = _snap_recorded([float(k) for k in c.get("kills") or []], marks or [])
            moved += n
            out.append(dict(c, kills=ks) if n else c)
            continue
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


# How far from Riot's time a recorded kill's emblem may be and still be ITS
# emblem. Measured on Aftrhrs's 22 recorded kills: 19 of 21 emblems sat inside
# this; the two outside (-0.87, +1.24) were a neighbouring kill's.
SNAP_BEFORE = 0.35
SNAP_AFTER = 0.70


def _snap_recorded(kills: list[float], emblems: list[float]) -> tuple[list[float], int]:
    """Each recorded kill on its own nearby emblem, one emblem per kill. -> (kills, moved)

    Nearest pairs first, so two kills close together each get the emblem that
    is theirs rather than the first one taking the second's.
    """
    pairs = sorted((abs(e - k), i, j) for i, k in enumerate(kills) for j, e in enumerate(emblems)
                   if -SNAP_BEFORE <= e - k <= SNAP_AFTER)
    got: dict[int, float] = {}
    used: set[int] = set()
    for _d, i, j in pairs:
        if i in got or j in used:
            continue
        got[i] = emblems[j]
        used.add(j)
    out = [round(got.get(i, k), 3) for i, k in enumerate(kills)]
    moved = sum(1 for a, b in zip(out, kills) if abs(a - b) > 0.02)
    return sorted(out), moved


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
    # A pool that is only hard cuts is a reel that asked for one transition -- a fast-cut
    # reel -- and a white flash on a share of its cuts would be a second.
    flash_share = 0.0 if set(trans) <= {"t01"} else _flash_share(style)
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
    asked = seed is not None
    if seed is None:
        seed = (int(project.get("seed") or 0) * 1103515245 + 12345) & 0x7FFFFFFF
    kind = what if what in (*POOL_KINDS, "all") else "all"

    def mix_of(shots):
        return [(s.get("transition"), tuple(s.get("fx") or ()), s.get("camera"), s.get("speed"),
                 tuple(s.get("hero_fx") or ())) for s in shots]
    was = mix_of(project["shots"])
    start = copy.deepcopy(project["shots"])
    # "MIX AGAIN" THAT CHANGES NOTHING READS AS A BROKEN BUTTON. Held to two kill
    # effects and one transition beside the hard cut (calm_mix), a fresh draw can
    # land on exactly the mix the reel already had -- the transitions above all,
    # where the flashes sit where the music puts them. So a draw that changed
    # nothing is drawn again with the next seed, a few times. An explicit seed is
    # a request for that draw and is kept as it comes.
    for _ in range(1 if asked else 6):
        project["shots"] = copy.deepcopy(start)
        project["seed"] = int(seed)
        _vary(project["shots"], pools, style, seed, kind)
        rulebook.budget(project["shots"], pools, what if what in POOL_KINDS else None)
        calm_mix(project["shots"], set(project.get("mix_free") or ()), keep_cuts=what == "kill")
        if mix_of(project["shots"]) != was:
            break
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
    return project


# NEVER TOO MANY KINDS OF EFFECT IN ONE REEL (asked 2026-10-17). A style's pools
# hold seven transitions and ten kill effects so that reels differ from each
# other; drawn shot by shot, they also made every reel a sampler -- the player's
# words: "never use too much mixed transition effects". So a reel keeps the hard
# cut and ONE other transition, and its TWO most used kill effects; every other
# draw becomes one of those. A set the player picked on the Make page is theirs
# and is left as it is.
MAX_TRANSITIONS = 2         # the hard cut, and one other
MAX_KILL_FX = 2


def chosen_sets(template: dict | None) -> set[str]:
    """The drawers a template picks more than one part for -- a mix the player asked for."""
    out = set()
    for kind in POOL_KINDS:
        if len(set(_picked((template or {}).get(kind), kind))) > 1:
            out.add(kind)
    return out


def calm_mix(shots: list[dict], free: set[str] | tuple = (), keep_cuts: bool = False) -> None:
    """Hold a reel to MAX_TRANSITIONS transitions and MAX_KILL_FX kill effects. In place."""
    from collections import Counter

    if "transition" not in free:
        others = Counter(s.get("transition") for s in shots[1:] if s.get("transition") not in (None, "", "t01"))
        keep = {t for t, _ in others.most_common(MAX_TRANSITIONS - 1)}
        for s in shots[1:]:
            if s.get("transition") not in keep:
                s["transition"], s["tlen"] = "t01", 0.0
    if "kill" not in free:
        used = Counter(f for s in shots for f in (s.get("fx") or []))
        keep = [f for f, _ in used.most_common(MAX_KILL_FX)]
        last = ""
        for s in shots:
            fx = list(s.get("fx") or [])
            if not fx:
                continue
            kept = list(dict.fromkeys(f for f in fx if f in keep))
            if not kept or kept[0] == last:
                # Still never the same effect twice running (see _vary): with two to
                # choose from, the other one -- the reel alternates rather than repeats.
                other = [f for f in keep if f != last]
                kept = [other[0]] if other else keep[:1]
            s["fx"] = kept
            last = kept[0]
    # A white cut straight into a bright kill is one flash on top of another; the
    # transitions keep them apart (rulebook.transitions), and the effects changed
    # since may have brought them together again. The cut gives way.
    # Mixing only the kill effects leaves the cuts as they are, so there the effect
    # gives way instead: a kept effect that is not bright, or the plain punch.
    for s in shots[1:]:
        if (s.get("transition") == "t02" and set(s.get("fx") or ()) & set(rulebook.BRIGHT_KILL)
                and float(s.get("pre") or 0.0) < rulebook.BRIGHT_GAP):
            if keep_cuts:
                calm = [f for f in dict.fromkeys(f for x in shots for f in (x.get("fx") or []))
                        if f not in rulebook.BRIGHT_KILL]
                s["fx"] = [calm[0] if calm else "k01"]
            else:
                s["transition"], s["tlen"] = "t01", 0.0


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
    own = _own_after(shot)

    def fits(post: float) -> bool:
        ps = pieces(shot["speed"], pre + post, pre, own=own)
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


CUT_LEAD = 3.0 / FPS        # how far a cut lands before the hit its kill is on; see apply_marks


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
    floor = after_floor(project)

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
    led: set[int] = set()
    for s in shots:
        s.pop("stretch", None)              # the marks decide every stretch afresh
        # A RUN-UP LED ONCE IS NOT LED AGAIN. The CUT_LEAD below is added to
        # the run-up the shot came in with, so laying the marks on twice -- a
        # shot removed, then another -- led every cut a second time and the
        # run-ups crept 50 ms per edit. Measured on 4Raws-X-valorant-B: 38 of
        # 39 shots moved when marks it was already on were laid on again.
        if s.pop("led", False):
            led.add(id(s))
    if len(shots) > 1 and max_pre(shots[0], marks[0]) < marks[0] - slack             and not stretch_to(dict(shots[0]), marks[0]):
        lead = 1
    if len(shots) - lead <= 0:
        return notes
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
    folded = skipped = early = 0
    j, mi = lead, 0                                    # the next shot, and the next mark
    while j < len(shots) and mi < len(marks):
        s = shots[j]
        k = marks[mi]
        if j == 0:
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
            j, mi = j + 1, mi + 1
            continue
        prev = shots[j - 1]
        prev_kill = cuts[j - 1] + pres[j - 1]          # where the shot before lands its kill
        gap = k - prev_kill
        # THE SAME FOOTAGE NEVER PLAYS TWICE. A follow-up from the same clip
        # whose kill is closer to the one before in the footage than the
        # marks are apart can only meet its mark by replaying what the shot
        # before has just shown. Measured on Aftrhrs: a quadra's first two
        # kills 1.90 s apart, on marks 4.40 s apart -- the opener ran on past
        # the second kill to its cut, and the follow-up started 2.20 s back
        # inside that and showed the second kill again. So it is folded into
        # the shot before -- one shot, both kills, the footage as it happened
        # -- and the mark passes on to the shot after it.
        if (s["clip"] == prev["clip"] and float(s["kill"]) > float(prev["kill"]) + 1e-6
                and gap > float(s["kill"]) - float(prev["kill"]) + 1.0 / FPS
                and min(float(x) for x in s["kills"]) - (float(prev["kill"]) + _own_after(prev) - OWN_KILL_HOLD)
                <= OWN_KILLS_WITHIN):
            _fold(prev, shots.pop(j))
            folded += 1
            continue
        # THE SHOT BEFORE KEEPS ITS OWN KILLS. A double kill is one shot with
        # its second kill 0.8 s after the first; this shot's run-up used to be
        # allowed everything but 0.22 s of the gap, and on ambiforcashlyrics a
        # run-up grown to 4.08 s cut the opener 0.51 s after its first kill --
        # its second was never seen.
        keep = max(floor, _own_tail(prev, pres[j - 1]))
        if keep > floor and gap - keep < rulebook.MIN_RUN_SECONDS:
            # ...and when the next mark comes too soon after them for this
            # shot to have any run-up at all, it takes the mark after. On
            # Aftrhrs a triple's tail needed 2.75 s and the next mark was
            # 2.20 s on: the third kill was cut off and the next shot opened
            # on its own kill with no fight before it.
            if mi + 1 < len(marks):
                mi += 1
                skipped += 1
                continue
            break                                      # no mark left: it follows at its own length
        asked = float(s["pre"]) - (CUT_LEAD if id(s) in led else 0.0)
        want = min(asked if asked > 0 else gap / 2, max(0.0, gap - keep))
        pre = max_pre(s, want)
        cut = k - pre
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
        cut = max(cut, prev_kill + 1.0 / FPS)
        if s["clip"] == prev["clip"] and float(s["kill"]) > float(prev["kill"]) + 1e-6:
            # The same rule for a follow-up too far on to fold: where the shot
            # before would still be playing footage this one starts in, the
            # cut moves to where they meet and this kill lands early instead.
            # A kill off its mark is a lesser fault than a kill seen twice.
            fz = _freeze_of(prev)
            ps_prev = pieces(prev["speed"], cut - cuts[j - 1], pres[j - 1], own=_own_after(prev))
            shown_to = float(prev["kill"]) + source_used(ps_prev, max(pres[j - 1], cut - cuts[j - 1] - fz)) \
                - source_used(ps_prev, pres[j - 1])
            starts = float(s["kill"]) - source_used(shot_pieces(s, 60.0 + pre, k - cut), k - cut)
            if shown_to > starts + 1.0 / FPS:
                meet = min(float(s["kill"]), max(starts, float(prev["kill"]) + _own_after(prev)))
                s.pop("stretch", None)
                cut = prev_kill + _post_for(prev, pres[j - 1], meet - float(prev["kill"])) + fz
                cuts.append(cut)
                pres.append(_pre_for(s, float(s["kill"]) - meet))
                early += 1
                j, mi = j + 1, mi + 1
                continue
        cuts.append(cut)
        pres.append(k - cut)
        j, mi = j + 1, mi + 1
    done = len(cuts)                                   # shots that were placed
    # THE CUT ARRIVES A LITTLE BEFORE THE HIT, THE KILL ON IT. Measured on 245
    # cuts in 11 public reference edits, an editor's cut lands a median 46 ms
    # before the bass peak this module puts kills on (IQR 84 ms) -- about three
    # frames. The player's own 662 kill marks sit 17 ms AFTER the same peaks, so
    # moving the hits earlier cost 6-14% of the marks; the two agree once the
    # kill stays on the hit and only the cut leads it. Each cut after the first
    # moves CUT_LEAD earlier where this shot has the footage before its kill
    # and the shot before keeps everything it was owed after its own.
    for i in range(1, done):
        s = shots[i]
        want = pres[i] + CUT_LEAD
        if s.get("stretch") or max_pre(s, want) < want - 1e-6:
            continue
        owed = max(floor, _own_tail(shots[i - 1], pres[i - 1]))
        if cuts[i] - CUT_LEAD < cuts[i - 1] + pres[i - 1] + owed - 1e-6:
            continue
        cuts[i] -= CUT_LEAD
        pres[i] = want
        s["led"] = True
    if mi < len(marks):
        notes.append(f"{len(marks)} kills were marked but the reel has {len(shots) - lead} shots to "
                     f"put on them; the last {len(marks) - mi} marks were not used.")
    if folded:
        notes.append(f"{folded} follow-up shot(s) were the same footage as the shot before, closer "
                     f"than the marks are apart, so each became part of that shot rather than "
                     f"showing its kill twice.")
    if skipped:
        notes.append(f"{skipped} mark(s) came too soon after a shot's own later kills to cut on; "
                     f"the next shot took the mark after instead.")
    if early:
        notes.append(f"{early} kill(s) land before their mark: reaching it would have replayed "
                     f"footage the shot before had just shown.")
    for s in shots:
        s.pop("lead_in", None)
    if lead:
        shots[0]["lead_in"] = True
    for s in shots[done:]:
        if id(s) in led:
            s["led"] = True                 # not placed, so its run-up is still the led one
    for i in range(done):
        s = shots[i]
        s["pre"] = round(pres[i], 5)
        if i < done - 1:
            s["duration"] = round(cuts[i + 1] - cuts[i], 5)
        else:
            post = max(floor, float(s["duration"]) - float(s["pre"]) if s["duration"] > s["pre"] else 0.5)
            post = max(post, _own_tail(s, pres[i]))
            s["duration"] = round(pres[i] + post, 5)
    return notes


def _fold(into: dict, follow: dict) -> None:
    """Make `follow`, a later moment of the same clip, part of the shot `into`. In place.

    The kills join; the caption and the hero treatment go with whichever had
    them, since the follow-up is usually the sequence's last shot and so the
    one captioned DOUBLE or QUADRA KILL.
    """
    into["kills"] = sorted({round(float(x), 3) for x in list(into["kills"]) + list(follow["kills"])})
    if follow.get("caption") and not into.get("caption"):
        into["caption"] = follow["caption"]
    if follow.get("hero") and not into.get("hero"):
        into["hero"] = True
        into["hero_fx"] = list(follow.get("hero_fx") or [])


# A shot's own later kills -- the rest of a double or a triple -- are the ones
# that follow its main kill each within this many seconds of the one before
# (see _own_after), and the last is held this long after it lands so its
# emblem is seen, not just begun.
OWN_KILLS_WITHIN = 3.0
OWN_KILL_HOLD = 0.35


def _own_tail(shot: dict, pre: float) -> float:
    """Reel seconds after the main kill needed to show the shot's own later kills.

    0 when it has none. Never more than its footage after the kill allows.

    A FREEZE ON THE KILL COMES OUT OF THIS TAIL, so it is added to it. On
    Aftrhrs the climax quadra froze 0.75 s on its third kill inside a tail of
    1.10 s: 0.11 s of footage played after the freeze and the fourth kill,
    0.83 s on, never appeared.
    """
    want_src = _own_after(shot)
    if not want_src:
        return 0.0
    return _post_for(shot, pre, want_src) + _freeze_of(shot)


def _post_for(shot: dict, pre: float, src: float) -> float:
    """Output seconds after the kill that play `src` seconds of footage past it.

    Capped at what the clip has after the kill.
    """
    own = _own_after(shot)

    def src_after(post: float) -> float:
        ps = pieces(shot["speed"], pre + post, pre, own=own)
        return source_used(ps, pre + post) - source_used(ps, pre)
    lo, hi = 0.0, 4.0 * src + 1.0               # slow-motion after a kill plays it at no less than 1/4
    if src_after(hi) < src:
        return max_post(shot, pre, hi)
    for _ in range(40):
        mid = (lo + hi) / 2
        if src_after(mid) >= src:
            hi = mid
        else:
            lo = mid
    return max_post(shot, pre, hi)


def _pre_for(shot: dict, src: float) -> float:
    """The run-up, in output seconds, that starts `src` seconds of footage before the kill."""
    src = max(0.0, min(float(src), float(shot["kill"])))
    lo, hi = 0.0, 4.0 * src + 1.0
    big = hi + 10.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if source_used(pieces(shot["speed"], big, mid), mid) >= src:
            hi = mid
        else:
            lo = mid
    return hi


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
        notes.append(f"The part of the song the reel plays holds {len(kept)} shots; "
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
    project["song_drop"] = (round(float(shape.drop), 4)
                            if getattr(shape, "drop", None) else None)
    part = (min(float(end), shape.seconds) - start) if end and end > start else shape.seconds - start
    # THE PART IS KEPT. Chosen here it was used once and forgotten: part_end
    # was written only by the planner, so the Song tab reopened on the reel's
    # length and a rebuild or a new style planned to the style's length again.
    # dwayIR is that: its song_offset is 6.9458, to the four places only this
    # function rounds to, so a part was chosen here -- and it has no end.
    project["part_end"] = round(start + part, 5)
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
        # A tenth of a millisecond, not a microsecond: apply_marks stores a
        # cut to 5 decimals, a 2.2x ramp multiplies that rounding, and a shot
        # cut exactly to its footage read 5 us over it -- so a whole beat came
        # off its tail and every kill after it in Aftrhrs's best order slid
        # 0.55 s off its mark (17 of 43 on marks instead of 43).
        ok_head = kill - before >= -1e-4
        ok_tail = kill + after <= dur_clip + 1e-4
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


def _pos(v, default=(0.0, 0.0)) -> list[float]:
    try:
        x, y = (float(n) for n in v)
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError
    except (TypeError, ValueError):
        x, y = default
    return [round(max(0.0, min(1.0, x)), 4), round(max(0.0, min(1.0, y)), 4)]


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


def tidy_locks(shots: list[dict]) -> None:
    """A lock holds two or more shots side by side; anything else is not one. In place.

    A shot moved out of the middle of a locked run, or a run cut down to one shot,
    leaves a lock that no longer joins anything -- and a lock id that turns up in
    two separate runs keeps only its first.
    """
    runs: dict[str, list[tuple[int, int]]] = {}
    i = 0
    while i < len(shots):
        lk = shots[i].get("lock")
        j = i
        while lk and j + 1 < len(shots) and shots[j + 1].get("lock") == lk:
            j += 1
        if lk:
            runs.setdefault(lk, []).append((i, j))
        i = j + 1
    for lk, spans in runs.items():
        keep = next((sp for sp in spans if sp[1] > sp[0]), None)
        for a, b in spans:
            if (a, b) != keep:
                for k in range(a, b + 1):
                    shots[k].pop("lock", None)


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
        # Where the handle sits, as a fraction of the room the frame leaves it:
        # 0,0 is the top-left corner and 1,1 the bottom-right, which is where
        # it always was before it could be moved.
        "handle_pos": _pos(project.get("handle_pos"), (1.0, 1.0)),
        # How the footage fills the frame: "zoom" crops it to fill (what a
        # vertical reel always did), "fit" shows all of it over a blurred copy.
        "vfit": project.get("vfit") if project.get("vfit") in VFITS else "zoom",
        # Seconds the ending takes, 0 for the style's own. A longer one holds
        # the last frame, easing in, while the picture and the song fade.
        "outro_len": round(_num(project.get("outro_len"), 0.0, 8.0, 0.0), 2),
        "cam": facecam.settings(project.get("cam")),
        "music_db": _num(project.get("music_db"), -30, 12, 0.0),
        "game_db": _num(project.get("game_db"), -30, 12, 0.0),
        "duck": bool(project.get("duck", True)),
        "saturation": round(_num(project.get("saturation"), 0.3, 1.5, 1.0), 3),
        "kill_sound": bool(project.get("kill_sound", True)),
        # The song's own words over the reel, in one of five looks; off by default.
        "lyrics": lyrics_mod.settings(project.get("lyrics")),
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
    arranged = _arrangement({"arrange": project.get("arrange"), "pins": project.get("pins"),
                             "hs_only": project.get("hs_only"), "fill": project.get("fill"),
                             "keep_all": project.get("keep_all")})
    out["arrange"], out["pins"] = arranged["arrange"], arranged["pins"]
    out["hs_only"] = arranged["hs_only"]
    # How long and Keep every kill ride on the project too, so a rebuild or a
    # new style keeps what was asked for -- as the arrangement does.
    out["fill"], out["keep_all"] = arranged["fill"], arranged["keep_all"]
    # Drawers the player picked a SET for, which the mix cap leaves alone; see calm_mix.
    out["mix_free"] = [k for k in (project.get("mix_free") or []) if k in POOL_KINDS]
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
            # WHERE THE BASS LANDS, carried through. normalise rebuilds the
            # project from a whitelist, so a key it does not name is dropped --
            # which silently emptied this one on every reel between being set
            # and being read, and the beat engine started its grid at the first
            # frame with no build and no punctuation into the drop. Found by
            # rendering a reel and reading the project back, not by reading the
            # code that sets it.
            drop = project.get("song_drop")
            out["song_drop"] = (round(_num(drop, 0.0, 36000.0, 0.0), 4)
                                if drop is not None else None)
            # The groove the song's layers drive (fx_schedule), in song seconds.
            if (groove := fx_schedule.clamp(project.get("groove"))):
                out["groove"] = groove
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
        # WHERE THE EDITOR PUT A KILL. [[source seconds, output seconds], ...]
        # -- a kill of this clip, and where in this shot it must play. The
        # anchor kill itself is implied by `kill` and `pre` and is added by
        # `segments`; these are the OTHER kills, dragged onto a beat. Empty on
        # every reel nobody has dragged, which is how the speed part stays in
        # charge of a shot that was never touched.
        anchors = []
        for a in (raw.get("anchors") or [])[:12]:
            if not (isinstance(a, (list, tuple)) and len(a) == 2):
                continue
            src, out_t = _num(a[0], 0.0, cs, -1.0), _num(a[1], 0.0, 60.0, -1.0)
            if src >= 0 and out_t >= 0:
                anchors.append([round(src, 4), round(out_t, 4)])
        if anchors:
            shot["anchors"] = sorted(anchors, key=lambda a: a[1])
        # SHOTS LOCKED TOGETHER on the timeline (asked 2026-10-17): a run of shots
        # that move as one when the cut before them moves. Only the timeline reads
        # it; the render does not. Tidied below once every shot is in.
        lock = str(raw.get("lock") or "")
        if lock and re.fullmatch(r"[A-Za-z0-9_-]{1,16}", lock):
            shot["lock"] = lock
        if raw.get("led") is True:
            shot["led"] = True                  # see apply_marks: its cut was led

        before = (shot["pre"], shot["duration"], shot["speed"])
        _fit(shot, out["step"])
        if (shot["pre"], shot["duration"], shot["speed"]) != before:
            notes.append(f"{shot['name']}: trimmed to the footage the clip has.")
        out["shots"].append(shot)

    if not out["shots"]:
        raise ProjectError("There are no usable clips in this reel.")
    tidy_locks(out["shots"])

    # A SHOT TAKEN OUT OR MOVED CLOSES UP ON THE SONG'S HITS (chosen 2026-10-19).
    # The page only splices the list, so every shot after the change slid by
    # the length of the one that went: on 4Raws X valorant, removing a 1.90 s
    # opener left 2 of 40 kills on a hit. With `remark` the marks are laid back
    # on -- shot N takes mark N, so everything after moves up one hit and the
    # last hit goes unused. Asked for by that edit only: re-timing on every
    # check would undo every cut moved by hand.
    if project.get("remark") and out.get("song_marks"):
        offset = out["song_offset"]
        notes += apply_marks(out, [m - offset for m in out["song_marks"]])
        if out.get("part_end"):
            notes += fit_to_part(out, out["part_end"] - offset)

    # THE FACECAM FILE FOR EACH SHOT comes from the links the Facecam tab
    # made, never from the page: a link is only ever written with a path the
    # OS dialog returned, which is what makes a file outside the clips folder
    # safe to hand to ffmpeg here.
    if out["cam"]["source"] == "file":
        links = facecam.load(root)["links"]
        for shot in out["shots"]:
            got = facecam.for_clip(root, Path(shot["clip"]), links)
            if got:
                shot["cam_file"], shot["cam_offset"] = got[0], round(got[1], 4)
        if not any(s.get("cam_file") for s in out["shots"]):
            notes.append("No facecam video is attached to these clips, so the reel has no facecam.")

    # The clips that were chosen for this reel and why any are not in it: what
    # "Add clips" rebuilds from. Only for display and for a new plan, which
    # checks every path against the library again.
    sel = []
    for row in (project.get("selection") or [])[:MAX_SHOTS * 2]:
        if isinstance(row, dict) and str(row.get("clip") or ""):
            sel.append({"clip": str(row["clip"])[:1000],
                        "name": re.sub(r"[\r\n]", " ", str(row.get("name") or Path(str(row["clip"])).stem))[:120],
                        "why": re.sub(r"[\r\n]", " ", str(row.get("why") or ""))[:200]})
            # The kills of a clip that went in but are not shown, each with why.
            gone = row.get("kills_out") if isinstance(row.get("kills_out"), list) else []
            gone = [{"kill": round(_num(x.get("kill"), 0.0, 36000.0, 0.0), 3),
                     "why": re.sub(r"[\r\n]", " ", str(x.get("why") or ""))[:120]}
                    for x in gone[:40] if isinstance(x, dict)]
            if gone:
                sel[-1]["kills_out"] = gone
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
    """Source seconds the shot's own (handle-free) footage covers.

    A freeze on the kill replaces that much of what follows it, so the
    footage ends that much sooner.
    """
    ps = shot_pieces(shot)
    start = shot["kill"] - source_used(ps, shot["pre"])
    end = max(float(shot["pre"]), float(shot["duration"]) - _freeze_of(shot))
    return start, start + source_used(ps, end)


def _head_room(shot: dict) -> float:
    return max(0.0, _span(shot)[0])


def _tail_room(shot: dict) -> float:
    return max(0.0, float(shot["clip_seconds"]) - _span(shot)[1])


# Seconds after the last kill before a long ending may start fading.
OUTRO_AFTER_KILL = 0.6


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
        freeze = _freeze_of(s)
        inside = []
        for k in s["kills"]:
            if a - 1e-6 <= k <= b + 1e-6:
                later = freeze if k > float(s["kill"]) + 1e-6 else 0.0
                inside.append(round(t0 + output_at(ps, k - a) + later, 4))
        kills_reel.extend(inside)
        rows.append({"index": i, "start": round(t0, 5), "end": round(t0 + s["duration"], 5),
                     "kill_reel": round(t0 + s["pre"], 5), "kills_reel": inside,
                     "lead_in": bool(s.get("lead_in")),
                     "source_in": round(a, 4), "source_out": round(b, 4),
                     # The page's instant preview plays the clip files
                     # themselves, so it has to know where the render holds
                     # the kill's frame -- and that what follows plays this
                     # much later. See preview_at().
                     "freeze": round(freeze, 4),
                     "pieces": [[round(x, 4), round(y, 4), r] for x, y, r in ps]})
    # A LONGER ENDING NEVER FADES THE LAST KILL. The fade runs over the last
    # `outro_len` seconds, and where the last shot ends sooner after its kill
    # than that, the reel is held on its last frame for the difference.
    fade = float(project.get("outro_len") or 0.0) if project.get("outro") != "e12" else 0.0
    hold = 0.0
    if fade and rows:
        last_kill = max(rows[-1]["kills_reel"] or [rows[-1]["kill_reel"]])
        hold = round(max(0.0, last_kill + OUTRO_AFTER_KILL + fade - length), 4)
        length += hold
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
                  "why": "" if str(r["clip"]).lower() in in_reel else (r.get("why") or "Removed on the timeline."),
                  "kills_out": list(r.get("kills_out") or []) if str(r["clip"]).lower() in in_reel else []}
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
            "outro_hold": hold, "outro_fade": round(fade, 4),
            "edited": bool(project.get("plan_sig")) and signature(shots) != project.get("plan_sig")}


def preview_at(derived: dict, t: float) -> dict:
    """Which clip, and which second of it, the reel shows at reel time `t`.

    THE ARITHMETIC THE PAGE'S INSTANT PREVIEW RUNS, written once here so it
    can be tested against the renderer rather than trusted. The Studio plays
    the timeline straight off the clip files while the real render catches up
    (studio_pvAt in ui/studio.py is this function, line for line), so a
    deleted shot is gone from the player the moment it is deleted instead of
    twenty seconds later.

    -> {"shot", "src", "rate"}: the shot index, the source second to show,
    and the playback rate there -- 0 while a frame is held (a freeze on the
    kill, a stretched run-up's held opening, a long ending's last frame).
    shot is -1 when the reel has no shots.
    """
    rows = derived.get("shots") or []
    if not rows:
        return {"shot": -1, "src": 0.0, "rate": 0.0}
    t = max(0.0, float(t))
    i = 0
    while i + 1 < len(rows) and t >= rows[i + 1]["start"]:
        i += 1
    r = rows[i]
    dur = r["end"] - r["start"]
    u = t - r["start"]
    ps = [tuple(p) for p in r["pieces"]]
    # Where the kill sits in the shot's own output time: the render's freeze
    # starts there (segment_command loops the frame at kill_at).
    pre = r["kill_reel"] - r["start"]
    freeze = float(r.get("freeze") or 0.0)
    held = u >= dur                       # past the shot: the long ending's hold
    u = min(u, dur)
    if freeze and pre <= u < pre + freeze:
        return {"shot": i, "src": round(r["source_in"] + source_used(ps, pre), 4), "rate": 0.0}
    if freeze and u >= pre + freeze:
        u -= freeze
    rate = 0.0 if held else next((p[2] for p in ps if p[0] <= u < p[1]), ps[-1][2])
    if rate < PREVIEW_MIN_RATE:
        rate = 0.0
    return {"shot": i, "src": round(r["source_in"] + source_used(ps, u), 4), "rate": rate}


# Slower than this is a held frame, not slow motion: it is what HOLD_RATE is
# for, and it is also the slowest a browser will play (Chrome refuses
# playbackRate below 1/16).
PREVIEW_MIN_RATE = 0.0625


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
    if sys.platform == "darwin":
        from ..macos import fonts as _mac
        found = _mac.first(("bahnschrift.ttf", "arialbd.ttf", "arial.ttf", "segoeuib.ttf"))
        return "fontfile='" + found.replace(":", "\\:") + "':" if found else ""
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


def _clock(text: str) -> float | None:
    """`HH:MM:SS.ffffff` as seconds, or None for anything else.

    ffmpeg writes `N/A` here before the first frame lands, and keeps writing
    the key either way, so an unparseable value is ordinary rather than wrong.
    """
    parts = text.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


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


# THE BEAT ENGINE. Every other effect in this file keys off `kt`, the kill time
# of the shot it is in; this keys off the SONG'S GRID, independent of where
# kills fall, which is what lets a one-second shot carry two beats of effect.
#
# It lives in `assemble_command`'s post chain and not in a pass of its own. The
# specification recommends a separate encode of the joined body -- reasonable
# advice from outside the app, where there is no joined body to hang a filter
# on. Inside, the post chain already runs over exactly that, in absolute v-time,
# in the pass that was happening anyway. One encode, not two.
#
# Measured numbers: docs/STYLE-FAST-PACED-HEADSHOT.md section 8.
# WINDOWS THAT SIT BETWEEN FRAMES, not on one. The specification's 0.0167 and
# 0.0500 are exactly one and three frames at 60 fps, and a frame boundary is
# the worst place to put a threshold: measured, 0.0167 caught TWO frames
# (1/60 = 0.0166667, which is under it) and 0.0500 caught four, because the
# phase offset is a large number and `mod` gives it back a few picoseconds
# light. Half a frame either side costs nothing and cannot land on the edge.
FLIP_BEAT = 0.012             # one frame at 60 fps: between 0 and 1/60
FLIP_BAR = 0.045              # three: between 2/60 and 3/60
FLIP_GUARD = 2.5 / 60         # s: a kill this near a flip turns it into FLIP_PARTIAL for one frame
FLIP_PARTIAL = 0.28           # how much of the inverted picture shows in that frame
KICK_FALL = 0.058
# THE PHASE IS THE DROP'S, BROUGHT INTO THE FIRST BAR. `mod` must never see a
# negative -- ffmpeg's keeps the sign of its argument, and the whole build would
# read as "not on the beat" -- so the offset is the drop's own position in a bar,
# 0 <= off < bar. It was 1e4 bars back instead, and the beat written into the
# filter is rounded to 7 places: at Murder in my Mind's 0.499966 s the 5 places it
# had then were 4 microseconds out, which forty thousand beats on is a sixth of a
# second -- every beat flip of a reel landed 0.167 s after its beat (ChatGPT's
# review, 2026-10-22: "flashes land in closely spaced pairs, 2.500 and 2.667 s").
GRID_PLACES = 7
# The intensity gate (section 8.1): the build runs at 45% so the drop has
# somewhere to go, and the last act 12% hotter so the finale is not more of the
# same. The reference's act three starts 69% of the way from the drop to the
# end -- 26.0s of a 36.0s body whose drop is at 4.0 -- so it is taken as a
# share rather than as the one number, which would land anywhere on a reel of
# another length.
GATE_BUILD = 0.45
GATE_LAST = 1.12
ACT3_SHARE = 0.69
# NO BLACK BEFORE THE DROP ANY MORE. The spec's two frames of black just before it
# (section 8.5) were a snap into the bass when the cut sat on the drop; with the
# kill ON the drop (clips/fasthead.py) they blank its last frames of approach, and
# ChatGPT's review called the black frame at 4.467 s the reel's worst defect.


def beat_engine(pid: str, *, beat: float, drop: float, length: float,
                var: str = "t", kills: list[float] | None = None) -> list[str]:
    """Filters that put the song's grid on the picture. -> post-chain entries.

    `drop` is in v-time -- where the bass lands in the finished reel, which is
    the song's drop less the song offset. Zero is honest when the song has no
    drop: the grid then starts at the first frame, which is what a reel with no
    build should do. `kills`, in v-time too, are protected from the long flip
    (FLIP_GUARD).
    """
    if beat <= 0 or length <= 0:
        return []
    bar = beat * 4.0
    drop = max(0.0, float(drop))
    # The flip starts one bar early, so the build ramps into the drop instead
    # of arriving with it.
    from_t = max(0.0, drop - bar)
    # In phase with the DROP, not with the first frame. The two coincide only
    # when the offset happens to be a whole number of beats, and being half a
    # beat out is the difference between an edit and a fault.
    off = (-drop) % bar
    on_beat = knob(pid, "beat", 1.0) >= 0.5
    gate = (f"if(lt({var},{drop:.4f}),{GATE_BUILD},"
            f"if(lt({var},{drop + (length - drop) * ACT3_SHARE:.4f}),1,{GATE_LAST}))")

    out: list[str] = []
    # SUMMING the two terms rather than using two negate filters: `enable`
    # treats any non-zero as on, so a bar line (both terms 1) stays on through
    # the longer window. Two filters would invert twice and cancel.
    P = GRID_PLACES
    # A KILL IS NOT WASHED OUT BY ITS OWN FLIP. Three frames near-white over three
    # quarters of the picture took the drop kill and the slow-motion kill with them
    # (ChatGPT's review of the v1.79.5 render). Its general rule: wherever a flip lands
    # within FLIP_GUARD of ANY kill, it stays on the grid but is one frame with only
    # FLIP_PARTIAL of the inverted picture over the real one; every other flip as before.
    grid = beat if on_beat else bar
    guard = sorted({round(g, 4) for k in (kills or []) for g in [round((float(k) + off) / grid) * grid - off]
                    if abs(float(k) - g) <= FLIP_GUARD and g >= from_t - 1e-6})
    near = "+".join(f"between({var},{g - 0.001:.4f},{g + FLIP_BAR:.4f})" for g in guard)
    terms = [f"lt(mod({var}+{off:.{P}f},{bar:.{P}f}),{FLIP_BAR})"]
    if on_beat:
        terms.insert(0, f"lt(mod({var}+{off:.{P}f},{beat:.{P}f}),{FLIP_BEAT})")
    flips = "+".join(terms)
    out.append(f"negate=enable='gte({var},{from_t:.4f})*({flips})" + (f"*not({near})'" if near else "'"))
    if guard:
        part = f"val+{FLIP_PARTIAL}*(maxval-2*val)"
        out.append(f"lutyuv=y='{part}':u='{part}':v='{part}':enable='" +
                   "+".join(f"between({var},{g - 0.001:.4f},{g + FLIP_BEAT:.4f})" for g in guard) + "'")
    if (kick := knob(pid, "kick", 0.029)) > 0:
        out.append(f"eq=brightness='({gate})*{kick:.4f}"
                   f"*exp(-mod({var}+{off:.{P}f},{beat:.{P}f})/{KICK_FALL})':eval=frame")
    return out


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
    hold: int = 0                                    # frames the last frame is held for a long ending
    layout: dict = field(default_factory=dict)       # facecam.layout(): where game and camera go
    cam_file: str = ""                               # a separate facecam video, if any
    cam_start: float = 0.0                           # its seconds at the segment's first source frame
    groove: dict = field(default_factory=dict)       # fx_schedule.for_shot(): bounce, pops, push

    def key(self) -> str:
        d = dict(self.__dict__)
        d.pop("index", None)
        # Left out at their defaults, so a shot that uses none of them keeps
        # the cache key -- and the render -- it had before they existed.
        for k, default in (("hold", 0), ("layout", {}), ("cam_file", ""), ("cam_start", 0.0), ("groove", {})):
            if d.get(k) == default:
                d.pop(k, None)
        # HOW THE RATES ARE RENDERED IS PART OF WHAT THE RENDER IS. The key is
        # built from the Segment's own fields, and `pieces` says what the rates
        # are but not what is done about them -- so the day smoothing arrived,
        # every slowed shot in every cache stayed exactly as juddery as it was
        # and the change looked like it had not worked. Added only when there
        # is re-timing to name, so a shot at real speed keeps the cache and the
        # render it already had.
        if retime.needed(self.pieces):
            d["smooth"] = retime.TAG
        blob = json.dumps(d, sort_keys=True, default=str)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:20]

    @property
    def frames(self) -> int:
        return self.head + self.body + self.tail


# PUTTING A KILL WHERE THE EDITOR WANTS IT, by bending time rather than by
# moving the cut. Dragging a kill used to change the shot's run-up, which
# changes the shot's length, which pushes every later shot down the timeline --
# so fixing one kill broke every kill after it. Measured on a real hand-edited
# reel: the kills the editor dragged landed within a frame of the beat and the
# ones after them were up to ten frames out.
#
# Here the shot's start and end do not move. What changes is the rate INSIDE
# it, so the anchored kills land on their marks and nothing downstream knows.
#
# HOW FAR TIME MAY BEND. Half to double speed is invisible on gameplay; beyond
# that a correction announces itself. 0.6-1.8 is the default band, and a drag
# that cannot be met inside it is REFUSED AND NAMED rather than quietly moving
# the cut -- which is exactly how that reel's later kills drifted.
RATE_MIN, RATE_MAX = 0.6, 1.8
# Two anchors closer than this in the output cannot be told apart and the rate
# between them is whatever rounding says. One frame is not an edit.
ANCHOR_MIN_GAP = 0.05


def fit_pieces(points: list[tuple[float, float]], dur: float, *,
               band: tuple[float, float] = (RATE_MIN, RATE_MAX)
               ) -> tuple[list[tuple[float, float, float]], list[str]]:
    """Rate map that makes each (output, source) point land where it says.

    `points` are (output seconds into the shot, source seconds), in order, and
    need not cover the whole shot: whatever is left at either end plays at the
    rate of the stretch beside it, so a shot does not change speed for no
    reason at its edges.

    -> (pieces, problems). `pieces` is what `_setpts_expr` wants. `problems` is
    empty when every rate fits the band, and otherwise says which pair could
    not be met and by how much -- the caller shows that rather than silently
    doing something else.
    """
    pts = sorted(((float(o), float(s)) for o, s in points), key=lambda p: p[0])
    kept: list[tuple[float, float]] = []
    for o, src in pts:
        if kept and o - kept[-1][0] < ANCHOR_MIN_GAP:
            continue
        kept.append((o, src))
    if len(kept) < 2 or dur <= 0:
        return [(0.0, max(dur, 0.0), 1.0)], []

    lo, hi = band
    spans, problems = [], []
    for (o0, s0), (o1, s1) in zip(kept, kept[1:]):
        out = o1 - o0
        rate = (s1 - s0) / out if out > 1e-6 else 1.0
        if rate < lo - 1e-9 or rate > hi + 1e-9:
            problems.append(
                f"{o0:.2f}s to {o1:.2f}s would have to play at {rate:.2f}x "
                f"(the limit is {lo:g}x to {hi:g}x)")
        spans.append((o0, o1, max(lo, min(hi, rate))))

    # The ends keep the rate of the stretch beside them: a shot that opens at
    # 1.0x and jumps to 0.6x on its first anchor reads as a stumble.
    head = []
    if kept[0][0] > 1e-6:
        head = [(0.0, kept[0][0], spans[0][2])]
    tail = []
    if dur - kept[-1][0] > 1e-6:
        tail = [(kept[-1][0], dur, spans[-1][2])]
    return head + spans + tail, problems


def segments(project: dict, derived: dict, *, has_audio=lambda p: True,
             song_beats: list[float] | None = None) -> list[Segment]:
    """The shot renders a project needs, with the handles its transitions use."""
    W, H = SIZES[project["format"]]
    shots = project["shots"]
    starts = [round(r["start"] * FPS) for r in derived["shots"]]
    ends = starts[1:] + [round(derived["length"] * FPS)]
    hold_f = round(float(derived.get("outro_hold") or 0.0) * FPS)
    cam = project.get("cam") or facecam.settings(None)
    groove = project.get("groove") or {}
    offset = float(project.get("song_offset") or 0.0)
    out = []
    for i, s in enumerate(shots):
        head = round(s["tlen"] / 2 * FPS) if i > 0 else 0
        tail = round(shots[i + 1]["tlen"] / 2 * FPS) if i + 1 < len(shots) else 0
        body = max(1, ends[i] - starts[i])
        held = min(hold_f, body - 1) if i == len(shots) - 1 else 0
        dur = (body - held) / FPS
        speed = s["speed"]
        if i == len(shots) - 1 and project["outro"] == "e03":
            speed = "exit"
        pre_s = min(s["pre"], dur)
        anchors = s.get("anchors") or []
        if anchors:
            # THE EDITOR'S MARKS WIN OVER THE SPEED PART. A shot nobody dragged
            # has no anchors and takes the ordinary path, so this changes
            # nothing for every reel that was planned rather than edited.
            pts = [(pre_s, s["kill"])] + [(float(o), float(src)) for src, o in anchors
                                          if 0.0 <= float(o) <= dur]
            ps, trouble = fit_pieces(pts, dur)
            for why in trouble:
                log.info("shot %d (%s): %s", i, s.get("name", ""), why)
        else:
            ps = pieces(speed, dur, pre_s, _stretch_of(s), _own_after(s))
        src_body_start = s["kill"] - source_used(ps, pre_s)
        hsec, tsec = head / FPS, tail / FPS
        seg_ps = []
        if head:
            seg_ps.append((0.0, hsec, 1.0))
        seg_ps += [(a + hsec, b + hsec, r) for a, b, r in ps]
        if tail:
            seg_ps.append((hsec + dur, hsec + dur + tsec, 1.0))
        freeze = _freeze_of(s)
        push = bool(s["hero"] and picked(s["hero_fx"], "h02"))
        kill_at = hsec + pre_s
        # Every kill this shot shows, where it plays in the segment -- through
        # the speed map, so a slowed kill is still gated at the right moment,
        # and a kill after a freeze plays that much later.
        k_src = source_used(ps, pre_s)
        kill_times = sorted({round(hsec + output_at(ps, max(0.0, k_src + (k - s["kill"])))
                                   + (freeze if k > s["kill"] + 1e-6 else 0.0), 4)
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
            game_gate=bool(project.get("song")) and bool(project.get("kill_sound", True)),
            hold=held,
            layout=_layout_for(project, s, W, H, cam),
            cam_file=str(s.get("cam_file") or "") if cam["source"] == "file" else "",
            cam_start=round(float(s.get("cam_offset") or 0.0) + src_body_start - hsec, 4)
            if cam["source"] == "file" and s.get("cam_file") else 0.0,
            groove=_shot_groove(groove, offset + starts[i] / FPS - hsec, (head + body + tail) / FPS)))
    return out


def _shot_groove(groove: dict, song_at_zero: float, length: float) -> dict:
    """The stretch of the reel's groove this shot plays, or {} for none (so its key is unchanged)."""
    if not groove:
        return {}
    g = fx_schedule.for_shot(groove, song_at_zero, length)
    return g if (g["zoom"] or g["pops"] or g["push"]) else {}


def _layout_for(project: dict, shot: dict, W: int, H: int, cam: dict) -> dict:
    """Where the game and the camera go in this shot, or {} for the plain frame.

    {} rather than a dict saying "zoom, no camera" so a reel that uses neither
    renders -- and caches -- exactly as it did before either existed.
    """
    has_cam = cam["source"] == "inset" or (cam["source"] == "file" and bool(shot.get("cam_file")))
    fit = project.get("vfit") or "zoom"
    if not has_cam and fit == "zoom":
        return {}
    return facecam.layout(project["format"], W, H, cam, fit, has_cam)


def _cam_input(seg: Segment, src_len: float) -> list[str]:
    """The facecam file as input 1, cued to the same moment as the clip."""
    if not seg.cam_file:
        return []
    return ["-ss", f"{max(0.0, seg.cam_start):.4f}", "-t", f"{src_len + 0.5:.4f}", "-i", seg.cam_file]


def _layout_graph(seg: Segment, time_ops: list[str], effects: list[str], end: str,
                  FW: int, FH: int, vin: int = 0) -> str:
    """The video graph for a shot with a layout: the game framed into its area
    with its effects, the camera cut out and placed, one frame out.

    The camera goes through the same time map as the game -- speed ramps,
    freezes, the held ending -- so a laugh stays with the kill that caused it.
    Kill effects touch the game only: a zoom punch that also punched the
    streamer's face in was measured as the thing that made those reels look
    home-made.
    """
    lay = seg.layout
    gx, gy, GW, GH = (int(n) for n in lay["game"])
    camb = lay.get("cam")
    g = []
    if camb and not seg.cam_file:
        g.append(f"[{vin}:v]" + ",".join(time_ops) + ",split[gt][ct]")
    else:
        g.append(f"[{vin}:v]" + ",".join(time_ops) + "[gt]")
    if camb and seg.cam_file:
        cam_ops = [_setpts_expr(seg.pieces), f"fps={FPS}"]
        if seg.cam_start < 0:
            cam_ops.append(f"tpad=start_duration={-seg.cam_start:.4f}:start_mode=clone")
        # Held to the end rather than dropped: a camera file that stops early
        # must not leave a hole in the corner of the reel.
        cam_ops.append(f"tpad=stop_mode=clone:stop_duration={seg.frames / FPS:.4f}")
        g.append("[1:v]" + ",".join(cam_ops) + "[ct]")
    if lay.get("fit") in ("fit", "near"):
        # NEAR FIT keeps the middle three quarters of the width: the minimap, the kill feed
        # and the scoreboard mostly survive, and the game is a third taller than a full fit
        # (docs/STYLE-FAST-PACED-HEADSHOT.md section 7.2)
        near = f"crop=iw*{NEAR_KEEP}:ih:iw*{(1 - NEAR_KEEP) / 2}:0," if lay.get("fit") == "near" else ""
        g.append(f"[gt]split[ga][gb];"
                 f"[ga]scale={GW}:{GH}:force_original_aspect_ratio=increase,crop={GW}:{GH},"
                 f"boxblur=24:2,eq=brightness=-0.12:saturation=0.8[gbg];"
                 f"[gb]{near}scale={GW}:{GH}:force_original_aspect_ratio=decrease:flags=lanczos[gfg];"
                 f"[gbg][gfg]overlay=(W-w)/2:(H-h)/2,setsar=1[gf]")
    else:
        g.append(f"[gt]scale={GW}:{GH}:force_original_aspect_ratio=increase:flags=lanczos,"
                 f"crop={GW}:{GH},setsar=1[gf]")
    g.append("[gf]" + ",".join(effects + ["format=yuv420p"]) + "[g]")
    base = "[g]"
    if (gx, gy, GW, GH) != (0, 0, FW, FH):
        g.append(f"[g]pad={FW}:{FH}:{gx}:{gy}:color=black[gp]")
        base = "[gp]"
    if camb:
        cx, cy, CW, CH = (int(n) for n in camb)
        bx, by, bw, bh = lay.get("crop") or [0, 0, 1, 1]
        cam = [f"crop=iw*{bw:.4f}:ih*{bh:.4f}:iw*{bx:.4f}:ih*{by:.4f}",
               f"scale={CW}:{CH}:force_original_aspect_ratio=increase:flags=lanczos",
               f"crop={CW}:{CH}", "setsar=1"]
        stacked = (CW, cx) == (FW, 0)
        if lay.get("border") and not stacked:
            b = max(2, round(min(FW, FH) * 0.004))
            cam.append(f"pad={CW + 2 * b}:{CH + 2 * b}:{b}:{b}:color=white@0.9")
            cx, cy = cx - b, cy - b
        g.append("[ct]" + ",".join(cam) + "[c]")
        g.append(f"{base}[c]overlay=x={max(0, cx)}:y={max(0, cy)}:eof_action=repeat[gc]")
        base = "[gc]"
    g.append(base + end + "[v]")
    return ";".join(g)


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


# MAKING A SPEED CHANGE LOOK LIKE ONE. A shot whose rate ever leaves real speed
# is re-timed before its graph runs (clips/retime.py): the speed eased through
# every change, slow motion from optical flow, speed-ups through a shutter. The
# graph then takes that clip frame for frame. What it replaced -- the rates as
# one stepped setpts, `minterpolate=blend` under the slow parts and a `tmix`
# over the whole clip -- was measured against the same reels cut by hand and
# called "blended and fast-forwarded"; it is gone, not kept as a fallback.


def _moves(seg: Segment) -> bool:
    """Whether the groove bounces or pushes this shot (drawn as it is re-timed)."""
    return bool(seg.groove.get("zoom") or seg.groove.get("push"))


def retime_height(seg: Segment) -> int:
    """Rows of source a re-timed shot needs: what the reel actually shows of it.

    Optical flow costs twice as much at 1080 rows as at 720 (15 s against 7 s
    for 0.6 s of source), so a game letterboxed into a vertical reel -- 608
    rows on screen -- is re-timed at 720, and anything cropped from the full
    height at 1080.
    """
    lay = seg.layout or {}
    if lay.get("fit") in ("fit", "near"):
        GW, GH = float(lay["game"][2]), float(lay["game"][3])
        shown = GW * 9 / 16 / (NEAR_KEEP if lay.get("fit") == "near" else 1.0)
        return 720 if min(GH, shown) <= 720 else 1080
    return 1080


def _time_ops(seg: Segment, retimed: bool, lead: float) -> list[str]:
    """The re-time in the graph: none for a re-timed clip, the plain map at real speed."""
    if retimed:
        return [f"fps={FPS}"]
    v = [_setpts_expr(seg.pieces), f"fps={FPS}"]
    if lead > 1e-3:
        v.append(f"tpad=start_duration={lead:.4f}:start_mode=clone")
    return v


def segment_command(seg: Segment, out: Path, ff: str = "ffmpeg", encoder_args=None,
                    textdir: Path | None = None, retimed: Path | None = None) -> list[str]:
    """ffmpeg argv that renders one shot, handles included, to `out`.

    `retimed` is the shot's footage from retime.render(), one frame per output
    frame; a shot whose pieces leave real speed is rendered from it.
    """
    W, H, F = seg.width, seg.height, FPS
    total = seg.frames                  # a freeze replaces footage; it never lengthens a shot
    total_s = total / F
    kt = seg.kill_at
    src_len = sum((b - a) * r for a, b, r in seg.pieces)
    start = max(0.0, seg.src_start)
    lead = start - seg.src_start          # > 0 only if the clip starts late; padded below
    # the picture's input: the re-timed clip after the clip itself and any camera file
    vin = (2 if seg.cam_file else 1) if retimed else 0

    v = _time_ops(seg, bool(retimed), lead)
    if seg.freeze > 0:
        v.append(f"loop=loop={round(seg.freeze * F)}:size=1:start={round(kt * F)}")
        v.append(f"setpts=N/{F}/TB")
    if seg.hold > 0:
        # A long ending: the footage has run out, so its last frame is held
        # while the picture and the song fade (the push-in is below).
        v.append(f"tpad=stop_mode=clone:stop_duration={seg.hold / F:.4f}")
    if seg.outro_freeze > 0:
        n = round(seg.outro_freeze * F)
        v.append(f"loop=loop={n}:size=1:start={max(0, total - n)}")
        v.append(f"setpts=N/{F}/TB")
    lay = seg.layout or {}
    FW, FH = W, H                       # the whole frame; W, H become the game's area
    time_ops = list(v)
    if lay:
        v = []
        W, H = int(lay["game"][2]), int(lay["game"][3])
    elif seg.fmt == "vertical":
        v.append(f"crop='min(iw,ih*9/16)':ih,scale={W}:{H}:flags=lanczos")
    else:
        v.append(f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}")
    if not lay:
        v.append("setsar=1")

    hold = seg.freeze
    T = "in_time"                       # zoompan's clock; every other filter uses t
    z_terms = []
    if seg.hold > 0:
        # Held, not frozen: a slow push over the held frame, eased at both
        # ends, so the ending settles rather than stopping.
        h0, hs = (total - seg.hold) / F, seg.hold / F
        z_terms.append(f"0.06*(1-cos(PI*min(1,max(0,({T}-{h0:.4f})/{hs:.4f}))))/2")
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
    if (pops := fx_schedule.pop_expr(seg.groove)):
        b_terms.append(pops)                    # the snare pops, on the game picture only
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
    end = f"format=yuv420p,trim=end_frame={total},setpts=PTS-STARTPTS"
    if not lay:
        vchain = f"[{vin}:v]" + ",".join(v + [end]) + "[v]"
    else:
        vchain = _layout_graph(seg, time_ops, v, end, FW, FH, vin)

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
            *_cam_input(seg, src_len),
            *(["-i", str(retimed)] if retimed else []),
            "-filter_complex", vchain + ";" + achain,
            "-map", "[v]", "-map", "[a]", "-r", str(F), *enc,
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-frames:v", str(total), str(out)]


def assemble_command(project: dict, derived: dict, segs: list[Segment], files: list[Path],
                     out: Path, ff: str = "ffmpeg", encoder_args=None,
                     textdir: Path | None = None, mark_at=None, lyrics=None) -> list[str]:
    """ffmpeg argv that joins the shot renders into the finished reel.

    `mark_at` is (animation folder, resting still, x, y) for the AutoStream
    mark, or None when it cannot be drawn. See THE MARK below. `lyrics` is a
    lyrics.Prepared whose subtitle script is drawn over everything but the mark.
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
    # THE ENDING'S OWN LENGTH, when one was chosen: every fading ending runs
    # for it, the song fades with it, and derive() has held the last frame
    # long enough that the fade never starts before the last kill has landed.
    long_end = float(derived.get("outro_fade") or 0.0)
    if long_end:
        end_fade = min(long_end, L)
    # THE LAST KILL IS NEVER FADED (F2, every style). A style's own fade is most of a bar
    # and ran over the last kill of two Follow-the-song reels; derive() holds the last
    # frame back only when an ending length was chosen. Otherwise the fade is shortened to
    # start OUTRO_AFTER_KILL after the last kill -- never below a third of a second.
    kills_all = derived.get("kills") or []
    room = L - (max(kills_all) + OUTRO_AFTER_KILL) if kills_all else L

    def unfaded(d: float) -> float:
        return round(max(0.3, min(d, room)), 4)
    end_fade = unfaded(end_fade)
    if fam(outro) == "fade_out":
        d = unfaded(end_fade if long_end else _fade_seconds(outro, 0.7))
        post.append(f"fade=out:st={max(0.0, L - d):.4f}:d={d:.4f}:color={_fade_colour(outro)}")
    elif outro == "e01" or outro == "e03":
        post.append(f"fade=out:st={max(0.0, L - end_fade):.4f}:d={end_fade:.4f}")
    elif outro == "e05":
        d = unfaded(end_fade if long_end else 0.35)
        post.append(f"fade=out:st={max(0.0, L - d):.4f}:d={d:.4f}:color=white")
    elif outro == "e02":
        d = unfaded(end_fade if long_end else 1.0)
        post.append(f"hue=s='if(gt(t,{L - d:.4f}),max(0,1-(t-{L - d:.4f})/{d * 0.8:.4f}),1)'")
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
    if (pid := picked(ov, "o09")):
        # THE SONG'S GRID, ON THE PICTURE. In v-time, which is why it is here
        # and not in a segment: a shot does not know where in the reel it sits.
        drop = project.get("song_drop")
        post += beat_engine(
            pid, beat=float(project.get("beat") or 0.0),
            drop=(float(drop) - float(project.get("song_offset") or 0.0)
                  if drop is not None else 0.0),
            length=L, kills=derived.get("kills") or [])
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
        # Anywhere in the frame, as a share of the room the text leaves:
        # 1,1 is the bottom-right corner it always used to sit in.
        px, py = project.get("handle_pos") or [1.0, 1.0]
        mx, my = round(W * 0.025), round(H * 0.03)
        post.append(f"drawtext={font}expansion=none:textfile={_path_arg(text_file(textdir, project['handle']))}:"
                    f"fontsize={size}:fontcolor=white@0.7:borderw=1:bordercolor=black@0.35:"
                    f"x={mx}+(w-tw-{2 * mx})*{float(px):.4f}:y={my}+(h-th-{2 * my})*{float(py):.4f}")
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
        # THE GATE IS 60% OF THE RENDER. The expression resolves to exactly
        # stream A once T >= b, but a per-pixel all_expr is still evaluated on
        # every frame of the whole reel -- 1080x1920 x 4243 frames for a 71 s
        # reel, ~98% of it thrown away. Measured on 10 s of a finished reel,
        # decode plus h264_nvenc each time: 2476 ms with no filter, 2532 ms
        # for the gblur alone, 28308 ms for this blend ungated and 6019 ms
        # gated. A 262 s render of that reel becomes about 100 s.
        #
        # Behaviour-preserving, not approximately: a disabled blend passes its
        # first input through, which is what the expression already computed
        # there. Ungated against gated over the first 4 s -- the blend window
        # and the pass-through either side of it -- is PSNR inf on all three
        # planes, i.e. bit-identical.
        chain_in = (f"[{acc_label}]split[bs][bb];[bb]gblur=sigma=18[bg];"
                    f"[bs][bg]blend=all_expr='A*min(1,T/{b})+B*(1-min(1,T/{b}))'"
                    f":enable='lt(t,{b})'[bl]")
        g.append(chain_in)
        acc_label = "bl"
    # THE LYRICS, LAST BUT FOR THE MARK: over the grade, the grain and the
    # bars, so a word is never dimmed by the look it sits on. Stamp greys the
    # picture under each red word first, the way the edit it copies does.
    if lyrics is not None and lyrics.ass:
        if lyrics.greys:
            on = "+".join(_between(a, b) for a, b in lyrics.greys)
            post.append(f"hue=s=0.15:enable='{on}'")
        post.append(f"ass=filename={_path_arg(lyrics.ass)}:fontsdir={_path_arg(lyrics_mod.FONTS_DIR)}")
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
        if outro in ("e01", "e03", "e02") or fam(outro) == "fade_out" or long_end:
            # A long ending eases out rather than ramping down in a straight
            # line, which sounds like the song being switched off slowly.
            curve = ":curve=qsin" if long_end else ""
            fades.append(f"afade=t=out:st={max(0.0, L - end_fade):.4f}:d={end_fade:.4f}{curve}")
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
                 shape_beats: list[float] | None = None, auto: bool = False):
        self.id = next(_JOB_IDS)
        self.project, self.derived, self.root, self.out = project, derived, root, out
        self.shape_beats = shape_beats
        # Started by the page on its own, once the user stopped editing, rather
        # than by Render. A newer edit -- or a press of Render -- replaces it
        # without asking: see Runner.yield_auto.
        self.auto = bool(auto)
        self.state = "queued"
        self.step = "shots"
        self.done = 0
        self.total = 0
        self.message = ""
        self.error = ""
        self.started = time.time()
        self.finished = 0.0
        self.cached = 0
        # How far through the reel the join has got, 0..1. See snapshot().
        self.join = 0.0
        self.lyrics_note = ""
        self.checks: list = []                  # reelcheck findings, once the render is read back
        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        with self._lock:
            # THE JOIN IS COUNTED IN ITS OWN SECONDS, not as one unit of work.
            # Shots are units because there are dozens of them; the join is a
            # single pass that is most of the wall clock whenever the shots
            # come from cache, so counting it as "2 of 49" parked the bar at
            # 95% for four minutes and a working render was indistinguishable
            # from a hung one. `join` is how far through the reel ffmpeg says
            # it is, which is a real fraction of a real pass.
            pct = int(100 * (self.done + 2 * self.join) / self.total) if self.total else 0
            # Never 100 until it is finished: the loudness pass and the intro
            # come after the join, and a bar that reads 100% beside a spinner
            # is the same lie in the other direction.
            if self.state not in ("done", "error", "cancelled"):
                pct = min(pct, 99)
            return {"id": self.id, "state": self.state, "step": self.step, "done": self.done,
                    "total": self.total,
                    "percent": max(0, min(100, pct)), "message": self.message, "error": self.error,
                    "output": str(self.out), "project": str(self.out.with_suffix(".reel.json")),
                    "elapsed": int((self.finished or time.time()) - self.started),
                    "cached": self.cached, "name": self.project.get("name", ""),
                    "lyrics_note": self.lyrics_note, "auto": self.auto, "checks": self.checks}

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

    def _run_ff(self, argv: list[str], *, capture: bool = False, seconds: float = 0.0) -> str:
        """Run ffmpeg where Cancel can reach it. -> its stderr when `capture`.

        A hardware encode that fails is run again on the CPU, and the CPU is
        used for the rest of the process -- see tools.software_fallback.

        `seconds` is how much reel this call produces. Pass it and the call
        reports its progress; leave it and nothing changes.
        """
        from .tools import software_fallback
        try:
            return self._run_ff_once(argv, capture=capture, seconds=seconds)
        except Cancelled:
            raise
        except RuntimeError as e:
            soft = software_fallback(argv)
            if soft is None:
                raise
            log.warning("studio: hardware encode failed, using the CPU (%s)", str(e)[-200:])
            # A second attempt starts the pass again, so the bar does too --
            # otherwise it would carry on from where the failed one died.
            self._set(join=0.0)
            return self._run_ff_once(soft, capture=capture, seconds=seconds)

    def _run_ff_once(self, argv: list[str], *, capture: bool = False, seconds: float = 0.0) -> str:
        from .killfeed import _NO_WINDOW
        if self._cancel.is_set():
            raise Cancelled("cancelled")
        # ASK FFMPEG WHERE IT HAS GOT TO. The join was one opaque call with
        # stdout thrown away, so the longest phase of a render was also the
        # only one nothing could report on. `-progress pipe:1` writes a block
        # of key=value lines every second; `-nostats` drops the carriage-return
        # status line, which is not parseable and not wanted.
        watch = seconds > 0
        if watch:
            argv = [argv[0], "-progress", "pipe:1", "-nostats", *argv[1:]]
        proc = subprocess.Popen(argv,
                                stdout=subprocess.PIPE if watch else subprocess.DEVNULL,
                                stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
        self._proc = proc
        # Cancel may have landed between the check above and the assignment.
        if self._cancel.is_set():
            proc.terminate()
        if watch:
            # communicate() would read stdout itself, so the pipes are drained
            # by hand: the reader thread takes the progress, this thread takes
            # the (small, -loglevel error) stderr, and neither can fill.
            pump = threading.Thread(target=self._watch_progress, args=(proc.stdout, seconds),
                                    daemon=True)
            pump.start()
            err = proc.stderr.read()
            proc.wait()
            pump.join(timeout=2)
        else:
            _, err = proc.communicate()
        code = proc.returncode
        self._proc = None
        if self._cancel.is_set():
            raise Cancelled("cancelled")
        text = (err or b"").decode("utf-8", "replace")
        if code != 0:
            raise RuntimeError(text[-1500:] or f"ffmpeg exited {code}")
        return text if capture else ""

    def _watch_progress(self, pipe, seconds: float) -> None:
        """Turn ffmpeg's own clock into a bar that moves.

        `out_time=HH:MM:SS.ffffff` rather than `out_time_ms`, which ffmpeg
        writes in microseconds despite its name -- a unit nobody reading the
        code would guess, and the sort of thing that silently halves a
        percentage. The clock is unambiguous.

        Nothing here may raise: the pipe closes when ffmpeg exits, which is an
        ordinary end to this thread, not a failed render.
        """
        try:
            for raw in pipe:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("out_time="):
                    continue
                at = _clock(line[9:])
                if at is not None and seconds > 0:
                    self._set(join=max(0.0, min(1.0, at / seconds)))
        except (OSError, ValueError):
            pass

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

    def _lyrics(self, ff: str):
        """The reel's lyrics, ready to draw, or None -- never a failed render.

        A song with no synced lyrics, no network, or an ffmpeg without libass
        each leaves the reel exactly as it would have been, with the reason in
        `lyrics_note` for the page to show.
        """
        if lyrics_mod.settings(self.project.get("lyrics"))["look"] == "off":
            return None
        if not lyrics_mod.ffmpeg_draws_ass(ff):
            self._set(lyrics_note="This copy of ffmpeg cannot draw subtitles (no libass), "
                                  "so the reel has no lyrics.")
            return None
        self._set(step="join", message="Timing the lyrics to the song")
        W, H = SIZES[self.project["format"]]
        try:
            got = lyrics_mod.prepare(self.project, self.derived, self.root / CACHE_DIR / "lyrics", W, H)
        except Exception as e:                              # noqa: BLE001
            log.warning("studio: lyrics failed (%s)", e)
            self._set(lyrics_note="The lyrics could not be prepared, so the reel has none.")
            return None
        self._set(lyrics_note=got.note, message="Joining the shots and mixing the sound")
        return got if got.ass else None

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

    def _check(self, ff: str, intro: float) -> list:
        """reelcheck's findings for the reel just written. Never raises."""
        try:
            st = STYLE.get(self.project.get("style") or "")
            fast = bool(st and (st.drop or getattr(st, "fast_cuts", False)))
            derived = dict(self.derived)
            derived["length"] = float(derived.get("length") or 0.0) + intro
            derived["offset"] = intro               # the intro sits in front of every kill
            return reelcheck.check(self.project, derived, self.out, fast=fast, ff=ff)
        except Exception as e:                              # noqa: BLE001
            log.info("reel check failed: %s", e)
            return [reelcheck.Finding(reelcheck.HARD, "check-failed", f"The reel could not be checked ({e}).")]

    def _retime(self, seg: "Segment", out: Path, ff: str) -> Path:
        """The shot's footage re-timed (clips/retime.py), for its graph to take as it is."""
        from .tools import media_info

        info = media_info(seg.clip)
        try:
            return retime.render(
                seg.clip, seg.src_start, seg.pieces, seg.frames, out,
                kills=[seg.kill_at, *seg.kill_times],
                size=retime.work_size(info.get("width", 0), info.get("height", 0), retime_height(seg)),
                ff=ff, work=out.parent, cancelled=self._cancel.is_set,
                zoom=(lambda t: fx_schedule.zoom_at(seg.groove, t)) if _moves(seg) else None)
        except RuntimeError:
            if self._cancel.is_set():
                raise Cancelled("cancelled")
            raise

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
            # THE CACHED SHOTS COUNT TOWARDS THE BAR. They were `total=len(todo)+2`,
            # so a reel whose every shot was already cut had total=2 and done=0
            # and sat at 0% for the whole join -- four minutes on a 47-shot reel,
            # which is indistinguishable from a render that never started.
            self._set(total=len(segs) + 2, done=len(segs) - len(todo),
                      cached=len(segs) - len(todo),
                      message=f"Rendering {len(todo)} of {len(segs)} shots")
            enc_seg = video_codec_args("auto", cq=16)
            retimes = self.root / CACHE_DIR / "retime"
            for j, (s, f) in enumerate(todo):
                self._set(step="shots", message=f"Shot {s.index + 1} of {len(segs)}")
                tmp = f.with_suffix(".part.mp4")
                rt = None
                rt_file = retimes / f"{s.key()}.mp4"
                try:
                    if retime.needed(s.pieces) or _moves(s):
                        self._set(message=f"Shot {s.index + 1} of {len(segs)}: smoothing its speed"
                                  if retime.needed(s.pieces) else f"Shot {s.index + 1} of {len(segs)}")
                        rt = self._retime(s, rt_file, ff)
                    self._run_ff(segment_command(s, tmp, ff, enc_seg, textdir, rt))
                except Cancelled:
                    # A subclass of RuntimeError: re-wrapped below, a Cancel
                    # the user pressed was reported as a failed render.
                    raise
                except RuntimeError as e:
                    _keep_failure(self.root, self.project, s, segment_command(s, tmp, ff, enc_seg, textdir, rt), e)
                    raise RuntimeError(f"Shot {s.index + 1} ({Path(s.clip).name}): {e}") from e
                finally:
                    if not tmp.is_file() or self._cancel.is_set():
                        _unlink(tmp)
                    _unlink(rt_file)
                tmp.replace(f)
                self._set(done=len(segs) - len(todo) + j + 1)
            # THE JOIN IS THE LONG PART when the shots are cached -- 258 s of a
            # 258 s render on the reel this was measured on. Say so, rather
            # than leaving a still bar to mean whatever the watcher fears.
            self._set(step="join",
                      message=f"Joining {len(segs)} shots and mixing the sound")
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
                    lyr = self._lyrics(ff)
                    # The reel's own length is what this pass produces, so it
                    # is the denominator the bar is honest against.
                    self._set(join=0.0)
                    self._run_ff(assemble_command(self.project, self.derived, segs, files, tmp, ff,
                                                  video_codec_args("auto", cq=19), textdir,
                                                  mark_at=mark_at, lyrics=lyr),
                                 seconds=float(self.derived.get("length") or 0))
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
                _swap_in(tmp, self.out)
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
            if self.lyrics_note:
                meta["lyrics_note"] = self.lyrics_note
            meta["render"] = {"length": round(self.derived["length"] + intro, 3),
                              "reel": self.derived["length"], "intro": intro,
                              "when": int(time.time()),
                              "shots": len(segs), "cached": len(segs) - len(todo)}
            # THE GATE (clips/reelcheck.py): the finished file is read back before
            # anyone is told it is ready. It never fails a render -- a check that
            # cannot run is a finding of its own -- but a hard finding changes what
            # the page says, and is kept on the project beside the reel.
            self._set(step="check", message="Checking the finished reel")
            findings = self._check(ff, intro)
            meta["checks"] = [f.as_dict() for f in findings]
            self.out.with_suffix(".reel.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
            hard = [f for f in findings if f.level == reelcheck.HARD]
            self._set(state="done", step="done", done=self.total, checks=meta["checks"],
                      message="Reel ready" if not hard else "Rendered, but not ready: " + hard[0].message,
                      finished=time.time())
        except Cancelled:
            self._set(state="cancelled", message="Cancelled", finished=time.time())
        except Exception as e:                              # noqa: BLE001
            log.warning("studio render failed: %s", e)
            self._set(state="failed", error=str(e)[-800:], message="The render failed",
                      finished=time.time())


FAILED_KEPT = 10


def _keep_failure(root: Path, project: dict, seg: "Segment", argv: list[str], error: Exception) -> None:
    """Write down what a shot that would not render was given. Never raises.

    A FAILED RENDER LEFT NOTHING BEHIND. The project lives in the page until a
    render succeeds, so on wsdhkwqbsd a shot failed five times running with
    "Invalid data found when processing input" and the timeline that caused it
    could not be read back: rebuilt from an export, the same shot rendered fine,
    because the export carries timing and not everything else. The project, the
    shot and the exact ffmpeg command, kept here, make the next one reproducible.
    """
    try:
        folder = root / CACHE_DIR / "failed"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", str(project.get("name") or "reel"))[:40] or "reel"
        path = folder / f"{stamp}-{name}-shot{seg.index + 1}.json"
        path.write_text(json.dumps({"shot": seg.index + 1, "key": seg.key(), "error": str(error)[-2000:],
                                    "argv": [str(a) for a in argv], "project": project},
                                   indent=1, default=str), encoding="utf-8")
        log.warning("studio: what the failed shot was given is in %s", path)
        for old in sorted(folder.glob("*.json"))[:-FAILED_KEPT]:
            _unlink(old)
    except Exception:                                       # noqa: BLE001
        log.exception("studio: could not keep the failed render's project")


def _swap_in(tmp: Path, out: Path) -> None:
    """Put the finished reel in place of the old one, waiting out a reader.

    THE RENDER WAS FINISHING AND FAILING ON ITS LAST LINE. Windows refuses to
    rename over a file anything still has open, and the thing holding the old
    reel was US: the page's player streams it through our own web server, and
    `_media` keeps the file open for the length of the response. So a render
    of a reel you were watching died with WinError 5 after doing all the work.

    It began happening when renders got FASTER. The same reel took 262 s
    before the blur gate landed and about 60 s after, which moved the swap
    from "long after the player finished loading" to "while it still has the
    file". A performance fix turned a latent race into a reliable failure.

    The page now drops the video before a render starts, which is the real
    fix; this is the belt to that braces -- Explorer previewing the folder, a
    media player someone left open, or a second page in another tab can all
    hold the same handle, and none of them are ours to close. Seconds, not
    minutes: a reader that has not let go by then is not about to.
    """
    for wait in (0.0, 0.2, 0.5, 1.0, 2.0, 3.0):
        if wait:
            time.sleep(wait)
        try:
            tmp.replace(out)
            return
        except PermissionError:
            continue
    # Out of patience: say which file, and that the render itself was fine.
    raise RuntimeError(
        f"The reel rendered, but {out.name} could not be replaced -- something "
        f"still has it open. Close anything playing it and press Render again.")


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

    def yield_auto(self, wait: float = 8.0) -> bool:
        """Make way for a newer render. -> True when nothing is rendering now.

        A BACKGROUND RENDER IS NEVER IN THE WAY. It was started because the
        user paused, not because they asked; an edit since then, or Render
        itself, has a better claim on the encoder. So a running auto job is
        cancelled here and waited for -- ffmpeg is terminated, so this is well
        under a second -- and the shots it finished stay in the cache for the
        render that replaces it. A render the user started is never touched:
        that is False, and the caller says it is busy.
        """
        with self._lock:
            job = self.job
        if job is None or job.state not in ("queued", "running"):
            return True
        if not job.auto:
            return False
        job.cancel()
        deadline = time.monotonic() + wait
        while job.state in ("queued", "running") and time.monotonic() < deadline:
            time.sleep(0.02)
        return job.state not in ("queued", "running")

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
