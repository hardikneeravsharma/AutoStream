"""Marvel Rivals match summaries: the planner, on readings built by hand.

No footage here -- the reader's numbers were measured on real recordings with
the harness scripts, and what is pinned below is what the PLANNER does with
readings of the shapes those recordings produce: a match opening on a setup
countdown, a death under a dimmed HUD, an ult, and a VICTORY screen.
"""
from __future__ import annotations

import numpy as np
import pytest

from autostream.clips import profiles, rivals, summary

FPS = rivals.FPS


def build(seconds: float, spec) -> rivals.Readings:
    """Readings sampled at FPS; `spec(t)` returns the fields that differ from
    'in a match, alive, full HUD, ult flat at 0'."""
    t = np.arange(0, seconds, 1 / FPS)
    rows = {k: [] for k in rivals.Readings.__dataclass_fields__ if k != "t"}
    for x in t:
        v = dict(bullet=True, ult_ncc=0.9, hp_ncc=0.9, tc_ncc=0.7, ult=0,
                 ready=0.0, hpfrac=1.0, green=0.0, red=0.0, tall=0,
                 tl_yellow=0.0, line=np.zeros(201, np.uint8))
        v.update(spec(float(x)))
        for k in rows:
            rows[k].append(v[k])
    return rivals.Readings(
        t=t, bullet=np.array(rows["bullet"], bool),
        ult_ncc=np.array(rows["ult_ncc"], np.float32),
        hp_ncc=np.array(rows["hp_ncc"], np.float32),
        tc_ncc=np.array(rows["tc_ncc"], np.float32),
        ult=np.array(rows["ult"], np.int16),
        ready=np.array(rows["ready"], np.float32),
        hpfrac=np.array(rows["hpfrac"], np.float32),
        green=np.array(rows["green"], np.float32),
        red=np.array(rows["red"], np.float32),
        tall=np.array(rows["tall"], np.int16),
        tl_yellow=np.array(rows["tl_yellow"], np.float32),
        line=np.stack(rows["line"]))


MENU = dict(bullet=False, ult_ncc=0.0, hp_ncc=0.0, tc_ncc=0.0, ult=-1)


def one_match(x: float) -> dict:
    """Menus to 60 s; a match 60-500 s; VICTORY from 512 s."""
    if x < 60 or x > 500:
        out = dict(MENU)
        if 512 <= x <= 545:
            out.update(tall=30, tl_yellow=0.19)
        return out
    if x < 120:                                  # setup: in spawn, nothing moves
        return dict(ult=0)
    if 200 <= x < 210:                           # dead: square gone, HUD dimmed
        return dict(bullet=False, ult_ncc=0.45, hp_ncc=0.5, ult=-1)
    if x < 200:
        return dict(ult=int((x - 120) // 2))     # fighting: the meter climbs
    if x < 240:
        return dict(ult=40)                      # the walk back: flat
    if x < 300:
        return dict(ult=min(99, 40 + int((x - 240))))
    if x < 320:
        return dict(ult=-1, ready=0.18)          # ult ready
    return dict(ult=5 + int((x - 320) // 3))     # ...and used


def test_finds_the_match_its_death_its_ult_and_its_result():
    r = build(600, one_match)
    ms = rivals.matches(r)
    assert len(ms) == 1
    m = ms[0]
    assert m.start == pytest.approx(60, abs=1)
    assert m.end == pytest.approx(500, abs=1)
    assert [(round(a), round(b)) for a, b in m.deaths] == [(200, 210)]
    assert [round(c) for c in m.casts] == [320]
    assert m.result == "victory"
    assert m.result_at == pytest.approx(512, abs=1)


def test_the_plan_cuts_the_setup_and_the_death_and_keeps_the_fights():
    r = build(600, one_match)
    m = rivals.matches(r)[0]
    spans = rivals.plan(r, m)
    kept = lambda at: any(a <= at <= b for a, b in spans)  # noqa: E731
    # The first seconds of the match stay; the setup after them does not.
    assert kept(61)
    assert not kept(90)
    # The fight is detected at 124 (the meter rising) and opens LEAD earlier.
    assert kept(122) and kept(150)
    # A death keeps what killed you, then the spectating and the walk go.
    assert kept(201) and not kept(215) and not kept(230)
    assert kept(245)
    # The ult, the end of the match and the result screen all stay.
    assert kept(320) and kept(499) and kept(514)
    assert not kept(530)


def test_an_ult_is_never_cut_into():
    def spec(x):
        s = one_match(x)
        # Ult ready on the walk back, and used there -- nothing else stirs.
        if 212 <= x < 216:
            s.update(ult=-1, ready=0.18)
        if 216 <= x < 240:
            s.update(ult=3)
        return s
    r = build(600, spec)
    m = rivals.matches(r)[0]
    assert [round(c) for c in m.casts] == [216, 320]
    spans = rivals.plan(r, m)
    assert any(a <= 216 <= b for a, b in spans)
    assert not any(a <= 205 <= b for a, b in spans)


def test_the_practice_range_is_not_a_match():
    # The full HUD, but no progress bar at the top.
    r = build(600, lambda x: {"tc_ncc": 0.0})
    assert rivals.matches(r) == []


def test_a_few_minutes_of_hud_is_not_a_match():
    r = build(400, lambda x: {} if 100 <= x < 200 else dict(MENU))
    assert rivals.matches(r) == []


def test_two_matches_with_menus_between_are_two():
    def spec(x):
        if 50 <= x < 300 or 450 <= x < 700:
            return {"ult": int(x // 3) % 90}
        return dict(MENU)
    r = build(800, spec)
    assert len(rivals.matches(r)) == 2


def test_no_hud_means_no_summary():
    r = build(300, lambda x: dict(MENU))
    assert not rivals.hud_found(r)
    assert rivals.hud_found(build(300, lambda x: {}))


def test_chapters_follow_the_cut():
    m = rivals.Match(start=0, end=300, phases=[150.0], result="defeat",
                     result_at=320.0)
    spans = [(0.0, 100.0), (160.0, 310.0), (320.0, 326.0)]
    # A phase that began inside a cut starts where the summary resumes.
    assert rivals.to_output(spans, 150.0) == 100.0
    assert rivals.to_output(spans, 200.0) == 140.0
    assert rivals.chapters(spans, m) == [
        (0.0, "Match start"), (100.0, "Objective 2"), (250.0, "Defeat")]
    assert summary.chapter_text(rivals.chapters(spans, m)) == (
        "0:00 Match start\n1:40 Objective 2\n4:10 Defeat\n")


def test_chapters_closer_than_ten_seconds_are_dropped():
    m = rivals.Match(start=0, end=300, phases=[5.0])
    assert rivals.chapters([(0.0, 300.0)], m) == [(0.0, "Match start")]


def test_a_blank_frame_reads_as_nothing():
    img = np.zeros((rivals.FRAME_H, rivals.W, 3), np.uint8)
    got = rivals.read_frame(img)
    assert got[0] is False          # no objective square
    assert got[4] == -1             # no ult reading
    assert got[1] < rivals.HUD_ULT_PART


def test_readings_survive_a_round_trip(tmp_path):
    r = build(30, lambda x: {})
    r.save(tmp_path / "r.npz")
    back = rivals.Readings.load(tmp_path / "r.npz")
    assert len(back) == len(r)
    assert (back.line == r.line).all()


def test_marvel_rivals_is_summarised_and_needs_nothing():
    p = profiles.for_game("Marvel-Win64-Shipping.exe", "Marvel Rivals")
    assert p is not None and p.mode == "summary"
    assert p.exists() and not p.missing() and not p.needs_ocr
    assert p.as_dict()["mode"] == "summary"


def test_the_references_ship_with_the_app():
    ref = rivals.refs()
    assert ref["digits"].shape == (10, rivals.GLYPH_H, rivals.GLYPH_W)
    for k in ("ult", "hp", "tc"):
        assert np.isfinite(ref[k]).all() and ref[k].std() > 0.5


def test_a_clip_job_for_marvel_rivals_makes_summaries(tmp_path, monkeypatch):
    """The job takes the summary path: no kill scan, one result per match."""
    from autostream.clips import cutter, jobs

    src = tmp_path / "rec.mp4"
    src.write_bytes(b"not really a video")
    monkeypatch.setattr(cutter, "probe_source", lambda p: {"duration": 600.0})
    monkeypatch.setattr(rivals, "scan", lambda *a, **k: build(600, one_match))
    cut = []

    def fake_master(source, spans, name, outdir, **kw):
        outdir.mkdir(parents=True, exist_ok=True)
        cut.append(spans)
        out = outdir / f"{name}.mp4"
        out.write_bytes(b"")
        return out
    monkeypatch.setattr(cutter, "master_segments", fake_master)

    job = jobs.ClipJob(src, game="Marvel Rivals",
                       game_key="marvel-win64-shipping.exe",
                       outdir=tmp_path / "out", options={})
    job.run()
    assert job.state == "done", job.error
    assert len(job.results) == 1 and len(cut) == 1
    got = job.results[0]
    assert got["result"] == "victory" and got["deaths"] == 1 and got["ults"] == 1
    assert "summar" in job.message
    assert (job.folder / "readings.npz").is_file()
    assert (job.folder / "summaries" / f"{got['name']}.chapters.txt").is_file()


def test_review_is_refused_for_a_summary(tmp_path, monkeypatch):
    from autostream.clips import cutter, jobs

    src = tmp_path / "rec.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(cutter, "probe_source", lambda p: {"duration": 600.0})
    job = jobs.ClipJob(src, game="Marvel Rivals",
                       game_key="marvel-win64-shipping.exe",
                       outdir=tmp_path / "out", options={"plan_only": True})
    job.run()
    assert job.state == "failed" and "no clips to review" in job.error
