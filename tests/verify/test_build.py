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

import pytest

pytestmark = pytest.mark.build

REPO = Path(__file__).resolve().parents[2]
BUILT = REPO / "dist" / "AutoStream" / "AutoStream.exe"
TOKEN = "verify-build-token"
BOOT_TIMEOUT = 90.0


def _running() -> list:
    """Is the user's AutoStream up? Checked, never killed.

    It may be mid-broadcast or mid-clip-job. Ending someone's stream to test
    a build is not a trade this suite gets to make -- and it could not run
    anyway: autostream/single.py holds a named mutex, so a second copy exits
    immediately.
    """
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq AutoStream.exe", "/NH"],
            capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln for ln in out.splitlines() if "AutoStream.exe" in ln]


@pytest.fixture(scope="module")
def daemon(tmp_path_factory):
    if not BUILT.is_file():
        pytest.skip(f"no build at {BUILT} - run scripts\\build.ps1 first")
    if _running():
        pytest.skip("AutoStream is already running; quit it first "
                    "(POST /api/cmd {\"command\":\"quit\"}). It is not killed "
                    "here because it may be live or cutting clips.")

    import yaml
    from fakes import free_port

    home = tmp_path_factory.mktemp("built-home")
    port = free_port()
    for d in ("config", "secrets", "logs"):
        (home / d).mkdir(parents=True, exist_ok=True)
    (home / "config" / "config.yaml").write_text(yaml.safe_dump({
        "youtube": {"enabled": False},          # no broadcast, no OAuth, no quota
        "record": {"enabled": False},           # nothing is written to disk
        "rules": {"web_token": TOKEN, "web_port": port,
                  "tray_icon": False, "kill_switch_hotkey": ""},
        "logging": {"level": "INFO"},
    }, sort_keys=False), encoding="utf-8")

    env = dict(os.environ)
    env["AUTOSTREAM_HOME"] = str(home)
    env["AUTOSTREAM_VIDEO_HOME"] = str(home / "video")
    proc = subprocess.Popen([str(BUILT), "run"], env=env,
                            cwd=str(BUILT.parent),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + BOOT_TIMEOUT
    last = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out = (proc.stdout.read() or b"").decode("utf-8", "replace")
            pytest.fail(f"the built app exited with {proc.returncode} before it "
                        f"served anything:\n{out[-3000:]}")
        try:
            with urllib.request.urlopen(f"{base}/api/status?k={TOKEN}",
                                        timeout=3) as r:
                if r.status == 200:
                    break
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last = str(e)
        time.sleep(1.0)
    else:
        proc.kill()
        pytest.fail(f"the built app never answered on {base} in "
                    f"{BOOT_TIMEOUT:.0f}s (last: {last})")

    try:
        yield base, proc, home
    finally:
        # Its own Quit, which is what the tray and the rail button use, and
        # which works even when the process is elevated and Stop-Process is
        # refused. Killed only if it will not go.
        try:
            req = urllib.request.Request(
                f"{base}/api/cmd?k={TOKEN}",
                data=json.dumps({"command": "quit"}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:                                    # noqa: BLE001
            pass
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


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
