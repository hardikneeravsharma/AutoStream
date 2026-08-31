"""obs-websocket 5 wrapper. Launches OBS if it isn't running."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import psutil

log = logging.getLogger("autostream.obs")

try:
    import obsws_python as obsws
except ImportError:  # pragma: no cover
    obsws = None


class ObsUnavailable(RuntimeError):
    pass


def _obs_process_alive() -> bool:
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info.get("name") or "").lower() in ("obs64.exe", "obs32.exe", "obs"):
                return True
        except psutil.Error:
            continue
    return False


# obs-websocket writes its own settings here, and they are the three things
# setup used to ask a person to copy by hand. The file is JSON carrying
# server_enabled / server_port / server_password / auth_required.
#
# The portable build keeps the same tree beside the executable instead, so both
# are checked -- portable is common on a machine where the user cannot write to
# Program Files, which is exactly the machine where hand-copying a generated
# password goes wrong.
WS_CONFIG = ("plugin_config", "obs-websocket", "config.json")


def _ws_config_paths(obs_exe: str = "") -> list[Path]:
    out: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(Path(appdata).joinpath("obs-studio", *WS_CONFIG))
    if obs_exe:
        # ...\obs-studio\bin\64bit\obs64.exe -> ...\obs-studio\config\obs-studio
        exe = Path(obs_exe)
        if len(exe.parents) > 2:
            out.append(exe.parents[2].joinpath("config", "obs-studio", *WS_CONFIG))
    return out


def discover_websocket(obs_exe: str = "") -> dict:
    """What OBS has already decided about its own WebSocket server.

    -> {found, enabled, port, password, auth_required, source}. `found` is
    False when there is nothing to read, which only means OBS has never opened
    the WebSocket dialog on this machine.

    Never raises: this feeds a setup screen, and an unreadable OBS profile
    should fall back to asking rather than failing.
    """
    out = {"found": False, "enabled": False, "port": 4455,
           "password": "", "auth_required": True, "source": ""}
    for path in _ws_config_paths(obs_exe):
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        out["found"] = True
        out["source"] = str(path)
        out["enabled"] = bool(data.get("server_enabled", False))
        out["auth_required"] = bool(data.get("auth_required", True))
        try:
            out["port"] = int(data.get("server_port") or 4455)
        except (TypeError, ValueError):
            out["port"] = 4455
        # A server with auth off ignores whatever password is stored, and
        # handing that stale value to the client fails in a way nobody could
        # explain from the error.
        out["password"] = ("" if not out["auth_required"]
                           else str(data.get("server_password") or ""))
        return out
    return out


def find_obs_exe() -> str:
    """The OBS executable: from the registry where it is recorded, else a guess."""
    try:
        import winreg

        sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\OBS Studio"
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    root = Path(winreg.QueryValueEx(k, "InstallLocation")[0])
                    exe = root.joinpath("bin", "64bit", "obs64.exe")
                    if exe.is_file():
                        return str(exe)
            except OSError:
                continue
    except ImportError:
        pass
    for guess in (r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
                  r"C:\Program Files (x86)\obs-studio\bin\64bit\obs64.exe"):
        if Path(guess).is_file():
            return guess
    return ""


class Obs:
    def __init__(self, config):
        self.cfg = config
        self.ws = None
        # Audio metering runs on its own thread; see audio_watch_start.
        self._audio_thread = None
        self._audio_client = None
        self._audio_stop = threading.Event()
        self._audio_heard: float | None = None
        # When each input was last heard, so one dead source among several is
        # distinguishable from the whole stream being silent.
        self._audio_by_input: dict[str, float] = {}
        # When to stop believing OBS is unreachable; see connect().
        self._down_until = 0.0
        self._audio_since = 0.0
        self._audio_ok = False

    # ---------------- connection ----------------

    def _connect(self, timeout: int = 5):
        if obsws is None:
            raise ObsUnavailable("obsws-python not installed")
        return obsws.ReqClient(
            host=self.cfg.obs.host,
            port=int(self.cfg.obs.port),
            password=self.cfg.obs_password,
            timeout=timeout,
        )

    def connect(self, *, wait: bool = False) -> None:
        """Reach OBS. -> nothing, or ObsUnavailable.

        `wait` is the difference between STARTING something and everything
        else. Starting a session is worth waiting for: OBS may still be
        loading, so it retries and will launch OBS itself. Nothing else is.

        Without that distinction every call took the full retry budget -- three
        attempts, twelve seconds apart, plus a launch -- whenever OBS was not
        answering. The engine loop is strictly serial, so half a minute of that
        blocks the tick, the ingestion timeout, and any button the user
        presses. A session once sat in STARTING with a dead websocket while
        End stream was pressed seven times, each press queueing behind the
        wait rather than doing anything.

        So a failure is REMEMBERED: for the next few seconds every non-waiting
        call fails at once instead of re-running the same doomed handshake.
        The engine keeps ticking, and the buttons answer.
        """
        if self.ws is not None:
            try:
                self.ws.get_version()
                return
            except Exception:  # noqa: BLE001
                self.ws = None

        now = time.monotonic()
        if not wait and now < self._down_until:
            raise ObsUnavailable(
                "OBS is not answering (it was checked a moment ago)")

        last: Exception | None = None
        attempts = self.ATTEMPTS if wait else 1
        for attempt in range(attempts):
            try:
                self.ws = self._connect()
                v = self.ws.get_version()
                self._down_until = 0.0
                log.info("connected to OBS %s (websocket rpc %s)",
                         getattr(v, "obs_version", "?"), getattr(v, "rpc_version", "?"))
                return
            except Exception as e:  # noqa: BLE001
                last = e
                # Only a caller that is willing to wait may start OBS. Doing it
                # from a status poll would relaunch it behind the user's back.
                if wait and not _obs_process_alive():
                    self._launch()
                log.info("OBS not ready (attempt %d/%d): %s",
                         attempt + 1, attempts, e)
                # NOT after the last attempt. Sleeping there delays the
                # failure by a full retry interval and changes nothing about
                # it -- the caller is already out of attempts.
                if attempt < attempts - 1:
                    time.sleep(self.RETRY_SECONDS)
        self._down_until = time.monotonic() + self.UNREACHABLE_FOR
        raise ObsUnavailable(f"could not reach obs-websocket: {last}")

    def probe(self) -> dict:
        """One quick look at OBS. Never launches it, never retries.

        connect() is built for the engine, which is right to wait: OBS may
        still be starting up and a session depends on it. A person who just
        pressed "Test" in the setup wizard is owed an answer in a second, and
        the retry loop makes that a 50-second freeze on the one machine where
        it is most likely to fail -- a first run, before anything is
        configured. It also LAUNCHES OBS, which is a surprising thing for a
        button called Test to do.

        -> {ok, version, scenes} or {ok: False, reason, error}, where `reason`
        names the fix rather than the symptom.
        """
        if obsws is None:
            return {"ok": False, "reason": "missing",
                    "error": "obsws-python is not installed."}
        if not _obs_process_alive():
            return {"ok": False, "reason": "not_running",
                    "error": "OBS is not running. Start OBS, then test again."}
        try:
            ws = self._connect(timeout=3)
            v = ws.get_version()
            scenes = [sc["sceneName"] for sc in ws.get_scene_list().scenes]
            try:
                ws.disconnect()
            except Exception:  # noqa: BLE001
                pass
            return {"ok": True, "version": getattr(v, "obs_version", "?"),
                    "scenes": scenes}
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            low = msg.lower()
            if any(k in low for k in ("auth", "password", "4009", "401")):
                return {"ok": False, "reason": "auth",
                        "error": "OBS is running but rejected the password. "
                                 "Copy it from OBS: Tools > WebSocket Server "
                                 "Settings > Show Connect Info."}
            if any(k in low for k in ("refused", "10061", "timed out", "timeout")):
                return {"ok": False, "reason": "closed",
                        "error": "OBS is running but is not listening on port "
                                 f"{self.cfg.obs.port}. Turn the server on in "
                                 "OBS: Tools > WebSocket Server Settings > "
                                 "Enable WebSocket server."}
            return {"ok": False, "reason": "error", "error": msg[:200]}

    # Retry budget for connect(). Named because probe() exists to NOT spend it.
    ATTEMPTS = 3
    RETRY_SECONDS = 12
    # How long a failure is believed before trying again. Long enough that a
    # dead websocket costs one handshake rather than one per call, short
    # enough that OBS coming back is noticed within a few ticks.
    UNREACHABLE_FOR = 20.0

    ARGS = ("--disable-shutdown-check", "--minimize-to-tray")

    def _launch(self) -> None:
        path = self.cfg.obs.path
        if not path or not os.path.exists(path):
            log.error("OBS executable not found at %s", path)
            return
        cwd = os.path.dirname(path)   # OBS dies without this — it can't find locale files
        if self.cfg.obs.launch_elevated:
            self._launch_elevated(path, cwd)
            return
        log.info("launching OBS from %s", path)
        try:
            subprocess.Popen(
                [path, *self.ARGS],
                cwd=cwd,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            )
        except OSError as e:
            if getattr(e, "winerror", None) == 740:
                log.error("OBS needs administrator rights to start. Turn on "
                          "Settings > OBS > 'Start OBS as administrator'.")
            else:
                log.error("failed to launch OBS: %s", e)

    def _launch_elevated(self, path: str, cwd: str) -> None:
        """Start OBS with administrator rights.

        Games with kernel anti-cheat -- Delta Force's ACE, Valorant's Vanguard,
        anything with EasyAntiCheat -- refuse OBS's Game Capture hook unless OBS
        is elevated. The failure is silent and total: the source stays black
        while every status readout says recording and streaming are fine, so
        you find out from the VOD.

        ShellExecute rather than Popen, because CreateProcess cannot raise
        privilege -- Popen against an elevated target fails with WinError 740.
        If AutoStream is itself elevated the child inherits and nothing prompts;
        otherwise Windows shows a UAC dialog, which is why this is opt-in.
        """
        log.info("launching OBS elevated from %s", path)
        try:
            import ctypes

            args = " ".join(self.ARGS)
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", path, args, cwd, 7)      # 7 = SW_SHOWMINNOACTIVE
            if rc <= 32:
                # 5 is ERROR_ACCESS_DENIED, which here means "user said No".
                log.error("elevated OBS launch failed (ShellExecute returned %s)%s",
                          rc, " - UAC was declined" if rc == 5 else "")
        except (AttributeError, OSError) as e:
            log.error("failed to launch OBS elevated: %s", e)

    def close(self) -> None:
        try:
            if self.ws is not None:
                self.ws.disconnect()
        except Exception:  # noqa: BLE001
            pass
        self.ws = None

    # ---------------- setup-time ----------------

    def configure_stream(self, ingestion_address: str, stream_key: str) -> None:
        """Written ONCE at setup. Never touched at runtime."""
        self.connect(wait=True)
        if self.cfg.obs.service_mode == "rtmp_common":
            self.ws.set_stream_service_settings(
                "rtmp_common", {"service": "YouTube - RTMPS", "key": stream_key})
        else:
            server = ingestion_address
            if not server.endswith("/"):
                server += "/"
            self.ws.set_stream_service_settings(
                "rtmp_custom", {"server": server, "key": stream_key, "use_auth": False})
        log.info("OBS stream service configured (%s)", self.cfg.obs.service_mode)

    def scene_names(self) -> list[str]:
        self.connect()
        r = self.ws.get_scene_list()
        return [s["sceneName"] for s in r.scenes]

    # ---------------- runtime ----------------

    def is_streaming(self) -> bool:
        try:
            self.connect()
            return bool(self.ws.get_stream_status().output_active)
        except Exception:  # noqa: BLE001
            return False

    # ---------------- is anything being heard ----------------
    #
    # The picture watchdog has a twin. A stream can be perfectly healthy by
    # every readout OBS offers -- output active, no dropped frames, a bright
    # picture -- and still be going out silent, because the scene collection
    # has no audio device in it, or the one it has is muted, or it is pointed
    # at a device that is not the one making sound. All three are invisible
    # from the request API: it reports what a source IS, never what it is
    # DOING.
    #
    # So the levels are read from the event stream instead, on their own
    # thread. InputVolumeMeters arrives about fifty times a second, which is
    # far too often to serve on the engine loop -- and the engine loop is
    # strictly serial, so anything that blocks it stops the OBS watchdog and
    # chat with it. The thread keeps one number: when sound was last heard.

    SILENCE_FLOOR = -55.0     # dBFS below which a peak is not audible content

    def audio_watch_start(self) -> None:
        """Begin listening to OBS's meters. Safe to call repeatedly."""
        if self._audio_thread is not None and self._audio_thread.is_alive():
            return
        if obsws is None:
            return
        self._audio_stop.clear()
        self._audio_heard = None
        self._audio_ok = False
        self._audio_by_input = {}
        # The clock silence is measured against until the first sound lands.
        self._audio_since = time.monotonic()
        self._audio_thread = threading.Thread(
            target=self._audio_loop, name="autostream-audio", daemon=True)
        self._audio_thread.start()

    def audio_watch_stop(self) -> None:
        self._audio_stop.set()
        client, self._audio_client = self._audio_client, None
        if client is not None:
            try:
                client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._audio_thread = None

    def _audio_loop(self) -> None:
        import math

        try:
            client = obsws.EventClient(
                host=self.cfg.obs.host, port=int(self.cfg.obs.port),
                password=self.cfg.obs_password,
                subs=obsws.Subs.INPUTVOLUMEMETERS)
        except Exception as e:  # noqa: BLE001
            log.info("audio metering unavailable (%s) - silence will not be "
                     "reported", e)
            return
        self._audio_client = client
        self._audio_ok = True
        log.info("listening to OBS audio levels")

        def on_input_volume_meters(data):
            now = time.monotonic()
            peak = -200.0
            for inp in getattr(data, "inputs", None) or []:
                name = str(inp.get("inputName") or "")
                best = -200.0
                for channel in inp.get("inputLevelsMul") or []:
                    # Three magnitudes per channel; the first is the peak.
                    if channel and channel[0] > 0:
                        best = max(best, 20 * math.log10(channel[0]))
                if name:
                    # Seen, so it exists; the timestamp only moves when it is
                    # actually carrying something.
                    self._audio_by_input.setdefault(name, 0.0)
                    if best >= self.SILENCE_FLOOR:
                        self._audio_by_input[name] = now
                peak = max(peak, best)
            if peak >= self.SILENCE_FLOOR:
                self._audio_heard = now

        try:
            client.callback.register(on_input_volume_meters)
            self._audio_stop.wait()
        except Exception as e:  # noqa: BLE001
            log.info("audio metering stopped: %s", e)
        finally:
            self._audio_ok = False
            try:
                client.disconnect()
            except Exception:  # noqa: BLE001
                pass

    def quiet_inputs(self, floor: float = 30.0) -> list[str]:
        """Audio sources that have been silent while others were not.

        The silence watchdog asks whether ANY sound is reaching the encoder, so
        a live game with a dead microphone passes it: the game is loud, and the
        stream is not silent. But nobody hears the streamer, which is its own
        failure and a more common one -- a muted mic, a device that vanished
        when a headset was unplugged, or a source pointed at the wrong one.

        -> the names that have carried nothing for `floor` seconds while some
        other input has. Empty when nothing is provably wrong, including when
        metering never came up.
        """
        if not self._audio_ok or not self._audio_by_input:
            return []
        now = time.monotonic()
        heard = [t for t in self._audio_by_input.values() if t]
        if not heard or now - max(heard) > 5.0:
            return []                  # everything is quiet: that is silence,
                                       # not one broken source
        out = []
        for name, when in self._audio_by_input.items():
            since = now - (when or self._audio_since)
            if since >= floor:
                out.append(name)
        return sorted(out)

    def silent_for(self) -> float | None:
        """Seconds since OBS last carried audible sound.

        -> None when metering never came up, which must NOT read as silence:
        an old OBS, a refused event connection or a missing library would
        otherwise raise a false alarm on every stream.
        """
        if not self._audio_ok:
            return None
        if self._audio_heard is None:
            # Connected, nothing heard yet. Measured from when listening began
            # rather than treated as unknown, so a stream that is silent from
            # its first second is still caught.
            return max(0.0, time.monotonic() - self._audio_since)
        return max(0.0, time.monotonic() - self._audio_heard)

    def health(self) -> dict:
        self.connect()
        s = self.ws.get_stream_status()
        out = {
            "active": bool(s.output_active),
            "congestion": getattr(s, "output_congestion", 0.0),
            "skipped": getattr(s, "output_skipped_frames", 0),
            "total": getattr(s, "output_total_frames", 0),
            "duration_ms": getattr(s, "output_duration", 0),
        }
        # Recording is reported alongside the stream so the LIVE watchdog and
        # the dashboard can notice a recording that died on its own — the
        # stream staying up says nothing about the local file still being
        # written.
        try:
            r = self.ws.get_record_status()
            out["recording"] = bool(r.output_active)
            out["rec_paused"] = bool(getattr(r, "output_paused", False))
            out["rec_bytes"] = int(getattr(r, "output_bytes", 0))
            out["rec_ms"] = int(getattr(r, "output_duration", 0))
        except Exception:  # noqa: BLE001 - an old OBS without the verb
            out["recording"] = False
        return out

    def set_scene(self, scene: str | None) -> None:
        if not scene:
            return
        self.connect()
        try:
            if scene not in self.scene_names():
                log.warning("scene %r does not exist in OBS — skipping switch", scene)
                return
            self.ws.set_current_program_scene(scene)
            log.info("scene -> %s", scene)
        except Exception as e:  # noqa: BLE001
            log.warning("scene switch failed: %s", e)

    # ---------------- scenes AutoStream owns ----------------
    #
    # The three screen savers -- starting, be-right-back, ending -- are ordinary
    # OBS scenes holding one looping media source each, and AutoStream builds
    # them rather than asking the user to. Everything here is idempotent: it
    # creates what is missing and updates what is there, so pointing a setting
    # at a different file just changes the file.

    MEDIA_KIND = "ffmpeg_source"
    BROWSER_KIND = "browser_source"

    # What a browser source renders at, before being scaled to the canvas.
    # Overlay tools lay their widgets out against a fixed design size and 1080p
    # is what nearly all of them use, so rendering there and scaling is safer
    # than rendering at whatever this particular OBS canvas happens to be.
    # Both are 16:9, so the scale is exact and nothing shifts.
    BROWSER_SIZE = (1920, 1080)

    def canvas(self) -> tuple[int, int]:
        """OBS's base resolution, for fitting a source to the whole frame."""
        try:
            self.connect()
            v = self.ws.get_video_settings()
            return int(v.base_width), int(v.base_height)
        except Exception:  # noqa: BLE001
            return 1920, 1080

    def ensure_browser_scene(self, scene: str, source: str, url: str) -> bool:
        """A scene showing `url` in a browser source. -> did it work.

        For screen savers that live in an overlay service rather than as a file
        on disk. The page keeps updating itself, which a downloaded copy of it
        would not.
        """
        if not scene or not source or not url:
            return False
        w, h = self.BROWSER_SIZE
        settings = {
            "url": str(url),
            "width": w, "height": h,
            # Start the page again each time the scene comes up, so the card
            # begins at the top rather than resuming mid-animation. The mirror
            # of restart_on_activate on a media source.
            "restart_when_active": True,
            # Shut the page down while it is off screen: an overlay left
            # running in the background burns CPU and keeps firing whatever
            # timers it has for the entire stream.
            "shutdown": True,
            # Audio through OBS's mixer rather than the desktop device, so a
            # card with music is captured predictably instead of depending on
            # whether desktop audio happens to be captured too.
            "reroute_audio": True,
        }
        return self._ensure_input(scene, source, self.BROWSER_KIND, settings)

    def ensure_media_scene(self, scene: str, source: str, path: str, *,
                           loop: bool = True) -> bool:
        """A scene containing `path` as a looping media source. -> did it work.

        Never raises: a screen saver that cannot be built must not stop a
        broadcast that is otherwise ready to go.
        """
        if not scene or not source or not path:
            return False
        settings = {
            "local_file": str(path),
            "is_local_file": True,
            "looping": bool(loop),
            # So the clip starts from the top each time the scene comes up
            # rather than resuming wherever it was left.
            "restart_on_activate": True,
            "close_when_inactive": False,
            "hw_decode": True,
            # OFF, deliberately: with it on OBS blanks the source when the file
            # ends, so a non-looping ending card would sit on black exactly
            # when somebody is reading it.
            "clear_on_media_end": False,
        }
        return self._ensure_input(scene, source, self.MEDIA_KIND, settings)

    def _ensure_input(self, scene: str, source: str, kind: str,
                      settings: dict) -> bool:
        """Create or update one source in one scene. Never raises.

        A screen saver that cannot be built must not stop a broadcast that is
        otherwise ready to go -- which is also why the SETTINGS are updated
        rather than the source recreated: an existing source may have been
        moved, resized or filtered by hand, and rebuilding it would silently
        throw that away every time the file changed.
        """
        try:
            self.connect()
            if scene not in self.scene_names():
                self.ws.create_scene(scene)
                log.info("created OBS scene %r", scene)
            names = {i["inputName"] for i in self.ws.get_input_list().inputs}
            if source in names:
                self.ws.set_input_settings(source, settings, True)
            else:
                self.ws.create_input(scene, source, kind, settings, True)
                log.info("added %r (%s) to %r", source, kind, scene)
                # Only on creation: see above.
                self._fit_to_canvas(scene, source)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("could not build the %r scene: %s", scene, e)
            return False

    def _fit_to_canvas(self, scene: str, source: str) -> None:
        """Scale the source to fill the frame without distorting it."""
        try:
            w, h = self.canvas()
            item = self.ws.get_scene_item_id(scene, source).scene_item_id
            self.ws.set_scene_item_transform(scene, item, {
                "boundsType": "OBS_BOUNDS_SCALE_INNER",
                "boundsWidth": w, "boundsHeight": h,
                "boundsAlignment": 0,        # centred
                "positionX": 0, "positionY": 0,
            })
        except Exception as e:  # noqa: BLE001
            log.info("could not fit %r to the canvas: %s", source, e)

    def remove_scene(self, name: str) -> None:
        try:
            self.connect()
            if name in self.scene_names():
                self.ws.remove_scene(name)
                log.info("removed OBS scene %r", name)
        except Exception as e:  # noqa: BLE001
            log.warning("could not remove scene %r: %s", name, e)

    def current_scene(self) -> str:
        try:
            self.connect()
            return str(self.ws.get_current_program_scene().current_program_scene_name)
        except Exception:  # noqa: BLE001
            return ""

    def set_overlay_text(self, text: str) -> None:
        src = self.cfg.obs.overlay_source
        if not src:
            return
        try:
            self.connect()
            self.ws.set_input_settings(src, {"text": text}, True)
        except Exception as e:  # noqa: BLE001
            log.warning("overlay text update failed (source %r): %s", src, e)

    def start(self, scene: str | None = None, overlay: str | None = None) -> None:
        # The one call worth waiting for: a session is beginning and OBS may
        # still be loading, so this is also the only path allowed to launch it.
        self.connect(wait=True)
        self.set_scene(scene or self.cfg.obs.default_scene or None)
        if overlay:
            self.set_overlay_text(overlay)
        if not self.ws.get_stream_status().output_active:
            self.ws.start_stream()
            log.info("OBS StartStream issued")
        else:
            log.info("OBS already streaming — reusing output")

    def stop(self) -> None:
        try:
            self.connect()
            if self.ws.get_stream_status().output_active:
                self.ws.stop_stream()
                log.info("OBS StopStream issued")
        except Exception as e:  # noqa: BLE001
            log.warning("OBS stop failed: %s", e)

    # ---------------- recording ----------------
    #
    # Local recording exists for clip production. What YouTube keeps is a
    # re-encode of the stream at roughly half its bitrate, and Studio hands
    # back a 720p transcode of that again, so anything cut from the VOD starts
    # two generations down. Recording writes the same canvas straight to disk.
    #
    # These mirror start()/stop() above: starting raises so a caller can react,
    # stopping swallows everything because a failure there must never be the
    # reason a session cannot end.

    def recording_active(self) -> bool:
        try:
            self.connect()
            return bool(self.ws.get_record_status().output_active)
        except Exception:  # noqa: BLE001
            return False

    def screenshot(self, width: int = 1280, height: int = 720,
                   scene: str | None = None) -> bytes | None:
        """The current program output as PNG bytes.

        Used to build a stream thumbnail from what is actually on screen. The
        scene name is resolved rather than assumed: GetSourceScreenshot needs a
        source, and the current program scene is the only one guaranteed to be
        rendering.
        """
        import base64

        try:
            self.connect()
            name = scene
            if not name:
                r = self.ws.get_current_program_scene()
                name = (getattr(r, "current_program_scene_name", None)
                        or getattr(r, "scene_name", None))
            if not name:
                return None
            shot = self.ws.get_source_screenshot(name, "png", width, height, -1)
            data = getattr(shot, "image_data", "") or ""
            if "," in data:
                data = data.split(",", 1)[1]
            return base64.b64decode(data) if data else None
        except Exception as e:  # noqa: BLE001
            log.warning("could not grab an OBS screenshot: %s", e)
            return None

    def record_directory(self) -> str | None:
        """Where OBS is currently set to write recordings."""
        try:
            self.connect()
            return self.ws.get_record_directory().record_directory or None
        except Exception:  # noqa: BLE001
            return None

    def set_record_directory(self, path: str) -> None:
        try:
            self.connect()
            os.makedirs(path, exist_ok=True)
            self.ws.set_record_directory(path)
            log.info("OBS record directory -> %s", path)
        except Exception as e:  # noqa: BLE001
            log.warning("could not set record directory: %s", e)

    def start_recording(self) -> None:
        self.connect()
        if self.ws.get_record_status().output_active:
            log.info("OBS already recording — reusing output")
            return
        self.ws.start_record()
        log.info("OBS StartRecord issued")

    def record_offset(self) -> float | None:
        """Seconds into the file OBS is writing. -> None when not recording.

        Asked of OBS rather than worked out from wall clocks. The recording may
        have started late, been paused, or been adopted from an output that was
        already running -- and a chat mark placed by arithmetic on
        session_start would be wrong by exactly that much, silently.
        """
        try:
            self.connect()
            r = self.ws.get_record_status()
            if not r.output_active:
                return None
            return max(0.0, float(getattr(r, "output_duration", 0)) / 1000.0)
        except Exception:  # noqa: BLE001
            return None

    def recording_paused(self) -> bool:
        try:
            self.connect()
            return bool(getattr(self.ws.get_record_status(), "output_paused", False))
        except Exception:  # noqa: BLE001
            return False

    def pause_recording(self) -> bool:
        """Stop writing frames WITHOUT closing the file. -> is it now paused.

        The recording equivalent of parking a broadcast on a card: the output
        stays open, so resuming continues the same file rather than starting a
        second one. Two files would have to be stitched before anything could
        be cut from the pair, and the clip cutter reads one file per session.
        """
        try:
            self.connect()
            r = self.ws.get_record_status()
            if not r.output_active:
                return False
            if getattr(r, "output_paused", False):
                return True
            self.ws.pause_record()
            log.info("OBS PauseRecord issued")
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("OBS pause recording failed: %s", e)
            return False

    def resume_recording(self) -> bool:
        """Write frames again, into the file already open. -> did it resume."""
        try:
            self.connect()
            r = self.ws.get_record_status()
            if not r.output_active or not getattr(r, "output_paused", False):
                return bool(r.output_active)
            self.ws.resume_record()
            log.info("OBS ResumeRecord issued")
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("OBS resume recording failed: %s", e)
            return False

    def stop_recording(self) -> str | None:
        """-> the file OBS actually wrote, or None.

        The returned outputPath is the only dependable way to learn the
        filename. Reconstructing it from the record directory plus OBS's
        filename format means reimplementing its token expansion and its
        collision suffixes, and being wrong there means a session's recording
        is simply lost track of.
        """
        try:
            self.connect()
            if not self.ws.get_record_status().output_active:
                return None
            path = getattr(self.ws.stop_record(), "output_path", None)
            log.info("OBS StopRecord issued -> %s", path)
            return path or None
        except Exception as e:  # noqa: BLE001
            log.warning("OBS stop recording failed: %s", e)
            return None
