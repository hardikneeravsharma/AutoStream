"""Kill checks kept on disk: read once per file, not once per restart.

A Build and drop plan from 48 clips spent 91 of its 131 s reading kill emblems,
and read them all again after every restart -- which every update is.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import killmark, studio      # noqa: E402


@pytest.fixture
def reads(monkeypatch, tmp_path):
    n = {"marks": 0, "appear": 0}

    def marks(path, game, ff):
        n["marks"] += 1
        return [1.5, 4.25]

    def appearance(path, game, near, ff):
        n["appear"] += 1
        return near - 0.1
    monkeypatch.setattr(killmark, "marks", marks)
    monkeypatch.setattr(killmark, "appearance", appearance)
    monkeypatch.setattr(killmark, "spec_for", lambda game: object())
    import autostream.clips.tools as tools
    monkeypatch.setattr(tools, "binary", lambda name: "ffmpeg")
    yield n
    studio.use_check_cache(None)


def restart():
    """What a restart forgets: the memory caches and the loaded file."""
    studio._MARK_CACHE.clear()
    studio._GLYPH_CACHE.clear()
    studio._CHECK_DISK.data = None


def test_a_restart_reads_the_checks_from_disk_not_the_clip(reads, tmp_path):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x")
    cache = tmp_path / ".studio" / studio.KILL_CHECKS_FILE
    studio.use_check_cache(cache)
    restart()
    assert studio.kill_marks(str(clip), "valorant") == [1.5, 4.25]
    assert studio.kill_appearance(str(clip), "valorant", 4.25) == pytest.approx(4.15)
    assert cache.is_file() and reads == {"marks": 1, "appear": 1}
    restart()
    assert studio.kill_marks(str(clip), "valorant") == [1.5, 4.25]
    assert studio.kill_appearance(str(clip), "valorant", 4.25) == pytest.approx(4.15)
    assert reads == {"marks": 1, "appear": 1}
    # the file changed: read again
    clip.write_bytes(b"xy")
    restart()
    studio.kill_marks(str(clip), "valorant")
    assert reads["marks"] == 2


def test_nothing_is_written_until_the_app_says_where(reads, tmp_path):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x")
    studio.use_check_cache(None)
    restart()
    studio.kill_marks(str(clip), "valorant")
    restart()
    studio.kill_marks(str(clip), "valorant")
    assert reads["marks"] == 2
    assert not list(tmp_path.rglob(studio.KILL_CHECKS_FILE))


def test_an_older_cache_is_not_believed(reads, tmp_path):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x")
    cache = tmp_path / studio.KILL_CHECKS_FILE
    key = studio._CheckDisk.key("marks", str(clip), "valorant")
    import json
    cache.write_text(json.dumps({"version": studio.KILL_CHECKS_VERSION - 1, "entries": {key: [9.0]}}), "utf-8")
    studio.use_check_cache(cache)
    restart()
    assert studio.kill_marks(str(clip), "valorant") == [1.5, 4.25] and reads["marks"] == 1
