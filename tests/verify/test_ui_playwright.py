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
                   check=True, timeout=180)
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
                        "-shortest", "-pix_fmt", "yuv420p", str(clip)], check=True, timeout=180)
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
    page.locator('#studio-insp input[data-list="fx"][value="k06"]').check()
    page.wait_for_function("document.getElementById('studio-render-btn').textContent === 'Render changes'")
    page.evaluate("document.getElementById('studio-state').textContent = ''")
    page.click("#studio-render-btn")
    rendered("the render after an edit")
    saved = ui.api("GET", "/api/studio/job")
    project = json.loads(Path(saved["project"]).read_text(encoding="utf-8"))
    assert "k06" in project["shots"][1]["fx"], "the edit on the timeline never reached the render"
    ui.clean("making and editing a reel")


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
    for v in page.evaluate("[...document.querySelectorAll('#studio-insp input[data-pool=\"kill\"]:checked')].map(x => x.value)"):
        if v not in ("k02", "k06"):
            page.locator(f'#studio-insp input[data-pool="kill"][value="{v}"]').uncheck()
            page.wait_for_timeout(250)
    for v in ("k02", "k06"):
        box = page.locator(f'#studio-insp input[data-pool="kill"][value="{v}"]')
        if not box.is_checked():
            box.check()
            page.wait_for_timeout(250)
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
    page.locator('#studio-insp input[data-list="fx"][value="k03"]').check()
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

    page.evaluate("document.getElementById('studio-state').textContent = ''; window.__toasts = []")
    page.click("#studio-render-btn")
    _studio_rendered(page, "the render with a song, marks and mixed effects")
    page.wait_for_timeout(1000)
    saved = json.loads(Path(ui.api("GET", "/api/studio/job")["project"]).read_text(encoding="utf-8"))
    assert saved["song"] == str(song) and saved["style"] == "hype"
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
