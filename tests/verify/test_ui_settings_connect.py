r"""Tier 7: the Connect buttons on the Settings page.

FROM A REPORT: "nothing happens on clicking the connect button". The handler
read `t.getAttribute(...)` where the variable in scope was `btn`, so every
press threw a ReferenceError and the button did nothing at all.

`node --check` passed it, because an undefined variable is not a syntax error
-- it is a runtime one, and only running the handler finds it. That is the
whole reason this tier exists, and the bug shipped because I did not run it
after making the change.
"""
from __future__ import annotations

import appd
import pytest

pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("connect-home")
    port = free_port()
    appd.seed_home(home, port)
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


@pytest.fixture
def page(app):
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as e:                               # noqa: BLE001
            pytest.skip(f"chromium will not launch: {e}")
        ctx = browser.new_context(viewport={"width": 1500, "height": 950})
        pg = ctx.new_page()
        trouble: list[str] = []
        pg.on("console",
              lambda m: trouble.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: trouble.append(str(e)))
        pg.goto(f"{app['base']}/?k={app['token']}",
                wait_until="domcontentloaded")
        pg.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
        pg.evaluate("() => go('settings')")
        pg.wait_for_selector("#view-settings.is-active", state="attached")
        pg.wait_for_timeout(2500)
        pg.trouble = trouble
        yield pg
        ctx.close()
        browser.close()


def _open_stream_section(page) -> None:
    page.evaluate("set_showSection('stream')")
    page.wait_for_timeout(500)


def test_the_connect_panel_is_on_the_stream_section(page):
    _open_stream_section(page)
    html = page.inner_text("#set-panels")
    assert "Sign in to a platform" in html
    for label in ("Twitch", "Kick"):
        assert label in html, f"{label} is not offered"
    assert page.trouble == [], page.trouble


@pytest.mark.parametrize("platform", ["twitch", "kick"])
def test_pressing_connect_runs_its_handler(page, platform):
    """THE BUG, pinned. It is not enough that the button exists: the press has
    to reach the handler without throwing. A ReferenceError here is silent to
    the user -- the button simply does nothing."""
    _open_stream_section(page)
    # window.open is stubbed rather than allowed: the real one opens a tab to
    # Twitch during a test run, which is both slow and rude.
    page.evaluate("""() => {
        window.__opened = [];
        window.open = (u) => { window.__opened.push(u); return null; };
    }""")
    btn = page.locator(f'[data-act="connect"][data-platform="{platform}"]')
    if btn.count() == 0:
        pytest.skip(f"{platform} is not offered on this install")
    if btn.first.is_disabled():
        # Correct when there are no credentials: the app cannot ask yet.
        return
    btn.first.click()
    page.wait_for_timeout(2500)
    assert page.trouble == [], (
        f"pressing Connect for {platform} produced: {page.trouble}")


def test_a_platform_with_no_credentials_offers_a_disabled_button(page):
    """The app cannot start a sign-in it has no client id for, and a button
    that looks pressable and is not is worse than one that says so."""
    _open_stream_section(page)
    got = page.evaluate("""() => {
        const out = {};
        document.querySelectorAll('[data-act="connect"]').forEach(b => {
            out[b.getAttribute('data-platform')] = b.disabled;
        });
        return out;
    }""")
    assert got, "no connect buttons rendered at all"
    status = page.evaluate("set_state.platforms")
    for name, disabled in got.items():
        configured = bool((status or {}).get(name, {}).get("configured"))
        assert disabled is not configured, (
            f"{name}: configured={configured} but disabled={disabled}")
