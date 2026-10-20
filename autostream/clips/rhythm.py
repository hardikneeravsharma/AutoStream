"""The song's rhythm as layers: kick, snare and hats, the cues they make together,
the energy curve and the sections a reel is cut in.

WHY THIS EXISTS. reel.analyse finds one beat grid and the hits a kill belongs on,
and until now a reel used nothing else: every transition, camera move and effect
was either on that one grid or on nothing at all. A song is several rhythms at
once -- a kick every beat, a clap on two and four, hats on every eighth -- and an
editor gives each a job: the kick carries the kills, the snare carries the cuts,
the hats carry the small movement in between, and the song's sections decide how
busy all of it is. This module reads those layers; the planner and the effects
decide what each one drives.

reel.analyse's grid is left exactly as it is -- it was tuned against 662 hand
marks -- and this module reads on top of it. Where the grid's phase is not on
the kick (Y Que Fue's grid sits on the dembow snare, half a beat off), that is
reported as `kick_phase` rather than corrected underneath everything else.

Pure numpy over a mono float32 signal at SR, so tests feed it synthetic drums
and need no ffmpeg.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

SR = 22050
HOP = 64                      # 2.9 ms between readings of every band

# Each layer: the band it is read in (Hz) and the window its loudness is read
# over (samples). A kick is below 150 Hz and needs a long window to be heard at
# all; a snare or clap is a noise burst that owns 1.5-5 kHz; hats live above
# 7 kHz and are short. Read with a 46 ms spectrogram, every kick came out ~22 ms
# late and the hits smeared into each other; band-passed signals read with short
# windows put snares and hats on the grid within one 3 ms step.
BANDS = {"kick": (30.0, 150.0, 512), "snare": (1500.0, 5000.0, 256), "hats": (7000.0, 11000.0, 128)}

# A hit is a local peak of its band's rise that stands out twice over: above the
# local median by PEAK_K deviations, and at least PEAK_REL of the strongest rise
# within a second either side. Local, not a song-wide percentile -- a percentile
# cut left nine-second holes in the hats of a quiet verse -- and the second test
# is what stops a bass line's wobble reading as a kick every 0.1 s.
PEAK_WINDOW_S = 1.0
PEAK_K = 3.0
PEAK_REL = 0.3
# ...and a hit must be loud in its own band against the hits around it: a hat's
# noise reaches into the snare band, and without this every hat was a snare too.
PEAK_LEVEL = 0.3
# ...and not so quiet against the song's own hits that it is only bleed: with no
# kick playing, a clap's low end still rises, and the local tests alone took it
# for a kick. Measured on synthetic drums: hats played at a seventh of the
# volume read at 5-8 % of the band's loudest hits (a snare's top end is in the
# hats band too), bleed at under 1.5 %.
PEAK_FLOOR = 0.03
TRANSIENT = "transient"       # the full band, read short: where a kick's click is
TRANSIENT_WIN = 128
MIN_GAP_S = 0.07              # two hits in one band closer than this are one hit
CLUSTER_S = 0.030             # hits in different bands this close are one cue
ENERGY_HZ = 10                # the energy curve's rate

SCHEMA = 3                    # bump when the cached shape of the answer changes


@dataclass
class Layer:
    name: str
    times: list[float] = field(default_factory=list)
    strength: list[float] = field(default_factory=list)   # 0..1, loudness of the hit within its band

    def median_gap(self) -> float:
        g = np.diff(self.times)
        return float(np.median(g)) if g.size else 0.0


@dataclass
class Section:
    start: float
    end: float
    kind: str        # intro, verse, build, riser, drop, groove, break, outro
    energy: float    # 0..1, mean over the section


@dataclass
class Rhythm:
    seconds: float
    beat: float
    phase: float                  # the grid reel.analyse uses
    kick_phase: float             # the same beat, phased on the kick
    downbeat_pos: int
    layers: dict[str, Layer]
    cues: list[dict]              # {"t", "kick", "snare", "hats", "strength"}
    energy: list[float]           # 0..1 at ENERGY_HZ
    sections: list[Section]

    @property
    def kick_offset(self) -> float:
        """How far the kick sits from the grid, in beats (-0.5..0.5).

        About 0.5 means the grid is on the off-beat: Y Que Fue's case."""
        if not self.beat:
            return 0.0
        d = ((self.kick_phase - self.phase) / self.beat) % 1.0
        return d - 1.0 if d > 0.5 else d

    def section_at(self, t: float) -> Section | None:
        for s in self.sections:
            if s.start <= t < s.end:
                return s
        return None

    def events(self, layer: str, a: float, b: float, min_strength: float = 0.0) -> list[tuple[float, float]]:
        """(time, strength) of one layer's hits between a and b."""
        L = self.layers.get(layer)
        if not L:
            return []
        return [(t, s) for t, s in zip(L.times, L.strength) if a <= t < b and s >= min_strength]

    def as_dict(self) -> dict:
        return {
            "schema": SCHEMA, "seconds": round(self.seconds, 3), "beat": round(self.beat, 6),
            "phase": round(self.phase, 4), "kick_phase": round(self.kick_phase, 4),
            "kick_offset": round(self.kick_offset, 3), "downbeat_pos": self.downbeat_pos,
            "layers": {k: {"times": [round(t, 4) for t in v.times],
                           "strength": [round(s, 3) for s in v.strength],
                           "median_gap": round(v.median_gap(), 4)} for k, v in self.layers.items()},
            "cues": self.cues,
            "energy": [round(e, 3) for e in self.energy],
            "sections": [asdict(s) for s in self.sections],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Rhythm":
        if d.get("schema") != SCHEMA:
            raise ValueError("an older rhythm")
        return cls(
            seconds=d["seconds"], beat=d["beat"], phase=d["phase"], kick_phase=d["kick_phase"],
            downbeat_pos=d.get("downbeat_pos", 0),
            layers={k: Layer(k, v["times"], v["strength"]) for k, v in d["layers"].items()},
            cues=d.get("cues") or [], energy=d.get("energy") or [],
            sections=[Section(**s) for s in d.get("sections") or []])


# ------------------------------------------------------------------ the bands

def _band(X: np.ndarray, freqs: np.ndarray, n: int, lo: float, hi: float) -> np.ndarray:
    return np.fft.irfft(np.where((freqs >= lo) & (freqs < hi), X, 0), n)


def _mean_square(y: np.ndarray, w: int) -> tuple[np.ndarray, np.ndarray]:
    """Mean square of y over windows of w samples every HOP, and each window's start."""
    c = np.concatenate([[0.0], np.cumsum(y * y)])
    starts = np.arange(0, len(y) - w, HOP)
    return (c[starts + w] - c[starts]) / w, starts


def band_curves(x: np.ndarray) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Per band: (times, rise, level). Rise is the log-energy increase -- it peaks
    where a hit begins, however loud -- and level is the band's loudness just after,
    which is what a hit's strength is read from. A time is where the reading
    window's newest sample is, so a rise is stamped at the hit, not half a window on."""
    n = len(x)
    out = {}
    if n < 4 * 512:
        return {k: (np.zeros(0), np.zeros(0), np.zeros(0)) for k in BANDS}
    X = np.fft.rfft(np.asarray(x, np.float64))
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    for name, (lo, hi, w) in BANDS.items():
        out[name] = _rise(_band(X, freqs, n, lo, hi), w)
    out[TRANSIENT] = _rise(np.asarray(x, np.float64), TRANSIENT_WIN)
    return out


def _rise(y: np.ndarray, w: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ms, starts = _mean_square(y, w)
    floor = float(np.percentile(ms, 50)) * 0.05 + 1e-12
    e = np.log(ms + floor)
    lag = max(1, w // (2 * HOP))
    rise = np.maximum(e - np.concatenate([np.full(lag, e[0]), e[:-lag]]), 0.0)
    level = np.sqrt(ms)
    # the level a hit reaches: the window that has just taken all of it in
    ahead = np.concatenate([level[w // HOP:], np.full(min(len(level), w // HOP), level[-1])])
    return (starts + w) / SR, rise, ahead


def on_transient(times: list[float], transient: tuple[np.ndarray, np.ndarray, np.ndarray], w: int) -> list[float]:
    """Move each kick onto the click that starts it.

    A kick's low end swells for a window or more after the beater lands, and with
    a bass line under it the swell is what the low band sees: on That Acid every
    kick read ~45 ms late (a 512-sample window) and ~22 ms with 256. The click is
    broadband and short, so the strongest full-band rise in the stretch the kick
    could have started in is where it did. With no click there (a pure 808), the
    window's middle is the honest guess."""
    tt, rise, _ = transient
    if not len(tt):
        return times
    fps = SR / HOP
    local = _max_filter(rise, int(PEAK_WINDOW_S * fps))
    out = []
    for t in times:
        a, b = np.searchsorted(tt, [t - 1.2 * w / SR - 0.01, t + 0.01])
        if b > a:
            i = a + int(np.argmax(rise[a:b]))
            if rise[i] >= 0.25 * local[i]:
                out.append(round(float(tt[i]), 4))
                continue
        out.append(round(t - 0.5 * w / SR, 4))
    return out


def _local_stat(v: np.ndarray, w: int, fn) -> np.ndarray:
    """fn (median) over a sliding window, computed on a coarse grid and interpolated."""
    if v.size == 0:
        return v
    step = max(1, w // 8)
    centres = np.arange(0, v.size, step)
    vals = np.array([fn(v[max(0, c - w // 2):c + w // 2 + 1]) for c in centres])
    return np.interp(np.arange(v.size), centres, vals)


def _max_filter(v: np.ndarray, half: int) -> np.ndarray:
    from numpy.lib.stride_tricks import sliding_window_view
    return sliding_window_view(np.pad(v, half, mode="edge"), 2 * half + 1).max(axis=1)


def peaks(times: np.ndarray, rise: np.ndarray, level: np.ndarray) -> tuple[list[float], list[float]]:
    """One band's hits, at least MIN_GAP_S apart, with a strength each (0..1)."""
    if rise.size < 3:
        return [], []
    fps = SR / HOP
    w = int(PEAK_WINDOW_S * fps)
    med = _local_stat(rise, w, np.median)
    mad = _local_stat(np.abs(rise - med), w, np.median)
    thr = np.maximum(med + PEAK_K * 1.4826 * mad, PEAK_REL * _max_filter(rise, w))
    lm = _max_filter(rise, max(1, int(MIN_GAP_S * fps)))
    idx = np.where((rise >= lm) & (rise > thr) & (rise > 0))[0]
    # a plateau has several equal maxima in a row; keep the first of each
    keep = np.array([i for k, i in enumerate(idx) if k == 0 or i - idx[k - 1] > 1], dtype=int)
    if not keep.size:
        return [], []
    lv = level[keep]
    # the loudest hit within PEAK_WINDOW_S of each, among the hits themselves
    t = times[keep]
    a = np.searchsorted(t, t - PEAK_WINDOW_S)
    b = np.searchsorted(t, t + PEAK_WINDOW_S, side="right")
    near = np.array([lv[i:j].max() for i, j in zip(a, b)])
    ok = lv >= PEAK_LEVEL * near
    keep, lv = keep[ok], lv[ok]
    top = float(np.percentile(lv, 95)) or 1.0
    ok = lv >= PEAK_FLOOR * top
    keep, lv = keep[ok], lv[ok]
    return ([round(float(times[i]), 4) for i in keep], [round(min(1.0, float(v) / top), 3) for v in lv])


def kick_phase(times: list[float], strength: list[float], beat: float, phase: float) -> float:
    """The grid's phase (same beat length) that the kick hits sit on, by circular mean."""
    if beat <= 0 or len(times) < 8:
        return phase
    t = np.asarray(times)
    s = np.asarray(strength)
    ang = 2 * np.pi * ((t - phase) / beat)
    z = np.sum(s * np.exp(1j * ang))
    if abs(z) < 0.15 * s.sum():
        return phase          # no clear kick phase: the grid stands
    return float((phase + beat * (np.angle(z) / (2 * np.pi))) % beat)


def cluster(layers: dict[str, Layer]) -> list[dict]:
    """Hits in different layers within CLUSTER_S of each other become one cue."""
    ev = sorted((t, k, s) for k, L in layers.items() for t, s in zip(L.times, L.strength))
    cues: list[dict] = []
    for t, k, s in ev:
        if cues and t - cues[-1]["t"] <= CLUSTER_S:
            cues[-1][k] = max(cues[-1].get(k, 0.0), s)
        else:
            cues.append({"t": t, k: s})
    out = []
    for c in cues:
        vals = [c.get(k, 0.0) for k in BANDS]
        strength = max(vals) + 0.3 * (sum(vals) - max(vals))
        out.append({"t": round(c["t"], 4), **{k: round(c.get(k, 0.0), 3) for k in BANDS},
                    "strength": round(min(1.0, strength), 3)})
    return out


# ------------------------------------------------------------------ sections

def energy_curve(x: np.ndarray, seconds: float) -> list[float]:
    """Loudness at ENERGY_HZ, smoothed over a second and scaled so the loud parts are ~1."""
    n = max(1, int(seconds * ENERGY_HZ))
    step = SR // ENERGY_HZ
    m = min(n, len(x) // step)
    if m == 0:
        return [0.0] * n
    e = np.sqrt(np.mean(np.asarray(x[:m * step], np.float64).reshape(m, step) ** 2, axis=1))
    e = np.concatenate([e, np.full(n - m, e[-1])])
    k = ENERGY_HZ // 2
    e = np.convolve(np.pad(e, k, mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="valid")[:n]
    top = float(np.percentile(e, 98)) or 1.0
    return [float(min(1.0, v / top)) for v in e]


def bar_starts(beat: float, phase: float, downbeat_pos: int, seconds: float) -> list[float]:
    if beat <= 0:
        return [0.0]
    bar = 4 * beat
    first = (phase + (downbeat_pos % 4) * beat) % bar
    starts = [float(v) for v in np.arange(first, seconds, bar)]
    if not starts:
        return [0.0]
    if starts[0] < 0.5 * bar:
        starts[0] = 0.0       # a pickup shorter than half a bar belongs to the first bar
    elif starts[0] > 0.05:
        starts = [0.0] + starts
    return starts


def sections(energy: list[float], kick_bars: list[float], starts: list[float], seconds: float,
             drops: list[float], drums_in: float | None) -> list[Section]:
    """Label the song bar by bar, then merge: intro, verse, build, riser, drop, groove, break, outro.

    Bars are levelled low / mid / high by loudness and kick, one-bar blips are
    absorbed into their neighbours (a fill is not a section), and the drops --
    reel.analyse's bass entrances -- each open a drop that lasts while the song
    stays loud, with a two-bar riser before it and a build before that.
    """
    if not energy or len(starts) < 2:
        return [Section(0.0, seconds, "groove", 1.0)]
    E = np.array(energy)
    bars = [(a, starts[k + 1] if k + 1 < len(starts) else seconds) for k, a in enumerate(starts)]
    eng = []
    for a, b in bars:
        i, j = int(a * ENERGY_HZ), max(int(a * ENERGY_HZ) + 1, int(b * ENERGY_HZ))
        # the median: the energy curve is smoothed over a second, so a stop
        # leaks into the edges of the bars either side of it
        eng.append(float(np.median(E[i:j])) if i < E.size else 0.0)
    kick = list(kick_bars) + [0.0] * (len(bars) - len(kick_bars))
    hi = float(np.percentile(eng, 85))
    lo = float(np.percentile(eng, 15))
    level = []
    for e, kb in zip(eng, kick):
        rel = (e - lo) / max(1e-6, hi - lo)
        level.append(2 if rel >= 0.65 and kb >= 0.4 else 0 if rel < 0.3 or kb < 0.15 else 1)
    # a one-bar change of level is a fill or a stop, not a section: it joins the
    # neighbour nearer its own level (the one before, on a tie)
    while True:
        runs = []
        for k, v in enumerate(level):
            if runs and runs[-1][2] == v:
                runs[-1][1] = k + 1
            else:
                runs.append([k, k + 1, v])
        short = [r for r in runs[1:] if r[1] - r[0] == 1] if len(runs) > 1 else []
        if not short:
            break
        a, _, v = short[0]
        i = runs.index(short[0])
        before = runs[i - 1][2]
        after = runs[i + 1][2] if i + 1 < len(runs) else None
        level[a] = before if after is None or abs(before - v) <= abs(after - v) else after
    kinds = ["break" if v == 0 else "verse" if v == 1 else "groove" for v in level]
    for k, (a, b) in enumerate(bars):
        if drums_in and b <= drums_in + 0.05:
            kinds[k] = "intro"
    for d in sorted(drops):
        k0 = next((k for k, (a, b) in enumerate(bars) if a - 0.15 <= d < b - 0.15), None)
        if k0 is None or kinds[k0] == "intro":
            continue      # a bass line entering under the intro is not the drop
        k = k0
        while k < len(bars) and k < k0 + 16 and (k == k0 or level[k] >= 1):
            kinds[k] = "drop"
            k += 1
        for j in (k0 - 1, k0 - 2):
            if j >= 0 and kinds[j] not in ("intro", "drop"):
                kinds[j] = "riser"
        j = k0 - 3
        while j >= 0 and j > k0 - 11 and kinds[j] in ("verse", "break", "groove") and eng[j] <= eng[j + 1] + 0.03:
            kinds[j] = "build"
            j -= 1
    k = len(bars) - 1
    while k > 0 and level[k] == 0 and kinds[k] != "drop":
        kinds[k] = "outro"
        k -= 1
    out: list[Section] = []
    bar = bars[1][1] - bars[1][0]
    for (a, b), kind, e in zip(bars, kinds, eng):
        if out and out[-1].kind == kind:
            n0 = max(1.0, (out[-1].end - out[-1].start) / bar)
            out[-1].energy = round((out[-1].energy * n0 + e) / (n0 + 1), 3)
            out[-1].end = round(b, 4)
        else:
            out.append(Section(round(a, 4), round(b, 4), kind, round(e, 3)))
    return out


# ------------------------------------------------------------------ the whole song

def analyse_signal(x: np.ndarray, *, beat: float, phase: float, downbeat_pos: int = 0,
                   drops: list[float] | None = None, drums_in: float | None = None) -> Rhythm:
    """The rhythm of a mono SR signal, given the grid reel.analyse already found."""
    x = np.asarray(x, np.float32)
    seconds = len(x) / SR
    curves = band_curves(x)
    layers = {k: Layer(k, *peaks(*curves[k])) for k in BANDS}
    if TRANSIENT in curves:
        kick = layers["kick"]
        moved = sorted(zip(on_transient(kick.times, curves[TRANSIENT], BANDS["kick"][2]), kick.strength))
        kick.times, kick.strength = [], []
        for t, s in moved:             # two swells can find the same click
            if kick.times and t - kick.times[-1] < MIN_GAP_S:
                kick.strength[-1] = max(kick.strength[-1], s)
            else:
                kick.times.append(t)
                kick.strength.append(s)
    kp = kick_phase(layers["kick"].times, layers["kick"].strength, beat, phase)
    energy = energy_curve(x, seconds)
    starts = bar_starts(beat, phase, downbeat_pos, seconds)
    # how much kick each bar has, as a share of the bars with the most
    kt = np.array(layers["kick"].times)
    ks = np.array(layers["kick"].strength)
    kick_bars = []
    for k, a in enumerate(starts):
        b = starts[k + 1] if k + 1 < len(starts) else seconds
        kick_bars.append(float(ks[(kt >= a) & (kt < b)].sum()) if kt.size else 0.0)
    top = float(np.percentile(kick_bars, 90)) if kick_bars else 1.0
    kick_bars = [min(1.0, v / (top or 1.0)) for v in kick_bars]
    secs = sections(energy, kick_bars, starts, seconds, drops or [], drums_in)
    return Rhythm(seconds=seconds, beat=beat, phase=phase, kick_phase=kp, downbeat_pos=downbeat_pos,
                  layers=layers, cues=cluster(layers), energy=energy, sections=secs)


def for_song(shape, cache_dir: Path | None = None) -> Rhythm:
    """The rhythm of the song a reel.Shape was read from, cached when a directory is given."""
    path = Path(shape.path)
    key = None
    if cache_dir is not None:
        st = path.stat()
        key = hashlib.sha1(f"{SCHEMA}|{path.resolve()}|{st.st_size}|{int(st.st_mtime)}|"
                           f"{shape.seconds:.2f}|{shape.beat:.6f}|{shape.phase:.4f}".encode()).hexdigest()[:16]
        f = Path(cache_dir) / f"rhythm-{key}.json"
        if f.is_file():
            try:
                return Rhythm.from_dict(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError):
                pass
    from . import beatsync as bs
    x = bs.load_mono(path)
    if shape.seconds and shape.seconds * SR < len(x):
        x = x[:int(shape.seconds * SR)]
    r = analyse_signal(x, beat=shape.beat, phase=shape.phase, downbeat_pos=shape.downbeat_pos,
                       drops=list(shape.drops or ([shape.drop] if shape.drop else [])),
                       drums_in=shape.drums_in)
    log.info("rhythm: %s kick every %.3fs, snare %.3fs, hats %.3fs; kick %+.2f beat off the grid; %s",
             path.name, r.layers["kick"].median_gap(), r.layers["snare"].median_gap(),
             r.layers["hats"].median_gap(), r.kick_offset,
             ", ".join(f"{s.kind}@{s.start:.1f}" for s in r.sections))
    if cache_dir is not None and key:
        try:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            (Path(cache_dir) / f"rhythm-{key}.json").write_text(json.dumps(r.as_dict()), encoding="utf-8")
        except OSError as e:
            log.info("rhythm: could not cache (%s)", e)
    return r
