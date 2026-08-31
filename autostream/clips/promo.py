r"""Sweep the ordinary kills into one promo reel.

WHY THIS EXISTS
    caption_for() deliberately says nothing about a plain single kill -- there
    is nothing distinctive to claim, and a filler caption is worse than none
    because a viewer reads a caption as a factual statement. That leaves those
    clips sitting on disk doing nothing.

    Individually they are unremarkable. Cut to a few seconds each and run
    together they are a perfectly good channel advert, which is a job the
    caption CAN honestly do: the claim is about the channel, not about the
    play.

LENGTH
    Aimed at 30-40 seconds. Short-form retention data puts the sweet spot at
    15-30s and the view ceiling around 25-35s, and a promo has to earn its
    length rather than assume it. Per-clip time is derived from the target and
    the clip count instead of fixed, so nine kills and three kills both produce
    something watchable.
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import cutter, montage, overlay, plan
from .tools import ffmpeg, media_info, video_codec_args

log = logging.getLogger("autostream.clips.promo")

TARGET_MIN, TARGET_MAX = 30.0, 40.0

# Room either side of the kill inside a promo cut. Tighter than any normal
# clip: nothing here has to be understood, only glimpsed.
PROMO_PRE = 1.0
# Long enough to hold the kill itself. At 1.6s the reel cut away while the kill
# was still happening -- the feed row is what dates a kill, and it appears as
# the animation plays, so a tail measured from it has to cover the rest of it.
PROMO_TAIL = 2.5
# ...but the run-up is what absorbs the target length, so it needs a ceiling
# as well as a floor. With only a floor, every single-kill piece came out at
# PROMO_PRE + PROMO_TAIL = 2.6s no matter what piece_length() asked for, and a
# reel documented at 30-40 seconds delivered fifteen. Beyond about three and a
# half seconds the run-up is somebody walking.
PROMO_PRE_MAX = 3.5
# A piece has to be long enough to READ, not merely long enough to contain the
# kill. At 2.4s a thirteen-clip reel came out at 2.2s a cut and every kill was
# clipped mid-action. The floor is now PROMO_PRE + PROMO_TAIL with room to
# spare, so the run-up grows with the piece instead of staying at the minimum.
MIN_PIECE = 4.0
MAX_PIECE = 5.5

# ...which in turn caps how many clips a reel can hold. Length is shared out
# between them, so past this the target window can only be met by cutting below
# the floor. The extras are dropped rather than squeezed: a promo is a taster,
# and the ones dropped are the weakest single kills of the session.
MAX_CLIPS = int(TARGET_MAX // MIN_PIECE)


def piece_length(count: int) -> float:
    """Seconds per clip so the reel lands inside the target window."""
    if count <= 0:
        return 0.0
    ideal = (TARGET_MIN + TARGET_MAX) / 2 / count
    return max(MIN_PIECE, min(MAX_PIECE, ideal))


def pick(plans, floor: int = 2) -> list:
    """The clips that fell BELOW the minimum -- the leftovers.

    The rule used to be "clips no caption could be found for", which was a
    reasonable proxy while a caption meant a multi-kill. It stopped being one
    when round clips started captioning themselves from their labels: a
    one-kill clutch has a caption and is not a leftover, and a two-kill burst
    has none and is not a leftover either.

    So the rule is now the one the user actually sets. Whatever `min_kills`
    says is worth a clip of its own, anything under it is promo material --
    which at the default of 2 is exactly "the single kills".
    """
    return [p for p in plans if int(getattr(p, "kills", 0)) < floor]


def strongest(leftovers, limit: int) -> list:
    """The `limit` best leftovers, in whatever order they came. -> a subset."""
    if len(leftovers) <= limit:
        return list(leftovers)
    best = sorted(leftovers,
                  key=lambda p: (int(getattr(p, "kills", 0)),
                                 float(getattr(p, "peak_score", 0.0) or 0.0)),
                  reverse=True)[:limit]
    log.info("promo: %d leftovers is more than %d cuts can hold; keeping the "
             "best %d", len(leftovers), limit, limit)
    return best


def build(source: Path, leftovers, kills, outdir: Path, *,
          game: str = "Session", handle: str = "@YuvaNeta",
          caption: str = "LIVE MOST EVENINGS \U0001F3AE",
          encoder: str = "auto", vertical_mode: str = "fit",
          transition: str = "fade", transition_ms: int = 400) -> Path | None:
    """Cut every leftover short, join them, and brand the result."""
    if len(leftovers) < 2:
        log.info("only %d leftover clip(s); not worth a promo", len(leftovers))
        return None

    per = piece_length(len(leftovers))
    log.info("promo: %d clips at %.1fs each", len(leftovers), per)
    work = outdir / "promo" / "_pieces"
    work.mkdir(parents=True, exist_ok=True)

    # Chronological, like the main montage -- a reel that jumps around the
    # match reads as an editing mistake even when nothing else is wrong.
    ordered = sorted(strongest(leftovers, MAX_CLIPS), key=lambda p: p.start)

    pieces: list[Path] = []
    for i, p in enumerate(ordered, 1):
        inside = [k for k in kills if p.start <= float(k["time"]) <= p.end]
        if not inside:
            continue
        # Rebuild a tight window round the kill rather than trimming the
        # existing clip, which was cut with a much longer run-up.
        last = max(inside, key=lambda k: float(k["time"]))
        end = float(last.get("end") or last["time"]) + PROMO_TAIL
        first = float(inside[0]["time"])
        # `per` sets the length; the two bounds keep the run-up sane whatever
        # it works out to. Ordered so the floor wins: a piece may be shorter
        # than the target, never blinder than PROMO_PRE.
        start = min(max(end - per, first - PROMO_PRE_MAX), first - PROMO_PRE)
        start = max(0.0, start)
        piece = plan.ClipPlan(rank=i, start=start, end=end, kills=len(inside),
                              burst_kills=len(inside), peak_score=0.0,
                              name=f"promo_{i:02d}")
        pieces.append(cutter.master(source, piece, work, encoder=encoder,
                                    keep_all_audio=False))

    if len(pieces) < 2:
        return None

    joined = outdir / "promo" / "_joined.mp4"
    montage.build(pieces, joined, transition=transition,
                  transition_ms=transition_ms, encoder=encoder)

    vert = cutter.vertical(joined, outdir / "promo", mode=vertical_mode,
                           encoder=encoder)
    if vert is None:
        vert = joined

    total = media_info(vert)["duration"]
    name = (f"{plan.slug(game)}_promo_{len(pieces)}clips"
            f"_{int(round(total))}s.mp4")
    final = outdir / "promo" / name
    _brand(vert, final, caption, handle, encoder)

    # The intermediates are large and reproducible; only the reel is wanted.
    for p in pieces:
        p.unlink(missing_ok=True)
    joined.unlink(missing_ok=True)
    if vert != joined:
        vert.unlink(missing_ok=True)
    try:
        work.rmdir()
    except OSError:
        pass
    log.info("promo reel: %s (%.0fs)", final.name, total)
    return final


def _brand(src: Path, out: Path, caption: str, handle: str, encoder: str) -> None:
    """Promo caption as an image overlay, held for the whole reel.

    An image rather than drawtext because the caption carries emoji, and
    drawtext renders those as tofu. Held throughout rather than timed out
    because the whole point of this reel IS the caption -- unlike a kill clip,
    where the caption is a label on something else.
    """
    info = media_info(src)
    w, h = info["width"], info["height"]
    tmp = out.parent / "_caption.png"
    img = overlay.text_png(caption, tmp, size=max(46, int(h * 0.040)))
    logo = overlay.brand_logo()

    parts: list[str] = []
    inputs: list[str] = []
    label = "0:v"
    idx = 1
    if img:
        inputs += ["-i", str(img)]
        # Clamp to the safe width. A caption rendered at a fixed point size runs
        # off both edges the moment the text is long -- and the ends are exactly
        # where the channel name sits.
        safe = int(w * 0.90)
        parts.append(f"[{idx}:v]scale='min({safe},iw)':-1[cap]")
        parts.append(f"[{label}][cap]overlay=(W-w)/2:{int(h * 0.115)}[t]")
        label, idx = "t", idx + 1
    if logo and logo.is_file():
        inputs += ["-i", str(logo)]
        lh = max(80, int(h * 0.068))
        parts.append(f"[{idx}:v]scale=-1:{lh}[lg]")
        parts.append(f"[{label}][lg]overlay={int(w * 0.055)}:{int(h * 0.855)}[b]")
        label, idx = "b", idx + 1
    hf = _handle_font()
    if handle and hf:
        parts.append(
            f"[{label}]drawtext=fontfile='{overlay._esc(hf)}'"
            f":text='{overlay._text(handle)}':fontcolor=white"
            f":fontsize={max(26, int(h * 0.021))}"
            f":shadowcolor=black@0.75:shadowx=2:shadowy=2"
            f":x={int(w * 0.055) + max(80, int(h * 0.068)) + 26}"
            f":y={int(h * 0.855) + max(80, int(h * 0.068)) // 3}[h]")
        label = "h"

    if not parts:
        ffmpeg("-i", str(src), "-c", "copy", "-y", str(out))
        return
    tail = f"[{label}]"
    parts[-1] = parts[-1][: -len(tail)] + "[vout]"
    ffmpeg("-i", str(src), *inputs, "-filter_complex", ";".join(parts),
           "-map", "[vout]", "-map", "0:a:0",
           *video_codec_args(encoder, cq=20),
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
           "-y", str(out))
    if img:
        img.unlink(missing_ok=True)


def _handle_font() -> str | None:
    return overlay._font(overlay._HANDLE_FONTS)
