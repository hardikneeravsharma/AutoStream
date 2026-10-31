r"""The match video, edited the way a match is shown -- not the way a montage is.

WHY THIS IS NOT highlight.py
    The recap was first cut by the Marvel Rivals highlight renderer: a whip slide and
    a synthesised whoosh between every moment, a synthesised hit and a two-frame white
    flash on every kill, an Impact title, a white flash into the result. The player
    watched the first Valorant recap made that way and said the fonts were terrible,
    the transitions and kill sounds not good, and "don't follow the approach of the
    Marvel highlights video" (2026-11-01). ChatGPT, asked how professional Valorant
    match and highlight videos are cut (Sinatraa, shroud, s0m, Subroza -- see
    docs/plans/2026-11-01-match-video-and-moments.md), set the rules this follows:

    * HARD CUTS between moments of one round; a dip to black of five frames between
      rounds, and a card at half-time. No whip, no whoosh, no flash.
    * THE GAME'S OWN SOUND. No hit added to a kill: the game's weapon, hit and kill
      sounds are the play. The recording's mix (the game and the player's mic) is
      kept as it is, normalised to -16 LUFS integrated, -1 dBTP.
    * NATURAL COLOUR. No grade.
    * TWO TYPEFACES from the player's own pack: Montserrat ExtraBold for the title,
      Alte Haas Grotesk Bold for everything else; off-white, gold only for the
      result. Cards on a dark translucent plate with rounded corners, top centre,
      gone before the kill. A font that lacks a glyph the text needs is not used.
    * THE MATCH'S STORY on screen: the title card says how the match went
      (match_story.Story.line), each moment's card carries a bar of every round --
      won, lost, half-time, the one being shown -- and the video ends on the final
      score and the player's line for the match.
    * THE FACECAM as recorded during play; on a strong reaction, a short close-up of
      it cut in after the action, from the box the player marked (clips/facecam.py's
      inset) -- never a box guessed, never two faces at once.

    Graphics are drawn by Pillow into transparent PNGs and laid over the footage by
    ffmpeg, so they are typeset (kerning, a real plate, rounded corners) rather than
    drawtext's one line of text.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import paths

log = logging.getLogger(__name__)

W, H = 1920, 1080
FPS = 60

# The player's font pack, and the two faces ChatGPT chose from it (sheet numbers 03
# and 05). A fresh install has no pack: the bundled OFL faces stand in.
PACK = paths.VIDEO_HOME / "assets" / "fonts" / "km-mustahin"
BUNDLED = Path(__file__).resolve().parent / "fonts"
TITLE_FACES = ("Montserrat-ExtraBold.ttf", "Montserrat-Black.ttf")
TEXT_FACES = ("AlteHaasGroteskBold.ttf", "Montserrat-Bold.ttf")
TITLE_FALLBACK = "Poppins-ExtraBold.ttf"
TEXT_FALLBACK = "Kanit-Medium.ttf"

OFF_WHITE = (242, 242, 238, 255)
MUTED = (200, 202, 208, 255)
GOLD = (232, 193, 90, 255)
WIN = (79, 209, 197, 255)       # the player's team on the round bar
LOSS = (255, 90, 95, 255)
PLATE = (8, 10, 14, 186)        # about 73 % -- ChatGPT's 70-75

CARD_IN = 0.35                  # after the cut
CARD_SECONDS = 1.8
CARD_CLEAR = 0.25               # gone this long before the moment's first kill
CARD_SHORTEST = 0.8
CARD_Y = 0.095                  # top centre, under the score bar
DIP = 5 / FPS                   # the dip to black between rounds
TITLE_SECONDS = 2.4
HALF_SECONDS = 1.8
RESULT_SECONDS = 3.2
CUTAWAY_SECONDS = 1.2           # the facecam close-up: 0.8-1.5 s
CUTAWAY_AFTER_KILL = 0.4
CUTAWAY_WIDTH = 0.6             # of the frame's width
CUTAWAYS = 3                    # a close-up is for the reactions that earn one, not every one
CUTAWAY_TRIM = 0.03             # inside the marked box, so its frame and the game around it stay out


# ---------------------------------------------------------------- fonts

def has_glyphs(font: ImageFont.FreeTypeFont, text: str) -> bool:
    """Whether the font draws every character in `text` rather than its empty box.

    Two fonts on the player's sheet (Akira, Eurostile) have no "·" and drew a box
    where the separator should be (ChatGPT: "missing glyphs must trigger a
    fallback, never a box"). A character is missing when its mask is the same as
    the font's mask for a code point no font draws."""
    def ink(ch: str) -> bytes:
        size = max(8, int(getattr(font, "size", 40) * 2))
        img = Image.new("L", (size, size), 0)
        ImageDraw.Draw(img).text((size // 4, size // 4), ch, font=font, fill=255)
        return img.tobytes()

    try:
        blank = ink("\U0010FFFD")
        for ch in set(text) - {" "}:
            if ink(ch) == blank:
                return False
    except Exception:  # noqa: BLE001 - a font PIL cannot even draw with is no use
        return False
    return True


def face(kind: str, size: int, text: str = "") -> ImageFont.FreeTypeFont:
    """The title or text face at `size` px: the pack's first face that has every
    glyph in `text`, else the bundled fallback."""
    names = TITLE_FACES if kind == "title" else TEXT_FACES
    for name in names:
        p = PACK / name
        if p.is_file():
            try:
                f = ImageFont.truetype(str(p), size)
            except OSError:
                continue
            if not text or has_glyphs(f, text):
                return f
    fb = BUNDLED / (TITLE_FALLBACK if kind == "title" else TEXT_FALLBACK)
    return ImageFont.truetype(str(fb), size)


# ---------------------------------------------------------------- graphics

def _rounded(d: ImageDraw.ImageDraw, box, fill, r=14):
    d.rounded_rectangle(box, radius=r, fill=fill)


def round_bar(won: list[bool | None], half: int, current: int | None, width: int,
              height: int = 10, gap: int = 3) -> Image.Image:
    """One segment per round -- teal for the player's team, red for the other --
    a gap at half-time, the round being shown outlined. Every score shown comes
    from the match record."""
    n = max(1, len(won))
    halves = 1 if n <= half else 2
    seg = (width - gap * (n - 1) - (12 if halves == 2 else 0)) / n
    img = Image.new("RGBA", (width, height + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = 0.0
    for i, w in enumerate(won, 1):
        col = WIN if w is True else LOSS if w is False else (120, 120, 128, 255)
        if current is not None and i != current:
            col = col[:3] + (150,)
        d.rectangle([round(x), 4, round(x + seg) - 1, 4 + height - 1], fill=col)
        if current == i:
            d.rectangle([round(x) - 2, 1, round(x + seg) + 1, 4 + height + 2], outline=OFF_WHITE, width=2)
        x += seg + gap
        if i == half and halves == 2:
            x += 12
    return img


def _text(d, xy, s, font, fill, anchor="mm"):
    d.text(xy, s, font=font, fill=fill, anchor=anchor)


def context_card(line: str, label: str, won: list[bool | None], half: int, current: int | None) -> Image.Image:
    """The moment's card: what round, what score, what is at stake, and where in the
    match it falls. A transparent frame-sized PNG; the plate sits top centre."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f1 = face("text", int(H * 0.025), line)
    f2 = face("text", int(H * 0.026), label)
    w1 = d.textlength(line, font=f1)
    w2 = d.textlength(label, font=f2) if label else 0
    bar_w = 460 if won else 0
    pw = int(max(w1, w2, bar_w) + 64)
    ph = 44 + (36 if label else 0) + (26 if won else 0)
    x0 = (W - pw) // 2
    y0 = int(H * CARD_Y)
    _rounded(d, [x0, y0, x0 + pw, y0 + ph], PLATE)
    y = y0 + 26
    _text(d, (W // 2, y), line, f1, OFF_WHITE)
    if label:
        y += 36
        _text(d, (W // 2, y), label, f2, GOLD)
    if won:
        bar = round_bar(won, half, current, bar_w)
        img.alpha_composite(bar, ((W - bar_w) // 2, y + 18))
    return img


def title_card(head: str, sub_gold: str, sub_rest: str, story_line: str) -> Image.Image:
    """The title over the match's opening shot: a dark wash, then the map, the
    result in gold, the player's line, and one sentence of how the match went."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wash = Image.new("RGBA", (W, H), (6, 8, 12, 150))
    img.alpha_composite(wash)
    d = ImageDraw.Draw(img)
    ft = face("title", int(H * 0.058), head)
    fs = face("text", int(H * 0.029), sub_gold + sub_rest)
    fl = face("text", int(H * 0.024), story_line)
    cy = int(H * 0.43)
    _text(d, (W // 2, cy), head, ft, OFF_WHITE)
    wg = d.textlength(sub_gold, font=fs)
    wr = d.textlength(sub_rest, font=fs)
    x = (W - (wg + wr)) / 2
    d.text((x, cy + 70), sub_gold, font=fs, fill=GOLD, anchor="lm")
    d.text((x + wg, cy + 70), sub_rest, font=fs, fill=OFF_WHITE, anchor="lm")
    if story_line:
        _text(d, (W // 2, cy + 122), story_line, fl, MUTED)
    return img


def full_card(background: Image.Image | None, heading: str, big: str, big_col, lines: list[str],
              won: list[bool | None], half: int) -> Image.Image:
    """A whole-frame card -- half-time, the result -- over a blurred, darkened frame
    of the match itself, never a stock background."""
    if background is not None:
        bg = background.convert("RGB").resize((W, H)).filter(ImageFilter.GaussianBlur(18))
        img = bg.convert("RGBA")
        img.alpha_composite(Image.new("RGBA", (W, H), (6, 8, 12, 190)))
    else:
        img = Image.new("RGBA", (W, H), (10, 12, 16, 255))
    d = ImageDraw.Draw(img)
    fh = face("text", int(H * 0.028), heading)
    fb = face("title", int(H * 0.09), big)
    fl = face("text", int(H * 0.027), " ".join(lines))
    cy = int(H * 0.36)
    _text(d, (W // 2, cy), heading, fh, MUTED)
    _text(d, (W // 2, cy + 90), big, fb, big_col)
    y = cy + 180
    for ln in lines:
        _text(d, (W // 2, y), ln, fl, OFF_WHITE)
        y += 46
    if won:
        bar = round_bar(won, half, None, 640, height=12)
        img.alpha_composite(bar, ((W - 640) // 2, y + 16))
    return img


# ---------------------------------------------------------------- the edit

@dataclass
class Piece:
    """One stretch of the finished video, in order."""
    kind: str                         # open | intro | moment | half | result
    start: float = 0.0                # source seconds (footage pieces)
    end: float = 0.0
    round: int | None = None
    card: str = ""                    # a PNG laid over it (moment, intro)
    first_kill: float | None = None   # source seconds, for the card to clear
    cutaway: float | None = None      # source seconds where the facecam close-up goes
    still: str = ""                   # a PNG that IS the piece (half, result)
    seconds: float = 0.0              # for stills
    dip_in: bool = False
    dip_out: bool = False

    @property
    def length(self) -> float:
        return self.seconds if self.still else max(0.0, self.end - self.start)


def plan(moments, *, opening, story, cold: tuple[float, float] | None,
         facecam_box: list[float] | None) -> list[Piece]:
    """The pieces in order: cold open, intro, the moments (a half-time card where
    the match turns sides), the result. Dips between rounds; hard cuts within one."""
    out: list[Piece] = []
    if cold:
        out.append(Piece("open", cold[0], cold[1]))
    if opening is not None:
        out.append(Piece("intro", opening.start, opening.end, dip_in=bool(cold)))
    last_round = None
    half_done = False
    for m in moments:
        n = int(getattr(m.round, "number", 0) or 0) or None
        if story is not None and n and not half_done and n > story.half and last_round is not None \
                and last_round <= story.half:
            out.append(Piece("half", seconds=HALF_SECONDS, still="half.png", dip_in=True, dip_out=True))
            half_done = True
        p = Piece("moment", m.start, m.end, round=n,
                  first_kill=(min(m.kills) if m.kills else None),
                  dip_in=bool(out) and n is not None and n != last_round)
        react_at = getattr(m, "react_at", None)
        if facecam_box and m.reaction and react_at is not None:
            at = max(float(react_at), (max(m.kills) + CUTAWAY_AFTER_KILL) if m.kills else float(react_at))
            if m.start + 1.0 <= at <= m.end - CUTAWAY_SECONDS - 0.3:
                p.cutaway = at
        out.append(p)
        last_round = n if n is not None else last_round
    if story is not None:
        out.append(Piece("result", seconds=RESULT_SECONDS, still="result.png", dip_in=True))
    # Only the strongest few reactions get the close-up (ChatGPT: "only when the
    # reaction deserves attention"); the first render put one on seven of fifteen.
    with_cut = [p for p in out if p.cutaway is not None]
    strength = {id(p): s for p, s in zip(
        [p for p in out if p.kind == "moment"],
        [getattr(m, "react_score", 0.0) for m in moments])}
    for p in sorted(with_cut, key=lambda p: -strength.get(id(p), 0.0))[CUTAWAYS:]:
        p.cutaway = None
    for a, b in zip(out, out[1:]):
        if b.dip_in:
            a.dip_out = True
    return out


def card_label(name: str, round_number: int | None) -> str:
    """A moment's name for its card: the card's first line already says the round, so
    "Round 24 - Final round" is "Final round" there (the chapter keeps the round)."""
    import re

    s = str(name or "")
    if round_number:
        s = re.sub(rf"^Round 0?{round_number} - ", "", s)
        s = re.sub(rf" - Round 0?{round_number}(?= - |$)", "", s)
    return s


def card_window(p: Piece) -> tuple[float, float] | None:
    """When a moment's card is on screen, in the piece's own seconds: from CARD_IN for
    CARD_SECONDS, gone CARD_CLEAR before its first kill; None if that leaves less
    than CARD_SHORTEST."""
    a = CARD_IN
    b = a + CARD_SECONDS
    if p.first_kill is not None:
        b = min(b, p.first_kill - p.start - CARD_CLEAR)
    return (a, b) if b - a >= CARD_SHORTEST else None


def graph(pieces: list[Piece], inputs: dict[int, int], cards: dict[int, int],
          facecam_box: list[float] | None) -> str:
    """The filter graph joining the pieces. `inputs[i]` is the ffmpeg input of piece
    i (its cut or its still), `cards[i]` the input of the PNG laid over it."""
    fc: list[str] = []
    segs = []
    for i, p in enumerate(pieces):
        L = p.length
        v = f"[{inputs[i]}:v]"
        chain = f"{v}fps={FPS},scale={W}:{H}:flags=lanczos,format=yuv420p,setsar=1"
        if p.still:
            chain += f",trim=0:{L:.3f},setpts=PTS-STARTPTS"
        fc.append(chain + f"[b{i}]")
        cur = f"b{i}"
        if p.cutaway is not None and facecam_box:
            x, y, w, h = facecam_box
            x, y = x + w * CUTAWAY_TRIM, y + h * CUTAWAY_TRIM
            w, h = w * (1 - 2 * CUTAWAY_TRIM), h * (1 - 2 * CUTAWAY_TRIM)
            a = p.cutaway - p.start
            b = a + CUTAWAY_SECONDS
            cw = int(W * CUTAWAY_WIDTH) // 2 * 2
            fc.append(f"[{cur}]split=3[m{i}][g{i}][f{i}]")
            fc.append(f"[g{i}]boxblur=24:2,eq=brightness=-0.22[gb{i}]")
            fc.append(f"[f{i}]crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},scale={cw}:-2:flags=lanczos,"
                      f"pad=iw+8:ih+8:4:4:color=0xF2F2EE@0.9[fc{i}]")
            fc.append(f"[gb{i}][fc{i}]overlay=(W-w)/2:(H-h)/2[cut{i}]")
            fc.append(f"[m{i}][cut{i}]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'[k{i}]")
            cur = f"k{i}"
        win = None
        if i in cards:
            win = (0.0, TITLE_SECONDS) if p.kind == "intro" else card_window(p)
        if win:
            a, b = win
            fc.append(f"[{cards[i]}:v]format=rgba,fade=t=in:st={a:.3f}:d=0.2:alpha=1,"
                      f"fade=t=out:st={b - 0.25:.3f}:d=0.25:alpha=1[c{i}]")
            fc.append(f"[{cur}][c{i}]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'[o{i}]")
            cur = f"o{i}"
        fades = []
        if p.dip_in:
            fades.append(f"fade=t=in:st=0:d={DIP:.3f}")
        if p.dip_out:
            fades.append(f"fade=t=out:st={max(0.0, L - DIP):.3f}:d={DIP:.3f}")
        fc.append(f"[{cur}]{','.join(fades) if fades else 'null'}[v{i}]")
        if p.still:
            fc.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{L:.3f}[a{i}]")
        else:
            ad = 0.08 if p.dip_in else 0.02
            ao = 0.08 if p.dip_out else 0.03
            fc.append(f"[{inputs[i]}:a]aresample=48000,aformat=channel_layouts=stereo,"
                      f"afade=t=in:d={ad},afade=t=out:st={max(0.0, L - ao):.3f}:d={ao}[a{i}]")
        segs.append(f"[v{i}][a{i}]")
    fc.append("".join(segs) + f"concat=n={len(pieces)}:v=1:a=1[vc][ac]")
    total = sum(p.length for p in pieces)
    fc.append(f"[vc]fade=t=out:st={max(0.0, total - 1.0):.3f}:d=1.0[vout]")
    fc.append("[ac]loudnorm=I=-16:TP=-1:LRA=11,aresample=48000[aout]")
    return ";\n".join(fc)


def chapters(pieces: list[Piece], names: dict[int, str]) -> list[tuple[float, str]]:
    """YouTube chapters: the intro at 0:00, each moment by name, the final score.

    `names[i]` is moment piece i's chapter name. The cold open and the half-time card
    are not chapters -- a viewer jumps to plays, not to a card -- and a chapter under
    ten seconds after the last one is dropped (YouTube shows none if one is shorter).
    Fewer than three is none at all."""
    marks: list[tuple[float, str]] = []
    for i, (p, off) in enumerate(zip(pieces, offsets(pieces))):
        name = ("Intro" if p.kind == "intro" else "Final score" if p.kind == "result"
                else names.get(i, "") if p.kind == "moment" else "")
        if not name or (marks and off - marks[-1][0] < 10.0):
            continue
        marks.append((round(off, 2), name))
    if marks and marks[0][0] > 0.0:
        marks[0] = (0.0, marks[0][1]) if marks[0][0] < 10.0 else marks[0]
        if marks[0][0] > 0.0:
            marks.insert(0, (0.0, "Intro"))
    return marks if len(marks) >= 3 else []


def facts(game: str, record: dict, story, *, map_name: str = "", agent: str = "") -> Facts:
    """What the title and the final card say. From the match record when there is one
    -- the whole match, not the rounds the recording happens to hold -- else from the
    rounds read off the recording."""
    a, b = story.final if story is not None else (0, 0)
    verdict = "WIN" if a > b else "LOSS" if b > a else "DRAW"
    place = (record.get("map") or map_name or "").upper()
    who = (record.get("agent") or agent or "").upper()
    bits = [who] if who else []
    if record.get("kills") is not None and record:
        bits.append(f"{record['kills']} / {record['deaths']} / {record['assists']}")
    if record.get("acs"):
        bits.append(f"ACS {record['acs']}")
    line = story.line() if story is not None else ""
    return Facts(head=f"{(game or 'MATCH').upper()}" + (f"  ·  {place}" if place else ""),
                 result=f"{a}-{b} {verdict}" if (a or b) else "",
                 line="  ·  ".join(bits),
                 story_line=line[:1].upper() + line[1:],
                 won=list(story.won) if story is not None else [],
                 half=story.half if story is not None else 12)


def offsets(pieces: list[Piece]) -> list[float]:
    """Where each piece starts in the finished video: hard cuts, so a running sum."""
    out, t = [], 0.0
    for p in pieces:
        out.append(round(t, 3))
        t += p.length
    return out


# ---------------------------------------------------------------- render

def _frame(source: Path, at: float) -> Image.Image | None:
    from .tools import ffmpeg_raw

    raw = ffmpeg_raw(["-ss", f"{max(0.0, at):.3f}", "-i", str(source), "-frames:v", "1",
                      "-vf", f"scale={W // 2}:{H // 2}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    if len(raw) < (W // 2) * (H // 2) * 3:
        return None
    return Image.frombytes("RGB", (W // 2, H // 2), raw[:(W // 2) * (H // 2) * 3])


@dataclass
class Facts:
    """What the cards say, from the match record."""
    head: str                         # "VALORANT · BIND"
    result: str                       # "11-13 LOSS"
    line: str                         # "CYPHER · 22 / 18 / 7 · ACS 274"
    story_line: str = ""              # "4-8 at the half, came back from 4-11 to 11-12, lost 11-13"
    won: list[bool | None] = field(default_factory=list)
    half: int = 12
    win_col: tuple = GOLD


def render(source: Path, pieces: list[Piece], out: Path, *, facts: Facts, cards_for: dict[int, tuple[str, str]],
           facecam_box: list[float] | None, encoder: str = "auto", cq: int = 21,
           progress: Callable[[int, int], None] | None = None) -> Path:
    """Cut the footage pieces, draw the cards, join it all. `cards_for[i]` is
    (line, label) for moment piece i."""
    from . import cutter
    from .highlight import _in_dir
    from .tools import filter_script_flag, media_info, video_codec_args

    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent / f".{out.stem}.parts"
    work.mkdir(parents=True, exist_ok=True)
    try:
        files: dict[int, str] = {}
        foot = [i for i, p in enumerate(pieces) if not p.still]
        for k, i in enumerate(foot):
            if progress:
                progress(k, len(foot) + 1)
            p = pieces[i]
            f = work / f"p{i:02d}.mp4"
            cutter._cut(source, p.start, p.length, f, encoder=encoder, cq=18, keep_all_audio=False)
            p.end = p.start + float(media_info(f)["duration"])     # the encoded length, exactly
            files[i] = f.name
        # The cards.
        card_files: dict[int, str] = {}
        for i, p in enumerate(pieces):
            if p.kind == "intro":
                img = title_card(facts.head, facts.result, f"  ·  {facts.line}", facts.story_line)
            elif p.kind == "moment" and i in cards_for:
                line, label = cards_for[i]
                img = context_card(line, label, facts.won, facts.half, p.round)
            else:
                continue
            name = f"card{i:02d}.png"
            img.save(work / name)
            card_files[i] = name
        nxt = next((p for p in pieces if p.kind == "moment" and p.round and p.round > facts.half), None)
        last = next((p for p in reversed(pieces) if not p.still), None)
        for p in pieces:
            if p.kind == "half":
                a = sum(1 for w in facts.won[:facts.half] if w is True)
                b = sum(1 for w in facts.won[:facts.half] if w is False)
                full_card(_frame(source, (nxt.start if nxt else 0.0) + 1.0), "HALF-TIME", f"{a} - {b}",
                          OFF_WHITE, [], facts.won[:facts.half], facts.half).save(work / "half.png")
            elif p.kind == "result":
                full_card(_frame(source, (last.end if last else 0.0) - 1.0), facts.head, facts.result,
                          facts.win_col, [facts.line] + ([facts.story_line] if facts.story_line else []),
                          facts.won, facts.half).save(work / "result.png")
        args: list[str] = []
        inputs: dict[int, int] = {}
        n = 0
        for i, p in enumerate(pieces):
            if p.still:
                args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{p.length:.3f}", "-i", p.still]
            else:
                args += ["-i", files[i]]
            inputs[i] = n
            n += 1
        cards: dict[int, int] = {}
        for i, name in card_files.items():
            args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{pieces[i].length:.3f}", "-i", name]
            cards[i] = n
            n += 1
        (work / "graph.txt").write_text(graph(pieces, inputs, cards, facecam_box), encoding="utf-8")
        if progress:
            progress(len(foot), len(foot) + 1)
        tmp = out.with_suffix(".tmp.mp4")
        _in_dir(work, *args, filter_script_flag(), "graph.txt", "-map", "[vout]", "-map", "[aout]",
                *video_codec_args(encoder, cq=cq), "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", "-y", str(tmp.resolve()))
        os.replace(tmp, out)
        return out
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
