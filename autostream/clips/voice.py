r"""Spoken hooks over the front of a clip, from Kokoro-82M on the CPU.

WHY SAY ANYTHING AT ALL
    A clip has about three seconds to explain why it is worth watching, and
    burning text on the picture spends screen space to do it -- see
    clips/overlay.py, which already does that as far as it sensibly can. A
    voice spends time instead, and the clip has time it was not using: the
    run-up before the first kill is dead air by definition, and for
    Counter-Strike there is now three seconds of it on purpose (see
    profiles.Profile.pre_roll_min). The hook lands there, over footage where
    nothing has happened yet, and is finished before the kill is.

WHY KOKORO AND NOT PIPER
    Piper is faster -- about 0.03x real time against Kokoro's roughly 1x on
    this machine. It is also noticeably flatter. A clip needs a few seconds of
    speech, so a second of synthesis either way is invisible, and the thing
    that is not invisible is the delivery. Kokoro is Apache 2.0, 82M
    parameters, 54 voices, and runs on the CPU.

WHY THE ONNX BUILD AND NOT THE PYTORCH PACKAGE
    The `kokoro` package on PyPI pulls torch, which is a multi-gigabyte install
    for an app that ships as a 54 MB zip. `kokoro-onnx` needs onnxruntime and
    the model as a file, which is a 177 MB download the user opts into once.
    So this module is written to be ABSENT: nothing here is imported until a
    hook is actually asked for, and `available()` answers honestly before
    anything tries.

WHAT IT SAYS, AND WHAT IT DOES NOT
    A HOOK IS NOT A LABEL READ ALOUD. The first version said "Anubis. One
    versus two." over a clutch, which is a caption with a full stop in it --
    it states what the clip contains to someone who is about to watch it
    contain that. It gives nobody a reason to stay.

    What works is the tension, in the voice a person would actually use:

        "they had the numbers. I had the timing."
        "they thought the round was free."
        "couldn't see a thing. didn't need to."

    Those are lifted in style from the channel's own shorts titles, and they
    share a shape: a setup and a turn, present tense, no statistics. The label
    chooses the POOL; the clip chooses which line out of it, deterministically,
    so a rerun says the same thing and two clutches in one session do not.

    The map is deliberately not spoken. It was, and besides being the dullest
    possible opening it is also where the pronunciation went wrong -- espeak
    reads "Anubis" as AN-oo-bis, stress on the first syllable.

    A clip with nothing to say gets SILENCE rather than filler. "Check this
    out" over an ordinary double kill is worse than nothing, and the app
    already has a rotating flavour line for stream titles (config `title.hooks`)
    which is a different thing entirely -- that one sells a stream, this one
    makes someone stay for a moment they have not seen yet.
"""
from __future__ import annotations

import logging
import re
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .. import paths

log = logging.getLogger("autostream.clips.voice")

# Where the model lives. NOT under paths.ROOT, for the same reason clips and
# history are not: a frozen build's ROOT is deleted wholesale on every rebuild,
# and re-downloading 177 MB because someone rebuilt the app is not acceptable.
MODEL_DIR = paths.MODELS_DIR / "kokoro"

# The two files kokoro-onnx needs, and where they come from. fp16 rather than
# the full-precision 325 MB build: half the download for speech nobody can tell
# apart. int8 (92 MB) exists too and is audibly rougher, which is the one thing
# Kokoro was chosen over Piper to avoid.
RELEASE = ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
           "model-files-v1.0/")
FILES = {
    "kokoro-v1.0.fp16.onnx": 177_464_787,
    "voices-v1.0.bin": 28_214_398,
}

# A male American voice, because these are first-person hooks on a gaming
# channel run by one. Overridable per job (`clips.voice_name`) because a voice
# is taste, unlike every other number in this package -- `catalogue()` lists
# what is available and `autostream voice --sample` renders one wav each.
VOICE = "am_michael"
LANG = "en-us"
SPEED = 1.0

# Kokoro names every voice <accent><gender>_<name>, so the catalogue does not
# have to be written down and cannot drift from what the model actually holds.
# Only English voices are listed: LANG is en-us, and handing an American
# phonemisation to a Japanese voice produces an accent nobody asked for.
GROUPS = {"af": "American female", "am": "American male",
          "bf": "British female", "bm": "British male"}

# Where the hook sits in the clip, and how loud. The delay keeps it off the
# very first frame -- a voice that starts before the picture has settled sounds
# like a mistake.
# What a voice says when it is being auditioned. One sentence, with a comma
# and a full stop in it, because that is where voices differ most audibly.
SAMPLE_LINE = "They had the numbers. I had the timing."

LEAD_IN = 0.3
VOICE_GAIN = 1.7          # the model peaks around 0.65, gameplay is mastered hot
DUCK_THRESHOLD = 0.06     # game audio dips under the voice, then comes back

_MODEL = None             # loaded once; ~1s each time


# --------------------------------------------------------------- the script

# One pool per situation, strongest first -- the same ordering idea as
# rounds.RANK, and for the same reason: a round that is an ace AND a 1v3 has one
# thing worth saying, not three.
#
# `{n}` and `{s}` are filled from the label itself and spelled out as words,
# because a model reading "1v3" says "one vee three".
#
# Every line here was checked through espeak's phonemiser before it shipped.
# That is not fussiness: the model says what the phonemiser hands it, and a
# single mispronounced word in a three-second hook is the whole hook.
HOOKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"^ACE$", (
        "the whole team, one round.",
        "nobody was getting out of that one.",
        "they queued up one by one.",
        "all five of them. still shaking.",
    )),
    (r"^CLUTCH 1v(?P<n>\d+)$", (
        "they had the numbers. I had the timing.",
        "{n} of them left, and they still lost it.",
        "they thought the round was free.",
        "last one standing, and somehow that was enough.",
        "outnumbered {n} to one. not outplayed.",
    )),
    (r"^ALMOST 1v(?P<n>\d+)$", (
        "one more bullet and this is a highlight.",
        "{n} of them, and I nearly took the whole round back.",
        "that was so close it still hurts.",
        "almost dragged this one out of nothing.",
    )),
    (r"^(?P<n>\d+) KILLS$", (
        "{n} of them, one round, no reload.",
        "they kept walking into the same spot.",
        "{n} down before they worked out where I was.",
    )),
    (r"^(?P<n>\d+)K IN (?P<s>\d+)s$", (
        "{n} of them in about {s} seconds.",
        "blink and you miss all {n}.",
        "no gap between any of those.",
    )),
    (r"^NO SCOPE$", (
        "no time to scope. no need either.",
        "didn't zoom in. still got him.",
    )),
    (r"^KNIFE KILL$", (
        "brought a knife to a gunfight. won it.",
        "close enough for the knife, apparently.",
    )),
    (r"^ZEUS$", (
        "taxed him with the zeus.",
        "the zeus. absolutely disrespectful.",
    )),
    (r"^THROUGH SMOKE$", (
        "couldn't see a thing. didn't need to.",
        "they thought the smoke was cover.",
        "shot into the smoke on a guess. it landed.",
    )),
    (r"^WALLBANG$", (
        "the wall was not helping them.",
        "cover only works if they can't shoot through it.",
    )),
    (r"^NADE KILL$", (
        "didn't even need the gun for that one.",
        "the grenade did all the work.",
    )),
    (r"^BLIND KILL$", (
        "completely flashed, and still hit it.",
        "couldn't see them. hit them anyway.",
    )),
    (r"^LAST ALIVE$", (
        "last one standing. no pressure.",
        "everyone's gone. it's on me now.",
    )),
    (r"^STREAK BREAKER$", (
        "this is where it finally turned.",
        "losing all game. not this round.",
        "needed exactly one round. this one.",
    )),
    (r"^MATCH POINT$", (
        "match point. no second chances.",
        "one round to end the whole thing.",
    )),
    (r"^PISTOL ROUND$", (
        "pistol round, and they were not ready.",
        "first round of the half. already ahead.",
    )),
    (r"^CHAOS$", (
        "everything happened at once here.",
        "that whole round lasted about twenty seconds.",
    )),
    (r"^SURVIVED THE LOSS$", (
        "won my fight. lost the round.",
        "lost the round and still walked out of it.",
    )),
)

# What a clip with no labels at all gets -- Delta Force and Valorant come
# through here, where a burst of kills is the whole story. One kill says
# nothing worth saying out loud.
# DEEP ENOUGH TO GET THROUGH A SESSION. Two lines per count was not: one
# Valorant recording produced seven two-kill clips, `avoid` ran out after the
# second and the same sentence opened four of them. A pool has to hold more
# lines than a session has clips of that size.
BURSTS: dict[int, tuple[str, ...]] = {
    2: ("two for the price of one.",
        "they lined up. rude not to.",
        "second one never saw it coming.",
        "one, then the other. no gap.",
        "both of them, same corner.",
        "they pushed together. that was the mistake.",
        "double, and I still had bullets left.",
        "two down before they knew where I was."),
    3: ("triple, and the round was over.",
        "three problems, one magazine.",
        "they queued up for that one.",
        "three of them. no reload.",
        "one angle, three kills.",
        "kept clicking. kept working."),
    4: ("four of them, one push.",
        "they arrived one at a time. bad plan.",
        "four down and I'm still standing.",
        "that is most of a team."),
    5: ("five of them. nobody left.",
        "the entire squad, one angle.",
        "all five. still shaking.",
        "nobody got out of that."),
}

WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven",
         "eight", "nine", "ten")


def spell(n: int) -> str:
    """1 -> "one". A model reading "1v3" says "one vee three"."""
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def _pool(plan) -> tuple[str, ...]:
    """Every line that fits this clip, or () if there is nothing to say."""
    labels = [str(x) for x in (getattr(plan, "labels", None) or [])]
    for pattern, lines in HOOKS:
        for label in labels:
            # Case-insensitive, NOT upper()-then-match: the labels are
            # uppercase apart from the lowercase letters inside "1v3" and
            # "3K IN 5s", and upper()ing them made every pattern with a `v` or
            # a trailing `s` in it silently fall through to the kill count --
            # so a 1v3 clutch announced itself as "Triple kill."
            m = re.match(pattern, label.strip(), re.IGNORECASE)
            if m:
                got = {k: spell(int(v)) for k, v in m.groupdict().items()}
                return tuple(line.format(**got) for line in lines)
    return BURSTS.get(int(getattr(plan, "kills", 0) or 0), ())


def line_for(plan, *, avoid: Sequence[str] = ()) -> str:
    """What to say over this clip. Empty means say nothing.

    Deterministic: the same clip picks the same line every run, so re-cutting a
    session does not quietly reword it. Which one is chosen comes from WHERE the
    clip sits in the recording, which is what makes two clutches in one session
    say different things without any state being threaded through.

    `avoid` is what has already been said in this session, and wins over the
    deterministic choice -- hearing the same sentence twice in one reel is worse
    than hearing the second-best line.
    """
    pool = _pool(plan)
    if not pool:
        return ""
    said = set(avoid or ())
    start = int(abs(getattr(plan, "start", 0.0))) % len(pool)
    # Capitalised BEFORE the avoid check, not after. Comparing raw pool lines
    # against already-spoken capitalised ones matched nothing, so `avoid` did
    # nothing at all and three clutches in one session opened with the same
    # sentence.
    order = [_speakable(pool[(start + i) % len(pool)]) for i in range(len(pool))]
    return next((x for x in order if x not in said), order[0])


def _speakable(line: str) -> str:
    """Capitalise EVERY sentence, not just the first.

    Kokoro reads case and punctuation as prosody, so a lowercase sentence after
    a full stop is delivered as a continuation of the one before it -- which is
    precisely the flat, run-on delivery these two-clause hooks exist to avoid.
    """
    out, capitalise = [], True
    for ch in line:
        out.append(ch.upper() if capitalise and ch.isalpha() else ch)
        if ch.isalnum():
            capitalise = False
        elif ch in ".!?":
            capitalise = True
    return "".join(out)


# ------------------------------------------------------------- the model

def model_file() -> Path | None:
    """The .onnx to load, whichever variant is on disk.

    Matched by glob rather than by the exact name `download()` fetches, so
    someone who grabbed the full-precision or int8 build by hand is not told
    the model is missing while it sits there.
    """
    for path in sorted(MODEL_DIR.glob("kokoro-*.onnx")):
        return path
    return None


def voices_file() -> Path | None:
    for path in sorted(MODEL_DIR.glob("voices-*.bin")):
        return path
    return None


def missing() -> list[str]:
    """What is not here yet. Empty means ready to speak."""
    gaps = []
    try:
        import kokoro_onnx                                  # noqa: F401
    except ImportError:
        gaps.append("the kokoro-onnx package (pip install kokoro-onnx)")
    if model_file() is None:
        gaps.append("the model file kokoro-v1.0.fp16.onnx")
    if voices_file() is None:
        gaps.append("the voice file voices-v1.0.bin")
    return gaps


def available() -> bool:
    return not missing()


def why_not() -> str:
    gaps = missing()
    if not gaps:
        return ""
    return ("Spoken hooks need Kokoro, which is an optional download: "
            + ", ".join(gaps) + f". The model files go in {MODEL_DIR}.")


def download(progress=None) -> list[Path]:
    """Fetch the model. Never called on its own -- the user asks for it.

    Written to a .part file and renamed, because a half-downloaded 177 MB model
    that looks complete fails later with an onnxruntime error nobody can read.
    """
    import urllib.request

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    got = []
    for name, size in FILES.items():
        target = MODEL_DIR / name
        if target.is_file() and target.stat().st_size == size:
            got.append(target)
            continue
        part = target.with_suffix(target.suffix + ".part")
        log.info("downloading %s (%.0f MB)", name, size / 1e6)
        with urllib.request.urlopen(RELEASE + name) as src, \
                part.open("wb") as dst:
            done = 0
            while chunk := src.read(1 << 20):
                dst.write(chunk)
                done += len(chunk)
                if progress:
                    progress(name, done, size)
        part.replace(target)
        got.append(target)
    return got


def model():
    """The loaded Kokoro, cached. Raises RuntimeError if it cannot be."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    gaps = missing()
    if gaps:
        raise RuntimeError(why_not())
    from kokoro_onnx import Kokoro

    # phonemizer logs "words count mismatch" every time espeak merges two words
    # into one token -- "of the" -> ʌvðə, "at once" -> ɐtwˈʌns, "out of" ->
    # ˌaʊɾəv. That is ordinary English liaison and nothing is dropped: checked
    # across all 55 shipped lines, every word is present in the phonemes. Left
    # at WARNING it puts an alarming line in the app log for most clips.
    logging.getLogger("phonemizer").setLevel(logging.ERROR)

    onnx, voices = model_file(), voices_file()
    _MODEL = Kokoro(str(onnx), str(voices))
    log.info("Kokoro loaded from %s", onnx.name)
    return _MODEL


def voices() -> list[str]:
    try:
        return sorted(model().get_voices())
    except Exception as e:  # noqa: BLE001
        log.info("could not list voices: %s", e)
        return [VOICE]


def catalogue() -> dict[str, list[str]]:
    """Every English voice the model has, grouped by accent and gender.

    Read off the model rather than hardcoded, so it says what is actually
    installed instead of what was true when this was written.
    """
    out: dict[str, list[str]] = {}
    for name in voices():
        group = GROUPS.get(name[:2])
        if group:
            out.setdefault(group, []).append(name)
    return out


def samples(out_dir: Path, line: str = "", *,
            names: Sequence[str] = ()) -> list[Path]:
    """One wav per voice, all saying the same line. For choosing one by ear.

    A voice is the one thing here that cannot be decided by measurement, so
    the honest answer to "which voice" is to render them and listen.
    """
    line = line or SAMPLE_LINE
    picked = list(names) or [n for group in catalogue().values() for n in group]
    made = []
    for name in picked:
        try:
            made.append(say(line, Path(out_dir) / f"{name}.wav",
                            voice=name).path)
        except Exception as e:  # noqa: BLE001
            log.warning("could not render %s: %s", name, e)
    return made


@dataclass
class Speech:
    path: Path
    duration: float


def say(text: str, out: Path, *, voice: str = VOICE, speed: float = SPEED,
        lang: str = LANG) -> Speech:
    """Synthesise `text` to a 16-bit wav. -> where it went and how long it is.

    Written with the `wave` module rather than soundfile: one fewer optional
    dependency for a file format that is a header and some integers.
    """
    import numpy as np

    text = " ".join(str(text or "").split())[:300]
    if not text:
        raise ValueError("nothing to say")
    samples, rate = model().create(text, voice=voice, speed=float(speed),
                                  lang=lang)
    pcm = np.clip(np.asarray(samples, dtype="float32"), -1.0, 1.0)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes((pcm * 32767).astype("<i2").tobytes())
    return Speech(path=out, duration=len(pcm) / float(rate))


# ------------------------------------------------------------- mixing in

def mix(src: Path, out: Path, speech: Path, *, at: float = LEAD_IN,
        gain: float = VOICE_GAIN, encoder: str = "auto",
        cq: int = 20) -> Path:      # noqa: ARG001 - encoder/cq kept for callers
    """Lay `speech` over the front of `src`, ducking the game under it.

    Ducked with sidechaincompress rather than a flat volume cut, so the game
    comes back the moment the voice stops instead of the whole clip sounding
    quiet. Both inputs are forced to one sample rate and layout first --
    sidechaincompress will not mix a mono 24 kHz voice with 48 kHz stereo
    gameplay, and the failure is an ffmpeg error rather than a bad mix.

    ONE AUDIO TRACK COMES OUT. A master keeps every track it was cut with (game,
    mic, chat) so it can be remixed in an editor; this flattens them, which is
    why it is applied to the vertical delivery clip and not to the master.
    """
    from .tools import ffmpeg, media_info

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    delay = max(0, int(at * 1000))
    fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"

    if media_info(src)["audio_tracks"]:
        graph = (
            f"[1:a]{fmt},adelay={delay}|{delay},volume={gain:.2f},"
            f"asplit=2[v1][v2];"
            # apad, and it is not optional. sidechaincompress ends with its
            # SHORTER input, so an unpadded two-second hook cut a fifteen-second
            # clip down to two seconds of video -- and did it silently, because
            # the file was perfectly valid.
            f"[v1]apad[sc];"
            f"[0:a]{fmt}[game];"
            f"[game][sc]sidechaincompress=threshold={DUCK_THRESHOLD}:ratio=8"
            f":attack=15:release=350[ducked];"
            f"[ducked][v2]amix=inputs=2:duration=first:normalize=0[out]"
        )
    else:
        # A clip with no audio at all: the voice IS the audio track.
        graph = f"[1:a]{fmt},adelay={delay}|{delay},volume={gain:.2f}[out]"

    # THE VIDEO IS COPIED, NOT RE-ENCODED. Nothing in the graph above touches
    # it, and re-encoding here cost every narrated clip a second full video
    # pass -- on top of the one the caption already paid for.
    ffmpeg("-i", str(src), "-i", str(speech), "-filter_complex", graph,
           "-map", "0:v:0", "-map", "[out]",
           "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", "-y", str(out))
    return out


def lay_over(clip: Path, speech: "Speech") -> bool:
    """Mix an already-synthesised hook into a clip, in place. -> did it work.

    The half of `narrate` that the clip pipeline uses on its own, because the
    line has to be spoken before the subtitle can be drawn -- see
    jobs.ClipJob._speak.
    """
    clip = Path(clip)
    staged = clip.with_suffix(".narrating.mp4")
    try:
        mix(clip, staged, speech.path)
        clip.unlink(missing_ok=True)
        staged.replace(clip)
        return True
    except Exception as e:  # noqa: BLE001 - a hook is not worth losing a clip
        log.warning("could not lay the hook over %s: %s", clip.name, e)
        return False
    finally:
        staged.unlink(missing_ok=True)


def narrate(clip: Path, plan, *, out: Path | None = None, voice: str = VOICE,
            speed: float = SPEED, avoid: Sequence[str] = (), text: str = "",
            encoder: str = "auto") -> str:
    """Speak this clip's hook over it, in place. -> what was said, or "".

    Returns the line rather than the path because the caller records it in the
    manifest, and because "" is the ordinary answer for a clip with nothing to
    say. Never raises: a missing model or a failed mix costs the narration, not
    the clip.
    """
    clip = Path(clip)
    said = text or line_for(plan, avoid=avoid)
    if not said:
        return ""
    if not available():
        log.info("no spoken hook: %s", why_not())
        return ""
    tmp = Path(tempfile.mkdtemp(prefix="hook_"))
    try:
        speech = say(said, tmp / "hook.wav", voice=voice, speed=speed)
        target = Path(out) if out else clip
        # Encoded NEXT TO the target, not in the temp directory: os.replace
        # cannot move across volumes, and a video library on another drive is
        # the ordinary case rather than an exotic one.
        staged = target.with_suffix(".narrating.mp4")
        mix(clip, staged, speech.path, encoder=encoder)
        if target == clip:
            clip.unlink(missing_ok=True)
        staged.replace(target)
        log.info("%s: said %r (%.1fs)", target.name, said, speech.duration)
        return said
    except Exception as e:  # noqa: BLE001 - a hook is not worth losing a clip over
        log.warning("could not narrate %s: %s", clip.name, e)
        return ""
    finally:
        staged = (Path(out) if out else clip).with_suffix(".narrating.mp4")
        staged.unlink(missing_ok=True)
        for leftover in tmp.glob("*"):
            leftover.unlink(missing_ok=True)
        try:
            tmp.rmdir()
        except OSError:
            pass
