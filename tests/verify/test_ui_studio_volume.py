r"""Tier 7: the volume lines -- the song's and the game's level as yellow lines with keyframes.

Asked for 2026-10-27, with a screenshot of an editor's music track: "give the users the song
controls ... with proper keyframes marking ability and moving them up down means changing their
volume". Decided the same night: the line is ABSOLUTE and replaces the dB sliders, and the game
sound gets one too.

Every promise here is a pointer gesture on a drawn SVG, which the offline suite cannot see:
a drag on the line sets the level, a click adds a keyframe where it is, a keyframe drags in time
and level, a double-click takes it off, Undo takes each one back, and the page's line is the
render's line (studio.vol_at).
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

    home = tmp_path_factory.mktemp("volume")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


SETUP = """() => {
  studio_tab('timeline');
  const shots = [0, 1, 2, 3].map(i => ({
    clip: 'C:/vid/clips/c' + i + '.mp4', clip_id: 'c' + i, name: 'c' + i, clip_seconds: 30,
    kill: 10.0, pre: 1.0, duration: 2.5, kills: [10.0], clip_mtime: 0, speed: 's00', fx: [],
    hero: false, hero_fx: [], camera: 'c00', transition: 't01', tlen: 0, caption: ''}));
  studio.project = {
    version: 1, name: 'volume', style: 'montage', format: 'landscape',
    song: 'C:/vid/song.mp3', song_offset: 0, beat: 0.5, step: 0.5,
    intro: 'i00', outro: 'e12', grade: 'g01', vignette: false, overlays: [],
    handle: '', music_db: 0, game_db: 0, duck: false, saturation: 1, shots: shots,
    lyrics: {look: 'off'}, cam: {source: 'none'}};
  let t = 0;
  const drows = shots.map((s, i) => {
    const r = {index: i, start: t, end: t + s.duration, kill_reel: t + s.pre, kills_reel: [t + s.pre],
               source_in: s.kill - s.pre, source_out: s.kill - s.pre + s.duration, pieces: [[0, s.duration, 1]]};
    t += s.duration;
    return r;
  });
  studio.derived = {length: t, beat: 0.5, bpm: 120, beats: [], kills: drows.map(r => r.kill_reel),
                    selection: [], lead_in: 0, intro_clip: null, shots: drows};
  studio.pps = 100;
  window.studio_check = () => {};
  window.studio_musicNeed = () => {};
  studio_select(-1);
  studio_drawAll();
  return true;
}"""


@pytest.fixture
def pg(browser, app):
    ctx = browser.new_context(viewport={"width": 1600, "height": 1100})
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
    page.evaluate(SETUP)
    page.wait_for_timeout(250)
    page.trouble = trouble
    yield page
    assert not trouble, trouble
    ctx.close()


def _line_point(pg, kind, t):
    """Where the line is drawn at reel second t, on screen."""
    return pg.evaluate("""([kind, t]) => {
      const svg = document.getElementById('studio-vol-' + kind);
      svg.scrollIntoView({block: 'center', inline: 'nearest'});
      const box = svg.getBoundingClientRect();
      const sc = studio_el('studio-scroll');
      sc.scrollLeft = Math.max(0, t * studio.pps - 300);
      const b2 = svg.getBoundingClientRect();
      return {x: b2.left + t * studio.pps, y: b2.top + studio_volY(kind, studio_volAt(studio.project, kind, t))};
    }""", [kind, t])


def _key_point(pg, kind, k):
    return pg.evaluate("""([kind, k]) => {
      const c = document.querySelector('#studio-vol-' + kind + ' circle[data-k="' + k + '"]');
      const r = c.getBoundingClientRect();
      return {x: r.left + r.width / 2, y: r.top + r.height / 2};
    }""", [kind, k])


def _drag(pg, at, dx, dy):
    pg.mouse.move(at["x"], at["y"])
    pg.mouse.down()
    pg.mouse.move(at["x"] + dx, at["y"] + dy, steps=8)
    pg.mouse.up()
    pg.wait_for_timeout(200)


def _p(pg):
    return pg.evaluate("""() => ({music_db: studio.project.music_db, game_db: studio.project.game_db,
      music_keys: studio.project.music_keys || [], game_keys: studio.project.game_keys || []})""")


def test_both_lines_are_drawn_and_the_sliders_are_gone(pg):
    assert pg.locator("#studio-vol-music path.st-vol-hit").count() == 1
    assert pg.locator("#studio-vol-game path.st-vol-hit").count() == 1
    assert pg.locator("#studio-r-music, #studio-r-game").count() == 0
    labels = pg.evaluate("() => [...document.querySelectorAll('#view-studio .studio-labels .st-lab')].map(x => x.textContent)")
    assert "Game audio" in labels and "Music" in labels


def test_dragging_a_flat_line_sets_the_level_and_undo_puts_it_back(pg):
    _drag(pg, _line_point(pg, "game", 4.0), 0, -30)
    got = _p(pg)
    assert got["game_db"] > 1.0 and got["game_keys"] == []           # up is louder; still flat
    _drag(pg, _line_point(pg, "game", 4.0), 0, 60)
    assert _p(pg)["game_db"] < got["game_db"] - 3
    pg.evaluate("studio_undo()")
    assert _p(pg)["game_db"] == pytest.approx(got["game_db"], abs=0.05)
    pg.evaluate("studio_undo()")
    assert _p(pg)["game_db"] == 0


def test_click_adds_a_keyframe_drag_moves_it_double_click_removes_it(pg):
    for t in (2.0, 6.0):
        a = _line_point(pg, "music", t)
        pg.mouse.click(a["x"], a["y"])
        pg.wait_for_timeout(150)
    ks = _p(pg)["music_keys"]
    assert [k[0] for k in ks] == [pytest.approx(2.0, abs=0.05), pytest.approx(6.0, abs=0.05)]
    assert all(k[1] == 0 for k in ks)                                 # added where the line was: nothing heard changes
    assert pg.locator("#studio-vol-music circle.st-vol-key").count() == 2

    # the second keyframe down and later: the line between them now falls
    _drag(pg, _key_point(pg, "music", 1), 40, 40)
    ks = _p(pg)["music_keys"]
    assert ks[1][1] < -4 and ks[1][0] == pytest.approx(6.4, abs=0.08)
    mid = pg.evaluate("() => studio_volAt(studio.project, 'music', 4.2)")
    assert mid == pytest.approx(ks[1][1] / 2, abs=0.2)                 # straight in dB between them
    assert pg.evaluate("() => studio_volAt(studio.project, 'music', 9.5)") == ks[1][1]   # flat past the last

    # a keyframe cannot be dragged past its neighbour
    _drag(pg, _key_point(pg, "music", 1), -900, 0)
    ks = _p(pg)["music_keys"]
    assert ks[1][0] > ks[0][0]

    a = _key_point(pg, "music", 0)
    pg.mouse.dblclick(a["x"], a["y"])
    pg.wait_for_timeout(200)
    assert len(_p(pg)["music_keys"]) == 1
    pg.evaluate("studio_undo()")
    assert len(_p(pg)["music_keys"]) == 2


def test_dragging_the_line_between_two_keyframes_moves_both(pg):
    pg.evaluate("""() => studio_change(pr => { pr.music_keys = [[1, -6], [3, -6], [8, 0]]; }, 'set up')""")
    before = _p(pg)["music_keys"]
    _drag(pg, _line_point(pg, "music", 2.0), 0, 25)
    after = _p(pg)["music_keys"]
    assert after[0][1] < before[0][1] and after[1][1] == pytest.approx(after[0][1], abs=0.05)
    assert after[2] == before[2]                                      # the one outside the stretch stays


def test_the_inspector_adds_at_the_playhead_and_goes_flat_again(pg):
    pg.evaluate("() => { studio_seekTo(5); studio_select(-1); studio_drawInspector(); }")
    pg.wait_for_timeout(150)
    btn = pg.locator('[data-act="studio-vol-add"][data-vol-kind="game"]')
    btn.scroll_into_view_if_needed()
    btn.click()
    ks = _p(pg)["game_keys"]
    assert len(ks) == 1 and ks[0][0] == pytest.approx(5.0, abs=0.05)
    pg.evaluate("() => studio_change(pr => { pr.game_keys = [[1, -20], [9, 0]]; }, 'set up')")
    pg.evaluate("() => { studio_seekTo(5); studio_drawInspector(); }")
    pg.locator('[data-act="studio-vol-flat"][data-vol-kind="game"]').click()
    got = _p(pg)
    assert got["game_keys"] == [] and got["game_db"] == pytest.approx(-10.0, abs=0.1)


def test_the_preview_plays_the_line(pg):
    pg.evaluate("""() => studio_change(pr => { pr.game_keys = [[0, 0], [4, -20]]; }, 'set up')""")
    got = pg.evaluate("""() => { studio.pv.playing = false; studio.pv.t = 4; studio_pvLevels(1);
        const el = studio_pvEls()[studio.pv.act]; return el ? el.volume : null; }""")
    if got is not None:
        assert got == pytest.approx(0.1, abs=0.01)                    # -20 dB
