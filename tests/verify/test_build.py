"""The thing that actually ships, started and driven.

Tier 5. Marked `build`, so it runs only under scripts\\verify.ps1 -Release.

Everything else in this suite imports autostream from the source tree. The
program the user runs is a PyInstaller bundle, and the ways a bundle differs
from a checkout -- a hidden import nothing collected, a data file the spec
never listed, a module imported lazily and therefore invisible to the
analysis -- are invisible to every other tier by construction. build.ps1's
import probe covers three modules; this covers the app answering requests.

The daemon is started in a throwaway AUTOSTREAM_HOME with youtube.enabled
off, which is the app's own supported no-op mode: no broadcast, no OAuth, no
quota, and is_configured() returns True so the setup wizard is skipped. It
touches nothing of the user's.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import appd
import pytest

pytestmark = pytest.mark.build

REPO = Path(__file__).resolve().parents[2]
BUILT = appd.BUILT
TOKEN = appd.TOKEN


@pytest.fixture(scope="module")
def daemon(tmp_path_factory):
    """The built app, started the one way both build tiers start it.

    Shared with tier 7 (the browser) through appd, so "how the real build is
    launched for a test" exists once: the same throwaway home, the same no-op
    config, the same refusal to touch a running AutoStream.
    """
    why = appd.why_not()
    if why:
        pytest.skip(why)
    from fakes import free_port

    home = tmp_path_factory.mktemp("built-home")
    port = free_port()
    appd.seed_home(home, port)
    try:
        base, proc = appd.start(home, port)
    except RuntimeError as e:
        pytest.fail(str(e))
    try:
        yield base, proc, home
    finally:
        appd.stop(base, proc)


def _get(base: str, path: str, timeout: float = 20.0):
    sep = "&" if "?" in path else "?"
    try:
        with urllib.request.urlopen(f"{base}{path}{sep}k={TOKEN}",
                                    timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_the_built_app_serves_its_page(daemon):
    base, _, _ = daemon
    status, body = _get(base, "/")
    assert status == 200
    assert b"<!DOCTYPE html>" in body or b"<!doctype html>" in body


def test_the_built_app_reports_a_status(daemon):
    base, _, _ = daemon
    status, body = _get(base, "/api/status")
    assert status == 200
    payload = json.loads(body)
    for key in ("phase", "apps", "clips"):
        assert key in payload, f"/api/status is missing {key} in the bundle"


def test_the_built_app_skips_setup_when_streaming_is_off(daemon):
    """youtube.enabled false means there is nothing to sign in to."""
    base, _, _ = daemon
    status, body = _get(base, "/api/bootstrap")
    assert status == 200
    assert json.loads(body).get("mode") == "dash"


def test_the_built_app_is_behind_its_token(daemon):
    """A packaging mistake that dropped the auth check would expose the
    machine on the LAN: the server binds 0.0.0.0."""
    base, _, _ = daemon
    try:
        with urllib.request.urlopen(f"{base}/api/status", timeout=10) as r:
            got = r.status
    except urllib.error.HTTPError as e:
        got = e.code
    assert got == 403


@pytest.mark.parametrize("path", [
    "/api/settings/schema",     # schema.py's tables
    "/api/settings/values",     # cfg + the seeded config
    "/api/clips/tools",         # ffmpeg/Tesseract discovery inside a bundle
    "/api/clips/games",         # the clip profiles and their templates
    "/api/clips/sessions",      # history
    "/api/clips/voices",        # the voice catalogue, lazily imported
    "/api/logs/tail?n=5",
])
def test_the_lazily_imported_corners_survive_packaging(daemon, path):
    """Each of these is the first thing to touch a subsystem the bundle only
    reaches at runtime. A missing hidden import shows up here as a 500 and
    nowhere else until a user presses the button."""
    base, _, _ = daemon
    status, body = _get(base, path)
    assert status == 200, f"{path} answered {status}: {body[:400]!r}"


def test_the_bundle_ships_the_clip_templates(daemon):
    """They live inside the package rather than config/, precisely so the
    share build cannot strip them. That only holds if the spec collects
    them."""
    base, _, _ = daemon
    status, body = _get(base, "/api/clips/games")
    assert status == 200
    text = body.decode("utf-8", "replace").lower()
    assert "delta force" in text, "the built app does not know about Delta Force"


def test_the_built_app_quits_when_asked(daemon):
    """The documented way to stop it, and the only one that works when it is
    elevated. build.ps1 depends on this: it cannot overwrite dist\\ while the
    app holds its log file open."""
    base, proc, _ = daemon
    req = urllib.request.Request(
        f"{base}/api/cmd?k={TOKEN}",
        data=json.dumps({"command": "quit"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 200
    try:
        proc.wait(timeout=45)
    except subprocess.TimeoutExpired:
        pytest.fail("the built app ignored Quit and had to be killed")
    assert proc.poll() is not None


def test_it_left_the_users_own_files_alone(daemon):
    """It ran against a throwaway home. Nothing it did should have reached
    the real one."""
    from autostream import paths

    base, _, home = daemon
    assert home.exists()
    real = Path(os.environ.get("AUTOSTREAM_HOME") or paths.ROOT)
    assert home.resolve() != real.resolve()
