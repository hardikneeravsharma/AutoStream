"""The song's rhythm layers: kick, snare, hats, cues and sections.

Synthetic drums, so the truth is known to the sample: every claim here is that
a hit placed at t is read at t, in the right layer, and nowhere else. What the
reader makes of real songs (That Acid's kicks on the grid, Y Que Fue's grid half
a beat off its kick) was measured by hand when this was written and is recorded
in the module's comments; it needs the audio, so it is not asserted here.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import rhythm as R                          # noqa: E402

SR = R.SR
RNG = np.random.default_rng(7)


def kick():
    t = np.arange(int(0.3 * SR)) / SR
    y = np.sin(2 * np.pi * np.cumsum(50 + 100 * np.exp(-t / 0.03)) / SR) * np.exp(-t / 0.12)
    y[:int(0.004 * SR)] += RNG.normal(0, 0.5, int(0.004 * SR))       # the beater's click
    return y


def snare():
    t = np.arange(int(0.2 * SR)) / SR
    return RNG.normal(0, 1, t.size) * np.exp(-t / 0.05) * 0.5 + np.sin(2 * np.pi * 200 * t) * np.exp(-t / 0.05) * 0.3


def hat():
    t = np.arange(int(0.05 * SR)) / SR
    return np.diff(RNG.normal(0, 1, t.size), prepend=0) * np.exp(-t / 0.01) * 0.2


def put(x, t, g, gain=1.0):
    a = int(t * SR)
    n = min(len(g), len(x) - a)
    if n > 0:
        x[a:a + n] += gain * g[:n]


def song(seconds=30.0, bpm=120.0, first=0.25, loud_from=None, quiet_gain=0.15):
    """Kick on 1 and 3, snare on 2 and 4, hats on every eighth.

    With loud_from, everything before it is played at quiet_gain and without kick."""
    beat = 60.0 / bpm
    x = np.zeros(int(seconds * SR))
    truth = {"kick": [], "snare": [], "hats": []}
    for i in range(int((seconds - first) / beat)):
        t = first + i * beat
        quiet = loud_from is not None and t < loud_from
        g = quiet_gain if quiet else 1.0
        if i % 2 == 0 and not quiet:
            put(x, t, kick())
            truth["kick"].append(t)
        if i % 2 == 1:
            put(x, t, snare(), g)
            truth["snare"].append(t)
        for h in (0.0, beat / 2):
            put(x, t + h, hat(), g)
            truth["hats"].append(t + h)
    x += RNG.normal(0, 0.003, x.size)
    return x.astype(np.float32), beat, truth


def nearest(found, truth):
    found = np.asarray(found)
    return np.array([found[np.argmin(np.abs(found - t))] - t for t in truth])


# ------------------------------------------------------------ the layers

def test_each_layer_is_read_at_its_hits():
    x, beat, truth = song()
    r = R.analyse_signal(x, beat=beat, phase=0.25)
    for name in ("kick", "hats"):
        err = nearest(r.layers[name].times, truth[name])
        assert np.all(np.abs(err) < 0.008), (name, err)
    # every snare is read; hats bleed into the snare band, so a few more may be
    err = nearest(r.layers["snare"].times, truth["snare"])
    assert np.all(np.abs(err) < 0.008)


def test_a_kick_is_one_hit_and_on_its_click():
    """The low band swells for a window after the beater lands; the kick is
    stamped where the click is, not where the swell peaks, and once."""
    x, beat, truth = song()
    r = R.analyse_signal(x, beat=beat, phase=0.25)
    assert len(r.layers["kick"].times) == len(truth["kick"])
    assert np.median(np.abs(nearest(r.layers["kick"].times, truth["kick"]))) < 0.004


def test_hits_are_found_in_a_quiet_stretch_too():
    """Local, not song-wide: hats at a seventh of the volume are still hats."""
    x, beat, truth = song(loud_from=15.0)
    r = R.analyse_signal(x, beat=beat, phase=0.25)
    quiet_truth = [t for t in truth["hats"] if t < 14.5]
    quiet_found = [t for t in r.layers["hats"].times if t < 14.5]
    assert len(quiet_found) >= 0.9 * len(quiet_truth)
    # ...and they are weaker than the loud ones
    s = dict(zip(r.layers["hats"].times, r.layers["hats"].strength))
    assert np.median([s[t] for t in quiet_found]) < 0.5 * np.median([v for t, v in s.items() if t > 16])


def test_strengths_are_in_range():
    x, beat, _ = song()
    r = R.analyse_signal(x, beat=beat, phase=0.25)
    for L in r.layers.values():
        assert L.strength and all(0.0 <= s <= 1.0 for s in L.strength)


def test_kick_phase_reports_a_grid_half_a_beat_off():
    """Y Que Fue's case: the grid on the off-beat. Reported, never applied underneath."""
    x, beat, _ = song()
    on = R.analyse_signal(x, beat=beat, phase=0.25)
    off = R.analyse_signal(x, beat=beat, phase=0.25 + beat / 2)
    assert abs(on.kick_offset) < 0.05
    assert abs(abs(off.kick_offset) - 0.5) < 0.05
    assert off.phase == pytest.approx(0.25 + beat / 2)      # the grid itself is untouched


def test_silence_reads_as_nothing():
    r = R.analyse_signal(np.zeros(SR * 5, np.float32), beat=0.5, phase=0.0)
    assert all(not L.times for L in r.layers.values())
    assert r.sections


# ------------------------------------------------------------ cues

def test_hits_together_are_one_cue_with_each_layer_strength():
    layers = {"kick": R.Layer("kick", [1.000, 2.0], [0.9, 0.8]),
              "snare": R.Layer("snare", [3.0], [0.7]),
              "hats": R.Layer("hats", [1.012, 1.5], [0.4, 0.3])}
    cues = R.cluster(layers)
    assert [c["t"] for c in cues] == [1.0, 1.5, 2.0, 3.0]
    first = cues[0]
    assert first["kick"] == 0.9 and first["hats"] == 0.4 and first["snare"] == 0.0
    assert first["strength"] > 0.9                         # a compound cue outranks its loudest part
    assert cues[1]["hats"] == 0.3 and cues[1]["kick"] == 0.0


def test_hits_further_apart_than_the_window_stay_separate():
    layers = {"kick": R.Layer("kick", [1.0], [1.0]), "snare": R.Layer("snare", [1.04], [1.0]),
              "hats": R.Layer("hats", [], [])}
    assert len(R.cluster(layers)) == 2


# ------------------------------------------------------------ sections

def test_a_drop_after_a_quiet_build_is_found():
    x, beat, _ = song(seconds=40.0, loud_from=20.25)
    r = R.analyse_signal(x, beat=beat, phase=0.25, drops=[20.25])
    drop = next(s for s in r.sections if s.kind == "drop")
    assert drop.start == pytest.approx(20.25, abs=0.01)
    before = r.section_at(19.0)
    assert before is not None and before.kind == "riser"
    assert r.section_at(25.0).kind == "drop"
    # sections tile the song with no gaps
    for a, b in zip(r.sections, r.sections[1:]):
        assert a.end == pytest.approx(b.start)
    assert r.sections[0].start == 0.0 and r.sections[-1].end == pytest.approx(40.0, abs=0.01)


def test_a_drop_inside_the_intro_is_not_the_drop():
    x, beat, _ = song(seconds=40.0, loud_from=20.25)
    r = R.analyse_signal(x, beat=beat, phase=0.25, drops=[6.25], drums_in=20.25)
    assert not any(s.kind == "drop" for s in r.sections)
    assert r.section_at(3.0).kind == "intro"


def test_a_one_bar_blip_is_not_a_section():
    """Loud, one quiet bar, loud: a fill, not a break."""
    x, beat, _ = song(seconds=40.0)
    bar = 4 * beat
    a = int((0.25 + 5 * bar) * SR)
    x[a:a + int(bar * SR)] *= 0.05
    r = R.analyse_signal(x, beat=beat, phase=0.25)
    assert not any(s.kind == "break" and s.end - s.start <= bar + 0.01 for s in r.sections)


# ------------------------------------------------------------ keeping it

def test_round_trip_and_an_old_schema_is_refused():
    x, beat, _ = song(seconds=10.0)
    r = R.analyse_signal(x, beat=beat, phase=0.25)
    d = json.loads(json.dumps(r.as_dict()))
    back = R.Rhythm.from_dict(d)
    assert back.layers["kick"].times == r.layers["kick"].times
    assert back.sections == r.sections
    assert back.kick_offset == pytest.approx(r.kick_offset, abs=0.001)
    d["schema"] = R.SCHEMA - 1
    with pytest.raises(ValueError):
        R.Rhythm.from_dict(d)


def test_for_song_reads_once_and_then_from_the_cache(tmp_path, monkeypatch):
    from autostream.clips import beatsync as bs, reel
    x, beat, _ = song(seconds=12.0)
    f = tmp_path / "song.m4a"
    f.write_bytes(b"not really audio")
    reads = []

    def load(path, *a, **k):
        reads.append(path)
        return x
    monkeypatch.setattr(bs, "load_mono", load)
    shape = reel.Shape(path=f, seconds=12.0, bpm=120.0, phase=0.25, downbeat_pos=0, drop=None,
                       drums_in=None, beats=[0.25 + i * beat for i in range(23)])
    one = R.for_song(shape, tmp_path / "cache")
    two = R.for_song(shape, tmp_path / "cache")
    assert len(reads) == 1
    assert two.layers["snare"].times == one.layers["snare"].times
