"""CS2 round kill tally, read from the cards under the crosshair.

The frames are synthetic, drawn in the geometry MEASURED off real footage: at
1080p a tally of N kills is exactly `18 + 16 * N` pixels wide, and every sample
of a given count measured the identical width. Pinning that here means a later
tweak that still happens to work on one recording, but has drifted from the
real geometry, fails in the suite rather than in the field.

Cases marked FROM FOOTAGE reproduce a specific measurement or a specific bug.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from autostream.clips import cs2_cards as cc

W, H = 130, 62                     # the card crop at 1080p
HUE = 338.0                        # this player's HUD colour; the default is not


def _bg(shade=(70, 55, 40)):
    a = np.zeros((H, W, 3), np.uint8)
    a[:, :] = shade                # Anubis sandstone: warm, and a real hazard
    return a


def _hud_rgb(hue=HUE, v=235):
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(hue / 360.0, 0.62, v / 255.0)
    return (int(r * 255), int(g * 255), int(b * 255))


def _tally(kills, hue=HUE, x0=15, y0=12, h=40, extra=0):
    """Draw a tally of `kills` cards at the measured geometry."""
    a = _bg()
    w = cc.CARD_W0 + cc.CARD_PITCH * kills + extra
    a[y0:y0 + h, x0:x0 + w] = _hud_rgb(hue)
    return a


# A frame of HUD_STRIP, as `measure_hue` samples it: the bottom 14% of a
# 1920x1080 screen, holding the card area and -- the hazard this reproduces --
# a facecam far bigger and far steadier than any HUD element.
SW, SH = 1920, 151
_FACE_PX = 300 * 140


def _strip(kills=2, hue=HUE, junk=True, face=True):
    a = np.zeros((SH, SW, 3), np.uint8)
    a[:, :] = (70, 55, 40)                              # sandstone
    if face:
        # A person sitting in a chair: skin, always there, never moving. On the
        # footage this comes from it held 2255 steady pixels to the HUD's 871.
        a[5:145, 20:320] = _hud_rgb(22.0, v=205)
    x0 = int(cc.CARDS[0] * SW)
    y0 = int((cc.CARDS[1] - cc.HUD_STRIP[1])
             / (cc.HUD_STRIP[3] - cc.HUD_STRIP[1]) * SH)
    if kills:
        w = cc.CARD_W0 + cc.CARD_PITCH * kills
        a[y0 + 10:y0 + 50, x0 + 10:x0 + 10 + w] = _hud_rgb(hue)
    elif junk:
        # Bright warm scenery in the card area at a width that is not a level,
        # so a wrong colour finds something and still cannot read it.
        a[y0 + 14:y0 + 44, x0 + 30:x0 + 57] = _hud_rgb(22.0, v=230)
    return a


def _look(kills=2, hue=HUE, junk=True, face=True, moving=True):
    """One sample as `measure_hue` takes it: two strips PAIR_GAP apart. The
    game goes on behind the tally between them unless `moving` is False -- a
    menu, a loading screen, a paused stream."""
    a = _strip(kills, hue, junk, face)
    b = a.copy()
    if moving:
        # darker than VAL_MIN either way, so the scenery never reads as a
        # colour in its own right; only the difference matters
        sand = np.all(b == (70, 55, 40), axis=2)
        b[sand] = (76, 60, 44)
    return (a, b)


def _panel(text_edges: bool):
    """The spectator panel patch: full of name/ADR text, or smooth gameplay."""
    a = np.zeros((20, 100, 3), np.uint8)
    a[:, :] = (40, 38, 42)
    if text_edges:
        for x in range(0, 100, 4):
            a[4:16, x:x + 2] = (210, 210, 215)
    return a


# --------------------------------------------------------------- reading one

@pytest.mark.parametrize("kills", [1, 2, 3, 4, 5])
def test_the_measured_widths_read_back_as_the_right_count(kills):
    r = cc.read_frame(_tally(kills), None, HUE)
    assert r.kills == kills, (r.kills, r.width)
    assert r.width == cc.CARD_W0 + cc.CARD_PITCH * kills


def test_no_tally_at_all_is_zero_kills():
    r = cc.read_frame(_bg(), None, HUE)
    assert r.kills == 0 and r.why == ""


def test_warm_sandstone_alone_is_not_a_tally():
    """FROM FOOTAGE: Anubis is orange, and orange is close to the player's
    magenta. Nothing but background must read as kills."""
    for shade in ((150, 110, 70), (200, 150, 100), (120, 90, 60)):
        r = cc.read_frame(_bg(shade), None, HUE)
        assert r.kills == 0, (shade, r.kills, r.width)


def test_a_near_red_surface_is_within_tolerance_and_is_not_pretended_otherwise():
    """An honest limit, recorded rather than hidden.

    Pure red is hue 0, which is 22 degrees from this player's magenta -- inside
    the tolerance the real cards need. Colour alone cannot reject it. What does
    is the shape: a flat surface has no columns of the right height in the
    right places, so it never lands on one of the real width levels.
    """
    flat = _bg((132, 83, 83))
    assert cc.hud_mask(flat, HUE).any(), "colour alone does not reject it"
    assert cc.read_frame(flat, None, HUE).kills != 1, "but the shape does"


def test_a_width_between_two_levels_is_refused_rather_than_rounded():
    """FROM FOOTAGE, and it invented a kill.

    The tally FLASHES as a kill lands -- it scales up for about 0.9s -- and
    mid-flash the width lands between the real levels. A single kill measured
    76px, which is wider than a genuine three. Reading it as "whatever is
    nearest" is how a two-kill round briefly reported three.
    """
    r = cc.read_frame(_tally(2, extra=9), None, HUE)
    assert r.kills is None and r.why == "flash", (r.kills, r.width)


# ------------------------------------------------------------ the HUD colour

def test_the_count_is_the_same_across_the_hues_detection_actually_returns():
    """FROM FOOTAGE: measuring the HUD colour on two recordings gave 333 and
    346, and an earlier version read the same one-card tally as 34px at 338 and
    48px at 348 -- a different count -- because the redder end of the tolerance
    started admitting sandstone. The column-occupancy rule is what fixed it."""
    for hue in (330.0, 338.0, 346.0):
        for kills in (1, 2, 3):
            r = cc.read_frame(_tally(kills, hue=HUE), None, hue)
            assert r.kills == kills, (hue, kills, r.kills, r.width)


def test_the_hud_colour_is_found_by_reading_the_tally_not_by_stillness():
    """FROM FOOTAGE: a user's 18-minute recording produced 5 of 13 kills, 12 of
    them invented, because the colour was taken from whatever held stillest on
    the bottom strip -- and that was his FACECAM. His face beat his HUD 2255
    steady pixels to 871, so the answer came out orange on a purple HUD and
    Anubis sandstone read as cards.

    Stillness cannot be made to rank a face below a health number: by that
    measure the face IS the steadier thing. So the colour is the one the card
    area can actually be READ in."""
    frames = [_look(kills=(i % 3) + 1, hue=300.0) for i in range(12)]
    # The hazard, reproduced: the face is both bigger and steadier than the
    # tally, so anything ranking steady things picks it.
    tally_px = 40 * (cc.CARD_W0 + cc.CARD_PITCH * 3)
    assert _FACE_PX > 10 * tally_px, "the test does not reproduce the hazard"

    got, why = cc.pick_hue(frames)
    assert why == "measured"
    assert abs((got - 300.0 + 180) % 360 - 180) < cc.HUE_TOL, got


def test_a_still_menu_is_not_a_tally_however_steadily_it_reads():
    """FROM FOOTAGE: over every second of the 2h36m recording this reader was
    built on, single looks gave red and orange MORE exact readings than the
    real colour -- from the main menu, where an agent's boots stand still and
    measure as one steady card for minutes. Agreeing with itself a second
    later does not separate that from a tally either. Having moved does: a
    tally holds while the game goes on behind it.

    Here the menu outnumbers the real tally three to one, reads exactly, and
    reads the same twice. Only the real colour ever sees the scene move."""
    menu = [_look(kills=1, hue=30.0, face=False, moving=False)
            for _ in range(18)]
    play = [_look(kills=(i % 3) + 1, hue=300.0) for i in range(6)]
    # the hazard, reproduced: one look apiece, the menu wins outright
    singles = [a for a, _ in menu + play]
    assert cc.pick_hue(singles)[0] is None,         "one look is never evidence for a colour"
    got, why = cc.pick_hue(menu + play)
    assert why == "measured"
    assert abs((got - 300.0 + 180) % 360 - 180) < cc.HUE_TOL, got


def test_a_count_that_changes_between_the_looks_is_not_evidence():
    """Two looks a second apart that disagree are a flash, a round ending, or
    scenery -- not a tally holding."""
    a = _strip(kills=1, hue=300.0)
    b = _strip(kills=3, hue=300.0)
    b[np.all(b == (70, 55, 40), axis=2)] = (76, 60, 44)
    assert cc.score_hue([(a, b)] * 10, 300.0) == (0, 0)


def test_a_colour_nothing_can_be_read_in_is_refused_rather_than_guessed():
    """Returning a colour that cannot read the tally is worse than returning
    none: the scan runs to the end and reports scenery as kills, and nothing
    about the run says so until somebody watches the clips."""
    rng = np.random.default_rng(1)
    frames = [(rng.integers(0, 90, (151, 1920, 3), dtype=np.uint8),
               rng.integers(0, 90, (151, 1920, 3), dtype=np.uint8))
              for _ in range(10)]
    assert cc.pick_hue(frames) == (None, "nothing readable")


def test_the_winning_colour_is_the_centre_of_its_arc_not_the_best_probe():
    """A real HUD colour wins a band of neighbouring probes about as wide as
    HUE_TOL. Which one inside it scores highest is noise, so landing on an edge
    spends tolerance the colour needs for the next recording."""
    rows = [(h * 5.0, 0, 0, 0.0) for h in range(72)]
    for h, exact in ((60.0, 4), (65.0, 9), (70.0, 10), (75.0, 9), (80.0, 4)):
        rows[int(h / 5)] = (h, exact, 1, 0.9)
    # a lone probe elsewhere passes too, and must not drag the answer
    rows[int(200 / 5)] = (200.0, 5, 1, 0.83)
    got = cc.best_hue(rows)
    assert abs(got - 70.0) < 2.0, got


# -------------------------------------------------------------- spectating

def test_the_spectator_panel_is_recognised():
    """FROM FOOTAGE: while dead you watch a team-mate, and the tally then shows
    THEIR kills. Counting it invents kills the player never got."""
    assert cc.spectating(_panel(True))
    assert not cc.spectating(_panel(False))


def test_a_spectated_tally_is_not_read_as_your_own():
    r = cc.read_frame(_tally(4), _panel(True), HUE)
    assert r.kills is None and r.why == "spectating"


# --------------------------------------------------------------- collapsing

def _rs(seq, t0=10.0, step=0.5):
    """seq of kills-or-None -> readings half a second apart."""
    out = []
    for i, k in enumerate(seq):
        why = "spectating" if k == "s" else ("flash" if k is None else "")
        out.append(cc.Reading(time=t0 + i * step,
                              kills=None if k in (None, "s") else k, why=why))
    return out


def test_each_rise_in_the_tally_is_a_kill():
    ev = cc.collapse(_rs([0, 0, 1, 1, 1, 2, 2, 2]))
    kills = [e for e in ev if e.kind == "kill"]
    assert [e.running for e in kills] == [1, 2]


def test_a_jump_of_two_reports_two_kills():
    # Both landed inside one sample. The tally still knows how many.
    ev = cc.collapse(_rs([0, 0, 2, 2, 2]))
    assert [e.running for e in ev if e.kind == "kill"] == [1, 2]


def test_a_count_seen_only_once_is_not_believed():
    """The flash can land on a valid width for a single frame. A real count
    holds for the rest of the round, so it will always say itself twice."""
    ev = cc.collapse(_rs([0, 0, 1, 1, 3, 1, 1, 1]))
    assert [e.running for e in ev if e.kind == "kill"] == [1]


def test_the_tally_falling_is_a_new_round_not_a_kill():
    # One kill, the round ends, one kill in the next round. The fall between
    # them is a reset and must not read as anything.
    ev = cc.collapse(_rs([0, 0, 1, 1, 0, 0, 1, 1]))
    assert [e.running for e in ev if e.kind == "kill"] == [1, 1]


def test_the_hud_being_hidden_mid_round_does_not_invent_kills():
    """FROM THE DESIGN: the scoreboard covers the HUD, so the tally vanishes and
    comes back unchanged. Emitting on the way back would add a kill every time
    the player pressed Tab."""
    seq = [0, 0, 2, 2] + [None] * 12 + [2, 2]   # a six-second blind spot
    got = [e.time for e in cc.collapse(_rs(seq)) if e.kind == "kill"]
    # The two real kills at the start, and nothing at all on the way back.
    assert len(got) == 2 and max(got) < 12.0, got


def test_a_kill_during_a_blind_spot_is_adopted_not_counted():
    # It cannot be known whether the rise happened here or a round ago, so it
    # is taken as the new baseline. Missing one beats inventing one.
    seq = [0, 0, 1, 1] + [None] * 12 + [3, 3]
    got = [e.time for e in cc.collapse(_rs(seq)) if e.kind == "kill"]
    assert len(got) == 1 and max(got) < 12.0, got


def test_going_to_spectate_is_recorded_as_a_death():
    ev = cc.collapse(_rs([0, 1, 1, "s", "s", "s", "s"]))
    deaths = [e for e in ev if e.kind == "death"]
    assert len(deaths) == 1
    # timed to when the panel FIRST appeared, not when it was believed
    assert deaths[0].time == pytest.approx(11.5)


def test_a_flicker_of_the_panel_is_not_a_death():
    """FROM FOOTAGE: undebounced, the panel test reported 73 deaths across a
    match of about 25 rounds. Being dead lasts until the round ends, so a real
    one is never one frame long."""
    ev = cc.collapse(_rs([0, 1, 1, "s", 1, 1, "s", 1, 1, "s", 1, 1]))
    assert [e for e in ev if e.kind == "death"] == []


def test_a_long_spectate_is_still_only_one_death():
    ev = cc.collapse(_rs([0, 1, 1] + ["s"] * 20))
    assert sum(1 for e in ev if e.kind == "death") == 1


def test_a_team_mates_tally_is_never_counted_as_kills():
    """FROM FOOTAGE at 45m09s: dead, watching LunaticYo, whose tally read 1."""
    ev = cc.collapse(_rs([0, 0, 2, 2, "s", "s", "s", "s", "s", "s"]))
    got = [e.time for e in ev if e.kind == "kill"]
    # Two real kills before dying, and nothing at all from what was watched.
    assert len(got) == 2 and max(got) < 12.0, got


def test_tally_counts_both_kinds():
    got = cc.tally([cc.Event(time=1), cc.Event(time=2),
                    cc.Event(time=3, kind="death")])
    assert got == {"kill": 2, "death": 1}


# ------------------------------------------------------------------ wiring

def test_a_cardcount_profile_needs_nothing_typed_in():
    from autostream.clips.profiles import Profile

    p = Profile(key="cs2.exe", label="Counter-Strike 2", band=(0, 0, 1, 1),
                template="", mode="cardcount")
    assert p.missing() == []        # the HUD colour is measured, not asked for
    assert p.exists() and p.why_not() == ""
    assert [r["key"] for r in p.requirements()] == ["hud_hue"]
    assert p.requirements()[0]["auto"] is True


def test_a_killfeed_profile_still_has_to_be_asked_for_the_name():
    from autostream.clips.profiles import Profile

    p = Profile(key="x.exe", label="X", band=(0, 0, 1, 1), template="",
                mode="killfeed")
    assert [r["key"] for r in p.missing()] == ["player"]
    assert not p.exists()
    assert "Clips" in p.why_not()


def test_a_measured_hud_colour_survives_the_yaml_round_trip():
    from autostream.clips.profiles import Profile, _build

    p = Profile(key="cs2.exe", label="CS2", band=(0.4, 0.8, 0.6, 0.95),
                template="", mode="cardcount", hud_hue=343.0)
    back = _build(p.key, p.as_dict())
    assert back is not None and back.mode == "cardcount"
    assert back.hud_hue == pytest.approx(343.0)


def test_the_saved_hud_colour_is_rechecked_against_every_recording(
        monkeypatch, tmp_path):
    """FROM FOOTAGE: the saved colour used to be trusted forever, so the first
    recording ever scanned decided every later one. A user handed the app a
    friend's footage and got clips cut from sandstone -- the saved colour was
    never the friend's, and nothing in the run could notice.

    So the recording is always offered the saved value. Keeping it is cheap;
    the point is that it CAN be overturned."""
    from autostream import paths
    from autostream.clips import cs2_cards, detect, profiles

    monkeypatch.setattr(paths, "CLIP_PROFILES", tmp_path / "profiles.yaml")
    seen = []

    def fake(v, d, **k):
        seen.append(k.get("cached"))
        # stands in for a recording that reads at 341 and nothing else
        return 341.0

    monkeypatch.setattr(cs2_cards, "measure_hue", fake)
    monkeypatch.setattr(cs2_cards, "scan", lambda v, **k: [])
    monkeypatch.setattr(detect, "media_info",
                        lambda p: {"width": 1920, "height": 1080,
                                   "duration": 120.0})
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"")
    prof = profiles.Profile(key="cs2.exe", label="CS2", band=(0, 0, 1, 1),
                            template="", mode="cardcount")
    profiles.save(prof)

    detect.scan(src, profiles.load_all()["cs2.exe"])
    assert seen == [None], "the first scan has nothing saved to offer"
    assert profiles.load_all()["cs2.exe"].hud_hue == pytest.approx(341.0)

    # The second scan hands the saved colour to the recording rather than
    # assuming it. `pick_hue` is what decides whether to keep it.
    detect.scan(src, profiles.load_all()["cs2.exe"])
    assert seen == [None, 341.0]


def test_the_measured_colour_and_box_survive_on_the_profile_cs2_really_has(
        monkeypatch, tmp_path):
    """FROM AN OUTSIDE USER: every run of his measured the colour from scratch,
    and on his 54 minutes the fresh guess was blue for a pink HUD -- no kills.

    The test above saves a `cardcount` profile, which nobody's install has.
    Counter-Strike's built-in is `killfeed`; the tally is a mode the RUN swaps
    in (jobs.py), so remember() reloads the killfeed one and saves through it.
    as_dict() wrote hud_hue and card_box only for cardcount, so both were
    dropped while remember() returned True -- and the card-area check told
    the user "saved"."""
    from autostream import paths
    from autostream.clips import profiles

    monkeypatch.setattr(paths, "CLIP_PROFILES", tmp_path / "profiles.yaml")
    assert profiles.load_all()["cs2.exe"].mode == "killfeed", \
        "the premise: CS2 is killfeed on disk"

    assert profiles.remember("cs2.exe", hud_hue=300.0)
    assert profiles.remember("cs2.exe", card_box=[0.47, 0.878, 0.538, 0.936])

    back = profiles.load_all()["cs2.exe"]
    assert back.hud_hue == pytest.approx(300.0)
    assert back.card_box == pytest.approx((0.47, 0.878, 0.538, 0.936))
    # and saving them did not cost the profile what makes it Counter-Strike
    assert back.mode == "killfeed" and back.demos and back.rounds


def test_a_saved_colour_that_still_reads_is_not_measured_again():
    """Measuring is not free, so a colour the recording agrees with is kept --
    no sweep, no second guess."""
    frames = [_look(kills=2, hue=300.0) for _ in range(10)]
    got, why = cc.pick_hue(frames, cached=300.0)
    assert (got, why) == (300.0, "kept")


def test_a_quiet_recording_does_not_overturn_a_saved_colour():
    """A recording where the tally is almost never up has nothing to say about
    any colour. Silence must not be read as disagreement, or a quiet session
    would throw away a colour measured on a good one."""
    frames = [_look(kills=0, hue=300.0, junk=False) for _ in range(10)]
    got, why = cc.pick_hue(frames, cached=300.0)
    assert (got, why) == (300.0, "kept")


def test_detect_routes_cardcount_to_the_tally_reader(monkeypatch, tmp_path):
    """A wiring guard. Two CS2 bugs -- a deleted helper and a Sighting read as
    a FeedEvent -- passed the whole unit suite because nothing walked the path."""
    from autostream.clips import cs2_cards, detect
    from autostream.clips.profiles import Profile

    called = {}

    def fake_scan(video, **kw):
        called.update(kw)
        return [cs2_cards.Event(time=t, kind=k) for t, k in
                ((10.0, "kill"), (11.0, "kill"), (30.0, "death"),
                 (60.0, "kill"))]

    monkeypatch.setattr(cs2_cards, "scan", fake_scan)
    monkeypatch.setattr(detect, "media_info",
                        lambda p: {"width": 1920, "height": 1080,
                                   "duration": 120.0})
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"")
    prof = Profile(key="cs2.exe", label="CS2", band=(0, 0, 1, 1), template="",
                   mode="cardcount", scan_fps=2.0, hud_hue=343.0)
    kills = detect.scan(src, prof)

    assert called["hue"] == 343.0 and called["frame_height"] == 1080
    # Deaths are not clipped, and the two kills stay TWO Kills for the planner.
    assert [(k.time, k.count) for k in kills] == [(10.0, 1), (11.0, 1),
                                                  (60.0, 1)]


# --------------------------------------------------- is the calibration right

def _sight(kills=None, mask=0, width=0, t=0.0):
    return cc.Sighting(time=t, kills=kills, width=width, mask=mask)


def _checked(monkeypatch, seen):
    monkeypatch.setattr(cc, "sample_tallies", lambda *a, **k: seen)
    return cc.check(Path("x.mp4"), 600.0, 340.0)


def test_a_working_calibration_passes(monkeypatch):
    """Six readable tallies out of ten sightings is what a correct region and
    hue measured on a real 30-minute match."""
    seen = [_sight(kills=k, mask=300, width=18 + 16 * k) for k in (1, 2, 1, 3, 2, 1)]
    seen += [_sight(mask=200, width=40) for _ in range(4)]
    got = _checked(monkeypatch, seen)
    assert got.ok is True
    assert got.read == 6 and got.present == 10


def test_the_wrong_hue_finds_nothing_and_says_so(monkeypatch):
    """Measured: a wrong hue put HUD colour in the card area zero times."""
    got = _checked(monkeypatch, [_sight() for _ in range(24)])
    assert got.ok is False
    assert "colour" in got.why


def test_a_region_off_the_tally_is_caught(monkeypatch):
    """The failure that matters. A region near the tally still catches HUD
    colour -- the health number, the ammo counter -- so "something is there"
    proves nothing. Only a width on a real card level does."""
    seen = [_sight(mask=250, width=41) for _ in range(8)]
    got = _checked(monkeypatch, seen)
    assert got.ok is False
    assert got.present == 8 and got.read == 0


def test_one_lucky_reading_is_not_enough(monkeypatch):
    """A width lands within tolerance of one of five levels about a quarter of
    the time by chance, so a single hit must not pass."""
    seen = [_sight(kills=2, mask=300, width=50)] + [_sight(mask=250, width=41)
                                                    for _ in range(9)]
    got = _checked(monkeypatch, seen)
    assert got.ok is False


def test_the_check_never_raises(monkeypatch):
    def boom(*a, **k):
        raise OSError("no such file")
    monkeypatch.setattr(cc, "sample_tallies", boom)
    got = cc.check(Path("x.mp4"), 600.0, 340.0)
    assert got.ok is False and "could not read" in got.why


def test_the_sample_puts_the_fullest_tally_first():
    """The frames shown to a person should be the ones worth looking at: a
    three-card tally proves the region, an empty one proves nothing."""
    rows = [_sight(kills=1, mask=100, t=1.0), _sight(mask=10, t=2.0),
            _sight(kills=3, mask=300, t=3.0), _sight(kills=2, mask=200, t=4.0)]
    rows.sort(key=lambda s: (s.kills or 0, s.mask), reverse=True)
    assert [r.time for r in rows] == [3.0, 4.0, 1.0, 2.0]


# ------------------------------------------------------------- the flash
#
# Synthetic sweeps, at the numbers measured on two demo-scored matches: a kill
# is a beam of 1050-1750 px held 0.6-1.1s with the emblem whitening by 440+,
# over the player's OWN emblem; a team-mate's kill while spectating is the
# same flash over somebody else's.

FPS = 10.0
_rng = np.random.default_rng(7)
OWN = _rng.standard_normal(cc.EMBLEM_GRID ** 2).astype(np.float32)
MATE = _rng.standard_normal(cc.EMBLEM_GRID ** 2).astype(np.float32)
MENU = _rng.standard_normal(cc.EMBLEM_GRID ** 2).astype(np.float32)
GEO = cc.Geometry(crop=(0, 0, 364, 140), k=1.0)


def _norm(v):
    return (v - v.mean()) / v.std()


class _Sweep:
    """Builds a Sweep, second by second."""

    def __init__(self, seconds=60.0, width=0):
        n = int(seconds * FPS)
        self.t = np.arange(n) / FPS
        self.beam = np.zeros(n, int)
        self.wb = np.zeros(n, int)
        self.ew = np.full(n, 20, int)
        self.w = np.full(n, width, int)
        self.dark = np.zeros(n, bool)
        self.emblem = [OWN] * n
        self.panel = np.full(n, 0.1)
        self.energy = np.full(n, 10.0)

    def i(self, t):
        return int(round(t * FPS))

    def flash(self, at, length=0.85, beam=1300, rise=900, cards=None):
        a, b = self.i(at), self.i(at + length)
        self.beam[a:b] = beam
        self.ew[a:a + int(0.6 * FPS)] += rise  # measured: faded in 0.6s
        self.w[a:b] = 90                     # mid-flash the width is nonsense
        if cards is not None:
            self.w[b:] = 0 if cards == 0 else cc.CARD_W0 + cc.CARD_PITCH * cards
        return self

    def cards(self, at, n):
        self.w[self.i(at):] = 0 if n == 0 else cc.CARD_W0 + cc.CARD_PITCH * n
        return self

    def die(self, at, cam=2.0):
        """The death cam has no HUD at all, then the view is a team-mate's."""
        self.energy[self.i(at):self.i(at + cam)] = 0.0
        return self.spectate(at + cam, at + cam + 20.0)

    def spectate(self, a, b):
        for j in range(self.i(a), self.i(b)):
            self.emblem[j] = MATE
            self.panel[j] = 0.8
        return self

    def build(self):
        every = int(FPS / cc.EMBLEM_FPS)
        idx = np.arange(0, len(self.t), every)
        return cc.Sweep(fps=FPS, t=self.t, beam=self.beam, white_beam=self.wb,
                        emblem_white=self.ew, width=self.w, dark=self.dark,
                        et=self.t[idx],
                        emaps=np.stack([_norm(self.emblem[j]) for j in idx]),
                        energy=self.energy[idx], panel=self.panel[idx])


def _read(sw):
    fl = cc.flashes(sw, GEO)
    own = cc.judge(fl, sw, cc.own_emblems(sw))
    kills = [f.time for f in fl for _ in range(f.kills)]
    return kills, fl, own


def test_a_flash_over_your_own_emblem_is_a_kill_at_its_onset():
    sw = _Sweep().flash(20.0, cards=1).build()
    kills, _, _ = _read(sw)
    assert kills == [pytest.approx(20.0)]


def test_a_kill_and_a_death_a_second_later_is_still_a_kill():
    """FROM FOOTAGE, and the reason for this reader. The width reader needed
    the new count to hold for two samples; dying a second after the kill
    never gave it that, and six of Dust2's thirty kills went missing."""
    sw = _Sweep().cards(10.0, 1).flash(20.0, cards=2).spectate(21.0, 40.0).build()
    kills, _, _ = _read(sw)
    assert kills == [pytest.approx(20.0)]


def test_a_team_mates_kill_while_you_are_dead_is_not_yours():
    """FROM FOOTAGE: 30 of these in two matches -- the same flash and the
    same beam, over the watched player's avatar instead of your own emblem."""
    sw = (_Sweep().spectate(15.0, 45.0).flash(20.0, cards=1)
          .flash(30.0, cards=2).build())
    kills, _, _ = _read(sw)
    assert kills == []


def test_a_blip_of_hud_colour_is_not_a_flash():
    """FROM FOOTAGE: HUD-coloured blips above the fan held 0.4s at most,
    and none whitened the emblem as a kill does."""
    sw = (_Sweep().flash(10.0, length=0.2, rise=420)
          .flash(20.0, length=0.9, rise=40).build())
    kills, _, _ = _read(sw)
    assert kills == []


def test_two_kills_inside_one_flash_are_two_kills():
    """FROM FOOTAGE at 1h26m42s: two kills 0.1s apart, one flash. The fan
    settles two cards wider, and says so."""
    sw = _Sweep().flash(20.0, cards=2).build()
    kills, _, _ = _read(sw)
    assert kills == [pytest.approx(20.0)] * 2


def test_back_to_back_kills_each_count_once():
    """Kills 1.2s apart: the second flash starts before the first has
    settled, so the count after the first must not swallow the second."""
    sw = _Sweep().flash(20.0).flash(21.2, cards=2).build()
    kills, _, _ = _read(sw)
    assert kills == [pytest.approx(20.0), pytest.approx(21.2)]


def test_a_kill_under_a_flashbang_is_recovered_from_the_count():
    """FROM FOOTAGE at 2h27m26s: the screen whited out as the kill landed,
    so no beam was ever visible -- but the fan came back one card wider."""
    s = _Sweep().flash(10.0, cards=1)
    s.w[s.i(20.0):] = 0                       # the next round
    a, b = s.i(30.0), s.i(32.0)
    s.wb[a:b] = 3900                          # white
    s.w[b:] = cc.CARD_W0 + cc.CARD_PITCH * 1
    sw = s.build()
    kills, _, own = _read(sw)
    assert cc.hidden_kills(sw, GEO, own, kills) == [pytest.approx(30.0)]


def test_a_tally_misread_low_and_recovering_is_not_a_kill():
    """FROM FOOTAGE, first round of an 18-minute recording: a steady two-card
    tally over bright Anubis sandstone loses the last card's columns to
    MIN_COL and reads as a ONE for a second or more, then recovers. Measured
    against the previous reading that recovery is a rise with no flash to
    explain it -- a hidden kill -- and the round reported four kills where
    there were two.

    The count never falls inside a round, so a reading below what the round
    has already shown is a misread, and climbing back out of one is not a
    kill."""
    s = _Sweep().flash(10.0, cards=2)
    one = cc.CARD_W0 + cc.CARD_PITCH * 1
    for a, b in ((14.0, 15.6), (21.0, 22.4), (28.0, 29.5)):
        s.w[s.i(a):s.i(b)] = one              # washed out...
    sw = s.build()                            # ...and back at two
    kills, _, own = _read(sw)
    assert cc.hidden_kills(sw, GEO, own, kills) == []


def test_a_real_rise_past_the_rounds_high_water_mark_still_counts():
    """The guard above must not cost the kill it exists to find: a dip and
    recovery is nothing, but going one card PAST what the round has shown is
    still a kill whose flash was missed."""
    s = _Sweep().flash(10.0, cards=2)
    s.w[s.i(14.0):s.i(15.6)] = cc.CARD_W0 + cc.CARD_PITCH * 1   # a misread
    a, b = s.i(30.0), s.i(32.0)
    s.wb[a:b] = 3900                                            # a flashbang
    s.w[b:] = cc.CARD_W0 + cc.CARD_PITCH * 3                    # a third kill
    sw = s.build()
    kills, _, own = _read(sw)
    assert cc.hidden_kills(sw, GEO, own, kills) == [pytest.approx(30.0)]


def test_the_scoreboard_hiding_the_fan_does_not_invent_kills():
    s = _Sweep().flash(10.0, cards=2)
    s.w[s.i(20.0):s.i(24.0)] = 0              # Tab: the tally is gone...
    s.dark[s.i(20.0):s.i(24.0)] = True
    sw = s.build()                            # ...and back unchanged
    kills, _, own = _read(sw)
    assert cc.hidden_kills(sw, GEO, own, kills) == []


def test_an_emblem_that_never_flashed_is_not_trusted():
    """FROM FOOTAGE: a menu is common in a session and carries no spectator
    panel, so it looks like an own emblem -- and it read two kills out of
    thin air -- until you notice that it never once flashed."""
    s = _Sweep(seconds=120.0).flash(10.0, cards=1)
    for j in range(s.i(60.0), s.i(120.0)):
        s.emblem[j] = MENU
    s.w[s.i(60.0):s.i(80.0)] = 0
    s.w[s.i(80.0):] = cc.CARD_W0 + cc.CARD_PITCH * 2
    sw = s.build()
    kills, _, own = _read(sw)
    assert len(cc.own_emblems(sw)) == 2, "both look like candidates"
    assert len(own) == 1, "only the one that flashed is kept"
    assert cc.hidden_kills(sw, GEO, own, kills) == []


def test_a_death_is_when_your_emblem_goes():
    """FROM FOOTAGE: at every one of 34 demo deaths the emblem was gone
    inside half a second -- the death cam draws no HUD -- and a team-mate's
    view followed. 27 of 34 found, against 1 by the spectator panel alone."""
    sw = _Sweep().flash(10.0, cards=1).die(25.0).build()
    _, _, own = _read(sw)
    assert cc.deaths(sw, own) == [pytest.approx(25.0)]


def test_a_flashbang_is_not_a_death():
    """The emblem goes under a flashbang too -- and comes back as yours."""
    s = _Sweep().flash(10.0, cards=1)
    s.energy[s.i(25.0):s.i(27.0)] = 0.0
    sw = s.build()
    _, _, own = _read(sw)
    assert cc.deaths(sw, own) == []


def test_a_borderline_flash_is_doubtful_not_decided():
    sw = _Sweep().flash(20.0, length=0.4, rise=900).build()
    _, fl, _ = _read(sw)
    assert [f.kills for f in fl] == [0]
    assert fl[0].doubt


def test_the_view_is_where_it_was_measured():
    """At 1080p the reader's view is exactly the crop its thresholds were
    measured in; anywhere else it scales with the frame and the band."""
    g = cc.geometry((1920, 1080))
    assert g.crop == (748, 918, 364, 140) and g.k == pytest.approx(1.0)
    g2 = cc.geometry((2560, 1440))
    assert g2.k == pytest.approx(1440 / 1080)
    assert abs(g2.crop[2] - 364 * g2.k) <= 2


def test_an_emblem_is_recognised_whatever_is_behind_it():
    """The emblem is translucent, so its fill is whatever the scenery is.
    Its outlines are not -- which is why it is compared by edges."""
    rng = np.random.default_rng(3)
    icon = np.zeros((52, 52, 3), np.uint8)
    icon[10:42, 24:28] = 200
    icon[24:28, 10:42] = 200
    over_sand = np.clip(icon.astype(int) + (40, 30, 20), 0, 255).astype(np.uint8)
    over_dark = np.clip(icon.astype(int) + (5, 8, 10), 0, 255).astype(np.uint8)
    other = rng.integers(0, 255, (52, 52, 3)).astype(np.uint8)
    a, _ = cc.emblem_map(over_sand)
    b, _ = cc.emblem_map(over_dark)
    c, _ = cc.emblem_map(other)
    d = len(a)
    assert float(a @ b) / d >= cc.EMBLEM_OWN
    assert float(a @ c) / d < cc.EMBLEM_OWN


def test_samples_carry_the_time_of_the_frame_actually_read(monkeypatch):
    """Samples are read off the keyframe at or before each point, which can
    be seconds earlier. The page shows the frame at the time it is handed, so
    that has to be the keyframe's, or the picture holds a different tally."""
    import numpy as np
    from autostream.clips import cs2_cards as cc

    asked = []

    def frame(video, at, band, size):
        asked.append(at)
        return np.zeros((4, 4, 3), np.uint8), at - 1.5

    monkeypatch.setattr(cc, "_one_frame", frame)
    seen = cc.sample_tallies("x.mp4", 420.0, 200.0, tries=10, want=0, size=(1920, 1080))
    assert len(seen) == 10 and len(asked) == 10
    assert sorted(s.time for s in seen) == sorted(a - 1.5 for a in asked)


# ---------------------------------------------------- a HUD it could not see

def _blind_scan(monkeypatch, seconds):
    """cs2_cards.scan over `seconds` of footage in which nothing is the
    player's own: no emblem confirmed by any flash."""
    from autostream.clips import killfeed, tools

    monkeypatch.setattr(tools, "media_info",
                        lambda p: {"width": 1920, "height": 1080,
                                   "duration": seconds})
    monkeypatch.setattr(killfeed, "_sweep_stale_temp", lambda: None)
    empty = np.zeros(0)
    monkeypatch.setattr(cc, "sweep", lambda *a, **k: cc.Sweep(
        fps=10.0, t=empty, beam=empty, white_beam=empty, emblem_white=empty,
        width=empty, dark=empty.astype(bool)))
    monkeypatch.setattr(cc, "flashes", lambda sw, geo: [])
    monkeypatch.setattr(cc, "own_emblems", lambda sw: np.zeros((0, 4)))
    monkeypatch.setattr(cc, "judge", lambda fl, sw, own, a=1.0: own[:0])
    return lambda: cc.scan(Path("rec.mp4"), hue=202.0, frame_height=1080)


def test_a_long_recording_with_no_kill_flash_is_unread_not_empty(monkeypatch):
    """FROM AN OUTSIDE USER: 54 minutes, 0 own emblems, 5 flashes in the
    wrong colour -- and the run said "No kills found", which sent him looking
    at his game instead of at his HUD. A whole match without one kill flash
    over your own badge is the reader not seeing, and it has to say so."""
    run = _blind_scan(monkeypatch, 54 * 60.0)
    with pytest.raises(cc.HudUnread) as e:
        run()
    msg = str(e.value)
    assert "not the same as having no kills" in msg
    assert "202" in msg, "the colour it read in is the first clue"
    assert "Set the colour by hand" not in msg, "there is no such control"


def test_a_short_quiet_clip_can_still_honestly_have_no_kills(monkeypatch):
    run = _blind_scan(monkeypatch, cc.HUD_UNREAD_AFTER - 60.0)
    assert run() == []


def test_a_colour_the_scan_could_not_read_is_forgotten_not_kept(
        monkeypatch, tmp_path):
    """The colour used to be saved the moment it was measured, before the
    scan had read a single kill in it -- and a saved colour is offered to
    every later recording, which keeps it unless it can object. One that
    just read nothing in a whole match is dropped instead."""
    from autostream import paths
    from autostream.clips import cs2_cards, detect, profiles

    monkeypatch.setattr(paths, "CLIP_PROFILES", tmp_path / "profiles.yaml")
    profiles.remember("cs2.exe", hud_hue=202.0)
    monkeypatch.setattr(cs2_cards, "measure_hue", lambda v, d, **k: 202.0)

    def blind(v, **k):
        raise cs2_cards.HudUnread("could not see it")

    monkeypatch.setattr(cs2_cards, "scan", blind)
    monkeypatch.setattr(detect, "media_info",
                        lambda p: {"width": 1920, "height": 1080,
                                   "duration": 3000.0})
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"")
    import dataclasses
    prof = dataclasses.replace(profiles.load_all()["cs2.exe"],
                               mode="cardcount", rounds=False, demos=False)
    with pytest.raises(cs2_cards.HudUnread):
        detect.scan(src, prof)
    assert profiles.load_all()["cs2.exe"].hud_hue == 0.0


def _spectated(look):
    """Put the spectator panel -- a team-mate's name and ADR, all vertical
    text edges -- into both strips of a look."""
    out = []
    for f in look:
        f = f.copy()
        x0 = int(cc.PANEL[0] * SW)
        x1 = int(cc.PANEL[2] * SW)
        y0 = int((cc.PANEL[1] - cc.HUD_STRIP[1])
                 / (cc.HUD_STRIP[3] - cc.HUD_STRIP[1]) * SH)
        y1 = int((cc.PANEL[3] - cc.HUD_STRIP[1])
                 / (cc.HUD_STRIP[3] - cc.HUD_STRIP[1]) * SH)
        f[y0:y1, x0:x1] = (40, 38, 42)
        for x in range(x0, x1, 4):
            f[y0 + 1:y1 - 1, x:x + 2] = (210, 210, 215)
        out.append(f)
    return tuple(out)


def test_a_team_mates_tally_while_spectating_does_not_choose_the_colour():
    """FROM AN OUTSIDE USER: 21 deaths in a match spent watching a team-mate
    who finished on 29, and while you watch, the fan is THEIRS -- in their
    colour. A real tally, steady, over a moving game: it put yellow ahead of
    his pale pink in half the alignments tried. The spectator panel says
    whose it is."""
    watched = [_spectated(_look(kills=3, hue=60.0)) for _ in range(12)]
    own = [_look(kills=(i % 2) + 1, hue=300.0) for i in range(5)]
    got, why = cc.pick_hue(watched + own)
    assert why == "measured"
    assert abs((got - 300.0 + 180) % 360 - 180) < cc.HUE_TOL, got


def test_a_close_call_is_not_an_answer():
    """Three readings to a rival's two is what a few dozen samples of a pale
    HUD looks like, and taking it handed an outside user's run the wrong
    colour. Not beating everything far away twice over means look harder."""
    a = [_look(kills=1, hue=300.0) for _ in range(3)]
    b = [_look(kills=1, hue=120.0, face=False) for _ in range(2)]
    assert cc.pick_hue(a + b) == (None, "undecided")
    assert cc.pick_hue(a + a + b)[1] == "measured"
