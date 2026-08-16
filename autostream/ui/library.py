"""Library page: the installed-game list and the two ways to launch one.

WHY THIS IS A LIST AND NOT A TILE GRID
    There is no cover art available offline, so a tile would be a name, a source
    string and two buttons floating in empty space -- and sixty of those is a wall
    of noise. The row list is scannable at a glance and stays readable at the
    420px window floor, which a 248px-minimum tile grid does not.

WHY THE LIBRARY STAYS VISIBLE WHILE LIVE
    The old dashboard hid the launcher during a broadcast, which was exactly
    backwards: switching games mid-session is the product's whole reason to exist.
    Instead a quiet inline note explains what "Open + stream" does to the running
    broadcast, so the user is informed rather than blocked.

WHY EVENT DELEGATION INSTEAD OF INLINE onclick
    App keys come from Steam/Epic/Start Menu paths and can contain apostrophes.
    The shared esc() helper escapes & < > but NOT quotes, so interpolating a key
    into onclick="lib_launch('...')" breaks on those apps. Keys travel in
    data-key attributes through a single delegated listener instead, which also
    means a rebuilt list never loses its handlers.

NAMING
    Every top-level JS name here is lib_-prefixed; window.PAGE_LIBRARY is the one
    unprefixed global this file is allowed to declare (see the module contract).
"""
from __future__ import annotations

from .icons import ICONS


def _svg(name: str, size: int = 16) -> str:
    """Inline a 24x24 icon for static markup.

    The shell's icon() is a JS function and cannot run inside a Python string,
    so chrome that ships in the HTML constant is wrapped here instead. Same
    viewBox and same currentColor as the shell wrapper, so the two are
    interchangeable on screen.
    """
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}"'
        f' aria-hidden="true" focusable="false">{ICONS[name]}</svg>'
    )


LIBRARY_HTML: str = (
    """
<div class="searchbar">
  <input class="input" id="lib-search" type="text" autocomplete="off" spellcheck="false"
         placeholder="Search games" aria-label="Search games">
  <button class="btn" type="button" id="lib-rescan">"""
    + _svg("refresh")
    + """<span>Rescan</span></button>
  <span class="muted" id="lib-count"></span>
</div>

<div class="panel hide" id="lib-livenote">"""
    + _svg("info")
    + """<p class="muted" id="lib-livetext"></p>
</div>

<div class="card">
  <div class="applist" id="lib-list"></div>
</div>

<div class="empty hide" id="lib-empty">"""
    + _svg("library", 20)
    + """<p>No games here yet.</p>
  <p class="muted">Press <b>Rescan</b> to look through Steam, Epic and your Start Menu,
  or add entries by hand in <span class="mono">config/apps.yaml</span>.</p>
</div>

<div class="empty hide" id="lib-nomatch">
  <p class="muted">Nothing matches <b class="mono" id="lib-nomatch-q"></b>.</p>
</div>
"""
)


LIBRARY_JS: str = r"""
/* ------------------------------------------------------------------ library */

/* Phases during which a broadcast exists, so "Open + stream" would switch the
   running stream rather than start a new one. */
const lib_LIVE = ['STARTING', 'TESTING', 'LIVE', 'COOLDOWN'];

let lib_apps = [];        /* last apps array seen on /api/status              */
let lib_sig = '';         /* signature of lib_apps, to skip identical renders */
let lib_query = '';
let lib_busy = false;     /* one launch in flight at a time                   */
let lib_scanning = false;
let lib_wired = false;

const lib_el = (id) => document.getElementById(id);

/* Superset of the shell's esc(): also escapes both quote characters, because
   app keys are interpolated into data-key="..." attributes. */
const lib_esc = (t) => String(t == null ? '' : t)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

function lib_name(key) {
  for (let i = 0; i < lib_apps.length; i++) {
    if (lib_apps[i].key === key) return lib_apps[i].name || key;
  }
  return key;
}

function lib_wire() {
  if (lib_wired) return;
  lib_wired = true;

  const search = lib_el('lib-search');
  if (search) {
    search.addEventListener('input', function () {
      lib_query = (search.value || '').toLowerCase().trim();
      lib_render();
    });
  }

  const rescan = lib_el('lib-rescan');
  if (rescan) rescan.addEventListener('click', lib_rescan);

  const list = lib_el('lib-list');
  if (list) {
    list.addEventListener('click', function (ev) {
      const b = ev.target && ev.target.closest ? ev.target.closest('button[data-key]') : null;
      if (b) lib_launch(b, b.getAttribute('data-key'), b.getAttribute('data-stream') === '1');
    });
  }
}

function lib_row(a) {
  const key = lib_esc(a.key);
  const name = lib_esc(a.name || a.key);
  const source = lib_esc(String(a.source || 'manual').toUpperCase());
  return '<div class="app-card">'
    + '<div class="app-name" title="' + name + '">' + name + '</div>'
    + '<div class="app-source">' + source + '</div>'
    + '<div class="app-actions">'
    + '<button class="btn btn-ghost btn-sm" type="button" data-key="' + key
    + '" data-stream="0">Open</button>'
    + (a.stream
        ? '<button class="btn btn-sm" type="button" data-key="' + key
          + '" data-stream="1">Open + stream</button>'
        : '')
    + '</div></div>';
}

function lib_render() {
  const list = lib_el('lib-list');
  if (!list) return;

  const q = lib_query;
  const shown = q
    ? lib_apps.filter(function (a) {
        return String(a.name || a.key || '').toLowerCase().includes(q);
      })
    : lib_apps.slice();

  list.innerHTML = shown.map(lib_row).join('');

  const none = lib_apps.length === 0;
  const missed = !none && shown.length === 0;

  const empty = lib_el('lib-empty');
  if (empty) empty.classList.toggle('hide', !none);

  const nomatch = lib_el('lib-nomatch');
  if (nomatch) {
    nomatch.classList.toggle('hide', !missed);
    const qs = lib_el('lib-nomatch-q');
    if (qs) qs.textContent = q;
  }

  /* While a scan is running the count line holds the spinner; a poll-driven
     re-render must not wipe that out from under it. */
  const count = lib_el('lib-count');
  if (count && !lib_scanning) {
    if (none) count.textContent = '';
    else if (q) count.textContent = shown.length + ' of ' + lib_apps.length + ' games';
    else count.textContent = lib_apps.length + (lib_apps.length === 1 ? ' game' : ' games');
  }
}

/* Returns true when the list actually changed, so callers can skip the render. */
function lib_ingest(apps) {
  const next = Array.isArray(apps) ? apps : [];
  const sig = JSON.stringify(next);
  if (sig === lib_sig) return false;
  lib_sig = sig;
  lib_apps = next;
  return true;
}

function lib_note(status) {
  const note = lib_el('lib-livenote');
  if (!note) return;
  const s = status || {};
  const live = lib_LIVE.indexOf(s.phase) >= 0;
  note.classList.toggle('hide', !live);
  const t = lib_el('lib-livetext');
  if (live && t) {
    t.textContent = 'You are on air'
      + (s.game ? ' with ' + s.game : '')
      + '. Opening another game with "Open + stream" retitles this broadcast and '
      + 'switches it over - it does not start a second one.';
  }
}

async function lib_launch(btn, key, stream) {
  if (lib_busy || !key) return;
  lib_busy = true;
  if (btn) btn.disabled = true;

  const name = lib_name(key);
  try {
    await API.post('/api/launch', { key: key, stream: !!stream });
    toast(stream ? 'Launching ' + name + ' and taking it live.' : 'Launching ' + name + '.', 'ok');
  } catch (e) {
    toast('Could not launch ' + name + '.', 'error');
  }

  /* The engine needs a moment to notice the new process. Re-enabling instantly
     invites the second click this guard exists to prevent. If the list has been
     rebuilt by then the button is detached, which is harmless. */
  setTimeout(function () {
    lib_busy = false;
    if (btn) btn.disabled = false;
  }, 1200);
}

async function lib_rescan() {
  if (lib_scanning) return;
  lib_scanning = true;

  const b = lib_el('lib-rescan');
  const count = lib_el('lib-count');
  if (b) b.disabled = true;
  if (count) count.innerHTML = '<span class="spin"></span> Scanning Steam, Epic and the Start Menu...';

  try {
    const r = await API.post('/api/apps/scan', {});
    lib_ingest(r && r.apps ? r.apps : []);
    lib_scanning = false;
    lib_render();
    const n = (r && r.count != null) ? r.count : lib_apps.length;
    toast('Found ' + n + (n === 1 ? ' game.' : ' games.'), 'ok');
  } catch (e) {
    lib_scanning = false;
    lib_render();
    toast('Scan failed - see the log.', 'error');
  }
  if (b) b.disabled = false;
}

window.PAGE_LIBRARY = {
  onShow: function () {
    lib_wire();
    lib_ingest((typeof STATUS !== 'undefined' && STATUS && STATUS.apps) || []);
    lib_render();
    lib_note(typeof STATUS !== 'undefined' ? STATUS : null);
  },
  onTick: function (status) {
    if (lib_ingest((status && status.apps) || []) && !lib_scanning) lib_render();
    lib_note(status);
  }
};
"""
