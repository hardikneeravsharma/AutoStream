"""Entry point for the frozen macOS app, AutoStream.app.

The macOS twin of autostream_launcher.py, which is the Windows one and is left
alone (issue #193). Three things differ inside a .app:

  * The program's files are not beside the executable. Contents/MacOS holds
    only the binary; PyInstaller puts the bundled data in Contents/Resources
    and links it into Contents/Frameworks, which is sys._MEIPASS. That is
    the PROGRAM folder, so it is what AUTOSTREAM_APP_DIR names -- it is where
    the seed config is read from. The user's files go to
    ~/Library/Application Support/AutoStream regardless (macos/paths.py).

  * The bundle is read-only once signed, so a crash cannot be written into it.
    It goes to ~/Library/Logs/AutoStream, where Console.app looks.

  * Finder can pass a -psn_0_12345 process serial number on older macOS. That
    is not a command, and must not stop a double-click meaning "run".
"""
from __future__ import annotations

import os
import sys


def _app_home() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    # From a checkout: the repo, two levels above packaging/macos/.
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


os.environ.setdefault("AUTOSTREAM_APP_DIR", _app_home())
if getattr(sys, "frozen", False):
    # The bundled OpenSSL looks for CA certificates where the build machine's
    # python.org Python keeps them, a folder a user's Mac does not have, so
    # every HTTPS call -- the update check first -- failed CERTIFICATE_VERIFY_
    # FAILED. The spec ships certifi's bundle for exactly this.
    os.environ.setdefault("SSL_CERT_FILE",
                          os.path.join(_app_home(), "certifi", "cacert.pem"))
else:
    sys.path.insert(0, _app_home())

from autostream.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.argv = [a for a in sys.argv if not a.startswith("-psn_")]
    # Opening the app passes no arguments -- run it.
    if len(sys.argv) == 1:
        sys.argv.append("run")
    try:
        sys.exit(main())
    except Exception:
        # No console in a windowed app: put the traceback where Console.app
        # and a bug report can find it.
        import traceback

        logs = os.path.expanduser("~/Library/Logs/AutoStream")
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, "crash.log"), "a", encoding="utf-8") as fh:
            traceback.print_exc(file=fh)
        raise
