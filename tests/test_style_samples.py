"""Style samples (M6), set-valued template picks (M3), the build-then-drop layout (K4) and the
drop detector (D1 prototype). Offline: no ffmpeg, no network."""
from __future__ import annotations

import numpy as np

from autostream.clips import beatsync, studio, style_samples as ss


def _clip(tmp_path, name, kills=(3.0,)):
    p = tmp_path / f"{name}.mp4"
    p.write_bytes(b"x" * 10)
    return {"path": str(p), "kills": list(kills)}


def test_key_is_stable_and_follows_what_a_sample_shows(tmp_path):
    a = [_clip(tmp_path, "a"), _clip(tmp_path, "b")]
    k = ss.key_of(a, "landscape")
    assert k == ss.key_of(a, "landscape") and len(k) == 16
    assert k != ss.key_of(a, "vertical")
    assert k != ss.key_of(a[:1], "landscape")
    assert k != ss.key_of(a, "landscape", part=(10.0, 40.0))
    assert k != ss.key_of([dict(a[0], kills=[4.0]), a[1]], "landscape")


def test_only_the_first_few_clips_are_used():
    rows = [{"path": f"c{i}.mp4"} for i in range(20)]
    assert len(ss.pick_clips(rows)) == ss.SAMPLE_CLIPS


def test_ready_lists_only_finished_non_empty_samples(tmp_path):
    key = "0123456789abcdef"
    d = ss.folder(tmp_path, key)
    d.mkdir(parents=True)
    (d / "hype.mp4").write_bytes(b"data")
    (d / "story.mp4").write_bytes(b"")
    assert ss.ready(tmp_path, key, ["hype", "story", "chaos"]) == {"hype": "hype.mp4"}
    assert ss.path_for(tmp_path, key, "story") is None


def test_runner_with_nothing_missing_starts_nothing(tmp_path):
    clips = [_clip(tmp_path, "a")]
    key = ss.key_of(clips, "landscape")
    d = ss.folder(tmp_path, key)
    d.mkdir(parents=True)
    (d / "hype.mp4").write_bytes(b"data")
    r = ss._Runner()
    st = r.start(tmp_path, clips, "landscape", ["hype"])
    assert st["state"] == "done" and st["total"] == 0 and not r.busy()


def test_a_list_pick_is_a_pool_and_a_repeat_is_a_weight():
    got = studio._picked(["t01", "t02", "t01", "nope"], "transition")
    assert got == ["t01", "t02", "t01"]
    assert studio._picked("t01", "transition") == ["t01"]


def test_build_then_drop_puts_the_first_kill_exactly_on_the_drop():
    beat = 0.4
    hits = [round(i * beat, 3) for i in range(1, 200)]
    out = studio.build_then_drop(hits, [1.0] * len(hits), first=20.0, drop=30.0, count=14,
                                 beat=beat, gap=0.4, end=80.0)
    assert 30.0 in out
    before = [t for t in out if t < 30.0]
    assert before and all(b - a >= 0.9 * studio.BUILD_BEATS * beat for a, b in zip(before, before[1:]))
    after = [t for t in out if t > 30.0]
    assert after and min(after) >= 30.0 + 0.4 - 1e-6


def test_entrances_are_empty_on_a_short_signal():
    assert beatsync.find_entrances(np.zeros(1000, dtype=np.float32)) == []
