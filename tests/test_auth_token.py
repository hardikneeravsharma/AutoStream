"""A wrong token has to be refused, whatever it is made of.

Both servers compared the token with hmac.compare_digest on str values, which
raises TypeError the moment either side contains a non-ASCII character. So a
URL with an accent or an emoji in ?k= did not come back 403 -- it raised inside
the request handler, dropped the connection with no response, and wrote a
traceback. Anyone who could reach the port could do it by mistake, and the
phone dashboard is on the local network by design.

Reproduced against a real server before the fix: `k=caf%C3%A9` gave
RemoteDisconnected where `k=wrong` gave 403.
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import web, webui  # noqa: E402

# A wrong token, written in every way a URL can carry one.
WRONG = [
    ("k=wrong", "plain ascii"),
    ("k=caf%C3%A9", "an accent"),
    ("k=%F0%9F%94%A5", "an emoji"),
    ("k=%E4%B8%AD%E6%96%87", "chinese characters"),
    ("k=%C2%A0", "a non-breaking space"),
    ("k=", "an empty value"),
    ("", "no token at all"),
    ("k=probe%00", "a null byte"),
    ("k=probe&k=wrong", "two values"),
]


def _status(port, query):
    """-> the HTTP status, or the exception's name if there was no response."""
    url = f"http://127.0.0.1:{port}/api/status?{query}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:                              # noqa: BLE001
        return type(e).__name__


# ------------------------------------------------------------- the app's own

# Module-scoped on purpose: one server for every case below. A fresh one per
# test cannot rebind the port fast enough, and the tests then time out against
# nothing rather than testing anything.
@pytest.fixture(scope="module")
def app_server():
    s = webui.Server(token="probe-token", port=8871)
    assert s.start(), "the app server could not bind its port"
    yield 8871
    if s.httpd:
        s.httpd.shutdown()


def test_the_right_token_is_let_in(app_server):
    assert _status(app_server, "k=probe-token") == 200


@pytest.mark.parametrize("query,why", WRONG, ids=[w[1] for w in WRONG])
def test_a_wrong_token_is_refused_not_crashed_on(app_server, query, why):
    got = _status(app_server, query)
    assert got == 403, (
        f"{why} gave {got} instead of 403 -- a refusal has to be an answer, "
        f"not a dropped connection")


# --------------------------------------------------------- the LAN dashboard

class FakeEngine:
    """Just enough engine for the dashboard to answer /api/status.

    The state is the REAL State object, not a hand-written stand-in. A stub
    with a list of fields on it drifts the moment a field is added, and then
    this test fails for a reason that has nothing to do with tokens -- which
    is exactly what happened while it was being written.
    """

    def __init__(self):
        from autostream.state import State

        self.state = State()
        self.client_seen = 0.0
        self.obs_health = {}
        self.chat = []

    def submit(self, *a, **k):
        return None


@pytest.fixture(scope="module")
def phone_server():
    s = web.Dashboard(FakeEngine(), token="phone-token", port=8872)
    assert s.start(), "the phone dashboard could not bind its port"
    yield 8872
    s.stop()


@pytest.mark.parametrize("query,why", WRONG, ids=[w[1] for w in WRONG])
def test_the_phone_dashboard_refuses_the_same_way(phone_server, query, why):
    """This one is served on the local network on purpose, so anything that
    can be reached by a stranger's mistyped URL matters more here."""
    got = _status(phone_server, query)
    assert got == 403, f"{why} gave {got} instead of 403"


def test_the_phone_dashboard_lets_the_right_token_in(phone_server):
    assert _status(phone_server, "k=phone-token") == 200


# ------------------------------------------------------- and it stays honest

def test_the_comparison_is_still_constant_time():
    """The fix must not have turned this into ==.

    Encoding both sides keeps compare_digest in play; a plain equality check
    would leak the token one character at a time to anything that can time a
    request, which on a LAN dashboard is every device on the network.
    """
    import inspect

    for mod in (webui, web):
        src = inspect.getsource(mod._Handler._authed)
        assert "compare_digest" in src, f"{mod.__name__} no longer uses hmac"
        assert ".encode(" in src, (
            f"{mod.__name__} compares text again -- non-ASCII will raise")
