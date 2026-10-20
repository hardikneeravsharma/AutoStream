"""The Mac window: closing quits (there is no tray to hide to), minimising
is the Dock's business, and a close mid-job asks first."""
from __future__ import annotations

import threading

import pytest

from autostream import window
from autostream.macos import window as mac


@pytest.fixture(autouse=True)
def _no_geometry(monkeypatch):
    monkeypatch.setattr(window, "save_geometry", lambda win: False)


def test_closing_quits_rather_than_hiding():
    w = mac.MacWindow("http://x/")
    assert w._on_closing() is True
    assert w._quit and w._asked_to_quit
    assert not w._hide.is_set(), "hidden with no tray to bring it back"


def test_minimising_does_not_hide_the_window():
    w = mac.MacWindow("http://x/")
    w._on_minimized()
    assert not w._hide.is_set()


def test_a_close_mid_job_asks_and_can_be_cancelled(monkeypatch):
    asked = []
    monkeypatch.setattr(mac, "_ask_to_quit", lambda why: asked.append(why) or False)
    w = mac.MacWindow("http://x/", busy=lambda: "a clip job")
    assert w._on_closing() is False
    assert asked == ["a clip job"] and not w._quit


def test_a_close_mid_job_can_be_confirmed(monkeypatch):
    monkeypatch.setattr(mac, "_ask_to_quit", lambda why: True)
    w = mac.MacWindow("http://x/", busy=lambda: "a reel render")
    assert w._on_closing() is True and w._quit


def test_the_question_is_only_asked_on_the_main_thread(monkeypatch):
    """Off it, an NSAlert is illegal; the close is allowed rather than risked."""
    monkeypatch.setattr(mac, "_ask_to_quit",
                        lambda why: pytest.fail("asked off the main thread"))
    w = mac.MacWindow("http://x/", busy=lambda: "a clip job")
    got = []
    t = threading.Thread(target=lambda: got.append(w._on_closing()))
    t.start()
    t.join()
    assert got == [True]


def test_a_quit_already_asked_for_is_not_asked_again(monkeypatch):
    monkeypatch.setattr(mac, "_ask_to_quit", lambda why: pytest.fail("asked twice"))
    w = mac.MacWindow("http://x/", busy=lambda: "a clip job")
    w._quit = True
    assert w._on_closing() is True


def test_a_busy_check_that_throws_does_not_trap_the_user():
    def boom():
        raise RuntimeError("x")

    w = mac.MacWindow("http://x/", busy=boom)
    assert w._on_closing() is True


def test_the_screen_answer_has_a_shape_even_without_appkit():
    left, top, w, h = mac.screen()
    assert w > 0 and h > 0
