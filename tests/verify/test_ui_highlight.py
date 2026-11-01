r"""Tier 7: the highlight editor, pressed in a browser.

FROM A REQUEST (2026-11-01): the stream highlight opened "in a timeline with
editing options other than the song reel edit" -- moments kept or removed, the
facecam area and zoom, the automatic captions -- laid out as the player chose, a
timeline with lanes and the transcript beside it (ui/highlight.py).

What only a browser can see: that the editor opens from the recording's summary,
that the preview really plays the recording and skips what was removed, that the
face zoom is drawn, that each control changes the project on disk, and that Make
video makes a file. The offline suite proves the cut list (test_highlight_edit.py).
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import appd
import pytest

pytestmark = pytest.mark.ui

SECONDS = 60


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("highlight-home")
    port = free_port()
    appd.seed_home(home, port)
    video = _run(home)
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN, "video": video}
    finally:
        appd.stop(base, proc)


def _run(home: Path) -> Path:
    """A recording, a run of it that made a highlight, and that highlight's project."""
    from autostream.clips import highlight_edit as he
    from autostream.clips import stream_highlight as sh
    from autostream.clips.speech import Line
    from autostream.clips.tools import binary

    vh = home / "video"
    rec = vh / "rec.mp4"
    rec.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([binary("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=size=640x360:rate=30:duration={SECONDS}",
                    "-f", "lavfi", "-i", f"sine=frequency=300:duration={SECONDS}", "-shortest",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-c:a", "aac",
                    "-movflags", "+faststart", str(rec)],
                   check=True, timeout=300, capture_output=True, creationflags=appd.NO_WINDOW)
    run = vh / "clips" / "2026-01-01_1200_VALORANT"
    (run / "match").mkdir(parents=True)
    (run / "session.json").write_text(json.dumps({"source": str(rec), "game": "VALORANT", "kills": []}),
                                      encoding="utf-8")
    out = run / "match" / "VALORANT_2026-01-01_highlights_Bind_0m20s.mp4"
    out.write_bytes(rec.read_bytes())
    cuts = [sh.Cut(30.0, 33.0, kind="cold", stretch=1),
            sh.Cut(2.0, 8.0, stretch=0, caption="MATCH 1 · COMPETITIVE · BIND"),
            sh.Cut(8.5, 10.0, stretch=0, layout="result", caption="ROUND 3 · WON · 2-1"),
            sh.Cut(20.0, 26.0, stretch=1),
            sh.Cut(26.0, 30.0, stretch=1, layout="cam"),
            sh.Cut(40.0, 46.0, stretch=2)]
    chosen = [sh.Stretch(2, 10, 3.0, round=3, why="2 kills"),
              sh.Stretch(20, 30, 4.0, round=5, why="Reaction"),
              sh.Stretch(40, 46, 2.0, round=8, why="1 kill")]
    lines = [Line(3.0, 5.0, "kya baat hai", "what a shot"),
             Line(21.0, 24.0, "bhai rotate karo", "bro rotate"),
             Line(27.0, 29.0, "gg bhai", "gg bro")]
    he.save(he.build(video=out, source=rec, source_seconds=SECONDS, cuts=cuts, chosen=chosen,
                     labels=["MATCH 1"] * 3, lines=lines, cam_box=(0.02, 0.6, 0.2, 0.3),
                     channel="", game="VALORANT"))
    row = {"session": 1, "game": "VALORANT", "game_key": "valorant-win64-shipping.exe",
           "started": 1_790_000_000.0, "ended": 1_790_000_000.0 + SECONDS,
           "recording_path": str(rec), "recording_seconds": SECONDS,
           "recording_bytes": rec.stat().st_size, "title": "highlight test"}
    (vh / "history.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return out


@pytest.fixture(scope="module")
def browser(app):
    api = pytest.importorskip("playwright.sync_api",
                              reason="pip install playwright && python -m playwright install chromium")
    with api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def ui(browser, app):
    from test_ui_clip_stages import _pick_first
    from test_ui_playwright import Watched

    ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    w = Watched(page, app["base"])
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('clips')")
    page.wait_for_selector("#view-clips.is-active", state="attached")
    _pick_first(page)
    page.wait_for_selector('#clip-sum [data-act="sum-highlight"]', timeout=20_000)
    page.click('#clip-sum [data-act="sum-highlight"]')
    page.wait_for_function("() => hl.p && !document.getElementById('hl-card').classList.contains('hide')",
                           timeout=20_000)
    page.wait_for_function("() => document.getElementById('hl-video').readyState >= 1", timeout=30_000)
    yield w
    ctx.close()


def _disk(app) -> dict:
    from autostream.clips import highlight_edit as he
    return he.load(app["video"])


def _settle(page) -> None:
    """Past the editor's save debounce."""
    page.wait_for_timeout(1200)


def test_it_opens_from_the_summary_over_the_clips_page(ui):
    page = ui.page
    assert page.locator("#hl-card").is_visible()
    assert page.locator("#clip-sum").is_hidden()
    assert page.locator("#hl-track .hl-mom").count() == 4         # the opening and three moments
    assert page.locator("#hl-track .hl-zm").count() == 1          # the talk cut zooms
    assert page.locator("#hl-track .hl-end").count() == 1
    assert page.locator("#hl-said .hl-line").count() == 3
    assert page.evaluate("() => document.getElementById('hl-video').duration") > SECONDS - 1
    ui.clean("opening the editor")


def test_removing_a_moment_saves_and_undo_puts_it_back(ui, app):
    page = ui.page
    page.locator("#hl-track .hl-mom").nth(1).click()
    page.click('#hl-insp [data-hl="keepmom"]')
    assert "is-off" in page.locator("#hl-track .hl-mom").nth(1).get_attribute("class")
    _settle(page)
    assert [c["keep"] for c in _disk(app)["cuts"]][1:3] == [False, False]
    page.click('[data-hl="undo"]')
    _settle(page)
    assert all(c["keep"] for c in _disk(app)["cuts"])
    ui.clean("removing a moment")


def test_the_preview_skips_a_removed_moment(ui):
    page = ui.page
    page.evaluate("() => { hl_change(() => { hl.p.cuts[1].keep = false; hl.p.cuts[2].keep = false; }); }")
    # From near the end of the opening: the next thing played is round 5, not round 3.
    page.evaluate("() => { hl_seek(0, 32.0); hl_togglePlay(); }")
    page.wait_for_function("() => hl.cur === 3", timeout=10_000)
    t = page.evaluate("() => document.getElementById('hl-video').currentTime")
    assert 19.9 <= t <= 22.0, t
    page.evaluate("() => { document.getElementById('hl-video').pause(); hl_undoRedo(true); }")
    ui.clean("playing through a removed moment")


def test_the_face_zoom_is_drawn_where_the_render_puts_it(ui):
    page = ui.page
    page.evaluate("() => hl_seek(4, 27.5)")
    page.wait_for_function("() => /scale/.test(document.getElementById('hl-video').style.transform)",
                           timeout=5_000)
    page.evaluate("() => hl_seek(3, 21.0)")
    page.wait_for_function("() => !document.getElementById('hl-video').style.transform", timeout=5_000)


def test_a_line_is_fixed_cut_and_put_on_the_face(ui, app):
    page = ui.page
    line = page.locator("#hl-line-1 .hl-line-text")
    line.click()
    page.keyboard.press("Control+A")
    page.keyboard.type("bro, rotate now")
    page.keyboard.press("Enter")
    page.click('#hl-line-0 [data-hl="face"]')
    page.click('#hl-line-2 [data-hl="cut"]')
    _settle(page)
    lines = _disk(app)["lines"]
    assert lines[1]["english"] == "bro, rotate now"
    assert lines[0]["face"] and lines[2]["cut"]
    assert page.locator("#hl-track .hl-zm.is-line").count() == 1
    assert page.locator("#hl-track .hl-cp.is-cut").count() >= 1
    # The caption shown over the preview is the corrected one.
    page.evaluate("() => hl_seek(3, 22.0)")
    page.wait_for_function("() => document.getElementById('hl-cap').textContent === 'bro, rotate now'",
                           timeout=5_000)
    ui.clean("editing a line")


def test_the_facecam_box_moves(ui, app):
    page = ui.page
    page.click('[data-hl="box"]')
    box = page.locator("#hl-box")
    assert box.is_visible()
    b = box.bounding_box()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    page.mouse.down()
    page.mouse.move(b["x"] + b["width"] / 2 + 80, b["y"] + b["height"] / 2 - 40, steps=5)
    page.mouse.up()
    page.click('[data-hl="box"]')
    _settle(page)
    x, y, _w, _h = _disk(app)["cam_box"]
    assert x > 0.05 and y < 0.6
    ui.clean("moving the facecam box")


def test_make_video_writes_the_edited_file(ui, app):
    from autostream.clips import highlight_edit as he

    page = ui.page
    page.click('[data-hl="caps"]')
    page.click('[data-hl="make"]')
    page.wait_for_function(
        "() => /Made:/.test(document.getElementById('hl-make-msg').textContent)", timeout=240_000)
    out = he.edited_path(app["video"])
    assert out.is_file() and out.stat().st_size > 10_000
    assert out.with_suffix(".srt").is_file()
    assert page.locator("#hl-show").is_visible()
    ui.clean("making the video")


def test_done_closes_it(ui):
    page = ui.page
    page.click('[data-hl="close"]')
    assert page.locator("#hl-card").is_hidden()
    assert page.locator("#clip-sum").is_visible()
    time.sleep(0.2)
    ui.clean("closing the editor")
