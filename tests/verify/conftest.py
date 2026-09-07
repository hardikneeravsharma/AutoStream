"""Isolation for the tiers that write.

The rest of the suite only reads config, so pinning AUTOSTREAM_HOME at the repo
(tests/conftest.py) is enough for it. The flow tests are different: they press
Save on the Settings page and click a theme swatch, and those routes call
cfg.save_fields, which rewrites config/config.yaml. Run against the repo home
that would edit the developer's own OBS password and web token every time the
suite ran.

paths.py computes its constants at import time from AUTOSTREAM_HOME, so setting
the variable now would be too late. What makes isolation possible instead is
that every module in the package reaches them as `paths.CONFIG_FILE` rather
than importing the constant -- verified, there is not one `from .paths import`
in autostream/. So repointing the module's attributes repoints the whole app.

The rebase is derived rather than listed. paths.py has twenty-odd Path
constants and gains one every few releases; a hand-written list would silently
stop covering the newest, which is exactly the one a new test would exercise.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from autostream import paths

# The three roots everything else in paths.py hangs off.
_ROOTS = ("ROOT", "DATA_HOME", "VIDEO_HOME")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway AUTOSTREAM_HOME the app writes into instead of the repo."""
    real = {name: getattr(paths, name) for name in _ROOTS}
    new_root = tmp_path / "home"
    video = tmp_path / "video"

    def rebased(p: Path) -> Path | None:
        """Where p should live under tmp_path, or None if it is not ours.

        Longest root first: DATA_HOME and ROOT are the same directory in a
        source checkout, and VIDEO_HOME sits outside both.
        """
        for name, root in sorted(real.items(), key=lambda kv: -len(str(kv[1]))):
            try:
                rel = p.relative_to(root)
            except ValueError:
                continue
            base = video if name == "VIDEO_HOME" else new_root
            return base / rel
        return None

    moved = 0
    for name in dir(paths):
        if name.startswith("_") or name in _ROOTS:
            continue
        value = getattr(paths, name)
        if not isinstance(value, Path):
            continue
        target = rebased(value)
        if target is not None:
            monkeypatch.setattr(paths, name, target)
            moved += 1

    # The floor: if this stops rebasing, the tests below start writing to the
    # developer's real config and would still pass.
    assert moved >= 15, (
        f"only rebased {moved} paths - isolation is not working, and these "
        "tests write to config.yaml")

    monkeypatch.setattr(paths, "ROOT", new_root)
    monkeypatch.setattr(paths, "DATA_HOME", new_root)
    monkeypatch.setattr(paths, "VIDEO_HOME", video)
    # SEED_CONFIG_DIR is ROOT/config, which paths.seed_config() copies from on
    # first run. Left pointing at the repo it would seed the real config.yaml
    # into the temp home, which is the leak this whole fixture exists to stop.
    monkeypatch.setattr(paths, "SEED_CONFIG_DIR", new_root / "config")
    monkeypatch.setenv("AUTOSTREAM_HOME", str(new_root))
    monkeypatch.setenv("AUTOSTREAM_VIDEO_HOME", str(video))

    for d in (new_root / "config", new_root / "secrets", new_root / "logs",
              video):
        d.mkdir(parents=True, exist_ok=True)
    return new_root


@pytest.fixture
def server(home: Path):
    """A real webui.Server on a real socket, with a fake engine behind it."""
    from fakes import FakeEngine, LiveServer

    eng = FakeEngine()
    srv = LiveServer(engine=eng)
    srv.engine = eng
    try:
        yield srv
    finally:
        srv.close()


@pytest.fixture
def headless(home: Path):
    """The same server with no engine at all.

    This is how the app runs during first-time setup, and webui answers a
    reduced /api/status for it. Worth exercising: several clip routes are
    reachable before there is an engine, and one of them assuming otherwise
    would break the setup wizard rather than the dashboard.
    """
    from fakes import LiveServer

    srv = LiveServer(engine=None)
    try:
        yield srv
    finally:
        srv.close()
