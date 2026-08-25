"""Google's errors, translated into something a person can act on.

A real user hit `Error 403: access_denied` and the wizard showed them the raw
exception string. Google writes those messages for whoever wrote the API call,
not for the person who just clicked Connect -- and every one of these has a fix
the user can carry out themselves in about a minute.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.setup_flow import explain_auth_error               # noqa: E402


def says(err: str) -> str:
    return explain_auth_error(RuntimeError(err))


def test_the_403_names_both_ways_out():
    """The one a real user hit. Testing mode blocks everyone not on the list."""
    got = says("(access_denied) Error 403: access_denied")
    assert "Test users" in got
    assert "Publish app" in got
    assert "Testing" in got


def test_the_403_warns_about_the_unverified_screen():
    """Publishing works, then shows a scary screen. Saying so first stops the
    user concluding they broke something and going back."""
    got = says("Error 403: access_denied")
    assert "unsafe" in got.lower() or "not verified" in got.lower() \
        or "hasn't verified" in got.lower()


def test_an_expired_token_explains_the_seven_days():
    """Testing-mode logins expire weekly, which is why streaming stops dead
    days after a setup that worked."""
    got = says("invalid_grant: Token has been expired or revoked.")
    assert "seven days" in got
    assert "Publish" in got


def test_a_web_client_is_named_as_the_wrong_type():
    got = says("redirect_uri_mismatch")
    assert "Desktop app" in got


def test_an_api_that_was_never_enabled_says_which_one():
    got = says("accessNotConfigured: YouTube Data API v3 has not been used in "
               "project 12345 before or it is disabled")
    assert "YouTube Data API v3" in got
    assert "Enable" in got


def test_a_scope_problem_asks_for_a_fresh_sign_in():
    got = says("Request had insufficient authentication scopes.")
    assert "again" in got.lower()


def test_an_unknown_error_is_passed_through_not_swallowed():
    """Inventing an explanation for something unrecognised would be worse than
    the raw text: it would send the user somewhere irrelevant."""
    got = says("the disk caught fire")
    assert got == "the disk caught fire"


def test_a_very_long_unknown_error_is_trimmed():
    got = says("x" * 900)
    assert len(got) <= 300
