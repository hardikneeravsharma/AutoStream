"""H2: the player's reactions on the microphone track, measured against their own voice.

The mic is noise-gated, so most of it is silence at the gate's floor; a reaction is
loud for this person SPEAKING. These tracks are built with a known answer: silence,
ordinary talk at -40 dBFS, and one shout 18 dB over it.
"""
from __future__ import annotations

import numpy as np

from autostream.clips import reactions as R

HZ = R.HZ


def _track(seconds=600.0, talk_share=0.35, shouts=((300.0, 5.0, 18.0),), seed=1):
    rng = np.random.default_rng(seed)
    n = int(seconds * HZ)
    lv = np.full(n, -120.0, dtype=np.float32)                 # the gate
    talk = rng.random(n) < talk_share
    lv[talk] = -40.0 + rng.normal(0, 2.0, talk.sum())          # speaking
    for at, length, over in shouts:
        a, b = int(at * HZ), int((at + length) * HZ)
        lv[a:b] = -40.0 + over
    return lv


def test_the_speaking_level_ignores_the_gate():
    assert abs(R.speaking_level(_track()) - (-40.0)) < 1.0


def test_a_shout_over_the_players_own_voice_is_a_reaction():
    got = R.find(_track())
    assert got and abs(got[0].at - 300.0) < 5.5 and got[0].peak_db > 15
    assert 4.5 <= got[0].end - got[0].start <= 5.5


def test_ordinary_talk_and_the_gate_are_not_reactions():
    """The rolling-median reader called every word a peak; this one calls none."""
    assert R.find(_track(shouts=())) == []


def test_a_longer_shout_outranks_a_shorter_one_as_loud():
    got = R.find(_track(shouts=((100.0, 1.0, 16.0), (400.0, 6.0, 16.0))))
    assert [round(r.start) for r in got[:2]] == [400, 100]


def test_a_muted_mic_has_no_speaking_level_and_no_reactions():
    lv = np.full(int(600 * HZ), -120.0, dtype=np.float32)
    assert R.speaking_level(lv) is None and R.find(lv) == []


def test_times_are_in_the_file_not_the_window():
    got = R.find(_track(), offset=1000.0)
    assert 1295 <= got[0].at <= 1306


def test_a_blip_shorter_than_the_minimum_is_not_a_reaction():
    assert R.find(_track(shouts=((300.0, 0.2, 20.0),))) == []


# ------------------------------------------------------------------ as clips

from types import SimpleNamespace as NS  # noqa: E402

from autostream.clips import plan  # noqa: E402


def _r(start, end, score=10.0, kind=""):
    return NS(start=start, end=end, at=start + 0.5, score=score, kind=kind)


def test_a_reaction_clip_starts_before_its_cause():
    """The hand-cut rage meme starts ~20 s before its shout: the cause is shown."""
    got = plan.build_reactions([_r(712.0, 717.4)], game="VALORANT", kills=[695.0, 700.0])
    c = got[0]
    assert c.start == 695.0 - plan.REACT_LEAD and c.end == 717.4 + plan.REACT_AFTER
    assert c.labels == ["REACTION"] and c.kills == 0 and c.reaction == [712.0, 717.4]


def test_with_no_cause_in_sight_it_takes_the_default_run_up():
    c = plan.build_reactions([_r(500.0, 503.0)], game="VALORANT", kills=[100.0])[0]
    assert c.start == 500.0 - plan.REACT_PRE


def test_a_round_ending_soon_after_is_shown_ending():
    rnd = NS(started=480.0, ended=510.0)
    c = plan.build_reactions([_r(500.0, 503.0)], game="VALORANT", rounds=[rnd])[0]
    assert c.end == 511.0


def test_a_clip_is_never_longer_than_the_cap():
    c = plan.build_reactions([_r(700.0, 730.0)], game="VALORANT", kills=[681.0])[0]
    assert c.end - c.start <= plan.REACT_MAX + 1e-9


def test_only_the_strongest_ten_an_hour_become_clips():
    many = [_r(60.0 * i + 10, 60.0 * i + 12, score=100 - i) for i in range(40)]
    assert len(plan.build_reactions(many, game="VALORANT", hours=1.0)) == 10
    assert len(plan.build_reactions(many, game="VALORANT", hours=0.5)) == 5


def test_a_reaction_on_a_kill_clip_joins_it_rather_than_doubling_it():
    kill = plan.ClipPlan(rank=1, start=690.0, end=715.0, kills=3, burst_kills=3,
                         peak_score=3.0, name="k", labels=["3K"])
    made = plan.build_reactions([_r(712.0, 717.4), _r(1500.0, 1503.0)], game="VALORANT")
    out = plan.merge_reactions([kill], made)
    assert len(out) == 2
    assert out[0].labels == ["3K", "REACTION"] and out[0].end == 717.4 + plan.REACT_AFTER
    assert out[1].kills == 0 and out[1].labels == ["REACTION"]


def test_a_classified_reaction_keeps_its_name():
    assert plan.build_reactions([_r(500.0, 502.0, kind="laugh")], game="X")[0].labels == ["LAUGH"]


def test_the_reactions_switch_reaches_the_job():
    """Both ends, as for match_summary: a flag the page sends and the server drops
    is a switch that does nothing."""
    import pathlib

    from autostream import webui as w
    from autostream.ui import clips as clips_page

    assert "reactions: clip_state.react !== false" in clips_page.CLIPS_JS
    assert 'id="clip-react"' in clips_page.CLIPS_HTML
    src = pathlib.Path(w.__file__).read_text(encoding="utf-8")
    run = src[src.index("def clips_run(self, body: dict) -> dict:"):]
    run = run[:run.index("    def _cached_kills(")]
    assert 'opt["reactions"]' in run
