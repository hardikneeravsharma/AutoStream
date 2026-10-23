"""Release file names (issue #206): one convention, the version on every file,
and installs that only know the old installer name still able to update."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import release_assets as ra  # noqa: E402

from autostream import updates  # noqa: E402

BUILT = ("AutoStream-1.78.2-setup.exe", "AutoStream-share.zip",
         "AutoStream-macos-arm64.dmg", "AutoStream-macos-x86_64.dmg")


def _builds(folder: Path, version: str = "1.78.2") -> Path:
    for name in BUILT:
        (folder / name.replace("1.78.2", version)).write_bytes(name.encode())
    (folder / "AutoStream-share.zip.sha256").write_text("stale  AutoStream-share.zip\r\n")
    return folder


def test_every_published_file_carries_the_version(tmp_path):
    names = {p.name for p in ra.prepare("v1.78.2", _builds(tmp_path))}
    assert {"AutoStream-1.78.2-windows-x64-setup.exe", "AutoStream-1.78.2-windows-x64.zip",
            "AutoStream-1.78.2-macos-arm64.dmg", "AutoStream-1.78.2-macos-x86_64.dmg"} <= names
    assert all("1.78.2" in n for n in names)
    assert {p.name for p in tmp_path.iterdir()} == names, "a build name was left behind"


def test_each_checksum_is_the_files_own_in_sha256sum_format(tmp_path):
    for p in ra.prepare("1.78.2", _builds(tmp_path)):
        if p.suffix == ".sha256":
            continue
        side = p.with_name(p.name + ".sha256").read_bytes()
        assert side == f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n".encode()


@pytest.mark.parametrize("version", ["1.79.4", "1.82.0", "2.0.0"])
def test_the_old_name_installer_rides_along_on_every_release(tmp_path, version):
    """It stopped at v1.80.0 once, and a v1.77.0 install was told v1.82.0 had
    nothing to download. No version is late enough for the copy to stop."""
    ra.prepare(version, _builds(tmp_path, version))
    old = tmp_path / f"AutoStream-{version}-setup.exe"
    assert old.read_bytes() == (tmp_path / f"AutoStream-{version}-windows-x64-setup.exe").read_bytes()
    assert (tmp_path / f"AutoStream-{version}-setup.exe.sha256").is_file()


def test_a_missing_build_stops_the_release(tmp_path):
    (tmp_path / "AutoStream-share.zip").write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        ra.prepare("1.78.2", tmp_path)


# --------------------------------------------- what an updater does with it

def _release(names, monkeypatch, platform="win32"):
    data = {"tag_name": "v1.78.2", "assets": [
        {"name": n, "browser_download_url": f"https://example/{n}", "size": 1} for n in names]}
    monkeypatch.setattr(updates, "_get", lambda url, accept=None: json.dumps(data).encode())
    monkeypatch.setattr(sys, "platform", platform)
    return updates.latest()


def _published(tmp_path):
    return [p.name for p in ra.prepare("1.78.2", _builds(tmp_path))]


def test_a_new_install_takes_the_new_name(tmp_path, monkeypatch):
    rel = _release(_published(tmp_path), monkeypatch)
    assert rel.asset_name == "AutoStream-1.78.2-windows-x64-setup.exe" and rel.installable
    assert rel.sha256_url.endswith("windows-x64-setup.exe.sha256")


def test_an_install_from_before_the_rename_still_finds_its_installer(tmp_path):
    """v1.78.1's own pattern, verbatim: it must match a file in the release."""
    import re

    old = re.compile(r"^AutoStream-[\d.]+-setup\.exe$", re.I)
    assert [n for n in _published(tmp_path) if old.match(n)] == ["AutoStream-1.78.2-setup.exe"]


def test_the_zip_is_found_by_its_new_name(tmp_path, monkeypatch):
    names = [n for n in _published(tmp_path) if "setup" not in n]
    assert _release(names, monkeypatch).asset_name == "AutoStream-1.78.2-windows-x64.zip"


def test_an_old_release_still_reads_the_old_names(monkeypatch):
    rel = _release(["AutoStream-1.78.1-setup.exe", "AutoStream-share.zip"], monkeypatch)
    assert rel.asset_name == "AutoStream-1.78.1-setup.exe"


def test_a_mac_takes_its_dmg_from_the_same_release(tmp_path, monkeypatch):
    from autostream.macos import updates as mac

    rel = _release(_published(tmp_path), monkeypatch, platform="darwin")
    assert rel.asset_name == f"AutoStream-1.78.2-macos-{mac.ARCH}.dmg"
