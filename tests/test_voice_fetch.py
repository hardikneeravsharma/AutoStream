"""Downloading the voice pack from inside the app.

FROM A REPORT: `voice.download` existed and nothing in the whole application
ever called it. The Clips page said "no voices installed" beside a voice
picker, and there was no button anywhere that would install them -- the only
way in was to read two URLs out of the source and place the files by hand.

These cover the job that fixes that: it runs off the request thread, it
reports progress, and -- the part worth guarding -- it decides it worked by
looking for the files rather than by the download loop ending without raising.
"""
from __future__ import annotations

import time

import pytest

from autostream.clips import voice


def _settle(f, limit=4.0):
    """Wait for the worker to stop. -> its last status."""
    end = time.time() + limit
    while time.time() < end:
        st = f.status()
        if st and st["state"] != "running":
            return st
        time.sleep(0.02)
    return f.status()


@pytest.fixture
def absent(monkeypatch):
    """A machine with no voice files on it."""
    monkeypatch.setattr(voice, "available", lambda: False)


def test_the_download_reports_progress_while_it_runs(absent, monkeypatch):
    seen = []

    def fake(progress=None):
        for name, size in voice.FILES.items():
            for part in (0, size // 2, size):
                progress(name, part, size)
                seen.append(part)
        monkeypatch.setattr(voice, "available", lambda: True)
        return []

    monkeypatch.setattr(voice, "download", fake)
    f = voice.Fetch()
    assert f.status() is None, "nothing to report before it is asked for"
    assert f.start() == (True, "")
    st = _settle(f)
    assert st["state"] == "done", st
    assert st["percent"] == 100
    assert st["total_mb"] == round(sum(voice.FILES.values()) / 1e6)
    assert seen, "progress was never called"


def test_a_download_that_lands_nothing_is_a_failure(absent, monkeypatch):
    """THE GUARD. A truncated response can close cleanly, leaving a file of
    the wrong size and a loop that ended without raising. Reporting that as
    done sends the user back to a voice picker that still says none are
    installed, with nothing to press."""
    monkeypatch.setattr(voice, "download", lambda progress=None: [])
    f = voice.Fetch()
    f.start()
    st = _settle(f)
    assert st["state"] == "failed", st
    assert "not complete" in st["error"]


def test_a_download_that_raises_says_so_rather_than_hanging(absent, monkeypatch):
    def boom(progress=None):
        raise OSError("the network went away")

    monkeypatch.setattr(voice, "download", boom)
    f = voice.Fetch()
    f.start()
    st = _settle(f)
    assert st["state"] == "failed"
    assert "network went away" in st["error"]


def test_it_will_not_download_what_is_already_here(monkeypatch):
    monkeypatch.setattr(voice, "available", lambda: True)
    ok, why = voice.Fetch().start()
    assert not ok
    assert "already installed" in why


def test_two_presses_do_not_start_two_downloads(absent, monkeypatch):
    monkeypatch.setattr(voice, "download",
                        lambda progress=None: time.sleep(0.3) or [])
    f = voice.Fetch()
    assert f.start()[0] is True
    ok, why = f.start()
    assert not ok, "a second press started a second 206 MB download"
    assert "already downloading" in why
    _settle(f)


def test_the_page_is_told_whether_installing_is_even_possible(monkeypatch):
    """The model files download; the kokoro-onnx PACKAGE does not. Offering a
    button that cannot fix the problem is worse than offering none."""
    from autostream import webui

    app = object.__new__(webui.Server)
    monkeypatch.setattr(voice, "available", lambda: False)
    monkeypatch.setattr(voice, "missing",
                        lambda: ["the kokoro-onnx package (pip install kokoro-onnx)"])
    assert app.clips_voices()["can_install"] is False

    monkeypatch.setattr(voice, "missing",
                        lambda: ["the model file kokoro-v1.0.fp16.onnx"])
    got = app.clips_voices()
    assert got["can_install"] is True
    assert got["size_mb"] == round(sum(voice.FILES.values()) / 1e6)
