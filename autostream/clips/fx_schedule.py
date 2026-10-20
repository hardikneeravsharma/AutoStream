"""The camera and the light, moving to the song's other layers.

WHY THIS EXISTS. Kills were the only thing in a reel that knew the music, so
between two kills the picture sat still however hard the song was hitting --
"right now we use the beats for kills only; if there are 3-4 different
tempos ... the other ones should land transitions or effects, like a screen
bounce on each fast beat". The rules are ChatGPT's spec for this
(projects/batch12/tempo/plan.md, Phase 4), with its numbers:

* THE GROOVE RUNS ON SONG TIME, so it is continuous across cuts: one curve over
  the whole reel, never restarted per shot. The kick is the camera's weight --
  a 0.30-0.45 % scale bounce in the build on the stronger kicks, 0.60-1.00 % on
  the drop -- and in the drop the hats add a 0.15-0.25 % pulse between them, 2-3
  a second in all. Quiet parts (intro, break, outro) stay still.
* THE SNARE IS PUNCTUATION: a one-frame 2-4 % brightness pop, no more than
  about 1.5 a second in the build and 2 in the drop, never within 120 ms of
  another.
* THE RISER PUSHES IN 1.5-2.5 % over the last 1.5-2 s before the drop, and lets
  go on it.
* A KILL OWNS ITS MOMENT: nothing here within 120 ms of a kill, and nothing in
  the 150 ms before the drop's.

Everything is in song seconds and stored on the project, so moving the song
under the reel moves its groove with it. studio.assemble_command draws it.
"""
from __future__ import annotations

KICK_BUILD = 0.0038        # scale, 0.38 %
KICK_DROP = 0.0080
HAT_DROP = 0.0020
POP = 0.03                 # brightness, one frame
KILL_CLEAR = 0.12
DROP_CLEAR = 0.15
PUSH = 0.02
PUSH_SECONDS = 1.8
KICK_MIN = {"build": 0.50, "drop": 0.30}       # s between kick bounces
HAT_MIN = 0.33
POP_MIN = {"build": 0.70, "drop": 0.50}
STILL = ("intro", "break", "outro")
MAX_EVENTS = 1200


def _thin(times: list[tuple[float, float]], gap: float) -> list[tuple[float, float]]:
    """Strongest first, keeping only events at least `gap` from every one kept."""
    kept: list[tuple[float, float]] = []
    for t, s in sorted(times, key=lambda x: -x[1]):
        if all(abs(t - k) >= gap for k, _ in kept):
            kept.append((t, s))
    return sorted(kept)


def schedule(rhythm, start: float, end: float, kills: list[float], drop: float | None) -> dict:
    """{"zoom": [[t, amount]], "pops": [[t, amount]], "push": [from, to, amount] or []}, song seconds."""
    clear = sorted(kills)

    def free(t: float) -> bool:
        if drop is not None and drop - DROP_CLEAR <= t <= drop + KILL_CLEAR:
            return False
        return all(abs(t - k) > KILL_CLEAR for k in clear)

    zoom: list[tuple[float, float]] = []
    pops: list[tuple[float, float]] = []
    for sec in rhythm.sections:
        a, b = max(start, sec.start), min(end, sec.end)
        if b <= a or sec.kind in STILL:
            continue
        hot = sec.kind in ("drop", "groove")
        kind = "drop" if hot else "build"
        kicks = [(t, s) for t, s in rhythm.events("kick", a, b, 0.45 if hot else 0.6) if free(t)]
        kicks = _thin(kicks, KICK_MIN[kind])
        amt = KICK_DROP if hot else KICK_BUILD
        zoom += [(t, round(amt * (0.75 + 0.25 * s), 5)) for t, s in kicks]
        if hot:
            hats = [(t, s) for t, s in rhythm.events("hats", a, b, 0.35)
                    if free(t) and all(abs(t - k) >= 0.1 for k, _ in kicks)]
            zoom += [(t, HAT_DROP) for t, _ in _thin(hats, HAT_MIN)]
        snares = [(t, s) for t, s in rhythm.events("snare", a, b, 0.6) if free(t)
                  and all(abs(t - k) >= 0.06 for k, _ in kicks)]
        pops += [(t, round(POP * (0.7 + 0.3 * s), 4)) for t, s in _thin(snares, POP_MIN[kind])]
    push: list[float] = []
    if drop is not None and start < drop - 0.5 <= end:
        push = [round(max(start, drop - PUSH_SECONDS), 4), round(drop - DROP_CLEAR, 4), PUSH]
    return {"zoom": [[round(t, 4), a] for t, a in sorted(zoom)][:MAX_EVENTS],
            "pops": [[round(t, 4), a] for t, a in sorted(pops)][:MAX_EVENTS],
            "push": push}


def clamp(raw) -> dict | None:
    """A project's groove as the page sent it, or None."""
    if not isinstance(raw, dict):
        return None

    def pairs(v, hi):
        out = []
        for x in (v or [])[:MAX_EVENTS]:
            try:
                t, a = float(x[0]), float(x[1])
            except (TypeError, ValueError, IndexError):
                continue
            if 0.0 <= t <= 36000.0:
                out.append([round(t, 4), round(max(0.0, min(hi, a)), 5)])
        return out
    push = raw.get("push") or []
    try:
        push = [float(push[0]), float(push[1]), max(0.0, min(0.05, float(push[2])))] if len(push) == 3 else []
    except (TypeError, ValueError):
        push = []
    if push and push[1] <= push[0]:
        push = []
    out = {"zoom": pairs(raw.get("zoom"), 0.02), "pops": pairs(raw.get("pops"), 0.08), "push": push}
    return out if (out["zoom"] or out["pops"] or out["push"]) else None


def zoom_expr(groove: dict, offset: float, length: float, var: str = "in_time") -> str:
    """The groove's scale as one expression over reel time: 1 + bounces + the push."""
    terms = []
    for t, a in groove.get("zoom") or []:
        r = t - offset
        if -0.2 <= r <= length + 0.2:
            # two frames up to the hit, then back down over about five
            terms.append(f"{a:.5f}*if(lt({var},{r:.4f}),clip(({var}-{r - 0.034:.4f})/0.034,0,1),"
                         f"exp(-({var}-{r:.4f})/0.045))")
    push = groove.get("push") or []
    if push:
        a, b, amt = push[0] - offset, push[1] - offset, push[2]
        if b > 0 and a < length:
            u = f"(({var}-{a:.4f})/{b - a:.4f})"
            terms.append(f"{amt:.4f}*between({var},{a:.4f},{b:.4f})*{u}*{u}*(3-2*{u})")
    return "1+" + "+".join(terms) if terms else ""


def pop_expr(groove: dict, offset: float, length: float, var: str = "t") -> str:
    terms = []
    for t, a in groove.get("pops") or []:
        r = t - offset
        if 0.0 <= r <= length:
            terms.append(f"{a:.4f}*between({var},{r - 0.004:.4f},{r + 0.0125:.4f})")
    return "+".join(terms)
