"""The groove: camera bounce on the kicks and hats, pops on the snares, the push into the drop."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import fx_schedule as fx, rhythm                 # noqa: E402

BEAT = 0.5


def song():
    kick = [i * BEAT for i in range(0, 80, 2)]           # on one and three
    hats = [i * BEAT + BEAT / 2 for i in range(80)]
    snare = [i * BEAT for i in range(1, 80, 2)]          # on two and four
    layers = {"kick": rhythm.Layer("kick", kick, [0.9] * len(kick)),
              "snare": rhythm.Layer("snare", snare, [0.8] * len(snare)),
              "hats": rhythm.Layer("hats", hats, [0.5] * len(hats))}
    return rhythm.Rhythm(seconds=40.0, beat=BEAT, phase=0.0, kick_phase=0.0, downbeat_pos=0, layers=layers,
                         cues=rhythm.cluster(layers), energy=[],
                         sections=[rhythm.Section(0.0, 4.0, "intro", 0.1), rhythm.Section(4.0, 20.0, "build", 0.5),
                                   rhythm.Section(20.0, 36.0, "drop", 0.9), rhythm.Section(36.0, 40.0, "outro", 0.1)])


def test_quiet_parts_stay_still_and_the_drop_moves_more():
    g = fx.schedule(song(), 0.0, 40.0, kills=[], drop=20.0)
    times = [t for t, _ in g["zoom"]]
    assert not [t for t in times if t < 4.0 or t >= 36.0]
    build = [a for t, a in g["zoom"] if 4.0 <= t < 20.0]
    drop = [a for t, a in g["zoom"] if 20.0 <= t < 36.0]
    assert max(build) < 0.005 and max(drop) >= 0.006
    # the drop adds the hats: more bounces a second than the build
    assert len(drop) > len(build)
    # rates as the spec gives them: build kicks no closer than half a second
    b = sorted(t for t, a in g["zoom"] if 4.0 <= t < 20.0)
    assert all(y - x >= 0.5 - 1e-6 for x, y in zip(b, b[1:]))


def test_a_kill_owns_its_moment():
    kills = [10.0, 25.0]
    g = fx.schedule(song(), 0.0, 40.0, kills=kills, drop=20.0)
    for t, _ in g["zoom"] + g["pops"]:
        assert all(abs(t - k) > fx.KILL_CLEAR for k in kills)
        assert not (20.0 - fx.DROP_CLEAR <= t <= 20.0 + fx.KILL_CLEAR)


def test_the_snare_pops_are_rationed():
    g = fx.schedule(song(), 0.0, 40.0, kills=[], drop=20.0)
    build = sorted(t for t, _ in g["pops"] if 4.0 <= t < 20.0)
    assert build and all(y - x >= fx.POP_MIN["build"] - 1e-6 for x, y in zip(build, build[1:]))
    assert len(build) / 16.0 <= 1.5


def test_the_push_ends_before_the_drop():
    g = fx.schedule(song(), 0.0, 40.0, kills=[], drop=20.0)
    a, b, amt = g["push"]
    assert b == pytest.approx(20.0 - fx.DROP_CLEAR) and b - a == pytest.approx(fx.PUSH_SECONDS - fx.DROP_CLEAR)
    assert 0.015 <= amt <= 0.025


def test_the_expressions_are_on_the_reels_clock():
    g = {"zoom": [[12.0, 0.008]], "pops": [[13.0, 0.03]], "push": [18.0, 19.85, 0.02]}
    z = fx.zoom_expr(g, offset=10.0, length=20.0)
    assert z.startswith("1+") and "2.0000" in z and "between(in_time,8.0000,9.8500)" in z
    assert "between(t,2.9960,3.0125)" in fx.pop_expr(g, offset=10.0, length=20.0)
    assert fx.zoom_expr({"zoom": [[50.0, 0.01]]}, offset=0.0, length=20.0) == ""


def test_clamp_keeps_what_is_sane():
    assert fx.clamp(None) is None
    got = fx.clamp({"zoom": [[1.0, 0.5], ["x", 1], [2.0, 0.004]], "pops": [], "push": [5.0, 4.0, 0.02]})
    assert got == {"zoom": [[1.0, 0.02], [2.0, 0.004]], "pops": [], "push": []}
