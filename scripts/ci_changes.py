"""Which platforms' tests a change needs: prints `windows=true|false` and
`macos=true|false` for $GITHUB_OUTPUT.

    python scripts/ci_changes.py BASE_SHA        (diffs BASE...HEAD)

The rule, deliberately blunt: a file that only one platform uses tests only
that platform; documentation tests neither; EVERYTHING ELSE is shared and tests
both. A new file nobody classified is therefore shared -- an unknown file
costs a few CI minutes, never a missed run.

A base that cannot be diffed (a new branch's first push, a force-push) runs
both, for the same reason.
"""
from __future__ import annotations

import subprocess
import sys

# Only the Mac build reads these (issue #193).
MAC_ONLY = ("autostream/macos/", "packaging/macos/", "scripts/macos/",
            "tests/macos/", "requirements-macos.txt",
            ".github/workflows/macos-release.yml")
# Only the Windows build reads these. The shared Python is NOT here: the
# streaming modules are imported and tested on both.
WINDOWS_ONLY = ("autostream.spec", "autostream_launcher.py", "packaging/AutoStream.iss",
                "scripts/build.ps1", "scripts/install.ps1", "scripts/verify.ps1",
                "scripts/make_shortcut.ps1", "scripts/register_task.ps1")
DOCS = ("docs/", "LICENSE")
DOC_SUFFIXES = (".md",)


def _is(path: str, prefixes: tuple[str, ...]) -> bool:
    return path in prefixes or path.startswith(tuple(p for p in prefixes if p.endswith("/")))


def targets(files: list[str]) -> dict[str, bool]:
    """-> {"windows": bool, "macos": bool} for a list of changed paths."""
    logic = [f for f in files if not (_is(f, DOCS) or f.endswith(DOC_SUFFIXES))]
    return {"windows": any(not _is(f, MAC_ONLY) for f in logic),
            "macos": any(not _is(f, WINDOWS_ONLY) for f in logic)}


def changed(base: str) -> list[str] | None:
    """The paths changed since `base`, or None when it cannot be diffed."""
    if not base or set(base) == {"0"}:
        return None
    p = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"],
                       capture_output=True, text=True)
    return p.stdout.split() if p.returncode == 0 else None


if __name__ == "__main__":
    files = changed(sys.argv[1] if len(sys.argv) > 1 else "")
    out = {"windows": True, "macos": True} if files is None else targets(files)
    for k, v in out.items():
        print(f"{k}={str(v).lower()}")
