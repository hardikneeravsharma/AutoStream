"""Counter-Strike 2 match data, read from the demo Valve gives you.

WHY THIS EXISTS ALONGSIDE THE PIXEL DETECTORS
    Reading the screen can only ever see what the HUD draws. A demo is the
    server's own record, so it carries the things no detector can infer:

        thrusmoke      the kill went through smoke
        attackerblind  you were flashed when you got it
        assistedflash  someone flashed for you
        penetrated     wallbang    headshot / noscope / hitgroup / distance
        winner, reason why each round ended
        every player's kills, deaths and assists, exactly

    Measured on a real 152MB match: 116 kills parsed in 1.1 seconds, against
    220 seconds to scan the same match's video.

WHAT IT CANNOT DO ALONE
    A demo has no idea when your recording started. Demo time is the game
    clock; the video is wall clock from whenever OBS began. Everything here
    turns on `align`, and the rule there is that a bad alignment must REFUSE
    rather than quietly shift every clip in the match.

WHAT THE ROUND LAYER GETS OUT OF IT
    clips/rounds.py used to read all of this off the screen: the score by
    template-matching HUD digits, the alive counts beside them, and which side
    was the player's by correlating their deaths against those counters. Every
    one of those is exact here instead, and two things that were impossible
    become arithmetic:

        who was alive, per side, per second -- so 1vN is COUNTED, not inferred
        who won each round -- so streaks, streak-breakers and match point are
                              simply read off the list

    Rosters come from `parse_ticks` at each round's freeze-end tick, which is
    the one moment every player is alive and on their final side for that
    round. That is also how the side swap at half time is handled without
    looking for one: the roster is re-read every round, so a swap is just the
    next round's answer.

THE DEMO IS ALSO A MARKING SCHEME
    Once aligned it says exactly what the pixel detector got right. On the
    match this was built against, the card-tally detector scored 11 of 12
    kills inside the demo's span, missed one and invented two -- numbers there
    was previously no way to know.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("autostream.clips.cs2_demo")

# CS2 matchmaking demos are 64 tick. It is not in the header, so it is assumed
# -- but harmlessly: `align` fits a SCALE as well as an offset, so a wrong
# tickrate comes out as a rate correction instead of wrecking the sync. On the
# match this was built against the fitted scale was 1.000039, which is how we
# know 64 is right for it.
TICKRATE = 64.0

# How far a demo kill may sit from a detected one and still be the same kill.
# Measured residuals after fitting: 0.06-0.17s for ten of eleven pairs, and
# 1.15s for the second half of a double kill 1.3s apart, where the detector
# merges the two. The window has to clear that.
MATCH_TOL = 1.5
# Below this share of the demo's kills lining up, the alignment is not trusted.
# Refusing costs one match; a wrong offset silently mis-cuts every clip in it.
MIN_ALIGNED = 0.6
# Absolute floor on matched kills, independent of the share. With a windowed
# denominator a share can be computed from very few pairs, and "2 of 2" is a
# perfect score that means nothing at all.
MIN_MATCHED = 6
# Below this share of the demo, the recording is a sample of the match rather
# than a truncated copy of it, and the floor above applies.
WINDOW_MINORITY = 0.5
# Rate ratios tried while searching. Matchmaking demos are 64 tick and third
# party servers are often 128, so parsing at the wrong one doubles or halves
# every timestamp. A least-squares fit CANNOT rescue that -- it only runs after
# an offset has already matched, and at the wrong rate no offset matches more
# than a couple of pairs. So the rate is searched, not fitted.
RATES = (1.0, 2.0, 0.5)

# team_num as the demo reports it. In a live round only these two occur; 1 is
# the spectators and 0 is unassigned.
SIDES = {2: "T", 3: "CT"}

# The same two sides, spelled two different ways by two different fields:
# `round_end.winner` says "CT"/"T" and `attacker_team_name` says "CT"/
# "TERRORIST". Both are normalised to the short form on the way in, so asking
# "did my side win this round" is a string comparison rather than a lookup
# table at every call site.
TEAM_NAMES = {"TERRORIST": "T", "T": "T", "CT": "CT"}


@dataclass
class Kill:
    time: float                 # seconds of demo time
    round: int                  # 1-indexed, as the demo numbers them
    killer: str
    victim: str
    killer_side: str = ""       # "CT" | "T" -- normalised, see TEAM_NAMES
    victim_side: str = ""
    weapon: str = ""
    headshot: bool = False
    thrusmoke: bool = False
    blinded: bool = False       # the KILLER was flashed
    penetrated: bool = False
    noscope: bool = False
    assister: str = ""
    flash_assist: bool = False


@dataclass
class Round:
    number: int                 # 1-indexed
    start: float = 0.0          # round_start: freeze time begins
    # round_freeze_end: when the round actually goes live. This, not `start`,
    # is where a round clip should be allowed to open -- freeze time is the buy
    # menu, and cutting from it opens on twenty seconds of standing still.
    live: float = 0.0
    end: float = 0.0
    winner: str = ""            # "CT" | "T" -- a NAME, not the int it looks like
    # How it ended: "t_killed", "ct_killed", "bomb_defused", "target_bombed",
    # "target_saved". A STRING -- reading it as an int threw, and the guard
    # around that swallowed every round while the kills still looked fine.
    reason: str = ""

    @property
    def opens_at(self) -> float:
        return self.live or self.start


@dataclass
class Match:
    path: Path
    map_name: str = ""
    tickrate: float = TICKRATE
    kills: list[Kill] = field(default_factory=list)
    rounds: list[Round] = field(default_factory=list)
    # round number -> player -> "CT" | "T", read at each round's freeze end.
    teams: dict[int, dict[str, str]] = field(default_factory=dict)
    match_point: int | None = None     # the round match point was announced in
    warmup: int = 0                    # kills dropped for being warm-up

    def team_of(self, player: str, round_no: int) -> str:
        """Which side `player` was on in that round. "" when unknown.

        Exact round first, then the most recent EARLIER one that knows. Never
        later: the sides swap at half time, so carrying an answer backwards
        across the swap gets every round in the first half wrong -- the same
        bug clips/rounds.py has a whole function to avoid on the pixel path.
        """
        want = (player or "").strip().casefold()
        for n in sorted((n for n in self.teams if n <= round_no), reverse=True):
            for who, side in self.teams[n].items():
                if who.casefold() == want:
                    return side
        return ""

    def round_no(self, number: int) -> Round | None:
        for r in self.rounds:
            if r.number == number:
                return r
        return None

    def by(self, player: str) -> list[Kill]:
        p = (player or "").strip().casefold()
        return [k for k in self.kills if k.killer.casefold() == p]

    def deaths_of(self, player: str) -> list[Kill]:
        p = (player or "").strip().casefold()
        return [k for k in self.kills if k.victim.casefold() == p]

    def players(self) -> list[str]:
        """Everyone who got a kill, most first."""
        seen: dict[str, int] = {}
        for k in self.kills:
            seen[k.killer] = seen.get(k.killer, 0) + 1
        return sorted(seen, key=lambda n: -seen[n])


def map_of(path: Path) -> str:
    """The map, straight out of the demo header -- no parse needed.

    Cheap enough to run over a whole replays folder, which is what makes
    picking the right demo for a recording practical.
    """
    try:
        head = Path(path).open("rb").read(1024)
    except OSError:
        return ""
    m = re.search(rb"(de_[a-z0-9_]+)", head)
    return m.group(1).decode() if m else ""


def _rows(parser, event: str, **kw) -> list[dict]:
    """One event as plain dicts, tolerating a parser that lacks a keyword.

    `player=[...]` is how demoparser2 asks for a per-player property on an
    event, and it is the only way to get each side's name onto a kill. Older
    builds do not take it, and a TypeError there must not cost us the event
    entirely -- the roster falls back to `parse_ticks`, and failing that to the
    sides named on the kills.
    """
    try:
        return _records(parser.parse_event(event, **kw))
    except TypeError:
        try:
            return _records(parser.parse_event(event))
        except Exception as e:                         # pragma: no cover
            log.warning("could not read %s: %s", event, e)
            return []
    except Exception as e:                             # pragma: no cover
        log.warning("could not read %s: %s", event, e)
        return []


def _records(got) -> list[dict]:
    """Rows out of whatever demoparser2 returned for an event.

    It answers a DataFrame when the event occurred and a plain LIST when it
    did not. Calling .to_dict on the list raises, and the old code logged that
    as "could not read round_announce_match_point" -- on every parse of every
    demo without a match point, which is most of them. A match that never went
    to a match point is not a failure to read one.
    """
    if got is None:
        return []
    if isinstance(got, list):
        return [r for r in got if isinstance(r, dict)]
    to_dict = getattr(got, "to_dict", None)
    if to_dict is None:
        return []
    return to_dict("records")


def _flag(row: dict, key: str) -> bool:
    v = row.get(key)
    return bool(v) and str(v).lower() not in ("0", "false", "none", "nan")


def _name(row: dict, key: str) -> str:
    v = str(row.get(key) or "")
    return "" if v in ("None", "nan") else v


def _side(row: dict, key: str) -> str:
    return TEAM_NAMES.get(_name(row, key).upper(), "")


def _num(value, default: float = 0.0) -> float:
    """A number out of a parsed demo row, whatever the parser put there.

    THE NaN TRAP. parse_ticks comes back through pandas, and a missing cell is
    float("nan") rather than None. NaN is TRUTHY, so `int(row.get(k) or 0)`
    does not fall back -- it reaches int(nan) and raises "cannot convert float
    NaN to integer". That killed the whole parse of a perfectly good demo, and
    with it the entire demo path for that recording: the rounds then had to be
    read off the screen, which is the worse source this code exists to avoid.
    """
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    # NaN is the only float that is not equal to itself.
    return default if out != out else out


def _number(row: dict, index: int) -> int:
    """Which round a row belongs to, 1-indexed.

    Two different columns say it depending on the event -- `round` on
    round_start and round_end, `total_rounds_played` on the others -- and they
    are offset from each other by one. Both are preferred to the row's
    position, which is only right while nothing is missing.
    """
    for key, add in (("round", 0), ("total_rounds_played", 1)):
        v = row.get(key)
        if v is None:
            continue
        try:
            return int(v) + add
        except (TypeError, ValueError):
            continue
    return index + 1


def _read_rounds(parser, tickrate: float) -> list[Round]:
    """round_start / round_freeze_end / round_end -> one Round each."""
    def secs(row):
        return _num(row.get("tick")) / tickrate

    out: list[Round] = []
    for i, row in enumerate(_rows(parser, "round_start",
                                  other=["total_rounds_played"])):
        out.append(Round(number=_number(row, i), start=secs(row)))
    by_no = {r.number: r for r in out}

    for i, row in enumerate(_rows(parser, "round_end",
                                  other=["total_rounds_played"])):
        r = by_no.get(_number(row, i)) or (out[i] if i < len(out) else None)
        if r is None:
            continue
        r.end = secs(row)
        r.winner = TEAM_NAMES.get(_name(row, "winner").upper(), "")
        r.reason = _name(row, "reason")

    # Freeze end is matched on the round NUMBER, not on position: it fires once
    # per round, but the count does not have to agree with round_start's when a
    # demo is truncated, and pairing those two by position would then shift
    # every round's opening moment by one.
    for i, row in enumerate(_rows(parser, "round_freeze_end",
                                  other=["total_rounds_played"])):
        r = by_no.get(_number(row, i))
        if r is not None:
            r.live = secs(row)
    return out


def _rosters(parser, kills: list["Kill"]) -> dict[int, dict[str, str]]:
    """Which side every player was on, per round.

    Read at each round's FREEZE END -- the one tick in a round where everybody
    is alive and on the side they will play it on. That makes the half-time
    swap a non-event: the roster is simply re-read, and the next round's answer
    is the new one. No reversal to spot, which is the whole of `rounds.halves()`
    on the pixel path.

    Falls back to the sides named on the kills themselves. That covers a parser
    with no `parse_ticks`, but it only knows players who killed or died -- a
    round the local player sat out has no roster from it at all -- so it is
    second choice rather than first.
    """
    out: dict[int, dict[str, str]] = {}
    frees = _rows(parser, "round_freeze_end", other=["total_rounds_played"])
    want = {int(r["tick"]): _number(r, i)
            for i, r in enumerate(frees) if r.get("tick") is not None}
    if want:
        try:
            rows = parser.parse_ticks(["team_num"],
                                      ticks=sorted(want)).to_dict("records")
        except Exception as e:                         # pragma: no cover
            log.info("no per-round rosters from parse_ticks (%s); using the "
                     "sides named on the kills instead", e)
            rows = []
        for row in rows:
            n = want.get(int(_num(row.get("tick"), -1)))
            side = SIDES.get(int(_num(row.get("team_num"))))
            who = str(row.get("name") or "")
            if n and side and who and who != "nan":
                out.setdefault(n, {})[who] = side

    for k in kills:
        seen = out.setdefault(k.round, {})
        for who, side in ((k.killer, k.killer_side), (k.victim, k.victim_side)):
            if who and side:
                seen.setdefault(who, side)
    return {n: t for n, t in out.items() if t}


def parse(path: Path, tickrate: float = TICKRATE) -> Match:
    """Read one .dem into normalised events."""
    try:
        from demoparser2 import DemoParser
    except ImportError as e:                       # pragma: no cover
        raise RuntimeError(
            "Reading CS2 demos needs the demoparser2 package. Install it "
            "with:  pip install demoparser2") from e

    path = Path(path)
    p = DemoParser(str(path))
    try:
        head = p.parse_header()
    except Exception:                              # pragma: no cover
        head = {}
    rows = _rows(p, "player_death", player=["team_name"],
                 other=["total_rounds_played", "is_warmup_period"])

    kills: list[Kill] = []
    warmup = 0
    dropped = 0
    for row in rows:
        # WARM-UP KILLS ARE NOT KILLS. They arrive before round 1 with exactly
        # the same shape as everything else, so counting them inflates the
        # match total and hands the fingerprint sync a pile of kills that the
        # recording may not even cover.
        if _flag(row, "is_warmup_period"):
            warmup += 1
            continue

        killer = _name(row, "attacker_name")
        if not killer:
            continue          # the world killed them: a fall, the bomb, a team
        # Same NaN trap as the rosters, but worse if it got through: a NaN
        # tick does not raise here, it produces a NaN TIME, and a clip planned
        # at an undefined position fails much later with nothing pointing
        # back. A kill whose tick cannot be read is dropped instead -- the
        # detector's own timings still cover it.
        tick = _num(row.get("tick"), -1.0)
        if tick < 0:
            dropped += 1
            continue
        kills.append(Kill(
            time=tick / tickrate,
            round=int(_num(row.get("total_rounds_played"))) + 1,
            killer=killer, victim=_name(row, "user_name"),
            killer_side=_side(row, "attacker_team_name"),
            victim_side=_side(row, "user_team_name"),
            weapon=_name(row, "weapon"),
            headshot=_flag(row, "headshot"),
            thrusmoke=_flag(row, "thrusmoke"),
            blinded=_flag(row, "attackerblind"),
            penetrated=_flag(row, "penetrated"),
            noscope=_flag(row, "noscope"),
            assister=_name(row, "assister_name"),
            flash_assist=_flag(row, "assistedflash"),
        ))
    kills.sort(key=lambda k: k.time)
    if warmup:
        log.info("dropped %d warm-up kill(s) from %s", warmup, path.name)
    if dropped:
        log.warning("%d kill(s) in %s had no readable tick and were skipped",
                    dropped, path.name)

    rounds = _read_rounds(p, tickrate)
    teams = _rosters(p, kills)
    mp = _rows(p, "round_announce_match_point", other=["total_rounds_played"])
    match_point = _number(mp[0], 0) if mp else None

    return Match(path=path, map_name=str(head.get("map_name") or map_of(path)),
                 tickrate=tickrate, kills=kills, rounds=rounds, teams=teams,
                 match_point=match_point, warmup=warmup)


# Where CS2 puts a demo you download from the Watch tab, relative to a Steam
# library root. There is no registry key for it and no setting -- the game
# writes there and nowhere else.
REPLAYS = ("steamapps", "common", "Counter-Strike Global Offensive", "game",
           "csgo", "replays")


def demo_folder(hint: str = "") -> Path | None:
    """Where to look for demos. `hint` wins if it is a real directory.

    Steam library roots come from catalog._steam_roots(), the same registry
    lookup the app already uses to find installed games -- so a library on a
    second drive is covered without asking.
    """
    if hint:
        p = Path(hint).expanduser()
        return p if p.is_dir() else None
    try:
        from .. import catalog
        roots = catalog._steam_roots()
    except Exception:                              # pragma: no cover
        roots = []
    for root in roots:
        p = Path(root).joinpath(*REPLAYS)
        if p.is_dir():
            return p
    return None


def audit(demo_times: list[float], vod_times: list[float], sync: "Sync",
          *, tol: float = MATCH_TOL) -> dict:
    """How the detector scored, now that there is a right answer to mark against.

    Only kills inside the demo's own span count. A recording routinely holds a
    second match the demo knows nothing about, and calling those false
    positives would mark the detector down for being right.
    """
    if not demo_times or not sync.ok:
        return {}
    lo, hi = sync.to_vod(min(demo_times)), sync.to_vod(max(demo_times))
    inside = [v for v in vod_times if lo - tol <= v <= hi + tol]
    hit = sum(1 for d in demo_times
              if any(abs(sync.to_vod(d) - v) <= tol for v in inside))
    return {
        "demo_kills": len(demo_times),
        "detected": len(vod_times),
        "detected_in_span": len(inside),
        "matched": hit,
        "missed": len(demo_times) - hit,
        "invented": max(0, len(inside) - hit),
        "worst_error": round(sync.residual, 2),
    }


@dataclass
class Sync:
    """How demo time maps onto the recording."""
    offset: float = 0.0
    scale: float = 1.0
    matched: int = 0
    total: int = 0
    residual: float = 0.0       # worst |error| over the matched pairs
    ok: bool = False
    why: str = "not attempted"

    def to_vod(self, t: float) -> float:
        return self.scale * t + self.offset

    @property
    def share(self) -> float:
        return self.matched / self.total if self.total else 0.0


def align(demo_times: list[float], vod_times: list[float], *,
          tol: float = MATCH_TOL, min_share: float = MIN_ALIGNED) -> Sync:
    """Find where a demo sits inside a recording, from the kills alone.

    Not a search over plausible offsets: every difference between a demo kill
    and a detected kill IS a candidate offset, and the right one is whichever
    lines up the most pairs. That makes it a FINGERPRINT match on the pattern
    of kills rather than a guess anchored on one event -- so it survives a
    missed detection, and it handles the ordinary case of OBS being started
    after the match had already begun.

    A RATE is searched alongside the offset, because a demo parsed at the wrong
    tickrate has every timestamp doubled or halved and no single offset then
    fits. The least-squares afterwards only polishes drift.

    The worst residual is reported so a bad alignment can be refused rather
    than silently mis-cutting every clip.
    """
    if len(demo_times) < 3 or len(vod_times) < 3:
        return Sync(total=len(demo_times), why="too few kills to align")

    demo, vod = sorted(demo_times), sorted(vod_times)
    best_off, best_rate, best_hits = 0.0, 1.0, -1
    for rate in RATES:
        for d in demo:
            for v in vod:
                off = v - d * rate
                hits = sum(1 for x in demo
                           if any(abs(x * rate + off - y) <= tol for y in vod))
                if hits > best_hits:
                    best_off, best_rate, best_hits = off, rate, hits

    pairs = []
    for x in demo:
        near = [y for y in vod if abs(x * best_rate + best_off - y) <= tol]
        if near:
            pairs.append((x, min(near,
                                 key=lambda y: abs(x * best_rate + best_off - y))))

    # THE DENOMINATOR IS THE WINDOW, NOT THE WHOLE DEMO.
    #
    # A recording rarely covers a whole match: OBS is started late, stopped
    # early, or -- the case this exists for -- only a few minutes of it have
    # been scanned so far. Counting demo kills that fall OUTSIDE what was
    # looked at marks the alignment down for the scan's coverage rather than
    # for being wrong, and that is what forced every job to scan the entire
    # recording before a demo could be trusted.
    #
    # So only demo kills whose mapped time lands inside the scanned span can
    # count against us. That makes a partial scan a valid fingerprint, which
    # is the whole optimisation.
    lo, hi = vod[0] - tol, vod[-1] + tol
    in_window = [x for x in demo if lo <= x * best_rate + best_off <= hi]

    # "Windowed" means judging the demo from a MINORITY of it -- a deliberate
    # partial scan. A recording that merely starts late or stops early still
    # covers most of the match, and that is the ordinary case the old
    # behaviour was written for; treating it as a partial scan would demand
    # extra evidence for nothing.
    windowed = 0 < len(in_window) < len(demo) * WINDOW_MINORITY
    s = Sync(offset=best_off, scale=best_rate,
             matched=len(pairs), total=len(in_window) or len(demo))

    # The absolute floor applies ONLY when the window actually narrowed the
    # denominator. A share computed from few pairs is easy to hit by luck --
    # two out of two is a perfect score and means nothing -- so a partial scan
    # has to clear a real count as well. A demo fully inside the recording is
    # judged exactly as it always was, floor and all left out of it, because
    # a genuinely short match is not a suspicious one.
    if windowed and s.matched < MIN_MATCHED:
        s.why = (f"only {s.matched} kill(s) line up in the part scanned so far "
                 f"-- is this the right match?")
        return s
    if s.share < min_share:
        s.why = (f"only {s.matched} of {s.total} demo kills line up with the "
                 f"recording -- is this the right match?")
        return s

    n = len(pairs)
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    den = sum((x - mx) ** 2 for x, _ in pairs)
    if den:
        s.scale = sum((x - mx) * (y - my) for x, y in pairs) / den
    s.offset = my - s.scale * mx
    s.residual = max(abs(y - s.to_vod(x)) for x, y in pairs)
    s.ok = True
    s.why = (f"{s.matched} of {s.total} kills aligned, worst error "
             f"{s.residual:.2f}s")
    return s


def identify(match: Match, vod_times: list[float],
             **kw) -> tuple[str, "Sync"]:
    """Which player in the demo is the one holding the camera?

    Worked out rather than configured. The pixel detectors only ever report the
    LOCAL player's kills, so the demo player whose kill pattern lines up with
    them is the local player -- and nobody else's will, because two players'
    kill timings do not coincide across a whole match by accident.

    So the demo path needs no in-game name either, which is the same bar the
    Valorant bar detector already meets.
    """
    best: tuple[str, Sync] = ("", Sync(why="no player matched"))
    for who in match.players():
        got = align([k.time for k in match.by(who)], vod_times, **kw)
        if got.ok and got.matched > best[1].matched:
            best = (who, got)
    return best


def newest_demo_time(folder: Path) -> float | None:
    """When the most recent demo was written. -> None if there are none.

    Cheap: a directory listing, no parsing. Used to decide whether looking is
    worth anything at all -- a demo cannot record a match played after it.
    """
    try:
        dems = list(Path(folder).glob("*.dem"))
    except OSError:
        return None
    return max((p.stat().st_mtime for p in dems), default=None)


def demo_state(folder, started: float, duration: float = 0.0) -> dict:
    """What Counter-Strike has for this recording. -> {state, file}.

    Three answers, not two, because they need different things done:

        have    the .dem is on disk and the clip run will use it
        listed  a .dem.info is there and the .dem is not -- the match is in
                your history and the download has not finished. Clicking
                Download again is the fix, and "no demo" would send somebody
                looking for a match that is already listed
        none    nothing for this recording at all

    Counter-Strike writes the .info when the match appears in the list and the
    .dem when the download completes -- a couple of minutes apart on a real
    one. Five .info files with no .dem is a download that never landed, which
    is exactly what one user hit while believing they had downloaded it.

    A FILE'S TIMESTAMP IS WHEN IT WAS DOWNLOADED, NOT WHEN THE MATCH WAS
    PLAYED. This first shipped with a twelve-hour window after the recording,
    which assumed people download demos promptly. They do not: a demo fetched
    forty-nine hours after the match was reported as absent while sitting on
    disk, twice, to somebody who had just downloaded it.

    So the only bound is the lower one, which is real -- a demo cannot be
    downloaded before its match was played. That over-reports on an old
    recording when newer demos exist, and that is the right way round to be
    wrong: a hopeful "there may be one" costs a twelve-minute probe that then
    falls back, while a wrong "none" costs somebody re-downloading a file they
    already have. The alignment is what actually decides.
    """
    out = {"state": "none", "file": None}
    if not folder or not started:
        return out
    try:
        entries = list(Path(folder).glob("*.dem")) + list(Path(folder).glob("*.dem.info"))
    except OSError:
        return out
    best_dem, best_dem_at = None, 0.0
    listed = False
    for f in entries:
        try:
            when = f.stat().st_mtime
        except OSError:
            continue
        if when < started:
            continue                    # written before the match was played
        if f.name.endswith(".dem.info"):
            listed = True
        elif when > best_dem_at:
            best_dem, best_dem_at = f.name, when
    if best_dem:
        return {"state": "have", "file": best_dem}
    if listed:
        return {"state": "listed", "file": None}
    return out


def pick_demo(folder: Path, vod_times: list[float], *,
              newest: int = 12) -> tuple[Match | None, str, "Sync"]:
    """Choose which demo in a folder belongs to a recording, by fingerprint.

    Cheap enough to be automatic: the map comes from the header without a
    parse, and only the newest few are parsed at all. Returns the best match
    along with who the local player turned out to be.
    """
    folder = Path(folder)
    dems = sorted(folder.glob("*.dem"), key=lambda p: -p.stat().st_mtime)
    best: tuple[Match | None, str, Sync] = (None, "", Sync(why="no demo fits"))
    for p in dems[:newest]:
        try:
            m = parse(p)
        except Exception as e:                     # pragma: no cover
            log.warning("could not parse %s: %s", p.name, e)
            continue
        who, s = identify(m, vod_times)
        # A SHARE IS NOT ENOUGH WHEN CHOOSING BETWEEN DEMOS. align() judges one
        # candidate on its own terms, and a player with seven kills in a demo
        # needs only five to clear 0.6 -- so a demo from two days earlier was
        # accepted for a recording it had nothing to do with, on five
        # coincidental timings out of seven. A wrong demo does not fail
        # loudly: it mis-cuts every clip in the run.
        #
        # So the CHOICE demands a real count as well. align stays permissive,
        # because it is also used to audit a demo already known to be right.
        if s.ok and s.matched < MIN_MATCHED:
            log.info("%s lines up on only %d kill(s) -- too few to trust",
                     p.name, s.matched)
            continue
        if s.ok and s.matched > best[2].matched:
            best = (m, who, s)
        # Stop looking once a demo accounts for nearly all of its own kills.
        # A whole match's timings lining up is not a coincidence, and parsing
        # the rest of the folder to confirm it costs a second and a half each.
        if best[2].ok and best[2].share >= 0.95:
            break
    return best
