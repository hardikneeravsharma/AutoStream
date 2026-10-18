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
    "V": ("'v'", "'V'"),
    "N": ("'n'", "'N'"),
    "C": ("'c'", "'C'"),
    "J": ("'j'", "'J'"),
    "K": ("'k'", "'K'"),
    "L": ("'l'", "'L'"),
    "I": ("'i'", "'I'"),
    "O": ("'o'", "'O'"),
    "M": ("'m'", "'M'"),
    "D": ("'d'", "'D'"),
    "K": ("'k'", "'K'"),
    "Ctrl+K": ("'k'", "'K'"),
    "Ctrl+Z": ("'z'", "'Z'"),
    "Ctrl+Shift+Z": ("'z'", "'Z'"),
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
        # Escape closes whatever is open AND puts the tool back to Select,
        # so the anchor is the call rather than the whole line.
        # Anchored on the line only this branch has: `studio_closeModals()`
        # alone appears earlier, in its own definition.
        "escape": page.index("if (studio.tool !== 'select') studio_tool('select');"),
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


# ------------------------------------- redo, and a history you can step back
# through (U17)

def test_undo_and_redo_are_one_key_apart_and_both_exist(page: str) -> None:
    """THE REPORTED SHAPE OF THE BUG: `studio.undo` was a pop stack behind one
    key, so a Ctrl+Z pressed once too often could not be taken back.

    Both halves are pinned here because they are easy to half-ship: a Redo
    command with no key, or a key bound to a command nobody registered.
    """
    undo = C.by_id("timeline.undo")
    redo = C.by_id("timeline.redo")
    assert undo and redo, "undo and redo must both be in the registry"
    assert undo["keys"] == ["Ctrl+Z"], undo
    assert redo["keys"] == ["Ctrl+Shift+Z"], redo
    assert undo["scope"] == redo["scope"], "they must live in the same scope"
    # One handler reads both, so Shift cannot end up on another scope's key.
    assert "if (e.shiftKey) studio_redo(); else studio_undo();" in page


def test_a_step_is_crossed_in_one_place_only(page: str) -> None:
    """Back and forward share `studio_step`, so they cannot drift apart.

    Two functions each doing half of it is how a redo ends up not reconciling
    the change list while an undo does -- which would make the count lie after
    going forward but not after going back.
    """
    assert page.count("function studio_step(") == 1
    # The two directions are the same call with its arguments swapped.
    assert "studio_step(studio.undo, studio.redo)" in page
    assert "studio_step(studio.redo, studio.undo)" in page
    # And a fresh edit abandons the way forward.
    assert "studio.redo = [];" in page


def test_the_history_reads_the_change_lists_own_words(page: str) -> None:
    """The plan's one correction: the labels `studio_change` writes are real
    and already feed the change list, so the history is a second VIEW of them
    and never a second list. Two lists over one set of edits would disagree.
    """
    # Every entry on the stack carries the label its edit was given.
    assert "studio.undo.push({snap: snapshot, label: label || " in page
    assert "studio_pushUndo(was, label);" in page
    # The panel is drawn from the two stacks, nothing else.
    assert "function studio_histDraw(" in page
    assert "const back = studio.undo, fwd = studio.redo;" in page


def test_jumping_to_a_step_crosses_every_step_between(page: str) -> None:
    """Restoring a state directly would leave the two stacks describing a
    history that never happened, and the change list reconciled once instead
    of at each step."""
    assert "function studio_histGo(" in page
    assert "for (let i = 0; i < back; i++) if (!studio_step(studio.undo, studio.redo)) break;" in page


# ------------------------------------- the timeline's tools (U18, part one)

def test_the_tools_are_named_and_each_has_a_key() -> None:
    """Select, Roll and Razor. Ripple is deliberately NOT among them: it is
    Shift on an edge, the one gesture that pushes everything after it. A
    "ripple tool" beside that would be two names for one behaviour, which is
    how a UI starts lying about what it does.
    """
    for cid, key in (("timeline.tool-select", "V"),
                     ("timeline.tool-roll", "N"),
                     ("timeline.tool-razor", "C")):
        c = C.by_id(cid)
        assert c, f"{cid} is not in the registry"
        assert c["keys"] == [key], c
        assert c["act"] == "studio-tool", c
        assert c["scope"] == "timeline", c
    assert C.by_id("timeline.tool-ripple") is None, (
        "there is no ripple tool: Shift on an edge already ripples")


def test_nobody_is_stranded_holding_a_tool(page: str) -> None:
    """Escape always comes back to Select, and every tool is also reachable as
    a modifier on the drag people already know -- so picking one is never
    required and never a trap."""
    assert "if (studio.tool !== 'select') studio_tool('select');" in page
    # An edge moves the cut with no tool picked at all; Shift asks for the
    # old push, and the Roll tool is the one place Shift cannot.
    assert "ripple: !!trim && e.shiftKey && studio.tool !== 'roll'," in page


def test_a_ripple_is_decided_on_the_press_not_read_each_frame(page: str) -> None:
    """Letting go of Shift halfway through a drag must not turn a push into a
    cut move under the hand: the reel's length would jump mid-gesture. So the
    move reads what the press decided, never the key as it is now."""
    assert "ripple: !!trim && e.shiftKey && studio.tool !== 'roll'," in page
    move = page[page.index("function studio_pointerMove("):]
    move = move[:move.index("\nfunction ")]
    assert "e.shiftKey" not in move


def test_the_razor_acts_on_the_press_and_starts_no_drag(page: str) -> None:
    """A cut that followed the pointer would be a trim with another name."""
    cut = page[page.index("if (studio.tool === 'razor') {"):]
    cut = cut[:cut.index("studio.drag = {")]
    assert "studio_razor(" in cut and "return;" in cut, cut


def test_the_razor_keeps_the_kill_with_the_half_it_happens_in(page: str) -> None:
    """`pre` is how long a shot runs before its kill, so the second half's
    kill is `at` nearer its own start -- and a kill left behind in the first
    half is simply not in the second. Both halves keep at least a beat."""
    fn = page[page.index("function studio_razor("):]
    fn = fn[:fn.index("\n}")]
    assert "b.pre = Number(Math.max(0, a.pre - at)" in fn, fn
    assert "at < beat || s.duration - at < beat" in fn, fn
    # A razor makes a hard cut between the halves; the transition it had
    # belonged to the join that is now the second half's.
    assert "a.transition = 't01'" in fn, fn


# --------------------------- in, out, marks and the shuttle (U18, part two)

def test_in_and_out_are_a_play_range_not_a_render_range(page: str) -> None:
    """THE PLAN RULED THIS OUT IN WRITING, and the reason is the change list:
    it says what has not reached the video yet, and a part-render would let it
    claim the video matches the timeline when it matches a slice of it.

    So nothing here may reach a render request.
    """
    fn = page[page.index("function studio_ioSet("):]
    fn = fn[:fn.index("\n}")]
    assert "/api/studio/render" not in fn, fn
    assert "studio_change(" not in fn, "an in point is not an edit of the reel"
    # And the range is read whichever way round the two were set.
    rng = page[page.index("function studio_ioRange("):]
    rng = rng[:rng.index("\n}")]
    assert "a <= b ? [a, b] : [b, a]" in rng, rng


def test_jkl_shuttles_rather_than_toggling(page: str) -> None:
    """Pressed again they go faster, and the other way they slow, stop and
    reverse -- which is what those keys do in every other editor. A toggle
    would be a second Play button on three keys."""
    assert "const STUDIO_SHUTTLE = [-8, -4, -2, -1, 0, 1, 2, 4, 8];" in page
    for cid, key in (("timeline.shuttle-back", "J"), ("timeline.shuttle-stop", "K"),
                     ("timeline.shuttle-on", "L")):
        c = C.by_id(cid)
        assert c and c["keys"] == [key], (cid, c)
    # K stops outright rather than stepping down.
    assert "studio.shuttle = 0; studio_shuttleApply();" in page


def test_a_mark_is_kept_on_the_reel_and_cannot_be_dropped_twice(page: str) -> None:
    """A mark is a note about the reel, not about this sitting at the screen,
    so it lives on the project and survives a reload. Pressing M twice on one
    frame is one mark."""
    fn = page[page.index("function studio_markAdd("):]
    fn = fn[:fn.index("\n}\n")]
    assert "pr.markers" in fn, fn
    assert "Math.abs(Number(m.t || m) - t) < 0.05" in fn, fn
    # Added through studio_change, so it joins the change list and one undo
    # takes it back, like every other edit.
    assert "studio_change(" in fn, fn


def test_a_scopes_keys_sit_below_the_scopes_read_before_it(page: str) -> None:
    """THE RULE THAT SHOULD HAVE CAUGHT IT, and did not.

    U18's shuttle bound K and was wired ABOVE the song pane, which binds K to
    "mark a kill". The handler returns on the first match, so marking a kill
    silently stopped working -- and `test_every_declared_key_is_one_the_page
    _reads` passed throughout, because it only asked whether the literal was
    somewhere in the file. The browser tier found it.

    Existence is not enough: a key has to be read in the scope it is declared
    in. The timeline is the LAST scope, so every timeline key must appear
    after the song pane's branch and after the focused-button guard.
    """
    song = page.index("if (song && studio.sg.shape) {")
    guard = page.index("if (onButton && (e.key === ' '")
    assert song < guard, "the song pane is read before the button guard"

    late = []
    for scope, key, cid in C.bindings():
        if scope != "timeline" or key.startswith("Ctrl"):
            continue                       # Ctrl keys are deliberately global
        forms = _LITERALS.get(key)
        assert forms, f"{cid} declares {key!r} with no literal in the table"
        # The LAST place the page reads this literal is the one that counts:
        # an earlier scope may legitimately bind the same key for itself.
        where = max((page.rfind(f) for f in forms), default=-1)
        if where < guard:
            late.append((cid, key))
    assert not late, (
        "these are declared as timeline keys but read before the scopes above "
        f"the timeline, so another pane's binding wins: {late}")
