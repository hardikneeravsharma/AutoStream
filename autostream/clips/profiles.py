"""Per-game kill-marker detector profiles.

WHAT A PROFILE IS
    Most shooters confirm your own kill with a fixed glyph drawn at a fixed
    place on the HUD -- Delta Force draws a skull just under the crosshair. That
    is far better to detect than the kill feed: the feed lists everyone's kills,
    needs fuzzy name matching to survive OCR mistakes, and reads badly over
    bright terrain. A fixed glyph can simply be template matched.

    So a profile is: where to look (a band, in frame fractions), what to look
    for (a small greyscale template), and how sure to be (a correlation floor).

    Some games leave no choice. CS2 draws no kill confirmation at all, so its
    profile sets mode="killfeed" and the feed is read instead -- see
    clips/killfeed.py. Those profiles carry a band and a name and no template.

WHY THE REFERENCE HEIGHT MATTERS MORE THAN ANYTHING ELSE HERE
    A template is a fixed number of PIXELS. The Delta Force one is 20x18, cut
    from a 1280x720 frame. On a 1920x1080 recording the same skull is drawn 1.5x
    larger, and normalised cross-correlation against a 20x18 patch then matches
    nothing at all -- the scan returns zero kills and looks like the game simply
    had none. ref_height records the height the template was cut at, and the
    scan rescales every band back to it before matching. Get this wrong and the
    failure is silent, which is why it is stored per profile rather than assumed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .. import paths

log = logging.getLogger("autostream.clips.profiles")


@dataclass
class Profile:
    key: str                      # exe name, e.g. "deltaforceclient.exe"
    label: str
    band: tuple[float, float, float, float]      # x1, y1, x2, y2 as fractions
    template: str                 # filename inside CLIP_TEMPLATES
    ref_height: int = 720
    match_min: float = 0.80
    scan_fps: float = 2.0
    merge_gap: float = 3.0        # matches closer than this are one kill burst
    notes: str = ""

    # How the kill is recognised:
    #   "template"  match a fixed glyph  (Delta Force's skull)
    #   "colour"    count pixels of a colour
    #   "killfeed"  OCR the feed and find your own name
    #
    # Not every game draws a fixed marker. CS2 has no centre-screen kill
    # confirmation at all -- no hitmarker, no banner -- and announces kills only
    # in the feed at the top right. Correlation has nothing to match.
    #
    # Colour was tried there first and FAILED on real footage: golden and warm
    # map walls register as red just as strongly as the feed outline does, so
    # the threshold that caught kills also caught scenery. Reading the feed is
    # slower but it is the only signal that actually distinguishes them.
    mode: str = "template"
    colour: tuple[int, int, int] = (255, 60, 60)   # colour mode: target RGB
    tolerance: int = 60                            # per-channel slack
    min_pixels: int = 40                           # pixels needed to count

    # killfeed mode: the name to look for, and how close a match has to be.
    # Left empty in the profile and filled from games.yaml at resolve time,
    # because the name belongs to the player and not to the game -- the same
    # profile has to work for anyone who copies it.
    player: str = ""
    match_ratio: float = 0.72

    # Counter-Strike only: read the scoreboard as well as the feed, and clip
    # ROUNDS rather than bursts of kills. See clips/rounds.py for why the round
    # is the right unit there -- three kills alone against three opponents is a
    # different clip from three kills with the team alive, and a kill-based
    # ranking buries the first.
    rounds: bool = False
    # HUD regions, as fractions of the frame. Empty means use the measured
    # defaults in clips/hud.py; stored per profile because HUD SCALE is a user
    # setting and the defaults were measured at one person's.
    hud_regions: dict[str, list[float]] = field(default_factory=dict)

    # True when the game cannot distinguish a kill from an assist, so counts run
    # high and the UI has to say so -- quietly reporting inflated numbers is
    # worse than not supporting the game.
    #
    # Not set for CS2, though it nearly was. The feed marks assists identically
    # in colour, but it puts them in a different SLOT ("you + killer <icon>
    # victim") and killfeed mode reads the slot, so assists are identified and
    # excluded rather than silently counted: 14 of 15 rows checked by eye came
    # out right. The one that did not had an unreadable killer name, which
    # leaves an assist looking exactly like a kill -- so counts still run
    # slightly high, and the profile's notes say so rather than this flag,
    # which would overstate it.
    counts_assists: bool = False

    def template_path(self) -> Path:
        """User-calibrated first, then the ones that ship with AutoStream.

        That order lets someone recalibrate a built-in game on their own
        footage -- different resolution, different HUD scale -- without having
        to touch anything inside the installation.
        """
        mine = paths.CLIP_TEMPLATES / self.template
        if mine.is_file():
            return mine
        return paths.CLIP_TEMPLATES_BUILTIN / self.template

    def exists(self) -> bool:
        """Whether this profile can actually be run.

        A colour profile needs nothing on disk. A killfeed profile needs a name
        to look for -- without one it would scan the whole recording and find
        nothing, which reads as "this game had no kills" rather than as the
        configuration error it is.
        """
        if self.mode == "colour":
            return True
        if self.mode == "killfeed":
            return bool(self.player)
        return self.template_path().is_file()

    def why_not(self) -> str:
        """Empty if usable, otherwise what to do about it."""
        if self.exists():
            return ""
        if self.mode == "killfeed":
            return (f"{self.label} reads your name out of the kill feed, but no "
                    f"in-game name is set for it. Add one on the Library page.")
        return (f"No kill-marker template for {self.label}. Calibrate it on a "
                f"recording first.")

    def as_dict(self) -> dict[str, Any]:
        out = {
            "label": self.label,
            "band": list(self.band),
            "ref_height": self.ref_height,
            "scan_fps": self.scan_fps,
            "merge_gap": self.merge_gap,
            "notes": self.notes,
        }
        # Only the keys the mode actually uses. This file is meant to be opened
        # and edited by hand, and a killfeed profile carrying a correlation
        # threshold and an empty template invites someone to tune a number that
        # does nothing.
        if self.mode == "template":
            out["template"] = self.template
            out["match_min"] = self.match_min
        if self.mode == "colour":
            out.update({"mode": self.mode, "colour": list(self.colour),
                        "tolerance": self.tolerance, "min_pixels": self.min_pixels})
        elif self.mode == "killfeed":
            out.update({"mode": self.mode, "match_ratio": self.match_ratio})
            if self.rounds:
                out["rounds"] = True
            if self.hud_regions:
                out["hud_regions"] = {k: list(v)
                                      for k, v in self.hud_regions.items()}
            # `player` is deliberately NOT written: it comes from games.yaml so
            # that a profile stays shareable and there is one place to change
            # the name.
        if self.counts_assists:
            out["counts_assists"] = True
        return out


# Shipped pre-calibrated. A single skull is centred at (0.499, 0.683) of the
# frame and multiple skulls spread horizontally around that centre, so the band
# is wide and shallow.
#
# ref_height and match_min were both MEASURED here, and both differ from what
# the original script asserted about itself:
#
#   ref_height 720. The source VOD is 640x360, so the template cannot have been
#     cut at native scale -- it was cut from a band already blown up for
#     inspection. Sweeping 540-900 against 64 known kills peaked unambiguously
#     at 720 (49 hits) and collapsed either side (540 -> 0, 900 -> 0). This is
#     the value that must be right: get it wrong and the scan returns nothing
#     at all rather than returning less.
#
#   match_min 0.75, not 0.80. Over 26 known kill frames and 104 frames sampled
#     well away from any kill: kills ran 0.78-0.91 (median 0.88), everything
#     else 0.25-0.74 (median 0.55). 0.75 sits in the gap and caught 100% of
#     kills with no false positives; 0.80 clipped 12% of real kills for nothing.
BUILTIN: dict[str, dict[str, Any]] = {
    "deltaforceclient.exe": {
        "label": "Delta Force",
        "band": [0.42, 0.650, 0.58, 0.712],
        "template": "delta-force.npy",
        "ref_height": 720,
        "match_min": 0.75,
        "notes": "Skull marker under the crosshair. Kills score 0.78-0.91 against "
                 "a 0.74 ceiling for gameplay, menus and results screens.",
    },
    # CS2 is read, not matched. The band is the whole feed area at the top
    # right, measured off real 1920x1080 footage: the feed starts just under
    # the top bar and four stacked rows reach about 30% down the frame.
    #
    # scan_fps 1.0 because OCR costs orders of magnitude more than a
    # correlation, and a feed line stays on screen for roughly five seconds --
    # so one sample a second cannot miss one, and two a second would only
    # double the bill for the same events.
    "cs2.exe": {
        "label": "Counter-Strike 2",
        "mode": "killfeed",
        # DO NOT TIGHTEN THIS FOR SPEED. It was tried: names only ever appeared
        # between y 0.062 and 0.209 across 93 sightings, so trimming to
        # 0.050-0.250 looked free and did cut 13% off the scan. It was not
        # free. Changing the crop changes Tesseract's layout analysis, and the
        # bounding boxes it returns became far less stable -- one kill row that
        # had read at R 0.706-0.713 (spread 0.007) started reading 0.695-0.725
        # (spread 0.030). That is wider than X_TOL, so a single kill split into
        # three and the count doubled. A five-minute benchmark showed identical
        # detections and missed it entirely.
        "band": [0.60, 0.030, 1.000, 0.300],
        "template": "",
        "ref_height": 1080,
        "scan_fps": 1.0,
        "merge_gap": 3.0,
        "match_ratio": 0.72,
        "rounds": True,
        "notes": "Reads the kill feed. Your name immediately left of the "
                 "weapon icon is a kill, right of it a death, and further left "
                 "again an assist, which is not clipped. Assists whose killer's "
                 "name is unreadable count as kills, so kill counts can run a "
                 "little high. Needs your in-game name, set on the Library page.",
    },
}

# Calibration starting points for games whose marker geometry is known but whose
# TEMPLATE is not. A template is a pixel patch and has to come from real footage;
# these only tell the calibrator where to open its box so the job is a drag
# rather than a hunt.
#
# Measured off real gameplay at 640x360, not guessed:
#   Valorant  killfeed top LEFT (not right - the right panel is the Combat
#             Report). The kill banner is bottom centre per Riot's own wiki, and
#             UPGRADED WEAPON SKINS REPLACE IT, so there is no single template
#             that is correct for every player. It has to be cut per-account.
#   CS2       killfeed top right, and the local player's rows are outlined red.
#             No centre-screen confirmation exists at all - no hitmarker, no
#             banner - so the colour mode is the only option.
SEEDS: dict[str, dict[str, Any]] = {
    "valorant-win64-shipping.exe": {
        "label": "VALORANT",
        "mode": "template",
        "box": [0.455, 0.640, 0.545, 0.700],     # where to open the calibrator
        "band": [0.36, 0.625, 0.64, 0.715],
        "why": "Kill banner, bottom centre. Your banner depends on which "
               "weapon skin you have upgraded, so this has to be cut from your "
               "own footage.",
    },
    "cs2.exe": {
        "label": "Counter-Strike 2",
        "mode": "killfeed",
        "box": [0.60, 0.030, 1.000, 0.300],      # the whole feed, not a glyph
        # DO NOT TIGHTEN THIS FOR SPEED. It was tried: names only ever appeared
        # between y 0.062 and 0.209 across 93 sightings, so trimming to
        # 0.050-0.250 looked free and did cut 13% off the scan. It was not
        # free. Changing the crop changes Tesseract's layout analysis, and the
        # bounding boxes it returns became far less stable -- one kill row that
        # had read at R 0.706-0.713 (spread 0.007) started reading 0.695-0.725
        # (spread 0.030). That is wider than X_TOL, so a single kill split into
        # three and the count doubled. A five-minute benchmark showed identical
        # detections and missed it entirely.
        "band": [0.60, 0.030, 1.000, 0.300],
        "why": "CS2 draws no kill confirmation at all, so the feed at the top "
               "right has to be read. Draw the box around the WHOLE feed, wide "
               "enough for the names at both ends, and give your in-game name "
               "exactly as it appears there.",
    },
}


def seed_for(game_key: str | None, game_name: str | None = None) -> dict | None:
    """A calibration starting point for a game with no template yet."""
    if game_key:
        k = ALIASES.get(game_key.lower(), game_key.lower())
        if k in SEEDS:
            return {"key": k, **SEEDS[k]}
    if game_name:
        want = slug(game_name)
        for k, s in SEEDS.items():
            if slug(s["label"]) == want:
                return {"key": k, **s}
    return None


# Aliases, because the same game ships under more than one executable name.
# Delta Force in particular runs as a small launcher stub that starts the real
# Unreal binary, and which of the two the watcher reports depends on whether it
# caught the foreground window or the process list.
ALIASES: dict[str, str] = {
    "deltaforce.exe": "deltaforceclient.exe",
    "delta force.exe": "deltaforceclient.exe",
    "deltaforceclient-win64-shipping.exe": "deltaforceclient.exe",
    "deltaforce-win64-shipping.exe": "deltaforceclient.exe",
}


def slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", str(s or "")).strip().lower()
    return re.sub(r"[\s_-]+", "-", s)[:48] or "game"


def _load_file() -> dict[str, dict]:
    if not paths.CLIP_PROFILES.exists():
        return {}
    try:
        data = yaml.safe_load(paths.CLIP_PROFILES.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as e:
        log.warning("could not read clip profiles: %s", e)
        return {}
    return data if isinstance(data, dict) else {}


def _build(key: str, raw: dict) -> Profile | None:
    try:
        band = tuple(float(v) for v in raw["band"])
        if len(band) != 4:
            raise ValueError("band needs four numbers")
        if str(raw.get("mode", "template")).lower() == "template" and not raw.get("template"):
            raise KeyError("template")
        mode = str(raw.get("mode", "template")).lower()
        if mode not in ("template", "colour", "killfeed"):
            raise ValueError(f"unknown mode {mode!r}")
        colour = tuple(int(v) for v in raw.get("colour", (255, 60, 60)))
        if len(colour) != 3:
            raise ValueError("colour needs three numbers")
        return Profile(
            key=key,
            label=str(raw.get("label") or key),
            band=band,                                    # type: ignore[arg-type]
            # A colour profile has no template, so this may legitimately be absent.
            template=str(raw.get("template") or ""),
            ref_height=int(raw.get("ref_height", 720)),
            match_min=float(raw.get("match_min", 0.80)),
            scan_fps=float(raw.get("scan_fps", 2.0)),
            merge_gap=float(raw.get("merge_gap", 3.0)),
            notes=str(raw.get("notes", "")),
            mode=mode,
            colour=colour,                                # type: ignore[arg-type]
            tolerance=int(raw.get("tolerance", 60)),
            min_pixels=int(raw.get("min_pixels", 40)),
            counts_assists=bool(raw.get("counts_assists", False)),
            player=str(raw.get("player") or ""),
            match_ratio=float(raw.get("match_ratio", 0.72)),
            rounds=bool(raw.get("rounds", False)),
            hud_regions={str(k): [float(v) for v in vals]
                         for k, vals in (raw.get("hud_regions") or {}).items()},
        )
    except (KeyError, TypeError, ValueError) as e:
        log.warning("ignoring malformed clip profile %r: %s", key, e)
        return None


def load_all() -> dict[str, Profile]:
    """Built-ins, then the user's file on top so a recalibration wins."""
    merged: dict[str, dict] = {k: dict(v) for k, v in BUILTIN.items()}
    for k, v in _load_file().items():
        if isinstance(v, dict):
            merged[str(k).lower()] = v
    out = {}
    for k, raw in merged.items():
        p = _build(k, raw)
        if p is not None:
            out[k] = p
    return out


def for_game(game_key: str | None, game_name: str | None = None) -> Profile | None:
    """Resolve a profile for a session.

    Matched on the executable name rather than the display name: the exe is
    stable, while the display name changes with the index source (a Steam
    lookup and the public index disagree often enough to matter).
    """
    if not game_key and not game_name:
        return None
    table = load_all()
    hit = None
    if game_key:
        k = game_key.lower()
        k = ALIASES.get(k, k)
        hit = table.get(k)
    if hit is None and game_name:
        want = slug(game_name)
        for p in table.values():
            if slug(p.label) == want:
                hit = p
                break
    if hit is not None and hit.mode == "killfeed" and not hit.player:
        hit.player = username_for(game_key, game_name)
    return hit


def username_for(game_key: str | None, game_name: str | None = None) -> str:
    """The in-game name to look for, out of games.yaml.

    Read straight from the file rather than through the game index, because a
    clip job runs from the dashboard and has no engine to ask. The name is
    per game because they genuinely differ -- Valorant appends a tag, most
    others do not.
    """
    try:
        data = yaml.safe_load(paths.GAMES_FILE.read_text(encoding="utf-8")) or {}
        games = data.get("games") or {}
    except (yaml.YAMLError, OSError) as e:
        log.warning("could not read %s for a killfeed name: %s", paths.GAMES_FILE, e)
        return ""
    if not isinstance(games, dict):
        return ""

    keys = []
    if game_key:
        k = game_key.lower()
        keys += [k, ALIASES.get(k, k)]
        # An alias points at the canonical exe, but the NAME may well be
        # recorded against the variant that was actually detected, so try both
        # directions before giving up.
        keys += [a for a, canon in ALIASES.items() if canon == ALIASES.get(k, k)]
    for k in keys:
        entry = games.get(k)
        if isinstance(entry, dict) and entry.get("username"):
            return str(entry["username"]).strip()
    if game_name:
        want = slug(game_name)
        for entry in games.values():
            if isinstance(entry, dict) and entry.get("username") \
                    and slug(str(entry.get("name") or "")) == want:
                return str(entry["username"]).strip()
    return ""


def save(profile: Profile) -> None:
    """Write one profile into the user's file, leaving the others alone."""
    paths.CLIP_PROFILES.parent.mkdir(parents=True, exist_ok=True)
    data = _load_file()
    data[profile.key.lower()] = profile.as_dict()
    header = (
        "# Kill detector profiles, one per game.\n"
        "#\n"
        "# band       x1, y1, x2, y2 as fractions of the frame - where to look\n"
        "# mode       how a kill is recognised:\n"
        "#              template  match a fixed glyph the game draws (default)\n"
        "#              killfeed  read the feed and find your own name\n"
        "#              colour    count pixels of one colour\n"
        "#\n"
        "# template mode\n"
        "#   template   greyscale patch to match, in config/clip_templates/\n"
        "#   ref_height the frame height the template was cut from. Every scan\n"
        "#              rescales to this before matching, so a template stays\n"
        "#              valid at any recording resolution. Do not edit by hand.\n"
        "#   match_min  correlation floor, 0-1. Raise it if menus register as\n"
        "#              kills.\n"
        "#\n"
        "# killfeed mode\n"
        "#   match_ratio how close an OCR read has to be to your name, 0-1. Lower\n"
        "#               it if kills are missed, raise it if another player's\n"
        "#               name registers as yours.\n"
        "#   Your in-game name is NOT stored here - it lives in games.yaml under\n"
        "#   the game's entry, so one edit changes it everywhere.\n"
    )
    paths.CLIP_PROFILES.write_text(
        header + yaml.safe_dump(data, sort_keys=True, allow_unicode=True),
        encoding="utf-8")
    log.info("saved clip profile %r", profile.key)


def delete(key: str) -> bool:
    data = _load_file()
    if key.lower() not in data:
        return False
    data.pop(key.lower())
    paths.CLIP_PROFILES.write_text(
        yaml.safe_dump(data, sort_keys=True, allow_unicode=True), encoding="utf-8")
    return True


def listing() -> list[dict]:
    """For the UI: every profile with whether its template is actually present."""
    out = []
    for p in sorted(load_all().values(), key=lambda x: x.label.lower()):
        out.append({
            "key": p.key,
            "label": p.label,
            "ref_height": p.ref_height,
            "match_min": p.match_min,
            "builtin": p.key in BUILTIN,
            "ready": p.exists(),
            "notes": p.notes,
        })
    return out
