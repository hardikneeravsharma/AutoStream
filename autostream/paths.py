r"""Single source of truth for where everything lives on disk.

TWO ROOTS, AND THE DIFFERENCE MATTERS
    ROOT is where the PROGRAM is. DATA_HOME is where the USER'S OWN FILES are.
    They used to be the same directory, and that is the root cause of every
    upgrade problem this app has:

      * unzip a new build over the old one and orphaned files from the previous
        build stay behind, where they can shadow the new ones;
      * unzip it somewhere ELSE and the config, the YouTube token and the
        StreamElements links are stranded in the old folder -- the "new
        install" starts unconfigured and asks you to sign in to YouTube again;
      * and a rebuild deletes dist\AutoStream outright, which is why the build
        script had to learn to carry the live installation across.

    Splitting them means an installer can replace the program wholesale and
    never come near anything the user made. It is also simply where Windows
    programs are supposed to put this: %LOCALAPPDATA%.

WHICH ROOT APPLIES WHEN
    Frozen build  -> DATA_HOME is %LOCALAPPDATA%\AutoStream, migrated once from
                     the old in-folder location by migrate_data_home().
    Source tree   -> DATA_HOME is the repo, exactly as before. Running from a
                     checkout keeps config\ and secrets\ beside the code where
                     they are easy to look at, and the test suite pins
                     AUTOSTREAM_HOME to the repo anyway.
    AUTOSTREAM_HOME set -> that wins in both cases. Portable installs, a second
                     profile, and the tests all rely on it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Where the PROGRAM is.
#
#   AUTOSTREAM_HOME     a person saying "keep everything in this one folder".
#                       Wins outright: it sets the data home too, below.
#   AUTOSTREAM_APP_DIR  the frozen launcher saying where the exe lives, because
#                       a bundled __file__ points inside the bundle. Says
#                       nothing about where the user's files belong.
#   neither             a source checkout: the parent of this package.
ROOT = Path(os.environ.get("AUTOSTREAM_HOME")
            or os.environ.get("AUTOSTREAM_APP_DIR")
            or Path(__file__).resolve().parent.parent)

FROZEN = bool(getattr(sys, "frozen", False))


def _default_data_home() -> Path:
    """Where the user's own files live when nothing overrides it."""
    if os.environ.get("AUTOSTREAM_HOME"):
        return ROOT                      # explicit wins, portable or a test
    if not FROZEN:
        return ROOT                      # a checkout keeps everything together
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "AutoStream"
    # Not Windows, or a stripped environment. XDG-ish, and still not ROOT.
    return Path(os.environ.get("XDG_DATA_HOME",
                               Path.home() / ".local" / "share")) / "autostream"


DATA_HOME = _default_data_home()

# The files that BELONG TO THE USER. An installer may replace everything under
# ROOT; it must never touch anything under DATA_HOME.
CONFIG_DIR = DATA_HOME / "config"
SECRETS_DIR = DATA_HOME / "secrets"
LOGS_DIR = DATA_HOME / "logs"

# What the program SHIPS WITH: defaults to seed a fresh install from, and the
# only config that belongs beside the program rather than beside the user.
SEED_CONFIG_DIR = ROOT / "config"

CONFIG_FILE = CONFIG_DIR / "config.yaml"
GAMES_FILE = CONFIG_DIR / "games.yaml"
INDEX_CACHE = CONFIG_DIR / "index.cache.json"

CLIENT_SECRET = SECRETS_DIR / "client_secret.json"
TOKEN_FILE = SECRETS_DIR / "token.json"

STATE_FILE = DATA_HOME / "state.json"
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


# ---------------------------------------------------------------- migration

# What moves out of the program folder and in beside the user, the first time a
# build that knows about DATA_HOME runs. Ordered so that the credentials go
# first: if anything fails half way, the thing worth keeping is already across.
MIGRATE = ("secrets", "config", "logs")
MIGRATE_FILES = ("state.json",)


def migrate_data_home(log=None) -> list[str]:
    """Move an older install's own files out of the program folder.

    -> what moved, for the log. Copies rather than moves: an upgrade that goes
    wrong should leave the old installation working, and the old copy costs
    kilobytes. Never overwrites -- anything already in DATA_HOME wins, because
    it is by definition newer than a folder we are migrating away from.
    """
    import shutil

    if DATA_HOME == ROOT:
        return []                        # a checkout, or an explicit HOME
    moved: list[str] = []
    for name in MIGRATE:
        src, dst = ROOT / name, DATA_HOME / name
        if not src.is_dir():
            continue
        for item in src.rglob("*"):
            if not item.is_file():
                continue
            target = dst / item.relative_to(src)
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(item, target)
                moved.append(str(target.relative_to(DATA_HOME)))
            except OSError as e:         # pragma: no cover - disk-level
                if log:
                    log.warning("could not migrate %s: %s", item.name, e)
    for name in MIGRATE_FILES:
        src, dst = ROOT / name, DATA_HOME / name
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
                moved.append(name)
            except OSError as e:         # pragma: no cover
                if log:
                    log.warning("could not migrate %s: %s", name, e)
    return moved


def seed_config(log=None) -> list[str]:
    """Fill a fresh DATA_HOME from the defaults the program ships with.

    Only what is missing, and never a credential: the shipped package has no
    secrets in it by design, and a file the user already has is theirs.
    """
    import shutil

    if SEED_CONFIG_DIR == CONFIG_DIR or not SEED_CONFIG_DIR.is_dir():
        return []
    made: list[str] = []
    for item in SEED_CONFIG_DIR.rglob("*"):
        if not item.is_file():
            continue
        target = CONFIG_DIR / item.relative_to(SEED_CONFIG_DIR)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(item, target)
            made.append(str(target.relative_to(CONFIG_DIR)))
        except OSError as e:             # pragma: no cover
            if log:
                log.warning("could not seed %s: %s", item.name, e)
    return made
