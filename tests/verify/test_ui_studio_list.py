r"""Tier 7: the Studio's 2026-10-29 layouts -- the clips as a list with the clip in focus beside it,
the reels as a list with a phone-shaped preview, and the guided maker's steps across the top.

WHY A BROWSER. All of it is markup and keys: a row whose box does not pick, an arrow that moves the
highlight but not the inspector, a grid choice that is forgotten on reload, a preview whose length is
NaN because it was told preload="none" -- every one passes the offline suite. Each test here presses
what a player presses. Nothing here reveals a file: Show in folder opens Explorer, so it is never
pressed (see the sweep's DESTRUCTIVE list).
"""
from __future__ import annotations

import json
import subprocess

import appd
import pytest

pytestmark = pytest.mark.ui

LONG = "A clutch on B site that keeps on going far past sixty characters"


def _mp4(ff, path, size, seconds):
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=size={size}:rate=30:duration={seconds}",
                    "-pix_fmt", "yuv420p", str(path)], check=True, timeout=180,
                   creationflags=appd.NO_WINDOW)


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
    from autostream.clips.tools import binary
    from fakes import free_port

    ff = binary("ffmpeg")
    if not ff:
        pytest.skip("no ffmpeg to make clips with")
    home = tmp_path_factory.mktemp("studiolist")
    run = home / "video" / "clips" / "2026-10-12_2000_VALORANT"
    (run / "clips").mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (kills, cap) in enumerate([(3, LONG), (1, "Opening pick"), (2, "Double on A")]):
        clip = run / "clips" / f"list_{i}.mp4"
        _mp4(ff, clip, "320x180", 3)
        rows.append({"rank": i + 1, "start": 100.0 * (i + 1), "end": 100.0 * (i + 1) + 3, "duration": 3.0,
                     "kills": kills, "name": clip.stem, "master": str(clip), "caption": cap,
                     "at": f"{i + 1}m40s"})
    (run / "clips.json").write_text(json.dumps({"game": "VALORANT", "clips": rows}), encoding="utf-8")
    (run / "session.json").write_text(json.dumps({"game": "VALORANT", "kills": []}), encoding="utf-8")
    reels = home / "video" / "clips" / "reels"
    reels.mkdir(parents=True, exist_ok=True)
    for i, (name, fmt) in enumerate([("Tall one", "vertical"), ("Wide one", "landscape")]):
        mp4 = reels / f"r{i}.mp4"
        _mp4(ff, mp4, "180x320" if fmt == "vertical" else "320x180", 2)
        mp4.with_suffix(".reel.json").write_text(json.dumps({
            "name": name, "style": "montage", "format": fmt, "song": "C:/songs/A song [Remix].mp3",
            "shots": [{"pre": 0.5}], "render": {"length": 2.0, "intro": 0.0}}), encoding="utf-8")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


@pytest.fixture
def pg(browser, app):
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("console", lambda m: trouble.append(m.text)
            if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => { try { localStorage.removeItem('as.studio.view'); } catch (e) {} studio.view = ''; }")
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.wait_for_function("() => studio.lib && studio.lib.games.length", timeout=30_000)
    page.evaluate("() => { studio.selected = []; studio_openRun(studio.lib.games[0].folders[0].folder); }")
    page.wait_for_selector("#studio-lib .studio-crow", timeout=10_000)
    yield page
    assert not trouble, trouble
    ctx.close()


def _focus(pg):
    return pg.evaluate("() => studio.focus")


def _name(pg):
    return pg.inner_text("#studio-cinsp .studio-cinsp-name")


# ------------------------------------------------------------- the clips

def test_the_clips_open_as_a_list_with_the_first_in_focus(pg):
    assert pg.get_attribute("#studio-view-list", "aria-pressed") == "true"
    assert pg.evaluate("() => document.querySelectorAll('#studio-lib .studio-crow').length") == 3
    assert pg.is_visible("#studio-cinsp")
    assert _name(pg) == LONG
    # the hero is gone and Make a reel is still the page's own button, named as before
    assert not pg.evaluate("() => !!document.querySelector('#view-studio .bin-title, #view-studio .bin-eyebrow')")
    assert pg.inner_text("#studio-gd-open") == "Make a reel"


def test_arrows_move_the_focus_and_the_inspector_follows(pg):
    pg.click("#studio-lib .studio-crow .studio-crow-main")
    first = _focus(pg)
    pg.keyboard.press("ArrowDown")
    assert _focus(pg) != first
    assert _name(pg) == "Opening pick"
    assert pg.evaluate("() => document.activeElement.closest('.studio-crow').getAttribute('data-clip')") == _focus(pg)
    pg.keyboard.press("ArrowUp")
    assert _focus(pg) == first


def test_a_adds_the_clip_in_focus_and_takes_it_out_again(pg):
    pg.click("#studio-lib .studio-crow .studio-crow-main")
    pg.keyboard.press("a")
    assert pg.evaluate("() => studio.selected") == [_focus(pg)]
    assert pg.inner_text("#studio-tray-count").startswith("1 clip")
    assert pg.evaluate("() => document.querySelector('#studio-lib .studio-crow').classList.contains('is-on')")
    pg.keyboard.press("a")
    assert pg.evaluate("() => studio.selected") == []


def test_the_rows_box_picks_like_a_tile_does(pg):
    pg.locator("#studio-lib .studio-clip-hit").nth(1).click()
    pg.locator("#studio-lib .studio-clip-hit").nth(2).click()
    assert pg.inner_text("#studio-tray-count").startswith("2 clips")
    kills = pg.locator("#studio-lib .studio-clip-kills")
    assert [kills.nth(i).inner_text().strip() for i in range(3)] == ["3 kills", "1 kill", "2 kills"]


def test_f_favourites_the_clip_in_focus(pg):
    pg.click("#studio-lib .studio-crow .studio-crow-main")
    cid = _focus(pg)
    was = pg.evaluate("(id) => !!studio.clipIndex[id].fav", cid)
    pg.keyboard.press("f")
    pg.wait_for_function("([id, was]) => !!studio.clipIndex[id].fav !== was", arg=[cid, was], timeout=10_000)
    pg.keyboard.press("f")
    pg.wait_for_function("([id, was]) => !!studio.clipIndex[id].fav === was", arg=[cid, was], timeout=10_000)


def test_e_opens_the_clip_in_the_editor(pg):
    pg.click("#studio-lib .studio-crow .studio-crow-main")
    pg.keyboard.press("e")
    pg.wait_for_selector("#studio-imp-scrim:not(.hide)", timeout=10_000)
    pg.keyboard.press("Escape")


def test_grid_is_one_click_away_and_remembered(pg, app):
    pg.click("#studio-view-grid")
    assert pg.evaluate("() => document.querySelectorAll('#studio-lib .studio-crow').length") == 0
    assert pg.evaluate("() => document.querySelectorAll('#studio-lib .studio-grid .studio-clip').length") == 3
    assert not pg.is_visible("#studio-cinsp")
    pg.reload(wait_until="domcontentloaded")
    pg.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    pg.evaluate("() => go('studio')")
    pg.wait_for_function("() => studio.lib && studio.lib.games.length", timeout=30_000)
    pg.evaluate("() => studio_openRun(studio.lib.games[0].folders[0].folder)")
    pg.wait_for_selector("#studio-lib .studio-grid .studio-clip", timeout=10_000)
    assert pg.get_attribute("#studio-view-grid", "aria-pressed") == "true"
    pg.click("#studio-view-list")
    assert pg.evaluate("() => localStorage.getItem('as.studio.view')") == "list"


def test_a_long_name_truncates_rather_than_wrapping_the_row(pg):
    pg.set_viewport_size({"width": 1200, "height": 900})
    pg.wait_for_timeout(200)
    got = pg.evaluate("""() => {
        const row = document.querySelector('#studio-lib .studio-crow');
        const name = row.querySelector('.studio-crow-name .truncate');
        const ins = document.querySelector('#studio-cinsp .studio-cinsp-name');
        return {h: row.getBoundingClientRect().height, cut: name.scrollWidth > name.clientWidth,
                ih: ins.getBoundingClientRect().height, icut: ins.scrollWidth > ins.clientWidth};
    }""")
    assert got["h"] < 60, got
    assert got["cut"], got
    assert got["ih"] < 30, got
    assert got["icut"], got


def test_the_games_are_in_the_sidebar(pg):
    names = pg.evaluate("() => [...document.querySelectorAll('#rail-section [data-act=\"studio-game\"]')]"
                        ".map(b => b.textContent)")
    assert any(n.startswith("VALORANT") for n in names), names
    assert any(n.startswith("Favourites") for n in names), names
    pg.click('#rail-section [data-act="studio-game"][data-game="all"]')
    assert pg.evaluate("() => studio.game") == "all"
    assert pg.evaluate("() => document.querySelectorAll('#studio-lib .studio-folder-card').length") >= 2


# ------------------------------------------------------------- the reels

def _reels(pg):
    pg.evaluate("() => studio_tab('reels')")
    pg.wait_for_selector("#studio-reel-grid .studio-reel", timeout=10_000)


def test_a_chosen_reel_plays_in_its_own_shape(pg):
    _reels(pg)
    assert pg.evaluate("() => document.querySelectorAll('#studio-reel-grid .studio-reel').length") == 2
    row = pg.evaluate("() => document.querySelector('#studio-reel-grid .studio-reel').textContent")
    assert "A song" in row and "[Remix]" not in row, row
    v = pg.locator("#studio-rvideo")
    assert v.get_attribute("preload") == "metadata"
    pg.wait_for_function("() => { const v = document.getElementById('studio-rvideo');"
                         " return v && isFinite(v.duration) && v.duration > 1; }", timeout=15_000)
    tall = pg.evaluate("() => { const r = document.querySelector('.studio-rphone').getBoundingClientRect();"
                       " return r.height / r.width; }")
    assert 1.7 < tall < 1.85, tall
    pg.click("#studio-reel-grid .studio-reel:nth-child(2) .studio-reel-main")
    assert pg.inner_text("#studio-rinsp .studio-rinsp-name") == "Wide one"
    assert pg.evaluate("() => document.querySelector('.studio-rphone').classList.contains('is-wide')")


def test_enter_opens_the_chosen_reels_timeline(pg):
    _reels(pg)
    pg.evaluate("() => { window.__opened = ''; studio_open = (p) => { window.__opened = p; }; }")
    pg.click("#studio-reel-grid .studio-reel .studio-reel-main")
    pg.keyboard.press("ArrowDown")
    pg.keyboard.press("Enter")
    assert pg.evaluate("() => window.__opened").endswith("r0.mp4") or pg.evaluate("() => window.__opened").endswith("r1.mp4")
    assert pg.evaluate("() => window.__opened") == pg.evaluate("() => studio.reelSel")


def test_delete_is_in_the_rows_menu_and_still_asks(pg):
    _reels(pg)
    assert not pg.is_visible('#studio-reel-grid [data-act="studio-reel-del"]')
    pg.click('#studio-reel-grid .studio-reel [data-act="studio-reel-menu"]')
    pg.click('#studio-reel-grid .studio-reel [data-act="studio-reel-del"]')
    pg.wait_for_selector("#studio-rdel-scrim:not(.hide)", timeout=10_000)
    pg.click('[data-act="studio-rdel-cancel"]')
    assert pg.evaluate("() => document.querySelectorAll('#studio-reel-grid .studio-reel').length") == 2


# ------------------------------------------------------------- the maker

def test_the_makers_steps_are_tabs_in_todays_order_and_enter_is_next(pg):
    pg.evaluate("() => studio_tab('clips')")
    pg.click("#studio-gd-open")
    pg.wait_for_selector("#studio-guide-scrim:not(.hide)", timeout=10_000)
    steps = pg.evaluate("() => [...document.querySelectorAll('#studio-gd-steps .gd-step')]"
                        ".map(b => b.textContent.replace(/^\\S+\\s*Step \\d+: /, ''))")
    assert steps == ["Style", "Clips", "Song", "Look", "Check and make"], steps
    pg.click('.gd-card[data-key="montage"]')
    assert "Montage" in pg.inner_text("#studio-gd-reel")
    pg.keyboard.press("Enter")
    pg.wait_for_function("() => studio.gd.step === 1", timeout=5_000)
    # a done step is a tab back to it
    pg.click('#studio-gd-steps .gd-step[data-i="0"]')
    pg.wait_for_function("() => studio.gd.step === 0", timeout=5_000)
    pos = pg.evaluate("() => getComputedStyle(document.querySelector('#studio-gd .gd-foot')).position")
    assert pos == "sticky"
    pg.evaluate("() => studio_gdClose()")
