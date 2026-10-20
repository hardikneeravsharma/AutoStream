"""Follow the song: the set-up take into the drop, the drums after it.

Synthetic clips and a synthetic song, so every claim is arithmetic: the take's
last kill is ON the drop, every kill after it is on a cue, no clip plays twice,
a double is retimed to hit two cues, and each shot ends where the next one's
run-up starts.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import director, reel, rhythm, studio            # noqa: E402

BEAT = 60 / 174
DROP = 40.0


def song():
    """174 BPM, a kick every beat, a snare on the off-beats, sections around one drop."""
    beats = [0.1 + i * BEAT for i in range(int(80 / BEAT))]
    shape = reel.Shape(path=Path("song.m4a"), seconds=80.0, bpm=174.0, phase=0.1, downbeat_pos=0,
                       drop=DROP, drums_in=8.0, beats=beats, drops=[DROP])
    kick = [b for b in beats]
    snare = [b + BEAT / 2 for b in beats]
    layers = {"kick": rhythm.Layer("kick", kick, [0.9] * len(kick)),
              "snare": rhythm.Layer("snare", snare, [0.7] * len(snare)),
              "hats": rhythm.Layer("hats", [], [])}
    r = rhythm.Rhythm(seconds=80.0, beat=BEAT, phase=0.1, kick_phase=0.1, downbeat_pos=0, layers=layers,
                      cues=rhythm.cluster(layers), energy=[0.5] * 800,
                      sections=[rhythm.Section(0.0, 30.0, "verse", 0.5), rhythm.Section(30.0, DROP, "build", 0.6),
                                rhythm.Section(DROP, 62.0, "drop", 0.9), rhythm.Section(62.0, 80.0, "outro", 0.2)])
    return shape, r


def clip(name, kills, hs=None, seconds=12.0, labels=()):
    return {"path": f"C:/clips/{name}.mp4", "id": name, "name": name, "duration": seconds,
            "kills": kills, "hs": hs if hs is not None else [True] * len(kills), "labels": list(labels)}


def library(singles=30, doubles=6):
    out = [clip("clutch", [3.5, 5.0, 7.2], labels=["CLUTCH 1v3"], seconds=12.0)]
    out += [clip(f"one{i}", [3.5], hs=[i % 3 != 0]) for i in range(singles)]
    out += [clip(f"two{i}", [3.5, 3.5 + 0.55 + 0.05 * i]) for i in range(doubles)]
    return out


def test_the_setup_take_lands_its_last_kill_on_the_drop():
    shape, r = song()
    p = director.plan(library(), shape, r, seed=3)
    take = [s for s in p.shots if s["name"] == "clutch"]
    assert [s["kill"] for s in take] == [3.5, 5.0, 7.2]
    t = 0.0
    for s, m in zip(p.shots, p.marks):
        if s["name"] == "clutch":
            assert p.part[0] + t + s["pre"] == pytest.approx(m, abs=1e-3)
        t += s["duration"]
    assert p.marks[len(take) - 1] == pytest.approx(DROP, abs=1e-3)
    # the take is one piece of footage: each shot starts where the last one stopped
    for a, b in zip(take, take[1:]):
        assert a["kill"] - a["pre"] + a["duration"] == pytest.approx(b["kill"] - b["pre"], abs=1e-3)


def test_every_kill_after_the_drop_is_on_a_cue_and_on_its_mark():
    shape, r = song()
    p = director.plan(library(), shape, r, seed=1)
    cues = {round(c["t"], 3) for c in r.cues}
    t = 0.0
    for s, m in zip(p.shots, p.marks):
        reel_kill = p.part[0] + t + s["pre"]
        assert reel_kill == pytest.approx(m, abs=1e-3)
        if m > DROP + 0.01:
            assert round(m, 3) in cues
        t += s["duration"]


def test_the_flurry_keeps_the_pace_and_the_drop_is_held():
    shape, r = song()
    p = director.plan(library(), shape, r, seed=2)
    after = [m for m in p.marks if m > DROP + 0.01]
    assert after, "nothing after the drop"
    gap = director.preferred_gap(BEAT)
    assert gap == pytest.approx(1.5 * BEAT)                 # 0.517 s at 174 BPM
    assert after[0] - DROP >= 0.9 * director.DROP_AFTER * gap - 1e-6
    for a, b in zip(after, after[1:]):
        assert 0.8 * gap - 1e-6 <= b - a <= 3.2 * gap + 1e-6


def test_no_clip_plays_twice_outside_its_take():
    shape, r = song()
    p = director.plan(library(), shape, r, seed=5)
    names = [s["name"] for s in p.shots if s["name"] != "clutch"]
    assert len(names) == len(set(names))


def test_a_double_is_one_shot_that_hits_two_cues():
    shape, r = song()
    p = director.plan(library(singles=10, doubles=8), shape, r, seed=4)
    runs = [s for s in p.shots if s.get("anchors")]
    assert runs, "no double was used as a run"
    cues = {round(c["t"], 3) for c in r.cues}
    t = 0.0
    for s in p.shots:
        if s.get("anchors"):
            (src, out), = s["anchors"]
            assert src == s["kills"][1]
            assert round(p.part[0] + t + out, 3) in cues
            rate = (s["kills"][1] - s["kill"]) / (out - s["pre"])
            assert director.PAIR_RATE[0] - 1e-6 <= rate <= director.PAIR_RATE[1] + 1e-6
        t += s["duration"]


def test_the_best_headshots_take_the_last_and_strongest_hits():
    shape, r = song()
    p = director.plan(library(), shape, r, seed=6)
    singles = [s for s in p.shots if s["name"].startswith("one")]
    # the last shot is a headshot (one0, one3 ... are not)
    last = p.shots[-1]
    if last["name"].startswith("one"):
        assert int(last["name"][3:]) % 3 != 0
    non_hs = [s for s in singles if int(s["name"][3:]) % 3 == 0]
    hs = [s for s in singles if int(s["name"][3:]) % 3 != 0]
    assert len(hs) >= len(non_hs)


def test_nothing_to_build_with_is_said_not_guessed():
    shape, r = song()
    with pytest.raises(ValueError, match="clutch"):
        director.plan([clip(f"one{i}", [3.5]) for i in range(10)], shape, r)


def test_studio_plans_it_and_the_timeline_agrees(tmp_path):
    """Through studio.plan and normalise: every kill on its mark, as derive() reads it."""
    shape, r = song()
    clips = library()
    for c in clips:
        p = tmp_path / Path(c["path"]).name
        p.write_bytes(b"x")
        c["path"] = str(p)
    shape.path = tmp_path / "song.m4a"
    shape.path.write_bytes(b"x")
    rhythm._MEMO.clear()
    orig = rhythm.for_song
    rhythm.for_song = lambda sh, cache_dir=None: r
    try:
        proj, notes = studio.plan(clips, "montage", shape=shape, song=str(shape.path), fmt="vertical",
                                  shape_it={"arrange": "sections"})
    finally:
        rhythm.for_song = orig
    assert proj["arrange"] == "sections"
    assert proj["song_drop"] == pytest.approx(DROP)
    got, derived, _ = studio.normalise(proj, tmp_path, probe=lambda p: 12.0)
    assert derived["on_marks"] == len(got["shots"])
