"""Reading a StreamElements channel's overlays.

Everything here fails quietly if it is wrong: a misclassified overlay puts the
ending card on at the start of the stream, and an unreadable token produces an
empty list that looks exactly like a channel with no overlays. So the classifier
is pinned against the real names this was built from, and every failure path is
checked for saying something rather than raising.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import streamelements as se       # noqa: E402


def a_token(**claims) -> str:
    """A JWT-shaped string. The signature is never checked, and must not be."""
    body = base64.urlsafe_b64encode(
        json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{body}.signature"


# ------------------------------------------------------------- classifying

def test_the_real_scene_names_are_classified():
    """The names this was built against, verbatim from the channel.

    A theme names every scene after itself, so the distinguishing part is a
    couple of words in the middle of sixty characters.
    """
    theme = "Japan Traditional Ink Stream Overlays - Japan Theme {} Youtube"
    assert se.kind_of(theme.format("Start Scene")) == "starting"
    assert se.kind_of(theme.format("Be right back Scene")) == "paused"
    assert se.kind_of(theme.format("Stream End Scene")) == "ending"
    assert se.kind_of(theme.format("InGame Scene")) == "game"
    assert se.kind_of(theme.format("Talk Scene")) == "talk"


def test_be_right_back_is_not_read_as_an_ending():
    """Order matters in KINDS.

    "Be right back" and "Stream End" both describe a stream that is not showing
    the game, and a looser test would put the goodbye card up during a break.
    """
    assert se.kind_of("BRB") == "paused"
    assert se.kind_of("be right back") == "paused"
    assert se.kind_of("Starting Soon") == "starting"


def test_a_name_that_says_nothing_is_left_alone():
    # Better than guessing: an unclassified overlay is simply not offered.
    assert se.kind_of("My Overlay") == ""
    assert se.kind_of("") == ""


# ------------------------------------------------------------ credentials

def test_the_channel_and_overlay_token_come_out_of_the_jwt():
    """So pasting one value is enough.

    The payload is read WITHOUT verifying the signature, which is safe because
    nothing is being authorised -- the claims only address the user's own
    channel, and a wrong one just fails the API call.
    """
    t = a_token(channel="chan123", authToken="overlay456", exp=4102444800)
    got = se._claims(t)
    assert got["channel"] == "chan123"
    assert got["authToken"] == "overlay456"


def test_rubbish_in_place_of_a_token_does_not_raise():
    for bad in ("", "not-a-jwt", "a.b", "a.!!!!.c", "..."):
        assert se._claims(bad) == {}


def test_an_expiry_is_reported_in_seconds():
    import time

    soon = a_token(channel="c", exp=time.time() + 3600)
    assert 3400 < se.expires_in(soon) < 3700
    assert se.expires_in(a_token(channel="c")) == 0.0


def test_a_token_with_no_channel_is_refused(tmp_path, monkeypatch):
    """Storing it would produce a credential that can never list anything."""
    monkeypatch.setattr(se, "CRED_FILE", tmp_path / "se.json")
    assert se.save_credentials(a_token(authToken="x")) is False
    assert not (tmp_path / "se.json").exists()


def test_storing_and_reading_a_token_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(se, "CRED_FILE", tmp_path / "se.json")
    assert se.save_credentials(a_token(channel="c1", authToken="o1")) is True
    got = se.credentials()
    assert got["channel_id"] == "c1"
    assert got["overlay_token"] == "o1"
    assert se.available() is True


def test_no_stored_token_is_an_empty_answer_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(se, "CRED_FILE", tmp_path / "nothing.json")
    se.forget()
    assert se.credentials() == {}
    assert se.available() is False
    assert se.overlays(force=True) == []


# ------------------------------------------------------------------- URLs

def test_the_overlay_url_is_the_id_and_the_overlay_token():
    o = se.Overlay(id="abc", name="x")
    assert o.url("tok") == "https://streamelements.com/overlay/abc/tok"


def test_an_unreachable_api_reports_an_empty_list(tmp_path, monkeypatch):
    """A settings page should show nothing and log why, not a stack trace over
    the form somebody is filling in."""
    monkeypatch.setattr(se, "CRED_FILE", tmp_path / "se.json")
    se.save_credentials(a_token(channel="c1", authToken="o1"))

    def boom(path, jwt):
        raise OSError("no network")

    monkeypatch.setattr(se, "_get", boom)
    se.forget()
    assert se.overlays(force=True) == []
