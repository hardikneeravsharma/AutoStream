r"""Tier 7: how long a reel is, and whether the part of the song survives.

dwayIR: twenty-five clips and a long part of the song picked, and the Hype
reel came out 43 s with eleven clips "left out to fit the reel's length".
The project said why, to four decimal places: its song_offset was 6.9458,
and only the Song tab's "Use this part" rounds to four. The part had been
chosen there -- and that path kept its start, threw its end away, and could
only ever take shots away from the reel, never add the clips that were
left out. A new style re-planned without the part too.

So this drives the page, not the planner:

    the Make dialog      How long, Keep every kill and Best order reach the
                         plan request and come back on the project
    a new style          re-plans on the part the reel was cut to
    the Song tab         a longer part is planned again and kept, and the
                         tab reopens on it rather than on the reel's length
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

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

    home = tmp_path_factory.mktemp("length")
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
    page.on("console", lambda m: trouble.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.wait_for_timeout(1000)
    page.trouble = trouble
    yield page
    ctx.close()


def _clips(app, name: str, count: int, seconds: float = 8.0) -> None:
    """A run of `count` real clips, each with its kill in the middle."""
    from autostream.clips.tools import binary

    ff = binary("ffmpeg")
    if not ff:
        pytest.skip("no ffmpeg to make clips with")
    run = Path(app["home"]) / "video" / "clips" / name
    (run / "clips").mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(count):
        clip = run / "clips" / f"len_{i}.mp4"
        subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"testsrc2=size=320x180:rate=30:duration={seconds}",
                        "-f", "lavfi", "-i", f"sine=frequency={300 + 70 * i}:duration={seconds}",
                        "-shortest", "-pix_fmt", "yuv420p", str(clip)], check=True, timeout=180,
                       creationflags=appd.NO_WINDOW)
        rows.append({"rank": i + 1, "start": 10.0 * (i + 1), "end": 10.0 * (i + 1) + seconds,
                     "duration": seconds, "kills": 1, "name": clip.stem, "master": str(clip),
                     "vertical": "", "caption": "", "tags": [], "at": ""})
    (run / "clips.json").write_text(json.dumps({"game": "VALORANT", "clips": rows}))
    (run / "session.json").write_text(json.dumps(
        {"game": "VALORANT", "kills": [{"time": 10.0 * (i + 1) + seconds / 2} for i in range(count)]}))


def _song(app, seconds: float = 60.0) -> Path:
    songs = Path(app["home"]) / "video" / "songs"
    songs.mkdir(parents=True, exist_ok=True)
    return appd.click_track(songs / "length song.wav", seconds=seconds, bpm=120.0)


def _spy(pg, song: Path) -> None:
    """Answer the file dialog with `song`, and keep every plan request."""
    pg.evaluate("""(path) => { window.__plans = []; const real = API.post;
        API.post = function (u, b) {
            if (u === '/api/clips/pick') return Promise.resolve({path: path});
            if (u === '/api/studio/plan') window.__plans.push(JSON.parse(JSON.stringify(b)));
            return real.apply(this, arguments); }; }""", str(song))


def _pick(pg, folder_label: str, picks: int) -> None:
    pg.click('[data-act="studio-refresh"]')
    # The library is a drill-down (U15): open the run this test seeded, then
    # its clips are on screen. Pressing the way in is test_ui_studio_folders'
    # job; this one is about what the plan carries.
    pg.wait_for_function(
        "(n) => studio.lib && (studio.lib.games || []).some("
        "g => g.folders.some(f => f.label.indexOf(n) >= 0))",
        arg=folder_label, timeout=30_000)
    opened = pg.evaluate("""(n) => {
        for (const g of (studio.lib.games || []))
            for (const f of g.folders)
                if (f.label.indexOf(n) >= 0) { studio_openRun(f.folder); return true; }
        return false; }""", folder_label)
    assert opened, f"no run labelled {folder_label!r} in the studio library"
    pg.wait_for_selector("#studio-lib .studio-clip-hit", timeout=30_000)
    if pg.is_visible('[data-act="studio-clear"]'):
        pg.click('[data-act="studio-clear"]')
    tiles = pg.locator("#studio-lib .studio-clip-hit")
    for i in range(picks):
        tiles.nth(i).click()


def _stop_render(pg) -> None:
    """Build renders straight after the plan; this is about the plan."""
    pg.wait_for_function("studio.jobId", timeout=60_000)
    pg.evaluate("API.post('/api/studio/cancel', {})")
    pg.wait_for_function("/^Cancelled|^Ready|fail/i.test(document.getElementById('studio-state').textContent)",
                         timeout=180_000)


def test_how_long_keep_every_kill_and_best_order_reach_the_plan_and_a_new_style_keeps_the_part(pg, app):
    _clips(app, "2026-10-11_1400_VALORANT", 6)
    song = _song(app)
    _pick(pg, "14:00", 6)
    _spy(pg, song)
    # Best order sits with the other arrangements, above the drawers.
    pg.wait_for_selector('#bin-arrange [data-act="studio-arrange"][data-how="hits"]', state="attached")
    assert pg.inner_text('#bin-arrange [data-how="hits"]') == "Best order"
    pg.evaluate("() => studio_arrangePick('hits')")
    assert pg.get_attribute('#bin-arrange [data-how="hits"]', "aria-pressed") == "true"

    pg.evaluate("studio_openMake()")              # All settings: the full page
    pg.wait_for_selector("#studio-make-scrim:not(.hide)")
    # Without a song there is no part to fill, so that choice is not offered.
    assert pg.is_disabled("#studio-fill-part")
    assert "is-active" in pg.get_attribute('[data-act="studio-fill"][data-fill="style"]', "class")
    pg.click('[data-act="studio-song"]')
    pg.wait_for_selector("#studio-mk-part:not(.hide)", timeout=60_000)
    # With one, the part is what runs unless something else is chosen.
    assert not pg.is_disabled("#studio-fill-part")
    assert "is-active" in pg.get_attribute("#studio-fill-part", "class")
    pg.click('[data-act="studio-mk-preset"][data-preset="whole"]')
    for _ in range(8):                                    # ~44 s of a 60 s song
        pg.click('[data-act="studio-mk-nudge"][data-what="end"][data-d="-bar"]')
    pg.click('[data-act="studio-fill"][data-fill="all"]')
    assert "is-active" in pg.get_attribute('[data-act="studio-fill"][data-fill="all"]', "class")
    assert "Every clip you chose goes in" in pg.inner_text("#studio-fill-note")
    pg.click("#studio-fill-part")
    pg.check("#studio-keep-all")
    part = pg.evaluate("[studio.mk.start, studio.mk.end]")
    assert part[1] - part[0] > 30
    pg.click('[data-act="studio-style"][data-style="hype"]')
    pg.fill("#studio-name", "Length check")
    pg.click('[data-act="studio-build"]')
    pg.wait_for_selector("#studio-pane-timeline:not(.hide)", timeout=120_000)
    _stop_render(pg)

    sent = pg.evaluate("window.__plans")[-1]
    assert sent["part_start"] == pytest.approx(part[0]) and sent["part_end"] == pytest.approx(part[1])
    assert sent["shaping"]["fill"] == "part" and sent["shaping"]["keep_all"] is True
    assert sent["shaping"]["arrange"] == "hits"
    proj = pg.evaluate("studio.project")
    d = pg.evaluate("studio.derived")
    assert proj["fill"] == "part" and proj["keep_all"] is True and proj["arrange"] == "hits"
    assert proj["song_offset"] == pytest.approx(part[0], abs=0.01)
    assert proj["part_end"] == pytest.approx(part[1], abs=0.01)
    # Six 8 s clips can hold most of a 44 s part; Hype's own pace -- six kills
    # 1.1 s apart -- would have been a reel of well under half of it.
    assert d["length"] > 0.6 * (part[1] - part[0]), d["length"]
    assert all(x["in"] for x in d["selection"])

    # --- a new style re-plans on the same part, with the same choices
    pg.select_option("#studio-r-style", "story")
    pg.click("#studio-restyle-btn")
    pg.wait_for_function("studio.project.style === 'story'", timeout=60_000)
    sent = pg.evaluate("window.__plans")[-1]
    assert sent["part_start"] == pytest.approx(part[0], abs=0.01), "a new style dropped the part"
    assert sent["part_end"] == pytest.approx(part[1], abs=0.01), "a new style dropped the part"
    assert sent["shaping"]["fill"] == "part" and sent["shaping"]["keep_all"] is True
    proj = pg.evaluate("studio.project")
    assert proj["part_end"] == pytest.approx(part[1], abs=0.01)
    assert proj["keep_all"] is True
    assert pg.trouble == [], pg.trouble


def test_a_longer_part_on_the_song_tab_is_planned_again_and_kept(pg, app):
    _clips(app, "2026-10-11_1500_VALORANT", 6)
    song = _song(app)
    _pick(pg, "15:00", 6)
    _spy(pg, song)
    pg.evaluate("studio_openMake()")              # All settings: the full page
    pg.wait_for_selector("#studio-make-scrim:not(.hide)")
    pg.click('[data-act="studio-song"]')
    pg.wait_for_selector("#studio-mk-part:not(.hide)", timeout=60_000)
    # AutoStream chooses, the style decides how long: a short Hype reel.
    pg.click('[data-act="studio-mk-mode"][data-mode="auto"]')
    assert "is-active" in pg.get_attribute('[data-act="studio-fill"][data-fill="style"]', "class")
    pg.click('[data-act="studio-style"][data-style="hype"]')
    pg.fill("#studio-name", "Song tab check")
    pg.click('[data-act="studio-build"]')
    pg.wait_for_selector("#studio-pane-timeline:not(.hide)", timeout=120_000)
    _stop_render(pg)
    before = pg.evaluate("studio.derived.length")

    # --- the Song tab, opened on the reel's part; made a good deal longer
    pg.click("#studio-tab-song")
    pg.wait_for_selector("#studio-sg-body:not(.hide)", timeout=60_000)
    start, end = pg.evaluate("[studio.sg.start, studio.sg.end]")
    assert end - start == pytest.approx(before, abs=0.6)
    for _ in range(10):
        pg.click('[data-act="studio-sg-nudge"][data-what="end"][data-d="bar"]')
    start, end = pg.evaluate("[studio.sg.start, studio.sg.end]")
    assert end - start > before + 15
    pg.click('[data-act="studio-sg-apply"]')
    pg.wait_for_function("(e) => studio.project.part_end && Math.abs(studio.project.part_end - e) < 0.05",
                         arg=end, timeout=120_000)
    after = pg.evaluate("studio.derived.length")
    assert after > before + 8, (before, after)
    assert any("planned again" in n for n in pg.evaluate("studio.notes")), pg.evaluate("studio.notes")

    # --- and it is the part the tab reopens on, not the reel's length
    pg.click("#studio-tab-timeline")
    pg.click("#studio-tab-song")
    pg.wait_for_selector("#studio-sg-body:not(.hide)")
    assert pg.evaluate("studio.sg.end") == pytest.approx(end, abs=0.05)
    assert pg.trouble == [], pg.trouble
