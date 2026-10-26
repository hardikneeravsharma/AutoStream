"""The volume lines: the song's and the game's level over the reel, with keyframes.

Asked for on 2026-10-27, modelled on filmcraft's Volume line. The line replaced the two dB
sliders, so the promises are: a reel without keyframes renders exactly as before, the render
follows the same line the page draws (vol_at), and ffmpeg really plays it at those levels.
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import editflow, studio                           # noqa: E402
from autostream.clips.tools import FfmpegMissing, binary                # noqa: E402

from test_studio import _built, _graph, root                            # noqa: E402,F401

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_keyframes_are_sorted_clamped_and_one_per_time():
    got = studio.vol_keys([[4, -6], [1, 3], "x", [2, "loud"], [1, -2], [-5, -900], [3, 99], [None, 1]])
    assert got == [[0.0, -60.0], [1.0, -2.0], [3.0, 12.0], [4.0, -6.0]]
    assert studio.vol_keys(None) == [] and studio.vol_keys({"a": 1}) == []
    assert len(studio.vol_keys([[i, 0] for i in range(500)])) == studio.VOL_KEYS


def test_the_line_is_straight_in_db_and_flat_past_its_ends():
    keys = [[2.0, 0.0], [4.0, -20.0], [6.0, -20.0]]
    assert studio.vol_at(keys, 5.0, 0.0) == 0.0                 # before the first: its level
    assert studio.vol_at(keys, 5.0, 3.0) == pytest.approx(-10.0)
    assert studio.vol_at(keys, 5.0, 5.0) == -20.0
    assert studio.vol_at(keys, 5.0, 60.0) == -20.0              # after the last: its level
    assert studio.vol_at([], -4.0, 3.0) == -4.0                 # no keyframes: the flat level


def test_no_keyframes_renders_as_every_reel_did(root):
    got, derived, _ = _built(root)
    got["song"] = ""
    assert "music_keys" not in got and "game_keys" not in got
    _, graph = _graph(got, derived)
    assert f"volume={got['game_db']}dB" in graph
    assert studio.vol_filter([], -3.0) == "volume=-3.0dB"


def test_the_project_keeps_its_lines_and_the_render_plays_them(root):
    got, derived, _ = _built(root)
    got["game_keys"] = [[0.5, 0.0], [1.5, -18.0]]
    got["music_keys"] = [[0, -6]]
    again, derived, _ = studio.normalise(got, root)
    assert again["game_keys"] == [[0.5, 0.0], [1.5, -18.0]] and again["music_keys"] == [[0.0, -6.0]]
    _, graph = _graph(again, derived)
    assert "volume='pow(10,(0.00+(-18.00)*clip((t-0.500)/1.000,0,1))/20)':eval=frame" in graph
    assert "\\," not in graph


def test_a_line_edit_is_a_rerender_not_a_replan():
    assert editflow.FIELDS["music_keys"] == "look" and editflow.FIELDS["game_keys"] == "look"


@pytest.fixture(scope="module")
def ff():
    try:
        return binary("ffmpeg")
    except FfmpegMissing as e:
        pytest.skip(str(e))


def _rms_db(ff, keys, flat, at: float) -> float:
    """A full-scale tone through the line's filter, measured in a 0.2 s window at `at`."""
    run = subprocess.run(
        [ff, "-hide_banner", "-nostdin", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
         "-af", f"volume=1,{studio.vol_filter(keys, flat)},atrim={at - 0.1:.3f}:{at + 0.1:.3f},astats=metadata=0",
         "-f", "null", "-"], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60)
    line = next(x for x in run.stderr.splitlines() if "RMS level dB" in x)
    return float(line.rsplit(":", 1)[1])


def test_ffmpeg_plays_the_line_at_the_levels_the_page_draws(ff):
    keys = [[1.0, 0.0], [3.0, -20.0], [5.0, -6.0]]
    ref = _rms_db(ff, [], 0.0, 0.5)
    for t in (0.5, 2.0, 3.0, 4.0, 5.5):
        assert _rms_db(ff, keys, 0.0, t) - ref == pytest.approx(studio.vol_at(keys, 0.0, t), abs=0.6), t
    assert math.isfinite(ref)
