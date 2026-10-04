"""Which recordings may be streamed back to the page, and which may not.

A route that streams whatever path it is handed is a file browser, so the one
that plays a recording in the Choose-the-part stage serves only files the user
has already pointed the app at: a recording in the journal, or one chosen
through the OS picker this session.

FROM A REPORT: the page fell back to building a three-minute preview of a file
that could have played whole. The file was fine; it simply was not registered
yet. The picker runs server-side and returns the path, so that is where it is
remembered -- the probe that used to do it is fired without being awaited, and
the part stage asked its question first.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from autostream import webui


@pytest.fixture
def srv(monkeypatch):
    s = object.__new__(webui.Server)
    # Class attributes are shared, so each test gets its own.
    s._picked = set()
    s._probed = {}
    return s


def _video(tmp_path: Path, name: str = "rec.mp4") -> Path:
    p = tmp_path / name
    p.write_bytes(b"\x00" * 2048)
    return p


def test_a_file_nobody_pointed_at_is_refused(srv, tmp_path, monkeypatch):
    monkeypatch.setattr(webui.Server, "_known_source",
                        webui.Server._known_source)
    stranger = _video(tmp_path, "someone-elses.mp4")
    monkeypatch.setattr("autostream.history.read", lambda *a, **k: [])
    assert srv._known_source(str(stranger)) is False


def test_a_file_chosen_from_the_picker_may_be_played(srv, tmp_path, monkeypatch):
    """The case that broke. The picker is server-side, so the path is known
    the instant the dialog closes -- long before anything probes it."""
    monkeypatch.setattr("autostream.history.read", lambda *a, **k: [])
    picked = _video(tmp_path)
    srv._picked.add(str(picked).lower())
    assert srv._known_source(str(picked)) is True


def test_a_recording_in_the_journal_may_be_played(srv, tmp_path, monkeypatch):
    rec = _video(tmp_path, "streamed.mp4")
    monkeypatch.setattr("autostream.history.read",
                        lambda *a, **k: [{"recording_path": str(rec)}])
    assert srv._known_source(str(rec)) is True


def test_the_check_does_not_care_about_the_shape_of_the_path(srv, tmp_path,
                                                             monkeypatch):
    """Windows hands the same file back in several spellings -- a picker's
    answer and a journal row routinely differ in case."""
    rec = _video(tmp_path, "Mixed Case.mp4")
    monkeypatch.setattr("autostream.history.read",
                        lambda *a, **k: [{"recording_path": str(rec).upper()}])
    assert srv._known_source(str(rec).lower()) is True


# -------------------------------------------------- can it be seeked at all

def _mp4(tmp_path: Path, order: tuple[bytes, ...], name="x.mp4") -> Path:
    """A file with real box headers in the given order and nothing inside."""
    import struct

    out = tmp_path / name
    body = b"".join(struct.pack(">I", 8 + 16) + k + b"\x00" * 16 for k in order)
    out.write_bytes(body)
    return out


def test_a_recording_with_an_index_can_be_played_whole(srv, tmp_path):
    """Either order is fine: a moov at the front is faststart, and one after
    the media is reached by a Range request for the tail."""
    assert srv._is_seekable(_mp4(tmp_path, (b"ftyp", b"moov", b"mdat"))) is True
    assert srv._is_seekable(_mp4(tmp_path, (b"ftyp", b"mdat", b"moov"))) is True


def test_a_fragmented_recording_is_not_pretended_to_be_seekable(srv, tmp_path):
    """The case the old comment was written about, and the only one that
    really has to fall back: moof with no moov is fragmented mp4, which a
    browser cannot seek."""
    assert srv._is_seekable(_mp4(tmp_path, (b"ftyp", b"moof", b"mdat"))) is False


def test_a_file_that_is_not_mp4_at_all_is_not_claimed_to_be_seekable(srv,
                                                                    tmp_path):
    junk = tmp_path / "notvideo.mp4"
    junk.write_bytes(b"this is not an mp4 at all, not even close")
    assert srv._is_seekable(junk) is False


def test_a_format_no_browser_plays_is_reported_as_unplayable(srv, tmp_path,
                                                             monkeypatch):
    """ffmpeg reads .mkv and .avi happily and no browser plays either, so the
    answer has to be about the BROWSER rather than about ffmpeg."""
    mkv = _mp4(tmp_path, (b"ftyp", b"moov", b"mdat"), name="rec.mkv")
    srv._picked.add(str(mkv).lower())
    monkeypatch.setattr("autostream.history.read", lambda *a, **k: [])
    got = srv.clips_source_info(str(mkv))
    assert got["ok"] is True
    assert got["seekable"] is False, "a .mkv was offered to a <video> tag"
    assert got["why"], "nothing told the page why it cannot play this"
