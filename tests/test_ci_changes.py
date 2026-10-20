"""The CI path filter: which platform's tests a change runs. A wrong answer
here is a required check that passes without having tested anything."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ci_changes import changed, targets  # noqa: E402

BOTH = {"windows": True, "macos": True}


@pytest.mark.parametrize("files,want", [
    (["autostream/webui.py"], BOTH),
    (["autostream/clips/studio.py", "README.md"], BOTH),
    (["requirements.txt"], BOTH),
    (["tests/conftest.py"], BOTH),
    (["autostream/macos/encode.py"], {"windows": False, "macos": True}),
    (["tests/macos/test_macos_ui.py", "scripts/macos/build.sh"], {"windows": False, "macos": True}),
    (["scripts/build.ps1"], {"windows": True, "macos": False}),
    (["autostream.spec", "docs/MACOS.md"], {"windows": True, "macos": False}),
    (["README.md", "docs/ROADMAP.md", "LICENSE"], {"windows": False, "macos": False}),
    # Never classified: shared, so both run.
    (["some/new/thing.py"], BOTH),
    # The CI definition itself is shared logic.
    ([".github/workflows/ci.yml"], BOTH),
])
def test_targets(files, want):
    assert targets(files) == want


def test_a_base_that_cannot_be_diffed_runs_everything():
    assert changed("") is None
    assert changed("0" * 40) is None
    assert changed("not-a-commit-anywhere") is None
