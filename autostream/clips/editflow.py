r"""ONE REEL, THREE EDITORS -- and what each change does to it.

A reel is made by the guide, rebuilt by the Make page (Rebuild, "Add clips...")
and edited on the timeline, and the song's part, its kill marks and its drops
can be changed in all three. They used to behave three ways: dragging the part
on the Song tab carried every kill mark along with it, a fixed distance from
the part's start, so the marks left the beats they were on and nothing said the
timing was out of date -- and Render rendered it. Rebuild could throw away the
timeline's edits without a word.

THE INVARIANT this module exists for: never silently discard an explicit edit,
and never render a plan that no longer matches the reel's own choices.

THREE THINGS, KEPT APART
    the spec     what the player chose: song, part, kill marks, drops, style...
    the plan     the shots, and the timing of every cut and kill
    the render   the file, and what it was made from (clips/versions.py)

The plan lives in the project's ordinary fields -- `song`, `song_offset`,
`part_end`, `song_marks`, `hand_drops`, and the shots -- because that is what
the render reads. A timing choice the player has made and the plan has NOT yet
caught up with is the project's `draft`: the part dragged somewhere else, the
marks tapped again, the drops moved. While there is a draft, the reel's timing
is STALE, and it stays stale until the player says how to resolve it: plan the
reel again for it, keep the shots and re-time them, or undo the change. Nothing
re-plans on its own. Undoing the change is deleting the draft, which is why it
needs no re-planning: the plan was never touched.

`anchors` are the marks the player placed by hand (K, a dragged mark, "where
the kills are now"): song-time constraints that nothing moves except the
player. Marks the planner placed are disposable and are placed again.

THE DEPENDENCY TABLE says, for every kind of change, what has to happen to the
reel before it is right again -- only a re-render, a re-time of the shots, or a
new plan. The page reads it from the catalog, so every control and every style
answers from the same table; the server classifies with it too.
"""
from __future__ import annotations

import copy
import json
import math
import zlib
from dataclasses import asdict, dataclass

# ------------------------------------------------------------------ actions

RERENDER, TIMELINE, RETIME, REPLAN = "rerender", "timeline", "retime", "replan"
# How much of the reel an action redoes. A change that needs a re-time also
# needs a re-render; one that needs a new plan needs both.
STRENGTH = {RERENDER: 0, TIMELINE: 1, RETIME: 2, REPLAN: 3}

# WHAT EACH ACTION KEEPS AND WHAT IT CHANGES, in the words the page shows before
# anything runs. Written once here so the three buttons, the "Add clips" choice
# and every control's one-line note say the same thing.
ACTIONS = {
    RERENDER: {
        "label": "Re-render", "says": "re-renders only",
        "keeps": ["every shot: its clip, its place and its trims",
                  "where every kill lands on the song",
                  "your kill marks and drops"],
        "changes": ["how it looks: effects, camera, colour, overlays, framing and lyrics are drawn again"],
    },
    TIMELINE: {
        "label": "Timeline edit", "says": "edits the timeline; the shots around it are re-timed",
        "keeps": ["every other shot's clip and effects", "your kill marks and drops"],
        "changes": ["the shots next to the edit move to keep their kills on the beat"],
    },
    RETIME: {
        "label": "Re-time", "says": "re-times your shots",
        "keeps": ["the clips and their order", "each shot's trims, as far as the new spacing allows",
                  "locked shots, pins and each shot's effects", "the kill marks you placed by hand"],
        "changes": ["where each kill lands: on the beats and hits of the song part as it is now",
                    "AutoStream's own kill marks, which are placed again"],
    },
    REPLAN: {
        "label": "Replan", "says": "plans the reel again",
        "keeps": ["the song, the part and the kill marks you placed by hand",
                  "your drops", "the reel's own look: facecam, handle, ending and lyrics",
                  "each shot's effects, where the same kill is still in the reel and the style is the same"],
        "changes": ["which clips and moments become shots", "the order and every cut",
                    "edits you made on the timeline to shots the new plan does not keep"],
    },
}


@dataclass(frozen=True)
class Change:
    key: str
    label: str
    action: str
    fallback: str = ""          # what it becomes when the action cannot be done
    offer: str = ""             # what a stale banner leads with, when not the action
    revalidate: bool = False    # the result must be checked again (framing, shape)
    scope: str = "reel"         # "reel", "local" (one shot and its neighbours) or "affected"
    says: str = ""              # the one line a control shows: what it changes, what it keeps


# THE TABLE. One row per kind of change a player can make, and what it needs.
CHANGES = (
    Change("style", "Style or template", REPLAN,
           says="Plans the reel again; your marks, drops and the reel's look are kept."),
    # A NEW PART LEADS WITH REPLAN, though re-timing would do. The table's action
    # is what the change needs at the least -- the shots can stay and be re-timed
    # -- and the banner's `offer` is what the player is shown first, highlighted:
    # a new section usually wants a plan of its own, and Hardik asked for that
    # button to be the one nobody can miss. Re-time stays one click beside it.
    Change("part", "Song or part", RETIME, fallback=REPLAN, offer=REPLAN,
           says="Makes the kill timing stale until you replan or re-time; nothing moves on its own."),
    Change("drop", "Drop, for a style built on it", REPLAN,
           says="Plans the reel again around the drop."),
    Change("mark", "A kill mark placed by hand", RETIME,
           says="Re-times your shots onto it; your marks are never moved for you."),
    Change("kills_now", "\"Where the kills are now\"", RETIME,
           says="Locks the kills where they are as your own marks, then re-times."),
    Change("clips", "Add or remove clips", REPLAN, scope="affected",
           says="Plans the shots those clips affect again."),
    Change("replace", "Replace a shot's clip", RETIME, fallback=REPLAN, scope="local",
           says="Re-times that shot and its neighbours; replans only if it cannot fit."),
    Change("trim", "Trim or move a shot", TIMELINE, scope="local",
           says="A timeline edit; the shots around it are re-timed."),
    Change("look", "Effect, camera, overlay or colour", RERENDER,
           says="Re-renders only."),
    Change("framing", "Framing or shape", RERENDER, revalidate=True,
           says="Re-renders only, then the reel is checked again."),
    Change("lyrics", "Lyric look", RERENDER,
           says="Re-renders only."),
    Change("intro", "Intro or ending", TIMELINE,
           says="A timeline edit; the reel is re-timed around it."),
    Change("length", "How long, order or what goes in", REPLAN,
           says="Plans the reel again."),
    Change("fades", "Fades or export quality", RERENDER,
           says="Re-renders only."),
)
BY_KEY = {c.key: c for c in CHANGES}

# WHICH CHANGE a field of the project belongs to. Top-level keys; a shot's own
# fields are below. A key not named is one nothing re-renders for (a name, the
# output path, the planner's own notes).
FIELDS = {
    "style": "style", "pools": "style", "mix_free": "style", "seed": "style",
    "song": "part", "song_offset": "part", "part_end": "part", "draft": "part", "beat": "part", "step": "part",
    "song_marks": "mark", "anchors": "mark",
    "hand_drops": "drop", "song_drop": "drop",
    "selection": "clips",
    "arrange": "length", "pins": "length", "hs_only": "length", "fill": "length", "keep_all": "length",
    "build_clip": "length", "part_auto": "length",
    "grade": "look", "vignette": "look", "overlays": "look", "saturation": "look", "handle": "look",
    "handle_pos": "look", "cam": "look", "music_db": "look", "game_db": "look", "duck": "look",
    "kill_sound": "look", "groove": "look",
    "format": "framing", "vfit": "framing",
    "lyrics": "lyrics",
    "intro": "intro", "intro_clip": "intro", "outro": "intro",
    "outro_len": "fades",
}
SHOT_FIELDS = {
    "clip": "replace", "kill": "replace", "kills": "replace",
    "pre": "trim", "duration": "trim", "speed": "trim", "stretch": "trim", "anchors": "trim", "lock": "trim",
    "fx": "look", "hero": "look", "hero_fx": "look", "camera": "look", "transition": "look", "tlen": "look",
    "caption": "look",
}


def table() -> dict:
    """The table, as the page reads it from the catalog."""
    return {"actions": ACTIONS, "strength": STRENGTH,
            "changes": [asdict(c) for c in CHANGES]}


def action_for(key: str, *, drop_style: bool = False, feasible: bool = True) -> str:
    """What a change of this kind needs. A drop only matters to the plan in a style built on it;
    anywhere else moving it changes which kill gets the drop's flash, which is a re-time."""
    c = BY_KEY.get(key)
    if c is None:
        return RERENDER
    a = c.action
    if key == "drop" and not drop_style:
        a = RETIME
    if not feasible and c.fallback:
        a = c.fallback
    return a


def change_of(path: list[str] | tuple[str, ...]) -> str:
    """The kind of change a project field path belongs to ('' when none)."""
    if not path:
        return ""
    if path[0] == "shots":
        if len(path) < 3:
            return "trim"                     # a shot added, removed or moved
        return SHOT_FIELDS.get(str(path[2]), "look")
    return FIELDS.get(str(path[0]), "")


def classify(old: dict, new: dict) -> dict:
    """What a change from `old` to `new` needs. -> {"action", "changes": [keys]}

    The strongest action any changed field needs: a reel whose effect and part
    both changed needs re-timing, which re-renders too.
    """
    keys: list[str] = []

    def walk(a, b, at):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in set(a) | set(b):
                walk(a.get(k), b.get(k), at + [k])
        elif isinstance(a, list) and isinstance(b, list) and at and at[0] == "shots" and len(at) == 1:
            if len(a) != len(b) or [s.get("clip") for s in a] != [s.get("clip") for s in b]:
                # A shot added, removed or moved: "shot 3" names another shot in each,
                # so the shots are not compared one by one -- it is a timeline edit.
                keys.append(change_of(["shots"]))
                return
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, at + [str(i)])
        elif not _same(a, b):
            k = change_of(at)
            if k:
                keys.append(k)
    walk(old or {}, new or {}, [])
    keys = list(dict.fromkeys(keys))
    drop_style = bool((new or {}).get("style") == "drop")
    best = RERENDER if keys else ""
    for k in keys:
        a = action_for(k, drop_style=drop_style)
        if not best or STRENGTH[a] > STRENGTH[best]:
            best = a
    return {"action": best, "changes": keys}


def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            return False
    return a == b


# ------------------------------------------------------------------ the draft

def _f(v, default: float = 0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _times(raw, lo: float = 0.0, hi: float = 36000.0, cap: int = 200) -> list[float]:
    out = []
    for v in (raw or [])[:cap]:
        f = _f(v, -1.0)
        if lo <= f <= hi:
            out.append(round(f, 4))
    return sorted(set(out))


def plan_part(project: dict) -> tuple[float, float]:
    """The part of the song the shots are laid on, in song seconds."""
    start = _f(project.get("song_offset"))
    end = _f(project.get("part_end"))
    return start, end if end > start else 0.0


def tidy_draft(raw, project: dict) -> dict | None:
    """The draft as normalise keeps it: clamped, and only what differs from the plan.

    A draft that says what the plan already says is no draft -- dragging the
    part away and back again leaves nothing stale, which is how "if it did not
    change, do nothing" holds however the player got there.
    """
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    song = str(raw["song"]) if isinstance(raw.get("song"), str) else None
    if song is not None and song != str(project.get("song") or ""):
        out["song"] = song
    if "start" in raw or "end" in raw:
        s0, e0 = plan_part(project)
        s = max(0.0, _f(raw.get("start"), s0))
        e = _f(raw.get("end"), e0)
        if e <= s:
            e = 0.0
        if "song" in out or abs(s - s0) > 5e-4 or abs(e - e0) > 5e-4:
            out["start"], out["end"] = round(s, 4), round(e, 4)
    if isinstance(raw.get("marks"), list):
        marks = _times(raw["marks"])
        if "song" in out or marks != _times(project.get("song_marks")):
            out["marks"] = marks
    if "drops" in raw:
        d = raw["drops"]
        drops = None if d is None else _times(d, cap=64)
        planned = project.get("hand_drops")
        planned = None if planned is None else _times(planned, cap=64)
        if drops != planned:
            out["drops"] = drops
    return out or None


def timing_spec(project: dict) -> dict:
    """The timing the player has chosen: the plan's, overlaid with the draft."""
    d = project.get("draft") or {}
    start, end = plan_part(project)
    marks = d["marks"] if "marks" in d else _times(project.get("song_marks"))
    drops = d["drops"] if "drops" in d else (
        None if project.get("hand_drops") is None else _times(project.get("hand_drops"), cap=64))
    return {"song": d.get("song", str(project.get("song") or "")),
            "start": _f(d.get("start"), start), "end": _f(d.get("end"), end),
            "marks": marks, "drops": drops, "anchors": _times(project.get("anchors"))}


STALE_SAYS = {
    "song": "The song changed",
    "part": "Song part changed",
    "marks": "Your kill marks changed",
    "drops": "The drops changed",
}


def stale(project: dict) -> list[str]:
    """What the plan has not caught up with, in a fixed order. [] when the timing holds."""
    d = project.get("draft") or {}
    out = []
    if "song" in d:
        out.append("song")
    if "start" in d or "end" in d:
        out.append("part")
    if "marks" in d:
        out.append("marks")
    if "drops" in d:
        out.append("drops")
    return out


def stale_text(project: dict) -> str:
    why = stale(project)
    if not why:
        return ""
    return STALE_SAYS[why[0]] + " — kill timing needs updating"


def can_render(project: dict) -> str:
    """Why this project must not be rendered now; "" when it may.

    Checked by the server immediately before a render, whatever the page
    thought: a page that missed a draft still cannot render the old plan as if
    it were the new one.
    """
    why = stale_text(project)
    if why:
        return why + ". Replan for this section, keep your shots and re-time them, or undo the change, then render."
    return ""


def spec_rev(project: dict) -> str:
    """A revision id for the spec: eight hex digits of what was chosen."""
    s = timing_spec(project)
    keep = {k: project.get(k) for k in ("style", "format", "fill", "keep_all", "arrange", "hs_only", "build_clip")}
    keep["clips"] = [r.get("clip") for r in project.get("selection") or [] if isinstance(r, dict)]
    raw = json.dumps([s, keep], sort_keys=True, default=str)
    return f"{zlib.crc32(raw.encode('utf-8')) & 0xFFFFFFFF:08x}"


# ------------------------------------------------------------------ the new section's grid

def section_slots(shape, start: float, end: float) -> tuple[list[float], list[float]]:
    """(hits, beats) of the song inside [start, end]: where a kill in this section may land.

    The section's OWN grid, read from the song where the section is -- never the
    old part's phase or tempo carried over, which is what left every mark off
    the beat when the part moved.
    """
    hits = [float(h) for h in (getattr(shape, "hits", None) or []) if start - 1e-6 <= float(h) <= end + 1e-6]
    beats = [float(b) for b in (getattr(shape, "beats", None) or []) if start - 1e-6 <= float(b) <= end + 1e-6]
    return sorted(hits), sorted(beats)


def snap_to(t: float, hits: list[float], beats: list[float], beat: float) -> float:
    """The hit nearest `t` when one is within half a beat, else the nearest beat, else `t`."""
    best = min(hits, key=lambda h: abs(h - t)) if hits else None
    if best is not None and abs(best - t) <= beat / 2 + 1e-6:
        return best
    if beats:
        return min(beats, key=lambda b: abs(b - t))
    return t


def merge_anchors(marks: list[float], anchors: list[float], *, start: float, end: float,
                  beat: float) -> list[float]:
    """The planner's marks with the player's own put in: each hand mark inside the part
    takes the place of the planner's mark nearest it, or joins the list if none is near.

    The hand mark is never the one that moves.
    """
    out = sorted(float(m) for m in marks)
    reach = max(beat, 0.35)
    for a in sorted(float(x) for x in anchors):
        if not (start - 1e-6 <= a <= end + 1e-6):
            continue
        near = min(range(len(out)), key=lambda i: abs(out[i] - a)) if out else -1
        if near >= 0 and abs(out[near] - a) <= reach and out[near] not in anchors:
            out[near] = a
        elif not any(abs(m - a) < 0.03 for m in out):
            out.append(a)
        out.sort()
    return out


# ------------------------------------------------------------------ keep my shots, re-time them

def _gap(beat: float) -> float:
    return max(0.25, beat / 2)


def retime(project: dict, derived: dict, shape, *, relax: str = "", resnap: bool = False) -> dict:
    """KEEP MY SHOTS, RE-TIME THEM, as a dry run. -> {"project", "conflicts", "notes", "room", "dropped"}

    The clips, their order, their trims, locks, pins and effects all stay; only
    where each kill lands changes. Each kill keeps its place in the rhythm --
    so many beats into the part -- counted on the NEW section's own beats and
    snapped to its hits. A kill on a mark the player placed stays on that mark.

    A shorter part leaves out the shots nothing holds -- not locked, not pinned,
    not on a hand mark -- from the end first. If what is left still cannot fit,
    nothing is applied: the conflict is returned with its fixes, never hidden
    with speed-ups, repeated footage or empty frames. `relax` widens what may be
    left out: "unlocked" lets pinned and hand-marked shots go too, "all" lets
    locked ones go as well.

    A longer part keeps every shot and says how much room is left (`room`), so
    the page can ask whether to add shots.

    `project` is not changed; the result's project is a copy with the draft
    resolved.
    """
    from . import studio

    p = copy.deepcopy(project)
    spec = timing_spec(p)
    shots = p["shots"]
    rows = derived.get("shots") or []
    old_start = _f(p.get("song_offset"))
    old_beat = _f(p.get("beat"), 0.5) or 0.5
    new_beat = float(getattr(shape, "beat", 0.0) or old_beat)
    seconds = float(getattr(shape, "seconds", 0.0) or 36000.0)
    start = max(0.0, min(spec["start"], seconds - 1.0))
    end = spec["end"] if spec["end"] > start else min(seconds, start + float(derived.get("length") or 30.0))
    end = min(end, seconds)
    hits, beats = section_slots(shape, start, end)
    anchors = list(spec["anchors"])
    notes: list[str] = []
    conflicts: list[dict] = []

    if resnap and anchors:
        # The one thing that moves a hand mark: the player asking for it. Each
        # goes with the part, by how far the part moved, onto the nearest hit.
        moved = [round(snap_to(a + (start - old_start), hits, beats, new_beat), 4) for a in anchors]
        p["anchors"] = sorted(set(moved))
        if p.get("draft") and "marks" in p["draft"]:
            p["draft"]["marks"] = sorted(set(round(m + (start - old_start), 4) for m in p["draft"]["marks"]))
        anchors = list(p["anchors"])
        notes.append(f"{len(anchors)} mark(s) you placed moved with the part, each onto the nearest hit.")

    outside = [a for a in anchors if not (start - 1e-3 <= a <= end + 1e-3)]
    if outside and relax != "all":
        conflicts.append({
            "kind": "marks-outside",
            "text": (f"{len(outside)} of the kill marks you placed "
                     f"{'is' if len(outside) == 1 else 'are'} outside the new part "
                     f"({', '.join(_clock(a) for a in outside[:4])}). They are never moved for you."),
            "fixes": [{"fix": "resnap", "label": "Move my marks with the part"},
                      {"fix": "forget-outside", "label": "Forget the marks outside the part"}]})

    # Where each shot's kill is now, in song seconds, and what holds it there.
    kill_song = [old_start + _f(r.get("kill_reel")) for r in rows]
    held_by = {}
    for i, k in enumerate(kill_song):
        near = [a for a in anchors if abs(a - k) <= 2 * studio.ON_MARK + 1e-6 and a not in outside]
        if near:
            held_by[i] = min(near, key=lambda a: abs(a - k))
    pinned_clips = {str(v).lower() for v in (p.get("pins") or {}).values()}

    def weight(i: int) -> int:
        """0: may go first. 1: only when relaxed to "unlocked". 2: only when relaxed to "all"."""
        s = shots[i]
        if s.get("lock"):
            return 2
        if i in held_by or str(s.get("clip") or "").lower() in pinned_clips:
            return 1
        return 0

    explicit = p.get("draft", {}).get("marks") if isinstance(p.get("draft"), dict) else None
    part_moved = abs(start - old_start) > 5e-4 or "song" in (p.get("draft") or {})
    if explicit is not None and not part_moved:
        # Only the marks changed: they are the player's list, laid on as they are.
        targets = [m for m in sorted(explicit) if start - 1e-3 <= m <= end + 1e-3]
    else:
        # Each kill keeps its place in the rhythm, counted on the new section's beats.
        targets = []
        prev = -1e9
        for i in range(len(shots)):
            if i in held_by:
                t = held_by[i]
            else:
                rel = (kill_song[i] - old_start) / old_beat if i < len(kill_song) else (len(targets) + 1)
                t = snap_to(start + rel * new_beat, hits, beats, new_beat)
            if t <= prev + _gap(new_beat) - 1e-6:
                later = [h for h in (hits or beats) if h > prev + _gap(new_beat) - 1e-6]
                t = later[0] if later else prev + _gap(new_beat)
            targets.append(round(t, 4))
            prev = t
        targets = merge_anchors(targets, [a for a in anchors if a not in outside],
                                start=start, end=end, beat=new_beat)

    # THE LAST KILL NEEDS ITS ENDING INSIDE THE PART. What each shot keeps after
    # its kill now is what it will want after its new mark.
    def tail(i: int) -> float:
        s = shots[i]
        return max(0.3, _f(s.get("duration")) - _f(s.get("pre")))

    keep = list(range(len(shots)))
    dropped: list[str] = []
    limit_rank = {"": 0, "unlocked": 1, "all": 2}[relax if relax in ("unlocked", "all") else ""]

    def fits(kept: list[int]) -> tuple[bool, float]:
        """Whether the kept shots fit, with marks taken in order. -> (fits, seconds needed)"""
        if not kept:
            return True, 0.0
        n = min(len(kept), len(targets))
        # Fewer marks than shots (a list the player shortened): the first shots
        # take the marks and the rest follow at their own lengths, as they always have.
        need = (targets[n - 1] + tail(kept[n - 1])) if n else start
        need += sum(_f(shots[i].get("duration")) for i in kept[n:])
        return need <= end + 0.05, need - start

    ok, need = fits(keep)
    while not ok:
        cands = [i for i in reversed(keep) if weight(i) <= limit_rank]
        if not cands:
            break
        go = cands[0]
        keep.remove(go)
        dropped.append(str(shots[go].get("name") or f"Shot {go + 1}"))
        # A shot taken out closes up on the marks: the hand-held ones keep theirs.
        free = [t for t in targets if t not in held_by.values()]
        targets = sorted(set([held_by[i] for i in keep if i in held_by] +
                             free[:max(0, len(keep) - sum(1 for i in keep if i in held_by))]))
        ok, need = fits(keep)
    if not ok:
        held = [i for i in keep if weight(i) > limit_rank]
        conflicts.append({
            "kind": "too-short",
            "text": (f"The part is {end - start:.1f} s; the shots you kept need about {need:.1f} s. "
                     + (f"{len(held)} of them are locked, pinned or on your own marks, so none of those were left out."
                        if held else "")).strip(),
            "need": round(need, 2),
            "fixes": ([{"fix": "relax:unlocked", "label": "Leave out unlocked shots too"}] if limit_rank < 1 else [])
                     + [{"fix": "longer-part", "label": f"Make the part {need:.0f} s", "end": round(start + need + 0.5, 3)}]
                     + ([{"fix": "relax:all", "label": "Let locked shots go too"}] if limit_rank < 2 else [])})

    report = {"project": p, "conflicts": conflicts, "notes": notes, "dropped": dropped, "room": None,
              "part": [round(start, 4), round(end, 4)]}
    if conflicts:
        return report

    p["shots"] = [shots[i] for i in keep]
    if dropped:
        notes.append(f"The shorter part holds {len(keep)} of {len(shots)} shots; "
                     f"{len(dropped)} nothing held were left out: {', '.join(dropped[:6])}"
                     + (" and more." if len(dropped) > 6 else "."))
    p["song"] = spec["song"]
    drops = spec["drops"]
    if drops is None:
        p.pop("hand_drops", None)
    else:
        p["hand_drops"] = drops
    pres = {id(s): round(_f(s.get("pre")), 3) for s in p["shots"]}
    marks_now = targets[:len(p["shots"])]
    notes += studio.apply_song(p, shape, spec["song"], start, end, marks_now)
    kept_trim = sum(1 for s in p["shots"] if abs(round(_f(s.get("pre")), 3) - pres.get(id(s), -1)) <= 1.0 / 60)
    notes.append(f"Every shot kept its clip, its place and its effects; "
                 f"{kept_trim} of {len(p['shots'])} kept their run-up exactly.")
    # A LONGER PART: the room left is said, and marked, not filled behind the player's back.
    last = (marks_now[-1] if marks_now else start) + (tail(keep[-1]) if keep else 0.0)
    spare = end - last
    spacing = (marks_now[-1] - marks_now[0]) / max(1, len(marks_now) - 1) if len(marks_now) > 1 else new_beat * 2
    more = int(spare // max(spacing, _gap(new_beat))) if spare > 2 * 4 * new_beat else 0
    if more > 0:
        extra, t = [], marks_now[-1] if marks_now else start
        for _ in range(more):
            t = snap_to(t + spacing, hits, beats, new_beat)
            if t >= end - 0.3:
                break
            extra.append(round(t, 4))
        if extra:
            p["song_marks"] = sorted(set(list(p.get("song_marks") or []) + extra))
            report["room"] = {"marks": len(extra), "seconds": round(spare, 1)}
            notes.append(f"The part runs {spare:.0f} s past the last kill: {len(extra)} more mark(s) are on the "
                         f"song for more shots. Add shots, or replan for this section, to fill it.")
    p["anchors"] = [a for a in anchors if start - 1e-3 <= a <= end + 1e-3] if relax == "all" else anchors
    p.pop("draft", None)
    report["notes"] = notes
    return report


def _clock(t: float) -> str:
    m, s = divmod(max(0.0, float(t)), 60)
    return f"{int(m)}:{s:05.2f}"


# ------------------------------------------------------------------ the drop a style is built on

def main_drop(drops, shape_drop) -> float | None:
    """THE drop: the analysis's own, or the player's nearest it -- as the server reads the list."""
    if drops is None:
        return float(shape_drop) if shape_drop else None
    if not drops:
        return None
    if shape_drop:
        return min(drops, key=lambda t: abs(t - float(shape_drop)))
    return drops[0]


def drop_conflict(style_drop: bool, drops, shape_drop, start: float, end: float) -> dict | None:
    """A style built on a drop, with its drop outside the part: it cannot be made. -> conflict or None"""
    if not style_drop:
        return None
    d = main_drop(drops, shape_drop)
    if d is not None and start - 1e-3 <= d <= end + 1e-3:
        return None
    if d is not None:
        return {"kind": "drop-outside",
                "text": "This style is built on the drop, and the drop is outside the part.",
                "fixes": [{"fix": "move-to-drop", "label": "Move the part to the drop"},
                          {"fix": "mark-drop", "label": "Mark a drop in this part"},
                          {"fix": "other-style", "label": "Choose another style"}]}
    return {"kind": "drop-outside",
            "text": "This style is built on the drop, and this song has no drop marked.",
            "fixes": [{"fix": "mark-drop", "label": "Mark a drop"},
                      {"fix": "other-style", "label": "Choose another style"}]}


# ------------------------------------------------------------------ a plan, compared

def _kills_in_song(project: dict, derived: dict) -> dict:
    """{(clip, kill): song second it lands on} for every shot."""
    off = _f(project.get("song_offset"))
    out = {}
    for s, r in zip(project.get("shots") or [], derived.get("shots") or []):
        out[(str(s.get("clip") or "").lower(), round(_f(s.get("kill")), 2))] = off + _f(r.get("kill_reel"))
    return out


def plan_diff(old: dict, old_derived: dict, new: dict, new_derived: dict) -> dict:
    """What applying `new` over `old` changes, in the terms the player decides on."""
    a = [str(s.get("clip") or "") for s in old.get("shots") or []]
    b = [str(s.get("clip") or "") for s in new.get("shots") or []]
    name = {str(s.get("clip") or "").lower(): str(s.get("name") or "") for s in
            list(old.get("shots") or []) + list(new.get("shots") or [])}
    la, lb = {x.lower() for x in a}, {x.lower() for x in b}
    ka, kb = _kills_in_song(old, old_derived), _kills_in_song(new, new_derived)
    both = set(ka) & set(kb)
    moved = sum(1 for k in both if abs(ka[k] - kb[k]) > 0.05)
    return {
        "shots": [len(a), len(b)],
        "clips_in": sorted(name.get(x, x) for x in lb - la),
        "clips_out": sorted(name.get(x, x) for x in la - lb),
        "kills_kept": len(both) - moved, "kills_moved": moved,
        "kills_new": len(set(kb) - set(ka)), "kills_gone": len(set(ka) - set(kb)),
        "length": [round(_f(old_derived.get("length")), 2), round(_f(new_derived.get("length")), 2)],
        "on_marks": [int(old_derived.get("on_marks") or 0), int(new_derived.get("on_marks") or 0)],
        "edited": bool(old_derived.get("edited")),
    }


CARRIED = ("fx", "hero", "hero_fx", "camera", "transition", "caption")


def carry_edits(old: dict, new: dict) -> int:
    """Each shot's own effects, carried onto the new plan's shot with the same kill. -> how many.

    Only for a plan of the same style: a new style's effects are the point of
    choosing it. In place on `new`.
    """
    if old.get("style") != new.get("style"):
        return 0
    by = {(str(s.get("clip") or "").lower(), round(_f(s.get("kill")), 2)): s for s in old.get("shots") or []}
    n = 0
    for s in new.get("shots") or []:
        was = by.get((str(s.get("clip") or "").lower(), round(_f(s.get("kill")), 2)))
        if was is None:
            continue
        if any(was.get(k) != s.get(k) for k in CARRIED):
            for k in CARRIED:
                if k in was:
                    s[k] = copy.deepcopy(was[k])
            n += 1
    return n


def replan_request(project: dict, overrides: dict | None = None) -> dict:
    """The plan request that plans this reel again, on its spec as it is now.

    Everything the reel asked for goes with it -- the part, How long, Keep every
    kill, the order, pins, Headshots only, the build clip, the intro -- and the
    reel's own look rides in `keep`, so a new plan changes the shots and not the
    facecam. `overrides` may name another `style`, other `clips` or a `fill`.
    """
    o = overrides or {}
    spec = timing_spec(project)
    clips = o.get("clips") or [r["clip"] for r in project.get("selection") or [] if isinstance(r, dict) and r.get("clip")] \
        or list(dict.fromkeys(s["clip"] for s in project.get("shots") or []))
    shaping = dict(project.get("shaping") or {})
    shaping.update(arrange=project.get("arrange") or "build", pins=project.get("pins") or {},
                   hs_only=bool(project.get("hs_only")), fill=o.get("fill", project.get("fill") or ""),
                   keep_all=bool(project.get("keep_all")))
    if project.get("build_clip"):
        shaping["build_clip"] = project["build_clip"]
    body = {"clips": list(clips), "style": o.get("style") or project.get("style"),
            "song": spec["song"], "format": project.get("format"), "name": project.get("name"),
            "shaping": shaping, "intro_clip": project.get("intro_clip"), "vfit": project.get("vfit"),
            "keep": {k: project.get(k) for k in ("cam", "vfit", "handle", "handle_pos", "outro_len",
                                                 "overlays", "lyrics")}}
    if spec["song"] and spec["end"] > spec["start"]:
        body["part_start"], body["part_end"] = spec["start"], spec["end"]
        if project.get("part_auto") and "start" not in (project.get("draft") or {}):
            body["shaping"]["part_auto"] = True
    if spec["drops"] is not None:
        body["drops"] = list(spec["drops"])
    d = project.get("draft") or {}
    if "marks" in d:
        body["marks"] = list(d["marks"])        # the player's own list, deletions and all
    return body
