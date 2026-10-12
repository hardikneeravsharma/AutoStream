"""The reel as a timeline another editor can open (U20).

WHY THIS EXISTS
    `<name>.reel.json` already holds every shot, where its kill lands, how fast
    it plays, the song and the offset into it. That IS a timeline -- it was
    simply written in a vocabulary only this app speaks. Translating it into
    the two formats the rest of the industry reads turns AutoStream from a box
    that emits an mp4 into a step in somebody's pipeline: cut here, finish in
    Resolve.

WHAT COMES OUT
    OpenTimelineIO (`.otio`) is the one to prefer -- Resolve reads it, and
    anything with the OTIO adapters does. FCP7 XML (`.xml`) is older and
    plainer and is what Premiere imports. Both carry the same thing: one video
    track of cuts, one audio track for the song, and markers.

WHAT DOES NOT COME OUT, AND WHY IT IS WRITTEN DOWN
    Our transitions, kill effects, colour grade, lyrics and facecam layout are
    ffmpeg filter graphs. No interchange format can carry them, and pretending
    otherwise is how somebody loses an afternoon finding out. `sheet()` says
    plainly what survives and what does not, and it is written beside the file
    so it is still there when the project is opened on another machine next
    week.

A NOTE ON SPEED
    A shot's speed is a RAMP -- fast in, slow on the kill, fast out -- and
    neither format has a vocabulary for that. Each shot exports as a single
    rate, the one that makes its source span fill its place on the timeline,
    which is the closest honest approximation. The sheet says so.
"""
from __future__ import annotations

import json
import xml.sax.saxutils as sax
from pathlib import Path

FPS = 30


def _rate(src_in: float, src_out: float, reel: float) -> float:
    """One rate for a shot whose real speed is a ramp. 1.0 when it is not moving."""
    span = max(0.0, src_out - src_in)
    return round(span / reel, 6) if reel > 0 and span > 0 else 1.0


def _rows(project: dict, derived: dict) -> list[dict]:
    """One row per shot: where it sits, where it came from, how fast it runs."""
    out = []
    for shot, row in zip(project.get("shots") or [], derived.get("shots") or []):
        reel = float(row["end"]) - float(row["start"])
        out.append({
            "name": shot.get("name") or Path(shot["clip"]).stem,
            "path": shot["clip"],
            "reel_in": float(row["start"]),
            "reel_out": float(row["end"]),
            "src_in": float(row["source_in"]),
            "src_out": float(row["source_out"]),
            "rate": _rate(float(row["source_in"]), float(row["source_out"]), reel),
            "kill": float(row["kill_reel"]),
            "transition": shot.get("transition") or "",
            "speed": shot.get("speed") or "",
        })
    return out


def _marks(project: dict, derived: dict) -> list[tuple[float, str]]:
    """Every mark worth carrying: the kills, the beat grid, and hand marks.

    The kills are the point of the reel, so they go first and by name. The beat
    grid is what the cuts were made against, so somebody re-cutting in another
    editor can still land on it.
    """
    out = [(float(t), "kill") for t in (derived.get("kills") or [])]
    out += [(float(m.get("t", m)), str((m or {}).get("label") or "mark") if isinstance(m, dict) else "mark")
            for m in (project.get("markers") or [])]
    beat = float(project.get("beat") or 0)
    length = float(derived.get("length") or 0)
    if beat > 0:
        n, t = 0, 0.0
        while t <= length and n < 4000:
            out.append((t, "beat"))
            n, t = n + 1, (n + 1) * beat
    return sorted(out)


def otio(project: dict, derived: dict) -> str:
    """The reel as OpenTimelineIO JSON. Resolve reads this."""
    rows = _rows(project, derived)
    rate = float(FPS)

    def rt(seconds: float) -> dict:
        return {"OTIO_SCHEMA": "RationalTime.1", "rate": rate,
                "value": round(seconds * rate, 3)}

    def span(start: float, dur: float) -> dict:
        return {"OTIO_SCHEMA": "TimeRange.1", "start_time": rt(start), "duration": rt(dur)}

    clips = []
    for r in rows:
        clips.append({
            "OTIO_SCHEMA": "Clip.1",
            "name": r["name"],
            "source_range": span(r["src_in"], r["src_out"] - r["src_in"]),
            "media_reference": {
                "OTIO_SCHEMA": "ExternalReference.1",
                "target_url": Path(r["path"]).as_uri(),
            },
            # Named, not recreated: see the sheet.
            "metadata": {"autostream": {"speed": r["speed"], "rate": r["rate"],
                                        "transition_in": r["transition"]}},
        })

    tracks = [{"OTIO_SCHEMA": "Track.1", "name": "Video", "kind": "Video", "children": clips}]
    song = project.get("song") or ""
    if song:
        total = float(derived.get("length") or 0)
        tracks.append({
            "OTIO_SCHEMA": "Track.1", "name": "Music", "kind": "Audio",
            "children": [{
                "OTIO_SCHEMA": "Clip.1", "name": Path(song).stem,
                "source_range": span(float(project.get("song_offset") or 0), total),
                "media_reference": {"OTIO_SCHEMA": "ExternalReference.1",
                                    "target_url": Path(song).as_uri()},
            }],
        })

    return json.dumps({
        "OTIO_SCHEMA": "Timeline.1",
        "name": project.get("name") or "reel",
        "global_start_time": rt(0.0),
        "metadata": {"autostream": {"style": project.get("style"),
                                    "grade": project.get("grade"),
                                    "beat": project.get("beat")}},
        "markers": [{"OTIO_SCHEMA": "Marker.2", "name": kind,
                     "marked_range": span(at, 0.0)} for at, kind in _marks(project, derived)],
        "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": tracks},
    }, indent=2)


def fcp7(project: dict, derived: dict) -> str:
    """The reel as Final Cut Pro 7 XML. Premiere imports this."""
    rows = _rows(project, derived)
    W, H = (1080, 1920) if project.get("format") == "vertical" else (1920, 1080)
    total = int(round(float(derived.get("length") or 0) * FPS))

    def frames(seconds: float) -> int:
        return int(round(seconds * FPS))

    def esc(text: str) -> str:
        return sax.escape(str(text))

    items = []
    for i, r in enumerate(rows):
        items.append(f"""        <clipitem id="clip{i}">
          <name>{esc(r['name'])}</name>
          <start>{frames(r['reel_in'])}</start>
          <end>{frames(r['reel_out'])}</end>
          <in>{frames(r['src_in'])}</in>
          <out>{frames(r['src_out'])}</out>
          <rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>
          <file id="file{i}">
            <name>{esc(Path(r['path']).name)}</name>
            <pathurl>{esc(Path(r['path']).as_uri())}</pathurl>
            <rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>
          </file>
          <filter><effect><name>Time Remap</name><effectid>timeremap</effectid>
            <parameter><parameterid>speed</parameterid>
              <value>{round(r['rate'] * 100, 3)}</value></parameter></effect></filter>
        </clipitem>""")

    marks = "".join(
        f"""      <marker><name>{esc(kind)}</name><in>{frames(at)}</in><out>-1</out></marker>\n"""
        for at, kind in _marks(project, derived))

    song = project.get("song") or ""
    audio = ""
    if song:
        audio = f"""      <audio>
        <track>
          <clipitem id="song">
            <name>{esc(Path(song).stem)}</name>
            <start>0</start><end>{total}</end>
            <in>{frames(float(project.get('song_offset') or 0))}</in>
            <out>{frames(float(project.get('song_offset') or 0)) + total}</out>
            <file id="songfile">
              <name>{esc(Path(song).name)}</name>
              <pathurl>{esc(Path(song).as_uri())}</pathurl>
            </file>
          </clipitem>
        </track>
      </audio>\n"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
  <sequence id="{esc(project.get('name') or 'reel')}">
    <name>{esc(project.get('name') or 'reel')}</name>
    <duration>{total}</duration>
    <rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>
    <media>
      <video>
        <format><samplecharacteristics>
          <width>{W}</width><height>{H}</height>
          <rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>
        </samplecharacteristics></format>
        <track>
{chr(10).join(items)}
        </track>
      </video>
{audio}    </media>
{marks}  </sequence>
</xmeml>
"""


def sheet(project: dict, derived: dict, kind: str) -> str:
    """What the other editor will get, and what it will not.

    A SILENT DOWNGRADE IS HOW SOMEBODY LOSES AN AFTERNOON. This is written
    beside the file so the answer is still there next week, on another
    machine, when the person opening it is not the person who exported it.
    """
    rows = _rows(project, derived)
    ramps = sum(1 for r in rows if (r["speed"] or "s00") != "s00")
    name = {"otio": "OpenTimelineIO", "fcp7": "Final Cut Pro 7 XML"}.get(kind, kind)
    lines = [
        f"{project.get('name') or 'reel'} - exported as {name}",
        "",
        "ARRIVES WHOLE",
        f"  - every cut, in order: {len(rows)} shots over "
        f"{float(derived.get('length') or 0):.1f}s",
        "  - each shot's source file and its in/out points, so the clips relink",
        f"  - speed, as ONE rate per shot ({ramps} of {len(rows)} shots are ramped)",
        f"  - the kills and the beat grid, as markers "
        f"({len(derived.get('kills') or [])} kills)",
    ]
    if project.get("song"):
        lines.append("  - the song, as an audio track at the offset the reel starts from")
    lines += [
        "",
        "ARRIVES BY NAME ONLY, OR NOT AT ALL",
        "  - our transitions and kill effects: named on the clip, not recreated",
        f"  - the colour grade ({project.get('grade') or 'none'}): a name, not a LUT",
        "  - lyrics and titles: not carried",
        "  - the facecam layout: not carried",
        "",
        "WHY: those are ffmpeg filter graphs. No interchange format has a",
        "vocabulary for them, and a speed RAMP -- fast in, slow on the kill,",
        "fast out -- becomes a single rate, because neither format can hold",
        "the shape of it. Render in AutoStream if you want them.",
    ]
    return "\n".join(lines) + "\n"


def write(project: dict, derived: dict, folder: Path, kind: str = "otio") -> list[Path]:
    """Write the timeline and its sheet. -> the files written."""
    if kind not in ("otio", "fcp7"):
        raise ValueError(f"unknown interchange format {kind!r}")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = (project.get("name") or "reel").strip() or "reel"
    body = otio(project, derived) if kind == "otio" else fcp7(project, derived)
    out = folder / f"{stem}.{'otio' if kind == 'otio' else 'xml'}"
    out.write_text(body, encoding="utf-8")
    note = folder / f"{stem}.export.txt"
    note.write_text(sheet(project, derived, kind), encoding="utf-8")
    return [out, note]


__all__ = ["fcp7", "otio", "sheet", "write"]
