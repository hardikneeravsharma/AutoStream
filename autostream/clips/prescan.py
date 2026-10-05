r"""Reading a finished session's kills in the background, before anyone asks.

WHY THIS FILE EXISTS
    `record.auto_scan` has been a setting since before this file, is on by
    default, and promises "when a session ends, scan its recording for kill
    markers in the background so the Clips page already has them ready when
    you open it".

    It did nothing. The engine set `pending_scan` when a session ended and
    NOTHING ANYWHERE READ IT -- the whole feature was one assignment and a
    help text. A setting that is on by default and does nothing is worse than
    one that is missing: the Clips page looked slow for a reason that was
    never true, and anyone who turned it off to save CPU saved nothing.

WHAT IT DOES AND DOES NOT DO
    Reads, and stops. It does NOT cut clips. Cutting takes the GPU for
    minutes, writes files nobody asked for and makes choices -- style, length,
    minimum kills -- that belong to the person, not to the end of a stream.
    What it leaves behind is the kill list, in the sidecar the Clips page
    already reads, so opening that page after a stream shows "23 kills found"
    instead of an unread recording and an eight-minute wait.

    The sidecar sits in a folder with no clips in it, which is exactly how
    `webui._scan_runs` already distinguishes "this recording has been read"
    from "this recording has been cut": `kills` is taken from every sidecar,
    and `runs` only from the ones with files beside them.

WHY IT NEVER RUNS WHILE A REAL JOB DOES
    They compete for the same decoder and the same disk, and a background
    read that makes a clip run the user is watching take twice as long is a
    feature doing harm. The runner is asked first, and this waits.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from .. import atomic, paths
from . import profiles

log = logging.getLogger("autostream.clips.prescan")

# How long to wait for a clip run the user started before giving up for this
# session. Long enough to outlast an ordinary run, short enough that the
# thread does not live forever on a machine where something is wedged.
WAIT_FOR_RUNNER = 1800.0
POLL = 5.0

_lock = threading.Lock()
_running: str = ""


def folder_for(root: Path, started: float | None, game: str | None) -> Path:
    """Where the kill list goes. Beside the runs, and named as one."""
    from .jobs import _stamp_folder

    name = _stamp_folder(started, game, "read")
    return Path(root) / name


def already_read(root: Path, recording: str) -> bool:
    """Has any run or read already covered this recording, whole?

    CHEAPER THAN THE SCAN BY ORDERS OF MAGNITUDE, and the common case: a
    session that ends, is read, and ends again after a restart would otherwise
    be read twice.
    """
    import json

    want = str(Path(recording).resolve()).lower()
    try:
        sidecars = list(Path(root).glob("*/session.json"))
    except OSError:
        return False
    for f in sidecars:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        src = data.get("source") or ""
        try:
            if str(Path(src).resolve()).lower() != want:
                continue
        except OSError:
            continue
        # A WINDOWED SCAN DOES NOT COUNT. Its kill list is complete only
        # inside its window, and treating it as "already read" would leave
        # everything outside that window permanently unread.
        window = data.get("scanned") or [0.0, 0.0]
        if list(window)[:2] == [0.0, 0.0] and data.get("kills") is not None:
            return True
    return False


def run(entry: dict, config, runner=None) -> dict | None:
    """Read one finished session. -> the sidecar written, or None.

    Never raises. This runs on a thread nobody is watching, at the end of a
    stream, and an exception here must not be able to take anything with it.
    """
    from . import detect

    recording = str(entry.get("recording_path") or "")
    if not recording or not Path(recording).is_file():
        return None

    prof = profiles.for_game(entry.get("game_key"), entry.get("game"))
    if prof is None or not prof.exists():
        log.info("not reading %s: no usable profile for %s",
                 Path(recording).name, entry.get("game") or "that game")
        return None

    root = _clips_root(config)
    if already_read(root, recording):
        log.info("%s has been read before; not reading it again",
                 Path(recording).name)
        return None

    if runner is not None and not _wait_for(runner):
        log.info("a clip job is still running; not reading %s this time",
                 Path(recording).name)
        return None

    started = time.monotonic()
    try:
        kills = detect.scan(Path(recording), prof)
    except Exception as e:                               # noqa: BLE001
        log.warning("could not read %s: %s", Path(recording).name, e)
        return None

    out = folder_for(root, entry.get("started"), entry.get("game"))
    data = {
        "source": str(Path(recording)),
        "game": entry.get("game"),
        "game_key": entry.get("game_key"),
        # [0, 0] is "the whole file", the same spelling a full clip run uses.
        "scanned": [0.0, 0.0],
        "kills": [{"time": k.time, "end": k.end, "score": k.score,
                   "count": k.count} for k in kills],
        # SO NOTHING MISTAKES THIS FOR A RUN. There are no clips in this
        # folder and there never will be; anything counting what was produced
        # should count the files, but saying it outright costs one key.
        "read_only": True,
    }
    try:
        out.mkdir(parents=True, exist_ok=True)
        atomic.write_json(out / "session.json", data)
    except OSError as e:
        log.warning("could not write the kill list: %s", e)
        return None
    log.info("read %s in %.0fs: %d kill(s) ready for the Clips page",
             Path(recording).name, time.monotonic() - started, len(kills))
    return data


def start(entry: dict, config, runner=None) -> bool:
    """Read `entry` on a thread. -> whether one was started.

    ONE AT A TIME, and never twice for the same recording: a session that
    ends, restarts and ends again inside half an hour would otherwise have
    two reads of the same file competing for the same decoder.
    """
    recording = str(entry.get("recording_path") or "")
    if not recording:
        return False
    global _running
    with _lock:
        if _running:
            log.info("already reading %s; not starting another",
                     Path(_running).name)
            return False
        _running = recording

    def work() -> None:
        global _running
        try:
            run(entry, config, runner)
        finally:
            with _lock:
                _running = ""

    threading.Thread(target=work, name="autostream-prescan",
                     daemon=True).start()
    return True


def busy() -> bool:
    with _lock:
        return bool(_running)


def _wait_for(runner) -> bool:
    """Hold until the clip runner is free. -> False if it never was."""
    end = time.monotonic() + WAIT_FOR_RUNNER
    while time.monotonic() < end:
        try:
            if not runner.busy():
                return True
        except Exception:                                # noqa: BLE001
            return True
        time.sleep(POLL)
    return False


def _clips_root(config) -> Path:
    want = ""
    try:
        want = str(getattr(config.clips, "output_dir", "") or "")
    except Exception:                                    # noqa: BLE001
        want = ""
    return Path(want) if want else paths.CLIPS_DIR
