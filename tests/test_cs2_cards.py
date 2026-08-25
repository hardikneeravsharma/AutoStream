"""CS2 round kill tally, read from the cards under the crosshair.

The frames are synthetic, drawn in the geometry MEASURED off real footage: at
1080p a tally of N kills is exactly `18 + 16 * N` pixels wide, and every sample
of a given count measured the identical width. Pinning that here means a later
tweak that still happens to work on one recording, but has drifted from the
real geometry, fails in the suite rather than in the field.

Cases marked FROM FOOTAGE reproduce a specific measurement or a specific bug.
"""
from __future__ import annotations

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


def test_hud_hue_is_measured_from_what_holds_still():
    # HUD pixels are drawn in the same place every frame; scenery is not.
    rng = np.random.default_rng(0)
    frames = []
    for _ in range(8):
        f = rng.integers(0, 255, (40, 200, 3), dtype=np.uint8)   # noisy scene
        f[10:30, 20:180] = _hud_rgb(300.0)                       # steady HUD
        frames.append(f)
    got = cc.hud_hue(frames)
    assert got is not None
    assert abs((got - 300.0 + 180) % 360 - 180) < 20, got


def test_hud_hue_gives_up_rather_than_guess():
    rng = np.random.default_rng(1)
    frames = [rng.integers(0, 255, (40, 200, 3), dtype=np.uint8) for _ in range(8)]
    assert cc.hud_hue(frames) is None


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


def test_a_measured_hud_colour_is_cached_so_only_the_first_scan_pays(
        monkeypatch, tmp_path):
    """The requirements system says a value that can be measured is never
    asked for. Measuring is not free, so the answer has to be kept."""
    from autostream import paths
    from autostream.clips import cs2_cards, detect, profiles

    monkeypatch.setattr(paths, "CLIP_PROFILES", tmp_path / "profiles.yaml")
    calls = []
    monkeypatch.setattr(cs2_cards, "measure_hue",
                        lambda v, d, **k: calls.append(1) or 341.0)
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
    assert len(calls) == 1
    assert profiles.load_all()["cs2.exe"].hud_hue == pytest.approx(341.0)

    # second run: the cached value is used and nothing is measured again
    detect.scan(src, profiles.load_all()["cs2.exe"])
    assert len(calls) == 1, "the HUD colour was measured twice"


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
