"""Read VALORANT's own record of a match, from the running Riot Client.

WHY THIS EXISTS
    Valorant clips were cut entirely from pixels: the kill feed read off the
    screen, seven minutes of scanning for a hundred-minute recording, and no
    way to know who was alive -- so "clutch", "best round" and "overtime" were
    out of reach and double kills were counted from feed rows that jitter.

    The game knows all of it. Riot's own client fetches a full match record
    after every game: every kill with its time from match start, every round
    with its result and its CEREMONY (Riot's own word for ace, flawless,
    clutch), the plant and defuse times, and each player's position at the
    moment of every kill -- which is who was alive, exactly.

WHAT THIS IS NOT
    Not a third-party service. The token comes from the Riot Client running on
    this machine, the request goes to Riot, and nothing about the player leaves
    the machine except to Riot itself. No API key, no account name sent
    anywhere, nothing stored but the match JSON.

THE ONE CONSTRAINT
    The Riot Client has to be running, because the lockfile it writes is where
    the credentials come from. Clips are usually cut hours later, so this is
    called WHILE THE GAME IS ON -- AutoStream is already running then -- and the
    match record is cached beside the recording. By the time anything is being
    clipped, the answer is on disk. That is the same shape as Counter-Strike,
    where the .dem is written by the game and read later.

UNDOCUMENTED ON PURPOSE
    These endpoints are the ones the client uses internally. They are not a
    public API, they are not promised, and they change on patch days. Every
    call here is therefore allowed to fail without costing anything: the pixel
    reader stays as the fallback and is used whenever this returns nothing.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("autostream.valorant_api")

LOCKFILE = Path(os.environ.get("LOCALAPPDATA", "")) / \
    "Riot Games/Riot Client/Config/lockfile"
GAME_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / \
    "VALORANT/Saved/Logs/ShooterGame.log"

# The client sends this, base64-encoded, on every request to pd.*. It is a
# fixed blob rather than this machine's real numbers: the value below is the
# documented one that works, and inventing a truthful-looking one has no
# benefit and one obvious failure mode.
PLATFORM = base64.b64encode(json.dumps({
    "platformType": "PC",
    "platformOS": "Windows",
    "platformOSVersion": "10.0.19042.1.256.64bit",
    "platformChipset": "Unknown",
}, separators=(",", ":")).encode()).decode()

# Some regions play on another region's servers, so the host is not just the
# region lowercased.
#
# AND THE CLIENT DOES NOT ANSWER IN VALORANT REGIONS. /riotclient/region-locale
# is a RIOT-wide endpoint, so it replies with the account's Riot region -- which
# for Europe is a League of Legends code. Measured on a real client:
#
#     {"region": "EUW", "webRegion": "EUW"}
#
# Both fields, so there is no better one to read. Valorant's European shard is
# "eu", and "pd.euw.a.pvp.net" does not resolve -- which is exactly what
# happened: a 43-minute session cached no match record at all, every poll
# failing with getaddrinfo, and the clips lost their round context with nothing
# on screen to say why.
#
# So the League regions are mapped onto the four shards Valorant actually has.
# Anything still unlisted is assumed to be its own shard, which is true of
# na, eu, ap and kr themselves.
SHARDS = {
    # Europe, Middle East, Russia and Türkiye all play on the EU shard.
    "euw": "eu", "eune": "eu", "eun": "eu", "ru": "eu", "tr": "eu",
    "me": "eu",
    # The Americas.
    "latam": "na", "lan": "na", "las": "na", "br": "na",
    # Asia-Pacific. Korea has its own shard; Japan and Oceania do not.
    "jp": "ap", "oce": "ap", "oc1": "ap", "sg": "ap", "ph": "ap",
    "th": "ap", "tw": "ap", "vn": "ap", "id": "ap",
    "pbe": "pbe",
}

TIMEOUT = 15.0
HISTORY_MAX = 20          # how many recent matches to consider


class Unavailable(RuntimeError):
    """The client is not running, or its record cannot be reached."""


@dataclass
class Session:
    """Everything needed to ask Riot about this player's matches."""
    puuid: str
    access: str
    entitlements: str
    region: str
    shard: str
    version: str

    @property
    def pd(self) -> str:
        return f"https://pd.{self.shard}.a.pvp.net"

    def user_agent(self) -> str:
        """What the game calls itself. `release-13.05-shipping-11-5350494`
        becomes `ShooterGame/13.05.11`, which is the shape the client sends."""
        ver = self.version.replace("release-", "").split("-shipping-")[0]
        build = self.version.rsplit("-", 1)[-1] if "-" in self.version else ""
        return (f"ShooterGame/{ver}.{build} "
                f"Windows/10.0.19042.1.256.64bit").strip()

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access}",
            "X-Riot-Entitlements-JWT": self.entitlements,
            "X-Riot-ClientPlatform": PLATFORM,
            "X-Riot-ClientVersion": self.version,
            # WITHOUT THIS, CLOUDFLARE REFUSES THE REQUEST BEFORE RIOT SEES IT.
            # urllib announces itself as "Python-urllib/3.12", and the edge in
            # front of pd.*.a.pvp.net answers 403 with error 1010,
            # "browser_signature_banned" -- nothing to do with the tokens,
            # which are fine. Measured: with no User-Agent every call is 403;
            # with this one the same call reaches Riot's own API and is
            # answered by it.
            "User-Agent": self.user_agent(),
            "Accept": "application/json",
        }


def _lockfile() -> tuple[int, str]:
    """-> (port, password). Raises Unavailable when the client is not running."""
    if not LOCKFILE.is_file():
        raise Unavailable("the Riot Client is not running (no lockfile)")
    try:
        parts = LOCKFILE.read_text(encoding="utf-8").strip().split(":")
        # name:pid:port:password:protocol
        return int(parts[2]), parts[3]
    except (OSError, IndexError, ValueError) as e:
        raise Unavailable(f"could not read the lockfile: {e}") from e


def _local(path: str) -> dict:
    """One call to the client's own API on localhost."""
    port, password = _lockfile()
    auth = base64.b64encode(f"riot:{password}".encode()).decode()
    req = urllib.request.Request(
        f"https://127.0.0.1:{port}{path}",
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
    # The local server presents a self-signed certificate for 127.0.0.1. There
    # is nothing to verify it against and nothing in the middle to protect it
    # from, so verification is off for THIS host only.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Unavailable(f"the client did not answer {path}: {e}") from e


def client_version(log_file: Path | None = None) -> str:
    """The running client's version string, read out of its own log.

    Riot rejects a request whose version is not the current one. The value can
    be had from a third-party version API, but the game writes it to a log on
    this machine on every launch, so there is no reason to ask anyone.
    """
    f = log_file or GAME_LOG
    if not f.is_file():
        raise Unavailable("no VALORANT log to read the client version from")
    try:
        text = f.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        raise Unavailable(f"could not read the VALORANT log: {e}") from e
    # e.g. "CI server version: release-11.00-shipping-8-3320046"
    m = re.search(r"CI server version:\s*(\S+)", text)
    if m:
        return _branch_version(m.group(1))
    m = re.search(r"Branch:\s*(\S+)", text)
    if m:
        return _branch_version(m.group(1))
    raise Unavailable("the VALORANT log does not name a client version")


def _branch_version(raw: str) -> str:
    """release-11.00-shipping-8-3320046 -> release-11.00-shipping-8-3320046

    The header wants the branch string as the log writes it, except that the
    log's form has the build number last and the header wants it in the same
    order -- so this exists to normalise the one difference that does turn up:
    a trailing newline or quote.
    """
    return raw.strip().strip('"').strip()


def session() -> Session:
    """Authenticate against the running client. Raises Unavailable."""
    tok = _local("/entitlements/v1/token")
    puuid = str(tok.get("subject") or "")
    access = str(tok.get("accessToken") or "")
    ent = str(tok.get("token") or "")
    if not (puuid and access and ent):
        raise Unavailable("the client did not return a usable token")
    region, shard = _region()
    return Session(puuid=puuid, access=access, entitlements=ent,
                   region=region, shard=shard, version=client_version())


def shard_from_log(log_file: Path | None = None) -> tuple[str, str]:
    """The region and shard the GAME is actually talking to. ("", "") if unknown.

    THE ACCOUNT'S REGION DOES NOT DECIDE THE SHARD. /riotclient/region-locale
    reports where the RIOT ACCOUNT lives, which for a European account is a
    League of Legends code -- and a player can perfectly well hold a EUW
    account and play VALORANT in Asia-Pacific. Measured on a real machine:

        region-locale says   EUW
        match history is on  ap        (29 matches; eu, na and kr all 404)

    No mapping from region to shard can be right about that, because the two
    are not related. The game writes the host it uses into its own log on
    every call, so it is read from there -- the same file, and the same
    reasoning, as client_version() above.
    """
    f = log_file or GAME_LOG
    try:
        text = f.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "", ""
    # "https://glz-ap-1.ap.a.pvp.net/..." gives both at once.
    m = re.search(r"glz-([a-z0-9]+)-\d+\.([a-z0-9]+)\.a\.pvp\.net", text)
    if m:
        return m.group(1), m.group(2)
    # Otherwise the shard alone, off any pd call.
    m = re.search(r"https://pd\.([a-z0-9]+)\.a\.pvp\.net", text)
    if m:
        return m.group(1), m.group(1)
    return "", ""


def _region() -> tuple[str, str]:
    # What the game is doing beats what the account says, every time.
    region, shard = shard_from_log()
    if shard:
        return region or shard, shard
    got = _local("/riotclient/region-locale")
    region = str(got.get("region") or got.get("webRegion") or "").lower()
    if not region:
        raise Unavailable("the client did not say which region this account is in")
    return region, SHARDS.get(region, region)


def _remote(sess: Session, path: str) -> dict:
    req = urllib.request.Request(sess.pd + path, headers=sess.headers())
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 400 here almost always means the version header is stale, which
        # happens the moment the game patches. Worth saying, because the
        # symptom is otherwise "Valorant stopped having match data".
        hint = " (the client version may be stale)" if e.code == 400 else ""
        raise Unavailable(f"Riot answered {e.code} for {path}{hint}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Unavailable(f"could not reach Riot for {path}: {e}") from e


def history(sess: Session, *, limit: int = HISTORY_MAX) -> list[dict]:
    """This player's recent matches, newest first.

    -> [{"MatchID": ..., "GameStartTime": ms, "QueueID": ...}, ...]
    """
    got = _remote(sess, f"/match-history/v1/history/{sess.puuid}"
                        f"?startIndex=0&endIndex={max(1, int(limit))}")
    rows = got.get("History") or got.get("history") or []
    return [r for r in rows if isinstance(r, dict)]


def details(sess: Session, match_id: str) -> dict:
    """The full record of one match."""
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", match_id or ""):
        raise Unavailable(f"that is not a match id: {match_id!r}")
    return _remote(sess, f"/match-details/v1/matches/{match_id}")


def available() -> bool:
    """Whether a match record could be fetched right now."""
    try:
        _lockfile()
        return GAME_LOG.is_file()
    except Unavailable:
        return False


def why_not() -> str:
    try:
        _lockfile()
    except Unavailable as e:
        return str(e)
    if not GAME_LOG.is_file():
        return "VALORANT has not run on this machine, so its log is not there"
    return ""
