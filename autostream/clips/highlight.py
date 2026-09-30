"""Marvel Rivals match HIGHLIGHTS: the fights, cut together with a theme.

The summary (clips/summary.py) is the whole match with the dead time out. A
highlight is the other thing people upload: two to three minutes of only the
fights, each around your kills and ults, joined the way gaming editors join
them -- the same small set of moves every time, so it reads as a style:

  * a title over the opening seconds of the match;
  * a whip (a fast slide) between fights, with a whoosh on every cut, and a
    white flash into the result;
  * on every kill a hit sound and a two-frame flash; on an ult a bigger one;
  * music under the end -- it fades in under the last fight, the game ducks
    beneath it, and the picture fades out on the VICTORY/DEFEAT screen.

The sounds and the music are synthesised (clips/sfx.py): nothing here can draw
a copyright claim. Where OBS froze, the frozen footage is left out.

WHAT A "KILL" IS HERE
    Every KO the scoreboard counts, final hit or assist: the notice the game
    puts beside the crosshair (rivals.ko_notice) -- 26 of a match's 29 -- and
    the white rows in the kill feed (rivals.own_rows) as a second witness for
    final hits. The two are merged, so one KO seen by both is one hit sound.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import cutter, rivals, sfx
from .tools import FfmpegMissing, filter_script_flag, media_info, video_codec_args

log = logging.getLogger("autostream.clips.highlight")

T = 0.35              # transition length
PRE = 8.0             # a fight opens this long before its first kill
POST = 4.0            # ...and closes this long after its last
CLUSTER = 12.0        # kills closer than this are one fight
JOIN = 6.0            # fights closer than this are one shot
INTRO = 4.0
# The intro starts this far into the match: its first seconds are the team-up
# card, which the title would sit on top of.
INTRO_SKIP = 3.0
RESULT = 5.0
DEATH_TAIL = 2.5      # a fight that ends in your death keeps this much of it
MUSIC_LEAD = 7.0      # the music starts this long before the result
MUSIC_VOL = 0.55      # measured: -21 dB RMS against the game's -29, ducked to 0.3
FONTS = ("impact.ttf", "arialbd.ttf", "segoeuib.ttf")
# The channel's outro (clips.outro): joined with a white flash this long, its
# sound turned down to sit with the game -- a made-for-YouTube outro is
# mastered near 0 dB, measured 6 dB louder than a highlight's ending -- and
# faded out over its last moments.
OUTRO_JOIN = 0.5
OUTRO_VOL = 0.7
OUTRO_FADE = 0.7
# An outro's last frame is usually its point -- the channel name lands in the
# final second -- so it is held this long before the fade takes it away.
OUTRO_HOLD = 1.5


@dataclass
class Shot:
    start: float
    end: float
    kind: str          # intro | fight | result

    @property
    def seconds(self) -> float:
        return self.end - self.start


def kos(m: rivals.Match) -> list[float]:
    """Every KO this match, from the notice and the feed together."""
    return m.all_kos()


def plan(r: rivals.Readings, m: rivals.Match) -> list[Shot]:
    """The shots of the highlight, in order. Empty if there is nothing to show."""
    events = sorted(kos(m) + m.casts)
    fights: list[tuple[float, float]] = []
    if events:
        groups = [[events[0], events[0]]]
        for e in events[1:]:
            if e - groups[-1][1] <= CLUSTER:
                groups[-1][1] = e
            else:
                groups.append([e, e])
        for a, b in groups:
            s, e = a - PRE, b + POST
            for d0, d1 in m.deaths:
                if s < d1 <= a:                 # do not open on the spectator view
                    s = max(s, d1 + 1.0)
                if b <= d0 < e:                 # a death closes the fight
                    e = min(e, d0 + DEATH_TAIL)
            fights.append((max(s, m.start), min(e, m.end + rivals.END_KEEP)))
        # The last fight runs to the end of the match: that is the ending.
        if m.end - fights[-1][1] < 30:
            fights[-1] = (fights[-1][0], m.end + rivals.END_KEEP)
    else:
        # Nothing the feed credits to you: the summary's fights, unthemed cuts.
        fights = [s for s in rivals.plan(r, m) if s[0] < m.end]
    # Joined first, frozen footage out after: joining after would bridge the
    # frozen gaps straight back in.
    fights = rivals.tidy(rivals.subtract(rivals.tidy(fights, gap=JOIN), m.frozen), gap=0.0)

    shots = [Shot(a, b, "intro")
             for a, b in rivals.subtract([(m.start + INTRO_SKIP,
                                           m.start + INTRO_SKIP + INTRO)], m.frozen)
             if b - a >= 2.0][:1]
    for a, b in fights:
        if shots and a < shots[-1].end:
            a = shots[-1].end
        if b - a >= 2.5:
            shots.append(Shot(a, b, "fight"))
    if m.result:
        shots.append(Shot(m.result_at, m.result_at + RESULT, "result"))
    if not any(s.kind == "fight" for s in shots):
        return []
    return shots


def transitions(shots: list[Shot]) -> list[str]:
    """One per cut: a white flash in and out of the fights, whips between them."""
    out = []
    whip = 0
    for a, b in zip(shots, shots[1:]):
        if a.kind == "fight" and b.kind == "fight":
            out.append("smoothleft" if whip % 2 == 0 else "smoothright")
            whip += 1
        else:
            out.append("fadewhite")
    return out


def offsets(durations: list[float]) -> list[float]:
    """Where each shot starts in the finished video, given the overlaps."""
    offs = [0.0]
    for d in durations[:-1]:
        offs.append(offs[-1] + d - T)
    return offs


def at_output(shots: list[Shot], offs: list[float], src: float) -> float | None:
    for s, o in zip(shots, offs):
        if s.start <= src <= s.end:
            return o + src - s.start
    return None


def graph(shots: list[Shot], durations: list[float], kills: list[float],
          ults: list[float], *, title: bool,
          outro: float | None = None) -> tuple[str, float]:
    """The whole filter graph, as text. -> (graph, output seconds)

    Inputs: 0..n-1 the shots, then whoosh, hit, the music bed, and -- when
    `outro` is its length -- the channel's outro, already fitted to the shots'
    size, rate and sound (see _fit_outro). Outputs [vout] [aout].
    Kept free of ffmpeg so it can be checked without running it.
    """
    n = len(shots)
    offs = offsets(durations)
    total = offs[-1] + durations[-1]
    trans = transitions(shots)
    kill_out = [x for x in (at_output(shots, offs, k) for k in kills) if x is not None]
    ult_out = [x for x in (at_output(shots, offs, k) for k in ults) if x is not None]
    fc = []

    last = "0:v"
    for i in range(1, n):
        fc.append(f"[{last}][{i}:v]xfade=transition={trans[i - 1]}:duration={T}"
                  f":offset={offs[i]:.3f}[v{i}]")
        last = f"v{i}"
    fx = [f"eq=brightness=0.28:saturation=1.3:enable='between(t,{k:.3f},{k + 0.08:.3f})'"
          for k in kill_out]
    fx += [f"eq=brightness=0.45:enable='between(t,{k:.3f},{k + 0.12:.3f})'" for k in ult_out]
    if title:
        fade = "if(lt(t,0.25),t/0.25,if(lt(t,2.4),1,max(0,(2.8-t)/0.4)))"
        fx.append("drawtext=fontfile=title.ttf:textfile=title1.txt:fontsize=h*0.1:"
                  "fontcolor=white:borderw=6:bordercolor=black@0.8:x=(w-text_w)/2:"
                  f"y=h*0.36:alpha='{fade}':enable='lt(t,2.8)'")
        fx.append("drawtext=fontfile=title.ttf:textfile=title2.txt:fontsize=h*0.05:"
                  "fontcolor=0xFFD23C:borderw=4:bordercolor=black@0.8:x=(w-text_w)/2:"
                  f"y=h*0.36+h*0.115:alpha='{fade}':enable='lt(t,2.8)'")
    fx.append("format=yuv420p")
    if outro:
        # A white flash from the result screen into the outro, which then
        # fades out on its own last frame.
        oi = n + 3
        fc.append(f"[{last}]{','.join(fx)}[hv]")
        end = total + outro - OUTRO_JOIN
        fc.append(f"[hv][{oi}:v]xfade=transition=fadewhite:duration={OUTRO_JOIN}"
                  f":offset={total - OUTRO_JOIN:.3f},"
                  f"fade=t=out:st={max(0.0, end - OUTRO_FADE):.3f}:d={OUTRO_FADE}[vout]")
    else:
        fx.insert(len(fx) - 1, f"fade=t=out:st={max(0.0, total - 1.5):.3f}:d=1.5")
        fc.append(f"[{last}]{','.join(fx)}[vout]")

    last = "0:a"
    for i in range(1, n):
        fc.append(f"[{last}][{i}:a]acrossfade=d={T}:c1=tri:c2=tri[a{i}]")
        last = f"a{i}"
    wi, hi, mi = n, n + 1, n + 2
    mix = [f"[{last}]"]
    cuts = [offs[i] + T / 2 for i in range(1, n)]
    if cuts:
        fc.append(f"[{wi}:a]asplit={len(cuts)}" + "".join(f"[w{i}]" for i in range(len(cuts))))
        for i, c in enumerate(cuts):
            ms = max(0, int((c - sfx.WHOOSH_PEAK) * 1000))
            fc.append(f"[w{i}]volume=0.55,adelay={ms}|{ms}[wd{i}]")
            mix.append(f"[wd{i}]")
    hits = [(k, 0.7) for k in kill_out] + [(k, 0.9) for k in ult_out]
    if hits:
        fc.append(f"[{hi}:a]asplit={len(hits)}" + "".join(f"[h{i}]" for i in range(len(hits))))
        for i, (k, vol) in enumerate(hits):
            ms = max(0, int((k - 0.01) * 1000))
            fc.append(f"[h{i}]volume={vol},adelay={ms}|{ms}[hd{i}]")
            mix.append(f"[hd{i}]")
    fc.append("".join(mix) + f"amix=inputs={len(mix)}:normalize=0:duration=first[gm]")

    # The music comes in under the last fight, so it starts before the result.
    end_at = offs[-1] if shots[-1].kind == "result" else total - 6.0
    at = max(0.0, end_at - MUSIC_LEAD)
    mlen = total - at
    fc.append(f"[gm]volume='if(lt(t,{at:.3f}),1,max(0.3,1-(t-{at:.3f})/3*0.7))':eval=frame[gd]")
    fc.append(f"[{mi}:a]atrim=0:{mlen:.3f},afade=t=in:d=3,"
              f"afade=t=out:st={max(0.0, mlen - 2.5):.3f}:d=2.5,volume={MUSIC_VOL},"
              f"adelay={int(at * 1000)}|{int(at * 1000)}[md]")
    if outro:
        # The music is already fading as the result ends; the outro's own
        # sound crossfades in under the flash.
        oi = n + 3
        end = total + outro - OUTRO_JOIN
        fc.append("[gd][md]amix=inputs=2:normalize=0:duration=first[hm]")
        fc.append(f"[{oi}:a]volume={OUTRO_VOL}[oa]")
        fc.append(f"[hm][oa]acrossfade=d={OUTRO_JOIN}:c1=tri:c2=tri,"
                  f"afade=t=out:st={max(0.0, end - OUTRO_FADE):.3f}:d={OUTRO_FADE},"
                  "alimiter=limit=0.95[aout]")
        return ";\n".join(fc), end
    fc.append(f"[gd][md]amix=inputs=2:normalize=0:duration=first,"
              f"afade=t=out:st={max(0.0, total - 1.5):.3f}:d=1.5,alimiter=limit=0.95[aout]")
    return ";\n".join(fc), total


def _font(work: Path) -> bool:
    """Copy a bold system font next to the graph, which then names it without
    a path -- a Windows drive colon inside a filter graph needs escaping that
    differs between ffmpeg builds, and a missing fontconfig crashes drawtext."""
    import os
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in FONTS:
        if (fonts / name).is_file():
            shutil.copyfile(fonts / name, work / "title.ttf")
            return True
    return False


def _fit_outro(src: Path, like: Path, out: Path, encoder: str = "auto") -> float | None:
    """The outro re-encoded to the highlight's own size, frame rate and sound.

    xfade and acrossfade need both sides identical, and an outro is whatever
    the person made -- 24 fps against a 60 fps recording, another size, often
    no sound at all (silence is laid in). -> its length, or None if it cannot
    be used, in which case the highlight simply ends without it.
    """
    try:
        info = media_info(like)
        w, h = int(info["width"]), int(info["height"])
        fps = float(info.get("fps") or 60) or 60.0
        has_audio = int(media_info(src).get("audio_tracks") or 0) > 0
    except Exception as e:                              # noqa: BLE001
        log.warning("outro %s could not be read: %s", src, e)
        return None
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:g},"
          f"tpad=stop_mode=clone:stop_duration={OUTRO_HOLD},format=yuv420p")
    if has_audio:
        ins = ["-i", str(Path(src).resolve())]
        maps = ["-map", "0:v:0", "-map", "0:a:0", "-af", f"apad=pad_dur={OUTRO_HOLD}"]
    else:
        ins = ["-i", str(Path(src).resolve()),
               "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        maps = ["-map", "0:v:0", "-map", "1:a", "-shortest"]
    try:
        _in_dir(out.parent, *ins, *maps, "-vf", vf,
                "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "256k",
                *video_codec_args(encoder, cq=18), "-y", out.name)
        return float(media_info(out)["duration"])
    except Exception as e:                              # noqa: BLE001
        log.warning("outro %s could not be fitted: %s", src, e)
        return None


def render(source: Path, shots: list[Shot], m: rivals.Match, out: Path, *,
           title: str, subtitle: str, encoder: str = "auto",
           outro: str | Path | None = None,
           check: Callable[[], None] | None = None) -> Path:
    """Cut the shots and join them into the finished highlight at `out`."""
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent / f".{out.stem}.parts"
    work.mkdir(parents=True, exist_ok=True)
    try:
        sounds = sfx.files(work)
        parts = []
        for i, s in enumerate(shots):
            if check:
                check()
            # The mix track only: this is a finished export, and the mix is
            # the one with the player's voice in it.
            parts.append(cutter._cut(source, s.start, s.seconds, work / f"s{i:02d}.mp4",
                                     encoder=encoder, cq=18, keep_all_audio=False))
        durs = [float(media_info(p)["duration"]) for p in parts]
        have_font = _font(work)
        (work / "title1.txt").write_text(title, encoding="utf-8")
        (work / "title2.txt").write_text(subtitle, encoding="utf-8")
        outro_len = None
        if outro and Path(outro).is_file():
            outro_len = _fit_outro(Path(outro), parts[0], work / "outro_fit.mp4", encoder)
        elif outro:
            log.warning("the outro %s is not there any more; ending without it", outro)
        text, total = graph(shots, durs, kos(m), m.casts, title=have_font,
                            outro=outro_len)
        (work / "graph.txt").write_text(text, encoding="utf-8")
        args = []
        for p in parts:
            args += ["-i", p.name]
        for k in ("whoosh", "hit", "outro"):
            args += ["-i", sounds[k].name]
        if outro_len:
            args += ["-i", "outro_fit.mp4"]
        tmp = out.with_suffix(".tmp.mp4")
        _in_dir(work, *args, filter_script_flag(), "graph.txt",
                "-map", "[vout]", "-map", "[aout]",
                *video_codec_args(encoder, cq=19),
                "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart",
                "-y", str(tmp.resolve()))
        tmp.replace(out)
        log.info("highlight: %d shots, %d KOs, %d ults -> %s (%.0fs)",
                 len(shots), len(kos(m)), len(m.casts), out.name, total)
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _in_dir(folder: Path, *args: str) -> None:
    """ffmpeg with the working directory set, so the graph's files resolve."""
    import subprocess

    from .tools import _NO_WINDOW, binary

    try:
        exe = binary("ffmpeg")
    except FfmpegMissing:
        raise
    p = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-nostdin", *args],
                       cwd=str(folder), capture_output=True, text=True,
                       creationflags=_NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed making the highlight: {p.stderr.strip()[-600:]}")


def subtitle_for(m: rivals.Match) -> str:
    what = m.result.upper() if m.result else "MATCH"
    k = len(kos(m))
    return f"{what}  -  {k} KO{'' if k == 1 else 's'}" if k else what
