"""Valorant feed-bar detector.

The frames here are synthetic, drawn in the colours MEASURED off real footage
(see valorant_feed's module docstring). That is deliberate: it pins the
thresholds to the numbers they were chosen from, so a later tweak that happens
to still work on one recording but has drifted away from the real colours fails
here instead of silently in the field.

Every constant these tests assert against came from frames that were also
checked by eye, and the cases marked FROM FOOTAGE reproduce a specific
measurement or a specific bug.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from autostream.clips import valorant_feed as vf

# The measured bar colours. Deliberately the real ones, not round numbers.
RED = (208, 106, 92)
GREEN = (118, 186, 160)
YELLOW = (220, 210, 125)
BG = (70, 72, 78)

BAND_W, BAND_H = 960, 178
RIGHT = 940              # where every real row ends, measured 939-947


def _band() -> np.ndarray:
    a = np.zeros((BAND_H, BAND_W, 3), np.uint8)
    a[:, :] = BG
    return a


def _draw(a, y0, x0, *, killer=RED, victim=GREEN, split=None,
          yellow_left=False, yellow_right=False, aside_at=None, h=34):
    """Draw one feed row the way the game does.

    killer's colour, then the victim's, right-aligned to RIGHT, with an
    optional yellow border on whichever end is the local player's.
    """
    x1 = RIGHT
    split = split if split is not None else (x0 + x1) // 2
    a[y0:y0 + h, x0:split] = killer
    a[y0:y0 + h, split:x1] = victim
    if yellow_left:
        a[y0:y0 + h, x0:x0 + 26] = YELLOW
    if yellow_right:
        a[y0:y0 + h, x1 - 26:x1] = YELLOW
    if aside_at is not None:
        # A detached assist tile: the player's portrait, well clear of the bar.
        a[y0:y0 + h, aside_at:aside_at + 26] = YELLOW
    return a


# ------------------------------------------------------------------- colour

def test_the_measured_colours_land_in_the_masks_they_were_measured_for():
    a = np.array([[RED, GREEN, YELLOW, BG]], np.uint8)
    red, green, yellow = vf.masks(a)
    assert list(red[0]) == [True, False, False, False]
    assert list(green[0]) == [False, True, False, False]
    assert list(yellow[0]) == [False, False, True, False]


def test_sky_blue_is_not_read_as_the_ally_colour():
    """FROM FOOTAGE: the agent-select screen is a wall of sky blue.

    G - R alone calls it green -- it is +80, more than the ally teal's +68 --
    so the whole screen read as one enormous ally segment and produced five
    bogus rows per frame. What separates them is that the ally colour is a
    TEAL, B below G, while sky blue has B above G.
    """
    sky = (90, 170, 230)
    red, green, yellow = vf.masks(np.array([[sky, GREEN]], np.uint8))
    assert not green[0][0], "sky blue must not be the ally colour"
    assert green[0][1], "the measured teal must still be"


def test_warm_brick_is_not_read_as_the_enemy_colour_on_its_own():
    """FROM FOOTAGE: a tan brick wall produced five bogus death rows.

    Brick does pass the red test -- that is why the two-tone rule exists rather
    than a cleverer red -- so what this pins is that it carries no green, which
    is what the row test then rejects it on.
    """
    brick = (182, 142, 104)
    red, green, _ = vf.masks(np.array([[brick]], np.uint8))
    assert red[0][0]
    assert not green[0][0]


# --------------------------------------------------------------- one row

def test_yellow_at_the_left_of_the_row_is_a_kill():
    a = _draw(_band(), 20, 560, killer=GREEN, victim=RED, yellow_left=True)
    got = vf.read_frame(a)
    assert [r.kind for r in got] == ["kill"]


def test_yellow_at_the_right_of_the_row_is_a_death():
    a = _draw(_band(), 20, 560, killer=RED, victim=GREEN, yellow_right=True)
    got = vf.read_frame(a)
    assert [r.kind for r in got] == ["death"]


def test_a_row_with_no_yellow_is_somebody_elses():
    a = _draw(_band(), 20, 560, killer=RED, victim=GREEN)
    assert [r.kind for r in vf.read_frame(a)] == ["other"]


def test_a_detached_yellow_tile_is_an_assist_not_a_kill():
    """FROM FOOTAGE, and the bug CS2's profile notes still apologise for.

    An assist puts the player's portrait on somebody else's row, as a separate
    tile to the left of the bar. Measured: on a kill the yellow overlaps the
    name segment; on an assist it sits 130px clear of it. By distance from the
    row's left edge the two are only 14px apart, so adjacency is what decides.
    """
    a = _band()
    _draw(a, 20, 586, killer=GREEN, victim=RED, aside_at=430)
    got = vf.read_frame(a)
    assert [r.kind for r in got] == ["assist"], [
        (r.kind, r.left, r.right, r.aside) for r in got]


def test_a_speck_of_yellow_off_to_the_side_is_not_an_assist():
    """Pins ASIDE_FLOOR. Detached yellow needs more evidence than yellow at
    the ends does: at an end it is a border of known shape, out here anything
    warm will do. Measured: real assist tiles 187-473, and the wash on rows
    that were not the player's, 52-74."""
    a = _draw(_band(), 20, 586, killer=RED, victim=GREEN)
    a[30:33, 430:450] = YELLOW          # 60px of yellow, well under the floor
    assert [r.kind for r in vf.read_frame(a)] == ["other"]


def test_the_assist_tile_would_be_a_kill_if_it_touched_the_bar():
    # The same tile, moved up against the segment: now it IS the player's own
    # portrait, so the same pixels mean a kill. Pins that adjacency is doing
    # the work rather than the tile's size or colour.
    a = _draw(_band(), 20, 586, killer=GREEN, victim=RED, yellow_left=True)
    assert [r.kind for r in vf.read_frame(a)] == ["kill"]


def test_the_players_name_at_both_ends_is_a_self_kill_and_counts_as_a_death():
    """FROM FOOTAGE at 22m19s: "YuvaNeta [ability] YuvaNeta".

    Killing yourself with your own ability puts you on both ends of the row and
    lights both borders. Letting the two yellow masses race decided it on a
    16-pixel margin -- two frames said death, five said kill, and the kill won,
    so a clip would have been cut celebrating the player killing themselves.
    """
    a = _draw(_band(), 20, 560, killer=GREEN, victim=GREEN,
              yellow_left=True, yellow_right=True)
    # Both halves are the player's own team colour, so the row would fail the
    # two-tone rule on its flat colours alone. The real one carries 16% red
    # from the portraits at each end, which is what lets it through.
    a[20:54, 860:912] = RED
    got = vf.read_frame(a)
    assert [r.kind for r in got] == ["death"], [
        (r.kind, r.left, r.right) for r in got]


# ------------------------------------------------------- rejecting scenery

def test_a_single_colour_block_is_not_a_row():
    """A row is two-tone. One colour is scenery, however solid it looks.

    FROM FOOTAGE: warm brick read as red and sky blue as green, and either
    colour alone found hundreds of rows -- an unfiltered pass over the
    recording returned 347 kills and 497 deaths in 46 minutes.
    """
    for colour in (RED, GREEN, YELLOW):
        a = _band()
        a[20:54, 400:RIGHT] = colour
        assert vf.read_frame(a) == [], f"{colour} alone must not be a row"


def test_a_row_needs_BOTH_tones_in_quantity_not_just_a_trace_of_one():
    """Pins MIN_TONE: a red bar with a sliver of green on the end is scenery."""
    a = _band()
    a[20:54, 400:RIGHT - 10] = RED
    a[20:54, RIGHT - 10:RIGHT] = GREEN
    assert vf.read_frame(a) == []
    red, green, _ = vf.masks(a)
    assert not vf._two_tone(red, green, slice(20, 54), 400, RIGHT)
    assert vf._two_tone(*vf.masks(_draw(_band(), 20, 400))[:2],
                        slice(20, 54), 400, RIGHT)


def test_a_row_lopsided_far_beyond_any_real_one_is_rejected():
    """Pins MIN_PAIR, which MIN_TONE alone does not reach.

    Both tones are over the MIN_TONE floor here, so only the RATIO rejects it:
    0.14, against 0.29-0.96 measured across every real row. The window is
    narrow by construction -- to clear a 0.10 floor and still fall under a 0.15
    ratio the smaller tone has to sit between 0.10 and 0.13 of the row.
    """
    a = _band()
    x0 = 400
    span = RIGHT - x0
    cut = x0 + int(span * 0.12)
    a[20:54, x0:cut] = GREEN
    a[20:54, cut:RIGHT] = RED
    red, green, _ = vf.masks(a)
    nr = red[20:54, x0:RIGHT].sum() / (34 * span)
    ng = green[20:54, x0:RIGHT].sum() / (34 * span)
    assert nr > vf.MIN_TONE and ng > vf.MIN_TONE, (nr, ng)   # MIN_TONE passes
    assert not vf._two_tone(red, green, slice(20, 54), x0, RIGHT)


def test_a_bar_that_misses_the_right_margin_is_not_a_row():
    """FROM FOOTAGE: the "X KILLED Y" banner is anchored at the LEFT.

    Every real row ends at the same margin, so this one test excludes both that
    banner and the network overlay without knowing where either is drawn.

    Drawn deliberately WIDE enough to fill the density window, so that what
    rejects it really is the right margin. An earlier version of this test put
    the bar at x 40-520, where the density window is empty -- so it passed with
    RIGHT_MIN set to zero, testing nothing it claimed to.
    """
    a = _band()
    stop = int(BAND_W * 0.94)          # just short of RIGHT_MIN
    a[20:54, 400:700] = RED
    a[20:54, 700:stop] = GREEN
    assert vf.read_frame(a) == []
    # ... and the same bar reaching the margin IS a row, so the only difference
    # between the two cases is the thing being tested.
    a[20:54, stop:RIGHT] = GREEN
    assert len(vf.read_frame(a)) == 1


def test_a_row_whose_solid_run_is_too_short_to_hold_a_name_is_not_a_row():
    """Pins MIN_ROW_W, and it takes some construction to reach it.

    A bar wide enough to fill the density window is already wider than the
    limit, so what the limit actually guards is a row whose longest SOLID run
    is tiny -- speckle that got through the colour tests, with one short
    two-tone block at the margin. Everything here exists to get past the other
    checks so that only this one is left to do the rejecting.
    """
    a = _band()
    for x in range(660, 872, 12):               # 6 on, 6 off: runs below MIN_SEG
        a[20:54, x:x + 6] = RED if (x // 12) % 2 else GREEN
    a[20:54, 880:910] = RED                     # one short two-tone block...
    a[20:54, 910:RIGHT] = GREEN                 # ...at the right margin
    assert vf.read_frame(a) == []


def test_a_faint_scattering_of_colour_is_not_a_row():
    """Pins DENSE_MIN. Coverage inside a real row measured 0.66-1.00 and 0.14-
    0.28 in the gap between two, so the floor sits in a gap 0.38 wide."""
    a = _band()
    for x in range(600, RIGHT, 20):             # ~10% coverage
        a[20:54, x:x + 2] = RED
        a[20:54, x + 2:x + 4] = GREEN
    assert vf.read_frame(a) == []


def test_a_dark_desaturated_colour_is_not_a_team_colour():
    """Pins SAT_MIN. The bars are drawn at full opacity and are vivid; scenery
    that merely leans green must not read as an ally."""
    murk = (50, 82, 70)                         # saturation 32, G-R 32
    red, green, _ = vf.masks(np.array([[murk, GREEN]], np.uint8))
    assert not green[0][0], "murky scenery must not be the ally colour"
    assert green[0][1]


def test_a_vivid_but_hue_neutral_colour_is_not_a_team_colour():
    """Pins TEAM_MIN, which SAT_MIN does not reach.

    Khaki is saturated enough to clear SAT_MIN comfortably, so what has to
    reject it is the size of the gap between its channels: 10, against the
    ally teal's 68 and the enemy red's 102.
    """
    khaki = (150, 160, 100)                     # saturation 60, G-R only 10
    red, green, _ = vf.masks(np.array([[khaki]], np.uint8))
    assert not green[0][0] and not red[0][0], "khaki is neither team"


def test_short_column_runs_do_not_add_up_to_a_name_segment():
    """Pins MIN_SEG. Scenery that survives the colour tests arrives as
    speckle; a name segment is a solid block, so runs shorter than a glyph
    must not be treated as one however many of them there are."""
    a = _band()
    for x in range(600, RIGHT, 8):              # 4px on, 4px off
        a[20:54, x:x + 2] = RED
        a[20:54, x + 2:x + 4] = GREEN
    assert vf.read_frame(a) == []


def test_the_gap_between_two_rows_is_not_itself_a_row():
    """Pins DENSE_MIN, using the gaps the real footage actually has.

    Coverage measured 0.66-1.00 inside a row and 0.14-0.28 in the gap between
    two -- the gaps are not empty, because of the bars' shadows and
    antialiasing. Synthetic gaps of clean background test nothing, since no
    threshold turns zero into a row.
    """
    a = _band()
    for i, y in enumerate((20, 59, 98)):
        _draw(a, y, 560 + i * 10)
    for y in (54, 55, 56, 57, 93, 94, 95, 96):  # ~0.2 coverage, as measured
        for x in range(560, RIGHT, 5):
            a[y, x] = RED
    got = vf.read_frame(a)
    assert _tops(got) == [20, 59, 98], [(r.y0, r.y1, r.kind) for r in got]


def test_a_bar_running_off_the_edge_of_the_band_is_not_a_settled_row():
    """FROM FOOTAGE: rows slide in, and their geometry is nonsense while they do.

    Mid-animation frames measured x0 at 234 instead of 630, heights of 29 and
    43 against a settled 34, and yellow masses of 1304 and 3470 against a
    settled 856 -- and three of the false kills in the first audit were exactly
    these frames read as if they were rows. A settled row always has
    background to its right; one flush with the edge has not landed yet.
    """
    a = _band()
    a[20:54, 400:700] = RED
    a[20:54, 700:BAND_W] = GREEN          # runs clean off the side
    assert vf.read_frame(a) == []


def test_a_bar_far_wider_than_any_real_row_is_rejected():
    """Real rows measured 202-529px across every verdict; this is 740."""
    a = _draw(_band(), 20, 200)
    assert vf.read_frame(a) == []


# ------------------------------------------------------------ stacked rows

def _tops(found):
    return [r.y0 for r in found]


def test_three_rows_are_found_separately():
    a = _band()
    for i, y in enumerate((20, 59, 98)):
        _draw(a, y, 560 + i * 10)
    got = vf.read_frame(a)
    # WHERE, not just how many: a loosened density floor or join tolerance
    # merges the rows and the pitch split then hands back the right COUNT with
    # every boundary in the wrong place.
    assert _tops(got) == [20, 59, 98], [(r.y0, r.y1) for r in got]


def test_rows_touching_with_no_gap_are_still_separated():
    """FROM FOOTAGE: at 20m20s three rows ran together.

    Coverage never fell below 0.46 across the joins, so no density threshold
    could split them -- the run came out 76px tall against a row height of 34,
    failed the height check, and BOTH lower rows were lost. The pitch is what
    separates them, so the count is arithmetic.
    """
    a = _band()
    for i, y in enumerate((20, 54, 88)):        # 34 apart: no gap at all
        _draw(a, y, 560 + i * 12)
    got = vf.read_frame(a)
    assert len(got) == 3, [(r.y0, r.y1) for r in got]


# ----------------------------------------------------------- global flashes

def test_two_deaths_in_one_frame_are_both_dropped():
    """FROM FOOTAGE at 1196.5s: a whole-screen flash.

    Three rows that read "other" in the frames either side all turned "death"
    together for one frame, each with 218-232 yellow at its right end. In
    Valorant you die at most once a round and rounds are half a minute apart,
    so two of your own deaths on screen together cannot happen -- the game's
    own rule catches this, with no threshold to tune.
    """
    a = _band()
    for i, y in enumerate((20, 59, 98)):
        _draw(a, y, 560 + i * 10, killer=RED, victim=GREEN, yellow_right=True)
    assert {r.kind for r in vf.read_frame(a)} == {"other"}


def test_two_kills_in_one_frame_are_kept():
    # A double kill is ordinary, so the death rule must not be applied to kills.
    a = _band()
    for i, y in enumerate((20, 59)):
        _draw(a, y, 560 + i * 10, killer=GREEN, victim=RED, yellow_left=True)
    assert [r.kind for r in vf.read_frame(a)] == ["kill", "kill"]


def test_a_trade_keeps_both_the_kill_and_the_death():
    """FROM FOOTAGE at 2m05s: the player killed TAHMS and was killed by HARD
    ENOUGH, and both rows sat in the feed together."""
    a = _band()
    _draw(a, 20, 560, killer=GREEN, victim=RED, yellow_left=True)
    _draw(a, 59, 444, killer=RED, victim=GREEN, yellow_right=True)
    assert [r.kind for r in vf.read_frame(a)] == ["kill", "death"]


# -------------------------------------------------------------- collapsing

def _sight(t, kind, x0=600, y0=20):
    return vf.Row(time=t, kind=kind, y0=y0, y1=y0 + 34, x0=x0, x1=RIGHT)


def test_one_row_seen_repeatedly_is_one_event():
    seen = [_sight(10.0 + i * 0.5, "kill") for i in range(8)]
    got = vf.collapse(seen)
    assert len(got) == 1
    assert got[0].kind == "kill"
    assert got[0].time == 10.0        # the event is when it FIRST appeared
    assert got[0].seen == 8


def test_a_single_frame_never_becomes_an_event():
    assert vf.collapse([_sight(10.0, "death")]) == []


def test_a_verdict_is_the_majority_of_the_frames_that_saw_it():
    # Two frames failed to find the yellow; the row is still a kill.
    seen = [_sight(10.0, "kill"), _sight(10.5, "other"), _sight(11.0, "kill"),
            _sight(11.5, "kill"), _sight(12.0, "other")]
    got = vf.collapse(seen)
    assert len(got) == 1 and got[0].kind == "kill"


def test_two_rows_at_the_same_place_far_apart_in_time_are_two_events():
    seen = ([_sight(10.0 + i * 0.5, "kill") for i in range(4)]
            + [_sight(40.0 + i * 0.5, "kill") for i in range(4)])
    assert len(vf.collapse(seen)) == 2


def test_a_row_that_moved_down_is_a_different_row():
    """Rows only ever move UP, as the rows above them expire. Something at the
    same x that has moved DOWN is a new row that happens to be as wide."""
    seen = ([_sight(10.0 + i * 0.5, "kill", y0=59) for i in range(4)]
            + [_sight(12.0 + i * 0.5, "kill", y0=98) for i in range(4)])
    got = vf.collapse(seen)
    assert len(got) == 2, [(e.time, e.seen) for e in got]


def test_a_row_shifting_up_as_the_one_above_expires_stays_one_event():
    seen = ([_sight(10.0 + i * 0.5, "kill", y0=98) for i in range(4)]
            + [_sight(12.0 + i * 0.5, "kill", y0=59) for i in range(4)])
    assert len(vf.collapse(seen)) == 1


def test_rows_of_different_widths_are_different_events():
    seen = ([_sight(10.0 + i * 0.5, "kill", x0=600) for i in range(4)]
            + [_sight(10.0 + i * 0.5, "death", x0=400) for i in range(4)])
    got = vf.collapse(seen)
    assert sorted(e.kind for e in got) == ["death", "kill"]


def test_two_rows_in_one_frame_never_join_the_same_track():
    """FROM FOOTAGE at 18m16s, and it produced a kill that never happened.

    Two rows on screen at once often sit at nearly the same left edge -- these
    were 2px apart. The rows-only-move-up rule cannot separate them, because it
    only fires when the new sighting is LATER, and two rows in one frame share
    a timestamp. So one track absorbed both, a row reading "other" and a row
    reading "kill" split the vote 10-10, and the tie became a kill.
    """
    seen = []
    for i in range(10):
        t = 10.0 + i * 0.5
        seen.append(_sight(t, "other", x0=717, y0=20))
        seen.append(_sight(t, "kill", x0=716, y0=59))
    got = vf.collapse(seen)
    assert len(got) == 2, [(e.kind, e.seen, e.votes) for e in got]
    assert sorted(e.kind for e in got) == ["kill", "other"]
    assert all(e.seen == 10 for e in got)


def test_a_track_cannot_run_longer_than_a_row_lives():
    """FROM FOOTAGE: tracks of 8.0, 8.5, 9.5 and 13.0 seconds were each several
    rows welded together, because their left edges happened to line up."""
    seen = [_sight(10.0 + i * 0.5, "kill") for i in range(40)]   # 20 seconds
    got = vf.collapse(seen)
    assert len(got) > 1
    assert all(e.end - e.time <= vf.MAX_LIFE for e in got), [
        (e.time, e.end) for e in got]


@pytest.mark.parametrize("mine", ["kill", "death", "assist"])
def test_a_tied_vote_never_becomes_a_clippable_event(mine):
    """A missed clip is a far cheaper mistake than a clip of somebody else's
    kill, so a tie goes to not clipping -- whichever verdict is tying."""
    seen = []
    for i in range(4):
        seen.append(_sight(10.0 + i * 1.0, mine))
        seen.append(_sight(10.5 + i * 1.0, "other"))
    got = vf.collapse(seen)
    assert len(got) == 1 and got[0].kind == "other", got


def test_a_clear_majority_still_wins():
    seen = ([_sight(10.0 + i * 0.5, "kill") for i in range(5)]
            + [_sight(12.5 + i * 0.5, "other") for i in range(2)])
    got = vf.collapse(seen)
    assert len(got) == 1 and got[0].kind == "kill"


def test_a_faint_border_is_not_enough_to_claim_the_row():
    """Pins YELLOW_FLOOR against the leak that turned an assist into a kill.

    Measured over 705 sightings: real kills and deaths carry 16-27 yellow
    pixels per pixel of row height, and the leak carried 6.4. The floor was
    2.0 and let it through.
    """
    a = _draw(_band(), 20, 586, killer=GREEN, victim=RED)
    a[20:26, 586:600] = YELLOW           # ~84px on a 34px row: 2.5 per pixel
    assert [r.kind for r in vf.read_frame(a)] == ["other"]
    # and a border of the measured strength is still a kill
    b = _draw(_band(), 20, 586, killer=GREEN, victim=RED, yellow_left=True)
    assert [r.kind for r in vf.read_frame(b)] == ["kill"]


def test_a_track_does_not_walk_from_a_kill_onto_a_death():
    """FROM FOOTAGE at 20m16s: a track voted "kkkkkdd".

    It was a kill row followed by a death row at a similar left edge, and the
    majority reported the death as a kill -- so a clip would have been cut
    around the player being shot. A row does not change from one into the
    other, so a definite flip means a different row.
    """
    seen = ([_sight(10.0 + i * 0.5, "kill") for i in range(5)]
            + [_sight(12.5 + i * 0.5, "death") for i in range(4)])
    got = vf.collapse(seen)
    assert sorted(e.kind for e in got) == ["death", "kill"], [
        (e.kind, e.votes) for e in got]


def test_other_still_settles_into_a_verdict():
    # "other" means the yellow was not found in that frame, not that the row
    # belongs to someone else -- so it must not split a track.
    seen = ([_sight(10.0 + i * 0.5, "other") for i in range(2)]
            + [_sight(11.0 + i * 0.5, "kill") for i in range(6)])
    got = vf.collapse(seen)
    assert len(got) == 1 and got[0].kind == "kill", [
        (e.kind, e.votes) for e in got]


def test_a_stale_track_does_not_steal_a_row_that_slid_up_into_its_slot():
    """FROM FOOTAGE at 1m43s, and it reported a kill four seconds early.

    A row at the top expires; the row below slides up one pitch into the slot
    it vacated. If the two have similar left edges the expiring row's track
    matches the newcomer just as well as its own track does -- and taking the
    first match that fits gave it to the wrong one, so a real kill was reported
    at the time of an unrelated row that had been on screen before it.

    Two things separate them, and both point the same way: the kill's own track
    already had a kill verdict, and it had been seen in the previous frame
    while the expiring row had not.
    """
    seen = []
    for i in range(4):                       # somebody else's row, at the top
        seen.append(_sight(10.0 + i * 0.5, "other", x0=630, y0=20))
    for i in range(3):                       # the player's kill, below it
        seen.append(_sight(11.0 + i * 0.5, "kill", x0=628, y0=59))
    for i in range(5):                       # ... which then slides up
        seen.append(_sight(12.5 + i * 0.5, "kill", x0=628, y0=20))
    got = vf.collapse(seen)
    kills = [e for e in got if e.kind == "kill"]
    assert len(kills) == 1, [(e.kind, e.time, e.votes) for e in got]
    assert kills[0].time == 11.0, (kills[0].time, kills[0].votes)
    assert "o" not in kills[0].votes, kills[0].votes


def test_a_kill_that_degrades_into_assist_readings_is_still_a_kill():
    """FROM FOOTAGE at 0m27s, where a real kill was thrown away.

    A row's left edge wanders late in its life, and once it moves far enough
    the player's own portrait stops touching the name segment and starts
    reading as a detached assist tile. The row came back "kkkaaa" -- three
    strong kill frames at 571-687 yellow, then three degraded ones -- and a
    plain plurality discarded the kill on the 3-3 tie.
    """
    seen = ([_sight(10.0 + i * 0.5, "kill") for i in range(3)]
            + [_sight(11.5 + i * 0.5, "assist") for i in range(3)])
    got = vf.collapse(seen)
    assert len(got) == 1 and got[0].kind == "kill", [
        (e.kind, e.votes) for e in got]


def test_an_assist_is_still_an_assist_when_nothing_harder_was_seen():
    seen = [_sight(10.0 + i * 0.5, "assist") for i in range(6)]
    got = vf.collapse(seen)
    assert len(got) == 1 and got[0].kind == "assist"


def test_assists_do_not_outvote_a_frame_that_found_nothing():
    # Half the frames saw a detached tile, half saw nothing: not enough.
    seen = []
    for i in range(4):
        seen.append(_sight(10.0 + i * 1.0, "assist"))
        seen.append(_sight(10.5 + i * 1.0, "other"))
    got = vf.collapse(seen)
    assert len(got) == 1 and got[0].kind == "other"


def test_tally_counts_every_kind():
    got = vf.tally([vf.Event(time=1, kind="kill"), vf.Event(time=2, kind="kill"),
                    vf.Event(time=3, kind="death")])
    assert got["kill"] == 2 and got["death"] == 1 and got["assist"] == 0


# ----------------------------------------------------------------- refining
#
# Sampling at 2 fps finds THAT a row appeared, not WHEN, and here the gap is far
# wider than the sampling interval because a row slides in over a second or more
# and those frames are rejected on purpose. Measured on two clips the player
# checked by eye: the reported time lagged the row's real appearance by 1.8s and
# 2.9s, so clips cut 1.5s ahead of it started AFTER the kill.

def _fake_frames(monkeypatch, tmp_path, present, kind="kill"):
    """Stub the decode so refine can be driven frame by frame.

    `present` maps a rounded timestamp to whether the row is visible then.
    """
    from PIL import Image

    from autostream.clips import killfeed

    def fake_extract(video, band, start, dur, fps):
        d = tmp_path / f"x_{start:.2f}"
        d.mkdir(exist_ok=True)
        n = int(dur * fps)
        for i in range(1, n + 1):
            Image.new("RGB", (4, 4)).save(d / f"f_{i:05d}.png")
        return d

    def fake_read(a, at=0.0, **kw):
        # x0 DRIFTED from the event's 600: over seconds a row's segment edge
        # wanders much further than it does frame to frame, which is why refine
        # uses a wider tolerance than the tracker does.
        return ([vf.Row(time=at, kind=kind, y0=20, y1=54, x0=645, x1=RIGHT)]
                if present.get(round(at, 2)) else [])

    monkeypatch.setattr(killfeed, "_extract", fake_extract)
    monkeypatch.setattr(vf, "read_frame", fake_read)


def test_refine_moves_a_kill_back_to_when_its_row_appeared(monkeypatch, tmp_path):
    # Visible from 97.0; only noticed at 99.0 by the 2 fps pass.
    present = {round(97.0 + i * 0.125, 2): True for i in range(17)}
    _fake_frames(monkeypatch, tmp_path, present)
    e = vf.Event(time=99.0, kind="kill", x0=600)
    vf.refine(Path("x.mp4"), (0, 0, 1, 1), [e])
    assert e.time == pytest.approx(97.0, abs=0.13), e.time
    assert e.end >= 99.0        # the row was still there when first reported


def test_refine_walks_through_a_detection_gap(monkeypatch, tmp_path):
    """The same row is found, lost for half a second, and found again while
    plainly on screen throughout. A one-frame tolerance stopped at once and
    moved nothing, which is why the walk tolerates a gap in TIME."""
    present = {round(97.0 + i * 0.125, 2): True for i in range(17)}
    for miss in (98.0, 98.125, 98.25, 98.375):
        present[round(miss, 2)] = False
    _fake_frames(monkeypatch, tmp_path, present)
    e = vf.Event(time=99.0, kind="kill", x0=600)
    vf.refine(Path("x.mp4"), (0, 0, 1, 1), [e])
    assert e.time == pytest.approx(97.0, abs=0.13), e.time


def test_refine_stops_at_a_gap_longer_than_a_rows_flicker(monkeypatch, tmp_path):
    # A separate, earlier row: the walk must not chain onto it.
    present = {round(95.0 + i * 0.125, 2): True for i in range(8)}
    present.update({round(98.5 + i * 0.125, 2): True for i in range(5)})
    _fake_frames(monkeypatch, tmp_path, present)
    e = vf.Event(time=99.0, kind="kill", x0=600)
    vf.refine(Path("x.mp4"), (0, 0, 1, 1), [e])
    assert e.time >= 98.4, e.time


def test_refine_never_moves_further_than_its_window(monkeypatch, tmp_path):
    """FROM FOOTAGE: with a 6s window one kill was dragged 5.6s back onto the
    kill before it -- both rows are on screen at once and their left edges are
    within tolerance. Real lags measured at most 3.4s."""
    present = {round(90.0 + i * 0.125, 2): True for i in range(100)}
    _fake_frames(monkeypatch, tmp_path, present)
    e = vf.Event(time=99.0, kind="kill", x0=600)
    vf.refine(Path("x.mp4"), (0, 0, 1, 1), [e])
    # 4.2s, not `99.0 - REFINE_LOOKBACK`: asserting against the constant under
    # test passes for any value it could take.
    assert e.time >= 94.8, e.time


def test_refine_only_moves_the_first_kill_of_a_burst(monkeypatch, tmp_path):
    """FROM A REAL CUT, and it made a "2 kills" clip show one.

    Refining both kills of a double dragged them onto the SAME instant, because
    both rows are on screen together and the walk cannot tell them apart. The
    burst's span collapsed to zero, and the window built from it then ended
    before the second kill.

    Only the first kill decides where a clip starts, so only the first is
    refined and the span survives.
    """
    present = {round(94.0 + i * 0.125, 2): True for i in range(60)}
    _fake_frames(monkeypatch, tmp_path, present)
    first = vf.Event(time=99.0, kind="kill", x0=600)
    second = vf.Event(time=100.5, kind="kill", x0=600)
    vf.refine(Path("x.mp4"), (0, 0, 1, 1), [first, second])
    assert first.time < 99.0, "the first kill should have moved back"
    assert second.time == 100.5, "the second must not move"
    assert second.time - first.time > 1.5, "the burst must keep its span"


def test_refine_moves_a_kill_that_stands_well_clear_of_the_last(monkeypatch,
                                                                tmp_path):
    # The spacing rule must not switch refining off for ordinary lone kills.
    present = {round(94.0 + i * 0.125, 2): True for i in range(60)}
    _fake_frames(monkeypatch, tmp_path, present)
    a = vf.Event(time=80.0, kind="kill", x0=600)
    b = vf.Event(time=99.0, kind="kill", x0=600)
    vf.refine(Path("x.mp4"), (0, 0, 1, 1), [a, b])
    assert b.time < 99.0, b.time


def test_refine_leaves_deaths_alone(monkeypatch, tmp_path):
    # Only kills decide where a clip starts, and refining is not free. The
    # frames here WOULD move it, so the kinds filter is what holds it still.
    present = {round(97.0 + i * 0.125, 2): True for i in range(17)}
    _fake_frames(monkeypatch, tmp_path, present, kind="death")
    e = vf.Event(time=99.0, kind="death", x0=600)
    vf.refine(Path("x.mp4"), (0, 0, 1, 1), [e])
    assert e.time == 99.0
    # ... and the same frames do move a kill, so the fixture is not the reason.
    k = vf.Event(time=99.0, kind="death", x0=600)
    vf.refine(Path("x.mp4"), (0, 0, 1, 1), [k], kinds=("death",))
    assert k.time == pytest.approx(97.0, abs=0.13), k.time


# ------------------------------------------------------------------ wiring

def test_the_valorant_profile_needs_no_name_and_no_template():
    from autostream.clips.profiles import for_game

    p = for_game("valorant-win64-shipping.exe")
    assert p is not None
    assert p.mode == "feedbar"
    assert p.exists(), p.why_not()
    assert p.why_not() == ""
    assert not p.player and not p.template


def test_the_old_wrong_valorant_seed_is_gone():
    """It claimed the feed was top LEFT -- it is top right, measured, every row
    ending at x 0.978-0.986 -- and pointed at a bottom-centre banner that
    upgraded weapon skins replace, so no template could ever have shipped."""
    from autostream.clips.profiles import SEEDS, seed_for

    assert "valorant-win64-shipping.exe" not in SEEDS
    assert seed_for("valorant-win64-shipping.exe") is None


def test_a_feedbar_profile_survives_the_yaml_round_trip():
    from autostream.clips.profiles import _build, for_game

    p = for_game("valorant-win64-shipping.exe")
    back = _build(p.key, p.as_dict())
    assert back is not None
    assert back.mode == "feedbar"
    assert [round(v, 3) for v in back.band] == [round(v, 3) for v in p.band]
    assert back.exists()


def test_detect_routes_feedbar_to_the_bar_reader(monkeypatch, tmp_path):
    """A wiring guard. Two CS2 bugs -- a deleted helper and a Sighting read as
    if it were a FeedEvent -- passed the whole unit suite because nothing
    actually walked this path."""
    from autostream.clips import detect, valorant_feed
    from autostream.clips.profiles import for_game

    called = {}

    def fake_scan(video, band, **kw):
        called["band"] = band
        called["fps"] = kw.get("fps")
        return [valorant_feed.Event(time=t, kind=k) for t, k in
                ((10.0, "kill"), (11.0, "kill"), (30.0, "death"),
                 (40.0, "assist"), (60.0, "kill"))]

    monkeypatch.setattr(valorant_feed, "scan", fake_scan)
    monkeypatch.setattr(detect, "media_info",
                        lambda p: {"width": 1920, "height": 1080,
                                   "duration": 120.0})
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"")
    kills = detect.scan(src, for_game("valorant-win64-shipping.exe"))

    assert called["band"] == (0.50, 0.070, 1.00, 0.235)
    assert called["fps"] == 2.0
    # Deaths and assists are NOT clipped. The two kills a second apart stay TWO
    # Kill objects: merging them here loses the second timestamp, and the
    # planner counts entries -- which is how four real double kills came out
    # labelled "1kill" while containing two. Grouping is the planner's job.
    assert [(k.time, k.count) for k in kills] == [
        (10.0, 1), (11.0, 1), (60.0, 1)]


def test_a_double_kill_is_labelled_two_kills_not_one(monkeypatch, tmp_path):
    """FROM A REAL CUT: four clips said "1kill" and contained two.

    The detector merged kills within its merge_gap into one Kill carrying
    count=2, which threw the second timestamp away. plan.cluster counts
    ENTRIES, so the burst reported one kill and the filename said so -- while
    the clip plainly showed two. Kills stay separate now and the planner groups
    them, which is what its 22s cluster window is for.
    """
    from autostream.clips import detect, plan, valorant_feed
    from autostream.clips.profiles import for_game

    def fake_scan(video, band, **kw):
        return [valorant_feed.Event(time=t, kind="kill")
                for t in (330.5, 331.5)]        # a second apart, as measured

    monkeypatch.setattr(valorant_feed, "scan", fake_scan)
    monkeypatch.setattr(detect, "media_info",
                        lambda p: {"width": 1920, "height": 1080,
                                   "duration": 600.0})
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"")
    kills = detect.scan(src, for_game("valorant-win64-shipping.exe"))
    assert len(kills) == 2, kills

    plans = plan.build([{"time": k.time, "end": k.end, "score": k.score,
                         "count": k.count} for k in kills],
                       game="VALORANT", min_kills=1, clip_seconds="15",
                       pre_roll=1.5, tail=2.0, source_duration=600.0)
    assert len(plans) == 1
    assert plans[0].kills == 2, plans[0].name
    assert "2kills" in plans[0].name, plans[0].name


@pytest.mark.parametrize("mode", ["template", "colour", "killfeed", "feedbar"])
def test_every_mode_the_builder_accepts_is_a_mode_something_handles(mode):
    from autostream.clips.profiles import _build

    p = _build("x.exe", {"label": "X", "band": [0, 0, 1, 1], "mode": mode,
                         "template": "t.npy"})
    assert p is not None and p.mode == mode


# ------------------------------------------------------------ whose victim
#
# `kind` only ever speaks about the local player, and most rows are other
# people killing each other. Which SIDE lost the player is the one signal here
# that covers those rows, and so the only thing a round's alive counts could be
# built from.

def _portraits(a, y0, x0, x1, h=34, colour=RED):
    """Agent portraits at both ends of a row.

    Photographs, not bars: warm artwork that reads RED whichever team the
    player is on. This is what defeated the two simpler readings.
    """
    a[y0:y0 + h, x0:x0 + 55] = colour
    a[y0:y0 + h, x1 - 55:x1] = colour
    return a


def test_the_victim_side_is_the_colour_at_the_bar_s_right_end():
    a = _band()
    _draw(a, 40, 500, killer=GREEN, victim=RED)      # I killed an enemy
    red, green, _y = vf.masks(a)
    assert vf.victim_of(red, green, 40, 74, 500, RIGHT) == "enemy"

    b = _band()
    _draw(b, 40, 500, killer=RED, victim=GREEN)      # an enemy killed my side
    red, green, _y = vf.masks(b)
    assert vf.victim_of(red, green, 40, 74, 500, RIGHT) == "mine"


def test_the_portraits_do_not_decide_the_victim():
    """The first attempt sampled the last 28% of the row.

    That is the victim's PORTRAIT, and portraits are warm artwork: 157/157
    kills still came out right, because an enemy's bar is red anyway, and a
    self-kill came out wrong -- its bar is green with a red portrait at each
    end.
    """
    a = _band()
    _draw(a, 40, 500, killer=GREEN, victim=GREEN)    # a self-kill: all mine
    _portraits(a, 40, 500, RIGHT)
    red, green, _y = vf.masks(a)
    assert vf.victim_of(red, green, 40, 74, 500, RIGHT) == "mine"


def test_a_row_that_will_not_say_says_nothing():
    a = _band()                                       # no row drawn at all
    red, green, _y = vf.masks(a)
    assert vf.victim_of(red, green, 40, 74, 500, RIGHT) == ""


def test_the_victim_side_survives_a_frame_that_disagrees():
    """Two sightings out of 202 disagreed with their own row.

    A per-event majority is what makes those cost nothing, and it is the same
    reasoning the kind vote already uses.
    """
    rows = [vf.Row(time=t, kind="kill", y0=40, y1=74, x0=500, x1=RIGHT,
                   left=400, right=0,
                   victim="mine" if t == 2.0 else "enemy")
            for t in (1.0, 1.5, 2.0, 2.5, 3.0)]
    got = vf.collapse(rows, min_seen=3)
    assert len(got) == 1
    assert got[0].victim == "enemy"


# ------------------------------------------------- one kill counted as two
#
# FROM FOOTAGE. Five clips out of a 93-minute Valorant recording went out
# labelled "2 kills" holding exactly one. All five were the same row counted
# twice, by three different routes.

def test_one_stray_kill_frame_does_not_outvote_three_assist_frames():
    """FROM FOOTAGE at 43m43s: a row voting "aaka" was reported as a kill.

    A hard verdict only had to beat "other", and no frame there read "other",
    so a single misread frame won outright against three that agreed.
    """
    seen = [_sight(10.0, "assist"), _sight(10.5, "assist"),
            _sight(11.0, "kill"), _sight(11.5, "assist")]
    got = vf.collapse(seen)
    assert len(got) == 1
    assert got[0].kind == "assist", got[0].votes


def test_a_hard_verdict_still_wins_a_tie_with_assists():
    """The rescue this rule exists for must survive the fix above.

    A row whose edge wanders late in its life starts reading as a detached
    assist tile, so a real kill comes back "kkkaaa" -- and a plain plurality
    threw it away on the 3-3 tie.
    """
    seen = [_sight(10.0 + i * 0.5, "kill") for i in range(3)]
    seen += [_sight(11.5 + i * 0.5, "assist") for i in range(3)]
    got = vf.collapse(seen)
    assert len(got) == 1 and got[0].kind == "kill", got[0].votes


def test_a_row_sliding_up_with_a_wandering_edge_is_still_one_event():
    """FROM FOOTAGE at 1h14m04s: y 98 -> 59 while the left edge moved 16px.

    Two over X_TOL, so the row's own track lost it and a second track started.
    """
    seen = [_sight(10.0 + i * 0.5, "kill", y0=98, x0=654) for i in range(4)]
    seen += [_sight(12.0 + i * 0.5, "kill", y0=59, x0=638) for i in range(5)]
    got = vf.collapse(seen)
    assert len(got) == 1, [(e.time, e.y0, e.votes) for e in got]


def test_a_row_holding_its_slot_across_a_dropout_is_one_event():
    """FROM FOOTAGE at 1h20m04s: one row sat at y 20 for four and a half
    seconds while its edge swung 566-640-566-668-648, with a frame missing in
    the middle. The feed only ever appends BELOW, so a second kill cannot land
    in a slot this one is still holding."""
    xs = [566, 640, 566, 640, 668]
    seen = [_sight(10.0 + i * 0.5, "kill", y0=20, x0=x) for i, x in enumerate(xs)]
    seen += [_sight(13.0 + i * 0.5, "kill", y0=20, x0=x)      # 1s hole
             for i, x in enumerate((648, 662, 672, 670))]
    got = vf.collapse(seen)
    assert len(got) == 1, [(e.time, e.votes) for e in got]


def test_a_real_second_kill_in_the_next_slot_is_still_two_events():
    """The guard on all of the above: the merges must not swallow a genuine
    double. A second kill lands in a DIFFERENT slot, because the row above it
    is still alive."""
    seen = [_sight(10.0 + i * 0.5, "kill", y0=20, x0=600) for i in range(6)]
    seen += [_sight(11.5 + i * 0.5, "kill", y0=59, x0=640) for i in range(6)]
    got = vf.collapse(seen)
    assert len(got) == 2, [(e.time, e.y0, e.votes) for e in got]


def test_a_row_missed_for_one_frame_keeps_its_slot():
    """FROM FOOTAGE at 1h27m09s. Two of the player's kill rows sat at their
    own slots. The upper one was missed in a single frame, which made the LOWER
    row's track the more recently seen -- so on the next frame it took the
    upper row (a legal one-pitch slide) and stranded its own. The stranded row
    started a second track, and the clip went out cut as four kills holding
    three.

    A row only moves when the row above it expires, so a track that did not
    have to move is the better explanation of a position than one that did.
    """
    seen = []

    def frame(t, upper=True):
        if upper:
            seen.append(_sight(t, "kill", y0=20, x0=580))
        seen.append(_sight(t, "kill", y0=59, x0=632))

    for i in range(4):
        frame(10.0 + i * 0.5)
    frame(12.0, upper=False)        # the upper row is missed here
    for i in range(4):
        frame(12.5 + i * 0.5)

    got = [e for e in vf.collapse(seen) if e.kind == "kill"]
    assert len(got) == 2, [(e.time, e.y0, e.votes) for e in got]


def test_the_feed_sliding_up_through_a_degraded_frame_is_one_row_each():
    """FROM FOOTAGE at 1h27m07s. The frames on which rows MOVE are exactly the
    ones that read badly: the whole feed slid up a pitch and both kill rows
    came back "assist" in that frame. Requiring the frame's verdict to match
    the track's meant nothing could bridge it, and the row that slid into the
    vacated slot was taken for the row that had been sitting there.
    """
    seen = []
    for i in range(2):                       # three rows, stacked
        t = 10.0 + i * 0.5
        seen.append(_sight(t, "other", y0=20, x0=650))
        seen.append(_sight(t, "kill", y0=59, x0=588))
        seen.append(_sight(t, "kill", y0=98, x0=684))
    seen.append(_sight(11.0, "kill", y0=59, x0=588))    # the top row goes
    seen.append(_sight(11.0, "kill", y0=98, x0=650))
    # ...everything moves up, and the frame they move on reads badly
    seen.append(_sight(11.5, "assist", y0=20, x0=628))
    seen.append(_sight(11.5, "assist", y0=59, x0=652))
    for i in range(4):
        t = 12.0 + i * 0.5
        seen.append(_sight(t, "kill", y0=20, x0=578))
        seen.append(_sight(t, "kill", y0=59, x0=638))

    got = [e for e in vf.collapse(seen) if e.kind == "kill"]
    assert len(got) == 2, [(e.time, e.y0, e.votes) for e in got]
