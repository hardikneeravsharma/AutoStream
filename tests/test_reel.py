"""The reel builder: grid from the audio, arrangement from a template.

The numbers asserted here come from real edits a person watched and corrected,
not from taste. Where a claim is about a specific song it is stated as such --
those live in tests/verify/test_media.py, which has the audio; these are the
arithmetic and the rules, which must hold with no files at all.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import beatsync as bs, reel                 # noqa: E402


def a_shape(bpm=134.46, seconds=52.0, phase=0.4091, downbeat_pos=2,
            drop=18.25, drums=14.69) -> reel.Shape:
    beat = 60.0 / bpm
    return reel.Shape(
        path=Path("song.flac"), seconds=seconds, bpm=bpm, phase=phase,
        downbeat_pos=downbeat_pos, drop=drop, drums_in=drums,
        beats=[phase + i * beat for i in range(int((seconds - phase) / beat))])


def kills(n, first=100.0, gap=60.0):
    return [{"time": first + i * gap, "round": i + 1, "labels": []}
            for i in range(n)]


# ------------------------------------------------------------ the grid

def test_the_downbeat_is_found_from_the_kick():
    """Two clicks a bar apart in the low band, offset from beat zero: the
    position carrying them is the downbeat. On real tracks this matched a
    person's own marks 8 times out of 8."""
    sr, beat = bs.SR, 60.0 / 120.0
    x = np.zeros(int(20 * sr), dtype=np.float32)
    n = np.arange(600)
    thud = (np.exp(-n / 220.0) * np.sin(2 * np.pi * 55 * n / sr)).astype(np.float32)
    beats = [0.1 + i * beat for i in range(int(19 / beat))]
    for i, b in enumerate(beats):
        if i % 4 == 2:                       # the downbeat we plant
            j = int(b * sr)
            x[j:j + 600] += thud
    assert reel.downbeat_position(x, beats) == 2


def test_drums_arriving_is_found_and_silence_before_it_is_not():
    sr = bs.SR
    x = np.zeros(int(24 * sr), dtype=np.float32)
    n = np.arange(600)
    thud = (np.exp(-n / 220.0) * np.sin(2 * np.pi * 55 * n / sr)).astype(np.float32)
    bar = 2.0
    for i in range(12):
        t = 6.0 + i * bar                    # drums from 6s
        j = int(t * sr)
        if j + 600 < len(x):
            x[j:j + 600] += thud
    got = reel.drums_in(x, 0.0, bar)
    # PER-BAR RESOLUTION, because that is how it reads: it names the bar the
    # arrival falls in. A spectrogram frame straddling the boundary can put it
    # in the bar before, which is why this is a window and not a point.
    assert got is not None and 6.0 - bar <= got <= 6.0 + bar, got


def test_drums_already_playing_report_no_arrival():
    """Otherwise every kill is held back from a track that starts hot."""
    sr = bs.SR
    x = np.zeros(int(20 * sr), dtype=np.float32)
    n = np.arange(600)
    thud = (np.exp(-n / 220.0) * np.sin(2 * np.pi * 55 * n / sr)).astype(np.float32)
    for i in range(10):
        j = int(i * 2.0 * sr)
        x[j:j + 600] += thud
    assert reel.drums_in(x, 0.0, 2.0) is None


# ------------------------------------------------------- the arrangement

def test_the_default_template_is_one_a_bar_on_the_downbeat():
    """What a person reached for unprompted, 14 marks out of 18."""
    s = a_shape()
    got = layout = reel.layout(s, want=10, template="bar")
    idx = [s.index_of(t) for t in got]
    assert all(s.is_downbeat(i) for i in idx), idx
    assert all(b - a == 4 for a, b in zip(idx, idx[1:])), np.diff(idx).tolist()


def test_kills_do_not_start_before_the_drums():
    """The one structural decision the audio supports. Measured: a person's
    first mark sat 6 beats after the kick entered."""
    s = a_shape(drums=14.69)
    first = reel.layout(s, want=8, template="bar")[0]
    assert first >= 14.69, f"first kill at {first:.2f}s, before the drums"
    assert first <= 14.69 + 8 * s.beat, f"first kill at {first:.2f}s, too late"


def test_a_track_with_no_drum_arrival_starts_at_the_top():
    s = a_shape(drums=None)
    assert reel.layout(s, want=4, template="bar")[0] < 2.0


def test_the_layout_never_hands_back_more_slots_than_kills():
    s = a_shape()
    assert len(reel.layout(s, want=3, template="bar")) == 3
    assert len(reel.layout(s, want=99, template="half")) <= 99


def test_the_doubles_template_puts_a_second_hit_a_beat_later():
    s = a_shape()
    idx = [s.index_of(t) for t in reel.layout(s, want=12, template="pairs")]
    pairs = [(a, b) for a, b in zip(idx, idx[1:]) if b - a == 1]
    assert len(pairs) == 3, f"expected three doubles, got {pairs}"
    assert all(s.is_downbeat(a) for a, _ in pairs), "a double must open on the downbeat"


def test_the_run_in_arrives_at_the_drop():
    s = a_shape()
    got = reel.layout(s, want=12, template="runin")
    drop_i = s.index_of(s.drop)
    run = [s.index_of(t) for t in got if s.index_of(t) <= drop_i]
    assert run[-5:] == [drop_i - 5, drop_i - 4, drop_i - 3, drop_i - 2, drop_i - 1]


def test_every_template_lays_out_on_real_beats():
    s = a_shape()
    for key in reel.TEMPLATES:
        for t in reel.layout(s, want=10, template=key):
            i = s.index_of(t)
            assert abs(s.at(i) - t) < 1e-6, f"{key} produced an off-grid slot"


# --------------------------------------------------------------- the drift

def test_the_drift_fit_recovers_a_known_lag_and_slope():
    """The real measurement: mean -0.323s, 233 ppm. Fitted from 13 kills a
    person marked by eye, every error negative."""
    true = reel.Drift(intercept=-2.5634, slope=2.332e-4)
    pairs = [(t, true.intercept + true.slope * t)
             for t in (8770.0, 9300.0, 9800.0, 10330.0)]
    got = reel.Drift.fit(pairs)
    assert got.intercept == pytest.approx(true.intercept, abs=0.01)
    assert got.slope == pytest.approx(true.slope, rel=0.01)
    assert got.apply(9000.0) == pytest.approx(true.apply(9000.0), abs=0.001)


def test_no_drift_without_evidence():
    assert reel.Drift.fit([]).apply(500.0) == 500.0
    assert reel.Drift().apply(500.0) == 500.0


# ---------------------------------------------------------------- the shots

def test_the_pre_roll_comes_from_the_gap_before_the_beat():
    """Sized from the FOLLOWING gap, a 3s shot wanted 0.9s of run-up, reached
    back past the previous kill's beat, and left that shot 0.10s long with its
    own kill outside it."""
    assert reel.pre_roll(3.1) == pytest.approx(0.9, abs=0.01)
    assert reel.pre_roll(0.45) < 0.25
    assert reel.pre_roll(0.45) <= 0.45 - reel.MIN_AFTER + 1e-9


def test_a_kill_always_lands_inside_its_own_shot():
    s = a_shape()
    for key in reel.TEMPLATES:
        slots = reel.layout(s, want=12, template=key)
        for sh in reel.shots(slots, kills(len(slots)), total=52.0):
            assert sh.reel_in <= sh.kill_at <= sh.reel_in + sh.duration


def test_a_kill_outside_its_shot_is_refused_rather_than_rendered():
    """The arithmetic exists to prevent exactly this, and it happened once."""
    with pytest.raises(RuntimeError, match="kill"):
        reel.shots([10.0, 10.05], kills(2), total=20.0, opening=False)


def test_the_opening_shot_carries_the_run_up():
    """A template that starts late must produce a build-up, not a hard cut
    onto a kill in progress."""
    s = a_shape()
    slots = reel.layout(s, want=6, template="bar")
    first = reel.shots(slots, kills(6), total=52.0)[0]
    assert first.reel_in == pytest.approx(0.0, abs=1e-6)
    assert first.duration > 10.0


def test_the_last_shot_runs_to_the_end_so_the_fade_is_the_footage():
    s = a_shape()
    slots = reel.layout(s, want=6, template="bar")
    last = reel.shots(slots, kills(6), total=52.0)[-1]
    assert last.reel_in + last.duration == pytest.approx(52.0, abs=1e-6)


def test_the_drift_correction_reaches_the_source_times():
    s = a_shape()
    slots = reel.layout(s, want=4, template="bar")
    k = kills(4)
    plain = reel.shots(slots, k, total=52.0)
    moved = reel.shots(slots, k, total=52.0,
                       drift=reel.Drift(intercept=-0.5, slope=0.0))
    assert moved[1].source_in == pytest.approx(plain[1].source_in - 0.5, abs=1e-6)


# ----------------------------------------------------------------- the look

def test_nothing_in_the_render_changes_playback_speed():
    """A ramp into the impact is this style's signature and the one effect
    that cannot be used: slowing the run-up moves the kill off its beat."""
    s = a_shape()
    slots = reel.layout(s, want=5, template="bar")
    sh = reel.shots(slots, kills(5), total=52.0)
    argv = reel.command(Path("in.mp4"), Path("song.flac"), sh, Path("out.mp4"),
                        main=48.0, fade=4.0)
    graph = argv[argv.index("-filter_complex") + 1]
    video = ";".join(p for p in graph.split(";") if not p.startswith("[a")
                     and "a:" not in p.split("]")[0])
    for banned in (",setpts", "atempo", "minterpolate", "framerate="):
        assert banned not in video, f"{banned} would move the kills off the beat"
    # asetpts on the audio is fine and expected; a VIDEO setpts is not.
    assert "asetpts" in graph


def test_the_push_in_uses_zoompan_because_crop_cannot_zoom_over_time():
    """crop evaluates w and h once at configure time, where `t` does not exist:
    it can pan but not zoom. Getting this wrong failed the whole render."""
    s = a_shape()
    sh = reel.shots(reel.layout(s, want=3, template="bar"), kills(3), total=52.0)
    graph = reel.command(Path("i.mp4"), Path("s.flac"), sh, Path("o.mp4"),
                         main=48.0, fade=4.0)[
        reel.command(Path("i.mp4"), Path("s.flac"), sh, Path("o.mp4"),
                     main=48.0, fade=4.0).index("-filter_complex") + 1]
    assert "zoompan" in graph
    assert "crop=w=" not in graph


def test_the_music_is_ducked_and_the_mix_is_not_halved():
    """amix halves every input unless told otherwise, which is half of why an
    early attempt came out 8.7 dB quiet."""
    g = reel.audio_graph(3, main=48.0, total=52.0, fade=4.0)
    assert "sidechaincompress" in g
    assert "normalize=0" in g
    assert f"threshold={reel.DUCK['threshold']}" in g


def test_the_duck_threshold_sits_above_ambience():
    """At -27 dB it sat UNDER the game's own room tone, so footsteps held the
    duck open for the whole reel."""
    assert reel.DUCK["threshold"] >= 0.1


def test_the_fade_is_on_the_last_shot_not_a_separate_clip():
    s = a_shape()
    sh = reel.shots(reel.layout(s, want=4, template="bar"), kills(4), total=52.0)
    argv = reel.command(Path("i.mp4"), Path("s.flac"), sh, Path("o.mp4"),
                        main=48.0, fade=4.0)
    graph = argv[argv.index("-filter_complex") + 1]
    # ",fade=" is the video fade; the audio ones are ",afade=".
    assert graph.count(",fade=t=out") == 1
    last = graph.split(f"[v{len(sh) - 1}]")[0]
    assert ",fade=t=out" in last, "the fade is not on the final shot"


def test_one_input_per_shot_plus_the_song():
    s = a_shape()
    sh = reel.shots(reel.layout(s, want=6, template="bar"), kills(6), total=52.0)
    argv = reel.command(Path("i.mp4"), Path("s.flac"), sh, Path("o.mp4"),
                        main=48.0, fade=4.0)
    assert argv.count("-i") == len(sh) + 1


# ------------------------------------------------ effects, measured not guessed

def test_no_chromatic_aberration_is_added():
    """THE EFFECT EVERYONE ASSUMES IS THERE. Correlating red and blue against
    green on four impact frames of a real montage gave 0px misalignment every
    time -- it does not use an RGB split, so neither does this."""
    s = a_shape()
    sh = reel.shots(reel.layout(s, want=4, template="bar"), kills(4), total=52.0)
    argv = reel.command(Path("i.mp4"), Path("s.flac"), sh, Path("o.mp4"),
                        main=48.0, fade=4.0)
    graph = argv[argv.index("-filter_complex") + 1]
    for banned in ("rgbashift", "chromashift"):
        assert banned not in graph


def test_the_song_is_named_from_its_own_tags(tmp_path):
    """A missing tag must fall back to the filename rather than a blank card."""
    f = tmp_path / "some-track.flac"
    f.write_bytes(b"")
    got = reel.song_tags(f)
    assert got["title"] == "some-track"


def test_the_now_playing_card_escapes_what_drawtext_would_eat():
    """A colon or an apostrophe in a title breaks the whole filtergraph, and
    "Beggin'" has an apostrophe in it."""
    chain = reel.nowplaying_chain(Path("Artist - Song: It's Here.flac"), 1920, 1080)
    body = chain.split("text='", 1)[1].split("':fontcolor", 1)[0]
    assert ":" not in body.replace(r"\:", "")
    assert "'" not in body.replace(r"\'", "")


def test_the_card_fades_itself_out():
    chain = reel.nowplaying_chain(Path("x.flac"), 1920, 1080)
    assert "alpha=" in chain
    assert str(reel.NOWPLAYING_SECONDS + reel.NOWPLAYING_FROM) in chain


def test_a_single_match_reel_says_it_will_look_uniform():
    """Measured: hue spread 0.114 from one match against 0.623 in a montage
    drawing on many maps. The remedy is more sources, not more saturation."""
    s = a_shape()
    sh = reel.shots(reel.layout(s, want=4, template="bar"), kills(4), total=52.0)
    assert "one match" in reel.sources_note(sh)
    assert "grading cannot" in reel.sources_note(sh)


def test_nothing_is_said_when_there_is_only_one_shot():
    assert reel.sources_note([]) == ""


# ------------------------------------------------------------ the page flow

def _ui():
    from autostream.ui import reel as ui
    return ui


def test_the_flow_asks_in_the_order_that_narrows():
    """Each choice constrains the next: a song fixes the tempo, the part fixes
    how many slots exist, and only then does a template mean anything."""
    html = _ui().REEL_HTML
    order = [html.index(f'id="reel-step-{k}"')
             for k in ("song", "part", "kills", "shape", "plan")]
    assert order == sorted(order), "the steps are out of order in the markup"


def test_every_control_in_the_reel_card_has_a_handler():
    ui = _ui()
    import re
    acts = set(re.findall(r'data-act="(reel-[a-z]+)"', ui.REEL_HTML))
    handled = set(re.findall(r"act === '(reel-[a-z]+)'", ui.REEL_JS))
    assert not acts - handled, f"dead buttons: {sorted(acts - handled)}"


def test_the_page_never_invents_an_instant():
    """Every time comes back from /api/reel/song or from a tap snapped to it.
    A grid computed in the browser would drift from the one that cuts."""
    js = _ui().REEL_JS
    assert "/api/reel/song" in js
    assert "reel_snap" in js
    for invented in ("60 /", "bpm / 60", "* 0.4462"):
        assert invented not in js, f"the page is computing beats itself: {invented}"


def test_changing_the_part_drops_stale_taps():
    """The grid the taps were made against has moved, so keeping them would
    place kills on beats nobody chose."""
    js = _ui().REEL_JS
    body = js[js.index("function reel_rangeChanged"):]
    body = body[:body.index("function ", 10)]
    assert "marks = null" in body


def test_choosing_a_template_drops_hand_marks():
    """Two answers to one question; the marks were the deliberate one, so the
    template clears them rather than silently losing to them."""
    js = _ui().REEL_JS
    i = js.index("act === 'reel-tpl'")
    assert "marks = null" in js[i:i + 400]


def test_the_reel_view_is_in_the_bundle_after_the_shell():
    """All views share one scope and the shell declares what they call."""
    from autostream import ui
    assert "{{REEL_HTML}}" not in ui.BODY, "the placeholder was not substituted"
    assert 'id="reel-card"' in ui.BODY
    # The ASSIGNMENTS, not the first mention: clips.js names window.PAGE_REEL
    # in a handler ~100 lines before it assigns its own global, so a mention
    # proves nothing about which module ran first.
    assert ui.JS.index("window.PAGE_REEL = {") > ui.JS.index("window.PAGE_CLIPS = {")
    assert ui.JS.index("window.PAGE_CLIPS = {") > ui.JS.index("SHELL_ICONS")


def test_the_clips_view_only_reaches_for_the_reel_if_it_loaded():
    """One bundle, but the reel is the newest module in it; an unguarded call
    would take the whole Clips page down with it if that changes."""
    from autostream.ui import clips
    i = clips.CLIPS_JS.index("PAGE_REEL.open(")
    assert "if (window.PAGE_REEL)" in clips.CLIPS_JS[i - 80:i]


def test_the_song_route_serves_only_the_song_already_chosen():
    """It is picked through an OS dialog so it can be anywhere on disk, and
    serving an arbitrary path because a query string asked for it is how a
    local server becomes a file browser."""
    from autostream import webui
    src = Path(webui.__file__).read_text(encoding="utf-8")
    body = src[src.index("def _reel_audio"):]
    body = body[:body.index("def _media")]
    assert "_reel_cache" in body and "resolve()" in body
    assert "send_error(404" in body
