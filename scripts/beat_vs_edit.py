r"""Score the beat finder against edits a person made by hand.

    python scripts\beat_vs_edit.py --out runs\beatcheck  URL_OR_FILE:valorant  URL_OR_FILE:cs2 ...

For each edit: run the app's own beat finder over the edit's OWN audio, find
where the editor actually cut and where the kills actually land, and measure
how far each cut and kill sits from the nearest beat the app would have used.
Writes one JSON per edit plus `summary.json`; `--html` also writes a report.

WHY THE EDIT'S OWN AUDIO
    The question is whether the grid the app computes is the grid an editor
    hears. Scoring it against the song's studio file would also be measuring
    the editor's choice of where in the song to start, which is a different
    question. Game sound mixed under the music is part of what the app would
    face too.

WHAT IS COMPARED
    beats   beatsync.analyse -- the snapped grid _flat_layout cuts on
    grid    reel.analyse     -- the rigid grid reels lay templates on
    hits    hits.song_hits   -- the bass hits reels put kills on
    Each against: cuts (frame difference), flashes (separately -- a white
    flash is an effect, not a cut), and kills.

THE CHANCE LINE, WHICH IS THE POINT
    "40% of cuts within 50 ms of a beat" means nothing until it is set against
    what random cuts would score on the same grid: 2 x 50 ms / beat period, or
    about 21% at 128 BPM. Every hit rate here is printed beside its chance
    rate; a number is only evidence when it clears it.

KILLS
    Valorant: killmark's ring reader -- the game's own kill emblem, no setup.
    It reads a 16:9 frame at the emblem's fixed place, so a vertical crop or a
    zoomed edit simply reports none, and the report says "not readable" rather
    than "no kills".
    CS2: there is no reader that needs nothing; cs2_cards needs a measured HUD
    hue and the kill feed needs a name. What this uses instead is the onset of
    a red-bordered row in the feed corner -- CS2 outlines YOUR kills in red.
    It is a heuristic and is labelled as one in every output.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autostream.clips import beatsync as bs          # noqa: E402
from autostream.clips import hits as hits_mod        # noqa: E402
from autostream.clips import killmark                # noqa: E402
from autostream.clips import reel                    # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

FPS = 30
TOLS = (0.05, 0.10)          # seconds either side of a beat that count as "on" it

# CUTS. A cut is a frame whose difference from the last one is both large in
# absolute terms and large against the second around it -- the second clause is
# what stops a fast flick in a gunfight from reading as a cut.
CUT_ABS = 18.0               # mean abs luma difference, 0-255, on a 64x36 frame
CUT_REL = 3.0                # times the local median difference
CUT_GAP = 4                  # frames; closer than this is one cut
# FLASHES. A frame far brighter than the one before, back down within a few
# frames. Editors put these on beats, so they are scored, but apart.
FLASH_RISE = 45.0
FLASH_BACK = 8

# CS2 feed corner, as fractions of a 16:9 frame.
CS2_FEED = (0.72, 1.0, 0.04, 0.32)
CS2_RED_SHARE = 0.004        # share of the corner that must turn red
CS2_HOLD = 0.4


def ff(args: list[str]) -> bytes:
    return subprocess.run(["ffmpeg", "-v", "error", *args], capture_output=True,
                          check=True, creationflags=NO_WINDOW).stdout


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True,
                         creationflags=NO_WINDOW).stdout
    d = json.loads(out)
    s = d["streams"][0]
    return {"w": int(s["width"]), "h": int(s["height"]),
            "dur": float(d["format"]["duration"])}


def fetch(src: str, folder: Path) -> Path:
    """A local file as given, or a URL fetched with yt-dlp at 720p or less."""
    p = Path(src)
    if p.exists():
        return p
    folder.mkdir(parents=True, exist_ok=True)
    tmpl = str(folder / "%(id)s.%(ext)s")
    subprocess.run(["yt-dlp", "--no-playlist", "-f",
                    "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]/b",
                    "--merge-output-format", "mp4", "-o", tmpl, src],
                   check=True, creationflags=NO_WINDOW)
    vid = subprocess.run(["yt-dlp", "--no-playlist", "--print", "id", src],
                         capture_output=True, text=True, check=True,
                         creationflags=NO_WINDOW).stdout.strip()
    return folder / f"{vid}.mp4"


# ------------------------------------------------------------------ the video

def small_frames(path: Path) -> np.ndarray:
    raw = ff(["-i", str(path), "-vf", f"fps={FPS},scale=64:36,format=gray",
              "-f", "rawvideo", "-"])
    n = len(raw) // (64 * 36)
    return np.frombuffer(raw, np.uint8)[:n * 64 * 36].reshape(n, 36, 64).astype(np.float32)


def cuts_and_flashes(frames: np.ndarray) -> tuple[list[float], list[float]]:
    if len(frames) < 3:
        return [], []
    d = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))        # d[i]: frame i -> i+1
    lum = frames.mean(axis=(1, 2))
    k = FPS
    pad = np.pad(d, k // 2, mode="edge")
    med = np.array([np.median(pad[i:i + k]) for i in range(len(d))])

    flash_frames: set[int] = set()
    flashes: list[float] = []
    for i in range(1, len(lum)):
        if lum[i] - lum[i - 1] >= FLASH_RISE:
            back = lum[i + 1:i + 1 + FLASH_BACK]
            if back.size and (back <= lum[i - 1] + FLASH_RISE * 0.6).any():
                flashes.append(round(i / FPS, 3))
                end = i + 1 + int(np.argmax(back <= lum[i - 1] + FLASH_RISE * 0.6))
                flash_frames.update(range(i - 1, end + 1))

    cuts: list[float] = []
    last = -CUT_GAP
    for i in range(len(d)):
        if i in flash_frames or i + 1 in flash_frames:
            continue
        if d[i] < CUT_ABS or d[i] < CUT_REL * max(med[i], 1.0):
            continue
        if i > 0 and d[i - 1] > d[i] or i + 1 < len(d) and d[i + 1] > d[i]:
            continue
        if i - last < CUT_GAP:
            continue
        cuts.append(round((i + 1) / FPS, 3))                     # the first new frame
        last = i
    return cuts, flashes


def cs2_feed_onsets(path: Path) -> list[float]:
    x0, x1, y0, y1 = CS2_FEED
    raw = ff(["-i", str(path), "-vf",
              f"fps={FPS},crop=iw*{x1 - x0:.3f}:ih*{y1 - y0:.3f}:iw*{x0:.3f}:ih*{y0:.3f},"
              "scale=160:90,format=rgb24", "-f", "rawvideo", "-"])
    n = len(raw) // (160 * 90 * 3)
    a = np.frombuffer(raw, np.uint8)[:n * 160 * 90 * 3].reshape(n, 90, 160, 3).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = ((r > 170) & (r - g > 90) & (r - b > 90)).mean(axis=(1, 2))
    hold = int(CS2_HOLD * FPS)
    out: list[float] = []
    i = 1
    while i < n - hold:
        if red[i] >= CS2_RED_SHARE and red[i - 1] < CS2_RED_SHARE * 0.5 \
                and (red[i:i + hold] >= CS2_RED_SHARE * 0.6).all():
            out.append(round(i / FPS, 3))
            i += hold
        else:
            i += 1
    return out


def kills_for(path: Path, game: str, info: dict) -> tuple[list[float] | None, str]:
    aspect = info["w"] / max(1, info["h"])
    if abs(aspect - 16 / 9) > 0.08:
        return None, f"not readable: {info['w']}x{info['h']} is not a 16:9 frame"
    if game == "valorant":
        got = killmark.marks(path, "valorant")
        return got, "killmark ring emblem"
    if game == "cs2":
        return cs2_feed_onsets(path), "heuristic: red-bordered feed row onset"
    return None, "no reader for this game"


# ------------------------------------------------------------------ the music

def music(path: Path, folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    wav = folder / f"{path.stem}.wav"
    ff(["-y", "-i", str(path), "-vn", "-ac", "1", "-ar", str(bs.SR), str(wav)])
    track = bs.analyse(wav)
    shape = reel.analyse(wav)
    return {"bpm": track.bpm, "beats": track.beats, "drop": track.drop,
            "drops": track.drops, "grid": shape.beats, "hits": shape.hits,
            "big": shape.big}


# ------------------------------------------------------------------ scoring

def offsets(events: list[float], marks: list[float]) -> list[float]:
    """Signed distance from each event to its nearest mark: + means the event is late."""
    if not marks:
        return []
    m = np.asarray(marks)
    return [round(float(e - m[np.argmin(np.abs(m - e))]), 4) for e in events]


def chance(marks: list[float], tol: float, span: tuple[float, float]) -> float:
    """Share of uniformly random times within `tol` of a mark, over `span`."""
    a, b = span
    if b <= a or not marks:
        return 0.0
    t = np.linspace(a, b, 20000)
    m = np.asarray(marks)
    near = np.abs(t[:, None] - m[None, :]).min(axis=1) <= tol if len(m) < 2000 else None
    return float(near.mean()) if near is not None else 0.0


def score(events: list[float], marks: list[float], span) -> dict:
    off = offsets(events, marks)
    out = {"n": len(events), "offsets": off}
    if not off:
        return out
    a = np.abs(off)
    out["median_abs_ms"] = round(float(np.median(a)) * 1000, 1)
    out["median_signed_ms"] = round(float(np.median(off)) * 1000, 1)
    for tol in TOLS:
        ms = int(tol * 1000)
        out[f"within_{ms}"] = round(float((a <= tol).mean()), 3)
        out[f"chance_{ms}"] = round(chance(marks, tol, span), 3)
    return out


def halves(beats: list[float]) -> list[float]:
    if len(beats) < 2:
        return list(beats)
    mids = [(a + b) / 2 for a, b in zip(beats, beats[1:])]
    return sorted(beats + mids)


def analyse(src: str, game: str, folder: Path) -> dict:
    path = fetch(src, folder / "media")
    info = probe(path)
    m = music(path, folder / "media")
    cuts, flashes = cuts_and_flashes(small_frames(path))
    kills, kill_source = kills_for(path, game, info)
    span = (min(m["beats"][:1] or [0.0]), max(m["beats"][-1:] or [info["dur"]]))
    in_span = lambda ev: [e for e in ev if span[0] - 0.2 <= e <= span[1] + 0.2]  # noqa: E731
    cuts_s, flashes_s = in_span(cuts), in_span(flashes)
    res = {
        "source": src, "file": path.name, "game": game, **info,
        "bpm": round(m["bpm"], 2), "beat_period": round(60 / m["bpm"], 4) if m["bpm"] else None,
        "drop": m["drop"], "drops": m["drops"],
        "beats": [round(b, 3) for b in m["beats"]], "grid": [round(b, 3) for b in m["grid"]],
        "hits": [round(h, 3) for h in m["hits"]],
        "cuts": cuts, "flashes": flashes, "kills": kills, "kill_source": kill_source,
        "cuts_vs": {"beats": score(cuts_s, m["beats"], span),
                    "halfbeats": score(cuts_s, halves(m["beats"]), span),
                    "grid": score(cuts_s, m["grid"], span),
                    "hits": score(cuts_s, m["hits"], span)},
        "flashes_vs": {"beats": score(flashes_s, m["beats"], span)},
    }
    if kills:
        ks = in_span(kills)
        res["kills_vs"] = {"beats": score(ks, m["beats"], span),
                           "hits": score(ks, m["hits"], span),
                           "cuts": score(ks, cuts, (0.0, info["dur"]))}
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("items", nargs="+", help="URL_OR_FILE:game  (game: valorant | cs2)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    every = []
    for item in args.items:
        src, _, game = item.rpartition(":")
        if game not in ("valorant", "cs2"):
            src, game = item, "valorant"
        try:
            res = analyse(src, game, args.out)
        except (subprocess.CalledProcessError, RuntimeError, OSError) as e:
            print(f"[skip] {src}: {e}")
            every.append({"source": src, "game": game, "error": str(e)})
            continue
        (args.out / f"{Path(res['file']).stem}.json").write_text(json.dumps(res, indent=1))
        cv = res["cuts_vs"]["beats"]
        print(f"[ok] {res['file']}: {res['bpm']} BPM, {len(res['cuts'])} cuts "
              f"({cv.get('within_50', 0):.0%} within 50 ms of a beat, chance "
              f"{cv.get('chance_50', 0):.0%}), kills: "
              f"{len(res['kills']) if res['kills'] is not None else res['kill_source']}")
        every.append(res)
    (args.out / "summary.json").write_text(json.dumps(every, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
