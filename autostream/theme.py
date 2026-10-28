"""Design tokens: the single source of truth for every colour in AutoStream.

WHY THIS FILE EXISTS
    The UI has no build step, so there is no Sass/Tailwind layer to hold a palette.
    Themes therefore live here as plain data and are emitted as CSS custom properties
    into the `:root{}` block of the one page the server serves. Nothing downstream --
    not css.py, not any page module -- is allowed to write a literal colour, so a new
    theme is purely an addition to THEMES and costs no other edit.

WHY THE TOKENS ARE ROLE-NAMED AND NOT COLOUR-NAMED
    Tokens name a job (`surface-sunken`, `border-strong`, `text-on-accent`), never a
    hue. That is what lets `light` invert the whole system without a single
    conditional in the stylesheet.

TWO PALETTES AND A CHOICE (the 2026-10-29 redesign)
    Five themes became System, Dark and Light. The look is calm and monochrome: the
    accent IS the text colour, so a primary button is a white plate in dark and a
    black one in light, and hue appears only for state. System is not a third
    palette -- root_css() emits dark with light inside prefers-color-scheme, so the
    page follows the OS without script. The old ids still resolve (ALIASES).

WHY THE SIX LEGACY ALIASES ARE STILL HERE
    `fg`, `dim`, `faint`, `line`, `raised` and `accent-fg` duplicate the semantic names.
    The old ui_assets.py stylesheet still references them, and its JavaScript resolves
    some of them *by name* at runtime through getComputedStyle, so dropping them would
    fail silently rather than loudly. They are aliases, not a second palette: keep them
    in step with the semantic token they mirror, and delete them only once the last
    `var(--line)` / `cssv('faint')` call site is gone.

CONTRAST
    Every ratio quoted in the per-theme `contrast` notes was computed with the WCAG 2.x
    relative-luminance formula, not estimated, and tests/test_theme.py re-measures them:
    every text token clears 4.5:1 on bg, chrome, surface, raised and sunken, and
    `border-strong` -- which bounds every interactive control -- clears 3:1, satisfying
    WCAG 1.4.11. The one exception is dark tertiary on `surface-active` (4.0:1), so
    tertiary text is never set on a selected fill.

    Consequence for maintainers: the state colours in `light` are dark bronze, brick
    and pine because they must work as TEXT. The light amber people expect is
    `warn-muted`, which is only ever the plate behind it. Do not "fix" them.
"""
from __future__ import annotations

# Canonical token order. Every theme declares exactly these keys, in this order, so a
# diff between two themes is a diff of values only. Verified at import time below.
TOKENS: tuple[str, ...] = (
    # --- ground ---------------------------------------------------------------
    "bg",                # the room: the page behind everything
    "chrome",            # rail + topbar chassis; deliberately not `bg`
    "surface",           # elevation 1: cards, panels, list rows
    "surface-raised",    # elevation 2: the status panel, metric cells
    "surface-sunken",    # elevation 0: inputs, log pane, chat scroller
    "surface-overlay",   # elevation 3/4: dropdowns, modals
    "surface-hover",     # row/nav hover fill
    "surface-active",    # pressed / selected row fill
    # --- lines ----------------------------------------------------------------
    "border-subtle",     # decorative only: panel edges, dividers, row rules
    "border-strong",     # bounds an interactive control; >=3:1 everywhere
    "border-focus",      # the focus ring
    # --- text -----------------------------------------------------------------
    "text-primary",
    "text-secondary",
    "text-tertiary",
    "text-on-accent",
    # Legible ON the ok fill, which is a light green in every dark theme. Four
    # places wrote #fff on it and measured 1.96-2.14:1 -- the same mistake as
    # #fff on accent, one token along.
    "text-on-ok",
    # --- accent (see the accent budget in css.py) -----------------------------
    "accent",
    "accent-hover",
    "accent-text",       # accent legible as small text on a surface
    "accent-muted",      # opaque plate, never an rgba wash
    # --- state ----------------------------------------------------------------
    "live",
    "live-muted",
    "ok",
    "ok-muted",
    "warn",
    "warn-muted",
    "danger",
    "danger-muted",
    "idle",
    "idle-muted",
    "track",             # meter / toggle track
    # --- effects --------------------------------------------------------------
    "shadow-color",
    "rim",               # 1px inner top highlight; elevation 2+ only
    "scrim",
    "selection",
    # --- foregrounds for filled state buttons ---------------------------------
    # Not in the original 40: the old sheet hardcoded `#fff` on the danger button and
    # `#12100a` on the warn button, which was the only unowned colour in a themed
    # stylesheet. These give those two fills a real token.
    "text-on-danger",
    "text-on-warn",
    # --- legacy aliases (see module docstring) --------------------------------
    "fg",
    "dim",
    "faint",
    "line",
    "raised",
    "accent-fg",
)


THEMES: dict[str, dict] = {
    "dark": {
        "label": "Dark",
        "dark": True,
        # Quiet graphite. Greys with no hue to speak of, hairline edges, and colour
        # kept for state alone: red is live or broken, green is done, amber needs you.
        # The accent is the text colour itself, so the primary button is a white
        # plate and the four accent uses read as emphasis rather than as a brand.
        "vars": {
            "bg": "#141519",
            "chrome": "#141519",
            "surface": "#191A1F",
            "surface-raised": "#202228",
            "surface-sunken": "#111215",
            "surface-overlay": "#1E2025",
            "surface-hover": "#1E2025",
            "surface-active": "#2A2C33",
            "border-subtle": "rgba(255,255,255,.07)",
            "border-strong": "rgba(255,255,255,.38)",
            "border-focus": "#ECEDEF",
            "text-primary": "#ECEDEF",
            "text-secondary": "#A0A3AB",
            "text-tertiary": "#868A93",
            "text-on-accent": "#191A1F",
            "text-on-ok": "#0E1512",
            "accent": "#ECEDEF",
            "accent-hover": "#FFFFFF",
            "accent-text": "#ECEDEF",
            "accent-muted": "#2A2C33",
            "live": "#F2626A",
            "live-muted": "#2E1A1C",
            "ok": "#5CC8A8",
            "ok-muted": "#16241F",
            "warn": "#E5B454",
            "warn-muted": "#2A2417",
            "danger": "#F2626A",
            "danger-muted": "#2E1A1C",
            "idle": "#868A93",
            "idle-muted": "#202228",
            "track": "#2A2C33",
            "shadow-color": "rgba(0,0,0,.5)",
            "rim": "rgba(255,255,255,.04)",
            "scrim": "rgba(10,10,12,.6)",
            "selection": "rgba(236,237,239,.18)",
            "text-on-danger": "#141519",
            "text-on-warn": "#141519",
            "fg": "#ECEDEF",
            "dim": "#A0A3AB",
            "faint": "#868A93",
            "line": "rgba(255,255,255,.07)",
            "raised": "#202228",
            "accent-fg": "#191A1F",
        },
        "contrast": {
            "on_surface": "primary 15.1 / secondary 7.0 / tertiary 5.0",
            "worst_text": "tertiary 4.6 on surface-raised; never on surface-active (4.0)",
            "non_text": "border-strong 3.2 on surface-raised, 3.6 on surface",
            "button": "text-on-accent on accent 15.1",
        },
    },
    "light": {
        "label": "Light",
        "dark": False,
        # The same system with the lights on: white plates on a pale grey room,
        # near-black ink. The state colours are deep (brick, pine, bronze) because
        # they must work as TEXT on white, not just as dots.
        "vars": {
            "bg": "#F4F4F6",
            "chrome": "#F4F4F6",
            "surface": "#FFFFFF",
            "surface-raised": "#F0F1F3",
            "surface-sunken": "#F7F7F8",
            "surface-overlay": "#FFFFFF",
            "surface-hover": "#F0F1F3",
            "surface-active": "#E3E4E8",
            "border-subtle": "rgba(0,0,0,.08)",
            "border-strong": "rgba(0,0,0,.45)",
            "border-focus": "#18191C",
            "text-primary": "#18191C",
            "text-secondary": "#55585F",
            "text-tertiary": "#666A72",
            "text-on-accent": "#FFFFFF",
            "text-on-ok": "#FFFFFF",
            "accent": "#18191C",
            "accent-hover": "#000000",
            "accent-text": "#18191C",
            "accent-muted": "#E3E4E8",
            "live": "#BF2C34",
            "live-muted": "#FBEAEB",
            "ok": "#167A5C",
            "ok-muted": "#E6F2EE",
            "warn": "#94610F",
            "warn-muted": "#F6EEDF",
            "danger": "#BF2C34",
            "danger-muted": "#FBEAEB",
            "idle": "#666A72",
            "idle-muted": "#ECEDEF",
            "track": "#E3E4E8",
            "shadow-color": "rgba(20,22,28,.12)",
            "rim": "rgba(255,255,255,.9)",
            "scrim": "rgba(20,22,28,.35)",
            "selection": "rgba(24,25,28,.12)",
            "text-on-danger": "#FFFFFF",
            "text-on-warn": "#FFFFFF",
            "fg": "#18191C",
            "dim": "#55585F",
            "faint": "#666A72",
            "line": "rgba(0,0,0,.08)",
            "raised": "#F0F1F3",
            "accent-fg": "#FFFFFF",
        },
        "contrast": {
            "on_surface": "primary 17.6 / secondary 7.3 / tertiary 5.4",
            "worst_text": "tertiary 4.8 on surface-raised",
            "non_text": "border-strong 3.3 on surface-raised",
            "button": "white on accent 17.6",
        },
    },
}

# Ids from before the redesign. Configs written by v1.92 and earlier still say
# one of these; they are read as the nearest of the two palettes rather than
# falling back to System, which would quietly flip a daylight user to dark.
ALIASES: dict[str, str] = {
    "midnight": "dark",
    "carbon": "dark",
    "ember": "dark",
    "forest": "dark",
    "daylight": "light",
}

# System is not a palette: it is dark with light swapped in by the browser
# when Windows (or macOS) is in light mode. See root_css().
CHOICES: tuple[tuple[str, str], ...] = (("system", "System"), ("dark", "Dark"), ("light", "Light"))

DEFAULT = "system"

# Engine phase -> token name. Four independent copies of this mapping used to exist
# (web JS, tray.py, panel.py, the dead web.py) and they had already drifted -- the tray
# painted TESTING a purple that appears in no theme. Anything that needs a phase colour
# resolves it through here plus rgb(), so there is one place to change.
PHASES: dict[str, str] = {
    "IDLE": "idle",
    "ARMING": "warn",
    "STARTING": "warn",
    "TESTING": "warn",
    "LIVE": "live",
    "COOLDOWN": "idle",
    "STOPPING": "warn",
}


def resolve(name: str | None) -> str:
    """'system', 'dark' or 'light' for whatever a config says. Never raises."""
    n = str(name or "").strip().lower()
    n = ALIASES.get(n, n)
    return n if n in ("system", "dark", "light") else "system"


def get(name: str | None) -> dict:
    """The palette dict for `name`. System answers with dark, which is what a
    surface that cannot ask the OS (the tray icon, the theme-color meta) uses."""
    r = resolve(name)
    return THEMES["dark" if r == "system" else r]


def css_vars(name: str | None) -> str:
    """The BODY of a `:root{}` block -- indented `--token: value;` lines only."""
    t = get(name)
    return "\n".join(f"  --{k}: {v};" for k, v in t["vars"].items())


def root_css(name: str | None) -> str:
    """The whole palette as CSS text, ready for its own <style> element.

    For System that is dark in `:root` and light again inside a
    prefers-color-scheme block, so the page follows the OS with no script and
    keeps following it if Windows flips to light mid-session.
    """
    r = resolve(name)
    if r != "system":
        return ":root{\n" + css_vars(r) + "\n}"
    return (":root{\n" + css_vars("dark") + "\n}\n"
            "@media (prefers-color-scheme: light){:root{\n" + css_vars("light") + "\n}}")


def listing() -> list[dict]:
    """[{id, label}] for the Settings > Appearance picker, in picker order."""
    return [{"id": k, "label": label} for k, label in CHOICES]


def rgb(name: str | None, token: str) -> tuple[int, int, int]:
    """A token as an (r, g, b) tuple for the non-web surfaces (tray icon, tk panel).

    Only #rgb / #rrggbb values resolve; rgba() tokens (shadow, rim, scrim, selection)
    have no meaningful opaque form and fall back to text-primary.
    """
    t = get(name)
    value = str(t["vars"].get(token, "")).strip()
    if not value.startswith("#"):
        value = str(t["vars"]["text-primary"])
    h = value.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# A theme with a missing or extra token renders a page with a silently undefined var(),
# which is invisible in review and obvious to the user. Catch it at import instead.
for _id, _t in THEMES.items():
    if tuple(_t["vars"]) != TOKENS:
        _missing = sorted(set(TOKENS) - set(_t["vars"]))
        _extra = sorted(set(_t["vars"]) - set(TOKENS))
        raise RuntimeError(
            f"theme {_id!r} token set does not match TOKENS "
            f"(missing={_missing}, extra={_extra}, order_mismatch={not _missing and not _extra})"
        )
if DEFAULT not in dict(CHOICES):
    raise RuntimeError(f"DEFAULT theme {DEFAULT!r} is not one of the choices")
