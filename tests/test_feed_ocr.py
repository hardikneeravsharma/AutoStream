"""The Valorant second look: OCR only where the colour reader is unsure.

Measured before it was written: on reviewed footage the colour reader found 6
of 12 kills, and on a 33-minute ranked match 14 of 16. Re-reading only the
doubtful rows as text found all of them, with no false kills, for +75% scan
time where reading every frame cost +585%. These tests pin the rules that
produced those numbers, so a change to any of them fails here by name rather
than showing up as a quietly different kill count.

No Tesseract is needed: the reader is injected, and the frames are built here.
"""
from __future__ import annotations

import numpy as np
import pytest

from autostream.clips import feed_ocr as fo
from autostream.clips import valorant_feed as vf


def row(kind="kill", y0=20, y1=54, left=0, right=0, aside=0, at=0.0):
    return vf.Row(time=at, kind=kind, y0=y0, y1=y1, x0=600, x1=940,
                  left=left, right=right, aside=aside)


def ev(t, end=None, kind="kill", x0=600):
    # x0 is how a kill event is matched back to its own row: the left edge of
    # the row's colour run, which holds still while the row is on screen.
    return vf.Event(time=t, kind=kind, end=end if end is not None else t + 4.0, x0=x0)


def capture_with(frames):
    """frames: [(at, rows, slot_yellow, {slot: True})] -> a Capture."""
    cap = fo.Capture(1080)
    for at, rows, yellow, text in frames:
        cap.frames.append(fo.Frame(
            at=at, rows=rows, slot_yellow=tuple(yellow),
            text={s: (np.packbits(np.ones((38, 500), bool)), (38, 500)) for s in text}))
    return cap


def words(name="YuvaNeta", victim="Jett", killer=True):
    x = 600 if killer else 820
    out = [{"text": name, "left": x - 40, "right": x + 40}]
    if killer:
        out.append({"text": victim, "left": 800, "right": 870})
    return out


def run_check(cap, doubt, script, player="YuvaNeta"):
    """fo.check with a reader that knows which frame and slot it is being asked about."""
    frames = cap.by_time()
    calls = []

    def read(bits, shape, k=1.0):
        for at, f in frames.items():
            for s, v in f.text.items():
                if v[0] is bits:
                    calls.append((at, s))
                    return script.get((at, s), [])
        return []

    rows, stats = fo.check(cap, doubt, player, read=read)
    return rows, stats, calls


# ------------------------------------------------------------------ names

def test_the_tag_is_not_part_of_the_name_the_feed_shows():
    assert fo.clean_name("YuvaNeta#IN1") == "YuvaNeta"
    assert fo.clean_name("  Plain ") == "Plain"
    assert fo.clean_name("") == ""


def test_your_name_on_the_left_half_is_a_kill_and_on_the_right_a_death():
    assert fo.player_in(words(killer=True), "YuvaNeta")[0] == "kill"
    assert fo.player_in(words(killer=False), "YuvaNeta")[0] == "death"
    assert fo.player_in([{"text": "SomebodyElse", "left": 600, "right": 680}], "YuvaNeta") is None


def test_ocr_misreads_of_the_name_still_match():
    """Measured on real rows: 'uvaNeta' with a lost first letter still read."""
    assert fo.player_in([{"text": "uvaNeta", "left": 600, "right": 680}], "YuvaNeta")


# ---------------------------------------------------------------- capture

def test_capture_keeps_a_slot_with_white_text_and_drops_an_empty_one():
    a = np.full((178, 960, 3), 90, np.uint8)
    a[25:45, 600:700] = 255                       # a white name in slot 0
    cap = fo.Capture(1080)
    cap.add(a, 1.0, [], np.zeros((178, 960), bool))
    f = cap.frames[0]
    assert 0 in f.text and 1 not in f.text and 2 not in f.text


def test_capture_counts_yellow_per_slot():
    a = np.zeros((178, 960, 3), np.uint8)
    yellow = np.zeros((178, 960), bool)
    yellow[100:130, 500:560] = True               # slot 2
    cap = fo.Capture(1080)
    cap.add(a, 0.0, [], yellow)
    ys = cap.frames[0].slot_yellow
    assert ys[2] == 30 * 60 and ys[0] == 0 and ys[1] == 0


def test_capture_scales_with_the_recording():
    """A 1440p band is 1280px wide; the text window is cut at the same share."""
    a = np.full((237, 1280, 3), 90, np.uint8)
    a[30:60, 800:930] = 255
    cap = fo.Capture(1440)
    cap.add(a, 0.0, [], np.zeros((237, 1280), bool))
    assert 0 in cap.frames[0].text


def test_reusing_the_masks_does_not_change_what_the_reader_reads():
    rng = np.random.default_rng(3)
    a = rng.integers(0, 255, (178, 960, 3), dtype=np.uint8)
    assert vf.read_frame(a, 1.0) == vf.read_frame(a, 1.0, planes=vf.masks(a))


# ------------------------------------------------------------------ doubt

def test_d1_a_kill_frame_no_counted_kill_covers_is_doubtful():
    cap = capture_with([(10.0, [row("kill")], (0, 0, 0), ())])
    assert fo.doubtful(cap, []) == {10.0: {0}}
    assert fo.doubtful(cap, [ev(9.5, end=12.0)]) == {}


def test_d2_a_row_called_assist_that_carries_your_yellow_is_doubtful():
    yellow = row("assist", y0=59, y1=93, aside=vf.ASIDE_FLOOR + 50)
    plain = row("other", y0=59, y1=93, aside=vf.ASIDE_FLOOR - 50)
    assert fo.doubtful(capture_with([(1.0, [yellow], (0, 0, 0), ())]), []) == {1.0: {1}}
    assert fo.doubtful(capture_with([(1.0, [plain], (0, 0, 0), ())]), []) == {}


def test_d3_a_yellow_panel_with_no_row_is_doubtful():
    """The third-row kill behind the performance overlay: never a row at all."""
    # Real quantities, not the constant: a portrait panel is ~1000 yellow px and
    # a stray yellow patch in scenery ~150. The threshold must sit between them.
    cap = capture_with([(2.5, [], (0, 0, 1000), ())])
    assert fo.doubtful(cap, []) == {2.5: {2}}
    stray = capture_with([(2.5, [], (0, 0, 150), ())])
    assert fo.doubtful(stray, []) == {}
    with_row = capture_with([(2.5, [row("kill", y0=98, y1=132)], (0, 0, 900), ())])
    assert fo.doubtful(with_row, [ev(2.0)]) == {}


def test_a_counted_kill_is_not_doubtful():
    cap = capture_with([(5.0, [row("kill")], (900, 0, 0), ())])
    assert fo.doubtful(cap, [ev(5.0)]) == {}


# ------------------------------------------------------------------ check

def _frames(times, slot=0):
    return capture_with([(t, [], (0, 0, 0), (slot,)) for t in times])


def test_a_row_needs_two_readings():
    cap = _frames([10.0, 10.5])
    rows, _, _ = run_check(cap, {10.0: {0}}, {(10.0, 0): words()})
    assert rows == []
    rows, _, _ = run_check(cap, {10.0: {0}, 10.5: {0}},
                           {(10.0, 0): words(), (10.5, 0): words()})
    assert [(r.victim, r.first, r.n) for r in rows] == [("Jett", 10.0, 2)]


def test_your_death_is_never_a_kill():
    cap = _frames([10.0, 10.5])
    script = {(10.0, 0): words(killer=False), (10.5, 0): words(killer=False)}
    rows, _, _ = run_check(cap, {10.0: {0}, 10.5: {0}}, script)
    assert rows == []


def test_a_confirmed_row_is_not_read_again():
    """What makes the check lean: ~6 readings per row became 2."""
    times = [10.0, 10.5, 11.0, 11.5, 12.0]
    cap = _frames(times)
    script = {(t, 0): words() for t in times}
    rows, stats, calls = run_check(cap, {t: {0} for t in times}, script)
    assert len(rows) == 1
    doubtful_reads = [c for c in calls if c[0] >= 10.0]
    assert len(doubtful_reads) == 2, calls


def test_a_confirmed_row_is_followed_back_for_its_start():
    """The kill the colour reader found 2.7s late started when its row appeared."""
    times = [8.5, 9.0, 9.5, 10.0, 10.5]
    cap = _frames(times)
    script = {(t, 0): words() for t in times}
    rows, _, _ = run_check(cap, {10.0: {0}, 10.5: {0}}, script)
    assert rows[0].first == 8.5


def test_two_victims_in_the_same_moment_are_two_rows():
    """The stacked double kill: one row per victim, not one per moment."""
    cap = capture_with([(t, [], (0, 0, 0), (0, 1)) for t in (90.0, 90.5)])
    script = {}
    for t in (90.0, 90.5):
        script[(t, 0)] = words(victim="Thornix")
        script[(t, 1)] = words(victim="wh1tebeard")
    rows, _, _ = run_check(cap, {90.0: {0, 1}, 90.5: {0, 1}}, script)
    assert sorted(r.victim for r in rows) == ["Thornix", "wh1tebeard"]


# ------------------------------------------------------------------ merge

def test_a_row_nobody_counted_is_added_as_a_kill():
    out, added, retimed = fo.merge([], [fo.OcrRow("Jett", 74.5, 79.0, 0, 3)])
    assert added == 1 and retimed == 0
    assert [(e.kind, e.time, e.votes) for e in out] == [("kill", 74.5, "ocr")]


def test_a_counted_kill_takes_the_earlier_start_and_is_not_doubled():
    late = ev(28.4, end=30.0)
    out, added, retimed = fo.merge([late], [fo.OcrRow("Yamastra", 25.5, 28.0, 0, 6)])
    assert added == 0 and retimed == 1
    assert [e.time for e in out if e.kind == "kill"] == [25.5]


def test_one_counted_kill_absorbs_one_row_only():
    """Double kill counted once by colour: the second victim is still new."""
    counted = ev(92.0, end=98.5)
    rows = [fo.OcrRow("Thornix", 89.5, 94.0, 0, 3), fo.OcrRow("wh1tebeard", 90.5, 95.0, 1, 3)]
    out, added, _ = fo.merge([counted], rows)
    assert added == 1
    assert len([e for e in out if e.kind == "kill"]) == 2


def test_deaths_and_assists_are_left_alone():
    death = ev(30.0, kind="death")
    out, added, retimed = fo.merge([death], [])
    assert out == [death] and added == 0 and retimed == 0


# ---------------------------------------------------------------- learning

def _learn_cap(n_frames, x0=600):
    """Frames in which the colour reader saw the player's own kill row."""
    return capture_with([(float(t), [row("kill", at=float(t))], (0, 0, 0), (0,))
                         for t in range(n_frames)])


def test_the_name_is_learned_from_rows_already_counted_as_yours():
    cap = _learn_cap(8)
    kills = [ev(float(t), end=float(t) + 2.0) for t in (0.0, 4.0)]
    got = fo.learn_name(cap, kills,
                        read=lambda b, s, k=1.0: [{"text": "YuvaNeta", "left": 560, "right": 640}])
    assert got == "YuvaNeta"


def test_one_kill_is_enough_to_learn_the_name():
    """A 100-second excerpt holds one kill. Asking for three votes meant the
    check silently did nothing on exactly the recordings that needed it."""
    cap = _learn_cap(4)
    got = fo.learn_name(cap, [ev(0.0, end=3.0)],
                        read=lambda b, s, k=1.0: [{"text": "YuvaNeta", "left": 560, "right": 640}])
    assert got == "YuvaNeta"


def test_only_the_players_own_kill_row_votes():
    """FROM A BUG. Reading every slot of the frame voted on teammates' rows
    too, and on one excerpt a teammate won -- so the name was refused and the
    whole check did nothing. The row is matched by its own left edge."""
    mine = row("kill", at=0.0)                       # x0 600, the event's row
    theirs = row("kill", y0=59, y1=93, at=0.0)
    theirs.x0 = 900                                  # a different row entirely
    cap = capture_with([(0.0, [mine, theirs], (0, 0, 0), (0, 1)),
                        (0.5, [mine, theirs], (0, 0, 0), (0, 1))])
    names = {0: "YuvaNeta", 1: "Teammate"}
    seen = []

    def read(bits, shape, k=1.0):
        for f in cap.frames:
            for slot, v in f.text.items():
                if v[0] is bits:
                    seen.append(slot)
                    return [{"text": names[slot], "left": 560, "right": 640}]
        return []

    assert fo.learn_name(cap, [ev(0.0, end=1.0)], read=read) == "YuvaNeta"
    assert set(seen) == {0}, "read a row that was not the player's kill"


def test_too_little_agreement_learns_nothing():
    cap = _learn_cap(6)
    names = iter(["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"])
    got = fo.learn_name(cap, [ev(float(t), end=float(t) + 1.0) for t in (0.0, 2.0, 4.0)],
                        read=lambda b, s, k=1.0: [{"text": next(names), "left": 560, "right": 640}])
    assert got == ""


# ---------------------------------------------------------------- safety

def test_without_tesseract_the_events_come_back_untouched(monkeypatch):
    monkeypatch.setattr("autostream.clips.deps.ocr_ready", lambda: False)
    events = [ev(10.0)]
    cap = _frames([10.0])
    assert fo.second_look(events, cap, {10.0: {0}}, player="YuvaNeta") is events


def test_a_failure_inside_the_check_never_costs_the_colour_readers_kills(monkeypatch):
    monkeypatch.setattr("autostream.clips.deps.ocr_ready", lambda: True)

    def boom(*a, **kw):
        raise RuntimeError("tesseract fell over")

    monkeypatch.setattr(fo, "check", boom)
    events = [ev(10.0)]
    assert fo.second_look(events, _frames([10.0]), {10.0: {0}}, player="YuvaNeta") is events


def test_with_no_doubt_nothing_is_read(monkeypatch):
    monkeypatch.setattr(fo, "check", lambda *a, **kw: pytest.fail("read with nothing doubtful"))
    events = [ev(10.0)]
    assert fo.second_look(events, _frames([10.0]), {}, player="YuvaNeta") is events


def test_the_clip_job_turns_the_second_look_on(monkeypatch, tmp_path):
    from autostream.clips import detect, profiles

    seen = {}

    def fake_scan(video, band, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(vf, "scan", fake_scan)
    monkeypatch.setattr(profiles, "username_for", lambda key, name=None: "YuvaNeta#IN1")
    prof = profiles.for_game("valorant-win64-shipping.exe")
    detect.scan_feedbar(tmp_path / "x.mp4", prof, 10.0, 1080, None, None)
    assert seen["second_look"] is True
    assert seen["player"] in ("YuvaNeta#IN1", prof.player)


def test_the_colour_reader_alone_is_still_available():
    import inspect
    assert inspect.signature(vf.scan).parameters["second_look"].default is False
