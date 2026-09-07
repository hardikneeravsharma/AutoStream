"""The reel, actually rendered.

Tier 4, alongside test_media.py. Marked `media`, so a plain `pytest -q` skips
it: this decodes real footage and runs a real ffmpeg encode, which is tens of
seconds rather than milliseconds.

WHY THE SONG IS SYNTHESISED AND THE FOOTAGE IS NOT. They are being asked two
different questions.

The footage has to be real because the thing that goes wrong with a reel is a
shot that does not contain its own kill, and that only means anything against
frames a person has watched -- the same reviewed baselines test_media.py scores
the detectors on.

The song is built here, on purpose, because for music the reviewed baseline
does not exist and cannot: nobody has hand-marked every beat of a track, and a
real song is a file that lives on one machine and would make this tier
unrunnable anywhere else -- and the repo is public, so a commercial track could
not be committed even if it were the right answer. A click track written by the
test has something better than a reviewed truth: it has a KNOWN one. The tempo,
the phase, the downbeat and the bar the drums enter are all inputs here, so
`analyse` can be asked to return the numbers that went in rather than numbers
that merely look plausible. That is the strongest assertion available about a
grid, and it is only available because the song is synthetic.

Set AUTOSTREAM_REEL_SONG to a real track to run the same checks against one.
Nothing is asserted about its tempo -- there is no truth to assert against --
but the render must still come out the length the plan promised.
"""
from __future__ import annotations

import json
import os
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
import score
from autostream.clips import beatsync as bs, reel, tools

pytestmark = pytest.mark.media

CORPUS = Path(os.environ.get("AUTOSTREAM_TESTDATA", r"C:\autostream-testdata"))

BPM = 120.0
BEAT = 60.0 / BPM
BAR = BEAT * 4
LEAD_IN = 2.0            # silence before the first beat: the phase to recover
DOWNBEAT = 0             # which of the four positions carries the kick
DRUMS_AT = 8.0           # the bar the kit walks in on
SONG_SECONDS = 44.0


# ------------------------------------------------------------- the song

def _kick(sr: int, hz: float = 55.0, ms: int = 260) -> np.ndarray:
    n = np.arange(int(sr * ms / 1000))
    return (np.exp(-n / (sr * 0.05)) * np.sin(2 * np.pi * hz * n / sr)).astype(
        np.float32)


def _tick(sr: int, hz: float = 1400.0, ms: int = 40) -> np.ndarray:
    n = np.arange(int(sr * ms / 1000))
    return (0.25 * np.exp(-n / (sr * 0.006))
            * np.sin(2 * np.pi * hz * n / sr)).astype(np.float32)


def _write(path: Path, x: np.ndarray, sr: int) -> Path:
    """A 16-bit mono wav, because that is what every decoder agrees on."""
    pcm = np.clip(x, -1.0, 1.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((pcm * 32767).astype("<i2").tobytes())
    return path


@pytest.fixture(scope="session")
def song(tmp_path_factory) -> Path:
    """A click track whose grid is known because this wrote it.

    A tick on every beat from the top, so there is always a tempo to find, and
    the kick -- which is what `downbeat_position` reads -- held back until
    DRUMS_AT, which is what `drums_in` has to find. Two separate claims, in one
    file, that can be checked independently.
    """
    real = os.environ.get("AUTOSTREAM_REEL_SONG")
    if real:
        p = Path(real)
        if not p.is_file():
            pytest.skip(f"AUTOSTREAM_REEL_SONG points at nothing: {p}")
        return p

    sr = bs.SR
    x = np.zeros(int(SONG_SECONDS * sr), dtype=np.float32)
    kick, tick = _kick(sr), _tick(sr)
    i = 0
    t = LEAD_IN
    while t < SONG_SECONDS - 1.0:
        j = int(t * sr)
        x[j:j + tick.size] += tick[:max(0, x.size - j)]
        if t >= DRUMS_AT and i % 4 == DOWNBEAT:
            x[j:j + kick.size] += kick[:max(0, x.size - j)]
        i += 1
        t = LEAD_IN + i * BEAT
    out = tmp_path_factory.mktemp("reel") / "click.wav"
    return _write(out, x * 0.8, sr)


@pytest.fixture(scope="session")
def shape(song: Path) -> reel.Shape:
    return reel.analyse(song)


# ---------------------------------------------------------- the footage

def _manifest() -> list[dict]:
    p = CORPUS / "manifest.json"
    if not p.is_file():
        return []
    return json.loads(p.read_text(encoding="utf-8"))["excerpts"]


def _reviewed_busy() -> dict | None:
    """One excerpt a person has watched, with the most kills in it.

    Reviewed rather than merely present, because the reel is judged on whether
    each shot contains its kill -- which needs the kill times to be true, not
    the detector's guess at them.
    """
    best, most = None, 0
    for e in _manifest():
        if e.get("kind") != "busy":
            continue
        truth = ((score.baseline(e["game"]).get("clips") or {})
                 .get(e["clip"], {}).get("truth") or [])
        if len(truth) > most:
            best, most = dict(e, truth=sorted(float(t) for t in truth)), len(truth)
    return best


@pytest.fixture(scope="session")
def footage() -> dict:
    e = _reviewed_busy()
    if not e:
        pytest.skip(
            "no reviewed busy excerpt in the corpus -- build one with "
            "tests\\verify\\corpus.py and review it before this can run")
    if len(e["truth"]) < 3:
        pytest.skip(f"{e['clip']} has only {len(e['truth'])} reviewed kills")
    return e


# ================================================================ the grid

def test_the_tempo_comes_back_out_of_the_song_that_went_in(shape):
    """Within a fifth of a BPM. The tolerance is not taste: at 120 BPM over a
    44 second track, being out by 0.2 BPM has drifted the last beat by 12ms,
    and everything looser than that is audible by the end of a reel."""
    if os.environ.get("AUTOSTREAM_REEL_SONG"):
        pytest.skip("a real song has no known tempo to check against")
    assert shape.bpm == pytest.approx(BPM, abs=0.2), (
        f"wrote {BPM} BPM, read {shape.bpm:.2f}")


def test_the_phase_finds_the_first_beat_and_not_the_silence(shape):
    """The track opens with two seconds of nothing. A phase fitted to the file
    rather than to the music would put beat zero at t=0, and every cut in the
    reel would sit a fraction early for its whole length."""
    if os.environ.get("AUTOSTREAM_REEL_SONG"):
        pytest.skip("a real song has no known phase to check against")
    off = (shape.phase - LEAD_IN) % BEAT
    off = min(off, BEAT - off)
    assert off < 0.03, (
        f"first beat at {shape.phase:.3f}s, wrote it at {LEAD_IN}s "
        f"({off * 1000:.0f}ms off the grid)")


def test_the_downbeat_is_the_position_carrying_the_kick(shape):
    if os.environ.get("AUTOSTREAM_REEL_SONG"):
        pytest.skip("a real song has no known downbeat to check against")
    assert shape.downbeat_pos == DOWNBEAT


def test_the_drums_are_found_at_the_bar_they_walk_in_on(shape):
    """Within a bar either side -- the arrival is reported per bar, because
    that is the unit it is used in: kills are held back to the bar after it."""
    if os.environ.get("AUTOSTREAM_REEL_SONG"):
        pytest.skip("a real song has no known drum entry to check against")
    assert shape.drums_in is not None, "found no drum entry in a track that has one"
    assert abs(shape.drums_in - DRUMS_AT) <= BAR, (
        f"drums read at {shape.drums_in:.2f}s, written at {DRUMS_AT}s")


def test_every_beat_the_page_is_given_is_on_the_grid(shape):
    """The page snaps a tap to the nearest of these and never computes one of
    its own, so a beat list that wandered would be unfixable by hand."""
    beats = shape.beats
    assert len(beats) > 30, f"only {len(beats)} beats in {SONG_SECONDS}s"
    gaps = np.diff(beats)
    assert float(gaps.std()) < 1e-6, "the beat list is not a rigid grid"


# ============================================================== the render

def test_the_reel_renders_and_is_the_length_the_plan_promised(
        shape, footage, tmp_path):
    """The whole flow, end to end: a real recording, the kills a person
    confirmed are in it, the grid measured off a song, and one ffmpeg run.

    The duration is the assertion because it is the one number that catches
    every arithmetic slip at once. A shot sized from the wrong gap, a fade
    that starts inside the last kill, a pre-roll reaching back past the
    previous cut -- each of them lands here as a reel that is not the length
    of the song it was cut to.
    """
    if not tools.binary("ffmpeg"):
        pytest.skip("no ffmpeg on this machine")

    kills = [{"time": t, "round": i + 1, "labels": []}
             for i, t in enumerate(footage["truth"])]
    main = min(shape.seconds, 30.0)
    slots = reel.layout(shape, want=len(kills), template=reel.DEFAULT_TEMPLATE,
                        until=main)
    kills = kills[:len(slots)]
    shots = reel.shots(slots, kills, total=main)
    assert shots, "the plan produced no shots"

    out = tmp_path / "reel.mp4"
    argv = reel.command(CORPUS / footage["file"], shape.path, shots, out,
                        main=main, fade=0.0)
    r = subprocess.run(argv, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, f"ffmpeg failed:\n{r.stderr[-1200:]}"
    assert out.is_file() and out.stat().st_size > 100_000, "the reel came out empty"

    info = tools.media_info(out)
    got = float(info.get("duration") or 0)
    # A frame and a half of slack: the encoder lands on a frame boundary and
    # the last one is kept whole. Anything beyond that is arithmetic, not
    # rounding.
    assert got == pytest.approx(main, abs=0.05), (
        f"asked for {main:.2f}s, got {got:.2f}s")


def test_every_kill_lands_inside_its_own_shot_on_real_kill_times(shape, footage):
    """The failure this exists to prevent, measured against real spacing.

    Synthetic kills are evenly spaced; real ones are not. Two kills 0.4s apart
    is where the pre-roll arithmetic breaks, and the corpus has those and the
    unit tests do not.
    """
    kills = [{"time": t, "round": i + 1, "labels": []}
             for i, t in enumerate(footage["truth"])]
    main = min(shape.seconds, 30.0)
    for key in reel.TEMPLATES:
        slots = reel.layout(shape, want=len(kills), template=key, until=main)
        for sh in reel.shots(slots, kills[:len(slots)], total=main):
            assert sh.reel_in <= sh.kill_at <= sh.reel_in + sh.duration, (
                f"{key}: shot {sh.index} runs {sh.reel_in:.2f}"
                f"-{sh.reel_in + sh.duration:.2f}s but its kill is at "
                f"{sh.kill_at:.2f}s")


def test_the_shots_tile_the_reel_with_no_gap_and_no_overlap(shape, footage):
    """A gap is a black frame and an overlap is a dropped one. Neither shows
    up in a duration check, because the concat runs them back to back either
    way -- the reel is the right length and one of the kills is missing.
    """
    kills = [{"time": t, "round": i + 1, "labels": []}
             for i, t in enumerate(footage["truth"])]
    main = min(shape.seconds, 30.0)
    slots = reel.layout(shape, want=len(kills), template=reel.DEFAULT_TEMPLATE,
                        until=main)
    shots = reel.shots(slots, kills[:len(slots)], total=main)
    for a, b in zip(shots, shots[1:]):
        assert a.reel_in + a.duration == pytest.approx(b.reel_in, abs=1e-6), (
            f"shot {a.index} ends at {a.reel_in + a.duration:.4f}s, "
            f"shot {b.index} starts at {b.reel_in:.4f}s")
    last = shots[-1]
    assert last.reel_in + last.duration == pytest.approx(main, abs=1e-6)


def test_the_song_and_the_game_are_both_audible_in_the_result(
        shape, footage, tmp_path):
    """Measured off the rendered file, not asserted off the filter graph.

    The mix has been silently wrong twice -- once from a duck threshold under
    the room tone of a game capture, which held the duck open and left the
    result 8.7 dB quiet, and once from amix without normalize=0, which halved
    both inputs. Both produced a valid file of the right length, and both
    would pass every other test here.
    """
    if not tools.binary("ffmpeg"):
        pytest.skip("no ffmpeg on this machine")

    kills = [{"time": t, "round": i + 1, "labels": []}
             for i, t in enumerate(footage["truth"])]
    main = min(shape.seconds, 20.0)
    slots = reel.layout(shape, want=len(kills), template=reel.DEFAULT_TEMPLATE,
                        until=main)
    shots = reel.shots(slots, kills[:len(slots)], total=main)
    out = tmp_path / "mix.mp4"
    argv = reel.command(CORPUS / footage["file"], shape.path, shots, out,
                        main=main, fade=0.0)
    r = subprocess.run(argv, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, f"ffmpeg failed:\n{r.stderr[-1200:]}"

    x = bs.load_mono(out)
    assert x.size, "the reel has no audio at all"
    rms = float(np.sqrt(np.mean(np.square(x))))
    peak = float(np.abs(x).max())
    # -20 dBFS. A reel that has to be turned up is not finished, and both of
    # the bugs above landed well under this.
    assert rms > 0.1, f"the mix is {20 * np.log10(max(rms, 1e-9)):.1f} dBFS RMS"
    assert peak <= 1.0
    # The limiter is the last stage, so nothing should be riding the ceiling
    # for any length of time.
    assert float(np.mean(np.abs(x) > 0.99)) < 0.01, "the mix is clipping"
