r"""Tier 7: walking a batch of clips, and cutting a piece out of one.

FOUR THINGS ASKED FOR ON THE "Added - mark its kills" DIALOG:

    move between the clips you just added, both ways
    say which one of how many you are on
    remove a piece you do not want, and save it
    find the kills in all of them at once

The first two were a queue, not a list: Save shifted the next path off it, so
the batch shrank as you went and there was no way back to the third of twenty
except closing the dialog and finding it in the library.
"""
from __future__ import annotations

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

    home = tmp_path_factory.mktemp("batch")
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
    page.on("console",
            lambda m: trouble.append(m.text)
            if m.type == "error" and "Failed to load resource" not in m.text
            else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.wait_for_timeout(1000)
    page.trouble = trouble
    page.ctx = ctx
    yield page
    ctx.close()


def _batch(pg, n):
    """Put the dialog in front of a batch of `n` clips, without files.

    `studio_impOpen` fetches real clip info, which needs real files; what is
    under test here is the batch chrome, so the state is set directly and the
    chrome asked to draw itself.
    """
    return pg.evaluate(
        """(n) => {
             studio.imp.batch = [];
             for (let i = 0; i < n; i++) studio.imp.batch.push('C:/v/c' + i + '.mp4');
             studio.imp.at = 0;
             studio.imp.dirty = false;
             studio_show('studio-imp-scrim', true);
             studio_impNav();
             return true;
           }""", n)


# ------------------------------------------------- which one of how many

def test_a_batch_says_where_you_are(pg):
    _batch(pg, 5)
    assert pg.locator("#studio-imp-nav").is_visible()
    assert pg.locator("#studio-imp-count").inner_text().strip() == "1 of 5"


def test_the_count_follows_the_clip(pg):
    _batch(pg, 5)
    pg.evaluate("() => { studio.imp.at = 2; studio_impNav(); }")
    assert pg.locator("#studio-imp-count").inner_text().strip() == "3 of 5"


def test_one_clip_on_its_own_shows_no_batch_chrome(pg):
    """A "1 of 1" with two dead arrows is three controls that cannot do
    anything."""
    _batch(pg, 1)
    assert not pg.locator("#studio-imp-nav").is_visible()
    assert not pg.locator("#studio-imp-detectall").is_visible()


def test_the_arrows_stop_at_the_ends(pg):
    _batch(pg, 3)
    assert pg.locator("#studio-imp-prev").is_disabled()
    assert not pg.locator("#studio-imp-next").is_disabled()
    pg.evaluate("() => { studio.imp.at = 2; studio_impNav(); }")
    assert not pg.locator("#studio-imp-prev").is_disabled()
    assert pg.locator("#studio-imp-next").is_disabled()


def test_the_batch_is_not_eaten_as_you_go(pg):
    """THE BUG THIS REPLACES. It was a queue: Save shifted the next path off
    it, so by the third clip the batch was two long and there was no way back
    to the first."""
    _batch(pg, 4)
    pg.evaluate("() => { studio.imp.at = 2; studio_impNav(); }")
    assert pg.evaluate("() => studio.imp.batch.length") == 4
    assert pg.locator("#studio-imp-count").inner_text().strip() == "3 of 4"


def test_find_them_in_all_says_how_many(pg):
    _batch(pg, 7)
    assert pg.locator("#studio-imp-detectall").is_visible()
    assert "7" in pg.locator("#studio-imp-detectall").inner_text()


# ------------------------------------------------------ removing a piece

def _cut(pg, a, b):
    return pg.evaluate(
        """([a, b]) => {
             studio.imp.seconds = 20;
             studio.imp.cutFrom = a;
             studio.imp.cutTo = b;
             studio_impCutLabel();
             return {
               label: document.getElementById('studio-imp-cutspan').textContent,
               disabled: document.getElementById('studio-imp-cut').disabled,
               from: studio.imp.cutFrom, to: studio.imp.cutTo
             };
           }""", [a, b])


def test_nothing_chosen_offers_nothing_to_remove(pg):
    got = pg.evaluate(
        """() => {
             studio_impCutClear();
             return {
               label: document.getElementById('studio-imp-cutspan').textContent,
               disabled: document.getElementById('studio-imp-cut').disabled
             };
           }""")
    assert "nothing chosen" in got["label"]
    assert got["disabled"] is True


def test_a_chosen_piece_says_how_long_it_is(pg):
    got = _cut(pg, 5.0, 9.5)
    assert got["disabled"] is False
    assert "4.50s" in got["label"], got["label"]


def test_marking_the_end_first_is_not_a_mistake(pg):
    """Somebody who scrubs to the end of the bit they dislike and presses
    "To here" first has done nothing wrong."""
    got = pg.evaluate(
        """() => {
             const v = document.getElementById('studio-imp-video');
             studio.imp.cutFrom = studio.imp.cutTo = null;
             v.currentTime = 12;  studio_impCutMark('to');
             v.currentTime = 4;   studio_impCutMark('from');
             return {from: studio.imp.cutFrom, to: studio.imp.cutTo};
           }""")
    assert got["from"] < got["to"], got


def test_a_piece_of_no_length_cannot_be_removed(pg):
    assert _cut(pg, 5.0, 5.0)["disabled"] is True


def test_clearing_forgets_it(pg):
    _cut(pg, 2.0, 8.0)
    got = pg.evaluate(
        """() => {
             studio_impCutClear();
             return {from: studio.imp.cutFrom, to: studio.imp.cutTo,
                     disabled: document.getElementById('studio-imp-cut').disabled};
           }""")
    assert got["from"] is None and got["to"] is None
    assert got["disabled"] is True


def test_opening_another_clip_does_not_carry_the_piece_over(pg):
    """A selection left over from the previous clip would offer to cut a
    stretch of a file it was never chosen on."""
    _cut(pg, 2.0, 8.0)
    pg.evaluate(
        """() => {
             /* What studio_impOpen does to the selection on its way in. */
             studio.imp.cutFrom = studio.imp.cutTo = null;
             studio_impCutLabel();
           }""")
    assert pg.evaluate("() => studio.imp.cutFrom") is None


def test_nothing_threw(pg):
    _batch(pg, 3)
    _cut(pg, 1.0, 4.0)
    pg.evaluate("() => studio_impCutClear()")
    assert pg.trouble == []
