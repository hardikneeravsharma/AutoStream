r"""Render the stock examples: one card per Studio part, cut from real VALORANT clips.

WHY REAL FOOTAGE
    Every part in the Studio's parts bin is shown by a short example, cut by the
    same code that renders a reel (clips/examples.py). Those are cut from the
    player's own clips -- which a brand-new install does not have, so the app
    ships a set. That set used to be cut from footage this script drew: a
    skyline and a blob strafing across a crosshair. Nobody can judge a colour
    grade, a kill flash or a punch-in on a drawing, so the cards showed the
    part without showing what it does to a game. The maintainer gave two of
    their own VALORANT clips for the job; they are used for these cards and
    for nothing else, and only the finished cards are committed -- never the
    clips themselves.

    The player's own examples still win wherever they exist; these are only
    what a card shows until then (examples.path_for).

USAGE
    .\.venv\Scripts\python.exe scripts\make_stock_examples.py --clips <clips folder>
        [--game VALORANT] [--only k01,t05] [--keep]

    Picks the two clips examples.sources() would pick, from that game only,
    copies them into a scratch clips folder of their own (so nothing is written
    into the real one), and writes autostream\clips\stock_examples\<part>.mp4.
    About a second a part on a GPU encoder; the whole set is several minutes.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autostream.clips import examples  # noqa: E402
from autostream.clips.tools import binary  # noqa: E402

OUT = ROOT / "autostream" / "clips" / "stock_examples"
# Smaller than a card cut on the user's machine: these ride inside every
# download, and 560 of them at the usual card size would add 70 MB.
STOCK_WIDTH, STOCK_FPS, STOCK_CRF = 360, 20, 33


def scratch_library(src: Path, game: str, work: Path) -> list[str]:
    """Two runs of one clip each, copied from the real clips folder. -> names."""
    picked = examples.sources(src, game=game)
    if len(picked) < 2:
        raise SystemExit(f"Need two {game} clips with a kill in {src}; found {len(picked)}.")
    for n, c in enumerate(picked):
        run = work / f"stock-{n}"
        (run / "clips").mkdir(parents=True, exist_ok=True)
        master = run / "clips" / f"sample-{n}.mp4"
        shutil.copy2(c["path"], master)
        dur = float(c["duration"])
        (run / "clips.json").write_text(json.dumps({"game": game, "clips": [{
            "name": f"Sample {n + 1}", "master": str(master), "start": 0.0,
            "end": dur, "duration": dur, "kills": len(c["kills"])}]}), encoding="utf-8")
        (run / "session.json").write_text(json.dumps({
            "game": game, "kills": [{"time": k} for k in c["kills"]]}), encoding="utf-8")
    return [c["name"] for c in picked]


def shrink(src: Path, dst: Path) -> None:
    argv = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(src), "-an",
            "-vf", f"fps={STOCK_FPS},scale={STOCK_WIDTH}:-2:flags=lanczos",
            "-c:v", "libx264", "-preset", "slow", "-crf", str(STOCK_CRF),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
    subprocess.run(argv, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", required=True, help="the clips folder to pick two clips from")
    ap.add_argument("--game", default="VALORANT", help="only this game's clips")
    ap.add_argument("--only", default="", help="comma-separated part ids")
    ap.add_argument("--keep", action="store_true", help="keep the scratch folder")
    ap.add_argument("--work", default="", help="scratch folder (default: a temp dir)")
    a = ap.parse_args()
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix="as-stock-"))
    work.mkdir(parents=True, exist_ok=True)
    if not (work / "stock-0").exists():
        print("cutting from:", ", ".join(scratch_library(Path(a.clips), a.game, work)), flush=True)
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
