"""Marvel Rivals match videos, around the edges the planner tests do not reach:
the reading cache, the cost model, what the page is told, and the outro.

No footage and no ffmpeg: the reader is replaced with readings built by hand
(see test_rivals.build), and every file touched is under tmp_path.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from autostream import webui
from autostream.clips import rivals, studio, summary
from test_rivals import build, one_match


# ------------------------------------------------------------- the cache

@pytest.fixture
def video(tmp_path):
    v = tmp_path / "rec.mp4"
    v.write_bytes(b"x" * 1000)
    return v


@pytest.fixture
def reads(monkeypatch):
    """Every window the reader was actually asked to decode."""
    asked = []

    def fake_scan(video, *, start=0.0, duration=None, workers=4, progress=None,
                  cancelled=None):
        asked.append((round(start), round(start + duration)))
        full = build(600, one_match)
        sel = (full.t >= start) & (full.t < start + duration)
        return rivals._take(full, sel)
    monkeypatch.setattr(rivals, "scan", fake_scan)
    return asked


def test_a_second_run_on_the_same_part_reads_nothing(tmp_path, video, reads):
    cache = tmp_path / "cache"
    r1, again1 = rivals.cached_scan(video, cache, start=0, duration=600)
    r2, again2 = rivals.cached_scan(video, cache, start=0, duration=600)
    assert (again1, again2) == (False, True)
    assert reads == [(0, 600)]
    assert len(r1) == len(r2) and (r1.t == r2.t).all()


def test_a_part_inside_an_earlier_read_is_sliced_out(tmp_path, video, reads):
    cache = tmp_path / "cache"
    rivals.cached_scan(video, cache, start=0, duration=600)
    r, again = rivals.cached_scan(video, cache, start=100, duration=200)
    assert again and reads == [(0, 600)]
    assert r.t[0] >= 100 and r.t[-1] < 300


def test_reads_that_meet_are_joined_and_then_cover_both(tmp_path, video, reads):
    cache = tmp_path / "cache"
    rivals.cached_scan(video, cache, start=0, duration=300)
    rivals.cached_scan(video, cache, start=300, duration=300)
    r, again = rivals.cached_scan(video, cache, start=0, duration=600)
    assert again and reads == [(0, 300), (300, 600)]
    assert np.all(np.diff(r.t) > 0.3), "the join must not duplicate samples"


def test_a_changed_recording_is_read_again(tmp_path, video, reads):
    cache = tmp_path / "cache"
    rivals.cached_scan(video, cache, start=0, duration=600)
    st = video.stat()
    os.utime(video, (st.st_atime, st.st_mtime + 60))
    _r, again = rivals.cached_scan(video, cache, start=0, duration=600)
    assert not again and len(reads) == 2


def test_a_cancelled_read_is_not_kept(tmp_path, video, reads):
    cache = tmp_path / "cache"
    rivals.cached_scan(video, cache, start=0, duration=600, cancelled=lambda: True)
    assert not list(cache.glob("*.npz")) if cache.exists() else True


def test_an_empty_span_joins_with_full_ones():
    """Cancel stops the spans mid-read, and one that had read nothing had its
    objective-line array the wrong width -- so the join raised, and the page
    said "Could not finish: all the input array dimensions..." instead of
    Cancelled."""
    full = build(10, lambda x: {})
    empty = rivals._pack([], [])
    got = rivals.Readings.join([full, empty])
    assert len(got) == len(full)
    assert empty.line.shape == (0, rivals.LINE_BYTES) == (0, full.line.shape[1])
    assert empty.ko_sig.shape == (0, rivals.KO_SIG)


def test_known_matches_come_from_what_was_read(tmp_path, video, reads):
    cache = tmp_path / "cache"
    assert rivals.known_matches(cache, video) == {"matches": [], "covered": []}
    rivals.cached_scan(video, cache, start=0, duration=600)
    got = rivals.known_matches(cache, video)
    assert got["covered"] == [[0.0, 600.0]]
    assert len(got["matches"]) == 1
    m = got["matches"][0]
    assert m["result"] == "victory" and 59 <= m["start"] <= 61


# ------------------------------------------------------ the cost model

def test_the_plan_prices_each_video_by_how_long_it_is():
    r = build(600, one_match)
    ms = rivals.matches(r)
    both = summary.plan(r, ms)
    assert [j.kind for j in both] == ["summary", "highlight"]
    s, h = both
    assert s.cost == pytest.approx(s.seconds / summary.SUMMARY_SPEED)
    assert h.cost == pytest.approx(h.seconds / summary.HIGHLIGHT_SPEED
                                   + summary.HIGHLIGHT_FIXED)
    assert [j.kind for j in summary.plan(r, ms, summaries=False)] == ["highlight"]
    assert [j.kind for j in summary.plan(r, ms, highlights=False)] == ["summary"]


def test_the_overview_counts_matches_not_videos():
    rows = [
        {"kind": "summary", "match": 1, "result": "victory", "kos": 20, "ults": 2,
         "deaths": 3, "cut_seconds": 90, "match_seconds": 600, "master": "a.mp4"},
        {"kind": "highlight", "match": 1, "result": "victory", "kos": 20, "ults": 2,
         "deaths": 3, "master": "b.mp4"},
        {"kind": "summary", "match": 2, "result": "defeat", "kos": 5, "ults": 1,
         "deaths": 9, "cut_seconds": 120, "match_seconds": 500, "master": "c.mp4"},
        {"kind": "highlight", "match": 2, "result": "defeat", "kos": 5, "ults": 1,
         "deaths": 9, "master": "", "error": "ffmpeg failed"},
    ]
    o = summary.overview(rows)
    assert (o["matches"], o["videos"], o["failed"]) == (2, 3, 1)
    assert (o["kos"], o["wins"], o["cut_seconds"]) == (25, 1, 210.0)


def test_a_failed_highlight_keeps_the_summary_and_says_why(tmp_path, monkeypatch):
    from autostream.clips import cutter, highlight

    def fake_master(source, spans, name, outdir, **kw):
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / f"{name}.mp4").write_bytes(b"")
        return outdir / f"{name}.mp4"

    def boom(*a, **k):
        raise RuntimeError("ffmpeg failed making the highlight: bad filter")
    monkeypatch.setattr(cutter, "master_segments", fake_master)
    monkeypatch.setattr(highlight, "render", boom)
    rows = summary.build(tmp_path / "src.mp4", build(600, one_match), tmp_path / "out",
                         game="Marvel Rivals")
    kinds = {r["kind"]: r for r in rows}
    assert kinds["summary"]["master"].endswith(".mp4")
    assert kinds["highlight"]["master"] == "" and "bad filter" in kinds["highlight"]["error"]


def test_every_row_carries_what_the_page_draws(tmp_path, monkeypatch):
    from autostream.clips import cutter, highlight

    def fake_master(source, spans, name, outdir, **kw):
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / f"{name}.mp4").write_bytes(b"")
        return outdir / f"{name}.mp4"

    def fake_render(source, shots, m, out, **kw):
        out.write_bytes(b"")
        return out
    monkeypatch.setattr(cutter, "master_segments", fake_master)
    monkeypatch.setattr(highlight, "render", fake_render)
    seen = []
    rows = summary.build(tmp_path / "src.mp4", build(600, one_match), tmp_path / "out",
                         game="Marvel Rivals", progress=seen.append)
    for r in rows:
        for key in ("kind", "match", "result", "duration", "kos", "master",
                    "match_seconds"):
            assert key in r, (r["kind"], key)
    s = [r for r in rows if r["kind"] == "summary"][0]
    assert s["chapter_marks"][0][1] == "Match start"
    assert "summary" in Path(s["master"]).stem
    h = [r for r in rows if r["kind"] == "highlight"][0]
    assert "highlight" in Path(h["master"]).stem
    # Progress in cost, ending on the whole of it.
    assert [p["kind"] for p in seen] == ["summary", "highlight", "done"]
    assert seen[-1]["done"] == pytest.approx(seen[-1]["total"])
    assert seen[1]["done"] == pytest.approx(seen[0]["cost"])


def test_the_studio_does_not_offer_match_videos_as_clips(tmp_path):
    run = tmp_path / "2026-09-29_0030_Marvel-Rivals_match-videos"
    (run / "summaries").mkdir(parents=True)
    video = run / "summaries" / "a.mp4"
    video.write_bytes(b"x")
    (run / "clips.json").write_text(json.dumps({"game": "Marvel Rivals", "clips": [
        {"kind": "summary", "master": str(video), "start": 0, "end": 600, "duration": 540},
        {"kind": "highlight", "master": str(video), "start": 0, "end": 600, "duration": 200},
    ]}), encoding="utf-8")
    assert studio.library(tmp_path)["clip_count"] == 0


# ------------------------------------------------------------- the outro

@pytest.fixture
def app(tmp_path, monkeypatch):
    a = webui.Server.__new__(webui.Server)
    saved = {}

    def save(values):
        saved.update(values)
        return {"ok": True, "saved": sorted(values), "errors": {}}
    a.save_settings = save
    monkeypatch.setattr(webui.Server, "outros_dir", staticmethod(lambda: tmp_path / "outros"))
    monkeypatch.setattr(webui.cfg, "load", lambda: SimpleNamespace(
        clips=SimpleNamespace(outro=saved.get("clips.outro", ""))))
    monkeypatch.setattr("autostream.clips.tools.media_info",
                        lambda p: {"duration": 6.0, "width": 1920, "height": 1080,
                                   "audio_tracks": 1})
    a.saved = saved
    return a


def test_choosing_an_outro_copies_it_in_and_saves_the_copy(app, tmp_path):
    src = tmp_path / "downloads" / "my outro.mp4"
    src.parent.mkdir()
    src.write_bytes(b"video")
    got = app.clips_outro_set({"path": str(src)})
    kept = tmp_path / "outros" / "my outro.mp4"
    assert kept.read_bytes() == b"video"
    assert app.saved["clips.outro"] == str(kept)
    assert got["name"] == "my outro.mp4" and got["seconds"] == 6.0 and got["sound"]
    # The original can go; the copy is what highlights use.
    src.unlink()
    assert app.clips_outro_info()["path"] == str(kept)


def test_no_outro_clears_it(app, tmp_path):
    got = app.clips_outro_set({"path": ""})
    assert app.saved["clips.outro"] == "" and got["path"] == ""


@pytest.mark.parametrize("name,why", [
    ("notes.txt", "MP4, MOV, MKV or WebM"),
    ("gone.mp4", "not there any more"),
])
def test_an_outro_that_cannot_be_one_is_refused(app, tmp_path, name, why):
    p = tmp_path / name
    if name != "gone.mp4":
        p.write_text("x")
    got = app.clips_outro_set({"path": str(p)})
    assert why in got["error"] and "clips.outro" not in app.saved


def test_a_long_video_is_not_an_outro(app, tmp_path, monkeypatch):
    monkeypatch.setattr("autostream.clips.tools.media_info", lambda p: {"duration": 600.0})
    p = tmp_path / "match.mp4"
    p.write_bytes(b"x")
    assert "between 1 and 60 seconds" in app.clips_outro_set({"path": str(p)})["error"]


def test_a_missing_outro_is_reported_not_hidden(app, tmp_path):
    app.saved["clips.outro"] = str(tmp_path / "moved.mp4")
    got = app.clips_outro_info()
    assert got["missing"] and got["name"] == "moved.mp4"


# ----------------------------------------------------- the page itself

def test_the_stylesheet_has_no_escape_accidents():
    """The stylesheet is a plain Python string, and a single backslash in CSS
    ("\\2192") became a control character: the progress arrows drew as a box
    and '92' on every run of every game."""
    from autostream.ui import css
    for name, value in vars(css).items():
        if isinstance(value, str) and len(value) > 1000:
            bad = [c for c in value if ord(c) < 32 and c not in "\n\r\t"]
            assert not bad, f"{name} carries control characters {bad[:3]}"


def test_every_page_s_markup_closes_what_it_opens():
    """One stray </div> moved the whole options card out of the page's
    scrolling column, so it floated over the stream list."""
    from html.parser import HTMLParser

    from autostream.ui import clips as clips_ui

    void = {"input", "img", "br", "hr", "meta", "link", "source", "col", "wbr", "track"}

    class Check(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.bad = [], []

        def handle_starttag(self, tag, attrs):
            if tag not in void:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if tag in void:
                return
            if not self.stack or self.stack[-1] != tag:
                self.bad.append(tag)
            else:
                self.stack.pop()

    c = Check()
    c.feed(clips_ui.CLIPS_HTML)
    assert c.bad == [] and c.stack == []


def test_a_match_video_game_hides_the_clip_options():
    from autostream.ui import clips as clips_ui
    js = clips_ui.CLIPS_JS
    body = js[js.index("function clip_mvRender() {"):]
    body = body[:body.index("\n}\n")]
    for el in ("clip-grid", "clip-calibrate", "clip-review"):
        assert re.search(r"clip_show\('" + el + r"', !on\)", body), el
    assert "Make match videos" in body
