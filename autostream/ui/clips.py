r"""The Clips page: turn a finished stream into clips.

SHAPE OF THE PAGE
    A list of past streams on top, the options for the selected one below, and
    one primary button. Everything the run needs is visible at once, because
    the choices interact -- a thirty-second clip and a minimum of three kills
    behave very differently together than either does alone -- and hiding half
    of them behind a dialog would mean guessing at the result.

PROGRESS COMES FROM THE STATUS POLL
    A run takes minutes. Rather than invent a second polling loop, the job
    publishes into the payload the shell already fetches every two seconds and
    this page reads it in onTick. That means progress survives a reload and
    keeps working if the page is closed and reopened mid-run, neither of which
    a page-local timer would manage.

NAMING
    Everything top level is prefixed clip_, and the single unprefixed global is
    window.PAGE_CLIPS. All page files share one scope, so a duplicate top-level
    const is a SyntaxError that takes the whole UI down.
"""
from __future__ import annotations

from .icons import ICONS


def _svg(name: str, size: int = 16) -> str:
    body = ICONS.get(name, "")
    return (f'<svg class="icon" viewBox="0 0 24 24" width="{size}" height="{size}"'
            f' aria-hidden="true" focusable="false">{body}</svg>')


CLIPS_HTML: str = (
    """
<div class="clip-setup card hide" id="clip-setup">
  <div class="card-head"><h2 class="card-title">One thing missing</h2></div>
  <p class="card-sub" id="clip-setup-text"></p>
  <pre class="clip-pre mono" id="clip-setup-detail"></pre>
</div>

<div class="card" id="clip-local">
  <div class="card-head">
    <div>
      <h2 class="card-title">Clip a video file</h2>
      <p class="card-sub">Any recording you already have - AutoStream does not have
         to have made it. Pick the file, say which game it is, and the highlights
         come out the same way they do for a stream.</p>
    </div>
  </div>
  <div class="card-body">
    <div class="localclip">
      <button class="btn" type="button" data-act="pick-local">Choose video&hellip;</button>
      <div class="field">
        <label class="field-label" for="clip-local-game">Game</label>
        <select class="select" id="clip-local-game"></select>
      </div>
      <button class="btn btn-primary" type="button" data-act="use-local"
              id="clip-local-go" disabled>Use this video</button>
      <p class="localclip-path" id="clip-local-path"></p>
    </div>
  </div>
</div>

<div class="searchbar">
  <span class="overline">Streams</span>
  <select class="select" id="clip-game" aria-label="Filter by game">
    <option value="">All games</option>
  </select>
  <button class="btn btn-sm" type="button" id="clip-refresh">"""
    + _svg("refresh")
    + """<span>Refresh</span></button>
  <span class="muted" id="clip-count"></span>
</div>

<div class="panel" id="clip-listwrap">
  <div class="clip-list" id="clip-list"></div>
</div>

<div class="empty hide" id="clip-empty">"""
    + _svg("film", 20)
    + """<p>No finished streams yet.</p>
  <p class="muted">Turn on <strong>Record while streaming</strong> in Settings, then
     stream once. When it ends, the recording shows up here.</p>
</div>

<div class="card hide" id="clip-options">
  <div class="card-head">
    <div>
      <h2 class="card-title" id="clip-chosen">&nbsp;</h2>
      <p class="card-sub" id="clip-chosen-sub">&nbsp;</p>
    </div>
    <button class="btn btn-ghost btn-sm" type="button" data-act="reveal-src">"""
    + _svg("folder")
    + """<span>Show file</span></button>
  </div>

  <div class="panel clip-warn hide" id="clip-wrongwrap">
    <p class="muted" id="clip-wrongtext"></p>
    <div class="field-inline">
      <select class="select" id="clip-gamefix" aria-label="Correct the game"></select>
      <button class="btn btn-sm" type="button" data-act="setgame">Use this game</button>
    </div>
  </div>

  <div class="clip-grid">
    <div class="field clip-span2">
      <span class="field-label">Style</span>
      <div class="seg" id="clip-style" role="group" aria-label="Clip style"></div>
      <p class="field-help" id="clip-style-help"></p>
    </div>

    <div class="field hide" id="clip-rounds-field">
      <span class="field-label">What to clip</span>
      <div class="field-inline">
        <button class="switch is-on" type="button" role="switch" id="clip-rounds"
                aria-checked="true"><span class="switch-dot"></span></button>
        <label for="clip-rounds">Whole rounds, not bursts of kills</label>
      </div>
      <p class="field-help">Counter-Strike is scored by the round, so a 1v3 won
         with one kill matters more than an ordinary double. Reads the scoreboard
         as well as the kill feed.</p>
      <div class="clip-types" id="clip-types"></div>
      <div class="field-inline" style="margin-top:8px">
        <button class="switch is-on" type="button" role="switch" id="clip-whole"
                aria-checked="true"><span class="switch-dot"></span></button>
        <label for="clip-whole">Keep the whole round</label>
      </div>
      <p class="field-help">A round runs 30 to 115 seconds. Off trims to the
         finish instead, which is what fits a Short.</p>
    </div>

    <div class="field" id="clip-min-field">
      <span class="field-label">Minimum kills in a clip</span>
      <div class="seg" id="clip-min" role="group" aria-label="Minimum kills"></div>
      <p class="field-help">A clip is only kept if this many kills land inside it,
         not just inside the fight it came from.</p>
    </div>

    <div class="field">
      <span class="field-label">Clip length</span>
      <div class="seg" id="clip-len" role="group" aria-label="Clip length"></div>
      <p class="field-help">A fixed length centres on the busiest seconds of each
         fight. Whole moment follows the fight however long it runs.</p>
    </div>

    <div class="field">
      <span class="field-label">Vertical copies</span>
      <div class="seg" id="clip-vert" role="group" aria-label="Vertical copies"></div>
      <p class="field-help">A 9:16 export for Shorts and Reels, made from each clip.</p>
    </div>

    <div class="field">
      <span class="field-label">Montage</span>
      <div class="field-inline">
        <button class="switch" type="button" role="switch" id="clip-montage"
                aria-checked="true" data-act="montage"><span class="switch-track">
          <span class="switch-thumb"></span></span></button>
        <select class="select" id="clip-trans" aria-label="Transition"></select>
        <select class="select" id="clip-transms" aria-label="Transition length">
          <option value="300">0.3s</option>
          <option value="500" selected>0.5s</option>
          <option value="800">0.8s</option>
          <option value="1200">1.2s</option>
        </select>
      </div>
      <p class="field-help" id="clip-trans-help">All the clips joined into one video.</p>
    </div>
  </div>

  <div class="clip-actions">
    <span class="muted" id="clip-hint"></span>
    <div class="field-inline">
      <button class="btn btn-ghost btn-sm" type="button" data-act="calibrate">"""
    + _svg("wand")
    + """<span>Calibrate a game</span></button>
      <button class="btn btn-primary" type="button" id="clip-go">"""
    + _svg("scissors")
    + """<span>Make clips</span></button>
    </div>
  </div>
</div>

<div class="card hide" id="clip-progress">
  <div class="card-head">
    <h2 class="card-title" id="clip-prog-title">Working</h2>
    <button class="btn btn-danger btn-sm" type="button" data-act="cancel">Cancel</button>
  </div>
  <div class="clip-steps" id="clip-steps"></div>
  <div class="meter" id="clip-meter" role="progressbar" aria-valuemin="0"
       aria-valuemax="100" aria-valuenow="0"><span class="meter-fill" id="clip-fill"></span></div>
  <p class="muted" id="clip-prog-msg"></p>
</div>

<div class="card hide" id="clip-results">
  <div class="card-head">
    <div>
      <h2 class="card-title" id="clip-res-title">Done</h2>
      <p class="card-sub" id="clip-res-sub"></p>
    </div>
    <button class="btn btn-sm" type="button" data-act="reveal-out">"""
    + _svg("folder")
    + """<span>Open folder</span></button>
  </div>
  <div class="clip-results" id="clip-res-list"></div>
</div>

<div class="scrim hide" id="clip-cal-scrim">
  <div class="modal clip-modal" role="dialog" aria-modal="true"
       aria-labelledby="clip-cal-title">
    <h2 class="modal-title" id="clip-cal-title">Calibrate a kill marker</h2>
    <div class="modal-body">
      <p class="muted">Scrub to a moment just after you got a kill, then drag a box
         tightly around the marker the game draws &mdash; the skull, the X, whatever
         it uses. AutoStream will check the box actually stands out before saving.</p>

      <div class="clip-cal-stage" id="clip-cal-stage">
        <img id="clip-cal-img" alt="Frame from the recording">
        <div class="clip-cal-box hide" id="clip-cal-rect"></div>
        <div class="clip-cal-wait" id="clip-cal-wait"><span class="spin"></span></div>
      </div>

      <div class="field-inline clip-cal-scrub">
        <button class="btn btn-ghost btn-sm" type="button" data-cal="-30">&minus;30s</button>
        <button class="btn btn-ghost btn-sm" type="button" data-cal="-5">&minus;5s</button>
        <input class="clip-range" type="range" id="clip-cal-range" min="0" max="100" value="0">
        <button class="btn btn-ghost btn-sm" type="button" data-cal="5">+5s</button>
        <button class="btn btn-ghost btn-sm" type="button" data-cal="30">+30s</button>
        <span class="mono muted" id="clip-cal-time">00:00:00</span>
      </div>

      <div class="field-row">
        <label class="field-label" for="clip-cal-name">Game name</label>
        <input class="input" type="text" id="clip-cal-name" maxlength="60"
               placeholder="Delta Force">
      </div>

      <div class="field-row">
        <label class="field-label">How kills show</label>
        <div class="seg" id="clip-cal-mode">
          <button class="seg-btn is-on" type="button" data-mode="template">A marker on screen</button>
          <button class="seg-btn" type="button" data-mode="killfeed">Only in the kill feed</button>
        </div>
      </div>

      <div class="field-row hide" id="clip-cal-player-row">
        <label class="field-label" for="clip-cal-player">Your in-game name</label>
        <input class="input" type="text" id="clip-cal-player" maxlength="60"
               placeholder="exactly as it appears in the feed">
      </div>
      <p class="muted small hide" id="clip-cal-mode-hint"></p>
      <p class="field-error hide" id="clip-cal-err"></p>
      <div class="clip-verdict hide" id="clip-cal-verdict"></div>
    </div>
    <div class="modal-actions">
      <button class="btn btn-ghost" type="button" data-act="cal-close">Close</button>
      <button class="btn btn-primary" type="button" id="clip-cal-save" disabled>
        Test and save</button>
    </div>
  </div>
</div>
"""
)


CLIPS_JS: str = r"""
/* ------------------------------------------------------------------ state */

var clip_state = {
  loaded: false, wired: false, busy: false,
  sessions: [], profiles: [], status: null, defaults: {},
  outputDir: '', games: [], game: '',
  pick: null,                 /* the selected session row */
  style: 'shortform',
  min: '2', len: '15', vert: 'crop', montage: true,
  trans: 'fade', transMs: 500,
  lastJob: null,
  cal: {open: false, t: 0, dur: 0, box: null, drag: null, path: '', busy: false}
};

/* Styles set pre-roll, tail and length together. The numbers come from how
   gaming clips are actually cut -- about a second or two before the kill and
   two after -- because most viewers who leave a short do so inside the first
   three seconds, and a long run-up spends the hook on nothing happening. */
var CLIP_STYLES = [
  ['shortform', 'Short-form', '1.5s before, 2s after, 15s clips. Opens on the action.'],
  ['montage',   'Montage cut', '1s before, 1.5s after, 6s clips. Cuts together without dragging.'],
  ['context',   'Full context', '6s before, 4s after, 30s clips. Better for watching back than posting.'],
  ['custom',    'Custom', 'Uses the lengths you pick below.']
];

var CLIP_MINS = [['1', '1+'], ['2', '2+'], ['3', '3+'], ['4', '4+'], ['5', '5+']];
var CLIP_LENS = [['10', '10s'], ['20', '20s'], ['30', '30s'], ['45', '45s'],
                 ['auto', 'Whole moment']];
var CLIP_VERTS = [['crop', 'Zoom'], ['fit', 'Fit'], ['none', 'None']];
/* Labels are ours; the values are real ffmpeg xfade names. "Swirl" maps to
   radial because xfade has 58 transitions and none of them is a swirl - radial
   sweeps round the centre and is the nearest real thing. */
var CLIP_TRANS = [['fade', 'Fade'], ['fadeblack', 'Dip to black'],
                  ['dissolve', 'Dissolve'], ['radial', 'Swirl'],
                  ['zoomin', 'Zoom'], ['slideleft', 'Slide'],
                  ['pixelize', 'Pixelize'], ['wipeleft', 'Wipe'],
                  ['cut', 'Hard cut'], ['mixed', 'Mixed']];
var CLIP_STEPS = [['scan', 'Find kills'], ['cut', 'Cut clips'],
                  ['vertical', 'Vertical'], ['montage', 'Montage']];

function clip_el(id) { return document.getElementById(id); }
function clip_show(id, on) {
  var e = clip_el(id);
  if (e) e.classList.toggle('hide', !on);
}

function clip_bytes(n) {
  if (!n) return '';
  var gb = n / 1073741824;
  if (gb >= 1) return gb.toFixed(1) + ' GB';
  return Math.round(n / 1048576) + ' MB';
}

function clip_when(ts) {
  if (!ts) return '';
  var d = new Date(ts * 1000);
  var now = new Date();
  var sameDay = d.toDateString() === now.toDateString();
  var time = d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  if (sameDay) return 'Today ' + time;
  return d.toLocaleDateString([], {day: 'numeric', month: 'short'}) + ' ' + time;
}

function clip_dur(s) {
  if (!s) return '';
  var h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? (h + 'h ' + m + 'm') : (m + 'm');
}

/* ------------------------------------------------------------------ chrome */

function clip_segs(host, items, current, act) {
  var h = '';
  for (var i = 0; i < items.length; i++) {
    var on = String(items[i][0]) === String(current);
    h += '<button class="seg-btn' + (on ? ' is-active' : '') + '" type="button"' +
         ' data-act="' + act + '" data-val="' + esc(items[i][0]) + '"' +
         ' aria-pressed="' + (on ? 'true' : 'false') + '">' +
         esc(items[i][1]) + '</button>';
  }
  var e = clip_el(host);
  if (e) e.innerHTML = h;
}

function clip_options(sel, items, current) {
  var e = clip_el(sel);
  if (!e) return;
  var h = '';
  for (var i = 0; i < items.length; i++) {
    h += '<option value="' + esc(items[i][0]) + '"' +
         (String(items[i][0]) === String(current) ? ' selected' : '') + '>' +
         esc(items[i][1]) + '</option>';
  }
  e.innerHTML = h;
}

/* -------------------------------------------------------------- the list */

function clip_row(s, i) {
  var gone = !s.has_recording;
  var sub = [];
  if (s.duration) sub.push(clip_dur(s.duration));
  if (s.recording_bytes) sub.push(clip_bytes(s.recording_bytes));
  if (s.kills_known) sub.push(s.kills_known + ' kills found');
  /* OBS was already recording when the session started, so most of this file
     is footage AutoStream never saw - possibly a different game entirely. */
  if (s.game_uncertain) sub.push(clip_dur(s.pre_session_seconds) + ' before this session');

  var tag;
  if (gone) tag = '<span class="tag is-warn">Recording gone</span>';
  else if (s.game_uncertain) tag = '<span class="tag is-warn">Game may be wrong</span>';
  else if (s.can_scan) tag = '<span class="tag">' + esc(s.profile) + '</span>';
  /* A killfeed game IS calibrated - it is just missing the in-game name. Saying
     "Not calibrated" would send the user to draw a box that already exists. */
  else if (s.scan_mode === 'killfeed') tag = '<span class="tag is-warn">No name set</span>';
  else tag = '<span class="tag is-warn">Not calibrated</span>';

  var on = clip_state.pick && clip_state.pick.recording_path === s.recording_path;
  return '<button class="clip-row' + (on ? ' is-active' : '') +
    (gone ? ' is-gone' : '') + '" type="button" data-act="pick" data-i="' + i + '">' +
    '<span class="clip-row-main">' +
      '<span class="clip-row-name">' + esc(s.game || 'Unknown game') + '</span>' +
      '<span class="clip-row-sub muted">' + esc(sub.join('  ·  ')) + '</span>' +
    '</span>' +
    '<span class="clip-row-when muted">' + esc(clip_when(s.display_started || s.started)) + '</span>' +
    '<span class="clip-row-tag">' + tag + '</span>' +
    '</button>';
}

function clip_renderList() {
  var host = clip_el('clip-list');
  if (!host) return;
  var rows = clip_state.sessions;
  if (clip_state.game) {
    rows = rows.filter(function (r) { return r.game === clip_state.game; });
  }
  clip_state.shown = rows;
  host.innerHTML = rows.map(clip_row).join('');

  var none = clip_state.sessions.length === 0;
  clip_show('clip-empty', none);
  clip_show('clip-listwrap', !none);
  var c = clip_el('clip-count');
  if (c) {
    c.textContent = none ? '' :
      rows.length + (rows.length === 1 ? ' stream' : ' streams');
  }
}

function clip_renderGames() {
  var sel = clip_el('clip-game');
  if (!sel) return;
  var h = '<option value="">All games</option>';
  for (var i = 0; i < clip_state.games.length; i++) {
    var g = clip_state.games[i];
    h += '<option value="' + esc(g) + '"' +
         (g === clip_state.game ? ' selected' : '') + '>' + esc(g) + '</option>';
  }
  sel.innerHTML = h;
  sel.parentNode.classList.toggle('hide', clip_state.games.length < 2);
}

/* ----------------------------------------------------------- the options */

/* The highlight types, in the order rounds.py ranks them. Losses are kept
   deliberately: a 1v3 lost at the last moment is often better viewing than a
   1v2 won, so ALMOST sits alongside CLUTCH rather than replacing it. */
var CLIP_ROUND_TYPES = [
  {key: 'ACE',      label: 'Ace (5 kills)'},
  {key: 'CLUTCH',   label: '1vN clutch won'},
  {key: 'ALMOST',   label: '1vN nearly won'},
  {key: 'KILLS',    label: '4 kills'},
  {key: 'LAST ALIVE', label: 'Last one alive'},
  {key: 'K IN',     label: 'Quick multi-kill'},
  {key: 'CHAOS',    label: 'Chaotic round'},
  {key: 'SURVIVED', label: 'Survived a loss'}
];

function clip_renderTypes() {
  var box = clip_el('clip-types');
  if (!box) return;
  if (!clip_state.types) {
    clip_state.types = CLIP_ROUND_TYPES.map(function (t) { return t.key; });
  }
  box.innerHTML = CLIP_ROUND_TYPES.map(function (t) {
    var on = clip_state.types.indexOf(t.key) >= 0;
    return '<button class="chip' + (on ? ' is-on' : '') + '" type="button" ' +
           'data-type="' + esc(t.key) + '">' + esc(t.label) + '</button>';
  }).join('');
}

function clip_renderOptions() {
  var s = clip_state.pick;
  clip_show('clip-options', !!s);
  if (!s) return;

  clip_el('clip-chosen').textContent = s.game || 'Unknown game';
  var bits = [clip_when(s.display_started || s.started)];
  if (s.duration) bits.push(clip_dur(s.duration));
  if (s.recording_bytes) bits.push(clip_bytes(s.recording_bytes));
  clip_el('clip-chosen-sub').textContent = bits.join('  ·  ');

  clip_segs('clip-style', CLIP_STYLES.map(function (s) { return [s[0], s[1]]; }),
            clip_state.style, 'style');
  var sh = clip_el('clip-style-help');
  if (sh) {
    var row = CLIP_STYLES.filter(function (s) { return s[0] === clip_state.style; })[0];
    sh.textContent = row ? row[2] : '';
  }
  /* A style owns the length, so showing an editable length control beside it
     would imply the two disagree. Only Custom exposes it. */
  var lenField = clip_el('clip-len');
  if (lenField && lenField.parentNode) {
    lenField.parentNode.classList.toggle('hide', clip_state.style !== 'custom');
  }

  var supports = !!(clip_state.pick && clip_state.pick.rounds);
  clip_show('clip-rounds-field', supports);
  var roundMode = supports && clip_state.rounds !== false;
  /* Minimum kills is meaningless for a round clip -- the round decides, not a
     kill count -- so it is hidden rather than left to mislead. */
  clip_show('clip-min-field', !roundMode);
  if (supports) clip_renderTypes();
  clip_segs('clip-min', CLIP_MINS, clip_state.min, 'min');
  clip_segs('clip-len', CLIP_LENS, clip_state.len, 'len');
  clip_segs('clip-vert', CLIP_VERTS, clip_state.vert, 'vert');
  clip_options('clip-trans', CLIP_TRANS, clip_state.trans);
  var ms = clip_el('clip-transms');
  if (ms) ms.value = String(clip_state.transMs);

  var sw = clip_el('clip-montage');
  if (sw) sw.setAttribute('aria-checked', clip_state.montage ? 'true' : 'false');
  [['clip-rounds', clip_state.rounds !== false],
   ['clip-whole', clip_state.whole !== false]].forEach(function (pair) {
    var el = clip_el(pair[0]);
    if (!el) return;
    el.setAttribute('aria-checked', pair[1] ? 'true' : 'false');
    el.classList.toggle('is-on', !!pair[1]);
  });
  var td = clip_el('clip-trans'), tm = clip_el('clip-transms');
  if (td) td.disabled = !clip_state.montage;
  if (tm) tm.disabled = !clip_state.montage || clip_state.trans === 'cut';

  /* Only offered when the recording predates the session: that is the case
     where the detected game describes a minute of a much longer file. */
  clip_show('clip-wrongwrap', !!s.game_uncertain);
  if (s.game_uncertain) {
    clip_el('clip-wrongtext').textContent =
      'OBS was already recording ' + clip_dur(s.pre_session_seconds) +
      ' before this session started, so most of this file is footage AutoStream ' +
      'never saw. It is labelled ' + (s.game || 'unknown') +
      ' because that is what was running at the end. If that is wrong, correct it here.';
    var sel = clip_el('clip-gamefix');
    if (sel) {
      var opts = (clip_state.profiles || []).map(function (pr) {
        return '<option value="' + esc(pr.key) + '" data-label="' + esc(pr.label) +
               '"' + (pr.label === s.game ? ' selected' : '') + '>' + esc(pr.label) + '</option>';
      }).join('');
      sel.innerHTML = opts || '<option value="">no calibrated games</option>';
    }
  }

  var go = clip_el('clip-go');
  var hint = clip_el('clip-hint');
  var why = '';
  if (!s.has_recording) why = 'The recording for this stream is no longer on disk.';
  else if (!s.can_scan) {
    /* The profile knows exactly what is missing, so say that rather than the
       generic line - the two causes need completely different fixes. */
    why = s.blocked || ('No kill marker is calibrated for ' +
          (s.game || 'this game') + ' yet. Use Calibrate a game first.');
  } else if (clip_state.busy) why = 'A clip job is already running.';

  /* A note is not a reason to disable anything, so it is kept separate from
     `why`. Reading a kill feed runs about 10 frames a second where a template
     match runs thousands, so an hour of footage takes minutes to scan. Better
     said before the button is pressed than discovered afterwards. */
  var note = '';
  if (!why && s.scan_mode === 'killfeed') {
    note = 'Kills for ' + esc(s.game || 'this game') + ' are read out of the ' +
           'kill feed, which is slower than a marker scan - roughly a minute ' +
           'per 10 minutes of footage. Assists are detected and not clipped.';
  }
  if (go) go.disabled = !!why;
  if (hint) hint.textContent = why || note;
}

/* ---------------------------------------------------------- the progress */

function clip_renderJob(j) {
  var running = !!j && (j.state === 'running' || j.state === 'queued');
  clip_state.busy = running;
  clip_show('clip-progress', running);

  if (running) {
    clip_el('clip-prog-title').textContent = 'Making clips from ' + (j.game || 'the stream');
    clip_el('clip-prog-msg').textContent = j.message || '';
    var fill = clip_el('clip-fill'), meter = clip_el('clip-meter');
    if (fill) fill.style.width = j.percent + '%';
    if (meter) meter.setAttribute('aria-valuenow', String(j.percent));

    var h = '';
    for (var i = 0; i < CLIP_STEPS.length; i++) {
      var cls = i < j.step_index ? ' is-done' : (i === j.step_index ? ' is-now' : '');
      h += '<span class="clip-step' + cls + '">' + esc(CLIP_STEPS[i][1]) + '</span>';
    }
    var st = clip_el('clip-steps');
    if (st) st.innerHTML = h;
  }

  /* Results stay on screen after the run, so closing and reopening the page
     mid-job still ends with something to click. */
  var done = !!j && (j.state === 'done' || j.state === 'failed' || j.state === 'cancelled');
  clip_show('clip-results', done);
  if (!done) return;

  clip_el('clip-res-title').textContent =
    j.state === 'done' ? 'Clips ready' :
    (j.state === 'cancelled' ? 'Cancelled' : 'Could not finish');

  var sum = j.summary || {};
  var sub;
  if (j.state === 'done') {
    sub = j.clips + (j.clips === 1 ? ' clip' : ' clips') +
          (sum.kills ? '  ·  ' + sum.covered + ' of ' + sum.kills +
                       ' kills (' + sum.coverage + '%)' : '') +
          '  ·  ' + (j.folder || '');
  } else {
    sub = j.error || j.message || '';
  }
  clip_el('clip-res-sub').textContent = sub;
  clip_show('clip-res-list', j.state === 'done');
}

function clip_renderResults(list, montagePath) {
  var host = clip_el('clip-res-list');
  if (!host) return;
  var h = '';
  if (montagePath) {
    h += '<div class="clip-res is-montage">' +
         '<span class="clip-res-rank">' + icon('film') + '</span>' +
         '<span class="clip-res-name">Montage</span>' +
         '<span class="clip-res-meta muted">every clip, joined</span>' +
         '<span class="clip-res-acts">' +
         '<button class="btn btn-ghost btn-sm" type="button" data-act="reveal"' +
         ' data-path="' + esc(montagePath) + '">Show</button></span></div>';
  }
  for (var i = 0; i < list.length; i++) {
    var c = list[i];
    h += '<div class="clip-res">' +
      '<span class="clip-res-rank mono">' + esc(String(c.rank)) + '</span>' +
      '<span class="clip-res-name">' + esc(c.kills) +
        (c.kills === 1 ? ' kill' : ' kills') + '</span>' +
      '<span class="clip-res-meta muted">at ' + esc(c.at) + '  ·  ' +
        Math.round(c.duration) + 's</span>' +
      '<span class="clip-res-acts">' +
      '<button class="btn btn-ghost btn-sm" type="button" data-act="reveal"' +
      ' data-path="' + esc(c.master) + '">Show</button></span></div>';
  }
  host.innerHTML = h;
}

/* -------------------------------------------------------------- actions */

async function clip_load() {
  try {
    var r = await API.get('/api/clips/sessions');
    if (r && r.error) { toast(r.error, 'error'); return; }
    clip_state.sessions = (r && r.sessions) || [];
    clip_state.profiles = (r && r.profiles) || [];
    clip_state.status = (r && r.status) || null;
    clip_state.games = (r && r.games) || [];
    clip_state.outputDir = (r && r.output_dir) || '';
    clip_state.loaded = true;

    var d = (r && r.defaults) || {};
    if (d['clips.style']) clip_state.style = String(d['clips.style']);
    if (d['clips.min_kills']) clip_state.min = String(d['clips.min_kills']);
    if (d['clips.clip_seconds']) clip_state.len = String(d['clips.clip_seconds']);
    if (d['clips.vertical_mode']) clip_state.vert = String(d['clips.vertical_mode']);
    if (d['clips.transition']) clip_state.trans = String(d['clips.transition']);
    if (d['clips.transition_ms']) clip_state.transMs = Number(d['clips.transition_ms']);

    var ok = !clip_state.status || clip_state.status.ok;
    clip_show('clip-setup', !ok);
    if (!ok) {
      clip_el('clip-setup-text').textContent =
        'The Clips page needs ' + clip_state.status.missing.join(' and ') +
        '. Everything else in AutoStream works without it.';
      clip_el('clip-setup-detail').textContent = clip_state.status.detail || '';
    }

    /* Keep the selection across a refresh if that stream is still listed. */
    if (clip_state.pick) {
      var want = clip_state.pick.recording_path;
      clip_state.pick = clip_state.sessions.filter(function (s) {
        return s.recording_path === want;
      })[0] || null;
    }
    if (!clip_state.pick) {
      clip_state.pick = clip_state.sessions.filter(function (s) {
        return s.has_recording;
      })[0] || null;
    }
    clip_renderGames();
    clip_renderList();
    clip_renderOptions();
  } catch (e) {
    toast('Could not read the stream history.', 'error');
  }
}

async function clip_run() {
  var s = clip_state.pick;
  if (!s) return;
  var go = clip_el('clip-go');
  if (go) go.disabled = true;
  try {
    var r = await API.post('/api/clips/run', {
      /* `source` wins server-side. A file the user picked is not in the
         history, so there is no row to look it up by. */
      source: s.source || '',
      recording_path: s.recording_path,
      game: s.game, game_key: s.game_key,
      style: clip_state.style,
      min_kills: Number(clip_state.min),
      clip_seconds: clip_state.len,
      vertical_mode: clip_state.vert,
      montage: clip_state.montage,
      transition: clip_state.trans,
      transition_ms: clip_state.transMs,
      rounds: clip_state.rounds !== false,
      whole_round: clip_state.whole !== false,
      round_types: clip_state.types || null
    });
    if (r && r.error) { toast(r.error, 'error'); if (go) go.disabled = false; return; }
    clip_state.busy = true;
    clip_show('clip-results', false);
    toast(r && r.reused_kills
      ? 'Re-cutting with the kills found earlier.'
      : 'Scanning the recording for kills.', 'ok');
  } catch (e) {
    toast('Could not start.', 'error');
    if (go) go.disabled = false;
  }
}

/* ------------------------------------------------- a file the user picked */

/* The whole clips-only path: somebody with a recording and no interest in
   streaming should not have to have made that recording with AutoStream. The
   picked file becomes an ordinary `pick`, so every option below it -- style,
   length, rounds, montage -- works exactly as it does for a stream, rather
   than growing a second, poorer copy of the same form. */
async function clip_loadGames() {
  try {
    var r = await API.get('/api/clips/games');
    clip_state.localGames = (r && r.games) || [];
  } catch (e) { clip_state.localGames = []; }
  var sel = clip_el('clip-local-game');
  if (!sel) return;
  sel.innerHTML = clip_state.localGames.map(function (g) {
    return '<option value="' + esc(g.game_key) + '">' + esc(g.game) +
           (g.can_scan ? '' : ' (needs calibrating)') + '</option>';
  }).join('') || '<option value="">No games available</option>';
}

async function clip_pickLocal() {
  var r;
  try {
    r = await API.post('/api/clips/pick', {});
  } catch (e) { toast('Could not open the file picker.', 'error'); return; }
  if (r && r.error) { toast(r.error, 'error'); return; }
  if (!r || !r.path) return;                 /* cancelled */
  clip_state.localFile = r;
  var lbl = clip_el('clip-local-path');
  if (lbl) lbl.textContent = r.name + '  ' + (r.size_mb ? r.size_mb + ' MB' : '');
  var go = clip_el('clip-local-go');
  if (go) go.disabled = false;
}

function clip_useLocal() {
  var f = clip_state.localFile;
  var sel = clip_el('clip-local-game');
  if (!f || !sel || !sel.value) {
    toast('Choose a video and a game first.', 'warn');
    return;
  }
  var g = null;
  for (var i = 0; i < clip_state.localGames.length; i++) {
    if (clip_state.localGames[i].game_key === sel.value) g = clip_state.localGames[i];
  }
  if (!g) return;
  /* Shaped like a history row so clip_renderOptions needs no special case.
     `source` is what marks it as not-from-history. */
  clip_state.pick = {
    source: f.path, recording_path: f.path,
    game: g.game, game_key: g.game_key, profile: g.profile,
    can_scan: g.can_scan, scan_mode: g.scan_mode, rounds: g.rounds,
    counts_assists: g.counts_assists, blocked: g.blocked, player: g.player,
    started: null, display_started: null, local: true
  };
  clip_renderList();
  clip_renderOptions();
  var card = clip_el('clip-options');
  if (card && card.scrollIntoView) card.scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function clip_setGame() {
  var s = clip_state.pick;
  var sel = clip_el('clip-gamefix');
  if (!s || !sel || !sel.value) return;
  var label = sel.options[sel.selectedIndex].getAttribute('data-label') || sel.value;
  if (s.local) {
    /* Nothing to correct in the journal: this file was never a session. */
    s.game_key = sel.value;
    s.game = label;
    clip_renderOptions();
    return;
  }
  var r = await API.post('/api/clips/setgame', {
    recording_path: s.recording_path, game: label, game_key: sel.value});
  if (r && r.error) { toast(r.error, 'error'); return; }
  toast('Now treated as ' + label + '.', 'ok');
  await clip_load();
}

async function clip_reveal(path) {
  if (!path) return;
  var r = await API.post('/api/clips/open', {path: path});
  if (r && r.error) toast(r.error, 'warn');
}

/* ----------------------------------------------------------- calibration */

function clip_calOpen() {
  var s = clip_state.pick;
  if (!s || !s.has_recording) {
    toast('Pick a stream with a recording first.', 'warn');
    return;
  }
  clip_state.cal.open = true;
  clip_state.cal.path = s.recording_path;
  clip_state.cal.dur = s.duration || 0;
  clip_state.cal.t = Math.min(60, (s.duration || 0) / 2);
  clip_state.cal.box = null;
  var range = clip_el('clip-cal-range');
  if (range) {
    range.max = String(Math.max(1, Math.floor(clip_state.cal.dur)));
    range.value = String(Math.floor(clip_state.cal.t));
  }
  var name = clip_el('clip-cal-name');
  if (name) name.value = s.game || '';
  /* Start on the mode this game actually needs. A seed says so before any
     profile exists, and an existing profile says so afterwards, so the user
     is confirming rather than guessing. */
  var player = clip_el('clip-cal-player');
  if (player) player.value = s.player || '';
  clip_calSetMode(s.scan_mode || (s.seed && s.seed.mode) || 'template');
  clip_show('clip-cal-scrim', true);
  clip_show('clip-cal-rect', false);
  clip_show('clip-cal-verdict', false);
  clip_show('clip-cal-err', false);
  clip_calFrame();
  clip_calSaveState();
}

function clip_calClose() {
  clip_state.cal.open = false;
  clip_show('clip-cal-scrim', false);
}

function clip_calFrame() {
  var img = clip_el('clip-cal-img');
  if (!img) return;
  clip_show('clip-cal-wait', true);
  var url = '/api/clips/frame?k=' + encodeURIComponent(SHELL_K) +
            '&path=' + encodeURIComponent(clip_state.cal.path) +
            '&t=' + encodeURIComponent(String(clip_state.cal.t));
  img.onload = function () { clip_show('clip-cal-wait', false); };
  img.onerror = function () {
    clip_show('clip-cal-wait', false);
    clip_calErr('Could not read that frame.');
  };
  img.src = url;
  var lbl = clip_el('clip-cal-time');
  if (lbl) lbl.textContent = shell_hms(clip_state.cal.t);
  /* A new frame invalidates the box drawn on the old one. */
  clip_state.cal.box = null;
  clip_show('clip-cal-rect', false);
  clip_show('clip-cal-verdict', false);
  clip_calSaveState();
}

function clip_calSeek(delta) {
  var c = clip_state.cal;
  c.t = Math.max(0, Math.min(c.dur || 1e9, c.t + delta));
  var range = clip_el('clip-cal-range');
  if (range) range.value = String(Math.floor(c.t));
  clip_calFrame();
}

function clip_calErr(msg) {
  var e = clip_el('clip-cal-err');
  if (!e) return;
  e.textContent = msg || '';
  e.classList.toggle('hide', !msg);
}

function clip_calSaveState() {
  var b = clip_el('clip-cal-save');
  var name = clip_el('clip-cal-name');
  if (!b) return;
  /* Reading the feed needs a name to look for. Without one the scan finds
     nothing and looks like a game with no kills, so the button stays off
     rather than letting a useless profile be saved. */
  var player = clip_el('clip-cal-player');
  var needsPlayer = clip_calMode() === 'killfeed' &&
                    !(player && player.value.trim());
  b.disabled = clip_state.cal.busy || !clip_state.cal.box ||
               !(name && name.value.trim()) || needsPlayer;
}

function clip_calDrag(stage, rect) {
  /* Fractions of the IMAGE, not of the stage: the image is letterboxed inside
     the stage, and sending stage-relative numbers would offset every box by
     the size of the black bars. */
  var img = clip_el('clip-cal-img');
  if (!img || !img.naturalWidth) return null;
  var ib = img.getBoundingClientRect();
  var x1 = (Math.min(rect.x1, rect.x2) - ib.left) / ib.width;
  var y1 = (Math.min(rect.y1, rect.y2) - ib.top) / ib.height;
  var x2 = (Math.max(rect.x1, rect.x2) - ib.left) / ib.width;
  var y2 = (Math.max(rect.y1, rect.y2) - ib.top) / ib.height;
  x1 = Math.max(0, Math.min(1, x1)); x2 = Math.max(0, Math.min(1, x2));
  y1 = Math.max(0, Math.min(1, y1)); y2 = Math.max(0, Math.min(1, y2));
  if (x2 - x1 < 0.004 || y2 - y1 < 0.006) return null;
  return [x1, y1, x2, y2];
}

var CLIP_CAL_HINTS = {
  template: 'Drag a tight box around the marker the game draws when YOU get a ' +
            'kill - usually a small icon near the crosshair.',
  killfeed: 'Drag a box around the WHOLE kill feed, wide enough to include the ' +
            'names at both ends of every line. Your name left of the weapon ' +
            'icon is a kill, right of it is a death.'
};

function clip_calMode() {
  return (clip_state.cal && clip_state.cal.mode) || 'template';
}

function clip_calSetMode(mode) {
  clip_state.cal.mode = (mode === 'killfeed') ? 'killfeed' : 'template';
  var seg = clip_el('clip-cal-mode');
  if (seg) {
    var bs = seg.querySelectorAll('[data-mode]');
    for (var i = 0; i < bs.length; i++) {
      bs[i].classList.toggle('is-on', bs[i].dataset.mode === clip_state.cal.mode);
    }
  }
  var row = clip_el('clip-cal-player-row');
  if (row) row.classList.toggle('hide', clip_state.cal.mode !== 'killfeed');
  var hint = clip_el('clip-cal-mode-hint');
  if (hint) {
    hint.textContent = CLIP_CAL_HINTS[clip_state.cal.mode] || '';
    hint.classList.remove('hide');
  }
  clip_calSaveState();
}

async function clip_calSave() {
  var c = clip_state.cal;
  var name = clip_el('clip-cal-name');
  if (!c.box || !name || !name.value.trim()) return;
  c.busy = true;
  clip_calSaveState();
  clip_calErr('');
  var v = clip_el('clip-cal-verdict');
  if (v) { v.classList.remove('hide'); v.className = 'clip-verdict';
           v.innerHTML = '<span class="spin"></span> ' + (clip_calMode() === 'killfeed'
             ? 'Checking your name is readable in that box...'
             : 'Checking the marker stands out...'); }
  try {
    var player = clip_el('clip-cal-player');
    var r = await API.post('/api/clips/calibrate', {
      path: c.path, t: c.t, box: c.box,
      label: name.value.trim(),
      key: (clip_state.pick && clip_state.pick.game_key) || '',
      mode: clip_calMode(),
      player: (player && player.value.trim()) || ''
    });
    if (r && r.error) {
      clip_calErr(r.error);
      if (v) v.classList.add('hide');
    } else if (v) {
      v.className = 'clip-verdict is-' + (r.separation || 'weak');
      v.textContent = r.note || '';
      if (r.separation === 'bad') {
        toast('That marker is not distinct enough - try again.', 'warn');
      } else {
        toast('Saved a profile for ' + r.label + '.', 'ok');
        await clip_load();
      }
    }
  } catch (e) {
    clip_calErr('Could not save that.');
  }
  c.busy = false;
  clip_calSaveState();
}

/* ------------------------------------------------------------------ wiring */

function clip_wire() {
  if (clip_state.wired) return;
  clip_state.wired = true;

  var g = clip_el('clip-game');
  if (g) g.addEventListener('change', function () {
    clip_state.game = g.value; clip_renderList();
  });
  var rf = clip_el('clip-refresh');
  if (rf) rf.addEventListener('click', clip_load);
  var go = clip_el('clip-go');
  if (go) go.addEventListener('click', clip_run);

  var rsw = clip_el('clip-rounds');
  if (rsw) rsw.addEventListener('click', function () {
    clip_state.rounds = clip_state.rounds === false;
    clip_renderOptions();
  });
  var wsw = clip_el('clip-whole');
  if (wsw) wsw.addEventListener('click', function () {
    clip_state.whole = clip_state.whole === false;
    clip_renderOptions();
  });
  var types = clip_el('clip-types');
  if (types) types.addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-type]');
    if (!b) return;
    var k = b.dataset.type;
    var i = clip_state.types.indexOf(k);
    if (i >= 0) clip_state.types.splice(i, 1);
    else clip_state.types.push(k);
    /* Turning everything off would silently produce nothing, so the last one
       stays on rather than the run failing with an empty selection. */
    if (!clip_state.types.length) clip_state.types = [k];
    clip_renderTypes();
  });

  var tr = clip_el('clip-trans');
  if (tr) tr.addEventListener('change', function () {
    clip_state.trans = tr.value; clip_renderOptions();
  });
  var tm = clip_el('clip-transms');
  if (tm) tm.addEventListener('change', function () {
    clip_state.transMs = Number(tm.value);
  });

  /* One delegated listener for everything with a data-act. No inline onclick
     anywhere, so rebuilding a list never leaks a handler. */
  document.addEventListener('click', function (ev) {
    var b = ev.target && ev.target.closest ? ev.target.closest('[data-act]') : null;
    if (!b) return;
    var view = clip_el('view-clips');
    if (!view || !view.contains(b)) return;
    var act = b.getAttribute('data-act');

    if (act === 'style') {
      clip_state.style = b.getAttribute('data-val');
      clip_renderOptions();
    } else if (act === 'pick') {
      clip_state.pick = clip_state.shown[Number(b.getAttribute('data-i'))] || null;
      clip_renderList(); clip_renderOptions();
    } else if (act === 'min') {
      clip_state.min = b.getAttribute('data-val'); clip_renderOptions();
    } else if (act === 'len') {
      clip_state.len = b.getAttribute('data-val'); clip_renderOptions();
    } else if (act === 'vert') {
      clip_state.vert = b.getAttribute('data-val'); clip_renderOptions();
    } else if (act === 'montage') {
      clip_state.montage = !clip_state.montage; clip_renderOptions();
    } else if (act === 'cancel') {
      API.post('/api/clips/cancel', {});
    } else if (act === 'reveal') {
      clip_reveal(b.getAttribute('data-path'));
    } else if (act === 'reveal-src') {
      clip_reveal(clip_state.pick && clip_state.pick.recording_path);
    } else if (act === 'reveal-out') {
      clip_reveal((clip_state.lastJob && clip_state.lastJob.folder) ||
                  clip_state.outputDir);
    } else if (act === 'pick-local') {
      clip_pickLocal();
    } else if (act === 'use-local') {
      clip_useLocal();
    } else if (act === 'setgame') {
      clip_setGame();
    } else if (act === 'calibrate') {
      clip_calOpen();
    } else if (act === 'cal-close') {
      clip_calClose();
    }
  });

  /* calibration: scrub buttons, range, and the drag-a-box overlay */
  document.addEventListener('click', function (ev) {
    var b = ev.target && ev.target.closest ? ev.target.closest('[data-cal]') : null;
    if (b) clip_calSeek(Number(b.getAttribute('data-cal')));
  });
  var range = clip_el('clip-cal-range');
  if (range) range.addEventListener('change', function () {
    clip_state.cal.t = Number(range.value); clip_calFrame();
  });
  var nm = clip_el('clip-cal-name');
  if (nm) nm.addEventListener('input', clip_calSaveState);
  var pl = clip_el('clip-cal-player');
  if (pl) pl.addEventListener('input', clip_calSaveState);
  var seg = clip_el('clip-cal-mode');
  if (seg) seg.addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-mode]');
    if (b) clip_calSetMode(b.dataset.mode);
  });
  var save = clip_el('clip-cal-save');
  if (save) save.addEventListener('click', clip_calSave);

  var stage = clip_el('clip-cal-stage');
  if (stage) {
    stage.addEventListener('pointerdown', function (ev) {
      if (ev.button !== 0) return;
      clip_state.cal.drag = {x1: ev.clientX, y1: ev.clientY,
                             x2: ev.clientX, y2: ev.clientY};
      stage.setPointerCapture(ev.pointerId);
      clip_calPaint();
      ev.preventDefault();
    });
    stage.addEventListener('pointermove', function (ev) {
      var d = clip_state.cal.drag;
      if (!d) return;
      d.x2 = ev.clientX; d.y2 = ev.clientY;
      clip_calPaint();
    });
    stage.addEventListener('pointerup', function (ev) {
      var d = clip_state.cal.drag;
      clip_state.cal.drag = null;
      if (!d) return;
      try { stage.releasePointerCapture(ev.pointerId); } catch (e) {}
      var box = clip_calDrag(stage, d);
      clip_state.cal.box = box;
      if (!box) {
        clip_show('clip-cal-rect', false);
        clip_calErr('That box is too small - drag a bigger one round the marker.');
      } else {
        clip_calErr('');
      }
      clip_calSaveState();
    });
  }

  /* Escape closes the calibrator, matching every other modal convention. */
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && clip_state.cal.open) clip_calClose();
  });
}

function clip_calPaint() {
  var d = clip_state.cal.drag;
  var stage = clip_el('clip-cal-stage'), r = clip_el('clip-cal-rect');
  if (!d || !stage || !r) return;
  var sb = stage.getBoundingClientRect();
  r.classList.remove('hide');
  r.style.left = (Math.min(d.x1, d.x2) - sb.left) + 'px';
  r.style.top = (Math.min(d.y1, d.y2) - sb.top) + 'px';
  r.style.width = Math.abs(d.x2 - d.x1) + 'px';
  r.style.height = Math.abs(d.y2 - d.y1) + 'px';
}

/* ------------------------------------------------------------------ page */

window.PAGE_CLIPS = {
  onShow: function () {
    clip_wire();
    if (!clip_state.loaded) { clip_load(); clip_loadGames(); }
    else clip_renderOptions();
  },
  onTick: function (status) {
    var j = status && status.clips;
    if (!j) { clip_state.busy = false; return; }
    var wasBusy = clip_state.busy;
    clip_renderJob(j);
    if (j.state === 'done' && (!clip_state.lastJob ||
        clip_state.lastJob.folder !== j.folder ||
        clip_state.lastJob.state !== 'done')) {
      /* The job payload is a summary; the per-clip list lives in the folder's
         manifest, so it is only fetched once the run actually finishes. */
      clip_fetchResults(j);
    }
    clip_state.lastJob = j;
    if (wasBusy && !clip_state.busy) {
      clip_load();
      if (j.state === 'done') toast('Clips are ready.', 'ok');
      else if (j.state === 'failed') toast(j.error || 'Clip job failed.', 'error');
    }
  }
};

async function clip_fetchResults(j) {
  /* Results ride the sessions endpoint rather than getting one of their own -
     it is already the page's refresh path. */
  try {
    var r = await API.get('/api/clips/sessions');
    var last = (r && r.last_job) || null;
    if (last && last.clips) clip_renderResults(last.clips, last.montage);
    else clip_renderResults([], j.montage);
  } catch (e) { /* the headline summary is already on screen */ }
}
"""
