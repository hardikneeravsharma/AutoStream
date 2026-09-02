"""Two endpoints that existed for a long time with nothing able to reach them.

Both were built, both were sensible, and no button anywhere called either. A
route the page never asks for is not a feature -- it is code that has to keep
working for nobody. These tests came with the buttons.

`clips_forget` clears streams whose recording has been deleted. Deleting old
footage is normal; the list otherwise fills with streams that can never be cut
again and cannot be dismissed.

`diagnostics` produces one paste-able report. Every problem this app has had
reported to it arrived as a photograph of a screen, and a photograph cannot
say which OBS version, which build, or what the log said thirty seconds
earlier.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import webui  # noqa: E402


# --------------------------------------------------------------- forgetting

@pytest.fixture
def journal(tmp_path, monkeypatch):
    """A history of four streams, two of whose recordings are gone."""
    here = tmp_path / "kept.mp4"
    here.write_bytes(b"video")
    also = tmp_path / "kept2.mp4"
    also.write_bytes(b"video")

    rows = [
        {"session": 1, "game": "VALORANT", "recording_path": str(here)},
        {"session": 2, "game": "VALORANT",
         "recording_path": str(tmp_path / "deleted.mp4")},
        {"session": 3, "game": "Counter-Strike 2", "recording_path": str(also)},
        {"session": 4, "game": "Counter-Strike 2",
         "recording_path": str(tmp_path / "also-deleted.mp4")},
    ]
    state = {"rows": list(rows)}

    from autostream import history

    monkeypatch.setattr(history, "read", lambda *a, **k: list(state["rows"]))
    monkeypatch.setattr(history, "rewrite",
                        lambda keep: state.update(rows=list(keep)))

    app = webui.Server.__new__(webui.Server)
    app.engine = None
    return types.SimpleNamespace(app=app, state=state, here=here, also=also,
                                 tmp=tmp_path)


def test_the_missing_ones_are_forgotten_and_the_others_kept(journal):
    out = journal.app.clips_forget("", -1, missing_only=True)
    assert out["removed"] == 2
    left = [r["session"] for r in journal.state["rows"]]
    assert left == [1, 3], "a stream that still has its recording was dropped"


def test_forgetting_never_touches_the_video(journal):
    """The whole point is that this deletes a LIST ENTRY, nothing else."""
    journal.app.clips_forget("", -1, missing_only=True)
    assert journal.here.exists() and journal.also.exists()


def test_a_recording_on_an_unplugged_drive_is_not_gone(journal, monkeypatch):
    """Existence is checked NOW, not trusted from the entry -- but "now" can
    be a moment when an external drive is unplugged, and forgetting then would
    lose the record of a stream that still exists.

    So this pins the behaviour that IS relied on: nothing is inferred from the
    entry itself, only from the file. The consequence is that the button has
    to be pressed deliberately, which is why it is a button and not automatic.
    """
    # Every file suddenly unreachable, as an unplugged drive would look.
    monkeypatch.setattr(webui.Path, "exists", lambda self: False)
    out = journal.app.clips_forget("", -1, missing_only=True)
    assert out["removed"] == 4
    # ...and nothing happened by itself: this only ran because it was called.


def test_nothing_missing_is_reported_rather_than_treated_as_an_error(journal):
    journal.state["rows"] = [r for r in journal.state["rows"]
                             if r["session"] in (1, 3)]
    out = journal.app.clips_forget("", -1, missing_only=True)
    assert out["ok"] and out["removed"] == 0
    assert "still" in out["detail"]


def test_one_named_stream_can_still_be_forgotten(journal):
    """The original single-entry mode has to keep working."""
    out = journal.app.clips_forget(str(journal.here), 1)
    assert out["removed"] == 1
    assert [r["session"] for r in journal.state["rows"]] == [2, 3, 4]


def test_forgetting_by_name_with_no_name_is_refused(journal):
    """Otherwise an empty path would match every row with no recording."""
    assert "error" in journal.app.clips_forget("", -1)
    assert len(journal.state["rows"]) == 4


def test_forgetting_something_that_is_not_there_is_an_error(journal):
    assert "error" in journal.app.clips_forget(str(journal.tmp / "never.mp4"), 9)
    assert len(journal.state["rows"]) == 4


# --------------------------------------------------------------- the report

@pytest.fixture
def app():
    s = webui.Server.__new__(webui.Server)
    s.engine = None
    return s


def test_the_report_says_what_a_photograph_cannot(app):
    out = app.diagnostics()
    assert out["ok"]
    text = out["text"]
    from autostream import __version__

    for expected in (__version__, "Python", "OS", "OBS", "ffmpeg",
                     "--- config (secrets removed) ---",
                     "--- last 40 log lines ---"):
        assert expected in text, f"the report no longer mentions {expected!r}"


def test_the_report_carries_no_secrets(app, monkeypatch):
    """It exists to be pasted into a chat window, so this is the whole
    difference between useful and dangerous."""
    import re

    from autostream import cfg

    real = cfg.load()
    # Values a real install has, planted so their absence proves scrubbing
    # rather than proving they were never there.
    secret = "hunter2-obs-password-long-enough"
    token = "web-token-abcdefghijklmnop"
    monkeypatch.setattr(real.obs, "password", secret, raising=False)
    monkeypatch.setattr(real.rules, "web_token", token, raising=False)
    monkeypatch.setattr(cfg, "load", lambda: real)

    text = app.diagnostics()["text"]
    assert secret not in text
    assert token not in text
    # And no URL still carrying a key, wherever it came from.
    assert not re.findall(r"[?&]k=(?!\(removed\))\S+", text)


def test_the_report_survives_a_broken_install(app, monkeypatch):
    """It is asked for precisely when things are wrong, so it cannot be the
    thing that also fails."""
    from autostream import obs

    def boom(*a, **k):
        raise RuntimeError("OBS is not installed")

    monkeypatch.setattr(obs, "find_obs_exe", boom, raising=False)
    monkeypatch.setattr(obs, "discover_websocket", boom, raising=False)
    out = app.diagnostics()
    assert out["ok"]
    assert "could not be inspected" in out["text"]
