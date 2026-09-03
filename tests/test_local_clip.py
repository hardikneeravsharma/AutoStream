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


# ------------------------------------- stopping rather than reading the screen

def test_the_stopped_run_offers_both_ways_forward():
    """A sharing-code box to fetch the right replay, and a button that takes
    the slow read deliberately. Neither is any use without the other."""
    from autostream.ui import clips as ui

    assert 'id="clip-needsdemo"' in ui.CLIPS_HTML
    assert 'id="clip-needsdemo-codes"' in ui.CLIPS_HTML
    assert 'data-act="demo-anyway"' in ui.CLIPS_HTML
    assert 'data-act="needsdemo-get"' in ui.CLIPS_HTML


def test_the_slow_read_button_carries_its_cost():
    """The cost is the entire reason the run stopped, so it goes ON the button
    rather than in prose beside it."""
    body = _func("clip_renderJob")
    assert "clip-needsdemo-anyway" in body
    assert "clip_dur(span / rate)" in body, (
        "the button has to say how long reading the screen would take")


def test_the_deliberate_slow_read_is_a_flag_on_the_same_run():
    """Not a second form. The selection, style and round types were already
    chosen, and asking for them again is how a slow path gets a wrong one."""
    body = _func("clip_runAnyway")
    assert "demo_fallback = true" in body
    assert "clip_runBody(s)" in body


def test_a_picked_file_carries_the_scan_rate():
    """It did not, so the page fell back to the plain kill-feed figure and
    advertised a 43-minute selection at 9 minutes of scanning. It took 40."""
    body = _func("clip_useLocal")
    assert "scan_rate: g.scan_rate" in body
    assert "demos: g.demos" in body


# ================================================================= THE CLASS
#
# Three times now the same shape: an object describing the selected recording
# is assembled field by field in one place, a field is added to what the server
# sends, and the other place is not updated. Nothing raises -- every one of
# those fields is falsy-when-absent and plausible-when-stale, so the page just
# answers wrong.
#
#   1.10.0  has_recording  missing from a picked file  -> Make clips dead
#   1.11.0  scan_rate      missing from a picked file  -> 9m quoted for 40m
#           ready          computed unresolved         -> Make clips dead again
#
# These tests are the audit, kept.

def _pick_literal() -> str:
    body = _func("clip_useLocal")
    i = body.index("clip_state.pick = {")
    j = body.index("{", i)
    depth = 0
    for k in range(j, len(body)):
        if body[k] == "{":
            depth += 1
        elif body[k] == "}":
            depth -= 1
            if depth == 0:
                return body[j:k + 1]
    raise AssertionError("unbalanced")


# What the games list sends about a game, and which of those the picked-file
# object has to carry. Anything the server learns about a game that the page
# reads off the selection belongs here.
GAME_FIELDS = ("can_scan", "scan_mode", "rounds", "demos", "scan_rate",
               "counts_assists", "player", "blocked")


def test_a_picked_file_carries_every_field_the_games_list_describes():
    """The audit that found scan_rate. A field the server sends about a game
    and the pick omits reads as undefined -- falsy, and therefore a wrong
    answer rather than an error."""
    import re

    literal = _pick_literal()
    have = set(re.findall(r"[{,]\s*(\w+)\s*:", literal))
    have |= set(re.findall(r"^\s*(\w+):", literal, re.M))
    missing = [f for f in GAME_FIELDS if f not in have]
    assert not missing, (
        f"clip_useLocal does not copy {missing} from the games list. Every one "
        f"of those is read off the pick somewhere, and an absent key is falsy "
        f"-- which is a wrong answer, not an error")


def test_switching_game_refreshes_every_field_that_describes_it():
    """The same audit, in the other direction. Retargeting used to refresh five
    fields and leave the rest describing the game before -- so Counter-Strike
    inherited Delta Force's scan rate, four times too fast."""
    body = _func("clip_useGameLocally")
    for f in ("rounds", "scan_mode", "can_scan", "scan_rate", "demos",
              "needs_ocr", "counts_assists"):
        assert f"s.{f} =" in body, (
            f"s.{f} is left describing the previous game after a switch")


def test_the_two_payloads_answer_can_this_be_scanned_the_same_way():
    """The games list and the profile rows both describe a game, and the page
    reads whichever it has. They disagreed: profiles.listing() computed
    exists() on an UNRESOLVED profile, so a kill-feed game whose in-game name
    was set came back not-ready and greyed out Make clips the moment it was
    chosen from the dropdown."""
    from autostream.clips import profiles

    app = webui.Server.__new__(webui.Server)
    rows = {r["key"]: r for r in app._profile_rows()}
    for row in app.clips_games()["games"]:
        other = rows.get(row["game_key"])
        assert other, row["game_key"]
        assert other["ready"] == row["can_scan"], (
            f"{row['game']}: the games list says can_scan={row['can_scan']} "
            f"and the profile listing says ready={other['ready']}")
        for f in ("scan_rate", "needs_ocr", "demos", "rounds"):
            assert other[f] == row[f], f"{row['game']}: {f} disagrees"


def test_the_profile_listing_resolves_the_in_game_name():
    """The root of it. load_all() reads the profile files; the name lives in
    games.yaml and only for_game() merges it, so exists() on an unresolved
    kill-feed profile is False even when the name is plainly set."""
    from autostream.clips import profiles

    for row in profiles.listing():
        prof = profiles.for_game(row["key"])
        if prof is None:
            continue
        assert row["ready"] == prof.exists(), (
            f"{row['label']}: listing says ready={row['ready']}, the resolved "
            f"profile says {prof.exists()}")
        assert row["player"] == prof.player


def test_a_picked_file_can_have_its_game_changed():
    """One file routinely holds more than one game -- the whole reason the
    filmstrip exists. The control that changes it was only ever shown for a
    recorded session, though clip_setGame already had the branch for a picked
    one."""
    body = _func("clip_renderOptions")
    assert "|| !!s.local" in body, (
        "the game switcher is hidden for picked files, so the only way to "
        "change the game is to re-pick the video")


# Fields a recorded session has and a picked file cannot. Listed rather than
# left to be re-derived: an audit that has to be repeated from scratch every
# time is an audit nobody repeats.
SESSION_ONLY = {
    # OBS was already recording before the session began. There is no session
    # behind a picked file, so there is nothing for it to predate.
    "game_uncertain": "no session to have started late",
    "pre_session_seconds": "same",
    # Which games were played during the session. Unknowable for a file
    # somebody handed us -- which is what the filmstrip and the game switcher
    # are for instead.
    "games": "the journal's record of a session",
    # A starting rectangle for a game with NO profile yet. A picked file's game
    # is chosen from a list of games that have one, so this is always None.
    "seed": "only offered for an uncalibrated game",
}


def test_the_only_gaps_left_are_ones_a_picked_file_cannot_have():
    """The audit, kept. Every field the page reads off the selection is either
    supplied for a picked file, set at runtime, or listed above with a reason.

    A new field arriving on a history row and not on a picked file has been
    the same bug three times, and it never raises."""
    import re

    js = clips_ui.CLIPS_JS
    reads = set()
    for m in re.finditer(r"\bvar\s+(\w+)\s*=\s*clip_state\.pick\b", js):
        name = m.group(1)
        start = js.rfind("function ", 0, m.start())
        b = js.index("{", start)
        depth = 0
        for k in range(b, len(js)):
            if js[k] == "{":
                depth += 1
            elif js[k] == "}":
                depth -= 1
                if depth == 0:
                    reads |= set(re.findall(rf"\b{name}\.(\w+)", js[start:k]))
                    break
    reads |= set(re.findall(r"clip_state\.pick\.(\w+)", js))

    literal = _pick_literal()
    supplied = set(re.findall(r"[{,]\s*(\w+)\s*:", literal))
    supplied |= set(re.findall(r"^\s*(\w+):", literal, re.M))
    # Filled in after the file is probed, or as the page runs.
    supplied |= {"demo_state", "demo_file", "has_demo", "match_state",
                 "match_count", "match_why", "duration", "started"}

    unexplained = sorted(reads - supplied - set(SESSION_ONLY))
    assert not unexplained, (
        f"the page reads {unexplained} off the selection, and a picked file "
        f"supplies none of them. Either copy them in clip_useLocal or add "
        f"them to SESSION_ONLY with the reason a picked file cannot have them")


# ------------------------------------------- Adjust the cut, on a fresh run
#
# FROM THE APP. A run finished, its clips were played from the results card,
# and Adjust the cut refused with "that run did not keep its recording" -- of a
# 111-minute recording it had just finished reading, still on disk.
#
# clip_state.made holds the clips a PREVIOUS run left for the selected stream.
# The player is just as often opened on the run that has this second ended, and
# the folder then does not match, so the source came out empty. The same shape
# as the picked-file bugs: state assembled in one place and read from another.

def test_the_trim_panel_can_learn_the_run_it_was_opened_on():
    body = _func("clip_trimSync")
    assert "clip_runFor(p.folder)" in body, (
        "clip_state.made only covers a run reached from the stream list; the "
        "player is also opened straight off the results of the run that just "
        "finished, and that folder has to be able to answer for itself")


def test_opening_the_player_asks_which_recording_the_run_used():
    body = _func("clip_openPlayer")
    assert "clip_loadRunFor" in body


def test_the_run_lookup_does_not_refetch_on_every_clip_change():
    """It is consulted on every clip change and the answer cannot move for a
    finished run. `undefined` means not asked; `null` means asked and there is
    no answer -- which is what stops the fetch repeating forever."""
    body = _func("clip_loadRunFor")
    assert "!== undefined" in body


def test_the_refusal_does_not_assert_a_missing_recording_it_has_not_checked():
    """The old message stated as fact that the recording was gone, to somebody
    whose recording was plainly there."""
    body = _func("clip_trimToggle")
    assert "did not keep its recording" not in body
    assert "clip_runFor" in body, "it has to distinguish 'gone' from 'not yet known'"
