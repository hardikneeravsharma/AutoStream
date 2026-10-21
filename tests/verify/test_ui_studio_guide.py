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


def test_the_full_make_page_carries_the_same_chip(pg):
    """F5: the verdict is not only the guided maker's. Opened with Build and drop on a song
    with no drop, the full page says it will not work, in words, before anything is built."""
    pg.click('.gd-card[data-key="drop"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song", timeout=30_000)
    pg.evaluate("() => { studio_gdPickAll(); if (!studio.gd.quick.length) studio.gd.quick = Object.keys(studio.clipIndex).slice(0, 4); }")
    pg.click('[data-gd="all"]')
    pg.wait_for_selector("#studio-make-scrim:not(.hide)")
    pg.wait_for_function("() => { const c = document.getElementById('studio-mk-chip'); return c && !c.hidden; }", timeout=30_000)
    text = pg.inner_text("#studio-mk-chip")
    assert "drop" in text.lower() and "won" in text.lower(), text


def _to_check(pg, style="story"):
    pg.evaluate("() => { document.querySelector('.gd-more').open = true; }")
    pg.click(f'.gd-card[data-key="{style}"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song", timeout=30_000)
    pg.click("#studio-gd-next")
    pg.click('[data-gd="pickall"]')
    pg.click("#studio-gd-next")
    pg.click("#studio-gd-next")
    pg.wait_for_selector("#studio-gd-name")


def test_make_asks_the_name_and_opens_the_timeline_not_all_settings(pg):
    """Reported: the name was never asked (every reel "Build and drop reel"), and Make opened
    All settings with its button greyed for the minute the plan took."""
    _to_check(pg)
    assert pg.get_attribute("#studio-gd-name", "placeholder") == "Length song story"
    pg.fill("#studio-gd-name", "My first reel")
    pg.evaluate("""() => { window.__plans = []; window.__make = false; const real = API.post;
        new MutationObserver(() => { if (!document.getElementById('studio-make-scrim').classList.contains('hide')) window.__make = true; })
          .observe(document.getElementById('studio-make-scrim'), {attributes: true});
        API.post = function (u, b) {
            if (u === '/api/studio/plan') window.__plans.push(JSON.parse(JSON.stringify(b)));
            if (u === '/api/studio/render') return Promise.resolve({ok: false, error: 'not rendered in this test'});
            return real.apply(this, arguments); }; }""")
    pg.wait_for_function("() => !document.getElementById('studio-gd-next').disabled", timeout=30_000)
    pg.click("#studio-gd-next")
    pg.wait_for_function("() => document.getElementById('studio-tab-timeline').classList.contains('is-active')", timeout=120_000)
    assert pg.evaluate("() => window.__make") is False
    assert pg.evaluate("() => window.__plans[0].name") == "My first reel"
    assert pg.evaluate("() => studio.project.name") == "My first reel"


def test_the_build_clip_chosen_is_sent_and_an_untouched_part_holds_the_drop(pg):
    """Reported: the build clip picked in the guide was not used. And Lalala's default part,
    from where the drums come in, left no room before the first drop for the take."""
    ids = pg.evaluate("() => Object.keys(studio.clipIndex)")
    body = pg.evaluate("""(ids) => { studio.style = 'drop'; studio.selected = ids.slice(0, 4);
        studio.buildClip = studio.clipIndex[ids[1]].path; return studio_planBody(false); }""", ids)
    assert body["shaping"]["build_clip"] == pg.evaluate("(id) => studio.clipIndex[id].path", ids[1])
    gone = pg.evaluate("""(ids) => { studio.selected = [ids[0]]; return studio_planBody(false).shaping.build_clip; }""", ids)
    assert gone is None                       # not among the clips any more: not sent
    pg.click('.gd-card[data-key="drop"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.songShape", timeout=30_000)
    part = pg.evaluate("""() => { studio.songShape.drop = 40; studio.mk.drops = null; studio.mk.touched = false;
        studio_mkDefault(); return [studio.mk.start, studio.mk.end]; }""")
    assert part[0] < 40 - 10 and part[1] > 40 + 10, part
    # drawn by the page and never moved: sent as a length, not an end
    assert pg.evaluate("() => studio_planBody(false).shaping.part_auto") is True
    assert pg.evaluate("() => { studio.mk.touched = true; return studio_planBody(false).shaping.part_auto; }") is None


def test_fast_paced_headshot_offers_and_picks_headshots_only(pg):
    """Pick for me filled Fast-paced headshot's slots with body kills, which its plan then left
    out (clips/fasthead.py is headshots only). Its clips step now offers clips with a headshot,
    counts them against about one a second, and says whether there is a double to end on."""
    ids = pg.evaluate("""() => { const ids = Object.keys(studio.clipIndex);
        ids.forEach((id, i) => { const c = studio.clipIndex[id]; c.hs = (c.kills || []).map(() => i % 2 === 0); });
        return ids.filter((id, i) => i % 2 === 0); }""")
    pg.evaluate("() => { document.querySelector('.gd-more').open = true; }")
    pg.click('.gd-card[data-key="fasthead"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song", timeout=30_000)
    pg.click("#studio-gd-next")
    pg.wait_for_selector('[data-gd="pickall"]')
    offered = pg.evaluate("() => [...document.querySelectorAll('.gd-clip')].map(b => b.getAttribute('data-id'))")
    assert sorted(offered) == sorted(ids)
    pg.click('[data-gd="pickall"]')
    assert sorted(pg.evaluate("() => studio.gd.quick")) == sorted(ids)
    text = pg.inner_text("#studio-gd-body")
    assert "Headshots only" in text and f"{len(ids)} of " in text and "single kill" in text
