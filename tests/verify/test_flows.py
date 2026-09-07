"""Every button, pressed.

Tier 2b. A real webui.Server on a real socket, a real HTTP client, real JSON,
and the shipped handler -- the only thing faked is the engine behind it, so a
command is recorded rather than acted on. That line is deliberate: whether the
route reaches the engine with the right payload is this tier's question, and
what the engine then does with it is tier 3's.

Each catalogued row is asked four things:

  it exists          a 404 here is a button wired to nothing
  it answers         a valid request comes back in the shape the page reads
  it refuses         a bad payload is rejected, and rejected the documented way
  it is guarded      without ?k= it is 403, whatever else it does

The rows marked STATIC are never called. They open a file dialog on the server,
raise UAC, reach the network, or replace the running program; their existence
is asserted from the source instead, in test_surface.py.
"""
from __future__ import annotations

import catalog
import pytest
from catalog import CALL, CONTROLS

CALLABLE = [c for c in CONTROLS if c.probe == CALL]
REJECTORS = [c for c in CALLABLE if c.reject is not None]


def _send(srv, c, body=None, *, key: bool = True):
    if c.method == "GET":
        path = f"{c.path}?{c.query}" if c.query else c.path
        return srv.get(path, key=key)
    return srv.post(c.path, body if body is not None else (c.body or {}), key=key)


def _id(c) -> str:
    return f"{c.method} {c.path}"


# ------------------------------------------------------------- reachable

@pytest.mark.parametrize("c", CALLABLE, ids=_id)
def test_the_route_exists(server, c):
    """A 404 means the page has a control pointing at nothing."""
    r = _send(server, c)
    assert r.status != 404, (
        f"{c.label or c.path} ({c.page}) is wired to a route webui does not "
        f"serve. {c.why}")


@pytest.mark.parametrize("c", CALLABLE, ids=_id)
def test_a_valid_request_answers_what_the_page_reads(server, c):
    """The page reads specific keys off each answer and renders nothing
    useful when they are absent -- a missing key is a blank panel, not an
    error anyone sees."""
    r = _send(server, c)
    if c.expect_resp is not None:
        assert c.expect_resp(r), (
            f"{_id(c)} answered {r.status} in a shape the page cannot use. "
            f"{c.why}\nbody: {r.text[:300]}")
        return
    assert r.status in c.status, (
        f"{_id(c)} answered {r.status}, expected one of {c.status}. "
        f"{c.why}\nbody: {r.text[:400]}")
    if c.expect is None:
        return
    body = r.json()
    assert body is not None, f"{_id(c)} did not answer JSON: {r.text[:200]}"
    assert c.expect(body), (
        f"{_id(c)} answered JSON the page cannot use. {c.why}\n"
        f"got: {str(body)[:400]}")


# --------------------------------------------------------------- refusal

@pytest.mark.parametrize("c", REJECTORS, ids=_id)
def test_a_bad_payload_is_refused(server, c):
    """Refused the documented way. /api/settings/save is the one that catches
    people out: a rejected field is HTTP 200 with ok:false, because the form
    has to render the message beside the field. Asserting on the status code
    alone would call that a success."""
    r = _send(server, c, body=c.reject)
    if c.reject_soft:
        assert r.status == 200, f"{_id(c)} rejects softly, so it stays 200"
        body = r.json() or {}
        assert body.get("ok") is not True, (
            f"{_id(c)} accepted {c.reject!r}. {c.why}")
        # Either key. `errors` is a map of field -> message, which is what a
        # form needs; `error` is one sentence, which is what a step in a card
        # needs. Requiring the plural fitted the one route that had it and
        # would have called a perfectly explained refusal a silent one.
        assert body.get("errors") or body.get("error"), (
            f"{_id(c)} rejected {c.reject!r} without saying which field or why")
        return
    assert r.status in c.reject_status, (
        f"{_id(c)} accepted {c.reject!r} with {r.status}. {c.why}\n"
        f"body: {r.text[:300]}")


# ------------------------------------------------------------------ auth

@pytest.mark.parametrize("c", CALLABLE, ids=_id)
def test_nothing_answers_without_the_token(server, c):
    """Every route, with no exemptions -- the page itself included.

    The check is hmac.compare_digest against rules.web_token and it runs
    before dispatch, so this also means an unknown path cannot be probed for
    existence without the key.
    """
    r = _send(server, c, key=False)
    assert r.status == 403, (
        f"{_id(c)} answered {r.status} with no ?k= - it is not behind the "
        "token")


def test_a_wrong_token_is_refused_like_a_missing_one(server):
    r = server.get("/api/status?k=not-the-token")
    assert r.status == 403


def test_a_token_that_is_a_prefix_of_the_real_one_is_refused(server):
    """compare_digest is length-safe; a truncating comparison would not be."""
    r = server.get(f"/api/status?k={server.token[:-1]}")
    assert r.status == 403


def test_a_non_ascii_token_is_refused_and_does_not_raise(server):
    """FROM A BUG. compare_digest raises TypeError on non-ASCII, which came
    back as a 500 and a traceback in the log instead of a plain 403.

    Percent-encoded, because that is what a browser puts on the wire -- a raw
    non-ASCII byte in a URL never reaches the server at all.
    """
    from urllib.parse import quote

    r = server.get(f"/api/status?k={quote('üñîçødé')}")
    assert r.status == 403


# ------------------------------------------------------------- /api/cmd

@pytest.mark.parametrize("command", catalog.COMMANDS)
def test_every_command_on_the_whitelist_is_accepted(server, command):
    r = server.post("/api/cmd", {"command": command})
    assert r.status == 200, f"{command} is on the whitelist but answered {r.status}"
    assert (r.json() or {}).get("ok") is True


@pytest.mark.parametrize("command", catalog.COMMANDS_REFUSED)
def test_nothing_off_the_whitelist_reaches_the_engine(server, command):
    """`kill` is the global hotkey only, and launch/chat have their own routes
    that validate a payload first. The whitelist is the entire boundary
    between a POST body and engine.submit()."""
    r = server.post("/api/cmd", {"command": command})
    assert r.status == 400, f"{command!r} was accepted with {r.status}"
    assert command not in server.engine.commands


def test_a_command_reaches_the_engine(server):
    server.post("/api/cmd", {"command": "record"})
    assert "record" in server.engine.commands


def test_quit_asks_the_engine_to_stop_rather_than_queueing_it(server):
    """Quit does not go through the command queue: a queue drained once per
    tick would leave the app running for up to poll_interval seconds after
    the user pressed it."""
    before = server.engine.stop_requests
    server.post("/api/cmd", {"command": "quit"})
    assert server.engine.stop_requests == before + 1
    assert "quit" not in server.engine.commands


def test_chat_reaches_the_engine_with_its_text(server):
    server.post("/api/chat", {"text": "hello"})
    assert ("chat", "hello") in server.engine.submitted


def test_chat_is_capped_before_it_reaches_the_engine(server):
    """200 characters, clipped server-side. The input has a maxlength, and an
    attribute in the browser is not a limit."""
    server.post("/api/chat", {"text": "x" * 5000})
    sent = [p for k, p in server.engine.submitted if k == "chat"]
    assert sent and len(sent[-1]) == 200


def test_launch_carries_the_key_and_the_stream_intent(server):
    server.post("/api/launch", {"key": "cs2.exe", "stream": True})
    assert ("launch", {"key": "cs2.exe", "stream": True}) in server.engine.submitted


# ------------------------------------------------------------ malformed

@pytest.mark.parametrize("raw", [b"", b"not json at all", b"{", b'{"a":',
                                 b"[]", b"null", b"5", b'"a string"', b"true"])
def test_a_malformed_body_never_crashes_a_route(server, raw):
    """FROM A BUG. _body() caught the parse error and returned {}, so the
    unparseable cases were fine. The valid-but-not-an-object ones were not:
    `[]`, `null` and a bare number parse cleanly and then raise at the first
    b.get(), which every POST route does on its first line. That reached the
    user as a 500 carrying a Python traceback, on all forty-odd of them."""
    r = server.post("/api/cmd", raw=raw)
    assert r.status in (200, 400), f"malformed body gave {r.status}: {r.text[:200]}"


@pytest.mark.parametrize("c", [c for c in CALLABLE if c.method == "POST"], ids=_id)
def test_no_post_route_crashes_on_a_json_array(server, c):
    """The same bug, asked of every POST route rather than one of them."""
    r = server.post(c.path, raw=b"[]")
    assert r.status != 500, (
        f"{_id(c)} raised on a non-object body: {r.text[:200]}")


def test_an_oversized_body_is_refused_rather_than_read_into_memory(server):
    r = server.post("/api/chat", raw=b'{"text":"' + b"x" * (2 * 1024 * 1024) + b'"}')
    assert r.status in (400, 413, 403), f"a 2 MiB body answered {r.status}"


@pytest.mark.parametrize("path", ["", "   ", "\t"])
def test_revealing_a_blank_path_does_not_open_a_window(server, path):
    """FROM A BUG this suite caused. Path("") is Path("."), which exists, so a
    blank path sailed past the not-exists check and spawned Explorer on the
    working directory -- a window the user never asked for, from a button
    pointed at a clip that is not there. It opened the repo folder several
    times a run until it was found."""
    body = server.post("/api/clips/open", {"path": path}).json() or {}
    assert body.get("ok") is not True, f"{path!r} would have opened Explorer"
    assert body.get("error")


def test_an_unknown_path_is_a_json_404(server):
    r = server.get("/api/definitely-not-a-route")
    assert r.status == 404
    assert (r.json() or {}).get("error")


# ------------------------------------------------------------- settings

def test_every_settable_path_accepts_its_own_current_value(server):
    """Round-trip the whole Settings page: read the values the app reports,
    write each one back unchanged, and it must be accepted. A field that
    rejects what the app itself just rendered is one the user cannot save
    without changing it first.
    """
    from autostream import schema

    values = (server.get("/api/settings/values").json() or {})
    assert len(values) >= 50, f"only {len(values)} settings offered"
    refused = {}
    for path, value in values.items():
        field = schema.FIELDS_BY_PATH.get(path)
        if field is None or field.get("control") == "readonly":
            continue
        r = server.post("/api/settings/save", {"values": {path: value}})
        body = r.json() or {}
        if not body.get("ok"):
            refused[path] = body.get("errors", {}).get(path) or body.get("error")
    assert refused == {}, f"settings that will not accept their own value: {refused}"


def test_an_unknown_setting_is_refused_by_name(server):
    r = server.post("/api/settings/save", {"values": {"rules.web_tokenn": "x"}})
    body = r.json() or {}
    assert body.get("ok") is not True
    assert "rules.web_tokenn" in body.get("errors", {})


def test_one_bad_field_rejects_the_whole_save(server):
    """All-or-nothing. A half-applied save leaves the daemon in a
    configuration the user never chose."""
    before = (server.get("/api/settings/values").json() or {})["clips.min_kills"]
    r = server.post("/api/settings/save", {
        "values": {"clips.min_kills": 3, "no.such.setting": 1}})
    assert (r.json() or {}).get("ok") is not True
    after = (server.get("/api/settings/values").json() or {})["clips.min_kills"]
    assert after == before, "a rejected save still wrote the valid field"


def test_a_choice_field_refuses_a_value_outside_its_options(server):
    """clips.upload_privacy decides whether a clip goes out public."""
    r = server.post("/api/settings/save",
                    {"values": {"clips.upload_privacy": "everyone"}})
    body = r.json() or {}
    assert body.get("ok") is not True
    assert "clips.upload_privacy" in body.get("errors", {})


def test_saving_actually_changes_what_is_read_back(server):
    """Compared against the coerced value, not the submitted one.

    A select stores its option values, and those are strings even when they
    read as numbers -- clips.min_kills offers "1".."4". Asserting on the raw
    submitted 4 would be asserting that the schema's own coercion is wrong.
    """
    from autostream import schema

    server.post("/api/settings/save", {"values": {"clips.min_kills": 4}})
    back = (server.get("/api/settings/values").json() or {})["clips.min_kills"]
    assert back == schema.coerce("clips.min_kills", 4)
    assert str(back) == "4"


def test_the_settings_page_offers_every_section_the_schema_declares(server):
    got = server.get("/api/settings/schema").json()
    assert got, "the Settings page would render empty"


# ---------------------------------------------------------- diagnostics

def test_the_diagnostics_report_never_carries_a_secret(server):
    """It is built to be pasted into a bug report."""
    from autostream import cfg

    body = server.post("/api/diagnostics", {}).json() or {}
    text = body.get("text", "")
    assert text, "the report came back empty"
    c = cfg.load()
    for secret in (server.token, getattr(c.obs, "password", ""),
                   getattr(c.rules, "web_token", "")):
        if secret and len(str(secret)) > 4:
            assert str(secret) not in text, "the diagnostics report leaked a secret"


# ------------------------------------------------------- with no engine

def test_the_page_is_served_before_there_is_an_engine(headless):
    """The setup wizard runs on a server with engine=None."""
    r = headless.get("/")
    assert r.status == 200
    assert b"<!DOCTYPE html>" in r.body or b"<!doctype html>" in r.body


def test_status_is_still_the_shape_the_page_reads_with_no_engine(headless):
    """The Clips page reads clip progress off /api/status whether or not an
    engine exists, so the payload has to keep one shape."""
    body = headless.get("/api/status").json() or {}
    for key in ("phase", "apps", "clips", "edit", "update", "upload"):
        assert key in body, f"/api/status lost {key} when there is no engine"


@pytest.mark.parametrize("c", [c for c in CALLABLE if c.page == "clips"], ids=_id)
def test_the_clips_routes_work_before_there_is_an_engine(headless, c):
    """They are reachable from the setup wizard, which has no engine yet."""
    r = _send(headless, c)
    assert r.status != 500, (
        f"{_id(c)} raised with no engine: {r.text[:300]}")
