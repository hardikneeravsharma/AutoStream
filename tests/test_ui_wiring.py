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


# ------------------------------------------------------------------ choices
#
# Every list the page offers has a counterpart in the app, and the two drift
# apart silently: an option that matches nothing looks exactly like an option
# nobody picked. That is how the round-type filter came to offer 8 labels for
# 17 kinds of clip, with nine of them unreachable and nobody any the wiser.
#
# So each of these pins one list to its source of truth.

def _js_list(js: str, name: str) -> str:
    """The text of one `NAME = [...]` array.

    Counts brackets rather than matching to the next `];`. A regex that guesses
    where the array ends swallows the rest of the script the moment the
    formatting changes -- and then every assertion made about "the list" is
    really about the whole file, which passes for the wrong reason or fails
    for one that has nothing to do with the list. Getting that wrong once was
    enough.
    """
    import re

    m = re.search(rf"\b{name}\s*=\s*\[", js)
    assert m, f"{name} is not in the page any more"
    at = m.end() - 1
    depth = 0
    for i in range(at, len(js)):
        if js[i] == "[":
            depth += 1
        elif js[i] == "]":
            depth -= 1
            if depth == 0:
                return js[at:i + 1]
    raise AssertionError(f"{name} is never closed")


def test_the_round_type_filter_offers_every_type_the_app_produces(ui):
    import re

    from autostream.clips import rounds

    offered = set(re.findall(r"'([A-Z0-9 ]{2,})'",
                             _js_list(ui["clips"], "CLIP_ROUND_TYPES")))
    assert offered == set(rounds.FILTERABLE), (
        f"unreachable in the app: {sorted(offered - set(rounds.FILTERABLE))}; "
        f"unofferable on the page: {sorted(set(rounds.FILTERABLE) - offered)}")


def test_the_filter_is_not_truncated_on_the_way_to_the_app(everything):
    """The endpoint caps the list it accepts. The cap has to be above the
    number of types, or the last few are dropped in transit -- the same bug
    again, one layer further down."""
    import inspect
    import re

    from autostream import webui
    from autostream.clips import rounds

    src = inspect.getsource(webui.Server.clips_run)
    caps = [int(n) for n in re.findall(r'round_types"\]\s*=\s*\[[^\]]*\]\[:(\d+)\]',
                                       src)]
    assert caps, "the round_types cap is no longer where this test looks"
    assert min(caps) >= len(rounds.FILTERABLE), (
        f"the endpoint keeps only {min(caps)} of {len(rounds.FILTERABLE)} types")


def test_every_transition_offered_is_one_the_montage_can_do(ui):
    import re

    from autostream.clips import montage

    offered = set(re.findall(r"'([a-z]+)'", _js_list(ui["clips"], "CLIP_TRANS")))
    known = set(montage.TRANSITIONS) | {"cut", "mixed"}
    assert not offered - known, f"the montage cannot do: {sorted(offered - known)}"
    assert not known - offered, f"the page hides: {sorted(known - offered)}"


def test_every_framing_offered_is_one_the_cutter_can_do(ui):
    import inspect
    import re

    from autostream.clips import cutter

    offered = set(re.findall(r'data-vert="([a-z]+)"', ui["clips"]))
    known = set(re.findall(r'mode == "(\w+)"',
                           inspect.getsource(cutter.vertical))) | {"none"}
    assert offered and not offered - known


def test_the_clip_styles_say_the_numbers_the_app_actually_uses(ui):
    """The timings are written out in prose in two places -- the Clips page and
    the Settings schema -- and applied from a third. Prose does not fail a
    test when it goes stale, so this checks the numbers inside it."""
    from autostream import schema
    from autostream.clips import plan

    page = _js_list(ui["clips"], "CLIP_STYLES")
    settings = str(schema.FIELDS) if hasattr(schema, "FIELDS") else ""
    if not settings:
        import inspect
        settings = inspect.getsource(schema)

    for key, style in plan.STYLES.items():
        pre = style["pre_roll"]
        tail = style["tail"]
        length = style["clip_seconds"]
        # "1.5s before, 2s after, 15s clips" -- written with the trailing .0
        # dropped, the way a person writes it.
        def num(v):
            return str(int(v)) if float(v) == int(v) else str(v)

        for where, text in (("the Clips page", page),
                            ("the Settings schema", settings)):
            assert key in text, f"{key} is missing from {where}"
            said = f"{num(pre)}s before, {num(tail)}s after, {length}s clips"
            assert said in text, (
                f"{where} does not say {said!r} for {key} -- plan.STYLES has "
                f"pre_roll={pre}, tail={tail}, clip_seconds={length}")


def test_the_page_offers_every_style_the_app_has_and_no_others(ui):
    import re

    from autostream.clips import plan

    offered = set(re.findall(r"\['([a-z]+)',", _js_list(ui["clips"], "CLIP_STYLES")))
    assert offered == set(plan.STYLES) | {"custom"}


# ------------------------------------------------------------------- routes

def _routes():
    """(what the server answers, what the page asks for)."""
    import inspect
    import re

    from autostream import ui_assets, webui

    src = inspect.getsource(webui)
    answers = set(re.findall(r'==\s*"(/api/[a-z0-9/_-]+)"', src))
    answers |= set(re.findall(r'startswith\("(/api/[a-z0-9/_-]+)"', src))
    asks = set(re.findall(r"['\"](/api/[a-z0-9/_-]+)", ui_assets.JS))
    return answers, asks


def test_every_route_the_page_calls_exists():
    """A 404 from the page shows up nowhere but a console nobody has open."""
    answers, asks = _routes()
    assert len(answers) > 40, (
        f"only {len(answers)} routes found -- the pattern has drifted and this "
        f"test is checking nothing")
    assert not asks - answers, (
        f"the page calls routes the server does not answer: {sorted(asks - answers)}")


def test_no_route_exists_that_nothing_can_reach():
    """Two did, for a long time: a diagnostic report and a way to clear
    streams whose recording had been deleted. Both were built, both were
    sensible, and no button anywhere called either -- so they were not
    features, just code that had to keep working for nobody.

    If a route belongs here without a caller, say why in this list rather
    than deleting the assertion.
    """
    answers, asks = _routes()
    deliberate: set[str] = set()
    orphaned = answers - asks - deliberate
    assert not orphaned, (
        f"nothing in the UI reaches: {sorted(orphaned)} -- wire it up, delete "
        f"it, or add it to `deliberate` above with a reason")


# ------------------------------------------------------------------ settings

def test_every_setting_offered_has_a_default_and_the_other_way_round():
    """The Settings page and the config defaults are two lists of the same
    thing, kept in two files.

    A field with no default writes a key nothing knows how to read. A default
    with no field is a behaviour only reachable by editing YAML. Both are
    invisible: the page renders either way.
    """
    from autostream import cfg, schema

    def flat(d, prefix=""):
        out = set()
        for k, v in (d or {}).items():
            key = f"{prefix}{k}"
            if isinstance(v, dict):
                out |= flat(v, key + ".")
            else:
                out.add(key)
        return out

    offered = set(schema.FIELDS_BY_PATH)
    defaults = flat(cfg.DEFAULTS)
    assert len(offered) > 50, (
        f"only {len(offered)} settings found -- FIELDS_BY_PATH has changed "
        f"shape and this test is checking nothing")

    assert not offered - defaults, (
        f"the page offers settings with no default: {sorted(offered - defaults)}")
    assert not defaults - offered, (
        f"settings only reachable by editing YAML: {sorted(defaults - offered)}")
