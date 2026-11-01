"""Heavy optional extras, downloaded when a feature needs them -- and only once the
user has said yes to the size.

WHY THIS EXISTS
    The player (2026-11-02): "for heavy models, whenever a user tries to use their
    feature and they are not present, ask them and download the resources for them
    -- download the library". Speech-to-text was the case in hand: faster-whisper,
    its CUDA libraries and its two models are about six gigabytes, far too much to
    put in an installer everybody downloads, and a packaged build has no pip -- so
    in the installed app the captions feature simply said it was not installed.

HOW
    A PACK is a pinned set of wheels plus the models they load. Installing one:
      1. each wheel's file is found on PyPI's JSON API for exactly the version
         pinned here, for this Python and Windows (the versions the feature was
         measured with -- an unpinned install is a different program),
      2. downloaded into the pack's folder, its sha256 checked against PyPI's,
      3. unzipped into the pack's own site folder (a wheel is a zip: no pip),
      4. then the models are fetched by the library itself, into its usual cache.
    `activate` puts that site folder at the END of sys.path, so anything the app
    already carries wins and only what it lacks comes from the pack.

    Nothing here runs on its own initiative: `Installer.start` is called only from
    the page, after the person has seen what it costs and pressed Download.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

log = logging.getLogger("autostream.packs")

PYPI = "https://pypi.org/pypi/{name}/{version}/json"
CHUNK = 1 << 20
# This app's CPython, as wheels name it: cp312.
PY = f"cp{sys.version_info.major}{sys.version_info.minor}"


@dataclass(frozen=True)
class Model:
    name: str                  # what the library calls it
    repo: str                  # where it is fetched from
    size: int                  # bytes, for the question asked before downloading


@dataclass(frozen=True)
class Pack:
    key: str
    label: str
    what: str                  # what it is for, in the page's words
    wheels: tuple[tuple[str, str], ...]
    models: tuple[Model, ...] = ()
    module: str = ""           # imported to prove the pack works
    needs: str = ""            # "nvidia": an NVIDIA graphics card, or it is no use
    extra: dict = field(default_factory=dict)


# Speech-to-text: the versions measured on the player's RTX 5060 Ti (v2.8.1).
# numpy is left out on purpose -- the app carries its own, and a second copy of a
# compiled library cannot be loaded beside the first.
SPEECH = Pack(
    key="speech",
    label="Speech-to-text",
    what="writes down what you and your team say, for captions and for cutting on sentences",
    wheels=(("faster-whisper", "1.2.1"), ("ctranslate2", "4.8.4"), ("av", "19.0.2"),
            ("onnxruntime", "1.29.0"), ("tokenizers", "0.23.3"), ("huggingface-hub", "2.4.0"),
            ("hf-xet", "1.8.0"), ("httpx2", "2.16.0"), ("httpcore2", "2.16.0"), ("h11", "0.16.0"),
            ("anyio", "4.15.1"), ("idna", "3.18"), ("truststore", "0.10.5"), ("filelock", "4.2.6"),
            ("fsspec", "2026.9.0"), ("packaging", "26.3"), ("pyyaml", "6.0.3"), ("tqdm", "4.70.0"),
            ("colorama", "0.4.6"), ("click", "8.5.0"), ("typing-extensions", "4.16.0"),
            ("flatbuffers", "25.12.19"), ("protobuf", "7.35.1"),
            ("nvidia-cublas-cu12", "12.9.2.10"), ("nvidia-cudnn-cu12", "9.27.0.42"),
            ("nvidia-cuda-nvrtc-cu12", "12.9.86")),
    models=(Model("large-v3-turbo", "mobiuslabsgmbh/faster-whisper-large-v3-turbo", 1_620_000_000),
            Model("large-v3", "Systran/faster-whisper-large-v3", 3_090_000_000)),
    module="faster_whisper",
    needs="nvidia",
)

PACKS = {p.key: p for p in (SPEECH,)}


def folder(key: str) -> Path:
    return paths.PACKS_DIR / key


def site(key: str) -> Path:
    return folder(key) / "site"


def _marker(key: str) -> Path:
    return folder(key) / "installed.json"


def installed(key: str) -> bool:
    """Whether every pinned wheel of the pack is unpacked (the models are the
    library's own business: it says whether they are on disk)."""
    pack = PACKS.get(key)
    try:
        got = json.loads(_marker(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return pack is not None and got.get("wheels") == [list(w) for w in pack.wheels]


def activate(key: str) -> bool:
    """Make an installed pack importable: its site folder at the end of sys.path,
    so whatever the app carries itself is used first. -> whether it is installed."""
    if not installed(key):
        return False
    s = str(site(key))
    if s not in sys.path:
        sys.path.append(s)
        import importlib
        importlib.invalidate_caches()
    return True


def nvidia() -> bool:
    """An NVIDIA card with its driver: the driver puts nvidia-smi on the PATH."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return False
    try:
        p = subprocess.run([exe, "-L"], capture_output=True, text=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0 and "GPU" in (p.stdout or "")


def why_not(pack: Pack) -> str:
    """Why this machine cannot use the pack at all, or ""."""
    if os.name != "nt":
        return f"{pack.label} is downloaded on Windows only, for now."
    if PY != "cp312":
        return f"{pack.label} needs the app's own Python 3.12."
    if pack.needs == "nvidia" and not nvidia():
        return (f"{pack.label} needs an NVIDIA graphics card: on the processor it is too slow to "
                f"wait for, so it is not offered here.")
    return ""


def _model_on_disk(m: Model) -> bool:
    try:
        from faster_whisper.utils import download_model
        download_model(m.name, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001 - not installed or not downloaded: either way, no
        return False


def models_missing(pack: Pack) -> list[Model]:
    if not pack.models:
        return []
    activate(pack.key)
    return [m for m in pack.models if not _model_on_disk(m)]


# ---------------------------------------------------------------- PyPI

def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "AutoStream"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _rank(filename: str) -> int | None:
    """How well a wheel fits this app, lower is better; None when it cannot load.
    A wheel's name ends python-abi-platform: cp312-cp312-win_amd64 is built for
    exactly this Python; cpXY-abi3 for any CPython from X.Y on (tokenizers is
    cp310-abi3); none-any is pure Python."""
    parts = filename[:-4].split("-")
    if len(parts) < 5:
        return None
    py, abi, plat = parts[-3], parts[-2], parts[-1]
    pys = py.split(".")
    if plat == "win_amd64":
        if abi == PY and PY in pys:
            return 0
        if abi == "abi3":
            try:
                if any(p.startswith("cp3") and int(p[3:]) <= int(PY[3:]) for p in pys):
                    return 1
            except ValueError:
                return None
        if abi == "none" and ("py3" in pys or PY in pys):
            return 2
        return None
    if plat == "any" and abi == "none" and ("py3" in pys or "py2" in pys and "py3" in pys):
        return 3
    return None


def pick(files: list[dict]) -> dict | None:
    """The wheel this app can load from a release's files, the best fit first."""
    ranked = [(r, f) for f in files if str(f.get("filename", "")).endswith(".whl")
              for r in [_rank(f["filename"])] if r is not None]
    return min(ranked, key=lambda x: x[0])[1] if ranked else None


def resolve(pack: Pack, fetch=None) -> list[dict]:
    """Each pinned wheel's file: {name, version, url, filename, size, sha256}."""
    fetch = fetch or _get_json
    out = []
    for name, version in pack.wheels:
        meta = fetch(PYPI.format(name=name, version=version))
        f = pick(meta.get("urls") or [])
        if f is None:
            raise RuntimeError(f"{name} {version} has no build for this computer.")
        out.append({"name": name, "version": version, "url": f["url"], "filename": f["filename"],
                    "size": int(f.get("size") or 0), "sha256": (f.get("digests") or {}).get("sha256", "")})
    return out


def _cached_plan(key: str) -> Path:
    return folder(key) / "plan.json"


def plan(key: str, fetch=None) -> dict:
    """What installing the pack would download, in bytes -- asked before anything
    is: the wheels' sizes from PyPI (cached beside the pack), and the models'."""
    pack = PACKS[key]
    why = why_not(pack)
    if why:
        return {"key": key, "label": pack.label, "what": pack.what, "can": False, "why": why,
                "installed": installed(key)}
    wheels_bytes = 0
    if not installed(key):
        try:
            files = json.loads(_cached_plan(key).read_text(encoding="utf-8"))
            if [[f["name"], f["version"]] for f in files] != [list(w) for w in pack.wheels]:
                raise ValueError("stale")
        except (OSError, ValueError, KeyError):
            files = resolve(pack, fetch)
            _cached_plan(key).parent.mkdir(parents=True, exist_ok=True)
            _cached_plan(key).write_text(json.dumps(files), encoding="utf-8")
        wheels_bytes = sum(f["size"] for f in files)
    # Models already in the library's cache -- a developer's machine, or a pack
    # downloaded before -- are not fetched again.
    missing = [m for m in pack.models if not _model_on_disk_without_pack(m)]
    models_bytes = sum(m.size for m in missing)
    return {"key": key, "label": pack.label, "what": pack.what, "can": True, "why": "",
            "installed": installed(key) and not missing,
            "bytes": wheels_bytes + models_bytes, "wheels_bytes": wheels_bytes,
            "models": [m.name for m in missing]}


def _model_on_disk_without_pack(m: Model) -> bool:
    """A model already in Hugging Face's cache, found without the library: the
    folder the library would read it from, with a finished snapshot in it."""
    root = Path(os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
                or Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub")
    snap = root / ("models--" + m.repo.replace("/", "--")) / "snapshots"
    try:
        return any((d / "model.bin").is_file() for d in snap.iterdir())
    except OSError:
        return False


# ---------------------------------------------------------------- installing

class Installer:
    """One pack at a time, with a snapshot the page polls."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.key, self.state, self.error, self.step = "", "idle", "", ""
        self.done, self.total = 0, 0

    def busy(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def start(self, key: str) -> tuple[bool, str]:
        pack = PACKS.get(key)
        if pack is None:
            return False, "There is no such download."
        why = why_not(pack)
        if why:
            return False, why
        if self.busy():
            return False, "Something is already being downloaded."
        with self._lock:
            self._stop.clear()
            self.key, self.state, self.error, self.step = key, "running", "", "Getting ready"
            self.done, self.total = 0, 0
            self._thread = threading.Thread(target=self._run, args=(pack,), name=f"autostream-pack-{key}",
                                            daemon=True)
            self._thread.start()
        return True, ""

    def cancel(self) -> None:
        self._stop.set()

    def _set(self, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def _download(self, f: dict, into: Path) -> Path:
        out = into / f["filename"]
        if out.is_file() and (not f["sha256"] or _sha256(out) == f["sha256"]):
            self._set(done=self.done + f["size"])
            return out
        part = out.with_suffix(out.suffix + ".part")
        h = hashlib.sha256()
        req = urllib.request.Request(f["url"], headers={"User-Agent": "AutoStream"})
        with urllib.request.urlopen(req, timeout=60) as r, part.open("wb") as fh:
            while True:
                if self._stop.is_set():
                    raise InterruptedError
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                with self._lock:
                    self.done += len(chunk)
        if f["sha256"] and h.hexdigest() != f["sha256"]:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"{f['filename']} did not arrive whole; try again.")
        part.replace(out)
        return out

    def _run(self, pack: Pack) -> None:
        base = folder(pack.key)
        dl = base / "downloads"
        try:
            dl.mkdir(parents=True, exist_ok=True)
            p = plan(pack.key)
            self._set(total=int(p.get("bytes") or 0))
            if not installed(pack.key):
                files = json.loads(_cached_plan(pack.key).read_text(encoding="utf-8"))
                got = []
                for n, f in enumerate(files, 1):
                    self._set(step=f"Downloading {pack.label.lower()}: {f['name']} ({n} of {len(files)})")
                    got.append(self._download(f, dl))
                self._set(step="Unpacking")
                fresh = base / "site.new"
                shutil.rmtree(fresh, ignore_errors=True)
                fresh.mkdir(parents=True)
                for w in got:
                    with zipfile.ZipFile(w) as z:
                        z.extractall(fresh)
                shutil.rmtree(site(pack.key), ignore_errors=True)
                fresh.replace(site(pack.key))
                _marker(pack.key).write_text(json.dumps({"wheels": [list(w) for w in pack.wheels],
                                                         "when": time.time()}), encoding="utf-8")
                shutil.rmtree(dl, ignore_errors=True)
            activate(pack.key)
            for m in pack.models:
                if self._stop.is_set():
                    raise InterruptedError
                if _model_on_disk(m):
                    continue
                self._set(step=f"Downloading the {m.name} model")
                self._fetch_model(m)
            if pack.module:
                __import__(pack.module)
            self._set(state="done", step="Ready")
            log.info("pack %s installed", pack.key)
        except InterruptedError:
            self._set(state="idle", step="", error="")
            log.info("pack %s stopped", pack.key)
        except Exception as e:  # noqa: BLE001 - the page shows why
            log.exception("could not install the %s pack: %s", pack.key, e)
            self._set(state="failed", error=str(e)[:400])

    def _fetch_model(self, m: Model) -> None:
        """The library fetches its own model; progress is the cache folder growing."""
        from faster_whisper.utils import download_model
        start = self.done
        box: dict = {}

        def run():
            try:
                download_model(m.name)
            except Exception as e:  # noqa: BLE001
                box["error"] = e

        t = threading.Thread(target=run, daemon=True)
        t.start()
        root = _hub_cache() / ("models--" + m.repo.replace("/", "--"))
        while t.is_alive():
            t.join(1.0)
            self._set(done=start + min(m.size, _tree_size(root)))
            if self._stop.is_set():
                raise InterruptedError
        if "error" in box:
            raise RuntimeError(f"the {m.name} model could not be downloaded: {box['error']}")
        self._set(done=start + m.size)

    def snapshot(self) -> dict:
        with self._lock:
            return {"key": self.key, "state": self.state, "error": self.error, "step": self.step,
                    "done": self.done, "total": self.total,
                    "percent": int(100 * self.done / self.total) if self.total else 0}


def _hub_cache() -> Path:
    try:
        from huggingface_hub import constants
        return Path(constants.HF_HUB_CACHE)
    except Exception:  # noqa: BLE001
        return Path.home() / ".cache" / "huggingface" / "hub"


def _tree_size(root: Path) -> int:
    total = 0
    try:
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


_INSTALLER = Installer()


def installer() -> Installer:
    return _INSTALLER
