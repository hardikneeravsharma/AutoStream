"""What the player said, off the microphone track: speech-to-text (faster-whisper).

WHY THIS EXISTS
    The stream highlight cuts long stretches of a player who talks through the whole
    match, and the microphone's level can only say THAT they are talking -- so its
    cuts land mid-sentence, a word in, a word short. A transcript says where each
    sentence starts and ends. ChatGPT's review of the highlight put this first
    (2026-11-01): "the next challenge is determining which things he says are worth
    hearing", and that needs the words before it needs anything else.

    The player said yes to installing faster-whisper (2026-11-01). It is optional: a
    machine without it, or without a model already on disk, gets None from here and
    the highlight cuts on the level as before. Nothing is ever downloaded from here --
    a 460 MB model fetched behind a person's back is not a side effect anyone agreed to.

WHAT IS MEASURED (2026-11-01, the Bind recording of 2026-10-25)
    The "small" multilingual model on the CPU, int8, 12 threads: 1.2x to 4.7x real
    time over the stretches of a match -- under the 5x a reader needs to go in front
    of people, so the clip job uses it only on a graphics card (`fast`). On the card
    (float16, with pip's nvidia-cublas-cu12 and nvidia-cudnn-cu12): 11x. The player
    speaks Hindi (detected at 0.73); the round-10 rage reads "साले इतार! बापास
    आजा!" at 715.2-727.3 s, where the mic's level put the end at 719.6.
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .tools import binary

log = logging.getLogger("autostream.clips.speech")

MODEL = "small"            # multilingual: a player is not assumed to speak English
RATE = 16000
MIC_TRACK = 1              # reactions.MIC_TRACK


@dataclass
class Line:
    start: float
    end: float
    text: str

    def as_dict(self) -> dict:
        return {"start": round(self.start, 2), "end": round(self.end, 2), "text": self.text}


def available() -> bool:
    """faster-whisper installed and MODEL already on disk."""
    try:
        from faster_whisper import WhisperModel  # noqa: F401
        from faster_whisper.utils import download_model
        download_model(MODEL, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001 - any reason at all means no transcript
        return False


_model = None
_device: str | None = None


def _cuda_dlls() -> None:
    """Put pip's CUDA libraries (nvidia-cublas-cu12, nvidia-cudnn-cu12) where Windows
    looks for DLLs. They install into site-packages/nvidia/*/bin, which is on no
    search path, and ctranslate2 loads cuBLAS by name."""
    if os.name != "nt":
        return
    try:
        import nvidia
    except ImportError:
        return
    for root in getattr(nvidia, "__path__", []):
        for bin_dir in Path(root).glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            except OSError:
                pass


def _load():
    """The model on the graphics card when it can run there, else the CPU.

    The card needs CUDA 12's cuBLAS and cuDNN beside ctranslate2, and a missing
    library only shows when the first audio is encoded -- so a second of silence is
    run through it to find out."""
    global _model, _device
    if _model is None:
        from faster_whisper import WhisperModel
        _cuda_dlls()
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() < 1:
                raise RuntimeError("no CUDA device")
            m = WhisperModel(MODEL, device="cuda", compute_type="float16", local_files_only=True)
            list(m.transcribe(np.zeros(RATE, dtype=np.float32), beam_size=1)[0])
            _model, _device = m, "cuda"
        except Exception as e:  # noqa: BLE001 - the CPU always works
            log.info("speech-to-text on the CPU: %s", e)
            _model = WhisperModel(MODEL, device="cpu", compute_type="int8", local_files_only=True,
                                  cpu_threads=os.cpu_count() or 0)
            _device = "cpu"
    return _model


def fast() -> bool:
    """Whether it reads fast enough to go in front of people: on the card. On this
    machine's CPU it read 1.2x-4.7x real time (2026-11-01), under the 5x a reader
    needs (CLAUDE.md), so a CPU-only machine does not transcribe in a clip job."""
    if not available():
        return False
    _load()
    return _device == "cuda"


def _audio(video: Path, track: int, start: float, duration: float) -> np.ndarray:
    # Decoded here rather than by faster-whisper, whose own decoder needs a newer
    # PyAV than this environment carries.
    p = subprocess.run([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-ss", f"{max(0.0, start):.3f}", "-t", f"{duration:.3f}", "-i", str(video),
                        "-map", f"0:a:{int(track)}", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return np.frombuffer(p.stdout or b"", dtype=np.float32)


def transcribe(video: str | Path, spans: list[tuple[float, float]], *, track: int = MIC_TRACK
               ) -> list[Line] | None:
    """Every sentence said inside `spans` (recording seconds), in order. None when
    there is no transcriber here; [] when nothing was said."""
    if not available():
        return None
    model = _load()
    out: list[Line] = []
    for a, b in sorted(spans):
        audio = _audio(Path(video), track, a, b - a)
        if audio.size < RATE:
            continue
        try:
            # Not conditioned on its own previous text: on a gamer's mic, half-heard
            # words fed back in made it loop on one phrase and run 4x slower.
            segs, _info = model.transcribe(audio, vad_filter=True, beam_size=1,
                                           condition_on_previous_text=False)
            for s in segs:
                text = (s.text or "").strip()
                if text:
                    out.append(Line(a + float(s.start), a + float(s.end), text))
        except Exception as e:  # noqa: BLE001 - a span that fails is a span without words
            log.info("could not transcribe %.0f-%.0f s: %s", a, b, e)
    out.sort(key=lambda x: x.start)
    log.info("%s: %d line(s) transcribed in %d span(s)", Path(video).name, len(out), len(spans))
    return out
