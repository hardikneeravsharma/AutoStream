r"""The beat engine: effects keyed to the song's grid, not to a kill.

Every other effect in `studio` keys off `kt`, the kill time of the shot it is
in. This keys off the grid, independent of where kills fall, which is what lets
a one-second shot carry two beats of effect.

The counts below are arithmetic over the SAME doubles ffmpeg uses, frame by
frame at 60 fps, so they are a simulation of the filter rather than an
assertion about the string. Checked against ffmpeg itself on a flat colour
while they were written: 24 flips over 12 seconds at 120 BPM, one frame on a
beat and three on a bar line, which is what this reproduces.

See docs/STYLE-FAST-PACED-HEADSHOT.md section 8.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import studio

FPS = 60


def flip_of(fx: list[str]) -> str:
    got = [f for f in fx if f.startswith("negate=")]
    assert len(got) == 1, fx
    return got[0]


def flip_frames(expr: str, seconds: float) -> list[int]:
    """Which frames the flip is on for, by running its own arithmetic."""
    gate = float(re.search(r"gte\(t,([0-9.]+)\)", expr).group(1))
    terms = [(float(a), float(b)) for a, b in
             re.findall(r"lt\(mod\(t\+([0-9.]+),([0-9.]+)\)", expr)]
    wins = [float(w) for w in re.findall(r"\),([0-9.]+)\)", expr)]
    assert len(terms) == len(wins), (terms, wins)
    out = []
    for i in range(int(seconds * FPS)):
        t = i / FPS
        if t < gate:
            continue
        if any((t + off) % period < win for (off, period), win in zip(terms, wins)):
            out.append(i)
    return out


def runs(frames: list[int]) -> list[int]:
    """Lengths of the consecutive stretches."""
    out: list[int] = []
    for f in frames:
        if out and f == prev + 1:
            out[-1] += 1
        else:
            out.append(1)
        prev = f
    return out


# ---- the flip, which is what the style is named for -----------------------


def test_one_flip_a_beat_and_three_frames_on_the_bar():
    fx = studio.beat_engine("o09", beat=0.5, drop=0.0, length=12.0)
    got = runs(flip_frames(flip_of(fx), 12.0))
    assert len(got) == 24, got            # 12s at 120 BPM is 24 beats
    assert got.count(3) == 6              # ...of which 6 are bar lines
    assert got.count(1) == 18


def test_the_windows_sit_between_frames_and_not_on_one():
    """The specification's 0.0167 and 0.0500 are exactly one and three frames
    at 60 fps, and a frame boundary is the worst place for a threshold:
    measured, 0.0167 caught TWO frames because 1/60 is 0.0166667, and 0.0500
    caught four because `mod` of a large offset gives it back a few picoseconds
    light. Half a frame either side costs nothing."""
    assert 0.0 < studio.FLIP_BEAT < 1 / FPS
    assert 2 / FPS < studio.FLIP_BAR < 3 / FPS


def test_the_grid_is_in_phase_with_the_drop_and_not_the_first_frame():
    """They coincide only when the song offset happens to be a whole number of
    beats. Half a beat out is the difference between an edit and a fault."""
    fx = studio.beat_engine("o09", beat=0.5, drop=4.25, length=20.0)
    on = flip_frames(flip_of(fx), 20.0)
    assert round(4.25 * FPS) in on
    assert round(4.75 * FPS) in on
    assert round(4.5 * FPS) not in on


def test_the_flip_starts_a_bar_before_the_drop_so_the_build_ramps_in():
    fx = studio.beat_engine("o09", beat=0.5, drop=6.0, length=30.0)
    first = flip_frames(flip_of(fx), 30.0)[0] / FPS
    assert first == pytest.approx(6.0 - 2.0, abs=1 / FPS)


def test_bar_only_is_offered_because_a_strobe_is_a_real_concern():
    """Over flat letterbox bands a whole-frame invert twice a second is a
    full-screen strobe -- 64 of them in 36 seconds. On bar lines it is 18,
    which still reads."""
    fx = studio.beat_engine("o10", beat=0.5, drop=0.0, length=12.0)
    assert len(runs(flip_frames(flip_of(fx), 12.0))) == 6


# ---- the rest of the chain ------------------------------------------------


def test_the_kick_is_evaluated_every_frame_or_it_does_nothing():
    """`eval=frame` is not optional: without it the expression is evaluated
    once at init and the brightness never moves."""
    fx = studio.beat_engine("o09", beat=0.5, drop=4.0, length=36.0)
    kick = [f for f in fx if f.startswith("eq=")][0]
    assert "eval=frame" in kick


def test_the_gate_runs_the_build_cool_and_the_last_act_hot():
    fx = studio.beat_engine("o09", beat=0.5, drop=4.0, length=36.0)
    kick = [f for f in fx if f.startswith("eq=")][0]
    assert f"lt(t,4.0000),{studio.GATE_BUILD}" in kick
    assert str(studio.GATE_LAST) in kick


def test_nothing_blacks_out_the_approach_to_the_drop_kill():
    """The spec's two black frames before the drop blanked the drop kill's last frames
    of approach once the kill sat on the drop; reviewed as the reel's worst defect."""
    fx = studio.beat_engine("o09", beat=0.5, drop=4.0, length=36.0)
    assert not [f for f in fx if f.startswith("drawbox=")]


def test_a_reel_with_no_drop_still_gets_a_grid():
    """Zero is honest: the grid starts at the first frame, which is what a reel
    with no build should do. What it must not do is refuse to run."""
    fx = studio.beat_engine("o09", beat=0.5, drop=0.0, length=12.0)
    assert flip_of(fx)
    assert not [f for f in fx if f.startswith("drawbox=")]


def test_no_song_means_no_engine_rather_than_a_division_by_zero():
    assert studio.beat_engine("o09", beat=0.0, drop=0.0, length=12.0) == []
    assert studio.beat_engine("o09", beat=0.5, drop=0.0, length=0.0) == []


def test_a_beat_that_is_not_a_round_number_keeps_its_flips_on_the_beat():
    """Murder in my Mind reads 0.499966 s a beat. Written to five places and taken
    forty thousand beats back for a positive `mod`, that was 4 us a beat and a sixth
    of a second in all: every beat flip of the reel landed 0.167 s after its beat."""
    beat, drop = 0.499966, 9 * 0.499966
    fx = studio.beat_engine("o09", beat=beat, drop=drop, length=36.0)
    on = flip_frames(flip_of(fx), 36.0)
    starts = [f for i, f in enumerate(on) if i == 0 or on[i - 1] != f - 1]
    for f in starts:
        beats_from_drop = (f / FPS - drop) / beat
        assert abs(beats_from_drop - round(beats_from_drop)) * beat <= 1 / FPS, (f / FPS, beats_from_drop)
    assert len(starts) >= 60


def test_a_flip_on_a_kill_is_one_partial_frame_and_elsewhere_as_before():
    """Three frames near-white over most of the picture took the drop kill and the
    slow-motion kill with them. ChatGPT's general rule: any flip within FLIP_GUARD of any
    kill stays on the grid but is one frame with FLIP_PARTIAL of the inverted picture."""
    fx = studio.beat_engine("o10", beat=0.5, drop=4.0, length=20.0, kills=[4.0, 6.01, 7.3, 9.0])
    flip = flip_of(fx)
    near = [float(a) + 0.001 for a, _ in re.findall(r"between\(t,([0-9.]+),([0-9.]+)\)", flip)]
    assert near == pytest.approx([4.0, 6.0])                    # 6.01 is a frame off its bar; 7.3 and 9.0 are not on one
    off = float(re.search(r"mod\(t\+([0-9.]+),", flip).group(1))
    lut = [f for f in fx if f.startswith("lutyuv=")]
    assert len(lut) == 1 and str(studio.FLIP_PARTIAL) in lut[0]
    soft = [(float(a), float(b)) for a, b in re.findall(r"between\(t,([0-9.]+),([0-9.]+)\)", lut[0])]

    def frames(bar_t):
        full = part = 0
        for i in range(int((bar_t - 0.1) * FPS), int((bar_t + 0.1) * FPS)):
            t = i / FPS
            full += (t + off) % 2.0 < studio.FLIP_BAR and not any(g - 0.001 <= t <= g + studio.FLIP_BAR for g in near)
            part += any(a <= t <= b for a, b in soft)
        return full, part
    assert frames(4.0) == (0, 1) and frames(6.0) == (0, 1) and frames(8.0) == (3, 0)
    # no kills near a flip: every flip as before, and nothing partial
    fx = studio.beat_engine("o10", beat=0.5, drop=4.0, length=20.0)
    assert "between" not in flip_of(fx) and not [f for f in fx if f.startswith("lutyuv=")]
