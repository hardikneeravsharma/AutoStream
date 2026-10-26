r"""Tier 7: one reel, three editors -- the part, the kill marks, the drops, and what becomes of them.

THE BUG THIS STARTED WITH (Hardik's recording, 2026-10-23). On the timeline's Song tab the part was
dragged from 0:00-0:44 to 0:59-2:07. The 21 kill-mark diamonds kept their offsets from the part's
start: none of them sat on the new section's beats, they covered 40% of the longer part, nothing said
the timing was stale, and Render would have rendered it. tests/verify/probe_part_drag.py shows it.

THE INVARIANT now: never silently discard an explicit edit, and never render a plan that no longer
matches the reel's own choices. Every scenario 6.86-6.104 in docs/UI-SCENARIOS.md is here, against
the real page, the real planner and -- for the versions -- a real render.

    $env:AUTOSTREAM_VERIFY_SOURCE=1
    .\.venv\Scripts\python.exe -m pytest tests\verify\test_ui_studio_timing.py -m ui -q -p no:randomly
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import appd
import pytest
from test_ui_studio_guide import _clips_then_song, _drop_song, _filled, _rich_clips

pytestmark = pytest.mark.ui

BEAT = 0.5                                  # every song here is 120 BPM


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

    home = tmp_path_factory.mktemp("timing")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    _rich_clips(home, n=14)
    songs = home / "video" / "songs"
    appd.click_track(songs / "long click.wav", seconds=150.0, bpm=120.0)
    _drop_song(songs / "drop song.wav")
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


@pytest.fixture
def pg(browser, app):
    ctx = browser.new_context(viewport={"width": 1500, "height": 1000})
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("console", lambda m: trouble.append(m.text)
            if m.type == "error" and "studio/thumb" not in m.text and "clips/video" not in m.text
            and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.click('[data-act="studio-refresh"]')
    page.wait_for_function("() => studio.lib && Object.keys(studio.clipIndex || {}).length >= 14", timeout=60_000)
    page.wait_for_function("() => studio.catalog && studio.catalog.editflow", timeout=30_000)
    page.trouble = trouble
    page.app = app
    yield page
    assert not page.trouble, page.trouble
    ctx.close()


def _song(app, name):
    return str(Path(app["home"]) / "video" / "songs" / name)


# The requests the page makes, kept; a render is refused unless a test lets it through.
SPY = """(letRender) => { window.__asked = []; const post = API.post;
  API.post = function (u, b) {
    window.__asked.push(u);
    if (u === '/api/studio/render' && !letRender) return Promise.resolve({ok: false, error: 'not rendered in this test'});
    if ((u === '/api/studio/replan' || u === '/api/studio/retime') && window.__hold) {
      const self = this, args = arguments;
      return new Promise(res => { (window.__held = window.__held || []).push(() => post.apply(self, args).then(res)); });
    }
    return post.apply(this, arguments); }; }"""


def _reel(pg, *, part=(0.0, 44.0), style="montage", song="long click.wav", n=12, render=False):
    """A reel planned for real on `part` of the song, open on the timeline and never rendered."""
    pg.evaluate(SPY, render)
    got = pg.evaluate("""async (a) => {
        const clips = Object.keys(studio.clipIndex).sort().slice(0, a.n).map(id => studio.clipIndex[id].path);
        const r = await API.post('/api/studio/plan', {clips: clips, style: a.style, song: a.song, format: 'landscape',
            name: 'timing', part_start: a.part[0], part_end: a.part[1], dry: true, shaping: {fill: 'part'}});
        if (!r || !r.ok) return r;
        studio_show('studio-guide-scrim', false); studio_show('studio-make-scrim', false); studio_makePage(false);
        studio.adding = null; studio_flowForget(); studio.flow.ask = '';
        studio.undo = []; studio.redo = []; studio.output = ''; studio.playFile = '';
        studio_setProject(r.project, r.derived, r.notes, r.song);
        studio.pending = []; studio.base = JSON.parse(JSON.stringify(studio.project)); studio.dirty = true;
        studio_tab('timeline'); studio_fit(); studio_drawAll();
        return {ok: true};
    }""", {"part": list(part), "style": style, "song": _song(pg.app, song), "n": n})
    assert got and got.get("ok"), got


def _song_tab(pg):
    pg.click("#studio-tab-song")
    pg.wait_for_selector("#studio-sg-body:not(.hide)", state="attached", timeout=60_000)
    pg.wait_for_function("() => studio.sg.shape && studio.sg.shape.peaks", timeout=60_000)
    pg.wait_for_timeout(200)


def _px(pg, t):
    """Where song second `t` is on the whole-song overview, and its middle -- scrolled into view
    first: a button pressed lower on the tab can leave the song above the window."""
    ov = pg.locator("#studio-sg-overview")
    ov.scroll_into_view_if_needed()
    box = ov.bounding_box()
    secs = pg.evaluate("studio.sg.shape.seconds")
    return box["x"] + t / secs * box["width"], box["y"] + box["height"] / 2


def _drag_part(pg, by, *, hold=False):
    """Grab the part by its middle and move it `by` seconds. `hold` leaves the button down."""
    s, e = pg.evaluate("[studio.sg.start, studio.sg.end]")
    x0, y = _px(pg, (s + e) / 2)
    x1, _ = _px(pg, (s + e) / 2 + by)
    pg.mouse.move(x0, y)
    pg.mouse.down()
    pg.mouse.move(x1, y, steps=12)
    if not hold:
        pg.mouse.up()
        pg.wait_for_timeout(150)


def _drag_end(pg, to):
    s, e = pg.evaluate("[studio.sg.start, studio.sg.end]")
    x0, y = _px(pg, e)
    x1, _ = _px(pg, to)
    pg.mouse.move(x0, y)
    pg.mouse.down()
    pg.mouse.move(x1, y, steps=12)
    pg.mouse.up()
    pg.wait_for_timeout(150)


MARKS = "studio_tmKillList(studio.sg).map(k => Math.round(k.t * 1000) / 1000)"


def _wait_prop(pg):
    pg.wait_for_function("() => studio.flow.prop || studio.flow.conflicts || studio.flow.err", timeout=180_000)
    assert not pg.evaluate("studio.flow.err"), pg.evaluate("studio.flow.err")


# ---------------------------------------------------------------- 6.86 the reported bug

def test_moving_the_part_never_moves_the_marks_and_holds_render(pg):
    _reel(pg)
    _song_tab(pg)
    before = pg.evaluate(MARKS)
    assert before, "the reel has kills to mark"
    undo0 = pg.evaluate("studio.undo.length")
    # WHILE IT IS DRAGGED, only the range and the waveform move
    _drag_part(pg, 59.0, hold=True)
    mid = pg.evaluate("({undo: studio.undo.length, draft: studio.project.draft || null, marks: " + MARKS +
                      ", asked: window.__asked.slice(), start: studio.sg.start})")
    assert mid["undo"] == undo0 and mid["draft"] is None, "the reel changed while the part was still in the hand"
    assert mid["marks"] == before and mid["start"] > 40
    assert not any(u in ("/api/studio/replan", "/api/studio/retime", "/api/studio/check") for u in mid["asked"])
    pg.mouse.up()
    pg.wait_for_timeout(200)
    _drag_end(pg, 127.0)
    st = pg.evaluate("({draft: studio.project.draft, marks: " + MARKS + ", start: studio.sg.start, end: studio.sg.end,"
                     " t0: Number(document.getElementById('studio-sg-detail').getAttribute('data-t0'))})")
    # every mark is where it was on the song: none followed the part
    assert st["marks"] == before, (before, st["marks"])
    # and the part itself landed on a beat (6.6)
    beats = pg.evaluate("studio.sg.shape.beats")
    assert min(abs(st["start"] - b) for b in beats) < 1e-3
    assert st["draft"]["start"] == pytest.approx(st["start"]) and st["end"] == pytest.approx(127.0, abs=0.6)
    assert all(abs(m / BEAT - round(m / BEAT)) < 0.02 for m in st["marks"])
    # the part up close is the NEW section, drawn on its own beats
    assert st["t0"] > 50
    banner = pg.inner_text("#studio-sg-stale")
    assert "Song part changed \u2014 kill timing needs updating" in banner
    pg.click("#studio-tab-timeline")
    assert pg.is_disabled("#studio-render-btn")
    assert "Replan for this section" in pg.get_attribute("#studio-render-btn", "title")
    assert pg.is_visible("#studio-tl-replan")
    assert "Song part changed" in pg.inner_text("#studio-tl-stale")
    assert "the kill timing is out of date" in pg.inner_text("#studio-stale")
    # and the server refuses it too, whatever the page thought
    got = pg.evaluate("() => API.post('/api/studio/render', {project: studio.project})")
    assert got["ok"] is False


def test_the_part_put_back_is_no_change(pg):
    _reel(pg)
    _song_tab(pg)
    undo0 = pg.evaluate("studio.undo.length")
    _drag_part(pg, 30.0, hold=True)
    pg.mouse.move(*_px(pg, pg.evaluate("(studio.sg.start + studio.sg.end) / 2") - 30.0), steps=12)
    pg.mouse.up()
    pg.wait_for_timeout(200)
    assert pg.evaluate("studio.project.draft || null") is None
    assert pg.evaluate("studio.undo.length") == undo0, "a part released where it was is an undo step"
    assert pg.inner_text("#studio-sg-stale").strip() == ""
    pg.evaluate("studio_sgNudge('start', 'bar')")
    assert pg.evaluate("!!studio.project.draft")
    pg.evaluate("studio_sgNudge('start', '-bar')")
    assert pg.evaluate("studio.project.draft || null") is None, "nudged and back is no draft"
    assert pg.evaluate("studio.pending.length") == 0


# ---------------------------------------------------------------- 6.88 the button nobody misses

def test_the_replan_button_is_highlighted_and_still_for_reduced_motion(pg):
    _reel(pg)
    _song_tab(pg)
    _drag_part(pg, 40.0)
    sel = '#studio-sg-stale [data-act="studio-flow"][data-do="replan"]'
    assert pg.inner_text(sel) == "Replan for this section"
    look = pg.eval_on_selector(sel, """e => ({cls: e.className, anim: getComputedStyle(e).animationName,
        shadow: getComputedStyle(e).boxShadow})""")
    assert "btn-primary" in look["cls"] and "studio-attn" in look["cls"]
    assert look["anim"] == "studio-attn" and look["shadow"] != "none"
    for other in ("Keep my shots, retime them", "Undo part change"):
        assert pg.locator("#studio-sg-stale button", has_text=other).count() == 1
    assert pg.locator("#studio-sg-stale button", has_text="Re-snap my marks").count() == 0, "no hand marks yet"
    pg.emulate_media(reduced_motion="reduce")
    still = pg.eval_on_selector(sel, "e => ({anim: getComputedStyle(e).animationName, shadow: getComputedStyle(e).boxShadow})")
    assert still["anim"] == "none" and still["shadow"] != "none", "still highlighted, without the motion"
    pg.click("#studio-tab-timeline")
    box = pg.locator("#studio-tl-replan").bounding_box()
    render = pg.locator("#studio-render-btn").bounding_box()
    assert box and render and abs(box["y"] - render["y"]) < 6 and box["x"] < render["x"], "beside Render"


# ---------------------------------------------------------------- 6.89 replan, with a diff, one undo

def test_replan_shows_a_diff_and_applies_as_one_undo_step(pg):
    _reel(pg)
    _song_tab(pg)
    _drag_part(pg, 59.0)
    stale = pg.evaluate("studio_canon(studio.project)")
    undo0 = pg.evaluate("studio.undo.length")
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="replan"]')
    assert pg.evaluate("studio.flow.busy") == "replan"
    assert pg.evaluate("studio_badgeState().key") == "planning"
    _wait_prop(pg)
    text = pg.inner_text("#studio-sg-stale")
    assert "apply it?" in text and "Shots:" in text and "Kills:" in text and "Length:" in text
    assert pg.evaluate("studio.project.draft") is not None, "nothing is applied before Apply"
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="apply"]')
    p = pg.evaluate("studio.project")
    start = pg.evaluate("studio.sg.start")
    assert "draft" not in p and p["song_offset"] == pytest.approx(start, abs=0.01)
    assert all(start - 0.01 <= m <= p["part_end"] + 0.01 for m in p["song_marks"])
    assert pg.evaluate("studio.undo.length") == undo0 + 1, "applying a plan is one step of undo"
    pg.click("#studio-tab-timeline")
    assert not pg.is_disabled("#studio-render-btn")
    pg.click("#studio-undo-btn")
    assert pg.evaluate("studio_canon(studio.project)") == stale, "undo brings back the stale reel exactly"


# ---------------------------------------------------------------- 6.90 a stale answer is dropped

def test_drag_release_and_drag_again_never_applies_a_stale_answer(pg):
    _reel(pg)
    _song_tab(pg)
    _drag_part(pg, 30.0)
    pg.evaluate("() => { window.__hold = true; }")
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="replan"]')
    pg.wait_for_function("() => (window.__held || []).length === 1")
    _drag_part(pg, 20.0)                                # a newer part while the first is planned
    assert pg.evaluate("studio.flow.busy") == "", "the answer being worked out is for a part that is gone"
    pg.evaluate("() => { window.__hold = false; window.__held[0](); }")
    pg.wait_for_timeout(2500)
    pg.wait_for_function("() => window.__asked.filter(u => u === '/api/studio/replan').length === 1")
    assert pg.evaluate("studio.flow.prop") is None, "an answer for the first part was offered for the second"
    assert pg.evaluate("!!studio.project.draft")
    assert "Song part changed" in pg.inner_text("#studio-sg-stale")


# ---------------------------------------------------------------- 6.91 keep my shots

def test_keep_my_shots_keeps_order_trims_effects_and_hand_marks(pg):
    _reel(pg)
    pg.evaluate("() => studio_change(p => { p.shots[1].fx = ['k07']; p.shots[2].caption = 'MINE'; }, 'effects')")
    pg.wait_for_timeout(600)
    clips = pg.evaluate("studio.project.shots.map(s => s.clip)")
    pres = pg.evaluate("studio.project.shots.map(s => s.pre)")
    _song_tab(pg)
    _drag_part(pg, 59.0)
    start = pg.evaluate("studio.sg.start")
    hand = round(start + 6.0, 3)
    pg.evaluate("(t) => studio_tmAddMark(studio_tmView('song'), t)", hand)
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="retime"]')
    _wait_prop(pg)
    assert not pg.evaluate("studio.flow.conflicts"), pg.evaluate("studio.flow.conflicts")
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="apply"]')
    p = pg.evaluate("studio.project")
    assert [s["clip"] for s in p["shots"]] == clips, "the same clips in the same order"
    assert p["shots"][1]["fx"] == ["k07"] and p["shots"][2]["caption"] == "MINE"
    kept = sum(1 for a, b in zip(pres, (s["pre"] for s in p["shots"])) if abs(a - b) < 1 / 60 + 1e-6)
    assert kept >= len(pres) // 2, (pres, [s["pre"] for s in p["shots"]])
    assert hand in [round(m, 3) for m in p["song_marks"]] and hand in [round(a, 3) for a in p.get("anchors", [])]
    beats = pg.evaluate("studio.sg.shape.beats")
    on = lambda m: min(abs(m - b) for b in beats) < 0.035                 # noqa: E731  a hit is on its beat
    assert all(on(m) or abs(m - hand) < 1e-3 for m in p["song_marks"][:len(p["shots"])]), p["song_marks"]


# ---------------------------------------------------------------- 6.92 undo part change

def test_undo_part_change_restores_the_plan_with_no_replan(pg):
    _reel(pg)
    _song_tab(pg)
    planned = pg.evaluate("studio_canon(studio.project)")
    _drag_part(pg, 45.0)
    n = pg.evaluate("window.__asked.length")
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="undo"]')
    pg.wait_for_timeout(400)
    asked = pg.evaluate("(n) => window.__asked.slice(n)", n)
    assert "/api/studio/replan" not in asked and "/api/studio/retime" not in asked and "/api/studio/plan" not in asked
    assert pg.evaluate("studio_canon(studio.project)") == planned
    assert pg.inner_text("#studio-sg-stale").strip() == ""
    pg.click("#studio-tab-timeline")
    assert not pg.is_disabled("#studio-render-btn")


# ---------------------------------------------------------------- 6.93 hand marks

def test_hand_marks_are_never_moved_for_you_and_resnap_is_asked_for(pg):
    _reel(pg)
    _song_tab(pg)
    pg.click('[data-act="studio-sg-fromkills"]')
    mine = pg.evaluate("studio.project.anchors")
    assert mine and len(mine) >= 5
    _drag_part(pg, 60.0)
    assert pg.evaluate("studio.project.anchors") == mine, "moving the part moved your marks"
    pg.wait_for_selector('#studio-sg-stale [data-act="studio-flow"][data-do="resnap"]', timeout=5_000)
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="retime"]')
    _wait_prop(pg)
    c = pg.evaluate("studio.flow.conflicts")
    assert c and c[0]["kind"] == "marks-outside", c
    assert pg.evaluate("studio.project.anchors") == mine
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="discard"]')
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="resnap"]')
    moved = pg.evaluate("studio.project.anchors")
    start, s0 = pg.evaluate("[studio.sg.start, studio.project.song_offset]")
    assert len(moved) == len(mine)
    assert all(abs((b - a) - (start - s0)) <= BEAT / 2 + 1e-3 for a, b in zip(mine, moved)), (mine, moved)
    # a replan keeps them where they are now
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="replan"]')
    _wait_prop(pg)
    prop = pg.evaluate("studio.flow.prop.project")
    assert prop["anchors"] == moved


# ---------------------------------------------------------------- 6.94 the drop leaves the part

def test_a_drop_outside_the_part_blocks_a_drop_style_with_fixes(pg):
    _reel(pg, song="drop song.wav", part=(30.0, 60.0))
    pg.evaluate("() => studio_change(p => { p.style = 'drop'; p.hand_drops = [40.0]; }, 'drop style')")
    pg.wait_for_timeout(500)
    _song_tab(pg)
    pg.wait_for_function("() => studio.sg.drops && studio.sg.drops.length")
    _drag_part(pg, 30.0)
    assert pg.evaluate("studio.sg.start") > 40.5
    banner = pg.inner_text("#studio-sg-stale")
    assert "the drop" in banner and "outside the part" in banner
    for do in ("replan", "retime"):
        assert pg.is_disabled(f'#studio-sg-stale [data-act="studio-flow"][data-do="{do}"]'), do
    fixes = pg.locator('#studio-sg-stale [data-act="studio-flow-fix"]').all_inner_texts()
    assert fixes == ["Move the part to the drop", "Mark a drop in this part", "Choose another style"]
    pg.click('#studio-sg-stale [data-act="studio-flow-fix"][data-fix="move-to-drop"]')
    s, e = pg.evaluate("[studio.sg.start, studio.sg.end]")
    assert s <= 40.0 <= e
    assert not pg.is_disabled('#studio-sg-stale [data-act="studio-flow"][data-do="replan"]')


def test_the_make_page_will_not_build_a_drop_style_with_the_drop_outside(pg):
    pg.evaluate(SPY, False)
    pg.evaluate("""() => { const ids = Object.keys(studio.clipIndex).sort().slice(0, 8);
        studio.selected = ids; studio.style = 'drop'; studio_tmFresh(); studio.mkFrom = null; }""")
    pg.evaluate("studio_openMake()")
    pg.wait_for_selector("#studio-make-scrim:not(.hide)")
    pg.evaluate("(p) => studio_useSong(p)", _song(pg.app, "drop song.wav"))
    pg.wait_for_function("() => studio.songShape && studio.songShape.drop")
    pg.evaluate("() => { const mk = studio.mk; const was = {start: mk.start, end: mk.end}; mk.start = 60; mk.end = 85; studio_mkPartChanged(was); }")
    assert pg.is_disabled("#studio-build-btn")
    assert "outside the part" in pg.get_attribute("#studio-build-btn", "title")
    assert pg.evaluate("studio_mkBadgeState().key") == "failed"
    pg.click('#studio-mk-stale [data-act="studio-mk-flow"][data-do="move-to-drop"]')
    assert not pg.is_disabled("#studio-build-btn")


# ---------------------------------------------------------------- 6.95 too short

def test_a_part_too_short_for_the_locked_shots_is_a_clear_conflict(pg):
    _reel(pg)
    pg.evaluate("() => studio_change(p => { p.shots.forEach(s => { s.lock = 'all'; }); }, 'locked')")
    pg.wait_for_timeout(500)
    _song_tab(pg)
    s = pg.evaluate("studio.sg.start")
    pg.evaluate("(e) => { const sg = studio.sg, was = {start: sg.start, end: sg.end}; sg.end = e; studio_sgPart(was); }", s + 4.0)
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="retime"]')
    _wait_prop(pg)
    c = pg.evaluate("studio.flow.conflicts")
    assert c and c[0]["kind"] == "too-short", c
    text = pg.inner_text("#studio-sg-stale")
    assert "cannot be done" in text and "locked, pinned or on your own marks" in text
    fixes = pg.locator('#studio-sg-stale [data-act="studio-flow-fix"]').all_inner_texts()
    assert any(f.startswith("Make the part") for f in fixes) and "Let locked shots go too" in fixes
    n = pg.evaluate("studio.project.shots.length")
    pg.click('#studio-sg-stale [data-act="studio-flow-fix"][data-fix="longer-part"]')
    _wait_prop(pg)
    assert pg.evaluate("studio.flow.prop") and not pg.evaluate("studio.flow.conflicts")
    assert pg.evaluate("studio.flow.prop.project.shots.length") == n, "every locked shot kept"


# ---------------------------------------------------------------- 6.96 what each update keeps

def test_each_way_to_update_says_what_survives_before_it_runs(pg):
    _reel(pg)
    actions = pg.evaluate("studio.catalog.editflow.actions")
    for do in ("rerender", "retime", "replan"):
        n = pg.evaluate("window.__asked.length")
        pg.click(f'[data-act="studio-flow-ask"][data-do="{do}"]')
        text = pg.inner_text("#studio-tl-stale")
        assert "keeps" in text.lower() and "changes" in text.lower()
        assert actions[do]["keeps"][0] in text and actions[do]["changes"][0] in text
        assert pg.evaluate("(n) => window.__asked.slice(n).filter(u => /replan|retime|render/.test(u)).length", n) == 0
        pg.click('#studio-tl-stale [data-act="studio-flow"][data-do="discard"]')
    pg.click('[data-act="studio-flow-ask"][data-do="replan"]')
    assert pg.locator("#studio-flow-style").count() == 1
    pg.select_option("#studio-flow-style", "hype")
    pg.click('#studio-tl-stale [data-act="studio-flow"][data-do="replan"]')
    _wait_prop(pg)
    assert pg.evaluate("studio.flow.prop.label") == "Replanned as Hype"
    pg.click('#studio-tl-stale [data-act="studio-flow"][data-do="apply"]')
    assert pg.evaluate("studio.project.style") == "hype"
    # Re-render waits while the timing is stale, and says so
    _song_tab(pg)
    _drag_part(pg, 30.0)
    pg.click("#studio-tab-timeline")
    pg.click('[data-act="studio-flow-ask"][data-do="rerender"]')
    assert pg.is_disabled('#studio-tl-stale [data-act="studio-flow"][data-do="rerender"]')
    assert "update the timing first" in pg.inner_text("#studio-tl-stale")


# ---------------------------------------------------------------- 6.97 add clips

def test_add_clips_to_the_pool_or_one_shot_or_a_replan(pg):
    _reel(pg, n=8)
    pg.wait_for_timeout(600)
    SHOTS = "JSON.stringify(studio.project.shots.map(s => [s.clip, s.kill, s.pre, s.duration, s.fx, s.transition]))"
    shots = pg.evaluate(SHOTS)
    pg.evaluate("studio_select(-1)")
    pg.click('#studio-why [data-act="studio-add"]')
    text = pg.inner_text("#studio-tl-stale")
    assert "pool" in text and "Replace" in text and "Replan with these clips" in text
    assert pg.is_disabled('[data-act="studio-add-how"][data-how="replace"]'), "no shot selected"
    pg.click('[data-act="studio-add-how"][data-how="pool"]')
    pg.wait_for_selector("#studio-pane-clips:not(.hide)")
    extra = pg.evaluate("() => Object.keys(studio.clipIndex).sort().slice(10, 12)")
    pg.evaluate("(ids) => { studio.selected = ids; studio_syncSelection(); }", extra)
    assert pg.inner_text("#studio-make-btn") == "Add 2 clips to the pool"
    pg.click("#studio-make-btn")
    pg.wait_for_selector("#studio-pane-timeline:not(.hide)")
    pg.wait_for_timeout(800)
    assert pg.evaluate(SHOTS) == shots, "the pool changed a shot"
    sel = pg.evaluate("studio.project.selection")
    assert sum(1 for r in sel if "In the pool" in (r.get("why") or "")) == 2
    assert pg.evaluate("studio.pending.length") == 0, "a clip waiting in the pool is not a change to render"
    # one shot's clip
    pg.evaluate("studio_select(2)")
    before = pg.evaluate("studio.project.shots[2]")
    pg.click('#studio-why [data-act="studio-add"]')
    # ...from the clips that land a kill on its beat (clips/slots.py), on the timeline itself
    pg.click('[data-act="studio-add-how"][data-how="replace"]')
    pg.wait_for_selector("#studio-slot:not([aria-busy])", timeout=30_000)
    assert pg.is_visible("#studio-pane-timeline")
    use = pg.query_selector('#studio-slot [data-do="use"]')
    assert use, pg.inner_text("#studio-slot")
    want = use.get_attribute("data-clip")
    use.click()
    pg.wait_for_function("(c) => studio.project.shots[2].clip === c", arg=want, timeout=30_000)
    pg.wait_for_timeout(800)
    after = pg.evaluate("studio.project.shots[2]")
    assert after["clip"] == want
    assert after["fx"] == before["fx"] and after["transition"] == before["transition"]
    assert pg.evaluate("studio.project.shots.length") == len(json.loads(shots))
    # a replan opens the Make page, which says what it keeps
    pg.click('#studio-why [data-act="studio-add"]')
    pg.click('[data-act="studio-add-how"][data-how="replan"]')
    pg.wait_for_selector("#studio-pane-clips:not(.hide)")
    assert pg.inner_text("#studio-make-btn").startswith("Replan timing with these clips")


# ---------------------------------------------------------------- 6.98 the badge

def test_the_state_badge_names_every_state(pg):
    _reel(pg)
    badge = lambda: pg.get_attribute("#studio-badge", "data-state")       # noqa: E731
    assert badge() == "ready" and pg.inner_text("#studio-badge") == "Ready to render"
    _song_tab(pg)
    _drag_part(pg, 40.0)
    pg.click("#studio-tab-timeline")
    assert badge() == "stale" and pg.inner_text("#studio-badge") == "Timing stale"
    pg.evaluate("() => { window.__hold = true; }")
    pg.click("#studio-tl-replan")
    assert badge() == "planning" and pg.inner_text("#studio-badge") == "Planning"
    pg.evaluate("() => { window.__hold = false; window.__held[0](); }")
    _wait_prop(pg)
    pg.click('#studio-tl-stale [data-act="studio-flow"][data-do="apply"]')
    assert badge() == "ready"
    pg.evaluate("() => { studio.output = 'C:/reels/x.mp4'; studio_settled(); studio_drawRenderCard(); }")
    assert badge() == "rendered" and pg.inner_text("#studio-badge") == "Rendered"
    pg.evaluate("() => studio_change(p => { p.vignette = !p.vignette; }, 'Vignette')")
    assert badge() == "changed" and pg.inner_text("#studio-badge") == "Changed"
    pg.evaluate("() => { studio_busy(true); studio_drawRenderCard(); }")
    assert badge() == "rendering" and pg.inner_text("#studio-badge") == "Rendering"
    pg.evaluate("() => { studio_busy(false); studio.failMsg = 'The render failed.'; studio_drawRenderCard(); }")
    assert badge() == "failed" and pg.inner_text("#studio-badge") == "Check failed"
    # and on the Make page
    pg.evaluate("() => { studio.failMsg = ''; studio.selected = Object.keys(studio.clipIndex).sort().slice(0, 6); studio.mkFrom = null; studio.adding = null; }")
    pg.evaluate("studio_openMake()")
    pg.wait_for_selector("#studio-make-scrim:not(.hide)")
    assert pg.get_attribute("#studio-mk-badge", "data-state") in ("changed", "planning", "ready")
    pg.wait_for_function("() => document.getElementById('studio-mk-badge').getAttribute('data-state') === 'ready'"
                         " || document.getElementById('studio-mk-badge').getAttribute('data-state') === 'failed'", timeout=60_000)


# ---------------------------------------------------------------- 6.99, 6.100 render versions

def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _render(pg):
    n = pg.evaluate("studio.jobId")
    pg.click("#studio-render-btn")
    pg.wait_for_function("(n) => studio.jobId && studio.jobId !== n", arg=n, timeout=60_000)
    pg.wait_for_function("/^Ready|Rendered, but/.test(document.getElementById('studio-state').textContent) "
                         "|| /fail/i.test(document.getElementById('studio-state').textContent)", timeout=600_000)
    assert "fail" not in pg.inner_text("#studio-state").lower(), pg.inner_text("#studio-state")


def test_a_render_is_a_new_version_and_history_restores_or_saves_it(pg):
    _reel(pg, n=5, part=(0.0, 12.0), render=True)
    pg.evaluate("() => studio_autoSet(false)")
    _render(pg)
    out = pg.evaluate("studio.output")
    v1 = _sha(out)
    vdir = Path(out).parent / ".versions" / Path(out).stem
    assert (vdir / "v1.mp4").is_file() and _sha(vdir / "v1.mp4") == v1
    assert "/.versions/" in pg.evaluate("studio.playFile").replace("\\", "/"), "the player plays the version file"
    pg.evaluate("() => studio_change(p => { p.vignette = !p.vignette; p.grade = 'g05'; }, 'Look')")
    pg.wait_for_timeout(500)
    pg.click("#studio-render-btn")
    # while it renders the reel is the first render, whole
    pg.wait_for_function("studio.rendering", timeout=30_000)
    assert _sha(out) == v1
    pg.wait_for_function("/^Ready|Rendered, but/.test(document.getElementById('studio-state').textContent)", timeout=600_000)
    assert _sha(vdir / "v1.mp4") == v1, "the version before was touched"
    assert _sha(out) == _sha(vdir / "v2.mp4") != v1
    pg.click("#studio-hist-btn")
    pg.wait_for_selector('.studio-ver-row[data-version="1"]')
    rows = pg.locator(".studio-ver-row").all_inner_texts()
    assert len(rows) == 2 and "the reel now" in rows[0] and "5 shots" in rows[1]
    # Restore this version
    undo0 = pg.evaluate("studio.undo.length")
    pg.click('[data-act="studio-ver-restore"][data-v="1"]')
    pg.wait_for_function("() => studio.versions.current === 1", timeout=30_000)
    assert _sha(out) == v1 and pg.evaluate("studio.undo.length") == undo0 + 1
    assert pg.evaluate("studio.project.render_version") == 1
    # Save as new reel
    pg.click('[data-act="studio-ver-fork"][data-v="2"]')
    pg.wait_for_function("(o) => studio.output && studio.output !== o", arg=out, timeout=30_000)
    fork = pg.evaluate("studio.output")
    assert _sha(fork) == _sha(vdir / "v2.mp4") and _sha(out) == v1, "the original reel was touched"


# ---------------------------------------------------------------- 6.101 one editor

def test_the_same_draft_and_editor_in_the_guide_the_make_page_and_the_song_tab(pg):
    pg.evaluate(SPY, False)
    pg.click("#studio-gd-open")
    pg.wait_for_selector("#studio-guide-scrim:not(.hide)")
    pg.click('.gd-card[data-key="montage"]')
    _clips_then_song(pg)
    pg.click('.gd-card[data-gd="song"][data-name*="drop song"]')
    pg.wait_for_function("() => studio.songShape && studio.song.indexOf('drop song') >= 0", timeout=60_000)
    pg.wait_for_selector("#studio-gd-dropcv")
    pg.evaluate("() => studio_gdAddDrop(22.5)")
    assert 22.5 in pg.evaluate("studio.mk.drops.map(d => d.t)"), "the guide's drop is not the draft's"
    pg.evaluate("() => studio_gdPickAll(true)")
    _filled(pg)
    pg.click('[data-act="studio-gd"][data-gd="all"]')
    pg.wait_for_selector("#studio-make-scrim:not(.hide)")
    assert "22.5" in pg.inner_text("#studio-mk-droplist").replace(":", "") or \
        any(abs(t - 22.5) < 1e-6 for t in pg.evaluate("studio_mkDropList().map(d => d.t)"))
    # a mark placed on the Make page is the draft's: the guide's plan carries it
    pg.evaluate("(t) => studio_mkAddMark(t)", pg.evaluate("studio.mk.start + 3.0"))
    mark = pg.evaluate("studio.mk.hand.filter(k => !k.auto)[0].t")
    pg.click("#studio-mk-guide")
    pg.wait_for_selector("#studio-guide-scrim:not(.hide)")
    body = pg.evaluate("studio_gdBody()")
    assert mark in body["marks"] and 22.5 in body["drops"]
    # and the Song tab's part-up-close is the Make page's editor: a double-click marks a kill there too
    _reel(pg)
    _song_tab(pg)
    assert pg.evaluate("studio_tmView('song').cv") == "studio-sg-detail"
    box = pg.locator("#studio-sg-detail").bounding_box()
    marks = pg.evaluate(MARKS)
    n = len(marks)
    # A DOUBLE-CLICK ON A MARK REMOVES IT, so aim at the widest gap between marks: the canvas's middle
    # was within 11 px of a mark on some plans, and the test then counted one fewer.
    t0, t1 = pg.evaluate("['data-t0', 'data-t1'].map(a => +studio_el('studio-sg-detail').getAttribute(a))")
    edges = [t0] + sorted(m for m in marks if t0 <= m <= t1) + [t1]
    lo, hi = max(zip(edges, edges[1:]), key=lambda g: g[1] - g[0])
    pg.mouse.dblclick(box["x"] + ((lo + hi) / 2 - t0) / (t1 - t0) * box["width"], box["y"] + box["height"] * 0.6)
    pg.wait_for_timeout(300)
    assert len(pg.evaluate(MARKS)) == n + 1
    assert pg.evaluate("studio.project.draft.marks.length") == n + 1


# ---------------------------------------------------------------- 6.102 the Make page by intent

def test_the_make_page_is_grouped_by_what_each_setting_is_for(pg):
    pg.evaluate("""() => { studio.selected = Object.keys(studio.clipIndex).sort().slice(0, 6); studio.style = 'montage';
        studio.adding = null; studio.mkFrom = null; }""")
    pg.evaluate("studio_openMake()")
    pg.wait_for_selector("#studio-make-scrim:not(.hide)")
    assert pg.locator("#studio-mk-nav .mk-nav-b").all_inner_texts() == ["Style", "Music", "Footage", "Timing", "Look"]
    where = pg.evaluate("""() => ({part: !!document.querySelector('#mk-sec-music #studio-mk-part'),
        drops: !!document.querySelector('#mk-sec-music #studio-mk-droplist'),
        intro: !!document.querySelector('#mk-sec-footage #studio-mk-intro'),
        hs: !!document.querySelector('#mk-sec-footage #studio-hs-row'),
        kills: !!document.querySelector('#mk-sec-timing #studio-mk-kills'),
        fill: !!document.querySelector('#mk-sec-timing #studio-fill'),
        order: !!document.querySelector('#mk-sec-timing #studio-mk-arrange'),
        shape: !!document.querySelector('#mk-sec-look .studio-shape'),
        template: !!document.querySelector('#mk-sec-look #studio-hand'),
        lyrics: !!document.querySelector('#mk-sec-look #studio-mk-lyrics')})""")
    assert all(where.values()), where
    says = pg.evaluate("""() => Array.from(document.querySelectorAll('#studio-make .mk-says[data-change]'))
        .map(e => [e.getAttribute('data-change'), e.textContent])""")
    table = {c["key"]: c["says"] for c in pg.evaluate("studio.catalog.editflow.changes")}
    assert len(says) >= 9 and all(text == table[k] and text for k, text in says), says
    assert "Re-renders only." in [t for _, t in says]


# ---------------------------------------------------------------- 6.103 back to the steps

def test_all_settings_returns_to_the_same_step_with_what_was_chosen(pg):
    pg.evaluate(SPY, False)
    pg.click("#studio-gd-open")
    pg.wait_for_selector("#studio-guide-scrim:not(.hide)")
    pg.click('.gd-card[data-key="montage"]')
    _clips_then_song(pg)
    pg.click('.gd-card[data-gd="song"][data-name*="long click"]')
    pg.wait_for_function("() => studio.songShape && studio.song.indexOf('long click') >= 0", timeout=60_000)
    pg.evaluate("() => studio_gdPickAll(true)")
    _filled(pg)
    quick = pg.evaluate("studio.gd.quick.slice()")
    assert pg.evaluate("studio.gd.step") == 2
    pg.click('[data-act="studio-gd"][data-gd="all"]')
    pg.wait_for_selector("#studio-make-scrim:not(.hide)")
    assert pg.is_visible("#studio-mk-guide")
    pg.click('[data-act="studio-fmt"][data-fmt="landscape"]')
    pg.evaluate("() => studio_mkPreset('whole')")
    part = pg.evaluate("[studio.mk.start, studio.mk.end]")
    looks = pg.evaluate("studio_gdLyricLooks().map(l => l.key)")
    if looks:
        pg.click(f'[data-act="studio-mk-lyrics"][data-v="{looks[0]}"]')
    pg.click("#studio-mk-guide")
    pg.wait_for_selector("#studio-guide-scrim:not(.hide)")
    gd = pg.evaluate("({step: studio.gd.step, fmt: studio.gd.fmt, quick: studio.gd.quick, lyrics: studio.gd.lyrics, style: studio.gd.style})")
    assert gd["step"] == 2 and gd["fmt"] == "landscape" and gd["style"] == "montage"
    assert sorted(gd["quick"]) == sorted(quick)
    if looks:
        assert gd["lyrics"] == looks[0]
    body = pg.evaluate("studio_gdBody()")
    assert body["part_start"] == pytest.approx(part[0]) and body["part_end"] == pytest.approx(part[1])
    assert "part_auto" not in body["shaping"], "the part chosen on All settings is the player's"


# ---------------------------------------------------------------- 6.104 undo covers the song

def test_undo_and_redo_cover_the_songs_timing(pg):
    _reel(pg)
    _song_tab(pg)
    pg.evaluate("studio_sgNudge('start', 'bar')")
    pg.evaluate("(t) => studio_tmAddMark(studio_tmView('song'), t)", pg.evaluate("studio.sg.start + 2.0"))
    assert pg.evaluate("studio.project.draft.marks") is not None
    pg.locator("#studio-sg-name").click()
    pg.keyboard.press("Control+z")
    assert pg.evaluate("(studio.project.draft || {}).marks") is None
    pg.keyboard.press("Control+z")
    assert pg.evaluate("studio.project.draft || null") is None
    pg.keyboard.press("Control+Shift+z")
    assert pg.evaluate("!!studio.project.draft")


# ---------------------------------------------------------------- 6.91 (a longer part), 6.94 (a drop taken away)

def test_a_longer_part_says_there_is_room_and_adds_shots_from_the_pool(pg):
    _reel(pg, n=5, part=(0.0, 14.0))
    n = pg.evaluate("studio.project.shots.length")
    # four clips in the reel's pool, not in it
    pg.evaluate("""() => studio_change(p => {
        const have = new Set(p.shots.map(s => s.clip));
        const more = Object.keys(studio.clipIndex).sort().map(id => studio.clipIndex[id]).filter(c => !have.has(c.path)).slice(0, 4);
        p.selection = (p.selection || []).concat(more.map(c => ({clip: c.path, name: c.name, why: 'In the pool, not in the reel yet.'})));
    }, 'pool')""")
    pg.wait_for_timeout(500)
    _song_tab(pg)
    _drag_end(pg, 70.0)
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="retime"]')
    _wait_prop(pg)
    room = pg.evaluate("studio.flow.prop.room")
    assert room and room["marks"] > 0, "a much longer part says how much room it has"
    assert pg.evaluate("studio.flow.prop.project.shots.length") == n, "re-timing never adds a shot by itself"
    assert "room for" in pg.inner_text("#studio-sg-stale")
    pg.click('#studio-sg-stale [data-act="studio-flow-fix"][data-fix="add"]')
    _wait_prop(pg)
    assert pg.evaluate("studio.flow.prop.project.shots.length") > n, "Add shots added none from the pool"
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="apply"]')
    assert pg.evaluate("studio.project.draft || null") is None


def test_a_drop_taken_away_is_never_found_again(pg):
    _reel(pg, song="drop song.wav", part=(25.0, 60.0))
    _song_tab(pg)
    pg.wait_for_function("() => studio_tmDropList(studio_tmView('song')).length > 0", timeout=30_000)
    found = pg.evaluate("studio_tmDropList(studio_tmView('song')).map(d => d.id)")
    pg.evaluate("(ids) => studio_tmDelIds(studio_tmView('song'), ids)", found)
    assert pg.evaluate("studio.project.draft.drops") == []
    assert "The drops changed" in pg.inner_text("#studio-sg-stale")
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="retime"]')
    _wait_prop(pg)
    pg.click('#studio-sg-stale [data-act="studio-flow"][data-do="apply"]')
    assert pg.evaluate("studio.project.hand_drops") == []
    # a whole new plan does not rediscover it
    pg.click("#studio-tab-timeline")
    pg.click('[data-act="studio-flow-ask"][data-do="replan"]')
    pg.click('#studio-tl-stale [data-act="studio-flow"][data-do="replan"]')
    _wait_prop(pg)
    assert pg.evaluate("studio.flow.prop.project.hand_drops") == []
