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
                "{game} is what you are playing and {hook} is one line picked at "
                "random from the hooks below; {day}, {date}, {time} and {n} (the "
                "session number) also work.",
                "text",
                placeholder="{game} - {hook} | {day} night stream",
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
