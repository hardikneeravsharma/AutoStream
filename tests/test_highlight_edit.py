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
    assert subs[1] == [(2.0, 5.0, "what a shot"), (10.0, 14.0, "bro rotate")]
    # A line with no English is shown as said.
    assert subs[4] == [(2.0, 6.0, "gg")]


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
    assert all("rotate" not in t for ss in subs for _a, _b, t in ss)
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
    assert subs[1] == [(10.0, 14.0, "bhai rotate karo")]


def test_merge_takes_only_what_the_editor_may_change(tmp_path):
    p = _project(tmp_path)
    edits = {"video": "C:/elsewhere.mp4", "source": "C:/Windows/system.dat",
             "cuts": [{"id": 1, "start": 8.0, "end": 38.5, "keep": False, "zoom": True, "layout": "cam",
                       "kind": "cold"},
                      {"id": 3, "start": -50, "end": 9e9},
                      {"id": 4, "start": 125.0, "end": 125.5},      # too short: refused
                      {"id": 99, "keep": False}],
             "lines": [{"id": 0, "text": "  kya   baat\n hai!  ", "face": True, "start": 0}],
             "cam_box": [0.1, 0.1, 0.3, 0.3], "cam_zoom": 9, "captions": {"on": True, "lang": "klingon"}}
    m = he.merge(p, edits)
    assert m["video"] == p["video"] and m["source"] == p["source"]
    c1 = m["cuts"][1]
    assert (c1["start"], c1["end"], c1["keep"], c1["zoom"]) == (8.0, 38.5, False, True)
    assert c1["layout"] == "game" and c1["kind"] == "play"
    assert (m["cuts"][3]["start"], m["cuts"][3]["end"]) == (0.0, 600.0)
    assert (m["cuts"][4]["start"], m["cuts"][4]["end"]) == (120.0, 130.0)
    assert m["lines"][0]["text"] == "kya baat hai!" and m["lines"][0]["face"]
    assert m["lines"][0]["start"] == 12.0
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
