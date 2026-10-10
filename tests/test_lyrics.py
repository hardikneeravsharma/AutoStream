"""Lyric reels: finding the words, timing them, and drawing them in each look."""
import re
from pathlib import Path

import pytest

from autostream.clips import lyrics


LRC = """[ar:Someone]
[00:10.00]We ride out at night
[00:13.50]Every shot, the one that drops
[00:16.00][00:30.00]Repeat (this) line!
"""


def test_an_lrc_is_read_into_lines_with_every_stamp():
    lines = lyrics.parse_lrc(LRC)
    assert [round(ln.t, 2) for ln in lines] == [10.0, 13.5, 16.0, 30.0]
    assert lines[1].words == ["Every", "shot", "the", "one", "that", "drops"]
    assert lines[2].words == ["Repeat", "this", "line"]


def test_braces_and_backslashes_never_reach_the_subtitle_script():
    lines = lyrics.parse_lrc("[00:01.00]a {\\b1}bold\\N word")
    assert all("{" not in w and "\\" not in w for w in lines[0].words)


def _lines():
    return [lyrics.Line(100.0, ["we", "run", "this", "town"]),
            lyrics.Line(102.0, ["the", "kill", "lands", "here"])]


def test_words_go_on_the_vocal_onsets_and_never_overlap():
    onsets = [(0.02, 2.0), (0.4, 3.0), (0.9, 2.5), (1.3, 1.5), (1.31, 1.4),
              (2.0, 2.0), (2.5, 3.0), (2.9, 2.0), (3.4, 2.2)]
    rows = lyrics.place(_lines(), 100.0, 10.0, onsets, kills=[])
    flat = [w for r in rows for w in r]
    assert [w["w"] for w in flat] == ["we", "run", "this", "town", "the", "kill", "lands", "here"]
    assert flat[1]["a"] == pytest.approx(0.4)
    for row in rows:
        for x, y in zip(row, row[1:]):
            assert x["b"] <= y["a"] + 1e-9
            assert y["a"] - x["a"] >= lyrics.MIN_WORD - 1e-9


def test_a_line_is_sung_at_a_singers_pace_then_its_last_word_held():
    """TISWFLFIL2: words went on the loudest piano and drum hits, so "so" sat
    alone for 1.6 s and a seven-word line was spread over five seconds."""
    line = lyrics.Line(100.0, ["so", "this", "is", "love", "i", "know", "it", "is"])
    drums = [(100.0 + 0.52 * i, 5.0) for i in range(12)]          # loud, and not the voice
    rows = lyrics.place([line, lyrics.Line(106.0, ["next"])], 100.0, 10.0, drums, kills=[])
    ws = rows[0]
    gaps = [b["a"] - a["a"] for a, b in zip(ws, ws[1:])]
    assert max(gaps) <= lyrics.SYLLABLE_MAX + lyrics.SNAP + 1e-6, gaps
    assert ws[-1]["a"] < 3.0 and ws[-1]["b"] > 5.0                 # sung in under 3 s, then held


def test_syllables_are_counted_well_enough_to_pace_by():
    assert [lyrics._syllables(w) for w in ("love", "falling", "cliché", "I", "forward", "little")] == \
        [1, 2, 2, 1, 2, 2]


def test_too_few_onsets_spread_the_words_evenly():
    rows = lyrics.place(_lines()[:1], 100.0, 10.0, [], kills=[])
    starts = [w["a"] for w in rows[0]]
    gaps = {round(b - a, 3) for a, b in zip(starts, starts[1:])}
    assert len(gaps) == 1


def test_the_word_sung_at_a_kill_is_red():
    rows = lyrics.place(_lines(), 100.0, 10.0, [], kills=[0.6])
    hooks = [w["w"] for r in rows for w in r if w.get("hook")]
    assert hooks == ["run"]


def test_a_kill_on_a_light_word_moves_its_accent_to_one_with_weight():
    onsets = [(t, 2.0) for t in (0.0, 0.4, 0.8, 1.2, 2.0, 2.3, 2.6, 2.9)]
    rows = lyrics.place(_lines(), 100.0, 10.0, onsets, kills=[2.15])  # on "the"
    hooks = [w["w"] for r in rows for w in r if w.get("hook")]
    assert hooks == ["kill"]


def test_a_kill_with_nothing_sung_near_it_has_no_red_word():
    rows = lyrics.place(_lines(), 100.0, 30.0, [], kills=[20.0])
    assert not [w for r in rows for w in r if w.get("hook")]


def test_lines_outside_the_reel_are_left_out_and_a_line_started_before_it_is_clipped():
    lines = [lyrics.Line(95.0, ["gone", "before"]), lyrics.Line(99.0, ["half", "in", "now", "here"]),
             lyrics.Line(130.0, ["after", "the", "end"])]
    rows = lyrics.place(lines, 100.0, 8.0, [], kills=[])
    flat = [w for r in rows for w in r]
    assert "gone" not in [w["w"] for w in flat] and "after" not in [w["w"] for w in flat]
    assert min(w["a"] for w in flat) >= 0.0
    assert max(w["b"] for w in flat) <= 8.0


def test_clean_stars_the_middle_of_a_swear_but_not_an_innocent_word():
    assert lyrics.clean("fucking") == "f*****g"
    assert lyrics.clean("Shit") == "S**t"
    assert lyrics.clean("class") == "class"
    assert lyrics.clean("ass") == "a*s"


@pytest.mark.parametrize("look", lyrics.LOOKS)
@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080)])
def test_every_look_writes_a_script_at_the_reel_size(look, size):
    rows = lyrics.place(_lines(), 100.0, 10.0, [], kills=[0.6])
    text = lyrics.build_ass(look, rows, *size)
    assert f"PlayResX: {size[0]}" in text and f"PlayResY: {size[1]}" in text
    face = lyrics.FACES[lyrics.LOOK_FACE[look]][0]
    assert re.search(rf"^Style: \w+,{re.escape(face)},\d+,", text, re.M)
    assert text.count("Dialogue:") >= 4
    assert lyrics.RED in text


def test_a_chosen_typeface_replaces_only_the_font():
    rows = lyrics.place(_lines(), 100.0, 10.0, [], kills=[])
    own = lyrics.build_ass("stamp", rows, 1080, 1920)
    other = lyrics.build_ass("stamp", rows, 1080, 1920, face="kalam")
    assert ",Kalam," in other and ",Anton," not in other
    style = next(ln for ln in other.splitlines() if ln.startswith("Style:")).split(",")
    assert style[7] == "-1"                         # Kalam ships as its Bold
    # the same words at the same times; only sizes follow the face
    strip = lambda t: [(ln.split(",")[1:3], ln.rsplit("}", 1)[-1]) for ln in t.splitlines()
                       if ln.startswith("Dialogue:")]
    assert strip(own) == strip(other)


def test_every_face_and_its_licence_ship_with_the_app():
    names = {p.name for p in lyrics.FONTS_DIR.glob("*.ttf")}
    assert len(names) == len(lyrics.FACES)
    licence = (lyrics.FONTS_DIR / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in licence
    for n in names:
        assert n in licence


def test_settings_are_off_unless_a_known_look_is_asked_for():
    assert lyrics.settings(None) == {"look": "off", "face": "", "clean": False, "pos": None, "shift": 0.0}
    assert lyrics.settings({"look": "bogus", "face": "comic"})["look"] == "off"
    assert lyrics.settings({"look": "glow", "face": "bebas", "clean": 1}) == \
        {"look": "glow", "face": "bebas", "clean": True, "pos": None, "shift": 0.0}


def test_a_position_is_kept_clamped_inside_the_frame_and_junk_is_dropped():
    assert lyrics.settings({"look": "stamp", "pos": [0.3, 0.7]})["pos"] == [0.3, 0.7]
    assert lyrics.settings({"look": "stamp", "pos": [-4, 9]})["pos"] == [lyrics.POS_EDGE, 1 - lyrics.POS_EDGE]
    for junk in ("x", [1], [None, 2], {"a": 1}, [float("nan"), 0.5]):
        assert lyrics.settings({"look": "stamp", "pos": junk})["pos"] is None


@pytest.mark.parametrize("look", lyrics.LOOKS)
@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080)])
def test_the_words_are_drawn_where_the_player_put_them(look, size):
    rows = lyrics.place(_lines(), 100.0, 10.0, [], kills=[0.6])
    W, H = size
    text = lyrics.build_ass(look, rows, W, H, pos=[0.5, 0.8])
    at = set(re.findall(r"\\(?:pos|move)\((\d+),(\d+)", text))
    # every look puts a word's resting place on the chosen centre
    assert (str(round(W * 0.5)), str(round(H * 0.8))) in at, sorted(at)[:6]
    assert lyrics.build_ass(look, rows, W, H) != text


@pytest.mark.parametrize("look", lyrics.LOOKS)
def test_a_line_placed_at_the_edge_is_moved_in_until_it_fits(look):
    """A caption centred 5% across hung its first word off the frame."""
    rows = lyrics.place([lyrics.Line(100.0, ["unbelievable", "extraordinary", "everything", "tonight"])],
                        100.0, 10.0, [], kills=[])
    text = lyrics.build_ass(look, rows, 1080, 1920, pos=[0.05, 0.5])
    xs = [int(x) for x in re.findall(r"\\(?:pos|move)\((\d+),960[,)]", text)]
    assert xs and min(xs) > round(1080 * 0.05), sorted(set(xs))


# ---------------------------------------------------------------- finding them

def test_an_lrc_beside_the_song_is_used_and_nothing_is_fetched(tmp_path):
    song = tmp_path / "Track.m4a"
    song.write_bytes(b"x")
    song.with_suffix(".lrc").write_text(LRC, encoding="utf-8")

    def boom(*a, **k):
        raise AssertionError("fetched")
    lines, src = lyrics.find(song, tmp_path / "cache", seconds=120, tags={}, fetch=boom)
    assert len(lines) == 4 and "Track.lrc" in src


def test_a_fetch_is_cached_and_a_miss_is_not_asked_again_at_once(tmp_path):
    song = tmp_path / "Ambition For Cash [Wl2In8FvQhE].m4a"
    song.write_bytes(b"x")
    asked = []

    def fetch(artist, title, seconds):
        asked.append((artist, title, seconds))
        return LRC if len(asked) == 1 else ""
    a, _ = lyrics.find(song, tmp_path / "c", seconds=143.0, tags={"title": song.stem}, fetch=fetch)
    b, _ = lyrics.find(song, tmp_path / "c", seconds=143.0, tags={"title": song.stem}, fetch=fetch)
    assert len(a) == len(b) == 4 and len(asked) == 1
    assert asked[0] == ("", "Ambition For Cash", 143.0)

    other = tmp_path / "Nothing.m4a"
    other.write_bytes(b"y")
    fetch_none = lambda *a: asked.append(a) or ""
    assert lyrics.find(other, tmp_path / "c", seconds=60.0, tags={}, fetch=fetch_none)[0] == []
    n = len(asked)
    assert lyrics.find(other, tmp_path / "c", seconds=60.0, tags={}, fetch=fetch_none)[0] == []
    assert len(asked) == n


def test_artist_dash_title_in_a_file_name_is_split(tmp_path):
    seen = []
    s = tmp_path / "Key Glock - Ambition For Cash (Official Audio).m4a"
    s.write_bytes(b"z")
    lyrics.find(s, tmp_path / "c", seconds=143.0, tags={"title": s.stem},
                fetch=lambda a, t, n: seen.append((a, t)) or "")
    assert seen == [("Key Glock", "Ambition For Cash")]


def test_lrclib_answers_of_the_wrong_length_are_refused():
    calls = []

    def get(url):
        calls.append(url)
        if "/get?" in url:
            return {"syncedLyrics": "[00:01.00]x", "duration": 200}
        return [{"syncedLyrics": "[00:01.00]far", "duration": 150},
                {"syncedLyrics": "[00:01.00]near", "duration": 143.4},
                {"syncedLyrics": "", "duration": 143.0}]
    got = lyrics.fetch_lrclib("Key Glock", "Ambition For Cash", 143.0, get=get)
    assert got == "[00:01.00]near"
    assert len(calls) == 2


def test_no_network_means_no_lyrics_not_a_crash():
    def get(url):
        raise OSError("offline")
    assert lyrics.fetch_lrclib("", "Song", 100.0, get=get) == ""


# ---------------------------------------------------------------- one reel

def test_prepare_writes_the_script_and_greys_under_stamps_red_words(tmp_path):
    project = {"song": str(tmp_path / "s.m4a"), "song_offset": 100.0,
               "lyrics": {"look": "stamp"}}
    derived = {"length": 10.0, "kills": [0.6]}
    got = lyrics.prepare(project, derived, tmp_path / "c", 1080, 1920,
                         finder=lambda s, c: (_lines(), "a test"), onsets=lambda *a: [])
    assert got.ass and got.ass.is_file()
    assert got.greys and got.hooks == 1
    assert "a test" in got.note and "moved" not in got.note


def test_the_players_timing_moves_every_line_before_words_are_placed(tmp_path):
    """TISWFLFIL2: LRCLIB's lines came 0.9 s early on the player's copy of the song."""
    project = {"song": str(tmp_path / "s.m4a"), "song_offset": 100.0,
               "lyrics": {"look": "stamp", "shift": 0.5}}
    got = lyrics.prepare(project, {"length": 10.0, "kills": [2.6]}, tmp_path / "c", 1080, 1920,
                         finder=lambda s, c: (_lines(), "a test"), onsets=lambda *a: [])
    events = [ln for ln in got.ass.read_text(encoding="utf-8").splitlines() if ln.startswith("Dialogue:")]
    assert events[0].split(",")[1] == "0:00:00.50"       # the first line was at 0.0 of the reel
    assert "+0.50 s" in got.note


def test_a_timing_is_clamped_and_junk_is_ignored():
    assert lyrics.settings({"look": "glow", "shift": 0.9})["shift"] == 0.9
    assert lyrics.settings({"look": "glow", "shift": 99})["shift"] == lyrics.SHIFT_MAX
    assert lyrics.settings({"look": "glow", "shift": "soon"})["shift"] == 0.0
    assert lyrics.settings({"look": "glow", "shift": float("nan")})["shift"] == 0.0


def test_prepare_says_why_when_there_are_no_words(tmp_path):
    project = {"song": str(tmp_path / "s.m4a"), "song_offset": 0.0, "lyrics": {"look": "glow"}}
    got = lyrics.prepare(project, {"length": 5.0, "kills": []}, tmp_path, 1080, 1920,
                         finder=lambda s, c: ([], ""), onsets=lambda *a: [])
    assert got.ass is None and ".lrc" in got.note
    off = lyrics.prepare({"lyrics": {"look": "off"}}, {"length": 5.0}, tmp_path, 1080, 1920)
    assert off.ass is None and off.note == ""
