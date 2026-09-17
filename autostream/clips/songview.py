r"""Ways of seeing a song, for the page that marks kills on it.

WHY THIS EXISTS
    The Song tab drew one waveform. A waveform shows loudness and nothing
    else -- you cannot see a kick in it, or a hi-hat pattern, or where a
    chorus lifts. Marking kills by eye needs the bands separated and the
    spectrogram shown, which is what the Kill Marks lab (scripts/kill_marks/)
    was built to prove, and this is that view moved into the app.

WHAT IT PRODUCES
    Five lanes and a spectrogram, all at 100 frames a second and scaled to
    bytes, so the page can draw any stretch of the song straight from the
    array without doing signal processing per frame:

        rms        loudness
        low        30-150 Hz: the kick and the bass
        mid        150-2500 Hz: snare body, vocals, most instruments
        high       5-16 kHz: hi-hats, cymbals, the crack of a snare
        flux       onset strength -- how much new energy arrives
        spec       80 log-spaced bands from 30 Hz to 16 kHz

    A four-minute song is about 1.3 MB of that, computed in a second and
    cached in the clips folder (<clips>\.studio\songview) against the song
    file's own mtime, so opening it again is instant.

    The kills clips/hits.py finds are handed over with it, so the page can
    show what the detector would cut to beside what the player marks by hand.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path

import numpy as np

from . import studio
from .tools import binary

log = logging.getLogger(__name__)

FPS = 100
SR = 24000
HOP = SR // FPS
NFFT = 2048
SPEC_BINS = 80
BANDS = {"low": (30, 150), "mid": (150, 2500), "high": (5000, 16000)}
FOLDER = "songview"
# The audio a song can be: what the Studio already accepts for a reel.
SOUND = (".m4a", ".mp3", ".wav", ".opus", ".ogg", ".flac", ".aac", ".webm")


def folder(root: Path) -> Path:
    return Path(root) / studio.CACHE_DIR / FOLDER


def key_for(song: Path) -> str:
    """One cache name per song file, changing when the file does."""
    try:
        stamp = f"{song.stat().st_mtime_ns}:{song.stat().st_size}"
    except OSError:
        stamp = "0"
    return hashlib.sha1(f"{str(song).lower()}|{stamp}".encode("utf-8")).hexdigest()[:16]


def songs(home: Path) -> list[dict]:
    """Every song downloaded or dropped into Videos\\AutoStream\\songs, newest first."""
    out = []
    d = Path(home) / "songs"
    try:
        files = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in SOUND]
    except OSError:
        return out
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        # "Title [videoid].m4a" is what the downloader writes; the id is noise
        # on a list of songs.
        name = f.stem
        if name.endswith("]") and " [" in name:
            name = name[:name.rindex(" [")]
        out.append({"path": str(f), "name": name, "file": f.name,
                    "bytes": st.st_size, "when": int(st.st_mtime)})
    out.sort(key=lambda s: -s["when"])
    return out


def _decode(song: Path) -> np.ndarray:
    ff = binary("ffmpeg") or "ffmpeg"
    r = subprocess.run([ff, "-v", "error", "-i", str(song), "-ac", "1", "-ar", str(SR),
                        "-f", "f32le", "-"], capture_output=True, timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError((r.stderr or b"").decode("utf-8", "replace")[-300:] or "ffmpeg read nothing")
    return np.frombuffer(r.stdout, np.float32)


def _scale(v: np.ndarray, lo_pct: float = 5.0, hi_pct: float = 99.5) -> np.ndarray:
    lo, hi = np.percentile(v, lo_pct), np.percentile(v, hi_pct)
    return np.clip((v - lo) / max(1e-9, hi - lo) * 255, 0, 255).astype(np.uint8)


def build(song: Path) -> tuple[dict, bytes]:
    """The lanes and the spectrogram. -> (meta, bytes)"""
    x = _decode(Path(song))
    frames = max(1, len(x) // HOP)
    win = np.hanning(NFFT).astype(np.float32)
    freqs = np.fft.rfftfreq(NFFT, 1.0 / SR)
    edges = np.geomspace(30, 16000, SPEC_BINS + 1)
    spec_idx = [np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0] for i in range(SPEC_BINS)]
    spec_idx = [ix if len(ix) else np.array([int(np.argmin(np.abs(freqs - edges[i])))])
                for i, ix in enumerate(spec_idx)]
    band_idx = {k: np.where((freqs >= lo) & (freqs < hi))[0] for k, (lo, hi) in BANDS.items()}

    rms = np.zeros(frames, np.float32)
    bands = {k: np.zeros(frames, np.float32) for k in BANDS}
    flux = np.zeros(frames, np.float32)
    spec = np.zeros((frames, SPEC_BINS), np.float32)
    pad = np.concatenate([np.zeros(NFFT // 2, np.float32), x, np.zeros(NFFT, np.float32)])
    prev = None
    # In blocks, because one STFT of a four-minute song at this resolution is
    # 24,000 frames of 2048 samples -- 400 MB of float32 in one array.
    for f0 in range(0, frames, 2000):
        f1 = min(frames, f0 + 2000)
        idx = np.arange(f0, f1)[:, None] * HOP + np.arange(NFFT)[None, :]
        seg = pad[idx] * win
        mag = np.abs(np.fft.rfft(seg, axis=1)).astype(np.float32)
        power = mag ** 2
        rms[f0:f1] = np.sqrt((seg ** 2).mean(axis=1))
        for k, ix in band_idx.items():
            bands[k][f0:f1] = 10 * np.log10(power[:, ix].sum(axis=1) + 1e-10)
        logmag = np.log1p(mag * 10)
        first = prev if prev is not None else logmag[:1]
        flux[f0:f1] = np.maximum(np.diff(np.vstack([first, logmag]), axis=0), 0).sum(axis=1)
        prev = logmag[-1:]
        for i, ix in enumerate(spec_idx):
            spec[f0:f1, i] = 10 * np.log10(power[:, ix].mean(axis=1) + 1e-10)

    lanes = {"rms": _scale(rms, 0, 99.5), "low": _scale(bands["low"], 20),
             "mid": _scale(bands["mid"], 20), "high": _scale(bands["high"], 20),
             "flux": _scale(flux, 0, 99.5)}
    top = float(spec.max())
    spec_u8 = np.clip((spec - (top - 70)) / 70 * 255, 0, 255).astype(np.uint8)
    blob = bytearray()
    meta = {"fps": FPS, "frames": frames, "spec_bins": SPEC_BINS,
            "spec_edges": [round(float(e), 1) for e in edges],
            "bands": {k: list(v) for k, v in BANDS.items()}, "lanes": {},
            "seconds": round(frames / FPS, 3)}
    for name, arr in lanes.items():
        meta["lanes"][name] = [len(blob), int(arr.size)]
        blob += arr.tobytes()
    meta["lanes"]["spec"] = [len(blob), int(spec_u8.size)]
    blob += spec_u8.tobytes()
    return meta, bytes(blob)


def views(root: Path, song: Path) -> tuple[dict, bytes]:
    """The lanes for a song, from the cache when it is there. -> (meta, bytes)"""
    song = Path(song)
    here = folder(root)
    key = key_for(song)
    meta_f, blob_f = here / f"{key}.json", here / f"{key}.bin"
    try:
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
        if blob_f.is_file():
            return meta, blob_f.read_bytes()
    except (OSError, ValueError):
        pass
    meta, blob = build(song)
    try:
        here.mkdir(parents=True, exist_ok=True)
        blob_f.write_bytes(blob)
        meta_f.write_text(json.dumps(meta), encoding="utf-8")
    except OSError as e:
        log.info("songview: could not cache %s: %s", song.name, e)
    return meta, blob


def detected(shape, *, gap: float = 0.0) -> dict:
    """What clips/hits.py would cut this song on, for drawing beside the marks."""
    hits = list(getattr(shape, "hits", None) or [])
    strength = list(getattr(shape, "hit_strength", None) or [])
    if not hits:
        return {"pattern": getattr(shape, "pattern", ""), "hits": [], "kills": [], "accents": [], "big": []}
    from . import hits as hits_mod

    kills, accents = hits_mod.choose_kills(hits, strength or None,
                                           target_gap=gap or hits_mod.TARGET_GAP)
    return {"pattern": getattr(shape, "pattern", ""), "hits": [round(t, 4) for t in hits],
            "kills": [round(t, 4) for t in kills], "accents": [round(t, 4) for t in accents],
            "big": [round(t, 4) for t in (getattr(shape, "big", None) or [])]}
