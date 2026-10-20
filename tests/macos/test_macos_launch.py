"""`autostream run` on a Mac: the server and the window, no engine -- and the
Windows launch never reaching any of it."""
from __future__ import annotations

import sys
import types

import pytest

from autostream import __main__ as cli
from autostream import paths
from autostream.macos import launch


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DATA_HOME", tmp_path)
    monkeypatch.delenv("AUTOSTREAM_INSTANCE", raising=False)
    yield tmp_path
    launch.release()


def test_one_at_a_time(home):
    assert launch.acquire() is True
    # flock is per open file, so a second open in this process is refused --
    # which is exactly what a second app process would see.
    fd = launch._lock_fd
    launch._lock_fd = None
    assert launch.acquire() is False
    launch._lock_fd = fd


def test_the_lock_is_in_the_data_folder_not_the_program_folder(home):
    """Inside a signed .app the program folder is read-only."""
    assert launch._lock_path().parent == home


def test_a_test_instance_takes_its_own_lock(home, monkeypatch):
    assert launch.acquire() is True
    monkeypatch.setenv("AUTOSTREAM_INSTANCE", "verify-1234")
    assert launch._lock_path().name.endswith("verify-1234")
    held = launch._lock_fd
    launch._lock_fd = None
    try:
        assert launch.acquire() is True
    finally:
        launch.release()
        launch._lock_fd = held


def test_busy_names_a_clip_job_and_a_render():
    srv = types.SimpleNamespace(_clips_status=lambda: {"state": "running"},
                                studio_job=lambda: {"state": "idle"})
    assert launch.busy(srv) == "a clip job"
    srv._clips_status = lambda: None
    srv.studio_job = lambda: {"state": "queued"}
    assert launch.busy(srv) == "a reel render"
    srv.studio_job = lambda: {}
    assert launch.busy(srv) == ""


def test_busy_never_raises():
    def boom():
        raise RuntimeError("x")

    assert launch.busy(types.SimpleNamespace(_clips_status=boom, studio_job=boom)) == ""


def test_run_hands_over_to_the_mac_launch_on_a_mac(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(launch, "run", lambda args, setup: seen.append(setup) or 7)
    assert cli.cmd_run(types.SimpleNamespace(verbose=False, quiet=True)) == 7
    assert seen == [cli.setup_logging]


def test_windows_run_never_reaches_the_mac_launch(monkeypatch):
    """cmd_run's own path, stopped at cfg.load() -- its first real step, and far enough to
    prove the Mac launch was not taken."""
    monkeypatch.setattr(sys, "platform", "win32")

    def boom(*a, **k):
        raise AssertionError("Windows took the Mac launch")

    monkeypatch.setattr(launch, "run", boom)
    # pystray would pick its win32 backend under a pretended platform.
    monkeypatch.setitem(sys.modules, "autostream.tray", types.SimpleNamespace(Tray=object))

    class Stop(Exception):
        pass

    def stop(*a, **k):
        raise Stop

    monkeypatch.setattr(cli.cfg, "load", stop)
    with pytest.raises(Stop):
        cli.cmd_run(types.SimpleNamespace(verbose=False, quiet=True))


def test_the_launch_never_constructs_an_engine():
    """The point of the Mac build. Read from the source because the honest
    test -- starting it -- opens a server and a window."""
    from pathlib import Path

    src = Path(launch.__file__).read_text(encoding="utf-8")
    body = src[src.index("def run("):]
    assert "Engine" not in body and "Tray" not in body and "keyboard" not in body
    assert "Server(token, port, None" in body
