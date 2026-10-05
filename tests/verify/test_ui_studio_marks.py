r"""Tier 7: adding clips in a batch, and correcting any clip's kills.

TWO THINGS ASKED FOR DIRECTLY, both confirmed in the source rather than
guessed at before they were built.

S1  `studio_impAdd` took one file and stopped, so somebody with a folder of
    twenty did the whole dance twenty times: open the dialog, choose one,
    wait, mark the kills, save, press Add again. The picker could always
    offer more than one -- Tk has `askopenfilenames` beside
    `askopenfilename` -- and nothing ever asked it to.

S2  The kill marker was gated on `c.imported`, which is set only for clips
    that came in through Add your own clip. A clip AutoStream cut for itself
    had no way back into the marker at all: a kill the detector put half a
    second late could not be corrected, and a clip could not be retitled.
    The marker never cared where a clip came from -- `studio_impOpen(path)`
    takes a path. What was missing was the way in.
"""
from __future__ import annotations

import json

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

    home = tmp_path_factory.mktemp("marks")
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
    # THE STUB CLIPS IN THIS FILE ARE NOT VIDEOS. Two tests write a one-byte
    # a.mp4 to give the server a manifest row to answer about, and the Studio
    # library then asks for a thumbnail of it and is correctly refused. That
    # 400 is the server being right; counting it as "something went wrong"
    # would make the watchdog below report the test's own fixture.
    page.on("console",
            lambda m: trouble.append(m.text)
            if m.type == "error" and "studio/thumb" not in m.text
            and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.wait_for_timeout(1200)
    page.trouble = trouble
    page.ctx = ctx
    yield page
    ctx.close()


# ------------------------------------------- S2: the Edit button exists

def _tile(pg, **clip):
    """Render one library tile and report what it offers."""
    row = {"id": "c1", "name": "a.mp4", "path": "C:/vid/clips/a.mp4",
           "duration": 20, "kills": [2.0], "kill_count": 1, "caption": "",
           "labels": [], "at": "00:01", "rank": 1, "game": "VALORANT",
           "fav": False, "vertical": "", "start": 0}
    row.update(clip)
    return pg.evaluate(
        """(c) => {
             const host = document.createElement('div');
             host.innerHTML = studio_tile(c, 0);
             const b = host.querySelector('[data-act="studio-imp-edit"]');
             return {edit: !!b, label: b ? b.textContent.trim() : '',
                     title: b ? b.getAttribute('title') : ''};
           }""", row)


def test_a_clip_autostream_cut_can_be_edited(pg):
    """THE REPORTED GAP: "the kills marker page is only visible once if I
    want to edit a clip later that option should also be there"."""
    got = _tile(pg, imported=False)
    assert got["edit"] is True, "a detected clip still has no way into the marker"
    assert got["label"] == "Edit"
    assert "Correct" in got["title"], got["title"]


def test_an_imported_clip_still_can(pg):
    got = _tile(pg, imported=True)
    assert got["edit"] is True
    assert got["label"] == "Edit"


def test_one_that_has_never_been_marked_says_so(pg):
    """An import with no kills yet is a different job from correcting one,
    and the button says which."""
    got = _tile(pg, imported=True, unmarked=True)
    assert got["label"] == "Mark kills"


def test_nothing_threw_rendering_them(pg):
    _tile(pg, imported=False)
    _tile(pg, imported=True, unmarked=True)
    assert pg.trouble == []


# ------------------------------------------------- S2: through the server

def test_the_server_opens_a_clip_whatever_made_it(pg, app):
    """`uploads.info` answered only for import folders. The guard that has to
    survive is the one about the clips folder, not the one about who cut
    it."""
    home = app["home"]
    run = home / "video" / "clips" / "2026-09-01_VALORANT_shortform"
    (run / "clips").mkdir(parents=True, exist_ok=True)
    clip = run / "clips" / "a.mp4"
    clip.write_bytes(b"x")
    (run / "clips.json").write_text(json.dumps({
        "game": "VALORANT",
        "clips": [{"name": "A", "master": str(clip), "start": 2500.0,
                   "end": 2520.0, "duration": 20.0}]}), encoding="utf-8")
    (run / "session.json").write_text(json.dumps({
        "game": "VALORANT", "kills": [{"time": 2504.0}]}), encoding="utf-8")

    got = pg.evaluate(
        """async (p) => await API.post('/api/studio/import/info', {path: p})""",
        str(clip))
    assert got["ok"] is True, got
    # RECORDING SECONDS BECOME CLIP SECONDS. A clip starting 42 minutes in
    # would otherwise open with its first mark at 2504, off the end of a
    # twenty-second clip.
    assert got["kills"] == [4.0], got["kills"]
    assert got["imported"] is False


def test_a_correction_sticks_and_leaves_the_run_alone(pg, app):
    """A run's session.json describes the whole recording and every clip cut
    from it reads its pips out of it. Writing one clip's correction there
    would move all forty."""
    home = app["home"]
    run = home / "video" / "clips" / "2026-09-02_VALORANT_shortform"
    (run / "clips").mkdir(parents=True, exist_ok=True)
    clip = run / "clips" / "b.mp4"
    clip.write_bytes(b"x")
    (run / "clips.json").write_text(json.dumps({
        "game": "VALORANT",
        "clips": [{"name": "B", "master": str(clip), "start": 100.0,
                   "end": 120.0, "duration": 20.0}]}), encoding="utf-8")
    (run / "session.json").write_text(json.dumps({
        "game": "VALORANT", "kills": [{"time": 104.0}]}), encoding="utf-8")

    saved = pg.evaluate(
        """async (p) => await API.post('/api/studio/import/save',
                                       {path: p, kills: [6.5]})""", str(clip))
    assert saved["ok"] is True, saved

    again = pg.evaluate(
        """async (p) => await API.post('/api/studio/import/info', {path: p})""",
        str(clip))
    assert again["kills"] == [6.5]

    sess = json.loads((run / "session.json").read_text(encoding="utf-8"))
    assert sess["kills"] == [{"time": 104.0}], (
        "a correction to one clip rewrote the recording's kill list")


def test_a_path_outside_the_clips_folder_is_still_refused(pg, app):
    got = pg.evaluate(
        """async (p) => await API.post('/api/studio/import/info', {path: p})""",
        str(app["home"] / "elsewhere" / "clips" / "a.mp4"))
    assert got["ok"] is False


# ------------------------------------------- S1: the picker offers several

def test_the_studio_asks_for_more_than_one_file(pg):
    """The one line that was missing. Asserted on the request the page makes,
    because the dialog itself cannot be opened in a test -- and must not be."""
    sent = pg.evaluate(
        """async () => {
             const seen = [];
             const real = API.post;
             API.post = async (path, body) => {
               seen.push([path, body]);
               if (path === '/api/clips/pick') return {ok: true, paths: []};
               return {ok: false};
             };
             try { await studio_impAdd(); } finally { API.post = real; }
             return seen;
           }""")
    assert sent, "studio_impAdd sent nothing"
    path, body = sent[0]
    assert path == "/api/clips/pick"
    assert body.get("multi") is True, body


def test_several_files_are_each_imported(pg):
    sent = pg.evaluate(
        """async () => {
             const seen = [];
             const real = API.post;
             API.post = async (path, body) => {
               seen.push([path, body]);
               if (path === '/api/clips/pick') {
                 return {ok: true, paths: ['C:/a.mp4', 'C:/b.mp4', 'C:/c.mp4']};
               }
               if (path === '/api/studio/import') {
                 return {ok: true, clip: {path: 'C:/in/' + body.path.slice(3)}};
               }
               return {ok: true, kills: [], seconds: 10, presets: []};
             };
             try { await studio_impAdd(); } finally { API.post = real; }
             return seen.filter(s => s[0] === '/api/studio/import')
                        .map(s => s[1].path);
           }""")
    assert sent == ["C:/a.mp4", "C:/b.mp4", "C:/c.mp4"], sent


def test_one_bad_file_does_not_stop_the_batch(pg):
    """Nineteen imported and the twentieth refused is a far better outcome
    than nothing imported and one error about a file nobody can see."""
    got = pg.evaluate(
        """async () => {
             const real = API.post;
             let imported = 0;
             API.post = async (path, body) => {
               if (path === '/api/clips/pick') {
                 return {ok: true, paths: ['C:/a.mp4', 'C:/bad.mp4', 'C:/c.mp4']};
               }
               if (path === '/api/studio/import') {
                 if (body.path.indexOf('bad') >= 0) {
                   return {ok: false, error: 'nope'};
                 }
                 imported++;
                 return {ok: true, clip: {path: body.path}};
               }
               return {ok: true, kills: [], seconds: 10, presets: []};
             };
             try { await studio_impAdd(); } finally { API.post = real; }
             return imported;
           }""")
    assert got == 2, got


def test_the_whole_batch_is_kept_not_just_the_rest(pg):
    """It used to be a queue that Save ate, so by the third clip the batch
    was two long and there was no way back to the first. It is a list with a
    position now -- see test_ui_studio_batch for the walking."""
    queued = pg.evaluate(
        """async () => {
             const real = API.post;
             API.post = async (path, body) => {
               if (path === '/api/clips/pick') {
                 return {ok: true, paths: ['C:/a.mp4', 'C:/b.mp4', 'C:/c.mp4']};
               }
               if (path === '/api/studio/import') {
                 return {ok: true, clip: {path: body.path}};
               }
               return {ok: true, kills: [], seconds: 10, presets: []};
             };
             try { await studio_impAdd(); } finally { API.post = real; }
             return {batch: (studio.imp.batch || []).slice(),
                     at: studio.imp.at | 0};
           }""")
    assert queued["batch"] == ["C:/a.mp4", "C:/b.mp4", "C:/c.mp4"], queued
    assert queued["at"] == 0, "it did not start on the first clip"


def test_closing_the_marker_drops_the_rest_of_the_batch(pg):
    """A queue that survived being dismissed would reopen a dialog the user
    had just shut, which is the one thing a Close button must never do."""
    left = pg.evaluate(
        """() => {
             studio.imp.batch = ['C:/a.mp4', 'C:/b.mp4', 'C:/c.mp4'];
             studio.imp.at = 1;
             studio.imp.dirty = false;
             studio_impClose(true);
             return (studio.imp.batch || []).length;
           }""")
    assert left == 0


def test_nothing_threw_through_a_batch(pg):
    pg.evaluate(
        """async () => {
             const real = API.post;
             API.post = async (path, body) => {
               if (path === '/api/clips/pick') return {ok: true, paths: []};
               return {ok: true};
             };
             try { await studio_impAdd(); } finally { API.post = real; }
           }""")
    assert pg.trouble == []
