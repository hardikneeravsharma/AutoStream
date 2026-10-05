r"""Generic highlight detection, measured against audio with known bursts.

MEASURED, NOT READ. The other detectors in this package have ground truth to
score against -- a CS2 demo file, a labelled set of Valorant clips. This one
has something better: audio that can be built to order, so a test can say
"there is a burst at 12.0s and another at 40.0s" and then ask whether it was
found, to the tenth of a second.

Every signal below is synthesised with ffmpeg. Nothing here depends on a
recording anybody has.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from autostream.clips import loudness
from autostream.clips.tools import FfmpegMissing, binary

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@pytest.fixture(scope="module")
def ff():
    try:
        return binary("ffmpeg")
    except FfmpegMissing as e:
        pytest.skip(str(e))


def make_audio(ff, out: Path, seconds: float, bursts: list[float], *,
               burst_len: float = 1.2, floor_db: float = -34.0,
               burst_db: float = -6.0) -> Path:
    """Quiet noise for `seconds`, with a loud tone at each time in `bursts`.

    The floor is NOISE rather than silence on purpose. Silence makes a rolling
    median of -120 dB and every burst a 114 dB rise, which would pass a
    detector that does nothing but compare against a constant -- the thing
    this is meant to prove it is not doing.
    """
    parts = [f"anoisesrc=d={seconds}:c=pink:a={10 ** (floor_db / 20):.5f}"]
    mixes = ["[0:a]"]
    for i, at in enumerate(bursts, start=1):
        parts.append(
            f"sine=f=220:d={burst_len},"
            f"volume={10 ** (burst_db / 20):.5f},"
            f"adelay={int(at * 1000)}|{int(at * 1000)}")
        mixes.append(f"[{i}:a]")
    graph = "".join(mixes) + f"amix=inputs={len(mixes)}:duration=first:normalize=0"
    args = [ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    for p in parts:
        args += ["-f", "lavfi", "-i", p]
    args += ["-filter_complex", graph, "-ac", "1", "-ar", "16000",
             "-c:a", "aac", str(out)]
    subprocess.run(args, check=True, capture_output=True,
                   creationflags=NO_WINDOW, timeout=300)
    return out


def near(found: list, want: float, slack: float = 1.5) -> bool:
    return any(abs(t - want) <= slack for t, _, _ in found)


# ----------------------------------------------------- reading the audio

def test_the_envelope_follows_the_sound(ff, tmp_path):
    a = make_audio(ff, tmp_path / "one.m4a", 30.0, [12.0])
    env = loudness.envelope(a)
    assert env.size > 0
    # 20 readings a second over 30 seconds, give or take the encoder's
    # priming samples.
    assert 560 <= env.size <= 640, env.size
    quiet = float(np.median(env[:int(8 * loudness.HZ)]))
    loud = float(np.max(env[int(11.5 * loudness.HZ):int(13 * loudness.HZ)]))
    assert loud > quiet + 15, (quiet, loud)


def test_silence_does_not_become_negative_infinity(ff, tmp_path):
    """-inf poisons every mean, median and comparison it touches."""
    out = tmp_path / "quiet.m4a"
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "lavfi", "-i", "anullsrc=d=5", "-ac", "1",
                    "-ar", "16000", "-c:a", "aac", str(out)],
                   check=True, capture_output=True, creationflags=NO_WINDOW,
                   timeout=120)
    env = loudness.envelope(out)
    assert np.isfinite(env).all()
    assert env.min() >= -121


def test_a_file_with_no_audio_is_not_a_crash(ff, tmp_path):
    """OBS can be configured to record without audio, and that is a thing to
    report rather than to fall over on."""
    out = tmp_path / "mute.mp4"
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=5:d=3",
                    "-pix_fmt", "yuv420p", str(out)],
                   check=True, capture_output=True, creationflags=NO_WINDOW,
                   timeout=120)
    assert loudness.find(out) == []


# ------------------------------------------------------- finding moments

def test_a_single_burst_is_found_where_it_was_put(ff, tmp_path):
    a = make_audio(ff, tmp_path / "one.m4a", 60.0, [25.0])
    got = loudness.find(a)
    assert len(got) == 1, got
    assert near(got, 25.0), got


def test_several_bursts_are_all_found(ff, tmp_path):
    want = [15.0, 40.0, 72.0, 95.0]
    a = make_audio(ff, tmp_path / "many.m4a", 120.0, want)
    got = loudness.find(a)
    assert len(got) == len(want), got
    for w in want:
        assert near(got, w), (w, got)


def test_quiet_noise_on_its_own_produces_nothing(ff, tmp_path):
    """THE FALSE-POSITIVE TEST, and the one that matters most: a detector
    that marks everything is no better than no detector, and costs the user
    the time it takes to watch what it marked."""
    a = make_audio(ff, tmp_path / "flat.m4a", 90.0, [])
    assert loudness.find(a) == []


def test_a_burst_in_a_loud_game_is_still_found(ff, tmp_path):
    """THE REASON THE BASELINE ROLLS. Games are mixed differently and people
    set their own volumes. A fixed "louder than X dBFS" finds everything in
    one recording and nothing in the next.

    MEASURED: this file's floor sits at -35.6 dB against the -49.7 dB of the
    test above -- fourteen decibels louder -- and the burst rises 13.2 dB
    above it where the other rises 22.7. Both are found, which is the claim."""
    a = make_audio(ff, tmp_path / "loud.m4a", 60.0, [30.0],
                   floor_db=-20.0, burst_db=-2.0)
    got = loudness.find(a)
    assert len(got) == 1, got
    assert near(got, 30.0), got


def test_a_sound_barely_above_its_surroundings_is_not_a_highlight(ff, tmp_path):
    """THE EDGE, MEASURED RATHER THAN ASSUMED. This burst is audible and sits
    about 8.4 dB above the noise around it -- under the 9 dB the threshold
    asks for -- and it is not reported.

    Written after a test that assumed the opposite and failed: the detector
    was right and the premise was wrong. A moment barely louder than the
    minute around it is not a moment, and a threshold that caught this would
    catch every reload and footstep in a real recording.

    ASSERTED AGAINST THE MEASURED RISE, not against the recipe that produced
    it. Pinning "this file yields exactly 8.4 dB" put the test a tenth of a
    decibel from the threshold and it flaked on encoder variation -- which is
    the test being brittle, not the detector."""
    a = make_audio(ff, tmp_path / "marginal.m4a", 60.0, [30.0],
                   floor_db=-14.0, burst_db=-2.0)
    env = loudness.envelope(a)
    base = float(np.median(env))
    rise = float(np.max(env[int(29 * loudness.HZ):int(32 * loudness.HZ)])) - base
    assert 6.0 < rise < 12.0, f"this file is no longer near the edge: {rise:.2f} dB"

    found = loudness.find(a)
    if rise < loudness.RISE_DB:
        assert found == [], f"{rise:.2f} dB was reported against a {loudness.RISE_DB} dB floor"
    else:
        assert len(found) == 1, f"{rise:.2f} dB cleared the floor and was missed"

    # Either way the burst IS there: told to be generous enough, it is found.
    # That is what makes the refusal above a decision rather than deafness.
    assert len(loudness.find(a, rise_db=rise - 2.0)) == 1


def test_a_quiet_recording_does_not_find_its_own_hiss(ff, tmp_path):
    """The other half of the same argument. +9 dB above near-silence is still
    near-silence, and the floor is what stops a room-tone recording coming
    back full of highlights."""
    a = make_audio(ff, tmp_path / "hiss.m4a", 60.0, [], floor_db=-70.0)
    assert loudness.find(a) == []


def test_a_burst_the_length_of_a_firefight_is_one_moment(ff, tmp_path):
    """A firefight is not twelve highlights."""
    a = make_audio(ff, tmp_path / "fight.m4a", 90.0, [40.0], burst_len=8.0)
    got = loudness.find(a)
    assert len(got) == 1, got


def test_two_bursts_close_together_merge_and_keep_the_louder(ff, tmp_path):
    """Merged on the LOUDEST rather than the first: the first is usually the
    opening shot and the clip wants the kill."""
    a = make_audio(ff, tmp_path / "pair.m4a", 60.0, [20.0])
    make_audio(ff, a, 60.0, [20.0, 23.0])
    got = loudness.find(a, merge_gap=6.0)
    assert len(got) == 1, got
    assert 19.0 <= got[0][0] <= 24.5, got


def test_the_same_two_are_separate_with_a_shorter_gap(ff, tmp_path):
    a = make_audio(ff, tmp_path / "pair2.m4a", 60.0, [20.0, 26.0])
    got = loudness.find(a, merge_gap=2.0)
    assert len(got) == 2, got


# ------------------------------------------------------ what it hands back

def test_the_end_is_past_the_peak(ff, tmp_path):
    """`end` is what a clip is cut against; ending it on the peak would cut
    the moment off at the moment."""
    a = make_audio(ff, tmp_path / "tail.m4a", 60.0, [30.0])
    t, _, end = loudness.find(a)[0]
    assert end >= t + loudness.TAIL


def test_the_score_is_how_far_above_its_surroundings_it_got(ff, tmp_path):
    """The only ranking available here, and a real one."""
    a = make_audio(ff, tmp_path / "score.m4a", 60.0, [30.0])
    _, score, _ = loudness.find(a)[0]
    assert score >= loudness.RISE_DB
    assert score < 100, "a dB rise this large means the baseline collapsed"


def test_a_limit_keeps_the_loudest_and_returns_them_in_order(ff, tmp_path):
    """A shortlist is ranked for choosing and watched in order."""
    a = make_audio(ff, tmp_path / "rank.m4a", 150.0, [20.0, 60.0, 100.0, 135.0])
    got = loudness.find(a, limit=2)
    assert len(got) == 2
    assert got[0][0] < got[1][0], "returned in rank order, not time order"


def test_times_are_offsets_into_the_file_not_into_the_window(ff, tmp_path):
    """A caller that scanned part of a recording must not have to add `start`
    back on -- that is the arithmetic that goes wrong once and is never
    noticed."""
    a = make_audio(ff, tmp_path / "win.m4a", 120.0, [80.0])
    got = loudness.find(a, start=60.0, duration=40.0)
    assert len(got) == 1, got
    assert near(got, 80.0, slack=2.0), got


# ------------------------------------- the peak finder, without any ffmpeg

def test_the_baseline_is_a_median_and_not_a_mean():
    """The mean of a window containing an explosion is dragged up by the
    explosion, which is exactly the thing it is supposed to describe the
    absence of."""
    hz = 20.0
    level = np.full(int(120 * hz), -40.0, dtype=np.float32)
    level[int(60 * hz):int(64 * hz)] = 0.0        # four very loud seconds
    base = loudness._baseline(level, hz, 45.0)
    assert float(np.median(base)) < -38.0, (
        "the loud part raised the floor it is measured against")


def test_a_rise_that_lasts_one_reading_is_still_a_moment():
    hz = 20.0
    level = np.full(int(60 * hz), -40.0, dtype=np.float32)
    level[int(30 * hz)] = -10.0
    got = loudness.peaks(level, hz)
    assert len(got) == 1
    assert abs(got[0][0] - 30.0) < 0.3


def test_nothing_at_all_is_an_empty_list_not_an_error():
    assert loudness.peaks(np.empty(0, dtype=np.float32)) == []
    assert loudness.peaks(np.full(10, -40.0, dtype=np.float32)) == []


def test_a_step_change_is_not_a_highlight():
    """A recording that gets louder and stays louder -- the game starting
    after a menu -- is not a moment. The baseline follows it."""
    hz = 20.0
    level = np.concatenate([
        np.full(int(120 * hz), -45.0, dtype=np.float32),
        np.full(int(120 * hz), -25.0, dtype=np.float32)])
    got = loudness.peaks(level, hz)
    assert len(got) <= 1, (
        f"a single step produced {len(got)} highlights: {got[:5]}")


# ================================ through the detector and the profile

def test_the_profile_needs_nothing_calibrated():
    """THE WHOLE POINT. Every other mode needs a template cut from real
    footage, or an in-game name, or a HUD colour measured on this PC. A game
    nobody has done any of that for had nothing at all on offer."""
    from autostream.clips import profiles

    p = profiles.load_all()[profiles.ANY_GAME]
    assert p.mode == "loudness"
    assert p.exists() is True
    assert p.why_not() == "", p.why_not()
    assert p.missing() == []


def test_it_is_offered_to_the_page_like_any_other_reader():
    from autostream.clips import profiles

    rows = {r["key"]: r for r in profiles.listing()}
    row = rows[profiles.ANY_GAME]
    assert row["ready"] is True
    assert row["mode"] == "loudness"
    assert row["builtin"] is True


def test_the_threshold_survives_a_round_trip_through_the_file():
    """It is the one number worth reaching for by hand, so it has to be in
    what the profile writes out."""
    from autostream.clips import profiles

    p = profiles.load_all()[profiles.ANY_GAME]
    out = p.as_dict()
    assert out["mode"] == "loudness"
    assert out["rise_db"] == 9.0
    again = profiles._build("x", {**out, "band": out["band"]})
    assert again is not None and again.rise_db == 9.0


def test_the_detector_returns_markers_the_rest_of_the_pipeline_can_use(ff,
                                                                       tmp_path):
    """`scan` is the one door into every reader, and everything downstream
    takes Kill objects. A mode that returned its own shape would need the
    cutter, the montage and the Studio page all taught about it."""
    from autostream.clips import detect, profiles

    src = tmp_path / "clip.mp4"
    audio = make_audio(ff, tmp_path / "a.m4a", 60.0, [20.0, 45.0])
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:d=60",
                    "-i", str(audio), "-shortest", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", str(src)],
                   check=True, capture_output=True, creationflags=NO_WINDOW,
                   timeout=600)

    prof = profiles.load_all()[profiles.ANY_GAME]
    got = detect.scan(src, prof)

    assert len(got) == 2, got
    for k in got:
        assert isinstance(k, detect.Kill)
        assert k.count == 1
        assert k.end > k.time, "a clip cut against `end` would be empty"
    assert near([(k.time, 0, 0) for k in got], 20.0)
    assert near([(k.time, 0, 0) for k in got], 45.0)


def test_a_window_into_the_file_reads_only_that_window(ff, tmp_path):
    """One recording routinely holds a menu, a warm-up and two matches, and
    reading the part that matters is the whole reason `start` exists."""
    from autostream.clips import detect, profiles

    src = tmp_path / "long.mp4"
    audio = make_audio(ff, tmp_path / "b.m4a", 120.0, [15.0, 90.0])
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:d=120",
                    "-i", str(audio), "-shortest", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", str(src)],
                   check=True, capture_output=True, creationflags=NO_WINDOW,
                   timeout=600)

    prof = profiles.load_all()[profiles.ANY_GAME]
    got = detect.scan(src, prof, start=60.0, duration=60.0)
    assert len(got) == 1, got
    assert abs(got[0].time - 90.0) < 2.0, got[0].time


def test_it_is_quoted_as_the_fastest_reader_there_is(ff, tmp_path):
    """It decodes no video at all. Measured on 600s of 720p30 h264 with AAC:
    0.17-0.19s, about 3,200x real time -- so a rate quoted anywhere near the
    frame readers' 4.5-16x would make the page's estimate nonsense."""
    from autostream.clips.jobs import SCAN_RATE, scan_rate

    assert scan_rate("loudness") >= 1000
    assert scan_rate("loudness") > max(
        v for k, v in SCAN_RATE.items() if k != "loudness") * 50
