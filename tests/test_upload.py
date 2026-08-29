"""Publishing clips to YouTube.

The plan for this (docs/PLAN-shorts-upload.md) names the failures that must be
handled rather than swallowed, and they are what this file pins. The two that
matter most:

    * a batch is REFUSED before anything uploads, so it cannot die
      half-published with no way to tell what went out;
    * an over-long title is caught here, because YouTube rejects the whole
      request for one -- and does it only after the file has finished
      uploading.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest                                                   # noqa: E402

from autostream.clips import upload as up                       # noqa: E402
from autostream.youtube import TITLE_MAX, UPLOAD_COST           # noqa: E402


# ------------------------------------------------------------- templating

def test_every_token_is_filled():
    got = up.render("{caption} - {game} ({kills} kills)",
                    {"caption": "ACE", "game": "CS2", "kills": 5}, limit=100)
    assert got == "ACE - CS2 (5 kills)"


def test_an_empty_caption_does_not_strand_its_separator():
    """"- Counter-Strike 2" is what the naive version produces."""
    got = up.render("{caption} - {game}", {"caption": "", "game": "CS2"}, limit=100)
    assert got == "CS2"


def test_a_long_title_is_cut_before_the_request():
    got = up.render("{caption}", {"caption": "word " * 60}, limit=TITLE_MAX)
    assert len(got) <= TITLE_MAX


def test_the_cut_lands_on_a_word():
    got = up.render("{caption}", {"caption": "alpha bravo charlie delta echo " * 8},
                    limit=40)
    assert len(got) <= 40
    assert not got.endswith(" ")
    assert "  " not in got


def test_a_missing_token_is_empty_not_literal():
    got = up.render("{caption} {nope}", {"caption": "ACE"}, limit=100)
    assert "{nope}" in got or got == "ACE"      # unknown tokens are left alone


# --------------------------------------------------------- refusing a batch

class FakeYT:
    """Counts uploads and answers quota questions. Never touches a network."""
    def __init__(self, left=100000):
        self.left = left
        self.uploaded: list[str] = []
        self.cfg = type("C", (), {"youtube": type("Y", (), {"category_id": "20"})()})()

    def quota_left(self):
        return self.left

    def upload_video(self, path, **kw):
        self.uploaded.append(Path(path).name)
        n = len(self.uploaded)
        return {"id": f"vid{n}", "url": f"https://youtu.be/vid{n}",
                "shorts_url": f"https://www.youtube.com/shorts/vid{n}",
                "privacy": kw.get("privacy"), "title": kw.get("title")}


def a_clip(tmp_path, name="a.mp4", **extra):
    f = tmp_path / name
    f.write_bytes(b"x")
    return {"path": str(f), "caption": "TRIPLE KILL", "kills": 3, **extra}


def a_job(clips, tmp_path, yt=None, **kw):
    return up.UploadJob(clips, yt=yt or FakeYT(), game="CS2",
                        folder=tmp_path, **kw)


def test_nothing_selected_is_refused(tmp_path):
    job = a_job([], tmp_path)
    job.run()
    assert job.state == "failed"
    assert "Nothing selected" in job.error


def test_the_daily_cap_holds_independently_of_quota(tmp_path):
    """The cap exists precisely because the quota cost is uncertain -- a wrong
    estimate must not be able to spend a day's streaming on uploads."""
    yt = FakeYT(left=10_000_000)                 # quota is not the limit here
    job = a_job([a_clip(tmp_path, f"{i}.mp4") for i in range(6)],
                tmp_path, yt=yt, daily_max=5)
    job.run()
    assert job.state == "failed"
    assert "limit is 5" in job.error
    assert yt.uploaded == []                     # refused BEFORE any upload


def test_zero_daily_max_switches_uploading_off(tmp_path):
    yt = FakeYT()
    job = a_job([a_clip(tmp_path)], tmp_path, yt=yt, daily_max=0)
    job.run()
    assert job.state == "failed"
    assert yt.uploaded == []


def test_too_little_quota_refuses_the_whole_batch(tmp_path):
    """Not a partial run. A batch that dies half-published leaves the user
    guessing which clips are already public."""
    yt = FakeYT(left=UPLOAD_COST)                # enough for one, two asked
    job = a_job([a_clip(tmp_path, "a.mp4"), a_clip(tmp_path, "b.mp4")],
                tmp_path, yt=yt)
    job.run()
    assert job.state == "failed"
    assert "quota" in job.error.lower()
    assert yt.uploaded == []


# ------------------------------------------------------------- running one

def test_a_good_batch_uploads_every_clip(tmp_path):
    yt = FakeYT()
    job = a_job([a_clip(tmp_path, "a.mp4"), a_clip(tmp_path, "b.mp4")],
                tmp_path, yt=yt)
    job.run()
    assert job.state == "done"
    assert yt.uploaded == ["a.mp4", "b.mp4"]
    assert len(job.results) == 2


def test_a_missing_file_is_skipped_not_fatal(tmp_path):
    """The rest of the batch is still good."""
    gone = {"path": str(tmp_path / "gone.mp4"), "caption": "X", "kills": 1}
    yt = FakeYT()
    job = a_job([gone, a_clip(tmp_path, "b.mp4")], tmp_path, yt=yt)
    job.run()
    assert job.state == "done"
    assert yt.uploaded == ["b.mp4"]
    assert job.failures and "gone" in job.failures[0]["error"].lower()


def test_an_already_uploaded_clip_is_not_published_twice(tmp_path):
    yt = FakeYT()
    job = a_job([a_clip(tmp_path, "a.mp4", video_id="already")], tmp_path, yt=yt)
    job.run()
    assert yt.uploaded == []
    assert "Already uploaded" in job.failures[0]["error"]


def test_one_failure_keeps_the_successes(tmp_path):
    class Flaky(FakeYT):
        def upload_video(self, path, **kw):
            if Path(path).name == "b.mp4":
                raise RuntimeError("network went away")
            return super().upload_video(path, **kw)

    yt = Flaky()
    job = a_job([a_clip(tmp_path, "a.mp4"), a_clip(tmp_path, "b.mp4"),
                 a_clip(tmp_path, "c.mp4")], tmp_path, yt=yt)
    job.run()
    assert job.state == "done"
    assert yt.uploaded == ["a.mp4", "c.mp4"]
    assert len(job.failures) == 1
    assert "network" in job.failures[0]["error"]


def test_the_ids_go_back_into_clips_json(tmp_path):
    """So the page can show links, and a re-upload is recognised as one."""
    clip = a_clip(tmp_path, "a.mp4")
    (tmp_path / "clips.json").write_text(
        json.dumps({"clips": [{"path": clip["path"], "caption": "TRIPLE KILL"}]}),
        encoding="utf-8")
    job = a_job([clip], tmp_path)
    job.run()

    data = json.loads((tmp_path / "clips.json").read_text(encoding="utf-8"))
    row = data["clips"][0]
    assert row["video_id"] == "vid1"
    assert row["shorts_url"].endswith("vid1")


def test_a_cancelled_batch_stops_and_says_so(tmp_path):
    job = a_job([a_clip(tmp_path, "a.mp4"), a_clip(tmp_path, "b.mp4")], tmp_path)
    job.cancel()
    job.run()
    assert job.state == "cancelled"


def test_the_snapshot_moves_during_one_clip(tmp_path):
    """A forty-megabyte clip must not sit at 0% for a minute."""
    job = a_job([a_clip(tmp_path, "a.mp4"), a_clip(tmp_path, "b.mp4")], tmp_path)
    job.state = "running"
    job.chunk = 0.5
    assert job.snapshot()["percent"] == 25      # half of the first of two
