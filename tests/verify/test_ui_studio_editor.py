r"""Tier 7: the shot's footage as a bar, the inspector in blocks, and shots locked together.

Asked for 2026-10-17, with a screenshot of the inspector:

  * "for each shot give a small preview window where the clip is shown, and there are
    markers which part is in the reel; by adjusting the markers or dragging the used
    section over the clip's length the user can select which part they want"
  * "there are no clear distinctions to separate different sections like songs and
    sound, lyrics, opening and ending"
  * "select multiple shots in the timeline and then lock them ... if I lock all clips
    from 12th to the last one and then move the ending of 11th shot then all of the
    clips locked will move without any getting shorter; this will increase the reel
    duration"

All of it is pointer gestures and layout on a drawn page, which the offline suite
cannot see.
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

    home = tmp_path_factory.mktemp("editor")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


SETUP = """() => {
  studio_tab('timeline');
  const rows = [
    {clip_seconds: 30, kill: 10.0, pre: 2.00, duration: 3.00, kills: [10.0, 16.0]},
    {clip_seconds: 40, kill: 20.0, pre: 1.00, duration: 2.00, kills: [20.0]},
    {clip_seconds: 40, kill: 20.0, pre: 1.00, duration: 2.00, kills: [20.0]},
    {clip_seconds: 30, kill: 8.00, pre: 1.00, duration: 2.00, kills: [8.0]},
  ];
  const shots = rows.map((r, i) => Object.assign({
    clip: 'C:/vid/clips/c' + i + '.mp4', clip_id: 'c' + i, name: 'c' + i,
    clip_mtime: 0, speed: 's00', fx: [], hero: false,
    hero_fx: [], camera: 'c00', transition: 't01', tlen: 0, caption: ''}, r));
  studio.project = {
    version: 1, name: 'editor', style: 'montage', format: 'landscape',
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
  studio_select(0);
  return true;
}"""

STATE = """() => {
  let t = 0;
  return studio.project.shots.map(s => {
    const row = {start: t, duration: s.duration, pre: s.pre, kill: s.kill, kill_at: t + s.pre, lock: s.lock || ''};
    t += s.duration;
    return row;
  });
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
    page.trouble = trouble
    yield page
    assert not trouble, trouble
    ctx.close()


def _drag(pg, sel, by_px, alt=False):
    loc = pg.locator(sel).first
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    assert box, f"{sel} is not on screen"
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y)
    if alt:
        pg.keyboard.down("Alt")
    pg.mouse.down()
    pg.mouse.move(x + by_px, y, steps=8)
    pg.mouse.up()
    if alt:
        pg.keyboard.up("Alt")
    pg.wait_for_timeout(250)


def _px_per_clip_second(pg):
    w = pg.locator("#studio-strip-track").bounding_box()["width"]
    return w / pg.evaluate("studio.project.shots[studio.sel].clip_seconds")


# ------------------------------------------------------------------ blocks

def test_a_shot_and_the_reel_each_read_as_labelled_blocks(pg):
    names = pg.evaluate("[...document.querySelectorAll('#studio-insp .ed-block')].map(b => b.dataset.blk)")
    assert names == ["footage", "cut", "kill", "camera"], names
    assert pg.locator("#studio-insp .ed-blocknav-b").count() == 4
    for g in ("timing", "trans", "fx", "hero", "camera"):
        assert pg.locator(f'#studio-insp .ed-group[data-grp="{g}"]').count() == 1, g
    pg.click('#studio-insp [data-act="studio-select"][data-shot="-1"]')
    pg.wait_for_timeout(200)
    names = pg.evaluate("[...document.querySelectorAll('#studio-insp .ed-block')].map(b => b.dataset.blk)")
    assert names == ["music", "words", "look", "start", "you"], names
    # where sound, lyrics, the opening and the facecam each went
    for blk, grp in (("music", "sound"), ("words", "lyrics"), ("look", "look"), ("look", "pools"),
                     ("start", "ending"), ("you", "handle"), ("you", "cam")):
        assert pg.locator(f'#studio-blk-{blk} .ed-group[data-grp="{grp}"]').count() == 1, (blk, grp)
    assert "no song" in pg.inner_text("#studio-blk-music .ed-block-sum")
    pg.click('#studio-insp [data-act="studio-insp-jump"][data-blk="start"]')


# ------------------------------------------------------------------ the footage bar

def test_the_bar_shows_the_part_in_the_reel_and_each_kill(pg):
    assert pg.locator("#studio-strip-track .studio-strip-kill").count() == 2
    assert pg.locator("#studio-strip-track .studio-strip-kill.is-main").count() == 1
    box = pg.locator("#studio-strip-box").bounding_box()
    pps = _px_per_clip_second(pg)
    assert box["width"] == pytest.approx(3.0 * pps, abs=3)          # 3 s of a 30 s clip
    assert pg.locator("video.studio-strip-video").count() == 1


def test_dragging_the_tail_marker_is_more_after_the_kill(pg):
    before = pg.evaluate(STATE)
    pps = _px_per_clip_second(pg)
    _drag(pg, "#studio-strip .studio-strip-h.is-tail", 0.5 * pps)
    after = pg.evaluate(STATE)
    assert after[0]["duration"] == pytest.approx(before[0]["duration"] + 0.5, abs=0.05)
    assert after[1]["pre"] == pytest.approx(before[1]["pre"] - 0.5, abs=0.05), "the next shot gives the time"
    for a, b in zip(before, after):
        assert b["kill_at"] == pytest.approx(a["kill_at"], abs=1e-3), "a kill left its beat"


def test_dragging_the_head_marker_is_less_before_the_kill(pg):
    pg.evaluate("studio_select(1)")
    pg.wait_for_timeout(200)
    before = pg.evaluate(STATE)
    pps = _px_per_clip_second(pg)
    _drag(pg, "#studio-strip .studio-strip-h.is-head", 0.4 * pps)
    after = pg.evaluate(STATE)
    assert after[1]["pre"] == pytest.approx(before[1]["pre"] - 0.4, abs=0.05)
    assert after[0]["duration"] == pytest.approx(before[0]["duration"] + 0.4, abs=0.05)
    assert [r["kill_at"] for r in after] == pytest.approx([r["kill_at"] for r in before], abs=1e-3)


def test_dragging_the_box_uses_another_part_of_the_clip(pg):
    before = pg.evaluate(STATE)
    pps = _px_per_clip_second(pg)
    _drag(pg, "#studio-strip-box", 2.0 * pps, alt=True)              # Alt: no pull onto a kill
    after = pg.evaluate(STATE)
    assert after[0]["kill"] == pytest.approx(before[0]["kill"] + 2.0, abs=0.1)
    assert after[0]["duration"] == pytest.approx(before[0]["duration"], abs=1e-6)
    assert after[0]["pre"] == pytest.approx(before[0]["pre"], abs=1e-6)
    assert [r["start"] for r in after] == pytest.approx([r["start"] for r in before], abs=1e-6)


def test_the_box_is_pulled_onto_a_kill_near_the_beat(pg):
    pps = _px_per_clip_second(pg)
    _drag(pg, "#studio-strip-box", 5.9 * pps)                         # aims at 15.9; a kill at 16.0
    assert pg.evaluate("studio.project.shots[0].kill") == pytest.approx(16.0, abs=1e-3)
    assert pg.locator("#studio-strip-track .studio-strip-kill.is-main").count() == 1


def test_the_box_stops_at_the_end_of_the_clip_and_says_so(pg):
    pps = _px_per_clip_second(pg)
    _drag(pg, "#studio-strip-box", 40 * pps, alt=True)
    s = pg.evaluate("studio.project.shots[0]")
    assert s["kill"] + (s["duration"] - s["pre"]) == pytest.approx(30.0, abs=0.02)
    pg.wait_for_selector("text=the clip ends there", timeout=3000)


# ------------------------------------------------------------------ locked shots

def _pick(pg, i, mod=None):
    loc = pg.locator(f'.st-shot[data-shot="{i}"]')
    box = loc.bounding_box()
    if mod:
        pg.keyboard.down(mod)
    pg.mouse.click(box["x"] + box["width"] * 0.3, box["y"] + 8)
    if mod:
        pg.keyboard.up(mod)
    pg.wait_for_timeout(150)


def test_locked_shots_slide_together_and_the_reel_grows(pg):
    """The request itself: lock 2 to the last, lengthen shot 1's ending."""
    _pick(pg, 1)
    _pick(pg, 3, "Shift")
    assert pg.locator(".st-shot.is-multi").count() == 3
    assert pg.inner_text("#studio-lock-btn") == "Lock shots 2–4"
    pg.click("#studio-lock-btn")
    pg.wait_for_timeout(200)
    before = pg.evaluate(STATE)
    assert [r["lock"] != "" for r in before] == [False, True, True, True]
    assert pg.locator(".st-lockband").count() == 1
    _drag(pg, '.st-trim[data-trim="0"]', 50)                           # 0.5 s later
    after = pg.evaluate(STATE)
    assert after[0]["duration"] == pytest.approx(before[0]["duration"] + 0.5, abs=0.02)
    for a, b in zip(before[1:], after[1:]):
        assert b["duration"] == pytest.approx(a["duration"], abs=1e-6), "a locked shot changed length"
        assert b["pre"] == pytest.approx(a["pre"], abs=1e-6)
        assert b["kill_at"] == pytest.approx(a["kill_at"] + 0.5, abs=0.02), "the run did not slide"
    assert pg.evaluate("studio.derived.length") == pytest.approx(9.5, abs=0.02)


def test_a_run_in_the_middle_slides_and_the_shot_after_it_gives_the_time(pg):
    _pick(pg, 1)
    _pick(pg, 2, "Control")
    pg.click("#studio-lock-btn")
    before = pg.evaluate(STATE)
    _drag(pg, '.st-trim[data-trim="0"]', 40)
    after = pg.evaluate(STATE)
    assert [b["duration"] for b in after[1:3]] == pytest.approx([a["duration"] for a in before[1:3]], abs=1e-6)
    assert after[3]["pre"] == pytest.approx(before[3]["pre"] - 0.4, abs=0.02)
    assert after[3]["kill_at"] == pytest.approx(before[3]["kill_at"], abs=1e-3), "the rest of the reel moved"
    assert pg.evaluate("studio.derived.length") == pytest.approx(9.0, abs=0.02)


def test_a_cut_inside_a_locked_run_does_not_move(pg):
    _pick(pg, 1)
    _pick(pg, 2, "Shift")
    pg.click("#studio-lock-btn")
    before = pg.evaluate(STATE)
    _drag(pg, '.st-trim[data-trim="1"]', 40)
    after = pg.evaluate(STATE)
    assert [r["duration"] for r in after] == pytest.approx([r["duration"] for r in before], abs=1e-6)
    pg.wait_for_selector("text=locked together", timeout=3000)


def test_unlock_lets_them_move_on_their_own_again(pg):
    _pick(pg, 1)
    _pick(pg, 3, "Shift")
    pg.click("#studio-lock-btn")
    _pick(pg, 2)
    assert pg.inner_text("#studio-lock-btn") == "Unlock"
    pg.click("#studio-lock-btn")
    assert pg.evaluate("studio.project.shots.every(s => !s.lock)")
    assert pg.locator(".st-lockband").count() == 0
    # locking is not a change to the video
    assert pg.evaluate("studio.pending.filter(x => /lock/i.test(x.label)).length") == 0
