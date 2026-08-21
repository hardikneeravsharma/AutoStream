"""Reading kills out of a game's kill feed.

Every number asserted here was MEASURED, not chosen. The source is 720 frames
of real Counter-Strike 2 -- 12 minutes at 1 fps, 110 sightings of the player's
name, 22 distinct feed rows -- plus individual rows checked by eye against
contact sheets cut from the same recording.

Where a constant is load-bearing, the test says what broke when it was wrong.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autostream.clips import killfeed as kf          # noqa: E402
from autostream.clips import profiles                # noqa: E402
from autostream.clips.profiles import Profile        # noqa: E402

# The band as the scan sees it: a 768x292 strip off a 1080p frame, upscaled 4x.
CROP_W, CROP_H = 3072.0, 1168.0


def _w(text, left, right, top=100.0):
    """One OCR word, positioned in crop pixels."""
    return kf.Word(text=text, conf=0.0, x=(left + right) / 2,
                   left=left, right=right, top=top, line=(1, 1, 1))


def _find(words, player="YUVANETA"):
    return kf.find_all(words, CROP_W, CROP_H, player)


# ------------------------------------------------------------ finding the name

def test_the_name_is_matched_through_tesseracts_usual_mistakes():
    # Real reads off the recording. "VUVANETA" comes back more often than the
    # correct spelling does, so exact matching would miss most of the kills.
    for read in ("YUVANETA", "VUVANETA", "VIVANETA", "vuvaneta", "YuvVANETA"):
        got = _find([_w(read, 1900, 2190)])
        assert got, f"{read!r} should have matched"
        assert got[0].ratio >= kf.MATCH_RATIO


def test_unrelated_words_do_not_match():
    # Real tokens from the same footage, including another player's name. The
    # measured noise ceiling was 0.55 against a 0.72 threshold.
    for junk in ("yang", "beta", "wAcKuPrAnKeTeR", "Jitter", "phoniesx", "Zolt"):
        assert not _find([_w(junk, 1900, 2190)]), f"{junk!r} must not match"


def test_confidence_is_ignored_because_it_is_meaningless_here():
    # A perfectly-read name came back with confidence 0 while netgraph junk
    # scored 70. Gating on confidence threw away the only word that mattered.
    got = _find([kf.Word(text="YUVANETA", conf=0.0, x=2000, left=1900,
                         right=2190, top=100, line=(1, 1, 1))])
    assert got and got[0].ratio == 1.0


# ------------------------------------------------------- which side of the row

def test_the_side_of_the_row_decides_kill_or_death():
    # Kill sightings measured 0.594-0.828 and deaths 0.966-0.988, with nothing
    # in between, so the threshold sits in a gap 0.14 wide.
    kill = _find([_w("YUVANETA", 0.72 * CROP_W, 0.807 * CROP_W)])[0]
    death = _find([_w("YUVANETA", 0.88 * CROP_W, 0.966 * CROP_W)])[0]
    assert kill.kind == "kill"
    assert death.kind == "death"


def test_both_rows_are_found_when_a_trade_puts_you_on_two_at_once():
    # Keeping only the strongest match per frame dropped the death on five
    # consecutive frames of real footage, so a trade read as a clean kill.
    got = _find([
        _w("VUVANETA", 0.53 * CROP_W, 0.714 * CROP_W, top=200),
        _w("YUVANETA", 0.88 * CROP_W, 0.966 * CROP_W, top=340),
    ])
    assert {s.kind for s in got} == {"kill", "death"}


def test_junk_glued_to_the_name_does_not_move_its_box():
    # Tesseract fused the netgraph's "20ms" onto the name, moving the right
    # edge 69px -- far enough to push a kill over the death threshold.
    clean = _find([_w("YUVANETA", 2705, 2967)])[0]
    fused = _find([_w("vuvaneeams", 2701, 3036)])[0]
    assert abs(clean.right - fused.right) < 0.02

    # A run of junk on the left is trimmed the same way.
    plain = _find([_w("YUVANETA", 1920, 2192)])[0]
    prefixed = _find([_w("FPPYUVANETA", 1810, 2192)])[0]
    assert abs(plain.left - prefixed.left) < 0.01

    # But a SINGLE stray character is left alone: it is far more likely to be a
    # misread of a real glyph than something glued on. Trimming the "!" out of
    # "VUVANET!" -- the last letter misread -- discarded a real character's
    # width, moved the right edge 0.017 and split one kill into two.
    misread = _find([_w("VUVANET!", 2229, 2500)])[0]
    exact = _find([_w("VUVANETA", 2229, 2500)])[0]
    assert misread.right == exact.right


def test_hud_furniture_is_not_mistaken_for_a_player():
    # The netgraph sits inside the feed band. Counting it as a player standing
    # to the right of your name would turn every kill into an assist.
    assert not kf.name_like("20ms")
    assert not kf.name_like("Jitter")
    assert not kf.name_like("$1200")
    assert kf.name_like("wAcKyPrAnKsTeR")
    assert kf.name_like("Mr.Infinite")
    assert kf.name_like("D4MIEN")


# ------------------------------------------- sightings back into single events

def _sight(t, right, top, right_xs=(), left=None):
    left = right - 0.088 if left is None else left      # measured name width
    return kf.Sighting(time=t, left=left, right=right, top=top, ratio=1.0,
                       text="YUVANETA", other="", right_xs=tuple(right_xs))


def test_one_row_read_over_several_frames_is_one_event():
    # A row lives a median of 5s and is sampled every second, so without this
    # a single kill is reported five times over.
    ev = kf.collapse([_sight(t, 0.807, 0.66 - 0.06 * t) for t in range(8)])
    assert len(ev) == 1
    assert ev[0].seen == 8
    assert (ev[0].time, ev[0].end) == (0, 7)


def test_a_row_survives_the_frames_where_ocr_loses_it():
    # Measured: two frames in the middle of one row's life read nothing at all.
    # Without bridging that gap, one kill is counted twice.
    ev = kf.collapse([_sight(0, 0.807, 0.662), _sight(1, 0.806, 0.542),
                      _sight(2, 0.806, 0.540),
                      # frames 3 and 4 read nothing
                      _sight(5, 0.807, 0.181), _sight(6, 0.807, 0.181)])
    assert len(ev) == 1


def test_consecutive_kills_in_the_same_place_stay_separate():
    # Three real kills ran back to back, each appearing in the top slot as the
    # previous one expired, so they share a y and only x separates them. Their
    # right edges were 0.828, 0.803 and 0.675 -- the closest pair 0.025 apart,
    # which is what X_TOL has to stay under.
    ev = kf.collapse([_sight(t, 0.828, 0.182) for t in range(0, 8)] +
                     [_sight(t, 0.803, 0.182) for t in range(9, 15)] +
                     [_sight(t, 0.675, 0.182) for t in range(16, 21)])
    assert len(ev) == 3
    assert [e.kind for e in ev] == ["kill", "kill", "kill"]


def test_a_row_that_moves_down_the_screen_is_a_new_row():
    # New entries are added at the bottom and push older ones up, so a name
    # that has moved DOWN cannot be the row that was there a moment ago.
    ev = kf.collapse([_sight(0, 0.807, 0.182), _sight(1, 0.807, 0.182),
                      _sight(2, 0.807, 0.420), _sight(3, 0.807, 0.420)])
    assert len(ev) == 2


def test_a_box_the_wrong_size_for_the_name_is_discarded():
    # Tesseract drew one box around the name AND the netgraph behind it while
    # transcribing only the name, so the text looks clean and only the geometry
    # gives it away. Both real cases landed at the netgraph's right edge, which
    # invented a death that never happened.
    good = [_sight(t, 0.807, 0.182) for t in range(10)]
    phantom = kf.Sighting(time=4, left=0.705, right=0.989, top=0.145,
                          ratio=0.88, text="YOVANETA", other="")
    assert [e.kind for e in kf.collapse(good + [phantom])] == ["kill"]


def test_one_bad_frame_cannot_flip_a_kill_into_a_death():
    # A row sitting right on the kill/death boundary can have single frames
    # measure either side of it. The kind is voted over the row's whole life so
    # the odd frame out cannot invent a death.
    good = [_sight(t, 0.897, 0.182) for t in range(6)]
    odd = kf.Sighting(time=3, left=0.815, right=0.903, top=0.182, ratio=0.9,
                      text="YUVANETA", other="")
    ev = kf.collapse(good + [odd])
    assert len(ev) == 1
    assert ev[0].kind == "kill"


def test_deaths_are_grouped_more_loosely_than_kills():
    # Every death sits at the right margin whoever killed you, so x carries no
    # information for them and its jitter split one death into three. Kills
    # keep the tight tolerance: three real ones were only 0.025 apart.
    one = kf.collapse([_sight(0, 0.963, 0.375), _sight(2, 0.976, 0.275),
                       _sight(3, 0.966, 0.279), _sight(6, 0.965, 0.303)])
    assert len(one) == 1 and one[0].kind == "death"

    two = kf.collapse([_sight(t, 0.828, 0.182) for t in range(0, 6)] +
                      [_sight(t, 0.803, 0.182) for t in range(7, 13)])
    assert len(two) == 2


# --------------------------------------------------------------------- assists

def test_an_assist_is_detected_and_is_not_counted_as_a_kill():
    # "YUVANETA + Mr.Infinite <icon> phoniesx" is Mr.Infinite's kill, verified
    # by eye. Counting it would put "3 kills" on a clip where the player got
    # one, and the filename is the thing a viewer sees first.
    ev = kf.collapse([_sight(t, 0.594, 0.185, right_xs=(0.755, 0.969))
                      for t in range(6)])
    assert [e.kind for e in ev] == ["assist"]
    assert kf.to_kills(ev) == []


def test_one_name_to_the_right_is_your_victim_not_a_third_player():
    ev = kf.collapse([_sight(t, 0.714, 0.185, right_xs=(0.967,))
                      for t in range(6)])
    assert [e.kind for e in ev] == ["kill"]


def test_a_name_seen_in_a_single_frame_does_not_make_it_an_assist():
    # OCR fragmented "Mr.Infinite" into "vite" on exactly one frame. Real
    # players show up repeatedly at the same x; fragments do not.
    xs = [(0.967,)] * 5 + [(0.661, 0.967)]
    ev = kf.collapse([_sight(t, 0.714, 0.185, right_xs=x)
                      for t, x in enumerate(xs)])
    assert [e.kind for e in ev] == ["kill"]


def test_an_assist_is_not_decided_by_one_frames_view_of_the_row():
    # Which names Tesseract manages to read swung 2,1,1,1,0,1 across one real
    # assist row, so a per-frame majority called it a kill. Pooling the
    # positions over the row is what gets it right.
    xs = [(0.755, 0.969), (0.755,), (0.755,), (0.969,), (), (0.755,)]
    ev = kf.collapse([_sight(t, 0.594, 0.185, right_xs=x)
                      for t, x in enumerate(xs)])
    assert [e.kind for e in ev] == ["assist"]


def test_kills_assists_and_deaths_are_all_reported():
    ev = (kf.collapse([_sight(t, 0.714, 0.185, right_xs=(0.967,))
                       for t in range(4)])
          + kf.collapse([_sight(t, 0.966, 0.30) for t in range(20, 24)])
          + kf.collapse([_sight(t, 0.594, 0.185, right_xs=(0.755, 0.969))
                         for t in range(40, 44)]))
    assert kf.tally(ev) == {"kill": 1, "assist": 1, "death": 1}
    assert len(kf.to_kills(ev)) == 1


def test_a_clipped_kill_carries_a_tail_anchor():
    # The planner reserves its tail from `end`. A feed row has no "marker
    # cleared" moment, so `end` is the kill itself -- but the key must exist or
    # clips silently start cutting early again.
    k = kf.to_kills(kf.collapse([_sight(t, 0.714, 0.185, right_xs=(0.967,))
                                 for t in range(4)]))
    assert k and "end" in k[0] and k[0]["end"] == k[0]["time"]


# ------------------------------------------------------- the killfeed profile

def test_the_shipped_cs2_profile_reads_the_feed_rather_than_matching():
    p = profiles._build("cs2.exe", dict(profiles.BUILTIN["cs2.exe"]))
    assert p is not None
    assert p.mode == "killfeed"
    assert p.template == ""             # nothing to match, so nothing to ship

    # It must NOT claim to be usable before a name is set. A scan without one
    # finds nothing, which reads as "this game had no kills" rather than as the
    # configuration error it is.
    assert not p.exists()
    assert "in-game name" in p.why_not()
    p.player = "YUVANETA"
    assert p.exists()
    assert p.why_not() == ""


def test_a_killfeed_profile_round_trips_without_storing_the_players_name():
    # The name lives in games.yaml, so one edit changes it everywhere and a
    # profile shared with someone else carries nobody's identity.
    p = Profile(key="cs2.exe", label="CS2", band=(0.6, 0.03, 1.0, 0.3),
                template="", mode="killfeed", player="YUVANETA")
    d = p.as_dict()
    assert d["mode"] == "killfeed"
    assert "player" not in d
    assert profiles._build("cs2.exe", d).mode == "killfeed"


def test_an_unknown_detector_mode_is_rejected_rather_than_guessed():
    assert profiles._build("x.exe", {"band": [0, 0, 1, 1],
                                     "mode": "vibes"}) is None


def test_template_games_are_untouched_by_any_of_this():
    p = profiles._build("deltaforceclient.exe",
                        dict(profiles.BUILTIN["deltaforceclient.exe"]))
    assert p.mode == "template"
    assert p.player == ""
    assert p.template.endswith(".npy")


# ------------------------------------------------------------ wiring guards
#
# These exist because a refactor once deleted _extract along with a dead
# function beside it, and every other test still passed: nothing below the
# matching logic is exercised without a real recording to decode. A missing
# name here is a NameError the first time a user scans anything.

def test_the_functions_the_rest_of_the_app_calls_all_exist():
    for name in ("scan", "collapse", "find_all", "to_kills", "tally",
                 "name_like", "matched_span", "norm", "tesseract",
                 "default_workers", "_extract", "_read", "_sightings",
                 "_drop_bad_boxes", "_slots_right", "_sweep_stale_temp",
                 "_crop_words", "_ocr_words"):
        assert callable(getattr(kf, name, None)), f"killfeed.{name} is missing"


def test_the_video_path_has_no_undefined_names():
    """Compile-time check of the code no unit test can run.

    _sightings, _extract and _read only execute with a real recording to
    decode, so a name that does not exist in them survives the whole suite.
    Walking their bytecode for globals that are not defined catches it.
    """
    missing = []
    for fn in (kf.scan, kf._sightings, kf._extract, kf._read,
               kf._sweep_stale_temp, kf._crop_words, kf._ocr_words):
        code = fn.__code__
        for name in code.co_names:
            if name in fn.__globals__ or hasattr(__builtins__, name):
                continue
            if name in dir(__import__("builtins")):
                continue
            # Attribute names appear in co_names too, so only flag a bare
            # global that is loaded as one.
            import dis
            for ins in dis.get_instructions(code):
                if ins.opname == "LOAD_GLOBAL" and                         (ins.argval or "").lstrip("NULL + ") == name:
                    missing.append(f"{fn.__name__} -> {name}")
                    break
    assert not missing, f"undefined globals: {missing}"


def test_the_detector_dispatches_killfeed_mode():
    """detect.scan must hand a killfeed profile to the reader, not the matcher."""
    from autostream.clips import detect

    assert callable(getattr(detect, "scan_killfeed", None))
    p = Profile(key="cs2.exe", label="CS2", band=(0.6, 0.03, 1.0, 0.3),
                template="", mode="killfeed", player="")
    # No name set, so it must refuse with the actionable message rather than
    # scanning and quietly reporting no kills.
    try:
        detect.scan_killfeed(__import__("pathlib").Path("nope.mp4"), p, 10.0,
                             None, None)
    except RuntimeError as e:
        assert "in-game name" in str(e)
    else:
        raise AssertionError("a killfeed profile with no name must refuse")


# --------------------------------------------------- the calibration handler
#
# The killfeed branch of the calibrator only runs with a recording to decode,
# so it is exercised here with the frame reader stubbed out. Written after two
# separate wiring bugs -- a deleted helper and a Sighting being read as if it
# were a FeedEvent -- both of which the rest of the suite sailed straight past.

def _calibrate_with(monkeypatch, tmp_path, sightings, **body):
    from autostream import paths
    from autostream.clips import calibrate

    monkeypatch.setattr(paths, "CLIP_PROFILES", tmp_path / "profiles.yaml")
    monkeypatch.setattr(calibrate, "_killfeed_sightings_hook", None, raising=False)
    monkeypatch.setattr(kf, "_sightings", lambda *a, **k: list(sightings))
    monkeypatch.setattr(kf, "tesseract", lambda: "tesseract")
    monkeypatch.setattr(calibrate, "media_info",
                        lambda p: {"width": 1920, "height": 1080,
                                   "duration": 600.0})
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"")
    return calibrate.from_request({
        "path": str(src), "t": 60.0, "box": [0.60, 0.03, 1.00, 0.30],
        "label": "Counter-Strike 2", "key": "cs2.exe", "mode": "killfeed",
        **body})


def test_calibrating_a_killfeed_game_saves_a_usable_profile(monkeypatch, tmp_path):
    from autostream.clips import profiles

    hit = kf.Sighting(time=60.0, left=0.72, right=0.807, top=0.18, ratio=1.0,
                      text="YUVANETA", other="Rico", right_xs=(0.96,))
    r = _calibrate_with(monkeypatch, tmp_path, [hit], player="YUVANETA")
    assert r.get("ok") and r.get("saved"), r
    assert r["mode"] == "killfeed"
    assert r["read"] == "YUVANETA"      # .text, not .matched
    assert r["kind"] == "kill"
    assert "YUVANETA" in r["note"]

    saved = profiles._build("cs2.exe", __import__("yaml").safe_load(
        (tmp_path / "profiles.yaml").read_text(encoding="utf-8"))["cs2.exe"])
    assert saved.mode == "killfeed"
    # The band is the box as drawn - a feed is not widened like a glyph is.
    assert [round(v, 3) for v in saved.band] == [0.6, 0.03, 1.0, 0.3]


def test_calibrating_refuses_when_the_name_is_not_readable(monkeypatch, tmp_path):
    # Saving here would produce a profile that reports "no kills found" on
    # every recording, which is indistinguishable from a quiet game.
    r = _calibrate_with(monkeypatch, tmp_path, [], player="NOTAREALNAME")
    assert not r.get("saved")
    assert r["separation"] == "bad"
    assert "not readable" in r["note"]
    assert not (tmp_path / "profiles.yaml").exists()


def test_calibrating_a_killfeed_game_demands_a_name(monkeypatch, tmp_path):
    r = _calibrate_with(monkeypatch, tmp_path, [])
    assert "in-game name" in r.get("error", "")


def test_a_big_box_is_still_refused_for_a_marker_game(monkeypatch, tmp_path):
    # The size checks must stay in force for template mode: they are what stops
    # someone calibrating a template that matches half the screen.
    from autostream.clips import calibrate

    monkeypatch.setattr(calibrate, "media_info",
                        lambda p: {"width": 1920, "height": 1080,
                                   "duration": 600.0})
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"")
    r = calibrate.from_request({"path": str(src), "t": 60.0,
                                "box": [0.60, 0.03, 1.00, 0.30],
                                "label": "CS2", "key": "cs2.exe"})
    assert "too much of the screen" in r.get("error", "")


# ------------------------------------------------- what counts as "same row"

def test_two_words_on_one_row_are_recognised_despite_differing_box_tops():
    """Tesseract's box top follows the tallest letter in the token.

    "/ANETA" and "Flex" sit on one feed line but their boxes differed by 31px,
    and a 12px tolerance decided they were on different rows -- so the victim
    went uncounted and a real assist was scored as a kill.
    """
    got = _find([
        _w("YUVANETA", 0.50 * CROP_W, 0.594 * CROP_W, top=390),
        _w("insane", 0.62 * CROP_W, 0.700 * CROP_W, top=372),
        _w("Flex", 0.90 * CROP_W, 0.968 * CROP_W, top=359),
    ])
    assert len(got) == 1
    assert len(got[0].right_xs) == 2, "both players past the name must count"
    assert kf.collapse([got[0], got[0]])[0].kind == "assist"


def test_the_row_below_is_not_counted_as_part_of_this_one():
    # Rows sit 0.118 apart. Pulling the next row's names in turned real kills
    # into assists, which is what caps the tolerance.
    got = _find([
        _w("YUVANETA", 0.62 * CROP_W, 0.714 * CROP_W, top=200),
        _w("wAcKyPrAnKsTeR", 0.80 * CROP_W, 0.967 * CROP_W, top=204),
        # the next row down, 0.118 of the strip lower
        _w("SaltFarmer", 0.55 * CROP_W, 0.660 * CROP_W, top=200 + 0.118 * CROP_H),
        _w("Khalnaayak", 0.80 * CROP_W, 0.960 * CROP_W, top=204 + 0.118 * CROP_H),
    ])
    mine = [s for s in got if s.right < 0.9][0]
    assert len(mine.right_xs) == 1, "only the victim on this row may count"


def test_the_same_row_tolerance_is_a_fraction_not_a_pixel_count():
    # A pixel constant is silently wrong at any other resolution or HUD scale,
    # and this one is compared against an upscaled crop.
    assert 0 < kf.SAME_ROW < 0.118, "must sit below one row's height"


def test_netgraph_text_is_rejected_however_badly_it_is_read():
    # The same recording produced all of these for one static overlay label.
    # An exact blocklist caught only the first, and the rest counted as players
    # standing on the row -- turning verified kills into assists.
    for junk in ("Jitter", "{Jitter", "qJitter", "Jitter,", "itter", "jitte"):
        assert not kf.name_like(junk), f"{junk!r} is the netgraph, not a player"
    for real in ("Flex", "Rico", "ANSHU", "Zolt", "insane", "SaltFarmer"):
        assert kf.name_like(real), f"{real!r} is a player"


# ------------------------------------ telling one player's drift from two players

def test_a_victims_own_wobble_is_not_a_second_player():
    """The single most expensive bug in this detector.

    A victim's right edge wandered 0.965 -> 0.971 over one row's life. Clustered
    too tightly that reads as two people standing past your name, which makes
    your kill an assist -- and it did exactly that to fourteen real kills across
    an 88-minute recording before it was caught.
    """
    xs = [(0.965,), (0.971,), (0.966,), (0.969,), (0.965,), (0.970,)]
    ev = kf.collapse([_sight(t, 0.828, 0.182, right_xs=x)
                      for t, x in enumerate(xs)])
    assert [e.kind for e in ev] == ["kill"]


def test_two_real_players_on_the_row_are_still_two():
    # Measured 0.21-0.27 apart on real assist rows, against a victim's own
    # drift of 0.006 -- so the two cases are an order of magnitude apart.
    xs = [(0.755, 0.969)] * 6
    ev = kf.collapse([_sight(t, 0.594, 0.185, right_xs=x)
                      for t, x in enumerate(xs)])
    assert [e.kind for e in ev] == ["assist"]


def test_the_slot_tolerance_sits_between_the_two_measurements():
    # Below one player's drift it invents players; above the gap between two
    # players it loses them.
    assert 0.01 < kf.SLOT_TOL < 0.20


# ------------------------------------------- the weapon icon poses as a player

def test_the_weapon_icon_is_not_counted_as_a_player():
    """Tesseract transcribes the icon as a word and it sits in the killer slot.

    "gage", "gummi", "pei" and "gagel" all came off real rows. Counted as
    players they turned two verified kills into assists in the same scan.
    """
    got = _find([
        _w("YUVANETA", 0.70 * CROP_W, 0.787 * CROP_W, top=200),
        _w("gummi", 0.801 * CROP_W, 0.867 * CROP_W, top=204),      # the icon
        _w("SoltFormer", 0.874 * CROP_W, 0.968 * CROP_W, top=202),  # the victim
    ])
    assert kf.collapse(got * 4)[0].kind == "kill"


def test_a_real_killer_name_past_yours_is_still_an_assist():
    got = _find([
        _w("YUVANETA", 0.50 * CROP_W, 0.595 * CROP_W, top=200),
        _w("Kholnoayek", 0.626 * CROP_W, 0.727 * CROP_W, top=204),
        _w("SoltFermer", 0.874 * CROP_W, 0.968 * CROP_W, top=202),
    ])
    assert kf.collapse(got * 4)[0].kind == "assist"


def test_a_name_to_your_left_means_the_kill_is_yours():
    """The line reads "assister + killer <icon> victim".

    An assister is always leftmost, so somebody standing to your left is the
    assister and you are the killer -- whatever the tokens to your right look
    like. This is what rescued "Khalnaayak + YUVANETA [rifle] SaltFarmer".
    """
    got = _find([
        _w("Khatneeyek", 0.571 * CROP_W, 0.668 * CROP_W, top=204),
        _w("YUVANETA", 0.70 * CROP_W, 0.787 * CROP_W, top=200),
        _w("gummi", 0.801 * CROP_W, 0.867 * CROP_W, top=204),
        _w("SoltFormer", 0.874 * CROP_W, 0.968 * CROP_W, top=202),
    ])
    mine = [g for g in got if 0.7 < g.right < 0.9]
    assert mine, "the player should still be found"
    assert kf.collapse(mine * 4)[0].kind == "kill"


def test_an_unreadable_killer_name_falls_back_to_calling_it_a_kill():
    """A documented limit, asserted so it stays deliberate.

    "YUVANETA + ::: insane ::: [rifle] Flex" is an assist, but the colons and a
    washed-out sky left the killer's name unreadable -- only the victim came
    through. With nothing in the killer slot to see, an assist is
    indistinguishable from a kill, and the detector errs toward the kill.
    """
    got = _find([
        _w("YUVANETA", 0.50 * CROP_W, 0.594 * CROP_W, top=390),
        _w("Flex", 0.90 * CROP_W, 0.968 * CROP_W, top=359),
    ])
    assert kf.collapse(got * 4)[0].kind == "kill"
