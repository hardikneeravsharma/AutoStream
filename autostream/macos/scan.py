"""One decode for the VALORANT kill feed AND the kill emblem, on a Mac.

WHY
    A VALORANT clip job decoded every second of the window twice: once to read
    the kill feed (valorant_feed.scan) and once, straight after, to find the
    kill emblem that confirms each kill (killmark.scan). On Windows that second
    pass runs on the graphics card and hides; on a Mac every decode is the CPU,
    and an M2 tops out at about 7.5x real time on a 1440p60 recording -- so a
    69-minute window spent 15 minutes on the feed and 20 more decoding the same
    footage again for the emblem. Measured on the report that asked (#212).

HOW
    Each feed chunk is ONE ffmpeg, its decoded picture `split` in two:

      branch A  exactly what valorant_feed pipes for the span: fps, the band's
                crop, rgb24 -- and trimmed to the span, as -t trimmed it
      branch B  exactly what killmark._region reads: 15 fps, the emblem crop,
                scaled to REGION_WIDTH, grey -- running one second past the
                span, as killmark's own chunks overlap

    Each branch goes out on its own pipe. Branch A feeds the same row reader
    valorant_feed._span uses; branch B is cut into killmark's own 30-second
    chunks (120 is four of them, and both start at the window's start) and
    scored with killmark's own ring_scores/onsets. The onsets are kept, by
    chunk start, and killmark.scan takes them from here instead of decoding.

    Windows never comes here: valorant_feed and killmark reach this module
    only from behind sys.platform == "darwin".
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path

log = logging.getLogger("autostream.macos.scan")

# killmark.scan's own chunking, which the emblem onsets must reproduce.
EMBLEM_CHUNK = 30.0
EMBLEM_OVERLAP = 1.0
EMBLEM_FPS = 15.0

# (video, chunk start rounded to the ms) -> that chunk's emblem onsets, in the
# recording's seconds. Filled by span(), read by emblem_onsets().
_ONSETS: dict[tuple[str, float], list[float]] = {}
_LOCK = threading.Lock()


def _key(video, t0: float) -> tuple[str, float]:
    return (str(Path(video)), round(float(t0), 3))


def _emblem_chain(spec, region_h: int) -> str:
    """killmark._region's -vf, verbatim."""
    from ..clips.killmark import REGION_WIDTH

    return (f"fps={EMBLEM_FPS:g},crop=iw*{spec.x1 - spec.x0:.4f}:ih*{spec.y1 - spec.y0:.4f}:"
            f"iw*{spec.x0:.4f}:ih*{spec.y0:.4f},scale={REGION_WIDTH}:{region_h},format=gray")


def _region_h(spec) -> int:
    from ..clips.killmark import REGION_WIDTH

    return int(round(REGION_WIDTH * (spec.y1 - spec.y0) * 9 / 16 / (spec.x1 - spec.x0)))


def _read_all(fd: int, sink: list) -> None:
    with os.fdopen(fd, "rb") as f:
        sink.append(f.read())


def frames_and_emblem(video: Path, band, start: float, dur: float, fps: float,
                      shape, window_end: float, spec):
    """Yield (time, band frame) exactly as valorant_feed._raw_frames does, and
    on exhaustion return the emblem frames for [start, start + dur + overlap].

    A generator whose return value is the emblem frames: the caller drains it
    with `yield from` semantics, or via the wrapper in span().
    """
    import numpy as np

    from ..clips.killfeed import _NO_WINDOW
    from ..clips.tools import binary
    from ..clips.valorant_feed import _crop_expr

    h, w = shape
    size = h * w * 3
    region_h = _region_h(spec)
    # killmark reads min(chunk + 1, window end - t0) from each 30 s start; the
    # span's last emblem chunk is the one that needs the overlap.
    emblem_secs = min(dur + EMBLEM_OVERLAP, max(0.0, window_end - start))
    feed_secs = max(0.5, dur)
    # TWO OUTPUTS OF ONE DECODE, each with its own -vf and -t -- which is
    # exactly how each standalone reader is built. A `split` filtergraph was
    # tried first and picked its frames one source frame (1/60 s) off theirs;
    # this is byte-identical to both, measured.
    feed_r, feed_w = os.pipe()
    emb_r, emb_w = os.pipe()
    args = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", f"{start:.3f}", "-i", str(video),
            "-t", f"{feed_secs:.3f}", "-an", "-sn",
            "-vf", f"fps={fps},{_crop_expr(band)}", "-pix_fmt", "rgb24",
            "-f", "rawvideo", f"pipe:{feed_w}",
            "-t", f"{emblem_secs:.3f}", "-an", "-sn",
            "-vf", _emblem_chain(spec, region_h),
            "-f", "rawvideo", f"pipe:{emb_w}"]
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, pass_fds=(feed_w, emb_w),
                            creationflags=_NO_WINDOW)
    os.close(feed_w)
    os.close(emb_w)
    # The emblem branch is drained on its own thread, or ffmpeg blocks on that
    # pipe while this one waits for band frames: two outputs, one writer.
    got: list[bytes] = []
    reader = threading.Thread(target=_read_all, args=(emb_r, got), daemon=True)
    reader.start()
    feed = os.fdopen(feed_r, "rb")
    try:
        i = 0
        while True:
            buf = feed.read(size)
            if not buf or len(buf) < size:
                break
            yield start + i / fps, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            i += 1
    finally:
        feed.close()
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=30)
        reader.join(timeout=30)
    from ..clips.killmark import REGION_WIDTH

    raw = got[0] if got else b""
    n = len(raw) // (REGION_WIDTH * region_h)
    # Kept as bytes: as float32, 121 s of it is 180 MB a worker. Each 30 s
    # slice is converted as killmark._region converts its own chunk.
    return np.frombuffer(raw, np.uint8)[:n * REGION_WIDTH * region_h].reshape(
        n, region_h, REGION_WIDTH)


def _store_onsets(video, start: float, dur: float, emblem, spec, window_end: float) -> None:
    """Cut the emblem frames into killmark's 30 s chunks and keep each one's onsets."""
    from ..clips.killmark import onsets, ring_scores

    per = int(round(EMBLEM_CHUNK * EMBLEM_FPS))
    t0, k = start, 0
    found = {}
    while t0 < start + dur - 0.05:
        secs = min(EMBLEM_CHUNK + EMBLEM_OVERLAP, window_end - t0)
        frames = emblem[k * per: k * per + int(round(secs * EMBLEM_FPS))].astype("float32")
        found[_key(video, t0)] = [round(t0 + o, 3)
                                  for o in onsets(ring_scores(frames, spec.cx, spec.cy), EMBLEM_FPS)]
        k += 1
        t0 += EMBLEM_CHUNK
    with _LOCK:
        _ONSETS.update(found)


def span(args, window_end: float):
    """valorant_feed._span, reading the emblem from the same decode. Same rows."""
    from ..clips import valorant_feed as vf
    from ..clips.killmark import spec_for

    video, band, start, dur, fps, frame_h, shape, want_capture, cancelled, _on_gpu = args
    spec = spec_for("VALORANT")
    capture = None
    if want_capture:
        from ..clips import feed_ocr

        capture = feed_ocr.Capture(frame_h)
    out = []
    gen = frames_and_emblem(Path(video), band, start, dur, fps, shape, window_end, spec)
    emblem = None
    try:
        while True:
            at, a = next(gen)
            if cancelled and cancelled():
                gen.close()
                break
            planes = vf.masks(a)
            rows = vf.read_frame(a, at, frame_height=frame_h, planes=planes)
            out.extend(rows)
            if capture is not None:
                capture.add(a, at, rows, planes[2])
    except StopIteration as done:
        emblem = done.value
    if emblem is not None and not (cancelled and cancelled()):
        _store_onsets(video, start, dur, emblem, spec, window_end)
    return out, (capture.frames if capture is not None else [])


def emblem_onsets(video, start: float, duration: float) -> list[float] | None:
    """killmark.scan's answer from the shared decode, or None when any of its
    30 s chunks was not read that way -- the caller then decodes as before."""
    starts, t = [], start
    while t < start + duration - 0.05:
        starts.append(t)
        t += EMBLEM_CHUNK
    with _LOCK:
        parts = [_ONSETS.get(_key(video, t0)) for t0 in starts]
    if not starts or any(p is None for p in parts):
        return None
    from ..clips.killmark import HOLD

    # A gap can end before the window does (at a match record), and its own
    # scan would not have read past that end: an onset needs HOLD seconds of
    # frames after it, all inside what was read.
    end = start + duration + 1e-6
    found = sorted(o for p in parts for o in p if o + HOLD <= end)
    merged: list[float] = []
    for o in found:                       # killmark.scan's own merge, verbatim
        if not merged or o - merged[-1] > 0.6:
            merged.append(o)
    return merged


def forget(video=None) -> None:
    """Drop the kept onsets -- for one recording, or all of them."""
    with _LOCK:
        if video is None:
            _ONSETS.clear()
        else:
            for k in [k for k in _ONSETS if k[0] == str(Path(video))]:
                del _ONSETS[k]
