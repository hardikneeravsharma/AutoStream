"""Per-frame features of the card tally, at 60 fps, out of a cs2_tally_dump.py dump.

The shipped reader keeps one number per frame -- the tally's width -- and
throws the rest away. Scoring against a demo needs the rest: a kill is not
only a wider fan, it is a FLASH, and the flash is several things at once,
each of which can be seen when the others are hidden --

    beam    a pink column shooting up out of the top card
    emblem  the rank emblem under the cards turning white
    glow    a pink line running out sideways at emblem height

So this records all of them, once, into features.npz. Everything after it
(scoring, tuning) reads that file and never decodes video.

    .venv\\Scripts\\python.exe scripts\\cs2_tally_features.py DUMP_DIR
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autostream.clips import cs2_cards  # noqa: E402
from autostream.clips.tools import binary  # noqa: E402

BATCH = 120


def regions(meta: dict) -> dict[str, tuple[slice, slice]]:
    """Named regions, as (rows, cols) slices of the cards crop."""
    c, W, H = meta["cards"], meta["width"], meta["height"]

    def band(x1, y1, x2, y2):
        ax, ay = int(W * x1) - c["x"], int(H * y1) - c["y"]
        return (slice(max(0, ay), ay + int(H * (y2 - y1))),
                slice(max(0, ax), ax + int(W * (x2 - x1))))

    def px(x1, y1, x2, y2):          # absolute 1080p pixels, scaled
        k = H / 1080
        return band(x1 * k / W, y1 * k / H, x2 * k / W, y2 * k / H)

    cards = band(*cs2_cards.CARDS)
    return {
        "cards": cards,
        "panel": band(*cs2_cards.PANEL),
        # the column above the cards, where the beam rises
        "beam": (slice(0, cards[0].start), cards[1]),
        # the rank emblem, centred under the fan
        "emblem": px(935, 1003, 985, 1053),
        # the sideways glow, clear of the emblem on both sides
        "glow_l": px(760, 1018, 925, 1040),
        "glow_r": px(995, 1018, 1105, 1040),
    }


def hsv(a: np.ndarray):
    x = a.astype(np.float32) * (1 / 255.0)
    mx, mn = x.max(axis=-1), x.min(axis=-1)
    d = np.where(mx - mn == 0, 1, mx - mn)
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    h = np.where(mx == r, ((g - b) / d) % 6,
                 np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60.0
    return h, mx - mn, mx


def hud(h, s, v, hue):
    dh = np.abs((h - hue + 180.0) % 360.0 - 180.0)
    return (dh <= cs2_cards.HUE_TOL) & (s >= cs2_cards.SAT_MIN) & (v >= cs2_cards.VAL_MIN)


def main() -> int:
    dump = Path(sys.argv[1])
    meta = json.loads((dump / "meta.json").read_text())
    c, hue, fps = meta["cards"], meta["hue"], meta["cards"]["fps"]
    R = regions(meta)
    k = meta["height"] / 1080
    min_col = max(2, int(cs2_cards.MIN_COL * k))

    out = {n: [] for n in ("n_cards", "w_cards", "c0", "c1", "n_beam",
                           "white_beam", "emb_v", "emb_white", "emb_hud",
                           "glow", "dx", "mean_v")}
    size = c["w"] * c["h"] * 3
    p = subprocess.Popen([
        binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
        "-threads", "4", "-i", str(dump / c["file"]),
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE, bufsize=size * BATCH)
    t0, done = time.time(), 0
    while True:
        buf = p.stdout.read(size * BATCH)
        n = len(buf) // size
        if not n:
            break
        f = np.frombuffer(buf[:n * size], np.uint8).reshape(n, c["h"], c["w"], 3)
        h, s, v = hsv(f)
        m = hud(h, s, v, hue)
        white = (v >= 0.85) & (s <= 0.25)

        ry, rx = R["cards"]
        mc = m[:, ry, rx]
        out["n_cards"].append(mc.sum(axis=(1, 2)))
        colok = mc.sum(axis=1) >= min_col
        any_ = colok.any(axis=1)
        first = np.where(any_, colok.argmax(axis=1), -1)
        last = np.where(any_, colok.shape[1] - 1 - colok[:, ::-1].argmax(axis=1), -1)
        out["c0"].append(first)
        out["c1"].append(last)
        out["w_cards"].append(np.where(any_, last - first + 1, 0))

        ry, rx = R["beam"]
        out["n_beam"].append(m[:, ry, rx].sum(axis=(1, 2)))
        out["white_beam"].append(white[:, ry, rx].sum(axis=(1, 2)))

        ry, rx = R["emblem"]
        out["emb_v"].append(v[:, ry, rx].mean(axis=(1, 2)))
        out["emb_white"].append(white[:, ry, rx].sum(axis=(1, 2)))
        out["emb_hud"].append(m[:, ry, rx].sum(axis=(1, 2)))

        g = 0
        for key in ("glow_l", "glow_r"):
            ry, rx = R[key]
            g = g + m[:, ry, rx].sum(axis=(1, 2))
        out["glow"].append(g)

        ry, rx = R["panel"]
        gray = f[:, ry, rx].astype(np.float32).mean(axis=-1)
        out["dx"].append(np.abs(np.diff(gray, axis=2)).mean(axis=(1, 2)))
        out["mean_v"].append(v.mean(axis=(1, 2)))

        done += n
        if done % (fps * 600) < BATCH:
            el = time.time() - t0
            print(f"  {done / fps / 60:5.1f} min  ({done / el:.0f} fps)", flush=True)
    p.wait()
    arr = {k2: np.concatenate(v2) for k2, v2 in out.items()}
    arr["t"] = np.arange(len(arr["n_cards"])) / fps
    np.savez_compressed(dump / "features.npz", **arr)
    print(f"{len(arr['t'])} frames in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
