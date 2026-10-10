"""Close the running AutoStream for a rebuild only when it is idle, and say why when not.

    python scripts\\handoff.py quit [--wait-minutes N]    -> exit 0 once it has quit
    python scripts\\handoff.py busy                       -> prints what it is doing, exit 0 idle / 1 busy

WHY THIS EXISTS
    A release build spends ~17 minutes in its tests and ~2 rewriting
    dist\\AutoStream. Only the rewrite needs the app closed -- Windows will not
    let a running program's files be replaced -- but the app used to be closed
    before the build started, so the player was locked out of it for twenty
    minutes for every release. build.ps1 -HandOff now runs the tests with the
    app open and calls this just before PyInstaller.

NEVER BY FORCE, NEVER MID-WORK. Quitting ends a broadcast and destroys a clip
job or a reel render in progress. So this asks the app itself, through the
same /api/status and /api/studio/job the dashboard reads, and quits only when
it is idle, not recording, and no clip job or render is running. Otherwise it
waits, saying what it is waiting for, and gives up after --wait-minutes.

The token and port come from the LIVE install's config (%LOCALAPPDATA%), the
one the running build reads -- not the repo's.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

POLL = 15.0


def _conf() -> tuple[str, int]:
    import yaml
    for p in (Path(os.environ.get("LOCALAPPDATA", "")) / "AutoStream" / "config" / "config.yaml",
              Path(__file__).resolve().parent.parent / "dist" / "AutoStream" / "config" / "config.yaml"):
        if p.is_file():
            rules = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("rules") or {}
            return str(rules.get("web_token") or ""), int(rules.get("web_port") or 8787)
    return "", 8787


def _get(port: int, token: str, path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}?k={token}", timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def busy(port: int, token: str) -> list[str]:
    """What the app is doing that a quit would destroy. [] when it is idle."""
    st = _get(port, token, "/api/status")
    why = []
    if st.get("phase") not in ("IDLE", "BLOCKED", None):
        why.append(f"phase {st.get('phase')}")
    if st.get("recording"):
        why.append("recording")
    clips = st.get("clips") or {}
    if isinstance(clips, dict) and clips.get("state") in ("running", "queued"):
        why.append("a clip job")
    job = _get(port, token, "/api/studio/job")
    if job.get("state") in ("running", "queued"):
        why.append(f"rendering the reel {job.get('name') or ''} ({job.get('percent', 0)}%)".replace("  ", " "))
    return why


def quit_when_idle(wait_minutes: float) -> int:
    token, port = _conf()
    give_up = time.time() + wait_minutes * 60
    said = None
    while True:
        try:
            why = busy(port, token)
        except OSError:
            print("  [ok] AutoStream is not answering; nothing to close")
            return 0
        if not why:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/cmd?k={token}",
                                         data=json.dumps({"command": "quit"}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10).read()
            print("  [ok] AutoStream was idle; asked it to close for the rebuild")
            return 0
        if why != said:
            print(f"  [--] waiting for AutoStream to finish: {', '.join(why)}")
            said = why
        if time.time() > give_up:
            print(f"  [!!] still busy after {wait_minutes:g} min ({', '.join(why)}); not closing it")
            return 1
        time.sleep(POLL)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "busy"
    wait = 60.0
    if "--wait-minutes" in sys.argv:
        wait = float(sys.argv[sys.argv.index("--wait-minutes") + 1])
    if cmd == "quit":
        sys.exit(quit_when_idle(wait))
    tok, prt = _conf()
    try:
        w = busy(prt, tok)
    except OSError:
        print("not running")
        sys.exit(0)
    print(", ".join(w) if w else "idle")
    sys.exit(1 if w else 0)
