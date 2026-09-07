r"""Reels: kills cut to a song, on the beat.

WHAT THIS IS FOR, AND WHY IT IS NOT montage.py
    A montage joins finished clips with transitions. A reel is a different
    thing: short shots whose KILL INSTANT lands on a chosen beat, so the edit
    is locked to the music rather than merely accompanied by it. The unit is
    the beat, not the clip.

EVERYTHING HERE WAS MEASURED, over several rounds against real edits a person
watched and corrected. The four findings that shaped it:

  1. THE GRID IS RELIABLE, THE ARRANGEMENT IS NOT. Tempo, phase and which
     position in the bar is the downbeat all come out of the audio: a person
     marking beats by hand agreed with the downbeat this finds 8 times out of
     8 on one track and 14 of 18 on another. WHICH of those beats should carry
     a kill does not come out of the audio at all -- onset density, spectral
     novelty and section boundaries were each tried against a person's own
     choices and none of them explained it. So the grid is computed and the
     arrangement is a TEMPLATE the user picks. See TEMPLATES.

  2. WHEN TO START IS MEASURABLE, and it is the drums. On Beggin' a person
     marked no kills at all for the first 17 seconds; the kick measures 0.1 to
     0.5% of its peak before 14.69s and 40 to 75% after. `drums_in` finds that
     edge, and it is the one structural decision this makes on its own.

  3. THE MATCH RECORD IS LATE. Riot timestamps a kill after the moment it is
     visible -- measured at 0.32s on average over 13 hand-marked kills, and
     drifting 233 ppm because the recording clock and the game clock run at
     different rates. A reel cut on the raw times puts every kill most of a
     beat early. See `Drift`.

  4. NOTHING MAY CHANGE PLAYBACK SPEED. A ramp into the impact is the
     signature of this style and it is the one effect that cannot be used,
     because slowing the run-up moves the kill off the beat it was placed on.
     Every effect in `look_for` leaves timing alone.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import beatsync as bs

log = logging.getLogger("autostream.clips.reel")

# ---------------------------------------------------------------- the song

# Where the kick lives. Everything that decides "have the drums come in" reads
# this band and nothing else.
KICK_HZ = 160.0
# A bar's kick has to reach this share of the track's loudest kick to count as
# the drums playing. Measured on Beggin': before the drums the loudest bar
# reaches 0.005 of the peak, the bar they enter on reaches 0.159, and the bars
# after run 0.4 to 0.75. Anywhere from 0.05 to 0.3 separates those.
DRUMS_SHARE = 0.12
# ...and it has to hold. A single thud in an intro is not the drums arriving,
# so the next few bars must also clear the bar.
DRUMS_HOLD_BARS = 2
# How long after the drums arrive the first kill lands, in beats. Measured: a
# person's first mark sat 6 beats after the kick entered.
DRUMS_LEAD_BEATS = 6


@dataclass
class Shape:
    """What a song is, as far as cutting to it is concerned."""
    path: Path
    seconds: float
    bpm: float
    phase: float                  # where beat zero sits, in seconds
    downbeat_pos: int             # which position in the bar carries the kick
    drop: float | None = None
    drums_in: float | None = None
    beats: list[float] = field(default_factory=list)
    peaks: list[float] = field(default_factory=list)   # for drawing a waveform
    onsets: list[float] = field(default_factory=list)  # for snapping a tap

    @property
    def beat(self) -> float:
        return 60.0 / self.bpm if self.bpm else 0.0

    @property
    def bar(self) -> float:
        return self.beat * 4

    def at(self, index: int) -> float:
        return self.phase + index * self.beat

    def index_of(self, t: float) -> int:
        return int(round((t - self.phase) / self.beat)) if self.beat else 0

    def is_downbeat(self, index: int) -> bool:
        return index % 4 == self.downbeat_pos

    def downbeats(self) -> list[int]:
        return [i for i in range(len(self.beats)) if self.is_downbeat(i)]

    def first_downbeat_after(self, t: float) -> int:
        """The downbeat at or after `t`, with a beat's worth of slack.

        THE SLACK IS NOT COSMETIC. `t` is normally computed as the drums
        arriving plus a whole number of beats, so it lands a hair either side
        of a real downbeat -- measured at 1.6 MILLISECONDS out. Without the
        tolerance that downbeat is skipped and the reel starts a whole bar
        late, which is a second and a half of dead air at the front for a
        rounding error.
        """
        slack = self.beat * 0.1
        for i in self.downbeats():
            if self.at(i) >= t - slack:
                return i
        return self.downbeats()[0] if self.beats else 0

    def as_dict(self) -> dict:
        return {
            "seconds": round(self.seconds, 3), "bpm": round(self.bpm, 2),
            "beat": round(self.beat, 5), "bar": round(self.bar, 4),
            "phase": round(self.phase, 4), "downbeat_pos": self.downbeat_pos,
            "drop": round(self.drop, 3) if self.drop else None,
            "drums_in": round(self.drums_in, 3) if self.drums_in else None,
            "beats": [round(b, 4) for b in self.beats],
            "peaks": self.peaks, "onsets": self.onsets,
        }


def _spectrum(x: np.ndarray, win: int = 1024):
    n = 1 + max(0, (len(x) - win) // bs.HOP)
    if n < 4:
        return None, None, None
    idx = np.arange(win)[None, :] + bs.HOP * np.arange(n)[:, None]
    mag = np.abs(np.fft.rfft(x[idx] * np.hanning(win).astype(np.float32), axis=1))
    return mag, np.fft.rfftfreq(win, 1.0 / bs.SR), np.arange(n) * bs.HOP / bs.SR


def kick_flux(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rising energy below KICK_HZ, per frame. -> (flux, times)"""
    mag, freqs, times = _spectrum(x)
    if mag is None:
        return np.zeros(0), np.zeros(0)
    low = mag[:, freqs < KICK_HZ].sum(axis=1)
    return np.maximum(np.diff(low, prepend=low[0]), 0.0), times


def downbeat_position(x: np.ndarray, beats: list[float]) -> int:
    """Which of the four positions in the bar carries the kick.

    THE KICK DECIDES, not the loudest onset. Measured on two tracks: 236
    against 41, 51 and 65 on one; 224 against 78, 136 and 60 on the other --
    and on the second, all eight of a person's hand-marked beats landed on the
    position this returns.
    """
    if len(beats) < 8:
        return 0
    flux, times = kick_flux(x)
    if not flux.size:
        return 0
    strength = np.array([
        flux[(times >= b - 0.06) & (times <= b + 0.06)].max()
        if ((times >= b - 0.06) & (times <= b + 0.06)).any() else 0.0
        for b in beats])
    return int(np.argmax([strength[i::4].mean() for i in range(4)]))


def drums_in(x: np.ndarray, phase: float, bar: float) -> float | None:
    """When the drums arrive, or None if they are playing from the start.

    THE ONE STRUCTURAL DECISION THIS MAKES BY ITSELF, and the only one the
    audio actually supports -- see the module note. Read per bar rather than
    per frame: a kick is a transient, and asking "was there a kick in this bar"
    is a far steadier question than "is there a kick now".
    """
    flux, times = kick_flux(x)
    if not flux.size or bar <= 0:
        return None
    peak = float(flux.max()) or 1.0
    n = int((times[-1] - phase) / bar)
    if n < DRUMS_HOLD_BARS + 1:
        return None
    per_bar = []
    for i in range(n):
        a = phase + i * bar
        m = (times >= a) & (times < a + bar)
        per_bar.append(float(flux[m].max()) / peak if m.any() else 0.0)
    for i, share in enumerate(per_bar):
        if share <= DRUMS_SHARE:
            continue
        ahead = per_bar[i + 1:i + 1 + DRUMS_HOLD_BARS]
        if ahead and all(s > DRUMS_SHARE for s in ahead):
            # Already playing at the top of the track: there is no arrival to
            # find, and pretending bar 0 is one would hold every kill back.
            return None if i == 0 else phase + i * bar
    return None


def analyse(path: Path, seconds: float = 0.0, points: int = 2000) -> Shape:
    """Read a song and work out everything a reel needs from it."""
    from .tools import media_info

    total = float(media_info(path).get("duration") or 0.0)
    x = bs.load_mono(path)
    if seconds and seconds < total:
        x = x[:int(seconds * bs.SR)]
        total = seconds
    env = bs.onset_envelope(x)
    bpm = bs.estimate_bpm(env)
    beat = 60.0 / bpm if bpm else 0.0
    if not beat:
        raise RuntimeError("Could not find a tempo in that track.")

    # PHASE BY TOTAL ONSET ENERGY, on a rigid grid. Deliberately not
    # beatsync.beat_grid, which snaps every beat to its nearest transient --
    # right for following a performance, wrong here: adjacent snaps in opposite
    # directions leave gaps of 0.28s and 0.58s on a 0.45s beat, and a cut
    # rhythm built on that reads as sloppy rather than as human.
    fps = bs.SR / bs.HOP
    per = beat * fps
    count = max(2, int(env.size / per))
    best = max(
        (float(env[np.clip((ph + per * np.arange(count)).astype(int),
                           0, max(0, env.size - 1))].sum()), ph)
        for ph in np.linspace(0.0, per, 96, endpoint=False))
    phase = best[1] / fps
    beats = [phase + i * beat for i in range(int((total - phase) / beat))]

    step = max(1, len(x) // points)
    raw = [float(np.abs(x[i:i + step]).max()) for i in range(0, len(x), step)]
    top = max(raw) or 1.0

    e = np.asarray(env, dtype=float)
    thr = e.mean() + 0.6 * e.std()
    hop_s = 1.0 / fps
    onsets = [round(i * hop_s, 4) for i in range(1, len(e) - 1)
              if e[i] > thr and e[i] >= e[i - 1] and e[i] > e[i + 1]]

    shape = Shape(
        path=path, seconds=total, bpm=bpm, phase=phase,
        downbeat_pos=downbeat_position(x, beats),
        drop=bs.find_drop(x, total),
        drums_in=drums_in(x, phase, beat * 4),
        beats=beats,
        peaks=[round(v / top, 3) for v in raw[:points]],
        onsets=onsets,
    )
    log.info("reel: %s is %.2f BPM, downbeat at position %d, drums in at %s, "
             "drop at %s", path.name, shape.bpm, shape.downbeat_pos,
             f"{shape.drums_in:.2f}s" if shape.drums_in else "the start",
             f"{shape.drop:.2f}s" if shape.drop else "no drop found")
    return shape


# ------------------------------------------------------------- the templates

@dataclass
class Template:
    """A rhythm for the kills, expressed in beats rather than seconds.

    WHY THESE ARE FIXED PATTERNS AND NOT DETECTED. Three separate attempts to
    find a person's own arrangement in the audio failed: onset density said
    their fast run was BELOW average (0.96x the median), the nearest section
    boundary was 3.76s away from where it started, and a 6.25-second hole they
    left had the HIGHEST loudness in the whole reel. The rhythm is taste. What
    the audio does support is the grid it is laid on, and when to start.
    """
    key: str
    label: str
    blurb: str
    every: int = 4              # beats between hits in the steady stretch
    on_downbeat: bool = True    # anchor the steady stretch to the downbeat
    # A flourish: after `flourish_after` steady hits, add `flourish` extra hits
    # one beat after their own downbeat, for `flourish_bars` bars.
    flourish_bars: int = 0
    run_in: int = 0             # consecutive beats leading into the drop


TEMPLATES: dict[str, Template] = {
    "bar": Template(
        key="bar", label="One a bar",
        blurb="A kill on every downbeat. The steadiest, and what a person "
              "reached for unprompted 14 times out of 18.",
        every=4),
    "half": Template(
        key="half", label="Twice a bar",
        blurb="Twice as busy. Wants a lot of kills -- it spends one every "
              "two beats.",
        every=2),
    "pairs": Template(
        key="pairs", label="One a bar, with doubles",
        blurb="A kill on the downbeat, and for three bars a second kill "
              "immediately after it. The flourish a person added by hand.",
        every=4, flourish_bars=3),
    "runin": Template(
        key="runin", label="Run into the drop",
        blurb="Five kills on consecutive beats arriving at the drop, then one "
              "a bar. Loud, and it needs a drop to aim at.",
        every=4, run_in=5),
}
DEFAULT_TEMPLATE = "bar"


def layout(shape: Shape, want: int, template: Template | str = DEFAULT_TEMPLATE,
           start: float | None = None, until: float | None = None) -> list[float]:
    """Where the kills go. -> times in the song, ascending.

    `start` defaults to the drums arriving, because that is the one structural
    edge the audio gives up -- see drums_in. `want` caps the result: there is
    no point laying out more slots than there are kills to put in them.
    """
    tpl = TEMPLATES.get(template, TEMPLATES[DEFAULT_TEMPLATE]) \
        if isinstance(template, str) else template
    if not shape.beats or want <= 0:
        return []
    end = min(until or shape.seconds, shape.seconds)
    if start is None:
        start = (shape.drums_in + DRUMS_LEAD_BEATS * shape.beat
                 if shape.drums_in else shape.at(0))

    slots: list[int] = []
    # The run-in, if the template wants one and there is a drop to aim at.
    if tpl.run_in and shape.drop:
        d = shape.index_of(shape.drop)
        slots += [d - tpl.run_in + k for k in range(tpl.run_in)]

    first = (shape.first_downbeat_after(start) if tpl.on_downbeat
             else shape.index_of(start))
    i, hits = first, 0
    while i < len(shape.beats) and shape.at(i) <= end and len(slots) < want:
        slots.append(i)
        hits += 1
        # The flourish: a second hit one beat later, for the first few bars.
        if tpl.flourish_bars and hits <= tpl.flourish_bars and len(slots) < want:
            if i + 1 < len(shape.beats):
                slots.append(i + 1)
        i += tpl.every
    seen: dict[int, None] = {}
    for s in slots:
        if 0 <= s < len(shape.beats):
            seen.setdefault(s, None)
    return [shape.at(i) for i in sorted(seen)][:want]


# ------------------------------------------------------------------- drift

@dataclass
class Drift:
    """How late the match record is, fitted from kills marked by eye.

    THE RECORD IS NOT WHEN THE KILL IS VISIBLE. Measured over 13 marked kills:
    every error negative, mean -0.323s, and shrinking through the match --
    a constant lag plus 233 ppm of clock drift between the recording and the
    game. At 134 BPM a third of a second is three quarters of a beat, so a reel
    cut on the raw times misses every one.
    """
    intercept: float = 0.0
    slope: float = 0.0

    @classmethod
    def fit(cls, pairs: list[tuple[float, float]]) -> "Drift":
        """`pairs` are (time the record gave, seconds the truth was off by)."""
        if len(pairs) < 2:
            return cls()
        t = np.array([p[0] for p in pairs], dtype=float)
        e = np.array([p[1] for p in pairs], dtype=float)
        slope, intercept = np.polyfit(t, e, 1)
        return cls(intercept=float(intercept), slope=float(slope))

    def apply(self, t: float) -> float:
        return t + (self.intercept + self.slope * t)


# -------------------------------------------------------------------- shots

MIN_AFTER = 0.22          # a kill stays on screen at least this long
PRE_SHARE = 0.30          # of the gap it has to live in
PRE_MIN, PRE_MAX = 0.14, 0.90


def pre_roll(in_gap: float) -> float:
    """How long before its kill a shot cuts in.

    FROM THE GAP BEFORE THE BEAT, NOT THE ONE AFTER IT. Sizing it from the
    following gap is wrong and visibly so: a three-second shot wanted 0.9s of
    run-up, which reached back past the beat of the shot before it and left
    that shot 0.10s long with its own kill outside it entirely.
    """
    return float(np.clip(min(PRE_SHARE * in_gap, in_gap - MIN_AFTER),
                         PRE_MIN, PRE_MAX))


@dataclass
class Shot:
    index: int
    reel_in: float
    duration: float
    source_in: float
    kill_at: float            # on the reel's clock
    kill_source: float
    round_no: int | None = None
    labels: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"index": self.index, "reel_in": round(self.reel_in, 4),
                "duration": round(self.duration, 4),
                "source_in": round(self.source_in, 4),
                "kill_at": round(self.kill_at, 4),
                "kill_source": round(self.kill_source, 4),
                "round": self.round_no, "labels": list(self.labels)}


def shots(slots: list[float], kills: list[dict], total: float,
          drift: Drift | None = None,
          opening: bool = True) -> list[Shot]:
    """Turn slots and kills into shots. -> in reel order.

    `opening` gives the first shot everything before its own beat, so a
    template that starts late produces a run-up rather than a hard start on a
    kill. The last shot runs to `total`, which is what makes the fade the
    footage continuing rather than a separate clip.
    """
    drift = drift or Drift()
    n = min(len(slots), len(kills))
    if not n:
        return []
    times = list(slots[:n])
    pres = [times[0] if opening else pre_roll(times[0])]
    pres += [pre_roll(times[i] - times[i - 1]) for i in range(1, n)]
    starts = [t - p for t, p in zip(times, pres)] + [total]

    out: list[Shot] = []
    for i in range(n):
        k = kills[i]
        src = drift.apply(float(k.get("time", 0.0)))
        shot = Shot(index=i, reel_in=starts[i],
                    duration=max(0.05, starts[i + 1] - starts[i]),
                    source_in=max(0.0, src - pres[i]),
                    kill_at=times[i], kill_source=src,
                    round_no=k.get("round"),
                    labels=list(k.get("labels") or []))
        # A kill outside its own shot is the failure this arithmetic exists to
        # prevent, and it happened once. Refuse rather than render it.
        if not (shot.reel_in - 1e-6 <= shot.kill_at
                <= shot.reel_in + shot.duration + 1e-6):
            raise RuntimeError(
                f"shot {i} runs {shot.reel_in:.2f}-"
                f"{shot.reel_in + shot.duration:.2f}s but its kill is at "
                f"{shot.kill_at:.2f}s")
        out.append(shot)
    return out


# --------------------------------------------------------------------- look

# The grade, per shot. Held gentle on purpose: the footage is already colourful
# and the swing in a real edit is far weaker than a still suggests.
# (saturation, contrast, brightness, red shift, blue shift)
FLAT = (0.80, 0.98, -0.020, -0.030, 0.040)
COOL = (0.92, 1.04, -0.010, -0.045, 0.055)
WARM = (1.14, 1.09, 0.008, 0.060, -0.050)
HOT = (1.22, 1.14, 0.020, 0.080, -0.055)

PUNCH = 0.10              # how far the push-in on a kill goes
PUNCH_FALL = 0.35         # and how long it takes to settle
SHORT_SHOT = 1.0          # a shot this brief is part of a flourish
FLASH = 0.11              # brightness lift at the top of a flourish shot

GAME_GAIN_DB = 10.0
DUCK = dict(threshold=0.16, ratio=5, attack=4, release=220)


def look_for(index: int, shot: Shot, hero: int) -> tuple:
    """The grade for one shot: the build-up held back, flourishes hot."""
    if index == 0:
        return FLAT
    if shot.duration <= SHORT_SHOT or index == hero:
        return HOT
    return WARM if index % 2 else COOL


def video_chain(index: int, shot: Shot, hero: int, width: int, height: int,
                fps: int, fade: float = 0.0, total: float = 0.0) -> str:
    """One shot's filter chain.

    THE PUSH-IN RUNS THROUGH zoompan, NOT crop. crop evaluates its width and
    height ONCE when the pad is configured, where `t` does not exist yet -- only
    x and y are re-evaluated per frame, so crop can pan but cannot zoom over
    time. d=1 with a matching fps keeps it one frame in, one frame out, so
    nothing about the timing moves.
    """
    at = shot.kill_at - shot.reel_in
    sat, con, bri, rs, bsh = look_for(index, shot, hero)
    z = (f"1+{PUNCH}*gte(in_time,{at:.3f})"
         f"*max(0,1-(in_time-{at:.3f})/{PUNCH_FALL})")
    chain = (f"[{index}:v]scale={width}:{height}:flags=lanczos,setsar=1,"
             f"fps={fps},"
             f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
             f":d=1:s={width}x{height}:fps={fps},"
             f"eq=saturation={sat}:contrast={con}:brightness={bri}")
    if index and shot.duration <= SHORT_SHOT:
        chain = chain.replace(f"brightness={bri}",
                              f"brightness='{bri}+{FLASH}*lt(t,0.07)':eval=frame")
    chain += (f",colorbalance=rs={rs}:bs={bsh},unsharp=3:3:0.55:3:3:0.0,"
              f"vignette=PI/5")
    if fade > 0:
        # ON THE LAST SHOT ITSELF, because that shot IS the outro: the reel
        # walks away from its own final moment rather than cutting to something
        # unrelated.
        start = max(0.0, shot.duration - fade)
        chain += f",fade=t=out:st={start:.2f}:d={fade:.2f}:color=black"
    return chain + f"[v{index}]"


def audio_graph(n: int, main: float, total: float, fade: float) -> str:
    """Game audio under the music, with the music ducked by the gunfire.

    NOT AT FIXED LEVELS. Every shot ducks the track and it releases straight
    after, so a gunshot is audible without turning the music down for the whole
    reel. Two numbers here are measured rather than chosen: the duck threshold
    has to sit ABOVE the game's ambience (at -27 dB it sat under it, and
    footsteps held the duck open for the entire reel, leaving the music 8.7 dB
    quieter than it should be), and amix needs normalize=0 or it halves every
    input regardless of what the ducking does.
    """
    g = (f"[graw]volume={GAME_GAIN_DB}dB,"
         f"afade=t=out:st={main:.3f}:d={fade:.3f},"
         f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
         f"asplit=2[gmix][gkey];")
    g += (f"[{n}:a]atrim=0:{total:.3f},asetpts=N/SR/TB,"
          f"afade=t=out:st={main:.3f}:d={fade:.3f},"
          f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
          f"[music];")
    g += (f"[music][gkey]sidechaincompress=threshold={DUCK['threshold']}"
          f":ratio={DUCK['ratio']}:attack={DUCK['attack']}"
          f":release={DUCK['release']}:level_sc=1[ducked];")
    g += ("[ducked][gmix]amix=inputs=2:duration=longest:normalize=0:"
          "weights=1 0.85,alimiter=limit=0.95,aresample=48000[a]")
    return g


def command(source: Path, song: Path, shots_: list[Shot], out: Path, *,
            main: float, fade: float, width: int = 1920, height: int = 1080,
            fps: int = 60, crf: int = 18, preset: str = "medium") -> list[str]:
    """The whole render as one ffmpeg invocation. -> argv"""
    from .tools import binary

    total = main + fade
    hero = max(range(len(shots_)), key=lambda i: len(shots_[i].labels)) \
        if shots_ else 0
    parts = []
    for i, s in enumerate(shots_):
        last = (i == len(shots_) - 1)
        parts.append(video_chain(i, s, hero, width, height, fps,
                                 fade=fade if last else 0.0, total=total))
        parts.append(f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=48000:"
                     f"channel_layouts=stereo[a{i}]")
    n = len(shots_)
    graph = ";".join(parts) + ";"
    graph += "".join(f"[v{i}][a{i}]" for i in range(n))
    graph += f"concat=n={n}:v=1:a=1[v][graw];"
    graph += audio_graph(n, main, total, fade)

    args = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error",
            "-nostdin", "-y"]
    for s in shots_:
        args += ["-ss", f"{s.source_in:.3f}", "-t", f"{s.duration:.3f}",
                 "-i", str(source)]
    args += ["-i", str(song), "-filter_complex", graph,
             "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
             "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
             "-movflags", "+faststart", str(out)]
    return args


# ------------------------------------------------------- effects, evidenced

# WHAT THE REFERENCE MONTAGE ACTUALLY DOES, measured off a 95-second Valorant
# edit rather than guessed at. Three findings, and one of them is a negative:
#
#   THE FLASH IS REAL. Two frames at a cut, measured at mean brightness 177 and
#     186 against about 118 either side. It coincides with a fast camera flick,
#     so it reads as the cut being hit rather than as a fault.
#
#   THERE IS NO CHROMATIC ABERRATION. Correlating the red and blue channels
#     against green on four impact frames gave a misalignment of 0px every
#     time. An RGB split is the effect everyone assumes is in these edits; this
#     one does not have it, and adding it would be inventing a signature the
#     reference does not carry.
#
#   THE GRADE IS NOT THE DIFFERENCE. Measured against a reel built here: the
#     reference's mean saturation is 0.314 and this builder's is 0.374 -- ours
#     is already the more saturated. What differs is hue SPREAD, 0.623 against
#     0.114. The reference visits many colour worlds because it draws on many
#     matches across many maps; a reel cut from one match on one map cannot,
#     and pushing the grade to fake it would look like a filter rather than
#     like footage. The fix is more sources, not more saturation -- see
#     `sources_note`.
FLASH_AT_CUTS = True
FLASH_FRAMES = 2

NOWPLAYING_SECONDS = 6.0     # how long the card stays up
NOWPLAYING_FROM = 1.0        # and when it appears


def song_tags(path: Path) -> dict:
    """Title and artist from the file's own tags. Never raises."""
    import json
    import subprocess

    from .killfeed import _NO_WINDOW
    from .tools import binary

    try:
        r = subprocess.run(
            [binary("ffprobe"), "-v", "error", "-show_entries",
             "format_tags=title,artist", "-of", "json", str(path)],
            capture_output=True, text=True, creationflags=_NO_WINDOW)
        tags = (json.loads(r.stdout or "{}").get("format") or {}).get("tags") or {}
    except Exception:                                # noqa: BLE001
        tags = {}
    low = {str(k).lower(): str(v) for k, v in tags.items()}
    title = low.get("title") or path.stem
    artist = low.get("artist") or ""
    return {"title": title, "artist": artist}


def _esc(text: str) -> str:
    """drawtext eats colons, backslashes, quotes and percent signs."""
    out = str(text).replace("\\", r"\\\\")
    for ch in (":", "'", "%", ",", "[", "]", ";"):
        out = out.replace(ch, "\\" + ch)
    return out


def nowplaying_chain(song: Path, width: int, height: int) -> str:
    """A "now playing" line, the way the reference labels its own track.

    Text rather than the reference's album-art card: the art is not in a FLAC
    reliably and a missing image is worse than no card at all. Positioned and
    sized from the frame so it holds at any resolution.
    """
    t = song_tags(song)
    line = f"{t['artist']} - {t['title']}" if t["artist"] else t["title"]
    size = max(16, int(height * 0.026))
    pad = int(height * 0.030)
    a, b = NOWPLAYING_FROM, NOWPLAYING_FROM + NOWPLAYING_SECONDS
    # Fades in and out with the same expression that draws it, so it needs no
    # second filter and cannot drift out of step with itself.
    alpha = (f"if(lt(t,{a}),0,"
             f"if(lt(t,{a + 0.4:.2f}),(t-{a})/0.4,"
             f"if(lt(t,{b - 0.6:.2f}),1,"
             f"if(lt(t,{b}),({b}-t)/0.6,0))))")
    return (f"drawtext=text='{_esc(line)}':fontcolor=white:fontsize={size}"
            f":x={pad}:y=h-{pad}-{size}:box=1:boxcolor=black@0.45:boxborderw=10"
            f":alpha='{alpha}'")


def sources_note(shots_: list[Shot]) -> str:
    """What to say about a reel drawn from a single match.

    Measured rather than asserted: hue spread 0.114 here against 0.623 in a
    reference montage that draws on many maps. Worth telling the user, because
    the remedy is choosing kills from more sessions and no amount of grading
    substitutes for it.
    """
    rounds = {s.round_no for s in shots_ if s.round_no is not None}
    if len(rounds) <= 1:
        return ""
    return ("Every shot here comes from one match, so the reel will look more "
            "uniform than a montage cut from several. Adding kills from other "
            "sessions is what widens it -- grading cannot.")
