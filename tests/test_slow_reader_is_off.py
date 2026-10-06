r"""The Counter-Strike screen read is switched off, and stays off.

MEASURED TWICE ON REAL FOOTAGE at 1.46x and 1.19x real time. A 45-minute
stream is about 40 minutes of reading. That is not a slow option, it is a
different order of magnitude -- and the people who said yes to it were the
ones who did not read the number printed beside the button.

THREE DOORS, AND ALL THREE HAVE TO BE SHUT. The reading choice on the style
page, the "Full rounds" button on the panel a stopped run puts up, and the
request itself. A page that stops drawing a control stops the button; it does
not stop the request, and the request is what spends the forty minutes.

WHAT REMAINS COVERS THE SAME GROUND. A replay is exact and instant; the kill
tally is about eight times faster than this and gets the kills right. Only
the round NAMES are lost without a replay, and the page says so.
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def clips_src() -> str:
    return (ROOT / "autostream" / "ui" / "clips.py").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def webui_src() -> str:
    return (ROOT / "autostream" / "webui.py").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def media_src() -> str:
    return (ROOT / "tests" / "verify" / "test_media.py").read_text(encoding="utf-8")


# ------------------------------------------------------- door one: the page

def test_the_slow_way_is_marked_as_developer_only(clips_src):
    """The fourth field on a CLIP_WAYS row means "developer mode only", and
    exactly one row carries it."""
    start = clips_src.index("var CLIP_WAYS = [")
    block = clips_src[start:clips_src.index("];", start)]
    assert "'rounds'" in block
    rounds = block[block.index("['rounds'"):]
    assert "true]" in rounds, "the slow reader is no longer marked"


def test_the_page_filters_it_out_unless_developer_mode_is_on(clips_src):
    assert "function clip_waysOffered()" in clips_src
    fn = clips_src[clips_src.index("function clip_waysOffered()"):]
    fn = fn[:fn.index("\n}")]
    assert "clip_state.dev" in fn


def test_the_chooser_draws_what_is_offered_and_not_the_whole_list(clips_src):
    """Filtering a list nothing renders from would be a no-op that reads
    like a fix."""
    fn = clips_src[clips_src.index("function clip_renderWays()"):]
    fn = fn[:fn.index("\n}\n")]
    assert "clip_waysOffered()" in fn
    assert "CLIP_WAYS.map" not in fn, "the chooser still draws every way"


def test_a_way_that_is_no_longer_offered_cannot_stay_chosen(clips_src):
    """Developer mode switched off with 'rounds' already selected would
    leave the run pointed at the hidden reader, with nothing on screen
    saying so."""
    fn = clips_src[clips_src.index("function clip_renderWays()"):]
    fn = fn[:fn.index("\n}\n")]
    assert "clip_state.way = 'demo'" in fn


# ---------------------------------------------------- door two: the panel

def test_the_needs_demo_button_is_developer_only_too(clips_src):
    """The other door. Somebody who has just been told their run cannot
    continue is exactly who presses "Full rounds, slower"."""
    assert "clip_show('clip-needsdemo-anyway', !!clip_state.dev)" in clips_src


def test_the_panel_does_not_describe_a_button_it_is_not_showing(clips_src):
    """It said "there are two ways" over a single button."""
    assert 'id="clip-needsdemo-how"' in clips_src
    assert "there are two ways" not in clips_src.split("clip_renderJob")[0], \
        "the fixed prose is back in the markup"


# -------------------------------------------------- door three: the request

def test_the_server_refuses_the_full_read_without_developer_mode(webui_src):
    """HIDING A CONTROL STOPS THE BUTTON, NOT THE REQUEST. This is the one
    that means something."""
    i = webui_src.index('if body.get("demo_fallback"):')
    block = webui_src[i:i + 2000]
    assert 'elif not getattr(c.ui, "developer_mode", False):' in block
    assert "return {\"error\"" in block


def test_it_says_so_rather_than_quietly_running_something_else(webui_src):
    """Clips named "3 kills" handed to somebody who asked for ACE and
    CLUTCH, with no explanation, is worse than a refusal."""
    i = webui_src.index('if body.get("demo_fallback"):')
    block = webui_src[i:i + 2000]
    assert "switched off" in block
    assert "Kills only" in block, "the refusal does not name the way forward"
    assert "Developer mode" in block, "the refusal does not say how to re-enable it"


def test_the_fast_reader_is_still_allowed(webui_src):
    """The whole point of switching one off is that the other two remain."""
    i = webui_src.index('if body.get("demo_fallback"):')
    block = webui_src[i:i + 2000]
    cards = block.index('== "cards"')
    refusal = block.index("developer_mode")
    assert cards < refusal, "the cards reader is caught by the refusal"


# --------------------------------------------------- and the build gate

def test_the_build_no_longer_measures_it(media_src):
    assert "SLOW_READERS = {\"killfeed\"}" in media_src


def test_every_test_that_scores_a_detector_honours_the_switch(media_src):
    """A scorer that forgot would scan it anyway, which is the whole cost."""
    scorers = ("test_the_detector_still_finds_what_a_person_confirmed",
               "test_the_detector_does_not_invent_kills",
               "test_a_quiet_excerpt_does_not_get_noisier",
               "test_the_game_as_a_whole_does_not_regress")
    for name in scorers:
        body = media_src[media_src.index(f"def {name}("):]
        body = body[:body.index("\n\n\n")] if "\n\n\n" in body else body
        assert "_slow(" in body, f"{name} does not honour SLOW_READERS"


def test_the_scan_itself_skips_it(media_src):
    """The fixture is session-scoped and scans every reviewed excerpt up
    front, so skipping only in the tests would still pay for the decode."""
    fn = media_src[media_src.index("def scanned()"):]
    fn = fn[:fn.index("\n\n\n")]
    assert "_slow(" in fn


def test_it_can_still_be_measured_on_purpose(media_src):
    """Switched off is not deleted. The day the turnaround is fixed, this
    is how it gets measured again."""
    assert 'os.environ.get("AUTOSTREAM_SLOW_READERS")' in media_src


def test_a_skipped_measurement_says_why(media_src):
    """"not run" must never be mistakable for "passing"."""
    fn = media_src[media_src.index("def _slow("):]
    fn = fn[:fn.index("\n\n\n")]
    assert "switched off" in fn
    assert "AUTOSTREAM_SLOW_READERS" in fn


# --------------------------------------------------------- and the rule

def test_the_rule_is_written_down_where_the_rules_live():
    """CLAUDE.md is the file whose first line says each rule is something
    that has already cost a session. An undocumented switch gets switched
    back by the next person who finds a disabled feature."""
    rules = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## A reader slower than real time is not shipped" in rules
    for must in ("1.46x", "killfeed", "SLOW_READERS", "developer_mode",
                 "AUTOSTREAM_SLOW_READERS"):
        assert must in rules, f"the rule does not mention {must}"
