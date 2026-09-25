"""AutoStream CLI.

  python -m autostream setup      one-time interactive setup
  python -m autostream detect     detection only, no streaming (stage 1)
  python -m autostream obs-test   30s private test stream (stage 3)
  python -m autostream run        the daemon
  python -m autostream status     print current state
  python -m autostream stop       force-stop whatever is live
  python -m autostream auth       re-run OAuth only
  python -m autostream refresh    force game index refresh
"""
from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import re
import signal
import sys
import time
from pathlib import Path

from . import cfg, notify, paths, single


class RedactSecrets(logging.Filter):
    """Blank any password written into a log line, whoever wrote it.

    obsws-python logs its connection arguments at INFO -- `password='...'`
    in full -- and the root logger is at INFO, so the OBS websocket password
    was in plain text in autostream.log: on the Logs page, behind "Open log",
    and in any log pasted into an issue on a public repo. Its logger is turned
    down below as well; this catches the next library that does the same.
    """

    PATTERN = re.compile(r"(password\s*[=:]\s*)(['\"]?)[^'\"\s,)}]*\2",
                         re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string is not ours to fix
            return True
        if "password" in msg.lower():
            record.msg = self.PATTERN.sub(r"\1\2(removed)\2", msg)
            record.args = None
        return True


def setup_logging(level: str = "INFO", console: bool = True) -> None:
    # BEFORE ANYTHING ELSE, and before the log file is opened, because the old
    # log is one of the things that comes across. Every command routes through
    # here, so this is the one place a migration cannot be skipped.
    moved = paths.migrate_data_home()
    paths.ensure_dirs()
    seeded = paths.seed_config()
    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    root.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)-18s %(message)s",
                            "%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.TimedRotatingFileHandler(
        paths.LOG_FILE, when="midnight", backupCount=7, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(RedactSecrets())
    root.addHandler(fh)

    if console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        ch.addFilter(RedactSecrets())
        root.addHandler(ch)

    logging.getLogger("googleapiclient").setLevel(logging.ERROR)
    logging.getLogger("google_auth_oauthlib").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    # Its INFO line is the connection arguments, password included.
    logging.getLogger("obsws_python").setLevel(logging.WARNING)

    # Said only once, on the run that actually moves anything -- and said at
    # all because "where did my settings go" is the first question an upgrade
    # of this kind provokes.
    # This module has no module-level logger -- setup_logging IS what makes
    # logging work -- so the logger is fetched here, after the handlers exist.
    started = logging.getLogger("autostream")
    if moved:
        started.info("your settings now live in %s (%d file(s) brought across "
                     "from the program folder, which an update no longer "
                     "touches)", paths.DATA_HOME, len(moved))
    if seeded:
        started.info("wrote %d default config file(s) into %s",
                     len(seeded), paths.CONFIG_DIR)


# ---------------------------------------------------------------- commands

def cmd_setup(_args) -> int:
    from .setup_wizard import run

    setup_logging("INFO", console=False)
    return run()


def cmd_auth(_args) -> int:
    from .state import State
    from .youtube import YouTube

    setup_logging("INFO")
    config = cfg.load()
    yt = YouTube(config, State.load())
    yt.authorise(interactive=True)
    print("authorised as:", yt.channel_title())
    return 0


def cmd_refresh(_args) -> int:
    from .gameindex import GameIndex

    setup_logging("INFO")
    idx = GameIndex(cfg.load())
    changed = idx.refresh(force=True)
    idx.reload()
    print(f"index refreshed={changed}: {len(idx.public)} executables, "
          f"{len(idx.steam_apps)} steam apps")
    return 0


def cmd_detect(args) -> int:
    """Stage 1: detection only. No API calls, no OBS. Run this for an evening."""
    from .gameindex import GameIndex
    from .watcher import Watcher

    config = cfg.load()
    setup_logging("DEBUG" if args.verbose else "INFO")
    log = logging.getLogger("autostream.detect")

    print(f"\nWatching every {config.timing.poll_interval}s. Ctrl-C to stop.")
    print(f"arm_delay={config.timing.arm_delay}s  "
          f"(a game must survive this long to count)")

    index = GameIndex(config)
    index.refresh(force=False)          # may take a few seconds on first run
    index.reload()
    warn = index.coverage_warning()
    if warn:
        print(f"\n  !! {warn}\n")
    else:
        print(f"knows {len(index.public) + len(index.overrides)} executables\n")
    watcher = Watcher(config, index)

    last = None
    armed_announced = False
    try:
        while True:
            hit = watcher.active_game()
            armed = watcher.armed_game()

            key = hit.key if hit else None
            if key != last:
                if hit:
                    print(f"  detected  {hit.name}   [{hit.key}]  via {hit.source}")
                else:
                    print("  detected  (nothing)")
                last = key
                armed_announced = False

            if armed and not armed_announced:
                print(f"  ARMED     {armed.name}  -> would start streaming now")
                armed_announced = True

            time.sleep(config.timing.poll_interval)
    except KeyboardInterrupt:
        pass

    unknown = watcher.unknown_candidates(min_seconds=60)
    if unknown:
        print("\nUnindexed executables seen for 60s+ (candidates for games.yaml):")
        for e in unknown[:40]:
            print(f"  {e}")
        print("\nAdd real games under `games:` in config/games.yaml,")
        print("and everything else under `blocklist:`.")
    log.info("detect session ended")
    return 0


def cmd_obs_test(_args) -> int:
    """Stage 3: prove OBS -> YouTube works, on a private broadcast."""
    from .obs import Obs
    from .state import State
    from .youtube import YouTube

    setup_logging("INFO")
    config = cfg.load()
    if not config.youtube.stream_id:
        print("No stream_id configured. Run: python -m autostream setup")
        return 1

    yt = YouTube(config, State.load())
    obs = Obs(config)
    bid = None
    try:
        bid = yt.create_broadcast("AutoStream obs-test — ignore", "test", privacy="private")
        yt.bind(bid, config.youtube.stream_id)
        obs.start(scene=config.obs.default_scene or None)
        deadline = time.time() + config.timing.ingestion_timeout
        while time.time() < deadline:
            s, h = yt.stream_status(config.youtube.stream_id)
            print(f"  status={s} health={h}")
            if s == "active":
                print("  ingestion active — holding 30s")
                time.sleep(30)
                print("  OK")
                return 0
            time.sleep(3)
        print("  FAILED: YouTube never saw the stream")
        return 1
    finally:
        obs.stop()
        if bid:
            yt.delete_broadcast(bid)


def cmd_status(_args) -> int:
    from .state import State

    s = State.load()
    print(json.dumps({
        "phase": s.phase,
        "broadcast": s.broadcast_id,
        "url": f"https://www.youtube.com/watch?v={s.broadcast_id}" if s.broadcast_id else None,
        "game": s.current_game,
        "session_games": s.session_games,
        "session_number": s.session_number,
        "paused": s.paused,
        "quota_spent_today": s.quota_spent,
        "quota_left": s.quota_left(),
    }, indent=2))
    return 0


def cmd_stop(_args) -> int:
    from .engine import Engine

    setup_logging("INFO")
    eng = Engine(cfg.load())
    eng.shutdown("cli stop")
    print("stopped")
    return 0


def cmd_scan(_args) -> int:
    """Rebuild config/apps.yaml from what is installed."""
    from . import catalog

    setup_logging("INFO")
    existing = {a.key: a for a in catalog.load()}
    found = catalog.discover_all()
    for a in found:
        prev = existing.get(a.key)
        if prev:
            a.stream, a.scene, a.favourite = prev.stream, prev.scene, prev.favourite
    catalog.save(found)
    print(f"\nfound {len(found)} apps -> config/apps.yaml\n")
    for a in found:
        print(f"  {'[stream]' if a.stream else '[  open]'}  {a.name:38.38s} "
              f"{a.source:9s} {a.exe}")
    print("\nEdit config/apps.yaml to change names or remove entries.")
    return 0


def _engine_loop(engine, tray, interval, log) -> None:
    """The poll loop, on a worker thread. The main thread belongs to the app
    window -- see win.run() -- which is what pywebview requires."""
    last_phase = None
    while not engine._stop_requested:  # noqa: SLF001
        try:
            engine.tick()
            if engine.state.phase != last_phase:
                last_phase = engine.state.phase
                tray.refresh()
        except Exception as e:  # noqa: BLE001
            log.exception("tick failed: %s", e)
        time.sleep(interval)


def cmd_voice(args) -> int:
    """Check, fetch or try out the spoken-hook voice.

    A separate command because the model is a 177 MB download and nothing
    should ever start one on its own. Clip jobs simply stay silent until this
    has been run.
    """
    from .clips import voice

    if args.download:
        def show(name, done, total):
            pct = 100 * done / total if total else 0
            print(f"\r  {name}  {done / 1e6:6.0f} / {total / 1e6:.0f} MB "
                  f"({pct:3.0f}%)", end="", flush=True)
        try:
            for path in voice.download(progress=show):
                print(f"\r  {path.name}  done" + " " * 24)
        except Exception as e:                     # noqa: BLE001
            print(f"download failed: {e}")
            return 1

    if not voice.available():
        print(voice.why_not())
        print("\nRun  python -m autostream voice --download  to fetch it.")
        return 1

    print(f"Kokoro is ready in {voice.MODEL_DIR}")
    print(f"the clips currently use {voice.VOICE}")
    if args.list_voices:
        for group, names in voice.catalogue().items():
            print(f"\n  {group}")
            print("    " + ", ".join(names))
        print(f"\n  set one with  clips.voice_name  in config.yaml")
    if args.sample:
        out = Path(args.out or (voice.MODEL_DIR / "samples"))
        out.mkdir(parents=True, exist_ok=True)
        made = voice.samples(out, args.say or "")
        print(f"{len(made)} samples in {out}")
    elif args.say:
        out = Path(args.out or "hook.wav")
        got = voice.say(args.say, out, voice=args.voice or voice.VOICE)
        print(f"said {args.say!r} -> {got.path} ({got.duration:.1f}s)")
    return 0


def cmd_run(args) -> int:
    """Main entry: web UI + native window + tray + engine.

    Thread layout, because these libraries all want to own a thread:
      main    - pywebview native window (it insists on the main thread)
      worker  - the engine poll loop
      worker  - the HTTP server, the tray icon
    """
    import secrets as _secrets
    import threading

    from .engine import Engine
    from .tray import Tray
    from .webui import Server, is_configured
    from .window import MainWindow, available as window_available

    config = cfg.load()
    setup_logging("DEBUG" if args.verbose else config.logging.level,
                  console=not args.quiet)
    log = logging.getLogger("autostream")

    # --- token for the local UI ---
    token = config.rules.web_token
    if not token:
        token = _secrets.token_urlsafe(12)
        cfg.save_field("rules", "web_token", token)
    port = int(config.rules.web_port or 8787)

    # One at a time. Two engines each create their own broadcast and each tell
    # the same OBS to start, so one broadcast never receives a frame, waits out
    # the ingestion timeout, aborts, and eventually pauses itself -- while the
    # log reads as one confused process rather than two coherent ones. Easy to
    # reach: the Scheduled Task starts one at login and somebody double-clicks
    # the shortcut.
    if not single.acquire():
        log.error("AutoStream is already running. Use the tray icon, or the "
                  "dashboard at %s", f"http://127.0.0.1:{port}/")
        notify.toast("AutoStream is already running",
                     "Open it from the tray icon rather than starting a second copy.")
        return 1

    first_run = not is_configured()
    engine = None if first_run else Engine(config)

    server = Server(token, port, engine,
                    lan=bool(getattr(config.rules, "web_lan", True)))
    if server.start() is None:
        log.error("could not start the UI server on port %d", port)
        return 1

    if first_run:
        log.info("no configuration found - starting the setup wizard")

    win_ref = {}
    # What is running, filled in by start_engine() -- at once when already
    # configured, or the moment the setup wizard finishes.
    run = {"engine": engine, "loop": None, "interval": 3}

    def _sig(_signum, _frame):
        log.info("signal received - stopping")
        if run["engine"]:
            run["engine"].request_stop()
        w = win_ref.get("w")
        if w is not None:
            w.request_quit("shutting down")          # otherwise webview.start() never returns

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, _sig)
        except (ValueError, AttributeError):
            pass

    # --- native window (main thread), or browser fallback ---
    win = MainWindow(server.local_url())
    win_ref["w"] = win
    server.window = win
    if not window_available():
        log.info("pywebview unavailable - the UI is at %s", server.url())

    def start_engine(eng) -> None:
        """Tray, hotkey and the engine loop. Needs a configured install."""
        tray = Tray(eng)
        tray.window = win
        tray.start()

        c = eng.cfg
        hotkey = c.rules.kill_switch_hotkey
        if hotkey:
            try:
                import keyboard

                # "kill", not "toggle_pause": pause now holds a live stream on
                # the be-right-back card instead of ending it, and a kill
                # switch that does that is not a kill switch.
                keyboard.add_hotkey(hotkey, lambda: eng.submit("kill"))
                log.info("kill switch hotkey: %s", hotkey)
            except Exception as e:  # noqa: BLE001
                log.info("hotkey unavailable (%s) - use the tray icon", e)

        eng.startup()
        interval = max(1, int(c.timing.poll_interval))
        loop = threading.Thread(target=_engine_loop,
                                args=(eng, tray, interval, log),
                                name="autostream-engine", daemon=True)
        loop.start()
        run.update(engine=eng, loop=loop, interval=interval)

    def await_setup() -> None:
        """Start the engine in THIS process once the wizard has finished.

        It used to exit instead and leave the restart to the user -- except
        the exit only happened after ten seconds with no request at all, and
        the dashboard the wizard reloads into polls every two, so it never
        came. The user got a dashboard that looked fine with nothing behind
        it: no game watched, "Open + stream" answering ok and doing nothing,
        and no screen saying why.

        Not while a request is in flight: finish() saves youtube.stream_id,
        which is what makes the install count as configured, part-way through
        its work, and the engine must not start on a half-written setup.
        """
        while not win._quit:                              # noqa: SLF001
            try:
                if is_configured() and server.idle_for() > 0:
                    eng = Engine(cfg.load())
                    server.engine = eng
                    start_engine(eng)
                    log.info("setup complete - AutoStream is running")
                    return
            except Exception as e:  # noqa: BLE001
                log.exception("could not start after setup: %s", e)
                return
            time.sleep(0.5)

    if engine is not None:
        start_engine(engine)
    else:
        log.info("setup wizard running at %s", server.url())
        threading.Thread(target=await_setup, name="autostream-setup",
                         daemon=True).start()

    # blocks until the window is destroyed (or returns at once without pywebview)
    win.run()

    # No native window to block on (no pywebview, or no WebView2 runtime), so
    # THIS loop is what keeps the daemon -- and the server the browser was
    # just pointed at -- alive. Without it such a machine ran for the fraction
    # of a second run() took to return, and the UI it opened could not load.
    if win.fell_back or not window_available():
        log.info("the UI is in your browser at %s", server.url())
    try:
        while not win._quit:                              # noqa: SLF001
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass

    eng = run["engine"]
    if eng is not None:
        eng.request_stop()
        # Let the tick in progress finish rather than racing it from this
        # thread -- a tick can be mid-way through talking to OBS or YouTube.
        if run["loop"] is not None:
            run["loop"].join(timeout=run["interval"] + 60)
        # And then END the session, here, before the process exits. This used
        # to be force_stop(), which puts the ending card up and leaves the
        # rest to a tick loop that no longer runs: OBS kept streaming and
        # recording, and the broadcast stayed open on the card until the next
        # launch.
        eng.shutdown("shutdown")

    server.stop()
    single.release()
    log.info("AutoStream exited cleanly")
    return 0


# ---------------------------------------------------------------- entry

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="autostream", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true", help="no console output")

    # The same flags again, accepted AFTER the subcommand. "autostream run
    # --quiet" is the order everyone types, and argparse would otherwise exit 2
    # — which is invisible when a Scheduled Task runs it windowless, and looks
    # exactly like "file not found" in the task's LastResult.
    # default=SUPPRESS is load-bearing: without it these would overwrite the
    # value the main parser already set for "autostream --quiet run".
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true",
                        default=argparse.SUPPRESS)
    common.add_argument("-q", "--quiet", action="store_true",
                        default=argparse.SUPPRESS, help="no console output")

    sub = p.add_subparsers(dest="cmd")

    for name, fn, helptext in (
        ("setup", cmd_setup, "one-time interactive setup"),
        ("auth", cmd_auth, "re-run the OAuth flow"),
        ("refresh", cmd_refresh, "force a game index refresh"),
        ("scan", cmd_scan, "find installed games and apps -> config/apps.yaml"),
        ("detect", cmd_detect, "detection only — no streaming"),
        ("obs-test", cmd_obs_test, "30s private test stream"),
        ("run", cmd_run, "run the daemon"),
        ("status", cmd_status, "print current state"),
        ("stop", cmd_stop, "force-stop the current stream"),
        ("voice", cmd_voice, "check or download the spoken-hook voice model"),
    ):
        sp = sub.add_parser(name, help=helptext, parents=[common])
        sp.set_defaults(func=fn)
        if name == "voice":
            sp.add_argument("--download", action="store_true",
                            help="fetch the Kokoro model (177 MB)")
            sp.add_argument("--say", metavar="TEXT",
                            help="synthesise one line to a wav and stop")
            sp.add_argument("--out", metavar="FILE",
                            help="where --say writes (default hook.wav)")
            sp.add_argument("--voice", metavar="NAME",
                            help="which voice --say uses")
            sp.add_argument("--list-voices", action="store_true",
                            help="print every English voice, grouped")
            sp.add_argument("--sample", action="store_true",
                            help="render one wav per voice, to choose by ear")

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
