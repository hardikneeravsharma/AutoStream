"""Handing over to the installer.

A program cannot overwrite the files it is running from, so this step does not
try. It starts the installer, which knows how to wait for this process to exit,
and then leaves. Everything worth testing is about what it REFUSES to do:
interrupting a recording or a clip job to install an update would be a worse
bug than any update is likely to fix.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import webui  # noqa: E402


class FakeWindow:
    def __init__(self):
        self.quit_reason = None

    def request_quit(self, reason: str = "") -> None:
        self.quit_reason = reason


class FakeEngine:
    def __init__(self, phase="IDLE"):
        self.state = types.SimpleNamespace(phase=phase)


@pytest.fixture
def server(monkeypatch, tmp_path):
    """A Server with nothing running and no real subprocesses."""
    s = webui.Server.__new__(webui.Server)
    s.engine = None
    s.window = FakeWindow()
    s._update_job = {}

    idle = types.SimpleNamespace(busy=lambda: False)
    monkeypatch.setattr("autostream.clips.runner", lambda: idle)
    monkeypatch.setattr("autostream.clips.edit.editor", lambda: idle)

    started: list[list[str]] = []
    monkeypatch.setattr(webui.subprocess, "Popen",
                        lambda cmd, **kw: started.append(list(cmd)))
    s._started = started

    # The hand-off sleeps before quitting; tests should not.
    monkeypatch.setattr(webui.time, "sleep", lambda _s: None)
    return s


def _ready(server, tmp_path, name="AutoStream-9.9.9-setup.exe"):
    exe = tmp_path / name
    exe.write_bytes(b"MZ")
    server._update_job = {"state": "ready", "version": "9.9.9",
                          "path": str(exe), "done": 1, "total": 1, "error": ""}
    return exe


def test_nothing_downloaded_is_refused(server):
    assert "nothing downloaded" in server.update_install()["error"].lower()
    assert server._started == []


def test_a_download_still_running_is_refused(server, tmp_path):
    server._update_job = {"state": "downloading", "version": "9.9.9", "path": ""}
    assert "error" in server.update_install()
    assert server._started == []


def test_a_file_that_has_since_been_deleted_is_refused(server, tmp_path):
    exe = _ready(server, tmp_path)
    exe.unlink()
    assert "no longer there" in server.update_install()["error"]
    assert server._started == []


def test_a_zip_says_what_to_do_with_it_instead_of_running_it(server, tmp_path):
    """Executing an archive would fail; saying so is more use than a traceback."""
    _ready(server, tmp_path, name="AutoStream-share.zip")
    err = server.update_install()["error"]
    assert "zip" in err.lower()
    assert server._started == []


def test_a_live_session_is_not_interrupted(server, tmp_path):
    _ready(server, tmp_path)
    server.engine = FakeEngine(phase="LIVE")
    assert "session is running" in server.update_install()["error"].lower()
    assert server._started == []


def test_a_running_clip_job_is_not_interrupted(server, tmp_path, monkeypatch):
    _ready(server, tmp_path)
    busy = types.SimpleNamespace(busy=lambda: True)
    monkeypatch.setattr("autostream.clips.runner", lambda: busy)
    assert "clip job" in server.update_install()["error"].lower()
    assert server._started == []


def test_a_re_render_in_flight_is_not_interrupted(server, tmp_path, monkeypatch):
    _ready(server, tmp_path)
    busy = types.SimpleNamespace(busy=lambda: True)
    monkeypatch.setattr("autostream.clips.edit.editor", lambda: busy)
    assert "re-rendered" in server.update_install()["error"].lower()
    assert server._started == []


def test_the_installer_is_started_silently_and_restarts_the_app(server, tmp_path):
    exe = _ready(server, tmp_path)
    out = server.update_install()
    assert out.get("ok") is True
    assert out.get("version") == "9.9.9"

    assert len(server._started) == 1
    cmd = server._started[0]
    assert cmd[0] == str(exe)
    # Silent, closes this app itself, brings it back, and never reboots the
    # machine behind the user's back.
    for flag in ("/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS",
                 "/NORESTART"):
        assert flag in cmd, f"{flag} missing from {cmd}"


def test_the_app_leaves_after_replying_not_before(server, tmp_path):
    """The reply has to reach the page, so the quit happens on its own thread."""
    import threading

    _ready(server, tmp_path)
    assert server.window.quit_reason is None
    server.update_install()
    # Still open at the moment the answer was returned.
    for t in threading.enumerate():
        if t.name == "autostream-handover":
            t.join(timeout=5)
    assert server.window.quit_reason == "an update is being installed"


def test_a_failure_to_start_is_reported_not_raised(server, tmp_path, monkeypatch):
    _ready(server, tmp_path)

    def boom(cmd, **kw):
        raise OSError("blocked by policy")

    monkeypatch.setattr(webui.subprocess, "Popen", boom)
    assert "blocked by policy" in server.update_install()["error"]
    assert server.window.quit_reason is None
