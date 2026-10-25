r"""Tier 7: the Song tab's Hits lane -- every kick, snare and hat, and the song's parts.

clips/rhythm.py reads a song as layers so a reel's cuts, camera and effects can
be timed to more than one beat grid. Offline tests prove the reading; what only
a browser shows is that the page asks for it, draws it where the song is, and
lets it be hidden like every other lane. The song is a drum loop written here
-- kick, clap, hats -- so there is something in each row to draw.
"""
from __future__ import annotations

import math
import struct
import wave
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

    home = tmp_path_factory.mktemp("hits")
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    base, proc = appd.start(home, port)
    try:
        yield {"base": base, "home": home, "token": appd.TOKEN}
    finally:
        appd.stop(base, proc)


def drum_loop(path: Path, seconds: float = 24.0, bpm: float = 120.0, rate: int = 22050) -> Path:
    """Kick on 1 and 3, a clap on 2 and 4, hats on the eighths; the first
    eight seconds quiet and without kick, so the song has parts to find."""
    beat = 60.0 / bpm
    n = int(seconds * rate)
    out = [0.0] * n
    seed = 1

    def noise():
        nonlocal seed
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        return seed / 0x3FFFFFFF - 1.0

    def add(t0, length, fn, gain):
        a = int(t0 * rate)
        for i in range(int(length * rate)):
            if a + i < n:
                out[a + i] += gain * fn(i / rate)
    i = 0
    while i * beat < seconds:
        t = i * beat
        g = 0.2 if t < 8.0 else 1.0
        if i % 2 == 0 and t >= 8.0:
            add(t, 0.25, lambda s: math.sin(2 * math.pi * (50 + 100 * math.exp(-s / 0.03)) * s) * math.exp(-s / 0.12), 0.8)
        if i % 2 == 1:
            add(t, 0.15, lambda s: noise() * math.exp(-s / 0.04), 0.4 * g)
        for h in (0.0, beat / 2):
            add(t + h, 0.04, lambda s: (noise() - noise()) * math.exp(-s / 0.008), 0.15 * g)
        i += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v)) * 20000)) for v in out))
    return path


PROJECT = """() => {
  studio.project = {
    version: 1, name: 'hits', style: 'montage', format: 'landscape',
    song: '', song_offset: 0, beat: 0.5, step: 0.5, intro: 'i00', outro: 'e12', grade: 'g01',
    vignette: false, overlays: [], handle: '', music_db: 0, game_db: 0, duck: false,
    saturation: 1, shots: [], lyrics: {look: 'off'}, cam: {source: 'none'}};
  studio.derived = {length: 10, beat: 0.5, bpm: 120, beats: [], kills: [], selection: [],
                    lead_in: 0, intro_clip: null, shots: []};
  studio_tab('song');
  return true;
}"""


@pytest.fixture
def pg(browser, app):
    song = drum_loop(Path(app["home"]) / "video" / "songs" / "drum loop.wav")
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    trouble: list[str] = []
    page.on("console", lambda m: trouble.append(m.text)
            if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: trouble.append(str(e)))
    page.goto(f"{app['base']}/?k={app['token']}", wait_until="domcontentloaded")
    page.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
    page.evaluate("() => go('studio')")
    page.wait_for_selector("#view-studio.is-active", state="attached")
    page.wait_for_timeout(900)
    page.evaluate(PROJECT)
    page.evaluate("(p) => studio_sgUseSong(p)", str(song))
    page.wait_for_function("studio.sv && studio.sv.meta", timeout=60_000)
    page.check("#studio-sg-adv")    # the lanes are under Advanced, off until asked for
    page.song = song
    yield page
    assert not trouble, trouble
    ctx.close()


def _ink(pg, top: float, bottom: float) -> int:
    """Painted pixels in a horizontal stripe of the Hits canvas (fractions of its height)."""
    return pg.evaluate("""([a, b]) => {
        const c = document.querySelector('#studio-sg-lanes .studio-sg-lane[data-lane="hits"] canvas');
        const x = c.getContext('2d'), y0 = Math.floor(c.height * a), y1 = Math.ceil(c.height * b);
        const d = x.getImageData(0, y0, c.width, y1 - y0).data;
        let n = 0;
        for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
        return n; }""", [top, bottom])


def test_the_hits_are_read_and_sent_with_the_song(pg):
    r = pg.evaluate("studio.sv.meta.rhythm")
    assert r, "the songview answer carries no rhythm"
    assert abs(r["beat"] - 0.5) < 0.01
    for name in ("kick", "snare", "hats"):
        assert len(r["layers"][name]["times"]) >= 10, name
    # no kick in the quiet opening
    assert all(t > 7.5 for t in r["layers"]["kick"]["times"])
    kinds = {s["kind"] for s in r["sections"]}
    assert len(r["sections"]) >= 2 and kinds, r["sections"]
    assert "cues" not in r, "the planner's cues are not the page's to carry"


def test_the_lane_draws_every_row_where_the_song_is(pg):
    assert pg.is_visible('#studio-sg-lanes .studio-sg-lane[data-lane="hits"]')
    # put the playhead in the loud part so all three rows have hits in view
    pg.evaluate("() => { const a = document.getElementById('studio-sg-audio'); a.currentTime = 14; }")
    pg.wait_for_timeout(300)
    pg.evaluate("studio_svDraw()")
    strip = _ink(pg, 0.0, 0.18)
    kick = _ink(pg, 0.24, 0.45)
    snare = _ink(pg, 0.48, 0.70)
    hats = _ink(pg, 0.73, 0.97)
    assert strip > 0, "the song's parts are not drawn"
    assert kick > 0 and snare > 0 and hats > 0, (kick, snare, hats)


def test_the_lane_hides_and_comes_back(pg):
    toggle = '#studio-sg-toggles [data-act="studio-sg-lane"][data-lane="hits"]'
    assert pg.get_attribute(toggle, "aria-pressed") == "true"
    pg.click(toggle)
    assert not pg.is_visible('#studio-sg-lanes .studio-sg-lane[data-lane="hits"]')
    pg.click(toggle)
    assert pg.is_visible('#studio-sg-lanes .studio-sg-lane[data-lane="hits"]')
