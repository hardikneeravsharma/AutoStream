r"""Tier 7: finding a setting among ninety, and reaching a section that scrolled.

TWO ITEMS FROM THE UI REVIEW, both about the same page and both about not
being able to get to something that is there.

  #8  Ninety keys across fifteen sections, and the only way in was knowing
      which section somebody had filed one under. The names are not always
      the guess a person makes: clip length is under Clips, clip upload
      privacy is under Clips too, and stream privacy is under Stream.

  #6  Below 1000px the section nav is one horizontal strip with its scrollbar
      hidden, so the last visible section was cut mid-word and nothing said
      the rest existed. The page read as though it had eight sections and a
      rendering fault.

Driven in a browser at both widths, because the whole of #6 only exists at
one of them and no amount of reading the stylesheet shows whether a box
overflows.
"""
from __future__ import annotations

import appd
import pytest

pytestmark = pytest.mark.ui

WIDE = {"width": 1500, "height": 950}     # the nav is a column here
NARROW = {"width": 860, "height": 900}    # and a scrolling strip here


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("find-home")
    port = free_port()
    appd.seed_home(home, port)
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


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


def _open(browser, app, viewport):
    ctx = browser.new_context(viewport=viewport)
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("console",
            lambda m: trouble.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('settings')")
    page.wait_for_selector("#view-settings.is-active", state="attached")
    # WAIT FOR THE DATA, not for a guess at how long it takes. The schema is
    # fetched, so for a moment the page is a spinner with no sections in it --
    # and `set_showSection` against an empty list silently does nothing, which
    # then reads as a section that refuses to open.
    page.wait_for_function(
        "() => typeof set_state !== 'undefined' && set_state.sections.length > 0",
        timeout=30_000)
    page.wait_for_selector("#set-nav .settings-nav-item", state="visible")
    page.trouble = trouble
    page.ctx = ctx
    return page


@pytest.fixture
def pg(browser, app):
    page = _open(browser, app, WIDE)
    yield page
    page.ctx.close()


@pytest.fixture
def narrow(browser, app):
    page = _open(browser, app, NARROW)
    yield page
    page.ctx.close()


def _type(pg, text):
    pg.fill("#set-search", text)
    pg.wait_for_timeout(250)


def _choose_platform(pg, name):
    pg.evaluate("""(n) => {
        const el = document.getElementById('set-f-youtube-platform');
        el.value = n;
        el.dispatchEvent(new Event('change', {bubbles: true}));
    }""", name)
    pg.wait_for_timeout(300)


def _visible_paths(pg):
    return pg.evaluate(
        """() => Array.from(
             document.querySelectorAll('#set-panels .field[data-path]'))
           .filter(e => !e.classList.contains('hide')
                     && !e.closest('.settings-section').classList.contains('hide'))
           .map(e => e.getAttribute('data-path'))""")


# ------------------------------------------------------------ #8, searching

def test_the_search_box_is_there_without_being_looked_for(pg):
    assert pg.locator("#set-search").is_visible()


def test_a_key_can_be_pasted_in_whole(pg):
    """People copy keys out of the log and out of the docs. A search that only
    matched labels would reject the most precise thing a user can give it."""
    _type(pg, "clips.min_kills")
    assert _visible_paths(pg) == ["clips.min_kills"]


def test_a_word_from_the_explanation_finds_it(pg):
    """The word somebody remembers is usually in the help text. "quota"
    appears in no label anywhere on this page."""
    _type(pg, "quota")
    found = _visible_paths(pg)
    assert found, "nothing matched a word that is in several help texts"
    assert any("quota" in p for p in found) or len(found) >= 1


def test_it_reaches_across_sections_rather_than_within_one(pg):
    """The point of the feature: you do not have to know where it was filed.
    "privacy" is one key under Stream and another under Clips."""
    _type(pg, "privacy")
    found = _visible_paths(pg)
    secs = pg.evaluate(
        """() => Array.from(document.querySelectorAll('.settings-section'))
             .filter(s => !s.classList.contains('hide'))
             .map(s => s.getAttribute('data-sec'))""")
    assert len(found) >= 2, found
    assert len(secs) >= 2, f"the results came from one section only: {secs}"


def test_two_words_narrow_rather_than_widen(pg):
    """Every term has to match. Anything else turns a second word into more
    results, which is the opposite of what typing it meant."""
    _type(pg, "clip")
    broad = len(_visible_paths(pg))
    _type(pg, "clip upload")
    narrow = len(_visible_paths(pg))
    assert narrow < broad, f"{narrow} results for two words, {broad} for one"
    assert narrow >= 1


def test_the_count_says_how_many(pg):
    _type(pg, "clips.min_kills")
    assert pg.locator("#set-search-count").inner_text().strip() == "1 setting"
    _type(pg, "")
    assert pg.locator("#set-search-count").inner_text().strip() == ""


def test_a_search_that_matches_nothing_says_so(pg):
    """An empty page reads as a page that failed to load."""
    _type(pg, "zzzz-no-such-setting")
    assert _visible_paths(pg) == []
    panel = pg.locator("#set-noresult")
    assert panel.is_visible()
    assert "zzzz-no-such-setting" in panel.inner_text()


def test_a_match_folded_inside_advanced_is_opened(pg):
    """A result nobody can see is not a result. The folds are opened only
    while searching."""
    hidden_in_fold = pg.evaluate(
        """() => {
             const d = document.querySelector('#set-panels details.panel');
             if (!d) return null;
             const f = d.querySelector('.field[data-path]');
             return f ? f.getAttribute('data-path') : null;
           }""")
    if not hidden_in_fold:
        pytest.skip("no advanced fold on this page")
    _type(pg, hidden_in_fold)
    assert pg.evaluate(
        """(p) => {
             const f = document.querySelector('.field[data-path="' + p + '"]');
             const d = f.closest('details.panel');
             return !d || d.hasAttribute('open');
           }""", hidden_in_fold), "the match stayed folded shut"


def test_clearing_puts_the_page_back_as_it_was(pg):
    before = _visible_paths(pg)
    _type(pg, "privacy")
    _type(pg, "")
    assert _visible_paths(pg) == before
    assert not pg.locator("#set-noresult").is_visible()


def test_the_nav_stays_while_searching(pg):
    """Hiding it left clearing the box as the only way out of a search, and a
    page that removes its own navigation when you type in it reads as having
    gone somewhere else."""
    _type(pg, "privacy")
    assert pg.locator("#set-nav").is_visible()
    assert pg.locator("#set-nav .settings-nav-item").count() > 1


def test_a_fold_the_search_opened_is_shut_again_afterwards(pg):
    """Searching once must not leave every Advanced section on the page
    hanging open: that is a different page from the one the user had."""
    shut = pg.evaluate(
        """() => Array.from(document.querySelectorAll('#set-panels details.panel'))
             .filter(d => !d.hasAttribute('open')).length""")
    if not shut:
        pytest.skip("every fold was already open")
    _type(pg, "clip")
    _type(pg, "")
    after = pg.evaluate(
        """() => Array.from(document.querySelectorAll('#set-panels details.panel'))
             .filter(d => !d.hasAttribute('open')).length""")
    assert after == shut, (
        f"{shut} folds were shut before the search and {after} after it")


def test_escape_clears_it(pg):
    _type(pg, "privacy")
    pg.focus("#set-search")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(250)
    assert pg.input_value("#set-search") == ""
    assert pg.locator("#set-nav").is_visible()


def test_pressing_a_section_leaves_the_search(pg):
    """Choosing a section means "show me that section", which it cannot do
    while results from every section are on screen."""
    _type(pg, "privacy")
    pg.click("#set-nav .settings-nav-item[data-sec='obs']")
    pg.wait_for_timeout(300)
    assert pg.input_value("#set-search") == ""
    assert pg.evaluate("() => set_state.active") == "obs"


def test_searching_does_not_fight_the_platform_gate(pg):
    """THE BUG THIS SHAPE EXISTS TO AVOID. Hiding a row for the platform and
    hiding a row for a search are two reasons toggling one class; done in two
    passes the later one wins, and a YouTube-only setting reappears on Twitch
    the moment somebody searches for it."""
    pg.click("#set-nav .settings-nav-item[data-sec='stream']")
    pg.wait_for_selector("#set-f-youtube-platform", state="visible")
    # Set and fire the change rather than driving the widget. The dropdown
    # itself is exercised in test_ui_platform_choice, which is where it
    # belongs; what is under test here is what the two filters do to each
    # other, and this is exactly the event the page's own handler receives.
    _choose_platform(pg, "twitch")

    _type(pg, "privacy")
    shown = _visible_paths(pg)
    assert "youtube.privacy" not in shown, (
        "a setting Twitch does not have came back through the search")

    # And it is still gone when the search is cleared, rather than the search
    # having been what hid it.
    _type(pg, "")
    assert "youtube.privacy" not in _visible_paths(pg)

    _choose_platform(pg, "youtube")
    assert "youtube.privacy" in _visible_paths(pg)


def test_nothing_threw_while_searching(pg):
    _type(pg, "clip")
    _type(pg, "privacy quota")
    _type(pg, "")
    assert pg.trouble == []


# -------------------------------------------------------- #6, the nav strip

def test_the_nav_really_does_overflow_at_this_width(narrow):
    """The premise of everything below. If it stops overflowing the rest of
    these tests would pass by describing nothing."""
    over = narrow.evaluate(
        """() => { const n = document.getElementById('set-nav');
                   return n.scrollWidth - n.clientWidth; }""")
    assert over > 2, f"the nav fits at {NARROW['width']}px; over = {over}"


def test_it_says_there_is_more_to_the_right(narrow):
    """THE REPORTED DEFECT: cut mid-word with no affordance."""
    assert "set-more-end" in (
        narrow.get_attribute("#set-nav", "class") or "")
    assert "set-more-start" not in (
        narrow.get_attribute("#set-nav", "class") or ""), (
        "it claims there is something off the left edge at scroll position 0")


def test_the_edges_follow_the_scroll(narrow):
    narrow.evaluate(
        """() => { const n = document.getElementById('set-nav');
                   n.scrollLeft = n.scrollWidth; }""")
    narrow.wait_for_timeout(400)
    cls = narrow.get_attribute("#set-nav", "class") or ""
    assert "set-more-start" in cls, "nothing said the start had scrolled away"
    assert "set-more-end" not in cls, "it claims more past the end of the end"


def test_choosing_a_section_brings_it_into_view(narrow):
    """A nav item off the end of the strip reads as one that was not pressed."""
    last = narrow.evaluate(
        """() => { const i = document.querySelectorAll('#set-nav .settings-nav-item');
                   return i[i.length - 1].getAttribute('data-sec'); }""")
    narrow.evaluate("() => { document.getElementById('set-nav').scrollLeft = 0; }")
    narrow.evaluate("(s) => set_showSection(s)", last)
    narrow.wait_for_timeout(500)
    assert narrow.evaluate(
        """(s) => {
             const n = document.getElementById('set-nav');
             const b = n.querySelector('[data-sec="' + s + '"]');
             const nb = n.getBoundingClientRect(), bb = b.getBoundingClientRect();
             return bb.left >= nb.left - 2 && bb.right <= nb.right + 2;
           }""", last), "the chosen section stayed off the end of the strip"


def test_a_vertical_wheel_scrolls_the_strip(narrow):
    """A horizontal strip and a mouse that only scrolls vertically: without
    this there is no way to reach the last sections except by dragging a
    scrollbar that is deliberately hidden."""
    narrow.evaluate("() => { document.getElementById('set-nav').scrollLeft = 0; }")
    narrow.hover("#set-nav")
    narrow.mouse.wheel(0, 240)
    narrow.wait_for_timeout(500)
    assert narrow.evaluate(
        "() => document.getElementById('set-nav').scrollLeft") > 0


def test_the_wide_layout_claims_no_overflow(pg):
    """At >=1000px the nav is a column. A fade there would be describing
    something that is not happening."""
    cls = pg.get_attribute("#set-nav", "class") or ""
    assert "set-more-end" not in cls
    assert "set-more-start" not in cls


def test_nothing_threw_on_the_narrow_layout(narrow):
    narrow.evaluate("() => set_showSection('clips')")
    narrow.wait_for_timeout(300)
    assert narrow.trouble == []
