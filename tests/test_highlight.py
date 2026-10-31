"""The themed renderer's filter graph (clips/highlight.py), checked as text -- graph()
is kept free of ffmpeg so it can be."""
from __future__ import annotations


def test_a_cold_open_puts_the_title_over_the_intro_and_cards_on_the_moments():
    """ChatGPT, 2026-11-01: open on a few seconds of the best moment, THEN the title;
    and say each moment's round and score as it opens."""
    from autostream.clips import highlight as h

    shots = [h.Shot(500.0, 504.8, "fight"), h.Shot(100.0, 116.0, "intro"),
             h.Shot(200.0, 214.0, "fight", card="Round 12  ·  8-9"), h.Shot(300.0, 312.0, "fight")]
    durs = [s.seconds for s in shots]
    text, _total = h.graph(shots, durs, [205.0], [], title=True)
    ta = h.offsets(durs)[1]
    assert f"between(t,{ta:.3f},{ta + 2.8:.3f})" in text          # the title, over the intro
    assert "textfile=card2.txt" in text and "card3.txt" not in text
    a = h.offsets(durs)[2] + h.CARD_IN
    assert f"between(t,{a:.3f},{a + h.CARD_SECONDS:.3f})" in text


def test_a_card_leaves_before_its_kill_and_sits_top_centre():
    from autostream.clips import highlight as h

    shots = [h.Shot(100.0, 116.0, "intro"), h.Shot(200.0, 214.0, "fight", card="Round 3  ·  1-1")]
    durs = [s.seconds for s in shots]
    a = h.offsets(durs)[1] + h.CARD_IN
    kill = 200.0 + h.CARD_IN + 1.2                 # 1.2 s after the card comes up
    text, _ = h.graph(shots, durs, [kill], [], title=True)
    k_out = h.at_output(shots, h.offsets(durs), kill)
    assert f"between(t,{a:.3f},{k_out - h.CARD_CLEAR:.3f})" in text
    assert f"y=h*{h.CARD_Y}" in text and "x=(w-text_w)/2" in text
    # a kill straight after the cut leaves no time for a card at all
    text, _ = h.graph(shots, durs, [200.0 + h.CARD_IN + 0.5], [], title=True)
    assert "card1.txt" not in text
