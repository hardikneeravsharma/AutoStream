"""Tests for the story arc and the spoken hook.

Both layers turn what a clip MEANT into how it is presented, and both fail
quietly when they are wrong: a reel whose drop lands on the wrong clip is a
perfectly valid video, and a hook that says "triple kill" over a 1v3 clutch is
a perfectly valid sentence. So the things pinned here are the ones that were
actually got wrong while building them, each with what went wrong in the
docstring.
"""
from __future__ import annotations

import pathlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autostream.clips import story, voice                    # noqa: E402
from autostream.clips.beatsync import Track                  # noqa: E402
from autostream.clips.plan import ClipPlan                   # noqa: E402

BPM = 128.0
BEAT = 60.0 / BPM


def track(duration: float = 180.0, drop: float | None = 64.0) -> Track:
    beats = [i * BEAT for i in range(int(duration / BEAT))]
    return Track(path=Path("t.mp3"), duration=duration, bpm=BPM, beats=beats,
                 drop=drop)


def clip(rank: int, start: float, kills: int = 1, labels=(), won=True) -> ClipPlan:
    return ClipPlan(rank=rank, start=start, end=start + 30.0, kills=kills,
                    burst_kills=kills, peak_score=0.0, name=f"c{rank}",
                    labels=list(labels), round_number=rank, won=won)


SESSION = [
    clip(1, 200, 2, ["PISTOL ROUND"]),
    clip(2, 300, 1, ["THROUGH SMOKE"]),
    clip(3, 420, 0, [], won=False),
    clip(4, 510, 0, [], won=False),
    clip(5, 580, 1, ["STREAK BREAKER"]),
    clip(6, 730, 2, []),
    clip(7, 900, 1, ["LAST ALIVE"]),
    clip(8, 1140, 3, ["CLUTCH 1v2"]),
    clip(9, 1550, 1, ["MATCH POINT"]),
]


# ------------------------------------------------------------------ the arc

def test_clips_are_never_reordered():
    """The whole point of the module.

    beatsync's flat layout moves the best clip into the drop's slot, which puts
    the end of the match in the middle of the reel. Here the clips stay put and
    the MUSIC is offset instead.
    """
    arc = story.arrange(SESSION, track())
    got = [s.plan.start for s in arc.slots]
    assert got == sorted(got)


def test_the_drop_lands_on_the_turn():
    arc = story.arrange(SESSION, track())
    assert arc.turn >= 0
    assert arc.drop_at == arc.turn
    turn = arc.slots[arc.turn]
    assert turn.start <= 64.0 < turn.start + turn.length


def test_the_turn_is_the_biggest_moment_not_the_streak_breaker():
    """Written the other way round first, on the reading that the arc is ABOUT
    the streak-breaker. It put the session's best clip -- a 1v2 clutch scoring
    10.5 against the breaker's 8.5 -- into a 0.9-second flash cut."""
    arc = story.arrange(SESSION, track())
    assert arc.slots[arc.turn].plan.labels == ["CLUTCH 1v2"]


def test_a_streak_breaker_wins_a_tie():
    plans = [clip(1, 100, 2, ["4 KILLS"]), clip(2, 200, 2, ["STREAK BREAKER"]),
             clip(3, 300, 1, [])]
    # 5 + 1 against 8 + 1: the breaker is the more intense of the two anyway,
    # so equalise them and check the tie-break rather than the ordering.
    assert story.intensity(plans[1]) > story.intensity(plans[0])
    tied = [clip(1, 100, 2, ["STREAK BREAKER"]), clip(2, 200, 2, ["STREAK BREAKER"])]
    arc = story.arrange(tied + [clip(3, 300, 1, [])], track())
    assert arc.slots[arc.turn].plan.start == 200.0      # the later of two


# Kills inside the peak clip of SESSION (a three-kill 1v2 that runs 11s),
# so the turn can be sized from its own sequence.
CLUTCH_KILLS = [{"time": 1146.0}, {"time": 1153.0}, {"time": 1157.0}]


def test_the_anchor_kill_lands_on_the_drop_and_never_after_it():
    """A beat a fraction after the kill reads as the music answering it.

    A beat a fraction BEFORE the kill reads as a mistake, which is what a
    viewer reported on the first reel that got this nearly right.
    """
    arc = story.arrange(SESSION, track(), kills=CLUTCH_KILLS)
    turn = arc.slots[arc.turn]
    at = turn.start + turn.pre
    assert at <= arc.drop, "the kill must not come after the drop"
    assert arc.drop - at == pytest.approx(story.TURN_BIAS, abs=0.01)
    # ...and it is the LAST kill of the clip. Anchoring on the first put the
    # drop on the defuse two seconds after the kill that won the round.
    assert turn.anchor == "last"


def test_the_turn_holds_the_whole_kill_sequence():
    """A fixed 16-beat turn cut the clip open two kills into a three-kill
    clutch: the kills spanned 11 seconds and the slot was 12 with the last kill
    at its end, so the first two were never in shot."""
    arc = story.arrange(SESSION, track(duration=400.0), kills=CLUTCH_KILLS)
    turn = arc.slots[arc.turn]
    span = CLUTCH_KILLS[-1]["time"] - CLUTCH_KILLS[0]["time"]
    assert turn.pre >= span, "the run-up has to reach the first kill"
    assert turn.length >= span + story.TURN_TAIL


def test_a_turn_with_one_kill_is_not_stretched_to_fit_a_sequence():
    plans = [clip(1, 100, 1, []), clip(2, 200, 1, ["ACE"])]
    arc = story.arrange(plans, track(), kills=[{"time": 205.0}])
    turn = arc.slots[arc.turn]
    assert turn.length <= story.TURN_MIN_BEATS * BEAT + 0.05


def test_the_turn_keeps_its_build_up_in_front_of_the_drop():
    """The drop lands well into the turn's slot, not at its start.

    Aiming the slot's start at the drop was the first version: the drop then
    coincides with the beginning of a clip rather than with anything in it.
    """
    arc = story.arrange(SESSION, track(duration=400.0), kills=CLUTCH_KILLS)
    turn = arc.slots[arc.turn]
    assert 0.35 < turn.pre / turn.length < 0.95


def test_a_short_slot_still_shows_its_busiest_kill():
    arc = story.arrange(SESSION, track())
    fast = [s for s in arc.slots
            if s.act != "turn" and s.length < 1.2 * BEAT * 2]
    assert fast and all(s.anchor == "busiest" for s in fast)


# ------------------------------------------------------------ the orderings

def test_build_order_escalates_and_ends_on_the_peak():
    arc = story.arrange(SESSION, track(), order="build")
    scores = [story.intensity(s.plan) for s in arc.slots]
    assert scores == sorted(scores)
    assert arc.turn == len(arc.slots) - 1


def test_hook_order_opens_on_the_best_moment():
    arc = story.arrange(SESSION, track(), order="hook", kills=CLUTCH_KILLS)
    assert arc.turn == 0
    assert arc.slots[0].plan.labels == ["CLUTCH 1v2"]
    # It still shows the whole sequence. An earlier version gave the hook a
    # deliberately tiny run-up so the payoff arrived immediately, and what that
    # produced was a clutch clip missing the first two of its three kills.
    span = CLUTCH_KILLS[-1]["time"] - CLUTCH_KILLS[0]["time"]
    assert arc.slots[0].pre >= span


def test_every_ordering_still_puts_the_drop_on_the_turn():
    for order in story.ORDERS:
        arc = story.arrange(SESSION, track(duration=400.0), order=order,
                            kills=CLUTCH_KILLS)
        turn = arc.slots[arc.turn]
        at = turn.start + turn.pre
        assert at <= arc.drop, order
        assert arc.drop - at == pytest.approx(story.TURN_BIAS, abs=0.01), order
        assert arc.order == order


def test_a_long_slot_lands_its_kill_on_a_beat_as_well_as_its_cut():
    """Both, where there is room for both.

    A slot always starts on a beat, so rounding the run-up to whole beats puts
    the kill on the grid too -- twice the beats used, for nothing.
    """
    t = track()
    arc = story.arrange(SESSION, t, kills=CLUTCH_KILLS)
    long_slots = [s for s in arc.slots
                  if s.act not in ("turn",)
                  and round(s.length / BEAT) >= story.QUANTISE_MIN_BEATS]
    assert long_slots
    for s in long_slots:
        at = s.start + s.pre
        assert min(abs(b - at) for b in t.beats) < 0.01, s.act


def test_short_slots_keep_a_natural_lead():
    """Landing every cut AND every kill on the grid is mechanical: the reel
    stops feeling edited to the music and starts feeling generated by it."""
    t = track()
    arc = story.arrange(SESSION, t, kills=CLUTCH_KILLS)
    short = [s for s in arc.slots
             if round(s.length / BEAT) <= story.FAST_BEATS]
    assert short
    for s in short:
        at = s.start + s.pre
        assert min(abs(b - at) for b in t.beats) > 0.01


def test_an_unknown_ordering_falls_back_to_the_story():
    assert story.arrange(SESSION, track(), order="nonsense").order == "story"


def test_every_act_change_lands_on_a_phrase_boundary():
    """An act starting three beats into a four-beat phrase sounds wrong even
    when every cut is on a beat."""
    arc = story.arrange(SESSION, track())
    at = 0
    for i, s in enumerate(arc.slots):
        beats = round(s.length / BEAT)
        if i and arc.slots[i - 1].act != s.act:
            assert at % story.PHRASE == 0, f"act {s.act} starts off-phrase"
        at += beats


def test_the_run_into_the_turn_accelerates():
    """Acceleration lives in whichever act leads into the turn.

    A session whose best moment is the second-to-last round has a long slide
    and no push at all, and it should still speed up on the way in -- which the
    first version did not, because the ramp was written only for the push.
    """
    # Stated as first-versus-last rather than half-versus-half: the run into
    # the turn can be three clips long, and splitting three in two says more
    # about the rounding than about the pacing.
    arc = story.arrange(SESSION, track())
    before = [s for s in arc.slots[:arc.turn] if s.act == "slide"]
    assert len(before) >= 3
    assert before[-1].length < before[0].length

    plain = [clip(i, 100 * i, 1, []) for i in range(1, 5)]
    plain.append(clip(9, 900, 5, ["ACE"]))
    run = [s for s in story.arrange(plain, track()).slots if s.act == "slide"]
    assert run[-1].length < run[0].length


def test_a_lost_round_in_the_slide_is_compressed():
    lost = [s for s in story.arrange(SESSION, track()).slots
            if s.act == "slide" and s.plan.won is False]
    assert lost and all(s.length <= story.SLIDE_LOST * BEAT + 0.02
                        for s in lost)


def test_a_big_moment_is_never_flash_cut_by_the_ramp():
    """Intensity matching. Without it a 1v2 clutch that happened to fall late
    in a run got 0.9 seconds -- the one clip nobody would cut that way."""
    plans = [clip(1, 100, 1, []), clip(2, 200, 1, []),
             clip(3, 300, 2, ["CLUTCH 1v3"]), clip(4, 400, 1, []),
             clip(5, 500, 5, ["ACE"]), clip(6, 600, 1, [])]
    arc = story.arrange(plans, track())
    got = next(s for s in arc.slots if "CLUTCH 1v3" in s.plan.labels)
    assert got.length >= story.PHRASE * BEAT - 0.02


def test_the_last_clip_always_lands_the_reel():
    arc = story.arrange(SESSION, track())
    assert arc.slots[-1].act == "close"
    assert arc.slots[-1].length >= story.PHRASE * BEAT


def test_a_track_with_no_drop_starts_at_the_beginning():
    # Not a failure worth special-casing away: an arc with nothing to build to
    # is a clip on a beat grid.
    arc = story.arrange(SESSION, track(drop=None))
    assert arc.start_beat == 0
    assert arc.slots and arc.slots[0].start == pytest.approx(0.0)


def test_more_clips_than_music_drops_the_slide_and_says_so():
    """Silent truncation reads as "covered everything" when it did not."""
    many = [clip(i, 100 * i, 1, []) for i in range(1, 12)]
    many.append(clip(99, 2000, 5, ["ACE"]))
    arc = story.arrange(many, track(duration=20.0, drop=12.0))
    assert arc.dropped
    assert all(s.act != "turn" for s in arc.dropped if hasattr(s, "act"))
    # ...and what is left is still in order and still ends on the peak or after.
    got = [s.plan.start for s in arc.slots]
    assert got == sorted(got)


def test_one_clip_is_not_an_arc_and_does_not_crash():
    arc = story.arrange([clip(1, 100, 3, ["ACE"])], track())
    assert len(arc.slots) == 1
    assert arc.slots[0].act == "turn"


def test_intensity_ranks_a_clutch_over_a_bigger_quiet_round():
    quiet = clip(1, 100, 4, ["4 KILLS"])
    clutch = clip(2, 200, 2, ["CLUTCH 1v3"])
    assert story.intensity(clutch) > story.intensity(quiet)


# --------------------------------------------------------- the spoken hook

def test_a_hook_is_not_the_label_read_aloud():
    """The complaint that caused the rewrite.

    "Anubis. One versus two." is a caption with a full stop in it: it states
    what the clip contains, to someone who is about to watch it contain that.
    A hook has to give a reason to stay.
    """
    said = voice.line_for(clip(1, 0, 3, ["CLUTCH 1v2"]))
    assert said
    assert "versus" not in said.lower()
    assert "anubis" not in said.lower()
    # a setup and a turn, in a person's voice -- not a statistic
    assert len(said.split()) >= 4


def test_the_situation_chooses_the_pool():
    smoke = voice.line_for(clip(1, 0, 1, ["THROUGH SMOKE"]))
    clutch = voice.line_for(clip(2, 0, 3, ["CLUTCH 1v3"]))
    assert smoke in [voice._speakable(x) for x in voice._pool(
        clip(1, 0, 1, ["THROUGH SMOKE"]))]
    assert smoke != clutch


def test_numbers_inside_a_line_are_spelled_out():
    """A model reading "1v3" says "one vee three"."""
    lines = [voice._speakable(x)
             for x in voice._pool(clip(1, 0, 2, ["CLUTCH 1v3"]))]
    assert any("three" in x for x in lines)
    assert not any("1v3" in x for x in lines)


def test_the_strongest_label_chooses_what_is_said():
    plan = clip(1, 0, 5, ["ACE", "CLUTCH 1v2", "THROUGH SMOKE"])
    assert voice.line_for(plan) in [voice._speakable(x)
                                    for x in voice._pool(clip(1, 0, 5, ["ACE"]))]


def test_a_clip_with_nothing_to_say_stays_silent():
    # "Check this out" over an ordinary single kill is worse than nothing.
    assert voice.line_for(clip(1, 0, 1, [])) == ""


def test_a_burst_with_no_labels_still_gets_a_line():
    # Delta Force and Valorant come through here: no round layer, so the burst
    # is the whole story.
    assert voice.line_for(clip(1, 0, 3, [])) != ""
    assert voice.line_for(clip(1, 0, 5, [])) != ""


def test_the_same_clip_says_the_same_thing_every_run():
    # Re-cutting a session at a different length must not quietly reword it.
    a = voice.line_for(clip(1, 412.0, 3, ["CLUTCH 1v2"]))
    b = voice.line_for(clip(1, 412.0, 3, ["CLUTCH 1v2"]))
    assert a == b


def test_two_clutches_in_one_session_do_not_say_the_same_sentence():
    """`avoid` compares FINISHED lines.

    Comparing raw pool lines against already-spoken capitalised ones matched
    nothing, so avoid did nothing at all and three clutches opened identically.
    """
    said = []
    for start in (100.0, 200.0, 300.0, 400.0):
        line = voice.line_for(clip(1, start, 3, ["CLUTCH 1v2"]), avoid=said)
        assert line not in said
        said.append(line)
    assert len(set(said)) == 4


def test_every_sentence_in_a_line_is_capitalised():
    """Kokoro reads case as prosody.

    A lowercase sentence after a full stop is delivered as a continuation of
    the one before it -- the flat run-on these two-clause hooks exist to avoid.
    """
    said = voice._speakable("shot into the smoke on a guess. it landed.")
    assert said == "Shot into the smoke on a guess. It landed."


def test_every_shipped_line_is_a_real_sentence():
    for _pattern, pool in voice.HOOKS:
        for line in pool:
            assert line == line.strip() and line
            assert line[-1] in ".!?", line
    for pool in voice.BURSTS.values():
        for line in pool:
            assert line[-1] in ".!?", line


def test_a_missing_model_is_reported_rather_than_guessed(tmp_path,
                                                         monkeypatch):
    monkeypatch.setattr(voice, "MODEL_DIR", tmp_path / "nope")
    assert not voice.available()
    assert "optional download" in voice.why_not()


def test_narration_never_costs_the_clip(tmp_path, monkeypatch):
    """A hook is not worth losing a clip over.

    Returns the empty string and leaves the file exactly as it was.
    """
    monkeypatch.setattr(voice, "MODEL_DIR", tmp_path / "nope")
    target = tmp_path / "clip.mp4"
    target.write_bytes(b"not really a video")
    assert voice.narrate(target, clip(1, 0, 5, ["ACE"])) == ""
    assert target.read_bytes() == b"not really a video"


# ------------------------------------------------------- the burned caption

def test_the_caption_says_what_the_clip_was_not_what_it_counted():
    """The bug: a 1v2 clutch containing three kills was captioned
    "TRIPLE KILL" -- true about the kill count, wrong about the clip."""
    from autostream.clips import overlay

    plan = clip(1, 0, 3, ["CLUTCH 1v2"])
    kills = [{"time": 1.0}, {"time": 2.0}, {"time": 3.0}]
    assert overlay.caption_for(plan, kills) == "1v2 CLUTCH"


def test_a_clip_with_no_labels_still_counts_its_kills():
    from autostream.clips import overlay

    plan = clip(1, 0, 3, [])
    kills = [{"time": 1.0}, {"time": 2.0}, {"time": 3.0}]
    assert overlay.caption_for(plan, kills) == "TRIPLE KILL"


def test_spelling_stops_being_words_past_what_a_round_can_hold():
    assert voice.spell(3) == "three"
    assert voice.spell(23) == "23"


# ------------------------------------------------- the caption and the subtitle

def _graph(caption="1v2 CLUTCH", sub=None, until=0.0, seconds=None):
    from autostream.clips import overlay

    kw = {} if seconds is None else {"caption_seconds": seconds}
    return overlay.build_filter(1080, 1920, caption, "@YuvaNeta", None, 72,
                                sub_file=sub, sub_until=until, **kw)[0]


def test_the_caption_stays_up_for_the_whole_clip():
    """It used to vanish after 2.6 seconds.

    A Short is watched on a loop and scrubbed into halfway through, and a
    viewer arriving at second eight then has nothing telling them what they
    are looking at. It sits in the blurred bar above the picture, so leaving it
    up costs no gameplay.
    """
    graph = _graph()
    assert "1v2 CLUTCH" in graph
    assert "enable=" not in graph


def test_a_caption_can_still_be_time_gated():
    assert "enable='lt(t,2.6)'" in _graph(seconds=2.6)


def test_the_subtitle_is_drawn_only_when_there_is_a_line_to_draw():
    assert "textfile" not in _graph()
    assert "textfile" not in _graph(sub=pathlib.Path("x.txt"), until=0.0)
    assert "textfile" in _graph(sub=pathlib.Path("x.txt"), until=2.4)


def test_the_subtitle_fades_out_after_the_voice_stops():
    from autostream.clips import overlay

    graph = _graph(sub=pathlib.Path("x.txt"), until=2.4)
    assert "alpha=" in graph
    # It holds past the end of the speech, then fades -- a subtitle still
    # sitting there in silence is just a second caption.
    ends = 2.4 + overlay.SUB_HOLD
    assert f"lt(t,{ends:.2f})" in graph
    assert f"enable='lt(t,{ends + overlay.SUB_FADE_OUT:.2f})'" in graph


def test_the_subtitle_clears_the_picture_and_the_branding():
    from autostream.clips import overlay

    # In a "fit" vertical the gameplay occupies roughly the middle third; the
    # subtitle goes in the blurred space under it, above the handle.
    assert 0.68 < overlay.SUB_Y < overlay.BRAND_Y


def test_a_long_hook_is_wrapped_rather_than_run_off_the_frame():
    from autostream.clips import overlay

    got = overlay._wrap("Two of them left, and they still lost it.")
    lines = got.split("\n")
    assert len(lines) == 2
    assert all(len(l) <= overlay.SUB_WRAP for l in lines)
    assert " ".join(lines) == "Two of them left, and they still lost it."


def test_no_shipped_hook_needs_a_third_line():
    """Three lines would push the subtitle into the branding.

    The box sits at 0.715 of frame height and the handle at 0.855, which is
    room for two lines of 57px and their padding and nothing more.
    """
    from autostream.clips import overlay

    lines = [l.replace("{n}", "three").replace("{s}", "five")
             for _p, pool in voice.HOOKS for l in pool]
    lines += [l for pool in voice.BURSTS.values() for l in pool]
    for line in lines:
        wrapped = overlay._wrap(voice._speakable(line))
        assert len(wrapped.split(chr(10))) <= 2, line


def test_a_short_hook_is_left_on_one_line():
    from autostream.clips import overlay

    assert "\n" not in overlay._wrap("Match point.")


def test_mixing_the_voice_in_copies_the_video(monkeypatch, tmp_path):
    """The overlay pass has already encoded the clip.

    Re-encoding here cost every narrated clip a second full video pass for a
    filtergraph that only touches audio.
    """
    from autostream.clips import tools, voice

    seen = {}
    monkeypatch.setattr(tools, "ffmpeg", lambda *a: seen.setdefault("args", a))
    monkeypatch.setattr(tools, "media_info", lambda p: {"audio_tracks": 1})
    voice.mix(tmp_path / "in.mp4", tmp_path / "out.mp4", tmp_path / "hook.wav")
    args = seen["args"]
    assert "-c:v" in args and args[args.index("-c:v") + 1] == "copy"


def test_the_sidechain_is_padded_so_the_clip_keeps_its_length(monkeypatch,
                                                              tmp_path):
    """sidechaincompress ends with its SHORTER input.

    An unpadded two-second hook cut a fifteen-second clip down to two seconds
    of video, and produced a perfectly valid file doing it.
    """
    from autostream.clips import tools, voice

    seen = {}
    monkeypatch.setattr(tools, "ffmpeg", lambda *a: seen.setdefault("args", a))
    monkeypatch.setattr(tools, "media_info", lambda p: {"audio_tracks": 1})
    voice.mix(tmp_path / "in.mp4", tmp_path / "out.mp4", tmp_path / "hook.wav")
    graph = next(a for a in seen["args"] if "sidechaincompress" in a)
    assert "apad" in graph


# ---------------------------------------------------------------- the voices

def test_the_voice_catalogue_is_read_off_the_model(monkeypatch):
    """Not hardcoded, so it says what is installed rather than what was true
    when this was written."""
    monkeypatch.setattr(voice, "voices",
                        lambda: ["am_michael", "af_heart", "bm_george",
                                 "jf_alpha", "zm_yunxi"])
    got = voice.catalogue()
    assert got["American male"] == ["am_michael"]
    assert got["British male"] == ["bm_george"]
    # Non-English voices are left out: LANG is en-us, and handing an American
    # phonemisation to a Japanese voice produces an accent nobody asked for.
    assert not any("jf_alpha" in v for v in got.values())


def test_the_clips_speak_with_a_male_voice_by_default():
    assert voice.VOICE.startswith(("am_", "bm_"))


def test_the_subtitle_file_is_written_with_unix_newlines(tmp_path,
                                                         monkeypatch):
    """Python writes \r\n on Windows and drawtext renders the carriage
    return as a line of its own, so a two-line hook came out double-spaced with
    a blank line through the middle of the box -- while a one-line hook looked
    perfect, which is why it survived a first look at the output."""
    from autostream.clips import overlay, tools

    written = {}

    def fake_ffmpeg(*args):
        sub = next(a for a in args if "textfile" in str(a))
        path = sub.split("textfile='")[1].split("'")[0]
        path = path.replace(chr(92) + ":", ":")
        written["bytes"] = pathlib.Path(path).read_bytes()

    # overlay imports ffmpeg at module level, so that is where it has to
    # be replaced -- patching tools.ffmpeg leaves the bound name alone.
    monkeypatch.setattr(overlay, "ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(tools, "media_info",
                        lambda p: {"width": 1080, "height": 1920})
    monkeypatch.setattr(overlay, "brand_logo", lambda: None)
    overlay.apply(tmp_path / "in.mp4", tmp_path / "out.mp4",
                  caption="1v2 CLUTCH",
                  subtitle="Two of them left, and they still lost it.",
                  subtitle_until=2.4)
    assert b"\r" not in written["bytes"]
    assert written["bytes"].count(b"\n") == 1


def test_the_subtitle_file_is_cleaned_up(tmp_path, monkeypatch):
    from autostream.clips import overlay, tools

    monkeypatch.setattr(overlay, "ffmpeg", lambda *a: None)
    monkeypatch.setattr(tools, "media_info",
                        lambda p: {"width": 1080, "height": 1920})
    monkeypatch.setattr(overlay, "brand_logo", lambda: None)
    out = tmp_path / "out.mp4"
    overlay.apply(tmp_path / "in.mp4", out, caption="ACE",
                  subtitle="Nobody was getting out of that one.",
                  subtitle_until=2.0)
    assert not list(tmp_path.glob("*.sub.txt"))


def test_a_burst_pool_outlasts_a_session():
    """One Valorant recording produced seven two-kill clips.

    With two lines in the pool, `avoid` ran out after the second and the same
    sentence opened four of them. A pool has to hold more lines than a session
    plausibly has clips of that size.
    """
    said = []
    for i in range(6):
        line = voice.line_for(clip(i + 1, 100.0 * (i + 1), 2, []), avoid=said)
        assert line and line not in said, f"repeated after {i} clips"
        said.append(line)


def test_the_promo_fills_the_length_it_asks_for():
    """A run-up floor with no ceiling pinned every single-kill piece to
    PROMO_PRE + PROMO_TAIL, so a reel documented at 30-40s delivered 15."""
    from autostream.clips import promo

    per = promo.piece_length(7)
    kill = 100.0
    first = kill
    end = kill + promo.PROMO_TAIL
    start = min(max(end - per, first - promo.PROMO_PRE_MAX),
                first - promo.PROMO_PRE)
    assert end - start >= per - 0.2, "the piece should reach the target length"
    assert first - start <= promo.PROMO_PRE_MAX + 0.01
    assert first - start >= promo.PROMO_PRE - 0.01


def test_the_promo_takes_what_fell_below_the_minimum():
    from autostream.clips import promo

    plans = [clip(1, 10, 1, []), clip(2, 20, 2, []), clip(3, 30, 3, [])]
    assert [p.kills for p in promo.pick(plans, 2)] == [1]
    assert [p.kills for p in promo.pick(plans, 3)] == [1, 2]


def test_a_promo_never_holds_more_clips_than_it_has_seconds_for():
    """FROM FOOTAGE: a 13-clip reel came out at 29s -- 2.2s a cut, with the
    kills chopped mid-action. Length is shared between the pieces, so past a
    point the target can only be met by cutting below what is watchable."""
    from autostream.clips import promo

    assert promo.MAX_CLIPS * promo.MIN_PIECE <= promo.TARGET_MAX + 0.01
    assert promo.piece_length(promo.MAX_CLIPS) >= promo.MIN_PIECE
    assert promo.piece_length(13) >= promo.MIN_PIECE


def test_a_promo_piece_is_long_enough_to_hold_its_kill():
    from autostream.clips import promo

    assert promo.MIN_PIECE >= promo.PROMO_PRE + promo.PROMO_TAIL


def test_the_extra_leftovers_dropped_from_a_promo_are_the_weakest():
    from autostream.clips import promo

    plans = [clip(i, 10.0 * i, 1, []) for i in range(1, 15)]
    for i, p in enumerate(plans):
        p.peak_score = float(i)              # last is strongest
    kept = promo.strongest(plans, promo.MAX_CLIPS)
    assert len(kept) == promo.MAX_CLIPS
    assert plans[-1] in kept and plans[0] not in kept


def test_a_short_promo_keeps_every_leftover():
    from autostream.clips import promo

    plans = [clip(i, 10.0 * i, 1, []) for i in range(1, 5)]
    assert promo.strongest(plans, promo.MAX_CLIPS) == plans
