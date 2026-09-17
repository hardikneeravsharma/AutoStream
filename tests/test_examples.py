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


# ---------------------------------------------------------------- the store

def test_a_fresh_install_has_no_examples_and_says_which(root):
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
    assert got.kill == ("k04",) and got.kill_pool == ("k04",)
    assert got.cuts == ("t05",) and got.transition_pool == ("t05",)
    assert got.camera == "c04" and got.camera_pool == ("c04",)
    # untouched drawers keep the style's own
    assert got.intro == base.intro and got.outro == base.outro and got.grade == base.grade
    assert got.key == base.key


def test_a_part_that_is_not_that_drawers_is_ignored():
    base = studio.STYLE["hype"]
    assert studio.templated(base, {"kill": "t05", "camera": "nonsense"}) is base
    assert studio.templated(base, {}) is base


def test_the_reel_is_built_from_the_template(root):
    """What the dealer deals is what the shots get."""
    from test_studio import Shape, _clips, _run          # the Studio's own fixtures

    r = root / "clips"
    _run(r, "2026-09-01_1200_VALORANT", "VALORANT",
         [{"start": 100.0 * i, "end": 100.0 * i + 12} for i in range(1, 7)],
         kills=[100.0 * i + 6 for i in range(1, 7)])
    picks = {"intro": "i08", "outro": "e05", "grade": "g08", "kill": "k06",
             "camera": "c04", "speed": "s02", "overlay": "o01"}
    proj, _notes = studio.plan(_clips(r), "story", shape=Shape(bpm=120.0), template=picks)
    assert proj["intro"] == "i08" and proj["grade"] == "g08"
    assert proj["overlays"] == ["o01"]
    assert all(s["fx"] == ["k06"] for s in proj["shots"])
    assert all(s["camera"] == "c04" for s in proj["shots"])
    # ...and the same clips without a template keep the style's own picks
    plain, _ = studio.plan(_clips(r), "story", shape=Shape(bpm=120.0))
    assert plain["intro"] == studio.STYLE["story"].intro
    assert plain["shots"][0]["fx"] != ["k06"]


def test_the_catalog_tells_the_page_the_drawers_and_each_styles_picks():
    cat = studio.catalog()
    assert cat["drawers"] == list(studio.DRAWERS)
    for s in cat["styles"]:
        assert set(s["picks"]) == set(studio.DRAWERS)
    # the page draws a card per part, so every part needs a label and a blurb
    for p in cat["parts"]:
        assert p["label"] and p["blurb"], p["id"]
    assert json.dumps(cat)                       # it has to survive the wire
