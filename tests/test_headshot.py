"""Valorant headshots off the kill feed: the icon test, and which row is the kill's.

Synthetic frames, so no ffmpeg and no footage: a teal row with a yellow border
(the player's own) and, for a headshot, the shipped template drawn into it as
white -- the same white-on-teal the reader looks for.
"""
from __future__ import annotations

import numpy as np
import pytest

from autostream.clips import headshot

TEAL = (118, 186, 160)
RED = (208, 106, 92)
YELLOW = (220, 210, 125)
H_ROW = 34


def _band(rows: list[bool], w: int = 960, pitch: int = 39, top: int = 10) -> np.ndarray:
    """A band with one own kill row per entry, newest lowest; True draws the icon."""
    a = np.full((top + pitch * max(1, len(rows)) + 20, w, 3), 70, np.uint8)
    for i, hs in enumerate(rows):
        y0 = top + i * pitch
        x0, xb = 420, 760                     # the killer half; the victim half beyond it
        a[y0:y0 + H_ROW, x0:xb] = TEAL
        a[y0:y0 + H_ROW, xb:w - 20] = RED
        a[y0:y0 + 2, x0:xb] = YELLOW            # the own row's border, top and bottom
        a[y0 + H_ROW - 2:y0 + H_ROW, x0:xb] = YELLOW
        if hs:
            iw = int(round(headshot.ICON_W * H_ROW))
            icon = headshot._resize(headshot._tmpl(), iw, H_ROW) > 0.5
            patch = a[y0:y0 + H_ROW, xb - iw - 6:xb - 6]
            patch[icon] = (250, 250, 250)
    return a


def test_the_icon_scores_above_the_line_and_a_plain_row_below_it():
    a = _band([True, False])
    rows = headshot.own_rows(a, 1080)
    assert len(rows) == 2
    assert headshot.icon_score(a, rows[0]) >= headshot.THRESHOLD
    assert headshot.icon_score(a, rows[1]) < headshot.THRESHOLD


def test_a_kill_is_read_from_the_lowest_own_row(monkeypatch):
    """New rows go in at the bottom: a kill's own row is the newest one."""
    monkeypatch.setattr(headshot, "_frame", lambda v, t, size: (_band([False, True]), 1080))
    assert headshot._one("v.mp4", 10.0, [], (1920, 1080)) is True
    monkeypatch.setattr(headshot, "_frame", lambda v, t, size: (_band([True, False]), 1080))
    assert headshot._one("v.mp4", 10.0, [], (1920, 1080)) is False


def test_a_later_kill_pushes_this_ones_row_up(monkeypatch):
    """Two kills 0.3 s apart: by the time the frame is read, the second's row
    is the lowest, so the first's is the one above it -- the case where
    tracking rows from frame to frame swapped them."""
    monkeypatch.setattr(headshot, "_frame", lambda v, t, size: (_band([True, False]), 1080))
    assert headshot._one("v.mp4", 10.0, [10.3], (1920, 1080)) is True
    assert headshot._one("v.mp4", 10.3, [10.0], (1920, 1080)) is False


def test_no_own_row_is_unread_not_a_body_shot(monkeypatch):
    monkeypatch.setattr(headshot, "_frame", lambda v, t, size: (_band([]), 1080))
    assert headshot._one("v.mp4", 10.0, [], (1920, 1080)) is None


def test_annotate_writes_only_what_was_read(monkeypatch):
    monkeypatch.setattr(headshot, "read", lambda v, times: [True, None, False])
    kills = [{"time": 1.0}, {"time": 2.0}, {"time": 3.0}, {"note": "no time"}]
    assert headshot.annotate("v.mp4", kills) == 2
    assert kills[0]["hs"] is True and "hs" not in kills[1] and kills[2]["hs"] is False


@pytest.mark.parametrize("game,yes", [("VALORANT", True), ("valorant-win64-shipping.exe", True),
                                      ("Counter-Strike 2", False), ("", False)])
def test_only_valorant_is_read(game, yes):
    assert headshot.is_valorant(game) is yes


def test_the_template_ships_with_the_app():
    t = headshot._tmpl()
    assert t.ndim == 2 and t.shape[0] > t.shape[1] and 0.0 <= t.min() and t.max() <= 1.0
