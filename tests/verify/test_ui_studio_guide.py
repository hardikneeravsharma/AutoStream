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
    # the drop may be there and missed: marking it is offered first, another song beside it
    assert pg.locator('#studio-gd-chip [data-fix="mark-drop"]').inner_text() == "Mark the drop yourself"
    assert pg.locator('#studio-gd-chip [data-fix="pick-song"]').inner_text() == "Choose another song"
    assert "none found" in pg.inner_text(".gd-facts")


def test_give_us_a_song_chooses_the_style_that_works_and_says_why_not_the_others(pg):
    """It chose Build and drop for a song with a drop and nothing otherwise, so a song with none
    was a dead end. Each recommended style is now tried on the song and the clips through the
    chip's own verdict: the click track has no drop and the clips no headshot, so not Build and drop
    and not Fast-paced headshot. Montage, Hype and Velocity (recommended since their review) can
    all cut it; the one chosen is one that works without a but, in the recommended order."""
    pg.click(".gd-auto")
    pg.wait_for_selector('.gd-card[data-gd="song"]')
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.gd.step === 0 && studio.song && studio.gd.autoWhy", timeout=60_000)
    why = {w["key"]: w for w in pg.evaluate("() => studio.gd.autoWhy")}
    assert list(why) == ["drop", "fasthead", "montage", "hype", "velocity"], why
    style = pg.evaluate("() => studio.gd.style")
    assert style in ("montage", "hype", "velocity"), style
    best = min(("ok", "warn").index(w["level"]) for k, w in why.items() if w["level"] in ("ok", "warn"))
    assert ("ok", "warn").index(why[style]["level"]) == best, why
    first = next(k for k in why if why[k]["level"] == ("ok", "warn")[best])
    assert style == first, (style, why)
    body = pg.inner_text("#studio-gd-body")
    assert why[style]["label"] + " suits this song" in body
    assert "needs a song with a drop" in body and "headshot" in body.split("Not the others:")[1], body
    assert pg.evaluate("() => studio.gd.quick.length") >= 4          # the clips it was judged with are chosen


def test_when_no_recommended_style_works_it_says_why_and_offers_a_way_on(pg):
    """None works with only two clips: no dead end, each style's reason and what to do instead."""
    ids = pg.evaluate("() => Object.keys(studio.clipIndex).slice(0, 2)")
    pg.evaluate("(ids) => { studio.gd.quick = ids; }", ids)
    # Hype and Velocity run on the general planner, which cuts two clips into a short reel that
    # works -- so here they are answered as refused, to reach the page that says none works.
    pg.evaluate("""() => { const real = API.post;
        API.post = function (u, b) {
            if (u === '/api/studio/feasible' && b && (b.style === 'hype' || b.style === 'velocity'))
                return Promise.resolve({ok: true, verdict: {level: 'bad', text: 'Two clips are too few for this style.'}});
            return real.apply(this, arguments); }; }""")
    pg.evaluate("() => { studio.gd.auto = true; studio.gd.step = 1; studio_gdDraw(); }")
    pg.click('.gd-card[data-gd="song"]')
    pg.wait_for_function("() => studio.gd.step === 0 && studio.gd.autoWhy", timeout=60_000)
    why = pg.evaluate("() => studio.gd.autoWhy")
    # Montage plans two clips the general way: a reel, but not a montage, so not chosen either
    assert [w["key"] for w in why] == ["drop", "fasthead", "montage", "hype", "velocity"], why
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


def _rich_clips(home, run_name="2026-10-20_2000_VALORANT", game="VALORANT", n=26, seconds=8.0,
                prefix=None, singles=False, demo=None):
    """Three set-ups (three headshots; the first a CLUTCH), three headshot doubles, then single
    kills, two in three of them headshots. `singles` makes every clip a single kill, and `demo`
    is the run's alignment against Riot's records -- where each match starts in the recording."""
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
        clip = run / "clips" / f"{prefix or run_name[-4:].lower()}{i:02d}.mp4"
        shutil.copy(base, clip)
        start = 100.0 * (i + 1)
        if singles:
            ks, labels = [(4.0, i % 2 == 0)], []
        elif i < 3:
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
    (run / "session.json").write_text(json.dumps({"game": game, "kills": kills, **({"demo": demo} if demo else {})}))


def _match_record(home, mid, map_key, queue):
    """One saved Riot match record, shaped like what valorant_match.summary reads."""
    import json

    d = home / "video" / "matches"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{mid}.json").write_text(json.dumps({
        "matchInfo": {"matchId": mid, "mapId": f"/Game/Maps/{map_key}/{map_key}", "queueID": queue,
                      "isRanked": queue == "competitive", "gameStartMillis": 1_792_000_000_000,
                      "gameLengthMillis": 900_000},
        "players": [], "teams": []}))


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
    # A second Valorant session whose clips came from two matches Riot recorded: the guide's
    # map and game-mode filters. The first clip is from before either match: Unknown.
    _rich_clips(home, "2026-10-18_2100_VALORANT", n=6, prefix="mtch", singles=True,
                demo={"matches": [{"match": "match-asc", "offset": 150.0}, {"match": "match-hvn", "offset": 350.0}]})
    _match_record(home, "match-asc", "Ascent", "competitive")
    _match_record(home, "match-hvn", "Triad", "spikerush")
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


# ---------------------------------------------------------------------------------------------
# THE DROPS ON THE SONG STEP, and a song from a YouTube link without leaving the guide.

def _drop_view(pg, style, song):
    _open(pg)
    _style(pg, style)
    pg.click("#studio-gd-next")
    _song_named(pg, song)
    pg.wait_for_selector("#studio-gd-dropcv")


def test_the_song_step_shows_the_song_its_drops_and_a_player(rp):
    """Asked for: see the drops on the chosen song, inside the guide, and hear into them."""
    _drop_view(rp, "drop", "drop song")
    view = rp.inner_text("#studio-gd-drops")
    assert "found by AutoStream" in view and "main drop" in view.lower() and "AutoStream’s" in view
    assert rp.is_enabled('#studio-gd-drops [data-gd="drop-into"]')
    assert rp.locator("#studio-gd-seek").count() == 1 and rp.locator("#studio-gd-vol").count() == 1
    # its parts are read for the drawing; the click track's loudness is drawn meanwhile either way
    rp.wait_for_function("() => studio.gd.parts && !studio.gd.parts.loading", timeout=60_000)
    # Play into the drop: from a few seconds before it
    main = rp.evaluate("() => studio_gdMainDrop()")
    rp.evaluate("() => { HTMLMediaElement.prototype.play = function () { this.dispatchEvent(new Event('play')); return Promise.resolve(); }; }")
    rp.click('.gd-transport [data-gd="drop-into"]')
    rp.wait_for_function("(t) => Math.abs(studio_gdNow() - t) < 0.3 || Math.abs(studio.gd.head - t) < 0.3", arg=main - 4)
    # a click on the drawing seeks there
    box = rp.locator("#studio-gd-dropcv").bounding_box()
    rp.mouse.click(box["x"] + box["width"] * 0.25, box["y"] + box["height"] * 0.8)
    secs = rp.evaluate("() => studio.songShape.seconds")
    assert abs(rp.evaluate("() => studio.gd.head") - secs * 0.25) < secs * 0.02


def test_a_drop_marked_on_a_song_with_none_is_judged_and_planned(rp):
    """M2 done properly: Build and drop on a song with no drop said "won't work" with only another
    song to offer. A drop marked here is in the guide's spec: the verdict and the plan carry it."""
    _drop_view(rp, "drop", "click song")
    rp.wait_for_function("() => studio.gd.verdict && studio.gd.verdict.level === 'bad'", timeout=60_000)
    assert "drop" in rp.inner_text("#studio-gd-chip")
    rp.click('#studio-gd-chip [data-fix="mark-drop"]')
    assert rp.evaluate("() => studio.gd.step") == 1
    rp.evaluate("() => studio_gdSeek(30)")
    rp.click("#studio-gd-dropadd")
    assert rp.evaluate("() => studio.gd.drops.map(d => d.t)") == [30]
    rp.click("#studio-gd-next")
    rp.click('[data-gd="pickall"]')
    _settled(rp)
    assert rp.evaluate("() => studio.gd.judged.drops") == [30]
    assert rp.evaluate("() => studio.gd.verdict.level") != "bad", rp.evaluate("() => studio.gd.verdict")
    rp.click("#studio-gd-next")
    rp.click("#studio-gd-next")
    rp.wait_for_selector("#studio-gd-name")
    _settled(rp)
    judged = rp.evaluate("() => studio.gd.judged")
    sent = _make(rp)
    assert sent == judged and sent["drops"] == [30]
    assert abs(rp.evaluate("() => studio.project.song_drop") - 30) < 0.05


def test_drops_move_and_go_and_come_back_and_all_settings_takes_them(rp):
    _drop_view(rp, "drop", "drop song")
    found = rp.evaluate("() => studio_gdDropList().map(d => d.t)")
    assert found and rp.evaluate("() => studio.gd.drops") is None
    # remove AutoStream's: no drop at all is an answer too
    rp.click('#studio-gd-droplist [data-gd="drop-del"]')
    assert rp.evaluate("() => studio.gd.drops") == []
    _settled(rp)
    assert rp.evaluate("() => studio.gd.judged.drops") == []
    assert rp.evaluate("() => studio.gd.verdict.level") == "bad"
    # double-click marks one; dragging it moves it
    box = rp.locator("#studio-gd-dropcv").bounding_box()
    secs = rp.evaluate("() => studio.songShape.seconds")
    rp.mouse.dblclick(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.7)
    t0 = rp.evaluate("() => studio.gd.drops[0].t")
    assert abs(t0 - secs * 0.5) < secs * 0.02
    box = rp.locator("#studio-gd-dropcv").bounding_box()
    x0 = box["x"] + box["width"] * t0 / secs
    rp.mouse.move(x0, box["y"] + 30)
    rp.mouse.down()
    rp.mouse.move(x0 + box["width"] * 0.1, box["y"] + 30, steps=5)
    rp.mouse.up()
    t1 = rp.evaluate("() => studio.gd.drops[0].t")
    assert abs(t1 - (t0 + secs * 0.1)) < secs * 0.02, (t0, t1)
    _settled(rp)
    assert rp.evaluate("() => studio.gd.judged.drops") == [t1]
    # All settings hands them over
    rp.click('[data-gd="step"][data-i="2"]')
    rp.click('[data-gd="pickall"]')
    rp.click('[data-gd="all"]')
    rp.wait_for_selector("#studio-make-scrim:not(.hide)")
    assert rp.evaluate("() => studio_planBody(false).drops") == [t1]
    # back in the guide: Back to AutoStream's sends none
    rp.evaluate("() => studio_gdOpen()")
    rp.wait_for_selector("#studio-guide-scrim:not(.hide)")
    rp.click('[data-gd="step"][data-i="1"]')
    rp.click('#studio-gd-drops [data-gd="drop-reset"]')
    assert rp.evaluate("() => studio.gd.drops") is None
    assert "drops" not in rp.evaluate("() => studio_gdBody()")
    # a drop belongs to its song: another song starts from its own
    rp.evaluate("() => studio_gdAddDrop(12)")
    _song_named(rp, "click song")
    assert rp.evaluate("() => studio.gd.drops") is None


def test_a_youtube_link_from_the_guide_chooses_the_song_there(rp, rich_app):
    """Asked for: paste a YouTube link on the guide's Song step. The download is stubbed -- no
    network -- and lands a song file in the songs folder, as the real one does."""
    import shutil

    songs = rich_app["home"] / "video" / "songs"
    got = songs / "Fetched tune [abc123].wav"
    shutil.copy(songs / "drop song.wav", got)
    _open(rp)
    _style(rp, "drop")
    rp.click("#studio-gd-next")
    rp.evaluate("""(path) => { const post = API.post, get = API.get; window.__ytPolls = 0;
        API.post = function (u, b) {
            if (u === '/api/studio/songfetch') return Promise.resolve(b.url.indexOf('bad') >= 0
                ? {ok: false, error: 'That is not a YouTube link.'} : {ok: true, fetch: {state: 'starting'}});
            return post.apply(this, arguments); };
        API.get = function (u) {
            if (u === '/api/studio/songfetch/status') { window.__ytPolls++;
                return Promise.resolve({ok: true, fetch: window.__ytPolls < 2 ? {state: 'downloading', percent: 50, title: 'Fetched tune'}
                    : {state: 'done', path: path, title: 'Fetched tune'}}); }
            return get.apply(this, arguments); }; }""", str(got))
    rp.click('#studio-gd-body [data-act="studio-yt"][data-for="guide"]')
    rp.wait_for_selector("#studio-yt-scrim:not(.hide)")
    rp.fill("#studio-yt-url", "https://youtu.be/bad")
    rp.click("#studio-yt-go")
    rp.wait_for_selector("#studio-yt-error:not(.hide)")
    assert "not a YouTube link" in rp.inner_text("#studio-yt-error")
    rp.fill("#studio-yt-url", "https://youtu.be/abc123")
    rp.click("#studio-yt-go")
    rp.wait_for_function("(p) => studio.song === p && studio.songShape", arg=str(got), timeout=60_000)
    rp.wait_for_selector("#studio-yt-scrim.hide", state="attached")
    assert not rp.evaluate("() => document.getElementById('studio-guide-scrim').classList.contains('hide')")
    assert rp.evaluate("() => studio.gd.step") == 1
    rp.wait_for_selector("#studio-gd-dropcv")
    assert rp.locator('.gd-card[data-gd="song"].is-on').inner_text().startswith("Fetched tune")


# ---------------------------------------------------------------------------------------------
# EVERY CLIP, A PAGE AT A TIME. The Clips step drew only the best 48 of a game's clips, favourites
# first: with more favourites than that the player saw nothing else and had no way to. Each slot is
# now a clip browser -- thumbnail cards, find, filters, sort, 24 a page -- and every part of that
# is a view: it never changes a choice, the verdict or the request.

QUICK = "#studio-gd-quickgrid .gd-clip"


def _many_clips(pg, extra=40, favs=5):
    """the fixture's Valorant clips, plus `extra` single-kill copies of one of them (each a little
    longer than the last), the first `favs` of them all favourites"""
    # Opening the page reads the library twice (the page's own load and the fixture's refresh);
    # one landing after this would put back a clip index without them.
    pg.evaluate("async () => { await studio_load(true); }")
    pg.wait_for_timeout(500)
    pg.evaluate("""([extra, favs]) => {
      const base = Object.values(studio.clipIndex).find(c => (c.kills || []).length === 1 && /^rant/.test(c.name));
      for (let i = 0; i < extra; i++) studio.clipIndex['extra' + i] = Object.assign({}, base,
        {id: 'extra' + i, name: 'extra_clip_' + i, fav: false, duration: 8 + i / 10});
      Object.values(studio.clipIndex).filter(c => c.game === 'VALORANT').forEach((c, i) => { c.fav = i < favs; });
    }""", [extra, favs])


def _to_clips(pg, style="montage", song="click song"):
    _open(pg)
    _style(pg, style)
    pg.click("#studio-gd-next")
    _song_named(pg, song)
    pg.click("#studio-gd-next")
    pg.wait_for_selector("#studio-gd-browse-quick")


def _ids(pg, sel=QUICK):
    return pg.evaluate("(s) => [...document.querySelectorAll(s)].map(e => e.getAttribute('data-id'))", sel)


def _count(pg, slot="quick"):
    return pg.inner_text(f"#studio-gd-count-{slot}")


def _pick_view(pg, k, label, slot="quick"):
    """choose a filter's option by its label, whatever its count"""
    sel = f"#studio-gd-{k}-{slot}"
    value = pg.evaluate("([s, l]) => [...document.querySelector(s).options].find(o => o.text.startsWith(l)).value", [sel, label])
    pg.select_option(sel, value)


def test_every_clip_is_offered_as_a_card_24_a_page(rp):
    _many_clips(rp)
    rp.evaluate("() => { studio.clipIndex.extra3.name = 'a_very_long_clip_name_without_any_breaks_' + 'x'.repeat(90); }")
    _to_clips(rp)
    n = rp.evaluate("() => studio_gdClips().length")
    assert n == 72                                       # 26 + 6 of the fixture's, 40 more
    lead = rp.inner_text("#studio-gd-body .gd-q")
    assert f"All {n} of your VALORANT clips are here, 24 a page" in lead and "Pick for me draws on all of them" in lead
    assert rp.locator(QUICK).count() == 24
    assert _count(rp) == f"Showing 1–24 of {n}"
    # favourites first, then the rest
    favs = rp.evaluate(f"() => [...document.querySelectorAll('{QUICK}')].map(e => !!studio.clipIndex[e.dataset.id].fav)")
    assert favs[:5] == [True] * 5 and not any(favs[5:])
    # a card: its frame at the first kill, lazily, and it loads; its tags, length and session
    imgs = rp.evaluate(f"() => [...document.querySelectorAll('{QUICK} img.gd-thumbimg')].map(i => [i.loading, i.src])")
    assert len(imgs) == 24 and all(lazy == "lazy" and "/api/studio/thumb" in src for lazy, src in imgs)
    rp.locator(QUICK).first.scroll_into_view_if_needed()
    rp.wait_for_function(f"() => {{ const i = document.querySelector('{QUICK} img.gd-thumbimg'); return i.complete && i.naturalWidth > 0; }}",
                         timeout=60_000)
    card = rp.locator(QUICK).first
    text, when = card.inner_text(), rp.evaluate("(id) => studio.clipIndex[id].folderLabel", card.get_attribute("data-id"))
    assert "8s" in text and when in text and ("HEADSHOT" in text.upper() or "BODY" in text.upper())
    assert card.locator('[data-gd="clip-play"]').is_visible() and card.locator('[data-gd="clip-edit"]').is_visible()
    # the pager: page numbers, Next and Prev, and what it shows out of how many
    rp.click('#studio-gd-browse-quick .gd-pager [aria-label="Page 2"]')
    assert _count(rp) == f"Showing 25–48 of {n}"
    second = _ids(rp)
    rp.click('#studio-gd-browse-quick .gd-pager [aria-label="Next page"]')
    assert _count(rp) == f"Showing 49–72 of {n}" and rp.locator(QUICK).count() == 24
    assert rp.is_disabled('#studio-gd-browse-quick .gd-pager [aria-label="Next page"]')
    rp.click('#studio-gd-browse-quick .gd-pager [aria-label="Previous page"]')
    assert _ids(rp) == second
    # every clip is on exactly one page
    seen = []
    for p in (1, 2, 3):
        rp.click(f'#studio-gd-browse-quick .gd-pager [aria-label="Page {p}"]')
        seen += _ids(rp)
    assert len(seen) == n and len(set(seen)) == n
    # a long name wraps inside its card
    rp.fill("#studio-gd-find-quick", "a_very_long")
    rp.wait_for_function(f"() => document.querySelectorAll('{QUICK}').length === 1")
    assert rp.evaluate(f"""() => {{ const c = document.querySelector('{QUICK}'), m = c.querySelector('.gd-name');
        return m.getBoundingClientRect().right <= c.getBoundingClientRect().right + 0.5 && c.scrollWidth <= c.clientWidth; }}""")


def test_each_slot_keeps_its_own_page_and_a_choice_never_moves_it(rp):
    """Build and drop's two slots, each a browser of its own."""
    _many_clips(rp)
    rp.evaluate("""() => {
      const base = Object.values(studio.clipIndex).find(c => (c.kills || []).length === 3 && !(c.labels || []).length);
      for (let i = 0; i < 30; i++) studio.clipIndex['build' + i] = Object.assign({}, base, {id: 'build' + i, name: 'build_clip_' + i});
    }""")
    _to_clips(rp, "drop", "drop song")
    assert _count(rp, "setup") == "Showing 1–24 of 33"
    rp.click('#studio-gd-browse-setup .gd-pager [aria-label="Page 2"]')
    assert _count(rp, "setup") == "Showing 25–33 of 33"
    assert _count(rp, "quick").startswith("Showing 1–24 of ")
    rp.click('#studio-gd-browse-quick .gd-pager [aria-label="Page 3"]')
    assert _count(rp, "setup") == "Showing 25–33 of 33"
    # choosing, in either slot, leaves both pages where they were
    pick = _ids(rp, "#studio-gd-setupgrid .gd-clip")[2]
    rp.click(f'#studio-gd-setupgrid [data-gd="setup"][data-id="{pick}"]')
    assert rp.evaluate("() => studio.gd.setup") == pick
    quick = _ids(rp)[1]
    rp.click(f'#studio-gd-quickgrid [data-gd="quick"][data-id="{quick}"]')
    assert rp.evaluate("(id) => studio.gd.quick.includes(id)", quick)
    assert _count(rp, "setup") == "Showing 25–33 of 33"
    assert _count(rp, "quick").startswith("Showing 49–")
    assert rp.locator(f'#studio-gd-quickgrid .gd-clip.is-on[data-id="{quick}"]').count() == 1
    assert rp.locator(f'#studio-gd-setupgrid .gd-clip.is-on[data-id="{pick}"]').count() == 1


def test_find_and_each_filter_narrow_with_counts_and_go_back_to_page_one(rp):
    _many_clips(rp)
    _to_clips(rp)
    n = 72
    # favourites
    assert rp.inner_text('#studio-gd-browse-quick [data-k="fav"][data-v="fav"]') == "Favourites (5)"
    assert rp.inner_text('#studio-gd-browse-quick [data-k="fav"][data-v="other"]') == f"Not favourites ({n - 5})"
    rp.click('#studio-gd-browse-quick .gd-pager [aria-label="Page 2"]')
    rp.click('#studio-gd-browse-quick [data-k="fav"][data-v="fav"]')
    assert _count(rp) == f"Showing 1–5 of 5 that match, of {n}"
    assert rp.evaluate(f"() => [...document.querySelectorAll('{QUICK}')].every(e => studio.clipIndex[e.dataset.id].fav)")
    rp.click('#studio-gd-browse-quick [data-k="fav"][data-v="other"]')
    assert _count(rp) == f"Showing 1–24 of {n - 5} that match, of {n}"
    rp.click('#studio-gd-browse-quick [data-k="fav"][data-v="any"]')
    # the sessions, newest first, each with its count
    runs = rp.evaluate("() => [...document.getElementById('studio-gd-run-quick').options].map(o => o.text)")
    assert runs[0] == "Every session" and len(runs) == 3
    assert sorted(runs[1:]) == sorted(["18 Oct 2026, 21:00 (6)", f"20 Oct 2026, 20:00 ({n - 6})"])
    _pick_view(rp, "run", "18 Oct 2026")
    assert _count(rp) == f"Showing 1–6 of 6 that match, of {n}"
    assert sorted(rp.evaluate(f"() => [...document.querySelectorAll('{QUICK}')].map(e => studio.clipIndex[e.dataset.id].name)")) == \
        [f"mtch{i:02d}" for i in range(6)]
    rp.select_option("#studio-gd-run-quick", "")
    # kind
    multi = rp.evaluate("() => studio_gdClips().filter(c => c.kills.length >= 2).length")
    assert multi == 6
    _pick_view(rp, "kind", "Multi-kill")
    assert _count(rp) == f"Showing 1–6 of 6 that match, of {n}"
    _pick_view(rp, "kind", "Clutch")
    assert rp.locator(QUICK).count() == 1 and "CLUTCH" in rp.locator(QUICK).first.inner_text().upper()
    rp.select_option("#studio-gd-kind-quick", "")
    # the find box: by name or label, the caret kept in the box, and back to page one
    rp.click('#studio-gd-browse-quick .gd-pager [aria-label="Page 3"]')
    rp.click("#studio-gd-find-quick")
    rp.keyboard.type("extra_clip_1")
    assert rp.locator(QUICK).count() == 11                 # extra_clip_1 and extra_clip_10..19
    assert _count(rp).startswith("Showing 1–11 of 11")
    assert rp.evaluate("() => document.activeElement && document.activeElement.id") == "studio-gd-find-quick"
    rp.keyboard.type("x")
    assert "No clip matches" in rp.inner_text("#studio-gd-quickgrid")
    rp.fill("#studio-gd-find-quick", "clutch")
    assert rp.locator(QUICK).count() == 1                  # a label
    rp.fill("#studio-gd-find-quick", "")
    # combined: two filters that leave nothing say so, and Clear the filters puts every clip back
    _pick_view(rp, "kind", "Multi-kill")
    _pick_view(rp, "run", "18 Oct 2026")
    assert "No clip matches" in rp.inner_text("#studio-gd-quickgrid")
    rp.click('#studio-gd-quickgrid [data-gd="view-clear"]')
    assert _count(rp) == f"Showing 1–24 of {n}"
    # the sorts
    rp.select_option("#studio-gd-sort-quick", "kills")
    assert rp.evaluate(f"() => studio.clipIndex[document.querySelector('{QUICK}').dataset.id].kills.length") == 3
    rp.select_option("#studio-gd-sort-quick", "long")
    assert _ids(rp)[0] == "extra39"
    rp.select_option("#studio-gd-sort-quick", "new")
    assert rp.evaluate(f"() => studio.clipIndex[document.querySelector('{QUICK}').dataset.id].name").startswith("mtch")
    # chosen only
    rp.select_option("#studio-gd-sort-quick", "best")
    first = _ids(rp)[:2]
    for i in first:
        rp.click(f'#studio-gd-quickgrid [data-gd="quick"][data-id="{i}"]')
    assert rp.inner_text('#studio-gd-browse-quick [data-k="chosen"]') == "Chosen only (2)"
    rp.click('#studio-gd-browse-quick [data-k="chosen"]')
    assert sorted(_ids(rp)) == sorted(first)


def test_map_and_game_mode_come_from_the_match_records(rp):
    """The seeded session's clips: one before either match (unknown), two from an Ascent
    Competitive, three from a Haven Spike Rush. The rest have no record at all."""
    _to_clips(rp)
    n = rp.evaluate("() => studio_gdClips().length")
    maps = rp.evaluate("() => [...document.getElementById('studio-gd-map-quick').options].map(o => o.text)")
    assert maps == ["Every map", f"Unknown map ({n - 5})", "Haven (3)", "Ascent (2)"]
    modes = rp.evaluate("() => [...document.getElementById('studio-gd-mode-quick').options].map(o => o.text)")
    assert modes == ["Every game mode", f"Unknown mode ({n - 5})", "Spike Rush (3)", "Competitive (2)"]
    _pick_view(rp, "map", "Ascent")
    names = rp.evaluate(f"() => [...document.querySelectorAll('{QUICK}')].map(e => studio.clipIndex[e.dataset.id].name).sort()")
    assert names == ["mtch01", "mtch02"]
    assert all("Ascent · Competitive" in t for t in rp.locator(QUICK).all_inner_texts())
    rp.select_option("#studio-gd-map-quick", "")
    _pick_view(rp, "mode", "Spike Rush")
    names = rp.evaluate(f"() => [...document.querySelectorAll('{QUICK}')].map(e => studio.clipIndex[e.dataset.id].name).sort()")
    assert names == ["mtch03", "mtch04", "mtch05"]
    # combined with the map they are not on: nothing
    _pick_view(rp, "map", "Ascent")
    assert "No clip matches" in rp.inner_text("#studio-gd-quickgrid")
    _pick_view(rp, "map", "Unknown map")
    assert "No clip matches" in rp.inner_text("#studio-gd-quickgrid")
    rp.select_option("#studio-gd-mode-quick", "")
    _pick_view(rp, "mode", "Unknown mode")
    assert "mtch00" in rp.evaluate(f"() => [...document.querySelectorAll('{QUICK}')].map(e => studio.clipIndex[e.dataset.id].name)")


def test_choices_survive_paging_and_filtering_and_no_view_asks_the_verdict_again(rp):
    _many_clips(rp)
    _to_clips(rp)
    a = _ids(rp)[3]
    rp.click(f'#studio-gd-quickgrid [data-gd="quick"][data-id="{a}"]')
    rp.click('#studio-gd-browse-quick .gd-pager [aria-label="Page 2"]')
    b = _ids(rp)[5]
    rp.click(f'#studio-gd-quickgrid [data-gd="quick"][data-id="{b}"]')
    assert _count(rp).startswith("Showing 25–48")          # choosing did not move the page
    _settled(rp)
    asked, body = rp.evaluate("() => [window.__feas.length, JSON.stringify(studio_gdBody())]")
    head = "#studio-gd-body .gd-slot .gd-slothead .mono"
    assert rp.inner_text(head) == "2 chosen, at least 4"
    # every kind of view, with both chosen clips out of sight in most of them
    rp.click('#studio-gd-browse-quick .gd-pager [aria-label="Page 3"]')
    rp.click('#studio-gd-browse-quick [data-k="fav"][data-v="fav"]')
    assert rp.inner_text(head) == "2 chosen, at least 4"
    assert rp.inner_text('#studio-gd-browse-quick [data-k="chosen"]') == "Chosen only (2)"
    rp.click('#studio-gd-browse-quick [data-k="fav"][data-v="any"]')
    _pick_view(rp, "run", "18 Oct 2026")
    _pick_view(rp, "map", "Haven")
    rp.select_option("#studio-gd-sort-quick", "long")
    rp.fill("#studio-gd-find-quick", "mtch")
    rp.click('#studio-gd-browse-quick [data-k="chosen"]')
    assert set(_ids(rp)) <= {a, b}
    rp.fill("#studio-gd-find-quick", "")
    rp.click('#studio-gd-browse-quick [data-k="chosen"]')
    _pick_view(rp, "kind", "Multi-kill")
    rp.select_option("#studio-gd-kind-quick", "")
    rp.select_option("#studio-gd-run-quick", "")
    rp.select_option("#studio-gd-map-quick", "")
    rp.select_option("#studio-gd-sort-quick", "best")
    rp.wait_for_timeout(700)                               # past the verdict's own debounce
    assert rp.evaluate("() => window.__feas.length") == asked
    assert rp.evaluate("() => JSON.stringify(studio_gdBody())") == body
    assert rp.evaluate("() => !!studio.gd.verdict")
    assert sorted(rp.evaluate("() => studio.gd.quick")) == sorted([a, b])
    assert rp.inner_text(head) == "2 chosen, at least 4"


def test_play_opens_the_clip_over_the_guide_and_chooses_it_there(rp):
    _to_clips(rp, "drop", "drop song")
    rp.evaluate("() => { studio.gd.quick = []; studio.gd.setup = ''; studio_gdDraw(); }")
    card = rp.locator("#studio-gd-setupgrid .gd-clip").first
    cid = card.get_attribute("data-id")
    card.locator('[data-gd="clip-play"]').click()
    rp.wait_for_selector("#studio-preview-scrim:not(.hide)")
    assert "/api/clips/video" in rp.get_attribute("#studio-preview-video", "src")
    kills = rp.evaluate("(id) => studio.clipIndex[id].kills", cid)
    assert rp.locator("#studio-preview-marks .gd-pvmark").count() == len(kills) == 3
    assert rp.locator("#studio-preview-marks .gd-pvmark.is-hs").count() == 3
    # a kill mark seeks there
    rp.locator("#studio-preview-marks .gd-pvmark").nth(1).click()
    assert abs(rp.evaluate("() => document.getElementById('studio-preview-video').currentTime") - kills[1]) < 0.5
    # chosen from inside the player, and the guide behind it says so
    assert rp.inner_text("#studio-preview-pick") == "Use it as the build"
    rp.click("#studio-preview-pick")
    assert rp.evaluate("() => studio.gd.setup") == cid
    assert "take it out" in rp.inner_text("#studio-preview-pick")
    assert rp.locator(f'#studio-gd-setupgrid .gd-clip.is-on[data-id="{cid}"]').count() == 1
    # the quick kills' Play chooses into the quick kills
    rp.keyboard.press("Escape")
    rp.wait_for_selector("#studio-preview-scrim.hide", state="attached")
    assert rp.is_visible("#studio-guide-scrim") and rp.evaluate("() => studio.gd.step") == 2
    rp.click('#studio-gd-browse-quick .gd-pager [aria-label="Page 2"]')
    page = _count(rp)
    q = rp.locator(QUICK).first
    qid = q.get_attribute("data-id")
    q.locator('[data-gd="clip-play"]').click()
    rp.wait_for_selector("#studio-preview-scrim:not(.hide)")
    rp.click("#studio-preview-pick")
    assert rp.evaluate("(id) => studio.gd.quick.includes(id)", qid)
    rp.click('#studio-preview [data-act="studio-preview-close"]')
    assert rp.is_hidden("#studio-preview-scrim")
    # the guide is where it was: the step, the slot's page, both choices
    assert rp.is_visible("#studio-guide-scrim") and _count(rp) == page
    assert rp.evaluate("() => studio.gd.setup") == cid
    assert rp.locator(f'{QUICK}.is-on[data-id="{qid}"]').count() == 1


def test_edit_opens_trim_and_cut_and_comes_back_with_the_choices(rp, rich_app):
    """Back keeps everything; a finished re-render re-reads the library and the choice follows
    the clip, even to a new path. The re-render itself needs the run's recording, which the
    fixture has not got, so its end is played to the page the way the status poll delivers it."""
    import json
    import shutil

    run = rich_app["home"] / "video" / "clips" / "2026-10-18_2100_VALORANT"
    man = run / "clips.json"
    kept = man.read_text()
    _to_clips(rp)
    target = rp.evaluate("() => Object.values(studio.clipIndex).find(c => c.name === 'mtch03').id")
    other = _ids(rp)[0]
    rp.evaluate("([a, b]) => { studio.gd.quick = [a, b]; studio_gdDraw(); }", [other, target])
    rp.fill("#studio-gd-find-quick", "mtch0")
    rp.locator(f'{QUICK}[data-id="{target}"] [data-gd="clip-edit"]').click()
    # the Clips page, on that clip's player alone, with Trim and cut
    rp.wait_for_selector("#view-clips.is-active.is-visit")
    rp.wait_for_selector("#clip-player-card:not(.hide)")
    assert rp.is_visible("#clip-player-card") and rp.is_visible("#clip-trim-open")
    assert "trim and cut" in rp.inner_text("#clip-player-card").lower()
    assert rp.inner_text("#clip-play-close") == "Back to the guide"
    assert rp.evaluate("() => clip_playerClip().master").endswith("mtch03.mp4")
    assert not rp.is_visible("#clip-local")
    # Back: the guide on its step, its search and its choices
    rp.click("#clip-play-close")
    rp.wait_for_selector("#view-studio.is-active")
    assert rp.is_visible("#studio-guide-scrim") and rp.evaluate("() => studio.gd.step") == 2
    assert rp.input_value("#studio-gd-find-quick") == "mtch0"
    assert rp.evaluate("() => studio.gd.quick") == [other, target]
    assert not rp.evaluate("() => document.getElementById('view-clips').classList.contains('is-visit')")
    # a save: the clip comes back two seconds shorter, under another name
    rp.locator(f'{QUICK}[data-id="{target}"] [data-gd="clip-edit"]').click()
    rp.wait_for_selector("#clip-player-card:not(.hide)")
    new = run / "clips" / "mtch03b.mp4"
    try:
        shutil.copy(run / "clips" / "mtch03.mp4", new)
        data = json.loads(kept)
        row = next(r for r in data["clips"] if r["name"] == "mtch03")
        row.update(name="mtch03b", master=str(new), duration=6.0, end=row["start"] + 6.0)
        man.write_text(json.dumps(data))
        rp.evaluate("(p) => { clip_state.editing = true; clip_renderEdit({state: 'done', result: {master: p, duration: 6}}); }", str(new))
        rp.wait_for_selector("#view-studio.is-active")
        rp.wait_for_function("() => Object.values(studio.clipIndex).some(c => c.name === 'mtch03b')", timeout=30_000)
        now = rp.evaluate("() => Object.values(studio.clipIndex).find(c => c.name === 'mtch03b').id")
        assert now != target
        rp.wait_for_function("([a, b]) => JSON.stringify(studio.gd.quick) === JSON.stringify([a, b])", arg=[other, now], timeout=30_000)
        assert rp.evaluate("() => studio.gd.step") == 2
        card = rp.locator(f'{QUICK}.is-on[data-id="{now}"]')
        assert card.count() == 1 and "6s" in card.inner_text()
        assert "mtch03b" in card.locator("img.gd-thumbimg").get_attribute("src")
    finally:
        man.write_text(kept)
        try:
            new.unlink()
        except OSError:
            pass
