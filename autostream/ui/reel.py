r"""The Clips page's reel maker: kills cut to a song, on the beat.

WHERE IT SITS IN THE FLOW. After a review, not before. Reviewing already
produces the list of moments and their kill counts, and the reel needs exactly
that -- so the picker here is "which of these", not a second detection pass.
It is one card that walks through five choices in order, because each one
narrows the next: a song decides the tempo, the part decides how many slots
exist, and only then does a template mean anything.

WHAT THE PAGE DOES NOT DECIDE. Where the beats are. That comes back from
/api/reel/song, measured -- tempo, the downbeat, and where the drums come in.
The page draws them and offers arrangements; it never invents an instant. When
the arrangement is wrong the answer is the beat marker, which hands back exact
times that override the template outright.

NAMING. Everything here is prefixed reel_ and the single global is
window.PAGE_REEL -- all view modules share one scope.
"""
from __future__ import annotations

from .icons import ICONS


def _svg(name: str, size: int = 16) -> str:
    body = ICONS.get(name, "")
    return (f'<svg class="icon" viewBox="0 0 24 24" width="{size}" height="{size}"'
            f' aria-hidden="true" focusable="false">{body}</svg>')


REEL_HTML: str = (
    """
<!-- THE REEL MAKER. Hidden until a review exists, because it cuts the moments
     the review found and there is nothing to offer before that. -->
<div class="card hide" id="reel-card">
  <div class="card-head">
    <div>
      <h2 class="card-title">Make a reel</h2>
      <p class="card-sub">Kills cut to a song, each one landing on a beat.
         Pick a track and the moments you want; the beat grid comes from the
         music itself.</p>
    </div>
    <button class="btn btn-ghost btn-sm" type="button" data-act="reel-close">
      <span>Not now</span></button>
  </div>

  <div class="card-body">
    <!-- THE STRAIGHT PATH, taken when the song edit is asked for from the
         finished clips: choose a track and the edit is made, with the whole
         five-step card kept behind "Not quite" for when it is wrong. -->
    <section class="reel-quick hide" id="reel-quick">
      <p class="reel-quick-msg" id="reel-quick-msg"></p>
      <div class="field-inline hide" id="reel-quick-pick">
        <button class="btn btn-primary" type="button" data-act="reel-quick-song">
          Choose a song&hellip;</button>
        <span class="muted">Any track on this PC. It is not uploaded anywhere.</span>
      </div>
      <div class="hide" id="reel-quick-result">
        <video class="reel-quick-video" id="reel-quick-video" controls
               playsinline preload="metadata"></video>
        <span class="media-knobs" data-for="reel-quick-video"></span>
        <p class="muted" id="reel-quick-facts"></p>
        <p class="reel-quick-ask" id="reel-quick-ask">How is it?</p>
        <div class="field-inline">
          <button class="btn btn-primary" type="button" data-act="reel-quick-love">
            Love it</button>
          <button class="btn" type="button" data-act="reel-quick-fix">
            Not quite &mdash; let me fix it</button>
          <button class="btn btn-ghost" type="button" data-act="reel-show">
            Show the file</button>
        </div>
      </div>
      <div class="panel hide" id="reel-quick-fixer">
        <p class="muted"><b>1.</b> Drag the handles to the part of the song you
           want. <b>2.</b> Play it and press <kbd>M</kbd> on every beat a kill
           should land on. <b>3.</b> Make it again.</p>
      </div>
    </section>

    <ol class="reel-steps" id="reel-steps"></ol>

    <!-- 1. the song -->
    <section class="reel-step" id="reel-step-song">
      <h3 class="reel-h">1 &middot; The song</h3>
      <div class="field-inline">
        <button class="btn" type="button" data-act="reel-song">Choose a track&hellip;</button>
        <span class="muted" id="reel-song-name">No track chosen.</span>
      </div>
      <p class="muted" id="reel-song-facts"></p>
    </section>

    <!-- 2. which part of it -->
    <section class="reel-step hide" id="reel-step-part">
      <h3 class="reel-h">2 &middot; Which part</h3>
      <canvas class="reel-wave" id="reel-wave" height="120"></canvas>
      <div class="clip-range" id="reel-range">
        <input class="clip-range-in" type="range" id="reel-from" min="0" max="1000"
               value="0" step="1" aria-label="Start of the part to use">
        <input class="clip-range-in" type="range" id="reel-to" min="0" max="1000"
               value="400" step="1" aria-label="End of the part to use">
      </div>
      <p class="muted" id="reel-part-facts"></p>
    </section>

    <!-- 3. the moments -->
    <section class="reel-step hide" id="reel-step-kills">
      <h3 class="reel-h">3 &middot; The moments</h3>
      <div class="field-inline">
        <button class="btn btn-sm" type="button" data-act="reel-all">All</button>
        <button class="btn btn-sm" type="button" data-act="reel-none">None</button>
        <button class="btn btn-sm" type="button" data-act="reel-best">Only the labelled ones</button>
        <span class="muted" id="reel-kills-count"></span>
      </div>
      <div class="reel-kills" id="reel-kills"></div>
    </section>

    <!-- 4. the shape -->
    <section class="reel-step hide" id="reel-step-shape">
      <h3 class="reel-h">4 &middot; The shape of the edit</h3>
      <div class="reel-templates" id="reel-templates"></div>
    </section>

    <!-- 5. what it will do, before anything is encoded -->
    <section class="reel-step hide" id="reel-step-plan">
      <h3 class="reel-h">5 &middot; Where every kill lands</h3>
      <canvas class="reel-wave" id="reel-plan-wave" height="120"></canvas>
      <p class="muted" id="reel-plan-facts"></p>
      <p class="muted" id="reel-plan-note"></p>
      <div class="field-inline">
        <button class="btn btn-primary" type="button" data-act="reel-build">"""
    + _svg("film")
    + """<span>Make the reel</span></button>
        <button class="btn" type="button" data-act="reel-mark">Mark the beats myself</button>
        <span class="muted" id="reel-build-msg"></span>
      </div>
    </section>

    <!-- after it exists -->
    <section class="reel-step hide" id="reel-step-done">
      <h3 class="reel-h">Done</h3>
      <p class="muted" id="reel-done-facts"></p>
      <div class="field-inline">
        <button class="btn" type="button" data-act="reel-show">Show the file</button>
        <button class="btn" type="button" data-act="reel-mark">Change the beats</button>
        <button class="btn" type="button" data-act="reel-again">Tune the moments</button>
      </div>
    </section>

    <!-- THE BEAT MARKER, in the page rather than a separate tool. Tapping is
         only needed when a template is not what somebody wants, and it snaps
         to the grid the song analysis already found, so what comes back is a
         choice of WHICH beats carry a kill. -->
    <section class="reel-step hide" id="reel-step-mark">
      <h3 class="reel-h">Tap where the kills should land</h3>
      <p class="muted">Press <kbd>Space</kbd> on every beat that should carry a
         kill. Taps snap to the nearest beat, so timing does not have to be
         exact &mdash; only the choice does. <kbd>Enter</kbd> plays and pauses,
         <kbd>&larr;</kbd><kbd>&rarr;</kbd> nudge (hold <kbd>Shift</kbd> for a
         second), <kbd>Backspace</kbd> undoes. Click the wave to jump.</p>
      <audio id="reel-audio" controls preload="auto"></audio>
      <span class="media-knobs" data-for="reel-audio"></span>
      <canvas class="reel-wave" id="reel-mark-wave" height="120"></canvas>
      <div class="field-inline">
        <span class="reel-clock" id="reel-mark-clock">0.000s</span>
        <button class="btn btn-primary" type="button" data-act="reel-tap">Kill here (Space)</button>
        <button class="btn" type="button" data-act="reel-play">Play / Pause</button>
        <button class="btn" type="button" data-act="reel-back">&larr; 1s</button>
        <button class="btn" type="button" data-act="reel-fwd">1s &rarr;</button>
        <button class="btn" type="button" data-act="reel-untap">Undo</button>
        <button class="btn" type="button" data-act="reel-clearmarks">Clear</button>
        <button class="btn" type="button" data-act="reel-seedmarks">Start from the template</button>
        <button class="btn btn-primary" type="button" id="reel-usemarks-btn"
                data-act="reel-usemarks">Use these beats</button>
      </div>
      <!-- HEARD, NOT SQUINTED AT. A mark that is on the wrong beat is obvious
           the moment it ticks against the music and nowhere near as obvious on
           a waveform. -->
      <div class="field-inline">
        <label class="muted"><input type="checkbox" id="reel-metro"> click on
          each mark as it plays</label>
        <span class="muted" id="reel-mark-count"></span>
      </div>
      <div class="reel-chips" id="reel-mark-chips"></div>
      <p class="muted" id="reel-mark-gaps"></p>
    </section>

    <!-- Last, because it acts on the two sections above it. -->
    <section class="reel-step hide" id="reel-quick-again-bar">
      <button class="btn btn-primary" type="button" data-act="reel-quick-again">
        Make it again</button>
      <span class="muted" id="reel-quick-again-msg"></span>
    </section>
  </div>
</div>
""")


REEL_JS: str = r"""
var reel_state = {
  open: false, song: '', shape: null, templates: [], template: 'bar',
  from: 0, to: 0,            /* the part of the song, in seconds */
  kills: [],                 /* from the review: which moments to use */
  plan: null, marks: null, built: null, busy: false, wired: false
};

function reel_el(id) { return document.getElementById(id); }
function reel_show(id, on) {
  var e = reel_el(id); if (e) e.classList.toggle('hide', !on);
}
function reel_secs(s) {
  s = Math.max(0, s || 0);
  var m = Math.floor(s / 60), r = s - m * 60;
  return m ? m + 'm' + (r < 10 ? '0' : '') + r.toFixed(1) + 's' : r.toFixed(2) + 's';
}
function reel_chosen() {
  return reel_state.kills.filter(function (k) { return k.on; });
}

/* THE STEP RAIL. Reports which choices are made; it does not gate them,
   because somebody changing the song after picking moments should not have to
   start again. */
function reel_renderSteps() {
  var st = reel_state;
  var steps = [['Song', !!st.song], ['Part', !!(st.shape && st.to > st.from)],
               ['Moments', reel_chosen().length > 0], ['Shape', !!st.template],
               ['Reel', !!st.built]];
  var host = reel_el('reel-steps');
  if (host) host.innerHTML = steps.map(function (s, i) {
    return '<li class="reel-step-chip' + (s[1] ? ' is-done' : '') + '">' +
      (s[1] ? '&#10003;' : (i + 1)) + ' ' + esc(s[0]) + '</li>';
  }).join('');
}

/* ---------------------------------------------------------------- 1. song */

/* ONE PLACE where a chosen song becomes the state both paths work from, so the
   straight path and the five-step card cannot drift about what a song means. */
function reel_useSong(path, got) {
  var st = reel_state;
  st.song = path;
  st.shape = got.song;
  st.templates = got.templates || [];
  st.template = got.default_template || 'bar';
  st.marks = null;
  st.from = 0;
  /* A sensible default part: the first minute, or the whole track if shorter.
     Long enough for a reel, short enough not to demand every kill a session
     ever produced. */
  st.to = Math.min(got.song.seconds, 60);
  var a = reel_el('reel-audio');
  if (a) a.src = '/api/reel/audio?k=' + encodeURIComponent(SHELL_K) +
                 '&path=' + encodeURIComponent(path);
  return reel_songFacts(got.song);
}

function reel_songFacts(s) {
  return s.bpm.toFixed(1) + ' BPM · bar ' + s.bar.toFixed(2) + 's' +
    (s.drums_in ? ' · drums in at ' + s.drums_in.toFixed(1) + 's' : '') +
    (s.drop ? ' · drop at ' + s.drop.toFixed(1) + 's' : '');
}

async function reel_pickSong() {
  var r = await API.post('/api/clips/pick', {kind: 'audio'});
  if (!r || !r.path) return;
  reel_el('reel-song-name').textContent = r.path.split(/[\\/]/).pop();
  reel_el('reel-song-facts').textContent = 'Reading the track…';
  var got = await API.post('/api/reel/song', {song: r.path});
  if (!got || !got.ok) {
    reel_el('reel-song-facts').textContent =
      (got && got.error) || 'Could not read that track.';
    return;
  }
  reel_el('reel-song-facts').textContent = reel_useSong(r.path, got);
  ['reel-step-part', 'reel-step-kills', 'reel-step-shape'].forEach(function (id) {
    reel_show(id, true);
  });
  reel_syncRange();
  reel_renderKills();
  reel_renderTemplates();
  reel_replan();
}

/* ------------------------------------------------------ 2. which part of it */

function reel_syncRange() {
  var s = reel_state.shape; if (!s) return;
  var a = reel_el('reel-from'), b = reel_el('reel-to');
  if (a) a.value = String(Math.round(reel_state.from / s.seconds * 1000));
  if (b) b.value = String(Math.round(reel_state.to / s.seconds * 1000));
  reel_el('reel-part-facts').textContent =
    'Using ' + reel_secs(reel_state.from) + ' to ' + reel_secs(reel_state.to) +
    ' — ' + reel_secs(reel_state.to - reel_state.from) + ' of music.';
  reel_drawWave('reel-wave', false);
}

function reel_rangeChanged() {
  var s = reel_state.shape; if (!s) return;
  var a = Number(reel_el('reel-from').value) / 1000 * s.seconds;
  var b = Number(reel_el('reel-to').value) / 1000 * s.seconds;
  reel_state.from = Math.min(a, b);
  reel_state.to = Math.max(a, b);
  /* The grid the taps were made against has moved, so they no longer mean
     what they meant. Keeping them would place kills on beats nobody chose. */
  reel_state.marks = null;
  reel_syncRange();
  reel_replan();
}

/* --------------------------------------------------------- 3. the moments */

function reel_loadKills(rows) {
  /* FROM THE REVIEW, not a second detection pass: those rows already carry the
     moment, its kill count and any label the round earned. */
  reel_state.kills = (rows || []).map(function (r) {
    return {
      time: Number(r.start) + (Number(r.duration || 0) * 0.6),
      round: r.round, labels: r.labels || [], name: r.name,
      count: Number(r.kills || 1), on: true
    };
  });
}

function reel_renderKills() {
  var host = reel_el('reel-kills'); if (!host) return;
  host.innerHTML = reel_state.kills.map(function (k, i) {
    var lab = (k.labels || []).join(', ');
    return '<label class="reel-kill' + (k.on ? ' is-on' : '') + '">' +
      '<input type="checkbox" data-reel-kill="' + i + '"' +
      (k.on ? ' checked' : '') + '>' +
      '<span class="reel-kill-n">' + k.count +
      (k.count === 1 ? ' kill' : ' kills') + '</span>' +
      '<span class="reel-kill-when">' + reel_secs(k.time) + '</span>' +
      (lab ? '<span class="reel-kill-lab">' + esc(lab) + '</span>' : '') +
      '</label>';
  }).join('');
  reel_el('reel-kills-count').textContent =
    reel_chosen().length + ' of ' + reel_state.kills.length + ' chosen';
  reel_renderSteps();
}

/* ----------------------------------------------------------- 4. the shape */

function reel_renderTemplates() {
  var host = reel_el('reel-templates'); if (!host) return;
  host.innerHTML = reel_state.templates.map(function (t) {
    var on = t.key === reel_state.template;
    return '<button class="reel-tpl' + (on ? ' is-on' : '') + '" type="button"' +
      ' data-act="reel-tpl" data-val="' + esc(t.key) + '"' +
      ' aria-pressed="' + (on ? 'true' : 'false') + '">' +
      '<b>' + esc(t.label) + '</b><span>' + esc(t.blurb) + '</span></button>';
  }).join('');
}

/* ------------------------------------------------------------- 5. the plan */

async function reel_replan() {
  var st = reel_state;
  if (!st.song || !st.shape || st.busy) return;
  var chosen = reel_chosen();
  if (!chosen.length) { reel_show('reel-step-plan', false); return; }
  var body = {
    song: st.song, main: st.to, fade: 0, template: st.template,
    start: st.from > 0.05 ? st.from : null,
    kills: chosen.map(function (k) {
      return {time: k.time, round: k.round, labels: k.labels};
    })
  };
  if (st.marks && st.marks.length) body.beats = st.marks;
  var r = await API.post('/api/reel/plan', body);
  reel_show('reel-step-plan', !st.quick);
  if (!r || !r.ok) {
    reel_el('reel-plan-facts').textContent =
      (r && r.error) || 'Could not work out a plan.';
    return;
  }
  st.plan = r;
  reel_el('reel-plan-facts').textContent =
    r.used + ' of ' + r.available + ' moments placed' +
    (r.used < r.available
      ? ' — the rest do not fit in this part of the song.' : '.');
  reel_el('reel-plan-note').textContent = r.note || '';
  reel_drawWave('reel-plan-wave', true);
  reel_renderSteps();
}

/* ONE DRAWING ROUTINE for all three canvases: the waveform, the beat grid, the
   chosen part, the planned slots and any hand marks. Kept together because
   they must agree about the horizontal scale, and three copies would not. */
function reel_drawWave(id, withSlots) {
  var cv = reel_el(id), st = reel_state;
  if (!cv || !st.shape) return;
  var dpr = window.devicePixelRatio || 1;
  var ctx = cv.getContext('2d');
  var w = cv.width = cv.clientWidth * dpr;
  var h = cv.height = 120 * dpr;
  var L = st.shape.seconds || 1;
  ctx.clearRect(0, 0, w, h);
  var mid = h * 0.46, pk = st.shape.peaks || [], n = pk.length || 1;

  ctx.fillStyle = '#2b6fb0';
  for (var i = 0; i < n; i++) {
    var t = i / n * L, amp = pk[i] * (h * 0.4);
    /* The part not being used is dimmed rather than hidden: it is still the
       same song, and its shape is what somebody drags the handles against. */
    ctx.globalAlpha = (t >= st.from && t <= st.to) ? 1 : 0.22;
    ctx.fillRect(i / n * w, mid - amp, Math.max(1, w / n), amp * 2);
  }
  ctx.globalAlpha = 1;
  ctx.lineWidth = 1;
  (st.shape.beats || []).forEach(function (b, i) {
    if (b < st.from || b > st.to) return;
    var down = (i % 4) === st.shape.downbeat_pos;
    ctx.strokeStyle = down ? '#c48eff' : '#39404f';
    ctx.beginPath();
    ctx.moveTo(b / L * w, h * (down ? 0.82 : 0.88));
    ctx.lineTo(b / L * w, h);
    ctx.stroke();
  });
  if (st.shape.drums_in) reel_tick(ctx, st.shape.drums_in / L * w, h, '#3fb950');
  if (st.shape.drop) reel_tick(ctx, st.shape.drop / L * w, h, '#e3b341');

  if (withSlots && st.plan) {
    ctx.strokeStyle = '#5aa9ff'; ctx.lineWidth = 2 * dpr;
    (st.plan.slots || []).forEach(function (t2) {
      ctx.beginPath();
      ctx.moveTo(t2 / L * w, 0); ctx.lineTo(t2 / L * w, h * 0.34); ctx.stroke();
    });
  }
  if (st.marks && st.marks.length) {
    ctx.strokeStyle = '#3fb950'; ctx.lineWidth = 2 * dpr;
    st.marks.forEach(function (t3) {
      ctx.beginPath();
      ctx.moveTo(t3 / L * w, h * 0.10); ctx.lineTo(t3 / L * w, h * 0.80);
      ctx.stroke();
    });
  }
}

function reel_tick(ctx, x, h, colour) {
  ctx.strokeStyle = colour;
  ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  ctx.setLineDash([]);
}

/* -------------------------------------------------------------- building */

async function reel_build() {
  var st = reel_state;
  if (!st.plan || st.busy) return;
  /* The straight path knows its recording from the finished run; the card is
     working on whatever the Clips page has picked. */
  var src = st.source || ((window.clip_state && clip_state.pick)
    ? clip_state.pick.recording_path : '');
  if (!src) { toast('No recording is selected.', 'error'); return; }
  st.busy = true;
  reel_el('reel-build-msg').textContent =
    'Cutting… this takes a couple of minutes.';
  var body = {
    song: st.song, source: src, main: st.to,
    /* The fade runs past the chosen part, into music that is already there --
       so it is a real fade rather than the track stopping. */
    fade: Math.min(4, Math.max(0, st.shape.seconds - st.to)),
    template: st.template, start: st.from > 0.05 ? st.from : null,
    name: (st.game || (clip_state.pick || {}).game || 'reel') + '-' +
          Math.round(st.shape.bpm || 0) + 'bpm',
    kills: reel_chosen().map(function (k) {
      return {time: k.time, round: k.round, labels: k.labels};
    })
  };
  if (st.marks && st.marks.length) body.beats = st.marks;
  var r = await API.post('/api/reel/run', body);
  st.busy = false;
  reel_el('reel-build-msg').textContent = '';
  if (!r || !r.ok) { toast((r && r.error) || 'The reel failed.', 'error'); return; }
  st.built = r;
  reel_show('reel-step-done', !st.quick);
  reel_el('reel-done-facts').textContent =
    r.shots + ' shots · ' + reel_secs(r.seconds) + ' · ' + r.path;
  reel_renderSteps();
  toast('Reel ready.', 'ok');
  return r;
}

/* ------------------------------------------------- the straight path */

function reel_quickMsg(text, bad) {
  var e = reel_el('reel-quick-msg');
  if (e) { e.textContent = text || ''; e.classList.toggle('is-bad', !!bad); }
}

/* Which parts of the card are on show. The five steps are not deleted in the
   straight path, only hidden: "Not quite" brings back the two that answer the
   question somebody actually has, which is the part of the song and the beats. */
function reel_quickUI(on) {
  reel_state.quick = !!on;
  reel_show('reel-quick', on);
  ['reel-steps', 'reel-step-song', 'reel-step-kills', 'reel-step-shape',
   'reel-step-plan', 'reel-step-done'].forEach(function (id) {
    var e = reel_el(id);
    if (e) e.classList.toggle('hide', !!on);
  });
  if (on) {
    ['reel-step-part', 'reel-step-mark', 'reel-quick-again-bar',
     'reel-quick-result', 'reel-quick-fixer', 'reel-quick-pick'].forEach(function (id) {
      reel_show(id, false);
    });
  }
  var um = reel_el('reel-usemarks-btn');
  if (um) um.classList.toggle('hide', !!on);
}

async function reel_quick(folder, game) {
  var st = reel_state;
  st.quick = true; st.built = null; st.marks = null; st.plan = null;
  st.source = ''; st.game = game || 'reel'; st.kills = [];
  reel_wire();
  st.open = true;
  reel_show('reel-card', true);
  reel_quickUI(true);
  var card = reel_el('reel-card');
  if (card) card.scrollIntoView({behavior: 'smooth', block: 'start'});

  reel_quickMsg('Reading what this run found…');
  var info = await API.get('/api/clips/existing?folder=' + encodeURIComponent(folder || ''));
  if (!info || !info.ok) {
    reel_quickMsg((info && info.error) || 'Could not read that run.', true);
    return;
  }
  st.source = info.source || '';
  /* The kills, not the clips: a clip is a window around a fight and the reel
     needs the instant of each kill. */
  st.kills = (info.kills || []).map(function (k) {
    return {time: Number(k.time), round: k.round,
            labels: k.labels || [], count: 1, on: true};
  });
  if (!st.kills.length || !st.source) {
    reel_quickMsg('This run has no kills to cut to a song.', true);
    return;
  }
  reel_quickPick();
}

async function reel_quickPick() {
  reel_show('reel-quick-pick', false);
  reel_quickMsg('Choose a song on your PC…');
  var r = await API.post('/api/clips/pick', {kind: 'audio'});
  if (!r || !r.path) {
    reel_quickMsg('No song chosen.');
    reel_show('reel-quick-pick', true);
    return;
  }
  reel_quickMake(r.path);
}

async function reel_quickMake(path) {
  var st = reel_state;
  reel_quickMsg('Finding the beat in ' + path.split(/[\\/]/).pop() + '…');
  var got = await API.post('/api/reel/song', {song: path});
  if (!got || !got.ok) {
    reel_quickMsg((got && got.error) || 'Could not read that track.', true);
    reel_show('reel-quick-pick', true);
    return;
  }
  var facts = reel_useSong(path, got);
  reel_quickMsg(facts + ' — working out where every kill lands…');
  await reel_replan();
  await reel_quickRender();
}

/* Shared by the first go and by "Make it again", so the fixed version is made
   exactly the way the first one was. */
async function reel_quickRender() {
  var st = reel_state;
  if (!st.plan) {
    reel_quickMsg('Could not work out a plan for that song.', true);
    return;
  }
  reel_quickMsg('Cutting your song edit… this takes a couple of minutes.');
  reel_el('reel-quick-again-msg').textContent = 'Cutting…';
  var r = await reel_build();
  reel_el('reel-quick-again-msg').textContent = '';
  if (!r || !r.ok) {
    reel_quickMsg((r && r.error) || 'The song edit failed. See the log.', true);
    return;
  }
  reel_quickMsg('');
  reel_show('reel-quick-result', true);
  var v = reel_el('reel-quick-video');
  if (v && window.clip_videoURL) { v.src = clip_videoURL(r.path); v.load(); }
  reel_el('reel-quick-facts').textContent =
    r.shots + (r.shots === 1 ? ' kill' : ' kills') + ' · ' +
    reel_secs(r.seconds) + ' · ' + (st.plan.used < st.plan.available
      ? (st.plan.available - st.plan.used) + ' more did not fit in this part of the song · ' : '') +
    r.path;
}

/* "Not quite": the two questions worth asking, in the order they matter. */
function reel_quickFix() {
  reel_show('reel-quick-fixer', true);
  reel_show('reel-step-part', true);
  reel_syncRange();
  reel_openMark();
  reel_show('reel-quick-again-bar', true);
  var e = reel_el('reel-quick-fixer');
  if (e) e.scrollIntoView({behavior: 'smooth', block: 'start'});
}

/* --------------------------------------------------------- marking beats */

function reel_openMark() {
  var st = reel_state;
  if (!st.shape) return;
  reel_show('reel-step-mark', true);
  var a = reel_el('reel-audio');
  if (a && st.song && !a.src) {
    a.src = '/api/reel/audio?k=' + encodeURIComponent(SHELL_K) +
            '&path=' + encodeURIComponent(st.song);
  }
  if (!st.marks) st.marks = [];
  reel_renderMarks();
}

/* SNAPPED TO THE GRID, so a tap is a choice of WHICH beat rather than a
   statement about timing. Human tap latency is 50-150ms and would otherwise
   land every kill late. */
function reel_snap(t) {
  var b = (reel_state.shape || {}).beats || [];
  if (!b.length) return t;
  var best = b[0], d = 1e9;
  for (var i = 0; i < b.length; i++) {
    var x = Math.abs(b[i] - t);
    if (x < d) { d = x; best = b[i]; }
  }
  return best;
}

function reel_tap() {
  var a = reel_el('reel-audio'), st = reel_state;
  if (!a || !st.shape) return;
  var t = reel_snap(a.currentTime);
  if ((st.marks || []).some(function (m) { return Math.abs(m - t) < 0.03; })) return;
  st.marks.push(t);
  st.marks.sort(function (p, q) { return p - q; });
  reel_renderMarks();
}

function reel_renderMarks() {
  var st = reel_state, m = st.marks || [];
  reel_el('reel-mark-count').textContent =
    m.length + ' beats marked, ' + reel_chosen().length + ' moments to place';
  /* Every mark listed and removable. A wrong one in the middle of a run used
     to mean Clear and start again, because Undo only drops the last. */
  var chips = reel_el('reel-mark-chips');
  if (chips) {
    chips.innerHTML = m.map(function (t, i) {
      return '<span class="reel-chip" data-mark="' + i +
             '" title="click to remove">' + (i + 1) + ' · ' +
             t.toFixed(3) + 's</span>';
    }).join('');
  }
  /* The gaps decide how the reel is cut, so they are worth seeing. */
  var gaps = reel_el('reel-mark-gaps');
  if (gaps) {
    var g = [];
    for (var i = 1; i < m.length; i++) g.push((m[i] - m[i - 1]).toFixed(2));
    gaps.textContent = g.length ? 'gaps: ' + g.join(', ') + 's' : '';
  }
  reel_drawWave('reel-mark-wave', false);
}

function reel_playPause() {
  var a = reel_el('reel-audio');
  if (a && a.src) { if (a.paused) { a.play(); } else { a.pause(); } }
}

function reel_seek(by) {
  var a = reel_el('reel-audio'), st = reel_state;
  if (!a || !st.shape) return;
  var end = st.shape.seconds || 0;
  a.currentTime = Math.max(0, Math.min(end, (a.currentTime || 0) + by));
}

/* A short tick through the Web Audio API rather than an asset: it has to fire
   on the beat, and a file would have to load and decode first. */
function reel_click() {
  try {
    var C = window.AudioContext || window.webkitAudioContext;
    if (!C) return;
    reel_state.ac = reel_state.ac || new C();
    var ac = reel_state.ac, o = ac.createOscillator(), g = ac.createGain();
    o.frequency.value = 1800;
    g.gain.value = 0.15;
    o.connect(g); g.connect(ac.destination);
    o.start(); o.stop(ac.currentTime + 0.03);
  } catch (e) { /* no audio context, no click; the marks still stand */ }
}

window.PAGE_REEL = {
  quick: reel_quick,
  open: function (rows) {
    reel_loadKills(rows);
    reel_state.open = true;
    reel_show('reel-card', true);
    /* Back to the five-step card, whatever the straight path last hid. */
    reel_quickUI(false);
    reel_show('reel-step-song', true);
    reel_state.source = '';
    reel_renderKills();
    reel_renderSteps();
    reel_wire();
    /* Scrolled here rather than by the caller: the clips view must not reach
       into this one's markup, and where this card sits is its own business. */
    var card = reel_el('reel-card');
    if (card) card.scrollIntoView({behavior: 'smooth', block: 'start'});
  },
  close: function () { reel_state.open = false; reel_show('reel-card', false); },
  onTick: function () {},
  redraw: function () {
    if (!reel_state.open) return;
    reel_drawWave('reel-wave', false);
    reel_drawWave('reel-plan-wave', true);
    reel_drawWave('reel-mark-wave', false);
  }
};

function reel_wire() {
  if (reel_state.wired) return;
  reel_state.wired = true;

  document.addEventListener('change', function (ev) {
    var t = ev.target;
    if (!t || !t.getAttribute) return;
    var i = t.getAttribute('data-reel-kill');
    if (i === null) return;
    var k = reel_state.kills[Number(i)];
    if (k) { k.on = !!t.checked; reel_renderKills(); reel_replan(); }
  });
  ['reel-from', 'reel-to'].forEach(function (id) {
    var e = reel_el(id);
    if (e) e.addEventListener('input', reel_rangeChanged);
  });
  var au = reel_el('reel-audio');
  if (au) au.addEventListener('timeupdate', function () {
    var c = reel_el('reel-mark-clock');
    if (c) c.textContent = au.currentTime.toFixed(3) + 's';
    var metro = reel_el('reel-metro');
    if (metro && metro.checked) {
      var st = reel_state;
      st.ticked = st.ticked || {};
      (st.marks || []).forEach(function (m, i) {
        if (Math.abs(au.currentTime - m) < 0.06 && !st.ticked[i]) {
          st.ticked[i] = 1;
          setTimeout(function () { delete st.ticked[i]; }, 300);
          reel_click();
        }
      });
    }
    reel_drawWave('reel-mark-wave', false);
  });
  if (au) au.addEventListener('seeked', function () {
    reel_drawWave('reel-mark-wave', false);
  });
  /* Click the wave to jump there: scrubbing to one beat through the native
     audio bar means aiming at a few pixels of a whole song. */
  var wave = reel_el('reel-mark-wave');
  if (wave) wave.addEventListener('click', function (ev) {
    var st = reel_state, a = reel_el('reel-audio');
    if (!a || !st.shape) return;
    var r = wave.getBoundingClientRect();
    a.currentTime = Math.max(0, Math.min(st.shape.seconds || 0,
      (ev.clientX - r.left) / r.width * (st.shape.seconds || 0)));
  });
  document.addEventListener('click', function (ev) {
    var c = ev.target.closest ? ev.target.closest('[data-mark]') : null;
    if (!c) return;
    (reel_state.marks || []).splice(Number(c.getAttribute('data-mark')), 1);
    reel_renderMarks();
  });
  document.addEventListener('keydown', function (e) {
    if (!reel_state.open) return;
    var tag = (e.target.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;
    /* Only while the marker is up: Space and the arrows belong to the rest of
       the page the rest of the time. */
    var mark = reel_el('reel-step-mark');
    if (!mark || mark.classList.contains('hide')) return;
    var k = e.key || '';
    if (k === ' ' || e.code === 'Space' || k.toLowerCase() === 'm') {
      e.preventDefault(); reel_tap();
    } else if (k === 'Enter') {
      e.preventDefault(); reel_playPause();
    } else if (k === 'Backspace') {
      e.preventDefault(); (reel_state.marks || []).pop(); reel_renderMarks();
    } else if (k === 'ArrowLeft') {
      e.preventDefault(); reel_seek(e.shiftKey ? -1 : -0.1);
    } else if (k === 'ArrowRight') {
      e.preventDefault(); reel_seek(e.shiftKey ? 1 : 0.1);
    }
  });
  document.addEventListener('click', function (ev) {
    var b = ev.target.closest ? ev.target.closest('[data-act]') : null;
    if (!b) return;
    var act = b.getAttribute('data-act');
    if (act === 'reel-song') reel_pickSong();
    else if (act === 'reel-close') PAGE_REEL.close();
    else if (act === 'reel-tpl') {
      reel_state.template = b.getAttribute('data-val');
      /* A template and hand-marked beats are two answers to one question, and
         the marks were the more deliberate one. Choosing a template clears
         them rather than silently losing to them. */
      reel_state.marks = null;
      reel_renderTemplates(); reel_replan();
    } else if (act === 'reel-all' || act === 'reel-none' || act === 'reel-best') {
      reel_state.kills.forEach(function (k) {
        k.on = act === 'reel-all' ? true
          : act === 'reel-none' ? false
          : ((k.labels || []).length > 0 || k.count > 1);
      });
      reel_renderKills(); reel_replan();
    }
    else if (act === 'reel-build') reel_build();
    else if (act === 'reel-quick-song') reel_quickPick();
    else if (act === 'reel-quick-fix') reel_quickFix();
    else if (act === 'reel-quick-again') reel_quickRender();
    else if (act === 'reel-quick-love') {
      reel_show('reel-quick-fixer', false);
      reel_show('reel-step-part', false);
      reel_show('reel-step-mark', false);
      reel_show('reel-quick-again-bar', false);
      var ask = reel_el('reel-quick-ask');
      if (ask) ask.textContent = 'Saved. It is in your clips folder.';
      toast('Song edit saved.', 'ok');
    }
    else if (act === 'reel-mark') reel_openMark();
    else if (act === 'reel-tap') reel_tap();
    else if (act === 'reel-play') reel_playPause();
    else if (act === 'reel-back') reel_seek(-1);
    else if (act === 'reel-fwd') reel_seek(1);
    else if (act === 'reel-untap') { (reel_state.marks || []).pop(); reel_renderMarks(); }
    else if (act === 'reel-clearmarks') { reel_state.marks = []; reel_renderMarks(); }
    else if (act === 'reel-seedmarks') {
      reel_state.marks = ((reel_state.plan || {}).slots || []).slice();
      reel_renderMarks();
    }
    else if (act === 'reel-usemarks') { reel_show('reel-step-mark', false); reel_replan(); }
    else if (act === 'reel-show') clip_reveal((reel_state.built || {}).path);
    else if (act === 'reel-again') {
      reel_show('reel-step-done', false); reel_show('reel-step-kills', true);
    }
  });
  window.addEventListener('resize', PAGE_REEL.redraw);
}
"""
