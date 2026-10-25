"""The dependency table, the timing draft and "keep my shots, re-time them" (clips/editflow.py).

The bug these exist for: on the Song tab the part was dragged from 0:00-0:44
to 0:59-2:07, every kill mark kept its offset from the part's start, none sat
on the new section's beats, and Render rendered the old timing as the new.
The browser half is tests/verify/test_ui_studio_timing.py; this is the rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from autostream.clips import editflow, studio


@dataclass
class Shape:
    bpm: float = 120.0
    seconds: float = 180.0
    phase: float = 0.0
    drop: float | None = None
    drops: list = field(default_factory=list)
    beats: list = field(default_factory=list)
    hits: list = field(default_factory=list)

    @property
    def beat(self) -> float:
        return 60.0 / self.bpm

    def __post_init__(self):
        if not self.beats:
            n = int((self.seconds - self.phase) / self.beat)
            self.beats = [round(self.phase + i * self.beat, 4) for i in range(n)]


def _shot(i: int, **over) -> dict:
    s = {"clip": f"C:/clips/c{i}.mp4", "clip_id": f"c{i}", "name": f"c{i}", "clip_seconds": 20.0,
         "clip_mtime": 0, "kill": 10.0, "kills": [10.0], "pre": 1.0, "duration": 2.0, "speed": "s00",
         "fx": [], "hero": False, "hero_fx": [], "camera": "c00", "transition": "t01", "tlen": 0.0,
         "caption": ""}
    s.update(over)
    return s


def _reel(n: int = 8, *, start: float = 0.0, beat: float = 0.5, **over) -> dict:
    """`n` two-second shots, each kill a second in: kills every 4 beats from start + 1 s."""
    p = {"version": 1, "name": "r", "style": "montage", "format": "landscape", "song": "C:/song.wav",
         "song_offset": start, "part_end": start + 2.0 * n, "beat": beat, "step": beat,
         "shots": [_shot(i) for i in range(n)], "song_marks": [round(start + 1.0 + 2.0 * i, 4) for i in range(n)]}
    p.update(over)
    return p


# ------------------------------------------------------------------ the table

def test_every_change_in_the_brief_has_its_default_action():
    want = {"style": "replan", "part": "retime", "drop": "replan", "mark": "retime", "kills_now": "retime",
            "clips": "replan", "replace": "retime", "trim": "timeline", "look": "rerender",
            "framing": "rerender", "lyrics": "rerender", "intro": "timeline", "length": "replan",
            "fades": "rerender"}
    got = {c.key: c.action for c in editflow.CHANGES}
    assert got == want
    assert editflow.BY_KEY["part"].fallback == "replan" and editflow.BY_KEY["part"].offer == "replan"
    assert editflow.BY_KEY["replace"].fallback == "replan"
    assert editflow.BY_KEY["framing"].revalidate is True
    assert all(c.says for c in editflow.CHANGES), "every control says what it changes"


def test_every_action_says_what_it_keeps_and_what_it_changes():
    for key, a in editflow.ACTIONS.items():
        assert a["label"] and a["says"] and a["keeps"] and a["changes"], key
    assert set(editflow.ACTIONS) == set(editflow.STRENGTH)


def test_the_page_reads_the_same_table():
    t = editflow.table()
    assert [c["key"] for c in t["changes"]] == [c.key for c in editflow.CHANGES]
    assert t["actions"]["retime"]["says"] == "re-times your shots"
    assert studio.catalog() and "editflow" not in studio.catalog()   # added by the server route


def test_a_drop_only_needs_a_plan_in_a_style_built_on_it():
    assert editflow.action_for("drop", drop_style=True) == "replan"
    assert editflow.action_for("drop", drop_style=False) == "retime"
    assert editflow.action_for("part") == "retime"
    assert editflow.action_for("part", feasible=False) == "replan"
    assert editflow.action_for("look") == "rerender"


def test_classify_names_the_strongest_action():
    a = _reel()
    b = _reel()
    b["shots"][2]["fx"] = ["k03"]
    assert editflow.classify(a, b) == {"action": "rerender", "changes": ["look"]}
    b["draft"] = {"start": 59.0, "end": 127.0}
    got = editflow.classify(a, b)
    assert got["action"] == "retime" and set(got["changes"]) == {"look", "part"}
    b["style"] = "hype"
    assert editflow.classify(a, b)["action"] == "replan"
    c = _reel()
    c["shots"] = c["shots"][1:]
    assert editflow.classify(a, c)["action"] == "timeline"


# ------------------------------------------------------------------ the draft

def test_a_draft_that_says_what_the_plan_says_is_no_draft():
    p = _reel()
    assert editflow.tidy_draft({"start": 0.0, "end": 16.0}, p) is None
    assert editflow.tidy_draft({"marks": list(p["song_marks"])}, p) is None
    assert editflow.tidy_draft({"start": 59.0, "end": 127.0}, p) == {"start": 59.0, "end": 127.0}
    # the same length somewhere else is a change too
    assert editflow.tidy_draft({"start": 4.0, "end": 20.0}, p) == {"start": 4.0, "end": 20.0}


def test_a_draft_is_stale_and_cannot_be_rendered():
    p = _reel()
    assert editflow.stale(p) == [] and editflow.can_render(p) == ""
    p["draft"] = {"start": 59.0, "end": 127.0}
    assert editflow.stale(p) == ["part"]
    assert editflow.stale_text(p) == "Song part changed \u2014 kill timing needs updating"
    assert editflow.can_render(p).startswith("Song part changed")
    spec = editflow.timing_spec(p)
    assert (spec["start"], spec["end"]) == (59.0, 127.0)
    assert spec["marks"] == p["song_marks"], "the old marks stay where they are, at their song times"


def test_normalise_keeps_the_draft_and_the_hand_marks(tmp_path):
    root = tmp_path / "clips"
    clip = root / "run" / "clips" / "a.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"x")
    song = tmp_path / "song.wav"
    song.write_bytes(b"x")
    p = {"song": str(song), "song_offset": 0.0, "part_end": 16.0, "song_marks": [1.0, 3.0],
         "shots": [_shot(0, clip=str(clip))], "draft": {"start": 59.0, "end": 127.0, "song": "C:/nowhere.wav"},
         "anchors": [3.0]}
    got, _, _ = studio.normalise(p, root, probe=lambda _p: 20.0)
    assert got["draft"] == {"start": 59.0, "end": 127.0}, "a song not on disk is not a draft"
    assert got["anchors"] == [3.0]
    p["draft"] = {"start": 0.0, "end": 16.0}
    got, _, _ = studio.normalise(p, root, probe=lambda _p: 20.0)
    assert "draft" not in got


# ------------------------------------------------------------------ keep my shots, re-time them

def _retimed(p, shape, **kw):
    return editflow.retime(p, studio.derive(p), shape, **kw)


def test_moving_the_part_keeps_each_kill_on_its_beat_of_the_new_section():
    p = _reel(8)
    p["shots"][3]["fx"] = ["k03"]
    p["shots"][5]["caption"] = "ACE"
    p["draft"] = {"start": 59.0, "end": 127.0}
    shape = Shape(phase=0.25)                          # the new section's own beats, a quarter-second out
    got = _retimed(p, shape)
    assert got["conflicts"] == []
    new = got["project"]
    assert "draft" not in new
    assert new["song_offset"] == pytest.approx(59.0)
    assert [s["clip"] for s in new["shots"]] == [s["clip"] for s in p["shots"]], "same clips, same order"
    assert new["shots"][3]["fx"] == ["k03"] and new["shots"][5]["caption"] == "ACE"
    beats = set(shape.beats)
    used = new["song_marks"][:8]
    assert all(m in beats for m in used), used
    # each kill keeps its place in the rhythm: about the same number of beats into the part
    for i, m in enumerate(used):
        assert (m - 59.0) == pytest.approx(1.0 + 2.0 * i, abs=0.5 + 1e-6)
    assert got["room"] and got["room"]["marks"] > 0, "a much longer part says there is room for more"


def test_a_hand_mark_outside_the_new_part_is_never_moved_for_you():
    p = _reel(8, anchors=[5.0])
    p["draft"] = {"start": 59.0, "end": 127.0}
    got = _retimed(p, Shape())
    assert got["conflicts"] and got["conflicts"][0]["kind"] == "marks-outside"
    assert {f["fix"] for f in got["conflicts"][0]["fixes"]} == {"resnap", "forget-outside"}
    assert got["project"]["anchors"] == [5.0]
    # asked for, it moves with the part, onto the new section's grid
    got = _retimed(p, Shape(), resnap=True)
    assert got["conflicts"] == []
    assert got["project"]["anchors"] == [64.0]


def test_a_hand_mark_inside_the_part_holds_its_kill():
    p = _reel(8, anchors=[7.0])
    p["draft"] = {"start": 0.0, "end": 30.0}           # longer, same start
    got = _retimed(p, Shape())
    assert got["conflicts"] == []
    assert 7.0 in got["project"]["song_marks"]
    assert got["project"]["anchors"] == [7.0]


def test_a_shorter_part_leaves_out_unheld_shots_from_the_end_first():
    p = _reel(8)
    p["shots"][7]["lock"] = "a"                       # the closer is locked in place
    p["shots"][6]["lock"] = "a"
    p["draft"] = {"start": 0.0, "end": 12.0}
    got = _retimed(p, Shape())
    assert got["conflicts"] == []
    names = [s["name"] for s in got["project"]["shots"]]
    assert "c6" in names and "c7" in names, "a locked shot is never left out to make room"
    assert len(names) < 8 and got["dropped"]
    assert all(n not in names for n in got["dropped"])


def test_a_part_too_short_for_the_locked_shots_is_a_conflict_with_fixes():
    p = _reel(6)
    for s in p["shots"]:
        s["lock"] = "a"
    p["draft"] = {"start": 0.0, "end": 5.0}
    got = _retimed(p, Shape())
    assert [c["kind"] for c in got["conflicts"]] == ["too-short"]
    fixes = {f["fix"] for f in got["conflicts"][0]["fixes"]}
    assert {"longer-part", "relax:all"} <= fixes
    assert got["project"]["shots"] == p["shots"], "nothing is applied while it conflicts"
    # relaxed, it fits by leaving shots out -- never by speeding them up
    got = _retimed(p, Shape(), relax="all")
    assert got["conflicts"] == []
    assert all(s["speed"] == "s00" for s in got["project"]["shots"])


def test_only_the_marks_changed_lays_the_shots_on_the_players_list():
    p = _reel(4)
    p["draft"] = {"marks": [1.0, 3.0, 4.5, 6.5]}
    got = _retimed(p, Shape())
    assert got["conflicts"] == []
    d = studio.derive(got["project"])
    assert [round(r["kill_reel"], 2) for r in d["shots"]] == [1.0, 3.0, 4.5, 6.5]


def test_merge_anchors_never_moves_the_hand_mark():
    got = editflow.merge_anchors([1.0, 3.0, 5.0], [3.2, 9.0, 40.0], start=0, end=10, beat=0.5)
    assert got == [1.0, 3.2, 5.0, 9.0]


def test_a_drop_style_cannot_be_made_with_its_drop_outside_the_part():
    assert editflow.drop_conflict(False, None, 30.0, 0, 20) is None
    assert editflow.drop_conflict(True, None, 10.0, 0, 20) is None
    c = editflow.drop_conflict(True, None, 30.0, 0, 20)
    assert c["kind"] == "drop-outside"
    assert [f["fix"] for f in c["fixes"]] == ["move-to-drop", "mark-drop", "other-style"]
    c = editflow.drop_conflict(True, [], 30.0, 0, 20)
    assert [f["fix"] for f in c["fixes"]] == ["mark-drop", "other-style"]


# ------------------------------------------------------------------ replanning

def test_a_plan_diff_counts_what_the_player_decides_on():
    a, b = _reel(4), _reel(4)
    b["shots"][3] = _shot(9)
    b["song_offset"] = 0.5
    d = editflow.plan_diff(a, studio.derive(a), b, studio.derive(b))
    assert d["shots"] == [4, 4]
    assert d["clips_in"] == ["c9"] and d["clips_out"] == ["c3"]
    assert d["kills_moved"] == 3 and d["kills_new"] == 1 and d["kills_gone"] == 1


def test_carry_edits_keeps_a_shots_effects_only_in_the_same_style():
    a, b = _reel(3), _reel(3)
    a["shots"][1]["fx"] = ["k07"]
    assert editflow.carry_edits(a, b) == 1 and b["shots"][1]["fx"] == ["k07"]
    c = _reel(3, style="hype")
    assert editflow.carry_edits(a, c) == 0 and c["shots"][1]["fx"] == []


def test_a_replan_asks_for_everything_the_reel_asked_for():
    p = _reel(4, fill="part", keep_all=True, arrange="hits", hand_drops=[30.0], build_clip="C:/b.mp4",
              selection=[{"clip": "C:/clips/c0.mp4"}, {"clip": "C:/clips/c9.mp4"}],
              lyrics={"look": "pop"}, cam={"source": "none"})
    p["draft"] = {"start": 59.0, "end": 127.0, "marks": [60.0, 62.0]}
    req = editflow.replan_request(p, {"style": "hype"})
    assert req["style"] == "hype" and req["clips"] == ["C:/clips/c0.mp4", "C:/clips/c9.mp4"]
    assert (req["part_start"], req["part_end"]) == (59.0, 127.0)
    assert req["drops"] == [30.0] and req["marks"] == [60.0, 62.0]
    assert req["shaping"]["fill"] == "part" and req["shaping"]["keep_all"] is True
    assert req["shaping"]["arrange"] == "hits" and req["shaping"]["build_clip"] == "C:/b.mp4"
    assert req["keep"]["lyrics"] == {"look": "pop"}


def test_more_marks_than_kills_is_refused_and_a_picked_part_fills():
    from autostream.clips import editflow
    proj = {"song_offset": 10.0, "part_end": 25.0, "anchors": [11.0, 12.0, 13.0], "fill": "style", "shots": []}
    assert editflow.kills_short(proj, 3) == ""
    assert "3 kills" in editflow.can_render(proj, 2)
    assert editflow.can_render(proj) == ""
    proj["draft"] = {"start": 12.0, "end": 30.0}
    assert editflow.replan_request(proj)["shaping"]["fill"] == "part"


def test_retime_with_more_marks_than_shots_is_a_conflict_not_a_silent_cut():
    from types import SimpleNamespace
    from autostream.clips import editflow
    shots = [{"clip": f"c{i}.mp4", "duration": 1.0, "pre": 0.5, "name": f"s{i}"} for i in range(7)]
    marks = [10.0 + i for i in range(10)]
    proj = {"song": "s.wav", "song_offset": 10.0, "part_end": 25.0, "beat": 0.5, "shots": shots,
            "draft": {"marks": marks}}
    shape = SimpleNamespace(beat=0.5, seconds=60.0, beats=[0.5 * i for i in range(120)], hits=[], drop=None)
    rep = editflow.retime(proj, {"shots": [{"kill_reel": float(i)} for i in range(7)], "length": 7.0}, shape)
    assert [c["kind"] for c in rep["conflicts"]] == ["marks-more-than-shots"]
    assert proj["draft"]["marks"] == marks
