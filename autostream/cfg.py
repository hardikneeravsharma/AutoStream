"""Config loading with dotted access and sane defaults."""
from __future__ import annotations

import copy
import os
import threading
from collections.abc import Iterable, Mapping
from typing import Any

import yaml

from . import paths

DEFAULTS: dict[str, Any] = {
    "youtube": {
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


def save_games(data: dict) -> None:
    paths.GAMES_FILE.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
