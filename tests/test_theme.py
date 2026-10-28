"""The palette is measured, not eyeballed.

The redesign (docs/superpowers/specs/2026-10-29-ui-redesign-design.md) moved
to two palettes, dark and light, plus a System choice that follows Windows.
Its first draft looked right and failed its own rules: tertiary text at
3.3:1, light-mode green at 3.4:1, control edges at 1.4:1. These tests are what
caught that, so the numbers stay pinned here rather than in a comment.
"""
from __future__ import annotations

import re

import pytest

from autostream import theme


def _rgb(value: str, over: tuple[int, int, int] | None = None) -> tuple[float, float, float]:
    value = value.strip()
    m = re.fullmatch(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)", value)
    if m:
        r, g, b, a = (int(m.group(1)), int(m.group(2)), int(m.group(3)), float(m.group(4)))
        assert over is not None, "an rgba value needs something to sit on"
        return tuple(a * c + (1 - a) * o for c, o in zip((r, g, b), over))
    h = value.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lum(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


GROUNDS = ("bg", "chrome", "surface", "surface-raised", "surface-sunken")


@pytest.mark.parametrize("tid", ["dark", "light"])
def test_text_reads_at_4_5_on_every_ground(tid):
    v = theme.THEMES[tid]["vars"]
    bad = []
    for text in ("text-primary", "text-secondary", "text-tertiary"):
        for ground in GROUNDS:
            c = contrast(_rgb(v[text]), _rgb(v[ground]))
            if c < 4.5:
                bad.append(f"{text} on {ground}: {c:.2f}")
    assert not bad, bad


@pytest.mark.parametrize("tid", ["dark", "light"])
def test_control_edges_read_at_3(tid):
    v = theme.THEMES[tid]["vars"]
    bad = []
    for ground in ("surface", "surface-raised", "surface-sunken"):
        g = _rgb(v[ground])
        c = contrast(_rgb(v["border-strong"], over=g), g)
        if c < 3.0:
            bad.append(f"border-strong on {ground}: {c:.2f}")
    assert not bad, bad


@pytest.mark.parametrize("tid", ["dark", "light"])
def test_state_colours_read_as_text(tid):
    v = theme.THEMES[tid]["vars"]
    bad = [f"{s}: {contrast(_rgb(v[s]), _rgb(v['surface'])):.2f}"
           for s in ("live", "ok", "warn", "danger")
           if contrast(_rgb(v[s]), _rgb(v["surface"])) < 4.5]
    assert not bad, bad


def test_legacy_ids_resolve():
    assert theme.resolve("carbon") == "dark"
    assert theme.resolve("midnight") == "dark"
    assert theme.resolve("ember") == "dark"
    assert theme.resolve("forest") == "dark"
    assert theme.resolve("daylight") == "light"
    assert theme.resolve("light") == "light"
    assert theme.resolve("nonsense") == "system"
    assert theme.resolve(None) == "system"


def test_system_carries_both_palettes():
    system = theme.root_css("system")
    assert "prefers-color-scheme: light" in system
    assert theme.THEMES["light"]["vars"]["bg"] in system
    assert theme.THEMES["dark"]["vars"]["bg"] in system
    assert "prefers-color-scheme" not in theme.root_css("dark")
    assert "prefers-color-scheme" not in theme.root_css("carbon")


def test_listing_is_system_dark_light():
    assert [t["id"] for t in theme.listing()] == ["system", "dark", "light"]


def test_the_page_carries_the_palette_in_its_own_style_block():
    from autostream import webui
    html = webui.page("system")
    assert '<style id="theme-vars">' in html
    assert "prefers-color-scheme: light" in html
