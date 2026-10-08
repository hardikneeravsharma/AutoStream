"""Score how the CS2 card reader picks the HUD colour, against recordings whose
colour is known.

WHY THIS EXISTS. The colour is decided from a few dozen single frames spread
across the recording, BEFORE the scan -- and when it is wrong, everything
after it is wrong with no error anywhere. An outside user's 54-minute match
came back as hue 202 (blue) for a pink HUD on three tally readings, and the
run reported "No kills found". Whether a picking rule is safe is a question
about how often it lands on the right colour across many draws of samples,
which no single scan can answer.

So this cuts the card area out of a cs2_tally_dump.py dump ONCE, at 1 fps,
into crops.npy -- then replays `measure_hue`'s sampling (evenly spaced, at
every phase offset) through `pick_hue` exactly as shipped, in seconds.

    .venv\\Scripts\\python.exe scripts\\cs2_hue_score.py DUMP_DIR --truth 332
        [--samples 60] [--draws 40] [--tol 25]

`--truth` is the HUD colour a person confirmed for that recording. A pick is
RIGHT within `--tol` degrees of it, WRONG outside, NONE when nothing read.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autostream.clips import cs2_cards  # noqa: E402
from autostream.clips.tools import binary  # noqa: E402

CROP_FPS = 1.0


def crops(dump: Path) -> np.ndarray:
    """The dump's view at 1 fps, cached in crops.npy. (n, h, w, 3) uint8."""
    out = dump / "crops.npy"
    meta = json.loads((dump / "meta.json").read_text())
    c = meta["cards"]
    if out.is_file():
        return np.load(out, mmap_mode="r")
    t0 = time.time()
    proc = subprocess.Popen(
        [binary("ffmpeg"), "-v", "error", "-nostdin", "-i",
         str(dump / c["file"]), "-vf", f"fps={CROP_FPS}", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    fb = c["w"] * c["h"] * 3
    frames = []
    while True:
        b = proc.stdout.read(fb)
        if len(b) < fb:
            break
        frames.append(np.frombuffer(b, np.uint8).reshape(c["h"], c["w"], 3))
    proc.wait()
    arr = np.stack(frames)
    np.save(out, arr)
    print(f"cut {len(arr)} crops in {time.time() - t0:.0f}s", file=sys.stderr)
    return arr


def strip_of(crop: np.ndarray, meta: dict) -> np.ndarray:
    """A crop pasted into a HUD_STRIP-shaped frame where it came from, so
    `pick_hue` runs unmodified -- it cuts the card area back out itself."""
    W, H, c = meta["width"], meta["height"], meta["cards"]
    sy0 = int(H * cs2_cards.HUD_STRIP[1])
    strip = np.zeros((H - sy0, W, 3), np.uint8)
    top = c["y"] - sy0                     # the crop's top row, in the strip
    r0 = max(0, -top)
    rows = crop[r0:, :]
    y = top + r0
    rows = rows[:max(0, strip.shape[0] - y)]
    strip[y:y + len(rows), c["x"]:c["x"] + c["w"]] = rows
    return strip


def draws(n_total: int, samples: int, k: int) -> list[list[int]]:
    """`measure_hue`'s even spacing, at k different phase offsets."""
    step = max(1.0, (n_total - 1.0) / (samples + 1))
    out = []
    for j in range(k):
        off = step * j / k
        out.append(sorted({min(n_total - 1, int(step * i + off))
                           for i in range(1, samples + 1)}))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", type=Path)
    ap.add_argument("--truth", type=float, required=True)
    ap.add_argument("--samples", type=int, default=cs2_cards.HUE_SAMPLES)
    ap.add_argument("--draws", type=int, default=40)
    ap.add_argument("--tol", type=float, default=15.0)
    ap.add_argument("--start", type=float, default=0.0,
                    help="seconds of the dump to skip (another game first)")
    a = ap.parse_args()

    meta = json.loads((a.dump / "meta.json").read_text())
    arr = crops(a.dump)
    lo = int(a.start * CROP_FPS)
    arr = arr[lo:]
    h = meta["height"]
    right = wrong = none = 0
    picks, used = [], []
    t0 = time.time()
    gap = max(1, int(round(cs2_cards.PAIR_GAP * CROP_FPS)))
    ladder = sorted({a.samples, *cs2_cards.HUE_SAMPLES_MORE})
    for j in range(a.draws):
        got = None
        # measure_hue's escalation, at this phase offset: stop at the first
        # sample count that gives a clear answer
        for n in ladder:
            idx = draws(len(arr), n, a.draws)[j]
            # pairs PAIR_GAP apart, as strip_samples takes them -- the crops
            # are at 1 fps, so the second look is the next crop
            frames = [(strip_of(arr[i], meta), strip_of(arr[i + gap], meta))
                      for i in idx if i + gap < len(arr)]
            got, _ = cs2_cards.pick_hue(frames, frame_height=h)
            if got is not None:
                used.append(n)
                break
        picks.append(got)
        if got is None:
            none += 1
        elif abs((got - a.truth + 180) % 360 - 180) <= a.tol:
            right += 1
        else:
            wrong += 1
    n = len(picks)
    from collections import Counter
    print(f"{a.dump.name}: {n} draws, truth {a.truth:.0f} +-{a.tol:.0f}"
          f" -> RIGHT {right}  WRONG {wrong}  NONE {none}"
          f"   samples used {dict(sorted(Counter(used).items()))}"
          f"   ({time.time() - t0:.0f}s)")
    ok = [p for p in picks if p is not None]
    if ok:
        print(f"  picks: min {min(ok):.0f}  median {float(np.median(ok)):.0f}"
              f"  max {max(ok):.0f}")
    bad = sorted({round(p) for p in picks if p is not None
                  and abs((p - a.truth + 180) % 360 - 180) > a.tol})
    if bad:
        print("  wrong picks:", bad)
    return 0


if __name__ == "__main__":
    sys.exit(main())
