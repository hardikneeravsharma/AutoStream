"""Finding ffmpeg on a Mac: the keg-only full build first, a Finder launch's
missing PATH filled in, and an ffmpeg that cannot draw text reported."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from autostream.clips import tools
from autostream.macos import tools as mac


def _exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_ffmpeg_full_wins_over_the_plain_formula(monkeypatch, tmp_path):
    full = _exe(tmp_path / "keg" / "ffmpeg")
    plain = _exe(tmp_path / "bin" / "ffmpeg")
    monkeypatch.setattr(mac, "FFMPEG_FULL", (full.parent,))
    monkeypatch.setattr(mac, "PREFIXES", (plain.parent,))
    monkeypatch.setattr(mac.shutil, "which", lambda name: str(plain))
    assert mac.find("ffmpeg") == str(full)


def test_a_prefix_is_found_without_it_being_on_path(monkeypatch, tmp_path):
    """The Finder hands an app /usr/bin:/bin:/usr/sbin:/sbin and no Homebrew."""
    t = _exe(tmp_path / "bin" / "tesseract")
    monkeypatch.setattr(mac, "PREFIXES", (t.parent,))
    monkeypatch.setattr(mac.shutil, "which", lambda name: None)
    assert mac.find("tesseract") == str(t)
    assert mac.find("nothing-by-this-name") == ""


def test_extend_path_appends_and_never_duplicates(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/bin"]))
    monkeypatch.setattr(mac, "PREFIXES", (tmp_path / "a", tmp_path / "b"))
    mac.extend_path()
    mac.extend_path()
    parts = os.environ["PATH"].split(os.pathsep)
    assert parts[:2] == ["/usr/bin", "/bin"]
    assert parts.count(str(tmp_path / "a")) == 1


def test_missing_filters_reads_the_filter_list(monkeypatch):
    listing = (" T.. = Timeline support\n ------\n"
               " TS. drawtext          V->V       Draw text\n"
               " ... scale             V->V       Scale\n")
    mac.missing_filters.cache_clear()
    monkeypatch.setattr(mac.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, listing, ""))
    assert mac.missing_filters("/x/ffmpeg") == ("ass",)
    assert "ffmpeg-full" in mac.text_warning("/x/ffmpeg")
    mac.missing_filters.cache_clear()


def test_a_full_build_has_nothing_to_warn_about(monkeypatch):
    listing = " TS. drawtext V->V x\n ... ass V->V y\n"
    mac.missing_filters.cache_clear()
    monkeypatch.setattr(mac.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, listing, ""))
    assert mac.text_warning("/y/ffmpeg") == ""
    mac.missing_filters.cache_clear()


@pytest.fixture
def no_cache():
    tools.binary.cache_clear()
    yield
    tools.binary.cache_clear()


def test_binary_asks_the_mac_lookup_on_a_mac(monkeypatch, no_cache):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(mac, "find", lambda name: f"/mac/{name}")
    assert tools.binary("ffprobe") == "/mac/ffprobe"


def test_a_missing_ffmpeg_on_a_mac_names_homebrew(monkeypatch, no_cache):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(mac, "find", lambda name: "")
    with pytest.raises(tools.FfmpegMissing) as e:
        tools.binary("ffmpeg")
    assert "brew install ffmpeg-full" in str(e.value)
    assert "winget" not in str(e.value)


def test_the_settings_folder_still_wins_on_a_mac(monkeypatch, tmp_path, no_cache):
    _exe(tmp_path / "ffmpeg")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(tools.os, "name", "posix")
    monkeypatch.setattr(tools, "_override", tmp_path)
    monkeypatch.setattr(mac, "find", lambda name: "/elsewhere/ffmpeg")
    assert tools.binary("ffmpeg") == str(tmp_path / "ffmpeg")


def test_windows_never_asks_the_mac_lookup(monkeypatch, no_cache):
    monkeypatch.setattr(sys, "platform", "win32")

    def boom(name):
        raise AssertionError("Windows consulted the Mac lookup")

    monkeypatch.setattr(mac, "find", boom)
    monkeypatch.setattr(tools.shutil, "which", lambda name: "C:/ff/ffmpeg.exe")
    assert tools.binary("ffmpeg") == "C:/ff/ffmpeg.exe"
