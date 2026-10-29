"""Logs explain what went wrong, in a sentence, with the fix where there is one.

A stranger reading 'OBS is not answering: [WinError 10061]' learns nothing
they can act on. Each rule below is matched against the real line the app
writes (the format strings are in engine.py, youtube.py and clips/jobs.py),
so a reworded log message fails here rather than silently going unexplained.
"""
from __future__ import annotations

from autostream import logexplain


def test_obs_not_answering_points_at_its_settings():
    got = logexplain.explain("OBS is not answering: [WinError 10061] refused")
    assert "OBS" in got["say"] and got["fix"]["act"] == "setting:obs.path"


def test_quota_ran_out_has_no_button_to_press():
    got = logexplain.explain("thumbnail upload failed: <HttpError 403 'quotaExceeded'>")
    assert "budget" in got["say"] and got["fix"] is None


def test_a_full_drive_offers_to_change_the_folder():
    got = logexplain.explain("only 4 GB free on the recording drive (floor 5 GB) - stopping the recording; the stream carries on")
    assert "full" in got["say"] and got["fix"]["act"] == "setting:record.directory"
    got = logexplain.explain("12 GB free on the recording drive, under the 20 GB you asked to be warned at")
    assert got["fix"]["act"] == "setting:record.directory"


def test_missing_ffmpeg_offers_the_tools():
    got = logexplain.explain("clip job failed: ffmpeg not found")
    assert "ffmpeg" in got["say"] and got["fix"]["act"] == "page:clips"


def test_an_expired_sign_in_offers_to_sign_in():
    got = logexplain.explain("token refresh failed: invalid_grant")
    assert "sign" in got["say"].lower() and got["fix"]["act"] == "setting:youtube.platform"


def test_an_unknown_line_is_not_explained():
    assert logexplain.explain("something nobody planned for went wrong") is None


def test_problems_are_newest_first_and_said_once():
    lines = [
        {"level": "WARNING", "msg": "OBS is not answering: a", "ts": "1"},
        {"level": "INFO", "msg": "OBS is not answering: b", "ts": "2"},
        {"level": "WARNING", "msg": "token refresh failed: x", "ts": "3"},
        {"level": "WARNING", "msg": "OBS is not answering: c", "ts": "4"},
    ]
    got = logexplain.problems(lines)
    assert [p["ts"] for p in got] == ["4", "3"]
