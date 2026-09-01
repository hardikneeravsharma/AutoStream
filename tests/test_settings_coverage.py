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


def _reads() -> set[str]:
    src = ""
    for f in (Path(__file__).resolve().parents[1] / "autostream").rglob("*.py"):
        src += f.read_text(encoding="utf-8", errors="ignore")
    found = set()
    for m in re.finditer(r"\b(?:c|cfg_now|self\.cfg|config|conf)\.([a-z_]+)\.([a-z_]+)",
                         src):
        found.add(f"{m.group(1)}.{m.group(2)}")
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
