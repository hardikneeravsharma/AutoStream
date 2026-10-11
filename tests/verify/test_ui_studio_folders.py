r"""Tier 7: the Studio library as a drill-down -- folders, runs, then clips.

WHAT WAS WRONG (U15, asked 2026-10-11). The library was one scroll: a heading
per game and a tile per clip, all of it at once. On the developer's own
machine that is 339 clips in 42 runs across 4 games -- 339 thumbnails and four
buttons each before the player has said what they are looking for.

It now opens on a card per game. A folder opens on its runs, and a run opens on
its clips **grouped by the match each was cut from**: the map, the mode, the
score and the player's K/D/A, none of it detected -- the match spans are in the
run's own session.json and the rest is in the Riot record the Clips page
already fetched.

WHY THIS FILE EXISTS. `clip_show` is a class toggle and the offline suite
cannot see a page: a drill-down whose second level renders nothing, or whose
Select match ticks the wrong clips, passes every unit test there is. Each test
here presses the thing a player presses.
"""
from __future__ import annotations

import json

import appd
import pytest

pytestmark = pytest.mark.ui

ME = "me-puuid"


def _clip(folder, i, start, end, kills=1):
    master = folder / "clips" / f"VAL_{i:02d}.mp4"
    master.write_bytes(b"x")
    return {"rank": i + 1, "name": master.stem, "master": str(master),
            "start": start, "end": end, "duration": end - start, "kills": kills}


def _run(root, name, game, clips, demo=None):
    folder = root / name
    (folder / "clips").mkdir(parents=True, exist_ok=True)
    rows = [_clip(folder, i, *c) for i, c in enumerate(clips)]
    (folder / "clips.json").write_text(
        json.dumps({"game": game, "clips": rows}), encoding="utf-8")
    sess = {"game": game, "kills": [], "options": {"pre_roll": 3.5}}
    if demo:
        sess["demo"] = demo
    (folder / "session.json").write_text(json.dumps(sess), encoding="utf-8")
    return folder


def _record(cache, mid, map_key, queue, mine, theirs, kda=(0, 0, 0)):
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"{mid}.json").write_text(json.dumps({
        "matchInfo": {"matchId": mid, "mapId": f"/Game/Maps/{map_key}/{map_key}",
                      "queueID": queue, "isRanked": queue == "competitive",
                      "gameStartMillis": 1_788_030_000_000,
                      "gameLengthMillis": 1_200_000},
        "players": [{"subject": ME, "teamId": "Blue",
                     "stats": {"kills": kda[0], "deaths": kda[1], "assists": kda[2]}}],
        "teams": [{"teamId": "Blue", "roundsWon": mine, "numPoints": mine,
                   "won": mine > theirs},
                  {"teamId": "Red", "roundsWon": theirs, "numPoints": theirs,
                   "won": theirs > mine}],
        "_autostream_puuid": ME,
    }), encoding="utf-8")


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

    home = tmp_path_factory.mktemp("folders")
    clips = home / "video" / "clips"
    # A VALORANT sitting with two matches in it, one of them ranked and lost.
    _run(clips, "2026-10-10_2215_VALORANT", "VALORANT",
         [(50.0, 60.0, 1),        # warm-up: inside no match
          (310.0, 322.0, 2), (900.0, 912.0, 3),              # Lotus
          (2700.0, 2706.0, 1), (2800.0, 2812.0, 4)],         # Drift
         demo={"matches": [{"match": "m-drift", "offset": 2632.0},
                           {"match": "m-lotus", "offset": 299.0}]})
    _run(clips, "2026-10-09_2001_VALORANT", "VALORANT",
         [(10.0, 20.0, 1), (40.0, 52.0, 2)])
    _run(clips, "2026-10-08_1800_Counter-Strike-2", "Counter-Strike 2",
         [(10.0, 20.0, 1)])
    _record(home / "video" / "matches", "m-lotus", "Jam", "competitive",
            7, 13, kda=(18, 14, 4))
    _record(home / "video" / "matches", "m-drift", "HURM_Helix", "hurm",
            100, 80, kda=(23, 11, 9))

    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


@pytest.fixture
def pg(browser, app):
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    page = ctx.new_page()
    trouble: list[str] = []
    # The clips here are one byte each, so the thumbnail route is correctly
    # refused. That 400 is the server being right about a stub, not a defect.
    page.on("console",
            lambda m: trouble.append(m.text)
            if m.type == "error" and "studio/thumb" not in m.text
            and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.wait_for_function("() => studio.lib && studio.lib.games.length", timeout=30_000)
    # Whatever the last test left open: every test here starts at the folders.
    page.evaluate("() => { studio.q = ''; studio.selected = []; "
                  "const q = studio_el('studio-q'); if (q) q.value = ''; "
                  "studio_goLib('folders'); }")
    page.wait_for_timeout(300)
    page.trouble = trouble
    page.ctx = ctx
    yield page
    ctx.close()


def _texts(pg, sel):
    return pg.evaluate("(s) => [...document.querySelectorAll(s)].map(e => e.textContent.trim())", sel)


def _count(pg, sel):
    return pg.evaluate("(s) => document.querySelectorAll(s).length", sel)


# ------------------------------------------------------ level 1: folders

def test_the_library_opens_on_folders_not_on_every_clip(pg):
    """THE REPORTED ASK: "show only folders". Three runs' worth of clips were
    on screen at once; now the page opens on one card per game."""
    assert _count(pg, "#studio-lib .studio-folder-card") >= 3      # 2 games + Favourites
    assert _count(pg, "#studio-lib .studio-clip") == 0, (
        "clip tiles are still rendered before a folder has been opened")
    names = _texts(pg, "#studio-lib .studio-folder-card-name")
    assert "VALORANT" in names and "Counter-Strike 2" in names
    assert "Favourites" in names


def test_a_folder_card_says_how_much_is_in_it(pg):
    facts = pg.evaluate("""() => {
        const c = [...document.querySelectorAll('#studio-lib .studio-folder-card')]
            .filter(e => e.getAttribute('data-game') === 'VALORANT')[0];
        return c ? c.querySelector('.studio-folder-card-facts').textContent : '';
    }""")
    assert "7 clips" in facts and "2 runs" in facts, facts


# --------------------------------------------------------- level 2: runs

def test_opening_a_folder_shows_its_runs_with_their_matches(pg):
    pg.click('#studio-lib .studio-folder-card[data-game="VALORANT"]')
    pg.wait_for_timeout(300)
    assert _count(pg, "#studio-lib .studio-run") == 2
    assert _count(pg, "#studio-lib .studio-clip") == 0, (
        "a folder opened straight onto its clips, skipping the runs")
    chips = _texts(pg, "#studio-lib .studio-mchip")
    # The map names Riot's own record gives, not its internal keys.
    assert any("Lotus" in c for c in chips), chips
    assert any("Drift" in c for c in chips), chips
    assert any("7–13" in c for c in chips), chips


def test_a_run_with_no_match_record_shows_no_chips(pg):
    """CS2, and anything imported. A run says what it knows and no more."""
    pg.click('#studio-lib .studio-folder-card[data-game="Counter-Strike 2"]')
    pg.wait_for_timeout(300)
    assert _count(pg, "#studio-lib .studio-run") == 1
    assert _count(pg, "#studio-lib .studio-mchip") == 0


# -------------------------------------------------------- level 3: clips

def _open_the_two_match_run(pg):
    pg.click('#studio-lib .studio-folder-card[data-game="VALORANT"]')
    pg.wait_for_timeout(250)
    pg.evaluate("""() => {
        const rows = [...document.querySelectorAll('#studio-lib .studio-run-hit')];
        const row = rows.filter(r => r.textContent.indexOf('Lotus') >= 0)[0];
        if (row) row.click();
    }""")
    pg.wait_for_timeout(350)


def test_a_run_opens_on_its_clips_grouped_by_match(pg):
    _open_the_two_match_run(pg)
    heads = _texts(pg, "#studio-lib .studio-match-name")
    assert heads[:2] == ["Match 1 · Lotus", "Match 2 · Drift"], heads
    assert "Outside those matches" in heads[-1], heads
    # Every clip in the run is on screen, and each one under its own match.
    assert _count(pg, "#studio-lib .studio-clip") == 5
    per = pg.evaluate("""() => [...document.querySelectorAll('#studio-lib .studio-match')]
        .map(s => s.querySelectorAll('.studio-clip').length)""")
    assert per == [2, 2, 1], per


def test_the_heading_carries_the_score_and_the_players_own_line(pg):
    _open_the_two_match_run(pg)
    text = pg.evaluate("""() => document.querySelectorAll('#studio-lib .studio-match-h')[0].textContent""")
    assert "Competitive" in text, text
    assert "7 – 13" in text, text
    assert "18 / 14 / 4 K/D/A" in text, text
    # Where it starts in the recording: 299 s in.
    assert "at 5m into the recording" in text, text
    lost = pg.evaluate(
        """() => document.querySelectorAll('#studio-lib .studio-match-score')[0].className""")
    assert "is-loss" in lost, lost


def test_select_match_takes_that_match_and_nothing_else(pg):
    _open_the_two_match_run(pg)
    pg.evaluate("""() => document.querySelector('#studio-lib [data-act="studio-match"]').click()""")
    pg.wait_for_timeout(250)
    assert pg.evaluate("() => studio.selected.length") == 2
    # The two Lotus clips, which are the 2-kill and the 3-kill ones.
    kills = pg.evaluate(
        "() => studio.selected.map(id => studio.clipIndex[id].kill_count).sort()")
    assert kills == [2, 3], kills
    assert "2 clips" in pg.evaluate("() => studio_el('studio-tray-count').textContent")
    # And pressing it again gives them back.
    pg.evaluate("""() => document.querySelector('#studio-lib [data-act="studio-match"]').click()""")
    pg.wait_for_timeout(200)
    assert pg.evaluate("() => studio.selected.length") == 0


def test_select_run_still_takes_the_whole_sitting(pg):
    _open_the_two_match_run(pg)
    pg.evaluate("""() => document.querySelector('#studio-lib [data-act="studio-folder"]').click()""")
    pg.wait_for_timeout(250)
    assert pg.evaluate("() => studio.selected.length") == 5


# ------------------------------------------------- getting back out again

def test_the_crumbs_walk_back_up(pg):
    _open_the_two_match_run(pg)
    pg.click('#studio-lib [data-act="studio-crumb"][data-to="runs"]')
    pg.wait_for_timeout(250)
    assert _count(pg, "#studio-lib .studio-run") == 2
    pg.click('#studio-lib [data-act="studio-crumb"][data-to="folders"]')
    pg.wait_for_timeout(250)
    assert _count(pg, "#studio-lib .studio-folder-card") >= 3


def test_where_you_are_survives_a_rerender(pg):
    """The pane is rebuilt on every selection change and after every reel.
    State kept in the markup would drop the player back at the top."""
    _open_the_two_match_run(pg)
    pg.evaluate("() => studio_renderLib()")
    pg.wait_for_timeout(200)
    assert _count(pg, "#studio-lib .studio-match") == 3
    assert _count(pg, "#studio-lib .studio-clip") == 5


# --------------------------------------------------- the search still sees all

def test_a_search_from_the_folders_reaches_a_clip_two_levels_down(pg):
    """A drill-down that could only search the drawer already open would have
    taken something away."""
    pg.fill("#studio-q", "VAL_04")
    pg.wait_for_timeout(350)
    assert _count(pg, "#studio-lib .studio-clip") == 1
    assert _count(pg, "#studio-lib .studio-folder-card") == 0
    # Clearing it puts the player back where they were, not at the top.
    pg.fill("#studio-q", "")
    pg.wait_for_timeout(300)
    assert _count(pg, "#studio-lib .studio-folder-card") >= 3


def test_a_search_that_matches_nothing_says_so(pg):
    pg.fill("#studio-q", "no-such-clip-anywhere")
    pg.wait_for_timeout(350)
    assert pg.evaluate("() => studio_el('studio-empty').className").find("hide") < 0
    assert "Nothing matches" in pg.evaluate(
        "() => studio_el('studio-empty').textContent")
    pg.fill("#studio-q", "")


def test_nothing_threw_in_any_of_it(pg):
    _open_the_two_match_run(pg)
    pg.click('#studio-lib [data-act="studio-crumb"][data-to="folders"]')
    pg.wait_for_timeout(300)
    assert pg.trouble == []


def test_a_shift_range_follows_what_is_on_screen(pg):
    """Shift-click takes everything between two tiles. The run draws its
    clips under the match each came from, so the manifest's rank order is not
    what the eye sees -- a range read off the wrong order would take clips
    from three groups at once."""
    _open_the_two_match_run(pg)
    order = pg.evaluate("""() => studio_visible()
        .filter(g => g.folder.folder === studio.run)[0].clips.map(c => c.id)""")
    shown = pg.evaluate("""() => [...document.querySelectorAll('#studio-lib .studio-clip')]
        .map(e => e.getAttribute('data-clip'))""")
    assert order == shown, "the range order is not the order on screen"


# ------------------------------------------- where the picked clips are

def _pick_two_runs(pg):
    """Pick clips from two different runs, the way adding to a reel does.

    -> {a, b} as {label, n}: the seeded runs' sizes are the fixture's
    business, so the counts come back rather than being written in here.
    """
    return pg.evaluate("""() => {
        const g = studio.lib.games.filter(x => x.game === 'VALORANT')[0];
        const a = g.folders[0], b = g.folders[1];
        const pa = a.clips.slice(0, 3), pb = b.clips.slice(0, 2);
        studio.selected = pa.map(c => c.id).concat(pb.map(c => c.id));
        studio_goLib('folders');
        return {a: {label: a.label, n: pa.length}, b: {label: b.label, n: pb.length}};
    }""")


def test_a_folder_card_says_how_many_of_its_clips_are_picked(pg):
    """THE REPORTED GAP: the library opens on folder cards, so a selection
    made two levels in -- or handed over by "Add clips" -- was invisible."""
    got = _pick_two_runs(pg)
    pill = pg.evaluate("""() => {
        const c = [...document.querySelectorAll('#studio-lib .studio-folder-card')]
            .filter(e => e.getAttribute('data-game') === 'VALORANT')[0];
        const p = c.querySelector('.studio-picked');
        return p ? p.textContent.trim() : ''; }""")
    assert pill == f"{got['a']['n'] + got['b']['n']} picked", pill
    # ...and nothing at all on a folder with none of them in it.
    other = pg.evaluate("""() => {
        const c = [...document.querySelectorAll('#studio-lib .studio-folder-card')]
            .filter(e => e.getAttribute('data-game') === 'Counter-Strike 2')[0];
        return !!c.querySelector('.studio-picked'); }""")
    assert other is False


def test_every_run_says_its_own_count(pg):
    got = _pick_two_runs(pg)
    pg.click('#studio-lib .studio-folder-card[data-game="VALORANT"]')
    pg.wait_for_timeout(250)
    rows = pg.evaluate("""() => [...document.querySelectorAll('#studio-lib .studio-run')]
        .map(r => ({name: r.querySelector('.studio-run-name').textContent.trim(),
                    pill: (r.querySelector('.studio-picked') || {}).textContent || ''}))""")
    by = {r["name"].replace((r["pill"] or "").strip(), "").strip(): (r["pill"] or "").strip() for r in rows}
    assert by.get(got["a"]["label"]) == f"{got['a']['n']} picked", by
    assert by.get(got["b"]["label"]) == f"{got['b']['n']} picked", by


def test_the_picks_can_be_shown_on_their_own(pg):
    """"Show only these" is a filter, not a highlight, so the tray, a
    shift-range and Select run all agree with what is on screen."""
    got = _pick_two_runs(pg)
    n = got["a"]["n"] + got["b"]["n"]
    pg.evaluate("() => { studio.onlyPicked = true; studio_libShow(); }")
    pg.wait_for_timeout(250)
    assert _count(pg, "#studio-lib .studio-clip") == n
    assert _count(pg, "#studio-lib .studio-folder-card") == 0
    assert pg.evaluate("() => studio_visible().reduce((n, g) => n + g.clips.length, 0)") == n
    pg.evaluate("() => { studio.onlyPicked = false; studio_libShow(); }")
    pg.wait_for_timeout(200)
    assert _count(pg, "#studio-lib .studio-folder-card") >= 3


def test_the_tray_names_the_runs_a_selection_spans(pg):
    got = _pick_two_runs(pg)
    pg.evaluate("() => studio_renderTray()")
    pg.wait_for_timeout(200)
    facts = pg.evaluate("() => studio_el('studio-tray-facts').textContent")
    assert "from 2 runs" in facts, facts
    chips = _texts(pg, "#studio-tray-runs .studio-srcchip")
    assert any(got["a"]["label"] in c for c in chips), chips
    assert any(got["b"]["label"] in c for c in chips), chips


def test_the_adding_band_names_the_reels_runs_and_opens_one(pg):
    """What "Add clips to this reel" could not say before: which runs the
    clips it just ticked for you came from."""
    got = _pick_two_runs(pg)
    pg.evaluate("""() => { studio.adding = {name: 'SajanSHort', path: 'x.mp4'}; studio_libShow(); }""")
    pg.wait_for_selector("#studio-lib .studio-band", timeout=5_000)
    band = pg.evaluate("() => document.querySelector('#studio-lib .studio-band').textContent")
    assert "Adding to SajanSHort" in band, band
    assert f"{got['a']['n'] + got['b']['n']} clips in it" in band, band
    chips = _texts(pg, "#studio-lib .studio-band .studio-srcchip")
    assert any(got["a"]["label"] in c and c.rstrip().endswith(str(got["a"]["n"])) for c in chips), chips
    assert any(got["b"]["label"] in c and c.rstrip().endswith(str(got["b"]["n"])) for c in chips), chips
    # the chip is the way to that run
    pg.evaluate("""(label) => {
        const c = [...document.querySelectorAll('#studio-lib .studio-band .studio-srcchip')]
            .filter(e => e.textContent.indexOf(label) >= 0)[0];
        c.click(); }""", got["a"]["label"])
    pg.wait_for_timeout(300)
    assert _count(pg, "#studio-lib .studio-clip") > 0
    assert got["a"]["label"] in pg.evaluate(
        "() => document.querySelector('#studio-lib .studio-crumb-now').textContent")
    pg.evaluate("() => { studio.adding = null; studio.selected = []; studio_goLib('folders'); }")
