"""'Since last time' on the idle Dashboard: what is new since you last looked.

A clip is new until the Clips or Studio page has shown it once. When you last
looked is kept in its own small file (webui.SEEN_FILE), not in state.json:
the engine owns state.json and rewrites it from memory, which would put the
stamp back to zero on its next save.
"""
from __future__ import annotations

from autostream import webui


def lib(*clips, reels=()):
    return {"ok": True, "games": [{"game": "VALORANT", "folders": [
        {"folder": "f", "label": "Tonight", "when": "", "clips": list(clips)}]}],
        "reels": list(reels)}


def test_new_means_newer_than_the_stamp():
    times = {"a.mp4": 100.0, "b.mp4": 200.0, "c.mp4": 300.0}
    got = webui.since_summary(lib({"path": "a.mp4"}, {"path": "b.mp4"}, {"path": "c.mp4"}),
                              seen=150.0, mtime=times.get)
    assert got["clips_new"] == 2
    assert got["since"] == 150.0


def test_reels_made_since_are_listed_newest_first_three_at_most():
    times = {f"r{i}.mp4": float(i * 100) for i in range(6)}
    reels = [{"name": f"r{i}", "path": f"r{i}.mp4"} for i in range(6)]
    got = webui.since_summary(lib(reels=reels), seen=150.0, mtime=times.get)
    assert [r["name"] for r in got["reels"]] == ["r5", "r4", "r3"]


def test_a_file_that_has_gone_is_not_new():
    got = webui.since_summary(lib({"path": "gone.mp4"}), seen=0.0, mtime=lambda p: None)
    assert got["clips_new"] == 0


def test_never_looked_means_nothing_is_new_yet():
    got = webui.since_summary(lib({"path": "a.mp4"}), seen=None, mtime=lambda p: 1e12)
    assert got["clips_new"] == 0 and got["since"] is None


def test_the_stamp_survives_a_restart(tmp_path):
    f = tmp_path / "ui-seen.json"
    assert webui.seen_get(f) is None
    webui.seen_stamp(f, 1234.5)
    assert webui.seen_get(f) == 1234.5


def test_two_pages_stamping_at_once_never_raise(tmp_path):
    """The Studio and the Clips page both stamp on show, and the browser tier
    caught them racing: one shared .tmp name, and os.replace on Windows
    refusing a file the other write still held -- a 500 from /api/seen."""
    import threading
    f = tmp_path / "ui-seen.json"
    errors = []

    def go(i):
        try:
            for j in range(40):
                webui.seen_stamp(f, float(i * 1000 + j))
        except Exception as e:                      # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors, errors
    assert webui.seen_get(f) is not None


def test_a_damaged_stamp_reads_as_never(tmp_path):
    f = tmp_path / "ui-seen.json"
    f.write_text("{not json", encoding="utf-8")
    assert webui.seen_get(f) is None


def test_the_page_calls_both_routes():
    from autostream import ui
    assert "'/api/since'" in ui.JS and "'/api/seen'" in ui.JS
