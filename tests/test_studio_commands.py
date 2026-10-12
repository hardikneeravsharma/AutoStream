"""The Studio's command registry has to agree with the page it describes.

The registry (autostream/ui/commands.py) exists so that three things can read
one list: the command list on Ctrl+K, the key sheet on ?, and the browser tier
through /api/studio/commands. The risk that comes with it is drift -- a
registry that has stopped describing the page is worse than no registry, because
the key sheet is then a confident lie and the palette offers buttons that are
not there.

So these tests hold four rules, all offline:

  1. Every `data-act` the page renders has a command naming it, and every
     command names an act the page renders.
  2. No key is bound twice in one scope.
  3. No binding names a command that does not exist, and no command sits in a
     scope the page does not have.
  4. Every key the registry declares is a key the page's handlers actually
     read. This is the one that keeps the generated sheet honest.

Rules 2 and 3 are the two ArtCraft's specifications carry (see the U16 row in
docs/ROADMAP.md); 1 and 4 are ours, because our commands stand on controls and
handlers that already exist.

Each test asserts a floor on how much it inspected: a regex that quietly stops
matching is the failure mode here, and a green test that checked nothing is
worse than no test.
"""
from __future__ import annotations

import re
from collections import Counter

import pytest

from autostream.ui import commands as C
from autostream.ui import studio as S


@pytest.fixture(scope="module")
def page() -> str:
    """Everything the Studio renders: its markup and its script, as one text."""
    return S.STUDIO_HTML + "\n" + S.STUDIO_JS


@pytest.fixture(scope="module")
def rendered_acts(page: str) -> set[str]:
    found = set(re.findall(r'data-act="([a-z0-9-]+)"', page))
    assert len(found) >= 147, f"only {len(found)} actions found in the page -- the regex has drifted"
    return found


def test_every_rendered_action_has_a_command(rendered_acts: set[str]) -> None:
    """An action with no command is one the list and the sheet cannot offer."""
    missing = sorted(rendered_acts - C.acts())
    assert not missing, (
        "these actions are on the page but not in ui/commands.py, so nothing "
        f"can name them: {missing}"
    )


def test_every_command_stands_on_a_real_action(rendered_acts: set[str]) -> None:
    """A command naming an act the page never renders is a dead offer."""
    stale = sorted(C.acts() - rendered_acts)
    assert not stale, (
        "these commands name an action the page does not render, so running "
        f"them would find no control: {stale}"
    )


def test_ids_are_unique_and_scopes_exist() -> None:
    dupes = [cid for cid, n in Counter(c["id"] for c in C.COMMANDS).items() if n > 1]
    assert not dupes, f"two commands share an id: {dupes}"
    assert len(C.COMMANDS) >= 147, "fewer commands than the page has actions"
    bad = sorted({c["scope"] for c in C.COMMANDS} - set(C.SCOPE_IDS))
    assert not bad, f"commands sit in scopes the page has no name for: {bad}"
    unlabelled = [c["id"] for c in C.COMMANDS if not c["label"].strip()]
    assert not unlabelled, f"a command with no label cannot be searched for: {unlabelled}"


def test_no_key_is_bound_twice_in_one_scope() -> None:
    """Two commands on one key in one scope: one of them never runs."""
    seen: dict[tuple[str, str], list[str]] = {}
    for scope, key, cid in C.bindings():
        seen.setdefault((scope, key), []).append(cid)
    clashes = {k: v for k, v in seen.items() if len(v) > 1}
    assert not clashes, f"the same key twice in one scope: {clashes}"
    assert len(seen) >= 20, f"only {len(seen)} bindings checked -- the registry has lost its keys"


def test_every_binding_names_a_command_that_exists() -> None:
    known = C.ids()
    orphans = [cid for _, _, cid in C.bindings() if cid not in known]
    assert not orphans, f"bindings naming nothing: {orphans}"


# The page reads a key by its DOM name, so each declared key has a literal the
# handlers must contain. Ctrl is matched separately (e.ctrlKey || e.metaKey),
# and a letter may be read in either case or through toLowerCase().
_LITERALS = {
    "Space": ("' '",),
    "Escape": ("'Escape'",),
    "Enter": ("'Enter'",),
    "Delete": ("'Delete'",),
    "Backspace": ("'Backspace'",),
    "ArrowLeft": ("'ArrowLeft'",),
    "ArrowRight": ("'ArrowRight'",),
    "?": ("'?'",),
    ",": ("','",),
    ".": ("'.'",),
    "+": ("'+'",),
    "=": ("'='",),
    "-": ("'-'",),
    "_": ("'_'",),
    "0": ("'0'",),
    "K": ("'k'", "'K'"),
    "Ctrl+K": ("'k'", "'K'"),
    "Ctrl+Z": ("'z'", "'Z'"),
}


def test_every_declared_key_is_one_the_page_reads(page: str) -> None:
    """The sheet is generated, so it is honest only if these match.

    A key declared here and read nowhere prints on the sheet and does nothing
    -- which is exactly the drift a generated sheet was supposed to end.
    """
    checked = 0
    for _scope, key, cid in C.bindings():
        forms = _LITERALS.get(key)
        assert forms, f"{cid} declares {key!r}, which this test has no literal for -- add it"
        assert any(f in page for f in forms), (
            f"{cid} declares {key!r} but the page's handlers never read {forms}"
        )
        if key.startswith("Ctrl+"):
            assert "e.ctrlKey || e.metaKey" in page, "no handler reads Ctrl at all"
        checked += 1
    assert checked >= 20, f"only {checked} keys checked -- the registry has lost its bindings"


def test_the_registry_reaches_the_page_and_the_api() -> None:
    """Both readers, so neither can be the one left behind."""
    from autostream import ui

    assert "const STUDIO_CMDS = " in ui.JS, "the page is not served the registry"
    assert "const STUDIO_SCOPES = " in ui.JS, "the page is not served the scopes"
    # The page's own route, written out, is what the wiring test looks for.
    assert '"/api/studio/commands"' in _webui_text(), "no route serves the registry"

    out = C.payload()
    assert out["ok"] is True
    assert len(out["commands"]) == len(C.COMMANDS)
    assert [s["id"] for s in out["scopes"]] == list(C.SCOPE_IDS)


def test_the_scope_order_is_the_handler_order(page: str) -> None:
    """The keydown block reads scopes in a fixed order and the sheet prints it.

    Space on a focused button must press the button, not play the reel; that
    is a consequence of the order alone, so the order is pinned here and the
    sheet cannot quietly print another one.
    """
    at = {
        "import": page.index("if (studio_impKey(e)) return;"),
        "picker": page.index("if (studio_fxpKey(e)) return;"),
        "palette": page.index("if (studio_palKey(e)) return;"),
        "escape": page.index("if (e.key === 'Escape') { studio_closeModals(); return; }"),
        "inputs": page.index("if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;"),
        "button": page.index("if (onButton && (e.key === ' '"),
    }
    order = [k for k, _ in sorted(at.items(), key=lambda kv: kv[1])]
    assert order == ["import", "picker", "palette", "escape", "inputs", "button"], order
    # And the sheet's scopes start with the two dialogs that take keys first.
    assert C.SCOPE_IDS[:2] == ("import", "picker")


def _webui_text() -> str:
    from pathlib import Path

    import autostream

    return (Path(autostream.__file__).parent / "webui.py").read_text(encoding="utf-8")
