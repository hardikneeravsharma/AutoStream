"""Teach AutoStream a new game's kill marker.

THE IDEA
    Pick a frame where the marker is on screen, drag a box round it, and that
    patch becomes the template. The band searched at scan time is that box
    widened sideways, because most games draw multi-kills as several markers
    spreading out from a centre.

WHY IT REPORTS A SCORE DISTRIBUTION INSTEAD OF JUST SAYING "SAVED"
    A template is only worth anything if frames WITH the marker score clearly
    higher than frames without it. That gap is the whole detector. Delta Force
    works because kills land at 0.78-0.91 while everything else tops out at
    0.74 -- and the only way to know a new template has a gap like that is to
    measure it. So calibration ends by scoring frames near the chosen moment
    against frames far from it, and reporting what it found rather than
    asserting success.

RESOLUTION
    The template is saved with the height of the frame it was cut from. Every
    later scan rescales to that height before matching, which is what lets one
    template work on a 1080p recording and a 1440p one. Nothing else in the
    system recovers from getting this wrong -- a mismatched scale finds zero
    kills and looks exactly like a game with no kills in it.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .. import paths
from . import detect
from .profiles import Profile, save, save_username, slug
from .tools import ffmpeg_raw, media_info

log = logging.getLogger("autostream.clips.calibrate")

# How far past the box to search at scan time, as a multiple of its width.
# 2.5x fits roughly four markers side by side, which covers the multi-kills
# any of these games actually draw.
BAND_WIDEN = 2.5

# Vertical slack around the box. Small: these HUD elements do not move
# vertically, and a taller band is only more chances to match something else.
BAND_PAD_Y = 0.35

MIN_BOX_PX = 8

# A kill marker is a HUD glyph. Nothing plausible covers more than a few
# percent of the frame, and a large box both matches loosely and makes the
# per-position search enormous. Rejecting it here is a domain fact, not a
# performance tweak.
MAX_BOX_AREA = 0.06
MAX_BOX_SIDE = 0.35


def _grab_gray(video: Path, at: float, box, height: int, width: int) -> np.ndarray:
    """The boxed region of one frame, greyscale, at native scale."""
    x1, y1, x2, y2 = box
    x = int(round(width * x1))
    y = int(round(height * y1))
    w = max(1, int(round(width * x2)) - x)
    h = max(1, int(round(height * y2)) - y)
    raw = ffmpeg_raw(["-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1",
                      "-an", "-sn", "-vf", f"crop={w}:{h}:{x}:{y},format=gray",
                      "-f", "rawvideo", "-"])
    if len(raw) < w * h:
        raise RuntimeError("could not read that frame")
    return np.frombuffer(raw[:w * h], dtype=np.uint8).reshape(h, w).astype(np.float32)


def _band_from_box(box) -> tuple[float, float, float, float]:
    """Widen the drawn box into the band the scan will search."""
    x1, y1, x2, y2 = box
    cx = (x1 + x2) / 2
    half = max(1e-4, (x2 - x1) / 2) * BAND_WIDEN
    padh = (y2 - y1) * BAND_PAD_Y
    return (max(0.0, cx - half), max(0.0, y1 - padh),
            min(1.0, cx + half), min(1.0, y2 + padh))


def from_request(body: dict) -> dict:
    """Handle a calibration POST. -> a JSON-able result dict."""
    src = Path(str(body.get("path") or ""))
    if not src.exists():
        return {"error": "That recording is no longer on disk."}

    try:
        at = float(body.get("t") or 0)
        box = tuple(float(v) for v in (body.get("box") or []))
    except (TypeError, ValueError):
        return {"error": "Bad selection."}
    if len(box) != 4:
        return {"error": "Drag a box around the kill marker first."}

    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return {"error": "That selection has no area."}

    label = str(body.get("label") or "").strip()
    key = str(body.get("key") or "").strip().lower()
    if not label:
        return {"error": "Give the game a name."}
    if not key:
        key = slug(label) + ".exe"

    info = media_info(src)
    W, H = info["width"], info["height"]

    # A killfeed game is calibrated by drawing the FEED, not a marker, so it
    # skips every check below -- those exist to reject a box too big to be a
    # HUD glyph, and here a big box is the correct answer.
    if str(body.get("mode") or "").lower() == "killfeed":
        return _killfeed_request(body, src, box, at, label, key, W, H)
    bw, bh = (x2 - x1) * W, (y2 - y1) * H
    if bw < MIN_BOX_PX or bh < MIN_BOX_PX:
        return {"error": f"That box is only {bw:.0f}x{bh:.0f} pixels. Draw it "
                         f"tightly around the marker, but at least "
                         f"{MIN_BOX_PX}x{MIN_BOX_PX}."}
    if ((x2 - x1) * (y2 - y1) > MAX_BOX_AREA
            or (x2 - x1) > MAX_BOX_SIDE or (y2 - y1) > MAX_BOX_SIDE):
        return {"error": "That box covers too much of the screen to be a kill "
                         "marker. Draw it around the marker itself - usually a "
                         "small icon near the middle or the crosshair."}

    try:
        patch = _grab_gray(src, at, box, H, W)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not read that frame: {e}"}

    if float(patch.std()) < 4.0:
        # A flat patch correlates with everything and nothing. Catching it here
        # beats saving a profile that fires on every frame of the game.
        return {"error": "That patch is almost featureless, so it would match "
                         "anything. Draw the box around the marker itself."}

    band = _band_from_box(box)
    template_name = f"{slug(label)}.npy"
    paths.CLIP_TEMPLATES.mkdir(parents=True, exist_ok=True)
    np.save(paths.CLIP_TEMPLATES / template_name, patch)

    profile = Profile(
        key=key, label=label, band=band, template=template_name,
        ref_height=H, match_min=float(body.get("match_min") or 0.75),
        notes=f"Calibrated from {src.name} at {at:.1f}s, {W}x{H}.",
    )

    report = evaluate(src, profile, at)
    if report.get("suggested"):
        profile.match_min = report["suggested"]

    # A template that cannot tell the marker from ordinary frames is worse than
    # no profile at all: with no profile the page says "not calibrated" and the
    # user knows where they stand, whereas a bad one produces a confident list
    # of clips containing nothing. So it is reported and discarded, not saved.
    if report.get("separation") == "bad":
        (paths.CLIP_TEMPLATES / template_name).unlink(missing_ok=True)
        return {"ok": False, "saved": False, "label": label,
                "patch": [int(patch.shape[1]), int(patch.shape[0])], **report}

    save(profile)
    return {
        "ok": True,
        "saved": True,
        "key": profile.key,
        "label": profile.label,
        "band": list(band),
        "ref_height": H,
        "match_min": profile.match_min,
        "patch": [int(patch.shape[1]), int(patch.shape[0])],
        **report,
    }


def _killfeed_request(body: dict, src: Path, box, at: float, label: str,
                      key: str, W: int, H: int) -> dict:
    """Calibrate a game whose kills are READ rather than matched.

    There is no template to cut and no correlation to threshold, so what has to
    be proved is different: that the name is legible in the box that was drawn.
    A profile that cannot read the name would report a clean "no kills found",
    which is the worst possible failure -- indistinguishable from a quiet game.
    So the name is looked for before anything is saved.
    """
    from . import killfeed as kf

    player = str(body.get("player") or "").strip()
    if not player:
        return {"error": "Type your in-game name exactly as it appears in the "
                         "kill feed - that is what tells your kills from "
                         "everyone else's."}
    if len(player) < kf.MIN_NAME_LEN:
        return {"error": f"That name is too short to find reliably. Names under "
                         f"{kf.MIN_NAME_LEN} characters get lost in the noise "
                         f"the feed's icons produce."}

    band = tuple(float(v) for v in box)          # the drawn box IS the band
    try:
        kf.tesseract()
    except kf.TesseractMissing as e:
        return {"error": str(e)}

    # Sample around the chosen moment rather than only at it. A feed row lives
    # a few seconds, so the frame the user paused on and its neighbours should
    # all contain the name; needing only one to succeed tolerates a seek
    # landing a moment early.
    window = [at + d for d in (-2.0, -1.0, 0.0, 1.0, 2.0) if at + d >= 0]
    seen = []
    for t in window:
        try:
            got = kf._sightings(src, band, player, t, 0.9, 1.0, 1)
        except Exception as e:  # noqa: BLE001
            return {"error": f"Could not read that frame: {e}"}
        seen.extend(got)

    if not seen:
        return {"ok": False, "saved": False, "label": label, "mode": "killfeed",
                "separation": "bad",
                "note": f"{player!r} was not readable anywhere in that box "
                           f"between {window[0]:.0f}s and {window[-1]:.0f}s. "
                           f"Check the spelling, and make sure the box covers "
                           f"the whole feed including the names at both ends."}

    best = max(seen, key=lambda e: e.ratio)
    profile = Profile(
        key=key, label=label, band=band, template="", ref_height=H,
        mode="killfeed", scan_fps=1.0,
        match_ratio=float(body.get("match_ratio") or kf.MATCH_RATIO),
        player=player,
        notes=f"Kill feed read from {src.name} at {at:.1f}s, {W}x{H}. "
              f"Name left of the weapon icon is a kill, right of it a death.",
    )
    save(profile)
    # The profile does not carry the name -- as_dict() leaves `player` out on
    # purpose -- so without this the name that was just proved readable would be
    # thrown away and the next scan would find nothing.
    kept = save_username(profile.key, player, label)
    return {
        "ok": True, "saved": True, "key": profile.key, "label": label,
        "mode": "killfeed", "band": list(band), "ref_height": H,
        "player": player, "name_saved": kept,
        "match_ratio": profile.match_ratio,
        "separation": "good" if best.ratio >= 0.9 else "ok",
        "read": best.text, "score": round(best.ratio, 3),
        "kind": best.kind, "hits": len(seen), "sampled": len(window),
        "note": f"Read {best.text!r} at {best.ratio:.0%} in {len(seen)} of "
                f"{len(window)} frames, scored as a {best.kind}."
                + ("" if kept else
                   f" The name could NOT be saved to games.yaml, so add "
                   f"{player!r} there by hand under {profile.key!r} or the "
                   f"next scan will find nothing."),
    }


def evaluate(video: Path, profile: Profile, at: float) -> dict:
    """Judge a template by what it actually detects across the recording.

    THE OBVIOUS TEST DOES NOT WORK, so this does something else.

    The tempting check is "score frames with the marker against frames
    without". It cannot be done: nothing knows which frames have the marker
    except the detector being tested, and kills are not rare. At roughly one
    kill every thirty seconds, any blindly sampled set of "ordinary" frames is
    several percent real markers, so its top decile IS the marker and the
    measured ceiling comes out as high as the signal. Tried against the
    known-good Delta Force template -- validated at 219 kills with clean
    separation -- that test graded it "bad".

    What is measurable without ground truth is the DETECTION RATE. Sample
    several minutes spread across the recording and count how many frames the
    template would fire on:

        fires on almost everything  -> the patch is featureless or generic
        fires on nothing            -> wrong scale, wrong spot, or too strict
        fires on a small minority   -> it is picking something specific out

    That last case is what a real marker looks like, and the number is
    something a person can sanity-check against their own game.
    """
    info = media_info(video)
    total = info["duration"] or 0.0
    tmpl0 = np.load(profile.template_path()).astype(np.float32)
    tmpl0 = tmpl0 - tmpl0.mean()

    at_frame = detect.sample_scores(video, profile, [(max(0.0, at - 0.5), 1.5)], tmpl0)
    spots = [total * f for f in (0.08, 0.2, 0.32, 0.44, 0.56, 0.68, 0.8, 0.92)]
    spread = detect.sample_scores(video, profile, [(t, 8.0) for t in spots], tmpl0)

    if not at_frame or len(spread) < 30:
        return {"separation": None, "suggested": None,
                "note": "Not enough of the recording to judge this template."}

    arr = np.asarray(spread, dtype=np.float32)
    here = float(max(at_frame))
    floor = float(np.median(arr))

    # Threshold sits between the everyday level and what the marker scores.
    # Biased towards the marker: a miss costs one clip, a false positive costs
    # a clip of nothing.
    suggested = round(max(0.55, min(0.95, floor + 0.65 * (here - floor))), 2)
    rate = float((arr >= suggested).mean())
    minutes = len(arr) / max(profile.scan_fps, 0.1) / 60.0
    per_min = rate * len(arr) / max(minutes, 1e-6)

    if here - floor < 0.12:
        verdict = "bad"
        suggested = None
        note = (f"The marker only scores {here:.2f} where the rest of the screen "
                f"already sits at {floor:.2f}. It is not distinct enough to find. "
                f"Try a frame where the marker is fully drawn, or a tighter box.")
    elif rate > 0.25:
        verdict = "bad"
        suggested = None
        note = (f"This would fire on {rate * 100:.0f}% of the recording, which "
                f"is far too much to be a kill marker. The box is probably "
                f"picking up background rather than the marker itself.")
    elif rate <= 0.0005:
        verdict = "bad"
        suggested = None
        note = (f"Scored {here:.2f} on the frame you picked but matched nothing "
                f"across {minutes:.0f} minutes elsewhere. That usually means the "
                f"box caught something that only appears in that one frame.")
    # A popup stays on screen for a few seconds, so one kill produces several
    # matching frames which merge_gap later collapses into one. Dividing by
    # that keeps the estimate honest -- quoting the raw frame rate would
    # overstate the kill count by roughly four times.
    est_kills = per_min * (1.0 / max(profile.scan_fps * profile.merge_gap, 1.0))

    if rate > 0.08:
        verdict = "weak"
        note = (f"The marker scores {here:.2f} against a background of "
                f"{floor:.2f}, but this matches {rate * 100:.0f}% of frames -- "
                f"roughly {est_kills:.0f} kills a minute. Usable if your game "
                f"really is that busy; otherwise draw a tighter box.")
    else:
        verdict = "good"
        note = (f"Looks right: the marker scores {here:.2f} where the rest of "
                f"the screen sits at {floor:.2f}. Across {minutes:.0f} minutes "
                f"sampled elsewhere it would find about {est_kills:.1f} kills a "
                f"minute.")

    return {
        "separation": verdict,
        "note": note,
        "marker_score": round(here, 3),
        "background": round(floor, 3),
        "hit_rate": round(rate, 4),
        "per_minute": round(per_min, 2),
        "suggested": suggested,
        "sampled": int(arr.size),
    }
