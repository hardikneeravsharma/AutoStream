"""The first step of setting the app up, which had no tests at all.

WHY THIS ONE MATTERS MORE THAN MOST
    It is the first thing a new user does, and the next thing that happens
    after it is an OAuth round trip to Google. Being wrong here does not
    produce an error about the wrong file -- it produces one of Google's own
    messages, two steps later, about something else.

    And there were two ways in. Pasting the JSON was validated; letting the
    app find the file in Downloads was not, so a stale Web client or a
    downloaded API key was copied straight in and the install was broken
    before it began.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.setup_flow import SetupFlow, explain_auth_error  # noqa: E402

DESKTOP = {"installed": {"client_id": "1234.apps.googleusercontent.com",
                         "client_secret": "GOCSPX-abc",
                         "redirect_uris": ["http://localhost"]}}
WEB = {"web": {"client_id": "1234.apps.googleusercontent.com",
               "client_secret": "GOCSPX-abc"}}
API_KEY = {"api_key": "AIzaSyExample"}


@pytest.fixture
def flow(tmp_path, monkeypatch):
    """A SetupFlow whose files and Downloads folder are ours."""
    from autostream import paths

    monkeypatch.setattr(paths, "CLIENT_SECRET", tmp_path / "secrets" /
                        "client_secret.json")
    monkeypatch.setattr(paths, "ensure_dirs",
                        lambda: (tmp_path / "secrets").mkdir(exist_ok=True))

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr("os.path.expanduser",
                        lambda p: str(downloads) if "Downloads" in p
                        else str(tmp_path / "Desktop"))

    f = SetupFlow()
    monkeypatch.setattr(f, "snapshot", lambda: {"stub": True})
    f._downloads = downloads
    f._saved = paths.CLIENT_SECRET
    return f


def _download(flow, name, payload, age=0.0):
    p = flow._downloads / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    if age:
        old = time.time() - age
        import os

        os.utime(p, (old, old))
    return p


# ----------------------------------------------------------- the validation

def test_a_desktop_client_is_accepted(flow):
    data, why = flow.check_client_secret(json.dumps(DESKTOP))
    assert data and not why


def test_a_web_client_is_named_as_a_web_client(flow):
    """It HAS a client_id, so "no client_id" would send somebody looking for
    a problem that is not the problem."""
    data, why = flow.check_client_secret(json.dumps(WEB))
    assert data is None
    assert "Web client" in why


def test_an_api_key_is_told_what_to_download_instead(flow):
    data, why = flow.check_client_secret(json.dumps(API_KEY))
    assert data is None
    assert "not an API key" in why


def test_a_client_with_no_secret_is_refused(flow):
    data, why = flow.check_client_secret(
        json.dumps({"installed": {"client_id": "x"}}))
    assert data is None
    assert "client_secret" in why


def test_rubbish_is_refused_without_a_traceback(flow):
    for raw in ("", "not json", "[1,2,3]", "null", '"a string"'):
        data, why = flow.check_client_secret(raw)
        assert data is None and why


# -------------------------------------------------- finding it in Downloads

def test_the_downloaded_file_is_used(flow):
    _download(flow, "client_secret_123.json", DESKTOP)
    out = flow.save_client_secret("")
    assert out["ok"], out
    saved = json.loads(flow._saved.read_text(encoding="utf-8"))
    assert saved["installed"]["client_id"] == DESKTOP["installed"]["client_id"]


def test_a_downloaded_web_client_is_REFUSED_not_copied_in(flow):
    """The bug. The paste path caught this; the find path did not, so the
    install was broken two steps before Google said anything about it."""
    _download(flow, "client_secret_web.json", WEB)
    out = flow.save_client_secret("")
    assert not out["ok"]
    assert not flow._saved.exists(), "a Web client was saved as credentials"


def test_a_downloaded_api_key_is_refused(flow):
    _download(flow, "client_secret_key.json", API_KEY)
    out = flow.save_client_secret("")
    assert not out["ok"]
    assert not flow._saved.exists()


def test_the_newest_USABLE_file_wins_not_just_the_newest(flow):
    """Somebody who downloaded the right client and then an API key should
    still be set up, not blocked by the newer wrong file."""
    _download(flow, "client_secret_good.json", DESKTOP, age=600)
    _download(flow, "client_secret_newer_but_wrong.json", API_KEY)
    out = flow.save_client_secret("")
    assert out["ok"], "the newer, useless file won"
    saved = json.loads(flow._saved.read_text(encoding="utf-8"))
    assert "installed" in saved


def test_the_newest_of_two_good_files_wins(flow):
    older = dict(DESKTOP)
    older = {"installed": dict(DESKTOP["installed"], client_id="old.apps")}
    _download(flow, "client_secret_old.json", older, age=600)
    _download(flow, "client_secret_new.json", DESKTOP)
    flow.save_client_secret("")
    saved = json.loads(flow._saved.read_text(encoding="utf-8"))
    assert saved["installed"]["client_id"] == DESKTOP["installed"]["client_id"]


def test_nothing_downloaded_says_what_to_do(flow):
    out = flow.save_client_secret("")
    assert not out["ok"]
    assert "download" in out["error"].lower()


def test_an_unreadable_candidate_is_skipped_not_fatal(flow, monkeypatch):
    _download(flow, "client_secret_good.json", DESKTOP, age=600)
    bad = _download(flow, "client_secret_locked.json", DESKTOP)

    real = Path.read_text

    def maybe(self, *a, **k):
        if self == bad:
            raise OSError("in use by another process")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", maybe)
    assert flow.save_client_secret("")["ok"]


def test_the_saved_file_is_this_apps_own_copy(flow):
    """Rewritten rather than copied, so it does not inherit whatever
    permissions a file in Downloads happened to have."""
    p = _download(flow, "client_secret_123.json", DESKTOP)
    flow.save_client_secret("")
    # Same content, different file, and formatted by us.
    assert flow._saved.read_text(encoding="utf-8") != p.read_text(encoding="utf-8")
    assert json.loads(flow._saved.read_text(encoding="utf-8")) == DESKTOP


# ---------------------------------------------- Google's errors, translated

def test_a_blocked_test_user_is_explained_with_a_way_out():
    said = explain_auth_error(Exception("access_denied"))
    assert "Test users" in said and "Publish app" in said


def test_an_expired_login_explains_the_seven_day_rule():
    said = explain_auth_error(Exception("invalid_grant: token expired"))
    assert "seven days" in said


def test_the_wrong_client_type_is_explained():
    said = explain_auth_error(Exception("redirect_uri_mismatch"))
    assert "Desktop app client" in said


def test_an_error_nobody_anticipated_still_says_something():
    said = explain_auth_error(Exception("something entirely new"))
    assert said and isinstance(said, str)
