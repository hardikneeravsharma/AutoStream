"""Single source of truth for where everything lives on disk."""
from __future__ import annotations

import os
from pathlib import Path

# project root = parent of the `autostream` package directory
ROOT = Path(os.environ.get("AUTOSTREAM_HOME", Path(__file__).resolve().parent.parent))

CONFIG_DIR = ROOT / "config"
SECRETS_DIR = ROOT / "secrets"
LOGS_DIR = ROOT / "logs"

CONFIG_FILE = CONFIG_DIR / "config.yaml"
GAMES_FILE = CONFIG_DIR / "games.yaml"
INDEX_CACHE = CONFIG_DIR / "index.cache.json"

CLIENT_SECRET = SECRETS_DIR / "client_secret.json"
TOKEN_FILE = SECRETS_DIR / "token.json"

STATE_FILE = ROOT / "state.json"
LOG_FILE = LOGS_DIR / "autostream.log"

# User video data. Deliberately OUTSIDE the application folder.
#
# For a frozen build ROOT is dist\AutoStream, and PyInstaller deletes that
# whole directory on every rebuild. Keeping the session journal and gigabytes
# of finished clips in there meant a rebuild silently destroyed both -- which
# it duly did, taking a stream's history and every clip cut from it. Video and
# its metadata outlive any particular installation, so they live beside the
# recordings instead.
VIDEO_HOME = Path(os.environ.get("AUTOSTREAM_VIDEO_HOME",
                                 Path.home() / "Videos" / "AutoStream"))

# One line per finished session. state.json only ever holds the CURRENT
# session and is wiped when it ends, so without this nothing survives to say
# which game was played on which broadcast.
HISTORY_FILE = VIDEO_HOME / "history.jsonl"

# VALORANT's own record of each match, fetched while the game is running and
# read when the recording is clipped -- see clips/valorant_match.py. Beside the
# recordings for the same reason the history is: it describes a recording, it
# cannot be fetched again once the client has closed, and a rebuild deletes
# anything inside the application folder.
MATCHES_DIR = VIDEO_HOME / "matches"

# Optional model downloads -- currently the Kokoro voice for spoken hooks.
#
# Outside ROOT for the same reason as everything else here: a frozen build's
# ROOT is deleted on every rebuild, and re-downloading a 177 MB model because
# someone rebuilt the app is not acceptable. Not inside CONFIG_DIR either --
# the share-package build strips that wholesale to remove credentials.
MODELS_DIR = Path(os.environ.get("AUTOSTREAM_MODELS", VIDEO_HOME / "models"))

# Clip output, and the per-game kill-marker detector profiles that drive it.
CLIPS_DIR = VIDEO_HOME / "clips"
CLIP_PROFILES = CONFIG_DIR / "clip_profiles.yaml"

# Templates the user calibrated. Writable, and personal to their footage.
CLIP_TEMPLATES = CONFIG_DIR / "clip_templates"

# Templates that ship with AutoStream. Inside the package, NOT in config/,
# for two reasons: the share-package build deletes config/ wholesale to strip
# credentials, and a read-only bundled asset has no business living in a
# directory the user is invited to edit.
CLIP_TEMPLATES_BUILTIN = Path(__file__).resolve().parent / "clips" / "templates"


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, SECRETS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
