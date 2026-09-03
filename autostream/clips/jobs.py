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

from . import (cutter, detect, killfeed, montage, overlay, plan, profiles,
               promo, voice)
from .. import atomic
from .tools import FfmpegMissing, media_info

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
# A demo changes the picture completely: the scan stops after the probe window,
# so only PROBE_SECONDS of the recording is ever read.
SCAN_RATE = {"feedbar": 14.0, "killfeed": 4.5, "cardcount": 10.0,
             "template": 14.0, "colour": 14.0}
DEFAULT_SCAN_RATE = 8.0

# Seconds per clip for everything after the scan: cutting the master, the
# vertical, the caption pass and the voice. Measured across the runs in this
# session at 9-24s a clip depending on length; the mean is what is reported.
CUT_SECONDS_PER_CLIP = 16.0
MONTAGE_SECONDS = 25.0

STEPS = ("scan", "cut", "vertical", "montage")

# Per-clip settings are keyed on the clip's START, to a tenth of a second.
# Not on its index: the list is re-planned between reviewing it and cutting
# it, and a rank can move. Not on its name either -- the name carries the rank.
def clip_key(start: float) -> str:
    return f"{float(start):.1f}"


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

    def __init__(self, source: Path, *, game: str, game_key: str | None,
                 outdir: Path, options: dict, started: float | None = None,
                 session: dict | None = None):
        self.source = Path(source)
        self.game = game or "Session"
        self.game_key = game_key
        self.options = options
        self.session = session or {}
        self.folder = _free_folder(
            Path(outdir), _stamp_folder(started, game, options.get("style")))

        self.state = "queued"          # queued|running|done|failed|cancelled
        self.step = "scan"
        self.done = 0
        self.total = 1
        self.message = "Waiting to start"
        self.error: str | None = None
        self.results: list[dict] = []
        self.montage_path: str | None = None
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
        self.started_at = time.time()
        self.finished_at: float | None = None
        # For the estimate: when the current step began, how long the recording
        # is, and how it is being read. Filled in as the run learns them.
        self.step_started = self.started_at
        self.source_seconds = 0.0
        self.scan_mode = ""
        self.scan_seconds = 0.0        # how much of the recording will be read
        self.clip_count = 0            # known once the plan exists
        self.eta_at: float | None = None
        # The part of the file being read. Settled by _window() once the source
        # has been probed; until then the whole thing, so anything that asks
        # early gets an answer that is true of every run without a window.
        self.win_start = 0.0
        self.win_end = 0.0
        self.win_whole = True

        # When Cancel was pressed. A cancelled scan does not stop at once --
        # the chunks already running finish on their own -- so the page has to
        # be able to say "stopping" rather than leave the last message up
        # looking hung.
        self.cancel_at: float | None = None
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
        if self.state not in ("running", "queued"):
            return None
        now = time.time()

        after_scan = (clips * CUT_SECONDS_PER_CLIP + MONTAGE_SECONDS
                      if clips else 0.0)
        if step == "scan":
            if done and total and done < total:
                # The scan reports chunks; its own pace is the best guide.
                per = (now - begun) / done
                return int(per * (total - done) + after_scan)
            if scan_seconds:
                rate = SCAN_RATE.get(mode, DEFAULT_SCAN_RATE)
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
                "reel": self.reel_path,
                "promo": self.promo_path,
                "summary": dict(self.summary),
                "preview": list(self.preview),
                "elapsed": int(time.time() - self.started_at),
                "eta": None,          # filled in below, outside the lock
                "source": self.source.name,
                "scan_mode": self.scan_mode,
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

    def _check(self) -> None:
        if self._cancel.is_set():
            raise detect.Cancelled("cancelled")

    # ---------------- the work ----------------

    def run(self) -> None:
        try:
            self._set(state="running")
            self._run()
            self._set(state="done", step="montage", done=self.total,
                      message=f"{len(self.results)} clips in {self.folder.name}")
        except detect.Cancelled:
            self._set(state="cancelled", message="Cancelled")
            log.info("clip job cancelled")
        except FfmpegMissing as e:
            self._set(state="failed", error=str(e), message="ffmpeg not found")
            log.error("clip job failed: %s", e)
        except Exception as e:  # noqa: BLE001
            self._set(state="failed", error=str(e), message="Failed - see the log")
            log.exception("clip job failed: %s", e)
        finally:
            self._set(finished_at=time.time())
            self._write_manifest()

    def _run(self) -> None:
        if not self.source.exists():
            raise FileNotFoundError(f"recording not found: {self.source}")

        opt = self.options
        info = cutter.probe_source(self.source)

        # ---- 1. find the kills -------------------------------------------
        self._set(step="scan", done=0, total=1, message="Looking for kills...")
        prof = profiles.for_game(self.game_key, self.game)

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

        # Counter-Strike is clipped per ROUND, which needs the scoreboard as
        # well as the feed. Both are read from ONE decode pass -- see
        # killfeed.scan_with_hud -- because decoding is about half the cost of
        # either and doing it twice would add ten minutes for nothing.
        use_rounds = bool(prof and getattr(prof, "rounds", False)
                          and opt.get("rounds", True))
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

        cached = self._trim_cached(opt.get("kills"))
        if cached is not None:
            opt["kills"] = cached
        # Cached kills are enough for a game that writes a demo even in round
        # mode: what the detector found is only ever the fingerprint that
        # locates the demo, and the rounds come out of the demo itself. Without
        # one, round mode has to rescan -- the scoreboard is only read during a
        # scan and there is nothing else to read it from.
        if cached and (not use_rounds or (prof and prof.demos)):
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
            kills, round_list = probe["kills"], probe["rounds"]
            self.demo = probe["about"]
        elif use_rounds and prof.mode == "killfeed":
            # Checked before the scan, not after. Reading the feed without a
            # name to look for finds nothing at all, and "no kills in this
            # recording" after four minutes of scanning is the least useful way
            # possible to say "you have not told me your in-game name".
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
            raise RuntimeError("No kills found in this recording.")

        # ---- 1a2. the match record, if the game keeps one ----------------
        # Before the demo branch and on the same terms: a record that lines up
        # replaces everything the detector said, and one that does not costs
        # only the lookup. Valorant is the only game with one today.
        if prof and getattr(prof, "matches", False) and opt.get("matches", True):
            got = self._from_match(kills, prof)
            if got:
                kills = got["kills"]
                round_list = got["rounds"]
                use_rounds = bool(round_list)
                self.demo = got["about"]

        # ---- 1b. the demo, if the game writes one ------------------------
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
            else:
                log.info("carrying on with the %d kills the detector found",
                         len(kills))

        # ---- 2. decide what to cut ---------------------------------------
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
        self._set(summary=plan.summarise(kills, plans), clip_count=len(plans))
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
        raw_per_clip = opt.get("per_clip") or {}
        per_clip = {str(k): v for k, v in raw_per_clip.items()
                    if isinstance(v, dict)}
        if per_clip:
            log.info("%d clip(s) carry their own caption or voice settings",
                     len(per_clip))
        enc = opt.get("encoder", "auto")
        vmode = opt.get("vertical_mode", "crop")
        want_vertical = vmode not in ("none", "", None)
        want_montage = bool(opt.get("montage", True)) and len(plans) > 1

        steps = len(plans) + (len(plans) if want_vertical else 0) + (1 if want_montage else 0)
        self._set(step="cut", done=0, total=steps)

        masters: list[Path] = []
        n = 0
        for p in plans:
            self._check()
            self._set(message=f"Cutting clip {p.rank} of {len(plans)} "
                              f"({p.kills} kills)")
            m = cutter.master(self.source, p, self.folder / "clips", encoder=enc)
            masters.append(m)
            n += 1
            self._set(done=n)
            self.results.append({
                **p.as_dict(),
                "master": str(m),
                "vertical": None,
            })

        # ---- 4. vertical -------------------------------------------------
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
                            handle=str(opt.get("handle") or "@YuvaNeta"),
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
            n += 1
            self._set(done=n)

        # ---- 5b. the promo -----------------------------------------------
        if want_promo and spare:
            self._check()
            self._set(message=f"Sweeping {len(spare)} leftover kill(s) into a "
                              f"promo")
            try:
                got = promo.build(
                    self.source, spare, kills, self.folder,
                    game=self.game,
                    handle=str(opt.get("handle") or "@YuvaNeta"),
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
        #
        # Separate from the montage, not a replacement for it: a montage is the
        # session in full with the original audio, and a reel is a short cut to
        # music. The music has to be supplied -- there is no track to default
        # to that would not be someone else's.
        music = str(opt.get("music") or "")
        if music and Path(music).is_file() and len(plans) > 1:
            self._reel(Path(music), plans, kills, enc)

    def _from_match(self, kills: list[dict], prof) -> dict | None:
        """Valorant's own record of the match, if one is cached for this
        recording and it lines up with what the detector found.

        -> {"kills", "rounds", "about"} or None. Never raises: the pixel reader
        has already produced a usable answer by this point, and this is only
        ever an improvement on it.
        """
        from . import valorant_match as vmatch

        started = self._source_started()
        if not started:
            log.info("no start time for this recording, so its Valorant match "
                     "record cannot be found")
            return None
        found = vmatch.for_recording(started, self.source_seconds)
        if not found:
            state = vmatch.state(started, self.source_seconds)
            log.info("no Valorant match record for this recording (%s)",
                     state.get("why") or "none cached")
            return None

        vod = sorted(float(k["time"]) for k in kills)
        best = None
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
            if best is None or sync.matched > best[2].matched:
                best = (m, puuid, sync)
        if best is None:
            return None

        m, puuid, sync = best
        got_kills = vmatch.kills_from(m, puuid, sync)
        got_rounds = vmatch.rounds_from(m, puuid, sync)
        if not got_kills:
            log.info("match %s lined up but reports no kills by you", m.id[:8])
            return None
        log.info("Valorant match %s (%s): %d kill(s) and %d round(s) from "
                 "Riot's own record, %s", m.id[:8], m.mode or "?",
                 len(got_kills), len(got_rounds), sync.why)
        return {
            "kills": got_kills,
            "rounds": got_rounds,
            "about": {"match": m.id, "mode": m.mode, "ranked": m.ranked,
                      "offset": round(sync.offset, 2),
                      "matched": sync.matched, "total": sync.total,
                      "how": sync.why},
        }

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
            return None

        def prog(d, t):
            self._set(done=d, total=t,
                      message=f"Reading a few minutes to find the match - "
                              f"{d} of {t} chunks")
        # The probe reads a window, not the recording, which changes the
        # estimate by an order of magnitude on a two-hour stream.
        self._set(scan_seconds=min(self.PROBE_SECONDS, total))
        try:
            found = detect.scan(self.source, prof, progress=prog,
                                cancelled=lambda: self._cancel.is_set(),
                                duration=min(self.PROBE_SECONDS, total),
                                start=self.win_start)
        except detect.Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            log.info("the probe scan failed (%s); reading the whole recording", e)
            self._set(scan_seconds=total)
            return None
        if self._cancel.is_set():
            raise detect.Cancelled("cancelled")

        seed = [{"time": k.time, "end": k.end, "score": k.score,
                 "count": k.count} for k in found]
        if len(seed) < 3:
            log.info("only %d kill(s) in the first %.0f minutes -- not enough to "
                     "find the demo, so the whole recording is read",
                     len(seed), self.PROBE_SECONDS / 60)
            return None

        got = self._from_demo(seed)
        if not got:
            log.info("no demo matched the first %.0f minutes; reading the whole "
                     "recording", self.PROBE_SECONDS / 60)
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
        return got

    def _source_started(self) -> float | None:
        """When the recording began, by OBS's own filename stamp.

        Falls back to the file's modification time, which is when writing
        FINISHED -- close enough to reject a demo from days earlier, and the
        only thing available for a file OBS did not name.
        """
        from .. import history

        stamp = history._started_from_name(str(self.source))  # noqa: SLF001
        if stamp is not None:
            return stamp
        try:
            return self.source.stat().st_mtime
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
                got["r"] = cs2_demo.pick_demo(folder, vod)
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
