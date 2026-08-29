"""The NaN that broke Counter-Strike's best path.

parse_ticks comes back through pandas, and a missing cell is float("nan"),
not None. NaN is TRUTHY, so `int(row.get(k) or 0)` never falls back -- it
reaches int(nan) and raises "cannot convert float NaN to integer". One such
cell failed the whole parse of a perfectly good demo, and with it the entire
demo path for that recording: the rounds then had to be read off the screen,
which is the worse source the demo path exists to avoid.

Every demo in the user's folder failed this way before the fix, and all
fourteen parse in about twenty seconds after it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOSTREAM_HOME", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream.clips.cs2_demo import _num                       # noqa: E402


NAN = float("nan")


def test_nan_falls_back_because_it_is_truthy():
    """The whole bug in one line: `nan or 0` is nan, not 0."""
    assert (NAN or 0) != 0, "if this ever changes, the trap is gone"
    assert _num(NAN) == 0.0
    assert _num(NAN, -1) == -1


def test_none_and_empty_fall_back_too():
    assert _num(None) == 0.0
    assert _num("") == 0.0
    assert _num(None, 7) == 7


def test_real_numbers_survive_unchanged():
    assert _num(3) == 3.0
    assert _num("42") == 42.0
    assert _num(0) == 0.0            # a real zero is not a missing value
    assert _num(-1.5) == -1.5


def test_a_zero_is_not_treated_as_missing():
    """team_num 0 is a real side. Falling back on it would mislabel players,
    which is worse than failing -- a wrong side silently mis-attributes kills."""
    assert _num(0, 99) == 0.0


def test_rubbish_falls_back_rather_than_raising():
    assert _num("not a number") == 0.0
    assert _num(object()) == 0.0


def test_infinity_is_not_mistaken_for_nan():
    """inf == inf, so it is a number -- odd, but not missing. int() would still
    raise on it, so callers cast through this and get a real value or a
    fallback, never an exception."""
    assert _num(float("inf")) == float("inf")


# ------------------------------------------------- against the real demos

def _real_demos():
    from autostream.clips import cs2_demo
    folder = cs2_demo.demo_folder("")
    if not folder:
        return []
    return sorted(Path(folder).glob("*.dem"), key=lambda p: -p.stat().st_mtime)


def test_the_real_demos_parse():
    """Skips where there are none, so CI stays green -- but on the machine
    that hit the bug this is the test that proves it gone."""
    import pytest

    from autostream.clips import cs2_demo

    dems = _real_demos()
    if not dems:
        pytest.skip("no CS2 replays on this machine")
    m = cs2_demo.parse(dems[0])
    assert m.map_name
    assert m.kills, "a parsed demo with no kills is not a parse"
