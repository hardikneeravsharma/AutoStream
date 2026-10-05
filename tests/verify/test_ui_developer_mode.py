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
    (home / "video" / "history.jsonl").write_text(json.dumps({
        "session": 1, "game": "Any game (loud moments)",
        "game_key": "any-game",
        "started": 1_790_000_000.0, "ended": 1_790_000_000.0 + SECONDS,
        "recording_path": str(out), "recording_seconds": SECONDS,
        "recording_bytes": out.stat().st_size,
        "title": "a session"}) + "\n", encoding="utf-8")
    return out


def _app(tmp_path_factory, name: str, **ui):
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from autostream.clips.tools import FfmpegMissing, binary
    from fakes import free_port

    try:
        ff = binary("ffmpeg")
    except FfmpegMissing as e:
        pytest.skip(str(e))

    home = tmp_path_factory.mktemp(name)
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True}, ui=ui)
    _recording(home, ff)
    base, proc = appd.start(home, port)
    return {"base": base, "home": home, "token": appd.TOKEN, "proc": proc}


@pytest.fixture(scope="module")
def plain(tmp_path_factory):
    """Developer mode off: what everybody else's install looks like."""
    app = _app(tmp_path_factory, "devoff")
    try:
        yield app
    finally:
        appd.stop(app["base"], app["proc"])


@pytest.fixture(scope="module")
def dev(tmp_path_factory):
    app = _app(tmp_path_factory, "devon", developer_mode=True)
    try:
        yield app
    finally:
        appd.stop(app["base"], app["proc"])


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
    page.locator("#clip-list .clip-row").first.click()
    page.wait_for_function("() => !!clip_state.pick", timeout=20_000)
    page.evaluate("() => clip_goStep('style')")
    page.wait_for_timeout(600)
    page.trouble = trouble
    page.ctx = ctx
    return page


@pytest.fixture
def off(browser, plain):
    page = _page(browser, plain)
    yield page
    page.ctx.close()


@pytest.fixture
def on(browser, dev):
    page = _page(browser, dev)
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
    got = off.evaluate(
        """async () => {
             const body = clip_runBody(clip_state.pick);
             body.diagnostic = true;
             return await API.post('/api/clips/run', body);
           }""")
    assert not (got or {}).get("error"), got
    off.wait_for_function(
        "() => { const j = clip_state.lastJob;"
        "        return j && ['done','failed','cancelled'].indexOf(j.state) >= 0; }",
        timeout=300_000)
    job = off.evaluate("() => clip_state.lastJob")
    assert job["diagnostic_run"] is False, "the flag was honoured with the setting off"
    assert not job["diagnostic"]


def test_and_writes_no_report(off, plain):
    assert not (Path(plain["home"]) / "logs" / "diagnostics").exists()


# ---------------------------------------------------------------- it is on

def test_turning_it_on_puts_the_button_on_the_style_page(on):
    assert on.evaluate("() => clip_state.dev") is True
    assert on.locator("#clip-diag").is_visible()
    assert "diagnostic" in on.locator("#clip-diag").inner_text().lower()


def test_it_is_offered_beside_make_clips_and_not_instead_of_it(on):
    """It runs the same cut. Replacing the ordinary button with it would
    make a diagnostic something you do instead of making clips."""
    assert on.locator("#clip-go").is_visible()
    assert on.locator("#clip-diag").is_visible()


def test_pressing_it_cuts_the_clips_and_writes_one_report(on, dev):
    """THE WHOLE CLAIM, end to end: a real recording, the real pipeline, and
    a report at the other end."""
    # ONE LOUD MOMENT IS ENOUGH HERE. The page defaults to "a moment needs
    # two kills", and the three bursts in this recording are seventeen
    # seconds apart, so nothing in it is a fight of two -- a correct run
    # that cuts nothing, which is not what this test is about.
    on.evaluate("() => { clip_state.min = '1'; clip_renderOptions(); }")
    on.click("#clip-diag")
    on.wait_for_function(
        "() => { const j = clip_state.lastJob;"
        "        return j && ['done','failed','cancelled'].indexOf(j.state) >= 0; }",
        timeout=300_000)
    job = on.evaluate("() => clip_state.lastJob")
    assert job["state"] == "done", job.get("error")
    assert job["clips"] >= 1, "the diagnostic run cut nothing"

    folder = Path(dev["home"]) / "logs" / "diagnostics"
    reports = sorted(folder.glob("clip-diagnostic-*.json"))
    assert len(reports) == 1, [p.name for p in reports]
    assert job["diagnostic"] == str(reports[0])


def test_the_report_is_one_file_a_program_and_a_person_can_both_read(dev):
    report = sorted((Path(dev["home"]) / "logs" / "diagnostics").glob("*.json"))[0]
    body = json.loads(report.read_text(encoding="utf-8"))
    assert body["kind"] == "autostream-clip-diagnostic"
    assert list(body)[0] == "summary"
    assert "where the time went" in body["summary"]


def test_it_says_what_every_stage_cost(dev):
    report = sorted((Path(dev["home"]) / "logs" / "diagnostics").glob("*.json"))[0]
    body = json.loads(report.read_text(encoding="utf-8"))
    names = [s["name"] for s in body["stages"]]
    assert any("find the kills" in n for n in names), names
    assert any("cut the clips" in n for n in names), names
    assert all(isinstance(s["seconds"], (int, float)) for s in body["stages"])


def test_it_says_what_every_ffmpeg_call_did(dev):
    report = sorted((Path(dev["home"]) / "logs" / "diagnostics").glob("*.json"))[0]
    body = json.loads(report.read_text(encoding="utf-8"))
    assert body["process_summary"]["total"] > 0
    first = body["processes"][0]
    assert first["exe"].lower().startswith(("ffmpeg", "ffprobe"))
    assert "exit" in first and "seconds" in first


def test_it_says_what_the_machine_is(dev):
    report = sorted((Path(dev["home"]) / "logs" / "diagnostics").glob("*.json"))[0]
    body = json.loads(report.read_text(encoding="utf-8"))
    assert body["system"]["os"]
    assert "nvenc" in body["system"]["gpu"]
    assert body["facts"]["encoder_used"]


def test_the_report_carries_no_config_and_no_token(dev):
    """Nothing here reads the config, the token store or the environment.
    The web token is the one secret a seeded test home definitely has, so
    it is the one to look for."""
    report = sorted((Path(dev["home"]) / "logs" / "diagnostics").glob("*.json"))[0]
    text = report.read_text(encoding="utf-8")
    assert appd.TOKEN not in text
    assert "web_token" not in text


def test_the_page_offers_to_open_it(on):
    """On a PAGE OPENED AFTERWARDS, which is the case that matters: a run
    that takes forty minutes is one nobody sits in front of, and a path
    announced only in a toast is a path nobody can find again."""
    on.wait_for_function(
        "() => clip_state.lastJob && clip_state.lastJob.diagnostic_run",
        timeout=30_000)
    # The results live on the Clips stage of the rail, which a page opened
    # after the run is not on -- the hop only happens for a run the page
    # watched finish.
    on.evaluate("() => clip_goStep('done')")
    on.wait_for_timeout(400)
    panel = on.locator("#clip-diagdone")
    assert panel.is_visible()
    assert ".json" in panel.inner_text()
    assert on.locator('#clip-diagdone [data-act="reveal-diag"]').is_enabled()


def test_nothing_threw_along_the_way(on):
    assert on.trouble == []
