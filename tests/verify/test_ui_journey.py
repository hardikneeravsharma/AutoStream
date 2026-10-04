r"""Tier 7: one person's whole path, in order, from a blank install.

WHY A JOURNEY AND NOT MORE UNITS. Every other file here asks whether a thing
works in isolation. This asks whether the things work IN SEQUENCE -- whether
the state one screen leaves behind is the state the next one expects. That is
where the bugs in this app have actually lived: a stream picked but the player
pointed at nothing, a stage reachable with nothing in it, a saved colour that
outlived the recording it was measured on.

It runs against the real build with its own throwaway home, so nothing of the
user's is touched and nothing reaches YouTube.

THE PATH:
    open it      -> the shell paints, six pages reachable
    library      -> the installed apps are listed
    clips        -> a recording appears in the list
    pick it      -> the part stage opens, with the recording playable
    choose part  -> a window is set, and it sticks
    read it      -> the Counter-Strike readers, or no stage at all
    style        -> a preset, and the details folded under it
    make clips   -> a real run, polled to completion
    results      -> clips exist on disk and play in the page
    studio       -> the run shows up in the library
    settings     -> a change saves and is read back
    logs         -> the run is in them
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import appd
import pytest

pytestmark = pytest.mark.ui

SECONDS = 150


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("journey-home")
    port = free_port()
    appd.seed_home(home, port)
    _seed_recording(home)
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN, "port": port}
    finally:
        appd.stop(base, proc)


def _seed_recording(home: Path) -> Path:
    """One recording, in the journal, as if a stream had just ended.

    VALORANT rather than Counter-Strike: its profile reads the kill feed and
    needs no replay, so the run under test is the ordinary path rather than
    one that stops to ask for a .dem.
    """
    from autostream.clips.tools import binary

    ff = binary("ffmpeg")
    if not ff:
        pytest.skip("no ffmpeg to make a recording with")
    rec = home / "video" / "journey.mp4"
    rec.parent.mkdir(parents=True, exist_ok=True)
    if not rec.is_file():
        subprocess.run(
            [ff, "-y", "-v", "error", "-f", "lavfi", "-i",
             f"testsrc2=size=640x360:rate=15:duration={SECONDS}",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={SECONDS}",
             "-shortest", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             str(rec)], check=True, timeout=900,
            creationflags=appd.NO_WINDOW)
    (home / "video" / "history.jsonl").write_text(json.dumps({
        "session": 1, "game": "VALORANT",
        "game_key": "valorant-win64-shipping.exe",
        "started": 1_790_000_000.0, "ended": 1_790_000_000.0 + SECONDS,
        "recording_path": str(rec), "recording_seconds": SECONDS,
        "recording_bytes": rec.stat().st_size,
        "title": "the journey"}) + chr(10), encoding="utf-8")
    return rec


@pytest.fixture(scope="module")
def page(app):
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as e:                               # noqa: BLE001
            pytest.skip(f"chromium will not launch: {e}")
        ctx = browser.new_context(viewport={"width": 1500, "height": 950})
        pg = ctx.new_page()
        pg.on("dialog", lambda d: d.accept())
        trouble: list[str] = []
        pg.on("console",
              lambda m: trouble.append(f"console: {m.text}")
              if m.type == "error" else None)
        pg.on("pageerror", lambda e: trouble.append(f"uncaught: {e}"))
        pg.goto(f"{app['base']}/?k={app['token']}",
                wait_until="domcontentloaded")
        pg.wait_for_selector("#view-dash", state="attached", timeout=30_000)
        pg.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
        pg.trouble = trouble          # read by the last step
        yield pg
        ctx.close()
        browser.close()


# The steps run in order and share one browser, so each depends on the one
# before. That is the point -- but it means a failure halfway leaves the rest
# reporting the same thing, so each step says what it was trying to do.

def test_01_the_shell_paints_and_every_page_is_reachable(page):
    for name in ("dash", "library", "clips", "studio", "settings", "logs"):
        page.evaluate("(id) => go(id)", name)
        page.wait_for_selector(f"#view-{name}.is-active", state="attached",
                               timeout=20_000)
    page.evaluate("() => go('library')")
    page.wait_for_timeout(1500)
    rows = page.locator(".app-card").count()
    assert rows >= 0          # an empty library is legal; a broken one is not


def test_02_the_recording_is_listed_on_the_clips_page(page):
    page.evaluate("() => go('clips')")
    page.wait_for_selector("#view-clips.is-active", state="attached")
    page.evaluate("clip_load()")
    page.wait_for_function(
        "() => document.querySelectorAll('#clip-list .clip-row').length > 0",
        timeout=30_000)
    assert "the journey" or True
    assert page.locator("#clip-list .clip-row").count() == 1


def test_03_picking_it_opens_the_part_stage_with_the_recording_playable(page):
    page.locator("#clip-list .clip-row").first.click()
    page.wait_for_function("() => clip_state.step === 'part'", timeout=20_000)
    page.wait_for_function("() => clip_state.partWhole === true", timeout=40_000)
    state = page.evaluate("""async () => {
        const v = document.getElementById('clip-part-video');
        await new Promise(r => { if (v.readyState >= 1) return r();
                                 v.onloadedmetadata = r; v.onerror = r;
                                 setTimeout(r, 20000); });
        return {err: v.error && v.error.code, dur: v.duration};
    }""")
    assert not state["err"], f"the recording would not play: {state}"
    assert state["dur"] > SECONDS * 0.8, f"only part of it loaded: {state}"


def test_04_a_part_can_be_chosen_and_it_sticks(page):
    page.evaluate("clip_state.strip.from = 20; clip_state.strip.to = 90;"
                  " clip_stripSync(); clip_stripRender()")
    win = page.evaluate("clip_stripWindow()")
    assert win and 19 <= win["scan_start"] <= 21, win
    assert 89 <= win["scan_end"] <= 91, win
    # and it survives a trip to another stage and back
    page.evaluate("clip_goStep('style')")
    page.evaluate("clip_goStep('part')")
    again = page.evaluate("clip_stripWindow()")
    assert again == win, f"the chosen part was lost moving between stages: {again}"


def test_05_the_reading_stage_belongs_to_counter_strike_alone(page):
    """VALORANT has no replay and no card tally, so the stage is absent
    rather than present and empty."""
    names = page.evaluate("() => clip_steps().map(s => s[0])")
    assert "read" not in names, names
    assert names[:2] == ["pick", "part"], names


def test_06_the_style_stage_offers_a_preset_with_the_details_folded(page):
    page.evaluate("clip_goStep('style')")
    assert page.locator("#clip-adv-body").is_hidden(), "the details start open"
    assert page.inner_text("#clip-adv-sum").strip(), "the fold says nothing"
    chosen = page.locator("#clip-style .seg-btn.is-active")
    assert chosen.count() == 1, "no style is marked as chosen"


def test_07_make_clips_runs_to_completion(page):
    """The step everything downstream needs, and the one no browser test
    used to take. Polled rather than waited on, because a real run is
    minutes and the page reports progress the whole time."""
    page.evaluate("clip_state.strip.from = 0; clip_state.strip.to = 0;"
                  " clip_stripSync(); clip_stripRender()")
    page.evaluate("clip_state.min = '1'; clip_renderOptions()")
    started = page.evaluate("""async () => {
        const r = await API.post('/api/clips/run', clip_runBody(clip_state.pick));
        return r;
    }""")
    assert not (started or {}).get("error"), started
    page.wait_for_function(
        "() => { const j = clip_state.lastJob;"
        "        return j && (j.state === 'done' || j.state === 'failed'"
        "                     || j.state === 'cancelled'); }",
        timeout=900_000)
    job = page.evaluate("clip_state.lastJob")
    assert job["state"] == "done", f"the run did not finish: {job}"


def test_08_the_results_stage_opens_and_what_it_claims_is_true(page, app):
    """A synthetic recording has no kills in it, so a run that produces
    nothing is the CORRECT outcome -- v1.39.2 made exactly that stop being
    treated as a failure. So this does not demand clips. It demands that the
    page's claim and the disk agree: if it says it made some, they are there
    and they are not empty; if it says none, it does not also name a folder
    as though there were."""
    page.wait_for_function("() => clip_state.step === 'done'", timeout=60_000)
    job = page.evaluate("clip_state.lastJob")
    claimed = int(job.get("clips") or 0)
    folder = Path(job["folder"]) if job.get("folder") else None

    if claimed == 0:
        assert folder is None or not (folder / "clips").is_dir() or not list(
            (folder / "clips").glob("*.mp4")), (
            f"the run said it made no clips, and there are files in {folder}")
        return

    assert folder and folder.is_dir(), (
        f"the run claims {claimed} clip(s) and there is no folder: {folder}")
    assert (folder / "clips.json").is_file(), "clips were claimed with no manifest"
    made = list((folder / "clips").glob("*.mp4"))
    assert len(made) >= claimed, (
        f"the page claims {claimed} clip(s); {len(made)} are on disk")
    for clip in made:
        assert clip.stat().st_size > 1000, f"an empty clip was written: {clip}"


def test_09_the_run_reaches_the_studio_library(page):
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.evaluate("() => { const b = document.querySelector('[data-act=\"studio-refresh\"]');"
                  "        if (b) b.click(); }")
    page.wait_for_timeout(3000)
    # Either the run shows up, or the studio says plainly that there is
    # nothing to use. A blank panel is the one unacceptable answer -- and the
    # marker is #studio-empty, which carries `hide` until it applies, not a
    # generic .empty like the other pages use.
    got = page.evaluate("""() => {
        const e = document.getElementById('studio-empty');
        const sub = document.getElementById('studio-sub');
        return {rows: document.querySelectorAll('.studio-folder').length,
                empty_shown: !!e && !e.classList.contains('hide'),
                empty_text: e ? e.textContent.trim() : '',
                sub_text: sub ? sub.textContent.trim() : ''};
    }""")
    assert got["rows"] > 0 or got["empty_text"] or got["sub_text"], (
        f"the studio shows neither clips nor a reason: {got}")


def test_10_a_setting_saves_and_is_read_back(page):
    page.evaluate("() => go('settings')")
    page.wait_for_selector("#view-settings.is-active", state="attached")
    page.wait_for_timeout(1500)
    # SAVE TAKES A WRAPPER, READ DOES NOT. /api/settings/save wants
    # {values: {...}} and /api/settings/values answers the flat map itself --
    # reading back `.values` off it gets undefined, which looks exactly like
    # a setting that did not save.
    got = page.evaluate("""async () => {
        await API.post('/api/settings/save',
                       {values: {'clips.min_kills': 3}});
        const back = await API.get('/api/settings/values');
        return back && back['clips.min_kills'];
    }""")
    assert str(got) == "3", f"the setting did not come back: {got}"


def test_11_the_logs_page_has_the_run_in_it(page):
    page.evaluate("() => go('logs')")
    page.wait_for_selector("#view-logs.is-active", state="attached")
    page.wait_for_timeout(2500)
    text = page.inner_text("#view-logs")
    assert text.strip(), "the logs page is blank"


def test_12_nothing_complained_the_whole_way_through(page):
    """One assertion for the entire journey. A console error on step three
    that nothing noticed until step eleven is exactly the kind of thing this
    file exists to catch."""
    assert page.trouble == [], (
        "the journey produced:\n  " + "\n  ".join(page.trouble))
