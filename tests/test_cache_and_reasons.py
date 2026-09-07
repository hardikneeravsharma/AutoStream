"""Reusing a scan, and saying why a run produced nothing.

Both come from one real run. A 174-minute Valorant recording was reviewed and
then cut; the cut rescanned the whole 42-minute window instead of reusing the
review's kills, and then reported "0 clips" with no explanation -- while
quietly writing a 105 MB promo reel holding all 13 of the kills it had found.

Nothing there was a detector fault. The kills were right. What was wrong was
that the cache could not be used and the result did not say what happened.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import webui                                      # noqa: E402


def a_sidecar(root: Path, name: str, source: Path, scanned, kills):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "session.json").write_text(json.dumps({
        "source": str(source), "scanned": scanned, "kills": kills,
    }), encoding="utf-8")
    return d


def an_app(monkeypatch, root: Path):
    app = webui.Server.__new__(webui.Server)
    monkeypatch.setattr(webui.Server, "_clips_dir", lambda self, c=None: root)
    return app


def test_a_window_running_to_the_end_reuses_its_own_scan(monkeypatch, tmp_path):
    """THE BUG. scan_end of 0 means "to the end of the file". The coverage
    test read `... and want_b and ...`, which is False for 0, so a window that
    ran to the end could never reuse the scan it had just paid for -- and
    reviewing a clip then cutting it rescanned minutes of video for nothing.
    """
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"x")
    root = tmp_path / "clips"
    kills = [{"time": 8478.1, "count": 1}]
    a_sidecar(root, "run1", src, [7917.7, 10413.4], kills)
    app = an_app(monkeypatch, root)

    # The caller resolves "to the end" to the real duration before asking.
    got = app._cached_kills(src, None, (7917.68, 10413.4))
    assert got == kills, "the review's kills were not reused"


def test_a_scan_that_stopped_short_is_not_reused(monkeypatch, tmp_path):
    """The reason the check exists: a windowed scan's kill list is complete
    only inside its window, so reusing it for footage it never read would
    report "no kills" for a stretch full of them."""
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"x")
    root = tmp_path / "clips"
    a_sidecar(root, "run1", src, [0.0, 600.0], [{"time": 10.0, "count": 1}])
    app = an_app(monkeypatch, root)

    assert app._cached_kills(src, None, (0.0, 3600.0)) is None


def test_an_unknown_duration_still_refuses(monkeypatch, tmp_path):
    """want_b of 0 now only happens when the file could not be probed, and
    then nothing windowed may be reused."""
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"x")
    root = tmp_path / "clips"
    a_sidecar(root, "run1", src, [100.0, 900.0], [{"time": 200.0, "count": 1}])
    app = an_app(monkeypatch, root)

    assert app._cached_kills(src, None, (100.0, 0.0)) is None


def test_a_whole_file_scan_is_still_reused_by_anything(monkeypatch, tmp_path):
    """[0, 0] means the whole file was read, which covers every window."""
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"x")
    root = tmp_path / "clips"
    kills = [{"time": 5.0, "count": 2}]
    a_sidecar(root, "run1", src, [0.0, 0.0], kills)
    app = an_app(monkeypatch, root)

    assert app._cached_kills(src, None, (900.0, 1800.0)) == kills


# ------------------------------------------------- saying why there are none

def test_a_run_that_plans_nothing_explains_itself():
    """"0 clips" alone reads as a failure. The run found 13 kills, planned
    nothing because every one was a single and the minimum was 2, and swept
    them all into the promo reel. It knew all of that and said none of it."""
    src = Path(webui.__file__).parent / "clips" / "jobs.py"
    body = src.read_text(encoding="utf-8")
    i = body.index("summary = plan.summarise(kills, plans)")
    block = body[i:i + 1400]
    assert 'summary["why"]' in block
    assert "promo reel" in block, "it must say where the kills actually went"
    assert "minimum to 1" in block, "it must say what to do about it"


def test_the_page_shows_that_reason_instead_of_a_bare_zero():
    from autostream.ui import clips as clips_ui

    assert "sum.why" in clips_ui.CLIPS_JS
    i = clips_ui.CLIPS_JS.index("if (!j.clips && sum.why)")
    assert "sub = sum.why" in clips_ui.CLIPS_JS[i:i + 120]


def test_the_caller_resolves_to_the_end_before_asking_the_cache():
    """WHERE THE BUG ACTUALLY WAS. The cache was asked with the raw option,
    and scan_end of 0 means "to the end of the file" -- so the coverage test
    got a falsy end and refused every windowed scan. Resolving it to the real
    duration is the fix; the comparison was only ever the symptom."""
    body = Path(webui.__file__).read_text(encoding="utf-8")
    i = body.index("cached = self._cached_kills(")
    before = body[max(0, i - 900):i]
    assert "media_info(path)" in before, "scan_end is still passed unresolved"
    assert "want_b" in body[i:i + 200], "the resolved end is not the one used"
