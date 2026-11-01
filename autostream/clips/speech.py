"""What the player said, off the microphone track: speech-to-text (faster-whisper).

WHY THIS EXISTS
    The stream highlight cuts long stretches of a player who talks through the whole
    match, and the microphone's level can only say THAT they are talking -- so its
    cuts land mid-sentence, a word in, a word short. A transcript says where each
    sentence starts and ends, and its English says what the moment was. ChatGPT's
    review of the highlight put this first (2026-11-01): "the next challenge is
    determining which things he says are worth hearing".

    The player said yes to installing faster-whisper, pip's CUDA 12 libraries and
    the two large models (2026-11-01). All of it is optional: a machine without it,
    or without a model already on disk, gets None from here and the highlight cuts
    on the level as before. Nothing is ever downloaded from here -- gigabytes fetched
    behind a person's back are not a side effect anyone agreed to.

TWO MODELS, ONE LANGUAGE (measured 2026-11-01 on an RTX 5060 Ti, 45 reaction windows
of a Hindi-speaking player -- his own labels on the "small" model's output:
English usable 36 of 43, the Hindi script mostly wrong):
    TEXT_MODEL, large-v3-turbo, writes what was said: ~20x real time on short
    windows, 2.4 GB of graphics memory. It CANNOT translate -- asked for English it
    returns the original language.
    ENGLISH_MODEL, large-v3, translates: ~9x on windows, 3.4-5.3 GB. As the text
    model it would read only 5-6x (once 4x), at the 5x line a reader needs.
    Neither can be trusted to find the language by itself on a gamer's mic: turbo
    called this player's Hindi English on 42 of 45 windows, large-v3 named five
    other languages on 5. So the language is decided ONCE per recording, by
    large-v3's vote over its longest stretches of talk (`language`), and forced on
    both. A machine with only the "small" model uses it for both jobs.
    On the CPU no model writes Hindi at 5x (small ~3x, large-v3 ~1x), so the clip
    job transcribes only on a graphics card (`fast`).
"""
from __future__ import annotations

import logging
import os
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .tools import binary

log = logging.getLogger("autostream.clips.speech")

TEXT_MODEL = "large-v3-turbo"
ENGLISH_MODEL = "large-v3"
FALLBACK_MODEL = "small"   # multilingual: a player is not assumed to speak English
RATE = 16000
MIC_TRACK = 1              # reactions.MIC_TRACK
VOTE_SPANS = 8             # stretches of talk the language is voted on
VOTE_SECONDS = 30.0


@dataclass
class Line:
    start: float
    end: float
    text: str                                  # as said
    english: str = ""                          # the same span in English, when it is not English

    def as_dict(self) -> dict:
        return {"start": round(self.start, 2), "end": round(self.end, 2), "text": self.text,
                **({"english": self.english} if self.english else {})}


def _on_disk(name: str) -> bool:
    try:
        from faster_whisper.utils import download_model
        download_model(name, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001 - not installed, not downloaded: either way, no
        return False


def models() -> tuple[str, str] | None:
    """(text model, English model) on this machine, or None."""
    try:
        import faster_whisper  # noqa: F401
    except Exception:  # noqa: BLE001
        return None
    if _on_disk(TEXT_MODEL) and _on_disk(ENGLISH_MODEL):
        return TEXT_MODEL, ENGLISH_MODEL
    if _on_disk(FALLBACK_MODEL):
        return FALLBACK_MODEL, FALLBACK_MODEL
    return None


def available() -> bool:
    """faster-whisper installed and its models already on disk."""
    return models() is not None


_loaded: dict[str, object] = {}
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


def _gpu() -> bool:
    """Whether the card runs the models. A missing CUDA library shows only when the
    first audio is encoded, so a second of silence goes through the smallest one."""
    global _device
    if _device is None:
        _cuda_dlls()
        try:
            import ctranslate2
            from faster_whisper import WhisperModel
            if ctranslate2.get_cuda_device_count() < 1:
                raise RuntimeError("no CUDA device")
            pair = models()
            m = WhisperModel(pair[0], device="cuda", compute_type="float16", local_files_only=True)
            list(m.transcribe(np.zeros(RATE, dtype=np.float32), beam_size=1)[0])
            _loaded[pair[0]] = m
            _device = "cuda"
        except Exception as e:  # noqa: BLE001 - the CPU always works
            log.info("speech-to-text on the CPU: %s", e)
            _device = "cpu"
    return _device == "cuda"


def _model(name: str):
    if name not in _loaded:
        from faster_whisper import WhisperModel
        if _gpu():
            _loaded[name] = WhisperModel(name, device="cuda", compute_type="float16", local_files_only=True)
        else:
            _loaded[name] = WhisperModel(name, device="cpu", compute_type="int8", local_files_only=True,
                                         cpu_threads=os.cpu_count() or 0)
    return _loaded[name]


def fast() -> bool:
    """Whether it reads fast enough to go in front of people: on the card only."""
    return available() and _gpu()


def _audio(video: Path, track: int, start: float, duration: float) -> np.ndarray:
    # Decoded here rather than by faster-whisper, whose own decoder needs a newer
    # PyAV than this environment carries.
    p = subprocess.run([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-ss", f"{max(0.0, start):.3f}", "-t", f"{duration:.3f}", "-i", str(video),
                        "-map", f"0:a:{int(track)}", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return np.frombuffer(p.stdout or b"", dtype=np.float32)


def language(video: str | Path, spans: list[tuple[float, float]], *, track: int = MIC_TRACK) -> str | None:
    """The language the player speaks in this recording: the English model's vote over
    the VOTE_SPANS longest of `spans`. None when there is nothing to listen to."""
    pair = models()
    if pair is None:
        return None
    model = _model(pair[1])
    votes: Counter = Counter()
    for a, b in sorted(spans, key=lambda s: s[0] - s[1])[:VOTE_SPANS]:
        audio = _audio(Path(video), track, a, min(b - a, VOTE_SECONDS))
        if audio.size < RATE * 2:
            continue
        try:
            lang, p, _ = model.detect_language(audio)
            votes[lang] += p
        except Exception as e:  # noqa: BLE001 - a span that fails casts no vote
            log.info("no language from %.0f-%.0f s: %s", a, b, e)
    if not votes:
        return None
    lang = votes.most_common(1)[0][0]
    log.info("the player speaks %r here (votes: %s)", lang,
             ", ".join(f"{k} {v:.2f}" for k, v in votes.most_common(3)))
    return lang


def _run(model, audio: np.ndarray, *, lang: str | None, task: str):
    # Not conditioned on its own previous text: on a gamer's mic, half-heard words
    # fed back in made it loop on one phrase and run 4x slower.
    segs, _info = model.transcribe(audio, vad_filter=True, beam_size=1, language=lang, task=task,
                                   condition_on_previous_text=False)
    return [(float(s.start), float(s.end), (s.text or "").strip()) for s in segs]


def transcribe(video: str | Path, spans: list[tuple[float, float]], *, track: int = MIC_TRACK,
               lang: str | None = None, english: bool = True) -> list[Line] | None:
    """Every sentence said inside `spans` (recording seconds), in order, each with its
    English when the language is not English. None when there is no transcriber
    here; [] when nothing was said. `lang` is decided by `language` when not given."""
    pair = models()
    if pair is None:
        return None
    lang = lang or language(video, spans, track=track)
    text_model = _model(pair[0])
    eng_model = _model(pair[1]) if english and lang != "en" else None
    out: list[Line] = []
    for a, b in sorted(spans):
        audio = _audio(Path(video), track, a, b - a)
        if audio.size < RATE:
            continue
        try:
            said = _run(text_model, audio, lang=lang, task="transcribe")
            if eng_model is not None and said:
                eng = _run(eng_model, audio, lang=lang, task="translate")
                for s, e, t in said:
                    # Translation segments do not line up with the transcript's, so each
                    # sentence takes the English that overlaps it most.
                    over = [(min(e, e2) - max(s, s2), t2) for s2, e2, t2 in eng if min(e, e2) > max(s, s2)]
                    out.append(Line(a + s, a + e, t, max(over)[1] if over else ""))
            else:
                out += [Line(a + s, a + e, t) for s, e, t in said if t]
        except Exception as e:  # noqa: BLE001 - a span that fails is a span without words
            log.info("could not transcribe %.0f-%.0f s: %s", a, b, e)
    out = [ln for ln in out if ln.text]
    out.sort(key=lambda x: x.start)
    log.info("%s: %d line(s) in %r from %d span(s) with %s", Path(video).name, len(out), lang,
             len(spans), " + ".join(dict.fromkeys(pair)))
    return out
