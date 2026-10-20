#!/usr/bin/env bash
# Build AutoStream.app -- the macOS clipper and Studio.
#
#   scripts/macos/build.sh             test, then build dist/macos/AutoStream.app
#   scripts/macos/build.sh --dist      and zip it for sharing, with a .sha256
#   scripts/macos/build.sh --no-tests  skip the offline suite (iterating only)
#
# The macOS twin of scripts/build.ps1, which is left alone (issue #193).
# Output goes to dist/macos/ and build/macos/, never to dist/AutoStream, so a
# Mac build and a Windows build in the same checkout cannot overwrite each other.
#
# In order:
#   1. the venv and PyInstaller
#   2. the version, from autostream/__init__.py
#   3. an import probe, then the offline test suite (the gate)
#   4. refuse if this tree's AutoStream.app is running
#   5. the .icns, from the same mark as the Windows .ico
#   6. PyInstaller with packaging/macos/autostream-macos.spec
#   7. a credential scan of the bundle
#   8. --dist: a zip made with ditto (keeps the symlinks and the executable
#      bit a .app depends on -- scripts/make_zip.py keeps neither) and its hash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

DIST=0
TESTS=1
for arg in "$@"; do
  case "$arg" in
    --dist) DIST=1 ;;
    --no-tests) TESTS=0 ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

ok()   { printf '  [ok] %s\n' "$*"; }
warn() { printf '  [!!] %s\n' "$*"; }
bad()  { printf '  [XX] %s\n' "$*" >&2; }

if [[ "$(uname -s)" != "Darwin" ]]; then
  bad "this builds the macOS app; on Windows use scripts/build.ps1"
  exit 1
fi

OUT="$ROOT/dist/macos"
WORK="$ROOT/build/macos"
APP="$OUT/AutoStream.app"
SPEC="$ROOT/packaging/macos/autostream-macos.spec"

# ---- 1. venv and PyInstaller ------------------------------------------
VPY="$ROOT/.venv/bin/python"
if [[ ! -x "$VPY" ]]; then
  bad "no .venv - run scripts/macos/install.sh first"
  exit 1
fi
if ! "$VPY" -c "import PyInstaller" 2>/dev/null; then
  echo "  [..] installing PyInstaller"
  "$VPY" -m pip install --quiet pyinstaller
fi

# ---- 2. version -------------------------------------------------------
VERSION="$("$VPY" -c 'import re,sys; print(re.search(r"__version__\s*=\s*\"([^\"]+)\"", open("autostream/__init__.py", encoding="utf-8").read()).group(1))')"
ARCH="$(uname -m)"
ok "version $VERSION ($ARCH)"

# ---- 3. import probe and the gate ------------------------------------
if ! "$VPY" -c "import autostream.__main__, autostream.macos.launch, autostream.webui"; then
  bad "the package does not import - fix that before building"
  exit 1
fi
ok "package imports cleanly"
if [[ "$TESTS" == 1 ]]; then
  if ! "$VPY" -c "import pytest" 2>/dev/null; then
    bad "pytest is not installed - run scripts/macos/install.sh --dev, or pass --no-tests"
    exit 1
  fi
  echo "  [..] running the offline suite"
  if ! "$VPY" -m pytest -q --no-header -p no:randomly; then
    bad "tests failed - not building"
    exit 1
  fi
  ok "offline suite passes"
else
  warn "building without the test gate (--no-tests)"
fi

# ---- 4. not while it is running -------------------------------------
# PyInstaller clears the old bundle first, and a running app keeps its log and
# its webview process open inside it. Asking, never killing: quitting can end a
# clip job or a reel render, and that is the user's call.
if pgrep -f "$APP/Contents/MacOS/AutoStream" >/dev/null 2>&1; then
  bad "this tree's AutoStream.app is running. Quit it (Cmd-Q) and build again."
  exit 1
fi

# ---- 5. icon ----------------------------------------------------------
"$VPY" packaging/macos/make_icns.py "$WORK/AutoStream.icns"

# ---- 6. freeze --------------------------------------------------------
AUTOSTREAM_ICNS="$WORK/AutoStream.icns" "$VPY" -m PyInstaller "$SPEC" \
  --noconfirm --log-level WARN --distpath "$OUT" --workpath "$WORK"
if [[ ! -x "$APP/Contents/MacOS/AutoStream" ]]; then
  bad "PyInstaller finished but $APP/Contents/MacOS/AutoStream is missing"
  exit 1
fi
ok "built $APP"

# ---- 7. nothing personal in the bundle --------------------------------
# The repo is public and so is anything built from it. The spec bundles no
# config but the tracked games.yaml; this proves it, file by file.
LEAKS="$(find "$APP" \( -iname 'config.yaml' -o -iname 'apps.yaml' -o -iname 'clip_profiles.yaml' \
  -o -iname 'streamelements.json' -o -iname 'state.json' -o -iname '*token*.json' \
  -o -iname 'client_secret*' \) -print)"
if [[ -n "$LEAKS" ]]; then
  bad "the bundle contains files that must never ship:"
  echo "$LEAKS" >&2
  exit 1
fi
ok "no credentials or personal config in the bundle"

# ---- 8. --dist: zip and hash ----------------------------------------
if [[ "$DIST" == 1 ]]; then
  ZIP="$OUT/AutoStream-$VERSION-macos-$ARCH.zip"
  rm -f "$ZIP" "$ZIP.sha256"
  ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
  (cd "$OUT" && shasum -a 256 "$(basename "$ZIP")" > "$(basename "$ZIP").sha256")
  ok "wrote $ZIP ($(du -h "$ZIP" | cut -f1))"
  ok "wrote $ZIP.sha256"
  warn "the app is ad-hoc signed, not notarised: the first open is right-click > Open"
fi

echo
ok "open it with:  open \"$APP\""
