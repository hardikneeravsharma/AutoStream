"""Downloading a demo from a match sharing code.

The sharing code is the only handle on a demo a person can copy out of the game,
and Counter-Strike acts on one through a steam:// link. That link asks the
user's OWN client to fetch the file -- so this needs no Steam credentials, no
API key and no game-coordinator protocol, and AutoStream never downloads
anything itself.

Several at once, because a live session routinely spans more than one match.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import cs2_demo                             # noqa: E402


REAL = "CSGO-Jojzi-QtbwS-xCf7V-jNcQK-G8MkO"
LINK = ("steam://rungame/730/76561202255233023/+csgo_download_match%20" + REAL)


def test_a_bare_code_is_found():
    assert cs2_demo.share_codes(REAL) == [REAL]


def test_the_whole_steam_link_is_found():
    """What the game actually puts on the clipboard."""
    assert cs2_demo.share_codes(LINK) == [REAL]


def test_several_matches_in_one_paste():
    """A long session covers more than one match, and pasting them one at a
    time would be the tedious way to say the same thing."""
    other = "CSGO-abcde-ABCDE-23456-fhijk-mnopq"
    got = cs2_demo.share_codes(f"{LINK}\n{other}\n")
    assert got == [REAL, other]


def test_the_same_code_twice_is_one_download():
    assert cs2_demo.share_codes(f"{REAL}\n{REAL}") == [REAL]


def test_order_is_kept():
    a, b = REAL, "CSGO-77777-88888-99999-22222-33333"
    assert cs2_demo.share_codes(f"{a}\n{b}") == [a, b]


def test_prose_around_the_codes_is_ignored():
    got = cs2_demo.share_codes(f"here you go:\n  {REAL}  <- nuke\nthanks")
    assert got == [REAL]


def test_something_that_only_looks_like_a_code_is_rejected():
    """A wrong code would send Counter-Strike after a match that does not
    exist, and the failure would be silent inside the game."""
    assert cs2_demo.share_codes("CSGO-short CSGO-11111 CSGO") == []


def test_the_confusable_letters_are_not_in_the_alphabet():
    """The alphabet deliberately omits I, l, 0, 1 so a hand-copied code cannot
    be ambiguous. Accepting them would accept typos as valid."""
    for bad in "Il01":
        assert bad not in cs2_demo.SHARE_ALPHABET


def test_the_link_carries_the_code_and_the_download_command():
    link = cs2_demo.download_link(REAL)
    assert link.startswith("steam://rungame/730/")
    assert "csgo_download_match" in link
    assert REAL in link


def test_a_given_steamid_is_used():
    assert "12345" in cs2_demo.download_link(REAL, "12345")


def test_requesting_a_download_never_raises(monkeypatch):
    """It runs from a button. A shell that refuses the protocol must report
    false, not take the page down."""
    def boom(_link):
        raise OSError("no handler for steam:")
    monkeypatch.setattr(cs2_demo.os, "startfile", boom, raising=False)
    assert cs2_demo.request_download(REAL) is False


def test_a_successful_request_says_so(monkeypatch):
    opened = []
    monkeypatch.setattr(cs2_demo.os, "startfile", opened.append, raising=False)
    monkeypatch.setattr(cs2_demo.sys, "platform", "win32")
    assert cs2_demo.request_download(REAL) is True
    assert opened and REAL in opened[0]
