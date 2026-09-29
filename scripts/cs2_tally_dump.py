"""Dump a CS2 recording's HUD once, so the card-tally reader can be scored offline.

WHY. Scoring a detector against a demo means re-reading the same recording
dozens of times, and every read of a 2.5-hour 1080p60 file is a full decode.
The reader only ever looks at two small regions -- the card tally with the
spectator panel beside it, and the kill feed -- so this cuts those out ONCE,
at full frame rate, into two small videos. Every later pass decodes those in
a fraction of the time.

    cards.mkv   the tally, the rank emblem and the spectator panel, 60 fps,
                near-lossless RGB: the reader measures hue and pixel widths,
                so this must not smear colour the way 4:2:0 would
    feed.mkv    the kill feed, 30 fps: rows hold for ~5 s, so OCR on doubtful
                kills needs nothing finer
    meta.json   geometry, frame rates and the measured HUD hue, so readers can
                map the reader's frame fractions onto the crops

Frame i of each file is at i / fps seconds in the recording (it starts at 0).

    .venv\\Scripts\\python.exe scripts\\cs2_tally_dump.py RECORDING OUT_DIR
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autostream.clips import cs2_cards  # noqa: E402
from autostream.clips.tools import binary, media_info  # noqa: E402

# Frame fractions. The card box plus a margin, wide enough to take in PANEL on
# the left, so a recalibrated box still falls inside the dump.
CARDS_CROP = (0.39, 0.85, 0.58, 0.98)
# The CS2 profile's feed band (profiles.py).
FEED_CROP = (0.60, 0.030, 1.000, 0.300)
CARDS_FPS = 60
FEED_FPS = 30


def px(band, w, h):
    x1, y1, x2, y2 = band
    x, y = int(w * x1) // 2 * 2, int(h * y1) // 2 * 2
    cw, ch = int(w * (x2 - x1)) // 2 * 2, int(h * (y2 - y1)) // 2 * 2
    return x, y, cw, ch


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="dump only this much from the start (a test run)")
    a = ap.parse_args()

    info = media_info(a.video)
    w, h = int(info["width"]), int(info["height"])
    total = float(info["duration"])
    secs = a.seconds or total
    a.out.mkdir(parents=True, exist_ok=True)

    cx, cy, cw, ch = px(CARDS_CROP, w, h)
    fx, fy, fw, fh = px(FEED_CROP, w, h)
    hue = cs2_cards.measure_hue(a.video, total)
    meta = {
        "source": str(a.video), "width": w, "height": h, "duration": total,
        "seconds": secs, "hue": hue,
        "cards": {"file": "cards.mkv", "fps": CARDS_FPS,
                  "x": cx, "y": cy, "w": cw, "h": ch},
        "feed": {"file": "feed.mkv", "fps": FEED_FPS,
                 "x": fx, "y": fy, "w": fw, "h": fh},
        "reader": {"CARDS": cs2_cards.CARDS, "PANEL": cs2_cards.PANEL},
    }
    print(f"HUD hue {hue}; cards {cw}x{ch}@{CARDS_FPS}, feed {fw}x{fh}@{FEED_FPS}",
          flush=True)

    t0 = time.time()
    subprocess.run([
        binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-stats",
        "-nostdin", "-y", "-t", f"{secs:.3f}", "-i", str(a.video), "-an", "-sn",
        "-filter_complex",
        f"[0:v]split=2[p][q];"
        f"[p]fps={CARDS_FPS},crop={cw}:{ch}:{cx}:{cy}[c];"
        f"[q]fps={FEED_FPS},crop={fw}:{fh}:{fx}:{fy}[f]",
        "-map", "[c]", "-c:v", "libx264rgb", "-crf", "4", "-preset", "veryfast",
        "-g", "60", str(a.out / "cards.mkv"),
        "-map", "[f]", "-c:v", "libx264", "-crf", "14", "-preset", "veryfast",
        "-pix_fmt", "yuv444p", "-g", "30", str(a.out / "feed.mkv"),
    ], check=True)
    meta["dump_seconds"] = round(time.time() - t0, 1)
    (a.out / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"done in {meta['dump_seconds']}s -> {a.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
