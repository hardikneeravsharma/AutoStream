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

    def _launch(self) -> None:
        path = self.cfg.obs.path
        if not path or not os.path.exists(path):
            log.error("OBS executable not found at %s", path)
            return
        cwd = os.path.dirname(path)   # OBS dies without this — it can't find locale files
        log.info("launching OBS from %s", path)
        try:
            subprocess.Popen(
                [path, "--disable-shutdown-check", "--minimize-to-tray"],
                cwd=cwd,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            )
        except OSError as e:
            log.error("failed to launch OBS: %s", e)

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
        return {
            "active": bool(s.output_active),
            "congestion": getattr(s, "output_congestion", 0.0),
            "skipped": getattr(s, "output_skipped_frames", 0),
            "total": getattr(s, "output_total_frames", 0),
            "duration_ms": getattr(s, "output_duration", 0),
        }

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
