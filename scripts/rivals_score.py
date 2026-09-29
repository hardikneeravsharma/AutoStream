"""Score the Marvel Rivals summary planner against hand labels.

Marvel Rivals writes nothing readable afterwards, so ground truth is a person
(CLAUDE.md): watch a match and write down, in recording seconds, where the
fighting was, where you were dead, and where nothing happened -- the setup in
spawn and the walks back. A labels file is

    {"fight": [[586, 596], [630, 656]], "dead": [[596, 606]],
     "quiet": [[530, 584], [606, 628]]}

and the score is how much of each the summary KEEPS. Fighting has to stay near
100%; quiet and dead time as low as it goes (a death keeps its first 3 s, so
dead time does not reach zero on purpose).

    1. The shipped reader (rivals.scan) runs once over the recording and its
       readings are cached in readings.npz beside --out; pass --rescan after
       changing what it measures. 38 minutes of 1080p60 reads in about 2.
    2. The shipped planner runs over the readings, printing every match, its
       deaths, ults, phases, result and the spans kept.
    3. With --labels, the kept fraction of each label.
    4. With --sheet, a PNG of frames from inside every cut that is not a death,
       to check by eye that nothing cut was a fight.

    .venv\\Scripts\\python.exe scripts\\rivals_score.py RECORDING --out DIR
        [--labels FILE] [--sheet] [--rescan]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autostream.clips import highlight, rivals                # noqa: E402
from autostream.clips.tools import binary                     # noqa: E402


def kept_fraction(spans, intervals) -> float:
    tot = inside = 0
    for a, b in intervals:
        for x in np.arange(a, b, 0.5):
            tot += 1
            inside += any(p <= x < q for p, q in spans)
    return inside / tot if tot else float("nan")


def sheet(video: Path, r: rivals.Readings, out: Path) -> None:
    rows = []
    for i, m in enumerate(rivals.matches(r), 1):
        spans = rivals.plan(r, m)
        for (_a0, b0), (a1, _b1) in zip(spans, spans[1:]):
            lo = b0
            for d0, d1 in m.deaths:
                if d0 - 1 <= b0 <= d0 + rivals.DEATH_KEEP + 1:
                    lo = max(lo, d1)
            if a1 - lo >= 2:
                rows.append((i, lo, a1))
    if not rows:
        print("no cuts outside deaths")
        return

    def grab(t):
        return subprocess.run(
            [binary("ffmpeg"), "-loglevel", "error", "-ss", f"{t:.2f}", "-i",
             str(video), "-frames:v", "1", "-vf", "scale=240:135",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True).stdout
    times = [t for _i, lo, hi in rows for t in np.linspace(lo, hi, 7)[:6]]
    with ThreadPoolExecutor(8) as ex:
        raw = list(ex.map(grab, times))
    blank = np.zeros((135, 240, 3), np.uint8)
    tiles = [np.frombuffer(b, np.uint8).reshape(135, 240, 3)
             if len(b) == 135 * 240 * 3 else blank for b in raw]
    lines = []
    for k, (i, lo, hi) in enumerate(rows):
        row = np.concatenate(tiles[k * 6:(k + 1) * 6], 1).copy()
        row[:2] = 255
        lines.append(row)
        print(f"  sheet row {k}: match {i}, cut {lo:.0f}-{hi:.0f} ({hi - lo:.0f}s)")
    cv = np.concatenate(lines, 0)
    subprocess.run([binary("ffmpeg"), "-loglevel", "error", "-y", "-f", "rawvideo",
                    "-pix_fmt", "rgb24", "-s", f"{cv.shape[1]}x{cv.shape[0]}",
                    "-i", "-", str(out)], input=cv.tobytes())
    print(f"sheet: {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("recording")
    ap.add_argument("--out", required=True)
    ap.add_argument("--labels")
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--rescan", action="store_true")
    a = ap.parse_args()
    video, out = Path(a.recording), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "readings.npz"
    if a.rescan or not cache.is_file():
        r = rivals.scan(video, progress=lambda d, n: print(f"\r  {d}/{n}", end="", flush=True))
        print()
        r.save(cache)
    r = rivals.Readings.load(cache)
    print(f"hud found: {rivals.hud_found(r)}   ult readable "
          f"{(r.ult >= 0).mean():.0%} of samples")
    every = []
    for i, m in enumerate(rivals.matches(r), 1):
        spans = rivals.plan(r, m)
        every += spans
        kept = sum(b - a for a, b in spans)
        print(f"match {i}: {m.start:.0f}-{m.end:.0f} ({m.seconds / 60:.1f} min) -> "
              f"{kept / 60:.1f} min in {len(spans)} pieces, {len(m.deaths)} deaths, "
              f"{len(m.casts)} ults, {m.result or 'no result'}")
        print("   deaths", [(round(x), round(y)) for x, y in m.deaths])
        print("   ults  ", [round(c) for c in m.casts],
              " phases", [round(p) for p in m.phases])
        print("   kept  ", [(round(x), round(y)) for x, y in spans])
        # Check these against the scoreboard: K is every KO, Final Hits the feed.
        print(f"   KOs {len(m.kos)} (notice), final hits {len(m.kills)} (feed), "
              f"frozen {[(round(x), round(y)) for x, y in m.frozen]}")
        shots = highlight.plan(r, m)
        print("   highlight", [(round(s.start), round(s.end), s.kind) for s in shots])
    if a.labels:
        labels = json.loads(Path(a.labels).read_text(encoding="utf-8"))
        for k, iv in labels.items():
            print(f"  {k:6s} kept {kept_fraction(every, iv):6.1%}")
    if a.sheet:
        sheet(video, r, out / "cuts.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
