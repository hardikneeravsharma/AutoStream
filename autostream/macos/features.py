"""What the macOS build does not do, said once, where the page can read it.

The Mac build is the clipper and the Studio (issue #193). Everything that
exists to stream -- the engine and its game watcher, the tray, the overlay,
the kill switch, OBS, recording, screen savers, thumbnails, the YouTube API,
start-at-login -- is simply not started. Hiding a control is not enough on its
own, so this module feeds the two places the page learns what exists:

  /api/bootstrap        `unavailable`, `hide_pages` and `home`, which the
                        shell and the setup wizard read (ui/shell.py,
                        ui/setup.py) to take the Dashboard, the Library and
                        the "Stream and clip" choice away.
  /api/settings/schema  the schema without the sections and fields that only
                        mean something to a streaming install, so Settings
                        never offers an OBS password on a machine with no OBS
                        to give it to.

On Windows neither route calls this, and both payloads are what they were.
"""
from __future__ import annotations

import copy

# key -> why, in the words the page would use. Kept as reasons rather than a
# bare list so an absence can be explained, never just noticed.
UNAVAILABLE: dict[str, str] = {
    "streaming": "Going live needs the game on the same machine, and the games "
                 "AutoStream knows mostly do not run on a Mac.",
    "engine": "There is no game watcher on a Mac, so nothing starts by itself.",
    "obs": "OBS control and recording setup are part of streaming.",
    "tray": "The Mac build lives in its window; closing it quits.",
    "overlay": "The in-game overlay and kill switch are Windows only.",
    "screens": "Starting, paused and ending screens are part of streaming.",
    "thumbnails": "Stream thumbnails are made for the YouTube broadcast.",
    "youtube": "Signing in to YouTube, uploads and chat need the streaming half.",
    "startup": "Start-at-login is a Windows Scheduled Task.",
    "valorant_api": "VALORANT's match record is read from its Windows client; "
                    "on a Mac the clipper reads the screen instead.",
    "game_fetch": "Nothing that needs a game installed: a CS2 demo is copied "
                  "across from the PC rather than fetched by the game.",
}

# NOTHING ON A MAC MAY NEED A GAME INSTALLED. The Mac clips footage recorded
# on a PC, so anything that asks the game itself for something is refused with
# a sentence that says what to do instead -- here, the one CS2 path that did.
DEMO_DOWNLOAD = ("Fetching a demo from a match code asks Counter-Strike to do "
                 "it, and Counter-Strike is not on this Mac. Download the demo "
                 "on your PC (Watch > Your Matches), copy the .dem file across, "
                 "and pick it with the recording.")

VALORANT_FETCH = ("VALORANT's match records come from the Riot Client, which is "
                  "not on this Mac. Fetch them on your PC, then copy its "
                  "Videos/AutoStream/matches folder to ~/Movies/AutoStream/matches "
                  "-- or clip without them, and the clipper reads the screen.")

# Pages with nothing to do without an engine. Clips is where a Mac starts.
HIDE_PAGES = ("dash", "library")
HOME = "clips"

# Settings sections that only configure streaming, and stray streaming fields
# inside sections that otherwise stay.
HIDE_SECTIONS = frozenset({"stream", "obs", "timing", "safety", "titles",
                           "thumbnail", "screens", "record"})
HIDE_FIELDS = frozenset({
    "ui.open_window",                    # hides to a tray the Mac does not have
    "clips.upload_privacy", "clips.upload_title", "clips.upload_description",
    "youtube.stream_id", "youtube.ingestion_address", "obs.password_env",
})

# The encoder menu, in the Mac's terms. Both values are ones the shared schema
# already accepts, so a save validates exactly as on Windows.
ENCODER_OPTIONS = [
    {"value": "auto", "label": "Automatic - Apple VideoToolbox when available"},
    {"value": "libx264", "label": "CPU"},
]
ENCODER_HELP = ("Automatic uses the Mac's own hardware encoder (VideoToolbox), "
                "which is several times faster and leaves the CPU free. Switch "
                "to CPU if clips come out corrupted.")
FFMPEG_HELP = ("Only needed if AutoStream cannot find ffmpeg on its own. Point "
               "this at the folder containing ffmpeg -- for Homebrew's full "
               "build, /opt/homebrew/opt/ffmpeg-full/bin.")


def bootstrap() -> dict:
    """The keys /api/bootstrap adds on a Mac."""
    return {"platform": "macos", "unavailable": sorted(UNAVAILABLE),
            "hide_pages": list(HIDE_PAGES), "home": HOME}


def settings_schema(schema: list[dict]) -> list[dict]:
    """`schema` without what a Mac cannot use. Never mutates the original."""
    out = []
    for sec in schema:
        if sec.get("id") in HIDE_SECTIONS:
            continue
        sec = copy.deepcopy(sec)
        fields = []
        for f in sec.get("fields", ()):
            if f.get("path") in HIDE_FIELDS:
                continue
            if f.get("path") == "clips.encoder":
                f["options"] = copy.deepcopy(ENCODER_OPTIONS)
                f["help"] = ENCODER_HELP
            elif f.get("path") == "clips.ffmpeg_path":
                f["help"] = FFMPEG_HELP
            fields.append(f)
        if fields:
            sec["fields"] = fields
            out.append(sec)
    return out


# ------------------------------------------------------------ the updater
# Every GitHub release asset the updater knows is a Windows installer or zip;
# downloading one to a Mac costs 70 MB it cannot run. Mac builds come from the
# .dmg on the release page instead (.github/workflows/release.yml).
UPDATE_WHY = ("Updates are not installed from inside the Mac app: download the "
              "newest AutoStream-macos .dmg from the GitHub release page.")


def update_check(current: str) -> dict:
    """What webui.update_check answers on a Mac, in the shape Settings reads."""
    return {"ok": True, "checked": True, "available": False, "newer": False,
            "current": current, "why": UPDATE_WHY, "cached": False}


def update_refused() -> dict:
    return {"error": UPDATE_WHY}
