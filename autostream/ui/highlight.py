r"""The highlight editor: the stream highlight's cut list on a timeline, with what
was said beside it.

WHAT THE PLAYER ASKED FOR (2026-11-01). The highlight video opened "in a timeline
with editing options other than the song reel edit": which moments to keep, the
facecam area, the facecam zoom, the automatic captions. Shown three layouts on his
own Bind footage he chose "a mix of B and C" -- B the timeline with lanes, C the
video edited by its words -- so both are here, editing one project:

    preview (the recording, played cut to cut)  |  what was said, moment by moment
    lanes: moments / face zoom / your captions   |  (fix a caption, cut a line,
      / team captions / mic / game / round ends  |   zoom on the face for a line)
    the selected moment, caption or zoom         |
    face zoom, the facecam box, captions, volume, Make video

THE SECOND PASS (asked after using it): "edit the time frame of a caption", "put a
face cam zoom manually for how much time I want", a "volume timeline for separate
tracks in the recording", "transcription for both audio tracks", "keyframe points"
and an "overall volume level adjuster just like a video editor". So caption blocks
are retimed by their edges and moved by their middle; face zooms are drawn across
their lane; the mic and the game each have a volume line with keyframes (the reel
editor's rules: clips/studio.vol_at); the team-mates' voice comms, on the game
track, are transcribed and captioned a line above the player's.

WHAT IS EDITED is the cut list, never pixels (clips/highlight_edit.py). The preview
plays the RECORDING, skipping what is removed, pushing in on the facecam exactly
where the render will, and -- once the two tracks are copied out of it -- playing
the mic and the game at their own volumes. Nothing is rendered until Make video.

NAMING. Everything is prefixed hl_ and the one global is window.PAGE_HL -- every
view module shares one scope. Its buttons carry data-hl, not data-act, so the Clips
page's own click handler (which owns data-act inside #view-clips) never sees them.
"""
from __future__ import annotations

HIGHLIGHT_HTML: str = r"""
<!-- THE HIGHLIGHT EDITOR. Over the whole Clips page while it is open
     (#view-clips.hl-on hides everything else), so the preview and the timeline
     get the room they need. -->
<div class="card hl-card hide" id="hl-card" aria-label="Edit the highlight video">
  <div class="hl-head">
    <div class="hl-head-text">
      <h2 class="card-title" id="hl-title">Edit the highlight video</h2>
      <p class="card-sub" id="hl-sub"></p>
    </div>
    <div class="hl-head-acts">
      <button class="btn btn-ghost btn-sm" type="button" data-hl="undo" id="hl-undo"
              title="Undo (Ctrl Z)" disabled>Undo</button>
      <button class="btn btn-ghost btn-sm" type="button" data-hl="redo" id="hl-redo"
              title="Redo (Ctrl Shift Z)" disabled>Redo</button>
      <button class="btn btn-sm" type="button" data-hl="close">Done</button>
    </div>
  </div>

  <div class="hl-grid">
    <div class="hl-main">
      <div class="hl-stage" id="hl-stage">
        <video id="hl-video" playsinline preload="metadata"></video>
        <div class="hl-cap is-team hide" id="hl-cap-team"></div>
        <div class="hl-cap hide" id="hl-cap"></div>
        <div class="hl-box hide" id="hl-box"><span class="hl-box-grip" id="hl-box-grip"></span></div>
        <p class="hl-stage-msg hide" id="hl-stage-msg"></p>
      </div>
      <div class="hl-transport">
        <button class="btn btn-sm hl-play" type="button" data-hl="play" id="hl-play"
                aria-label="Play">Play</button>
        <button class="btn btn-ghost btn-sm" type="button" data-hl="prev"
                title="The moment before">Previous moment</button>
        <button class="btn btn-ghost btn-sm" type="button" data-hl="next"
                title="The moment after">Next moment</button>
        <button class="btn btn-ghost btn-sm" type="button" data-hl="addcap"
                title="A new caption where the playhead is">Add caption</button>
        <span class="hl-clock" id="hl-clock">0:00 / 0:00</span>
        <span class="hl-spacer"></span>
        <span class="muted hl-audio-msg" id="hl-audio-msg"></span>
        <label class="hl-scale-label" for="hl-scale">Timeline zoom</label>
        <input type="range" id="hl-scale" min="1" max="40" step="1" value="6">
      </div>
      <div class="hl-lanes" id="hl-lanes">
        <div class="hl-lane-names" id="hl-lane-names"></div>
        <div class="hl-scroll" id="hl-scroll"><div class="hl-track" id="hl-track"></div></div>
      </div>
      <div class="hl-insp" id="hl-insp"></div>
    </div>

    <aside class="hl-said">
      <div class="hl-said-head">
        <h3 class="hl-said-title">What was said</h3>
        <p class="muted hl-said-help">Fix a line's words to fix its caption. Click a line's time to
           hear it and set when it shows.</p>
        <div class="hl-said-tools">
          <span class="hl-seg" role="group" aria-label="Whose lines">
            <button class="hl-seg-btn is-on" type="button" data-hl="said-who" data-v="all">All</button>
            <button class="hl-seg-btn" type="button" data-hl="said-who" data-v="mic">You</button>
            <button class="hl-seg-btn" type="button" data-hl="said-who" data-v="game">Team</button>
          </span>
          <button class="btn btn-sm hide" type="button" data-hl="team-stt" id="hl-team-stt">Write down the team's voice</button>
        </div>
        <p class="muted hl-team-msg hide" id="hl-team-msg"></p>
      </div>
      <div class="hl-said-list" id="hl-said"></div>
    </aside>
  </div>

  <div class="hl-foot">
    <div class="hl-opt">
      <label class="hl-opt-label" for="hl-zoom">Face zoom</label>
      <select class="select" id="hl-zoom" data-hl-change="zoom">
        <option value="">Fit the facecam box</option>
        <option value="1.5">1.5&times;</option>
        <option value="2">2&times;</option>
        <option value="2.5">2.5&times;</option>
        <option value="3">3&times;</option>
      </select>
      <button class="btn btn-sm" type="button" data-hl="box" id="hl-box-btn">Move the facecam box</button>
    </div>
    <div class="hl-opt">
      <button class="switch" type="button" role="switch" id="hl-caps" data-hl="caps"
              aria-checked="false"><span class="switch-track"><span class="switch-thumb"></span></span>
        <span>Captions in the video</span></button>
      <select class="select" id="hl-lang" data-hl-change="lang" aria-label="Caption language">
        <option value="english">In English</option>
        <option value="said">As said</option>
      </select>
    </div>
    <div class="hl-opt">
      <label class="hl-opt-label" for="hl-master">Overall volume</label>
      <input type="range" id="hl-master" min="-10" max="6" step="1" value="0" data-hl-change="master">
      <span class="hl-master-v" id="hl-master-v">0 dB</span>
    </div>
    <div class="hl-make">
      <span class="muted hl-make-msg" id="hl-make-msg"></span>
      <button class="btn btn-ghost btn-sm hide" type="button" data-hl="reveal" id="hl-show">Show the file</button>
      <button class="btn btn-ghost btn-sm hide" type="button" data-hl="stop" id="hl-stop">Stop</button>
      <button class="btn btn-primary" type="button" data-hl="make" id="hl-make">Make video</button>
    </div>
  </div>
</div>
"""

HIGHLIGHT_JS: str = r"""
/* ============================================================ the highlight editor */
const hl = {
  video: '', p: null, groups: [], at: [], total: 0, pieces: null,
  sel: 0, selKind: 'mom', selId: null, cur: -1, undo: [], redo: [], saveT: 0,
  pxs: 6, boxMode: false, drag: null, editing: null, poll: 0, raf: 0, workPoll: 0,
  lastLine: -1, outLen: 0, made: '', tracks: 0, audio: {}, aud: null, who: 'all', lanes: []
};
const HL_FIT_PAD = 1.12, HL_ZOOM_MOST = 3.2, HL_SHORTEST = 0.5, HL_CAP_LEAST = 0.3;
const HL_VOL_TOP = 12, HL_VOL_BOT = -40, HL_LANE_GAP = 6;
const HL_LANES = [
  {k: 'mom', name: 'Moments', h: 24},
  {k: 'zoom', name: 'Face zoom', h: 22},
  {k: 'capmic', name: 'Your captions', h: 22, track: 'mic'},
  {k: 'capgame', name: 'Team captions', h: 22, track: 'game'},
  {k: 'volmic', name: 'Mic volume', h: 44, vol: 'mic'},
  {k: 'volgame', name: 'Game volume', h: 44, vol: 'game'},
  {k: 'end', name: 'Round ends', h: 14}
];

function hl_el(id) { return document.getElementById(id); }
/* Times on a four-hour recording read 3:19:39, not 199:39. */
function hl_fmt(s, fine) {
  s = Math.max(0, s || 0);
  var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  var sec = fine ? x.toFixed(1) : String(Math.floor(x));
  if (x < 10) sec = '0' + sec;
  return h ? h + ':' + (m < 10 ? '0' : '') + m + ':' + sec : m + ':' + sec;
}
function hl_fmtFine(s) { return hl_fmt(s, true); }
function hl_r3(x) { return Math.round(x * 1000) / 1000; }

/* ---- the project, as the page sees it -------------------------------------- */

function hl_len(c) { return Math.max(0, c.end - c.start); }

/* Moments: consecutive cuts of one stretch. The cold open is its own. */
function hl_group() {
  var p = hl.p, out = [];
  p.cuts.forEach(function (c, i) {
    var g = out[out.length - 1];
    if (g && g.kind === c.kind && g.stretch === c.stretch && c.kind !== 'cold') g.cuts.push(i);
    else out.push({kind: c.kind, stretch: c.stretch, cuts: [i]});
  });
  out.forEach(function (g) {
    var m = (p.moments || [])[g.stretch] || {};
    g.name = g.kind === 'cold' ? 'Opening' : (m.name || 'Moment');
    g.match = m.match || '';
    g.from = g.kind === 'cold' ? ('Replays ' + (m.name || 'the best moment')) : '';
  });
  hl.groups = out;
}

function hl_layout() {
  var at = [], t = 0;
  hl.p.cuts.forEach(function (c) { at.push(t); t += hl_len(c); });
  hl.at = at; hl.total = t; hl.pieces = null;
}

function hl_capText(ln) {
  var lang = (hl.p.captions || {}).lang || 'english';
  return lang === 'english' && ln.english ? ln.english : (ln.text || '');
}
function hl_capField(ln) {
  var lang = (hl.p.captions || {}).lang || 'english';
  return lang === 'english' && ln.english ? 'english' : 'text';
}

function hl_minus(a, b, holes) {
  var out = [[a, b]];
  holes.forEach(function (h) {
    var next = [];
    out.forEach(function (s) {
      if (h[1] <= s[0] || h[0] >= s[1]) { next.push(s); return; }
      if (h[0] > s[0]) next.push([s[0], h[0]]);
      if (h[1] < s[1]) next.push([h[1], s[1]]);
    });
    out = next;
  });
  return out;
}

/* The same cut list clips/highlight_edit.pieces() renders: kept cuts, cut lines
   taken out, face lines and drawn face zooms as the zoom. Kept in step with it by
   tests/test_highlight_edit.py, which runs both on one project. */
function hl_pieces() {
  if (hl.pieces) return hl.pieces;
  var lines = hl.p.lines || [];
  var holes = lines.filter(function (l) { return l.cut; }).map(function (l) { return [l.start, l.end]; });
  var faces = lines.filter(function (l) { return l.face && !l.cut; }).map(function (l) { return [l.start, l.end]; })
    .concat((hl.p.zooms || []).map(function (z) { return [z.start, z.end]; }));
  var out = [];
  hl.p.cuts.forEach(function (c, i) {
    if (!c.keep || hl_len(c) < HL_SHORTEST) return;
    var base = c.zoom ? 'cam' : (c.layout === 'cam' ? 'game' : (c.layout || 'game'));
    hl_minus(c.start, c.end, holes).forEach(function (s) {
      if (s[1] - s[0] < HL_SHORTEST) return;
      var marks = [s[0], s[1]];
      faces.forEach(function (f) { f.forEach(function (x) { if (x > s[0] && x < s[1]) marks.push(x); }); });
      marks.sort(function (x, y) { return x - y; });
      var segs = [];
      for (var k = 0; k + 1 < marks.length; k++) {
        var x = marks[k], y = marks[k + 1];
        if (y - x < 1e-6) continue;
        var mid = (x + y) / 2;
        var lay = faces.some(function (f) { return f[0] <= mid && mid < f[1]; }) ? 'cam' : base;
        var last = segs[segs.length - 1];
        if (last && last.layout === lay) last.b = y; else segs.push({cut: i, a: x, b: y, layout: lay});
      }
      for (var j = 0; j < segs.length;) {
        if (segs[j].b - segs[j].a < HL_SHORTEST && segs.length > 1) {
          var n = j > 0 ? j - 1 : j + 1;
          segs[n].a = Math.min(segs[n].a, segs[j].a); segs[n].b = Math.max(segs[n].b, segs[j].b);
          segs.splice(j, 1); j = 0; continue;
        }
        if (j && segs[j - 1].layout === segs[j].layout) { segs[j - 1].b = segs[j].b; segs.splice(j, 1); continue; }
        j++;
      }
      out = out.concat(segs);
    });
  });
  hl.pieces = out;
  hl.outLen = out.reduce(function (s, x) { return s + x.b - x.a; }, 0);
  return out;
}

/* A volume line's level, in dB, at recording second t: clips/studio.vol_at. */
function hl_volAt(keys, flat, t) {
  if (!keys || !keys.length) return +flat || 0;
  if (t <= keys[0][0]) return keys[0][1];
  for (var i = 0; i + 1 < keys.length; i++) {
    var a = keys[i], b = keys[i + 1];
    if (t <= b[0]) return a[1] + (b[1] - a[1]) * (t - a[0]) / Math.max(b[0] - a[0], 1e-9);
  }
  return keys[keys.length - 1][1];
}
function hl_lane(name) {
  var v = hl.p.volume || (hl.p.volume = {master: 0, mic: {db: 0, keys: []}, game: {db: 0, keys: []}});
  return v[name] || (v[name] = {db: 0, keys: []});
}

/* ---- opening and saving ---------------------------------------------------- */

async function hl_open(video) {
  if (!video) return;
  var r = await API.get('/api/clips/highlight?video=' + encodeURIComponent(video));
  if (!r || r.error) { toast((r && r.error) || 'That video cannot be opened.', 'error'); return; }
  hl_dropAudio();
  hl.video = video; hl.p = r.project; hl.undo = []; hl.redo = []; hl.sel = 0; hl.cur = -1;
  hl.selKind = 'mom'; hl.selId = null;
  hl.made = r.made || ''; hl.tracks = r.tracks || 0; hl.audio = r.audio || {};
  hl.p.zooms = hl.p.zooms || [];
  hl_lane('mic'); hl_lane('game');
  hl.lanes = HL_LANES.filter(function (l) { return !l.vol || hl.tracks >= 3; });
  hl_group(); hl_layout(); hl_pieces();
  var view = hl_el('view-clips');
  if (view) view.classList.add('hl-on');
  hl_el('hl-card').classList.remove('hide');
  var v = hl_el('hl-video');
  var msg = hl_el('hl-stage-msg');
  msg.classList.add('hide');
  v.muted = false;
  if (r.source_ok) {
    v.src = '/api/clips/highlight/source?k=' + encodeURIComponent(SHELL_K) +
            '&video=' + encodeURIComponent(video);
  } else {
    v.removeAttribute('src');
    msg.textContent = 'The recording this was cut from is not on this PC any more, so it cannot be ' +
                      'previewed or made again.';
    msg.classList.remove('hide');
  }
  var first = hl_pieces()[0];
  if (first) { hl.cur = first.cut; v.addEventListener('loadedmetadata', function once() {
    v.removeEventListener('loadedmetadata', once); if (hl.cur >= 0) v.currentTime = hl.p.cuts[hl.cur].start;
  }); }
  hl_render();
  hl_paintRender(r.render || {});
  if (r.render && (r.render.state === 'running' || r.render.state === 'waiting')) hl_pollRender();
  hl_paintWork(r.work || {});
  /* The mic and the game, copied out of the recording once (the player's yes),
     so each can be heard at its own volume here. */
  if (r.source_ok && hl.tracks >= 3) {
    if (hl.audio.mic && hl.audio.game) hl_attachAudio();
    else { API.post('/api/clips/highlight/tracks', {video: video}); hl_pollWork(); }
  }
  if ((r.work || {}).transcribe && r.work.transcribe.state === 'running') hl_pollWork();
  if (!hl.raf) hl.raf = requestAnimationFrame(hl_tick);
  window.scrollTo(0, 0);
}

function hl_close() {
  hl_save(true);
  var v = hl_el('hl-video');
  if (v) { v.pause(); v.removeAttribute('src'); v.load(); }
  hl_dropAudio();
  hl_el('hl-card').classList.add('hide');
  var view = hl_el('view-clips');
  if (view) view.classList.remove('hl-on');
  hl.p = null; hl.video = '';
  clearTimeout(hl.workPoll);
  if (hl.raf) { cancelAnimationFrame(hl.raf); hl.raf = 0; }
}

function hl_edits() {
  var p = hl.p;
  return {
    cuts: p.cuts.map(function (c) { return {id: c.id, start: c.start, end: c.end, keep: c.keep, zoom: c.zoom}; }),
    lines: (p.lines || []).map(function (l) {
      return {id: l.id, start: l.start, end: l.end, text: l.text, english: l.english, show: l.show,
              cut: l.cut, face: l.face, track: l.track || 'mic'};
    }),
    zooms: (p.zooms || []).map(function (z) { return {id: z.id, start: z.start, end: z.end}; }),
    volume: JSON.parse(JSON.stringify(p.volume || {})),
    cam_box: p.cam_box, cam_zoom: p.cam_zoom, captions: p.captions
  };
}

async function hl_save(now) {
  clearTimeout(hl.saveT);
  if (!hl.p) return;
  var go = async function () {
    if (!hl.p) return;
    try {
      var r = await API.post('/api/clips/highlight/save', {video: hl.video, project: hl_edits()});
      if (r && r.error) toast(r.error, 'error');
    } catch (e) { toast('Your changes could not be saved.', 'error'); }
  };
  if (now) return go();
  hl.saveT = setTimeout(go, 600);
}

function hl_snap() { return JSON.stringify(hl_edits()); }
function hl_restore(s) {
  var e = JSON.parse(s), p = hl.p, cuts = {};
  e.cuts.forEach(function (c) { cuts[c.id] = c; });
  p.cuts.forEach(function (c) { Object.assign(c, cuts[c.id] || {}); });
  p.lines = e.lines; p.zooms = e.zooms; p.volume = e.volume;
  p.cam_box = e.cam_box; p.cam_zoom = e.cam_zoom; p.captions = e.captions;
}

/* Every change goes through here: one undo step, a redraw, a save. */
function hl_change(fn, keepSaid) {
  hl.undo.push(hl_snap());
  if (hl.undo.length > 80) hl.undo.shift();
  hl.redo = [];
  fn();
  hl_layout();
  hl_render(keepSaid);
  hl_save();
}

function hl_undoRedo(back) {
  var from = back ? hl.undo : hl.redo, to = back ? hl.redo : hl.undo;
  if (!from.length) return;
  to.push(hl_snap());
  hl_restore(from.pop());
  hl_layout(); hl_render(); hl_save();
}

/* ---- drawing ---------------------------------------------------------------- */

function hl_render(keepSaid) {
  if (!hl.p) return;
  hl_pieces();
  var kept = hl.groups.filter(function (g) { return g.cuts.some(function (i) { return hl.p.cuts[i].keep; }); }).length;
  hl_el('hl-sub').textContent = hl_fmt(hl.outLen) + ' long, ' + kept + ' of ' + hl.groups.length +
    ' moments kept. Nothing is made until you press Make video; your changes are saved as you go.';
  hl_el('hl-undo').disabled = !hl.undo.length;
  hl_el('hl-redo').disabled = !hl.redo.length;
  hl_renderTrack();
  hl_renderInsp();
  if (!keepSaid) hl_renderSaid();
  var caps = hl_el('hl-caps'), cap = hl.p.captions || {};
  caps.setAttribute('aria-checked', cap.on ? 'true' : 'false');
  var lang = hl_el('hl-lang');
  var anyEnglish = (hl.p.lines || []).some(function (l) { return l.english; });
  lang.value = cap.lang || 'english';
  lang.disabled = !anyEnglish;
  hl_el('hl-zoom').value = hl.p.cam_zoom ? String(hl.p.cam_zoom) : '';
  var m = (hl.p.volume || {}).master || 0;
  hl_el('hl-master').value = String(m);
  hl_el('hl-master-v').textContent = (m > 0 ? '+' : '') + m + ' dB';
  hl_el('hl-box-btn').textContent = hl.boxMode ? 'Done moving the box' :
    (hl.p.cam_box ? 'Move the facecam box' : 'Mark the facecam');
  hl_el('hl-team-stt').classList.toggle('hide', hl.tracks < 3);
  hl_placeBox();
}

/* Where a cut's stretch of the recording sits on the timeline (seconds). */
function hl_x(i, t) { return hl.at[i] + Math.max(0, Math.min(hl_len(hl.p.cuts[i]), t - hl.p.cuts[i].start)); }

function hl_blocks(i, a, b) {
  /* [a, b) of the recording as it appears inside cut i, or null. */
  var c = hl.p.cuts[i];
  var x = Math.max(a, c.start), y = Math.min(b, c.end);
  return y - x > 0.05 ? [hl_x(i, x), hl_x(i, y)] : null;
}

/* A point on the timeline -> the cut there and the recording second it shows. */
function hl_hit(clientX) {
  var tr = hl_el('hl-track').getBoundingClientRect();
  var T = (clientX - tr.left) / hl.pxs, p = hl.p;
  for (var i = 0; i < p.cuts.length; i++) {
    if (T < hl.at[i] + hl_len(p.cuts[i]) || i === p.cuts.length - 1) {
      return {i: i, t: Math.max(p.cuts[i].start, Math.min(p.cuts[i].end, p.cuts[i].start + (T - hl.at[i])))};
    }
  }
  return {i: 0, t: 0};
}

function hl_laneTops() {
  var tops = {}, y = 4;
  hl.lanes.forEach(function (l) { tops[l.k] = y; y += l.h + HL_LANE_GAP; });
  tops._h = y - HL_LANE_GAP + 4;
  return tops;
}

function hl_volY(db, h) { return (HL_VOL_TOP - Math.max(HL_VOL_BOT, Math.min(HL_VOL_TOP, db))) / (HL_VOL_TOP - HL_VOL_BOT) * h; }
function hl_volDb(y, h) { return Math.round((HL_VOL_TOP - y / h * (HL_VOL_TOP - HL_VOL_BOT)) * 2) / 2; }

function hl_renderTrack() {
  var p = hl.p, pxs = hl.pxs, h = '', tops = hl_laneTops();
  var W = Math.max(hl.total * pxs, 200);
  var px = function (s) { return (s * pxs).toFixed(1) + 'px'; };
  var pos = function (k, a, b) {
    return 'left:' + px(a) + ';width:' + px(Math.max(0, b - a)) + ';top:' + tops[k] + 'px';
  };
  /* the lanes' own grounds, under everything: press one to seek, or to draw */
  hl.lanes.forEach(function (l) {
    if (l.vol) return;
    h += '<div class="hl-ground" data-lane="' + l.k + '" style="top:' + tops[l.k] + 'px;height:' + l.h + 'px"></div>';
  });
  /* moments */
  hl.groups.forEach(function (g, k) {
    var a = hl.at[g.cuts[0]], last = g.cuts[g.cuts.length - 1];
    var b = hl.at[last] + hl_len(p.cuts[last]);
    var on = g.cuts.some(function (i) { return p.cuts[i].keep; });
    var sel = hl.selKind === 'mom' && k === hl.sel;
    h += '<div class="hl-blk hl-mom' + (on ? '' : ' is-off') + (sel ? ' is-sel' : '') +
         (g.kind === 'cold' ? ' is-cold' : '') + '" style="' + pos('mom', a, b) +
         '" data-hl="mom" data-k="' + k + '" title="' + esc(g.name) + '">' +
         '<span class="hl-edge hl-edge-a" data-edge="a" data-i="' + g.cuts[0] + '"></span>' +
         '<span class="hl-blk-text">' + esc(g.name) + '</span>' +
         '<span class="hl-edge hl-edge-b" data-edge="b" data-i="' + last + '"></span></div>';
  });
  /* face zoom: whole cuts, face lines, and the zooms drawn by hand */
  p.cuts.forEach(function (c, i) {
    if (!c.zoom && c.layout !== 'cam') return;
    h += '<div class="hl-blk hl-zm' + (c.zoom ? '' : ' is-off') + (c.keep ? '' : ' is-gone') +
         '" style="' + pos('zoom', hl.at[i], hl.at[i] + hl_len(c)) + '" data-hl="zoomcut" data-i="' + i +
         '" title="' + (c.zoom ? 'Face zoom on this cut: click to turn it off' : 'Face zoom is off here: click to turn it on') + '"></div>';
  });
  (p.zooms || []).forEach(function (z) {
    p.cuts.forEach(function (c, i) {
      var s = hl_blocks(i, z.start, z.end);
      if (!s) return;
      var sel = hl.selKind === 'zoom' && hl.selId === z.id;
      h += '<div class="hl-blk hl-zm is-drawn' + (sel ? ' is-sel' : '') + (c.keep ? '' : ' is-gone') +
           '" style="' + pos('zoom', s[0], s[1]) + '" data-zm="' + z.id + '" title="Face zoom, ' +
           (z.end - z.start).toFixed(1) + ' s: drag its edges to change how long">' +
           '<span class="hl-cedge" data-ce="a"></span><span class="hl-cedge hl-cedge-b" data-ce="b"></span></div>';
    });
  });
  (p.lines || []).forEach(function (l) {
    var lane = l.track === 'game' ? 'capgame' : 'capmic';
    if (!tops.hasOwnProperty(lane)) return;
    p.cuts.forEach(function (c, i) {
      var s = hl_blocks(i, l.start, l.end);
      if (!s) return;
      if (l.face && !l.cut) {
        h += '<div class="hl-blk hl-zm is-line" style="' + pos('zoom', s[0], s[1]) +
             '" data-hl="zoomline" data-l="' + l.id + '" title="Face zoom for this line: click to turn it off"></div>';
      }
      var sel = hl.selKind === 'cap' && hl.selId === l.id;
      h += '<div class="hl-blk hl-cp' + (l.track === 'game' ? ' is-team' : '') +
           (l.cut ? ' is-cut' : (l.show ? '' : ' is-off')) + (c.keep ? '' : ' is-gone') + (sel ? ' is-sel' : '') +
           '" style="' + pos(lane, s[0], s[1]) + '" data-cap="' + l.id + '" title="' + esc(hl_capText(l)) + '">' +
           '<span class="hl-cedge" data-ce="a"></span><span class="hl-blk-text">' + esc(hl_capText(l)) + '</span>' +
           '<span class="hl-cedge hl-cedge-b" data-ce="b"></span></div>';
    });
  });
  /* round ends */
  p.cuts.forEach(function (c, i) {
    if (c.layout !== 'result' || !tops.hasOwnProperty('end')) return;
    h += '<div class="hl-blk hl-end' + (c.keep ? '' : ' is-off') + '" style="' + pos('end', hl.at[i], hl.at[i] + hl_len(c)) +
         ';height:14px" data-hl="endcut" data-i="' + i + '" title="' +
         esc(c.caption || 'The round ends') + (c.keep ? '' : ' (removed)') + '"></div>';
  });
  /* the volume lines */
  hl.lanes.forEach(function (l) {
    if (l.vol) h += hl_volSvg(l, tops[l.k], W);
  });
  h += '<div class="hl-head-line" id="hl-playhead"></div>';
  var tr = hl_el('hl-track');
  tr.style.width = W + 'px';
  tr.style.height = tops._h + 'px';
  tr.innerHTML = h;
  var names = hl_el('hl-lane-names');
  names.innerHTML = hl.lanes.map(function (l) {
    var clear = l.vol && hl_lane(l.vol).keys.length
      ? '<button class="hl-lane-clear" type="button" data-hl="volclear" data-v="' + l.vol + '" title="Take every point off this line">Clear</button>' : '';
    return '<span class="hl-lane-name" style="height:' + l.h + 'px;line-height:' + Math.min(l.h, 22) + 'px">' +
      esc(l.name) + clear + '</span>';
  }).join('');
  hl_paintHead();
}

function hl_volSvg(l, top, W) {
  var p = hl.p, lane = hl_lane(l.vol), keys = lane.keys, H = l.h, pxs = hl.pxs;
  var paths = '', dots = '';
  p.cuts.forEach(function (c, i) {
    var x0 = hl.at[i] * pxs, pts = [[x0, hl_volY(hl_volAt(keys, lane.db, c.start), H)]];
    keys.forEach(function (k, n) {
      if (k[0] > c.start && k[0] < c.end) {
        var x = (hl.at[i] + k[0] - c.start) * pxs, y = hl_volY(k[1], H);
        pts.push([x, y]);
        dots += '<circle class="hl-vk" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="4.5" data-vk="' + n +
                '"><title>' + (k[1] > 0 ? '+' : '') + k[1] + ' dB at ' + hl_fmtFine(k[0]) + '</title></circle>';
      }
    });
    pts.push([(hl.at[i] + hl_len(c)) * pxs, hl_volY(hl_volAt(keys, lane.db, c.end), H)]);
    paths += '<polyline class="hl-vl' + (c.keep ? '' : ' is-gone') + '" points="' +
             pts.map(function (q) { return q[0].toFixed(1) + ',' + q[1].toFixed(1); }).join(' ') + '"/>';
  });
  var zero = hl_volY(0, H).toFixed(1);
  return '<svg class="hl-vol" data-vol="' + l.vol + '" width="' + W + '" height="' + H + '" style="top:' + top +
    'px" aria-label="' + esc(l.name) + ': click to add a point, drag a point to move it, double-click it to remove it">' +
    '<rect class="hl-vol-bg" x="0" y="0" width="' + W + '" height="' + H + '"/>' +
    '<line class="hl-v0" x1="0" x2="' + W + '" y1="' + zero + '" y2="' + zero + '"/>' + paths + dots + '</svg>';
}

function hl_line(id) { return (hl.p.lines || []).filter(function (l) { return l.id === id; })[0]; }
function hl_zoom(id) { return (hl.p.zooms || []).filter(function (z) { return z.id === id; })[0]; }
function hl_nextId(list) { return list.reduce(function (m, x) { return Math.max(m, x.id); }, -1) + 1; }

function hl_nudges(act, edge, id) {
  return '<span class="hl-nudge">' + [-1, -0.1, 0.1, 1].map(function (d) {
    return '<button class="btn btn-ghost btn-sm" type="button" data-hl="' + act + '" data-id="' + id +
      '" data-edge="' + edge + '" data-d="' + d + '">' + (d > 0 ? '+' : '&minus;') + Math.abs(d) + (Math.abs(d) >= 1 ? 's' : '') + '</button>';
  }).join('') + '</span>';
}

function hl_renderInsp() {
  var host = hl_el('hl-insp'), p = hl.p;
  if (hl.selKind === 'cap' && hl_line(hl.selId)) {
    var l = hl_line(hl.selId), f = hl_capField(l);
    host.innerHTML =
      '<div class="hl-insp-head"><div><b>Caption</b><span class="muted"> ' + (l.track === 'game' ? 'Team' : 'You') + ', shown ' +
        (l.end - l.start).toFixed(1) + ' s</span></div><div class="hl-insp-acts">' +
        '<select class="select" data-hl-change="captrack" aria-label="Who says it">' +
          '<option value="mic"' + (l.track !== 'game' ? ' selected' : '') + '>You</option>' +
          '<option value="game"' + (l.track === 'game' ? ' selected' : '') + '>Team</option></select>' +
        '<button class="btn btn-sm" type="button" data-hl="show" data-l="' + l.id + '">' + (l.show ? 'Hide caption' : 'Show caption') + '</button>' +
        '<button class="btn btn-sm" type="button" data-hl="capdel">Delete</button></div></div>' +
      '<input class="input hl-cap-input" id="hl-cap-input" type="text" value="' + esc(l[f] || '') +
        '" data-field="' + f + '" data-l="' + l.id + '" aria-label="The caption\'s words">' +
      '<div class="hl-trim"><span class="hl-trim-label">Shows at <b>' + hl_fmtFine(l.start) + '</b></span>' +
        hl_nudges('capnudge', 'a', l.id) +
        '<span class="hl-trim-label">Until <b>' + hl_fmtFine(l.end) + '</b></span>' + hl_nudges('capnudge', 'b', l.id) + '</div>' +
      '<div class="hl-insp-acts"><button class="btn btn-ghost btn-sm" type="button" data-hl="capsplit">Split at the playhead</button>' +
        '<button class="btn btn-ghost btn-sm" type="button" data-hl="capmerge">Join with the next caption</button></div>';
    return;
  }
  if (hl.selKind === 'zoom' && hl_zoom(hl.selId)) {
    var z = hl_zoom(hl.selId);
    host.innerHTML =
      '<div class="hl-insp-head"><div><b>Face zoom</b><span class="muted"> ' + (z.end - z.start).toFixed(1) + ' s</span></div>' +
        '<button class="btn btn-sm" type="button" data-hl="zoomdel">Delete</button></div>' +
      '<div class="hl-trim"><span class="hl-trim-label">From <b>' + hl_fmtFine(z.start) + '</b></span>' + hl_nudges('zoomnudge', 'a', z.id) +
        '<span class="hl-trim-label">To <b>' + hl_fmtFine(z.end) + '</b></span>' + hl_nudges('zoomnudge', 'b', z.id) + '</div>';
    return;
  }
  hl.selKind = 'mom';
  var g = hl.groups[hl.sel];
  if (!g) { host.innerHTML = ''; return; }
  var on = g.cuts.some(function (i) { return p.cuts[i].keep; });
  var a = p.cuts[g.cuts[0]], b = p.cuts[g.cuts[g.cuts.length - 1]];
  var parts = g.cuts.map(function (i) {
    var c = p.cuts[i];
    var what = c.layout === 'result' ? 'Round end' : (c.zoom ? 'Face zoom' : 'Game');
    return '<li class="hl-part' + (c.keep ? '' : ' is-off') + '">' +
      '<button class="hl-part-seek" type="button" data-hl="seekcut" data-i="' + i + '">' +
      '<span class="hl-part-t">' + hl_fmtFine(c.start) + '</span> ' + esc(what) + ', ' + hl_len(c).toFixed(1) + ' s</button>' +
      '<button class="btn btn-ghost btn-sm" type="button" data-hl="zoomcut" data-i="' + i + '">' +
        (c.zoom ? 'No face zoom' : 'Face zoom') + '</button>' +
      '<button class="btn btn-ghost btn-sm" type="button" data-hl="keepcut" data-i="' + i + '">' +
        (c.keep ? 'Remove' : 'Put back') + '</button></li>';
  }).join('');
  host.innerHTML =
    '<div class="hl-insp-head"><div><b>' + esc(g.name) + '</b>' +
      '<span class="muted"> ' + esc(g.from || g.match) + '</span></div>' +
      '<button class="btn btn-sm' + (on ? '' : ' btn-primary') + '" type="button" data-hl="keepmom">' +
        (on ? 'Remove this moment' : 'Put this moment back') + '</button></div>' +
    '<div class="hl-trim"><span class="hl-trim-label">Starts at <b>' + hl_fmtFine(a.start) + '</b></span>' +
      hl_nudges('nudge', 'a', g.cuts[0]) +
      '<span class="hl-trim-label">Ends at <b>' + hl_fmtFine(b.end) + '</b></span>' + hl_nudges('nudge', 'b', g.cuts[g.cuts.length - 1]) +
    '</div><ol class="hl-parts">' + parts + '</ol>';
}

/* What was said, moment by moment. A line belongs to the first moment whose
   planned span (with a little either side) holds it. */
function hl_renderSaid() {
  var p = hl.p, host = hl_el('hl-said');
  var lines = (p.lines || []).filter(function (l) { return hl.who === 'all' || (l.track || 'mic') === hl.who; });
  if (!(p.lines || []).length) {
    host.innerHTML = '<p class="muted hl-said-empty">No transcript for this video. What you said is ' +
      'written down when the video is made on a PC with a graphics card and speech-to-text installed.</p>';
    return;
  }
  if (!lines.length) {
    host.innerHTML = '<p class="muted hl-said-empty">' + (hl.who === 'game'
      ? 'Nothing from your team yet. Press "Write down the team\'s voice" to transcribe the game\'s sound.'
      : 'Nothing here.') + '</p>';
    return;
  }
  var used = {}, h = '';
  hl.groups.forEach(function (g, k) {
    if (g.kind === 'cold') return;
    var lo = Infinity, hi = -Infinity;
    g.cuts.forEach(function (i) {
      var c = p.cuts[i], pl = c.planned || [c.start, c.end];
      lo = Math.min(lo, c.start, pl[0]); hi = Math.max(hi, c.end, pl[1]);
    });
    var mine = lines.filter(function (l) { return !used[l.id] && l.end > lo - 6 && l.start < hi + 6; });
    var on = g.cuts.some(function (i) { return p.cuts[i].keep; });
    h += '<section class="hl-said-mom' + (on ? '' : ' is-off') + (k === hl.sel && hl.selKind === 'mom' ? ' is-sel' : '') + '">' +
         '<button class="hl-said-name" type="button" data-hl="mom" data-k="' + k + '">' + esc(g.name) +
         (on ? '' : ' <span class="hl-chip">Removed</span>') + '</button>';
    if (!mine.length) h += '<p class="muted hl-said-none">Nothing said.</p>';
    mine.forEach(function (l) {
      used[l.id] = true;
      var inside = g.cuts.some(function (i) { var c = p.cuts[i]; return c.keep && l.end > c.start && l.start < c.end; });
      var field = hl_capField(l);
      var team = l.track === 'game';
      h += '<div class="hl-line' + (l.cut ? ' is-cut' : '') + (inside ? '' : ' is-out') + (l.face ? ' is-face' : '') +
           (team ? ' is-team' : '') + (hl.selKind === 'cap' && hl.selId === l.id ? ' is-sel' : '') +
           '" id="hl-line-' + l.id + '" data-l="' + l.id + '">' +
           '<button class="hl-line-t" type="button" data-hl="seekline" data-l="' + l.id + '">' + hl_fmt(l.start) + '</button>' +
           '<div class="hl-line-body">' +
             (team ? '<span class="hl-chip is-team">Team</span>' : '') +
             '<span class="hl-line-text" contenteditable="' + (l.cut ? 'false' : 'plaintext-only') +
               '" spellcheck="true" data-field="' + field + '" data-l="' + l.id + '">' + esc(l[field] || '') + '</span>' +
             (field === 'english' && l.text ? '<span class="hl-line-orig">' + esc(l.text) + '</span>' : '') +
             (inside ? '' : '<span class="hl-line-orig">Not in the video</span>') +
           '</div>' +
           '<div class="hl-line-acts">' +
             '<button class="hl-tog' + (l.show && !l.cut ? ' is-on' : '') + '" type="button" data-hl="show" data-l="' + l.id +
               '" title="Show this line as a caption"' + (l.cut ? ' disabled' : '') + '>Caption</button>' +
             '<button class="hl-tog' + (l.face ? ' is-on' : '') + '" type="button" data-hl="face" data-l="' + l.id +
               '" title="Zoom on your face while this is said"' + (l.cut ? ' disabled' : '') + '>Face</button>' +
             '<button class="hl-tog' + (l.cut ? ' is-on is-danger' : '') + '" type="button" data-hl="cut" data-l="' + l.id +
               '" title="' + (l.cut ? 'Cut out of the video: click to put it back' : 'Take this line out of the video') +
               '">Cut</button>' +
           '</div></div>';
    });
    h += '</section>';
  });
  host.innerHTML = h;
}

/* ---- the preview -------------------------------------------------------------- */

function hl_pieceAt(i, t) {
  var P = hl_pieces();
  for (var k = 0; k < P.length; k++) if (P[k].cut === i && t >= P[k].a - 0.02 && t < P[k].b) return k;
  return -1;
}

function hl_nextPiece(i, t) {
  var P = hl_pieces();
  for (var k = 0; k < P.length; k++) if (P[k].cut > i || (P[k].cut === i && P[k].a >= t - 0.02)) return k;
  return -1;
}

function hl_seek(i, t, keepPlaying) {
  var v = hl_el('hl-video'), c = hl.p.cuts[i];
  if (!c) return;
  hl.cur = i;
  var to = Math.max(c.start, Math.min(c.end - 0.05, t));
  if (Math.abs(v.currentTime - to) > 0.04) v.currentTime = to;
  if (!keepPlaying) hl_paintHead();
}

function hl_goPiece(k) {
  var v = hl_el('hl-video'), P = hl_pieces();
  if (k < 0 || k >= P.length) { v.pause(); return; }
  hl.cur = P[k].cut;
  if (Math.abs(v.currentTime - P[k].a) > 0.06) v.currentTime = P[k].a;
}

function hl_zoomOf(box) {
  if (hl.p.cam_zoom) return Math.max(1, Math.min(hl.p.cam_zoom, HL_ZOOM_MOST));
  return Math.max(1, Math.min(1 / (box[2] * HL_FIT_PAD), 1 / (box[3] * HL_FIT_PAD), HL_ZOOM_MOST));
}

/* The two tracks, each at its own volume: two hidden players kept on the
   video's clock, through Web Audio so a line can go above 0 dB. */
function hl_attachAudio() {
  hl_dropAudio();
  var Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx || !hl.video) return;
  var ctx = new Ctx(), master = ctx.createGain(), aud = {ctx: ctx, master: master};
  master.connect(ctx.destination);
  ['mic', 'game'].forEach(function (name) {
    var el = new Audio();
    el.preload = 'auto';
    el.src = '/api/clips/highlight/audio?k=' + encodeURIComponent(SHELL_K) + '&video=' +
             encodeURIComponent(hl.video) + '&track=' + name;
    var g = ctx.createGain();
    ctx.createMediaElementSource(el).connect(g);
    g.connect(master);
    aud[name] = {el: el, gain: g};
  });
  hl.aud = aud;
  hl_el('hl-video').muted = true;
  hl_el('hl-audio-msg').textContent = '';
}

function hl_dropAudio() {
  var a = hl.aud;
  if (!a) return;
  ['mic', 'game'].forEach(function (n) { if (a[n]) { a[n].el.pause(); a[n].el.removeAttribute('src'); } });
  try { a.ctx.close(); } catch (e) { /* already closed */ }
  hl.aud = null;
  var v = hl_el('hl-video');
  if (v) v.muted = false;
}

function hl_syncAudio(v, t) {
  var a = hl.aud;
  if (!a) return;
  var m = Math.pow(10, (((hl.p.volume || {}).master) || 0) / 20);
  a.master.gain.setTargetAtTime(m, a.ctx.currentTime, 0.03);
  ['mic', 'game'].forEach(function (name) {
    var lane = hl_lane(name), x = a[name];
    x.gain.gain.setTargetAtTime(Math.pow(10, hl_volAt(lane.keys, lane.db, t) / 20), a.ctx.currentTime, 0.03);
    if (v.paused || v.seeking) { if (!x.el.paused) x.el.pause(); return; }
    if (Math.abs(x.el.currentTime - t) > 0.15) x.el.currentTime = t;
    if (x.el.paused) { var pr = x.el.play(); if (pr && pr.catch) pr.catch(function () {}); }
  });
}

function hl_tick() {
  hl.raf = requestAnimationFrame(hl_tick);
  var view = hl_el('view-clips'), v = hl_el('hl-video');
  if (!hl.p || !v) return;
  if (!view || !view.classList.contains('is-active')) { if (!v.paused) v.pause(); hl_syncAudio(v, v.currentTime); return; }
  var i = hl.cur, c = hl.p.cuts[i];
  if (!c) return;
  var t = v.currentTime;
  if (!v.paused && !v.seeking) {
    var k = hl_pieceAt(i, t);
    if (k >= 0) {
      if (t >= hl_pieces()[k].b - 0.03) hl_goPiece(k + 1);
    } else if (t >= c.end - 0.03 || !c.keep) {
      /* Playing a removed moment, to judge it: to its end, then on. */
      if (t >= c.end - 0.03) hl_goPiece(hl_nextPiece(i + 1, -1));
    } else {
      hl_goPiece(hl_nextPiece(i, t));       /* a cut line: over it */
    }
  }
  hl_syncAudio(v, v.currentTime);
  hl_paintHead();
}

function hl_capAt(t, track) {
  var on = null;
  (hl.p.lines || []).some(function (l) {
    if ((l.track || 'mic') === track && l.show && !l.cut && t >= l.start && t < l.end && hl_capText(l).trim()) { on = l; return true; }
    return false;
  });
  return on;
}

function hl_paintHead() {
  var v = hl_el('hl-video'), i = hl.cur, c = hl.p && hl.p.cuts[i];
  if (!c) return;
  var t = v.currentTime;
  var head = hl_el('hl-playhead');
  var x = hl_x(i, t);
  if (head) head.style.left = (x * hl.pxs).toFixed(1) + 'px';
  /* keep the playhead in view while playing */
  var sc = hl_el('hl-scroll');
  if (sc && !v.paused) {
    var px = x * hl.pxs;
    if (px < sc.scrollLeft + 40 || px > sc.scrollLeft + sc.clientWidth - 40) sc.scrollLeft = px - sc.clientWidth / 3;
  }
  /* where it is in the video that will be made */
  var P = hl_pieces(), out = 0, inside = false;
  for (var k = 0; k < P.length; k++) {
    if (P[k].cut === i && t >= P[k].a - 0.02 && t < P[k].b) { out += t - P[k].a; inside = true; break; }
    if (P[k].cut > i || (P[k].cut === i && P[k].a > t)) break;
    out += P[k].b - P[k].a;
  }
  hl_el('hl-clock').textContent = (inside ? hl_fmt(out) : 'Not in the video') + ' / ' + hl_fmt(hl.outLen);
  var play = hl_el('hl-play');
  play.textContent = v.paused ? 'Play' : 'Pause';
  play.setAttribute('aria-label', v.paused ? 'Play' : 'Pause');
  /* the face zoom, as the render makes it */
  var k2 = hl_pieceAt(i, t);
  var lay = k2 >= 0 ? P[k2].layout : (c.zoom ? 'cam' : 'game');
  var box = hl.p.cam_box;
  if (lay === 'cam' && box && !hl.boxMode) {
    var z = hl_zoomOf(box);
    var cx = box[0] + box[2] / 2, cy = box[1] + box[3] / 2;
    var X = Math.max(0, Math.min(1 - 1 / z, cx - 0.5 / z)) * 100;
    var Y = Math.max(0, Math.min(1 - 1 / z, cy - 0.5 / z)) * 100;
    v.style.transform = 'scale(' + z.toFixed(3) + ') translate(' + (-X).toFixed(2) + '%,' + (-Y).toFixed(2) + '%)';
  } else {
    v.style.transform = '';
  }
  v.classList.toggle('is-out', !inside);
  /* the captions: the player's at the bottom, the team's a line above */
  var burned = !!(hl.p.captions || {}).on, now = -1;
  [['mic', 'hl-cap'], ['game', 'hl-cap-team']].forEach(function (pair) {
    var cap = hl_el(pair[1]), on = inside ? hl_capAt(t, pair[0]) : null;
    if (on) {
      if (cap.textContent !== hl_capText(on)) cap.textContent = hl_capText(on);
      cap.classList.remove('hide');
      if (now < 0 || pair[0] === 'mic') now = on.id;
    } else cap.classList.add('hide');
    cap.classList.toggle('is-burned', burned);
  });
  if (now !== hl.lastLine) {
    var was = hl_el('hl-line-' + hl.lastLine);
    if (was) was.classList.remove('is-now');
    var el = hl_el('hl-line-' + now);
    if (el) {
      el.classList.add('is-now');
      if (!v.paused && !hl.editing) el.scrollIntoView({block: 'nearest'});
    }
    hl.lastLine = now;
  }
}

/* ---- the facecam box ------------------------------------------------------------ */

function hl_placeBox() {
  var el = hl_el('hl-box'), b = hl.p && hl.p.cam_box;
  if (!el) return;
  el.classList.toggle('hide', !hl.boxMode);
  if (!b) b = [0.02, 0.6, 0.22, 0.32];
  el.style.left = (b[0] * 100) + '%'; el.style.top = (b[1] * 100) + '%';
  el.style.width = (b[2] * 100) + '%'; el.style.height = (b[3] * 100) + '%';
}

function hl_boxDown(e) {
  if (!hl.boxMode) return;
  var stage = hl_el('hl-stage').getBoundingClientRect();
  var b = (hl.p.cam_box || [0.02, 0.6, 0.22, 0.32]).slice();
  hl.drag = {kind: 'box', grip: e.target.id === 'hl-box-grip', x: e.clientX, y: e.clientY,
             w: stage.width, h: stage.height, b: b, snap: hl_snap()};
  e.preventDefault();
}

/* ---- pressing the timeline -------------------------------------------------------- */

function hl_trackDown(e) {
  if (!hl.p) return;
  var tgt = e.target, snap = hl_snap(), top = hl.p.source_seconds || Infinity;
  /* a moment's edge */
  if (tgt.getAttribute('data-edge')) {
    var i = +tgt.getAttribute('data-i'), c = hl.p.cuts[i], ed = tgt.getAttribute('data-edge');
    hl.drag = {kind: 'edge', edge: ed, i: i, x: e.clientX, v: ed === 'a' ? c.start : c.end, snap: snap};
    e.preventDefault(); e.stopPropagation();
    return;
  }
  /* a caption: its edges retime it, its middle moves it */
  var cap = tgt.closest('[data-cap]');
  if (cap) {
    var l = hl_line(+cap.getAttribute('data-cap'));
    hl.drag = {kind: 'cap', id: l.id, mode: tgt.getAttribute('data-ce') || 'move', x: e.clientX,
               a: l.start, b: l.end, snap: snap};
    e.preventDefault();
    return;
  }
  /* a face zoom drawn by hand: the same */
  var zm = tgt.closest('[data-zm]');
  if (zm) {
    var z = hl_zoom(+zm.getAttribute('data-zm'));
    hl.drag = {kind: 'zoom', id: z.id, mode: tgt.getAttribute('data-ce') || 'move', x: e.clientX,
               a: z.start, b: z.end, snap: snap};
    e.preventDefault();
    return;
  }
  /* a volume line: a point to drag, or a new one */
  var svg = tgt.closest('svg[data-vol]');
  if (svg) {
    var name = svg.getAttribute('data-vol'), lane = hl_lane(name), r = svg.getBoundingClientRect();
    var key;
    if (tgt.getAttribute('data-vk') !== null) key = lane.keys[+tgt.getAttribute('data-vk')];
    else {
      var hit = hl_hit(e.clientX);
      key = [hl_r3(hit.t), Math.max(-60, hl_volDb(e.clientY - r.top, r.height))];
      hl.undo.push(snap); hl.redo = []; snap = null;
      lane.keys.push(key);
      lane.keys.sort(function (x, y) { return x[0] - y[0]; });
      hl_renderTrack();
    }
    hl.drag = {kind: 'key', lane: name, key: key, top: r.top, h: r.height, x: e.clientX, y: e.clientY,
               snap: snap, moved: !snap};
    e.preventDefault();
    return;
  }
  if (tgt.closest('[data-hl]')) return;
  /* an empty lane: the face zoom lane draws a zoom; any other seeks */
  var ground = tgt.getAttribute('data-lane'), at = hl_hit(e.clientX);
  if (ground === 'zoom') {
    if (!hl.p.cam_box) { toast('Mark where your facecam is first.', 'warn'); hl.boxMode = true; hl_render(true); return; }
    var c2 = hl.p.cuts[at.i];
    hl.drag = {kind: 'newzoom', i: at.i, t0: at.t, lo: c2.start, hi: c2.end, x: e.clientX, snap: snap, id: null};
    e.preventDefault();
    return;
  }
  hl_seek(at.i, at.t, !hl_el('hl-video').paused);
}

function hl_move(e) {
  var d = hl.drag;
  if (!d) return;
  var p = hl.p, top = p.source_seconds || Infinity, dt = (e.clientX - d.x) / hl.pxs;
  if (Math.abs(e.clientX - d.x) > 3 || (d.kind === 'key' && Math.abs(e.clientY - d.y) > 2)) d.moved = true;
  if (d.kind === 'box') {
    var dx = (e.clientX - d.x) / d.w, dy = (e.clientY - d.y) / d.h, b = d.b.slice();
    if (d.grip) {
      b[2] = Math.max(0.04, Math.min(1 - b[0], b[2] + dx)); b[3] = Math.max(0.04, Math.min(1 - b[1], b[3] + dy));
    } else {
      b[0] = Math.max(0, Math.min(1 - b[2], b[0] + dx)); b[1] = Math.max(0, Math.min(1 - b[3], b[1] + dy));
    }
    p.cam_box = b.map(function (x) { return Math.round(x * 100000) / 100000; });
    d.moved = true;
    hl_placeBox();
    return;
  }
  if (!d.moved) return;
  if (d.kind === 'edge') {
    var c = p.cuts[d.i];
    if (d.edge === 'a') c.start = hl_r3(Math.max(0, Math.min(c.end - 1, d.v + dt)));
    else c.end = hl_r3(Math.min(top, Math.max(c.start + 1, d.v + dt)));
    hl_layout();
    hl_seek(d.i, d.edge === 'a' ? c.start : c.end - 0.1);
  } else if (d.kind === 'cap' || d.kind === 'zoom') {
    var o = d.kind === 'cap' ? hl_line(d.id) : hl_zoom(d.id), least = d.kind === 'cap' ? HL_CAP_LEAST : HL_SHORTEST;
    if (d.mode === 'a') o.start = hl_r3(Math.max(0, Math.min(d.b - least, d.a + dt)));
    else if (d.mode === 'b') o.end = hl_r3(Math.min(top, Math.max(d.a + least, d.b + dt)));
    else {
      var sh = Math.max(-d.a, Math.min(top - d.b, dt));
      o.start = hl_r3(d.a + sh); o.end = hl_r3(d.b + sh);
    }
    hl.pieces = null;
  } else if (d.kind === 'newzoom') {
    var t = Math.max(d.lo, Math.min(d.hi, d.t0 + dt)), a = Math.min(d.t0, t), b2 = Math.max(d.t0, t);
    if (b2 - a < HL_SHORTEST) return;
    if (d.id === null) {
      d.id = hl_nextId(p.zooms || []);
      (p.zooms = p.zooms || []).push({id: d.id, start: hl_r3(a), end: hl_r3(b2)});
      hl.selKind = 'zoom'; hl.selId = d.id;
    } else { var zz = hl_zoom(d.id); zz.start = hl_r3(a); zz.end = hl_r3(b2); }
    hl.pieces = null;
  } else if (d.kind === 'key') {
    var hit = hl_hit(e.clientX);
    d.key[0] = hl_r3(hit.t);
    d.key[1] = Math.max(-60, hl_volDb(e.clientY - d.top, d.h));
    hl_lane(d.lane).keys.sort(function (x, y) { return x[0] - y[0]; });
  }
  if (!d.frame) d.frame = requestAnimationFrame(function () { d.frame = 0; hl_renderTrack(); });
}

function hl_up() {
  var d = hl.drag;
  if (!d) return;
  hl.drag = null;
  if (d.kind === 'box') {
    if (d.moved) { hl.undo.push(d.snap); hl.redo = []; hl_save(); hl_render(true); }
    return;
  }
  if (!d.moved) {
    /* a press without a drag: choose it, and hear it */
    if (d.kind === 'cap') { hl.selKind = 'cap'; hl.selId = d.id; hl_render(true); hl_markSaid(); hl_seekLine(hl_line(d.id), -1); }
    else if (d.kind === 'zoom') { hl.selKind = 'zoom'; hl.selId = d.id; hl_render(true); }
    return;
  }
  if (d.snap) { hl.undo.push(d.snap); hl.redo = []; }
  if (d.kind === 'cap') { hl.selKind = 'cap'; hl.selId = d.id; }
  hl_layout(); hl_render(); hl_save();
}

function hl_markSaid() {
  var on = document.querySelectorAll('#hl-said .hl-line.is-sel');
  for (var i = 0; i < on.length; i++) on[i].classList.remove('is-sel');
  if (hl.selKind !== 'cap') return;
  var el = hl_el('hl-line-' + hl.selId);
  if (el) { el.classList.add('is-sel'); el.scrollIntoView({block: 'nearest'}); }
}

/* ---- captions: add, split, join, delete ---------------------------------------- */

function hl_addCaption() {
  var v = hl_el('hl-video'), c = hl.p.cuts[hl.cur];
  if (!c) return;
  var t = Math.max(c.start, Math.min(c.end - HL_CAP_LEAST, v.currentTime));
  var id = hl_nextId(hl.p.lines || []);
  hl_change(function () {
    (hl.p.lines = hl.p.lines || []).push({id: id, start: hl_r3(t), end: hl_r3(Math.min(t + 2, (hl.p.source_seconds || Infinity))),
      text: '', english: '', show: true, cut: false, face: false, track: 'mic'});
    hl.p.lines.sort(function (a, b) { return a.start - b.start || a.id - b.id; });
    hl.selKind = 'cap'; hl.selId = id;
  });
  var inp = hl_el('hl-cap-input');
  if (inp) inp.focus();
}

function hl_splitWords(s, frac) {
  var w = (s || '').split(/\s+/).filter(Boolean), k = Math.max(0, Math.min(w.length, Math.round(w.length * frac)));
  return [w.slice(0, k).join(' '), w.slice(k).join(' ')];
}

function hl_capSplit() {
  var l = hl_line(hl.selId), t = hl_el('hl-video').currentTime;
  if (!l) return;
  if (!(t > l.start + HL_CAP_LEAST && t < l.end - HL_CAP_LEAST)) {
    toast('Put the playhead inside the caption, where it should split.', 'warn'); return;
  }
  var frac = (t - l.start) / (l.end - l.start), id = hl_nextId(hl.p.lines);
  hl_change(function () {
    var a = hl_splitWords(l.text, frac), b = hl_splitWords(l.english, frac);
    hl.p.lines.push({id: id, start: hl_r3(t), end: l.end, text: a[1], english: b[1], show: l.show,
                     cut: l.cut, face: l.face, track: l.track || 'mic'});
    l.end = hl_r3(t); l.text = a[0]; l.english = b[0];
    hl.p.lines.sort(function (x, y) { return x.start - y.start || x.id - y.id; });
  });
}

function hl_capMerge() {
  var l = hl_line(hl.selId);
  if (!l) return;
  var next = hl.p.lines.filter(function (x) { return (x.track || 'mic') === (l.track || 'mic') && x.start >= l.start && x.id !== l.id; })
    .sort(function (a, b) { return a.start - b.start; })[0];
  if (!next) { toast('There is no caption after this one to join.', 'warn'); return; }
  hl_change(function () {
    l.end = Math.max(l.end, next.end);
    l.text = (l.text + ' ' + next.text).trim();
    l.english = ((l.english || '') + ' ' + (next.english || '')).trim();
    hl.p.lines = hl.p.lines.filter(function (x) { return x.id !== next.id; });
  });
}

function hl_delete() {
  if (hl.selKind === 'cap' && hl_line(hl.selId)) {
    var id = hl.selId;
    hl_change(function () { hl.p.lines = hl.p.lines.filter(function (x) { return x.id !== id; }); hl.selKind = 'mom'; });
  } else if (hl.selKind === 'zoom' && hl_zoom(hl.selId)) {
    var zid = hl.selId;
    hl_change(function () { hl.p.zooms = hl.p.zooms.filter(function (x) { return x.id !== zid; }); hl.selKind = 'mom'; });
  }
}

/* ---- clicks ------------------------------------------------------------------------ */

function hl_click(e) {
  var b = e.target.closest('[data-hl]');
  if (!b || !hl.p) return;
  var act = b.getAttribute('data-hl'), p = hl.p, v = hl_el('hl-video');
  var i = +b.getAttribute('data-i'), l = hl_line(+b.getAttribute('data-l'));
  var top = p.source_seconds || Infinity;
  if (act === 'close') hl_close();
  else if (act === 'undo') hl_undoRedo(true);
  else if (act === 'redo') hl_undoRedo(false);
  else if (act === 'play') hl_togglePlay();
  else if (act === 'prev' || act === 'next') {
    var k = Math.max(0, Math.min(hl.groups.length - 1, hl.sel + (act === 'next' ? 1 : -1)));
    hl.sel = k; hl.selKind = 'mom'; hl_render(); hl_seek(hl.groups[k].cuts[0], p.cuts[hl.groups[k].cuts[0]].start);
  } else if (act === 'mom') {
    var kk = +b.getAttribute('data-k');
    hl.sel = kk; hl.selKind = 'mom';
    hl_render();
    var g = hl.groups[kk];
    if (b.classList.contains('hl-blk')) {
      var r = b.getBoundingClientRect(), frac = (e.clientX - r.left) / Math.max(1, r.width);
      var into = frac * g.cuts.reduce(function (s, j) { return s + hl_len(p.cuts[j]); }, 0);
      for (var n = 0; n < g.cuts.length; n++) {
        var cl = hl_len(p.cuts[g.cuts[n]]);
        if (into <= cl || n === g.cuts.length - 1) { hl_seek(g.cuts[n], p.cuts[g.cuts[n]].start + into, !v.paused); break; }
        into -= cl;
      }
    } else hl_seek(g.cuts[0], p.cuts[g.cuts[0]].start);
  } else if (act === 'keepmom') {
    var gg = hl.groups[hl.sel], on = gg.cuts.some(function (j) { return p.cuts[j].keep; });
    hl_change(function () { gg.cuts.forEach(function (j) { p.cuts[j].keep = !on; }); });
  } else if (act === 'keepcut' || act === 'endcut') {
    hl_change(function () { p.cuts[i].keep = !p.cuts[i].keep; });
  } else if (act === 'zoomcut') {
    if (!p.cam_box) { toast('Mark where your facecam is first.', 'warn'); hl.boxMode = true; hl_render(); return; }
    hl_change(function () { p.cuts[i].zoom = !p.cuts[i].zoom; });
  } else if (act === 'zoomline' || act === 'face') {
    if (!p.cam_box) { toast('Mark where your facecam is first.', 'warn'); hl.boxMode = true; hl_render(); return; }
    hl_change(function () { l.face = !l.face; });
  } else if (act === 'show') {
    hl_change(function () { l.show = !l.show; });
  } else if (act === 'cut') {
    hl_change(function () { l.cut = !l.cut; });
  } else if (act === 'nudge') {
    var edge = b.getAttribute('data-edge'), d = +b.getAttribute('data-d'), c = p.cuts[+b.getAttribute('data-id')];
    hl_change(function () {
      if (edge === 'a') c.start = hl_r3(Math.max(0, Math.min(c.end - 1, c.start + d)));
      else c.end = hl_r3(Math.min(top, Math.max(c.start + 1, c.end + d)));
    });
    hl_seek(p.cuts.indexOf(c), edge === 'a' ? c.start : c.end - 2);
  } else if (act === 'capnudge' || act === 'zoomnudge') {
    var o = act === 'capnudge' ? hl_line(+b.getAttribute('data-id')) : hl_zoom(+b.getAttribute('data-id'));
    var e2 = b.getAttribute('data-edge'), d2 = +b.getAttribute('data-d');
    var least = act === 'capnudge' ? HL_CAP_LEAST : HL_SHORTEST;
    hl_change(function () {
      if (e2 === 'a') o.start = hl_r3(Math.max(0, Math.min(o.end - least, o.start + d2)));
      else o.end = hl_r3(Math.min(top, Math.max(o.start + least, o.end + d2)));
    }, act === 'zoomnudge');
  } else if (act === 'capsplit') hl_capSplit();
  else if (act === 'capmerge') hl_capMerge();
  else if (act === 'capdel' || act === 'zoomdel') hl_delete();
  else if (act === 'addcap') hl_addCaption();
  else if (act === 'seekcut') {
    hl_seek(i, p.cuts[i].start);
  } else if (act === 'seekline') {
    hl.selKind = 'cap'; hl.selId = l.id; hl_render(true); hl_markSaid();
    hl_seekLine(l, -1);
  } else if (act === 'said-who') {
    hl.who = b.getAttribute('data-v');
    var segs = document.querySelectorAll('#hl-card .hl-seg-btn');
    for (var s = 0; s < segs.length; s++) segs[s].classList.toggle('is-on', segs[s] === b);
    hl_renderSaid();
  } else if (act === 'team-stt') hl_teamStt();
  else if (act === 'volclear') {
    var vn = b.getAttribute('data-v');
    hl_change(function () { hl_lane(vn).keys = []; }, true);
  } else if (act === 'caps') {
    hl_change(function () { p.captions = {on: !(p.captions || {}).on, lang: (p.captions || {}).lang || 'english'}; }, true);
  } else if (act === 'box') {
    hl.boxMode = !hl.boxMode;
    if (hl.boxMode) v.pause();
    if (!hl.boxMode && !p.cam_box) hl_change(function () { p.cam_box = [0.02, 0.6, 0.22, 0.32]; });
    hl_render(true);
  } else if (act === 'make') hl_make();
  else if (act === 'stop') API.post('/api/clips/highlight/cancel', {});
  else if (act === 'reveal') clip_reveal(hl.made);
}

function hl_seekLine(l, prefer) {
  if (!l) return;
  var p = hl.p, best = -1;
  p.cuts.forEach(function (c, i) {
    if (best >= 0 && best === prefer) return;
    if (l.end > c.start && l.start < c.end && (best < 0 || (c.keep && !p.cuts[best].keep) || i === prefer)) best = i;
  });
  if (best < 0) {
    /* Not inside any cut: the nearest one, at its edge, so the line can be judged
       before the moment is trimmed out to it. */
    var dist = Infinity;
    p.cuts.forEach(function (c, i) {
      var d2 = Math.min(Math.abs(c.start - l.start), Math.abs(c.end - l.end));
      if (c.kind !== 'cold' && d2 < dist) { dist = d2; best = i; }
    });
  }
  if (best >= 0) hl_seek(best, Math.max(p.cuts[best].start, l.start));
}

function hl_togglePlay() {
  var v = hl_el('hl-video');
  if (!v.getAttribute('src')) return;
  if (hl.aud && hl.aud.ctx.state === 'suspended') hl.aud.ctx.resume();
  if (v.paused) {
    if (hl.cur < 0) { var P = hl_pieces(); if (P[0]) hl_goPiece(0); }
    var pr = v.play();
    if (pr && pr.catch) pr.catch(function () {});
  } else v.pause();
}

/* ---- the slow jobs: tracks copied out, the team's voice written down -------------- */

async function hl_teamStt() {
  await hl_save(true);
  var r = await API.post('/api/clips/highlight/transcribe', {video: hl.video, track: 'game'});
  if (!r || r.error) { toast((r && r.error) || 'The team\'s voice could not be written down.', 'error'); return; }
  hl_paintWork({transcribe: {state: 'running'}});
  hl_pollWork();
}

function hl_pollWork() {
  clearTimeout(hl.workPoll);
  hl.workPoll = setTimeout(async function () {
    if (!hl.p) return;
    var r;
    try { r = await API.get('/api/clips/highlight/work?video=' + encodeURIComponent(hl.video)); } catch (e) { r = null; }
    if (!r || r.error) { hl_pollWork(); return; }
    var was = hl.workState || {};
    hl_paintWork(r.work || {});
    if (r.audio && r.audio.mic && r.audio.game && !hl.aud) { hl.audio = r.audio; hl_attachAudio(); }
    var tr = (r.work || {}).transcribe;
    if (tr && tr.state === 'done' && was.transcribe === 'running') await hl_reloadLines(tr.result);
    var busy = Object.keys(r.work || {}).some(function (k) { return r.work[k].state === 'running'; });
    if (busy || (hl.tracks >= 3 && !hl.aud && !((r.work || {}).tracks || {}).error)) hl_pollWork();
  }, 1500);
}

function hl_paintWork(w) {
  hl.workState = {};
  Object.keys(w).forEach(function (k) { hl.workState[k] = w[k].state; });
  var am = hl_el('hl-audio-msg');
  var t = w.tracks || {};
  if (t.state === 'running') am.textContent = 'Preparing the mic and game tracks...';
  else if (t.state === 'failed') am.textContent = 'The mic and game play together here: ' + (t.error || '');
  else if (hl.aud) am.textContent = '';
  var msg = hl_el('hl-team-msg'), btn = hl_el('hl-team-stt'), s = w.transcribe || {};
  btn.disabled = s.state === 'running';
  msg.classList.toggle('hide', !s.state || s.state === 'idle');
  msg.textContent = s.state === 'running' ? 'Writing down what your team said... this takes a few minutes.'
    : s.state === 'failed' ? (s.error || 'It could not be written down.')
    : s.state === 'done' ? ((s.result || 0) + ' lines from your team.') : '';
}

async function hl_reloadLines(n) {
  var r = await API.get('/api/clips/highlight?video=' + encodeURIComponent(hl.video));
  if (!r || r.error || !hl.p) return;
  hl.undo.push(hl_snap()); hl.redo = [];
  hl.p.lines = r.project.lines || [];
  hl_layout(); hl_render();
  toast((n || 0) + ' lines from your team were added as captions.', 'ok');
}

/* ---- Make video ---------------------------------------------------------------------- */

async function hl_make() {
  clearTimeout(hl.saveT);
  var r = await API.post('/api/clips/highlight/render', {video: hl.video, project: hl_edits()});
  if (!r || r.error) { toast((r && r.error) || 'The video could not be started.', 'error'); return; }
  hl_paintRender(r.waiting ? {state: 'waiting', why: r.waiting} : {state: 'running', percent: 0});
  hl_pollRender();
}

function hl_pollRender() {
  clearTimeout(hl.poll);
  hl.poll = setTimeout(async function () {
    var r;
    try { r = await API.get('/api/clips/highlight/status'); } catch (e) { r = null; }
    if (!r) { hl_pollRender(); return; }
    hl_paintRender(r);
    if (r.state === 'running' || r.state === 'waiting') hl_pollRender();
    else if (r.state === 'done') { hl.made = r.out; toast('Your edited video is made.', 'ok'); hl_paintRender(r); }
    else if (r.state === 'failed') toast(r.error || 'The video could not be made.', 'error');
  }, 1000);
}

function hl_paintRender(r) {
  var wait = r.state === 'waiting';
  var run = r.state === 'running' || wait;
  var msg = hl_el('hl-make-msg');
  /* Live or recording: the render is held so the stream keeps its encoder,
     and starts by itself afterwards (clips/highlight_edit.Renderer). */
  if (wait) msg.textContent = (r.why || 'Waiting.') + ' The video starts by itself after that.';
  else if (run) msg.textContent = r.total ? ('Making it: part ' + Math.min(r.done + 1, r.total) + ' of ' + r.total + ', ' +
                                        r.percent + '%') : 'Making it...';
  else if (r.state === 'failed') msg.textContent = r.error || 'It could not be made.';
  else if (hl.made) msg.textContent = 'Made: ' + hl.made.split(/[\\/]/).pop();
  else msg.textContent = '';
  hl_el('hl-make').disabled = run;
  hl_el('hl-make').textContent = hl.made && !run ? 'Make it again' : 'Make video';
  hl_el('hl-stop').classList.toggle('hide', !run);
  hl_el('hl-show').classList.toggle('hide', run || !hl.made);
}

/* ---- wiring --------------------------------------------------------------------------- */

(function hl_wire() {
  var card = hl_el('hl-card');
  if (!card) return;
  card.addEventListener('click', hl_click);
  card.addEventListener('change', function (e) {
    var w = e.target.getAttribute('data-hl-change'), p = hl.p;
    if (!w || !p) return;
    if (w === 'zoom') hl_change(function () { p.cam_zoom = e.target.value ? +e.target.value : null; }, true);
    if (w === 'lang') hl_change(function () {
      p.captions = {on: !!(p.captions || {}).on, lang: e.target.value};
    });
    if (w === 'master') hl_change(function () { p.volume.master = +e.target.value; }, true);
    if (w === 'captrack') {
      var l = hl_line(hl.selId);
      if (l) hl_change(function () { l.track = e.target.value; });
    }
  });
  hl_el('hl-master').addEventListener('input', function (e) {
    var m = +e.target.value;
    hl_el('hl-master-v').textContent = (m > 0 ? '+' : '') + m + ' dB';
    if (hl.p) hl.p.volume.master = m;
  });
  hl_el('hl-scale').addEventListener('input', function (e) {
    hl.pxs = +e.target.value; if (hl.p) hl_renderTrack();
  });
  hl_el('hl-scroll').addEventListener('pointerdown', hl_trackDown);
  hl_el('hl-scroll').addEventListener('dblclick', function (e) {
    var dot = e.target.closest('[data-vk]'), svg = e.target.closest('svg[data-vol]');
    if (!dot || !svg || !hl.p) return;
    var name = svg.getAttribute('data-vol'), n = +dot.getAttribute('data-vk');
    hl_change(function () { hl_lane(name).keys.splice(n, 1); }, true);
  });
  hl_el('hl-box').addEventListener('pointerdown', hl_boxDown);
  document.addEventListener('pointermove', hl_move);
  document.addEventListener('pointerup', hl_up);
  /* A line's words: changed in place, saved after typing stops. One undo step per
     line edited, not per key. The caption box in the inspector is the same. */
  function wordsIn(t) {
    if (!t || !t.getAttribute) return;
    var l = hl.p && hl_line(+t.getAttribute('data-l'));
    if (!l) return;
    if (hl.editing && !hl.editing.pushed) { hl.undo.push(hl.editing.snap); hl.redo = []; hl.editing.pushed = true; }
    l[t.getAttribute('data-field')] = (t.value !== undefined ? t.value : t.textContent).replace(/\s+/g, ' ');
    hl.pieces = null;
    hl_save();
  }
  [hl_el('hl-said'), hl_el('hl-insp')].forEach(function (host) {
    host.addEventListener('focusin', function (e) {
      var t = e.target;
      if (t.classList && (t.classList.contains('hl-line-text') || t.id === 'hl-cap-input')) {
        hl.editing = {id: +t.getAttribute('data-l'), snap: hl_snap()};
      }
    });
    host.addEventListener('input', function (e) {
      if (e.target.classList.contains('hl-line-text') || e.target.id === 'hl-cap-input') wordsIn(e.target);
    });
    host.addEventListener('focusout', function () {
      if (hl.editing && hl.editing.pushed) { hl_renderTrack(); hl_el('hl-undo').disabled = false; }
      if (hl.editing && hl.editing.pushed && host.id === 'hl-insp') hl_renderSaid();
      hl.editing = null;
    });
    host.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && (e.target.classList.contains('hl-line-text') || e.target.id === 'hl-cap-input')) {
        e.preventDefault(); e.target.blur();
      }
    });
  });
  document.addEventListener('keydown', function (e) {
    if (!hl.p || hl_el('hl-card').classList.contains('hide')) return;
    var view = hl_el('view-clips');
    if (!view || !view.classList.contains('is-active')) return;
    var t = e.target, typing = t && (t.isContentEditable || /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName));
    if (typing) return;
    if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); hl_undoRedo(!e.shiftKey); }
    else if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || e.key === 'Y')) { e.preventDefault(); hl_undoRedo(false); }
    else if (e.key === ' ' && !(t && t.tagName === 'BUTTON')) { e.preventDefault(); hl_togglePlay(); }
    else if ((e.key === 'Delete' || e.key === 'Backspace') && (hl.selKind === 'cap' || hl.selKind === 'zoom')) {
      e.preventDefault(); hl_delete();
    }
  });
  var v = hl_el('hl-video');
  v.addEventListener('click', function () { if (!hl.boxMode) hl_togglePlay(); });
  v.addEventListener('error', function () {
    var msg = hl_el('hl-stage-msg');
    msg.textContent = 'This recording cannot be played here, so the preview is off. Editing and ' +
                      'Make video still work.';
    msg.classList.remove('hide');
  });
})();

window.PAGE_HL = {open: hl_open, close: hl_close};
"""

HIGHLIGHT_CSS: str = r"""
/* ==========================================================================
   THE HIGHLIGHT EDITOR (ui/highlight.py): preview, lanes, and what was said
   ========================================================================== */
#view-clips.hl-on>:not(#hl-card){display:none !important}
.hl-card{
  --hl-gold:var(--warn);
  --hl-team:#5ec8bd;
  display:flex;flex-direction:column;gap:var(--space-6);
  padding:var(--pad-card);
}
.hl-head{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-6)}
.hl-head-text{min-width:0}
.hl-head-acts{display:flex;gap:var(--space-3);flex:0 0 auto}
.hl-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(280px,360px);gap:var(--space-7);align-items:start}
.hl-main{display:flex;flex-direction:column;gap:var(--space-5);min-width:0}

/* the stage: a 16:9 window the frame zooms inside */
.hl-stage{position:relative;aspect-ratio:16/9;overflow:hidden;border-radius:var(--radius-md);
  background:#000;user-select:none}
.hl-stage video{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;
  transform-origin:0 0;transition:transform var(--dur-slow) var(--ease-standard);cursor:pointer}
.hl-stage video.is-out{opacity:.45}
.hl-cap{position:absolute;left:50%;bottom:16.5%;transform:translateX(-50%);max-width:72%;
  padding:.2em .6em;border-radius:var(--radius-sm);background:var(--on-media-scrim);
  color:var(--on-media);font-weight:600;font-size:clamp(12px,2.2vw,22px);line-height:1.25;text-align:center;
  pointer-events:none;outline:var(--border-hair) dashed rgba(255,255,255,.35);outline-offset:3px}
/* A team-mate on voice comms: a line above the player's, in the team colour --
   stream_highlight.caption_image(who="game") draws it the same way. */
.hl-cap.is-team{bottom:27%;color:#96e2da}
/* Burned in: drawn exactly as the video will carry it. Off: a dashed outline says
   it is only a guide here. */
.hl-cap.is-burned{outline:0}
.hl-box{position:absolute;border:var(--border-thick) solid var(--hl-gold);border-radius:var(--radius-xs);
  box-shadow:0 0 0 9999px rgba(0,0,0,.45);cursor:move;touch-action:none}
.hl-box-grip{position:absolute;right:-7px;bottom:-7px;width:14px;height:14px;border-radius:var(--radius-xs);
  background:var(--hl-gold);cursor:nwse-resize}
.hl-stage-msg{position:absolute;inset:auto var(--space-6) var(--space-6);margin:0;padding:var(--space-4) var(--space-5);
  border-radius:var(--radius-sm);background:var(--on-media-scrim);color:var(--on-media);font-size:var(--text-sm)}

.hl-transport{display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap}
.hl-play{min-width:72px}
.hl-clock{font-variant-numeric:tabular-nums;color:var(--text-secondary);font-size:var(--text-sm);margin-left:var(--space-4)}
.hl-spacer{flex:1 1 auto}
.hl-audio-msg{font-size:var(--text-xs)}
.hl-scale-label{font-size:var(--text-xs);color:var(--text-tertiary)}
#hl-scale{width:120px;accent-color:var(--accent)}

/* the lanes */
.hl-lanes{display:grid;grid-template-columns:112px minmax(0,1fr);border:var(--border-hair) solid var(--border-subtle);
  border-radius:var(--radius-md);background:var(--surface-sunken);overflow:hidden}
.hl-lane-names{display:flex;flex-direction:column;padding:4px 0 4px var(--space-4);gap:6px;
  border-right:var(--border-hair) solid var(--border-subtle)}
.hl-lane-name{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-2);
  padding-right:var(--space-3);font-size:var(--text-xs);color:var(--text-tertiary);white-space:nowrap}
.hl-lane-clear{background:none;border:0;padding:0 2px;font:inherit;font-size:11px;color:var(--text-tertiary);
  cursor:pointer;text-decoration:underline}
.hl-lane-clear:hover{color:var(--text-primary)}
.hl-scroll{overflow-x:auto;overflow-y:hidden;cursor:pointer}
.hl-track{position:relative}
.hl-ground{position:absolute;left:0;right:0}
.hl-ground[data-lane="zoom"]{cursor:crosshair}
.hl-blk{position:absolute;height:22px;border-radius:var(--radius-xs);
  box-sizing:border-box;min-width:2px;overflow:hidden}
.hl-mom{height:24px;background:var(--accent-muted);border:var(--border-hair) solid var(--accent);color:var(--text-primary);
  display:flex;align-items:center;cursor:pointer}
.hl-mom.is-cold{border-style:dashed}
.hl-mom.is-off{background:repeating-linear-gradient(135deg,var(--surface) 0 6px,var(--surface-sunken) 6px 12px);
  border-color:var(--border-strong);color:var(--text-tertiary)}
.hl-mom.is-sel{box-shadow:0 0 0 var(--border-thick) var(--text-primary) inset}
.hl-blk-text{flex:1 1 auto;min-width:0;padding:0 6px;font-size:11px;line-height:22px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;pointer-events:none}
.hl-mom.is-off .hl-blk-text{text-decoration:line-through}
.hl-edge{flex:0 0 7px;align-self:stretch;cursor:ew-resize;background:var(--accent);opacity:0;touch-action:none}
.hl-mom:hover .hl-edge,.hl-mom.is-sel .hl-edge{opacity:.75}
.hl-zm{background:var(--warn-muted);border:var(--border-hair) solid var(--hl-gold);cursor:pointer}
.hl-zm.is-line{background:var(--hl-gold);opacity:.8}
.hl-zm.is-off{background:transparent;border-style:dashed;opacity:.8}
.hl-zm.is-drawn{background:var(--hl-gold);opacity:.9;display:flex;cursor:grab}
/* A caption block: its words in it, an edge to retime either end, its middle to move it. */
.hl-cp{display:flex;align-items:stretch;background:var(--surface-active);border:var(--border-hair) solid var(--border-strong);
  color:var(--text-primary);cursor:grab}
.hl-cp.is-team{border-color:var(--hl-team);background:color-mix(in srgb,var(--hl-team) 18%,var(--surface-active))}
.hl-cp.is-off{background:transparent;border-style:dashed;color:var(--text-tertiary)}
.hl-cp.is-cut{background:var(--danger-muted);border-color:var(--danger);color:var(--text-tertiary)}
.hl-cp.is-sel,.hl-zm.is-sel{box-shadow:0 0 0 var(--border-thick) var(--text-primary) inset}
.hl-cedge{flex:0 0 6px;cursor:ew-resize;touch-action:none}
.hl-cedge-b{margin-left:auto}
.hl-cp:hover .hl-cedge,.hl-zm.is-drawn:hover .hl-cedge{background:rgba(127,127,127,.45)}
.hl-end{background:var(--text-tertiary);cursor:pointer}
.hl-end.is-off{background:transparent;border:var(--border-hair) dashed var(--text-tertiary)}
.hl-blk.is-gone{opacity:.35}
/* the volume lines: a point per keyframe, the line straight between them */
.hl-vol{position:absolute;left:0;overflow:visible;cursor:copy}
.hl-vol-bg{fill:transparent}
.hl-v0{stroke:var(--border-strong);stroke-dasharray:3 4;stroke-width:1}
.hl-vl{fill:none;stroke:var(--accent);stroke-width:2;pointer-events:none}
.hl-vol[data-vol="game"] .hl-vl{stroke:var(--hl-team)}
.hl-vl.is-gone{opacity:.35}
.hl-vk{fill:var(--surface);stroke:var(--text-primary);stroke-width:2;cursor:grab}
.hl-vk:hover{fill:var(--text-primary)}
.hl-head-line{position:absolute;top:0;bottom:0;width:2px;margin-left:-1px;background:var(--text-primary);pointer-events:none}

/* the selected moment, caption or zoom */
.hl-insp{display:flex;flex-direction:column;gap:var(--space-4);padding:var(--space-5);
  border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-md)}
.hl-insp-head{display:flex;align-items:center;justify-content:space-between;gap:var(--space-5)}
.hl-insp-acts{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-3)}
.hl-cap-input{width:100%}
.hl-trim{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-3) var(--space-5)}
.hl-trim-label{font-size:var(--text-sm);color:var(--text-secondary);font-variant-numeric:tabular-nums}
.hl-nudge{display:inline-flex;gap:2px}
.hl-parts{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px}
.hl-part{display:flex;align-items:center;gap:var(--space-3);font-size:var(--text-sm)}
.hl-part.is-off .hl-part-seek{text-decoration:line-through;color:var(--text-tertiary)}
.hl-part-seek{flex:1 1 auto;text-align:left;background:none;border:0;padding:var(--space-2) 0;
  color:var(--text-secondary);font:inherit;cursor:pointer}
.hl-part-seek:hover{color:var(--text-primary)}
.hl-part-t{font-variant-numeric:tabular-nums;color:var(--text-tertiary)}

/* what was said */
.hl-said{display:flex;flex-direction:column;min-height:0;max-height:calc(var(--vh) * 100 - 220px);
  border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-md);overflow:hidden}
.hl-said-head{padding:var(--space-5) var(--space-5) var(--space-3);display:flex;flex-direction:column;gap:var(--space-3)}
.hl-said-title{margin:0;font-size:var(--text-md);font-weight:600}
.hl-said-help{margin:0;font-size:var(--text-xs)}
.hl-said-tools{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:var(--space-3)}
.hl-seg{display:inline-flex;border:var(--border-hair) solid var(--border-subtle);border-radius:var(--radius-sm);overflow:hidden}
.hl-seg-btn{background:none;border:0;padding:var(--space-2) var(--space-4);font:inherit;font-size:var(--text-xs);
  color:var(--text-secondary);cursor:pointer}
.hl-seg-btn.is-on{background:var(--surface-active);color:var(--text-primary)}
.hl-team-msg{margin:0;font-size:var(--text-xs)}
.hl-said-list{overflow-y:auto;padding:0 var(--space-3) var(--space-5)}
.hl-said-empty{padding:var(--space-5);font-size:var(--text-sm)}
.hl-said-mom{padding:var(--space-3) 0;border-top:var(--border-hair) solid var(--border-subtle)}
.hl-said-mom.is-off{opacity:.6}
.hl-said-name{display:block;width:100%;text-align:left;background:none;border:0;cursor:pointer;
  padding:var(--space-2) var(--space-3);font:600 var(--text-sm)/1.3 var(--font-text);color:var(--text-primary)}
.hl-said-mom.is-sel .hl-said-name{color:var(--accent-text)}
.hl-said-none{margin:0;padding:0 var(--space-3);font-size:var(--text-xs)}
.hl-chip{display:inline-block;margin-left:var(--space-3);padding:0 var(--space-3);border-radius:var(--radius-xs);
  background:var(--surface-active);font-weight:500;font-size:11px;color:var(--text-secondary)}
.hl-chip.is-team{margin:0;align-self:flex-start;color:var(--hl-team)}
.hl-line{display:grid;grid-template-columns:38px minmax(0,1fr);gap:var(--space-2) var(--space-3);
  padding:var(--space-3);border-radius:var(--radius-sm)}
.hl-line.is-now{background:var(--surface-active)}
.hl-line.is-sel{box-shadow:inset 0 0 0 var(--border-hair) var(--border-strong)}
.hl-line.is-face{box-shadow:inset 3px 0 0 var(--hl-gold)}
.hl-line.is-out .hl-line-text{color:var(--text-tertiary)}
.hl-line.is-cut .hl-line-text{text-decoration:line-through;color:var(--text-tertiary)}
.hl-line-t{background:none;border:0;padding:0;font:inherit;font-size:var(--text-xs);color:var(--text-tertiary);
  font-variant-numeric:tabular-nums;cursor:pointer;text-align:left;align-self:start;line-height:20px}
.hl-line-t:hover{color:var(--text-primary)}
.hl-line-body{display:flex;flex-direction:column;gap:2px;min-width:0}
.hl-line-text{font-size:var(--text-sm);line-height:20px;color:var(--text-primary);border-radius:var(--radius-xs);
  outline:0;padding:0 2px;margin:0 -2px;overflow-wrap:anywhere}
.hl-line-text:focus{background:var(--surface);box-shadow:0 0 0 var(--focus-ring-width) var(--border-focus)}
.hl-line-orig{font-size:var(--text-xs);color:var(--text-tertiary);overflow-wrap:anywhere}
.hl-line-acts{grid-column:2;display:flex;gap:var(--space-2)}
.hl-tog{height:22px;padding:0 var(--space-3);border-radius:var(--radius-xs);border:var(--border-hair) solid var(--border-subtle);
  background:none;color:var(--text-tertiary);font:inherit;font-size:11px;cursor:pointer}
.hl-tog:hover{color:var(--text-primary);border-color:var(--border-strong)}
.hl-tog.is-on{background:var(--surface-active);color:var(--text-primary);border-color:var(--border-strong)}
.hl-tog.is-on.is-danger{background:var(--danger-muted);border-color:var(--danger)}
.hl-tog:disabled{opacity:var(--opacity-disabled);cursor:default}
.hl-tog:focus-visible,.hl-said-name:focus-visible,.hl-line-t:focus-visible,.hl-part-seek:focus-visible,
.hl-seg-btn:focus-visible,.hl-lane-clear:focus-visible{
  outline:var(--focus-ring-width) solid var(--border-focus);outline-offset:1px}

/* the foot: the whole video's settings, and Make */
.hl-foot{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-5) var(--space-8);
  padding-top:var(--space-5);border-top:var(--border-hair) solid var(--border-subtle)}
.hl-opt{display:flex;align-items:center;gap:var(--space-4)}
.hl-opt-label{font-size:var(--text-sm);color:var(--text-secondary)}
#hl-master{width:120px;accent-color:var(--accent)}
.hl-master-v{min-width:44px;font-size:var(--text-sm);font-variant-numeric:tabular-nums;color:var(--text-secondary)}
.hl-make{display:flex;align-items:center;gap:var(--space-4);margin-left:auto}
.hl-make-msg{font-size:var(--text-sm);font-variant-numeric:tabular-nums}

@media (max-width:1100px){
  .hl-grid{grid-template-columns:minmax(0,1fr)}
  .hl-said{max-height:420px}
}
@media (prefers-reduced-motion:reduce){.hl-stage video{transition:none}}
/* A toast's one action (shell's toast(message, kind, action)): "Edit" on
   "Your highlight video is ready." */
.toast .toast-act{flex:0 0 auto;margin-left:auto;margin-top:-2px}
"""
