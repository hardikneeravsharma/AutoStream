"""A song for a reel, from a YouTube link.

WHY
    A reel is cut to a song, and the song the player wants is usually a YouTube
    video. Saving it meant a third-party download site, a file with a name like
    "YTDown.com_YouTube_Lil-Nas-X-MONTERO-..._009_128k.mp3", and then finding
    that file again in a dialog. Pasting the link is one step.

HOW
    yt-dlp reads the link first, without downloading, so a live stream or a
    two-hour mix is refused before a byte is fetched. Then it downloads the
    audio alone -- m4a where YouTube offers it, which it did for every song
    tried, 2.1 MB in 1.9 s for a 138 s track -- into the songs folder beside
    the clips, named after the title and the video id. The same link pasted
    again is the file already there, not a second download.

WHAT GOES WRONG, IN WORDS A PLAYER CAN ACT ON
    yt-dlp's errors are written for people debugging yt-dlp: a refused
    connection is a 400-character traceback ending "please report this issue".
    explain() turns the ones measured here into what happened and what to do:

        This video is unavailable              missing, private or removed
        Failed to resolve ... getaddrinfo      no internet (DNS)
        Failed to establish a new connection   no internet (connection refused)
        Sign in to confirm your age            age-restricted

    A playlist link is refused before yt-dlp sees it: given one, yt-dlp went
    and fetched an arbitrary song from the list.

    YouTube changes how downloads work from time to time, and yt-dlp follows;
    a build carries the yt-dlp it was built with. So anything unrecognised says
    that plainly, and points at the file picker, which always works.
"""
from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import paths

log = logging.getLogger("autostream.clips.songfetch")

# What the Studio accepts as a song -- see studio.normalise.
SONG_TYPES = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus")

# A reel's song is a track, not a mix or a stream VOD. The longest song any
# reel here has used is under five minutes; twenty leaves room for extended
# mixes without downloading a two-hour video by mistake.
MAX_SECONDS = 20 * 60

HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
         "youtube-nocookie.com", "www.youtube-nocookie.com", "youtu.be", "www.youtu.be")
_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class FetchError(Exception):
    """A failure with a message meant for the player, not a developer."""


def songs_dir() -> Path:
    d = paths.VIDEO_HOME / "songs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def video_id(url: str) -> str:
    """The 11-character video id in a YouTube link. -> id, or raises FetchError saying what is wrong."""
    text = (url or "").strip()
    if not text:
        raise FetchError("Paste a YouTube link first.")
    if not re.match(r"^[a-z]+://", text, re.I):
        text = "https://" + text
    try:
        u = urlparse(text)
    except ValueError:
        raise FetchError("That isn't a link. Copy the address of the YouTube video and paste it here.") from None
    host = (u.hostname or "").lower()
    if host not in HOSTS:
        raise FetchError("That isn't a YouTube link. Paste a link like "
                         "https://www.youtube.com/watch?v=… or https://youtu.be/…")
    q = parse_qs(u.query)
    parts = [p for p in u.path.split("/") if p]
    vid = ""
    if host.endswith("youtu.be"):
        vid = parts[0] if parts else ""
    elif parts[:1] == ["watch"]:
        vid = (q.get("v") or [""])[0]
    elif parts[:1] and parts[0] in ("shorts", "live", "embed", "v") and len(parts) > 1:
        vid = parts[1]
    elif parts[:1] == ["playlist"]:
        raise FetchError("That is a playlist link. Open the song you want and copy that video's link instead.")
    if not _ID.match(vid or ""):
        raise FetchError("That YouTube link doesn't point at a video. Open the video and copy its "
                         "address from the browser, or use Share → Copy link.")
    return vid


# Order matters: the first pattern that matches explains the error.
_EXPLAIN: tuple[tuple[str, str], ...] = (
    (r"getaddrinfo failed|Failed to resolve|NameResolutionError|Temporary failure in name resolution"
     r"|Failed to establish a new connection|WinError 1006[015]|WinError 10051|Network is unreachable"
     r"|timed out|Connection reset|Unable to connect to proxy|RemoteDisconnected",
     "Can't reach YouTube. Check your internet connection, then try again."),
    (r"Sign in to confirm your age|age-restricted|inappropriate for some users",
     "YouTube only plays this video to signed-in adults, so it can't be downloaded here. "
     "Choose another upload of the song."),
    (r"not a bot",
     "YouTube is asking this computer to prove it isn't a bot, so it won't hand over the song right now. "
     "Try again later, or download the song another way and use Choose a song…."),
    (r"members-only|Join this channel|requires payment|purchase",
     "This video is for paying members only, so it can't be downloaded. Choose another upload of the song."),
    (r"Private video|This video is private",
     "This video is private. Choose a public upload of the song."),
    (r"not available in your country|blocked it in your country|geo.?restrict",
     "YouTube doesn't allow this video in your country. Choose another upload of the song."),
    (r"This video is unavailable|Video unavailable|has been removed|account .* terminated|does not exist",
     "YouTube says this video is unavailable: it may be private, removed, or the link may be mistyped."),
    (r"live event will begin|Premieres in|is_upcoming",
     "This video hasn't been published yet. Try again once it has."),
    (r"live stream recording is not available|is a live stream|This live stream",
     "That link is a live stream, or a stream whose recording isn't available. "
     "Paste the link of a finished video instead."),
    (r"No space left|disk is full|WinError 112",
     "There isn't enough free disk space to save the song."),
    (r"Permission denied|WinError 5\b|Access is denied",
     "The song couldn't be saved: Windows refused access to the songs folder."),
    (r"HTTP Error 403|Forbidden|Requested format is not available|nsig|signature|JavaScript runtime",
     "YouTube refused the download. It changes how downloads work from time to time, so this version of "
     "AutoStream may need an update. Until then, download the song another way and use Choose a song…."),
)


def explain(message: str) -> str:
    """A yt-dlp error in words a player can act on."""
    text = str(message or "")
    for pattern, said in _EXPLAIN:
        if re.search(pattern, text, re.I):
            return said
    short = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)?([A-Za-z0-9_-]{11}:\s*)?", "", text).split(";")[0].strip()
    return ("YouTube didn't hand over this song" + (f" ({short[:160]})" if short else "") +
            ". Try again, or download the song another way and use Choose a song….")


def _existing(vid: str) -> Path | None:
    for f in songs_dir().glob(f"*[[]{vid}[]].*"):
        if f.suffix.lower() in SONG_TYPES and f.stat().st_size > 0:
            return f
    return None


class Fetch:
    """One download, run on its own thread, reporting as it goes."""

    def __init__(self, url: str, vid: str):
        self.url, self.vid = url, vid
        self.id = int(time.time() * 1000)
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self.s = {"id": self.id, "state": "starting", "url": url, "video": vid, "title": "",
                  "seconds": 0.0, "done_bytes": 0, "total_bytes": 0, "percent": 0.0,
                  "speed": 0.0, "eta": None, "path": "", "error": "", "reused": False,
                  "started": time.time(), "finished": None}

    # ------------------------------------------------------------ state
    def _set(self, **kw) -> None:
        with self._lock:
            self.s.update(kw)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.s)

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def running(self) -> bool:
        return self.snapshot()["state"] in ("starting", "reading", "downloading", "converting")

    # ------------------------------------------------------------ work
    def run(self, ydl_factory=None, ffmpeg: str | None = None) -> None:
        try:
            self._run(ydl_factory, ffmpeg)
        except FetchError as e:
            self._fail(str(e))
        except Exception as e:                              # noqa: BLE001
            if self._cancel.is_set():
                self._set(state="cancelled", error="", finished=time.time())
            else:
                log.info("song download failed for %s: %s", self.vid, e)
                self._fail(explain(str(e)))
        finally:
            self._tidy()

    def _fail(self, message: str) -> None:
        self._set(state="failed", error=message, finished=time.time())

    def _tidy(self) -> None:
        # A cancelled or failed download leaves yt-dlp's .part file behind.
        if self.snapshot()["state"] != "done":
            for f in songs_dir().glob(f"*[[]{self.vid}[]]*"):
                if f.suffix.lower() in (".part", ".ytdl", ".webm", ".tmp") or f.name.endswith(".part"):
                    try:
                        f.unlink()
                    except OSError:
                        pass

    def _run(self, ydl_factory, ffmpeg) -> None:
        have = _existing(self.vid)
        if have is not None:
            self._set(state="done", path=str(have), title=re.sub(r"\s*\[[^\]]+\]$", "", have.stem),
                      reused=True, percent=100.0, finished=time.time())
            return
        if ydl_factory is None:
            try:
                import yt_dlp
            except ImportError:
                raise FetchError("This copy of AutoStream can't download from YouTube: its downloader "
                                 "isn't installed. Download the song another way and use Choose a song….") from None
            ydl_factory = yt_dlp.YoutubeDL

        def hook(d):
            if self._cancel.is_set():
                raise _Cancelled()
            if d.get("status") == "downloading":
                done = int(d.get("downloaded_bytes") or 0)
                total = int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
                self._set(state="downloading", done_bytes=done, total_bytes=total,
                          percent=round(100.0 * done / total, 1) if total else 0.0,
                          speed=float(d.get("speed") or 0.0), eta=d.get("eta"))
            elif d.get("status") == "finished":
                total = int(d.get("total_bytes") or d.get("downloaded_bytes") or 0)
                self._set(done_bytes=total, total_bytes=total, percent=100.0, eta=0)

        opts = {
            "format": "bestaudio[ext=m4a]/bestaudio",
            "outtmpl": str(songs_dir() / "%(title).80B [%(id)s].%(ext)s"),
            "windowsfilenames": True, "noplaylist": True, "quiet": True, "no_warnings": True,
            "noprogress": True, "socket_timeout": 20, "retries": 2, "extractor_retries": 1,
            "progress_hooks": [hook],
            # yt-dlp prints ERROR lines even when quiet; they belong in the log,
            # and the player gets explain()'s version instead.
            "logger": _Quiet(),
        }
        self._set(state="reading")
        watch = f"https://www.youtube.com/watch?v={self.vid}"
        with ydl_factory(opts) as ydl:
            info = ydl.extract_info(watch, download=False)
            if self._cancel.is_set():
                raise _Cancelled()
            title = str(info.get("title") or self.vid)
            seconds = float(info.get("duration") or 0.0)
            self._set(title=title, seconds=seconds)
            if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
                raise FetchError("That link is a live stream. Paste the link of a finished video instead.")
            if seconds > MAX_SECONDS:
                raise FetchError(f"That video is {_dur(seconds)} long. A reel's song should be one track, "
                                 f"not a mix: choose a video under {MAX_SECONDS // 60} minutes.")
            self._set(state="downloading")
            got = ydl.process_ie_result(info, download=True)
        where = _downloaded(got, self.vid)
        if where is None:
            raise FetchError("The download finished but the song file isn't there. Try again.")
        if where.suffix.lower() not in SONG_TYPES:
            where = self._convert(where, ffmpeg)
        self._set(state="done", path=str(where), percent=100.0, finished=time.time())
        log.info("song from YouTube %s: %s (%.0f s, %.1f MB)", self.vid, where.name, seconds,
                 where.stat().st_size / 1e6)

    def _convert(self, src: Path, ffmpeg: str | None) -> Path:
        """Audio YouTube only offered as webm, into m4a the Studio can use."""
        from .tools import binary

        ff = ffmpeg or binary("ffmpeg")
        if not ff:
            raise FetchError("This song needs converting, and ffmpeg isn't installed. "
                             "Install it from the Clips page, then try again.")
        self._set(state="converting")
        out = src.with_suffix(".m4a")
        r = subprocess.run([ff, "-v", "error", "-y", "-i", str(src), "-vn", "-c:a", "aac", "-b:a", "192k", str(out)],
                           capture_output=True, text=True, timeout=600,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0 or not out.is_file():
            raise FetchError("The song downloaded but couldn't be converted: " + (r.stderr or "").strip()[:160])
        try:
            src.unlink()
        except OSError:
            pass
        return out


class _Cancelled(Exception):
    pass


class _Quiet:
    """yt-dlp's logger, into AutoStream's log at debug level."""

    def debug(self, msg):
        log.debug("yt-dlp: %s", msg)

    def info(self, msg):
        log.debug("yt-dlp: %s", msg)

    def warning(self, msg):
        log.debug("yt-dlp warning: %s", msg)

    def error(self, msg):
        log.info("yt-dlp: %s", str(msg)[:300])


def _downloaded(info: dict, vid: str) -> Path | None:
    for d in (info or {}).get("requested_downloads") or []:
        p = Path(str(d.get("filepath") or d.get("_filename") or ""))
        if p.name and p.is_file():
            return p
    return _existing(vid) or next((f for f in songs_dir().glob(f"*[[]{vid}[]].*")
                                   if f.is_file() and not f.name.endswith(".part")), None)


def _dur(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}h {s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m {s % 60:02d}s"


class Runner:
    """One download at a time: the page shows a single progress bar."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.job: Fetch | None = None

    def start(self, url: str) -> Fetch:
        vid = video_id(url)                                  # raises FetchError on a bad link
        with self._lock:
            if self.job is not None and self.job.running:
                raise FetchError("A song is already downloading. Wait for it, or cancel it first.")
            self.job = Fetch(url, vid)
            job = self.job
        threading.Thread(target=job.run, name="autostream-songfetch", daemon=True).start()
        return job

    def status(self) -> dict:
        with self._lock:
            job = self.job
        return job.snapshot() if job else {"state": "idle"}

    def busy(self) -> bool:
        with self._lock:
            job = self.job
        return job is not None and job.running

    def cancel(self) -> bool:
        with self._lock:
            job = self.job
        if job is None or not job.running:
            return False
        job.cancel()
        return True


_RUNNER: Runner | None = None
_RUNNER_LOCK = threading.Lock()


def runner() -> Runner:
    global _RUNNER
    if _RUNNER is None:
        with _RUNNER_LOCK:
            if _RUNNER is None:
                _RUNNER = Runner()
    return _RUNNER
