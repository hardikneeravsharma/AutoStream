"""Valorant's own record of a match, instead of reading the screen.

The fixtures here are shaped like Riot's `match-details/v1/matches/{id}`
response -- gameStartMillis, kills with gameTime, roundResults with a
roundCeremony, and playerLocations listing whoever was still alive. The field
names are the ones in the documented response, so a rename upstream fails here
rather than silently producing empty rounds.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autostream import valorant_api                      # noqa: E402
from autostream.clips import valorant_match as vm        # noqa: E402

ME = "me-puuid"
MATE = "mate-puuid"
FOE1, FOE2, FOE3 = "foe1", "foe2", "foe3"
START_MS = 1_788_030_000_000          # epoch ms
REC_STARTED = START_MS / 1000 - 60    # recording began a minute earlier


def _kill(round_no, at_s, killer, victim, alive):
    return {"round": round_no, "gameTime": int(at_s * 1000),
            "roundTime": int(at_s * 1000), "killer": killer, "victim": victim,
            "playerLocations": [{"subject": p} for p in alive]}


def _match(rounds=2, ceremony="CeremonyClutch"):
    kills = [
        # round 0: an ordinary two-kill round, team alive
        _kill(0, 30.0, ME, FOE1, [ME, MATE, FOE1, FOE2, FOE3]),
        _kill(0, 34.0, ME, FOE2, [ME, MATE, FOE2, FOE3]),
        # round 1: the mate dies first, so this is a 1v2
        _kill(1, 90.0, FOE1, MATE, [ME, MATE, FOE1, FOE2]),
        _kill(1, 95.0, ME, FOE1, [ME, FOE1, FOE2]),
        _kill(1, 99.0, ME, FOE2, [ME, FOE2]),
    ]
    return {
        "matchInfo": {"matchId": "abc12345-0000-0000-0000-000000000001",
                      "gameStartMillis": START_MS,
                      "gameLengthMillis": 600_000,
                      "queueID": "competitive", "isRanked": True,
                      "isCompleted": True},
        "players": [
            {"subject": ME, "gameName": "YuvaNeta", "teamId": "Blue"},
            {"subject": MATE, "gameName": "Mate", "teamId": "Blue"},
            {"subject": FOE1, "gameName": "Foe1", "teamId": "Red"},
            {"subject": FOE2, "gameName": "Foe2", "teamId": "Red"},
            {"subject": FOE3, "gameName": "Foe3", "teamId": "Red"},
        ],
        "roundResults": [
            {"roundNum": 0, "roundResult": "Eliminated", "winningTeam": "Blue",
             "roundCeremony": "CeremonyDefault"},
            {"roundNum": 1, "roundResult": "Eliminated", "winningTeam": "Blue",
             "roundCeremony": ceremony, "plantRoundTime": 40000},
        ][:rounds],
        "kills": kills,
    }


def _m(data=None, **kw):
    return vm.Match(Path("x.json"), data or _match(**kw))


# ------------------------------------------------------------ reading it

def test_the_record_says_when_the_match_started_and_how_long_it_was():
    m = _m()
    assert m.started == START_MS / 1000
    assert m.seconds == 600.0
    assert m.ranked is True
    assert m.mode == "competitive"


def test_only_this_players_kills_are_counted():
    m = _m()
    # Five kills in the match; four of them are the player's.
    assert m.my_kill_times(ME) == [30.0, 34.0, 95.0, 99.0]
    assert m.my_kill_times(FOE1) == [90.0]


# ------------------------------------------------------------ which match

def test_a_match_that_began_inside_the_recording_is_the_one():
    m = _m()
    assert vm.for_recording(REC_STARTED, 1800.0, [m]) == [m]


def test_a_match_from_another_session_is_not():
    m = _m()
    # The recording started an hour after the match did.
    assert vm.for_recording(m.started + 3600, 1800.0, [m]) == []
    # ...and one that started an hour before it ended.
    assert vm.for_recording(m.started - 7200, 600.0, [m]) == []


def test_slack_covers_obs_starting_a_moment_late():
    """OBS is told to record and the file's first frame lands a beat later, so
    a match that began seconds BEFORE the recording still belongs to it."""
    m = _m()
    assert vm.for_recording(m.started + 30, 600.0, [m]) == [m]


# ------------------------------------------------------------ lining it up

def test_the_clock_alone_lines_it_up_when_there_is_nothing_to_fingerprint():
    m = _m()
    sync = vm.align(m, ME, REC_STARTED, [])
    assert sync.ok and sync.offset == pytest.approx(60.0, abs=0.01)
    assert "clock" in sync.why


def test_the_fingerprint_is_used_when_it_agrees_with_the_clock():
    m = _m()
    # What the pixel reader would have found: the same three kills, 60s in.
    detected = [90.0, 155.0, 159.0]
    sync = vm.align(m, ME, REC_STARTED, detected)
    assert sync.ok
    assert sync.offset == pytest.approx(60.0, abs=1.0)
    assert sync.matched >= 3


def test_neither_is_trusted_when_they_disagree():
    """A fingerprint that locks onto a different match, or a clock that is not
    what it seems, must refuse rather than mis-cut every clip in the run."""
    m = _m()
    # The detector's kills sit 600s from where the clock says they should.
    detected = [630.0, 695.0, 699.0]
    sync = vm.align(m, ME, REC_STARTED, detected)
    assert not sync.ok
    assert "disagree" in sync.why


def test_a_record_with_no_kills_by_this_player_cannot_line_up():
    m = _m()
    sync = vm.align(m, "nobody", REC_STARTED, [90.0, 155.0])
    assert not sync.ok


# ------------------------------------------------------------ what it gives

def _sync(m):
    return vm.align(m, ME, REC_STARTED, [])


def test_kills_come_out_on_the_recordings_timeline():
    m = _m()
    got = vm.kills_from(m, ME, _sync(m))
    assert [round(k["time"], 1) for k in got] == [90.0, 94.0, 155.0, 159.0]
    assert all(k["count"] == 1 for k in got)


def test_alive_counts_are_counted_rather_than_inferred():
    """playerLocations only lists players who are ALIVE, which is the thing the
    pixel reader could never see."""
    m = _m()
    rds = vm.rounds_from(m, ME, _sync(m))
    by_num = {r.number: r for r in rds}
    # Round 1: the mate died first, leaving the player alone against two.
    assert by_num[2].min_my_alive == 1
    assert by_num[2].enemies_at_last_stand == 2
    # Round 0: nobody on the player's side died.
    assert by_num[1].min_my_alive == 2


def test_riots_own_ceremony_leads_the_labels():
    """CLUTCH is not computed here -- it is what Riot called that round."""
    m = _m()
    rds = vm.rounds_from(m, ME, _sync(m))
    second = [r for r in rds if r.number == 2][0]
    assert second.labels and second.labels[0] == "CLUTCH"
    assert "PLANT" in second.flags


def test_an_unknown_ceremony_is_not_invented():
    m = _m(ceremony="CeremonySomethingNew")
    rds = vm.rounds_from(m, ME, _sync(m))
    second = [r for r in rds if r.number == 2][0]
    assert "CeremonySomethingNew" not in second.flags
    assert "CeremonySomethingNew" not in (second.labels or [])


def test_won_and_lost_come_from_the_record():
    m = _m()
    rds = vm.rounds_from(m, ME, _sync(m))
    assert all(r.won is True for r in rds)


def test_the_players_own_kills_are_the_ones_attributed():
    m = _m()
    rds = vm.rounds_from(m, ME, _sync(m))
    by_num = {r.number: r for r in rds}
    assert by_num[1].my_kills == 2         # not the 2 in the round total
    assert by_num[2].my_kills == 2
    assert by_num[2].my_deaths == 0        # the MATE died, not the player


# ------------------------------------------------------------ the cache

def test_the_cache_lives_beside_the_recordings():
    """A rebuild deletes the application folder, and a match record cannot be
    fetched again once the Riot Client has closed."""
    from autostream import paths

    assert vm.CACHE == paths.MATCHES_DIR
    assert str(paths.VIDEO_HOME) in str(vm.CACHE)


def test_a_cached_record_is_read_back(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "CACHE", tmp_path)
    (tmp_path / "one.json").write_text(json.dumps(_match()), encoding="utf-8")
    (tmp_path / "junk.json").write_text("not json", encoding="utf-8")
    (tmp_path / "other.json").write_text('{"no": "matchInfo"}', encoding="utf-8")
    got = vm.cached()
    assert len(got) == 1 and got[0].started == START_MS / 1000


def test_collecting_without_a_client_costs_nothing(monkeypatch):
    def no_client():
        raise valorant_api.Unavailable("the Riot Client is not running")

    monkeypatch.setattr(valorant_api, "session", no_client)
    assert vm.collect() == []


# ------------------------------------------------------------ the client

def test_the_platform_header_is_the_documented_blob():
    import base64

    got = json.loads(base64.b64decode(valorant_api.PLATFORM))
    assert got["platformType"] == "PC"
    assert got["platformOS"] == "Windows"


def test_the_client_version_is_read_out_of_the_games_own_log(tmp_path):
    f = tmp_path / "ShooterGame.log"
    f.write_text("some noise\nCI server version: release-11.00-shipping-8-3320046\n",
                 encoding="utf-8")
    assert valorant_api.client_version(f) == "release-11.00-shipping-8-3320046"


def test_a_log_with_no_version_says_so_rather_than_guessing(tmp_path):
    f = tmp_path / "ShooterGame.log"
    f.write_text("nothing useful here\n", encoding="utf-8")
    with pytest.raises(valorant_api.Unavailable):
        valorant_api.client_version(f)


def test_regions_that_play_on_another_regions_servers_map_to_its_shard():
    assert valorant_api.SHARDS["latam"] == "na"
    assert valorant_api.SHARDS["br"] == "na"
    assert valorant_api.SHARDS.get("eu", "eu") == "eu"


def test_a_match_id_that_is_not_one_is_refused_before_any_request():
    sess = valorant_api.Session(puuid="p", access="a", entitlements="e",
                                region="eu", shard="eu", version="v")
    with pytest.raises(valorant_api.Unavailable):
        valorant_api.details(sess, "../../etc/passwd")
    assert sess.pd == "https://pd.eu.a.pvp.net"
    assert sess.headers()["X-Riot-ClientVersion"] == "v"


# --------------------------------------- the record has to remember whose it is

def test_a_cached_record_says_which_player_it_was_fetched_for(tmp_path, monkeypatch):
    """WITHOUT THIS THE WHOLE ROUTE IS UNUSABLE in the normal case. The record
    does not name the local player, and the only thing that knows is the client
    the token came from -- which is closed by the time anything is clipped. So
    every match would line up and then be discarded for not knowing which of
    the ten players to read."""
    monkeypatch.setattr(vm, "CACHE", tmp_path)

    class FakeSession:
        puuid = ME

    monkeypatch.setattr(valorant_api, "session", lambda: FakeSession())
    monkeypatch.setattr(valorant_api, "history",
                        lambda s, limit=5: [{"MatchID": "abc12345"}])
    monkeypatch.setattr(valorant_api, "details", lambda s, mid: _match())

    assert vm.collect() == ["abc12345"]
    got = vm.cached()
    assert len(got) == 1
    # ...and it can be attributed with nothing running at all.
    monkeypatch.setattr(valorant_api, "session",
                        lambda: (_ for _ in ()).throw(
                            valorant_api.Unavailable("client closed")))
    assert vm.puuid_of(got[0]) == ME


def test_the_in_game_name_is_the_fallback_for_a_record_from_elsewhere(monkeypatch):
    m = _m()
    assert vm.puuid_of(m, "YuvaNeta") == ME
    # THE THIRD FALLBACK IS THE RUNNING CLIENT, so "no name matched" only
    # comes back empty when there is no client to ask. Without this the test
    # passed with VALORANT closed and failed with it open, which is a test
    # that depends on what the machine happens to be doing.
    monkeypatch.setattr(valorant_api, "session",
                        lambda: (_ for _ in ()).throw(
                            valorant_api.Unavailable("client closed")))
    assert vm.puuid_of(m, "nobody") == ""


def test_the_record_is_preferred_over_the_name():
    """A second account on the same machine would answer wrongly, and the name
    can be stale; what the record was fetched for cannot be either."""
    data = _match()
    data[vm.MINE] = MATE
    m = _m(data)
    assert vm.puuid_of(m, "YuvaNeta") == MATE


def test_a_record_that_cannot_be_attributed_is_reported_as_such(tmp_path, monkeypatch):
    """"no match data" and "a match record nobody can read" are different
    problems and must not look the same."""
    monkeypatch.setattr(vm, "CACHE", tmp_path)
    (tmp_path / "one.json").write_text(json.dumps(_match()), encoding="utf-8")
    got = vm.state(REC_STARTED, 1800.0)
    assert got["state"] == "have" and got["matches"] == 1
    assert "which player" in got.get("why", "")


# ============================================ reaching Riot at all
#
# FROM A REAL SESSION. 43 minutes of VALORANT recorded, and not one match
# record cached -- so the clips would have come off the screen with no round
# context, and nothing on the page said why. Two separate faults, both silent
# because collect() is deliberately quiet: it must never cost a run.

def test_the_shard_is_read_from_the_game_not_guessed_from_the_account():
    """THE ACCOUNT'S REGION DOES NOT DECIDE THE SHARD, and this cost a whole
    session's match record before anybody noticed.

    /riotclient/region-locale reports where the RIOT ACCOUNT lives. Measured on
    a real machine it said EUW -- and the player's 29 VALORANT matches were on
    ap; eu, na and kr all answered 404. A EUW account playing in Asia-Pacific
    is an ordinary thing, and no region-to-shard table can be right about it
    because the two are not related.

    The game writes the host it uses into its own log on every call, so that is
    what is read -- the same file client_version() already reads.
    """
    import tempfile

    from autostream import valorant_api as va

    log = ("URL [GET https://pd.ap.a.pvp.net/store/v1/wallet/abc]\n"
           "URL [GET https://glz-ap-1.ap.a.pvp.net/session/v1/sessions/abc]")
    f = Path(tempfile.mkdtemp()) / "ShooterGame.log"
    f.write_text(log, encoding="utf-8")
    assert va.shard_from_log(f) == ("ap", "ap")


def test_the_shard_is_found_from_a_pd_call_alone():
    """A log that has not made a glz call yet still names the shard."""
    import tempfile

    from autostream import valorant_api as va

    f = Path(tempfile.mkdtemp()) / "ShooterGame.log"
    f.write_text("URL [GET https://pd.eu.a.pvp.net/mmr/v1/players/x]",
                 encoding="utf-8")
    assert va.shard_from_log(f) == ("eu", "eu")


def test_no_log_is_not_an_error():
    """It falls back to the account's region -- a guess, but a better one than
    refusing to look at all."""
    from autostream import valorant_api as va

    assert va.shard_from_log(Path("Z:/nowhere/ShooterGame.log")) == ("", "")


def test_the_region_fallback_still_maps_the_known_ones():
    """Only reached when the log cannot be read."""
    from autostream import valorant_api as va

    for region, shard in (("euw", "eu"), ("tr", "eu"), ("br", "na"),
                          ("oce", "ap")):
        assert va.SHARDS.get(region) == shard, region
    for own in ("na", "eu", "ap", "kr"):
        assert va.SHARDS.get(own, own) == own, own

def test_every_shard_is_one_valorant_actually_serves():
    from autostream import valorant_api as va

    assert set(va.SHARDS.values()) <= {"na", "eu", "ap", "kr", "pbe"}


def test_the_request_says_what_it_is():
    """Cloudflare sits in front of pd.*.a.pvp.net and answers 403 error 1010,
    "browser_signature_banned", to a request with no User-Agent -- which is
    what urllib sends. Nothing to do with the tokens, which were fine.
    Measured: no User-Agent is 403 every time; with one the same call reaches
    Riot's own API and is answered by it."""
    from autostream import valorant_api as va

    s = va.Session(puuid="p", access="a", entitlements="e", region="euw",
                   shard="eu", version="release-13.05-shipping-11-5350494")
    h = s.headers()
    assert "User-Agent" in h, (
        "without one, every call is refused by the edge before Riot sees it")
    ua = h["User-Agent"]
    assert "Python" not in ua
    assert ua.startswith("ShooterGame/"), ua
    assert "13.05" in ua, "it has to carry the version the client is on"


def test_the_user_agent_survives_an_odd_version_string():
    """It is parsed out of a log line, so it must not raise on a shape nobody
    anticipated -- a failure here would take out every Riot call."""
    from autostream import valorant_api as va

    for version in ("release-13.05-shipping-11-5350494", "release-13.05",
                    "13.05", "", "weird"):
        s = va.Session(puuid="p", access="a", entitlements="e", region="eu",
                       shard="eu", version=version)
        assert s.user_agent().startswith("ShooterGame/")


# ------------------------------- the clock says WHICH match, not where it starts
#
# FROM A REAL MATCH. Sixteen of the player's kills aligned to within 1.41s, and
# the alignment was thrown away because the wall clock disagreed by 109s.
#
# match.started is when the match was CREATED. Agent select, loading and the
# first buy phase all happen after it, so the clock is systematically early --
# Counter-Strike's demos show the same lag, measured there at 130-149s. A
# twenty-second tolerance assumed the two meant the same instant.

def test_the_clock_may_lag_the_first_round_by_minutes():
    from autostream.clips import valorant_match as vm

    assert vm.DISAGREE_MAX >= 120, (
        "agent select alone is longer than this; a strong fingerprint would "
        "be refused on every match")
    # ...and still far below the gap between two matches, which is what the
    # check exists to catch.
    assert vm.DISAGREE_MAX < 20 * 60


def test_a_strong_fingerprint_survives_the_usual_lag(monkeypatch):
    """The exact numbers from the run that failed: fingerprint +159.3s,
    clock +50.3s, 109s apart."""
    from autostream.clips import cs2_demo, valorant_match as vm

    started = 1_000_000.0
    mine = [100.0 + 30 * i for i in range(12)]

    class M:
        id = "b645186b-x"
        started = 1_000_050.3          # the clock: match created

        def my_kill_times(self, puuid):
            return mine

    # detected at the fingerprint's offset, which is 109s later than the clock
    detected = [t + 159.3 for t in mine]
    s = vm.align(M(), "p", started, detected)
    assert s.ok, s.why
    assert abs(s.offset - 159.3) < 2.0, "it must keep the fingerprint's answer"


def test_a_fingerprint_that_disagrees_by_a_whole_match_is_still_refused():
    """The thing the check is for: two VALORANT games are half an hour apart,
    and cutting on the wrong one mis-places every clip."""
    from autostream.clips import valorant_match as vm

    started = 1_000_000.0
    mine = [100.0 + 30 * i for i in range(12)]

    class M:
        id = "wrongone"
        started = 1_000_050.0

        def my_kill_times(self, puuid):
            return mine

    detected = [t + 2400.0 for t in mine]      # forty minutes out
    s = vm.align(M(), "p", started, detected)
    assert not s.ok
    assert "disagree" in s.why
