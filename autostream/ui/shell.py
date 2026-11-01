"""The application frame: rail, topbar, view containers, and the shared runtime.

WHY THIS FILE EXISTS SEPARATELY FROM THE PAGES
    Every page (Dashboard, Library, Settings, Logs) is concatenated into ONE
    <script> tag sharing ONE top-level scope, so exactly one module has to own
    the names that everybody needs -- API, toast, go, icon, esc, STATUS -- and
    everything else has to stay out of the way. That owner is this file. Page
    modules prefix their helpers (dash_, lib_, set_, log_, setup_); shell
    prefixes its own internals with shell_ / SHELL_ for the same reason, so the
    only unprefixed names shell contributes are the six contract globals.

WHY THE POLL LOOP LIVES HERE AND NEVER STOPS
    engine.py gates YouTube chat polling on `client_seen` being under 90s old,
    and webui.py stamps that on every GET /api/status. If polling paused while
    the user sat on Settings, live chat would quietly die after a minute and a
    half and only come back when the Dashboard was reopened. So the loop is
    app-wide, owned by the shell, and only the ACTIVE page gets onTick() -- the
    rail dot and topbar pill are painted by the shell itself, which is also why
    pages never need to know about each other.

WHY QUIT IS A CONFIRM AND A ONE-WAY DOOR
    Quitting kills the server that serves this page. The socket dies mid-flight,
    so the POST is fire-and-forget, polling is stopped BEFORE the request goes
    out, and the page swaps to a terminal card. Without that the page would
    spend the rest of its life throwing connection errors at a daemon that no
    longer exists.
"""
from __future__ import annotations

import json

from .icons import ICONS, LOGO_LOCKUP, LOGO_MARK

# LOGO_LOCKUP is re-exported rather than used: the rail draws the mark plus a
# real text wordmark (so it inherits the page font and the type ramp), but the
# lockup is the correct single-element logo for anything that cannot lay out
# HTML -- keep the import so the symbol resolves from this module too.
__all__ = ["SHELL_HTML", "SHELL_JS", "LOGO_LOCKUP"]


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

# (page id, icon name, label). Order is the rail order.
_NAV: tuple[tuple[str, str, str], ...] = (
    ("dash", "dashboard", "Dashboard"),
    ("library", "library", "Library"),
    ("clips", "film", "Clips"),
    ("studio", "timeline", "Studio"),
    ("settings", "settings", "Settings"),
    ("logs", "logs", "Logs"),
)


def _svg(name: str) -> str:
    """Wrap an ICONS entry exactly the way the JS icon() helper does."""
    return (
        '<svg class="icon" viewBox="0 0 24 24" width="24" height="24"'
        ' aria-hidden="true" focusable="false">' + ICONS[name] + "</svg>"
    )


def _nav_button(page: str, ico: str, label: str) -> str:
    # The label is a bare <span> on purpose: below 900px the rail collapses and
    # CSS removes `.rail-btn span` from flow, and inventing a class name here
    # would put a token outside the agreed vocabulary.
    return (
        '<button type="button" class="rail-btn" data-page="' + page + '"'
        ' title="' + label + '" aria-label="' + label + '">'
        + _svg(ico)
        + "<span>" + label + "</span>"
        + "</button>"
    )


_RAIL = (
    '<aside class="rail" id="rail">'
    '<div class="rail-logo">'
    + LOGO_MARK
    + '<span class="rail-word">AutoStream</span>'
    # The only always-visible state when the rail is collapsed to 60px, so it
    # must NOT be a bare <span> — the narrow-width rule hides those.
    + '<span class="pill pill-idle" id="rail-dot" title="Idle"></span>'
    "</div>"
    # One search box that finds anything and runs anything (Ctrl K). The
    # palette itself is shell-owned; pages only register what it can find.
    '<button type="button" class="rail-search" id="rail-search"'
    ' aria-label="Search and run commands (Ctrl K)" title="Search (Ctrl K)">'
    + _svg("search")
    + '<span>Search</span><span class="kbd">Ctrl K</span>'
    "</button>"
    '<nav class="rail-nav" aria-label="Pages">'
    + "".join(_nav_button(*n) for n in _NAV)
    + "</nav>"
    # A page's own list, shown only while that page is (the Studio's games).
    '<div class="rail-section hide" id="rail-section"></div>'
    '<div class="rail-spacer"></div>'
    # Quit is detached from the four page links by a full-bleed rule so it can
    # never be misread as a fifth destination. .rail-foot supplies that bleed
    # and .rail-meta is what the narrow-rail rule hides — both are required.
    '<div class="rail-foot">'
    # THE APP'S STATE, visible from every page: what it is doing and for how
    # long, as a mark and a sentence. It replaced the top bar's pill and clock,
    # which said the same thing in caps on every page.
    # Only the WORDS are a live region: the clock ticks every poll, and inside
    # the region it was announced every two seconds for a whole stream.
    '<div class="rail-state" id="rail-state">'
    '<span class="mark mark-idle" id="rail-state-mark" aria-hidden="true"></span>'
    '<span><span id="rail-state-text" role="status" aria-live="polite">Idle, not recording</span>'
    '<span id="rail-state-clock" aria-hidden="true"></span></span>'
    "</div>"
    '<p class="rail-meta" id="rail-readout"></p>'
    '<button type="button" class="rail-btn is-danger" id="rail-quit"'
    ' title="Quit AutoStream" aria-label="Quit AutoStream">'
    + _svg("power")
    + "<span>Quit</span>"
    + "</button>"
    + "</div>"
    "</aside>"
)

_TOPBAR = (
    '<header class="topbar">'
    # Collapses the rail to its icon strip. Open by default on the Dashboard only;
    # see shell_rail.
    '<button type="button" class="btn btn-ghost btn-sm topbar-rail" id="rail-toggle"'
    ' aria-expanded="true" aria-controls="rail" aria-label="Collapse the sidebar"'
    ' title="Collapse the sidebar">'
    '<svg class="icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">'
    '<rect x="3" y="4" width="18" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/>'
    '<path d="M9 4v16" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>'
    "</button>"
    '<h1 class="topbar-title" id="topbar-title">Dashboard</h1>'
    # Page actions, filled by the page that is showing (shell_setActions).
    '<div class="topbar-actions" id="topbar-actions"></div>'
    # PAGE SIZE, on screen as well as on Ctrl + scroll and Ctrl +/-/0: a
    # shortcut nobody knows about is not an option, and the number is the
    # answer to "why is everything so big".
    '<div class="zoom" role="group" aria-label="Page size">'
    '<button type="button" class="zoom-btn" id="zoom-out"'
    ' aria-label="Smaller (Ctrl and minus, or Ctrl and scroll down)" title="Smaller (Ctrl -)">'
    '<span aria-hidden="true">&minus;</span></button>'
    '<button type="button" class="zoom-btn zoom-pct" id="zoom-reset"'
    ' aria-label="Actual size (Ctrl and 0)" title="Back to 100% (Ctrl 0)">100%</button>'
    '<button type="button" class="zoom-btn" id="zoom-in"'
    ' aria-label="Bigger (Ctrl and plus, or Ctrl and scroll up)" title="Bigger (Ctrl +)">'
    '<span aria-hidden="true">+</span></button>'
    '<span class="sr-only" id="zoom-said" role="status" aria-live="polite"></span>'
    "</div>"
    '<div class="topbar-meta">'
    # The pill, game and clock still exist for the tests and the title, but
    # the sidebar's state line is where the state is read now (#rail-state).
    '<span class="pill pill-idle hide" id="top-pill">Idle</span>'
    '<span class="status-game hide" id="top-game"></span>'
    '<span class="mono hide" id="top-clock">--:--:--</span>'
    '<button type="button" class="btn btn-ghost btn-sm hide" id="top-toggle">'
    "Pause</button>"
    "</div>"
    "</header>"
)

SHELL_HTML: str = (
    # Revealed by shell JS on focus (see shell_bind) so it works even before CSS
    # has an opinion about it. The rail is four tab stops ahead of the content.
    '<a class="skip-link" href="#views" id="skip-link"'
    ' style="position:absolute;width:1px;height:1px;overflow:hidden;'
    'clip-path:inset(50%);white-space:nowrap">Skip to content</a>'
    '<div class="app">'
    + _RAIL
    + '<main class="main">'
    + _TOPBAR
    # tabindex so the skip link actually moves focus here, not just the scroll.
    + '<div class="views" id="views" tabindex="-1">'
    '<section class="view is-active" id="view-dash" role="tabpanel"'
    ' aria-label="Dashboard">{{DASH_HTML}}</section>'
    '<section class="view" id="view-library" role="tabpanel"'
    ' aria-label="Library">{{LIBRARY_HTML}}</section>'
    '<section class="view" id="view-clips" role="tabpanel"'
    ' aria-label="Clips">{{CLIPS_HTML}}{{REEL_HTML}}{{HIGHLIGHT_HTML}}</section>'
    '<section class="view" id="view-studio" role="tabpanel"'
    ' aria-label="Studio">{{STUDIO_HTML}}</section>'
    '<section class="view" id="view-settings" role="tabpanel"'
    ' aria-label="Settings">{{SETTINGS_HTML}}</section>'
    '<section class="view" id="view-logs" role="tabpanel"'
    ' aria-label="Logs">{{LOGS_HTML}}</section>'
    "</div>"
    "</main>"
    "</div>"
    '<div id="setup-root" class="hide">{{SETUP_HTML}}</div>'
    # Ctrl K: one box over every page. Outside .app so no view's overflow or
    # stacking can clip it.
    '<div class="pal-scrim hide" id="pal-scrim">'
    '<div class="pal" id="pal" role="dialog" aria-modal="true" aria-label="Search">'
    '<input class="pal-q" id="pal-q" type="search" autocomplete="off" spellcheck="false"'
    ' placeholder="Search clips, reels, games and settings, or type a command"'
    ' aria-label="Search" aria-controls="pal-list">'
    '<div class="pal-list" id="pal-list" role="listbox" aria-label="Results"></div>'
    '<p class="pal-foot"><span class="kbd">Up</span> <span class="kbd">Down</span> to move,'
    ' <span class="kbd">Enter</span> to open, <span class="kbd">Esc</span> to close</p>'
    "</div></div>"
    '<div id="toasts" role="status" aria-live="polite"></div>'
)


# ---------------------------------------------------------------------------
# JS
# ---------------------------------------------------------------------------

# The icon table is embedded as data rather than built at runtime so icon() is a
# pure lookup with no string assembly on the hot path (the log page renders it
# hundreds of times per repaint).
_ICON_TABLE = "const SHELL_ICONS = " + json.dumps(ICONS, sort_keys=True) + ";\n"

_SHELL_BODY = r"""
/* =======================================================================
   SHELL -- shared runtime. Owns: API, toast, go, icon, esc, STATUS.
   Everything else in this block is prefixed shell_ / SHELL_ and is private.
   ======================================================================= */

const SHELL_K = new URLSearchParams(location.search).get('k') || '';
const SHELL_PAGES = ['dash', 'library', 'clips', 'studio', 'settings', 'logs'];
const SHELL_TITLES = {dash: 'Dashboard', library: 'Library', clips: 'Clips',
                      studio: 'Studio', settings: 'Settings', logs: 'Logs'};
/* Page objects are looked up off window by name so a page file that failed to
   load cannot take the whole shell down with a ReferenceError. */
const SHELL_PAGE_OBJ = {dash: 'PAGE_DASH', library: 'PAGE_LIBRARY',
                        clips: 'PAGE_CLIPS', studio: 'PAGE_STUDIO',
                        settings: 'PAGE_SETTINGS', logs: 'PAGE_LOGS'};
const SHELL_POLL_MS = 2000;
const SHELL_FAIL_LIMIT = 3;   /* misses before we admit we are disconnected */
const SHELL_STORE_KEY = 'autostream.page';
const SHELL_RAIL_KEY = 'autostream.rail';   // 'open' | 'min': the player's own choice, once made

/* Engine phase -> pill modifier + wordmark. Colour is never the only channel:
   the wordmark always rides along with the dot. */
const SHELL_PHASE = {
  IDLE:     {pill: 'pill-idle', label: 'Idle'},
  ARMING:   {pill: 'pill-warn', label: 'Getting ready'},
  STARTING: {pill: 'pill-warn', label: 'Starting'},
  TESTING:  {pill: 'pill-warn', label: 'Going live'},
  LIVE:     {pill: 'pill-live', label: 'Live'},
  COOLDOWN: {pill: 'pill-idle', label: 'Wrapping up'},
  STOPPING: {pill: 'pill-warn', label: 'Stopping'}
};

let STATUS = {};              /* latest GET /api/status payload (contract) */
let SHELL_BOOT = {};          /* latest GET /api/bootstrap payload */
let shell_page = 'dash';
let shell_fails = 0;
let shell_off = false;        /* true once the disconnected state is showing */
let shell_dead = false;       /* quit or 403: stop everything, permanently */
let shell_booted = false;
let shell_timer = null;
let shell_phase_seen = '';

const shell_$ = (id) => document.getElementById(id);

/* Escapes quotes as well as angle brackets -- the old helper did not, and page
   files interpolate names and keys straight into single-quoted attributes. */
const esc = (t) => String(t === null || t === undefined ? '' : t)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');

function icon(name) {
  const body = SHELL_ICONS[name];
  if (!body) return '';
  return '<svg class="icon" viewBox="0 0 24 24" width="24" height="24"' +
         ' aria-hidden="true" focusable="false">' + body + '</svg>';
}

/* ---------------- media knobs ----------------
   Every player in the app gets the same two controls: how loud and how fast.
   A page marks where they go with <span class="media-knobs" data-for="ID">
   and this fills it in, so a new player cannot ship without them. The choice
   is remembered per viewer, and re-applied whenever a player loads new media,
   because loading a new src resets playbackRate to the default. */
const SHELL_RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
const SHELL_KNOB_KEY = 'autostream.knobs';

function shell_knobPrefs() {
  let v = {};
  try { v = JSON.parse(localStorage.getItem(SHELL_KNOB_KEY) || '{}') || {}; } catch (e) { v = {}; }
  return {vol: typeof v.vol === 'number' ? v.vol : 1, rate: typeof v.rate === 'number' ? v.rate : 1};
}

function shell_knobSave(prefs) {
  try { localStorage.setItem(SHELL_KNOB_KEY, JSON.stringify(prefs)); } catch (e) { /* private window */ }
}

function shell_knobApply(m) {
  if (!m || m.getAttribute('data-knobs') === 'off') return;
  const k = shell_knobPrefs();
  m.volume = Math.max(0, Math.min(1, k.vol));
  m.defaultPlaybackRate = k.rate;
  m.playbackRate = k.rate;
  m.preservesPitch = true;
}

function mediaKnobs(id) {
  const k = shell_knobPrefs();
  return '<span class="knobs" role="group" aria-label="Volume and speed">' +
    '<label class="knob-vol" title="Volume"><span aria-hidden="true">&#128266;</span>' +
    '<input type="range" min="0" max="100" step="1" value="' + Math.round(k.vol * 100) + '"' +
    ' data-knob="vol" data-for="' + esc(id) + '" aria-label="Volume"></label>' +
    '<select class="select knob-rate" data-knob="rate" data-for="' + esc(id) + '" aria-label="Playback speed" title="Playback speed">' +
    SHELL_RATES.map(r => '<option value="' + r + '"' + (r === k.rate ? ' selected' : '') + '>' + r + 'x</option>').join('') +
    '</select></span>';
}

function shell_knobsFill(root) {
  (root || document).querySelectorAll('.media-knobs[data-for]').forEach(h => {
    if (!h.firstChild) h.innerHTML = mediaKnobs(h.getAttribute('data-for'));
  });
}

function shell_knobsBind() {
  shell_knobsFill(document);
  document.querySelectorAll('audio, video').forEach(shell_knobApply);
  /* loadedmetadata does not bubble; captured at the document it still arrives
     for every player, including ones a page creates later. */
  document.addEventListener('loadedmetadata', e => shell_knobApply(e.target), true);
  const onKnob = e => {
    const t = e.target;
    const which = t && t.getAttribute && t.getAttribute('data-knob');
    if (!which) return;
    const prefs = shell_knobPrefs();
    if (which === 'vol') prefs.vol = Number(t.value) / 100;
    else prefs.rate = Number(t.value) || 1;
    shell_knobSave(prefs);
    /* One choice for the whole app: every player follows, and every other
       set of knobs shows the new value. */
    document.querySelectorAll('audio, video').forEach(shell_knobApply);
    document.querySelectorAll('[data-knob="' + which + '"]').forEach(o => {
      if (o !== t) o.value = which === 'vol' ? String(Math.round(prefs.vol * 100)) : String(prefs.rate);
    });
  };
  document.addEventListener('input', onKnob);
  document.addEventListener('change', onKnob);
}

/* ---------------- transport ---------------- */

function shell_denied() {
  shell_dead = true;
  if (shell_timer) { clearTimeout(shell_timer); shell_timer = null; }
  document.body.innerHTML =
    '<div class="empty"><div class="card"><div class="card-body">' +
    '<h2 class="card-title">Wrong or missing key</h2>' +
    '<p class="card-sub">Open the exact URL AutoStream printed in its log.</p>' +
    '</div></div></div>';
}

async function shell_fetch(path, body) {
  const opts = {cache: 'no-store', credentials: 'same-origin'};
  if (body !== undefined) {
    opts.method = 'POST';
    opts.headers = {'Content-Type': 'application/json'};
    opts.body = JSON.stringify(body);
  }
  const sep = path.indexOf('?') >= 0 ? '&' : '?';
  const r = await fetch(path + sep + 'k=' + encodeURIComponent(SHELL_K), opts);
  if (r.status === 403) { shell_denied(); throw new Error('403'); }
  const ct = r.headers.get('content-type') || '';
  /* 4xx/5xx still carry a JSON {error: ...} body; hand it back rather than
     throwing, because every caller already branches on r.error. */
  return ct.indexOf('json') >= 0 ? r.json() : r.text();
}

const API = {
  get(path) { return shell_fetch(path, undefined); },
  post(path, body) { return shell_fetch(path, body === undefined ? {} : body); }
};

/* ---------------- toasts ---------------- */

/* `action`, optional: {label, run} -- one button on the toast, which then stays
   long enough to be pressed. */
function toast(message, kind, action) {
  const host = shell_$('toasts');
  if (!host) return;
  const el = document.createElement('div');
  el.className = 'toast is-' + (kind === 'warn' || kind === 'error' ? kind : 'ok');
  el.textContent = message === null || message === undefined ? '' : String(message);
  const kill = () => { if (el.parentNode) el.parentNode.removeChild(el); };
  if (action && action.label && typeof action.run === 'function') {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn btn-sm toast-act';
    b.textContent = action.label;
    b.addEventListener('click', (e) => { e.stopPropagation(); kill(); action.run(); });
    el.appendChild(b);
  }
  host.appendChild(el);
  el.addEventListener('click', kill);
  setTimeout(kill, action ? 10000 : 3500);
  while (host.children.length > 4) host.removeChild(host.firstChild);
}

/* ---------------- heavy downloads (packs.py) ----------------

   ASKED, NEVER ASSUMED. The player (2026-11-02): when somebody uses a feature
   whose heavy libraries or models are not on the machine, ask them and download
   it for them. So a feature that needs a pack calls pack_need(key) first: it
   says what the pack is for and what it costs in gigabytes, and downloads only
   on Download, with its progress, and the app stays usable meanwhile.
   -> a promise of true once the pack is there; false for Not now, or a machine
   that cannot use it (opts.quiet: say nothing about that). */
let pack_open = null;

function pack_size(b) {
  return b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : Math.max(1, Math.round(b / 1e6)) + ' MB';
}

async function pack_need(key, opts) {
  opts = opts || {};
  if (pack_open) return pack_open.promise;
  const scrim = document.createElement('div');
  scrim.className = 'scrim pack-scrim';
  scrim.innerHTML =
    '<div class="modal pack-modal" role="dialog" aria-modal="true" aria-labelledby="pack-title">' +
    '<h2 class="modal-title" id="pack-title">Checking what is needed</h2>' +
    '<div class="modal-body" id="pack-body"><p class="muted">Working out the download size&hellip;</p></div>' +
    '<div class="pack-bar hide" id="pack-bar"><span id="pack-fill"></span></div>' +
    '<p class="muted pack-step hide" id="pack-step"></p>' +
    '<div class="modal-actions" id="pack-acts"></div></div>';
  let done;
  const promise = new Promise(res => { done = res; });
  pack_open = {promise: promise};
  const finish = (ok) => {
    clearTimeout(pack_open && pack_open.poll);
    if (scrim.parentNode) scrim.parentNode.removeChild(scrim);
    pack_open = null;
    done(ok);
  };
  const $ = (id) => scrim.querySelector('#' + id);
  const acts = (html) => { $('pack-acts').innerHTML = html; };
  document.body.appendChild(scrim);
  let plan;
  try { plan = await API.post('/api/packs/plan', {key: key}); } catch (e) { plan = {error: 'The download could not be checked.'}; }
  if (!plan || plan.error) { finish(false); toast((plan && plan.error) || 'The download could not be checked.', 'error'); return promise; }
  if (plan.installed) { finish(true); return promise; }
  if (!plan.can) { finish(false); if (!opts.quiet) toast(plan.why, 'warn'); return promise; }
  const label = plan.label;
  $('pack-title').textContent = 'Download ' + label.toLowerCase() + '?';
  $('pack-body').innerHTML =
    '<p>' + esc((opts.reason ? opts.reason + ' needs ' : '') + label.toLowerCase() + ': it ' + plan.what + '.') + '</p>' +
    '<p>It is too large to come with AutoStream, so it is downloaded once, when it is first ' +
    'needed: <b>' + esc(pack_size(plan.bytes || 0)) + '</b>, kept on this PC and never uploaded anywhere.</p>';
  const watch = () => {
    pack_open.poll = setTimeout(async () => {
      let r;
      try { r = await API.get('/api/packs/progress'); } catch (e) { r = null; }
      if (!pack_open) return;
      if (!r) { watch(); return; }
      if (r.state === 'running') {
        $('pack-bar').classList.remove('hide');
        $('pack-step').classList.remove('hide');
        $('pack-fill').style.width = Math.min(100, r.percent || 0) + '%';
        $('pack-step').textContent = (r.step || 'Downloading') + ' -- ' + pack_size(r.done || 0) + ' of ' +
          pack_size(r.total || plan.bytes || 0);
        watch();
      } else if (r.state === 'done') {
        toast(label + ' is ready.', 'ok');
        finish(true);
      } else if (r.state === 'failed') {
        $('pack-step').textContent = r.error || 'The download failed.';
        acts('<button class="btn" type="button" data-pack="no">Close</button>' +
             '<button class="btn btn-primary" type="button" data-pack="go">Try again</button>');
      } else {
        finish(false);
      }
    }, 1000);
  };
  const start = async () => {
    const r = await API.post('/api/packs/install', {key: key});
    if (r && r.error) { toast(r.error, 'error'); return; }
    acts('<button class="btn" type="button" data-pack="hide">Keep using the app</button>' +
         '<button class="btn btn-ghost" type="button" data-pack="stop">Stop</button>');
    $('pack-step').classList.remove('hide');
    $('pack-step').textContent = 'Starting the download...';
    watch();
  };
  acts('<button class="btn" type="button" data-pack="no">' + esc(opts.skip || 'Not now') + '</button>' +
       '<button class="btn btn-primary" type="button" data-pack="go">Download ' + esc(pack_size(plan.bytes || 0)) + '</button>');
  scrim.addEventListener('click', (e) => {
    const b = e.target.closest('[data-pack]');
    if (!b) return;
    const a = b.getAttribute('data-pack');
    if (a === 'go') start();
    else if (a === 'no') finish(false);
    else if (a === 'stop') { API.post('/api/packs/cancel', {}); finish(false); }
    else if (a === 'hide') scrim.classList.add('hide');     /* still downloading; resolves when done */
  });
  const running = await API.get('/api/packs/progress').catch(() => null);
  if (running && running.state === 'running' && running.key === key) {
    acts('<button class="btn" type="button" data-pack="hide">Keep using the app</button>' +
         '<button class="btn btn-ghost" type="button" data-pack="stop">Stop</button>');
    watch();
  }
  return promise;
}

/* ---------------- navigation ---------------- */

function shell_call(obj, method, arg) {
  if (!obj || typeof obj[method] !== 'function') return;
  try { obj[method](arg); } catch (e) { console.error(method + ' failed', e); }
}

function shell_doc_title() {
  const live = STATUS && STATUS.phase === 'LIVE' && !STATUS.paused;
  document.title = (live ? 'LIVE - ' : '') +
                   (SHELL_TITLES[shell_page] || 'Dashboard') + ' - AutoStream';
}

/* THE SIDEBAR IS OPEN ON EVERY PAGE until the player collapses it, and that
   choice then holds on every page. It used to fold to an icon strip off the
   Dashboard, which hid the page names from exactly the person who did not
   know the icons yet. Below 900px it is the strip regardless. */
function shell_rail() {
  let pref = null;
  try { pref = localStorage.getItem(SHELL_RAIL_KEY); } catch (e) { /* private mode */ }
  const min = shell_narrow(899) || pref === 'min';
  const app = document.querySelector('.app'), t = shell_$('rail-toggle');
  if (app) { app.classList.toggle('rail-min', min); if (!min) app.classList.remove('rail-peek'); }
  if (t) {
    const say = min ? 'Expand the sidebar' : 'Collapse the sidebar';
    t.setAttribute('aria-expanded', String(!min));
    t.setAttribute('aria-label', say);
    t.title = say;
  }
  return min;
}

/* THE STRIP OPENS ON HOVER (or keyboard focus), the page making room, and closes when the pointer leaves.
   Not below 900px, where the strip is the layout and the labels are gone for good. */
let shell_peekTimer = 0;
function shell_railPeek(on) {
  clearTimeout(shell_peekTimer);
  const app = document.querySelector('.app');
  if (!app) return;
  if (!on) { app.classList.remove('rail-peek'); return; }
  if (!app.classList.contains('rail-min') || shell_narrow(899)) return;
  shell_peekTimer = setTimeout(() => app.classList.add('rail-peek'), 120);
}

function shell_railToggle() {
  const next = shell_rail() ? 'open' : 'min';
  try { localStorage.setItem(SHELL_RAIL_KEY, next); } catch (e) { /* the choice lasts until reload */ }
  shell_rail();
}

function go(page) {
  if (SHELL_PAGES.indexOf(page) < 0) page = SHELL_BOOT.home || 'dash';
  /* The page being left is told first, so whatever it is playing stops with it. */
  if (page !== shell_page) shell_call(window[SHELL_PAGE_OBJ[shell_page]], 'onHide');
  shell_page = page;
  const views = document.querySelectorAll('.view');
  for (let i = 0; i < views.length; i++) {
    views[i].classList.toggle('is-active', views[i].id === 'view-' + page);
  }
  const btns = document.querySelectorAll('.rail-btn[data-page]');
  for (let i = 0; i < btns.length; i++) {
    const on = btns[i].getAttribute('data-page') === page;
    btns[i].classList.toggle('is-active', on);
    if (on) btns[i].setAttribute('aria-current', 'page');
    else btns[i].removeAttribute('aria-current');
  }
  shell_setText(shell_$('topbar-title'), SHELL_TITLES[page]);
  /* A page's actions and sidebar list belong to it alone: clear them before
     the new page's onShow puts its own back. */
  shell_setActions(null);
  shell_railSection(null);
  shell_rail();
  try { sessionStorage.setItem(SHELL_STORE_KEY, page); } catch (e) { /* private mode */ }
  shell_doc_title();

  const host = shell_$('views');
  if (host) { host.scrollTop = 0; shell_scrolled(host); }

  const P = window[SHELL_PAGE_OBJ[page]];
  shell_call(P, 'onShow');
  /* A page that just became visible should not sit blank for two seconds. */
  if (STATUS && STATUS.phase) shell_call(P, 'onTick', STATUS);
  /* Its canvases were painted in the palette it was last shown in. */
  if ((shell_themeSeen[page] || 0) !== shell_themeGen) shell_repaint();
  shell_newOnGo(page);
}

/* ---------------- "Clips, N new" ---------------- */

/* The clips made since the player last looked at them, beside Clips in the
   sidebar -- the same count as the idle Dashboard's "Since last time", from
   the same endpoint, so the two can never disagree. Looking at them (the Clips
   page or the Studio, which both stamp /api/seen on show) clears it. Asked
   when the page opens, when a clip job finishes, and on a change of page at
   most every 30 s: /api/since walks the clips folder, which is not a thing to
   do every two-second status poll. */
let shell_newN = 0, shell_newAt = 0, shell_newJob = '';

function shell_newPaint() {
  const btn = document.querySelector('.rail-btn[data-page="clips"]');
  if (!btn) return;
  let b = btn.querySelector('.rail-n');
  const n = shell_newN;
  if (!n) { if (b) b.remove(); btn.setAttribute('aria-label', 'Clips'); btn.title = 'Clips'; return; }
  if (!b) { b = document.createElement('b'); b.className = 'rail-n'; btn.appendChild(b); }
  const say = n + ' new';
  shell_setText(b, say);
  btn.setAttribute('aria-label', 'Clips, ' + say);
  btn.title = 'Clips, ' + say;
}

function shell_newAsk() {
  shell_newAt = Date.now();
  API.get('/api/since').then(d => {
    /* Looked at the clips while the request was out: they are not new any more. */
    if (shell_page === 'clips' || shell_page === 'studio') return;
    shell_newN = Math.max(0, Number(d && d.clips_new) || 0);
    shell_newPaint();
  }).catch(() => { /* a missed count is not worth a toast */ });
}

function shell_newOnGo(page) {
  if (page === 'clips' || page === 'studio') { shell_newN = 0; shell_newPaint(); return; }
  if (Date.now() - shell_newAt > 30000) shell_newAsk();
}

function shell_newWatch(s) {
  const st = (s && s.clips && s.clips.state) || '';
  if (st !== shell_newJob && shell_newJob === 'running' &&
      shell_page !== 'clips' && shell_page !== 'studio') shell_newAsk();
  shell_newJob = st;
}

/* ---------------- the palette changed ---------------- */

/* A canvas is pixels, not styles: it keeps the colours it was drawn in until
   something draws it again, so a theme switch left graphs in the old palette
   until their song played or the window was resized. Every page's canvases
   already redraw on resize (zoom relies on it), so that is the signal; the
   few that only redraw while playing listen for 'as-theme' as well. A page
   that is hidden when the palette changes repaints the next time it is shown,
   because its resize handlers draw only the page on screen. */
let shell_themeGen = 0, shell_scheme = null;
const shell_themeSeen = {};

function shell_repaint() {
  shell_themeSeen[shell_page] = shell_themeGen;
  window.dispatchEvent(new Event('resize'));
  window.dispatchEvent(new Event('as-theme'));
}

function shell_themeChanged() {
  shell_themeGen++;
  shell_repaint();
}

/* ---------------- live state ---------------- */

function shell_setText(el, text) {
  const v = text === null || text === undefined ? '' : String(text);
  if (el && el.textContent !== v) el.textContent = v;
}

function shell_setPill(el, mod, text, title) {
  if (!el) return;
  const cls = 'pill ' + mod;
  if (el.className !== cls) el.className = cls;
  if (text !== null) shell_setText(el, text);
  if (title && el.title !== title) el.title = title;
}

/* What the sidebar's state line says, and which mark goes beside it.
   -> {mark: 'live'|'work'|'need'|'idle', text}. A sentence, not a code: it is
   the one place every page shows what the app is doing. */
function shell_stateLine(s) {
  const phase = String(s.phase || 'IDLE');
  const t = shell_clock(s.elapsed);
  if (s.blocked) return {mark: 'need', text: 'Held back: ' + String(s.blocked)};
  if (s.paused) return {mark: 'need', text: 'Paused'};
  if (phase === 'LIVE') {
    const rec = s.streaming === false;
    return {mark: 'live', text: (rec ? 'Recording' : 'Live') + (t ? ', ' + t : '')};
  }
  if (phase === 'IDLE') {
    return s.recording ? {mark: 'live', text: 'Recording' + (t ? ', ' + t : '')}
                       : {mark: 'idle', text: 'Idle, not recording'};
  }
  const meta = SHELL_PHASE[phase];
  return {mark: 'work', text: meta ? meta.label : phase};
}

/* 1:24:07, or 12:40 under an hour. Empty when there is nothing to time. */
function shell_clock(sec) {
  if (sec === null || sec === undefined || isNaN(Number(sec))) return '';
  sec = Math.max(0, sec | 0);
  const h = (sec / 3600) | 0, m = ((sec % 3600) / 60) | 0, x = sec % 60;
  const p = (n) => String(n).padStart(2, '0');
  return h ? h + ':' + p(m) + ':' + p(x) : m + ':' + p(x);
}

function shell_paintState(line) {
  const mark = shell_$('rail-state-mark');
  const cls = 'mark mark-' + line.mark;
  if (mark && mark.className !== cls) mark.className = cls;
  if (mark && line.mark === 'work') mark.style.setProperty('--p', '50');
  /* "Live, 1:24:07" is drawn as the words (a live region) and the clock
     (not one), so a screen reader hears "Live" once, not every tick. */
  const m = /^(.*), (\d+:\d\d(?::\d\d)?)$/.exec(line.text);
  shell_setText(shell_$('rail-state-text'), m ? m[1] : line.text);
  shell_setText(shell_$('rail-state-clock'), m ? ', ' + m[2] : '');
}

/* A page puts its own buttons in the top bar (null clears them). */
function shell_setActions(html) {
  const host = shell_$('topbar-actions');
  if (host && host.innerHTML !== (html || '')) host.innerHTML = html || '';
}

/* A page puts its own list in the sidebar under the page links (the Studio's
   games); null takes it away again. */
function shell_railSection(html) {
  const host = shell_$('rail-section');
  if (!host) return;
  if (host.innerHTML !== (html || '')) host.innerHTML = html || '';
  host.classList.toggle('hide', !html);
}

function shell_hms(s) {
  if (s === null || s === undefined) return '--:--:--';
  s = Math.max(0, s | 0);
  const p = (n) => String(n).padStart(2, '0');
  return p((s / 3600) | 0) + ':' + p(((s % 3600) / 60) | 0) + ':' + p(s % 60);
}

/* Grouped digits, because a bare 1240 next to 10,000 reads as a typo. */
const shell_group = (n) => isNaN(Number(n))
  ? String(n) : Number(n).toLocaleString('en-US');

function shell_paint(s) {
  const phase = String(s.phase || 'IDLE');
  const meta = SHELL_PHASE[phase] || SHELL_PHASE.IDLE;
  let mod = meta.pill, label = meta.label, why = phase;
  if (s.blocked) { mod = 'pill-warn'; label = 'Blocked'; why = String(s.blocked); }
  else if (s.paused) { mod = 'pill-idle'; label = 'Paused'; why = 'Paused'; }

  shell_setPill(shell_$('rail-dot'), mod, null, label);
  shell_setPill(shell_$('top-pill'), mod + ' hide', label, why);
  shell_paintState(shell_stateLine(s));

  /* The game is named in the sidebar's state line and the Dashboard's status
     line now; the top bar keeps the element, hidden, for the title. */
  shell_setText(shell_$('top-game'), s.game || '');
  shell_setText(shell_$('top-clock'), shell_hms(s.elapsed));

  /* One pause control, always in the same place, on every page. */
  const tog = shell_$('top-toggle');
  if (tog) {
    /* Three failed starts hold every game back the way a pause does, and
       Resume is what clears them. */
    const held = !!(s.paused || s.start_blocked);
    const running = phase !== 'IDLE' || held;
    /* The Dashboard has its own Pause in its status line. */
    tog.classList.toggle('hide', !running || shell_page === 'dash');
    shell_setText(tog, held ? 'Resume' : 'Pause');
  }

  const readout = shell_$('rail-readout');
  if (readout) {
    const bits = [];
    if (SHELL_BOOT.version) bits.push('v' + SHELL_BOOT.version);
    if (s.session) bits.push('session ' + s.session);
    /* The API budget means nothing with YouTube off. */
    if (s.streaming !== false && s.quota_spent !== null && s.quota_spent !== undefined) {
      bits.push('quota ' + shell_group(s.quota_spent) + '/10,000');
    }
    shell_setText(readout, bits.join(', '));   /* commas: the redesign retired the middot strings */
  }

  if (phase !== shell_phase_seen) { shell_phase_seen = phase; shell_doc_title(); }
}

function shell_offline(on) {
  if (shell_off === on) return;
  shell_off = on;
  if (!on) return;    /* the next successful paint repaints everything */
  shell_setPill(shell_$('top-pill'), 'pill-warn hide', 'Not responding',
                'AutoStream is not responding');
  shell_paintState({mark: 'need', text: 'Not responding'});
  shell_setPill(shell_$('rail-dot'), 'pill-warn', null, 'Not responding');
  const game = shell_$('top-game');
  if (game) game.classList.add('hide');
  shell_setText(shell_$('top-clock'), '--:--:--');
}

async function shell_poll() {
  if (shell_dead) return;
  let s;
  try {
    s = await API.get('/api/status');
  } catch (e) {
    /* No toast here on purpose: a dropped daemon would produce one every two
       seconds forever. Three misses flips the topbar instead. */
    if (!shell_dead && ++shell_fails >= SHELL_FAIL_LIMIT) shell_offline(true);
    return;
  }
  shell_fails = 0;
  shell_offline(false);
  STATUS = s || {};
  /* Guarded: a throw in here used to freeze the whole page silently, because
     the loop would stop rescheduling and nothing visible would change. */
  try { shell_paint(STATUS); } catch (e) { console.error('paint failed', e); }
  shell_newWatch(STATUS);
  shell_call(window[SHELL_PAGE_OBJ[shell_page]], 'onTick', STATUS);
}

function shell_loop() {
  if (shell_timer) { clearTimeout(shell_timer); shell_timer = null; }
  /* Self-scheduling rather than setInterval: a slow response must not let a
     second request stack up behind the first. The catch is what guarantees the
     loop can never die -- a frozen UI is the worst failure mode this page has. */
  shell_poll()
    .catch((e) => { console.error('poll failed', e); })
    .then(() => {
      if (!shell_dead) shell_timer = setTimeout(shell_loop, SHELL_POLL_MS);
    });
}

/* ---------------- quit ---------------- */

function shell_farewell() {
  document.body.innerHTML =
    '<div class="empty"><div class="card"><div class="card-body">' +
    '<h2 class="card-title">AutoStream has quit</h2>' +
    '<p class="card-sub">The daemon has stopped. You can close this window.</p>' +
    '</div></div></div>';
}

function shell_quit() {
  const live = STATUS.phase === 'LIVE' || STATUS.phase === 'STARTING' ||
               STATUS.phase === 'TESTING';
  const msg = live
    ? 'You are LIVE right now.\n\nQuit AutoStream completely? This ends the ' +
      'broadcast immediately and stops the daemon.'
    : 'Quit AutoStream completely? This ends any live stream and stops the daemon.';
  if (!confirm(msg)) return;
  /* Stop polling BEFORE the server dies, or the page spends the rest of its
     life retrying a socket that is never coming back. */
  shell_dead = true;
  if (shell_timer) { clearTimeout(shell_timer); shell_timer = null; }
  API.post('/api/cmd', {command: 'quit'}).catch(() => { /* expected */ });
  shell_farewell();
}

async function shell_toggle_pause() {
  const btn = shell_$('top-toggle');
  if (btn) btn.disabled = true;
  try {
    const r = await API.post('/api/cmd', {
      command: (STATUS.paused || STATUS.start_blocked) ? 'resume' : 'pause'});
    if (r && r.error) toast(r.error, 'error');
  } catch (e) {
    if (!shell_dead) toast('Could not reach AutoStream', 'error');
  }
  if (btn) btn.disabled = false;
}

/* ---------------- page size ---------------- */

/* THE WHOLE PAGE, BIGGER OR SMALLER. CSS zoom on the root, so it is the same
   in the app's own window and in a browser tab, and kept per screen in
   localStorage: a page size is about the monitor in front of you, not about
   the install. Widths reflow by themselves under zoom; the layouts that are
   the window's HEIGHT divide by --ui-zoom (css.py --vh100), or a bigger page
   would spill below the window instead of fitting it.

   THE BREAKPOINTS DO NOT FOLLOW BY THEMSELVES. A media query measures the
   window, and CSS zoom does not change the window: at 200% a 1200px window
   holds 600px of page but still matched the desktop rules, so the sidebar,
   the Studio's panel and the Dashboard's two halves were squeezed side by
   side at twice the size. shell_zoomMedia() rescales every width and height
   in the sheet's @media rules by the zoom, so they ask about the page's room
   instead; shell_narrow() is the same question for the script. */
const SHELL_ZOOM_STEPS = [0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2];
const SHELL_ZOOM_KEY = 'autostream.zoom';
let shell_zoom = 1;

/* Is the page's own room (the window divided by the zoom) at most `px` wide? */
function shell_narrow(px) {
  return window.innerWidth / (shell_zoom || 1) <= px;
}

function shell_zoomMedia(z) {
  const scale = text => text.replace(/((?:min|max)-(?:width|height)\s*:\s*)([\d.]+)px/g,
    (m, k, n) => k + (Math.round(Number(n) * z * 100) / 100) + 'px');
  const walk = rules => {
    for (let i = 0; i < rules.length; i++) {
      const r = rules[i];
      if (r.media && r.cssRules) {
        /* The rule's own text is kept the first time, so every step scales the
           original rather than the last step's already-scaled number. */
        if (r.__asMedia === undefined) r.__asMedia = r.media.mediaText;
        if (/(?:min|max)-(?:width|height)/.test(r.__asMedia)) {
          const want = z === 1 ? r.__asMedia : scale(r.__asMedia);
          if (r.media.mediaText !== want) r.media.mediaText = want;
        }
      }
      if (r.cssRules) walk(r.cssRules);
    }
  };
  for (let i = 0; i < document.styleSheets.length; i++) {
    let rules = null;
    try { rules = document.styleSheets[i].cssRules; } catch (e) { continue; }  /* not ours to read */
    if (rules) walk(rules);
  }
}

/* The next step up (dir 1) or down (dir -1) the ladder from z. A value that
   is not on the ladder -- an old or hand-edited one -- moves to the nearest
   step in that direction; anything unreadable counts as 100%. */
function shell_zoomNext(z, dir) {
  z = Number(z);
  if (!isFinite(z) || z <= 0) z = 1;
  const s = SHELL_ZOOM_STEPS;
  if (dir > 0) { for (let i = 0; i < s.length; i++) if (s[i] > z + 1e-6) return s[i]; return s[s.length - 1]; }
  for (let i = s.length - 1; i >= 0; i--) if (s[i] < z - 1e-6) return s[i];
  return s[0];
}

/* No toast: the percentage on screen already changes, and a toast per
   Ctrl + scroll notch would stack up. A screen reader hears it from the
   status line below. */
function shell_zoomSet(z) {
  z = Math.min(2, Math.max(0.67, Number(z) || 1));
  shell_zoom = z;
  const root = document.documentElement;
  root.style.zoom = String(z);
  root.style.setProperty('--ui-zoom', String(z));
  shell_zoomMedia(z);
  try { localStorage.setItem(SHELL_ZOOM_KEY, String(z)); } catch (e) { /* the size lasts until reload */ }
  const pct = Math.round(z * 100) + '%';
  shell_setText(shell_$('zoom-reset'), pct);
  const out = shell_$('zoom-out'), inn = shell_$('zoom-in');
  if (out) out.disabled = z <= SHELL_ZOOM_STEPS[0] + 1e-6;
  if (inn) inn.disabled = z >= SHELL_ZOOM_STEPS[SHELL_ZOOM_STEPS.length - 1] - 1e-6;
  /* Canvases (the viewer graph) measure their box when they draw. */
  window.dispatchEvent(new Event('resize'));
  shell_setText(shell_$('zoom-said'), 'Page size ' + pct);
}

function shell_zoomStep(dir) { shell_zoomSet(shell_zoomNext(shell_zoom, dir)); }

function shell_zoomLoad() {
  let z = 1;
  try { z = Number(localStorage.getItem(SHELL_ZOOM_KEY)) || 1; } catch (e) { /* private mode */ }
  shell_zoomSet(z);
}

/* Ctrl + scroll: up is bigger, down is smaller. Non-passive, or the browser
   ignores preventDefault and zooms the page on top of us. */
let shell_zoomWheelAt = 0;
function shell_zoomWheel(e) {
  if (!e.ctrlKey || e.deltaY === 0) return;
  e.preventDefault();
  /* One step per notch, not per event: a touchpad pinch arrives as Ctrl +
     wheel in a burst of tiny events, and stepping on each one would jump
     from 100% to 200% in a single gesture. */
  const now = Date.now();
  if (now - shell_zoomWheelAt < 120) return;
  shell_zoomWheelAt = now;
  shell_zoomStep(e.deltaY < 0 ? 1 : -1);
}

/* Ctrl + plus (or =, the same key unshifted), Ctrl + minus, Ctrl + 0. */
function shell_zoomKey(e) {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
  const k = e.key;
  if (k === '=' || k === '+') { e.preventDefault(); shell_zoomStep(1); }
  else if (k === '-') { e.preventDefault(); shell_zoomStep(-1); }
  else if (k === '0') { e.preventDefault(); shell_zoomSet(1); }
}

/* ---------------- Ctrl K ---------------- */

/* Each page registers what it can find: pal_source('Clips', q => [{label,
   hint, keys, run}]). The shell owns the box, the keys and the order. */
const PAL_GROUPS = ['Clips', 'Reels', 'Games', 'Actions', 'Settings'];
const PAL_SOURCES = [];
const PAL_PER_GROUP = 6;
let pal_rows = [];
let pal_at = 0;

function pal_source(name, fn) { PAL_SOURCES.push({name: name, fn: fn}); }

/* Every word of the query, in any order, somewhere in the text. */
function pal_match(q, text) {
  const words = String(q || '').toLowerCase().split(/\s+/).filter(Boolean);
  const t = String(text || '').toLowerCase();
  return words.every(w => t.indexOf(w) >= 0);
}

/* -> rows in group order, no group over PAL_PER_GROUP (6). A source that
   throws is skipped: one broken page must not empty the box. */
function pal_collect(q, sources) {
  const by = {};
  for (let i = 0; i < sources.length; i++) {
    let got = [];
    try { got = sources[i].fn(q) || []; } catch (e) { got = []; }
    const g = sources[i].name;
    by[g] = (by[g] || []).concat(got);
  }
  const out = [];
  const order = PAL_GROUPS.concat(Object.keys(by).filter(g => PAL_GROUPS.indexOf(g) < 0));
  for (let i = 0; i < order.length; i++) {
    const rows = (by[order[i]] || []).slice(0, 6);
    for (let j = 0; j < rows.length; j++) out.push(Object.assign({group: order[i]}, rows[j]));
  }
  return out;
}

function pal_draw() {
  const host = shell_$('pal-list');
  const q = shell_$('pal-q');
  if (!host) return;
  pal_rows = pal_collect(q ? q.value : '', PAL_SOURCES);
  if (pal_at >= pal_rows.length) pal_at = Math.max(0, pal_rows.length - 1);
  if (!pal_rows.length) {
    host.innerHTML = '<p class="pal-none">Nothing matches. Try fewer words.</p>';
    return;
  }
  let html = '', last = '';
  pal_rows.forEach((r, i) => {
    if (r.group !== last) { html += '<p class="pal-grp">' + esc(r.group) + '</p>'; last = r.group; }
    html += '<button type="button" role="option" class="pal-row' + (i === pal_at ? ' is-on' : '') +
      '" data-pal="' + i + '" aria-selected="' + (i === pal_at) + '">' +
      '<span class="pal-lab">' + esc(r.label) + '</span>' +
      (r.hint ? '<span class="pal-hint">' + esc(r.hint) + '</span>' : '') +
      (r.keys ? '<span class="kbd">' + esc(r.keys) + '</span>' : '') + '</button>';
  });
  host.innerHTML = html;
  const on = host.querySelector('.pal-row.is-on');
  if (on && on.scrollIntoView) on.scrollIntoView({block: 'nearest'});
}

/* Where Ctrl K was pressed, so closing the box puts the keyboard back there
   rather than at the top of the document -- a keyboard user who looked
   something up and pressed Escape was otherwise sent back to the skip link. */
let pal_from = null;

function pal_open() {
  const scrim = shell_$('pal-scrim');
  if (!scrim || !scrim.classList.contains('hide')) return;
  const a = document.activeElement;
  pal_from = a && a !== document.body ? a : null;
  scrim.classList.remove('hide');
  const q = shell_$('pal-q');
  if (q) { q.value = ''; q.focus(); }
  pal_at = 0;
  pal_draw();
}

/* Back to where it was opened from, if that is still on screen. A command
   that changed page has hidden it, and focusing a hidden control scrolls
   nothing into view and leaves the keyboard nowhere visible. */
function pal_return() {
  const from = pal_from;
  pal_from = null;
  if (!from || !from.isConnected || !from.offsetParent || !from.focus) return;
  const a = document.activeElement;
  if (a && a !== document.body && !shell_$('pal-scrim').contains(a)) return;  /* the command moved it */
  try { from.focus({preventScroll: true}); } catch (e) { /* gone mid-call */ }
}

function pal_close() {
  const scrim = shell_$('pal-scrim');
  if (!scrim || scrim.classList.contains('hide')) return;
  scrim.classList.add('hide');
  pal_return();
}

function pal_run(i) {
  const r = pal_rows[i];
  if (!r) return;
  const scrim = shell_$('pal-scrim');
  if (scrim) scrim.classList.add('hide');
  try { r.run && r.run(); } catch (e) { console.error('palette', e); }
  pal_return();
}

/* aria-modal says nothing outside the box can be reached; Tab has to agree,
   or it walks out behind the scrim into a page the reader was told is not
   there. Wraps from the last result to the search box and back. */
function pal_trap(e) {
  const box = shell_$('pal');
  if (!box) return;
  const all = Array.prototype.filter.call(box.querySelectorAll('input, button, [tabindex]'),
    el => !el.disabled && el.tabIndex >= 0 && el.offsetParent);
  if (!all.length) return;
  const first = all[0], last = all[all.length - 1], at = document.activeElement;
  if (!box.contains(at)) { e.preventDefault(); first.focus(); }
  else if (e.shiftKey && at === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && at === last) { e.preventDefault(); first.focus(); }
}

/* Ctrl K (Cmd K) opens it from any page. Only opens: a page with its own
   Ctrl K handler that also calls pal_open() must not toggle it shut. */
function pal_key(e) {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && String(e.key).toLowerCase() === 'k') {
    e.preventDefault();
    pal_open();
    return;
  }
  const scrim = shell_$('pal-scrim');
  if (!scrim || scrim.classList.contains('hide')) return;
  /* While the box is open the keys are its own. Escape here also reached
     the Studio's handler, which closed the reel maker under the palette. */
  if (['Escape', 'ArrowDown', 'ArrowUp', 'Enter', 'Tab'].indexOf(e.key) >= 0) e.stopImmediatePropagation();
  if (e.key === 'Tab') pal_trap(e);
  else if (e.key === 'Escape') { e.preventDefault(); pal_close(); }
  else if (e.key === 'ArrowDown') { e.preventDefault(); pal_at = Math.min(pal_rows.length - 1, pal_at + 1); pal_draw(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); pal_at = Math.max(0, pal_at - 1); pal_draw(); }
  else if (e.key === 'Enter') {
    /* A result reached with Tab is the one meant, not the highlighted one. */
    const row = document.activeElement && document.activeElement.closest
      ? document.activeElement.closest('.pal-row[data-pal]') : null;
    e.preventDefault();
    pal_run(row ? Number(row.getAttribute('data-pal')) : pal_at);
  }
}

/* The app's own actions: pages, and what the engine can do from anywhere. */
pal_source('Actions', q => {
  const out = [];
  SHELL_PAGES.forEach(p => {
    const t = SHELL_TITLES[p] || p;
    if (pal_match(q, 'go to ' + t)) out.push({label: 'Go to ' + t, run: () => go(p)});
  });
  const held = STATUS && (STATUS.paused || STATUS.start_blocked);
  const say = held ? 'Resume' : 'Pause';
  if (STATUS && STATUS.phase && (STATUS.phase !== 'IDLE' || held) && pal_match(q, say))
    out.push({label: say, keys: 'P', run: shell_toggle_pause});
  if (pal_match(q, 'make the page bigger zoom in larger size'))
    out.push({label: 'Make the page bigger', keys: 'Ctrl +', run: () => shell_zoomStep(1)});
  if (pal_match(q, 'make the page smaller zoom out size'))
    out.push({label: 'Make the page smaller', keys: 'Ctrl -', run: () => shell_zoomStep(-1)});
  if (shell_zoom !== 1 && pal_match(q, 'actual size page reset zoom 100'))
    out.push({label: 'Page at actual size', keys: 'Ctrl 0', run: () => shell_zoomSet(1)});
  if (pal_match(q, 'save replay instant'))
    out.push({label: 'Save replay', keys: 'F9', run: () => API.post('/api/cmd', {command: 'replay'})
      .then(r => toast(r && r.error ? r.error : 'Saving the replay', r && r.error ? 'error' : 'ok'))
      .catch(() => toast('Could not reach AutoStream', 'error'))});
  return out;
});

/* ---------------- wiring ---------------- */

function shell_scrolled(host) {
  /* The only chrome that reacts to scroll. A data attribute rather than a class
     so it stays outside the shared class vocabulary. */
  const bar = document.querySelector('.topbar');
  if (!bar) return;
  if (host.scrollTop > 8) bar.setAttribute('data-scrolled', '1');
  else bar.removeAttribute('data-scrolled');
}

function shell_bind() {
  const btns = document.querySelectorAll('.rail-btn[data-page]');
  for (let i = 0; i < btns.length; i++) {
    btns[i].addEventListener('click', function () {
      go(this.getAttribute('data-page'));
    });
  }
  const q = shell_$('rail-quit');
  if (q) q.addEventListener('click', shell_quit);
  window.addEventListener('resize', shell_rail);
  const rt = shell_$('rail-toggle');
  if (rt) rt.addEventListener('click', shell_railToggle);
  const rail = shell_$('rail');
  if (rail) {
    rail.addEventListener('mouseenter', () => shell_railPeek(true));
    rail.addEventListener('mouseleave', () => shell_railPeek(false));
    rail.addEventListener('focusin', () => shell_railPeek(true));
    rail.addEventListener('focusout', e => { if (!rail.contains(e.relatedTarget)) shell_railPeek(false); });
  }
  const tog = shell_$('top-toggle');
  if (tog) tog.addEventListener('click', shell_toggle_pause);

  document.addEventListener('keydown', pal_key);
  document.addEventListener('keydown', shell_zoomKey);
  window.addEventListener('wheel', shell_zoomWheel, {passive: false});
  const zo = shell_$('zoom-out'), zi = shell_$('zoom-in'), zr = shell_$('zoom-reset');
  if (zo) zo.addEventListener('click', () => shell_zoomStep(-1));
  if (zi) zi.addEventListener('click', () => shell_zoomStep(1));
  if (zr) zr.addEventListener('click', () => shell_zoomSet(1));
  shell_zoomLoad();
  /* System follows Windows, which can flip to light mid-session. Held in a global: a
     MediaQueryList nothing refers to may be collected, and its listener with it. */
  shell_scheme = window.matchMedia ? matchMedia('(prefers-color-scheme: light)') : null;
  if (shell_scheme && shell_scheme.addEventListener) shell_scheme.addEventListener('change', shell_themeChanged);
  const ps = shell_$('rail-search');
  if (ps) ps.addEventListener('click', pal_open);
  const pq = shell_$('pal-q');
  if (pq) pq.addEventListener('input', () => { pal_at = 0; pal_draw(); });
  const scrim = shell_$('pal-scrim');
  if (scrim) scrim.addEventListener('click', e => {
    if (e.target === scrim) { pal_close(); return; }
    const row = e.target.closest ? e.target.closest('[data-pal]') : null;
    if (row) pal_run(Number(row.getAttribute('data-pal')));
  });

  const host = shell_$('views');
  if (host) host.addEventListener('scroll', () => shell_scrolled(host), {passive: true});
  shell_knobsBind();

  /* Reveal the skip link on focus without depending on CSS having a rule for
     it -- clearing the inline hide is enough to make it a normal link. */
  const skip = shell_$('skip-link');
  if (skip) {
    const hidden = skip.getAttribute('style');
    skip.addEventListener('focus', () => { skip.removeAttribute('style'); });
    skip.addEventListener('blur', () => { skip.setAttribute('style', hidden); });
  }
}

/* ---------------- boot ---------------- */

/* Pages this build cannot serve -- the Dashboard and Library on the macOS
   clipper, which has no engine to drive them (issue #193). Taken out of the
   rail and out of SHELL_PAGES, so go() sends a stale sessionStorage page to
   SHELL_BOOT.home instead. Their views stay in the document, unshown; nothing
   calls onShow on a page that cannot be reached. On Windows the list is
   empty and this does nothing. */
function shell_dropPages(pages) {
  for (let i = 0; i < pages.length; i++) {
    const at = SHELL_PAGES.indexOf(pages[i]);
    if (at >= 0) SHELL_PAGES.splice(at, 1);
    const btn = document.querySelector('.rail-btn[data-page="' + pages[i] + '"]');
    if (btn) btn.remove();
  }
}

async function shell_boot() {
  if (shell_booted) return;
  shell_booted = true;
  shell_bind();

  let b;
  try {
    b = await API.get('/api/bootstrap');
  } catch (e) {
    if (!shell_dead) shell_offline(true);
    return;
  }
  SHELL_BOOT = b || {};
  window.BOOT = SHELL_BOOT;      /* window property, not a lexical global, so a
                                    page declaring its own BOOT cannot clash */
  shell_dropPages(SHELL_BOOT.hide_pages || []);

  if (SHELL_BOOT.mode === 'setup') {
    const app = document.querySelector('.app');
    if (app) app.classList.add('hide');
    const root = shell_$('setup-root');
    if (root) root.classList.remove('hide');
    shell_call(window.PAGE_SETUP, 'start');
    return;
  }

  let start = SHELL_BOOT.home || 'dash';
  try { start = sessionStorage.getItem(SHELL_STORE_KEY) || start; } catch (e) { /* ok */ }
  go(start);
  shell_loop();
}

/* The orchestrator appends its own boot line, but page files assign their PAGE
   objects AFTER this block executes, so booting is deferred to a task either
   way and shell_boot() is idempotent. Whichever fires first wins. */
window.AUTOSTREAM_BOOT = shell_boot;
setTimeout(shell_boot, 0);
"""

SHELL_JS: str = _ICON_TABLE + _SHELL_BODY
