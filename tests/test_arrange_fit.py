"""The fit arranger: order and timing searched together, every multi-kill clip whole.

Synthetic clips and songs only -- no files, no ffmpeg. What these pin is the
promise the arranger makes over studio.plan(): every kill of a clip with three
or more is in the reel exactly once and in order, every shot's kill is on one
of the song's hits to the frame, no footage plays twice, and the programme at
its heart really is the optimum it claims to be (checked against brute force).
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field

import numpy as np
import pytest

from autostream.clips import arrange_fit, rulebook, studio

FRAME = 1.0 / studio.FPS


@dataclass
class Shape:
    """What the planner reads off a song analysis."""
    bpm: float = 120.0
    seconds: float = 120.0
    phase: float = 0.0
    drop: float | None = None
    drums_in: float | None = None
    downbeat_pos: int = 0
    beats: list = field(default_factory=list)
    hits: list = field(default_factory=list)
    hit_strength: list = field(default_factory=list)
    big: list = field(default_factory=list)
    peaks: list = field(default_factory=list)
    pattern: str = "bass hits"

    @property
    def beat(self) -> float:
        return 60.0 / self.bpm

    def __post_init__(self):
        if not self.beats:
            n = int((self.seconds - self.phase) / self.beat)
            self.beats = [self.phase + i * self.beat for i in range(n)]


def _song(seconds: float = 120.0, seed: int = 3, **kw) -> Shape:
    """Hits that are NOT a metronome: an eighth-note grid with some hits missing
    and every one pushed a few milliseconds, as real kick detection gives."""
    rng = random.Random(seed)
    hits, strength = [], []
    t = 1.0
    while t < seconds - 0.5:
        if rng.random() < 0.7:
            hits.append(round(t + rng.uniform(-0.02, 0.02), 4))
            strength.append(rng.uniform(0.8, 1.2))
        t += 0.25
    big = [h for h in hits if 8.0 <= h <= 9.0][:1] + [h for h in hits if 40.0 <= h <= 41.0][:1]
    return Shape(seconds=seconds, hits=hits, hit_strength=strength, big=big, **kw)


def _clip(name: str, kills: list[float], seconds: float = 30.0) -> dict:
    return {"path": f"C:/clips/run/clips/{name}.mp4", "name": name, "id": name,
            "duration": seconds, "kills": list(kills), "kill_count": len(kills),
            "mtime": 1, "game": "VALORANT", "at": ""}


def _clips() -> list[dict]:
    return [
        _clip("quadra", [3.5, 5.4, 17.6, 18.43], 26.0),       # two pairs of a round's kills
        _clip("triple_chain", [4.0, 4.9, 6.1], 12.0),          # three inside three seconds
        _clip("triple_round", [3.6, 23.1, 41.8], 50.0),        # three far apart
        _clip("double", [3.8, 10.8], 20.0),
        _clip("lead", [0.3, 1.2], 8.0),                        # its first kill has no run-up
        _clip("single_a", [3.5], 9.0),
        _clip("single_b", [4.0], 10.0),
        _clip("single_c", [3.7], 8.0),
    ]


def _plan(clips=None, style="hype", shape=None, **kw):
    shape = shape or _song()
    return arrange_fit.plan(clips or _clips(), style, shape=shape, song="s.mp3",
                            iterations=kw.pop("iterations", 60), **kw)


def _shown(proj: dict) -> tuple[list[tuple[str, float]], dict]:
    """Every kill the reel shows, (clip, kill), in reel order, from derive()."""
    d = studio.derive(proj)
    out = []
    for s, row in zip(proj["shots"], d["shots"]):
        a, b = row["source_in"], row["source_out"]
        for k in sorted(s["kills"]):
            if a - 1e-6 <= k <= b + 1e-6:
                out.append((s["clip"], round(k, 3)))
    return out, d


# ------------------------------------------------------------------ the promises

@pytest.mark.parametrize("style", ["hype", "story", "montage", "velocity"])
def test_every_kill_of_a_multi_kill_clip_is_shown_once_in_order(style):
    proj, _ = _plan(style=style)
    shown, _d = _shown(proj)
    assert len(shown) == len(set(shown)), "a kill is shown twice"
    for c in _clips():
        if len(c["kills"]) < arrange_fit.MUST_KILLS:
            continue
        mine = [k for p, k in shown if p == c["path"]]
        assert mine == [round(k, 3) for k in c["kills"]], f"{style}: {c['name']} shows {mine}"


def test_every_shot_kill_lands_on_a_hit_to_the_frame():
    shape = _song()
    proj, _ = _plan(shape=shape)
    d = studio.derive(proj)
    off = proj["song_offset"]
    for row in d["shots"]:
        assert abs(row["drift"]) <= FRAME, f"shot {row['index']} is {row['drift']:.4f} s off its mark"
        t = row["kill_reel"] + off
        assert min(abs(t - h) for h in shape.hits) <= FRAME
    assert d["on_marks"] == len(d["shots"])


@pytest.mark.parametrize("style", ["hype", "velocity", "short", "chaos"])
def test_no_footage_plays_twice(style):
    proj, _ = _plan(style=style)
    d = studio.derive(proj)
    rows = d["shots"]
    shots = proj["shots"]
    for i, j in itertools.combinations(range(len(shots)), 2):
        if shots[i]["clip"] != shots[j]["clip"]:
            continue
        overlap = min(rows[i]["source_out"], rows[j]["source_out"]) - max(rows[i]["source_in"], rows[j]["source_in"])
        assert overlap <= FRAME, f"shots {i} and {j} share {overlap:.3f} s of footage"


@pytest.mark.parametrize("style", ["velocity", "short", "chaos", "story"])
def test_every_kill_has_a_run_up_and_plays_at_real_speed_or_slower(style):
    proj, _ = _plan(style=style)
    run_min = max(rulebook.MIN_RUN_BEATS * proj["beat"], rulebook.MIN_RUN_SECONDS)
    d = studio.derive(proj)
    for s, row in zip(proj["shots"], d["shots"]):
        assert s["pre"] >= run_min - 1e-4
        ps = [tuple(p) for p in row["pieces"]]
        for k in s["kills"]:
            out = studio.output_at(ps, k - row["source_in"])
            rate = next(r for a, b, r in ps if a - 1e-9 <= out <= b + 1e-9)
            assert rate <= 1.0 + 1e-9, f"a kill at {k} plays at {rate}x"
        assert row["source_in"] >= -1e-4 and row["source_out"] <= s["clip_seconds"] + 1e-4


def test_a_kill_with_no_run_up_rides_in_the_next_ones():
    proj, _ = _plan()
    shown, _d = _shown(proj)
    lead = _clips()[4]["path"]
    assert [k for p, k in shown if p == lead] == [0.3, 1.2]


def test_the_reel_ends_inside_the_song_part():
    shape = _song(seconds=200.0)
    proj, _ = _plan(shape=shape, part=(20.0, 50.0))
    d = studio.derive(proj)
    assert proj["song_offset"] >= 20.0 - 1e-6
    assert proj["song_offset"] + d["length"] <= 50.0 + 1e-6


def test_a_short_part_leaves_out_single_kills_never_a_triple():
    shape = _song(seconds=200.0)
    proj, notes = _plan(shape=shape, part=(20.0, 32.0))
    shown, _d = _shown(proj)
    for c in _clips():
        if len(c["kills"]) >= arrange_fit.MUST_KILLS:
            assert [k for p, k in shown if p == c["path"]] == [round(k, 3) for k in c["kills"]]
    out = [r for r in proj["selection"] if r["why"]]
    assert out, "a 12 s part held all 8 clips -- the test no longer squeezes"
    assert all(len(next(c for c in _clips() if c["path"] == r["clip"])["kills"]) < arrange_fit.MUST_KILLS
               for r in out)


def test_a_part_too_short_for_every_triple_says_so_and_still_fits():
    shape = _song(seconds=200.0)
    proj, notes = _plan(shape=shape, part=(20.0, 28.0))
    assert any("too short to hold every clip" in n for n in notes)
    d = studio.derive(proj)
    assert all(abs(r["drift"]) <= FRAME for r in d["shots"])
    assert proj["song_offset"] + d["length"] <= 28.0 + 1e-6


def test_the_same_clips_plan_the_same_reel():
    a, _ = _plan()
    b, _ = _plan()
    assert a == b


def test_without_hits_it_is_the_ordinary_planner():
    shape = Shape(seconds=120.0)
    a, notes = arrange_fit.plan(_clips(), "hype", shape=shape, song="s.mp3")
    b, _ = studio.plan(_clips(), "hype", shape=shape, song="s.mp3")
    assert a["shots"] == b["shots"]
    assert a["arrange"] == "fit", "a rebuild would forget the choice"
    assert any("planned the usual way" in n for n in notes)


def test_a_pinned_opener_stays_first():
    pin = _clips()[6]["path"]
    proj, _ = _plan(shape_it={"pins": {"open": pin}})
    assert proj["shots"][0]["clip"] == pin


@pytest.mark.parametrize("style", ["hype", "velocity", "chaos"])
def test_the_project_survives_normalise(tmp_path, style):
    root = tmp_path / "clips"
    (root / "run" / "clips").mkdir(parents=True)
    clips = []
    for c in _clips():
        p = root / "run" / "clips" / (c["name"] + ".mp4")
        p.write_bytes(b"x")
        clips.append(dict(c, path=str(p), mtime=int(p.stat().st_mtime)))
    proj, _ = arrange_fit.plan(clips, style, shape=_song(), song="", iterations=10)
    assert proj["shots"]                          # no song: the ordinary planner
    proj, _ = arrange_fit.plan(clips, style, shape=_song(), song="s.mp3", iterations=10)
    proj["song"] = ""                             # not on disk; the shots are the point
    got, derived, notes = studio.normalise(proj, root, probe=lambda p: 0.0)
    # normalise() trims a shot asking for footage its clip lacks, and a trim
    # moves every cut after it off its hit: none may be asked for, at any speed.
    assert [s["pre"] for s in got["shots"]] == [s["pre"] for s in proj["shots"]]
    assert [s["duration"] for s in got["shots"]] == [s["duration"] for s in proj["shots"]]
    assert [s["speed"] for s in got["shots"]] == [s["speed"] for s in proj["shots"]]
    assert not [n for n in notes if "trimmed" in n]
    assert got["arrange"] == "fit", "normalise() threw the arrangement away"


# ------------------------------------------------------------------ at each shot's own speed

@pytest.mark.parametrize("speed", ["s00", "s01", "s02", "s03", "s04", "s05", "s06"])
def test_the_speed_tables_are_the_renderers_own_time_map(speed):
    """The programme plans through Ramp; the render plays studio.pieces(). They
    must be the same map, between the table's corners as well as on them."""
    rp = arrange_fit.Ramp(speed)
    for r in np.arange(0.0, 11.5, 0.0173):
        want = studio.source_used(studio.pieces(speed, r + 30.0, r), r)
        assert float(rp.pre_src(r)) == pytest.approx(want, abs=1e-9)
        assert float(rp.pre_out(want)) == pytest.approx(r, abs=1e-6) or want == 0.0
    for own in (0.0, 0.8, 2.4):
        ps = studio.pieces(speed, 20.0 + 12.0, 20.0, own=own)
        for t in np.arange(0.0, 11.5, 0.0173):
            want = studio.source_used(ps, 20.0 + t) - studio.source_used(ps, 20.0)
            assert float(rp.post_src(t, own)) == pytest.approx(want, abs=1e-9)


def test_a_velocity_reel_keeps_its_ramps():
    """Velocity's speed is a shape every kill gets (studio.speed_curves) since
    2026-10-23, not a preset drawn per shot -- and Perfect fit gives it too: most
    shots rush in, slow through the kill and rush out."""
    proj, notes = _plan(style="velocity")
    shaped = [s for s in proj["shots"] if s.get("anchors")]
    assert len(shaped) >= len(proj["shots"]) * 3 // 4, f"only {len(shaped)} of {len(proj['shots'])} shots shaped"
    for s in shaped:
        ps = studio.shot_pieces(s)
        p = float(s["pre"])
        slow = (studio.source_used(ps, p + 0.05) - studio.source_used(ps, p - 0.05)) / 0.1
        assert 0.5 <= slow <= 0.7, slow
    assert not [n for n in notes if "changed speed" in n], notes


def test_a_drop_reel_lands_its_fourth_kill_on_the_drop():
    shape = _song(drop=60.0)
    proj, notes = _plan(style="drop", shape=shape)
    d = studio.derive(proj)
    fourth = d["shots"][3]["kill_reel"] + proj["song_offset"]
    near = min(shape.hits, key=lambda h: abs(h - 60.0))
    assert fourth == pytest.approx(near, abs=FRAME), f"the fourth kill is at {fourth:.3f}, the drop's hit at {near:.3f}"
    assert any("fourth kill lands on the song's drop" in n for n in notes)


def test_a_quiet_intro_is_built_over_at_half_speed():
    """studio.plan()'s build: two bars of half-speed run-up over a quiet intro,
    the opener's kill arriving with the drums, and the intro effect for it."""
    n = 1200
    peaks = [0.2 if i * 120.0 / n < 16.0 else 1.0 for i in range(n)]
    shape = _song(drums_in=16.0)
    shape.peaks = peaks
    proj, _ = _plan(style="story", shape=shape)
    assert proj["intro"] == "i12"
    assert proj["shots"][0]["speed"] == "s05"
    first = proj["song_offset"] + proj["shots"][0]["pre"]
    assert first >= 16.0 - 1e-6, f"the opener's kill at {first:.2f} s lands before the drums"
    assert proj["shots"][0]["pre"] >= 3 * proj["beat"], "the build is too short to be one"


def test_the_search_is_a_count_not_a_clock(monkeypatch):
    """The same clips and song plan the same reel on any machine: nothing in
    the search may look at the time."""
    import inspect
    import time

    assert "budget" not in inspect.signature(arrange_fit.plan).parameters
    a, _ = _plan(iterations=30)
    ticks = iter(range(10 ** 9))
    monkeypatch.setattr(time, "perf_counter", lambda: next(ticks) * 1000.0)
    monkeypatch.setattr(time, "time", lambda: next(ticks) * 1000.0)
    b, _ = _plan(iterations=30)
    assert a == b


def test_studio_plan_hands_a_fit_to_the_arranger():
    proj, notes = studio.plan(_clips(), "hype", shape=_song(), song="s.mp3",
                              shape_it={"arrange": "fit"})
    assert proj["arrange"] == "fit"
    assert any("Perfect fit" in n for n in notes)


def test_a_failure_in_the_arranger_plans_the_usual_way(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no")
    monkeypatch.setattr(arrange_fit, "plan", boom)
    proj, notes = studio.plan(_clips(), "hype", shape=_song(), song="s.mp3", shape_it={"arrange": "fit"})
    assert proj["shots"] and proj["arrange"] == "fit"
    assert any("could not plan this reel" in n for n in notes)


# ------------------------------------------------------------------ the programme is exact

def _brute(fit: arrange_fit.Fitter, order: list[int]) -> float:
    """Every anchor/rider choice, every position and every clip left off the end,
    scored with the programme's own terms."""
    best = arrange_fit.NEG
    pen = 0.0
    for s in range(0, arrange_fit.MAX_SKIP + 1):
        if s:
            gone = fit.blocks[order[len(order) - s]]
            if gone.must or len(order) - s < 1:
                break
            pen += fit.w["kill"] * gone.total
        kept = fit.events(order[:len(order) - s])
        best = max(best, _brute_events(fit, kept) - pen)
    return best + fit.order_score(order)


def _brute_events(fit: arrange_fit.Fitter, ev: list[tuple]) -> float:
    T = fit.song.T
    P = len(T)
    s0, _ = fit.start(ev)
    best = arrange_fit.NEG
    riders_ok = [False] + [ev[e][1] > 0 and ev[e][2] - ev[e - 1][2] <= arrange_fit.JOIN_WITHIN + 1e-9
                           for e in range(1, len(ev))]
    choices = [[True]] + [[True, False] if riders_ok[e] else [True] for e in range(1, len(ev))]
    for anchor_mask in itertools.product(*choices):
        anchors = [e for e in range(len(ev)) if anchor_mask[e]]
        # r for the last event of each shot
        shots = []
        for n, a in enumerate(anchors):
            last = (anchors[n + 1] - 1) if n + 1 < len(anchors) else len(ev) - 1
            shots.append((a, last))
        for pos in itertools.combinations(range(P), len(anchors)):
            sc = s0[pos[0]] + fit._node(fit.blocks[ev[0][0]])[pos[0]]
            if sc <= arrange_fit.NEG / 2:
                continue
            ok = True
            for n, (a, last) in enumerate(shots):
                for x in range(a + 1, last + 1):
                    sc += fit._ride(arrange_fit.ramp(fit.speed(ev, a)), ev[x][2] - ev[a][2])[pos[n]]
                if n + 1 < len(shots):
                    p, q = pos[n], pos[n + 1]
                    e = shots[n + 1][0]
                    edge, _cut = fit.edge(ev, last, last - a, e, np.array([T[p]]), np.array([T[q]]))
                    if q - p > fit.song.IDX.shape[1]:
                        ok = False
                        break
                    sc += float(edge[0]) + fit._node(fit.blocks[ev[e][0]])[q]
                    if sc <= arrange_fit.NEG / 2:
                        ok = False
                        break
            if not ok:
                continue
            a, last = shots[-1]
            end, _stop = fit.end(ev, last, last - a, np.array([T[pos[-1]]]), fit.r.first - fit.r.open_want)
            sc += float(end[0])
            best = max(best, sc)
    return best


def test_the_programme_finds_the_brute_force_optimum():
    clips = [_clip("pair", [2.0, 3.1], 8.0), _clip("one", [2.5], 6.0)]
    blocks, _why, _lost = arrange_fit._blocks(clips, {c["path"]: c["kills"] for c in clips},
                                              {c["path"]: 2.0 * len(c["kills"]) for c in clips}, {}, 0.5)
    grid = studio.Grid.of(_song(seconds=12.0, seed=7))
    rules = arrange_fit.Rules(gap=1.1, run_min=0.5, readable=0.66, run_cap=2.2, max_lead=8.0,
                              tail_pref=0.44, open_want=1.6, close_want=0.5, floor=0.0,
                              end_cap=11.5, first=2.0, start_window=1.0, soft_max=86.0)
    song = arrange_fit.Song.of(grid, 1.0, 8.0, 8.0)
    fit = arrange_fit.Fitter(blocks, song, rules)
    for order in ([0, 1], [1, 0]):
        got, _ = fit.solve(order)
        want = _brute(fit, order)
        assert got > arrange_fit.NEG / 2, f"order {order} has no feasible reel -- the test proves nothing"
        assert got == pytest.approx(want, abs=1e-6), f"order {order}: programme {got} against {want}"
