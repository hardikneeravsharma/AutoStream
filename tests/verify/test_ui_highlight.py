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
                    # A recording's three tracks, as OBS writes them: the mix, the mic, the game.
                    "-f", "lavfi", "-i", f"sine=frequency=300:duration={SECONDS}",
                    "-f", "lavfi", "-i", f"sine=frequency=500:duration={SECONDS}",
                    "-f", "lavfi", "-i", f"sine=frequency=800:duration={SECONDS}",
                    "-map", "0", "-map", "1", "-map", "2", "-map", "3", "-shortest",
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


def test_a_finished_run_lists_its_highlight_with_edit(ui, app):
    """The highlight used to be written to the run's folder and listed nowhere."""
    page = ui.page
    page.click('[data-hl="close"]')
    # The card a finished run shows (a real run is minutes of footage away).
    page.evaluate("([p]) => { clip_show('clip-results', true); clip_show('clip-res-list', true);"
                  " document.getElementById('clip-results').classList.remove('clip-offstep');"
                  " clip_renderResults([], null, {path: p, edit: true}); }", [str(app["video"])])
    row = page.locator("#clip-res-list .is-highlight")
    assert row.is_visible()
    assert "Highlight video" in row.inner_text()
    row.locator('[data-act="res-highlight-edit"]').click()
    page.wait_for_function("() => !document.getElementById('hl-card').classList.contains('hide')", timeout=10_000)
    page.click('[data-hl="close"]')
    # Made before the editor: listed, with no Edit to press.
    page.evaluate("([p]) => clip_renderResults([], null, {path: p, edit: false})", [str(app["video"])])
    assert page.locator('#clip-res-list [data-act="res-highlight-edit"]').count() == 0
    ui.clean("the results' highlight row")


def test_the_ready_toast_offers_edit(ui, app):
    page = ui.page
    page.click('[data-hl="close"]')
    page.evaluate("([p]) => toast('Your highlight video is ready.', 'ok',"
                  " {label: 'Edit', run: () => PAGE_HL.open(p)})", [str(app["video"])])
    page.locator("#toasts .toast-act").click()
    page.wait_for_function("() => !document.getElementById('hl-card').classList.contains('hide')", timeout=10_000)
    ui.clean("the toast's Edit")


# ------------------------------------------- the second pass: a video editor's controls

def _lane_point(page, lane: str, recording_t: float, cut: int):
    """Where on screen a recording second of one cut sits, in one lane."""
    return page.evaluate("""([lane, t, i]) => {
        const tr = document.getElementById('hl-track').getBoundingClientRect();
        const tops = hl_laneTops(), l = hl.lanes.find(x => x.k === lane);
        document.getElementById('hl-scroll').scrollLeft = Math.max(0, hl_x(i, t) * hl.pxs - 200);
        const tr2 = document.getElementById('hl-track').getBoundingClientRect();
        return {x: tr2.left + hl_x(i, t) * hl.pxs, y: tr2.top + tops[lane] + l.h / 2};
    }""", [lane, recording_t, cut])


def test_a_captions_end_is_dragged_to_show_it_longer(ui, app):
    page = ui.page
    page.evaluate("() => { hl.pxs = 20; hl_renderTrack(); }")
    before = _disk(app)["lines"][0]
    edge = page.locator('#hl-track .hl-cp[data-cap="0"] .hl-cedge-b').first
    b = edge.bounding_box()
    page.mouse.move(b["x"] + 2, b["y"] + b["height"] / 2)
    page.mouse.down()
    page.mouse.move(b["x"] + 2 + 40, b["y"] + b["height"] / 2, steps=6)    # 40 px at 20 px/s: 2 s
    page.mouse.up()
    _settle(page)
    after = [ln for ln in _disk(app)["lines"] if ln["id"] == 0][0]
    assert after["start"] == before["start"]
    assert after["end"] == pytest.approx(before["end"] + 2.0, abs=0.15)
    # Chosen: the inspector shows its times, and Split / Join / Delete.
    assert page.locator('#hl-insp [data-hl="capsplit"]').is_visible()
    ui.clean("retiming a caption")


def test_a_caption_is_added_split_and_deleted(ui, app):
    page = ui.page
    page.evaluate("() => hl_seek(3, 22.0)")
    page.click('[data-hl="addcap"]')
    page.locator("#hl-cap-input").fill("new words here now")
    page.keyboard.press("Enter")
    _settle(page)
    new = [ln for ln in _disk(app)["lines"] if ln["text"] == "new words here now"]
    assert len(new) == 1 and new[0]["start"] == pytest.approx(22.0, abs=0.1)
    page.evaluate("() => hl_seek(3, 23.0)")
    page.click('[data-hl="capsplit"]')
    _settle(page)
    halves = [ln for ln in _disk(app)["lines"] if ln["start"] >= 21.9 and ln["start"] < 24.1 and ln["id"] >= 3]
    assert [h["text"] for h in sorted(halves, key=lambda x: x["start"])] == ["new words", "here now"]
    page.click('[data-hl="capdel"]')
    _settle(page)
    assert len([ln for ln in _disk(app)["lines"] if ln["id"] >= 3]) == 1
    ui.clean("adding, splitting and deleting a caption")


def test_a_face_zoom_is_drawn_for_as_long_as_wanted(ui, app):
    page = ui.page
    page.evaluate("() => { hl.pxs = 20; hl_renderTrack(); }")
    a = _lane_point(page, "zoom", 21.0, 3)
    page.mouse.move(a["x"], a["y"])
    page.mouse.down()
    page.mouse.move(a["x"] + 60, a["y"], steps=6)                          # 3 s
    page.mouse.up()
    _settle(page)
    z = _disk(app)["zooms"]
    assert len(z) == 1 and z[0]["start"] == pytest.approx(21.0, abs=0.15)
    assert z[0]["end"] - z[0]["start"] == pytest.approx(3.0, abs=0.2)
    page.evaluate("() => hl_seek(3, 22.5)")
    page.wait_for_function("() => /scale/.test(document.getElementById('hl-video').style.transform)", timeout=5_000)
    page.keyboard.press("Delete")
    _settle(page)
    assert _disk(app)["zooms"] == []
    ui.clean("drawing a face zoom")


def test_volume_points_are_added_moved_and_removed(ui, app):
    page = ui.page
    page.evaluate("() => { hl.pxs = 20; hl_renderTrack(); }")
    assert page.locator('#hl-track svg[data-vol="game"]').count() == 1
    a = _lane_point(page, "volgame", 22.0, 3)
    page.mouse.click(a["x"], a["y"] + 10)                                 # below 0 dB
    _settle(page)
    keys = _disk(app)["volume"]["game"]["keys"]
    assert len(keys) == 1 and keys[0][0] == pytest.approx(22.0, abs=0.15) and keys[0][1] < 0
    page.locator('#hl-track svg[data-vol="game"] .hl-vk').first.dblclick()
    _settle(page)
    assert _disk(app)["volume"]["game"]["keys"] == []
    ui.clean("the game's volume line")


def test_the_overall_volume_is_saved(ui, app):
    page = ui.page
    page.locator("#hl-master").fill("-4")
    page.locator("#hl-master").dispatch_event("change")
    _settle(page)
    assert _disk(app)["volume"]["master"] == -4.0
    assert page.locator("#hl-master-v").inner_text() == "-4 dB"


def test_the_two_tracks_are_copied_out_and_played_at_their_own_volume(ui, app):
    from autostream.clips import highlight_edit as he
    page = ui.page
    page.wait_for_function("() => !!hl.aud", timeout=60_000)
    assert he.track_path(app["video"], "mic").is_file() and he.track_path(app["video"], "game").is_file()
    assert page.evaluate("() => document.getElementById('hl-video').muted")
    assert page.locator("#hl-team-stt").is_visible()
    ui.clean("the separate tracks")


def test_a_missing_speech_pack_is_offered_downloaded_and_then_used(ui):
    """The player (2026-11-02): a feature whose heavy parts are not here asks, and
    downloads them. The server's side is faked: PyPI and six gigabytes are not a test."""
    import json as _json
    page = ui.page
    calls = {"transcribe": 0, "progress": 0}

    def transcribe(route):
        calls["transcribe"] += 1
        body = {"error": "Speech-to-text is not downloaded yet.", "need": "speech"} \
            if calls["transcribe"] == 1 else {"ok": True, "state": "running"}
        route.fulfill(status=200, content_type="application/json", body=_json.dumps(body))

    def progress(route):
        calls["progress"] += 1
        body = ({"ok": True, "key": "speech", "state": "idle"} if calls["progress"] == 1 else
                {"ok": True, "key": "speech", "state": "running", "percent": 40, "done": 2_500_000_000,
                 "total": 6_200_000_000, "step": "Downloading speech-to-text: nvidia-cudnn-cu12 (25 of 26)"}
                if calls["progress"] < 4 else {"ok": True, "key": "speech", "state": "done"})
        route.fulfill(status=200, content_type="application/json", body=_json.dumps(body))

    page.route("**/api/clips/highlight/transcribe**", transcribe)
    page.route("**/api/packs/plan**", lambda r: r.fulfill(status=200, content_type="application/json", body=_json.dumps(
        {"ok": True, "key": "speech", "label": "Speech-to-text", "what": "writes down what you and your team say",
         "can": True, "installed": False, "bytes": 6_200_000_000})))
    page.route("**/api/packs/install**", lambda r: r.fulfill(status=200, content_type="application/json",
                                                             body='{"ok": true}'))
    page.route("**/api/packs/progress**", progress)
    page.click('[data-hl="team-stt"]')
    page.wait_for_selector(".pack-modal", timeout=10_000)
    assert "6.2 GB" in page.locator(".pack-modal").inner_text()
    assert "Captioning your team" in page.locator(".pack-modal").inner_text()
    page.click('.pack-modal [data-pack="go"]')
    page.wait_for_function("() => /25 of 26/.test(document.getElementById('pack-step').textContent)",
                           timeout=10_000)
    page.wait_for_selector(".pack-modal", state="detached", timeout=15_000)
    page.wait_for_function("() => true")
    assert calls["transcribe"] == 2                # asked again once it was there
    page.unroute("**/api/clips/highlight/transcribe**")
    page.unroute("**/api/packs/progress**")
    ui.clean("offering the speech download")


def test_done_closes_it(ui):
    page = ui.page
    page.click('[data-hl="close"]')
    assert page.locator("#hl-card").is_hidden()
    assert page.locator("#clip-sum").is_visible()
    time.sleep(0.2)
    ui.clean("closing the editor")
