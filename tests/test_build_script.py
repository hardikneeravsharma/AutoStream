"""The build script names modules. They have to still exist.

WHY THIS FILE EXISTS
    Removing the floating overlay deleted autostream/panel.py. The whole test
    suite passed -- nothing in the package referred to it any more -- and the
    build then failed on its own import probe, which still did:

        import autostream.__main__, autostream.web, autostream.panel

    The guard did its job and refused to build a broken exe, which is the only
    reason this was a two-minute problem rather than a shipped one. But the
    suite is what is supposed to catch it, and the suite could not see the
    build script at all.

    It is the same shape as every other bug this week: a name written down in
    two places and updated in one. The difference is that this one lives
    outside Python, where nothing was looking.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest                                                     # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "scripts" / "build.ps1"


def _imported_names() -> set[str]:
    """Every autostream module the build script asks Python to import."""
    text = BUILD.read_text(encoding="utf-8-sig")
    names: set[str] = set()
    for line in re.findall(r'"import ([^"]+)"', text):
        for part in line.split(","):
            part = part.strip()
            if part.startswith("autostream"):
                names.add(part)
    return names


@pytest.mark.skipif(not BUILD.is_file(), reason="no build script here")
def test_every_module_the_build_probe_imports_exists():
    names = _imported_names()
    assert names, (
        "the import probe in build.ps1 could not be read - if its shape "
        "changed, change this test with it rather than letting it check "
        "nothing")
    missing = []
    for name in sorted(names):
        try:
            importlib.import_module(name)
        except Exception as e:                                    # noqa: BLE001
            missing.append(f"{name}: {type(e).__name__}: {e}")
    assert not missing, (
        "build.ps1 refuses to build when its probe cannot import, so these "
        "would fail the build rather than the suite:\n  " + "\n  ".join(missing))


@pytest.mark.skipif(not BUILD.is_file(), reason="no build script here")
def test_the_probe_still_covers_the_entry_point():
    """A probe that stopped naming __main__ would pass this file happily and
    stop protecting the thing it exists for."""
    names = _imported_names()
    assert "autostream.__main__" in names
