r"""Tier 7: the order of a reel is asked once, in the dialog that makes it.

WHAT WAS WRONG. The order was asked twice, in two places, with different
answers. Inside the Make dialog sat three buttons -- As chosen / Most kills
first / Oldest first -- which only re-sorted the clip list in the page before
it was sent; the server never saw them. The arrangements the planner actually
runs, with the song in hand, were six buttons in the drawers strip at the
foot of the page. So **Best order** -- the one that puts the aces and
multi-kills on the song's biggest hits -- could not be reached from the
dialog where somebody decides how their reel is built, and it went unnoticed
for two releases: "where is the option I asked for about the order of the
clips".

These press the real controls, because the offline suite cannot see a
dialog: a control that renders nothing, or is wired to nothing, passes every
unit test there is.
"""
from __future__ import annotations

import json

import appd
import pytest

pytestmark = pytest.mark.ui

# Every arrangement the page offers, and what each sends as `arrange`.
WANT = ["build", "time", "best", "shuffle", "hits", "fit"]


def _run(root, name, game, clips):
    folder = root / name
    (folder / "clips").mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (start, end, kills) in enumerate(clips):
        master = folder / "clips" / f"{game}_{i:02d}.mp4"
        master.write_bytes(b"x")
        rows.append({"rank": i + 1, "name": master.stem, "master": str(master),
                     "start": start, "end": end, "duration": end - start, "kills": kills})
    (folder / "clips.json").write_text(json.dumps({"game": game, "clips": rows}), encoding="utf-8")
    (folder / "session.json").write_text(
        json.dumps({"game": game, "kills": [], "options": {"pre_roll": 3.5}}), encoding="utf-8")


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

    home = tmp_path_factory.mktemp("order")
    _run(home / "video" / "clips", "2026-10-05_2221_VALORANT", "VALORANT",
         [(10.0, 20.0, 1), (40.0, 52.0, 2), (80.0, 92.0, 3)])
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
    # The clips here are one byte each, so the thumbnail route is correctly
    # refused; that 400 is the server being right about a stub.
    page.on("console",
            lambda m: trouble.append(m.text)
            if m.type == "error" and "studio/thumb" not in m.text
            and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.wait_for_function("() => studio.lib && studio.lib.games.length", timeout=30_000)
    page.trouble = trouble
    page.ctx = ctx
    yield page
    ctx.close()


def _open_make(pg):
    """Pick the seeded run's clips and open the dialog, through the page."""
    pg.evaluate("""() => {
        const f = studio.lib.games[0].folders[0];
        studio_openRun(f.folder);
        studio.selected = f.clips.map(c => c.id);
        studio_syncSelection();
        studio_openMake();
    }""")
    pg.wait_for_selector("#studio-mk-arrange .studio-mk-arr", timeout=10_000)


def test_the_dialog_offers_every_arrangement(pg):
    _open_make(pg)
    got = pg.evaluate("""() => [...document.querySelectorAll('#studio-mk-arrange .studio-mk-arr')]
        .map(e => e.getAttribute('data-how'))""")
    assert got == WANT, got
    # Each one says what it does: two words on a button is how Best order
    # went unnoticed in the strip.
    whys = pg.evaluate("""() => [...document.querySelectorAll('#studio-mk-arrange .studio-mk-arr-why')]
        .map(e => e.textContent.trim().length)""")
    assert all(n > 25 for n in whys), whys


def test_the_two_that_cost_something_say_so(pg):
    _open_make(pg)
    notes = pg.evaluate("""() => {
        const out = {};
        document.querySelectorAll('#studio-mk-arrange .studio-mk-arr').forEach(e => {
            const n = e.querySelector('.studio-mk-arr-note');
            if (n) out[e.getAttribute('data-how')] = n.textContent.trim();
        });
        return out; }""")
    assert notes.get("hits") == "recommended", notes
    assert "30 s" in (notes.get("fit") or ""), notes


def test_the_old_three_way_is_gone(pg):
    """As chosen / Most kills first / Oldest first only sorted the clip list
    in the page. Their meanings live on as Best first and As it happened."""
    assert pg.evaluate("""() => document.querySelectorAll('[data-act="studio-order"]').length""") == 0


def test_pressing_best_order_takes_and_reaches_the_plan(pg):
    _open_make(pg)
    pg.click('#studio-mk-arrange [data-how="hits"]')
    pg.wait_for_function("() => studio.arrange === 'hits'")
    assert pg.evaluate(
        """() => document.querySelector('#studio-mk-arrange [data-how="hits"]')
                .classList.contains('is-on')""")
    sent = pg.evaluate("""() => { let body = null; const real = API.post;
        API.post = function (u, b) {
            if (u === '/api/studio/plan') { body = b; return Promise.resolve({ok: false}); }
            return real.apply(this, arguments); };
        studio_build();
        API.post = real; return body; }""")
    assert (sent or {}).get("shaping", {}).get("arrange") == "hits", sent


def test_the_dialog_and_the_strip_stay_in_step(pg):
    """Two controls over one choice is what this change exists to end: press
    either and both must show it."""
    _open_make(pg)
    pg.click('#studio-mk-arrange [data-how="fit"]')
    pg.wait_for_function("() => studio.arrange === 'fit'")
    assert pg.evaluate(
        """() => document.querySelector('#bin-arrange [data-how="fit"]').classList.contains('is-active')""")
    # ...and the other way round.
    pg.evaluate("""() => document.querySelector('#bin-arrange [data-how="build"]').click()""")
    pg.wait_for_function("() => studio.arrange === 'build'")
    assert pg.evaluate(
        """() => document.querySelector('#studio-mk-arrange [data-how="build"]')
                .classList.contains('is-on')""")


def test_shuffle_re_rolls_rather_than_doing_nothing_twice(pg):
    _open_make(pg)
    pg.click('#studio-mk-arrange [data-how="shuffle"]')
    pg.wait_for_function("() => studio.arrange === 'shuffle'")
    first = pg.evaluate("() => studio.shuffleSeed")
    pg.click('#studio-mk-arrange [data-how="shuffle"]')
    pg.wait_for_timeout(200)
    assert pg.evaluate("() => studio.shuffleSeed") != first


def test_nothing_threw(pg):
    _open_make(pg)
    pg.click('#studio-mk-arrange [data-how="hits"]')
    pg.wait_for_timeout(200)
    assert pg.trouble == []
