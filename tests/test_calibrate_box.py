"""What the calibrator will accept as a kill marker, and why.

THE BUG THIS FILE EXISTS FOR
    A user drew a 277x213 box around the marker area of a 1080p recording and
    pressed Test and save. Nothing appeared to happen, so it was reported as a
    dead button. Nothing was dead: the request ran for ELEVEN MINUTES AND
    FIFTY-SIX SECONDS, measured, and then answered 'good'.

    ncc slides the template over a band that grows with the box, so the work
    per frame is quartic in the box's linear size. The two limits that existed
    were on the box's AREA and on its longest SIDE AS A FRACTION of the frame,
    and that box was comfortably inside both -- area 0.0285 against a 0.06
    limit, sides 0.14 and 0.20 against 0.35. Neither limit is wrong; neither
    could see the cost.

    So the third limit is in absolute pixels, and it is checked before a single
    frame is decoded. The refusal takes 0.21s where the acceptance took 715.

Nothing here needs a video. The probe is faked because the resolution is the
only thing the box arithmetic reads off the file, and every assertion below is
about arithmetic that happens strictly before any decoding.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import calibrate                            # noqa: E402


@pytest.fixture
def video(tmp_path, monkeypatch):
    """A file that exists, reporting 1920x1080, that is never decoded."""
    p = tmp_path / "recording.mp4"
    p.write_bytes(b"not really an mp4")
    monkeypatch.setattr(calibrate, "media_info",
                        lambda _p: {"width": 1920, "height": 1080,
                                    "duration": 10418.0})

    def _never(*a, **k):
        raise AssertionError(
            "a frame was decoded -- every box this file rejects must be "
            "refused before any decoding, which is the whole point")

    monkeypatch.setattr(calibrate, "_grab_gray", _never)
    return p


def ask(video, box, **kw):
    body = {"path": str(video), "t": 1303.0, "box": list(box),
            "label": "Counter-Strike 2", "key": "cs2.exe", "mode": "template"}
    body.update(kw)
    return calibrate.from_request(body)


def px_box(w_px, h_px, W=1920, H=1080):
    """A box w_px x h_px, centred low on the frame where a marker sits."""
    fw, fh = w_px / W, h_px / H
    return (0.5 - fw / 2, 0.90 - fh / 2, 0.5 + fw / 2, 0.90 + fh / 2)


# ------------------------------------------------------- the reported bug

def test_the_box_from_the_report_is_refused_and_says_what_to_do(video):
    """277x213 -- the exact box that took twelve minutes."""
    r = ask(video, px_box(277, 213))
    assert "277x213" in r["error"], (
        "the refusal must quote what they drew; 'too big' with no number "
        f"leaves them guessing: {r['error']}")
    assert "minutes to check" in r["error"], (
        f"it must say what the cost would be, in time: {r['error']}")
    assert "tightly" in r["error"], "it must say which way to change it"


def test_the_old_limits_really_did_let_that_box_through(video):
    """The floor under the fix. If a later change to MAX_BOX_AREA or
    MAX_BOX_SIDE happens to catch this box, the cost cap stops being the
    thing under test and this file quietly proves nothing."""
    x1, y1, x2, y2 = px_box(277, 213)
    assert (x2 - x1) * (y2 - y1) < calibrate.MAX_BOX_AREA
    assert (x2 - x1) < calibrate.MAX_BOX_SIDE
    assert (y2 - y1) < calibrate.MAX_BOX_SIDE


def test_a_marker_sized_box_is_not_refused(video):
    """58x58 calibrated in 16.6s on the same recording, so it must pass.

    Reaching the decode is the proof it got past every gate. from_request
    catches anything _grab_gray raises and reports it as a read failure, so
    that message -- and not the sentinel itself -- is what comes back.
    """
    r = ask(video, px_box(58, 58))
    assert "Could not read that frame" in r.get("error", ""), (
        f"a marker-sized box was refused before it was even looked at: {r}")
    assert "a frame was decoded" in r["error"], (
        "it failed for some reason other than reaching the decode")


def test_a_tight_box_round_a_TALL_icon_is_not_refused(video):
    """79x125 -- A REAL BOX A REAL USER DREW, correctly, round a tall marker.

    The first version of this cap was on the box's longest side, at 96px. That
    refused this box and told the user to draw it tighter than it already was.
    It costs 1.0e8 multiply-adds a frame, which is about forty seconds: well
    inside the budget. A rule that cannot tell a tall sliver from a square is
    not measuring the thing it claims to measure.
    """
    assert calibrate.ncc_work(px_box(79, 125), 1920, 1080) < calibrate.MAX_NCC_WORK
    r = ask(video, px_box(79, 125))
    assert "Could not read that frame" in r.get("error", ""), (
        f"a tight box round a tall icon was refused before being looked at: {r}")


def test_a_long_thin_box_is_cheap_and_is_allowed(video):
    """200x20 is a fifth of the screen wide and costs seven seconds, because
    a 20px-tall template has almost nothing to slide down. Area and longest
    side both call this large; the cost knows better."""
    assert calibrate.ncc_work(px_box(200, 20), 1920, 1080) < calibrate.MAX_NCC_WORK
    r = ask(video, px_box(200, 20))
    assert "Could not read that frame" in r.get("error", ""), (
        f"a cheap thin box was refused: {r}")


def test_the_estimate_matches_the_one_timed_measurement(video):
    """The budget is only meaningful if the arithmetic behind it reproduces
    the run that was actually timed: 277x213 took 715.3s end to end."""
    work = calibrate.ncc_work(px_box(277, 213), 1920, 1080)
    seconds = work / calibrate.NCC_WORK_PER_SECOND
    assert seconds == pytest.approx(715.3, rel=0.05), (
        f"the model says {seconds:.0f}s where the timed run took 715.3s")


# ----------------------------------------------- the limits that were there

def test_a_box_smaller_than_the_floor_is_still_refused(video):
    r = ask(video, px_box(4, 4))
    assert str(calibrate.MIN_BOX_PX) in r["error"]


def test_a_box_covering_the_screen_is_still_refused(video):
    r = ask(video, (0.0, 0.0, 1.0, 1.0))
    assert "too much of the screen" in r["error"]


def test_a_box_with_no_area_is_refused(video):
    assert "no area" in ask(video, (0.5, 0.5, 0.5, 0.6))["error"]


def test_a_missing_box_is_refused_before_anything_else(video):
    assert "Drag a box" in ask(video, [])["error"]


# ------------------------------------------------------- the killfeed path

def test_the_killfeed_mode_is_not_capped(video, monkeypatch):
    """A feed box SHOULD be big -- it is the feed, not a glyph -- and it is
    read by OCR rather than by sliding a template, so none of the cost the cap
    exists for applies. Capping both modes with one number would make the
    zero-configuration detector the one that needs a careful hand."""
    seen = {}
    monkeypatch.setattr(calibrate, "_killfeed_request",
                        lambda *a, **k: seen.setdefault("called", True) or {"ok": True})
    r = ask(video, (0.05, 0.05, 0.55, 0.35), mode="killfeed")
    assert seen.get("called"), f"the feed box was rejected by a marker rule: {r}"


# --------------------------------------------------------------- the cost

def test_the_budget_is_a_wait_a_person_will_sit_through():
    """The cap is a number of multiply-adds, so its meaning is a duration.

    The dialog's spinner promises "up to a minute on a long recording", and a
    cap that allowed three would make that line a lie -- which is the same
    failure as the original bug, just smaller.
    """
    seconds = calibrate.MAX_NCC_WORK / calibrate.NCC_WORK_PER_SECOND
    assert 30.0 <= seconds <= 75.0, (
        f"the worst box the cap allows takes {seconds:.0f}s, against a "
        "spinner that promises about a minute")


# --------------------------------------------------- what the failure SAYS

def test_a_killfeed_failure_is_not_described_as_a_marker():
    """ASKED DIRECTLY: "what does this marker is not distinct enough means???"

    The user was in kill-feed mode, where there is no marker. calibrate returns
    the real reason -- "'NAME' was not readable anywhere in that box ... make
    sure the box covers the whole feed including the names at both ends" --
    and the page replaced it with a sentence about marker contrast, which
    sends someone off to redraw a box whose contrast was never the problem.
    """
    from autostream.ui import clips as ui

    js = ui.CLIPS_JS
    i = js.index("r.separation === 'bad'")
    branch = js[i:i + 900]
    assert "clip_calMode() === 'killfeed'" in branch, (
        "the failure toast does not distinguish the two modes, so a kill-feed "
        "failure is still reported as a marker that lacks contrast")
    assert "read your name" in branch, (
        "kill-feed mode must say the NAME could not be read; that is the "
        "actual failure and the only one the user can act on")


def test_the_servers_own_reason_reaches_the_panel():
    """Four different causes, each with its own sentence and its own numbers.
    Discarding them for one generic line is how a precise diagnosis becomes
    'what does this mean'."""
    from autostream.ui import clips as ui

    js = ui.CLIPS_JS
    i = js.index("r.separation === 'bad'")
    assert "v.textContent = r.note" in js[max(0, i - 400):i], (
        "the note calibrate returns must be rendered, not summarised away")
