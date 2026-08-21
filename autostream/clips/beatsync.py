r"""Cut clips to a track, landing kills on the beat and the best one on the drop.

WHY THIS IS WRITTEN OUT RATHER THAN PULLED FROM A LIBRARY
    librosa does all of this and does it better, but it drags in scipy, numba
    and a compiler toolchain -- for an app that ships as a 54 MB zip and treats
    numpy itself as an optional extra. What is actually needed here is a beat
    grid and a drop, and both fall out of an onset envelope that numpy can
    compute directly.

HOW THE BEAT GRID IS FOUND
    1. Decode to mono at 22.05 kHz -- ample for rhythm, which lives well below
       the point where sample rate matters.
    2. Short-time FFT, then SPECTRAL FLUX: the sum of positive frame-to-frame
       changes per bin. Rising energy is what an onset is; falling energy is a
       note ending and must not count, which is why the negatives are clipped
       rather than taken as magnitude.
    3. Tempo by autocorrelating that envelope over a plausible BPM range. The
       peak lag is the beat period.
    4. Phase by testing every offset within one period and keeping whichever
       lands the grid on the most onset energy.

    Steps 3 and 4 are separate on purpose: a track can have an obvious tempo
    and still defeat a naive "first big onset is beat one", because intros
    routinely start off-grid.

THE DROP
    The point where the track stops building and arrives -- a large, SUSTAINED
    jump in energy, not a transient. Found by comparing a trailing and leading
    window either side of each candidate and taking the biggest sustained rise,
    which ignores a single loud crash in a way a peak-picker would not.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .tools import ffmpeg_raw

log = logging.getLogger("autostream.clips.beatsync")

SR = 22050
HOP = 512                      # ~23 ms per frame
WIN = 1024

BPM_MIN, BPM_MAX = 70.0, 180.0

# The drop is compared over this much music either side. Long enough that one
# loud bar cannot fake it.
DROP_WINDOW = 6.0
DROP_LEAD_IN = 12.0            # ignore the first seconds; intros are noisy


@dataclass
class Track:
    path: Path
    duration: float
    bpm: float
    beats: list[float] = field(default_factory=list)
    drop: float | None = None
    strength: list[float] = field(default_factory=list)

    def bars(self, per_bar: int = 4) -> list[float]:
        """Downbeats, assuming 4/4. Most clip montages want bar boundaries
        rather than every beat -- a cut every 0.5s is a strobe."""
        return self.beats[::per_bar]

    def nearest(self, t: float) -> float:
        if not self.beats:
            return t
        i = int(np.argmin(np.abs(np.asarray(self.beats) - t)))
        return self.beats[i]


def load_mono(path: Path) -> np.ndarray:
    raw = ffmpeg_raw(["-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                      "-f", "f32le", "-"])
    return np.frombuffer(raw, dtype="<f4").astype(np.float32)


def onset_envelope(x: np.ndarray) -> np.ndarray:
    """Spectral flux per frame: how much energy ROSE since the last frame."""
    n = 1 + max(0, (len(x) - WIN) // HOP)
    if n < 4:
        return np.zeros(0, dtype=np.float32)
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(WIN).astype(np.float32)
    mag = np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)
    # Log compression: without it a loud chorus swamps a quiet verse and the
    # autocorrelation locks onto the loudest section's tempo alone.
    mag = np.log1p(mag * 8.0)
    flux = np.diff(mag, axis=0)
    env = np.maximum(flux, 0.0).sum(axis=1)
    env = np.concatenate([[0.0], env])
    # Subtract a local median so a long crescendo does not read as a continuous
    # onset.
    k = 41
    pad = np.pad(env, k // 2, mode="edge")
    base = np.array([np.median(pad[i:i + k]) for i in range(len(env))],
                    dtype=np.float32)
    return np.maximum(env - base, 0.0)


def estimate_bpm(env: np.ndarray) -> float:
    if env.size < 64:
        return 0.0
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    fps = SR / HOP
    lo = int(fps * 60.0 / BPM_MAX)
    hi = min(len(ac) - 1, int(fps * 60.0 / BPM_MIN))
    if hi <= lo:
        return 0.0
    lag = lo + int(np.argmax(ac[lo:hi]))
    if not lag:
        return 0.0
    # Sub-frame refinement. The autocorrelation peak is quantised to whole
    # frames (23 ms), and a lag error of one frame is over a BPM -- which
    # compounds into a third of a second of drift by the eightieth beat.
    # Fitting a parabola through the peak and its neighbours recovers the
    # fractional lag.
    if 0 < lag < len(ac) - 1:
        y0, y1, y2 = float(ac[lag - 1]), float(ac[lag]), float(ac[lag + 1])
        denom = y0 - 2 * y1 + y2
        if abs(denom) > 1e-9:
            lag += max(-0.5, min(0.5, 0.5 * (y0 - y2) / denom))
    return float(60.0 * fps / lag)


def beat_grid(env: np.ndarray, bpm: float) -> list[float]:
    """A steady grid at `bpm`, phase-aligned to wherever the onsets actually are."""
    if bpm <= 0 or env.size == 0:
        return []
    fps = SR / HOP
    period = 60.0 / bpm * fps
    n = int(env.size / period)
    if n < 2:
        return []
    best_phase, best_score = 0.0, -1.0
    for phase in np.linspace(0.0, period, 24, endpoint=False):
        idx = (phase + period * np.arange(n)).astype(int)
        idx = idx[idx < env.size]
        score = float(env[idx].sum())
        if score > best_score:
            best_phase, best_score = float(phase), score

    # Snap each grid position to the strongest onset near it. A perfectly even
    # grid drifts against real music -- tempo is never exactly constant, and
    # any residual BPM error accumulates every bar. Snapping re-anchors on the
    # actual transient, which is what a listener hears as "on the beat", and
    # bounds the error instead of letting it grow.
    reach = max(1, int(period * 0.25))
    out: list[float] = []
    for i in range(n):
        centre = int(best_phase + period * i)
        lo = max(0, centre - reach)
        hi = min(env.size, centre + reach + 1)
        if hi <= lo:
            continue
        window = env[lo:hi]
        pos = lo + int(np.argmax(window)) if float(window.max()) > 0 else centre
        out.append(pos / fps)
    return out


def find_drop(x: np.ndarray, duration: float) -> float | None:
    """Biggest SUSTAINED rise in loudness -- where the track arrives."""
    win = int(SR * 0.25)
    if len(x) < win * 8:
        return None
    n = len(x) // win
    rms = np.sqrt((x[:n * win].reshape(n, win).astype(np.float64) ** 2).mean(axis=1))
    rms = 20 * np.log10(rms + 1e-9)
    # Scale the comparison to the track. A twenty-second excerpt has no room
    # for a twelve-second lead-in plus two six-second windows, and the fixed
    # values simply returned "no drop" for every short clip -- which is not the
    # same as there being none.
    window = min(DROP_WINDOW, max(1.5, duration * 0.15))
    lead = min(DROP_LEAD_IN, max(2.0, duration * 0.22))
    k = int(window / 0.25)
    start = max(k, int(lead / 0.25))
    if n - k <= start:
        return None
    best_i, best_gain = None, 0.0
    for i in range(start, n - k):
        gain = rms[i:i + k].mean() - rms[i - k:i].mean()
        if gain > best_gain:
            best_i, best_gain = i, gain
    if best_i is None or best_gain < 2.0:      # no real arrival in this track
        return None
    log.info("drop at %.1fs (+%.1f dB sustained)", best_i * 0.25, best_gain)
    return best_i * 0.25


def analyse(path: Path) -> Track:
    path = Path(path)
    x = load_mono(path)
    duration = len(x) / SR
    env = onset_envelope(x)
    bpm = estimate_bpm(env)
    beats = beat_grid(env, bpm)
    drop = find_drop(x, duration)
    fps = SR / HOP
    strength = [float(env[min(int(b * fps), len(env) - 1)]) for b in beats] if beats else []
    log.info("%s: %.0fs, %.1f BPM, %d beats, drop=%s",
             path.name, duration, bpm, len(beats),
             f"{drop:.1f}s" if drop else "none")
    return Track(path=path, duration=duration, bpm=bpm, beats=beats,
                 drop=drop, strength=strength)


def mixed_slots(track: Track, *, beats_per_clip: int = 4,
                fast_from: float | None = None, fast_beats: int = 2,
                limit: int | None = None) -> list[tuple[float, float, bool]]:
    """Bar-length slots, switching to short ones after `fast_from`.

    -> [(start, length, is_fast)]

    Musical structure is the one thing worth taking on trust rather than
    detecting. Loudness, onset density and spectral brightness were all
    measured on this track and none of them marks the section a listener can
    plainly hear, so the boundary is given rather than guessed. An automatic
    guess that disagrees with the person who chose the music is worse than no
    guess at all.
    """
    beats = track.beats
    if len(beats) < 2:
        return []
    out: list[tuple[float, float, bool]] = []
    i = 0
    while i < len(beats) - 1:
        fast = fast_from is not None and beats[i] >= fast_from
        step = fast_beats if fast else beats_per_clip
        j = min(i + step, len(beats) - 1)
        if j <= i:
            break
        out.append((beats[i], beats[j] - beats[i], fast))
        i = j
        if limit and len(out) >= limit:
            break
    return out


def slots(track: Track, count: int, *, beats_per_clip: int = 4,
          start_at: float | None = None) -> list[tuple[float, float]]:
    """-> [(start, length)] on the grid, one per clip.

    Anchored so the LOUDEST clip can be placed on the drop: the caller puts its
    best clip at the returned drop index.
    """
    grid = track.beats[::beats_per_clip]
    if len(grid) < 2:
        return []
    if start_at is not None:
        grid = [b for b in grid if b >= start_at] or grid
    out = []
    for a, b in zip(grid, grid[1:]):
        out.append((a, b - a))
        if len(out) >= count:
            break
    return out


def render(source: Path, plans, kills, track: Track, out: Path, *,
           beats_per_clip: int = 4, encoder: str = "auto",
           vertical: bool = True, lead: float = 0.45,
           fast_from: float | None = None, fast_beats: int = 2) -> Path | None:
    """Cut `plans` onto `track`'s beat grid and mux the music over the result.

    Each piece is exactly one slot long and starts `lead` seconds before its
    kill, so the CUT lands on the beat and the kill reads just after it -- the
    ordering a montage editor uses, because a cut landing after the payoff
    feels late even when it is mathematically on time.

    The clip with the most kills is moved to whichever slot contains the drop.
    """
    from . import cutter, plan as planmod
    from .tools import ffmpeg, media_info, video_codec_args

    if not plans or not track.beats:
        return None
    full = mixed_slots(track, beats_per_clip=beats_per_clip,
                       fast_from=fast_from, fast_beats=fast_beats)
    if len(full) < 2:
        log.warning("track has no usable beat grid")
        return None

    # The fast section is where the multi-kills go: a run of short cuts each
    # landing on a kill is the payoff the section is building to, and spending
    # it on single kills wastes both.
    by_kills = sorted(plans, key=lambda p: (-p.kills, p.start))
    fast_n = sum(1 for _s, _l, f in full if f)
    hot = by_kills[:fast_n]
    rest = sorted((p for p in by_kills[fast_n:]), key=lambda p: p.start)
    hot_sorted = sorted(hot, key=lambda p: p.start)

    ordered: list = []
    hi = ri = 0
    for _s, _l, is_fast in full:
        if is_fast and hi < len(hot_sorted):
            ordered.append(hot_sorted[hi]); hi += 1
        elif ri < len(rest):
            ordered.append(rest[ri]); ri += 1
        elif hi < len(hot_sorted):
            ordered.append(hot_sorted[hi]); hi += 1
        else:
            break
    grid = [(s, l) for (s, l, _f) in full[:len(ordered)]]
    if fast_n:
        log.info("%d fast slot(s) from %.1fs carry the %s",
                 fast_n, fast_from,
                 ", ".join(f"{p.kills}-kill" for p in hot_sorted) or "remainder")

    di = drop_slot(track, grid)
    if di is not None and di < len(ordered):
        best = max(ordered, key=lambda p: p.kills)
        ordered.remove(best)
        ordered.insert(di, best)
        log.info("drop at %.1fs -> slot %d gets the %d-kill clip",
                 track.drop, di, best.kills)

    work = out.parent / "_beat"
    work.mkdir(parents=True, exist_ok=True)
    pieces: list[Path] = []
    flags = [f for (_s, _l, f) in full[:len(ordered)]]
    for i, (p, (slot_start, slot_len)) in enumerate(zip(ordered, grid), 1):
        inside = [k for k in kills if p.start <= float(k["time"]) <= p.end]
        if not inside:
            continue
        # Prefer the busiest kill in the clip, so a fast slot shows the
        # multi-kill rather than whichever kill happened to come first.
        anchor = float(max(inside, key=lambda k: int(k.get("count", 1)))["time"]) \
            if flags[i - 1] else float(inside[0]["time"])
        # On the drop the KILL itself lands on the beat, not the cut: that
        # moment is the one the whole edit is built around. A fast slot gets
        # almost no run-up either -- there is no room for it in a slot barely
        # longer than a second, and the cut IS the effect.
        if di is not None and i - 1 == di:
            pre = 0.0
        elif flags[i - 1]:
            pre = min(0.18, slot_len * 0.15)
        else:
            pre = lead
        start = max(0.0, anchor - pre)
        piece = planmod.ClipPlan(rank=i, start=start, end=start + slot_len,
                                 kills=len(inside), burst_kills=p.burst_kills,
                                 peak_score=0.0, name=f"beat_{i:02d}")
        pieces.append(cutter.master(source, piece, work, encoder=encoder,
                                    keep_all_audio=False))
    if len(pieces) < 2:
        return None

    joined = work / "_joined.mp4"
    # Hard cuts, not crossfades: a crossfade slides the picture off the beat by
    # half its own duration, which is the one thing this whole module exists to
    # avoid.
    from . import montage as mont
    mont.build(pieces, joined, transition="cut", encoder=encoder)

    if vertical:
        v = cutter.vertical(joined, work, mode="fit", encoder=encoder)
        if v:
            joined = v

    # Replace the audio with the track, starting at the first slot so the music
    # and the cuts share a phase.
    total = media_info(joined)["duration"]
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-i", str(joined), "-ss", f"{grid[0][0]:.3f}", "-i", str(track.path),
           "-map", "0:v:0", "-map", "1:a:0", "-t", f"{total:.3f}",
           *video_codec_args(encoder, cq=20),
           "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", "-y", str(out))

    for p in pieces:
        p.unlink(missing_ok=True)
    for leftover in work.glob("*.mp4"):
        leftover.unlink(missing_ok=True)
    try:
        work.rmdir()
    except OSError:
        pass
    log.info("beat-synced reel: %s (%.0fs, %.0f BPM)", out.name, total, track.bpm)
    return out


def drop_slot(track: Track, slots_: list[tuple[float, float]]) -> int | None:
    """Which slot the drop lands in, so the best clip can go there."""
    if track.drop is None or not slots_:
        return None
    for i, (s, d) in enumerate(slots_):
        if s <= track.drop < s + d:
            return i
    return min(range(len(slots_)), key=lambda i: abs(slots_[i][0] - track.drop))
