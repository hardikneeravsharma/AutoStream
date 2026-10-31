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
