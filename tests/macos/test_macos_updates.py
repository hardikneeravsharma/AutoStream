"""The Mac app updating itself: the right .dmg chosen, the running .app swapped
for the new one -- and put back if the swap fails."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from autostream import paths, updates
from autostream.macos import updates as mac

DMG = f"AutoStream-9.9.9-macos-{mac.ARCH}.dmg"
BOTH = {"tag_name": "v9.9.9", "html_url": "https://example/rel", "body": "", "assets": [
    {"name": "AutoStream-9.9.9-setup.exe", "browser_download_url": "https://example/setup", "size": 1},
    {"name": "AutoStream-9.9.9-setup.exe.sha256", "browser_download_url": "https://example/setup.sha"},
    {"name": "AutoStream-share.zip", "browser_download_url": "https://example/zip", "size": 2},
    {"name": DMG, "browser_download_url": "https://example/dmg", "size": 3},
    {"name": DMG + ".sha256", "browser_download_url": "https://example/dmg.sha"},
]}


@pytest.fixture
def release(monkeypatch):
    monkeypatch.setattr(updates, "_get", lambda url, accept=None: json.dumps(BOTH).encode())


def test_a_mac_takes_its_own_dmg(release, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    rel = updates.latest()
    assert rel.asset_name == DMG and rel.installable
    assert rel.sha256_url == "https://example/dmg.sha"


def test_windows_still_takes_the_installer_from_the_same_release(release, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    rel = updates.latest()
    assert rel.asset_name == "AutoStream-9.9.9-setup.exe" and rel.installable


def test_the_dmg_is_this_macs_architecture():
    other = "x86_64" if mac.ARCH == "arm64" else "arm64"
    names = [f"AutoStream-9.9.9-macos-{other}.dmg", DMG, DMG + ".sha256"]
    assert mac.pick(names) == DMG


def test_the_newest_dmg_wins_and_the_arch_digits_are_not_a_version():
    """"arm64" and "x86_64" are full of digits; only the leading version counts."""
    old = f"AutoStream-macos-{mac.ARCH}.dmg"                # v1.78.1's name
    names = [old, f"AutoStream-1.78.2-macos-{mac.ARCH}.dmg", f"AutoStream-1.79.0-macos-{mac.ARCH}.dmg"]
    assert mac.pick(names) == f"AutoStream-1.79.0-macos-{mac.ARCH}.dmg"
    assert mac.pick([old]) == old


# ------------------------------------------------------------ which app

def test_a_checkout_is_not_an_app(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert mac.running_app() is None


def test_a_built_app_finds_its_bundle(monkeypatch, tmp_path):
    exe = tmp_path / "AutoStream.app" / "Contents" / "MacOS" / "AutoStream"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert mac.running_app() == (tmp_path / "AutoStream.app").resolve()


# ------------------------------------------------------------ install

@pytest.fixture
def app(monkeypatch, tmp_path):
    bundle = tmp_path / "Applications" / "AutoStream.app"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(mac, "running_app", lambda: bundle)
    monkeypatch.setattr(paths, "DATA_HOME", tmp_path / "data")
    return bundle


def test_from_source_it_says_git_pull(monkeypatch, tmp_path):
    monkeypatch.setattr(mac, "running_app", lambda: None)
    assert "git pull" in mac.install(None, tmp_path / "x.dmg", "9.9.9")["error"]


def test_only_a_disk_image_is_installed(app, tmp_path):
    assert "not a Mac disk image" in mac.install(None, tmp_path / "x.zip", "9.9.9")["error"]


def test_a_folder_it_cannot_write_to_says_so(app, monkeypatch, tmp_path):
    monkeypatch.setattr(mac.os, "access", lambda p, mode: False)
    assert "drag the new version" in mac.install(None, tmp_path / "x.dmg", "9.9.9")["error"]


def test_a_failed_stage_changes_nothing(app, monkeypatch, tmp_path):
    def boom(dmg, into):
        raise RuntimeError("could not open the download")
    monkeypatch.setattr(mac, "stage", boom)
    monkeypatch.setattr(mac.subprocess, "Popen", lambda *a, **k: pytest.fail("handed over"))
    assert "could not open" in mac.install(None, tmp_path / "x.dmg", "9.9.9")["error"]
    assert app.is_dir()


def test_it_hands_over_and_then_quits(app, monkeypatch, tmp_path):
    staged, started, quit = [], [], []
    monkeypatch.setattr(mac, "stage", lambda dmg, into: staged.append(into))
    monkeypatch.setattr(mac.subprocess, "Popen", lambda argv, **k: started.append((argv, k)))
    monkeypatch.setattr(mac.time, "sleep", lambda s: None)
    server = types.SimpleNamespace(window=types.SimpleNamespace(request_quit=quit.append))
    got = mac.install(server, tmp_path / "x.dmg", "9.9.9")
    assert got == {"ok": True, "version": "9.9.9"}
    # Staged beside the running app, so the swap is a rename on one volume.
    assert staged == [app.parent / mac.STAGED]
    argv, kw = started[0]
    assert argv[0] == "/bin/sh" and argv[2:] == [str(os.getpid()), str(app), str(staged[0])]
    assert kw["start_new_session"] is True           # outlives this process
    assert Path(argv[1]).read_text() == mac.SWAP
    for t in __import__("threading").enumerate():
        if t.name == "autostream-handover":
            t.join(5)
    assert quit == ["an update is being installed"]


# ------------------------------------------------------------ the swap, for real

def _ended_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def _swap(tmp_path, app: Path, new: Path) -> int:
    script = tmp_path / "swap.sh"
    script.write_text(mac.SWAP)
    env = dict(os.environ, AUTOSTREAM_NO_RELAUNCH="1")
    return subprocess.run(["/bin/sh", str(script), str(_ended_pid()), str(app), str(new)],
                          env=env, timeout=30).returncode


@pytest.mark.skipif(not shutil.which("sh") or sys.platform == "win32", reason="a POSIX shell")
def test_the_swap_puts_the_new_app_in_place(tmp_path):
    app, new = tmp_path / "AutoStream.app", tmp_path / mac.STAGED
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "v").write_text("old")
    (new / "Contents").mkdir(parents=True)
    (new / "Contents" / "v").write_text("new")
    assert _swap(tmp_path, app, new) == 0
    assert (app / "Contents" / "v").read_text() == "new"
    assert not new.exists()
    assert not list(tmp_path.glob("AutoStream.app.old-*")), "the old app was left behind"


@pytest.mark.skipif(not shutil.which("sh") or sys.platform == "win32", reason="a POSIX shell")
def test_a_swap_that_fails_puts_the_old_app_back(tmp_path):
    app = tmp_path / "AutoStream.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "v").write_text("old")
    assert _swap(tmp_path, app, tmp_path / "not-there.app") != 0
    assert (app / "Contents" / "v").read_text() == "old"


@pytest.mark.skipif(sys.platform != "darwin", reason="hdiutil and ditto are macOS")
def test_staging_copies_the_app_out_of_a_real_disk_image(tmp_path):
    src = tmp_path / "src"
    exe = src / "AutoStream.app" / "Contents" / "MacOS" / "AutoStream"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    (src / "Applications").symlink_to("/Applications")
    dmg = tmp_path / "t.dmg"
    subprocess.run(["hdiutil", "create", "-quiet", "-volname", "AutoStream", "-srcfolder",
                    str(src), "-format", "UDZO", str(dmg)], check=True, timeout=120)
    into = tmp_path / mac.STAGED
    mac.stage(dmg, into)
    got = into / "Contents" / "MacOS" / "AutoStream"
    assert got.is_file() and os.access(got, os.X_OK)
