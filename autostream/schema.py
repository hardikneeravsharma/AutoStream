"""Declarative description of config.yaml: one source of truth for UI and API.

The settings page and the settings endpoints used to drift apart, because the
page hand-rolled its controls while the server hand-rolled its validation. Every
new key meant editing both, and forgetting one produced a control that silently
saved garbage. So the shape of the config lives here, once, as data: which keys
exist, what each one means in plain language, which control edits it, and what
counts as a legal value. `webui.py` serves this to the browser and re-uses the
same `coerce`/`validate` pair on the way back in, so the client can never save
something the server would not accept.

Two flags carry real meaning and are not decoration:

`restart` marks keys the daemon reads exactly once at process start (the HTTP
port, the tray icon, the logging level, the poll interval). Everything else is
re-read from the live config each tick, so it takes effect on the next pass.
Callers should surface "restart AutoStream" when any saved key sets this.

`danger` marks keys that are derived or destructive: values written by `setup`
that pair with state held elsewhere (OBS, YouTube), where a plausible-looking
edit breaks streaming in a way that only shows up at the next session.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from .cfg import DEFAULTS

Field = dict[str, Any]
Section = dict[str, Any]


def _field(path: str, label: str, help_text: str, control: str, **extra: Any) -> Field:
    """Build a field with the three flags always present, so the UI can trust them."""
    field: Field = {
        "path": path,
        "label": label,
        "help": help_text,
        "control": control,
        "advanced": bool(extra.pop("advanced", False)),
        "restart": bool(extra.pop("restart", False)),
        "danger": bool(extra.pop("danger", False)),
    }
    field.update(extra)
    return field


def _opts(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"value": v, "label": lbl} for v, lbl in pairs]


def _theme_options() -> list[dict[str, str]]:
    """Theme ids come from theme.py, which owns the palettes.

    Imported defensively: a broken or half-written theme module must not take
    the whole settings page down with it.
    """
    try:
        from . import theme

        listing = getattr(theme, "listing", None)
        items = listing() if callable(listing) else []
        opts = [
            {"value": str(t["id"]), "label": str(t.get("label") or t["id"])}
            for t in items
            if isinstance(t, dict) and t.get("id")
        ]
    except Exception:  # noqa: BLE001 - settings must render even if themes break
        opts = []
    return opts or _opts(("midnight", "Midnight"))


# YouTube's category ids are global and stable; 20 is Gaming.
_CATEGORIES = _opts(
    ("20", "Gaming"),
    ("24", "Entertainment"),
    ("22", "People and blogs"),
    ("28", "Science and technology"),
    ("27", "Education"),
    ("23", "Comedy"),
    ("10", "Music"),
    ("17", "Sport"),
    ("1", "Film and animation"),
)

# ---------------------------------------------------------------- the schema

CONFIG_SCHEMA: list[Section] = [
    {
        "id": "appearance",
        "label": "Appearance",
        "icon": "eye",
        "blurb": "How AutoStream looks and when its window shows up.",
        "advanced": False,
        "fields": [
            _field(
                "ui.theme",
                "Theme",
                "Applies straight away, here and in any browser tab you have open "
                "on this dashboard.",
                "select",
                options=_theme_options(),
                options_source="themes",
            ),
            _field(
                "ui.open_window",
                "Open the window at startup",
                "Off means AutoStream starts quietly in the notification area and "
                "you open this window from the tray icon when you want it.",
                "toggle",
                restart=True,
            ),
        ],
    },
    {
        "id": "stream",
        "label": "Stream",
        "icon": "play",
        "blurb": "What every broadcast looks like on your channel.",
        "advanced": False,
        "fields": [
            _field(
                "youtube.enabled",
                "Go live on YouTube",
                "Off turns AutoStream into a clipper and nothing else: it still "
                "spots the game, still records it and still cuts clips, and never "
                "touches YouTube. Nothing else on this page is read while it is "
                "off, and no Google sign-in is needed.",
                "toggle",
            ),
            _field(
                "youtube.privacy",
                "Who can see your streams",
                "Unlisted is the safe setting while you still half expect a mistake: "
                "the stream exists but only people you send the link to can find it. "
                "A game can override this in games.yaml.",
                "select",
                options=_opts(
                    ("public", "Public - listed on your channel and in search"),
                    ("unlisted", "Unlisted - only people with the link"),
                    ("private", "Private - only you"),
                ),
            ),
            _field(
                "youtube.latency",
                "Latency",
                "Low latency keeps chat close to what you are doing. Ultra low cuts "
                "the delay again but leaves YouTube almost no buffer, so a shaky "
                "connection turns into stutter for viewers instead of a lag spike "
                "for you.",
                "select",
                options=_opts(
                    ("normal", "Normal - most forgiving of a poor connection"),
                    ("low", "Low - a few seconds behind, chat still works"),
                    ("ultraLow", "Ultra low - closest to real time, least buffer"),
                ),
            ),
            _field(
                "youtube.category_id",
                "Category",
                "The category the finished video is filed under on your channel. "
                "Applied once the broadcast goes live.",
                "select",
                options=_CATEGORIES,
            ),
            _field(
                "youtube.made_for_kids",
                "Made for kids",
                "Leave this off unless your channel really is aimed at children. "
                "Turning it on disables live chat and strips personalised features "
                "for every viewer, on every stream.",
                "toggle",
            ),
            _field(
                "youtube.switch_policy",
                "When you switch game mid-session",
                "Renaming keeps one video for the whole evening and just rewrites "
                "its title, which is cheap and keeps your viewers. Starting a new "
                "broadcast gives each game its own VOD, but costs roughly a whole "
                "session of API quota each time and drops everyone watching.",
                "select",
                options=_opts(
                    ("rolling", "Rename the stream in place - one VOD per session"),
                    ("new_broadcast", "Start a new stream - one VOD per game"),
                ),
            ),
        ],
    },
    {
        "id": "obs",
        "label": "OBS",
        "icon": "external",
        "blurb": "How AutoStream talks to OBS Studio over its websocket.",
        "advanced": False,
        "fields": [
            _field(
                "obs.host",
                "Websocket host",
                "Leave this as localhost unless OBS runs on a different machine on "
                "your network.",
                "text",
                placeholder="localhost",
                required=True,
                max_chars=200,
                restart=True,
            ),
            _field(
                "obs.port",
                "Websocket port",
                "Must match Tools > WebSocket Server Settings in OBS. 4455 is the "
                "OBS default.",
                "number",
                min=1,
                max=65535,
                step=1,
                integer=True,
                restart=True,
            ),
            _field(
                "obs.password",
                "Websocket password",
                "From Show Connect Info in the same OBS dialog. If you leave this "
                "blank AutoStream falls back to the environment variable named "
                "below, which keeps the password out of config.yaml.",
                "password",
                placeholder="from OBS Show Connect Info",
                max_chars=200,
                restart=True,
            ),
            _field(
                "obs.path",
                "Path to obs64.exe",
                "AutoStream starts OBS from here when a session begins and OBS is "
                "not already running. If the path is wrong OBS simply never starts "
                "and the session is abandoned.",
                "text",
                placeholder=r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
                max_chars=400,
            ),
            _field(
                "obs.default_scene",
                "Default scene",
                "Switched to when a session starts, unless the game has its own "
                "scene in games.yaml. Leave blank to keep whatever scene is already "
                "showing. Use a Game Capture scene, never Display Capture: if "
                "detection is ever wrong, viewers see a black screen instead of "
                "your desktop.",
                "text",
                placeholder="Scene",
                max_chars=200,
            ),
            _field(
                "obs.launch_elevated",
                "Start OBS as administrator",
                "Games with kernel anti-cheat - Delta Force, Valorant, anything "
                "using EasyAntiCheat - block OBS's Game Capture unless OBS is "
                "running as administrator. The symptom is a completely black "
                "capture while everything else reports healthy. Turning this on "
                "means Windows asks for permission whenever AutoStream has to "
                "start OBS itself.",
                "toggle",
            ),
            _field(
                "obs.overlay_source",
                "Overlay text source",
                "Name of a Text source in OBS that AutoStream rewrites with the "
                "current game name as you switch. Leave blank if you do not have "
                "one.",
                "text",
                placeholder="Game Title",
                nullable=True,
                max_chars=200,
            ),
            _field(
                "obs.service_mode",
                "How the stream key was written into OBS",
                "Only used while setup is running. Custom RTMPS server works on "
                "every OBS build; the built-in YouTube service entry is tidier but "
                "occasionally lags behind YouTube's ingest changes. Re-run setup "
                "after changing this.",
                "select",
                options=_opts(
                    ("rtmp_custom", "Custom RTMPS server"),
                    ("rtmp_common", "OBS built-in YouTube - RTMPS service"),
                ),
                advanced=True,
            ),
        ],
    },
    {
        "id": "timing",
        "label": "Timing",
        "icon": "refresh",
        "blurb": "The delays that decide when a stream starts, retitles and ends.",
        "advanced": False,
        "fields": [
            _field(
                "timing.poll_interval",
                "Detection interval",
                "How often AutoStream looks at your running processes. Lower reacts "
                "sooner but wakes the machine more often.",
                "number",
                min=1,
                max=60,
                step=1,
                unit="seconds",
                integer=True,
                restart=True,
            ),
            _field(
                "timing.arm_delay",
                "Wait before starting",
                "A game must keep running this long before a stream starts. This is "
                "what stops a mis-click, a launcher splash or a crash on load from "
                "going live. Pressing Open and stream skips it, because you have "
                "already said what you want.",
                "number",
                min=0,
                max=900,
                step=5,
                unit="seconds",
                integer=True,
            ),
            _field(
                "timing.abort_grace",
                "Private hold before going public",
                "The broadcast sits in YouTube's private testing state for this long, "
                "with a desktop notification, so the kill switch can still cancel it. "
                "Set to 0 to go straight to public with no window to change your mind.",
                "number",
                min=0,
                max=300,
                step=5,
                unit="seconds",
                integer=True,
            ),
            _field(
                "timing.switch_delay",
                "Wait before retitling",
                "How long you must stay in a different game before the title is "
                "rewritten. Stops alt-tabbing between two games from renaming the "
                "stream every few seconds.",
                "number",
                min=0,
                max=900,
                step=5,
                unit="seconds",
                integer=True,
            ),
            _field(
                "timing.cooldown",
                "Keep the stream alive after the game closes",
                "A crash or a quick restart inside this window rejoins the same "
                "broadcast instead of splitting your evening into two VODs. Once it "
                "expires with nothing running, the session ends.",
                "number",
                min=0,
                max=3600,
                step=30,
                unit="seconds",
                integer=True,
            ),
            _field(
                "timing.ingestion_timeout",
                "Give up if YouTube sees nothing",
                "How long to wait for YouTube to actually receive video after OBS "
                "starts pushing. If nothing arrives the session is abandoned and the "
                "empty broadcast is deleted, rather than sitting there forever.",
                "number",
                min=15,
                max=600,
                step=5,
                unit="seconds",
                integer=True,
            ),
            _field(
                "timing.max_session_hours",
                "Maximum session length",
                "A hard stop. However long you keep playing, the broadcast is ended "
                "at this point; the next detection starts a fresh one.",
                "number",
                min=0.5,
                max=24,
                step=0.5,
                unit="hours",
                integer=False,
            ),
            _field(
                "timing.index_refresh_days",
                "Refresh the game index every",
                "How stale the downloaded executable-to-game-name list may get before "
                "AutoStream fetches it again. Only checked when the daemon starts.",
                "number",
                min=1,
                max=365,
                step=1,
                unit="days",
                integer=True,
            ),
        ],
    },
    {
        "id": "safety",
        "label": "Safety",
        "icon": "alert",
        "blurb": "The rails that decide when AutoStream refuses to go live.",
        "advanced": False,
        "fields": [
            _field(
                "rules.quiet_hours",
                "Quiet hours",
                "AutoStream never starts a stream by itself inside this window. A "
                "session already running is left alone. The window may cross "
                "midnight. Leave both blank to allow streaming at any hour.",
                "time_range",
                placeholder="HH:MM",
            ),
            _field(
                "rules.require_ac_power",
                "Only stream on mains power",
                "Refuses to auto-start while a laptop is on battery, because an hour "
                "of encoding empties it. Pressing Open and stream overrides this.",
                "toggle",
            ),
            _field(
                "rules.min_free_disk_gb",
                "Minimum free disk space",
                "Never start a session with less than this free on the drive "
                "AutoStream lives on. Local recording and buffering both need room, "
                "and running out mid-stream corrupts the recording.",
                "number",
                min=0,
                max=4000,
                step=5,
                unit="GB",
                integer=False,
            ),
            _field(
                "rules.kill_switch_hotkey",
                "Kill switch hotkey",
                "Works from inside a fullscreen game: pauses AutoStream and ends "
                "whatever is live right now. Leave blank to disable it.",
                "text",
                placeholder="ctrl+alt+shift+k",
                max_chars=80,
                restart=True,
            ),
            _field(
                "rules.paused_flag_file",
                "Pause marker file",
                "While a file with this name exists in the AutoStream folder, nothing "
                "will ever auto-start. Creating an empty NOSTREAM file is the "
                "no-clicking way to go dark for an evening.",
                "text",
                placeholder="NOSTREAM",
                max_chars=120,
            ),
            _field(
                "rules.quota_reserve",
                "API quota to hold back",
                "YouTube allows 10,000 API units a day and one session spends about "
                "250. AutoStream refuses to start a session that would eat into this "
                "reserve, so there is always enough left to stop a stream cleanly.",
                "number",
                min=0,
                max=9000,
                step=50,
                unit="units",
                integer=True,
            ),
            _field(
                "rules.tray_icon",
                "Show the tray icon",
                "The notification-area icon with the current phase, pause and force "
                "stop. Turning it off leaves this window as your only way in.",
                "toggle",
                restart=True,
            ),
            _field(
                "rules.control_panel",
                "Show the floating overlay",
                "The small always-on-top panel with the current phase and a stop "
                "button, so you can see what AutoStream is doing without leaving the "
                "game.",
                "toggle",
                restart=True,
            ),
            _field(
                "rules.web_dashboard",
                "Serve this dashboard",
                "Turning this off stops the local web server that draws this page, on "
                "the next start. You would then have to edit config.yaml by hand to "
                "get back in.",
                "toggle",
                advanced=True,
                danger=True,
                restart=True,
            ),
        ],
    },
    {
        "id": "titles",
        "label": "Titles",
        "icon": "copy",
        "blurb": "What your broadcasts are called and what the description says.",
        "advanced": False,
        "fields": [
            _field(
                "title.template",
                "Title template",
                "Rendered at the start of a session and again on every game switch. "
                "{game} is what you are playing RIGHT NOW and {games} is everything "
                "played this session -- use {games} if you hop between games, or a "
                "retitle will forget the earlier ones. {hook} is one line picked at "
                "random from the hooks below. {daypart} becomes morning, afternoon, "
                "evening or night from when the session actually started; {day}, "
                "{date}, {time} and {n} (the session number) also work.",
                "text",
                placeholder="{games} - {hook} | {day} {daypart} stream",
                required=True,
                max_chars=200,
            ),
            _field(
                "title.hooks",
                "Title hooks",
                "One is picked at random when a session starts and stays for the whole "
                "session, so back-to-back streams do not look identical in your "
                "channel list. Press Enter to add.",
                "taglist",
                placeholder="chill session",
                max_items=40,
                item_max_chars=80,
            ),
            _field(
                "title.max_len",
                "Maximum title length",
                "Longer titles are cut at a word boundary and given an ellipsis, "
                "never chopped mid-word. YouTube's own ceiling is 100 characters.",
                "number",
                min=20,
                max=100,
                step=1,
                unit="characters",
                integer=True,
            ),
            _field(
                "title.fallback_game",
                "Fallback game name",
                "Stands in for {game} when AutoStream can tell something is running "
                "but has no name for it.",
                "text",
                placeholder="Just Chatting",
                max_chars=100,
            ),
            _field(
                "description.template",
                "Description template",
                "Same placeholders as the title, plus {session_games} for everything "
                "played so far this session, {start_local} for when you started and "
                "{game_hashtag} for a hashtag-safe version of the game name. Rewritten "
                "on every game switch.",
                "textarea",
                placeholder="Live: {game}",
                max_chars=5000,
            ),
            _field(
                "description.tags",
                "Video tags",
                "Attached to the video once it goes live. YouTube only keeps the first "
                "30, and they matter far less than the title does.",
                "taglist",
                placeholder="gaming",
                max_items=30,
                item_max_chars=60,
            ),
        ],
    },
    {
        "id": "thumbnail",
        "label": "Thumbnail",
        "icon": "eye",
        "blurb": "Build a thumbnail from the live picture each time a stream "
                 "starts, and set it on the broadcast.",
        "advanced": False,
        "fields": [
            _field(
                "thumbnail.enabled",
                "Make a thumbnail each stream",
                "When a broadcast goes live, AutoStream grabs the frame OBS is "
                "showing and lays your logo, the game and your channel name over "
                "it. The image is always written to Videos\\AutoStream\\thumbnails "
                "whether or not it is uploaded.",
                "toggle",
            ),
            _field(
                "thumbnail.upload",
                "Set it on the broadcast",
                "Uploads the thumbnail to YouTube. Costs 50 units of daily API "
                "quota per stream on top of the usual 250, and needs a verified "
                "channel - an unverified one is refused, which is logged and "
                "otherwise ignored.",
                "toggle",
            ),
            _field(
                "thumbnail.channel_name",
                "Channel name",
                "Available to the templates below as {channel}.",
                "text",
                placeholder="YuvaNeta",
                nullable=True,
                max_chars=80,
            ),
            _field(
                "thumbnail.logo",
                "Channel logo",
                "Full path to a PNG. Transparency is strongly preferred - a logo "
                "on a white background will show its box over the gameplay.",
                "text",
                placeholder=r"C:\Users\you\Pictures\logo.png",
                nullable=True,
                max_chars=400,
            ),
            _field(
                "thumbnail.headline",
                "Headline",
                "The big line. Tokens: {game} {games} {channel} {username} {day} "
                "{daypart} {date} "
                "{time}. Keep it short - it is read at about 210 pixels wide.",
                "text",
                placeholder="{game}",
                nullable=True,
                max_chars=120,
            ),
            _field(
                "thumbnail.subtitle",
                "Second line",
                "Smaller line under the headline. Same tokens. Leave blank for none.",
                "text",
                placeholder="{channel} | {day} {daypart}",
                nullable=True,
                max_chars=160,
            ),
            _field(
                "thumbnail.base_image",
                "Fallback image",
                "Used when OBS cannot supply a frame - if it is not running, or "
                "the scene is not rendering yet.",
                "text",
                placeholder="(a flat colour is used if blank)",
                nullable=True,
                max_chars=400,
                advanced=True,
            ),
        ],
    },
    {
        "id": "screens",
        "label": "Screen savers",
        "icon": "play",
        "blurb": "Short videos for the moments the game is not the thing to look "
                 "at: going live, stepping away, and signing off. AutoStream "
                 "builds the OBS scenes for these itself -- point each one at a "
                 "file and it appears in OBS as a scene.",
        "advanced": False,
        "fields": [
            _field(
                "screens.enabled",
                "Use screen savers",
                "Off leaves OBS exactly as it is and never creates a scene.",
                "toggle",
            ),
            _field(
                "screens.starting_file",
                "Stream starting",
                "Played from the moment you go live. Give it long enough for people to arrive - the first minute of a stream is mostly people opening the tab. "
                "A video file, or the URL of an overlay page - AutoStream makes a "
                "media source for one and a browser source for the other.",
                "text",
                placeholder="C:\\Users\\you\\Videos\\starting.mp4 or https://...",
            ),
            _field(
                "screens.starting_seconds",
                "How long to hold it",
                "Seconds before the game scene takes over. The video loops if it "
                "is shorter than this.",
                "number", min=0, max=600, unit="seconds",
            ),
            _field(
                "screens.paused_file",
                "Be right back",
                "Shown for as long as the stream is paused. Pause keeps the broadcast running and only changes the picture, so this is the one people actually sit through. "
                "A video file, or the URL of an overlay page - AutoStream makes a "
                "media source for one and a browser source for the other.",
                "text",
                placeholder="C:\\Users\\you\\Videos\\brb.mp4 or https://...",
            ),
            _field(
                "screens.ending_file",
                "Thanks for watching",
                "The last thing on the stream. Held before the broadcast is completed, because afterwards there is nothing to show it on. "
                "A video file, or the URL of an overlay page - AutoStream makes a "
                "media source for one and a browser source for the other.",
                "text",
                placeholder="C:\\Users\\you\\Videos\\ending.mp4 or https://...",
            ),
            _field(
                "screens.ending_seconds",
                "How long to hold that",
                "Seconds to keep the ending card up before ending the broadcast.",
                "number", min=0, max=600, unit="seconds",
            ),
            _field(
                "screens.scene_prefix",
                "Scene name prefix",
                "What AutoStream calls the scenes it creates in OBS. Change it "
                "only if it collides with scenes you already have.",
                "text", advanced=True, placeholder="AutoStream",
            ),
        ],
    },
    {
        "id": "record",
        "label": "Recording",
        "icon": "save",
        "blurb": "Keep a clean local copy of every stream. YouTube re-encodes what "
                 "you send it and only serves a downscaled transcode back, so clips "
                 "cut from the VOD start two generations down. A local recording "
                 "does not.",
        "advanced": False,
        "fields": [
            _field(
                "record.enabled",
                "Record while streaming",
                "OBS writes the same picture to disk at the same time it streams. "
                "On a GPU with a dedicated encoder this costs no game framerate. "
                "Expect roughly 20-30 GB per hour at Indistinguishable quality.",
                "toggle",
            ),
            _field(
                "record.directory",
                "Recording folder",
                "Where OBS saves recordings. Leave blank to use whatever OBS is "
                "already set to. AutoStream never deletes anything in here.",
                "text",
                placeholder=r"C:\Users\you\Videos\AutoStream",
                nullable=True,
                max_chars=400,
            ),
            _field(
                "record.min_free_gb",
                "Never record below",
                "If the recording drive has less space than this, AutoStream streams "
                "anyway but does not record. It will not delete anything to make "
                "room.",
                "number",
                min=1,
                max=10000,
                step=5,
                unit="GB free",
                integer=True,
            ),
            _field(
                "record.warn_free_gb",
                "Warn below",
                "Show a warning on the dashboard once free space drops under this. "
                "Nothing is deleted; this is only a heads-up.",
                "number",
                min=1,
                max=10000,
                step=10,
                unit="GB free",
                integer=True,
            ),
            _field(
                "record.auto_scan",
                "Find kills after each stream",
                "When a session ends, scan its recording for kill markers in the "
                "background so the Clips page already has them ready when you open "
                "it.",
                "toggle",
            ),
        ],
    },
    {
        "id": "clips",
        "label": "Clips",
        "icon": "film",
        "blurb": "Defaults for the Clips page. Every one of these can also be changed "
                 "per run, just before cutting.",
        "advanced": False,
        "fields": [
            _field(
                "clips.output_dir",
                "Clips folder",
                "Where finished clips are written, in a subfolder per stream. Leave "
                "blank to use a 'clips' folder next to AutoStream.",
                "text",
                placeholder="(next to AutoStream)",
                nullable=True,
                max_chars=400,
            ),
            _field(
                "clips.min_kills",
                "Minimum kills per clip",
                "How busy a moment has to be before it is worth cutting. On a "
                "two-hour session, 1+ typically yields far more clips than you will "
                "watch; 3+ keeps only the standout fights.",
                "select",
                options=_opts(
                    ("1", "1 or more - everything"),
                    ("2", "2 or more - balanced"),
                    ("3", "3 or more - highlights only"),
                    ("4", "4 or more - very selective"),
                ),
            ),
            _field(
                "clips.rounds",
                "Clip whole rounds in Counter-Strike",
                "Counter-Strike is scored by the round, so a 1v3 won with one "
                "kill is a better clip than an ordinary double -- and a "
                "kill-based ranking buries it. With this on, CS2 recordings are "
                "cut per round: aces, 1vN clutches, last-alive, and chaotic "
                "rounds. Reads the scoreboard as well as the kill feed, from "
                "the same pass. Other games are unaffected.",
                "toggle",
            ),
            _field(
                "clips.whole_round",
                "Keep the whole round",
                "A Counter-Strike round runs 30 to 115 seconds, against a "
                "15-second short-form clip. On keeps the round intact, which is "
                "better for watching back; off trims to the finish, which is "
                "what fits a Short. The end is always kept either way, because "
                "in Counter-Strike the resolution is the payoff.",
                "toggle",
            ),
            _field(
                "clips.style",
                "Clip style",
                "Sets the three timings below together, using the way gaming "
                "clips are actually cut: about a second or two before the kill "
                "and two after. Most viewers who leave a short do so in the "
                "first three seconds, so a long run-up spends the whole hook on "
                "nothing happening. Choose Custom to set them yourself.",
                "select",
                options=_opts(
                    ("shortform", "Short-form - 1.5s before, 2s after, 15s clips"),
                    ("montage", "Montage cut - 1s before, 1.5s after, 6s clips"),
                    ("context", "Full context - 6s before, 4s after, 30s clips"),
                    ("custom", "Custom - use the settings below"),
                ),
            ),
            _field(
                "clips.clip_seconds",
                "Clip length",
                "A fixed length centres on the busiest few seconds of each fight. "
                "Whole moment instead follows the fight however long it runs, which "
                "can be two minutes or more.",
                "select",
                options=_opts(
                    ("10", "10 seconds"),
                    ("15", "15 seconds"),
                    ("20", "20 seconds"),
                    ("30", "30 seconds"),
                    ("45", "45 seconds"),
                    ("60", "60 seconds"),
                    ("auto", "Whole moment"),
                ),
            ),
            _field(
                "clips.pre_roll",
                "Run-up before the first kill",
                "Seconds of lead-in kept before the action starts, so a clip does not "
                "open on the shot already being fired. Around 1-2 seconds is what "
                "short-form clips use; much more and the opening is spent on nothing "
                "happening, which is where most viewers leave.",
                "number",
                min=0,
                max=30,
                step=0.5,
                unit="seconds",
                # Half seconds matter at this scale: the researched run-up is
                # 1-2s, so rounding to whole numbers would be a 50% change.
                # `integer` defaults to True, hence the explicit opt-out.
                integer=False,
            ),
            _field(
                "clips.tail_seconds",
                "Hold after the last kill",
                "Kept after the kill marker leaves the screen, so a clip never "
                "cuts while the kill feed is still running. Raise it if clips "
                "still end too abruptly; note that on a fixed length this room "
                "comes out of the action, so a short clip will hold fewer kills.",
                "number",
                min=0,
                max=15,
                step=0.5,
                unit="seconds",
                integer=False,
            ),
            _field(
                "clips.voice",
                "Spoken hook",
                "Says what the clip is over its opening seconds -- \"one versus "
                "three\", \"match point\" -- from the labels the clip already "
                "earned, and stays quiet when there is nothing worth saying. "
                "Needs a one-off 177 MB voice model download.",
                "toggle",
            ),
            # THE VOICE, AND WHAT AN UPLOAD SAYS. All four of these exist in
            # the config, are read on every run, and were not on this page --
            # so the only way to change any of them was to hand-edit the YAML
            # of the INSTALLED copy, which is not a thing anybody would guess.
            #
            # upload_privacy is the one that matters most: it decides whether a
            # clip goes out public.
            _field(
                "clips.voice_name",
                "Which voice",
                "The voice used for spoken hooks, unless a clip is given its "
                "own. Twenty-eight are installed with the model, grouped by "
                "accent -- and the honest way to choose one is to hear it, "
                "which the clip player and the review panel both let you do. "
                "The names look like af_bella (American female) or bm_george "
                "(British male).",
                "text",
                advanced=True,
            ),
            _field(
                "clips.upload_privacy",
                "Who can see an uploaded clip",
                "Applies to clips sent to YouTube from the Clips page. Unlisted "
                "is the default on purpose: an upload that turns out wrong is a "
                "quiet mistake rather than a public one. This is the default "
                "for the button; the button asks as well.",
                "select",
                options=_opts(
                    ("private", "Private - only you"),
                    ("unlisted", "Unlisted - anyone with the link"),
                    ("public", "Public - listed on the channel"),
                ),
            ),
            _field(
                "clips.upload_title",
                "Title for an uploaded clip",
                "Tokens: {caption} what the clip says on screen, {game}, "
                "{kills}, {at} where in the stream it happened, {channel}, "
                "{date}, and {n} its number in the batch. YouTube truncates a "
                "Short's title in search at about 60 characters.",
                "text",
                advanced=True,
            ),
            _field(
                "clips.upload_description",
                "Description for an uploaded clip",
                "The same seven tokens as the title. Kept short by default: a "
                "Short's description is rarely read and is not where a channel "
                "is won.",
                "text",
                advanced=True,
            ),
            _field(
                "clips.promo",
                "Sweep the leftovers into a promo",
                "Clips that fell below the minimum above are not cut on their own. "
                "They are trimmed to a few seconds each, run together into one "
                "vertical reel and captioned as an advert for the channel - which "
                "is a claim about you rather than about the play, and so is the one "
                "caption a single kill can honestly carry.",
                "toggle",
            ),
            _field(
                "clips.promo_caption",
                "What the promo says",
                "Held on screen for the whole reel. Emoji work.",
                "text",
                placeholder="LIVE MOST EVENINGS",
            ),
            _field(
                "clips.music",
                "Music for the reel",
                "A track you own. Given one, the montage is joined by a beat-synced "
                "reel: cuts on the beat, act changes on phrase boundaries, and the "
                "session's best moment on the drop. Leave blank for no reel.",
                "text",
                placeholder=r"C:\Users\you\Music\track.flac",
            ),
            _field(
                "clips.arc",
                "Tell the session's story",
                "How the reel is arranged. On keeps the clips in the order they "
                "happened and offsets the music instead, so the drop lands on the "
                "best moment - opening, the rounds you lost, the round that turned "
                "it, the push, match point. Off puts the multi-kills in the busiest "
                "section, which needs no round labels at all.",
                "toggle",
            ),
            _field(
                "clips.order",
                "How the reel is ordered",
                "Story plays the session in the order it happened, with the best "
                "moment on the drop. Build goes weakest to strongest, so the reel "
                "escalates and always ends on the peak. Hook opens on the best "
                "moment, which is where a Short is won or lost.",
                "select",
                options=_opts(
                    ("story", "Story - as it happened"),
                    ("build", "Build - weakest to strongest"),
                    ("hook", "Hook - best moment first"),
                ),
            ),
            _field(
                "clips.vertical_mode",
                "Vertical versions",
                "Also export a 9:16 copy for Shorts and Reels. Zoom keeps the "
                "crosshair large and loses the edges of the screen; Fit keeps the "
                "whole frame over a blurred background.",
                "select",
                options=_opts(
                    ("crop", "Zoom to centre - best for shooters"),
                    ("fit", "Fit whole frame on a blurred background"),
                    ("none", "Do not make vertical copies"),
                ),
            ),
            _field(
                "clips.transition",
                "Montage transition",
                "How one clip becomes the next in the combined montage.",
                "select",
                options=_opts(
                    ("fade", "Fade"),
                    ("fadeblack", "Dip to black"),
                    ("dissolve", "Dissolve"),
                    ("radial", "Swirl"),
                    ("zoomin", "Zoom"),
                    ("slideleft", "Slide"),
                    ("pixelize", "Pixelize"),
                    ("wipeleft", "Wipe"),
                    ("cut", "Hard cut - no transition"),
                    ("mixed", "Mixed - a different one each time"),
                ),
            ),
            _field(
                "clips.transition_ms",
                "Transition length",
                "Long transitions eat the clips on both sides of them, so this is "
                "capped automatically when the clips are short.",
                "number",
                min=100,
                max=2000,
                step=50,
                unit="ms",
                integer=True,
            ),
            _field(
                "clips.encoder",
                "Encoder",
                "Automatic uses your GPU when it can, which is several times faster. "
                "Switch to CPU if clips come out corrupted.",
                "select",
                options=_opts(
                    ("auto", "Automatic - GPU when available"),
                    ("nvenc", "NVIDIA GPU"),
                    ("libx264", "CPU"),
                ),
                advanced=True,
            ),
            _field(
                "clips.ffmpeg_path",
                "ffmpeg folder",
                "Only needed if AutoStream cannot find ffmpeg on its own. Point this "
                "at the folder containing ffmpeg.exe.",
                "text",
                placeholder="(found automatically)",
                nullable=True,
                max_chars=400,
                advanced=True,
            ),
        ],
    },
    {
        "id": "logging",
        "label": "Logging",
        "icon": "logs",
        "blurb": "How much AutoStream writes down, and for how long.",
        "advanced": False,
        "fields": [
            _field(
                "logging.level",
                "Log level",
                "Info is the right everyday setting. Debug is loud, but it is what "
                "shows you why detection or ingestion is misbehaving.",
                "select",
                options=_opts(
                    ("DEBUG", "Debug - every decision, very noisy"),
                    ("INFO", "Info - phase changes and sessions"),
                    ("WARNING", "Warning - only things that look wrong"),
                    ("ERROR", "Error - only failures"),
                ),
                restart=True,
            ),
            _field(
                "logging.keep_days",
                "Keep logs for",
                "The log rotates at midnight; older files past this many days are "
                "deleted.",
                "number",
                min=1,
                max=365,
                step=1,
                unit="days",
                integer=True,
                restart=True,
            ),
        ],
    },
    {
        "id": "advanced",
        "label": "Advanced",
        "icon": "settings",
        "blurb": "Written by setup or by the daemon itself. Change these only if you "
                 "know exactly why.",
        "advanced": True,
        "fields": [
            _field(
                "youtube.stream_id",
                "Reusable stream id",
                "The permanent YouTube ingest that every broadcast is bound to, "
                "created once by setup. If this is wrong or empty, broadcasts are "
                "created and then never receive any video. Re-run setup to replace "
                "it.",
                "readonly",
                danger=True,
                restart=True,
                max_chars=200,
            ),
            _field(
                "youtube.ingestion_address",
                "Ingestion address",
                "The RTMPS server setup pushed into OBS alongside your stream key. "
                "Editing it here does not touch OBS, so the two stop agreeing and "
                "the next session never reaches YouTube.",
                "readonly",
                danger=True,
                restart=True,
                max_chars=400,
            ),
            _field(
                "obs.password_env",
                "OBS password environment variable",
                "Consulted when the OBS password above is blank, so the password can "
                "live in your user environment instead of in config.yaml. A change "
                "here needs a restart, because the daemon only sees the environment "
                "it was started with.",
                "text",
                placeholder="AUTOSTREAM_OBS_PW",
                max_chars=120,
                advanced=True,
                restart=True,
            ),
            _field(
                "rules.web_port",
                "Dashboard port",
                "TCP port this dashboard listens on. Change it only if something "
                "else on the machine already owns 8787.",
                "number",
                min=1024,
                max=65535,
                step=1,
                integer=True,
                advanced=True,
                restart=True,
            ),
            _field(
                "rules.web_token",
                "Dashboard token",
                "Appended to every request this page makes. Anyone on your network "
                "holding it can read your chat and stop your stream. Generated on "
                "first run; clear it and restart to have a new one issued, which also "
                "logs out every other tab.",
                "password",
                advanced=True,
                danger=True,
                restart=True,
                max_chars=200,
            ),
        ],
    },
]

FIELDS_BY_PATH: dict[str, Field] = {
    f["path"]: f for section in CONFIG_SCHEMA for f in section["fields"]
}

# ---------------------------------------------------------------- conversion

_TIME_RE = re.compile(r"^([01]?[0-9]|2[0-3]):([0-5][0-9])$")
_TEXTY = ("text", "password", "textarea", "readonly")


class _SafeVars(dict):
    """Placeholder lookup that never fails, mirroring titles.SafeDict."""

    def __missing__(self, key: str) -> str:
        return ""


def _select_values(field: Field) -> list[str]:
    """Legal values for a select, re-reading dynamic sources at call time."""
    if field.get("options_source") == "themes":
        return [o["value"] for o in _theme_options()]
    return [str(o["value"]) for o in field.get("options") or []]


def _fmt_num(n: float | int) -> str:
    if isinstance(n, float) and n == int(n):
        return str(int(n))
    return str(n)


def _with_unit(field: Field, n: float | int) -> str:
    unit = field.get("unit")
    return f"{_fmt_num(n)} {unit}" if unit else _fmt_num(n)


def _as_text(value: Any) -> tuple[str, str | None]:
    if value is None:
        return "", None
    if isinstance(value, str):
        return value, None
    if isinstance(value, bool):
        return "", "Expected text."
    if isinstance(value, (int, float)):
        return str(value), None
    return "", "Expected text."


def _convert_number(field: Field, value: Any) -> tuple[Any, str | None]:
    if isinstance(value, bool):
        return None, "Enter a number."
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None, "Enter a number."
        try:
            num: float = float(text)
        except ValueError:
            return None, "Enter a number."
    elif isinstance(value, (int, float)):
        num = float(value)
    else:
        return None, "Enter a number."

    if num != num or num in (float("inf"), float("-inf")):  # NaN / infinity
        return None, "Enter a number."

    out: float | int = num
    if field.get("integer", True):
        if abs(num - round(num)) > 1e-9:
            return None, "Enter a whole number."
        out = int(round(num))

    low, high = field.get("min"), field.get("max")
    if low is not None and out < low:
        return None, f"Must be {_with_unit(field, low)} or more."
    if high is not None and out > high:
        return None, f"Must be {_with_unit(field, high)} or less."
    return out, None


def _convert_select(field: Field, value: Any) -> tuple[Any, str | None]:
    if isinstance(value, bool) or value is None:
        return None, "Choose one of the listed options."
    text = value.strip() if isinstance(value, str) else str(value)
    legal = _select_values(field)
    if legal and text not in legal:
        return None, "Choose one of the listed options."
    return text, None


def _convert_text(field: Field, value: Any) -> tuple[Any, str | None]:
    text, err = _as_text(value)
    if err:
        return None, err
    if field["control"] == "textarea":
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    else:
        text = text.strip()
    limit = field.get("max_chars")
    if limit and len(text) > limit:
        return None, f"Keep this under {limit} characters."
    if not text:
        if field.get("required"):
            return None, "This cannot be left empty."
        if field.get("nullable"):
            # config.yaml stores "unset" as null here, not as an empty string.
            return None, None
    return text, None


def _convert_taglist(field: Field, value: Any) -> tuple[Any, str | None]:
    if isinstance(value, str):
        raw_items: list[Any] = re.split(r"[,\n]", value)
    elif isinstance(value, (list, tuple)):
        raw_items = list(value)
    else:
        return None, "Expected a list of entries."

    item_limit = field.get("item_max_chars", 120)
    out: list[str] = []
    for raw in raw_items:
        if raw is None:
            continue
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            return None, "Every entry must be text."
        item = str(raw).strip()
        if not item:
            continue
        if len(item) > item_limit:
            return None, f"Each entry must be under {item_limit} characters."
        if item not in out:
            out.append(item)

    max_items = field.get("max_items")
    if max_items and len(out) > max_items:
        return None, f"At most {max_items} entries."
    return out, None


def _convert_clock(part: Any) -> tuple[str | None, str | None]:
    """One end of a time range, as a normalised HH:MM string or None if blank."""
    if part is None:
        return None, None
    if isinstance(part, bool):
        return None, "Use 24-hour times like 23:30."
    if isinstance(part, int):
        # YAML 1.1 reads an unquoted 9:00 as sexagesimal minutes, so a config
        # written by hand can arrive here as an integer rather than a string.
        if 0 <= part < 1440:
            return f"{part // 60:02d}:{part % 60:02d}", None
        return None, "Use 24-hour times like 23:30."
    if not isinstance(part, str):
        return None, "Use 24-hour times like 23:30."
    text = part.strip()
    if not text:
        return None, None
    m = _TIME_RE.match(text)
    if not m:
        return None, "Use 24-hour times like 23:30."
    return f"{int(m.group(1)):02d}:{m.group(2)}", None


def _convert_time_range(_field: Field, value: Any) -> tuple[Any, str | None]:
    if value is None or value == "":
        return [], None
    if not isinstance(value, (list, tuple)):
        return None, "Expected a start and an end time."
    parts = list(value)
    if not parts:
        return [], None
    if len(parts) != 2:
        return None, "Expected a start and an end time."

    start, err = _convert_clock(parts[0])
    if err:
        return None, err
    end, err = _convert_clock(parts[1])
    if err:
        return None, err
    if start is None and end is None:
        return [], None
    if start is None or end is None:
        return None, "Set both times, or clear both to allow streaming at any hour."
    if start == end:
        return None, "Start and end cannot be the same time."
    return [start, end], None


def _check_template(value: Any) -> str | None:
    """Reject a template whose braces would blow up at render time."""
    if not isinstance(value, str) or not value:
        return None
    try:
        value.format_map(_SafeVars())
    except (ValueError, IndexError, KeyError):
        return "Unbalanced { } in the template."
    return None


def _check_flag_file(value: Any) -> str | None:
    if isinstance(value, str) and value and (("/" in value) or ("\\" in value)
                                             or (":" in value)):
        return "Use a plain file name, with no folders."
    return None


def _check_hotkey(value: Any) -> str | None:
    if isinstance(value, str) and value and any(c.isspace() for c in value):
        return "Join keys with +, without spaces, like ctrl+alt+shift+k."
    return None


# Per-key checks that do not fall out of the control type. Run after conversion.
_EXTRA_CHECKS: dict[str, Callable[[Any], str | None]] = {
    "title.template": _check_template,
    "description.template": _check_template,
    "rules.paused_flag_file": _check_flag_file,
    "rules.kill_switch_hotkey": _check_hotkey,
}


def _convert(field: Field, value: Any) -> tuple[Any, str | None]:
    """(converted value, error). The one place a raw JSON value becomes config."""
    control = field["control"]
    if control == "toggle":
        if not isinstance(value, bool):
            return None, "Expected true or false."
        return value, None
    if control == "number":
        out, err = _convert_number(field, value)
    elif control == "select":
        out, err = _convert_select(field, value)
    elif control == "taglist":
        out, err = _convert_taglist(field, value)
    elif control == "time_range":
        out, err = _convert_time_range(field, value)
    elif control in _TEXTY:
        out, err = _convert_text(field, value)
    else:
        return None, "Unsupported setting type."
    if err:
        return None, err

    check = _EXTRA_CHECKS.get(field["path"])
    if check is not None:
        err = check(out)
        if err:
            return None, err
    return out, None


# ---------------------------------------------------------------- public API


def coerce(path: str, value: Any) -> Any:
    """Cast a JSON value to the type config.yaml wants for `path`.

    Never raises. If the value cannot be converted it is handed back untouched,
    so callers must ask validate() whether it was actually acceptable.
    """
    field = FIELDS_BY_PATH.get(path)
    if field is None:
        return value
    out, err = _convert(field, value)
    return value if err else out


def validate(path: str, value: Any) -> str | None:
    """Return a message fit to show under the control, or None if the value is fine."""
    field = FIELDS_BY_PATH.get(path)
    if field is None:
        return "Unknown setting."
    return _convert(field, value)[1]


def _dig(source: Any, parts: list[str]) -> tuple[Any, bool]:
    cur = source
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return None, False
        cur = cur[part]
    return cur, True


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def flatten(config: dict) -> dict[str, Any]:
    """Config dict -> {dotted path: value} covering every field in the schema.

    Missing keys fall back to cfg.DEFAULTS rather than being omitted, so the
    settings page always has a value to render. Values are normalised through
    the same converters the save path uses, which is what turns a hand-edited
    quiet_hours into the [HH:MM, HH:MM] the control expects.
    """
    out: dict[str, Any] = {}
    for path, field in FIELDS_BY_PATH.items():
        parts = path.split(".")
        value, found = _dig(config or {}, parts)
        if not found:
            value, _ = _dig(DEFAULTS, parts)
        converted, err = _convert(field, value)
        out[path] = _jsonable(value if err else converted)
    return out


def unflatten(values: dict[str, Any]) -> dict[str, Any]:
    """{dotted path: value} -> nested dict, for writing back to config.yaml."""
    out: dict[str, Any] = {}
    for path, value in (values or {}).items():
        parts = str(path).split(".")
        cur = out
        for part in parts[:-1]:
            nxt = cur.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[part] = nxt
            cur = nxt
        cur[parts[-1]] = value
    return out
