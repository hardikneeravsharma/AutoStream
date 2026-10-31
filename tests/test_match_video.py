"""The match video's renderer (clips/match_video.py): not the Marvel highlight's.

The player watched the first Valorant recap -- whips and whooshes between moments, a
synthesised hit and a white flash on every kill, an Impact title -- and said the fonts
were terrible and the transitions and kill sounds not good. ChatGPT's spec, checked
here without ffmpeg: hard cuts, a short dip between rounds, the game's own sound, two
typefaces with every glyph present, cards that leave before the kill, the match's
story on screen, and a facecam close-up only for the strongest few reactions.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

from PIL import ImageFont

from autostream.clips import match_video as mv
from autostream.clips.match_story import Story

BIND = [c == "W" for c in "WLLWLLWLWLLLLLLWWWLWWWWL"]


def _m(start, end, n, kills=(), reaction=False, react_at=None, score=0.0):
    m = NS(start=start, end=end, round=NS(number=n), kills=list(kills), reaction=reaction,
           react_at=react_at, react_score=score)
    return m


def test_the_pieces_cold_open_intro_moments_half_time_result():
    story = Story(BIND)
    ms = [_m(100, 115, 7, [110]), _m(130, 140, 7, [135]), _m(300, 320, 13, [310]), _m(500, 515, 24)]
    ps = mv.plan(ms, opening=NS(start=10, end=26), story=story, cold=(308.5, 313.3), facecam_box=None)
    assert [p.kind for p in ps] == ["open", "intro", "moment", "moment", "half", "moment", "moment", "result"]
    # a hard cut within a round, a dip between rounds
    assert ps[3].dip_in is False and ps[2].dip_in is True and ps[5].dip_in is True
    assert ps[2].dip_out is False and ps[3].dip_out is True       # out of round 7 into the half-time card


def test_only_the_three_strongest_reactions_get_a_facecam_close_up():
    ms = [_m(100 * i, 100 * i + 20, i, [100 * i + 8], reaction=True, react_at=100 * i + 9, score=i)
          for i in range(1, 7)]
    ps = mv.plan(ms, opening=None, story=None, cold=None, facecam_box=[0.01, 0.58, 0.25, 0.28])
    cut = [p.round for p in ps if p.cutaway is not None]
    assert sorted(cut) == [4, 5, 6]
    # after the action, never over the kill
    for p in ps:
        if p.cutaway is not None:
            assert p.cutaway >= p.first_kill + mv.CUTAWAY_AFTER_KILL


def test_no_box_marked_no_close_up():
    ms = [_m(100, 120, 3, [108], reaction=True, react_at=109, score=9)]
    assert mv.plan(ms, opening=None, story=None, cold=None, facecam_box=None)[0].cutaway is None


def test_a_card_leaves_before_the_first_kill_or_is_not_drawn():
    p = mv.Piece("moment", 100.0, 120.0, first_kill=102.0)
    a, b = mv.card_window(p)
    assert a == mv.CARD_IN and abs(b - (2.0 - mv.CARD_CLEAR)) < 1e-9
    assert mv.card_window(mv.Piece("moment", 100.0, 120.0, first_kill=100.9)) is None
    assert mv.card_window(mv.Piece("moment", 100.0, 120.0)) == (mv.CARD_IN, mv.CARD_IN + mv.CARD_SECONDS)


def test_the_graph_is_hard_cuts_and_the_games_own_sound():
    ps = [mv.Piece("intro", 10, 26), mv.Piece("moment", 100, 115, round=7, first_kill=110, dip_in=True),
          mv.Piece("moment", 130, 140, round=7, first_kill=135),
          mv.Piece("result", seconds=3.2, still="result.png", dip_in=True)]
    ps[0].dip_out = True
    text = mv.graph(ps, {0: 0, 1: 1, 2: 2, 3: 3}, {0: 4, 1: 5}, None)
    for gone in ("xfade", "whoosh", "hit", "fadewhite", "eq=brightness=0.28"):
        assert gone not in text, gone
    assert "concat=n=4:v=1:a=1" in text and "loudnorm=I=-16:TP=-1" in text
    assert f"fade=t=in:st=0:d={mv.DIP:.3f}" in text            # the dip into round 7
    assert "anullsrc" in text                                   # a card has no sound of its own


def test_a_facecam_close_up_is_cut_from_inside_the_marked_box():
    p = mv.Piece("moment", 100, 120, round=3, cutaway=110.0)
    text = mv.graph([p], {0: 0}, {}, [0.0122, 0.5851, 0.2514, 0.2795])
    assert "crop=iw*" in text and "between(t,10.000,11.200)" in text
    x = 0.0122 + 0.2514 * mv.CUTAWAY_TRIM
    assert f"ih*{0.5851 + 0.2795 * mv.CUTAWAY_TRIM}" in text and f"iw*{x}" in text


def test_a_cards_label_does_not_repeat_its_round():
    assert mv.card_label("Round 24 - Final round", 24) == "Final round"
    assert mv.card_label("Thrifty - Round 09 - Second Moment", 9) == "Thrifty - Second Moment"
    assert mv.card_label("3K In 5s", 10) == "3K In 5s"


def test_a_font_missing_a_glyph_is_not_used():
    f = ImageFont.truetype(str(mv.BUNDLED / "Poppins-ExtraBold.ttf"), 40)
    assert mv.has_glyphs(f, "VALORANT 11-13")
    assert not mv.has_glyphs(f, "ༀ")            # a Tibetan syllable Poppins does not draw
    # whatever the pack holds, the face handed back draws the text it was asked for
    assert mv.has_glyphs(mv.face("text", 30, "Round 13  ·  4-8"), "Round 13  ·  4-8")


def test_chapters_are_plays_not_cards():
    ps = [mv.Piece("open", 0, 4.8), mv.Piece("intro", 10, 26), mv.Piece("moment", 100, 115),
          mv.Piece("half", seconds=1.8, still="half.png"), mv.Piece("moment", 300, 320),
          mv.Piece("result", seconds=3.2, still="result.png")]
    marks = mv.chapters(ps, {2: "Last Alive", 4: "Final round"})
    assert [n for _t, n in marks] == ["Intro", "Last Alive", "Final round", "Final score"]
    assert marks[0][0] == 0.0


def test_the_facts_come_from_the_whole_match():
    rec = {"map": "Bind", "agent": "Cypher", "kills": 22, "deaths": 18, "assists": 7, "acs": 274, "won": BIND}
    fx = mv.facts("VALORANT", rec, Story(BIND))
    assert fx.head == "VALORANT  ·  BIND" and fx.result == "11-13 LOSS"
    assert fx.line == "CYPHER  ·  22 / 18 / 7  ·  ACS 274"
    assert fx.story_line.startswith("4-8 at the half")


def test_the_cards_draw():
    img = mv.context_card("Round 13  ·  4-8  ·  1v4", "Last Alive 1v4", BIND, 12, 13)
    assert img.size == (mv.W, mv.H) and img.getbbox() is not None
    assert mv.full_card(None, "HALF-TIME", "4 - 8", mv.OFF_WHITE, [], BIND[:12], 12).size == (mv.W, mv.H)
    assert mv.title_card("VALORANT  ·  BIND", "11-13 LOSS", "  ·  CYPHER", "4-8 at the half").getbbox()
