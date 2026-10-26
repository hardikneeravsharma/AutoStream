"""No effect whites out a kill, in any style (round 3's last rule).

The render gate only reported it (reelcheck, soft `kill-bright`); the planner now
turns the effect down. Which effects whiten is read off KILL_LIGHT -- measured by
scripts/measure_kill_light.py -- never off a list of names here. The one white-out
that is meant is the flash on the drop's kill, which goes on after the guard.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_build_and_drop as BD                                    # noqa: E402
import test_director as TD                                          # noqa: E402
from autostream.clips import rhythm, studio                         # noqa: E402
from test_general_planner_rules import _song, pile                  # noqa: E402,F401
from test_studio import _clips                                      # noqa: E402

ALL = [st.key for st in studio.STYLES]
WHITENING = [p.id for p in studio.PARTS if p.kind in ("kill", "hero") and studio._light(p.id) > studio.WHITE_CEIL]


def _left(proj, style: str) -> list:
    """Every shot whose own effects still white its kill out -- the drop's flash aside."""
    out = []
    for s in proj["shots"]:
        fx = list(s.get("fx") or [])
        if studio.STYLE[style].drop and fx and fx[-1] == studio.DROP_FLASH:
            fx = fx[:-1]
        if studio.kill_light(dict(s, fx=fx)) > studio.WHITE_CEIL:
            out.append((s.get("fx"), s.get("hero_fx")))
    return out


def test_the_table_finds_the_flashes_the_flickers_and_the_inversion():
    """What the measurement says whitens, by family: every one of the three kinds
    the gate's kill-bright has caught, and nothing that only moves or tints."""
    fams = {studio.fam(p) for p in WHITENING}
    assert fams == {"k03", "k16", "k12"}, fams
    for quiet in ("k01", "k02", "k06", "k07", "k08", "k14", "k15", "k17", "k18", "k19", "k20", "k21",
                  "k22", "h01", "h03"):
        assert studio._light(quiet) <= studio.WHITE_CEIL, quiet
    # the dim flash and every contrast crunch stay: measured under the ceiling
    assert studio._light("k03dim") <= studio.WHITE_CEIL and studio._light("k11hard") <= studio.WHITE_CEIL


@pytest.mark.parametrize("bpm", [90.0, 174.0])
@pytest.mark.parametrize("style", ALL)
def test_no_style_leaves_a_white_out_on_a_kill_on_the_general_planner(pile, style, bpm, tmp_path):
    song = tmp_path / "s.mp3"
    song.write_bytes(b"not really a song")
    for seed in range(4):
        proj, _notes = studio.plan(_clips(pile), style, shape=_song(bpm), song=str(song), fmt="vertical",
                                   seed=seed)
        assert not _left(proj, style), (style, seed, _left(proj, style))


@pytest.mark.parametrize("style", ALL)
def test_no_style_leaves_a_white_out_on_a_kill_through_its_own_director(style, tmp_path, monkeypatch):
    """Build and drop, Montage and Fast-paced headshot plan themselves (director,
    fasthead); the rule holds over their shots too -- the director's inversion included."""
    shape, r = TD.song()
    clips = TD.library()
    for c in clips:
        p = tmp_path / Path(c["path"]).name
        p.write_bytes(b"x")
        c["path"] = str(p)
    shape.path = tmp_path / "song.m4a"
    shape.path.write_bytes(b"x")
    monkeypatch.setattr(rhythm, "for_song", lambda sh, cache_dir=None: r)
    for seed in range(1, 6):
        proj, _notes = studio.plan(clips, style, shape=shape, song=str(shape.path), fmt="vertical", seed=seed)
        assert not _left(proj, style), (style, seed, _left(proj, style))


def test_a_directors_inversion_on_a_kill_is_turned_down(tmp_path, monkeypatch):
    """Planted: the director dealing the inversion on every kill after the drop."""
    from autostream.clips import director
    shape, r = TD.song()
    clips = TD.library()
    for c in clips:
        p = tmp_path / Path(c["path"]).name
        p.write_bytes(b"x")
        c["path"] = str(p)
    shape.path = tmp_path / "song.m4a"
    shape.path.write_bytes(b"x")
    monkeypatch.setattr(rhythm, "for_song", lambda sh, cache_dir=None: r)
    monkeypatch.setattr(director, "FX_CYCLE", (director.INVERT,))
    proj, notes = studio.plan(clips, "drop", shape=shape, song=str(shape.path), fmt="vertical", seed=1)
    assert not _left(proj, "drop")
    assert any("whited out" in n and "invert frame" in n for n in notes), notes


def test_without_the_rule_these_plans_do_white_kills_out(pile, tmp_path, monkeypatch):
    """The tests above are not vacuous: with the ceiling lifted and the guard off,
    Velocity's flicker and Hype's and Chaos's flashes land on kills."""
    song = tmp_path / "s.mp3"
    song.write_bytes(b"x")
    ceil = studio.WHITE_CEIL
    monkeypatch.setattr(studio, "WHITE_CEIL", 99.0)
    monkeypatch.setattr(studio, "no_whiteout", lambda *a, **k: [])
    for style in ("velocity", "hype", "chaos"):
        plans = [studio.plan(_clips(pile), style, shape=_song(bpm), song=str(song), fmt="vertical", seed=seed)[0]
                 for bpm in (90.0, 174.0) for seed in range(4)]
        assert any(studio.kill_light(s) > ceil for p in plans for s in p["shots"]), style


def test_the_drop_flash_survives(tmp_path):
    """The one white-out asked for by name: Build and drop's flash on the drop's kill."""
    root = tmp_path / "clips"
    BD.T._run(root, "2026-09-01_1200_VALORANT", "VALORANT",
              [{"start": 100.0 * i, "end": 100.0 * i + 12} for i in range(1, 31)],
              kills=[100.0 * i + 6 for i in range(1, 31)])
    song = tmp_path / "x.m4a"
    song.write_bytes(b"x")
    proj, notes = studio.plan(_clips(root), "drop", shape=BD._espresso_like(), song=str(song))
    flashed = [s for s in proj["shots"] if studio.DROP_FLASH in s["fx"]]
    assert len(flashed) == 1 and flashed[0]["fx"][-1] == studio.DROP_FLASH, [s["fx"] for s in proj["shots"]]
    assert any("flashes white" in n for n in notes), notes


def test_mix_again_keeps_the_drop_flash_and_turns_down_the_rest(tmp_path):
    root = tmp_path / "clips"
    BD.T._run(root, "2026-09-01_1200_VALORANT", "VALORANT",
              [{"start": 100.0 * i, "end": 100.0 * i + 12} for i in range(1, 31)],
              kills=[100.0 * i + 6 for i in range(1, 31)])
    song = tmp_path / "x.m4a"
    song.write_bytes(b"x")
    proj, _ = studio.plan(_clips(root), "drop", shape=BD._espresso_like(), song=str(song))
    i = next(n for n, s in enumerate(proj["shots"]) if studio.DROP_FLASH in s["fx"])
    studio.vary(proj, "transition", seed=7)
    assert proj["shots"][i]["fx"][-1] == studio.DROP_FLASH, "mixing the cuts leaves the drop's flash"
    # Mixing the kill effects from a pool full of flashes leaves none of them on a kill.
    proj["pools"] = dict(proj.get("pools") or {}, kill=["k01", "k16", "k03wide", "k02", "k12"])
    for seed in range(5):
        studio.vary(proj, "kill", seed=seed)
        assert not _left(proj, "drop"), (seed, [s["fx"] for s in proj["shots"]])


# ------------------------------------------------------------------ the guard itself

def _shot(fx, hero_fx=()):
    return {"clip": "a.mp4", "kill": 3.0, "kills": [3.0], "pre": 1.0, "duration": 2.0, "clip_seconds": 20.0,
            "speed": "s00", "fx": list(fx), "hero_fx": list(hero_fx), "camera": "c00"}


@pytest.mark.parametrize("bright", WHITENING)
def test_every_whitening_part_gives_way_to_one_the_reel_already_uses(bright):
    a, b, c = _shot(["k01"]), _shot([bright, "k02"]), _shot(["k06"])
    gone = studio.no_whiteout([a, b, c], {"kill": ["k01", "k02", "k06", bright]})
    assert gone == [bright]
    assert studio.kill_light(b) <= studio.WHITE_CEIL
    # the kill effect it already had is kept, and the swap is one the reel uses
    assert "k02" in b["fx"] and set(b["fx"]) <= {"k01", "k02", "k06"}
    assert studio.kill_detail(b) >= studio.SHARP_FLOOR


def test_a_stack_too_bright_together_loses_its_brightest_part():
    s = _shot(["k11hard", "k03dim"])
    assert studio.kill_light(s) > studio.WHITE_CEIL
    assert studio.no_whiteout([s], {"kill": ["k01"]}) == ["k11hard"]
    assert studio.kill_light(s) <= studio.WHITE_CEIL and "k03dim" in s["fx"]


def test_with_nothing_dark_to_swap_to_the_effect_is_dropped():
    s = _shot(["k16hard"])
    assert studio.no_whiteout([s], {"kill": []}) == ["k16hard"] and s["fx"] == []


def test_unrelated_effects_are_untouched():
    shots = [_shot(["k01"]), _shot(["k06", "k02"], ["h01"]), _shot(["k11hard"]), _shot(["k03dim"]),
             _shot(["k20"], ["h03"]), _shot([])]
    before = [(list(s["fx"]), list(s["hero_fx"])) for s in shots]
    assert studio.no_whiteout(shots, {"kill": ["k01", "k16"]}) == []
    assert [(s["fx"], s["hero_fx"]) for s in shots] == before


def test_a_drawer_the_player_chose_and_the_styles_signature_are_left_alone():
    s = _shot(["k03wide"])
    assert studio.no_whiteout([s], {"kill": ["k01"]}, free={"kill"}) == [] and s["fx"] == ["k03wide"]
    s = _shot(["k01", "k16"])
    assert studio.no_whiteout([s], {"kill": ["k01"]}, fixed={"k16"}) == [] and s["fx"] == ["k01", "k16"]


def test_the_plan_says_what_gave_way():
    note = studio.whiteout_note(["k16", "k12one"])
    assert "2 effect(s)" in note and "flicker" in note and "single negative" in note
