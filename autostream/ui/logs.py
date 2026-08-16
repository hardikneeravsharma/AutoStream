"""Logs page: an in-page tail of the daemon log file.

WHY AN IN-PAGE VIEW AT ALL
    The only log affordance used to be POST /api/logs/open, which shells out to
    os.startfile on the machine running the daemon. Over the LAN that opens a
    file on the *host*, not on the viewer's laptop, so from a phone or a second
    PC it does nothing observable. The tail endpoint is what makes the log
    actually readable from the UI; the open button stays as a secondary action
    for whoever is sitting at the streaming machine.

WHY THE AUTO-REFRESH TIMER POLICES ITSELF
    The page contract gives onShow() but no onHide(), so a naive setInterval
    would keep hitting the disk every five seconds while the user reads the
    Dashboard. The timer therefore checks whether #view-logs is still active and
    cancels itself when it is not; onShow() restarts it if the toggle is still
    on. Polling a rotating log file in the background while a game is running is
    pure waste.

WHY THE PARSER IS TOLERANT
    The endpoint is contracted to return {lines:[{ts,level,msg}]}, but the log
    formatter on disk emits "%(asctime)s %(levelname)-7s %(name)-18s %(message)s"
    and a plain array of strings is the obvious fallback implementation. Both
    shapes are accepted so a mismatch degrades to readable text rather than to
    "[object Object]" repeated three hundred times.

NAMING
    Every top-level JS name here is log_-prefixed; window.PAGE_LOGS is the one
    unprefixed global this file is allowed to declare (see the module contract).
"""
from __future__ import annotations

from .icons import ICONS


def _svg(name: str, size: int = 16) -> str:
    """Inline a 24x24 icon for static markup (see ui/library.py for the why)."""
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}"'
        f' aria-hidden="true" focusable="false">{ICONS[name]}</svg>'
    )


LOGS_HTML: str = (
    """
<div class="card">
  <div class="card-head">
    <div>
      <h2 class="card-title">Activity log</h2>
      <p class="card-sub"><span class="mono" id="log-path">config/logs/autostream.log</span></p>
    </div>
    <div class="field-inline">
      <label class="switch" title="Re-read the log every 5 seconds while this page is open">
        <input type="checkbox" id="log-auto">
        <span class="switch-track"><span class="switch-thumb"></span></span>
        <span>Auto-refresh</span>
      </label>
      <button class="btn btn-sm" type="button" id="log-refresh">"""
    + _svg("refresh", 14)
    + """<span>Refresh</span></button>
      <button class="btn btn-ghost btn-sm" type="button" id="log-open"
              title="Opens the file in an editor on the machine running AutoStream">"""
    + _svg("external", 14)
    + """<span>Open log file</span></button>
    </div>
  </div>

  <div class="card-body">
    <div class="field-inline" id="log-filters">
      <button class="btn btn-sm btn-primary" type="button" data-level="all" aria-pressed="true">All</button>
      <button class="btn btn-sm" type="button" data-level="info" aria-pressed="false">Info</button>
      <button class="btn btn-sm" type="button" data-level="warn" aria-pressed="false">Warning</button>
      <button class="btn btn-sm" type="button" data-level="error" aria-pressed="false">Error</button>
      <span class="muted" id="log-count"></span>
    </div>

    <div class="logview" id="log-pane"></div>
  </div>
</div>
"""
)


LOGS_JS: str = r"""
/* --------------------------------------------------------------------- logs */

/* "2026-08-16 06:10:00 INFO    autostream.webui  message" -- the formatter in
   __main__.setup_logging(). Only used when the endpoint hands back raw strings. */
const log_RE = /^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+([A-Za-z]+)\s+(.*)$/;

let log_lines = [];       /* normalised {ts, level, msg}                        */
let log_filter = 'all';
let log_timer = null;     /* auto-refresh interval handle, null when stopped    */
let log_wired = false;
let log_loading = false;
let log_err = '';
let log_sig = '';         /* skip identical re-renders on the 5s poll           */
let log_pin = true;       /* force a scroll to the end on the next render       */

const log_el = (id) => document.getElementById(id);

const log_esc = (t) => String(t == null ? '' : t)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

/* Python level names collapse onto the four chip styles the CSS defines. */
function log_kind(level) {
  const s = String(level == null ? '' : level).toUpperCase();
  if (s.indexOf('CRIT') === 0 || s.indexOf('FATAL') === 0 || s.indexOf('ERR') === 0) return 'error';
  if (s.indexOf('WARN') === 0) return 'warn';
  if (s.indexOf('DEBUG') === 0 || s.indexOf('TRACE') === 0) return 'debug';
  return 'info';
}

const log_LABEL = { error: 'ERROR', warn: 'WARN', debug: 'DEBUG', info: 'INFO' };

/* The row's time column is narrow on purpose: the date is the same for every
   line you are ever looking at, so only the clock earns the space. */
function log_time(ts) {
  if (ts == null || ts === '') return '';
  if (typeof ts === 'number') {
    const d = new Date(ts > 1e11 ? ts : ts * 1000);
    if (isNaN(d.getTime())) return '';
    const p = (n) => String(n).padStart(2, '0');
    return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }
  const s = String(ts).trim();
  const m = s.match(/\d{2}:\d{2}:\d{2}/);
  return m ? m[0] : s.slice(0, 12);
}

function log_norm(raw) {
  if (raw == null) return null;
  if (typeof raw === 'string') {
    if (!raw.trim()) return null;
    const m = raw.match(log_RE);
    return m ? { ts: m[1], level: m[2], msg: m[3] } : { ts: '', level: '', msg: raw };
  }
  return { ts: raw.ts, level: raw.level, msg: raw.msg == null ? '' : raw.msg };
}

function log_row(l) {
  const kind = log_kind(l.level);
  return '<div class="log-line">'
    + '<span class="log-time">' + log_esc(log_time(l.ts)) + '</span>'
    + '<span class="log-level is-' + kind + '">' + log_LABEL[kind] + '</span>'
    + '<span class="log-msg">' + log_esc(l.msg) + '</span>'
    + '</div>';
}

function log_render() {
  const pane = log_el('log-pane');
  if (!pane) return;

  const shown = log_filter === 'all'
    ? log_lines
    : log_lines.filter(function (l) { return log_kind(l.level) === log_filter; });

  const tail = shown.length ? shown[shown.length - 1] : null;
  const sig = log_filter + '|' + log_err + '|' + log_lines.length + '|' + shown.length
    + '|' + (tail ? log_time(tail.ts) + tail.msg : '');
  if (sig === log_sig && !log_pin) return;
  log_sig = sig;

  /* Same rule as the chat pane: only chase the tail if the reader was already
     at it. Someone scrolled up reading a stack trace must not get yanked down. */
  const near = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 60;

  if (log_err) {
    pane.innerHTML = '<div class="empty"><p>' + log_esc(log_err) + '</p>'
      + '<p class="muted">AutoStream may not have written anything yet, or the file is '
      + 'locked. Try Refresh, or open <span class="mono">'
      + log_esc((log_el('log-path') || {}).textContent || 'the log file')
      + '</span> directly.</p></div>';
  } else if (!log_lines.length) {
    pane.innerHTML = '<div class="empty"><p class="muted">The log is empty.</p></div>';
  } else if (!shown.length) {
    pane.innerHTML = '<div class="empty"><p class="muted">No '
      + log_esc(log_LABEL[log_filter] || log_filter) + ' lines in the last '
      + log_lines.length + '.</p></div>';
  } else {
    pane.innerHTML = shown.map(log_row).join('');
  }

  if (near || log_pin) pane.scrollTop = pane.scrollHeight;
  log_pin = false;

  const count = log_el('log-count');
  if (count) {
    count.textContent = log_err ? ''
      : (log_filter === 'all'
          ? log_lines.length + (log_lines.length === 1 ? ' line' : ' lines')
          : shown.length + ' of ' + log_lines.length + ' lines');
  }
}

async function log_load(quiet) {
  if (log_loading) return;
  log_loading = true;

  const pane = log_el('log-pane');
  if (!quiet && pane && !log_lines.length) {
    pane.innerHTML = '<div class="empty"><span class="spin"></span> Reading the log...</div>';
  }

  try {
    const r = await API.get('/api/logs/tail?n=300');
    const raw = (r && r.lines) || [];
    log_lines = raw.map(log_norm).filter(function (l) { return !!l; });
    log_err = '';
    const path = log_el('log-path');
    if (path && r && r.path) path.textContent = r.path;
  } catch (e) {
    log_err = 'Could not read the log file.';
  }

  log_loading = false;
  log_render();
}

/* ---- auto-refresh -------------------------------------------------------- */

function log_active() {
  const v = log_el('view-logs');
  return !!(v && v.classList.contains('is-active'));
}

function log_stopAuto() {
  if (log_timer) { clearInterval(log_timer); log_timer = null; }
}

function log_startAuto() {
  log_stopAuto();
  log_timer = setInterval(function () {
    /* No onHide() in the page contract, so the timer retires itself the moment
       the Logs view stops being the active one. */
    if (!log_active()) { log_stopAuto(); return; }
    log_load(true);
  }, 5000);
}

function log_setFilter(v) {
  log_filter = v;
  log_pin = true;
  const box = log_el('log-filters');
  if (box) {
    const btns = box.querySelectorAll('button[data-level]');
    for (let i = 0; i < btns.length; i++) {
      const on = btns[i].getAttribute('data-level') === v;
      btns[i].classList.toggle('btn-primary', on);
      btns[i].setAttribute('aria-pressed', on ? 'true' : 'false');
    }
  }
  log_render();
}

async function log_open() {
  try {
    await API.post('/api/logs/open', {});
    toast('Opening the log on the machine running AutoStream.', 'ok');
  } catch (e) {
    toast('Could not open the log file.', 'error');
  }
}

function log_wire() {
  if (log_wired) return;
  log_wired = true;

  const filters = log_el('log-filters');
  if (filters) {
    filters.addEventListener('click', function (ev) {
      const b = ev.target && ev.target.closest ? ev.target.closest('button[data-level]') : null;
      if (b) log_setFilter(b.getAttribute('data-level'));
    });
  }

  const refresh = log_el('log-refresh');
  if (refresh) refresh.addEventListener('click', function () { log_pin = true; log_load(false); });

  const open = log_el('log-open');
  if (open) open.addEventListener('click', log_open);

  const auto = log_el('log-auto');
  if (auto) {
    auto.addEventListener('change', function () {
      if (auto.checked) { log_startAuto(); log_load(true); } else { log_stopAuto(); }
    });
  }
}

window.PAGE_LOGS = {
  onShow: function () {
    log_wire();
    log_pin = true;
    log_load(false);
    const auto = log_el('log-auto');
    if (auto && auto.checked) log_startAuto();
  }
};
"""
