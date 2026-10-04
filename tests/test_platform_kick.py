"""Kick as a Platform, and the two things it does not share with Twitch.

The lifecycle is Twitch's and is covered there. What is worth asserting here
is where they differ, because those are the places a shared base class would
have hidden a bug: a two-hour token, and a stream key the API hands over.

No network.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time

import pytest

from autostream.platforms import NotConfigured, Platform, PlatformError, Session
from autostream.platforms import kick as kk


@pytest.fixture
def creds(tmp_path, monkeypatch):
    cred = tmp_path / "kick.json"
    cred.write_text(json.dumps({
        "client_id": "cid", "client_secret": "csecret"}), encoding="utf-8")
    monkeypatch.setattr(kk, "CRED_FILE", cred)
    monkeypatch.setattr(kk, "TOKEN_FILE", tmp_path / "kick_token.json")
    return cred


@pytest.fixture
def calls(monkeypatch):
    seen = []
    answers = {}

    def fake(self, method, path, *, params=None, body=None):
        seen.append({"method": method, "path": path,
                     "params": params or {}, "body": body})
        return answers.get((method, path), {})

    monkeypatch.setattr(kk.Kick, "_call", fake)
    monkeypatch.setattr(kk.Kick, "token", lambda self: "tok")
    return seen, answers


def test_kick_is_a_platform():
    assert isinstance(kk.Kick(), Platform)


# ------------------------------------------- difference 1: the stream key

def test_it_says_it_can_fetch_its_own_stream_key():
    """The one capability Twitch does not have, and the reason this is a flag
    rather than an assumption baked into the caller."""
    assert kk.Kick().caps.fetches_stream_key is True


def test_being_configured_does_not_require_a_stream_key(creds):
    """Kick hands the key over under `streamkey:read`. Requiring one in the
    file would refuse to start an install that is correctly set up."""
    assert kk.Kick().configured() is True


def test_starting_fetches_the_key_rather_than_asking_for_one(creds, calls):
    seen, answers = calls
    answers[("GET", "/channels")] = {
        "data": [{"broadcaster_user_id": "77", "slug": "yuvaneta"}]}
    answers[("GET", "/channels/stream-key")] = {"data": {"stream_key": "sk_live_x"}}

    s = kk.Kick().start("Friday night", category="VALORANT")

    assert s.stream_key == "sk_live_x"
    assert s.ingest_server == kk.INGEST
    assert s.watch_url == "https://kick.com/yuvaneta"
    assert any(c["path"] == "/channels/stream-key" for c in seen)


def test_a_key_the_scope_was_not_granted_for_is_empty_not_an_exception(creds,
                                                                       monkeypatch):
    """A user who ticked three of the four boxes should be told what to fix,
    not have the session die inside a helper."""
    def refuse(self, method, path, *, params=None, body=None):
        if path == "/channels/stream-key":
            raise PlatformError("scope not granted")
        return {}

    monkeypatch.setattr(kk.Kick, "_call", refuse)
    monkeypatch.setattr(kk.Kick, "token", lambda self: "tok")
    assert kk.Kick().stream_key() == ""


def test_a_key_already_in_the_file_is_used_without_asking(creds, calls):
    """Someone who pasted one should not have it overwritten by a fetch."""
    seen, answers = calls
    cfg = json.loads(creds.read_text(encoding="utf-8"))
    cfg["stream_key"] = "typed_by_hand"
    creds.write_text(json.dumps(cfg), encoding="utf-8")
    answers[("GET", "/channels")] = {"data": [{"broadcaster_user_id": "77",
                                               "slug": "y"}]}

    s = kk.Kick().start("t")

    assert s.stream_key == "typed_by_hand"
    assert not [c for c in seen if c["path"] == "/channels/stream-key"]


# ----------------------------------------------- difference 2: the token

def test_the_renewal_margin_is_wide_because_the_token_is_short(creds):
    """Two hours is shorter than a stream. The margin has to be big enough
    that a long session never reaches a dead token, and small enough that it
    is not renewing on every call."""
    assert kk.RENEW_MARGIN >= 120
    assert kk.RENEW_MARGIN < 7200 / 2


def test_a_token_with_an_hour_left_is_still_used(creds):
    kk.TOKEN_FILE.write_text(json.dumps({
        "access_token": "fine", "expires_in": 7200,
        "obtained_at": time.time() - 3600}), encoding="utf-8")
    assert kk.Kick().token() == "fine"


def test_a_token_inside_the_margin_is_renewed_before_it_is_used(creds,
                                                                monkeypatch):
    """THE ONE THAT BITES. A token taken at go-live is dead by the third game
    switch of a long stream, and the symptom is a retitle that silently stops
    working partway through."""
    kk.TOKEN_FILE.write_text(json.dumps({
        "access_token": "nearly", "refresh_token": "r1", "expires_in": 7200,
        "obtained_at": time.time() - 7000}), encoding="utf-8")   # 200s left
    monkeypatch.setattr(kk.Kick, "_form",
                        staticmethod(lambda url, data: {"access_token": "renewed",
                                                        "expires_in": 7200}))
    assert kk.Kick().token() == "renewed"


def test_a_refresh_without_a_new_refresh_token_keeps_the_old_one(creds,
                                                                 monkeypatch):
    kk.TOKEN_FILE.write_text(json.dumps({
        "access_token": "old", "refresh_token": "keep-me", "expires_in": 10,
        "obtained_at": time.time() - 100}), encoding="utf-8")
    monkeypatch.setattr(kk.Kick, "_form",
                        staticmethod(lambda url, data: {"access_token": "new",
                                                        "expires_in": 7200}))
    kk.Kick().token()
    saved = json.loads(kk.TOKEN_FILE.read_text(encoding="utf-8"))
    assert saved["refresh_token"] == "keep-me"


def test_never_authorised_asks_rather_than_failing_at_go_live(creds):
    with pytest.raises(NotConfigured) as e:
        kk.Kick().token()
    assert "Settings" in str(e.value)


# ------------------------------------------------------------- PKCE

def test_the_pkce_challenge_really_is_s256_of_the_verifier():
    """OAuth 2.1 allows no other method, and a challenge that does not match
    its verifier fails at the exchange with an error about the client."""
    verifier, challenge = kk.pkce_pair()
    want = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    assert challenge == want
    assert "=" not in challenge, "padding is not allowed in the challenge"
    assert 43 <= len(verifier) <= 128, "outside the length the spec allows"


def test_every_pkce_pair_is_different():
    pairs = {kk.pkce_pair()[0] for _ in range(50)}
    assert len(pairs) == 50


# ------------------------------------------------------- the lifecycle

def test_the_title_and_category_go_in_one_patch(creds, calls):
    seen, answers = calls
    answers[("GET", "/channels")] = {"data": [{"broadcaster_user_id": "77",
                                               "slug": "y"}]}
    answers[("GET", "/categories")] = {"data": [{"id": 42}]}

    kk.Kick().start("Playing CS2", category="Counter-Strike 2")

    patch = [c for c in seen if c["method"] == "PATCH"][0]
    assert patch["path"] == "/channels"
    assert patch["body"]["stream_title"] == "Playing CS2"
    assert patch["body"]["category_id"] == 42, "an id Kick gave as a number"


def test_an_unknown_category_does_not_stop_the_stream(creds, calls):
    seen, answers = calls
    answers[("GET", "/channels")] = {"data": [{"broadcaster_user_id": "77",
                                               "slug": "y"}]}
    answers[("GET", "/categories")] = {"data": []}

    kk.Kick().start("t", category="Nothing Kick Knows")

    patch = [c for c in seen if c["method"] == "PATCH"][0]
    assert "category_id" not in patch["body"]


def test_transitions_do_nothing_and_raise_nothing(creds, calls):
    k = kk.Kick()
    s = Session(handle="77")
    k.go_preview(s)
    k.go_live(s)
    k.stop(s)
    k.stop(s)
    seen, _ = calls
    assert not [c for c in seen if c["method"] != "GET"]


# ------------------------------------------------- Cloudflare, not Kick

def test_every_kick_request_carries_a_browser_user_agent(creds, monkeypatch):
    """FROM A REAL FAILURE. Kick sits behind Cloudflare, which bans on browser
    signature. urllib's default `Python-urllib/3.x` never reached Kick at all:
    the token endpoint answered 403 with the body `error code: 1010`, which is
    Cloudflare's "banned by signature" and reads exactly like Kick refusing
    the credentials. An hour went into the credentials, which were fine.

    Measured both ways against the live endpoint with the same client id,
    secret and a deliberately invalid code: 403/1010 with no User-Agent,
    401 with one. Nothing else differed."""
    sent = {}

    class Fake:
        status = 200
        def read(self): return b'{"access_token":"a","expires_in":7200}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def spy(req, timeout=None):
        sent["ua"] = req.get_header("User-agent") or ""
        return Fake()

    monkeypatch.setattr(kk.urllib.request, "urlopen", spy)
    kk.Kick().exchange("code", "verifier", "http://localhost:1/oauth/kick")

    assert sent["ua"], "no User-Agent: Cloudflare answers 403/1010"
    assert "Python-urllib" not in sent["ua"]
    assert kk.UA == sent["ua"]


def test_the_authorised_calls_carry_it_too(creds, monkeypatch):
    """The token endpoint is not the only thing behind Cloudflare -- a fetch
    of the stream key at go-live goes through the same front door."""
    sent = {}

    class Fake:
        def read(self): return b'{"data":[]}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def spy(req, timeout=None):
        sent["ua"] = req.get_header("User-agent") or ""
        return Fake()

    monkeypatch.setattr(kk.Kick, "token", lambda self: "tok")
    monkeypatch.setattr(kk.urllib.request, "urlopen", spy)
    kk.Kick()._call("GET", "/channels")
    assert sent["ua"] == kk.UA


def test_a_cloudflare_block_is_not_reported_as_a_credential_problem(creds,
                                                                    monkeypatch):
    """If it ever comes back, the message must not send somebody to the Kick
    developer console to re-copy a client secret that was never wrong."""
    def blocked(req, timeout=None):
        raise kk.urllib.error.HTTPError(
            req.full_url, 403, "Forbidden", {},
            __import__("io").BytesIO(b"error code: 1010 "))

    monkeypatch.setattr(kk.urllib.request, "urlopen", blocked)
    with pytest.raises(PlatformError) as e:
        kk.Kick().exchange("c", "v", "http://localhost:1/oauth/kick")
    said = str(e.value)
    assert "Cloudflare" in said
    assert "not in your account" in said


def test_a_stale_sign_in_code_says_to_press_connect_again(creds, monkeypatch):
    """Kick answers a spent or invented code with a bare 401 and no body.
    Passed through unchanged that is `Kick refused (401):` and nothing else."""
    def refuse(req, timeout=None):
        raise kk.urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {},
                                        __import__("io").BytesIO(b""))

    monkeypatch.setattr(kk.urllib.request, "urlopen", refuse)
    with pytest.raises(PlatformError) as e:
        kk.Kick().exchange("c", "v", "http://localhost:1/oauth/kick")
    said = str(e.value)
    assert "try again" in said
    assert "401" not in said, "a bare status code is not an instruction"
