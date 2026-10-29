r"""Tier 7: the Studio's layout (issue #259) -- the side panes on demand, the player's transport,
the timeline's lanes and zoom, and the render status folded to a chip.

Offline tests cannot see any of it: a pane that will not close, a menu that opens off screen or a chip
nothing draws all pass every unit test. A browser presses the buttons.
"""
from __future__ import annotations

import appd
import pytest

pytestmark = pytest.mark.ui

PROJECT = """() => {
  studio.project = {
    version: 1, name: 'layout', style: 'montage', format: 'landscape',
    song: '', song_offset: 0, beat: 0.5, step: 0.5, intro: 'i00', outro: 'e12', grade: 'g01',
    vignette: false, overlays: [], handle: '', music_db: 0, game_db: 0, duck: false,
    saturation: 1, shots: [], lyrics: {look: 'off'}, cam: {source: 'none'}};
  studio.derived = {length: 10, beat: 0.5, bpm: 120, beats: [], kills: [], selection: [],
                    lead_in: 0, intro_clip: null, shots: []};
  studio_tab('timeline');
  return true;
}"""


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

    home = tmp_path_factory.mktemp("layout")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


@pytest.fixture
def pg(browser, app):
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("console", lambda m: trouble.append(m.text)
            if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.wait_for_timeout(900)
    page.evaluate("() => localStorage.removeItem('autostream.studio.side')")    # the default: closed
    page.evaluate(PROJECT)
    yield page
    assert not trouble, trouble
    ctx.close()


def rail_min(pg) -> bool:
    return pg.evaluate("() => document.querySelector('.app').classList.contains('rail-min')")


def rail_width(pg) -> float:
    pg.wait_for_timeout(350)    # the column eases to its width
    return pg.evaluate("() => document.querySelector('.rail').getBoundingClientRect().width")


def test_the_rail_is_open_on_every_page_until_the_player_chooses(pg):
    # The 2026-10-29 redesign: the sidebar used to fold to an icon strip off
    # the Dashboard, which hid the page names from exactly the person who did
    # not know the icons yet. Now it is open everywhere until collapsed.
    pg.evaluate("() => { localStorage.removeItem('autostream.rail'); shell_page = 'dash'; shell_rail(); }")
    assert not rail_min(pg) and rail_width(pg) > 150
    pg.evaluate("() => go('studio')")
    assert not rail_min(pg) and rail_width(pg) > 150
    # the toggle collapses it here, and the choice holds on the next page
    pg.click("#rail-toggle")
    assert rail_min(pg) and rail_width(pg) < 80
    assert pg.get_attribute("#rail-toggle", "aria-expanded") == "false"
    pg.evaluate("() => go('settings')")
    assert rail_min(pg)
    pg.click("#rail-toggle")
    assert not rail_min(pg)
    assert pg.get_attribute("#rail-toggle", "aria-expanded") == "true"
    pg.click("#rail-toggle")
    pg.evaluate("() => { shell_page = 'dash'; shell_rail(); }")
    assert rail_min(pg), "a collapse the player chose must hold on the Dashboard too"
    pg.evaluate("() => { localStorage.removeItem('autostream.rail'); shell_rail(); }")


def test_the_strip_opens_on_hover_and_the_page_makes_room(pg):
    # Collapsed by the player's own choice -- the only way to the strip now.
    pg.evaluate("() => { localStorage.setItem('autostream.rail', 'min'); shell_page = 'studio'; shell_rail(); }")
    assert rail_min(pg) and rail_width(pg) < 80    # and settled, before the page edge is measured
    main = pg.evaluate("() => document.querySelector('.main').getBoundingClientRect().left")
    pg.hover(".rail-nav")
    pg.wait_for_function("() => document.querySelector('.app').classList.contains('rail-peek')")
    assert rail_width(pg) > 150
    assert pg.is_visible(".rail-btn[data-page='studio'] span")
    pg.wait_for_timeout(400)
    left = pg.evaluate("() => document.querySelector('.main').getBoundingClientRect().left")
    assert left > main + 100, "the page must move over, not sit under the strip"
    assert left >= rail_width(pg) - 1
    pg.mouse.move(900, 500)
    pg.wait_for_function("() => !document.querySelector('.app').classList.contains('rail-peek')")
    assert rail_width(pg) < 80
    pg.evaluate("() => { localStorage.removeItem('autostream.rail'); shell_rail(); }")


def pin_side(pg):
    pg.evaluate("() => { localStorage.setItem('autostream.studio.side', 'on'); studio_sideApply('timeline'); }")


def test_the_side_panel_is_closed_by_default_opens_on_its_edge_and_stays_when_pinned(pg):
    assert pg.is_visible("#studio-sidebtn")
    assert not pg.is_visible(".ed-side"), "the panel starts closed"
    # the edge reaches the window's right side, and says what it is for
    box = pg.evaluate("""() => { const e = document.getElementById('studio-side-edge').getBoundingClientRect();
        return [e.right, window.innerWidth, e.width]; }""")
    assert box[0] >= box[1] - 2 and box[2] >= 28, box
    assert pg.is_visible(".ed-side-tab")
    # resting on the edge opens it; leaving it closes it again
    pg.hover("#studio-side-edge")
    pg.wait_for_selector(".ed-side", state="visible")
    pg.mouse.move(300, 500)
    pg.wait_for_selector(".ed-side", state="hidden")
    # the button keeps it open, and the choice is kept
    pg.click("#studio-sidebtn")
    assert pg.is_visible(".ed-side")
    assert pg.get_attribute("#studio-sidebtn", "aria-expanded") == "true"
    pg.reload(wait_until="domcontentloaded")
    pg.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    pg.evaluate("() => go('studio')")
    pg.wait_for_timeout(900)
    pg.evaluate(PROJECT)
    assert pg.is_visible(".ed-side"), "the pin was forgotten"
    pg.click("#studio-sidebtn")
    assert not pg.is_visible(".ed-side")
    pg.evaluate("() => studio_tab('clips')")
    assert not pg.is_visible("#studio-sidebtn"), "the button belongs to the Timeline tab"


def test_the_edge_says_what_it_holds_for_a_moment_on_a_first_visit(pg):
    pg.evaluate("() => { localStorage.removeItem('autostream.studio.sidehint'); studio_tab('clips'); studio_tab('timeline'); }")
    assert "side-hint" in pg.get_attribute("#studio-pane-timeline", "class")
    assert pg.is_visible(".ed-side-hint")
    pg.hover("#studio-side-edge")
    pg.wait_for_selector(".ed-side", state="visible")
    pg.mouse.move(300, 500)
    pg.evaluate("() => { studio_tab('clips'); studio_tab('timeline'); }")
    assert "side-hint" not in pg.get_attribute("#studio-pane-timeline", "class"), "seen once, not shown again"


def test_the_transport_is_a_media_player_and_the_toolbar_is_quiet(pg):
    for sel in ("#studio-prev-btn", "#studio-play-btn", "#studio-next-btn"):
        assert pg.is_visible(sel), sel
    assert pg.inner_text("#studio-play-btn").strip() == ""
    assert pg.get_attribute("#studio-play-btn", "aria-label") == "Play"
    pg.evaluate("() => { studio.pv.on = true; studio.pv.playing = true; studio_playGlyph(); studio.pv.playing = false; studio.pv.on = false; }")
    assert pg.get_attribute("#studio-play-btn", "aria-label") == "Pause"
    # A press as slow as a person's still lands while it plays. The glyph used to be rebuilt every frame of
    # playback, so the press went down on one icon and up on another and was no click at all: Pause did nothing.
    pg.evaluate("""() => {
        studio.pv.on = true; studio.pv.playing = true; studio_playGlyph();
        const b = document.getElementById('studio-play-btn');
        window.__pb = {clicks: 0, spin: true, icon: b.querySelector('svg')};
        b.addEventListener('click', e => { e.stopPropagation(); window.__pb.clicks++; }, {capture: true, once: true});
        const spin = () => { studio_playGlyph(); if (window.__pb.spin) requestAnimationFrame(spin); };
        requestAnimationFrame(spin);
    }""")
    p = pg.locator("#studio-play-btn").bounding_box()
    pg.mouse.move(p["x"] + p["width"] / 2, p["y"] + p["height"] / 2)
    pg.mouse.down()
    pg.wait_for_timeout(150)
    pg.mouse.up()
    held = pg.evaluate("""() => { window.__pb.spin = false; studio.pv.playing = false; studio.pv.on = false;
        const b = document.getElementById('studio-play-btn');
        return {clicks: window.__pb.clicks, same: b.querySelector('svg') === window.__pb.icon}; }""")
    assert held == {"clicks": 1, "same": True}, held
    pg.evaluate("() => studio_playGlyph()")
    # the play button sits in the middle of the bar
    box = pg.evaluate("""() => { const b = document.querySelector('.ed-player-bar').getBoundingClientRect(),
        p = document.getElementById('studio-play-btn').getBoundingClientRect();
        return [b.left + b.width / 2, p.left + p.width / 2]; }""")
    assert abs(box[0] - box[1]) < 4, box
    # zoom is two bare buttons; no Fit, no px/s, no paragraph
    assert [pg.inner_text(f'[data-act="studio-zoom"][data-z="{z}"]').strip() for z in ("-1", "1")] == ["−", "+"]
    assert not pg.query_selector('[data-act="studio-zoom"][data-z="0"]')
    assert not pg.query_selector("#studio-zoomlab")
    assert not pg.query_selector(".ed-hint")
    # the status line says what the reel uses of what was chosen; Actions is a keyboard and its shortcut
    pg.evaluate("() => { studio_syncNote(); }")
    assert pg.is_visible("#studio-palbtn kbd")
    assert "Actions" not in pg.inner_text("#studio-palbtn")
    assert pg.get_attribute("#studio-palbtn", "aria-label") == "Actions"
    assert pg.is_visible('#studio-lanes #studio-snap') is False      # inside the closed menu
    pg.click("#studio-lanes summary")
    assert pg.is_visible('#studio-lanes #studio-snap')
    pg.click("#studio-lanes summary")
    assert not pg.is_visible(".studio-help-pop")
    pg.hover("#studio-help")
    assert "Drag a shot to move it" in pg.inner_text(".studio-help-pop")
    assert pg.is_visible(".studio-help-pop")


def test_a_lane_can_be_put_away_and_comes_back(pg):
    assert pg.is_visible('.studio-labels .st-lab:nth-child(5)')
    pg.click("#studio-lanes summary")
    pg.uncheck('#studio-lanes [data-lane="fx"]')
    assert pg.evaluate("() => STUDIO_ROW.fx") == 0
    assert pg.evaluate("() => document.getElementById('studio-tracks').classList.contains('off-fx')")
    assert not pg.is_visible('.studio-labels .st-lab:nth-child(5)')
    pg.check('#studio-lanes [data-lane="fx"]')
    assert pg.evaluate("() => STUDIO_ROW.fx") > 0
    assert pg.is_visible('.studio-labels .st-lab:nth-child(5)')
    # a press anywhere else shuts the menu
    pg.mouse.click(5, 5)
    assert not pg.evaluate("() => document.getElementById('studio-lanes').open")


def test_a_folded_render_card_leaves_a_chip_with_a_count(pg):
    pin_side(pg)
    assert pg.is_visible("#studio-sync") and not pg.is_visible("#studio-chip")
    pg.click('#studio-sync [data-act="studio-sync-fold"]')
    assert not pg.is_visible("#studio-sync")
    assert pg.is_visible("#studio-chip")
    pg.evaluate("() => { studio.rendering = true; studio.prog = {done: 5, total: 6}; studio_drawSync(); }")
    assert pg.inner_text("#studio-chip-text") == "Rendering 5/6"
    assert "is-busy" in pg.get_attribute("#studio-chip", "class")
    anim = pg.evaluate("() => getComputedStyle(document.querySelector('#studio-chip .studio-chip-dot')).animationName")
    assert anim == "studio-pulse"
    # with the whole panel closed the dot rides on its button
    pg.click("#studio-sidebtn")
    assert pg.is_visible("#studio-sidebtn-dot")
    pg.click("#studio-sidebtn")
    pg.click("#studio-chip")
    assert pg.is_visible("#studio-sync") and not pg.is_visible("#studio-chip")


def test_the_reel_facts_are_a_length_and_a_style_and_nothing_else(pg):
    pg.evaluate("() => { studio.project.style = 'montage'; studio_drawRenderCard(); }")
    text = pg.inner_text("#studio-facts")
    assert "shots" not in text and "BPM" not in text and "9:16" not in text and "16:9" not in text, text
    assert pg.is_visible("#studio-facts .sy-pill.is-len") and pg.is_visible("#studio-facts .sy-pill.is-style")


def test_the_status_line_counts_clips_and_kills(pg):
    pg.evaluate("""() => {
      studio.clipIndex = {a: {id: 'a', path: '/c/a.mp4', kills: [1, 2, 3], kill_count: 3, hs: [true, false, true]},
                          b: {id: 'b', path: '/c/b.mp4', kills: [1, 2], kill_count: 2, hs: [false, false]}};
      studio.project.shots = [{clip: '/c/a.mp4', clip_id: 'a', kill: 1, kills: [1, 3]}];
      studio.derived.selection = [{clip: '/c/a.mp4', in: true}, {clip: '/c/b.mp4', in: false}];
      studio.derived.kills = [1.0, 2.0];
      studio_syncNote(); }""")
    assert pg.inner_text("#studio-tl-sync").replace("\n", " ") == "1/2 clips 2/5 kills 2 HS"
    assert not pg.query_selector("#studio-pv-play"), "the picture has no play button of its own"


def test_below_900px_the_rail_is_always_the_strip_and_the_toggle_steps_aside(pg):
    pg.evaluate("() => { localStorage.setItem('autostream.rail', 'open'); shell_rail(); }")
    assert not rail_min(pg)
    pg.set_viewport_size({"width": 820, "height": 900})
    pg.wait_for_function("() => document.querySelector('.app').classList.contains('rail-min')")
    assert rail_width(pg) < 80 and not pg.is_visible("#rail-toggle")
    pg.set_viewport_size({"width": 1600, "height": 1000})
    pg.wait_for_function("() => !document.querySelector('.app').classList.contains('rail-min')")
    assert rail_width(pg) > 150 and pg.is_visible("#rail-toggle")
