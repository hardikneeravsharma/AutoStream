"""Noticing a Google sign-in that is about to expire, before it does.

THE MOST EXPENSIVE AVOIDABLE FAILURE IN THIS PRODUCT. An OAuth consent screen
left in Testing issues refresh tokens that die after about seven days. The
symptom is streaming that silently stops working days after a setup that went
perfectly, and the cause is one button in a console nobody has open any more.

GOOGLE DOES NOT TELL THE CLIENT whether the app is published -- no field, no
endpoint, no scope -- so "refuse to finish setup while it is in Testing"
cannot be built, however much one would want it.

What can be known is the thing that matters. A published app's refresh token
does not expire, so a token still being refreshed nine days after it was
granted PROVES the app is published. Until that proof exists, days five to
seven are worth a word -- while the fix is still a button rather than a
sign-in.
"""
from __future__ import annotations

import json
import time

import pytest

from autostream import paths
from autostream import youtube as yt


DAY = 86400.0


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "TOKEN_FILE", tmp_path / "token.json")
    paths.TOKEN_FILE.write_text("{}", encoding="utf-8")
    return tmp_path


def _granted(days_ago: float, long_lived: bool = False):
    yt._grant_file().write_text(json.dumps({
        "granted_at": time.time() - days_ago * DAY,
        "long_lived": long_lived}), encoding="utf-8")


# ------------------------------------------------------------- quiet

def test_a_fresh_sign_in_says_nothing(home):
    _granted(0.2)
    got = yt.sign_in_health()
    assert got["warn"] is False
    assert got["why"] == ""


def test_it_stays_quiet_through_the_first_days(home):
    """A warning every day from day one is a warning nobody reads by day
    four, which is the day it starts to matter."""
    for d in (1, 2, 3, 4):
        _granted(d)
        assert yt.sign_in_health()["warn"] is False, d


def test_no_sign_in_at_all_is_not_a_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "TOKEN_FILE", tmp_path / "absent.json")
    assert yt.sign_in_health()["warn"] is False


def test_a_token_with_no_note_beside_it_is_not_a_warning(home):
    """Everyone who signed in before this existed. Warning them about an age
    that was never recorded would be inventing a number."""
    assert not yt._grant_file().exists()
    assert yt.sign_in_health()["warn"] is False


# --------------------------------------------------------- the window

@pytest.mark.parametrize("days", [5.0, 6.0, 6.9])
def test_it_speaks_up_while_the_fix_is_still_a_button(home, days):
    _granted(days)
    got = yt.sign_in_health()
    assert got["warn"] is True
    assert "Publish app" in got["why"]
    assert "Testing" in got["why"]


def test_it_says_how_long_is_left(home):
    _granted(5.0)
    assert "2 left" in yt.sign_in_health()["why"]


def test_past_seven_days_it_stops_promising_time(home):
    """The token may already be dead. "0 days left" reads as "you still have
    today"."""
    _granted(8.0)
    why = yt.sign_in_health()["why"]
    assert "any time now" in why


def test_it_says_how_to_make_the_notice_go_away(home):
    """Somebody who published the app months ago and sees this needs to know
    it will settle itself, or they will go and publish it again."""
    _granted(6.0)
    assert "goes away by itself" in yt.sign_in_health()["why"]


# ------------------------------------------- the proof, and the silence after

def test_a_proven_published_app_is_never_warned_about(home):
    _granted(400.0, long_lived=True)
    got = yt.sign_in_health()
    assert got["long_lived"] is True
    assert got["warn"] is False


def test_a_refresh_this_late_is_the_proof(home):
    """A Testing-mode token would have been rejected days ago, so a refresh
    that worked at day nine settles the question by evidence."""
    _granted(9.5)
    assert yt.sign_in_health()["long_lived"] is False

    yt._note_grant(fresh=False)                 # what a successful refresh does

    got = yt.sign_in_health()
    assert got["long_lived"] is True
    assert got["warn"] is False


def test_a_refresh_before_then_proves_nothing(home):
    """A Testing token is alive at day six too. Marking it published there
    would silence the warning exactly when it is needed."""
    _granted(6.0)
    yt._note_grant(fresh=False)
    got = yt.sign_in_health()
    assert got["long_lived"] is False
    assert got["warn"] is True


def test_signing_in_again_starts_the_clock_over(home):
    """A new consent is a new token with a new seven days, and carrying the
    old age forward would warn about a sign-in made a minute ago."""
    _granted(30.0, long_lived=True)
    yt._note_grant(fresh=True)
    got = yt.sign_in_health()
    assert got["days"] < 0.1
    assert got["long_lived"] is False, (
        "a fresh consent inherited a proof that was about the old token")
    assert got["warn"] is False


# ------------------------------------------------------ never in the way

def test_an_unreadable_note_is_silence_not_a_crash(home):
    yt._grant_file().write_text("{ not json", encoding="utf-8")
    assert yt.sign_in_health()["warn"] is False


def test_writing_the_note_never_raises(tmp_path, monkeypatch):
    """It is a note, not a credential. Failing to write it must not be able to
    stop somebody signing in."""
    monkeypatch.setattr(paths, "TOKEN_FILE",
                        tmp_path / "no" / "such" / "dir" / "token.json")
    monkeypatch.setattr(
        type(tmp_path), "mkdir",
        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    yt._note_grant(fresh=True)                   # and does not raise
