"""The macOS build files: present, separate from the Windows ones, and saying
what they mean. The build itself is exercised by scripts/macos/build.sh."""
from __future__ import annotations

import glob
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "packaging" / "macos" / "autostream-macos.spec"
BUILD = ROOT / "scripts" / "macos" / "build.sh"
INSTALL = ROOT / "scripts" / "macos" / "install.sh"
LAUNCHER = ROOT / "packaging" / "macos" / "launcher.py"
REQS = ROOT / "requirements-macos.txt"


def test_the_spec_uses_cocoa_and_none_of_the_windows_backends():
    src = SPEC.read_text(encoding="utf-8")
    assert '"webview.platforms.cocoa"' in src
    for win in ("edgechromium", "winforms", "mshtml", "pystray._win32", "win32timezone"):
        assert f'"{win}' not in src.split("excludes=")[0], win


def test_the_spec_leaves_the_streaming_half_out():
    excludes = SPEC.read_text(encoding="utf-8").split("excludes=[", 1)[1].split("]", 1)[0]
    for mod in ("obsws_python", "googleapiclient", "pystray", "keyboard"):
        assert f'"{mod}"' in excludes, mod


def test_every_data_glob_in_the_spec_matches_something():
    src = SPEC.read_text(encoding="utf-8")
    for parts in re.findall(r'here\(((?:"[^"]+",?\s*)+)\),\s*"', src):
        rel = [p for p in re.findall(r'"([^"]+)"', parts)]
        pattern = str(ROOT.joinpath(*rel))
        assert glob.glob(pattern), f"{pattern} matches nothing"


def test_the_spec_bundles_no_config_but_the_tracked_seed():
    src = SPEC.read_text(encoding="utf-8")
    assert '"config", "games.yaml"' in src
    for never in ("config.yaml", "apps.yaml", "clip_profiles.yaml", "secrets"):
        assert never not in src.replace("games.yaml", ""), never


def test_the_build_probe_imports_modules_that_exist():
    import importlib

    probe = re.search(r'-c "import (autostream[^"]+)"', BUILD.read_text(encoding="utf-8"))
    assert probe
    names = [n.strip() for n in probe.group(1).split(",")]
    assert "autostream.macos.launch" in names
    for n in names:
        importlib.import_module(n)


def test_the_build_writes_nowhere_the_windows_build_does():
    src = BUILD.read_text(encoding="utf-8")
    assert 'OUT="$ROOT/dist/macos"' in src and 'WORK="$ROOT/build/macos"' in src
    assert "dist/AutoStream\"" not in src and "dist\\AutoStream" not in src


def test_the_build_scans_for_the_same_credentials_as_build_ps1():
    src = BUILD.read_text(encoding="utf-8")
    for name in ("config.yaml", "apps.yaml", "clip_profiles.yaml",
                 "streamelements.json", "state.json", "client_secret"):
        assert name in src, name


def test_the_dmg_keeps_the_bundle_whole_and_its_name_stable():
    """ditto, not make_zip.py, which drops the symlinks a .app needs. And no
    version in the name, so releases/latest/download/ always finds it."""
    src = BUILD.read_text(encoding="utf-8")
    assert 'ditto "$APP"' in src and "hdiutil create" in src
    assert 'DMG="$OUT/AutoStream-macos-$ARCH.dmg"' in src


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("bash"),
                    reason="the Mac's own bash is the one these scripts run under")
@pytest.mark.parametrize("script", [BUILD, INSTALL], ids=lambda p: p.name)
def test_the_scripts_parse(script):
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0


def test_the_launcher_ignores_a_finder_process_number():
    src = LAUNCHER.read_text(encoding="utf-8")
    assert '-psn_' in src and 'sys.argv.append("run")' in src
    assert "~/Library/Logs/AutoStream" in src


def test_mac_requirements_carry_nothing_windows_or_streaming():
    reqs = [ln.split("#")[0].strip().lower() for ln in REQS.read_text().splitlines()]
    names = {re.split(r"[<>=;\[ ]", r, maxsplit=1)[0] for r in reqs if r}
    assert {"pywebview", "numpy", "pillow", "pyyaml"} <= names
    assert not names & {"pywin32", "winotify", "obsws-python", "keyboard", "pystray",
                        "google-auth", "google-api-python-client"}


def test_the_windows_build_files_are_where_they_were():
    """#193: the Windows build is not moved, renamed or replaced."""
    for p in ("autostream.spec", "autostream_launcher.py", "requirements.txt",
              "scripts/build.ps1", "scripts/install.ps1"):
        assert (ROOT / p).is_file(), p
