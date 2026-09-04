"""When a recording began, for a file this app did not record.

Most users of the clipper will never stream with it. They hand it a video from
OBS, ShadowPlay or Medal and expect clips, so everything that keys off "when
was this recorded" has to work on a file that arrived by hand.

The filename stamp is exact when OBS wrote it. When it did not, the only clock
left is the file's mtime -- which is when writing FINISHED. Using it as the
START shifts the whole recording forward by its own length, and the searches
that depend on it have windows measured in a minute or two, so the shift does
not degrade them: it makes them find nothing at all.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import valorant_match as vm                 # noqa: E402
from autostream.clips.jobs import ClipJob                         # noqa: E402


def a_job(path: Path, seconds: float) -> ClipJob:
    job = ClipJob.__new__(ClipJob)
    job.source = path
    job.source_seconds = seconds
    return job


def test_the_obs_stamp_still_wins(tmp_path):
    """A named file says so itself, and mtime is not consulted."""
    src = tmp_path / "2026-09-05 00-46-48.mp4"
    src.write_bytes(b"x")
    os.utime(src, (2_000_000, 2_000_000))          # a wildly wrong mtime

    started = a_job(src, 43 * 60)._source_started()

    from autostream import history
    assert started == history._started_from_name(str(src))        # noqa: SLF001


def test_a_hand_supplied_file_dates_from_its_start_not_its_end(tmp_path):
    """The fix. mtime is when writing finished, so the length comes off it."""
    src = tmp_path / "gameplay.mp4"                 # no stamp: not OBS's name
    src.write_bytes(b"x")
    os.utime(src, (1_800_000_000, 1_800_000_000))

    started = a_job(src, 43 * 60)._source_started()

    assert started == 1_800_000_000 - 43 * 60


def test_an_unprobed_file_is_no_worse_than_before(tmp_path):
    """Length unknown, so nothing is subtracted -- the old behaviour, which is
    still enough to reject a demo from days earlier."""
    src = tmp_path / "gameplay.mp4"
    src.write_bytes(b"x")
    os.utime(src, (1_800_000_000, 1_800_000_000))

    assert a_job(src, 0.0)._source_started() == 1_800_000_000


def test_the_match_record_is_actually_found(tmp_path):
    """The point of the fix, measured rather than asserted about.

    A 43-minute recording of a match that began 40 seconds in. Dated from its
    end, the search window opens after the match is over -- and EDGE_SLACK is
    90 seconds, so nothing is found no matter how good the record is.
    """
    length = 43 * 60
    began = 1_800_000_000.0                       # when the picture starts
    src = tmp_path / "gameplay.mp4"
    src.write_bytes(b"x")
    os.utime(src, (began + length, began + length))

    match = vm.Match(tmp_path / "m.json", {
        "matchInfo": {"matchId": "abcd1234",
                      "gameStartMillis": int((began + 40) * 1000)}})

    started = a_job(src, length)._source_started()
    assert vm.for_recording(started, length, [match]) == [match]

    # And the reason it needed fixing: the end date finds nothing.
    assert vm.for_recording(began + length, length, [match]) == []
