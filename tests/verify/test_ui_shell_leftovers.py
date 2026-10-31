r"""What the redesign (v2.0.0) and page zoom (v2.1.0) left for later, pressed in a browser.

ROADMAP R1-R4 and R6: an old theme id rewritten at start, canvases told when the palette
changes, Ctrl K giving the keyboard back to where it was pressed and keeping it inside
while open, "Clips, N new" in the sidebar, and the breakpoints following the page size.
Each is behaviour the offline suite cannot see -- a focus that goes nowhere, a media
query that never matches -- so a browser does the pressing.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import appd
import pytest
import yaml

pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def browser():
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:                               # noqa: BLE001
            pytest.skip(f"chromium will not launch: {e}")
        yield b
        b.close()


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("leftovers")
    port = free_port()
    # A theme from before the redesign: the app must rewrite it as it starts.
    appd.seed_home(home, port, rules={"setup_done": True}, ui={"theme": "daylight"})
    # Clips looked at an hour ago, and two made since.
    run = home / "video" / "clips" / "2026-10-31_1200_VALORANT"
    (run / "clips").mkdir(parents=True)
    rows = []
    for i in range(2):
        clip = run / "clips" / f"new_{i}.mp4"
        clip.write_bytes(b"\0" * 64)
        rows.append({"rank": i + 1, "start": 10.0, "end": 18.0, "duration": 8.0, "kills": 1,
                     "name": clip.stem, "master": str(clip), "vertical": "", "caption": "",
                     "tags": [], "at": ""})
    (run / "clips.json").write_text(json.dumps({"game": "VALORANT", "clips": rows}))
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "token": appd.TOKEN, "home": home}
    finally:
        appd.stop(base, proc)


def _page(browser, app, width=1600, height=1000):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("console", lambda m: trouble.append(m.text)
            if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined' && typeof shell_zoomSet === 'function'",
                           timeout=30_000)
    page.evaluate("() => { try { localStorage.removeItem('autostream.zoom'); } catch (e) {} shell_zoomSet(1); go('dash'); }")
    return ctx, page, trouble


@pytest.fixture
def pg(browser, app):
    ctx, page, trouble = _page(browser, app)
    yield page
    assert not trouble, trouble
    ctx.close()


def test_r1_an_old_theme_is_rewritten_when_the_app_starts(app, pg):
    raw = yaml.safe_load((Path(app["home"]) / "config" / "config.yaml").read_text(encoding="utf-8"))
    assert raw["ui"]["theme"] == "light"
    # and the page is in it: the light palette, with no System block
    css = pg.evaluate("() => document.getElementById('theme-vars').textContent")
    assert "prefers-color-scheme" not in css


def test_r2_a_new_palette_reaches_every_pages_canvases(pg):
    pg.evaluate("""() => { window.__resized = 0; window.__themed = 0;
        window.addEventListener('resize', () => window.__resized++);
        window.addEventListener('as-theme', () => window.__themed++); }""")
    pg.evaluate("() => go('settings')")
    pg.evaluate("() => { window.__resized = 0; window.__themed = 0; }")
    pg.evaluate("() => shell_themeChanged()")
    assert pg.evaluate("() => [window.__resized, window.__themed]") == [1, 1]
    # A page that was hidden repaints when it is next shown -- once.
    pg.evaluate("() => go('dash')")
    assert pg.evaluate("() => window.__themed") == 2
    pg.evaluate("() => go('settings')")
    assert pg.evaluate("() => window.__themed") == 2, "settings was already in the new palette"


def test_r2_windows_flipping_to_light_repaints_too(pg):
    # A media query's change event is sent while the page renders, so each switch is
    # given two frames to be seen in.
    frames = "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    pg.emulate_media(color_scheme="light")
    pg.evaluate(frames)
    gen = pg.evaluate("() => shell_themeGen")
    pg.emulate_media(color_scheme="dark")
    pg.evaluate(frames)
    assert not pg.evaluate("() => matchMedia('(prefers-color-scheme: light)').matches")
    pg.wait_for_function("(g) => shell_themeGen > g", arg=gen, timeout=10_000)


def test_r3_ctrl_k_gives_the_keyboard_back_and_keeps_it_while_open(pg):
    pg.focus("#zoom-in")
    pg.keyboard.press("Control+k")
    pg.wait_for_selector("#pal-scrim:not(.hide)")
    assert pg.evaluate("() => document.activeElement.id") == "pal-q"
    # Tab walks the results and wraps; it never leaves the box.
    rows = pg.evaluate("() => document.querySelectorAll('#pal .pal-row').length")
    assert rows > 0
    for _ in range(rows + 2):
        pg.keyboard.press("Tab")
        assert pg.evaluate("() => document.getElementById('pal').contains(document.activeElement)")
    pg.keyboard.press("Shift+Tab")
    assert pg.evaluate("() => document.getElementById('pal').contains(document.activeElement)")
    pg.keyboard.press("Escape")
    pg.wait_for_selector("#pal-scrim.hide", state="attached")
    assert pg.evaluate("() => document.activeElement.id") == "zoom-in"


def test_r3_a_command_that_changes_page_does_not_drag_focus_back(pg):
    pg.focus("#zoom-in")
    pg.keyboard.press("Control+k")
    pg.fill("#pal-q", "go to logs")
    pg.keyboard.press("Enter")
    pg.wait_for_selector("#view-logs.is-active", state="attached")
    # #zoom-in is in the top bar, still on screen: going back to it is right.
    # What must not happen is focus left on the hidden search box.
    assert pg.evaluate("() => document.activeElement.id") != "pal-q"


def test_r4_the_sidebar_counts_the_clips_made_since_they_were_last_looked_at(browser, app):
    seen = Path(app["home"]) / "ui-seen.json"
    for clip in (Path(app["home"]) / "video" / "clips").rglob("*.mp4"):
        os.utime(clip, (time.time(), time.time()))
    seen.write_text(json.dumps({"clips": time.time() - 3600}), encoding="utf-8")
    ctx, page, trouble = _page(browser, app)
    try:
        page.wait_for_selector('.rail-btn[data-page="clips"] .rail-n', timeout=15_000)
        assert page.inner_text('.rail-btn[data-page="clips"] .rail-n') == "2 new"
        assert page.get_attribute('.rail-btn[data-page="clips"]', "aria-label") == "Clips, 2 new"
        # Looking at them clears it.
        page.evaluate("() => go('studio')")
        assert page.query_selector('.rail-btn[data-page="clips"] .rail-n') is None
        assert page.get_attribute('.rail-btn[data-page="clips"]', "aria-label") == "Clips"
        assert not trouble, trouble
    finally:
        ctx.close()


def test_r6_the_breakpoints_follow_the_page_size(browser, app):
    ctx, page, trouble = _page(browser, app, width=1200, height=900)
    try:
        page.evaluate("() => { localStorage.removeItem('autostream.rail'); shell_rail(); }")
        assert not page.evaluate("() => document.querySelector('.app').classList.contains('rail-min')")
        rule = """() => { for (const s of document.styleSheets) { let r; try { r = s.cssRules; } catch (e) { continue; }
            for (const x of r) if (x.media && /max-width:\\s*899px/.test(x.__asMedia || x.media.mediaText)) return x.media.mediaText; }
            return null; }"""
        assert "899px" in page.evaluate(rule)
        # 200% of a 1200 px window is 600 px of page: the narrow arrangement.
        page.evaluate("() => shell_zoomSet(2)")
        assert "1798px" in page.evaluate(rule)
        assert page.evaluate("() => shell_narrow(899)")
        assert page.evaluate("() => document.querySelector('.app').classList.contains('rail-min')")
        assert page.evaluate("() => matchMedia('(max-width:1798px)').matches")
        # and back, exactly -- every step scales the original, not the last step
        page.evaluate("() => { shell_zoomSet(1.5); shell_zoomSet(1); }")
        assert "899px" in page.evaluate(rule) and "1348" not in page.evaluate(rule)
        assert not page.evaluate("() => document.querySelector('.app').classList.contains('rail-min')")
        assert not trouble, trouble
    finally:
        ctx.close()
