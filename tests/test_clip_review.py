"""Reviewing a plan before anything is encoded.

The point of the review is that the plan shown IS the plan cut -- so the tests
here are mostly about the identity that makes that true: the key a per-clip
setting is stored under has to survive the round trip from planning to cutting.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autostream import webui                        # noqa: E402
from autostream.clips import jobs, voice            # noqa: E402


# ------------------------------------------------------------- the clip key

def test_the_key_is_the_start_time_to_a_tenth():
    assert jobs.clip_key(12.34) == "12.3"
    assert jobs.clip_key(12.0) == "12.0"
    assert jobs.clip_key(0) == "0.0"


def test_the_key_survives_a_round_trip_through_json():
    """The plan is written to session.json, read by the browser, and posted
    back. A float that changed on the way would silently lose the setting."""
    key = jobs.clip_key(1219.5)
    back = json.loads(json.dumps({key: {"caption": False}}))
    assert key in back


def test_two_clips_a_tenth_apart_do_not_share_a_key():
    assert jobs.clip_key(10.0) != jobs.clip_key(10.1)


# ------------------------------------------------------------- the voices

def _server():
    return webui.Server.__new__(webui.Server)


def test_the_voice_list_is_grouped_by_readable_names():
    got = _server().clips_voices()
    assert got["ok"] and got["default"]
    assert got["sample_line"], "a voice cannot be auditioned without a line"
    if got["available"]:
        # The groups are what the chooser shows, so they have to be words
        # rather than the two-letter prefixes the files are named with.
        assert got["groups"]
        for label, names in got["groups"].items():
            assert len(label) > 2, label
            assert names


def test_an_unknown_voice_is_refused_rather_than_rendered():
    wav, err = _server().voice_sample("not-a-voice")
    assert wav == b"" and err and "no voice" in err.lower()


@pytest.mark.skipif(not voice.available(), reason="no voice model installed")
def test_a_sample_is_a_wav_and_is_kept_for_the_next_ask():
    srv = _server()
    srv._voice_samples = {}
    wav, err = srv.voice_sample(voice.VOICE, "Testing one two.")
    assert err is None and wav[:4] == b"RIFF"
    assert srv._voice_samples, "rendering again per click would be a second each"
    again, err2 = srv.voice_sample(voice.VOICE, "Testing one two.")
    assert err2 is None and again == wav


# -------------------------------------------------- per-clip settings apply

class _Plan:
    """Enough of a ClipPlan for _speak."""
    def __init__(self, start=10.0):
        self.start, self.end = start, start + 10
        self.kills = self.burst_kills = 2
        self.labels: list[str] = []
        self.name = "clip"
        self.rank = 1


def _job(**opt):
    j = jobs.ClipJob.__new__(jobs.ClipJob)
    j.options = opt
    j.said = []
    return j


def test_a_typed_line_is_spoken_instead_of_the_generated_one(monkeypatch, tmp_path):
    said = {}

    class FakeSpeech:
        duration = 1.0
        path = tmp_path / "s.wav"

    def fake_say(text, out, **kw):
        said["text"] = text
        said["voice"] = kw.get("voice")
        return FakeSpeech()

    monkeypatch.setattr(voice, "available", lambda: True)
    monkeypatch.setattr(voice, "say", fake_say)
    monkeypatch.setattr(voice, "line_for", lambda p, avoid=(): "GENERATED")

    j = _job(voice_name="am_michael")
    spoken, speech = j._speak(_Plan(), tmp_path / "clip.mp4",
                              line="  My own words.  ", name="bf_emma")
    assert spoken == "My own words."
    assert said["text"] == "My own words."
    assert said["voice"] == "bf_emma", "the clip's own voice was ignored"


def test_without_a_typed_line_the_generated_one_is_used(monkeypatch, tmp_path):
    class FakeSpeech:
        duration = 1.0
        path = tmp_path / "s.wav"

    monkeypatch.setattr(voice, "available", lambda: True)
    monkeypatch.setattr(voice, "say", lambda text, out, **kw: FakeSpeech())
    monkeypatch.setattr(voice, "line_for", lambda p, avoid=(): "GENERATED")
    j = _job()
    spoken, _ = j._speak(_Plan(), tmp_path / "clip.mp4")
    assert spoken == "GENERATED"


def test_a_repeated_typed_line_is_not_dropped(monkeypatch, tmp_path):
    """`avoid` stops the GENERATED lines repeating. Someone who typed the same
    sentence twice meant it, and dropping their words would be worse."""
    class FakeSpeech:
        duration = 1.0
        path = tmp_path / "s.wav"

    monkeypatch.setattr(voice, "available", lambda: True)
    monkeypatch.setattr(voice, "say", lambda text, out, **kw: FakeSpeech())
    monkeypatch.setattr(voice, "line_for", lambda p, avoid=(): "GENERATED")
    j = _job()
    j.said = ["Same line."]
    spoken, _ = j._speak(_Plan(), tmp_path / "clip.mp4", line="Same line.")
    assert spoken == "Same line."


# ------------------------------------------------- one spelling for a path

def test_a_path_is_compared_by_what_it_points_at():
    """The history writes a recording with forward slashes; a run's
    session.json writes the same file with backslashes. Compared as strings
    they never match -- which is why the Clips page could say neither how many
    kills a previous run found nor that a stream had already been clipped."""
    srv = _server()
    a = srv._same_file(r"C:/Users/u/Videos/AutoStream/x.mp4")
    b = srv._same_file(r"C:\Users\u\Videos\AutoStream\x.mp4")
    assert a == b and a
    assert srv._same_file("") == ""
    # Windows does not care about case, and OBS and the journal disagree on it.
    assert srv._same_file(r"C:\Users\U\X.MP4") == srv._same_file(r"c:/users/u/x.mp4")


# --------------------------------------------- the voice chooser gets filled

def test_every_voice_chooser_is_filled_by_the_same_function():
    """FROM THE APP: the player said "no voices installed" with 28 of them
    loaded. Fetching the voices is async, so a panel is drawn before they
    arrive and has to be filled in when they land -- and the function that
    does that filled the review panel's choosers and not the player's.

    Structural rather than behavioural, because there is no browser here: every
    <select> that offers voices must be named inside clip_fillVoiceSelects.
    """
    from autostream.ui import clips as ui

    js = ui.CLIPS_JS
    start = js.index("function clip_fillVoiceSelects()")
    body = js[start:js.index("\nasync function clip_loadVoices", start)]
    # The player's chooser and the review rows' choosers.
    assert "clip-play-voice" in body
    assert "clip-review-voice" in body
    assert "clip-review-voice-all" in body

    # ...and every chooser in the markup is one of those three.
    html = ui.CLIPS_HTML
    for token in ("clip-play-voice", "clip-review-voice-all"):
        assert f'id="{token}"' in html, token


# ------------------------------------------------- a cancelled job says so

def _stub_job():
    import threading
    import time as _t

    j = jobs.ClipJob.__new__(jobs.ClipJob)
    j._lock = threading.Lock()
    j._cancel = threading.Event()
    j._proc = None
    j.cancel_at = None
    j.state, j.step = "running", "scan"
    j.done, j.total = 1, 23
    j.message, j.error = "Reading the feed", None
    j.game, j.folder = "Delta Force", Path("x")
    j.results, j.preview, j.summary = [], [], {}
    j.montage_path = j.reel_path = j.promo_path = None
    j.started_at = _t.time() - 90
    j.step_started = j.started_at
    j.source = Path("rec.mp4")
    j.source_seconds, j.scan_seconds = 6660.0, 6660.0
    j.scan_mode, j.clip_count = "template", 0
    return j


def test_a_cancelled_job_reports_that_it_is_stopping():
    """FROM THE APP: pressing Cancel left the last message on screen while the
    chunks already decoding ran to their end -- most of a minute on a long
    recording -- which reads as "it ignored me"."""
    j = _stub_job()
    assert j.snapshot()["stopping"] is False
    j.cancel()
    snap = j.snapshot()
    assert snap["stopping"] is True
    assert snap["stopping_for"] >= 0


def test_stopping_stops_being_true_once_the_job_has_ended():
    j = _stub_job()
    j.cancel()
    j.state = "cancelled"
    assert j.snapshot()["stopping"] is False


def test_pressing_cancel_twice_does_not_restart_the_clock():
    j = _stub_job()
    j.cancel()
    first = j.cancel_at
    j.cancel()
    assert j.cancel_at == first


# ------------------------------------------- choosing a game changes the form

def test_the_profile_listing_says_what_kind_of_game_each_one_is():
    """FROM THE APP: a Delta Force recording was re-pointed at Counter-Strike 2
    and the options carried on offering "minimum kills in a clip" -- which
    Counter-Strike does not use, because it clips whole ROUNDS.

    The page could only describe the game the journal had recorded, because the
    listing did not say what kind of game any of the others were."""
    from autostream.clips import profiles

    rows = {r["label"]: r for r in profiles.listing()}
    for r in rows.values():
        assert "rounds" in r and "mode" in r
        assert "demos" in r and "matches" in r
    if "Counter-Strike 2" in rows:
        assert rows["Counter-Strike 2"]["rounds"] is True
        assert rows["Counter-Strike 2"]["demos"] is True
    if "Delta Force" in rows:
        assert rows["Delta Force"]["rounds"] is False
    if "VALORANT" in rows:
        assert rows["VALORANT"]["matches"] is True


def test_choosing_a_game_retargets_the_options_without_rewriting_the_journal():
    """Structural: selecting applies to the form and the next run; only the
    button writes the correction back to the stream's record."""
    from autostream.ui import clips as ui

    js = ui.CLIPS_JS
    start = js.index("function clip_useGameLocally(")
    body = js[start:js.index("async function clip_setGame()", start)]
    assert "clip_renderOptions()" in body
    assert "s.rounds" in body                  # the form follows the game
    assert "/api/clips/setgame" not in body    # ...but the journal is not touched
    # ...and selecting is wired, not just the button.
    assert "gamefix.addEventListener('change'" in js
