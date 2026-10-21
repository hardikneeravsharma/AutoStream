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
    fix: str = ""          # an action the page knows: "style:story", "pick-clips", "shorter", "format:vertical"
    fix_label: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def judge(*, style, song: dict | None, clips: int, kills: int, has_setup: bool = True,
          project: dict | None = None, notes: list[str] | None = None, part: tuple[float, float] | None = None,
          fmt: str = "vertical", error: str = "") -> Verdict:
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
                short = int(max(1, round((want - length) / 0.52)))
                return Verdict(WARN, f"The reel runs {length:.0f} s of the {want:.0f} s part: about {short} more quick kills would fill it.",
                               "pick-clips", "Add the best")
        for n in notes or []:
            if "usual build-and-drop way" in n or "planned the usual way" in n or "planned without one" in n:
                return Verdict(WARN, f"{name} could not follow the song here, so it was planned the usual way: " + n.split(". ")[0] + ".")
    if fmt != "vertical":
        return Verdict(WARN, "A Short or Reel is vertical; this shape shows black bars on a phone.", "format:vertical", "Use 9:16")
    return Verdict(OK, "This works.")
