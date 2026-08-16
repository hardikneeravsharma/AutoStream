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
for _pkg in ("webview",):
    try:
        datas += collect_data_files(_pkg)
    except Exception:                       # noqa: BLE001 - optional dependency
        pass

a = Analysis(
    ["autostream_launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "matplotlib", "numpy", "pandas", "scipy",
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
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AutoStream",
)
