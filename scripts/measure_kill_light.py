"""Measure how much near-white light each kill effect adds at the kill frame.

The planner's light table (studio.KILL_LIGHT) comes from this. Each kill and hero
part is rendered alone, through the renderer's own segment_command, on a set of
moments of real footage, and read back the way the render gate reads a reel
(reelcheck: grey, 540x304, pixels over BRIGHT_LEVEL, the best two-frame run in
KILL_WINDOW around the kill). What a part adds is that share minus the same
moment rendered plain. Re-run it after changing any kill effect's filter or knobs:

    .venv\\Scripts\\python.exe scripts\\measure_kill_light.py CLIP.mp4 [CLIP.mp4 ...]

Prints a dict of part id -> mean share added (and the worst moment), to paste
over KILL_LIGHT. Moments are taken at 25%, 50% and 75% of each clip.
"""
from __future__ import annotations

import concurrent.futures as cf
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autostream.clips import reelcheck, studio  # noqa: E402
from autostream.clips.tools import media_info  # noqa: E402

PRE = 0.4            # s of footage before the kill in each test render
LEN = 1.0            # s rendered


def _render(clip: str, at: float, fx: list[str], hero: list[str], out: Path) -> None:
    seg = studio.Segment(index=0, clip=clip, clip_mtime=0.0, width=640, height=360, fmt="landscape",
                         head=0, body=round(LEN * studio.FPS), tail=0, src_start=at - PRE,
                         pieces=[(0.0, LEN, 1.0)], kill_at=PRE, fx=fx, hero_fx=hero, camera="c00",
                         grade="g01", vignette=False, caption="", beats=[], has_audio=False)
    subprocess.run(studio.segment_command(seg, out), check=True, capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _lit(mp4: Path) -> float:
    """The best two-frame run's share of near-white pixels around the kill."""
    frames = reelcheck._frames("ffmpeg", mp4, "crop=iw:ih:0:0", (540, 304))
    share = (frames > reelcheck.BRIGHT_LEVEL).mean(axis=(1, 2))
    i = round(PRE * studio.FPS)
    a, b = max(0, i - reelcheck.KILL_WINDOW[0]), min(len(share) - 1, i + reelcheck.KILL_WINDOW[1])
    return max(min(share[j], share[j + 1]) for j in range(a, b))


def main(clips: list[str]) -> None:
    moments = []
    for c in clips:
        d = float(media_info(c).get("duration") or 0.0)
        moments += [(c, d * q) for q in (0.25, 0.5, 0.75) if d * q > PRE + 0.1]
    parts = [p.id for p in studio.PARTS if p.kind in ("kill", "hero") and p.id[0] in "kh"]
    work = [("", m) for m in moments] + [(p, m) for p in parts for m in moments]
    tmp = Path(tempfile.mkdtemp(prefix="killlight-"))

    def one(job):
        pid, (clip, at) = job
        out = tmp / f"{pid or 'plain'}_{abs(hash((clip, at)))}.mp4"
        hero = [pid] if pid.startswith("h") else []
        _render(clip, at, [pid] if pid and not hero else [], hero, out)
        v = _lit(out)
        out.unlink(missing_ok=True)
        return pid, (clip, at), v

    got: dict[tuple, float] = {}
    with cf.ThreadPoolExecutor(8) as ex:
        for pid, m, v in ex.map(one, work):
            got[pid, m] = v
    print(f"# {len(moments)} moments of {len(clips)} clips; plain median "
          f"{statistics.median(got['', m] for m in moments):.4f}")
    for pid in parts:
        adds = [max(0.0, got[pid, m] - got["", m]) for m in moments]
        print(f'    "{pid}": {statistics.mean(adds):.3f},   # worst {max(adds):.3f}')


if __name__ == "__main__":
    main(sys.argv[1:])
