"""A write that is interrupted must not destroy the file it replaces.

config.yaml, state.json and history.jsonl were already written this way. The
files the Clips page and the uploader depend on were not -- they used
write_text, which truncates the target first. Killed in that window (a rebuild,
the tray, a crash) the file is left empty or half-written, and nothing
announces it: it simply fails to parse at some later moment and the feature has
no data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autostream import atomic                          # noqa: E402


def test_a_write_replaces_the_file(tmp_path):
    f = tmp_path / "clips.json"
    f.write_text('["old"]', encoding="utf-8")
    atomic.write_json(f, ["new"])
    assert json.loads(f.read_text(encoding="utf-8")) == ["new"]
    assert list(tmp_path.iterdir()) == [f], "a .tmp was left behind"


def test_the_old_file_survives_a_failed_write(tmp_path, monkeypatch):
    f = tmp_path / "clips.json"
    f.write_text('[{"caption": "the original"}]', encoding="utf-8")

    class Boom(Exception):
        pass

    real = atomic.os.replace

    def explode(*a, **k):
        raise Boom("the machine went away mid-write")

    monkeypatch.setattr(atomic.os, "replace", explode)
    with pytest.raises(Boom):
        atomic.write_json(f, [{"caption": "the new one"}])
    monkeypatch.setattr(atomic.os, "replace", real)

    # The point: the original is intact, not empty and not half-written.
    assert json.loads(f.read_text(encoding="utf-8"))[0]["caption"] == "the original"


def test_a_failed_write_leaves_no_temporary_file_behind(tmp_path, monkeypatch):
    f = tmp_path / "clips.json"
    f.write_text("[]", encoding="utf-8")

    def explode(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(atomic.os, "replace", explode)
    with pytest.raises(RuntimeError):
        atomic.write_json(f, [1, 2, 3])
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "clips.json"]
    assert leftovers == [], leftovers


def test_an_interrupt_mid_write_leaves_no_temporary_file(tmp_path, monkeypatch):
    """KeyboardInterrupt is a BaseException, so a bare `except Exception`
    around the cleanup would have missed exactly the case that matters when
    somebody kills the app."""
    f = tmp_path / "session.json"

    def interrupt(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(atomic.os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        atomic.write_json(f, {"plans": []})
    assert list(tmp_path.iterdir()) == []


def test_the_temporary_file_is_made_beside_the_target(tmp_path):
    """os.replace cannot move across volumes, and a clips folder on another
    drive is the ordinary case here rather than an exotic one."""
    seen = {}
    real = atomic.tempfile.mkstemp

    def watch(*a, **k):
        seen["dir"] = k.get("dir")
        return real(*a, **k)

    atomic.tempfile.mkstemp = watch
    try:
        atomic.write_json(tmp_path / "deep" / "x.json", {"a": 1})
    finally:
        atomic.tempfile.mkstemp = real
    assert Path(seen["dir"]) == tmp_path / "deep"


def test_it_writes_what_it_was_given(tmp_path):
    f = tmp_path / "x.json"
    atomic.write_json(f, {"b": [1, 2], "a": "x"})
    assert json.loads(f.read_text(encoding="utf-8")) == {"b": [1, 2], "a": "x"}
    # ...and a compact form for the files nobody reads by hand.
    atomic.write_json(f, {"a": 1}, indent=None)
    assert f.read_text(encoding="utf-8") == '{"a": 1}'


def test_parent_directories_are_made(tmp_path):
    """A run writes its manifest into a folder it has just created."""
    f = tmp_path / "a" / "b" / "clips.json"
    atomic.write_json(f, {"ok": True})
    assert json.loads(f.read_text(encoding="utf-8")) == {"ok": True}


def test_the_manifests_use_it():
    """The whole point: the files that matter go through this."""
    root = Path(__file__).resolve().parents[1] / "autostream" / "clips"
    for name in ("jobs.py", "edit.py", "upload.py", "valorant_match.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "atomic.write_json" in src, name
        # ...and none of them still write a manifest the unsafe way.
        assert "write_text(json.dumps" not in src, name
