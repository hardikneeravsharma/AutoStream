"""Studio page: every clip the user has made, and reels edited on a timeline.

WHAT THE PAGE IS FOR
    The Clips page is organised around ONE recording at a time -- scan it, cut
    it, fix it. That is the wrong shape for making a reel, which wants the best
    moments from every session. So this page starts from the other end: all the
    clips on disk, grouped the way they were made (game, then run), selectable
    one at a time, by range, or a whole run at once.

WHY A TIMELINE AND NOT A FORM
    A reel is a sequence of decisions in time -- this shot, this long, its kill
    on this beat, this transition into the next. A form can hold those values
    but cannot show how they relate, and "the flash lands a beat late" is only
    visible when the flash, the kill and the beat are drawn on one axis. So the
    finished reel opens as tracks: video, transitions, effects, speed, text and
    music with its beat grid, and every one of them is editable there.

THE SERVER OWNS THE ARITHMETIC
    The page edits the project; /api/studio/check clamps it and returns every
    derived time. During a drag the page moves blocks with its own quick
    estimate, then asks the server once on release. Two implementations of
    where a kill lands would eventually disagree, and the one that renders is
    the one that has to be right.

NAMING
    Every top-level JS name is studio_-prefixed; window.PAGE_STUDIO is the one
    unprefixed global (see the module contract in ui/__init__.py).
"""
from __future__ import annotations

STUDIO_HTML = r"""
<div class="studio">
  <header class="studio-head">
    <div class="studio-head-text">
      <h2 class="studio-title">Make reels from everything you have clipped</h2>
      <p class="muted" id="studio-sub">Reading your clips…</p>
    </div>
    <div class="seg" role="tablist" aria-label="Studio views">
      <button type="button" class="seg-btn is-active" role="tab" aria-selected="true"
              data-act="studio-tab" data-tab="clips" id="studio-tab-clips">Clips</button>
      <button type="button" class="seg-btn" role="tab" aria-selected="false"
              data-act="studio-tab" data-tab="timeline" id="studio-tab-timeline" disabled>Timeline</button>
      <button type="button" class="seg-btn" role="tab" aria-selected="false"
              data-act="studio-tab" data-tab="song" id="studio-tab-song" disabled>Song</button>
    </div>
  </header>

  <section id="studio-pane-clips" aria-label="Clips">
    <div class="studio-tools">
      <input class="input studio-search" id="studio-q" type="search"
             placeholder="Search clips, captions or runs" aria-label="Search clips">
      <div class="studio-games" id="studio-games" role="group" aria-label="Games"></div>
      <button type="button" class="btn btn-ghost btn-sm" data-act="studio-refresh">Refresh</button>
    </div>
    <div class="studio-reels" id="studio-reels"></div>
    <div id="studio-lib" class="studio-lib"></div>
    <p class="muted studio-empty hide" id="studio-empty"></p>
    <div class="studio-tray hide" id="studio-tray" role="region" aria-label="Selection">
      <div class="studio-tray-text">
        <strong id="studio-tray-count">0 clips</strong>
        <span class="muted" id="studio-tray-facts"></span>
      </div>
      <button type="button" class="btn btn-ghost btn-sm" data-act="studio-clear">Clear</button>
      <button type="button" class="btn btn-primary" data-act="studio-make">Make a reel</button>
    </div>
  </section>

  <section id="studio-pane-timeline" class="hide" aria-label="Timeline">
    <div class="studio-top">
      <div class="studio-player">
        <video id="studio-video" controls playsinline preload="metadata"></video>
        <div class="studio-player-empty" id="studio-player-empty">The reel appears here once it has rendered.</div>
      </div>
      <div class="studio-render card">
        <div class="card-body">
          <label class="field-label" for="studio-pname">Reel name</label>
          <input class="input" id="studio-pname" maxlength="80">
          <p class="muted studio-facts" id="studio-facts"></p>
          <div class="meter" aria-hidden="true"><div class="meter-fill" id="studio-meter" style="width:0%"></div></div>
          <p class="studio-state" id="studio-state" role="status" aria-live="polite"></p>
          <div class="field-inline">
            <button type="button" class="btn btn-primary" data-act="studio-render" id="studio-render-btn">Render</button>
            <button type="button" class="btn btn-ghost hide" data-act="studio-cancel" id="studio-cancel-btn">Cancel</button>
            <button type="button" class="btn btn-ghost" data-act="studio-undo" id="studio-undo-btn" disabled>Undo</button>
            <button type="button" class="btn btn-ghost" data-act="studio-show" id="studio-show-btn" disabled>Show file</button>
          </div>
          <ul class="studio-notes" id="studio-notes"></ul>
        </div>
      </div>
    </div>

    <div class="studio-tl-bar">
      <button type="button" class="btn btn-sm" data-act="studio-play" id="studio-play-btn">Play</button>
      <span class="mono studio-clock" id="studio-clock">0:00.00</span>
      <label class="studio-check"><input type="checkbox" id="studio-snap" checked> Snap to beats</label>
      <span class="studio-spacer"></span>
      <span class="muted studio-hint">Drag a shot to move it, its edge to trim, its diamond to move the kill.</span>
      <button type="button" class="btn btn-ghost btn-sm" data-act="studio-zoom" data-z="-1" aria-label="Zoom out">−</button>
      <button type="button" class="btn btn-ghost btn-sm" data-act="studio-zoom" data-z="0">Fit</button>
      <button type="button" class="btn btn-ghost btn-sm" data-act="studio-zoom" data-z="1" aria-label="Zoom in">+</button>
    </div>
    <div class="studio-edit">
      <div class="studio-tl" id="studio-tl" tabindex="0" aria-label="Timeline, use arrow keys to move between shots">
        <div class="studio-labels" aria-hidden="true">
          <div class="st-lab st-lab-ruler"></div>
          <div class="st-lab">Video</div>
          <div class="st-lab">Transitions</div>
          <div class="st-lab">Effects</div>
          <div class="st-lab">Speed</div>
          <div class="st-lab">Text</div>
          <div class="st-lab">Music</div>
        </div>
        <div class="studio-scroll" id="studio-scroll">
          <div class="studio-tracks" id="studio-tracks"></div>
        </div>
      </div>
      <aside class="studio-insp card" id="studio-insp" aria-label="Inspector"></aside>
    </div>
  </section>

  <!-- THE SONG. Its own place, because choosing the part of a track and where
       the kills fall in it is listening work: it wants the whole song on one
       axis, the chosen part magnified on another, and the music playing. -->
  <section id="studio-pane-song" class="hide" aria-label="Song">
    <div class="studio-sg-head">
      <div class="studio-sg-title">
        <strong class="studio-sg-name" id="studio-sg-name">No song</strong>
        <span class="muted" id="studio-sg-facts">Choose a song to cut the reel to.</span>
      </div>
      <div class="field-inline">
        <button type="button" class="btn" data-act="studio-sg-pick">Choose a song…</button>
        <button type="button" class="btn btn-ghost" data-act="studio-sg-none">No song</button>
      </div>
    </div>
    <div class="studio-sg-body hide" id="studio-sg-body">
      <p class="field-label">The whole song — drag the highlighted part, or its edges</p>
      <canvas class="studio-sg-wave" id="studio-sg-overview" height="90" aria-label="Whole song"></canvas>
      <p class="field-label">The part you are using — click to move the playhead</p>
      <canvas class="studio-sg-wave studio-sg-detail" id="studio-sg-detail" height="130" aria-label="Chosen part"></canvas>
      <audio id="studio-sg-audio" preload="auto"></audio>
      <div class="studio-tl-bar">
        <button type="button" class="btn btn-sm" data-act="studio-sg-play" id="studio-sg-play">Play the part</button>
        <label class="studio-check"><input type="checkbox" id="studio-sg-loop" checked> Loop</label>
        <span class="mono studio-clock" id="studio-sg-clock">0:00.00</span>
        <span class="muted" id="studio-sg-range"></span>
      </div>
      <div class="studio-sg-grid">
        <div class="card"><div class="card-body studio-sg-card">
          <h3 class="studio-h">Where the reel starts</h3>
          <div class="field-inline studio-nudge">
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="start" data-d="-bar">−1 bar</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="start" data-d="-beat">−1 beat</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="start" data-d="-ms">−10 ms</button>
            <span class="mono" id="studio-sg-start">0:00.00</span>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="start" data-d="ms">+10 ms</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="start" data-d="beat">+1 beat</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="start" data-d="bar">+1 bar</button>
          </div>
          <div class="field-inline">
            <button type="button" class="btn btn-sm" data-act="studio-sg-snapbar">Snap to the nearest bar</button>
            <button type="button" class="btn btn-sm" data-act="studio-sg-atdrop" id="studio-sg-atdrop">Build into the drop</button>
          </div>
          <h3 class="studio-h">Where it ends</h3>
          <div class="field-inline studio-nudge">
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="end" data-d="-bar">−1 bar</button>
            <span class="mono" id="studio-sg-end">0:00.00</span>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="end" data-d="bar">+1 bar</button>
            <button type="button" class="btn btn-sm" data-act="studio-sg-fit">Fit the timeline</button>
          </div>
          <p class="muted" id="studio-sg-fitnote"></p>
        </div></div>
        <div class="card"><div class="card-body studio-sg-card">
          <h3 class="studio-h">Mark the kills <span class="muted">(optional)</span></h3>
          <p class="muted">Play the part and press <kbd>K</kbd> on every beat a kill should land on.
             Shot 1's kill lands on mark 1, shot 2's on mark 2, and so on; the cuts move to fit.
             <kbd>Space</kbd> plays and pauses.</p>
          <div class="field-inline">
            <button type="button" class="btn btn-primary" data-act="studio-sg-mark">Mark a kill here (K)</button>
            <button type="button" class="btn btn-ghost" data-act="studio-sg-unmark">Undo mark</button>
            <button type="button" class="btn btn-ghost" data-act="studio-sg-clearmarks">Clear marks</button>
          </div>
          <div class="field-inline">
            <label class="studio-check"><input type="checkbox" id="studio-sg-snap" checked> Snap marks to the beat</label>
            <label class="studio-check"><input type="checkbox" id="studio-sg-click" checked> Click on each mark as it plays</label>
          </div>
          <div class="reel-chips" id="studio-sg-chips"></div>
          <p class="muted" id="studio-sg-marksinfo"></p>
        </div></div>
      </div>
      <div class="studio-sg-apply">
        <span class="muted" id="studio-sg-msg"></span>
        <button type="button" class="btn btn-primary" data-act="studio-sg-apply" id="studio-sg-apply">Use this part</button>
      </div>
    </div>
  </section>

  <div class="scrim hide" id="studio-make-scrim">
  <div class="modal studio-modal" id="studio-make" role="dialog" aria-modal="true" aria-labelledby="studio-make-title">
    <h2 class="modal-title" id="studio-make-title">Make a reel</h2>
    <div class="modal-body">
      <p class="muted" id="studio-make-facts"></p>
      <h3 class="studio-h">Style</h3>
      <div class="studio-styles" id="studio-styles" role="radiogroup" aria-label="Style"></div>
      <h3 class="studio-h">Song</h3>
      <div class="field-inline">
        <button type="button" class="btn" data-act="studio-song">Choose a song…</button>
        <button type="button" class="btn btn-ghost" data-act="studio-nosong">No song</button>
        <span class="muted" id="studio-song-name">No song: the clips keep their own sound, cut to a 120 BPM grid.</span>
      </div>
      <h3 class="studio-h">Shape</h3>
      <div class="field-inline studio-shape">
        <div class="seg" role="group" aria-label="Format">
          <button type="button" class="seg-btn is-active" data-act="studio-fmt" data-fmt="landscape">Landscape 16:9</button>
          <button type="button" class="seg-btn" data-act="studio-fmt" data-fmt="vertical">Vertical 9:16</button>
        </div>
        <div class="seg" role="group" aria-label="Order">
          <button type="button" class="seg-btn is-active" data-act="studio-order" data-order="chosen">As chosen</button>
          <button type="button" class="seg-btn" data-act="studio-order" data-order="kills">Most kills first</button>
          <button type="button" class="seg-btn" data-act="studio-order" data-order="oldest">Oldest first</button>
        </div>
      </div>
      <label class="field-label" for="studio-name">Name</label>
      <input class="input" id="studio-name" maxlength="80" placeholder="Montage reel">
    </div>
    <div class="modal-actions">
      <span class="muted" id="studio-make-msg"></span>
      <button type="button" class="btn btn-ghost" data-act="studio-make-cancel">Cancel</button>
      <button type="button" class="btn btn-primary" data-act="studio-build" id="studio-build-btn">Build and render</button>
    </div>
  </div>
  </div>

  <div class="scrim hide" id="studio-preview-scrim">
  <div class="modal studio-modal" id="studio-preview" role="dialog" aria-modal="true" aria-labelledby="studio-preview-title">
    <h2 class="modal-title" id="studio-preview-title">Clip</h2>
    <div class="modal-body"><video id="studio-preview-video" controls playsinline></video></div>
    <div class="modal-actions">
      <button type="button" class="btn btn-ghost" data-act="studio-preview-close">Close</button>
    </div>
  </div>
  </div>
</div>
"""

STUDIO_JS = r"""
/* =======================================================================
   STUDIO -- all clips, reels, and the timeline editor. Prefix: studio_
   ======================================================================= */

const studio = {
  lib: null, catalog: null, loadedAt: 0,
  game: 'all', q: '', selected: [], lastClick: null,
  style: '', song: '', songShape: null, fmt: 'landscape', order: 'chosen',
  project: null, derived: null, notes: [], dirty: true, output: '', renderedAt: 0,
  sel: -1, pps: 60, snap: true, undo: [], checking: 0, checkTimer: null,
  polling: null, drag: null, clipIndex: {},
  gen: 0, jobId: 0, seenJob: -1, watching: -1, busy: false, pollTok: 0,
  sg: {song: '', shape: null, start: 0, end: 0, marks: [], drag: null, ticked: {}, ac: null}
};

const studio_el = (id) => document.getElementById(id);
const studio_show = (id, on) => { const e = studio_el(id); if (e) e.classList.toggle('hide', !on); };

/* The whole route, written out at every call: the wiring test finds the pages'
   routes by their literal text, and a route assembled from pieces is a route
   nothing appears to call. */
function studio_media(route, path, extra) {
  return route + '?k=' + encodeURIComponent(SHELL_K) + '&path=' +
         encodeURIComponent(path) + (extra || '');
}

function studio_secs(t) {
  t = Math.max(0, Number(t) || 0);
  const m = Math.floor(t / 60), s = t - m * 60;
  return m + ':' + (s < 10 ? '0' : '') + s.toFixed(2);
}

function studio_dur(t) {
  t = Math.round(Math.max(0, Number(t) || 0));
  return t >= 60 ? Math.floor(t / 60) + 'm ' + String(t % 60).padStart(2, '0') + 's' : t + 's';
}

function studio_part(id) {
  const p = (studio.catalog && studio.catalog.parts || []).find(x => x.id === id);
  return p || {id: id, label: id, blurb: '', kind: ''};
}

function studio_parts(kind) {
  return (studio.catalog && studio.catalog.parts || []).filter(p => p.kind === kind);
}

/* ------------------------------------------------------------ loading */

async function studio_load(force) {
  if (!studio.catalog) {
    const cat = await API.get('/api/studio/catalog');
    if (cat && cat.ok) { studio.catalog = cat; studio.style = cat.default_style; }
  }
  if (!force && studio.lib && Date.now() - studio.loadedAt < 30000) { studio_renderLib(); return; }
  const lib = await API.get('/api/studio/library');
  if (!lib || !lib.ok) {
    studio_el('studio-sub').textContent = (lib && lib.error) || 'Could not read the clips folder.';
    return;
  }
  studio.lib = lib; studio.loadedAt = Date.now(); studio.clipIndex = {};
  lib.games.forEach(g => g.folders.forEach(f => f.clips.forEach(c => {
    c.game = g.game; c.folderLabel = f.label; c.when = f.when; studio.clipIndex[c.id] = c;
  })));
  studio.selected = studio.selected.filter(id => studio.clipIndex[id]);
  studio_renderLib();
}

/* ------------------------------------------------------------ the library */

function studio_visible() {
  const q = studio.q.trim().toLowerCase();
  const out = [];
  (studio.lib ? studio.lib.games : []).forEach(g => {
    if (studio.game !== 'all' && g.game !== studio.game) return;
    g.folders.forEach(f => {
      const clips = f.clips.filter(c => !q ||
        (c.name + ' ' + c.caption + ' ' + f.label + ' ' + g.game).toLowerCase().indexOf(q) >= 0);
      if (clips.length) out.push({game: g.game, folder: f, clips: clips});
    });
  });
  return out;
}

function studio_renderLib() {
  const lib = studio.lib;
  if (!lib) return;
  const games = lib.games.length;
  studio_el('studio-sub').textContent = lib.clip_count
    ? lib.clip_count + ' clips from ' + lib.games.reduce((n, g) => n + g.folders.length, 0) +
      ' runs across ' + games + (games === 1 ? ' game' : ' games') +
      '. Pick any of them, from any run, and make a reel.'
    : 'No clips yet. Cut some on the Clips page and they will appear here.';
  studio_el('studio-games').innerHTML =
    '<button type="button" class="chip' + (studio.game === 'all' ? ' is-on' : '') +
    '" data-act="studio-game" data-game="all" aria-pressed="' + (studio.game === 'all') + '">All <b>' +
    lib.clip_count + '</b></button>' +
    lib.games.map(g => '<button type="button" class="chip' + (studio.game === g.game ? ' is-on' : '') +
      '" data-act="studio-game" data-game="' + esc(g.game) + '" aria-pressed="' + (studio.game === g.game) +
      '">' + esc(g.game) + ' <b>' + g.clips + '</b></button>').join('');

  const reels = lib.reels || [];
  studio_el('studio-reels').innerHTML = reels.length
    ? '<h3 class="studio-h">Your reels</h3><div class="studio-reel-row">' + reels.slice(0, 10).map(r =>
      '<div class="studio-reel">' +
      '<span class="studio-reel-name truncate" title="' + esc(r.name) + '">' + esc(r.name) + '</span>' +
      '<span class="muted studio-reel-meta">' + (r.shots ? r.shots + ' shots · ' : '') +
      (r.length ? studio_dur(r.length) + ' · ' : '') + new Date(r.when * 1000).toLocaleDateString() + '</span>' +
      '<span class="field-inline">' +
      (r.project ? '<button type="button" class="btn btn-sm" data-act="studio-open" data-path="' + esc(r.path) + '">Open timeline</button>'
                 : '<span class="muted studio-reel-old">Made before the Studio</span>') +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-watch" data-path="' + esc(r.path) + '">Play</button>' +
      '</span></div>').join('') + '</div>'
    : '';

  const groups = studio_visible();
  const pos = {};
  studio.selected.forEach((id, i) => { pos[id] = i + 1; });
  let lastGame = '';
  let html = '';
  groups.forEach(gr => {
    if (gr.game !== lastGame) {
      html += '<h3 class="studio-game-h">' + esc(gr.game) + '</h3>';
      lastGame = gr.game;
    }
    const allOn = gr.clips.every(c => pos[c.id]);
    html += '<section class="studio-folder" aria-label="' + esc(gr.folder.label) + '">' +
      '<div class="studio-folder-h"><span class="studio-folder-name">' + esc(gr.folder.label) + '</span>' +
      '<span class="muted">' + gr.clips.length + ' clips</span>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-folder" data-folder="' +
      esc(gr.folder.folder) + '">' + (allOn ? 'Unselect run' : 'Select run') + '</button></div>' +
      '<div class="studio-grid">' + gr.clips.map(c => studio_tile(c, pos[c.id])).join('') + '</div></section>';
  });
  studio_el('studio-lib').innerHTML = html;
  const empty = !groups.length;
  studio_show('studio-empty', empty && lib.clip_count > 0);
  if (empty && lib.clip_count) studio_el('studio-empty').textContent = 'Nothing matches that search.';
  studio_renderTray();
}

function studio_tile(c, n) {
  const kill = (c.kills && c.kills.length ? c.kills[0] : 0);
  const at = Math.max(0, kill - 0.3).toFixed(2);
  return '<div class="studio-clip' + (n ? ' is-on' : '') + '" data-clip="' + esc(c.id) + '">' +
    '<button type="button" class="studio-clip-hit" data-act="studio-pick" data-clip="' + esc(c.id) +
    '" aria-pressed="' + (!!n) + '" aria-label="' + esc(c.name) + '">' +
    '<img loading="lazy" alt="" width="320" height="180" src="' + studio_media('/api/studio/thumb', c.path, '&t=' + at + '&v=' + (c.mtime || 0)) + '">' +
    '<span class="studio-clip-n">' + (n || '') + '</span>' +
    '<span class="studio-clip-dur mono">' + studio_dur(c.duration) + '</span>' +
    '<span class="studio-clip-kills">' + (c.kill_count > 1 ? c.kill_count + ' kills' : '1 kill') + '</span>' +
    '</button>' +
    '<div class="studio-clip-foot"><span class="truncate" title="' + esc(c.name) + '">' +
    esc(c.caption || c.name) + '</span>' +
    '<button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="studio-preview" data-clip="' +
    esc(c.id) + '" aria-label="Play ' + esc(c.name) + '">' + icon('play') + '</button></div></div>';
}

/* Selection changes touch the tiles they change. Rebuilding the grid on every
   click reloaded every thumbnail and threw away the scroll anchor. */
function studio_syncSelection() {
  const pos = {};
  studio.selected.forEach((id, i) => { pos[id] = i + 1; });
  document.querySelectorAll('#studio-lib .studio-clip').forEach(el => {
    const n = pos[el.getAttribute('data-clip')] || 0;
    el.classList.toggle('is-on', !!n);
    const badge = el.querySelector('.studio-clip-n');
    if (badge) badge.textContent = n ? String(n) : '';
    const hit = el.querySelector('.studio-clip-hit');
    if (hit) hit.setAttribute('aria-pressed', String(!!n));
  });
  studio_visible().forEach(gr => {
    const btn = document.querySelector('#studio-lib [data-act="studio-folder"][data-folder="' + CSS.escape(gr.folder.folder) + '"]');
    if (btn) btn.textContent = gr.clips.every(c => pos[c.id]) ? 'Unselect run' : 'Select run';
  });
  studio_renderTray();
}

function studio_renderTray() {
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  studio_show('studio-tray', sel.length > 0);
  studio_el('studio-tray-count').textContent = sel.length + (sel.length === 1 ? ' clip' : ' clips');
  const secs = sel.reduce((n, c) => n + c.duration, 0);
  const kills = sel.reduce((n, c) => n + (c.kill_count || 1), 0);
  const games = new Set(sel.map(c => c.game)).size;
  studio_el('studio-tray-facts').textContent = sel.length
    ? studio_dur(secs) + ' of footage · ' + kills + ' kills' + (games > 1 ? ' · ' + games + ' games' : '') : '';
}

function studio_pick(id, shift) {
  const flat = [];
  studio_visible().forEach(g => g.clips.forEach(c => flat.push(c.id)));
  const i = studio.selected.indexOf(id);
  if (shift && studio.lastClick && flat.indexOf(studio.lastClick) >= 0) {
    const a = flat.indexOf(studio.lastClick), b = flat.indexOf(id);
    const lo = Math.min(a, b), hi = Math.max(a, b);
    for (let k = lo; k <= hi; k++) if (studio.selected.indexOf(flat[k]) < 0) studio.selected.push(flat[k]);
  } else if (i >= 0) {
    studio.selected.splice(i, 1);
  } else {
    studio.selected.push(id);
  }
  studio.lastClick = id;
  studio_syncSelection();
}

function studio_folderToggle(folder) {
  const f = studio_visible().find(g => g.folder.folder === folder);
  if (!f) return;
  const ids = f.clips.map(c => c.id);
  const all = ids.every(id => studio.selected.indexOf(id) >= 0);
  if (all) studio.selected = studio.selected.filter(id => ids.indexOf(id) < 0);
  else ids.forEach(id => { if (studio.selected.indexOf(id) < 0) studio.selected.push(id); });
  studio_syncSelection();
}

function studio_preview(id) {
  const c = studio.clipIndex[id];
  if (!c) return;
  studio_el('studio-preview-title').textContent = c.caption || c.name;
  const v = studio_el('studio-preview-video');
  v.src = studio_media('/api/clips/video', c.path);
  studio_show('studio-preview-scrim', true);
  v.play().catch(() => {});
}

function studio_closeModals() {
  const v = studio_el('studio-preview-video');
  if (v) { v.pause(); v.removeAttribute('src'); v.load(); }
  ['studio-preview-scrim', 'studio-make-scrim'].forEach(id => studio_show(id, false));
}

/* ------------------------------------------------------------ make a reel */

function studio_openMake() {
  if (!studio.selected.length) return;
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  studio_el('studio-make-facts').textContent = sel.length + ' clips, ' +
    sel.reduce((n, c) => n + (c.kill_count || 1), 0) + ' kills. Every cut and kill lands on the beat; ' +
    'you can change anything on the timeline afterwards.';
  studio_renderStyles();
  studio_el('studio-make-msg').textContent = '';
  studio_show('studio-make-scrim', true);
}

function studio_renderStyles() {
  const cat = studio.catalog;
  if (!cat) return;
  studio_el('studio-styles').innerHTML = cat.styles.map(s => {
    const m = s.measured || {};
    const on = s.key === studio.style;
    return '<button type="button" class="studio-style' + (on ? ' is-on' : '') + '" role="radio" aria-checked="' + on +
      '" data-act="studio-style" data-style="' + esc(s.key) + '">' +
      '<span class="studio-style-name">' + esc(s.label) + '</span>' +
      '<span class="studio-style-blurb">' + esc(s.blurb) + '</span>' +
      (m.edits ? '<span class="studio-style-data mono">Measured on ' + m.edits + (m.edits === 1 ? ' edit' : ' edits') + ': ' +
        m.cuts_per_min + ' cuts/min · ' + m.flashes_per_min + ' flashes/min · first shot ' + m.first_shot + ' s</span>' : '') +
      '</button>';
  }).join('');
  const st = cat.styles.find(s => s.key === studio.style);
  studio_el('studio-name').placeholder = (st ? st.label : 'My') + ' reel';
}

async function studio_pickSong() {
  const r = await API.post('/api/clips/pick', {kind: 'audio'});
  if (!r || !r.path) return;
  studio_el('studio-song-name').textContent = 'Reading ' + r.path.split(/[\\/]/).pop() + '…';
  const got = await API.post('/api/reel/song', {song: r.path});
  if (!got || !got.ok) {
    studio_el('studio-song-name').textContent = (got && got.error) || 'Could not read that song.';
    return;
  }
  studio.song = r.path; studio.songShape = got.song;
  studio_el('studio-song-name').textContent = r.path.split(/[\\/]/).pop() + ' · ' +
    Math.round(got.song.bpm) + ' BPM · ' + studio_dur(got.song.seconds) +
    (got.song.drop ? ' · drop at ' + studio_secs(got.song.drop) : '');
}

function studio_ordered() {
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  if (studio.order === 'kills') return sel.slice().sort((a, b) => (b.kill_count || 1) - (a.kill_count || 1));
  if (studio.order === 'oldest') return sel.slice().sort((a, b) => (a.when - b.when) || (a.rank - b.rank));
  return sel;
}

async function studio_build() {
  const btn = studio_el('studio-build-btn');
  btn.disabled = true;
  studio_el('studio-make-msg').textContent = studio.song ? 'Finding the beat and planning every shot…' : 'Planning every shot…';
  try {
    const r = await API.post('/api/studio/plan', {
      clips: studio_ordered().map(c => c.path), style: studio.style, song: studio.song,
      format: studio.fmt, name: studio_el('studio-name').value.trim()
    });
    if (!r || !r.ok) { studio_el('studio-make-msg').textContent = (r && r.error) || 'Could not plan that reel.'; return; }
    studio_closeModals();
    studio_setProject(r.project, r.derived, r.notes, r.song);
    studio.output = ''; studio.dirty = true; studio.undo = [];
    studio_tab('timeline');
    studio_fit();
    studio_render();
  } finally {
    btn.disabled = false;
  }
}

/* ------------------------------------------------------------ project */

function studio_setProject(project, derived, notes, songShape) {
  studio.project = project; studio.derived = derived; studio.notes = notes || [];
  if (songShape !== undefined) studio.songShape = songShape;
  if (project.output) studio.output = project.output;
  studio_el('studio-tab-timeline').disabled = false;
  studio_el('studio-tab-song').disabled = false;
  studio_el('studio-pname').value = project.name || '';
  if (studio.sel >= project.shots.length) studio.sel = project.shots.length - 1;
  studio_drawAll();
}

function studio_pushUndo(snapshot) {
  studio.undo.push(snapshot);
  if (studio.undo.length > 60) studio.undo.shift();
}

function studio_change(mutate, immediate) {
  if (!studio.project) return;
  studio_pushUndo(JSON.stringify(studio.project));
  studio.gen++;
  mutate(studio.project);
  studio.dirty = true;
  studio_localDerive();
  studio_drawAll();
  clearTimeout(studio.checkTimer);
  studio.checkTimer = setTimeout(studio_check, immediate ? 0 : 250);
}

async function studio_check() {
  const n = ++studio.checking;
  const gen = studio.gen;
  const r = await API.post('/api/studio/check', {project: studio.project});
  /* An answer about an older project must never replace a newer one: an edit
     made while this was in flight would silently disappear. */
  if (n !== studio.checking || gen !== studio.gen) return;
  if (!r || !r.ok) { toast((r && r.error) || 'That edit could not be applied.', 'warn'); return; }
  studio.project = r.project; studio.derived = r.derived; studio.notes = r.notes || [];
  studio_drawAll();
}

function studio_undo() {
  const last = studio.undo.pop();
  if (!last) return;
  studio.gen++;
  studio.project = JSON.parse(last);
  studio.dirty = true;
  studio_localDerive(); studio_drawAll();
  studio_check();
}

/* A quick estimate while dragging. The server's answer replaces it. */
function studio_localDerive() {
  const p = studio.project, d = studio.derived;
  if (!p) return;
  let t = 0;
  const rows = p.shots.map((s, i) => {
    const old = (d && d.shots[i]) || {};
    const row = {index: i, start: t, end: t + s.duration, kill_reel: t + s.pre,
                 kills_reel: [t + s.pre], pieces: old.pieces || [[0, s.duration, 1]]};
    t += s.duration;
    return row;
  });
  const beat = p.beat || 0.5;
  const beats = [];
  for (let b = 0; b <= t + 1e-6; b += beat) beats.push(b);
  studio.derived = {length: t, shots: rows, kills: rows.map(r => r.kill_reel), beats: beats, beat: beat,
                    bpm: 60 / beat};
}

function studio_snapTo(t) {
  const beat = (studio.project && studio.project.beat) || 0.5;
  return studio_el('studio-snap').checked ? Math.round(t / beat) * beat : Math.round(t * 60) / 60;
}

/* ------------------------------------------------------------ rendering */

async function studio_render() {
  if (!studio.project) return;
  /* A check still waiting or in flight describes the project before the
     server allocates its output; letting it land afterwards would wipe that. */
  clearTimeout(studio.checkTimer);
  studio.gen++;
  /* The previous render is old news once a new one is asked for: a poll that
     lands in between must not say "Ready" about the reel being replaced. */
  studio.seenJob = studio.jobId; studio.watching = -1;
  studio.project.name = studio_el('studio-pname').value.trim() || studio.project.name;
  const r = await API.post('/api/studio/render', {project: studio.project});
  if (!r || !r.ok) { studio_state((r && r.error) || 'Could not start the render.', true); return; }
  studio.project = r.project; studio.derived = r.derived; studio.notes = r.notes || [];
  studio.output = r.output;
  studio.jobId = r.job || 0;
  studio_drawAll();
  studio_poll();
}

function studio_state(msg, bad) {
  const el = studio_el('studio-state');
  el.textContent = msg || '';
  el.classList.toggle('is-bad', !!bad);
}

async function studio_poll() {
  clearTimeout(studio.polling);
  /* One loop. Render and every visit to the page start a poll; without this
     each left its predecessor running, and they multiplied. */
  const mine = ++studio.pollTok;
  const j = await API.get('/api/studio/job');
  if (mine !== studio.pollTok) return;
  if (!j || j.state === 'idle') { studio_busy(false); return; }
  const running = j.state === 'running' || j.state === 'queued';
  studio_busy(running);
  studio_el('studio-meter').style.width = (running ? j.percent : 100) + '%';
  if (running) {
    studio.watching = j.id;       /* seen running on this page: its finish is news */
    studio_state(j.message + (j.cached ? ' · ' + j.cached + ' shots unchanged' : ''));
    studio.polling = setTimeout(studio_poll, 700);
    return;
  }
  /* A finished job is news once, and only to a page that started it or watched
     it run. The server keeps the last job for as long as it runs, so without
     this every visit to the page announced the same reel again. */
  const news = j.id !== studio.seenJob && (j.id === studio.jobId || j.id === studio.watching);
  studio.seenJob = j.id;
  if (!news) { studio_drawRenderCard(); return; }
  if (j.state === 'done') {
    const same = studio.project && j.output === studio.project.output;
    studio_state('Ready · rendered in ' + j.elapsed + ' s' + (j.cached ? ' · ' + j.cached + ' shots reused' : ''));
    if (same) {
      studio.dirty = false; studio.output = j.output; studio.renderedAt = Date.now();
      studio_loadVideo();
    }
    toast('Reel ready.', 'ok');
    studio.loadedAt = 0;
  } else if (j.state === 'failed') {
    studio_state(j.error || 'The render failed.', true);
  } else {
    studio_state('Cancelled.');
  }
  studio_drawRenderCard();
}

function studio_busy(on) {
  studio_show('studio-cancel-btn', on);
  studio_el('studio-render-btn').disabled = on;
}

function studio_loadVideo() {
  const v = studio_el('studio-video');
  if (!studio.output) { v.removeAttribute('src'); studio_show('studio-player-empty', true); return; }
  v.src = studio_media('/api/clips/video', studio.output, '&v=' + studio.renderedAt);
  studio_show('studio-player-empty', false);
}

function studio_drawRenderCard() {
  const p = studio.project, d = studio.derived;
  if (!p || !d) return;
  const st = (studio.catalog ? studio.catalog.styles : []).find(s => s.key === p.style);
  studio_el('studio-facts').textContent = studio_dur(d.length) + ' · ' + p.shots.length + ' shots · ' +
    Math.round(d.bpm) + ' BPM grid · ' + (st ? st.label : p.style) + ' · ' +
    (p.format === 'vertical' ? '9:16' : '16:9') + (p.song ? '' : ' · no song');
  const btn = studio_el('studio-render-btn');
  btn.textContent = studio.output ? (studio.dirty ? 'Render changes' : 'Render again') : 'Render';
  studio_el('studio-undo-btn').disabled = !studio.undo.length;
  studio_el('studio-show-btn').disabled = !studio.output || studio.dirty && !studio.renderedAt;
  studio_el('studio-notes').innerHTML = (studio.notes || []).map(n => '<li>' + esc(n) + '</li>').join('');
}

/* ------------------------------------------------------------ timeline */

const STUDIO_ROW = {ruler: 26, video: 64, trans: 30, fx: 34, speed: 38, text: 30, music: 56};

function studio_drawAll() {
  studio_drawRenderCard();
  studio_drawTimeline();
  /* Rebuilding the panel under a focused field throws away what is being
     typed; the panel is redrawn when the field is left instead. */
  const a = document.activeElement;
  const typing = a && a.closest && a.closest('#studio-insp') &&
    /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) && a.type !== 'checkbox' && a.type !== 'range';
  if (!typing) studio_drawInspector();
}

function studio_fit() {
  const d = studio.derived;
  const box = studio_el('studio-scroll');
  if (!d || !box) return;
  const w = Math.max(320, box.clientWidth - 24);
  studio.pps = Math.max(12, Math.min(400, w / Math.max(1, d.length)));
}

function studio_drawTimeline() {
  const p = studio.project, d = studio.derived;
  const host = studio_el('studio-tracks');
  if (!p || !d || !host) return;
  const pps = studio.pps, L = d.length, W = Math.ceil(L * pps) + 24;
  const X = (t) => (t * pps).toFixed(1);
  let top = 0;
  const rows = {};
  Object.keys(STUDIO_ROW).forEach(k => { rows[k] = top; top += STUDIO_ROW[k]; });
  let h = '<div class="st-area" style="width:' + W + 'px;height:' + top + 'px">';

  /* ruler: seconds, bars and beats */
  h += '<div class="st-ruler" data-act="studio-seek" style="top:0;height:' + STUDIO_ROW.ruler + 'px">';
  const step = pps > 120 ? 1 : pps > 40 ? 2 : pps > 18 ? 5 : 10;
  for (let t = 0; t <= L + 1e-6; t += step) {
    h += '<span class="st-tick" style="left:' + X(t) + 'px">' + studio_secs(t).replace(/\.\d+$/, '') + '</span>';
  }
  h += '</div>';
  (d.beats || []).forEach((b, i) => {
    const bar = i % 4 === 0;
    if (!bar && pps < 30) return;
    h += '<i class="st-beat' + (bar ? ' is-bar' : '') + '" style="left:' + X(b) + 'px;top:' + STUDIO_ROW.ruler +
         'px;height:' + (top - STUDIO_ROW.ruler) + 'px"></i>';
  });

  /* video */
  p.shots.forEach((s, i) => {
    const r = d.shots[i];
    if (!r) return;
    const c = studio.clipIndex[s.clip_id] || null;
    const thumb = studio_media('/api/studio/thumb', s.clip, '&t=' + Math.max(0, s.kill - 0.3).toFixed(2) +
                               '&v=' + ((c && c.mtime) || 0));
    const w = Math.max(6, (r.end - r.start) * pps);
    h += '<div class="st-shot' + (i === studio.sel ? ' is-sel' : '') + (s.hero ? ' is-hero' : '') +
      '" data-shot="' + i + '" style="left:' + X(r.start) + 'px;top:' + rows.video + 'px;width:' + w.toFixed(1) +
      'px;height:' + STUDIO_ROW.video + 'px;background-image:url(\'' + thumb + '\')" title="' + esc(s.name) + '">' +
      '<span class="st-shot-name">' + (i + 1) + (w > 70 ? ' · ' + esc((c && c.caption) || s.name) : '') + '</span>' +
      '<span class="st-kill" data-kill="' + i + '" style="left:' + ((r.kill_reel - r.start) * pps).toFixed(1) +
      'px" title="Kill — drag to move it"></span>' +
      '<span class="st-trim" data-trim="' + i + '" title="Drag to change the length"></span></div>';
  });

  /* transitions: a label where there is room for one, a marker where not */
  p.shots.forEach((s, i) => {
    if (i === 0) return;
    const r = d.shots[i];
    const part = studio_part(s.transition);
    const hard = s.transition === 't01';
    const room = Math.min((r.end - r.start) * pps, (d.shots[i - 1].end - d.shots[i - 1].start) * pps);
    const compact = room < 44;
    h += '<button type="button" class="st-tr' + (hard ? ' is-cut' : '') + (compact ? ' is-compact' : '') +
      (i === studio.sel ? ' is-sel' : '') + '" data-act="studio-select" data-shot="' + i + '" style="left:' + X(r.start) +
      'px;top:' + rows.trans + 'px' + (compact ? '' : ';width:' + Math.max(26, s.tlen * pps).toFixed(1) + 'px') +
      '" title="Shot ' + (i + 1) + ': ' + esc(part.label) + '">' +
      (compact ? '' : esc(hard ? '|' : s.transition.toUpperCase())) + '</button>';
  });

  /* effects: every id on a wide shot, a count on a narrow one */
  p.shots.forEach((s, i) => {
    const r = d.shots[i];
    const ids = s.fx.concat(s.hero ? s.hero_fx : []);
    if (!ids.length) return;
    const room = (r.end - r.start) * pps;
    const full = ids.map(x => x.toUpperCase()).join(' ');
    const label = room >= full.length * 7 + 16 ? full : room >= 30 ? String(ids.length) : '';
    h += '<button type="button" class="st-fx' + (s.hero ? ' is-hero' : '') + (label === full ? '' : ' is-compact') +
      '" data-act="studio-select" data-shot="' + i +
      '" style="left:' + X(r.kill_reel) + 'px;top:' + (rows.fx + 6) + 'px" title="Shot ' + (i + 1) + ': ' +
      esc(ids.map(id => studio_part(id).label).join(', ')) + ' — click to change">' + esc(label) + '</button>';
  });

  /* speed: one line per shot, real speed through the middle */
  h += '<svg class="st-speed" style="top:' + rows.speed + 'px;height:' + STUDIO_ROW.speed + 'px;width:' + W +
       'px" viewBox="0 0 ' + W + ' ' + STUDIO_ROW.speed + '" preserveAspectRatio="none" aria-hidden="true">';
  const mid = STUDIO_ROW.speed / 2;
  h += '<line class="st-speed-base" x1="0" x2="' + W + '" y1="' + mid + '" y2="' + mid + '"></line>';
  p.shots.forEach((s, i) => {
    const r = d.shots[i];
    const pts = [];
    (r.pieces || []).forEach(pc => {
      const y = (mid - Math.max(-1.8, Math.min(1.8, Math.log2(pc[2]))) * (mid - 4) / 1.8).toFixed(1);
      pts.push(X(r.start + pc[0]) + ',' + y, X(r.start + pc[1]) + ',' + y);
    });
    if (pts.length) h += '<polyline class="st-speed-line' + (s.speed !== 's00' ? ' is-ramp' : '') + '" points="' + pts.join(' ') + '"></polyline>';
  });
  h += '</svg>';

  /* text & overlays */
  const texts = [];
  if (p.intro && p.intro !== 'i00') texts.push([0, Math.min(L, 1.2), studio_part(p.intro).label]);
  if (p.outro && p.outro !== 'e12') texts.push([Math.max(0, L - 1.2), L, studio_part(p.outro).label]);
  (p.overlays || []).forEach(o => texts.push(o === 'i04' ? [1, Math.min(L, 7), studio_part(o).label] : [0, L, studio_part(o).label]));
  p.shots.forEach((s, i) => {
    if (s.hero && s.hero_fx.indexOf('h05') >= 0 && s.caption) {
      texts.push([d.shots[i].kill_reel, Math.min(L, d.shots[i].kill_reel + 1.4), '“' + s.caption + '”']);
    }
  });
  texts.forEach((t, k) => {
    h += '<button type="button" class="st-text" data-act="studio-select" data-shot="-1" style="left:' + X(t[0]) +
      'px;top:' + (rows.text + 3 + (k % 2) * 2) + 'px;width:' + Math.max(12, (t[1] - t[0]) * pps).toFixed(1) +
      'px" title="' + esc(t[2]) + '">' + esc(t[2]) + '</button>';
  });

  /* music */
  h += '<canvas class="st-music" id="studio-wave" style="top:' + rows.music + 'px;height:' + STUDIO_ROW.music + 'px"></canvas>';
  h += '<div class="st-ph" id="studio-ph" style="height:' + top + 'px"></div>';
  h += '</div>';
  host.innerHTML = h;
  studio_drawWave(W);
  studio_playhead();
}

function studio_drawWave(W) {
  const cv = studio_el('studio-wave');
  const p = studio.project, d = studio.derived, sh = studio.songShape;
  if (!cv || !p || !d) return;
  const dpr = window.devicePixelRatio || 1;
  const cw = Math.min(16000, W);
  cv.style.width = W + 'px';
  cv.width = Math.round(cw * dpr); cv.height = Math.round(STUDIO_ROW.music * dpr);
  const ctx = cv.getContext('2d');
  ctx.scale(cv.width / W, dpr);
  const H = STUDIO_ROW.music, mid = H / 2;
  const css = getComputedStyle(document.documentElement);
  ctx.fillStyle = css.getPropertyValue('--accent').trim() || '#5aa9ff';
  if (p.song && sh && sh.peaks && sh.peaks.length) {
    const n = sh.peaks.length, per = sh.seconds / n;
    for (let x = 0; x < W; x += 2) {
      const t = p.song_offset + x / studio.pps;
      const k = Math.floor(t / per);
      if (k < 0 || k >= n) continue;
      const a = sh.peaks[k] * (mid - 3);
      ctx.fillRect(x, mid - a, 1.5, a * 2);
    }
    if (sh.drop) {
      const x = (sh.drop - p.song_offset) * studio.pps;
      if (x >= 0 && x <= W) { ctx.fillStyle = css.getPropertyValue('--warn').trim() || '#e3b341'; ctx.fillRect(x, 0, 2, H); }
    }
  } else {
    ctx.globalAlpha = 0.35;
    ctx.fillRect(0, mid - 1, W, 2);
    ctx.globalAlpha = 1;
    ctx.font = '12px sans-serif';
    ctx.fillText('No song — the clips keep their own sound', 8, mid - 6);
  }
}

function studio_playhead() {
  const v = studio_el('studio-video'), ph = studio_el('studio-ph');
  const t = v && v.src ? v.currentTime || 0 : 0;
  if (ph) ph.style.left = (t * studio.pps).toFixed(1) + 'px';
  const c = studio_el('studio-clock');
  if (c) c.textContent = studio_secs(t);
}

function studio_select(i) {
  studio.sel = i;
  studio_drawTimeline();
  studio_drawInspector();
}

/* ------------------------------------------------------------ inspector */

function studio_select_html(id, kind, value, allowNone) {
  return '<select class="select" id="' + id + '">' + studio_parts(kind).map(p =>
    '<option value="' + esc(p.id) + '"' + (p.id === value ? ' selected' : '') + '>' + esc(p.id.toUpperCase() + ' · ' + p.label) + '</option>'
  ).join('') + '</select>';
}

function studio_pool_html(kind, values) {
  return '<div class="studio-checks">' + studio_parts(kind).filter(p => p.id !== 't01' || kind === 'transition').map(p =>
    '<label class="studio-check-chip' + (values.indexOf(p.id) >= 0 ? ' is-on' : '') + '" title="' + esc(p.blurb) + '">' +
    '<input type="checkbox" data-pool="' + kind + '" value="' + esc(p.id) + '"' + (values.indexOf(p.id) >= 0 ? ' checked' : '') + '> ' +
    esc(p.label) + '</label>').join('') + '</div>';
}

function studio_checks_html(name, kind, values) {
  return '<div class="studio-checks">' + studio_parts(kind).map(p =>
    '<label class="studio-check-chip' + (values.indexOf(p.id) >= 0 ? ' is-on' : '') + '" title="' + esc(p.blurb) + '">' +
    '<input type="checkbox" data-list="' + name + '" value="' + esc(p.id) + '"' + (values.indexOf(p.id) >= 0 ? ' checked' : '') + '> ' +
    esc(p.label) + '</label>').join('') + '</div>';
}

function studio_drawInspector() {
  const box = studio_el('studio-insp');
  const p = studio.project;
  if (!box || !p) return;
  const tabs = '<div class="seg studio-insp-tabs" role="tablist">' +
    '<button type="button" class="seg-btn' + (studio.sel >= 0 ? ' is-active' : '') + '" data-act="studio-select" data-shot="' + Math.max(0, studio.sel) + '"' + (p.shots.length ? '' : ' disabled') + '>Shot</button>' +
    '<button type="button" class="seg-btn' + (studio.sel < 0 ? ' is-active' : '') + '" data-act="studio-select" data-shot="-1">Reel</button></div>';
  if (studio.sel >= 0 && p.shots[studio.sel]) {
    const i = studio.sel, s = p.shots[i], r = studio.derived.shots[i] || {};
    const beat = p.beat || 0.5;
    const kills = s.kills.map((k, j) => '<option value="' + k + '"' + (Math.abs(k - s.kill) < 0.01 ? ' selected' : '') + '>Kill ' + (j + 1) + ' at ' + k.toFixed(2) + ' s</option>').join('');
    box.innerHTML = tabs + '<div class="card-body studio-insp-body">' +
      '<div class="studio-insp-head"><strong>Shot ' + (i + 1) + ' of ' + p.shots.length + '</strong>' +
      '<span class="field-inline"><button type="button" class="btn btn-ghost btn-sm" data-act="studio-move" data-d="-1"' + (i ? '' : ' disabled') + ' aria-label="Move earlier">◀</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-move" data-d="1"' + (i < p.shots.length - 1 ? '' : ' disabled') + ' aria-label="Move later">▶</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-remove">Remove</button></span></div>' +
      '<p class="muted truncate" title="' + esc(s.name) + '">' + esc(s.name) + '</p>' +
      '<p class="muted mono">' + studio_secs(r.start) + ' → ' + studio_secs(r.end) + ' · kill at ' + studio_secs(r.kill_reel) + '</p>' +
      '<div class="studio-field"><span class="field-label">Kill</span>' +
      (s.kills.length > 1 ? '<select class="select" id="studio-f-kill">' + kills + '</select>' : '<span class="muted">' + s.kill.toFixed(2) + ' s into the clip</span>') +
      '<span class="field-inline studio-nudge"><button type="button" class="btn btn-ghost btn-sm" data-act="studio-slip" data-d="-0.1">−0.1s</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-slip" data-d="-0.0167">−1f</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-slip" data-d="0.0167">+1f</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-slip" data-d="0.1">+0.1s</button></span></div>' +
      '<div class="studio-field"><span class="field-label">Run-up</span><span class="field-inline">' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-beats" data-what="pre" data-d="-1">−</button>' +
      '<span class="mono">' + (s.pre / beat).toFixed(s.pre % beat < 0.01 ? 0 : 1) + ' beats · ' + s.pre.toFixed(2) + ' s</span>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-beats" data-what="pre" data-d="1">+</button></span></div>' +
      '<div class="studio-field"><span class="field-label">Length</span><span class="field-inline">' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-beats" data-what="duration" data-d="-1">−</button>' +
      '<span class="mono">' + (s.duration / beat).toFixed(s.duration % beat < 0.01 ? 0 : 1) + ' beats · ' + s.duration.toFixed(2) + ' s</span>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-beats" data-what="duration" data-d="1">+</button></span></div>' +
      '<div class="studio-field"><label class="field-label" for="studio-f-speed">Speed</label>' + studio_select_html('studio-f-speed', 'speed', s.speed) + '</div>' +
      '<div class="studio-field"><label class="field-label" for="studio-f-trans">Transition in</label>' +
      (i ? studio_select_html('studio-f-trans', 'transition', s.transition) +
        '<input type="range" id="studio-f-tlen" min="0.1" max="1" step="0.05" value="' + (s.tlen || 0.3) + '"' + (s.transition === 't01' ? ' disabled' : '') + ' aria-label="Transition length">'
         : '<span class="muted">The first shot opens the reel.</span>') + '</div>' +
      '<div class="studio-field"><span class="field-label">Kill effects</span>' + studio_checks_html('fx', 'kill', s.fx) +
      '<span class="field-inline"><button type="button" class="btn btn-ghost btn-sm" data-act="studio-fx-all">Use these on every shot</button>' +
      (i ? '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-tr-all">Use this transition on every cut</button>' : '') +
      '</span></div>' +
      '<div class="studio-field"><label class="studio-check"><input type="checkbox" id="studio-f-hero"' + (s.hero ? ' checked' : '') + '> Hero moment</label>' +
      (s.hero ? studio_checks_html('hero_fx', 'hero', s.hero_fx) +
        '<label class="field-label" for="studio-f-caption">Caption</label><input class="input" id="studio-f-caption" maxlength="40" value="' + esc(s.caption) + '">' : '') + '</div>' +
      '<div class="studio-field"><label class="field-label" for="studio-f-camera">Camera</label>' + studio_select_html('studio-f-camera', 'camera', s.camera) + '</div>' +
      '</div>';
    return;
  }
  const styles = (studio.catalog ? studio.catalog.styles : []);
  const pools = p.pools || {};
  box.innerHTML = tabs + '<div class="card-body studio-insp-body">' +
    '<p class="studio-tip">To change one shot\'s kill effects, speed or transition, click that shot on the timeline.</p>' +
    '<div class="studio-field"><span class="field-label">Effects every shot draws from</span>' +
    '<p class="muted studio-small">Each kill gets its own mix from these, never the same as the shot before.</p>' +
    '<span class="field-label">Kill effects</span>' + studio_pool_html('kill', pools.kill || []) +
    '<span class="field-label">Transitions</span>' + studio_pool_html('transition', pools.transition || []) +
    '<span class="field-inline">' +
    '<button type="button" class="btn btn-sm" data-act="studio-mix" data-what="kill">Mix kill effects</button>' +
    '<button type="button" class="btn btn-sm" data-act="studio-mix" data-what="transition">Mix transitions</button>' +
    '<button type="button" class="btn btn-sm" data-act="studio-mix" data-what="all">Mix everything</button></span></div>' +
    '<div class="studio-field"><label class="field-label" for="studio-r-style">Style</label>' +
    '<select class="select" id="studio-r-style">' + styles.map(s => '<option value="' + esc(s.key) + '"' + (s.key === p.style ? ' selected' : '') + '>' + esc(s.label) + '</option>').join('') + '</select>' +
    '<button type="button" class="btn btn-sm" data-act="studio-restyle" id="studio-restyle-btn"' + (studio.busy ? ' disabled' : '') + '>Rebuild with this style</button>' +
    '<span class="muted studio-small">Replans every shot. Undo brings your edits back.</span></div>' +
    '<div class="studio-field"><label class="field-label" for="studio-r-grade">Colour</label>' + studio_select_html('studio-r-grade', 'grade', p.grade) +
    '<label class="studio-check"><input type="checkbox" id="studio-r-vignette"' + (p.vignette ? ' checked' : '') + '> Soft vignette</label></div>' +
    '<div class="studio-field"><label class="field-label" for="studio-r-intro">Intro</label>' + studio_select_html('studio-r-intro', 'intro', p.intro) + '</div>' +
    '<div class="studio-field"><label class="field-label" for="studio-r-outro">Outro</label>' + studio_select_html('studio-r-outro', 'outro', p.outro) + '</div>' +
    '<div class="studio-field"><span class="field-label">Overlays</span>' + studio_checks_html('overlays', 'overlay', p.overlays) +
    '<label class="field-label" for="studio-r-handle">Handle</label><input class="input" id="studio-r-handle" maxlength="40" placeholder="@yourhandle" value="' + esc(p.handle) + '"></div>' +
    '<div class="studio-field"><span class="field-label">Song</span>' +
    '<span class="muted truncate">' + (p.song ? esc(p.song.split(/[\\/]/).pop()) : 'No song') + '</span>' +
    '<button type="button" class="btn btn-sm" data-act="studio-edit-song">' + (p.song ? 'Edit the song and mark kills…' : 'Add a song…') + '</button>' +
    (p.song ? '<span class="field-inline"><button type="button" class="btn btn-ghost btn-sm" data-act="studio-offset" data-d="-4">−1 bar</button>' +
      '<span class="mono">starts at ' + studio_secs(p.song_offset) + '</span>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-offset" data-d="4">+1 bar</button></span>' : '') +
    '<label class="field-label" for="studio-r-music">Music ' + p.music_db.toFixed(0) + ' dB</label>' +
    '<input type="range" id="studio-r-music" min="-20" max="6" step="1" value="' + p.music_db + '"' + (p.song ? '' : ' disabled') + '>' +
    '<label class="field-label" for="studio-r-game">Game sound ' + p.game_db.toFixed(0) + ' dB</label>' +
    '<input type="range" id="studio-r-game" min="-20" max="12" step="1" value="' + p.game_db + '">' +
    '<label class="studio-check"><input type="checkbox" id="studio-r-duck"' + (p.duck ? ' checked' : '') + '> Duck the music under gunfire</label></div>' +
    '<div class="studio-field"><span class="field-label">Format</span><div class="seg">' +
    '<button type="button" class="seg-btn' + (p.format === 'landscape' ? ' is-active' : '') + '" data-act="studio-rfmt" data-fmt="landscape">16:9</button>' +
    '<button type="button" class="seg-btn' + (p.format === 'vertical' ? ' is-active' : '') + '" data-act="studio-rfmt" data-fmt="vertical">9:16</button></div></div>' +
    '</div>';
}

function studio_inspectorInput(e) {
  const t = e.target;
  if (!t || !studio.project || !t.closest || !t.closest('#studio-insp')) return;
  const i = studio.sel, p = studio.project;
  const s = i >= 0 ? p.shots[i] : null;
  const pool = t.getAttribute('data-pool');
  if (pool) {
    const vals = Array.prototype.slice.call(studio_el('studio-insp').querySelectorAll('input[data-pool="' + pool + '"]:checked')).map(x => x.value);
    if (!vals.length) { t.checked = true; toast('Keep at least one to choose from.', 'warn'); return; }
    studio_change(pr => { pr.pools = Object.assign({}, pr.pools || {}); pr.pools[pool] = vals; });
    studio_mix(pool, false);
    return;
  }
  const list = t.getAttribute('data-list');
  if (list) {
    const vals = Array.prototype.slice.call(studio_el('studio-insp').querySelectorAll('input[data-list="' + list + '"]:checked')).map(x => x.value);
    studio_change(pr => { if (list === 'overlays') pr.overlays = vals; else pr.shots[i][list] = vals; });
    return;
  }
  const map = {
    'studio-f-kill': () => studio_change(pr => { pr.shots[i].kill = Number(t.value); }),
    'studio-f-speed': () => studio_change(pr => { pr.shots[i].speed = t.value; }),
    'studio-f-trans': () => studio_change(pr => { pr.shots[i].transition = t.value; pr.shots[i].tlen = 0; }),
    'studio-f-tlen': () => studio_change(pr => { pr.shots[i].tlen = Number(t.value); }),
    'studio-f-hero': () => studio_change(pr => { const sh = pr.shots[i]; sh.hero = t.checked; if (t.checked && !sh.hero_fx.length) sh.hero_fx = ['h01']; }),
    'studio-f-caption': () => studio_change(pr => { pr.shots[i].caption = t.value; }),
    'studio-f-camera': () => studio_change(pr => { pr.shots[i].camera = t.value; }),
    'studio-r-grade': () => studio_change(pr => { pr.grade = t.value; }),
    'studio-r-vignette': () => studio_change(pr => { pr.vignette = t.checked; }),
    'studio-r-intro': () => studio_change(pr => { pr.intro = t.value; }),
    'studio-r-outro': () => studio_change(pr => { pr.outro = t.value; }),
    'studio-r-handle': () => studio_change(pr => { pr.handle = t.value; }),
    'studio-r-music': () => studio_change(pr => { pr.music_db = Number(t.value); }),
    'studio-r-game': () => studio_change(pr => { pr.game_db = Number(t.value); }),
    'studio-r-duck': () => studio_change(pr => { pr.duck = t.checked; })
  };
  if (s === null && t.id && t.id.indexOf('studio-f-') === 0) return;
  if (map[t.id]) map[t.id]();
}

/* ------------------------------------------------------------ dragging */

function studio_pointerDown(e) {
  const tl = studio_el('studio-tracks');
  if (!studio.project || !tl || !tl.contains(e.target) || e.button !== 0) return;
  const trim = e.target.closest('[data-trim]'), kill = e.target.closest('[data-kill]');
  const shot = e.target.closest('.st-shot');
  if (!trim && !kill && !shot) return;
  const i = Number((trim || kill || shot).getAttribute(trim ? 'data-trim' : kill ? 'data-kill' : 'data-shot'));
  const s = studio.project.shots[i];
  studio.drag = {kind: trim ? 'trim' : kill ? 'kill' : 'move', i: i, x0: e.clientX, moved: false,
                 dur: s.duration, pre: s.pre, snapshot: JSON.stringify(studio.project), pointer: e.pointerId};
  /* Captured on the timeline itself, which survives the redraws a drag does. */
  try { tl.setPointerCapture(e.pointerId); } catch (err) { /* no capture, still works with a mouse */ }
  e.preventDefault();
}

function studio_pointerMove(e) {
  const g = studio.drag;
  if (!g || (g.pointer !== undefined && e.pointerId !== g.pointer)) return;
  const dx = e.clientX - g.x0;
  if (!g.moved && Math.abs(dx) < 4) return;
  g.moved = true;
  const p = studio.project, s = p.shots[g.i], dt = dx / studio.pps, beat = p.beat || 0.5;
  if (g.kind === 'trim') {
    s.duration = Math.max(beat, studio_snapTo(g.dur + dt));
    s.pre = Math.min(s.pre, s.duration);
  } else if (g.kind === 'kill') {
    s.pre = Math.max(0, Math.min(s.duration, studio_snapTo(g.pre + dt)));
  } else {
    const d = studio.derived, last = d.shots.length - 1;
    const mid = d.shots[g.i].start + (d.shots[g.i].end - d.shots[g.i].start) / 2 + dt;
    /* Past either end is "first" or "last", not "nowhere". */
    let to = mid < 0 ? 0 : mid >= d.shots[last].end ? last : g.i;
    d.shots.forEach((r, k) => { if (mid >= r.start && mid < r.end) to = k; });
    if (to !== g.i) {
      const before = d.shots[g.i].start;
      const [moved] = p.shots.splice(g.i, 1);
      p.shots.splice(to, 0, moved);
      g.i = to; studio.sel = to;
      /* Where the moved shot now starts, from the new order -- not where the
         shot it swapped with used to start, which differs by their lengths. */
      studio_localDerive();
      g.x0 += (studio.derived.shots[to].start - before) * studio.pps;
    }
  }
  studio_localDerive();
  studio_drawTimeline();
}

function studio_pointerUp(e) {
  const g = studio.drag;
  if (!g || (e && g.pointer !== undefined && e.pointerId !== g.pointer)) return;
  studio.drag = null;
  if (e && e.type === 'pointercancel') {
    /* The browser took the gesture (a touch pan): put the shot back. */
    if (g.moved) { studio.project = JSON.parse(g.snapshot); studio_localDerive(); studio_drawAll(); }
    return;
  }
  if (!g.moved) { studio_select(g.i); return; }
  studio.gen++;
  studio_pushUndo(g.snapshot);
  studio.dirty = true;
  studio.sel = g.i;
  studio_drawAll();
  studio_check();
}

/* ------------------------------------------------------------ opening */

async function studio_open(path) {
  const r = await API.get('/api/studio/project?path=' + encodeURIComponent(path));
  if (!r || !r.ok) { toast((r && r.error) || 'Could not open that reel.', 'warn'); return; }
  studio.undo = []; studio.sel = -1;
  studio_setProject(r.project, r.derived, r.notes, r.song);
  studio.output = r.project.output; studio.dirty = false; studio.renderedAt = r.when || Date.now();
  studio_tab('timeline');
  studio_fit();
  studio_drawAll();
  studio_loadVideo();
}

function studio_tab(which) {
  ['clips', 'timeline', 'song'].forEach(k => {
    studio_show('studio-pane-' + k, k === which);
    const b = studio_el('studio-tab-' + k);
    b.classList.toggle('is-active', k === which);
    b.setAttribute('aria-selected', String(k === which));
  });
  const a = studio_el('studio-sg-audio');
  if (which !== 'song' && a && !a.paused) a.pause();
  if (which === 'timeline') { studio_fit(); studio_drawAll(); }
  if (which === 'song') studio_sgOpen();
}

/* ------------------------------------------------------------ wiring */

function studio_wire() {
  if (studio.wired) return;
  studio.wired = true;
  document.addEventListener('click', e => {
    const b = e.target.closest ? e.target.closest('[data-act^="studio-"]') : null;
    if (!b || !b.closest('#view-studio')) return;
    const act = b.getAttribute('data-act');
    const p = studio.project;
    if (act === 'studio-tab') studio_tab(b.getAttribute('data-tab'));
    else if (act === 'studio-edit-song') studio_tab('song');
    else if (act === 'studio-refresh') studio_load(true);
    else if (act === 'studio-game') { studio.game = b.getAttribute('data-game'); studio_renderLib(); }
    else if (act === 'studio-pick') studio_pick(b.getAttribute('data-clip'), e.shiftKey);
    else if (act === 'studio-folder') studio_folderToggle(b.getAttribute('data-folder'));
    else if (act === 'studio-preview') studio_preview(b.getAttribute('data-clip'));
    else if (act === 'studio-preview-close' || act === 'studio-make-cancel') studio_closeModals();
    else if (act === 'studio-clear') { studio.selected = []; studio_syncSelection(); }
    else if (act === 'studio-make') studio_openMake();
    else if (act === 'studio-style') { studio.style = b.getAttribute('data-style'); studio_renderStyles(); }
    else if (act === 'studio-song') studio_pickSong();
    else if (act === 'studio-nosong') {
      studio.song = ''; studio.songShape = null;
      studio_el('studio-song-name').textContent = 'No song: the clips keep their own sound, cut to a 120 BPM grid.';
    }
    else if (act === 'studio-fmt' || act === 'studio-order') {
      const key = act === 'studio-fmt' ? 'fmt' : 'order';
      studio[key] = b.getAttribute('data-' + key);
      b.parentElement.querySelectorAll('.seg-btn').forEach(x => x.classList.toggle('is-active', x === b));
    }
    else if (act === 'studio-build') studio_build();
    else if (act === 'studio-open') studio_open(b.getAttribute('data-path'));
    else if (act === 'studio-watch') {
      studio_el('studio-preview-title').textContent = b.closest('.studio-reel').querySelector('.studio-reel-name').textContent;
      const v = studio_el('studio-preview-video');
      v.src = studio_media('/api/clips/video', b.getAttribute('data-path'));
      studio_show('studio-preview-scrim', true);
      v.play().catch(() => {});
    }
    else if (act === 'studio-render') studio_render();
    else if (act === 'studio-cancel') API.post('/api/studio/cancel', {}).then(studio_poll);
    else if (act === 'studio-undo') studio_undo();
    else if (act === 'studio-show') { if (studio.output && typeof clip_reveal === 'function') clip_reveal(studio.output); }
    else if (act === 'studio-play') {
      const v = studio_el('studio-video');
      if (v.src) { if (v.paused) v.play().catch(() => {}); else v.pause(); }
    }
    else if (act === 'studio-zoom') {
      const z = Number(b.getAttribute('data-z'));
      if (z === 0) studio_fit(); else studio.pps = Math.max(8, Math.min(400, studio.pps * (z > 0 ? 1.5 : 1 / 1.5)));
      studio_drawTimeline();
    }
    else if (act === 'studio-seek') {
      const v = studio_el('studio-video');
      const box = b.getBoundingClientRect();
      if (v.src) v.currentTime = Math.max(0, (e.clientX - box.left) / studio.pps);
      studio_playhead();
    }
    else if (act === 'studio-select') studio_select(Number(b.getAttribute('data-shot')));
    else if (act === 'studio-move' && p) {
      const d = Number(b.getAttribute('data-d')), i = studio.sel, j = i + d;
      if (j < 0 || j >= p.shots.length) return;
      studio_change(pr => { const t = pr.shots[i]; pr.shots[i] = pr.shots[j]; pr.shots[j] = t; });
      studio.sel = j; studio_drawAll();
    }
    else if (act === 'studio-remove' && p) {
      if (p.shots.length <= 1) { toast('A reel needs at least one shot.', 'warn'); return; }
      const i = studio.sel;
      studio_change(pr => { pr.shots.splice(i, 1); });
      studio.sel = Math.min(i, p.shots.length - 1); studio_drawAll();
    }
    else if (act === 'studio-slip' && p) {
      const d = Number(b.getAttribute('data-d'));
      studio_change(pr => { const s = pr.shots[studio.sel]; s.kill = Math.max(0, Math.min(s.clip_seconds, s.kill + d)); });
    }
    else if (act === 'studio-beats' && p) {
      const what = b.getAttribute('data-what'), d = Number(b.getAttribute('data-d')), beat = p.beat || 0.5;
      studio_change(pr => {
        const s = pr.shots[studio.sel];
        if (what === 'pre') s.pre = Math.max(0, Math.min(s.duration, s.pre + d * beat));
        else { s.duration = Math.max(beat, s.duration + d * beat); s.pre = Math.min(s.pre, s.duration); }
      });
    }
    else if (act === 'studio-offset' && p) {
      const d = Number(b.getAttribute('data-d')), beat = p.beat || 0.5;
      studio_change(pr => { pr.song_offset = Math.max(0, pr.song_offset + d * beat); });
    }
    else if (act === 'studio-rfmt' && p) studio_change(pr => { pr.format = b.getAttribute('data-fmt'); });
    else if (act === 'studio-restyle' && p) studio_restyle();
    else if (act === 'studio-mix' && p) studio_mix(b.getAttribute('data-what'), true);
    else if (act === 'studio-fx-all' && p && studio.sel >= 0) {
      const fx = p.shots[studio.sel].fx.slice();
      studio_change(pr => { pr.shots.forEach(s => { s.fx = fx.slice(); }); });
      toast('Every shot now uses ' + (fx.length ? fx.map(id => studio_part(id).label).join(' + ') : 'no kill effect') + '.', 'ok');
    }
    else if (act === 'studio-tr-all' && p && studio.sel > 0) {
      const t = p.shots[studio.sel].transition, len = p.shots[studio.sel].tlen;
      studio_change(pr => { pr.shots.forEach((s, k) => { if (k) { s.transition = t; s.tlen = len; } }); });
      toast('Every cut is now ' + studio_part(t).label + '.', 'ok');
    }
    else if (act === 'studio-sg-pick') studio_sgPick();
    else if (act === 'studio-sg-none') studio_sgApply(true);
    else if (act === 'studio-sg-play') studio_sgPlay();
    else if (act === 'studio-sg-mark') studio_sgMark();
    else if (act === 'studio-sg-unmark') { studio.sg.marks.pop(); studio_sgDraw(); }
    else if (act === 'studio-sg-clearmarks') { studio.sg.marks = []; studio_sgDraw(); }
    else if (act === 'studio-sg-nudge') studio_sgNudge(b.getAttribute('data-what'), b.getAttribute('data-d'));
    else if (act === 'studio-sg-snapbar') studio_sgSnapBar();
    else if (act === 'studio-sg-atdrop') studio_sgAtDrop();
    else if (act === 'studio-sg-fit') studio_sgFit();
    else if (act === 'studio-sg-apply') studio_sgApply(false);
  });
  document.addEventListener('change', studio_inspectorInput);
  const q = studio_el('studio-q');
  if (q) q.addEventListener('input', () => { studio.q = q.value; studio_renderLib(); });
  const pn = studio_el('studio-pname');
  if (pn) pn.addEventListener('change', () => { if (studio.project) studio_change(pr => { pr.name = pn.value.trim() || pr.name; }); });
  document.addEventListener('pointerdown', studio_pointerDown);
  document.addEventListener('pointermove', studio_pointerMove);
  document.addEventListener('pointerup', studio_pointerUp);
  document.addEventListener('pointercancel', studio_pointerUp);
  const v = studio_el('studio-video');
  if (v) {
    ['timeupdate', 'seeked', 'loadedmetadata'].forEach(ev => v.addEventListener(ev, studio_playhead));
    v.addEventListener('play', function tick() {
      studio_playhead();
      studio_el('studio-play-btn').textContent = 'Pause';
      if (!v.paused) requestAnimationFrame(tick);
    });
    v.addEventListener('pause', () => { studio_el('studio-play-btn').textContent = 'Play'; });
  }
  ['studio-make-scrim', 'studio-preview-scrim'].forEach(id => {
    const sc = studio_el(id);
    if (sc) sc.addEventListener('click', e => { if (e.target === sc) studio_closeModals(); });
  });
  document.addEventListener('keydown', e => {
    if (shell_page !== 'studio') return;
    if (e.key === 'Escape') { studio_closeModals(); return; }
    const tag = (e.target.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    /* A focused button owns Space and Backspace: Space presses it. */
    const onButton = tag === 'BUTTON' || (e.target.closest && e.target.closest('button,[role="tab"],a'));
    const song = !studio_el('studio-pane-song').classList.contains('hide');
    if (song && studio.sg.shape) {
      if ((e.key || '').toLowerCase() === 'k') { e.preventDefault(); studio_sgMark(); }
      else if (e.key === ' ' && !onButton) { e.preventDefault(); studio_sgPlay(); }
      return;
    }
    if (onButton && (e.key === ' ' || e.key === 'Backspace' || e.key === 'Enter')) return;
    const tl = !studio_el('studio-pane-timeline').classList.contains('hide');
    if (!tl || !studio.project) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); studio_undo(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); studio_select(Math.min(studio.project.shots.length - 1, studio.sel + 1)); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); studio_select(Math.max(0, studio.sel - 1)); }
    else if (e.key === ' ') { e.preventDefault(); const vv = studio_el('studio-video'); if (vv.src) { if (vv.paused) vv.play().catch(() => {}); else vv.pause(); } }
    else if ((e.key === 'Delete' || e.key === 'Backspace') && studio.sel >= 0 && studio.project.shots.length > 1) {
      e.preventDefault();
      const i = studio.sel;
      studio_change(pr => { pr.shots.splice(i, 1); });
      studio.sel = Math.min(i, studio.project.shots.length - 1); studio_drawAll();
    }
  });
  window.addEventListener('resize', () => { if (studio.project && shell_page === 'studio') studio_drawTimeline(); });
}

async function studio_restyle() {
  const p = studio.project, sel = studio_el('studio-r-style');
  if (!p || !sel || studio.busy) return;
  const key = sel.value;
  const label = (sel.options[sel.selectedIndex] || {}).text || key;
  studio.busy = true;
  const btn = studio_el('studio-restyle-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Rebuilding…'; }
  try {
    const snapshot = JSON.stringify(p);
    const r = await API.post('/api/studio/plan', {clips: p.shots.map(s => s.clip), style: key,
      song: p.song, format: p.format, name: p.name});
    if (!r || !r.ok) { toast((r && r.error) || 'Could not rebuild with that style.', 'warn'); return; }
    studio_pushUndo(snapshot);
    studio.gen++;
    r.project.output = p.output;
    studio.sel = -1; studio.dirty = true;
    studio_setProject(r.project, r.derived, r.notes, r.song);
    studio_fit(); studio_drawAll();
    toast('Rebuilt as ' + label + ' — ' + r.project.shots.length + ' shots. Render to see it.', 'ok');
  } finally {
    studio.busy = false;
    studio_drawInspector();
  }
}

async function studio_mix(what, announce) {
  const p = studio.project;
  if (!p) return;
  const gen = ++studio.gen;
  const snapshot = JSON.stringify(p);
  const r = await API.post('/api/studio/vary', {project: p, what: what});
  if (gen !== studio.gen) return;
  if (!r || !r.ok) { toast((r && r.error) || 'Could not mix the effects.', 'warn'); return; }
  if (announce) studio_pushUndo(snapshot);
  studio.project = r.project; studio.derived = r.derived; studio.notes = r.notes || [];
  studio.dirty = true;
  studio_drawAll();
  if (announce) toast(what === 'all' ? 'Everything mixed again.' : what === 'kill' ? 'Kill effects mixed again.' : 'Transitions mixed again.', 'ok');
}

/* ------------------------------------------------------------ the song */

function studio_sgOpen() {
  const p = studio.project, sg = studio.sg;
  if (!p) return;
  if (p.song && (!sg.shape || sg.song !== p.song)) {
    sg.song = p.song;
    sg.shape = studio.songShape && studio.songShape.beats ? studio.songShape : null;
    if (!sg.shape) {
      API.post('/api/reel/song', {song: p.song}).then(got => {
        if (got && got.ok) { sg.shape = got.song; studio.songShape = got.song; studio_sgReset(); }
      });
    }
  }
  if (!p.song) { sg.song = ''; sg.shape = null; }
  studio_sgReset();
}

function studio_sgReset() {
  const p = studio.project, sg = studio.sg, sh = sg.shape;
  studio_show('studio-sg-body', !!sh);
  studio_el('studio-sg-name').textContent = sg.song ? sg.song.split(/[\\/]/).pop() : 'No song';
  studio_el('studio-sg-facts').textContent = sh
    ? Math.round(sh.bpm) + ' BPM · ' + studio_dur(sh.seconds) + (sh.drop ? ' · drop at ' + studio_secs(sh.drop) : '') +
      (sh.drums_in ? ' · drums in at ' + studio_secs(sh.drums_in) : '')
    : 'Choose a song to cut the reel to. Without one the clips keep their own sound on a 120 BPM grid.';
  if (!sh) return;
  const len = (studio.derived && studio.derived.length) || 30;
  if (sg.song === p.song && !sg.touched) {
    sg.start = p.song_offset || 0;
    sg.end = Math.min(sh.seconds, sg.start + len);
  }
  studio_el('studio-sg-atdrop').disabled = !sh.drop;
  const a = studio_el('studio-sg-audio');
  const want = studio_media('/api/reel/audio', sg.song);
  if (a.getAttribute('data-song') !== sg.song) { a.src = want; a.setAttribute('data-song', sg.song); }
  studio_sgDraw();
}

function studio_sgBeat() {
  const sh = studio.sg.shape;
  return sh ? sh.beat || (60 / sh.bpm) : 0.5;
}

function studio_sgNearestBeat(t) {
  const b = (studio.sg.shape && studio.sg.shape.beats) || [];
  let best = t, d = 1e9;
  for (let i = 0; i < b.length; i++) { const x = Math.abs(b[i] - t); if (x < d) { d = x; best = b[i]; } }
  return best;
}

function studio_sgNudge(what, how) {
  const sg = studio.sg, sh = sg.shape;
  if (!sh) return;
  const beat = studio_sgBeat();
  const step = {bar: 4 * beat, '-bar': -4 * beat, beat: beat, '-beat': -beat, ms: 0.01, '-ms': -0.01}[how] || 0;
  sg.touched = true;
  if (what === 'start') {
    const len = sg.end - sg.start;
    sg.start = Math.max(0, Math.min(sh.seconds - 1, sg.start + step));
    sg.end = Math.min(sh.seconds, sg.start + len);
  } else {
    sg.end = Math.max(sg.start + beat, Math.min(sh.seconds, sg.end + step));
  }
  studio_sgDraw();
}

function studio_sgSnapBar() {
  const sg = studio.sg, sh = sg.shape;
  if (!sh || !sh.beats || !sh.beats.length) return;
  const bars = sh.beats.filter((b, i) => (i % 4) === (sh.downbeat_pos || 0));
  let best = sg.start, d = 1e9;
  bars.forEach(b => { const x = Math.abs(b - sg.start); if (x < d) { d = x; best = b; } });
  const len = sg.end - sg.start;
  sg.touched = true; sg.start = best; sg.end = Math.min(sh.seconds, best + len);
  studio_sgDraw();
}

function studio_sgAtDrop() {
  const sg = studio.sg, sh = sg.shape;
  if (!sh || !sh.drop) return;
  const len = sg.end - sg.start;
  const lead = Math.min(8 * 4 * studio_sgBeat(), sh.drop, Math.max(4 * studio_sgBeat(), len / 3));
  sg.touched = true;
  sg.start = Math.max(0, studio_sgNearestBeat(sh.drop - lead));
  sg.end = Math.min(sh.seconds, sg.start + len);
  studio_sgDraw();
}

function studio_sgFit() {
  const sg = studio.sg, sh = sg.shape, d = studio.derived;
  if (!sh || !d) return;
  sg.touched = true;
  sg.end = Math.min(sh.seconds, sg.start + d.length);
  studio_sgDraw();
}

function studio_sgPlay() {
  const a = studio_el('studio-sg-audio'), sg = studio.sg;
  if (!sg.shape || !a.src) return;
  if (a.paused) {
    if (a.currentTime < sg.start || a.currentTime >= sg.end) a.currentTime = sg.start;
    sg.ticked = {};
    a.play().catch(() => toast('The song could not be played.', 'warn'));
  } else {
    a.pause();
  }
}

function studio_sgMark() {
  const a = studio_el('studio-sg-audio'), sg = studio.sg;
  if (!sg.shape) return;
  let t = a.currentTime || sg.start;
  if (studio_el('studio-sg-snap').checked) t = studio_sgNearestBeat(t);
  if (t < sg.start - 0.01 || t > sg.end + 0.01) { toast('Marks go inside the part you are using.', 'warn'); return; }
  if (sg.marks.some(m => Math.abs(m - t) < 0.03)) return;
  sg.marks.push(t);
  sg.marks.sort((x, y) => x - y);
  studio_sgDraw();
}

function studio_sgClick() {
  try {
    const C = window.AudioContext || window.webkitAudioContext;
    if (!C) return;
    studio.sg.ac = studio.sg.ac || new C();
    const ac = studio.sg.ac, o = ac.createOscillator(), g = ac.createGain();
    o.frequency.value = 1800; g.gain.value = 0.15;
    o.connect(g); g.connect(ac.destination);
    o.start(); o.stop(ac.currentTime + 0.03);
  } catch (e) { /* no audio context, no click */ }
}

function studio_sgTick() {
  const a = studio_el('studio-sg-audio'), sg = studio.sg;
  if (!sg.shape) return;
  if (!a.paused && studio_el('studio-sg-loop').checked && a.currentTime >= sg.end) {
    a.currentTime = sg.start; sg.ticked = {};
  }
  if (!a.paused && studio_el('studio-sg-click').checked) {
    sg.marks.forEach((m, i) => {
      if (Math.abs(a.currentTime - m) < 0.05 && !sg.ticked[i]) { sg.ticked[i] = 1; studio_sgClick(); }
    });
  }
  studio_el('studio-sg-clock').textContent = studio_secs(a.currentTime || 0);
  studio_sgDrawWaves();
  if (!a.paused) requestAnimationFrame(studio_sgTick);
}

function studio_sgDraw() {
  const sg = studio.sg, sh = sg.shape, d = studio.derived, p = studio.project;
  if (!sh) return;
  studio_el('studio-sg-start').textContent = studio_secs(sg.start);
  studio_el('studio-sg-end').textContent = studio_secs(sg.end);
  studio_el('studio-sg-range').textContent = 'Using ' + studio_secs(sg.start) + ' → ' + studio_secs(sg.end) +
    ' (' + studio_dur(sg.end - sg.start) + ')';
  const len = d ? d.length : 0, part = sg.end - sg.start;
  studio_el('studio-sg-fitnote').textContent = len > part + 0.05
    ? 'The timeline is ' + studio_dur(len) + '; shots past ' + studio_dur(part) + ' will be left out. "Fit the timeline" keeps them all.'
    : 'The whole timeline fits in this part.';
  studio_el('studio-sg-chips').innerHTML = sg.marks.map((m, i) =>
    '<span class="reel-chip" data-sgmark="' + i + '" title="click to remove">' + (i + 1) + ' · ' + studio_secs(m) + '</span>').join('');
  const shots = p ? p.shots.length : 0;
  studio_el('studio-sg-marksinfo').textContent = sg.marks.length
    ? sg.marks.length + ' marks for ' + shots + ' shots' + (sg.marks.length < shots ? ' — the rest keep their spacing after the last mark.' : sg.marks.length > shots ? ' — the extra marks will not be used.' : '.')
    : 'No marks: the shots keep the lengths they have, starting from here.';
  studio_el('studio-sg-apply').textContent = sg.marks.length ? 'Use this part and these marks' : 'Use this part';
  studio_sgDrawWaves();
}

function studio_sgCanvas(id, H) {
  const cv = studio_el(id);
  if (!cv) return null;
  const dpr = window.devicePixelRatio || 1, W = Math.max(200, cv.clientWidth);
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {cv: cv, ctx: ctx, W: W, H: H};
}

function studio_sgDrawWaves() {
  const sg = studio.sg, sh = sg.shape;
  if (!sh || !sh.peaks) return;
  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue('--accent').trim() || '#5aa9ff';
  const warn = css.getPropertyValue('--warn').trim() || '#e3b341';
  const faint = css.getPropertyValue('--border-strong').trim() || '#555';
  const a = studio_el('studio-sg-audio');
  const now = a ? a.currentTime || 0 : 0;
  const n = sh.peaks.length, per = sh.seconds / n;

  /* the whole song */
  const o = studio_sgCanvas('studio-sg-overview', 90);
  if (o) {
    const {ctx, W, H} = o, X = t => t / sh.seconds * W, mid = H / 2;
    ctx.fillStyle = accent;
    ctx.globalAlpha = 0.35;
    for (let x = 0; x < W; x++) {
      const k = Math.min(n - 1, Math.floor(x / W * n));
      const amp = sh.peaks[k] * (mid - 2);
      ctx.globalAlpha = (x >= X(sg.start) && x <= X(sg.end)) ? 1 : 0.3;
      ctx.fillRect(x, mid - amp, 1, amp * 2);
    }
    ctx.globalAlpha = 0.18; ctx.fillStyle = accent;
    ctx.fillRect(X(sg.start), 0, X(sg.end) - X(sg.start), H);
    ctx.globalAlpha = 1;
    ctx.fillStyle = accent;
    ctx.fillRect(X(sg.start) - 2, 0, 4, H); ctx.fillRect(X(sg.end) - 2, 0, 4, H);
    if (sh.drop) { ctx.fillStyle = warn; ctx.fillRect(X(sh.drop) - 1, 0, 2, H); }
    ctx.fillStyle = '#ff5c5c'; ctx.fillRect(X(now) - 1, 0, 2, H);
    o.cv.title = 'Drag the highlighted part to move it, or its edges to resize it';
  }

  /* the part, magnified */
  const dt = studio_sgCanvas('studio-sg-detail', 130);
  if (dt) {
    const {ctx, W, H} = dt;
    const pad = Math.max(0.5, (sg.end - sg.start) * 0.04);
    const t0 = Math.max(0, sg.start - pad), t1 = Math.min(sh.seconds, sg.end + pad);
    const X = t => (t - t0) / (t1 - t0) * W, mid = H / 2;
    ctx.fillStyle = accent;
    for (let x = 0; x < W; x += 2) {
      const t = t0 + x / W * (t1 - t0), k = Math.min(n - 1, Math.floor(t / per));
      const amp = sh.peaks[k] * (mid - 14);
      ctx.globalAlpha = (t >= sg.start && t <= sg.end) ? 0.9 : 0.25;
      ctx.fillRect(x, mid - amp, 1.5, amp * 2);
    }
    ctx.globalAlpha = 1;
    (sh.beats || []).forEach((b, i) => {
      if (b < t0 || b > t1) return;
      const bar = (i % 4) === (sh.downbeat_pos || 0);
      ctx.fillStyle = faint;
      ctx.globalAlpha = bar ? 0.9 : 0.35;
      ctx.fillRect(X(b), bar ? 0 : H - 12, 1, bar ? H : 12);
    });
    ctx.globalAlpha = 1;
    ctx.fillStyle = accent;
    ctx.fillRect(X(sg.start) - 1, 0, 3, H); ctx.fillRect(X(sg.end) - 1, 0, 3, H);
    if (sh.drop && sh.drop >= t0 && sh.drop <= t1) {
      ctx.fillStyle = warn; ctx.fillRect(X(sh.drop) - 1, 0, 2, H);
      ctx.font = '11px sans-serif'; ctx.fillText('drop', X(sh.drop) + 4, 12);
    }
    sg.marks.forEach((m, i) => {
      const x = X(m);
      ctx.save(); ctx.translate(x, H - 20); ctx.rotate(Math.PI / 4);
      ctx.fillStyle = '#fff'; ctx.fillRect(-6, -6, 12, 12);
      ctx.strokeStyle = accent; ctx.lineWidth = 2; ctx.strokeRect(-6, -6, 12, 12);
      ctx.restore();
      ctx.fillStyle = css.getPropertyValue('--text-primary').trim() || '#fff';
      ctx.font = '11px sans-serif'; ctx.fillText(String(i + 1), x + 8, H - 26);
    });
    ctx.fillStyle = '#ff5c5c'; ctx.fillRect(X(now) - 1, 0, 2, H);
    dt.cv.setAttribute('data-t0', t0); dt.cv.setAttribute('data-t1', t1);
  }
}

function studio_sgPointer(e) {
  const sg = studio.sg, sh = sg.shape;
  if (!sh) return;
  const ov = studio_el('studio-sg-overview'), de = studio_el('studio-sg-detail');
  const a = studio_el('studio-sg-audio');
  if (e.type === 'pointerdown' && e.target === de) {
    const r = de.getBoundingClientRect();
    const t0 = Number(de.getAttribute('data-t0')), t1 = Number(de.getAttribute('data-t1'));
    a.currentTime = Math.max(0, t0 + (e.clientX - r.left) / r.width * (t1 - t0));
    studio_sgDrawWaves();
    studio_el('studio-sg-clock').textContent = studio_secs(a.currentTime);
    return;
  }
  if (e.type === 'pointerdown' && e.target === ov) {
    const r = ov.getBoundingClientRect();
    const t = (e.clientX - r.left) / r.width * sh.seconds;
    const edge = 6 / r.width * sh.seconds;
    const kind = Math.abs(t - sg.start) < edge ? 'start' : Math.abs(t - sg.end) < edge ? 'end'
      : (t > sg.start && t < sg.end) ? 'move' : 'jump';
    if (kind === 'jump') {
      const len = sg.end - sg.start;
      sg.touched = true;
      sg.start = Math.max(0, Math.min(sh.seconds - len, t - len / 2));
      sg.end = sg.start + len;
      studio_sgDraw();
      return;
    }
    sg.drag = {kind: kind, x0: e.clientX, start: sg.start, end: sg.end, w: r.width, pointer: e.pointerId};
    try { ov.setPointerCapture(e.pointerId); } catch (err) { /* fine without */ }
    e.preventDefault();
    return;
  }
  const g = sg.drag;
  if (!g || e.pointerId !== g.pointer) return;
  if (e.type === 'pointermove') {
    const dt = (e.clientX - g.x0) / g.w * sh.seconds;
    sg.touched = true;
    if (g.kind === 'start') sg.start = Math.max(0, Math.min(sg.end - 1, g.start + dt));
    else if (g.kind === 'end') sg.end = Math.max(sg.start + 1, Math.min(sh.seconds, g.end + dt));
    else {
      const len = g.end - g.start;
      sg.start = Math.max(0, Math.min(sh.seconds - len, g.start + dt));
      sg.end = sg.start + len;
    }
    studio_sgDraw();
  } else {
    sg.drag = null;
    /* Dragging lands the part on a beat; the 10 ms nudges are for leaving it. */
    const len = sg.end - sg.start;
    if (g.kind !== 'end') { sg.start = studio_sgNearestBeat(sg.start); if (g.kind === 'move') sg.end = Math.min(sh.seconds, sg.start + len); }
    if (g.kind === 'end') sg.end = studio_sgNearestBeat(sg.end);
    studio_sgDraw();
  }
}

async function studio_sgPick() {
  const r = await API.post('/api/clips/pick', {kind: 'audio'});
  if (!r || !r.path) return;
  studio_el('studio-sg-facts').textContent = 'Finding the beat in ' + r.path.split(/[\\/]/).pop() + '…';
  const got = await API.post('/api/reel/song', {song: r.path});
  if (!got || !got.ok) { studio_el('studio-sg-facts').textContent = (got && got.error) || 'Could not read that song.'; return; }
  const sg = studio.sg, sh = got.song, len = (studio.derived && studio.derived.length) || 30;
  sg.song = r.path; sg.shape = sh; sg.marks = []; sg.touched = true;
  const from = sh.drums_in || (sh.beats && sh.beats[0]) || 0;
  sg.start = studio_sgNearestBeat(Math.max(0, Math.min(from, sh.seconds - len)));
  sg.end = Math.min(sh.seconds, sg.start + len);
  studio_sgReset();
}

async function studio_sgApply(noSong) {
  const p = studio.project, sg = studio.sg;
  if (!p) return;
  const btn = studio_el('studio-sg-apply');
  btn.disabled = true;
  studio_el('studio-sg-msg').textContent = noSong ? 'Taking the song off…' : 'Fitting the timeline to the song…';
  try {
    const snapshot = JSON.stringify(p);
    const gen = ++studio.gen;
    const body = noSong ? {project: p, song: ''} :
      {project: p, song: sg.song, start: sg.start, end: sg.end, marks: sg.marks};
    const r = await API.post('/api/studio/song', body);
    if (gen !== studio.gen) return;
    if (!r || !r.ok) { studio_el('studio-sg-msg').textContent = (r && r.error) || 'Could not use that song.'; return; }
    studio_pushUndo(snapshot);
    r.project.output = p.output;
    studio.dirty = true;
    studio_setProject(r.project, r.derived, r.notes, r.song);
    if (noSong) { sg.song = ''; sg.shape = null; sg.marks = []; }
    sg.touched = false;
    studio_el('studio-sg-msg').textContent = '';
    toast(noSong ? 'The reel has no song now.' : sg.marks.length
      ? 'Kills moved onto your ' + Math.min(sg.marks.length, r.project.shots.length) + ' marks. Render to hear it.'
      : 'Song part set. Render to hear it.', 'ok');
    studio_tab('timeline');
  } finally {
    btn.disabled = false;
  }
}

function studio_sgWire() {
  const ov = studio_el('studio-sg-overview'), de = studio_el('studio-sg-detail');
  ['pointerdown', 'pointermove', 'pointerup', 'pointercancel'].forEach(ev => {
    if (ov) ov.addEventListener(ev, studio_sgPointer);
    if (de && ev === 'pointerdown') de.addEventListener(ev, studio_sgPointer);
  });
  const a = studio_el('studio-sg-audio');
  if (a) {
    a.addEventListener('play', () => { studio_el('studio-sg-play').textContent = 'Pause'; requestAnimationFrame(studio_sgTick); });
    a.addEventListener('pause', () => { studio_el('studio-sg-play').textContent = 'Play the part'; studio_sgDrawWaves(); });
    a.addEventListener('seeked', studio_sgDrawWaves);
  }
  document.addEventListener('click', e => {
    const c = e.target.closest ? e.target.closest('[data-sgmark]') : null;
    if (!c) return;
    studio.sg.marks.splice(Number(c.getAttribute('data-sgmark')), 1);
    studio_sgDraw();
  });
  window.addEventListener('resize', () => { if (shell_page === 'studio') studio_sgDrawWaves(); });
}

window.PAGE_STUDIO = {
  onShow: function () {
    if (!studio.wired) studio_sgWire();
    studio_wire();
    studio_load(false);
    studio_poll();
  },
  onTick: function () {}
};
"""

__all__ = ["STUDIO_HTML", "STUDIO_JS"]
