"""SHOTS AS SLOTS: take one shot out, or give it another clip, and no other kill moves.

WHY THIS EXISTS. A weak clip in a finished reel had two ways out and both moved
everything else: Remove spliced the list and laid every later kill back one hit
along ("closes up on the song's hits", v1.76.2), and Replace took any clip and
re-laid the marks, so a clip without the footage before its kill was trimmed and
its neighbours shifted. Agreed with ChatGPT on 2026-10-24, step 2 of the guide plan:
every shot is a fixed slot on the song -- its kill stays on its beat whatever clip
fills it -- and

    replace   offers only clips that can land a kill on that same beat, with the
              footage the slot's run-up and tail need, best first;
    close     takes the shot out and lets the shots either side stretch over it:
              the one before runs on, the one after starts sooner. Every other
              kill stays where it is on the song;
    fill      the next best clip into the same slot (replace, chosen for you);
    shorten   when neither works: the reel ends before the shot, on the beat.

The build take of a Build and drop reel is one slot whose last kill is ON the
drop: it is only ever swapped for another take that lands there (`build_options`).

Every operation returns a new project and says which other kills moved, measured
in song seconds -- the proof is that list being empty.
"""
from __future__ import annotations

import copy
from pathlib import Path

from . import director, studio

SAME_KILL = 0.05          # two readings closer than this are one kill
CLEAR = 0.05              # a lone kill's shot shows no other kill this near its window
EDGE = 0.02               # footage kept back from a clip's first and last frame
MOVED = 0.01              # a kill this far from where it was has moved


class SlotError(ValueError):
    """The operation cannot be done as asked; the message says why, in words."""


# ------------------------------------------------------------------ reading the reel

def song_kills(project: dict) -> list[float]:
    """Each shot's kill, in song seconds: what must not move."""
    off = float(project.get("song_offset") or 0.0)
    out, t = [], 0.0
    for s in project["shots"]:
        out.append(round(off + t + float(s["pre"]), 4))
        t += float(s["duration"])
    return out


def moved(before: list[float], after: list[float]) -> list[int]:
    """Indexes, in `before`, of kills that are no longer anywhere in `after`."""
    return [i for i, t in enumerate(before) if not any(abs(t - u) <= MOVED for u in after)]


def take_shots(project: dict) -> list[int]:
    """The shots of a Build and drop reel's take: its opening run of the build clip's footage."""
    shots = project.get("shots") or []
    build = str(project.get("build_clip") or "").lower()
    if not build and project.get("song_drop") is not None and len(shots) > 1:
        build = str(shots[0]["clip"]).lower() if str(shots[1]["clip"]).lower() == str(shots[0]["clip"]).lower() else ""
    out = []
    for i, s in enumerate(shots):
        if not build or str(s["clip"]).lower() != build:
            break
        out.append(i)
    return out


def need(shot: dict) -> tuple[float, float]:
    """Source seconds a clip must have before and after its kill to fill this slot as timed.

    The replacement is a lone kill on the slot's timing and speed: the shot's own anchors (a
    run's second kill) and stretch belong to the clip that is leaving."""
    s = dict(shot)
    s.pop("anchors", None)
    s.pop("stretch", None)
    s["kills"] = [s["kill"]]
    ps = studio.shot_pieces(s)
    before = studio.source_used(ps, float(s["pre"]))
    return before, studio.source_used(ps, float(s["duration"])) - before


def _seconds(row: dict) -> float:
    return float(row.get("clip_seconds") or row.get("duration") or row.get("seconds") or 0.0)


def fits(row: dict, k: float, before: float, after: float) -> bool:
    """Whether this clip's kill `k` can fill a slot that needs this footage, and shows no other kill."""
    secs = _seconds(row)
    if k - before < EDGE - 1e-6 or k + after > secs - EDGE + 1e-6:
        return False
    return not any(k - before - CLEAR < float(x) < k + after + CLEAR and abs(float(x) - k) > SAME_KILL
                   for x in row.get("kills") or [])


def _score(row: dict, h: bool) -> float:
    labels = " ".join(str(x) for x in row.get("labels") or row.get("tags") or []).upper()
    return (1.0 + (1.5 if h else 0.0) + (0.4 if any(w in labels for w in ("CLOSER", "FLAWLESS", "LAST")) else 0.0)
            + (0.3 if row.get("fav") or row.get("favourite") else 0.0))


def _in_reel(project: dict) -> set[str]:
    return {str(s["clip"]).lower() for s in project["shots"]}


# ------------------------------------------------------------------ replace

def options(project: dict, i: int, rows: list[dict], *, limit: int = 12) -> dict:
    """The clips that can fill shot i's slot, best first. -> {"slot", "clips", "take", "why"}

    One clip, one place: a clip already in the reel is not offered. The kill offered from each
    clip is its best one that fits -- a headshot before a body kill."""
    shots = project["shots"]
    if not 0 <= i < len(shots):
        raise SlotError("That shot is not in the reel any more.")
    if i in take_shots(project):
        return build_options(project, rows, limit=limit)
    shot = shots[i]
    before, after = need(shot)
    have = _in_reel(project)
    got = []
    for row in rows:
        path = str(row.get("path") or "")
        if not path or path.lower() in have:
            continue
        ks = [float(k) for k in row.get("kills") or []]
        hs = [bool(h) for h in row.get("hs") or []] + [False] * len(ks)
        best = None
        for k, h in zip(ks, hs):
            if fits(row, k, before, after):
                sc = _score(row, h)
                if best is None or sc > best[0]:
                    best = (sc, k, h)
        if best:
            got.append({"clip": path, "name": str(row.get("name") or Path(path).stem), "kill": round(best[1], 3),
                        "hs": best[2], "score": round(best[0], 2)})
    got.sort(key=lambda c: (-c["score"], c["name"]))
    mark = song_kills(project)[i]
    why = "" if got else (f"None of your other clips has a kill with {before:.1f} s of footage before it and "
                          f"{after:.1f} s after it, which this shot's place on the song needs.")
    return {"slot": {"index": i, "mark": mark, "before": round(before, 3), "after": round(after, 3)},
            "clips": got[:limit], "take": False, "why": why}


def replace(project: dict, i: int, row: dict, kill: float | None = None) -> dict:
    """Shot i with this clip's kill in its place: its timing, speed and effects stay. -> project"""
    shots = project["shots"]
    if not 0 <= i < len(shots):
        raise SlotError("That shot is not in the reel any more.")
    if i in take_shots(project):
        raise SlotError("The build is swapped as a whole take: choose from the takes offered for it.")
    path = str(row.get("path") or "")
    if path.lower() in _in_reel(project) and path.lower() != str(shots[i]["clip"]).lower():
        raise SlotError("That clip is in the reel already, and a clip plays in one place.")
    before, after = need(shots[i])
    ks = [float(k) for k in row.get("kills") or []]
    if kill is None:
        hs = [bool(h) for h in row.get("hs") or []] + [False] * len(ks)
        ok = [(k, h) for k, h in zip(ks, hs) if fits(row, k, before, after)]
        if not ok:
            raise SlotError("That clip has no kill with the footage this shot's place needs.")
        kill = max(ok, key=lambda x: (x[1], -x[0]))[0]
    kill = float(kill)
    if not fits(row, kill, before, after):
        raise SlotError(f"That kill needs {before:.1f} s of footage before it and {after:.1f} s after it, "
                        f"and the clip does not have them.")
    out = copy.deepcopy(project)
    s = out["shots"][i]
    for k in ("anchors", "stretch", "led"):
        s.pop(k, None)
    s.update({"clip": path, "clip_id": str(row.get("id") or ""), "name": str(row.get("name") or Path(path).stem),
              "clip_seconds": round(_seconds(row), 3), "kill": round(kill, 3), "kills": [round(kill, 3)],
              "clip_mtime": 0})
    out.pop("remark", None)
    return out


# ------------------------------------------------------------------ the build take

def build_options(project: dict, rows: list[dict], *, limit: int = 8) -> dict:
    """Takes that can replace the build: each lands its last kill on the drop, as the take does."""
    shots = project["shots"]
    take = take_shots(project)
    drop = project.get("song_drop")
    if not take or drop is None:
        raise SlotError("This reel has no build take to swap.")
    off = float(project.get("song_offset") or 0.0)
    have = _in_reel(project) - {str(shots[take[0]]["clip"]).lower()}
    got = []
    for row in rows:
        path = str(row.get("path") or "")
        if not path or path.lower() in have or path.lower() == str(shots[take[0]]["clip"]).lower():
            continue
        b = _best_take(row)
        if b is None:
            continue
        try:
            new = _swap_take(project, b)
        except SlotError:
            continue
        lost = round(float(new.get("song_offset") or 0.0) - off, 2)
        got.append({"clip": path, "name": str(row.get("name") or Path(path).stem), "kills": len(director.take_kills(b)),
                    "score": round(director.setup_score(b), 2), "later": max(0.0, lost)})
    got.sort(key=lambda c: (-c["score"], c["later"], c["name"]))
    why = "" if got else "None of your other clips has a clutch, an ace or three kills together to build into the drop with."
    return {"slot": {"index": take[0], "mark": round(float(drop), 4), "shots": len(take)},
            "clips": got[:limit], "take": True, "why": why}


def _best_take(row: dict):
    clip = dict(row)
    clip.setdefault("duration", _seconds(row))
    cands = [b for b in director.bursts(clip) if director.is_setup(b)]
    r = director.round_of(clip)
    if r is not None and director.is_setup(r):
        cands.append(r)
    return max(cands, key=director.setup_score) if cands else None


def _swap_take(project: dict, b) -> dict:
    """The take rebuilt from burst `b`, its last kill on the same song second as the old one's."""
    shots = project["shots"]
    take = take_shots(project)
    off = float(project.get("song_offset") or 0.0)
    drop_song = song_kills(project)[take[-1]]
    first_cut_song = off + sum(float(shots[j]["duration"]) for j in take)   # where the flurry's first shot starts
    new, begin = director.take(b, drop_song - off)
    off2 = off + begin
    ks = [s["kill"] for s in new]
    built = []
    for n, s in enumerate(new):
        a, b_ = s.pop("_src")
        reel_k = (drop_song - off2) - director.take_span([x for x in ks if x >= s["kill"] - 1e-6])
        if n == 0 and reel_k - float(s["pre"]) < -1e-3:
            raise SlotError("That take needs a longer run-up than the reel has before the drop.")
        dur = (b_ - a) if b_ is not None else (first_cut_song - off2) - (reel_k - s["pre"])
        if dur <= 0.1:
            raise SlotError("That take cannot reach the drop from where the reel starts.")
        s["duration"] = round(dur, 5)
        s["kills"] = [round(x, 3) for x in b.kills if a - 1e-6 <= x <= (b_ if b_ is not None else 1e9)]
        built.append(s)
    if not built:
        raise SlotError("That clip has no take.")
    if not all(_footage_ok(s) for s in built):
        raise SlotError("That take runs out of footage before the first quick kill.")
    # the take's effects stay with their places: the punch on the drop above all
    old_fx = [list(shots[j].get("fx") or []) for j in take]
    for n, s in enumerate(built):
        s["fx"] = old_fx[-1] if n == len(built) - 1 else (old_fx[n] if n < len(old_fx) - 1 else [])
    out = copy.deepcopy(project)
    out["shots"] = built + out["shots"][len(take):]
    out["song_offset"] = round(off2, 5)
    out["build_clip"] = b.path
    out.pop("remark", None)
    return out


def swap_take(project: dict, row: dict) -> dict:
    b = _best_take(row)
    if b is None:
        raise SlotError("That clip has no clutch, ace or three kills together to build with.")
    return _swap_take(project, b)


# ------------------------------------------------------------------ remove

def _tail_room(shot: dict) -> float:
    """Reel seconds the shot can run on past its end: footage, and no other kill shown."""
    secs = float(shot.get("clip_seconds") or 0.0)
    _a, end_src = studio._span(shot)
    later = [float(k) for k in shot.get("kills") or []] + [float(k) for k in shot.get("_clip_kills") or []]
    stop = min([secs - EDGE] + [k - 0.3 for k in later if k > end_src + 1e-6])
    ps = studio.shot_pieces(shot)
    rate = ps[-1][2] if ps else 1.0
    return max(0.0, (stop - end_src) / max(rate, 1e-6))


def _head_room(shot: dict) -> float:
    """Reel seconds the shot can start sooner by: footage, and no earlier kill shown."""
    start_src, _b = studio._span(shot)
    earlier = [float(k) for k in shot.get("_clip_kills") or []]
    stop = max([EDGE] + [k + 0.3 for k in earlier if k < start_src - 1e-6])
    ps = studio.shot_pieces(shot)
    rate = ps[0][2] if ps else 1.0
    return max(0.0, (start_src - stop) / max(rate, 1e-6))


def _grow_tail(shot: dict, by: float) -> None:
    shot["duration"] = round(float(shot["duration"]) + by, 5)


def _grow_head(shot: dict, by: float) -> None:
    shot["pre"] = round(float(shot["pre"]) + by, 5)
    shot["duration"] = round(float(shot["duration"]) + by, 5)


def _footage_ok(shot: dict) -> bool:
    secs = float(shot.get("clip_seconds") or 0.0)
    a, b = studio._span(shot)
    return a >= -1e-4 and b <= secs + 1e-4


def close(project: dict, i: int, clip_kills: dict | None = None) -> dict:
    """Shot i taken out; the shot before runs on and the one after starts sooner to cover it.

    `clip_kills` is every kill of each clip, by lower-cased path, so a stretched shot never
    reaches another of its clip's kills (which would land off every beat). -> project"""
    shots = project["shots"]
    if len(shots) <= 1:
        raise SlotError("A reel needs at least one shot.")
    if not 0 <= i < len(shots):
        raise SlotError("That shot is not in the reel any more.")
    take = take_shots(project)
    if i in take:
        raise SlotError("The build is one take into the drop: swap it for another take instead.")
    out = copy.deepcopy(project)
    sh = out["shots"]
    for s in sh:
        s["_clip_kills"] = list((clip_kills or {}).get(str(s["clip"]).lower(), []))
    gap = float(sh[i]["duration"])
    prev = sh[i - 1] if i > 0 else None
    nxt = sh[i + 1] if i + 1 < len(sh) else None
    # the take's last shot is the drop: it does not run on past where the quick kills begin
    can_prev = _tail_room(prev) if prev is not None and (i - 1) not in take[:-1] else 0.0
    can_next = _head_room(nxt) if nxt is not None else 0.0
    # the reel's first shot gone: the reel may simply start later in the song
    can_start = gap if i == 0 else 0.0
    # the last shot gone: the reel may simply end sooner -- that is a shorter reel, said as such
    if nxt is None and can_prev + 1e-3 < gap:
        raise SlotError(f"The shot before it has {can_prev:.1f} s more footage, not the {gap:.1f} s this shot "
                        f"runs; end the reel before it instead, or fill it with another clip.")
    y = min(can_next, gap / 2 if prev is not None and can_prev > 0 else gap)
    x = min(can_prev, gap - y)
    y = min(can_next, gap - x)
    rest = gap - x - y
    if rest > 1e-3 and rest > can_start + 1e-6:
        who = []
        if prev is not None:
            who.append(f"the shot before it has {can_prev:.1f} s more footage after its kill")
        if nxt is not None:
            who.append(f"the shot after it {can_next:.1f} s before its")
        raise SlotError(f"The gap is {gap:.1f} s and " + " and ".join(who) + ": not enough to close it. "
                        "Fill it with another clip instead.")
    if x > 0:
        _grow_tail(prev, x)
    if y > 0:
        _grow_head(nxt, y)
    if rest > 1e-3:
        out["song_offset"] = round(float(out.get("song_offset") or 0.0) + rest, 5)
    for s in (prev, nxt):
        if s is not None and not _footage_ok(s):
            raise SlotError("The shots either side do not have the footage to close the gap.")
    del sh[i]
    for s in sh:
        s.pop("_clip_kills", None)
    out.pop("remark", None)
    return out


def shorten(project: dict, i: int, beat: float | None = None) -> dict:
    """The reel ending before shot i: the shot before runs on to the next beat, as far as it can. -> project"""
    shots = project["shots"]
    take = take_shots(project)
    if not 1 <= i < len(shots):
        raise SlotError("The reel cannot end before its first shot." if i <= 0 else "That shot is not in the reel any more.")
    if take and i <= take[-1]:
        raise SlotError("The reel cannot end inside its build.")
    out = copy.deepcopy(project)
    out["shots"] = out["shots"][:i]
    last = out["shots"][-1]
    beat = float(beat or project.get("beat") or 0.5)
    # on to a whole beat at least OUTRO_AFTER_KILL past the kill, as far as its footage goes
    after = float(last["duration"]) - float(last["pre"])
    want = max(after, studio.OUTRO_AFTER_KILL)
    want = beat * max(1, -(-want // beat))
    grow = max(0.0, min(want - after, _tail_room(dict(last, _clip_kills=[]))))
    _grow_tail(last, grow)
    out.pop("remark", None)
    return out
