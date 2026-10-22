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


def test_every_style_leaves_out_a_kill_filmed_through_a_flash(tmp_path, monkeypatch):
    """F2: the director's flash check now runs on any style's plan, on a copy of the clip."""
    import json
    from autostream.clips import studio as st
    clips = []
    for i in range(6):
        p = tmp_path / f"c{i}.mp4"
        p.write_bytes(b"x")
        clips.append({"path": str(p), "id": f"c{i}", "name": f"c{i}", "duration": 12.0, "kills": [3.5, 8.0],
                      "hs": [True, True], "labels": []})
    monkeypatch.setattr(st, "kill_clarity", lambda path, t: 20.0 if t > 7 else 900.0)
    monkeypatch.setattr(st, "plan_checks", lambda: {})
    proj, notes = st.plan(clips, "montage", checks=True)
    shown = {k for s in proj["shots"] for k in s["kills"]}
    assert 8.0 not in shown and 3.5 in shown
    assert any("washed out" in n for n in notes)
    assert clips[0]["kills"] == [3.5, 8.0]          # the library's own row is untouched


def test_a_fast_style_plays_each_fight_once_and_whole():
    """One clip's kills 2-5 s apart were dealt round the reel as three shots."""
    from autostream.clips import rulebook
    c = {"path": "C:/c/a.mp4", "kills": [2.9, 5.3, 10.2, 30.0]}
    ms = [rulebook.Moment(clip=c, kills=[k], group=0, seq=i, strength=1.0 + (i == 3) * 0.5) for i, k in enumerate(c["kills"])]
    other = rulebook.Moment(clip={"path": "C:/c/b.mp4"}, kills=[3.0], group=1, strength=1.0)
    dropped = []
    got = rulebook.one_fight_per_clip(ms[:2] + [other] + ms[2:], dropped)
    a = [m for m in got if m.group == 0]
    assert len(a) == 1 and a[0].kills == [2.9, 5.3, 10.2]
    assert dropped == [("C:/c/a.mp4", 30.0)]


def test_a_black_flash_and_a_white_ending_are_caught(tmp_path):
    """ChatGPT's review of the first Fast-paced headshot render: a whole black frame before
    the drop kill, and the last frame burnt almost white. Both had passed every check."""
    ff = _ff()
    if not ff:
        pytest.skip("no ffmpeg")
    mp4 = tmp_path / "r.mp4"
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=60:duration=4",
                    "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=black@1:t=fill:enable='between(t,2,2.02)',"
                           "drawbox=x=0:y=0:w=iw:h=ih:color=white@1:t=fill:enable='gte(t,3.95)',format=yuv420p",
                    str(mp4)], check=True, creationflags=rc._NO_WINDOW)
    f = rc.render_findings(mp4, {"format": "landscape", "shots": []}, {"length": 4.0, "kills": []}, ff)
    got = {x.code: x for x in f}
    assert "black-frame" in got and got["black-frame"].at == pytest.approx(2.0, abs=0.05), f
    assert "white-ending" in got, f
    clean = tmp_path / "c.mp4"
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=60:duration=4",
                    "-vf", "format=yuv420p", str(clean)], check=True, creationflags=rc._NO_WINDOW)
    assert not [x for x in rc.render_findings(clean, {"format": "landscape"}, {"length": 4.0, "kills": []}, ff)
                if x.code in ("black-frame", "white-ending")]


def test_a_master_at_another_frame_rate_is_caught(tmp_path):
    """Every timing claim is made at 60 fps; ChatGPT's review copy read 30 and asked."""
    ff = _ff()
    if not ff:
        pytest.skip("no ffmpeg")
    assert rc.REEL_FPS == studio.FPS
    mp4 = tmp_path / "r30.mp4"
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2",
                    "-vf", "format=yuv420p", str(mp4)], check=True, creationflags=rc._NO_WINDOW)
    f = rc.render_findings(mp4, {"format": "landscape"}, {"length": 2.0, "kills": []}, ff)
    assert "wrong-fps" in codes(f)


def test_two_frames_of_near_white_are_said_but_do_not_block(tmp_path):
    ff = _ff()
    if not ff:
        pytest.skip("no ffmpeg")
    mp4 = tmp_path / "w.mp4"
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=60:duration=4",
                    "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=white@1:t=fill:enable='between(t,1.5,1.55)',format=yuv420p",
                    str(mp4)], check=True, creationflags=rc._NO_WINDOW)
    f = [x for x in rc.render_findings(mp4, {"format": "landscape"}, {"length": 4.0, "kills": []}, ff) if x.code == "too-bright"]
    assert f and f[0].level == rc.SOFT and f[0].at == pytest.approx(1.5, abs=0.05)


def test_a_kill_frame_burnt_white_reads_as_no_detail(tmp_path):
    """ChatGPT's general rule: more than 20 % of the picture over 245 at a kill hides the target,
    however much edge the rest of it has."""
    ff = _ff()
    if not ff:
        pytest.skip("no ffmpeg")
    ok, burnt = tmp_path / "ok.mp4", tmp_path / "burnt.mp4"
    for out, vf in ((ok, "format=yuv420p"), (burnt, "lutyuv=y='min(255,val*2.2)',format=yuv420p")):
        subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=60:duration=2",
                        "-vf", vf, str(out)], check=True, creationflags=rc._NO_WINDOW)
    studio._CLEAR_CACHE.clear()
    assert (studio.kill_clarity(str(ok), 1.0) or 0) >= studio.CLEAR_MIN
    assert studio.kill_clarity(str(burnt), 1.0) == 0.0
