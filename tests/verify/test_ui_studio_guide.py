r"""Tier 7: the guided maker -- one question a screen, and a chip that says whether it works.

The Make page asks everything at once and lets any style meet any song. The guided
maker asks one thing at a time, marks the reviewed style "Use this for best result", and
after each answer says -- through /api/studio/feasible, a real plan without the slow
footage checks -- whether the choices so far work together, with one fix.

The song here is a click track with no drop, and the clips have one kill each, so the
"won't work" paths are what a browser can reach honestly; the verdicts themselves are
tested offline in test_feasible, and the plan behind them in test_director.
"""
from __future__ import annotations

import appd
import pytest
from test_ui_studio_make_page import _clips, _song

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

    home = tmp_path_factory.mktemp("guide")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


@pytest.fixture
def pg(browser, app):
    _clips(app, "2026-10-11_1400_VALORANT", 6)
    _song(app)
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
    page.wait_for_function("() => studio.lib && Object.keys(studio.clipIndex || {}).length >= 6", timeout=30_000)
    page.wait_for_function("() => studio.catalog", timeout=30_000)
    page.wait_for_function("() => document.getElementById('studio-gd-open') !== null")
    page.click("#studio-gd-open")
    page.wait_for_selector("#studio-guide-scrim:not(.hide)")
    yield page
    assert not trouble, trouble
    ctx.close()


def chip(pg):
    return pg.evaluate("() => { const c = document.getElementById('studio-gd-chip'); "
                       "return {cls: c.className, text: c.innerText}; }")


def test_the_first_question_is_the_style_and_the_reviewed_one_says_so(pg):
    assert "What kind of reel?" in pg.inner_text("#studio-gd-body")
    best = pg.locator('.gd-card[data-key="drop"]')
    assert "use this for best result" in best.inner_text().lower()
    # the second style through the review loop (v1.79.8), in the same grid, not under More styles
    fh = pg.locator('.gd-grid-best .gd-card[data-key="fasthead"]')
    assert "use this for best result" in fh.inner_text().lower()
    # the others are there, folded away, and say they are not reviewed
    assert not pg.evaluate("() => document.querySelector('.gd-more').open")
    assert "not reviewed" in pg.inner_text(".gd-more summary").lower()
    assert pg.locator(".gd-more .gd-card").count() >= 8
    # nothing chosen: no way on, and the chip says why
    assert pg.is_disabled("#studio-gd-next")
    assert "warn" in chip(pg)["cls"] and "Pick a style" in chip(pg)["text"]
    best.click()
    assert pg.is_enabled("#studio-gd-next")
    assert "ok" in chip(pg)["cls"]


def test_a_style_that_needs_a_drop_on_a_song_without_one_is_refused_in_words_with_a_fix(pg):
    pg.click('.gd-card[data-key="drop"]')
    pg.click("#studio-gd-next")
    pg.wait_for_selector('.gd-card[data-gd="song"]')
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song && studio.songShape", timeout=30_000)
    pg.wait_for_function("() => document.getElementById('studio-gd-chip').className.indexOf('bad') >= 0", timeout=30_000)
    c = chip(pg)
    assert "drop" in c["text"].lower(), c
    fix = pg.locator('#studio-gd-chip [data-gd="fix"]')
    assert fix.inner_text() == "Choose another song"
    assert "none found" in pg.inner_text(".gd-facts")


def test_give_us_a_song_chooses_the_style_that_works_and_says_why_not_the_others(pg):
    """It chose Build and drop for a song with a drop and nothing otherwise, so a song with none
    was a dead end. Each recommended style is now tried on the song and the clips through the
    chip's own verdict: the click track has no drop and the clips no headshot, so Montage."""
    pg.click(".gd-auto")
    pg.wait_for_selector('.gd-card[data-gd="song"]')
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.gd.step === 0 && studio.song && studio.gd.autoWhy", timeout=60_000)
    assert pg.evaluate("() => studio.gd.style") == "montage"
    body = pg.inner_text("#studio-gd-body")
    assert "Montage suits this song" in body
    assert "needs a song with a drop" in body and "headshot" in body.split("Not the others:")[1], body
    assert pg.evaluate("() => studio.gd.quick.length") >= 4          # the clips it was judged with are chosen


def test_when_no_recommended_style_works_it_says_why_and_offers_a_way_on(pg):
    """None works with only two clips: no dead end, each style's reason and what to do instead."""
    ids = pg.evaluate("() => Object.keys(studio.clipIndex).slice(0, 2)")
    pg.evaluate("(ids) => { studio.gd.quick = ids; }", ids)
    pg.evaluate("() => { studio.gd.auto = true; studio.gd.step = 1; studio_gdDraw(); }")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.gd.step === 0 && studio.gd.autoWhy", timeout=60_000)
    why = pg.evaluate("() => studio.gd.autoWhy")
    # Montage plans two clips the general way: a reel, but not a montage, so not chosen either
    assert [w["key"] for w in why] == ["drop", "fasthead", "montage"], why
    assert pg.evaluate("() => studio.gd.style") == ""
    body = pg.inner_text("#studio-gd-body")
    assert "None of the recommended styles works" in body
    assert pg.locator('.gd-acts [data-gd="step"][data-i="1"]').inner_text() == "Choose another song"
    pg.click('.gd-acts [data-gd="more"]')
    assert pg.evaluate("() => document.querySelector('.gd-more').open")


def test_pick_for_me_fills_the_clips_and_the_counter_says_how_many(pg):
    pg.click('.gd-card[data-key="story"]') if False else None
    pg.evaluate("() => { const d = document.querySelector('.gd-more'); d.open = true; }")
    pg.click('.gd-card[data-key="story"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song", timeout=30_000)
    pg.click("#studio-gd-next")
    pg.wait_for_selector('[data-gd="pickall"]')
    assert pg.is_disabled("#studio-gd-next")
    pg.click('[data-gd="pickall"]')
    chosen = pg.evaluate("() => studio.gd.quick.length")
    assert chosen >= 4, chosen
    assert pg.is_enabled("#studio-gd-next")
    assert f"{chosen} chosen" in pg.inner_text(".gd-slothead .mono")


def test_all_settings_opens_the_full_page_with_the_choices_in_it(pg):
    pg.evaluate("() => { document.querySelector('.gd-more').open = true; }")
    pg.click('.gd-card[data-key="story"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song", timeout=30_000)
    pg.click("#studio-gd-next")
    pg.click('[data-gd="pickall"]')
    pg.click('[data-gd="all"]')
    pg.wait_for_selector("#studio-make-scrim:not(.hide)")
    assert pg.evaluate("() => studio.style") == "story"
    assert pg.evaluate("() => studio.selected.length") >= 4
    assert pg.evaluate("() => document.getElementById('studio-guide-scrim').classList.contains('hide')")


def test_the_last_choices_are_remembered_as_intent_and_checked_again(pg, browser, app):
    pg.click('.gd-card[data-key="drop"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song", timeout=30_000)
    kept = pg.evaluate("() => JSON.parse(localStorage.getItem('autostream.guide'))")
    assert kept["style"] == "drop" and kept["fmt"] == "vertical" and kept["song"]
    # a clip that no longer exists is not brought back
    pg.evaluate("""() => { const m = JSON.parse(localStorage.getItem('autostream.guide'));
        m.quick = ['gone', ...m.quick]; localStorage.setItem('autostream.guide', JSON.stringify(m)); }""")
    pg.click('[data-gd="close"]')
    pg.evaluate("() => { studio.gd.style = ''; studio.gd.quick = []; }")
    pg.click("#studio-gd-open")
    pg.wait_for_selector("#studio-guide-scrim:not(.hide)")
    assert pg.evaluate("() => studio.gd.style") == "drop"
    assert "gone" not in pg.evaluate("() => studio.gd.quick")


def test_the_full_make_page_carries_the_same_chip(pg):
    """F5: the verdict is not only the guided maker's. Opened with Build and drop on a song
    with no drop, the full page says it will not work, in words, before anything is built."""
    pg.click('.gd-card[data-key="drop"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song", timeout=30_000)
    pg.evaluate("() => { studio_gdPickAll(); if (!studio.gd.quick.length) studio.gd.quick = Object.keys(studio.clipIndex).slice(0, 4); }")
    pg.click('[data-gd="all"]')
    pg.wait_for_selector("#studio-make-scrim:not(.hide)")
    pg.wait_for_function("() => { const c = document.getElementById('studio-mk-chip'); return c && !c.hidden; }", timeout=30_000)
    text = pg.inner_text("#studio-mk-chip")
    assert "drop" in text.lower() and "won" in text.lower(), text


def _to_check(pg, style="story"):
    pg.evaluate("() => { document.querySelector('.gd-more').open = true; }")
    pg.click(f'.gd-card[data-key="{style}"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song", timeout=30_000)
    pg.click("#studio-gd-next")
    pg.click('[data-gd="pickall"]')
    pg.click("#studio-gd-next")
    pg.click("#studio-gd-next")
    pg.wait_for_selector("#studio-gd-name")


def test_make_asks_the_name_and_opens_the_timeline_not_all_settings(pg):
    """Reported: the name was never asked (every reel "Build and drop reel"), and Make opened
    All settings with its button greyed for the minute the plan took."""
    _to_check(pg)
    assert pg.get_attribute("#studio-gd-name", "placeholder") == "Length song story"
    pg.fill("#studio-gd-name", "My first reel")
    pg.evaluate("""() => { window.__plans = []; window.__make = false; const real = API.post;
        new MutationObserver(() => { if (!document.getElementById('studio-make-scrim').classList.contains('hide')) window.__make = true; })
          .observe(document.getElementById('studio-make-scrim'), {attributes: true});
        API.post = function (u, b) {
            if (u === '/api/studio/plan') window.__plans.push(JSON.parse(JSON.stringify(b)));
            if (u === '/api/studio/render') return Promise.resolve({ok: false, error: 'not rendered in this test'});
            return real.apply(this, arguments); }; }""")
    pg.wait_for_function("() => !document.getElementById('studio-gd-next').disabled", timeout=30_000)
    pg.click("#studio-gd-next")
    pg.wait_for_function("() => document.getElementById('studio-tab-timeline').classList.contains('is-active')", timeout=120_000)
    assert pg.evaluate("() => window.__make") is False
    assert pg.evaluate("() => window.__plans[0].name") == "My first reel"
    assert pg.evaluate("() => studio.project.name") == "My first reel"


def test_the_build_clip_chosen_is_sent_and_an_untouched_part_holds_the_drop(pg):
    """Reported: the build clip picked in the guide was not used. And Lalala's default part,
    from where the drums come in, left no room before the first drop for the take."""
    ids = pg.evaluate("() => Object.keys(studio.clipIndex)")
    body = pg.evaluate("""(ids) => { studio.style = 'drop'; studio.selected = ids.slice(0, 4);
        studio.buildClip = studio.clipIndex[ids[1]].path; return studio_planBody(false); }""", ids)
    assert body["shaping"]["build_clip"] == pg.evaluate("(id) => studio.clipIndex[id].path", ids[1])
    gone = pg.evaluate("""(ids) => { studio.selected = [ids[0]]; return studio_planBody(false).shaping.build_clip; }""", ids)
    assert gone is None                       # not among the clips any more: not sent
    pg.click('.gd-card[data-key="drop"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.songShape", timeout=30_000)
    part = pg.evaluate("""() => { studio.songShape.drop = 40; studio.mk.drops = null; studio.mk.touched = false;
        studio_mkDefault(); return [studio.mk.start, studio.mk.end]; }""")
    assert part[0] < 40 - 10 and part[1] > 40 + 10, part
    # drawn by the page and never moved: sent as a length, not an end
    assert pg.evaluate("() => studio_planBody(false).shaping.part_auto") is True
    assert pg.evaluate("() => { studio.mk.touched = true; return studio_planBody(false).shaping.part_auto; }") is None


def test_fast_paced_headshot_offers_and_picks_headshots_only(pg):
    """Pick for me filled Fast-paced headshot's slots with body kills, which its plan then left
    out (clips/fasthead.py is headshots only). Its clips step now offers clips with a headshot,
    counts them against about one a second, and says whether there is a double to end on."""
    ids = pg.evaluate("""() => { const ids = Object.keys(studio.clipIndex);
        ids.forEach((id, i) => { const c = studio.clipIndex[id]; c.hs = (c.kills || []).map(() => i % 2 === 0); });
        return ids.filter((id, i) => i % 2 === 0); }""")
    pg.evaluate("() => { document.querySelector('.gd-more').open = true; }")
    pg.click('.gd-card[data-key="fasthead"]')
    pg.click("#studio-gd-next")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.song", timeout=30_000)
    pg.click("#studio-gd-next")
    pg.wait_for_selector('[data-gd="pickall"]')
    offered = pg.evaluate("() => [...document.querySelectorAll('.gd-clip')].map(b => b.getAttribute('data-id'))")
    assert sorted(offered) == sorted(ids)
    pg.click('[data-gd="pickall"]')
    assert sorted(pg.evaluate("() => studio.gd.quick")) == sorted(ids)
    text = pg.inner_text("#studio-gd-body")
    assert "Headshots only" in text and f"{len(ids)} of " in text and "single kill" in text


def test_the_make_button_opens_the_steps_with_the_clips_picked(pg):
    """F13, the player's call: the steps are the way in. Clips picked on the Clips tab open the
    guided maker with them in it; the full page is All settings, on every step. And the shape
    of a 9:16 reel starts at Near fit, the player's other call."""
    pg.click('[data-gd="close"]')
    ids = pg.evaluate("() => Object.keys(studio.clipIndex).slice(0, 4)")
    pg.evaluate("(ids) => { studio.selected = ids; studio_syncSelection(); }", ids)
    pg.evaluate("() => { studio.gd.style = ''; studio.gd.auto = false; studio.gd.quick = []; studio.gd.setup = ''; }")
    pg.click("#studio-make-btn")
    pg.wait_for_selector("#studio-guide-scrim:not(.hide)")
    assert pg.evaluate("() => document.getElementById('studio-make-scrim').classList.contains('hide')")
    assert sorted(pg.evaluate("() => studio_gdIds()")) == sorted(ids)
    assert pg.inner_text("#studio-gd-open") == "Make a reel"
    assert pg.evaluate("() => studio.gd.fit") in ("near",) or pg.evaluate("() => !!localStorage.getItem('autostream.guide')")
    assert pg.evaluate("() => studio.vfit") == "near"


def test_the_look_step_asks_for_lyrics_and_the_plan_keeps_them(pg):
    """Asked: "why did we not give the lyrics option in the make a reel flow?" The roadmap had
    lyrics on the Look step; it shipped without them. Chosen there, they go with the plan."""
    _to_check(pg)
    pg.click("#studio-gd-back")
    looks = pg.evaluate("() => studio_gdLyricLooks().map(l => l.key)")
    assert looks, "no lyric looks in the catalogue"
    pg.click(f'[data-gd="set"][data-k="lyrics"][data-v="{looks[0]}"]')
    assert pg.evaluate("() => studio.gd.lyrics") == looks[0]
    pg.click("#studio-gd-next")
    assert "lyrics" in pg.inner_text(".gd-facts").lower()
    pg.evaluate("""() => { window.__plans = []; const real = API.post;
        API.post = function (u, b) {
            if (u === '/api/studio/plan') window.__plans.push(JSON.parse(JSON.stringify(b)));
            if (u === '/api/studio/render') return Promise.resolve({ok: false, error: 'not rendered in this test'});
            return real.apply(this, arguments); }; }""")
    pg.wait_for_function("() => !document.getElementById('studio-gd-next').disabled", timeout=30_000)
    pg.click("#studio-gd-next")
    pg.wait_for_function("() => window.__plans.length", timeout=120_000)
    assert pg.evaluate("() => window.__plans[0].keep.lyrics.look") == looks[0]
    pg.wait_for_function("() => studio.project && studio.project.lyrics", timeout=120_000)
    assert pg.evaluate("() => studio.project.lyrics.look") == looks[0]


# ---------------------------------------------------------------------------------------------
# THE GUIDE'S ONE SPEC (rules 1-5 of the guide review). These need what the click track and the
# one-kill clips above cannot give: a song with a drop, clutches and doubles to build with,
# headshots and body kills, and a clip of another game. Their own app and home, so the library
# the tests above count is untouched.

def _drop_song(path, seconds=90.0, bpm=120.0, drop_at=40.0, rate=22050):
    """Quiet ticks, then kick, bass and hats from `drop_at`: one clear drop."""
    import math
    import struct
    import wave

    beat = 60.0 / bpm
    fr = bytearray()
    for i in range(int(seconds * rate)):
        t = i / rate
        since = t % beat
        if t < drop_at:
            v = 0.08 * math.sin(2 * math.pi * 3000 * t) * math.exp(-since * 80) if since < 0.03 else 0.0
        else:
            kick = math.sin(2 * math.pi * (60 + 80 * math.exp(-since * 30)) * since) * math.exp(-since * 8)
            v = 0.9 * kick + 0.5 * math.sin(2 * math.pi * 55 * t) + \
                0.2 * math.sin(2 * math.pi * 5000 * t) * math.exp(-((t + beat / 2) % beat) * 80)
        fr += struct.pack("<h", int(max(-1, min(1, v * 0.9)) * 30000))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(fr))


def _rich_clips(home, run_name="2026-10-20_2000_VALORANT", game="VALORANT", n=26, seconds=8.0):
    """Three set-ups (three headshots; the first a CLUTCH), three headshot doubles, then single
    kills, two in three of them headshots."""
    import json
    import shutil
    import subprocess
    from pathlib import Path

    from autostream.clips.tools import binary

    ff = binary("ffmpeg")
    if not ff:
        pytest.skip("no ffmpeg to make clips with")
    run = Path(home) / "video" / "clips" / run_name
    (run / "clips").mkdir(parents=True, exist_ok=True)
    base = run / "clips" / "_base.mp4"
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-shortest", "-pix_fmt", "yuv420p",
                    str(base)], check=True, timeout=180, creationflags=appd.NO_WINDOW)
    rows, kills = [], []
    for i in range(n):
        clip = run / "clips" / f"{run_name[-4:].lower()}{i:02d}.mp4"
        shutil.copy(base, clip)
        start = 100.0 * (i + 1)
        if i < 3:
            ks, labels = [(2.0, True), (3.5, True), (5.0, True)], (["CLUTCH 1v3"] if i == 0 else [])
        elif i < 6:
            ks, labels = [(3.0, True), (4.0, True)], []
        else:
            ks, labels = [(4.0, i % 3 != 0)], []
        kills += [{"time": start + k, "hs": h} for k, h in ks]
        rows.append({"rank": i + 1, "start": start, "end": start + seconds, "duration": seconds, "kills": len(ks),
                     "name": clip.stem, "master": str(clip), "vertical": "", "caption": "", "tags": labels, "at": ""})
    base.unlink()
    (run / "clips.json").write_text(json.dumps({"game": game, "clips": rows}))
    (run / "session.json").write_text(json.dumps({"game": game, "kills": kills}))


@pytest.fixture(scope="module")
def rich_app(tmp_path_factory):
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("guide_spec")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    _rich_clips(home)
    _rich_clips(home, "2026-10-19_1800_CS2", game="Counter-Strike 2", n=2)
    songs = home / "video" / "songs"
    _drop_song(songs / "drop song.wav")
    appd.click_track(songs / "click song.wav", seconds=60, bpm=120.0)
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


# Every plan and verdict asked for is kept; a render is never started.
SPY = """() => { if (window.__spied) return; window.__spied = true; window.__plans = []; window.__feas = [];
  const post = API.post, get = API.get;
  API.post = function (u, b) {
    if (u === '/api/studio/plan') window.__plans.push(JSON.parse(JSON.stringify(b)));
    if (u === '/api/studio/feasible') window.__feas.push(JSON.parse(JSON.stringify(b)));
    if (u === '/api/studio/render') return Promise.resolve({ok: false, error: 'not rendered in this test'});
    if (u === '/api/studio/plan' && window.__holdPlan)
      return new Promise(res => { window.__release = () => post.apply(this, [u, b]).then(res); });
    return post.apply(this, arguments); };
  API.get = function (u) {
    if (u === '/api/studio/job' && window.__job) return Promise.resolve(window.__job);
    return get.apply(this, arguments); }; }"""


@pytest.fixture
def rp(browser, rich_app):
    ctx = browser.new_context(viewport={"width": 1500, "height": 1000})
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("console", lambda m: trouble.append(m.text)
            if m.type == "error" and "studio/thumb" not in m.text and "clips/video" not in m.text
            and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{rich_app['base']}/?k={rich_app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.click('[data-act="studio-refresh"]')
    page.wait_for_function("() => studio.lib && Object.keys(studio.clipIndex || {}).length >= 28", timeout=60_000)
    page.wait_for_function("() => studio.catalog", timeout=30_000)
    page.evaluate(SPY)
    yield page
    assert not trouble, trouble
    ctx.close()


def _open(pg):
    pg.click("#studio-gd-open")
    pg.wait_for_selector("#studio-guide-scrim:not(.hide)")


def _style(pg, key):
    pg.evaluate("() => { const d = document.querySelector('.gd-more'); if (d) d.open = true; }")
    pg.click(f'.gd-card[data-key="{key}"]')


def _song_named(pg, name):
    pg.click(f'.gd-card[data-gd="song"][data-name*="{name}"]')
    pg.wait_for_function("(n) => studio.song && studio.song.indexOf(n) >= 0 && studio.songShape", arg=name, timeout=60_000)


def _settled(pg):
    """the chip's verdict on what is chosen now"""
    pg.wait_for_function("() => { const gd = studio.gd; return gd.verdict && gd.judged && "
                         "JSON.stringify(gd.judged) === JSON.stringify(studio_gdBody()); }", timeout=60_000)


def _to_check_rich(pg, style, song="drop song"):
    _open(pg)
    _style(pg, style)
    pg.click("#studio-gd-next")
    _song_named(pg, song)
    pg.click("#studio-gd-next")
    pg.click('[data-gd="pickall"]')
    pg.click("#studio-gd-next")
    pg.click("#studio-gd-next")
    pg.wait_for_selector("#studio-gd-name")
    _settled(pg)


def _make(pg):
    pg.wait_for_function("() => !document.getElementById('studio-gd-next').disabled", timeout=60_000)
    n = pg.evaluate("() => window.__plans.length")
    pg.click("#studio-gd-next")
    pg.wait_for_function("(n) => window.__plans.length > n && studio.project && !studio.gd.busy", arg=n, timeout=180_000)
    return pg.evaluate("() => window.__plans.slice(-1)[0]")


@pytest.mark.parametrize("style", ["drop", "fasthead", "montage", "story"])
def test_the_verdict_judges_exactly_the_body_the_plan_sends(rp, style):
    """Rule 2: verdict == plan. A vertical reel was judged on the Make page's 46 s landscape part
    and planned on 30 s; the build clip chosen never reached the verdict."""
    _to_check_rich(rp, style)
    judged = rp.evaluate("() => studio.gd.judged")
    assert rp.evaluate("() => window.__feas.slice(-1)[0]") == judged
    sent = _make(rp)
    assert sent == judged
    assert sent["shaping"]["arrange"] == "build" and sent["format"] == "vertical"
    assert round(sent["part_end"] - sent["part_start"]) == 30                  # the vertical part, not 46 s
    if style == "drop":
        assert sent["shaping"]["build_clip"] == rp.evaluate("() => studio.clipIndex[studio.gd.setup].path")


def test_no_setting_left_on_the_make_page_reaches_a_guided_reel(rp):
    """Rule 1: a fresh spec. Perfect fit, pins, a shuffle, Headshots only, an intro, kill marks,
    drops, an order, How long, the dials and a reel being rebuilt were all live on the Make page
    and reached the guided plan unseen."""
    _to_check_rich(rp, "drop")
    clean = rp.evaluate("() => studio_gdBody()")
    rp.evaluate("""() => {
        studio.arrange = 'fit'; studio.pins = {open: 'x'}; studio.shuffleSeed = 77; studio.order = 'kills';
        studio.fill = 'all'; studio.keepAll = true; studio.shaping = {length: 2, pace: 2, effects: 2, flash: 2};
        studio.picks = {kill: ['k01']}; studio.mkIntro = {path: 'C:/intro.mp4', audio: true};
        studio.mk.hand = [{id: 'h1', t: 41, auto: false}]; studio.mk.edited = true; studio.mk.drops = [{id: 'u1', t: 20, auto: false}];
        studio.mk.touched = true; studio.mk.start = 0; studio.mk.end = 80; studio.fmt = 'landscape'; studio.vfit = 'zoom';
        studio.buildClip = studio.clipIndex[Object.keys(studio.clipIndex)[5]].path;
        const hs = document.getElementById('studio-hs-only'); hs.checked = true;
        document.getElementById('studio-hs-row').classList.remove('hide');
        studio.adding = {name: 'Old reel', output: 'C:/reels/old.mp4', style: 'story', keep: {handle: '@old'}}; }""")
    assert rp.evaluate("() => studio_gdBody()") == clean
    sent = _make(rp)
    assert sent == clean
    assert rp.evaluate("() => studio.output") == ""                            # a new reel, not old.mp4
    # and the Make page now shows the reel that was made: its Build would send the same request
    assert rp.evaluate("() => studio_planBody(false)") == clean
    assert rp.evaluate("() => studio.adding") is None


def test_all_settings_hands_the_same_spec_over_as_a_new_reel(rp):
    """Rule 1 and 4: after "Add clips..." on a reel, the guide's All settings opened as "Rebuild
    <that reel>" with its song and name, and its render would have overwritten it."""
    _to_check_rich(rp, "montage")
    _make(rp)
    rp.evaluate("() => studio_addClips()")
    rp.wait_for_function("() => !!studio.adding")
    _open(rp)
    _style(rp, "drop")
    rp.click('[data-gd="step"][data-i="2"]')
    rp.click('[data-gd="pickall"]')
    _settled(rp)
    spec = rp.evaluate("() => studio_gdBody()")
    rp.click('[data-gd="all"]')
    rp.wait_for_selector("#studio-make-scrim:not(.hide)")
    assert rp.inner_text("#studio-make-title") == "Make a reel"
    assert rp.inner_text("#studio-build-btn") == "Build and render"
    assert rp.evaluate("() => studio.adding") is None
    assert rp.evaluate("() => studio_planBody(false)") == spec


def test_changing_style_recomputes_which_chosen_clips_count(rp):
    """Rule 3: Montage's clips kept under Fast-paced headshot: the body kills are left out of the
    count, the verdict and the plan, and shown with why -- not hidden and counted."""
    _open(rp)
    _style(rp, "montage")
    rp.click("#studio-gd-next")
    _song_named(rp, "drop song")
    rp.click("#studio-gd-next")
    rp.click('[data-gd="pickall"]')
    chosen = rp.evaluate("() => studio.gd.quick.slice()")
    body_ids = set(chosen)
    rp.click('[data-gd="step"][data-i="0"]')
    _style(rp, "fasthead")
    rp.click('[data-gd="step"][data-i="2"]')
    rp.wait_for_selector('[data-gd="pickall"]')
    got = rp.evaluate("""() => { const body = studio_gdBody(), byPath = {};
        Object.values(studio.clipIndex).forEach(c => { byPath[c.path] = c; });
        return {kept: studio.gd.quick.slice(), sent_hs: body.clips.map(p => studio_gdHs(byPath[p]) > 0),
                left: [...document.querySelectorAll('.gd-leftlist li')].map(li => li.innerText),
                counter: document.querySelector('.gd-slothead .mono').innerText,
                ids: studio_gdIds().length}; }""")
    assert set(got["kept"]) == body_ids                                       # the selection is the player's
    assert got["sent_hs"] and all(got["sent_hs"])                             # only headshots reach the plan
    assert got["left"] and all("not a headshot" in x for x in got["left"])
    assert got["counter"].startswith(f"{got['ids']} of ")
    assert len(got["left"]) + got["ids"] == len(chosen)
    rp.click('.gd-leftlist [data-gd="unpick"]')                               # and one can be taken out
    assert rp.evaluate("() => studio.gd.quick.length") == len(chosen) - 1
    rp.click('[data-gd="step"][data-i="0"]')
    _style(rp, "montage")
    assert rp.evaluate("() => studio_gdIds().length") == len(chosen) - 1      # back: they count again


def test_a_clip_of_another_game_or_one_deleted_is_shown_or_dropped_never_hidden(rp):
    """L5, L6: a clip of another game passed from the Clips tab was chosen but drawn nowhere; a
    clip deleted mid-session stayed in the draft."""
    ids = rp.evaluate("""() => { const all = Object.values(studio.clipIndex);
        return [all.find(c => /Counter/.test(c.game)).id].concat(all.filter(c => c.game === 'VALORANT').slice(6, 12).map(c => c.id)); }""")
    rp.evaluate("(ids) => { studio.gd.style = 'montage'; return studio_gdOpenWith(ids); }", ids)
    rp.wait_for_selector("#studio-guide-scrim:not(.hide)")
    rp.click('[data-gd="step"][data-i="1"]')
    _song_named(rp, "drop song")
    rp.click('[data-gd="step"][data-i="2"]')
    left = rp.inner_text(".gd-leftlist")
    assert "another game" in left
    assert ids[0] not in rp.evaluate("() => studio_gdIds()")
    gone = ids[3]
    rp.evaluate("(id) => { delete studio.clipIndex[id]; studio_gdDraw(); }", gone)
    assert gone not in rp.evaluate("() => studio.gd.quick")


def test_add_the_best_keeps_the_build_clip_the_player_chose(rp):
    """L2 and M1: "Add the best" replaced the chosen build clip with the top scorer; and the
    verdict never heard which clip was chosen."""
    _open(rp)
    _style(rp, "drop")
    rp.click("#studio-gd-next")
    _song_named(rp, "drop song")
    rp.click("#studio-gd-next")
    mine = rp.evaluate("() => studio_gdPools().setups[2].id")
    rp.click(f'[data-gd="setup"][data-id="{mine}"]')
    rp.evaluate("() => { const q = studio_gdPools().quick.slice(-3).map(c => c.id); studio.gd.quick = q; studio_gdDraw(); }")
    _settled(rp)
    assert rp.evaluate("() => studio.gd.judged.shaping.build_clip") == rp.evaluate("(id) => studio.clipIndex[id].path", mine)
    fix = rp.evaluate("() => studio.gd.verdict.fix")
    assert fix == "pick-clips", rp.evaluate("() => studio.gd.verdict")
    before = rp.evaluate("() => studio.gd.quick.slice()")
    rp.click('#studio-gd-chip [data-gd="fix"]')
    after = rp.evaluate("() => ({setup: studio.gd.setup, quick: studio.gd.quick.slice()})")
    assert after["setup"] == mine
    assert set(before) <= set(after["quick"]) and len(after["quick"]) > len(before)


def test_a_rebuild_asks_again_for_what_the_player_chose(rp):
    """M6: a rebuild of a Build and drop reel built on the best-scoring set-up, not the one chosen,
    held the page's part to an end, and lost Headshots only, the intro and drops marked by hand."""
    _open(rp)
    _style(rp, "drop")
    rp.click("#studio-gd-next")
    _song_named(rp, "drop song")
    rp.click("#studio-gd-next")
    rp.click('[data-gd="pickall"]')
    mine = rp.evaluate("() => studio_gdPools().setups.map(c => c.id).find(id => id !== studio.gd.setup)")
    rp.click(f'[data-gd="setup"][data-id="{mine}"]')
    rp.click("#studio-gd-next")
    rp.click("#studio-gd-next")
    rp.wait_for_selector("#studio-gd-name")
    _settled(rp)
    _make(rp)
    path = rp.evaluate("(id) => studio.clipIndex[id].path", mine)
    assert rp.evaluate("() => studio.project.build_clip") == path
    assert rp.evaluate("() => studio.project.part_auto") is True
    # the reel as a later session finds it, with a drop the player marked and Headshots only
    rp.evaluate("""() => { studio.buildClip = ''; studio.project.hand_drops = [40.5]; studio.project.hs_only = true;
        studio.project.intro_clip = {path: 'C:/intro.mp4', audio: true}; }""")
    rp.evaluate("() => studio_addClips()")
    rp.wait_for_function("() => !!studio.adding")
    rp.evaluate("() => studio_openMake()")
    rp.wait_for_selector("#studio-make-scrim:not(.hide)")
    rp.wait_for_function("() => studio.songShape && studio.mk.drops", timeout=30_000)
    body = rp.evaluate("() => studio_planBody(true)")
    assert rp.inner_text("#studio-make-title").startswith("Rebuild")
    assert body["shaping"]["build_clip"] == path
    assert body["shaping"]["part_auto"] is True
    assert body["drops"] == [40.5]
    assert rp.evaluate("() => studio.mkIntro") == {"path": "C:/intro.mp4", "audio": True}
    assert rp.evaluate("() => document.getElementById('studio-hs-only').checked") is True


def test_back_or_close_while_it_plans_leaves_a_guide_that_works(rp):
    """M4, L3: Back looked live and did nothing; closing left the guide ignoring every click, and
    when the plan came back the first step's button read "Make the reel"."""
    _to_check_rich(rp, "story", "click song")
    rp.evaluate("() => { window.__holdPlan = true; }")
    rp.click("#studio-gd-next")
    rp.wait_for_function("() => studio.gd.busy && typeof window.__release === 'function'")
    assert rp.is_enabled("#studio-gd-back")
    rp.click("#studio-gd-back")
    st = rp.evaluate("() => ({step: studio.gd.step, busy: studio.gd.busy, next: document.getElementById('studio-gd-next').textContent})")
    assert st == {"step": 3, "busy": False, "next": "Next"}
    rp.evaluate("() => { const r = window.__release; window.__release = null; r(); }")
    rp.wait_for_timeout(1500)
    assert rp.evaluate("() => studio.project") is None                       # its answer was dropped
    rp.click("#studio-gd-next")
    _settled(rp)
    rp.click("#studio-gd-next")
    rp.wait_for_function("() => studio.gd.busy && typeof window.__release === 'function'")
    rp.click('[data-gd="close"]')
    _open(rp)
    _style(rp, "montage")                                                      # a click is answered
    assert rp.evaluate("() => studio.gd.style") == "montage"
    rp.evaluate("() => { window.__holdPlan = false; window.__release(); }")
    rp.wait_for_timeout(1500)
    st = rp.evaluate("() => ({step: studio.gd.step, next: document.getElementById('studio-gd-next').textContent, project: !!studio.project})")
    assert st == {"step": 0, "next": "Next", "project": False}


def test_a_render_in_progress_is_not_planned_over(rp):
    """M7: Make planned for a minute, replaced the timeline, then the server refused to render."""
    _to_check_rich(rp, "story", "click song")
    rp.evaluate("() => { window.__job = {ok: true, state: 'running', id: 9, percent: 42, auto: false, message: 'Rendering'}; }")
    n = rp.evaluate("() => window.__plans.length")
    rp.click("#studio-gd-next")
    rp.wait_for_function("() => !studio.gd.busy && studio.gd.held")
    assert rp.evaluate("() => window.__plans.length") == n
    assert "rendering now (42%)" in rp.inner_text("#studio-gd-chip")
    assert rp.evaluate("() => studio.project") is None
    assert rp.evaluate("() => studio.watching") == 9                           # its progress is still followed
    rp.evaluate("() => { window.__job = null; }")


def test_the_next_reel_gets_its_own_name_and_typing_it_is_not_interrupted(rp):
    """L1 and L7: the next reel opened with the last one's name; and the verdict landing redrew
    the step, taking the name field out from under the typing."""
    _to_check_rich(rp, "story", "click song")
    rp.focus("#studio-gd-name")
    rp.keyboard.type("First")
    rp.evaluate("() => { studio.gd.verdict = null; studio_gdAsk(); }")
    _settled(rp)
    assert rp.evaluate("() => document.activeElement && document.activeElement.id") == "studio-gd-name"
    rp.keyboard.type(" reel")
    assert _make(rp)["name"] == "First reel"
    rp.evaluate("() => studio_tab('clips')")
    _open(rp)
    rp.click('[data-gd="step"][data-i="4"]')
    rp.wait_for_selector("#studio-gd-name")
    assert rp.input_value("#studio-gd-name") == ""
    assert rp.evaluate("() => studio_gdBody().name") != "First reel"


def test_lyrics_are_offered_as_used_if_found_and_montage_says_its_minimum(rp):
    _open(rp)
    _style(rp, "montage")
    rp.click("#studio-gd-next")
    _song_named(rp, "click song")
    rp.click("#studio-gd-next")
    assert "at least four clips" in rp.inner_text("#studio-gd-body")
    rp.click('[data-gd="pickall"]')
    rp.click("#studio-gd-next")
    if rp.locator('[data-gd="set"][data-k="lyrics"]').count():
        assert "if this song’s lyrics are found" in rp.inner_text("#studio-gd-body")
