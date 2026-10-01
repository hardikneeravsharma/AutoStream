r"""Tier 7, first run: the setup wizard of the real build, in a real browser.

Its own module because test_ui_playwright.py keeps one built app running for
the whole module, and appd will not start a second copy beside it -- so a
wizard test there was skipped on every full run.
"""
from __future__ import annotations

import appd
import pytest
from test_ui_playwright import Watched

pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def browser():
    api = pytest.importorskip(
        "playwright.sync_api",
        reason="pip install playwright && python -m playwright install chromium")
    with api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:                               # noqa: BLE001
            pytest.skip(f"chromium will not launch: {e}")
        yield b
        b.close()


OVERFLOW_JS = """() => [...document.querySelectorAll('#setup-root button')]
  .filter(e => e.offsetParent && e.scrollHeight > e.clientHeight + 3)
  .map(e => (e.getAttribute('data-act') || e.id) + ': ' + e.scrollHeight +
            'px of content in a ' + e.clientHeight + 'px button')"""


@pytest.mark.parametrize("width", (1500, 390))
def test_the_first_screen_a_new_user_sees_is_legible(browser, tmp_path_factory, width):
    """Every other test here seeds youtube.enabled off, which skips the setup
    wizard -- so its welcome cards shipped from v1.3.2 to v1.39.0 squashed to
    one button's height, text spilling over the heading, and nothing noticed.
    Streaming on with no sign-in is exactly what first run looks like."""
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("ui-setup")
    port = free_port()
    appd.seed_home(home, port, youtube={"enabled": True})
    base, proc = appd.start(home, port)
    try:
        ctx = browser.new_context(viewport={"width": width, "height": 900})
        page = ctx.new_page()
        w = Watched(page, base)
        page.goto(f"{base}/?k={appd.TOKEN}", wait_until="domcontentloaded")
        page.wait_for_selector('#setup-root [data-act="wantClips"]', timeout=30_000)
        page.wait_for_timeout(800)
        assert page.evaluate(OVERFLOW_JS) == []
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        w.clean("the setup wizard's first screen")
        ctx.close()
    finally:
        appd.stop(base, proc)
