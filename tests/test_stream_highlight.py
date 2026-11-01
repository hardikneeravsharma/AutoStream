"""Stream highlights: continuous stretches bounded by their situation (clips/stream_highlight.py).

The Bind match of 2026-10-25 is the measured case: round 10 had a plant at 682.9,
team-mates dying at 686.7 and 690.7, the player's three kills at 704.9, 706.0 and
709.0, his death at 711.6 and a 24 dB-second scream from 712.0 to 717.4; the round
was decided at 716.9. The planner is arithmetic over times, so these tests feed it
times and read the spans back.
"""
from __future__ import annotations

import numpy as np

from autostream.clips import stream_highlight as sh
from autostream.clips.match_story import Story
from autostream.clips.reactions import Reaction

R10 = {"number": 10, "start": 642.3, "end": 716.9, "plant": 682.9, "last_stand": None, "final": False,
       "contacts": [651.6, 686.7, 689.9, 690.7, 704.9, 706.0, 709.0, 711.6], "labels": ["3K IN 5s"]}
R11 = {"number": 11, "start": 753.9, "end": 783.2, "plant": None, "last_stand": None, "final": False,
       "contacts": [757.2, 767.2, 769.8, 775.0, 783.2]}


def rx(start, end, score):
    return Reaction(at=start, start=start, end=end, score=score, peak_db=15.0)


def r10_events():
    return sh.events(kills=[704.9, 706.0, 709.0], deaths=[711.6], reactions=[rx(712.0, 717.4, 24.0)],
                     rounds=[R10, R11])


def test_speech_runs_join_words_and_respect_the_gate():
    lv = np.full(200, -90.0, dtype=np.float32)           # 10 s at 20 Hz, gated silent
    lv[20:40] = -30                                       # 1.0-2.0 s
    lv[50:60] = -30                                       # 2.5-3.0 s: 0.5 s gap, joined
    lv[120:140] = -30                                     # 6.0-7.0 s
    assert sh.speech_runs(lv, offset=100.0) == [(101.0, 103.0), (106.0, 107.0)]
    assert sh.speech_runs(np.empty(0)) == []


def test_game_activity_is_the_game_over_its_own_baseline():
    lv = np.full(400, -40.0, dtype=np.float32)
    lv[200:220] = -25.0                                   # a burst of gunfire at 10-11 s
    assert sh.game_activity(lv) == [(10.0, 11.0)]


def test_the_fight_starts_at_first_contact_not_at_the_plant():
    # 704.9 chains back to nothing within 10 s (690.7 is 14 s earlier), and the
    # plant at 682.9 frames the round but does not start the stretch.
    s = sh.stretches(r10_events(), speech=[], rounds=[R10, R11])[0]
    assert s.start == 704.9 - sh.SETUP
    assert sh.punches(s) == [709.0]


def test_a_last_alive_moment_starts_the_stretch():
    r = dict(R10, last_stand=696.0)
    s = sh.stretches(r10_events(), speech=[], rounds=[r, R11])[0]
    assert s.start == 696.0 - sh.STATE_SETUP


def test_the_reaction_plays_out_and_the_round_ends_on_its_result():
    s = sh.stretches(r10_events(), speech=[], rounds=[R10, R11])[0]
    # the scream ends 717.4; the round was decided at 716.9 (within RESOLVE)
    assert s.end == max(717.4 + sh.REACTION_TAIL, 716.9 + sh.RESULT_HOLD)
    # talking it out after the scream keeps it going, up to REACTION_TALK
    s = sh.stretches(r10_events(), speech=[(712.0, 724.0)], rounds=[R10, R11])[0]
    assert s.end == 724.0 + sh.AFTER_TALK
    # a second turn that follows straight on is the same continuation
    s = sh.stretches(r10_events(), speech=[(712.0, 720.0), (721.0, 725.0)], rounds=[R10, R11])[0]
    assert s.end == 725.0 + sh.AFTER_TALK
    s = sh.stretches(r10_events(), speech=[(712.0, 760.0)], rounds=[R10, R11])[0]
    assert s.end == 717.4 + sh.REACTION_TALK + sh.AFTER_TALK


def test_a_stretch_never_runs_into_the_next_rounds_fight():
    evs = sh.events(kills=[780.0], deaths=[], reactions=[], rounds=[R10, R11])
    s = sh.stretches(evs, speech=[], rounds=[R10, R11])[0]
    assert s.end <= 783.2 + sh.AFTER_ROUND


def test_mid_sentence_starts_move_back_a_little_but_never_a_minute():
    s = sh.stretches(r10_events(), speech=[(695.0, 701.0)], rounds=[R10, R11])[0]
    assert s.start == 695.0 - 0.3
    s = sh.stretches(r10_events(), speech=[(600.0, 701.0)], rounds=[R10, R11])[0]
    assert s.start == 704.9 - sh.SETUP


def test_the_last_round_plays_to_the_result_screen():
    r24 = {"number": 24, "start": 2006.3, "end": 2088.0, "plant": 2063.2, "last_stand": None, "final": True,
           "contacts": [2012.8, 2019.3, 2025.1, 2049.0, 2058.0, 2068.0, 2083.0, 2088.0]}
    evs = sh.events(kills=[], deaths=[2058.0], reactions=[rx(2058.6, 2061.0, 13.0)], rounds=[r24])
    s = sh.stretches(evs, speech=[], rounds=[r24])[0]
    assert s.end == 2088.0 + sh.FINAL_HOLD


def test_a_death_alone_is_not_a_stretch_and_weak_reactions_are_talking():
    evs = sh.events(kills=[], deaths=[300.0], reactions=[rx(600.0, 601.0, 3.0)])
    assert sh.stretches(evs, speech=[]) == []


def test_talking_is_not_scored():
    quiet = sh.stretches(r10_events(), speech=[], rounds=[R10, R11])[0]
    chatty = sh.stretches(r10_events(), speech=[(650.0, 760.0)], rounds=[R10, R11])[0]
    assert quiet.score == chatty.score


def test_dead_time_is_cut_but_never_the_build_up_or_a_post_plant():
    s = sh.Stretch(start=0.0, end=60.0, score=5.0, events=[sh.Event(50.0, "kill", 1.0)])
    cuts = sh.trim_dead(s, speech=[(0.0, 10.0)])
    # silence 10-46 (the 4 s before the kill are held): cut, keeping 1.5 s in and 2 s out;
    # then the 9.5 s of silence that ends the stretch, cut after 1.5 s
    assert cuts == [(0.0, 11.5), (44.0, 52.0)]
    # game audio counts as activity
    assert sh.trim_dead(s, speech=[(0.0, 10.0)], game=[(10.0, 46.0)])[0] == (0.0, 52.0)
    # and a plant protects everything after it
    r = {"number": 1, "start": 0.0, "end": 60.0, "plant": 12.0, "contacts": [50.0]}
    assert sh.trim_dead(s, speech=[(0.0, 10.0)], r=r) == [(0.0, 60.0)]


def test_selection_keeps_the_best_in_order_and_the_final_round_always():
    a = sh.Stretch(start=0, end=100, score=9.0, round=3)
    b = sh.Stretch(start=200, end=300, score=8.0, round=5)
    c = sh.Stretch(start=400, end=420, score=1.0, round=24)
    d = sh.Stretch(start=500, end=520, score=1.0, round=20)
    got = sh.select([a, b, c, d], budget=150, must=[24])
    assert got == [a, c]                                  # b does not fit, d is too weak


def test_plan_opens_on_the_strongest_action_not_the_highest_score():
    r23 = {"number": 23, "start": 1895.1, "end": 1969.3, "plant": 1943.6, "last_stand": None, "final": True,
           "contacts": [1898.9, 1922.5, 1931.4, 1954.2, 1955.0, 1956.0, 1965.3, 1967.7, 1970.0]}
    story = Story([c == "W" for c in "WLLWLLWLWLLLLLLWWWLWWWWL"])
    cuts, chosen = sh.plan(kills=[704.9, 706.0, 709.0, 1954.2, 1965.3], deaths=[711.6, 1967.7],
                           reactions=[rx(712.0, 717.4, 24.0), rx(1927, 1929, 7), rx(1941, 1943, 7),
                                      rx(1969, 1971, 8), rx(1984, 1986, 12)],
                           speech=[(1900.0, 1990.0)], rounds=[R10, R11, r23], story=story)
    assert cuts[0].kind == "cold"
    assert (cuts[0].start, cuts[0].end) == (706.0, 706.0 + sh.COLD_LONGEST)
    assert [c.kind for c in cuts[1:]] == ["play"] * (len(cuts) - 1)
    assert [c.start for c in cuts[1:]] == sorted(c.start for c in cuts[1:])
    assert any(c.punches == [709.0] for c in cuts)


def test_the_zoom_is_one_outside_the_punch():
    assert sh.zoom_expr([]) == "1"
    z = sh.zoom_expr([2.0])
    assert z.startswith("1+0.1200*(") and "it-1.8500" in z


def test_chapters_name_each_stretch_once_from_zero():
    chosen = [sh.Stretch(start=0, end=30, score=5, round=7, why="LAST ALIVE"),
              sh.Stretch(start=100, end=150, score=5, round=10, why="3 kills")]
    cuts = [sh.Cut(5, 10, kind="cold", stretch=1), sh.Cut(0, 30, stretch=0),
            sh.Cut(100, 120, stretch=1), sh.Cut(125, 150, stretch=1)]
    assert sh.chapters(cuts, chosen) == [(0.0, "Round 7 - LAST ALIVE"), (35.0, "Round 10 - 3 kills")]


def test_respawn_matches_cluster_tighter_and_count_kills_for_less():
    kills = [100.0, 104.0, 108.0, 130.0, 138.0]
    tdm = sh.stretches(sh.events(kills=kills, deaths=[], reactions=[], kill_weight=sh.RESPAWN_KILL),
                       speech=[], cluster_gap=sh.RESPAWN_GAP)
    comp = sh.stretches(sh.events(kills=kills, deaths=[], reactions=[]), speech=[])
    # 130 and 138 are one fight in a round-based match, two in a deathmatch
    assert [len(s.events) for s in comp] == [3, 2]
    assert [len(s.events) for s in tdm] == [3, 1, 1]
    assert tdm[0].score < comp[0].score


def test_the_session_takes_the_strongest_matches_and_one_deathmatch_at_most():
    found = {0: (False, 35.6), 1: (True, 30.0), 2: (False, 17.8), 3: (False, 19.0),
             4: (False, 22.6), 5: (True, 52.7), 6: (False, 37.5), 7: (False, 31.9)}
    # the 52.7 deathmatch beats the weakest of the best three round-based matches
    assert sh.choose_matches(found) == [0, 5, 6]
    found[5] = (True, 20.0)
    assert sh.choose_matches(found) == [0, 6, 7]
    assert sh.choose_matches({1: (True, 9.0)}) == [1]


def test_a_match_only_owns_what_happened_in_it():
    m = sh.Match(kills=[500.0], span=(400.0, 900.0))
    assert m.holds(400.0 - sh.SPAN_BEFORE, 410.0)
    assert not m.holds(5000.0, 5003.0)
    assert sh.Match(kills=[]).holds(0.0, 1e9)


def test_a_session_video_names_each_match_once_and_a_single_match_never():
    def match(n, t, label):
        # two 3Ks in one round: strong enough for a session (MATCH_FLOOR)
        ks = [t, t + 1, t + 2, t + 40, t + 41, t + 42]
        r = {"number": 1, "start": t - 20, "end": t + 50, "plant": None, "last_stand": None, "final": True,
             "contacts": ks}
        return sh.Match(kills=ks, rounds=[r], label=label, span=(t - 30, t + 60))
    ms = [match(1, 1000.0, "MATCH 1"), match(2, 5000.0, "MATCH 2")]
    cuts, chosen, owner = sh.plan_session(ms, reactions=[], speech=[])
    assert [c.caption for c in cuts if c.caption] == ["MATCH 1", "MATCH 2"]
    assert cuts[0].kind == "cold" and not cuts[0].caption
    cuts, _, _ = sh.plan_session(ms[:1], reactions=[], speech=[])
    assert not any(c.caption for c in cuts)


def test_the_lower_third_and_the_end_screen_draw():
    img = sh.lower_third("MATCH 3 · COMPETITIVE · BIND · CYPHER", (960, 540))
    assert img.size == (960, 540) and img.mode == "RGBA"
    box = img.getbbox()
    assert box and box[1] >= 540 * 0.75 and box[0] >= 960 * 0.25        # beside the facecam, low
    end = sh.end_screen("Somebody", None, (960, 540), game="Valorant")
    assert end.size == (960, 540) and end.mode == "RGB"


def test_the_job_cuts_the_session_from_the_match_records(tmp_path, monkeypatch):
    """jobs._cut_match: every match the record found is offered, the matches are
    labelled, the end screen gets the channel, and the manifest names what was kept."""
    import json

    from autostream.clips import jobs, reactions as react

    job = jobs.ClipJob.__new__(jobs.ClipJob)
    job.source = tmp_path / "rec.mp4"
    job.game = "VALORANT"
    job.options = {"channel": "Somebody"}
    job.session = {"started": 1_761_400_000}
    job.started_at = 0.0
    job.folder = tmp_path / "run"
    job.win_whole, job.win_start, job.win_end = True, 0.0, 10_000.0
    job.reactions_found = []
    job._set = lambda **kw: None

    def record(t, mode, map_name, won):
        ks = [t, t + 1, t + 2, t + 40, t + 41, t + 42]
        times = [{"number": 1, "start": t - 20, "end": t + 50, "plant": None, "last_stand": None,
                  "final": True, "contacts": ks}]
        return {"kills": [{"time": k} for k in ks], "rounds": [], "times": times, "deaths": [],
                "span": (t - 30, t + 60),
                "about": {"mode": mode, "map": map_name, "agent": "Cypher", "story": {"won": won}}}
    job.record_matches = [record(1000.0, "competitive", "Bind", [True] * 13),
                          record(5000.0, "competitive", "Sunset", [False] * 13)]
    monkeypatch.setattr(react, "tracks", lambda src: 0)
    seen = {}

    def fake_render(source, cuts, out, **kw):
        seen.update(kw, cuts=cuts)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"")
        return out
    monkeypatch.setattr(sh, "render", fake_render)
    out = job._cut_match([], {"duration": 10_000.0}, "auto")
    assert out and "_highlights_2matches_" in out
    assert seen["channel"] == "Somebody" and seen["game"] == "VALORANT"
    assert [c.caption for c in seen["cuts"] if c.caption] == [
        "MATCH 1 · COMPETITIVE · BIND · CYPHER", "MATCH 2 · COMPETITIVE · SUNSET · CYPHER"]
    manifest = json.loads((tmp_path / "run" / "match" / (out.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]))
                          .with_suffix(".json").read_text(encoding="utf-8"))
    assert manifest["matches"] == ["MATCH 1 · COMPETITIVE · BIND · CYPHER",
                                   "MATCH 2 · COMPETITIVE · SUNSET · CYPHER"]
    assert all(n.startswith("Match ") for _, n in manifest["chapters"])


R7 = {"number": 7, "start": 281.4, "end": 373.9, "plant": 328.9, "last_stand": 359.2, "final": False,
      "contacts": [296.0, 303.1, 307.1, 310.8, 317.0, 341.4, 356.0, 359.2, 366.7], "won": True, "score": (3, 4)}


def shaped(stretch, r, speech, next_start=None):
    stretch.cuts = [(stretch.start, stretch.end)]
    return sh.shape(stretch, r, speech, next_start)


def test_after_the_player_dies_their_talk_is_the_cam_and_the_round_ends_on_its_banner():
    s = sh.Stretch(start=698.9, end=722.6, score=9, round=10,
                   events=[sh.Event(704.9, "kill", 1), sh.Event(711.6, "death", 0.3)])
    r = dict(R10, won=False, score=(4, 6))
    got = shaped(s, r, speech=[(712.0, 720.0)])
    d = 711.6 + sh.CAM_AFTER_DEATH
    assert got[0] == (698.9, d, "game")
    # talk after the death is the cam, interrupted by the game's own banner
    assert (d, 716.9 + sh.RESULT_IN, "cam") in got
    assert (716.9 + sh.RESULT_IN, 716.9 + sh.RESULT_OUT, "result") in got
    # silent after the death: straight from the death to the banner
    got = shaped(s, r, speech=[])
    assert [lay for _, _, lay in got] == ["game", "result"]


def test_a_round_already_shown_to_its_end_gets_no_second_banner():
    s = sh.Stretch(start=355.0, end=373.9 + 4.0, score=5, round=7, events=[sh.Event(366.7, "kill", 1)])
    assert [lay for _, _, lay in shaped(s, R7, speech=[])] == ["game"]


def test_buy_phase_talk_is_the_cam_and_the_last_round_keeps_the_game():
    s = sh.Stretch(start=1305.0, end=1385.8, score=6, round=17, events=[sh.Event(1350.0, "kill", 1)])
    r17 = {"number": 17, "start": 1334.2, "end": 1367.5, "plant": None, "last_stand": None,
           "final": True, "contacts": [1350.0]}
    got = shaped(s, r17, speech=[(1310.0, 1330.0)])
    assert got[0] == (1310.0, 1330.0, "cam")
    assert got[-1][2] == "game" and got[-1][1] == 1385.8


def test_the_result_line_reads_like_the_scoreboard():
    assert sh.result_line(R7) == "ROUND 7 · WON · 3-4"
    assert sh.result_line({"number": 1}) == ""


def test_cuts_move_to_the_edges_of_sentences_but_not_the_banner():
    from autostream.clips.speech import Line
    cuts = [sh.Cut(100.0, 120.0, stretch=0), sh.Cut(130.0, 132.5, stretch=0, layout="result")]
    got = sh.snap(cuts, [Line(97.0, 101.0, "a"), Line(118.0, 123.0, "b"), Line(129.0, 131.0, "c")])
    assert (got[0].start, got[0].end) == (97.0 - 0.15, 123.0 + 0.25)
    assert (got[1].start, got[1].end) == (130.0, 132.5)
    # a sentence more than SNAP away is left alone
    far = sh.snap([sh.Cut(100.0, 120.0)], [Line(80.0, 101.0, "x")])
    assert far[0].start == 100.0


def test_the_cam_layout_pushes_in_on_the_marked_box():
    z, x, y = sh.cam_zoom([0.0122, 0.5851, 0.2514, 0.2795], 10.0)
    # the facecam fills the frame with CAM_PAD to spare: 1 / (0.2795 * 1.12)
    assert z.startswith("1+2.1945*(")
    assert "0.13790*iw" in x and "0.72485*ih" in y          # centred on the box
    assert "clip(" in x and "iw-iw/zoom" in x                # never past the frame's edge


def test_no_transcriber_means_none_not_a_failure(monkeypatch):
    from autostream.clips import speech
    monkeypatch.setattr(speech, "models", lambda: None)
    assert speech.available() is False
    assert speech.transcribe("x.mp4", [(0.0, 10.0)]) is None
    assert speech.language("x.mp4", [(0.0, 10.0)]) is None
    assert speech.fast() is False


def test_the_large_pair_when_both_are_on_disk_else_small_for_both(monkeypatch):
    from autostream.clips import speech
    import types, sys
    monkeypatch.setitem(sys.modules, "faster_whisper", types.ModuleType("faster_whisper"))
    monkeypatch.setattr(speech, "_on_disk", lambda name: True)
    assert speech.models() == ("large-v3-turbo", "large-v3")
    monkeypatch.setattr(speech, "_on_disk", lambda name: name == "small")
    assert speech.models() == ("small", "small")
    monkeypatch.setattr(speech, "_on_disk", lambda name: False)
    assert speech.models() is None


def test_each_sentence_takes_the_english_that_overlaps_it_most(monkeypatch):
    from autostream.clips import speech
    import numpy as np
    monkeypatch.setattr(speech, "models", lambda: ("turbo", "large"))
    monkeypatch.setattr(speech, "_model", lambda name: name)
    monkeypatch.setattr(speech, "_audio", lambda *a: np.zeros(speech.RATE * 10, dtype=np.float32))

    def run(model, audio, *, lang, task):
        assert lang == "hi"
        if task == "transcribe":
            return [(0.0, 3.0, "pehla"), (3.5, 8.0, "doosra")]
        return [(0.2, 4.0, "first"), (4.0, 7.9, "second")]
    monkeypatch.setattr(speech, "_run", run)
    got = speech.transcribe("x.mp4", [(100.0, 110.0)], lang="hi")
    assert [(ln.start, ln.text, ln.english) for ln in got] == [(100.0, "pehla", "first"), (103.5, "doosra", "second")]


def test_a_team_mates_fight_after_the_death_stays_on_the_game():
    s = sh.Stretch(start=698.9, end=722.6, score=9, round=10,
                   events=[sh.Event(704.9, "kill", 1), sh.Event(711.6, "death", 0.3)])
    r = dict(R10, contacts=R10["contacts"] + [716.0], won=False, score=(4, 6))
    got = shaped(s, r, speech=[(712.0, 730.0)])
    # 716.0 is a team-mate's kill: the game from HOLD_BEFORE_CONTACT before it
    assert any(lay == "game" and a <= 715.0 and b >= 717.0 for a, b, lay in got)
    assert any(lay == "cam" for _, _, lay in got)


def test_two_stretches_of_one_round_end_on_one_banner_in_order():
    a = sh.Stretch(start=285.8, end=317.9, score=5, round=7, shaped=[(285.8, 317.9, "game"), (374.7, 377.2, "result")])
    b = sh.Stretch(start=333.5, end=389.2, score=5, round=7, shaped=[(333.5, 369.2, "game"), (374.7, 377.2, "result")])
    cuts = sh._cuts([a, b], cold_open=False)
    assert [c.start for c in cuts] == sorted(c.start for c in cuts)
    assert sum(c.layout == "result" for c in cuts) == 1


def test_a_sentence_never_runs_over_the_rounds_banner():
    from autostream.clips.speech import Line
    cuts = [sh.Cut(698.9, 714.1, stretch=0), sh.Cut(714.1, 717.7, stretch=0, layout="cam"),
            sh.Cut(717.7, 720.2, stretch=0, layout="result")]
    got = sh.snap(cuts, [Line(715.0, 723.2, "talk")])
    assert [c.layout for c in got] == ["game", "cam", "result"]
    assert got[1].end == 717.7 and (got[2].start, got[2].end) == (717.7, 720.2)


def test_a_team_mates_clutch_is_a_stretch_of_its_own_and_always_kept():
    r22 = {"number": 22, "start": 1789.6, "end": 1858.1, "plant": 1816.3, "last_stand": None,
           "mate_clutch": 1825.0, "final": False, "won": True, "score": (10, 12),
           "contacts": [1801.1, 1807.4, 1824.6, 1825.0, 1835.0, 1843.0, 1846.0, 1850.0]}
    evs = sh.events(kills=[], deaths=[1807.4], reactions=[], rounds=[r22])
    sts = sh.stretches(evs, speech=[], rounds=[r22])
    clutch = next(s for s in sts if any(e.kind == "clutch" for e in s.events))
    # from the fight that left the team-mate alone, to the round's result
    assert clutch.start <= 1825.0 - sh.STATE_SETUP and clutch.end >= 1858.1 + sh.RESULT_HOLD
    assert clutch.why == "Team-mate clutch"
    assert sh.must_show(clutch)
    # kept even when the budget has no room for it
    assert clutch in sh.select(sts, budget=1.0)


def test_no_kill_is_ever_budgeted_out():
    a = sh.Stretch(start=0, end=200, score=50.0, round=3, events=[sh.Event(100, "reaction", 9)])
    b = sh.Stretch(start=300, end=330, score=1.0, round=5, events=[sh.Event(310, "kill", 1)])
    assert sh.select([a, b], budget=150) == [b]


def test_a_lone_kill_with_nothing_said_is_a_quick_look():
    s = sh.stretches(sh.events(kills=[500.0], deaths=[], reactions=[]), speech=[])[0]
    assert (s.start, s.end) == (500.0 - sh.SINGLE_LEAD, 500.0 + sh.SINGLE_TAIL)
