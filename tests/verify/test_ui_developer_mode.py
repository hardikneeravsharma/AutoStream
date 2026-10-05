r"""Tier 7: Developer Mode, and the diagnostic it adds to the style page.

END TO END, IN A REAL BROWSER, AGAINST A REAL RECORDING. Everything below the
button is covered by unit tests -- what the recorder keeps, what it redacts,
that it writes even on a failure. What those cannot answer is whether pressing
the thing produces a report, which is the only question a user has.

TWO GATES, AND THEY ARE DIFFERENT PROMISES. The page hiding the button is a
courtesy. The run route refusing the flag is the one that means something, and
it is checked here by asking the server directly with developer mode off --
which is what anybody who read the page source would do.
"""
from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path

import appd
import pytest

pytestmark = pytest.mark.ui

SECONDS = 60


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


def _recording(home: Path, ff: str) -> Path:
    """Quiet noise with three loud bursts, so the audio reader -- the one
    game profile that needs no calibration -- has something real to find."""
    out = home / "video" / "session.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    args = [ff, "-y", "-v", "error", "-nostdin",
            "-f", "lavfi", "-i",
            f"testsrc2=size=640x360:rate=15:duration={SECONDS}",
            # SEEDED. anoisesrc takes its seed from the clock otherwise,
            # so every run reads a different recording -- see make_audio
            # in tests/test_loudness.py for the run where that mattered.
            "-f", "lavfi", "-i",
            f"anoisesrc=d={SECONDS}:c=pink:a=0.02:seed=20261006"]
    bursts = (15.0, 32.0, 48.0)
    for at in bursts:
        args += ["-f", "lavfi", "-i",
                 f"sine=f=220:d=1.2,volume=0.5,"
                 f"adelay={int(at * 1000)}|{int(at * 1000)}"]
    mix = "".join(f"[{i}:a]" for i in range(1, 2 + len(bursts)))
    args += ["-filter_complex",
             f"{mix}amix=inputs={1 + len(bursts)}:duration=first:normalize=0[a]",
             "-map", "0:v", "-map", "[a]", "-shortest",
             "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
             "-c:a", "aac", str(out)]
    subprocess.run(args, check=True, capture_output=True, timeout=900,
                   creationflags=appd.NO_WINDOW)
    # TWO SESSIONS OF THE SAME FILE. The first is read by the audio
    # detector, which needs no calibration and is what the diagnostic run
    # cuts. The second claims to be Counter-Strike, which is the only game
    # with a choice of readers -- and that choice is what the slow-read
    # tests below are about. Both point at one recording so the fixture
    # still pays for a single encode.
    rows = [
        {"session": 1, "game": "Any game (loud moments)",
         "game_key": "any-game",
         "started": 1_790_000_000.0, "ended": 1_790_000_000.0 + SECONDS,
         "recording_path": str(out), "recording_seconds": SECONDS,
         "recording_bytes": out.stat().st_size, "title": "a session"},
        {"session": 2, "game": "Counter-Strike 2", "game_key": "cs2.exe",
         "started": 1_790_010_000.0, "ended": 1_790_010_000.0 + SECONDS,
         "recording_path": str(out), "recording_seconds": SECONDS,
         "recording_bytes": out.stat().st_size, "title": "a cs2 session"},
    ]
    (home / "video" / "history.jsonl").write_text(
        "".join(json.dumps(r) + chr(10) for r in rows), encoding="utf-8")
    return out


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """ONE app, and the setting is flipped on it.

    IT USED TO BE TWO, one seeded with developer mode on and one with it
    off -- and that silently cost ten of this module's fourteen tests.
    appd.why_not() refuses to start a second AutoStream while one is
    running, correctly, because the running one may be live or cutting
    clips; so the second fixture skipped and the skip read as a pass in
    the tier summary. The tests never ran against the built binary at all.

    Flipping the setting through the app's own save route is better than
    two homes anyway: it is what a person does, and it proves the toggle
    takes effect without a restart -- which the field claims by not being
    marked `restart`.
    """
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from autostream.clips.tools import FfmpegMissing, binary
    from fakes import free_port

    try:
        ff = binary("ffmpeg")
    except FfmpegMissing as e:
        pytest.skip(str(e))

    home = tmp_path_factory.mktemp("devmode")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    _recording(home, ff)
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


def _set_developer(app, on: bool) -> None:
    """Through the app's own Save, so this is the path a person takes."""
    req = urllib.request.Request(
        f"{app['base']}/api/settings/save?k={app['token']}",
        data=json.dumps({"values": {"ui.developer_mode": bool(on)}}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        got = json.load(r)
    assert got.get("ok"), got


def _page(browser, app):
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("console",
            lambda m: trouble.append(m.text)
            if m.type == "error" and "Failed to load resource" not in m.text
            else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('clips')")
    page.wait_for_selector("#view-clips.is-active", state="attached")
    page.evaluate("clip_load()")
    page.wait_for_function(
        "() => document.querySelectorAll('#clip-list .clip-row').length > 0",
        timeout=30_000)
    # NAMED, NOT "the first one". The list is newest first, and adding a
    # second session for the slow-reader tests below quietly made
    # Counter-Strike the first row -- which has no in-game name on a test
    # machine, so the style page correctly greyed out every button and the
    # diagnostic test spent thirty seconds trying to click a disabled one.
    # These tests want the game the audio reader reads with no setup at all.
    page.locator("#clip-list .clip-row", has_text="Any game").first.click()
    page.wait_for_function(
        "() => (clip_state.pick || {}).game_key === 'any-game'", timeout=20_000)
    page.evaluate("() => clip_goStep('style')")
    page.wait_for_timeout(600)
    page.trouble = trouble
    page.ctx = ctx
    return page


def _job_now(page) -> str:
    """The folder of whatever job the page is showing, or ""."""
    return page.evaluate("() => (clip_state.lastJob || {}).folder || ''")


def _wait_for_a_NEW_job(page, before: str, timeout: int = 300_000) -> dict:
    """Wait for a job that is not the one already on the page. -> its snapshot.

    THE APP REMEMBERS THE LAST FINISHED JOB, and the page polls it into
    clip_state.lastJob. So "wait until lastJob is done or failed" is already
    true the instant a second test starts, and it returns the PREVIOUS
    test's result -- which is how a diagnostic run came back with the
    not-a-diagnostic job from the test before it, reporting zero clips and
    no report. Every job gets its own output folder, so the folder changing
    is what says this is a different run.
    """
    page.wait_for_function(
        """(before) => {
             const j = clip_state.lastJob;
             return j && j.folder && j.folder !== before
                    && ['done', 'failed', 'cancelled'].indexOf(j.state) >= 0;
           }""",
        arg=before, timeout=timeout)
    return page.evaluate("() => clip_state.lastJob")


@pytest.fixture
def off(browser, app):
    """Developer mode off: what everybody else's install looks like.

    SET PER TEST, not once for the module. Tests run in a random order
    here, so a mode set by whichever test happened to run first is a mode
    the next test cannot rely on.
    """
    _set_developer(app, False)
    page = _page(browser, app)
    yield page
    page.ctx.close()


@pytest.fixture
def on(browser, app):
    _set_developer(app, True)
    page = _page(browser, app)
    yield page
    page.ctx.close()


# --------------------------------------------------------------- it is off

def test_nobody_sees_the_button_by_default(off):
    """It is a developer's tool on a page every user opens."""
    assert off.evaluate("() => clip_state.dev") is False
    assert not off.locator("#clip-diag").is_visible()


def test_the_rest_of_the_style_page_is_exactly_as_it_was(off):
    assert off.locator("#clip-go").is_visible()
    assert off.locator("#clip-review").is_visible()
    assert off.trouble == []


def test_the_server_refuses_the_flag_even_when_it_is_asked_directly(off):
    """THE GATE THAT MEANS SOMETHING. Hiding a control stops the button; it
    does not stop the request. A run started with the flag while developer
    mode is off must be an ordinary run."""
    before = _job_now(off)
    got = off.evaluate(
        """async () => {
             const body = clip_runBody(clip_state.pick);
             body.diagnostic = true;
             return await API.post('/api/clips/run', body);
           }""")
    assert not (got or {}).get("error"), got
    job = _wait_for_a_NEW_job(off, before)
    assert job["diagnostic_run"] is False, "the flag was honoured with the setting off"
    assert not job["diagnostic"]


def test_and_writes_no_report(off, app):
    assert not (Path(app["home"]) / "logs" / "diagnostics").exists()


# ---------------------------------------------------------------- it is on

@pytest.fixture(scope="module")
def diagnostic(browser, app):
    """One real diagnostic run, pressed in the browser, shared by every test
    that reads its report.

    A FIXTURE AND NOT THE FIRST TEST. These run in a random order, so tests
    that opened the report by finding the newest file in the folder passed
    or failed on whether the test that MAKES it happened to run first --
    seven of them failed the moment the ordering changed. A dependency a
    test has is a fixture it takes.

    Module-scoped because this is a real cut of real footage: pressing the
    button once and asking eight questions of the answer is the whole point
    of the tier being slow.
    """
    _set_developer(app, True)
    page = _page(browser, app)
    try:
        # ONE LOUD MOMENT IS ENOUGH HERE. The page defaults to "a moment
        # needs two kills", and the three bursts in this recording are
        # seventeen seconds apart, so nothing in it is a fight of two -- a
        # correct run that cuts nothing, which is not what this is about.
        page.evaluate("() => { clip_state.min = '1'; clip_renderOptions(); }")
        before = _job_now(page)
        page.click("#clip-diag")
        job = _wait_for_a_NEW_job(page, before)
        folder = Path(app["home"]) / "logs" / "diagnostics"
        reports = sorted(folder.glob("clip-diagnostic-*.json"))
        body = (json.loads(reports[0].read_text(encoding="utf-8"))
                if reports else {})
        yield {"job": job, "reports": reports, "body": body,
               "trouble": page.trouble}
    finally:
        page.ctx.close()


def test_turning_it_on_puts_the_button_on_the_style_page(on):
    assert on.evaluate("() => clip_state.dev") is True
    assert on.locator("#clip-diag").is_visible()
    assert "diagnostic" in on.locator("#clip-diag").inner_text().lower()


def test_it_is_offered_beside_make_clips_and_not_instead_of_it(on):
    """It runs the same cut. Replacing the ordinary button with it would
    make a diagnostic something you do instead of making clips."""
    assert on.locator("#clip-go").is_visible()
    assert on.locator("#clip-diag").is_visible()


def test_pressing_it_cuts_the_clips(diagnostic):
    """THE WHOLE CLAIM, end to end: a real recording, the real pipeline, and
    clips at the other end."""
    job = diagnostic["job"]
    assert job["state"] == "done", job.get("error")
    assert job["clips"] >= 1, "the diagnostic run cut nothing"


def test_and_writes_exactly_one_report(diagnostic):
    reports = diagnostic["reports"]
    assert len(reports) == 1, [p.name for p in reports]
    assert diagnostic["job"]["diagnostic"] == str(reports[0])


def test_the_report_is_one_file_a_program_and_a_person_can_both_read(diagnostic):
    body = diagnostic["body"]
    assert body["kind"] == "autostream-clip-diagnostic"
    assert list(body)[0] == "summary"
    assert "where the time went" in body["summary"]


def test_it_says_what_every_stage_cost(diagnostic):
    body = diagnostic["body"]
    names = [s["name"] for s in body["stages"]]
    assert any("find the kills" in n for n in names), names
    assert any("cut the clips" in n for n in names), names
    assert all(isinstance(s["seconds"], (int, float)) for s in body["stages"])


def test_it_says_what_every_ffmpeg_call_did(diagnostic):
    body = diagnostic["body"]
    assert body["process_summary"]["total"] > 0
    first = body["processes"][0]
    assert first["exe"].lower().startswith(("ffmpeg", "ffprobe"))
    assert "exit" in first and "seconds" in first


def test_it_says_what_the_machine_is(diagnostic):
    body = diagnostic["body"]
    assert body["system"]["os"]
    assert "nvenc" in body["system"]["gpu"]
    assert body["facts"]["encoder_used"]


def test_the_report_carries_no_config_and_no_token(diagnostic):
    """Nothing here reads the config, the token store or the environment.
    The web token is the one secret a seeded test home definitely has, so
    it is the one to look for."""
    text = diagnostic["reports"][0].read_text(encoding="utf-8")
    assert appd.TOKEN not in text
    assert "web_token" not in text


def test_the_page_offers_to_open_it(browser, app, diagnostic):
    """On a PAGE OPENED AFTERWARDS, which is the case that matters: a run
    that takes forty minutes is one nobody sits in front of, and a path
    announced only in a toast is a path nobody can find again."""
    page = _page(browser, app)
    try:
        page.wait_for_function(
            "() => clip_state.lastJob && clip_state.lastJob.diagnostic_run",
            timeout=30_000)
        # The results live on the Clips stage of the rail, which a page
        # opened after the run is not on -- the hop only happens for a run
        # the page watched finish.
        page.evaluate("() => clip_goStep('done')")
        page.wait_for_timeout(400)
        panel = page.locator("#clip-diagdone")
        assert panel.is_visible()
        assert ".json" in panel.inner_text()
        assert page.locator('#clip-diagdone [data-act="reveal-diag"]').is_enabled()
    finally:
        page.ctx.close()


def test_nothing_threw_along_the_way(diagnostic):
    assert diagnostic["trouble"] == []


# ------------------------------- the reader that reads slower than playback
#
# Counter-Strike read off the screen -- the kill feed as text, plus the
# scoreboard beside it for the round labels -- runs at about 1.2x real time,
# so a 45-minute stream is 40 minutes of reading. It is developer-mode only
# until that is fixed. tests/test_slow_reader_is_off.py pins the wiring;
# these are the page a person actually sees.


def _at_counter_strike(page) -> None:
    """Pick the Counter-Strike session, where the choice of readers lives.

    BACK TO THE PICK STAGE FIRST. `_page` has already chosen a stream and
    moved on, and the list it chose from belongs to that stage -- correctly,
    the page hides what you have finished with. Clicking a row without
    returning is thirty seconds of Playwright waiting for an element that is
    in the DOM and will never be visible.
    """
    page.evaluate("() => clip_goStep('pick')")
    page.wait_for_selector("#clip-listwrap", state="visible", timeout=20_000)
    page.locator("#clip-list .clip-row", has_text="Counter-Strike").first.click()
    page.wait_for_function(
        "() => (clip_state.pick || {}).game_key === 'cs2.exe'", timeout=20_000)
    page.evaluate("() => clip_goStep('read')")
    page.wait_for_timeout(400)


def _ways(page) -> list:
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('#clip-ways [data-val]'))"
        "          .map(b => b.getAttribute('data-val'))")


def _ask_for_the_slow_read(page) -> dict:
    return page.evaluate(
        """async () => {
             const body = clip_runBody(clip_state.pick);
             body.demo_fallback = true;
             body.fallback_mode = '';
             return await API.post('/api/clips/run', body);
           }""")


def test_the_slow_reader_is_not_offered(off):
    """TWO WAYS, NOT THREE. A 45-minute stream advertised at 40 minutes of
    reading is a number nobody should say yes to."""
    _at_counter_strike(off)
    ways = _ways(off)
    assert "rounds" not in ways, ways
    assert "demo" in ways and "cards" in ways, ways


def test_the_two_that_remain_still_cover_the_job(off):
    """A replay is exact and instant; the tally gets the kills right. Only
    the round NAMES go without a replay, and the page says so."""
    _at_counter_strike(off)
    said = off.locator("#clip-ways").inner_text().lower()
    assert "replay" in said
    assert "kills only" in said


def test_developer_mode_puts_it_back(on):
    """Switched off is not deleted -- whoever fixes the turnaround has to be
    able to run it."""
    _at_counter_strike(on)
    assert "rounds" in _ways(on), _ways(on)


def test_the_server_refuses_it_even_when_asked_directly(off):
    """Hiding a control stops the button, not the request -- and the request
    is what spends the forty minutes."""
    _at_counter_strike(off)
    got = _ask_for_the_slow_read(off)
    assert (got or {}).get("error"), got
    assert "switched off" in got["error"].lower(), got["error"]


def test_the_refusal_names_the_way_forward(off):
    """A refusal that leaves somebody stuck is a dead end with manners."""
    _at_counter_strike(off)
    got = _ask_for_the_slow_read(off)
    assert "Kills only" in got["error"], got["error"]


def test_the_fast_reader_is_still_accepted(off):
    """The point of switching one off is that the others remain.

    STARTED AND THEN STOPPED, not run to the end. Accepting the request is
    the whole claim here; letting a real Counter-Strike card read finish on
    this fixture is minutes of scanning to learn nothing further, and a test
    that slow inside the release gate is how the gate gets switched off.
    """
    _at_counter_strike(off)
    got = off.evaluate(
        """async () => {
             const body = clip_runBody(clip_state.pick);
             body.demo_fallback = true;
             body.fallback_mode = 'cards';
             const r = await API.post('/api/clips/run', body);
             /* Stopped straight away: see the docstring. Cancelling a job
                that never started is harmless, so this is unconditional. */
             await API.post('/api/clips/cancel', {});
             return r;
           }""")
    assert not (got or {}).get("error"), got
    assert got.get("ok") is True, got
