"""Where a Mac keeps the user's files -- and that Windows still decides first.

Runs on every platform: sys.platform is pretended, never required.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

from autostream import paths
from autostream.macos import paths as mac_paths

REPO = str(Path(__file__).resolve().parents[2])


@pytest.fixture(autouse=True)
def _restore():
    """paths is reloaded below, and a reload is global; put it back."""
    yield
    os.environ["AUTOSTREAM_HOME"] = REPO
    if hasattr(sys, "frozen"):
        del sys.frozen
    importlib.reload(paths)


def _reload(monkeypatch, platform: str, *, frozen: bool, localappdata=None):
    monkeypatch.delenv("AUTOSTREAM_HOME", raising=False)
    monkeypatch.delenv("AUTOSTREAM_VIDEO_HOME", raising=False)
    monkeypatch.delenv("AUTOSTREAM_MODELS", raising=False)
    if localappdata is None:
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
    else:
        monkeypatch.setenv("LOCALAPPDATA", localappdata)
    monkeypatch.setattr(sys, "platform", platform)
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    return importlib.reload(paths)


def test_a_built_mac_app_keeps_settings_in_application_support(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p = _reload(monkeypatch, "darwin", frozen=True)
    assert p.DATA_HOME == tmp_path / "Library" / "Application Support" / "AutoStream"
    assert p.CONFIG_FILE == p.DATA_HOME / "config" / "config.yaml"


def test_a_mac_keeps_footage_in_movies(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p = _reload(monkeypatch, "darwin", frozen=False)
    assert p.VIDEO_HOME == tmp_path / "Movies" / "AutoStream"
    assert p.CLIPS_DIR == tmp_path / "Movies" / "AutoStream" / "clips"
    assert p.MODELS_DIR == tmp_path / "Movies" / "AutoStream" / "models"


def test_the_overrides_still_win_on_a_mac(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOSTREAM_VIDEO_HOME", str(tmp_path / "v"))
    monkeypatch.setattr(sys, "platform", "darwin")
    p = importlib.reload(paths)
    assert p.VIDEO_HOME == tmp_path / "v"


def test_windows_is_decided_exactly_as_before(monkeypatch, tmp_path):
    """LOCALAPPDATA and ~/Videos, untouched by the Mac branches."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p = _reload(monkeypatch, "win32", frozen=True, localappdata=str(tmp_path / "lad"))
    assert p.DATA_HOME == tmp_path / "lad" / "AutoStream"
    assert p.VIDEO_HOME == tmp_path / "Videos" / "AutoStream"


def test_a_checkout_on_a_mac_keeps_everything_together(monkeypatch):
    p = _reload(monkeypatch, "darwin", frozen=False)
    assert p.DATA_HOME == p.ROOT


def test_the_mac_module_imports_nothing_from_the_package():
    """paths.py imports it, and everything imports paths.py."""
    src = Path(mac_paths.__file__).read_text(encoding="utf-8")
    assert "from .." not in src and "from autostream" not in src
