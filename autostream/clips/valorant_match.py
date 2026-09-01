"""VALORANT's own record of a match, turned into kills and rounds.

The shape of this mirrors clips/cs2_demo.py deliberately: find the record that
belongs to this recording, work out where it sits on the video's timeline, and
then take every number from the record rather than from the screen. Everything
the pixel reader guesses at -- who was alive, whether a round was a clutch,
which round was the best one -- is a field here.

TWO WAYS TO LINE IT UP, AND THE CHEAP ONE IS USUALLY RIGHT
    A Counter-Strike demo has no wall-clock anchor, so cs2_demo fingerprints
    the kill timings to find its offset. A match record has `gameStartMillis`,
    which came from the same system clock that timestamped the recording -- so
    subtracting one from the other is already correct to within however long
    OBS took to start writing.

    That is not trusted on its own. The fingerprint runs as well and wins when
    it is confident, because it is a measurement of these two specific things
    rather than an assumption about two clocks. When the detector found too few
    kills to fingerprint, the wall clock stands -- with the residual reported
    either way, so a bad alignment can be refused instead of mis-cutting every
    clip in the run.

WHY THE RECORD IS CACHED
    The credentials come from the running Riot Client. Clips are cut hours
    later, so the record is fetched while the game is on and kept on disk --
    see valorant_api's module docstring.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .. import atomic, paths, valorant_api
from . import cs2_demo, rounds as rounds_mod

log = logging.getLogger("autostream.clips.valorant_match")

# The last reason given for each kind of failure, so a poll every two minutes
# does not write the same line to the log all evening.
_said: dict[str, str] = {}

# Beside the recordings, NOT in the application folder: a rebuild deletes
# that whole directory, and a match record cannot be fetched again once the
# client has closed. See paths.MATCHES_DIR.
CACHE = paths.MATCHES_DIR

# A record is only for this recording if the match started inside it. Slack at
# each end for the gap between OBS being told to record and the file's first
# frame, and for a match that was already running when recording began.
EDGE_SLACK = 90.0

# How far the fingerprint may disagree with the wall clock before the pair is
# treated as suspect rather than as a refinement.
DISAGREE_MAX = 20.0

# Riot's own name for what made a round notable. These are the values the
# client sends; the mapping is to the words this app already uses elsewhere so
# a Valorant clip and a Counter-Strike clip read the same way.
# Where the local player's id is kept inside a cached record. Prefixed because
# it is not one of Riot's fields and must not be mistaken for one.
MINE = "_autostream_puuid"

CEREMONIES = {
    "CeremonyAce": "ACE",
    "CeremonyTeamAce": "TEAM ACE",
    "CeremonyClutch": "CLUTCH",
    "CeremonyCloser": "CLOSER",
    "CeremonyFlawless": "FLAWLESS",
    "CeremonyThrifty": "THRIFTY",
}


@dataclass
class Match:
    """One cached match record."""
    path: Path
    data: dict

    @property
    def id(self) -> str:
        return str(self.info.get("matchId") or "")

    @property
    def info(self) -> dict:
        return self.data.get("matchInfo") or {}

    @property
    def started(self) -> float:
        """Epoch seconds when the match began."""
        return float(self.info.get("gameStartMillis") or 0) / 1000.0

    @property
    def seconds(self) -> float:
        return float(self.info.get("gameLengthMillis") or 0) / 1000.0

    @property
    def mode(self) -> str:
        return str(self.info.get("queueID") or self.info.get("gameMode") or "")

    @property
    def ranked(self) -> bool:
        return bool(self.info.get("isRanked"))

    def kills(self) -> list[dict]:
        return [k for k in (self.data.get("kills") or []) if isinstance(k, dict)]

    def my_kill_times(self, puuid: str) -> list[float]:
        """Seconds from match start, for kills by this player."""
        out = [float(k.get("gameTime") or 0) / 1000.0
               for k in self.kills() if k.get("killer") == puuid]
        return sorted(t for t in out if t > 0)


# --------------------------------------------------------------- the cache

def cache_dir() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE


def cached() -> list[Match]:
    """Every match record on disk, newest match first."""
    out: list[Match] = []
    try:
        files = sorted(cache_dir().glob("*.json"))
    except OSError:
        return out
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("matchInfo"):
            out.append(Match(f, data))
    out.sort(key=lambda m: -m.started)
    return out


def collect(limit: int = 5) -> list[str]:
    """Fetch any recent match not already cached. -> the ids added.

    Called while the game is running. Never raises: a match record that cannot
    be had costs the extra context for that match and nothing else.
    """
    try:
        sess = valorant_api.session()
    except valorant_api.Unavailable as e:
        # Said ONCE per reason, at a level that is actually visible. Logged at
        # debug it was invisible, and "Valorant has no match data" with nothing
        # in the log to say why is the shape of bug this codebase keeps
        # finding: see the demo search that returned nothing in silence.
        if _said.get("session") != str(e):
            _said["session"] = str(e)
            log.info("no Valorant match record available: %s", e)
        return []
    try:
        rows = valorant_api.history(sess, limit=limit)
    except valorant_api.Unavailable as e:
        log.info("could not read the Valorant match list: %s", e)
        return []
    added: list[str] = []
    for row in rows:
        mid = str(row.get("MatchID") or row.get("matchId") or "")
        if not mid:
            continue
        target = cache_dir() / f"{mid}.json"
        if target.exists():
            continue
        try:
            data = valorant_api.details(sess, mid)
        except valorant_api.Unavailable as e:
            log.info("could not read Valorant match %s: %s", mid[:8], e)
            continue
        # WHOSE RECORD THIS IS, written into it now. The record itself does
        # not say which player is the local one, and the only thing that knows
        # is the client the token came from -- which is closed by the time
        # anything is clipped. Without this the whole route was unusable in the
        # normal case: every match would line up and then be discarded for not
        # knowing which of the ten players to read.
        data[MINE] = sess.puuid
        try:
            # Cannot be fetched again once the client has closed, so a
            # half-written one is gone for good.
            atomic.write_json(target, data, indent=None)
        except OSError as e:
            log.warning("could not cache Valorant match %s: %s", mid[:8], e)
            continue
        added.append(mid)
        log.info("cached Valorant match %s (%s, %.0f min)", mid[:8],
                 (data.get("matchInfo") or {}).get("queueID", "?"),
                 float((data.get("matchInfo") or {}).get("gameLengthMillis") or 0)
                 / 60000)
    return added


def puuid_of(match: Match, name_hint: str = "") -> str:
    """Which player is the local one. -> a puuid, or "" if it cannot be told.

    Three ways, cheapest and most reliable first:

    1. What the record was fetched FOR, written into it at the time. This is
       the normal case and needs nothing running.
    2. The in-game name, if one is configured. Works for a record copied from
       somewhere else.
    3. The client, if it happens to be open. Last because it is a lockfile read
       and an HTTP call, and because a second account would answer wrongly.
    """
    mine = str(match.data.get(MINE) or "")
    if mine:
        return mine
    want = (name_hint or "").strip().lower()
    if want:
        for p in match.data.get("players") or []:
            if str(p.get("gameName") or "").strip().lower() == want:
                return str(p.get("subject") or "")
    try:
        return valorant_api.session().puuid
    except valorant_api.Unavailable:
        return ""


# ------------------------------------------------------------- the matching

def for_recording(started: float, seconds: float,
                  matches: list[Match] | None = None) -> list[Match]:
    """Cached matches that began inside this recording, oldest first."""
    if started <= 0:
        return []
    lo, hi = started - EDGE_SLACK, started + max(0.0, seconds) + EDGE_SLACK
    got = [m for m in (matches if matches is not None else cached())
           if m.started and lo <= m.started <= hi]
    got.sort(key=lambda m: m.started)
    return got


def align(match: Match, puuid: str, started: float,
          detected: list[float]) -> cs2_demo.Sync:
    """Where this match sits on the recording's timeline.

    `started` is when the recording began, in epoch seconds; `detected` are the
    kill times the pixel reader found, in seconds into the video.
    """
    mine = match.my_kill_times(puuid)
    clock = match.started - started
    if not mine:
        return cs2_demo.Sync(why="the record has no kills by this player")

    fitted = cs2_demo.align(mine, detected) if len(detected) >= 3 else \
        cs2_demo.Sync(total=len(mine), why="too few detected kills to fingerprint")
    if fitted.ok:
        drift = abs(fitted.offset - clock)
        if drift <= DISAGREE_MAX:
            log.info("match %s: fingerprint agrees with the clock to %.1fs; %s",
                     match.id[:8], drift, fitted.why)
            return fitted
        # The two disagree. That means either the clocks are not what they seem
        # or the fingerprint locked onto the wrong match, and cutting on either
        # would be a guess.
        log.warning("match %s: the fingerprint says %+.1fs and the clock says "
                    "%+.1fs -- %.0fs apart, so neither is trusted",
                    match.id[:8], fitted.offset, clock, drift)
        return cs2_demo.Sync(total=len(mine),
                             why=f"the fingerprint and the clock disagree by "
                                 f"{drift:.0f}s")
    if started > 0 and match.started > 0:
        log.info("match %s: lined up by the clock at %+.1fs (%s)",
                 match.id[:8], clock, fitted.why)
        return cs2_demo.Sync(offset=clock, scale=1.0, matched=0,
                             total=len(mine), ok=True,
                             why="lined up by the clock, not fingerprinted")
    return fitted


# -------------------------------------------------------- kills and rounds

def kills_from(match: Match, puuid: str, sync: cs2_demo.Sync) -> list[dict]:
    """Every kill by this player, on the recording's timeline."""
    out = []
    for k in match.kills():
        if k.get("killer") != puuid:
            continue
        at = sync.to_vod(float(k.get("gameTime") or 0) / 1000.0)
        if at <= 0:
            continue
        out.append({"time": round(at, 3), "end": round(at, 3),
                    "score": 1.0, "count": 1,
                    "round": int(k.get("round") or 0) + 1})
    out.sort(key=lambda k: k["time"])
    return out


def _alive_at(match: Match, kill: dict, puuid: str) -> tuple[int, int]:
    """How many of each side were alive at this kill. -> (mine, theirs)

    playerLocations is only sent for players who are ALIVE, which makes this a
    count rather than an inference -- the thing the pixel reader could never
    do. The victim of this kill is still listed, so they are discounted.
    """
    teams = {str(p.get("subject")): str(p.get("teamId") or "")
             for p in (match.data.get("players") or [])}
    me = teams.get(puuid, "")
    if not me:
        return 0, 0
    mine = theirs = 0
    victim = kill.get("victim")
    for loc in kill.get("playerLocations") or []:
        who = str(loc.get("subject") or "")
        if who == victim:
            continue
        side = teams.get(who, "")
        if not side:
            continue
        if side == me:
            mine += 1
        else:
            theirs += 1
    # The player themself is alive if they made the kill.
    if kill.get("killer") == puuid and not any(
            str(l.get("subject")) == puuid for l in kill.get("playerLocations") or []):
        mine += 1
    return mine, theirs


def rounds_from(match: Match, puuid: str, sync: cs2_demo.Sync) -> list:
    """Riot's round record, as the Round objects the planner already takes."""
    teams = {str(p.get("subject")): str(p.get("teamId") or "")
             for p in (match.data.get("players") or [])}
    me = teams.get(puuid, "")
    results = match.data.get("roundResults") or []
    by_round: dict[int, list[dict]] = {}
    for k in match.kills():
        by_round.setdefault(int(k.get("round") or 0), []).append(k)

    out = []
    for r in results:
        n = int(r.get("roundNum") or 0)
        kills = sorted(by_round.get(n, []),
                       key=lambda k: float(k.get("gameTime") or 0))
        if not kills:
            continue          # no timing to place the round on the video with
        first = sync.to_vod(float(kills[0].get("gameTime") or 0) / 1000.0)
        last = sync.to_vod(float(kills[-1].get("gameTime") or 0) / 1000.0)
        mine_k = [k for k in kills if k.get("killer") == puuid]
        my_deaths = sum(1 for k in kills if k.get("victim") == puuid)

        rd = rounds_mod.Round(
            number=n + 1,
            started=max(0.0, first - 20.0),
            ended=last + 6.0,
            score_before=(0, 0), score_after=(0, 0),
            half=1 if n < 12 else 2)
        rd.source = "match"
        rd.my_kills = len(mine_k)
        rd.my_deaths = my_deaths
        rd.kill_times = [sync.to_vod(float(k.get("gameTime") or 0) / 1000.0)
                         for k in mine_k]
        rd.won = (str(r.get("winningTeam") or "") == me) if me else None

        # The lowest my side ever got while the player was still in the round,
        # counted rather than inferred.
        low_mine, at_low = None, 0
        for k in kills:
            if k.get("victim") == puuid:
                break                     # once dead, it is not their stand
            mine_alive, theirs_alive = _alive_at(match, k, puuid)
            if mine_alive and (low_mine is None or mine_alive < low_mine):
                low_mine, at_low = mine_alive, theirs_alive
        rd.min_my_alive = low_mine
        if low_mine == 1 and at_low >= 1:
            rd.last_stand_at = rd.kill_times[0] if rd.kill_times else rd.started
            rd.enemies_at_last_stand = at_low

        cer = CEREMONIES.get(str(r.get("roundCeremony") or ""))
        if cer:
            rd.flags = list(rd.flags) + [cer]
        if r.get("plantRoundTime"):
            rd.flags = list(rd.flags) + ["PLANT"]
        if r.get("defuseRoundTime"):
            rd.flags = list(rd.flags) + ["DEFUSE"]
        if n >= 24:
            rd.flags = list(rd.flags) + ["OVERTIME"]
        out.append(rd)

    rounds_mod.label(out)
    # Riot's own word for what made a round notable outranks anything counted
    # here, so it leads the labels rather than joining them.
    for rd in out:
        named = [f for f in rd.flags if f in set(CEREMONIES.values())]
        extra = [f for f in ("OVERTIME",) if f in rd.flags]
        rd.labels = named + extra + [l for l in rd.labels
                                     if l not in named and l not in extra]
    log.info("%d round(s) from Valorant match %s: %d earned a label",
             len(out), match.id[:8], len(rounds_mod.highlights(out)))
    return out


def state(started: float, seconds: float,
          matches: list[Match] | None = None) -> dict:
    """Whether a match record is on hand for this recording, for the UI.

    `matches` is the cache, already read. Pass it when asking about more than
    one recording: reading every cached match once per recording is every
    match times every stream.
    """
    got = for_recording(started, seconds, matches)
    if got:
        nameless = [m for m in got if not str(m.data.get(MINE) or "")]
        return {"state": "have", "matches": len(got),
                "ids": [m.id[:8] for m in got],
                **({"why": f"{len(nameless)} of {len(got)} record(s) do not say "
                            f"which player you are"} if nameless else {})}
    if valorant_api.available():
        return {"state": "none", "matches": 0, "ids": [],
                "why": "no match record was cached while this was recorded"}
    return {"state": "none", "matches": 0, "ids": [],
            "why": valorant_api.why_not()}
