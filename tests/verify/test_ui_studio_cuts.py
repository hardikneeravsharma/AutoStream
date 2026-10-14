r"""Tier 7: moving a cut moves that cut, and nothing else.

ASKED FOR WITH A SCREEN RECORDING. "The second shot cuts just before the kill
and we were showing the lead-up more than the actual kill, so I wanted to
shorten the lead-up and increase the time after -- but it shifted the whole
timeline." Read off the recording frame by frame, every tool within reach moved
the wrong thing:

  * Run-up -/+ and the kill diamond moved the KILL inside a shot that stayed
    put, so the kill left its beat (2.00 s -> 1.20 -> 0.80 in the recording,
    then dragged back by hand to 2.03, 1.23, 1.97 hunting for it).
  * Length -/+ and the edge drag changed the shot's length, so every shot
    after it moved.
  * Roll, the one tool meant for this, moved the next shot's start without
    trimming its head -- so that shot's kill slid off its beat instead.

Now an edge is a cut, and moving it lengthens one shot and shortens the other
from the side the cut is on, so both kills play at exactly the moment they did.
The geometry below is shot 2 of that reel: a 2.22 s shot whose kill comes 2.00 s
in, leaving 0.22 s after it.

None of this is visible offline. It is pointer gestures on a drawn timeline.
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

    home = tmp_path_factory.mktemp("cuts")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


SETUP = """(song) => {
  studio_tab('timeline');
  /* Four shots at real speed, every clip with footage to spare either side
     unless a test takes it away. Shot index 1 is the one from the recording. */
  const rows = [
    {clip_seconds: 30, kill: 10.0, pre: 2.80, duration: 4.60},
    {clip_seconds: 40, kill: 3.50, pre: 2.00, duration: 2.22},
    {clip_seconds: 40, kill: 20.0, pre: 0.64, duration: 1.20},
    {clip_seconds: 30, kill: 8.00, pre: 0.80, duration: 2.00},
  ];
  const shots = rows.map((r, i) => Object.assign({
    clip: 'C:/vid/clips/c' + i + '.mp4', clip_id: 'c' + i, name: 'c' + i,
    clip_mtime: 0, kills: [r.kill], speed: 's00', fx: [], hero: false,
    hero_fx: [], camera: 'c00', transition: 't01', tlen: 0, caption: ''}, r));
  studio.project = {
    version: 1, name: 'cuts', style: 'montage', format: 'landscape',
    song: song ? 'C:/vid/song.m4a' : '', song_offset: song ? 5.0 : 0, beat: 0.4, step: 0.4,
    intro: 'i00', outro: 'e12', grade: 'g01', vignette: false, overlays: [],
    handle: '', music_db: 0, game_db: 0, duck: false, saturation: 1, shots: shots};
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
  /* Every cut off the grid, so the hand decides where it goes. */
  studio_el('studio-snap').checked = false;
  studio.sel = 1;
  /* 100 px a second keeps every handle these tests use clear of the
     inspector on the right, which a wider timeline slides under. */
  studio.pps = 100;
  studio_drawTimeline();
  /* No server in the loop: these are about the gesture, and the answer to a
     check about a project with no real clips would replace the one under test. */
  window.studio_check = () => {};
  return true;
}"""

STATE = """() => {
  let t = 0;
  return studio.project.shots.map(s => {
    const row = {start: t, duration: s.duration, pre: s.pre, kill_at: t + s.pre};
    t += s.duration;
    return row;
  }).concat([{song_offset: studio.project.song_offset}]);
}"""


@pytest.fixture
def pg(browser, app):
    ctx = browser.new_context(viewport={"width": 1600, "height": 950})
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
    page.evaluate(SETUP, False)
    page.wait_for_timeout(200)
    page.trouble = trouble
    yield page
    assert not trouble, trouble
    ctx.close()


def _drag(pg, sel, by_px, shift=False):
    box = pg.locator(sel).first.bounding_box()
    assert box, f"{sel} is not on screen"
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y)
    if shift:
        pg.keyboard.down("Shift")
    pg.mouse.down()
    pg.mouse.move(x + by_px, y, steps=8)
    pg.mouse.up()
    if shift:
        pg.keyboard.up("Shift")
    pg.wait_for_timeout(250)


def _state(pg):
    rows = pg.evaluate(STATE)
    return rows[:-1], rows[-1]["song_offset"]


def _kills_where_they_were(before, after, skip=()):
    for i, (a, b) in enumerate(zip(before, after)):
        if i in skip:
            continue
        assert b["kill_at"] == pytest.approx(a["kill_at"], abs=1e-3), (i, a, b)


# ---- the recording's own request ------------------------------------------


def test_less_before_the_kill_moves_only_the_cut_before_it(pg):
    """Drag shot 2's LEFT edge to the right: less lead-up. Shot 1 takes the
    time, both kills stay where they play, and shots 3 and 4 do not move."""
    before, _ = _state(pg)
    _drag(pg, '.st-trim-l[data-trim-l="1"]', 80)           # 0.8 s at 100 px/s
    after, _ = _state(pg)
    assert after[1]["pre"] < before[1]["pre"] - 0.5, "the lead-up did not get shorter"
    assert after[0]["duration"] == pytest.approx(
        before[0]["duration"] + (before[1]["pre"] - after[1]["pre"]), abs=1e-3)
    _kills_where_they_were(before, after)
    assert [r["start"] for r in after[2:]] == pytest.approx([r["start"] for r in before[2:]], abs=1e-3)


def test_more_after_the_kill_moves_only_the_cut_after_it(pg):
    """Drag shot 2's RIGHT edge to the right: more after the kill. Shot 3
    gives up the time from its head, so ITS kill stays put too -- the thing
    Roll used to get wrong."""
    before, _ = _state(pg)
    _drag(pg, '.st-trim[data-trim="1"]', 30)               # 0.3 s
    after, _ = _state(pg)
    assert after[1]["duration"] - after[1]["pre"] > before[1]["duration"] - before[1]["pre"] + 0.2
    assert after[2]["pre"] < before[2]["pre"]
    _kills_where_they_were(before, after)
    assert after[3]["start"] == pytest.approx(before[3]["start"], abs=1e-3)


def test_the_whole_request_in_two_drags(pg):
    """Shorter lead-up and longer tail on the same shot, which is the edit the
    recording was trying to make. Nothing outside the three shots it touches
    moves, and no kill anywhere moves."""
    before, _ = _state(pg)
    _drag(pg, '.st-trim-l[data-trim-l="1"]', 80)
    _drag(pg, '.st-trim[data-trim="1"]', 30)
    after, _ = _state(pg)
    _kills_where_they_were(before, after)
    assert after[3]["start"] == pytest.approx(before[3]["start"], abs=1e-3)
    total = lambda rows: sum(r["duration"] for r in rows)
    assert total(after) == pytest.approx(total(before), abs=1e-3), "the reel changed length"


def test_shift_still_pushes_everything_after(pg):
    """The old trim, on purpose and on Shift: sometimes it is what is meant."""
    before, _ = _state(pg)
    _drag(pg, '.st-trim[data-trim="1"]', 30, shift=True)
    after, _ = _state(pg)
    assert after[1]["duration"] > before[1]["duration"] + 0.2
    assert after[3]["start"] > before[3]["start"] + 0.2


# ---- where a cut has to stop ----------------------------------------------


def test_a_cut_cannot_pass_the_next_shots_kill_and_says_so(pg):
    """Shot 3's kill is 0.64 s in. Dragging the cut a full second into it
    would cut the kill out of its own shot: it stops short, and says why."""
    _drag(pg, '.st-trim[data-trim="1"]', 100)              # 1.0 s, far past it
    after, _ = _state(pg)
    assert after[2]["pre"] >= 0.1 - 1e-6, after[2]
    toast = pg.locator(".toast").last.inner_text(timeout=3000)
    assert "kill" in toast.lower(), toast


def test_a_cut_cannot_run_past_the_footage_a_clip_has(pg):
    """A shot cut past the end of its footage is trimmed back by a whole beat on
    the server -- which pushes everything after it, the very fault this
    replaces. So the drag stops at the footage, two frames short."""
    pg.evaluate("""() => {
      const s = studio.project.shots[1], r = studio.derived.shots[1];
      s.clip_seconds = r.source_out + 0.05;       // 0.05 s of footage left after it
      studio_drawTimeline();
    }""")
    before, _ = _state(pg)
    _drag(pg, '.st-trim[data-trim="1"]', 40)               # asks for 0.4 s
    after, _ = _state(pg)
    assert after[1]["duration"] - before[1]["duration"] < 0.05


def test_the_start_of_the_reel_moves_the_song_with_it(pg):
    """The first shot has nothing before it. Trimming its head moves reel zero,
    and the song moves by the same amount, so every kill still meets the same
    moment of the music."""
    pg.evaluate(SETUP, True)
    before, off0 = _state(pg)
    _drag(pg, '.st-trim-l[data-trim-l="0"]', 50)           # 0.5 s
    after, off1 = _state(pg)
    trimmed = before[0]["pre"] - after[0]["pre"]
    assert trimmed > 0.3
    assert off1 == pytest.approx(off0 + trimmed, abs=1e-3)
    for a, b in zip(before, after):                         # song time = reel time + offset
        assert b["kill_at"] + off1 == pytest.approx(a["kill_at"] + off0, abs=1e-3)


# ---- the inspector says the same thing the edges do -----------------------


def test_the_inspector_buttons_move_the_cuts_too(pg):
    """'Before the kill' and 'After the kill' replace Run-up and Length, which
    were the two controls in the recording that moved the wrong thing."""
    pg.evaluate("() => studio_drawAll()")
    pg.wait_for_timeout(200)
    labels = pg.evaluate("""() => [...document.querySelectorAll('.field-label')]
                                 .map(e => e.textContent.trim())""")
    assert "Before the kill" in labels and "After the kill" in labels
    assert "Run-up" not in labels and "Length" not in labels
    before, _ = _state(pg)
    pg.locator('[data-act="studio-cut"][data-end="head"][data-d="-1"]').first.click()
    pg.wait_for_timeout(200)
    after, _ = _state(pg)
    assert after[1]["pre"] < before[1]["pre"]
    _kills_where_they_were(before, after)
    assert after[3]["start"] == pytest.approx(before[3]["start"], abs=1e-3)
