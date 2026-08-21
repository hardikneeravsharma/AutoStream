r"""Kill detection by reading the kill feed.

FOR GAMES WITH NO KILL MARKER
    Delta Force draws a skull under the crosshair, so a template match finds
    your kills directly. CS2 draws nothing at all -- no hitmarker, no banner --
    and announces kills only in the feed at the top right. The feed lists
    EVERYONE's kills, so finding yours means reading it.

THE LINE FORMAT
        KILLER [+ assister]   <weapon icon>   VICTIM

    The KILLER IS FIRST. This was originally implemented the other way round
    and it was wrong. What settles it, from the footage itself: a row read
    "YUVANETA + Comrade P.O.T [ak47] Rebound", and sixteen seconds earlier the
    feed had shown "Rebound [pistol] Comrade P.O.T". Comrade P.O.T was already
    dead. A dead player cannot get a kill, but can certainly have damaged the
    victim before dying -- so the second name is the assister and the first is
    the killer.

    Your name appears in the feed whether you killed, died, or merely assisted,
    so finding it decides nothing on its own. WHICH SLOT it occupies is the
    whole signal, and the slot is read off pixel positions:

        name ends at the right margin   -> you died
        a name to the LEFT of yours     -> that one is the killer, you assisted
        nothing to the left of yours    -> you got the kill

WHY POSITION AND NOT TOKENS, COLOUR, OR TIME
    Tokens. The weapon icon is not text and OCRs as junk -- on real footage it
    came out as "pei", "at.", "gagel" -- and how many junk tokens it produces
    changes every frame, so nothing can be counted. "First token" fails too,
    because an assist puts another player's name ahead of yours.

    Colour. CS2 really does outline your own rows in red, and it was tried
    first. It does not survive the map: over sandy terrain a KILL row measured
    redness 60 with 79% of its pixels red, while a genuine DEATH row measured
    26. The outline also marks rows you only assisted, so even read perfectly
    it would not separate a kill from a death.

    Time. One row is read in several consecutive frames and has to be collapsed
    back to one event, but rows live anywhere from 1 to 9 seconds and two
    DIFFERENT rows can be 1 second apart, so no time window splits them
    correctly. Rows are tracked by where they sit instead -- see collapse().

WHY MATCHING IS FUZZY
    Tesseract misreads this font predictably; "VUVANETA" comes back more often
    than "YUVANETA" does. Names are compared with an edit-distance ratio after
    folding the characters it actually confuses. Measured over 720 frames,
    unrelated words topped out at 0.55 while real reads ran 0.71-1.00.

COST
    One OCR pass per sampled frame, which is orders of magnitude dearer than a
    correlation: about 10 frames a second across 8 threads, so an hour of
    footage takes six minutes. Sampling is 1 fps, which cannot miss a row that
    lives a median of 5 seconds.

CALIBRATION
    Everything above is measured, not assumed, and the measurements are pinned
    in tests/test_killfeed.py so that changing a constant fails loudly.
"""
from __future__ import annotations

import difflib
import functools
import logging
import os
import re
import shutil
import subprocess
import tempfile
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .tools import _NO_WINDOW, binary, has_cuda

log = logging.getLogger("autostream.clips.killfeed")

TESSERACT_HINT = "winget install --id UB-Mannheim.TesseractOCR"


class TesseractMissing(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def tesseract() -> str:
    """Where Tesseract is.

    Not tools.binary(): that one searches ffmpeg's install locations and its
    failure message tells you to install ffmpeg, which would be actively
    misleading here. The UB-Mannheim installer -- the usual Windows build --
    does not put itself on PATH, so its own directory has to be checked.
    """
    found = shutil.which("tesseract")
    if found:
        return found
    for root in (Path(r"C:/Program Files/Tesseract-OCR"),
                 Path(r"C:/Program Files (x86)/Tesseract-OCR"),
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Tesseract-OCR"):
        exe = root / ("tesseract.exe" if os.name == "nt" else "tesseract")
        if exe.is_file():
            return str(exe)
    raise TesseractMissing(
        f"Tesseract OCR was not found, and reading the kill feed needs it. "
        f"Install it with:  {TESSERACT_HINT}\nThen reopen AutoStream.")


# 4x, and greyscale is NOT an option. Measured against known frames: 4x colour
# read all three, while 4x greyscale, 4x Otsu and 3x greyscale each lost one.
# CS2 tints names by team, and discarding colour merges a name into the wall
# behind it.
UPSCALE = 4

# One sample a second. A feed row lives a median of 5s (measured: 1-9s over 20
# rows), so 1 fps sees every row several times, and OCR is far too expensive to
# run more often -- this is already the dominant cost of the whole scan.
SAMPLE_FPS = 1.0

# Fuzzy threshold. Measured over 720 frames of real CS2: unrelated words topped
# out at 0.55 ("yang", "beta", another player's "wAcKuPrAnKeTeR"), while genuine
# reads of the name ran 0.71-1.00. The distinct-row count was IDENTICAL for
# every threshold from 0.58 to 0.80, so this sits in the middle of a plateau
# rather than on a cliff.
MATCH_RATIO = 0.72

# Tesseract genuinely confuses these in HUD fonts, so they are folded together
# before comparing. Y/V is in here because it is what turned YUVANETA into
# VUVANETA on real frames.
_FOLD = str.maketrans({
    "0": "o", "O": "o", "Q": "o",
    "1": "l", "I": "l", "|": "l",
    "5": "s", "S": "s",
    "8": "b", "6": "b",
    "3": "e", "E": "e",
    "7": "t", "T": "t",
    "n": "h", "H": "h",
    "2": "z", "9": "g",
    "V": "y", "v": "y", "Y": "y",
    "4": "a",
})

# CONFIDENCE IS NOT USABLE HERE AND MUST NOT GATE THE MATCH.
# Measured on real CS2 frames: a perfectly-read "YUVANETA" came back with
# confidence 0, while netgraph junk ("20ms") scored 70 and scenery noise scored
# 85. Filtering on confidence threw away the one word that mattered and kept
# everything that did not. What actually separates a name from noise is LENGTH
# plus how closely it matches the one name being looked for, so those do the
# filtering and confidence is carried only for diagnostics.
MIN_NAME_LEN = 4

# WHICH SIDE OF THE LINE, DECIDED BY THE RIGHT MARGIN.
#
# The feed is RIGHT-ALIGNED, so the victim's name always ends hard against the
# margin and a killer's name never can -- the weapon icon and the victim still
# have to fit after it. Measured on known frames, as a fraction of the strip
# width, where the player's name ended:
#
#     kill   0.807      (name followed by icon + victim)
#     kill   0.813
#     death  0.966      (name is last on the line)
#
# 0.90 sits in the middle of a 0.15-wide gap. Even the worst case -- a long
# killer name followed by the shortest possible victim -- lands near 0.82.
#
# Confirmed over 12 minutes of play: 77 kill sightings spanned 0.594-0.828 and
# 10 death sightings spanned 0.966-0.988. Nothing landed in between.
DEATH_EDGE = 0.90

# ---- turning repeated sightings back into events -------------------------
#
# The same feed row is read in several consecutive frames, so sightings have to
# be grouped into rows before anything is counted. Time cannot do that on its
# own: rows live 1-9s and the gap between two DIFFERENT rows was as short as
# 1s, so any single time window either splits one row in two or merges two into
# one. Position can, and these are what it takes.
#
# The RIGHT edge identifies a row. Measured across every row in the sample, it
# is an order of magnitude steadier than the left:
#
#     row      left edge span   right edge span
#     09:29    0.739-0.740        0.826-0.828
#     09:38    0.715              0.802-0.803
#     09:45    0.563-0.590        0.675-0.676
#
# The right edge is bounded by the whitespace before the weapon icon, whereas
# the left is disturbed by whatever precedes the name -- an assist's "+", the
# red outline's border, a spurious character Tesseract invents. Tracking on the
# left split one 8-second kill into two because a single frame's left edge
# moved 0.027.
#
# The tolerance then only has to beat the closest two rows ever seen together,
# which was 0.025 (right edges 0.828 and 0.803), while a row's own drift never
# exceeded 0.004.
X_TOL = 0.020

# Deaths get a looser one, because for them x carries no information at all:
# the victim slot is pinned to the right margin, so EVERY death sits at
# 0.957-0.988 whoever killed you. Two deaths cannot be told apart by x even in
# principle, and trying split one death into three. What separates them instead
# is time -- in Counter-Strike you die once a round, and a round is minutes --
# so MAX_GAP does the work here and x only has to stop being an obstacle.
DEATH_X_TOL = 0.035

# A row only ever moves UP: new entries are added at the bottom of the feed and
# push the older ones up, measured as y going 0.662 -> 0.542 -> 0.181 across one
# row's life. So a name that has moved DOWN is a new row, not the old one --
# which is what separates two kills that happen to sit at the same x.
#
# The slack has to sit below one row's height and above OCR's jitter. Rows are
# 0.118 apart, and the worst jitter measured on a stationary row was 0.068 --
# so 0.09 tells a genuine new row from a wobbly reading of an old one.
Y_SLACK = 0.09

# How long a row may go unread before it is considered gone. OCR drops frames
# in the middle of a row's life when the background is awkward, and without
# bridging the gap one kill is counted twice.
#
# 4.0 was too short and the 12-minute sample that set it never showed why: it
# is insensitive to this value entirely. A row on a bright wall elsewhere in
# the recording was read at 62m24 and then not again until 62m29 -- a 5-second
# hole -- and became two kills, then a third when its edge drifted. 6.0 clears
# that with the tolerance below; nothing measured needs more.
MAX_GAP = 6.0

# WHY NOT THE RED OUTLINE.
# CS2 does outline your own rows red, and reading that colour was tried first.
# It does not survive contact with the game: over sandy terrain a KILL row
# measured redness 60 with 79% of pixels red, while a genuine DEATH row measured
# 26. The map, not the outline, decides how red the row is. Position does not
# have that problem.


# The netgraph sits inside the feed band and reads as text. "20ms" and
# "Jitter" would otherwise be counted as players standing to the right of your
# name, which turns your own kills into assists. Both are excluded: one by
# being mostly digits, the other by name.
_HUD_WORDS = {"jitter", "loss", "ping", "choke", "fps", "tick"}
MIN_ALPHA_FRAC = 0.6

# Unmatched characters needed on one side of a token before its box is
# trimmed there. See matched_span().
MIN_TRIM = 2


# How close two tokens' boxes must be vertically to be on the same feed row,
# as a fraction of the strip's height. A FRACTION, because a pixel count is
# silently wrong at any other resolution or HUD scale.
#
# Tesseract's box top follows the tallest letter in the token, so two words on
# one row differ by as much as their ascenders do: "/ANETA" and "Flex" on the
# same line measured 31px apart, and a 12px tolerance therefore decided they
# were on different rows and lost the assist. Rows themselves sit 0.118 apart,
# so anything comfortably under half of that separates them safely.
# Swept against nine rows verified by eye: 0.020-0.035 all classify every one
# correctly, 0.040 starts pulling the row below into the count and turns two
# real kills into assists. 0.030 sits mid-band and clears the widest genuine
# gap measured (31px, or 0.027).
SAME_ROW = 0.030


def name_like(text: str) -> bool:
    """Whether a token could be a player name rather than HUD furniture."""
    t = (text or "").strip()
    if len(t) < MIN_NAME_LEN:
        return False
    letters = sum(ch.isalpha() for ch in t)
    if letters / len(t) < MIN_ALPHA_FRAC:
        return False                       # "20ms", "$1200", timers
    # Fuzzy, not exact. The netgraph label comes back as "Jitter", "{Jitter",
    # "qJitter", "\itter" and "Jitter," in the same recording, and an exact
    # blocklist caught only the first -- the partial reads then counted as
    # players standing on your row and turned kills into assists.
    bare = re.sub(r"[^a-z]", "", t.lower())
    return not any(difflib.SequenceMatcher(None, bare, w).ratio() >= 0.75
                   for w in _HUD_WORDS)


def norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", str(s or "").lower().translate(_FOLD))


def _norm_map(s: str) -> tuple[str, list[int]]:
    """norm(s), plus where each surviving letter came from in the original."""
    folded = str(s or "").lower().translate(_FOLD)
    out, idx = [], []
    for i, ch in enumerate(folded):
        if "a" <= ch <= "z":
            out.append(ch)
            idx.append(i)
    return "".join(out), idx


def matched_span(text: str, target: str) -> tuple[float, float]:
    """Which part of `text` is actually the name. -> (start, end) as fractions.

    Tesseract attaches neighbouring junk to a name -- a leading underscore, or
    the netgraph's "20ms" fused onto the end -- and that junk moves the token's
    box. The box is what decides both which row this is and whether it is a
    kill, so the junk has to be discounted rather than tolerated.

    Measured: "_YUVANETA" put the left edge 0.016 out, enough to look like a
    different row, and a fused "20ms" put the right edge 69px out, enough to
    push a kill over the death threshold. Trimming to the matched span fixes
    both at the source, which is what lets the tolerances stay tight enough to
    separate rows only 0.024 apart.

    Characters are assumed evenly spaced. That is not exactly true of a
    proportional font, but the error is a few pixels against the tens of pixels
    it is correcting.
    """
    if not text:
        return 0.0, 1.0
    normed, idx = _norm_map(text)
    if not normed:
        return 0.0, 1.0
    blocks = [b for b in difflib.SequenceMatcher(None, target, normed)
              .get_matching_blocks() if b.size]
    if not blocks:
        return 0.0, 1.0
    lo = idx[blocks[0].b]
    hi = idx[blocks[-1].b + blocks[-1].size - 1] + 1
    n = len(text)

    # Only trim a side with at least MIN_TRIM unmatched characters on it. One
    # stray character is far more likely to be a MISREAD of a real glyph than
    # something glued on: "VUVANET!" is the name with its last letter read as
    # "!", and trimming that "!" threw away a real character's width, moving
    # the right edge 0.017 and splitting one kill into two. Genuine
    # contamination is bigger -- the fused netgraph added three.
    if lo < MIN_TRIM:
        lo = 0
    if n - hi < MIN_TRIM:
        hi = n
    return lo / n, hi / n


@dataclass
class FeedEvent:
    """One kill or death, after repeated sightings have been collapsed."""
    time: float
    kind: str           # "kill" | "death"
    matched: str        # what OCR actually read for the name
    other: str          # the other player on the line, if legible
    ratio: float
    end: float = 0.0    # when the row was last still on screen
    seen: int = 1       # frames it was read in, for diagnostics
    right: float = 0.0  # where the row ends, so refine() can find it again

    def __post_init__(self) -> None:
        if not self.end:
            self.end = self.time


@dataclass
class Sighting:
    """The name found on one row of one frame."""
    time: float
    left: float         # fraction of the strip -- identifies the row
    right: float        # fraction of the strip -- decides kill or death
    top: float          # fraction of the strip -- rows only ever move up
    ratio: float
    text: str
    other: str
    # Where the players to the LEFT of your name end, as fractions of the
    # strip. Positions rather than a count, because which names OCR manages to
    # read changes every frame while where they sit does not.
    #
    # LEFT, because the killer comes first: somebody standing to your left on
    # the row means they got the kill and you assisted.
    left_xs: tuple[float, ...] = ()

    @property
    def kind(self) -> str:
        """kill or death, from where the name sits on the row.

        Assists are decided per ROW, not per frame -- see collapse() -- because
        one frame's view of who else is on the line is far too unreliable.
        """
        return "death" if self.right >= DEATH_EDGE else "kill"


@dataclass
class Word:
    text: str
    conf: float
    x: float            # centre, in crop pixels
    left: float
    right: float
    top: float
    line: tuple


def _ocr_words(img) -> list[Word]:
    try:
        import pytesseract
    except ImportError as e:
        raise TesseractMissing(
            "The pytesseract package is missing, and reading the kill feed "
            "needs it. Install it with:  pip install pytesseract") from e

    pytesseract.pytesseract.tesseract_cmd = tesseract()
    d = pytesseract.image_to_data(img, config="--psm 6",
                                  output_type=pytesseract.Output.DICT)
    out: list[Word] = []
    for i, raw in enumerate(d["text"]):
        w = (raw or "").strip()
        if len(w) < MIN_NAME_LEN:
            continue
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = 0.0
        left, width = float(d["left"][i]), float(d["width"][i])
        out.append(Word(text=w, conf=conf, x=left + width / 2,
                        left=left, right=left + width, top=float(d["top"][i]),
                        line=(d["block_num"][i], d["par_num"][i], d["line_num"][i])))
    return out


# The frame handed to _crop_words is already the band, so it takes all of it.
WHOLE_IMAGE = (0.0, 0.0, 1.0, 1.0)


def _crop_words(png: Path, band=WHOLE_IMAGE) -> tuple[list[Word], float, float]:
    """-> (words, crop width, crop height), both in pixels."""
    from PIL import Image

    im = Image.open(png).convert("RGB")
    w, h = im.size
    x1, y1, x2, y2 = band
    c = im.crop((int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)))
    c = c.resize((c.width * UPSCALE, c.height * UPSCALE), Image.LANCZOS)
    return _ocr_words(c), float(c.width), float(c.height)


def find_all(words: list[Word], crop_w: float, crop_h: float, player: str,
             at: float = 0.0, ratio_min: float = MATCH_RATIO) -> list[Sighting]:
    """Every place the player's name appears in one frame.

    Every place, not the best one: the name can be on TWO rows at once -- you
    trade, and your kill and your death sit in the feed together. Keeping only
    the strongest match dropped the death on five consecutive frames of real
    footage, so a trade looked like a clean kill.
    """
    target = norm(player)
    if not target or crop_w <= 0:
        return []

    scored = []
    for w in words:
        r = difflib.SequenceMatcher(None, target, norm(w.text)).ratio()
        if r >= ratio_min:
            scored.append((r, w))
    if not scored:
        return []

    # Two tokens on the same feed row both matching is one sighting, not two --
    # Tesseract sometimes splits a name in half. Keep the strongest per row.
    scored.sort(key=lambda rw: -rw[0])
    out: list[Sighting] = []
    for r, w in scored:
        row_px = SAME_ROW * crop_h
        if any(abs(w.top - s.top * crop_h) < row_px for s in out):
            continue
        # Only for the caption, and only from the same feed row: "same OCR
        # line" spans the whole strip, which picked up the buy menu's "$1200"
        # and the netgraph's jitter reading as the other player's name.
        others = [o for o in words
                  if o is not w and abs(o.top - w.top) < row_px
                  and abs(o.left - w.left) > 4
                  and abs(o.x - w.x) < crop_w * 0.30]
        near = min(others, key=lambda o: abs(o.x - w.x)).text if others else ""
        # Measure the box of the NAME, not of whatever Tesseract glued to it.
        f0, f1 = matched_span(w.text, target)
        width = w.right - w.left
        my_left, my_right = w.left + width * f0, w.left + width * f1
        # Only tokens that could be players, and only ones clearly past the end
        # of your name -- a few pixels of overlap is OCR jitter, not a person.
        on_row = [o for o in words
                  if o is not w and abs(o.top - w.top) < row_px
                  and name_like(o.text)]
        # The KILLER IS FIRST, so a player standing to the left of your name is
        # the one who got the kill and you only assisted. Nothing to your left
        # means the kill is yours.
        #
        # Only the left is examined, which also sidesteps the weapon icon: it
        # sits between the killer group and the victim, so it is never left of
        # the killer or the assister, and the victim case is already settled by
        # the right-margin test before this runs.
        before = [o for o in on_row
                  if o.right < my_left - width * 0.10]
        to_left = tuple(sorted(o.right / crop_w for o in before))
        out.append(Sighting(time=at,
                            left=my_left / crop_w,
                            right=my_right / crop_w,
                            top=w.top / crop_h, ratio=r, text=w.text, other=near,
                            left_xs=to_left))
    return out


def _extract(video: Path, band, start: float, duration: float,
             fps: float) -> Path:
    """Write one span's frames, already cropped to the band. -> temp dir.

    CROPPED IN FFMPEG, NOT AFTERWARDS. Writing whole 1920x1080 frames and
    cropping them in Pillow made the scan three times slower than the OCR alone
    accounts for: the band is 11% of the frame, so the other 89% was being
    encoded to PNG and read back for nothing. Expressed with `iw`/`ih` so the
    frame size does not have to be known here.
    """
    x1, y1, x2, y2 = band
    crop = (f"crop=iw*{x2 - x1:.6f}:ih*{y2 - y1:.6f}"
            f":iw*{x1:.6f}:ih*{y1:.6f}")
    # Hardware decode where there is any: measured 8.5s against 10.3s a span,
    # and the cores it stops using are cores the OCR pool can have. Falls back
    # silently, because a machine without it must still be able to scan.
    accel = ["-hwaccel", "cuda"] if has_cuda() else []
    tmp = Path(tempfile.mkdtemp(prefix="kf_"))
    subprocess.run([
        binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
        *accel,
        "-ss", f"{start:.3f}", "-i", str(video),
        "-t", f"{max(0.5, duration):.3f}", "-an", "-sn",
        "-vf", f"fps={fps},{crop}", str(tmp / "f_%05d.png"),
    ], capture_output=True, check=False, creationflags=_NO_WINDOW)
    return tmp


# A span's frames are deleted as soon as they are read, but only if the process
# lives to run the finally. A force-quit or a kill mid-scan leaves them: one
# abandoned scan was found holding 1.5 GB of PNGs. Anything this old cannot
# belong to a live scan -- a span directory exists for about twenty seconds --
# so it is safe to remove even with another AutoStream running.
STALE_TEMP_HOURS = 6


def _sweep_stale_temp() -> None:
    """Delete frame directories abandoned by a scan that was killed."""
    import time

    cutoff = time.time() - STALE_TEMP_HOURS * 3600
    root = Path(tempfile.gettempdir())
    freed = 0
    try:
        for d in root.glob("kf_*"):
            try:
                if d.is_dir() and d.stat().st_mtime < cutoff:
                    freed += sum(f.stat().st_size for f in d.glob("*"))
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                continue                 # in use, or gone between the two calls
    except OSError:
        return
    if freed:
        log.info("removed %.0f MB of frames left by an interrupted scan",
                 freed / 2 ** 20)


def _extract_pair(video: Path, band, start: float, duration: float,
                  fps: float, hud_div: int) -> Path:
    """One decode, two crops: the kill feed strip and the scoreboard strip.

    The feed scan and the scoreboard scan want the same frames at the same
    rate, and decoding is roughly half the cost of each -- 10.3s of ffmpeg
    against 11s of OCR per two-minute span. Run separately they decode the
    recording twice for nothing.
    """
    x1, y1, x2, y2 = band
    feed = (f"crop=iw*{x2 - x1:.6f}:ih*{y2 - y1:.6f}"
            f":iw*{x1:.6f}:ih*{y1:.6f}")
    accel = ["-hwaccel", "cuda"] if has_cuda() else []
    tmp = Path(tempfile.mkdtemp(prefix="kf_"))
    subprocess.run([
        binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
        *accel, "-ss", f"{start:.3f}",
        # -t BEFORE -i, so it limits how much is READ. After -i it is an output
        # option and applies only to the FIRST output: the second kept decoding
        # to the end of the file, which turned a 20-second span into 19 minutes
        # of work and made every round scan appear to hang.
        "-t", f"{max(0.5, duration):.3f}",
        "-i", str(video), "-an", "-sn",
        "-filter_complex",
        f"[0:v]fps={fps},split=2[a][b];"
        f"[a]{feed}[feedout];[b]crop=iw:ih/{hud_div}:0:0[hudout]",
        "-map", "[feedout]", str(tmp / "f_%05d.png"),
        "-map", "[hudout]", str(tmp / "s_%05d.png"),
    ], capture_output=True, check=False, creationflags=_NO_WINDOW)
    return tmp


def scan_with_hud(video: Path, band, player: str, *,
                  duration: float | None = None, fps: float = SAMPLE_FPS,
                  chunk: float = 120.0, workers: int = 0,
                  hud_regions: dict | None = None,
                  progress=None, cancelled=None):
    """Read the feed AND the scoreboard from one pass. -> (events, readings).

    Only for games whose profile asks for rounds. Everything else uses scan().
    """
    from . import hud as _hud
    from .tools import media_info

    total = duration if duration is not None else media_info(video)["duration"]
    workers = workers or default_workers()
    _sweep_stale_temp()

    spans = []
    t = 0.0
    while t < total:
        spans.append((t, min(chunk, total - t)))
        t += chunk

    seen: list[Sighting] = []
    readings: list = []
    if progress:
        progress(0, len(spans))
    for i, (at, dur) in enumerate(spans, 1):
        if cancelled and cancelled():
            break
        tmp = _extract_pair(video, band, at, dur, fps, _hud.STRIP_DIV)
        try:
            seen.extend(_read(tmp, player, at, fps, workers))
            for png in sorted(tmp.glob("s_*.png")):
                from PIL import Image

                when = at + (int(png.stem.split("_")[1]) - 1) / fps
                strip = np.asarray(Image.open(png).convert("L")).astype(np.float32)
                readings.append(_hud.read_strip(strip, when, hud_regions))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if progress:
            progress(i, len(spans))

    events = collapse(seen)
    if not (cancelled and cancelled()):
        refine(video, band, player, events, workers=workers, cancelled=cancelled)
    good = sum(1 for r in readings if r.complete)
    t = tally(events)
    log.info("%s: %d kill(s), %d assist(s), %d death(s), and the scoreboard on "
             "%d of %d frame(s)", Path(video).name, t["kill"], t["assist"],
             t["death"], good, len(readings))
    return events, readings


def _read(tmp: Path, player: str, start: float, fps: float,
          workers: int) -> list[Sighting]:
    """OCR every frame in an extracted span. -> raw sightings, not events."""
    def one(png: Path) -> list[Sighting]:
        # The frame is already the band, so nothing is cropped again here.
        words, cw, ch = _crop_words(png)
        at = start + (int(png.stem.split("_")[1]) - 1) / fps
        return find_all(words, cw, ch, player, at)

    # Threads, not processes: pytesseract shells out to tesseract.exe, so the
    # work happens in a child process and the GIL is not in the way. Decoding
    # and upscaling the PNG is Pillow, which releases it too. Measured 8
    # threads against 1 on this machine: 1.7 -> 10 frames a second.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        got = list(pool.map(one, sorted(tmp.glob("f_*.png"))))
    return [s for chunk in got for s in chunk]


def _sightings(video: Path, band, player: str, start: float, duration: float,
               fps: float, workers: int) -> list[Sighting]:
    """Extract and read one span. Used by the calibrator, which does one."""
    tmp = _extract(video, band, start, duration, fps)
    try:
        return _read(tmp, player, start, fps, workers)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# A box this far off the usual size is not the name. Self-calibrating against
# the scan's own median rather than a pixel count, because the right answer
# depends on resolution and HUD scale, and a scan already has hundreds of
# samples to take a median from.
#
# Measured over 110 sightings: the middle 90% spanned 0.94x-1.15x the median
# and the 98th percentile was 1.30x, then nothing until 3.23x. Both outliers
# were the same failure -- Tesseract drawing one box around the name AND the
# netgraph behind it while transcribing only the name, so the text looks clean
# and only the geometry gives it away. Both landed at the netgraph's right
# edge, which put them over the death threshold and invented a death.
WIDTH_MIN, WIDTH_MAX = 0.55, 1.60
MIN_FOR_MEDIAN = 8


def _drop_bad_boxes(sightings: list[Sighting]) -> list[Sighting]:
    """Discard sightings whose box is the wrong size to be the name."""
    if len(sightings) < MIN_FOR_MEDIAN:
        return sightings                 # too few to know what normal is
    widths = sorted(s.right - s.left for s in sightings)
    med = widths[len(widths) // 2]
    if med <= 0:
        return sightings
    kept = [s for s in sightings
            if WIDTH_MIN <= (s.right - s.left) / med <= WIDTH_MAX]
    if len(kept) != len(sightings):
        log.debug("dropped %d sighting(s) whose box was the wrong size",
                  len(sightings) - len(kept))
    return kept


# How far apart two right-hand names have to be to be different players.
#
# This has to absorb one player's own drift while still separating two. Both
# were measured: a victim's right edge wandered 0.965 -> 0.971 across a single
# row's life, whereas the two names on an assist row sat 0.21-0.27 apart. At
# 0.02 the drift split into two clusters and invented a second player, turning
# verified kills ("YUVANETA [ak] Rico") into assists; at 0.08 the killer and
# the victim merged into one and a verified assist became a kill. 0.05 sits an
# order of magnitude clear of both, and classified all eleven eye-verified rows
# correctly at every row tolerance tried.
SLOT_TOL = 0.05


def _slots_left(xs: list[float], sightings: int) -> int:
    """How many other players are on the row, BEFORE your name.

    Counted over the row's WHOLE life rather than per frame. Which names
    Tesseract manages to read changes frame to frame -- one real assist row
    reported 2, 1, 1, 1, 0, 1, 3, 2 names on consecutive frames -- so no single
    frame can be trusted and a majority vote over frames gets it wrong. Where
    the names sit does not move, so positions are pooled across the row and
    clustered instead.

    A cluster normally has to be seen twice, which discards a one-frame
    fragment ("vite" out of "Mr.Infinite") without discarding a real player who
    was only legible in half the frames. A row read only two or three times has
    no room for that: demanding two sightings there missed a real assist
    ("YUVANETA + ::: insane ::: <icon> Flex", read twice, scored a kill), so
    below four sightings one is enough.
    """
    if not xs:
        return 0
    need = 2 if sightings >= 4 else 1
    clusters: list[list[float]] = []
    for x in sorted(xs):
        if clusters and x - clusters[-1][-1] <= SLOT_TOL:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return sum(1 for c in clusters if len(c) >= need)


def collapse(sightings: list[Sighting]) -> list[FeedEvent]:
    """Repeated sightings of the same feed row -> one event each.

    Rows are tracked by WHERE they are, because time alone cannot do it: rows
    live 1-9 seconds and two different rows can be 1 second apart, so no single
    window splits them correctly. A sighting continues an open row when it ends
    at the same x and has not moved down the screen.

    The kind is decided by MAJORITY VOTE over the row's whole life rather than
    from its first frame. One frame's right edge can be corrupted -- Tesseract
    merging the name with the netgraph behind it moved a right edge by 69px --
    and a single bad frame must not be able to turn a kill into a death.

    Assists are settled here too, and only here: whether somebody is standing
    to the LEFT of your name -- which, the killer being first, is what makes it
    their kill and not yours -- cannot be answered from one frame, because
    whether OCR reads that name changes every frame. See _slots_left().
    """
    sightings = _drop_bad_boxes(sightings)
    open_rows: list[dict] = []
    done: list[dict] = []

    for s in sorted(sightings, key=lambda x: x.time):
        hit = None
        for r in reversed(open_rows):
            if s.time - r["last"] > MAX_GAP:
                continue
            # The ROW's kind picks the tolerance, not the sighting's: a
            # borderline frame has to be able to join the row it belongs to so
            # the vote can overrule it, rather than being turned away and
            # becoming an event of its own.
            tol = DEATH_X_TOL if r["votes"][0] == "death" else X_TOL
            if abs(s.right - r["right"]) > tol:
                continue
            if s.top > r["top"] + Y_SLACK:
                continue          # moved DOWN the screen, so it is a new row
            hit = r
            break
        if hit is None:
            hit = {"first": s.time, "last": s.time, "right": s.right,
                   "top": s.top, "votes": [], "best": s, "n": 0, "rx": []}
            open_rows.append(hit)
            done.append(hit)
        hit["last"] = s.time
        hit["top"] = s.top
        hit["n"] += 1
        hit["votes"].append(s.kind)
        hit["rx"].extend(s.left_xs)
        if s.ratio > hit["best"].ratio:
            hit["best"] = s
        open_rows = [r for r in open_rows if s.time - r["last"] <= MAX_GAP]

    out: list[FeedEvent] = []
    for r in done:
        kind = max(set(r["votes"]), key=r["votes"].count)
        if kind == "kill" and _slots_left(r["rx"], r["n"]) >= 1:
            # Somebody is standing to the left of your name, and the killer is
            # first -- so they got it and you assisted.
            kind = "assist"
        b = r["best"]
        out.append(FeedEvent(time=r["first"], kind=kind, matched=b.text,
                             other=b.other, ratio=b.ratio, end=r["last"],
                             seen=r["n"], right=r["right"]))
    out.sort(key=lambda e: e.time)
    return out


def scan(video: Path, band, player: str, *, duration: float | None = None,
         fps: float = SAMPLE_FPS, chunk: float = 120.0, workers: int = 0,
         progress=None, cancelled=None) -> list[FeedEvent]:
    """Read the whole recording's feed. -> events in time order.

    Chunked so ffmpeg writes a manageable number of PNGs at a time; a two-hour
    recording at 1 fps would otherwise be 7,200 files in one directory.
    """
    from .tools import media_info

    total = duration if duration is not None else media_info(video)["duration"]
    workers = workers or default_workers()
    _sweep_stale_temp()
    spans = []
    t = 0.0
    while t < total:
        spans.append((t, min(chunk, total - t)))
        t += chunk

    seen: list[Sighting] = []
    if progress:
        progress(0, len(spans))
    # Deliberately sequential. Pulling the next span's frames while reading the
    # current one was tried and measured no faster (15.9 min against 16.1 for
    # the same recording): ffmpeg's decode and the OCR pool want the same
    # cores, so there is no idle resource for the overlap to use. It only added
    # a cancellation path and a temp directory that could leak.
    for i, (at, dur) in enumerate(spans, 1):
        if cancelled and cancelled():
            break
        seen.extend(_sightings(video, band, player, at, dur, fps, workers))
        if progress:
            progress(i, len(spans))

    # Collapsed only once every span is in, so a row straddling a chunk
    # boundary is still one event rather than two.
    events = collapse(seen)
    # Then each kill's time is pulled back to when its row really appeared.
    # Costs a couple of minutes against the scan's fifteen and is what keeps
    # the kill inside the clip that is cut around it.
    if not (cancelled and cancelled()):
        refine(video, band, player, events, workers=workers, cancelled=cancelled)
    t = tally(events)
    log.info("%s: %d kill(s), %d assist(s), %d death(s) read from the feed "
             "(%d sightings)", Path(video).name, t["kill"], t["assist"],
             t["death"], len(seen))
    return events


# Sampling at 1 fps finds THAT a row appeared, not WHEN. If OCR misses the
# row's first frames -- and it often does, because a row is at its least legible
# while the background behind it is still moving -- the reported time lags the
# kill. Measured on one clip: the row was on screen from 1415.0s but was not
# read until 1417.0s, so a clip cut 1.5s before 1417 began AFTER the kill and
# contained none of it. The clip was labelled two kills and showed one.
#
# So each kill gets a second, much cheaper look: re-scan the few seconds before
# it at a higher rate and take the row's real first appearance. Only kills are
# refined, because only kills decide where a clip starts.
REFINE_FPS = 4.0
REFINE_LOOKBACK = 4.0


def refine(video: Path, band, player: str, events: list[FeedEvent], *,
           fps: float = REFINE_FPS, look_back: float = REFINE_LOOKBACK,
           workers: int = 0, kinds: tuple[str, ...] = ("kill",),
           progress=None, cancelled=None) -> list[FeedEvent]:
    """Move each kill's timestamp back to when its row actually appeared."""
    workers = workers or default_workers()
    todo = [e for e in events if e.kind in kinds]
    moved = 0
    for i, e in enumerate(todo, 1):
        if cancelled and cancelled():
            break
        start = max(0.0, e.time - look_back)
        span = e.time - start
        if span <= 0:
            continue
        try:
            seen = _sightings(video, band, player, start, span, fps, workers)
        except Exception as err:  # noqa: BLE001 - a refine must never fail a scan
            log.debug("refine skipped at %.1fs: %s", e.time, err)
            continue
        # The same row: same end-of-name x, and not already after the event.
        same = [s for s in seen
                if abs(s.right - e.right) <= X_TOL and s.time < e.time]
        if same:
            earliest = min(s.time for s in same)
            if earliest < e.time:
                moved += 1
                e.time = earliest
        if progress:
            progress(i, len(todo))
    if moved:
        log.info("refined %d of %d kill time(s) back to when the row appeared",
                 moved, len(todo))
    events.sort(key=lambda x: x.time)
    return events


def default_workers() -> int:
    """Enough to keep the CPU busy without starving the rest of the app.

    Each worker is an entire tesseract.exe, so this is real parallelism and
    real memory. Two cores are left alone because a scan is a background job
    and the dashboard has to stay responsive while it runs.
    """
    return max(2, min(8, (os.cpu_count() or 4) - 2))


def to_kills(events: list[FeedEvent]) -> list[dict]:
    """Kill events in the shape the rest of the clipper expects.

    `end` is set to the event time: a feed line has no "marker cleared" moment
    the way a HUD glyph does, so the tail is measured from the kill itself.
    """
    return [{"time": e.time, "end": e.time, "score": round(e.ratio, 3),
             "count": 1, "victim": e.other}
            for e in events if e.kind == "kill"]


def tally(events: list[FeedEvent]) -> dict[str, int]:
    """Kills, assists and deaths, for reporting."""
    return {k: sum(1 for e in events if e.kind == k)
            for k in ("kill", "assist", "death")}
