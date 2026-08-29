"""Config loading with dotted access and sane defaults."""
from __future__ import annotations

import copy
import logging
import os
import threading
from collections.abc import Iterable, Mapping
from typing import Any

import yaml

from . import paths

log = logging.getLogger("autostream.cfg")

DEFAULTS: dict[str, Any] = {
    "youtube": {
        # Off turns AutoStream into a clipper: it still spots the game, still
        # records it and still cuts clips, and never touches the YouTube API.
        # Nothing below this line is read while it is off.
        "enabled": True,
        "privacy": "unlisted",
        "latency": "low",
        "category_id": "20",
        "stream_id": "",
        "ingestion_address": "",
        "made_for_kids": False,
        "switch_policy": "rolling",
    },
    "obs": {
        "host": "localhost",
        "port": 4455,
        "password": "",
        "password_env": "AUTOSTREAM_OBS_PW",
        "path": r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
        "default_scene": "",
        "overlay_source": None,
        "service_mode": "rtmp_custom",
        "launch_elevated": False,
    },
    "timing": {
        "poll_interval": 3,
        "arm_delay": 30,
        "abort_grace": 20,
        "switch_delay": 60,
        "cooldown": 300,
        "ingestion_timeout": 90,
        "max_session_hours": 8,
        "index_refresh_days": 7,
    },
    "rules": {
        "quiet_hours": [],
        "require_ac_power": True,
        "min_free_disk_gb": 25,
        "kill_switch_hotkey": "ctrl+alt+shift+k",
        "paused_flag_file": "NOSTREAM",
        "quota_reserve": 500,
        # Enforced INDEPENDENTLY of the quota arithmetic. videos.insert has
        # had two very different published prices in a year, and a wrong
        # estimate must not be able to spend a day's streaming on uploads.
        "upload_daily_max": 5,
        "tray_icon": True,
        "control_panel": True,
        "web_dashboard": True,
        "web_port": 8787,
        "web_token": "",
    },
    "title": {
        "template": "{game} — live",
        "hooks": ["live"],
        "max_len": 100,
        "fallback_game": "Just Chatting",
    },
    "description": {"template": "Live: {game}", "tags": ["gaming", "live"]},
    # Local recording, for clip production. What YouTube keeps is a re-encode
    # of the stream, and Studio only serves a 720p transcode of that, so clips
    # cut from the VOD start two generations down. Recording writes the same
    # canvas straight to disk instead.
    #
    # Nothing here deletes anything. Below min_free_gb AutoStream declines to
    # start a recording and streams anyway, rather than making room for itself.
    "record": {
        "enabled": False,
        "directory": "",              # blank -> whatever OBS is already set to
        "min_free_gb": 50,
        "warn_free_gb": 100,
        "auto_scan": True,            # find kills as soon as a session ends
    },
    "clips": {
        # Publishing is public, attributed and awkward to undo, so it never
        # happens by itself -- there is deliberately no auto_upload. These only
        # decide what the button does when a person presses it.
        "upload_privacy": "unlisted",
        "upload_title": "{caption} - {game}",
        "upload_description": "Cut automatically by AutoStream from a {game} stream.",
        "output_dir": "",             # blank -> <root>/clips
        "ffmpeg_path": "",            # blank -> auto-discover
        # Both are strings because they are `select` fields, and the settings
        # form round-trips select values as strings. Keeping the default an int
        # would mean the type silently changed the first time it was saved.
        "min_kills": "2",
        # style presets these three; "custom" leaves them alone. See
        # clips/plan.py STYLES for where the numbers come from.
        "style": "shortform",
        "clip_seconds": "15",         # or "auto" for the whole burst
        "pre_roll": 1.5,
        "tail_seconds": 2,
        "vertical_mode": "crop",
        "transition": "fade",
        "transition_ms": 500,
        "encoder": "auto",
        # Counter-Strike only. Games whose profile reads the scoreboard clip
        # whole ROUNDS instead of bursts of kills; see clips/rounds.py.
        "rounds": True,
        # A round runs 30-115s. On keeps all of it, which is what you want to
        # watch back; off trims to the finish, which is what fits a Short.
        "whole_round": True,
        # Spoken hook over the run-up of each vertical clip. Off by default
        # because it needs a 177 MB model download -- see clips/voice.py.
        "voice": False,
        "voice_name": "am_michael",
        # A music bed turns the montage into a beat-synced reel: cuts on the
        # beat, the best moment on the drop. Blank means no reel is made --
        # the track has to be one the user owns, so there is nothing sensible
        # to default it to.
        "music": "",
        # How the reel is arranged. On tells the session's story in order (see
        # clips/story.py); off puts the multi-kills in the busy section and the
        # best clip on the drop, which needs no round labels at all.
        "arc": True,
        # Which arrangement, when arc is on: story / build / hook.
        "order": "story",
        # Sweep the clips that fell below min_kills into one promo reel rather
        # than cutting them individually. A lone kill rarely earns a post; a
        # dozen of them cut short and run together is a channel advert.
        "promo": True,
        "promo_caption": "LIVE MOST EVENINGS \U0001F3AE",
    },
    # The three screen savers. AutoStream builds the OBS scenes itself from
    # these files -- see screens.py -- so what is configured is a video, not a
    # scene name.
    "screens": {
        "enabled": False,
        "scene_prefix": "AutoStream",
        "starting_file": "",
        "starting_seconds": 10,
        # No hold: the be-right-back card stays up until Resume, which is the
        # whole reason pause keeps the broadcast alive.
        "paused_file": "",
        "ending_file": "",
        "ending_seconds": 15,
    },
    # Composed from a live OBS frame each time a session goes live. Templates
    # take the same tokens as the title ones.
    "thumbnail": {
        "enabled": False,
        "upload": True,             # false = write the file, never call the API
        "channel_name": "",
        "logo": "",                 # PNG, transparency preferred
        "base_image": "",           # fallback when OBS gives no frame
        "headline": "{game}",
        "subtitle": "{channel} | {day} {daypart}",
    },
    "ui": {"theme": "midnight", "open_window": True},
    "logging": {"level": "INFO", "keep_days": 7},
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Section(dict):
    """dict that also supports attribute access: cfg.obs.port"""

    def __getattr__(self, item):
        try:
            v = self[item]
        except KeyError as e:
            raise AttributeError(item) from e
        return Section(v) if isinstance(v, dict) else v

    def __setattr__(self, key, value):
        self[key] = value


class Config(Section):
    @property
    def obs_password(self) -> str:
        pw = self["obs"].get("password") or ""
        if not pw:
            env = self["obs"].get("password_env")
            if env:
                pw = os.environ.get(env, "")
        return pw


def load() -> Config:
    raw = {}
    if paths.CONFIG_FILE.exists():
        raw = yaml.safe_load(paths.CONFIG_FILE.read_text(encoding="utf-8")) or {}
    return Config(_deep_merge(DEFAULTS, raw))


def refresh_in_place(config: Config) -> Config:
    """Re-read config.yaml into an EXISTING Config object.

    cmd_run builds one Config at startup and hands that same instance to the
    engine, watcher, game index, YouTube and OBS clients. They all read through
    it on every tick (Section.__getattr__ walks the live dict), so replacing the
    contents here makes a saved setting take effect on the next pass instead of
    on the next restart.

    Rebinding the name would not work — the five components hold the object, not
    the name — hence clear()+update() rather than `config = load()`.
    """
    fresh = load()
    config.clear()
    config.update(fresh)
    return config


# The web UI is served by a ThreadingHTTPServer, so two saves can arrive at
# once. Every write goes through one read-modify-write under this lock or the
# later one silently discards the earlier one's keys.
_WRITE_LOCK = threading.Lock()


def load_raw() -> dict[str, Any]:
    """The on-disk overlay only, without DEFAULTS merged in.

    Callers that want to know what is *written* (as opposed to what is in
    effect) need this: load() cannot tell a value from a default.
    """
    if not paths.CONFIG_FILE.exists():
        return {}
    raw = yaml.safe_load(paths.CONFIG_FILE.read_text(encoding="utf-8"))
    # A file of nothing but comments parses as None, and a stray list or scalar
    # document is not something we can merge keys into.
    return raw if isinstance(raw, dict) else {}


def _split_path(path: str) -> tuple[str, str]:
    section, dot, key = str(path).partition(".")
    if not dot or not section or not key or "." in key:
        raise ValueError(f"bad config path {path!r}: expected 'section.key'")
    return section, key


def save_fields(values: Mapping[str, Any], *, delete: Iterable[str] = ()) -> dict[str, Any]:
    """Merge many dotted keys into config.yaml in ONE atomic pass.

        save_fields({"obs.port": 4455, "rules.quiet_hours": ["03:30", "09:00"]})

    `delete` removes keys so DEFAULTS takes over again ("reset to default").
    Returns the mapping that was written (the overlay, not the merged config).

    Every unrelated key survives, missing sections are created, and the file is
    replaced rather than rewritten in place: config.yaml is either the old
    document or the new one, never a truncated half of either. That matters
    because load() raises on invalid YAML, and a corrupt config bricks the
    daemon on its next start with no way back through the UI.
    """
    with _WRITE_LOCK:
        # Split every path before touching disk, so a malformed key aborts the
        # whole call instead of writing the ones that came before it.
        writes = [(_split_path(p), v) for p, v in (values or {}).items()]
        drops = [_split_path(p) for p in delete]

        original = paths.CONFIG_FILE.read_bytes() if paths.CONFIG_FILE.exists() else None
        raw = load_raw()

        for (section, key), value in writes:
            cur = raw.get(section)
            if not isinstance(cur, dict):
                # `obs:` with only comments under it parses as None; setdefault
                # would hand that back and the assignment would blow up.
                cur = {}
            cur[key] = value
            raw[section] = cur

        for section, key in drops:
            cur = raw.get(section)
            if isinstance(cur, dict):
                cur.pop(key, None)
                if not cur:
                    raw.pop(section, None)

        # sort_keys=False keeps the on-disk order; new sections append.
        text = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
        if yaml.safe_load(text) != raw:
            raise ValueError("config.yaml would not survive a round-trip; nothing written")

        paths.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = paths.CONFIG_FILE.with_suffix(".yaml.tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            if original is not None:
                paths.CONFIG_FILE.with_suffix(".yaml.bak").write_bytes(original)
            # Same directory means same volume, which is what makes this atomic.
            os.replace(tmp, paths.CONFIG_FILE)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        return raw


def save_field(section: str, key: str, value: Any) -> None:
    """Write a single value back into config.yaml, preserving everything else.

    Used by `setup` to persist stream_id / ingestion_address.
    """
    save_fields({f"{section}.{key}": value})


def load_games() -> dict:
    if not paths.GAMES_FILE.exists():
        return {"games": {}, "blocklist": [], "never_stream_if_running": []}
    data = yaml.safe_load(paths.GAMES_FILE.read_text(encoding="utf-8")) or {}
    # A YAML key with only comments under it parses as None, not {} — coerce,
    # or `games["games"][exe] = ...` blows up during setup.
    if not isinstance(data.get("games"), dict):
        data["games"] = {}
    for key in ("blocklist", "never_stream_if_running"):
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


def save_game_field(key: str, field: str, value) -> bool:
    """Set one field on one game in games.yaml. -> whether it was written.

    The generic form of what clips/profiles.save_username does for the in-game
    name. Kept here rather than there because a thumbnail has nothing to do
    with clip detection, and `cfg` is the module that owns games.yaml.
    """
    key = str(key or "").strip().lower()
    field = str(field or "").strip()
    if not key or not field:
        return False
    try:
        data = load_games()
        games = data.setdefault("games", {})
        entry = games.get(key)
        if not isinstance(entry, dict):
            entry = {}
            games[key] = entry
        if value in (None, ""):
            entry.pop(field, None)
        else:
            entry[field] = value
        save_games(data)
    except (OSError, KeyError, TypeError, ValueError) as e:
        log.warning("could not set %s for %r: %s", field, key, e)
        return False
    return True


def save_games(data: dict) -> None:
    paths.GAMES_FILE.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
