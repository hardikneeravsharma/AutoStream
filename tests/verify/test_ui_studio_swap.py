r"""Tier 7: Replace... swaps a weak shot with a strong one in the reel, or takes any game's clip.

ASKED FOR 2026-10-27. A weak clip had one way out without a replan: Replace, offering only the
reel's own game's clips that land on the beat, never a clip already in the reel. Now the panel
offers three places a better clip can come from -- a shot of this reel to trade with (clips swap,
slots stay), every game's clips that land on this beat, and, folded away, the ones that cannot,
each with why. The server works the options out (clips/slots.py, tested offline in
tests/test_slots.py); here its answers are stubbed, and what is checked is what only a browser
can see: the three sections are there, the find box filters without losing the caret, a refused
swap cannot be pressed, Swap changes both shots on the timeline in one step, and Undo puts both back.
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

    home = tmp_path_factory.mktemp("swap")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


# Four shots, and the server's answers as it would give them. The exchange answer is the page's
# own project with two clips traded and every timing left alone -- that is the whole contract.
SETUP = """() => {
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
    version: 1, name: 'swap', style: 'montage', format: 'landscape',
    song: '', song_offset: 0, beat: 0.4, step: 0.4,
    intro: 'i00', outro: 'e12', grade: 'g01', vignette: false, overlays: [],
    handle: '', music_db: 0, game_db: 0, duck: false, saturation: 1, shots: shots,
    lyrics: {look: 'off'}, cam: {source: 'none'}};
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
  window.studio_check = () => {};
  window.__slot = [];
  const post = API.post;
  API.post = function (u, b) {
    if (u !== '/api/studio/slot') return post.apply(this, arguments);
    window.__slot.push(b);
    if (b.do === 'options') {
      const clips = [];
      for (let k = 0; k < 6; k++) clips.push({clip: 'C:/vid/clips/v' + k + '.mp4', name: 'val' + k, game: 'VALORANT', own: true, kill: 3.5, hs: true, score: 2.5});
      clips.push({clip: 'C:/vid/clips/cs.mp4', name: 'awp-flick', game: 'Counter-Strike 2', own: false, kill: 4.0, hs: true, score: 2.5});
      return Promise.resolve({ok: true, take: false, why: '', clips: clips,
        others: [{clip: 'C:/vid/clips/short.mp4', name: 'short', game: 'VALORANT', own: true,
                  why: 'needs 1.9 s before its kill, has 0.1 s'}],
        swaps: [{shot: 2, name: 'c2', ok: true, why: '', kill_here: 20.0, kill_there: 10.0},
                {shot: 3, name: 'c3', ok: false, why: 'c3 cannot fill shot 1: it needs 1.9 s before its kill, has 7.98 s.'}],
        swap_why: ''});
    }
    if (b.do === 'exchange') {
      const q = JSON.parse(JSON.stringify(b.project)), i = b.shot, j = b.with;
      const keys = ['clip', 'clip_id', 'name', 'clip_seconds', 'kill', 'kills'];
      keys.forEach(k => { const x = q.shots[i][k]; q.shots[i][k] = q.shots[j][k]; q.shots[j][k] = x; });
      return Promise.resolve({ok: true, project: q, moved: 0});
    }
    return Promise.resolve({ok: false, error: 'Not in this test.'});
  };
  studio_select(0);
  return true;
}"""


@pytest.fixture
def pg(browser, app):
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
    page.evaluate(SETUP)
    page.wait_for_timeout(250)
    yield page
    assert not trouble, trouble
    ctx.close()


def _clips(pg):
    return pg.evaluate("studio.project.shots.map(s => s.name)")


def _open(pg):
    pg.evaluate("studio_select(0)")
    pg.click('#studio-insp [data-act="studio-replace"]')
    pg.wait_for_selector('#studio-slot [data-do="swap"]')


def test_replace_offers_the_reels_shots_every_games_clips_and_the_misfits(pg):
    _open(pg)
    text = pg.inner_text("#studio-slot")
    assert "Swap with a shot in this reel" in text
    assert "Clips that land a kill on this beat" in text
    assert "counter-strike 2" in text.lower()                        # another game's clip, labelled
    # the refused swap is listed, says why, and cannot be pressed
    assert pg.is_disabled('#studio-slot [data-do="swap"][data-with="3"]')
    assert "before its kill" in text
    # the misfits are folded away until asked for
    assert not pg.is_visible('#studio-slot-others li')
    pg.click('#studio-slot-others summary')
    assert pg.is_visible('#studio-slot-others li') and "needs 1.9 s" in pg.inner_text('#studio-slot-others')


def test_the_find_box_filters_in_place_and_keeps_the_caret(pg):
    _open(pg)
    pg.click('#studio-slot-q')
    pg.keyboard.type("counter")
    assert pg.evaluate("document.activeElement && document.activeElement.id") == "studio-slot-q"
    shown = pg.evaluate("[...document.querySelectorAll('#studio-slot-clips li')].filter(li => !li.hidden).map(li => li.textContent)")
    assert len(shown) == 1 and "awp-flick" in shown[0]
    # the swaps are not a search result: they stay
    assert pg.is_visible('#studio-slot [data-do="swap"][data-with="2"]')


def test_swap_trades_both_clips_in_one_step_and_undo_puts_both_back(pg):
    _open(pg)
    before = _clips(pg)
    timings = pg.evaluate("studio.project.shots.map(s => [s.pre, s.duration])")
    pg.click('#studio-slot [data-do="swap"][data-with="2"]')
    pg.wait_for_function("studio.project.shots[0].name === 'c2'", timeout=5_000)
    assert _clips(pg) == ["c2", "c1", "c0", "c3"]
    assert pg.evaluate("studio.project.shots.map(s => [s.pre, s.duration])") == timings   # slots stayed
    assert not pg.query_selector("#studio-slot")                     # the panel closes on use
    # the timeline shows it, not just the model
    assert pg.get_attribute('.st-shot[data-shot="0"]', "title") == "c2"
    assert pg.get_attribute('.st-shot[data-shot="2"]', "title") == "c0"
    sent = pg.evaluate("window.__slot.filter(b => b.do === 'exchange')")
    assert len(sent) == 1 and sent[0]["shot"] == 0 and sent[0]["with"] == 2
    pg.evaluate("studio_undo()")
    pg.wait_for_function("studio.project.shots[0].name === 'c0'", timeout=5_000)
    assert _clips(pg) == before
    assert pg.get_attribute('.st-shot[data-shot="0"]', "title") == "c0"
