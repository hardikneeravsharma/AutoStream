r"""Build a stream thumbnail from what is actually on screen.

WHY A COMPOSITE AND NOT GENERATED ART
    The best possible image for a live stream thumbnail is the stream. OBS is
    already connected and already rendering the game, so a frame is one call
    away -- free, offline, instant, and showing the thing a viewer is deciding
    whether to watch. Generated art costs money per image, needs the network
    at the exact moment of going live, and depicts something that is not the
    stream.

WHAT YOUTUBE WANTS
    1280x720, under 2 MB, JPEG or PNG. Bigger is accepted and downscaled, but
    the small player tile is where the decision happens, so everything here is
    sized to survive at roughly 210 pixels wide: heavy type, one short line,
    high contrast against a darkened frame.

FAILURE IS NOT FATAL
    Every step degrades rather than raises. No OBS frame falls back to the
    configured base image, no base image falls back to a flat brand colour, no
    Pillow means no thumbnail at all -- and in every case the stream still
    goes live. A thumbnail is decoration on a broadcast that has already
    started.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path

from . import paths

log = logging.getLogger("autostream.thumbnail")

WIDTH, HEIGHT = 1280, 720
MAX_BYTES = 2 * 1024 * 1024        # YouTube's hard limit

_FONT_DIR = Path(r"C:\Windows\Fonts")
_TITLE_FONTS = ("impact.ttf", "arialbd.ttf", "segoeuib.ttf")
_SUB_FONTS = ("segoeuib.ttf", "arialbd.ttf")

# Fractions of the frame. The logo sits top-left, the headline bottom-left,
# both clear of the duration badge YouTube stamps into the bottom-right.
PAD = 0.045
LOGO_H = 0.20
TITLE_H = 0.155
SUB_H = 0.070


def _font(names, size: int):
    from PIL import ImageFont

    for n in names:
        p = _FONT_DIR / n
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _fit(draw, text: str, names, target_h: int, max_w: int):
    """Largest font size at which `text` still fits the width."""
    size = target_h
    while size > 12:
        f = _font(names, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return _font(names, 12)


def render(frame_png: bytes | None, *, game: str, channel: str,
           headline: str, sub: str = "", logo: Path | None = None,
           base_image: Path | None = None, out: Path | None = None,
           style: str = "clean") -> Path | None:
    """Compose and write the thumbnail. -> path, or None if it could not be made.

    style="clean"  headline low-left over a gradient, LIVE flag top-right.
                   Reads as a live stream, which is what it is.
    style="punchy" the gaming-thumbnail convention: headline across the TOP in
                   heavy outlined caps, colour and contrast pushed hard, a
                   vignette pulling the eye to the middle. Louder, and built to
                   survive next to hand-made thumbnails in a sidebar.
    """
    try:
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
    except ImportError:
        log.warning("Pillow is not installed; no thumbnail")
        return None

    bg = None
    if frame_png:
        try:
            bg = Image.open(io.BytesIO(frame_png)).convert("RGB")
        except Exception as e:  # noqa: BLE001
            log.warning("OBS frame unreadable (%s); falling back", e)
    if bg is None and base_image and Path(base_image).is_file():
        try:
            bg = Image.open(base_image).convert("RGB")
        except Exception:  # noqa: BLE001
            bg = None
    if bg is None:
        bg = Image.new("RGB", (WIDTH, HEIGHT), (14, 17, 22))

    # Cover-crop to 16:9 rather than squashing: a stretched thumbnail is the
    # most obvious tell that something automated made it.
    bg = _cover(bg, WIDTH, HEIGHT)

    punchy = style == "punchy"

    if punchy:
        # Colour and contrast pushed well past natural. Gameplay footage is
        # muted next to a thumbnail somebody graded by hand, and the tile is
        # seen for a fraction of a second.
        bg = ImageEnhance.Color(bg).enhance(1.55)
        bg = ImageEnhance.Contrast(bg).enhance(1.22)
        bg = ImageEnhance.Brightness(bg).enhance(1.05)
        # Vignette: darken the edges so the eye lands in the middle, where the
        # subject is. Radial rather than linear -- a linear gradient reads as a
        # band, a vignette reads as focus.
        vig = Image.new("L", (WIDTH, HEIGHT), 0)
        vd = ImageDraw.Draw(vig)
        cx, cy = WIDTH / 2, HEIGHT * 0.52
        steps = 60
        for i in range(steps, 0, -1):
            f = i / steps
            rx, ry = WIDTH * 0.78 * f, HEIGHT * 0.86 * f
            vd.ellipse([cx - rx, cy - ry, cx + rx, cy + ry],
                       fill=int(150 * (1 - f) ** 1.4))
        vig = vig.filter(ImageFilter.GaussianBlur(60))
        bg = Image.composite(Image.new("RGB", bg.size, (4, 5, 9)), bg, vig)
        # A dark band behind the top text only, so the headline never fights
        # a bright sky.
        top = Image.new("L", (WIDTH, HEIGHT), 0)
        td = ImageDraw.Draw(top)
        for i in range(int(HEIGHT * 0.34)):
            t = 1.0 - i / (HEIGHT * 0.34)
            td.line([(0, i), (WIDTH, i)], fill=int(130 * (t ** 1.3)))
        top = top.filter(ImageFilter.GaussianBlur(18))
        bg = Image.composite(Image.new("RGB", bg.size, (5, 6, 10)), bg, top)
    else:
        # Darken the lower-left so type reads over any gameplay. A gradient
        # rather than a flat scrim, because a hard band across a screenshot
        # looks pasted on.
        scrim = Image.new("L", (WIDTH, HEIGHT), 0)
        sd = ImageDraw.Draw(scrim)
        for i in range(HEIGHT):
            t = max(0.0, (i / HEIGHT - 0.35) / 0.65)
            sd.line([(0, i), (WIDTH, i)], fill=int(170 * (t ** 1.5)))
        scrim = scrim.filter(ImageFilter.GaussianBlur(12))
        bg = Image.composite(Image.new("RGB", bg.size, (6, 8, 12)), bg, scrim)
        bg = ImageEnhance.Color(bg).enhance(1.12)

    im = bg.convert("RGBA")
    d = ImageDraw.Draw(im)
    pad = int(WIDTH * PAD)

    # ---- logo, top left -------------------------------------------------
    # Punchy puts its logo bottom-left instead, next to the handle, because the
    # top is entirely given over to the headline. Drawing both leaves two.
    if not punchy and logo and Path(logo).is_file():
        try:
            lg = Image.open(logo).convert("RGBA")
            lh = int(HEIGHT * LOGO_H)
            lg = lg.resize((max(1, int(lh * lg.width / lg.height)), lh),
                           Image.LANCZOS)
            im.alpha_composite(lg, (pad, pad))
        except Exception as e:  # noqa: BLE001
            log.debug("logo skipped: %s", e)

    # ---- headline --------------------------------------------------------
    text = (headline or game or "LIVE").upper()
    if punchy:
        # Across the top, as big as it will go, with a stroke thick enough to
        # read against anything underneath. borderw does the outline in one
        # pass rather than the four-corner shadow trick used below.
        max_w = int(WIDTH * 0.94)
        tf = _fit(d, text, _TITLE_FONTS, int(HEIGHT * 0.20), max_w)
        tb = d.textbbox((0, 0), text, font=tf)
        tw_, th_ = tb[2] - tb[0], tb[3] - tb[1]
        tx = (WIDTH - tw_) / 2 - tb[0]
        ty = int(HEIGHT * 0.045) - tb[1]
        d.text((tx, ty), text, font=tf, fill=(255, 255, 255, 255),
               stroke_width=max(6, int(HEIGHT * 0.012)),
               stroke_fill=(8, 8, 12, 255))
        if sub:
            sf = _fit(d, sub, _SUB_FONTS, int(HEIGHT * 0.075), max_w)
            sb = d.textbbox((0, 0), sub, font=sf)
            sx = (WIDTH - (sb[2] - sb[0])) / 2 - sb[0]
            sy = ty + th_ + int(HEIGHT * 0.045)
            d.text((sx, sy), sub, font=sf, fill=(255, 214, 92, 255),
                   stroke_width=max(4, int(HEIGHT * 0.007)),
                   stroke_fill=(8, 8, 12, 255))
        _punchy_marks(im, d, pad, logo, channel)
        out = Path(out or (paths.VIDEO_HOME / "thumbnails" /
                           f"{datetime.now():%Y-%m-%d_%H%M}_{_slug(game)}.jpg"))
        out.parent.mkdir(parents=True, exist_ok=True)
        _save_under_limit(im.convert("RGB"), out)
        log.info("thumbnail: %s (%.0f KB)", out.name, out.stat().st_size / 1024)
        return out

    max_w = int(WIDTH * 0.82)
    tf = _fit(d, text, _TITLE_FONTS, int(HEIGHT * TITLE_H), max_w)
    tb = d.textbbox((0, 0), text, font=tf)
    th = tb[3] - tb[1]

    sub_font = None
    sh = 0
    if sub:
        sub_font = _fit(d, sub, _SUB_FONTS, int(HEIGHT * SUB_H), max_w)
        sb = d.textbbox((0, 0), sub, font=sub_font)
        sh = sb[3] - sb[1] + int(HEIGHT * 0.018)

    y = HEIGHT - pad - th - sh
    for dx, dy in ((4, 4), (-4, 4), (4, -4), (-4, -4), (0, 6)):
        d.text((pad + dx, y - tb[1] + dy), text, font=tf, fill=(0, 0, 0, 235))
    d.text((pad, y - tb[1]), text, font=tf, fill=(255, 255, 255, 255))

    if sub and sub_font:
        sy = y + th + int(HEIGHT * 0.022)
        for dx, dy in ((3, 3), (-3, 3)):
            d.text((pad + dx, sy + dy), sub, font=sub_font, fill=(0, 0, 0, 220))
        d.text((pad, sy), sub, font=sub_font, fill=(235, 240, 248, 255))

    # ---- LIVE flag, top right -------------------------------------------
    flag = "LIVE"
    ff = _font(_TITLE_FONTS, int(HEIGHT * 0.062))
    fw = d.textlength(flag, font=ff)
    bx2, by1 = WIDTH - pad, pad
    bx1 = bx2 - int(fw) - int(WIDTH * 0.030)
    by2 = by1 + int(HEIGHT * 0.088)
    d.rounded_rectangle([bx1, by1, bx2, by2], radius=int(HEIGHT * 0.016),
                        fill=(214, 48, 49, 235))
    d.text((bx1 + (bx2 - bx1 - fw) / 2, by1 + int(HEIGHT * 0.014)), flag,
           font=ff, fill=(255, 255, 255, 255))

    out = Path(out or (paths.VIDEO_HOME / "thumbnails" /
                       f"{datetime.now():%Y-%m-%d_%H%M}_{_slug(game)}.jpg"))
    out.parent.mkdir(parents=True, exist_ok=True)
    _save_under_limit(im.convert("RGB"), out)
    log.info("thumbnail: %s (%.0f KB)", out.name, out.stat().st_size / 1024)
    return out


def _punchy_marks(im, d, pad: int, logo: Path | None, channel: str) -> None:
    """Logo and handle for the punchy layout: bottom-left, out of the way of a
    centred subject and clear of YouTube's duration badge bottom-right."""
    from PIL import Image

    y = HEIGHT - pad
    x = pad
    if logo and Path(logo).is_file():
        try:
            lg = Image.open(logo).convert("RGBA")
            lh = int(HEIGHT * 0.17)
            lg = lg.resize((max(1, int(lh * lg.width / lg.height)), lh),
                           Image.LANCZOS)
            im.alpha_composite(lg, (x, y - lh))
            x += lg.width + int(WIDTH * 0.016)
            y_text = y - lh // 2
        except Exception:  # noqa: BLE001
            y_text = y - int(HEIGHT * 0.05)
    else:
        y_text = y - int(HEIGHT * 0.05)

    if channel:
        handle = channel if channel.startswith("@") else "@" + channel
        f = _font(_SUB_FONTS, int(HEIGHT * 0.055))
        bb = d.textbbox((0, 0), handle, font=f)
        d.text((x, y_text - (bb[3] - bb[1]) / 2 - bb[1]), handle, font=f,
               fill=(255, 255, 255, 255), stroke_width=4,
               stroke_fill=(8, 8, 12, 255))


def _cover(img, w: int, h: int):
    """Scale to fill and centre-crop, preserving aspect."""
    from PIL import Image

    scale = max(w / img.width, h / img.height)
    nw, nh = max(w, int(img.width * scale)), max(h, int(img.height * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _save_under_limit(img, out: Path) -> None:
    """JPEG, stepping quality down until it fits YouTube's 2 MB ceiling."""
    for q in (92, 86, 80, 72, 62, 50):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
        if buf.tell() <= MAX_BYTES:
            out.write_bytes(buf.getvalue())
            return
    out.write_bytes(buf.getvalue())      # last try; still better than nothing


def _slug(s: str) -> str:
    import re

    s = re.sub(r"[^\w\s-]", "", str(s or "")).strip()
    return re.sub(r"[\s_-]+", "-", s)[:40] or "stream"


def build_for_session(cfg, obs, *, game: str, username: str = "") -> Path | None:
    """Grab a frame and compose the thumbnail for the session going live."""
    if not cfg.thumbnail.enabled:
        return None
    frame = obs.screenshot(WIDTH, HEIGHT) if obs else None
    if frame is None:
        log.info("no OBS frame; using the configured base image")

    from . import titles

    now = datetime.now()
    v = {
        "game": game or "Just Chatting",
        "channel": cfg.thumbnail.channel_name or "",
        "username": username or "",
        "day": now.strftime("%A"),
        "date": now.strftime("%d %b"),
        "time": now.strftime("%H:%M"),
    }
    headline = _render_template(cfg.thumbnail.headline, v) or v["game"]
    sub = _render_template(cfg.thumbnail.subtitle, v)
    logo = cfg.thumbnail.logo or None
    base = cfg.thumbnail.base_image or None
    return render(frame, game=v["game"], channel=v["channel"],
                  headline=headline, sub=sub,
                  logo=Path(logo) if logo else None,
                  base_image=Path(base) if base else None)


def _render_template(tpl: str | None, v: dict) -> str:
    """Same forgiving substitution the title templates use: an unknown token
    renders as itself rather than blowing up a live session."""
    if not tpl:
        return ""
    try:
        return str(tpl).format_map(_Safe(v)).strip()
    except Exception:  # noqa: BLE001
        return str(tpl)


class _Safe(dict):
    def __missing__(self, key):  # noqa: D105
        return "{" + key + "}"
