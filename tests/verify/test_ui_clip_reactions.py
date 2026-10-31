r"""The Clips page's "Also clip your reactions" switch (H2), pressed in a browser.

Two switches on this page have shipped wired to nothing -- the whole-match video was
sent by the page and dropped by the server for a year -- so this presses the switch and
reads what the next run would ask for. The server half is tests/test_reactions.py.
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

    home = tmp_path_factory.mktemp("react")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


def test_the_reactions_switch_is_on_by_default_and_turns_off(browser, app):
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("pageerror", lambda e: trouble.append(str(e)))
    try:
        page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
        page.wait_for_function("typeof clip_runBody === 'function'", timeout=30_000)
        page.evaluate("() => go('clips')")
        page.wait_for_selector("#clip-react", state="attached")
        # The options belong to a picked recording; with none, the panel is not drawn.
        page.evaluate("""() => { clip_state.pick = {path: 'C:/verify/rec.mp4', name: 'rec.mp4',
            game: 'VALORANT', duration: 600, size: 1}; clip_renderOptions(); }""")
        assert page.get_attribute("#clip-react", "aria-checked") == "true"
        assert page.evaluate("() => clip_runBody({}).reactions") is True
        page.evaluate("() => document.getElementById('clip-react').click()")
        assert page.get_attribute("#clip-react", "aria-checked") == "false"
        assert page.evaluate("() => clip_runBody({}).reactions") is False
        page.evaluate("() => document.getElementById('clip-react').click()")
        assert page.evaluate("() => clip_runBody({}).reactions") is True
        assert not trouble, trouble
    finally:
        ctx.close()
