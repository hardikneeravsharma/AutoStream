"""A reel's song from a YouTube link.

No network: a stand-in for yt-dlp replays what the real one did, and the error
messages below are the ones yt-dlp actually produced for each case.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from autostream import paths
from autostream.clips import songfetch as sf


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "VIDEO_HOME", tmp_path)
    return tmp_path


# ------------------------------------------------------------------ the link

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=nsXwi67WgOo",
    "https://youtu.be/nsXwi67WgOo?si=Abc123",
    "youtube.com/watch?v=nsXwi67WgOo&list=RDnsXwi67WgOo&index=2",
    "https://music.youtube.com/watch?v=nsXwi67WgOo&feature=share",
    "https://www.youtube.com/shorts/nsXwi67WgOo",
    "  https://m.youtube.com/watch?v=nsXwi67WgOo  ",
])
def test_every_shape_of_youtube_link_gives_the_video(url):
    assert sf.video_id(url) == "nsXwi67WgOo"


@pytest.mark.parametrize("url, says", [
    ("", "Paste a YouTube link"),
    ("https://open.spotify.com/track/123", "isn't a YouTube link"),
    ("https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI", "playlist link"),
    ("https://www.youtube.com/@somechannel", "doesn't point at a video"),
    ("https://www.youtube.com/watch?v=short", "doesn't point at a video"),
])
def test_a_link_that_is_not_one_video_is_refused_before_anything_is_fetched(url, says):
    """Given a playlist link, yt-dlp fetched an arbitrary song from the list."""
    with pytest.raises(sf.FetchError, match=says):
        sf.video_id(url)


# ------------------------------------------------------------------ what went wrong

@pytest.mark.parametrize("raw, says", [
    # Measured: DNS failure and a refused connection, the two ways "offline" arrives.
    ("ERROR: [youtube] nsXwi67WgOo: Unable to download API page: ('Unable to connect to proxy', "
     "NameResolutionError(\"HTTPSConnection(host='no-such-host.invalid', port=8080): Failed to resolve "
     "'no-such-host.invalid' ([Errno 11001] getaddrinfo failed)\")); please report this issue", "internet connection"),
    ("ERROR: [youtube] nsXwi67WgOo: Unable to download API page: NewConnectionError(\"Failed to establish a new "
     "connection: [WinError 10061] No connection could be made\")", "internet connection"),
    ("ERROR: [youtube] aaaaaaaaaaa: This video is unavailable", "unavailable"),
    ("ERROR: [youtube] OT2IKn6ycbA: Sign in to confirm your age. Use --cookies-from-browser", "signed-in adults"),
    ("ERROR: [youtube] jfKfPfyJRdk: This live stream recording is not available.", "live stream"),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "may need an update"),
    ("ERROR: something nobody has seen before", "didn't hand over this song"),
])
def test_errors_are_said_in_words_a_player_can_act_on(raw, says):
    got = sf.explain(raw)
    assert says in got
    assert "please report this issue" not in got and "yt-dlp -U" not in got


# ------------------------------------------------------------------ the download

class FakeYDL:
    """Replays a real download: 13 progress calls for a 2.2 MB m4a."""
    info = {"id": "nsXwi67WgOo", "title": "Lil Nas X - MONTERO (Call Me By Your Name) (Lyrics)",
            "duration": 138, "ext": "m4a"}
    fail_with: str | None = None
    downloads = 0

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        if type(self).fail_with:
            raise RuntimeError(type(self).fail_with)
        return dict(type(self).info)

    def process_ie_result(self, info, download=True):
        type(self).downloads += 1
        out = Path(self.opts["outtmpl"].replace("%(title).80B", info["title"]).replace("%(id)s", info["id"])
                   .replace("%(ext)s", info["ext"]))
        total = 2_234_465
        for done in (1024, 262_144, 1_048_576, total):
            for h in self.opts["progress_hooks"]:
                h({"status": "downloading", "downloaded_bytes": done, "total_bytes": total, "speed": 5e6, "eta": 0})
        out.write_bytes(b"\0" * 64)
        for h in self.opts["progress_hooks"]:
            h({"status": "finished", "downloaded_bytes": total, "total_bytes": total})
        return dict(info, requested_downloads=[{"filepath": str(out)}])


def _fresh(**over):
    cls = type("YDL", (FakeYDL,), {"fail_with": None, "downloads": 0, "info": dict(FakeYDL.info, **over)})
    return cls


def _run(url, factory):
    job = sf.Fetch(url, sf.video_id(url))
    seen = []
    th = threading.Thread(target=job.run, kwargs={"ydl_factory": factory})
    th.start()
    while th.is_alive():
        seen.append(job.snapshot()["state"])
        time.sleep(0.001)
    return job.snapshot(), seen


def test_a_song_downloads_into_the_songs_folder_and_reports_progress(home):
    ydl = _fresh()
    got, seen = _run("https://youtu.be/nsXwi67WgOo", ydl)
    assert got["state"] == "done" and got["error"] == ""
    assert Path(got["path"]).parent == home / "songs" and Path(got["path"]).suffix == ".m4a"
    assert got["percent"] == 100.0 and got["total_bytes"] == 2_234_465
    assert got["title"].startswith("Lil Nas X") and got["seconds"] == 138


def test_the_same_link_again_uses_the_file_already_there(home):
    ydl = _fresh()
    first, _ = _run("https://youtu.be/nsXwi67WgOo", ydl)
    again, _ = _run("https://www.youtube.com/watch?v=nsXwi67WgOo&list=RD1", ydl)
    assert again["state"] == "done" and again["reused"] and again["path"] == first["path"]
    assert ydl.downloads == 1


def test_a_live_stream_or_a_long_mix_is_refused_before_a_byte_is_fetched():
    live = _fresh(is_live=True)
    got, _ = _run("https://youtu.be/nsXwi67WgOo", live)
    assert got["state"] == "failed" and "live stream" in got["error"] and live.downloads == 0
    long = _fresh(duration=2 * 3600)
    got, _ = _run("https://youtu.be/nsXwi67WgOo", long)
    assert got["state"] == "failed" and "2h 00m" in got["error"] and long.downloads == 0


def test_no_internet_is_reported_as_no_internet():
    offline = _fresh()
    offline.fail_with = ("ERROR: [youtube] nsXwi67WgOo: Unable to download API page: "
                         "NameResolutionError(\"Failed to resolve 'www.youtube.com' ([Errno 11001] getaddrinfo failed)\")")
    got, _ = _run("https://youtu.be/nsXwi67WgOo", offline)
    assert got["state"] == "failed" and got["error"] == "Can't reach YouTube. Check your internet connection, then try again."


def test_a_cancelled_download_stops_and_leaves_no_part_file(home):
    class Slow(FakeYDL):
        info = FakeYDL.info
        fail_with = None
        downloads = 0

        def process_ie_result(self, info, download=True):
            part = Path(self.opts["outtmpl"].replace("%(title).80B", info["title"])
                        .replace("%(id)s", info["id"]).replace("%(ext)s", "m4a.part"))
            part.write_bytes(b"\0")
            for i in range(200):
                for h in self.opts["progress_hooks"]:
                    h({"status": "downloading", "downloaded_bytes": i, "total_bytes": 200})
                time.sleep(0.01)
            raise AssertionError("never cancelled")

    job = sf.Fetch("https://youtu.be/nsXwi67WgOo", "nsXwi67WgOo")
    th = threading.Thread(target=job.run, kwargs={"ydl_factory": Slow})
    th.start()
    while job.snapshot()["state"] != "downloading":
        time.sleep(0.005)
    job.cancel()
    th.join(5)
    assert job.snapshot()["state"] == "cancelled"
    assert not list((home / "songs").glob("*.part"))


def test_only_one_download_at_a_time(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def slow_run(self, ydl_factory=None, ffmpeg=None):
        self._set(state="downloading")
        started.set()
        release.wait(5)
        self._set(state="done")
    monkeypatch.setattr(sf.Fetch, "run", slow_run)
    r = sf.Runner()
    r.start("https://youtu.be/nsXwi67WgOo")
    started.wait(5)
    with pytest.raises(sf.FetchError, match="already downloading"):
        r.start("https://youtu.be/dQw4w9WgXcQ")
    release.set()
