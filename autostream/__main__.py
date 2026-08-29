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
import signal
import sys
import time
from pathlib import Path

from . import cfg, notify, paths, single


def setup_logging(level: str = "INFO", console: bool = True) -> None:
    paths.ensure_dirs()
    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    root.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)-18s %(message)s",
                            "%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.TimedRotatingFileHandler(
        paths.LOG_FILE, when="midnight", backupCount=7, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        root.addHandler(ch)

    logging.getLogger("googleapiclient").setLevel(logging.ERROR)
    logging.getLogger("google_auth_oauthlib").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


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
    eng.force_stop("cli stop")
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
    """The poll loop. Runs on the main thread, or on a worker thread when the
    control panel owns the main thread (tkinter requires it)."""
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


# How long the setup server keeps answering after the install becomes
# configured. Long enough for the finish response to arrive, for the page to
# render what it says, and for a person to read it before the process exits.
SETUP_LINGER = 10.0


def cmd_run(args) -> int:
    """Main entry: web UI + native window + overlay + tray + engine.

    Thread layout, because three libraries all want to own a thread:
      main    - pywebview native window (it insists on the main thread)
      worker  - the engine poll loop
      worker  - the tkinter overlay panel
      worker  - the HTTP server, the tray icon
    """
    import secrets as _secrets
    import threading

    from .engine import Engine
    from .panel import ControlPanel, available as panel_available
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

    server = Server(token, port, engine)
    if server.start() is None:
        log.error("could not start the UI server on port %d", port)
        return 1

    if first_run:
        log.info("no configuration found - starting the setup wizard")

    win_ref = {}

    def _sig(_signum, _frame):
        log.info("signal received - stopping")
        if engine:
            engine.request_stop()
        w = win_ref.get("w")
        if w is not None:
            w.request_quit()          # otherwise webview.start() never returns

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

    # --- overlay panel + tray, only once configured ---
    pnl = None
    tray = None
    if engine is not None:
        use_panel = (config.rules.control_panel and panel_available()
                     and not args.no_panel)
        pnl = ControlPanel(engine) if use_panel else None
        if pnl is not None:
            pnl.open_window = win.request_show
        tray = Tray(engine, pnl)
        tray.window = win
        tray.start()

        hotkey = config.rules.kill_switch_hotkey
        if hotkey:
            try:
                import keyboard

                # "kill", not "toggle_pause": pause now holds a live stream on
                # the be-right-back card instead of ending it, and a kill
                # switch that does that is not a kill switch.
                keyboard.add_hotkey(hotkey, lambda: engine.submit("kill"))
                log.info("kill switch hotkey: %s", hotkey)
            except Exception as e:  # noqa: BLE001
                log.info("hotkey unavailable (%s) - use the tray icon", e)

        engine.startup()
        interval = max(1, int(config.timing.poll_interval))
        threading.Thread(target=_engine_loop,
                         args=(engine, tray, interval, log),
                         name="autostream-engine", daemon=True).start()

        if pnl is not None:
            # tkinter is happy off-main as long as every Tk call is on the
            # thread that created the root, which panel.run() guarantees.
            threading.Thread(target=_safe_panel, args=(pnl, log),
                             name="autostream-panel", daemon=True).start()

    # blocks until the window is destroyed (or returns at once without pywebview)
    win.run()

    if engine is None:
        # Setup mode with no native window: hold the process open so the
        # wizard in the browser can finish.
        #
        # THE WIZARD'S OWN SUCCESS USED TO KILL IT. finish() saves
        # youtube.stream_id part-way through its work, which is the moment
        # is_configured() turns true -- while the request that caused it is
        # still being answered. This loop saw that within two seconds and
        # stopped the server underneath the response, so the browser got a
        # connection reset and the last thing every new user saw was "Failed
        # to fetch" on a setup that had in fact worked.
        #
        # So: never while a request is in flight, and not until the answer has
        # had time to arrive and be read.
        log.info("setup wizard running at %s", server.url())
        try:
            while not win._quit:                          # noqa: SLF001
                if is_configured() and server.idle_for() >= SETUP_LINGER:
                    log.info("setup complete - restart AutoStream to begin "
                             "streaming")
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    else:
        if win.fell_back:
            # No native window to block on, so THIS loop is what keeps the
            # daemon -- and the server the browser was just pointed at --
            # alive. Without it a machine with no WebView2 runtime ran the
            # whole daemon for the fraction of a second run() took to return,
            # and the UI it had opened could not even load.
            log.info("the UI is in your browser at %s", server.url())
            try:
                while not win._quit:              # noqa: SLF001
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        engine.request_stop()
        time.sleep(0.6)
        engine.force_stop("shutdown")

    server.stop()
    single.release()
    log.info("AutoStream exited cleanly")
    return 0


def _safe_panel(pnl, log) -> None:
    try:
        pnl.run()
    except Exception as e:  # noqa: BLE001
        log.warning("overlay panel unavailable (%s) - tray and window still work", e)


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
        sp.set_defaults(func=fn, no_panel=False)
        if name == "run":
            sp.add_argument("--no-panel", action="store_true",
                            help="run without the control panel window")
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
