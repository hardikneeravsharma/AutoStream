r"""A reel keeps the hard cut and one other transition, and two kill effects (asked 2026-10-17).

The styles' pools hold up to seven transitions and ten kill effects; drawn shot by
shot, a 36-shot montage used most of them and read as a sampler. A set the player
picks on the Make page is theirs and is left alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import test_studio as T                                             # noqa: E402
from autostream.clips import studio                                 # noqa: E402


@pytest.fixture
def clips_root(tmp_path):
    r = tmp_path / "clips"
    T._run(r, "2026-09-01_1200_VALORANT", "VALORANT",
           [{"start": 100.0 * i, "end": 100.0 * i + 12} for i in range(1, 25)],
           kills=[100.0 * i + 6 for i in range(1, 25)])
    return r


def _mix(proj):
    trans = {s["transition"] for s in proj["shots"][1:]}
    kills = {f for s in proj["shots"] for f in s["fx"]}
    return trans, kills


@pytest.mark.parametrize("style", ["montage", "velocity", "story", "chaos", "retro", "cinematic"])
def test_every_style_keeps_to_two_transitions_and_two_kill_effects(clips_root, style):
    proj, _ = studio.plan(T._clips(clips_root), style, shape=T.Shape(bpm=100.0))
    trans, kills = _mix(proj)
    assert len(trans | {"t01"}) <= studio.MAX_TRANSITIONS, trans
    assert len(kills) <= studio.MAX_KILL_FX, kills


def test_mix_them_up_keeps_to_it_too(clips_root):
    proj, _ = studio.plan(T._clips(clips_root), "velocity", shape=T.Shape(bpm=100.0))
    for seed in range(5):
        studio.vary(proj, "all", seed=seed)
        trans, kills = _mix(proj)
        assert len(trans | {"t01"}) <= studio.MAX_TRANSITIONS
        assert len(kills) <= studio.MAX_KILL_FX


def test_a_set_the_player_picked_is_left_as_it_is(clips_root):
    picked = ["t04", "t05", "t06"]
    proj, _ = studio.plan(T._clips(clips_root), "montage", shape=T.Shape(bpm=100.0),
                          template={"transition": picked})
    trans, _ = _mix(proj)
    assert len(trans - {"t01", "t02"}) > 1, "three picked, more than one used"
    assert "transition" in proj["mix_free"]
