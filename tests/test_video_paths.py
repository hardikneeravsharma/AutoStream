"""What the video endpoint is allowed to serve.

Adjusting where a clip starts needs footage from either side of it, and the
obvious way to get it was to serve the recording -- which would have meant
widening this guard to a folder full of raw source files. It is not done that
way: the app cuts a small preview into the run's own folder instead, so this
guard stays exactly as narrow as it was.

These tests are what stops it drifting: the clips folder only, video
extensions only, and nothing reachable by climbing out with "..".
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autostream import webui  # noqa: E402


@pytest.fixture
def serve(tmp_path, monkeypatch):
    """A _video call that records its answer instead of writing a socket."""
    clips = tmp_path / "Videos" / "AutoStream" / "clips"
    recordings = tmp_path / "Videos" / "AutoStream"
    elsewhere = tmp_path / "Documents"
    for d in (clips, recordings, elsewhere):
        d.mkdir(parents=True, exist_ok=True)

    app = webui.Server.__new__(webui.Server)
    app._clips_dir = staticmethod(lambda _c: clips).__func__

    h = webui._Handler.__new__(webui._Handler)
    h.app = app
    h.headers = {}

    said: list[tuple] = []
    monkeypatch.setattr(webui._Handler, "_json",
                        lambda self, obj, code=200: said.append((code, obj)))
    # A file that passes the guard reaches the sending code, which wants a
    # real socket. Stop at the point the decision has been made.
    sent: list[Path] = []

    def stop_here(self, *a, **k):
        sent.append(Path(getattr(self, "_serving", "")))
        raise _Served()

    monkeypatch.setattr(webui._Handler, "send_response", stop_here)

    cfg_obj = types.SimpleNamespace(
        record=types.SimpleNamespace(directory=str(recordings)))
    monkeypatch.setattr(webui.cfg, "load", lambda: cfg_obj)

    def call(path):
        said.clear()
        sent.clear()
        h._serving = str(path)
        try:
            h._video(str(path))
        except _Served:
            return ("SERVED", None)
        return ("REFUSED", said[0] if said else None)

    call.clips = clips
    call.recordings = recordings
    call.elsewhere = elsewhere
    return call


class _Served(Exception):
    """Raised once the guard has decided to serve, to stop before the socket."""


def _mp4(where: Path, name: str) -> Path:
    f = where / name
    f.write_bytes(b"\x00" * 64)
    return f


def test_a_clip_is_served(serve):
    what, _ = serve(_mp4(serve.clips, "clip.mp4"))
    assert what == "SERVED"


def test_a_preview_inside_the_run_is_served(serve):
    """Adjusting a cut plays a preview, and a preview lives in the run."""
    (serve.clips / "run" / "preview").mkdir(parents=True)
    what, _ = serve(_mp4(serve.clips / "run" / "preview", "clip.3600-3700.mp4"))
    assert what == "SERVED"


def test_the_recording_itself_is_still_refused(serve):
    """This endpoint never needs to reach a source file, so it never may.

    Scrubbing around a clip could have been done by streaming the recording.
    It is not, partly because AutoStream's recordings are fragmented mp4 that
    a browser cannot seek in anyway -- and partly because the alternative
    would have meant widening this guard to a folder full of raw footage.
    """
    what, answer = serve(_mp4(serve.recordings, "2026-08-27 22-59-18.mp4"))
    assert what == "REFUSED"
    assert answer[0] == 403


def test_a_file_somewhere_else_is_refused(serve):
    what, answer = serve(_mp4(serve.elsewhere, "private.mp4"))
    assert what == "REFUSED"
    assert answer[0] == 403


def test_climbing_out_with_dot_dot_is_refused(serve):
    """resolve() is what makes this true; without it the string would pass."""
    sneaky = serve.clips / ".." / ".." / ".." / "Documents" / "private.mp4"
    _mp4(serve.elsewhere, "private.mp4")
    what, answer = serve(sneaky)
    assert what == "REFUSED"
    assert answer[0] == 403


def test_something_that_is_not_a_video_is_refused(serve):
    """Being in the right folder is not enough to be worth streaming."""
    token = serve.clips / "token.json"
    token.write_text("{}", encoding="utf-8")
    what, answer = serve(token)
    assert what == "REFUSED"
    assert answer[0] == 404


def test_a_missing_file_is_refused(serve):
    what, answer = serve(serve.clips / "gone.mp4")
    assert what == "REFUSED"
    assert answer[0] == 404


# ------------------------------------------------------------ sound effects

@pytest.fixture
def serve_sound(tmp_path, monkeypatch):
    """The same shape as `serve`, for the route that streams sound effects."""
    sounds = tmp_path / "Videos" / "AutoStream" / "sounds"
    clips = tmp_path / "Videos" / "AutoStream" / "clips"
    elsewhere = tmp_path / "Documents"
    for d in (sounds, clips, elsewhere):
        d.mkdir(parents=True, exist_ok=True)

    app = webui.Server.__new__(webui.Server)
    app._clips_dir = staticmethod(lambda _c: clips).__func__
    app.sounds_dir = staticmethod(lambda _c=None: sounds).__func__

    h = webui._Handler.__new__(webui._Handler)
    h.app = app
    h.headers = {}

    said: list[tuple] = []
    monkeypatch.setattr(webui._Handler, "_json",
                        lambda self, obj, code=200: said.append((code, obj)))

    def stop_here(self, *a, **k):
        raise _Served()

    monkeypatch.setattr(webui._Handler, "send_response", stop_here)
    monkeypatch.setattr(webui.cfg, "load", lambda: types.SimpleNamespace())

    def call(path):
        said.clear()
        try:
            h._sound(str(path))
        except _Served:
            return ("SERVED", None)
        return ("REFUSED", said[0] if said else None)

    call.sounds = sounds
    call.clips = clips
    call.elsewhere = elsewhere
    return call


def _sound(where: Path, name: str) -> Path:
    f = where / name
    f.write_bytes(b"\x00" * 64)
    return f


def test_a_sound_in_the_sounds_folder_is_served(serve_sound):
    what, _ = serve_sound(_sound(serve_sound.sounds, "boom.mp3"))
    assert what == "SERVED"


def test_a_sound_anywhere_else_is_refused(serve_sound):
    """The whole reason this route has its own root instead of widening the
    video one to a second directory."""
    what, answer = serve_sound(_sound(serve_sound.elsewhere, "private.mp3"))
    assert what == "REFUSED" and answer[0] == 403


def test_the_sound_route_will_not_serve_a_clip(serve_sound):
    what, answer = serve_sound(_sound(serve_sound.clips, "clip.mp4"))
    assert what == "REFUSED" and answer[0] == 403


def test_climbing_out_of_the_sounds_folder_is_refused(serve_sound):
    _sound(serve_sound.elsewhere, "private.mp3")
    sneaky = serve_sound.sounds / ".." / ".." / ".." / "Documents" / "private.mp3"
    what, answer = serve_sound(sneaky)
    assert what == "REFUSED" and answer[0] == 403


def test_something_that_is_not_a_sound_is_refused(serve_sound):
    token = serve_sound.sounds / "token.json"
    token.write_text("{}", encoding="utf-8")
    what, answer = serve_sound(token)
    assert what == "REFUSED" and answer[0] == 404
