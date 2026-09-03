"""Clipping a video file the user picked, rather than one AutoStream recorded.

THE BUG THIS FILE EXISTS FOR
    A picked file became a `pick` shaped like a history row -- but without
    `has_recording`, which every gate on the Clips page asks first. A key that
    is simply absent reads as false, so "Make clips" was disabled on every file
    anybody chose, under the one hint that could not possibly be true of a file
    picked from a dialog thirty seconds earlier: "the recording for this stream
    is no longer on disk". "Review clips first" was never gated the same way,
    so the page refused a scan it would then happily perform.

    The second half was the same shape: the refresh that keeps the selected
    stream across a poll matched picks against the history list, found no row
    for a picked file, and silently swapped it for an unrelated stream.

Both are absences rather than errors, which is why they are tested as text:
there is nothing to raise.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest                                                     # noqa: E402

from autostream import webui                                      # noqa: E402
from autostream.ui import clips as clips_ui                       # noqa: E402


def _func(name: str) -> str:
    """One function's source out of the page script.

    Braces are counted rather than regex-matched to the closing one: these
    functions contain object literals and nested functions, and a lazy match
    stops at the first `}` inside them.
    """
    js = clips_ui.CLIPS_JS
    i = js.index(f"function {name}(")
    j = js.index("{", i)
    depth = 0
    for k in range(j, len(js)):
        if js[k] == "{":
            depth += 1
        elif js[k] == "}":
            depth -= 1
            if depth == 0:
                return js[i:k + 1]
    raise AssertionError(f"{name} has unbalanced braces")


# ------------------------------------------------------------ the main bug

def test_a_picked_file_says_its_recording_exists():
    """Without this the primary button on the page is dead for every local
    file, and the reason given is about a file that is plainly there."""
    body = _func("clip_useLocal")
    assert re.search(r"has_recording:\s*true", body), (
        "clip_useLocal builds the pick every gate on this page reads; a "
        "missing has_recording disables Make clips on every picked file")


def test_the_picked_file_carries_what_the_gates_read():
    """duration feeds the calibrator's range and the filmstrip; both refuse a
    pick without one, so a picked file could not be calibrated either."""
    body = _func("clip_useLocal")
    for key in ("duration", "started", "local: true"):
        assert key in body, key


def test_a_refresh_does_not_swap_a_picked_file_for_a_stream():
    """clip_load runs on every refresh and again the moment a review lands.
    Matching a picked file against the history finds nothing, so without the
    guard the pick became some other stream -- and the cut that followed cut
    that one instead."""
    body = _func("clip_load")
    keep = body[body.index("Keep the selection"):]
    guard = keep[:keep.index("}")]
    assert "!clip_state.pick.local" in guard, (
        "the keep-the-selection filter must skip picked files, which are not "
        "in the history and can never match a row in it")


def test_review_and_make_clips_are_gated_the_same_way():
    """The tell that something was wrong: one button worked and the other did
    not, for the same file and the same scan. Both now read `why`."""
    js = clips_ui.CLIPS_JS
    assert "clip_gateReview" in js or "go.disabled = !!why" in js
    # And the review button is disabled by the same reason the run button is.
    render = _func("clip_renderPick") if "function clip_renderPick(" in js \
        else _func("clip_renderOptions")
    assert "clip-review" in render, (
        "Review clips first must be disabled by the same `why` that disables "
        "Make clips, or the page offers a run it says it cannot do")


# ------------------------------------------------------- probing the file

@pytest.fixture
def app():
    return webui.Server.__new__(webui.Server)


def test_probing_a_missing_file_answers_rather_than_raising(app):
    out = app.clips_probe({"path": "Z:/not/here.mp4"})
    assert out["duration"] == 0
    assert out["started"] is None


def test_the_start_comes_from_obs_s_filename_stamp(app, tmp_path, monkeypatch):
    """OBS stamps its filenames, which is when the picture begins. The file's
    mtime is when writing FINISHED, so on a two-hour recording it is two hours
    out -- and every demo played during it then looks older than the
    recording and is rejected."""
    monkeypatch.setattr("autostream.clips.tools.media_info",
                        lambda p: {"duration": 7200.0})
    f = tmp_path / "2026-08-30 19-04-11.mp4"
    f.write_bytes(b"x")
    out = app.clips_probe({"path": str(f)})
    assert out["duration"] == 7200.0
    stamped = time.localtime(out["started"])
    assert (stamped.tm_year, stamped.tm_mon, stamped.tm_mday) == (2026, 8, 30)
    assert (stamped.tm_hour, stamped.tm_min) == (19, 4)


def test_without_a_stamp_the_duration_is_taken_off_the_mtime(app, tmp_path,
                                                             monkeypatch):
    """The same correction, for a file OBS did not name."""
    monkeypatch.setattr("autostream.clips.tools.media_info",
                        lambda p: {"duration": 3600.0})
    f = tmp_path / "gameplay.mp4"
    f.write_bytes(b"x")
    out = app.clips_probe({"path": str(f)})
    assert out["started"] == pytest.approx(f.stat().st_mtime - 3600.0, abs=2)


def test_a_file_that_cannot_be_probed_still_answers(app, tmp_path, monkeypatch):
    """ffmpeg missing, or a file it cannot read. The run probes it again
    itself, so a failure here costs the filmstrip and nothing else."""
    def boom(p):
        raise RuntimeError("no ffprobe")

    monkeypatch.setattr("autostream.clips.tools.media_info", boom)
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    out = app.clips_probe({"path": str(f)})
    assert out["duration"] == 0
    assert out["started"] is not None


def test_a_game_with_no_replays_is_not_asked_about_demos(app, tmp_path,
                                                         monkeypatch):
    """"No demo" against a game that has never written one reads as a fault
    rather than as not applicable."""
    monkeypatch.setattr("autostream.clips.tools.media_info",
                        lambda p: {"duration": 600.0})
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    out = app.clips_probe({"path": str(f), "game_key": "deltaforceclient.exe"})
    assert out["demo_state"] is None
    assert out["has_demo"] is None


# ------------------------------------------- the demo panel, for a picked file
#
# demo_state came back "have" for a real recording, and the page showed nothing
# at all -- the panel only ever appeared when something was MISSING. That works
# for a recorded stream, whose row in the list carries a "demo on disk" tag,
# but a picked file has no row, so the one arrangement where a replay halves
# the run reported nothing.

def test_the_demo_panel_is_shown_even_when_a_replay_was_found():
    body = _func("clip_renderDemoBox")
    assert "s.demo_state !== 'have'" not in body, (
        "hiding the panel on 'have' leaves a picked file with no way to know "
        "a replay was found, because it has no row in the list to carry a tag")
    assert "!!s.demo_state" in body


def test_the_found_case_says_which_replay_and_drops_the_code_box():
    body = _func("clip_renderDemoBox")
    assert "demo_file" in body, "say WHICH replay, so a wrong one is spottable"
    assert "clip-democodes" in body and "clip-demoask" in body, (
        "there is nothing to ask for once the replay is on disk")


def test_the_progress_card_explains_which_path_the_run_took():
    from autostream.ui import clips as ui

    assert 'id="clip-prog-demo"' in ui.CLIPS_HTML
    assert "j.demo_note" in ui.CLIPS_JS


def test_the_scan_estimate_comes_from_the_rate_not_a_rule_of_thumb():
    """It said 'roughly a minute per 10 minutes' for every killfeed run and
    quoted 4 minutes for one that took 30."""
    body = _func("clip_renderOptions")
    assert "s.scan_rate" in body
    assert "span / 10" not in body
