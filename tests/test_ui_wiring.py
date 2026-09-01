"""The page and its script have to agree about what exists.

Two bugs shipped from this seam. A player said "no voices installed" while 28
were loaded, because the code filled every voice select except the one on the
player. A settings filter silently dropped nine round types, because the list
in the markup and the list in the app had drifted apart.

Both were invisible: a `getElementById` that returns null throws nothing, and a
handler wired to a function nobody wrote is a console message on a machine
where nobody has the console open. So these tests read the markup and the
script as text and check they still refer to the same things.

Each test asserts a floor on how much it inspected. A regex that quietly stops
matching is the failure mode of a test like this -- it goes green while
checking nothing, which is worse than not existing. The floors are what make
that loud.
"""
from __future__ import annotations

import importlib
import re

import pytest

PAGES = ("shell", "settings", "clips", "dashboard", "library", "logs", "setup")


def _blobs(name: str) -> list[str]:
    """Every rendered string a UI module exposes: its markup and its script."""
    mod = importlib.import_module(f"autostream.ui.{name}")
    return [getattr(mod, n) for n in dir(mod)
            if n.isupper() and isinstance(getattr(mod, n), str)]


@pytest.fixture(scope="module")
def ui() -> dict[str, str]:
    return {name: "\n".join(_blobs(name)) for name in PAGES}


@pytest.fixture(scope="module")
def everything(ui: dict[str, str]) -> str:
    return "\n".join(ui.values())


# Ids that markup creates -- written into the HTML, or built by a script that
# assembles rows at runtime, which is how most of the clip list exists.
def _defined(text: str) -> set[str]:
    ids = set(re.findall(r"""id=["']([A-Za-z0-9_-]+)["']""", text))
    ids |= set(re.findall(r"""\.id\s*=\s*["']([A-Za-z0-9_-]+)["']""", text))
    return ids


# Ids a script reaches for, whether through the DOM directly or one of the
# per-page one-line helpers (set_el, clip_el, shell_$, ...).
_GETTERS = re.compile(
    r"""(?:getElementById|\b[a-z]{2,7}_(?:el|\$|byId|get))"""
    r"""\(\s*['"]([A-Za-z0-9_-]+)['"]\s*\)""")


def test_every_id_the_script_reaches_for_exists(ui, everything):
    """A null element is a feature that quietly does nothing."""
    defined = _defined(everything)
    assert len(defined) >= 200, (
        f"only {len(defined)} ids found in the markup -- the id pattern has "
        f"probably stopped matching, so this test is checking nothing")

    reached = 0
    missing: dict[str, list[str]] = {}
    for page, text in ui.items():
        used = set(_GETTERS.findall(text))
        reached += len(used)
        gone = sorted(used - defined)
        if gone:
            missing[page] = gone

    assert reached >= 150, (
        f"only {reached} element lookups seen across {len(PAGES)} pages -- the "
        f"getter pattern has drifted and this test is checking nothing")
    assert not missing, (
        "the script reaches for elements no markup creates:\n" + "\n".join(
            f"  {page}: {', '.join(ids)}" for page, ids in missing.items()))


def _declared(text: str) -> set[str]:
    names = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", text))
    names |= set(re.findall(
        r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\()",
        text))
    names |= set(re.findall(r"^\s*([A-Za-z_$][\w$]*)\s*\(.*\)\s*\{", text, re.M))
    return names


def test_every_handler_points_at_a_real_function(everything):
    """A button wired to a name nobody wrote is a button that does nothing."""
    declared = _declared(everything)
    assert len(declared) >= 200, (
        f"only {len(declared)} function declarations found -- the declaration "
        f"pattern has drifted and this test is checking nothing")

    used = set(re.findall(
        r"""on(?:click|change|input|submit)=["']([a-z][\w$]*)\(""", everything))
    used |= set(re.findall(
        r"""addEventListener\(\s*['"][a-z]+['"]\s*,\s*([a-z][\w$]*)\s*[,)]""",
        everything))
    # Page helpers all carry a page prefix; a bare name is a DOM builtin.
    ours = {n for n in used if "_" in n}
    assert len(ours) >= 15, (
        f"only {len(ours)} handler references seen -- the handler pattern has "
        f"drifted and this test is checking nothing")

    assert not sorted(ours - declared), (
        "handlers point at functions that do not exist: "
        + ", ".join(sorted(ours - declared)))


def test_the_settings_page_can_show_and_install_an_update(ui):
    """The version card is only useful if all three of its states are wired."""
    text = ui["settings"]
    for element in ("set-ver-check", "set-ver-get", "set-ver-open",
                    "set-ver-msg", "set-ver-meter", "set-ver-fill"):
        assert f'id="{element}"' in text, f"{element} is missing from Settings"
    for call in ("/api/update/check", "/api/update/download",
                 "/api/update/install"):
        assert call in text, f"nothing in Settings calls {call}"
    # Progress has to ride the status poll, or the meter never moves.
    assert "onTick" in text and "set_verProgress" in text


def test_the_ui_script_is_valid_javascript(everything):
    """A syntax error anywhere kills EVERY page at once.

    The scripts are Python strings, so nothing checks them: a stray bracket
    passes the whole Python suite and then stops the entire app from working,
    silently, on a machine where nobody has the browser console open. esprima
    is a JavaScript parser written in Python, so this needs no Node install.
    """
    esprima = pytest.importorskip(
        "esprima", reason="pip install -r requirements-dev.txt to check the JS")

    from autostream import ui_assets

    assert len(ui_assets.JS) > 100_000, (
        "the assembled script is suspiciously small -- this test would be "
        "checking almost nothing")
    try:
        esprima.parseScript(ui_assets.JS)
    except Exception as e:                              # noqa: BLE001
        pytest.fail(f"the UI script does not parse: {e}")
