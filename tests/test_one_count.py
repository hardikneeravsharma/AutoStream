"""ONE COUNT: the chip, the clip counter and "Add N more" all read the plan's own shortfall.

JUST A BOY, 2026-10-24: three parts of the page each estimated how many clips a reel
needed -- the counter (a two-kill clip as two), the chip (missing seconds over a kill's
length) and "Add the best" (the counter's number, already met) -- and the player saw
"50 of 41", "about 13 more" and a button that added nothing. These run the real planners
on clips shaped like that machine's: most two-kill clips have their kills seconds apart,
so each plays once. What the chip asks for must be what the plan is short, and the fix
must add exactly that or say why it cannot.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import webui                                            # noqa: E402
from autostream.clips import rhythm, studio                             # noqa: E402

from test_director import clip, song, DROP                              # noqa: E402


def realistic(n_far=40, n_single=20, n_run=3):
    """A clutch to build on, then what a real library holds: two-kill clips whose kills are
    2-20 s apart (one quick kill each), lone kills, and a few real runs."""
    out = [clip("clutch", [3.5, 5.0, 7.2], labels=["CLUTCH 1v3"], seconds=12.0)]
    out += [clip(f"far{i}", [3.5, 3.5 + 2.0 + (i % 10) * 1.8], seconds=26.0) for i in range(n_far)]
    out += [clip(f"one{i}", [3.5], hs=[i % 3 != 0]) for i in range(n_single)]
    out += [clip(f"run{i}", [3.5, 4.2 + 0.1 * i]) for i in range(n_run)]
    return out


@pytest.fixture
def srv(monkeypatch, tmp_path):
    shape, r = song()
    lib = realistic()
    for c in lib:
        p = tmp_path / Path(c["path"]).name
        p.write_bytes(b"x")
        c["path"] = str(p)
    shape.path = tmp_path / "song.m4a"
    shape.path.write_bytes(b"x")
    by = {c["path"]: c for c in lib}
    s = webui.Server.__new__(webui.Server)
    monkeypatch.setattr(webui.cfg, "load", lambda: SimpleNamespace(clips=SimpleNamespace(ffmpeg_path=None)))
    monkeypatch.setattr(webui.Server, "_clips_dir", staticmethod(lambda c: tmp_path))
    monkeypatch.setattr(s, "_studio_shape", lambda song: shape, raising=False)
    monkeypatch.setattr(s, "_studio_chosen", lambda root, want: [dict(by[p]) for p in want if p in by],
                        raising=False)
    monkeypatch.setattr(rhythm, "for_song", lambda sh, cache_dir=None: r)
    real = studio.normalise
    monkeypatch.setattr(studio, "normalise", lambda p, root, probe=None: real(p, root, probe=lambda x: 26.0))
    s.lib = lib
    s.song = str(shape.path)
    return s


def body(srv, style, chosen, part=(DROP - 14.0, DROP + 16.0)):
    b = {"style": style, "song": srv.song, "clips": [c["path"] for c in chosen], "format": "vertical",
         "part_start": part[0], "part_end": part[1],
         "shaping": {"arrange": "build", "part_auto": True, "fill": ""}}
    if style == "drop":
        b["shaping"]["build_clip"] = srv.lib[0]["path"]
    return b


def quick(srv):
    return [c for c in srv.lib[1:]]


STYLES = [s.key for s in studio.STYLES]
SHORT = {"fasthead": 10}            # its planner will not start on fewer than eight headshots


def test_every_style_is_covered():
    assert set(STYLES) == {"drop", "montage", "hype", "clean", "cinematic", "chaos", "velocity", "fasthead"}


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("n", [6, 10, 16])
def test_the_chip_asks_for_exactly_what_the_plan_is_short(srv, style, n):
    chosen = ([srv.lib[0]] if style == "drop" else []) + quick(srv)[:max(n, SHORT.get(style, 0))]
    b = body(srv, style, chosen)
    plan = srv.studio_plan(dict(b, dry=True))
    v = srv.studio_feasible(b)["verdict"]
    missing = int(plan["fill"].get("missing") or 0)
    length = sum(s["duration"] for s in plan["project"]["shots"])
    if v["fix"] == "pick-clips":
        assert v["more"] == missing > 0, (v, plan["fill"])
        assert v["fix_label"] == f"Add {missing} more"
    else:
        # not short of clips: either full enough, or short for a reason clips cannot fix
        assert v["more"] == 0 and (v["level"] == "ok" or v["fix"] == "part:fit"), v
    # the counter's facts are the same plan's
    assert v["planned"] and v["used"] == len({s["clip"] for s in plan["project"]["shots"]})
    assert v["length"] == pytest.approx(length, abs=0.01)


@pytest.mark.parametrize("style", STYLES)
def test_add_n_more_adds_clips_the_plan_plays_until_it_is_full(srv, style):
    # as few clips as it takes for this style's plan to come up short
    for n in (SHORT.get(style, 6), 4, 3, 2):
        keep = ([srv.lib[0]] if style == "drop" else []) + quick(srv)[:n]
        b = body(srv, style, keep)
        v0 = srv.studio_feasible(b)["verdict"]
        if v0["fix"] == "pick-clips":
            break
    else:
        pytest.skip(f"{style} fills the part even with two clips: {v0['text']}")
    offered = [c["path"] for c in quick(srv)]
    got = srv.studio_fill(dict(b, candidates=offered))
    added = got["added"]
    assert added and set(added) <= set(offered) - set(b["clips"])
    after = srv.studio_feasible(dict(b, clips=b["clips"] + added, want_used=True))
    # every clip it added is one the plan plays: nothing is "added" that the reel cannot use
    assert set(added) <= set(after["used"])
    # and the reel is no longer short of clips -- or it says, in words, why it still is
    assert after["verdict"]["fix"] != "pick-clips" or got["why"], (v0, after["verdict"])
    # each far-apart pair and lone kill fills one hit, so what it added is what the chip asked for
    if after["verdict"]["fix"] != "pick-clips" and style == "drop":
        assert len(added) <= v0["more"]


def test_a_two_kill_clip_far_apart_is_one_clip_short_not_two(srv):
    """Most real two-kill clips have their kills seconds apart: the plan plays one of them, so
    adding one clip closes one hit, never two."""
    keep = [srv.lib[0]] + [c for c in quick(srv) if c["name"].startswith("far")][:8]
    b = body(srv, "drop", keep)
    v0 = srv.studio_feasible(b)["verdict"]
    one = next(c for c in quick(srv) if c["name"].startswith("far") and c not in keep)
    v1 = srv.studio_feasible(dict(b, clips=b["clips"] + [one["path"]]))["verdict"]
    assert v0["more"] - v1["more"] == 1, (v0, v1)


def test_when_no_clip_is_left_it_says_why_rather_than_adding_nothing(srv):
    keep = [srv.lib[0]] + quick(srv)[:6]
    b = body(srv, "drop", keep)
    got = srv.studio_fill(dict(b, candidates=[c["path"] for c in quick(srv)[6:9]]))
    assert len(got["added"]) <= 3
    assert got["verdict"]["fix"] == "pick-clips" and "Every other clip" in got["why"]


def test_pick_for_me_starts_from_nothing_and_stops_when_full(srv):
    b = body(srv, "montage", [])
    offered = [c["path"] for c in quick(srv)]
    got = srv.studio_fill(dict(b, candidates=offered))
    assert got["added"], got
    v = srv.studio_feasible(dict(b, clips=got["added"]))["verdict"]
    assert v["fix"] != "pick-clips", v
    assert len(got["added"]) < len(offered)          # it stopped when the plan was full
