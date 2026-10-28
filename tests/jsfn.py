"""Run one pure function from the page's script, for a test.

The page is a single script in Python strings, and most of it touches the
DOM. The few functions that turn data into words or rows do not, and those
are worth testing directly rather than through a browser tier that takes
minutes to start. This lifts a function (and any helpers named alongside it)
out of the bundle by counting braces, and runs it in Node.

Node is not a dependency of the app or of the offline suite: without it these
tests skip and say so, which is a different thing from passing.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest


def source(js: str, name: str) -> str:
    """The full text of `function NAME(...) {...}` in `js`."""
    m = re.search(rf"(?:async\s+)?function\s+{re.escape(name)}\s*\(", js)
    assert m, f"{name} is not in the page any more"
    at = js.index("{", m.end())
    depth = 0
    for i in range(at, len(js)):
        c = js[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return js[m.start():i + 1]
    raise AssertionError(f"{name} is never closed")


def call(js: str, names: list[str], expr: str, prelude: str = ""):
    """Evaluate `expr` with the named functions defined; -> its JSON value."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed: the page's pure functions are not run")
    body = prelude + "\n" + "\n".join(source(js, n) for n in names)
    prog = body + "\nprocess.stdout.write(JSON.stringify(" + expr + "));\n"
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=30,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)
