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
