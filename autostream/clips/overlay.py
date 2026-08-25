r"""Captions and channel branding burned into the vertical exports.

WHERE THE CAPTION TEXT COMES FROM
    Only from things the pipeline actually knows. The kill scan records, per
    event, how many markers were on screen AT ONCE -- and that, not the gap
    between events, is the rapid-multikill signal. MERGE_GAP is three seconds,
    so two kills closer together than that cannot appear as separate events at
    all; they collapse into one event with a higher count. A caption derived
    from inter-event gaps would therefore be describing an artefact of the
    detector rather than anything that happened in the match.

    Anything not derivable is simply not claimed. There is no caption that
    guesses.

WHY THE OVERLAY GOES ON THE VERTICAL AND NOT THE MASTER
    The master is the editing copy: burning text into it would force anyone
    re-cutting it to work around the caption. The vertical is the finished
    export, so that is where it belongs.

PLACEMENT
    Caption in the upper third, branding above the bottom sixth. Both avoid the
    zones a Shorts/Reels player covers with its own UI -- the bottom strip for
    title and controls, the right edge for the button rail. A caption that
    lands under the like button is a caption nobody reads.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .. import paths
from .tools import ffmpeg, video_codec_args

log = logging.getLogger("autostream.clips.overlay")

# Fonts, in preference order. Impact is the gaming-caption default and is on
# every Windows install; the rest are fallbacks for stripped-down images.
_CAPTION_FONTS = ("impact.ttf", "arialbd.ttf", "segoeuib.ttf", "seguivar.ttf")
_HANDLE_FONTS = ("segoeuib.ttf", "arialbd.ttf", "seguivar.ttf")

_FONT_DIR = Path(r"C:\Windows\Fonts")

# Fractions of frame height. The bottom sixth of a Short is covered by the
# player's own chrome, so nothing of ours goes below 0.86.
CAPTION_Y = 0.15
BRAND_Y = 0.855
SAFE_X = 0.055

# 0 means the whole clip. It was 2.6 seconds on the reasoning that a caption
# has done its job by then and afterwards only covers the gameplay it is
# advertising -- but a Short is watched on a loop and scrubbed into halfway
# through, and a viewer arriving at second eight then has nothing telling them
# what they are looking at. The caption sits in the blurred bar above the
# picture anyway, so it costs no gameplay to leave it up.
CAPTION_SECONDS = 0.0

# The spoken hook, written out underneath. Placed BELOW the picture rather than
# over it: in "fit" verticals the gameplay occupies roughly the middle third and
# everything from 0.68 down is blurred backdrop, so this lands in empty space
# and still clears the branding at 0.855.
SUB_Y = 0.715
SUB_WRAP = 30              # characters per line before wrapping
SUB_FADE_IN = 0.25
SUB_HOLD = 0.35            # stays this long after the voice stops
SUB_FADE_OUT = 0.55


def _font(names) -> str | None:
    for n in names:
        p = _FONT_DIR / n
        if p.is_file():
            return str(p)
    return None


def _esc(path: str) -> str:
    r"""ffmpeg filter syntax eats colons and backslashes, so a Windows font
    path has to become C\:/Windows/Fonts/impact.ttf or the filtergraph fails
    to parse with an error that blames the wrong thing."""
    return path.replace("\\", "/").replace(":", r"\:")


def _wrap(text: str, width: int = SUB_WRAP) -> str:
    """Break a hook into lines that fit the frame.

    Greedy, and deliberately not clever: these are two short clauses, so the
    only thing that matters is that a forty-character line does not run off
    both edges of a 1080-wide frame.
    """
    words, lines, line = str(text or "").split(), [], ""
    for w in words:
        if line and len(line) + 1 + len(w) > width:
            lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        lines.append(line)
    return "\n".join(lines)


def _text(s: str) -> str:
    """Escape a caption for drawtext. Apostrophes are the common one."""
    return (s.replace("\\", r"\\").replace(":", r"\:")
             .replace("'", r"\'").replace("%", r"\%"))


# ------------------------------------------------------------ tag detectors
#
# A tag detector is the same band + template machinery the kill scan uses, but
# evaluated ONLY at the handful of timestamps a kill was already found at.
# Forty-odd frames instead of a hundred thousand, so it costs seconds.
#
# Measured on a real session before being enabled: the sniper silhouette scores
# 0.83-0.96 on sniper kills and 0.50-0.58 on everything else, so 0.70 sits in a
# gap with nothing in it. Verified against a frame chosen by the detector and
# not by hand.
TAG_TEMPLATES: dict[str, dict] = {
    "deltaforceclient.exe": {
        "sniper": {
            "template": "delta-force-sniper.npy",
            "band": (0.865, 0.880, 0.995, 0.945),   # weapon silhouette, bottom right
            "ref_height": 1080,
            "match_min": 0.70,
        },
    },
}


def detect_tags(source, kill_times: list[float], game_key: str | None,
                game_name: str | None = None) -> dict[float, list[str]]:
    """-> {kill time: [tags]}. Never raises; a failed tag is just no tag."""
    from .profiles import ALIASES, slug

    key = ALIASES.get((game_key or "").lower(), (game_key or "").lower())
    table = TAG_TEMPLATES.get(key)
    if not table and game_name:
        for k, v in TAG_TEMPLATES.items():
            if slug(k.replace(".exe", "")) in slug(game_name):
                table = v
                break
    if not table or not kill_times:
        return {}

    import numpy as np

    from .detect import ncc
    from .tools import ffmpeg_raw, media_info

    out: dict[float, list[str]] = {}
    try:
        info = media_info(source)
        W, H = info["width"], info["height"]
    except Exception:  # noqa: BLE001
        return {}

    for name, spec in table.items():
        tpl_path = (Path(__file__).resolve().parent / "templates" / spec["template"])
        if not tpl_path.is_file():
            continue
        tpl = np.load(tpl_path).astype(np.float32)
        t0 = tpl - tpl.mean()
        x1, y1, x2, y2 = spec["band"]
        x, y = round(W * x1), round(H * y1)
        w, h = round(W * x2) - x, round(H * y2) - y
        # Match at the template's own scale, the same rule the kill scan uses.
        rw, rh = tpl.shape[1], tpl.shape[0]
        for t in kill_times:
            try:
                raw = ffmpeg_raw(["-ss", f"{t + 0.2:.3f}", "-i", str(source),
                                  "-frames:v", "1", "-an", "-sn",
                                  "-vf", f"crop={w}:{h}:{x}:{y},"
                                         f"scale={rw}:{rh}:flags=bilinear,format=gray",
                                  "-f", "rawvideo", "-"])
                if len(raw) < rw * rh:
                    continue
                band = np.frombuffer(raw[:rw * rh], dtype=np.uint8) \
                         .reshape(rh, rw).astype(np.float32)
                if ncc(band, t0, 2.0)[0] >= spec["match_min"]:
                    out.setdefault(t, []).append(name)
            except Exception:  # noqa: BLE001
                continue
    return out


# --------------------------------------------------------------------- tags

def tags_for(plan, kills) -> list[str]:
    """Descriptive tags for one clip, from data already captured.

    `kills` is the subset of kill events inside this clip.
    """
    out: list[str] = []
    if not kills:
        return out
    burst = max((int(k.get("count", 1)) for k in kills), default=1)
    n = len(kills)

    # Markers on screen together mean kills too close to have been separately
    # aimed -- a spray transfer rather than two engagements.
    if burst >= 3:
        out.append("spray")
    elif burst == 2:
        out.append("double")
    if n >= 3:
        out.append("multi")
    return out


# How a round label reads when it is burned onto the picture. Only the ones
# that need reordering are here; every other label is already a caption.
CAPTIONS: tuple[tuple[str, str], ...] = (
    (r"^CLUTCH 1v(?P<n>\d+)$", "1v{n} CLUTCH"),
    (r"^ALMOST 1v(?P<n>\d+)$", "ALMOST A 1v{n}"),
    (r"^(?P<n>\d+)K IN (?P<s>\d+)s$", "{n}K IN {s} SECONDS"),
)


def caption_for(plan, kills, extra: list[str] | None = None) -> str:
    """The line burned onto the clip. Empty means no caption is drawn.

    Deliberately conservative: a wrong caption is worse than none, because it
    is the one part of the clip a viewer reads as a factual claim.

    THE LABEL WINS WHERE THERE IS ONE. A round clip already knows what it was,
    and counting its kills instead produced exactly the wrong claim: a 1v2
    clutch containing three kills was captioned "TRIPLE KILL", which is true
    about the kill count and wrong about the clip.
    """
    import re

    for label in (getattr(plan, "labels", None) or []):
        for pattern, template in CAPTIONS:
            m = re.match(pattern, label.strip(), re.IGNORECASE)
            if m:
                return template.format(**m.groupdict())
        return label.strip().upper()

    tags = set(tags_for(plan, kills)) | set(extra or [])
    n = getattr(plan, "kills", len(kills))

    if "sniper" in tags and n >= 2:
        return f"{n}K SNIPER"
    if "sniper" in tags:
        return "SNIPER KILL"
    if "spray" in tags:
        return f"{n}K SPRAY TRANSFER" if n >= 3 else "SPRAY TRANSFER"
    if n >= 4:
        return f"{n} KILLS"
    if n == 3:
        return "TRIPLE KILL"
    if "double" in tags or n == 2:
        return "DOUBLE KILL"
    return ""


# ------------------------------------------------------------------ render

def text_png(text: str, out: Path, *, size: int = 96, colour=(255, 255, 255),
             pad: int = 26) -> Path | None:
    r"""Render a line of text -- emoji included -- to a transparent PNG.

    ffmpeg's drawtext goes through libfreetype and renders a single glyph
    source, so a colour emoji font comes out as tofu or as flat monochrome
    outlines. Pillow can do it properly with embedded_color=True against
    seguiemj.ttf, so anything with emoji in it is drawn here and composited as
    an image instead.

    Plain ASCII captions still go through drawtext: it needs no temp file and
    can be time-gated with enable=, which an overlay cannot as cheaply.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    # Segoe UI Emoji only has real glyphs at certain sizes; it scales from its
    # own bitmap strikes, so an arbitrary size renders blank. 109 is the strike
    # Windows ships, and everything is scaled afterwards.
    STRIKE = 109
    font_path = _FONT_DIR / "seguiemj.ttf"
    if not font_path.is_file():
        return None
    try:
        font = ImageFont.truetype(str(font_path), STRIKE)
        probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        box = probe.textbbox((0, 0), text, font=font, embedded_color=True)
        w, h = box[2] - box[0], box[3] - box[1]
        if w <= 0 or h <= 0:
            return None
        im = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        ox, oy = pad - box[0], pad - box[1]
        # A shadow, because this lands over gameplay of unknown brightness.
        for dx, dy in ((4, 4), (-4, 4), (4, -4), (-4, -4), (0, 5)):
            d.text((ox + dx, oy + dy), text, font=font, fill=(0, 0, 0, 210))
        d.text((ox, oy), text, font=font, fill=tuple(colour) + (255,),
               embedded_color=True)
        scale = size / STRIKE
        if abs(scale - 1.0) > 0.01:
            im = im.resize((max(1, int(im.width * scale)),
                            max(1, int(im.height * scale))), Image.LANCZOS)
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out)
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("could not render caption image: %s", e)
        return None


def brand_logo() -> Path | None:
    """The channel mark, light variant -- gameplay is more often dark than not,
    and the dark variant disappears into a blurred background entirely."""
    for name in ("yuvaneta-light.png", "channel-light.png"):
        p = paths.ROOT / "autostream" / "ui" / "assets" / name
        if p.is_file():
            return p
        p = Path(__file__).resolve().parent.parent / "ui" / "assets" / name
        if p.is_file():
            return p
    return None


def build_filter(width: int, height: int, caption: str, handle: str,
                 logo: Path | None, logo_h: int, *,
                 caption_seconds: float = CAPTION_SECONDS,
                 sub_file: Path | None = None,
                 sub_until: float = 0.0) -> tuple[str, list[str]]:
    """-> (filtergraph, extra ffmpeg inputs).

    `sub_file` holds the spoken hook, already wrapped; `sub_until` is when the
    voice stops saying it.
    """
    parts: list[str] = []
    inputs: list[str] = []
    label = "0:v"

    if logo and logo.is_file():
        inputs += ["-i", str(logo)]
        lh = logo_h
        parts.append(f"[1:v]scale=-1:{lh}[lg]")
        lx = int(width * SAFE_X)
        ly = int(height * BRAND_Y)
        parts.append(f"[{label}][lg]overlay={lx}:{ly}[b]")
        label = "b"
        handle_x = f"{lx} + {lh} + 26"
        handle_y = ly + lh // 2 - int(lh * 0.22)
    else:
        handle_x = str(int(width * SAFE_X))
        handle_y = int(height * BRAND_Y)

    hf = _font(_HANDLE_FONTS)
    if handle and hf:
        parts.append(
            f"[{label}]drawtext=fontfile='{_esc(hf)}':text='{_text(handle)}'"
            f":fontcolor=white:fontsize={max(26, int(height * 0.021))}"
            f":shadowcolor=black@0.75:shadowx=2:shadowy=2"
            f":x={handle_x}:y={handle_y}[h]")
        label = "h"

    cf = _font(_CAPTION_FONTS)
    if caption and cf:
        size = max(48, int(height * 0.052))
        gate = (f":enable='lt(t,{caption_seconds})'"
                if caption_seconds and caption_seconds > 0 else "")
        parts.append(
            f"[{label}]drawtext=fontfile='{_esc(cf)}':text='{_text(caption)}'"
            f":fontcolor=white:fontsize={size}"
            f":borderw={max(3, size // 22)}:bordercolor=black@0.9"
            f":shadowcolor=black@0.6:shadowx=3:shadowy=3"
            f":x=(w-text_w)/2:y={int(height * CAPTION_Y)}"
            f"{gate}[c]")
        label = "c"

    sf = _font(_HANDLE_FONTS)
    if sub_file and sub_until > 0 and sf:
        size = max(34, int(height * 0.030))
        # Timing comes from the voice: it appears with the first word and
        # leaves once the line has been said, because a subtitle still sitting
        # there in silence is just a second caption.
        t0 = 0.0
        t1 = max(t0 + 0.4, float(sub_until)) + SUB_HOLD
        alpha = (f"if(lt(t,{t0 + SUB_FADE_IN:.2f}),(t-{t0:.2f})/{SUB_FADE_IN},"
                 f"if(lt(t,{t1:.2f}),1,"
                 # Commas need no escaping inside a quoted option value --
                 # `enable='lt(t,2.6)'` above has always relied on that.
                 f"max(0,1-(t-{t1:.2f})/{SUB_FADE_OUT})))")
        # textfile, not text=: the hook is a real sentence with apostrophes and
        # commas in it and may be two lines, and every one of those needs
        # escaping through two layers of filtergraph parsing if it is inlined.
        parts.append(
            f"[{label}]drawtext=fontfile='{_esc(sf)}'"
            f":textfile='{_esc(str(sub_file))}'"
            # line_spacing 0 and text_align=C: drawtext left-aligns a
            # multi-line block by default and its default leading leaves a gap
            # you could park a third line in, so a two-clause hook came out
            # ragged and double-spaced.
            f":fontcolor=white:fontsize={size}:line_spacing=0:text_align=C"
            f":box=1:boxcolor=black@0.55:boxborderw={size // 2}"
            f":borderw=0:shadowcolor=black@0.7:shadowx=2:shadowy=2"
            f":x=(w-text_w)/2:y={int(height * SUB_Y)}"
            f":alpha='{alpha}'"
            f":enable='lt(t,{t1 + SUB_FADE_OUT:.2f})'[s]")
        label = "s"

    if not parts or label == "0:v":
        return "", []
    # The chain's final output carries whatever label the last step assigned.
    # Rename that one occurrence to [vout] so the caller can -map it without
    # having to know which steps ran.
    tail = f"[{label}]"
    assert parts[-1].endswith(tail), parts[-1]
    parts[-1] = parts[-1][: -len(tail)] + "[vout]"
    return ";".join(parts), inputs


def apply(src: Path, out: Path, *, caption: str, handle: str = "@YuvaNeta",
          logo: Path | None = None, encoder: str = "auto",
          cq: int = 20, subtitle: str = "", subtitle_until: float = 0.0,
          caption_seconds: float = CAPTION_SECONDS) -> Path:
    """Burn caption, branding and the spoken hook onto a vertical clip.

    `subtitle` is what the voice says and `subtitle_until` is when it stops --
    so this has to run AFTER the speech has been synthesised and before it is
    mixed in. Doing it in that order also means the clip is encoded once
    rather than twice: mixing the audio afterwards copies the video through.
    """
    from .tools import media_info

    info = media_info(src)
    w, h = info["width"], info["height"]
    logo = logo if logo is not None else brand_logo()
    out.parent.mkdir(parents=True, exist_ok=True)

    sub_file = None
    if subtitle and subtitle_until > 0:
        sub_file = out.with_suffix(".sub.txt")
        # newline is forced to \n, and it matters: Python translates
        # \n to \r\n on Windows by default, and drawtext renders that
        # carriage return as a line of its own -- so a two-line hook came
        # out double-spaced with a blank line through the middle of the
        # box, while a one-line hook looked perfect.
        sub_file.write_text(_wrap(subtitle), encoding="utf-8",
                            newline="\n")
    try:
        graph, extra = build_filter(w, h, caption, handle, logo,
                                    logo_h=max(72, int(h * 0.062)),
                                    caption_seconds=caption_seconds,
                                    sub_file=sub_file,
                                    sub_until=subtitle_until)
        if not graph:
            log.warning("nothing to draw; copying instead")
            ffmpeg("-i", str(src), "-c", "copy", "-y", str(out))
            return out

        ffmpeg("-i", str(src), *extra,
               "-filter_complex", graph, "-map", "[vout]", "-map", "0:a:0",
               *video_codec_args(encoder, cq=cq),
               "-c:a", "copy", "-movflags", "+faststart", "-y", str(out))
    finally:
        if sub_file is not None:
            sub_file.unlink(missing_ok=True)
    return out
