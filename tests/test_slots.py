"""Shots as slots: replace or remove one shot and no other kill moves on the song.

Step 2 of the guide plan agreed with ChatGPT (2026-10-24). Before it, Remove laid every later
kill back one hit along and Replace re-laid every mark, so taking out one weak clip moved the
whole reel. The proof is arithmetic on a real Build and drop plan: every kill but the one
edited stays on the same song second, and nothing leaves a black gap.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips import director, slots, studio                    # noqa: E402

from test_director import clip, library, song                           # noqa: E402


def reel(seed=3):
    shape, r = song()
    lib = library()
    p = director.plan(lib, shape, r, seed=seed)
    proj = {"shots": p.shots, "song_offset": p.part[0], "song_drop": p.drop, "beat": shape.beat,
            "build_clip": "C:/clips/clutch.mp4"}
    return proj, lib


def spares(proj, lib):
    used = {s["clip"] for s in proj["shots"]}
    return [c for c in lib if c["path"] not in used]


def length(proj):
    return sum(float(s["duration"]) for s in proj["shots"])


def flurry(proj):
    take = slots.take_shots(proj)
    return [i for i in range(len(proj["shots"])) if i not in take]


def test_the_take_is_found_and_the_rest_are_slots():
    proj, _ = reel()
    take = slots.take_shots(proj)
    assert take == [0, 1, 2] and all(proj["shots"][i]["clip"].endswith("clutch.mp4") for i in take)


def test_replace_offers_only_clips_that_land_on_the_same_beat_and_no_other_kill_moves():
    proj, lib = reel()
    i = flurry(proj)[4]
    before = slots.song_kills(proj)
    got = slots.options(proj, i, spares(proj, lib))
    assert got["clips"] and not got["take"]
    need_b, need_a = got["slot"]["before"], got["slot"]["after"]
    rows = {c["path"]: c for c in lib}
    for c in got["clips"]:
        assert slots.fits(rows[c["clip"]], c["kill"], need_b, need_a)
    assert [c["score"] for c in got["clips"]] == sorted((c["score"] for c in got["clips"]), reverse=True)
    new = slots.replace(proj, i, rows[got["clips"][0]["clip"]])
    after = slots.song_kills(new)
    assert after == before                                  # every kill, the replaced one too, on its second
    assert new["shots"][i]["clip"] == got["clips"][0]["clip"]
    assert length(new) == pytest.approx(length(proj))
    assert slots._footage_ok(new["shots"][i])


def test_a_clip_without_the_footage_or_with_another_kill_in_the_window_is_not_offered():
    proj, lib = reel()
    i = flurry(proj)[4]
    b, a = slots.need(proj["shots"][i])
    short = clip("short", [0.05])                           # no run-up at all
    crowded = clip("crowded", [3.5, 3.5 + a / 2])           # a second kill inside the shot, off its beat
    fine = clip("fine", [3.5])
    got = slots.options(proj, i, [short, crowded, fine])
    assert [c["name"] for c in got["clips"]] == ["fine"]
    with pytest.raises(slots.SlotError):
        slots.replace(proj, i, short)
    # a clip already in the reel plays in one place only
    inside = next(c for c in lib if c["path"] == proj["shots"][i + 1]["clip"])
    assert inside["path"] not in [c["clip"] for c in slots.options(proj, i, [inside])["clips"]]


def test_nothing_fits_is_said_in_words():
    proj, _ = reel()
    got = slots.options(proj, flurry(proj)[2], [clip("short", [0.05])])
    assert not got["clips"] and "footage" in got["why"]


def test_close_the_gap_keeps_every_other_kill_and_leaves_no_hole():
    proj, lib = reel()
    kills = {c["path"].lower(): c["kills"] for c in lib}
    for i in flurry(proj)[1:-1]:
        before = slots.song_kills(proj)
        try:
            new = slots.close(proj, i, kills)
        except slots.SlotError as e:
            assert "gap" in str(e) or "footage" in str(e)
            continue
        after = slots.song_kills(new)
        assert len(new["shots"]) == len(proj["shots"]) - 1
        assert slots.moved([t for j, t in enumerate(before) if j != i], after) == []
        # no hole: the reel is as long as it was, every shot within its footage
        assert length(new) == pytest.approx(length(proj), abs=1e-3)
        assert all(slots._footage_ok(s) for s in new["shots"])
        break
    else:
        pytest.fail("no shot of this reel could be closed over")


def test_closing_over_the_first_shot_starts_the_reel_later_and_moves_nothing():
    proj = {"shots": [studio_shot("a", 2.0, 0.6, 1.0), studio_shot("b", 2.0, 0.5, 1.0), studio_shot("c", 2.0, 0.5, 1.0)],
            "song_offset": 10.0}
    before = slots.song_kills(proj)
    new = slots.close(proj, 0)
    assert slots.song_kills(new) == before[1:]
    assert new["song_offset"] > 10.0 or new["shots"][0]["pre"] > 0.5


def test_a_gap_too_big_to_close_says_so_and_changes_nothing():
    tight = [studio_shot("a", 1.3, 0.5, 1.0, secs=1.32), studio_shot("b", 9.0, 0.5, 4.0),
             studio_shot("c", 0.52, 0.5, 1.0, secs=1.6)]
    proj = {"shots": tight, "song_offset": 0.0}
    with pytest.raises(slots.SlotError) as e:
        slots.close(proj, 1)
    assert "not enough" in str(e.value) or "footage" in str(e.value)
    assert proj["shots"][1]["name"] == "b"                  # untouched


def test_the_build_is_swapped_only_for_a_take_that_lands_on_the_drop():
    proj, lib = reel()
    take = slots.take_shots(proj)
    drop_before = slots.song_kills(proj)[take[-1]]
    rest_before = slots.song_kills(proj)[len(take):]
    other = clip("ace", [2.0, 3.0, 4.0, 5.0, 6.0], labels=["ACE"], seconds=12.0)
    lone = clip("lone", [3.5])
    got = slots.options(proj, take[0], spares(proj, lib) + [other, lone])
    assert got["take"] and [c["name"] for c in got["clips"]][0] == "ace"
    assert "lone" not in [c["name"] for c in got["clips"]]
    new = slots.swap_take(proj, other)
    nt = slots.take_shots(new)
    assert all(new["shots"][j]["clip"] == other["path"] for j in nt)
    assert slots.song_kills(new)[nt[-1]] == pytest.approx(drop_before, abs=1e-3)   # still ON the drop
    assert slots.song_kills(new)[len(nt):] == pytest.approx(rest_before, abs=1e-3)  # nothing after it moves
    with pytest.raises(slots.SlotError):
        slots.replace(proj, take[0], lone)
    with pytest.raises(slots.SlotError):
        slots.close(proj, take[1])


def test_ending_before_a_shot_ends_on_the_beat_and_keeps_what_came_before():
    proj, _ = reel()
    i = flurry(proj)[6]
    before = slots.song_kills(proj)
    new = slots.shorten(proj, i)
    assert len(new["shots"]) == i and slots.song_kills(new) == before[:i]
    last = new["shots"][-1]
    assert float(last["duration"]) - float(last["pre"]) >= min(studio.OUTRO_AFTER_KILL, 0.0) - 1e-6
    with pytest.raises(slots.SlotError):
        slots.shorten(proj, slots.take_shots(proj)[-1])


def studio_shot(name, secs_kill, pre, dur, secs=12.0):
    return {"clip": f"C:/clips/{name}.mp4", "name": name, "clip_seconds": secs, "kill": secs_kill,
            "kills": [secs_kill], "pre": pre, "duration": dur, "speed": "s00", "fx": []}


def test_the_endpoint_offers_applies_and_counts_what_moved(monkeypatch, tmp_path):
    """/api/studio/slot: the page's project, normalised; every answer says how many other kills moved."""
    from types import SimpleNamespace

    from autostream import webui

    proj, lib = reel()
    for c in lib:
        p = tmp_path / Path(c["path"]).name
        p.write_bytes(b"x")
        old = c["path"]
        c["path"] = str(p)
        for s in proj["shots"]:
            if s["clip"] == old:
                s["clip"] = str(p)
        if proj["build_clip"] == old:
            proj["build_clip"] = str(p)
    srv = webui.Server.__new__(webui.Server)
    monkeypatch.setattr(webui.cfg, "load", lambda: SimpleNamespace())
    monkeypatch.setattr(webui.Server, "_clips_dir", staticmethod(lambda c: tmp_path))
    monkeypatch.setattr(studio, "library", lambda root: {"games": [{"game": "VALORANT", "folders": [{"clips": lib}]}]})
    real = studio.normalise
    monkeypatch.setattr(studio, "normalise", lambda p, root, probe=None: real(p, root, probe=lambda x: 12.0))
    i = flurry(proj)[4]
    got = srv.studio_slot({"project": proj, "shot": i, "do": "options"})
    assert got["ok"] and got["clips"], got
    used = srv.studio_slot({"project": proj, "shot": i, "do": "replace", "clip": got["clips"][0]["clip"]})
    assert used["ok"] and used["moved"] == 0, used.get("error")
    assert used["project"]["shots"][i]["clip"] == got["clips"][0]["clip"]
    filled = srv.studio_slot({"project": proj, "shot": i, "do": "fill"})
    assert filled["ok"] and filled["moved"] == 0
    closed = srv.studio_slot({"project": proj, "shot": i, "do": "close"})
    assert closed["ok"] is False or closed["moved"] == 0
    refused = srv.studio_slot({"project": proj, "shot": i, "do": "replace", "clip": "C:/elsewhere/x.mp4"})
    assert refused["ok"] is False and "clips folder" in refused["error"]


# ------------------------------------------------------------------ exchange and every game's clips

def test_exchange_trades_two_clips_and_keeps_every_kill_on_its_second():
    """Clips swap, slots stay: each clip's kill lands on the other's beat; nothing else moves."""
    proj, lib = reel()
    rows = {c["path"].lower(): c for c in lib}
    fl = flurry(proj)
    i, j = fl[1], fl[5]
    before = slots.song_kills(proj)
    a, b = proj["shots"][i], proj["shots"][j]
    new = slots.exchange(proj, i, j, rows)
    assert slots.song_kills(new) == before
    assert new["shots"][i]["clip"] == b["clip"] and new["shots"][j]["clip"] == a["clip"]
    for k in ("pre", "duration", "speed", "fx", "transition"):         # the slot is the slot's
        assert new["shots"][i].get(k) == a.get(k) and new["shots"][j].get(k) == b.get(k)
    assert all(slots._footage_ok(s) for s in new["shots"])
    assert length(new) == pytest.approx(length(proj))
    assert proj["shots"][i]["clip"] == a["clip"]                       # the input is not touched


def test_exchange_options_list_every_other_shot_and_say_why_one_cannot_trade():
    proj, lib = reel()
    rows = {c["path"].lower(): c for c in lib}
    i = flurry(proj)[2]
    # a shot whose clip has no run-up at all cannot take shot i's place
    j = flurry(proj)[6]
    proj["shots"][j] = dict(proj["shots"][j], clip="C:/clips/bare.mp4", name="bare", kill=0.05, kills=[0.05],
                            pre=0.0, clip_seconds=2.0)
    rows["c:/clips/bare.mp4"] = clip("bare", [0.05], seconds=2.0)
    got = slots.exchange_options(proj, i, rows)
    shots = [w["shot"] for w in got["swaps"]]
    take = slots.take_shots(proj)
    assert i not in shots and not set(take) & set(shots)
    assert any(w["ok"] for w in got["swaps"])
    bare = next(w for w in got["swaps"] if w["shot"] == j)
    assert not bare["ok"] and "bare" in bare["why"] and "before its kill" in bare["why"]
    with pytest.raises(slots.SlotError) as e:
        slots.exchange(proj, i, j, rows)
    assert "before its kill" in str(e.value)


def test_the_build_take_is_never_exchanged_and_says_why():
    proj, lib = reel()
    rows = {c["path"].lower(): c for c in lib}
    take = slots.take_shots(proj)
    got = slots.exchange_options(proj, take[0], rows)
    assert got["swaps"] == [] and "take" in got["why"]
    with pytest.raises(slots.SlotError) as e:
        slots.exchange(proj, flurry(proj)[0], take[1], rows)
    assert "take" in str(e.value)


def test_exchange_falls_back_on_what_the_shot_knows_when_its_clip_is_not_in_the_library():
    proj, _ = reel()
    fl = flurry(proj)
    before = slots.song_kills(proj)
    new = slots.exchange(proj, fl[0], fl[3], {})
    assert slots.song_kills(new) == before
    assert new["shots"][fl[0]]["clip"] == proj["shots"][fl[3]]["clip"]


def test_options_offer_every_game_own_game_first_and_the_misfits_with_reasons():
    proj, lib = reel()
    i = flurry(proj)[4]
    b, a = slots.need(proj["shots"][i])
    rows = [dict(c, game="VALORANT") for c in spares(proj, lib)]
    cs2 = dict(clip("cs2-one", [3.5]), game="Counter-Strike 2")
    short = dict(clip("short", [0.05]), game="Counter-Strike 2")
    crowded = dict(clip("crowded", [3.5, 3.5 + a / 2]), game="VALORANT")
    got = slots.options(proj, i, rows + [cs2, short, crowded], limit=None, games={"VALORANT"})
    names = [c["name"] for c in got["clips"]]
    assert "cs2-one" in names                                          # any game is offered
    # at an equal score the reel's own game comes first
    sc = next(c["score"] for c in got["clips"] if c["name"] == "cs2-one")
    same = [c for c in got["clips"] if c["score"] == sc]
    assert same[-1]["name"] == "cs2-one" and all(c["own"] for c in same[:-1])
    others = {c["name"]: c for c in got["others"]}
    assert set(others) == {"short", "crowded"}
    assert "before its kill" in others["short"]["why"]
    assert "another kill" in others["crowded"]["why"]
    # never offered: using one would break the beat
    with pytest.raises(slots.SlotError):
        slots.replace(proj, i, short)


def test_the_endpoint_exchanges_and_fill_stays_in_the_reels_game(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from autostream import webui

    proj, lib = reel()
    for c in lib:
        p = tmp_path / Path(c["path"]).name
        p.write_bytes(b"x")
        old = c["path"]
        c["path"] = str(p)
        for s in proj["shots"]:
            if s["clip"] == old:
                s["clip"] = str(p)
        if proj["build_clip"] == old:
            proj["build_clip"] = str(p)
    # a better clip in another game's folder: offered first, but not what "fill" picks for the player
    star = clip("star", [3.5], labels=["CLOSER"])
    star["path"] = str(tmp_path / "star.mp4")
    (tmp_path / "star.mp4").write_bytes(b"x")
    srv = webui.Server.__new__(webui.Server)
    monkeypatch.setattr(webui.cfg, "load", lambda: SimpleNamespace())
    monkeypatch.setattr(webui.Server, "_clips_dir", staticmethod(lambda c: tmp_path))
    monkeypatch.setattr(studio, "library", lambda root: {"games": [
        {"game": "VALORANT", "folders": [{"clips": lib}]},
        {"game": "Counter-Strike 2", "folders": [{"clips": [star]}]}]})
    real = studio.normalise
    monkeypatch.setattr(studio, "normalise", lambda p, root, probe=None: real(p, root, probe=lambda x: 12.0))
    fl = flurry(proj)
    i, j = fl[1], fl[5]
    got = srv.studio_slot({"project": proj, "shot": i, "do": "options"})
    assert got["ok"] and got["swaps"] and "others" in got
    assert got["clips"][0]["name"] == "star" and got["clips"][0]["game"] == "Counter-Strike 2"
    assert any(w["shot"] == j and w["ok"] for w in got["swaps"])
    swapped = srv.studio_slot({"project": proj, "shot": i, "do": "exchange", "with": j})
    assert swapped["ok"] and swapped["moved"] == 0, swapped.get("error")
    assert swapped["project"]["shots"][i]["clip"] == proj["shots"][j]["clip"]
    assert swapped["project"]["shots"][j]["clip"] == proj["shots"][i]["clip"]
    filled = srv.studio_slot({"project": proj, "shot": i, "do": "fill"})
    assert filled["ok"] and filled["project"]["shots"][i]["clip"] != star["path"]
    used = srv.studio_slot({"project": proj, "shot": i, "do": "replace", "clip": star["path"]})
    assert used["ok"] and used["moved"] == 0 and used["project"]["shots"][i]["clip"] == star["path"]
    nowith = srv.studio_slot({"project": proj, "shot": i, "do": "exchange"})
    assert nowith["ok"] is False
