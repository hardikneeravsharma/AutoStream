"""The gate: what a reel is checked against before it is called ready.

Each known failure from the first Follow-the-song reels is rebuilt as a small
plan here, and must be caught for its own reason; a plan without it must pass.
The render checks run on a synthetic clip with a blurred stretch.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import reelcheck as rc, studio              # noqa: E402


def shot(clip, kill, dur=0.52, pre=0.2, kills=None):
    return {"clip": f"C:/clips/{clip}.mp4", "kill": kill, "duration": dur, "pre": pre, "kills": kills or [kill]}


def plan(shots, *, length=None, fade=0.0, marks_drift=None):
    starts, t = [], 0.0
    for s in shots:
        starts.append(t)
        t += s["duration"]
    rows = [{"index": i, "start": a, "end": a + s["duration"], "kill_reel": a + s["pre"],
             "drift": (marks_drift or {}).get(i, 0.0)} for i, (a, s) in enumerate(zip(starts, shots))]
    kills = [r["kill_reel"] for r in rows]
    derived = {"shots": rows, "kills": kills, "marks": kills, "on_mark_window": 0.05,
               "length": length if length is not None else t, "outro_fade": fade}
    return {"shots": shots, "song_drop": None}, derived


def codes(f):
    return sorted({x.code for x in f})


def test_a_clean_plan_is_ready():
    proj, d = plan([shot(f"c{i}", 3.5) for i in range(10)], length=6.5)
    f = rc.plan_findings(proj, d)
    assert f == [] and rc.ready(f)


def test_a_clip_used_twice_is_caught_in_a_fast_style():
    """One LAST-ALIVE file played at 17.4 s and again at 21.2 s."""
    shots = [shot("a", 3.5), shot("b", 3.5), shot("a", 11.0), shot("c", 3.5)]
    f = rc.plan_findings(*plan(shots, length=3.0), fast=True)
    assert "repeat" in codes(f) and not rc.ready(f)


def test_a_slow_style_may_use_two_fights_but_not_the_same_fight_twice():
    two_fights = [shot("a", 3.5), shot("b", 3.5), shot("a", 11.0)]
    assert rc.ready(rc.plan_findings(*plan(two_fights, length=3.0), fast=False))
    same = [shot("a", 3.5), shot("b", 3.5), shot("a", 4.5)]
    assert "repeat-fight" in codes(rc.plan_findings(*plan(same, length=3.0), fast=False))


def test_the_opening_take_is_not_a_repeat():
    """A clutch plays as consecutive shots of one clip: that is one take."""
    shots = [shot("clutch", 3.5, 2.5), shot("clutch", 5.0, 2.5), shot("clutch", 7.2, 2.5), shot("b", 3.5)]
    assert rc.ready(rc.plan_findings(*plan(shots, length=9.0), fast=True))


def test_one_file_may_not_take_over_a_slow_reel():
    shots = [shot(f"c{i % 2 and 'x' or 'y'}", 3.5 + i * 10) for i in range(10)]
    assert "too-many-from-one" in codes(rc.plan_findings(*plan(shots, length=6.0), fast=False))


def test_a_twenty_second_shot_is_caught():
    """The Notorious reel after its drop."""
    shots = [shot("a", 3.5, 1.0), shot("b", 3.5, 20.0, pre=0.2), shot("c", 3.5, 0.5)]
    assert "long-shot" in codes(rc.plan_findings(*plan(shots), fast=True))


def test_a_kill_off_its_beat_is_caught():
    proj, d = plan([shot("a", 3.5), shot("b", 3.5)], marks_drift={1: 0.12})
    assert "off-mark" in codes(rc.plan_findings(proj, d))


def test_an_ending_fade_over_the_last_kill_is_caught():
    shots = [shot("a", 3.5, 1.0), shot("b", 3.5, 1.0, pre=0.9)]
    f = rc.plan_findings(*plan(shots, fade=1.4), fast=True)      # fade starts at 0.6 s; last kill at 1.9 s
    assert "fade-over-kill" in codes(f)
    shots = [shot("a", 3.5, 1.0), shot("b", 3.5, 2.5, pre=0.9)]
    assert "fade-over-kill" not in codes(rc.plan_findings(*plan(shots, fade=0.6), fast=True))


def test_a_stalled_flurry_is_said_but_does_not_block():
    shots = [shot("a", 3.5, 1.0), shot("b", 3.5, 3.0), shot("c", 3.5, 0.6)]
    proj, d = plan(shots)
    proj["song_drop"], proj["song_offset"] = 0.0, 0.0
    f = rc.plan_findings(proj, d, fast=True)
    assert "slow-pace" in codes(f) and all(x.level == rc.SOFT for x in f if x.code == "slow-pace")


def test_no_shots_is_not_ready():
    assert not rc.ready(rc.plan_findings({"shots": []}, {"shots": []}))


# ------------------------------------------------------------ the render

def _ff():
    from autostream.clips.tools import binary
    try:
        return binary("ffmpeg")
    except Exception:                                           # noqa: BLE001
        return None


def test_a_blurred_kill_is_caught_in_the_rendered_file_and_a_sharp_one_is_not(tmp_path):
    ff = _ff()
    if not ff:
        pytest.skip("no ffmpeg")
    mp4 = tmp_path / "r.mp4"
    # 4 s of sharp test pattern; from 2.0 s to 2.3 s it is blurred hard
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=60:duration=4",
                    "-vf", "gblur=sigma=30:enable='between(t,2,2.3)',format=yuv420p", str(mp4)],
                   check=True, creationflags=rc._NO_WINDOW)
    proj = {"format": "landscape", "shots": []}
    d = {"length": 4.0, "kills": [2.15, 1.0]}
    f = rc.render_findings(mp4, proj, d, ff)
    blurred = [x for x in f if x.code == "kill-not-sharp"]
    assert [round(x.at, 2) for x in blurred] == [2.15], f
    assert not any(x.code == "wrong-length" for x in f)
    d["length"] = 9.0
    assert "wrong-length" in codes(rc.render_findings(mp4, proj, d, ff))


def test_a_missing_file_and_a_failed_check_are_hard_findings(tmp_path):
    f = rc.render_findings(tmp_path / "nope.mp4", {}, {"length": 1.0})
    assert not rc.ready(f) and f[0].code == "no-file"
    bad = tmp_path / "junk.mp4"
    bad.write_bytes(b"x" * 20_000)
    f = rc.render_findings(bad, {"format": "landscape"}, {"length": 1.0, "kills": [0.5]}, "ffmpeg-that-is-not-there")
    assert not rc.ready(f), f
