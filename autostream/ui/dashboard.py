"""Dashboard page: the one view AutoStream is left open on for an entire session.

WHY THIS PAGE IS SHAPED THE WAY IT IS
    It answers exactly three questions, in this order, from a metre away:
    "am I live?", "is the picture actually getting out?", and "why not?".
    Everything else on the page is secondary, so the hero, the ingest meter and the
    blocked reason are the only things that ever change colour. At the reference
    1120x860 window the left column measures roughly 540px tall, which is why this
    page never scrolls there -- the budget was spent deliberately, not by accident.

WHY THE BLOCKED REASON IS A FIRST-CLASS ELEMENT
    engine.blocked_reason is the single most useful string the daemon produces
    ("opened without streaming", "stopped manually - close the game to reset") and in
    the old UI it was a grey subtitle nobody read. It now renders in --danger directly
    under the game name, never behind a tooltip, because it is the whole answer to the
    only support question this product generates.

WHY ONE SEND BUTTON IS THE PAGE'S ONLY ACCENT
    The accent budget allows one primary button per view. The dashboard has no "go
    live" control -- going live is automatic -- so the single creative action on the
    page, sending a chat message, gets it. End stream is --danger, pause is secondary,
    open-on-YouTube is a ghost. A blue thing here is always a thing you can act on.

WHY RENDERING IS DIFFED RATHER THAN REPAINTED
    onTick runs every 2s for as long as the app is open (hours). Blindly reassigning
    innerHTML on the chat list would reset scroll position twice a second and make the
    pane unusable, so the chat list is keyed on last-message-id plus length, the
    pause button only re-renders when its label flips, and scroll is restored only
    when the reader was already near the bottom.

Exports DASH_HTML (injected into <section id="view-dash">) and DASH_JS (concatenated
into the page's single shared <script>). Every top-level JS name is dash_-prefixed
except the one permitted global, window.PAGE_DASH.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Markup
# ---------------------------------------------------------------------------
# The column split lives in .dash-grid / .dash-main / .dash-side (css.py section 9),
# which becomes "minmax(0,1.45fr) minmax(300px,.8fr)" above 980px and a single column
# below. The classes are load-bearing: without them these are plain blocks with no
# gap, and the whole page paints flush against itself.
# Numeric readouts start as em-dashes (never "-", which reads as a minus sign next
# to real numbers) and the timer starts as --:--:-- so nothing ever paints "undefined"
# during the window between page load and the first poll.

DASH_HTML: str = """
<div class="dash-grid">
<div class="dash-main" id="dash-col-main">

  <section class="status-hero" id="dash-hero" role="status" aria-live="polite">
    <div class="hero-text">
      <span class="pill pill-idle"
            id="dash-pill"><i></i><span id="dash-pill-text">IDLE</span></span>
      <div class="status-phase" id="dash-phase">Idle</div>
      <div class="status-game" id="dash-game">Nothing running</div>
      <div class="field-error hide" id="dash-blocked"></div>
    </div>

    <!-- Countdown ring. Only shown for phases that run against a deadline;
         it is the answer to "is it about to go live, and can I stop it?" -->
    <div class="ring hide" id="dash-ring" role="timer" aria-label="Time remaining in this phase">
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle class="ring-track" cx="60" cy="60" r="52"></circle>
        <circle class="ring-bar" id="dash-ring-bar" cx="60" cy="60" r="52"></circle>
      </svg>
      <div class="ring-face">
        <div class="ring-count mono" id="dash-ring-count">0</div>
        <div class="ring-cap" id="dash-ring-cap">SECONDS</div>
      </div>
    </div>

    <div class="status-timer mono" id="dash-timer" aria-label="Session elapsed">--:--:--</div>
  </section>

  <!-- Cancel bar: appears only while a countdown is running, so the abort
       window is a button rather than a hotkey you have to remember. -->
  <div class="abort-bar hide" id="dash-abort">
    <span class="abort-text" id="dash-abort-text">Going public shortly</span>
    <button type="button" class="btn btn-danger btn-sm" id="dash-btn-abort">
      <span>Cancel</span>
    </button>
  </div>

  <div class="stat-grid" id="dash-stats" role="tablist"
       aria-label="Choose which metric the graph plots">
    <button type="button" class="stat is-sel" id="dash-stat-viewers-btn"
            role="tab" aria-selected="true" data-metric="viewers">
      <div class="stat-label">Watching</div>
      <div class="stat-value mono" id="dash-stat-viewers">&#8212;</div>
      <div class="stat-delta" id="dash-delta-viewers"></div>
    </button>
    <button type="button" class="stat" id="dash-stat-likes-btn"
            role="tab" aria-selected="false" data-metric="likes">
      <div class="stat-label">Likes</div>
      <div class="stat-value mono" id="dash-stat-likes">&#8212;</div>
      <div class="stat-delta" id="dash-delta-likes"></div>
    </button>
    <button type="button" class="stat" id="dash-stat-views-btn"
            role="tab" aria-selected="false" data-metric="views">
      <div class="stat-label">Views</div>
      <div class="stat-value mono" id="dash-stat-views">&#8212;</div>
      <div class="stat-delta" id="dash-delta-views"></div>
    </button>
  </div>

  <section class="card spark-card" id="dash-spark-card">
    <div class="card-head">
      <div>
        <div class="card-title" id="dash-spark-title">Watching</div>
        <div class="card-sub" id="dash-spark-sub">This session</div>
      </div>
      <span class="spark-now mono" id="dash-spark-now">&#8212;</span>
    </div>
    <div class="card-body">
      <canvas class="spark" id="dash-spark" height="96"></canvas>
      <div class="spark-empty" id="dash-spark-empty">Graph starts when you go live.</div>
    </div>
  </section>

  <section class="card" id="dash-ingest">
    <div class="card-head">
      <div>
        <div class="card-title">Ingest</div>
        <div class="card-sub">What OBS is actually pushing</div>
      </div>
      <span class="pill pill-idle"
            id="dash-obs-pill"><i></i><span id="dash-obs-state">OFFLINE</span></span>
    </div>
    <div class="card-body">
      <div class="meter" id="dash-obs-meter" role="progressbar"
           aria-label="Encoder congestion" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
        <div class="meter-fill" id="dash-obs-fill"></div>
      </div>
      <div class="status-meta mono" id="dash-obs-detail">OBS not streaming</div>
    </div>
  </section>

  <section class="card" id="dash-session">
    <div class="card-head">
      <div>
        <div class="card-title">Session</div>
        <div class="card-sub">Today's YouTube API budget</div>
      </div>
    </div>
    <div class="card-body">
      <div class="status-meta" id="dash-session-meta">Session &#8212;</div>
      <div class="meter" id="dash-quota-meter" role="progressbar"
           aria-label="API quota spent" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
        <div class="meter-fill" id="dash-quota-fill"></div>
      </div>
      <div class="status-meta mono" id="dash-quota-note">&#8212; / 10,000 units</div>
    </div>
  </section>

  <div class="controls" id="dash-actions">
    <button type="button" class="btn btn-danger" id="dash-btn-stop" disabled>
      <span>End stream</span>
    </button>
    <button type="button" class="btn" id="dash-btn-pause">
      <span>Pause</span>
    </button>
    <a class="btn btn-ghost hide" id="dash-btn-open"
       href="#" target="_blank" rel="noreferrer noopener">
      <span>Open on YouTube</span>
    </a>
  </div>

</div>

<aside class="dash-side" id="dash-col-side">
  <section class="chat" id="dash-chat">
    <div class="card-head">
      <div>
        <div class="card-title">Live chat</div>
        <div class="card-sub" id="dash-chat-sub">Opens when you go live</div>
      </div>
    </div>
    <div class="chat-msgs" id="dash-chat-msgs" aria-live="polite">
      <div class="chat-empty">Chat opens when you go live.</div>
    </div>
    <div class="chat-row hide" id="dash-chat-row">
      <input class="input" id="dash-chat-input" type="text" maxlength="200"
             autocomplete="off" spellcheck="false" placeholder="Say something">
      <button type="button" class="btn btn-primary" id="dash-chat-send">
        <span>Send</span>
      </button>
    </div>
  </section>
</aside>
</div>
"""


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------
# Raw string: JS \u and regex escapes must survive Python unchanged.

DASH_JS: str = r"""
/* ============================ DASHBOARD ============================ */

/* Phase -> the sentence the user reads. TESTING is YouTube's word for "the
   broadcast exists and is being verified", which means nothing to a streamer, so
   it is shown as "Going live". */
const dash_PHASE_LABEL = {
  IDLE: 'Idle', ARMING: 'Arming', STARTING: 'Starting', TESTING: 'Going live',
  LIVE: 'LIVE', COOLDOWN: 'Cooldown', STOPPING: 'Stopping'
};

/* Phase -> the wordmark on the state pill. Colour is never the only channel, so
   this text is always present beside the dot. */
const dash_PHASE_WORD = {
  IDLE: 'IDLE', ARMING: 'ARMING', STARTING: 'STARTING', TESTING: 'GOING LIVE',
  LIVE: 'LIVE', COOLDOWN: 'COOLDOWN', STOPPING: 'STOPPING'
};

/* Phase -> pill variant, per the design system's state mapping. Transitional
   phases are warn; idle and cooldown are quiet; only LIVE is the tally lamp. */
const dash_PHASE_PILL = {
  IDLE: 'pill-idle', ARMING: 'pill-warn', STARTING: 'pill-warn', TESTING: 'pill-warn',
  LIVE: 'pill-live', COOLDOWN: 'pill-idle', STOPPING: 'pill-warn'
};

/* Phases during which "End stream" is a meaningful thing to press. */
const dash_ACTIVE = ['STARTING', 'TESTING', 'LIVE', 'COOLDOWN'];

const dash_QUOTA_MAX = 10000;
const dash_EMDASH = '—';
const dash_MIDDOT = '·';

/* Ingest is called bad at either of these, matching the operator's intuition:
   a congested encoder queue, or more than 2% of frames never sent. */
const dash_CONGESTION_BAD = 0.3;
const dash_DROP_BAD = 2;

let dash_busy = false;        /* a command is in flight; actions are locked */
let dash_wired = false;       /* listeners attached exactly once */
let dash_last = null;         /* last status, so onShow can repaint without a poll */
let dash_chatKey = '';        /* last-rendered chat identity, to avoid repainting */
let dash_seen = null;         /* message ids already shown; null until first paint */
let dash_pauseState = null;   /* last-rendered pause label, so it only flips on change */

function dash_el(id) {
  return document.getElementById(id);
}

/* icon() is declared by the shell. Guarded because onTick can legitimately fire
   before anything else has run, and a missing glyph must not take the page down. */
function dash_icon(name) {
  try {
    return (typeof icon === 'function') ? icon(name) : '';
  } catch (e) {
    return '';
  }
}

function dash_setLabel(id, iconName, label) {
  const b = dash_el(id);
  if (b) b.innerHTML = dash_icon(iconName) + '<span>' + label + '</span>';
}

function dash_hms(secs) {
  if (secs == null) return '--:--:--';
  let s = Number(secs);
  if (!isFinite(s)) return '--:--:--';
  s = Math.max(0, Math.floor(s));
  const p = n => String(n).padStart(2, '0');
  return p(Math.floor(s / 3600)) + ':' + p(Math.floor((s % 3600) / 60)) + ':' + p(s % 60);
}

/* MB up to a gigabyte, then GB. A recording passes 1 GB in minutes and
   "4823 MB" is a number nobody reads as four and a bit gigabytes. */
function dash_bytes(n) {
  const b = Number(n) || 0;
  const mb = b / (1024 * 1024);
  return mb < 1024 ? mb.toFixed(0) + ' MB' : (mb / 1024).toFixed(1) + ' GB';
}

/* Null is an em-dash, never "-": a hyphen beside real numbers reads as a minus. */
function dash_count(v) {
  if (v == null) return dash_EMDASH;
  const n = Number(v);
  if (!isFinite(n)) return dash_EMDASH;
  if (n >= 1000000) return (n / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
  if (n >= 10000) return Math.round(n / 1000) + 'k';
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
  return String(Math.round(n));
}

function dash_int(v) {
  if (v == null) return null;
  const n = Number(v);
  return isFinite(n) ? Math.round(n) : null;
}

function dash_group(n) {
  return n == null ? dash_EMDASH : n.toLocaleString('en-US');
}

/* ---------------------------------------------------------------- motion ----
   Two hard rules, because this window sits open on a second monitor while a
   game is running and every frame it paints is a frame the GPU is not giving
   the game:
     1. nothing animates when the window is hidden (it lives in the tray), and
     2. nothing animates at all under prefers-reduced-motion.
   Everything below is event-driven - a value changed, a phase changed - and
   there is no always-on ambient loop anywhere on the page. */
const dash_reduce = window.matchMedia
  ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };

function dash_still() {
  return dash_reduce.matches || document.hidden;
}

const dash_ease = t => 1 - Math.pow(1 - t, 3);   /* easeOutCubic */

/* Number roll. Runs only when the value actually changed, and only for a
   change small enough to read - jumping 0 -> 4300 views is snapped, because
   watching four digits spin for 600ms is noise, not information. */
const dash_anim = {};
function dash_rollTo(id, to, fmt) {
  const el = dash_el(id);
  if (!el) return;
  const prev = dash_anim[id];
  if (prev && prev.raf) cancelAnimationFrame(prev.raf);
  const from = prev ? prev.value : null;
  if (to == null) { dash_anim[id] = { value: null }; el.textContent = dash_EMDASH; return; }
  const delta = from == null ? Infinity : Math.abs(to - from);
  if (dash_still() || from == null || delta === 0 || delta > 5000) {
    dash_anim[id] = { value: to };
    el.textContent = fmt(to);
    if (delta !== 0 && from != null) dash_bump(el);
    return;
  }
  const t0 = performance.now(), dur = 520;
  const step = now => {
    const k = Math.min(1, (now - t0) / dur);
    const v = from + (to - from) * dash_ease(k);
    el.textContent = fmt(k >= 1 ? to : v);
    if (k < 1) { dash_anim[id].raf = requestAnimationFrame(step); }
    else { dash_anim[id] = { value: to }; }
  };
  dash_anim[id] = { value: to, raf: requestAnimationFrame(step) };
  dash_bump(el);
}

/* A one-shot scale/colour tick on change. Restarting an animation needs the
   class removed, a reflow read, then re-added - without the reflow the browser
   coalesces both mutations and nothing plays the second time. */
function dash_bump(el) {
  if (!el || dash_still()) return;
  el.classList.remove('is-bump');
  void el.offsetWidth;
  el.classList.add('is-bump');
}

/* Directional delta chip under each stat: +3 since the previous poll. */
function dash_delta(id, from, to) {
  const el = dash_el(id);
  if (!el) return;
  if (from == null || to == null || from === to) { el.textContent = ''; el.className = 'stat-delta'; return; }
  const d = to - from;
  el.textContent = (d > 0 ? '+' : '') + dash_group(d);
  el.className = 'stat-delta ' + (d > 0 ? 'is-up' : 'is-down');
  if (!dash_still()) { el.classList.remove('is-in'); void el.offsetWidth; el.classList.add('is-in'); }
}

function dash_pill(pillId, textId, variant, word) {
  const p = dash_el(pillId);
  if (p) p.className = 'pill ' + variant;
  const t = dash_el(textId);
  if (t) t.textContent = word;
}

/* The class vocabulary has no per-state meter variant, so the fill resolves a
   design token by name. The token names are the contract with theme.py. */
function dash_meter(meterId, fillId, pct, token) {
  const clamped = Math.max(0, Math.min(100, isFinite(pct) ? pct : 0));
  const fill = dash_el(fillId);
  if (fill) {
    fill.style.width = clamped.toFixed(2) + '%';
    fill.style.background = 'var(--' + token + ')';
  }
  const meter = dash_el(meterId);
  if (meter) meter.setAttribute('aria-valuenow', String(Math.round(clamped)));
}

/* ---------------------------- rendering ---------------------------- */

function dash_renderHero(s) {
  const phase = s.phase || 'IDLE';
  const paused = !!s.paused;
  const active = dash_ACTIVE.indexOf(phase) >= 0;
  /* Clips-only mode runs the same phases, and LIVE there means a recording is
     running and nothing is being broadcast. Saying LIVE would be a lie about
     the one thing a streamer most needs to be true. */
  const clipsOnly = s.streaming === false;
  const word = clipsOnly && phase === 'LIVE' ? 'RECORDING'
                                             : (dash_PHASE_WORD[phase] || String(phase));
  const label = clipsOnly && phase === 'LIVE' ? 'Recording'
                                              : (dash_PHASE_LABEL[phase] || String(phase));

  dash_pill('dash-pill', 'dash-pill-text',
            paused ? 'pill-idle' : (dash_PHASE_PILL[phase] || 'pill-idle'),
            paused ? 'PAUSED' : word);

  const head = dash_el('dash-phase');
  if (head) {
    head.textContent = paused ? 'Paused' : label;
    /* Colour only when something is happening; idle stays text-primary so the
       calm default is still the most legible thing on the page. */
    let token = 'text-primary';
    if (!paused && phase === 'LIVE') token = 'live';
    else if (!paused && (phase === 'ARMING' || phase === 'STARTING'
                         || phase === 'TESTING' || phase === 'STOPPING')) token = 'warn';
    head.style.color = 'var(--' + token + ')';
  }

  const game = dash_el('dash-game');
  if (game) game.textContent = s.game || 'Nothing running';

  /* The blocked reason is why a running game is not on air. Only meaningful
     before the broadcast exists; the engine clears it once streaming starts. */
  const why = (!active && s.blocked) ? String(s.blocked) : '';
  const blocked = dash_el('dash-blocked');
  if (blocked) {
    if (why && blocked.textContent !== why) blocked.textContent = why;
    blocked.classList.toggle('hide', !why);
  }

  const timer = dash_el('dash-timer');
  if (timer) timer.textContent = dash_hms(s.elapsed);
}

function dash_renderStats(s) {
  const prev = dash_last || {};
  [['viewers', 'dash-stat-viewers', 'dash-delta-viewers'],
   ['likes',   'dash-stat-likes',   'dash-delta-likes'],
   ['views',   'dash-stat-views',   'dash-delta-views']].forEach(function (row) {
    const key = row[0];
    const to = dash_int(s[key]);
    dash_delta(row[2], dash_int(prev[key]), to);
    dash_rollTo(row[1], to, dash_count);
  });
}

/* ------------------------------------------------------------- countdown ---
   ARMING/STARTING/TESTING/COOLDOWN each run against a deadline the server
   reports as phase_elapsed/phase_total. The ring interpolates between the 2s
   polls so it sweeps smoothly instead of stepping, and it is the ONLY thing on
   the page that animates continuously - which is why it stops the moment the
   phase ends or the window is hidden. */
const dash_RING_LEN = 2 * Math.PI * 52;
const dash_RING_CAP = {
  ARMING: 'UNTIL START', STARTING: 'CONNECTING', TESTING: 'UNTIL PUBLIC', COOLDOWN: 'UNTIL STOP'
};
let dash_ring = null;   /* {phase, total, base, at} */
let dash_ringRaf = 0;

function dash_ringStop() {
  if (dash_ringRaf) { cancelAnimationFrame(dash_ringRaf); dash_ringRaf = 0; }
}

function dash_ringPaint() {
  const r = dash_ring;
  if (!r) return;
  const now = performance.now();
  const elapsed = r.base + (dash_still() ? 0 : (now - r.at) / 1000);
  const left = Math.max(0, r.total - elapsed);
  const frac = Math.max(0, Math.min(1, left / r.total));

  const bar = dash_el('dash-ring-bar');
  if (bar) {
    bar.style.strokeDasharray = dash_RING_LEN;
    bar.style.strokeDashoffset = (dash_RING_LEN * (1 - frac)).toFixed(2);
  }
  const c = dash_el('dash-ring-count');
  if (c) c.textContent = String(Math.ceil(left));
  const ring = dash_el('dash-ring');
  /* Under 5s the ring turns danger-coloured and starts breathing: this is the
     last moment to cancel before the stream is public. */
  if (ring) ring.classList.toggle('is-urgent', left <= 5 && r.phase === 'TESTING');

  if (!dash_still() && left > 0) dash_ringRaf = requestAnimationFrame(dash_ringPaint);
  else dash_ringStop();
}

function dash_renderRing(s) {
  const ring = dash_el('dash-ring');
  const bar = dash_el('dash-abort');
  const total = Number(s.phase_total);
  const el = Number(s.phase_elapsed);
  const on = isFinite(total) && total > 0 && isFinite(el) && dash_RING_CAP[s.phase] && !s.paused;

  if (!on) {
    dash_ringStop(); dash_ring = null;
    if (ring) { ring.classList.add('hide'); ring.classList.remove('is-urgent'); }
    if (bar) bar.classList.add('hide');
    return;
  }
  dash_ring = { phase: s.phase, total: total, base: el, at: performance.now() };
  if (ring) ring.classList.remove('hide');
  const cap = dash_el('dash-ring-cap');
  if (cap) cap.textContent = dash_RING_CAP[s.phase];

  /* Cancel is only meaningful while something can still be stopped. */
  const abortable = s.phase === 'ARMING' || s.phase === 'STARTING' || s.phase === 'TESTING';
  if (bar) {
    bar.classList.toggle('hide', !abortable);
    bar.classList.toggle('is-hot', s.phase === 'TESTING');
    const txt = dash_el('dash-abort-text');
    if (txt) {
      txt.textContent = s.phase === 'TESTING'
        ? 'This goes PUBLIC when the ring runs out'
        : (s.phase === 'ARMING' ? 'Getting ready to stream ' + (s.game || 'this game')
                                : 'Waiting for YouTube to receive video');
    }
  }
  dash_ringStop();
  dash_ringPaint();
}

/* -------------------------------------------------------------- sparkline ---
   A real plot of the session, drawn on canvas so 300 points cost nothing.
   Redrawn only when a new sample arrives or the metric is switched. */
const dash_SPARK_MAX = 240;
const dash_series = { viewers: [], likes: [], views: [] };
let dash_metric = 'viewers';

function dash_sparkPush(s) {
  let added = false;
  ['viewers', 'likes', 'views'].forEach(function (k) {
    const v = dash_int(s[k]);
    if (v == null) return;
    const arr = dash_series[k];
    if (arr.length && arr[arr.length - 1] === v) return;   /* flat: no new shape */
    arr.push(v);
    if (arr.length > dash_SPARK_MAX) arr.shift();
    added = true;
  });
  return added;
}

function dash_sparkDraw() {
  const cv = dash_el('dash-spark');
  const empty = dash_el('dash-spark-empty');
  if (!cv) return;
  const data = dash_series[dash_metric] || [];
  if (empty) empty.classList.toggle('hide', data.length > 1);
  cv.classList.toggle('hide', data.length <= 1);
  if (data.length <= 1) return;

  const css = getComputedStyle(document.documentElement);
  const tok = n => (css.getPropertyValue('--' + n) || '').trim() || '#888';
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = cv.clientWidth || 480, h = cv.clientHeight || 96;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  }
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);

  const pad = 6;
  let lo = Math.min.apply(null, data), hi = Math.max.apply(null, data);
  if (hi === lo) { hi = lo + 1; }
  const x = i => pad + (i / (data.length - 1)) * (w - pad * 2);
  const y = v => h - pad - ((v - lo) / (hi - lo)) * (h - pad * 2);

  /* baseline grid */
  g.strokeStyle = tok('border-subtle'); g.lineWidth = 1;
  g.beginPath(); g.moveTo(0, h - pad + .5); g.lineTo(w, h - pad + .5); g.stroke();

  const accent = tok('accent');
  /* area fill under the line, so a thin line still reads as a quantity */
  const grad = g.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, accent + '55');
  grad.addColorStop(1, accent + '00');
  g.beginPath(); g.moveTo(x(0), y(data[0]));
  for (let i = 1; i < data.length; i++) g.lineTo(x(i), y(data[i]));
  g.lineTo(x(data.length - 1), h - pad); g.lineTo(x(0), h - pad); g.closePath();
  g.fillStyle = grad; g.fill();

  g.beginPath(); g.moveTo(x(0), y(data[0]));
  for (let i = 1; i < data.length; i++) g.lineTo(x(i), y(data[i]));
  g.strokeStyle = accent; g.lineWidth = 2; g.lineJoin = 'round'; g.lineCap = 'round';
  g.stroke();

  /* emphasised endpoint - "where it is now" is the point people look for */
  const ex = x(data.length - 1), ey = y(data[data.length - 1]);
  g.beginPath(); g.arc(ex, ey, 5.5, 0, Math.PI * 2);
  g.fillStyle = accent + '33'; g.fill();
  g.beginPath(); g.arc(ex, ey, 2.8, 0, Math.PI * 2);
  g.fillStyle = accent; g.fill();
}

function dash_setMetric(m) {
  if (!dash_series[m]) return;
  dash_metric = m;
  ['viewers', 'likes', 'views'].forEach(function (k) {
    const b = dash_el('dash-stat-' + k + '-btn');
    if (b) { b.classList.toggle('is-sel', k === m); b.setAttribute('aria-selected', k === m); }
  });
  const title = dash_el('dash-spark-title');
  if (title) title.textContent = { viewers: 'Watching', likes: 'Likes', views: 'Views' }[m];
  dash_sparkDraw();
}

function dash_renderSpark(s) {
  if (dash_sparkPush(s)) dash_sparkDraw();
  const now = dash_el('dash-spark-now');
  if (now) now.textContent = dash_count(s[dash_metric]);
}

function dash_renderIngest(s) {
  const obs = s.obs || {};
  const detail = dash_el('dash-obs-detail');

  /* Clips-only has no ingest to report, and a panel stuck on OFFLINE all
     session says nothing. Report the RECORDING instead -- which is also the
     only place a paused recording becomes visible, since the file keeps its
     size and the phase stays LIVE. */
  if (s.streaming === false) {
    const rec = !!obs.recording, held = !!obs.rec_paused;
    dash_pill('dash-obs-pill', 'dash-obs-state',
              !rec ? 'pill-idle' : (held ? 'pill-warn' : 'pill-ok'),
              !rec ? 'OFFLINE' : (held ? 'PAUSED' : 'RECORDING'));
    dash_meter('dash-obs-meter', 'dash-obs-fill', rec && !held ? 100 : 0,
               held ? 'warn' : 'ok');
    if (detail) {
      detail.textContent = rec
        ? dash_hms(Math.floor((Number(obs.rec_ms) || 0) / 1000))
          + ' ' + dash_MIDDOT + ' ' + dash_bytes(obs.rec_bytes)
          + (held ? ' ' + dash_MIDDOT + ' paused' : '')
        : 'Not recording';
    }
    return;
  }

  if (!obs.active) {
    /* An empty meter beside no words looks like a broken widget. Say the words. */
    dash_pill('dash-obs-pill', 'dash-obs-state', 'pill-idle', 'OFFLINE');
    dash_meter('dash-obs-meter', 'dash-obs-fill', 0, 'idle');
    if (detail) detail.textContent = 'OBS not streaming';
    return;
  }

  const total = Number(obs.total) || 0;
  const skipped = Number(obs.skipped) || 0;
  const drop = total > 0 ? (skipped / total * 100) : 0;
  const cong = Math.max(0, Math.min(1, Number(obs.congestion) || 0));
  const bad = cong > dash_CONGESTION_BAD || drop > dash_DROP_BAD;

  dash_pill('dash-obs-pill', 'dash-obs-state',
            bad ? 'pill-warn' : 'pill-ok', bad ? 'CONGESTED' : 'HEALTHY');
  /* The meter reads as congestion, so empty is unambiguously good. */
  dash_meter('dash-obs-meter', 'dash-obs-fill', cong * 100, bad ? 'warn' : 'ok');
  if (detail) {
    detail.textContent = 'Congestion ' + Math.round(cong * 100) + '% '
      + dash_MIDDOT + ' ' + drop.toFixed(1) + '% frames dropped';
  }
}

function dash_renderSession(s) {
  const n = dash_int(s.session);
  const meta = dash_el('dash-session-meta');
  if (meta) meta.textContent = 'Session ' + (n == null ? dash_EMDASH : '#' + n);

  const spent = dash_int(s.quota_spent);
  const pct = spent == null ? 0 : (spent / dash_QUOTA_MAX * 100);
  let token = 'ok';
  if (spent != null && spent > 9800) token = 'danger';
  else if (spent != null && spent > 9500) token = 'warn';
  dash_meter('dash-quota-meter', 'dash-quota-fill', pct, token);

  const note = dash_el('dash-quota-note');
  if (note) {
    note.textContent = dash_group(spent) + ' / ' + dash_group(dash_QUOTA_MAX) + ' units';
  }
}

/* null so the first paint always writes a label, whichever mode it is in. */
let dash_stopClipsOnly = null;

function dash_applyActions(s) {
  s = s || {};
  const phase = s.phase || 'IDLE';
  const paused = !!s.paused;
  const active = dash_ACTIVE.indexOf(phase) >= 0;

  const stop = dash_el('dash-btn-stop');
  if (stop) stop.disabled = dash_busy || !active;

  const pause = dash_el('dash-btn-pause');
  if (pause) {
    pause.disabled = dash_busy;
    if (dash_pauseState !== paused) {
      dash_pauseState = paused;
      dash_setLabel('dash-btn-pause', paused ? 'resume' : 'pause',
                    paused ? 'Resume' : 'Pause');
    }
  }

  /* Everything about a broadcast goes away when there is no broadcast: the
     viewer/like counters and the chat column describe something that does not
     exist in clips-only mode. The STOP BUTTON STAYS -- a recording still has
     to be stoppable -- but it cannot go on calling itself "End stream". */
  const clipsOnly = s.streaming === false;
  ['dash-stats', 'dash-chat'].forEach(function (id) {
    const el = dash_el(id);
    if (el) el.classList.toggle('hide', clipsOnly);
  });

  /* Guarded like the pause label: dash_setLabel rebuilds innerHTML, and doing
     that every two-second poll would fight the browser for no reason. */
  if (dash_stopClipsOnly !== clipsOnly) {
    dash_stopClipsOnly = clipsOnly;
    dash_setLabel('dash-btn-stop', 'stop',
                  clipsOnly ? 'Stop recording' : 'End stream');
  }

  const open = dash_el('dash-btn-open');
  if (open) {
    const url = s.url || '';
    open.classList.toggle('hide', !url);
    if (url && open.getAttribute('href') !== url) open.setAttribute('href', url);
  }
}

/* Chat is the one list on the page that a repaint would visibly damage, so it is
   keyed on (last message id, length) exactly as the old dashboard was, and scroll
   is only pinned to the bottom when the reader was already there. */
function dash_renderChat(s) {
  const phase = s.phase || 'IDLE';
  const live = dash_ACTIVE.indexOf(phase) >= 0 && !s.paused;
  const box = dash_el('dash-chat-msgs');
  const row = dash_el('dash-chat-row');
  const sub = dash_el('dash-chat-sub');
  if (!box) return;

  if (row) row.classList.toggle('hide', !live);

  if (!live) {
    if (sub) sub.textContent = 'Opens when you go live';
    if (dash_chatKey !== 'off') {
      dash_chatKey = 'off';
      /* Re-seed on the next live session, so returning to LIVE does not
         replay an entrance for every message in the backlog. */
      dash_seen = null;
      box.innerHTML = '<div class="chat-empty">Chat opens when you go live.</div>';
    }
    return;
  }

  const msgs = s.chat || [];
  if (sub) sub.textContent = msgs.length + (msgs.length === 1 ? ' message' : ' messages');

  const key = msgs.length
    ? (String(msgs[msgs.length - 1].id) + ':' + msgs.length)
    : 'live-empty';
  if (key === dash_chatKey) return;
  dash_chatKey = key;

  if (!msgs.length) {
    box.innerHTML = '<div class="chat-empty">No messages yet. Say hello.</div>';
    return;
  }

  const near = (box.scrollHeight - box.scrollTop - box.clientHeight) < 60;

  /* The list is re-rendered wholesale, so "new" has to be tracked by id or
     every message would replay its entrance on every poll. The first paint
     seeds the set silently - going live with 40 backlogged messages should
     not fire 40 animations at once. */
  const first = dash_seen === null;
  if (first) dash_seen = new Set();
  const fresh = new Set();
  msgs.forEach(function (m) {
    const id = String(m && m.id);
    if (!first && !dash_seen.has(id)) fresh.add(id);
    dash_seen.add(id);
  });
  if (dash_seen.size > 400) dash_seen = new Set(msgs.map(m => String(m && m.id)));

  box.innerHTML = msgs.map(function (m) {
    return dash_chatMsg(m, !dash_still() && fresh.has(String(m && m.id)));
  }).join('');
  if (near) box.scrollTop = box.scrollHeight;
}

function dash_chatMsg(m, isNew) {
  m = m || {};
  let badge = '';
  if (m.owner) badge = '<span class="tag">HOST</span>';
  else if (m.mod) badge = '<span class="tag">MOD</span>';
  return '<div class="chat-msg' + (isNew ? ' is-new' : '') + '">'
    + '<span class="chat-author">' + esc(m.author) + '</span>'
    + badge
    + '<span>' + esc(m.text) + '</span>'
    + '</div>';
}

/* ---------------------------- actions ---------------------------- */

async function dash_cmd(command) {
  if (dash_busy) return;
  dash_busy = true;
  dash_applyActions(dash_last);           /* lock immediately, before the round trip */
  try {
    const r = await API.post('/api/cmd', { command: command });
    if (r && r.error) throw new Error(r.error);
  } catch (e) {
    toast('That command did not go through.', 'error');
  }
  /* The engine applies commands on its own thread; hold the lock until the next
     poll can plausibly reflect the new phase, so a double-click cannot double-fire. */
  window.setTimeout(function () {
    dash_busy = false;
    dash_applyActions(dash_last);
  }, 700);
}

async function dash_send() {
  const input = dash_el('dash-chat-input');
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;
  const btn = dash_el('dash-chat-send');

  input.value = '';
  input.disabled = true;
  if (btn) btn.disabled = true;
  try {
    const r = await API.post('/api/chat', { text: text });
    if (r && r.error) throw new Error(r.error);
  } catch (e) {
    input.value = text;                   /* never silently eat what was typed */
    toast('Could not send that message.', 'error');
  }
  input.disabled = false;
  if (btn) btn.disabled = false;
  input.focus();
}

/* ---------------------------- wiring ---------------------------- */

function dash_wire() {
  if (dash_wired) return;
  dash_wired = true;

  dash_setLabel('dash-btn-stop', 'stop', 'End stream');
  dash_setLabel('dash-btn-pause', 'pause', 'Pause');
  dash_setLabel('dash-btn-open', 'external', 'Open on YouTube');
  dash_setLabel('dash-chat-send', 'chevron-right', 'Send');

  const stop = dash_el('dash-btn-stop');
  if (stop) stop.addEventListener('click', function () { dash_cmd('stop'); });

  const pause = dash_el('dash-btn-pause');
  if (pause) {
    pause.addEventListener('click', function () {
      dash_cmd(dash_pauseState ? 'resume' : 'pause');
    });
  }

  const send = dash_el('dash-chat-send');
  if (send) send.addEventListener('click', function () { dash_send(); });

  const input = dash_el('dash-chat-input');
  if (input) {
    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' && !ev.shiftKey) {
        ev.preventDefault();
        dash_send();
      }
    });
  }

  /* Stat tiles double as the graph's metric picker. */
  ['viewers', 'likes', 'views'].forEach(function (k) {
    const b = dash_el('dash-stat-' + k + '-btn');
    if (b) b.addEventListener('click', function () { dash_setMetric(k); });
  });

  /* Cancel during the countdown. TESTING is the one that matters - it is the
     last moment before the broadcast is public - so it confirms nothing and
     acts immediately; hesitating is the whole failure mode. */
  const abort = dash_el('dash-btn-abort');
  if (abort) {
    abort.addEventListener('click', function () {
      dash_cmd(dash_last && dash_last.phase === 'ARMING' ? 'pause' : 'stop');
    });
  }

  /* Canvas has no intrinsic reflow: it must be told to redraw. */
  let rs = 0;
  window.addEventListener('resize', function () {
    clearTimeout(rs);
    rs = setTimeout(dash_sparkDraw, 120);
  });

  /* Closing the window to the tray must stop the ring; reopening resumes it
     from the server's clock on the next poll rather than from a stale base. */
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { dash_ringStop(); }
    else if (dash_last) { dash_renderRing(dash_last); dash_sparkDraw(); }
  });
}

function dash_onShow() {
  dash_wire();
  if (dash_last) dash_onTick(dash_last);
  const box = dash_el('dash-chat-msgs');
  if (box) box.scrollTop = box.scrollHeight;
}

function dash_onTick(status) {
  dash_wire();
  const s = status || {};
  /* dash_last is still the PREVIOUS poll here: dash_renderStats diffs against
     it to draw the +N chips, so the assignment has to come last. */
  dash_renderHero(s);
  dash_renderStats(s);
  dash_renderIngest(s);
  dash_renderSession(s);
  dash_renderRing(s);
  dash_renderSpark(s);
  dash_applyActions(s);
  dash_renderChat(s);
  dash_last = s;
}

window.PAGE_DASH = { onShow: dash_onShow, onTick: dash_onTick };
"""
