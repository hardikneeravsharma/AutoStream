r"""The three screen savers: starting, be right back, and thanks for watching.

A FILE OR A URL
    Some people have their cards as MP4s; some have them in an overlay service
    where the card is a page rather than a video. Both are one setting, because
    to the person filling it in they are the same thing -- "the be right back
    card" -- and which OBS source type that needs is not their problem.

    An overlay is deliberately NOT downloaded and turned into a file. The page
    keeps updating itself, and a copy taken today stops being the card the
    moment it is edited.

WHY AUTOSTREAM BUILDS THE SCENES RATHER THAN ASKING FOR THEM
    Every other way of getting a video onto a stream ends with "now go and set
    up three scenes in OBS", which is the step people do not do. The scenes are
    ordinary OBS scenes holding one looping media source each, and obs-websocket
    can create both -- so the setting is a FILE, and the scene is an
    implementation detail AutoStream owns.

    Everything here is idempotent. Pointing a setting at a different file
    updates the source in place; the scene is only created if it is missing.
    Nothing is ever removed behind the user's back: a scene they have since
    decorated with a webcam and an overlay is theirs, and it keeps whatever
    they put in it.

WHEN EACH ONE IS ON SCREEN
    starting   from going live until `starting_seconds` have passed, then the
               game scene takes over
    paused     for as long as the stream is paused. THIS is the one that
               changes what pause means -- see engine.toggle_pause. A "be right
               back" card is a promise to come back, so the broadcast stays up
               and only the picture changes
    ending     for `ending_seconds` before the broadcast is completed, which is
               the only window in which anything can be said to the people
               still watching

WHY THE HOLD MATTERS
    Without one the starting card would be replaced by the game within the same
    tick and nobody would see it, and the ending card would never reach the
    encoder at all -- the broadcast would already be complete. Both are held by
    a deadline the engine checks, not by sleeping, because the engine's loop is
    strictly serial and a sleep in it stops the OBS watchdog and chat with it.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("autostream.screens")

# The three screens, in the order a session meets them. The suffix is what
# appears in OBS after the configured prefix, and the config keys are
# `<key>_file` in the `screens` section.
STARTING = "starting"
PAUSED = "paused"
ENDING = "ending"

SCREENS: dict[str, dict] = {
    STARTING: {"suffix": "Starting", "label": "Stream starting",
               "loop": True, "hold": "starting_seconds"},
    PAUSED: {"suffix": "Be Right Back", "label": "Be right back",
             "loop": True, "hold": None},          # held until Resume
    ENDING: {"suffix": "Ending", "label": "Thanks for watching",
             "loop": True, "hold": "ending_seconds"},
}


def is_url(value: str) -> bool:
    """Is this setting a page rather than a file?

    Scheme only. Guessing from anything else -- a dot in the name, a slash --
    misreads ordinary Windows paths, and the two are never ambiguous in
    practice: a screen saver is either somewhere on disk or somewhere on the
    web.
    """
    return str(value or "").strip().lower().startswith(("http://", "https://"))


def scene_name(cfg, which: str) -> str:
    """What the scene is called in OBS."""
    prefix = (getattr(cfg.screens, "scene_prefix", "") or "AutoStream").strip()
    return f"{prefix} {SCREENS[which]['suffix']}"


def source_name(cfg, which: str) -> str:
    return f"{scene_name(cfg, which)} media"


def file_for(cfg, which: str) -> str:
    return str(getattr(cfg.screens, f"{which}_file", "") or "")


def hold_for(cfg, which: str) -> float:
    key = SCREENS[which]["hold"]
    if not key:
        return 0.0
    try:
        return max(0.0, float(getattr(cfg.screens, key, 0)))
    except (TypeError, ValueError):
        return 0.0


def configured(cfg, which: str) -> bool:
    """Is this screen switched on AND pointed at something that is there?

    The existence check is the point: a path that has been moved or deleted
    would otherwise produce a scene showing nothing, which on a live stream is
    worse than never switching to it at all.

    A URL is taken on trust. Reaching out to check it would put a network round
    trip in front of going live, and an overlay that needs a browser session to
    render answers unhelpfully to anything else anyway.
    """
    if not getattr(cfg.screens, "enabled", False):
        return False
    where = file_for(cfg, which)
    if not where:
        return False
    return True if is_url(where) else Path(where).is_file()


def ensure(cfg, obs, which: str) -> str:
    """Build or update this screen's scene. -> the scene name, or "".

    Called before switching rather than once at startup, so a file changed in
    Settings takes effect on the next session without a restart.
    """
    if not configured(cfg, which):
        return ""
    scene = scene_name(cfg, which)
    where = file_for(cfg, which)
    source = source_name(cfg, which)
    if is_url(where):
        ok = obs.ensure_browser_scene(scene, source, where)
    else:
        ok = obs.ensure_media_scene(scene, source, where,
                                    loop=bool(SCREENS[which]["loop"]))
    return scene if ok else ""


def ensure_all(cfg, obs) -> dict[str, str]:
    """Every configured screen, built. -> {which: scene name}."""
    out = {}
    for which in SCREENS:
        scene = ensure(cfg, obs, which)
        if scene:
            out[which] = scene
    if out:
        log.info("screen scenes ready: %s", ", ".join(sorted(out.values())))
    return out


def show(cfg, obs, which: str) -> bool:
    """Put this screen on air. -> whether it actually went up."""
    scene = ensure(cfg, obs, which)
    if not scene:
        return False
    obs.set_scene(scene)
    return True


def missing(cfg) -> list[str]:
    """Screens switched on but pointed at nothing readable. For the UI."""
    if not getattr(cfg.screens, "enabled", False):
        return []
    out = []
    for which, meta in SCREENS.items():
        where = file_for(cfg, which)
        if where and not is_url(where) and not Path(where).is_file():
            out.append(f"{meta['label']}: {where} is not there")
    return out
