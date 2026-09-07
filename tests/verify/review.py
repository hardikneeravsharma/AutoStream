"""Build the page you review the detector's output on, and read your verdicts back.

    .venv\\Scripts\\python.exe tests\\verify\\review.py build
    .venv\\Scripts\\python.exe tests\\verify\\review.py import C:\\path\\verdicts.json

`build` writes review.html into the corpus directory and opens it. `import`
turns the verdicts it saves into tests/verify/baselines/<game>.json, which is
what tier 4 then measures every future scan against.

WHY A LOCAL PAGE AND NOT A PUBLISHED ONE. The excerpts are 7.5 GB sitting on
this machine. A page served from the filesystem can play them inline and seek
to a detection, so a verdict is one click and one look. A hosted page could
only show a still, and judging "is that a kill" from one 320-pixel frame is
guesswork -- which is the opposite of what a baseline is for.

WHAT IS BEING ASKED. Two different questions, and both matter:

    is each detection real?   -> precision. Wrong ones become clips of nothing.
    was anything missed?      -> recall. Missed ones are the highlight that
                                 never got cut.

The second cannot be answered from the detections alone, which is why the page
gives you the video and a button that records wherever you have paused it.
Nothing here is truth until you have said so: the detector's own output is the
thing under test, so seeding a baseline from it unreviewed would be marking
its own homework.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from autostream.clips import tools                             # noqa: E402

CORPUS = Path(os.environ.get("AUTOSTREAM_TESTDATA", r"C:\autostream-testdata"))
BASELINES = Path(__file__).resolve().parent / "baselines"
THUMBS = "thumbs"

# Recall floors are lower than precision floors on purpose. A missed kill
# costs one clip that was never cut; a false positive costs a clip of nothing
# that a viewer actually sees, and thirty of them make the feature useless.
DEFAULT_FLOOR = {"recall": 0.85, "precision": 0.95}


def manifest() -> list[dict]:
    p = CORPUS / "manifest.json"
    if not p.is_file():
        raise SystemExit(f"no corpus at {CORPUS} - run corpus.py build first")
    return json.loads(p.read_text(encoding="utf-8"))["excerpts"]


def detections() -> dict:
    p = CORPUS / "detections.json"
    if not p.is_file():
        raise SystemExit(f"no detections at {p} - run score.py scan first")
    return json.loads(p.read_text(encoding="utf-8"))


def thumb(video: Path, at: float, dest: Path, width: int = 320) -> bool:
    if dest.is_file():
        return True
    exe = tools.binary("ffmpeg")
    if not exe:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [exe, "-y", "-hide_banner", "-loglevel", "error",
         "-ss", f"{max(0.0, at):.3f}", "-i", str(video),
         "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(dest)],
        capture_output=True, text=True, timeout=120)
    return r.returncode == 0 and dest.is_file()


# --------------------------------------------------------------- the page

CSS = """
:root{--bg:#0f1115;--card:#171a21;--line:#262b36;--ink:#e6e9ef;--dim:#9aa3b2;
--ok:#3fb950;--bad:#f85149;--accent:#58a6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:9;background:#0f1115ee;
backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:14px 20px;
display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:17px;margin:0;font-weight:650}
.sub{color:var(--dim);font-size:13px}
.spacer{flex:1}
button{font:inherit;background:var(--card);color:var(--ink);
border:1px solid var(--line);border-radius:7px;padding:7px 13px;cursor:pointer}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent);border-color:var(--accent);color:#06101f;
font-weight:600}
section{padding:20px;border-bottom:1px solid var(--line)}
h2{font-size:15px;margin:0 0 4px}
.meta{color:var(--dim);font-size:12px;margin-bottom:12px}
.wrap{display:grid;grid-template-columns:minmax(320px,520px) 1fr;gap:20px;
align-items:start}
video{width:100%;border-radius:9px;background:#000;border:1px solid var(--line)}
.pad{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;align-items:center}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));
gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:9px;
overflow:hidden}
.card.yes{border-color:var(--ok)}
.card.no{border-color:var(--bad);opacity:.55}
.card img{width:100%;display:block;cursor:pointer;aspect-ratio:16/9;
object-fit:cover}
.card .t{padding:6px 8px;font-size:12px;color:var(--dim);
display:flex;justify-content:space-between;gap:6px}
.vote{display:flex;border-top:1px solid var(--line)}
.vote button{flex:1;border:0;border-radius:0;background:transparent;padding:6px}
.vote button.on-yes{background:var(--ok);color:#04140a;font-weight:700}
.vote button.on-no{background:var(--bad);color:#1a0505;font-weight:700}
.missed{margin-top:14px;background:var(--card);border:1px solid var(--line);
border-radius:9px;padding:12px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{background:#22272f;border:1px solid var(--line);border-radius:20px;
padding:3px 10px;font-size:12px;display:flex;gap:7px;align-items:center}
.chip b{cursor:pointer;color:var(--bad)}
.none{color:var(--dim);font-size:12px}
.tag{font-size:11px;padding:2px 7px;border-radius:20px;border:1px solid var(--line);
color:var(--dim)}
.tag.quiet{border-color:#8957e5;color:#c9a6ff}
code{background:#22272f;padding:2px 6px;border-radius:5px;font-size:12px}
"""

JS = r"""
const V = JSON.parse(localStorage.getItem('autostream.verdicts') || '{}');

function save(){ localStorage.setItem('autostream.verdicts', JSON.stringify(V)); }
function slot(clip){
  if (!V[clip]) V[clip] = {ok:[], bad:[], missed:[]};
  return V[clip];
}
function fmt(t){
  const m = Math.floor(t/60), s = (t%60);
  return m + ':' + (s<10?'0':'') + s.toFixed(1);
}

function vote(clip, time, yes){
  const s = slot(clip);
  s.ok = s.ok.filter(x => x !== time);
  s.bad = s.bad.filter(x => x !== time);
  (yes ? s.ok : s.bad).push(time);
  save(); paint(clip);
}

function addMissed(clip){
  const v = document.getElementById('v-' + clip);
  if (!v) return;
  const t = Math.round(v.currentTime * 10) / 10;
  const s = slot(clip);
  if (!s.missed.includes(t)) s.missed.push(t);
  s.missed.sort((a,b) => a-b);
  save(); paint(clip);
}

function dropMissed(clip, t){
  const s = slot(clip);
  s.missed = s.missed.filter(x => x !== t);
  save(); paint(clip);
}

function seek(clip, t){
  const v = document.getElementById('v-' + clip);
  if (!v) return;
  v.currentTime = Math.max(0, t - 2);
  v.play();
}

function paint(clip){
  const s = slot(clip);
  document.querySelectorAll('[data-clip="' + clip + '"][data-time]').forEach(el => {
    const t = parseFloat(el.dataset.time);
    const yes = s.ok.includes(t), no = s.bad.includes(t);
    el.classList.toggle('yes', yes);
    el.classList.toggle('no', no);
    const by = el.querySelector('.b-yes'), bn = el.querySelector('.b-no');
    if (by) by.classList.toggle('on-yes', yes);
    if (bn) bn.classList.toggle('on-no', no);
  });
  const box = document.getElementById('m-' + clip);
  if (box) {
    box.innerHTML = s.missed.length
      ? s.missed.map(t =>
          '<span class="chip"><span onclick="seek(\'' + clip + '\',' + t +
          ')" style="cursor:pointer">' + fmt(t) +
          '</span><b onclick="dropMissed(\'' + clip + '\',' + t +
          ')">x</b></span>').join('')
      : '<span class="none">none marked</span>';
  }
  progress();
}

function progress(){
  let done = 0, total = 0;
  ALL.forEach(c => {
    total += c.times.length;
    const s = V[c.clip] || {ok:[], bad:[]};
    c.times.forEach(t => {
      if (s.ok.includes(t) || s.bad.includes(t)) done++;
    });
  });
  document.getElementById('progress').textContent =
    done + ' of ' + total + ' detections judged';
}

function payload(){
  const out = {};
  ALL.forEach(c => {
    const s = V[c.clip] || {ok:[], bad:[], missed:[]};
    out[c.clip] = {
      game: c.game, kind: c.kind, seconds: c.seconds,
      confirmed: s.ok.slice().sort((a,b)=>a-b),
      rejected: s.bad.slice().sort((a,b)=>a-b),
      missed: (s.missed||[]).slice().sort((a,b)=>a-b),
      judged: s.ok.length + s.bad.length,
      of: c.times.length
    };
  });
  return JSON.stringify(out, null, 2);
}

function download(){
  const b = new Blob([payload()], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(b);
  a.download = 'verdicts.json';
  a.click();
}

function copy(){
  navigator.clipboard.writeText(payload()).then(
    () => { const b = document.getElementById('copybtn');
            b.textContent = 'copied'; setTimeout(()=>b.textContent='Copy JSON',1500); });
}

window.addEventListener('DOMContentLoaded', () => ALL.forEach(c => paint(c.clip)));
"""


def build_page() -> Path:
    rows = manifest()
    dets = detections()
    by_clip = {r["clip"]: r for r in rows}

    made = 0
    cards_all = []
    body = []

    for r in sorted(rows, key=lambda r: (r["game"], r["clip"])):
        clip = r["clip"]
        got = dets.get(clip) or {}
        video = CORPUS / r["file"]
        found = [d["time"] for d in (got.get("detections") or [])]
        cards_all.append({"clip": clip, "game": r["game"], "kind": r["kind"],
                          "seconds": r.get("seconds"), "times": found})

        cards = []
        for d in (got.get("detections") or []):
            t = d["time"]
            name = f"{clip}_{t:08.2f}.jpg".replace(".", "_", 1)
            dest = CORPUS / THUMBS / name
            if thumb(video, t, dest):
                made += 1
                src = f"{THUMBS}/{dest.name}"
            else:
                src = ""
            cards.append(f"""
      <div class="card" data-clip="{clip}" data-time="{t}">
        <img src="{src}" onclick="seek('{clip}',{t})" loading="lazy" alt="">
        <div class="t"><span>{t:.1f}s</span><span>score {d.get('score', 0):.2f}</span></div>
        <div class="vote">
          <button class="b-yes" onclick="vote('{clip}',{t},true)">real</button>
          <button class="b-no" onclick="vote('{clip}',{t},false)">wrong</button>
        </div>
      </div>""")

        kind_tag = ('<span class="tag quiet">quiet - should find nothing</span>'
                    if r["kind"] == "quiet" else '<span class="tag">busy</span>')
        err = got.get("error")
        cards_html = ("".join(cards) if cards else
                      f'<p class="none">{"ERROR: " + err if err else "no detections"}'
                      f'{" - correct, if nothing happens here" if r["kind"] == "quiet" and not err else ""}</p>')

        body.append(f"""
  <section>
    <h2>{clip} {kind_tag}</h2>
    <div class="meta">{r.get('seconds', 0):.0f}s from {r['source_name']} at
      {r['source_offset'] / 60:.1f} min &middot; {got.get('mode', '?')} detector
      &middot; found {len(found)} &middot; <code>{video}</code></div>
    <div class="wrap">
      <div>
        <video id="v-{clip}" src="{r['file']}" controls preload="metadata"></video>
        <div class="pad">
          <button onclick="addMissed('{clip}')">Mark a missed kill here</button>
          <span class="sub">pause on the kill, then press it</span>
        </div>
        <div class="missed">
          <b>Missed kills</b>
          <div class="chips" id="m-{clip}"></div>
        </div>
      </div>
      <div>
        <div class="cards">{cards_html}</div>
      </div>
    </div>
  </section>""")

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>AutoStream clip detector review</title>
<style>{CSS}</style></head>
<body>
<header>
  <div>
    <h1>Clip detector review</h1>
    <div class="sub">Judge each detection, and mark anything it missed.
      Verdicts are saved in this browser as you go.</div>
  </div>
  <div class="spacer"></div>
  <div class="sub" id="progress"></div>
  <button id="copybtn" onclick="copy()">Copy JSON</button>
  <button class="primary" onclick="download()">Save verdicts.json</button>
</header>
{''.join(body)}
<script>const ALL = {json.dumps(cards_all)};</script>
<script>{JS}</script>
</body></html>"""

    out = CORPUS / "review.html"
    out.write_text(html, encoding="utf-8")
    print(f"  {made} thumbnail(s) ready")
    print(f"  written: {out}")
    return out


# ------------------------------------------------------------- importing


def cmd_build(args) -> int:
    out = build_page()
    if not args.no_open:
        webbrowser.open(out.as_uri())
    print("\nJudge each detection, mark anything missed, then press "
          "'Save verdicts.json' and run:")
    print(r"  .venv\Scripts\python.exe tests\verify\review.py import "
          r"%USERPROFILE%\Downloads\verdicts.json")
    return 0


def cmd_import(args) -> int:
    src = Path(args.path)
    if not src.is_file():
        print(f"no such file: {src}")
        return 1
    verdicts = json.loads(src.read_text(encoding="utf-8"))
    rows = {r["clip"]: r for r in manifest()}

    games: dict[str, dict] = {}
    unjudged = []
    for clip, v in verdicts.items():
        row = rows.get(clip)
        if row is None:
            print(f"  [!!] {clip} is not in the manifest - skipped")
            continue
        if v.get("judged", 0) < v.get("of", 0):
            unjudged.append(f"{clip} ({v.get('judged', 0)}/{v.get('of', 0)})")
        # Truth is what you confirmed plus what you said was missed. What the
        # detector reported and you rejected is deliberately NOT here: that is
        # the false-positive set, and its absence from truth is what makes
        # precision measurable at all.
        truth = sorted(set(v.get("confirmed", [])) | set(v.get("missed", [])))
        g = games.setdefault(row["game"], {"clips": {}})
        g["clips"][clip] = {
            "kind": row["kind"],
            "source_name": row["source_name"],
            "source_offset": row["source_offset"],
            "seconds": row.get("seconds"),
            "truth": truth,
            "rejected": sorted(v.get("rejected", [])),
            "floor": dict(DEFAULT_FLOOR),
        }

    if unjudged:
        print("  [!!] not every detection was judged in: "
              + ", ".join(unjudged))
        print("       importing anyway; the unjudged ones count as not-real, "
              "which will understate recall.")

    BASELINES.mkdir(parents=True, exist_ok=True)
    for game, data in sorted(games.items()):
        data["note"] = ("Reviewed by hand against the excerpt. `truth` is what "
                        "a person confirmed plus what they said was missed; "
                        "`rejected` is what the detector reported that is not "
                        "there. Regenerate with review.py, never by hand.")
        p = BASELINES / f"{game}.json"
        p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        n = sum(len(c["truth"]) for c in data["clips"].values())
        print(f"  {p.name}: {len(data['clips'])} excerpt(s), {n} confirmed kill(s)")
    print("\nNow run: .venv\\Scripts\\python.exe tests\\verify\\score.py report")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build")
    b.add_argument("--no-open", action="store_true")
    b.set_defaults(func=cmd_build)
    i = sub.add_parser("import")
    i.add_argument("path")
    i.set_defaults(func=cmd_import)
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
