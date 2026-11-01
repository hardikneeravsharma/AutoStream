"""The highlight editor's project: what the page may change, and the cut list a
render is made from.

The page edits the stream highlight's CUT LIST (clips/highlight_edit.py); a cut
line or a face line is a flag applied only when the list is built, so the same
project always renders the same video and switching a flag off gives back what
was there. The page plays its preview from its own copy of that function, so the
two are run on one project here and must agree.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import jsfn
from autostream import ui, webui
from autostream.clips import highlight_edit as he
from autostream.clips import stream_highlight as sh
from autostream.clips.speech import Line


def _project(tmp_path: Path, **over) -> dict:
    cuts = [sh.Cut(100.0, 108.0, kind="cold", stretch=1),
            sh.Cut(10.0, 40.0, stretch=0, caption="MATCH 1 · COMPETITIVE · BIND"),
            sh.Cut(41.0, 45.0, stretch=0, layout="result", caption="ROUND 3 · WON · 2-1"),
            sh.Cut(90.0, 120.0, punches=[104.0], stretch=1),
            sh.Cut(120.0, 130.0, stretch=1, layout="cam")]
    chosen = [sh.Stretch(10, 45, 3.0, round=3, why="2 kills"),
              sh.Stretch(90, 130, 5.0, round=7, why="Last alive")]
    lines = [Line(12.0, 15.0, "kya baat hai", "what a shot"),
             Line(20.0, 24.0, "bhai rotate karo", "bro rotate"),
             Line(122.0, 126.0, "gg", "")]
    video = tmp_path / "match" / "v.mp4"
    p = he.build(video=video, source=tmp_path / "rec.mp4", source_seconds=600.0, cuts=cuts,
                 chosen=chosen, labels=["MATCH 1", "MATCH 1"], lines=lines,
                 cam_box=(0.02, 0.6, 0.2, 0.3), channel="Chan", game="VALORANT")
    p.update(over)
    return p


def test_the_project_carries_every_cut_moment_and_line(tmp_path):
    p = _project(tmp_path)
    assert [c["kind"] for c in p["cuts"]] == ["cold", "play", "play", "play", "play"]
    assert all(c["keep"] for c in p["cuts"])
    assert [c["zoom"] for c in p["cuts"]] == [False, False, False, False, True]
    assert p["moments"][1]["name"] == "Round 7 · Last alive"
    assert p["lines"][0]["english"] == "what a shot" and p["lines"][0]["show"]
    # A player who does not speak English gets English captions by default.
    assert p["captions"] == {"on": False, "lang": "english"}


def test_as_built_it_renders_the_planned_video(tmp_path):
    p = _project(tmp_path)
    cuts, subs = he.pieces(p)
    assert [(c.start, c.end, c.layout) for c in cuts] == [
        (100.0, 108.0, "game"), (10.0, 40.0, "game"), (41.0, 45.0, "result"),
        (90.0, 120.0, "game"), (120.0, 130.0, "cam")]
    assert cuts[3].punches == [104.0]
    assert cuts[1].caption.startswith("MATCH 1")
    # Captions are seconds into their cut, in English.
    assert subs[1] == [(2.0, 5.0, "what a shot", "mic"), (10.0, 14.0, "bro rotate", "mic")]
    # A line with no English is shown as said.
    assert subs[4] == [(2.0, 6.0, "gg", "mic")]


def test_a_removed_moment_is_not_in_the_video(tmp_path):
    p = _project(tmp_path)
    p["cuts"][1]["keep"] = False
    assert [c.start for c in he.pieces(p)[0]] == [100.0, 41.0, 90.0, 120.0]


def test_a_cut_line_is_taken_out_and_a_face_line_zooms(tmp_path):
    p = _project(tmp_path)
    p["lines"][1]["cut"] = True       # 20-24 out of the 10-40 cut
    p["lines"][0]["face"] = True      # 12-15 on the face
    cuts, subs = he.pieces(p)
    got = [(c.start, c.end, c.layout) for c in cuts if c.stretch == 0 and c.layout != "result"]
    assert got == [(10.0, 12.0, "game"), (12.0, 15.0, "cam"), (15.0, 20.0, "game"), (24.0, 40.0, "game")]
    # The lower third is on the first piece only.
    firsts = [c.caption for c in cuts if c.stretch == 0 and c.layout != "result"]
    assert firsts[0] and not any(firsts[1:])
    # The cut line is not a caption any more.
    assert all("rotate" not in t for ss in subs for _a, _b, t, _w in ss)
    # And switching the flags off gives back exactly the plan.
    p["lines"][1]["cut"] = p["lines"][0]["face"] = False
    assert [(c.start, c.end) for c in he.pieces(p)[0]][1] == (10.0, 40.0)


def test_face_zoom_off_on_a_talk_cut_plays_it_as_the_game(tmp_path):
    p = _project(tmp_path)
    p["cuts"][4]["zoom"] = False
    p["cuts"][1]["zoom"] = True
    lay = {c.start: c.layout for c in he.pieces(p)[0]}
    assert lay[120.0] == "game" and lay[10.0] == "cam"


def test_a_sliver_between_two_face_lines_is_not_a_layout_of_its_own():
    assert he._layouts(0.0, 10.0, "game", [(2.0, 5.0), (5.3, 8.0)]) == [
        (0.0, 2.0, "game"), (2.0, 8.0, "cam"), (8.0, 10.0, "game")]


def test_hidden_captions_and_the_language_choice(tmp_path):
    p = _project(tmp_path)
    p["lines"][0]["show"] = False
    p["captions"]["lang"] = "said"
    subs = he.pieces(p)[1]
    assert subs[1] == [(10.0, 14.0, "bhai rotate karo", "mic")]


def test_merge_takes_only_what_the_editor_may_change(tmp_path):
    p = _project(tmp_path)
    edits = {"video": "C:/elsewhere.mp4", "source": "C:/Windows/system.dat",
             "cuts": [{"id": 1, "start": 8.0, "end": 38.5, "keep": False, "zoom": True, "layout": "cam",
                       "kind": "cold"},
                      {"id": 3, "start": -50, "end": 9e9},
                      {"id": 4, "start": 125.0, "end": 125.5},      # too short: refused
                      {"id": 99, "keep": False}],
             # The page sends every line it has: one it leaves out is deleted.
             "lines": [{"id": 0, "text": "  kya   baat\n hai!  ", "face": True, "start": 11.5,
                        "source": "C:/x"},
                       {"id": 1, "start": 20.0, "end": 20.1},          # too short: keeps its times
                       {"id": 9, "start": 50.0, "end": 52.0, "text": "new", "track": "game"},
                       {"id": 7, "start": 1.0, "end": 1.1}],           # new and unreadable: dropped
             "cam_box": [0.1, 0.1, 0.3, 0.3], "cam_zoom": 9, "captions": {"on": True, "lang": "klingon"}}
    m = he.merge(p, edits)
    assert m["video"] == p["video"] and m["source"] == p["source"]
    c1 = m["cuts"][1]
    assert (c1["start"], c1["end"], c1["keep"], c1["zoom"]) == (8.0, 38.5, False, True)
    assert c1["layout"] == "game" and c1["kind"] == "play"
    assert (m["cuts"][3]["start"], m["cuts"][3]["end"]) == (0.0, 600.0)
    assert (m["cuts"][4]["start"], m["cuts"][4]["end"]) == (120.0, 130.0)
    assert m["lines"][0]["text"] == "kya baat hai!" and m["lines"][0]["face"]
    assert m["lines"][0]["start"] == 11.5 and "source" not in m["lines"][0]
    assert (m["lines"][1]["start"], m["lines"][1]["end"]) == (20.0, 24.0)
    assert [ln["id"] for ln in m["lines"]] == [0, 1, 9]            # line 2 deleted, 7 refused
    assert m["lines"][2]["track"] == "game" and m["lines"][1]["track"] == "mic"
    assert m["cam_box"] == [0.1, 0.1, 0.3, 0.3]
    assert m["cam_zoom"] == he.ZOOM_MOST
    assert m["captions"] == {"on": True, "lang": "english"}
    # The base is not changed in place.
    assert p["cuts"][1]["keep"] is True


@pytest.mark.parametrize("box", [[0.9, 0.9, 0.3, 0.3], [0, 0, 0, 0], "x", [0.1, 0.1, 0.2]])
def test_a_box_outside_the_frame_is_refused(tmp_path, box):
    p = _project(tmp_path)
    assert he.merge(p, {"cam_box": box})["cam_box"] == p["cam_box"]


def test_auto_zoom_is_none(tmp_path):
    p = _project(tmp_path, cam_zoom=2.0)
    assert he.merge(p, {"cam_zoom": None})["cam_zoom"] is None
    assert he.merge(p, {"cam_zoom": 1.0})["cam_zoom"] == he.ZOOM_LEAST


def test_the_srt_is_on_the_edited_videos_clock(tmp_path):
    p = _project(tmp_path)
    cuts, subs = he.pieces(p)
    text = he.srt(cuts, subs)
    # The opening is 8 s, so the first line (2 s into the second cut) is at 10 s.
    assert text.startswith("1\n00:00:10,000 --> 00:00:13,000\nwhat a shot\n")
    assert text.count(" --> ") == 3


def test_saved_and_loaded_beside_its_video(tmp_path):
    p = _project(tmp_path)
    (tmp_path / "match").mkdir()
    path = he.save(p)
    assert path.name == "v.edit.json"
    assert he.load(tmp_path / "match" / "v.mp4") == json.loads(path.read_text(encoding="utf-8"))
    assert he.edited_path(p["video"]).name == "v_edited.mp4"


def test_the_page_plays_the_same_cut_list_the_render_makes(tmp_path):
    """The preview walks hl_pieces(); the render, pieces(). One project, both."""
    p = _project(tmp_path)
    p["lines"][1]["cut"] = True
    p["lines"][0]["face"] = True
    p["cuts"][2]["keep"] = False
    p["cuts"][4]["zoom"] = False
    js = jsfn.call(ui.JS, ["hl_len", "hl_minus", "hl_pieces"], "hl_pieces()",
                   prelude=f"const HL_SHORTEST = {he.SHORTEST}; const hl = {{p: {json.dumps(p)}, pieces: null}};")
    py = [(c.start, c.end, c.layout) for c in he.pieces(p)[0]]
    assert [(x["a"], x["b"], x["layout"]) for x in js] == py


# ---------------------------------------------------------------- the routes

@pytest.fixture
def srv(tmp_path, monkeypatch):
    s = object.__new__(webui.Server)
    monkeypatch.setattr(webui.Server, "_clips_dir", staticmethod(lambda config: tmp_path))
    return s


def _saved(tmp_path) -> dict:
    (tmp_path / "match").mkdir(exist_ok=True)
    p = _project(tmp_path)
    Path(p["video"]).write_bytes(b"\0")
    he.save(p)
    return p


def test_the_editor_opens_a_project_in_the_clips_folder(srv, tmp_path):
    p = _saved(tmp_path)
    got = srv.clips_highlight(p["video"])
    assert got["ok"] and got["project"]["cuts"] == p["cuts"]
    assert got["source_ok"] is False          # the recording is not here
    assert got["length"] == pytest.approx(82.0)


def test_a_video_outside_the_clips_folder_is_refused(srv, tmp_path, tmp_path_factory):
    other = tmp_path_factory.mktemp("elsewhere")
    p = _project(other)
    (other / "match").mkdir()
    he.save(p)
    assert "not in the clips folder" in srv.clips_highlight(p["video"])["error"]


def test_a_project_naming_another_video_is_refused(srv, tmp_path):
    p = _saved(tmp_path)
    copy = tmp_path / "match" / "copy.mp4"
    copy.write_bytes(b"\0")
    he.project_path(copy).write_text(json.dumps(p), encoding="utf-8")
    assert "another video" in srv.clips_highlight(str(copy))["error"]


def test_saving_merges_the_edits_onto_the_file(srv, tmp_path):
    p = _saved(tmp_path)
    got = srv.clips_highlight_save({"video": p["video"],
                                    "project": {"cuts": [{"id": 1, "keep": False}], "source": "C:/x"}})
    assert got["ok"] and got["length"] == pytest.approx(52.0)
    back = he.load(p["video"])
    assert back["cuts"][1]["keep"] is False and back["source"] == p["source"]


def test_the_newest_editable_highlight_of_a_run_is_offered(tmp_path):
    p = _saved(tmp_path)
    assert webui.Server._editable_highlight(str(tmp_path)) == p["video"]
    assert webui.Server._editable_highlight(str(tmp_path / "nothing")) == ""


# ------------------------------------------------- waiting for the broadcast

def _quick_render(monkeypatch, made: list):
    def fake(source, cuts, out, **kw):
        made.append(out)
        Path(out).write_bytes(b"\0" * 16)
        return out
    monkeypatch.setattr(sh, "render", fake)
    monkeypatch.setattr(he, "WAIT_POLL", 0.05)


def _until(r: he.Renderer, state: str, seconds: float = 5.0) -> dict:
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        snap = r.snapshot()
        if snap["state"] == state and not (state != "waiting" and r.busy()):
            return snap
        time.sleep(0.02)
    raise AssertionError(f"never {state}: {r.snapshot()}")


def test_make_video_waits_while_live_and_starts_by_itself(tmp_path, monkeypatch):
    """The player's rule: no Make video while live or recording -- it waits and says so."""
    made: list = []
    _quick_render(monkeypatch, made)
    p = _saved(tmp_path)
    live = {"why": "Waiting until you are not live."}
    r = he.Renderer()
    assert r.start(p, held=lambda: live["why"])
    snap = _until(r, "waiting")
    assert snap["why"] == "Waiting until you are not live."
    assert not made and not r.encoding()
    # Edits saved while it waits are what it makes.
    he.save({**he.load(p["video"]), "cuts": [dict(c, keep=c["id"] != 1) for c in p["cuts"]]})
    live["why"] = ""
    _until(r, "done")
    assert made and he.load(p["video"])["made"].endswith("_edited.mp4")
    assert he.load(p["video"])["cuts"][1]["keep"] is False


def test_stopping_a_waiting_render_makes_nothing(tmp_path, monkeypatch):
    made: list = []
    _quick_render(monkeypatch, made)
    p = _saved(tmp_path)
    r = he.Renderer()
    r.start(p, held=lambda: "Waiting until the recording stops.")
    _until(r, "waiting")
    r.cancel()
    snap = _until(r, "idle")
    assert snap["why"] == "" and not made


def test_a_waiting_render_does_not_hold_up_a_clip_job(tmp_path, monkeypatch):
    """busy() is the slot; encoding() is the encoder, which is what a clip job
    fights over -- and a render waiting FOR that clip job must not refuse it."""
    _quick_render(monkeypatch, [])
    p = _saved(tmp_path)
    r = he.Renderer()
    r.start(p, held=lambda: "Waiting for the clip job to finish.")
    _until(r, "waiting")
    assert r.busy() and not r.encoding()
    r.cancel()
    _until(r, "idle")


def test_the_last_run_says_whether_its_highlight_opens_in_the_editor(srv, tmp_path, monkeypatch):
    p = _saved(tmp_path)
    run = tmp_path / "run"
    run.mkdir()
    (run / "clips.json").write_text(json.dumps({"match_video": p["video"], "clips": []}), encoding="utf-8")
    got = srv._last_manifest(None)
    assert got["match_video_edit"] is True
    he.project_path(p["video"]).unlink()
    assert srv._last_manifest(None)["match_video_edit"] is False


# ------------------------------------------------- the second pass: a video editor's controls

def test_a_drawn_face_zoom_zooms_for_exactly_as_long_as_it_is(tmp_path):
    p = _project(tmp_path)
    p["zooms"] = [{"id": 0, "start": 30.0, "end": 33.5}]
    got = [(c.start, c.end, c.layout) for c in he.pieces(p)[0] if c.stretch == 0 and c.layout != "result"]
    assert got == [(10.0, 30.0, "game"), (30.0, 33.5, "cam"), (33.5, 40.0, "game")]


def test_zooms_are_checked_and_sorted(tmp_path):
    p = _project(tmp_path)
    m = he.merge(p, {"zooms": [{"id": 2, "start": 50, "end": 51}, [10, 12], {"id": 3, "start": 5, "end": 5.2},
                               "x", {"id": 4, "start": -9, "end": 9e9}]})
    assert [(z["start"], z["end"]) for z in m["zooms"]] == [(0.0, 600.0), (10.0, 12.0), (50.0, 51.0)]


def test_a_team_mates_line_is_captioned_a_line_up_and_marked_in_the_srt(tmp_path):
    p = _project(tmp_path)
    p["lines"].append({"id": 9, "start": 25.0, "end": 27.0, "text": "push B", "english": "",
                       "show": True, "cut": False, "face": False, "track": "game"})
    cuts, subs = he.pieces(p)
    assert (15.0, 17.0, "push B", "game") in subs[1]
    assert "[Team] push B" in he.srt(cuts, subs)


def test_volume_is_checked_and_an_old_project_is_upgraded(tmp_path):
    p = _project(tmp_path)
    for k in ("zooms", "volume", "audio"):
        p.pop(k)
    for ln in p["lines"]:
        ln.pop("track")
    p = he.upgrade(p)
    assert p["zooms"] == [] and p["volume"]["mic"] == {"db": 0.0, "keys": []}
    assert all(ln["track"] == "mic" for ln in p["lines"])
    m = he.merge(p, {"volume": {"master": 40, "mic": {"keys": [[20, -6], [10, 3], ["x", 1], [30, 99]]},
                                "game": {"db": -200}}})
    assert m["volume"]["master"] == he.MASTER_MOST
    assert m["volume"]["mic"]["keys"] == [[10.0, 3.0], [20.0, -6.0], [30.0, 12.0]]
    assert m["volume"]["game"]["db"] == -60.0


def test_untouched_volume_keeps_the_recordings_own_mix(tmp_path, monkeypatch):
    p = _project(tmp_path)
    monkeypatch.setattr(he, "track_count", lambda src: 3)
    assert he.track_mix(p) is None
    p["volume"]["game"]["keys"] = [[12.0, -10.0]]
    assert he.track_mix(p) == {"mic": [], "mic_db": 0.0, "game": [[12.0, -10.0]], "game_db": 0.0}
    monkeypatch.setattr(he, "track_count", lambda src: 1)
    assert he.track_mix(p) is None


def test_a_volume_line_on_one_cuts_own_clock():
    from autostream.clips.studio import vol_at
    keys = [[10.0, 0.0], [20.0, -20.0], [40.0, -20.0]]
    c = sh.Cut(15.0, 25.0)
    f = sh._vol_in_cut(keys, 0.0, c)
    # Starts at the level the line has at 15 s (-10 dB), reaches -20 at 5 s in, holds.
    assert f.startswith("volume='pow(10,(-10.00") and "(-10.00)*clip((t-0.000)/5.000,0,1)" in f
    assert vol_at(keys, 0.0, 15.0) == -10.0
    assert sh._vol_in_cut([], -3.0, c) == "volume=-3.0dB"


def test_the_render_mixes_the_two_tracks_through_their_lines(tmp_path, monkeypatch):
    """The cut's filter graph takes a:1 and a:2, each through its line, not a:0."""
    seen = {}
    monkeypatch.setattr("autostream.clips.tools.ffmpeg", lambda *a: seen.setdefault("args", a))
    out = tmp_path / "c.mp4"
    sh._cut_one(tmp_path / "src.mp4", sh.Cut(10.0, 14.0), out, size=(640, 360), encoder="auto", cq=23,
                mix={"mic": [], "mic_db": 3.0, "game": [[12.0, -8.0]], "game_db": 0.0})
    graph = out.with_suffix(".graph.txt").read_text(encoding="utf-8")
    assert "[0:a:1]" in graph and "[0:a:2]" in graph and "[0:a:0]" not in graph
    assert "volume=3.0dB" in graph and "amix=inputs=2" in graph


def test_the_page_plays_drawn_zooms_too(tmp_path):
    p = _project(tmp_path)
    p["zooms"] = [{"id": 0, "start": 30.0, "end": 33.5}]
    js = jsfn.call(ui.JS, ["hl_len", "hl_minus", "hl_pieces"], "hl_pieces()",
                   prelude=f"const HL_SHORTEST = {he.SHORTEST}; const hl = {{p: {json.dumps(p)}, pieces: null}};")
    assert [(x["a"], x["b"], x["layout"]) for x in js] == [(c.start, c.end, c.layout) for c in he.pieces(p)[0]]


def test_the_pages_volume_line_is_the_render_s(tmp_path):
    from autostream.clips.studio import vol_at
    keys = [[10.0, 0.0], [20.0, -20.0], [40.0, 6.0]]
    ts = [0.0, 10.0, 12.5, 20.0, 30.0, 45.0]
    js = jsfn.call(ui.JS, ["hl_volAt"], f"{json.dumps(ts)}.map(t => hl_volAt({json.dumps(keys)}, 0, t))")
    assert js == pytest.approx([vol_at(keys, 0.0, t) for t in ts])


def test_copying_the_tracks_out(tmp_path, monkeypatch):
    import subprocess
    p = _saved(tmp_path)
    monkeypatch.setattr(he, "track_count", lambda src: 3)
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        Path(args[-1]).write_bytes(b"m4a")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    made = he.copy_tracks(p)
    assert set(made) == {"mic", "game"}
    assert ["0:a:1" in a for a in calls] == [True, False] and "0:a:2" in calls[1]
    assert all("-c:a" in a and a[a.index("-c:a") + 1] == "copy" for a in calls)     # never re-encoded
    assert he.load(p["video"])["audio"]["game"].endswith(".game.m4a")
    monkeypatch.setattr(he, "track_count", lambda src: 1)
    with pytest.raises(ValueError):
        he.copy_tracks(p)


def test_the_teams_voice_replaces_only_the_game_tracks_lines(tmp_path, monkeypatch):
    from autostream.clips import speech
    p = _saved(tmp_path)
    monkeypatch.setattr(he, "track_count", lambda src: 3)
    monkeypatch.setattr(speech, "available", lambda: True)
    monkeypatch.setattr(speech, "fast", lambda: True)
    asked = {}

    def fake(video, spans, track=1, lang=None, english=True):
        asked.update(track=track, spans=spans)
        return [Line(21.5, 23.0, "push", ""), Line(95.0, 96.0, "nice one", "")]
    monkeypatch.setattr(speech, "transcribe", fake)
    assert he.transcribe_track(p, "game") == 2
    assert asked["track"] == 2
    lines = he.load(p["video"])["lines"]
    assert [ln["track"] for ln in lines].count("game") == 2 and [ln["track"] for ln in lines].count("mic") == 3
    assert all(ln["show"] for ln in lines if ln["track"] == "game")
    he.transcribe_track(he.load(p["video"]), "game")                 # again: replaced, not doubled
    assert [ln["track"] for ln in he.load(p["video"])["lines"]].count("game") == 2


def test_no_graphics_card_says_so(tmp_path, monkeypatch):
    from autostream.clips import speech
    p = _saved(tmp_path)
    monkeypatch.setattr(speech, "available", lambda: True)
    monkeypatch.setattr(speech, "fast", lambda: False)
    with pytest.raises(RuntimeError, match="graphics card"):
        he.transcribe_track(p, "game")


def test_the_routes_for_tracks_and_the_teams_voice(srv, tmp_path, monkeypatch):
    p = _saved(tmp_path)
    started = []
    monkeypatch.setattr(he.work(), "copy_tracks", lambda proj: started.append("tracks") or True)
    monkeypatch.setattr(he.work(), "transcribe", lambda proj, t: started.append(t) or True)
    # As on a machine that has it: without, the route asks for the download
    # instead (test_packs) -- which is what CI, with no speech-to-text, saw.
    from autostream.clips import speech
    monkeypatch.setattr(speech, "available", lambda: True)
    assert "not on this PC" in srv.clips_highlight_tracks({"video": p["video"]})["error"]
    Path(p["source"]).write_bytes(b"\0")
    assert srv.clips_highlight_tracks({"video": p["video"]})["state"] == "running"
    assert srv.clips_highlight_transcribe({"video": p["video"], "track": "game"})["ok"]
    assert srv.clips_highlight_transcribe({"video": p["video"], "track": "x"})["error"] == "Which track?"
    assert started == ["tracks", "game"]
    assert srv.clips_highlight_work(p["video"])["audio"] == {"mic": False, "game": False}


def test_a_job_with_the_teams_words_builds_them_in_as_team_captions(tmp_path):
    p = he.build(video=tmp_path / "v.mp4", source=tmp_path / "r.mp4", source_seconds=100.0,
                 cuts=[sh.Cut(0.0, 30.0, stretch=0)], chosen=[sh.Stretch(0, 30, 1.0, round=1, why="1 kill")],
                 labels=["MATCH 1"], lines=[Line(5.0, 7.0, "mine", "")],
                 team_lines=[Line(3.0, 4.0, "theirs", ""), Line(9.0, 10.0, "again", "")])
    assert [(ln["text"], ln["track"]) for ln in p["lines"]] == [("theirs", "game"), ("mine", "mic"), ("again", "game")]
    assert [ln["id"] for ln in p["lines"]] == [0, 1, 2]


def test_words_written_over_and_over_are_one_line():
    """Measured on the game track: "Close down" four times a second apart."""
    got = he.collapse([Line(11.0, 12.0, "Close down", ""), Line(15.5, 16.4, "Close down.", ""),
                       Line(16.5, 17.4, "close down", ""), Line(17.5, 18.0, "Close down", ""),
                       Line(19.5, 20.0, "Reta", ""), Line(24.5, 25.4, "Nice round", ""),
                       Line(29.0, 30.0, "Nice round", "")])
    assert [(ln.start, ln.end, ln.text) for ln in got] == [
        (11.0, 12.0, "Close down"), (15.5, 18.0, "Close down."), (19.5, 20.0, "Reta"),
        (24.5, 25.4, "Nice round"), (29.0, 30.0, "Nice round")]
