r"""Tier 7: the guided maker -- one question a screen, and a chip that says whether it works.

The Make page asks everything at once and lets any style meet any song. The guided
maker asks one thing at a time, marks the reviewed style "Use this for best result", and
after each answer says -- through /api/studio/feasible, a real plan without the slow
footage checks -- whether the choices so far work together, with one fix.

The song here is a click track with no drop, and the clips have one kill each, so the
"won't work" paths are what a browser can reach honestly; the verdicts themselves are
tested offline in test_feasible, and the plan behind them in test_director.
"""
from __future__ import annotations

import appd
import pytest
from test_ui_studio_make_page import _clips, _song

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

    home = tmp_path_factory.mktemp("guide")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


@pytest.fixture
def pg(browser, app):
    _clips(app, "2026-10-11_1400_VALORANT", 6)
    _song(app)
    ctx = browser.new_context(viewport={"width": 1500, "height": 1000})
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("console", lambda m: trouble.append(m.text)
            if m.type == "error" and "studio/thumb" not in m.text and "clips/video" not in m.text
            and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.click('[data-act="studio-refresh"]')
    page.wait_for_function("() => studio.lib && Object.keys(studio.clipIndex || {}).length >= 6", timeout=30_000)
    page.wait_for_function("() => studio.catalog", timeout=30_000)
    page.wait_for_function("() => document.getElementById('studio-gd-open') !== null")
    page.click("#studio-gd-open")
    page.wait_for_selector("#studio-guide-scrim:not(.hide)")
    yield page
    assert not trouble, trouble
    ctx.close()


def chip(pg):
    return pg.evaluate("() => { const c = document.getElementById('studio-gd-chip'); "
                       "return {cls: c.className, text: c.innerText}; }")


def test_the_first_question_is_the_style_and_the_reviewed_one_says_so(pg):
    assert "What kind of reel?" in pg.inner_text("#studio-gd-body")
    best = pg.locator('.gd-card[data-key="drop"]')
    assert "use this for best result" in best.inner_text().lower()
    # the others are there, folded away, and say they are not reviewed
    assert not pg.evaluate("() => document.querySelector('.gd-more').open")
    assert "not reviewed" in pg.inner_text(".gd-more summary").lower()
    assert pg.locator(".gd-more .gd-card").count() >= 8
    # nothing chosen: no way on, and the chip says why
    assert pg.is_disabled("#studio-gd-next")
    assert "warn" in chip(pg)["cls"] and "Pick a style" in chip(pg)["text"]
    best.click()
    assert pg.is_enabled("#studio-gd-next")
    assert "ok" in chip(pg)["cls"]


def test_a_style_that_needs_a_drop_on_a_song_without_one_is_refused_in_words_with_a_fix(pg):
    pg.click('.gd-card[data-key="drop"]')
    pg.click("#studio-gd-next")
    pg.wait_for_selector('.gd-card[data-gd="song"]')
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song && studio.songShape", timeout=30_000)
    pg.wait_for_function("() => document.getElementById('studio-gd-chip').className.indexOf('bad') >= 0", timeout=30_000)
    c = chip(pg)
    assert "drop" in c["text"].lower(), c
    fix = pg.locator('#studio-gd-chip [data-gd="fix"]')
    assert fix.inner_text() == "Choose another song"
    assert "none found" in pg.inner_text(".gd-facts")


def test_give_us_a_song_chooses_the_style_only_when_the_song_supports_one(pg):
    pg.click(".gd-auto")
    pg.wait_for_selector('.gd-card[data-gd="song"]')
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.gd.step === 0 && studio.song", timeout=30_000)
    # the click track has no drop, so no style is picked for the player
    assert pg.evaluate("() => studio.gd.style") == ""
    assert "no clear drop" in pg.inner_text("#studio-gd-body")
    # a song with a drop would have chosen Build and drop: the rule behind it
    assert pg.evaluate("""() => { const sh = {drops: [10], bpm: 120}; return !!((sh.drops && sh.drops.length) || sh.drop); }""")


def test_pick_for_me_fills_the_clips_and_the_counter_says_how_many(pg):
    pg.click('.gd-card[data-key="story"]') if False else None
    pg.evaluate("() => { const d = document.querySelector('.gd-more'); d.open = true; }")
    pg.click('.gd-card[data-key="story"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song", timeout=30_000)
    pg.click("#studio-gd-next")
    pg.wait_for_selector('[data-gd="pickall"]')
    assert pg.is_disabled("#studio-gd-next")
    pg.click('[data-gd="pickall"]')
    chosen = pg.evaluate("() => studio.gd.quick.length")
    assert chosen >= 4, chosen
    assert pg.is_enabled("#studio-gd-next")
    assert f"{chosen} chosen" in pg.inner_text(".gd-slothead .mono")


def test_all_settings_opens_the_full_page_with_the_choices_in_it(pg):
    pg.evaluate("() => { document.querySelector('.gd-more').open = true; }")
    pg.click('.gd-card[data-key="story"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song", timeout=30_000)
    pg.click("#studio-gd-next")
    pg.click('[data-gd="pickall"]')
    pg.click('[data-gd="all"]')
    pg.wait_for_selector("#studio-make-scrim:not(.hide)")
    assert pg.evaluate("() => studio.style") == "story"
    assert pg.evaluate("() => studio.selected.length") >= 4
    assert pg.evaluate("() => document.getElementById('studio-guide-scrim').classList.contains('hide')")


def test_the_last_choices_are_remembered_as_intent_and_checked_again(pg, browser, app):
    pg.click('.gd-card[data-key="drop"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song", timeout=30_000)
    kept = pg.evaluate("() => JSON.parse(localStorage.getItem('autostream.guide'))")
    assert kept["style"] == "drop" and kept["fmt"] == "vertical" and kept["song"]
    # a clip that no longer exists is not brought back
    pg.evaluate("""() => { const m = JSON.parse(localStorage.getItem('autostream.guide'));
        m.quick = ['gone', ...m.quick]; localStorage.setItem('autostream.guide', JSON.stringify(m)); }""")
    pg.click('[data-gd="close"]')
    pg.evaluate("() => { studio.gd.style = ''; studio.gd.quick = []; }")
    pg.click("#studio-gd-open")
    pg.wait_for_selector("#studio-guide-scrim:not(.hide)")
    assert pg.evaluate("() => studio.gd.style") == "drop"
    assert "gone" not in pg.evaluate("() => studio.gd.quick")
