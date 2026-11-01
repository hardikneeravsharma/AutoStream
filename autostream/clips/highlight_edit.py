"""The stream highlight, opened again: its cut list as a project the page edits.

WHY THIS EXISTS
    The player approved the stream highlight (stream_highlight.py, v2.8.0) and asked
    for it to open "in a timeline with editing options other than the song reel
    edit": which moments to keep, the facecam area, the facecam zoom, and the
    automatic captions. What he would change before uploading: "the moment to keep
    and remove, the auto generated captions and the part where the face cam is in
    focus". Of three ways to lay that out he chose a timeline with lanes AND the
    transcript beside it ("a mix of B and C"); docs/superpowers/specs/
    2026-11-01-highlight-editor-design.md has the rest.

WHAT IS EDITED
    The cut list, never pixels. The clip job writes PROJECT beside the video it
    renders -- every cut the planner chose, the moments they belong to, what was
    said around them -- and the page changes only what `merge` lets it: a cut's
    start, end, whether it is kept and whether it zooms on the face; a line's
    words, whether it is a caption, cut out of the video, or said on the face; the
    facecam box, the zoom, the captions. Where the recording is, where the video
    goes and what was chosen in the first place are the job's, and a request
    cannot move them.

    A cut line and a face line are FLAGS on the line, applied only when the cut list
    is built for a render (`pieces`), so switching one off gives back exactly what
    was there before.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from .. import atomic
from . import stream_highlight as sh

log = logging.getLogger("autostream.clips.highlight_edit")

VERSION = 1
SUFFIX = ".edit.json"
EDITED = "_edited"
LAYOUTS = ("game", "cam", "result")
LANGS = ("english", "said")
SHORTEST = 0.5             # sh.shape()'s floor: a piece shorter than this is a flash
TRIM_LEAST = 1.0           # a kept cut is never trimmed shorter than this
CAPTION_LEAST = 0.3        # a caption shown for less than this cannot be read
LINES_MOST = 5000
ZOOMS_MOST = 500
TRACKS = ("mic", "game")   # the recording's own audio: 0 is the mix, 1 the mic, 2 the game
TRACK_INDEX = {"mic": 1, "game": 2}
MASTER_LEAST, MASTER_MOST = -10.0, 6.0   # the overall volume, dB from LOUDNESS
LOUDNESS = -16.0           # stream_highlight.render's target, LUFS
ZOOM_LEAST, ZOOM_MOST = 1.2, sh.CAM_ZOOM_MOST


def project_path(video: str | Path) -> Path:
    v = Path(video)
    return v.with_name(v.stem + SUFFIX)


def edited_path(video: str | Path) -> Path:
    v = Path(video)
    return v.with_name(v.stem + EDITED + v.suffix)


def _name(s: sh.Stretch) -> str:
    return f"Round {s.round} · {s.why}" if s.round else (s.why or "Moment")


def build(*, video: str | Path, source: str | Path, source_seconds: float, cuts: list[sh.Cut],
          chosen: list[sh.Stretch], labels: list[str], lines=None, team_lines=None, cam_box=None,
          channel: str = "", game: str = "", language: str | None = None,
          size: tuple[int, int] = (1920, 1080)) -> dict:
    """The project for a video the job has just planned. `labels[i]` names the match
    stretch i is from ("MATCH 1 · COMPETITIVE · BIND · CYPHER"). `team_lines` are
    what the team-mates said on voice comms (the game's track)."""
    said = [(ln, "mic") for ln in lines or []] + [(ln, "game") for ln in team_lines or []]
    said.sort(key=lambda x: x[0].start)
    english = any(getattr(ln, "english", "") for ln in lines or [])
    return {
        "version": VERSION,
        "video": str(video),
        "source": str(source),
        "source_seconds": round(float(source_seconds), 3),
        "game": game, "channel": channel, "size": list(size),
        "cam_box": [round(float(v), 5) for v in cam_box] if cam_box else None,
        "cam_zoom": None,
        "language": language,
        "captions": {"on": False, "lang": "english" if english else "said"},
        "moments": [{"id": i, "name": _name(s),
                     "match": labels[i] if i < len(labels) else "", "round": s.round}
                    for i, s in enumerate(chosen)],
        "cuts": [{"id": i, "start": round(c.start, 3), "end": round(c.end, 3),
                  "planned": [round(c.start, 3), round(c.end, 3)],
                  "kind": c.kind, "stretch": c.stretch, "layout": c.layout,
                  "caption": c.caption, "punches": [round(p, 3) for p in c.punches],
                  "keep": True, "zoom": c.layout == "cam"}
                 for i, c in enumerate(cuts)],
        "lines": [{"id": i, "start": round(ln.start, 3), "end": round(ln.end, 3),
                   "text": ln.text, "english": getattr(ln, "english", "") or "",
                   "show": True, "cut": False, "face": False, "track": who}
                  for i, (ln, who) in enumerate(said)],
        "zooms": [],
        "volume": _volume_default(),
        "audio": {},
        "made": "",
    }


def _volume_default() -> dict:
    return {"master": 0.0, "mic": {"db": 0.0, "keys": []}, "game": {"db": 0.0, "keys": []}}


def upgrade(project: dict) -> dict:
    """A project as this version reads it: v2.9.0 projects had no speaker on a
    line, no face-zoom spans, no volume lines and no copied-out tracks."""
    for ln in project.get("lines") or []:
        ln.setdefault("track", "mic")
    project.setdefault("zooms", [])
    vol = project.get("volume") if isinstance(project.get("volume"), dict) else {}
    project["volume"] = {**_volume_default(), **vol}
    project.setdefault("audio", {})
    return project


def save(project: dict) -> Path:
    p = project_path(project["video"])
    atomic.write_json(p, project, indent=1)
    return p


def load(video: str | Path) -> dict | None:
    import json
    p = project_path(video)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return upgrade(d) if isinstance(d, dict) and d.get("version") == VERSION else None


def _num(v, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f == f and abs(f) != float("inf") else default


def merge(base: dict, edits: dict) -> dict:
    """`base` with the page's edits applied, each checked. Only what the editor can
    change is read from `edits`; anything else in it is ignored."""
    out = {**base, "cuts": [dict(c) for c in base.get("cuts") or []],
           "lines": [dict(ln) for ln in base.get("lines") or []]}
    top = _num(base.get("source_seconds"), 0.0) or float("inf")
    by_id = {c["id"]: c for c in out["cuts"]}
    for e in edits.get("cuts") or []:
        c = by_id.get(e.get("id")) if isinstance(e, dict) else None
        if c is None:
            continue
        a = max(0.0, min(_num(e.get("start"), c["start"]), top))
        b = max(0.0, min(_num(e.get("end"), c["end"]), top))
        if b - a >= TRIM_LEAST:
            c["start"], c["end"] = round(a, 3), round(b, 3)
        c["keep"] = bool(e.get("keep", c["keep"]))
        c["zoom"] = bool(e.get("zoom", c["zoom"]))
    if isinstance(edits.get("lines"), list):
        out["lines"] = _lines(edits["lines"], {ln["id"]: ln for ln in out["lines"]}, top)
    if isinstance(edits.get("zooms"), list):
        out["zooms"] = _zooms(edits["zooms"], top)
    if isinstance(edits.get("volume"), dict):
        out["volume"] = _volume(edits["volume"], base.get("volume") or _volume_default())
    if "cam_box" in edits:
        b = edits.get("cam_box")
        if isinstance(b, (list, tuple)) and len(b) == 4:
            x, y, w, h = (_num(v, -1.0) for v in b)
            if 0 <= x and 0 <= y and 0.02 <= w and 0.02 <= h and x + w <= 1.001 and y + h <= 1.001:
                out["cam_box"] = [round(x, 5), round(y, 5), round(w, 5), round(h, 5)]
    if "cam_zoom" in edits:
        z = edits.get("cam_zoom")
        out["cam_zoom"] = None if z in (None, "", 0, "auto") else round(
            max(ZOOM_LEAST, min(_num(z, ZOOM_LEAST), ZOOM_MOST)), 2)
    cap = edits.get("captions")
    if isinstance(cap, dict):
        out["captions"] = {"on": bool(cap.get("on", (base.get("captions") or {}).get("on"))),
                           "lang": cap.get("lang") if cap.get("lang") in LANGS
                           else (base.get("captions") or {}).get("lang", "english")}
    return out


def _lines(raw: list, before: dict, top: float) -> list[dict]:
    """The page's lines -- it adds, splits, merges, retimes and deletes them, so the
    list it sends is the list. Each is checked; a line it no longer sends is gone."""
    out, seen = [], set()
    for e in raw[:LINES_MOST]:
        if not isinstance(e, dict):
            continue
        try:
            i = int(e.get("id"))
        except (TypeError, ValueError):
            continue
        if i in seen or i < 0:
            continue
        old = before.get(i, {})
        a = max(0.0, min(_num(e.get("start"), old.get("start", -1.0)), top))
        b = max(0.0, min(_num(e.get("end"), old.get("end", -1.0)), top))
        if b - a < CAPTION_LEAST:
            if not old:
                continue
            a, b = old["start"], old["end"]
        ln = {"id": i, "start": round(a, 3), "end": round(b, 3)}
        for k in ("text", "english"):
            v = e.get(k, old.get(k, ""))
            ln[k] = " ".join(v.split())[:400] if isinstance(v, str) else ""
        for k, dflt in (("show", True), ("cut", False), ("face", False)):
            ln[k] = bool(e.get(k, old.get(k, dflt)))
        ln["track"] = e.get("track") if e.get("track") in TRACKS else old.get("track", "mic")
        seen.add(i)
        out.append(ln)
    return sorted(out, key=lambda x: (x["start"], x["id"]))


def _zooms(raw: list, top: float) -> list[dict]:
    """Face-zoom spans drawn on the timeline: {id, start, end} on the recording's clock."""
    out = []
    for n, e in enumerate(raw[:ZOOMS_MOST]):
        if isinstance(e, dict):
            a, b, i = _num(e.get("start"), -1.0), _num(e.get("end"), -1.0), e.get("id", n)
        elif isinstance(e, (list, tuple)) and len(e) == 2:
            (a, b), i = (_num(e[0], -1.0), _num(e[1], -1.0)), n
        else:
            continue
        a, b = max(0.0, min(a, top)), max(0.0, min(b, top))
        if b - a >= SHORTEST:
            out.append({"id": int(i) if isinstance(i, (int, float)) else n,
                        "start": round(a, 3), "end": round(b, 3)})
    return sorted(out, key=lambda z: z["start"])


def _volume(raw: dict, before: dict) -> dict:
    from .studio import VOL_FLOOR, VOL_TOP, vol_keys
    out = {"master": round(max(MASTER_LEAST, min(_num(raw.get("master"), before.get("master", 0.0)),
                                                   MASTER_MOST)), 2)}
    for name in TRACKS:
        lane = raw.get(name) if isinstance(raw.get(name), dict) else {}
        old = before.get(name) or {"db": 0.0, "keys": []}
        out[name] = {"db": round(max(VOL_FLOOR, min(_num(lane.get("db"), old.get("db", 0.0)), VOL_TOP)), 2),
                     "keys": vol_keys(lane["keys"]) if "keys" in lane else old.get("keys", [])}
    return out


def _layouts(a: float, b: float, base: str, faces: list[tuple[float, float]]) -> list[tuple[float, float, str]]:
    """[a, b) as (start, end, layout): `base`, and "cam" over the face spans."""
    marks = sorted({a, b, *(x for f in faces for x in f if a < x < b)})
    segs: list[list] = []
    for x, y in zip(marks, marks[1:]):
        mid = (x + y) / 2
        lay = "cam" if any(f0 <= mid < f1 for f0, f1 in faces) else base
        if segs and segs[-1][2] == lay:
            segs[-1][1] = y
        else:
            segs.append([x, y, lay])
    # A sliver between two face lines, or before one, is not a layout of its own.
    k = 0
    while k < len(segs):
        if segs[k][1] - segs[k][0] < SHORTEST and len(segs) > 1:
            j = k - 1 if k > 0 else k + 1
            segs[j][0], segs[j][1] = min(segs[j][0], segs[k][0]), max(segs[j][1], segs[k][1])
            del segs[k]
            k = 0
            continue
        if k and segs[k - 1][2] == segs[k][2]:
            segs[k - 1][1] = segs[k][1]
            del segs[k]
            continue
        k += 1
    return [(x, y, lay) for x, y, lay in segs]


def caption_text(ln: dict, lang: str) -> str:
    if lang == "english" and ln.get("english"):
        return ln["english"]
    return ln.get("text") or ""


def pieces(project: dict) -> tuple[list[sh.Cut], list[list[tuple[float, float, str]]]]:
    """The edited video's cut list, in order, and each cut's captions (seconds into
    the cut). Captions come back whether or not they are to be burned in: the .srt
    is written from them either way."""
    lines = [ln for ln in project.get("lines") or [] if (ln.get("end") or 0) > (ln.get("start") or 0)]
    holes = [(ln["start"], ln["end"]) for ln in lines if ln.get("cut")]
    faces = sh._union([(ln["start"], ln["end"]) for ln in lines if ln.get("face") and not ln.get("cut")]
                      + [(z["start"], z["end"]) for z in project.get("zooms") or []])
    lang = (project.get("captions") or {}).get("lang", "english")
    said = [ln for ln in lines if ln.get("show", True) and not ln.get("cut") and caption_text(ln, lang).strip()]
    cuts: list[sh.Cut] = []
    subs: list[list[tuple[float, float, str]]] = []
    for c in project.get("cuts") or []:
        if not c.get("keep", True) or c["end"] - c["start"] < SHORTEST:
            continue
        lay = c.get("layout") if c.get("layout") in LAYOUTS else "game"
        base = "cam" if c.get("zoom") else ("game" if lay == "cam" else lay)
        first = True
        for a, b in sh._minus([(c["start"], c["end"])], holes):
            if b - a < SHORTEST:
                continue
            for x, y, layout in _layouts(a, b, base, faces):
                cut = sh.Cut(x, y, punches=[p for p in c.get("punches") or [] if x <= p < y],
                             kind=c.get("kind") or "play", stretch=int(c.get("stretch", -1)),
                             caption=(c.get("caption") or "") if first else "", layout=layout)
                first = False
                cuts.append(cut)
                subs.append([(max(ln["start"], x) - x, min(ln["end"], y) - x, caption_text(ln, lang),
                              ln.get("track", "mic"))
                             for ln in said if ln["start"] < y and ln["end"] > x
                             and min(ln["end"], y) - max(ln["start"], x) >= 0.3])
    return cuts, subs


def _stamp(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(cuts: list[sh.Cut], subs: list[list[tuple[float, float, str]]]) -> str:
    """The captions as SubRip, on the edited video's clock -- for YouTube's own
    captions, which a viewer can switch off and which are searchable."""
    rows, at = [], 0.0
    for c, ss in zip(cuts, subs):
        for sub in ss:
            who = sub[3] if len(sub) > 3 else "mic"
            rows.append((at + sub[0], at + sub[1], ("[Team] " if who == "game" else "") + sub[2]))
        at += c.length
    return "".join(f"{n}\n{_stamp(a)} --> {_stamp(b)}\n{text}\n\n"
                   for n, (a, b, text) in enumerate(rows, 1))


def length(project: dict) -> float:
    return sum(c.length for c in pieces(project)[0])


def track_count(source: str | Path) -> int:
    try:
        from . import reactions
        return int(reactions.tracks(Path(source)))
    except Exception:  # noqa: BLE001 - unreadable: the recording's own mix only
        return 1


def track_mix(project: dict) -> dict | None:
    """The mic and game volume lines for the render, or None to keep the
    recording's own mix: when they are untouched -- OBS's mix is what the player
    has always heard -- or when the recording has no separate tracks."""
    vol = project.get("volume") or {}
    lanes = {name: vol.get(name) or {"db": 0.0, "keys": []} for name in TRACKS}
    if all(not lane.get("keys") and not lane.get("db") for lane in lanes.values()):
        return None
    if track_count(project.get("source") or "") < 3:
        return None
    return {"mic": lanes["mic"].get("keys") or [], "mic_db": float(lanes["mic"].get("db") or 0.0),
            "game": lanes["game"].get("keys") or [], "game_db": float(lanes["game"].get("db") or 0.0)}


# ---------------------------------------------------------------- the tracks, and the team's words

def track_path(video: str | Path, track: str) -> Path:
    """Where a track copied out of the recording is kept: beside the project."""
    v = Path(video)
    return v.with_name(f"{v.stem}.{track}.m4a")


def copy_tracks(project: dict) -> dict:
    """The mic and the game, each copied out of the recording into a file of its
    own -- no re-encode, seconds for a long stream -- so the editor can play them
    at their own volumes: a browser plays only a file's first audio track. The
    player's yes (2026-11-01): about 130 MB each for a 4.6 h stream."""
    import subprocess
    from .tools import binary
    src = Path(project["source"])
    if track_count(src) < 3:
        raise ValueError("This recording has no separate mic and game tracks.")
    made = {}
    for name in TRACKS:
        out = track_path(project["video"], name)
        if not out.is_file():
            tmp = out.with_name(out.stem + ".part.m4a")
            p = subprocess.run([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                                "-i", str(src), "-map", f"0:a:{TRACK_INDEX[name]}", "-vn", "-c:a", "copy",
                                "-movflags", "+faststart", str(tmp)],
                               capture_output=True, text=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if p.returncode != 0 or not tmp.is_file():
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"could not copy the {name} track: {(p.stderr or '').strip()[-300:]}")
            tmp.replace(out)
        made[name] = str(out)
    fresh = load(project["video"]) or project
    save({**fresh, "audio": {**(fresh.get("audio") or {}), **made}})
    return made


TEAM_PAD = 2.0             # transcribed this far either side of every cut
REPEAT_GAP = 2.5           # the same words again within this is one line said once


def _key(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def collapse(lines: list) -> list:
    """One line where speech-to-text wrote the same words over and over. Measured on
    the game track of the 2026-10-25 session: "Close down" four times a second
    apart, "Nice round" twice -- the model repeats itself over gunfire and music,
    and four identical captions in four seconds read as a stutter. A repeat closer
    than REPEAT_GAP extends the line before it instead."""
    out: list = []
    for ln in sorted(lines, key=lambda x: x.start):
        prev = out[-1] if out else None
        if prev is not None and _key(prev.text) and _key(prev.text) == _key(ln.text) \
                and ln.start - prev.end <= REPEAT_GAP:
            prev.end = max(prev.end, ln.end)
            continue
        out.append(ln)
    return out


def transcribe_track(project: dict, track: str) -> int:
    """Every line said on one of the recording's tracks around the video's cuts, in
    place of that track's lines so far. For the game track that is the team-mates'
    voice comms, which the player wants captioned (2026-11-01). -> lines found.

    Only where speech-to-text is fast enough to wait for (speech.fast: a graphics
    card). The language of that track is decided on its own, since a team-mate need
    not speak the player's."""
    from . import speech
    if track not in TRACKS:
        raise ValueError("Which track?")
    if not speech.available():
        raise RuntimeError("Speech-to-text is not installed in this copy of AutoStream.")
    if not speech.fast():
        raise RuntimeError("Speech-to-text needs a graphics card here; on the processor it is too slow to wait for.")
    if track == "game" and track_count(project["source"]) < 3:
        raise ValueError("This recording has no separate game track.")
    spans = sh._union([(max(0.0, min(c["start"], (c.get("planned") or [c["start"]])[0]) - TEAM_PAD),
                        max(c["end"], (c.get("planned") or [0, c["end"]])[1]) + TEAM_PAD)
                       for c in project.get("cuts") or []])
    found = speech.transcribe(project["source"], spans, track=TRACK_INDEX[track], english=True)
    if found is None:
        raise RuntimeError("Speech-to-text could not run.")
    found = collapse(found)
    fresh = load(project["video"]) or project
    keep = [ln for ln in fresh.get("lines") or [] if ln.get("track", "mic") != track]
    nxt = max((ln["id"] for ln in fresh.get("lines") or []), default=-1) + 1
    new = [{"id": nxt + k, "start": round(ln.start, 3), "end": round(ln.end, 3), "text": ln.text,
            "english": ln.english or "", "show": True, "cut": False, "face": False, "track": track}
           for k, ln in enumerate(found)]
    save({**fresh, "lines": sorted(keep + new, key=lambda x: (x["start"], x["id"]))})
    log.info("%s: %d line(s) on the %s track", Path(project["video"]).name, len(new), track)
    return len(new)


class Work:
    """The editor's slow jobs: copying the tracks out, and transcribing a track. Each
    runs on its own thread, one of a kind at a time; the page polls `snapshot`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.jobs: dict[str, dict] = {}     # "tracks" / "transcribe" -> its state

    def _go(self, kind: str, video: str, fn) -> bool:
        with self._lock:
            j = self.jobs.get(kind)
            if j and j["state"] == "running":
                return False
            job = {"state": "running", "video": video, "error": "", "result": None}
            self.jobs[kind] = job

        def run():
            try:
                result = fn()
                with self._lock:
                    job.update(state="done", result=result)
            except Exception as e:  # noqa: BLE001 - the page shows why
                log.warning("highlight %s failed: %s", kind, e)
                with self._lock:
                    job.update(state="failed", error=str(e)[:400])

        threading.Thread(target=run, name=f"autostream-highlight-{kind}", daemon=True).start()
        return True

    def copy_tracks(self, project: dict) -> bool:
        return self._go("tracks", project["video"], lambda: copy_tracks(project))

    def transcribe(self, project: dict, track: str) -> bool:
        return self._go("transcribe", project["video"], lambda: transcribe_track(project, track))

    def snapshot(self, video: str) -> dict:
        with self._lock:
            return {k: {x: j[x] for x in ("state", "error", "result")}
                    for k, j in self.jobs.items() if j["video"] == video}


_WORK = Work()


def work() -> Work:
    return _WORK

WAIT_POLL = 3.0            # how often a waiting render asks whether it may start


class Renderer:
    """One edited video at a time, with a snapshot the page polls.

    IT WAITS FOR THE BROADCAST. Make video saturates the encoder, and on a
    session that is live or recording that is dropped frames in the stream --
    so a render asked for then is held ("waiting", with the reason) and starts
    by itself once `held()` says nothing is in the way. The player's own word
    on the plan (2026-11-01): no Make video while live or recording; wait and
    say so."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.state, self.video, self.out, self.error, self.why = "idle", "", "", "", ""
        self.done, self.total, self.started = 0, 0, 0.0

    def busy(self) -> bool:
        with self._lock:
            t = self._thread
        return bool(t and t.is_alive())

    def encoding(self) -> bool:
        """Rendering now, as opposed to waiting for its turn."""
        with self._lock:
            return self.state == "running" and bool(self._thread and self._thread.is_alive())

    def start(self, project: dict, *, encoder: str = "auto", held=None) -> bool:
        """`held()` -> why the render may not start yet, "" when it may."""
        if self.busy():
            return False
        with self._lock:
            self._stop.clear()
            self.state, self.video, self.error, self.why = "running", project["video"], "", ""
            self.out, self.done, self.total, self.started = "", 0, 0, time.time()
            self._thread = threading.Thread(target=self._run, args=(project, encoder, held),
                                            name="autostream-highlight-edit", daemon=True)
            self._thread.start()
        return True

    def cancel(self) -> None:
        self._stop.set()

    def _wait(self, held) -> bool:
        """Until nothing holds the encoder. False when stopped while waiting."""
        while True:
            try:
                why = held() if held else ""
            except Exception:  # noqa: BLE001 - a check that fails holds nothing
                why = ""
            if not why:
                with self._lock:
                    self.state, self.why, self.started = "running", "", time.time()
                return True
            with self._lock:
                if self.state != "waiting":
                    log.info("edited highlight waiting: %s", why)
                self.state, self.why = "waiting", why
            if self._stop.wait(WAIT_POLL):
                return False

    def _run(self, project: dict, encoder: str, held=None) -> None:
        out = edited_path(project["video"])
        try:
            if not self._wait(held):
                raise InterruptedError("stopped while waiting")
            # From disk now, not as asked: edits saved while it waited are in.
            project = load(project["video"]) or project
            cuts, subs = pieces(project)
            if sum(c.length for c in cuts) < 5.0:
                raise ValueError("Nothing is kept: keep at least one moment.")

            def tick(done: int, total: int) -> None:
                with self._lock:
                    self.done, self.total = done, total

            tmp = out.with_name(out.stem + ".part.mp4")
            box = project.get("cam_box")
            sh.render(Path(project["source"]), cuts, tmp, size=tuple(project.get("size") or (1920, 1080)),
                      encoder=encoder, cq=23, channel=project.get("channel") or "",
                      game=project.get("game") or "", cam_box=tuple(box) if box else None,
                      progress=tick, cam_most=project.get("cam_zoom"),
                      subs=subs if (project.get("captions") or {}).get("on") else None,
                      mix=track_mix(project),
                      loudness=LOUDNESS + float((project.get("volume") or {}).get("master") or 0.0),
                      cancelled=self._stop.is_set)
            tmp.replace(out)
            text = srt(cuts, subs)
            if text:
                out.with_suffix(".srt").write_text(text, encoding="utf-8")
            # From disk, not the copy this started with: the page may have saved
            # edits while it rendered.
            save({**(load(project["video"]) or project), "made": str(out)})
            with self._lock:
                self.state, self.out = "done", str(out)
            log.info("edited highlight: %s (%d cuts, %.0f s)", out.name, len(cuts),
                     sum(c.length for c in cuts))
        except InterruptedError:
            with self._lock:
                self.state, self.why = "idle", ""
            log.info("edited highlight stopped")
        except Exception as e:  # noqa: BLE001 - the page shows why
            log.exception("could not make the edited highlight: %s", e)
            with self._lock:
                self.state, self.error = "failed", str(e)[:400]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"state": self.state, "video": self.video, "out": self.out, "error": self.error,
                    "why": self.why,
                    "done": self.done, "total": self.total,
                    "percent": int(100 * self.done / self.total) if self.total else 0,
                    "elapsed": int(time.time() - self.started) if self.started else 0}


_RENDERER = Renderer()


def renderer() -> Renderer:
    return _RENDERER
