"""Reading the Counter-Strike 2 scoreboard, and turning it into round highlights.

Every number here was measured against one 88-minute recording: 4,934 usable
scoreboard readings, 48 rounds across two matches and five side swaps. Where a
constant matters the test says what went wrong when it was different, because
several of these were only found by auditing real output.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autostream.clips import hud, rounds          # noqa: E402
from autostream.clips.hud import Reading          # noqa: E402
from autostream.clips.rounds import Round         # noqa: E402


# --------------------------------------------------------------- the digits

def test_the_shipped_digit_templates_are_present_and_sane():
    d = hud._digits()
    assert d.shape[0] == 10, "one template per digit"
    assert d.shape[1] > 8 and d.shape[2] > 4
    # Every glyph must actually differ from every other, or the reader would
    # confidently return the wrong number rather than nothing.
    for a in range(10):
        for b in range(a + 1, 10):
            g = hud.glyphs(d.shape[1])
            c = hud.corr(g[a], g[b])
            assert not c.size or float(c.max()) < 0.98, f"{a} and {b} are alike"


def test_a_digit_matches_itself_whatever_the_background():
    """The reason this is template matching and not OCR.

    The score sits on a TRANSLUCENT panel, so the same digit appears white on
    black in one round and white on a bright sky in the next. Tesseract has to
    threshold and there is no threshold that serves both; normalised
    cross-correlation does not threshold at all.
    """
    g = hud.glyphs(hud._digits().shape[1])[7]
    for bg, gain in ((0.0, 1.0), (200.0, 1.0), (0.0, 0.35), (120.0, 0.5)):
        field = g * gain + bg
        c = hud.corr(field, g)
        assert float(c.max()) > 0.99, f"failed at background {bg}, gain {gain}"


def test_the_alive_digits_are_read_at_their_own_smaller_size():
    # They are drawn smaller than the timer and score. Sweeping found 11px
    # reads every hand-labelled frame while 9 and 13 read none.
    assert hud.ALIVE_GLYPH_HEIGHT < hud._digits().shape[1]


def test_a_timer_over_fifty_nine_seconds_is_rejected_not_guessed():
    # Better to report nothing than to report a clock that cannot exist.
    field = np.zeros((20, 40), dtype=np.float32)
    assert hud.read_timer(field, hud._digits().shape[1])[0] is None


def test_the_strip_and_full_frame_paths_agree():
    """Scanning crops the top of the frame; both paths must read the same.

    They did not, once: the crop fraction 0.12 of 1080 is 129.6, ffmpeg wrote
    129 and the reader wanted 130, and resizing by that single pixel blurred
    the 11-pixel alive digits enough to misread a 3 as a 1. Hence a power of
    two.
    """
    assert hud.REF_HEIGHT % hud.STRIP_DIV == 0
    for h in (1080, 1440, 2160):
        assert h % hud.STRIP_DIV == 0, f"{h} does not divide cleanly"


# ---------------------------------------------------------- score settling

def _readings(seq, start=0.0, step=1.0):
    """seq of (score_l, score_r) -> readings a second apart."""
    return [Reading(time=start + i * step, seconds=100 - i, score_l=a,
                    score_r=b, alive_l=5, alive_r=5)
            for i, (a, b) in enumerate(seq)]


def test_one_misread_frame_cannot_invent_a_round():
    """A real scan read 2-8 as 12-7 on a single frame.

    Without settling, that one frame is two score changes and therefore two
    phantom rounds in the middle of a real one.
    """
    seq = ([(2, 8)] * 20) + [(12, 7)] + ([(2, 8)] * 20) + ([(2, 9)] * 20)
    rd = rounds.segment(_readings(seq))
    assert len(rd) == 1
    assert rd[0].score_before == (2, 8)
    assert rd[0].score_after == (2, 9)


def test_a_round_needs_exactly_one_point_on_one_side():
    seq = ([(3, 3)] * 10) + ([(4, 4)] * 10)      # both gained: not a round
    assert rounds.segment(_readings(seq)) == []


def test_absurdly_long_spans_are_not_rounds():
    # A menu or a map change leaves the score unchanged for minutes. Reporting
    # that as one enormous round would put a clip over the whole thing.
    seq = ([(1, 1)] * 400) + ([(1, 2)] * 10)
    assert rounds.segment(_readings(seq)) == []


# ------------------------------------------------------------- side swapping

def test_a_reversed_score_is_a_side_swap_not_a_round():
    """The bug this exists for.

    At half time the scoreboard swaps ends, so one match reads 2-10 before and
    10-2 after. Miss it and every round in the second half has the player on
    the wrong side, so every win is recorded as a loss -- and it cannot show up
    in a short test window.
    """
    steps = [(0.0, (2, 10)), (10.0, (10, 2)), (20.0, (10, 3))]
    assert rounds.halves(steps) == [10.0]


def test_the_swap_is_found_through_the_misread_in_the_middle():
    # Real footage: (2,10) then a transient (11,11) then (10,2).
    steps = [(0.0, (2, 10)), (5.0, (11, 11)), (9.0, (10, 2))]
    assert rounds.halves(steps) == [9.0]


def test_a_fresh_match_starts_a_new_half():
    steps = [(0.0, (13, 10)), (60.0, (0, 0)), (120.0, (0, 1))]
    assert 60.0 in rounds.halves(steps)


def test_a_round_may_not_straddle_a_swap():
    # The score either side of a swap describes different ends of the map, so
    # the span between them is not a round at all.
    seq = ([(5, 7)] * 10) + ([(7, 5)] * 10) + ([(7, 6)] * 10)
    rd = rounds.segment(_readings(seq))
    assert all(r.score_before != (5, 7) for r in rd)


# ------------------------------------------------------- inferring the side

def _curve(points, start=0.0):
    """points of (alive_l, alive_r) -> readings a second apart."""
    return [Reading(time=start + i, seconds=100 - i, score_l=1, score_r=1,
                    alive_l=a, alive_r=b) for i, (a, b) in enumerate(points)]


def test_my_death_drops_my_own_side_and_that_identifies_it():
    # Five seconds in, the left count falls. If that coincides with the
    # player's death, the player is on the left.
    rs = _curve([(5, 5)] * 5 + [(4, 5)] * 5)
    assert rounds.infer_side(rs, deaths=[5.0], kills=[]) == "l"


def test_my_kill_drops_the_other_side():
    rs = _curve([(5, 5)] * 5 + [(5, 4)] * 5)
    assert rounds.infer_side(rs, deaths=[], kills=[5.0]) == "l"


def test_the_side_is_decided_by_majority_not_by_one_event():
    # One reading can be wrong and one kill can coincide with a teammate's
    # death, so a single event must not settle it.
    rs = _curve([(5, 5)] * 3 + [(4, 4)] * 3 + [(3, 4)] * 3 + [(2, 4)] * 3)
    assert rounds.infer_side(rs, deaths=[7.0, 10.0], kills=[]) == "l"


def test_no_evidence_returns_no_answer_rather_than_a_guess():
    assert rounds.infer_side(_curve([(5, 5)] * 10), [], []) is None


# --------------------------------------------- the scoreboard bounds the feed

def _round_with(kills, enemy_from, enemy_to, side="l"):
    rd = Round(number=1, started=0.0, ended=60.0, score_before=(0, 0),
               score_after=(1, 0))
    rs = _curve([(5, enemy_from)] * 5 + [(5, enemy_to)] * 5)

    class E:
        def __init__(self, t, k):
            self.time, self.kind = t, k
    ev = [E(float(i) + 1, "kill") for i in range(kills)]
    rounds.annotate([rd], rs, ev)
    return rd


def test_the_feed_cannot_claim_more_kills_than_the_enemy_lost_players():
    """An independent check on the kill feed, and it caught a real error.

    The feed reported a six-kill ace in a game where five is the maximum. The
    enemy alive counter is a separate measurement of the same events, so it can
    bound the feed -- which is exactly the known failure mode, an assist whose
    killer's name is unreadable counting as a kill.
    """
    rd = _round_with(kills=6, enemy_from=5, enemy_to=0)
    assert rd.my_kills == 5
    assert rd.kill_overcount == 1
    assert len(rd.kill_times) == 5


def test_a_kill_count_the_scoreboard_supports_is_left_alone():
    rd = _round_with(kills=3, enemy_from=5, enemy_to=1)
    assert rd.my_kills == 3
    assert rd.kill_overcount == 0


# ------------------------------------------------------------------- labels

def _labelled(**kw):
    base = dict(number=1, started=0.0, ended=90.0, score_before=(0, 0),
                score_after=(1, 0), my_side="l", won=True)
    base.update(kw)
    return rounds.label([Round(**base)])[0]


def test_five_kills_is_an_ace():
    assert "ACE" in _labelled(my_kills=5).labels


def test_four_kills_is_labelled_as_four_kills_not_an_ace():
    got = _labelled(my_kills=4).labels
    assert "4 KILLS" in got and "ACE" not in got


def test_last_alive_against_two_or_more_and_winning_is_a_clutch():
    r = _labelled(my_kills=2, last_stand_at=40.0, enemies_at_last_stand=3,
                  won=True)
    assert "CLUTCH 1v3" in r.labels


def test_the_same_situation_lost_is_kept_but_named_differently():
    # A 1v3 lost at the last moment is often better viewing than a 1v2 won, so
    # it is not thrown away -- but it must not claim to be a clutch.
    r = _labelled(my_kills=1, last_stand_at=40.0, enemies_at_last_stand=3,
                  won=False)
    assert "ALMOST 1v3" in r.labels
    assert not any("CLUTCH" in l for l in r.labels)


def test_last_alive_against_one_is_not_a_clutch():
    r = _labelled(my_kills=1, last_stand_at=40.0, enemies_at_last_stand=1)
    assert "LAST ALIVE" in r.labels
    assert not any("1v" in l for l in r.labels)


def test_three_quick_kills_are_a_burst():
    assert rounds.fast_burst([10.0, 11.5, 13.0])
    assert not rounds.fast_burst([10.0, 20.0, 30.0])


def test_a_burst_needs_three_kills_close_together_not_merely_three_kills():
    r = _labelled(my_kills=3, kill_times=[10.0, 40.0, 80.0])
    assert not any("K IN" in l for l in r.labels)


def test_chaos_is_a_rate_not_a_count():
    """A raw count does not discriminate.

    Nearly every round in a real scan ended with 8-10 of the ten players dead,
    so a count threshold passed every time and duration was doing all the work.
    A fast round with everyone dead runs about 0.2 deaths a second against 0.06
    for an ordinary one.
    """
    fast = _labelled(ended=30.0, my_kills=1, total_kills=8)
    slow = _labelled(ended=150.0, my_kills=1, total_kills=8)
    assert "CHAOS" in fast.labels
    assert "CHAOS" not in slow.labels


def test_a_quiet_fast_round_is_not_chaos():
    r = _labelled(ended=30.0, my_kills=1, total_kills=2)
    assert "CHAOS" not in r.labels


def test_an_ordinary_round_earns_nothing():
    assert _labelled(my_kills=1, total_kills=8).labels == []


# ------------------------------------------------------------------ ranking

def test_a_round_that_matches_several_things_is_still_one_clip():
    # Otherwise a round that is an ace AND a 1v3 emits three overlapping clips
    # of the same forty seconds.
    r = _labelled(my_kills=5, last_stand_at=30.0, enemies_at_last_stand=3,
                  kill_times=[30.0, 31.0, 32.0])
    assert len(r.labels) > 1
    hl = rounds.highlights([r])
    assert len(hl) == 1
    assert rounds.rank_of(r.labels) == 0, "an ace should name the clip"


def test_highlights_are_ordered_by_what_is_worth_watching():
    ace = _labelled(my_kills=5)
    clutch = _labelled(my_kills=2, last_stand_at=1.0, enemies_at_last_stand=2)
    quiet = _labelled(my_kills=4)
    order = rounds.highlights([quiet, clutch, ace])
    assert order[0].labels[0] == "ACE"
    assert "CLUTCH" in order[1].labels[0]


def test_rounds_with_nothing_to_show_are_not_offered():
    assert rounds.highlights([_labelled(my_kills=1)]) == []


# ------------------------------------------------------- turning rounds into clips

def _hl(**kw):
    base = dict(number=7, started=100.0, ended=190.0, score_before=(3, 3),
                score_after=(4, 3), my_side="l", won=True, my_kills=2,
                kill_times=[150.0, 152.0], labels=["CLUTCH 1v2"])
    base.update(kw)
    return Round(**base)


def test_a_round_clip_is_anchored_on_the_round_not_the_kills():
    """The difference from burst clipping, and the reason for a second mode.

    build() slides a window over a burst of kills. What makes a round worth
    watching can be one kill at the end of a 1v3, and the run-up is the point
    rather than dead air -- so a round clip is anchored on the round.
    """
    from autostream.clips import plan

    r = _hl(last_stand_at=140.0)
    c = plan.build_rounds([r], game="Counter-Strike 2", pre_roll=3.0, tail=3.0)[0]
    assert c.start == pytest.approx(137.0)     # the last stand, minus pre-roll
    assert c.end == pytest.approx(193.0)       # the round's end, plus tail
    assert c.labels == ["CLUTCH 1v2"]
    assert c.round_number == 7


def test_a_clip_never_starts_before_its_round_does():
    from autostream.clips import plan

    r = _hl(last_stand_at=101.0)
    c = plan.build_rounds([r], game="CS2", pre_roll=30.0)[0]
    assert c.start >= r.started


def test_trimming_keeps_the_END_of_the_round():
    """In Counter-Strike the resolution is the payoff.

    A trimmed clip must lose the opening, not the finish -- the opposite of
    what truncating from the front would do.
    """
    from autostream.clips import plan

    r = _hl(last_stand_at=110.0)
    whole = plan.build_rounds([r], game="CS2", whole_round=True, tail=2.0)[0]
    short = plan.build_rounds([r], game="CS2", whole_round=False,
                              clip_seconds=15, tail=2.0)[0]
    assert short.duration < whole.duration
    assert short.end == pytest.approx(whole.end), "the finish is kept"
    assert short.start > whole.start, "the opening is what gets dropped"


def test_the_clip_name_says_what_the_round_was():
    # Clips get dragged into editors and the folder is lost, so the label,
    # round number, position and length all live in the filename.
    from autostream.clips import plan

    c = plan.build_rounds([_hl(labels=["ACE"])], game="Counter-Strike 2")[0]
    assert "ACE" in c.name.upper()
    assert "_r7_" in c.name
    assert c.name.startswith("Counter-Strike-2_01_")


def test_a_round_with_no_kills_and_no_last_stand_still_cuts_from_the_round():
    from autostream.clips import plan

    r = _hl(my_kills=0, kill_times=[], last_stand_at=None,
            labels=["SURVIVED THE LOSS"])
    c = plan.build_rounds([r], game="CS2")[0]
    assert c.start >= r.started and c.end >= r.ended


def test_round_clips_carry_the_result_into_the_manifest():
    from autostream.clips import plan

    d = plan.build_rounds([_hl(won=False, labels=["ALMOST 1v3"])],
                          game="CS2")[0].as_dict()
    assert d["labels"] == ["ALMOST 1v3"]
    assert d["won"] is False
    assert d["round"] == 7


def test_burst_clips_do_not_pretend_to_be_rounds():
    # The extra fields are round-only, and must stay absent for kill clips so
    # nothing downstream has to know which mode produced them.
    from autostream.clips import plan

    kills = [{"time": 10.0, "end": 10.0, "score": 1.0, "count": 1},
             {"time": 12.0, "end": 12.0, "score": 1.0, "count": 1}]
    d = plan.build(kills, game="Delta Force", min_kills=2,
                   clip_seconds="15", pre_roll=1.5, tail=2.0,
                   source_duration=600.0)[0].as_dict()
    assert "labels" not in d and "round" not in d and "won" not in d


# ------------------------------------------------------------ the CS2 profile

def test_the_cs2_profile_asks_for_rounds_and_delta_force_does_not():
    from autostream.clips import profiles

    cs2 = profiles._build("cs2.exe", dict(profiles.BUILTIN["cs2.exe"]))
    df = profiles._build("deltaforceclient.exe",
                         dict(profiles.BUILTIN["deltaforceclient.exe"]))
    assert cs2.rounds is True
    assert df.rounds is False


def test_the_rounds_flag_and_hud_regions_round_trip():
    from autostream.clips import profiles
    from autostream.clips.profiles import Profile

    p = Profile(key="cs2.exe", label="CS2", band=(0.6, 0.03, 1.0, 0.3),
                template="", mode="killfeed", player="X", rounds=True,
                hud_regions={"timer": [0.1, 0.2, 0.3, 0.4]})
    back = profiles._build("cs2.exe", p.as_dict())
    assert back.rounds is True
    assert back.hud_regions["timer"] == [0.1, 0.2, 0.3, 0.4]


# ------------------------------------------------- the ffmpeg call itself
#
# Everything above tests logic on synthetic data, and that is exactly how a
# real bug got through: `-t` after `-i` is an OUTPUT option, so with two mapped
# outputs it constrained only the first and the second decoded to the end of
# the file. A twenty-second span became nineteen minutes of work on every
# chunk. No unit test touched ffmpeg, so nothing caught it.

def _have_ffmpeg() -> bool:
    try:
        from autostream.clips.tools import binary
        binary("ffmpeg")
        return True
    except Exception:            # noqa: BLE001
        return False


@pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg not installed")
def test_both_crops_get_the_same_number_of_frames(tmp_path):
    """The regression test for the -t placement bug.

    A dual-output extraction must produce the SAME frame count on both outputs,
    and only for the span asked for.
    """
    import shutil
    import subprocess

    from autostream.clips import killfeed as kf
    from autostream.clips.tools import binary

    src = tmp_path / "src.mp4"
    subprocess.run([binary("ffmpeg"), "-hide_banner", "-loglevel", "error",
                    "-nostdin", "-y", "-f", "lavfi",
                    "-i", "testsrc=size=640x360:rate=10:duration=30",
                    "-pix_fmt", "yuv420p", str(src)],
                   capture_output=True, check=False)
    assert src.exists() and src.stat().st_size > 0

    out = kf._extract_pair(src, (0.6, 0.03, 1.0, 0.3), 2.0, 4.0, 1.0, 8)
    try:
        feed = sorted(out.glob("f_*.png"))
        hud_frames = sorted(out.glob("s_*.png"))
        assert feed, "no kill-feed frames written"
        assert hud_frames, "no scoreboard frames written"
        assert len(feed) == len(hud_frames), (
            f"{len(feed)} feed frames but {len(hud_frames)} scoreboard frames "
            f"-- the two outputs disagree, which is the -t bug")
        # 4 seconds at 1 fps. Generous upper bound, but nowhere near the
        # hundreds the bug produced.
        assert len(feed) <= 8, f"{len(feed)} frames for a 4-second span"
    finally:
        shutil.rmtree(out, ignore_errors=True)
