"""The visual language of the 2026-10-29 redesign, checked in the sheet's text.

The redesign's brief (docs/superpowers/specs/2026-10-29-ui-redesign-design.md)
names the tells of a templated page that this app used to wear: tracked-out
ALL-CAPS labels, a monospace face for small data, one radius on everything.
Each is a rule anybody can quietly reintroduce with one declaration, so each
is pinned here, scanned as text the way test_css_contrast.py does.
"""
from __future__ import annotations

import re

from autostream.ui import css as css_mod

SHEET = css_mod.CSS


def rules():
    for m in re.finditer(r"([^{}@/][^{}]*?)\{([^{}]*)\}", SHEET):
        sel = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S).strip()
        if sel and not sel.startswith("@"):
            yield sel, m.group(2)


def test_no_uppercase_text_transform():
    shouting = [sel for sel, body in rules() if re.search(r"text-transform\s*:\s*uppercase", body)]
    assert not shouting, shouting


# Monospace is for text that IS code or a log: alignment there carries meaning.
# Everywhere else a number is set in the text face with tabular figures.
MONO_ALLOWED = (
    "code,kbd,samp,pre",            # literal code elements
    ".log-line",                    # the log itself
    ".set-diag-text",               # the diagnostics report, pasted into issues
    ".field-key",                   # a config key, shown under Advanced only
    '.input.is-mono,.input[type="password"]',  # tokens and keys typed by hand
    "#setup-root textarea",         # the wizard's paste-a-key box
    ".bin-code",                    # an effect's code name
    ".st-tick",                     # editor timeline ruler: frames line up
    ".st-tr",                       # editor timeline track readouts
    ".st-io-edge",                  # the export sheet's edge list
)


def test_monospace_only_where_allowed():
    stray = [sel for sel, body in rules()
             if "var(--font-mono)" in body and sel not in MONO_ALLOWED]
    assert not stray, stray


def test_radii_are_the_three_sizes():
    for token, value in (("--radius-sm", "6px"), ("--radius-md", "8px"), ("--radius-lg", "10px")):
        assert re.search(rf"{token}\s*:\s*{value}", SHEET), token


def test_font_stack_leads_with_instrument_sans():
    m = re.search(r"--font-text\s*:\s*([^;]+);", SHEET)
    assert m and m.group(1).strip().startswith('"Instrument Sans"'), m and m.group(1)


# Upper-case words that are not shouting: acronyms, the highlight names the
# app stamps on clips, element tag names and log levels compared in code, and
# the engine's phase KEYS (compared, never shown -- their labels are tested
# separately below).
NOT_SHOUTING = {
    "OBS", "API", "GPU", "FPS", "HUD", "URL", "OAUTH", "MVP", "CS", "POST", "OK",
    "ACE", "CLUTCH", "ALMOST", "KILLS", "LAST ALIVE", "K IN", "CHAOS", "SURVIVED",
    "MATCH POINT", "PISTOL", "STREAK BREAKER", "FLAWLESS", "THRIFTY", "CLOSER",
    "TEXTAREA", "INPUT", "SELECT", "BUTTON", "VIDEO", "CAMERA",
    "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "ERR", "CRIT", "CRITICAL", "FATAL", "TRACE",
    "IDLE", "ARMING", "STARTING", "TESTING", "LIVE", "COOLDOWN", "STOPPING",
}


def test_no_shouted_words_in_markup():
    from autostream import ui
    found = {w for w in re.findall(r">\s*([A-Z][A-Z ]{2,}[A-Z])\s*<", ui.BODY)} - NOT_SHOUTING
    assert not found, sorted(found)


def test_no_shouted_words_in_script():
    from autostream import ui
    found = {w for w in re.findall(r"'([A-Z][A-Z ]{2,}[A-Z])'", ui.JS)} - NOT_SHOUTING
    assert not found, sorted(found)


def test_phase_labels_are_words_not_caps():
    from autostream import ui
    labels = re.findall(r"label:\s*'([^']+)'", ui.JS)
    assert labels, "no phase labels found"
    assert not [lab for lab in labels if lab.isupper() and len(lab) > 2], labels


def test_instrument_sans_ships_with_its_licence_and_is_loaded():
    """Bundled, not fetched: the face is embedded in the sheet so the page
    makes no network request, and the OFL travels beside it."""
    from pathlib import Path
    fonts = Path(css_mod.__file__).parent / "assets" / "fonts"
    assert (fonts / "InstrumentSans.ttf").is_file()
    assert "Open Font License" in (fonts / "OFL.txt").read_text(encoding="utf-8")
    assert re.search(r'@font-face\s*\{[^}]*font-family:\s*"Instrument Sans"', SHEET)
    assert "data:font/ttf;base64," in SHEET


def test_the_build_ships_the_ui_font():
    from pathlib import Path
    spec = (Path(css_mod.__file__).parents[2] / "autostream.spec").read_text(encoding="utf-8")
    assert "autostream/ui/assets/fonts" in spec


def test_base_text_is_13px():
    m = re.search(r"body\s*\{([^}]*)\}", SHEET)
    assert m and re.search(r"font-size\s*:\s*13px", m.group(1))
