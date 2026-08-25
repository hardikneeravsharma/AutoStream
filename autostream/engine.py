"""The state machine. The ONLY place a stream is started, retitled or stopped.

IDLE -> ARMING -> STARTING -> TESTING -> LIVE -> COOLDOWN -> STOPPING -> IDLE
"""
from __future__ import annotations

import collections
import logging
import queue
import shutil
import time
from datetime import datetime, time as dtime
from pathlib import Path

import psutil

from . import history, notify, paths, state as st, titles
from .gameindex import GameHit, GameIndex
from .obs import Obs, ObsUnavailable
from .watcher import Watcher
from .youtube import DAILY_QUOTA, NotAuthorised, QuotaExhausted, YouTube

log = logging.getLogger("autostream.engine")

SESSION_COST = 250   # insert + bind + 2 transitions + complete


class Engine:
    def __init__(self, config):
        self.cfg = config
        self.state = st.State.load()
        self.index = GameIndex(config)
        self.watcher = Watcher(config, self.index)
        self.yt = YouTube(config, self.state)
        self.obs = Obs(config)
        # CLIPS-ONLY MODE. The state machine is the same shape either way --
        # spot the game, hold it through arm_delay, run a session, cool down --
        # because what changes is only what a session DOES. Off, a session is a
        # recording and nothing else: no broadcast, no OBS stream output, no
        # quota, no Google sign-in.
        self.streaming = bool(getattr(config.youtube, "enabled", True))
        if not self.streaming:
            log.info("streaming is off: AutoStream will record and clip only")
            if not config.record.enabled:
                # Neither half is switched on, so a session would spot the game
                # and then do nothing at all. Said once, loudly, at startup --
                # the alternative is a user watching IDLE forever and
                # reasonably concluding the app is broken.
                log.error("streaming AND recording are both off: nothing will "
                          "be produced. Turn on Settings > Recording.")
                notify.toast("AutoStream has nothing to do",
                             "Streaming is off and so is recording. Turn on "
                             "recording to make clips.")

        self._phase_since = time.monotonic()
        self._switch_candidate: tuple[str, float] | None = None
        self._starting_deadline: float | None = None
        self._obs_down_since: float | None = None
        self._stop_requested = False
        self._start_failures = 0
        # The rendered title is only built inside _begin_session, but the
        # journal is written at the far end of the session and wants it.
        self._last_title: str | None = None
        # Black-output watchdog; see _check_picture.
        self._blank_checked = 0.0
        self._blank_strikes = 0
        # Screen savers: when the starting card should give way to the game,
        # and when the ending card has been shown long enough to stop. Held by
        # a deadline rather than a sleep, because this loop is strictly serial
        # and sleeping in it stops the OBS watchdog and chat with it.
        self._screen_until: float | None = None
        self._ending_until: float | None = None
        # Set when a session ends with a recording and record.auto_scan is on.
        # The Clips job runner picks it up; the engine never scans anything
        # itself, because a multi-minute ffmpeg pass on this thread would
        # freeze every phase transition behind it.
        self.pending_scan: dict | None = None

        # UI runs on another thread; it never touches YouTube/OBS directly.
        # It posts commands here and the engine thread drains them each tick.
        self._commands: queue.Queue = queue.Queue()
        self.viewers: int | None = None
        self.likes: int | None = None
        self.views: int | None = None
        self.obs_health: dict = {}
        self.chat: collections.deque = collections.deque(maxlen=120)
        self._chat_id: str | None = None
        self._chat_token: str | None = None
        self._chat_next_poll = 0.0
        self._chat_interval = 5.0
        self._details_checked = 0.0
        self._obs_checked = 0.0
        # Chat costs a quota unit per poll, so it only runs while somebody
        # actually has a dashboard open. web.py stamps this.
        self.client_seen = 0.0
        # exe -> "stream" | "silent". Set when the user launches something from
        # the dashboard, so "Open" and "Open & stream" behave differently.
        # Cleared when that executable is no longer running.
        self.launch_intent: dict[str, str] = {}
        # Why we are sitting idle while a game IS running. Surfaced in the
        # panel and dashboard - a silent refusal looks identical to a bug.
        self.blocked_reason: str | None = None

    # ================= lifecycle =================

    def startup(self) -> None:
        log.info("=" * 60)
        log.info("AutoStream starting up")
        self.index.refresh(force=False)
        self.index.reload()
        warn = self.index.coverage_warning()
        if warn:
            log.error(warn)
            notify.toast("AutoStream: no games known", warn[:180])
        self._recover()

    def _recover(self) -> None:
        """A crash mid-session leaves a broadcast live on the channel. Kill it."""
        if self.state.phase in (st.LIVE, st.TESTING, st.STARTING, st.COOLDOWN):
            log.warning("recovering from unclean shutdown (phase was %s)", self.state.phase)
            # Close the recording too, and journal it. OBS survives an
            # AutoStream crash perfectly well and would otherwise keep writing
            # to a file nothing remembers starting.
            rec_path = self._stop_recording()
            try:
                self.obs.stop()
            except Exception:  # noqa: BLE001
                pass
            if self.streaming:
                try:
                    n = self.yt.sweep_orphans()
                    log.info("orphan sweep completed %d broadcast(s)", n)
                except (NotAuthorised, Exception) as e:  # noqa: BLE001
                    log.error("orphan sweep failed: %s", e)
            self._journal(rec_path)
            self.state.reset_session()
            self.state.save()

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        self.startup()
        interval = max(1, int(self.cfg.timing.poll_interval))
        while not self._stop_requested:
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - a bug must never kill the daemon
                log.exception("tick failed: %s", e)
            time.sleep(interval)
        log.info("stop requested — shutting down")
        self.force_stop("daemon shutting down", suppress=False)

    # ================= gating =================

    def _paused(self) -> bool:
        flag = self.cfg.rules.paused_flag_file
        return bool(flag) and (paths.ROOT / flag).exists()

    def _in_quiet_hours(self, now: datetime | None = None) -> bool:
        qh = self.cfg.rules.quiet_hours or []
        if len(qh) != 2:
            return False
        now = now or datetime.now()
        try:
            start = dtime.fromisoformat(str(qh[0]))
            end = dtime.fromisoformat(str(qh[1]))
        except ValueError:
            return False
        t = now.time()
        if start <= end:
            return start <= t < end
        return t >= start or t < end        # window crosses midnight

    def _preflight(self, force: bool = False) -> str | None:
        """Return a reason string if we must NOT start, else None.

        `force` is set when the user explicitly pressed "Open & stream", which
        overrides the convenience guards (quiet hours, battery) but NEVER the
        safety ones (paused, disk, quota).
        """
        if self._paused():
            return f"paused ({self.cfg.rules.paused_flag_file} present)"
        if self.state.paused:
            return "paused via kill switch"
        if not force and self._in_quiet_hours():
            return "inside quiet hours"
        if not force and self.cfg.rules.require_ac_power:
            bat = psutil.sensors_battery()
            if bat is not None and not bat.power_plugged:
                return "on battery power"
        try:
            free_gb = shutil.disk_usage(str(paths.ROOT)).free / (1024 ** 3)
            if free_gb < float(self.cfg.rules.min_free_disk_gb):
                return f"only {free_gb:.1f} GB free"
        except OSError:
            pass
        if (self.streaming and self.state.quota_left(DAILY_QUOTA)
                < SESSION_COST + self.cfg.rules.quota_reserve):
            return f"quota too low ({self.state.quota_left(DAILY_QUOTA)} units left)"
        return None

    # ================= phase helpers =================

    def _goto(self, phase: str) -> None:
        if phase == self.state.phase:
            return
        log.info("phase %s -> %s", self.state.phase, phase)
        self.state.phase = phase
        self.state.save()          # persist BEFORE the side effect
        self._phase_since = time.monotonic()

    def _elapsed(self) -> float:
        return time.monotonic() - self._phase_since

    def _vars(self, hit: GameHit) -> dict:
        start = datetime.fromtimestamp(self.state.session_start or time.time())
        return titles.build_vars(
            game=hit.name,
            hook=self.state.hook or titles.pick_hook(self.cfg),
            session_games=self.state.session_games or [hit.name],
            session_start=start,
            session_number=self.state.session_number,
            blurb=hit.blurb,
            username=getattr(hit, "username", "") or "",
        )

    # ================= the tick =================

    def submit(self, command: str) -> None:
        """Thread-safe entry point for the UI. Never blocks, never side-effects."""
        self._commands.put(command)

    def _drain_commands(self) -> None:
        while True:
            try:
                cmd = self._commands.get_nowait()
            except queue.Empty:
                return
            # commands are either a bare string or (name, payload)
            payload = None
            if isinstance(cmd, tuple):
                cmd, payload = cmd
            log.info("command from UI: %s", cmd)
            try:
                if cmd == "chat":
                    self.yt.send_chat(self._chat_id, str(payload or ""))
                elif cmd == "launch":
                    self._launch(payload or {})
                elif cmd == "stop":
                    self.force_stop("control panel")
                elif cmd == "pause":
                    if not self.state.paused:
                        self.toggle_pause("pause button")
                elif cmd == "resume":
                    if self.state.paused:
                        self.toggle_pause("resume button")
                    else:
                        # Not paused, but possibly stopped-and-stuck. Resume is
                        # the button a user presses to mean "carry on", so it
                        # clears the manual-stop flag either way.
                        self._resume()
                elif cmd == "toggle_pause":
                    self.toggle_pause()
                elif cmd == "kill":
                    self.kill()
                elif cmd == "quit":
                    self._stop_requested = True
                else:
                    log.warning("unknown command %r", cmd)
            except Exception as e:  # noqa: BLE001
                log.exception("command %r failed: %s", cmd, e)

    def tick(self) -> None:
        self._drain_commands()
        if self._stop_requested:
            return
        phase = self.state.phase

        if phase == st.IDLE:
            self._tick_idle()
        elif phase == st.ARMING:
            self._tick_arming()
        elif phase == st.STARTING:
            self._tick_starting()
        elif phase == st.TESTING:
            self._tick_testing()
        elif phase == st.LIVE:
            self._tick_live()
        elif phase == st.COOLDOWN:
            self._tick_cooldown()
        elif phase == st.STOPPING:
            self._tick_stopping()
        else:
            log.error("unknown phase %r — resetting", phase)
            self.state.reset_session()
            self.state.save()

    # ---- IDLE -------------------------------------------------------

    def _launch(self, payload: dict) -> None:
        """Start an app from the dashboard, recording what should happen next."""
        from . import catalog

        key = str(payload.get("key", ""))
        want_stream = bool(payload.get("stream"))
        app = catalog.find(catalog.load(), key)
        if app is None:
            log.warning("launch: unknown app %r", key)
            return
        if app.exe:
            self.launch_intent[app.exe.lower()] = "stream" if want_stream else "silent"
        if not catalog.launch(app):
            self.launch_intent.pop((app.exe or "").lower(), None)
            return
        log.info("launched %s with intent=%s", app.name,
                 "stream" if want_stream else "silent")
        notify.toast("AutoStream",
                     f"Launching {app.name}"
                     + (" and going live" if want_stream else " (not streaming)"))

    def _intent_for(self, hit: GameHit) -> str | None:
        return self.launch_intent.get((hit.key or "").lower())

    def _prune_intents(self) -> None:
        """Forget intents for things that are no longer running."""
        if not self.launch_intent:
            return
        seen, _u, _v = self.watcher.snapshot()
        running = {h.key.lower() for h in seen.values()}
        for exe in list(self.launch_intent):
            if exe not in running:
                self.launch_intent.pop(exe, None)

    def _tick_idle(self) -> None:
        self._prune_intents()
        hit = self.watcher.active_game()
        if hit is None:
            if self.blocked_reason:
                self.blocked_reason = None
            return

        intent = self._intent_for(hit)
        if intent in ("silent", "stopped"):
            why = ("opened without streaming" if intent == "silent"
                   else "stopped manually - close the game to reset")
            if self.blocked_reason != why:
                self.blocked_reason = why
                log.info("%s: %s", hit.name, why)
            return

        reason = self._preflight(force=(intent == "stream"))
        if reason:
            # Log once per change, not every 3s, but never stay silent.
            if reason != self.blocked_reason:
                self.blocked_reason = reason
                log.warning("%s is running but AutoStream will NOT start: %s",
                            hit.name, reason)
            return
        self.blocked_reason = None
        log.info("candidate detected: %s (%s, via %s)", hit.name, hit.key, hit.source)
        self._goto(st.ARMING)

    # ---- ARMING -----------------------------------------------------

    def _tick_arming(self) -> None:
        # An explicit "Open & stream" has already expressed intent - no need to
        # wait out the debounce that exists to filter accidental launches.
        express = self.watcher.active_game()
        if express is not None and self._intent_for(express) == "stream":
            if not self._preflight(force=True):
                log.info("explicit launch - skipping arm delay")
                self._begin_session(express)
                return

        hit = self.watcher.armed_game()
        if hit is None:
            if not self.watcher.any_game_running():
                log.info("candidate went away before arming completed")
                self._goto(st.IDLE)
            return
        reason = self._preflight()
        if reason:
            log.info("armed but blocked: %s", reason)
            self._goto(st.IDLE)
            return
        self._begin_session(hit)

    def _begin_session(self, hit: GameHit) -> None:
        self.state.session_start = time.time()
        self.state.session_number += 1
        self.state.hook = titles.pick_hook(self.cfg)
        self.state.current_game = hit.name
        self.state.current_key = hit.key
        self.state.session_games = [hit.name]
        self.state.save()

        v = self._vars(hit)
        title = titles.render_title(self.cfg, v)
        desc = titles.render_description(self.cfg, v)
        self._last_title = title

        self._goto(st.STARTING)
        if not self.streaming:
            self._begin_recording_only(hit)
            return
        try:
            self.yt.check_budget(SESSION_COST)
            bid = self.yt.create_broadcast(title, desc, privacy=hit.privacy)
            self.state.broadcast_id = bid
            self.state.save()
            self.yt.bind(bid, self.cfg.youtube.stream_id)
            # Open ON the starting card where there is one. Starting on the
            # game scene and switching a moment later shows the game for a
            # frame or two at the top of every stream -- which is the one
            # moment the card exists to cover.
            from . import screens

            opening = screens.ensure(self.cfg, self.obs, screens.STARTING)
            self.obs.start(scene=opening or hit.scene, overlay=hit.name)
            self._start_recording()
            self._starting_deadline = time.monotonic() + self.cfg.timing.ingestion_timeout
            log.info("session #%d started: %s", self.state.session_number, title)
        except (QuotaExhausted, NotAuthorised) as e:
            log.error("cannot start session: %s", e)
            notify.toast("AutoStream blocked", str(e))
            self._abandon_start()
        except ObsUnavailable as e:
            log.error("OBS unavailable: %s", e)
            notify.toast("AutoStream: OBS unavailable", str(e))
            self._abandon_start()
        except Exception as e:  # noqa: BLE001
            log.exception("session start failed: %s", e)
            self._abandon_start()

    def _begin_recording_only(self, hit: GameHit) -> None:
        """A session with no broadcast: start recording and go straight to LIVE.

        No ingestion to wait for and nothing to hold in `testing`, so STARTING
        and TESTING have nothing to do -- and a phase that exists only to be
        skipped is a phase somebody will one day debug for an hour.
        """
        try:
            self.obs.set_overlay_text(hit.name)
        except Exception:  # noqa: BLE001
            pass
        self._start_recording()
        if not self.state.recording:
            # The whole point of the session is the recording. Without one
            # there is nothing to clip and nothing to show, so say so rather
            # than sitting in a LIVE phase that is not doing anything.
            log.error("recording did not start; nothing to do without it")
            notify.toast("AutoStream", "Could not start recording. Check OBS.")
            self._abandon_start()
            return
        self._start_failures = 0
        self._goto(st.LIVE)
        self._show_starting()
        log.info("recording session #%d: %s", self.state.session_number, hit.name)
        notify.toast("AutoStream is recording", hit.name)

    # ---- local recording --------------------------------------------
    #
    # Recording is strictly a side benefit: it produces the clean master the
    # Clips page cuts from. Every failure path here logs and returns, because
    # nothing about recording is worth interrupting a live broadcast for.

    def _start_recording(self) -> None:
        if not self.cfg.record.enabled:
            return
        want = (self.cfg.record.directory or "").strip()
        if want and self.obs.record_directory() != want:
            # Pushed here rather than at startup so it survives someone editing
            # it in OBS: the config is the source of truth every session.
            self.obs.set_record_directory(want)
        free = self._free_gb()
        if free is not None and free < self.cfg.record.min_free_gb:
            # Refuse rather than make room. Deleting the user's video files to
            # fit a new recording is never the right call.
            log.warning("not recording: %.0f GB free, need %s",
                        free, self.cfg.record.min_free_gb)
            notify.toast("AutoStream: recording skipped",
                         f"Only {free:.0f} GB free on the recording drive.")
            return
        try:
            # Was OBS already rolling? start_recording() reuses an existing
            # output rather than interrupting a recording you started yourself,
            # but that means the file can predate the session by a long way --
            # and cover a completely different game. Remember which it was, so
            # the journal does not later claim the whole file is this session.
            already = self.obs.recording_active()
            self.obs.start_recording()
            self.state.recording = True
            self.state.recording_adopted = already
            self.state.save()
            if already:
                log.info("OBS was already recording; adopting that file. Its "
                         "earlier footage is not part of this session.")
        except Exception as e:  # noqa: BLE001
            log.warning("could not start recording: %s", e)

    def _stop_recording(self) -> str | None:
        if not self.state.recording:
            return None
        path = self.obs.stop_recording()          # already swallows its errors
        self.state.recording = False
        return path

    # A completely black program output while live. Every other readout says
    # healthy in this state -- OBS reports streaming, YouTube reports ingest,
    # bitrate looks plausible because black compresses to nothing -- so it can
    # run for a whole session unnoticed. It has happened twice here: once from
    # anti-cheat blocking the capture hook, once from a capture source pinned
    # to a game that was not running.
    BLANK_EVERY = 30.0        # seconds between checks; this is not free
    BLANK_STRIKES = 2         # consecutive black samples before saying so
    BLANK_LEVEL = 6.0         # mean 0-255 under which a frame is "no picture"

    def _check_picture(self) -> None:
        now = time.monotonic()
        if now - self._blank_checked < self.BLANK_EVERY:
            return
        self._blank_checked = now
        try:
            from PIL import Image
        except ImportError:
            return                       # Pillow is optional; skip quietly
        png = self.obs.screenshot(160, 90)
        if not png:
            return
        try:
            import io

            # Downscale to a single pixel and read it: that IS the mean, and
            # it avoids walking every pixel in Python on the engine thread.
            im = Image.open(io.BytesIO(png)).convert("L").resize((1, 1))
            mean = float(im.getpixel((0, 0)))
        except Exception:  # noqa: BLE001
            return

        if mean >= self.BLANK_LEVEL:
            if self._blank_strikes:
                log.info("picture is back")
            self._blank_strikes = 0
            return

        self._blank_strikes += 1
        if self._blank_strikes == self.BLANK_STRIKES:
            log.error("STREAM HAS NO PICTURE - OBS program output is black. "
                      "Check the capture source: a game-capture pinned to a "
                      "window that is not running, or a hook blocked by "
                      "anti-cheat (run OBS as administrator).")
            notify.toast("AutoStream: no picture",
                         "The stream is black. Check your OBS capture source.")

    def _set_thumbnail(self) -> None:
        """Compose a thumbnail from the live picture and upload it.

        Runs AFTER the transition to live, never before: the frame has to show
        the game actually rendering, and nothing here is worth delaying a
        broadcast for. Every failure is contained -- the stream is already up.
        """
        if not self.cfg.thumbnail.enabled or not self.state.broadcast_id:
            return
        try:
            from . import thumbnail

            hit = self.watcher.active_game()
            path = thumbnail.build_for_session(
                self.cfg, self.obs,
                designated=(getattr(hit, "thumbnail", "") if hit else ""),
                game=self.state.current_game or "",
                username=self._username_for(self.state.current_key))
            if not path:
                return
            self.last_thumbnail = str(path)
            if self.cfg.thumbnail.upload:
                self.yt.set_thumbnail(self.state.broadcast_id, path)
        except Exception as e:  # noqa: BLE001
            log.warning("thumbnail step failed (stream unaffected): %s", e)

    def _username_for(self, game_key: str | None) -> str:
        """The in-game name for this game, from games.yaml.

        Per game rather than global because they genuinely differ, and a
        killfeed detector needs the right one to tell your kills from
        everyone else's.
        """
        if not game_key:
            return ""
        try:
            entry = self.index.overrides.get(game_key.lower()) or {}
            return str(entry.get("username") or "")
        except Exception:  # noqa: BLE001
            return ""

    def _journal(self, recording_path: str | None) -> None:
        """Write the finished session to history.jsonl. Call before
        reset_session()."""
        bid = self.state.broadcast_id
        try:
            entry = history.record_session(
                self.state,
                watch_url=self.yt.watch_url(bid) if bid else None,
                title=self._last_title,
                recording_path=recording_path,
            )
            if entry and self.cfg.record.auto_scan and recording_path:
                self.pending_scan = entry
        except Exception as e:  # noqa: BLE001
            log.warning("could not journal session: %s", e)

    def _free_gb(self) -> float | None:
        """Free space on the drive OBS records to, not on the AutoStream drive.
        They are frequently different disks."""
        target = self.cfg.record.directory or None
        if not target:
            try:
                target = self.obs.record_directory()
            except Exception:  # noqa: BLE001
                target = None
        if not target:
            return None
        try:
            return shutil.disk_usage(target).free / 1024 ** 3
        except OSError:
            # Directory does not exist yet; fall back to its nearest parent.
            p = Path(target)
            for parent in p.parents:
                try:
                    return shutil.disk_usage(parent).free / 1024 ** 3
                except OSError:
                    continue
            return None

    def _abandon_start(self) -> None:
        self._start_failures += 1
        if self.state.broadcast_id:
            try:
                self.yt.delete_broadcast(self.state.broadcast_id)
            except Exception:  # noqa: BLE001
                pass
        self._stop_recording()
        try:
            self.obs.stop()
        except Exception:  # noqa: BLE001
            pass
        self.state.reset_session()
        self.state.save()
        self._goto(st.IDLE)
        if self._start_failures >= 3:
            log.error("3 consecutive start failures — pausing until restart")
            self.state.paused = True
            self.state.save()
            notify.toast("AutoStream paused",
                         "3 failed start attempts. Check logs/autostream.log.")

    # ---- STARTING ---------------------------------------------------

    def _tick_starting(self) -> None:
        if self._starting_deadline and time.monotonic() > self._starting_deadline:
            log.error("YouTube never saw our ingestion — aborting session")
            notify.toast("AutoStream", "Stream never reached YouTube. Aborted.")
            self._abandon_start()
            return
        try:
            status, health = self.yt.stream_status(self.cfg.youtube.stream_id)
        except Exception as e:  # noqa: BLE001
            log.warning("stream status check failed: %s", e)
            return
        log.debug("ingestion status=%s health=%s", status, health)
        if status != "active":
            return
        if health not in ("good", "ok", "noData"):
            log.warning("ingestion health is %s — continuing anyway", health)

        self._start_failures = 0
        if self.cfg.timing.abort_grace > 0:
            try:
                self.yt.transition(self.state.broadcast_id, "testing")
                self._goto(st.TESTING)
                notify.toast(
                    "AutoStream going live",
                    f"{self.state.current_game} — public in "
                    f"{self.cfg.timing.abort_grace}s. Kill switch to cancel.",
                    self.yt.watch_url(self.state.broadcast_id),
                )
                return
            except Exception as e:  # noqa: BLE001
                log.warning("testing transition failed (%s) — going straight to live", e)
        self._go_live()

    # ---- TESTING ----------------------------------------------------

    def _tick_testing(self) -> None:
        if self._elapsed() < self.cfg.timing.abort_grace:
            return
        self._go_live()

    def _go_live(self) -> None:
        if not self.streaming:
            self._goto(st.LIVE)
            return
        try:
            self.yt.transition(self.state.broadcast_id, "live")
        except Exception as e:  # noqa: BLE001
            log.exception("could not transition to live: %s", e)
            self._abandon_start()
            return
        self._goto(st.LIVE)
        self._show_starting()
        url = self.yt.watch_url(self.state.broadcast_id)
        log.info("LIVE: %s", url)
        notify.toast("AutoStream is live", self.state.current_game or "", url)
        self._set_thumbnail()
        try:
            self.yt.set_video_meta(self.state.broadcast_id,
                                   list(self.cfg.description.tags or []))
        except Exception:  # noqa: BLE001
            pass

    # ---- screen savers ----------------------------------------------

    def _show_starting(self) -> None:
        """Open the session on the starting card, if there is one."""
        from . import screens

        if screens.show(self.cfg, self.obs, screens.STARTING):
            self._screen_until = time.monotonic() + screens.hold_for(
                self.cfg, screens.STARTING)
            log.info("starting screen up for %.0fs",
                     screens.hold_for(self.cfg, screens.STARTING))

    def _back_to_game(self) -> None:
        """Put the game scene back on air and forget any screen deadline."""
        self._screen_until = None
        hit = self.watcher.active_game()
        scene = (hit.scene if hit else None) or self.cfg.obs.default_scene or None
        if scene:
            self.obs.set_scene(scene)
        if hit:
            self.obs.set_overlay_text(hit.name)

    def _tick_screen(self) -> None:
        """Hand the picture back to the game once the starting card is done.

        Not while paused: the be-right-back card is held by the pause, not by a
        timer, and this would otherwise pull it off after ten seconds.
        """
        if self._screen_until is None or self.state.paused:
            return
        if time.monotonic() >= self._screen_until:
            log.info("starting screen done -> game scene")
            self._back_to_game()

    # ---- LIVE -------------------------------------------------------

    def _tick_live(self) -> None:
        # hard safety valve
        max_s = float(self.cfg.timing.max_session_hours) * 3600
        if self.state.session_start and time.time() - self.state.session_start > max_s:
            log.warning("max session length reached — stopping")
            self._goto(st.STOPPING)
            return

        if self._paused():
            # The flag FILE is a different thing from the pause button: it is a
            # "do not stream" switch meant to be left in place, so it still
            # ends the session rather than parking it on a card.
            log.info("pause flag file present — stopping")
            self._goto(st.STOPPING)
            return

        if self.state.paused:
            # PAUSE KEEPS THE BROADCAST UP. A "be right back" card is a promise
            # to come back, and it can only be kept if there is still a stream
            # to come back to -- so pausing changes the picture and nothing
            # else. The picture switch itself happens in toggle_pause; here we
            # only decline to do anything a paused stream should not do.
            self._check_picture()
            return

        self._check_picture()
        self._tick_screen()

        # OBS health: only give up after a sustained outage, let OBS reconnect
        # first. With streaming off the output to watch is the RECORDING --
        # checking is_streaming() there would report a dead output every tick
        # and end the session after two minutes, every time.
        alive = (self.obs.recording_active() if not self.streaming
                 else self.obs.is_streaming())
        if not alive:
            self._obs_down_since = self._obs_down_since or time.monotonic()
            down = time.monotonic() - self._obs_down_since
            log.warning("OBS output inactive for %.0fs", down)
            if down > 120:
                log.error("OBS output dead — ending session")
                self._goto(st.STOPPING)
                return
        else:
            self._obs_down_since = None

        if self.streaming:
            self._poll_live_extras()

        hit = self.watcher.active_game()
        if hit is None:
            log.info("no game running — entering cooldown")
            self._goto(st.COOLDOWN)
            return

        if hit.key != self.state.current_key:
            self._maybe_switch(hit)
        else:
            self._switch_candidate = None

    def _poll_live_extras(self) -> None:
        """Viewers/likes/views, OBS health, and chat — all best-effort.

        Quota: the details call is 1 unit a minute. Chat is 1 unit per poll but
        ONLY while a dashboard is open, so an unattended stream costs ~60/hour.
        """
        now = time.monotonic()
        watching = (now - self.client_seen) < 90

        # 1 unit / minute
        if now - self._details_checked > 60:
            self._details_checked = now
            try:
                d = self.yt.live_details(self.state.broadcast_id)
                self.viewers, self.likes, self.views = d["viewers"], d["likes"], d["views"]
                if d["chat_id"] and d["chat_id"] != self._chat_id:
                    self._chat_id = d["chat_id"]
                    self._chat_token = None
                    log.info("live chat attached")
            except Exception:  # noqa: BLE001
                pass

        # free — local websocket
        if now - self._obs_checked > 5:
            self._obs_checked = now
            try:
                self.obs_health = self.obs.health()
            except Exception:  # noqa: BLE001
                self.obs_health = {}

        # 1 unit per poll, only while someone is looking
        if watching and self._chat_id and now >= self._chat_next_poll:
            try:
                msgs, token, interval_ms = self.yt.chat_messages(
                    self._chat_id, self._chat_token)
                self._chat_token = token
                self._chat_interval = max(4.0, interval_ms / 1000)
                self._chat_next_poll = now + self._chat_interval
                for m in msgs:
                    self.chat.append(m)
            except Exception:  # noqa: BLE001
                self._chat_next_poll = now + 15

    def _maybe_switch(self, hit: GameHit) -> None:
        """Debounce a game switch so alt-tabbing doesn't spam the API."""
        now = time.monotonic()
        if self._switch_candidate is None or self._switch_candidate[0] != hit.key:
            self._switch_candidate = (hit.key, now)
            log.debug("switch candidate: %s", hit.name)
            return
        if now - self._switch_candidate[1] < self.cfg.timing.switch_delay:
            return

        self._switch_candidate = None
        log.info("game switch: %s -> %s", self.state.current_game, hit.name)
        self.state.current_game = hit.name
        self.state.current_key = hit.key
        if hit.name not in self.state.session_games:
            self.state.session_games.append(hit.name)
        self.state.save()

        self.obs.set_scene(hit.scene)
        self.obs.set_overlay_text(hit.name)

        if not self.streaming:
            # Nothing to retitle and nothing to restart. The recording carries
            # on across the switch, and history.jsonl already records every
            # game a session covered.
            return
        if self.cfg.youtube.switch_policy == "new_broadcast":
            self._restart_broadcast(hit)
            return

        v = self._vars(hit)
        try:
            self.yt.retitle(self.state.broadcast_id,
                            titles.render_title(self.cfg, v),
                            titles.render_description(self.cfg, v))
        except Exception as e:  # noqa: BLE001
            log.warning("retitle failed (non-fatal): %s", e)

    def _restart_broadcast(self, hit: GameHit) -> None:
        old = self.state.broadcast_id
        try:
            self.yt.transition(old, "complete")
        except Exception as e:  # noqa: BLE001
            log.warning("could not complete old broadcast: %s", e)
        v = self._vars(hit)
        try:
            bid = self.yt.create_broadcast(titles.render_title(self.cfg, v),
                                           titles.render_description(self.cfg, v),
                                           privacy=hit.privacy)
            self.yt.bind(bid, self.cfg.youtube.stream_id)
            self.state.broadcast_id = bid
            self.state.save()
            self._starting_deadline = time.monotonic() + self.cfg.timing.ingestion_timeout
            self._goto(st.STARTING)
        except Exception as e:  # noqa: BLE001
            log.exception("new broadcast failed: %s", e)
            self._goto(st.STOPPING)

    # ---- COOLDOWN ---------------------------------------------------

    def _tick_cooldown(self) -> None:
        hit = self.watcher.active_game()
        if hit is not None:
            log.info("game returned during cooldown (%s) — staying live", hit.name)
            self._goto(st.LIVE)
            if hit.key != self.state.current_key:
                self._switch_candidate = (hit.key, 0.0)   # switch immediately
                self._maybe_switch(hit)
            return
        if self._elapsed() >= self.cfg.timing.cooldown:
            log.info("cooldown expired — stopping")
            self._goto(st.STOPPING)

    # ---- STOPPING ---------------------------------------------------

    def _tick_stopping(self) -> None:
        # The ending card, held before anything is torn down. This is the only
        # window in which it can be seen at all: afterwards the broadcast is
        # complete and there is nothing to show it on.
        from . import screens

        if self._ending_until is None and screens.configured(
                self.cfg, screens.ENDING) and self.state.broadcast_id:
            if screens.show(self.cfg, self.obs, screens.ENDING):
                hold = screens.hold_for(self.cfg, screens.ENDING)
                self._ending_until = time.monotonic() + hold
                log.info("ending screen up for %.0fs before stopping", hold)
                return
        if self._ending_until is not None:
            if time.monotonic() < self._ending_until:
                return
            self._ending_until = None

        bid = self.state.broadcast_id
        # Stop recording BEFORE the stream: stop_record() is the only thing
        # that reports the filename, and OBS needs the output closed before
        # the container is finalised and its size is meaningful.
        rec_path = self._stop_recording()
        if self.streaming:
            try:
                self.obs.stop()
            except Exception as e:  # noqa: BLE001
                log.warning("OBS stop failed: %s", e)
        if bid:
            try:
                self.yt.transition(bid, "complete")
                log.info("session complete: %s", self.yt.watch_url(bid))
                notify.toast("AutoStream stopped",
                             f"VOD: {', '.join(self.state.session_games)}",
                             self.yt.watch_url(bid))
            except Exception as e:  # noqa: BLE001
                log.warning("complete transition failed: %s", e)
        # The journal has to be written here. reset_session() below is the last
        # instant broadcast_id, session_games, current_game and session_start
        # all still exist, and the Clips page needs every one of them.
        self._journal(rec_path)
        self.state.reset_session()
        self.state.save()
        self.watcher.reset_debounce()     # next session serves a full arm_delay
        self._goto(st.IDLE)
        self._obs_down_since = None
        self._switch_candidate = None
        self._screen_until = None
        self._ending_until = None
        self.viewers = self.likes = self.views = None
        self.obs_health = {}
        self.chat.clear()
        self._chat_id = self._chat_token = None
        self._details_checked = 0.0

    # ================= external controls =================

    def force_stop(self, reason: str = "manual", suppress: bool = True) -> None:
        """Stop the current session.

        `suppress` marks whatever is running as "do not restart", because a
        human pressing End stream while a game is open means "stop streaming
        THIS", not "stop for one second then start again". Cleared when the
        game exits, so the next launch behaves normally.
        """
        if suppress:
            self._suppress_running()
        # Unconditional: whichever path we take out of here, the next session
        # must serve a fresh arm_delay rather than inherit an expired timer.
        self.watcher.reset_debounce()
        if self.state.phase in (st.IDLE, st.ARMING):
            self.state.reset_session()
            self.state.save()
            self.watcher.reset_debounce()
            return
        log.warning("force stop: %s", reason)
        self._goto(st.STOPPING)
        self._tick_stopping()

    def _suppress_running(self) -> None:
        """Mark every running game so it will not auto-restart a stream."""
        try:
            seen, _u, _v = self.watcher.snapshot()
        except Exception:  # noqa: BLE001
            return
        for hit in seen.values():
            key = (hit.key or "").lower()
            if key:
                self.launch_intent[key] = "stopped"
                log.info("%s will not restart streaming until you close it",
                         hit.name)

    def toggle_pause(self, reason: str = "pause button") -> bool:
        """Pause or resume. -> whether it is now paused.

        PAUSING A LIVE SESSION KEEPS IT LIVE and puts the be-right-back card on
        air. That is what pause means to a viewer: a promise to come back, and
        one that can only be kept if there is still a broadcast to come back to.
        Ending it and starting a fresh one loses the URL, the chat and everyone
        watching.

        Without a card configured there is nothing to switch TO, so a live
        session is stopped instead -- a paused stream showing the game is not
        paused, it is just unattended.

        PAUSING DOES NOT SUPPRESS THE RUNNING GAME either way. `force_stop`
        marks every open game "do not restart" because a human pressing End
        stream means "stop streaming THIS", and that flag is only cleared when
        the game exits -- so borrowing it for pause meant Resume did nothing at
        all and the only way out was to close the game.
        """
        from . import screens

        self.state.paused = not self.state.paused
        self.state.save()
        log.warning("paused=%s (%s)", self.state.paused, reason)

        if not self.state.paused:
            self._resume()
            notify.toast("AutoStream", "Resumed")
            return False

        live = self.state.phase in (st.LIVE, st.TESTING)
        if live and screens.show(self.cfg, self.obs, screens.PAUSED):
            self._screen_until = None      # held by the pause, not by a timer
            log.info("be right back: the broadcast stays up")
            notify.toast("AutoStream paused", "Be right back is on air")
            return True
        if live:
            log.info("no be-right-back screen configured, so pausing stops the "
                     "session instead")
        notify.toast("AutoStream", "Paused")
        self.force_stop(reason, suppress=False)
        return True

    def kill(self, reason: str = "kill switch") -> None:
        """Stop everything now, and stay stopped. The hotkey's job.

        Kept separate from pause now that pause holds a stream up rather than
        ending it. A kill switch that parks the stream on a card is not a kill
        switch, and the hotkey is documented as one.
        """
        log.warning("kill switch: %s", reason)
        notify.toast("AutoStream", "Stopped by the kill switch")
        self.state.paused = True
        self.state.save()
        self.force_stop(reason, suppress=False)

    def _resume(self) -> None:
        """Undo everything pausing put in the way of carrying on.

        Two different situations, and both arrive here: a session still LIVE on
        the be-right-back card just needs the game scene back, and one that was
        stopped needs the flags clearing so it can start again.
        """
        if self.state.phase in (st.LIVE, st.TESTING):
            self._back_to_game()
            log.info("resumed: back to the game scene")
        for exe, intent in list(self.launch_intent.items()):
            if intent == "stopped":
                self.launch_intent.pop(exe, None)
                log.info("%s may stream again", exe)
        # A fresh arm_delay rather than an expired timer inherited from before
        # the pause, which could otherwise start a session the same tick.
        self.watcher.reset_debounce()
        self.blocked_reason = None
