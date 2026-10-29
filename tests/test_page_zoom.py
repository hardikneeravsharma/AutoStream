"""Page size: zoom the whole UI in and out, and have the layout follow.

Asked 2026-10-30: "zoom in and zoom out to make the page big or small while
adjusting the UI components ... ctrl+scroll up zooms in and scroll down zooms
out, give on screen options also for it". The page scales itself (CSS zoom on
the root) so it works the same in the app's window and in a browser tab, and
the window-height layouts divide by the zoom so a bigger page still fits the
window instead of spilling below it.
"""
from __future__ import annotations

import json
import re

from autostream import ui
from autostream.ui import css as css_mod
from tests import jsfn

PRE = "const SHELL_ZOOM_STEPS = [0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2];"


def step(z, d):
    return jsfn.call(ui.JS, ["shell_zoomNext"], f"shell_zoomNext({json.dumps(z)}, {d})", PRE)


def test_steps_go_up_and_down_the_ladder():
    assert step(1, 1) == 1.1
    assert step(1, -1) == 0.9
    assert step(1.25, 1) == 1.5


def test_the_ends_hold():
    assert step(2, 1) == 2
    assert step(0.67, -1) == 0.67


def test_an_odd_saved_value_lands_on_the_nearest_step():
    assert step(1.03, 1) == 1.1
    assert step(1.03, -1) == 1
    assert step(0, 1) == 1.1, "a broken saved value counts as 100%"


def test_the_on_screen_control_is_there_and_named():
    body = ui.BODY
    for el, words in (("zoom-out", "Smaller"), ("zoom-reset", "Actual size"), ("zoom-in", "Bigger")):
        m = re.search(rf'id="{el}"[^>]*aria-label="([^"]+)"', body)
        assert m and words in m.group(1), el


def test_ctrl_wheel_and_ctrl_keys_are_handled():
    src = jsfn.source(ui.JS, "shell_zoomKey") + jsfn.source(ui.JS, "shell_zoomWheel")
    assert "ctrlKey" in src and "deltaY" in src
    for k in ("'='", "'+'", "'-'", "'0'"):
        assert k in src, k
    # A wheel listener has to be non-passive or preventDefault is ignored and
    # the browser's own zoom runs on top of ours.
    assert re.search(r"addEventListener\('wheel', shell_zoomWheel, \{passive: false\}\)", ui.JS)


def test_window_height_layouts_follow_the_zoom():
    sheet = css_mod.CSS
    assert "--vh:calc(1dvh / var(--ui-zoom, 1))" in sheet
    rest = sheet.replace("--vh:calc(1dvh / var(--ui-zoom, 1))", "")
    plain = re.findall(r"(?<![\w-])\d+(?:\.\d+)?d?vh", rest)
    assert not plain, plain


def test_ctrl_k_offers_the_page_size():
    assert "Make the page bigger" in ui.JS and "Make the page smaller" in ui.JS
