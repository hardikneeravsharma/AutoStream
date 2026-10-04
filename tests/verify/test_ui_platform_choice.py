r"""Tier 7: choosing a platform, and the settings that stop applying when you do.

TWO REPORTS, ONE CAUSE. With Twitch selected the Settings page still offered
"Who can see your streams", a privacy choice Twitch does not have -- so a
stream set to Unlisted went out public and the page had said otherwise. And
the choice itself lived only in Settings, three clicks deep, when it is the
thing you most want to confirm before pressing go.

Pressed in a real browser rather than read. The last two defects in this area
were a ReferenceError and a class name that did not match the stylesheet --
neither is a syntax error, and neither is visible in the source.
"""
from __future__ import annotations

import appd
import pytest

pytestmark = pytest.mark.ui

# What the page must stop offering once the platform is not YouTube. Each is a
# real capability gap, not a tidying-up: Twitch and Kick have no privacy
# setting, no latency choice, no "made for kids" flag, no second broadcast to
# start, and no private preview to hold a stream in.
YOUTUBE_ONLY = [
    "youtube.privacy",
    "youtube.latency",
    "youtube.category_id",
    "youtube.made_for_kids",
    "youtube.switch_policy",
]


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("platform-home")
    port = free_port()
    # GOING LIVE IS ON HERE, unlike every other tier-7 home. The whole point
    # of this page is which platform a stream goes to, and with streaming off
    # the chooser correctly says so and stops naming platforms -- which would
    # make every assertion below pass for the wrong reason.
    #
    # And it is dressed as a finished YouTube install -- a stream id and a
    # token file -- because the setup wizard stands in front of the dashboard
    # until one exists, and YouTube is the case these tests need to see. The
    # values are never used: nothing here can reach Google, and the engine
    # never starts a session because no game is running.
    appd.seed_home(home, port,
                   youtube={"enabled": True, "platform": "youtube",
                            "stream_id": "verify-stream-id"})
    (home / "secrets").mkdir(parents=True, exist_ok=True)
    (home / "secrets" / "token.json").write_text(
        '{"token": "not-a-real-token", "refresh_token": "nor-this"}',
        encoding="utf-8")
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


@pytest.fixture
def pg(app):
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as e:                               # noqa: BLE001
            pytest.skip(f"chromium will not launch: {e}")
        ctx = browser.new_context(viewport={"width": 1500, "height": 950})
        page = ctx.new_page()
        trouble: list[str] = []
        page.on("console",
                lambda m: trouble.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: trouble.append(str(e)))
        page.goto(f"{app['base']}/?k={app['token']}",
                  wait_until="domcontentloaded")
        page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
        page.trouble = trouble
        yield page
        ctx.close()
        browser.close()


def _settings(pg):
    pg.evaluate("() => go('settings')")
    pg.wait_for_selector("#view-settings.is-active", state="attached")
    pg.wait_for_timeout(2000)
    pg.evaluate("() => set_showSection('stream')")
    pg.wait_for_timeout(200)


def _shown(pg, path):
    """Is this field's row actually on the page, hidden or not."""
    return pg.evaluate(
        """(p) => {
            const el = document.querySelector('.field[data-path="' + p + '"]');
            if (!el) return null;
            return !el.classList.contains('hide');
        }""", path)


def _choose(pg, name):
    pg.select_option("#set-f-youtube-platform", name)
    pg.wait_for_timeout(300)


# ------------------------------------------- the settings that stop applying

def test_youtube_shows_all_of_its_own_settings(pg):
    _settings(pg)
    _choose(pg, "youtube")
    for path in YOUTUBE_ONLY:
        assert _shown(pg, path) is True, f"{path} should be offered on YouTube"


@pytest.mark.parametrize("platform", ["twitch", "kick"])
def test_the_settings_that_platform_does_not_have_go_away(pg, platform):
    """THE REPORTED BUG. Privacy is the one that can actually hurt: a stream
    set to Unlisted on a page that is talking to Twitch goes out public."""
    _settings(pg)
    _choose(pg, platform)
    for path in YOUTUBE_ONLY:
        assert _shown(pg, path) is False, (
            f"{path} is still offered on {platform}, which does not have it")


def test_the_private_hold_goes_too_because_there_is_no_preview(pg):
    """`timing.abort_grace` is the window the kill switch acts in, and it
    exists because YouTube holds a broadcast privately first. Twitch is live
    the moment the stream arrives, so the setting describes nothing."""
    _settings(pg)
    _choose(pg, "twitch")
    pg.evaluate("() => set_showSection('timing')")
    pg.wait_for_timeout(200)
    assert _shown(pg, "timing.abort_grace") is False


def test_switching_back_returns_them_untouched(pg):
    """Hiding a control must not be a way of changing it."""
    _settings(pg)
    before = pg.evaluate(
        "() => JSON.stringify(['youtube.privacy','youtube.latency']"
        ".map(p => set_state.values[p]))")
    _choose(pg, "twitch")
    _choose(pg, "youtube")
    after = pg.evaluate(
        "() => JSON.stringify(['youtube.privacy','youtube.latency']"
        ".map(p => set_state.values[p]))")
    assert before == after
    for path in YOUTUBE_ONLY:
        assert _shown(pg, path) is True


def test_the_gap_is_explained_where_the_gap_is(pg):
    """Five rows vanishing with no word about why reads as a broken page."""
    _settings(pg)
    _choose(pg, "twitch")
    note = pg.locator("#set-panels .settings-only-note[data-sec='stream']")
    assert note.is_visible()
    said = note.inner_text()
    assert "Twitch" in said
    assert "not changed" in said


def test_no_note_when_nothing_is_hidden(pg):
    _settings(pg)
    _choose(pg, "youtube")
    note = pg.locator("#set-panels .settings-only-note[data-sec='stream']")
    assert not note.is_visible()


# ------------------------------------------------- the dashboard chooser

def _dash(pg):
    pg.evaluate("() => go('dash')")
    pg.wait_for_selector("#view-dash.is-active", state="attached")
    pg.wait_for_timeout(2500)


def test_the_chooser_is_on_the_dashboard_without_being_asked_for(pg):
    """THE SECOND REPORT: it should have been always there."""
    _dash(pg)
    assert pg.locator("#dash-where").is_visible()
    assert pg.locator("#dash-where-seg .seg-btn").count() == 3


def test_exactly_one_platform_reads_as_chosen(pg):
    _dash(pg)
    on = pg.locator("#dash-where-seg .seg-btn.is-active")
    assert on.count() == 1, "the chooser must say which one it is on"
    assert on.first.get_attribute("aria-checked") == "true"


def test_pressing_one_moves_the_selection_and_sticks(pg):
    """The class is `is-active`, which is what the stylesheet styles. An
    earlier control in this app toggled `is-on` and looked dead on click."""
    _dash(pg)
    pg.click("#dash-where-seg [data-platform='twitch']")
    pg.wait_for_timeout(1200)
    on = pg.locator("#dash-where-seg .seg-btn.is-active")
    assert on.count() == 1
    assert on.first.get_attribute("data-platform") == "twitch"

    # And it is a saved setting, not a highlight: the Settings page, which
    # reads the config afresh, has to agree.
    _settings(pg)
    assert pg.input_value("#set-f-youtube-platform") == "twitch"


def test_what_it_chose_reaches_the_server(pg):
    _dash(pg)
    pg.click("#dash-where-seg [data-platform='kick']")
    pg.wait_for_timeout(1200)
    got = pg.evaluate("async () => (await API.get('/api/status')).platform")
    assert got == "kick"


def test_the_note_says_what_changes_about_going_live(pg):
    """The countdown is the difference that matters: on Twitch and Kick there
    is no window to cancel in, and that is worth knowing before the press."""
    _dash(pg)
    pg.click("#dash-where-seg [data-platform='twitch']")
    pg.wait_for_timeout(1200)
    said = pg.locator("#dash-where-note").inner_text()
    assert "no countdown" in said

    pg.click("#dash-where-seg [data-platform='youtube']")
    pg.wait_for_timeout(1200)
    assert "countdown" in pg.locator("#dash-where-note").inner_text()


def test_the_api_budget_is_not_shown_for_a_platform_that_has_none(pg):
    """A meter reading 0 / 10,000 units during a Twitch stream is reporting
    on another service entirely."""
    _dash(pg)
    pg.click("#dash-where-seg [data-platform='twitch']")
    pg.wait_for_timeout(2600)       # one full status poll
    assert not pg.locator("#dash-session").is_visible()

    pg.click("#dash-where-seg [data-platform='youtube']")
    pg.wait_for_timeout(2600)
    assert pg.locator("#dash-session").is_visible()


def test_nothing_threw_while_all_that_happened(pg):
    _dash(pg)
    pg.click("#dash-where-seg [data-platform='twitch']")
    pg.wait_for_timeout(600)
    pg.click("#dash-where-seg [data-platform='youtube']")
    pg.wait_for_timeout(600)
    _settings(pg)
    _choose(pg, "twitch")
    _choose(pg, "youtube")
    assert pg.trouble == []
