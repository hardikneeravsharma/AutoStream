"""The parts bin: a template is one pick per drawer, and every pick has an example.

No ffmpeg here -- building an example is measured in tests/verify; these pin
what the page is handed and what a template does to a plan.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from autostream.clips import examples, studio


@pytest.fixture
def root(tmp_path):
    (tmp_path / ".studio").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def stock(tmp_path, monkeypatch):
    """A stock set of our own, so these do not depend on what is checked in."""
    d = tmp_path / "stock"
    d.mkdir()
    monkeypatch.setattr(examples, "STOCK", d)
    return d


# ---------------------------------------------------------------- the store

def test_a_fresh_install_has_no_examples_and_says_which(root, stock):
    m = examples.manifest(root)
    assert m["ok"] and m["examples"] == {}
    parts = {p["id"] for p in studio.catalog()["parts"]}
    assert set(m["missing"]) | set(m["nothing"]) == parts
    # "nothing added" parts need no example: an example of no camera move is
    # an empty card.
    assert "i00" in m["nothing"] and "i00" not in m["missing"]


def test_an_example_is_found_by_its_part_id(root):
    f = examples.folder(root)
    f.mkdir(parents=True)
    (f / "k04.mp4").write_bytes(b"not really a video")
    assert examples.path_for(root, "k04") == f / "k04.mp4"
    m = examples.manifest(root)
    assert m["examples"]["k04"]["type"] == "video/mp4"
    assert m["examples"]["k04"]["bytes"] == 18
    assert "k04" not in m["missing"]


def test_a_new_user_sees_the_stock_example_until_they_cut_their_own(root, stock):
    (stock / "k04.mp4").write_bytes(b"stock")
    assert examples.path_for(root, "k04") == stock / "k04.mp4"
    m = examples.manifest(root)
    assert m["examples"]["k04"]["stock"] is True
    # Still missing: a stock card is not cut from their clips, and a rebuild
    # is what replaces it.
    assert "k04" in m["missing"]
    assert examples.path_for(root, "k04", stock=False) is None

    f = examples.folder(root)
    f.mkdir(parents=True)
    (f / "k04.mp4").write_bytes(b"theirs")
    assert examples.path_for(root, "k04") == f / "k04.mp4"
    m = examples.manifest(root)
    assert m["examples"]["k04"]["stock"] is False and "k04" not in m["missing"]


def test_a_stock_example_is_only_found_for_a_part_the_catalog_knows(root, stock):
    (stock / "nonsense.mp4").write_bytes(b"x")
    assert examples.path_for(root, "nonsense") is None


def test_the_shipped_stock_set_covers_every_part_there_is_something_to_show():
    """The point of shipping them: a new user's bin has no empty cards."""
    have = {f.stem for f in examples.STOCK.glob("*.mp4")}
    want = {p for p in examples.known() if p not in examples.NOTHING}
    assert want - have == set()


@pytest.mark.parametrize("asked", ["", "nonsense", "../../secrets/token",
                                   "k04/../../config.yaml", "K04"])
def test_only_a_part_the_catalog_knows_can_be_asked_for(root, asked):
    (examples.folder(root)).mkdir(parents=True)
    (examples.folder(root) / "k04.mp4").write_bytes(b"x")
    assert examples.path_for(root, asked) is None


def test_taking_examples_rendered_elsewhere_ignores_anything_else(root, tmp_path):
    src = tmp_path / "elsewhere"
    src.mkdir()
    for name in ("k04.gif", "t05.mp4", "nonsense.mp4", "k04.txt", "secrets.yaml"):
        (src / name).write_bytes(b"x")
    got = examples.take_from(root, src)
    assert got["ok"] and got["taken"] == ["k04", "t05"]
    assert sorted(p.name for p in examples.folder(root).iterdir()) == ["k04.gif", "t05.mp4"]


def test_a_gif_and_an_mp4_are_both_playable(root):
    f = examples.folder(root)
    f.mkdir(parents=True)
    (f / "c04.gif").write_bytes(b"x")
    assert examples.manifest(root)["examples"]["c04"]["type"] == "image/gif"


# ------------------------------------------------------------- the template

def test_a_style_is_already_a_template():
    for key, style in studio.STYLE.items():
        picks = studio.picks_of(style)
        assert set(picks) == set(studio.DRAWERS), key
        for kind, part in picks.items():
            assert part in studio.ids_of(kind), (key, kind, part)


def test_a_template_swaps_the_picks_and_nothing_else():
    base = studio.STYLE["story"]
    got = studio.templated(base, {"kill": "k04", "transition": "t05", "camera": "c04"})
    assert got.kill == ("k04",) and got.cuts == ("t05",)
    assert got.camera == "c04" and got.camera_pool == ("c04",)
    # untouched drawers keep the style's own
    assert got.intro == base.intro and got.outro == base.outro and got.grade == base.grade
    assert got.key == base.key


def test_a_picked_drawer_leads_but_is_not_emptied():
    """A kill effect is drawn once per SHOT. A pool of one put the same effect
    on all six kills of a montage, which no reference edit does."""
    base = studio.STYLE["montage"]
    got = studio.templated(base, {"kill": "k04", "transition": "t05", "hero": "h02"})
    for pool, pick, was in ((got.kill_pool, "k04", base.kill_pool),
                            (got.transition_pool, "t05", base.transition_pool),
                            (got.hero_pool, "h02", base.hero_pool)):
        assert pool[0] == pick
        assert pool.count(pick) >= 2, "the pick has to be the likeliest draw"
        assert len(set(pool)) >= 3, "_vary avoids the last two: fewer and it repeats"
        assert set(was) - {pick} <= set(pool), "the style's own parts stay behind it"
    # ...but a drawer drawn from ONCE for the whole reel is exactly the pick
    once = studio.templated(base, {"intro": "i08", "grade": "g08", "camera": "c04"})
    assert once.intro == "i08" and once.grade == "g08" and once.camera_pool == ("c04",)


def test_a_part_that_is_not_that_drawers_is_ignored():
    base = studio.STYLE["hype"]
    assert studio.templated(base, {"kill": "t05", "camera": "nonsense"}) is base
    assert studio.templated(base, {}) is base


def test_the_reel_is_built_from_the_template(root):
    """What the dealer deals is what the shots get."""
    from test_studio import Shape, _clips, _run          # the Studio's own fixtures

    r = root / "clips"
    _run(r, "2026-09-01_1200_VALORANT", "VALORANT",
         [{"start": 100.0 * i, "end": 100.0 * i + 12} for i in range(1, 25)],
         kills=[100.0 * i + 6 for i in range(1, 25)])
    picks = {"intro": "i08", "outro": "e05", "grade": "g08", "kill": "k06",
             "camera": "c04", "speed": "s02", "overlay": "o01"}
    # A fixed seed: the effect mix is seeded from the clip ids, which are
    # hashes of paths, and the paths are a new temp directory every run.
    proj, _notes = studio.plan(_clips(r), "story", shape=Shape(bpm=120.0), template=picks, seed=7)
    assert proj["intro"] == "i08" and proj["grade"] == "g08"
    assert proj["overlays"] == ["o01"]
    assert all(s["camera"] == "c04" for s in proj["shots"])
    fx = [s["fx"][0] for s in proj["shots"]]
    assert max(set(fx), key=fx.count) == "k06", f"the dealt kill should lead: {fx}"
    assert all(a != b for a, b in zip(fx, fx[1:])), f"two kills running share an effect: {fx}"
    # ...and the same clips without a template keep the style's own picks
    plain, _ = studio.plan(_clips(r), "story", shape=Shape(bpm=120.0), seed=7)
    assert plain["intro"] == studio.STYLE["story"].intro
    assert "k06" not in [s["fx"][0] for s in plain["shots"]]


def test_the_catalog_tells_the_page_the_drawers_and_each_styles_picks():
    cat = studio.catalog()
    assert cat["drawers"] == list(studio.DRAWERS)
    for s in cat["styles"]:
        assert set(s["picks"]) == set(studio.DRAWERS)
    # the page draws a card per part, so every part needs a label and a blurb
    for p in cat["parts"]:
        assert p["label"] and p["blurb"], p["id"]
    assert json.dumps(cat)                       # it has to survive the wire


# ------------------------------------------------------------- favourites

def test_a_star_is_kept_by_clip_id_and_survives_the_run_being_cut_again(root):
    """clips.json is rewritten whole when a recording is cut again, so a star
    cannot live in it."""
    clip = root / "2026-09-01_1200_VALORANT" / "clips" / "VALORANT_01.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"not really a video")
    assert studio.favourites(root) == set()
    got = studio.set_favourite(root, [str(clip)], on=True)
    assert got["ok"] and got["changed"] == 1
    assert studio.favourites(root) == {studio.clip_id(clip)}
    # ...and it is still there when the same path is read again
    assert studio.clip_id(str(clip).upper()) in studio.favourites(root)


def test_starring_twice_changes_nothing_and_unstarring_removes_it(root):
    a, b = root / "a.mp4", root / "b.mp4"
    studio.set_favourite(root, [str(a), str(b)], on=True)
    again = studio.set_favourite(root, [str(a)], on=True)
    assert again["changed"] == 0 and len(again["favourites"]) == 2
    off = studio.set_favourite(root, [str(a)], on=False)
    assert off["favourites"] == [studio.clip_id(b)]


def test_the_library_says_which_clips_are_starred(root):
    from test_studio import _clips, _run

    r = root / "clips"
    _run(r, "2026-09-01_1200_VALORANT", "VALORANT",
         [{"start": 100.0, "end": 112.0}, {"start": 200.0, "end": 212.0}],
         kills=[106.0, 206.0])
    (r / ".studio").mkdir(exist_ok=True)
    first = _clips(r)[0]
    studio.set_favourite(r, [first["path"]], on=True)
    lib = studio.library(r)
    clips = [c for g in lib["games"] for f in g["folders"] for c in f["clips"]]
    assert lib["fav_count"] == 1
    assert [c["fav"] for c in clips] == [True, False]


def test_deleting_a_clip_takes_its_star_with_it(root):
    from test_studio import _clips, _run

    r = root / "clips"
    _run(r, "2026-09-01_1200_VALORANT", "VALORANT",
         [{"start": 100.0, "end": 112.0}, {"start": 200.0, "end": 212.0}],
         kills=[106.0, 206.0])
    (r / ".studio").mkdir(exist_ok=True)
    clips = _clips(r)
    studio.set_favourite(r, [c["path"] for c in clips], on=True)
    assert len(studio.favourites(r)) == 2
    studio.delete_clips(r, [clips[0]["path"]])
    assert studio.favourites(r) == {studio.clip_id(clips[1]["path"])}


def test_a_dry_run_delete_leaves_the_stars_alone(root):
    from test_studio import _clips, _run

    r = root / "clips"
    _run(r, "2026-09-01_1200_VALORANT", "VALORANT", [{"start": 100.0, "end": 112.0}], kills=[106.0])
    (r / ".studio").mkdir(exist_ok=True)
    clip = _clips(r)[0]["path"]
    studio.set_favourite(r, [clip], on=True)
    studio.delete_clips(r, [clip], dry_run=True)
    assert studio.favourites(r) == {studio.clip_id(clip)}
