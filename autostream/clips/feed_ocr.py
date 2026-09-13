r"""A second look at the Valorant kill feed, only where the colour reader is unsure.

WHY THIS EXISTS. valorant_feed reads the feed by colour and shape, which is fast
and needs no in-game name -- and it drops real kills whenever scenery behind
the feed breaks the geometry. Measured on reviewed footage it found 6 of 12
kills: a smoke lit the row's right margin so it read as still sliding in, the
performance overlay fused with a third stacked row, a rifle icon split a bar so
a kill read as an assist. In every one of those the row was plainly legible.
The names are drawn in white, and white text survives all three.

WHY ONLY WHERE IT IS UNSURE. Reading text is what makes the CS2 reader slow.
Doing it on every frame of a match cost six times the scan; doing it only on
the rows the colour reader was doubtful about recovered the same kills for a
fraction of that. On a 33-minute ranked match: 14 of 16 kills -> 16 of 16, no
false kills, +75% scan time, where reading every frame would have been +585%.

HOW, IN ORDER, all fixed on the reviewed excerpts and then confirmed on a match
they were never tuned against:

  capture  while the scan already holds each frame, keep the white-text mask of
           each feed slot. Tiny, and it means no second decode.
  doubt    three rules over what the colour reader already produced
             D1  a frame read as a kill that no counted kill covers
             D2  a row read as assist/other that still carries your yellow
             D3  a slot holding a portrait's worth of yellow and no row at all
  check    OCR only the doubtful slots. Your name on the killer half of a row is
           a reading; the same victim within 6s is the same row; a row counts at
           2 readings, is not read again once confirmed, and is followed back in
           time for its true start.
  merge    a counted kill that an OCR row shares a moment with keeps its place
           and takes the earlier start; an OCR row nobody counted is a new kill.

The name comes from games.yaml when it is set. When it is not, it is learned:
the most common name on the killer half of rows the colour reader already
counted as yours. Valorant needs no setup today, and this keeps it that way.

Optional by construction. With no Tesseract, no name, or any failure inside,
the colour reader's events come back untouched.
"""
from __future__ import annotations

import collections
import difflib
import logging
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)

REF_WIDTH = 960       # band width at 1080p; every x below is measured against it
REF_HEIGHT = 1080

# Valorant's feed rows sit on a fixed grid: 34px tall, 39px apart, the first 20px
# into the band. Measured against a pixel ruler on real footage.
SLOTS = ((20, 54), (59, 93), (98, 132))
TEXT_X = (440, 940)   # where names can be: left of this is scenery, right is the portrait edge
KILLER_MAX_X = 750    # a name centred left of this is the killer half of a row

WHITE_MIN = 185       # min(R,G,B) of a name pixel
GREY_MAX = 45         # max - min: names are colourless
MIN_TEXT_PX = 40      # a slot with fewer white pixels than this has no name to read
UPSCALE = 3
MATCH_RATIO = 0.72    # killfeed.MATCH_RATIO: how close an OCR word must be to the name
SAME_VICTIM = 0.6     # victim names are read less carefully than yours; this is enough
YELLOW_PANEL = 300    # yellow px in a slot: a portrait panel is ~1000, a stray patch far less

ROW_LIFE = 6.0        # s. A feed row lives about five.
CONFIRM = 2           # readings of the same row before it counts
LOOK_BACK = 4.0       # s. How far a confirmed row is followed back for its start
COVER_PAD = 1.0       # s. A counted kill covers its row this far either side

# Agreement, not a count a short recording cannot reach. Every vote comes from
# a row the colour reader already judged to be the player's kill, so two
# readings that agree with no dissent is real evidence -- and a 100-second
# excerpt holding one kill could never reach three.
LEARN_MIN_VOTES = 2
LEARN_MIN_SHARE = 0.6


def scale_for(frame_height: int | None) -> float:
    return (frame_height or REF_HEIGHT) / REF_HEIGHT


def slot_rows(k: float) -> list[tuple[int, int]]:
    return [(int(a * k), int(b * k)) for a, b in SLOTS]


# ------------------------------------------------------------------ capture

@dataclass
class Frame:
    """What the check needs from one sampled frame, kept after the pixels go."""
    at: float
    rows: list                              # valorant_feed.Row, as the colour reader read them
    slot_yellow: tuple[int, int, int]
    text: dict = field(default_factory=dict)  # slot -> (packed bits, shape)


class Capture:
    """Everything the check needs, gathered during the scan.

    Packed white masks rather than images: a slot is ~500x40 bits, about 2.5KB,
    and only slots that actually contain white text are kept. A two-hour
    recording at 2 fps is a few tens of megabytes at most, and nothing is
    decoded twice.
    """

    def __init__(self, frame_height: int | None = None):
        self.k = scale_for(frame_height)
        self.frames: list[Frame] = []

    def add(self, a: np.ndarray, at: float, rows: list, yellow: np.ndarray) -> None:
        k = self.k
        # x as a share of the band's width, so a 1440p band (1280px) is cut in
        # the same place as a 1080p one (960px).
        x0 = int(a.shape[1] * TEXT_X[0] / REF_WIDTH)
        x1 = int(a.shape[1] * TEXT_X[1] / REF_WIDTH)
        ys = []
        text = {}
        for i, (ya, yb) in enumerate(slot_rows(k)):
            ys.append(int(yellow[ya:yb, x0:].sum()))
            strip = a[max(0, ya - 2): yb + 2, x0:x1].astype(np.int16)
            mn, mx = strip.min(axis=2), strip.max(axis=2)
            mask = (mn >= WHITE_MIN) & ((mx - mn) <= GREY_MAX)
            if int(mask.sum()) >= MIN_TEXT_PX:
                text[i] = (np.packbits(mask), mask.shape)
        self.frames.append(Frame(at=round(at, 3), rows=list(rows),
                                 slot_yellow=tuple(ys), text=text))

    def by_time(self) -> dict[float, Frame]:
        return {f.at: f for f in self.frames}


# -------------------------------------------------------------------- doubt

def _slot_of(y0: int, y1: int, k: float) -> int:
    rows = slot_rows(k)
    return max(range(len(rows)), key=lambda i: min(y1, rows[i][1]) - max(y0, rows[i][0]))


def doubtful(cap: Capture, kills: list) -> dict[float, set[int]]:
    """Frame time -> the slots worth reading there. `kills` are counted kill events."""
    from .valorant_feed import ASIDE_FLOOR

    k = cap.k
    rows_px = slot_rows(k)
    min_overlap = int(17 * k)
    out: dict[float, set[int]] = {}
    for f in cap.frames:
        covered = any(e.time - COVER_PAD <= f.at <= e.end + COVER_PAD for e in kills)
        slots: set[int] = set()
        for r in f.rows:
            weak = r.kind == "kill" and not covered
            yellow_row = r.kind in ("assist", "other") and \
                (r.left + r.right + r.aside) >= ASIDE_FLOOR * k * k
            if weak or yellow_row:
                slots.add(_slot_of(r.y0, r.y1, k))
        for i, (ya, yb) in enumerate(rows_px):
            has_row = any(min(r.y1, yb) - max(r.y0, ya) >= min_overlap for r in f.rows)
            if f.slot_yellow[i] >= YELLOW_PANEL * k * k and not has_row:
                slots.add(i)
        if slots:
            out[f.at] = slots
    return out


# ---------------------------------------------------------------------- OCR

def ocr_words(bits, shape, k: float = 1.0) -> list[dict]:
    """One slot's white text, read as a single line. x in 1080p band pixels."""
    import pytesseract
    from PIL import Image

    from .deps import tesseract

    pytesseract.pytesseract.tesseract_cmd = tesseract()
    mask = np.unpackbits(bits)[: shape[0] * shape[1]].reshape(shape).astype(bool)
    img = Image.fromarray(np.where(mask, 0, 255).astype(np.uint8))
    img = img.resize((img.width * UPSCALE, img.height * UPSCALE), Image.NEAREST)
    d = pytesseract.image_to_data(img, config="--psm 7",
                                  output_type=pytesseract.Output.DICT)
    x_scale = 1.0 / (UPSCALE * k)
    out = []
    for i, raw in enumerate(d["text"]):
        w = (raw or "").strip()
        if len(w) < 3:
            continue
        left = TEXT_X[0] + d["left"][i] * x_scale
        out.append({"text": w, "left": left, "right": left + d["width"][i] * x_scale})
    return out


def _norm(s: str) -> str:
    from .killfeed import norm
    return norm(s)


def player_in(words: list[dict], player: str):
    """-> ("kill"|"death", word) for the best match of the name, or None."""
    target = _norm(player)
    if not target:
        return None
    best, best_r = None, 0.0
    for w in words:
        r = difflib.SequenceMatcher(None, target, _norm(w["text"])).ratio()
        if r >= MATCH_RATIO and r > best_r:
            best, best_r = w, r
    if best is None:
        return None
    centre = (best["left"] + best["right"]) / 2
    return ("kill" if centre < KILLER_MAX_X else "death"), best


def _victim(words: list[dict], hit: dict) -> str:
    after = [w for w in words if w["left"] > hit["right"] + 15]
    return max(after, key=lambda w: len(w["text"]))["text"] if after else "?"


def _same(a: str, b: str) -> bool:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= SAME_VICTIM


def clean_name(name: str) -> str:
    """Valorant names carry a #tag the feed never shows."""
    return (name or "").split("#", 1)[0].strip()


def learn_name(cap: Capture, kills: list, read=ocr_words) -> str:
    """The most common killer-side name on rows already counted as the player's.

    Votes come only from THE ROW OF EACH COUNTED KILL, found by its own left
    edge in the frames the reader saw it in -- never from whatever else is in
    the feed. Reading every slot of one frame instead votes on teammates'
    rows: on a 100-second excerpt with one kill that elected a teammate, and
    the name was refused, and the whole check silently did nothing.

    Up to LOOKS frames per kill, so a short recording with a single kill still
    reaches the agreement bar on evidence rather than on one reading.
    """
    from .valorant_feed import X_TOL

    LOOKS = 5
    votes: collections.Counter = collections.Counter()
    for e in kills[:12]:
        seen = 0
        for f in cap.frames:
            if seen >= LOOKS or f.at < e.time - 0.01 or f.at > e.end + 0.01:
                continue
            row = next((r for r in f.rows
                        if r.kind == "kill" and abs(r.x0 - e.x0) <= X_TOL * cap.k), None)
            if row is None:
                continue
            slot = _slot_of(row.y0, row.y1, cap.k)
            if slot not in f.text:
                continue
            bits, shape = f.text[slot]
            left = [w for w in read(bits, shape, cap.k)
                    if (w["left"] + w["right"]) / 2 < KILLER_MAX_X and len(w["text"]) >= 4]
            seen += 1
            if left:
                votes[min(left, key=lambda w: w["left"])["text"]] += 1
    if not votes:
        return ""
    name, n = votes.most_common(1)[0]
    total = sum(votes.values())
    if n < LEARN_MIN_VOTES or n / total < LEARN_MIN_SHARE:
        log.info("feed OCR: could not learn the player's name (best %r, %d of %d)",
                 name, n, total)
        return ""
    log.info("feed OCR: learned the player's name as %r (%d of %d)", name, n, total)
    return name


@dataclass
class OcrRow:
    victim: str
    first: float
    last: float
    slot: int
    n: int = 1


def check(cap: Capture, doubt: dict[float, set[int]], player: str,
          read=ocr_words, cancelled=None) -> tuple[list[OcrRow], dict]:
    """The lean check: rows your name is the killer on, from the doubtful slots only."""
    frames = cap.by_time()
    stats = {"reads": 0}

    def victim_at(at: float, slot: int):
        f = frames.get(round(at, 3))
        if f is None or slot not in f.text:
            return None
        bits, shape = f.text[slot]
        stats["reads"] += 1
        words = read(bits, shape, cap.k)
        hit = player_in(words, player)
        if hit and hit[0] == "kill":
            return _victim(words, hit[1])
        return None

    rows: list[OcrRow] = []
    closed: dict[int, float] = {}
    step = 0.0
    times = sorted(frames)
    if len(times) > 1:
        step = min(b - a for a, b in zip(times, times[1:]) if b > a)
    for at in sorted(doubt):
        if cancelled and cancelled():
            break
        for slot in sorted(doubt[at]):
            if closed.get(slot, -1.0) >= at:
                continue
            v = victim_at(at, slot)
            if v is None:
                continue
            r = next((r for r in rows if r.slot == slot and _same(r.victim, v)
                      and at - r.last <= ROW_LIFE), None) or \
                next((r for r in rows if _same(r.victim, v) and at - r.last <= ROW_LIFE), None)
            if r:
                r.last, r.n, r.slot = at, r.n + 1, slot
            else:
                r = OcrRow(victim=v, first=at, last=at, slot=slot)
                rows.append(r)
            if r.n >= CONFIRM:
                closed[slot] = r.first + ROW_LIFE
    rows = [r for r in rows if r.n >= CONFIRM]
    if step > 0:
        for r in rows:
            at = r.first - step
            while r.first - at <= LOOK_BACK + 1e-6:
                v = victim_at(at, r.slot)
                if v is not None and _same(v, r.victim):
                    r.first = at
                    at -= step
                else:
                    break
    return rows, stats


def merge(events: list, rows: list[OcrRow]) -> tuple[list, int, int]:
    """Counted kills plus OCR rows. -> (events, added, re-timed). Kill events only are touched."""
    from .valorant_feed import Event

    kills = sorted((e for e in events if e.kind == "kill"), key=lambda e: e.time)
    used: set[int] = set()
    retimed = 0
    for e in kills:
        mates = [i for i, r in enumerate(rows)
                 if i not in used and r.first - COVER_PAD <= e.end + COVER_PAD
                 and e.time <= r.last + ROW_LIFE]
        if not mates:
            continue
        i = min(mates, key=lambda i: abs(rows[i].first - e.time))
        used.add(i)
        if rows[i].first < e.time - 0.05:
            e.time = rows[i].first
            retimed += 1
    added = [Event(time=r.first, kind="kill", end=r.last, seen=r.n, votes="ocr")
             for i, r in enumerate(rows) if i not in used]
    out = sorted(list(events) + added, key=lambda e: e.time)
    return out, len(added), retimed


def second_look(events: list, cap: Capture, doubt: dict[float, set[int]],
                player: str = "", cancelled=None) -> list:
    """The whole check, never raising. -> events, with any recovered kills added."""
    from .deps import ocr_ready

    if not cap.frames or not doubt:
        return events
    if not ocr_ready():
        log.info("feed OCR: Tesseract is not installed, so doubtful rows were not "
                 "re-read (%d frames were doubtful)", len(doubt))
        return events
    try:
        kills = [e for e in events if e.kind == "kill"]
        name = clean_name(player) or learn_name(cap, kills)
        if not name:
            return events
        rows, stats = check(cap, doubt, name, cancelled=cancelled)
        out, added, retimed = merge(events, rows)
        log.info("feed OCR: %d doubtful frames, %d row reads -> %d kill(s) added, "
                 "%d re-timed (name %r)", len(doubt), stats["reads"], added, retimed, name)
        return out
    except Exception as e:                                   # noqa: BLE001
        log.warning("feed OCR check skipped: %s", e)
        return events
