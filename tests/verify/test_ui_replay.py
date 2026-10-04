r"""Tier 7: the instant-replay card, and the metric strip it sits beside.

A3 and the two UI items paired with it.

WHAT THE CARD IS FOR. "On" in the config and not actually running in OBS is
the whole failure mode of a replay buffer -- OBS refuses to hold one unless
it is switched on in its own Output settings, and without a readout the only
sign was a hotkey that did nothing at all. So the pill reports what OBS is
doing, not what the config says, and the line under it names the setting.

The strip above it is #7: it was `repeat(3)` with a comment explaining that a
fixed `repeat(4)` had left a dead quarter -- both the same mistake with a
different number, and the day instant replay landed there was a fourth thing
to put on a dashboard.
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


def _home(tmp_path_factory, **record):
    from fakes import free_port

    why = appd.why_not()
    if why:
        pytest.skip(why)
    home = tmp_path_factory.mktemp("replay")
    port = free_port()
    appd.seed_home(home, port, record=record, rules={"setup_done": True})
    return home, port


def _open(browser, base):
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("console",
            lambda m: trouble.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{base}/?k={appd.TOKEN}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('dash')")
    page.wait_for_selector("#view-dash.is-active", state="attached")
    page.wait_for_timeout(2600)                     # one full status poll
    page.trouble = trouble
    page.ctx = ctx
    return page


@pytest.fixture
def off(browser, tmp_path_factory):
    home, port = _home(tmp_path_factory, enabled=False, replay_enabled=False)
    base, proc = appd.start(home, port)
    page = None
    try:
        page = _open(browser, base)
        yield page
    finally:
        if page:
            page.ctx.close()
        appd.stop(base, proc)


@pytest.fixture
def on(browser, tmp_path_factory):
    """Instant replay switched on, with no OBS anywhere -- which is exactly
    the state the card exists to describe."""
    home, port = _home(tmp_path_factory, enabled=False, replay_enabled=True,
                       replay_seconds=45)
    base, proc = appd.start(home, port)
    page = None
    try:
        page = _open(browser, base)
        yield page
    finally:
        if page:
            page.ctx.close()
        appd.stop(base, proc)


# ------------------------------------------------------------- the card

def test_nothing_is_offered_when_it_is_switched_off(off):
    """A button for a feature that is off is a button that does nothing."""
    assert not off.locator("#dash-replay").is_visible()


def test_the_card_is_there_when_it_is_on(on):
    assert on.locator("#dash-replay").is_visible()


def test_it_says_obs_is_not_holding_a_buffer(on):
    """THE FAILURE MODE. On in the config, not running in OBS -- and before
    this card the only sign was a hotkey that did nothing."""
    assert on.locator("#dash-replay-state").inner_text().strip() == "NOT RUNNING"
    said = on.locator("#dash-replay-note").inner_text()
    assert "Replay Buffer" in said, said
    assert "Output" in said, "it does not say where the setting is"


def test_the_button_is_not_offered_while_there_is_no_buffer(on):
    """Pressing it would ask OBS to save from a buffer that does not exist."""
    assert on.locator("#dash-btn-replay").is_disabled()


def test_the_button_says_how_far_back_it_goes(on):
    """45 seconds was configured; a button reading "last 30 seconds" would be
    describing a different setting."""
    assert "45" in on.locator("#dash-btn-replay").inner_text()


def test_the_status_poll_carries_what_the_card_needs(on):
    s = on.evaluate("async () => await API.get('/api/status')")
    assert s["replay_enabled"] is True
    assert s["replay_seconds"] == 45
    assert s["replay_armed"] is False      # no OBS in this home
    assert s["replay_saved"] == 0


def test_the_command_is_accepted_by_the_server(on):
    """It is on the /api/cmd whitelist, which is the only thing between a
    POST and the engine."""
    got = on.evaluate(
        """async () => {
             const r = await fetch('/api/cmd?k=' + encodeURIComponent(SHELL_K), {
               method: 'POST',
               headers: {'Content-Type': 'application/json'},
               body: JSON.stringify({command: 'replay'})});
             return r.status;
           }""")
    assert got == 200


def test_an_unknown_command_is_still_refused(on):
    """Widening the whitelist by one must not widen it by any more."""
    got = on.evaluate(
        """async () => {
             const r = await fetch('/api/cmd?k=' + encodeURIComponent(SHELL_K), {
               method: 'POST',
               headers: {'Content-Type': 'application/json'},
               body: JSON.stringify({command: 'replay; rm -rf'})});
             return r.status;
           }""")
    assert got == 400


def test_nothing_threw(on):
    assert on.trouble == []


# ------------------------------------------------- #7, the metric strip

def test_the_strip_lays_out_the_cells_it_is_given(on):
    """It was repeat(3), written when there were three. A hard count is the
    same mistake whatever the number."""
    cols = on.evaluate(
        """() => getComputedStyle(document.getElementById('dash-stats'))
             .gridTemplateColumns.split(' ').length""")
    cells = on.evaluate(
        "() => document.querySelectorAll('#dash-stats .stat').length")
    assert cols == cells, f"{cells} cells laid out in {cols} columns"


def test_the_numbers_are_not_crushed_at_a_narrow_width(browser,
                                                        tmp_path_factory):
    """The values are 24px tabular figures and have a width they cannot go
    under; the strip wraps rather than squeezing them."""
    home, port = _home(tmp_path_factory, enabled=False, replay_enabled=True)
    base, proc = appd.start(home, port)
    try:
        ctx = browser.new_context(viewport={"width": 420, "height": 900})
        page = ctx.new_page()
        page.goto(f"{base}/?k={appd.TOKEN}", wait_until="domcontentloaded")
        page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
        page.evaluate("() => go('dash')")
        page.wait_for_timeout(2600)
        overflow = page.evaluate(
            """() => [...document.querySelectorAll('#dash-stats .stat-value')]
                 .filter(e => e.scrollWidth > e.clientWidth + 2).length""")
        assert overflow == 0, f"{overflow} metric values are clipped at 420px"
        assert page.evaluate("document.documentElement.scrollWidth") <= 420
        ctx.close()
    finally:
        appd.stop(base, proc)


# --------------------------------------------- #1, white on an accent fill

def test_no_accent_fill_is_painted_with_hard_white(on):
    """MEASURED, NOT ASSUMED. Four rules filled a shape with var(--accent) and
    wrote #fff on it. That holds for the dark themes that shipped first and
    fails the moment an accent is light -- and the accent is a user setting
    with five palettes behind it. On `carbon` the accent is #EDE7DD and white
    on it measures 1.23:1, which is not a contrast ratio so much as an
    absence of one."""
    got = on.evaluate(
        """() => {
             const bad = [], seen = [];
             for (const sheet of document.styleSheets) {
               let rules;
               try { rules = sheet.cssRules; } catch (e) { continue; }
               for (const r of rules) {
                 if (!r.style) continue;
                 const bg = r.style.getPropertyValue('background') +
                            r.style.getPropertyValue('background-color');
                 if (bg.indexOf('var(--accent)') < 0) continue;
                 seen.push(r.selectorText);
                 const fg = r.style.getPropertyValue('color').trim().toLowerCase();
                 if (fg === '#fff' || fg === '#ffffff' || fg === 'white') {
                   bad.push(r.selectorText);
                 }
               }
             }
             return {bad: bad, seen: seen.length};
           }""")
    # AN EMPTY ANSWER IS NOT A PASS on its own: a stylesheet this cannot read
    # would give exactly the same result as a stylesheet with nothing wrong
    # in it, and the test would then be checking nothing for ever.
    assert got["seen"] >= 8, (
        f"only {got['seen']} accent fills found -- the stylesheet is not being "
        f"read, so this test is not checking anything")
    assert got["bad"] == [], (
        f"accent fills still painted with hard white: {got['bad']}")
