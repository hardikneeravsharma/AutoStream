r"""Render the stock style samples: fifteen seconds of every style, cut from the same VALORANT clips.

WHY THESE SHIP
    The Make page's style cards were empty until the player pressed "Show every style
    on my kills" and waited several minutes while eleven samples were cut -- so the one
    screen where a look is chosen opened as a wall of "Not shown yet". A style is chosen
    by watching it, so every card now plays one of these from the moment the page opens.

    Every sample is cut by the same code that cuts a player's own (style_samples.make),
    from the SAME clips, on the same song, so the only thing that differs between two
    cards is the style. The clips are the maintainer's own VALORANT clips, given for
    this and for the stock examples; only the finished, silent, card-sized samples are
    committed -- never the clips or the song.

    A sample cut from the player's own kills still wins wherever one exists
    (style_samples.path_for); these are what a card plays until then.

USAGE
    .\.venv\Scripts\python.exe scripts\make_stock_samples.py --clips <clips folder>
        --song <audio file> [--game VALORANT] [--only hype,chaos]

    Picks the clips examples.sources() would pick (starred first, then shortest), and
    writes autostream\clips\stock_samples\<style>.mp4. Each is a full plan and render,
    about a minute a style.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autostream.clips import examples, reel, studio, style_samples  # noqa: E402

OUT = style_samples.STOCK


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", required=True, help="the clips folder to pick the clips from")
    ap.add_argument("--song", required=True, help="the song every sample is cut to (it is not shipped)")
    ap.add_argument("--game", default="VALORANT", help="only this game's clips")
    ap.add_argument("--only", default="", help="comma-separated style keys")
    a = ap.parse_args()
    root = Path(a.clips)
    picked = examples.sources(root, want=style_samples.SAMPLE_CLIPS, game=a.game)
    if len(picked) < 3:
        raise SystemExit(f"Need at least three {a.game} clips with a kill in {root}; found {len(picked)}.")
    print("cutting from:", ", ".join(c["name"] for c in picked), flush=True)
    shape = reel.analyse(Path(a.song))
    styles = [s for s in a.only.split(",") if s] or [s.key for s in studio.STYLES]
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="as-samples-"))
    failed = {}
    for style in styles:
        print(f"  {style}", flush=True)
        try:
            tmp = style_samples.make(root, picked, style, "landscape", work / f"{style}.mp4",
                                     song=str(a.song), shape=shape, stock=True)
            tmp.replace(OUT / f"{style}.mp4")
        except Exception as e:                       # noqa: BLE001
            failed[style] = str(e)
            print(f"FAILED {style}: {e}", flush=True)
    total = sum(f.stat().st_size for f in OUT.glob("*.mp4"))
    print(f"{len(styles) - len(failed)} stock samples, {total / 1e6:.1f} MB in {OUT}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
