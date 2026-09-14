"""The Studio render, measured: does a kill land where the timeline says?

Tier 4 (media): it runs ffmpeg for real. tests/test_studio.py pins the
arithmetic as strings; strings cannot catch a filter expression ffmpeg refuses,
nor a shot that lands a frame late, and both have happened while building this.

The clips are synthetic and every frame carries its own index as a bar code,
so where a source frame appears in the finished reel is read back exactly --
through speed ramps, crossfades, flashes and freezes -- rather than judged by
eye.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from autostream.clips import studio
from autostream.clips.tools import binary

pytestmark = pytest.mark.media

W, H, F = 320, 180, 60
BITS, BW = 16, 16


def _frame(idx: int) -> bytes:
    a = np.full((H, W, 3), 40, np.uint8)
    for b in range(BITS):
        if idx >> b & 1:
            x = 32 + b * BW
            a[H // 2 - 30: H // 2 + 30, x: x + BW - 3] = 235
    return a.tobytes()


def _read(frame: np.ndarray) -> int:
    row = frame[H // 2, :]
    v = 0
    for b in range(BITS):
        x = 32 + b * BW
        if row[x + 3: x + BW - 6].mean() > 140:
            v |= 1 << b
    return v


def _clip(path: Path, base: int, seconds: float) -> None:
    ff = binary("ffmpeg")
    p = subprocess.Popen([ff, "-hide_banner", "-loglevel", "error", "-y",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(F), "-i", "-",
                          "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000",
                          "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
                          "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], stdin=subprocess.PIPE)
    for n in range(int(seconds * F)):
        p.stdin.write(_frame(base + n))
    p.stdin.close()
    assert p.wait() == 0


def _run_folder(root: Path, n: int, seconds: float = 6.0, kill: float = 3.0) -> list[dict]:
    folder = root / "2026-09-14_1200_VALORANT"
    (folder / "clips").mkdir(parents=True)
    rows = []
    for i in range(n):
        path = folder / "clips" / f"coded_{i}.mp4"
        _clip(path, base=(i + 1) * 2000, seconds=seconds)
        rows.append({"rank": i + 1, "start": 100.0 * (i + 1), "end": 100.0 * (i + 1) + seconds,
                     "duration": seconds, "kills": 1, "name": path.stem, "master": str(path),
                     "vertical": "", "caption": "", "tags": [], "at": ""})
    (folder / "clips.json").write_text(json.dumps({"game": "VALORANT", "clips": rows}))
    (folder / "session.json").write_text(json.dumps(
        {"game": "VALORANT", "kills": [{"time": 100.0 * (i + 1) + kill} for i in range(n)]}))
    lib = studio.library(root)
    return [c for g in lib["games"] for f in g["folders"] for c in f["clips"]]


def _render(root: Path, project: dict) -> tuple[dict, dict, Path]:
    proj, derived, _ = studio.normalise(project, root)
    out = root / "reels" / "check.mp4"
    job = studio.StudioJob(proj, derived, root, out)
    job.run()
    snap = job.snapshot()
    assert snap["state"] == "done", snap["error"]
    return proj, derived, out


@pytest.fixture(scope="module")
def coded(tmp_path_factory):
    try:
        binary("ffmpeg")
    except Exception:                                   # noqa: BLE001
        pytest.skip("ffmpeg is not installed")
    root = tmp_path_factory.mktemp("studio") / "clips"
    return root, _run_folder(root, 4)


def test_every_kill_lands_on_its_planned_frame(coded):
    root, clips = coded
    proj, _ = studio.plan(clips, "velocity")
    proj.update(grade="g01", vignette=False, overlays=[], intro="i00", outro="e12")
    speeds = ["s04", "s02", "s00", "s03"]
    for i, s in enumerate(proj["shots"]):
        s.update(fx=["k04"] if i == 2 else [], hero=False, hero_fx=[], camera="c00", speed=speeds[i])
    proj["shots"][1].update(transition="t04", tlen=0.5)
    proj["shots"][2].update(transition="t02", tlen=0.2)
    proj["shots"][3].update(transition="t06", tlen=0.3)
    proj, derived, out = _render(root, proj)

    raw = subprocess.run([binary("ffmpeg"), "-v", "error", "-i", str(out), "-vf", f"scale={W}:{H}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, H, W)
    assert abs(len(frames) - round(derived["length"] * F)) <= 1, "the reel is not the length the timeline says"
    ids = [_read(f) for f in frames]

    for i, (s, row) in enumerate(zip(proj["shots"], derived["shots"])):
        want = (i + 1) * 2000 + round(s["kill"] * F)
        # THE KILL FRAME IS ON SCREEN AT THE PLANNED INSTANT. Not "first
        # appears then": slowed to 0.3x, each source frame holds for three
        # output frames, so its first appearance is legitimately a little
        # early, and measuring that once read a correct render as 100 ms off.
        at = round(row["kill_reel"] * F)
        near = ids[max(0, at - 1): at + 2]
        assert any(abs(v - want) <= 1 for v in near), (
            f"shot {i + 1} ({s['speed']}, {s['transition']}): at {row['kill_reel']:.3f}s the "
            f"reel shows source frames {[v - (i + 1) * 2000 for v in near]}, "
            f"not the kill frame {want - (i + 1) * 2000}")


def test_every_part_renders_without_ffmpeg_refusing_it(coded):
    """Each id below reaches ffmpeg at least once. An expression it cannot
    parse fails the whole render, and only a render can show that."""
    root, clips = coded
    kills = studio.ids_of("kill")
    heroes = studio.ids_of("hero")
    cameras = studio.ids_of("camera")
    transitions = [t for t in studio.ids_of("transition") if t != "t01"]
    grades, intros, outros = studio.ids_of("grade"), studio.ids_of("intro"), studio.ids_of("outro")
    rounds = max(len(grades), len(intros), len(outros), 3)
    for r in range(rounds):
        proj, _ = studio.plan(clips, "montage")
        proj.update(grade=grades[r % len(grades)], intro=intros[r % len(intros)],
                    outro=outros[r % len(outros)], vignette=bool(r % 2),
                    overlays=studio.ids_of("overlay") if r == 0 else [], handle="@verify")
        for i, s in enumerate(proj["shots"]):
            j = r * len(proj["shots"]) + i
            s.update(fx=[kills[j % len(kills)], kills[(j + 5) % len(kills)]],
                     hero=True, hero_fx=[heroes[j % len(heroes)]], caption="ACE",
                     camera=cameras[j % len(cameras)],
                     speed=studio.ids_of("speed")[j % 5])
            if i:
                s.update(transition=transitions[j % len(transitions)], tlen=0.3)
        _render(root, proj)
