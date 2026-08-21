"""Find your own kills by template-matching the on-screen kill marker.

WHY NOT READ THE KILL FEED
    The feed lists everyone's kills, so telling a kill from a death needs the
    killer/victim SIDE, which needs OCR, which needs fuzzy name matching to
    survive Tesseract's mistakes on a HUD font. The marker is strictly better:
    it is the player's own kill confirmation, drawn at a fixed spot, and it is
    a glyph rather than text -- so it can be matched instead of read.

    A colour prefilter was tried first and rejected: the running score beside
    the markers renders white in some frames and gold in others. The glyph is
    dependable where the colour is not.

THE TWO THINGS THAT SILENTLY BREAK THIS
    1. Resolution. The template is a fixed pixel patch. Match a 720p template
       against a 1080p frame and you get nothing -- not fewer hits, none. Every
       band is rescaled to the profile's ref_height before matching.
    2. Crop arithmetic. ffmpeg ROUNDS a fractional crop where int() truncates
       (204.8 -> 205 vs 204). Predicting the size instead of computing it makes
       the reshape misalign by one pixel per row and the scan quietly returns
       nothing. Integers are computed up front and handed to ffmpeg literally.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from .profiles import Profile
from .tools import ffmpeg_raw, has_cuda, media_info

log = logging.getLogger("autostream.clips.detect")

# One ffmpeg per chunk, several at once. Decode is the entire cost here: two
# hours of 1080p60 is 432,000 frames even though only two per second are ever
# matched, and a single serial pass leaves both the GPU decoder and most CPU
# cores idle.
CHUNK_SECONDS = 300.0
MAX_WORKERS = 4


@dataclass
class Kill:
    time: float
    score: float
    count: int            # markers visible in that frame
    # When the marker was last still on screen. `time` is when it APPEARED,
    # and that is the wrong thing to end a clip against: the kill feed and the
    # marker animation carry on for seconds afterwards, so a clip cut two
    # seconds past `time` still lands in the middle of them. Cutting against
    # `end` is what actually gets past the moment.
    end: float = 0.0

    def __post_init__(self) -> None:
        if not self.end:
            self.end = self.time


def load_template(profile: Profile) -> np.ndarray:
    p = profile.template_path()
    if not p.is_file():
        raise FileNotFoundError(
            f"no kill-marker template for {profile.label} at {p}. "
            f"Calibrate the game first.")
    t = np.load(p).astype(np.float32)
    return t - t.mean()          # zero-mean once, not per position


def band_geometry(width: int, height: int, profile: Profile):
    """-> ((x, y, w, h) in source pixels, (w, h) at the template's scale).

    The source crop and the matching size are computed separately on purpose.
    Cropping happens at native resolution so nothing is resampled twice, then
    a single scale brings the band to the geometry the template was cut at.
    """
    x1, y1, x2, y2 = profile.band
    x = int(round(width * x1))
    y = int(round(height * y1))
    w = max(1, int(round(width * x2)) - x)
    h = max(1, int(round(height * y2)) - y)

    ref_h = profile.ref_height
    ref_w = int(round(ref_h * width / height)) if height else ref_h
    rw = max(1, int(round(ref_w * x2)) - int(round(ref_w * x1)))
    rh = max(1, int(round(ref_h * y2)) - int(round(ref_h * y1)))
    return (x, y, w, h), (rw, rh)


def ncc(band: np.ndarray, tmpl0: np.ndarray, match_min: float) -> tuple[float, int]:
    """Best zero-mean normalised cross-correlation of tmpl over band.

    -> (best score, how many distinct marker positions cleared match_min)

    Vectorised over every candidate position. A Python loop here costs ~4700
    iterations per frame, which is 69 million over a two-hour scan and takes
    hours; as_strided builds all the candidate patches as one view so numpy
    does the whole frame in a single pass.
    """
    th, tw = tmpl0.shape
    bh, bw = band.shape
    if bh < th or bw < tw:
        return 0.0, 0
    tnorm = float(np.sqrt((tmpl0 ** 2).sum())) + 1e-6

    oh, ow = bh - th + 1, bw - tw + 1
    s0, s1 = band.strides
    patches = np.lib.stride_tricks.as_strided(
        band, shape=(oh, ow, th, tw), strides=(s0, s1, s0, s1), writeable=False)

    # as_strided itself is a free view, but `patches - means` MATERIALISES the
    # whole thing: oh * ow * th * tw floats. With the 18x20 skull that is a few
    # megabytes and nobody notices. With a template someone drew by hand it is
    # quadratic in the template size -- a 230x43 patch over a 576x73 band comes
    # to 106 million floats, 425 MB, for ONE frame. Calibration then ran the
    # app to several gigabytes.
    #
    # Chunking over output rows keeps the arithmetic identical and bounds the
    # intermediate to a fixed budget instead of the template's area.
    budget = 32 * 1024 * 1024                      # bytes per intermediate
    per_row = max(1, ow * th * tw * 4)
    rows = max(1, min(oh, budget // per_row))

    corr = np.empty((oh, ow), dtype=np.float32)
    for lo in range(0, oh, rows):
        hi = min(oh, lo + rows)
        block = patches[lo:hi]
        centred = block - block.mean(axis=(2, 3), keepdims=True)
        num = (centred * tmpl0).sum(axis=(2, 3))
        den = np.sqrt((centred ** 2).sum(axis=(2, 3))) * tnorm + 1e-6
        corr[lo:hi] = num / den

    best = float(corr.max())
    # Collapse adjacent columns: one marker lights up a run of near-identical
    # positions, and counting those as separate markers would inflate every
    # kill count by roughly the template width.
    count, last = 0, -10 ** 6
    for x in sorted(set(np.where(corr >= match_min)[1].tolist())):
        if x - last > tw // 2:
            count += 1
        last = x
    return best, count


def colour_hits(band: np.ndarray, profile: Profile) -> tuple[float, int]:
    """How much of the band matches the profile's colour. -> (0-1 score, rows).

    For games with no glyph to correlate against. CS2 marks the local player's
    killfeed rows by outlining them red and by nothing else, so the signal is
    the presence of that colour in the killfeed strip.

    Scored as a fraction of min_pixels rather than a raw count, so the number
    lands on the same 0-1 scale as a correlation and the rest of the pipeline --
    thresholds, merging, reporting -- needs no special case for it.
    """
    target = np.array(profile.colour, dtype=np.int16)
    diff = np.abs(band.astype(np.int16) - target).max(axis=2)
    mask = diff <= profile.tolerance
    count = int(mask.sum())
    if count < profile.min_pixels:
        return count / max(1, profile.min_pixels), 0
    # Distinct ROWS, not distinct pixels: one killfeed entry is one kill and
    # entries stack vertically, so runs of matching rows are what to count.
    rows = np.where(mask.any(axis=1))[0]
    blobs, last = 0, -10 ** 6
    for r in rows.tolist():
        if r - last > 2:
            blobs += 1
        last = r
    return min(1.0, count / max(1, profile.min_pixels)), max(1, blobs)


def scan_span(video: Path, profile: Profile, start: float, duration: float,
              tmpl0: np.ndarray | None, geom=None) -> list[Kill]:
    """Scan one span. A single ffmpeg, cropped, piped raw."""
    if geom is None:
        info = media_info(video)
        geom = band_geometry(info["width"], info["height"], profile)
    (x, y, w, h), (rw, rh) = geom
    colour_mode = profile.mode == "colour"

    # Crop before scale so the rescale operates on the band alone, and crop in
    # ffmpeg so only the band crosses the pipe rather than whole frames.
    # Colour mode needs the colour, so it pays three bytes a pixel not one.
    vf = (f"fps={profile.scan_fps},crop={w}:{h}:{x}:{y},"
          f"scale={rw}:{rh}:flags=bilinear,"
          f"format={'rgb24' if colour_mode else 'gray'}")
    args = []
    if has_cuda():
        # Decode on the GPU; frames come back to system memory automatically
        # because no hwaccel_output_format is requested, which is what the CPU
        # crop/scale filters need.
        args += ["-hwaccel", "cuda"]
    args += ["-ss", f"{start:.3f}", "-i", str(video), "-t", f"{duration:.3f}",
             "-an", "-sn", "-vf", vf, "-f", "rawvideo", "-"]

    raw = ffmpeg_raw(args)
    frame_bytes = rw * rh * (3 if colour_mode else 1)
    if not raw or frame_bytes == 0:
        return []
    n = len(raw) // frame_bytes
    if n == 0:
        return []
    shape = (n, rh, rw, 3) if colour_mode else (n, rh, rw)
    frames = np.frombuffer(raw[:n * frame_bytes], dtype=np.uint8).reshape(shape)

    out: list[Kill] = []
    last = -1e9
    for i in range(n):
        if colour_mode:
            score, count = colour_hits(frames[i], profile)
        else:
            score, count = ncc(frames[i].astype(np.float32), tmpl0, profile.match_min)
        if score < profile.match_min or count < 1:
            continue
        t = start + i / profile.scan_fps
        if t - last > profile.merge_gap:
            out.append(Kill(time=t, score=score, count=max(1, count), end=t))
            last = t
        elif out:
            # Same marker still up. Deliberately does NOT touch `last`, so which
            # frames become events is unchanged -- only how far each one is
            # known to extend. Advancing `last` here would swallow a sustained
            # display into a single event and change every kill count.
            out[-1].end = t
            out[-1].score = max(out[-1].score, score)
            out[-1].count = max(out[-1].count, count)
    return out


def scan(video: Path, profile: Profile, *,
         progress: Callable[[int, int], None] | None = None,
         cancelled: Callable[[], bool] | None = None,
         duration: float | None = None) -> list[Kill]:
    """Scan a whole recording for kill markers. -> kills in time order."""
    video = Path(video)
    info = media_info(video)
    total = duration if duration is not None else info["duration"]
    if not total:
        return []

    if profile.mode == "killfeed":
        return scan_killfeed(video, profile, total, progress, cancelled)

    if info["height"] < profile.ref_height:
        # Not fatal: upscaling a smaller frame still matches, just with less to
        # separate a real marker from a bright patch of terrain.
        log.warning("source is %dp but %s was calibrated at %dp; matches will be "
                    "less certain", info["height"], profile.label, profile.ref_height)

    # Colour profiles have no template to load.
    tmpl0 = None if profile.mode == "colour" else load_template(profile)
    geom = band_geometry(info["width"], info["height"], profile)
    log.info("scanning %s for %s markers: %dx%d, band %s -> %s",
             video.name, profile.label, info["width"], info["height"],
             geom[0], geom[1])

    spans = []
    t = 0.0
    while t < total:
        spans.append((t, min(CHUNK_SECONDS, total - t)))
        t += CHUNK_SECONDS

    done = 0
    results: list[list[Kill]] = [[] for _ in spans]
    if progress:
        progress(0, len(spans))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(scan_span, video, profile, s, d, tmpl0, geom): i
            for i, (s, d) in enumerate(spans)
        }
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as e:  # noqa: BLE001
                log.warning("chunk %d failed: %s", i, e)
                results[i] = []
            done += 1
            if progress:
                progress(done, len(spans))
            if cancelled and cancelled():
                # Chunks already running finish on their own; nothing queued
                # behind them starts.
                pool.shutdown(wait=False, cancel_futures=True)
                raise Cancelled("scan cancelled")

    kills = [k for chunk in results for k in chunk]
    kills.sort(key=lambda k: k.time)

    # Chunk boundaries can split one marker popup across two spans, which would
    # otherwise show up as two kills a second apart.
    merged: list[Kill] = []
    for k in kills:
        if merged and k.time - merged[-1].time <= profile.merge_gap:
            merged[-1].count = max(merged[-1].count, k.count)
            merged[-1].score = max(merged[-1].score, k.score)
            merged[-1].end = max(merged[-1].end, k.end)
            continue
        merged.append(k)
    log.info("found %d kill(s) in %s", len(merged), video.name)
    return merged


def scan_killfeed(video: Path, profile: Profile, total: float,
                  progress: Callable[[int, int], None] | None,
                  cancelled: Callable[[], bool] | None) -> list[Kill]:
    """Kills read out of the feed rather than matched as a glyph.

    Kept behind the same signature as the template path so everything
    downstream -- bursts, windows, the tail guarantee, captions, the montage --
    works on these exactly as it does on Delta Force's.
    """
    from . import killfeed

    if not profile.player:
        raise RuntimeError(profile.why_not())

    log.info("reading the %s kill feed for %r", profile.label, profile.player)
    events = killfeed.scan(video, profile.band, profile.player,
                           duration=total, fps=profile.scan_fps,
                           progress=progress, cancelled=cancelled)
    if cancelled and cancelled():
        raise Cancelled("scan cancelled")

    kills: list[Kill] = []
    for e in events:
        # Assists are deliberately NOT clipped. CS2 puts your name on a row you
        # only assisted, and counting those would put "3 kills" on a clip where
        # you got one -- so they are detected, reported, and left out.
        if e.kind != "kill":
            continue
        # A feed line has no "marker cleared" moment the way a HUD glyph does,
        # so `end` is the kill itself and the tail is measured from there.
        if kills and e.time - kills[-1].time <= profile.merge_gap:
            kills[-1].count += 1
            kills[-1].end = e.time
            kills[-1].score = max(kills[-1].score, e.ratio)
            continue
        kills.append(Kill(time=e.time, end=e.time, score=e.ratio, count=1))
    deaths = sum(1 for e in events if e.kind == "death")
    assists = sum(1 for e in events if e.kind == "assist")
    log.info("found %d kill(s), %d assist(s) (not clipped) and %d death(s) in %s",
             len(kills), assists, deaths, video.name)
    return kills


class Cancelled(RuntimeError):
    pass


def sample_scores(video: Path, profile: Profile, spans: Iterable[tuple[float, float]],
                  tmpl0: np.ndarray | None = None) -> list[float]:
    """Every per-frame best score across some spans, for the calibrator.

    A template is only trustworthy if kill frames and ordinary frames land in
    clearly separate bands. This returns the raw distribution so the UI can
    show whether that separation exists rather than asserting that it does.
    """
    info = media_info(video)
    geom = band_geometry(info["width"], info["height"], profile)
    (x, y, w, h), (rw, rh) = geom
    if tmpl0 is None:
        tmpl0 = load_template(profile)

    scores: list[float] = []
    for start, dur in spans:
        vf = (f"fps={profile.scan_fps},crop={w}:{h}:{x}:{y},"
              f"scale={rw}:{rh}:flags=bilinear,format=gray")
        raw = ffmpeg_raw(["-ss", f"{start:.3f}", "-i", str(video),
                          "-t", f"{dur:.3f}", "-an", "-sn",
                          "-vf", vf, "-f", "rawvideo", "-"])
        fb = rw * rh
        n = len(raw) // fb if fb else 0
        if not n:
            continue
        frames = np.frombuffer(raw[:n * fb], dtype=np.uint8).reshape(n, rh, rw)
        for i in range(n):
            scores.append(ncc(frames[i].astype(np.float32), tmpl0, 2.0)[0])
    return scores
