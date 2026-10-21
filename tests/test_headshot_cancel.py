"""A cancel reaches the headshot stage (the report: Cancel pressed, "Stopping..."
for many minutes, then the app had to be closed to run again)."""
from __future__ import annotations

from autostream.clips import headshot


def test_a_cancelled_read_decodes_no_more_kills(monkeypatch):
    calls = []
    monkeypatch.setattr(headshot, "_one", lambda *a: calls.append(a) or True)
    monkeypatch.setattr("autostream.clips.tools.media_info", lambda p: {"width": 1920, "height": 1080})
    got = headshot.read("rec.mp4", [float(t) for t in range(200)], cancelled=lambda: True)
    assert calls == [] and got == [None] * 200


def test_without_a_cancel_every_kill_is_read(monkeypatch):
    monkeypatch.setattr(headshot, "_one", lambda *a: True)
    monkeypatch.setattr("autostream.clips.tools.media_info", lambda p: {"width": 1920, "height": 1080})
    assert headshot.read("rec.mp4", [1.0, 2.0, 3.0]) == [True, True, True]


def test_annotate_passes_the_cancel_through(monkeypatch):
    seen = {}

    def fake_read(video, times, cancelled=None):
        seen["c"] = cancelled
        return []

    def stop():
        return True

    monkeypatch.setattr(headshot, "read", fake_read)
    headshot.annotate("rec.mp4", [{"time": 1.0}], cancelled=stop)
    assert seen["c"] is stop
