"""Bootstrap every test file used to repeat.

Thirty-seven files opened with the same two lines -- point AUTOSTREAM_HOME at
the repo, then put the repo on sys.path -- because there was no conftest. That
worked, but it meant the isolation every test depends on lived in whichever
file you happened to open, and a new file that forgot the env line would read
the *real* config and write the *real* state.json.

conftest is imported before any test module, so setting it here makes the
isolation structural. The per-file lines are left where they are: they use
setdefault and are now no-ops, and removing fifty of them is churn with a
non-zero chance of breaking a file nobody re-reads.

`fakes` is importable from anywhere under tests/ because of the sys.path
insert below -- including tests/verify/, which is a subdirectory.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# The app writes config, secrets, logs and state under AUTOSTREAM_HOME. Pointed
# at the repo it uses the repo's tracked config/ -- never the installed build's,
# and never %LOCALAPPDATA%.
os.environ.setdefault("AUTOSTREAM_HOME", str(REPO))
for p in (str(REPO), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)


# ON A MAC, A SECOND DOOR SHUT. The Mac build reveals files with `open` and
# picks them with AppleScript, both of which put a real window on the screen;
# both refuse when this is set (macos/shell.py, webui.clips_pick). Windows
# runs are untouched -- the harness there sets it per run, as it always has.
if sys.platform == "darwin":
    os.environ.setdefault("AUTOSTREAM_NO_DIALOGS", "1")


def pytest_collection_modifyitems(config, items):              # noqa: ARG001
    """On a Mac, skip the tests that pin Windows behaviour, each with its
    reason -- see tests/macos/mac_skips.py. A no-op anywhere else."""
    if sys.platform != "darwin":
        return
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_mac_skips", HERE / "macos" / "mac_skips.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import pytest as _pytest

    for item in items:
        why = mod.reason_for(item.nodeid)
        if why:
            item.add_marker(_pytest.mark.skip(reason=f"not on a Mac: {why}"))


import shutil                                                    # noqa: E402
from collections import namedtuple                               # noqa: E402

import pytest                                                    # noqa: E402

_Usage = namedtuple("_Usage", "total used free")


@pytest.fixture(autouse=True)
def _plenty_of_disk():
    """The engine refuses to start below rules.min_free_disk_gb, and it asks
    the REAL drive. So twelve engine tests failed on a machine that merely had
    a full C: -- each one asserting a quota or arming reason and getting
    "only 23.7 GB free" instead, and the build refused to ship over it.

    Free space is not what those tests are about, so every test sees a
    roomy disk. The one that is about it (test_a_full_disk_blocks_a_start)
    patches disk_usage itself, which overrides this.

    Swapped by hand rather than through monkeypatch: requesting monkeypatch
    here would make it the first fixture set up and so the LAST torn down,
    after test_data_home's own teardown has already deleted the sys.frozen
    that monkeypatch then tries to put back.
    """
    real = shutil.disk_usage
    shutil.disk_usage = lambda p: _Usage(16 * 1024 ** 4, 0, 16 * 1024 ** 4)
    yield
    shutil.disk_usage = real
