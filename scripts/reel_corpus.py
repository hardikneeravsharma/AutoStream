"""Run the reel gate over a regression corpus and say which reels disagree with what is expected.

    python scripts/reel_corpus.py <corpus.json>

The corpus is a list of {"mp4": ..., "project": ..., "fast": true, "expect": ["code", ...]}:
the finding codes (clips/reelcheck.py) a reel is KNOWN to have -- [] for a reel that must
pass, the failures it showed for one that is kept because it failed. It lives beside the
player's own reels and footage, not in the repository: the footage is theirs. Exit status 1
if any reel's findings differ from its expectation -- run it after any change to shared
planning, effects or rendering code.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    from autostream import cfg, paths
    from autostream.clips import reelcheck, studio

    rows = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    root = Path(cfg.load().clips.output_dir or paths.CLIPS_DIR)
    bad = 0
    for r in rows:
        mp4, proj_file = Path(r["mp4"]), Path(r["project"])
        raw = json.loads(proj_file.read_text(encoding="utf-8"))
        project, derived, _ = studio.normalise(raw, root)
        found = reelcheck.check(project, derived, mp4, fast=bool(r.get("fast", True)))
        got = sorted({f.code for f in found if f.level == reelcheck.HARD or f.code in r.get("expect", [])})
        want = sorted(r.get("expect", []))
        ok = got == want
        bad += 0 if ok else 1
        print(("ok   " if ok else "DIFF ") + mp4.name + ("" if ok else f"  expected {want}, got {got}"))
    print(f"{len(rows) - bad} of {len(rows)} as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
