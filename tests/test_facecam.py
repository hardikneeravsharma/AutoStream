"""The facecam and the player's own clips: where the camera comes from, where it
goes, and how a file the player brings becomes a clip the Studio can use.

No ffmpeg here: the layouts and the links are arithmetic and files, and the
renders they drive are measured in tests/verify.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from autostream.clips import facecam, studio, tools, uploads


# ------------------------------------------------------------------ layouts

def test_a_vertical_stack_puts_the_camera_across_the_top():
    cam = facecam.settings({"source": "inset", "layout": "stack", "split": 0.4})
    lay = facecam.layout("vertical", 1080, 1920, cam, "zoom", True)
    assert lay["cam"] == [0, 0, 1080, 768]
    assert lay["game"] == [0, 768, 1080, 1152]


def test_a_landscape_reel_never_stacks():
    cam = facecam.settings({"source": "inset", "layout": "stack"})
    lay = facecam.layout("landscape", 1920, 1080, cam, "zoom", True)
    assert lay["game"] == [0, 0, 1920, 1080]
    x, y, w, h = lay["cam"]
    assert 0 <= x and x + w <= 1920 and 0 <= y and y + h <= 1080


@pytest.mark.parametrize("pos", [[0, 0], [1, 0], [0, 1], [1, 1], [0.5, 0.5]])
def test_a_corner_camera_stays_inside_the_frame_wherever_it_is_put(pos):
    cam = facecam.settings({"source": "inset", "layout": "corner", "pos": pos, "size": 0.45,
                            "box": [0.7, 0.0, 0.3, 0.3]})
    for fmt, W, H in (("vertical", 1080, 1920), ("landscape", 1920, 1080)):
        x, y, w, h = facecam.layout(fmt, W, H, cam, "zoom", True)["cam"]
        assert 0 <= x <= W - w and 0 <= y <= H - h, (fmt, pos)
        assert w % 2 == 0 and h % 2 == 0


def test_a_camera_box_keeps_its_shape():
    """A square cut of a 16:9 frame is 9/16 as tall as it is wide in pixels."""
    cam = facecam.settings({"source": "inset", "layout": "corner", "box": [0, 0, 0.25, 0.25]})
    _, _, w, h = facecam.layout("landscape", 1920, 1080, cam, "zoom", True)["cam"]
    assert h / w == pytest.approx(9 / 16, abs=0.02)


def test_junk_settings_are_clamped():
    got = facecam.settings({"source": "hack", "box": [-1, 2, 9, "x"], "split": 5,
                            "pos": ["a"], "size": -3, "layout": "../"})
    assert got["source"] == "none" and got["layout"] == "stack"
    assert got["split"] == 0.6 and got["size"] == 0.12 and got["pos"] == [0.0, 0.0]
    x, y, w, h = got["box"]
    assert 0 <= x <= 1 - w and 0 <= y <= 1 - h


# ------------------------------------------------------------------ the project

@pytest.fixture
def root(tmp_path):
    return tmp_path


def _run(root: Path, name: str, start: float = 100.0) -> Path:
    run = root / name
    (run / "clips").mkdir(parents=True)
    clip = run / "clips" / "a.mp4"
    clip.write_bytes(b"x")
    (run / "clips.json").write_text(json.dumps({"game": "VALORANT", "clips": [{
        "name": "A", "master": str(clip), "start": start, "end": start + 10, "duration": 10}]}))
    (run / "session.json").write_text(json.dumps({"game": "VALORANT",
                                                  "kills": [{"time": start + 4}]}))
    return clip


def test_a_run_link_offsets_each_clip_by_where_it_starts(root, tmp_path):
    clip = _run(root, "2026-09-01_VALORANT", start=100.0)
    cam = tmp_path / "cam.mp4"
    cam.write_bytes(b"x")
    assert facecam.link(root, facecam.key_for(clip), str(cam), 2.5)["ok"]
    assert facecam.for_clip(root, clip) == (str(cam), 102.5)
    # a clip's own link wins
    own = tmp_path / "own.mp4"
    own.write_bytes(b"x")
    facecam.link(root, studio.clip_id(clip), str(own), 1.0)
    assert facecam.for_clip(root, clip) == (str(own), 1.0)


def test_only_a_video_file_can_be_linked(root, tmp_path):
    clip = _run(root, "r")
    bad = tmp_path / "token.json"
    bad.write_text("{}")
    assert not facecam.link(root, facecam.key_for(clip), str(bad))["ok"]
    assert not facecam.link(root, facecam.key_for(clip), str(tmp_path / "missing.mp4"))["ok"]


def test_the_project_gets_facecam_files_from_the_links_never_the_page(root, tmp_path, monkeypatch):
    clip = _run(root, "r")
    cam = tmp_path / "cam.mp4"
    cam.write_bytes(b"x")
    facecam.link(root, facecam.key_for(clip), str(cam), 0.0)
    proj = {"format": "vertical", "cam": {"source": "file"},
            "shots": [{"clip": str(clip), "kills": [4.0], "kill": 4.0, "duration": 3.0, "pre": 1.5,
                       "cam_file": r"C:\Windows\System32\secret.mp4"}]}
    got, derived, _ = studio.normalise(proj, root, probe=lambda p: 10.0)
    assert got["shots"][0]["cam_file"] == str(cam)
    seg = studio.segments(got, derived)[0]
    assert seg.cam_file == str(cam) and seg.layout["cam"]
    cmd = studio.segment_command(seg, Path("o.mp4"))
    assert cmd.count("-i") == 2 and str(cam) in cmd


def test_a_plain_reel_renders_and_caches_exactly_as_before(root):
    """No layout, no hold, no camera: the shot's key must not change, or every
    cached shot of every reel would be rendered again."""
    clip = _run(root, "r")
    proj = {"shots": [{"clip": str(clip), "kills": [4.0], "kill": 4.0, "duration": 3.0, "pre": 1.5}]}
    got, derived, _ = studio.normalise(proj, root, probe=lambda p: 10.0)
    seg = studio.segments(got, derived)[0]
    assert seg.layout == {} and seg.hold == 0 and seg.cam_file == ""
    d = dict(seg.__dict__)
    for k in ("hold", "layout", "cam_file", "cam_start"):
        d.pop(k)
    d.pop("index")
    assert seg.key() == hashlib.sha1(json.dumps(d, sort_keys=True, default=str)
                                     .encode("utf-8")).hexdigest()[:20]


def test_a_long_ending_holds_the_last_frame_so_the_fade_misses_the_kill(root):
    clip = _run(root, "r")
    proj = {"outro": "e01", "outro_len": 4.0,
            "shots": [{"clip": str(clip), "kills": [4.0], "kill": 4.0, "duration": 2.0, "pre": 1.5}]}
    got, derived, _ = studio.normalise(proj, root, probe=lambda p: 10.0)
    assert derived["outro_hold"] == pytest.approx(1.5 + studio.OUTRO_AFTER_KILL + 4.0 - 2.0)
    assert derived["length"] == pytest.approx(2.0 + derived["outro_hold"])
    seg = studio.segments(got, derived)[-1]
    assert seg.hold == round(derived["outro_hold"] * studio.FPS)
    assert "tpad=stop_mode=clone" in " ".join(studio.segment_command(seg, Path("o.mp4")))
    cmd = " ".join(studio.assemble_command(got, derived, [seg], [Path("0.mp4")], Path("r.mp4")))
    L = derived["length"]
    assert f"fade=out:st={L - 4.0:.4f}:d=4.0000" in cmd


def test_the_handle_goes_where_it_is_put(root):
    clip = _run(root, "r")
    proj = {"overlays": ["o07"], "handle": "@me", "handle_pos": [0.0, 0.25],
            "shots": [{"clip": str(clip), "kills": [4.0], "kill": 4.0, "duration": 3.0, "pre": 1.5}]}
    got, derived, _ = studio.normalise(proj, root, probe=lambda p: 10.0)
    assert got["handle_pos"] == [0.0, 0.25]
    segs = studio.segments(got, derived)
    cmd = " ".join(studio.assemble_command(got, derived, segs, [Path("0.mp4")], Path("r.mp4"),
                                           textdir=root))
    assert "*0.0000:y=" in cmd and "*0.2500" in cmd


# ------------------------------------------------------------------ imported clips

@pytest.fixture
def probe10(monkeypatch):
    monkeypatch.setattr(tools, "media_info", lambda p: {"duration": 12.5})


def test_an_added_file_becomes_a_clip_in_the_library(root, tmp_path, probe10):
    src = tmp_path / "my ace.mp4"
    src.write_bytes(b"video")
    got = uploads.add(root, str(src), game="VALORANT", title="ACE")
    assert got["ok"], got
    clip = Path(got["clip"]["path"])
    assert clip.is_file() and clip.parent.parent.name.startswith(uploads.PREFIX)
    assert src.is_file(), "the player's own file must be left where it was"
    saved = uploads.save(root, str(clip), [3.0, 1.2, 99.0, "x"], title="1v3 clutch")
    assert saved["kills"] == [1.2, 3.0]
    lib = studio.library(root)
    c = lib["games"][0]["folders"][0]["clips"][0]
    assert c["name"] == "1v3 clutch" and c["kills"] == [1.2, 3.0] and c["kill_count"] == 2
    assert uploads.info(root, str(clip))["title"] == "1v3 clutch"


def test_only_a_video_can_be_added(root, tmp_path, probe10):
    bad = tmp_path / "config.yaml"
    bad.write_text("x")
    assert not uploads.add(root, str(bad))["ok"]


def test_marks_can_only_be_saved_on_an_imported_clip(root):
    clip = _run(root, "2026-09-01_VALORANT")
    assert not uploads.save(root, str(clip), [1.0])["ok"]
    assert not uploads.save(root, str(root.parent / "import-x" / "clips" / "a.mp4"), [1.0])["ok"]


# ------------------------------------------------------------------ lining up

def test_the_offset_is_found_from_the_sound_both_share(monkeypatch):
    """The camera started 7.3 s before the game: its sound is the game's,
    7.3 s later in the file."""
    import numpy as np
    rng = np.random.default_rng(3)
    rate, true = 100, 7.3
    world = rng.standard_normal(rate * 400)              # 400 s of onsets
    game_t = 150.0

    def env(path, start, seconds, rate=100):
        # the game file's clock is world time; the camera's is world + true
        at = start - (true if str(path) == "cam" else 0.0)
        i = int(round(at * rate))
        return world[max(0, i):i + int(seconds * rate)].copy()
    monkeypatch.setattr(facecam, "_envelope", env)
    got = facecam.sync(Path("game"), game_t, Path("cam"), guess=0.0, window=30, search=20)
    assert got["ok"], got
    assert got["offset"] == pytest.approx(true, abs=0.02)


def test_noise_that_lines_up_nowhere_is_refused(monkeypatch):
    import numpy as np
    rng = np.random.default_rng(5)
    monkeypatch.setattr(facecam, "_envelope",
                        lambda path, start, seconds, rate=100: rng.standard_normal(int(seconds * rate)))
    got = facecam.sync(Path("game"), 10.0, Path("cam"), window=30, search=20)
    assert not got["ok"] and "by ear" in got["error"]
