r"""Render the stock examples: one card per Studio part, cut from made-up footage.

WHY MADE-UP FOOTAGE
    Every part in the Studio's parts bin is shown by a short example, cut by the
    same code that renders a reel (clips/examples.py). Those are cut from the
    player's own clips -- which a brand-new install does not have, so a new
    user met a wall of empty cards. The fix ships a set with the app. It
    cannot be cut from anybody's real gameplay: the repo is public, and a
    recording carries a player's name, their team-mates' names and a game's
    artwork. So the footage is drawn here, frame by frame: a skyline, a target
    strafing across the crosshair, a shot, the target dropping. Enough motion
    and colour for a transition, a grade or a punch-in to read, and nobody's.

    The player's own examples still win wherever they exist; these are only
    what a card shows until then (examples.path_for).

USAGE
    .\.venv\Scripts\python.exe scripts\make_stock_examples.py [--only k01,t05] [--keep]

    Writes autostream\clips\stock_examples\<part>.mp4. About a second a part on
    a GPU encoder; the whole set is several minutes.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from autostream.clips import examples, studio  # noqa: E402
from autostream.clips.tools import binary  # noqa: E402

W, H, FPS = 1280, 720, 30
SECONDS = 6.0
OUT = ROOT / "autostream" / "clips" / "stock_examples"
# Smaller than a card cut on the user's machine: these ride inside every
# download, and 560 of them at the usual card size would add 50 MB.
STOCK_WIDTH, STOCK_FPS, STOCK_CRF = 360, 20, 33

SCENES = [
    # sky top, sky horizon, ground near, ground far, building, target, kills
    {"sky": ((38, 20, 74), (247, 140, 82)), "ground": ((40, 30, 36), (96, 62, 60)),
     "bld": (54, 36, 60), "win": (255, 214, 120), "target": (230, 64, 70),
     "kills": [2.6], "seed": 3},
    {"sky": ((10, 40, 70), (90, 200, 210)), "ground": ((20, 38, 44), (60, 98, 96)),
     "bld": (24, 52, 66), "win": (160, 255, 240), "target": (255, 160, 40),
     "kills": [2.2, 4.1], "seed": 11},
]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(top, bottom, w, h):
    col = Image.new("RGB", (1, h))
    for y in range(h):
        col.putpixel((0, y), lerp(top, bottom, y / max(1, h - 1)))
    return col.resize((w, h))


def skyline(scene, rng):
    """A strip of buildings wider than the frame, so the camera can pan over it."""
    strip_w, horizon = W * 3, int(H * 0.56)
    img = Image.new("RGBA", (strip_w, horizon), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = 0
    while x < strip_w:
        bw, bh = rng.randint(70, 200), rng.randint(90, int(horizon * 0.8))
        shade = tuple(max(0, c + rng.randint(-10, 14)) for c in scene["bld"])
        d.rectangle([x, horizon - bh, x + bw, horizon], fill=shade + (255,))
        for wy in range(horizon - bh + 14, horizon - 10, 22):
            for wx in range(x + 10, x + bw - 12, 20):
                if rng.random() < 0.45:
                    d.rectangle([wx, wy, wx + 8, wy + 10], fill=scene["win"] + (255,))
        x += bw + rng.randint(4, 30)
    return img


def draw_frame(scene, strip, t):
    horizon = int(H * 0.56)
    frame = gradient(*scene["sky"], W, H)
    frame.paste(gradient(scene["ground"][1], scene["ground"][0], W, H - horizon), (0, horizon))
    # The camera sways, so a cut or a camera move has motion to act on.
    yaw = 180 * math.sin(t * 0.9) + 60 * t
    frame.paste(strip, (int(-W + (-yaw % W)) - W // 2, 0), strip)
    d = ImageDraw.Draw(frame)
    # Perspective lines on the ground, moving with the camera.
    for i in range(-12, 13):
        x0 = W / 2 + i * 60 - (yaw % 60)
        d.line([(W / 2 + (x0 - W / 2) * 0.15, horizon), (W / 2 + (x0 - W / 2) * 3.2, H)],
               fill=lerp(scene["ground"][1], (0, 0, 0), 0.35), width=2)
    cx, cy = W // 2, int(H * 0.5)
    kills = scene["kills"]
    # One target per kill, each strafing through the crosshair as its kill lands.
    for k, kt in enumerate(kills):
        start, end = kt - 1.8, kt + 1.2
        if not (start <= t <= end):
            continue
        side = -1 if k % 2 == 0 else 1
        x = cx + side * (kt - t) * 260 + 8 * math.sin(t * 14)
        fall = max(0.0, t - kt)
        body = (84, 230)
        col = scene["target"]
        if fall > 0:
            col = lerp(col, (30, 30, 30), min(1, fall * 1.6))
        # Head on the crosshair, so the kill is a headshot the eye can follow.
        top = cy - 30 + fall * 260
        box = Image.new("RGBA", (body[0] + 8, body[1] + 76), (0, 0, 0, 0))
        bd = ImageDraw.Draw(box)
        hx = body[0] // 2 + 4
        bd.ellipse([hx - 28, 0, hx + 28, 56], fill=col + (255,))
        bd.rounded_rectangle([4, 62, body[0] + 4, body[1] + 70], radius=30, fill=col + (255,))
        if fall > 0:
            box = box.rotate(-side * min(85, fall * 220), expand=True, resample=Image.BICUBIC)
        frame.paste(box, (int(x - box.width / 2), int(top - 28)), box)
    # The weapon, kicking back on every shot.
    kick = 0.0
    for kt in kills:
        for s in (kt - 0.35, kt - 0.18, kt):
            if 0 <= t - s < 0.12:
                kick = max(kick, 1 - (t - s) / 0.12)
    gx, gy = int(W * 0.66 + kick * 18), int(H * 0.70 + kick * 30)
    d.polygon([(gx, gy + 40), (gx + 250, gy - 10), (gx + 320, gy + 30), (gx + 360, H),
               (gx + 40, H)], fill=(28, 30, 36))
    d.polygon([(gx + 10, gy + 36), (gx + 230, gy - 4), (gx + 250, gy + 10), (gx + 30, gy + 58)],
              fill=(70, 76, 90))
    if kick > 0.5:
        fx, fy = gx + 8, gy + 30
        d.ellipse([fx - 40, fy - 30, fx + 40, fy + 30], fill=(255, 236, 170))
        d.ellipse([fx - 20, fy - 14, fx + 20, fy + 14], fill=(255, 255, 255))
    # Crosshair, and a hit marker around each kill.
    d.line([(cx - 14, cy), (cx - 4, cy)], fill=(120, 255, 170), width=3)
    d.line([(cx + 4, cy), (cx + 14, cy)], fill=(120, 255, 170), width=3)
    d.line([(cx, cy - 14), (cx, cy - 4)], fill=(120, 255, 170), width=3)
    d.line([(cx, cy + 4), (cx, cy + 14)], fill=(120, 255, 170), width=3)
    for kt in kills:
        if 0 <= t - kt < 0.35:
            r = 16 + (t - kt) * 40
            for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                d.line([(cx + sx * r * 0.5, cy + sy * r * 0.5), (cx + sx * r, cy + sy * r)],
                       fill=(255, 255, 255), width=4)
    return frame


def render_clip(scene, path: Path) -> None:
    rng = random.Random(scene["seed"])
    strip = skyline(scene, rng)
    argv = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
            "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo",
            "-t", str(SECONDS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)]
    p = subprocess.Popen(argv, stdin=subprocess.PIPE)
    for i in range(int(SECONDS * FPS)):
        p.stdin.write(draw_frame(scene, strip, i / FPS).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit(f"ffmpeg failed on {path}")


def fake_library(root: Path) -> None:
    """Two runs of one clip each, laid out the way the clip cutter writes them."""
    for n, scene in enumerate(SCENES):
        run = root / f"stock-{n}"
        (run / "clips").mkdir(parents=True, exist_ok=True)
        master = run / "clips" / f"sample-{n}.mp4"
        render_clip(scene, master)
        (run / "clips.json").write_text(json.dumps({"game": "Sample", "clips": [{
            "name": f"Sample {n + 1}", "master": str(master), "start": 0.0,
            "end": SECONDS, "duration": SECONDS, "kills": len(scene["kills"])}]}),
            encoding="utf-8")
        (run / "session.json").write_text(json.dumps({
            "game": "Sample", "kills": [{"time": k} for k in scene["kills"]],
            "options": {"pre_roll": scene["kills"][0]}}), encoding="utf-8")


def shrink(src: Path, dst: Path) -> None:
    argv = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(src), "-an",
            "-vf", f"fps={STOCK_FPS},scale={STOCK_WIDTH}:-2:flags=lanczos",
            "-c:v", "libx264", "-preset", "slow", "-crf", str(STOCK_CRF),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
    subprocess.run(argv, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated part ids")
    ap.add_argument("--keep", action="store_true", help="keep the scratch folder")
    ap.add_argument("--work", default="", help="scratch folder (default: a temp dir)")
    a = ap.parse_args()
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix="as-stock-"))
    work.mkdir(parents=True, exist_ok=True)
    if not (work / "stock-0").exists():
        fake_library(work)
    only = [p for p in a.only.split(",") if p] or None
    # A stock card must never be mistaken for one of the player's own, so the
    # scratch root has none, and every part is cut fresh.
    parts = only or [p for p in examples.known() if p not in examples.NOTHING]
    OUT.mkdir(parents=True, exist_ok=True)
    done = 0
    for i in range(0, len(parts), 20):
        batch = parts[i:i + 20]
        res = examples.build(work, batch, lambda d, t, p: print(f"  {p}", flush=True) if p else None)
        for part in res.get("made") or []:
            shrink(examples.folder(work) / f"{part}.mp4", OUT / f"{part}.mp4")
            done += 1
        for part, why in (res.get("failed") or {}).items():
            print(f"FAILED {part}: {why}", flush=True)
        print(f"{min(i + 20, len(parts))}/{len(parts)}", flush=True)
    total = sum(f.stat().st_size for f in OUT.glob("*.mp4"))
    print(f"{done} stock examples, {total / 1e6:.1f} MB in {OUT}")
    if not a.keep and not a.work:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
