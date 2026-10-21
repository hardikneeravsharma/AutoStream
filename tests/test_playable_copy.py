"""The playable copy (#210): where it goes, when it counts as made, and that
it is something a player can show."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from autostream import paths
from autostream.clips import cutter, tools


def test_the_copy_sits_beside_the_recording(tmp_path):
    src = tmp_path / "stream.mp4"
    src.write_bytes(b"x")
    assert cutter.playable_path(src) == tmp_path / "stream.playable.mp4"


def test_a_folder_it_cannot_write_to_sends_the_copy_home(tmp_path, monkeypatch):
    src = tmp_path / "stream.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(os, "access", lambda p, m: False)
    monkeypatch.setattr(paths, "VIDEO_HOME", tmp_path / "home")
    got = cutter.playable_path(src)
    assert got.parent == tmp_path / "home" / "playable" and got.name.endswith(".playable.mp4")


def test_only_a_copy_newer_than_its_recording_counts(tmp_path):
    src = tmp_path / "stream.mp4"
    src.write_bytes(b"x")
    assert cutter.playable_ready(src) is None
    copy = cutter.playable_path(src)
    copy.write_bytes(b"y")
    os.utime(copy, (time.time() - 100, time.time() - 100))
    assert cutter.playable_ready(src) is None, "a copy of an older file was trusted"
    os.utime(copy, None)
    assert cutter.playable_ready(src) == copy


def _ffmpeg():
    try:
        return tools.binary("ffmpeg")
    except tools.FfmpegMissing:
        pytest.skip("no ffmpeg")


def test_the_copy_is_h264_at_720p_and_reports_its_progress(tmp_path):
    ff = _ffmpeg()
    src = tmp_path / "rec.mkv"                     # a format no browser plays
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x1440:r=60:d=3",
                    "-f", "lavfi", "-i", "sine=d=3", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(src)], check=True, timeout=120)
    seen = []
    out = cutter.playable_copy(src, cutter.playable_path(src), on_progress=seen.append)
    info = tools.media_info(out)
    assert info["vcodec"] == "h264" and info["height"] == cutter.PLAYABLE_HEIGHT
    assert round(info["fps"]) == cutter.PLAYABLE_FPS and info["audio_tracks"] == 1
    assert seen and seen[-1] > 0.5
    assert not list(tmp_path.glob("*.part")), "the unfinished name was left behind"


def test_a_failed_copy_leaves_nothing_that_looks_made(tmp_path):
    _ffmpeg()
    src = tmp_path / "broken.mp4"
    src.write_bytes(b"not a video")
    with pytest.raises(Exception):
        cutter.playable_copy(src, cutter.playable_path(src))
    assert cutter.playable_ready(src) is None
    assert not list(tmp_path.glob("*.part"))


def test_a_stopped_copy_leaves_nothing_behind(tmp_path):
    """The Stop button: ffmpeg is killed and the unfinished file removed."""
    ff = _ffmpeg()
    src = tmp_path / "rec.mkv"
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=60:d=20",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True, timeout=120)
    seen = []
    with pytest.raises(RuntimeError, match="cancelled"):
        cutter.playable_copy(src, cutter.playable_path(src), on_progress=seen.append,
                             cancelled=lambda: bool(seen))      # stop at the first sign of life
    assert cutter.playable_ready(src) is None
    assert not list(tmp_path.glob("*.playable.mp4*")), "a stopped copy left a file"


def test_quitting_the_app_mid_copy_leaves_no_ffmpeg_behind(tmp_path):
    """Found orphaned an hour after its app had quit: the copy writes to a
    file, so nothing broke when the app went. A real child process, a real
    exit -- and no ffmpeg still running after it."""
    ff = _ffmpeg()
    src = tmp_path / "rec.mkv"
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=60:d=120",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src)],
                   check=True, timeout=300)
    marker = tmp_path / "pid"
    child = (
        "import sys, threading, time, os\n"
        "from pathlib import Path\n"
        "from autostream.clips import cutter\n"
        f"src = Path({str(src)!r})\n"
        "threading.Thread(target=cutter.playable_copy, args=(src, cutter.playable_path(src)),\n"
        "                 daemon=True).start()\n"
        "for _ in range(100):\n"
        "    if cutter._COPYING: break\n"
        "    time.sleep(0.1)\n"
        f"Path({str(marker)!r}).write_text(str(next(iter(cutter._COPYING)).pid))\n"
        "sys.exit(0)\n")
    subprocess.run([__import__("sys").executable, "-c", child], check=True, timeout=60,
                   cwd=str(Path(__file__).resolve().parents[1]))
    pid = int(marker.read_text())
    time.sleep(0.5)
    try:
        os.kill(pid, 0)
        alive = True
    except OSError:
        alive = False
    assert not alive, f"ffmpeg {pid} outlived the app that started it"
