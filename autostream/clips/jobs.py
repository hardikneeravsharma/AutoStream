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
from .tools import FfmpegMissing, media_info

log = logging.getLogger("autostream.clips.jobs")

STEPS = ("scan", "cut", "vertical", "montage")


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
        # Filled in when a demo aligned: which one, and how the detector scored
        # against it. Recorded because it is the only place the detector's
        # accuracy is ever actually measured.
        self.demo: dict = {}
        self.started_at = time.time()
        self.finished_at: float | None = None

        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # ---------------- progress ----------------

    def _set(self, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            pct = int(100 * self.done / self.total) if self.total else 0
            return {
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
                "elapsed": int(time.time() - self.started_at),
                "source": self.source.name,
            }

    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
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
        kills: list[dict] = []

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

        cached = opt.get("kills")
        # Cached kills are enough for a game that writes a demo even in round
        # mode: what the detector found is only ever the fingerprint that
        # locates the demo, and the rounds come out of the demo itself. Without
        # one, round mode has to rescan -- the scoreboard is only read during a
        # scan and there is nothing else to read it from.
        if cached and (not use_rounds or (prof and prof.demos)):
            kills = list(cached)
            self._set(message=f"Using {len(kills)} kills found earlier")
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
                duration=info["duration"], fps=prof.scan_fps,
                hud_regions=prof.hud_regions or None,
                progress=prog, cancelled=lambda: self._cancel.is_set())
            if self._cancel.is_set():
                raise detect.Cancelled("cancelled")
            round_list = rounds_mod.analyse(readings, events)
            kills = [{"time": e.time, "end": e.end, "score": e.ratio,
                      "count": 1} for e in events if e.kind == "kill"]
            self._set(message=f"{len(round_list)} rounds, "
                              f"{len(rounds_mod.highlights(round_list))} worth cutting")
        elif prof and prof.exists():
            def prog(d, t):
                self._set(done=d, total=t,
                          message=f"Scanning for kills - {d} of {t} chunks")
            found = detect.scan(self.source, prof, progress=prog,
                                cancelled=lambda: self._cancel.is_set(),
                                duration=info["duration"])
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

        # ---- 1b. the demo, if the game writes one ------------------------
        #
        # Everything found above is superseded when a demo aligns: exact kill
        # times, exact rounds, and the circumstances no detector can see. What
        # the detector found is kept only as the fingerprint that located it,
        # and as a mark against a right answer.
        if prof and prof.demos and opt.get("demo", True):
            got = self._from_demo(kills)
            if got:
                kills, round_list = got["kills"], got["rounds"]
                self.demo = got["about"]

        # ---- 2. decide what to cut ---------------------------------------
        if use_rounds and not round_list:
            log.info("no round data for this recording; cutting bursts of "
                     "kills instead")
            use_rounds = False
        if use_rounds:
            from . import rounds as rounds_mod

            hl = rounds_mod.highlights(round_list)
            wanted = opt.get("round_types")
            if wanted:
                keep = set(wanted)
                hl = [r for r in hl
                      if any(any(k in l for l in r.labels) for k in keep)]
            plans = plan.build_rounds(
                hl, game=self.game,
                pre_roll=pre_roll, tail=tail,
                whole_round=bool(opt.get("whole_round", True)),
                clip_seconds=opt.get("clip_seconds", "auto"),
                source_duration=info["duration"])
            if want_promo:
                # Rounds the player did something in but which earned no label.
                # Individually they are nothing; together they are the advert.
                quiet = [r for r in round_list
                         if r.my_kills >= 1 and not r.labels]
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

        self._set(summary=plan.summarise(kills, plans))
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "session.json").write_text(json.dumps({
            "source": str(self.source), "game": self.game,
            "game_key": self.game_key, "options": opt,
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
        }, indent=2), encoding="utf-8")

        # ---- 3. cut ------------------------------------------------------
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
            marks: dict[float, list[str]] = {}
            if opt.get("captions", True):
                try:
                    marks = overlay.detect_tags(
                        self.source, [float(k["time"]) for k in kills],
                        self.game_key, self.game)
                    if marks:
                        log.info("tagged %d kill(s): %s", len(marks),
                                 sorted({t for v in marks.values() for t in v}))
                except Exception as e:  # noqa: BLE001 - a caption is not worth failing over
                    log.warning("tag detection failed: %s", e)

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
                spoken, speech = "", None
                if v and opt.get("voice"):
                    # `avoid` is what has already been said in this session.
                    # Two clutches in one reel saying the same sentence is the
                    # one thing a viewer notices immediately.
                    spoken, speech = self._speak(plans[i], v)
                if v and opt.get("captions", True):
                    p = plans[i]
                    inside = [k for k in kills
                              if p.start <= float(k["time"]) <= p.end]
                    extra = sorted({t for k in inside
                                    for t in marks.get(float(k["time"]), [])})
                    cap = overlay.caption_for(p, inside, extra)
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

    def _speak(self, plan, clip: Path):
        """The hook for one clip, synthesised but not yet mixed in.

        -> (what it says, the Speech) or ("", None). Split out from the mixing
        because the subtitle needs the line and its duration BEFORE the overlay
        pass runs, and because a failure here must cost the hook and not the
        clip.
        """
        name = str(self.options.get("voice_name") or voice.VOICE)
        said = voice.line_for(plan, avoid=self.said)
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

        worker = threading.Thread(target=search, name="autostream-demo",
                                  daemon=True)
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
            (self.folder / "clips.json").write_text(json.dumps({
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
            }, indent=2), encoding="utf-8")
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
