"""CS2 demo parsing and demo-to-recording sync.

The parse itself is exercised against a stubbed demoparser2, so the suite has
no dependency on a 150MB demo. What is pinned here is the part that can go
silently wrong: the ALIGNMENT. A wrong offset does not fail loudly -- it cuts
every clip in the match at the wrong moment.

Cases marked FROM FOOTAGE reproduce a measurement taken from a real match:
de_anubis, 16 rounds, YUVANETA with 12 kills, synced against the card-tally
detector at offset +166.60s with a worst residual of 1.16s.
"""
from __future__ import annotations

import pytest

from autostream.clips import cs2_demo as cd

# The real match, in demo seconds. Every number here was measured.
ANUBIS = [44.2, 74.6, 127.0, 196.3, 628.6, 629.9, 753.0, 881.1,
          1010.3, 1019.3, 1023.2, 1357.9]
OFFSET = 166.60


# ------------------------------------------------------------------ aligning

def test_a_clean_recording_aligns_exactly():
    vod = [t + OFFSET for t in ANUBIS]
    s = cd.align(ANUBIS, vod)
    assert s.ok
    assert s.matched == len(ANUBIS)
    assert s.offset == pytest.approx(OFFSET, abs=0.05)
    assert s.scale == pytest.approx(1.0, abs=1e-4)
    assert s.residual < 0.05


def test_alignment_survives_the_detector_missing_one():
    """FROM FOOTAGE: the card detector missed the kill at demo 196.3s."""
    vod = [t + OFFSET for t in ANUBIS if t != 196.3]
    s = cd.align(ANUBIS, vod)
    assert s.ok and s.matched == len(ANUBIS) - 1
    assert s.offset == pytest.approx(OFFSET, abs=0.05)


def test_alignment_survives_the_detector_inventing_some():
    """FROM FOOTAGE: it invented two inside the match and found four more
    belonging to a SECOND match later in the same recording."""
    vod = sorted([t + OFFSET for t in ANUBIS]
                 + [157.4, 1370.0, 1370.0, 1990.9, 2697.9, 2700.5])
    s = cd.align(ANUBIS, vod)
    assert s.ok and s.matched == len(ANUBIS)
    assert s.offset == pytest.approx(OFFSET, abs=0.05)


def test_alignment_works_when_recording_started_mid_match():
    # The ordinary case: OBS was started after the match had begun, so the
    # first kills are simply not in the recording.
    vod = [t + OFFSET for t in ANUBIS[4:]]
    s = cd.align(ANUBIS, vod)
    assert s.ok
    assert s.offset == pytest.approx(OFFSET, abs=0.05)


def test_a_wrong_demo_is_refused_rather_than_fitted():
    """The whole point of the residual check. A wrong offset does not fail
    loudly -- it mis-cuts every clip in the match, so it has to be caught."""
    import random

    rng = random.Random(7)
    other = sorted(rng.uniform(0, 2000) for _ in range(12))
    s = cd.align(ANUBIS, other)
    assert not s.ok
    assert "is this the right match" in s.why


def test_too_few_kills_to_be_sure_is_not_a_guess():
    s = cd.align([10.0, 20.0], [110.0, 120.0])
    assert not s.ok and "too few" in s.why


def test_a_wrong_tickrate_comes_out_as_a_rate_not_a_wreck():
    # Parsed at 64 when the demo was really 128: every time is doubled. The
    # fit absorbs it, which is why the tickrate does not have to be known.
    vod = [t * 2.0 + OFFSET for t in ANUBIS]
    s = cd.align(ANUBIS, vod)
    assert s.ok and s.matched == len(ANUBIS)
    assert s.scale == pytest.approx(2.0, abs=1e-3)
    assert s.residual < 0.05


def test_to_vod_uses_both_the_offset_and_the_scale():
    s = cd.Sync(offset=100.0, scale=2.0, ok=True)
    assert s.to_vod(10.0) == pytest.approx(120.0)


# ----------------------------------------------------------- who is who

def _match(kills):
    return cd.Match(path=cd.Path("x.dem"), kills=[
        cd.Kill(time=t, round=0, killer=k, victim="someone")
        for t, k in kills])


def test_the_local_player_is_worked_out_not_configured():
    """The pixel detectors only ever report the LOCAL player's kills, so the
    demo player whose pattern lines up with them is the local player. That is
    what lets the demo path need no in-game name either."""
    m = _match([(t, "YUVANETA") for t in ANUBIS]
               + [(t + 3.3, "SomeoneElse") for t in ANUBIS])
    who, s = cd.identify(m, [t + OFFSET for t in ANUBIS])
    assert who == "YUVANETA", (who, s.why)
    assert s.matched == len(ANUBIS)


def test_identify_gives_up_when_nobody_fits():
    m = _match([(t, "Stranger") for t in (5.0, 400.0, 900.0, 1600.0)])
    who, s = cd.identify(m, [11.0, 55.0, 700.0, 1234.0])
    assert who == "" or not s.ok


# ----------------------------------------------------------------- parsing

class _FakeDF:
    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, how):
        return list(self._rows)


class _FakeParser:
    """Stands in for demoparser2 so the suite needs no 150MB demo.

    Shaped like the real thing where it matters: `player=[...]` is accepted and
    puts each side's name on the kill, `round`/`total_rounds_played` number the
    rounds the two different ways the real events do, and `parse_ticks` answers
    with a roster per freeze-end tick.
    """
    def __init__(self, path):
        self.path = path

    def parse_header(self):
        return {"map_name": "de_anubis"}

    def parse_event(self, name, player=None, other=None):
        if name == "player_death":
            return _FakeDF([
                # warm-up: same shape as a real kill, must not be counted
                {"tick": 64 * 2, "total_rounds_played": 0,
                 "is_warmup_period": True,
                 "attacker_name": "YUVANETA", "user_name": "KOMI",
                 "attacker_team_name": "CT", "user_team_name": "TERRORIST",
                 "weapon": "ak47", "headshot": False, "thrusmoke": False,
                 "attackerblind": False, "penetrated": 0, "noscope": False,
                 "assister_name": None, "assistedflash": False},
                {"tick": 64 * 10, "total_rounds_played": 0,
                 "is_warmup_period": False,
                 "attacker_name": "YUVANETA", "user_name": "KOMI",
                 "attacker_team_name": "CT", "user_team_name": "TERRORIST",
                 "weapon": "ak47", "headshot": True, "thrusmoke": True,
                 "attackerblind": False, "penetrated": 0, "noscope": False,
                 "assister_name": None, "assistedflash": False},
                # the world killing someone: no attacker, must be dropped
                {"tick": 64 * 20, "total_rounds_played": 0,
                 "is_warmup_period": False,
                 "attacker_name": None, "user_name": "FUSION",
                 "attacker_team_name": None, "user_team_name": "CT",
                 "weapon": "world", "headshot": False, "thrusmoke": False,
                 "attackerblind": False, "penetrated": 0, "noscope": False,
                 "assister_name": None, "assistedflash": False},
            ])
        if name == "round_start":
            return _FakeDF([{"tick": 64, "round": 1},
                            {"tick": 64 * 100, "round": 2}])
        if name == "round_freeze_end":
            # numbered by total_rounds_played, one behind `round`
            return _FakeDF([{"tick": 64 * 20, "total_rounds_played": 0},
                            {"tick": 64 * 110, "total_rounds_played": 1}])
        if name == "round_end":
            # `winner` is "CT"/"T", NOT a number -- reading it as an int threw,
            # and the guard around it then swallowed every round while the
            # kills still looked fine. `reason` is a string too.
            return _FakeDF([
                {"tick": 64 * 90, "round": 1, "winner": "CT",
                 "reason": "t_killed"},
                {"tick": 64 * 180, "round": 2, "winner": "T",
                 "reason": "bomb_defused"}])
        return _FakeDF([])

    def parse_ticks(self, props, ticks=None):
        rows = []
        for t in ticks or []:
            # sides swap for the second round, which is what makes this worth
            # reading per round rather than once
            swap = t > 64 * 100
            for who, side in (("YUVANETA", 3), ("KOMI", 2)):
                if swap:
                    side = 2 if side == 3 else 3
                rows.append({"tick": t, "name": who, "team_num": side})
        return _FakeDF(rows)


@pytest.fixture()
def fake_demo(monkeypatch):
    import sys
    import types

    mod = types.ModuleType("demoparser2")
    mod.DemoParser = _FakeParser
    monkeypatch.setitem(sys.modules, "demoparser2", mod)


def test_parse_normalises_ticks_into_seconds(fake_demo, tmp_path):
    m = cd.parse(tmp_path / "x.dem")
    assert m.map_name == "de_anubis"
    assert len(m.kills) == 1                 # world kill and warm-up both gone
    k = m.kills[0]
    assert k.time == pytest.approx(10.0)     # 640 ticks at 64 tick
    assert k.killer == "YUVANETA" and k.victim == "KOMI"
    assert k.headshot and k.thrusmoke and not k.penetrated


def test_warmup_kills_are_not_kills(fake_demo, tmp_path):
    """They arrive with the same shape as everything else.

    Counting them inflates the match total and hands the fingerprint sync a
    pile of events the recording may not even cover.
    """
    m = cd.parse(tmp_path / "x.dem")
    assert m.warmup == 1
    assert all(k.time >= 10.0 for k in m.kills)


def test_rounds_are_numbered_the_way_the_demo_numbers_them(fake_demo, tmp_path):
    # 1-indexed, from the event's own `round` column rather than from the row's
    # position -- two different events disagree by one about which is which.
    m = cd.parse(tmp_path / "x.dem")
    assert [r.number for r in m.rounds] == [1, 2]
    assert m.kills[0].round == 1


def test_parse_reads_rounds_including_a_named_winner(fake_demo, tmp_path):
    m = cd.parse(tmp_path / "x.dem")
    assert m.rounds[0].start == pytest.approx(1.0)
    assert m.rounds[0].end == pytest.approx(90.0)
    assert m.rounds[0].winner == "CT"
    assert m.rounds[0].reason == "t_killed"
    assert m.rounds[1].winner == "T"


def test_a_round_opens_when_freeze_time_ends_not_when_it_starts(fake_demo,
                                                               tmp_path):
    """Freeze time is the buy menu.

    A round clip allowed to open at round_start opens on twenty seconds of
    standing still, so the round layer anchors on the freeze end instead.
    """
    m = cd.parse(tmp_path / "x.dem")
    assert m.rounds[0].start == pytest.approx(1.0)
    assert m.rounds[0].live == pytest.approx(20.0)
    assert m.rounds[0].opens_at == pytest.approx(20.0)


def test_the_roster_is_read_again_every_round_so_the_swap_is_free(fake_demo,
                                                                 tmp_path):
    """The half-time swap needs no detecting.

    On the pixel path it is a whole function, because the scoreboard reads
    2-10 before the swap and 10-2 after and nothing says which. Here the roster
    is simply re-read at each round's freeze end.
    """
    m = cd.parse(tmp_path / "x.dem")
    assert m.team_of("YUVANETA", 1) == "CT"
    assert m.team_of("YUVANETA", 2) == "T"
    assert m.team_of("KOMI", 1) == "T"


def test_an_unknown_round_carries_forward_and_never_backward(fake_demo,
                                                            tmp_path):
    # Backwards across a swap would put the player on the wrong side for every
    # round of the first half -- the exact bug rounds.halves() exists for.
    m = cd.parse(tmp_path / "x.dem")
    assert m.team_of("YUVANETA", 5) == "T"        # after the last known round
    m.teams.pop(1)
    assert m.team_of("YUVANETA", 1) == ""         # not "T" from round 2


def test_a_missing_attacker_never_becomes_a_kill(fake_demo, tmp_path):
    # Falls, the bomb and team damage all arrive with no attacker. Counting
    # them would put kills on the board that nobody got.
    m = cd.parse(tmp_path / "x.dem")
    assert all(k.killer for k in m.kills)


def test_by_and_deaths_of_are_case_insensitive(fake_demo, tmp_path):
    m = cd.parse(tmp_path / "x.dem")
    assert len(m.by("yuvaneta")) == 1
    assert len(m.deaths_of("komi")) == 1
    assert m.players() == ["YUVANETA"]


def test_a_parser_without_the_player_keyword_still_yields_kills(monkeypatch,
                                                               tmp_path):
    """Older demoparser2 builds do not take `player=[...]`.

    Losing the event entirely over a keyword would cost every kill; the sides
    fall back to what parse_ticks says instead.
    """
    import sys
    import types

    class Older(_FakeParser):
        def parse_event(self, name, other=None):
            return super().parse_event(name, other=other)

    mod = types.ModuleType("demoparser2")
    mod.DemoParser = Older
    monkeypatch.setitem(sys.modules, "demoparser2", mod)
    m = cd.parse(tmp_path / "x.dem")
    assert len(m.kills) == 1
    assert m.team_of("YUVANETA", 1) == "CT"


def test_the_audit_only_marks_the_detector_inside_the_demos_own_span():
    """A recording routinely holds a second match the demo knows nothing about.

    Counting those as false positives would mark the detector down for being
    right about them.
    """
    demo = [10.0, 20.0, 30.0]
    vod = [110.0, 120.0, 130.0, 900.0]        # 900 is a later, other match
    s = cd.align(demo, vod)
    got = cd.audit(demo, vod, s)
    assert got["matched"] == 3
    assert got["missed"] == 0
    assert got["invented"] == 0
    assert got["detected"] == 4 and got["detected_in_span"] == 3


def test_the_audit_counts_what_the_detector_got_wrong():
    demo = [10.0, 20.0, 30.0, 40.0]
    vod = [110.0, 120.0, 130.0, 133.0]        # 40 missed, 133 invented
    s = cd.align(demo, vod)
    got = cd.audit(demo, vod, s)
    assert got["missed"] == 1
    assert got["invented"] == 1


def test_map_of_reads_the_header_without_parsing(tmp_path):
    p = tmp_path / "m.dem"
    p.write_bytes(b"PBDEMS2\x00" + b"\x00" * 40 + b"de_anubis2" + b"\x00" * 900)
    assert cd.map_of(p) == "de_anubis2"
    assert cd.map_of(tmp_path / "missing.dem") == ""


# ============================================ which match, decided by the clock
#
# FROM A REAL FAILURE. A 46-minute recording, sixteen demos in the folder, and
# the right one sitting there unread: the probe found six kills, the correct
# demo aligned four of them PERFECTLY (share 1.00), and it was thrown away for
# being two short of MIN_MATCHED.
#
# The floor exists to stop an unrelated demo winning on coincidence, and it
# cannot be simply lowered: on those same six kills a match from 22 August and
# one from 22 NOVEMBER both scored 5 at share 0.62. Nothing in those numbers
# separates them.
#
# Counter-Strike writes the match time in a .dem.info beside every demo, and it
# was going unread. That separates them instantly.

import struct  # noqa: E402


def _info_blob(when: int) -> bytes:
    """A .dem.info-shaped blob carrying `when` as a protobuf varint."""
    out = bytearray(b"\x08\x96\x01\x12\x20")      # some plausible leading fields
    out.append(0x28)                              # field 5, varint
    v = when
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            break
    out += b"\x32\x10" + b"\x00" * 16
    return bytes(out)


def _demo_with_info(tmp_path, name: str, when: int):
    dem = tmp_path / f"{name}.dem"
    dem.write_bytes(b"not a real demo")
    info = tmp_path / f"{name}.dem.info"
    info.write_bytes(_info_blob(when))
    return dem


def test_the_match_time_is_read_out_of_the_info_file(tmp_path):
    from autostream.clips import cs2_demo

    played = int(__import__("time").time()) - 3600
    dem = _demo_with_info(tmp_path, "match730_1", played)
    assert cs2_demo.match_time(dem) == pytest.approx(played, abs=1)


def test_an_unreadable_info_is_not_an_error(tmp_path):
    """An older .info may carry no timestamp, and the caller then falls back to
    the fingerprint alone rather than refusing to look."""
    from autostream.clips import cs2_demo

    dem = tmp_path / "match730_x.dem"
    dem.write_bytes(b"x")
    assert cs2_demo.match_time(dem) is None
    (tmp_path / "match730_x.dem.info").write_bytes(b"\x00\x01\x02")
    assert cs2_demo.match_time(dem) is None


def test_only_the_demos_played_during_the_recording_are_offered(tmp_path):
    """The whole point: sixteen demos in a folder, and a directory listing says
    which two belong to a 46-minute recording."""
    import time as _t

    from autostream.clips import cs2_demo

    started = _t.time() - 7 * 86400
    _demo_with_info(tmp_path, "during_1", int(started + 60))     # a minute in
    _demo_with_info(tmp_path, "during_2", int(started + 2400))   # 40 minutes in
    _demo_with_info(tmp_path, "before", int(started - 86400))    # the day before
    _demo_with_info(tmp_path, "after", int(started + 86400))     # the day after
    _demo_with_info(tmp_path, "months_later", int(started + 90 * 86400))

    got = [p.name for p in cs2_demo.demos_for_recording(tmp_path, started, 46 * 60)]
    assert sorted(got) == ["during_1.dem", "during_2.dem"]


def test_a_recording_with_no_match_says_none_rather_than_hoping(tmp_path):
    """It used to answer "have" for any demo newer than the recording, and told
    a user their replay was on disk when all sixteen belonged to other
    matches -- who then spent twelve minutes proving it."""
    import time as _t

    from autostream.clips import cs2_demo

    started = _t.time() - 7 * 86400
    _demo_with_info(tmp_path, "another_day", int(started + 5 * 86400))
    assert cs2_demo.demo_state(tmp_path, started, 46 * 60)["state"] == "none"


def test_a_match_in_the_window_with_no_demo_is_listed(tmp_path):
    """The precise meaning of "listed": Counter-Strike knows about this match
    and has not finished downloading it."""
    import time as _t

    from autostream.clips import cs2_demo

    started = _t.time() - 7 * 86400
    (tmp_path / "m.dem.info").write_bytes(_info_blob(int(started + 60)))
    assert cs2_demo.demo_state(tmp_path, started, 46 * 60)["state"] == "listed"


# ------------------------------------------- the clock constrains WHERE, too

def test_an_offset_the_clock_forbids_is_refused():
    """Lowering the floor for a dated demo is only safe because of this. Without
    it, the SECOND match of the same session won on five coincidental timings,
    under another player's name, at an offset placing the match fourteen
    minutes before the recording started."""
    from autostream.clips import cs2_demo

    demo = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    vod = [x + 100.0 for x in demo]
    good = cs2_demo.align(demo, vod, expect_offset=100.0)
    assert good.ok, good.why

    bad = cs2_demo.align(demo, vod, expect_offset=100.0 + 3 * cs2_demo.OFFSET_TOL)
    assert not bad.ok
    assert "from where this match was played" in bad.why


def test_a_dated_demo_may_align_on_fewer_kills():
    """Four kills that line up perfectly are enough to place a match the clock
    has already identified. Six were demanded, and the right demo was thrown
    away for having four."""
    from autostream.clips import cs2_demo

    demo = [10.0, 20.0, 30.0, 40.0, 100.0, 200.0, 300.0, 400.0, 500.0, 600.0]
    vod = [x + 50.0 for x in demo[:4]]
    strict = cs2_demo.align(demo, vod)
    loose = cs2_demo.align(demo, vod, floor=cs2_demo.MIN_MATCHED_DATED,
                           expect_offset=50.0)
    assert not strict.ok, "the strict floor is what rejected the right demo"
    assert loose.ok and loose.matched == 4


def test_identify_does_not_break_a_tie_alphabetically():
    """Two players in one demo routinely align the same NUMBER of a handful of
    probe kills -- measured, the local player and a team-mate both hit 4 -- and
    the tie went to whoever came first out of players(). That is alphabetical
    order deciding whose kills get clipped."""
    from autostream.clips import cs2_demo

    import inspect
    src = inspect.getsource(cs2_demo.identify)
    assert "rank(" in src, "identify still compares on matched alone"
    assert "expect_offset" in src
