"""The game's own kill emblem as the truth about when -- and whether -- a kill happened.

The numbers in the docstrings are from one 70-minute Valorant recording whose
clips the player checked by eye. No ffmpeg here: frames and score traces are
built in memory.
"""
from __future__ import annotations

import numpy as np
import pytest

from autostream.clips import jobs, killmark, studio


def _frames(n: int, ring_from: int | None = None, ring_to: int | None = None, seed: int = 1):
    """n frames of the emblem region: a busy random world, with a ring drawn over it in [from, to)."""
    rng = np.random.default_rng(seed)
    h = int(round(killmark.REGION_WIDTH * 0.155 * 9 / 16 / 0.09))
    W = killmark.REGION_WIDTH
    out = rng.uniform(40, 200, (n, h, W)).astype(np.float32)
    out = (out + np.roll(out, 1, axis=2) + np.roll(out, 1, axis=1)) / 3     # a little texture, not pure noise
    yy, xx = np.mgrid[0:h, 0:W]
    r = np.hypot(xx - W * 0.5, yy - h * 0.55)
    ring = (np.abs(r - W * 0.33) < 2.5)
    if ring_from is not None:
        out[ring_from:ring_to, ring] = 250.0
    return out


def test_a_ring_reads_as_an_emblem_and_the_world_does_not():
    fr = _frames(20, ring_from=10, ring_to=20)
    s = killmark.ring_scores(fr)
    assert s[:10].max() < killmark.BASE
    assert s[10:].min() > killmark.ON


def test_an_emblem_is_found_where_it_rises_and_a_flicker_is_not():
    fps = 30
    s = np.full(300, 0.15)
    s[60:112] = 0.52          # 1.73 s: a real emblem, rising at 2.0 s
    s[57:60] = 0.30           # its grow-in
    s[200:203] = 0.5          # a tenth of a second: a flash, not an emblem
    got = killmark.onsets(s, fps)
    assert got == [pytest.approx(1.9, abs=0.05)]


def test_late_kills_move_onto_their_emblems():
    """The feed reader was a median 0.30 s late against the emblems (p90 0.77 s)."""
    kills, dropped, added = killmark.confirm([2.0, 5.0, 13.0], [1.867, 4.967, 12.333])
    assert kills == [1.867, 4.967, 12.333] and dropped == 0 and added == 0


def test_a_kill_with_no_emblem_is_not_a_kill():
    """Clip 06 claimed three kills; the player saw one, and one emblem showed -- 2 s before the feed's last."""
    kills, dropped, added = killmark.confirm([3.5, 5.0, 12.5], [10.27])
    assert kills == [10.27] and dropped == 3 and added == 1


def test_a_clip_with_no_emblem_has_no_kill_but_no_reading_keeps_them():
    """Clips 14 and 35 claimed kills; the player saw none (a map opened, a death)."""
    assert killmark.confirm([3.5, 7.25], []) == ([], 2, 0)
    assert killmark.confirm([3.5, 7.25], None) == ([3.5, 7.25], 0, 0)


def test_an_emblem_seen_while_spectating_is_a_team_mates_and_not_added():
    """8 of the 19 emblems no feed kill claimed rose while the player watched a team-mate."""
    kills, dropped, added = killmark.confirm([5.0], [4.9, 20.0, 40.0], theirs=lambda t: t == 20.0)
    assert kills == [4.9, 40.0] and dropped == 0 and added == 1


def _card(rule: bool, glow: bool = False, seed: int = 3):
    """The spectator-card crop: a textured world, the card's thin left rule, or a glow down the whole edge."""
    rng = np.random.default_rng(seed)
    a = rng.uniform(60, 120, (killmark.CARD_H, killmark.CARD_W)).astype(np.float32)
    sp = killmark.spec_for("VALORANT")
    top = sp.card_above[0]
    r0 = int(round((sp.card[2] - top) / (sp.card[3] - top) * killmark.CARD_H))
    if rule:
        a[r0:, 17] = 235.0
    if glow:
        a[:, 18] = 235.0
    return a


def test_the_card_rule_is_read_and_a_glow_down_the_screen_edge_is_not_a_card():
    """The one real kill the rule alone flagged had a glow down the whole left edge."""
    sp = killmark.spec_for("VALORANT")
    rule, above = killmark.card_rule(_card(rule=True), sp)
    assert rule > killmark.CARD_ON and above < killmark.CARD_ON
    rule, above = killmark.card_rule(_card(rule=False), sp)
    assert rule < killmark.CARD_ON
    rule, above = killmark.card_rule(_card(rule=False, glow=True), sp)
    assert rule > killmark.CARD_ON and above > killmark.CARD_ON


def test_each_emblem_claims_one_kill():
    got, unclaimed = killmark.match([3.5, 3.5, 4.0], [4.1])
    assert list(got.items()) == [(2, 0)] and unclaimed == []


def test_only_games_that_draw_an_emblem_are_checked():
    assert killmark.spec_for("VALORANT") is not None
    assert killmark.spec_for("Counter-Strike 2") is None


# ------------------------------------------------------------------ the clip job

class _Job(jobs.ClipJob):
    def __init__(self, tmp_path):                 # no folder, no source: just the method
        self.game = "VALORANT"
        self.source = tmp_path / "rec.mp4"
        self.win_start, self.win_end = 0.0, 600.0
        self.emblem_note = {}
        import threading
        self._cancel = threading.Event()
        self.state = {}

    def _set(self, **kw):
        self.state.update(kw)


def test_the_job_keeps_round_context_and_marks_kills_confirmed(tmp_path, monkeypatch):
    monkeypatch.setattr(killmark, "scan", lambda *a, **k: [99.7, 250.0, 300.0])
    monkeypatch.setattr(killmark, "spectating", lambda video, t, game, ff: t == 300.0)
    job = _Job(tmp_path)
    kills = [{"time": 100.0, "end": 100.0, "score": 1.0, "count": 1, "round": 4},
             {"time": 180.0, "end": 180.0, "score": 1.0, "count": 1}]
    got = job._confirm_by_emblem(kills)
    assert [k["time"] for k in got] == [99.7, 250.0]
    assert got[0]["round"] == 4 and all(k["emblem"] for k in got)
    assert job.emblem_note == {"emblems": 3, "confirmed": 1, "dropped": 1, "added": 1,
                               "spectating": 1}


def test_the_job_never_moves_a_record_kill_and_reads_only_what_no_record_covers(tmp_path, monkeypatch):
    """Two record kills 0.5 s apart -- the start of a 1v4 clutch -- share one emblem.
    Checked against it, the second was dropped."""
    scanned = []

    def scan(video, game, start=0.0, duration=0.0, **k):
        scanned.append((start, start + duration))
        return [x for x in (50.0, 3468.33) if start <= x <= start + duration]
    monkeypatch.setattr(killmark, "scan", scan)
    monkeypatch.setattr(killmark, "spectating", lambda *a: False)
    job = _Job(tmp_path)
    job.win_start, job.win_end = 0.0, 4000.0
    job.record_spans = [(1800.0, 3900.0)]
    kills = [{"time": 3468.23, "record": True, "count": 1}, {"time": 3468.7, "record": True, "count": 1},
             {"time": 50.4, "count": 1}]
    got = job._confirm_by_emblem(kills)
    assert [k["time"] for k in got] == [50.0, 3468.23, 3468.7]
    assert scanned == [(0.0, 1795.0), (3905.0, 4000.0)]


def test_confirmed_kills_are_not_read_again_and_a_hidden_hud_keeps_them(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(killmark, "scan", lambda *a, **k: calls.append(1) or [])
    job = _Job(tmp_path)
    done = [{"time": 5.0, "end": 5.0, "count": 1, "emblem": True}]
    assert job._confirm_by_emblem(done) == done and not calls
    raw = [{"time": 5.0, "end": 5.0, "count": 1}]
    assert job._confirm_by_emblem(raw) == raw and calls


# ------------------------------------------------------------------ the studio

def test_the_studio_judges_a_missing_emblem_per_run(tmp_path):
    def clip(run, name, kills):
        p = tmp_path / run / "clips" / f"{name}.mp4"
        return {"path": str(p), "game": "VALORANT", "kills": kills, "kill_count": len(kills)}
    shown = [clip("runA", "a", [3.5]), clip("runA", "b", [3.5])]
    hidden = [clip("runB", "c", [3.5])]
    marks = {"a": [3.2], "b": [], "c": []}
    got, moved, dropped, added = studio._confirm_kills(
        shown + hidden, lambda path, game: marks[path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1][:-4]])
    names = [c["path"][-5:-4] for c in got]
    assert names == ["a", "c"]                    # b had no kill; runB shows no emblem at all
    assert got[0]["kills"] == [3.2] and moved == 1 and dropped == 1


def test_the_studio_leaves_a_clip_cut_from_the_match_record_alone(tmp_path):
    rec = {"path": str(tmp_path / "run" / "clips" / "r.mp4"), "game": "VALORANT",
           "kills": [3.73, 4.2], "kill_count": 2, "recorded": True}
    other = {"path": str(tmp_path / "run" / "clips" / "s.mp4"), "game": "VALORANT",
             "kills": [3.5], "kill_count": 1}
    asked = []

    def confirm(path, game):
        asked.append(path)
        return [3.83, 9.0]
    got, moved, dropped, added = studio._confirm_kills(
        [rec, other], confirm, theirs=lambda path, game, t: t == 9.0)
    assert got[0]["kills"] == [3.73, 4.2] and asked == [other["path"]]
    assert got[1]["kills"] == [3.83] and added == 0       # 9.0 was a team-mate's


def test_the_library_marks_clips_cut_from_the_record(tmp_path):
    import json
    run = tmp_path / "2026-09-15_VALORANT"
    (run / "clips").mkdir(parents=True)
    for n in ("a", "b"):
        (run / "clips" / f"{n}.mp4").write_bytes(b"x")
    (run / "clips.json").write_text(json.dumps({"game": "VALORANT", "clips": [
        {"rank": 1, "start": 3464.7, "end": 3498.0, "kills": 2, "master": str(run / "clips" / "a.mp4")},
        {"rank": 2, "start": 500.0, "end": 510.0, "kills": 1, "master": str(run / "clips" / "b.mp4")}]}))
    (run / "session.json").write_text(json.dumps({"kills": [
        {"time": 3468.23, "record": True}, {"time": 3468.7, "record": True}, {"time": 505.0}]}))
    clips = studio.library(tmp_path)["games"][0]["folders"][0]["clips"]
    assert clips[0].get("recorded") is True and not clips[1].get("recorded")
