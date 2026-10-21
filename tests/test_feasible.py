"""The verdict the guided maker's chips show: one level, one sentence, one fix."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import feasible as fz, studio                     # noqa: E402

DROP = studio.STYLE["drop"]
FAST = studio.STYLE["hype"]
SONG = {"bpm": 174.0, "drops": [125.8]}
NO_DROP = {"bpm": 68.0, "drops": []}


def j(**kw):
    base = dict(style=DROP, song=SONG, clips=20, kills=30, has_setup=True, fmt="vertical")
    base.update(kw)
    return fz.judge(**base)


def test_a_style_that_needs_a_drop_on_a_song_without_one_cannot_be_made():
    v = j(song=NO_DROP)
    assert v.level == fz.BAD and "drop" in v.text and v.fix == "pick-song"


def test_a_fast_style_on_a_slow_song_warns_and_offers_build_and_drop_only_if_there_is_a_drop():
    v = j(style=FAST, song={"bpm": 89.0, "drops": [30.0]})
    assert v.level == fz.WARN and v.fix == "style:drop"
    v = j(style=FAST, song={"bpm": 89.0, "drops": []})
    assert v.level == fz.WARN and v.fix == "pick-song"


def test_nothing_to_build_with_is_named_and_fixable():
    v = j(has_setup=False)
    assert v.level == fz.BAD and "clutch" in v.text and v.fix == "pick-clips"
    assert j(clips=0).level == fz.BAD


def test_a_plan_that_runs_short_says_by_how_much():
    project = {"shots": [{"duration": 0.52}] * 20}
    v = j(project=project, part=(100.0, 128.0))
    assert v.level == fz.WARN and "10 s of the 28 s" in v.text and v.fix == "pick-clips"
    assert j(project={"shots": [{"duration": 1.0}] * 27}, part=(100.0, 128.0)).level == fz.OK


def test_no_shots_is_not_a_reel():
    assert j(project={"shots": []}).level == fz.BAD
    assert j(error="The song has no drum hits after this drop.").level == fz.BAD


def test_a_plan_that_could_not_follow_the_song_is_said_not_hidden():
    v = j(project={"shots": [{"duration": 1.0}] * 28}, part=(0, 28), notes=["x was missing. It was planned the usual build-and-drop way instead."])
    assert v.level == fz.WARN


def test_a_wrong_shape_warns_and_a_good_choice_is_ok():
    assert j(fmt="landscape").fix == "format:vertical"
    assert j().level == fz.OK and j().fix == ""


def test_no_style_asks_for_one():
    assert j(style=None).level == fz.WARN


def test_fast_paced_headshot_counts_headshots_and_is_not_rushed_by_a_slow_song():
    FH = studio.STYLE["fasthead"]
    assert j(style=FH, headshots=5).level == fz.BAD
    v = j(style=FH, headshots=12)
    assert v.level == fz.WARN and "12" in v.text and v.fix == "pick-clips"
    assert j(style=FH, headshots=40, song={"bpm": 90.0, "drops": [30.0]}).level == fz.OK
