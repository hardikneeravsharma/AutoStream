"""Every setting the app reads has to be changeable in the app.

FROM AN AUDIT. Four settings existed in the config, were read on every run, and
were not on the Settings page -- so the only way to change any of them was to
hand-edit the YAML of the INSTALLED copy, which is not a thing anybody would
guess. One of them decides whether an uploaded clip goes out public.

This test is the guard: a setting that is read must be offered.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autostream import cfg, schema                     # noqa: E402

# Reads that are not settings: a method call, or a local that happens to match.
NOT_SETTINGS = {"obs.get"}


def _sections() -> set[str]:
    """The config's real top-level sections.

    The patterns below look for `c.<something>.<something>`, and `c` is an
    ordinary name for an ordinary variable -- a caption, a clip, a character.
    Without this, `c.text.strip()` in a loop over captions reads as a setting
    called text.strip and the test fails for a reason that has nothing to do
    with settings.

    Filtering on the real sections keeps every bug this was written for: the
    one that prompted it, rules.upload_daily_max, is under a real section and
    would still be caught.
    """
    return {k for k, v in cfg.DEFAULTS.items() if isinstance(v, dict)}


def _reads() -> set[str]:
    """Every config path the code actually reads, however it reads it."""
    src = ""
    for f in (Path(__file__).resolve().parents[1] / "autostream").rglob("*.py"):
        src += f.read_text(encoding="utf-8", errors="ignore")
    found = set()
    # The names a Config gets bound to across the codebase.
    holder = r"(?<![A-Za-z_.])(?:c|cfg_now|self\.cfg|config|conf)"
    # plain attribute access: c.clips.min_kills
    for m in re.finditer(holder + r"\.([a-z_]+)\.([a-z_]+)", src):
        found.add(f"{m.group(1)}.{m.group(2)}")
    # ...and through getattr, which is how rules.upload_daily_max hid from this
    # check while two error messages told people to change it on the page.
    getter = (r"getattr\(\s*" + holder +
              r"\.([a-z_]+)\s*,\s*['\"]([a-z_]+)['\"]")
    for m in re.finditer(getter, src):
        found.add(f"{m.group(1)}.{m.group(2)}")
    real = _sections()
    found = {f for f in found if f.split(".")[0] in real}
    return found - NOT_SETTINGS


def test_every_setting_the_code_reads_is_on_the_settings_page():
    offered = set(schema.flatten(cfg.load()))
    missing = sorted(_reads() - offered)
    assert missing == [], (
        "read in code but not offered on the Settings page, so it can only be "
        f"changed by hand-editing YAML: {missing}")


def test_the_four_that_were_missing_are_there_now():
    offered = set(schema.flatten(cfg.load()))
    for path in ("clips.voice_name", "clips.upload_privacy",
                 "clips.upload_title", "clips.upload_description"):
        assert path in offered, path


def test_a_choice_setting_refuses_a_value_outside_its_options():
    """Being on the page also means being validated. Privacy decides whether a
    clip goes out public, so 'whatever was in the YAML' is not good enough."""
    assert schema.validate("clips.upload_privacy", "public") is None
    assert schema.validate("clips.upload_privacy", "unlisted") is None
    assert schema.validate("clips.upload_privacy", "nonsense")


def test_every_offered_setting_actually_exists_on_the_config():
    """The reverse: a field on the page whose path the config does not have
    would render, accept a value, and save it nowhere."""
    c = cfg.load()
    for path in schema.flatten(c):
        section, _, key = path.partition(".")
        obj = getattr(c, section, None)
        assert obj is not None, f"no config section for {path}"
        assert getattr(obj, key, "<<missing>>") != "<<missing>>", path


def test_the_upload_token_help_lists_the_tokens_that_exist():
    """Help that names a token which does not exist is a promise the app
    breaks; help that omits one hides a feature. Both are cheap to get wrong
    and cheap to check."""
    import re

    from autostream.clips.upload import UploadJob

    # The tokens _text_for actually builds.
    src = __import__("inspect").getsource(UploadJob._text_for)
    real = set(re.findall(r'^\s+"([a-z]+)":', src, re.M))
    assert real, "could not find the token table"

    for path in ("clips.upload_title", "clips.upload_description"):
        help_text = schema.FIELDS_BY_PATH[path]["help"]
        named = set(re.findall(r"\{([a-z]+)\}", help_text))
        assert named <= real, f"{path} names tokens that do not exist: {named - real}"
    # ...and the title help should name all of them, since it is the one place
    # anybody looks for the list.
    title_help = schema.FIELDS_BY_PATH["clips.upload_title"]["help"]
    named = set(re.findall(r"\{([a-z]+)\}", title_help))
    assert named == real, f"missing from the help: {sorted(real - named)}"
