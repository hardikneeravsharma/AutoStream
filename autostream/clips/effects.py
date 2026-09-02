r"""Hand-placed effects on one finished clip: text, punch-ins, freezes, sounds.

WHAT THIS IS FOR
    The rest of the pipeline decides things FROM THE FOOTAGE -- where the kills
    are, how long a clip should be, what its caption can honestly claim. This
    module decides nothing. Every effect here is placed by a person who watched
    the clip and said "there", and this only has to put it exactly there.

    So the rules are different. Nothing is inferred, nothing is clamped into
    what looks reasonable, and an effect asked for outside the clip is an error
    rather than a silent adjustment -- because a person who dragged a marker to
    a spot will not go back and check that it stayed.

EVERY TIME IS A POSITION IN THE CLIP, NOT IN THE OUTPUT
    A freeze makes the output longer than the clip, so after one is added the
    two timelines stop agreeing. Effect times are always the CLIP's, because
    that is the thing on screen when the person places them -- they scrub to
    3.2s and put a caption there, and it must appear at what was 3.2s however
    many freezes end up before it.

    `at_output` does that mapping, and it is the only place the two timelines
    meet. Everything else in here works in clip time until the last moment.

WHY IT ALL HAPPENS IN ONE FILTER GRAPH
    Because each pass is a re-encode. Freeze, zoom, three captions and a sound
    done as five passes is five generations of h264 on the same clip, and the
    fifth looks it. One graph, one encode.

WHERE IT APPLIES
    The vertical export, for the reason overlay.py gives: the master is the
    editing copy, and burning anything into it forces whoever re-cuts it to
    work around what was burnt in. A freeze therefore makes the vertical
    longer than its master, which is expected -- the vertical is the thing
    being published.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .overlay import _CAPTION_FONTS, _HANDLE_FONTS, _esc, _font, _text, _wrap
from .tools import ffmpeg, media_info, video_codec_args

log = logging.getLogger("autostream.clips.effects")

# Where a caption sits, as a fraction of the height. The same three zones the
# rest of the app uses, and for the same reason: a Shorts player covers the
# bottom strip with its own title and controls, so "bottom" is above that
# rather than at the edge.
WHERE = {"top": 0.15, "middle": 0.46, "bottom": 0.70}

# How long a punch-in takes to arrive and to let go. Fast enough to feel like
# an edit rather than a drift, slow enough not to look like a glitch.
ZOOM_RAMP = 0.35
ZOOM_MIN, ZOOM_MAX = 1.05, 2.5

FREEZE_MIN, FREEZE_MAX = 0.1, 5.0
SOUND_GAIN_MAX = 3.0

# concat needs every piece in the same format, and a freeze introduces a piece
# made of silence rather than of the clip. Normalising both to this is what
# stops the join failing on a recording with an unusual layout.
MIX_RATE = 48000
MIX_LAYOUT = "stereo"


@dataclass
class Caption:
    """Words on screen from `at` until `until`, in clip seconds."""
    text: str
    at: float = 0.0
    until: float = 3.0
    where: str = "top"
    size: float = 1.0                # multiplier on the default


@dataclass
class Zoom:
    """A punch-in that arrives, holds, and lets go again."""
    at: float = 0.0
    until: float = 2.0
    to: float = 1.35


@dataclass
class Freeze:
    """Hold one frame. Everything after it moves later by `seconds`."""
    at: float = 0.0
    seconds: float = 0.7


@dataclass
class Sound:
    """A file mixed in on top, starting at `at`. The clip's own audio stays."""
    path: Path
    at: float = 0.0
    gain: float = 1.0


@dataclass
class Effects:
    captions: list[Caption] = field(default_factory=list)
    zooms: list[Zoom] = field(default_factory=list)
    freezes: list[Freeze] = field(default_factory=list)
    sounds: list[Sound] = field(default_factory=list)

    def any(self) -> bool:
        return bool(self.captions or self.zooms or self.freezes or self.sounds)


# --------------------------------------------------------------- the timeline

def ordered_freezes(freezes: list[Freeze]) -> list[Freeze]:
    """Freezes in the order they happen, with unusable ones dropped."""
    keep = [f for f in freezes
            if f.seconds >= FREEZE_MIN and f.at >= 0]
    return sorted(keep, key=lambda f: f.at)


def at_output(t: float, freezes: list[Freeze]) -> float:
    """A clip time -> where it lands once the freezes are in.

    A freeze at exactly this moment does NOT push it later. Placing a caption
    or a sound on a freeze means "while it is held" -- so it has to land at the
    start of the hold, not after it. Counting the freeze as before it would put
    the caption on screen the moment the picture starts moving again, which is
    precisely the wrong side.

    A span still spans it: a caption from 2s to 5s across a freeze at 3s
    becomes 2s to 6s, because its END is strictly after the freeze and does
    move.
    """
    out = float(t)
    for f in ordered_freezes(freezes):
        if f.at < t:
            out += min(FREEZE_MAX, f.seconds)
    return out


def output_seconds(clip_seconds: float, freezes: list[Freeze]) -> float:
    # Only the freezes that are actually rendered count -- _freeze_graph drops
    # any at or past the end, and a length that included them would not match
    # the file.
    held = sum(min(FREEZE_MAX, f.seconds) for f in ordered_freezes(freezes)
               if 0 <= f.at < clip_seconds)
    return float(clip_seconds) + held


# ------------------------------------------------------------------ checking

def problems(fx: Effects, clip_seconds: float) -> list[str]:
    """Everything wrong with this set of effects, in plain words.

    Reported rather than corrected. An effect quietly moved to somewhere legal
    is an effect that is not where it was put, and the person who put it there
    will not watch the whole clip again to find out.
    """
    said: list[str] = []
    end = float(clip_seconds)

    for i, c in enumerate(fx.captions, 1):
        what = f"Caption {i}"
        if not c.text.strip():
            said.append(f"{what} has no text.")
        if c.at < 0 or c.at > end:
            said.append(f"{what} starts at {c.at:.1f}s, outside the "
                        f"{end:.1f}s clip.")
        elif c.until <= c.at:
            said.append(f"{what} ends before it starts.")
        if c.where not in WHERE:
            said.append(f"{what} asks for a position called {c.where!r}.")

    for i, z in enumerate(fx.zooms, 1):
        what = f"Zoom {i}"
        if z.at < 0 or z.at > end:
            said.append(f"{what} starts outside the clip.")
        elif z.until <= z.at:
            said.append(f"{what} ends before it starts.")
        if not ZOOM_MIN <= z.to <= ZOOM_MAX:
            said.append(f"{what} is {z.to:.2f}x; keep it between "
                        f"{ZOOM_MIN} and {ZOOM_MAX}.")

    for i, f in enumerate(ordered_freezes(fx.freezes), 1):
        if f.at > end:
            said.append(f"Freeze {i} is past the end of the clip.")
        if f.seconds > FREEZE_MAX:
            said.append(f"Freeze {i} holds for {f.seconds:.1f}s; "
                        f"{FREEZE_MAX:.0f}s is the most.")

    for i, s in enumerate(fx.sounds, 1):
        what = f"Sound {i}"
        if not s.path or not Path(s.path).is_file():
            said.append(f"{what} points at a file that is not there.")
        if s.at < 0 or s.at > end:
            said.append(f"{what} starts outside the clip.")
        if not 0 < s.gain <= SOUND_GAIN_MAX:
            said.append(f"{what} has a volume of {s.gain:.2f}.")

    return said


# ------------------------------------------------------------- the filtergraph

def _freeze_graph(freezes: list[Freeze], clip_seconds: float,
                  fps: float, has_audio: bool) -> tuple[list[str], str, str]:
    """The trim/hold/concat chain. -> (parts, video label, audio label).

    HOW A FROZEN FRAME IS MADE
        Cut one frame out with trim, then tpad clones it for as long as the
        hold lasts. That is the whole trick; the rest is bookkeeping to put the
        pieces back in order.

        The silence beside it has to be built rather than borrowed, because
        concat refuses pieces whose audio does not match -- hence anullsrc and
        the aformat on both sides. A freeze with the clip's own audio running
        underneath would also be wrong: the picture has stopped, and sound
        continuing over a held frame reads as a dropped video feed.
    """
    order = ordered_freezes(freezes)
    order = [f for f in order if 0 <= f.at < clip_seconds]
    if not order:
        return [], "0:v", ("0:a" if has_audio else "")

    frame = 1.0 / fps if fps > 0 else 1.0 / 30.0
    parts: list[str] = []
    pieces: list[str] = []

    fmt = (f"aformat=sample_fmts=fltp:sample_rates={MIX_RATE}"
           f":channel_layouts={MIX_LAYOUT}")

    at = 0.0
    for i, f in enumerate(order):
        hold = max(FREEZE_MIN, min(FREEZE_MAX, f.seconds))
        # The clip up to the freeze. Skipped when two freezes touch, because a
        # zero-length piece is not something concat can use.
        if f.at - at > 1e-3:
            parts.append(f"[0:v]trim=start={at:.3f}:end={f.at:.3f},"
                         f"setpts=PTS-STARTPTS[v{i}]")
            pieces.append(f"[v{i}]")
            if has_audio:
                parts.append(f"[0:a]atrim=start={at:.3f}:end={f.at:.3f},"
                             f"asetpts=PTS-STARTPTS,{fmt}[a{i}]")
                pieces.append(f"[a{i}]")
        # The held frame.
        parts.append(f"[0:v]trim=start={f.at:.3f}:end={f.at + frame:.4f},"
                     f"setpts=PTS-STARTPTS,"
                     f"tpad=stop_mode=clone:stop_duration={hold:.3f}[z{i}]")
        pieces.append(f"[z{i}]")
        if has_audio:
            parts.append(f"anullsrc=channel_layout={MIX_LAYOUT}:"
                         f"sample_rate={MIX_RATE},atrim=duration={hold:.3f},"
                         f"asetpts=PTS-STARTPTS,{fmt}[s{i}]")
            pieces.append(f"[s{i}]")
        at = f.at

    # ...and whatever is left after the last freeze.
    tail = len(order)
    parts.append(f"[0:v]trim=start={at:.3f},setpts=PTS-STARTPTS[v{tail}]")
    pieces.append(f"[v{tail}]")
    if has_audio:
        parts.append(f"[0:a]atrim=start={at:.3f},asetpts=PTS-STARTPTS,"
                     f"{fmt}[a{tail}]")
        pieces.append(f"[a{tail}]")

    n = len(pieces) // (2 if has_audio else 1)
    parts.append("".join(pieces) +
                 f"concat=n={n}:v=1:a={1 if has_audio else 0}"
                 + ("[vcat][acat]" if has_audio else "[vcat]"))
    return parts, "vcat", ("acat" if has_audio else "")


def _zoom_expr(zooms: list[Zoom], freezes: list[Freeze]) -> str:
    """One expression giving the zoom factor at any moment. "" for none.

    A trapezoid per zoom -- in over ZOOM_RAMP, hold, out over ZOOM_RAMP -- and
    the largest one wins where two overlap. Ramping matters: a punch-in that
    arrives on one frame is indistinguishable from a glitch, and one that never
    returns leaves the rest of the clip cropped.
    """
    terms = []
    for z in zooms:
        a = at_output(z.at, freezes)
        b = at_output(z.until, freezes)
        if b <= a or z.to <= 1.0:
            continue
        to = max(ZOOM_MIN, min(ZOOM_MAX, z.to))
        r = min(ZOOM_RAMP, (b - a) / 2.0)
        if r <= 0:
            continue
        terms.append(f"({to}-1)*min(1,max(0,(t-{a:.3f})/{r:.3f}))"
                     f"*min(1,max(0,({b:.3f}-t)/{r:.3f}))")
    if not terms:
        return ""
    lift = terms[0]
    for extra in terms[1:]:
        lift = f"max({lift},{extra})"
    return f"1+{lift}"


def _caption_parts(captions: list[Caption], freezes: list[Freeze],
                   width: int, height: int, label: str) -> tuple[list[str], str]:
    """drawtext per caption, each gated to its own stretch of time."""
    font = _font(_CAPTION_FONTS) or _font(_HANDLE_FONTS)
    if not font:
        log.warning("no usable font found; captions were not drawn")
        return [], label
    parts = []
    for i, c in enumerate(captions):
        text = (c.text or "").strip()
        if not text:
            continue
        a = at_output(c.at, freezes)
        b = at_output(c.until, freezes)
        if b <= a:
            continue
        size = max(28, int(height * 0.052 * max(0.4, min(2.0, c.size))))
        y = int(height * WHERE.get(c.where, WHERE["top"]))
        # A textfile, not text=, for the same reason overlay.py uses one: this
        # is whatever a person typed, and apostrophes and commas in it would
        # otherwise need escaping through two layers of filtergraph parsing.
        parts.append(
            f"[{label}]drawtext=fontfile='{_esc(font)}'"
            f":textfile='{_esc(str(c._file))}'"
            f":fontcolor=white:fontsize={size}:line_spacing=0:text_align=C"
            f":borderw={max(3, size // 22)}:bordercolor=black@0.9"
            f":shadowcolor=black@0.6:shadowx=3:shadowy=3"
            f":x=(w-text_w)/2:y={y}"
            f":enable='between(t,{a:.3f},{b:.3f})'[cap{i}]")
        label = f"cap{i}"
    return parts, label


def _sound_parts(sounds: list[Sound], freezes: list[Freeze],
                 audio_label: str, first_input: int) -> tuple[list[str], list[str], str]:
    """-> (filter parts, extra ffmpeg inputs, the label carrying the mix).

    amix with normalize=0. With it on, mixing anything in quietens the clip's
    own audio in proportion -- so adding a sound effect would duck the gunfire
    it is meant to sit on top of, which is not what anybody means by adding a
    sound.
    """
    usable = [s for s in sounds if s.path and Path(s.path).is_file()]
    if not usable or not audio_label:
        return [], [], audio_label

    inputs: list[str] = []
    parts: list[str] = []
    labels = [f"[{audio_label}]"]
    fmt = (f"aformat=sample_fmts=fltp:sample_rates={MIX_RATE}"
           f":channel_layouts={MIX_LAYOUT}")
    for i, s in enumerate(usable):
        idx = first_input + i
        inputs += ["-i", str(s.path)]
        delay = int(max(0.0, at_output(s.at, freezes)) * 1000)
        gain = max(0.01, min(SOUND_GAIN_MAX, s.gain))
        parts.append(f"[{idx}:a]{fmt},volume={gain:.3f},"
                     f"adelay={delay}:all=1[snd{i}]")
        labels.append(f"[snd{i}]")
    parts.append("".join(labels) +
                 f"amix=inputs={len(labels)}:duration=first"
                 f":dropout_transition=0:normalize=0[amixed]")
    return parts, inputs, "amixed"


def build(fx: Effects, width: int, height: int, clip_seconds: float,
          fps: float, has_audio: bool) -> tuple[str, list[str], str, str]:
    """-> (filtergraph, extra inputs, video label, audio label).

    An empty graph means there is nothing to do, and the caller should leave
    the clip alone rather than re-encode it to no purpose.
    """
    parts, vlabel, alabel = _freeze_graph(fx.freezes, clip_seconds, fps,
                                          has_audio)

    zoom = _zoom_expr(fx.zooms, fx.freezes)
    if zoom:
        # Scale up by the factor, then crop back to the frame. The obvious
        # alternative -- cropping a smaller box each frame -- cannot work: a
        # filter's output size is fixed when it is set up, so an animated crop
        # is not something ffmpeg will accept.
        parts.append(
            f"[{vlabel}]scale=w='2*round(iw*({zoom})/2)'"
            f":h='2*round(ih*({zoom})/2)':eval=frame,"
            f"crop={width}:{height}[zoomed]")
        vlabel = "zoomed"

    cap_parts, vlabel = _caption_parts(fx.captions, fx.freezes, width, height,
                                       vlabel)
    parts += cap_parts

    snd_parts, inputs, alabel = _sound_parts(fx.sounds, fx.freezes, alabel, 1)
    parts += snd_parts

    if not parts:
        return "", [], vlabel, alabel
    return ";".join(parts), inputs, vlabel, alabel


def apply(src: Path, out: Path, fx: Effects, *, encoder: str = "auto",
          cq: int = 20) -> Path | None:
    """Render `src` with `fx` applied. -> the output, or None if nothing to do.

    Raises ValueError listing everything wrong, rather than rendering a clip
    with an effect silently in the wrong place.
    """
    if not fx.any():
        return None

    info = media_info(src)
    width, height = int(info["width"]), int(info["height"])
    fps = float(info["fps"] or 60.0)
    seconds = float(info["duration"] or 0.0)
    has_audio = bool(info.get("audio_tracks"))

    wrong = problems(fx, seconds)
    if wrong:
        raise ValueError(" ".join(wrong))

    # Caption text goes to files beside the output, for the escaping reason in
    # _caption_parts. Written before the graph is built because the graph
    # refers to them by path.
    scratch = out.parent / f".{out.stem}.fx"
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        for i, c in enumerate(fx.captions):
            f = scratch / f"cap{i}.txt"
            # newline forced, as overlay.py explains: Python would write \r\n
            # on Windows and drawtext renders the carriage return as a line.
            f.write_text(_wrap((c.text or "").strip()), encoding="utf-8",
                         newline="\n")
            c._file = f

        graph, inputs, vlabel, alabel = build(fx, width, height, seconds, fps,
                                              has_audio)
        if not graph:
            return None

        tmp = out.with_suffix(".fx.mp4")
        args = ["-i", str(src), *inputs, "-filter_complex", graph,
                "-map", f"[{vlabel}]" if vlabel != "0:v" else "0:v"]
        if has_audio:
            args += ["-map", f"[{alabel}]" if alabel != "0:a" else "0:a"]
        args += [*video_codec_args(encoder, cq=cq),
                 "-c:a", "aac", "-b:a", "160k",
                 "-movflags", "+faststart", "-y", str(tmp)]
        ffmpeg(*args)

        out.unlink(missing_ok=True)
        tmp.rename(out)
        log.info("effects on %s: %d caption(s), %d zoom(s), %d freeze(s), "
                 "%d sound(s)", out.name, len(fx.captions), len(fx.zooms),
                 len(ordered_freezes(fx.freezes)), len(fx.sounds))
        return out
    finally:
        import shutil

        shutil.rmtree(scratch, ignore_errors=True)


# The caption's text file is an implementation detail of one render, so it
# lives on the instance rather than in the dataclass's declared fields.
Caption._file = None
