"""Design tokens: the single source of truth for every colour in AutoStream.

WHY THIS FILE EXISTS
    The UI has no build step, so there is no Sass/Tailwind layer to hold a palette.
    Themes therefore live here as plain data and are emitted as CSS custom properties
    into the `:root{}` block of the one page the server serves. Nothing downstream --
    not css.py, not any page module -- is allowed to write a literal colour, so a new
    theme is purely an addition to THEMES and costs no other edit.

WHY THE TOKENS ARE ROLE-NAMED AND NOT COLOUR-NAMED
    Tokens name a job (`surface-sunken`, `border-strong`, `text-on-accent`), never a
    hue. That is what lets `daylight` invert the whole system without a single
    conditional in the stylesheet: in a light theme elevation comes from shadow rather
    than from a lighter fill, so `surface-raised` and `surface-overlay` are both pure
    white on purpose and the shadow scale does the work instead.

WHY THE SIX LEGACY ALIASES ARE STILL HERE
    `fg`, `dim`, `faint`, `line`, `raised` and `accent-fg` duplicate the semantic names.
    The old ui_assets.py stylesheet still references them, and its JavaScript resolves
    some of them *by name* at runtime through getComputedStyle, so dropping them would
    fail silently rather than loudly. They are aliases, not a second palette: keep them
    in step with the semantic token they mirror, and delete them only once the last
    `var(--line)` / `cssv('faint')` call site is gone.

CONTRAST
    Every ratio quoted in the per-theme `contrast` notes was computed with the WCAG 2.x
    relative-luminance formula, not estimated. No token is excused at 3:1: the worst
    text pair in the whole system is 4.92:1 (carbon `text-tertiary` on `surface-active`)
    and `border-strong` -- which bounds every interactive control -- clears 3:1 against
    every surface it can sit on, satisfying WCAG 1.4.11 for non-text contrast.

    Consequence for maintainers: the state colours in `daylight` are dark bronze, brick
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
    "midnight": {
        "label": "Midnight",
        "dark": True,
        # The blue hour. A cool blue-graphite room under a muted cyanotype lamp, with
        # warm bone-white text rather than blue-white -- that tension is what keeps it
        # from reading clinical. The default, and the theme most users will ever see.
        "vars": {
            "bg": "#0C1016",
            "chrome": "#090D12",
            "surface": "#12171F",
            "surface-raised": "#1A212B",
            "surface-sunken": "#080B10",
            "surface-overlay": "#1F2732",
            "surface-hover": "#171D27",
            "surface-active": "#222A36",
            "border-subtle": "#1F2833",
            "border-strong": "#68768A",
            "border-focus": "#58A6FF",
            "text-primary": "#E9EFF7",
            "text-secondary": "#AAB8C9",
            "text-tertiary": "#909EB0",
            "text-on-accent": "#04121F",
            "accent": "#4D9FFF",
            "accent-hover": "#6FB2FF",
            "accent-text": "#7CB8FF",
            "accent-muted": "#0D1B2B",
            "live": "#FF6B6B",
            "live-muted": "#2A0F11",
            "ok": "#4FC97A",
            "ok-muted": "#0A1A11",
            "warn": "#E3AC3B",
            "warn-muted": "#1E1708",
            "danger": "#FF7A70",
            "danger-muted": "#2B100E",
            "idle": "#909EB0",
            "idle-muted": "#161B23",
            "track": "#1C242F",
            "shadow-color": "rgba(2,5,10,.62)",
            "rim": "rgba(255,255,255,.055)",
            "scrim": "rgba(4,7,12,.66)",
            "selection": "rgba(77,159,255,.30)",
            "text-on-danger": "#1A0706",
            "text-on-warn": "#1A1305",
            "fg": "#E9EFF7",
            "dim": "#AAB8C9",
            "faint": "#909EB0",
            "line": "#1F2833",
            "raised": "#1A212B",
            "accent-fg": "#04121F",
        },
        "contrast": {
            "on_surface": "primary 15.54 / secondary 8.91 / tertiary 6.60",
            "worst_text": "primary 12.50, secondary 7.17, tertiary 5.30 (surface-active)",
            "non_text": "border-strong 3.26 worst, border-focus 7.55 on bg",
            "button": "text-on-accent on accent 6.94, on accent-hover 8.54",
        },
    },
    "carbon": {
        "label": "Carbon",
        "dark": True,
        # Rolled steel. Near-black, but the neutral is warm graphite (~30deg hue at ~4%
        # saturation) so it reads as anodised metal rather than a default #111. The lamp
        # is bone-white by design: colour appears only when something is happening.
        #
        # MANDATORY MITIGATION: the accent is luminance, not hue, and sits close to
        # text-primary (15.10 vs 16.19 on surface). This theme must never signal
        # interactivity by colour alone -- links carry an underline, and the active rail
        # item shows the bone indicator bar plus an accent-muted plate. Note that
        # accent-muted is a slightly *lighter* warm plate here, not a dark one, so a
        # selected nav item reads as an inset panel with a white label.
        "vars": {
            "bg": "#0C0B0A",
            "chrome": "#080807",
            "surface": "#141311",
            "surface-raised": "#1C1A18",
            "surface-sunken": "#0A0908",
            "surface-overlay": "#232120",
            "surface-hover": "#1F1D1B",
            "surface-active": "#282523",
            "border-subtle": "#252220",
            "border-strong": "#726B64",
            "border-focus": "#EDE7DD",
            "text-primary": "#F2EFEA",
            "text-secondary": "#B0A9A0",
            "text-tertiary": "#9A9188",
            "text-on-accent": "#0C0B0A",
            "accent": "#EDE7DD",
            "accent-hover": "#FFFBF4",
            "accent-text": "#EDE7DD",
            "accent-muted": "#211E1B",
            "live": "#FF6672",
            "live-muted": "#260A0C",
            "ok": "#57CE7C",
            "ok-muted": "#08170C",
            "warn": "#E8BC55",
            "warn-muted": "#191204",
            "danger": "#F97970",
            "danger-muted": "#250B0A",
            "idle": "#9A9188",
            "idle-muted": "#1A1715",
            "track": "#1F1D1B",
            "shadow-color": "rgba(0,0,0,.70)",
            "rim": "rgba(255,250,242,.05)",
            "scrim": "rgba(0,0,0,.72)",
            "selection": "rgba(237,231,221,.22)",
            "text-on-danger": "#190605",
            "text-on-warn": "#191204",
            "fg": "#F2EFEA",
            "dim": "#B0A9A0",
            "faint": "#9A9188",
            "line": "#252220",
            "raised": "#1C1A18",
            "accent-fg": "#0C0B0A",
        },
        "contrast": {
            "on_surface": "primary 16.19 / secondary 7.98 / tertiary 5.99",
            "worst_text": "tertiary 4.92 on surface-active -- the tightest pair in the system",
            "non_text": "border-strong 3.06 worst, border-focus 15.99 on bg",
            "button": "text-on-accent on accent 15.99",
        },
    },
    "ember": {
        "label": "Ember",
        "dark": True,
        # The darkroom. An espresso-toned iron room under a safelight. Deliberately not
        # warm-cream-plus-terracotta: the room is dark and desaturated and trends more
        # neutral as surfaces rise, so it never becomes a wash of brown. The orange is a
        # lamp, not a paint.
        #
        # HUE SEPARATION: the one theme where accent (~22deg), live (~354deg) and warn
        # (~44deg) sit within ~30deg of each other. warn is pushed to a distinctly
        # yellower gold, live always renders the LIVE wordmark beside its dot, and the
        # accent budget forbids the accent from ever appearing as a status indicator.
        "vars": {
            "bg": "#140F0C",
            "chrome": "#0E0A08",
            "surface": "#1C1613",
            "surface-raised": "#251E19",
            "surface-sunken": "#0F0B09",
            "surface-overlay": "#2D2420",
            "surface-hover": "#231C18",
            "surface-active": "#302722",
            "border-subtle": "#2E241E",
            "border-strong": "#877063",
            "border-focus": "#FF8A4C",
            "text-primary": "#F6EDE4",
            "text-secondary": "#C0AC9C",
            "text-tertiary": "#AC9583",
            "text-on-accent": "#1A0B04",
            "accent": "#FF8A4C",
            "accent-hover": "#FF9D68",
            "accent-text": "#FF9D68",
            "accent-muted": "#2A1108",
            "live": "#FF6070",
            "live-muted": "#2A0B0F",
            "ok": "#63CE8A",
            "ok-muted": "#0A1A0F",
            "warn": "#F0C24A",
            "warn-muted": "#1C1405",
            "danger": "#FD6A62",
            "danger-muted": "#2A0D0B",
            "idle": "#AC9583",
            "idle-muted": "#1D1714",
            "track": "#261F1A",
            "shadow-color": "rgba(10,4,2,.66)",
            "rim": "rgba(255,228,208,.055)",
            "scrim": "rgba(12,7,4,.70)",
            "selection": "rgba(255,138,76,.28)",
            "text-on-danger": "#1F0605",
            "text-on-warn": "#1C1405",
            "fg": "#F6EDE4",
            "dim": "#C0AC9C",
            "faint": "#AC9583",
            "line": "#2E241E",
            "raised": "#251E19",
            "accent-fg": "#1A0B04",
        },
        "contrast": {
            "on_surface": "primary 15.47 / secondary 8.20 / tertiary 6.29",
            "worst_text": "primary 12.61, secondary 6.69, tertiary 5.13 (surface-active)",
            "non_text": "border-strong 3.27 worst, border-focus 8.15 on bg",
            "button": "text-on-accent on accent 8.22, on accent-hover 9.40",
        },
    },
    "forest": {
        "label": "Forest",
        "dark": True,
        # Understory. A deep pine room with blue in the shadows, lit by a muted citron --
        # a hue almost nothing else uses, which is exactly why it feels chosen rather
        # than defaulted. Citron also solves the problem every green theme has: the
        # accent no longer collides with `ok`, which stays a true leaf green ~60deg away.
        # warn is pushed to amber-orange (~32deg) to open the gap from the citron accent.
        "vars": {
            "bg": "#0C1210",
            "chrome": "#080D0B",
            "surface": "#121A17",
            "surface-raised": "#18231F",
            "surface-sunken": "#080E0C",
            "surface-overlay": "#1E2A25",
            "surface-hover": "#16211D",
            "surface-active": "#213029",
            "border-subtle": "#1F2C27",
            "border-strong": "#5E7C70",
            "border-focus": "#AFC85C",
            "text-primary": "#ECEFE7",
            "text-secondary": "#A6B4AA",
            "text-tertiary": "#8DA096",
            "text-on-accent": "#0E1405",
            "accent": "#AFC85C",
            "accent-hover": "#C2DA70",
            "accent-text": "#B9D067",
            "accent-muted": "#181D0C",
            "live": "#FF6470",
            "live-muted": "#2A0C10",
            "ok": "#4FC781",
            "ok-muted": "#07180D",
            "warn": "#E49B44",
            "warn-muted": "#1F1206",
            "danger": "#FD6A62",
            "danger-muted": "#2A0C0A",
            "idle": "#8DA096",
            "idle-muted": "#161D1A",
            "track": "#182521",
            "shadow-color": "rgba(2,7,5,.64)",
            "rim": "rgba(226,255,236,.05)",
            "scrim": "rgba(4,9,7,.68)",
            "selection": "rgba(175,200,92,.28)",
            "text-on-danger": "#1F0605",
            "text-on-warn": "#1F1206",
            "fg": "#ECEFE7",
            "dim": "#A6B4AA",
            "faint": "#8DA096",
            "line": "#1F2C27",
            "raised": "#18231F",
            "accent-fg": "#0E1405",
        },
        "contrast": {
            "on_surface": "primary 15.24 / secondary 8.21 / tertiary 6.41",
            "worst_text": "primary 11.89, secondary 6.40, tertiary 5.00 (surface-active)",
            "non_text": "border-strong 3.25 worst, border-focus 10.13 on bg",
            "button": "text-on-accent on accent 10.03, on accent-hover 12.09",
        },
    },
    "daylight": {
        "label": "Daylight",
        "dark": False,
        # Studio daylight. Cool paper, warm ink -- the inverse of the cliche. The body is
        # blue-grey paper, cards are true white floating on shadow alone, and the chassis
        # is a cooler tinted panel like a machined bezel. The lamp is petrol teal, the
        # lights-on counterpart of midnight's cyanotype.
        #
        # DO NOT lighten `chrome`, `surface-sunken` or `surface-active` without re-running
        # the contrast check: every text token here was tuned against `chrome`, which is
        # the true worst ground in a light theme, not white.
        "vars": {
            "bg": "#EDF0F3",
            "chrome": "#E4E9ED",
            "surface": "#FFFFFF",
            "surface-raised": "#FFFFFF",
            "surface-sunken": "#E7EBEF",
            "surface-overlay": "#FFFFFF",
            "surface-hover": "#F2F5F8",
            "surface-active": "#E8EDF2",
            "border-subtle": "#DDE3E9",
            "border-strong": "#767D85",
            "border-focus": "#0F6E85",
            "text-primary": "#16191C",
            "text-secondary": "#48525D",
            "text-tertiary": "#5A646F",
            "text-on-accent": "#FFFFFF",
            "accent": "#0F6E85",
            "accent-hover": "#0B5A6D",
            "accent-text": "#0B6070",
            "accent-muted": "#E4EFF2",
            "live": "#C02730",
            "live-muted": "#F8E9EA",
            "ok": "#116B39",
            "ok-muted": "#E5F0E9",
            "warn": "#7F5300",
            "warn-muted": "#F2EDE4",
            "danger": "#B02218",
            "danger-muted": "#F7E8E7",
            "idle": "#5A646F",
            "idle-muted": "#ECEEF0",
            "track": "#DDE3E9",
            "shadow-color": "rgba(19,29,39,.13)",
            "rim": "rgba(255,255,255,.90)",
            "scrim": "rgba(18,25,32,.38)",
            "selection": "rgba(15,110,133,.20)",
            "text-on-danger": "#FFFFFF",
            "text-on-warn": "#FFFFFF",
            "fg": "#16191C",
            "dim": "#48525D",
            "faint": "#5A646F",
            "line": "#DDE3E9",
            "raised": "#FFFFFF",
            "accent-fg": "#FFFFFF",
        },
        "contrast": {
            "on_surface": "primary 17.65 / secondary 7.95 / tertiary 6.02",
            "worst_text": "primary 14.44, secondary 6.51, tertiary 4.93 (on chrome)",
            "non_text": "border-strong 3.48 worst (surface-sunken), 4.16 on white",
            "button": "white on accent 5.85, on accent-hover 7.78",
        },
    },
}

DEFAULT = "midnight"

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


def get(name: str | None) -> dict:
    """The theme dict for `name`, falling back to DEFAULT. Never raises."""
    return THEMES.get(name or "", THEMES[DEFAULT])


def css_vars(name: str | None) -> str:
    """The BODY of a `:root{}` block -- indented `--token: value;` lines only.

    webui.page() wraps this in ":root{" ... "}" itself, so emitting a selector,
    a brace or an @media block here would produce invalid CSS.
    """
    t = get(name)
    return "\n".join(f"  --{k}: {v};" for k, v in t["vars"].items())


def listing() -> list[dict]:
    """[{id, label, dark, swatch}] for the Settings > Appearance picker.

    The swatch is bg / surface / accent / live: room, plate, lamp, tally -- the four
    values that carry a theme's whole identity at 88px.
    """
    return [
        {
            "id": k,
            "label": v["label"],
            "dark": v["dark"],
            "swatch": [
                v["vars"]["bg"],
                v["vars"]["surface"],
                v["vars"]["accent"],
                v["vars"]["live"],
            ],
        }
        for k, v in THEMES.items()
    ]


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
if DEFAULT not in THEMES:
    raise RuntimeError(f"DEFAULT theme {DEFAULT!r} is not in THEMES")
