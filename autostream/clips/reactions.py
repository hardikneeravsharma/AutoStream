r"""The player's own reactions, read off the microphone track (H2).

WHY THIS EXISTS
    Every other reader here finds kills: the kill feed, the scoreboard, Riot's
    match record, the game's loudness. But the moments people keep from a
    session are just as often the ones where the player lost it -- a laugh, a
    shout at a missed clutch, a scream at a flick -- and a kill-only clipper
    walks straight past them. The hand-cut "missed 1v4 clutch RAGE" meme of
    2026-10-25 was a lost round with no kill worth clipping.

    A person's reaction is also the strongest single sign of excitement the
    highlight-detection literature found (streams, golf, League casters), and
    OBS already hands us that person on a track of their own.

WHY THE MIC TRACK, AND WHY NOT THE ROLLING BASELINE
    AutoStream records three audio tracks: 1 the mix, 2 the microphone alone,
    3 the game alone (obs.split_audio_tracks). The mic alone is the player
    without the gunfire. But it is noise-gated -- silent 65-70 % of the time --
    so loudness.py's rolling median sits at the gate's floor and every word
    reads as a peak (206 of them in 40 minutes). A reaction is loud for THIS
    PERSON SPEAKING, so the line is drawn from their own voice: the median
    level of the frames that are voiced at all.

WHAT IS MEASURED (2026-11-01, on the Bind recording of 2026-10-25)
    The mic's RMS level at HZ, smoothed over SMOOTH seconds. A reaction is a run
    at least RISE_DB over the speaking level for at least MIN_SECONDS; runs
    closer than MERGE_GAP are one reaction. Its score is the dB-seconds above
    the line -- a long shout outranks a short one at the same pitch. On that
    recording: 96 reactions in 40 minutes, and the hand-cut rage moment
    (691.8-728.6 s) is the second strongest, a 5.4 s run 20.8 dB over the
    player's voice at 712 s. Two tracks of 40 minutes read in 3 s.

    What it cannot say is WHAT the sound was -- a laugh and a shout are both
    loud. That is a classifier's job (see `kind`), and without one a reaction
    is named for what is known: that the player reacted.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .tools import binary

log = logging.getLogger("autostream.clips.reactions")

HZ = 20.0
RATE = 8000
MIC_TRACK = 1                 # the second audio stream: tracks are 0 mix, 1 mic, 2 game
VOICED_DB = -60.0             # a frame above this is someone speaking (the gate is far below)
SMOOTH = 0.3                  # seconds
RISE_DB = 10.0                # over the player's own speaking level
MIN_SECONDS = 0.4
MERGE_GAP = 3.0
MIN_VOICED = 30.0             # seconds of speech before the speaking level means anything


@dataclass
class Reaction:
    at: float                 # the loudest instant, seconds into the file
    start: float              # where the run over the line began
    end: float
    score: float              # dB-seconds over the line
    peak_db: float            # how far over the speaking level it reached
    kind: str = ""            # "laugh" / "hype" / "rage", when a classifier said so

    def as_dict(self) -> dict:
        return {"at": round(float(self.at), 2), "start": round(float(self.start), 2),
                "end": round(float(self.end), 2), "score": round(float(self.score), 2),
                "peak_db": round(float(self.peak_db), 1), "kind": self.kind}


def tracks(video: str | Path) -> int:
    """How many audio streams the file has. 0 when it cannot be read."""
    try:
        p = subprocess.run([binary("ffprobe"), "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=index", "-of", "csv=p=0", str(video)],
                           capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return len([x for x in (p.stdout or "").split() if x.strip()])
    except Exception:  # noqa: BLE001 - a file that cannot be probed has no mic track to read
        return 0


def level(video: str | Path, track: int = MIC_TRACK, start: float = 0.0,
          duration: float | None = None, hz: float = HZ) -> np.ndarray:
    """RMS level in dBFS of one audio stream, one value every 1/hz seconds."""
    args = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start > 0:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(video)]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    args += ["-map", f"0:a:{int(track)}", "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"]
    p = subprocess.run(args, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    a = np.frombuffer(p.stdout or b"", dtype=np.int16)
    step = max(1, int(RATE / hz))
    n = a.size // step
    if n < 2:
        return np.empty(0, dtype=np.float32)
    frames = a[:n * step].astype(np.float32).reshape(n, step) / 32768.0
    rms = np.sqrt(np.mean(np.square(frames), axis=1))
    return (20.0 * np.log10(np.maximum(rms, 1e-6))).astype(np.float32)


def speaking_level(lv: np.ndarray, hz: float = HZ) -> float | None:
    """The median of the voiced frames: how loud this player is when they talk.
    None with too little speech to say (a muted mic, a silent session)."""
    voiced = lv[lv > VOICED_DB]
    if voiced.size < MIN_VOICED * hz:
        return None
    return float(np.median(voiced))


def find(lv: np.ndarray, hz: float = HZ, *, rise_db: float = RISE_DB,
         min_seconds: float = MIN_SECONDS, merge_gap: float = MERGE_GAP,
         offset: float = 0.0) -> list[Reaction]:
    """Every reaction in a level track, strongest first. `offset` is added to every time."""
    speech = speaking_level(lv, hz)
    if speech is None:
        return []
    k = max(1, int(round(SMOOTH * hz)))
    sm = np.convolve(lv, np.ones(k) / k, mode="same")
    line = speech + rise_db
    hot = sm >= line
    edges = np.diff(np.r_[0, hot.astype(np.int8), 0])
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    runs = [(a, b) for a, b in zip(starts, ends) if (b - a) / hz >= min_seconds]
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and (a - merged[-1][1]) / hz < merge_gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    out = []
    for a, b in merged:
        over = sm[a:b] - line
        top = int(np.argmax(sm[a:b]))
        out.append(Reaction(at=offset + (a + top) / hz, start=offset + a / hz, end=offset + b / hz,
                            score=float(np.sum(np.clip(over, 0, None)) / hz),
                            peak_db=float(sm[a + top] - speech)))
    out.sort(key=lambda r: -r.score)
    return out


def scan(video: str | Path, *, start: float = 0.0, duration: float | None = None,
         track: int = MIC_TRACK) -> list[Reaction]:
    """The reactions in a recording, strongest first. [] when it has no mic track."""
    if tracks(video) <= track:
        log.info("%s has no microphone track to read reactions from", Path(video).name)
        return []
    lv = level(video, track, start, duration)
    got = find(lv, offset=start)
    log.info("%s: %d reaction(s) on the microphone track", Path(video).name, len(got))
    return got
