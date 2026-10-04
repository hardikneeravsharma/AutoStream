"""Twitch as a Platform: what it does, and what it correctly refuses to.

No network. Every HTTP call is replaced, because the point of these is the
decisions this module makes -- which call to send, what to do with a game
Twitch has never heard of, when a token is too old to use -- and not whether
Twitch is up.
"""
from __future__ import annotations

import json
import time

import pytest

from autostream.platforms import (Capabilities, NotConfigured, Platform,
                                  PlatformError, Session)
from autostream.platforms import twitch as tw


@pytest.fixture
def creds(tmp_path, monkeypatch):
    """A configured install, pointing at a throwaway secrets directory."""
    cred = tmp_path / "twitch.json"
    cred.write_text(json.dumps({
        "client_id": "cid", "client_secret": "csecret",
        "stream_key": "live_123", "broadcaster_id": "99", "login": "yuvaneta",
    }), encoding="utf-8")
    monkeypatch.setattr(tw, "CRED_FILE", cred)
    monkeypatch.setattr(tw, "TOKEN_FILE", tmp_path / "twitch_token.json")
    return cred


@pytest.fixture
def calls(monkeypatch):
    """Every API call this module makes, and canned answers for them."""
    seen = []
    answers = {}

    def fake(self, method, path, *, params=None, body=None):
        seen.append({"method": method, "path": path,
                     "params": params or {}, "body": body})
        return answers.get((method, path), {})

    monkeypatch.setattr(tw.Twitch, "_call", fake)
    monkeypatch.setattr(tw.Twitch, "token", lambda self: "tok")
    return seen, answers


# ------------------------------------------------------------ the shape

def test_twitch_is_a_platform():
    assert isinstance(tw.Twitch(), Platform)


def test_it_says_what_it_cannot_do(creds):
    """The capability flags are the point of the seam. Twitch has no preview
    state, no quota, no chat through this file and no thumbnail -- and the
    engine reads these rather than calling methods that return None."""
    c = tw.Twitch().caps
    assert isinstance(c, Capabilities)
    assert c.waits_for_ingest is False, "pushing RTMP is already going live"
    assert c.has_preview is False
    assert c.has_quota is False
    assert c.has_chat is False
    assert c.has_thumbnail is False
    assert c.fetches_stream_key is False, "Twitch has no endpoint for the key"


# ------------------------------------------------------- not set up yet

def test_missing_credentials_are_a_question_for_the_user(tmp_path, monkeypatch):
    monkeypatch.setattr(tw, "CRED_FILE", tmp_path / "nothing.json")
    t = tw.Twitch()
    assert t.configured() is False
    with pytest.raises(NotConfigured) as e:
        t.preflight()
    # It now comes through `creds()`, which names the file as well as the
    # keys -- `ready()` stopped asking `configured()` because a stream key
    # alone is enough to go live.
    said = str(e.value).lower()
    assert "client_id" in said and "stream_key" in said


def test_half_filled_credentials_do_not_count_as_configured(tmp_path,
                                                            monkeypatch):
    """A client id with no stream key cannot start a stream, and finding that
    out at go-live wastes the session."""
    cred = tmp_path / "twitch.json"
    cred.write_text(json.dumps({"client_id": "cid", "client_secret": "s"}),
                    encoding="utf-8")
    monkeypatch.setattr(tw, "CRED_FILE", cred)
    assert tw.Twitch().configured() is False


def test_never_authorised_says_so_rather_than_failing_at_go_live(creds,
                                                                 monkeypatch):
    monkeypatch.setattr(tw, "TOKEN_FILE", creds.parent / "absent.json")
    with pytest.raises(NotConfigured) as e:
        tw.Twitch().token()
    assert "authorised" in str(e.value).lower()


# ------------------------------------------------------------ the token

def test_a_fresh_token_is_reused(creds):
    t = tw.Twitch()
    tw.TOKEN_FILE.write_text(json.dumps({
        "access_token": "good", "expires_in": 3600,
        "obtained_at": time.time()}), encoding="utf-8")
    assert t.token() == "good"


def test_a_token_about_to_expire_is_refreshed_rather_than_used(creds,
                                                               monkeypatch):
    """THE TWO-MINUTE MARGIN. A token that expires between the check and the
    request fails the request, and a 401 reads as a revoked authorisation
    rather than a stale clock."""
    tw.TOKEN_FILE.write_text(json.dumps({
        "access_token": "nearly-dead", "refresh_token": "r1",
        "expires_in": 3600,
        "obtained_at": time.time() - 3540}), encoding="utf-8")  # 60s left
    monkeypatch.setattr(tw, "_post_form",
                        lambda url, data: {"access_token": "renewed",
                                           "expires_in": 3600})
    assert tw.Twitch().token() == "renewed"


def test_a_refresh_that_returns_no_refresh_token_keeps_the_old_one(creds,
                                                                   monkeypatch):
    """Twitch usually returns a new one. When it does not, dropping the old
    one is the difference between renewing forever and asking the user to
    sign in again tomorrow."""
    tw.TOKEN_FILE.write_text(json.dumps({
        "access_token": "old", "refresh_token": "keep-me",
        "expires_in": 10, "obtained_at": time.time() - 100}), encoding="utf-8")
    monkeypatch.setattr(tw, "_post_form",
                        lambda url, data: {"access_token": "new",
                                           "expires_in": 3600})
    t = tw.Twitch()
    t.token()
    saved = json.loads(tw.TOKEN_FILE.read_text(encoding="utf-8"))
    assert saved["refresh_token"] == "keep-me"


# ------------------------------------------------------- going live

def test_starting_sets_the_title_and_hands_back_where_obs_pushes(creds, calls):
    seen, answers = calls
    answers[("GET", "/games")] = {"data": [{"id": "516575", "name": "VALORANT"}]}

    s = tw.Twitch().start("VALORANT - Friday night", category="VALORANT")

    patch = [c for c in seen if c["method"] == "PATCH"]
    assert len(patch) == 1, seen
    assert patch[0]["path"] == "/channels"
    assert patch[0]["params"]["broadcaster_id"] == "99"
    assert patch[0]["body"]["title"] == "VALORANT - Friday night"
    assert patch[0]["body"]["game_id"] == "516575"

    assert isinstance(s, Session)
    assert s.ingest_server == tw.INGEST
    assert s.stream_key == "live_123"
    assert s.watch_url == "https://twitch.tv/yuvaneta"


def test_a_game_twitch_has_never_heard_of_does_not_stop_the_stream(creds, calls):
    """Twitch's directory does not carry everything. A stream with the right
    title under no category beats a stream that refused to start."""
    seen, answers = calls
    answers[("GET", "/games")] = {"data": []}

    tw.Twitch().start("Some indie game", category="Totally Unknown Game")

    patch = [c for c in seen if c["method"] == "PATCH"][0]
    assert "title" in patch["body"]
    assert "game_id" not in patch["body"], "an empty category was sent anyway"


def test_a_category_lookup_that_fails_does_not_stop_the_stream(creds,
                                                               monkeypatch):
    def boom(self, method, path, *, params=None, body=None):
        if path == "/games":
            raise PlatformError("Twitch is having a day")
        return {}

    monkeypatch.setattr(tw.Twitch, "_call", boom)
    monkeypatch.setattr(tw.Twitch, "token", lambda self: "tok")
    assert tw.Twitch().game_id("VALORANT") == ""


def test_the_category_is_looked_up_once_and_remembered(creds, calls):
    """The same game is set at every retitle, and a session that switches back
    and forth would otherwise ask Twitch each time."""
    seen, answers = calls
    answers[("GET", "/games")] = {"data": [{"id": "32399"}]}
    t = tw.Twitch()
    for _ in range(4):
        t.game_id("Counter-Strike 2")
    assert len([c for c in seen if c["path"] == "/games"]) == 1


def test_a_long_title_is_cut_rather_than_refused(creds, calls):
    seen, _ = calls
    tw.Twitch().start("x" * 400)
    patch = [c for c in seen if c["method"] == "PATCH"][0]
    assert len(patch["body"]["title"]) == 140


def test_going_live_and_preview_do_nothing_and_raise_nothing(creds, calls):
    """There is no preview state and nothing to transition. The engine calls
    these on every platform; here they must be harmless."""
    t = tw.Twitch()
    s = Session(handle="99")
    t.go_preview(s)
    t.go_live(s)
    t.stop(s)
    seen, _ = calls
    assert not [c for c in seen if c["method"] != "GET"], (
        "something was sent for a transition Twitch does not have")


def test_stopping_twice_is_not_an_error(creds, calls):
    t = tw.Twitch()
    s = Session(handle="99")
    t.stop(s)
    t.stop(s)


# ------------------------------------------------------------ retitling

def test_a_game_switch_retitles_the_channel(creds, calls):
    seen, answers = calls
    answers[("GET", "/games")] = {"data": [{"id": "32399"}]}
    t = tw.Twitch()
    assert t.retitle(Session(handle="99"), "Now playing CS2",
                     category="Counter-Strike 2") is True
    patch = [c for c in seen if c["method"] == "PATCH"][0]
    assert patch["body"]["title"] == "Now playing CS2"
    assert patch["body"]["game_id"] == "32399"


def test_a_retitle_with_nothing_in_it_sends_nothing(creds, calls):
    seen, _ = calls
    assert tw.Twitch().retitle(Session(handle="99"), "", category="") is False
    assert not [c for c in seen if c["method"] == "PATCH"]


# ------------------------------------------------- when Twitch says no

def test_an_expired_authorisation_asks_the_user_rather_than_retrying(creds,
                                                                     monkeypatch):
    """401 and 403 are not transient. Telling the engine to try again would
    spend a session discovering the same thing."""
    import urllib.error

    def unauthorised(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(tw.Twitch, "token", lambda self: "tok")
    monkeypatch.setattr(tw.urllib.request, "urlopen", unauthorised)
    with pytest.raises(NotConfigured) as e:
        tw.Twitch()._call("GET", "/users")
    assert "Settings" in str(e.value)


def test_twitch_being_unreachable_is_a_platform_error_not_a_crash(creds,
                                                                  monkeypatch):
    monkeypatch.setattr(tw.Twitch, "token", lambda self: "tok")

    def down(req, timeout=None):
        raise OSError("no route to host")

    monkeypatch.setattr(tw.urllib.request, "urlopen", down)
    with pytest.raises(PlatformError):
        tw.Twitch()._call("GET", "/users")


def test_a_label_pasted_with_the_value_is_caught_at_the_source(tmp_path,
                                                               monkeypatch):
    """FROM A REAL HOUR LOST. A notes file held `<id> - twitch client ID` per
    line, the suffix reached the JSON, and the authorize URL carried
    `client_id=ckldy...+-+twitch+client+ID`. Twitch said
    `{"status":400,"message":"invalid client"}` -- true, and silent about why.

    No credential Twitch issues contains a space, so this cannot be a false
    positive."""
    cred = tmp_path / "twitch.json"
    cred.write_text(json.dumps({
        "client_id": "ckldyamyr9k068b0pumq95ognabvrl - twitch client ID",
        "client_secret": "abc", "stream_key": "live_1"}), encoding="utf-8")
    monkeypatch.setattr(tw, "CRED_FILE", cred)
    with pytest.raises(NotConfigured) as e:
        tw.Twitch().creds()
    said = str(e.value)
    assert "label" in said
    assert "30 characters" in said, said


def test_a_stream_key_on_its_own_is_enough_to_go_live(tmp_path, monkeypatch):
    """The client id and secret exist for ONE purpose: setting the title and
    category over the API. Somebody who pasted a key and wants nothing else
    can stream without either, and requiring them left a first run where a
    valid key had just been saved and Continue stayed grey."""
    cred = tmp_path / "twitch.json"
    cred.write_text(json.dumps({"stream_key": "live_only_a_key"}),
                    encoding="utf-8")
    monkeypatch.setattr(tw, "CRED_FILE", cred)
    monkeypatch.setattr(tw, "TOKEN_FILE", tmp_path / "absent.json")

    t = tw.Twitch()
    ok, why = t.ready()
    assert ok is True
    assert "not signed in" in why, "it must still say the title will not be set"
    t.preflight()                       # and does not raise


def test_no_key_is_refused_however_much_else_there_is(tmp_path, monkeypatch):
    cred = tmp_path / "twitch.json"
    cred.write_text(json.dumps({"client_id": "a" * 30,
                                "client_secret": "b" * 30}), encoding="utf-8")
    monkeypatch.setattr(tw, "CRED_FILE", cred)
    monkeypatch.setattr(tw, "TOKEN_FILE", tmp_path / "absent.json")
    ok, why = tw.Twitch().ready()
    assert ok is False
    assert "stream key" in why.lower()


def test_a_clean_credential_is_left_alone(tmp_path, monkeypatch):
    cred = tmp_path / "twitch.json"
    cred.write_text(json.dumps({
        "client_id": "ckldyamyr9k068b0pumq95ognabvrl",
        "client_secret": "s" * 30, "stream_key": "live_abc"}), encoding="utf-8")
    monkeypatch.setattr(tw, "CRED_FILE", cred)
    got = tw.Twitch().creds()
    assert got["client_id"] == "ckldyamyr9k068b0pumq95ognabvrl"
