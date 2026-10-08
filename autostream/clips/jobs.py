"""Runs a clip job on its own thread and publishes progress.

WHERE THIS MUST NOT RUN
    Not on the engine thread. That loop is strictly serial -- tick, sleep,
    tick -- so a five-minute ffmpeg pass parked in it would freeze phase
    transitions, the OBS health watchdog and chat polling for the duration.

    Not on the HTTP request thread either. The server speaks HTTP/1.1 with
    keep-alive and a browser only opens about six connections per host; pinning
    one open for minutes is fragile, and a fetch that never returns looks
    identical to a hang.

    So: the POST starts a worker and returns immediately, and progress is
    published into the payload the dashboard already polls every two seconds.
    No new client machinery, and it survives a page reload -- which a
    JavaScript-side "busy" flag does not.

CANCELLATION
    Cooperative. The worker checks a flag between steps and ffmpeg's own
    Popen is tracked so a long encode can be killed mid-run rather than only
    between clips.
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import (cutter, detect, diag, killfeed, montage, overlay, plan,
               profiles, promo, voice)
from .. import atomic, paths
from .cs2_cards import HudUnread
from .tools import FfmpegMissing, duration_label, media_info

log = logging.getLogger("autostream.clips.jobs")

# HOW FAST EACH SCAN MODE ACTUALLY IS, in seconds of recording per second of
# work. Measured on this machine, on real recordings, so the estimate shown
# before any progress exists is a measurement rather than a guess:
#
#   feedbar   (Valorant)  102 min in 435s  -> 14x
#   killfeed  (CS2, OCR)   30 min in 396s  ->  4.5x
#   cardcount (CS2 cards)  30 min in 170s  -> 10x        (same pass as the HUD)
#   template  (Delta Force) faster than any of them; treated as feedbar
#
# ROUND MODE IS A DIFFERENT PASS AND A MUCH SLOWER ONE. scan_with_hud reads the
# feed AND the scoreboard, which is two crops OCR'd per sampled frame instead
# of one, so the 4.5x above does not describe it and must not be used for it.
# Measured twice on real runs, both about three quarters of an hour of CS2:
#
#   22 chunks reporting 82s a chunk                    -> 1.46x
#   44 min of footage read in ~37 min after the probe  -> 1.19x
#
# 1.2 is the lower of the two, because this number's whole job is to be quoted
# BEFORE the run and an estimate that undersells is the one that gets somebody
# to press the button. The page advertised a 43-minute selection as "about 4m
# of scanning" against a real 40.
#   summary   (Marvel Rivals) 38 min in 118s -> 19x; 16 quoted for margin
# "loudness" DECODES NO VIDEO AT ALL -- it reads the audio track at 8 kHz
# mono and nothing else -- so it is two orders of magnitude faster than any
# reader that looks at frames. Measured on 600s of 720p30 h264 with AAC
# audio: 0.17-0.19s, which is about 3,200x real time. Quoted at 1,500 so the
# page's estimate stays honest on a slow disk and over a network share.
SCAN_RATE = {"feedbar": 14.0, "killfeed": 4.5, "cardcount": 10.0,
             "template": 14.0, "colour": 14.0, "summary": 16.0,
             "loudness": 1500.0}
# Keyed separately rather than overwriting "killfeed": the same profile scans
# at either rate depending on whether rounds are switched on for the run.
ROUND_SCAN_RATE = {"killfeed": 1.2}
DEFAULT_SCAN_RATE = 8.0


def scan_rate(mode: str | None, rounds: bool = False) -> float:
    """Seconds of recording read per second of work, for an estimate."""
    if rounds and mode in ROUND_SCAN_RATE:
        return ROUND_SCAN_RATE[mode]
    return SCAN_RATE.get(mode or "", DEFAULT_SCAN_RATE)

# Seconds per clip for everything after the scan: cutting the master, the
# vertical, the caption pass and the voice. Measured across the runs in this
# session at 9-24s a clip depending on length; the mean is what is reported.
CUT_SECONDS_PER_CLIP = 16.0
MONTAGE_SECONDS = 25.0

STEPS = ("scan", "cut", "vertical", "montage")


class NoKills(RuntimeError):
    """The recording was read and there were no kills in it.

    An answer, not a fault: a menu, a spectated match or a bad round all read
    this way. It was raised as a plain RuntimeError, so the page said "Could
    not finish", "Failed - see the log" and an error toast about a run that
    had done exactly what it was asked.
    """


class NeedsDemo(RuntimeError):
    """The replay could not be found, and reading the screen instead is dear.

    RAISED RATHER THAN FALLEN BACK FROM. Counter-Strike read off the screen
    costs about forty minutes for three quarters of an hour of footage and
    produces a worse answer than the demo would have: measured on a real run,
    the screen gave up 10 kills where the demo held 24. Spending that on
    somebody's behalf, because a replay they may simply not have downloaded
    yet did not match, is the expensive decision made silently.

    So the run stops and says what it needs. `demo_fallback` in the options is
    the deliberate "read the screen anyway", which the page offers as a button
    next to the sharing-code box.
    """


# Per-clip settings are keyed on the clip's START, to a tenth of a second.
# Not on its index: the list is re-planned between reviewing it and cutting
# it, and a rank can move. Not on its name either -- the name carries the rank.
def clip_key(start: float) -> str:
    return f"{float(start):.1f}"


def _mmss(seconds: float) -> str:
    s = int(max(0.0, seconds))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _hms(seconds: float) -> str:
    s = int(max(0.0, seconds))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def _kill_tags(kill) -> list[str]:
    """What was remarkable about one demo kill, for the caption layer."""
    out = []
    for flag, tag in (("headshot", "HEADSHOT"), ("thrusmoke", "THROUGH SMOKE"),
                      ("blinded", "BLIND"), ("penetrated", "WALLBANG"),
                      ("noscope", "NO SCOPE")):
        if getattr(kill, flag, False):
            out.append(tag)
    return out


def _stamp_folder(started: float | None, game: str | None,
                  style: str | None = None) -> str:
    when = datetime.fromtimestamp(started or time.time())
    name = f"{when:%Y-%m-%d_%H%M}_{plan.slug(game or 'Session')}"
    # The style is part of the name because the folder is keyed on the SESSION,
    # so re-cutting one stream at a different length would otherwise land in the
    # folder that already exists and leave 10-second and 15-second clips mixed
    # together with no way to tell which run produced which.
    if style and style != "custom":
        name += f"_{plan.slug(style)}"
    return name


def _summary_game(game_key: str | None, game: str | None) -> bool:
    """Whether this game is made into match videos rather than clips."""
    try:
        prof = profiles.for_game(game_key, game)
    except Exception:                                   # noqa: BLE001
        return False
    return bool(prof and prof.mode == "summary")


def _free_folder(root: Path, name: str) -> Path:
    """`name`, or name_2, name_3... if it is already taken.

    Two runs of the same session at the same style are a deliberate redo, and
    silently writing over the previous attempt loses whichever clips the new
    run happens not to produce.
    """
    p = root / name
    if not p.exists():
        return p
    for i in range(2, 100):
        alt = root / f"{name}_{i}"
        if not alt.exists():
            return alt
    return root / f"{name}_{int(time.time())}"


class ClipJob:
    """One run. Not reused -- a second run makes a second job."""

    # ON THE CLASS, not only in __init__. Instrumentation that exists on
    # every job is instrumentation nothing has to check for, and these two
    # are read from `run`, from `snapshot` and from a dozen places inside
    # `_run` -- so a job built any other way than through __init__ has to
    # have them. Several tests build one with __new__ to exercise snapshot
    # and cancel without a real recording, and the first version of this
    # turned every one of those into an AttributeError.
    #
    # OFF is the recorder whose methods return; see clips/diag.py.
    diag: "diag.Recorder" = diag.OFF
    diag_path: str = ""

    def __init__(self, source: Path, *, game: str, game_key: str | None,
                 outdir: Path, options: dict, started: float | None = None,
                 session: dict | None = None):
        self.source = Path(source)
        self.game = game or "Session"
        self.game_key = game_key
        self.options = options
        self.session = session or {}
        # A game made into match videos is not cut in a style at all, and a
        # folder called "..._shortform" holding two ten-minute videos says the
        # wrong thing about what is in it.
        tag = ("match-videos" if _summary_game(game_key, game)
               else options.get("style"))
        self.folder = _free_folder(Path(outdir), _stamp_folder(started, game, tag))

        self.state = "queued"          # queued|running|done|failed|cancelled
        self.step = "scan"
        self.done = 0
        self.total = 1
        self.message = "Waiting to start"
        self.error: str | None = None
        self.results: list[dict] = []
        self.montage_path: str | None = None
        # YouTube chapters for the montage, ready to paste into a description.
        self.montage_chapters: str = ""
        # The whole match with the dead time out, where it was asked for.
        self.summary_path: str | None = None
        self.summary_chapters: str = ""
        self.reel_path: str | None = None
        self.promo_path: str | None = None
        # Every spoken hook used so far, so no two clips in one session open
        # with the same sentence.
        self.said: list[str] = []
        self.summary: dict = {}
        # In plan_only mode, what WOULD be cut: one entry per clip, with the
        # caption and spoken line it would get, so the choice can be made on
        # the real thing rather than on a description of it.
        self.preview: list[dict] = []
        # Filled in when a demo aligned: which one, and how the detector scored
        # against it. Recorded because it is the only place the detector's
        # accuracy is ever actually measured.
        self.demo: dict = {}
        # What checking the kills against the game's kill emblem did, if the
        # game draws one -- see _confirm_by_emblem.
        self.emblem_note: dict = {}
        # Where Riot's match records cover the recording. Nothing read off the
        # screen is allowed to change a kill inside one.
        self.record_spans: list[tuple[float, float]] = []
        # WHY THE RUN IS TAKING THE SLOW PATH, in one sentence that survives
        # the next step's progress message. A probe that reads twelve minutes
        # and then finds nothing is the difference between a three-minute run
        # and a thirty-minute one, and it used to be visible only in the log --
        # so from the outside a demo that did not match was indistinguishable
        # from a demo that was never looked for.
        self.demo_note: str = ""
        # Set when the run stopped because no replay could be matched. The
        # page turns this into the sharing-code box plus a button that says
        # what reading the screen instead would cost.
        self.needs_demo: bool = False
        self.started_at = time.time()
        self.finished_at: float | None = None
        # For the estimate: when the current step began, how long the recording
        # is, and how it is being read. Filled in as the run learns them.
        self.step_started = self.started_at
        self.source_seconds = 0.0
        self.scan_mode = ""
        # Round mode reads the scoreboard as well as the feed, at a third of
        # the rate, so the estimate has to know which pass this run is.
        self.scan_rounds = False
        self.scan_seconds = 0.0        # how much of the recording will be read
        self.clip_count = 0            # known once the plan exists
        self.eta_at: float | None = None
        # The part of the file being read. Settled by _window() once the source
        # has been probed; until then the whole thing, so anything that asks
        # early gets an answer that is true of every run without a window.
        self.win_start = 0.0
        self.win_end = 0.0
        self.win_whole = True
        # A match-video run's progress in estimated seconds of work, and how
        # long the work already done really took -- see _summary_eta.
        self.sm: dict = {}

        # When Cancel was pressed. A cancelled scan does not stop at once --
        # the chunks already running finish on their own -- so the page has to
        # be able to say "stopping" rather than leave the last message up
        # looking hung.
        self.cancel_at: float | None = None

        # WHAT THIS RUN DID, FOR WHEN IT GOES WRONG. Left as the class's
        # OFF unless the run was started from Developer Mode's "Run
        # diagnostic", in which case this is a real Recorder and the marks
        # through _run() below fill it in. See clips/diag.py.
        if options.get("diagnostic"):
            self.diag = diag.Recorder(job=self.folder.name, source=self.source,
                                      game=self.game, options=options)

        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # ---------------- progress ----------------

    def _set(self, **kw) -> None:
        with self._lock:
            if "step" in kw and kw["step"] != self.step:
                self.step_started = time.time()
            for k, v in kw.items():
                setattr(self, k, v)

    def eta(self) -> int | None:
        """Seconds left, or None when there is nothing honest to say.

        Two sources, in order of trust. Once a step reports progress, its own
        rate is used -- that is measurement, and it accounts for a machine that
        is busy with something else. Before then the estimate comes from the
        measured throughput of the scan mode, which is the only thing known in
        advance. A number that is wrong is worse than no number, so anything
        this cannot reason about returns None.
        """
        with self._lock:
            step, done, total = self.step, self.done, self.total
            begun, clips = self.step_started, self.clip_count
            scan_seconds, mode = self.scan_seconds, self.scan_mode
            rounds = self.scan_rounds
        if self.state not in ("running", "queued"):
            return None
        now = time.time()
        if mode == "summary":
            return self._summary_eta(now)

        after_scan = (clips * CUT_SECONDS_PER_CLIP + MONTAGE_SECONDS
                      if clips else 0.0)
        if step == "scan":
            if done and total and done < total:
                # The scan reports chunks; its own pace is the best guide.
                per = (now - begun) / done
                return int(per * (total - done) + after_scan)
            if scan_seconds:
                rate = scan_rate(mode, rounds)
                left = scan_seconds / rate - (now - begun)
                return int(max(0.0, left) + after_scan)
            return None
        if done and total and done < total:
            per = (now - begun) / done
            return int(per * (total - done))
        return None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            pct = int(100 * self.done / self.total) if self.total else 0
            out = {
                "state": self.state,
                "step": self.step,
                "step_index": STEPS.index(self.step) if self.step in STEPS else 0,
                "done": self.done,
                "total": self.total,
                "percent": max(0, min(100, pct)),
                "message": self.message,
                "error": self.error,
                "game": self.game,
                "folder": str(self.folder),
                "clips": len(self.results),
                "montage": self.montage_path,
                "montage_chapters": self.montage_chapters,
                "match_video": self.summary_path,
                "match_chapters": self.summary_chapters,
                "reel": self.reel_path,
                "promo": self.promo_path,
                "summary": dict(self.summary),
                "preview": list(self.preview),
                "elapsed": int(time.time() - self.started_at),
                "eta": None,          # filled in below, outside the lock
                "source": self.source.name,
                "scan_mode": self.scan_mode,
                # Which match videos this run makes, so the page draws only
                # the steps it will actually take.
                "make": ({"summaries": bool(self.options.get("summaries", True)),
                          "highlights": bool(self.options.get("highlights", True))}
                         if self.scan_mode == "summary" else None),
                "demo_note": self.demo_note,
                "needs_demo": self.needs_demo,
                # Developer Mode only. Empty on every ordinary run, which is
                # what keeps the results card unchanged for everybody else.
                "diagnostic": self.diag_path,
                "diagnostic_run": bool(self.diag.on),
                "demo_file": self.demo.get("demo", "") if self.demo else "",
                # Cancelled but not finished yet: ffmpeg has to be waited on
                # and any chunk already decoding runs to its end.
                "stopping": bool(self.cancel_at
                                 and self.state in ("running", "queued")),
                "stopping_for": (int(time.time() - self.cancel_at)
                                 if self.cancel_at else 0),
            }
        out["eta"] = self.eta()
        return out

    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
            if self.cancel_at is None:
                self.cancel_at = time.time()
            p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _cut_match(self, round_list, info, enc) -> str | None:
        """The whole match, dead time out, with chapters. -> the file.

        THE CUT ITSELF IS `master_segments`, which the Marvel Rivals summary
        already uses and which is proved against real files there. What is
        decided here is which seconds to keep, and that lives in
        clips/match_summary.py where it can be tested without footage.
        """
        from . import match_summary as msum

        spans = msum.spans(round_list, source_duration=info["duration"])
        if len(spans) < 2:
            log.info("not cutting a match summary: %d span(s) is not a match",
                     len(spans))
            return None

        when = datetime.fromtimestamp(
            self.session.get("started") or self.started_at).strftime("%Y-%m-%d")
        about = msum.describe(round_list, spans)
        name = (f"{plan.slug(self.game)}_{when}_match_"
                f"{about['won']}-{about['lost']}_"
                f"{duration_label(about['duration'])}")
        out = cutter.master_segments(
            self.source, spans, name, self.folder / "match", encoder=enc)

        marks = msum.chapters(round_list, spans)
        if marks:
            from .summary import chapter_text

            text = chapter_text(marks)
            Path(out).with_suffix(".chapters.txt").write_text(
                text, encoding="utf-8")
            self.summary_chapters = text
        # Through atomic, like every other manifest here: a half-written one
        # is indistinguishable from a complete one to whatever reads it next.
        atomic.write_json(Path(out).with_suffix(".json"), {
            "title": msum.title(self.game, round_list, when),
            "source": str(self.source), **about,
            "chapters": [[round(t, 2), n] for t, n in marks],
        })
        log.info("match summary: %s (%d rounds, %d chapters)",
                 Path(out).name, about["rounds"], len(marks))
        return str(out)

    def _write_chapters(self, out, plans, masters, opt) -> None:
        """Write the montage's YouTube chapters beside it. Never raises.

        A montage without chapters is the feature minus a convenience; a run
        that FAILED because a text file could not be written would be the
        convenience costing the feature.
        """
        try:
            ordered = sorted(zip(plans, masters), key=lambda pm: pm[0].start)
            durations = [media_info(m)["duration"] for _p, m in ordered]
            d = montage.clamp_transition(
                durations, int(opt.get("transition_ms", 500)) / 1000)
            labels = [self._chapter_label(p) for p, _m in ordered]
            marks = montage.chapter_marks(durations, d, labels)
            if not marks:
                log.info("no chapters for this montage: too few clips, or too "
                         "short for YouTube to show any")
                return
            from .summary import chapter_text

            text = chapter_text(marks)
            Path(out).with_suffix(".chapters.txt").write_text(
                text, encoding="utf-8")
            self.montage_chapters = text
            log.info("montage chapters: %d", len(marks))
        except Exception as e:  # noqa: BLE001
            log.info("could not write the montage chapters: %s", e)

    @staticmethod
    def _chapter_label(p) -> str:
        """What one clip is called in the chapter list.

        SAID AS THE MOMENT, not as the file. The filename carries a rank and a
        timestamp because it has to sort on disk; a chapter is read while
        watching, where the only useful thing is what happens next.
        """
        if getattr(p, "labels", None):
            # Counter-Strike's round types: ACE, CLUTCH, PISTOL ROUND.
            what = ", ".join(str(x).replace("_", " ").title() for x in p.labels)
            if getattr(p, "round_number", None):
                return f"Round {p.round_number} - {what}"
            return what
        n = int(getattr(p, "kills", 0) or 0)
        if n <= 0:
            return "Moment"
        return f"{n} kill" + ("s" if n != 1 else "")

    def _check(self) -> None:
        if self._cancel.is_set():
            raise detect.Cancelled("cancelled")

    # ---------------- the work ----------------

    def run(self) -> None:
        """The single entry and exit of a clip run.

        EVERYTHING THE DIAGNOSTIC NEEDS HAPPENS HERE because this is the only
        place that sees every terminal state. The recorder is made current for
        the duration -- that is how tools.run reports ffmpeg exit codes from
        the scan's worker threads without any of them knowing about it -- and
        the report is written in the `finally`, which is reached by the happy
        path, by all five of the handled failures, and by anything unhandled.

        NOTHING HERE MAY FAIL THE JOB. The report is written inside its own
        try, and diag.Recorder.write never raises in the first place; two
        layers, because a diagnostic that breaks the thing it is diagnosing
        is the one outcome that is worse than no diagnostic at all.
        """
        try:
            self._set(state="running")
            if self.diag.on:
                self._begin_diagnostic()
            self._run()
            if self.scan_mode == "summary":
                n = sum(1 for x in self.results if x.get("master"))
                self._set(state="done", step="done", done=self.total,
                          message=f"{n} match video{'' if n == 1 else 's'} "
                                  f"in {self.folder.name}")
            else:
                self._set(state="done", step="montage", done=self.total,
                          message=f"{len(self.results)} clips in {self.folder.name}")
        except NoKills as e:
            # Done, with nothing to cut. The page reads summary.why for a run
            # that planned no clips, so the reason travels there.
            summary = dict(self.summary or {})
            summary["why"] = str(e)
            self._set(state="done", step="done", done=self.total,
                      summary=summary, message=str(e))
            log.info("clip job found nothing to cut: %s", e)
            self.diag.error(e)
        except detect.Cancelled as e:
            self._set(state="cancelled", message="Cancelled")
            log.info("clip job cancelled")
            self.diag.error(e)
        except NeedsDemo as e:
            # Not "failed - see the log": nothing went wrong, the run needs
            # something only the user can supply. The page shows the
            # sharing-code box and the "read the screen anyway" button on
            # this, so it must be distinguishable from a real failure.
            self._set(state="failed", needs_demo=True, error=str(e),
                      message="Waiting for the replay")
            log.info("stopped for a demo: %s", e)
            self.diag.error(e)
        except HudUnread as e:
            # Not "see the log": the reason is the whole message, and it says
            # what to do. Kept apart from NoKills on purpose -- a reader that
            # could not see the HUD must never read as a match with no kills.
            self._set(state="failed", error=str(e),
                      message="Could not see your kill counter")
            log.info("clip job could not read the HUD: %s", e)
            self.diag.error(e)
        except FfmpegMissing as e:
            self._set(state="failed", error=str(e), message="ffmpeg not found")
            log.error("clip job failed: %s", e)
            self.diag.error(e)
        except Exception as e:  # noqa: BLE001
            self._set(state="failed", error=str(e), message="Failed - see the log")
            log.exception("clip job failed: %s", e)
            self.diag.error(e)
        finally:
            self._set(finished_at=time.time())
            self._write_manifest()
            self._finish_diagnostic()

    def _begin_diagnostic(self) -> None:
        """Make this run's recorder current and describe the machine.

        IN ITS OWN TRY, unlike the marks through _run. Those call methods
        that each swallow their own exceptions; this runs ffmpeg three or
        four times -- the encoder list, the hwaccel list and a frame through
        each -- on a machine whose graphics stack is, quite possibly, the
        thing being diagnosed. A probe that hangs up the driver must cost
        the report, not the clips.
        """
        try:
            diag.set_active(self.diag)
            self.diag.stage("0. starting up")
            # Asked for ONCE, up front. A report whose system block was
            # gathered after a forty-minute scan would describe a different
            # machine state from the one the run actually had.
            self.diag.note("system", diag.system_info())
            self.diag.note("disk_out", diag.disk_for(self.folder.parent))
        except Exception as e:                               # noqa: BLE001
            log.warning("the diagnostic could not be started: %s", e)

    def _finish_diagnostic(self) -> None:
        """Close the recorder and write the one report. Never raises.

        Called from run()'s `finally`, so it runs after a success, after each
        handled failure and after an unhandled one -- which is the point: the
        run this exists to explain is the run that did not finish.
        """
        if not self.diag.on:
            return
        try:
            self.diag.note("state", self.state)
            self.diag.note("clips_made", len(self.results))
            self.diag.note("folder", str(self.folder))
            # AT THE END, because what is wanted is the PEAK. A scan holds
            # frames for a thread pool and a reel builds its graph in
            # memory; both are gone by now, and the peak is what answers
            # "did this machine have enough".
            self.diag.note("memory", diag.memory_used())
            self.diag.note("disk_out_after", diag.disk_for(self.folder.parent))
            for kind, where in (("montage", self.montage_path),
                                ("match video", self.summary_path),
                                ("reel", self.reel_path),
                                ("promo", self.promo_path)):
                if where:
                    self.diag.output(kind, where)
            for row in self.results:
                for kind in ("master", "vertical"):
                    if row.get(kind):
                        self.diag.output(kind, row[kind])
            ok = self.state == "done"
            self.diag.end_stages(ok=ok, error="" if ok else (self.error or self.state))
            self.diag.finish(self.state, self.error or "")
            self.diag_path = self.diag.write(paths.LOGS_DIR / "diagnostics")
        except Exception as e:                               # noqa: BLE001
            log.warning("the diagnostic could not be completed: %s", e)
        finally:
            diag.set_active(None)

    def _run(self) -> None:
        self.diag.stage("probe the source")
        if not self.source.exists():
            raise FileNotFoundError(f"recording not found: {self.source}")
        # BEFORE ANYTHING ELSE, AND SEPARATELY FROM THE PROBE BELOW. A file
        # that is there but zero bytes, or still being written, reads as a
        # corrupt-input failure from ffprobe with nothing to say whether the
        # file was the problem or the tool was.
        self.diag.note("source_bytes", self.source.stat().st_size)
        self.diag.note("source_disk", diag.disk_for(self.source.parent))

        opt = self.options
        info = cutter.probe_source(self.source)
        # The codec, resolution and frame rate the whole run is decided by.
        # A report without these cannot answer "does it only happen on AV1"
        # or "does it only happen at 1440p", which are the first two
        # questions anybody asks.
        self.diag.note("source_info", dict(info))
        handle, logo = overlay.branding(opt)

        # ---- 1. find the kills -------------------------------------------
        self.diag.stage("1. find the kills")
        self._set(step="scan", done=0, total=1, message="Looking for kills...")
        prof = profiles.for_game(self.game_key, self.game)
        prof = self._as_asked(prof, opt)
        self.diag.note("profile", getattr(prof, "label", None) or "(none)")
        self.diag.note("scan_mode", getattr(prof, "mode", None) or "(none)")

        # BEFORE ANY DECODING. A killfeed profile reads the feed as text, and
        # the OCR binary was previously discovered inside the scan -- which on
        # a feature-length recording is minutes of work thrown away to arrive
        # at a sentence a directory listing could have produced immediately.
        if prof is not None and getattr(prof, "needs_ocr", False):
            from . import deps

            why = deps.ocr_why_not()
            if why:
                raise RuntimeError(
                    f"{why} Install it from the Clips page - AutoStream can "
                    f"do it for you - then run this again.")

        kills: list[dict] = []
        # ---- the window -------------------------------------------------
        self.diag.stage("1. find the kills - choose the window")
        #
        # WHICH PART OF THE FILE TO READ. One recording routinely holds more
        # than one game -- and a menu, a warm-up and the tail of the previous
        # match besides -- so a file the user picked is not necessarily one
        # session of one game. Chosen on the Clips page against a filmstrip of
        # the file; absent, it is the whole thing and nothing changes.
        #
        # Everything below works in the FILE's clock, not the window's: the
        # scanners return absolute times and the cutter seeks the source, so
        # the window is applied here and then never thought about again.
        total = float(info.get("duration") or 0.0)
        self.win_start, self.win_end = self._window(info)
        self.win_whole = self.win_start <= 0 and self.win_end >= total
        span = self.win_end - self.win_start
        self._set(source_seconds=total,
                  scan_mode=(prof.mode if prof else ""),
                  scan_seconds=span)
        if not self.win_whole:
            log.info("clipping part of %s only: %s to %s of %s",
                     self.source.name, _hms(self.win_start),
                     _hms(self.win_end), _hms(total))

        # A game summarised rather than clipped has nothing below to do with
        # kills -- see clips/rivals.py -- so it takes its own short path.
        if prof is not None and prof.mode == "summary":
            self._summarise(span)
            return

        # Counter-Strike is clipped per ROUND, which needs the scoreboard as
        # well as the feed. Both are read from ONE decode pass -- see
        # killfeed.scan_with_hud -- because decoding is about half the cost of
        # either and doing it twice would add ten minutes for nothing.
        use_rounds = bool(prof and getattr(prof, "rounds", False)
                          and opt.get("rounds", True))
        self._set(scan_rounds=use_rounds)
        round_list: list = []

        # Clips that fall below min_kills. Swept into one promo reel instead of
        # being cut individually -- see clips/promo.py.
        want_promo = bool(opt.get("promo", True))
        spare: list = []

        # Per-game padding floors, applied BEFORE anything is planned. Resolved
        # here rather than inside the planner so session.json records the
        # numbers actually used -- a style name whose meaning changed later
        # would otherwise be the only record of how a clip was cut.
        asked_pre = float(opt.get("pre_roll", 3 if use_rounds else 6))
        asked_tail = float(opt.get("tail_seconds", plan.TAIL_MIN))
        pre_roll, tail = (prof.padding(asked_pre, asked_tail) if prof
                          else (asked_pre, asked_tail))
        if (pre_roll, tail) != (asked_pre, asked_tail):
            log.info("%s needs more room than the %s style asks for: "
                     "run-up %.1f -> %.1fs, tail %.1f -> %.1fs", self.game,
                     opt.get("style", "chosen"), asked_pre, pre_roll,
                     asked_tail, tail)
        opt["pre_roll"], opt["tail_seconds"] = pre_roll, tail

        self.diag.stage("1a. read the kills")
        cached = self._trim_cached(opt.get("kills"))
        if cached is not None:
            opt["kills"] = cached
        # Cached kills are enough for a game that writes a demo even in round
        # mode: what the detector found is only ever the fingerprint that
        # locates the demo, and the rounds come out of the demo itself. Without
        # one, round mode has to rescan -- the scoreboard is only read during a
        # scan and there is nothing else to read it from.
        if cached and (not use_rounds or (prof and prof.demos)):
            self.diag.note("kill_source", "cached from an earlier scan")
            kills = list(cached)
            self._set(message=f"Using {len(kills)} kills found earlier")
        # ---- 1a. the probe ------------------------------------------------
        #
        # THE SCAN ONLY EXISTS TO FIND THE DEMO. Where a demo aligns, every
        # kill and round below is thrown away and taken from it instead -- so
        # reading a whole recording to build a fingerprint that a few minutes
        # would have built is the most expensive thing this job does for the
        # least reason. Reading the feed costs about eleven seconds per minute
        # of video: twenty minutes on a feature-length recording, about one on
        # the probe.
        #
        # Five minutes of kills picked the right demo out of fourteen with
        # every kill aligned and no error, measured. Twelve is used because a
        # recording often opens on a menu, a warm-up, or the tail of the
        # previous match, and those minutes contribute nothing.
        elif (probe := self._probe_for_demo(prof, opt, info)) is not None:
            self.diag.note("kill_source", "replay matched by probe")
            kills, round_list = probe["kills"], probe["rounds"]
            self.demo = probe["about"]
        elif use_rounds and prof.mode == "killfeed":
            # Checked before the scan, not after. Reading the feed without a
            # name to look for finds nothing at all, and "no kills in this
            # recording" after four minutes of scanning is the least useful way
            # possible to say "you have not told me your in-game name".
            self.diag.note("kill_source", "feed and scoreboard (round mode)")
            if not prof.player:
                raise RuntimeError(prof.why_not())
            from . import rounds as rounds_mod

            def prog(d, t):
                self._set(done=d, total=t,
                          message=f"Reading the feed and scoreboard - "
                                  f"{d} of {t} chunks")
            events, readings = killfeed.scan_with_hud(
                self.source, prof.band, prof.player,
                duration=span, start=self.win_start, fps=prof.scan_fps,
                hud_regions=prof.hud_regions or None,
                progress=prog, cancelled=lambda: self._cancel.is_set())
            if self._cancel.is_set():
                raise detect.Cancelled("cancelled")
            round_list = rounds_mod.analyse(readings, events)
            kills = [{"time": e.time, "end": e.end, "score": e.ratio,
                      "count": 1} for e in events if e.kind == "kill"]
            worth = rounds_mod.highlights(round_list,
                                          int(opt.get("min_kills", 2)))
            self._set(message=f"{len(round_list)} rounds, "
                              f"{len(worth)} worth cutting")
        elif prof and prof.exists():
            self.diag.note("kill_source", f"scan ({prof.mode})")

            def prog(d, t):
                self._set(done=d, total=t,
                          message=f"Scanning for kills - {d} of {t} chunks")
            found = detect.scan(self.source, prof, progress=prog,
                                cancelled=lambda: self._cancel.is_set(),
                                duration=span, start=self.win_start)
            # `end` must survive into session.json: the planner reserves its
            # tail from when the marker CLEARED, and without this key it silently
            # falls back to the appearance time and clips cut early again.
            kills = [{"time": k.time, "end": k.end, "score": k.score,
                      "count": k.count} for k in found]
        else:
            raise RuntimeError(
                prof.why_not() if prof else
                f"No kill-marker profile for {self.game}. Calibrate it first "
                f"from the Clips page, or pick a session for a game that has one.")

        if not kills:
            self._set(summary={"kills": 0, "clips": 0, "covered": 0,
                               "coverage": 0, "runtime": 0})
            # SAYS WHAT THIS READER WAS LOOKING FOR. The loudness reader does
            # not look for kills and cannot find one, so "no kills found" from
            # it is a sentence about something nobody asked it to do -- and it
            # hides the thing worth knowing, which is that there was nothing
            # loud enough to be worth a clip.
            if prof is not None and prof.mode == "loudness":
                raise NoKills("Nothing in this recording was loud enough to "
                              "stand out. Lower the threshold on the reading "
                              "step to find quieter moments.")
            raise NoKills("No kills found in this recording.")
        self.diag.note("kills_found", len(kills))

        # ---- 1a2. the match record, if the game keeps one ----------------
        self.diag.stage("1a2. the match record")
        # Before the demo branch: a record that lines up replaces what the
        # detector said INSIDE ITS MATCH, and one that does not costs only the
        # lookup. Valorant is the only game with one today.
        # EVERY MATCH IN THE RECORDING, NOT THE BEST ONE. It used to take the
        # single record that lined up best. A real 70-minute recording held
        # three deathmatches and a competitive match, all four cached and all
        # four lining up; the run used the first deathmatch and cut the other
        # 62 minutes from the feed reader, and the player found seven of those
        # clips wrong by eye -- a 1v4 clutch cut as one 6-second "triple",
        # "double kills" with no kill in them. The competitive record had all
        # seven right.
        # Where the round-based matches are; a kill outside them all is cut in
        # a burst beside the rounds.
        round_spans: list = []
        if prof and getattr(prof, "matches", False) and opt.get("matches", True):
            found = self._from_matches(kills, prof)
            if found:
                from . import valorant_match as vmatch

                kills, round_list, round_spans, outside = vmatch.merge_matches(kills, found)
                self.record_spans = [g["span"] for g in found]
                use_rounds = bool(round_list)
                first = max(found, key=lambda g: len(g["kills"]))
                self.demo = dict(first["about"], outside=outside,
                                 **({"matches": [g["about"] for g in found]}
                                    if len(found) > 1 else {}))
                if outside:
                    log.info("kept %d kill(s) the detector read outside %s",
                             outside, "that match" if len(found) == 1 else
                             f"the {len(found)} matches")

        # ---- 1b. the demo, if the game writes one ------------------------
        self.diag.stage("1b. read the replay")
        #
        # Everything found above is superseded when a demo aligns: exact kill
        # times, exact rounds, and the circumstances no detector can see. What
        # the detector found is kept only as the fingerprint that located it,
        # and as a mark against a right answer.
        # Not when the probe already did it: `kills` are the demo's own by
        # then, so searching again would spend another pass matching the demo
        # against itself.
        # Logged either way. A run once reached the end with no demo and no
        # line explaining why -- every branch inside _from_demo logs, so the
        # only reading left was that it had never been called, and there was
        # nothing in the record to confirm or refute that. A decision this
        # expensive should never be invisible.
        wants_demo = bool(prof and prof.demos and opt.get("demo", True))
        if not wants_demo:
            log.info("not looking for a demo: profile=%s demos=%s option=%s",
                     bool(prof), getattr(prof, "demos", None),
                     opt.get("demo", True))
        elif self.demo:
            log.info("the demo was already found by the probe")
        else:
            got = self._from_demo(kills)
            if got:
                kills, round_list = got["kills"], got["rounds"]
                self.demo = got["about"]
                self._set(demo_note=(
                    "Found Steam's replay of this match, so the kills and "
                    "rounds are exact."))
            else:
                log.info("carrying on with the %d kills the detector found",
                         len(kills))
                # Only if nothing earlier already explained the slow path --
                # the probe's reason is the more useful of the two.
                if not self.demo_note:
                    self._set(demo_note=(
                        "No Steam replay matched this stream, so the kills "
                        "were read off the video. Download the match in "
                        "Counter-Strike and run this again for exact kills "
                        "and proper round names."))

        # ---- 1c. the game's own kill emblem --------------------------------
        self.diag.stage("1c. confirm against the kill emblem")
        # Last, so it checks whatever the kills came from: the feed, a match
        # record or a cache. See killmark for what it is and what it fixed.
        if opt.get("emblems", True):
            kills = self._confirm_by_emblem(kills)
            if not kills:
                self._set(summary={"kills": 0, "clips": 0, "covered": 0,
                                   "coverage": 0, "runtime": 0})
                raise NoKills("No kills found in this recording: none of "
                                   "the kills the feed showed had the game's "
                                   "kill emblem on screen.")

        # ---- 2. decide what to cut ---------------------------------------
        self.diag.stage("2. decide what to cut")
        if use_rounds and not round_list:
            log.info("no round data for this recording; cutting bursts of "
                     "kills instead")
            use_rounds = False
        if use_rounds:
            from . import rounds as rounds_mod

            hl = rounds_mod.highlights(round_list,
                                       int(opt.get("min_kills", 2)))
            wanted = opt.get("round_types")
            if wanted:
                # See rounds.wanted_by: a round with no label is kept because
                # it is being cut on its kill count, and a round whose labels
                # the list has never heard of is kept because a list that
                # cannot offer a thing must not be read as excluding it.
                before = len(hl)
                hl = [r for r in hl
                      if rounds_mod.wanted_by(r.labels, wanted)]
                if before != len(hl):
                    log.info("%d of %d round(s) dropped by the chosen types",
                             before - len(hl), before)
            plans = plan.build_rounds(
                hl, game=self.game,
                pre_roll=pre_roll, tail=tail,
                whole_round=bool(opt.get("whole_round", True)),
                clip_seconds=opt.get("clip_seconds", "auto"),
                source_duration=info["duration"])
            if want_promo:
                # Rounds the player did something in but which earned no label.
                # Individually they are nothing; together they are the advert.
                cutting = {id(r) for r in hl}
                quiet = [r for r in round_list
                         if r.my_kills >= 1 and id(r) not in cutting]
                spare = plan.build_rounds(
                    quiet, game=self.game, pre_roll=pre_roll, tail=tail,
                    whole_round=False, clip_seconds="12",
                    source_duration=info["duration"])
            # Only where the recording also holds a round-based match: a
            # round list read off the screen (Counter-Strike) covers every kill.
            from . import valorant_match as vmatch
            loose = vmatch.loose(kills, round_spans) if round_spans else []
            if loose:
                log.info("cutting %d kill(s) outside the round-based match(es) "
                         "as bursts, beside the rounds", len(loose))
                floor = int(opt.get("min_kills", 2))
                bursts = plan.build(
                    loose, game=self.game, min_kills=floor,
                    clip_seconds=opt.get("clip_seconds", "30"),
                    pre_roll=pre_roll, tail=tail,
                    source_duration=info["duration"])
                plans = plan.combine(plans, bursts, self.game)
                if want_promo:
                    spare = spare + promo.pick(plan.build(
                        loose, game=self.game, min_kills=1,
                        clip_seconds=opt.get("clip_seconds", "30"),
                        pre_roll=pre_roll, tail=tail,
                        source_duration=info["duration"]), floor)
            if not plans:
                raise RuntimeError(
                    f"{len(round_list)} rounds found but none matched the "
                    f"selected highlight types.")
        else:
            floor = int(opt.get("min_kills", 2))
            plans = plan.build(
                kills, game=self.game,
                min_kills=floor,
                clip_seconds=opt.get("clip_seconds", "30"),
                pre_roll=pre_roll, tail=tail,
                source_duration=info["duration"],
            )
            if want_promo:
                # Built as a SECOND pass at min_kills=1 rather than by lowering
                # the first: the clips that are kept must be numbered and named
                # exactly as they would have been without the promo, and
                # filtering a single list would leave gaps in the ranking.
                spare = promo.pick(plan.build(
                    kills, game=self.game, min_kills=1,
                    clip_seconds=opt.get("clip_seconds", "30"),
                    pre_roll=pre_roll, tail=tail,
                    source_duration=info["duration"]), floor)
            if not plans and not spare and not opt.get("marks"):
                raise RuntimeError(
                    f"{len(kills)} kills found, but none in a fight of "
                    f"{opt.get('min_kills', 2)}+ kills. Lower the minimum.")

        # What chat asked for, folded in beside what was detected. Added after
        # both modes so a marked moment survives round filtering and the kill
        # threshold alike -- the point of a mark is that it catches what a
        # detector cannot, including in a game with no profile at all.
        if opt.get("marks"):
            marked = plan.build_marks(
                opt["marks"], game=self.game,
                clip_seconds=opt.get("clip_seconds", "30"),
                source_duration=info["duration"])
            before = len(plans)
            plans = plan.merge_marks(plans, marked)
            log.info("chat asked for %d moment(s); %d were not already found",
                     len(marked), len(plans) - before)

        # Now the plan is known, so the rest of the run can be estimated: a
        # clip costs about the same as any other clip.
        summary = plan.summarise(kills, plans)
        # WHY THERE ARE NO CLIPS, in the run's own words. A finished job that
        # says "0 clips" and nothing else is the most confusing thing this can
        # produce: it found 13 kills, planned nothing because every one of them
        # was a single and the minimum was 2, swept them all into a promo reel,
        # and reported a number that made the whole run look like a failure.
        # Everything needed to explain that was already in hand.
        if not plans:
            floor = int(opt.get("min_kills", 2))
            most = max((int(getattr(p, "kills", 0)) for p in spare), default=0)
            if spare:
                summary["why"] = (
                    f"{len(kills)} kill(s) found, but none of them landed in a "
                    f"burst of {floor} or more — the biggest was {most}. They "
                    f"are all in the promo reel instead. Set the minimum to 1 "
                    f"to cut them one by one.")
            elif use_rounds:
                summary["why"] = ("No round matched the highlight types you "
                                  "chose.")
            else:
                summary["why"] = (
                    f"{len(kills)} kill(s) found, but none reached your "
                    f"minimum of {floor}.")
        self._set(summary=summary, clip_count=len(plans))
        self.folder.mkdir(parents=True, exist_ok=True)
        atomic.write_json(self.folder / "session.json", {
            "source": str(self.source), "game": self.game,
            "game_key": self.game_key, "options": opt,
            # WHAT WAS ACTUALLY READ, recorded separately from the options
            # because the next run reuses these kills and has to know whether
            # they cover the part it cares about. A windowed scan's kill list
            # is complete only inside its window, and reusing it for the whole
            # file would report "no kills" for everything outside it.
            # [0, 0] means the whole file, which is what every run before
            # windows existed did -- so an old sidecar with no key at all
            # reads the same way.
            "scanned": ([0.0, 0.0] if self.win_whole else
                        [round(self.win_start, 1), round(self.win_end, 1)]),
            "kills": kills, "plans": [p.as_dict() for p in plans],
            **({"demo": self.demo} if self.demo else {}),
            **({"emblems": self.emblem_note} if self.emblem_note else {}),
            **({"promo_clips": [p.as_dict() for p in spare]} if spare else {}),
            **({"rounds": [
                {"number": r.number, "start": round(r.started, 1),
                 "end": round(r.ended, 1), "half": r.half,
                 "score": list(r.score_after), "won": r.won,
                 "kills": r.my_kills, "deaths": r.my_deaths,
                 "assists": r.my_assists, "labels": r.labels,
                 "overcount": r.kill_overcount,
                 **({"source": r.source, "reason": r.reason,
                     "flags": r.flags, "headshots": r.headshots}
                    if r.source == "demo" else {})}
                for r in round_list]} if round_list else {}),
        })

        # ---- 2b. stop here if the plan is all that was asked for ---------
        self.diag.stage("2b. plan only - stop before cutting")
        if opt.get("plan_only"):
            marks = self._tags(kills, True)
            said: list[str] = []
            rows = []
            for i, pl in enumerate(plans):
                inside = [k for k in kills
                          if pl.start <= float(k["time"]) <= pl.end]
                extra = sorted({t for k in inside
                                for t in marks.get(float(k["time"]), [])})
                line = voice.line_for(pl, avoid=said)
                if line:
                    said.append(line)
                rows.append({
                    "index": i, "key": clip_key(pl.start),
                    "name": pl.name, "start": round(pl.start, 2),
                    "end": round(pl.end, 2),
                    "duration": round(pl.end - pl.start, 2),
                    "kills": int(getattr(pl, "kills", 0)),
                    "labels": list(getattr(pl, "labels", []) or []),
                    "round": getattr(pl, "round", None),
                    "caption": overlay.caption_for(pl, inside, extra),
                    "voice_line": line,
                    # Where to grab a still from: a moment INTO the clip, not
                    # its first frame, which is the run-up and often a wall.
                    "thumb_at": round(min(pl.end - 0.5,
                                          pl.start + (pl.end - pl.start) * 0.6), 2),
                })
            self._set(preview=rows, step="scan", done=1, total=1,
                      message=f"{len(rows)} clip(s) ready to review")
            data = json.loads((self.folder / "session.json").read_text(
                encoding="utf-8"))
            data["preview"] = rows
            atomic.write_json(self.folder / "session.json", data)
            log.info("plan only: %d clip(s) ready to review", len(rows))
            # Nothing was encoded, so leave nothing behind. The plan itself
            # lives in this job's status, which is what the page reads.
            try:
                for f in self.folder.iterdir():
                    if f.is_file() and f.name in ("session.json", "clips.json"):
                        f.unlink()
                self.folder.rmdir()
            except OSError:
                pass          # something else is in there; leave it alone
            return

        # ---- 3. cut ------------------------------------------------------
        self.diag.stage("3. cut the clips")
        raw_per_clip = opt.get("per_clip") or {}
        per_clip = {str(k): v for k, v in raw_per_clip.items()
                    if isinstance(v, dict)}
        if per_clip:
            log.info("%d clip(s) carry their own caption or voice settings",
                     len(per_clip))
        enc = opt.get("encoder", "auto")
        if self.diag.on:
            from .tools import video_codec_args

            self.diag.note("encoder_asked", enc)
            self.diag.note("encoder_used", video_codec_args(enc)[1])
        vmode = opt.get("vertical_mode", "crop")
        want_vertical = vmode not in ("none", "", None)
        want_montage = bool(opt.get("montage", True)) and len(plans) > 1

        steps = len(plans) + (len(plans) if want_vertical else 0) + (1 if want_montage else 0)
        self._set(step="cut", done=0, total=steps)
        self.diag.note("clips_planned", len(plans))
        self.diag.note("vertical", vmode if want_vertical else "none")
        self.diag.note("montage", bool(want_montage))

        masters: list[Path] = []
        n = 0
        for p in plans:
            self._check()
            self._set(message=f"Cutting clip {p.rank} of {len(plans)} "
                              f"({p.kills} kills)")
            m = cutter.master(self.source, p, self.folder / "clips", encoder=enc)
            self.diag.event("cut a clip", rank=p.rank, kills=p.kills,
                            start=round(p.start, 2),
                            seconds=round(p.end - p.start, 2), file=str(m))
            masters.append(m)
            n += 1
            self._set(done=n)
            self.results.append({
                **p.as_dict(),
                "master": str(m),
                "vertical": None,
            })

        # ---- 4. vertical -------------------------------------------------
        self.diag.stage("4. vertical copies, captions and voice")
        if want_vertical:
            self._set(step="vertical")
            # Tag detection runs once for the whole session, at the kill
            # timestamps already known -- a few dozen frames, not the whole
            # recording.
            marks = self._tags(kills, bool(opt.get("captions", True)))

            for i, m in enumerate(masters):
                self._check()
                self._set(message=f"Vertical {i + 1} of {len(masters)}")
                v = cutter.vertical(m, self.folder / "vertical", mode=vmode,
                                    encoder=enc)
                # THE SPEECH IS SYNTHESISED BEFORE THE OVERLAY, not after.
                # The subtitle has to fade out when the voice stops saying it,
                # so its timing is only known once the line exists -- and doing
                # it in this order also encodes the clip ONCE: the overlay pass
                # burns everything, and the audio mix afterwards copies the
                # video straight through.
                # WHAT THIS CLIP WAS TOLD TO DO, if anything. Reviewing the
                # plan lets each clip be given its own caption, its own spoken
                # line, its own voice, or none of them -- so the switches in
                # the request are only the default for a clip nobody decided
                # about. Keyed on the start time; see clip_key.
                mine = per_clip.get(clip_key(plans[i].start), {})
                spoken, speech = "", None
                if v and bool(mine.get("voice", opt.get("voice"))):
                    # `avoid` is what has already been said in this session.
                    # Two clutches in one reel saying the same sentence is the
                    # one thing a viewer notices immediately.
                    spoken, speech = self._speak(
                        plans[i], v, line=str(mine.get("voice_text") or ""),
                        name=str(mine.get("voice_name") or ""))
                if v and bool(mine.get("caption", opt.get("captions", True))):
                    p = plans[i]
                    inside = [k for k in kills
                              if p.start <= float(k["time"]) <= p.end]
                    extra = sorted({t for k in inside
                                    for t in marks.get(float(k["time"]), [])})
                    cap = (str(mine.get("caption_text") or "").strip()
                           or overlay.caption_for(p, inside, extra))
                    self.results[i]["caption"] = cap
                    self.results[i]["tags"] = extra
                    try:
                        tmp = v.with_suffix(".tmp.mp4")
                        overlay.apply(
                            v, tmp, caption=cap,
                            handle=handle, logo=logo,
                            encoder=enc, subtitle=spoken,
                            subtitle_until=(voice.LEAD_IN + speech.duration
                                            if speech else 0.0))
                        v.unlink(missing_ok=True)
                        tmp.rename(v)
                    except Exception as e:  # noqa: BLE001
                        log.warning("could not caption %s: %s", v.name, e)
                # The hook goes on the VERTICAL, not the master: it flattens
                # the audio tracks a master deliberately keeps, and the
                # vertical is the copy that gets posted. It lands in the
                # run-up, which is the one part of the clip where nothing has
                # happened yet.
                if v and speech:
                    if voice.lay_over(v, speech):
                        self.said.append(spoken)
                        self.results[i]["said"] = spoken
                    speech.path.unlink(missing_ok=True)
                self.results[i]["vertical"] = str(v) if v else None
                n += 1
                self._set(done=n)

        # ---- 5. montage --------------------------------------------------
        self.diag.stage("5. montage")
        if want_montage:
            self._check()
            self._set(step="montage",
                      message=f"Joining {len(masters)} clips into a montage")
            when = datetime.fromtimestamp(
                self.session.get("started") or self.started_at).strftime("%Y-%m-%d")
            total = montage.expected_duration(
                [media_info(m)["duration"] for m in masters],
                montage.clamp_transition(
                    [media_info(m)["duration"] for m in masters],
                    int(opt.get("transition_ms", 500)) / 1000))
            name = plan.montage_name(self.game, plans, when, total)
            # Chronological, NOT by rank. The clips are numbered best-first so
            # the strongest is easy to find on disk, but joining them in that
            # order makes a montage that jumps from the end of the match back
            # to the start. A session reel should play in the order things
            # actually happened.
            ordered = [m for _p, m in sorted(zip(plans, masters),
                                             key=lambda pm: pm[0].start)]
            out = montage.build(
                ordered, self.folder / "montage" / f"{name}.mp4",
                transition=opt.get("transition", "fade"),
                transition_ms=int(opt.get("transition_ms", 500)),
                encoder=enc)
            self.montage_path = str(out)
            # CHAPTERS, BECAUSE A MONTAGE IS THE ONE OUTPUT WITH NO WAY INTO
            # THE MIDDLE OF IT. Forty clips joined into eight minutes, and the
            # good one is somewhere in there. The offsets are the same
            # arithmetic that placed the crossfades, so each chapter lands on
            # the frame its clip starts on.
            self._write_chapters(out, plans, masters, opt)
            n += 1
            self._set(done=n)

        # ---- 5a. the match summary ---------------------------------------
        self.diag.stage("5a. the match summary")
        # OPT-IN, AND ONLY WHERE THE ROUNDS ARE KNOWN. A clip is thirty
        # seconds around a fight; this is the other thing people upload --
        # the whole match in order with the buy time, the walking and the
        # twenty seconds of nothing between rounds taken out.
        #
        # Counter-Strike has the best source material for it in the app: a
        # demo gives exact round starts, ends, scores and labels, so the
        # spans are arithmetic over known numbers rather than a guess at
        # where a round began.
        if opt.get("match_summary") and round_list:
            self._check()
            self._set(step="montage",
                      message=f"Cutting the match: {len(round_list)} rounds")
            try:
                self.summary_path = self._cut_match(round_list, info, enc)
            except Exception as e:  # noqa: BLE001
                # Never fatal. The clips are the job; this is beside them.
                log.warning("could not cut the match summary: %s", e)

        # ---- 5b. the promo -----------------------------------------------
        self.diag.stage("5b. the promo")
        if want_promo and spare:
            self._check()
            self._set(message=f"Sweeping {len(spare)} leftover kill(s) into a "
                              f"promo")
            try:
                got = promo.build(
                    self.source, spare, kills, self.folder,
                    game=self.game,
                    handle=handle, logo=logo,
                    caption=str(opt.get("promo_caption")
                               or "LIVE MOST EVENINGS \U0001F3AE"),
                    encoder=enc, vertical_mode=(vmode if want_vertical else "fit"),
                    transition=opt.get("transition", "fade"),
                    transition_ms=int(opt.get("transition_ms", 400)))
                if got:
                    self.promo_path = str(got)
            except Exception as e:  # noqa: BLE001 - the clips are already cut
                log.warning("could not build the promo: %s", e)

        # ---- 6. the beat-synced reel -------------------------------------
        self.diag.stage("6. the beat-synced reel")
        #
        # Separate from the montage, not a replacement for it: a montage is the
        # session in full with the original audio, and a reel is a short cut to
        # music. The music has to be supplied -- there is no track to default
        # to that would not be someone else's.
        music = str(opt.get("music") or "")
        if music and Path(music).is_file() and len(plans) > 1:
            self._reel(Path(music), plans, kills, enc)

    def _confirm_by_emblem(self, kills: list[dict]) -> list[dict]:
        """Kills moved onto the kill emblem the game draws, for a game that draws one.

        A kill with no emblem is dropped and an emblem with no kill is added,
        unless the player was spectating a team-mate when it rose.

        MEASURED against Riot's records for a 70-minute recording, 76 kills
        outside the one match the run already had a record for: the feed alone
        read 67 of them and 15 kills that never happened. Confirmed by the
        emblem, with the spectated emblems left out, it reads 74 and 4 -- two of
        those 4 show SINGLE KILL on screen and are more likely gaps in a
        deathmatch record. The two it misses are second kills while the first
        emblem was still up.

        Only where no match record covers the recording: a record is Riot's own
        word, and checked against the emblems the second of two record kills
        0.5 s apart -- the start of a 1v4 clutch -- would be dropped, because
        one emblem showed for both.
        Kills that were already confirmed -- a cache from an earlier run that
        did this -- are not read again. A run in which no emblem shows at all
        keeps its kills: the HUD may be hidden.
        """
        from . import killmark
        from .tools import binary

        if killmark.spec_for(self.game) is None or not kills:
            return kills
        spans = [(lo - 5.0, hi + 5.0) for lo, hi in getattr(self, "record_spans", [])]

        def recorded(t: float) -> bool:
            return any(lo <= t <= hi for lo, hi in spans)
        screen = [k for k in kills if not k.get("record") and not recorded(float(k["time"]))]
        if not screen or all(k.get("emblem") for k in screen):
            return kills
        kept = [k for k in kills if k not in screen]
        ff = binary("ffmpeg") or "ffmpeg"

        # The stretches no record covers -- the whole window when there is none.
        gaps, t = [], self.win_start
        for lo, hi in sorted(spans):
            if lo > t:
                gaps.append((t, min(lo, self.win_end)))
            t = max(t, hi)
        if t < self.win_end:
            gaps.append((t, self.win_end))
        gaps = [(a, b) for a, b in gaps if b - a > 1.0]
        total = sum(b - a for a, b in gaps)
        done = [0.0]

        marks: list[float] = []
        for a, b in gaps:
            def prog(d, n, a=a, b=b):
                share = done[0] + (b - a) * d / max(1, n)
                self._set(done=int(share), total=int(total),
                          message=f"Checking kills against the game's kill emblem - "
                                  f"{int(100 * share / max(1.0, total))}%")
            got_marks = killmark.scan(self.source, self.game, start=a, duration=b - a, ff=ff,
                                      progress=prog, cancelled=lambda: self._cancel.is_set())
            if self._cancel.is_set():
                raise detect.Cancelled("cancelled")
            marks += got_marks or []
            done[0] += b - a
        marks.sort()
        if not marks:
            log.info("no kill emblem anywhere in %s; keeping the %d kills as read "
                     "(the HUD may be hidden)", self.source.name, len(kills))
            return kills
        ordered = sorted(screen, key=lambda k: float(k["time"]))
        got, unclaimed = killmark.match([float(k["time"]) for k in ordered], marks)
        theirs = [j for j in unclaimed
                  if killmark.menu(self.source, marks[j], self.game, ff)
                  or killmark.spectating(self.source, marks[j], self.game, ff)]
        out = list(kept)
        for i, j in got.items():
            k = dict(ordered[i])
            k["time"] = k["end"] = marks[j]
            k["count"], k["emblem"] = 1, True
            out.append(k)
        added = [j for j in unclaimed if j not in theirs]
        for j in added:
            out.append({"time": marks[j], "end": marks[j], "score": 1.0, "count": 1,
                        "emblem": True})
        out.sort(key=lambda k: k["time"])
        log.info("kill emblems: %d on screen, %d of %d kills confirmed and moved onto "
                 "them, %d dropped with no emblem, %d missed kills added, %d left out "
                 "as a team-mate's seen while spectating or an agent-select ring", len(marks), len(got),
                 len(screen), len(screen) - len(got), len(added), len(theirs))
        self.emblem_note = {"emblems": len(marks), "confirmed": len(got),
                            "dropped": len(screen) - len(got), "added": len(added),
                            "spectating": len(theirs)}
        # Into the diagnostic too. An outside user's Valorant report said 36
        # kills found and then cut clips holding 60 between them, and nothing
        # in it said where the other 24 came from -- these numbers were only
        # in the app's log, which is not what gets sent back.
        self.diag.note("emblem_check", dict(self.emblem_note,
                                            kills_before=len(kills),
                                            kills_after=len(out)))
        return out

    def _from_matches(self, kills: list[dict], prof) -> list[dict]:
        """Valorant's own record of every match in this recording that is
        cached and lines up with what the detector found, oldest first.

        -> [{"kills", "rounds", "span", "about"}]. Never raises: the pixel
        reader has already produced a usable answer by this point, and this is
        only ever an improvement on it.
        """
        from . import valorant_match as vmatch

        started = self._source_started()
        if not started:
            log.info("no start time for this recording, so its Valorant match "
                     "record cannot be found")
            return []
        found = vmatch.for_recording(started, self.source_seconds)
        # WHILE THE CLIENT IS OPEN, ASK IT. Records are collected while the
        # daemon runs; a recording made while AutoStream was closed has none on
        # disk, yet the client still lists its matches.
        if vmatch.valorant_api.available():
            try:
                if vmatch.collect(limit=10):
                    found = vmatch.for_recording(started, self.source_seconds)
            except Exception as e:                     # noqa: BLE001
                log.info("could not ask the Valorant client for match records: %s", e)
        if not found:
            state = vmatch.state(started, self.source_seconds)
            log.info("no Valorant match record for this recording (%s)",
                     state.get("why") or "none cached")
            return []

        vod = sorted(float(k["time"]) for k in kills)
        out: list[dict] = []
        for m in found:
            puuid = vmatch.puuid_of(m, getattr(prof, "player", "") or "")
            if not puuid:
                log.info("match %s: cannot tell which player is you, so its "
                         "record is unusable", m.id[:8])
                continue
            sync = vmatch.align(m, puuid, started, vod)
            if not sync.ok:
                log.info("match %s does not line up: %s", m.id[:8], sync.why)
                continue
            got_kills = vmatch.kills_from(m, puuid, sync)
            if not got_kills:
                log.info("match %s lined up but reports no kills by you", m.id[:8])
                continue
            got_rounds = vmatch.rounds_from(m, puuid, sync)
            log.info("Valorant match %s (%s): %d kill(s) and %d round(s) from "
                     "Riot's own record, %s", m.id[:8], m.mode or "?",
                     len(got_kills), len(got_rounds), sync.why)
            out.append({
                "kills": got_kills,
                "rounds": got_rounds,
                "span": vmatch.span_of(m, sync),
                "about": {"match": m.id, "mode": m.mode, "ranked": m.ranked,
                          "offset": round(sync.offset, 2),
                          "matched": sync.matched, "total": sync.total,
                          "how": sync.why},
            })
        return out

    def _tags(self, kills, wanted: bool) -> dict[float, list[str]]:
        """Kill circumstances read off the frames, for the captions.

        A few dozen frames at the kill timestamps already known, not the whole
        recording. Never worth failing a run over: a caption without its tags
        is still a caption.
        """
        if not wanted:
            return {}
        try:
            marks = overlay.detect_tags(
                self.source, [float(k["time"]) for k in kills],
                self.game_key, self.game)
            if marks:
                log.info("tagged %d kill(s): %s", len(marks),
                         sorted({t for v in marks.values() for t in v}))
            return marks
        except Exception as e:  # noqa: BLE001
            log.warning("tag detection failed: %s", e)
            return {}

    def _speak(self, plan, clip: Path, *, line: str = "", name: str = ""):
        """The hook for one clip, synthesised but not yet mixed in.

        -> (what it says, the Speech) or ("", None). Split out from the mixing
        because the subtitle needs the line and its duration BEFORE the overlay
        pass runs, and because a failure here must cost the hook and not the
        clip.
        """
        name = name or str(self.options.get("voice_name") or voice.VOICE)
        # A line typed for THIS clip wins over anything generated, and is not
        # held to `avoid`: if someone wrote the same sentence twice they meant
        # it, and silently dropping their words would be worse than a repeat.
        said = line.strip() or voice.line_for(plan, avoid=self.said)
        if not said:
            return "", None
        if not voice.available():
            log.info("no spoken hook: %s", voice.why_not())
            return "", None
        try:
            speech = voice.say(said, clip.with_suffix(".hook.wav"), voice=name)
        except Exception as e:  # noqa: BLE001
            log.warning("could not say %r: %s", said, e)
            return "", None
        log.info("%s: %s says %r (%.1fs)", clip.name, name, said,
                 speech.duration)
        return said, speech

    def _reel(self, music: Path, plans, kills, encoder: str) -> None:
        """Cut a beat-synced reel to a supplied track. Never fatal.

        Last, deliberately: it is the one output that depends on a file the
        user chose, and a missing or unreadable track must not cost the clips
        that are already on disk.
        """
        from . import beatsync

        try:
            self._set(step="montage", message=f"Reading {music.name}")
            track = beatsync.analyse(music)
            if not track.beats:
                log.info("no beat grid in %s; no reel", music.name)
                return
            arc = bool(self.options.get("arc", True))
            self._set(message=f"Cutting a {track.bpm:.0f} BPM reel"
                              + (" as a story" if arc else ""))
            out = self.folder / "montage" / f"{plan.slug(self.game)}_reel.mp4"
            got = beatsync.render(self.source, plans, kills, track, out,
                                  encoder=encoder, arc=arc,
                                  order=str(self.options.get("order")
                                            or "story"))
            if got:
                self.reel_path = str(got)
                self._set(message=f"Reel: {got.name}")
        except Exception as e:  # noqa: BLE001 - the clips are already cut
            log.warning("could not cut a reel to %s: %s", music.name, e)

    # Generous: the whole replays folder parses in about twenty seconds, so
    # anything past this is stuck rather than slow.
    DEMO_TIMEOUT = 240.0

    # How much of the recording to read before trying the demos. Generous
    # against the five minutes that proved sufficient against fourteen real
    # demos, because a recording often opens on a menu, a warm-up, or the tail
    # of the previous match, and those minutes contribute nothing.
    PROBE_SECONDS = 12 * 60.0

    # HOW MANY TIMES THE PROBE MAY TRY AGAIN, WIDER, before giving up.
    #
    # Twelve minutes is enough when the match is under them and useless when it
    # is not. Measured on a real failure: the chosen window began at 20m22s,
    # the match's first kill was at 31m14s, and the probe read the eleven
    # minutes of nothing in between -- one of the demo's sixteen kills fell
    # inside it, the fingerprint had nothing to work with, and the run stopped
    # asking for a replay that was sitting on disk. Reading twelve more minutes
    # would have covered NINE of them.
    #
    # Three windows is 36 minutes of footage, about 8 minutes of work at the
    # kill-feed rate, against 92 for reading the 111-minute recording whole. So
    # widening is cheap in exactly the case it is needed, and it stops well
    # short of the full read it exists to avoid.
    PROBE_TRIES = 3

    # The shortest window worth honouring. Below this there is not room for a
    # clip plus its run-up and tail, so a selection that small is a slip of the
    # hand rather than an instruction.
    MIN_WINDOW = 30.0

    def _window(self, info: dict) -> tuple[float, float]:
        """The part of the file to read. -> (start, end) in the file's clock.

        Sanitised rather than trusted: a window that is backwards, negative,
        past the end, or too short to hold a clip is treated as no window at
        all. Getting this wrong silently produces "no kills in this recording"
        for a file that is full of them, which is the least debuggable failure
        this job has.
        """
        total = float(info.get("duration") or 0.0)
        try:
            a = float(self.options.get("scan_start") or 0.0)
            b = float(self.options.get("scan_end") or 0.0)
        except (TypeError, ValueError):
            return 0.0, total
        if not total:
            return 0.0, 0.0
        a = max(0.0, min(a, total))
        b = total if b <= 0 else max(0.0, min(b, total))
        if b - a < self.MIN_WINDOW:
            if a or b < total:
                log.warning("the chosen part of %s is only %.0fs long, which "
                            "is too short to clip -- reading all of it instead",
                            self.source.name, b - a)
            return 0.0, total
        return a, b

    def _trim_cached(self, cached: list | None) -> list | None:
        """Cached kills, cut down to the window. -> the list, or None.

        A CACHED SCAN COVERS THE WHOLE FILE. Reusing it inside a window would
        plan clips from the part the user deliberately left out -- and the
        cache is keyed on the recording rather than on the window, so this is
        the normal case the second time a file is clipped, not an edge one.
        """
        if not cached or self.win_whole:
            return cached
        kept = [k for k in cached
                if self.win_start <= float(k.get("time") or 0.0) <= self.win_end]
        log.info("%d of %d cached kills are inside the chosen part",
                 len(kept), len(cached))
        return kept

    def _as_asked(self, prof, opt: dict):
        """The profile with the reader the user chose, when they chose one.

        WHY THERE IS A CHOICE AT ALL. Counter-Strike read off the screen is
        two passes in one: the kill feed says what you killed, and the
        scoreboard beside it is what turns a round into "1v3 CLUTCH" rather
        than "2 kills". The scoreboard is the whole cost -- measured, 1.2x
        real time against 10x for the kill tally under the crosshair, so a
        48-minute recording is 40 minutes of scanning against 5.

        With a demo none of that matters, because the rounds come from the
        demo and the scan stops after twelve minutes. Without one it is a real
        trade and only the user can make it, so they are asked rather than
        charged 35 extra minutes for labels they may not want.

        cs2_cards.py was written for exactly this and was never reachable: the
        profile sets rounds, rounds force the scoreboard, and nothing could
        say otherwise.
        """
        if prof is None or opt.get("fallback_mode") != "cards":
            return prof
        if not getattr(prof, "demos", False):
            return prof            # only Counter-Strike has the second reader
        import dataclasses

        log.info("reading %s by the kill tally rather than the feed, as asked "
                 "-- kills only, no round labels", prof.label)
        self._set(demo_note=(
            "Counting your kills off the screen. Clips get named by how many "
            "kills are in them — for names like ACE and CLUTCH, use "
            "'Kills and round names' instead."))
        # demos=False as well. "Kill tally only" means the tally and nothing
        # else, but the profile still said Counter-Strike writes demos -- so
        # the run read the cards and then matched them against every replay
        # on disk anyway, about twenty seconds that could only ever replace
        # the reading the user had chosen with a different one.
        return dataclasses.replace(prof, mode="cardcount", rounds=False,
                                   demos=False)

    def _stop_for_demo(self, opt: dict, why: str, total: float) -> None:
        """Refuse to read the screen instead, unless asked to. Raises.

        Falls through silently only when `demo_fallback` says the user has
        chosen the screen with their eyes open -- which the page offers as a
        button beside the sharing-code box, with the cost on it.
        """
        if opt.get("demo_fallback"):
            self._set(demo_note=why + " Reading the screen instead, as asked.")
            # THE ESTIMATE STARTS AGAIN HERE. The probe and the demo search
            # are not chunks, and leaving their minutes inside the per-chunk
            # average made the first estimate of the full scan about a fifth
            # too pessimistic -- measured on a 111-minute recording: 13m24s
            # claimed against 10m54s actual. Reading the whole file is new
            # work, so it is timed as such.
            self._set(scan_seconds=total, step_started=time.time(),
                      done=0, total=1)
            return
        self._set(demo_note=why)
        raise NeedsDemo(why)

    # ---- the probe's own kills, kept ----------------------------------
    #
    # THE WHOLE POINT IS THE SECOND RUN. The probe costs about nine minutes on
    # a long recording, and the answer to "no replay matched" is to download
    # the replay and go again -- at which point the seed the first probe built
    # is exactly what the search needs and paying for it twice is pure waste.
    # Keyed on the source AND the window start, because a probe of a different
    # part of the file is a different seed.

    def _remember_probe(self, seed: list, seconds: float) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            atomic.write_json(self.folder / "probe.json", {
                "source": str(self.source),
                "start": round(self.win_start, 1),
                "seconds": round(seconds, 1),
                "kills": seed,
            })
        except OSError as e:
            log.info("could not keep the probe's kills: %s", e)

    def _recall_probe(self, seconds: float) -> list | None:
        want = str(self.source).lower()
        try:
            saved = sorted(self.folder.parent.glob("*/probe.json"),
                           key=lambda f: f.stat().st_mtime, reverse=True)
        except OSError:
            return None
        for f in saved:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if str(d.get("source") or "").lower() != want:
                continue
            if abs(float(d.get("start") or 0) - self.win_start) > 1.0:
                continue
            # A shorter probe than this run wants is not enough to reuse.
            if float(d.get("seconds") or 0) + 1 < seconds:
                continue
            kills = d.get("kills") or []
            if kills:
                log.info("reusing the %d kills a previous probe of this file "
                         "already found", len(kills))
                return kills
        return None

    def _probe_for_demo(self, prof, opt: dict, info: dict) -> dict | None:
        """Read a few minutes, then take the whole match from the demo it finds.

        -> the same shape as _from_demo, or None to fall back to a full scan.
        Never raises past Cancelled: a probe that cannot answer must cost the
        run nothing beyond the minutes it spent.
        """
        from . import cs2_demo, detect

        if not (prof and prof.demos and opt.get("demo", True)):
            return None
        if opt.get("kills"):
            return None                 # a cached scan is already free
        # The window, not the file: the probe reads the FIRST few minutes of
        # whatever is being clipped, and on a file holding two games the first
        # few minutes of the file can be the other one.
        total = (self.win_end or float(info.get("duration") or 0)) - self.win_start
        if total <= self.PROBE_SECONDS * 1.5:
            return None                 # short enough that a full read is cheap
        folder = cs2_demo.demo_folder(str(opt.get("demo_folder") or ""))
        if not folder:
            return None

        # A demo cannot record a match played after it was written. Reading
        # twelve minutes to search a folder whose newest demo predates the
        # recording is time spent proving something a directory listing
        # already knew -- it cost 2.2 minutes on a recording made two days
        # after the last demo, and then the whole file was read anyway.
        #
        # The recording's own start is taken from OBS's filename stamp rather
        # than the file's mtime, which is when WRITING FINISHED and would make
        # a long recording look newer than it is.
        newest = cs2_demo.newest_demo_time(folder)
        started = self._source_started()
        if newest is not None and started is not None and newest < started:
            log.info("no demo newer than this recording (the last one was "
                     "written %.1f hours before it started), so there is "
                     "nothing to search for", (started - newest) / 3600.0)
            self._stop_for_demo(
                opt,
                "No replay on disk is newer than this recording, so there is "
                "none that could belong to it.",
                total)
            return None

        def prog(d, t):
            self._set(done=d, total=t,
                      message=f"Reading a few minutes to find the match - "
                              f"{d} of {t} chunks")
        # The probe reads a window, not the recording, which changes the
        # estimate by an order of magnitude on a two-hour stream.
        # WIDER, NOT LONGER. Each attempt reads the NEXT twelve minutes and
        # adds to the seed, so nothing is read twice and a match that starts
        # late is reached without paying for the whole recording.
        seed: list = []
        read = 0.0
        got = None
        for attempt in range(1, self.PROBE_TRIES + 1):
            window = min(self.PROBE_SECONDS * attempt, total)
            if window <= read:
                break
            self._set(scan_seconds=window)

            # An earlier probe of this same stretch already built the seed. The
            # usual way to reach here twice is "no replay matched" -> download
            # it -> run again, and re-reading the same twelve minutes to
            # rebuild an identical list is nine minutes spent to learn nothing.
            recalled = self._recall_probe(window) if attempt == 1 else None
            if recalled is not None:
                seed = recalled
                read = window
                self._set(message=f"Using the {len(seed)} kills a previous run "
                                  f"already read from these minutes")
            else:
                if attempt > 1:
                    self._set(message=f"Reading {(window - read) / 60:.0f} more "
                                      f"minutes to find the match",
                              step_started=time.time(), done=0, total=1)
                try:
                    found = detect.scan(
                        self.source, prof, progress=prog,
                        cancelled=lambda: self._cancel.is_set(),
                        duration=window - read, start=self.win_start + read)
                except detect.Cancelled:
                    raise
                except Exception as e:  # noqa: BLE001
                    log.info("the probe scan failed (%s); reading the whole "
                             "recording", e)
                    self._set(scan_seconds=total)
                    return None
                if self._cancel.is_set():
                    raise detect.Cancelled("cancelled")
                seed = seed + [{"time": k.time, "end": k.end, "score": k.score,
                                "count": k.count} for k in found]
                read = window
                self._remember_probe(seed, window)

            if len(seed) < 3:
                log.info("only %d kill(s) in the first %.0f minutes",
                         len(seed), read / 60)
                continue                  # a wider window may find some
            got = self._from_demo(seed)
            if got:
                break
            log.info("no demo matched the first %.0f minutes (%d kills)",
                     read / 60, len(seed))

        if len(seed) < 3:
            self._stop_for_demo(
                opt,
                f"Only {len(seed)} kill(s) in the first {read / 60:.0f} "
                f"minutes of what you chose - too few to identify the match. "
                f"If the selection starts on a menu or a warm-up, drag the "
                f"start handle to where the play begins.",
                total)
            return None

        if not got:
            log.info("no demo matched the first %.0f minutes; reading the whole "
                     "recording", self.PROBE_SECONDS / 60)
            self._stop_for_demo(
                opt,
                f"Read {read / 60:.0f} minutes and found {len(seed)} kills, and "
                f"no replay on disk matched them. The replay for THIS match is "
                f"probably not downloaded yet - the ones that are belong to "
                f"other matches.",
                total)
            # THE ESTIMATE STARTS AGAIN HERE. The probe and the demo search are
            # not chunks, and leaving their minute and three quarters inside the
            # per-chunk average made the first estimate of the full scan about a
            # fifth too pessimistic -- measured on a 111-minute recording:
            # 13m24s claimed against 10m54s actual, converging only near the
            # end. Reading the whole file is new work, so it is timed as such.
            self._set(scan_seconds=total,
                      step_started=time.time(), done=0, total=1)
            return None
        log.info("the demo was found from the first %.0f minutes, so the rest of "
                 "the recording did not need reading", self.PROBE_SECONDS / 60)
        self._set(demo_note=(
            f"Found Steam's replay in the first {self.PROBE_SECONDS / 60:.0f} "
            f"minutes, so the rest did not need watching. Your kills and "
            f"rounds are exact."))
        return got

    def _source_started(self) -> float | None:
        """When the recording began, by OBS's own filename stamp.

        Falls back to the file's modification time LESS ITS DURATION, because
        mtime is when writing FINISHED. That subtraction is the whole story for
        a file this app did not record. Without it a 43-minute video dropped in
        by hand looks 43 minutes newer than it is, so `for_recording` searches a
        window opening after the match ended -- and EDGE_SLACK is 90 seconds, so
        it finds NOTHING, however good the cached record is. The same shift
        rejects every CS2 demo written during the recording as "written before
        the match started".

        The Clips page already subtracted it when probing the file, which is
        the worst version of this: the page said the record was there and the
        job then went looking with a different number and did not find it.
        """
        from .. import history

        stamp = history._started_from_name(str(self.source))  # noqa: SLF001
        if stamp is not None:
            return stamp
        try:
            return self.source.stat().st_mtime - max(0.0, self.source_seconds)
        except OSError:
            return None

    def _from_demo(self, kills: list[dict]) -> dict | None:
        """Counter-Strike rounds and kills from Valve's own record of the match.

        The detector's kill times go in as a FINGERPRINT -- see
        cs2_demo.align -- so a detector that missed one or invented two costs
        nothing beyond the search, and the demo then says exactly what it got
        right. Returns None whenever anything is missing or does not line up:
        a wrong alignment mis-cuts every clip in the match, so it must refuse
        rather than shift.
        """
        from . import cs2_demo
        from . import rounds as rounds_mod

        folder = cs2_demo.demo_folder(str(self.options.get("demo_folder") or ""))
        if not folder:
            log.info("no CS2 replays folder found, so the rounds have to come "
                     "off the screen")
            return None
        vod = sorted(float(k["time"]) for k in kills)
        self._set(message="Looking for this match in your demos...")
        # ON ITS OWN THREAD, WITH A DEADLINE. The demo search reads other
        # people's files through a native parser: fourteen demos take about
        # twenty seconds here, but a corrupt or half-written one is not this
        # code's to survive, and a clip job that hangs in it hangs forever --
        # the step reports no progress, the job never fails, and the only way
        # out is killing the app and losing the scan that already succeeded.
        # That happened, for twenty-five minutes, at two percent of one core.
        #
        # Rounds off the screen are the documented fallback, so giving up here
        # costs quality rather than the run.
        got: dict = {}

        def search():
            try:
                # WHEN the recording was made, so the search can ask which
                # match was played during it before asking which one its kills
                # resemble. Counter-Strike writes that time beside every demo
                # and it was going unread -- see cs2_demo.match_time.
                got["r"] = cs2_demo.pick_demo(
                    folder, vod,
                    started=self._source_started(),
                    seconds=self.source_seconds or 0.0)
            except RuntimeError as e:      # demoparser2 not installed
                got["skip"] = str(e)
            except Exception as e:         # noqa: BLE001
                got["skip"] = f"the demo search failed: {e}"
            except BaseException as e:     # noqa: BLE001
                # NOT redundant. demoparser2 is a Rust extension, and pyo3
                # raises PanicException, which derives from BaseException --
                # so `except Exception` let it kill this thread in silence.
                # The packaged build shipped without polars/pyarrow/pandas and
                # every CS2 demo search died here, instantly and invisibly,
                # for as long as the demo path has existed.
                got["skip"] = (f"the demo reader crashed ({type(e).__name__}: "
                               f"{str(e)[:200]}); reading the rounds off the "
                               f"screen instead")

        worker = threading.Thread(target=search, name="autostream-demo",
                                  daemon=True)
        t0 = time.time()
        worker.start()
        worker.join(self.DEMO_TIMEOUT)
        if worker.is_alive():
            log.warning("the demo search has taken over %ds; falling back to "
                        "reading the rounds off the screen", self.DEMO_TIMEOUT)
            return None
        if "skip" in got:
            log.info("%s", got["skip"])
            return None
        match, who, sync = got.get("r") or (None, "", None)
        if sync is None:
            # Added logging to this method precisely so a run could not end
            # with no demo and no reason, and then left this path silent.
            # It then happened anyway, above, and this said nothing useful --
            # so say what was actually on the table.
            try:
                count = len(list(Path(folder).glob("*.dem")))
            except Exception:              # noqa: BLE001
                count = -1
            log.warning("the demo search returned nothing at all after %.0fs "
                        "(%d demo file(s) in %s, %d kill(s) to match) -- the "
                        "worker died without reporting why",
                        time.time() - t0, count, folder, len(vod))
            return None
        if not match or not sync.ok:
            log.info("no demo in %s fits this recording (%s)", folder,
                     sync.why)
            return None

        mine = match.by(who)
        about = {
            "demo": match.path.name, "map": match.map_name, "player": who,
            "offset": round(sync.offset, 2), "rate": round(sync.scale, 6),
            **cs2_demo.audit([k.time for k in mine], vod, sync),
        }
        log.info("demo %s (%s): you are %s, %s", match.path.name,
                 match.map_name, who, sync.why)
        log.info("the detector scored %d of %d, missing %d and inventing %d",
                 about.get("matched", 0), about.get("demo_kills", 0),
                 about.get("missed", 0), about.get("invented", 0))

        rounds = rounds_mod.from_demo(match, who, sync)
        # `end` is the kill itself: a demo records the moment, not how long the
        # game drew something about it, and the planner's tail is measured from
        # there -- see plan.TAIL_MIN and the profile's tail_min.
        exact = [{"time": round(sync.to_vod(k.time), 3),
                  "end": round(sync.to_vod(k.time), 3),
                  "score": 1.0, "count": 1,
                  "round": k.round,
                  **({"tags": _kill_tags(k)} if _kill_tags(k) else {})}
                 for k in mine]
        self._set(message=f"{match.map_name}: {len(rounds)} rounds and "
                          f"{len(exact)} kills, exactly")
        return {"kills": exact, "rounds": rounds, "about": about}

    # ------------------------------------------------ Marvel Rivals

    # What is left after the read, before the read has said how many matches
    # there are: seconds of work per second of recording, for each kind of
    # video. From the measured runs -- a 38-minute recording, a third of it
    # menus, took 212 s after its read for the summaries and 208 s more for
    # the highlights; an 11-minute window that was all match took 137 s and
    # 123 s. Somewhere between, for a typical recording.
    AFTER_READ = {"summaries": 0.10, "highlights": 0.10}

    def _summary_eta(self, now: float) -> int | None:
        """Seconds left for a match-video run, or None before anything is known.

        While reading: the read's own pace for what is left of it, plus a
        per-second-of-recording guess at the cutting. After: the cost of every
        video still to make (clips/summary.py), scaled by how the videos
        already made compared with their estimate -- a busy PC corrects it.
        """
        with self._lock:
            step, done, total = self.step, self.done, self.total
            begun = self.step_started
            sm = dict(self.sm)
        if step == "scan":
            if not total:
                return None
            left_read = None
            if done > 0:
                left_read = (now - begun) / done * max(0, total - done)
            elif self.scan_seconds:
                left_read = total / scan_rate("summary") - (now - begun)
            if left_read is None:
                return None
            after = self.scan_seconds * sum(
                rate for kind, rate in self.AFTER_READ.items() if sm.get(kind, True))
            return int(max(0.0, left_read) + after)
        cost_total = sm.get("total") or 0.0
        if not cost_total:
            return None
        cost_done = sm.get("done") or 0.0
        spent = sm.get("spent") or 0.0
        ratio = spent / cost_done if cost_done > 1 and spent > 1 else 1.0
        ratio = min(4.0, max(0.25, ratio))
        in_unit = now - (sm.get("unit_at") or now)
        unit = sm.get("unit") or 0.0
        left = (cost_total - cost_done - unit) * ratio + max(0.0, unit * ratio - in_unit)
        return int(max(0.0, left))

    def _summarise(self, span: float) -> None:
        """Marvel Rivals: match videos instead of clips around kills."""
        from . import rivals, summary

        if self.options.get("plan_only"):
            raise RuntimeError(
                f"{self.game} is made into match videos, which have no clips "
                f"to review first. Use Make match videos.")
        want_summaries = bool(self.options.get("summaries", True))
        want_highlights = bool(self.options.get("highlights", True))
        if not (want_summaries or want_highlights):
            raise RuntimeError("Nothing to make: choose a summary, a highlight, or both.")
        with self._lock:
            self.sm = {"summaries": want_summaries, "highlights": want_highlights}

        def prog(read, total):
            self._set(done=int(read), total=max(1, int(total)),
                      message=f"Reading the HUD - {_mmss(read)} of {_mmss(total)} read")
        self._set(step="scan", done=0, total=max(1, int(span)),
                  message="Reading the HUD...")
        cache = Path(self.folder).parent / ".cache" / "rivals"
        r, reused = rivals.cached_scan(
            self.source, cache, start=self.win_start, duration=span,
            progress=prog, cancelled=lambda: self._cancel.is_set())
        self._check()
        if reused:
            self._set(message="Using the HUD reading from an earlier run")
        if not rivals.hud_found(r):
            raise RuntimeError(
                f"No {self.game} HUD found in this part of the recording. It reads "
                f"the HUD at the game's default scale on a 16:9 recording, so a "
                f"different HUD scale or a stretched resolution will not read -- "
                f"and neither will a stretch with no match in it.")
        found = rivals.matches(r)
        if not found:
            self._set(summary={"matches": 0, "clips": 0})
            raise RuntimeError(
                f"The {self.game} HUD is in this part of the recording, but no "
                f"whole match is. A match needs at least three minutes of play; "
                f"widen the part you chose if it cuts one short.")
        self._set(clip_count=len(found))
        self.folder.mkdir(parents=True, exist_ok=True)
        # WHAT THIS RUN WAS, for the next visit to the page: the stream list
        # says "made before" from a run's session.json, and without one these
        # runs were invisible to it -- the same recording could be made into
        # the same videos again with nothing on screen to say it already had.
        atomic.write_json(self.folder / "session.json", {
            "kind": "match-videos",
            "source": str(self.source), "game": self.game,
            "game_key": self.game_key,
            "window": [round(self.win_start, 2), round(self.win_end, 2)],
            "source_seconds": round(self.source_seconds, 2),
            "recording_seconds": round(self.source_seconds, 2),
            "options": {"summaries": want_summaries, "highlights": want_highlights,
                        "outro": str(self.options.get("outro") or "")},
            "matches": [{"start": round(m.start, 2), "end": round(m.end, 2),
                         "result": m.result, "deaths": len(m.deaths),
                         "ults": len(m.casts), "kos": len(m.all_kos())} for m in found],
        })

        def cut_prog(p):
            now = time.time()
            with self._lock:
                sm = self.sm
                if sm.get("unit_at"):
                    sm["spent"] = sm.get("spent", 0.0) + (now - sm["unit_at"])
                sm.update(total=p["total"], done=p["done"], unit=p["cost"], unit_at=now)
            if p["kind"] == "done":
                return
            n, i = p["matches"], p["match"]
            of = f" of {n}" if n > 1 else ""
            if p["kind"] == "summary":
                self._set(step="cut", done=int(p["done"]), total=int(p["total"]) or 1,
                          message=f"Cutting the summary of match {i}{of} - "
                                  f"{_mmss(p['match_seconds'])} of play down to "
                                  f"{_mmss(p['seconds'])}")
            else:
                self._set(step="highlight", done=int(p["done"]),
                          total=int(p["total"]) or 1,
                          message=f"Making the highlight of match {i}{of} - "
                                  f"{_mmss(p['seconds'])} of fights")
        self._set(step="cut", done=0, total=1, message="Planning the cuts")
        self.results = summary.build(
            self.source, r, self.folder / "summaries", game=self.game,
            when=self.session.get("started") or self.started_at,
            encoder=self.options.get("encoder", "auto"),
            summaries=want_summaries, highlights=want_highlights,
            outro=str(self.options.get("outro") or "") or None,
            progress=cut_prog, check=self._check)
        over = summary.overview(self.results)
        self._set(clip_count=over["videos"], summary={
            **over, "clips": over["videos"], "reused_reading": reused,
        })

    def _write_manifest(self) -> None:
        """A record of what was produced, next to the files themselves."""
        if not self.folder.exists():
            return
        try:
            atomic.write_json(self.folder / "clips.json", {
                "game": self.game,
                "source": str(self.source),
                "state": self.state,
                "error": self.error,
                "summary": self.summary,
                "montage": self.montage_path,
                "montage_chapters": self.montage_chapters,
                "match_video": self.summary_path,
                "match_chapters": self.summary_chapters,
                "reel": self.reel_path,
                "promo": self.promo_path,
                "clips": self.results,
                "finished": self.finished_at,
            })
        except OSError as e:
            log.warning("could not write clips.json: %s", e)


class JobRunner:
    """Holds the one job that may be running, and the last one that finished.

    One at a time on purpose: these saturate the GPU encoder, and two competing
    runs would each take more than twice as long while making the progress bar
    meaningless.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current: ClipJob | None = None
        self.last: ClipJob | None = None

    def busy(self) -> bool:
        with self._lock:
            return self.current is not None and self.current.state in (
                "queued", "running")

    def start(self, job: ClipJob) -> bool:
        with self._lock:
            if self.current is not None and self.current.state in ("queued", "running"):
                return False
            self.current = job
        threading.Thread(target=self._run, args=(job,),
                         name="autostream-clips", daemon=True).start()
        return True

    def _run(self, job: ClipJob) -> None:
        try:
            job.run()
        finally:
            with self._lock:
                self.last = job
                if self.current is job:
                    self.current = None

    def cancel(self) -> bool:
        with self._lock:
            job = self.current
        if job is None:
            return False
        job.cancel()
        return True

    def status(self) -> dict | None:
        with self._lock:
            job = self.current or self.last
        return job.snapshot() if job else None
