"""A PICKED PART IS FILLED FROM THE CLIPS CHOSEN, AND FROM THE MARKS PLACED ON IT.

Yeat on Velocity, 2026-10-25: 20 clips of three fights each on a 15 s part planned 7 shots
from 4 clips. The count was settled on the walk's compact length although a filled part's
kills are spread over all of it, and a clip's fights are one group taken whole, so a few
clips filled the reel. With kills marked by hand the planner laid its own slots, from its
own 4.5 s opener, cut the shots that ran past the part, and the reel came out 12 s.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import webui                                            # noqa: E402
from autostream.clips import rhythm, studio                             # noqa: E402

from test_director import clip, song, DROP                              # noqa: E402

PART = (DROP - 6.0, DROP + 9.0)


@pytest.fixture
def srv(monkeypatch, tmp_path):
    shape, r = song()
    shape.hits = list(shape.beats[::2])          # a bass hit every other beat, as real songs read
    # three fights each, seconds apart: what a clip cut around a round holds
    lib = [clip(f"tri{i}", [2.0, 7.0 + (i % 3), 12.0], seconds=16.0) for i in range(20)]
    for c in lib:
        p = tmp_path / Path(c["path"]).name
        p.write_bytes(b"x")
        c["path"] = str(p)
    shape.path = tmp_path / "song.m4a"
    shape.path.write_bytes(b"x")
    by = {c["path"]: c for c in lib}
    s = webui.Server.__new__(webui.Server)
    monkeypatch.setattr(webui.cfg, "load", lambda: SimpleNamespace(clips=SimpleNamespace(ffmpeg_path=None)))
    monkeypatch.setattr(webui.Server, "_clips_dir", staticmethod(lambda c: tmp_path))
    monkeypatch.setattr(s, "_studio_shape", lambda song: shape, raising=False)
    monkeypatch.setattr(s, "_studio_chosen", lambda root, want: [dict(by[p]) for p in want if p in by],
                        raising=False)
    monkeypatch.setattr(rhythm, "for_song", lambda sh, cache_dir=None: r)
    real = studio.normalise
    monkeypatch.setattr(studio, "normalise", lambda p, root, probe=None: real(p, root, probe=lambda x: 16.0))
    s.lib, s.song, s.shape = lib, str(shape.path), shape
    return s


def plan(srv, **extra):
    b = {"style": "velocity", "song": srv.song, "clips": [c["path"] for c in srv.lib], "format": "vertical",
         "part_start": PART[0], "part_end": PART[1], "shaping": {"fill": "part"}, "dry": True, **extra}
    got = srv.studio_plan(b)
    assert got["ok"], got
    return got["project"], got["derived"]


def test_a_picked_part_takes_a_shot_from_many_clips_not_every_fight_of_a_few(srv):
    proj, derived = plan(srv)
    used = {s["clip"] for s in proj["shots"]}
    assert len(proj["shots"]) >= 10, len(proj["shots"])
    assert len(used) == len(proj["shots"]), "no clip gives a second shot while chosen clips sit out"
    assert derived["length"] >= PART[1] - PART[0] - 1.0


def test_marks_placed_by_hand_are_the_slots_and_the_part_stays_full(srv):
    hits = [t for t in srv.shape.hits if PART[0] + 1.0 <= t <= PART[1] - 1.5]
    marks = [hits[round(i * (len(hits) - 1) / 11)] for i in range(12)]      # across the whole part
    proj, derived = plan(srv, marks=marks)
    assert proj["song_marks"] == pytest.approx(sorted(marks), abs=1e-3), "only the player's marks, none added"
    assert len(proj["shots"]) >= len(marks) - 3
    assert float(proj["song_offset"]) + derived["length"] >= marks[-1], "the reel runs on to the last mark"
