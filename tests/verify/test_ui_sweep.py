r"""Tier 7: press everything, and listen.

WHY A SWEEP RATHER THAN 244 CASES. The UI declares 190 `data-act` controls and
54 operable ids. Hand-writing a case for each would produce 244 things to keep
current, and most of them would assert only that pressing did not explode --
which is a real property, but one worth asserting mechanically rather than by
hand.

So this reads the control list out of the source on every run and presses what
it finds, asserting the weak-but-universal thing: no console error, no uncaught
exception, and nothing the page asked for coming back refused. It cannot drift,
because a control added tomorrow is swept tomorrow with nothing to update.

WHAT THIS DOES NOT DO is tell you a feature works. A button that quietly does
the wrong thing passes here. The focused files are what assert outcomes; see
docs/UI-SCENARIOS.md for which scenarios are covered by which.

Some controls are deliberately not pressed -- see DESTRUCTIVE. Each one is
named with a reason, because "skip the dangerous ones" quietly becomes "skip
the ones that fail".
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import appd
import pytest
import surface

nl = chr(10)

pytestmark = pytest.mark.ui

PAGES = ("dash", "library", "clips", "studio", "settings", "logs")

# Pressed by nobody. Each of these ends the session, destroys work, or opens a
# native dialog that a headless run cannot close -- so a sweep that pressed
# them would be testing the sweep's own ability to recover, not the app.
DESTRUCTIVE = {
    "install-tools": "runs winget and raises a UAC prompt",
    "voice-get": "starts a 206 MB download over the connection",
    "pick-local": "opens a native file dialog nothing can close",
    "studio-sg-pick": "opens a native file dialog",
    "studio-intro-pick": "opens a native file dialog",
    "outro-pick": "opens a native file dialog",
    "studio-pick": "opens a native file dialog",
    "pick": "opens a native file dialog",
    "studio-yt": "opens a download dialog and then fetches from YouTube",
    "studio-yt-go": "downloads from YouTube",
    "studio-delete": "deletes a reel",
    "studio-remove": "removes a reel from the library",
    "cal-reset": "throws away a calibration",
    "studio-fc-boxreset": "throws away the facecam box",
    "studio-sg-clearmarks": "throws away marked beats",
    "reel-clearmarks": "throws away marked beats",
    "studio-imp-clear": "throws away an import in progress",
    "studio-intro-clear": "throws away the chosen intro",
    "reveal": "opens a file explorer window on the desktop",
    "reveal-out": "opens a file explorer window on the desktop",
    "reveal-src": "opens a file explorer window on the desktop",
    "studio-show": "opens a file explorer window on the desktop",
    "reel-show": "opens a file explorer window on the desktop",
}

# Anything whose name says it opens a native picker. Belt and braces with
# DESTRUCTIVE above: a picker added later is unpressable the day it lands
# rather than the day somebody remembers to list it.
PICKER_HINTS = ("-pick", "pick-", "choose", "browse")


def _skip_reason(token: str) -> str:
    if token in DESTRUCTIVE:
        return DESTRUCTIVE[token]
    return ""


def _seed_data(home: Path) -> None:
    """A recording and a finished run, so the pages have something to draw.

    WITHOUT THIS THE SWEEP IS NEARLY EMPTY. Measured on a blank install: 14 of
    the 190 declared controls ever render, because almost every one lives in a
    card that only appears once there is a stream, a clip or a reel. A sweep
    of an empty app mostly proves that an empty app has no buttons.
    """
    import json
    import subprocess

    from autostream.clips.tools import binary

    ff = binary("ffmpeg")
    if not ff:
        pytest.skip("no ffmpeg to seed the pages with")

    rec = home / "video" / "swept.mp4"
    rec.parent.mkdir(parents=True, exist_ok=True)
    if not rec.is_file():
        subprocess.run(
            [ff, "-y", "-v", "error", "-f", "lavfi", "-i",
             "testsrc2=size=640x360:rate=15:duration=200",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=200",
             "-shortest", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             str(rec)], check=True, timeout=900,
            creationflags=appd.NO_WINDOW)
    (home / "video" / "history.jsonl").write_text(json.dumps({
        "session": 1, "game": "VALORANT",
        "game_key": "valorant-win64-shipping.exe",
        "started": 1_790_000_000.0, "ended": 1_790_000_200.0,
        "recording_path": str(rec), "recording_seconds": 200,
        "recording_bytes": rec.stat().st_size, "title": "swept"}) + chr(10),
        encoding="utf-8")

    # A finished run, so the results, the player and the whole Studio library
    # have rows to draw.
    run = home / "video" / "clips" / "sweep-run"
    (run / "clips").mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(3):
        clip = run / "clips" / f"sweep_{i}.mp4"
        if not clip.is_file():
            subprocess.run(
                [ff, "-y", "-v", "error", "-f", "lavfi", "-i",
                 "testsrc2=size=320x180:rate=30:duration=4",
                 "-f", "lavfi", "-i", f"sine=frequency={300 + 90 * i}:duration=4",
                 "-shortest", "-pix_fmt", "yuv420p", str(clip)],
                check=True, timeout=600,
                creationflags=appd.NO_WINDOW)
        rows.append({"rank": i + 1, "start": 10.0 * (i + 1),
                     "end": 10.0 * (i + 1) + 4, "duration": 4.0, "kills": i + 1,
                     "name": clip.stem, "master": str(clip), "vertical": "",
                     "caption": "", "tags": [], "at": f"0m{10 * (i + 1)}s"})
    (run / "clips.json").write_text(
        json.dumps({"game": "VALORANT", "clips": rows}), encoding="utf-8")
    (run / "session.json").write_text(json.dumps(
        {"game": "VALORANT", "source": str(rec),
         "kills": [{"time": 10.0 * (i + 1) + 2} for i in range(3)]}),
        encoding="utf-8")

    # A SONG AND AN INTRO, because the controls that outnumber everything
    # else need one loaded rather than a panel opened: fifteen on the song
    # tab, seven in the make dialog, twelve in the reel maker and ten on the
    # intro dialog only exist once there is something to work on. Dropped
    # straight into the folders the app reads, which is the same route that
    # exists so a song can be chosen without the file dialog -- see
    # webui.studio_songs.
    song = home / "video" / "songs" / "sweep-song.m4a"
    song.parent.mkdir(parents=True, exist_ok=True)
    if not song.is_file():
        subprocess.run(
            [ff, "-y", "-v", "error", "-f", "lavfi",
             "-i", "sine=frequency=220:duration=40",
             "-af", "volume=0.4", "-c:a", "aac", "-b:a", "128k", str(song)],
            check=True, timeout=600, creationflags=appd.NO_WINDOW)
    # A FINISHED REEL, with its timeline beside it. Forty of the controls
    # left live on the Studio's timeline, its intro dialog, its make dialog
    # and its facecam panel, and every one of them asks `studio.project`
    # first -- so without a project they do not exist to be pressed. A reel
    # is an mp4 and a .reel.json next to it (see webui.studio_project), so it
    # can be written rather than rendered: a real build is minutes of
    # encoding to reach buttons that only need the timeline to be there.
    reels = home / "video" / "clips" / "reels"
    reels.mkdir(parents=True, exist_ok=True)
    reel_mp4 = reels / "sweep-reel.mp4"
    if not reel_mp4.is_file():
        subprocess.run(
            [ff, "-y", "-v", "error", "-f", "lavfi", "-i",
             "testsrc2=size=640x360:rate=30:duration=8",
             "-f", "lavfi", "-i", "sine=frequency=330:duration=8",
             "-shortest", "-pix_fmt", "yuv420p", str(reel_mp4)],
            check=True, timeout=600, creationflags=appd.NO_WINDOW)
    shots = []
    for i, row in enumerate(rows):
        shots.append({
            "clip": row["master"], "name": row["name"],
            "clip_id": f"sweep{i:04d}", "clip_seconds": 4.0,
            "clip_mtime": 1_790_000_000, "kills": [2.0], "kill": 2.0,
            "duration": 2.0, "pre": 1.0, "speed": "s00", "fx": [],
            "hero": False, "hero_fx": [], "camera": "c00",
            "transition": "t01", "caption": ""})
    (reels / "sweep-reel.reel.json").write_text(json.dumps({
        "version": 1, "name": "sweep-reel", "style": "hype",
        "format": "landscape", "song": "", "song_offset": 0.0,
        "intro": "", "outro": "", "grade": "", "vignette": False,
        "overlays": [], "handle": "", "music_db": 0.0, "game_db": 6.0,
        "duck": True, "saturation": 0.6, "kill_sound": True,
        "beat": 0.5, "seed": 1, "pools": {}, "shots": shots,
        "selection": [r["master"] for r in rows],
    }), encoding="utf-8")

    intro = home / "video" / "intros" / "sweep-intro.mp4"
    intro.parent.mkdir(parents=True, exist_ok=True)
    if not intro.is_file():
        subprocess.run(
            [ff, "-y", "-v", "error", "-f", "lavfi",
             "-i", "testsrc2=size=320x180:rate=30:duration=3",
             "-f", "lavfi", "-i", "sine=frequency=600:duration=3",
             "-shortest", "-pix_fmt", "yuv420p", str(intro)],
            check=True, timeout=600, creationflags=appd.NO_WINDOW)


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("sweep-home")
    port = free_port()
    appd.seed_home(home, port)
    _seed_data(home)
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


class Noise:
    """Everything a page complained about while it was being prodded."""

    def __init__(self, page):
        self.console: list[str] = []
        self.errors: list[str] = []
        self.refused: list[str] = []
        page.on("console",
                lambda m: self.console.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("response", self._response)

    def _response(self, r):
        if r.status >= 400:
            self.refused.append(f"{r.status} {r.request.method} "
                                f"{urlparse(r.url).path}")

    def drain(self) -> list[str]:
        out = ([f"console: {c}" for c in self.console]
               + [f"uncaught: {e}" for e in self.errors]
               + [f"refused: {f}" for f in self.refused])
        self.console.clear()
        self.errors.clear()
        self.refused.clear()
        return out


@pytest.fixture(scope="module")
def swept(browser, app):
    """Press every control on every page once, and report what each one said.

    ONE BROWSER FOR THE WHOLE SWEEP. Opening a context per control would spend
    most of the run starting Chromium, and the thing being looked for -- a
    control that breaks the page -- is just as visible when they are pressed
    in sequence. A control that breaks a LATER one still shows up, because
    every press is reported against its own name.
    """
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    page = ctx.new_page()
    noise = Noise(page)
    # ANY DIALOG, ACCEPTED. Pressing things on Settings makes it dirty, and
    # leaving a dirty Settings raises a beforeunload-style confirm -- which
    # nothing answers in a headless run, so the next rail click never lands
    # and the sweep stalls on whichever page came after. A sweep that cannot
    # leave a page is not a sweep.
    page.on("dialog", lambda d: d.accept())
    # ONE PLACE THAT KNOWS THE LIBRARY'S SHAPE. It is games[].folders[].clips[]
    # -- read out of webui.studio_library rather than guessed at, because a
    # guess here is a state that silently opens nothing and takes every control
    # inside it out of the sweep without saying so.
    page.add_init_script("""
        window.__sweepFirstClip = function (lib) {
          const games = (lib && lib.games) || [];
          for (const g of games) {
            for (const f of (g.folders || [])) {
              for (const c of (f.clips || [])) { if (c && c.path) return c; }
            }
          }
          return null;
        };
    """)
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_selector("#view-dash", state="attached", timeout=30_000)
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)

    # OPENING THE PAGE IS NOT OPENING THE PAGE. Most controls live inside a
    # stage, a tab or a panel that only exists once something has been chosen.
    # Measured: a seeded install shows 19 of the 190 declared controls from
    # the six top-level pages alone. These put each page into its several
    # states, and the sweep enumerates afresh in each one.
    STATES = {
        "clips": [
            ("as opened", ""),
            ("a stream picked", """
                clip_state.pick = clip_state.shown && clip_state.shown[0];
                if (clip_state.pick) { clip_renderOptions(); clip_stripOpen();
                                       clip_goStep('part'); }"""),
            ("the style stage", "clip_goStep('style')"),
            ("style, details open",
             "clip_state.style='custom'; clip_state.adv=true;"
             " clip_renderOptions(); clip_renderAdv()"),
            ("a finished run on screen", """
                clip_state.lastJob = {state:'done', folder:'sweep-run',
                                      game:'VALORANT', clips:3};
                clip_renderJob(clip_state.lastJob); clip_goStep('done');"""),
            ("a job running", """
                clip_renderJob({state:'running', percent:40, step_index:1,
                                game:'VALORANT', message:'Cutting',
                                elapsed:30, eta:60});"""),
            ("the review stage", """
                clip_openReview({folder:'sweep-run', game:'VALORANT',
                                 clips:[{name:'a', start:10, end:14,
                                         duration:4, kills:2, caption:'',
                                         voice_line:'', master:'', at:'0m10s'}]});"""),
            ("the calibration dialog", "clip_show('clip-cal-scrim', true)"),
            ("the reel maker", "window.PAGE_REEL && PAGE_REEL.open([])"),
            ("the reel maker, marks and a template", """
                window.PAGE_REEL && PAGE_REEL.open(
                    [{start: 10, end: 14, kills: 2, name: 'a'},
                     {start: 20, end: 24, kills: 1, name: 'b'}]);
                setTimeout(() => {
                  if (window.reel_state) {
                    reel_state.marks = [1.0, 2.0, 3.0];
                    reel_state.template = 'bar';
                    if (window.reel_renderSteps) reel_renderSteps();
                    if (window.reel_renderKills) reel_renderKills();
                  }
                }, 1200);"""),
            ("the reel maker, a song loaded", """
                window.PAGE_REEL && PAGE_REEL.open(
                    [{start: 10, end: 14, kills: 2, name: 'a'},
                     {start: 20, end: 24, kills: 1, name: 'b'}]);
                (async () => {
                  const r = await API.get('/api/studio/songs');
                  const one = r && r.songs && r.songs[0];
                  if (one && window.reel_useSong) {
                    const got = await API.post('/api/reel/song', {song: one.path});
                    if (got && got.song) reel_useSong(one.path, got);
                  }
                })();"""),
            ("the card reader panels", """
                clip_show('clip-read-card', true);
                clip_show('clip-cal-card', true);
                clip_show('clip-demowrap', true);
                clip_show('clip-known', true);"""),
            ("the match-video options", """
                clip_show('clip-mv', true);
                clip_show('clip-mv-outro-field', true);"""),
            ("the local-file panels", """
                clip_goStep('pick');
                clip_show('clip-local-namewrap', true);
                clip_show('clip-wrongwrap', true);"""),
        ],
        "studio": [
            ("as opened", ""),
            ("clips tab", "studio_tab && studio_tab('clips')"),
            ("timeline tab", "studio_tab && studio_tab('timeline')"),
            ("song tab", "studio_tab && studio_tab('song')"),
            ("facecam tab", "studio_tab && studio_tab('facecam')"),
            # WITH A SONG LOADED. studio_sgUseSong is what the songs list
            # calls, and the list exists so a song can be chosen without the
            # file dialog -- which is exactly what an automated run needs.
            ("song tab, a song loaded", """
                studio_tab && studio_tab('song');
                window.__sweepSong = (async () => {
                  const r = await API.get('/api/studio/songs');
                  const one = r && r.songs && r.songs[0];
                  if (one && window.studio_sgUseSong)
                      await studio_sgUseSong(one.path);
                  return !!(studio.sg && studio.sg.shape);
                })();"""),
            ("a reel open on the timeline", """
                (async () => {
                  const r = await API.get('/api/studio/library');
                  const reels = (r && r.reels) || [];
                  if (reels.length && window.studio_open)
                      await studio_open(reels[0].path || reels[0].output);
                  studio_tab && studio_tab('timeline');
                })();"""),
            # THE KILL MARKER, ON A CLIP THE APP CUT ITSELF. Reachable only
            # since S2: it used to be gated on `imported`, so none of these
            # controls rendered for a seeded run and the whole dialog was
            # outside the sweep.
            ("the kill marker, on a clip", """
                (async () => {
                  const r = await API.get('/api/studio/library');
                  /* games[].folders[].clips[] -- the shape the server
                     actually sends, read out of webui.studio_library rather
                     than guessed at. A guess here is a state that silently
                     opens nothing and takes its controls with it. */
                  const first = window.__sweepFirstClip(r);
                  if (first && window.studio_impOpen)
                      await studio_impOpen(first.path, false);
                })();"""),
            ("the kill marker, a kill marked", """
                (async () => {
                  const r = await API.get('/api/studio/library');
                  const first = window.__sweepFirstClip(r);
                  if (first && window.studio_impOpen) {
                      await studio_impOpen(first.path, false);
                      studio.imp.kills = [1.0];
                      studio.imp.sel = 0;
                      if (window.studio_impDraw) studio_impDraw();
                  }
                })();"""),
            # THE FACECAM, WHICH NEEDS A REEL OPEN. studio_fcOpen reads
            # studio.project.shots, so the tab on its own draws nothing.
            ("facecam tab, a reel open", """
                (async () => {
                  const r = await API.get('/api/studio/library');
                  const reels = (r && r.reels) || [];
                  if (reels.length && window.studio_open)
                      await studio_open(reels[0].path || reels[0].output);
                  studio_tab && studio_tab('facecam');
                  if (window.studio_fcOpen) await studio_fcOpen();
                })();"""),
            ("the intro dialog, a reel open", """
                if (studio.project && window.studio_introOpen) studio_introOpen();"""),
            ("the make dialog, a reel open", """
                if (window.studio_openMake) studio_openMake();"""),
            ("timeline, a shot selected", """
                studio_tab && studio_tab('timeline');
                if (studio.project && window.studio_select) studio_select(0);"""),
            ("the intro dialog, an intro chosen", """
                if (studio.project && window.studio_introOpen) {
                  studio_introOpen();
                  setTimeout(() => {
                    /* `list`, not `lib`. Read from the live object rather
                       than guessed: studio.intro is
                       {list, pick, seconds, hasAudio, start, end, audio,
                        fit, tick}. */
                    const lib = studio.intro && studio.intro.list;
                    const one = lib && lib[0];
                    if (one && window.studio_introChoose)
                        studio_introChoose(one.path || one);
                  }, 1500);
                }"""),
            ("the make dialog, choosing a part", """
                if (window.studio_openMake) {
                  studio_openMake();
                  setTimeout(() => {
                    if (studio.mk) { studio.mk.mode = 'part'; studio_mkDraw(); }
                  }, 1500);
                }"""),
            ("the song tab, a mark made", """
                studio_tab && studio_tab('song');
                setTimeout(() => {
                  if (studio.sg && studio.sg.shape && window.studio_sgMark) {
                    studio.sg.marks = [2.0, 4.0];
                    studio_sgMark();
                  }
                }, 1500);"""),
            ("facecam, a source chosen", """
                studio_tab && studio_tab('facecam');
                if (studio.project && window.studio_change)
                    studio_change(pr => { pr.cam = Object.assign({}, pr.cam,
                        {source: 'inset', box: [0.02, 0.6, 0.25, 0.38]}); },
                        'Facecam');"""),
        ] + [
            # EVERY DIALOG, OPENED DIRECTLY. Each holds five to fifteen
            # controls that exist nowhere else, and driving the flow that
            # normally opens one would mean a reel built, a song downloaded
            # or a file chosen from a native picker. The scrim is shown the
            # same way the page shows it.
            (f"the {scrim} dialog",
             f"studio_show('studio-{scrim}-scrim', true)")
            for scrim in ("make", "imp", "intro", "del", "rdel", "yt",
                          "preview")
        ],
        "settings": [("as opened", "")] + [
            # Settings paints one section at a time, so twelve thirteenths of
            # it is never on screen at once.
            (f"the {sec} section",
             f"set_showSection('{sec}')")
            for sec in ("appearance", "stream", "obs", "timing", "safety",
                        "titles", "thumbnail", "screens", "record", "clips",
                        "logging", "advanced")
        ],
    }

    results: dict[str, list[str]] = {}
    for page_id in PAGES:
        # Through the shell's own router rather than the rail button. A modal
        # left open by the page before this one covers the rail, and the point
        # here is to reach the next page -- whether the rail is clickable is
        # its own question, asked by test_ui_playwright.
        page.evaluate("(id) => go(id)", page_id)
        # ATTACHED, not visible. A view can carry is-active while its content
        # is still empty -- the dashboard does on a fresh install -- and
        # Playwright calls a zero-height element invisible, so waiting for
        # visibility waits for data rather than for the page switch.
        page.wait_for_selector(f"#view-{page_id}.is-active", state="attached",
                               timeout=20_000)
        page.wait_for_timeout(1200)
        results[f"page:{page_id}"] = noise.drain()

        for state_name, setup in STATES.get(page_id, [("as opened", "")]):
            if setup:
                try:
                    page.evaluate(f"() => {{ {setup} }}")
                    # HOW LONG TO WAIT IS A PROPERTY OF THE SETUP, not of
                    # its name. This keyed off the word "loaded" in the label,
                    # so four states that settle asynchronously were given
                    # 700ms while their own setTimeout fired at 1500 -- the
                    # sweep enumerated the surface before the thing it had
                    # asked for arrived, and thirty-one controls stayed
                    # invisible for no better reason than a label.
                    slow = ("setTimeout" in setup or "await" in setup
                            or "async" in setup)
                    page.wait_for_timeout(4500 if slow else 700)
                except Exception as e:              # noqa: BLE001
                    results[f"{page_id}:[{state_name}]"] = [
                        f"could not be reached: {str(e).splitlines()[0][:110]}"]
                    continue
                noise.drain()      # getting there is not what is under test

            _sweep_state(page, page_id, state_name, noise, results,
                         app["base"])

        # Back to a known page: a control may have opened a panel or moved the
        # stage on, and the next page is looked for from here.
        page.evaluate("(id) => go(id)", page_id)
        page.wait_for_timeout(300)
        noise.drain()

    yield results
    ctx.close()


def _sweep_state(page, page_id, state_name, noise, results, base) -> None:
    """Press everything on screen right now, recording what each one said."""
    last_pressed = "(nothing yet)"
    if True:
        # Only what is actually on screen. A control inside a card that has not
        # applied yet is not broken for being absent, and clicking a hidden
        # element would be asserting something nobody can do.
        tokens = page.evaluate("""(id) => {
            const out = [];
            document.querySelectorAll('#view-' + id + ' [data-act]')
                .forEach(e => {
                    const r = e.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && !e.disabled)
                        out.push(e.getAttribute('data-act'));
                });
            return [...new Set(out)];
        }""", page_id)

        for token in tokens:
            why = _skip_reason(token)
            if why or any(h in token for h in PICKER_HINTS):
                results[f"{page_id} [{state_name}]:{token}"] = []      # deliberately unpressed
                continue
            sel = f'#view-{page_id} [data-act="{token}"]'
            try:
                el = page.locator(sel).first
                if not el.is_visible() or el.is_disabled():
                    results[f"{page_id} [{state_name}]:{token}"] = []
                    continue
                # STILL THERE? Asked before every press, because the press
                # before this one is the suspect. An app that has stopped
                # answering is blocked on something -- a modal window is the
                # way that has actually happened -- and carrying on would
                # spend the rest of the run waiting on pages that will never
                # load, with the window sitting on somebody's screen. Better
                # to stop at the control that did it and name it.
                assert appd.answering(base), (
                    f"the app stopped answering after {last_pressed!r} on "
                    f"{page_id} [{state_name}]. Something is blocking its "
                    f"request thread -- a native window is the usual cause, "
                    f"and AUTOSTREAM_NO_DIALOGS is meant to prevent it.")
                last_pressed = token
                try:
                    el.click(timeout=3000, no_wait_after=True)
                except Exception:                       # noqa: BLE001
                    # POINTER FIRST, DOM SECOND. Playwright refuses a pointer
                    # click on anything it judges unstable or covered -- a
                    # control inside a panel that is still animating, or under
                    # a tooltip. That is a real finding about the pointer, and
                    # it is NOT a finding about the handler, which is what a
                    # sweep is asking about. So the handler is run directly
                    # and the control still gets its answer recorded.
                    page.eval_on_selector(sel, "e => e.click()")
                page.wait_for_timeout(350)
            except Exception as e:                      # noqa: BLE001
                # Neither worked. Reported rather than raised, so the sweep
                # finishes and shows everything it found at once.
                results[f"{page_id} [{state_name}]:{token}"] = noise.drain() + [
                    f"could not be pressed at all: {str(e).splitlines()[0][:110]}"]
                continue
            results[f"{page_id} [{state_name}]:{token}"] = noise.drain()


# How many distinct controls the sweep reaches on a seeded install. A FLOOR,
# not a target: it exists so that a change which quietly stops a page
# rendering -- and so stops its controls being swept -- fails here rather than
# passing with less and less under test. Raise it when coverage genuinely
# improves; never lower it without saying what stopped being reachable.
# MEASURED, not chosen: 117 of the 190 controls the source declares, on an
# install seeded with a recording, a finished run, a song, an intro and a reel.
# It got there in stages -- 43 with nothing seeded, 86 once the dialogs were
# opened, 99 with a song, 111 with a reel project, 117 with a shot selected,
# and 122 once the kill marker could be opened on a clip the app had cut
# itself. That last one was not a sweep change: the marker was gated on
# `imported` until S2, so the whole dialog was unreachable for a seeded run
# and its controls could not have been swept however the states were written.
#
# The honest account of the 73 still out of reach is in docs/UI-SCENARIOS.md
# rather than hidden behind a comfortable number here.
#
# A FLOOR, not a target. It exists so that a change which quietly stops a page
# rendering fails here rather than passing with less and less under test.
REACHED_FLOOR = 122


def _reached(swept) -> set:
    return {k.split(":", 1)[1] for k in swept
            if ":" in k and not k.startswith("page:")
            and not k.endswith("]")}


def test_the_sweep_writes_down_what_it_reached(swept, tmp_path_factory):
    """THE REPORT, written every run.

    The catalogue in docs/UI-SCENARIOS.md is only honest if the number in it
    is measured, and measuring it by reading a failing assertion is how a
    number goes stale. This writes reached and unreached to a file next to
    the run, so extending the sweep is a matter of reading a list rather than
    guessing which control to chase next.
    """
    import json

    declared = set(surface.ui_actions())
    reached = _reached(swept)
    out = tmp_path_factory.getbasetemp() / "ui-sweep-coverage.json"
    out.write_text(json.dumps({
        "declared": len(declared),
        "reached": len(reached),
        "excused": sorted(DESTRUCTIVE),
        "reached_controls": sorted(reached),
        "unreached_controls": sorted(declared - reached - set(DESTRUCTIVE)),
    }, indent=2), encoding="utf-8")
    print(nl + "UI sweep: reached %d of %d declared controls "
          "(%d excused). Full report: %s"
          % (len(reached), len(declared), len(DESTRUCTIVE), out))
    assert reached, "nothing at all was reached"


def test_the_sweep_actually_sweeps(swept):
    """A sweep that found no controls would pass every test below it."""
    reached = _reached(swept)
    assert len(reached) >= REACHED_FLOOR, (
        "only %d distinct controls were reached, against a floor of %d. "
        "Either a page stopped rendering, or a state in STATES stopped "
        "working. Reached: %s"
        % (len(reached), REACHED_FLOOR, sorted(reached)))


@pytest.mark.parametrize("page_id", PAGES)
def test_each_page_opens_in_silence(swept, page_id):
    assert swept.get(f"page:{page_id}") == [], (
        f"opening {page_id} produced:\n  "
        + "\n  ".join(swept[f"page:{page_id}"]))


def test_no_control_breaks_its_page(swept):
    """Every control that could be pressed, pressed -- and what it said.

    Reported in one assertion rather than one per control, because a page with
    three broken buttons should fail once with all three named, not three
    times with one each.
    """
    bad = {k: v for k, v in swept.items()
           if v and not k.startswith("page:")}
    assert bad == {}, (
        "pressing these produced something:\n  "
        + "\n  ".join(f"{k}: {'; '.join(v)}" for k, v in sorted(bad.items())))


def test_every_control_the_source_declares_is_either_swept_or_excused():
    """THE DRIFT GUARD. The sweep presses what is on screen, so a control that
    never renders is silently never tested. This does not fix that -- it makes
    it countable, and fails if the share that cannot be reached grows.
    """
    declared = set(surface.ui_actions())
    assert declared, "no controls were found in the source at all"
    excused = set(DESTRUCTIVE)
    assert excused <= declared, (
        "DESTRUCTIVE names controls that no longer exist: "
        + ", ".join(sorted(excused - declared)))
