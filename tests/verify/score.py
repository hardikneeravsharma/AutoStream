"""Run the real detectors over the corpus, and score them against truth.

    .venv\\Scripts\\python.exe tests\\verify\\score.py scan
    .venv\\Scripts\\python.exe tests\\verify\\score.py scan --only valorant
    .venv\\Scripts\\python.exe tests\\verify\\score.py report

`scan` writes detections.json next to the corpus. `report` scores whatever is
in detections.json against the reviewed baselines and prints the table tier 4
asserts on.

WHAT COUNTS AS A MATCH. A detection is credited to a truth time if it falls
within a per-mode tolerance. The tolerances are not the same because the
readers are not: a template lights up on the frame the marker appears, while
an OCR pass over a kill feed reads a row that is already a second or two old
and stays up for several more. Using one number for both would either forgive
the template everything or fail the feed for being what it is.

WHY PRECISION IS SCORED AT ALL. A detector that finds every kill and thirty
things that are not kills produces thirty clips of nothing, which is the
failure a viewer actually notices. Recall alone would call that perfect.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from autostream.clips import detect, profiles                  # noqa: E402

CORPUS = Path(os.environ.get("AUTOSTREAM_TESTDATA", r"C:\autostream-testdata"))
BASELINES = Path(__file__).resolve().parent / "baselines"

# Seconds either side of a truth time that a detection may land in.
#
#   template  the marker is drawn on a frame; the reader either sees it or
#             does not, and scan_fps=2 puts the worst case at half a second.
#   feedbar   the row appears with the kill and is found by its border.
#   killfeed  Tesseract reads a feed row that persists for about five
#             seconds, so the first sighting can be well after the kill.
TOLERANCE = {"template": 2.0, "feedbar": 2.5, "killfeed": 4.0,
             "cardcount": 3.0, "colour": 2.0}


def manifest() -> list[dict]:
    p = CORPUS / "manifest.json"
    if not p.is_file():
        raise SystemExit(
            f"no corpus at {CORPUS} - build one first:\n"
            f"  .venv\\Scripts\\python.exe tests\\verify\\corpus.py build")
    return json.loads(p.read_text(encoding="utf-8"))["excerpts"]


def detections_file() -> Path:
    return CORPUS / "detections.json"


# --------------------------------------------------------------- scanning


def scan_one(entry: dict) -> dict:
    """One excerpt through the shipped detector for its game.

    detect.scan is called directly rather than through /api/clips/run,
    which means webui._cached_kills never sees this. That is deliberate:
    the cache reuses the kill list from an earlier run of the same
    recording, so going through the API would measure a detector fix
    against the output of the detector before the fix.
    """
    video = CORPUS / entry["file"]
    prof = profiles.for_game(entry["game_key"])
    if prof is None:
        return {"error": f"no profile for {entry['game_key']}"}
    missing = prof.missing()
    if missing:
        return {"error": f"profile not ready: {missing}"}

    t0 = time.monotonic()
    try:
        kills = detect.scan(video, prof)
    except Exception as e:                       # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    took = time.monotonic() - t0

    return {
        "mode": prof.mode,
        "seconds_scanned": entry.get("seconds"),
        "scan_seconds": round(took, 1),
        "detections": [
            {"time": round(float(k.time), 2),
             "end": round(float(getattr(k, "end", k.time) or k.time), 2),
             "score": round(float(getattr(k, "score", 0.0) or 0.0), 4),
             "count": int(getattr(k, "count", 1) or 1)}
            for k in kills
        ],
    }


def cmd_scan(args) -> int:
    rows = manifest()
    if args.only:
        rows = [r for r in rows if args.only in (r["game"], r["clip"])]
    if not rows:
        print("nothing matched --only")
        return 1

    out = {}
    if detections_file().is_file() and not args.force:
        out = json.loads(detections_file().read_text(encoding="utf-8"))

    print(f"\nscanning {len(rows)} excerpt(s)\n")
    for r in rows:
        if r["clip"] in out and not args.force:
            print(f"  [--] {r['clip']}: already scanned "
                  f"({len(out[r['clip']].get('detections', []))} found)")
            continue
        print(f"  [--] {r['clip']} ({r['kind']}, {r.get('seconds')}s) ...",
              flush=True)
        res = scan_one(r)
        res["kind"] = r["kind"]
        res["game"] = r["game"]
        out[r["clip"]] = res
        if "error" in res:
            print(f"       ERROR {res['error']}")
        else:
            print(f"       {len(res['detections'])} detection(s) "
                  f"in {res['scan_seconds']}s of scanning")
        detections_file().write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"\nwritten to {detections_file()}")
    return 0


# --------------------------------------------------------------- scoring


def match(detected: list[float], truth: list[float], tol: float) -> dict:
    """Greedy nearest-first pairing of detections to truth times.

    Greedy rather than optimal: with events seconds apart and a tolerance of
    a couple of seconds, the two agree, and a Hungarian assignment here would
    be precision about a distinction that does not arise.

    One detection can satisfy only one truth time. Without that, a detector
    that fired ten times on one kill would score ten true positives.
    """
    unused = sorted(detected)
    hits, missed = [], []
    for t in sorted(truth):
        best, best_d = None, tol
        for d in unused:
            gap = abs(d - t)
            if gap <= best_d:
                best, best_d = d, gap
        if best is None:
            missed.append(t)
        else:
            unused.remove(best)
            hits.append((t, best, round(best - t, 2)))
    return {"hits": hits, "missed": missed, "extra": unused}


def metrics(m: dict) -> dict:
    tp, fn, fp = len(m["hits"]), len(m["missed"]), len(m["extra"])
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)
    return {"tp": tp, "fn": fn, "fp": fp,
            "recall": round(recall, 4),
            "precision": round(precision, 4),
            "f1": round(f1, 4)}


def baseline(game: str) -> dict:
    p = BASELINES / f"{game}.json"
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def score_all() -> list[dict]:
    """Every scanned excerpt scored against its reviewed baseline.

    An excerpt with no baseline entry is reported as unreviewed rather than
    skipped: a corpus half of which nobody has looked at should be visible,
    not silently absent from the table.
    """
    dets = {}
    if detections_file().is_file():
        dets = json.loads(detections_file().read_text(encoding="utf-8"))
    rows = []
    for entry in manifest():
        clip, game = entry["clip"], entry["game"]
        got = dets.get(clip)
        base = (baseline(game).get("clips") or {}).get(clip)
        row = {"clip": clip, "game": game, "kind": entry["kind"]}
        if got is None:
            row["state"] = "not scanned"
            rows.append(row)
            continue
        if "error" in got:
            row["state"] = "error"
            row["error"] = got["error"]
            rows.append(row)
            continue
        found = [d["time"] for d in got["detections"]]
        row["found"] = len(found)
        row["mode"] = got.get("mode")
        if base is None:
            row["state"] = "unreviewed"
            row["times"] = found
            rows.append(row)
            continue
        tol = base.get("tolerance") or TOLERANCE.get(got.get("mode"), 2.0)
        m = match(found, base.get("truth", []), tol)
        row.update({"state": "scored", "truth": len(base.get("truth", [])),
                    **metrics(m), "detail": m,
                    "floor": base.get("floor", {})})
        rows.append(row)
    return rows


def cmd_report(args) -> int:
    rows = score_all()
    print()
    print(f"{'clip':<26}{'kind':<7}{'found':>6}{'truth':>6}"
          f"{'tp':>4}{'fn':>4}{'fp':>4}{'recall':>9}{'prec':>8}  state")
    print("-" * 92)
    for r in rows:
        if r["state"] == "scored":
            print(f"{r['clip']:<26}{r['kind']:<7}{r['found']:>6}{r['truth']:>6}"
                  f"{r['tp']:>4}{r['fn']:>4}{r['fp']:>4}"
                  f"{r['recall']:>9.2f}{r['precision']:>8.2f}  ok")
        else:
            found = r.get("found", "-")
            print(f"{r['clip']:<26}{r['kind']:<7}{found:>6}{'-':>6}"
                  f"{'-':>4}{'-':>4}{'-':>4}{'-':>9}{'-':>8}  {r['state']}"
                  + (f": {r.get('error', '')}" if r["state"] == "error" else ""))
    print()
    unreviewed = [r for r in rows if r["state"] == "unreviewed"]
    if unreviewed:
        print(f"{len(unreviewed)} excerpt(s) have no reviewed baseline yet. "
              "Until they do, tier 4 cannot fail on them.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("scan")
    s.add_argument("--only", help="a game slug or one clip name")
    s.add_argument("--force", action="store_true",
                   help="re-scan excerpts already in detections.json")
    s.set_defaults(func=cmd_scan)
    r = sub.add_parser("report")
    r.set_defaults(func=cmd_report)
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
