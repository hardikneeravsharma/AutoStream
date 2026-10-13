r"""The match cut the way a highlight channel cuts one.

MEASURED AGAINST THE GENRE, NOT INVENTED. "15 Times Shroud Was a Beast In
VALORANT" is 6m32s: an 18-second intro and fourteen moments of 15 to 50
seconds, averaging 28, every one named for the play -- "Insanely quick 4K",
"3 kills with 4 bullets" -- and not one named "Round 7". Three other VALORANT
uploads on that channel run 9:58, 10:21 and 12:04.

The numbers below are that shape. Everything here is arithmetic over rounds
and kill times, so none of it needs footage.
"""
from __future__ import annotations

from autostream.clips import match_recap as recap


class R:
    """What a round looks like to this module. See clips/rounds.Round."""

    def __init__(self, number, started, ended, *, kill_times=(), labels=None,
                 won=None, my_kills=None):
        self.number = number
        self.started = started
        self.ended = ended
        self.kill_times = list(kill_times)
        self.labels = list(labels or [])
        self.won = won
        self.my_kills = len(self.kill_times) if my_kills is None else my_kills


def _match(n=20, every=110.0, length=90.0, kills=2):
    """`n` rounds, `kills` kills apiece, each starting `every` seconds apart."""
    out = []
    for i in range(n):
        a = 100.0 + i * every
        ts = [a + 40.0 + j * 3.0 for j in range(kills)]
        out.append(R(i + 1, a, a + length, kill_times=ts, won=(i % 2 == 0)))
    return out


# ---- length: minutes, not an hour and not ninety seconds -----------------


def test_a_long_match_is_cut_to_about_the_target():
    """The fault that started this: 38 rounds became 52 minutes, which is 83%
    of the recording. A recap is minutes."""
    ms = recap.moments(_match(n=40), target=480.0)
    spent = sum(m.seconds for m in ms)
    assert 300.0 <= spent <= 540.0, spent
    assert len(ms) >= 8


def test_a_short_match_is_not_padded_to_the_target():
    """Six rounds is not eight minutes of anything. A recap that repeated
    footage to reach a number would be worse than a short one."""
    ms = recap.moments(_match(n=6), target=480.0)
    assert sum(m.seconds for m in ms) < 300.0
    assert len(ms) == 6


def test_every_moment_is_inside_the_measured_range():
    for m in recap.moments(_match(n=30)):
        assert recap.MOMENT_MIN <= m.seconds <= recap.MOMENT_MAX + 0.001, m


def test_nothing_to_show_is_said_rather_than_guessed():
    assert recap.moments([R(1, 0.0, 90.0)]) == []
    assert recap.moments([]) == []


# ---- what gets in, and in what order -------------------------------------


def test_the_best_rounds_get_in_and_the_quiet_ones_do_not():
    rounds = _match(n=30, kills=1)
    rounds[7].labels = ["ACE"]
    rounds[7].kill_times = [rounds[7].started + 40 + j * 3 for j in range(5)]
    rounds[19].labels = ["CLUTCH 1V3"]
    ms = recap.moments(rounds, target=120.0)
    names = [m.name for m in ms]
    assert any("Ace" in n for n in names), names
    assert any("Clutch" in n.title() for n in names), names


def test_chosen_by_strength_but_played_in_order():
    """A recap of a MATCH, not a montage: the score moves forward and the last
    moment is the one the match ended on."""
    rounds = _match(n=25)
    rounds[22].labels = ["ACE"]
    ms = recap.moments(rounds, target=200.0)
    assert [m.start for m in ms] == sorted(m.start for m in ms)


def test_moments_that_touch_are_merged():
    """Two bursts in one round can be chosen separately and still overlap once
    the lead-in and tail are added. A cut from a frame to the frame beside it
    reads as a stutter."""
    rd = R(1, 0.0, 200.0, kill_times=[50.0, 53.0, 70.0, 73.0])
    ms = recap.moments([rd], target=600.0)
    for a, b in zip(ms, ms[1:]):
        assert b.start > a.end


# ---- the names, which are the reason anyone opens the chapter list -------


def test_a_moment_is_named_for_the_play_not_the_round_number():
    rd = R(7, 0.0, 90.0, kill_times=[40.0, 43.0, 46.0], labels=["ACE"])
    assert recap.name_of(rd, 3) == "Ace"
    assert "7" not in recap.name_of(rd, 3)


def test_a_round_with_no_label_is_named_by_its_kills():
    rd = R(3, 0.0, 90.0, kill_times=[40.0, 43.0, 46.0])
    assert recap.name_of(rd, 3) == "3K"
    assert recap.name_of(rd, 5) == "Ace"


def test_one_kill_earns_no_name_rather_than_a_boring_one():
    """"1 kill" as a YouTube chapter is a reason not to click."""
    assert recap.name_of(R(3, 0.0, 90.0), 1) == ""


def test_the_strongest_label_names_the_moment():
    """A round that is an ace AND a 1v3 is called an ace: `rounds.rank_of`
    already decides which, and a recap must not disagree with the clip list."""
    rd = R(4, 0.0, 90.0, labels=["LAST ALIVE 1V3", "ACE"])
    assert recap.name_of(rd, 5) == "Ace"


# ---- two matches in one recording ----------------------------------------


def test_two_matches_are_told_apart_in_the_chapters():
    """The fault: two matches became one file titled 15-23, a scoreline that
    never existed. One file is fine; one file pretending to be one match is
    not."""
    first = _match(n=10)
    second = _match(n=10)
    for r in second:
        r.started += 4000.0
        r.ended += 4000.0
        r.kill_times = [t + 4000.0 for t in r.kill_times]
    ms = recap.moments(first + second,
                       match_of=lambda r: "Lotus" if r.started < 4000 else "Sunset")
    assert {m.match for m in ms} == {"Lotus", "Sunset"}
    offs = []
    t = 0.0
    for m in ms:
        offs.append(t)
        t += m.seconds
    marks = recap.chapters(ms, [m.seconds for m in ms], offs)
    assert any(n.startswith("Lotus") for _t, n in marks), marks
    assert any(n.startswith("Sunset") for _t, n in marks), marks


def test_one_match_is_not_labelled_with_its_own_name():
    """A label that is the same on every chapter is noise."""
    ms = recap.moments(_match(n=10), match_of=lambda r: "")
    assert all(m.match == "" for m in ms)


# ---- chapters ------------------------------------------------------------


def test_chapters_obey_youtubes_rules_or_there_are_none():
    """First at 0:00, at least three, ten seconds apart. Break one and YouTube
    shows none of them, which is the same as writing none."""
    ms = recap.moments(_match(n=12))
    offs, t = [], 0.0
    for m in ms:
        offs.append(t)
        t += m.seconds
    marks = recap.chapters(ms, [m.seconds for m in ms], offs)
    assert marks[0][0] == 0.0
    assert len(marks) >= 3
    for a, b in zip(marks, marks[1:]):
        assert b[0] - a[0] >= 10.0


def test_too_few_chapters_is_none_at_all():
    rd = R(1, 0.0, 90.0, kill_times=[40.0, 43.0])
    ms = recap.moments([rd])
    assert recap.chapters(ms, [m.seconds for m in ms], [0.0]) == []


# ---- the opening shot ----------------------------------------------------


def test_the_recap_opens_on_the_match_and_not_on_a_kill():
    """A highlight that opens on a kill has no idea what it is looking at yet,
    and the title card needs somewhere to sit that is not already the point."""
    rounds = _match(n=8)
    got = recap.intro(rounds)
    assert got is not None
    assert got.start < min(t for r in rounds for t in r.kill_times)
    assert 4.0 <= got.seconds <= recap.INTRO + 0.001


def test_the_title_says_the_score_and_the_kills():
    rounds = _match(n=6, kills=2)
    head, sub = recap.title_of("VALORANT", rounds)
    assert head == "VALORANT"
    assert "3-3" in sub and "12 KILLS" in sub


def test_a_map_name_is_a_chapter_once_not_on_every_moment():
    """The first real run produced eight chapters in a row reading "Lotus",
    because a one-kill moment has no name of its own and the match name stood
    in for it. Eight identical chapters fill the list and say nothing."""
    rounds = _match(n=14, kills=1)
    # Three rounds that earn a name of their own, so the list is long enough
    # for YouTube to show any of it at all; the other eleven are the ones
    # that used to be called "Lotus".
    for i in (3, 7, 11):
        rounds[i].kill_times = [rounds[i].started + 40.0 + j * 3.0 for j in range(3)]
    ms = recap.moments(rounds, match_of=lambda r: "Lotus")
    offs, t = [], 0.0
    for m in ms:
        offs.append(t)
        t += m.seconds
    marks = recap.chapters(ms, [m.seconds for m in ms], offs)
    assert sum(1 for _t, n in marks if n.startswith("Lotus")) == 1, marks


def test_one_spelling_for_a_label():
    """"LAST ALIVE 1v3", "Last Alive" and "CLUTCH 1v2" in the same chapter
    list is what automatic looks like."""
    assert recap.tidy_label("LAST ALIVE 1v3") == "Last Alive 1v3"
    assert recap.tidy_label("CLUTCH 1V2") == "Clutch 1V2"
    assert recap.tidy_label("Flawless") == "Flawless"


def test_two_matches_get_no_invented_scoreline():
    """Lotus won 13-10 plus Sunset lost 2-13 came out as "15-23", a result
    neither game had."""
    _head, sub = recap.title_of("VALORANT", _match(n=10), matches=2)
    assert "2 MATCHES" in sub
    assert "5-5" not in sub
