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
    for k in ("hold", "layout", "cam_file", "cam_start", "groove"):
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


def test_marks_can_be_saved_on_any_clip_in_the_clips_folder(root):
    """THIS USED TO REFUSE. The marker was gated on `imported`, so a clip
    AutoStream cut for itself had no way back into it at all: a kill the
    detector put half a second late could not be corrected and a clip could
    not be retitled. The marker itself never cared where a clip came from --
    what was missing was the way in."""
    clip = _run(root, "2026-09-01_VALORANT", start=100.0)
    got = uploads.save(root, str(clip), [1.0, 4.5])
    assert got["ok"], got
    assert got["kills"] == [1.0, 4.5]


def test_a_correction_does_not_move_the_other_clips_in_the_run(root):
    """A run's session.json describes the whole RECORDING and every clip cut
    from it reads its kill pips out of it. Writing one clip's correction
    there would move all forty and break the next re-cut -- from a dialog
    that said Save."""
    clip = _run(root, "2026-09-01_VALORANT", start=100.0)
    before = json.loads((root / "2026-09-01_VALORANT" / "session.json")
                        .read_text(encoding="utf-8"))
    uploads.save(root, str(clip), [2.0])
    after = json.loads((root / "2026-09-01_VALORANT" / "session.json")
                       .read_text(encoding="utf-8"))
    assert after["kills"] == before["kills"], (
        "a correction to one clip rewrote the recording's kill list")


def test_the_correction_is_what_comes_back(root):
    clip = _run(root, "2026-09-01_VALORANT", start=100.0)
    # The recording has a kill at 104s, which is 4s into this clip.
    assert uploads.info(root, str(clip))["kills"] == [4.0]
    uploads.save(root, str(clip), [6.25])
    assert uploads.info(root, str(clip))["kills"] == [6.25]


def test_a_detected_clips_kills_are_offered_in_clip_seconds(root):
    """The two halves store them differently: an import's are already
    clip-relative, a run's are recording-relative. A clip starting 42 minutes
    in would otherwise open with its first mark at 2520 seconds, off the end
    of a thirty-second clip."""
    clip = _run(root, "2026-09-01_VALORANT", start=2500.0)
    assert uploads.info(root, str(clip))["kills"] == [4.0]


def test_a_path_outside_the_clips_folder_is_still_refused(root):
    """The guard that has to survive: this writes JSON next to whatever it is
    given, and the page is not the only thing that can call it."""
    assert not uploads.save(
        root, str(root.parent / "import-x" / "clips" / "a.mp4"), [1.0])["ok"]
    assert not uploads.info(
        root, str(root.parent / "elsewhere" / "clips" / "a.mp4"))["ok"]


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


# ---------------------------------------- S1: a folder of clips, in one go

def test_a_batch_is_imported_one_after_another(root, tmp_path, probe10,
                                                monkeypatch):
    """Somebody with a folder of twenty did the whole dance twenty times:
    open the dialog, choose one, wait, mark, save, press Add again."""
    srcs = []
    for i in range(3):
        f = tmp_path / f"clip{i}.mp4"
        f.write_bytes(b"x" * 10)
        srcs.append(f)

    got = [uploads.add(root, str(f)) for f in srcs]
    assert all(g["ok"] for g in got), got
    paths = [g["clip"]["path"] for g in got]
    assert len(set(paths)) == 3, "two imports landed on the same path"
    for p in paths:
        assert uploads.info(root, p)["ok"]


def test_each_imported_clip_keeps_its_own_marks(root, tmp_path, probe10):
    """The reason a batch needs its own walk: twenty clips each want their
    own kills, and one set shared between them is worse than none."""
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    a.write_bytes(b"x" * 10)
    b.write_bytes(b"y" * 10)
    pa = uploads.add(root, str(a))["clip"]["path"]
    pb = uploads.add(root, str(b))["clip"]["path"]

    uploads.save(root, pa, [1.0, 2.0])
    uploads.save(root, pb, [5.0])

    assert uploads.info(root, pa)["kills"] == [1.0, 2.0]
    assert uploads.info(root, pb)["kills"] == [5.0]


@pytest.mark.parametrize("vfit,crop", [("fit", False), ("near", True), ("zoom", None)])
def test_near_fit_shows_the_middle_three_quarters_over_the_blurred_copy(root, vfit, crop):
    """F16: full fit left the game a third of the 9:16 height. Near fit keeps the middle
    75 % of the width -- minimap and kill feed mostly stay -- a third taller."""
    clip = _run(root, "r")
    proj = {"format": "vertical", "vfit": vfit,
            "shots": [{"clip": str(clip), "kills": [4.0], "kill": 4.0, "duration": 3.0, "pre": 1.5}]}
    got, derived, _ = studio.normalise(proj, root, probe=lambda p: 10.0)
    assert got["vfit"] == vfit
    seg = studio.segments(got, derived)[0]
    cmd = " ".join(studio.segment_command(seg, Path("o.mp4")))
    if crop is None:
        assert seg.layout == {} and "boxblur" not in cmd
        return
    assert seg.layout["fit"] == vfit and "boxblur" in cmd
    assert ("crop=iw*0.75:ih:iw*0.125:0" in cmd) is crop
    assert studio.retime_height(seg) == (1080 if crop else 720)


def test_an_unknown_framing_is_zoom(root):
    clip = _run(root, "r")
    proj = {"format": "vertical", "vfit": "stretch",
            "shots": [{"clip": str(clip), "kills": [4.0], "kill": 4.0, "duration": 3.0, "pre": 1.5}]}
    got, _, _ = studio.normalise(proj, root, probe=lambda p: 10.0)
    assert got["vfit"] == "zoom"


# ------------------------------------------------------------------ the frame set by hand, and what is behind it

def _vertical(root, **extra):
    clip = _run(root, "r")
    proj = {"format": "vertical", "shots": [{"clip": str(clip), "kills": [4.0], "kill": 4.0, "duration": 3.0, "pre": 1.5}],
            **extra}
    got, derived, notes = studio.normalise(proj, root, probe=lambda p: 10.0)
    return got, studio.segments(got, derived), notes


def test_a_hand_set_frame_crops_the_width_it_keeps_from_where_it_was_put(root):
    """keep 0.6 of the width, from its left third, the band a third of the way down"""
    got, segs, _ = _vertical(root, vfit="custom", frame={"keep": 0.6, "x": 0.3, "y": 0.35})
    assert got["vfit"] == "custom" and got["frame"] == {"keep": 0.6, "x": 0.3, "y": 0.35}
    seg = segs[0]
    assert seg.layout["fit"] == "custom" and seg.layout["frame"]["keep"] == 0.6
    cmd = " ".join(studio.segment_command(seg, Path("o.mp4")))
    assert "crop=iw*0.6000:ih*1.0000:(iw-iw*0.6000)*0.3000" in cmd
    h = 1012                                     # 1080 * 9/16 / 0.6, to an even pixel
    assert f"scale=1080:{h}" in cmd and f"overlay=0:{round((1920 - h) * 0.35)}" in cmd
    assert studio.game_band(got) == (round((1920 - h) * 0.35), h)


def test_a_frame_zoomed_past_filling_crops_rows_too_and_fills_the_frame(root):
    got, segs, _ = _vertical(root, vfit="custom", frame={"keep": 0.25})
    cmd = " ".join(studio.segment_command(segs[0], Path("o.mp4")))
    assert "scale=1080:1920" in cmd and "overlay=0:0" in cmd
    assert studio.game_band(got) is None         # the game is the whole frame
    assert studio.retime_height(segs[0]) == 1080


def test_junk_frames_are_clamped(root):
    got, _, _ = _vertical(root, vfit="custom", frame={"keep": "x", "x": 9, "y": -3})
    assert got["frame"] == {"keep": studio.NEAR_KEEP, "x": 1.0, "y": 0.0}


def test_the_presets_render_exactly_as_before_and_carry_no_background(root):
    for fit in ("fit", "near"):
        got, segs, _ = _vertical(root / fit, vfit=fit)
        assert "bg" not in got and "frame" not in got and "bg" not in segs[0].layout
        assert "boxblur=24:2,eq=brightness=-0.12:saturation=0.8" in " ".join(studio.segment_command(segs[0], Path("o.mp4")))


@pytest.mark.parametrize("bg,want", [({"kind": "black"}, "color=c=0x000000"),
                                     ({"kind": "color", "color": "#203040"}, "color=c=0x203040"),
                                     ({"kind": "blur", "blur": 8, "dim": 0.3}, "boxblur=8:2,eq=brightness=-0.300")])
def test_behind_the_band_is_what_was_chosen(root, bg, want):
    got, segs, _ = _vertical(root, vfit="near", bg=bg)
    assert got["bg"]["kind"] == bg["kind"]
    cmd = " ".join(studio.segment_command(segs[0], Path("o.mp4")))
    assert want in cmd and cmd.count(" -i ") == 1          # no file of its own


def test_a_motion_background_loops_on_across_the_cuts(root, tmp_path, monkeypatch):
    home = tmp_path / "videos"
    (home / "backgrounds").mkdir(parents=True)
    loop = home / "backgrounds" / "waves.mp4"
    loop.write_bytes(b"x")
    from autostream import paths
    monkeypatch.setattr(paths, "VIDEO_HOME", home)
    clip = _run(root, "r")
    shot = {"clip": str(clip), "kills": [4.0], "kill": 4.0, "duration": 3.0, "pre": 1.5}
    proj = {"format": "vertical", "vfit": "near", "bg": {"kind": "file", "file": str(loop)}, "shots": [dict(shot), dict(shot)]}
    got, derived, notes = studio.normalise(proj, root, probe=lambda p: 10.0 if p == loop.resolve() else 10.0)
    assert got["bg"]["file"] == str(loop.resolve()) and got["bg"]["dim"] == studio.BG_FILE_DIM and not notes
    segs = studio.segments(got, derived)
    cmd = studio.segment_command(segs[1], Path("o.mp4"))
    at = segs[1].layout["bg"]["at"]
    assert 2.9 < at < 3.1                                   # the second shot starts 3 s into the reel
    i = cmd.index(str(loop.resolve()))
    assert cmd[i - 5:i] == ["-ss", f"{at:.3f}", "-t", cmd[i - 2], "-i"] and cmd[i - 7:i - 5] == ["-stream_loop", "-1"]
    assert "[1:v]fps=60" in " ".join(cmd)                    # the loop's own input, after the clip


def test_a_background_outside_the_folder_falls_back_and_says_so(root, tmp_path, monkeypatch):
    from autostream import paths
    monkeypatch.setattr(paths, "VIDEO_HOME", tmp_path / "videos")
    stray = tmp_path / "secret.mp4"
    stray.write_bytes(b"x")
    got, segs, notes = _vertical(root, vfit="near", bg={"kind": "file", "file": str(stray)})
    assert "bg" not in got and any("backgrounds folder" in n for n in notes)
    assert str(stray) not in " ".join(studio.segment_command(segs[0], Path("o.mp4")))


def test_backgrounds_are_listed_only_from_their_folders(tmp_path, monkeypatch):
    from autostream import paths
    home = tmp_path / "videos"
    for d, f in (("backgrounds", "a.png"), ("assets/backgrounds", "b.mp4"), ("songs", "c.mp4")):
        (home / d).mkdir(parents=True, exist_ok=True)
        (home / d / f).write_bytes(b"x")
    (home / "backgrounds" / "notes.txt").write_text("x")
    monkeypatch.setattr(paths, "VIDEO_HOME", home)
    got = studio.backgrounds()
    assert [(i["name"], i["kind"]) for i in got] == [("a", "image"), ("b", "video")]
    assert studio.bg_allowed(str(home / "songs" / "c.mp4")) is None
    assert studio.bg_allowed(str(home / "backgrounds" / "notes.txt")) is None
