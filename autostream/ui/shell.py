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
    '<aside class="rail">'
    '<div class="rail-logo">'
    + LOGO_MARK
    + '<span class="rail-word">AutoStream</span>'
    # The only always-visible state when the rail is collapsed to 60px, so it
    # must NOT be a bare <span> — the narrow-width rule hides those.
    + '<span class="pill pill-idle" id="rail-dot" title="Idle"></span>'
    "</div>"
    '<nav class="rail-nav" aria-label="Pages">'
    + "".join(_nav_button(*n) for n in _NAV)
    + "</nav>"
    '<div class="rail-spacer"></div>'
    # Quit is detached from the four page links by a full-bleed rule so it can
    # never be misread as a fifth destination. .rail-foot supplies that bleed
    # and .rail-meta is what the narrow-rail rule hides — both are required.
    '<div class="rail-foot">'
    '<div class="divider"></div>'
    '<p class="rail-meta mono" id="rail-readout"></p>'
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
    '<h1 class="topbar-title" id="topbar-title">Dashboard</h1>'
    '<div class="topbar-meta">'
    # aria-live so a phase change is announced without the user hunting for it;
    # shell_setText() only writes when the value actually changed, so the two
    # second poll does not spam the screen reader.
    '<span class="pill pill-idle" id="top-pill" role="status"'
    ' aria-live="polite">IDLE</span>'
    '<span class="status-game hide" id="top-game"></span>'
    '<span class="mono" id="top-clock">--:--:--</span>'
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
    '<section class="view" id="view-settings" role="tabpanel"'
    ' aria-label="Settings">{{SETTINGS_HTML}}</section>'
    '<section class="view" id="view-logs" role="tabpanel"'
    ' aria-label="Logs">{{LOGS_HTML}}</section>'
    "</div>"
    "</main>"
    "</div>"
    '<div id="setup-root" class="hide">{{SETUP_HTML}}</div>'
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
const SHELL_PAGES = ['dash', 'library', 'settings', 'logs'];
const SHELL_TITLES = {dash: 'Dashboard', library: 'Library',
                      settings: 'Settings', logs: 'Logs'};
/* Page objects are looked up off window by name so a page file that failed to
   load cannot take the whole shell down with a ReferenceError. */
const SHELL_PAGE_OBJ = {dash: 'PAGE_DASH', library: 'PAGE_LIBRARY',
                        settings: 'PAGE_SETTINGS', logs: 'PAGE_LOGS'};
const SHELL_POLL_MS = 2000;
const SHELL_FAIL_LIMIT = 3;   /* misses before we admit we are disconnected */
const SHELL_STORE_KEY = 'autostream.page';

/* Engine phase -> pill modifier + wordmark. Colour is never the only channel:
   the wordmark always rides along with the dot. */
const SHELL_PHASE = {
  IDLE:     {pill: 'pill-idle', label: 'IDLE'},
  ARMING:   {pill: 'pill-warn', label: 'ARMING'},
  STARTING: {pill: 'pill-warn', label: 'STARTING'},
  TESTING:  {pill: 'pill-warn', label: 'TESTING'},
  LIVE:     {pill: 'pill-live', label: 'LIVE'},
  COOLDOWN: {pill: 'pill-idle', label: 'COOLDOWN'},
  STOPPING: {pill: 'pill-warn', label: 'STOPPING'}
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

function toast(message, kind) {
  const host = shell_$('toasts');
  if (!host) return;
  const el = document.createElement('div');
  el.className = 'toast is-' + (kind === 'warn' || kind === 'error' ? kind : 'ok');
  el.textContent = message === null || message === undefined ? '' : String(message);
  host.appendChild(el);
  const kill = () => { if (el.parentNode) el.parentNode.removeChild(el); };
  el.addEventListener('click', kill);
  setTimeout(kill, 3500);
  while (host.children.length > 4) host.removeChild(host.firstChild);
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

function go(page) {
  if (SHELL_PAGES.indexOf(page) < 0) page = 'dash';
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
  try { sessionStorage.setItem(SHELL_STORE_KEY, page); } catch (e) { /* private mode */ }
  shell_doc_title();

  const host = shell_$('views');
  if (host) { host.scrollTop = 0; shell_scrolled(host); }

  const P = window[SHELL_PAGE_OBJ[page]];
  shell_call(P, 'onShow');
  /* A page that just became visible should not sit blank for two seconds. */
  if (STATUS && STATUS.phase) shell_call(P, 'onTick', STATUS);
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
  if (s.blocked) { mod = 'pill-warn'; label = 'BLOCKED'; why = String(s.blocked); }
  else if (s.paused) { mod = 'pill-idle'; label = 'PAUSED'; why = 'Paused'; }

  shell_setPill(shell_$('rail-dot'), mod, null, label);
  shell_setPill(shell_$('top-pill'), mod, label, why);

  const game = shell_$('top-game');
  if (game) {
    shell_setText(game, s.game || '');
    game.classList.toggle('hide', !s.game);
  }
  shell_setText(shell_$('top-clock'), shell_hms(s.elapsed));

  /* One pause control, always in the same place, on every page. */
  const tog = shell_$('top-toggle');
  if (tog) {
    const running = phase !== 'IDLE' || s.paused;
    tog.classList.toggle('hide', !running);
    shell_setText(tog, s.paused ? 'Resume' : 'Pause');
  }

  const readout = shell_$('rail-readout');
  if (readout) {
    const bits = [];
    if (SHELL_BOOT.version) bits.push('v' + SHELL_BOOT.version);
    if (s.session) bits.push('session ' + s.session);
    if (s.quota_spent !== null && s.quota_spent !== undefined) {
      bits.push('quota ' + shell_group(s.quota_spent) + '/10,000');
    }
    shell_setText(readout, bits.join(' \u00b7 '));   /* escaped so the source file stays ASCII */
  }

  if (phase !== shell_phase_seen) { shell_phase_seen = phase; shell_doc_title(); }
}

function shell_offline(on) {
  if (shell_off === on) return;
  shell_off = on;
  if (!on) return;    /* the next successful paint repaints everything */
  shell_setPill(shell_$('top-pill'), 'pill-warn', 'OFFLINE',
                'AutoStream is not responding');
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
    const r = await API.post('/api/cmd', {command: STATUS.paused ? 'resume' : 'pause'});
    if (r && r.error) toast(r.error, 'error');
  } catch (e) {
    if (!shell_dead) toast('Could not reach AutoStream', 'error');
  }
  if (btn) btn.disabled = false;
}

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
  const tog = shell_$('top-toggle');
  if (tog) tog.addEventListener('click', shell_toggle_pause);

  const host = shell_$('views');
  if (host) host.addEventListener('scroll', () => shell_scrolled(host), {passive: true});

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

  if (SHELL_BOOT.mode === 'setup') {
    const app = document.querySelector('.app');
    if (app) app.classList.add('hide');
    const root = shell_$('setup-root');
    if (root) root.classList.remove('hide');
    shell_call(window.PAGE_SETUP, 'start');
    return;
  }

  let start = 'dash';
  try { start = sessionStorage.getItem(SHELL_STORE_KEY) || 'dash'; } catch (e) { /* ok */ }
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
