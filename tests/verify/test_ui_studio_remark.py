r"""Tier 7: a shot taken out or moved closes up on the song's hits.

WHAT WAS WRONG. "4Raws X valorant: when I removed the first clip the
remaining reel should have adjusted according to the beat; instead all of it
got displaced." Removing a shot only spliced the list, so every shot after it
slid earlier by the removed shot's length -- 1.90 s there -- while the song
stayed put: 2 of 40 kills were left on a hit. Moving a shot did the same
whenever the two shots differed in length.

Chosen 2026-10-19 between two rendered versions: each shot after the change
moves up one hit and the last hit goes unused. The server lays the marks back
on (`studio.normalise`, tested offline); what only a browser can show is that
every gesture that removes or reorders a shot asks for it -- and that nothing
else does, since re-timing on every edit would undo every cut moved by hand.
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

    home = tmp_path_factory.mktemp("remark")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


# Four shots of different lengths, each kill on one of the song's marks. What
# the page sends to the server is recorded instead of sent: the stub clips are
# not videos, and the question here is what the page asks for.
SETUP = """(marked) => {
  studio_tab('timeline');
  const rows = [
    {clip_seconds: 30, kill: 10.0, pre: 1.90, duration: 2.40, kills: [10.0]},
    {clip_seconds: 40, kill: 20.0, pre: 0.60, duration: 1.20, kills: [20.0]},
    {clip_seconds: 40, kill: 20.0, pre: 0.70, duration: 1.00, kills: [20.0]},
    {clip_seconds: 30, kill: 8.00, pre: 0.60, duration: 1.40, kills: [8.0]},
  ];
  const shots = rows.map((r, i) => Object.assign({
    clip: 'C:/vid/clips/c' + i + '.mp4', clip_id: 'c' + i, name: 'c' + i,
    clip_mtime: 0, speed: 's00', fx: [], hero: false,
    hero_fx: [], camera: 'c00', transition: 't01', tlen: 0, caption: ''}, r));
  studio.project = {
    version: 1, name: 'remark', style: 'montage', format: 'landscape',
    song: '', song_offset: 0, beat: 0.4, step: 0.4,
    intro: 'i00', outro: 'e12', grade: 'g01', vignette: false, overlays: [],
    handle: '', music_db: 0, game_db: 0, duck: false, saturation: 1, shots: shots,
    lyrics: {look: 'off'}, cam: {source: 'none'}};
  if (marked) studio.project.song_marks = [1.9, 3.0, 4.1, 5.1];
  let t = 0;
  const drows = shots.map((s, i) => {
    const r = {index: i, start: t, end: t + s.duration, kill_reel: t + s.pre,
               kills_reel: [t + s.pre], source_in: s.kill - s.pre,
               source_out: s.kill - s.pre + s.duration, pieces: [[0, s.duration, 1]]};
    t += s.duration;
    return r;
  });
  studio.derived = {length: t, beat: 0.4, bpm: 150, beats: [], kills: drows.map(r => r.kill_reel),
                    selection: [], lead_in: 0, intro_clip: null, shots: drows};
  studio_el('studio-snap').checked = false;
  studio.pps = 100;
  window.__sent = [];
  window.studio_check = () => { window.__sent.push(!!studio.project.remark); };
  studio_select(0);
  return true;
}"""


def _page(browser, app, marked):
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("console",
            lambda m: trouble.append(m.text)
            if m.type == "error" and "studio/thumb" not in m.text and "clips/video" not in m.text
            and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.wait_for_timeout(900)
    page.evaluate(SETUP, marked)
    page.wait_for_timeout(250)
    page.trouble = trouble
    page.ctx = ctx
    return page


@pytest.fixture
def pg(browser, app):
    page = _page(browser, app, True)
    yield page
    assert not page.trouble, page.trouble
    page.ctx.close()


@pytest.fixture
def unmarked(browser, app):
    page = _page(browser, app, False)
    yield page
    assert not page.trouble, page.trouble
    page.ctx.close()


def _sent(pg):
    """What the page asked of the server, once its debounced check has gone."""
    pg.wait_for_function("window.__sent.length > 0", timeout=5_000)
    return pg.evaluate("window.__sent")


def _clips(pg):
    return pg.evaluate("studio.project.shots.map(s => s.name)")


def _remove_button(pg, i):
    pg.evaluate("(i) => studio_select(i)", i)
    pg.click('#studio-insp [data-act="studio-remove"]')


def _drag_shot(pg, i, by_px):
    loc = pg.locator(f'.st-shot[data-shot="{i}"]').first
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    assert box, f"shot {i} is not on screen"
    # Low on the shot, clear of the kill diamond and the trim handles at its edges.
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] - 6
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.mouse.move(x + by_px, y, steps=10)
    pg.mouse.up()


def test_the_remove_button_asks_for_the_hits(pg):
    _remove_button(pg, 0)
    assert _clips(pg) == ["c1", "c2", "c3"]
    assert _sent(pg)[-1] is True, "the shot went but nothing asked for the reel to close up on the hits"


def test_the_delete_key_asks_for_the_hits(pg):
    pg.evaluate("studio_select(1)")
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("Delete")
    assert _clips(pg) == ["c0", "c2", "c3"]
    assert _sent(pg)[-1] is True


def test_moving_a_shot_asks_for_the_hits(pg):
    pg.evaluate("studio_select(0)")
    pg.click('#studio-insp [data-act="studio-move"][data-d="1"]')
    assert _clips(pg) == ["c1", "c0", "c2", "c3"]
    assert _sent(pg)[-1] is True


def test_dragging_a_shot_to_another_place_asks_for_the_hits(pg):
    _drag_shot(pg, 0, 330)
    assert _clips(pg)[0] != "c0", "the drag did not move the shot"
    assert _sent(pg)[-1] is True


def test_the_request_is_said_once_not_kept(pg):
    """It must not count as a change of its own, or the page would call the
    reel edited for a flag the server's answer drops."""
    _remove_button(pg, 0)
    _sent(pg)
    assert pg.evaluate("studio_isEdit(['remark'])") is False


def test_a_reel_with_no_hits_is_left_alone(unmarked):
    _remove_button(unmarked, 0)
    assert _clips(unmarked) == ["c1", "c2", "c3"]
    assert _sent(unmarked)[-1] is False, "a reel with no marks was asked to close up on them"
