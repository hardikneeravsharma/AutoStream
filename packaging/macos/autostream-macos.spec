# PyInstaller spec for AutoStream.app -- the macOS clipper and Studio.
#   scripts/macos/build.sh            (which runs this; do not run it from elsewhere)
#
# The Windows spec is autostream.spec at the repo root and is left alone (issue
# #193). This one differs in what it leaves OUT as much as in what it adds:
#
#   * No streaming half. OBS websocket, the Google client, the tray and the
#     global hotkey are excluded outright -- nothing on a Mac starts them, and a
#     dev venv has them installed for the test suite, so without the excludes
#     they would ride along anyway.
#   * pywebview's Cocoa backend (WKWebView) instead of Edge WebView2.
#   * A BUNDLE step, so the result is AutoStream.app with an Info.plist and an
#     .icns icon, not a folder with an exe in it.
#
# --onedir inside the bundle, as on Windows: a one-file app unpacks itself to a
# temporary folder on every launch, which is slow and needs no defending.
#
# SPECPATH is this file's folder; every source path below is from the repo root.

import os
import re

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))  # noqa: F821 - PyInstaller global


def here(*parts):
    return os.path.join(ROOT, *parts)


with open(here("autostream", "__init__.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)

ICON = os.environ.get("AUTOSTREAM_ICNS") or here("build", "macos", "AutoStream.icns")

# ---------------------------------------------------------------- hidden imports
# Modules imported lazily, inside the function that needs them, are invisible
# to PyInstaller -- the trap numpy once fell into for the whole Clips page.
hidden = [
    "webview",
    "webview.platforms.cocoa",
    "PIL._tkinter_finder",
]
# Optional extras, exactly as autostream.spec treats them: bundled when the
# build machine has them, never required.
for _mod in ("pytesseract", "yt_dlp"):
    try:
        __import__(_mod)
        hidden.append(_mod)
    except ImportError:
        print(f"NOTE: {_mod} is not installed - the build will not include it.")
try:
    import demoparser2  # noqa: F401
    hidden += ["demoparser2", "pandas", "pyarrow"]
    hidden += collect_submodules("polars")
except ImportError:
    print("NOTE: demoparser2 is not installed - CS2 .dem files will not be read.")

# Every AutoStream module, including the streaming ones: they are imported
# lazily from routes the Mac page never shows, and an ImportError there is a
# sentence on a hidden page rather than a crash. Their third-party imports are
# excluded below, so this costs kilobytes.
hidden += collect_submodules("autostream")

# ---------------------------------------------------------------- data files
datas = [
    (here("autostream", "clips", "templates", "*.npy"), "autostream/clips/templates"),
    (here("autostream", "clips", "stock_examples", "*.mp4"), "autostream/clips/stock_examples"),
    (here("autostream", "clips", "stock_samples", "*.mp4"), "autostream/clips/stock_samples"),
    (here("autostream", "clips", "fonts", "*.ttf"), "autostream/clips/fonts"),
    (here("autostream", "clips", "fonts", "OFL.txt"), "autostream/clips/fonts"),
    # The seed a fresh ~/Library/Application Support/AutoStream is filled
    # from (paths.seed_config). Tracked, and holds no one's name.
    (here("config", "games.yaml"), "config"),
]
datas += collect_data_files("certifi")
for _pkg in ("webview",):
    try:
        datas += collect_data_files(_pkg)
    except Exception:  # noqa: BLE001
        pass
# The spoken-hook voice. The model itself is downloaded on first use into
# ~/Movies/AutoStream/models; only the package data ships.
try:
    datas += collect_data_files("kokoro_onnx", includes=["*.json"])
    datas += collect_data_files("espeakng_loader",
                                includes=["espeak-ng-data/**", "*.dylib"])
except Exception:  # noqa: BLE001 - optional feature
    print("NOTE: kokoro-onnx is not installed - spoken hooks will be offered as a download.")

a = Analysis(
    [here("packaging", "macos", "launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "matplotlib", "scipy",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "pytest", "setuptools",
        # The streaming half -- see the header.
        "obsws_python", "googleapiclient", "google_auth_oauthlib",
        "google.auth", "google.oauth2", "pystray", "keyboard",
        "winotify", "win32api", "win32gui", "win32process", "win32com",
        "clr_loader", "pythonnet",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoStream",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=os.environ.get("AUTOSTREAM_ARCH") or None,
    codesign_identity=os.environ.get("AUTOSTREAM_CODESIGN") or None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AutoStream",
)

app = BUNDLE(  # noqa: F821
    coll,
    name="AutoStream.app",
    icon=ICON if os.path.isfile(ICON) else None,
    bundle_identifier="com.yuvaneta.autostream",
    version=VERSION,
    info_plist={
        "CFBundleName": "AutoStream",
        "CFBundleDisplayName": "AutoStream",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.video",
        # Shown by macOS the first time a remembered recording is read from
        # one of these folders without going through the picker.
        "NSDesktopFolderUsageDescription":
            "AutoStream reads the recordings you choose to clip.",
        "NSDocumentsFolderUsageDescription":
            "AutoStream reads the recordings you choose to clip.",
        "NSDownloadsFolderUsageDescription":
            "AutoStream reads the recordings you choose to clip.",
        "NSRemovableVolumesUsageDescription":
            "AutoStream reads recordings from the drive you choose.",
        "NSNetworkVolumesUsageDescription":
            "AutoStream reads recordings from the network drive you choose.",
    },
)
