"""Fast-paced headshot plans itself: build, body, burst, slow motion, finale.

Synthetic clips and a synthetic song, so each claim is arithmetic: every kill is
a headshot ON a beat, every clip plays once, the sections come in order at the
spec's lengths, and a song too short for the whole shape gets a shorter one
rather than the general planner.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import fasthead as H, reel, rhythm, studio      # noqa: E402

DROP = 30.0


def song(bpm=120.0, seconds=90.0, drop=DROP):
    beat = 60.0 / bpm
    beats = [0.0 + i * beat for i in range(int(seconds / beat))]
    shape = reel.Shape(path=Path("song.m4a"), seconds=seconds, bpm=bpm, phase=0.0, downbeat_pos=0,
                       drop=drop, drums_in=8.0, beats=beats, drops=[drop])
    layers = {"kick": rhythm.Layer("kick", beats, [0.9] * len(beats)),
              "snare": rhythm.Layer("snare", [], []), "hats": rhythm.Layer("hats", [], [])}
    r = rhythm.Rhythm(seconds=seconds, beat=beat, phase=0.0, kick_phase=0.0, downbeat_pos=0, layers=layers,
                      cues=rhythm.cluster(layers), energy=[0.5] * 900,
                      sections=[rhythm.Section(0.0, drop, "build", 0.5), rhythm.Section(drop, seconds, "drop", 0.9)])
    return shape, r


def clip(name, kills, hs, seconds=10.0, labels=()):
    return {"path": f"C:/clips/{name}.mp4", "id": name, "name": name, "duration": seconds,
            "kills": kills, "hs": hs, "labels": list(labels)}


def library(n=50, doubles=2):
    out = [clip(f"hs{i}", [4.0], [True]) for i in range(n)]
    out += [clip(f"body{i}", [4.0], [False]) for i in range(10)]              # never used
    out += [clip(f"dbl{i}", [4.0, 4.5 + 0.2 * i], [True, True]) for i in range(doubles)]
    return out


def reel_kills(p):
    t, out = 0.0, []
    for s in p.shots:
        out.append(p.part[0] + t + s["pre"])
        t += s["duration"]
    return out


@pytest.mark.parametrize("bpm,unit", [(120, 2), (174, 3), (100, 2), (60, 1)])
def test_the_unit_is_the_beat_multiple_nearest_a_second(bpm, unit):
    assert H.unit_beats(60.0 / bpm) == unit


def test_run_ups_are_whole_beats_and_an_odd_unit_bursts_alternately():
    assert [H.pre_beats(u) for u in (2, 3, 4)] == [1, 2, 2]
    assert H.burst_steps(3, 4) == [1, 2, 1, 2] and H.burst_steps(2, 3) == [1, 1, 1]


def test_every_kill_is_a_headshot_on_a_beat_and_on_its_mark():
    shape, r = song()
    p = H.plan(library(), shape, r, seed=1)
    for t, m in zip(reel_kills(p), p.marks):
        assert t == pytest.approx(m, abs=1e-3)
        assert min(abs(b - m) for b in shape.beats) < 1e-6
    assert not any(s["clip"].split("/")[-1].startswith("body") for s in p.shots)
    assert len({s["clip"] for s in p.shots}) == len(p.shots)          # each clip once


def test_the_sections_come_in_order():
    shape, r = song()
    beat = 0.5
    p = H.plan(library(), shape, r, seed=1)
    m = p.marks
    # the build: four kills two beats apart, the last two beats before the drop
    assert [round(x - DROP, 3) for x in m[:4]] == [-4.0, -3.0, -2.0, -1.0]
    assert m[4] == pytest.approx(DROP)
    gaps = [round(b - a, 3) for a, b in zip(m, m[1:])]
    assert gaps[4] == 2 * beat                                         # the body at 2 beats
    assert sum(1 for g in gaps if g == beat) >= 9                      # the burst at half that
    speeds = [s["speed"] for s in p.shots]
    assert speeds.count("s01") == 1 and speeds[-2] == "s01"           # one slow-motion kill, before the finale
    fin = p.shots[-1]
    assert len(fin["kills"]) == 2 and fin["duration"] == max(s["duration"] for s in p.shots)
    # the finale ends on a bar line
    assert min(abs(b - p.part[1]) for b in shape.beats[::4]) < 1e-3
    assert p.part[1] - p.part[0] == pytest.approx(36.0, abs=4.0)


def test_at_174_the_body_is_three_beats_and_the_burst_alternates():
    shape, r = song(bpm=174.0, seconds=120.0, drop=60.0)
    p = H.plan(library(), shape, r, seed=1)
    beat = 60.0 / 174
    gaps = [round((b - a) / beat) for a, b in zip(p.marks, p.marks[1:])]
    assert gaps[4:8] == [3, 3, 3, 3]
    assert [1, 2, 1, 2] == [g for g in gaps if g in (1, 2)][4:8]


def test_no_double_means_a_single_held_and_the_reel_says_so():
    shape, r = song()
    p = H.plan(library(doubles=0), shape, r, seed=1)
    assert len(p.shots[-1]["kills"]) == 1
    assert "no real multi-kill" in p.notes[0]


def test_a_short_song_gets_a_shorter_shape():
    shape, r = song(seconds=21.0, drop=9.0)
    p = H.plan(library(), shape, r, seed=1)
    assert p.part[1] <= 21.0 + 1e-6 and len(p.shots) >= 8
    assert any("too short for the whole shape" in n for n in p.notes)


def test_too_few_headshots_is_said_not_filled():
    shape, r = song()
    lib = [clip(f"hs{i}", [4.0], [True]) for i in range(5)] + [clip(f"b{i}", [4.0], [False]) for i in range(40)]
    with pytest.raises(ValueError, match="headshots only"):
        H.plan(lib, shape, r)


def test_studio_plans_it_with_the_beat_engine_and_no_groove(tmp_path, monkeypatch):
    shape, r = song()
    clips = library()
    for c in clips:
        p = tmp_path / Path(c["path"]).name
        p.write_bytes(b"x")
        c["path"] = str(p)
    shape.path = tmp_path / "song.m4a"
    shape.path.write_bytes(b"x")
    monkeypatch.setattr(rhythm, "for_song", lambda sh, cache_dir=None: r)
    proj, notes = studio.plan(clips, "fasthead", shape=shape, song=str(shape.path), fmt="vertical")
    assert notes[0].startswith("Fast-paced headshot:"), notes
    assert any(studio.fam(o) == "o09" for o in proj["overlays"]) and not proj["groove"]
    got, derived, _ = studio.normalise(proj, tmp_path, probe=lambda p: 10.0)
    assert derived["on_marks"] == len(got["shots"])
    # too few headshots: the usual planner, and the reason
    few = [c for c in clips if "body" in c["path"]] + clips[:3]
    proj, notes = studio.plan(few, "fasthead", shape=shape, song=str(shape.path), fmt="vertical")
    assert any("planned the usual way" in n for n in notes), notes
