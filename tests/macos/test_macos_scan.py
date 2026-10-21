"""One decode for the VALORANT feed and the kill emblem (macos/scan.py, #212).

The contract is that nothing downstream can tell: each branch of the shared
decode must be byte-identical to the standalone reader it replaces, and the
emblem onsets handed to killmark.scan must be the ones its own chunks find.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from autostream.clips import killmark, tools
from autostream.clips import valorant_feed as vf
from autostream.macos import scan

BAND = (0.5, 0.07, 1.0, 0.235)          # the VALORANT profile's feed band


@pytest.fixture(autouse=True)
def _clean():
    scan.forget()
    yield
    scan.forget()


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    try:
        ff = tools.binary("ffmpeg")
    except tools.FfmpegMissing:
        pytest.skip("no ffmpeg")
    out = tmp_path_factory.mktemp("scan") / "rec.mp4"
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=60:d=40",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "240",
                    "-pix_fmt", "yuv420p", str(out)], check=True, timeout=300)
    return out


def _shared(video, start, dur, end, fps=2.0):
    shape = vf.band_shape(video, BAND)
    gen = scan.frames_and_emblem(video, BAND, start, dur, fps, shape, end,
                                 killmark.spec_for("VALORANT"))
    frames = []
    try:
        while True:
            frames.append(next(gen)[1].copy())
    except StopIteration as e:
        return frames, e.value, shape


@pytest.mark.skipif(sys.platform == "win32", reason="pass_fds pipes are POSIX")
@pytest.mark.parametrize("start,dur,end", [(0.0, 10.0, 40.0), (7.25, 12.0, 40.0), (20.0, 15.0, 35.0)])
def test_both_branches_are_byte_identical_to_the_standalone_readers(video, start, dur, end):
    feed, emblem, shape = _shared(video, start, dur, end)
    solo = [f.copy() for _, f in vf._raw_frames(video, BAND, start, dur, 2.0, shape, False)]
    assert len(feed) == len(solo) and all(np.array_equal(a, b) for a, b in zip(feed, solo))
    alone = killmark._region(video, killmark.spec_for("VALORANT"), tools.binary("ffmpeg"),
                             t0=start, seconds=min(dur + 1.0, end - start), fps=15.0, hwaccel=True)
    assert emblem.shape == alone.shape and np.array_equal(emblem.astype("float32"), alone)


def test_onsets_are_served_only_for_chunks_this_decode_read():
    scan._ONSETS.update({scan._key("v.mp4", 0.0): [3.0], scan._key("v.mp4", 30.0): [31.0]})
    assert scan.emblem_onsets("v.mp4", 0.0, 60.0) == [3.0, 31.0]
    # A third chunk nobody read: the caller must decode as before.
    assert scan.emblem_onsets("v.mp4", 0.0, 90.0) is None
    # A gap starting off the grid (after a match record): not ours either.
    assert scan.emblem_onsets("v.mp4", 12.0, 30.0) is None


def test_overlap_duplicates_merge_as_killmark_merges_them():
    scan._ONSETS.update({scan._key("v.mp4", 0.0): [10.0, 30.4],
                         scan._key("v.mp4", 30.0): [30.5, 45.0]})
    assert scan.emblem_onsets("v.mp4", 0.0, 60.0) == [10.0, 30.4, 45.0]


def test_a_gap_that_ends_early_keeps_nothing_its_own_scan_could_not_see():
    """killmark needs HOLD seconds after an onset, inside what it read."""
    scan._ONSETS[scan._key("v.mp4", 0.0)] = [5.0, 19.7, 20.5]
    assert scan.emblem_onsets("v.mp4", 0.0, 20.0) == [5.0]


def test_forgetting_one_recording_keeps_the_others():
    scan._ONSETS.update({scan._key("a.mp4", 0.0): [1.0], scan._key("b.mp4", 0.0): [2.0]})
    scan.forget("a.mp4")
    assert scan.emblem_onsets("a.mp4", 0.0, 30.0) is None
    assert scan.emblem_onsets("b.mp4", 0.0, 30.0) == [2.0]


def test_killmark_takes_the_shared_onsets_on_a_mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    scan._ONSETS[scan._key("v.mp4", 0.0)] = [4.0]
    monkeypatch.setattr(killmark, "_region", lambda *a, **k: pytest.fail("decoded again"))
    assert killmark.scan(Path("v.mp4"), "VALORANT", start=0.0, duration=30.0) == [4.0]


def test_windows_never_asks_the_shared_decode(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(scan, "emblem_onsets", lambda *a: pytest.fail("Windows asked"))
    monkeypatch.setattr(killmark, "_region", lambda *a, **k: np.zeros((0, 155, 160), np.float32))
    assert killmark.scan(Path("v.mp4"), "VALORANT", start=0.0, duration=30.0) == []


def test_spans_read_in_parallel_come_back_in_time_order_on_a_mac(monkeypatch, tmp_path):
    """The Mac twin of test_valorant's ordering test: the shared reader is the
    one a Mac submits, and rows still merge in span order however the
    decoders finish."""
    import time as _time

    from autostream.clips import feed_ocr

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(vf, "band_shape", lambda video, band: (10, 10))
    monkeypatch.setattr(vf, "gpu_drop_works", lambda video, band, shape: False)
    monkeypatch.setattr(vf, "refine", lambda *a, **k: None)
    monkeypatch.setattr(feed_ocr, "doubtful", lambda cap, kills: {})
    monkeypatch.setattr(feed_ocr, "second_look", lambda events, cap, doubt, **k: events)
    used = []

    def span(args, window_end):
        _video, _band, start, *_ = args
        used.append(window_end)
        _time.sleep(0.02 * (5 - start / 120))          # later spans finish first
        return [("row", start)], []
    monkeypatch.setattr(scan, "span", span)
    monkeypatch.setattr(vf, "_span", lambda args: pytest.fail("the Mac used the old reader"))
    seen = []
    monkeypatch.setattr(vf, "collapse", lambda rows, min_seen: seen.extend(rows) or [])
    vf.scan(tmp_path / "rec.mp4", BAND, duration=600.0, second_look=True)
    assert [r[1] for r in seen] == [0.0, 120.0, 240.0, 360.0, 480.0]
    assert set(used) == {600.0}, "the window's end was not handed to the shared reader"
