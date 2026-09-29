"""Score the CS2 card-tally reader against the match demos.

The demo is ground truth (CLAUDE.md): every kill the player made, to the tick.

    1. The shipped reader (cs2_cards.scan's own pipeline, not a copy of it)
       runs over the dump from cs2_tally_dump.py -- the dump's cards.mkv IS the
       reader's view, cut out once, so this takes minutes instead of a decode
       of the whole recording. The sweep is cached in sweep.npz; pass --rescan
       after changing what it measures. Events land in events.json.
    2. Each demo is placed on the recording by the kill fingerprint
       (cs2_demo.align) and its player found the way the app finds them.
    3. Every demo kill inside the matches is looked for:

    caught   a detected kill within --tol of the demo tick
    missed   none -- the number that has to reach zero
    extra    a detected kill matching no demo kill, inside a match
    timing   detected minus true, over the caught ones

    .venv\\Scripts\\python.exe scripts\\cs2_tally_score.py DUMP_DIR A.dem [B.dem ...]
        [--player NAME] [--tol 0.6] [--rescan] [--list]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autostream.clips import cs2_cards, cs2_demo  # noqa: E402


def run_reader(dump: Path, rescan: bool) -> dict:
    """cs2_cards.scan's pipeline, with the dump standing in for the recording.

    The sweep -- the only slow part -- is kept in sweep.npz, so a change to
    how flashes are judged is re-scored in seconds. --rescan after changing
    what the sweep measures.
    """
    meta = json.loads((dump / "meta.json").read_text())
    video = dump / meta["cards"]["file"]
    c = meta["cards"]
    # The dump was cut at exactly the reader's view for the shipped band, so
    # the view is the whole of it.
    want = cs2_cards.geometry((meta["width"], meta["height"]))
    if want.crop != (c["x"], c["y"], c["w"], c["h"]):
        raise SystemExit(f"the dump's crop {c} is not the reader's view {want.crop}"
                         " -- re-dump it")
    geo = cs2_cards.Geometry(crop=(0, 0, c["w"], c["h"]), k=want.k)
    hue = meta["hue"]
    npz = dump / "sweep.npz"
    if npz.is_file() and not rescan:
        z = np.load(npz)
        sw = cs2_cards.Sweep(fps=float(z["fps"]), **{k: z[k] for k in z.files
                                                      if k != "fps"})
    else:
        t0 = time.time()
        sw = cs2_cards.sweep(video, 0.0, meta["seconds"], hue, geo,
                             progress=lambda i, n: print(f"\r  sweep {i}/{n}",
                                                         end="", flush=True))
        print(f"  ({time.time() - t0:.0f}s)")
        np.savez_compressed(npz, **{k: getattr(sw, k) for k in (
            "fps", "t", "beam", "white_beam", "emblem_white", "width", "dark",
            "et", "emaps", "energy", "panel")})
    fl = cs2_cards.flashes(sw, geo)
    own = cs2_cards.judge(fl, sw, cs2_cards.own_emblems(sw), geo.area)
    kills = [f.time for f in fl for _ in range(f.kills)]
    exact = cs2_cards.refine_onsets(video, kills, hue, geo)
    hidden = cs2_cards.hidden_kills(sw, geo, own, exact)
    out = {
        "kills": sorted([max(0.0, x - cs2_cards.FLASH_LAG) for x in exact] + hidden),
        "hidden": hidden,
        "deaths": cs2_cards.deaths(sw, own),
        "doubtful": [{"time": f.time, "why": f.doubt, "own": round(f.own, 2),
                      "length": f.length, "rise": f.rise} for f in fl if f.doubt],
        "flashes": len(fl), "own_emblems": len(own),
    }
    (dump / "events.json").write_text(json.dumps(out, indent=1))
    return out


def pair(truth: list[float], found: list[float], tol: float):
    """Nearest pairing, each detection used once. -> pairs, missed, extra."""
    free = sorted(found)
    pairs, missed = [], []
    for t in sorted(truth):
        near = [f for f in free if abs(f - t) <= tol]
        if near:
            f = min(near, key=lambda f: abs(f - t))
            pairs.append((t, f))
            free.remove(f)
        else:
            missed.append(t)
    return pairs, missed, free


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", type=Path)
    ap.add_argument("demos", type=Path, nargs="+")
    ap.add_argument("--player", default="")
    ap.add_argument("--tol", type=float, default=0.6)
    ap.add_argument("--rescan", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--video", type=Path, default=None,
                    help="run cs2_cards.scan itself on the full recording "
                         "instead of the dump -- slow, the end-to-end check")
    a = ap.parse_args()

    if a.video:
        ev = cs2_cards.scan(a.video, player=a.player)
        got = {"kills": [e.time for e in ev if e.kind == "kill"], "hidden": [],
               "deaths": [e.time for e in ev if e.kind == "death"],
               "doubtful": [], "flashes": 0, "own_emblems": 0}
        (a.dump / "events_e2e.json").write_text(json.dumps(got, indent=1))
    else:
        got = run_reader(a.dump, a.rescan)
    found = got["kills"]
    print(f"reader: {len(found)} kills ({len(got['hidden'])} hidden), "
          f"{len(got['deaths'])} deaths, {got['flashes']} flashes, "
          f"{len(got['doubtful'])} doubtful, {got['own_emblems']} own emblem(s)")

    truth, dtruth, spans = [], [], []
    for dem in a.demos:
        m = cs2_demo.parse(dem)
        if a.player:
            who = a.player
            s = cs2_demo.align([k.time for k in m.by(who)], found)
        else:
            who, s = cs2_demo.identify(m, found)
        print(f"{dem.name}: {m.map_name}, {who!r}: {s.why}; offset {s.offset:.2f}s")
        if not s.ok:
            continue
        spans.append((s.to_vod(min(r.start for r in m.rounds)),
                      s.to_vod(max(r.end for r in m.rounds))))
        truth += [{"t": s.to_vod(k.time), "round": k.round, "weapon": k.weapon,
                   "victim": k.victim, "map": m.map_name} for k in m.by(who)]
        dtruth += [s.to_vod(k.time) for k in m.deaths_of(who)]
    if not truth:
        print("no demo could be placed on this recording")
        return 1

    def inside(x):
        return any(lo - 5 <= x <= hi + 5 for lo, hi in spans)

    tt = [d["t"] for d in truth]
    pairs, missed, extra = pair(tt, [x for x in found if inside(x)], a.tol)
    err = np.array([f - t for t, f in pairs]) if pairs else np.zeros(1)
    n = len(tt)
    prec = len(pairs) / max(1, len(pairs) + len(extra))
    print(f"\nKILLS  caught {len(pairs)}/{n} ({len(pairs) / n:.1%})  missed "
          f"{len(missed)}  extra {len(extra)}  precision {prec:.1%}")
    print(f"       timing median {np.median(err):+.3f}s  p5 {np.percentile(err, 5):+.3f}"
          f"  p95 {np.percentile(err, 95):+.3f}  worst {np.abs(err).max():.3f}")
    dp, dm, dx = pair(dtruth, [x for x in got["deaths"] if inside(x)], 3.0)
    print(f"DEATHS caught {len(dp)}/{len(dtruth)}  extra {len(dx)}")
    print(f"outside the demos: {[round(x, 1) for x in found if not inside(x)]}")
    if a.list or missed or extra:
        by = {round(d["t"], 3): d for d in truth}
        for t in missed:
            d = by[round(t, 3)]
            print(f"   MISS  {t:8.2f}s  {d['map']} r{d['round']:<2d} {d['weapon']:<14s} {d['victim']}")
        for t in extra:
            print(f"   EXTRA {t:8.2f}s")
    (a.dump / "score.json").write_text(json.dumps({
        "caught": len(pairs), "truth": n, "missed": missed, "extra": extra,
        "errors": [round(float(x), 3) for x in err]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
