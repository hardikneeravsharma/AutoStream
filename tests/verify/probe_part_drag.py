r"""Probe: drag the song part on the timeline's Song tab and see what the marks do.

THE REPORT THIS REPRODUCES (2026-10-23, Hardik's screen recording): on the Song
tab he dragged the part from 0:00-0:44 to 0:59-2:07. The 21 kill-mark diamonds
kept the same offsets from the part's start, so they no longer sat on the new
section's beats, covered only 40% of the longer part, and nothing on the page
said the timing was stale.

Not a test -- the file name keeps pytest away from it. It is kept because it is
how the bug was seen before it was fixed, and running it again is how the fix
is seen working: it prints what the marks did and what the page said.

    $env:AUTOSTREAM_VERIFY_SOURCE=1
    .\.venv\Scripts\python.exe tests\verify\probe_part_drag.py

It starts this checkout against a throwaway home on a free port, so it is safe
while the real app is open, and opens no window: Chromium runs headless.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent), str(HERE.parents[1])]

import appd  # noqa: E402
from fakes import free_port  # noqa: E402

BEAT = 0.5                                  # the click track is 120 BPM


def seed(home: Path, n: int = 10) -> tuple[list[str], Path]:
    """`n` real ten-second clips with a kill in the middle, and a 150 s song."""
    from autostream.clips.tools import binary

    ff = binary("ffmpeg")
    run = home / "video" / "clips" / "2026-10-23_1200_VALORANT"
    (run / "clips").mkdir(parents=True, exist_ok=True)
    rows, paths = [], []
    for i in range(n):
        clip = run / "clips" / f"probe_{i}.mp4"
        subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=320x180:rate=30:duration=10",
                        "-f", "lavfi", "-i", f"sine=frequency={300 + 40 * i}:duration=10",
                        "-shortest", "-pix_fmt", "yuv420p", str(clip)],
                       check=True, timeout=180, creationflags=appd.NO_WINDOW)
        rows.append({"rank": i + 1, "start": 20.0 * (i + 1), "end": 20.0 * (i + 1) + 10, "duration": 10,
                     "kills": 1, "name": clip.stem, "master": str(clip), "vertical": "",
                     "caption": "", "tags": [], "at": ""})
        paths.append(str(clip))
    (run / "clips.json").write_text(json.dumps({"game": "VALORANT", "clips": rows}))
    (run / "session.json").write_text(json.dumps(
        {"game": "VALORANT", "kills": [{"time": 20.0 * (i + 1) + 5} for i in range(n)]}))
    song = appd.click_track(home / "video" / "songs" / "probe song.wav", seconds=150.0, bpm=120.0)
    return paths, song


def main() -> int:
    from playwright.sync_api import sync_playwright

    import tempfile
    home = Path(tempfile.mkdtemp(prefix="probe-part-"))
    port = free_port()
    appd.seed_home(home, port, rules={"setup_done": True})
    clips, song = seed(home)
    base, proc = appd.start(home, port)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1500, "height": 1000})
            errors: list[str] = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(f"{base}/?k={appd.TOKEN}", wait_until="domcontentloaded")
            pg.wait_for_function("typeof API !== 'undefined'", timeout=30_000)
            pg.evaluate("() => go('studio')")
            pg.wait_for_selector("#view-studio.is-active", state="attached")
            pg.wait_for_timeout(800)
            ok = pg.evaluate("""async (a) => {
                const r = await API.post('/api/studio/plan', {clips: a.clips, style: 'montage', song: a.song,
                    format: 'landscape', name: 'probe', part_start: 0, part_end: 44, dry: true,
                    shaping: {fill: 'part'}});
                if (!r || !r.ok) return r;
                studio_setProject(r.project, r.derived, r.notes, r.song);
                studio_tab('song');
                return {ok: true};
            }""", {"clips": clips, "song": str(song)})
            assert ok.get("ok"), ok
            pg.wait_for_selector("#studio-sg-body:not(.hide)", state="attached", timeout=30_000)
            pg.wait_for_timeout(500)
            before = pg.evaluate("({start: studio.sg.start, end: studio.sg.end, marks: studio.sg.marks.slice(),"
                                 " song: studio.sg.shape.seconds})")
            print("before:", round(before["start"], 2), "->", round(before["end"], 2),
                  len(before["marks"]), "marks:", [round(m, 2) for m in before["marks"]])

            # Drag the lit part on the whole-song overview 59 s to the right...
            ov = pg.locator("#studio-sg-overview").bounding_box()
            px = lambda t: ov["x"] + t / before["song"] * ov["width"]       # noqa: E731
            y = ov["y"] + ov["height"] / 2
            grab = (before["start"] + before["end"]) / 2
            pg.mouse.move(px(grab), y)
            pg.mouse.down()
            pg.mouse.move(px(grab + 59 - before["start"]), y, steps=12)
            pg.mouse.up()
            # ...then its end edge out to 2:07.
            mid = pg.evaluate("[studio.sg.start, studio.sg.end]")
            pg.mouse.move(px(mid[1]), y)
            pg.mouse.down()
            pg.mouse.move(px(127), y, steps=12)
            pg.mouse.up()
            pg.wait_for_timeout(300)
            after = pg.evaluate("({start: studio.sg.start, end: studio.sg.end, marks: studio.sg.marks.slice()})")
            print("after: ", round(after["start"], 2), "->", round(after["end"], 2),
                  len(after["marks"]), "marks:", [round(m, 2) for m in after["marks"]])
            moved = [round(a - b_, 3) for a, b_ in zip(after["marks"], before["marks"])]
            print("each mark moved by:", sorted(set(moved)))
            off = [m for m in after["marks"] if abs((m / BEAT) - round(m / BEAT)) > 0.02]
            print("marks off the new section's beats:", len(off), "of", len(after["marks"]))
            span = (max(after["marks"]) - after["start"]) / (after["end"] - after["start"]) if after["marks"] else 0
            print(f"the marks cover {span:.0%} of the part")
            said = pg.evaluate("document.getElementById('studio-pane-song').innerText")
            print("the page says the timing is stale:", "stale" in said.lower() or "needs updating" in said.lower())
            print("render allowed while stale:", not pg.evaluate("studio_el('studio-render-btn').disabled"))
            print("page errors:", errors)
            b.close()
    finally:
        appd.stop(base, proc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
