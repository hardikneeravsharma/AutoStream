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

# WHERE THE WORDS SIT BY DEFAULT: the centre of the line, as shares of the
# frame. Eight of the ten edits studied put the words mid-height, over the
# crosshair; on a vertical reel that is where the kill emblem is, so the
# vertical default sits higher. The player can put them anywhere else.
DEFAULT_POS = {"vertical": (0.5, 0.29), "landscape": (0.5, 0.40)}
POS_EDGE = 0.05

LRCLIB = "https://lrclib.net/api"
LENGTH_TOLERANCE = 3.0          # s. A release whose length differs more is a different cut
MISS_RETRY = 24 * 3600          # s. A song with no lyrics is asked about again after a day
HOOK_REACH = 0.5                # s. How far a kill's accent may move off a light word
MIN_WORD = 0.1                  # s. The shortest a word is on screen
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
    return {"look": look, "face": face, "clean": bool(raw.get("clean")), "pos": _pos(raw.get("pos"))}


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


class Synced(str):
    """Synced lyrics, and the length of the recording they were timed on (0 unknown)."""
    duration: float = 0.0

    def __new__(cls, text: str, duration: float = 0.0):
        obj = super().__new__(cls, text)
        obj.duration = float(duration or 0.0)
        return obj


class Lines(list):
    """Parsed lines, and the length of the recording they were timed on (0 unknown)."""
    ref_seconds: float = 0.0


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
                return Synced(d["syncedLyrics"], d.get("duration") or 0.0)
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
    return Synced(best[0]["syncedLyrics"], best[0].get("duration") or 0.0) if best else ""


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
            # A hit cached before the record's length was kept is asked for
            # again, once: without the length, align() cannot tell which way
            # this recording is cut against the one the lyrics were timed on.
            if held.get("lrc") and "duration" in held:
                out = Lines(parse_lrc(held["lrc"]))
                out.ref_seconds = float(held.get("duration") or 0.0)
                return out, "LRCLIB"
            if not held.get("lrc") and time.time() - float(held.get("when") or 0) < MISS_RETRY:
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
    ref = float(getattr(lrc, "duration", 0.0) or 0.0)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"lrc": str(lrc), "when": time.time(), "duration": ref,
                                     "artist": artist, "title": title}), encoding="utf-8")
    except OSError:
        pass
    if not lrc:
        return [], ""
    out = Lines(parse_lrc(str(lrc)))
    out.ref_seconds = ref
    return out, "LRCLIB"


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


# How far a synced lyric may be moved to meet this recording, how close to a
# candidate a shift has to be, and how much better it has to fit to be taken.
ALIGN_REACH = 3.5
ALIGN_NEAR = 0.3
ALIGN_STEP = 0.02
ALIGN_GAIN = 1.05


def align_score(flux, fps: float, starts, shift: float) -> float:
    """How strongly the vocals rise where the lines say they start, moved by `shift`."""
    import numpy as np
    v = []
    for st in starts:
        a, b = int((st + shift - 0.05) * fps) - 1, int((st + shift + 0.15) * fps) - 1
        if 0 <= a < b <= len(flux):
            v.append(float(flux[a:b].max()))
    return float(np.mean(v)) if v else 0.0


def align(lines: list[Line], flux, fps: float, ref_seconds: float,
          song_seconds: float) -> tuple[float, float]:
    """Seconds to move every line by so it starts where this recording sings it. -> (shift, gain)

    MEASURED ON THE PLAYER'S OWN SONGS. A lyric is timed on one release; the
    file is often another cut of it. JVKE's "(Lyrics)" upload is 121.88 s
    against the 120 s release LRCLIB timed, and every line came 1.9 s early --
    the reel showed each word two seconds before it was sung. "Ambition For
    Cash" is 143.48 s against 143 and came 0.42 s early. Both times the shift
    that best puts the line starts on vocal rises is the difference in length:
    the extra is at the front.

    So the length difference says where to look and the vocals say whether to
    move. Shifts near 0 and near that difference are scored by how strongly
    the vocal band rises at every line start, smoothed over neighbouring
    shifts so one lucky hit cannot win, and the lines move only when the best
    beats leaving them alone by ALIGN_GAIN. Nothing far from those two is
    considered: a dense rap verse rises everywhere, and on Ambition For Cash a
    shift of -2.8 s scored almost as well as the right one. With no record
    length -- a .lrc the player supplied -- only small corrections near 0 are.
    """
    import numpy as np
    starts = [ln.t for ln in lines]
    if len(starts) < 4 or len(flux) < 8:
        return 0.0, 1.0
    shifts = np.round(np.arange(-ALIGN_REACH, ALIGN_REACH + 1e-9, ALIGN_STEP), 3)
    raw = np.array([align_score(flux, fps, starts, s) for s in shifts])
    smooth = np.convolve(raw, np.ones(7) / 7, mode="same")
    centres = [0.0]
    diff = song_seconds - ref_seconds if ref_seconds and song_seconds else 0.0
    if ALIGN_NEAR < abs(diff) <= ALIGN_REACH - ALIGN_NEAR:
        centres.append(diff)
    ok = np.zeros(len(shifts), dtype=bool)
    for c in centres:
        ok |= np.abs(shifts - c) <= ALIGN_NEAR + 1e-9
    base = float(smooth[int(np.argmin(np.abs(shifts)))])
    best = int(np.argmax(np.where(ok, smooth, -np.inf)))
    gain = float(smooth[best]) / base if base > 0 else 1.0
    if gain < ALIGN_GAIN:
        return 0.0, gain
    return float(shifts[best]), gain


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
        cand = [(t, s) for t, s in onsets if a - 0.12 <= t < b]
        if len(cand) >= len(ws):
            times = sorted(t for t, _ in sorted(cand, key=lambda c: -c[1])[:len(ws)])
            times[0] = min(times[0], a + 0.05)
        else:
            times = [a + (b - a) * k / len(ws) for k in range(len(ws))]
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


def build_ass(look: str, rows: list[list[dict]], W: int, H: int, *, face: str = "",
              clean_words: bool = False, pos=None) -> str:
    """The subtitle script that draws `rows` in `look`, at W x H."""
    rows = [[dict(w, w=clean(w["w"]) if clean_words else w["w"]) for w in row] for row in rows]
    fid = face if face in FACES else LOOK_FACE[look]
    fname, bold, fscale, _ = FACES[fid]
    rel = fscale / FACES[LOOK_FACE[look]][2]
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
        top, bot = Y - 0.40 * px, Y + 0.40 * px
        step = (bot - top) / len(bands)
        for wd in words:
            a, b, w = wd["a"], wd["b"], wd["w"].upper()
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
    return _HEAD.format(W=W, H=H, wrap=wrap, style=st) + "".join(evs)


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


def _song_shift(song: str, lines: list[Line]) -> tuple[float, float]:
    """align() on the whole song, which is where the evidence is. -> (shift, gain)"""
    from .tools import media_info
    try:
        seconds = float(media_info(str(song)).get("duration") or 0.0)
    except Exception:                                       # noqa: BLE001
        seconds = 0.0
    flux, fps = vocal_flux(song)
    return align(lines, flux, fps, float(getattr(lines, "ref_seconds", 0.0) or 0.0), seconds)


def prepare(project: dict, derived: dict, cache_dir: Path, W: int, H: int, *,
            finder=find, onsets=vocal_onsets, shifter=_song_shift) -> Prepared:
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
    # THE LINES MOVED ONTO THIS RECORDING FIRST. See align(): a lyric timed on
    # another cut of the song is early or late by however much that cut
    # differs, and every word placed after that inherits it.
    try:
        shift, _gain = shifter(song, lines)
    except Exception as e:                                  # noqa: BLE001
        log.info("lyrics: could not check the timing against the song (%s)", e)
        shift = 0.0
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
    text = build_ass(cfg["look"], rows, W, H, face=cfg["face"], clean_words=cfg["clean"], pos=cfg["pos"])
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    p = cache / f"{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}.ass"
    if not p.is_file():
        p.write_text(text, encoding="utf-8")
    hooks = sum(1 for row in rows for w in row if w.get("hook"))
    return Prepared(p, grey_spans(cfg["look"], rows),
                    f"Lyrics from {source}: {len(rows)} lines, {hooks} on kills."
                    + (f" Moved {shift:+.2f} s to match this recording of the song." if shift else ""),
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
