r"""What has changed since the last thing that shipped.

THE SAME QUESTION verify.ps1 ASKS, asked from Python. Tier 4 is gated as a
whole on whether the clip pipeline moved; some of the tests inside it are
expensive enough to deserve the same question about a narrower slice of the
tree, and a test can only ask it for itself.

EVERY UNCERTAIN ANSWER IS "RUN IT". No git, no tag, not a checkout, a git
call that fails -- all of them come back None, and the caller runs the test.
A slow suite is a nuisance; a suite that silently stopped covering something
is how a regression ships.

UNCOMMITTED AND UNTRACKED WORK COUNTS, because what is being tested is the
working tree and not HEAD.
"""
from __future__ import annotations

import functools
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _git(*args: str) -> str | None:
    try:
        p = subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                           text=True, timeout=60, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


@functools.lru_cache(maxsize=1)
def changed_since_release() -> tuple[str, ...] | None:
    """Repo-relative paths changed since the last v* tag. None = cannot say.

    Cached: a dozen tests may ask, and the answer cannot change inside one
    run of the suite.
    """
    if _git("rev-parse", "--is-inside-work-tree") is None:
        return None
    tag = _git("describe", "--tags", "--abbrev=0", "--match", "v*")
    if not tag or not tag.strip():
        return None
    diff = _git("diff", "--name-only", tag.strip())
    if diff is None:
        return None
    names = [ln.strip() for ln in diff.splitlines() if ln.strip()]

    dirty = _git("status", "--porcelain")
    for line in (dirty or "").splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:                       # a rename: the new name is
            path = path.split(" -> ")[-1]        # what is in the tree now
        names.append(path.strip().strip('"'))
    return tuple(sorted({n.replace("\\", "/") for n in names}))


def touched(*prefixes: str) -> tuple[str, ...] | None:
    """Which of `prefixes` have changed. None when git cannot say.

    A prefix is matched as a path prefix, so "autostream/clips/" means the
    directory and "autostream/clips/studio.py" means the one file.
    """
    changed = changed_since_release()
    if changed is None:
        return None
    return tuple(n for n in changed if any(n.startswith(p) for p in prefixes))


def why_skip(what: str, prefixes: tuple[str, ...], env: str) -> str:
    """"" when this must run, else the sentence saying why it will not.

    THE REASON IS ALWAYS SAID OUT LOUD. A test that quietly stopped running
    is a test nobody notices has stopped running, and a skip in a summary
    reads very much like a pass.
    """
    if os.environ.get(env):
        return ""
    hits = touched(*prefixes)
    if hits is None:
        return ""                                # cannot say -> run it
    if hits:
        return ""
    return (f"{what} has not changed since the last release, and this is "
            f"the slowest test in the suite ({env}=1 to run it anyway)")
