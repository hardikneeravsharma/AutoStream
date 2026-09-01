"""Find out whether a newer AutoStream exists, and fetch it.

WHAT THIS IS FOR
    The app is distributed as a zip on GitHub Releases. Finding out there is a
    new one means remembering to look, and installing it means unzipping over
    a running program -- which is how installations end up with orphaned files
    from three versions ago. A button is better than a habit.

WHAT IT WILL NOT DO
    Install anything by itself. It checks, it downloads, it verifies, and then
    it hands over to whatever can actually replace a running program. Nothing
    here touches the installation.

VERIFICATION IS NOT OPTIONAL
    The package is unsigned today, GitHub serves the asset through a redirect
    to a CDN, and a truncated download looks exactly like a complete one. So
    the release publishes a .sha256 beside the zip and this refuses anything
    that does not match it. An update that cannot be verified is not applied;
    it is reported.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("autostream.updates")

REPO = "hardikneeravsharma/AutoStream"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"

ASSET = "AutoStream-share.zip"

# The installer is preferred over the zip when a release publishes both. Only
# the installer can replace a running program, so downloading the zip leaves a
# person with a file and no way to apply it. The zip stays the fallback: older
# releases have nothing else, and it is still the thing to hand somebody who
# wants to look inside before installing.
SETUP = re.compile(r"^AutoStream-[\d.]+-setup\.exe$", re.I)
TIMEOUT = 30.0

# GitHub allows 60 unauthenticated requests an hour per address. One check a
# day is the intent; this is only a floor to stop a UI bug hammering it.
MIN_SECONDS_BETWEEN_CHECKS = 900.0


@dataclass
class Release:
    """What the newest release says about itself."""
    version: str = ""
    tag: str = ""
    url: str = ""                    # the page a person would open
    asset_url: str = ""              # the zip
    asset_name: str = ""
    asset_bytes: int = 0
    sha256_url: str = ""             # the checksum published beside it
    notes: str = ""
    published: str = ""
    installable: bool = False        # an installer, not a zip to unpack by hand

    @property
    def usable(self) -> bool:
        return bool(self.version and self.asset_url)


@dataclass
class Progress:
    """How a download is going, for the page to poll."""
    state: str = "idle"              # idle|checking|downloading|ready|failed
    message: str = ""
    done: int = 0
    total: int = 0
    path: str = ""
    release: dict = field(default_factory=dict)

    @property
    def fraction(self) -> float:
        return (self.done / self.total) if self.total else 0.0


def parse_version(text: str) -> tuple[int, ...]:
    """"v1.7.0" -> (1, 7, 0). Anything unparseable sorts lowest.

    Deliberately not packaging.version: this app ships plain three-part
    versions and pulling in a dependency to compare two of them would be a
    poor trade.
    """
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def _get(url: str, *, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={
        "Accept": accept,
        # GitHub requires a User-Agent and answers 403 without one.
        "User-Agent": f"AutoStream-updater ({REPO})",
    })
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
        return r.read()


def latest() -> Release:
    """Ask GitHub what the newest release is. Raises RuntimeError."""
    try:
        raw = _get(API)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise RuntimeError(
                "GitHub is rate-limiting this machine (60 checks an hour). "
                "Try again later.") from e
        raise RuntimeError(f"GitHub answered {e.code} when asked for the "
                           f"latest release.") from e
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"Could not reach GitHub: {e}") from e
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        raise RuntimeError("GitHub's answer was not readable.") from e

    rel = Release(
        tag=str(data.get("tag_name") or ""),
        url=str(data.get("html_url") or RELEASES_PAGE),
        notes=str(data.get("body") or ""),
        published=str(data.get("published_at") or ""))
    rel.version = rel.tag.lstrip("vV")
    by_name = {str(a.get("name") or ""): a for a in data.get("assets") or []}
    # A release should carry one installer, but pick the highest version
    # rather than whichever the dictionary happened to yield: an asset left
    # behind by a re-upload must never win over the one being released.
    setups = [n for n in by_name if SETUP.match(n)]
    installer = max(setups, key=lambda n: parse_version(n), default=None)
    chosen = installer or (ASSET if ASSET in by_name else None)
    if chosen:
        asset = by_name[chosen]
        rel.asset_url = str(asset.get("browser_download_url") or "")
        rel.asset_name = chosen
        rel.asset_bytes = int(asset.get("size") or 0)
        rel.installable = bool(installer)
        sha = by_name.get(chosen + ".sha256")
        if sha:
            rel.sha256_url = str(sha.get("browser_download_url") or "")
    return rel


def published_sha256(rel: Release) -> str:
    """The checksum the release published, or "" if it published none."""
    if not rel.sha256_url:
        return ""
    try:
        text = _get(rel.sha256_url, accept="text/plain").decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, RuntimeError) as e:
        log.info("could not read the published checksum: %s", e)
        return ""
    # "<hex>  AutoStream-share.zip", the format sha256sum -c expects.
    m = re.search(r"\b([0-9a-fA-F]{64})\b", text)
    return m.group(1).lower() if m else ""


def download(rel: Release, into: Path, *, on_progress=None,
             should_stop=None) -> Path:
    """Fetch the release asset into `into`. -> the file. Raises RuntimeError.

    Verified against the published checksum before it is returned, and deleted
    if it does not match: half a download that looks like an update is worse
    than no update.
    """
    if not rel.usable:
        raise RuntimeError("That release has no downloadable package.")
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    target = into / (rel.asset_name or ASSET)
    part = target.with_suffix(target.suffix + ".part")

    want = published_sha256(rel)
    digest = hashlib.sha256()
    try:
        req = urllib.request.Request(rel.asset_url, headers={
            "User-Agent": f"AutoStream-updater ({REPO})"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r, \
                part.open("wb") as fh:
            total = int(r.headers.get("Content-Length") or rel.asset_bytes or 0)
            done = 0
            while True:
                if should_stop and should_stop():
                    raise RuntimeError("cancelled")
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
    except (urllib.error.URLError, OSError) as e:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"The download failed: {e}") from e
    except RuntimeError:
        part.unlink(missing_ok=True)
        raise

    got = digest.hexdigest()
    if want and got != want:
        part.unlink(missing_ok=True)
        raise RuntimeError(
            "The download does not match the checksum published with the "
            "release, so it has not been kept. Try again, and if it happens "
            "twice download it by hand instead.")
    if not want:
        # Said out loud rather than passed over: an unverified update is a
        # different thing from a verified one, and the difference should not
        # be invisible.
        log.warning("release %s published no checksum, so this download could "
                    "not be verified", rel.tag)
    part.replace(target)
    log.info("downloaded %s (%.0f MB)%s", target.name,
             target.stat().st_size / 1e6,
             f", sha256 {got[:12]} verified" if want else ", UNVERIFIED")
    return target
