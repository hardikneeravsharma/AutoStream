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

  <p class="field-warn hide" id="dash-disk" role="status" aria-live="polite"></p>

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

  <!-- INSTANT REPLAY. The frames are already in memory, so this is the one
       thing on the page that produces a clip with no scan and no wait -- and
       it works in a game AutoStream cannot read a word of.

       Beside the graph strip rather than in it: the three above are series
       the graph can draw and this is not one, so putting it in the same
       tablist would offer a tab that draws nothing. -->
  <section class="card replay-card hide" id="dash-replay">
    <div class="card-head">
      <div>
        <div class="card-title">Instant replay</div>
        <div class="card-sub" id="dash-replay-sub">The last few seconds, kept</div>
      </div>
      <span class="pill pill-idle" id="dash-replay-pill"><i></i><span
            id="dash-replay-state">OFF</span></span>
    </div>
    <div class="card-body">
      <div class="replay-row">
        <button type="button" class="btn btn-primary" id="dash-btn-replay"
                data-act="dash-save-replay">
          <span>Save the last 30 seconds</span>
        </button>
        <span class="status-meta" id="dash-replay-note"></span>
      </div>
    </div>
  </section>

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

  <!-- Only during a live VALORANT session. Fetching the match record used to
       be visible in the log and nowhere else, so a player had no way to know
       AutoStream was reading their Riot Client -- or that it had failed to and
       the clips would be cut from the screen after all. -->
  <section class="card hide" id="dash-vmatch">
    <div class="card-head">
      <div>
        <div class="card-title">VALORANT match record</div>
        <div class="card-sub">Kills, rounds and clutches for your clips</div>
      </div>
      <span class="pill pill-idle"
            id="dash-vmatch-pill"><i></i><span id="dash-vmatch-state">WAITING</span></span>
    </div>
    <div class="card-body">
      <div class="status-meta" id="dash-vmatch-detail"></div>
      <div class="panel hide" id="dash-vmatch-explain" style="margin-top:8px">
        <p class="muted" style="margin:0 0 8px">
          While you play, AutoStream asks the Riot Client on this PC for the
          record of each match you finish, and keeps it next to your
          recordings. Clips then take their kills, rounds and clutches from
          the game instead of reading them off the screen. The request goes
          only to Riot, using the sign-in the Riot Client already has; nothing
          is sent anywhere else, and nothing is needed from you.
        </p>
        <button type="button" class="btn btn-sm" id="dash-vmatch-ok">Got it</button>
      </div>
    </div>
  </section>

  <!-- WHERE YOU GO LIVE. This lived only in Settings, three clicks and a
       scroll away, which made the one thing you want to check before pressing
       go the hardest thing on the page to find. It is a setting, but it is
       the setting you change most often and the one whose value you most want
       to see without changing anything -- so it reads as a row you can
       confirm at a glance and change in one click.

       Locked while a session is running: switching platform mid-broadcast
       would leave the stream going on one service and the engine talking to
       another. -->
  <section class="card" id="dash-where">
    <div class="card-head">
      <div>
        <div class="card-title">Where you go live</div>
        <div class="card-sub" id="dash-where-sub">Pick a platform before you start</div>
      </div>
    </div>
    <div class="card-body">
      <div class="seg" id="dash-where-seg" role="radiogroup"
           aria-label="Streaming platform">
        <button type="button" class="seg-btn" role="radio" aria-checked="false"
                data-act="dash-where-platform"
                data-platform="youtube"><span>YouTube</span></button>
        <button type="button" class="seg-btn" role="radio" aria-checked="false"
                data-act="dash-where-platform"
                data-platform="twitch"><span>Twitch</span></button>
        <button type="button" class="seg-btn" role="radio" aria-checked="false"
                data-act="dash-where-platform"
                data-platform="kick"><span>Kick</span></button>
      </div>
      <p class="field-help" id="dash-where-note"></p>
    </div>
  </section>

  <section class="card" id="dash-session">
    <div class="card-head">
      <div>
        <div class="card-title">Session</div>
        <div class="card-sub" id="dash-session-sub">Today's YouTube API budget</div>
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
    <button type="button" class="btn" id="dash-btn-record">
      <span>Stop recording</span>
    </button>
    <a class="btn btn-ghost hide" id="dash-btn-open"
       href="#" target="_blank" rel="noreferrer noopener">
      <span>Open stream</span>
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

  <!-- The two OBS mixer settings a streamer reaches for mid-session: which
       microphone, and how loud it sits against the game. Beside the chat
       rather than in the main column, whose height budget is already spent,
       and it stays in clips-only mode where the chat goes away. -->
  <section class="card" id="dash-audio">
    <div class="card-head">
      <div>
        <div class="card-title">Audio</div>
        <div class="card-sub" id="dash-audio-sub">Microphone and desktop, as OBS mixes them</div>
      </div>
      <button type="button" class="btn btn-icon btn-ghost btn-sm" id="dash-audio-refresh"
              title="Read the mixer from OBS again" aria-label="Refresh audio"></button>
    </div>
    <div class="card-body">
      <div class="field">
        <label class="field-help" for="dash-audio-device">Input device</label>
        <select class="select" id="dash-audio-device" disabled></select>
      </div>
      <div class="dash-fader">
        <label class="field-help" for="dash-audio-mic">Mic</label>
        <input type="range" id="dash-audio-mic" min="-60" max="0" step="0.5" disabled>
        <span class="mono dash-fader-db" id="dash-audio-mic-db">&#8212;</span>
        <button type="button" class="chip" id="dash-audio-mic-mute"
                aria-pressed="false" disabled>Mute</button>
      </div>
      <div class="dash-fader">
        <label class="field-help" for="dash-audio-desktop">Desktop</label>
        <input type="range" id="dash-audio-desktop" min="-60" max="0" step="0.5" disabled>
        <span class="mono dash-fader-db" id="dash-audio-desktop-db">&#8212;</span>
        <button type="button" class="chip" id="dash-audio-desktop-mute"
                aria-pressed="false" disabled>Mute</button>
      </div>
      <div class="status-meta" id="dash-audio-balance"></div>
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
        ? (s.privacy && s.privacy !== 'public'
            ? 'This goes live (' + s.privacy + ') when the ring runs out'
            : 'This goes PUBLIC when the ring runs out')
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

/* The match-record card: whether the Riot Client is being read, what it has
   given this session, and -- once, until "Got it" -- what that means. */
function dash_renderVMatch(s) {
  const v = s.valorant;
  const card = dash_el('dash-vmatch');
  if (!card) return;
  card.classList.toggle('hide', !v);
  if (!v) return;
  const n = Number(v.saved_count) || 0;
  let variant = 'pill-idle', word = 'WAITING', text;
  if (!v.checked) {
    text = 'Checking the Riot Client...';
  } else if (!v.ok && !n) {
    variant = 'pill-warn'; word = 'NOT READ';
    text = 'Could not read the match record: ' + (v.why || 'unknown reason')
      + '. Clips will be cut from the screen instead.';
  } else if (n) {
    variant = 'pill-ok'; word = 'SAVED';
    const last = (v.saved || [])[(v.saved || []).length - 1] || {};
    text = n + (n === 1 ? ' match' : ' matches') + ' saved this session'
      + (last.minutes ? ' ' + dash_MIDDOT + ' last one ' + last.minutes + ' min' : '')
      + (v.why ? ' ' + dash_MIDDOT + ' ' + v.why : '');
  } else {
    variant = 'pill-ok'; word = 'CONNECTED';
    text = 'Connected to the Riot Client. Each match is saved a minute or two '
      + 'after it ends.';
  }
  dash_pill('dash-vmatch-pill', 'dash-vmatch-state', variant, word);
  const d = dash_el('dash-vmatch-detail');
  if (d) d.textContent = text;
  const ex = dash_el('dash-vmatch-explain');
  if (ex) ex.classList.toggle('hide', !!v.explained);
}

async function dash_vmatchExplained() {
  const ex = dash_el('dash-vmatch-explain');
  if (ex) ex.classList.add('hide');
  if (dash_last && dash_last.valorant) dash_last.valorant.explained = true;
  try { await API.post('/api/clips/valorant/explained', {}); }
  catch (e) { /* hidden for this page either way */ }
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

/* ----------------------------- instant replay --------------------------

   The frames are already in OBS's memory, so pressing this is a request and
   a filename back -- no scan, no wait, and no detector, which is why it is
   the one clip feature that works in every game.

   WHAT THE PILL IS FOR. "On" in the config and not actually running in OBS is
   the whole failure mode here: OBS refuses to hold a buffer unless it is
   switched on in its own Output settings, and without this readout the only
   sign was a hotkey that did nothing. So the pill reports what OBS is doing,
   not what the config says. */

let dash_replayState = null;
let dash_replayBusy = false;

function dash_renderReplay(s) {
  const card = dash_el('dash-replay');
  if (!card) return;
  const on = !!s.replay_enabled;
  card.classList.toggle('hide', !on);
  if (!on) { dash_replayState = null; return; }

  const armed = !!s.replay_armed;
  const saved = dash_int(s.replay_saved) || 0;
  const secs = dash_int(s.replay_seconds) || 30;

  const btn = dash_el('dash-btn-replay');
  if (btn) btn.disabled = dash_replayBusy || !armed;

  const key = armed + '|' + saved + '|' + secs + '|' + (s.replay_last || '') +
              '|' + dash_replayBusy;
  if (dash_replayState === key) return;
  dash_replayState = key;

  dash_pill('dash-replay-pill', 'dash-replay-state',
            armed ? 'live' : 'warn', armed ? 'READY' : 'NOT RUNNING');

  const label = btn ? btn.querySelector('span') : null;
  if (label) label.textContent = 'Save the last ' + secs + ' seconds';

  const sub = dash_el('dash-replay-sub');
  if (sub) sub.textContent = armed
    ? 'The last ' + secs + ' seconds, kept in memory'
    : 'Waiting for OBS to start the buffer';

  const note = dash_el('dash-replay-note');
  if (note) {
    if (!armed) {
      /* NAMES THE SETTING, because this is almost always one switch in OBS
         rather than anything wrong. */
      note.textContent = 'OBS is not holding a buffer. Turn on Replay Buffer ' +
        'under Settings → Output in OBS, then start a session.';
    } else if (!saved) {
      note.textContent = 'Nothing saved yet this session.';
    } else {
      note.textContent = (saved === 1 ? '1 replay' : saved + ' replays') +
        ' saved' + (s.replay_last ? ' — last: ' + s.replay_last : '');
    }
  }
}

async function dash_saveReplay() {
  if (dash_replayBusy) return;
  dash_replayBusy = true;
  dash_replayState = null;
  dash_renderReplay(dash_last || {});
  try {
    const r = await API.post('/api/cmd', { command: 'replay' });
    if (r && r.error) throw new Error(r.error);
    toast('Saving that moment...', 'ok');
  } catch (e) {
    toast('Could not save a replay.', 'error');
  }
  /* The engine saves on its own thread and OBS takes a moment to mux, so the
     count arrives on a later poll rather than from this response. */
  window.setTimeout(function () {
    dash_replayBusy = false;
    dash_replayState = null;
    dash_renderReplay(dash_last || {});
  }, 1500);
}

/* ----------------------------- where you go live -----------------------

   The same key the Settings page edits (`youtube.platform`), saved through
   the same endpoint, so there is one validator and no second way for this
   value to become something the engine cannot read.

   LOCKED WHILE LIVE. Switching platform during a session would leave OBS
   pushing to one service while the engine retitled a broadcast on another,
   and the symptom -- a stream that is up but that AutoStream has stopped
   describing -- is hard to connect back to a button press. */

let dash_platform = null;       /* what the page is showing right now */
let dash_platformBusy = false;

function dash_renderWhere(s) {
  const now = s.platform || 'youtube';
  const live = dash_ACTIVE.indexOf(s.phase || 'IDLE') >= 0;

  const seg = dash_el('dash-where-seg');
  if (seg) {
    const btns = seg.querySelectorAll('.seg-btn');
    for (let i = 0; i < btns.length; i++) {
      const mine = btns[i].getAttribute('data-platform') === now;
      btns[i].classList.toggle('is-active', mine);
      btns[i].setAttribute('aria-checked', mine ? 'true' : 'false');
      btns[i].disabled = dash_platformBusy || live;
    }
  }

  /* Rewritten only when something changed: this runs on every two-second
     poll and the note is read, not watched. */
  const key = now + '|' + live + '|' + !!s.streaming + '|' +
              (s.platform_ready === false) + '|' + (s.platform_why || '') +
              '|' + (s.signin_why || '');
  if (dash_platform === key) return;
  dash_platform = key;

  const note = dash_el('dash-where-note');
  if (note) {
    /* WHAT WOULD STOP IT, FIRST. A platform that cannot go live is worth
       saying before a game starts; the alternative is finding out from a
       toast after one does, with the session already abandoned. */
    if (s.streaming === false) {
      note.textContent = 'Going live is switched off, so this install only ' +
        'records and cuts clips. Turn it on under Settings → Stream.';
    } else if (live) {
      note.textContent = 'Locked while a session is running. End the stream ' +
        'to switch platform.';
    } else if (s.platform_ready === false) {
      note.textContent = s.platform_why ||
        ((s.platform_label || now) + ' is not set up yet.');
    } else if (s.signin_warn) {
      /* IT CAN GO LIVE TODAY AND MAY NOT TOMORROW. A Google app left in
         Testing issues sign-ins that die at about seven days, and the symptom
         is streaming that silently stops working days after a setup that went
         perfectly. Said while the fix is still one button. */
      note.textContent = s.signin_why;
    } else if (now === 'youtube') {
      note.textContent = 'YouTube holds the broadcast in a private preview ' +
        'first, so there is a countdown you can still cancel in.';
    } else {
      note.textContent = (s.platform_label || now) + ' is live the moment ' +
        'the stream reaches it — there is no countdown and nothing to ' +
        'cancel.' + (s.platform_why ? ' ' + s.platform_why : '');
    }
    note.classList.toggle('field-error', s.platform_ready === false);
    note.classList.toggle('field-warn',
      s.platform_ready !== false && !!s.signin_warn);
  }

  const sub = dash_el('dash-where-sub');
  if (sub) {
    sub.textContent = live
      ? 'Streaming to ' + (s.platform_label || now)
      : 'Pick a platform before you start';
  }
}

async function dash_setPlatform(name) {
  if (!name || dash_platformBusy) return;
  if (dash_last && (dash_last.platform || 'youtube') === name) return;
  dash_platformBusy = true;
  dash_platform = null;                  /* force the note to be rewritten */
  dash_renderWhere(dash_last || {});
  try {
    const body = {};
    body['youtube.platform'] = name;
    const r = await API.post('/api/settings/save', { values: body });
    if (r && r.errors && r.errors['youtube.platform']) {
      throw new Error(r.errors['youtube.platform']);
    }
    if (r && r.error) throw new Error(r.error);
    /* Paint it now rather than waiting up to two seconds for the next poll:
       a segmented control that does not move when pressed reads as broken. */
    if (dash_last) {
      dash_last.platform = name;
      const seg = dash_el('dash-where-seg');
      const btn = seg ? seg.querySelector('[data-platform="' + name + '"]') : null;
      dash_last.platform_label = btn ? btn.textContent.trim() : name;
    }
    toast('Going live on ' + ((dash_last && dash_last.platform_label) || name) +
          ' from the next session.', 'ok');
  } catch (e) {
    toast('Could not switch platform. ' + (e.message || ''), 'error');
  }
  dash_platformBusy = false;
  dash_platform = null;
  dash_renderWhere(dash_last || {});
}

/* null so the first paint always writes a label, whichever mode it is in. */
let dash_stopClipsOnly = null;
let dash_recState = null;

function dash_applyActions(s) {
  s = s || {};
  const phase = s.phase || 'IDLE';
  const paused = !!s.paused;
  const active = dash_ACTIVE.indexOf(phase) >= 0;

  const stop = dash_el('dash-btn-stop');
  if (stop) stop.disabled = dash_busy || !active;

  /* Three failed starts hold every game back just as a pause does, and
     Resume is what clears it -- so the button offers Resume for either. */
  const held = paused || !!s.start_blocked;
  const pause = dash_el('dash-btn-pause');
  if (pause) {
    pause.disabled = dash_busy;
    if (dash_pauseState !== held) {
      dash_pauseState = held;
      dash_setLabel('dash-btn-pause', held ? 'resume' : 'pause',
                    held ? 'Resume' : 'Pause');
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
  /* The API budget belongs to YouTube. With YouTube off nothing spends it,
     and on Twitch or Kick there is no budget to spend -- a meter reading
     "0 / 10,000 units" on a Twitch stream is describing another service. */
  const quota = dash_el('dash-session');
  if (quota) quota.classList.toggle('hide', clipsOnly || s.has_quota === false);
  /* Chat is read through the platform, and only YouTube is wired for it. */
  const chat = dash_el('dash-chat');
  if (chat && !clipsOnly) chat.classList.toggle('hide', s.has_chat === false);

  /* The recording is a separate thing from the broadcast: it is the master the
     clips are cut from, and it used to begin and end with the session with no
     way to reach it in between -- so the only way to stop writing a file was
     to end the stream. */
  const rec = dash_el('dash-btn-record');
  if (rec) {
    const on = !!s.recording;
    const can = s.record_enabled !== false;
    rec.classList.toggle('hide', !can && !on);
    rec.disabled = dash_busy || (!can && !on);
    if (dash_recState !== on) {
      dash_recState = on;
      dash_setLabel('dash-btn-record', on ? 'stop' : 'save',
                    on ? 'Stop recording' : 'Record');
      rec.classList.toggle('btn-danger', false);
    }
    rec.title = on ? 'Stop writing the local recording. The stream carries on.'
                   : 'Start writing a local recording. Clips are cut from it.';
  }

  /* Guarded like the pause label: dash_setLabel rebuilds innerHTML, and doing
     that every two-second poll would fight the browser for no reason. */
  if (dash_stopClipsOnly !== clipsOnly) {
    dash_stopClipsOnly = clipsOnly;
    /* Not "Stop recording": that is the record toggle's label, and the two
       do different things -- this ends the session, the toggle only closes
       the file. */
    dash_setLabel('dash-btn-stop', 'stop',
                  clipsOnly ? 'End session' : 'End stream');
  }

  const open = dash_el('dash-btn-open');
  if (open) {
    const url = s.url || '';
    open.classList.toggle('hide', !url);
    if (url && open.getAttribute('href') !== url) open.setAttribute('href', url);
    /* It used to say "Open on YouTube" whatever it opened. */
    const want = 'Open on ' + (s.platform_label || 'YouTube');
    const span = open.querySelector('span');
    if (span && span.textContent !== want) span.textContent = want;
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

/* ---------------------------- audio ---------------------------- */

/* The mixer is read on a connection of its own, so it is not part of the
   two-second status poll: every 15s is plenty for something that only changes
   when someone touches it, and a read is skipped while a fader is held so the
   knob never jumps out from under the pointer. */
const dash_AUDIO_EVERY = 15000;
let dash_audio = null;        /* last mixer reading */
let dash_audioAt = 0;         /* when it was asked for */
let dash_audioHeld = false;   /* a fader is being dragged */
let dash_audioTimer = 0;      /* debounce for a fader's writes */

async function dash_audioLoad(force) {
  if (!force && (dash_audioHeld || Date.now() - dash_audioAt < dash_AUDIO_EVERY)) return;
  dash_audioAt = Date.now();
  try {
    dash_renderAudio(await API.get('/api/audio'));
  } catch (e) {
    dash_renderAudio({ ok: false, error: 'AutoStream did not answer.' });
  }
}

function dash_db(v) {
  const n = Number(v);
  if (!isFinite(n)) return dash_EMDASH;
  return n.toFixed(1) + ' dB';
}

/* "Compared to desktop" is the whole question, so it is answered in words
   rather than left for someone to subtract two dB readouts in their head. */
function dash_audioBalance(a) {
  const mic = a.mic, desk = a.desktop;
  if (!mic && !desk) return 'OBS has no audio sources. Add them in OBS: Settings > Audio.';
  if (!mic) return 'OBS has no microphone. Add one in OBS: Settings > Audio > Mic/Auxiliary Audio.';
  if (!desk) return 'OBS has no desktop audio. Add it in OBS: Settings > Audio > Desktop Audio.';
  if (mic.muted) return 'Your mic is muted: nobody can hear you.';
  if (desk.muted) return 'Desktop audio is muted: the game is silent on stream.';
  const d = Math.round((Number(mic.db) - Number(desk.db)) * 2) / 2;
  if (Math.abs(d) < 0.5) return 'Your mic sits level with the desktop.';
  return 'Your mic sits ' + Math.abs(d).toFixed(1).replace(/\.0$/, '') + ' dB '
    + (d > 0 ? 'above' : 'below') + ' the desktop.';
}

function dash_renderFader(key, src, ok) {
  const range = dash_el('dash-audio-' + key);
  const label = dash_el('dash-audio-' + key + '-db');
  const mute = dash_el('dash-audio-' + key + '-mute');
  const on = !!(ok && src);
  if (range) {
    range.disabled = !on;
    if (on && !dash_audioHeld) range.value = String(src.db);
    range.title = on ? src.name : '';
  }
  if (label) label.textContent = on ? dash_db(src.db) : dash_EMDASH;
  if (mute) {
    mute.disabled = !on;
    const m = on && !!src.muted;
    mute.classList.toggle('is-on', m);
    mute.setAttribute('aria-pressed', m ? 'true' : 'false');
    mute.textContent = m ? 'Muted' : 'Mute';
  }
}

function dash_renderAudio(a) {
  a = a || {};
  const ok = !!a.ok;
  if (ok) dash_audio = a;
  const sub = dash_el('dash-audio-sub');
  if (sub) {
    sub.textContent = ok ? 'Microphone and desktop, as OBS mixes them'
                         : (a.error || 'OBS is not answering.');
  }
  const sel = dash_el('dash-audio-device');
  if (sel) {
    const mic = ok ? a.mic : null;
    sel.disabled = !mic;
    const devs = mic ? (mic.devices || []) : [];
    /* Rebuilt only when the list changes, so an open dropdown is not closed
       under the cursor by a background refresh. */
    const key = JSON.stringify(devs) + '|' + (mic ? mic.device : '');
    if (sel.dataset.key !== key) {
      sel.dataset.key = key;
      sel.innerHTML = devs.map(function (d) {
        return '<option value="' + esc(d.id) + '">' + esc(d.name) + '</option>';
      }).join('') || '<option value="">No microphone</option>';
      if (mic) sel.value = mic.device;
    }
  }
  dash_renderFader('mic', ok ? a.mic : null, ok);
  dash_renderFader('desktop', ok ? a.desktop : null, ok);
  const bal = dash_el('dash-audio-balance');
  if (bal) bal.textContent = ok ? dash_audioBalance(a) : '';
}

async function dash_audioSet(change) {
  try {
    const r = await API.post('/api/audio/set', change);
    if (!r || !r.ok) throw new Error((r && r.error) || 'OBS refused');
    dash_audioAt = Date.now();
    dash_renderAudio(r);
  } catch (e) {
    toast('Audio not changed: ' + e.message, 'error');
    dash_audioLoad(true);          /* put the controls back to what OBS has */
  }
}

/* A fader answers while it moves -- the point is to hear the balance change --
   but only one write is in flight per pause in the drag. */
function dash_wireFader(key) {
  const range = dash_el('dash-audio-' + key);
  if (range) {
    const send = function () {
      const change = {};
      change[key + '_db'] = Number(range.value);
      dash_audioSet(change);
    };
    range.addEventListener('input', function () {
      dash_audioHeld = true;
      const label = dash_el('dash-audio-' + key + '-db');
      if (label) label.textContent = dash_db(range.value);
      if (dash_audio && dash_audio[key]) {
        dash_audio[key].db = Number(range.value);
        const bal = dash_el('dash-audio-balance');
        if (bal) bal.textContent = dash_audioBalance(dash_audio);
      }
      clearTimeout(dash_audioTimer);
      dash_audioTimer = setTimeout(send, 150);
    });
    range.addEventListener('change', function () {
      clearTimeout(dash_audioTimer);
      dash_audioHeld = false;
      send();
    });
  }
  const mute = dash_el('dash-audio-' + key + '-mute');
  if (mute) {
    mute.addEventListener('click', function () {
      const change = {};
      change[key + '_muted'] = mute.getAttribute('aria-pressed') !== 'true';
      dash_audioSet(change);
    });
  }
}

/* ---------------------------- wiring ---------------------------- */

function dash_wire() {
  if (dash_wired) return;
  dash_wired = true;

  dash_setLabel('dash-btn-stop', 'stop', 'End stream');
  dash_setLabel('dash-btn-pause', 'pause', 'Pause');
  dash_setLabel('dash-btn-record', 'save', 'Stop recording');
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

  const rec = dash_el('dash-btn-record');
  if (rec) rec.addEventListener('click', function () { dash_cmd('record'); });
  const vok = dash_el('dash-vmatch-ok');
  if (vok) vok.addEventListener('click', dash_vmatchExplained);

  dash_setLabel('dash-audio-refresh', 'refresh', '');
  const aref = dash_el('dash-audio-refresh');
  if (aref) aref.addEventListener('click', function () { dash_audioLoad(true); });
  const dev = dash_el('dash-audio-device');
  if (dev) {
    dev.addEventListener('change', function () {
      if (dev.value) dash_audioSet({ mic_device: dev.value });
    });
  }
  dash_wireFader('mic');
  dash_wireFader('desktop');

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
      /* 'stop' in every phase. ARMING used to send 'pause', which is the
         global kill switch: it outlived the cancel, survived a restart, and
         refused every other game until someone found Resume. Stop holds back
         only the game that was about to go live. */
      dash_cmd('stop');
    });
  }

  const rb = dash_el('dash-btn-replay');
  if (rb) rb.addEventListener('click', dash_saveReplay);

  /* The platform chooser. Delegated from the group so the three buttons do
     not each need a listener. */
  const seg = dash_el('dash-where-seg');
  if (seg) {
    seg.addEventListener('click', function (ev) {
      const b = ev.target.closest ? ev.target.closest('.seg-btn') : null;
      if (b && !b.disabled) dash_setPlatform(b.getAttribute('data-platform'));
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
  dash_audioLoad(true);
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
  dash_renderVMatch(s);
  dash_renderSession(s);
  dash_renderRing(s);
  dash_renderSpark(s);
  dash_applyActions(s);
  dash_renderReplay(s);
  dash_renderWhere(s);
  dash_renderChat(s);
  dash_audioLoad(false);
  dash_last = s;
}

window.PAGE_DASH = { onShow: dash_onShow, onTick: dash_onTick };
"""
