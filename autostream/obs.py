"""obs-websocket 5 wrapper. Launches OBS if it isn't running."""
from __future__ import annotations

import logging
import os
import subprocess
import time

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


class Obs:
    def __init__(self, config):
        self.cfg = config
        self.ws = None

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

    def connect(self) -> None:
        """Connect, launching OBS if needed. Retries 3x with backoff."""
        if self.ws is not None:
            try:
                self.ws.get_version()
                return
            except Exception:  # noqa: BLE001
                self.ws = None

        last: Exception | None = None
        for attempt in range(3):
            try:
                self.ws = self._connect()
                v = self.ws.get_version()
                log.info("connected to OBS %s (websocket rpc %s)",
                         getattr(v, "obs_version", "?"), getattr(v, "rpc_version", "?"))
                return
            except Exception as e:  # noqa: BLE001
                last = e
                if not _obs_process_alive():
                    self._launch()
                log.info("OBS not ready (attempt %d/3): %s", attempt + 1, e)
                time.sleep(12)
        raise ObsUnavailable(f"could not reach obs-websocket: {last}")

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
        self.connect()
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
        self.connect()
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
