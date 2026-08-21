r"""Reading the Counter-Strike 2 scoreboard off the top of the frame.

WHY THIS EXISTS
    clips/killfeed.py answers "did I get a kill". For CS2 that is not enough,
    because the round is the unit of drama: three kills opening a round with
    five teammates alive is a good start, and the same three kills alone
    against three opponents is the clip people actually watch. Telling those
    apart needs the scoreboard -- the round timer, the score, and how many
    players are left on each side.

WHAT IS READABLE, MEASURED
    All three are drawn in a fixed block at the top centre and were confirmed
    legible on real 1080p footage:

        round timer   1:14, and red under ten seconds
        score         12 | 12
        players alive  3 |  2, beside a small person icon

    The player cards either side carry names, health and money, and a skull
    appears under a card when that player dies. Those are not read here.

TEMPLATE MATCHING, NOT OCR
    OCR was tried first and failed on more than half the frames. The reason is
    worth recording: the score and alive counts sit on a TRANSLUCENT panel, so
    their background is whatever the gameplay behind it happens to be, and the
    digits go from white-on-dark to white-on-light within one round. Tesseract
    has to threshold before it can read, and there is no threshold that works
    for both.

    Normalised cross-correlation does not threshold. It is invariant to
    brightness and contrast, so the same template matches a digit on a black
    panel and on a bright sky. Against 1080p footage it read the timer on 40 of
    40 consecutive held-out frames and every score and alive count on the
    hand-labelled set.

    It is also far cheaper: ten glyphs over a few small regions, against a full
    OCR pass over a 768x292 strip.

HOW THE TEMPLATES WERE BUILT
    Not by hand, and not by trusting a label. The timer counts down one second
    at a time, so a run of consecutive frames labels ITSELF: cluster the units
    digit across 150 frames, follow which cluster succeeds which, and the chain
    that comes out is the digits in descending order. Only one frame then has to
    be read by eye to anchor the chain to actual numbers.

    That mattered. The first attempt assumed the run started at the value a
    screenshot showed, was off by one second, and produced ten confidently
    mislabelled templates that read 9 of 40 held-out frames correctly. The
    self-labelling version reads 40 of 40.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import paths
from .tools import _NO_WINDOW, binary, has_cuda

log = logging.getLogger("autostream.clips.hud")

# The frame height the templates were cut from. Every frame is scaled to this
# before matching, for exactly the reason clips/profiles.py records for kill
# templates: a template is a fixed number of pixels and matching it at the
# wrong scale returns nothing at all, which looks like a game with no
# scoreboard rather than a bug.
REF_HEIGHT = 1080

# Regions as fractions of the frame, measured on real footage. Fractions rather
# than pixels so a different resolution works; HUD SCALE is a separate problem
# and needs calibration, which is why these are overridable per profile.
REGIONS: dict[str, tuple[float, float, float, float]] = {
    #            x1        y1        x2        y2
    "timer":   (0.47917, 0.00370, 0.52083, 0.02963),
    "score_l": (0.47604, 0.03148, 0.49896, 0.07222),
    "score_r": (0.49896, 0.03148, 0.52292, 0.07222),
    "alive_l": (0.48750, 0.06481, 0.50000, 0.08704),
    "alive_r": (0.50990, 0.06481, 0.52240, 0.08704),
}

# The alive digits are drawn smaller than the timer and score, which share one
# size. Measured by sweeping: 11px reads all four hand-labelled frames, 9 and
# 13 read none.
ALIVE_GLYPH_HEIGHT = 11

# Correlation floor. Real digits scored 0.68-0.95 on the labelled set; the
# highest score from background texture masquerading as a digit was 0.55.
MIN_SCORE = 0.60

# The scan crops the top of the frame rather than writing whole 1080p PNGs.
# A power of two, so the crop height divides exactly at every common
# resolution (1080/8 = 135, 1440/8 = 180, 2160/8 = 270) and the strip needs no
# resampling at all. An awkward fraction cost a correct reading: 0.12 of 1080
# is 129.6, ffmpeg wrote 129 and the reader wanted 130, and resizing by that
# one pixel blurred the 11-pixel alive digits enough to misread a 3 as a 1.
STRIP_DIV = 8

# A scoreboard can show 0-15 or so, but never more than two digits, and the
# alive count is a single digit 0-5. Constraining the alphabet is what stopped
# blood spatter behind the alive counter reading as a leading zero.
ALIVE_DIGITS = tuple(range(6))
SCORE_DIGITS = tuple(range(10))
MAX_SCORE_DIGITS = 2


def _digits() -> np.ndarray:
    path = paths.CLIP_TEMPLATES_BUILTIN / "cs2-digits.npy"
    if not path.is_file():
        raise FileNotFoundError(f"CS2 digit templates missing at {path}")
    return np.load(path).astype(np.float32)


_CACHE: dict[int, list[np.ndarray]] = {}


def glyphs(height: int) -> list[np.ndarray]:
    """The ten digits, scaled so each glyph is `height` pixels tall."""
    if height in _CACHE:
        return _CACHE[height]
    from PIL import Image

    out = []
    for t in _digits():
        im = Image.fromarray(np.clip(t, 0, 255).astype(np.uint8))
        w = max(3, int(round(t.shape[1] * height / t.shape[0])))
        out.append(np.asarray(im.resize((w, height), Image.LANCZOS))
                   .astype(np.float32))
    _CACHE[height] = out
    return out


def corr(field: np.ndarray, tmpl: np.ndarray) -> np.ndarray:
    """Normalised cross-correlation of tmpl at every position in field.

    Vectorised the same way as detect.ncc: a Python loop over positions would
    be a few thousand iterations per region per frame, which over an hour of
    footage is tens of millions.
    """
    th, tw = tmpl.shape
    fh, fw = field.shape
    if fh < th or fw < tw:
        return np.zeros((0, 0), dtype=np.float32)
    tz = tmpl - tmpl.mean()
    tn = float(np.sqrt((tz * tz).sum())) + 1e-6

    oh, ow = fh - th + 1, fw - tw + 1
    s0, s1 = field.strides
    patches = np.lib.stride_tricks.as_strided(
        field, shape=(oh, ow, th, tw), strides=(s0, s1, s0, s1), writeable=False)
    centred = patches - patches.mean(axis=(2, 3), keepdims=True)
    num = (centred * tz).sum(axis=(2, 3))
    den = np.sqrt((centred ** 2).sum(axis=(2, 3))) * tn + 1e-6
    return (num / den).astype(np.float32)


def read_one(field: np.ndarray, height: int,
             digits: tuple[int, ...] = SCORE_DIGITS) -> tuple[int | None, float]:
    """The single most likely digit in a field. -> (digit, score)."""
    best = (-2.0, None)
    for d in digits:
        c = corr(field, glyphs(height)[d])
        if c.size and float(c.max()) > best[0]:
            best = (float(c.max()), d)
    score, digit = best
    return (digit, score) if digit is not None and score >= MIN_SCORE \
        else (None, max(0.0, score))


def read_number(field: np.ndarray, height: int, *, max_digits: int = 2,
                digits: tuple[int, ...] = SCORE_DIGITS) -> tuple[int | None, float]:
    """A left-to-right number in a field. -> (value, weakest digit's score).

    The field is searched rather than pre-segmented into cells, because the
    score is CENTRED: "7" and "12" do not start at the same x, so fixed cells
    read one of them and miss the other.
    """
    found: list[tuple[float, int, int, int]] = []      # score, digit, x, width
    for d in digits:
        g = glyphs(height)[d]
        c = corr(field, g)
        if not c.size:
            continue
        for y, x in zip(*np.where(c >= MIN_SCORE)):
            found.append((float(c[y, x]), d, int(x), g.shape[1]))
    if not found:
        return None, 0.0

    # Strongest first, then drop anything overlapping a digit already taken --
    # one glyph lights up a run of neighbouring positions.
    found.sort(reverse=True)
    kept: list[tuple[float, int, int, int]] = []
    for s, d, x, w in found:
        if all(abs(x - kx) >= max(w, kw) * 0.6 for _, _, kx, kw in kept):
            kept.append((s, d, x, w))
        if len(kept) >= max_digits:
            break
    kept.sort(key=lambda h: h[2])
    value = int("".join(str(d) for _, d, _, _ in kept))
    return value, min(s for s, _, _, _ in kept)


@dataclass
class Reading:
    """One frame's scoreboard."""
    time: float
    seconds: int | None = None      # round timer, in seconds
    score_l: int | None = None
    score_r: int | None = None
    alive_l: int | None = None
    alive_r: int | None = None
    confidence: float = 0.0         # the weakest field that was read

    @property
    def complete(self) -> bool:
        return None not in (self.seconds, self.score_l, self.score_r,
                            self.alive_l, self.alive_r)

    @property
    def score(self) -> tuple[int, int] | None:
        if self.score_l is None or self.score_r is None:
            return None
        return (self.score_l, self.score_r)


def read_frame(gray: np.ndarray, at: float = 0.0,
               regions: dict | None = None) -> Reading:
    """Read the scoreboard out of one full greyscale frame."""
    from PIL import Image

    regions = regions or REGIONS
    h, w = gray.shape
    if h != REF_HEIGHT:
        # Scale to the height the templates were cut at, never the other way:
        # shrinking the templates loses strokes.
        scale = REF_HEIGHT / h
        im = Image.fromarray(np.clip(gray, 0, 255).astype(np.uint8))
        gray = np.asarray(im.resize((int(round(w * scale)), REF_HEIGHT),
                                    Image.LANCZOS)).astype(np.float32)
        h, w = gray.shape

    def crop(key: str) -> np.ndarray:
        x1, y1, x2, y2 = regions[key]
        return gray[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]

    gh = _digits().shape[1]                     # native glyph height
    scores = []

    mmss, c = read_timer(crop("timer"), gh)
    scores.append(c)
    sl, c1 = read_number(crop("score_l"), gh, max_digits=MAX_SCORE_DIGITS)
    sr, c2 = read_number(crop("score_r"), gh, max_digits=MAX_SCORE_DIGITS)
    al, c3 = read_one(crop("alive_l"), ALIVE_GLYPH_HEIGHT, ALIVE_DIGITS)
    ar, c4 = read_one(crop("alive_r"), ALIVE_GLYPH_HEIGHT, ALIVE_DIGITS)
    scores += [c1, c2, c3, c4]

    return Reading(time=at, seconds=mmss, score_l=sl, score_r=sr,
                   alive_l=al, alive_r=ar,
                   confidence=round(min(scores), 3))


def read_timer(field: np.ndarray, height: int) -> tuple[int | None, float]:
    """M:SS as a number of seconds. The colon is not matched, only the digits.

    Three digits, and their positions are fixed because M:SS is always four
    characters in a monospaced font -- so unlike the score, this one can be
    read as a plain left-to-right sequence.
    """
    value, conf = read_number(field, height, max_digits=3)
    if value is None:
        return None, conf
    s = f"{value:03d}"
    mins, secs = int(s[0]), int(s[1:])
    if secs > 59:
        return None, conf                # not a clock; reject rather than guess
    return mins * 60 + secs, conf


# ---------------------------------------------------------------- scanning

def scan(video: Path, *, duration: float | None = None, fps: float = 1.0,
         chunk: float = 120.0, regions: dict | None = None,
         progress=None, cancelled=None) -> list[Reading]:
    """Read the scoreboard across a whole recording. -> readings in time order.

    Sampling at 1 fps is ample: a round lasts 30-115 seconds and only the
    TRANSITIONS matter -- when the score changes, when the alive count drops.
    """
    from PIL import Image

    from .tools import media_info

    video = Path(video)
    total = duration if duration is not None else media_info(video)["duration"]
    if not total:
        return []

    spans = []
    t = 0.0
    while t < total:
        spans.append((t, min(chunk, total - t)))
        t += chunk

    out: list[Reading] = []
    if progress:
        progress(0, len(spans))
    for i, (start, dur) in enumerate(spans, 1):
        if cancelled and cancelled():
            break
        out.extend(_scan_span(video, start, dur, fps, regions))
        if progress:
            progress(i, len(spans))

    good = sum(1 for r in out if r.complete)
    log.info("%s: read the scoreboard on %d of %d sampled frame(s)",
             video.name, good, len(out))
    return out


def _scan_span(video: Path, start: float, duration: float, fps: float,
               regions: dict | None) -> list[Reading]:
    """One span. Only the top of the frame is decoded, so this is cheap."""
    from PIL import Image

    # The scoreboard lives in the top ~10% of the frame, so crop before writing
    # the PNGs. read_frame() wants a full frame to apply its fractions to, so
    # the crop is undone by handing it a frame of the right nominal height --
    # simpler to keep the whole width and the top 12%.
    accel = ["-hwaccel", "cuda"] if has_cuda() else []
    tmp = Path(tempfile.mkdtemp(prefix="hud_"))
    try:
        subprocess.run([
            binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
            *accel, "-ss", f"{start:.3f}", "-i", str(video),
            "-t", f"{max(0.5, duration):.3f}", "-an", "-sn",
            "-vf", f"fps={fps},crop=iw:ih/{STRIP_DIV}:0:0",
            str(tmp / "h_%05d.png"),
        ], capture_output=True, check=False, creationflags=_NO_WINDOW)

        out = []
        for png in sorted(tmp.glob("h_*.png")):
            at = start + (int(png.stem.split("_")[1]) - 1) / fps
            strip = np.asarray(Image.open(png).convert("L")).astype(np.float32)
            out.append(read_strip(strip, at, regions))
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def read_strip(strip: np.ndarray, at: float = 0.0,
               regions: dict | None = None) -> Reading:
    """Read a scoreboard from the top 1/STRIP_DIV of a frame, not a whole one.

    Scanning crops in ffmpeg to avoid writing whole 1080p frames -- the same
    saving that made the kill feed scan three times faster -- so the y
    fractions are rescaled to the strip.
    """
    from PIL import Image

    regions = regions or REGIONS
    scaled = {k: (x1, y1 * STRIP_DIV, x2, y2 * STRIP_DIV)
              for k, (x1, y1, x2, y2) in regions.items()}

    # Resize only if the source really is a different resolution. At 1080p the
    # strip is already exactly the height the templates were cut for, and
    # resampling it would only soften the smallest glyphs.
    want_h = REF_HEIGHT // STRIP_DIV
    if abs(strip.shape[0] - want_h) > 1:
        im = Image.fromarray(np.clip(strip, 0, 255).astype(np.uint8))
        w = int(round(strip.shape[1] * want_h / strip.shape[0]))
        strip = np.asarray(im.resize((w, want_h), Image.LANCZOS)).astype(np.float32)

    h, w = strip.shape

    def crop(key):
        x1, y1, x2, y2 = scaled[key]
        return strip[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]

    gh = _digits().shape[1]
    mmss, c0 = read_timer(crop("timer"), gh)
    sl, c1 = read_number(crop("score_l"), gh, max_digits=MAX_SCORE_DIGITS)
    sr, c2 = read_number(crop("score_r"), gh, max_digits=MAX_SCORE_DIGITS)
    al, c3 = read_one(crop("alive_l"), ALIVE_GLYPH_HEIGHT, ALIVE_DIGITS)
    ar, c4 = read_one(crop("alive_r"), ALIVE_GLYPH_HEIGHT, ALIVE_DIGITS)
    return Reading(time=at, seconds=mmss, score_l=sl, score_r=sr,
                   alive_l=al, alive_r=ar,
                   confidence=round(min([c0, c1, c2, c3, c4]), 3))
