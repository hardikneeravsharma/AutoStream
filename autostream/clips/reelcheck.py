"""What a finished reel is checked against, before anyone is shown it.

WHY THIS EXISTS. Every real defect found in the first Follow-the-song reels was
found by measuring the render -- three kills under a blur, a kill whited out, a
clip played twice, a 20-second shot, a last kill under the ending fade -- and
every one of those measurements was run by hand. A reviewer (ChatGPT, asked to
rate the roadmap) put it plainly: build the gate before the wizard, because a
guided flow on top of an engine that sometimes makes a bad reel only makes bad
reels easier to make. This is the gate, in three layers kept apart:

* the PLAN checks (`plan_findings`) read the project and what derive() says of
  it -- no ffmpeg, so the check engine can run them on a plan it has not
  rendered, and a test can run them on a hand-built one;
* the RENDER checks (`render_findings`) read the finished file: it decodes, it
  is as long as the plan, every kill frame has detail;
* a finding is HARD (the reel is not shown as ready) or SOFT (said only when
  there is something to do about it). A check that could not run is a hard
  finding of its own -- not evidence of quality.

Nothing here scores a reel. A handful of independent checks, each with a
reason, is what can be acted on.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

from . import rulebook

log = logging.getLogger(__name__)

HARD, SOFT = "hard", "soft"

# What the checks compare against. Each number is a measurement, not a taste:
FAST_MAX_SHOT = 6.0        # s. The Notorious reel's 20 s shot; a build take's shots run to 3 s
FAST_MAX_GAP = 1.0         # s between two kills after the drop (director.MAX_GAP)
SHARP_MIN = 0.35           # a kill frame's detail vs the reel's median: three blurred kills read 0.00-0.17
SHARP_RADIUS = (2, 5)      # frames before and after the kill whose median must clear SHARP_MIN
LENGTH_TOLERANCE = 0.25    # s a render may differ from the plan
REEL_FPS = 60              # studio.FPS: what every shot is cut and checked at
# A FRAME THE VIEWER SEES AS A FAULT. ChatGPT's review of the first Fast-paced headshot
# render found a whole black frame just before the drop kill and a reel that ended on
# a frame burnt almost white; both passed every check there was. Mean grey, 0-255,
# over the game's own picture: a frame under BLACK_MAX between pictures brighter
# than BLACK_AROUND is a black flash, and a last frame over WHITE_END is a white end.
BLACK_MAX = 4.0
BLACK_AROUND = 20.0
WHITE_END = 225.0
# ...and one too bright to look at: ChatGPT's general rule after a flip lit 31 % of the
# picture above 245 -- no more than BRIGHT_SHARE of the game's pixels over BRIGHT_LEVEL
# for BRIGHT_FRAMES frames running. Said, not blocked: a flashbang in the footage is one.
BRIGHT_LEVEL = 245
BRIGHT_SHARE = 0.20
BRIGHT_FRAMES = 2
MAX_FROM_ONE_FILE = 4      # R13: no file gives a reel more shots than this
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class Finding:
    level: str            # HARD or SOFT
    code: str             # a short stable name tests and the page can key on
    message: str          # one sentence for the person
    at: float | None = None   # reel seconds, when it is about a moment

    def as_dict(self) -> dict:
        return asdict(self)


def ready(findings: list[Finding]) -> bool:
    """Whether the reel may be shown as ready: no hard finding."""
    return not any(f.level == HARD for f in findings)


# ------------------------------------------------------------------ the plan

def plan_findings(project: dict, derived: dict, *, fast: bool = True) -> list[Finding]:
    """Checks that need no render. `fast` is the style's reuse rule: a clip appears
    once (fast styles), or a file may give several shots but never the same fight
    twice and never back to back (the slower ones)."""
    out: list[Finding] = []
    shots = project.get("shots") or []
    rows = derived.get("shots") or []
    if not shots:
        return [Finding(HARD, "no-shots", "The reel has no shots.")]

    # every kill on its mark
    marks = derived.get("marks") or []
    if marks:
        for r in rows:
            d = r.get("drift")
            if d is not None and abs(d) > derived.get("on_mark_window", 0.05):
                out.append(Finding(HARD, "off-mark", f"A kill is {abs(d) * 1000:.0f} ms from its beat.", r.get("kill_reel")))

    # a clip, or a fight, shown twice
    by_clip: dict[str, list[int]] = {}
    for i, s in enumerate(shots):
        by_clip.setdefault(str(s["clip"]).lower(), []).append(i)
    for clip, idx in by_clip.items():
        if len(idx) < 2:
            continue
        name = Path(clip).stem
        if fast:
            lead = [i for i in idx if not _same_take(shots, idx[0], i)]
            if lead:
                out.append(Finding(HARD, "repeat", f"{name} is used twice.", rows[idx[1]]["kill_reel"] if rows else None))
        else:
            # Against the kills of the clip's OTHER shots only. A double kill is two
            # kills of one fight in ONE shot -- shown once -- and comparing each shot's
            # kills with each other flagged it: five of the eight repeat-fight findings
            # on the Velocity reel of Skechers were a double kill inside one shot.
            seen: list[float] = []
            for i in idx:
                own = [float(k) for k in shots[i].get("kills") or []]
                if any(abs(k - p) < rulebook.REPEAT_FIGHT_GAP for k in own for p in seen):
                    out.append(Finding(HARD, "repeat-fight", f"The same fight in {name} is shown twice.", rows[i]["kill_reel"]))
                seen += own
            if any(b - a == 1 for a, b in zip(idx, idx[1:])) and not all(_same_take(shots, idx[0], i) for i in idx):
                out.append(Finding(SOFT, "back-to-back", f"{name} plays twice in a row.", rows[idx[0]]["kill_reel"]))
            if len(idx) > MAX_FROM_ONE_FILE:
                out.append(Finding(HARD, "too-many-from-one", f"{name} gives {len(idx)} shots (the limit is {MAX_FROM_ONE_FILE}).", None))

    # one very long shot in a fast style
    if fast:
        for i, s in enumerate(shots):
            if float(s["duration"]) > FAST_MAX_SHOT and i not in _take_indexes(shots):
                out.append(Finding(HARD, "long-shot", f"One shot runs {float(s['duration']):.0f} s in a fast-cut reel.", rows[i]["start"] if rows else None))

    # the ending
    kills = derived.get("kills") or []
    if kills:
        length = float(derived.get("length") or 0.0)
        fade = float(derived.get("outro_fade") or 0.0)
        from . import studio
        if fade and length - fade < max(kills) + studio.OUTRO_AFTER_KILL - 1e-3:
            out.append(Finding(HARD, "fade-over-kill", "The ending fade starts before the last kill has played.", max(kills)))
        if length - max(kills) < 0.3:
            out.append(Finding(HARD, "no-room-after-kill", "The reel ends within a third of a second of its last kill.", max(kills)))

    out += style_findings(project, derived)

    # pace after the drop
    drop = project.get("song_drop")
    # Fast-paced headshot holds a cut of about a second by design (clips/fasthead.py)
    if fast and drop is not None and kills and project.get("style") not in ("fasthead", "montage"):
        off = float(project.get("song_offset") or 0.0)
        after = [k for k in kills if k > float(drop) - off + 0.01]
        for a, b in zip(after, after[1:]):
            if b - a > FAST_MAX_GAP + 1e-6:
                out.append(Finding(SOFT, "slow-pace", f"{b - a:.1f} s between two kills after the drop.", a))
    return out


# ------------------------------------------------------------- the style itself
#
# ChatGPT's second review (Hype 6.4/10, Velocity 6.2/10): a reel can pass every
# check above and still not be its style. These measure what the style promises.

PACE_MEDIAN = 0.15         # the median shot within this share of the references'
PACE_CPM = 0.10            # ...and the cuts a minute within this
PACE_MIN_SHOTS = 8         # fewer shots than this have no median worth the name
DIRECTED = ("drop", "fasthead", "montage")   # planned by the director, to their own specifications
VEL_SLOW_BAND = (0.45, 0.75)   # "roughly 0.5-0.7x" through the impact
VEL_SLOW_SHARE = 0.90          # of the kills
VEL_FAST = 1.3                 # the rush between kills, at least
VEL_FAST_SHARE = 0.70          # of the time between them (ChatGPT's third review: 70%)
VEL_WINDOW = 0.06              # s either side of the kill the slow rate is read over
VEL_CLEAR = 0.20               # s either side of a kill that is not "between kills"
SIGNATURE_SHARE = 0.95
QUARTILE_TOLERANCE = 0.20      # provisional: each quartile within this of the references'
KILL_BRIGHT_SHARE = 0.20       # of the gameplay pixels over BRIGHT_LEVEL...
KILL_BRIGHT_FRAMES = 2         # ...for this many frames running, near a kill
KILL_WINDOW = (6, 12)          # frames before and after a kill the brightness is read over
INTENDED_BRIGHT = ("k03", "k16")   # kill effects meant to white out: the white flash, the flicker
REAL_SPEED = (0.95, 1.05)      # a rate that reads as real speed (Clean's review)
OPEN_AT = 15                   # the frame a quarter of a second in, at REEL_FPS...
OPEN_BLACK = 0.50              # ...no more than this share of the picture near-black...
NEAR_BLACK = 24                # ...below this level of 255


def _rate(pieces: list, t0: float, t1: float) -> float:
    """Source seconds per output second over [t0, t1] of a shot's pieces."""
    src = 0.0
    for a, b, r in pieces:
        lo, hi = max(a, t0), min(b, t1)
        if hi > lo:
            src += (hi - lo) * float(r)
    return src / max(1e-6, t1 - t0)


def style_findings(project: dict, derived: dict) -> list[Finding]:
    """Pace against the references (soft), Velocity's speed shape and Hype's signature (hard)."""
    from . import studio, studio_refs

    out: list[Finding] = []
    shots = project.get("shots") or []
    rows = derived.get("shots") or []
    st = studio.STYLE.get(project.get("style") or "")
    if not st or not shots or not rows:
        return out
    # PACE: the median shot and the cuts a minute against the references' own --
    # both, because one gap for every shot made the cuts a minute right with every
    # shot 1.5x the median. Soft: a limit the plan names is said with it.
    ref = studio_refs.summary(st.refs) if st.refs else {}
    if st.key not in DIRECTED and ref.get("median_shot") and len(shots) >= PACE_MIN_SHOTS:
        pace = float((project.get("shaping") or {}).get("pace") or 1.0)
        want_med = float(ref["median_shot"]) / pace
        want_cpm = float(ref["cuts_per_min"]) * pace
        durs = sorted(float(s["duration"]) for s in shots)
        med = durs[len(durs) // 2] if len(durs) % 2 else (durs[len(durs) // 2 - 1] + durs[len(durs) // 2]) / 2
        cpm = 60.0 * len(shots) / max(1e-6, float(derived.get("length") or 0.0))
        why = "; ".join((project.get("pace") or {}).get("limits") or [])
        if abs(med / want_med - 1) > PACE_MEDIAN:
            out.append(Finding(SOFT, "pace-median", f"The median shot is {med:.2f} s; {st.label}'s references "
                               f"hold {want_med:.2f} s." + (f" ({why})" if why else "")))
        if abs(cpm / want_cpm - 1) > PACE_CPM:
            out.append(Finding(SOFT, "pace-cuts", f"{cpm:.0f} cuts a minute; {st.label}'s references cut "
                               f"{want_cpm:.0f}." + (f" ({why})" if why else "")))
    # VELOCITY: slow through every impact, fast between them, measured off the
    # speed the render plays (each row's pieces).
    if st.speed_profile == "velocity":
        slow = n = 0
        fast_t = between_t = 0.0
        for s, r in zip(shots, rows):
            if r.get("lead_in"):
                continue
            ps = r.get("pieces") or [[0.0, float(s["duration"]), 1.0]]
            k = float(r["kill_reel"]) - float(r["start"])
            n += 1
            lo_, hi_ = VEL_SLOW_BAND
            if lo_ <= _rate(ps, max(0.0, k - VEL_WINDOW), k + VEL_WINDOW) <= hi_:
                slow += 1
            ks = [float(x) - float(r["start"]) for x in r.get("kills_reel") or []] or [k]
            # A transition is centred on its cut: half of it at this shot's head, and
            # half of the next one's at its tail.
            head_t = float(s.get("tlen") or 0.0) / 2
            nxt = shots[shots.index(s) + 1] if s is not shots[-1] else {}
            tail_t = float(s["duration"]) - float(nxt.get("tlen") or 0.0) / 2
            t, step = 0.0, 1.0 / REEL_FPS
            while t < float(s["duration"]) - 1e-9:
                if all(abs(t - x) > VEL_CLEAR for x in ks) and head_t <= t <= tail_t:
                    between_t += step
                    if _rate(ps, t, t + step) >= VEL_FAST - 1e-6:
                        fast_t += step
                t += step
        # (the frames of a transition are excluded too: a cut is not footage between kills)
        if n and slow / n < VEL_SLOW_SHARE:
            out.append(Finding(HARD, "velocity-slow", f"{slow} of {n} kills slow to "
                               f"{VEL_SLOW_BAND[0]:g}-{VEL_SLOW_BAND[1]:g}x through the impact; Velocity needs "
                               f"{VEL_SLOW_SHARE:.0%}."))
        if between_t and fast_t / between_t < VEL_FAST_SHARE:
            out.append(Finding(HARD, "velocity-fast", f"{fast_t / between_t:.0%} of the footage between kills "
                               f"runs at {VEL_FAST:g}x or more; Velocity needs {VEL_FAST_SHARE:.0%}."))
    # THE SIGNATURE (Hype's shake) on every kill the readability guard allows.
    if st.signature:
        sig = studio.fam(st.signature[0])
        eligible = [s for s in shots if not s.get("signature_off")]
        has = sum(1 for s in eligible if any(studio.fam(f) == sig for f in s.get("fx") or []))
        if eligible and has / len(eligible) < SIGNATURE_SHARE:
            out.append(Finding(HARD, "signature", f"{has} of {len(eligible)} kills have {st.label}'s "
                               f"{studio.PART[st.signature[0]].label.lower()}."))
    # THE GRADE ON EVERY SHOT, BY ITS ID (ChatGPT's third review of Hype, every style): read
    # off what each shot's render is handed (segments), never off its colour -- the saturation
    # trim and a clip's own colours move how graded a shot looks while it IS graded, and a
    # colour test failed shots that were right. A shot handed another grade, or none, fails.
    # The reel's grade is the style's unless the player chose another: that is said, not failed.
    try:
        graded = [g.grade for g in studio.segments(project, derived, has_audio=lambda p: True)]
    except Exception as e:                                     # noqa: BLE001
        out.append(Finding(HARD, "grade", f"The grade each shot is rendered with could not be read ({e})."))
        graded = None
    if graded is not None:
        want = project.get("grade") or ""
        wrong = sum(1 for g in graded if g != want) + abs(len(shots) - len(graded))
        if want not in studio.PART or wrong:
            out.append(Finding(HARD, "grade", f"{wrong or len(shots)} of {len(shots)} shots go out without "
                               f"the reel's grade ({studio.PART[want].label if want in studio.PART else want or 'none'})."))
        elif want != st.grade:
            out.append(Finding(SOFT, "grade-chosen", f"Graded {studio.PART[want].label}, not {st.label}'s own "
                               f"{studio.PART[st.grade].label}: the grade chosen for this reel."))
    # RESTRAINT AS A SIGNATURE (Clean, from ChatGPT's review): what the style leaves out,
    # measured the way Hype's shake and Velocity's shape are. studio.restrain_speed and
    # restrain_look hold a plan to it, so a finding here is a plan that slipped past them.
    if st.real_speed:
        real = sum(1 for r in rows if all(rt == 0 or REAL_SPEED[0] <= rt <= REAL_SPEED[1]
                                          for _a, _b, rt in r.get("pieces") or []))
        if real / len(rows) < st.real_speed - 1e-9:
            out.append(Finding(HARD, "calm-speed", f"{real} of {len(rows)} shots play at real speed; "
                               f"{st.label} needs {st.real_speed:.0%}."))
    if st.kill_fx_max:
        heavy = sum(1 for s in shots if len(s.get("fx") or []) > st.kill_fx_max)
        if heavy:
            out.append(Finding(HARD, "calm-effects", f"{heavy} kill(s) carry more than {st.kill_fx_max} "
                               f"effect(s); {st.label} gives each kill one soft treatment."))
    cuts = shots[1:]
    if cuts and st.crossfade_max < 1.0:
        blends = sum(1 for s in cuts if s.get("transition") not in ("t01", "t02", None))
        if blends / len(cuts) > st.crossfade_max + 1e-9:
            out.append(Finding(HARD, "calm-blends", f"{blends} of {len(cuts)} cuts are blends; {st.label} "
                               f"keeps them to {st.crossfade_max:.0%}."))
    if cuts and st.flash_cap and ref.get("flashes_per_min") and float(derived.get("length") or 0.0) > 0:
        rate = 60.0 * sum(1 for s in cuts if s.get("transition") == "t02") / float(derived["length"])
        cap = float(ref["flashes_per_min"]) * st.flash_cap
        if rate > cap + 1e-9:
            out.append(Finding(SOFT, "flash-rate", f"{rate:.1f} white flashes a minute; {st.label}'s references "
                               f"flash {float(ref['flashes_per_min']):.1f}, at most {cap:.1f}."))
    if st.drift_max:
        moving = sum(1 for s in shots if studio.drift_of(s.get("camera") or "c00") > st.drift_max + 1e-9)
        if moving:
            out.append(Finding(HARD, "calm-camera", f"{moving} shot(s) move the camera more than "
                               f"{st.drift_max:.0%}; {st.label}'s camera barely breathes."))
    # QUARTILES (provisional): only where the references were measured for them.
    if st.key not in DIRECTED and all(q in ref for q in studio_refs.QUARTILES) and len(shots) >= PACE_MIN_SHOTS:
        beat = float(project.get("beat") or 0.5)
        durs = sorted(float(s["duration"]) / beat for s in shots)
        for q, f in zip(studio_refs.QUARTILES, (0.25, 0.5, 0.75)):
            got = durs[min(len(durs) - 1, int(f * (len(durs) - 1) + 0.5))]
            if abs(got / float(ref[q]) - 1) > QUARTILE_TOLERANCE:
                out.append(Finding(SOFT, "pace-quartile", f"The {q[1:3]}th-percentile shot is {got:.2f} beats; "
                                   f"the references' is {float(ref[q]):.2f}."))
    # THE KILL COUNTER ticks once for every kill the reel shows, and on it.
    if "o02" in (project.get("overlays") or []):
        shown = sorted(round(float(k), 3) for r in rows for k in r.get("kills_reel") or [])
        ticks = sorted(round(float(k), 3) for k in derived.get("kills") or [])
        missing = [r for r in rows if not r.get("lead_in")
                   and not any(abs(float(k) - float(r["kill_reel"])) < 1.5 / REEL_FPS for k in r.get("kills_reel") or [])]
        if shown != ticks or missing or len(set(ticks)) != len(ticks):
            out.append(Finding(HARD, "kill-counter", f"The kill counter ticks {len(ticks)} times for "
                               f"{len(shown)} kills shown" + (f"; {len(missing)} shot(s) do not count their own kill."
                                                              if missing else ".")))
    return out


def _take_indexes(shots: list[dict]) -> set[int]:
    """The shots of the opening take: consecutive shots of one clip from the first shot on."""
    if not shots:
        return set()
    first = shots[0]["clip"]
    n = 0
    while n < len(shots) and shots[n]["clip"] == first:
        n += 1
    return set(range(n))


def _same_take(shots: list[dict], a: int, b: int) -> bool:
    take = _take_indexes(shots)
    return a in take and b in take


# ---------------------------------------------------------------- the render

def _lap(frames) -> list[float]:
    import numpy as np

    return [float(np.var(f[1:-1, 1:-1] * 4 - f[:-2, 1:-1] - f[2:, 1:-1] - f[1:-1, :-2] - f[1:-1, 2:])) for f in frames]


def _frames(ff: str, mp4: Path, crop: str, size: tuple[int, int]):
    import numpy as np

    w, h = size
    raw = subprocess.run([ff, "-v", "error", "-nostdin", "-i", str(mp4), "-vf", f"{crop},scale={w}:{h},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, creationflags=_NO_WINDOW, timeout=900).stdout
    n = len(raw) // (w * h)
    return np.frombuffer(raw[:n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)


def render_findings(mp4: Path, project: dict, derived: dict, ff: str = "ffmpeg") -> list[Finding]:
    """Checks on the finished file. Any failure to check is itself a hard finding."""
    out: list[Finding] = []
    try:
        mp4 = Path(mp4)
        if not mp4.is_file() or mp4.stat().st_size < 10_000:
            return [Finding(HARD, "no-file", "The reel file is missing or empty.")]
        from .tools import media_info

        info = media_info(mp4)
        dur = float(info.get("duration") or 0.0)
        # THE MASTER AT THE REEL'S OWN RATE. Every timing claim here is made at 60 fps; a
        # file at another rate would put a kill or a flip between the frames it was cut on.
        fps = float(info.get("fps") or 0.0)
        if fps and abs(fps - REEL_FPS) > 0.5:
            out.append(Finding(HARD, "wrong-fps", f"The reel is {fps:g} fps; it is cut at {REEL_FPS}."))
        if abs(dur - float(derived.get("length") or 0.0)) > LENGTH_TOLERANCE:
            out.append(Finding(HARD, "wrong-length", f"The reel is {dur:.1f} s; the plan was {float(derived['length']):.1f} s."))
        # the game's own picture sits in the middle band of a 9:16 fit layout; in a plain frame it is the frame
        vertical = project.get("format") == "vertical"
        band = {"fit": 608, "near": 810}.get(project.get("vfit") or "") if vertical else None
        crop = f"crop=iw:iw*{band}/1080:0:(ih-iw*{band}/1080)/2" if band else "crop=iw:ih:0:0"
        from . import studio
        frames = _frames(ff, mp4, crop, (540, 304))
        if not len(frames):
            return out + [Finding(HARD, "does-not-decode", "The reel could not be read back.")]
        lap = _lap(frames)
        import numpy as np

        luma = frames.mean(axis=(1, 2))
        n = len(luma)
        for i in range(int(0.2 * 60), n - int(1.0 * 60)):          # the opening and the ending fade aside
            if luma[i] < BLACK_MAX and np.median(luma[max(0, i - 6):i]) > BLACK_AROUND                     and np.median(luma[i + 1:i + 7]) > BLACK_AROUND:
                out.append(Finding(HARD, "black-frame", "A black frame flashes in the middle of the reel.",
                                   round(i / 60 - float(derived.get("offset") or 0.0), 3)))
                break
        hot_share = (frames > BRIGHT_LEVEL).mean(axis=(1, 2))
        hot = hot_share > BRIGHT_SHARE
        # a white-flash transition is meant to be white: its frames are not a finding
        off = float(derived.get("offset") or 0.0)
        for s, r in zip(project.get("shots") or [], derived.get("shots") or []):
            if s.get("transition") == "t02" and float(s.get("tlen") or 0.0) > 0:
                a = int((off + float(r["start"]) - float(s["tlen"]) / 2) * 60) - 1
                hot[max(0, a):max(0, a + int(float(s["tlen"]) * 60) + 3)] = False
        # The frames round each kill are the kill-readability check's below, which says why.
        near_kill = np.zeros(n, bool)
        for k in derived.get("kills") or []:
            i = int(round((float(k) + off) * 60))
            near_kill[max(0, i - KILL_WINDOW[0]):max(0, i + KILL_WINDOW[1] + 1)] = True
        hot_away = hot & ~near_kill
        for i in range(n - BRIGHT_FRAMES + 1):
            if hot_away[i:i + BRIGHT_FRAMES].all():
                out.append(Finding(SOFT, "too-bright", "A moment of the reel is almost all white for two frames or more.",
                                   round(i / 60 - float(derived.get("offset") or 0.0), 3)))
                break
        # THE GAME BY A QUARTER OF A SECOND (ChatGPT's review of Clean, every style): more
        # than half the picture near-black then is a fade that hides the hook. Only the
        # fade's fault when the footage a second in is not that dark itself; a style made
        # to open slowly (long_fade_in) is left alone.
        st_ = studio.STYLE.get(project.get("style") or "")
        if n > 60 and not (st_ and st_.long_fade_in):
            dark_at = float((frames[OPEN_AT] < NEAR_BLACK).mean())
            if dark_at > OPEN_BLACK and float((frames[60] < NEAR_BLACK).mean()) <= OPEN_BLACK:
                out.append(Finding(SOFT, "opening-dark", f"{dark_at:.0%} of the picture is still black a "
                                   f"quarter of a second in: the fade hides the hook.", 0.25))
        if luma[-1] > WHITE_END:
            out.append(Finding(HARD, "white-ending", "The reel ends on a frame burnt almost white.",
                               round(n / 60 - float(derived.get("offset") or 0.0), 3)))
        med = float(np.median(lap)) or 1.0
        # KILL READABILITY, every style (ChatGPT's third review). Two readings at each kill:
        #   - its DETAIL: the hard one. A kill whose picture is gone cannot be read, whatever
        #     did it -- the only hard fail.
        #   - its LIGHT: over KILL_BRIGHT_SHARE of the game's pixels above BRIGHT_LEVEL for
        #     KILL_BRIGHT_FRAMES frames running is a finding, soft, saying why. A flash meant
        #     to white out (INTENDED_BRIGHT, or a white-flash cut) is not counted at all;
        #     footage that is that bright away from its kill too -- a white wall -- is said
        #     as the footage's, never the effect's; only what is left is the effect's.
        # Measured on the v3 renders: Velocity's one too-bright kill was a white wall at 21%.
        by_kill = []                                   # (kill reel time, shot, row)
        for s, r in zip(project.get("shots") or [], derived.get("shots") or []):
            for kk in r.get("kills_reel") or ([r["kill_reel"]] if r.get("kill_reel") is not None else []):
                by_kill.append((float(kk), s, r))
        for k in derived.get("kills") or []:
            i = int(round((float(k) + off) * 60))
            win = lap[max(0, i - SHARP_RADIUS[0]):i + SHARP_RADIUS[1] + 1]
            if win and sorted(win)[len(win) // 2] / med < SHARP_MIN:
                out.append(Finding(HARD, "kill-not-sharp", "A kill is blurred or washed out where it lands.", float(k)))
            if not by_kill:
                continue
            _k, s, r = min(by_kill, key=lambda x: abs(x[0] - float(k)))
            if any(studio.fam(f) in INTENDED_BRIGHT for f in s.get("fx") or []):
                continue
            # Only this shot's own frames, and none of a white-flash cut's: the next shot's
            # cut is not this kill's light.
            s0, s1 = int(round((float(r["start"]) + off) * 60)), int(round((float(r["end"]) + off) * 60))
            a, b = max(i - KILL_WINDOW[0], s0, 0), min(i + KILL_WINDOW[1], s1 - 1, n - 1)
            lit = (hot_share[a:b + 1] > KILL_BRIGHT_SHARE) & hot[a:b + 1]
            run = best = 0
            for h in lit:
                run = run + 1 if h else 0
                best = max(best, run)
            if best < KILL_BRIGHT_FRAMES:
                continue
            rest = np.concatenate([hot_share[max(0, s0):a], hot_share[min(n, b + 20):max(0, min(n, s1))]])
            if len(rest) and float(np.median(rest)) > KILL_BRIGHT_SHARE * 0.75:
                why = "the footage is that bright (it is away from the kill too), not an effect"
            else:
                why = "an effect lifting the picture; take it off or give the kill another"
            out.append(Finding(SOFT, "kill-bright", f"Over {KILL_BRIGHT_SHARE:.0%} of the game's picture is near-white "
                               f"for {best} frames at a kill: {why}.", float(k)))
    except Exception as e:                                     # noqa: BLE001
        log.info("reel check could not run: %s", e)
        out.append(Finding(HARD, "check-failed", f"The reel could not be checked ({e})."))
    return out


def check(project: dict, derived: dict, mp4: Path | None = None, *, fast: bool = True, ff: str = "ffmpeg") -> list[Finding]:
    """Plan checks, then render checks when there is a render."""
    found = plan_findings(project, derived, fast=fast)
    if mp4 is not None:
        found += render_findings(mp4, project, derived, ff)
    return found
