"""Lyrics on a reel: the song's own words, on its own syllables, red on the kills.

Five looks, each copied from real lyric edits measured frame by frame (see
docs/ROADMAP.md, U3): STAMP (one condensed word per syllable, hard cuts),
GLOW (heavy caps with a halo), SERIF (a small lowercase line that builds),
CAPTION (whole phrases in sentence case) and SCRAWL (huge hand-lettered words).

WHERE THE WORDS COME FROM, in order:
  1. a .lrc file beside the song (same name), so anyone can supply their own;
  2. what was fetched before, cached under the clips folder;
  3. LRCLIB's synced lyrics, matched by artist, title and the song's length --
     a mismatched length is a different recording, and its timestamps would
     put every line in the wrong place.

WHEN EACH WORD APPEARS. A synced lyric only says when a LINE starts. The
words of the line go on the vocal onsets measured in the song itself -- the
300-3400 Hz band, where a voice is and a kick drum is not -- because the real
edits land each word on its sung syllable, 0-70 ms late, never early.

THE RED WORD is the one being sung when a kill lands. A kill on "the" or "a"
moves the accent to the nearest word that carries weight, up to half a second
away: a red "THE" reads as a mistake, not an accent.

Nothing here needs the network to be tested: fetching is one function, and a
song with a .lrc beside it never reaches it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

LOOKS = ("stamp", "glow", "serif", "caption", "scrawl")
LOOK_LABELS = {"off": "No lyrics", "stamp": "Stamp", "glow": "Glow", "serif": "Serif",
               "caption": "Caption", "scrawl": "Scrawl"}
LOOK_BLURBS = {
    "stamp": "One big word per sung syllable, hard cuts. The kill word turns red and grows "
             "while the picture goes grey.",
    "glow": "Heavy white capitals with a soft glow. Filled and hollow words alternate.",
    "serif": "A small lowercase line that builds word by word as it is sung.",
    "caption": "Whole phrases in sentence case, whipping in and out.",
    "scrawl": "Huge hand-lettered words, one or two at a time.",
}

# id -> (ASS font name, bold, size relative to Anton, label). The names are the
# fonts' own full names, which is what libass matches in `fontsdir`.
FACES = {
    "anton": ("Anton", False, 1.0, "Anton"),
    "bebas": ("Bebas Neue", False, 1.08, "Bebas Neue"),
    "poppins-xb": ("Poppins ExtraBold", False, 0.8, "Poppins ExtraBold"),
    "poppins-black": ("Poppins Black", False, 0.8, "Poppins Black"),
    "kanit": ("Kanit Medium", False, 0.86, "Kanit Medium"),
    "crimson": ("Crimson Text", False, 0.92, "Crimson Text"),
    "patrick": ("Patrick Hand", False, 1.0, "Patrick Hand"),
    "kalam": ("Kalam", True, 0.88, "Kalam Bold"),
    "gochi": ("Gochi Hand", False, 1.0, "Gochi Hand"),
}
LOOK_FACE = {"stamp": "anton", "glow": "poppins-xb", "serif": "crimson",
             "caption": "kanit", "scrawl": "patrick"}

# HOW THE WORDS ARRIVE, as a choice of its own.
#
# It used to be welded to the look: Stamp was one word per syllable because
# Stamp was, and somebody who wanted whole lines in Stamp's type had no way to
# ask. Every look draws UNITS out of the placed rows, so the reveal decides
# what a unit is and the look keeps its own type, colour and motion:
#
#   look   each look's own, unchanged -- the default, so nothing moves for
#          anyone who had lyrics set before this
#   word   one word at a time
#   line   the whole line at once, held while it is sung
#   build  the line assembles, a word at a time, and stays up
#   type   a typewriter: the line arrives letter by letter
#
# A unit of several words cannot be drawn at a single word's size, so the
# type shrinks to fit the longest one (see `_shrink`), wrapped at the look's
# own comfortable width.
REVEALS = ("look", "word", "line", "build", "type")
REVEAL_LABELS = {"look": "The look’s own", "word": "One word at a time",
                 "line": "A whole line at a time", "build": "The line builds up",
                 "type": "Typewriter"}
REVEAL_BLURBS = {
    "look": "However the look you picked does it.",
    "word": "Each word on its own, as it is sung.",
    "line": "The whole line appears together and holds while it is sung.",
    "build": "The line assembles a word at a time and stays up to the end of it.",
    "type": "The line arrives letter by letter, at the pace it is sung.",
}
# How many characters of that look's type sit comfortably across the frame.
# Measured from each look's own size against a 1080-wide frame: Stamp at 250px
# fits about eight, Caption at 78px about forty.
REVEAL_FIT = {"stamp": 9, "glow": 12, "serif": 34, "caption": 38, "scrawl": 9}
# A unit never shrinks below this share of the look's size: past it the words
# are no longer the look you chose.
REVEAL_MIN_SCALE = 0.42

# THE BOX THE WORDS LIVE IN, how big they are in it, and how solid.
#
# Stamp draws a word at 250px, which is most of a 1080 frame -- fine for
# "YEAH" and a wall for "YEAH HELL", and worse once a reveal puts a whole
# line in it. The box is a share of the frame's width: the words wrap inside
# it and come down in size until they fit, so narrowing it is how you keep
# the lyrics out of the picture rather than over it.
BOX_MIN, BOX_MAX = 0.2, 1.0
SIZE_MIN, SIZE_MAX = 0.5, 1.6
# Fully transparent lyrics would be a setting that looks like a bug, so the
# faintest offered still reads over a bright frame.
ALPHA_MIN, ALPHA_MAX = 0.15, 1.0

# WHERE THE WORDS SIT BY DEFAULT: the centre of the line, as shares of the
# frame. Eight of the ten edits studied put the words mid-height, over the
# crosshair; on a vertical reel that is where the kill emblem is, so the
# vertical default sits higher. The player can put them anywhere else.
DEFAULT_POS = {"vertical": (0.5, 0.29), "landscape": (0.5, 0.40)}
POS_EDGE = 0.05
# How far the player may move every line, earlier or later, in seconds.
SHIFT_MAX = 5.0

LRCLIB = "https://lrclib.net/api"
LENGTH_TOLERANCE = 3.0          # s. A release whose length differs more is a different cut
MISS_RETRY = 24 * 3600          # s. A song with no lyrics is asked about again after a day
HOOK_REACH = 0.5                # s. How far a kill's accent may move off a light word
MIN_WORD = 0.1                  # s. The shortest a word is on screen
# How fast a line is sung when nothing says otherwise: a syllable at least
# every SYLLABLE_MAX seconds and at most every SYLLABLE_MIN, and how far a
# word may move to land on a vocal rise. See place().
SYLLABLE_MAX = 0.32
SYLLABLE_MIN = 0.1
SNAP = 0.1


def _syllables(word: str) -> int:
    """Vowel groups, a silent final e off: near enough to pace a line by."""
    import unicodedata
    # "cliché" is two: the accent is a vowel, not punctuation to drop.
    w = re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", word.lower()))
    n = len(re.findall(r"[aeiouy]+", w))
    if n > 1 and word.lower().endswith("e") and not w.endswith(("le", "ee")):
        n -= 1
    return max(1, n)
LIGHT = frozenset("a an the and or but of to in on at for with i me my you your it is be "
                  "i'm it's uh yeah oh".split())
# Whole-word masks for "clean lyrics". Roots match inside a word (fucking,
# bitches); the short ones only as the whole word, so "class" stays "class".
_ROOTS = ("fuck", "shit", "bitch", "nigg", "pussy", "cunt", "dick")
_WHOLE = frozenset(("ass", "hoe", "hoes", "asshole"))


def settings(raw) -> dict:
    """A project's lyric settings, made safe. Off unless a known look is asked for."""
    raw = raw if isinstance(raw, dict) else {}
    look = raw.get("look") if raw.get("look") in LOOKS else "off"
    face = raw.get("face") if raw.get("face") in FACES else ""
    try:
        shift = float(raw.get("shift") or 0.0)
    except (TypeError, ValueError):
        shift = 0.0
    shift = 0.0 if shift != shift else round(max(-SHIFT_MAX, min(SHIFT_MAX, shift)), 2)
    reveal = raw.get("reveal") if raw.get("reveal") in REVEALS else "look"

    def num(key, lo, hi):
        try:
            v = float(raw.get(key))
        except (TypeError, ValueError):
            return hi if key != "size" else 1.0
        if v != v:                                       # NaN
            return hi if key != "size" else 1.0
        return round(min(hi, max(lo, v)), 3)

    return {"look": look, "face": face, "clean": bool(raw.get("clean")), "pos": _pos(raw.get("pos")),
            "shift": shift, "reveal": reveal,
            # How wide the words may run, how big they are, and how solid.
            "box": num("box", BOX_MIN, BOX_MAX), "size": num("size", SIZE_MIN, SIZE_MAX),
            "alpha": num("alpha", ALPHA_MIN, ALPHA_MAX)}


def _pos(v) -> list[float] | None:
    """Where the words sit, as the centre of the line in shares of the frame.

    None is the look's own place (DEFAULT_POS). Held inside POS_EDGE of every
    side, so a line dragged into a corner still has room to be read.
    """
    try:
        x, y = (float(c) for c in v)
    except (TypeError, ValueError):
        return None
    if not (x == x and y == y):                      # NaN
        return None
    lo, hi = POS_EDGE, 1.0 - POS_EDGE
    return [round(min(hi, max(lo, x)), 4), round(min(hi, max(lo, y)), 4)]


def default_pos(fmt: str) -> list[float]:
    return list(DEFAULT_POS["vertical" if fmt == "vertical" else "landscape"])


def catalog() -> dict:
    """What the page offers: the looks and the faces, in order."""
    return {"looks": [{"key": k, "label": LOOK_LABELS[k], "blurb": LOOK_BLURBS[k],
                       "face": LOOK_FACE[k]} for k in LOOKS],
            "faces": [{"key": k, "label": v[3]} for k, v in FACES.items()],
            "reveals": [{"key": k, "label": REVEAL_LABELS[k], "blurb": REVEAL_BLURBS[k]}
                        for k in REVEALS],
            "default_pos": {k: list(v) for k, v in DEFAULT_POS.items()}}


# ============================================================== the words

@dataclass
class Line:
    t: float                    # song seconds the line starts at
    words: list[str]


def _words(text: str) -> list[str]:
    out = []
    for w in re.sub(r"[{}\\]", "", text).split():
        w = re.sub(r"^[^\w']+|[^\w']+$", "", w)
        if w:
            out.append(w)
    return out


def parse_lrc(text: str) -> list[Line]:
    """[mm:ss.xx] lines -> Lines, sorted. A line may carry several stamps."""
    lines = []
    for raw in str(text or "").splitlines():
        stamps = re.findall(r"\[(\d+):(\d+(?:\.\d+)?)\]", raw)
        if not stamps:
            continue
        words = _words(re.sub(r"\[[^\]]*\]", "", raw))
        if not words:
            continue
        for m, s in stamps:
            lines.append(Line(int(m) * 60 + float(s), list(words)))
    lines.sort(key=lambda ln: ln.t)
    return lines


def _get_json(url: str, timeout: float = 10.0):
    from .. import __version__
    # LRCLIB asks every client to name itself.
    req = urllib.request.Request(url, headers={"User-Agent": f"AutoStream/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_lrclib(artist: str, title: str, seconds: float, *, get=_get_json) -> str:
    """The synced lyrics LRCLIB holds for this recording, or "".

    An exact lookup first; a search by title when the file carries no artist
    (a song saved from YouTube is often only its title), keeping only a result
    whose length is within LENGTH_TOLERANCE of the file's own.
    """
    def fits(d) -> bool:
        return (isinstance(d, dict) and bool(d.get("syncedLyrics"))
                and abs(float(d.get("duration") or 0) - seconds) <= LENGTH_TOLERANCE)
    if artist:
        q = urllib.parse.urlencode({"artist_name": artist, "track_name": title,
                                    "duration": int(round(seconds))})
        try:
            d = get(f"{LRCLIB}/get?{q}")
            if fits(d):
                return d["syncedLyrics"]
        except Exception as e:                              # noqa: BLE001
            log.info("lyrics: no exact match for %s - %s (%s)", artist, title, e)
    q = urllib.parse.urlencode({"q": f"{artist} {title}".strip()} if artist else {"track_name": title})
    try:
        found = get(f"{LRCLIB}/search?{q}") or []
    except Exception as e:                                  # noqa: BLE001
        log.info("lyrics: search failed for %s (%s)", title, e)
        return ""
    best = sorted((d for d in found if fits(d)),
                  key=lambda d: abs(float(d.get("duration") or 0) - seconds))
    return best[0]["syncedLyrics"] if best else ""


def _clean_title(stem: str) -> str:
    """'Ambition For Cash [Wl2In8FvQhE]' -> 'Ambition For Cash'; drops (Lyrics) and the like."""
    t = re.sub(r"\[[^\]]*\]", "", stem)
    t = re.sub(r"\((?:official|lyrics?|audio|video|visualizer)[^)]*\)", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" -")


def find(song: Path, cache_dir: Path, *, seconds: float = 0.0, tags=None,
         fetch=fetch_lrclib) -> tuple[list[Line], str]:
    """-> (lines, where they came from). Empty lines when there are none."""
    side = song.with_suffix(".lrc")
    if side.is_file():
        lines = parse_lrc(side.read_text(encoding="utf-8", errors="replace"))
        if lines:
            return lines, f"{side.name} beside the song"
    key = hashlib.sha1(f"{song.name}|{song.stat().st_size if song.is_file() else 0}".encode()).hexdigest()[:16]
    cache = Path(cache_dir) / f"{key}.json"
    if cache.is_file():
        try:
            held = json.loads(cache.read_text(encoding="utf-8"))
            if held.get("lrc"):
                return parse_lrc(held["lrc"]), "LRCLIB"
            if time.time() - float(held.get("when") or 0) < MISS_RETRY:
                return [], ""
        except (OSError, ValueError):
            pass
    if tags is None:
        from .reel import song_tags
        tags = song_tags(song)
    artist = str(tags.get("artist") or "")
    title = _clean_title(str(tags.get("title") or song.stem))
    if " - " in title and not artist:
        artist, title = (s.strip() for s in title.split(" - ", 1))
    if not seconds:
        from .tools import media_info
        try:
            seconds = float(media_info(str(song)).get("duration") or 0.0)
        except Exception:                                   # noqa: BLE001
            seconds = 0.0
    lrc = fetch(artist, title, seconds) if seconds else ""
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"lrc": lrc, "when": time.time(),
                                     "artist": artist, "title": title}), encoding="utf-8")
    except OSError:
        pass
    return (parse_lrc(lrc), "LRCLIB") if lrc else ([], "")


# ============================================================== the timing

VOCAL_SR, VOCAL_HOP, VOCAL_WIN = 22050, 256, 1024


def vocal_flux(song: str, start: float = 0.0, seconds: float = 0.0):
    """Rising energy in the vocal band (300-3400 Hz), standardised. -> (flux, frames/s)

    Value i is the change into frame i+1, so it sits (i + 1) / fps seconds
    after `start`. `seconds` 0 reads to the end of the song.
    """
    import numpy as np

    from .tools import ffmpeg_raw
    sr, hop, win = VOCAL_SR, VOCAL_HOP, VOCAL_WIN
    args = ["-ss", f"{max(0.0, start):.4f}"] + (["-t", f"{seconds + 0.5:.4f}"] if seconds else [])
    raw = ffmpeg_raw(args + ["-i", str(song), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"])
    x = np.frombuffer(raw, dtype="<f4").astype(np.float32)
    n = (len(x) - win) // hop
    if n < 8:
        return np.zeros(0), sr / hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * np.hanning(win).astype(np.float32), axis=1))
    f = np.fft.rfftfreq(win, 1 / sr)
    band = np.log1p(spec[:, (f > 300) & (f < 3400)])
    flux = np.maximum(np.diff(band, axis=0), 0).sum(1)
    return (flux - flux.mean()) / (float(flux.std()) or 1.0), sr / hop


def vocal_onsets(song: str, start: float, seconds: float) -> list[tuple[float, float]]:
    """(seconds from `start`, strength) for every rise in the vocal band."""
    flux, fps = vocal_flux(song, start, seconds)
    return [(round((i + 1) / fps, 3), round(float(flux[i]), 3)) for i in range(1, len(flux) - 1)
            if flux[i] > flux[i - 1] and flux[i] >= flux[i + 1] and flux[i] > 1.0]


def place(lines: list[Line], offset: float, length: float, onsets: list[tuple[float, float]],
          kills: list[float]) -> list[list[dict]]:
    """Each word of every line sung inside the reel, in reel seconds.

    -> rows of {"w", "a", "b", "hook"}. A line's words go on the strongest
    onsets between its start and the next line's, in time order; with fewer
    onsets than words they are spread evenly. A line is never held past
    about half a second a word, so a long instrumental gap after the last line
    does not leave it on screen.
    """
    rows = []
    starts = [ln.t - offset for ln in lines]
    for i, ln in enumerate(lines):
        a = starts[i]
        nxt = starts[i + 1] if i + 1 < len(lines) else a + 6.0
        b = min(nxt - 0.08, a + 0.55 * len(ln.words) + 1.5, length)
        if b <= 0 or a >= length or b - a < 0.2:
            continue
        ws = ln.words
        # SUNG AT A SINGER'S PACE, THEN HELD. The words used to go on the
        # strongest rises anywhere between this line and the next, and on a
        # piano-and-drums mix the strongest rises are the piano and the drums:
        # TISWFLFIL2 showed "so", then nothing for 1.6 s, then "this is love"
        # in 0.2 s, and stretched a seven-word line over five seconds. Now each
        # word takes its syllables at the pace the line's room allows -- never
        # slower than SYLLABLE_MAX a syllable, so a line with a long gap after
        # it is sung and then its last word held -- and is then moved onto a
        # vocal rise only if one is within SNAP of where that pace puts it.
        syl = [_syllables(w) for w in ws]
        per = min(SYLLABLE_MAX, max(SYLLABLE_MIN, (b - a) / max(1, sum(syl))))
        times, t = [], a
        for n in syl:
            times.append(t)
            t += n * per
        rises = [o for o, _s in onsets]
        for k in range(1, len(times)):
            near = [o for o in rises if abs(o - times[k]) <= SNAP]
            if near:
                times[k] = min(near, key=lambda o: abs(o - times[k]))
        # Two onsets closer than a word can be read are pushed apart, so a
        # one-word look never draws two words over each other.
        for k in range(1, len(times)):
            times[k] = max(times[k], times[k - 1] + MIN_WORD)
        b = max(b, times[-1] + MIN_WORD)
        row = []
        for k, w in enumerate(ws):
            t0 = times[k]
            t1 = times[k + 1] if k + 1 < len(ws) else b
            if t1 <= 0 or t0 >= length:
                continue
            row.append({"w": w, "a": round(max(0.0, t0), 3), "b": round(min(t1, length), 3)})
        if row:
            rows.append(row)
    allw = [w for row in rows for w in row]
    for k in kills:
        if not allw:
            break

        def gap(wd, k=k):
            return 0.0 if wd["a"] <= k < wd["b"] else min(abs(wd["a"] - k), abs(wd["b"] - k))
        best = min(allw, key=gap)
        if gap(best) > 1.0:
            continue                            # nothing is being sung at this kill
        if best["w"].lower() in LIGHT:
            heavy = [wd for wd in allw if wd["w"].lower() not in LIGHT and gap(wd) <= HOOK_REACH]
            best = min(heavy, key=gap) if heavy else best
        best["hook"] = True
    return rows


def clean(word: str) -> str:
    """A swear with its middle starred: n***a, f***ing."""
    low = word.lower()
    if low in _WHOLE or any(r in low for r in _ROOTS):
        if len(word) <= 2:
            return word
        return word[0] + "*" * (len(word) - 2) + word[-1]
    return word


# ============================================================== the looks

RED, RED_DK = "&H003A26E0&", "&H001C0F7A&"

_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: {wrap}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ev(layer: int, a: float, b: float, style: str, text: str) -> str:
    return f"Dialogue: {layer},{_ts(a)},{_ts(b)},{style},,0,0,0,,{text}\n"


def _wrap(text: str, budget: int) -> str:
    """Break a unit over as few lines as keep each inside `budget` characters.

    ASS wraps on its own, but where it wraps is the renderer's business and
    the looks position their text by hand -- so the breaks are decided here,
    where the line's width is also what decides the size.
    """
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        nxt = (cur + " " + w).strip()
        if cur and len(nxt) > budget:
            lines.append(cur)
            cur = w
        else:
            cur = nxt
    if cur:
        lines.append(cur)
    return "\\N".join(lines)


def _budget(look: str, box: float, size: float) -> int:
    """How many characters of this look's type fit across the box.

    REVEAL_FIT is what fits across the whole frame at the look's own size,
    so a narrower box or bigger type fits proportionally fewer.
    """
    full = REVEAL_FIT.get(look, 20)
    return max(3, int(round(full * max(BOX_MIN, box) / max(0.1, size))))


def _regroup(look: str, rows: list[list[dict]], reveal: str, budget: int) -> list[list[dict]]:
    """The units a look should draw, for this reveal. Rows in, rows out.

    Every look reads the same shape -- a list of lines, each a list of
    {w, a, b, hook} -- so changing what a unit IS changes how the words
    arrive without touching a single look's type or motion.
    """
    if reveal not in REVEALS or reveal == "look":
        return rows
    out: list[list[dict]] = []
    for row in rows:
        if not row:
            continue
        if reveal == "word":
            # ONE UNIT PER ROW, for every reveal below as well. Two looks
            # aggregate a whole row themselves -- Caption joins it into one
            # phrase, Serif prepends the words already sung -- so a row of
            # several units comes out doubled ("never never gonna"). A row of
            # one leaves each look drawing exactly what it is given.
            out.extend([[dict(w)] for w in row])
            continue
        end = row[-1]["b"]
        text = " ".join(w["w"] for w in row)
        hook = any(w.get("hook") for w in row)
        if reveal == "line":
            out.append([{"w": _wrap(text, budget), "a": row[0]["a"], "b": end, "hook": hook}])
            continue
        if reveal == "build":
            # Each word adds to what is already there and the whole line
            # holds to the end of it, so the last unit is the full line.
            units = []
            for i, wd in enumerate(row):
                so_far = " ".join(w["w"] for w in row[:i + 1])
                nxt = row[i + 1]["a"] if i + 1 < len(row) else end
                units.append({"w": _wrap(so_far, budget), "a": wd["a"], "b": max(nxt, wd["a"] + MIN_WORD),
                              "hook": bool(wd.get("hook"))})
            out.extend([[u] for u in units])
        else:                                   # type
            # Letter by letter across the line's own span, so the typing
            # keeps pace with the singing rather than a fixed speed.
            units = []
            for i, wd in enumerate(row):
                head = " ".join(w["w"] for w in row[:i])
                nxt = row[i + 1]["a"] if i + 1 < len(row) else end
                span = max(MIN_WORD, nxt - wd["a"])
                step = span / max(1, len(wd["w"]))
                for j in range(1, len(wd["w"]) + 1):
                    so_far = (head + " " if head else "") + wd["w"][:j]
                    a = wd["a"] + step * (j - 1)
                    b = end if (i + 1 == len(row) and j == len(wd["w"])) else a + step
                    units.append({"w": _wrap(so_far, budget), "a": round(a, 3),
                                  "b": round(max(b, a + 0.02), 3), "hook": bool(wd.get("hook"))})
            out.extend([[u] for u in units])
    return out


def _shrink(look: str, rows: list[list[dict]], budget: int) -> float:
    """How far the type must come down for the widest unit to fit.

    A look's size was chosen for the unit it draws -- Stamp's 250px is one
    word. Asked for a whole line, it has to come down or it hangs off both
    edges; never below REVEAL_MIN_SCALE, past which it is not that look any
    more and a wrap is the better answer.
    """
    widest = max((len(part) for row in rows for u in row
                  for part in str(u["w"]).split("\\N")), default=0)
    if widest <= budget:
        return 1.0
    return max(REVEAL_MIN_SCALE, budget / float(widest))


def build_ass(look: str, rows: list[list[dict]], W: int, H: int, *, face: str = "",
              clean_words: bool = False, pos=None, reveal: str = "look",
              box: float = 1.0, size: float = 1.0, alpha: float = 1.0) -> str:
    """The subtitle script that draws `rows` in `look`, at W x H."""
    rows = [[dict(w, w=clean(w["w"]) if clean_words else w["w"]) for w in row] for row in rows]
    budget = _budget(look, box, size)
    # THE BOX COMES OFF THE SIZE BEFORE IT COMES OFF THE LINE. Wrapping at the
    # box's own character count left `_shrink` below with nothing to do -- every
    # row it was handed already fitted, so it returned 1.0 and the type never
    # came down. Stamp kept its 250px and a sung line went DOWN the middle of
    # the frame instead of across it: eight rows at full width, and one word a
    # row once the box was narrowed ("the whole lyrics style is busted").
    #
    # So the wrap is given the characters the type fits once it HAS come down
    # -- its floor is REVEAL_MIN_SCALE -- and `_shrink` then brings it there.
    # The invariant it guarantees is unchanged: widest x scale <= budget, so
    # the widest row still lands exactly inside the box.
    rows = _regroup(look, rows, reveal, max(3, round(budget / REVEAL_MIN_SCALE)))
    fid = face if face in FACES else LOOK_FACE[look]
    fname, bold, fscale, _ = FACES[fid]
    # THE DEFAULT IS UNTOUCHED. A look asked for its own reveal in a
    # full-width box renders exactly as it did before any of this existed;
    # shrinking is what a narrower box or a wider unit buys.
    tight = reveal != "look" or box < 1.0 or size != 1.0
    rel = fscale / FACES[LOOK_FACE[look]][2] * size
    if tight:
        rel *= _shrink(look, rows, budget)
    k = min(W, H) / 1080                    # every size was measured on a 1080-wide frame
    vertical = H > W
    px, py = _pos(pos) or default_pos("vertical" if vertical else "landscape")
    cx = round(W * px)
    Y = round(H * py)
    placed = _pos(pos) is not None
    B = -1 if bold else 0

    def size(px: float) -> int:
        return max(8, round(px * k * rel))

    def style(name: str, px: float, rest: str) -> str:
        return f"Style: {name},{fname},{size(px)},{rest.replace('B,', f'{B},', 1)}"

    def fit(chars: int, font_px: float, per_char: float) -> int:
        """The centre, moved only as far as keeps a line this long inside the frame.

        Placed near an edge, a long line centred there hangs off it: measured
        on a caption at 30% across, "addiction" lost its first letter. libass
        cannot be asked the width, so it is estimated from the character
        count at a per-look rate, generously. A line wider than the frame is
        centred, where it loses least.
        """
        half = chars * font_px * per_char / 2
        lo, hi = W * 0.03 + half, W * 0.97 - half
        return round(W / 2) if lo > hi else round(min(max(cx, lo), hi))

    words = [w for row in rows for w in row]
    evs: list[str] = []
    wrap = 2
    if look == "stamp":
        st = style("Stamp", 250, "&H00FFFFFF,&H00FFFFFF,&H00301808,&H96000000,B,0,0,0,100,100,1,0,1,3,5,5,0,0,0,1")
        px = size(250)
        bands = ["&H00FFEFD6&", "&H00F2C98E&", "&H00D99A4E&", "&H00A8642A&"]
        for wd in words:
            a, b, w = wd["a"], wd["b"], wd["w"].upper()
            # THE GRADIENT HAS TO COVER WHAT IS DRAWN, not one row of it. The
            # four bands are painted by clipping the same word four times, and
            # the clip was a single row's height around the centre -- so a
            # wrapped unit drew its middle row in the gradient and every other
            # row in the base colour, the darkest of the four. One line it was
            # measured on; a reveal that puts a whole line up makes four.
            # 0.40 is the cap height either side of one row; each further row
            # adds a line of 1.2, half of it above the centre and half below.
            half = (0.40 + 0.60 * w.count("\\N")) * px
            top, bot = Y - half, Y + half
            step = (bot - top) / len(bands)
            wx = fit(len(w), px * (1.22 if wd.get("hook") else 1.0), 0.48)
            if wd.get("hook"):
                evs.append(_ev(2, a, b, "Stamp", f"{{\\pos({wx},{Y})\\fad(40,0)\\1c{RED}\\3c{RED_DK}"
                                                 f"\\t(0,{int((b - a) * 1000)},\\fscx122\\fscy122)}}{w}"))
                continue
            evs.append(_ev(0, a, b, "Stamp", f"{{\\pos({wx},{Y})\\fad(40,0)\\1c{bands[-1]}}}{w}"))
            for j, col in enumerate(bands[:-1]):
                y1 = top + j * step - (200 * k if j == 0 else 0)
                y2 = top + (j + 1) * step
                evs.append(_ev(1, a, b, "Stamp", f"{{\\pos({wx},{Y})\\fad(40,0)\\1c{col}\\bord0\\shad0"
                                                 f"\\clip(0,{int(y1)},{W},{int(y2)})}}{w}"))
    elif look == "glow":
        st = style("Glow", 190, "&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,&H00000000,B,0,0,0,100,100,2,0,1,0,0,5,0,0,0,1")
        for i, wd in enumerate(words):
            a, b, w = wd["a"], wd["b"], wd["w"].upper()
            hook = wd.get("hook")
            extra = "\\fscx116\\fscy116\\t(0,180,\\fscx100\\fscy100)" if hook else ""
            col = f"\\1c{RED}\\3c{RED}" if hook else ""
            wx = fit(len(w), size(190) * (1.16 if hook else 1.0), 0.75)
            evs.append(_ev(0, a, b, "Glow", f"{{\\pos({wx},{Y})\\bord{round(18 * k)}\\blur{round(22 * k)}"
                                            f"\\1a&H80&\\3a&H68&\\3c&HFFFFFF&\\1c&HFFFFFF&{col}{extra}}}{w}"))
            if i % 2 and not hook:
                evs.append(_ev(1, a, b, "Glow", f"{{\\pos({wx},{Y})\\1a&HFF&\\bord{max(1, round(4 * k))}"
                                                f"\\3c&HFFFFFF&\\blur0.8{extra}}}{w}"))
            else:
                evs.append(_ev(1, a, b, "Glow", f"{{\\pos({wx},{Y})\\bord0\\blur0.6{col}{extra}}}{w}"))
    elif look == "serif":
        wrap = 0
        margin = round(W * 0.06)
        st = style("Serif", 84, f"&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,B,0,0,0,100,100,0,0,1,0,3,5,{margin},{margin},0,1")
        for row in rows:
            end = row[-1]["b"]
            wx = fit(len(" ".join(w["w"] for w in row)), size(84), 0.45)
            for i, wd in enumerate(row):
                nxt = row[i + 1]["a"] if i + 1 < len(row) else end
                prev = " ".join(("{\\1c" + RED + "}" + p["w"].lower() + "{\\1c&HFFFFFF&}") if p.get("hook")
                                else p["w"].lower() for p in row[:i])
                col = f"\\1c{RED}" if wd.get("hook") else ""
                new = f"{{\\alpha&HFF&\\blur4{col}\\t(0,120,\\alpha&H00&\\blur0.6)}}{wd['w'].lower()}"
                dur = int((nxt - wd["a"]) * 1000)
                out = f"\\t({dur - 180},{dur},\\alpha&HFF&)" if i + 1 == len(row) else ""
                evs.append(_ev(0, wd["a"], nxt, "Serif",
                               f"{{\\pos({wx},{Y})\\blur0.6{out}}}" + (prev + " " if prev else "") + new))
    elif look == "caption":
        st = style("Cap", 78, "&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,B,0,0,0,100,100,0,0,1,0,4,7,0,0,0,1")

        def sc(w: str) -> str:
            return "I" + w[1:].lower() if w.upper() == "I" or w.upper().startswith("I'") else w.lower()
        for li, row in enumerate(rows):
            ws = [("{\\1c" + RED + "}" + sc(w["w"]) + "{\\1c&HFFFFFF&}") if w.get("hook") else sc(w["w"]) for w in row]
            if not ws[0].startswith("{"):
                ws[0] = ws[0][:1].upper() + ws[0][1:]
            half = (len(ws) + 1) // 2
            text = " ".join(ws[:half]) + ("\\N" + " ".join(ws[half:]) if ws[half:] else "")
            a, b = row[0]["a"], row[-1]["b"]
            left = li % 2 == 0
            if placed:
                # Put somewhere by the player: every line centred there,
                # still whipping in from alternate sides.
                plain = [w["w"] for w in row]
                x = fit(max(len(" ".join(plain[:half])), len(" ".join(plain[half:]))), size(78), 0.5)
                an, d = 5, 1 if left else -1
                y = Y
            else:
                x, an, d = (round(W * 0.065), 7, 1) if left else (round(W * 0.935), 9, -1)
                y = Y - round(90 * k) + round(40 * k) * (li % 2)
            sx, drift = x + round(160 * k) * d, x - round(26 * k) * d
            sh = f"\\shad{max(1, round(4 * k))}\\4a&HA0&"
            evs.append(_ev(0, a, a + .13, "Cap", f"{{\\an{an}\\move({sx},{y},{x},{y})\\blur10\\fscx118\\alpha&H60&"
                                                 f"\\t(0,130,\\blur0.8\\fscx100\\alpha&H00&){sh}}}{text}"))
            evs.append(_ev(0, a + .13, max(a + .14, b - .12), "Cap",
                           f"{{\\an{an}\\move({x},{y},{drift},{y})\\blur0.8{sh}}}{text}"))
            evs.append(_ev(0, max(a + .14, b - .12), b, "Cap",
                           f"{{\\an{an}\\move({drift},{y},{drift - round(220 * k) * d},{y})\\blur0.8"
                           f"\\t(0,120,\\blur12\\fscx120\\alpha&HFF&){sh}}}{text}"))
    elif look == "scrawl":
        st = style("Scr", 260, "&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,B,0,0,0,100,100,0,0,1,0,12,5,0,0,0,1")
        shots: list[dict] = []
        for wd in words:
            w = wd["w"].upper()
            if (shots and len(shots[-1]["w"]) + len(w) <= 6 and not wd.get("hook")
                    and not shots[-1].get("hook") and wd["a"] - shots[-1]["b"] < 0.05):
                shots[-1] = {"w": shots[-1]["w"] + "\\N" + w, "a": shots[-1]["a"], "b": wd["b"]}
            else:
                shots.append(dict(wd, w=w))
        whip, looped = .09, False
        for i, s in enumerate(shots):
            rot = (-3, 2, -2, 3)[i % 4]
            sz = f"\\fs{size(200)}" if "\\N" in s["w"] else ""
            col = f"\\1c{RED}" if s.get("hook") else ""
            a, b = s["a"], s["b"]
            wx = fit(max(len(x) for x in s["w"].split("\\N")), size(200 if sz else 260), 0.5)
            evs.append(_ev(1, a, a + whip, "Scr", f"{{\\move({wx + round(760 * k)},{Y},{wx},{Y})\\frz{rot}{sz}{col}"
                                                  f"\\blur14\\fscx135\\t(0,{int(whip * 1000)},\\blur1.2\\fscx100)}}{s['w']}"))
            evs.append(_ev(1, a + whip, max(a + whip + .01, b), "Scr",
                           f"{{\\move({wx},{Y},{wx - round(30 * k)},{Y})\\frz{rot}{sz}{col}\\blur1.2}}{s['w']}"))
            if s.get("hook") and not looped:
                looped = True
                path = ("m 0 0 b 160 -260 760 -300 900 -40 b 980 120 860 300 640 330 "
                        "l 640 312 b 840 282 950 115 878 -30 b 745 -275 175 -240 18 8")
                sc_ = round(100 * k)
                evs.append(_ev(0, a + whip, b, "Scr", f"{{\\an7\\pos({wx - round(460 * k)},{Y - round(230 * k)})"
                                                      f"\\fscx{sc_}\\fscy{sc_}\\p1\\bord0\\shad8\\blur1.5"
                                                      f"\\clip(0,0,{wx - round(450 * k)},{H})\\t(0,320,\\clip(0,0,{W},{H}))}}{path}"))
    else:
        raise ValueError(f"unknown lyric look {look!r}")
    return _opacity(_HEAD.format(W=W, H=H, wrap=wrap, style=st) + "".join(evs), alpha)


def _opacity(script: str, alpha: float) -> str:
    """Fade the whole script to `alpha` (1.0 solid), in place.

    ASS carries transparency in the top byte of every colour and in the
    \alpha override, and the looks animate alpha themselves -- Serif fades
    each word in, Glow fades the line out. So this cannot simply prepend an
    override: it has to move the OPAQUE end of every animation, which is
    `&H00&`, to the chosen value, and dim the style's own colours to match.
    A fade from invisible still starts invisible.
    """
    if alpha >= 1.0:
        return script
    aa = f"{round((1.0 - max(0.0, min(1.0, alpha))) * 255):02X}"

    def colour(m):
        return m.group(1) + aa + m.group(3)

    out = []
    for line in script.splitlines(keepends=True):
        if line.startswith("Style:"):
            # &HAABBGGRR -- only the alpha byte of each colour moves.
            line = re.sub(r"(&H)([0-9A-Fa-f]{2})([0-9A-Fa-f]{6})", colour, line)
        elif line.startswith("Dialogue:"):
            line = line.replace("\\alpha&H00&", f"\\alpha&H{aa}&")
        out.append(line)
    return "".join(out)


def grey_spans(look: str, rows: list[list[dict]]) -> list[tuple[float, float]]:
    """Where Stamp greys the picture: under each held red word."""
    if look != "stamp":
        return []
    return [(w["a"], w["b"]) for row in rows for w in row if w.get("hook")]


# ============================================================== one reel

@dataclass
class Prepared:
    ass: Path | None
    greys: list[tuple[float, float]]
    note: str
    lines: int = 0
    hooks: int = 0


def prepare(project: dict, derived: dict, cache_dir: Path, W: int, H: int, *,
            finder=find, onsets=vocal_onsets) -> Prepared:
    """Everything the join needs to draw this reel's lyrics, or why there are none."""
    cfg = settings(project.get("lyrics"))
    if cfg["look"] == "off":
        return Prepared(None, [], "")
    song = project.get("song") or ""
    if not song:
        return Prepared(None, [], "Lyrics need a song, so this reel has none.")
    try:
        lines, source = finder(Path(song), Path(cache_dir))
    except Exception as e:                                  # noqa: BLE001
        log.warning("lyrics: lookup failed for %s: %s", song, e)
        lines, source = [], ""
    if not lines:
        return Prepared(None, [], "No synced lyrics were found for this song, so the reel has none. "
                                  "A .lrc file with the song's name, beside it, adds them.")
    # THE PLAYER'S OWN TIMING, before any word is placed. A synced lyric is
    # timed on one release of a song and the file is often another cut: on
    # JVKE's "(Lyrics)" upload LRCLIB's lines came 0.9 s early (median of 22
    # lines against that upload's own on-screen lyrics). Working that out
    # from the audio was tried and measured unreliable -- it chose +1.9 s, a
    # bar out, because a drum-heavy mix rises everywhere -- so the player
    # sets it by ear, and every line moves together.
    shift = cfg["shift"]
    if shift:
        lines = [Line(ln.t + shift, ln.words) for ln in lines]
    offset = float(project.get("song_offset") or 0.0)
    L = float(derived["length"])
    try:
        ons = onsets(song, offset, L)
    except Exception as e:                                  # noqa: BLE001
        log.info("lyrics: no vocal onsets (%s); words are spread evenly", e)
        ons = []
    rows = place(lines, offset, L, ons, list(derived.get("kills") or []))
    if not rows:
        return Prepared(None, [], "Nothing is sung in the part of the song this reel uses.")
    text = build_ass(cfg["look"], rows, W, H, face=cfg["face"], clean_words=cfg["clean"],
                     pos=cfg["pos"], reveal=cfg.get("reveal") or "look",
                     box=cfg.get("box", 1.0), size=cfg.get("size", 1.0),
                     alpha=cfg.get("alpha", 1.0))
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    p = cache / f"{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}.ass"
    if not p.is_file():
        p.write_text(text, encoding="utf-8")
    hooks = sum(1 for row in rows for w in row if w.get("hook"))
    return Prepared(p, grey_spans(cfg["look"], rows),
                    f"Lyrics from {source}: {len(rows)} lines, {hooks} on kills."
                    + (f" Every line moved {shift:+.2f} s." if shift else ""),
                    lines=len(rows), hooks=hooks)


_HAS_ASS: dict[str, bool] = {}


def ffmpeg_draws_ass(ff: str) -> bool:
    """Whether this ffmpeg was built with libass. Asked once per binary."""
    if ff not in _HAS_ASS:
        import subprocess

        from .killfeed import _NO_WINDOW
        try:
            r = subprocess.run([ff, "-hide_banner", "-filters"], capture_output=True, text=True,
                               creationflags=_NO_WINDOW, timeout=20)
            _HAS_ASS[ff] = bool(re.search(r"^\s*\S+\s+ass\s", r.stdout or "", re.M))
        except (OSError, subprocess.SubprocessError):
            _HAS_ASS[ff] = False
    return _HAS_ASS[ff]


# ====================================================== the preview's words

# THE WORDS OVER THE PREVIEW, BEFORE ANY RENDER. The instant preview plays the
# timeline off the clip files, and a lyric look changed there showed nothing
# until the render came back -- 20-odd seconds to see whether Glow suits the
# song better than Stamp. So the same subtitle script is drawn on its own, on
# nothing, into a small transparent video the page lays over the preview and
# keeps on the reel's clock. Same script, same libass, same fonts: what shows
# is what the render will draw, only smaller.
OVERLAY_FPS = 15
OVERLAY_SHORT = 540            # the frame's short side; libass scales the script to it


def mask_ass(text: str) -> str:
    """The same script with every colour white and every alpha kept.

    libass cannot draw onto a transparent frame -- it blends into the pixels,
    and the alpha channel stays empty -- so the overlay is drawn twice on
    black: once as it is, which is colour times coverage, and once in white,
    which is the coverage alone. Dividing the first by the second gives the
    colour back, and the second is the alpha.
    """
    out = []
    for line in text.splitlines(True):
        if line.startswith("Style:"):
            line = re.sub(r"&H([0-9A-Fa-f]{2})[0-9A-Fa-f]{6}", r"&H\g<1>FFFFFF", line)
        elif line.startswith("Dialogue:"):
            line = re.sub(r"\\([1-4]?c)&H[0-9A-Fa-f]{1,8}&", r"\\\g<1>&HFFFFFF&", line)
        out.append(line)
    return "".join(out)


def overlay_size(W: int, H: int) -> tuple[int, int]:
    k = OVERLAY_SHORT / min(W, H)
    return (round(W * k / 2) * 2, round(H * k / 2) * 2)


def overlay(ass: Path, W: int, H: int, length: float, out: Path) -> Path:
    """`ass` drawn alone into a transparent VP9 .webm at `out`. -> out.

    Measured on a 62 s Glow reel: 2.7 s. Work is done only where a word is,
    since most of every frame is empty.
    """
    import subprocess

    import numpy as np

    from .tools import _NO_WINDOW, binary

    ff = binary("ffmpeg")
    w, h = overlay_size(W, H)
    ass = Path(ass)
    mask = ass.with_name(ass.stem + ".mask.ass")
    if not mask.is_file():
        mask.write_text(mask_ass(ass.read_text(encoding="utf-8")), encoding="utf-8")
    def arg(p: Path) -> str:
        """A path as a quoted filter option: 'C\\:/like/this'."""
        return "'" + str(p).replace("\\", "/").replace(":", "\\:") + "'"

    def draw(script: Path):
        return subprocess.Popen(
            [ff, "-hide_banner", "-loglevel", "error", "-nostdin",
             "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={OVERLAY_FPS}:d={max(0.1, length):.3f}",
             "-vf", f"format=rgb24,ass=filename={arg(script)}:fontsdir={arg(FONTS_DIR)}",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)

    tmp = out.with_name(out.stem + ".part.webm")
    col, cov = draw(ass), draw(mask)
    enc = subprocess.Popen(
        [ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", str(OVERLAY_FPS), "-i", "-",
         "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-deadline", "realtime", "-cpu-used", "8",
         "-row-mt", "1", "-b:v", "0", "-crf", "36", "-auto-alt-ref", "0", str(tmp)],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    n = w * h * 3
    frame = np.zeros((h, w, 4), np.uint8)
    try:
        while True:
            ca, ma = col.stdout.read(n), cov.stdout.read(n)
            if len(ca) < n or len(ma) < n:
                break
            m = np.frombuffer(ma, np.uint8).reshape(h, w, 3)[..., 1]
            frame[:] = 0
            rows = np.flatnonzero(m.max(axis=1))
            if rows.size:
                y0, y1 = rows[0], rows[-1] + 1
                cols = np.flatnonzero(m[y0:y1].max(axis=0))
                x0, x1 = cols[0], cols[-1] + 1
                a = m[y0:y1, x0:x1]
                c = np.frombuffer(ca, np.uint8).reshape(h, w, 3)[y0:y1, x0:x1]
                frame[y0:y1, x0:x1, :3] = np.minimum(
                    255, c.astype(np.uint16) * 255 // np.maximum(a, 1).astype(np.uint16)[..., None])
                frame[y0:y1, x0:x1, 3] = a
            enc.stdin.write(frame.tobytes())
    finally:
        for p in (col, cov):
            p.stdout.close()
            p.wait()
        enc.stdin.close()
        enc.wait()
    if enc.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        raise RuntimeError("the lyric overlay could not be encoded")
    tmp.replace(out)
    return out
