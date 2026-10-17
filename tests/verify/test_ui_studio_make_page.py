r"""Tier 7: the Make a reel PAGE (M1-M6).

It used to be a dialog. This drives the page itself:

    page        a page in the Studio's flow, not an overlay; the rest of the Studio steps aside
    effects     a slot opens a LIST; a set can hold several, each weighted
    kills       planned kills drawn on the song, editable, and sent as `marks` with Build
    styles      a card shows the style cut from the player's own kills
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import appd
import pytest

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

    home = tmp_path_factory.mktemp("length")
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
    page.on("console", lambda m: trouble.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.wait_for_timeout(1000)
    page.trouble = trouble
    yield page
    ctx.close()


def _clips(app, name: str, count: int, seconds: float = 8.0) -> None:
    """A run of `count` real clips, each with its kill in the middle."""
    from autostream.clips.tools import binary

    ff = binary("ffmpeg")
    if not ff:
        pytest.skip("no ffmpeg to make clips with")
    run = Path(app["home"]) / "video" / "clips" / name
    (run / "clips").mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(count):
        clip = run / "clips" / f"len_{i}.mp4"
        subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"testsrc2=size=320x180:rate=30:duration={seconds}",
                        "-f", "lavfi", "-i", f"sine=frequency={300 + 70 * i}:duration={seconds}",
                        "-shortest", "-pix_fmt", "yuv420p", str(clip)], check=True, timeout=180,
                       creationflags=appd.NO_WINDOW)
        rows.append({"rank": i + 1, "start": 10.0 * (i + 1), "end": 10.0 * (i + 1) + seconds,
                     "duration": seconds, "kills": 1, "name": clip.stem, "master": str(clip),
                     "vertical": "", "caption": "", "tags": [], "at": ""})
    (run / "clips.json").write_text(json.dumps({"game": "VALORANT", "clips": rows}))
    (run / "session.json").write_text(json.dumps(
        {"game": "VALORANT", "kills": [{"time": 10.0 * (i + 1) + seconds / 2} for i in range(count)]}))


def _song(app, seconds: float = 60.0) -> Path:
    songs = Path(app["home"]) / "video" / "songs"
    songs.mkdir(parents=True, exist_ok=True)
    return appd.click_track(songs / "length song.wav", seconds=seconds, bpm=120.0)


def _spy(pg, song: Path) -> None:
    """Answer the file dialog with `song`, and keep every plan request."""
    pg.evaluate("""(path) => { window.__plans = []; const real = API.post;
        API.post = function (u, b) {
            if (u === '/api/clips/pick') return Promise.resolve({path: path});
            if (u === '/api/studio/plan') window.__plans.push(JSON.parse(JSON.stringify(b)));
            return real.apply(this, arguments); }; }""", str(song))


def _pick(pg, folder_label: str, picks: int) -> None:
    pg.click('[data-act="studio-refresh"]')
    # The library is a drill-down (U15): open the run this test seeded, then
    # its clips are on screen. Pressing the way in is test_ui_studio_folders'
    # job; this one is about what the plan carries.
    pg.wait_for_function(
        "(n) => studio.lib && (studio.lib.games || []).some("
        "g => g.folders.some(f => f.label.indexOf(n) >= 0))",
        arg=folder_label, timeout=30_000)
    opened = pg.evaluate("""(n) => {
        for (const g of (studio.lib.games || []))
            for (const f of g.folders)
                if (f.label.indexOf(n) >= 0) { studio_openRun(f.folder); return true; }
        return false; }""", folder_label)
    assert opened, f"no run labelled {folder_label!r} in the studio library"
    pg.wait_for_selector("#studio-lib .studio-clip-hit", timeout=30_000)
    if pg.is_visible('[data-act="studio-clear"]'):
        pg.click('[data-act="studio-clear"]')
    tiles = pg.locator("#studio-lib .studio-clip-hit")
    for i in range(picks):
        tiles.nth(i).click()


def _stop_render(pg) -> None:
    """Build renders straight after the plan; this is about the plan."""
    pg.wait_for_function("studio.jobId", timeout=60_000)
    pg.evaluate("API.post('/api/studio/cancel', {})")
    pg.wait_for_function("/^Cancelled|^Ready|fail/i.test(document.getElementById('studio-state').textContent)",
                         timeout=180_000)




def _open(pg, app):
    _clips(app, "2026-10-11_1400_VALORANT", 5)
    song = _song(app)
    _pick(pg, "14:00", 5)
    _spy(pg, song)
    pg.click('[data-act="studio-make"]')
    pg.wait_for_selector("#studio-make-scrim:not(.hide)")
    return song


def test_it_is_a_page_not_a_dialog_and_the_nav_moves_it(pg, app):
    _open(pg, app)
    pos = pg.evaluate("getComputedStyle(document.getElementById('studio-make-scrim')).position")
    assert pos != "fixed", "the Make page is still an overlay"
    assert pg.evaluate("document.getElementById('view-studio').classList.contains('is-making')")
    assert pg.get_attribute("#studio-make", "role") != "dialog"
    for sec in ("look", "song", "kills", "shape", "style"):
        pg.click(f'[data-act="studio-mk-jump"][data-sec="{sec}"]')
        assert pg.evaluate(f"!!document.getElementById('mk-sec-{sec}')")
    # clicking beside it does nothing: a page is left through Back
    pg.mouse.click(5, 5)
    assert pg.is_visible("#studio-make-scrim")
    pg.click("#studio-make-back")
    pg.wait_for_selector("#studio-make-scrim", state="hidden")
    assert not pg.evaluate("document.getElementById('view-studio').classList.contains('is-making')")
    assert pg.trouble == [], pg.trouble


def test_an_effect_slot_opens_a_list_and_a_set_can_hold_several(pg, app):
    _open(pg, app)
    pg.click('#studio-hand [data-act="studio-hand-pick"] >> nth=0')
    pg.wait_for_selector("#studio-fxp-scrim:not(.hide)")
    pg.keyboard.press("Escape")
    pg.evaluate("() => studio_makeSet('transition', ['t01', 't02'])")
    pg.wait_for_selector(".studio-set-chip")
    assert pg.locator(".studio-set-chip").count() >= 2
    pg.click('[data-act="studio-set-weight"][data-d="1"] >> nth=0')
    ids = pg.evaluate("studio_pickIds(studio_template().transition)")
    assert len(ids) == 3, ids
    assert pg.trouble == [], pg.trouble


def test_kills_are_drawn_edited_and_sent_with_build(pg, app):
    _open(pg, app)
    pg.click('[data-act="studio-song"]')
    pg.wait_for_selector("#studio-mk-part:not(.hide)", timeout=60_000)
    pg.wait_for_selector("#studio-mk-killsbox:not(.hide)")
    pg.click('[data-act="studio-mk-plan"]')
    pg.wait_for_function("studio.mk.planned && studio.mk.planned.marks.length > 0", timeout=120_000)
    n = pg.evaluate("studio.mk.planned.marks.length")
    assert pg.locator("#studio-mk-marklist li").count() == n
    # touching one makes them all the player's
    pg.click('[data-act="studio-mk-nudgemark"][data-i="0"][data-d="1"]')
    assert pg.evaluate("studio.mk.edited") is True
    assert pg.locator("#studio-mk-marklist li.is-hand").count() == n
    pg.click('[data-act="studio-mk-delmark"][data-i="0"]')
    assert pg.locator("#studio-mk-marklist li").count() == n - 1
    marks = pg.evaluate("studio.mk.hand")
    body = pg.evaluate("studio_planBody(true)")
    assert body["marks"] == pytest.approx(marks, abs=0.001)
    pg.click('[data-act="studio-mk-clearmarks"]')
    assert "marks" not in pg.evaluate("studio_planBody(true)")
    assert pg.trouble == [], pg.trouble


def test_a_style_card_plays_a_sample_cut_from_the_same_kills(pg, app):
    _open(pg, app)
    pg.wait_for_function("studio.samples.key !== ''", timeout=30_000)
    pg.click('[data-act="studio-samples-start"]')
    pg.wait_for_function("Object.keys(studio.samples.ready).length >= 1 || studio.samples.held", timeout=300_000)
    held = pg.evaluate("studio.samples.held")
    if held:                       # the page refuses, correctly, while a session or recording holds the encoder
        pytest.skip(f"the encoder is held on this machine: {held}")
    pg.click('[data-act="studio-samples-stop"]') if pg.is_visible('[data-act="studio-samples-stop"]') else None
    pg.wait_for_selector(".studio-style-media video", timeout=30_000)
    src = pg.get_attribute(".studio-style-media video >> nth=0", "src")
    assert "/api/studio/sample" in src
    assert pg.trouble == [], pg.trouble


def test_a_list_shows_each_effect_once_and_its_versions_open_from_it(pg, app):
    """566 parts were listed as if each were a new effect -- 104 tint shades, 150
    crossfades. A list now shows each effect once; its versions open when clicked."""
    _open(pg, app)
    pg.evaluate("() => studio_handPick('grade', false)")
    pg.wait_for_selector("#studio-fxp-scrim:not(.hide)")
    grid = '#studio-fxp-list [aria-label="Every option"] .studio-fxp-card'
    pg.wait_for_selector(grid)
    leads = pg.evaluate("studio_leads('grade').length")
    total = pg.evaluate("studio_parts('grade').length")
    assert leads < total / 4, (leads, total)
    assert pg.locator(grid).count() == leads
    assert pg.locator(grid, has_text="Colour tint").count() == 1
    assert pg.locator(grid, has_text="Neon pop").count() == 1
    # the tint's versions open from its own card, and close again
    pg.click('#studio-fxp-list .bin-more[data-group="tint"]')
    pg.wait_for_selector('#studio-fxp-list [aria-label="Versions"]')
    n = pg.locator('#studio-fxp-list [aria-label="Versions"] .studio-fxp-card').count()
    assert n == pg.evaluate("studio_versions('grade', 'tint').length") and n > 50
    pg.click('#studio-fxp-list [data-act="studio-fxp-group"][data-group=""]')
    pg.wait_for_selector(grid)
    assert pg.locator(grid).count() == leads
    # a search still reaches every version
    pg.fill("#studio-fxp-q", "amber")
    pg.wait_for_timeout(300)
    assert pg.locator('#studio-fxp-list [aria-label="Search results"] .studio-fxp-card').count() >= 4
    assert pg.trouble == [], pg.trouble
