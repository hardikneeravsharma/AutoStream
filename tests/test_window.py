"""What happens when there is no native window.

A first run on a clean Windows machine has no WebView2 runtime, so pywebview
is installed (it is bundled) but webview.start() throws. run() correctly fell
back to the real browser -- and then set _quit in a `finally`, which cmd_run
reads as "the user closed the window". The server stopped a fraction of a
second after the browser had been pointed at it, and the first thing a new
user ever saw was ERR_CONNECTION_REFUSED.

_quit means a PERSON asked to leave. Nothing else may set it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import window as win_mod                      # noqa: E402
from autostream.window import MainWindow                      # noqa: E402

URL = "http://127.0.0.1:8787/?k=tok"


def a_window(monkeypatch):
    opened = []
    monkeypatch.setattr(win_mod.webbrowser, "open", lambda u: opened.append(u))
    return MainWindow(URL), opened


def test_a_failed_window_is_not_a_quit(monkeypatch):
    """The screenshot bug, exactly: the browser opens and the process must
    stay up to serve it."""
    class FakeWebview:
        @staticmethod
        def create_window(*a, **k):
            return type("W", (), {"events": type("E", (), {})()})()

        @staticmethod
        def start():
            raise RuntimeError("WebView2 runtime not found")

    monkeypatch.setattr(win_mod, "_HAS", True)
    monkeypatch.setattr(win_mod, "webview", FakeWebview)
    w, opened = a_window(monkeypatch)

    w.run()

    assert opened == [URL], "the browser was not opened"
    assert w.fell_back is True
    assert w._quit is False, "a dead window backend asked nobody to quit"


def test_no_pywebview_at_all_is_not_a_quit(monkeypatch):
    monkeypatch.setattr(win_mod, "_HAS", False)
    w, opened = a_window(monkeypatch)

    w.run()

    assert opened == [URL]
    assert w.fell_back is True
    assert w._quit is False


def test_a_window_that_could_not_be_created_is_not_a_quit(monkeypatch):
    class FakeWebview:
        @staticmethod
        def create_window(*a, **k):
            raise RuntimeError("no display")

        @staticmethod
        def start():                      # pragma: no cover - never reached
            raise AssertionError("start() must not run")

    monkeypatch.setattr(win_mod, "_HAS", True)
    monkeypatch.setattr(win_mod, "webview", FakeWebview)
    w, opened = a_window(monkeypatch)

    w.run()

    assert opened == [URL]
    assert w.fell_back is True
    assert w._quit is False


def test_closing_a_real_window_IS_a_quit(monkeypatch):
    """The other half. A window that opened and was closed must still stop
    the daemon, or the tray's Quit stops working."""
    started = []

    class FakeWebview:
        @staticmethod
        def create_window(*a, **k):
            return type("W", (), {"events": type("E", (), {})()})()

        @staticmethod
        def start():
            started.append(1)             # returns = the user closed it

    monkeypatch.setattr(win_mod, "_HAS", True)
    monkeypatch.setattr(win_mod, "webview", FakeWebview)
    monkeypatch.setattr(win_mod.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda s: None})())
    w, opened = a_window(monkeypatch)

    w.run()

    assert started == [1]
    assert w.fell_back is False
    assert w._quit is True, "a closed window must stop the daemon"
    assert opened == [], "no browser when the native window worked"


def test_request_quit_still_sets_it(monkeypatch):
    w, _ = a_window(monkeypatch)
    assert w._quit is False
    w.request_quit()
    assert w._quit is True
