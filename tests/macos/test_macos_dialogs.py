"""Choosing a file on a Mac -- never Tk, which off the main thread takes a Mac
app down -- and that the answer is the one clips_pick gives on Windows."""
from __future__ import annotations

import subprocess
import sys
import types

import pytest

from autostream import webui
from autostream.macos import dialogs


class FakeWin:
    def __init__(self, picked):
        self.picked = picked
        self.asked = []

    def create_file_dialog(self, kind, allow_multiple=False, file_types=()):
        self.asked.append((kind, allow_multiple, file_types))
        return self.picked


def _window(picked):
    return types.SimpleNamespace(win=FakeWin(picked), fell_back=False)


def test_the_native_window_dialog_is_used_when_there_is_one(monkeypatch):
    monkeypatch.setattr(dialogs, "_osascript", lambda *a: pytest.fail("used osascript"))
    w = _window(("/a.mp4", "/b.mp4"))
    got, err = dialogs.pick(w, "video", multi=True)
    assert got == ["/a.mp4", "/b.mp4"] and not err
    _kind, multi, types_ = w.win.asked[0]
    assert multi is True and "*.mp4" in types_[0]


def test_a_cancelled_native_dialog_is_an_empty_answer():
    assert dialogs.pick(_window(None), "audio") == ([], "")


def test_without_a_window_applescript_is_asked(monkeypatch):
    seen = []
    monkeypatch.setattr(dialogs.subprocess, "run", lambda argv, **k: seen.append(argv)
                        or subprocess.CompletedProcess(argv, 0, "/x/one.mp4\n/x/two.mp4\n", ""))
    got, err = dialogs.pick(None, "video", multi=True)
    assert got == ["/x/one.mp4", "/x/two.mp4"] and not err
    script = seen[0][2]
    assert seen[0][:2] == ["osascript", "-e"]
    assert "multiple selections allowed" in script and '"mp4"' in script


def test_applescript_cancel_is_not_an_error(monkeypatch):
    monkeypatch.setattr(dialogs.subprocess, "run", lambda argv, **k:
                        subprocess.CompletedProcess(argv, 1, "", "User canceled. (-128)"))
    assert dialogs.pick(None, "audio") == ([], "")


def test_a_picker_that_fails_says_so(monkeypatch):
    monkeypatch.setattr(dialogs.subprocess, "run", lambda argv, **k:
                        subprocess.CompletedProcess(argv, 1, "", "execution error"))
    got, err = dialogs.pick(None, "video")
    assert got == [] and "file picker" in err


def test_each_kind_has_its_own_filter():
    assert "mp3" in dialogs._filter("audio")[2]
    assert "mp4" in dialogs._filter("outro")[2]
    assert "gif" in dialogs._filter("intro")[2]


# ------------------------------------------------ the tail, against Windows'

@pytest.fixture
def server():
    srv = webui.Server.__new__(webui.Server)
    srv.window = None
    srv._picked = set()
    srv.clips_probe = lambda body: {"probed": body["path"]}
    return srv


def test_the_mac_answer_matches_the_windows_answer(server, tmp_path, monkeypatch):
    """answer() is clips_pick's tail written again (to leave Windows code
    alone). Pinned here: the same files give the same reply both ways."""
    a = tmp_path / "a.mp4"
    a.write_bytes(b"x" * 2048)
    gone = str(tmp_path / "gone.mp4")
    mac_got = dialogs.answer(server, [str(a), gone], "video")
    mac_seen = set(server._picked)

    # Windows' own tail, through the Tk picker faked to return the same.
    server._picked = set()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("AUTOSTREAM_NO_DIALOGS", raising=False)
    import tkinter
    from tkinter import filedialog

    monkeypatch.setattr(tkinter, "Tk", lambda: types.SimpleNamespace(
        withdraw=lambda: None, attributes=lambda *a: None, destroy=lambda: None))
    monkeypatch.setattr(filedialog, "askopenfilenames", lambda **k: (str(a), gone))
    win_got = server.clips_pick("video", multi=True)
    assert mac_got == win_got
    assert mac_seen == server._picked


def test_a_cancel_and_a_vanished_file_read_the_same(server):
    assert dialogs.answer(server, [], "video") == {"ok": True, "path": "", "paths": []}
    assert "error" in dialogs.answer(server, ["/nowhere/at/all.mp4"], "video")


def test_an_intro_is_not_probed(server, tmp_path):
    g = tmp_path / "i.gif"
    g.write_bytes(b"GIF89a")
    assert "probed" not in dialogs.answer(server, [str(g)], "intro")


def test_clips_pick_takes_the_mac_door_on_a_mac(server, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("AUTOSTREAM_NO_DIALOGS", raising=False)
    monkeypatch.setattr(dialogs, "pick", lambda win, kind, multi: ([], ""))
    assert server.clips_pick("video") == {"ok": True, "path": "", "paths": []}


def test_the_no_dialogs_door_is_shut_before_the_mac_one(server, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("AUTOSTREAM_NO_DIALOGS", "1")
    monkeypatch.setattr(dialogs, "pick", lambda *a: pytest.fail("a picker opened"))
    assert "error" in server.clips_pick("video")
