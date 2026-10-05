r"""Tier 7: a recording of a game nobody has calibrated.

UNTIL THE AUDIO READER EXISTED THIS SCREEN WAS A DEAD END. A game with no
profile got "No kill marker is calibrated for this game yet", a Calibrate
button that is half an hour of work against real footage, and nothing else --
which is most games, because four are supported and there are thousands.

There is a reader now that needs no calibration at all, so the end of the road
is a choice. Offered rather than taken: it reads the audio, so it finds loud
moments and not kills, and that is the user's trade to make.
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
    from autostream.clips.tools import FfmpegMissing, binary
    from fakes import free_port

    try:
        ff = binary("ffmpeg")
    except FfmpegMissing as e:
        pytest.skip(str(e))

    home = tmp_path_factory.mktemp("anygame")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})

    # A RECORDING OF A GAME THAT HAS NO PROFILE. Three loud bursts in quiet
    # noise, so the audio reader has something real to find and the test is
    # not asserting against silence.
    out = home / "video" / "unknown.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    seconds = 90
    bursts = []
    for i, at in enumerate((20.0, 50.0, 75.0), start=2):
        bursts.append(["-f", "lavfi", "-i",
                       f"sine=f=220:d=1.2,volume=0.5,"
                       f"adelay={int(at * 1000)}|{int(at * 1000)}"])
    args = [ff, "-y", "-v", "error", "-nostdin",
            "-f", "lavfi", "-i",
            f"testsrc2=size=640x360:rate=15:duration={seconds}",
            "-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=pink:a=0.02"]
    for b in bursts:
        args += b
    mix = "".join(f"[{i}:a]" for i in range(1, 2 + len(bursts)))
    args += ["-filter_complex",
             f"{mix}amix=inputs={1 + len(bursts)}:duration=first:normalize=0[a]",
             "-map", "0:v", "-map", "[a]", "-shortest",
             "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
             "-c:a", "aac", str(out)]
    subprocess.run(args, check=True, capture_output=True, timeout=900,
                   creationflags=appd.NO_WINDOW)

    hist = home / "video" / "history.jsonl"
    hist.write_text(json.dumps({
        "session": 1, "game": "Some Game Nobody Has Calibrated",
        "game_key": "totally-unknown-game.exe",
        "started": 1_790_000_000.0, "ended": 1_790_000_090.0,
        "recording_path": str(out), "recording_seconds": seconds,
        "recording_bytes": out.stat().st_size, "title": "unknown game"}) + "\n",
        encoding="utf-8")

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
    page.on("console",
            lambda m: trouble.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('clips')")
    page.wait_for_selector("#view-clips.is-active", state="attached")
    # Chosen by CLICKING THE ROW, which is what a person does -- there is no
    # `clip_pick(i)` to call, and a test that invented one would be exercising
    # a path the page does not have.
    page.evaluate("clip_load()")
    page.wait_for_function(
        "() => document.querySelectorAll('#clip-list .clip-row').length > 0",
        timeout=30_000)
    page.locator("#clip-list .clip-row").first.click()
    page.wait_for_function("() => !!clip_state.pick", timeout=20_000)
    # The offer lives on the style stage, which is where the run is started
    # from -- and where the message it replaces was.
    page.evaluate("() => clip_goStep('style')")
    page.wait_for_timeout(600)
    page.trouble = trouble
    page.ctx = ctx
    yield page
    ctx.close()


def test_the_page_really_does_consider_this_game_unreadable(pg):
    """The premise. If a profile appeared for it, everything below would be
    describing a situation that is not happening."""
    assert pg.evaluate("() => clip_state.pick.can_scan") is False


def test_the_dead_end_now_offers_a_way_out(pg):
    """It used to be a message and a Calibrate button, and that was all."""
    panel = pg.locator("#clip-anygame")
    assert panel.is_visible()
    said = panel.inner_text()
    assert "audio" in said.lower()
    # It must not promise kills, because it cannot tell one from a death.
    assert "shortlist" in said.lower(), said


def test_taking_it_retargets_the_reader(pg):
    pg.click('#clip-anygame [data-act="anygame"]')
    pg.wait_for_timeout(800)
    assert pg.evaluate("() => clip_state.pick.game_key") == "any-game"
    assert pg.evaluate("() => clip_state.pick.scan_mode") == "loudness"
    assert pg.evaluate("() => clip_state.pick.can_scan") is True


def test_the_offer_goes_away_once_it_has_been_taken(pg):
    pg.click('#clip-anygame [data-act="anygame"]')
    pg.wait_for_timeout(800)
    assert not pg.locator("#clip-anygame").is_visible()


def test_it_does_not_rewrite_what_the_session_was(pg, app):
    """A choice about what to cut now is not a claim that the session was a
    different game. The journal is the record of a stream that happened."""
    pg.click('#clip-anygame [data-act="anygame"]')
    pg.wait_for_timeout(800)
    row = json.loads(
        (Path(app["home"]) / "video" / "history.jsonl").read_text(
            encoding="utf-8").splitlines()[0])
    assert row["game"] == "Some Game Nobody Has Calibrated"
    assert row["game_key"] == "totally-unknown-game.exe"


def test_a_run_finds_the_moments_that_are_in_the_recording(pg):
    """END TO END, on a file with three loud bursts in it. This is the claim
    the whole feature rests on: a game nothing has been taught about, and
    clips out of the other end."""
    pg.click('#clip-anygame [data-act="anygame"]')
    pg.wait_for_timeout(800)
    started = pg.evaluate(
        """async () => await API.post('/api/clips/run',
                                      clip_runBody(clip_state.pick))""")
    assert not (started or {}).get("error"), started
    pg.wait_for_function(
        "() => { const j = clip_state.lastJob;"
        "        return j && ['done','failed','cancelled'].indexOf(j.state) >= 0; }",
        timeout=600_000)
    job = pg.evaluate("() => clip_state.lastJob")
    assert job["state"] == "done", job
    # The recording has three bursts in it; at least two must come back, and
    # clips must actually be on disk -- a summary with no files behind it is
    # the shape a hollow pass would take.
    assert (job.get("summary") or {}).get("kills", 0) >= 2, job["summary"]
    assert job["clips"] >= 1, job
    folder = Path(job["folder"])
    made = list((folder / "clips").glob("*.mp4"))
    assert len(made) >= 1, f"nothing in {folder}"
    for clip in made:
        assert clip.stat().st_size > 1000, f"an empty clip was written: {clip}"


def test_the_minimum_follows_the_reader(pg):
    """THE AUDIO READER HAS ALREADY MERGED anything within a few seconds, so
    the default minimum of 2 asks for two SEPARATE loud moments inside one
    clip -- which is rare. A run that found three moments cut nothing and
    explained why in a line nobody had any reason to go looking for."""
    before = pg.evaluate("() => clip_state.min")
    pg.click('#clip-anygame [data-act="anygame"]')
    pg.wait_for_timeout(800)
    assert before != "1", (
        "the default was already 1, so this proves nothing about the switch")
    assert pg.evaluate("() => clip_state.min") == "1"
    assert pg.evaluate(
        "() => clip_runBody(clip_state.pick).min_kills") == 1
    assert "Leave this at 1" in pg.locator("#clip-min-help").inner_text()


def test_what_it_found_is_not_called_kills(pg):
    """It cannot tell a kill from a death, or your grenade from theirs. The
    first time somebody opens a clip of their own death labelled "kill" they
    stop trusting the rest of the page."""
    pg.click('#clip-anygame [data-act="anygame"]')
    pg.wait_for_timeout(800)
    assert pg.evaluate(
        "() => clip_found(3, clip_state.pick)") == "loud moments"
    assert pg.evaluate(
        "() => clip_found(1, clip_state.pick)") == "loud moment"
    # ...and the word is still "kills" for a reader that really does find them.
    assert pg.evaluate(
        "() => clip_found(3, {scan_mode: 'feedbar'})") == "kills"


def test_nothing_threw(pg):
    pg.click('#clip-anygame [data-act="anygame"]')
    pg.wait_for_timeout(800)
    assert pg.trouble == []
