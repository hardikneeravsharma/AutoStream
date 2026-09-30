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
                 tl_yellow=0.0, line=np.zeros(201, np.uint8), own_rows=0,
                 motion=5.0, ko=False, ko_sig=np.zeros(rivals.KO_SIG, np.uint8))
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
        line=np.stack(rows["line"]),
        own_rows=np.array(rows["own_rows"], np.int8),
        motion=np.array(rows["motion"], np.float32),
        ko=np.array(rows["ko"], bool),
        ko_sig=np.stack(rows["ko_sig"]))


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
    # The full HUD, under the range's big title.
    r = build(600, lambda x: {"tall": 24})
    assert rivals.matches(r) == []


def test_domination_without_its_progress_bar_is_still_a_match():
    # Domination swaps the bar for a capture ring for minutes at a time.
    r = build(600, lambda x: {"tc_ncc": 0.05})
    assert len(rivals.matches(r)) == 1


def test_the_results_after_a_match_are_not_part_of_it():
    # The scoreboard leaves a partial HUD behind, without the objective square.
    def spec(x):
        if x >= 500:
            return dict(bullet=False, ult_ncc=0.5, hp_ncc=0.5)
        return {}
    m = rivals.matches(build(560, spec))[0]
    assert m.end == pytest.approx(499.5, abs=0.6)


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
    from autostream.clips import highlight
    made = []

    def fake_render(source, shots, m, out, **kw):
        made.append((shots, kw))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"")
        return out
    monkeypatch.setattr(highlight, "render", fake_render)

    job = jobs.ClipJob(src, game="Marvel Rivals",
                       game_key="marvel-win64-shipping.exe",
                       outdir=tmp_path / "out", options={})
    job.run()
    assert job.state == "done", job.error
    assert len(job.results) == 2 and len(cut) == 1 and len(made) == 1
    assert job.results[1]["kind"] == "highlight"
    assert made[0][1]["subtitle"].startswith("VICTORY")
    assert job.summary["matches"] == 1 and job.summary["highlights"] == 1
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


# ------------------------------------------------------------ kills, frozen

def with_kills(x: float) -> dict:
    """one_match, plus feed rows: kills at 150 and 152 (two rows), one at 280,
    and the white row of YOUR death at 202 -- which is not a kill."""
    s = one_match(x)
    if 150 <= x < 155:
        s["own_rows"] = 1
    if 152 <= x < 157:
        s["own_rows"] = 2
    if 157 <= x < 160:
        s["own_rows"] = 1
    if 202 <= x < 207:
        s["own_rows"] = 1
    if 280 <= x < 285:
        s["own_rows"] = 1
    return s


def test_kills_come_from_your_rows_in_the_feed_and_deaths_do_not_count():
    m = rivals.matches(build(600, with_kills))[0]
    assert [round(k) for k in m.kills] == [150, 152, 280]


def test_frozen_footage_is_found_and_cut():
    def spec(x):
        s = one_match(x)
        if 130 <= x < 170:
            s["motion"] = 0.0
        return s
    r = build(600, spec)
    m = rivals.matches(r)[0]
    assert [(round(a), round(b)) for a, b in m.frozen] == [(130, 170)]
    spans = rivals.plan(r, m)
    assert not any(a <= 150 <= b for a, b in spans)
    assert any(a <= 175 <= b for a, b in spans)


def test_old_readings_load_without_the_new_fields(tmp_path):
    r = build(30, lambda x: {})
    np.savez(tmp_path / "old.npz", **{k: getattr(r, k) for k in r.__dataclass_fields__
                                       if k not in ("own_rows", "motion", "ko", "ko_sig")})
    back = rivals.Readings.load(tmp_path / "old.npz")
    assert len(back.own_rows) == len(back) and (back.motion > 1).all()


def test_the_feed_row_reader_counts_white_rows():
    feed = np.zeros((rivals.FH, rivals.FW, 3), np.uint8)
    assert rivals.own_rows(feed) == 0
    feed[20:42, 240:550] = 235                    # one white row
    feed[60:84, 240:550] = 235                    # and another
    feed[120:140, 240:550] = (40, 60, 160)        # somebody else's blue row
    assert rivals.own_rows(feed) == 2


# ---------------------------------------------------------------- highlight

def test_a_highlight_is_the_fights_around_kills_and_ults_in_order():
    from autostream.clips import highlight
    r = build(600, with_kills)
    m = rivals.matches(r)[0]
    shots = highlight.plan(r, m)
    kinds = [s.kind for s in shots]
    assert kinds[0] == "intro" and kinds[-1] == "result"
    fights = [s for s in shots if s.kind == "fight"]
    covered = lambda at: any(s.start <= at <= s.end for s in fights)  # noqa: E731
    assert covered(150) and covered(152) and covered(280) and covered(320)
    assert not covered(230)          # the walk back after the death
    assert not covered(215)          # the spectator view
    # In order, never overlapping.
    assert all(a.end <= b.start for a, b in zip(shots, shots[1:]))


def test_no_highlight_without_a_match_to_show():
    from autostream.clips import highlight
    r = build(600, one_match)
    m = rivals.matches(r)[0]
    m.kills, m.casts = [], []
    # No kills: it falls back to the summary's fights rather than nothing.
    assert any(s.kind == "fight" for s in highlight.plan(r, m))


def test_the_highlight_graph_has_a_whoosh_per_cut_and_a_hit_per_kill():
    from autostream.clips import highlight
    shots = [highlight.Shot(0, 4, "intro"), highlight.Shot(100, 120, "fight"),
             highlight.Shot(200, 230, "fight"), highlight.Shot(300, 305, "result")]
    durs = [s.seconds for s in shots]
    text, total = highlight.graph(shots, durs, kills=[110.0, 210.0, 999.0],
                                  ults=[215.0], title=True)
    assert total == pytest.approx(sum(durs) - 3 * highlight.T)
    assert text.count("xfade=") == 3
    assert "transition=fadewhite" in text and "transition=smoothleft" in text
    assert "asplit=3" in text                 # three whooshes
    assert "asplit=3[h0]" in text             # two kills that are in shots + one ult
    assert "drawtext" in text and "fade=t=out" in text
    assert "[aout]" in text and "[vout]" in text
    no_title, _ = highlight.graph(shots, durs, [], [], title=False)
    assert "drawtext" not in no_title


def test_the_sounds_are_made_once_and_are_real_audio(tmp_path):
    from autostream.clips import sfx
    import wave
    got = sfx.files(tmp_path)
    for name in ("whoosh", "hit", "outro"):
        with wave.open(str(got[name])) as w:
            assert w.getnchannels() == 2 and w.getframerate() == sfx.SR
            assert w.getnframes() > sfx.SR * 0.3
    stamp = got["outro"].stat().st_mtime_ns
    sfx.files(tmp_path)
    assert got["outro"].stat().st_mtime_ns == stamp



def name(seed: int) -> np.ndarray:
    """A KO notice's text bits: a different name for each seed."""
    rng = np.random.default_rng(seed)
    return np.packbits(rng.random(rivals.KO_SIG * 8) < 0.2)


def with_kos(x: float) -> dict:
    """one_match plus KO notices: A at 140-144, B at 144-148 (a double), a
    one-sample flourish at 170, A again at 180, and one under your death."""
    s = one_match(x)
    for a, b, who in ((140, 144, 1), (144, 148, 2), (180, 184, 1), (203, 207, 3)):
        if a <= x < b:
            s.update(ko=True, ko_sig=name(who))
    if 170 <= x < 170.5:
        s.update(ko=True, ko_sig=name(9))
    return s


def test_every_ko_notice_counts_once_and_deaths_do_not():
    m = rivals.matches(build(600, with_kos))[0]
    assert [round(k) for k in m.kos] == [140, 144, 180]


def test_the_ko_notice_reader():
    crop = np.zeros((rivals.KH, rivals.KW, 3), np.uint8)
    assert rivals.ko_notice(crop)[0] is False
    crop[8:28, 14:32] = 240              # the icon
    crop[10:26, 44:160] = 240            # the name
    up, bits = rivals.ko_notice(crop)
    assert up and len(bits) == rivals.KO_SIG


def test_the_highlight_counts_kos_from_both_witnesses():
    from autostream.clips import highlight
    m = rivals.Match(start=0, end=600, kills=[150.0, 300.0], kos=[149.5, 200.0])
    assert highlight.kos(m) == [149.5, 200.0, 300.0]
    m.result = "victory"
    assert highlight.subtitle_for(m) == "VICTORY  -  3 KOs"


def test_the_outro_joins_with_a_flash_and_the_music_crossfades_into_it():
    from autostream.clips import highlight
    shots = [highlight.Shot(0, 4, "intro"), highlight.Shot(100, 120, "fight"),
             highlight.Shot(300, 305, "result")]
    durs = [s.seconds for s in shots]
    plain, total = highlight.graph(shots, durs, [110.0], [], title=False)
    text, with_outro = highlight.graph(shots, durs, [110.0], [], title=False, outro=6.0)
    assert with_outro == pytest.approx(total + 6.0 - highlight.OUTRO_JOIN)
    # The outro is input n+3, after whoosh, hit and the music bed.
    assert "[3:v]" not in plain and "[6:v]xfade=transition=fadewhite" in text
    assert "[6:a]volume=" in text and "acrossfade" in text.split("[6:a]")[1]
    # The picture fades out at the end of the outro, not of the match.
    assert f"fade=t=out:st={with_outro - highlight.OUTRO_FADE:.3f}" in text


def test_a_missing_outro_file_ends_on_the_result(tmp_path, monkeypatch):
    from autostream.clips import cutter, highlight
    seen = {}

    def fake_cut(source, start, dur, out, **kw):
        out.write_bytes(b"")
        return out
    monkeypatch.setattr(cutter, "_cut", fake_cut)
    monkeypatch.setattr(highlight, "media_info", lambda p: {"duration": 10.0})
    monkeypatch.setattr(highlight, "filter_script_flag", lambda: "-/filter_complex")
    shots = [highlight.Shot(0, 10, "fight")]
    m = rivals.Match(start=0, end=10)
    out = tmp_path / "hl.mp4"
    tmp = out.with_suffix(".tmp.mp4")

    def run(folder, *a):
        seen["args"] = a
        tmp.write_bytes(b"")
    monkeypatch.setattr(highlight, "_in_dir", run)
    highlight.render(tmp_path / "src.mp4", shots, m, out, title="T", subtitle="S",
                     outro=tmp_path / "gone.mp4")
    assert "outro_fit.mp4" not in seen["args"]
    assert out.is_file()
