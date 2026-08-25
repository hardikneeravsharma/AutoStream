"""Reading OBS's WebSocket settings instead of asking a person to copy them.

OBS writes host, port and password into its own profile the moment the
WebSocket dialog is committed. Setup used to ask for all three by hand, and a
mistyped character in a generated sixteen-character password fails in exactly
the way OBS-not-running fails -- which is the support question that never ends.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import obs as obsmod                            # noqa: E402


def write_cfg(tmp_path: Path, **fields) -> Path:
    p = tmp_path / "obs-studio" / "plugin_config" / "obs-websocket"
    p.mkdir(parents=True)
    f = p / "config.json"
    f.write_text(json.dumps(fields), encoding="utf-8")
    return f


def test_it_reads_port_and_password(tmp_path, monkeypatch):
    write_cfg(tmp_path, server_enabled=True, server_port=4466,
              server_password="s3cret-from-obs", auth_required=True)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    r = obsmod.discover_websocket()
    assert r["found"] is True
    assert r["enabled"] is True
    assert r["port"] == 4466
    assert r["password"] == "s3cret-from-obs"


def test_auth_off_reports_no_password(tmp_path, monkeypatch):
    """OBS keeps the old password in the file with auth switched off, and it
    ignores it. Handing that stale value to the client fails in a way nobody
    could explain from the error."""
    write_cfg(tmp_path, server_enabled=True, server_port=4455,
              server_password="stale-and-ignored", auth_required=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    r = obsmod.discover_websocket()
    assert r["auth_required"] is False
    assert r["password"] == ""


def test_a_server_that_is_off_is_reported_not_hidden(tmp_path, monkeypatch):
    """The settings existing and the server listening are different facts, and
    the wizard has different advice for each."""
    write_cfg(tmp_path, server_enabled=False, server_port=4455,
              server_password="p", auth_required=True)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    r = obsmod.discover_websocket()
    assert r["found"] is True
    assert r["enabled"] is False


def test_no_profile_is_not_an_error(tmp_path, monkeypatch):
    """A machine where OBS has never opened that dialog. Setup asks instead."""
    monkeypatch.setenv("APPDATA", str(tmp_path))

    r = obsmod.discover_websocket()
    assert r["found"] is False
    assert r["port"] == 4455          # still a usable default
    assert r["password"] == ""


def test_unreadable_json_falls_back_rather_than_raising(tmp_path, monkeypatch):
    p = tmp_path / "obs-studio" / "plugin_config" / "obs-websocket"
    p.mkdir(parents=True)
    (p / "config.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))

    r = obsmod.discover_websocket()
    assert r["found"] is False        # never raises: this feeds a setup screen


def test_a_portable_install_is_found_beside_the_exe(tmp_path, monkeypatch):
    """Portable OBS keeps its profile next to the executable, and portable is
    common on exactly the locked-down machine where hand-copying goes wrong."""
    monkeypatch.delenv("APPDATA", raising=False)
    root = tmp_path / "obs-studio"
    exe = root / "bin" / "64bit" / "obs64.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    cfgdir = root / "config" / "obs-studio" / "plugin_config" / "obs-websocket"
    cfgdir.mkdir(parents=True)
    (cfgdir / "config.json").write_text(
        json.dumps({"server_enabled": True, "server_port": 4477,
                    "server_password": "portable", "auth_required": True}),
        encoding="utf-8")

    r = obsmod.discover_websocket(str(exe))
    assert r["found"] is True
    assert r["port"] == 4477
    assert r["password"] == "portable"
