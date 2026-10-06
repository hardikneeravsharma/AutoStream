r"""Taking a piece out of a clip, and what happens to its kill marks.

SAID AS "REMOVE", NOT AS "KEEP". What somebody watching a clip wants to do is
"this bit at the front is dead, take it off" -- phrasing it as a keep-range
makes them work out the complement of the thing they can actually see. It
therefore handles a middle as naturally as an end.

THE MARKS ARE THE DANGEROUS PART. A kill at 12s with seconds 5 to 10 removed
is at 7s afterwards, and one inside the removed piece is gone. Left where they
were, every mark after the cut would point at the wrong moment and the only
sign would be a reel cutting to nothing.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from autostream.clips import uploads

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ------------------------------------- the arithmetic, with no files at all

def test_a_mark_before_the_cut_does_not_move():
    assert uploads.shift_marks([2.0], 5.0, 10.0) == [2.0]


def test_a_mark_after_the_cut_moves_back_by_what_went():
    """Five seconds came out, so everything after it is five seconds earlier."""
    assert uploads.shift_marks([12.0], 5.0, 10.0) == [7.0]


def test_a_mark_inside_the_cut_is_gone():
    """There is no moment left for it to point at."""
    assert uploads.shift_marks([7.0], 5.0, 10.0) == []


def test_marks_on_the_edges_count_as_inside():
    assert uploads.shift_marks([5.0, 10.0], 5.0, 10.0) == []


def test_a_whole_set_moves_together():
    got = uploads.shift_marks([1.0, 7.0, 12.0, 20.0], 5.0, 10.0)
    assert got == [1.0, 7.0, 15.0]


def test_they_come_back_in_order():
    """Given out of order: 1 is before the cut, 12 and 20 are after it and
    move back five each."""
    assert uploads.shift_marks([20.0, 1.0, 12.0], 5.0, 10.0) == [1.0, 7.0, 15.0]


def test_rubbish_marks_are_dropped_rather_than_crashing():
    assert uploads.shift_marks([None, "x", 12.0], 5.0, 10.0) == [7.0]


def test_no_marks_is_no_marks():
    assert uploads.shift_marks([], 1.0, 2.0) == []
    assert uploads.shift_marks(None, 1.0, 2.0) == []


# ----------------------------------------------- what it refuses, on disk

@pytest.fixture
def clip(tmp_path):
    """An imported clip with a real 20-second video behind it."""
    from autostream.clips.tools import FfmpegMissing, binary

    try:
        ff = binary("ffmpeg")
    except FfmpegMissing as e:
        pytest.skip(str(e))

    root = tmp_path / "clips"
    run = root / "import-2026-10-05-a"
    (run / "clips").mkdir(parents=True)
    f = run / "clips" / "a.mp4"
    subprocess.run(
        [ff, "-y", "-v", "error", "-nostdin",
         "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15:duration=20",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
         "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264",
         "-preset", "ultrafast", "-c:a", "aac", str(f)],
        check=True, capture_output=True, timeout=600, creationflags=NO_WINDOW)
    (run / "clips.json").write_text(json.dumps({
        "game": "Other", "clips": [{"name": "A", "master": str(f),
                                    "start": 0.0, "end": 20.0,
                                    "duration": 20.0, "kills": 0}]}),
        encoding="utf-8")
    (run / "session.json").write_text(json.dumps({
        "game": "Other", "imported": True,
        "kills": [{"time": 2.0}, {"time": 7.0}, {"time": 15.0}]}),
        encoding="utf-8")
    return root, f, run


def _dur(path):
    from autostream.clips.tools import media_info

    return float(media_info(path)["duration"])


def test_a_piece_of_no_length_is_refused(clip):
    root, f, _run = clip
    got = uploads.trim(root, str(f), 5.0, 5.0)
    assert got["ok"] is False
    assert "longer" in got["error"].lower()


def test_removing_everything_is_refused(clip):
    """Deleting the clip is a different decision, made somewhere else."""
    root, f, _run = clip
    got = uploads.trim(root, str(f), 0.0, 999.0)
    assert got["ok"] is False
    assert "delete" in got["error"].lower()


def test_a_path_outside_the_clips_folder_is_refused(clip, tmp_path):
    root, _f, _run = clip
    stray = tmp_path / "elsewhere" / "clips" / "x.mp4"
    assert uploads.trim(root, str(stray), 1.0, 2.0)["ok"] is False


def test_a_clip_that_is_gone_is_refused(clip):
    root, f, _run = clip
    f.unlink()
    assert uploads.trim(root, str(f), 1.0, 2.0)["ok"] is False


# ------------------------------------------------- and what it actually does

def test_taking_the_front_off_shortens_the_clip(clip):
    root, f, _run = clip
    before = _dur(f)
    got = uploads.trim(root, str(f), 0.0, 5.0)
    assert got["ok"] is True, got
    after = _dur(f)
    assert after == pytest.approx(before - 5.0, abs=0.6), (before, after)
    assert got["seconds"] == pytest.approx(after, abs=0.6)


def test_taking_the_middle_out_joins_what_is_left(clip):
    """The two halves become one clip. This is the case a keep-range cannot
    express at all, and the reason it is phrased as removing."""
    root, f, _run = clip
    before = _dur(f)
    got = uploads.trim(root, str(f), 8.0, 12.0)
    assert got["ok"] is True, got
    assert _dur(f) == pytest.approx(before - 4.0, abs=0.8)


def test_the_marks_come_back_moved(clip):
    """Marks at 2, 7 and 15; seconds 5 to 10 removed. 2 stays, 7 is inside
    and goes, 15 becomes 10."""
    root, f, _run = clip
    got = uploads.trim(root, str(f), 5.0, 10.0)
    assert got["ok"] is True, got
    assert got["kills"] == [2.0, 10.0]


def test_the_manifest_agrees_with_the_file(clip):
    """A row still claiming twenty seconds would put every later reader --
    the reel, the Studio lane, the next re-cut -- out by the difference."""
    root, f, run = clip
    uploads.trim(root, str(f), 5.0, 10.0)
    man = json.loads((run / "clips.json").read_text(encoding="utf-8"))
    row = man["clips"][0]
    assert row["duration"] == pytest.approx(_dur(f), abs=0.6)
    assert row["kills"] == 2
    assert row["marks"] == [2.0, 10.0]


def test_the_session_of_an_import_is_updated_too(clip):
    """An import's session.json describes that one clip, so its kills are the
    clip's -- unlike a cut run, where they belong to the whole recording."""
    root, f, run = clip
    uploads.trim(root, str(f), 5.0, 10.0)
    sess = json.loads((run / "session.json").read_text(encoding="utf-8"))
    assert [k["time"] for k in sess["kills"]] == [2.0, 10.0]


def test_what_it_says_is_what_is_on_disk(clip):
    root, f, _run = clip
    got = uploads.trim(root, str(f), 2.0, 6.0)
    assert got["removed"] == [2.0, 6.0]
    assert uploads.info(root, str(f))["seconds"] == pytest.approx(
        got["seconds"], abs=0.6)


def test_the_original_is_kept(clip):
    """The cost of being wrong is somebody's footage. A regretted cut should
    be a rename, not a re-import."""
    root, f, _run = clip
    before = _dur(f)
    uploads.trim(root, str(f), 5.0, 10.0)
    backup = f.with_suffix(f.suffix + ".original")
    assert backup.is_file()
    assert _dur(backup) == pytest.approx(before, abs=0.3)


def test_the_backup_is_the_file_they_brought_in(clip):
    """Taken once. Refreshed every trim it would become a copy of the last
    cut, which is no use at all as the thing to go back to."""
    root, f, _run = clip
    before = _dur(f)
    uploads.trim(root, str(f), 0.0, 3.0)
    uploads.trim(root, str(f), 0.0, 3.0)
    backup = f.with_suffix(f.suffix + ".original")
    assert _dur(backup) == pytest.approx(before, abs=0.3)


def test_two_cuts_in_a_row_both_take_effect(clip):
    root, f, _run = clip
    before = _dur(f)
    assert uploads.trim(root, str(f), 0.0, 3.0)["ok"] is True
    mid = _dur(f)
    assert uploads.trim(root, str(f), 0.0, 3.0)["ok"] is True
    assert _dur(f) == pytest.approx(mid - 3.0, abs=0.8)
    assert _dur(f) < before - 5.0
