r"""The Library's Streams switch (ROADMAP R5), pressed in a browser.

It replaced "Open + stream", a switch that only changed the row's menu while a
detected game went live whatever it said. Off now means the game is recorded and
never streamed -- written to games.yaml where the engine reads it -- and it cannot
be pressed while Records is off, because an ignored game has no session to allow.
"""
from __future__ import annotations

from pathlib import Path

import appd
import pytest
import yaml

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

    home = tmp_path_factory.mktemp("streams")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    (home / "config" / "apps.yaml").write_text(yaml.safe_dump({"apps": [
        {"key": "verifygame", "name": "Verify Game", "path": "C:/nowhere/verifygame.exe",
         "exe": "verifygame.exe", "source": "manual", "stream": True},
    ]}), encoding="utf-8")
    (home / "config" / "games.yaml").write_text(yaml.safe_dump({
        "games": {"verifygame.exe": {"name": "Verify Game"}},
        "blocklist": [], "never_stream_if_running": []}), encoding="utf-8")
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "token": appd.TOKEN, "home": home}
    finally:
        appd.stop(base, proc)


@pytest.fixture
def pg(browser, app):
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("console", lambda m: trouble.append(m.text)
            if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('library')")
    page.wait_for_selector('.lib-row[data-row="verifygame"]', timeout=30_000)
    yield page
    assert not trouble, trouble
    ctx.close()


SW = '.lib-row[data-row="verifygame"] [data-act="lib-golive"]'
REC = '.lib-row[data-row="verifygame"] [data-act="lib-records"]'


def _game(app) -> dict:
    data = yaml.safe_load((Path(app["home"]) / "config" / "games.yaml").read_text(encoding="utf-8"))
    return data


def test_streams_off_records_only_and_the_menu_stops_offering_a_stream(pg, app):
    assert pg.inner_text(SW + " .lib-sw-label") == "Streams"
    assert pg.get_attribute(SW, "aria-checked") == "true"
    pg.click('.lib-row[data-row="verifygame"] [data-act="lib-more"]')
    assert pg.locator('.lib-row[data-row="verifygame"] .lib-mi[data-stream="1"]').count() == 1

    pg.click(SW)
    pg.wait_for_function(f"() => document.querySelector('{SW}').getAttribute('aria-checked') === 'false'")
    pg.wait_for_function("() => !Object.keys(lib_saving).length")
    assert _game(app)["games"]["verifygame.exe"].get("stream") is False
    assert "recorded only" in pg.get_attribute(SW, "title")
    pg.click('.lib-row[data-row="verifygame"] [data-act="lib-more"]')
    assert pg.locator('.lib-row[data-row="verifygame"] .lib-mi[data-stream="1"]').count() == 0

    pg.click(SW)                                 # and back
    pg.wait_for_function("() => !Object.keys(lib_saving).length")
    assert "stream" not in _game(app)["games"]["verifygame.exe"]


def test_streams_cannot_be_pressed_while_records_is_off(pg, app):
    pg.click(REC)
    pg.wait_for_function("() => !Object.keys(lib_saving).length")
    pg.wait_for_function(f"() => document.querySelector('{SW}').getAttribute('aria-disabled') === 'true'")
    assert pg.get_attribute(SW, "aria-checked") == "false"
    pg.click(SW, force=True)
    pg.wait_for_timeout(300)
    assert "stream" not in _game(app)["games"].get("verifygame.exe", {})
    pg.click(REC)                                # Records back on, Streams with it
    pg.wait_for_function("() => !Object.keys(lib_saving).length")
    pg.wait_for_function(f"() => document.querySelector('{SW}').getAttribute('aria-checked') === 'true'")
