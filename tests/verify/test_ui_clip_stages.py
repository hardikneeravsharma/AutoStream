r"""Tier 7: the Clips page's stages, and the buttons on them.

WHY THIS FILE EXISTS. The Clips page was turned from one long scrolling column
into six stages, each a page of its own, and a stage gate is exactly the kind
of change that passes every unit test while leaving a control nobody can
reach. The unit suite cannot see it: `clip_show` is a class toggle, and the
thing worth asserting is whether a person can get to the button at all.

So this opens the real build in Chromium, walks the stages, and presses what
was added or repaired -- the pager, the rail, the fold on the style page, the
framing control whose selection was drawn nowhere, the part player, the save.
It watches the console and every response throughout, because a dead button is
usually a JS error nobody heard.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import appd
import pytest

pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("stage-home")
    port = free_port()
    appd.seed_home(home, port)
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


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


@pytest.fixture
def ui(browser, app):
    from test_ui_playwright import Watched

    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    page = ctx.new_page()
    w = Watched(page, app["base"])
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_selector("#view-dash", state="attached", timeout=30_000)
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.click('.rail-btn[data-page="clips"]')
    page.wait_for_selector("#view-clips.is-active")
    yield w
    ctx.close()


def _recording(app, seconds: int = 200) -> Path:
    """A real recording the page can pick.

    OVER TWO MINUTES on purpose: under that, clip_stripOpen hides the whole
    part stage, so a shorter file would have the test asserting against a page
    that is correctly not there. Written faststart, because whether a recording
    plays whole is one of the things under test.
    """
    from autostream.clips.tools import binary

    ff = binary("ffmpeg")
    if not ff:
        pytest.skip("no ffmpeg to make a recording with")
    out = Path(app["home"]) / "video" / "stage.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.is_file():
        subprocess.run(
            [ff, "-y", "-v", "error", "-f", "lavfi", "-i",
             f"testsrc2=size=640x360:rate=15:duration={seconds}",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
             "-shortest", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             str(out)],
            check=True, timeout=900,
            creationflags=appd.NO_WINDOW)
    hist = Path(app["home"]) / "video" / "history.jsonl"
    hist.parent.mkdir(parents=True, exist_ok=True)
    row = {"session": 1, "game": "VALORANT",
           "game_key": "valorant-win64-shipping.exe",
           "started": 1_790_000_000.0, "ended": 1_790_000_200.0,
           "recording_path": str(out), "recording_seconds": seconds,
           "recording_bytes": out.stat().st_size, "title": "stage test"}
    hist.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return out


def _pick_first(page) -> None:
    """Load the list and choose the first stream.

    NOT by pressing Refresh. The search bar it sits in is hidden while there
    are no streams -- correctly, there is nothing to search -- and the
    recording is written after the page has already loaded, so the button is
    not there to press. Asking the page to load is what Refresh does anyway.
    """
    page.evaluate("clip_load()")
    page.wait_for_function(
        "() => document.querySelectorAll('#clip-list .clip-row').length > 0",
        timeout=30_000)
    page.locator("#clip-list .clip-row").first.click()


def _at_part(ui, app) -> None:
    _recording(app)
    _pick_first(ui.page)
    ui.page.wait_for_function("() => clip_state.step === 'part'", timeout=20_000)


# ------------------------------------------------------------ the stages

def test_picking_a_stream_moves_to_the_next_stage(ui, app):
    """The point of the split: choosing IS finishing a stage."""
    _at_part(ui, app)
    assert ui.page.locator("#clip-listwrap").is_hidden(), \
        "the list it was chosen from is still on screen"
    assert ui.page.locator("#clip-strip-card").is_visible()
    ui.clean("picking a stream")


def test_the_stages_ahead_are_locked_until_there_is_something_in_them(ui, app):
    """FROM A REPORT: 'if I have never clicked on make clips button on style
    page why am I able to go to the next pages?' Review and Clips were
    reachable from the rail with nothing in them, so each opened on a heading
    above an empty panel."""
    _at_part(ui, app)
    locked = ui.page.evaluate(
        "() => clip_steps().filter(s => !s[3]).map(s => s[0])")
    assert "review" in locked and "done" in locked, locked
    for name in ("review", "done"):
        btn = ui.page.locator(f'#clip-rail button[data-val="{name}"]')
        assert btn.count() == 1, f"the {name} stage vanished instead of locking"
        assert btn.is_disabled(), f"{name} opens with nothing in it"
    ui.clean("the locked stages")


def test_next_will_not_walk_past_the_last_open_stage(ui, app):
    _at_part(ui, app)
    # Pressed only while it still offers to go anywhere. Playwright will not
    # click a disabled control, so a fixed number of presses fails at the
    # exact moment the thing under test starts working.
    for _ in range(5):
        if ui.page.locator("#clip-step-next").is_disabled():
            break
        ui.page.click("#clip-step-next")
    assert ui.page.evaluate("clip_state.step") == "style"
    assert ui.page.locator("#clip-step-next").is_disabled()
    ui.clean("walking forward")


def test_back_returns_to_the_stage_it_came_from(ui, app):
    _at_part(ui, app)
    ui.page.click("#clip-step-next")
    assert ui.page.evaluate("clip_state.step") == "style"
    ui.page.click("#clip-step-back")
    assert ui.page.evaluate("clip_state.step") == "part"
    assert ui.page.locator("#clip-strip-card").is_visible()
    ui.clean("going back")


def test_the_rail_opens_a_stage_that_is_already_done(ui, app):
    """Nothing finished is ever locked away: the usual reason to go back is to
    look at something rather than to change it."""
    _at_part(ui, app)
    ui.page.click("#clip-step-next")
    ui.page.click('#clip-rail button[data-val="pick"]')
    assert ui.page.evaluate("clip_state.step") == "pick"
    assert ui.page.locator("#clip-listwrap").is_visible()
    ui.clean("going back by the rail")


# -------------------------------------------------------- the style page

def test_the_details_fold_opens_and_says_what_is_inside_it(ui, app):
    """Progressive disclosure: shut by default, and summarised while shut, so
    nobody has to open it to find out whether it matters."""
    _at_part(ui, app)
    ui.page.evaluate("clip_goStep('style')")
    assert ui.page.locator("#clip-adv-body").is_hidden(), "the fold starts open"
    assert ui.page.inner_text("#clip-adv-sum").strip(), \
        "a shut fold says nothing about what is in it"

    ui.page.click("#clip-adv-btn")
    assert ui.page.locator("#clip-adv-body").is_visible()
    assert ui.page.get_attribute("#clip-adv-btn", "aria-expanded") == "true"
    ui.page.click("#clip-adv-btn")
    assert ui.page.locator("#clip-adv-body").is_hidden()
    assert ui.page.get_attribute("#clip-adv-btn", "aria-expanded") == "false"
    ui.clean("the details fold")


@pytest.mark.parametrize("seg", ["clip-style", "clip-min", "clip-len",
                                 "clip-vert"])
def test_every_choice_on_the_style_page_shows_which_one_is_chosen(ui, app, seg):
    """FROM A REPORT about the framing control: 'the user could not see on
    click what option is selected.' It toggled a class nothing styles, so the
    choice was recorded in the DOM and drawn nowhere. Every segmented control
    here is checked, not only the one that was reported."""
    _at_part(ui, app)
    ui.page.evaluate("clip_goStep('style')")
    # CUSTOM, and the fold open. Clip length is deliberately hidden unless the
    # style is custom -- the preset owns it otherwise -- so a test that did not
    # say so was asserting against a control the app is right to be hiding.
    ui.page.evaluate("clip_state.style = 'custom'; clip_state.adv = true;"
                     " clip_renderOptions(); clip_renderAdv()")
    buttons = ui.page.locator(f"#{seg} .seg-btn")
    n = buttons.count()
    if n < 2 or not buttons.nth(n - 1).is_visible():
        pytest.skip(f"{seg} does not apply to this game")
    buttons.nth(n - 1).click()
    on = ui.page.locator(f"#{seg} .seg-btn.is-active")
    assert on.count() == 1, f"{seg} marks {on.count()} buttons as chosen"
    assert "is-active" in (buttons.nth(n - 1).get_attribute("class") or ""), \
        f"{seg} highlighted a button other than the one pressed"
    ui.clean(f"choosing in {seg}")


def test_the_framing_control_in_the_player_marks_its_choice(ui, app):
    """The exact control reported. It is static HTML rather than built by
    clip_segs, which is how it came to toggle a class of its own."""
    _recording(app)
    ui.page.evaluate("""() => {
        clip_show('clip-player-card', true);
        const c = document.getElementById('clip-player-card');
        c.classList.remove('clip-offstep');
    }""")
    # Clicked through the DOM rather than by pointer: this control lives on
    # the results stage, which is locked until a run has made something, and
    # what is under test is the marking, not whether the stage is open.
    got = ui.page.evaluate("""() => {
        const q = v => document.querySelector('#clip-play-vert [data-vert="' + v + '"]');
        const read = e => ({on: e.classList.contains('is-active'),
                            pressed: e.getAttribute('aria-pressed')});
        q('fit').click();
        const afterFit = {fit: read(q('fit')), crop: read(q('crop'))};
        q('crop').click();
        return {afterFit: afterFit,
                afterCrop: {fit: read(q('fit')), crop: read(q('crop'))}};
    }""")
    assert got["afterFit"]["fit"]["on"],         f"the framing choice is still drawn nowhere: {got}"
    assert got["afterFit"]["fit"]["pressed"] == "true", got
    assert not got["afterFit"]["crop"]["on"],         f"both framing buttons read as chosen at once: {got}"
    assert got["afterCrop"]["crop"]["on"], got
    assert not got["afterCrop"]["fit"]["on"],         f"the old choice stayed marked: {got}"
    ui.clean("the framing control")


# ----------------------------------------------------- choosing the part

def test_the_recording_plays_whole_in_the_part_stage(ui, app):
    """What this replaced built a small copy of the chosen part, on the
    strength of a comment saying a recording cannot be scrubbed in a browser.
    That is true of fragmented mp4 and false of an ordinary one -- so the file
    is asked rather than assumed, and a faststart recording has to come back
    seekable and actually load."""
    _at_part(ui, app)
    ui.page.wait_for_function("() => clip_state.partWhole === true",
                              timeout=30_000)
    state = ui.page.evaluate("""async () => {
        const v = document.getElementById('clip-part-video');
        await new Promise(res => { if (v.readyState >= 1) return res();
                                   v.onloadedmetadata = res; v.onerror = res;
                                   setTimeout(res, 20000); });
        return {err: v.error && v.error.code, ready: v.readyState,
                dur: v.duration, src: !!v.getAttribute('src')};
    }""")
    assert state["src"], "no recording was ever pointed at the player"
    assert not state["err"], f"the recording would not play: {state}"
    assert state["dur"] > 100, f"the player did not load the whole file: {state}"
    ui.clean("playing the recording whole")


def test_the_part_can_be_marked_from_the_playhead(ui, app):
    """A handle on a long strip is seconds per pixel; watching to the moment
    and pressing a button is exact."""
    _at_part(ui, app)
    ui.page.wait_for_function("() => clip_state.partWhole === true",
                              timeout=30_000)
    ui.page.evaluate("document.getElementById('clip-part-video').currentTime = 40")
    ui.page.wait_for_function(
        "() => Math.abs(document.getElementById('clip-part-video')"
        ".currentTime - 40) < 3", timeout=20_000)
    ui.page.click("#clip-part-markin")
    ui.page.evaluate("document.getElementById('clip-part-video').currentTime = 90")
    ui.page.wait_for_function(
        "() => Math.abs(document.getElementById('clip-part-video')"
        ".currentTime - 90) < 3", timeout=20_000)
    ui.page.click("#clip-part-markout")
    got = ui.page.evaluate("[clip_state.strip.from, clip_state.strip.to]")
    assert got[0] > 30, f"the start was not taken from the playhead: {got}"
    assert got[1] > got[0], f"the part ends before it starts: {got}"
    assert ui.page.inner_text("#clip-part-len").strip(), "no length was shown"
    ui.clean("marking the part")


def test_saving_the_part_writes_a_file(ui, app):
    """The one button on this page with a consequence on disk."""
    _at_part(ui, app)
    ui.page.evaluate("clip_state.strip.from = 20; clip_state.strip.to = 35;"
                     " clip_stripRender()")
    ui.page.click("#clip-part-save")
    ui.page.wait_for_function("() => clip_state.partSaving === false",
                              timeout=300_000)
    made = list((Path(app["home"]) / "video" / "clips" / "trimmed").glob("*.mp4"))
    assert made, "Save this part produced no file"
    assert made[0].stat().st_size > 1000, f"the saved part is empty: {made[0]}"
    ui.clean("saving the part")


# ------------------------------------------------------ the stream list

def test_the_stream_list_pages_rather_than_running_off_the_screen(ui, app):
    """Twelve to a page, and the pager only when there is a second page."""
    _recording(app)
    # IN ONE GO. The status poll reloads the real session list every couple of
    # seconds, so rows put on the page from outside get wiped between
    # statements -- every assertion has to be made before the next tick.
    got = ui.page.evaluate("""() => {
        clip_state.sessions = Array.from({length: 30}, (_, i) => ({
            game: 'VALORANT', started: 1790000000 + i * 3600,
            display_started: 1790000000 + i * 3600,
            duration: 600, has_recording: true,
            recording_path: 'C:/x' + i + '.mp4'}));
        clip_state.game = '';
        clip_state.page = 0;
        clip_goStep('pick');
        clip_renderList();
        const rows = () => document.querySelectorAll('#clip-list .clip-row');
        const pager = document.getElementById('clip-pager');
        const out = {
            first_page: rows().length,
            pager_shown: !pager.classList.contains('hide'),
            prev_off: document.getElementById('clip-page-prev').disabled};
        clip_page(1);
        out.page = clip_state.page;
        out.at = document.getElementById('clip-page-at').textContent;
        /* THE BUG THIS GUARDS: a row keeps its index into the WHOLE list, so
           a row on page two picks the stream it names rather than the one
           twelve earlier. Slicing naively gets this wrong, and silently. */
        out.first_index = rows()[0].getAttribute('data-i');
        return out;
    }""")
    assert got["first_page"] == 12, got
    assert got["pager_shown"], "thirty streams and no pager"
    assert got["prev_off"], "page one offers to go to a newer page"
    assert got["page"] == 1, got
    assert "13-24" in got["at"], got
    assert got["first_index"] == "12", \
        f"a row on page two indexes into the page rather than the list: {got}"
    ui.clean("paging the stream list")


def test_only_stages_behind_you_show_a_tick(ui, app):
    """FROM THE UI REVIEW, defect 3: on step 2 the rail ticked step 3 "Style"
    while 4 and 5 were still numbered, so a stage nobody had opened read as
    finished.

    The done flag answers "has this card got something in it" -- Style's is
    `a video is picked` -- which is not the same question as "is this behind
    me". A tick means behind you."""
    _at_part(ui, app)
    got = ui.page.evaluate("""() => {
        const out = [];
        document.querySelectorAll('#clip-rail .clip-rail-step').forEach(li => {
            const b = li.querySelector('button');
            out.push({name: b.getAttribute('data-val'),
                      tick: li.querySelector('.clip-rail-dot').textContent.trim(),
                      done: li.classList.contains('is-done'),
                      here: li.classList.contains('is-here')});
        });
        return out;
    }""")
    names = [r["name"] for r in got]
    at = next(i for i, r in enumerate(got) if r["here"])
    assert names[at] == "part", got

    for i, row in enumerate(got):
        ticked = row["tick"] == "✓" or row["done"]
        if i < at:
            continue                      # behind: a tick is correct
        assert not ticked, (
            f"{row['name']!r} is at or ahead of the open stage and shows a "
            f"tick: {got}")
