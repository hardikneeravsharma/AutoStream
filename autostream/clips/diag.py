r"""What a clip run actually did, written down, for when it goes wrong.

WHY THIS EXISTS. A clip run is a dozen stages across six modules and a few
hundred ffmpeg invocations, and when it fails on somebody else's machine the
evidence is a toast saying "Failed - see the log" and a log line holding the
last six lines of one process's stderr. That was enough to find a bug on a
machine you can reach. It was not enough for the Radeon one: ffmpeg exited 255
before reading a frame, every caller discarded stderr, and what came back was
"it found 0 kills".

WHAT IT IS. A Recorder that a run carries, collecting:

    every stage, with how long it took and whether it finished
    every external process, with its exit code and the tail of its stderr
    every error, with its traceback and which stage was open at the time
    what the machine is: OS, CPU, RAM, disk, ffmpeg build, GPU support
    what the input was: codec, resolution, frame rate, duration, size

and then writing all of it to ONE file. One, because what gets sent back is
whatever was easiest to attach, and three files means two of them arrive.

FOUR RULES IT CANNOT BREAK

    1. IT MUST NEVER FAIL THE JOB. A diagnostic that turns a working run into
       a failed one is worse than no diagnostic. Every public method here
       swallows its own exceptions; the report is best effort and the run
       neither knows nor cares whether it was written.

    2. IT MUST BE WRITTEN EVEN WHEN THE RUN FAILS. That is the case it exists
       for, so the write happens in the job's `finally`, after the terminal
       state is known.

    3. NO SECRETS. Nothing here reads the config, the token store or the
       environment wholesale. The one thing that leaks by accident is paths --
       the user's account name is in every single one of them -- so the home
       directory is replaced on the way out.

    4. OFF BY DEFAULT. `ui.developer_mode` gates the button that asks for one.
       A run nobody asked to diagnose carries OFF, whose methods do nothing;
       the instrumentation at the call sites stays in place and costs an
       attribute lookup and a call that returns.

THE SHAPE OF THE FILE. JSON, so a program can read it, with a rendered human
summary as the first key so the first screen answers "what broke" without the
reader parsing anything.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# How much of a process's stderr is kept. ffmpeg is chatty on failure and the
# useful line is the last one, but the lines above it say what it was doing.
STDERR_LINES = 40
# A cap on how many SUCCESSFUL process records are kept. A montage of fifty
# clips is fifty-plus invocations and a scan is hundreds; past this they are
# counted rather than kept, so the report stays small enough to attach.
MAX_PROCESSES = 400
MAX_EVENTS = 600
# A command line longer than this is cut. A reel's filter graph is tens of
# thousands of characters -- the code that builds it already writes it to a
# file -- and keeping it whole would make the report larger than the thing it
# describes.
MAX_ARG_CHARS = 1200


def _now() -> float:
    return time.time()


def _home_shape(text: str) -> str:
    r"""Replace the user's home directory with %USERPROFILE%.

    The only personal thing a clip run's paths carry is the account name, and
    it is in every one of them. Replaced rather than removed: a reader still
    needs to see that two paths are on the same drive and in the same tree.

    THREE SPELLINGS, NOT ONE. The same folder reaches this written three
    different ways and all three were found leaking in a real run:

        C:\Users\sam     a path, as everything that handles files writes it
        C:/Users/sam     a path, as everything that came through a browser
                         or a config file writes it
        C:\\Users\\sam   a path inside a Python repr -- which is what the
                         text of an OSError is. FileExistsError's message
                         embeds the filename repr'd, so the doubled form is
                         exactly what lands in a report about a run that
                         failed on a file, which is most of them.

    THE DOUBLED FORM GOES FIRST. A single-backslash match cannot occur
    inside a doubled one, so order is not strictly load-bearing here -- but
    longest-first is the habit that keeps it true if a fourth spelling is
    ever added.
    """
    try:
        home = str(Path.home())
    except Exception:                                        # noqa: BLE001
        return text
    if not home:
        return text
    slashed = home.replace("\\", "/")
    backed = slashed.replace("/", "\\")
    out = text
    for form in (backed.replace("\\", "\\\\"), backed, slashed):
        out = out.replace(form, "%USERPROFILE%")
        out = out.replace(form.lower(), "%USERPROFILE%")
    return out


def redact(value: Any) -> Any:
    """`value` with home paths shaped, walked into lists and dicts."""
    if isinstance(value, str):
        return _home_shape(value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


# ------------------------------------------------------------- the machine

def system_info() -> dict:
    """What this PC is, as far as a clip run is concerned. Never raises."""
    out: dict[str, Any] = {}

    def attempt(key: str, fn) -> None:
        try:
            out[key] = fn()
        except Exception as e:                               # noqa: BLE001
            out[key] = f"(unavailable: {e.__class__.__name__}: {e})"

    attempt("os", lambda: f"{platform.system()} {platform.release()} "
                          f"({platform.version()})")
    attempt("machine", platform.machine)
    attempt("processor", lambda: platform.processor() or "(unknown)")
    attempt("cpu_count", lambda: os.cpu_count() or 0)
    attempt("python", lambda: sys.version.split()[0])
    attempt("frozen", lambda: bool(getattr(sys, "frozen", False)))
    attempt("autostream", _app_version)
    attempt("memory_gb", _memory_gb)
    attempt("numpy", _numpy_version)
    attempt("ffmpeg", lambda: tool_version("ffmpeg"))
    attempt("ffprobe", lambda: tool_version("ffprobe"))
    attempt("tesseract", lambda: tool_version("tesseract"))
    attempt("gpu", gpu_info)
    return out


def _app_version() -> str:
    from .. import __version__

    return __version__


def _memory_gb() -> float | str:
    """Installed RAM in GB. Windows only; "(unknown)" everywhere else.

    No psutil: it is not a dependency of this app and adding one for a line
    in a report would be the wrong trade.
    """
    if sys.platform != "win32":
        return "(unknown)"
    import ctypes

    class _Status(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullExtendedVirtual", ctypes.c_ulonglong)]

    st = _Status()
    st.dwLength = ctypes.sizeof(_Status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    return round(st.ullTotalPhys / (1024 ** 3), 1)


def _numpy_version() -> str:
    try:
        import numpy
    except Exception:                                        # noqa: BLE001
        return "(not installed)"
    return str(numpy.__version__)


def tool_version(name: str) -> dict:
    """Where a binary is and what version it says it is.

    THE PATH MATTERS AS MUCH AS THE VERSION. Two ffmpeg builds of the same
    version differ in which encoders they were compiled with, and "which
    ffmpeg is it finding" has been the answer more than once.
    """
    from . import deps, tools

    try:
        # Tesseract has its own finder. tools.binary searches ffmpeg's
        # install folders and its error says to install ffmpeg, so a report
        # from a machine without Tesseract told the reader to run
        # `winget install --id Gyan.FFmpeg` -- and missed the UB-Mannheim
        # build, which does not put itself on PATH.
        where = deps.tesseract() if name == "tesseract" else tools.binary(name)
    except Exception as e:                                   # noqa: BLE001
        return {"found": False, "why": str(e)}
    first = "(could not be asked)"
    try:
        p = subprocess.run([where, "-version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20,
                           creationflags=_NO_WINDOW)
        head = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
        first = head[0] if head else ""
    except Exception:                                        # noqa: BLE001
        pass
    return {"found": True, "path": _home_shape(where), "version": first}


def gpu_info() -> dict:
    """Whether hardware encode and decode actually WORK here, not whether
    ffmpeg lists them.

    tools.has_nvenc and has_cuda both list the capability and then use it
    once, which is the distinction that cost a friend with a Radeon a working
    CS2 scan. The adapter names come from Windows so the report says which
    card the answer is about.
    """
    from . import tools

    out: dict[str, Any] = {}
    for key, fn in (("nvenc", tools.has_nvenc), ("cuda", tools.has_cuda),
                    ("amf", tools.has_amf), ("qsv", tools.has_qsv), ("d3d11va", tools.has_d3d11va)):
        try:
            out[key] = bool(fn())
        except Exception as e:                               # noqa: BLE001
            out[key] = f"(check failed: {e})"
    # What the run will actually use, so a report answers "was it on the card?"
    # without the reader having to know the order the probes are tried in.
    try:
        out["decode"] = tools.hw_decoder() or "cpu"
        out["encode"] = tools.gpu_encoder() or "cpu"
    except Exception as e:                                   # noqa: BLE001
        out["decode"] = out["encode"] = f"(check failed: {e})"
    out["adapters"] = adapters()
    return out


def memory_used() -> dict:
    """How much memory this process has needed, at its worst.

    THE PEAK, NOT THE CURRENT. A scan holds frames for a thread pool and a
    reel builds a filter graph in memory; both are long gone by the time a
    run ends, so the number at the end says nothing about the run. The peak
    working set is what answers "did this machine have enough", which is the
    question a 16 GB PC that failed on a 1440p recording is asking.

    Windows only, through the API that already answers it. No psutil: it is
    not a dependency of this app and adding one for a line in a report would
    be the wrong trade.
    """
    if sys.platform != "win32":
        return {}
    try:
        import ctypes
        from ctypes import wintypes

        class _Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        # THE SIGNATURES, SPELLED OUT. Without them ctypes defaults the
        # return of GetCurrentProcess to a 32-bit int, and the pseudo-handle
        # -- which is (HANDLE)-1 -- arrives at a 64-bit HANDLE parameter
        # truncated. The call then fails with no error set and returns
        # nothing, which reads exactly like "this platform has no counters".
        kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        c = _Counters()
        c.cb = ctypes.sizeof(_Counters)
        if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(),
                                          ctypes.byref(c), c.cb):
            return {}
        return {"peak_mb": round(c.PeakWorkingSetSize / (1024 ** 2), 1),
                "now_mb": round(c.WorkingSetSize / (1024 ** 2), 1)}
    except Exception:                                        # noqa: BLE001
        return {}


def adapters() -> list[str]:
    """The graphics cards Windows knows about. [] anywhere else."""
    if sys.platform != "win32":
        return []
    # PowerShell rather than wmic: wmic is deprecated and already absent from
    # recent Windows 11 installs, which is exactly the machine a report like
    # this comes from.
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
           "Get-CimInstance Win32_VideoController | "
           "Select-Object -ExpandProperty Name"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=25,
                           encoding="utf-8", errors="replace",
                           creationflags=_NO_WINDOW)
    except Exception:                                        # noqa: BLE001
        return []
    return [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()][:6]


def disk_for(path: Path | str) -> dict:
    """Free and total space on the volume `path` is on.

    A run that dies three clips in with a truncated file is out of disk, and
    nothing else in the report would say so.
    """
    try:
        total, _used, free = shutil.disk_usage(str(path))
    except Exception as e:                                   # noqa: BLE001
        return {"error": str(e)}
    return {"free_gb": round(free / (1024 ** 3), 1),
            "total_gb": round(total / (1024 ** 3), 1)}


# ------------------------------------------------------ the active recorder
#
# WHY A MODULE GLOBAL AND NOT A PARAMETER. Every external process in a clip
# run goes through tools.run / tools.ffmpeg_raw, and those are called from a
# dozen modules, several of them on worker threads inside the scan pool.
# Threading a recorder through all of that would be a large change to code
# that has nothing to do with diagnostics -- and a thread-local would miss
# precisely the calls that matter, because the ffmpeg ones happen on pool
# threads.
#
# One job runs at a time (jobs.JobRunner enforces it, because these saturate
# the encoder), so one global is correct. Anything else on the machine that
# calls tools.run while a diagnostic is recording is captured too; that is
# noise in a developer's report, not a defect.
_active: "Recorder | None" = None
_active_lock = threading.Lock()


def active() -> "Recorder | None":
    return _active


def set_active(rec: "Recorder | None") -> None:
    global _active
    with _active_lock:
        _active = rec


def note_process(args, returncode: int, stderr: str, seconds: float,
                 stdout_bytes: int | None = None) -> None:
    """Called by tools.run and friends. Does nothing when nobody is recording."""
    rec = _active
    if rec is None:
        return
    try:
        rec.process(args, returncode, stderr, seconds, stdout_bytes)
    except Exception:                                        # noqa: BLE001
        pass                                    # rule 1: never fail the job


# -------------------------------------------------------------- the recorder

class Recorder:
    """Collects one run's worth of evidence. Thread-safe; never raises."""

    on = True

    def __init__(self, *, job: str = "", source: Path | str = "",
                 game: str = "", options: dict | None = None):
        self.job = job
        self.source = str(source)
        self.game = game
        self.options = dict(options or {})
        self.started = _now()
        self.finished: float | None = None
        self.outcome = "(unfinished)"
        self.stages: list[dict] = []
        self.processes: list[dict] = []
        self.process_total = 0
        self.process_failed = 0
        self.errors: list[dict] = []
        self.events: list[dict] = []
        self.facts: dict[str, Any] = {}
        self.outputs: list[dict] = []
        self._open: dict | None = None
        self._lock = threading.Lock()

    # --------------------------------------------------------------- stages

    def stage(self, name: str) -> None:
        """Begin a stage, closing whichever one was open.

        MARKS, NOT A CONTEXT MANAGER. The pipeline is one long method whose
        stages are already marked by comments; turning each into a `with`
        block would reindent six hundred lines of working code in order to
        add instrumentation, which is how instrumentation introduces bugs. A
        mark per boundary gives the same per-stage timings for one line each,
        and the stage still open when the run ends is -- by construction --
        the one it died in.
        """
        try:
            with self._lock:
                self._close(ok=True)
                # `at` is seconds from the start of the run, and it is
                # kept as well as the duration so a stage can be lined up
                # against the app's own log, whose lines carry wall-clock
                # times. "the cut took 40s" and "the cut began 11m12s in"
                # answer different questions.
                self._open = {"name": str(name), "at": round(_now() - self.started, 3),
                              "started": _now(), "seconds": None,
                              "ok": None, "notes": {}}
        except Exception:                                    # noqa: BLE001
            pass

    def _close(self, *, ok: bool, error: str = "") -> None:
        """Caller holds the lock."""
        s = self._open
        if s is None:
            return
        s["seconds"] = round(_now() - s.pop("started"), 3)
        s["ok"] = bool(ok)
        if error:
            s["error"] = error
        self.stages.append(s)
        self._open = None

    def end_stages(self, *, ok: bool, error: str = "") -> None:
        try:
            with self._lock:
                self._close(ok=ok, error=error)
        except Exception:                                    # noqa: BLE001
            pass

    def note(self, key: str, value: Any) -> None:
        """A fact about the run. Attached to the open stage AND to the top
        level: a reader skimming wants it in one place, and a reader debugging
        wants to know which stage learned it."""
        try:
            with self._lock:
                self.facts[str(key)] = value
                if self._open is not None:
                    self._open["notes"][str(key)] = value
        except Exception:                                    # noqa: BLE001
            pass

    def event(self, message: str, **fields) -> None:
        """A moment worth a line, with the stage and the offset it happened at."""
        try:
            with self._lock:
                if len(self.events) >= MAX_EVENTS:
                    return
                self.events.append({
                    "at": round(_now() - self.started, 3),
                    "stage": (self._open or {}).get("name", ""),
                    "message": str(message), **redact(fields)})
        except Exception:                                    # noqa: BLE001
            pass

    # ------------------------------------------------------------ processes

    def process(self, args, returncode: int, stderr: str, seconds: float,
                stdout_bytes: int | None = None) -> None:
        with self._lock:
            self.process_total += 1
            failed = int(returncode) != 0
            if failed:
                self.process_failed += 1
            # A FAILED PROCESS IS ALWAYS KEPT. The cap exists to stop a
            # fifty-clip montage filling the file with successes; dropping
            # the one non-zero exit among them would remove the only thing
            # the report was opened for, so the cap applies to successes.
            if not failed and len(self.processes) >= MAX_PROCESSES:
                return
            tail = "\n".join((stderr or "").strip().splitlines()[-STDERR_LINES:])
            row: dict[str, Any] = {
                "at": round(_now() - self.started, 3),
                "stage": (self._open or {}).get("name", ""),
                "exe": Path(str(args[0])).name if args else "",
                "args": redact(_arg_text(args)),
                "exit": int(returncode),
                "seconds": round(float(seconds), 3),
            }
            if stdout_bytes is not None:
                row["stdout_bytes"] = int(stdout_bytes)
            if tail:
                row["stderr"] = redact(tail)
            self.processes.append(row)

    # --------------------------------------------------------------- errors

    def error(self, exc: BaseException, *, where: str = "") -> None:
        try:
            with self._lock:
                self.errors.append({
                    "at": round(_now() - self.started, 3),
                    "stage": where or (self._open or {}).get("name", ""),
                    "type": exc.__class__.__name__,
                    "message": redact(str(exc)),
                    "traceback": redact("".join(traceback.format_exception(
                        type(exc), exc, exc.__traceback__))),
                })
        except Exception:                                    # noqa: BLE001
            pass

    def output(self, kind: str, path: Path | str) -> None:
        """A file the run produced, with its size.

        A file that exists and is zero bytes is a different failure from one
        that is not there, and both read as "no clips" from the outside.
        """
        try:
            p = Path(str(path))
            here = p.is_file()
            with self._lock:
                self.outputs.append({"kind": str(kind),
                                     "path": _home_shape(str(p)),
                                     "exists": here,
                                     "bytes": p.stat().st_size if here else None})
        except Exception:                                    # noqa: BLE001
            pass

    # ----------------------------------------------------------- the report

    def finish(self, outcome: str, error: str = "") -> None:
        try:
            with self._lock:
                self.finished = _now()
                self.outcome = str(outcome)
                if error:
                    self.facts["final_error"] = redact(str(error))
        except Exception:                                    # noqa: BLE001
            pass

    def report(self) -> dict:
        with self._lock:
            stages = list(self.stages)
            if self._open is not None:
                # Still open at report time: the run never got past it.
                stages.append({
                    "name": self._open["name"],
                    "at": self._open["at"],
                    "seconds": round(_now() - self._open["started"], 3),
                    "ok": False,
                    "notes": dict(self._open["notes"]),
                    "error": "did not finish",
                })
            body = {
                "schema": 1,
                "kind": "autostream-clip-diagnostic",
                "job": self.job,
                "outcome": self.outcome,
                "started": _stamp(self.started),
                "finished": _stamp(self.finished) if self.finished else None,
                "seconds": round((self.finished or _now()) - self.started, 3),
                "input": {
                    "source": self.source,
                    "game": self.game,
                    **(self.facts.get("source_info") or {}),
                },
                "options": _safe_options(self.options),
                "facts": dict(self.facts),
                "stages": stages,
                "processes": list(self.processes),
                "process_summary": {
                    "total": self.process_total,
                    "failed": self.process_failed,
                    "kept": len(self.processes),
                },
                "errors": list(self.errors),
                "events": list(self.events),
                "outputs": list(self.outputs),
                "system": self.facts.get("system") or {},
            }
        # ONE REDACTION, OVER THE WHOLE THING, AT THE ONE PLACE THE REPORT
        # LEAVES THIS OBJECT. Redacting each piece as it was collected is
        # what the first version did, and it leaked by three separate routes
        # at once: a `note` reached `facts` redacted and `stages[].notes`
        # raw, a stage's `error` was never passed through it at all, and the
        # human summary -- built from the body -- reprinted both. A rule
        # applied in nine places is a rule with nine chances to be forgotten.
        body = redact(body)
        # The human part is built FROM the machine part, after redaction, so
        # the two cannot disagree about what happened and the summary cannot
        # reprint something the body removed.
        return {"summary": summarise(body), **body}

    def write(self, folder: Path | str) -> str:
        """Write the one file. -> its path, or "" if it could not be written.

        Rule 1 in the module docstring: this is called from the job's
        `finally` and must not raise there, so every failure mode here ends
        in an empty string and a log line.
        """
        try:
            body = self.report()
        except Exception as e:                               # noqa: BLE001
            log.warning("the diagnostic report could not be built: %s", e)
            return ""
        try:
            out = Path(folder)
            out.mkdir(parents=True, exist_ok=True)
            path = _free_name(out)
            path.write_text(json.dumps(body, indent=2, default=str),
                            encoding="utf-8")
        except Exception as e:                               # noqa: BLE001
            log.warning("the diagnostic report could not be written: %s", e)
            return ""
        log.info("diagnostic written: %s", path)
        return str(path)


class _Off(Recorder):
    """The recorder an ordinary run carries: present, and does nothing.

    Instrumentation guarded by `if self.diag:` at forty call sites is
    instrumentation somebody will forget to guard. This costs an attribute
    lookup and a call that returns.
    """

    on = False

    def stage(self, name: str) -> None: return None

    def end_stages(self, *, ok: bool, error: str = "") -> None: return None

    def note(self, key: str, value: Any) -> None: return None

    def event(self, message: str, **fields) -> None: return None

    def process(self, *a, **k) -> None: return None

    def error(self, exc: BaseException, *, where: str = "") -> None: return None

    def output(self, kind: str, path: Path | str) -> None: return None

    def finish(self, outcome: str, error: str = "") -> None: return None

    def write(self, folder: Path | str) -> str: return ""


OFF = _Off()


# ----------------------------------------------------------------- helpers

def _stamp(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def _free_name(folder: Path) -> Path:
    """A path in `folder` nothing has taken yet.

    THE STAMP IS ONLY ACCURATE TO THE SECOND, and two runs can land inside
    one. Measured, not imagined: driving six diagnostic runs back to back --
    a missing file, a truncated file and a zero-byte file all fail in well
    under a second -- produced four files for six runs, so two reports were
    silently written over. The one that survives is the later one, which is
    not even the one most likely to be wanted.
    """
    base = f"clip-diagnostic-{time.strftime('%Y-%m-%d-%H%M%S')}"
    path = folder / f"{base}.json"
    if not path.exists():
        return path
    for i in range(2, 1000):
        alt = folder / f"{base}_{i}.json"
        if not alt.exists():
            return alt
    # A thousand reports inside one second is not a thing that happens, but
    # the fallback still has to be a name nobody else has -- a clock-derived
    # one can repeat, and repeating here means losing a report silently,
    # which is the exact failure this function exists to stop.
    return folder / f"{base}_{uuid.uuid4().hex[:8]}.json"


def _arg_text(args) -> str:
    try:
        text = " ".join(str(a) for a in args)
    except Exception:                                        # noqa: BLE001
        return "(unreadable)"
    if len(text) <= MAX_ARG_CHARS:
        return text
    return text[:MAX_ARG_CHARS] + f"... (+{len(text) - MAX_ARG_CHARS} chars)"


# Options that are bulk data rather than a decision: counted, not copied.
# Nothing in the clip options is a credential -- the config as a whole is
# deliberately NOT collected -- and the file paths among them are shaped by
# redact() on the way out.
_BULK_OPTIONS = ("kills", "marks", "per_clip", "card_box")


def _safe_options(opt: dict) -> dict:
    out: dict[str, Any] = {}
    for k, v in (opt or {}).items():
        if k in _BULK_OPTIONS:
            try:
                out[k] = f"({len(v)} items)"
            except Exception:                                # noqa: BLE001
                out[k] = "(present)"
        else:
            out[k] = v
    return out


def summarise(body: dict) -> str:
    """The human header: what happened, where the time went, what broke.

    BUILT FROM THE MACHINE-READABLE BODY, never alongside it. A summary
    assembled separately drifts from the data under it, and then the first
    thing the reader sees is the thing that is wrong.
    """
    lines: list[str] = []
    add = lines.append
    add(f"AutoStream clip diagnostic - {body.get('outcome', '?')}")
    add(f"job        {body.get('job', '')}")
    add(f"started    {body.get('started', '')}")
    add(f"took       {_mins(body.get('seconds') or 0)}")

    src = body.get("input") or {}
    bits = [f"{src.get('width', '?')}x{src.get('height', '?')}",
            f"{src.get('fps', '?')}fps", str(src.get("vcodec") or "?")]
    if src.get("duration"):
        bits.append(_mins(src["duration"]) + " long")
    add(f"input      {Path(str(src.get('source', ''))).name} - " + ", ".join(bits))
    add(f"game       {src.get('game') or '(none)'}")

    sysinfo = body.get("system") or {}
    gpu = sysinfo.get("gpu") or {}
    add(f"machine    {sysinfo.get('os', '?')}, {sysinfo.get('cpu_count', '?')} CPUs, "
        f"{sysinfo.get('memory_gb', '?')} GB")
    add(f"gpu        nvenc={gpu.get('nvenc')} cuda={gpu.get('cuda')}  "
        f"{', '.join(gpu.get('adapters') or []) or '(no adapter list)'}")
    ff = sysinfo.get("ffmpeg")
    add(f"ffmpeg     {ff.get('version') if isinstance(ff, dict) else ff}")

    mem = (body.get("facts") or {}).get("memory") or {}
    if mem:
        add(f"memory     peak {mem.get('peak_mb')} MB")
    ps = body.get("process_summary") or {}
    add(f"processes  {ps.get('total', 0)} run, {ps.get('failed', 0)} failed")

    add("")
    add("--- where the time went ---")
    stages = body.get("stages") or []
    if not stages:
        add("  (no stage was reached)")
    for s in stages:
        flag = "ok  " if s.get("ok") else "FAIL"
        add(f"  {flag} {float(s.get('seconds') or 0):>8.2f}s  {s.get('name', '')}"
            + (f"   <- {s['error']}" if s.get("error") else ""))

    errors = body.get("errors") or []
    add("")
    add(f"--- errors ({len(errors)}) ---")
    if not errors:
        add("  (none)")
    for e in errors:
        add(f"  [{e.get('stage', '')}] {e.get('type', '')}: {e.get('message', '')}")

    bad = [p for p in (body.get("processes") or []) if p.get("exit")]
    add("")
    add(f"--- processes that failed ({len(bad)}) ---")
    if not bad:
        add("  (none)")
    for p in bad[:10]:
        add(f"  {p.get('exe', '')} exit {p.get('exit')} in stage "
            f"{p.get('stage') or '(none)'}")
        for ln in str(p.get("stderr", "")).splitlines()[-4:]:
            add(f"      {ln}")

    outs = body.get("outputs") or []
    add("")
    add(f"--- what it produced ({len(outs)}) ---")
    if not outs:
        add("  (nothing)")
    for o in outs[:40]:
        if o.get("exists"):
            add(f"  {o.get('kind', '')}: {Path(str(o.get('path', ''))).name} "
                f"({o.get('bytes')} bytes)")
        else:
            add(f"  {o.get('kind', '')}: MISSING {o.get('path', '')}")
    return "\n".join(lines)


def _mins(seconds: float) -> str:
    s = max(0, int(round(float(seconds or 0))))
    return f"{s}s" if s < 60 else f"{s // 60}m{s % 60:02d}s"
