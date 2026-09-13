"""The song edit offered on the finished clips.

The reel maker has existed since 1.17.0, reachable only from the review card --
which is BEFORE the clips are cut, and so before anybody has seen them. This is
the same maker, offered at the moment somebody has just watched their clips,
with the five steps taken automatically and kept behind "Not quite".

These tests cover the two halves a browser cannot be asked about here: that the
finished run hands over the kills the reel needs, and that the page and the
script still agree about the buttons.
"""
from __future__ import annotations

import json
import urllib.parse

from autostream import webui
from autostream.ui import clips as clips_ui
from autostream.ui import reel as reel_ui


def _server(tmp_path, monkeypatch):
    srv = webui.Server.__new__(webui.Server)
    monkeypatch.setattr(srv, "_clips_dir", lambda c=None: tmp_path, raising=False)
    return srv


def _run(tmp_path, kills, game="VALORANT"):
    folder = tmp_path / "2026-09-06_1653_VALORANT"
    folder.mkdir(parents=True)
    (folder / "clips.json").write_text(json.dumps({"clips": [], "montage": None}),
                                       encoding="utf-8")
    (folder / "session.json").write_text(json.dumps({
        "source": str(tmp_path / "rec.mp4"), "game": game,
        "game_key": "valorant-win64-shipping.exe",
        "recording_seconds": 600.0, "kills": kills}), encoding="utf-8")
    return folder


# ------------------------------------------------------- the run's kills

def test_a_finished_run_hands_over_the_kills_the_reel_needs(tmp_path, monkeypatch):
    """THE REEL CUTS KILLS, NOT CLIPS. A clip is a window around a fight; the
    reel needs the instant of each kill to land it on a beat."""
    srv = _server(tmp_path, monkeypatch)
    folder = _run(tmp_path, [{"time": 25.5, "end": 25.5, "tags": ["HEADSHOT"]},
                             {"time": 44.0, "end": 44.0}])
    got = srv.clips_existing(str(folder))
    assert got["ok"] is True
    assert [k["time"] for k in got["kills"]] == [25.5, 44.0]
    assert got["kills"][0]["labels"] == ["HEADSHOT"]
    assert got["source"].endswith("rec.mp4")
    assert got["game_key"] == "valorant-win64-shipping.exe"


def test_a_run_with_no_kills_says_so_rather_than_half_answering(tmp_path, monkeypatch):
    srv = _server(tmp_path, monkeypatch)
    got = srv.clips_existing(str(_run(tmp_path, [])))
    assert got["ok"] is True and got["kills"] == []


def test_a_kill_with_no_time_is_not_offered_to_the_reel(tmp_path, monkeypatch):
    """A malformed row would place a shot at zero seconds -- the reel would cut
    the first frame of the recording and call it a kill."""
    srv = _server(tmp_path, monkeypatch)
    folder = _run(tmp_path, [{"end": 3.0}, {"time": 12.0}])
    assert [k["time"] for k in srv.clips_existing(str(folder))["kills"]] == [12.0]


def test_the_kills_are_still_confined_to_the_clips_folder(tmp_path, monkeypatch):
    srv = _server(tmp_path, monkeypatch)
    assert "error" in srv.clips_existing(str(tmp_path.parent))


# --------------------------------------------------------- page and script

def test_the_button_is_on_the_finished_clips_card():
    html = clips_ui.CLIPS_HTML
    at = html.index('id="clip-songedit"')
    assert html.index('id="clip-results"') < at < html.index('id="clip-res-list"')
    assert 'data-act="songedit"' in html


def test_the_button_is_only_offered_where_it_can_work():
    """Kills on a recording, from a run that finished, in the game whose reader
    returns per-kill times. Offering it otherwise is a button that fails."""
    js = clips_ui.CLIPS_JS
    at = js.index("var sumk")
    guard = js[at:js.index("\n", js.index("clip_show('clip-songedit'")) + 200]
    assert "j.state === 'done'" in guard
    assert "!j.needs_demo" in guard
    assert "kills" in guard
    assert "valorant" in guard.lower()


def test_the_button_starts_the_straight_path():
    assert "PAGE_REEL.quick(" in clips_ui.CLIPS_JS
    assert "quick: reel_quick" in reel_ui.REEL_JS


def test_the_straight_path_asks_for_a_song_and_then_builds_it():
    js = reel_ui.REEL_JS
    assert "/api/clips/pick" in js and "'audio'" in js
    assert js.index("reel_quickPick") < js.index("reel_quickMake")
    for called in ("/api/reel/song", "reel_replan", "reel_quickRender", "reel_build"):
        assert called in js


def test_not_quite_asks_the_two_questions_and_rebuilds():
    """Which part of the song, then which beats -- then make it again."""
    js = reel_ui.REEL_JS
    fix = js[js.index("function reel_quickFix()"):]
    fix = fix[:fix.index("window.PAGE_REEL")]
    assert "reel-step-part" in fix and "reel_openMark" in fix
    assert "reel-quick-again-bar" in fix
    assert "reel-quick-again') reel_quickRender" in js


def test_the_five_step_card_still_works_on_its_own():
    """PAGE_REEL.open is the review path and must not inherit the straight
    path's hidden sections."""
    js = reel_ui.REEL_JS
    open_fn = js[js.index("open: function (rows)"):]
    open_fn = open_fn[:open_fn.index("close:")]
    assert "reel_quickUI(false)" in open_fn
    assert "reel-step-song" in open_fn


def test_the_edit_is_cut_from_the_finished_runs_recording():
    """Not from whatever the Clips page happens to have selected."""
    js = reel_ui.REEL_JS
    build = js[js.index("async function reel_build()"):]
    assert "st.source ||" in build[:400]


def test_every_id_the_song_edit_script_touches_exists():
    html = clips_ui.CLIPS_HTML + reel_ui.REEL_HTML
    for el in ("reel-quick", "reel-quick-msg", "reel-quick-pick", "reel-quick-result",
               "reel-quick-video", "reel-quick-facts", "reel-quick-ask",
               "reel-quick-fixer", "reel-quick-again-bar", "reel-quick-again-msg",
               "reel-usemarks-btn", "clip-songedit"):
        assert f'id="{el}"' in html, el


def test_the_flashy_button_stops_moving_when_motion_is_turned_down():
    from autostream.ui import css

    assert ".btn-flashy" in css.CSS
    reduced = css.CSS[css.CSS.index(".btn-flashy"):]
    reduced = reduced[:reduced.index(".reel-quick{")]
    assert "prefers-reduced-motion" in reduced
    assert "animation:none" in reduced


# --------------------------------------------------------------- the song file

def _cached_song(srv, path):
    """Put a song in the whitelist the audio route serves from, as reel_song does."""
    class _Shape:
        def __init__(self, p):
            self.path = p
    srv._reel_cache = ((str(path.resolve()), 0.0), _Shape(path))


def test_the_chosen_song_is_actually_served_to_the_beat_marker(tmp_path):
    """FROM A BUG. The route passed only the FILE NAME to _media, which resolves
    what it is given against the process's working directory instead of joining
    it to the folder -- so a song anywhere else (the Downloads folder, in the
    report that found this) resolved to the app folder instead, failed the "inside
    the folder" guard, and came back 403. The page could only render that as a
    player with a greyed-out play button and 0:00 / 0:00.

    The song therefore lives somewhere that is NOT the working directory, which
    is the whole point: every path in this test is absolute and elsewhere.
    """
    from fakes import LiveServer

    song = tmp_path / "a song.mp3"
    song.write_bytes(b"ID3" + b"\0" * 4096)
    srv = LiveServer(engine=None)
    try:
        _cached_song(srv.srv, song)
        r = srv.get("/api/reel/audio?path=" + urllib.parse.quote(str(song)))
        assert r.status == 200, f"the chosen song was refused with {r.status}"
        assert "audio" in (r.headers.get("Content-Type") or "")
        assert len(r.body) == 4099
    finally:
        srv.close()


def test_the_beat_marker_can_seek_within_the_song(tmp_path):
    """A marker you cannot scrub is no use: taps are made against the playing
    track, so the player has to be able to start anywhere."""
    from fakes import LiveServer

    song = tmp_path / "track.flac"
    song.write_bytes(bytes(range(256)) * 16)
    srv = LiveServer(engine=None)
    try:
        _cached_song(srv.srv, song)
        url = "/api/reel/audio?path=" + urllib.parse.quote(str(song))
        r = srv.get(url, headers={"Range": "bytes=100-199"})
        assert r.status == 206, f"no byte ranges: {r.status}"
        assert len(r.body) == 100
    finally:
        srv.close()


def test_no_other_file_is_served_even_from_the_songs_own_folder(tmp_path):
    """The whitelist is exactly one file. Anything else in that folder -- and
    anything anywhere -- is still refused."""
    from fakes import LiveServer

    song = tmp_path / "chosen.mp3"
    song.write_bytes(b"ID3" + b"\0" * 32)
    other = tmp_path / "private.mp3"
    other.write_bytes(b"ID3" + b"\0" * 32)
    srv = LiveServer(engine=None)
    try:
        _cached_song(srv.srv, song)
        for path in (other, tmp_path / ".." / "secrets.mp3"):
            r = srv.get("/api/reel/audio?path=" + urllib.parse.quote(str(path)))
            assert r.status in (403, 404), f"{path} was served with {r.status}"
    finally:
        srv.close()


def test_with_no_song_chosen_nothing_is_served(tmp_path):
    from fakes import LiveServer

    srv = LiveServer(engine=None)
    try:
        r = srv.get("/api/reel/audio?path=" + urllib.parse.quote(str(tmp_path / "x.mp3")))
        assert r.status in (403, 404)
    finally:
        srv.close()
