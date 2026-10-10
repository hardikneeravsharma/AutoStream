"""The Studio's instant preview and its background render.

An edit on the timeline used to be invisible until it was rendered: delete a
shot, press Render, wait 10-20 s, then find out whether it was the right shot.
The page now plays the timeline straight off the clip files (studio_pvAt in
ui/studio.py) and renders by itself once the edits stop. Two things here have
to be right without a browser:

  preview_at   the arithmetic the page's player runs -- which clip, which
               second of it, how fast -- checked against the renderer's own
               segments, so the preview cannot drift from what gets rendered.
               The browser test (tests/verify/test_ui_playwright.py) holds
               the page's copy of it to this one.
  the guard    a background render never starts while live, recording or
               cutting clips, and never displaces a render the user asked for.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from test_studio import Shape, _clips, _run

from autostream import cfg, webui
from autostream import state as st
from autostream.clips import studio


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "clips"
    _run(r, "2026-09-14_0045_VALORANT", "VALORANT",
         [{"start": 100.0, "end": 108.0}, {"start": 200.0, "end": 214.0, "kills": 2},
          {"start": 300.0, "end": 305.5}, {"start": 400.0, "end": 410.0}],
         kills=[103.5, 203.0, 206.5, 303.5, 405.0])
    (r / "reels").mkdir()
    return r


def _project(root, **shot):
    proj, _ = studio.plan(_clips(root), "montage", shape=Shape(bpm=120.0))
    proj["song"] = ""
    for s in proj["shots"]:
        s.update(shot)
    got, derived, _ = studio.normalise(proj, root, probe=lambda p: 30.0)
    return got, derived


# ------------------------------------------------------------- preview_at

def test_every_shot_starts_on_the_frame_the_render_starts_it_on(root):
    """The renderer's segment begins `head` frames of handle before the shot,
    at src_start; the shot itself is src_start + head. The preview must open
    each shot on that same source second, or every cut shows the wrong frame."""
    proj, derived = _project(root)
    segs = studio.segments(proj, derived, has_audio=lambda p: True)
    for row, seg in zip(derived["shots"], segs):
        at = studio.preview_at(derived, row["start"])
        assert at["shot"] == row["index"]
        assert at["src"] == pytest.approx(seg.src_start + seg.head / studio.FPS, abs=2e-3)


@pytest.mark.parametrize("speed", ["s00", "s01", "s02", "s03", "s04", "s05", "s06"])
def test_the_kill_plays_on_its_mark_at_every_speed(root, speed):
    """However a shot is ramped, its kill's own source second is on screen
    exactly when the timeline says the kill lands."""
    proj, derived = _project(root, speed=speed)
    for row, shot in zip(derived["shots"], proj["shots"]):
        at = studio.preview_at(derived, row["kill_reel"])
        assert at["shot"] == row["index"]
        assert at["src"] == pytest.approx(shot["kill"], abs=2e-3), (speed, row["index"])


def test_a_freeze_holds_the_kill_and_what_follows_plays_late(root):
    """k04 holds the kill's frame for 0.4 s and replaces footage rather than
    lengthening the shot -- segment_command loops the frame at kill_at. The
    preview pauses on it and then carries on from the next source second."""
    proj, derived = _project(root, fx=["k04"], speed="s00")
    row = derived["shots"][1]
    assert row["freeze"] == pytest.approx(0.4)
    kill = proj["shots"][1]["kill"]
    held = studio.preview_at(derived, row["kill_reel"] + 0.2)
    assert held == {"shot": 1, "src": pytest.approx(kill, abs=2e-3), "rate": 0.0}
    d = min(0.1, (row["end"] - row["kill_reel"] - 0.4) / 2)
    assert d > 0, "the shot ends inside its own freeze; pick another"
    after = studio.preview_at(derived, row["kill_reel"] + 0.4 + d)
    assert after["shot"] == 1 and after["rate"] == 1.0
    assert after["src"] == pytest.approx(kill + d, abs=2e-3)


def test_slow_motion_plays_slowly_and_a_held_frame_does_not_play(root):
    proj, derived = _project(root, speed="s01")
    row = derived["shots"][0]
    assert studio.preview_at(derived, row["start"] + 0.1)["rate"] == 0.5
    # Past the last shot is the long ending's hold: the last frame, still.
    end = studio.preview_at(derived, derived["length"] + 5)
    assert end["shot"] == len(derived["shots"]) - 1 and end["rate"] == 0.0


def test_a_deleted_shot_is_gone_from_the_preview_with_nothing_rendered(root):
    """The case the user asked for: the shot after the deleted one now plays
    where the deleted one did, and the reel is that much shorter."""
    proj, derived = _project(root)
    gone = proj["shots"][1]
    proj["shots"].pop(1)
    after = studio.derive(proj)
    assert after["length"] == pytest.approx(derived["length"] - gone["duration"], abs=1e-3)
    at = studio.preview_at(after, after["shots"][1]["start"] + 0.01)
    assert at["shot"] == 1
    assert proj["shots"][1]["clip"] != gone["clip"] or proj["shots"][1]["kill"] != gone["kill"]


def test_an_empty_reel_has_nothing_to_show():
    assert studio.preview_at({"shots": []}, 3.0) == {"shot": -1, "src": 0.0, "rate": 0.0}


# ---------------------------------------------------------------- the jobs

class _Job:
    """A render that runs until it is cancelled or released."""

    def __init__(self, auto: bool):
        self.auto = auto
        self.state = "running"
        self.cancelled = False
        self._go = threading.Event()

    def run(self):
        self._go.wait(5)
        time.sleep(0.05)            # ffmpeg takes a moment to die
        self.state = "cancelled" if self.cancelled else "done"

    def cancel(self):
        self.cancelled = True
        self._go.set()

    def snapshot(self):
        return {"state": self.state, "auto": self.auto}


def test_a_background_render_makes_way_and_is_waited_for():
    run = studio.Runner()
    job = _Job(auto=True)
    assert run.start(job) == ""
    assert run.yield_auto() is True
    assert job.cancelled and job.state == "cancelled"
    assert not run.busy()


def test_a_render_the_user_started_is_never_displaced():
    run = studio.Runner()
    job = _Job(auto=False)
    assert run.start(job) == ""
    assert run.yield_auto() is False
    assert not job.cancelled and run.busy()
    job._go.set()


def test_nothing_running_is_nothing_in_the_way():
    assert studio.Runner().yield_auto() is True


def test_the_job_says_whether_nobody_asked_for_it(root, tmp_path):
    proj, derived = _project(root)
    assert studio.StudioJob(proj, derived, root, tmp_path / "a.mp4", auto=True).snapshot()["auto"] is True
    assert studio.StudioJob(proj, derived, root, tmp_path / "a.mp4").snapshot()["auto"] is False


# ---------------------------------------------------------------- the guard

def _server(phase=st.IDLE, recording=False):
    srv = webui.Server.__new__(webui.Server)
    srv.engine = SimpleNamespace(state=SimpleNamespace(phase=phase, recording=recording))
    return srv


@pytest.fixture
def no_clip_job(monkeypatch):
    monkeypatch.setattr("autostream.clips.runner", lambda: SimpleNamespace(busy=lambda: False))


def test_idle_is_the_only_time_it_renders_by_itself(no_clip_job):
    assert _server().studio_auto_held() == ""
    for phase in (st.ARMING, st.STARTING, st.TESTING, st.LIVE, st.COOLDOWN, st.STOPPING):
        assert "live" in _server(phase).studio_auto_held(), phase


def test_a_recording_holds_it(no_clip_job):
    assert "recording" in _server(recording=True).studio_auto_held()


def test_a_clip_job_holds_it(monkeypatch):
    monkeypatch.setattr("autostream.clips.runner", lambda: SimpleNamespace(busy=lambda: True))
    assert "clip job" in _server().studio_auto_held()


def test_switched_off_in_settings_it_never_starts(monkeypatch, no_clip_job):
    c = cfg.load()
    c["clips"] = dict(c["clips"], auto_render=False)
    monkeypatch.setattr(cfg, "load", lambda: cfg.Config(c))
    assert "off" in _server().studio_auto_held()


def test_it_is_on_unless_switched_off():
    assert cfg.DEFAULTS["clips"]["auto_render"] is True


def test_the_server_refuses_a_background_render_while_live(monkeypatch, root, no_clip_job):
    """The page checks too, but hiding a timer is not what keeps an encode off
    a live broadcast: the request itself is refused, and says why."""
    monkeypatch.setattr("autostream.clips.available", lambda: True)
    srv = _server(st.LIVE)
    monkeypatch.setattr(srv, "_clips_dir", lambda c: root, raising=False)
    started = []
    monkeypatch.setattr(studio.Runner, "start", lambda self, job, claim=0: started.append(job) or "")
    proj, _ = _project(root)
    got = srv.studio_render({"project": proj, "auto": True})
    assert got["ok"] is False and "live" in got["held"]
    assert started == []
    # Render, pressed by the user, is still theirs to press.
    got = srv.studio_render({"project": proj})
    assert got["ok"] is True and got["auto"] is False
    assert started and started[0].auto is False


def test_a_background_render_waits_for_the_one_the_user_started(monkeypatch, root, no_clip_job):
    monkeypatch.setattr("autostream.clips.available", lambda: True)
    srv = _server()
    monkeypatch.setattr(srv, "_clips_dir", lambda c: root, raising=False)
    run = studio.Runner()
    monkeypatch.setattr(studio, "runner", lambda: run)
    mine = _Job(auto=False)
    run.start(mine)
    proj, _ = _project(root)
    got = srv.studio_render({"project": proj, "auto": True})
    assert got["ok"] is False and "you started" in got["held"]
    assert not mine.cancelled
    mine._go.set()
