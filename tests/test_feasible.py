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


def test_a_build_and_drop_reel_the_song_cuts_short_says_where_not_how_many_more():
    """JUST A BOY, 2026-10-24: 33 or 48 clips both planned 21 s of a 30 s part -- the take was
    4.5 s and the song's hits stopped at 0:34.8 -- yet the chip asked for 16 more quick kills."""
    project = {"shots": [{"duration": 2.6}] + [{"duration": 0.6}] * 31, "song_offset": 13.6, "song_drop": 18.1}
    v = j(project=project, part=(3.1, 33.1), notes=["Builds on x (3 kills in one take), its last kill on the drop."])
    assert v.level == fz.WARN and v.fix == "part:fit"
    assert "4.5 s before the drop" in v.text and "0:34.8" in v.text and "quick kills" not in v.text
    assert v.span == (13.6, 34.8)                    # the part the page makes of it is what the plan covers
    # ...and when the plan says its clips ran out, more clips are still the fix
    v = j(project=project, part=(3.1, 33.1), notes=["The clips ran out 15 hits before the end of the part."])
    assert v.fix == "pick-clips" and "quick kills" in v.text


def test_a_montage_the_song_cuts_short_says_more_clips_will_not_lengthen_it():
    project = {"shots": [{"duration": 1.0}] * 18, "song_offset": 40.0}
    v = j(style=studio.STYLE["montage"], project=project, part=(40.0, 70.0))
    assert v.level == fz.WARN and v.fix == "part:fit" and "0:58.0" in v.text and v.span == (40.0, 58.0)


def test_no_shots_is_not_a_reel():
    assert j(project={"shots": []}).level == fz.BAD
    assert j(error="The song has no drum hits after this drop.").level == fz.BAD


def test_a_plan_that_could_not_follow_the_song_is_said_not_hidden():
    v = j(project={"shots": [{"duration": 1.0}] * 28}, part=(0, 28), notes=["x was missing. It was planned the usual build-and-drop way instead."])
    assert v.level == fz.WARN and v.fallback          # "Pick the style for me" does not choose it on these terms
    assert not j().fallback


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


def test_the_shortfall_is_counted_in_this_styles_own_kills():
    """It was 0.52 s a kill for every style -- Build and drop's quick kill -- so a montage of
    one-second cuts was told it needed twice the kills it did. The plan's middle shot says."""
    MT = studio.STYLE["montage"]
    v = j(style=MT, project={"shots": [{"duration": 1.0}] * 10}, part=(0.0, 30.0),
          notes=["The clips ran out 20 hits before the end of the part."])
    assert v.level == fz.WARN and "about 20 more kills" in v.text, v.text
    v = j(project={"shots": [{"duration": 8.0}] + [{"duration": 0.5}] * 10}, part=(0.0, 30.0))
    assert "more quick kills" in v.text and "about 34 more" in v.text, v.text   # the take is not a kill's length


def test_fast_paced_headshot_says_the_part_it_is_short_of():
    FH = studio.STYLE["fasthead"]
    assert "rather than 30" in j(style=FH, headshots=12, part=(40.0, 70.0)).text
    assert "rather than 36" in j(style=FH, headshots=12).text


def _feasible_server(monkeypatch, tmp_path, analysed):
    """The feasible endpoint with the song, the library and the plan stubbed: what it judges."""
    from types import SimpleNamespace

    from autostream import webui
    from autostream.clips import reel

    srv = webui.Server.__new__(webui.Server)
    shape = reel.Shape(path=Path("song.wav"), seconds=120.0, bpm=120.0, phase=0.0, downbeat_pos=0,
                       drop=analysed[0] if analysed else None, drops=list(analysed))
    clips = [{"path": str(tmp_path / "ace.mp4"), "kills": [10.0, 11.0, 12.0, 13.0, 14.0], "name": "ace",
              "labels": ["ACE"]},
             {"path": str(tmp_path / "one.mp4"), "kills": [4.0], "name": "one"}]
    seen = {}

    def plan(body):
        seen["body"] = body
        return {"ok": True, "project": {"shots": [{"duration": 1.0}] * 30}, "derived": {"length": 30.0},
                "notes": []}
    monkeypatch.setattr(webui.cfg, "load", lambda: SimpleNamespace())
    monkeypatch.setattr(webui.Server, "_clips_dir", staticmethod(lambda c: tmp_path))
    monkeypatch.setattr(srv, "_studio_shape", lambda song: shape, raising=False)
    monkeypatch.setattr(srv, "_studio_chosen", lambda root, want: [c for c in clips if c["path"] in want],
                        raising=False)
    monkeypatch.setattr(srv, "studio_plan", plan, raising=False)
    return srv, clips, seen


def test_the_verdict_reads_the_drops_the_plan_will_read(monkeypatch, tmp_path):
    """M2: the plan builds on drops marked by hand; the verdict judged the analysis alone, so a
    drop marked on a song with none was refused by a chip whose plan worked -- and the other way."""
    srv, clips, seen = _feasible_server(monkeypatch, tmp_path, analysed=[])
    body = {"style": "drop", "song": "song.wav", "clips": [c["path"] for c in clips], "format": "vertical",
            "part_start": 10.0, "part_end": 40.0}
    assert srv.studio_feasible(body)["verdict"]["level"] == fz.BAD            # no drop found, none marked
    got = srv.studio_feasible(dict(body, drops=[30.0]))
    assert got["verdict"]["level"] != fz.BAD, got
    assert seen["body"]["drops"] == [30.0]                                    # and the plan asked with them
    srv, clips, _ = _feasible_server(monkeypatch, tmp_path, analysed=[30.0])
    got = srv.studio_feasible(dict(body, drops=[]))                           # every drop taken away
    assert got["verdict"]["level"] == fz.BAD and "drop" in got["verdict"]["text"]


def test_a_reel_keeps_the_choices_a_rebuild_must_ask_again(tmp_path):
    """M6: the clip it builds on, whether the part was the page's own, and drops marked by hand
    rode on the request only, so "Add clips" rebuilt without any of them."""
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x")
    song = tmp_path / "s.wav"
    song.write_bytes(b"x")
    base = {"shots": [{"clip": str(clip), "start": 0.0, "end": 2.0}], "song": str(song), "song_offset": 1.0}
    out, _d, _n = studio.normalise(dict(base, build_clip=str(clip), part_auto=True, hand_drops=[31.0, "9.5", -2]),
                                   tmp_path, probe=lambda p: 8.0)
    assert out["build_clip"] == str(clip) and out["part_auto"] is True and out["hand_drops"] == [9.5, 31.0]
    out, _d, _n = studio.normalise(base, tmp_path, probe=lambda p: 8.0)
    assert "build_clip" not in out and "part_auto" not in out and "hand_drops" not in out
    out, _d, _n = studio.normalise(dict(base, hand_drops=[]), tmp_path, probe=lambda p: 8.0)
    assert out["hand_drops"] == []                                            # "no drop at all" is an answer
