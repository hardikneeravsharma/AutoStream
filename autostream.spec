# PyInstaller spec for AutoStream.
#   pyinstaller autostream.spec --noconfirm
#
# --onedir (not --onefile): one-file bundles unpack to %TEMP% on every launch,
# which is slow and trips antivirus heuristics far more often.
#
# config/, secrets/, logs/ and state.json deliberately stay OUTSIDE the bundle,
# next to the exe, because they must be writable and user-editable.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ---------------------------------------------------------------- hidden imports
hidden = [
    "win32timezone",              # pywin32 imports this lazily at runtime
    "pystray._win32",
    "PIL._tkinter_finder",
    "tkinter",
    "tkinter.font",
    "google.auth.transport.requests",
    "googleapiclient.discovery",
]
# Reading a kill feed needs pytesseract, and killfeed.py imports it lazily
# inside the function that uses it, so PyInstaller cannot see it. Named here or
# the packaged build raises ImportError the first time someone scans a CS2
# recording -- the same trap numpy fell into for the whole Clips page.
#
# Optional, and the build must not require it: without it every other detector
# still works and killfeed mode says what to install.
try:
    import pytesseract  # noqa: F401
    hidden += ["pytesseract"]
except ImportError:
    print("NOTE: pytesseract is not installed, so this build cannot read kill "
          "feeds (Counter-Strike 2). Everything else is unaffected.")

# Reading a CS2 demo goes through demoparser2, whose native extension returns
# its rows as pandas DataFrames by way of polars and pyarrow. NOTHING imports
# those from Python -- the .pyd reaches for them itself -- so PyInstaller's
# analysis cannot see them and the packaged app shipped without all three.
#
# It failed in the worst possible way. pyo3 raises PanicException, which is a
# BaseException and NOT an Exception, so the demo search thread died without
# being caught, the search "returned nothing at all" in zero seconds, and every
# CS2 run in a packaged build fell back to reading rounds off the screen. That
# is the fallback path, so nothing looked broken -- the round boundaries and
# the clutch tags were just quietly wrong. Same trap as numpy and pytesseract.
try:
    import demoparser2  # noqa: F401
    hidden += ["demoparser2", "pandas", "pyarrow"]
    hidden += collect_submodules("polars")
except ImportError:
    print("NOTE: demoparser2 is not installed, so this build cannot read CS2 "
          "demos. Rounds and clutches would come off the screen instead.")

hidden += collect_submodules("obsws_python")
# cmd_run imports submodules lazily inside the function body; be explicit so a
# missed import fails the BUILD rather than the running app.
hidden += collect_submodules("autostream")
# pywebview picks its platform backend at runtime, so nothing imports these
# statically for PyInstaller to find.
hidden += [
    "webview",
    "webview.platforms.edgechromium",
    "webview.platforms.mshtml",
    "webview.platforms.winforms",
    "clr_loader",
]

# ---------------------------------------------------------------- data files
datas = []
# google-api-python-client ships static discovery JSON; without these the
# YouTube client fails at build("youtube", "v3") with a discovery error.
datas += collect_data_files("googleapiclient",
                            includes=["discovery_cache/documents/*.json"])
datas += collect_data_files("certifi")
# kokoro-onnx reads its own config.json out of its package directory, and the
# voice model is loaded from it -- so without this the packaged build can load
# the 177 MB model and then fail to tell you which voices are in it. Same trap
# as numpy, pytesseract and demoparser2: a data file nothing imports.
# ...and espeakng_loader carries the phoneme data and the DLL that turns the
# words into sounds, in a directory nothing imports either. 18 MB, and without
# it a packaged build loads the model and then fails on every line it is asked
# to say -- which is how the spoken hooks came to work only in development.
try:
    datas += collect_data_files("kokoro_onnx", includes=["*.json"])
    datas += collect_data_files("espeakng_loader",
                                includes=["espeak-ng-data/**", "*.dll"])
except Exception:                           # noqa: BLE001 - optional feature
    print("NOTE: kokoro-onnx is not installed, so this build cannot speak. "
          "Everything else is unaffected.")
for _pkg in ("webview",):
    try:
        datas += collect_data_files(_pkg)
    except Exception:                       # noqa: BLE001 - optional dependency
        pass

# The kill-marker templates that ship with the Clips page. These live inside
# the package rather than in config/ precisely so they survive here -- the
# share-package step deletes config/ wholesale to strip credentials.
datas += [("autostream/clips/templates/*.npy", "autostream/clips/templates")]

# The app icon. Embedded in the exe below for Explorer and the taskbar, and
# also shipped as a file so shortcuts and the installer can point at it without
# having to dig it back out of the binary.
datas += [("autostream/ui/assets/autostream.ico", "autostream/ui/assets")]

a = Analysis(
    ["autostream_launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # numpy is deliberately NOT excluded. It was, and that quietly made the
    # Clips page impossible in the packaged build: a frozen app has no pip, so
    # "install numpy" is not advice anyone can act on. It costs about 35 MB.
    # ffmpeg is still not bundled - it is 80 MB, it is a general system tool,
    # and the Clips page explains how to install it if it is missing.
    excludes=[
        "matplotlib", "scipy",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "pytest", "setuptools",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoStream",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                    # UPX compression is a major AV false-positive trigger
    console=False,                # no console window; logs go to logs\autostream.log
    disable_windowed_traceback=False,
    # Generated from the same mark the UI draws, by scripts/make_icon.py.
    # Regenerate it rather than editing the .ico by hand.
    icon="autostream/ui/assets/autostream.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AutoStream",
)
