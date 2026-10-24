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

    def as_dict(self) -> dict:
        return asdict(self)


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def judge(*, style, song: dict | None, clips: int, kills: int, has_setup: bool = True,
          project: dict | None = None, notes: list[str] | None = None, part: tuple[float, float] | None = None,
          fmt: str = "vertical", error: str = "", headshots: int | None = None) -> Verdict:
    """The verdict for these choices. `style` is a studio.Style (or None)."""
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
    # Fast-paced headshot is headshots only (clips/fasthead.py): body kills never fill in.
    if getattr(style, "key", "") == "fasthead" and headshots is not None:
        if headshots < 8:
            return Verdict(BAD, f"{name} is headshots only, and {headshots} of these clips have a headshot; "
                                f"it needs at least 8.", "pick-clips", "Pick for me")
        # about one headshot a second, against the part that will be planned -- "rather than 36"
        # was said of a 30 s part as readily as of a 46 s one
        want = (part[1] - part[0]) if part and part[1] > part[0] else 36.0
        if headshots < 20:
            return Verdict(WARN, f"Only {headshots} of these clips have a headshot, so the reel will be about "
                                 f"{headshots} s rather than {want:.0f}.", "pick-clips", "Pick for me")
    if needs_drop and not has_setup:
        return Verdict(BAD, "Build and drop needs a clutch, an ace or three kills in one clip to build with.",
                       "pick-clips", "Pick the best")
    if error:
        return Verdict(BAD, error)
    if project is not None:
        shots = project.get("shots") or []
        if not shots:
            return Verdict(BAD, "These choices make no shots. Pick more clips or another part of the song.", "pick-clips", "Pick for me")
        length = sum(float(s.get("duration") or 0.0) for s in shots)
        if part and part[1] > part[0]:
            want = part[1] - part[0]
            if length < want * (1.0 - SHORT_BY) - 0.5:
                # SAY WHERE THE REEL STOPS SHORT, NOT ONLY BY HOW MUCH. "About 16 more quick kills"
                # was said of a Build and drop reel whose clips had already reached the last drum
                # hit before the song's break, and whose build take was 4.5 s of a 15 s lead-in:
                # adding clips -- or taking them away -- never moved it (JUST A BOY, 2026-10-24).
                # More clips are the fix only when the plan says its clips ran out.
                ran_out = any("clips ran out" in n for n in notes or [])
                start = float(project.get("song_offset") or part[0])
                end = start + length
                span = (round(start, 3), round(end, 3))
                if needs_drop and not ran_out and project.get("song_drop") is not None:
                    drop = float(project["song_drop"])
                    return Verdict(WARN, f"The song gives this reel {length:.0f} s, not {want:.0f}: the build clip "
                                         f"covers {max(0.0, drop - start):.1f} s before the drop and the drums after "
                                         f"it stop at {_mmss(end)}. More clips will not change that; a build clip "
                                         f"that runs longer, or a part around another drop, would.",
                                   "part:fit", f"Make the part {length:.0f} s", span=span)
                if not ran_out and getattr(style, "key", "") == "montage":
                    # Montage cuts its flurry on the drums the same way (director._after)
                    return Verdict(WARN, f"The reel runs {length:.0f} s of the {want:.0f} s part: the song has no "
                                         f"more hits for it after {_mmss(end)}, so more clips will not lengthen it.",
                                   "part:fit", f"Make the part {length:.0f} s", span=span)
                # HOW LONG A KILL RUNS IN THIS STYLE, from the plan itself: the middle shot, so a
                # build-and-drop take of eight seconds does not count as a kill's length. It was
                # 0.52 s for every style, which is Build and drop's quick kill and nobody else's.
                durs = sorted(float(s.get("duration") or 0.0) for s in shots)
                per = max(0.3, min(4.0, durs[len(durs) // 2] if durs else 0.52))
                short = int(max(1, round((want - length) / per)))
                what = ("quick kills" if needs_drop else
                        "headshots" if getattr(style, "key", "") == "fasthead" else "kills")
                return Verdict(WARN, f"The reel runs {length:.0f} s of the {want:.0f} s part: about {short} more {what} would fill it.",
                               "pick-clips", "Add the best")
        for n in notes or []:
            if "usual build-and-drop way" in n or "planned the usual way" in n or "planned without one" in n:
                return Verdict(WARN, f"{name} could not follow the song here, so it was planned the usual way: " + n.split(". ")[0] + ".",
                               fallback=True)
    if fmt != "vertical":
        return Verdict(WARN, "A Short or Reel is vertical; this shape shows black bars on a phone.", "format:vertical", "Use 9:16")
    return Verdict(OK, "This works.")
