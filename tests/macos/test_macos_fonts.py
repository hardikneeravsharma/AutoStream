"""Every font the renderers ask Windows for has a Mac answer.

Measured, not assumed: before this the caption, handle and subtitle were
silently left out of every Mac clip, because each lookup went to
C:\\Windows\\Fonts and drawtext is only added when a font is found.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from autostream.macos import fonts


def test_every_row_ends_in_a_font_that_ships_with_autostream():
    """So no Mac -- however stripped -- drops a caption for want of a face."""
    for name, row in fonts.SUBSTITUTES.items():
        assert row, name
        assert row[-1].is_file(), f"{name} has no bundled fallback: {row[-1]}"
        assert row[-1].parent == fonts.BUNDLED


def test_a_lookup_never_comes_back_empty_for_a_known_name():
    for name in fonts.SUBSTITUTES:
        assert fonts.find(name) is not None, name


def test_the_callers_order_is_kept(monkeypatch, tmp_path):
    a, b = tmp_path / "a.ttf", tmp_path / "b.ttf"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    monkeypatch.setattr(fonts, "SUBSTITUTES", {"one.ttf": (a,), "two.ttf": (b,)})
    assert fonts.first(("two.ttf", "one.ttf")) == str(b)
    assert fonts.first(("nope.ttf",)) is None


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")


def test_overlay_captions_get_a_font_on_a_mac(mac):
    from autostream.clips import overlay

    got = overlay._font(overlay._CAPTION_FONTS)
    assert got and Path(got).is_file()


def test_the_mark_finds_a_bold_face_on_a_mac(mac):
    from autostream.clips import mark

    assert Path(mark._font_file()).is_file()


def test_studio_text_names_a_fontfile_on_a_mac(mac):
    """An empty answer here put drawtext in the graph with no font at all."""
    from autostream.clips import studio

    got = studio._font()
    assert got.startswith("fontfile='") and got.endswith("':")


def test_the_highlight_title_font_is_copied_on_a_mac(mac, tmp_path):
    from autostream.clips import highlight

    assert highlight._font(tmp_path) is True
    assert (tmp_path / "title.ttf").stat().st_size > 0


def test_windows_still_looks_only_in_its_own_fonts_folder(monkeypatch, tmp_path):
    from autostream.clips import overlay

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(overlay, "_FONT_DIR", tmp_path)
    (tmp_path / "impact.ttf").write_bytes(b"x")
    assert overlay._font(("impact.ttf",)) == str(tmp_path / "impact.ttf")
    assert overlay._font(("arialbd.ttf",)) is None
