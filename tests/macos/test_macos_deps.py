"""The clipper's outside tools on a Mac: Homebrew's commands, Homebrew's
installer, and the Windows payload untouched."""
from __future__ import annotations

import subprocess
import sys

import pytest

from autostream.clips import deps
from autostream.macos import deps as mac
from autostream.macos import tools as mac_tools


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    deps.forget()
    monkeypatch.setattr(deps, "_installer", None)
    yield
    deps.forget()


def test_the_page_is_given_brew_commands_on_a_mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(deps, "_found", lambda key: "")
    monkeypatch.setattr(mac, "brew", lambda: "/opt/homebrew/bin/brew")
    st = deps.state()
    by = {t["key"]: t for t in st["tools"]}
    assert by["ffmpeg"]["install"] == "brew install ffmpeg-full"
    assert by["tesseract"]["install"] == "brew install tesseract"
    assert st["can_install"] is True
    assert "Homebrew" in st["install_note"] and "Homebrew" in st["manual_note"]


def test_no_homebrew_means_no_install_button(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(deps, "_found", lambda key: "")
    monkeypatch.setattr(mac, "brew", lambda: "")
    assert deps.state()["can_install"] is False


def test_an_ffmpeg_that_cannot_draw_text_is_reported(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(deps, "_found", lambda key: f"/x/{key}")
    monkeypatch.setattr(mac, "brew", lambda: "")
    monkeypatch.setattr(mac_tools, "text_warning", lambda ff: "no drawtext")
    assert deps.state()["text_warning"] == "no drawtext"


def test_the_windows_payload_has_no_mac_keys(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(deps, "_found", lambda key: "")
    monkeypatch.setattr(deps, "winget", lambda: "")
    st = deps.state()
    assert not ({"install_note", "manual_note", "text_warning"} & set(st))
    assert all("install" not in t for t in st["tools"])


def test_a_mac_gets_the_brew_installer(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert isinstance(deps.installer(), mac.BrewInstaller)


def test_the_brew_installer_refuses_without_homebrew(monkeypatch):
    monkeypatch.setattr(mac, "brew", lambda: "")
    ok, why = mac.BrewInstaller().start(["ffmpeg"])
    assert ok is False and "Homebrew" in why


def test_the_brew_installer_asks_for_the_full_ffmpeg(monkeypatch):
    seen = []
    monkeypatch.setattr(mac, "brew", lambda: "/b/brew")
    monkeypatch.setattr(mac.subprocess, "run", lambda argv, **k: seen.append(argv)
                        or subprocess.CompletedProcess(argv, 0, "", ""))
    ok, why = mac.BrewInstaller()._brew({"key": "ffmpeg", "label": "FFmpeg"})
    assert ok and seen == [["/b/brew", "install", "ffmpeg-full"]]


def test_success_is_judged_by_the_tool_being_there(monkeypatch):
    """Not by what brew printed -- the winget path's rule."""
    inst = mac.BrewInstaller()
    monkeypatch.setattr(inst, "_brew", lambda t: (False, "brew grumbled"))
    monkeypatch.setattr(deps, "_found", lambda key: "/now/here")
    inst._run([{"key": "ffmpeg", "label": "FFmpeg"}])
    assert inst.state == "done" and inst.done == ["ffmpeg"]


def test_a_missing_tesseract_on_a_mac_names_homebrew(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(mac_tools, "find", lambda name: "")
    with pytest.raises(deps.ToolMissing) as e:
        deps.tesseract()
    assert "brew install tesseract" in str(e.value)
