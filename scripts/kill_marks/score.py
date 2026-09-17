r"""Score the kill detector against the kills the player marked by ear.

    .venv\Scripts\python.exe scripts\kill_marks\score.py [--level 0.8] [--gap 0.14] ...

Every song marked in Kill Marks is replayed through autostream/clips/hits.py
and compared with the marks:

    what        which pattern the song turned out to have -- the bass hits, or
                another band's repeated bar figure
    caught      marks with a detected hit within TOL
    /min        hits a minute -- the detector must not fire several times per kick
    offset      detected hit minus the mark it matched
    KILLS       the share of marks that choose_kills() actually CUTS on, at the
                spacing the player marked at. This is the number that decides a
                reel: a hit nobody cuts on is worth nothing.
    lag         how late the marks are against the hits they sit on -- the
                player's own reaction, which the page can measure and correct.
                A kick can be anticipated (14 ms), a swelling hat has to be
                reacted to (100 ms), so KILLS is also given with that constant
                lag taken out: it says whether the right moments were found,
                separately from when the finger landed.
    big         big marks caught by big_hits()

The numbers, not the code, decide whether a change is an improvement (see
CLAUDE.md). Measured this way: the level-peak detector beat the rise-based one
it replaced (73% against 58% at the same density); taking the LOUDEST hit where
the next kill belongs beat taking every Nth (62% of marks cut on against 45%);
and Believer, whose kick lands on 4% of its marks, needed its hats' bar figure
instead.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from autostream import paths                            # noqa: E402
from autostream.clips import beatsync as bs, hits as H  # noqa: E402

MARKS = paths.VIDEO_HOME / "songs" / "marks"
TOL = 0.06                      # the tolerance the marks were measured at


def pair(want: list[float], got: list[float], tol: float = TOL):
    """Match marks to detections, nearest first. -> (pairs, missed, stray)"""
    cand = sorted((abs(w - g), i, j)
                  for i, w in enumerate(want) for j, g in enumerate(got) if abs(w - g) <= tol)
    used_w: set[int] = set()
    used_g: set[int] = set()
    pairs = []
    for _, i, j in cand:
        if i in used_w or j in used_g:
            continue
        used_w.add(i)
        used_g.add(j)
        pairs.append((want[i], got[j]))
    return (pairs,
            [w for i, w in enumerate(want) if i not in used_w],
            [g for j, g in enumerate(got) if j not in used_g])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--level", type=float, default=H.LEVEL)
    p.add_argument("--local", type=float, default=H.LOCAL_SECONDS)
    p.add_argument("--gap", type=float, default=H.MIN_GAP)
    p.add_argument("--big", type=float, default=H.BIG_RISE)
    p.add_argument("--tol", type=float, default=TOL)
    p.add_argument("--song", default="", help="only this video id")
    p.add_argument("--nth", action="store_true", help="thin by every Nth hit, the old way")
    a = p.parse_args()
    H.LEVEL, H.LOCAL_SECONDS, H.MIN_GAP, H.BIG_RISE = a.level, a.local, a.gap, a.big

    files = sorted(f for f in MARKS.glob("*.json") if not f.name.startswith("_"))
    if a.song:
        files = [f for f in files if a.song in f.name]
    tot_marks = tot_caught = tot_big = tot_big_caught = tot_kill = tot_lag = 0
    offsets: list[float] = []
    dens: list[float] = []
    print(f"level {a.level}  local {a.local}s  min gap {a.gap}s  big rise {a.big}   "
          f"tolerance +/-{a.tol * 1000:.0f} ms"
          + ("   thinning: every Nth" if a.nth else "   thinning: the loudest in the window") + "\n")
    head = (f"{'song':30s} {'what':>12s} {'marks':>5s} {'caught':>7s} {'/min':>5s} "
            f"{'offset ms':>24s} {'KILLS':>6s} {'lag':>5s} {'-lag':>5s} {'big':>8s}")
    print(head)
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        song = Path(d.get("path") or "")
        marks = sorted(m["t"] for m in (d.get("marks") or []))
        if not marks:
            continue
        if not song.is_file():
            print(f"{d.get('title', f.stem)[:30]:30s} (the song file is gone)")
            continue
        bigs = [m["t"] for m in d["marks"] if m["kind"] == "big"]
        x = bs.load_mono(song)
        beat = 60.0 / ((d.get("analysis") or {}).get("bpm") or 120.0)
        got, strength, kind = H.song_hits(x, beat, len(x) / bs.SR)
        big, _rises = H.big_hits(x, got)
        # Thinned at the spacing the PLAYER marked at, not a style's, so this
        # measures which hits are chosen rather than how fast a reel cuts.
        own = float(np.median(np.diff(marks))) if len(marks) > 2 else 1.0
        kills, _accents = H.choose_kills(got, None if a.nth else strength, target_gap=own)
        pairs, _missed, _stray = pair(marks, got, a.tol)
        kpairs, _km, _ks = pair(marks, kills, a.tol)
        # The song's own timing bias: how late every mark is against the
        # nearest hit, whether or not that hit was matched.
        lag = float(np.median([min((g - m for g in got), key=abs) for m in marks])) if got else 0.0
        klag, _a, _b = pair(marks, [k - lag for k in kills], a.tol)
        offs = [(g - w) * 1000 for w, g in pairs]
        bpairs, _bmissed, _ = pair(bigs, big, 0.12)
        mins = max(1e-6, len(x) / bs.SR / 60)
        tot_marks += len(marks)
        tot_caught += len(pairs)
        tot_kill += len(kpairs)
        tot_big += len(bigs)
        tot_big_caught += len(bpairs)
        offsets += offs
        dens.append(len(got) / mins)
        print(f"{d.get('title', '')[:30]:30s} {kind:>12s} {len(marks):5d} "
              f"{len(pairs) / len(marks) * 100:6.0f}% {len(got) / mins:5.0f} "
              f"{np.median(offs) if offs else 0:+6.0f} "
              f"(p10 {np.percentile(offs, 10) if offs else 0:+5.0f}, "
              f"p90 {np.percentile(offs, 90) if offs else 0:+5.0f}) "
              f"{len(kpairs) / len(marks) * 100:5.0f}% {-lag * 1000:+5.0f} "
              f"{len(klag) / len(marks) * 100:4.0f}% {len(bpairs):4d}/{len(bigs):<3d}")
        tot_lag += len(klag)
    print(f"\n{'ALL':30s} {'':12s} {tot_marks:5d} "
          f"{tot_caught / max(1, tot_marks) * 100:6.0f}% {np.mean(dens) if dens else 0:5.0f} "
          f"{np.median(offsets) if offsets else 0:+6.0f} "
          f"(p10 {np.percentile(offsets, 10) if offsets else 0:+5.0f}, "
          f"p90 {np.percentile(offsets, 90) if offsets else 0:+5.0f}) "
          f"{tot_kill / max(1, tot_marks) * 100:5.0f}% {'':5s} "
          f"{tot_lag / max(1, tot_marks) * 100:4.0f}% {tot_big_caught:4d}/{tot_big:<3d}")


if __name__ == "__main__":
    main()
