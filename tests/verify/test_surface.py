"""The register and the app have to describe the same program.

Tier 2a. Nothing here starts a server -- these are static checks over the
source, and they are the reason the flow tests can claim to cover every
button rather than the forty-odd somebody remembered to write down.

Four ways the app and the register can drift, and all four fail here:

  a button calls a route nobody serves        -> a dead control
  a route nobody calls and nobody catalogued  -> untested surface
  an action with no row and no exemption      -> a button nobody checked
  a regex that stopped matching               -> caught by the floors

The floors matter as much as the checks. tests/test_ui_wiring.py learned this
the hard way: a source-reading test whose pattern drifts goes green while
inspecting nothing, which is worse than not existing. Every count below is
asserted to be at least roughly what it is today.
"""
from __future__ import annotations

import catalog
import surface


# ------------------------------------------------------------ the floors

def test_the_extractors_still_find_the_surface():
    """If these drop, a regex stopped matching and every check below is a lie."""
    assert len(surface.server_routes()) >= 60, "routes vanished from webui.py"
    assert len(surface.ui_endpoints()) >= 55, "the UI stopped naming its routes"
    assert len(surface.ui_actions()) >= 28, "data-act extraction drifted"
    assert len(surface.ui_operable_ids()) >= 30, "id extraction drifted"
    assert len(catalog.CONTROLS) >= 60, "the register shrank"


def test_every_route_is_reached_by_one_dispatcher_or_the_other():
    routes, methods = surface.server_routes(), surface.server_methods()
    unmapped = sorted(routes - set(methods))
    assert unmapped == [], f"served but in neither _get nor do_POST: {unmapped}"
    both = sorted(p for p, m in methods.items() if len(m) > 1)
    assert both == [], f"answered by both GET and POST, which the UI cannot know: {both}"


# --------------------------------------------------------- the closure

def test_every_endpoint_the_ui_calls_is_actually_served():
    """A button wired to a path webui does not answer gets a 404 and a toast
    saying nothing useful. This is the check that would have caught it."""
    called = set(surface.ui_endpoints())
    missing = sorted(called - surface.server_routes())
    assert missing == [], (
        "the UI calls routes that webui.py does not serve: " + str(missing))


def test_every_route_the_server_answers_is_in_the_register():
    """The other direction: a route added without a row here is surface that
    nothing exercises. Adding the row is the cost of adding the route."""
    orphans = sorted(surface.server_routes() - set(catalog.BY_PATH))
    assert orphans == [], (
        "served but not in tests/verify/catalog.py, so nothing tests them: "
        + str(orphans))


def test_the_register_does_not_invent_routes():
    """A row for a path that no longer exists would pass forever without
    testing anything, because the flow test would skip it as unreachable."""
    invented = sorted(set(catalog.BY_PATH) - surface.server_routes())
    assert invented == [], (
        "catalogued but not served - stale rows: " + str(invented))


def test_the_register_agrees_with_the_server_about_the_method():
    methods = surface.server_methods()
    wrong = [f"{c.path}: register says {c.method}, webui says {sorted(methods[c.path])}"
             for c in catalog.CONTROLS
             if c.path in methods and c.method not in methods[c.path]]
    assert wrong == [], wrong


# ---------------------------------------------------------- the controls

def test_every_action_is_either_catalogued_or_exempt():
    """data-act is the click vocabulary of the Clips and setup pages. Each
    token either reaches a route in the register, or is listed in NOT_A_FLOW
    with the reason it never leaves the browser."""
    catalogued = {a for c in catalog.CONTROLS for a in c.acts}
    loose = sorted(set(surface.ui_actions())
                   - catalogued - set(catalog.NOT_A_FLOW))
    assert loose == [], (
        "a user can click these and nothing checks what happens; give each a "
        "row in CONTROLS.acts or an entry in NOT_A_FLOW saying why it stays "
        "in the browser: " + str(loose))


def test_the_exemptions_are_still_real_controls():
    """An exemption for a control that no longer exists is a note nobody will
    ever delete, and it hides the next control that takes the same name."""
    stale = sorted(name for name in catalog.NOT_A_FLOW
                   if not surface.names_the_ui_still_uses(name))
    assert stale == [], f"exempted but no longer in the UI: {stale}"


def test_every_exemption_says_why():
    blank = sorted(k for k, v in catalog.NOT_A_FLOW.items() if not v.strip())
    assert blank == [], f"exempted with no reason given: {blank}"


# -------------------------------------------------------- never-invoke

def test_the_dangerous_routes_are_marked_and_stay_marked():
    """These do something to the developer's machine or reach the network, so
    the flow tests assert they exist without calling them. The list is pinned
    because downgrading one to CALL would look like a small edit and would
    start opening file dialogs in CI."""
    must_stay_static = {
        "/api/clips/pick",              # native Tk dialog, blocks the thread
        "/api/clips/install",           # winget, UAC
        "/api/update/check",            # network
        "/api/update/download",         # network
        "/api/update/install",          # installs and quits the app
        "/api/setup/auth",              # opens a browser, OAuth
        "/api/setup/obs_test",          # connects to OBS
        "/api/setup/webview2/install",  # downloads the Edge runtime
        "/api/logs/open",               # os.startfile
    }
    wrong = sorted(p for p in must_stay_static
                   if catalog.BY_PATH[p].probe != catalog.STATIC)
    assert wrong == [], f"marked callable but must never be called: {wrong}"


def test_every_static_row_says_why_it_cannot_be_called():
    silent = sorted(c.path for c in catalog.CONTROLS
                    if c.probe == catalog.STATIC and not c.why.strip())
    assert silent == [], silent


def test_every_row_carries_a_reason():
    """`why` is what a failure reads like at three in the morning."""
    silent = sorted(c.path for c in catalog.CONTROLS if not c.why.strip())
    assert silent == [], f"rows with no explanation: {silent}"
