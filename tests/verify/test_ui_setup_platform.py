r"""Tier 7: first run, for somebody who is not streaming to YouTube.

A2 + B1, and the two UI items paired with them.

THE WIZARD WAS YOUTUBE END TO END. Nine steps, four of which exist only for
YouTube: a Google Cloud project of your own, an OAuth round trip to Google, a
set of stream settings that are properties of a YouTube broadcast object, and
a finish step that creates a YouTube permanent stream. A Twitch user was
walked through all four for a service they were not going to use.

The first attempt at fixing that answered "already configured" for anything
that was not YouTube, which skipped not the Google steps but the WHOLE
WIZARD -- so a fresh Twitch install opened on a dashboard with no OBS
configured, no apps listed and no stream key anywhere. Both failures are
asserted here.
"""
from __future__ import annotations

import json

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


@pytest.fixture
def wiz(browser, tmp_path_factory):
    """A fresh install mid-first-run: streaming on, nothing signed in."""
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("wiz")
    port = free_port()
    appd.seed_home(home, port, youtube={"enabled": True})
    base, proc = appd.start(home, port)
    ctx = page = None
    try:
        ctx = browser.new_context(viewport={"width": 1400, "height": 950})
        page = ctx.new_page()
        trouble: list[str] = []
        page.on("console",
                lambda m: trouble.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: trouble.append(str(e)))
        page.goto(f"{base}/?k={appd.TOKEN}", wait_until="domcontentloaded")
        page.wait_for_selector('#setup-root [data-act="wantClips"]', timeout=30_000)
        page.wait_for_timeout(600)
        page.trouble = trouble
        page.home = home
        yield page
    finally:
        if ctx:
            ctx.close()
        appd.stop(base, proc)


def _steps(pg):
    return pg.evaluate("() => setup_plan()")


def _labels(pg):
    return pg.evaluate(
        """() => Array.from(document.querySelectorAll('#setup-stepbar .stp'))
             .map(e => e.getAttribute('title'))""")


def _pick_platform(pg, name):
    """Get onto the platform step and choose one, from wherever we are.

    The first version always pressed "Stream and clip", which only exists on
    the welcome step -- so a second call in the same test waited thirty
    seconds for a button that had been replaced four steps ago.
    """
    if pg.locator('#setup-root [data-act="wantStream"]').count():
        pg.click('#setup-root [data-act="wantStream"]')
    else:
        pg.evaluate("() => setup_goName('platform')")
    pg.wait_for_selector(f'#setup-root [data-platform="{name}"]', timeout=15_000)
    pg.click(f'#setup-root [data-platform="{name}"]')
    pg.wait_for_timeout(1200)


# ----------------------------------------- B1: clips-only is the one to take

def test_the_clipper_is_offered_first_and_marked(wiz):
    """Two choices drawn as equals made the ten-minute path look as ordinary
    as the five-second one, and most people arriving here want the clipper."""
    picks = wiz.evaluate(
        """() => Array.from(document.querySelectorAll('#setup-root .pick'))
             .map(e => [e.getAttribute('data-act'), e.className])""")
    assert picks[0][0] == "wantClips", f"streaming is offered first: {picks}"
    assert "is-primary" in picks[0][1]
    assert "is-primary" not in picks[1][1]
    # Upper-cased by the stylesheet, which inner_text reflects.
    assert "RECOMMENDED" in wiz.locator(
        '#setup-root [data-act="wantClips"]').inner_text().upper()


def test_the_first_screen_no_longer_says_youtube_is_the_only_way_to_stream(wiz):
    """It read "Go live on YouTube by itself", which stopped being true."""
    said = wiz.locator('#setup-root [data-act="wantStream"]').inner_text()
    assert "Twitch" in said and "Kick" in said


# ------------------------------------- A2: a wizard shaped like the platform

def test_youtube_still_gets_all_of_its_steps(wiz):
    _pick_platform(wiz, "youtube")
    plan = _steps(wiz)
    for name in ("google", "ytauth", "stream"):
        assert name in plan, f"{name} went missing from the YouTube path: {plan}"


@pytest.mark.parametrize("who", ["twitch", "kick"])
def test_the_google_steps_are_not_in_a_twitch_or_kick_install(wiz, who):
    """THE POINT OF A2. A Google Cloud project and an OAuth round trip to
    Google are of no use to somebody streaming to Twitch."""
    _pick_platform(wiz, who)
    plan = _steps(wiz)
    assert "google" not in plan, plan
    assert "ytauth" not in plan, plan
    assert "connect" in plan, plan


@pytest.mark.parametrize("who", ["twitch", "kick"])
def test_the_youtube_stream_settings_go_too(wiz, who):
    """Who can see the stream, latency, and whether a game switch starts a
    second broadcast are all properties of a YouTube broadcast object. There
    is no broadcast object here."""
    _pick_platform(wiz, who)
    assert "stream" not in _steps(wiz)


def test_the_steps_that_everyone_needs_stay(wiz):
    """The first attempt skipped the whole wizard, so a fresh Twitch install
    had no OBS configured, no apps listed and no branding."""
    _pick_platform(wiz, "twitch")
    plan = _steps(wiz)
    for name in ("obs", "timing", "apps", "branding", "finish"):
        assert name in plan, f"{name} is needed whatever the platform: {plan}"


def test_choosing_twitch_makes_the_wizard_visibly_shorter(wiz):
    _pick_platform(wiz, "youtube")
    long_plan = len(_steps(wiz))
    _pick_platform(wiz, "twitch")
    short_plan = len(_steps(wiz))
    assert short_plan < long_plan, (long_plan, short_plan)
    assert len(_labels(wiz)) == short_plan, "the bar still draws the old length"


def test_the_choice_is_recorded_where_the_engine_reads_it(wiz):
    _pick_platform(wiz, "kick")
    import yaml

    cfg = yaml.safe_load(
        (wiz.home / "config" / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["youtube"]["platform"] == "kick"
    assert cfg["youtube"]["enabled"] is True


def test_the_chosen_one_reads_as_chosen(wiz):
    _pick_platform(wiz, "twitch")
    pg = wiz
    pg.evaluate("() => setup_goName('platform')")
    pg.wait_for_timeout(400)
    on = pg.locator('#setup-root .pick.is-active')
    assert on.count() == 1
    assert on.first.get_attribute("data-platform") == "twitch"
    assert on.first.get_attribute("aria-checked") == "true"


def test_the_sign_in_step_will_not_let_you_past_until_it_can_stream(wiz):
    """Carrying on from here with nothing signed in produces an install whose
    finish step has no key to give OBS."""
    _pick_platform(wiz, "kick")
    wiz.wait_for_selector("#setup-connstate", timeout=15_000)
    assert wiz.locator("#setup-nextb").is_disabled()
    said = wiz.locator("#setup-connstate").inner_text()
    assert said.strip(), "it refuses to continue and does not say why"


def test_twitch_offers_the_key_by_hand_and_kick_does_not(wiz):
    """Twitch has no endpoint for its key and never will; Kick hands its own
    over under `streamkey:read`, so there is nothing to paste."""
    _pick_platform(wiz, "twitch")
    assert wiz.locator("#setup-twkey").count() == 1
    _pick_platform(wiz, "kick")
    assert wiz.locator("#setup-twkey").count() == 0


def test_a_pasted_key_is_enough_for_twitch(wiz):
    """LIVE WITH A STALE TITLE BEATS NOT LIVE: the key is what makes the
    broadcast happen, and the sign-in only sets the title."""
    _pick_platform(wiz, "twitch")
    wiz.fill("#setup-twkey", "live_not_a_real_key")
    wiz.click('#setup-root [data-act="saveTwitchKey"]')
    wiz.wait_for_timeout(1500)
    saved = json.loads(
        (wiz.home / "secrets" / "twitch.json").read_text(encoding="utf-8"))
    assert saved["stream_key"] == "live_not_a_real_key"
    assert not wiz.locator("#setup-nextb").is_disabled(), (
        "a key is enough to go live, and it still refuses to continue")


def test_a_key_with_a_label_pasted_on_it_is_refused(wiz):
    """FROM A REAL HOUR LOST, on the same shape of value."""
    _pick_platform(wiz, "twitch")
    wiz.fill("#setup-twkey", "live_abc - my twitch stream key")
    wiz.click('#setup-root [data-act="saveTwitchKey"]')
    wiz.wait_for_timeout(1200)
    assert "space" in wiz.locator("#setup-connmsg").inner_text().lower()


# --------------------------------------------- #13 and ARIA, the paired items

def test_the_google_steps_are_a_checklist_you_can_keep_your_place_in(wiz):
    """Six separate journeys through a console that looks nothing like this
    page. As a plain list there was no way to mark where you got to."""
    _pick_platform(wiz, "youtube")
    wiz.evaluate("() => setup_goName('google')")
    wiz.wait_for_timeout(400)
    boxes = wiz.locator('#setup-ck-gcloud input[type="checkbox"]')
    assert boxes.count() == 6


def test_a_tick_sticks_across_coming_back_to_the_step(wiz):
    _pick_platform(wiz, "youtube")
    wiz.evaluate("() => setup_goName('google')")
    wiz.wait_for_timeout(400)
    wiz.locator('#setup-ck-gcloud input[type="checkbox"]').nth(3).check()
    wiz.wait_for_timeout(300)
    assert "1 of 6" in wiz.locator("#setup-ck-gcloud-count").inner_text()

    wiz.evaluate("() => setup_goName('obs')")
    wiz.wait_for_timeout(300)
    wiz.evaluate("() => setup_goName('google')")
    wiz.wait_for_timeout(400)
    assert wiz.locator(
        '#setup-ck-gcloud input[type="checkbox"]').nth(3).is_checked(), (
        "the reader's place was lost on leaving the step")


def test_the_step_bar_says_where_you_are(wiz):
    """It was a row of empty divs. A screen reader was told nothing at all."""
    bar = wiz.locator("#setup-stepbar")
    assert bar.get_attribute("role") == "progressbar"
    _pick_platform(wiz, "twitch")
    plan = _steps(wiz)
    assert bar.get_attribute("aria-valuemax") == str(len(plan))
    said = bar.get_attribute("aria-valuetext") or ""
    assert "Step" in said and "of" in said, said
    # The pips themselves are noise read one by one.
    assert wiz.evaluate(
        """() => Array.from(document.querySelectorAll('#setup-stepbar .stp'))
             .every(e => e.getAttribute('aria-hidden') === 'true')""")


def test_every_step_has_a_heading_to_jump_to(wiz):
    """The card title was a styled div, so there was no heading on the only
    screen a new user cannot skip."""
    for name in ("welcome", "platform"):
        wiz.evaluate("(n) => setup_goName(n)", name)
        wiz.wait_for_timeout(300)
        assert wiz.locator("#setup-stepcard h1").count() == 1, name
        assert wiz.locator("#setup-stepcard h1").inner_text().strip()


def test_what_the_wizard_reports_is_announced(wiz):
    """These slots carry every result the wizard gives -- without a live
    region a screen reader user pressed a button and heard nothing, ever."""
    _pick_platform(wiz, "twitch")
    wiz.fill("#setup-twkey", "live_announced_key")
    wiz.click('#setup-root [data-act="saveTwitchKey"]')
    wiz.wait_for_timeout(1200)
    msg = wiz.locator("#setup-connmsg")
    assert msg.get_attribute("role") == "status"
    assert msg.get_attribute("aria-live") in ("polite", "assertive")


def test_focus_follows_the_step(wiz):
    """The card is replaced wholesale, so focus fell back to the top of the
    document -- tabbing from the bottom of a long step started at the logo."""
    _pick_platform(wiz, "twitch")
    assert wiz.evaluate(
        "() => document.activeElement && document.activeElement.id") == \
        "setup-stepcard"


def test_nothing_threw_through_the_whole_first_run(wiz):
    _pick_platform(wiz, "twitch")
    _pick_platform(wiz, "kick")
    _pick_platform(wiz, "youtube")
    wiz.evaluate("() => setup_goName('google')")
    wiz.wait_for_timeout(400)
    wiz.evaluate("() => setup_goName('obs')")
    wiz.wait_for_timeout(400)
    assert wiz.trouble == []
