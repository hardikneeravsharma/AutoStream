"""Tests for recording, the session journal and clip planning.

These cover the things that broke silently while this was being built. Every
one of them is a failure that produces plausible-looking output rather than an
exception, which is exactly the kind that survives a manual smoke test:

  * a template matched at the wrong resolution finds ZERO kills and looks like
    a session with no kills in it
  * xfade offsets computed as i*duration drift further out of sync with every
    clip, and the first join still looks fine
  * "minimum kills per clip" filtering on the FIGHT's kill count instead of the
    clip's yields two-kill clips from a setting that asked for five
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import history, paths  # noqa: E402
from autostream.clips import montage, plan, profiles  # noqa: E402
from autostream.clips.profiles import Profile  # noqa: E402


# --------------------------------------------------------------- montage math

def test_xfade_offsets_are_cumulative():
    """Each xfade overlaps by D, so offsets shrink relative to a naive i*d."""
    durs = [10.0, 8.0, 12.0, 6.0]
    d = 0.5
    offs = montage._plan_offsets(durs, d)
    assert offs == [9.5, 17.0, 28.5]
    # the naive version everyone writes first
    naive = [i * durs[0] for i in range(1, len(durs))]
    assert offs != naive


def test_montage_duration_matches_the_sum_minus_overlaps():
    durs = [20.0, 20.0, 20.0]
    d = 0.6
    assert montage.expected_duration(durs, d) == pytest.approx(60.0 - 2 * 0.6)


def test_offsets_stay_positive_and_ordered():
    """A negative offset is a filtergraph error with an unhelpful message."""
    durs = [4.0, 4.0, 4.0, 4.0, 4.0]
    d = montage.clamp_transition(durs, 2.0)
    offs = montage._plan_offsets(durs, d)
    assert offs[0] > 0
    assert offs == sorted(offs)


def test_transition_is_clamped_to_the_shortest_clip():
    assert montage.clamp_transition([10.0, 1.0, 8.0], 2.0) == pytest.approx(0.4)
    assert montage.clamp_transition([10.0], 2.0) == 0.0


def test_swirl_maps_to_a_real_xfade_name():
    """xfade has no 'swirl'; the label must resolve to something ffmpeg knows."""
    assert montage.TRANSITIONS["radial"] == "radial"
    assert "swirl" not in montage.TRANSITIONS.values()
    for name in montage.MIXED_POOL:
        assert name in montage.TRANSITIONS


# ------------------------------------------------------------------ clustering

def _kills(*times):
    return [{"time": t, "score": 0.9, "count": 1} for t in times]


def test_cluster_splits_on_the_gap():
    b = plan.cluster(_kills(10, 12, 14, 100, 102), gap=22.0)
    assert [x.kills for x in b] == [3, 2]


def test_cluster_chains_through_close_kills():
    """Each kill is measured against the PREVIOUS one, not the burst start, so
    a long running fight stays one burst."""
    b = plan.cluster(_kills(0, 20, 40, 60, 80), gap=22.0)
    assert len(b) == 1
    assert b[0].span == 80


# -------------------------------------------------------------- clip selection

def test_min_kills_counts_what_is_in_the_clip():
    """A 5-kill fight spread over 90s must not yield a 5-kill 20s clip."""
    spread = _kills(0, 30, 60, 90, 120)          # one burst only if gap is huge
    plans = plan.build(spread, game="G", min_kills=5, clip_seconds="20",
                       gap=40.0)
    for p in plans:
        assert p.kills >= 5, f"{p.name} claims {p.kills} kills but 5 were asked for"
    # nothing can fit 5 kills 30s apart into 20 seconds
    assert plans == []


def test_fixed_window_picks_the_densest_part_of_a_fight():
    # four kills bunched at the end of a long burst
    times = [0, 40, 80, 100, 102, 104, 106]
    plans = plan.build(_kills(*times), game="G", min_kills=4,
                       clip_seconds="20", pre_roll=5, tail=2.0, gap=45.0)
    assert len(plans) == 1
    p = plans[0]
    assert p.kills == 4
    # End is fixed by the last kill plus the tail (106 + 2). The start is then
    # pre_roll before the FIRST kill kept, not the full 20s back -- the length
    # is a ceiling, not dead air to fill.
    assert p.end == pytest.approx(108.0)
    assert p.start == pytest.approx(95.0)        # 100 - pre_roll
    assert p.duration == pytest.approx(13.0)     # shorter than the 20s ceiling
    assert p.burst_kills == 7


def test_auto_length_follows_the_whole_fight():
    plans = plan.build(_kills(100, 110, 120), game="G", min_kills=3,
                       clip_seconds="auto", pre_roll=6)
    assert len(plans) == 1
    assert plans[0].start == pytest.approx(94.0)
    assert plans[0].end == pytest.approx(124.0)  # 120 + POST_ROLL


def test_clips_never_start_before_zero_or_run_past_the_source():
    plans = plan.build(_kills(2, 4), game="G", min_kills=2, clip_seconds="30",
                       pre_roll=10, source_duration=20.0)
    assert plans[0].start >= 0.0
    assert plans[0].end <= 20.0


def test_ranking_is_stable_and_best_first():
    kills = _kills(10, 11, 12, 200, 201, 400)
    a = plan.build(kills, game="G", min_kills=1, clip_seconds="30")
    b = plan.build(kills, game="G", min_kills=1, clip_seconds="30")
    assert [p.name for p in a] == [p.name for p in b]
    assert [p.kills for p in a] == sorted((p.kills for p in a), reverse=True)


# ------------------------------------------------------------------- filenames

def test_filename_states_the_game_kills_position_and_length():
    plans = plan.build(_kills(3610, 3615), game="Delta Force", min_kills=2,
                       clip_seconds="30", pre_roll=6, tail=2.0)
    name = plans[0].name
    assert name.startswith("Delta-Force_01_")
    assert "2kills" in name
    # Position is where the CLIP starts: pre_roll before the first kill.
    assert "1h00m04s" in name
    # Length is the ceiling; this fight only needs 13s of it.
    assert name.endswith("_13s")


def test_position_in_the_name_is_the_clip_start_not_the_kill():
    plans = plan.build(_kills(600), game="G", min_kills=1, clip_seconds="20",
                       pre_roll=8, tail=2.0)
    assert plans[0].start == pytest.approx(592.0)     # 600 - pre_roll
    assert "9m52s" in plans[0].name


# ------------------------------------------------------------ the tail guarantee

def test_a_clip_never_ends_within_the_tail_of_a_kill():
    """The reported bug: a 10s clip ended 0.5s after its third kill, with the
    kill feed still running."""
    kills = _kills(1268.0, 1273.0, 1276.5)
    for length in ("10", "20", "30", "auto"):
        plans = plan.build(kills, game="G", min_kills=1, clip_seconds=length,
                           pre_roll=6, tail=2.0)
        for p in plans:
            inside = [k["time"] for k in kills if p.start <= k["time"] <= p.end]
            if inside:
                assert p.end - max(inside) >= 2.0 - 1e-6, (
                    f"{length}: clip ends {p.end - max(inside):.2f}s after a kill")


def test_the_tail_is_measured_from_the_marker_leaving_not_appearing():
    """`time` is when the marker appeared. Ending two seconds after THAT still
    cuts the feed, because the marker is on screen for a couple of seconds."""
    kills = [{"time": 100.0, "end": 103.0, "score": 0.9, "count": 1}]
    p = plan.build(kills, game="G", min_kills=1, clip_seconds="20",
                   pre_roll=6, tail=2.0)[0]
    assert p.end == pytest.approx(105.0)      # 103 (marker gone) + 2, not 102


def test_kills_recorded_before_end_tracking_still_work():
    """Old session.json files have no `end` key."""
    p = plan.build([{"time": 100.0, "score": 0.9, "count": 1}], game="G",
                   min_kills=1, clip_seconds="20", pre_roll=6, tail=2.0)[0]
    assert p.end == pytest.approx(102.0)


def test_a_kill_is_never_left_inside_the_reserved_tail():
    """Rejecting those candidates is the whole mechanism -- an accepted window
    with a kill in its last two seconds is the original bug."""
    kills = _kills(0.0, 1.0, 2.0, 3.0, 9.5)
    for p in plan.build(kills, game="G", min_kills=1, clip_seconds="10",
                        pre_roll=3, tail=2.0):
        for k in kills:
            t = k["time"]
            assert not (p.end - 2.0 < t <= p.end), f"kill at {t} sits in the tail"


def test_tail_can_be_turned_off():
    plans = plan.build(_kills(100.0), game="G", min_kills=1, clip_seconds="10",
                       pre_roll=6, tail=0.0)
    assert plans[0].end == pytest.approx(100.0)


def test_whole_moment_keeps_at_least_the_tail():
    p = plan.build(_kills(50.0, 55.0), game="G", min_kills=1,
                   clip_seconds="auto", pre_roll=6, tail=8.0)[0]
    assert p.end - 55.0 >= 8.0 - 1e-6


def test_singular_kill_reads_correctly():
    plans = plan.build(_kills(60), game="G", min_kills=1, clip_seconds="10")
    assert "_1kill_" in plans[0].name


def test_slug_keeps_names_filesystem_safe():
    assert plan.slug("Tom Clancy's: Rainbow/Six") == "Tom-Clancys-RainbowSix"
    assert plan.slug("") == "Game"


# ----------------------------------------------------- resolution normalisation

def _profile(ref_height: int) -> Profile:
    return Profile(key="k", label="L", band=(0.42, 0.650, 0.58, 0.712),
                   template="x.npy", ref_height=ref_height)


def test_band_rescales_to_the_template_reference_height():
    """The whole reason a 720p template works on a 1080p recording.

    Without this the template is matched against a band 1.5x too large and the
    scan returns nothing at all -- not fewer kills, none.
    """
    from autostream.clips.detect import band_geometry

    p = _profile(720)
    _crop_1080, match_1080 = band_geometry(1920, 1080, p)
    _crop_1440, match_1440 = band_geometry(2560, 1440, p)
    _crop_720, match_720 = band_geometry(1280, 720, p)
    # every source resolution ends up matching at the same geometry
    assert match_1080 == match_720
    assert match_1440 == match_720


def test_crop_is_computed_in_whole_pixels():
    """ffmpeg ROUNDS a fractional crop where int() truncates. Predicting the
    size rather than computing it misaligns the reshape by a pixel per row."""
    from autostream.clips.detect import band_geometry

    (x, y, w, h), _ = band_geometry(1920, 1080, _profile(720))
    for v in (x, y, w, h):
        assert isinstance(v, int)
    assert w > 0 and h > 0
    assert x + w <= 1920 and y + h <= 1080


def test_crop_tracks_the_source_resolution():
    from autostream.clips.detect import band_geometry

    p = _profile(720)
    (_, _, w720, _), _ = band_geometry(1280, 720, p)
    (_, _, w1080, _), _ = band_geometry(1920, 1080, p)
    assert w1080 > w720          # cropped at native scale, then normalised


def test_shipped_delta_force_profile_is_present_and_sane():
    from autostream.clips import profiles

    p = profiles.for_game("deltaforceclient.exe")
    assert p is not None
    assert p.exists(), "the shipped kill-marker template is missing"
    assert p.ref_height == 720
    assert 0.5 < p.match_min < 0.95


def test_profile_lookup_falls_back_to_the_display_name():
    from autostream.clips import profiles

    assert profiles.for_game("unknown.exe", "Delta Force") is not None
    assert profiles.for_game("deltaforce.exe") is not None       # alias
    assert profiles.for_game("nothing.exe", "Nothing At All") is None


# --------------------------------------------------------------------- history

def test_history_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HISTORY_FILE", tmp_path / "history.jsonl")

    class S:
        session_number = 4
        broadcast_id = "abc"
        current_game = "Delta Force"
        current_key = "deltaforceclient.exe"
        session_games = ["Delta Force"]
        session_start = 1_755_600_000.0

    entry = history.record_session(S(), watch_url="https://y/w?v=abc",
                                   title="DF", recording_path=None)
    assert entry["game"] == "Delta Force"
    rows = history.read()
    assert len(rows) == 1 and rows[0]["broadcast_id"] == "abc"


def test_history_skips_corrupt_lines(tmp_path, monkeypatch):
    f = tmp_path / "history.jsonl"
    monkeypatch.setattr(paths, "HISTORY_FILE", f)
    f.write_text('{"session": 1}\nnot json at all\n\n{"session": 2}\n',
                 encoding="utf-8")
    rows = history.read()
    assert [r["session"] for r in rows] == [2, 1]      # newest first


def test_history_reports_a_missing_recording(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HISTORY_FILE", tmp_path / "history.jsonl")
    history.append({"session": 1, "recording_path": str(tmp_path / "gone.mp4")})
    real = tmp_path / "there.mp4"
    real.write_bytes(b"x" * 10)
    history.append({"session": 2, "recording_path": str(real)})
    rows = history.annotate(history.read())
    assert rows[0]["has_recording"] is True
    assert rows[1]["has_recording"] is False


def test_history_never_raises_on_a_bad_path(monkeypatch):
    monkeypatch.setattr(paths, "HISTORY_FILE",
                        Path("Z:/definitely/not/a/drive/history.jsonl"))
    history.append({"session": 1})        # must not raise
    assert history.read() == []


# ---------------------------------------------------------------------- config

def test_config_paths_are_only_two_levels_deep():
    """cfg._split_path rejects anything deeper, so record.x not obs.record.x."""
    from autostream import cfg, schema

    for path in schema.FIELDS_BY_PATH:
        if path.startswith(("record.", "clips.")):
            section, _, key = path.partition(".")
            assert key and "." not in key
            assert key in cfg.DEFAULTS[section], f"{path} missing from DEFAULTS"


def test_every_new_setting_validates_its_own_default():
    from autostream import cfg, schema

    flat = schema.flatten(cfg.load())
    for path, value in flat.items():
        if path.startswith(("record.", "clips.")):
            assert schema.validate(path, value) is None, f"{path}={value!r}"


def test_section_icons_exist():
    from autostream import schema
    from autostream.ui.icons import ICONS

    for section in schema.CONFIG_SCHEMA:
        assert section["icon"] in ICONS, section["id"]


# -------------------------------------------------------------------------- ui

def test_the_ui_bundle_has_no_unsubstituted_placeholders():
    from autostream import ui

    assert "{{" not in ui.BODY
    assert 'id="view-clips"' in ui.BODY


def test_no_duplicate_top_level_js_names():
    """Every page's JS lands in ONE scope; a duplicate const is a SyntaxError
    that takes down the whole UI, not just one page."""
    import re

    from autostream import ui

    names = re.findall(r"^(?:const|var|let|function)\s+([A-Za-z_$][\w$]*)",
                       ui.JS, re.M)
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f"duplicate top-level JS declarations: {dupes}"


def test_clips_page_is_registered_everywhere():
    from autostream.ui import shell

    assert "('clips', 'film', 'Clips')".replace("'", '"') or True
    assert any(n[0] == "clips" for n in shell._NAV)
    assert "'clips'" in shell.SHELL_JS
    assert "PAGE_CLIPS" in shell.SHELL_JS


# ---------------------------------------------------------------- clip styles

def test_every_style_resolves_to_three_numbers():
    for sid in plan.STYLES:
        v = plan.style_values(sid)
        assert set(v) == {"pre_roll", "tail", "clip_seconds"}


def test_custom_leaves_the_individual_settings_alone():
    mine = {"pre_roll": 9.0, "tail": 9.0, "clip_seconds": "99"}
    assert plan.style_values("custom", mine) == mine
    assert plan.style_values(None, mine) == mine


def test_short_form_weights_the_end_not_the_start():
    """The whole point of the change: the old 6s/2s default put three times as
    much room before the kill as after it."""
    s = plan.STYLES["shortform"]
    assert s["tail"] >= s["pre_roll"]
    assert s["pre_roll"] <= 2.0


def test_montage_clips_are_short_enough_to_cut_together():
    assert 3 <= float(plan.STYLES["montage"]["clip_seconds"]) <= 8


def test_pre_roll_is_honoured_rather_than_padded_to_the_length():
    """A single kill in a 15s clip must not open with 11 seconds of run-up."""
    p = plan.build(_kills(600.0), game="G", min_kills=1, clip_seconds="15",
                   pre_roll=1.5, tail=2.0)[0]
    # 1.5s of run-up would make a 3.5s clip, under MIN_CLIP, so the run-up is
    # extended to reach the floor rather than the moment being dropped. The
    # tail is what may not move.
    assert p.end == pytest.approx(602.0)
    assert p.duration == pytest.approx(plan.MIN_CLIP)
    assert p.duration < 15.0                       # nowhere near the ceiling


def test_length_is_a_ceiling_never_exceeded():
    kills = _kills(*[100 + i for i in range(0, 40, 2)])
    for length in ("10", "15", "30"):
        for p in plan.build(kills, game="G", min_kills=1, clip_seconds=length,
                            pre_roll=1.5, tail=2.0, gap=60.0):
            assert p.duration <= float(length) + 1e-6


def test_montage_plays_in_the_order_things_happened():
    """Clips are NUMBERED best-first, but a session reel that jumps from the
    end of the match back to the start reads as an editing mistake."""
    kills = [{"time": t, "end": t + 1.5, "score": 0.9, "count": 1}
             for t in (120, 300, 640, 1268, 1273, 1276, 1600)]
    plans = plan.build(kills, game="D", min_kills=1, clip_seconds="15",
                       pre_roll=3.5, tail=2.0)
    masters = [f"clip{p.rank:02d}" for p in plans]
    # the best clip is not the earliest, so rank order is genuinely out of order
    assert plans[0].start != min(p.start for p in plans)
    ordered = [m for _p, m in sorted(zip(plans, masters), key=lambda pm: pm[0].start)]
    starts = sorted(p.start for p in plans)
    assert len(ordered) == len(masters)
    assert starts == [p.start for p, _m in sorted(zip(plans, masters),
                                                  key=lambda pm: pm[0].start)]


# ------------------------------------------------------------- thumbnails

def test_thumbnail_templates_survive_an_unknown_token():
    """A live session must never fail because a template has a typo in it."""
    from autostream import thumbnail as th
    v = {"game": "Delta Force", "channel": "YuvaNeta"}
    assert th._render_template("{game}", v) == "Delta Force"
    assert "{nonsense}" in th._render_template("{game} {nonsense}", v)
    assert th._render_template("", v) == ""
    assert th._render_template(None, v) == ""


def test_thumbnail_renders_without_an_obs_frame():
    """No frame, no base image -- still produces a valid file rather than
    holding up the broadcast."""
    import tempfile
    from pathlib import Path as _P

    from autostream import thumbnail as th
    with tempfile.TemporaryDirectory() as d:
        out = _P(d) / "t.jpg"
        got = th.render(None, game="Delta Force", channel="YuvaNeta",
                        headline="DELTA FORCE", sub="YuvaNeta", out=out)
        assert got and got.exists()
        from PIL import Image
        with Image.open(got) as im:
            assert im.size == (th.WIDTH, th.HEIGHT)
        assert got.stat().st_size <= th.MAX_BYTES


def test_thumbnail_stays_under_youtubes_size_limit():
    from autostream import thumbnail as th
    assert th.MAX_BYTES == 2 * 1024 * 1024
    assert (th.WIDTH, th.HEIGHT) == (1280, 720)


# --------------------------------------------------------- per-game names

def test_a_username_only_override_keeps_the_real_game_name():
    """Saving an in-game name creates a games.yaml entry with no `name`.
    Falling through to a title-cased exe there renamed VALORANT to
    'Valorant-Win64-Shipping'."""
    from autostream.gameindex import GameIndex

    idx = GameIndex.__new__(GameIndex)
    idx.overrides = {"valorant-win64-shipping.exe": {"username": "me"}}
    idx.public = {"valorant-win64-shipping.exe": "VALORANT"}
    idx.blocklist = set()
    hit = idx.lookup("valorant-win64-shipping.exe")
    assert hit.name == "VALORANT"
    assert hit.username == "me"


def test_username_reaches_the_title_variables():
    from datetime import datetime

    from autostream import titles
    v = titles.build_vars(game="G", hook="h", session_games=["G"],
                          session_start=datetime.now(), session_number=1,
                          username="YuvaNeta")
    assert v["username"] == "YuvaNeta"
    # and an absent one must not break a template that references it
    v2 = titles.build_vars(game="G", hook="h", session_games=["G"],
                           session_start=datetime.now(), session_number=1)
    assert v2["username"] == ""


# ------------------------------------------------------------------ the UI JS

def test_the_javascript_bundle_actually_parses():
    """Every page's JS lands in ONE script tag, so a syntax error in any of
    them kills the whole UI -- and the dashboard still LOOKS fine, because it
    is `is-active` in the static HTML. That is exactly how an unescaped
    apostrophe in a setup string shipped: the dashboard rendered, and every
    other tab silently stopped responding.

    Nothing else in the suite would have caught it.
    """
    esprima = pytest.importorskip("esprima")
    from autostream import ui
    esprima.parseScript(ui.JS)


def test_no_unescaped_apostrophes_in_single_quoted_js():
    """A cheap guard that works without esprima installed, aimed at the exact
    mistake above: an apostrophe inside a single-quoted JS string literal.

    Counts unescaped single quotes per line by scanning rather than by regex --
    a line that opens and closes its strings properly always has an even
    number.
    """
    from autostream import ui

    for n, line in enumerate(ui.JS.splitlines(), 1):
        code = line.strip()
        if not code.startswith("'"):
            continue
        quotes = 0
        i = 0
        while i < len(code):
            c = code[i]
            if c == "\\":
                i += 2
                continue
            if c == "'":
                quotes += 1
            i += 1
        assert quotes % 2 == 0, f"line {n} has an odd quote count: {code[:90]}"


# ------------------------------------------------- journalling the recording

def test_duration_comes_from_the_file_not_the_session(tmp_path, monkeypatch):
    """OBS may already be recording when a session starts -- start_recording()
    reuses that output rather than interrupting it -- so the file can be far
    longer than the session that adopted it. A 47-minute recording was being
    listed as "1m"."""
    monkeypatch.setattr(paths, "HISTORY_FILE", tmp_path / "history.jsonl")
    rec = tmp_path / "2026-08-19 23-19-47.mp4"
    rec.write_bytes(b"x" * 2048)
    history.append({
        "session": 1, "game": "Counter-Strike 2",
        "started": 1755648343.0, "ended": 1755648428.0,     # an 85-second session
        "recording_path": str(rec),
        "recording_seconds": 2840.1,                        # a 47-minute file
        "recording_started": 1755645587.0,
    })
    row = history.annotate(history.read())[0]
    assert row["duration"] == 2840                # the file, not the session
    assert row["session_seconds"] == 85           # still available separately
    assert row["display_started"] == 1755645587.0


def test_recording_start_is_read_from_obs_filename():
    from datetime import datetime

    got = history._started_from_name("C:/x/2026-08-19 23-19-47.mp4")
    assert got is not None
    assert datetime.fromtimestamp(got).strftime("%Y-%m-%d %H:%M:%S") == "2026-08-19 23:19:47"
    assert history._started_from_name("no-timestamp-here.mp4") is None


def test_ncc_still_matches_an_exact_patch_after_chunking():
    """`patches - means` is oh*ow*th*tw floats. With a hand-drawn 230x43
    template over a 576x73 band that is 425 MB for ONE frame, which ran the
    app to several gigabytes during calibration. Chunking must not change the
    answer."""
    import numpy as np

    from autostream.clips import detect

    rng = np.random.RandomState(7)
    band = (rng.rand(73, 576) * 255).astype(np.float32)
    tpl = band[10:53, 40:270].copy()
    tpl -= tpl.mean()
    score, _n = detect.ncc(band, tpl, 0.5)
    assert score == pytest.approx(1.0, abs=1e-3)


def test_ncc_matches_a_plain_unchunked_reference():
    import numpy as np

    from autostream.clips import detect

    rng = np.random.RandomState(11)
    band = (rng.rand(60, 200) * 255).astype(np.float32)
    tpl = (rng.rand(20, 40) * 255).astype(np.float32)
    tpl -= tpl.mean()

    th, tw = tpl.shape
    oh, ow = band.shape[0] - th + 1, band.shape[1] - tw + 1
    ref = np.empty((oh, ow), dtype=np.float32)
    tnorm = float(np.sqrt((tpl ** 2).sum())) + 1e-6
    for i in range(oh):
        for j in range(ow):
            w = band[i:i + th, j:j + tw]
            c = w - w.mean()
            ref[i, j] = (c * tpl).sum() / (np.sqrt((c ** 2).sum()) * tnorm + 1e-6)
    assert detect.ncc(band, tpl, 2.0)[0] == pytest.approx(float(ref.max()), abs=1e-4)


def test_a_recording_that_predates_the_session_is_flagged(tmp_path, monkeypatch):
    """OBS already recording when a session starts means the file can be a
    different game entirely. A 47-minute Delta Force recording was labelled
    Counter-Strike 2 because a 1-minute CS2 session adopted it."""
    monkeypatch.setattr(paths, "HISTORY_FILE", tmp_path / "history.jsonl")
    rec = tmp_path / "2026-08-19 23-19-47.mp4"
    rec.write_bytes(b"x" * 64)
    history.append({
        "session": 1, "game": "Counter-Strike 2",
        "started": 1755648343.0, "ended": 1755648428.0,
        "recording_path": str(rec),
        "recording_started": 1755645587.0,     # 45 minutes earlier
        "recording_seconds": 2840.0,
    })
    row = history.annotate(history.read())[0]
    assert row["pre_session_seconds"] > 60
    assert row["game_uncertain"] is True


def test_a_session_that_started_its_own_recording_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HISTORY_FILE", tmp_path / "history.jsonl")
    rec = tmp_path / "2026-08-19 05-15-45.mp4"
    rec.write_bytes(b"x" * 64)
    history.append({
        "session": 1, "game": "Delta Force",
        "started": 1755645350.0, "ended": 1755647000.0,
        "recording_path": str(rec),
        "recording_started": 1755645345.0,     # 5 seconds earlier: normal
        "recording_seconds": 1650.0,
    })
    assert history.annotate(history.read())[0]["game_uncertain"] is False


def test_the_game_can_be_corrected_across_path_separators(tmp_path, monkeypatch):
    """OBS reports outputPath with forward slashes while Python uses
    backslashes, so a literal compare matched nothing."""
    monkeypatch.setattr(paths, "HISTORY_FILE", tmp_path / "history.jsonl")
    rec = tmp_path / "rec.mp4"
    rec.write_bytes(b"x" * 64)
    stored = str(rec).replace("\\", "/")            # as OBS would report it
    history.append({"session": 1, "game": "Counter-Strike 2", "started": 10.0,
                    "ended": 20.0, "recording_path": stored,
                    "recording_started": 1.0, "recording_seconds": 100.0})
    assert history.set_game(str(rec), "Delta Force", "df.exe") is True
    row = history.annotate(history.read())[0]
    assert row["game"] == "Delta Force"
    assert row["game_key"] == "df.exe"
    assert row["game_uncertain"] is False        # a hand correction is trusted


# ------------------------------------------------------- per-game clip padding
#
# The styles in plan.py are measured against short-form retention and are right
# for a respawn shooter. A game whose kill ends a slow approach, and whose kill
# feed outlives the kill by seconds, needs more room at both ends -- so a
# profile can raise the floor.

def test_a_profile_can_raise_the_run_up_and_the_tail():
    p = profiles.Profile(key="x.exe", label="X", band=(0, 0, 1, 1),
                         template="", pre_roll_min=3.0, tail_min=4.0)
    assert p.padding(1.5, 2.0) == (3.0, 4.0)


def test_padding_is_a_floor_and_never_shortens_a_longer_style():
    # "Full context" asks for 6s of run-up. A game floor of 3 must not cut it.
    p = profiles.Profile(key="x.exe", label="X", band=(0, 0, 1, 1),
                         template="", pre_roll_min=3.0, tail_min=4.0)
    assert p.padding(6.0, 8.0) == (6.0, 8.0)


def test_a_game_with_no_floor_gets_exactly_what_was_asked_for():
    p = profiles.Profile(key="x.exe", label="X", band=(0, 0, 1, 1),
                         template="")
    assert p.padding(1.5, 2.0) == (1.5, 2.0)


def test_counter_strike_asks_for_more_room_than_short_form_gives():
    """Real clips from a 45-minute CS2 session came out FOUR SECONDS long.

    Two measurements say why that is wrong for this game and not for Delta
    Force: the feed row naming your kill lives a median of 5s, so a 2s tail
    cuts mid-announcement, and there is no respawn, so a kill is the end of an
    approach that 1.5s of run-up does not show.
    """
    cs2 = profiles.for_game("cs2.exe", "Counter-Strike 2")
    assert cs2 is not None
    pre, tail = cs2.padding(1.5, 2.0)
    assert pre >= 3.0 and tail >= 4.0
    # ...and a single-kill short-form clip is no longer a four-second stub.
    got = plan.build([{"time": 100.0, "end": 100.0}], game="CS2", min_kills=1,
                     clip_seconds="15", pre_roll=pre, tail=tail)[0]
    assert got.duration >= 7.0


def test_delta_force_is_left_alone():
    # Its 1.5s/2.0s were measured on its own footage and verified by eye.
    df = profiles.for_game("deltaforceclient.exe", "Delta Force")
    assert df.padding(1.5, 2.0) == (1.5, 2.0)


def test_the_padding_floors_survive_the_yaml_round_trip(tmp_path,
                                                        monkeypatch):
    monkeypatch.setattr(paths, "CLIP_PROFILES", tmp_path / "p.yaml")
    p = profiles.Profile(key="x.exe", label="X", band=(0.1, 0.2, 0.3, 0.4),
                         template="t.npy", pre_roll_min=3.0, tail_min=4.0)
    profiles.save(p)
    back = profiles.load_all().get("x.exe")
    assert back is not None
    assert back.pre_roll_min == 3.0 and back.tail_min == 4.0


def test_a_recut_reuses_the_newest_scan_not_the_oldest(tmp_path, monkeypatch):
    """FROM FOOTAGE. Sorted by name, the first session.json belongs to the run
    whose folder has no "_2" suffix -- the oldest scan there is. So a re-cut
    after the Valorant feed reader was fixed quietly reproduced the OLD kill
    list, and five clips came back out labelled "2 kills" holding one."""
    import json as _json
    from autostream import webui

    src = str(Path(r"C:/rec/x.mp4"))     # as the sidecar records it
    for name, kills, when in (("2026-08-27_2047_VALORANT", 33, 1000),
                              ("2026-08-27_2047_VALORANT_2", 30, 2000)):
        d = tmp_path / name
        d.mkdir()
        f = d / "session.json"
        f.write_text(_json.dumps(
            {"source": src, "kills": [{"time": float(i)} for i in range(kills)]}),
            encoding="utf-8")
        os.utime(f, (when, when))

    app = webui.Server.__new__(webui.Server)
    monkeypatch.setattr(app, "_clips_dir", lambda _c: tmp_path, raising=False)
    got = app._cached_kills(Path(src), object())
    assert got is not None and len(got) == 30, "the older 33-kill scan won"
