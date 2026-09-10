"""Corpus planning, with no footage involved.

Deliberately unmarked, so it runs in the default offline tier: everything here
is arithmetic over hint times and a faked detector. The `media` tier is for
things that need real recordings; where the excerpts get cut is not one of
them, and it is the part that silently did nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus                                                  # noqa: E402


class _Kill:
    def __init__(self, t):
        self.time = t


class _Prof:
    label = "VALORANT"

    def __init__(self, missing=()):
        self._missing = list(missing)

    def missing(self):
        return self._missing


def _patch(monkeypatch, *, for_game, scan=None):
    """Point _hints_by_scanning at a fake detector.

    It imports both modules inside the function, so they have to be patched
    where they live rather than on `corpus`.
    """
    import autostream.clips.detect as detect
    import autostream.clips.profiles as profiles

    monkeypatch.setattr(profiles, "for_game", for_game)
    if scan is not None:
        monkeypatch.setattr(detect, "scan", scan)


# ------------------------------------------- the gap this was written for

def test_footage_with_no_hints_plans_no_windows_at_all():
    """WHY THE SCAN EXISTS. Both planners start from hints, so a VOD with no
    session.json and no sidecar produced an empty corpus -- and said nothing.

    Pinned rather than fixed in place: the planners are right to need hints.
    What was missing was anywhere for a first set of them to come from.
    """
    assert corpus._busy_windows([], 100, 2400.0, 4) == []
    assert corpus._quiet_windows([], 100, 2400.0, [], 1) == []


def test_a_scan_supplies_the_hints_a_downloaded_vod_has_none_of(monkeypatch):
    seen = {}

    def fake_scan(video, prof):
        seen["video"] = video
        return [_Kill(120.0), _Kill(121.4), _Kill(600.2)]

    _patch(monkeypatch, for_game=lambda k: _Prof(), scan=fake_scan)

    got = corpus._hints_by_scanning(Path("vod.mp4"), "valorant-win64-shipping.exe")
    assert got == [120.0, 121.4, 600.2]
    assert seen["video"] == Path("vod.mp4")
    # and those hints are now enough to place a window
    assert corpus._busy_windows(got, 100, 2400.0, 4)


def test_hints_from_a_scan_are_deduplicated_and_sorted(monkeypatch):
    _patch(monkeypatch, for_game=lambda k: _Prof(),
           scan=lambda v, p: [_Kill(9.0), _Kill(3.0), _Kill(9.04)])
    assert corpus._hints_by_scanning(Path("v.mp4"), "cs2.exe") == [3.0, 9.0]


# --------------------------------------------------- never fail the build
#
# A corpus build that dies on one unusable source loses the excerpts it could
# have cut from every other one. Every one of these is a real way an --extra
# VOD goes wrong on a machine that is not the one it was written on.

def _boom(video, prof):
    raise RuntimeError("ffmpeg went away")


@pytest.mark.parametrize("why, kw", [
    ("no profile for the game", {"for_game": lambda k: None}),
    ("the game is not set up",
     {"for_game": lambda k: _Prof(missing=[{"key": "player"}])}),
    ("the scan itself raised", {"for_game": lambda k: _Prof(), "scan": _boom}),
    # Not an error: a VOD with no kills has no windows to cut. The printed
    # message is what distinguishes it from a build that quietly did nothing.
    ("the detector found nothing",
     {"for_game": lambda k: _Prof(), "scan": lambda v, p: []}),
])
def test_hints_come_back_empty_rather_than_raising(why, kw, monkeypatch):
    _patch(monkeypatch, **kw)
    assert corpus._hints_by_scanning(Path("v.mp4"), "cs2.exe") == [], why
