r"""Tier 7: a recording the player cannot decode still gets a working part stage.

FROM A REPORT (#208): on a Mac, an .mp4 downloaded from YouTube -- AV1 video,
Opus audio -- showed a crossed-out play button on "Choose the part to clip"
while the filmstrip under it read the file perfectly. WKWebView on a Mac
without an AV1 decoder (anything before an M3) refuses AV1 outright: measured,
error 4 (MEDIA_ERR_SRC_NOT_SUPPORTED), where Chromium plays the same file. The
page decided "plays whole" from the extension alone, so it never fell back.

So this drives the app in WEBKIT, the Mac window's own engine, with exactly
that kind of file. Skipped where WebKit cannot be launched or the machine's
WebKit can decode AV1 -- the bug is "a file the player refuses", and a machine
where it does not refuse has nothing to show.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import appd
import pytest

pytestmark = pytest.mark.ui

SECONDS = 150          # over two minutes, or the part stage is not shown at all


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("unplayable-home")
    port = free_port()
    appd.seed_home(home, port)
    _av1_recording(home)
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


def _av1_recording(home: Path) -> Path:
    """What yt-dlp hands over for a long stream: AV1 and Opus in an mp4."""
    from autostream.clips.tools import binary

    ff = binary("ffmpeg")
    enc = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True,
                         text=True, creationflags=appd.NO_WINDOW).stdout
    if "libsvtav1" not in enc or "libopus" not in enc:
        pytest.skip("this ffmpeg cannot write AV1 and Opus")
    out = home / "video" / "av1.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ff, "-y", "-v", "error", "-f", "lavfi", "-i",
         f"testsrc2=size=640x360:rate=15:duration={SECONDS}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={SECONDS}",
         "-shortest", "-c:v", "libsvtav1", "-preset", "12", "-c:a", "libopus",
         "-movflags", "+faststart", str(out)],
        check=True, timeout=900, capture_output=True, creationflags=appd.NO_WINDOW)
    row = {"session": 1, "game": "VALORANT", "game_key": "valorant-win64-shipping.exe",
           "started": 1_790_000_000.0, "ended": 1_790_000_000.0 + SECONDS,
           "recording_path": str(out), "recording_seconds": SECONDS,
           "recording_bytes": out.stat().st_size, "title": "av1 test"}
    (home / "video" / "history.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return out


@pytest.fixture(scope="module")
def webkit(app):
    api = pytest.importorskip("playwright.sync_api",
                              reason="pip install playwright && python -m playwright install webkit")
    with api.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as e:                               # noqa: BLE001
            pytest.skip(f"webkit will not launch: {e}")
        yield b
        b.close()


@pytest.fixture
def ui(webkit, app):
    from test_ui_clip_stages import _pick_first
    from test_ui_playwright import Watched

    ctx = webkit.new_context(viewport={"width": 1500, "height": 950})
    page = ctx.new_page()
    w = Watched(page, app["base"])
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('clips')")
    page.wait_for_selector("#view-clips.is-active", state="attached")
    if page.evaluate("""() => { const v = document.createElement('video');
                                return v.canPlayType('video/mp4; codecs="av01.0.04M.08"'); }"""):
        ctx.close()
        pytest.skip("this WebKit decodes AV1, so it has no file to refuse")
    _pick_first(page)
    # Picking opens the summary now (2026-10-29 redesign); the part screen is
    # behind its first Change.
    page.wait_for_selector('#clip-sum [data-act="sum-change"][data-val="part"]', timeout=20_000)
    page.click('#clip-sum [data-act="sum-change"][data-val="part"]')
    page.wait_for_function("() => clip_state.step === 'part'", timeout=20_000)
    yield w
    ctx.close()


def test_a_file_the_player_refuses_falls_back_to_the_part(ui):
    """Not a dead play button: the page says why, and offers the part."""
    ui.page.wait_for_function(
        "() => clip_state.partFor && clip_state.partWhole === false"
        " && !document.getElementById('clip-part-video').getAttribute('src')",
        timeout=30_000)
    said = ui.page.locator("#clip-part-emptytext").inner_text()
    assert "only the part you choose" in said, said
    assert ui.page.locator("#clip-part-empty").is_visible()
    assert ui.page.locator("#clip-part-markin").is_hidden()


def test_the_part_it_offers_plays_in_the_same_player(ui):
    """The fallback is only worth having if what it builds plays here."""
    ui.page.wait_for_function("() => clip_state.partWhole === false", timeout=30_000)
    ui.page.evaluate("() => clip_partPlay()")
    state = ui.page.evaluate("""async () => {
        const v = document.getElementById('clip-part-video');
        for (let i = 0; i < 120 && !(v.getAttribute('src') || '').length; i++)
            await new Promise(r => setTimeout(r, 500));
        await new Promise(res => { if (v.readyState >= 1) return res();
                                   v.addEventListener('loadedmetadata', res);
                                   v.addEventListener('error', res);
                                   setTimeout(res, 30000); });
        return {src: v.getAttribute('src') || '', err: v.error && v.error.code,
                ready: v.readyState, dur: v.duration};
    }""")
    assert state["src"] and "/api/clips/source" not in state["src"], state
    assert not state["err"] and state["ready"] >= 1 and state["dur"] > 0, state


def test_a_copy_can_be_stopped(ui, app):
    """FROM A REPORT: "you didn't add a stop button to the create a copy
    portion, now it's stuck and I don't know how to make it stop"."""
    ui.page.wait_for_function("() => clip_state.partWhole === false", timeout=30_000)
    ui.page.locator("#clip-part-copy").click()
    stop = ui.page.locator("#clip-part-copystop")
    stop.wait_for(state="visible", timeout=20_000)
    stop.click()
    ui.page.wait_for_function(
        "() => !document.getElementById('clip-part-copy').disabled"
        " && document.getElementById('clip-part-copystop').classList.contains('hide')",
        timeout=30_000)
    left = list((Path(app["home"]) / "video").glob("*.playable.mp4*"))
    assert left == [], f"a stopped copy left {left}"


def test_a_playable_copy_makes_the_whole_recording_watchable(ui):
    """#210: the AV1 recording's own video never shows on an M1 or M2, so the
    page offers a copy it can show -- and once made, the player plays it,
    picture and all, and the whole recording can be marked again."""
    ui.page.wait_for_function("() => clip_state.partWhole === false", timeout=30_000)
    btn = ui.page.locator("#clip-part-copy")
    assert btn.is_visible()
    assert "GB" in btn.inner_text(), "the cost was not on the button"
    btn.click()
    ui.page.wait_for_function("() => clip_state.partWhole === true", timeout=300_000)
    state = ui.page.evaluate("""async () => {
        const v = document.getElementById('clip-part-video');
        await new Promise(res => { if (v.readyState >= 1) return res();
                                   v.addEventListener('loadedmetadata', res);
                                   v.addEventListener('error', res);
                                   setTimeout(res, 30000); });
        return {src: v.getAttribute('src') || '', err: v.error && v.error.code,
                width: v.videoWidth, dur: v.duration};
    }""")
    assert "copy=1" in state["src"], state
    assert not state["err"] and state["width"] > 0, f"still no picture: {state}"
    assert abs(state["dur"] - SECONDS) < 2, state
    assert ui.page.locator("#clip-part-markin").is_visible()
