"""The tools the clipper needs from outside Python.

ffmpeg and Tesseract are not pip packages, and both used to be discovered at
the moment they were first USED. For Tesseract that is several minutes into a
scan -- after the file was picked, the game chosen and the run started -- and
"Tesseract OCR was not found" arriving there is a true sentence delivered at
the least useful moment there is.

So the question is asked before anything is offered. These tests pin that: the
check happens up front, a missing OCR binary blocks only the games that
actually read text, and nothing installs itself without being asked.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest                                                     # noqa: E402

from autostream import webui                                      # noqa: E402
from autostream.clips import deps, killfeed                       # noqa: E402
from autostream.clips.profiles import Profile                     # noqa: E402


def a_profile(mode="killfeed", **kw) -> Profile:
    return Profile(key="game.exe", label="A Game", band=(0, 0, 1, 1),
                   template="t.png", mode=mode, **kw)


# ------------------------------------------------------------- what needs OCR

def test_only_the_killfeed_reader_needs_ocr():
    """The other three detectors were built specifically to avoid it, and
    telling a Delta Force user to install an OCR engine is a wall in front of
    something that was never going to use it."""
    assert a_profile("killfeed", player="me").needs_ocr
    for mode in ("template", "colour", "feedbar", "cardcount"):
        assert not a_profile(mode).needs_ocr, mode


# --------------------------------------------------- asked before the run
#
# The whole point. `_scan_ready` is what the Clips page greys its button on,
# so a missing tool has to reach it -- otherwise the page offers a run it
# knows will fail.

def _app():
    return webui.Server.__new__(webui.Server)


def test_a_killfeed_game_is_blocked_when_ocr_is_missing(monkeypatch):
    monkeypatch.setattr("autostream.clips.ocr_ready", lambda: False)
    ready, why, ocr = _app()._scan_ready(a_profile("killfeed", player="me"))
    assert not ready
    assert ocr, "the page cannot offer an Install button without knowing why"
    assert "Tesseract" in why


def test_the_same_game_is_ready_once_ocr_is_there(monkeypatch):
    monkeypatch.setattr("autostream.clips.ocr_ready", lambda: True)
    ready, why, ocr = _app()._scan_ready(a_profile("killfeed", player="me"))
    assert ready and not why and not ocr


def test_a_game_that_does_not_read_text_is_unaffected(monkeypatch):
    """Measured the wrong way round once already: a machine-wide tool must not
    decide whether a game with a template is clippable."""
    monkeypatch.setattr("autostream.clips.ocr_ready", lambda: False)
    ready, why, ocr = _app()._scan_ready(a_profile("feedbar"))
    assert ready and not why and not ocr


def test_a_missing_name_is_still_reported_as_a_missing_name(monkeypatch):
    """A missing name is typed in and a missing tool is installed, so the two
    must not collapse into one message. Saying "install Tesseract" to someone
    whose real problem is a blank name field sends them to the wrong place."""
    monkeypatch.setattr("autostream.clips.ocr_ready", lambda: False)
    ready, why, ocr = _app()._scan_ready(a_profile("killfeed", player=""))
    assert not ready
    assert not ocr
    assert "in-game name" in why


# ---------------------------------------------------------------- reporting

def test_state_names_every_tool_and_what_it_costs():
    st = deps.state()
    keys = {t["key"] for t in st["tools"]}
    assert keys == {"ffmpeg", "tesseract"}
    for t in st["tools"]:
        assert t["why"], "a tool the user is asked to install must say why"
        assert t["winget"], "and how"
        assert "found" in t


def test_missing_tesseract_alone_does_not_make_the_page_unusable(monkeypatch):
    """`ok` is about ffmpeg. Folding Tesseract into it would tell every Delta
    Force user the clipper does not work, when it works perfectly."""
    monkeypatch.setattr(deps, "_found",
                        lambda key: "" if key == "tesseract" else "C:/ffmpeg.exe")
    st = deps.state()
    assert st["ok"]
    assert st["missing"] == ["tesseract"]


def test_missing_ffmpeg_does(monkeypatch):
    monkeypatch.setattr(deps, "_found", lambda key: "")
    assert not deps.state()["ok"]


def test_ocr_why_not_is_empty_when_it_can_read(monkeypatch):
    monkeypatch.setattr(deps, "have_tesseract", lambda: True)
    monkeypatch.setattr(deps, "have_pytesseract", lambda: True)
    assert deps.ocr_why_not() == ""


def test_ocr_why_not_separates_the_binary_from_the_package(monkeypatch):
    """They have different fixes: one is a winget install, the other is a
    broken build. One message for both would be advice for the wrong half."""
    monkeypatch.setattr(deps, "have_tesseract", lambda: False)
    monkeypatch.setattr(deps, "have_pytesseract", lambda: True)
    assert "Tesseract OCR is not installed" in deps.ocr_why_not()

    monkeypatch.setattr(deps, "have_tesseract", lambda: True)
    monkeypatch.setattr(deps, "have_pytesseract", lambda: False)
    assert "pytesseract" in deps.ocr_why_not()


# ------------------------------------------------------------- installing

def test_nothing_installs_without_being_asked():
    """These are machine-wide installs that raise a UAC prompt. A prompt from
    a process the user asked nothing of is how software gets mistaken for
    something worse."""
    assert deps.installer().status() is None, (
        "an installer that has never been started must report nothing at all")


def test_an_install_refuses_rather_than_failing_when_winget_is_absent(monkeypatch):
    monkeypatch.setattr(deps, "winget", lambda: "")
    started, why = deps.Installer().start(["tesseract"])
    assert not started
    assert "winget" in why


def test_an_install_of_nothing_is_refused(monkeypatch):
    monkeypatch.setattr(deps, "winget", lambda: "C:/winget.exe")
    started, why = deps.Installer().start(["not-a-tool"])
    assert not started and why


# --------------------------------------------------------- the old names

def test_killfeed_still_exposes_the_names_its_callers_use():
    """calibrate.py catches kf.TesseractMissing and the CLI calls
    kf.tesseract(). Moving discovery must not break either."""
    assert killfeed.TesseractMissing is deps.ToolMissing
    assert killfeed.tesseract is deps.tesseract


def test_a_missing_tesseract_raises_something_that_says_what_to_do(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)
    monkeypatch.setattr(deps, "_TESSERACT_DIRS", (Path("Z:/nowhere"),))
    deps.tesseract.cache_clear()
    with pytest.raises(deps.ToolMissing) as e:
        deps.tesseract()
    deps.tesseract.cache_clear()
    assert "Clips page" in str(e.value) or "winget" in str(e.value)
