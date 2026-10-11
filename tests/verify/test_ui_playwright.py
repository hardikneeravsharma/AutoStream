r"""Tier 7: the real build, in a real browser.

Every other tier talks to the app over HTTP. That is fast, and it cannot see
what the PAGE does with an answer -- and the page is most of this program. The
bug that prompted this tier is exactly that shape: /api/reel/audio answered
403, the page set that URL on an <audio> element, and the only symptom
anywhere was a greyed-out play button on somebody's screen. Every HTTP test
still passed, because the route was only ever asked to say no.

So this tier opens dist\AutoStream\AutoStream.exe -- the actual build, not the
source tree -- in Chromium, clicks through it, and watches three things the
HTTP tiers cannot:

    the console          a JS error is a dead button nobody hears about
    every response       anything the page asks for that comes back 4xx or 5xx
    media elements       readyState and duration: whether it can actually PLAY

The app runs against a throwaway home with youtube.enabled off, so nothing of
the user's is touched and nothing reaches YouTube.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import appd
import pytest

pytestmark = pytest.mark.ui

PAGES = ("dash", "library", "clips", "studio", "settings", "logs")
# Answers that are correct even though they are 4xx. Empty on purpose: today
# the page asks for nothing it expects to be refused, and an entry here should
# have to be justified.
ALLOWED_FAILURES: tuple[str, ...] = ()


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("ui-home")
    port = free_port()
    appd.seed_home(home, port)
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


@pytest.fixture(scope="module")
def browser():
    api = pytest.importorskip(
        "playwright.sync_api",
        reason="pip install playwright && python -m playwright install chromium")
    with api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:                               # noqa: BLE001
            pytest.skip(f"chromium will not launch: {e}")
        yield b
        b.close()


class Watched:
    """A page, plus everything that went wrong on it."""

    def __init__(self, page, base):
        self.page, self.base = page, base
        self.console: list[str] = []
        self.errors: list[str] = []
        self.failed: list[str] = []
        page.on("console", self._console)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("response", self._response)

    def _console(self, msg):
        if msg.type == "error":
            self.console.append(msg.text)

    def _response(self, r):
        if r.status >= 400:
            path = urlparse(r.url).path
            if path not in ALLOWED_FAILURES:
                self.failed.append(f"{r.status} {r.request.method} {path}")

    def clean(self, what: str = "") -> None:
        problems = ([f"console error: {c}" for c in self.console]
                    + [f"uncaught: {e}" for e in self.errors]
                    + [f"asked for and refused: {f}" for f in self.failed])
        assert problems == [], ((what or "the page") + " produced:\n  "
                                + "\n  ".join(problems))

    def api(self, method: str, path: str, body=None):
        """Ask the backend THROUGH THE PAGE, with the page's own token."""
        return self.page.evaluate(
            """async ([m, p, b]) => (m === 'GET' ? API.get(p) : API.post(p, b || {}))""",
            [method, path, body])

    def raw(self, method: str, path: str, body=None) -> dict:
        """The same, but reporting the status rather than throwing on it.

        Several routes answer 4xx as their correct answer -- a blank clip path
        is refused, and that refusal is the guard working. API.get raises on
        any non-2xx, so a sweep that used it would call every one of those a
        failure.
        """
        return self.page.evaluate(
            """async ([m, p, b]) => {
                 const sep = p.indexOf('?') >= 0 ? '&' : '?';
                 const url = p + sep + 'k=' + encodeURIComponent(SHELL_K);
                 const r = await fetch(url, m === 'GET' ? {} : {
                     method: 'POST',
                     headers: {'Content-Type': 'application/json'},
                     body: JSON.stringify(b || {})});
                 let out = null;
                 try { out = await r.json(); } catch (e) { out = null; }
                 return {status: r.status, body: out};
               }""", [method, path, body])


@pytest.fixture
def ui(browser, app):
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    page = ctx.new_page()
    w = Watched(page, app["base"])
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_selector("#view-dash", state="attached", timeout=30_000)
    page.wait_for_function("typeof API !== 'undefined' && typeof go === 'function'",
                           timeout=30_000)
    yield w
    ctx.close()


# ------------------------------------------------------------------ the page

def test_the_built_app_paints_its_page(ui):
    """The whole document is assembled from Python strings. A join that breaks
    is a blank window -- which is what 1.17.5 shipped."""
    assert ui.page.locator(".rail-btn[data-page]").count() == len(PAGES)
    assert ui.page.locator("#view-dash").count() == 1
    ui.page.wait_for_timeout(2500)          # two turns of the status poll
    ui.clean("opening the app")


@pytest.mark.parametrize("page_id", PAGES)
def test_every_page_opens_without_a_word_in_the_console(ui, page_id):
    ui.page.click(f'.rail-btn[data-page="{page_id}"]')
    ui.page.wait_for_selector(f"#view-{page_id}.is-active", timeout=15_000)
    ui.page.wait_for_timeout(1200)
    assert ui.page.locator(f"#view-{page_id} .card").count() >= 1, \
        f"the {page_id} page opened but drew no cards"
    ui.clean(f"the {page_id} page")


def test_nothing_the_page_asks_for_comes_back_refused(ui):
    """THE WATCHDOG. Walk the whole app and fail on any 4xx/5xx the page itself
    caused -- the class of bug that greyed out the beat marker's play button."""
    for page_id in PAGES:
        ui.page.click(f'.rail-btn[data-page="{page_id}"]')
        ui.page.wait_for_selector(f"#view-{page_id}.is-active", timeout=15_000)
        ui.page.wait_for_timeout(900)
    ui.clean("walking every page")


# ------------------------------------------------------------------- settings

def test_a_setting_saved_in_the_browser_reaches_the_app(ui):
    """Chosen in the real form, saved with the real button, read back out of
    the real app: the round trip the HTTP tier can only see half of."""
    ui.page.click('.rail-btn[data-page="settings"]')
    ui.page.wait_for_selector("#view-settings.is-active")
    # Only the chosen section is on screen, and advanced fields are folded
    # away inside a <details>. Both are real steps a person takes.
    ui.page.click('#set-nav [data-sec="clips"]')
    ui.page.wait_for_selector("#set-sec-clips:not(.hide)", timeout=15_000)
    ui.page.evaluate("""() => {
        const f = document.getElementById('set-f-clips-min-kills');
        for (let n = f; n; n = n.parentElement)
            if (n.tagName === 'DETAILS') n.open = true;
    }""")
    field = ui.page.locator("#set-f-clips-min-kills")
    field.wait_for(timeout=15_000)
    before = str(ui.api("GET", "/api/settings/values")["clips.min_kills"])
    want = "3" if before != "3" else "2"
    field.select_option(want)
    save = ui.page.locator("#set-save")
    assert save.is_enabled(), "editing a field did not arm Save"
    save.click()
    ui.page.wait_for_timeout(1500)
    after = str(ui.api("GET", "/api/settings/values")["clips.min_kills"])
    assert after == want, f"the page saved {want}, the app has {after}"
    ui.clean("saving a setting")


# -------------------------------------------------------------------- media

def test_the_beat_marker_can_actually_play_the_song(ui, tmp_path):
    """THE BUG THIS TIER EXISTS FOR. The song is analysed and the marker opened
    exactly as the page does it, then the <audio> element is asked whether it
    can play. Before the fix it carried media error 4 -- the request came back
    403 -- and every HTTP-level test still passed."""
    song = appd.click_track(tmp_path / "verify song.wav")
    got = ui.api("POST", "/api/reel/song", {"song": str(song)})
    assert got and got.get("ok"), f"the app could not read the song: {got}"

    ui.page.click('.rail-btn[data-page="clips"]')
    ui.page.wait_for_selector("#view-clips.is-active")
    ui.page.evaluate("""([path, got]) => {
        reel_useSong(path, got);      /* what choosing a track does */
        PAGE_REEL.open([]);           /* show the reel card */
        reel_openMark();              /* open the tap-the-beats panel */
    }""", [str(song), got])

    ui.page.locator("#reel-audio").wait_for(state="visible", timeout=15_000)
    ui.page.wait_for_function(
        """() => { const a = document.getElementById('reel-audio');
                   return a && (a.readyState > 0 || a.error); }""", timeout=20_000)
    state = ui.page.evaluate(
        """() => { const a = document.getElementById('reel-audio');
                   return {err: a.error && a.error.code, ready: a.readyState,
                           dur: a.duration, net: a.networkState, src: a.currentSrc}; }""")
    assert not state["err"], (
        f"the beat marker cannot play the song (media error {state['err']}, "
        f"network state {state['net']}): {state['src']}")
    assert state["ready"] >= 1 and state["dur"] > 1, \
        f"the player has nothing to tap against: {state}"
    ui.clean("opening the beat marker")


def test_a_clip_plays_in_the_page(ui, app, tmp_path):
    """The other media element, through the page's own URL builder against the
    real app -- so a video route that stops serving fails here."""
    import subprocess

    from autostream.clips.tools import binary

    ff = binary("ffmpeg")
    if not ff:
        pytest.skip("no ffmpeg to make a clip with")
    clips = Path(app["home"]) / "video" / "clips" / "ui-test"
    clips.mkdir(parents=True, exist_ok=True)
    made = clips / "sample.mp4"
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=320x180:rate=15:duration=2", str(made)],
                   check=True, timeout=180,
                   creationflags=appd.NO_WINDOW)
    ui.page.click('.rail-btn[data-page="clips"]')
    ui.page.wait_for_selector("#view-clips.is-active")
    state = ui.page.evaluate("""async (path) => {
        const v = document.createElement('video');
        v.src = clip_videoURL(path);          /* the page's own URL builder */
        document.body.appendChild(v);
        await new Promise(res => { v.onloadedmetadata = res; v.onerror = res;
                                   setTimeout(res, 15000); });
        return {err: v.error && v.error.code, ready: v.readyState, dur: v.duration};
    }""", str(made))
    assert not state["err"], f"a clip in the clips folder would not play: {state}"
    assert state["dur"] > 0.5, f"the clip loaded no video: {state}"
    ui.clean("playing a clip")


def _studio_run(app, name: str, count: int, seconds: float = 4.0) -> None:
    """A run of `count` real clips, each with its kill in the middle."""
    import json
    import subprocess

    from autostream.clips.tools import binary

    ff = binary("ffmpeg")
    if not ff:
        pytest.skip("no ffmpeg to make clips with")
    run = Path(app["home"]) / "video" / "clips" / name
    (run / "clips").mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(count):
        clip = run / "clips" / f"ui_{i}.mp4"
        subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"testsrc2=size=320x180:rate=30:duration={seconds}",
                        "-f", "lavfi", "-i", f"sine=frequency={300 + 100 * i}:duration={seconds}",
                        "-shortest", "-pix_fmt", "yuv420p", str(clip)], check=True, timeout=180,
                   creationflags=appd.NO_WINDOW)
        rows.append({"rank": i + 1, "start": 10.0 * (i + 1), "end": 10.0 * (i + 1) + seconds,
                     "duration": seconds, "kills": 1, "name": clip.stem, "master": str(clip),
                     "vertical": "", "caption": "", "tags": [], "at": ""})
    (run / "clips.json").write_text(json.dumps({"game": "VALORANT", "clips": rows}))
    (run / "session.json").write_text(json.dumps(
        {"game": "VALORANT", "kills": [{"time": 10.0 * (i + 1) + seconds / 2} for i in range(count)]}))


def _studio_build(page, folder_label: str, picks: int, style: str, name: str) -> None:
    page.click('.rail-btn[data-page="studio"]')
    page.wait_for_selector("#view-studio.is-active")
    page.click('[data-act="studio-refresh"]')
    page.wait_for_function(
        "(n) => [...document.querySelectorAll('.studio-folder')].some(f => f.textContent.indexOf(n) >= 0)",
        arg=folder_label, timeout=30_000)
    folder = page.locator(".studio-folder", has_text=folder_label).first
    tiles = folder.locator(".studio-clip-hit")
    page.click('[data-act="studio-clear"]') if page.is_visible('[data-act="studio-clear"]') else None
    for i in range(picks):
        tiles.nth(i).click()
    assert page.inner_text("#studio-tray-count").startswith(f"{picks} clips")
    page.click('[data-act="studio-make"]')
    page.click(f'[data-act="studio-style"][data-style="{style}"]')
    page.fill("#studio-name", name)
    page.click('[data-act="studio-build"]')
    page.wait_for_selector("#studio-pane-timeline:not(.hide)", timeout=60_000)


def _studio_rendered(page, what: str) -> None:
    page.wait_for_function(
        "() => { const t = document.getElementById('studio-state').textContent;"
        " return t.startsWith('Ready') || /fail|Could not|refus/i.test(t); }", timeout=300_000)
    state = page.inner_text("#studio-state")
    assert state.startswith("Ready"), f"{what}: {state}"
    video = page.evaluate("""async () => {
        const v = document.getElementById('studio-video');
        if (v.readyState < 1) await new Promise(r => { v.onloadedmetadata = r; v.onerror = r; setTimeout(r, 15000); });
        return {err: v.error && v.error.code, ready: v.readyState, dur: v.duration};
    }""")
    assert not video["err"] and video["dur"] > 1, f"{what}: the reel will not play: {video}"


def test_every_reel_is_reachable_not_only_the_newest_ten(ui, app):
    """The Studio listed the newest ten reels and nothing else; the user had 82.
    Twelve reels here: two rows show folded, all twelve unfold, and the search,
    the shape filter and the order each narrow or reorder the whole set."""
    import json
    import os
    import subprocess
    import time

    from autostream.clips.tools import binary

    ff = binary("ffmpeg")
    if not ff:
        pytest.skip("no ffmpeg to make reels with")
    reels = Path(app["home"]) / "video" / "clips" / "reels"
    reels.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for i in range(12):
        tall = i % 3 == 0
        mp4 = reels / f"grid reel {i:02d}.mp4"
        subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"testsrc2=size={'180x320' if tall else '320x180'}:rate=30:duration=2",
                        "-pix_fmt", "yuv420p", str(mp4)], check=True, timeout=120,
                       creationflags=appd.NO_WINDOW)
        mp4.with_suffix(".reel.json").write_text(json.dumps({
            "name": f"grid reel {i:02d}" + (" lyric" if i == 7 else ""), "style": "montage",
            "format": "vertical" if tall else "landscape",
            "shots": [{"pre": 0.5}] * (i + 1), "render": {"length": 2.0 + i, "intro": 0.0}}), encoding="utf-8")
        os.utime(mp4, (now - 3600 * (12 - i), now - 3600 * (12 - i)))     # reel 11 is the newest
    page = ui.page
    page.click('.rail-btn[data-page="studio"]')
    page.wait_for_selector("#view-studio.is-active")
    page.click('[data-act="studio-refresh"]')
    page.wait_for_function("document.querySelectorAll('#studio-reel-grid .studio-reel').length > 0", timeout=30_000)

    def names():
        return page.evaluate("[...document.querySelectorAll('#studio-reel-grid .studio-reel-name')].map(e => e.textContent)")
    assert page.inner_text("#studio-reels-count") == "12"
    assert len(names()) == 8 and names()[0] == "grid reel 11"
    more = page.locator("#studio-reels-more")
    assert more.inner_text() == "Show all 12 reels"
    more.click()
    assert len(names()) == 12 and names()[-1] == "grid reel 00"
    page.fill("#studio-reel-q", "lyric")
    page.wait_for_function("document.querySelectorAll('#studio-reel-grid .studio-reel').length === 1")
    assert names() == ["grid reel 07 lyric"]
    assert page.evaluate("document.activeElement.id") == "studio-reel-q", "typing lost the search box"
    page.fill("#studio-reel-q", "")
    page.click('[data-act="studio-reel-fmt"][data-fmt="vertical"]')
    assert sorted(names()) == ["grid reel 00", "grid reel 03", "grid reel 06", "grid reel 09"]
    page.click('[data-act="studio-reel-fmt"][data-fmt="all"]')
    page.select_option("#studio-reel-sort", "long")
    assert names()[0] == "grid reel 11" and names()[-1] == "grid reel 00"
    page.select_option("#studio-reel-sort", "old")
    assert names()[0] == "grid reel 00"
    # every card's still is a real frame, and pressing it plays that reel
    page.wait_for_function("""() => { const i = document.querySelector('#studio-reel-grid .studio-reel-thumb img');
        return i && i.complete && i.naturalWidth > 0; }""", timeout=30_000)
    ui.clean("browsing every reel")


def test_headshots_only_is_offered_for_read_clips_and_keeps_only_headshots(ui, app):
    """Valorant clips carry a headshot reading per kill. The tiles count them,
    the Make dialog offers "Headshot kills only" with what it would keep, and
    ticking it plans a reel of the headshot kills alone."""
    import json

    _studio_run(app, "2026-09-15_1200_VALORANT", 3)
    sess_p = Path(app["home"]) / "video" / "clips" / "2026-09-15_1200_VALORANT" / "session.json"
    sess = json.loads(sess_p.read_text())
    for k, hs in zip(sess["kills"], (True, False, True)):
        k["hs"] = hs
    sess_p.write_text(json.dumps(sess))
    page = ui.page
    page.click('.rail-btn[data-page="studio"]')
    page.wait_for_selector("#view-studio.is-active")
    page.click('[data-act="studio-refresh"]')
    folder = page.locator(".studio-folder", has_text="12:00").first
    folder.wait_for(timeout=30_000)
    assert "1 HS" in folder.locator(".studio-clip-kills").nth(0).inner_text()
    assert "HS" not in folder.locator(".studio-clip-kills").nth(1).inner_text().replace("0 HS", "")
    page.click('[data-act="studio-clear"]') if page.is_visible('[data-act="studio-clear"]') else None
    for i in range(3):
        folder.locator(".studio-clip-hit").nth(i).click()
    page.click('[data-act="studio-make"]')
    row = page.locator("#studio-hs-row")
    assert row.is_visible(), "headshots only is not offered for clips that carry a reading"
    assert "2 of 3 kills were headshots" in row.inner_text()
    page.check("#studio-hs-only")
    page.click('[data-act="studio-style"][data-style="story"]')
    page.fill("#studio-name", "Headshots")
    page.click('[data-act="studio-build"]')
    page.wait_for_selector("#studio-pane-timeline:not(.hide)", timeout=60_000)
    proj = page.evaluate("studio.project")
    assert proj["hs_only"] is True
    assert sorted(Path(s["clip"]).name for s in proj["shots"]) == ["ui_0.mp4", "ui_2.mp4"]
    page.evaluate("API.post('/api/studio/cancel', {})")
    ui.clean("headshots only")


def test_perfect_fit_keeps_every_kill_on_a_beat_and_survives_a_restyle(ui, app, tmp_path):
    """6.13. "Perfect fit (slower)" is chosen like any arrangement, the Make
    dialog warns that it takes longer, and the plan it returns has every kill
    of every chosen clip in it -- the triple whole -- each shot's kill on one
    of the song's hits. Rebuilding in another style keeps the arrangement."""
    import json
    import subprocess

    from autostream.clips.tools import binary

    ff = binary("ffmpeg")
    if not ff:
        pytest.skip("no ffmpeg to make clips with")
    name = "2026-09-16_1200_VALORANT"
    run = Path(app["home"]) / "video" / "clips" / name
    (run / "clips").mkdir(parents=True, exist_ok=True)
    # Three clips, 12 s each: a triple, a single and a double.
    want = {"fit_0": [2.5, 6.0, 9.5], "fit_1": [6.0], "fit_2": [3.0, 8.5]}
    rows, kills = [], []
    for i, (stem, ks) in enumerate(want.items()):
        clip = run / "clips" / f"{stem}.mp4"
        subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=12",
                        "-f", "lavfi", "-i", f"sine=frequency={300 + 100 * i}:duration=12",
                        "-shortest", "-pix_fmt", "yuv420p", str(clip)], check=True, timeout=180,
                       creationflags=appd.NO_WINDOW)
        start = 100.0 * (i + 1)
        rows.append({"rank": i + 1, "start": start, "end": start + 12.0, "duration": 12.0,
                     "kills": len(ks), "name": stem, "master": str(clip), "vertical": "",
                     "caption": "", "tags": [], "at": ""})
        kills += [{"time": start + k} for k in ks]
    (run / "clips.json").write_text(json.dumps({"game": "VALORANT", "clips": rows}))
    (run / "session.json").write_text(json.dumps({"game": "VALORANT", "kills": kills}))
    song = appd.click_track(tmp_path / "fit song.wav", seconds=60.0, bpm=120.0)

    page = ui.page
    page.click('.rail-btn[data-page="studio"]')
    page.wait_for_selector("#view-studio.is-active")
    page.click('[data-act="studio-refresh"]')
    folder = page.locator(".studio-folder", has_text="16 Sep").first
    folder.wait_for(timeout=30_000)
    page.click('[data-act="studio-clear"]') if page.is_visible('[data-act="studio-clear"]') else None
    for i in range(3):
        folder.locator(".studio-clip-hit").nth(i).click()
    # The bin redraws its buttons as the library loads, so the locator is
    # resolved afresh at each step rather than held.
    fit_btn = page.locator('[data-act="studio-arrange"][data-how="fit"]')
    assert "30 s" in (fit_btn.get_attribute("title") or ""), "the slower arrangement does not say it is slower"
    fit_btn.click()
    page.wait_for_function("studio.arrange === 'fit'")
    assert fit_btn.get_attribute("aria-pressed") == "true"
    page.evaluate("""(path) => { const real = API.post;
        API.post = function (u, b) {                  /* the native file dialog, answered */
            if (u === '/api/clips/pick') return Promise.resolve({path: path});
            return real.apply(this, arguments); }; }""", str(song))
    page.click('[data-act="studio-make"]')
    page.click('[data-act="studio-song"]')
    page.wait_for_function("studio.song && studio.songShape", timeout=60_000)
    page.click('[data-act="studio-style"][data-style="velocity"]')
    page.fill("#studio-name", "Fit check")
    before_job = page.evaluate("studio.jobId")
    page.click('[data-act="studio-build"]')
    assert "30 s" in page.inner_text("#studio-make-msg"), "planning a perfect fit gave no warning it takes longer"
    page.wait_for_selector("#studio-pane-timeline:not(.hide)", timeout=120_000)
    page.wait_for_function("(n) => studio.jobId && studio.jobId !== n", arg=before_job, timeout=60_000)
    page.evaluate("API.post('/api/studio/cancel', {})")

    proj = page.evaluate("studio.project")
    derived = page.evaluate("studio.derived")
    assert proj["arrange"] == "fit"
    assert any("Perfect fit" in n for n in proj.get("plan_notes") or []), proj.get("plan_notes")
    shown: dict[str, list[float]] = {}
    for s, row in zip(proj["shots"], derived["shots"]):
        for k in s["kills"]:
            if row["source_in"] - 1e-6 <= k <= row["source_out"] + 1e-6:
                shown.setdefault(Path(s["clip"]).stem, []).append(round(k, 1))
        assert row["drift"] is not None and abs(row["drift"]) <= 1 / 60 + 1e-4, \
            f"shot {row['index']} is {row['drift']} s off its hit"
    assert {k: sorted(v) for k, v in shown.items()} == {k: [round(x, 1) for x in v] for k, v in want.items()}

    # --- a rebuild in another style keeps the arrangement
    page.select_option("#studio-r-style", "hype")
    page.click("#studio-restyle-btn")
    page.wait_for_function("studio.project.style === 'hype'", timeout=120_000)
    assert page.evaluate("studio.project.arrange") == "fit", "the rebuild forgot the perfect fit"
    ui.clean("a perfect-fit reel")


def test_a_reel_is_made_edited_and_rendered_again_in_the_studio(ui, app):
    """The Studio's whole promise, in the real build: choose clips, get a reel
    that plays, change one shot on the timeline, and get the change rendered.

    Every step is a place the page and the server could disagree -- a route
    the bundle does not serve, a filter expression the packaged ffmpeg refuses,
    a video URL the player cannot load -- and none of them is visible to a
    test that does not drive the page."""
    import json

    _studio_run(app, "2026-09-14_1200_VALORANT", 3)
    page = ui.page
    _studio_build(page, "12:00", 2, "story", "UI check")

    def rendered(what):
        _studio_rendered(page, what)

    rendered("first render")
    assert page.locator(".st-shot").count() == 2
    page.locator(".st-shot").nth(1).click()
    _fxp_set(page, '#studio-insp [data-act="studio-fxp-open"][data-list="fx"]', ["k06"])
    # "Apply 1 change" since the render strip was reworded in v1.33.0; this
    # waited for the old "Render changes" and timed out on every run since.
    page.wait_for_function("/^Apply/.test(document.getElementById('studio-render-btn').textContent)")
    page.evaluate("document.getElementById('studio-state').textContent = ''")
    page.click("#studio-render-btn")
    rendered("the render after an edit")
    saved = ui.api("GET", "/api/studio/job")
    project = json.loads(Path(saved["project"]).read_text(encoding="utf-8"))
    assert "k06" in project["shots"][1]["fx"], "the edit on the timeline never reached the render"
    ui.clean("making and editing a reel")


def _wait_auto(page, what: str, after: int, timeout: float = 300_000) -> dict:
    """The first background-render event of kind `what` logged after `after`
    (a Date.now() on the page). -> the log row."""
    page.wait_for_function(
        "([w, a]) => studio.auto.log.some(x => x.what === w && x.at >= a)",
        arg=[what, after], timeout=timeout)
    return page.evaluate(
        "([w, a]) => studio.auto.log.find(x => x.what === w && x.at >= a)", [what, after])


def test_an_edit_plays_at_once_and_renders_itself_in_the_background(ui, app):
    """THE ASK: "to delete a clip from the reel the user marks it deleted, waits
    10-20 s for rendering, then checks. Make it fast."

    Deleting a shot must show in the player at once, with nothing rendered:
    the preview plays the timeline off the clip files, so its shot list, its
    length and the clip on screen after the cut all change in the same frame
    as the timeline. Its arithmetic is the server's -- checked here against
    clips/studio.py preview_at for the project actually on the page -- and it
    cuts on time, measured while it plays. Then, with nobody pressing Render,
    the real render starts once the edits stop and the player changes over to
    it when it matches the project."""
    import json

    from autostream.clips import studio as studio_mod

    _studio_run(app, "2026-09-16_1415_VALORANT", 3)
    page = ui.page
    _studio_build(page, "14:15", 3, "story", "Instant preview")
    _studio_rendered(page, "the first render")
    page.wait_for_function("!studio.pv.on && studio.project.shots.length === 3", timeout=30_000)
    before = page.evaluate("({len: studio.derived.length, clips: studio.project.shots.map(s => s.clip),"
                           " out: studio.output, at: studio.renderedAt})")

    # --- delete the middle shot and time how long the player takes to show it
    page.locator(".st-shot").nth(1).click()
    page.wait_for_selector('#studio-insp [data-act="studio-remove"]', timeout=15_000)
    got = page.evaluate("""async () => {
        const t0 = performance.now(), wall = Date.now();
        document.querySelector('#studio-insp [data-act="studio-remove"]').click();
        const sync = performance.now() - t0;
        const rows = studio.derived.shots.length, len = studio.derived.length, on = studio.pv.on;
        /* and until a frame of the edit is on screen: the cued player at the
           new cut holds the shot that now follows it, decoded */
        const ready = () => { const els = studio_pvEls();
            return els.some(e => Number(e.getAttribute('data-shot')) === 1 && e.readyState >= 2 && !e.seeking); };
        while (!ready() && performance.now() - t0 < 10000) await new Promise(r => requestAnimationFrame(r));
        return {sync: sync, frame: performance.now() - t0, rows: rows, len: len, on: on, wall: wall,
                clips: studio.project.shots.map(s => s.clip), ready: ready()};
    }""")
    edited_at = got["wall"]
    assert got["on"], "the player is still on the old render after a shot was deleted"
    assert got["rows"] == 2 and got["clips"] == [before["clips"][0], before["clips"][2]]
    assert got["len"] < before["len"] - 0.5, f"the reel did not get shorter: {before['len']} -> {got['len']}"
    assert got["ready"], "the shot after the cut never loaded in the preview"
    assert got["sync"] < 100, f"the preview took {got['sync']:.0f} ms to take the edit"
    assert page.is_visible("#studio-pv-tag") and not page.is_visible("#studio-video")
    print(f"\n  delete -> preview updated {got['sync']:.1f} ms, next shot's frame decoded {got['frame']:.0f} ms")

    # --- the page's arithmetic is the server's
    page.wait_for_function("studio.derived.shots.every(r => r.source_in !== undefined && r.freeze !== undefined)",
                           timeout=15_000)
    derived = page.evaluate("studio.derived")
    ts = [round(derived["length"] * k / 23, 3) for k in range(24)] + \
         [r["start"] for r in derived["shots"]] + [r["kill_reel"] for r in derived["shots"]]
    page_at = page.evaluate("(ts) => ts.map(t => studio_pvAt(t))", ts)
    for t, mine in zip(ts, page_at):
        want = studio_mod.preview_at(derived, t)
        assert mine["shot"] == want["shot"] and mine["rate"] == pytest.approx(want["rate"]), (t, mine, want)
        assert mine["src"] == pytest.approx(want["src"], abs=1e-3), (t, mine, want)

    # --- play across the new cut and measure it
    cut = derived["shots"][1]["start"]
    page.evaluate("(t) => { studio.pv.cuts = []; studio_seekTo(t); studio_pvPlay(); }", max(0.0, cut - 0.8))
    page.wait_for_function("(c) => studio_pvTime() > c + 0.7", arg=cut, timeout=15_000)
    played = page.evaluate("""() => { const el = studio_pvEls()[studio.pv.act], t = studio_pvTime();
        const r = {cuts: studio.pv.cuts.slice(), clip: el.getAttribute('data-clip'), cur: el.currentTime,
                   want: studio_pvAt(t).src, paused: el.paused, rate: el.playbackRate};
        studio_pvPause(); return r; }""")
    assert played["cuts"], "the preview played across a cut and never cut"
    first = played["cuts"][0]
    assert first["shot"] == 1 and first["cued"], played["cuts"]
    assert abs(first["late"]) < 0.05, f"the cut landed {first['late'] * 1000:.0f} ms off"
    assert played["clip"] == before["clips"][2], "after the cut the preview played the deleted shot"
    assert abs(played["cur"] - played["want"]) < 0.2, f"the preview drifted off the clock: {played}"
    print(f"  cut played {first['late'] * 1000:+.0f} ms from its place (cued player: {first['cued']})")

    # --- nobody presses Render: it renders itself, and the player changes over
    started = _wait_auto(page, "start", edited_at, timeout=60_000)
    done = _wait_auto(page, "done", edited_at)
    page.wait_for_function("!studio.pv.on && studio.renderedAt !== %d" % before["at"], timeout=30_000)
    state = page.evaluate("""async () => { const v = document.getElementById('studio-video');
        if (v.readyState < 1) await new Promise(r => { v.onloadedmetadata = r; v.onerror = r; setTimeout(r, 15000); });
        return {dur: v.duration, err: v.error && v.error.code, hidden: v.classList.contains('hide'),
                sync: document.getElementById('studio-sync-head').textContent,
                auto: document.getElementById('studio-auto-state').textContent,
                len: studio.derived.length, dirty: studio.dirty}; }""")
    assert not state["err"] and not state["hidden"], state
    assert state["dur"] == pytest.approx(state["len"], abs=0.25), \
        f"the rendered reel is {state['dur']:.2f} s, the edited timeline {state['len']:.2f} s"
    assert not state["dirty"] and state["sync"] == "The video matches your edits", state
    assert state["auto"] == "Up to date.", state
    saved = json.loads(Path(before["out"]).with_suffix(".reel.json").read_text(encoding="utf-8"))
    assert len(saved["shots"]) == 2, "the background render did not render the deleted shot away"
    print(f"  background render began {(started['at'] - edited_at) / 1000:.1f} s after the edit, "
          f"took {done['why']} s; rendered video in the player "
          f"{(page.evaluate('Date.now()') - edited_at) / 1000:.1f} s after the delete")
    ui.clean("an edit previewed at once and rendered in the background")


def test_no_background_render_starts_while_a_render_you_started_runs(ui, app):
    """Render is the user's: a background render must never start beside it,
    however long it runs. Edit, press Render, edit again while it renders --
    with the idle delay cut to 0.2 s, so the timer would fire many times over
    -- and not one background request may leave the page until that render is
    done. The edit made during it is then rendered by itself afterwards."""
    import json
    import time

    _studio_run(app, "2026-09-16_1530_VALORANT", 3)
    page = ui.page
    _studio_build(page, "15:30", 3, "story", "No second encode")
    _studio_rendered(page, "the first render")
    sent = []
    page.on("request", lambda r: sent.append((time.time() * 1000, r.post_data or ""))
            if "/api/studio/render" in r.url else None)
    # When the page's own Render job stops running, on the page's clock.
    page.evaluate("""() => { const busy = studio_busy;
        window.studio_busy = function (on) {
            if (!on && studio.rendering) window.__manualEnd = Date.now();
            return busy.apply(this, arguments); }; }""")
    page.locator(".st-shot").nth(0).click()
    page.click('#studio-insp [data-act="studio-move"][data-d="1"]')
    page.evaluate("document.getElementById('studio-state').textContent = ''")
    page.click("#studio-render-btn")
    page.wait_for_function("studio.rendering", timeout=30_000)
    # Only now: a timer that fired before Render was pressed is a background
    # render started before yours, which Render then replaced -- correct, and
    # not what this test is about.
    t0 = page.evaluate("studio.auto.idleMs = 200; Date.now()")
    page.locator(".st-shot").nth(2).click()
    page.click('#studio-insp [data-act="studio-move"][data-d="-1"]')
    held = _wait_auto(page, "held", t0, timeout=15_000)
    assert held["why"] == "Waiting for the render you started.", held
    assert page.evaluate("studio.pv.on"), "the edit made during the render is not being previewed"
    _studio_rendered(page, "the render you started")
    end = page.evaluate("window.__manualEnd")
    assert end and end >= t0, "the render you started never finished on the page"
    autos = [at for at, body in sent
             if t0 <= at < end and '"auto":true' in body.replace(" ", "")]
    assert autos == [], f"{len(autos)} background render(s) asked for while yours ran"
    # and once that render is done, the edit made during it renders itself
    started = _wait_auto(page, "start", t0, timeout=30_000)
    assert started["at"] >= end, "a background render started before yours had finished"
    _wait_auto(page, "done", end)
    page.wait_for_function("!studio.dirty && !studio.pv.on", timeout=30_000)
    order = page.evaluate("studio.project.shots.map(s => s.clip)")
    saved = json.loads(Path(page.evaluate("studio.output")).with_suffix(".reel.json").read_text(encoding="utf-8"))
    assert [s["clip"] for s in saved["shots"]] == order, "the edit made during your render never reached a video"
    ui.clean("a render you started is left alone")


def _fxp_set(page, opener: str, want: list[str], *, exact: bool = False) -> None:
    """Choose effects the way a person does since the picker replaced the
    checkbox walls: open it, find each by its code in the search box, click
    it, press Done. `exact` also takes off whatever else was on."""
    page.click(opener)
    page.wait_for_selector("#studio-fxp-scrim:not(.hide)")
    sel = page.evaluate("studio.fxp.sel.slice()")
    toggle = [w for w in want if w not in sel] + ([x for x in sel if x not in want] if exact else [])
    for pid in toggle:
        page.fill("#studio-fxp-q", pid)
        page.locator(f'#studio-fxp-list .studio-fxp-card[data-part="{pid}"]').first.click()
    page.click("#studio-fxp-done")
    page.wait_for_selector("#studio-fxp-scrim", state="hidden")


def test_the_effect_picker_searches_previews_remembers_and_applies(ui, app):
    """U1. Every effect choice on the timeline opens one dialog: search by
    name or by code, a preview of whichever option the pointer is on, the
    ones used recently first, and the choice applied through the same path
    the old dropdowns took -- so it is undoable and named in the list of
    what is not rendered yet."""
    _studio_run(app, "2026-09-14_1200_VALORANT", 3)
    page = ui.page
    _studio_build(page, "12:00", 2, "story", "Picker check")
    # Building starts a render; let it finish, or the next test's build finds
    # the studio busy and never gets a job of its own.
    _studio_rendered(page, "first render")
    page.locator(".st-shot").nth(1).click()
    page.evaluate("localStorage.removeItem('autostream.fxRecent')")

    # --- one choice: the speed. Search by NAME, then by CODE.
    page.click("#studio-f-speed")
    page.wait_for_selector("#studio-fxp-scrim:not(.hide)")
    assert page.evaluate("document.activeElement.id") == "studio-fxp-q", "search is not focused"
    parts = page.evaluate("studio_parts('speed').map(p => [p.id, p.label])")
    assert len(parts) >= 2
    current = page.evaluate("studio.project.shots[1].speed")
    pid, label = next((i, l) for i, l in parts if i != current)
    page.fill("#studio-fxp-q", label.split()[0].lower())
    assert page.locator(f'#studio-fxp-list .studio-fxp-card[data-part="{pid}"]').count() >= 1,         f"searching {label!r} by name did not find {pid}"
    page.fill("#studio-fxp-q", pid.upper())
    cards = page.locator("#studio-fxp-list .studio-fxp-card")
    assert cards.count() >= 1 and cards.first.get_attribute("data-part") == pid,         f"searching the code {pid.upper()} did not put {pid} first"
    page.fill("#studio-fxp-q", "zzqq-nothing")
    assert "Nothing matches" in page.inner_text("#studio-fxp-list")

    # --- the preview follows the pointer
    page.fill("#studio-fxp-q", "")
    other = page.locator(f'#studio-fxp-list .studio-fxp-card[data-part="{pid}"]').first
    other.hover()
    page.wait_for_function("(id) => document.getElementById('studio-fxp-prevcode').textContent === id.toUpperCase()",
                           arg=pid)

    # --- Escape closes without changing anything, and focus comes back
    page.keyboard.press("Escape")
    page.wait_for_selector("#studio-fxp-scrim", state="hidden")
    assert page.evaluate("studio.project.shots[1].speed") == current
    assert page.evaluate("document.activeElement.id") == "studio-f-speed"

    # --- a click applies it, undoably, and it is remembered
    page.click("#studio-f-speed")
    page.wait_for_selector("#studio-fxp-scrim:not(.hide)")
    page.fill("#studio-fxp-q", pid)
    page.locator(f'#studio-fxp-list .studio-fxp-card[data-part="{pid}"]').first.click()
    page.wait_for_selector("#studio-fxp-scrim", state="hidden")
    page.wait_for_function("(id) => studio.project.shots[1].speed === id", arg=pid)
    assert page.locator("#studio-f-speed").get_attribute("data-part") == pid
    page.click("#studio-f-speed")
    page.wait_for_selector("#studio-fxp-scrim:not(.hide)")
    assert "recently used" in page.inner_text("#studio-fxp-list").lower()
    page.keyboard.press("Escape")
    page.click("#studio-undo-btn")
    page.wait_for_function("(id) => studio.project.shots[1].speed === id", arg=current)

    # --- several at once: kill effects, then one taken off by its chip
    before = page.evaluate("studio.project.shots[1].fx.slice()")
    add = next(i for i in page.evaluate("studio_parts('kill').map(p => p.id)") if i not in before)
    _fxp_set(page, '#studio-insp [data-act="studio-fxp-open"][data-list="fx"]', [add])
    page.wait_for_function("(id) => studio.project.shots[1].fx.indexOf(id) >= 0", arg=add)
    page.click(f'#studio-insp .studio-pick-x[data-list="fx"][data-part="{add}"]')
    page.wait_for_function("(id) => studio.project.shots[1].fx.indexOf(id) < 0", arg=add)
    ui.clean("the effect picker")


def test_the_change_count_is_what_differs_from_the_video_not_clicks(ui, app):
    """6.13. "If I select and unselect a setting, the changes count increases."
    It counted clicks: a switch turned on and off again was two changes to a
    project identical to the video, and the button begged to apply them. The
    count is now a comparison with what was rendered, so it is driven here
    through the real controls and read back off the card, the button and the
    badge over the player -- the three places that say it."""
    _studio_run(app, "2026-09-14_1200_VALORANT", 3)
    page = ui.page
    _studio_build(page, "12:00", 2, "story", "Count check")
    _studio_rendered(page, "first render")

    def says(n: int) -> None:
        page.wait_for_function("(n) => studio_pendingCount() === n", arg=n, timeout=15_000)
        head = page.inner_text("#studio-sync-head")
        button = page.inner_text("#studio-render-btn")
        if n:
            word = "change" if n == 1 else "changes"
            assert head == f"{n} {word} {'is' if n == 1 else 'are'} not in the video", head
            assert button == f"Apply {n} {word}", button
            assert page.inner_text("#studio-stale") == f"Last render · {n} {word} not shown"
            assert page.locator("#studio-pending li").count() == n
        else:
            assert head == "The video matches your edits", head
            assert not button.startswith("Apply"), f"nothing differs, yet the button says {button!r}"
            assert not page.is_visible("#studio-stale")

    def settle() -> None:
        # The server's answer to an edit lands a moment later and can move a
        # field; the count must still be right once it has.
        page.wait_for_timeout(700)

    says(0)
    page.click('#studio-insp [data-act="studio-select"][data-shot="-1"]')
    vig = page.evaluate("studio.project.vignette")

    # --- the reported bug: on, then off again
    page.click("#studio-r-vignette")
    page.wait_for_function("(v) => studio.project.vignette === !v", arg=vig)
    says(1)
    assert "Vignette" in page.inner_text("#studio-pending")
    page.click("#studio-r-vignette")
    page.wait_for_function("(v) => studio.project.vignette === v", arg=vig)
    says(0)
    settle()
    says(0)

    # --- two different things, one undone
    fit = page.evaluate("studio.project.vfit || 'zoom'")
    other = "fit" if fit == "zoom" else "zoom"
    page.click("#studio-r-vignette")
    page.click(f'#studio-insp [data-act="studio-rfit"][data-fit="{other}"]')
    page.wait_for_function("(f) => studio.project.vfit === f", arg=other)
    says(2)
    page.click("#studio-undo-btn")
    page.wait_for_function("(f) => (studio.project.vfit || 'zoom') === f", arg=fit)
    says(1)
    page.click("#studio-undo-btn")
    page.wait_for_function("(v) => studio.project.vignette === v", arg=vig)
    says(0)
    settle()
    says(0)

    # --- one shot's field, changed and then put back by hand. The camera move,
    # because it asks nothing of the footage: a speed can make the server trim
    # the shot, and then putting the speed back rightly leaves a change.
    page.locator(".st-shot").nth(1).click()
    if not page.evaluate("document.querySelector('#studio-insp details[data-grp=\"camera\"]').open"):
        page.click('#studio-insp details[data-grp="camera"] > summary')
    current = page.evaluate("studio.project.shots[1].camera")
    other = next(i for i in page.evaluate("studio_parts('camera').map(p => p.id)") if i != current)
    for pid in (other, current):
        page.click("#studio-f-camera")
        page.wait_for_selector("#studio-fxp-scrim:not(.hide)")
        page.fill("#studio-fxp-q", pid)
        page.locator(f'#studio-fxp-list .studio-fxp-card[data-part="{pid}"]').first.click()
        page.wait_for_selector("#studio-fxp-scrim", state="hidden")
        page.wait_for_function("(id) => studio.project.shots[1].camera === id", arg=pid)
        if pid == other:
            says(1)
            assert "Shot 2 · camera move" in page.inner_text("#studio-pending")
    says(0)
    settle()
    says(0)
    ui.clean("the change count")


def test_the_studio_mixes_effects_restyles_and_cuts_to_marked_kills(ui, app, tmp_path):
    """Everything the timeline offers beyond one shot's checkboxes, in the build.

    The reel the user sent back had the same effect on every kill, and
    "Rebuild with this style" was reported as doing nothing -- so both are
    driven through their own buttons and judged by the project, not by a toast.
    Then the song editor: choose a track, fine-tune the part, mark kills on it,
    apply, and render -- and every marked kill must land on its mark."""
    import json

    _studio_run(app, "2026-09-13_2130_VALORANT", 6, seconds=6.0)
    page = ui.page
    page.evaluate("""() => { window.__toasts = []; const t = window.toast;
        window.toast = function (m) { window.__toasts.push(String(m)); return t.apply(this, arguments); }; }""")
    before_job = page.evaluate("studio.jobId")
    _studio_build(page, "21:30", 6, "velocity", "Mix check")
    # Edits first, one render at the end. Build shows the timeline BEFORE it
    # starts the render, so a cancel sent then finds nothing to cancel and the
    # render finishes mid-test -- wait for the job to exist first.
    page.wait_for_function("(n) => studio.jobId && studio.jobId !== n", arg=before_job, timeout=60_000)
    page.evaluate("API.post('/api/studio/cancel', {})")
    page.wait_for_function("/^Cancelled|^Ready/.test(document.getElementById('studio-state').textContent)",
                           timeout=120_000)

    shots = page.evaluate("studio.project.shots")
    firsts = [s["fx"][0] for s in shots]
    assert all(a != b for a, b in zip(firsts, firsts[1:])), f"two kills running got one effect: {firsts}"
    assert len(set(firsts)) >= 3, f"the reel draws from too few kill effects: {firsts}"

    # --- the Reel inspector: pools and the Mix buttons
    page.click('#studio-insp [data-act="studio-select"][data-shot="-1"]')
    timing = page.evaluate("studio.derived.shots.map(r => [r.start, r.kill_reel])")
    before = page.evaluate("studio.project.shots.map(s => s.fx.join('+')).join()")
    page.click('[data-act="studio-mix"][data-what="kill"]')
    page.wait_for_function("(b) => studio.project.shots.map(s => s.fx.join('+')).join() !== b",
                           arg=before, timeout=15_000)
    after = page.evaluate("studio.derived.shots.map(r => [r.start, r.kill_reel])")
    assert all(abs(a - b) < 1e-3 for x, y in zip(timing, after) for a, b in zip(x, y)), \
        "mixing the effects moved a cut or a kill"
    before = page.evaluate("studio.project.shots.map(s => s.transition).join()")
    page.click('[data-act="studio-mix"][data-what="transition"]')
    page.wait_for_function("(b) => studio.project.shots.map(s => s.transition).join() !== b",
                           arg=before, timeout=15_000)
    _fxp_set(page, '#studio-insp [data-act="studio-fxp-open"][data-pool="kill"]', ["k02", "k06"], exact=True)
    page.wait_for_function(
        "studio.project.shots.every(s => s.fx.every(k => k === 'k02' || k === 'k06'))", timeout=15_000)

    # --- Rebuild with this style
    page.select_option("#studio-r-style", "hype")
    page.click("#studio-restyle-btn")
    page.wait_for_function("studio.project.style === 'hype'", timeout=30_000)
    assert page.evaluate("studio.project.name") == "Mix check"
    assert any(t.startswith("Rebuilt as") for t in page.evaluate("window.__toasts"))

    # --- one shot's effects, then onto every shot
    page.locator(".st-shot").nth(1).click()
    _fxp_set(page, '#studio-insp [data-act="studio-fxp-open"][data-list="fx"]', ["k03"])
    page.wait_for_function("studio.project.shots[1].fx.indexOf('k03') >= 0", timeout=15_000)
    page.click('[data-act="studio-fx-all"]')
    page.wait_for_function(
        "studio.project.shots.every(s => s.fx.join() === studio.project.shots[1].fx.join())", timeout=15_000)
    page.click("#studio-undo-btn")
    page.wait_for_function(
        "!studio.project.shots.every(s => s.fx.join() === studio.project.shots[1].fx.join())", timeout=15_000)

    # --- the song editor
    song = appd.click_track(tmp_path / "studio song.wav", seconds=40.0, bpm=120.0)
    page.click("#studio-tab-song")
    page.evaluate("""(path) => { const real = API.post;
        API.post = function (u, b) {                  /* the native file dialog, answered */
            if (u === '/api/clips/pick') return Promise.resolve({path: path});
            return real.apply(this, arguments); }; }""", str(song))
    page.click('[data-act="studio-sg-pick"]')
    page.wait_for_selector("#studio-sg-body:not(.hide)", timeout=60_000)
    audio = page.evaluate("""async () => {
        const a = document.getElementById('studio-sg-audio');
        if (a.readyState < 1) await new Promise(r => { a.onloadedmetadata = r; a.onerror = r; setTimeout(r, 15000); });
        return {err: a.error && a.error.code, dur: a.duration}; }""")
    assert not audio["err"] and audio["dur"] > 30, f"the song editor cannot play the song: {audio}"
    # --- the ways of seeing it, and whether they MOVE
    # The lanes were drawn around a field nothing ever set, so they sat at zero
    # while the song played and every still-frame check passed anyway. Play it
    # and watch the window advance.
    page.wait_for_function("() => studio.sv && studio.sv.meta && studio.sv.bytes", timeout=120_000)
    lanes = page.evaluate("() => [...document.querySelectorAll('#studio-sg-lanes .studio-sg-lane')]"
                          ".map(l => l.getAttribute('data-lane'))")
    assert lanes, "the song has no views at all"
    assert "spec" in lanes, f"no spectrogram: {lanes}"
    assert page.evaluate("() => studio.sv.meta.frames") > 1000, "the lanes are empty"

    def spec_row():
        """A row of pixels out of the spectrogram, as a string."""
        return page.evaluate("""() => { const c = document.querySelector('[data-lane="spec"] canvas');
            if (!c) return '';
            const d = c.getContext('2d').getImageData(0, Math.round(c.height * 0.6), c.width, 1).data;
            let out = ''; for (let i = 0; i < d.length; i += 40) out += d[i] + ',';
            return out; }""")

    page.evaluate("() => { document.getElementById('studio-sg-audio').currentTime = 2; }")
    page.wait_for_timeout(300)
    was_window = page.evaluate("() => studio_svWindow().t0")
    was_row = spec_row()
    assert was_row.strip(","), "the spectrogram drew nothing"
    page.click('[data-act="studio-sg-play"]')
    page.wait_for_function("() => document.getElementById('studio-sg-audio').currentTime > 4",
                           timeout=30_000)
    now_window = page.evaluate("() => studio_svWindow().t0")
    now_row = spec_row()
    page.evaluate("() => document.getElementById('studio-sg-audio').pause()")
    assert now_window > was_window + 1.0, \
        f"the lanes did not follow the song: window {was_window:.2f}s -> {now_window:.2f}s"
    assert now_row != was_row, "the spectrogram is drawing the same stretch while the song plays"

    beat = page.evaluate("studio_sgBeat()")
    s0 = page.evaluate("studio.sg.start")
    page.click('[data-act="studio-sg-nudge"][data-what="start"][data-d="bar"]')
    page.click('[data-act="studio-sg-nudge"][data-what="start"][data-d="ms"]')
    assert page.evaluate("studio.sg.start") == pytest.approx(s0 + 4 * beat + 0.01, abs=1e-3)
    page.click('[data-act="studio-sg-snapbar"]')
    page.click('[data-act="studio-sg-fit"]')
    start = page.evaluate("studio.sg.start")
    for k in (1, 3, 5):                                       # K at three playheads
        page.evaluate(f"document.getElementById('studio-sg-audio').currentTime = {start + k * 2 * beat + 0.04}")
        page.evaluate("document.activeElement && document.activeElement.blur()")
        page.keyboard.press("k")
    marks = page.evaluate("studio.sg.marks")
    assert len(marks) == 3, f"K did not mark the kills: {marks}"
    assert page.locator("#studio-sg-chips .reel-chip").count() == 3
    page.click("#studio-sg-apply")
    page.wait_for_selector("#studio-pane-timeline:not(.hide)", timeout=60_000)
    proj, derived = page.evaluate("[studio.project, studio.derived]")
    assert proj["song"] == str(song)
    assert proj["song_offset"] == pytest.approx(start, abs=1e-3)
    landed = [derived["shots"][i]["kill_reel"] + proj["song_offset"] for i in range(3)]
    assert landed == pytest.approx(marks, abs=0.04), f"marks {marks}, kills landed at {landed}"
    # --- the instant preview plays the new song under the cuts, from where
    # the reel starts it -- before anything has been rendered with it
    song_play = page.evaluate("""async () => {
        /* held off for the length of the check, so a background render
           finishing mid-way cannot swap the player out from under it */
        const was = studio.auto.on; studio.auto.on = false;
        studio_seekTo(0.5); studio_pvPlay();
        const a = document.getElementById('studio-pv-song'), t0 = performance.now();
        while ((a.paused || a.readyState < 2 || a.currentTime < studio.project.song_offset + 1.0)
               && performance.now() - t0 < 15000) await new Promise(r => setTimeout(r, 50));
        const r = {on: studio.pv.on, err: a.error && a.error.code, paused: a.paused,
                   drift: a.currentTime - (studio.project.song_offset + studio_pvTime())};
        studio_pvPause(); studio.auto.on = was; return r; }""")
    assert song_play["on"] and not song_play["err"] and not song_play["paused"], song_play
    assert abs(song_play["drift"]) < 0.2, f"the preview's song is {song_play['drift']:+.2f} s off the cuts"

    # --- lyrics: a .lrc beside the song, so nothing is fetched, in a chosen look and face
    song.with_suffix(".lrc").write_text(
        "".join(f"[00:{t:02d}.00]line {t} of the test song here\n" for t in range(0, 40, 2)), encoding="utf-8")
    page.click('#studio-insp [data-act="studio-select"][data-shot="-1"]')
    page.evaluate("() => { const d = document.querySelector('#studio-insp details[data-grp=\"lyrics\"]'); if (d) d.open = true; }")
    page.select_option("#studio-r-lyrics", "caption")
    page.wait_for_function("studio.project.lyrics && studio.project.lyrics.look === 'caption'", timeout=15_000)
    page.wait_for_selector("#studio-r-lyricface", timeout=15_000)
    page.select_option("#studio-r-lyricface", "gochi")
    page.wait_for_function("studio.project.lyrics.face === 'gochi'", timeout=15_000)
    # put them anywhere: drag the LYRICS stand-in on the picture, then one of the nine places.
    # The stand-in is not over the video until asked for -- it covered the real words.
    chip = page.locator("#studio-lyrics-chip")
    assert not chip.is_visible(), "the LYRICS stand-in sits over the video before anything is being placed"
    page.click('#studio-insp [data-act="studio-lyr-move"]')
    chip.wait_for(state="visible", timeout=15_000)
    box = chip.bounding_box()
    vr = page.evaluate("studio_videoRect()")
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx + vr["w"] * 0.2, cy + vr["h"] * 0.3, steps=6)
    page.mouse.up()
    page.wait_for_function("studio.project.lyrics.pos && studio.project.lyrics.pos[1] > 0.6", timeout=15_000)
    page.click('#studio-insp [data-act="studio-lyr-pos"][data-x="0"][data-y="1"]')
    page.wait_for_function("studio.project.lyrics.pos[0] === 0.25 && studio.project.lyrics.pos[1] === 0.85",
                           timeout=15_000)
    # and their timing, by ear: every line half a second later
    page.click('#studio-insp [data-act="studio-lyr-shift"][data-d="0.5"]')
    page.wait_for_function("studio.project.lyrics.shift === 0.5", timeout=15_000)
    assert page.inner_text("#studio-lyr-shift-val") == "+0.5 s"

    page.evaluate("document.getElementById('studio-state').textContent = ''; window.__toasts = []")
    page.click("#studio-render-btn")
    _studio_rendered(page, "the render with a song, marks and mixed effects")
    page.wait_for_timeout(1000)
    job = ui.api("GET", "/api/studio/job")
    saved = json.loads(Path(job["project"]).read_text(encoding="utf-8"))
    assert saved["song"] == str(song) and saved["style"] == "hype"
    assert saved["lyrics"] == {"look": "caption", "face": "gochi", "clean": False, "pos": [0.25, 0.85], "shift": 0.5}
    assert not page.locator("#studio-lyrics-chip").is_visible(), "the LYRICS stand-in stayed over the rendered words"
    assert "studio song.lrc" in (saved.get("lyrics_note") or ""), saved.get("lyrics_note")
    assert "studio song.lrc" in page.inner_text('#studio-insp details[data-grp="lyrics"]')
    assert page.evaluate("window.__toasts.filter(t => t === 'Reel ready.').length") == 1
    ui.clean("mixing, restyling and cutting to marked kills")


# ------------------------------------------- the backend, through the page

def _rows():
    import catalog

    return [c for c in catalog.CONTROLS
            if c.probe == catalog.CALL and c.path.startswith("/api/")
            and c.method in ("GET", "POST")]


@pytest.mark.parametrize("c", _rows(), ids=lambda c: f"{c.method} {c.path}")
def test_the_backend_answers_the_built_app(ui, c):
    """Tier 2 asks these of a server built inside the test process. This asks
    the same of the FROZEN build, through the page's own fetch -- so a route
    that only breaks once PyInstaller has packaged it fails here."""
    path = f"{c.path}?{c.query}" if c.query else c.path
    got = ui.raw(c.method, path, c.body)
    assert got["status"] in c.status, (
        f"{c.path} answered {got['status']}, expected one of {c.status}. {c.why}")
    if got["status"] == 200 and c.expect_resp is None and c.expect is not None:
        assert c.expect(got["body"]), f"{c.path} answered {str(got['body'])[:300]}"


def test_the_watchdog_notices_a_dead_player(ui, tmp_path):
    """Proof that the tests above would fail if the bug came back.

    A song the app has not analysed is refused -- which is precisely what the
    whole Downloads folder was, before the fix. The page is made to ask for one
    anyway, and both nets must catch it: the media element ends up with an
    error, and the refused response is recorded. If either stops working, the
    checks above would go quiet instead of failing.
    """
    import urllib.parse

    stranger = tmp_path / "not the chosen song.wav"
    appd.click_track(stranger, seconds=2.0)
    state = ui.page.evaluate("""async (path) => {
        const a = document.createElement('audio');
        a.src = '/api/reel/audio?k=' + encodeURIComponent(SHELL_K) +
                '&path=' + encodeURIComponent(path);
        document.body.appendChild(a);
        await new Promise(res => { a.onloadedmetadata = res; a.onerror = res;
                                   setTimeout(res, 10000); });
        return {err: a.error && a.error.code, ready: a.readyState};
    }""", str(stranger))
    assert state["err"], "a refused song still looked playable to the page"
    assert any("/api/reel/audio" in f for f in ui.failed), \
        f"the response watchdog did not record the refusal: {ui.failed}"
    ui.failed.clear()        # the refusal was the point of this test
