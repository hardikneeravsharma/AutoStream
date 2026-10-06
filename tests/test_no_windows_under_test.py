r"""Nothing a test run does may put a window on somebody's screen.

THIS IS THE THIRD WAY ONE GOT THROUGH.

    file pickers      a modal Tk dialog with no parent, over whatever the
                      person was doing -- shut by AUTOSTREAM_NO_DIALOGS
    console windows   one per ffmpeg call, dozens a run -- shut by
                      creationflags=NO_WINDOW
    the app's own     one per test module, reported as "I have been seeing
                      autostream pop again and again on my screen"

The third is the worst of them, because it is the application window itself:
it takes focus, it is the size of the app, and the browser tier starts one for
every module it runs.

WHY AN ENVIRONMENT VARIABLE AND NOT A SETTING. `ui.open_window` is the setting
a person uses, and the harness seeds it too -- but a test that builds its own
home and forgets it would open a window anyway, and that is exactly how this
happened: `appd.seed_home` set `tray_icon: False` and said nothing about the
window. A guard that can be forgotten is not a guard. The variable is set once
where every test app is started, and the window code refuses before it looks
at anything else.

BOTH DOORS, NOT ONE. Without pywebview the app hands its UI to the real
browser instead, so a guard on only the native window would have answered a
machine with no WebView2 by opening a browser tab per module -- the same
interruption wearing a different hat.
"""
from __future__ import annotations

import pathlib
import re

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def window_src() -> str:
    return (ROOT / "autostream" / "window.py").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def main_src() -> str:
    return (ROOT / "autostream" / "__main__.py").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def appd_src() -> str:
    return (ROOT / "tests" / "verify" / "appd.py").read_text(encoding="utf-8")


# ------------------------------------------------- the harness shuts it

def test_every_app_a_test_starts_has_windows_switched_off(appd_src):
    """Set where the process is started, so no individual test can forget."""
    assert 'env["AUTOSTREAM_NO_WINDOW"] = "1"' in appd_src


def test_the_seeded_config_says_so_as_well(appd_src):
    """Belt and braces: the setting a person would use, in case anything ever
    reaches the window code by a route the variable does not cover."""
    assert '"ui": {"open_window": False}' in appd_src


def test_the_dialog_guard_is_still_there(appd_src):
    """The first of the three. Losing it would reopen the oldest of these."""
    assert 'env["AUTOSTREAM_NO_DIALOGS"] = "1"' in appd_src


# -------------------------------------------------- and the app honours it

def test_the_window_refuses_before_it_does_anything_else(window_src):
    """Before the pywebview check, so the browser fallback is covered too."""
    guard = window_src.index('AUTOSTREAM_NO_WINDOW')
    fallback = window_src.index("if not _HAS:")
    create = window_src.index("webview.create_window")
    assert guard < fallback, (
        "the guard runs after the pywebview check, so a machine without it "
        "would open a browser tab instead")
    assert guard < create


def test_it_tells_the_caller_to_hold_the_process_open(window_src):
    """`run` normally blocks on the window. Returning without setting
    `fell_back` would let cmd_run exit immediately and the server with it, so
    every browser test would find nothing answering."""
    block = window_src[window_src.index("AUTOSTREAM_NO_WINDOW"):]
    block = block[:block.index("if not _HAS:")]
    assert "self.fell_back = True" in block


def test_first_run_cannot_escape_it(main_src):
    """A test seeding an unconfigured home would otherwise open the setup
    wizard's window -- the one screen the quiet path deliberately never
    hides, for good reasons that do not apply to a test."""
    i = main_src.index("quiet = (")
    block = main_src[i:i + 400]
    assert "AUTOSTREAM_NO_WINDOW" in block
    # The variable has to come FIRST in the expression, or `first_run` short
    # circuits it away.
    assert block.index("AUTOSTREAM_NO_WINDOW") < block.index("first_run")


def test_os_is_imported_where_the_guard_reads_it(main_src, window_src):
    """A NameError here would be at startup, in the one path a test cannot
    see -- the app would simply never answer."""
    for src in (main_src, window_src):
        assert re.search(r"^import os$", src, re.M)


# ------------------------------------------- the other two, still shut

def test_ffmpeg_calls_still_hide_their_console(appd_src):
    assert "NO_WINDOW" in appd_src


def test_the_picker_still_refuses_outright():
    src = (ROOT / "autostream" / "webui.py").read_text(encoding="utf-8")
    assert 'os.environ.get("AUTOSTREAM_NO_DIALOGS")' in src
