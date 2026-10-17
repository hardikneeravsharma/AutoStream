r"""Shots locked together on the timeline survive the server's whitelist, and a lock that
no longer joins two shots side by side is dropped (studio.tidy_locks)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import studio


def _shots(locks):
    return [{"lock": lk} if lk else {} for lk in locks]


def test_a_run_of_two_or_more_is_kept():
    s = _shots(["", "a", "a", "a", ""])
    studio.tidy_locks(s)
    assert [x.get("lock", "") for x in s] == ["", "a", "a", "a", ""]


def test_a_single_locked_shot_is_not_a_lock():
    s = _shots(["", "a", "", "b", "b"])
    studio.tidy_locks(s)
    assert [x.get("lock", "") for x in s] == ["", "", "", "b", "b"]


def test_a_shot_moved_out_of_its_run_leaves_it():
    """Shot 3 of a run dragged to the front: the first span is one shot, the run keeps the rest."""
    s = _shots(["a", "", "a", "a"])
    studio.tidy_locks(s)
    assert [x.get("lock", "") for x in s] == ["", "", "a", "a"]


def test_one_id_in_two_runs_keeps_the_first():
    s = _shots(["a", "a", "", "a", "a"])
    studio.tidy_locks(s)
    assert [x.get("lock", "") for x in s] == ["a", "a", "", "", ""]


def test_a_lock_rides_through_normalise(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_studio as T

    r = tmp_path / "clips"
    T._run(r, "2026-09-01_1200_VALORANT", "VALORANT",
           [{"start": 100.0 * i, "end": 100.0 * i + 12} for i in range(1, 7)],
           kills=[100.0 * i + 6 for i in range(1, 7)])
    proj, _ = studio.plan(T._clips(r), "montage", shape=T.Shape(bpm=120.0))
    for s in proj["shots"][1:3]:
        s["lock"] = "L1"
    proj["shots"][-1]["lock"] = "bad id!"
    got, _derived, _notes = studio.normalise(proj, r, probe=lambda p: 12.0)
    assert [s.get("lock", "") for s in got["shots"]][:3] == ["", "L1", "L1"]
    assert "lock" not in got["shots"][-1]
