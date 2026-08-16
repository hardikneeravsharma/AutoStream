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


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, SECRETS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
