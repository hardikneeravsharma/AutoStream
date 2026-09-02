"""The window opening where it was left, and refusing to open where it cannot.

The second half is the point. A saved position outlives the monitor it was
saved on: undock a laptop, unplug a second screen, or change which monitor is
primary, and a remembered position can put the window somewhere with no pixels
behind it. There is then no title bar to drag and no window to see, and the
app looks exactly like one that failed to start.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import window  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A data folder of our own, and one predictable 1920x1080 screen."""
    monkeypatch.setattr(window.paths, "DATA_HOME", tmp_path)
    monkeypatch.setattr(window, "_screen", lambda: (0, 0, 1920, 1080))
    return tmp_path


def _write(home, **fields):
    (home / window.GEOMETRY_FILE).write_text(json.dumps(fields), encoding="utf-8")


class FakeWin:
    def __init__(self, x=100, y=100, width=1120, height=860):
        self.x, self.y, self.width, self.height = x, y, width, height


# ------------------------------------------------------------- what is saved

def test_a_position_is_remembered(home):
    assert window.save_geometry(FakeWin(x=40, y=60, width=1200, height=900))
    assert window.load_geometry() == {"width": 1200, "height": 900,
                                      "x": 40, "y": 60}


def test_a_minimised_window_is_not_remembered(home):
    """Minimised windows report sizes that mean nothing; saving one would
    reopen the app as a sliver."""
    assert not window.save_geometry(FakeWin(width=160, height=28))
    assert window.load_geometry() == {}


def test_a_window_object_that_is_not_there_is_survived(home):
    assert not window.save_geometry(None)
    assert not window.save_geometry(types.SimpleNamespace())


# ---------------------------------------------------------- what is restored

def test_nothing_saved_means_nothing_restored(home):
    assert window.load_geometry() == {}


def test_a_corrupt_file_is_ignored_rather_than_fatal(home):
    (home / window.GEOMETRY_FILE).write_text("{not json", encoding="utf-8")
    assert window.load_geometry() == {}


def test_a_file_missing_half_its_fields_is_ignored(home):
    _write(home, width=1200, height=900)
    assert window.load_geometry() == {}


def test_a_size_larger_than_the_desktop_is_ignored(home):
    _write(home, width=4000, height=3000, x=0, y=0)
    assert window.load_geometry() == {}


def test_a_position_on_a_monitor_that_is_gone_keeps_the_size(home, caplog):
    """The size is still good information; only the position is stale."""
    _write(home, width=1200, height=900, x=-2400, y=300)
    got = window.load_geometry()
    assert got == {"width": 1200, "height": 900}
    assert "x" not in got, "it would open off the side of the desktop"


def test_a_window_pushed_above_the_top_is_refused(home):
    """Its title bar would be off the desktop, so it could never be dragged."""
    _write(home, width=1200, height=900, x=100, y=-200)
    assert "x" not in window.load_geometry()


# ------------------------------------------------------ where "on screen" is

def test_a_second_monitor_to_the_LEFT_is_a_real_place(monkeypatch):
    """The virtual desktop origin is NEGATIVE then.

    A check written against 0,0 would call every position on that monitor
    off-screen and helpfully move the window away from where the user keeps
    it -- every single launch.
    """
    monkeypatch.setattr(window, "_screen", lambda: (-1920, 0, 3840, 1080))
    assert window.on_screen(-1800, 100, 1120, 860)
    assert window.on_screen(200, 100, 1120, 860)
    assert not window.on_screen(-3500, 100, 1120, 860)


def test_a_window_overhanging_an_edge_is_still_reachable(monkeypatch):
    """Half off the right-hand side is somewhere people genuinely leave
    windows, and it can be dragged back."""
    monkeypatch.setattr(window, "_screen", lambda: (0, 0, 1920, 1080))
    assert window.on_screen(1400, 100, 1120, 860)
    assert not window.on_screen(1900, 100, 1120, 860)


def test_the_desktop_is_measurable_on_this_machine():
    """Not a mock: whatever this box reports has to be usable numbers."""
    left, top, w, h = window._screen()
    assert w > 0 and h > 0
    assert isinstance(left, int) and isinstance(top, int)


# ------------------------------------------------------------- taskbar name

def test_the_app_names_itself_to_windows():
    """Without this the taskbar button is Python's: Python's name, Python's
    icon, and pinning it pins Python."""
    import os

    got = window.name_this_app()
    assert got is (os.name == "nt")


# ------------------------------------------------- the startup path itself

def test_the_window_is_actually_created_with_the_saved_geometry(home, monkeypatch):
    """This code runs before anything else the app does.

    A mistake here is not a broken feature, it is an app that will not start
    -- which has happened before, from a NameError on a startup path that no
    test executed. So this executes it.
    """
    made = {}

    def fake_create_window(title, url, **kw):
        made.update(kw)
        made["title"] = title
        return types.SimpleNamespace(
            events=types.SimpleNamespace(),
            x=0, y=0, width=0, height=0)

    fake = types.SimpleNamespace(
        create_window=fake_create_window,
        start=lambda *a, **k: None)
    monkeypatch.setattr(window, "webview", fake, raising=False)
    monkeypatch.setattr(window, "_HAS", True)

    _write(home, width=1200, height=900, x=40, y=60)
    w = window.MainWindow("http://127.0.0.1:1/", "AutoStream")
    w._quit = True                      # so run() does not wait on anything
    w.run(hidden=True)

    assert made["width"] == 1200 and made["height"] == 900
    assert made["x"] == 40 and made["y"] == 60
    assert made["min_size"] == window.MIN_SIZE
    assert not w.fell_back


def test_with_nothing_saved_the_window_is_left_to_centre_itself(home, monkeypatch):
    """x and y are OMITTED, not passed as None -- pywebview centres a window
    that has no position, which is what a first run should get."""
    made = {}
    monkeypatch.setattr(window, "webview", types.SimpleNamespace(
        create_window=lambda t, u, **kw: (made.update(kw), types.SimpleNamespace(
            events=types.SimpleNamespace(), x=0, y=0, width=0, height=0))[1],
        start=lambda *a, **k: None), raising=False)
    monkeypatch.setattr(window, "_HAS", True)

    w = window.MainWindow("http://127.0.0.1:1/")
    w._quit = True
    w.run(hidden=True)

    assert "x" not in made and "y" not in made
    assert made["width"], made["height"] == window.DEFAULT_SIZE
