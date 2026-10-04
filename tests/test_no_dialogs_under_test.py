"""The file picker must never open during an automated run.

FROM A REPORT, twice. A sweep presses controls it has not been told about --
that is what makes it a sweep -- and eight controls across four pages reach
the OS file picker. Both times the answer was to add the offending control to
a list of ones to avoid, and both times a control that was not on the list
opened a dialog over what the person at the keyboard was doing.

A denylist fails open. This one fails shut: the app refuses to open a picker
at all when AUTOSTREAM_NO_DIALOGS is set, so a control nobody remembered
cannot open one, because there is nothing to open.

There is a second reason beyond the nuisance. The dialog is modal and has no
parent window here, so it blocks the thread serving the page -- the app stops
answering and the run hangs instead of failing.
"""
from __future__ import annotations

import pytest

from autostream import webui


@pytest.fixture
def srv():
    return object.__new__(webui.Server)


@pytest.mark.parametrize("kind", ["video", "audio", "intro", "outro", ""])
def test_no_kind_of_picker_opens_when_dialogs_are_off(srv, kind, monkeypatch):
    monkeypatch.setenv("AUTOSTREAM_NO_DIALOGS", "1")

    def explode(*a, **k):                     # noqa: ANN002, ANN003
        raise AssertionError("a file dialog was opened during a test run")

    monkeypatch.setattr("tkinter.filedialog.askopenfilename", explode,
                        raising=False)
    got = srv.clips_pick(kind)
    assert got.get("error"), f"{kind!r} did not refuse: {got}"
    assert "switched off" in got["error"]


def test_the_harness_sets_the_flag_for_every_app_it_starts():
    """The guard is worth nothing if the harness forgets to ask for it."""
    import re
    from pathlib import Path

    src = Path("tests/verify/appd.py").read_text(encoding="utf-8")
    assert re.search(r'env\["AUTOSTREAM_NO_DIALOGS"\]\s*=', src), (
        "appd.start no longer sets AUTOSTREAM_NO_DIALOGS, so a browser test "
        "can open a file dialog on whoever is running it")


def test_a_real_run_is_unaffected(srv, monkeypatch):
    """The door is shut only for test runs. Without the variable the picker
    behaves exactly as it always did -- this is not a feature flag anybody
    ships switched on."""
    monkeypatch.delenv("AUTOSTREAM_NO_DIALOGS", raising=False)
    opened = []

    def fake(*a, **k):                        # noqa: ANN002, ANN003
        opened.append(True)
        return ""                             # as though cancelled

    monkeypatch.setattr("tkinter.filedialog.askopenfilename", fake,
                        raising=False)
    got = srv.clips_pick("video")
    assert opened, "the picker was refused when nothing asked it to be"
    assert got.get("ok") is True and got.get("path") == ""
