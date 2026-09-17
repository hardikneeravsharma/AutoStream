r"""Kill Marks: mark where kills should land on real songs, to learn the rule from.

WHY
    The Studio puts kills on beats its beat finder chose, and on the player's
    songs that is not good enough -- MONTERO came out 71.9 BPM. Instead of
    tuning the finder by ear, this collects ground truth: the player listens to a
    song and presses K wherever a kill should land, the way an editor would cut
    it. Those marks are then compared with everything the finder reports (beat,
    bar position, onsets, loudness, the drop) to learn which moments kills
    belong on, and how far off the finder's grid is.

WHAT IT DOES
    A local page (http://127.0.0.1:8790/). Paste YouTube links; each song's
    audio is downloaded with the Studio's own downloader (clips/songfetch.py)
    and analysed with the Studio's own beat finder (clips/reel.py), so the grid
    shown is the grid reels are cut to. Marks save as they are made, one file
    per song in Videos\AutoStream\songs\marks\<video id>.json, with the analysis
    they were made against.

    A tap is late by the player's reaction plus the audio device's latency --
    tens of milliseconds, more over Bluetooth. The page measures it once against
    a click track played through the same audio element, and stores it; marks
    are kept raw and corrected at analysis time.

RUN
    .venv\Scripts\python.exe scripts\kill_marks\server.py

Loopback only. A POST must be JSON from this page's own origin, so another
site open in the browser cannot make it download or overwrite anything.
"""
from __future__ import annotations

import json
import math
import mimetypes
import os
import struct
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np                                 # noqa: E402

from autostream import paths                       # noqa: E402
from autostream.clips import hits as hits_mod, reel, songfetch   # noqa: E402

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("KILL_MARKS_PORT", "8790"))
MARKS = paths.VIDEO_HOME / "songs" / "marks"
SETTINGS = MARKS / "_calibration.json"
LOCK = threading.Lock()
QUEUE: list[str] = []                               # video ids waiting to download
WAKE = threading.Event()


def _num(o):
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(type(o))


def _read(vid: str) -> dict | None:
    f = MARKS / f"{vid}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(vid: str, data: dict) -> None:
    MARKS.mkdir(parents=True, exist_ok=True)
    tmp = MARKS / f"{vid}.json.tmp"
    tmp.write_text(json.dumps(data, indent=1, default=_num), encoding="utf-8")
    tmp.replace(MARKS / f"{vid}.json")


def _songs() -> list[dict]:
    out = []
    for f in sorted(MARKS.glob("*.json"), key=lambda p: p.stat().st_mtime):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        a = d.get("analysis") or {}
        out.append({"id": d["id"], "url": d.get("url", ""), "title": d.get("title") or d["id"],
                    "state": d.get("state", "queued"), "percent": d.get("percent", 0),
                    "error": d.get("error", ""), "seconds": a.get("seconds"), "bpm": a.get("bpm"),
                    "marks": len(d.get("marks") or []), "done": bool(d.get("done")),
                    "added": d.get("added", 0)})
    out.sort(key=lambda s: s["added"])
    return out


# ------------------------------------------------------------------ the download worker

def _set(vid: str, **kw) -> None:
    with LOCK:
        d = _read(vid) or {"id": vid}
        d.update(kw)
        _write(vid, d)


def _worker() -> None:
    while True:
        WAKE.wait(2.0)
        WAKE.clear()
        while True:
            with LOCK:
                vid = QUEUE.pop(0) if QUEUE else None
            if vid is None:
                break
            d = _read(vid) or {}
            job = songfetch.Fetch(d.get("url") or f"https://www.youtube.com/watch?v={vid}", vid)
            t = threading.Thread(target=job.run, daemon=True)
            t.start()
            while t.is_alive():
                s = job.snapshot()
                _set(vid, state="downloading", percent=round(s.get("percent") or 0, 1),
                     title=s.get("title") or d.get("title", ""))
                time.sleep(0.4)
            s = job.snapshot()
            if s["state"] != "done":
                _set(vid, state="failed", error=s.get("error") or "The download failed.")
                continue
            _set(vid, state="analysing", percent=100, title=s.get("title") or vid, path=s["path"])
            try:
                shape = reel.analyse(Path(s["path"]))
                _features(vid, Path(s["path"]))       # computed now, so opening the song is instant
                _set(vid, state="ready", analysis=shape.as_dict(), error="")
            except Exception as e:                  # noqa: BLE001
                _set(vid, state="failed", error=f"The song downloaded, but its beat couldn't be read: {e}")


def _resume() -> None:
    """Songs added before a restart that never finished downloading."""
    MARKS.mkdir(parents=True, exist_ok=True)
    for s in _songs():
        if s["state"] in ("queued", "downloading", "analysing"):
            QUEUE.append(s["id"])
    WAKE.set()


def _median(v) -> float:
    return float(np.median(v)) if len(v) else 0.0


def _with_detected(d: dict) -> dict:
    """The song, plus what clips/hits.py makes of it: hits, kills, accents, big hits.

    Drawn beside the player's own marks so the detector can be reviewed against
    them. Computed once and kept in the song's file; a song analysed before the
    detector existed is analysed again here.
    """
    a = d.get("analysis") or {}
    if d.get("state") != "ready":
        return d
    song = Path(d.get("path") or "")
    if "pattern" not in a and song.is_file():
        try:
            a = reel.analyse(song).as_dict()
            d["analysis"] = a
            with LOCK:
                _write(d["id"], d)
        except Exception as e:                    # noqa: BLE001
            log_line = f"could not re-analyse {d['id']}: {e}"
            print(log_line, flush=True)
            return d
    hits = list(a.get("hits") or [])
    strength = list(a.get("hit_strength") or [])
    # At the spacing this song was marked at, so the page compares like with
    # like; a reel uses its style's spacing instead.
    marks = sorted(m["t"] for m in (d.get("marks") or []))
    gap = float(_median(np.diff(marks))) if len(marks) > 2 else hits_mod.TARGET_GAP
    kills, accents = hits_mod.choose_kills(hits, strength or None, target_gap=gap)
    d = dict(d)
    d["detected"] = {"hits": hits, "kills": kills, "accents": accents,
                     "big": list(a.get("big") or []), "pattern": a.get("pattern", ""),
                     "gap": round(gap, 3)}
    return d


# ------------------------------------------------------------------ ways of seeing a song
#
# Each is 100 frames a second, scaled 0-255, so the page draws any stretch of
# the song straight from the bytes without doing signal processing per frame:
#
#   rms        loudness
#   low        30-150 Hz energy: kick drum and bass
#   mid        150-2500 Hz: snare body, vocals, most instruments
#   high       5-16 kHz: hi-hats, cymbals, the crack of a snare
#   flux       onset strength -- how much new energy arrives, summed over
#              frequencies; what a beat finder listens to
#   spec       a spectrogram, 80 log-spaced bands from 30 Hz to 16 kHz
FPS = 100
SR = 24000
HOP = SR // FPS
NFFT = 2048
SPEC_BINS = 80
BANDS = {"low": (30, 150), "mid": (150, 2500), "high": (5000, 16000)}


def _features(vid: str, audio: Path) -> tuple[dict, bytes]:
    """-> (meta, blob). Cached beside the marks; recomputed only if the song file changes."""
    import numpy as np

    meta_f, blob_f = MARKS / f"_{vid}.features.json", MARKS / f"_{vid}.features.bin"
    try:
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
        if meta.get("source_mtime") == int(audio.stat().st_mtime) and blob_f.is_file():
            return meta, blob_f.read_bytes()
    except (OSError, ValueError):
        pass

    from autostream.clips.tools import binary
    import subprocess

    raw = subprocess.run([binary("ffmpeg") or "ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, timeout=300,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    x = np.frombuffer(raw, np.float32)
    frames = max(1, len(x) // HOP)
    win = np.hanning(NFFT).astype(np.float32)
    freqs = np.fft.rfftfreq(NFFT, 1.0 / SR)
    edges = np.geomspace(30, 16000, SPEC_BINS + 1)
    spec_idx = [np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0] for i in range(SPEC_BINS)]
    spec_idx = [ix if len(ix) else np.array([int(np.argmin(np.abs(freqs - edges[i])))]) for i, ix in enumerate(spec_idx)]
    band_idx = {k: np.where((freqs >= lo) & (freqs < hi))[0] for k, (lo, hi) in BANDS.items()}

    rms = np.zeros(frames, np.float32)
    bands = {k: np.zeros(frames, np.float32) for k in BANDS}
    flux = np.zeros(frames, np.float32)
    spec = np.zeros((frames, SPEC_BINS), np.float32)
    pad = np.concatenate([np.zeros(NFFT // 2, np.float32), x, np.zeros(NFFT, np.float32)])
    prev = None
    step = 2000
    for f0 in range(0, frames, step):
        f1 = min(frames, f0 + step)
        idx = np.arange(f0, f1)[:, None] * HOP + np.arange(NFFT)[None, :]
        seg = pad[idx] * win
        mag = np.abs(np.fft.rfft(seg, axis=1)).astype(np.float32)
        power = mag ** 2
        rms[f0:f1] = np.sqrt((seg ** 2).mean(axis=1))
        for k, ix in band_idx.items():
            bands[k][f0:f1] = 10 * np.log10(power[:, ix].sum(axis=1) + 1e-10)
        logmag = np.log1p(mag * 10)
        diff = np.diff(np.vstack([prev, logmag]) if prev is not None else np.vstack([logmag[:1], logmag]), axis=0)
        flux[f0:f1] = np.maximum(diff, 0).sum(axis=1)
        prev = logmag[-1:]
        for i, ix in enumerate(spec_idx):
            spec[f0:f1, i] = 10 * np.log10(power[:, ix].mean(axis=1) + 1e-10)

    def scale(v, lo_pct=5, hi_pct=99.5):
        lo, hi = np.percentile(v, lo_pct), np.percentile(v, hi_pct)
        return np.clip((v - lo) / max(1e-9, hi - lo) * 255, 0, 255).astype(np.uint8)

    lanes = {"rms": scale(rms, 0, 99.5), "low": scale(bands["low"], 20), "mid": scale(bands["mid"], 20),
             "high": scale(bands["high"], 20), "flux": scale(flux, 0, 99.5)}
    top = spec.max()
    spec_u8 = np.clip((spec - (top - 70)) / 70 * 255, 0, 255).astype(np.uint8)
    blob = bytearray()
    meta = {"fps": FPS, "frames": frames, "spec_bins": SPEC_BINS, "spec_edges": [round(float(e), 1) for e in edges],
            "bands": BANDS, "lanes": {}, "source_mtime": int(audio.stat().st_mtime)}
    for name, arr in lanes.items():
        meta["lanes"][name] = [len(blob), len(arr)]
        blob += arr.tobytes()
    meta["lanes"]["spec"] = [len(blob), spec_u8.size]
    blob += spec_u8.tobytes()
    MARKS.mkdir(parents=True, exist_ok=True)
    blob_f.write_bytes(bytes(blob))
    meta_f.write_text(json.dumps(meta), encoding="utf-8")
    return meta, bytes(blob)


# ------------------------------------------------------------------ the calibration click

def _click_track() -> Path:
    """30 s of clicks at 100 BPM, as a WAV, played through the page's own audio element."""
    f = MARKS / "_click_100bpm.wav"
    if f.is_file():
        return f
    MARKS.mkdir(parents=True, exist_ok=True)
    rate, bpm, seconds = 44100, 100.0, 30.0
    beat = 60.0 / bpm
    frames = bytearray()
    first = 1.0
    for i in range(int(seconds * rate)):
        t = i / rate
        since = (t - first) % beat if t >= first else 1.0
        v = math.sin(2 * math.pi * 1500 * t) * math.exp(-since * 90) if since < 0.04 else 0.0
        frames += struct.pack("<h", int(v * 22000))
    with wave.open(str(f), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return f


CLICK = {"bpm": 100.0, "first": 1.0}


# ------------------------------------------------------------------ http

class Handler(BaseHTTPRequestHandler):
    server_version = "KillMarks/1"

    def log_message(self, fmt, *args):             # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, default=_num).encode("utf-8"), "application/json")

    def _file(self, f: Path) -> None:
        """A song or the click track, with Range: the page seeks."""
        size = f.stat().st_size
        ctype = mimetypes.guess_type(f.name)[0] or ("audio/mp4" if f.suffix == ".m4a" else "application/octet-stream")
        rng = self.headers.get("Range", "")
        start, end = 0, size - 1
        code = 200
        if rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else max(0, size - int(b))
            end = int(b) if (a and b) else size - 1
            end = min(end, size - 1)
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with f.open("rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(65536, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    return
                left -= len(chunk)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if u.path in ("/", "/index.html"):
            return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/songs":
            cal = None
            try:
                cal = json.loads(SETTINGS.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            return self._json({"songs": _songs(), "calibration": cal, "click": CLICK})
        if u.path == "/api/song":
            d = _read((q.get("id") or [""])[0])
            if not d:
                return self._json({"error": "No such song."}, 404)
            return self._json(_with_detected(d))
        if u.path == "/api/audio":
            d = _read((q.get("id") or [""])[0]) or {}
            f = Path(d.get("path") or "")
            if not f.name or not f.is_file() or f.parent.resolve() != (paths.VIDEO_HOME / "songs").resolve():
                return self._json({"error": "No such song."}, 404)
            return self._file(f)
        if u.path in ("/api/features", "/api/features.bin"):
            d = _read((q.get("id") or [""])[0]) or {}
            f = Path(d.get("path") or "")
            if not f.name or not f.is_file():
                return self._json({"error": "No such song."}, 404)
            try:
                meta, blob = _features(d["id"], f)
            except Exception as e:                  # noqa: BLE001
                return self._json({"error": f"Couldn't read the song's sound: {e}"}, 500)
            if u.path == "/api/features":
                return self._json(meta)
            return self._send(200, blob, "application/octet-stream")
        if u.path == "/api/click.wav":
            return self._file(_click_track())
        return self._json({"error": "Not found."}, 404)

    def _body(self) -> dict | None:
        # Only this page may write: JSON (which a cross-site form cannot send
        # without a preflight this server never answers) from its own origin.
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return None
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return None
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(min(n, 2_000_000)) or b"{}")
        except (ValueError, OSError):
            return None

    def do_POST(self):
        u = urlparse(self.path)
        b = self._body()
        if b is None:
            return self._json({"error": "Refused."}, 403)
        if u.path == "/api/add":
            results = []
            for raw in (b.get("urls") or [])[:200]:
                url = str(raw).strip()
                if not url:
                    continue
                try:
                    vid = songfetch.video_id(url)
                except songfetch.FetchError as e:
                    results.append({"url": url, "ok": False, "error": str(e)})
                    continue
                with LOCK:
                    have = _read(vid)
                    if have and have.get("state") in ("ready", "queued", "downloading", "analysing"):
                        results.append({"url": url, "ok": True, "id": vid, "already": True})
                        continue
                    d = have or {"id": vid, "marks": [], "done": False, "added": time.time()}
                    d.update(url=url, state="queued", percent=0, error="")
                    _write(vid, d)
                    QUEUE.append(vid)
                results.append({"url": url, "ok": True, "id": vid})
            WAKE.set()
            return self._json({"results": results})
        if u.path == "/api/marks":
            vid = str(b.get("id") or "")
            marks = []
            for m in (b.get("marks") or [])[:2000]:
                try:
                    marks.append({"t": round(float(m["t"]), 4), "kind": "big" if m.get("kind") == "big" else "kill",
                                  "rate": round(float(m.get("rate") or 1.0), 3), "at": float(m.get("at") or time.time())})
                except (KeyError, TypeError, ValueError):
                    continue
            with LOCK:
                d = _read(vid)
                if not d:
                    return self._json({"error": "No such song."}, 404)
                d["marks"] = sorted(marks, key=lambda m: m["t"])
                d["done"] = bool(b.get("done"))
                d["updated"] = time.time()
                _write(vid, d)
            return self._json({"ok": True, "saved": len(marks)})
        if u.path == "/api/retry":
            vid = str(b.get("id") or "")
            with LOCK:
                d = _read(vid)
                if not d:
                    return self._json({"error": "No such song."}, 404)
                d.update(state="queued", percent=0, error="")
                _write(vid, d)
                QUEUE.append(vid)
            WAKE.set()
            return self._json({"ok": True})
        if u.path == "/api/calibration":
            taps = [float(x) for x in (b.get("offsets") or []) if isinstance(x, (int, float))][:200]
            if len(taps) < 6:
                return self._json({"error": "Tap along to at least six clicks."}, 400)
            s = sorted(taps)
            med = s[len(s) // 2]
            spread = sorted(abs(x - med) for x in s)[len(s) // 2]
            data = {"offset": round(med, 4), "spread": round(spread, 4), "taps": len(taps), "when": time.time()}
            MARKS.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(json.dumps(data, indent=1), encoding="utf-8")
            return self._json({"ok": True, **data})
        return self._json({"error": "Not found."}, 404)


def main() -> None:
    _resume()
    threading.Thread(target=_worker, name="kill-marks-download", daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Kill Marks: http://127.0.0.1:{PORT}/  (marks in {MARKS})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
