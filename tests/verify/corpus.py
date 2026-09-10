"""Build the sample-footage corpus tier 4 measures against.

    .venv\\Scripts\\python.exe tests\\verify\\corpus.py survey
    .venv\\Scripts\\python.exe tests\\verify\\corpus.py build
    .venv\\Scripts\\python.exe tests\\verify\\corpus.py build --extra deltaforceclient.exe=C:\\path\\vod.mp4

Run once, by hand. The output goes to C:\\autostream-testdata (override with
AUTOSTREAM_TESTDATA), never into the repo: the repo is public and these are
someone's own recordings. Only the small reviewed baseline JSON is committed.

WHY EXCERPTS. The recordings this cuts from are 14 to 76 GB at 35-59 Mbps.
Scanning one end to end takes minutes and depends on a file that will be
deleted to make room one day. A hundred seconds around a known burst is the
same footage for the detector's purposes, survives in a fixed place, and lets
the whole of tier 4 finish inside the release budget.

WHERE THE WINDOWS COME FROM. Every past run wrote a session.json listing the
kills it found, so the app has already said where the action is. Those times
are a HINT and nothing more -- they were produced by the detector under test,
so treating them as truth would be marking its own homework. They choose where
to cut; what is actually in each excerpt is decided by review.

FOOTAGE THAT WAS NEVER RECORDED HERE -- a VOD somebody downloaded -- has no
session.json and no sidecar, so there are no hints and both planners return
nothing. That is the ordinary case for testing the clipper the way it is meant
to be used, on a recording made without AutoStream, so `--extra` scans such a
file once to find its own hints. Same status as a session.json's times: they
choose where to cut and nothing else.

Every game also gets a deliberately quiet excerpt. A detector that finds
nothing is only half tested: the other half is a detector that finds things
that are not there, and nothing in this repo tests that today.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from autostream import paths                                   # noqa: E402
from autostream.clips import tools                             # noqa: E402

CORPUS = Path(os.environ.get("AUTOSTREAM_TESTDATA", r"C:\autostream-testdata"))

# Per-game excerpt shape. Delta Force gets longer windows because its VOD is a
# 640x360 download at half a megabit -- three minutes of it is 20 MB, where
# three minutes of a 1080p60 capture is nearly two gigabytes.
@dataclass
class Recipe:
    slug: str
    seconds: int
    wanted: int          # excerpts containing kills
    quiet: int = 1       # excerpts deliberately containing none


RECIPES = {
    "valorant-win64-shipping.exe": Recipe("valorant", 100, 4),
    "cs2.exe": Recipe("cs2", 100, 3),
    "deltaforceclient.exe": Recipe("deltaforce", 180, 4),
}

# Aliases the history may carry for the same game.
ALIASES = {
    "deltaforceclient-win64-shipping.exe": "deltaforceclient.exe",
    "deltaforce-win64-shipping.exe": "deltaforceclient.exe",
    "valorant.exe": "valorant-win64-shipping.exe",
}


@dataclass
class Candidate:
    game_key: str
    video: Path
    duration: float
    hints: list[float] = field(default_factory=list)   # kill times, seconds


# ------------------------------------------------------------- discovery


def _canon(key: str) -> str:
    key = (key or "").strip().lower()
    return ALIASES.get(key, key)


def _probe(video: Path) -> dict | None:
    exe = tools.binary("ffprobe")
    if not exe:
        return None
    out = subprocess.run(
        [exe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-show_entries", "format=duration,bit_rate",
         "-of", "json", str(video)],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        return None
    try:
        d = json.loads(out.stdout)
    except ValueError:
        return None
    s = (d.get("streams") or [{}])[0]
    f = d.get("format") or {}
    return {"width": s.get("width"), "height": s.get("height"),
            "fps": s.get("r_frame_rate"),
            "duration": float(f.get("duration") or 0),
            "bitrate": int(f.get("bit_rate") or 0)}


def discover(extra: dict[str, Path] | None = None) -> list[Candidate]:
    """Recordings still on disk, with whatever the app already knows about them.

    Nothing here is hard-coded to one machine: the paths come out of the user's
    own session journal, which is the same place the Clips page reads them
    from. A recording that has been deleted to make room is skipped rather than
    failing the build.
    """
    found: dict[Path, Candidate] = {}

    for sess in sorted(paths.CLIPS_DIR.glob("*/session.json")):
        try:
            d = json.loads(sess.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        src = Path(d.get("source") or "")
        key = _canon(d.get("game_key") or "")
        if not src.name or key not in RECIPES or not src.is_file():
            continue
        times = sorted({round(float(k.get("time", 0)), 1)
                        for k in (d.get("kills") or []) if k.get("time")})
        c = found.get(src)
        if c is None:
            info = _probe(src)
            if not info or info["duration"] <= 0:
                continue
            c = found[src] = Candidate(key, src, info["duration"])
        # Several runs of the same recording each contribute what they saw.
        # More hints is strictly better: they only decide where to cut.
        c.hints = sorted(set(c.hints) | set(times))

    for key, video in (extra or {}).items():
        key = _canon(key)
        if not video.is_file():
            print(f"  [!!] --extra {key}: no file at {video}")
            continue
        info = _probe(video)
        if not info:
            print(f"  [!!] --extra {key}: ffprobe could not read {video}")
            continue
        c = found.setdefault(video, Candidate(key, video, info["duration"]))
        c.game_key = key
        # A sidecar kills.json beside the video, as the vodclipper prototype
        # wrote. Same status as a session.json: a hint, not truth.
        side = video.parent / "kills.json"
        if side.is_file():
            try:
                raw = json.loads(side.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = []
            times = []
            for k in raw if isinstance(raw, list) else []:
                t = k.get("time") if isinstance(k, dict) else k
                if isinstance(t, (int, float)):
                    times.append(round(float(t), 1))
            c.hints = sorted(set(c.hints) | set(times))
            print(f"  [--] {video.name}: {len(times)} hints from kills.json")
        if not c.hints:
            c.hints = _hints_by_scanning(video, key)

    return list(found.values())


def _hints_by_scanning(video: Path, key: str) -> list[float]:
    """Ask the detector where the action is, for footage with no history.

    A VOD somebody downloaded has no session.json and no sidecar, and BOTH
    window planners start from hints -- so `--extra` on one produced no
    excerpts at all, and said nothing about why. That is the case this exists
    for, and it is the ordinary case for testing the clipper the way it is
    meant to be used: on a recording made without AutoStream.

    Marking its own homework for WINDOW CHOICE only, which is exactly the
    status a session.json's kill times already have -- they were produced by
    the detector under test too. Where to cut is not what these excerpts
    measure: what is actually in one is decided by review, and a kill the
    detector misses inside a window it chose itself is still a miss.
    """
    from autostream.clips import detect, profiles

    prof = profiles.for_game(key)
    if prof is None:
        print(f"  [!!] {video.name}: no profile for {key}, so no hints")
        return []
    if prof.missing():
        print(f"  [!!] {video.name}: {key} is not set up ({prof.missing()}), "
              f"so no hints")
        return []
    print(f"  [--] {video.name}: no history and no kills.json, so scanning it "
          f"once to find where the action is (this is the slow part)",
          flush=True)
    try:
        kills = detect.scan(video, prof)
    except Exception as e:                       # noqa: BLE001
        print(f"  [!!] {video.name}: could not scan it ({type(e).__name__}: "
              f"{e}), so no hints")
        return []
    times = sorted({round(float(k.time), 1) for k in kills})
    print(f"  [--] {video.name}: {len(times)} hints from a scan")
    return times


# ------------------------------------------------------------- planning


def _busy_windows(hints: list[float], length: int, duration: float,
                  want: int) -> list[tuple[float, int]]:
    """Non-overlapping windows, densest first.

    Greedy on purpose: the aim is a handful of excerpts that each contain
    something, not an optimal packing. Each candidate start is placed so a
    hint sits about a quarter of the way in, which leaves room on both sides
    for the pre-roll and tail a real clip would take.
    """
    lead = length * 0.25
    starts = []
    for h in hints:
        s = max(0.0, min(h - lead, duration - length))
        if s >= 0 and s + length <= duration:
            starts.append(round(s, 1))
    scored = []
    for s in sorted(set(starts)):
        n = sum(1 for h in hints if s <= h < s + length)
        scored.append((s, n))
    scored.sort(key=lambda x: (-x[1], x[0]))

    chosen: list[tuple[float, int]] = []
    for s, n in scored:
        if len(chosen) >= want:
            break
        if any(abs(s - c) < length for c, _ in chosen):
            continue          # overlaps one already taken
        chosen.append((s, n))
    return sorted(chosen)


def _quiet_windows(hints: list[float], length: int, duration: float,
                   taken: list[tuple[float, int]], want: int,
                   margin: float = 45.0) -> list[float]:
    """Windows with no hint in them, nor within `margin` of either edge.

    The margin matters: a kill just outside the window still puts its marker
    on screen inside it, and an excerpt like that would score a correct
    detection as a false positive.

    Searched only BETWEEN the first and last hint, never from the top of the
    file. The first minutes of a recording are the desktop, a launcher and a
    main menu -- footage with no kills in it because there is no game in it.
    An excerpt like that proves nothing: the question a quiet excerpt asks is
    whether the detector stays silent through real gameplay, which is where
    a false positive would actually come from.
    """
    out: list[float] = []
    step = max(30.0, length / 2)
    if not hints:
        return out
    first, last = min(hints), max(hints)
    s = first
    if last - first < length + 2 * margin:
        return out          # the action is too tightly packed to sit between
    while s + length <= min(duration, last) and len(out) < want:
        lo, hi = s - margin, s + length + margin
        if not any(lo <= h <= hi for h in hints) \
                and not any(abs(s - c) < length for c, _ in taken) \
                and not any(abs(s - o) < length for o in out):
            out.append(round(s, 1))
            s += length
        else:
            s += step
    return out


# --------------------------------------------------------------- cutting


def cut(video: Path, start: float, length: int, dest: Path) -> dict | None:
    """One excerpt, stream-copied.

    No re-encode. These detectors read pixels -- a HUD colour, a template
    correlation against a threshold, an OCR crop -- and re-encoding would make
    the corpus a measurement of the transcode as much as of the detector.

    Stream copy can only start on a keyframe, so ffmpeg moves the start back
    to the nearest one. The excerpt is its own timeline from then on and the
    requested offset is recorded only as provenance, which is why that
    imprecision does not matter: the baseline is reviewed against the excerpt.
    """
    exe = tools.binary("ffmpeg")
    if not exe:
        print("  [!!] no ffmpeg")
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{start:.3f}", "-i", str(video),
           "-t", str(length), "-c", "copy",
           "-avoid_negative_ts", "make_zero", str(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not dest.is_file():
        print(f"  [!!] ffmpeg failed on {dest.name}: {r.stderr[:300]}")
        return None
    info = _probe(dest)
    if not info or info["duration"] <= 1:
        print(f"  [!!] {dest.name} came out empty")
        dest.unlink(missing_ok=True)
        return None
    return info


# ------------------------------------------------------------- commands


def cmd_survey(args) -> int:
    cands = discover(args.extra)
    if not cands:
        print("No usable recordings found. Nothing in the session journal "
              "points at a file that is still on disk.")
        return 1
    print(f"\n{len(cands)} recording(s) usable:\n")
    for c in sorted(cands, key=lambda c: c.game_key):
        info = _probe(c.video) or {}
        gb = c.video.stat().st_size / 1024 ** 3
        print(f"  {c.game_key}")
        print(f"    {c.video}")
        print(f"    {gb:.1f} GB  {info.get('width')}x{info.get('height')} "
              f"@ {info.get('fps')}  {c.duration / 60:.0f} min  "
              f"{(info.get('bitrate') or 0) / 1e6:.0f} Mbps")
        print(f"    {len(c.hints)} kill hints from past runs")
        rec = RECIPES[c.game_key]
        busy = _busy_windows(c.hints, rec.seconds, c.duration, rec.wanted)
        quiet = _quiet_windows(c.hints, rec.seconds, c.duration, busy, rec.quiet)
        est = (info.get("bitrate", 0) / 8) * rec.seconds * (len(busy) + len(quiet))
        print(f"    would cut {len(busy)} busy + {len(quiet)} quiet "
              f"x {rec.seconds}s  ~= {est / 1024 ** 3:.1f} GB")
        for s, n in busy:
            print(f"        busy  {s / 60:6.1f} min  ({n} hints)")
        for s in quiet:
            print(f"        quiet {s / 60:6.1f} min")
        print()
    return 0


def cmd_build(args) -> int:
    cands = discover(args.extra)
    if not cands:
        print("No usable recordings found.")
        return 1
    CORPUS.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"excerpts": []}
    total = 0

    # One source per game: the densest. Mixing two recordings of the same game
    # doubles the corpus for no extra coverage of the detector.
    by_game: dict[str, Candidate] = {}
    for c in cands:
        best = by_game.get(c.game_key)
        if best is None or len(c.hints) > len(best.hints):
            by_game[c.game_key] = c

    for key, c in sorted(by_game.items()):
        rec = RECIPES[key]
        out_dir = CORPUS / rec.slug
        busy = _busy_windows(c.hints, rec.seconds, c.duration, rec.wanted)
        quiet = _quiet_windows(c.hints, rec.seconds, c.duration, busy, rec.quiet)
        print(f"\n{key}: {len(busy)} busy + {len(quiet)} quiet excerpts")

        plan = [(s, n, "busy") for s, n in busy] + [(s, 0, "quiet") for s in quiet]
        for i, (start, hints_in, kind) in enumerate(sorted(plan), 1):
            name = f"{rec.slug}_{i:02d}_{kind}.mp4"
            dest = out_dir / name
            if dest.is_file() and not args.force:
                print(f"  [--] {name} already there")
                info = _probe(dest) or {}
            else:
                print(f"  [--] cutting {name} at {start / 60:.1f} min ...")
                info = cut(c.video, start, rec.seconds, dest)
                if info is None:
                    continue
            size = dest.stat().st_size
            total += size
            manifest["excerpts"].append({
                "clip": dest.stem,
                "game_key": key,
                "game": rec.slug,
                "file": str(dest.relative_to(CORPUS)).replace("\\", "/"),
                "kind": kind,
                # Provenance only. The excerpt is its own timeline: stream
                # copy snaps the start back to a keyframe, so this is where
                # the cut was ASKED for, not where it landed.
                "source_name": c.video.name,
                "source_offset": start,
                "hints_in_window": hints_in,
                "seconds": round(info.get("duration", 0), 2),
                "width": info.get("width"),
                "height": info.get("height"),
                "bytes": size,
            })
            print(f"       {size / 1024 ** 2:.0f} MB  "
                  f"{info.get('duration', 0):.0f}s  "
                  f"{info.get('width')}x{info.get('height')}")

    (CORPUS / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n{len(manifest['excerpts'])} excerpts, "
          f"{total / 1024 ** 3:.1f} GB, in {CORPUS}")
    print("Next: score them, then review the result before it becomes a baseline.")
    return 0


def _extra(values: list[str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for v in values or []:
        key, _, path = v.partition("=")
        if not path:
            raise SystemExit(f"--extra wants game_key=path, got {v!r}")
        out[key] = Path(path)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    for name, fn in (("survey", cmd_survey), ("build", cmd_build)):
        p = sub.add_parser(name)
        p.add_argument("--extra", action="append", default=[],
                       help="game_key=path/to/video.mp4, for footage the "
                            "session journal does not know about")
        p.add_argument("--force", action="store_true",
                       help="re-cut excerpts that are already there")
        p.set_defaults(func=fn)
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 1
    args.extra = _extra(args.extra)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
