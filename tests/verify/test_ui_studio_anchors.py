r"""Tier 7: every kill is a diamond, and dragging one does not move the cut.

WHAT WAS WRONG, MEASURED ON A REAL HAND-EDITED REEL. The editor wanted a 1v3's
last kill on the song's bass drop. The only draggable thing was the shot's own
kill, and dragging it changes the shot's run-up, which changes the shot's
length, which pushes every later shot down the timeline. So: the kills they
dragged landed within a frame of the beat and the ones after them were up to
ten frames out, and the clutch kill never reached the drop at all -- it sat at
17.7 s against a drop at 25.0.

Now every kill of a shot is its own diamond. Dragging one pins it where it was
dropped and the renderer bends the rate INSIDE the shot to hit it
(studio.fit_pieces); the shot's start and end do not move, so nothing
downstream knows anything happened.

None of this is visible to the offline suite: the diamonds are elements drawn
into a timeline, and a drag is a pointer gesture. It is a browser or it is
nothing.
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

    home = tmp_path_factory.mktemp("anchors")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


SETUP = """() => {
  /* THE TIMELINE PANE, OPENED. The diamonds exist in the DOM whatever pane is
     showing, so a test that only queries them passes on a hidden timeline --
     and a drag cannot happen on one, which is the half that matters. */
  studio_tab('timeline');
  /* One shot, three kills, cut around the first. Built here rather than
     planned, so the geometry is the same on every run. */
  studio.project = {
    version: 1, name: 'anchors', style: 'montage', format: 'landscape',
    song: '', song_offset: 0, beat: 0.5, step: 0.5,
    intro: 'i00', outro: 'e12', grade: 'g01', vignette: false, overlays: [],
    handle: '', music_db: 0, game_db: 0, duck: false, saturation: 1,
    shots: [{
      clip: 'C:/vid/clips/a.mp4', clip_id: 'c1', name: 'a', clip_seconds: 30,
      clip_mtime: 0, kills: [10.0, 11.5, 13.0], kill: 10.0,
      duration: 4.0, pre: 1.0, speed: 's00', fx: [], hero: false,
      hero_fx: [], camera: 'c00', transition: 't01', tlen: 0, caption: ''
    }]
  };
  studio.derived = {
    length: 4.0, beat: 0.5, bpm: 120, beats: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4],
    kills: [1.0, 2.5, 4.0], selection: [], lead_in: 0, intro_clip: null,
    shots: [{index: 0, start: 0, end: 4.0, kill_reel: 1.0,
             kills_reel: [1.0, 2.5, 3.5], source_in: 9.0, source_out: 13.0,
             pieces: [[0, 4.0, 1]]}]
  };
  studio.sel = 0;
  studio.pps = 120;
  studio_drawTimeline();
  return true;
}"""


@pytest.fixture
def pg(browser, app):
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("console",
            lambda m: trouble.append(m.text)
            if m.type == "error" and "studio/thumb" not in m.text
            and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.wait_for_timeout(900)
    page.evaluate(SETUP)
    page.wait_for_timeout(200)
    page.trouble = trouble
    page.ctx = ctx
    yield page
    assert not trouble, trouble
    ctx.close()


def _drag(pg, sel, by_px):
    box = pg.locator(sel).first.bounding_box()
    assert box, f"{sel} is not on screen"
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.mouse.move(x + by_px, y, steps=6)
    pg.mouse.up()
    pg.wait_for_timeout(250)


# ---- the diamonds ---------------------------------------------------------


def test_every_kill_in_the_shot_gets_a_diamond(pg):
    got = pg.evaluate(
        """() => ({own: document.querySelectorAll('.st-kill[data-kill]').length,
                   extra: document.querySelectorAll('.st-kill[data-anchor]').length})""")
    assert got["own"] == 1, got
    assert got["extra"] == 2, "the shot's other two kills are not drawn"


def test_the_shots_own_kill_still_reads_as_the_one_in_charge(pg):
    """A row of equal diamonds says nothing about which the cut is built
    around."""
    got = pg.evaluate(
        """() => {
             const own = document.querySelector('.st-kill[data-kill]');
             const extra = document.querySelector('.st-kill[data-anchor]');
             const a = getComputedStyle(own), b = getComputedStyle(extra);
             return {ownW: parseFloat(a.width), extraW: parseFloat(b.width),
                     extraBg: b.backgroundColor};
           }""")
    assert got["extraW"] < got["ownW"]
    assert "0, 0, 0, 0" in got["extraBg"] or got["extraBg"] == "transparent"


# ---- dragging one ---------------------------------------------------------


def test_dragging_a_kill_pins_it_and_leaves_the_cut_alone(pg):
    before = pg.evaluate(
        """() => { const s = studio.project.shots[0];
                   return {pre: s.pre, duration: s.duration}; }""")
    _drag(pg, '.st-kill[data-anchor="0:1"]', 60)
    after = pg.evaluate(
        """() => { const s = studio.project.shots[0];
                   return {pre: s.pre, duration: s.duration,
                           anchors: s.anchors || []}; }""")
    assert after["pre"] == before["pre"], "the cut moved"
    assert after["duration"] == before["duration"], "the shot changed length"
    assert len(after["anchors"]) == 1, after
    src, out = after["anchors"][0]
    assert src == pytest.approx(11.5, abs=1e-3), "pinned the wrong kill"
    assert out > 1.5, "the kill did not move"


def test_a_pinned_kill_looks_pinned(pg):
    _drag(pg, '.st-kill[data-anchor="0:1"]', 60)
    assert pg.locator('.st-kill[data-anchor="0:1"].is-pinned').count() == 1


def test_alt_click_lets_it_float_again(pg):
    """Unpinning has to be as cheap as pinning, or a mistake costs a
    rebuild."""
    _drag(pg, '.st-kill[data-anchor="0:1"]', 60)
    assert pg.evaluate("() => (studio.project.shots[0].anchors || []).length") == 1
    box = pg.locator('.st-kill[data-anchor="0:1"]').first.bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pg.keyboard.down("Alt")
    pg.mouse.down()
    pg.mouse.up()
    pg.keyboard.up("Alt")
    pg.wait_for_timeout(250)
    assert pg.evaluate("() => (studio.project.shots[0].anchors || []).length") == 0


def test_pinning_a_second_kill_keeps_the_first(pg):
    _drag(pg, '.st-kill[data-anchor="0:1"]', 40)
    _drag(pg, '.st-kill[data-anchor="0:2"]', -30)
    anchors = pg.evaluate("() => studio.project.shots[0].anchors || []")
    assert len(anchors) == 2, anchors
    assert sorted(round(a[0], 2) for a in anchors) == [11.5, 13.0]


def test_dragging_the_same_kill_twice_moves_it_rather_than_pinning_it_twice(pg):
    _drag(pg, '.st-kill[data-anchor="0:1"]', 40)
    _drag(pg, '.st-kill[data-anchor="0:1"]', 40)
    anchors = pg.evaluate("() => studio.project.shots[0].anchors || []")
    assert len(anchors) == 1, anchors


def test_the_shots_own_kill_still_moves_the_cut(pg):
    """The old handle keeps its old meaning: that is how you choose where the
    shot sits around its kill, and nothing here replaces it."""
    _drag(pg, '.st-kill[data-kill="0"]', 60)
    got = pg.evaluate(
        """() => { const s = studio.project.shots[0];
                   return {pre: s.pre, anchors: (s.anchors || []).length}; }""")
    assert got["pre"] > 1.0, "the cut did not move"
    assert got["anchors"] == 0, "moving the cut should pin nothing"
