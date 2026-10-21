#!/usr/bin/env bash
# Set up AutoStream for macOS from a checkout: the clipper and the Studio.
#
#   scripts/macos/install.sh          the app:   .venv + requirements-macos.txt
#   scripts/macos/install.sh --dev    and tests: + requirements-dev.txt
#
# The macOS twin of scripts/install.ps1, which is left alone (issue #193). No
# OBS, no Google client, no stream key -- the Mac build does not stream.
#
# What it does, in order:
#   1. finds Python 3.12+ (Homebrew's, or whatever python3 is)
#   2. makes .venv and installs the requirements into it
#   3. checks ffmpeg can draw text, and says how to fix it if not
#   4. prints how to start it
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

DEV=0
for arg in "$@"; do
  case "$arg" in
    --dev) DEV=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '  [..] %s\n' "$*"; }
ok()   { printf '  [ok] %s\n' "$*"; }
warn() { printf '  [!!] %s\n' "$*"; }

if [[ "$(uname -s)" != "Darwin" ]]; then
  warn "this is the macOS installer; on Windows use scripts/install.ps1"
  exit 1
fi

# ---------------------------------------------------------------- 1. Python
# $PYTHON wins when set (CI points it at the interpreter it installed).
PY="${PYTHON:+$(command -v "$PYTHON")}"
if [[ -z "$PY" ]]; then
  for cand in python3.14 python3.13 python3.12 python3; do
    for dir in "" /opt/homebrew/bin/ /usr/local/bin/; do
      exe="${dir}${cand}"
      if command -v "$exe" >/dev/null 2>&1 && \
         "$exe" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
        PY="$(command -v "$exe")"; break 2
      fi
    done
  done
fi
if [[ -z "$PY" ]]; then
  warn "no Python 3.12 or newer found. Install one with:  brew install python"
  exit 1
fi
ok "Python: $PY ($("$PY" -c 'import platform; print(platform.python_version())'))"

# ---------------------------------------------------------------- 2. venv
if [[ ! -x .venv/bin/python ]]; then
  say "creating .venv"
  "$PY" -m venv .venv
fi
VPY="$ROOT/.venv/bin/python"
"$VPY" -m pip install --quiet --upgrade pip
if [[ "$DEV" == 1 ]]; then
  # The whole suite imports the streaming modules too, so tests want the
  # full Windows list on top of the Mac one. Nothing Windows-only installs:
  # those lines are already marked sys_platform == "win32".
  say "installing requirements-macos.txt and requirements-dev.txt"
  "$VPY" -m pip install --quiet -r requirements-macos.txt -r requirements-dev.txt
else
  say "installing requirements-macos.txt"
  "$VPY" -m pip install --quiet -r requirements-macos.txt
fi
"$VPY" -c "import yaml, requests, webview, numpy, PIL" && ok "Python packages installed"
mkdir -p config secrets logs

# ---------------------------------------------------------------- 3. ffmpeg
# The plain Homebrew ffmpeg has no drawtext or ass filter: clips cut fine and
# come out without captions, lyrics or the handle. Say so now, not at render.
"$VPY" - <<'PY' || true
from autostream.macos import tools
tools.extend_path()
ff = tools.find("ffmpeg")
if not ff:
    print("  [!!] ffmpeg not found. Install it with:  " + tools.INSTALL_HINT)
else:
    w = tools.text_warning(ff)
    print("  [!!] " + w if w else "  [ok] ffmpeg: " + ff)
if not tools.find("tesseract"):
    print("  [..] Tesseract not found (only Counter-Strike 2's kill feed needs it): "
          + tools.TESSERACT_HINT)
PY

# ---------------------------------------------------------------- 4. next
echo
ok "done. Start it with:"
echo "      .venv/bin/python -m autostream run"
echo "  or build the .app with:  scripts/macos/build.sh"
