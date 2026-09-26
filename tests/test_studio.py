"""The Studio: every clip on disk, and reels planned and rendered from them.

No ffmpeg here -- the render is measured in tests/verify/test_studio_render.py.
These pin the arithmetic the render trusts: where each clip's kills are, where
every cut and kill lands on the song, and what the page is refused.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from autostream.clips import rulebook, studio, studio_refs


# ------------------------------------------------------------------ fixtures

def _run(root: Path, name: str, game: str, clips: list[dict], kills: list[float],
         pre_roll: float = 3.5) -> Path:
    folder = root / name
    (folder / "clips").mkdir(parents=True)
    rows = []
    for i, c in enumerate(clips):
        master = folder / "clips" / f"{game}_{i:02d}.mp4"
        master.write_bytes(b"not really a video")
        rows.append({"rank": i + 1, "start": c["start"], "end": c["end"],
                     "duration": c["end"] - c["start"], "kills": c.get("kills", 1),
                     "name": master.stem, "master": str(master), "vertical": "",
                     "caption": c.get("caption", ""), "tags": [], "at": ""})
    (folder / "clips.json").write_text(json.dumps({"game": game, "clips": rows}))
    (folder / "session.json").write_text(json.dumps(
        {"game": game, "kills": [{"time": k} for k in kills],
         "options": {"pre_roll": pre_roll}}))
    return folder


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "clips"
    _run(r, "2026-09-14_0045_VALORANT", "VALORANT",
         [{"start": 100.0, "end": 108.0}, {"start": 200.0, "end": 214.0, "kills": 2},
          {"start": 300.0, "end": 305.5}], kills=[103.5, 203.0, 206.5, 303.5])
    _run(r, "2026-08-22_2151_Counter-Strike-2_shortform", "Counter-Strike 2",
         [{"start": 10.0, "end": 18.0}], kills=[])
    (r / "reels").mkdir()
    (r / ".studio").mkdir()
    return r


@dataclass
class Shape:
    """Just what the planner reads off a real song analysis."""
    bpm: float = 120.0
    seconds: float = 240.0
    phase: float = 0.1
    drop: float | None = None
    drums_in: float | None = None
    downbeat_pos: int = 0
    beats: list = field(default_factory=list)
    hits: list = field(default_factory=list)      # bass hits, song seconds
    big: list = field(default_factory=list)

    @property
    def beat(self) -> float:
        return 60.0 / self.bpm

    def __post_init__(self):
        if not self.beats:
            n = int((self.seconds - self.phase) / self.beat)
            self.beats = [self.phase + i * self.beat for i in range(n)]


def _clips(root):
    lib = studio.library(root)
    return [c for g in lib["games"] for f in g["folders"] for c in f["clips"]]


def _on_grid(t: float, beat: float, tol: float = 1e-3) -> bool:
    return abs(t / beat - round(t / beat)) * beat < tol


# ------------------------------------------------------------------ library

def test_the_library_groups_clips_by_game_then_run(root):
    lib = studio.library(root)
    assert lib["clip_count"] == 4
    games = {g["game"]: g for g in lib["games"]}
    assert set(games) == {"VALORANT", "Counter-Strike 2"}
    assert games["VALORANT"]["folders"][0]["label"].startswith("14 Sep 2026, 00:45")


def test_each_kill_is_placed_inside_its_own_clip(root):
    """A master starts at the clip's `start`, so a kill's place in the file is
    its recording time minus that start."""
    val = next(g for g in studio.library(root)["games"] if g["game"] == "VALORANT")
    clips = val["folders"][0]["clips"]
    assert clips[0]["kills"] == [3.5]
    assert clips[1]["kills"] == [3.0, 6.5]


def test_a_run_without_kill_times_uses_its_pre_roll(root):
    cs = next(g for g in studio.library(root)["games"] if g["game"] == "Counter-Strike 2")
    assert cs["folders"][0]["clips"][0]["kills"] == [3.5]


def test_a_clip_whose_file_is_gone_is_left_out(root):
    Path(_clips(root)[0]["path"]).unlink()
    assert studio.library(root)["clip_count"] == 3


def test_reels_and_hidden_folders_are_not_runs(root):
    names = [f["name"] for g in studio.library(root)["games"] for f in g["folders"]]
    assert "reels" not in names and ".studio" not in names


def test_a_reel_with_a_project_can_be_reopened(root):
    (root / "reels" / "old.mp4").write_bytes(b"x")
    (root / "reels" / "new.mp4").write_bytes(b"x")
    (root / "reels" / "new.reel.json").write_text(json.dumps({"name": "New", "shots": [{}, {}]}))
    by = {r["name"]: r for r in studio.reels(root)}
    assert by["New"]["project"] and by["New"]["shots"] == 2
    assert by["old"]["project"] == ""


# ------------------------------------------------------------------ speed

@pytest.mark.parametrize("speed", ["s00", "s01", "s02", "s03", "s04", "s05", "s06", "exit"])
def test_speed_pieces_tile_the_shot_exactly(speed):
    ps = studio.pieces(speed, 3.0, 1.5)
    assert ps[0][0] == 0.0 and ps[-1][1] == pytest.approx(3.0)
    for (_, b, _), (a, _, _) in zip(ps, ps[1:]):
        assert a == pytest.approx(b)


@pytest.mark.parametrize("speed", ["s00", "s01", "s02", "s03", "s04", "s05", "s06"])
def test_output_at_inverts_source_used(speed):
    ps = studio.pieces(speed, 3.0, 1.5)
    for t in (0.0, 0.4, 1.5, 2.2, 3.0):
        assert studio.output_at(ps, studio.source_used(ps, t)) == pytest.approx(t, abs=1e-6)


def test_the_kill_is_never_inside_a_sped_up_piece():
    for speed in ("s02", "s03", "s04", "s05", "s06"):
        for a, b, r in studio.pieces(speed, 3.0, 1.5):
            if a <= 1.5 < b:
                assert r <= 1.0


# ------------------------------------------------------------------ planning

@pytest.mark.parametrize("style", [s.key for s in studio.STYLES])
def test_every_cut_and_every_kill_lands_on_the_beat(root, style):
    shape = Shape(bpm=162.0, drop=120.0, drums_in=30.0)
    proj, _ = studio.plan(_clips(root), style, shape=shape, song="song.mp3")
    proj["song"] = ""                         # nothing on disk; the arithmetic is the point
    beat = shape.beat
    t = 0.0
    for s in proj["shots"]:
        assert _on_grid(t, beat), f"{style}: cut at {t}"
        assert _on_grid(t + s["pre"], beat), f"{style}: kill at {t + s['pre']}"
        t += s["duration"]
    # Reel zero is a beat of the song, so reel beats are song beats.
    assert any(abs(proj["song_offset"] - b) < 1e-4 for b in shape.beats)


def test_the_drop_style_lands_a_kill_on_the_drop(tmp_path):
    r = tmp_path / "clips"
    _run(r, "2026-09-01_1200_VALORANT", "VALORANT",
         [{"start": 100.0 * i, "end": 100.0 * i + 12} for i in range(1, 9)],
         kills=[100.0 * i + 6 for i in range(1, 9)])
    shape = Shape(bpm=120.0, seconds=300.0, phase=0.0, drop=96.0)
    proj, _ = studio.plan(_clips(r), "drop", shape=shape, song="x.mp3")
    starts = studio._starts(proj["shots"])
    kill_on_drop = starts[3] + proj["shots"][3]["pre"] + proj["song_offset"]
    assert kill_on_drop == pytest.approx(96.0, abs=1e-6)


def test_pace_is_the_measured_median_as_a_power_of_two_in_beats():
    """At 120 BPM a style measured at ~30 cuts/min is 4-beat shots."""
    meas = studio_refs.summary(studio.STYLE["montage"].refs)
    beats = studio._pow2_beats(60.0 / meas["cuts_per_min"], 0.5, lo=1, hi=8)
    assert beats in (2, 4, 8)
    assert abs(math.log2(beats) - math.log2(60.0 / meas["cuts_per_min"] / 0.5)) <= 0.5 + 1e-9


def test_flashes_come_at_the_reference_rate_on_the_grid(tmp_path):
    """Flashes are spaced at the rate the style's references flash at, on the
    grid, never inside a jump-cut sequence and never beside a bright kill.

    ON THE GRID, NOT ALWAYS ON A BAR. Velocity's references flash 28 times a
    minute against 45 cuts -- two cuts in three -- and with its shots taken
    from that pace rather than rounded to a power of two beats, only one cut in
    four lands on a bar. Asking for a bar line left the reel with no flash at
    all. See rulebook.transitions.
    """
    r = tmp_path / "clips"
    _run(r, "2026-09-01_1200_VALORANT", "VALORANT",
         [{"start": 100.0 * i, "end": 100.0 * i + 12} for i in range(1, 25)],
         kills=[100.0 * i + 6 for i in range(1, 25)])
    proj, _ = studio.plan(_clips(r), "velocity", shape=Shape(bpm=120.0))
    beat = proj["beat"]
    shots = proj["shots"]
    meas = studio_refs.summary(studio.STYLE["velocity"].refs)
    share = min(0.9, meas["flashes_per_min"] / meas["cuts_per_min"])
    flashes = [i for i in range(1, len(shots)) if shots[i]["transition"] == "t02"]
    assert flashes, "a velocity reel with twenty cuts has no flash at all"
    assert len(flashes) <= share * (len(shots) - 1) + 1
    step = proj["step"]
    first_kill = round(shots[0]["pre"] / step)
    starts = [round(t / step) for t in studio._starts(shots)]
    div = round(beat / step)
    bar = 4 * div
    on_bars = sum(1 for i in range(1, len(shots)) if starts[i] % bar == first_kill % bar)
    unit = bar if on_bars >= share * (len(shots) - 1) else div
    for i in flashes:
        assert starts[i] % unit == first_kill % unit, f"flash at step {starts[i]} is off the grid"
        assert shots[i]["clip"] != shots[i - 1]["clip"]
        assert not (set(shots[i]["fx"]) & set(rulebook.BRIGHT_KILL) and shots[i]["pre"] < rulebook.BRIGHT_GAP)


def test_without_a_song_the_reel_is_cut_to_120_bpm(root):
    proj, _ = studio.plan(_clips(root), "story")
    assert proj["beat"] == pytest.approx(0.5)
    assert proj["song"] == "" and proj["song_offset"] == 0.0


def test_the_reel_never_outlasts_the_song(tmp_path):
    r = tmp_path / "clips"
    _run(r, "2026-09-01_1200_VALORANT", "VALORANT",
         [{"start": 100.0 * i, "end": 100.0 * i + 12} for i in range(1, 25)],
         kills=[100.0 * i + 6 for i in range(1, 25)])
    proj, notes = studio.plan(_clips(r), "story", shape=Shape(bpm=120.0, seconds=30.0), song="s.mp3")
    assert sum(s["duration"] for s in proj["shots"]) <= 30.0
    assert any("song ends" in n for n in notes)


# ------------------------------------------------- kills on the song's hits

def _song(hits_from: float = 1.0, gap: float = 0.5, seconds: float = 240.0,
          big: list | None = None, **kw) -> Shape:
    n = int((seconds - hits_from) / gap)
    return Shape(seconds=seconds, hits=[hits_from + gap * i for i in range(n)],
                 big=big if big is not None else [], **kw)


def test_every_kill_lands_on_a_bass_hit(root):
    shape = _song()
    proj, notes = studio.plan(_clips(root), "montage", shape=shape, song="s.mp3")
    off = proj["song_offset"]
    t = 0.0
    for s in proj["shots"]:
        kill = t + s["pre"] + off
        assert min(abs(kill - h) for h in shape.hits) <= 1.0 / studio.FPS,             f"a kill at {kill:.3f} s is on no hit"
        t += s["duration"]
    assert any("bass hits" in n for n in notes)


def test_the_hits_the_kills_were_put_on_are_kept_with_the_reel(root):
    """The music lane draws each kill against the hit it was aimed at, so the
    reel has to remember which hits those were. Asking the detector again is
    not the same question: it answers at its own default pace, not the pace
    this style was cut at, and would mark hits no kill was ever put on."""
    shape = _song()
    proj, _ = studio.plan(_clips(root), "montage", shape=shape, song="s.mp3")
    marks = proj["song_marks"]
    assert marks, "the reel kept no record of the hits it was cut to"
    assert all(min(abs(m - h) for h in shape.hits) < 1e-6 for m in marks)
    off, t = proj["song_offset"], 0.0
    for s, m in zip(proj["shots"], marks):
        assert t + s["pre"] + off == pytest.approx(m, abs=1.0 / studio.FPS)
        t += s["duration"]


def test_the_timeline_is_told_how_far_each_kill_sits_from_its_hit(root, tmp_path):
    """Two implementations of "did this land on the beat" would disagree, so
    the drift is worked out where the rest of the derived times are."""
    song = tmp_path / "s.mp3"
    song.write_bytes(b"not really a song")
    proj, _ = studio.plan(_clips(root), "montage", shape=_song(), song=str(song))
    proj, derived, _ = studio.normalise(proj, root)
    assert proj["song_marks"], "checking dropped the marks"
    assert derived["marks"] and len(derived["marks"]) <= len(proj["song_marks"])
    assert derived["on_marks"] == len(derived["shots"])
    for row in derived["shots"]:
        assert abs(row["drift"]) <= studio.ON_MARK

    # Slide the reel against the song and every kill is late by that much.
    proj["song_offset"] = round(proj["song_offset"] + 0.4, 5)
    _, moved, _ = studio.normalise(proj, root)
    assert moved["on_marks"] == 0
    assert all(row["drift"] == pytest.approx(0.4, abs=0.02) for row in moved["shots"])


def test_a_reel_without_a_song_has_no_marks_to_miss(root):
    proj, derived, _ = studio.normalise(_project(root), root)
    assert derived["marks"] == [] and derived["on_marks"] == 0
    assert all(row["drift"] is None for row in derived["shots"])


def test_kills_marked_by_hand_are_remembered_as_marks(root):
    """The Song tab's marks are the same thing as the planner's hits: where
    the player said the kill goes. The lane draws both the same way."""
    proj, _ = studio.plan(_clips(root), "montage")
    shape = _song()
    studio.apply_song(proj, shape, "s.mp3", 4.0, 40.0, marks=[6.0, 9.0, 12.0, 300.0])
    assert proj["song_marks"] == [6.0, 9.0, 12.0], "a mark outside the part was kept"


def test_the_first_kill_waits_for_the_song_to_start(root):
    """Skechers has no drums until 18 s and the player marked no kill before
    19.5; a story reel opened at the first beat and cut its first kill at 7 s."""
    shape = _song(hits_from=0.5, drums_in=18.0, big=[19.5, 40.0])
    proj, _ = studio.plan(_clips(root), "story", shape=shape, song="s.mp3")
    first = proj["song_offset"] + proj["shots"][0]["pre"]
    assert first == pytest.approx(19.5, abs=0.02)
    assert proj["song_offset"] > 0


def test_a_fast_style_cuts_more_of_the_same_song(root):
    """The player's rule: hype and velocity cut rapidly, story and montage
    leave the kills further apart -- on the same song."""
    shape = _song()
    gaps = {}
    for style in ("story", "hype"):
        proj, _ = studio.plan(_clips(root), style, shape=shape, song="s.mp3")
        kills, t = [], 0.0
        for s in proj["shots"]:
            kills.append(t + s["pre"])
            t += s["duration"]
        gaps[style] = sorted(b - a for a, b in zip(kills, kills[1:]))[len(kills) // 2]
    assert gaps["story"] > gaps["hype"] * 1.5, gaps


def test_the_same_clip_twice_is_one_clip(root):
    """The rebuild-in-another-style button sent the timeline's shots back as
    the clip list, so a clip in nine shots arrived nine times and filled the
    reel with itself while the clips asked for once were left out."""
    clips = _clips(root)
    proj, _ = studio.plan(clips * 3, "story", shape=Shape(bpm=120.0))
    once, _ = studio.plan(clips, "story", shape=Shape(bpm=120.0))
    assert [s["clip"] for s in proj["shots"]] == [s["clip"] for s in once["shots"]]
    seen = [(s["clip"], s["kill"]) for s in proj["shots"]]
    assert len(seen) == len(set(seen)), "the same kill is in the reel twice"
    assert len(proj["selection"]) == len(clips)


# ------------------------------------------------------------------ checking

def _project(root, **over):
    proj, _ = studio.plan(_clips(root), "montage")
    proj.update(over)
    return proj


def test_a_clip_outside_the_clips_folder_is_refused(root, tmp_path):
    outside = tmp_path / "elsewhere.mp4"
    outside.write_bytes(b"x")
    proj = _project(root)
    proj["shots"][0]["clip"] = str(outside)
    got, _, notes = studio.normalise(proj, root)
    assert all(Path(s["clip"]).resolve() != outside.resolve() for s in got["shots"])
    assert any("not a clip in the clips folder" in n for n in notes)


def test_nothing_usable_is_an_error_not_an_empty_render(root):
    with pytest.raises(studio.ProjectError):
        studio.normalise({"shots": [{"clip": "C:/nope.mp4"}]}, root)
    with pytest.raises(studio.ProjectError):
        studio.normalise(None, root)


def test_unknown_parts_and_wild_numbers_are_clamped(root):
    proj = _project(root, grade="g99", intro="zzz", music_db=900, overlays=["o01", "evil"])
    proj["shots"][1].update(fx=["k01", "rm -rf"], speed="warp", transition="t99", duration=-4)
    got, derived, _ = studio.normalise(proj, root)
    assert got["grade"] == "g01" and got["intro"] == "i00" and got["music_db"] == 12
    assert got["overlays"] == ["o01"]
    s = got["shots"][1]
    assert s["fx"] == ["k01"] and s["speed"] == "s00" and s["transition"] == "t01"
    assert s["duration"] >= studio.MIN_SHOT
    assert derived["length"] > 0


def test_the_output_can_only_be_written_inside_reels(root, tmp_path):
    proj = _project(root, output=str(tmp_path / "anywhere.mp4"))
    got, _, _ = studio.normalise(proj, root)
    assert got["output"] == ""
    proj = _project(root, output=str(root / "reels" / "mine.mp4"))
    got, _, _ = studio.normalise(proj, root)
    assert got["output"].endswith("mine.mp4")


def test_a_transition_is_shortened_to_the_footage_around_the_cut(root):
    proj = _project(root)
    s0, s1 = proj["shots"][0], proj["shots"][1]
    s1.update(transition="t04", tlen=1.5)
    got, _, _ = studio.normalise(proj, root)
    t = got["shots"][1]
    if t["transition"] != "t01":
        assert t["tlen"] / 2 <= studio._head_room(t) + 1e-6
        assert t["tlen"] / 2 <= studio._tail_room(got["shots"][0]) + 1e-6
        assert t["tlen"] <= 0.8 * min(t["duration"], got["shots"][0]["duration"]) + 1e-6


def test_the_first_shot_never_has_a_transition_into_it(root):
    proj = _project(root)
    proj["shots"][0].update(transition="t05", tlen=0.5)
    got, _, _ = studio.normalise(proj, root)
    assert got["shots"][0]["transition"] == "t01" and got["shots"][0]["tlen"] == 0.0


def test_a_shot_is_trimmed_to_the_footage_its_speed_consumes(root):
    proj = _project(root)
    s = proj["shots"][0]
    s.update(speed="s04", duration=12.0, pre=6.0)    # 2.2x wants far more than 8 s of clip
    got, _, _ = studio.normalise(proj, root)
    g = got["shots"][0]
    a, b = studio._span(g)
    assert a >= -1e-6 and b <= g["clip_seconds"] + 1e-6


# ------------------------------------------------------------------ render graphs

def _built(root, **shot):
    proj, _ = studio.plan(_clips(root), "montage", shape=Shape(bpm=120.0))
    proj["song"] = ""
    for s in proj["shots"]:
        s.update(shot)
    got, derived, _ = studio.normalise(proj, root)
    segs = studio.segments(got, derived, has_audio=lambda p: True, song_beats=derived["beats"])
    return got, derived, segs


def test_graphs_carry_no_escaped_commas_inside_quotes(root):
    got, derived, segs = _built(root, fx=["k01", "k02", "k03", "k07", "k11", "k15", "k16"],
                                hero=True, hero_fx=["h01", "h02", "h03", "h05"], caption="ACE",
                                camera="c04", speed="s02")
    for seg in segs:
        argv = studio.segment_command(seg, Path("out.mp4"))
        graph = argv[argv.index("-filter_complex") + 1]
        assert "\\," not in graph
        assert graph.count("zoompan=") <= 1
    argv = studio.assemble_command(got, derived, segs, [Path(f"{i}.mp4") for i in range(len(segs))], Path("r.mp4"))
    assert "\\," not in argv[argv.index("-filter_complex") + 1]


def test_a_freeze_never_changes_how_long_a_shot_is(root):
    got, derived, segs = _built(root, fx=["k04"])
    for seg in segs:
        argv = studio.segment_command(seg, Path("o.mp4"))
        assert argv[argv.index("-frames:v") + 1] == str(seg.frames)
    assert derived["length"] == pytest.approx(sum(s["duration"] for s in got["shots"]))


def test_a_variant_reaches_the_renderer_the_way_its_base_does(root):
    """Every variant of a family must arrive, not just the id the family is named for.

    Three checks here read the id rather than the family, and the parts bin
    proved it: the four Beat bounce cards rendered byte-identical because no
    beats were passed for c04hard, and the two Freeze cards were identical to
    a plain hard cut. A dead variant is still offered, picked and shipped in a
    built-in style -- montage uses c04hard -- so it fails silently.
    """
    for part, hold in (("h02", 0.75), ("h02short", 0.35), ("h02long", 1.0)):
        _, _, segs = _built(root, hero=True, hero_fx=[part])
        assert [s.freeze for s in segs] == [pytest.approx(hold)] * len(segs), part
        assert all(s.freeze_push for s in segs), part
    for part in ("h05", "h05soft", "h05hard"):
        _, _, segs = _built(root, hero=True, hero_fx=[part], caption="ACE")
        assert all(s.caption == "ACE" for s in segs), part
    for part in ("c04", "c04hair", "c04soft", "c04hard", "c04slam"):
        _, _, segs = _built(root, camera=part)
        assert all(s.beats for s in segs), part
    # and a camera that is not the beat family still gets none
    _, _, segs = _built(root, camera="c01soft")
    assert not any(s.beats for s in segs)


def test_the_text_slam_slams_in_from_its_own_scale(root):
    sizes = []
    for part in ("h05soft", "h05", "h05hard"):
        _, _, segs = _built(root, hero=True, hero_fx=[part], caption="ACE")
        argv = studio.segment_command(segs[0], Path("o.mp4"))
        graph = argv[argv.index("-filter_complex") + 1]
        big = int(re.search(r"fontsize='if\(lt\(t-[\d.]+,0\.1\),(\d+)-", graph).group(1))
        sizes.append(big)
    assert sizes[0] < sizes[1] < sizes[2], sizes


def test_each_transition_is_centred_on_its_cut(root):
    proj, _ = studio.plan(_clips(root), "montage", shape=Shape(bpm=120.0))
    proj["song"] = ""
    for s in proj["shots"][1:]:
        s.update(transition="t04", tlen=0.4)
    got, derived, _ = studio.normalise(proj, root)
    segs = studio.segments(got, derived)
    argv = studio.assemble_command(got, derived, segs, [Path(f"{i}.mp4") for i in range(len(segs))], Path("r.mp4"))
    graph = argv[argv.index("-filter_complex") + 1]
    F = studio.FPS
    for i, m in enumerate(re.finditer(r"\[s(\d+)\]xfade=transition=\w+:duration=([\d.]+):offset=([\d.]+)", graph)):
        k = int(m.group(1))
        dur, off = float(m.group(2)), float(m.group(3))
        cut = derived["shots"][k]["start"]
        head = segs[k].head / F
        # B's own footage begins exactly where its handle ends: on the cut.
        assert off + head == pytest.approx(cut, abs=1.5 / F)
        assert off < cut < off + dur


def test_the_segment_cache_key_changes_with_what_is_rendered(root):
    _, _, a = _built(root, fx=["k01"])
    _, _, b = _built(root, fx=["k03"])
    assert a[0].key() != b[0].key()
    _, _, c = _built(root, fx=["k01"])
    assert a[0].key() == c[0].key()


# ------------------------------------------------------------------ catalogue

def test_part_ids_are_unique_and_every_style_uses_real_parts():
    ids = [p.id for p in studio.PARTS]
    assert len(ids) == len(set(ids))
    for s in studio.STYLES:
        for pid in (s.intro, s.outro, s.speed, s.hero_speed, s.camera, s.grade,
                    *s.cuts, *s.kill, *s.hero, *s.overlays):
            assert pid in studio.PART, f"{s.key} uses unknown part {pid}"
        assert studio_refs.summary(s.refs)["edits"] == len(s.refs), f"{s.key} cites an unmeasured edit"


def test_every_transition_part_can_be_drawn():
    """Every cut in the drawer resolves to an xfade preset and a length.

    A generated transition carries its preset as a knob rather than a row in
    XFADE, so the invariant is that the RESOLVER answers for all of them --
    an id that fell through would render as a hard cut and the drawer would
    quietly offer the same part a hundred times.
    """
    from autostream.clips import parts as parts_mod

    names = set(parts_mod.XFADE_NAMES) | set(studio.XFADE.values())
    for pid in studio.ids_of("transition"):
        if pid == "t01":
            assert studio._cut_seconds(pid) == 0.0
            continue
        assert studio._xfade_name(pid) in names, f"{pid} draws with no preset"
        assert 0.05 <= studio._cut_seconds(pid) <= 1.0, f"{pid} has no usable length"


def test_every_part_in_a_drawer_survives_normalise():
    """A part the bin offers must come back out of normalise() unchanged.

    The generated grades were checked against the hand-written GRADES table
    rather than the drawer, so every one of sixty tints silently became g01 --
    the bin offered them, the page showed them, and the render ignored them.
    A drawer's ids and what normalise accepts are the same list or the bin
    lies.
    """
    for pid in studio.ids_of("grade"):
        sat, con, bri, static = studio._grade_of(pid)
        assert 0.0 <= sat <= 2.0 and 0.5 <= con <= 2.0, f"{pid} grades to nonsense"
        assert pid == "g01" or static or sat != 1.0 or con != 1.0, f"{pid} grades to nothing"
    for pid in studio.ids_of("intro"):
        assert studio._fade_seconds(pid, 0.7) > 0 or pid == "i00"
    for pid in studio.ids_of("outro"):
        assert studio._fade_seconds(pid, 0.7) > 0 or pid == "e12"


def test_every_generated_part_resolves_to_a_family():
    """A variant whose family the renderer does not know draws nothing."""
    drawn = {"k01", "k02", "k03", "k06", "k07", "k08", "k11", "k12", "k14", "k15",
             "k16", "k17", "k18", "k19", "k20", "k21", "k22", "xfade", "tint",
             "c01", "c03", "c04", "c05", "c06", "c07", "c08",
             "o01", "o04", "o05", "o08", "h01", "h02", "h03", "h05",
             "fade_in", "fade_out"}
    for p in studio.PARTS:
        if p.base:
            assert p.base in drawn, f"{p.id} has family {p.base}, which nothing draws"


def test_the_catalog_is_what_the_page_reads():
    cat = studio.catalog()
    assert cat["ok"] and cat["default_style"] in {s["key"] for s in cat["styles"]}
    assert all(s["measured"]["edits"] >= 3 for s in cat["styles"])
    assert all(s["pools"]["kill"] and s["pools"]["transition"] for s in cat["styles"])


# ------------------------------------------------------------------ variety

@pytest.fixture
def long_run(tmp_path):
    """Twenty-four 12 s clips with the kill in the middle: room to move."""
    r = tmp_path / "clips"
    _run(r, "2026-09-01_1200_VALORANT", "VALORANT",
         [{"start": 100.0 * i, "end": 100.0 * i + 12} for i in range(1, 25)],
         kills=[100.0 * i + 6 for i in range(1, 25)])
    return r


@pytest.mark.parametrize("style", [s.key for s in studio.STYLES])
def test_no_two_shots_running_get_the_same_kill_effect(long_run, style):
    """The reel the user sent back had one effect on every kill. Every shot
    draws its own now, and never what the shot before it got."""
    proj, _ = studio.plan(_clips(long_run), style, shape=Shape(bpm=128.0))
    firsts = [s["fx"][0] for s in proj["shots"] if s["fx"]]
    assert len(firsts) == len(proj["shots"])
    assert all(a != b for a, b in zip(firsts, firsts[1:])), firsts
    assert len(set(firsts)) >= 3, firsts


@pytest.mark.parametrize("style", [s.key for s in studio.STYLES])
def test_transitions_are_mixed_too(long_run, style):
    proj, _ = studio.plan(_clips(long_run), style, shape=Shape(bpm=128.0))
    cuts = [s["transition"] for s in proj["shots"][1:]]
    assert len(set(cuts)) >= 2, cuts
    soft = [t for t in cuts if t not in ("t01", "t02")]
    assert all(a != b for a, b in zip(soft, soft[1:])) or len(set(soft)) <= 1, cuts


def test_the_same_seed_is_the_same_reel(long_run):
    clips = _clips(long_run)
    a, _ = studio.plan(clips, "velocity", seed=7)
    b, _ = studio.plan(clips, "velocity", seed=7)
    c, _ = studio.plan(clips, "velocity", seed=8)
    mix = lambda p: [(s["fx"], s["transition"], s["speed"], s["camera"]) for s in p["shots"]]
    assert mix(a) == mix(b)
    assert mix(a) != mix(c)


def test_mixing_again_moves_no_cut_and_no_kill(long_run):
    proj, _ = studio.plan(_clips(long_run), "montage", shape=Shape(bpm=128.0))
    timing = [(s["duration"], s["pre"], s["kill"], s["clip"]) for s in proj["shots"]]
    before = [s["fx"] for s in proj["shots"]]
    seed = proj["seed"]
    studio.vary(proj, "kill")
    assert [(s["duration"], s["pre"], s["kill"], s["clip"]) for s in proj["shots"]] == timing
    assert [s["fx"] for s in proj["shots"]] != before
    assert proj["seed"] != seed


def test_mixing_one_kind_leaves_the_others_alone(long_run):
    proj, _ = studio.plan(_clips(long_run), "velocity", shape=Shape(bpm=128.0))
    trans = [s["transition"] for s in proj["shots"]]
    speeds = [s["speed"] for s in proj["shots"]]
    studio.vary(proj, "kill")
    assert [s["transition"] for s in proj["shots"]] == trans
    assert [s["speed"] for s in proj["shots"]] == speeds


def test_a_narrowed_pool_is_all_that_is_drawn(long_run):
    proj, _ = studio.plan(_clips(long_run), "hype", shape=Shape(bpm=128.0))
    proj["pools"]["kill"] = ["k02", "k06"]
    studio.vary(proj, "kill")
    assert {k for s in proj["shots"] for k in s["fx"]} <= {"k02", "k06"}


def test_pools_and_seed_survive_the_round_trip_and_junk_is_dropped(long_run):
    proj, _ = studio.plan(_clips(long_run), "story", shape=Shape(bpm=128.0))
    proj["pools"]["kill"] = ["k01", "evil", "t04"]
    proj["seed"] = "not a number"
    got, _, _ = studio.normalise(proj, long_run)
    assert got["pools"]["kill"] == ["k01"]
    assert isinstance(got["seed"], int)


# ------------------------------------------------------------------ the song part

def test_a_marked_kill_lands_on_its_mark(long_run):
    proj, _ = studio.plan(_clips(long_run)[:6], "story", shape=Shape(bpm=120.0))
    marks = [2.0, 3.5, 5.25, 7.0, 9.5]
    studio.apply_marks(proj, marks)
    got, derived, _ = studio.normalise(proj, long_run)
    for i, m in enumerate(marks):
        assert derived["shots"][i]["kill_reel"] == pytest.approx(m, abs=1.0 / studio.FPS), i
    # the shot with no mark follows on at its own length
    assert derived["shots"][5]["start"] == pytest.approx(derived["shots"][4]["end"], abs=1e-6)


def test_more_marks_than_shots_says_so(long_run):
    proj, _ = studio.plan(_clips(long_run)[:2], "story", shape=Shape(bpm=120.0))
    notes = studio.apply_marks(proj, [2.0, 4.0, 6.0])
    assert any("were not used" in n for n in notes)


def test_a_mark_the_footage_cannot_reach_is_reported(long_run):
    proj, _ = studio.plan(_clips(long_run)[:2], "story", shape=Shape(bpm=120.0))
    # 6 s of footage before the kill; even slowed to MIN_STRETCH it cannot
    # fill 60 s.
    notes = studio.apply_marks(proj, [60.0, 61.0])
    assert any("Shot 1 has only" in n for n in notes)


def test_a_short_run_up_is_slowed_so_the_kill_still_lands_on_its_mark(long_run):
    """The mark is authoritative: too little footage stretches the approach,
    it never moves the kill."""
    proj, _ = studio.plan(_clips(long_run)[:4], "story", shape=Shape(bpm=120.0))
    proj["shots"][0]["speed"] = "s00"
    marks = [10.0, 11.5, 13.0]                              # 6 s of footage before the kill
    notes = studio.apply_marks(proj, marks)
    assert any("slowed" in n for n in notes), notes
    got, derived, _ = studio.normalise(proj, long_run)
    assert not got["shots"][0].get("lead_in")
    rate, real = got["shots"][0]["stretch"][:2]
    assert studio.MIN_STRETCH <= rate < 1 and real == pytest.approx(studio.STRETCH_REAL)
    for i, m in enumerate(marks):
        assert derived["shots"][i]["kill_reel"] == pytest.approx(m, abs=1.0 / studio.FPS), i
    # the last seconds into the kill play as recorded, the rest slowed, and no
    # more footage is asked for than the clip has before its kill
    ps = derived["shots"][0]["pieces"]
    assert ps[-1][2] == 1.0 and ps[0][2] == pytest.approx(rate)
    assert derived["shots"][0]["source_in"] >= -1e-3


def test_past_the_slowest_stretch_the_opening_frame_is_held(long_run):
    proj, _ = studio.plan(_clips(long_run)[:3], "story", shape=Shape(bpm=120.0))
    proj["shots"][0]["speed"] = "s00"
    studio.apply_marks(proj, [45.0, 46.5])                 # 6 s of footage before the kill
    got, derived, _ = studio.normalise(proj, long_run)
    rate, real, hold = got["shots"][0]["stretch"]
    assert rate == pytest.approx(studio.MIN_STRETCH, rel=0.01) and 0 < hold <= studio.MAX_HOLD
    assert derived["shots"][0]["kill_reel"] == pytest.approx(45.0, abs=1.0 / studio.FPS)
    assert derived["shots"][0]["source_in"] >= -1e-3
    segs = studio.segments(got, derived)
    cmd = studio.segment_command(segs[0], Path("s.mp4"))
    assert "setpts=" in " ".join(cmd)


def test_a_stretch_survives_the_round_trip_and_junk_is_dropped(long_run):
    proj, _ = studio.plan(_clips(long_run)[:2], "story", shape=Shape(bpm=120.0))
    proj["shots"][0]["stretch"] = [0.5, 1.0]
    proj["shots"][1]["stretch"] = ["evil", None]
    got, _, _ = studio.normalise(proj, long_run)
    assert "stretch" not in got["shots"][1]
    assert got["shots"][0].get("stretch", [0.5])[0] == 0.5


def test_a_first_mark_out_of_reach_goes_to_the_next_shot(long_run):
    """The mark keeps its kill even when the opener cannot get to it.

    Measured on QUATROKAV2: a part chosen from 2.0 s put the first mark on the
    song's arrival at 12.12 s, the opening clip had 3.50 s of footage before
    its kill, and the arrival -- the loudest thing in the part -- ended up with
    no cut on it at all while one shot stretched across it.
    """
    proj, _ = studio.plan(_clips(long_run)[:6], "story", shape=Shape(bpm=120.0))
    # Straight speed, so the reach is the footage: a slowed opener spends its
    # 6 s over twelve and could reach the mark after all.
    proj["shots"][0]["speed"] = "s00"
    # 6 s of footage before the kill: not enough even slowed to MIN_STRETCH.
    marks = [50.0, 51.5, 53.0, 54.5]
    studio.apply_marks(proj, marks)
    got, derived, _ = studio.normalise(proj, long_run)
    assert got["shots"][0]["lead_in"] is True
    assert derived["shots"][0]["mark"] is None              # the lead-in is not scored
    for i, m in enumerate(marks):
        assert derived["shots"][i + 1]["kill_reel"] == pytest.approx(m, abs=1.0 / studio.FPS), i
    # and the opener still opens on every frame of run-up it owns
    assert derived["shots"][0]["kill_reel"] == pytest.approx(6.0, abs=1.0 / studio.FPS)


def test_a_first_mark_within_reach_is_still_the_openers(long_run):
    proj, _ = studio.plan(_clips(long_run)[:4], "story", shape=Shape(bpm=120.0))
    studio.apply_marks(proj, [4.0, 6.0, 8.0])
    got, derived, _ = studio.normalise(proj, long_run)
    assert not got["shots"][0].get("lead_in")
    assert derived["shots"][0]["kill_reel"] == pytest.approx(4.0, abs=1.0 / studio.FPS)


def test_the_lead_in_stretches_the_intro_over_itself(long_run):
    """A one-second fade over a nine-second hold does not look like a start."""
    proj, _ = studio.plan(_clips(long_run)[:4], "story", shape=Shape(bpm=120.0))
    proj["intro"] = "i03"
    proj["shots"][0]["speed"] = "s00"
    studio.apply_marks(proj, [50.0, 51.5, 53.0])
    assert proj["shots"][0]["lead_in"] is True
    got, derived, _ = studio.normalise(proj, long_run)
    segs = studio.segments(got, derived)
    cmd = studio.assemble_command(got, derived, segs,
                                  [Path(f"{i}.mp4") for i in range(len(segs))], Path("r.mp4"))
    fade = [a for a in cmd if "fade=in:st=0:d=" in str(a)]
    assert fade, cmd
    assert "fade=in:st=0:d=1.0" not in str(fade)


def test_the_song_starts_exactly_where_it_was_fine_tuned(long_run):
    """10 ms nudges are the point of the control, so the start is not snapped."""
    proj, _ = studio.plan(_clips(long_run)[:4], "story", shape=Shape(bpm=128.0))
    shape = Shape(bpm=128.0, seconds=90.0)
    studio.apply_song(proj, shape, "song.wav", 13.1061)
    assert proj["song_offset"] == pytest.approx(13.1061, abs=1e-4)
    assert proj["beat"] == pytest.approx(shape.beat, abs=1e-6)


def test_song_marks_are_song_seconds_and_outside_ones_are_ignored(long_run):
    proj, _ = studio.plan(_clips(long_run)[:4], "story", shape=Shape(bpm=120.0))
    shape = Shape(bpm=120.0, seconds=90.0, phase=0.0)
    studio.apply_song(proj, shape, "song.wav", 20.0, 0.0, [3.0, 22.0, 24.0])
    got, derived, _ = studio.normalise(dict(proj, song=""), long_run)
    assert derived["shots"][0]["kill_reel"] == pytest.approx(2.0, abs=1.0 / studio.FPS)
    assert derived["shots"][1]["kill_reel"] == pytest.approx(4.0, abs=1.0 / studio.FPS)


def test_a_short_part_keeps_only_the_shots_it_holds(long_run):
    proj, _ = studio.plan(_clips(long_run)[:8], "story", shape=Shape(bpm=120.0))
    n = len(proj["shots"])
    notes = studio.apply_song(proj, Shape(bpm=120.0, seconds=90.0), "song.wav", 10.0, 16.0)
    assert sum(s["duration"] for s in proj["shots"]) <= 6.0 + 1e-6
    assert len(proj["shots"]) < n
    assert any("left out" in x for x in notes)


def test_a_caption_with_punctuation_is_drawn_from_a_file(tmp_path):
    text = "Ace, it's 3:30 [100%]; done \\o/"
    p = studio.text_file(tmp_path, text)
    assert p.read_text(encoding="utf-8") == text
    assert studio.text_file(tmp_path, text) == p                # same text, same file
    arg = studio._path_arg(p)
    assert arg.startswith("'") and arg.endswith("'") and "\\" not in arg.replace("\\:", "")


def test_a_hero_caption_never_goes_into_the_graph_inline(root, tmp_path):
    got, derived, segs = _built(root, hero=True, hero_fx=["h05"], caption="it's, an ACE: [1v5]")
    for seg in segs:
        graph = studio.segment_command(seg, Path("o.mp4"), textdir=tmp_path)
        graph = graph[graph.index("-filter_complex") + 1]
        assert "it's" not in graph
        if "drawtext" in graph:
            assert "textfile=" in graph


class _Job:
    def __init__(self):
        import threading
        self.state = "running"
        self.release = threading.Event()
        self.cancelled = False

    def run(self):
        self.release.wait(5)
        self.state = "done"

    def cancel(self):
        self.cancelled = True
        self.release.set()

    def snapshot(self):
        return {"state": self.state}


@pytest.mark.parametrize("stage", ["shot", "join"])
def test_cancel_is_reported_as_cancelled_not_as_a_failure(root, tmp_path, monkeypatch, stage):
    """Cancelled is a RuntimeError, and each stage re-wraps RuntimeErrors with
    which shot failed -- which turned Cancel into "Shot 1 (...): cancelled"."""
    from autostream.clips import tools

    monkeypatch.setattr(tools, "binary", lambda name: "ffmpeg")
    monkeypatch.setattr(tools, "media_info", lambda p: {"audio_tracks": 1})
    got, derived, _ = _built(root)
    job = studio.StudioJob(got, derived, root, root / "reels" / "x.mp4")

    def fake_ff(argv, capture=False):
        out = Path(argv[-1])
        joining = out.name.endswith(".part.mp4") and out.parent.name == "reels"
        if (stage == "shot") or joining:
            job._cancel.set()
            raise studio.Cancelled("cancelled")
        out.write_bytes(b"x")
        return ""
    monkeypatch.setattr(job, "_run_ff", fake_ff)
    job.run()
    snap = job.snapshot()
    assert snap["state"] == "cancelled", snap
    assert not snap["error"]


def test_only_one_reel_renders_at_a_time():
    run = studio.Runner()
    a, b = _Job(), _Job()
    assert run.start(a) == ""
    assert run.busy() and run.start(b) == "A reel is already rendering."
    assert run.cancel() and a.cancelled
    for _ in range(100):
        if not run.busy():
            break
        import time
        time.sleep(0.02)
    assert not run.busy() and run.start(b) == ""
    b.release.set()


def test_cancel_reaches_a_render_that_has_only_been_claimed():
    """The gap the page's Cancel button is offered in.

    A render is claimed, then prepared, then started. Cancel landing in the
    middle used to find no job and be dropped, and the render began anyway.
    """
    run = studio.Runner()
    claim = run.claim()
    assert run.cancel()                      # nothing running, but one claimed
    job = _Job()
    assert run.start(job, claim) == "The render was cancelled before it started."
    assert not run.busy()
    assert run.job is None                   # never handed to a thread


def test_a_claim_that_was_not_cancelled_still_starts():
    run = studio.Runner()
    claim = run.claim()
    job = _Job()
    assert run.start(job, claim) == ""
    assert run.busy()
    run.cancel()
    job.release.set()


def test_cancel_says_no_when_there_is_nothing_to_cancel():
    run = studio.Runner()
    assert not run.cancel()
    run.release(run.claim())
    assert not run.cancel()


# ------------------------------------------------------------------ the part of the song, chosen first

def _spans_by_clip(shots):
    out = {}
    for s in shots:
        out.setdefault(s["clip"], []).append(studio._span(s))
    return out


def test_a_chosen_part_is_where_the_reel_starts_and_how_long_it_is(long_run):
    """MONTERO at 72 BPM came out 24 s: the length rule snapped to one 8-bar
    phrase and left clips out. With the part chosen first it is the length."""
    shape = Shape(bpm=120.0, seconds=120.0, phase=0.0)
    proj, notes = studio.plan(_clips(long_run)[:8], "story", shape=shape, song="s.mp3", part=(10.0, 34.0))
    total = sum(s["duration"] for s in proj["shots"])
    assert proj["song_offset"] == pytest.approx(10.0)
    assert proj["part_end"] == pytest.approx(34.0)
    assert total == pytest.approx(24.0, abs=shape.beat + 1e-6)
    assert all(x["why"] == "" for x in proj["selection"])          # every chosen clip went in
    t = 0.0
    for s in proj["shots"]:
        assert _on_grid(t, shape.beat) and _on_grid(t + s["pre"], shape.beat)
        t += s["duration"]


def test_clips_short_of_the_part_get_longer_run_ups_within_their_footage(long_run):
    shape = Shape(bpm=120.0, seconds=180.0, phase=0.0)
    auto, _ = studio.plan(_clips(long_run)[:4], "story", shape=shape, song="s.mp3")
    proj, notes = studio.plan(_clips(long_run)[:4], "story", shape=shape, song="s.mp3", part=(0.0, 30.0))
    assert sum(s["duration"] for s in proj["shots"]) > sum(s["duration"] for s in auto["shots"])
    assert any("longer run-ups" in n for n in notes)
    for s in proj["shots"]:
        a, b = studio._span(s)
        assert a >= -1e-6 and b <= s["clip_seconds"] + 1e-6              # never past the footage
        assert s["pre"] <= rulebook.MAX_LEAD_UP_SECONDS + 1e-6          # never a walk to site


def test_a_part_the_clips_cannot_fill_ends_early_and_says_so(long_run):
    shape = Shape(bpm=120.0, seconds=300.0, phase=0.0)
    proj, notes = studio.plan(_clips(long_run)[:2], "story", shape=shape, song="s.mp3", part=(0.0, 120.0))
    assert sum(s["duration"] for s in proj["shots"]) < 120.0
    assert any("ends early" in n for n in notes)


def test_a_part_too_short_for_every_clip_says_which_were_left_out_and_why(long_run):
    shape = Shape(bpm=120.0, seconds=120.0, phase=0.0)
    proj, _ = studio.plan(_clips(long_run), "story", shape=shape, song="s.mp3", part=(0.0, 8.0))
    out = [x for x in proj["selection"] if x["why"]]
    assert out and len(proj["selection"]) == 24
    assert all(("part" in x["why"]) for x in out)
    assert {x["clip"] for x in proj["selection"] if not x["why"]} == {s["clip"] for s in proj["shots"]}


def test_a_longer_run_up_never_shows_a_kill_twice(tmp_path):
    """Round clips give several shots from one file; growing a run-up back past
    the previous shot's footage would play that kill again."""
    r = tmp_path / "clips"
    _run(r, "2026-09-16_1537_VALORANT", "VALORANT",
         [{"start": 1000.0, "end": 1033.0, "kills": 4}, {"start": 2000.0, "end": 2025.0, "kills": 2}],
         kills=[1003.5, 1012.3, 1025.2, 1029.9, 2003.5, 2011.6])
    shape = Shape(bpm=72.0, seconds=140.0, phase=0.0)
    proj, _ = studio.plan(_clips(r), "hype", shape=shape, song="s.mp3", part=(0.0, 90.0))
    for clip, spans in _spans_by_clip(proj["shots"]).items():
        spans.sort()
        for (a1, b1), (a2, b2) in zip(spans, spans[1:]):
            assert a2 >= b1 - 1e-6, f"{Path(clip).name}: {a1:.2f}-{b1:.2f} overlaps {a2:.2f}-{b2:.2f}"


def test_without_a_part_the_planner_chooses_as_before(long_run):
    shape = Shape(bpm=120.0, seconds=120.0, phase=0.0, drums_in=8.0)
    a, _ = studio.plan(_clips(long_run)[:8], "story", shape=shape, song="s.mp3")
    b, _ = studio.plan(_clips(long_run)[:8], "story", shape=shape, song="s.mp3", part=None)
    assert a["shots"] == b["shots"] and a["song_offset"] == b["song_offset"]
    assert "part_end" not in a


# ------------------------------------------------------------------ what went in, and edits

def test_the_selection_and_part_survive_a_save_and_a_removed_shot_is_explained(long_run):
    shape = Shape(bpm=120.0, seconds=120.0, phase=0.0)
    proj, _ = studio.plan(_clips(long_run)[:4], "story", shape=shape, song="", part=None)
    proj["part_end"] = 30.0
    got, derived, _ = studio.normalise(proj, long_run)
    assert [x["clip"] for x in got["selection"]] == [c["path"] for c in _clips(long_run)[:4]]
    assert all(x["in"] for x in derived["selection"])
    gone = got["shots"].pop(0)["clip"]
    got, derived, _ = studio.normalise(got, long_run)
    row = next(x for x in derived["selection"] if x["clip"] == gone)
    assert not row["in"] and row["why"] == "Removed on the timeline."


def test_an_edited_timeline_is_told_apart_from_an_untouched_one(long_run):
    proj, _ = studio.plan(_clips(long_run)[:4], "story")
    proj, derived, _ = studio.normalise(proj, long_run)
    proj["plan_sig"] = studio.signature(proj["shots"])
    proj, derived, _ = studio.normalise(proj, long_run)
    assert derived["edited"] is False
    proj["shots"][1]["caption"] = "MINE"
    proj, derived, _ = studio.normalise(proj, long_run)
    assert derived["edited"] is True


# ------------------------------------------------------------------ deleting clips

def test_deleting_clips_removes_the_clip_its_vertical_and_its_row_and_nothing_else(root):
    folder = root / "2026-09-14_0045_VALORANT"
    man = json.loads((folder / "clips.json").read_text())
    vert = folder / "vertical" / "VALORANT_00_vertical.mp4"
    vert.parent.mkdir()
    vert.write_bytes(b"v" * 1000)
    man["clips"][0]["vertical"] = str(vert)
    (folder / "clips.json").write_text(json.dumps(man))
    target = man["clips"][0]["master"]

    dry = studio.delete_clips(root, [target], dry_run=True)
    assert dry["clips"] == 1 and dry["bytes"] == len(b"not really a video") + 1000
    assert Path(target).is_file() and vert.is_file()                    # a dry run touches nothing

    got = studio.delete_clips(root, [target])
    assert got["clips"] == 1 and not got["errors"]
    assert not Path(target).exists() and not vert.exists()
    assert (folder / "session.json").is_file()                          # a re-cut still needs it
    names = [c["name"] for c in json.loads((folder / "clips.json").read_text())["clips"]]
    assert "VALORANT_00" not in names and len(names) == 2
    assert studio.library(root)["clip_count"] == 3


def test_only_a_clip_a_run_lists_can_be_deleted(root, tmp_path):
    stray = tmp_path / "elsewhere.mp4"
    stray.write_bytes(b"x")
    session = root / "2026-09-14_0045_VALORANT" / "session.json"
    got = studio.delete_clips(root, [str(stray), str(session)])
    assert got["clips"] == 0 and got["missing"] == 2
    assert stray.is_file() and session.is_file()


def test_a_reel_that_uses_a_clip_is_named_before_it_is_deleted(root):
    clip = _clips(root)[0]["path"]
    (root / "reels" / "MONTERO2.mp4").write_bytes(b"x")
    (root / "reels" / "MONTERO2.reel.json").write_text(json.dumps({"name": "MONTERO2", "shots": [{"clip": clip}]}))
    assert studio.delete_clips(root, [clip], dry_run=True)["reels"] == ["MONTERO2"]


# ------------------------------------------------------------------ deleting reels

def test_deleting_a_reel_takes_its_video_project_and_leftovers_and_leaves_the_clips(root):
    clip = _clips(root)[0]["path"]
    reels = root / "reels"
    (reels / "MONTERO2.mp4").write_bytes(b"v" * 1000)
    (reels / "MONTERO2.reel.json").write_text(json.dumps({"name": "MONTERO2", "shots": [{"clip": clip}]}))
    # What a render that died leaves beside the reel. reels() hides these, so
    # deleting the reel is the only thing that ever clears them.
    (reels / "MONTERO2.part.mp4").write_bytes(b"p" * 10)
    (reels / "OTHER.mp4").write_bytes(b"o")

    dry = studio.delete_reels(root, [str(reels / "MONTERO2.mp4")], dry_run=True)
    assert dry["reels"] == 1 and dry["names"] == ["MONTERO2"] and dry["bytes"] > 1000
    assert (reels / "MONTERO2.mp4").is_file()                           # a dry run touches nothing

    got = studio.delete_reels(root, [str(reels / "MONTERO2.mp4")])
    assert got["reels"] == 1 and not got["errors"]
    assert sorted(p.name for p in reels.iterdir()) == ["OTHER.mp4"]
    assert Path(clip).is_file()                                         # the clips are never touched
    assert studio.library(root)["clip_count"] == 4


def test_only_an_mp4_the_reels_folder_lists_can_be_deleted(root, tmp_path):
    stray = tmp_path / "home_video.mp4"
    stray.write_bytes(b"x")
    clip = _clips(root)[0]["path"]
    part = root / "reels" / "HALF.part.mp4"
    part.write_bytes(b"p")
    got = studio.delete_reels(root, [str(stray), clip, str(part)])
    assert got["reels"] == 0 and got["missing"] == 3
    assert stray.is_file() and Path(clip).is_file() and part.is_file()


def test_what_the_planner_said_stays_with_the_reel(long_run):
    """Said only in the reply to the plan, the notes were replaced by the render's
    reply a moment later, so "the weakest were left out" was never read."""
    proj, _ = studio.plan(_clips(long_run)[:2], "story")
    proj["plan_notes"] = ["Your clips fill 41 s of the 60 s part, so the reel ends early.", 7, ""]
    got, _, _ = studio.normalise(proj, long_run)
    assert got["plan_notes"] == ["Your clips fill 41 s of the 60 s part, so the reel ends early."]


# ------------------------------------------------------------------ the intro clip

@pytest.fixture
def intro_home(tmp_path, monkeypatch):
    """A throwaway VIDEO_HOME, so the intros library is not the developer's own."""
    from autostream import paths

    home = tmp_path / "video"
    monkeypatch.setattr(paths, "VIDEO_HOME", home)
    return home


def _fake_intro(home: Path, name="sting", seconds=6.0, has_audio=True) -> str:
    """An intro already in the library, written without ffmpeg."""
    d = home / "intros"
    d.mkdir(parents=True, exist_ok=True)
    mp4 = d / f"{name}.mp4"
    mp4.write_bytes(b"not really a video")
    (d / f"{name}.json").write_text(json.dumps(
        {"name": name, "seconds": seconds, "width": 1920, "height": 1080,
         "has_audio": has_audio, "when": 1_700_000_000}))
    return str(mp4)


def test_an_intro_is_only_ever_a_file_in_the_intros_folder(intro_home, tmp_path):
    from autostream.clips import intros

    good = _fake_intro(intro_home)
    assert intros.inside(good) is not None
    stray = tmp_path / "somewhere.mp4"
    stray.write_bytes(b"x")
    # The shapes of "not ours": outside the folder, not an mp4, not there.
    assert intros.inside(str(stray)) is None
    assert intros.inside(str(intro_home / "intros" / "sting.json")) is None
    assert intros.inside(str(intro_home / "intros" / "gone.mp4")) is None
    assert intros.inside("") is None


def test_the_intro_library_lists_what_its_sidecar_says(intro_home):
    from autostream.clips import intros

    _fake_intro(intro_home, "old", seconds=3.0, has_audio=False)
    _fake_intro(intro_home, "new", seconds=8.5)
    by = {e["name"]: e for e in intros.listing()}
    assert by["old"]["seconds"] == 3.0 and by["old"]["has_audio"] is False
    assert by["new"]["seconds"] == 8.5 and by["new"]["has_audio"] is True


def test_adding_an_intro_refuses_what_is_not_short_or_not_video(intro_home, tmp_path):
    from autostream.clips import intros

    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    with pytest.raises(ValueError, match="minutes"):
        intros.add(src, measure=lambda p: {"duration": 600.0, "audio_tracks": 0},
                   encode=lambda *a, **k: None)
    doc = tmp_path / "notes.txt"
    doc.write_text("x")
    with pytest.raises(ValueError, match="not a video"):
        intros.add(doc, measure=lambda p: {"duration": 2.0}, encode=lambda *a, **k: None)


def test_adding_an_intro_writes_one_mp4_and_its_sidecar(intro_home, tmp_path):
    from autostream.clips import intros

    src = tmp_path / "My Sting!.gif"
    src.write_bytes(b"x")

    def encode(s, out, *, keep_audio):
        out.write_bytes(b"converted")

    got = intros.add(src, measure=lambda p: {"duration": 4.0, "width": 800, "height": 600,
                                             "audio_tracks": 0}, encode=encode)
    assert got["name"] == "My Sting" and got["seconds"] == 4.0 and got["has_audio"] is False
    assert Path(got["path"]).suffix == ".mp4"
    assert [e["name"] for e in intros.listing()] == ["My Sting"]
    # A second file of the same name does not overwrite the first.
    again = intros.add(src, measure=lambda p: {"duration": 4.0, "audio_tracks": 0}, encode=encode)
    assert again["path"] != got["path"] and len(intros.listing()) == 2


def test_deleting_an_intro_takes_its_sidecar_and_refuses_anything_else(intro_home, tmp_path):
    from autostream.clips import intros

    path = _fake_intro(intro_home, "sting")
    stray = tmp_path / "elsewhere.mp4"
    stray.write_bytes(b"x")
    with pytest.raises(ValueError):
        intros.remove(str(stray))
    assert stray.is_file()
    intros.remove(path)
    assert intros.listing() == []
    assert not (intro_home / "intros" / "sting.json").exists()


def _with_intro(root, intro_home, **over):
    proj, _ = studio.plan(_clips(root), "montage", shape=Shape(bpm=120.0))
    proj["song"] = ""
    ic = {"path": _fake_intro(intro_home), "start": 1.0, "end": 3.0,
          "audio": True, "fit": "cover"}
    ic.update(over)
    proj["intro_clip"] = ic
    return studio.normalise(proj, root)


def test_an_intro_clip_survives_normalise_with_its_trim_and_its_sound(root, intro_home):
    got, derived, _ = _with_intro(root, intro_home)
    assert got["intro_clip"]["start"] == 1.0 and got["intro_clip"]["end"] == 3.0
    assert got["intro_clip"]["audio"] is True and got["intro_clip"]["has_audio"] is True
    assert derived["intro_clip"]["seconds"] == pytest.approx(2.0)


def test_an_intro_longer_than_the_reel_is_kept_but_remarked_on(root, intro_home):
    """It plays in front of the reel now, so it can no longer swallow it --
    but an opener longer than the reel behind it is nearly always a mistrim."""
    long_one = _fake_intro(intro_home, "long", seconds=600.0)
    got, derived, notes = _with_intro(root, intro_home, path=long_one, start=0.0, end=600.0)
    assert got["intro_clip"]["end"] - got["intro_clip"]["start"] == pytest.approx(600.0)
    assert derived["length"] == pytest.approx(derived["length"])
    assert any("longer than the" in n for n in notes)


def test_an_intro_the_user_deleted_drops_off_the_project(root, intro_home):
    got, _, _ = _with_intro(root, intro_home)
    Path(got["intro_clip"]["path"]).unlink()
    again, _, notes = studio.normalise(got, root)
    assert again["intro_clip"] is None
    assert any("not in your intros folder" in n for n in notes)


def test_sound_asked_for_on_a_silent_intro_is_remembered_but_not_used(root, intro_home):
    path = _fake_intro(intro_home, "silent", has_audio=False)
    got, derived, _ = _with_intro(root, intro_home, path=path, audio=True)
    # What the user asked for is kept -- ticking the box on a clip that is
    # later replaced by one with sound should not be silently forgotten --
    # but what will actually happen is what derive reports.
    assert got["intro_clip"]["audio"] is True
    assert got["intro_clip"]["has_audio"] is False
    assert derived["intro_clip"]["audio"] is False


def test_an_intro_that_trims_to_nothing_leaves_the_reel_alone(root, intro_home):
    got, _, notes = _with_intro(root, intro_home, start=2.0, end=2.1)
    assert got["intro_clip"] is None
    assert any("too short to see" in n for n in notes)


def _graph(got, derived):
    segs = studio.segments(got, derived)
    argv = studio.assemble_command(got, derived, segs,
                                   [Path(f"{i}.mp4") for i in range(len(segs))], Path("r.mp4"))
    return argv, argv[argv.index("-filter_complex") + 1]


def test_the_intro_is_trimmed_by_ffmpeg_and_never_touches_the_reel_pass(root, intro_home):
    """The reel's own pass must not know about the intro at all.

    It used to overlay it on the reel's first seconds, so whatever the reel
    opened with played underneath and was lost -- on a reel that opens on a
    kill, the kill.
    """
    got, derived, _ = _with_intro(root, intro_home)
    argv, graph = _graph(got, derived)
    assert got["intro_clip"]["path"] not in argv
    assert "overlay=0:0:eof_action=pass" not in graph
    assert "[icv]" not in graph and "[icj]" not in graph and "[ica]" not in graph
    # It is its own pass, and only the chosen part is ever decoded.
    head = studio.intro_head_command(got, Path("head.mp4"))
    i = head.index(got["intro_clip"]["path"])
    assert head[i - 5:i] == ["-ss", "1.0000", "-t", "2.0000", "-i"]


def _song_proj(intro_home, *, offset, audio=False, has_audio=True, song="C:/s/track.m4a"):
    """A project by hand: these assert on the argv, not on normalise."""
    return {"format": "landscape", "song": song, "song_offset": offset, "music_db": -3.0,
            "intro_clip": {"path": _fake_intro(intro_home), "start": 0.0, "end": 3.0,
                           "audio": audio, "has_audio": has_audio, "fit": "cover"}}


def test_the_intro_carries_the_song_run_up_into_the_reel(intro_home):
    """The seam this removes: an intro over silence, then a reel starting the
    song from nothing. The intro plays the seconds BEFORE song_offset, so the
    song is already going when the first kill lands and the reel still begins
    exactly where its beat grid was built."""
    args = studio.intro_head_command(_song_proj(intro_home, offset=20.0), Path("h.mp4"))
    i = args.index("C:/s/track.m4a")
    assert args[i - 5:i] == ["-ss", "17.0000", "-t", "3.0000", "-i"]  # 3s ending on 20.0
    fc = args[args.index("-filter_complex") + 1]
    assert "volume=-3.0dB" in fc                                  # the reel's music level
    assert "adelay" not in fc                                     # run-up fills the intro
    assert "anullsrc" not in " ".join(args)


def test_the_intros_own_sound_wins_and_the_song_waits_for_the_reel(intro_home):
    args = studio.intro_head_command(_song_proj(intro_home, offset=20.0, audio=True),
                                     Path("h.mp4"))
    assert "C:/s/track.m4a" not in args
    assert "-filter_complex" not in args
    assert args[args.index("-map") + 3] == "0:a:0"                # the clip's own track


def test_a_reel_starting_near_the_songs_beginning_still_lands_on_the_cut(intro_home):
    """Less run-up than the intro is long: the song has to END on the cut, not
    start on it, so what there is sits at the tail of the intro."""
    args = studio.intro_head_command(_song_proj(intro_home, offset=1.0), Path("h.mp4"))
    i = args.index("C:/s/track.m4a")
    assert args[i - 5:i] == ["-ss", "0.0000", "-t", "1.0000", "-i"]
    assert "adelay=2000:all=1" in args[args.index("-filter_complex") + 1]


def test_no_run_up_and_no_song_both_fall_back_to_a_silent_track(intro_home):
    for proj in (_song_proj(intro_home, offset=0.0),
                 _song_proj(intro_home, offset=20.0, song="")):
        args = studio.intro_head_command(proj, Path("h.mp4"))
        assert "anullsrc=channel_layout=stereo:sample_rate=48000" in args
        assert "-filter_complex" not in args


def test_the_intro_head_matches_the_reel_so_the_two_can_splice(root, intro_home):
    """The join copies the reel rather than re-encoding it, which it can only
    do if the intro was written to the same shape: size, rate, one stereo
    track. A mismatch here is a re-encode of the whole reel at best."""
    got, _, _ = _with_intro(root, intro_home)
    args = studio.intro_head_command(got, Path("head.mp4"))
    W, H = studio.SIZES[got["format"]]
    vf = args[args.index("-vf") + 1]
    assert vf.startswith(f"fps={studio.FPS},") and f"{W}:{H}" in vf
    assert vf.endswith("setsar=1,format=yuv420p")
    assert args[args.index("-c:a") + 1] == "aac"
    assert args[args.index("-ar") + 1] == "48000"
    assert args[args.index("-ac") + 1] == "2"


def test_prepend_intro_actually_runs(root, intro_home, tmp_path, monkeypatch):
    """The join step itself, not just the argv it builds.

    The argv builders are pure and were covered; _prepend_intro was not, and
    shipped calling video_codec_args without importing it. Every name in it is
    resolved only when a real render reaches it, so a test has to reach it too.
    """
    got, derived, _ = _with_intro(root, intro_home)
    job = studio.StudioJob(got, derived, root, tmp_path / "out.mp4")
    ran: list[list[str]] = []

    def fake_ff(argv, *, capture=False):
        ran.append(list(argv))
        # The head encode and the concat each write the file named last.
        Path(argv[-1]).write_bytes(b"x")
        return ""
    monkeypatch.setattr(job, "_run_ff", fake_ff)
    reel = tmp_path / "reel.part.mp4"
    reel.write_bytes(b"reel")
    job._prepend_intro("ffmpeg", reel)

    assert len(ran) == 2, ran                      # encode the head, then splice
    assert got["intro_clip"]["path"] in ran[0]     # the intro is what was encoded
    assert ran[1][ran[1].index("-f") + 1] == "concat"
    assert "-c" in ran[1] and ran[1][ran[1].index("-c") + 1] == "copy"
    # The reel it was handed is what came back, and no scratch file is left.
    assert reel.is_file()
    assert not list(reel.parent.glob("*.join.txt"))
    assert not list(reel.parent.glob("*.intro.mp4"))


def test_no_intro_means_no_extra_pass_at_all(root, intro_home):
    plain, _ = studio.plan(_clips(root), "montage", shape=Shape(bpm=120.0))
    plain["song"] = ""
    got, _, _ = studio.normalise(plain, root)
    assert got["intro_clip"] is None
    assert studio.intro_head_command(got, Path("head.mp4")) == []


def test_the_intro_never_moves_a_cut_or_changes_the_length(root, intro_home):
    plain, _ = studio.plan(_clips(root), "montage", shape=Shape(bpm=120.0))
    plain["song"] = ""
    _, d_plain, _ = studio.normalise(plain, root)
    _, derived, _ = _with_intro(root, intro_home)
    assert derived["length"] == pytest.approx(d_plain["length"])
    assert [r["start"] for r in derived["shots"]] == [r["start"] for r in d_plain["shots"]]
    assert derived["kills"] == pytest.approx(d_plain["kills"])


def test_a_muted_intro_plays_silence_rather_than_no_track(root, intro_home):
    """Concat lines streams up by position: both halves need one stereo track,
    whether or not the intro is meant to be heard."""
    got, _, _ = _with_intro(root, intro_home, audio=False)
    quiet = studio.intro_head_command(got, Path("head.mp4"))
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in quiet
    assert quiet[quiet.index("-map") + 3] == "1:a:0"     # the silence, not the clip
    got2, _, _ = _with_intro(root, intro_home, audio=True)
    loud = studio.intro_head_command(got2, Path("head.mp4"))
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" not in loud
    assert loud[loud.index("-map") + 3] == "0:a:0"       # the clip's own sound


def test_a_silent_intro_asked_to_play_its_sound_gets_a_silent_track(root, intro_home):
    path = _fake_intro(intro_home, "silent", has_audio=False)
    got, _, _ = _with_intro(root, intro_home, path=path, audio=True)
    args = studio.intro_head_command(got, Path("head.mp4"))
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in args


@pytest.mark.parametrize("fit,want,avoid", [("cover", "crop=", "pad="), ("contain", "pad=", "crop=")])
def test_the_intro_fills_or_fits_as_asked(root, intro_home, fit, want, avoid):
    got, _, _ = _with_intro(root, intro_home, fit=fit)
    args = studio.intro_head_command(got, Path("head.mp4"))
    chain = args[args.index("-vf") + 1]
    assert want in chain and avoid not in chain


def test_the_lead_in_the_intro_is_for_is_on_the_derived_project(root, intro_home):
    proj, _ = studio.plan(_clips(root), "montage", shape=Shape(bpm=120.0))
    proj["song"] = ""
    got, derived, _ = studio.normalise(proj, root)
    assert derived["lead_in"] == 0.0
    got["shots"][0]["lead_in"] = True
    got2, derived2, _ = studio.normalise(got, root)
    assert derived2["lead_in"] == pytest.approx(got2["shots"][0]["pre"])


# ------------------------------------------------------------------ the command line

def _long_reel(root, n):
    """A project with `n` shots, by repeating what the library has."""
    proj, _ = studio.plan(_clips(root), "hype", shape=Shape(bpm=150.0), song="song.mp3")
    proj["song"] = ""
    base = proj["shots"]
    proj["shots"] = [dict(base[i % len(base)]) for i in range(n)]
    got, derived, _ = studio.normalise(proj, root)
    return got, derived, studio.segments(got, derived)


def test_a_long_reel_still_fits_on_a_windows_command_line(root, tmp_path):
    """MEASURED, not guessed: a real 50-shot reel built a 33,144-character
    command against CreateProcess's 32,767 limit and died with WinError 206
    AFTER encoding all fifty shots. MAX_SHOTS is 80, so the app was offering
    nearly twice what it could deliver."""
    for n in (50, studio.MAX_SHOTS):
        got, derived, segs = _long_reel(root, n)
        files = [tmp_path / f"seg{i:03d}.mp4" for i in range(len(segs))]
        argv = studio.assemble_command(got, derived, segs, files, tmp_path / "out.mp4",
                                       textdir=tmp_path)
        length = sum(len(a) + 3 for a in argv)
        assert length < 32_767, f"{n} shots: {length} characters is over the Windows limit"
        # Over the threshold it must be the file form, or the line would grow
        # with the shot count again the moment the graph did. Which spelling
        # depends on the ffmpeg installed -- see tools.filter_script_flag.
        assert any(x in argv for x in ("-filter_complex_script", "-/filter_complex")),             f"{n} shots: still inline"


def test_the_graph_in_the_script_file_is_the_graph_that_was_built(root, tmp_path):
    got, derived, segs = _long_reel(root, 50)
    files = [tmp_path / f"seg{i:03d}.mp4" for i in range(len(segs))]
    argv = studio.assemble_command(got, derived, segs, files, tmp_path / "out.mp4",
                                   textdir=tmp_path)
    from autostream.clips.tools import filter_script_flag
    script = Path(argv[argv.index(filter_script_flag()) + 1])
    graph = script.read_text(encoding="utf-8")
    # The same shape the inline form has, and every input wired up.
    assert graph.count("[s0]") >= 1 and "[v]" in graph and "[a]" in graph
    assert graph.count(";") >= len(segs)
    assert "\n" not in graph          # one line; ffmpeg reads the file whole


def test_a_short_reel_keeps_the_command_readable(root, tmp_path):
    """The file form is a workaround for an OS limit, not the normal path: a
    graph hidden in a temp file is a graph nobody will find in a log."""
    got, derived, segs = _long_reel(root, 6)
    files = [tmp_path / f"seg{i:03d}.mp4" for i in range(len(segs))]
    argv = studio.assemble_command(got, derived, segs, files, tmp_path / "out.mp4",
                                   textdir=tmp_path)
    assert "-filter_complex" in argv and "-filter_complex_script" not in argv
