"""Will this style, this song and these clips make a good reel? Said before anything renders.

WHY THIS EXISTS. The Make page let any style meet any song and any clips, and said
nothing until the reel was wrong: Build and drop on a song with no drop, a fast style
on an 89 BPM song, a reel that runs out of kills halfway through the part. The guided
maker asks one question at a time and has to say, at each step, whether the choices so
far work together -- and offer the one fix that makes them.

Three levels, about whether a plan EXISTS and not about taste:

    ok      a plan exists and nothing in it falls short
    warn    a plan exists, with a shortfall the player can act on
    bad     no plan can be made from these choices

`judge` is pure: it reads the facts (the style, the song's drops and tempo, how many
clips and kills, and -- when the planner was asked -- what it made) and returns one
verdict with one fix. The page's chips are this and nothing else, so what a chip says
is what the planner will do: the only rules here that are not the planner's own are the
two that cannot be learned by planning (a style that needs a drop, a style that needs
tempo), and both are the style's own declared needs.

ONE COUNT. How many more clips a reel needs is the planner's number (`fill["missing"]`:
the hits, or the shots at the style's pace, it had no clip for) and nothing else's. The
clip counter, the chip and "Add the best" each used to estimate it their own way -- a
two-kill clip as two kills, missing seconds over a kill's length -- and on JUST A BOY the
three disagreed: "50 of 41" chosen, "about 13 more", and a button that added nothing
(2026-10-24). The verdict carries the plan's length, its target and the clips it used,
so the counter is drawn from the same plan the chip judged.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

OK, WARN, BAD = "ok", "warn", "bad"
FAST_BPM = 110.0           # studio.FAST_BPM: under this a cut every second is not fast
SHORT_BY = 0.15            # a reel under this share short of its part is not worth a warning


@dataclass
class Verdict:
    level: str
    text: str
    fix: str = ""          # an action the page knows: "style:drop", "pick-clips", "shorter", "format:vertical"
    fix_label: str = ""
    # The style could not plan itself here and the reel was planned the general way: a reel, but
    # not that style's. "Pick the style for me" never chooses a style on these terms.
    fallback: bool = False
    # For fix "part:fit": the song seconds the plan actually covers, which the page makes the part.
    span: tuple[float, float] | None = None
    # For fix "pick-clips": how many more clips the plan says it is short, which "Add" adds.
    more: int = 0
    # What the plan made, when one was made: the counter on the Clips step is drawn from these,
    # never from an estimate of its own. `used` is the clips the reel plays.
    length: float = 0.0
    want: float = 0.0
    used: int = 0
    planned: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def judge(*, style, song: dict | None, clips: int, kills: int, has_setup: bool = True,
          project: dict | None = None, notes: list[str] | None = None, part: tuple[float, float] | None = None,
          fmt: str = "vertical", error: str = "", headshots: int | None = None,
          fill: dict | None = None) -> Verdict:
    """The verdict for these choices. `style` is a studio.Style (or None).

    `fill` is the planner's own account of what it could not fill (`missing`), beside the
    `project` it made; absent, the plan is taken to have had a clip for everything."""
    v = _judge(style=style, song=song, clips=clips, kills=kills, has_setup=has_setup, project=project,
               notes=notes, part=part, fmt=fmt, error=error, headshots=headshots, fill=fill)
    if project is not None and project.get("shots"):
        shots = project["shots"]
        v.planned = True
        v.length = round(sum(float(s.get("duration") or 0.0) for s in shots), 2)
        v.want = round(part[1] - part[0], 2) if part and part[1] > part[0] else 0.0
        v.used = len({s.get("clip") for s in shots if s.get("clip")})
    return v


def _judge(*, style, song, clips, kills, has_setup, project, notes, part, fmt, error, headshots,
           fill) -> Verdict:
    name = getattr(style, "label", "This style")
    if style is None:
        return Verdict(WARN, "Pick a style, or pick a song and we will choose one.")
    needs_drop = bool(getattr(style, "drop", False))
    fast = bool(getattr(style, "fast_cuts", False))
    if song:
        drops = song.get("drops") or ([song["drop"]] if song.get("drop") else [])
        bpm = float(song.get("bpm") or 0.0)
        if needs_drop and not drops:
            return Verdict(BAD, f"{name} needs a song with a drop, and this one has none.",
                           "pick-song", "Choose another song")
        # Fast-paced headshot sizes its cut to the tempo (clips/fasthead.py), so a slow song is not rushed
        if fast and not needs_drop and getattr(style, "key", "") != "fasthead" and bpm and bpm < FAST_BPM:
            return Verdict(WARN, f"{name} cuts fast and this song is {bpm:.0f} BPM; it will feel rushed.",
                           "style:drop" if drops else "pick-song",
                           "Use Build and drop" if drops else "Choose another song")
    if clips <= 0:
        return Verdict(BAD, "No clips are chosen yet.", "pick-clips", "Pick for me")
    # Fast-paced headshot is headshots only (clips/fasthead.py): body kills never fill in, and its
    # planner will not start on fewer than eight. How many more it wants beyond that is the plan's.
    if getattr(style, "key", "") == "fasthead" and headshots is not None and headshots < 8:
        return Verdict(BAD, f"{name} is headshots only, and {headshots} of these clips have a headshot; "
                            f"it needs at least 8.", "pick-clips", "Pick for me")
    if needs_drop and not has_setup:
        return Verdict(BAD, "Build and drop needs a clutch, an ace or three kills in one clip to build with.",
                       "pick-clips", "Pick the best")
    if error:
        return Verdict(BAD, error)
    works = "This works."
    if project is not None:
        shots = project.get("shots") or []
        if not shots:
            return Verdict(BAD, "These choices make no shots. Pick more clips or another part of the song.", "pick-clips", "Pick for me")
        length = sum(float(s.get("duration") or 0.0) for s in shots)
        missing = max(0, int((fill or {}).get("missing") or 0))
        if part and part[1] > part[0]:
            want = part[1] - part[0]
            if length < want * (1.0 - SHORT_BY) - 0.5:
                # THE PLAN'S OWN COUNT, IN CLIPS. It was seconds short over a kill's length, said
                # as kills: "about 11 more quick kills" on JUST A BOY turned into "This works" when
                # ONE two-kill clip was ticked, which read as one clip being worth eleven
                # (2026-10-24). The plan says how many hits it had no clip for, and each takes one
                # more clip -- every clip plays once, and a two-kill clip is one quick kill unless
                # its kills are close enough to be a run.
                if missing:
                    return Verdict(WARN, f"The reel runs {length:.0f} s of the {want:.0f} s part: the clips ran out "
                                         f"{missing} {'hit' if missing == 1 else 'hits'} before its end, so about "
                                         f"{missing} more clip{'s' if missing != 1 else ''} would fill it. "
                                         f"Each clip plays once.",
                                   "pick-clips", f"Add {missing} more", more=missing)
                # SAY WHERE THE REEL STOPS SHORT, NOT ONLY BY HOW MUCH. "About 16 more quick kills"
                # was said of a Build and drop reel whose clips had already reached the last drum
                # hit before the song's break, and whose build take was 4.5 s of a 15 s lead-in:
                # adding clips -- or taking them away -- never moved it (JUST A BOY, 2026-10-24).
                # The plan had a clip for every hit, so more clips are never the fix here.
                start = float(project.get("song_offset") or part[0])
                end = start + length
                span = (round(start, 3), round(end, 3))
                if needs_drop and project.get("song_drop") is not None:
                    drop = float(project["song_drop"])
                    return Verdict(WARN, f"The song gives this reel {length:.0f} s, not {want:.0f}: the build clip "
                                         f"covers {max(0.0, drop - start):.1f} s before the drop and the drums after "
                                         f"it stop at {_mmss(end)}. More clips will not change that; a build clip "
                                         f"that runs longer, or a part around another drop, would.",
                                   "part:fit", f"Make the part {length:.0f} s", span=span)
                return Verdict(WARN, f"The reel runs {length:.0f} s of the {want:.0f} s part: the song has no "
                                     f"more hits for it after {_mmss(end)}, so more clips will not lengthen it.",
                               "part:fit", f"Make the part {length:.0f} s", span=span)
            if length < want - 1.0:
                # within SHORT_BY: it works -- and says by how much, so a warning that clears
                # when one clip is added is not a mystery
                works = f"This works: the reel runs {length:.0f} s of the {want:.0f} s part."
        for n in notes or []:
            if "usual build-and-drop way" in n or "planned the usual way" in n or "planned without one" in n:
                return Verdict(WARN, f"{name} could not follow the song here, so it was planned the usual way: " + n.split(". ")[0] + ".",
                               fallback=True)
    if fmt != "vertical":
        return Verdict(WARN, "A Short or Reel is vertical; this shape shows black bars on a phone.", "format:vertical", "Use 9:16")
    return Verdict(OK, works)
