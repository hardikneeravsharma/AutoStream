"""F14: the camera across the cuts -- the measure, and what the planner does with it.

The measure is checked against a picture moved by a known amount; the planner against
the invariants ChatGPT set (2026-11-01): kills stay on their beats, a clip plays once,
a shot is only ever swapped for one exactly as good, unknown motion changes nothing,
and the reversing cuts never go up.
"""
from __future__ import annotations

import numpy as np
import pytest

from autostream.clips import director, motion

from test_director import DROP, clip, song


def _pan(px_per_frame: float, n: int = 8) -> dict:
    rng = np.random.default_rng(4)
    world = rng.random((motion.H, motion.W + 200)).astype(np.float32) * 255
    k = np.ones(5) / 5
    world = np.apply_along_axis(lambda r: np.convolve(r, k, "same"), 1, world)
    world = np.apply_along_axis(lambda c: np.convolve(c, k, "same"), 0, world)
    frames = [world[:, int(100 + px_per_frame * i): int(100 + px_per_frame * i) + motion.W] for i in range(n)]
    bands = [motion._band(f) for f in frames]
    pairs = [motion._shift(a, b) for a, b in zip(bands, bands[1:])]
    return {"start": 0.0, "fps": motion.FPS, "width": motion.W,
            "dx": [p[0] for p in pairs], "conf": [p[1] for p in pairs]}


def test_a_camera_turning_right_moves_the_picture_left():
    tr = _pan(3)
    assert all(abs(d + 3) < 0.1 for d in tr["dx"]), tr["dx"]
    assert min(tr["conf"]) > motion.PEAK_MIN
    assert motion.direction(tr, 0.0, motion.WINDOW) == -1
    assert motion.direction(_pan(-3), 0.0, motion.WINDOW) == 1


def test_too_little_movement_is_unknown_not_a_direction():
    # 0.2 px a frame over five pairs is 1 px of 192: half the 1 % that counts as moving
    assert motion.direction(_pan(0), 0.0, motion.WINDOW) == 0
    tr = {"start": 0.0, "fps": motion.FPS, "width": motion.W, "dx": [0.2] * 5, "conf": [0.9] * 5}
    assert motion.direction(tr, 0.0, motion.WINDOW) == 0
    # ...and so is a window the track does not reach, or no track at all
    assert motion.direction(tr, 10.0, 10.25) == 0 and motion.direction(None, 0, 1) == 0


def test_disagreeing_pairs_are_unknown():
    tr = {"start": 0.0, "fps": motion.FPS, "width": motion.W,
          "dx": [6, -5, 6, -5, -5, 6], "conf": [0.9] * 6}
    assert motion.direction(tr, 0.0, 0.30) == 0          # 3 of 6 agree: under 60 %


def test_a_cut_costs_only_when_both_sides_move():
    assert motion.cut_cost(1, -1) == 1.0 and motion.cut_cost(-1, 1) == 1.0
    assert motion.cut_cost(1, 1) < 0 and motion.cut_cost(-1, -1) < 0
    assert motion.cut_cost(0, 1) == motion.cut_cost(1, 0) == motion.cut_cost(0, 0) == 0.0


class _Look:
    """A motion.Cache stand-in: every clip moves one way all the way through."""

    def __init__(self, ways):
        self.ways, self.asked = ways, []

    def prefetch(self, pairs, budget=0):
        self.asked += list(pairs)
        return len(pairs)

    def direction(self, path, kill, t0, t1):
        return self.ways.get(path, 0)


def _lib():
    out = [clip("clutch", [3.5, 5.0, 7.2], labels=["CLUTCH 1v3"], seconds=12.0)]
    out += [clip(f"one{i}", [3.5], hs=[True]) for i in range(40)]
    return out


def _plan(look):
    shape, r = song()
    tok = director.MOTION.set(look)
    try:
        return director.plan(_lib(), shape, r, seed=3)
    finally:
        director.MOTION.reset(tok)


def _cost(p, ways):
    fl = [s for s in p.shots if s["name"] != "clutch"]
    d = [ways.get(s["clip"], 0) for s in fl]
    return sum(motion.cut_cost(a, b) for a, b in zip(d, d[1:]))


def test_the_flurry_keeps_the_camera_moving_where_it_can():
    # Half the clips swing right, half left: a plan made by score alone alternates freely.
    ways = {f"C:/clips/one{i}.mp4": (1 if i % 2 else -1) for i in range(40)}
    plain = _plan(None)
    moved = _plan(_Look(ways))
    assert _cost(moved, ways) < _cost(plain, ways), (_cost(plain, ways), _cost(moved, ways))
    # the invariants: every kill where it was, no clip twice, nothing worse swapped in
    assert moved.marks == plain.marks and moved.kills == plain.kills
    fl = [s["clip"] for s in moved.shots if s["name"] != "clutch"]
    assert len(set(fl)) == len(fl)
    assert len(moved.shots) == len(plain.shots)


def test_a_shot_is_only_swapped_for_one_exactly_as_good():
    lib = _lib()
    for i, c in enumerate(lib[1:]):
        c["hs"] = [i % 3 != 0]                     # two score classes
    shape, r = song()
    ways = {c["path"]: (1 if i % 2 else -1) for i, c in enumerate(lib)}
    plain = director.plan(lib, shape, r, seed=3)
    tok = director.MOTION.set(_Look(ways))
    try:
        moved = director.plan(lib, shape, r, seed=3)
    finally:
        director.MOTION.reset(tok)
    hs = {c["path"]: c["hs"][0] for c in lib}
    assert [hs[s["clip"]] for s in plain.shots] == [hs[s["clip"]] for s in moved.shots]


def test_unknown_motion_changes_nothing():
    plain = _plan(None)
    moved = _plan(_Look({}))
    assert [s["clip"] for s in moved.shots] == [s["clip"] for s in plain.shots]


def test_a_dry_plan_never_reads_motion(monkeypatch):
    """The feasibility chip plans dry and must answer in about a second."""
    from autostream.clips import studio

    made = []
    monkeypatch.setattr(motion, "Cache", lambda *a, **k: made.append(a) or _Look({}))
    shape, r = song()
    from autostream.clips import rhythm
    monkeypatch.setattr(rhythm, "for_song", lambda s: r)
    chosen = {c["path"]: c for c in _lib()}
    try:
        studio._plan_sections(list(chosen.values()), "drop", shape=shape, song="song.m4a", part=None,
                              seed=1, checks=False, confirm=None, theirs=None, refine=None, shape_it={})
    except Exception:  # noqa: BLE001 - only whether a cache was made matters here
        pass
    assert made == []


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_reversing_cuts_never_go_up(seed):
    rng = np.random.default_rng(seed)
    ways = {f"C:/clips/one{i}.mp4": int(rng.choice([-1, 0, 1])) for i in range(40)}
    shape, r = song()
    plain = director.plan(_lib(), shape, r, seed=seed)
    tok = director.MOTION.set(_Look(ways))
    try:
        moved = director.plan(_lib(), shape, r, seed=seed)
    finally:
        director.MOTION.reset(tok)
    assert _cost(moved, ways) <= _cost(plain, ways)
    assert moved.marks == plain.marks
    assert DROP in [round(m, 4) for m in moved.marks] or moved.drop == plain.drop
