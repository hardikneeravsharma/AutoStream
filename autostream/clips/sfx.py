"""The highlight's sounds, synthesised: a transition whoosh, a kill hit, an outro bed.

Made here from numpy rather than shipped as files, for one reason: a highlight
is made to be posted, and a sound effect or a music bed lifted from anywhere
else is a copyright claim waiting to happen. These are nobody's but ours.
Deterministic (fixed seeds), so the same highlight sounds the same on every PC,
and cached as .wav the first time they are asked for.

The shapes are the ones gaming editors use:
  whoosh  band-limited noise swept up and back down, peaking 60% in, panned
          left to right -- 0.6 s, placed so the peak lands on the cut
  hit     a low thump that drops in pitch, a click, and a short bright ting --
          0.45 s, on every kill
  outro   warm pad chords (F - G - Am - C at 88 bpm), a soft plucked arpeggio
          and a gentle kick, 20 s -- faded in under the last fight so the
          match ends on music rather than stopping dead
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 48000
# Where the whoosh is loudest, as a fraction of its length: the cut goes here.
WHOOSH_PEAK = 0.36


def _save(path: Path, x: np.ndarray) -> Path:
    x = x / (np.abs(x).max() + 1e-9) * 0.89
    if x.ndim == 1:
        x = np.stack([x, x], 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.wav")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    tmp.replace(path)
    return path


def _lowpass(x: np.ndarray, fc: np.ndarray) -> np.ndarray:
    """One-pole low-pass with a cutoff that moves sample by sample."""
    y = np.empty_like(x)
    a = 1 - np.exp(-2 * np.pi * fc / SR)
    s = 0.0
    for i in range(len(x)):
        s += a[i] * (x[i] - s)
        y[i] = s
    return y


def whoosh() -> np.ndarray:
    n = int(0.6 * SR)
    p = np.arange(n) / (n - 1)
    noise = np.random.default_rng(7).standard_normal(n)
    fc = 400 + 5200 * np.sin(np.pi * np.clip(p / 0.75, 0, 1)) ** 2
    band = _lowpass(noise, fc) - _lowpass(noise, fc * 0.25)
    env = np.where(p < 0.6, (p / 0.6) ** 2, np.exp(-(p - 0.6) * 14))
    w = band * env
    return np.stack([w * np.cos(p * np.pi / 2), w * np.sin(p * np.pi / 2)], 1)


def hit() -> np.ndarray:
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 45 + 115 * np.exp(-t * 30)
    thump = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11)
    click = np.random.default_rng(7).standard_normal(n) * np.exp(-t * 400) * 0.6
    ting = (np.sin(2 * np.pi * 1760 * t) + 0.6 * np.sin(2 * np.pi * 2637 * t)) \
        * np.exp(-t * 14) * 0.28
    return thump + click + ting


def outro(seconds: float = 20.0) -> np.ndarray:
    bpm = 88
    beat = 60 / bpm
    bar = 4 * beat
    n = int(seconds * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(3)

    def hz(m):
        return 440.0 * 2 ** ((m - 69) / 12)

    chords = [[53, 60, 65, 69, 72], [55, 62, 67, 71, 74],
              [57, 64, 69, 72, 76], [48, 55, 64, 67, 72]]
    L = np.zeros(n)
    R = np.zeros(n)
    for i in range(int(seconds / bar) + 1):
        s, e = i * bar, (i + 1) * bar + 1.2
        a, b = int(s * SR), min(n, int(e * SR))
        if a >= n:
            break
        tt = t[a:b] - s
        env = np.minimum(1, tt / 0.9) * np.clip((e - s - tt) / 1.2, 0, 1)
        for m in chords[i % 4]:
            for det, pan in ((-0.07, 0.2), (0.0, 0.5), (0.07, 0.8)):
                f = hz(m + det)
                v = (np.sin(2 * np.pi * f * tt) + 0.25 * np.sin(4 * np.pi * f * tt)) * env * 0.05
                L[a:b] += v * (1 - pan)
                R[a:b] += v * pan
    k = 0
    while k * beat / 2 < seconds - 0.5:
        s = k * beat / 2
        m = chords[int(s // bar) % 4][1:][k % 4] + 12
        a = int(s * SR)
        b = min(n, a + int(0.9 * SR))
        tt = t[a:b] - s
        v = np.sin(2 * np.pi * hz(m) * tt) * np.exp(-tt * 5) * 0.09
        pan = 0.3 if k % 2 else 0.7
        L[a:b] += v * (1 - pan)
        R[a:b] += v * pan
        k += 1
    k = 0
    while k * beat < seconds:
        a = int(k * beat * SR)
        b = min(n, a + int(0.35 * SR))
        tt = t[a:b] - k * beat
        kick = np.sin(2 * np.pi * np.cumsum(50 + 70 * np.exp(-tt * 35)) / SR) \
            * np.exp(-tt * 9) * 0.35
        L[a:b] += kick
        R[a:b] += kick
        a2 = int((k + 0.5) * beat * SR)
        b2 = min(n, a2 + int(0.06 * SR))
        if a2 < n:
            sh = rng.standard_normal(b2 - a2) * np.exp(-np.arange(b2 - a2) / SR * 60) * 0.04
            L[a2:b2] += sh
            R[a2:b2] += sh
        k += 1
    for d, g in ((0.113, 0.35), (0.271, 0.22)):
        o = int(d * SR)
        L[o:] += R[:-o] * g
        R[o:] += L[:-o] * g
    return np.stack([L, R], 1)


def files(folder: Path) -> dict[str, Path]:
    """The three sounds as .wav files in `folder`, made on first use."""
    out = {}
    for name, make in (("whoosh", whoosh), ("hit", hit), ("outro", outro)):
        p = Path(folder) / f"{name}.wav"
        if not p.is_file():
            _save(p, make())
        out[name] = p
    return out
