"""Library page: games apart from other apps, each game with two plain switches.

WHY TWO TABS
    The catalogue is everything Steam, Epic and the Start Menu hold, so on a
    real machine it was 79 "games" with Administrative Tools, Character Map and
    Command Prompt among them, and the dozen real games buried. Games are the
    apps AutoStream treats as games (`game` on /api/status's apps); the rest
    sit under Other apps, one "Move to Games" away.

WHAT THE TWO SWITCHES ARE
    Records is whether AutoStream treats the exe as a game at all, written to
    games.yaml where the watcher reads it (POST /api/library/game). Goes live
    is the app's own `stream` flag in apps.yaml (POST /api/library/stream),
    which is what offers "Open + stream" in the row's menu.

A ROW DOES NOT JUMP TABS UNDER THE POINTER
    Switching Records off makes an app "not a game", and the next poll would
    move its row to Other apps while the user is still looking at it. A row
    toggled here stays in the tab it was toggled in until the tab or the page
    is changed (lib_keep).

WHY EVENT DELEGATION INSTEAD OF INLINE onclick
    App keys come from Steam/Epic/Start Menu paths and can contain apostrophes.
    Keys travel in data-* attributes through one delegated listener instead,
    which also means a rebuilt list never loses its handlers.

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
<div class="searchbar lib-bar">
  <div class="seg lib-tabs" role="tablist" aria-label="Show">
    <button class="seg-btn is-active" type="button" role="tab" id="lib-tab-games"
            data-act="lib-tab" data-tab="games" aria-selected="true">Games
      <span class="lib-n" id="lib-n-games"></span></button>
    <button class="seg-btn" type="button" role="tab" id="lib-tab-apps"
            data-act="lib-tab" data-tab="apps" aria-selected="false">Other apps
      <span class="lib-n" id="lib-n-apps"></span></button>
  </div>
  <input class="input" id="lib-search" type="text" autocomplete="off" spellcheck="false"
         placeholder="Search games" aria-label="Search games">
  <span class="muted lib-count" id="lib-count"></span>
  <button class="btn" type="button" id="lib-rescan">"""
    + _svg("refresh")
    + """<span>Rescan</span></button>
</div>

<div class="panel hide" id="lib-livenote">"""
    + _svg("info")
    + """<p class="muted" id="lib-livetext"></p>
</div>

<div class="card lib-card">
  <div class="applist lib-list" id="lib-list" role="tabpanel" aria-labelledby="lib-tab-games"></div>
  <p class="muted lib-foot" id="lib-foot"></p>
</div>

<div class="empty hide" id="lib-empty">"""
    + _svg("library", 20)
    + """<p>No games here yet.</p>
  <p class="muted">Press <b>Rescan</b> to look through Steam, Epic and your Start Menu,
  or add entries by hand in <span class="mono">config/apps.yaml</span>.</p>
</div>

<div class="empty hide" id="lib-nomatch">
  <p class="muted">Nothing matches <b id="lib-nomatch-q"></b>.</p>
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
let lib_tab = 'games';    /* 'games' | 'apps'                                 */
let lib_keep = {};        /* app key -> tab it stays in until the tab changes */
let lib_menu = '';        /* key of the row whose menu is open                */
let lib_dirty = false;    /* a poll changed the list while a menu was open    */
let lib_saving = {};      /* 'key:act' -> a switch is being saved             */

/* What Ctrl K finds in the Library: games and apps by name. Opening one goes
   to the Library filtered to it, on the tab it lives in, rather than
   launching from a search box. */
pal_source('Games', function (q) {
  if (!String(q || '').trim()) return [];
  return lib_apps.filter(a => pal_match(q, a.name)).slice(0, 6).map(a => ({
    label: a.name, hint: a.game ? 'Game' : 'App',
    run: () => { go('library'); lib_setTab(a.game ? 'games' : 'apps');
                 const s = lib_el('lib-search');
                 if (s) { s.value = a.name; s.dispatchEvent(new Event('input')); } }}));
});
let lib_busy = false;     /* one launch in flight at a time                   */
let lib_scanning = false;
let lib_wired = false;

const lib_el = (id) => document.getElementById(id);

/* Superset of the shell's esc(): also escapes both quote characters, because
   app keys are interpolated into data-* attributes. */
const lib_esc = (t) => String(t == null ? '' : t)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

/* How the source reads on a row: a word, not the catalogue's lower-case id. */
const lib_SOURCES = {steam: 'Steam', epic: 'Epic', shortcut: 'Shortcut', manual: 'Added by hand'};

function lib_app(key) {
  for (let i = 0; i < lib_apps.length; i++) if (lib_apps[i].key === key) return lib_apps[i];
  return null;
}

function lib_name(key) {
  const a = lib_app(key);
  return (a && a.name) || key;
}

function lib_tabOf(a) {
  if (lib_keep[a.key]) return lib_keep[a.key];
  return a.game ? 'games' : 'apps';
}

/* Short and stable, so a changed thumbnail path is a new cover URL. */
function lib_hash(s) {
  let h = 5381;
  s = String(s || '');
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
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

  const bar = document.querySelector('#view-library .lib-tabs');
  if (bar) {
    bar.addEventListener('click', function (ev) {
      const t = ev.target && ev.target.closest && ev.target.closest('[data-act="lib-tab"]');
      if (t) lib_setTab(t.getAttribute('data-tab'));
    });
  }

  const list = lib_el('lib-list');
  if (list) {
    list.addEventListener('click', function (ev) {
      if (!ev.target || !ev.target.closest) return;
      const act = ev.target.closest('[data-act]');
      const what = act ? act.getAttribute('data-act') : '';
      const app = act ? act.getAttribute('data-app') : '';
      if (what === 'lib-more') { lib_openMenu(app, act); return; }
      if (what === 'lib-records') { lib_setGame(act, app, act.getAttribute('aria-checked') !== 'true'); return; }
      if (what === 'lib-move') { lib_setGame(act, app, true); return; }
      if (what === 'lib-golive') { lib_setStream(act, app, act.getAttribute('aria-checked') !== 'true'); return; }
      const t = ev.target.closest('button[data-thumb]');
      if (t) {
        lib_closeMenu();
        lib_thumb(t.getAttribute('data-thumb'), t.getAttribute('data-app'));
        return;
      }
      const b = ev.target.closest('button[data-key]');
      if (b) {
        lib_closeMenu();
        lib_launch(b, b.getAttribute('data-key'), b.getAttribute('data-stream') === '1');
      }
    });
    list.addEventListener('keydown', lib_menuKey);
  }

  /* A menu closes on any click outside it, the way every menu does. */
  document.addEventListener('click', function (ev) {
    if (!lib_menu) return;
    if (ev.target && ev.target.closest && ev.target.closest('.lib-more')) return;
    lib_closeMenu();
  });
}

function lib_setTab(tab) {
  tab = tab === 'apps' ? 'apps' : 'games';
  lib_keep = {};
  lib_menu = '';
  lib_tab = tab;
  const s = lib_el('lib-search');
  if (s) {
    const say = tab === 'games' ? 'Search games' : 'Search other apps';
    s.placeholder = say;
    s.setAttribute('aria-label', say);
  }
  ['games', 'apps'].forEach(function (t) {
    const b = lib_el('lib-tab-' + t);
    if (!b) return;
    b.classList.toggle('is-active', t === tab);
    b.setAttribute('aria-selected', t === tab ? 'true' : 'false');
  });
  const list = lib_el('lib-list');
  if (list) list.setAttribute('aria-labelledby', 'lib-tab-' + tab);
  lib_render();
}

/* ---------------- rows ---------------- */

function lib_initial(a) {
  return '<span class="lib-initial" aria-hidden="true">'
    + lib_esc(String(a.name || a.key || '?').charAt(0)) + '</span>';
}

function lib_cover(a) {
  if (!a.thumbnail) return '<span class="lib-cover is-blank">' + lib_initial(a) + '</span>';
  const src = '/api/library/cover?key=' + encodeURIComponent(a.game_key || a.key)
    + '&v=' + lib_hash(a.thumbnail) + '&k=' + encodeURIComponent(SHELL_K);
  /* A thumbnail moved since it was set falls back to the placeholder. */
  return '<span class="lib-cover"><img alt="" loading="lazy" decoding="async" src="'
    + lib_esc(src) + '" onerror="this.parentNode.classList.add(\'is-blank\');this.remove()">'
    + lib_initial(a) + '</span>';
}

function lib_switch(act, key, on, label, title) {
  const busy = !!lib_saving[key + ':' + (act === 'lib-golive' ? 'lib-golive' : 'lib-records')];
  return '<button class="switch lib-sw" type="button" role="switch" data-act="' + act
    + '" data-app="' + lib_esc(key) + '" aria-checked="' + (on ? 'true' : 'false') + '"'
    + (busy ? ' aria-disabled="true"' : '')
    + ' title="' + lib_esc(title) + '">'
    + '<span class="switch-track"><span class="switch-thumb"></span></span>'
    + '<span class="lib-sw-label">' + label + '</span></button>';
}

/* The row's "..." menu: the two ways to open the app, and its thumbnail. */
function lib_menuHtml(a) {
  const key = lib_esc(a.key);
  const open = lib_menu === a.key;
  let items = ''
    /* "Open" on a game used to mean "do nothing": no stream, and no recording
       either -- with streaming off in Settings, a game opened from here was
       simply not recorded. It now records and never streams, and says so. */
    + '<button class="lib-mi" type="button" role="menuitem" data-key="' + key
    + '" data-stream="0"'
    + (a.game
        ? ' title="Records the game and does not stream it (needs Recording '
          + 'on in Settings)">Open (record only)'
        : '>Open')
    + '</button>'
    + (a.stream
        ? '<button class="lib-mi" type="button" role="menuitem" data-key="' + key
          + '" data-stream="1">Open + stream</button>'
        : '');
  /* Only on things that will actually have a broadcast. NOT the same
     condition as "Open + stream": a game started through a launcher carries
     stream=false, because the launcher exits while the game runs -- true of
     Valorant and League. Those still go live, by being noticed once they are
     running, and they still want a thumbnail. */
  if (a.game || a.stream) {
    items += '<button class="lib-mi" type="button" role="menuitem" data-thumb="'
      + lib_esc(a.game_key || a.key) + '" data-app="' + key
      + '" title="' + (a.thumbnail ? 'Thumbnail: ' + lib_esc(a.thumbnail)
                                   : 'No thumbnail assigned') + '">'
      + (a.thumbnail ? 'Change thumbnail' : 'Set thumbnail') + '</button>';
  }
  return '<div class="lib-more">'
    + '<button class="btn btn-ghost btn-sm btn-icon" type="button" data-act="lib-more" data-app="'
    + key + '" aria-haspopup="menu" aria-expanded="' + (open ? 'true' : 'false')
    + '" aria-label="More for ' + lib_esc(a.name || a.key) + '" title="More">'
    + '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">'
    + '<circle cx="5" cy="12" r="1.6" fill="currentColor"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/>'
    + '<circle cx="19" cy="12" r="1.6" fill="currentColor"/></svg></button>'
    + '<div class="lib-menu' + (open ? '' : ' hide') + '" role="menu" aria-label="'
    + lib_esc(a.name || a.key) + '">' + items + '</div></div>';
}

function lib_row(a) {
  const key = a.key;
  const label = a.name || key;
  const name = lib_esc(label);
  const source = lib_esc(lib_SOURCES[a.source] || a.source || 'Added by hand');
  const id = '<div class="lib-id"><div class="app-name"><span title="' + name + '">' + name
    + '</span></div><div class="app-source">' + source + '</div></div>';
  if (lib_tabOf(a) === 'games') {
    return '<div class="app-card lib-row is-game" data-row="' + lib_esc(key) + '">'
      + lib_cover(a) + id
      + lib_switch('lib-records', key, !!a.game, 'Records',
                   a.game ? 'AutoStream treats ' + label + ' as a game'
                          : 'AutoStream ignores ' + label + ' when it runs')
      /* NOT "Goes live": this flag only decides whether the Library offers
         Open + stream for the game. Whether a detected game broadcasts is
         Settings' streaming switch, and a label saying otherwise would be a
         promise the engine does not keep. */
      + lib_switch('lib-golive', key, !!a.stream, 'Open + stream',
                   a.stream ? 'Offers Open + stream for ' + label
                            : 'Opens without streaming')
      + lib_menuHtml(a) + '</div>';
  }
  return '<div class="app-card lib-row is-app" data-row="' + lib_esc(key) + '">'
    + id
    + '<button class="btn btn-sm lib-move" type="button" data-act="lib-move" data-app="'
    + lib_esc(key) + '"' + (lib_saving[key + ':lib-records'] ? ' disabled' : '')
    + '>Move to Games</button>'
    + lib_menuHtml(a) + '</div>';
}

function lib_render() {
  const list = lib_el('lib-list');
  if (!list) return;
  lib_dirty = false;

  /* A switch pressed by keyboard must keep focus through the redraw it
     causes, or the next Space lands on nothing. */
  const was = document.activeElement;
  const focus = was && list.contains(was) && was.getAttribute
    ? [was.getAttribute('data-act'), was.getAttribute('data-app') || was.getAttribute('data-key'),
       was.getAttribute('data-stream')] : null;

  const q = lib_query;
  const inTab = lib_apps.filter(a => lib_tabOf(a) === lib_tab);
  const shown = q
    ? inTab.filter(a => String(a.name || a.key || '').toLowerCase().includes(q))
    : inTab;

  const nGames = lib_apps.filter(a => lib_tabOf(a) === 'games').length;
  const ng = lib_el('lib-n-games'), na = lib_el('lib-n-apps');
  if (ng) ng.textContent = lib_apps.length ? String(nGames) : '';
  if (na) na.textContent = lib_apps.length ? String(lib_apps.length - nGames) : '';

  const none = lib_apps.length === 0;
  const missed = !none && !!q && shown.length === 0;
  const blank = !none && !q && shown.length === 0;

  list.innerHTML = blank
    ? '<p class="lib-blank muted">' + (lib_tab === 'games'
        ? 'No games yet. Press Rescan, or move one across from Other apps.'
        : 'Every app in the Library is under Games.') + '</p>'
    : shown.map(lib_row).join('');
  list.classList.toggle('hide', none || missed);

  if (focus) {
    let sel = '';
    if (focus[0]) sel = '[data-act="' + focus[0] + '"][data-app="' + CSS.escape(focus[1] || '') + '"]';
    else if (focus[1]) sel = '[data-key="' + CSS.escape(focus[1]) + '"][data-stream="' + (focus[2] || '0') + '"]';
    const back = sel && list.querySelector(sel);
    if (back) back.focus();
  }

  const foot = lib_el('lib-foot');
  if (foot) {
    foot.textContent = none || missed ? '' : (lib_tab === 'games'
      ? 'Apps that aren\'t games, like Discord or Command Prompt, are under Other apps. Move one across if it should record.'
      : 'An app moved to Games is treated as a game: AutoStream starts a session when it is in front.');
  }

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
  if (count && !lib_scanning) count.textContent = q && !none ? shown.length + ' of ' + inTab.length : '';
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

/* ---------------- the "..." menu ---------------- */

function lib_openMenu(key, btn) {
  if (lib_menu === key) { lib_closeMenu(true); return; }
  lib_menu = key;
  const list = lib_el('lib-list');
  if (!list) return;
  list.querySelectorAll('.lib-more').forEach(function (m) {
    const b = m.querySelector('[data-act="lib-more"]');
    const menu = m.querySelector('.lib-menu');
    const mine = b === btn;
    if (menu) menu.classList.toggle('hide', !mine);
    if (b) b.setAttribute('aria-expanded', mine ? 'true' : 'false');
    /* Near the bottom of the window it opens upwards instead of off-screen. */
    if (mine && menu) {
      menu.classList.remove('is-up');
      const r = menu.getBoundingClientRect();
      if (r.bottom > window.innerHeight - 8) menu.classList.add('is-up');
      const first = menu.querySelector('.lib-mi');
      if (first) first.focus();
    }
  });
}

function lib_closeMenu(refocus) {
  if (!lib_menu) return;
  const list = lib_el('lib-list');
  const key = lib_menu;
  lib_menu = '';
  if (!list) return;
  if (lib_dirty) { lib_render(); }
  list.querySelectorAll('.lib-menu').forEach(m => m.classList.add('hide'));
  list.querySelectorAll('[data-act="lib-more"]').forEach(function (b) {
    b.setAttribute('aria-expanded', 'false');
    if (refocus && b.getAttribute('data-app') === key) b.focus();
  });
}

function lib_menuKey(ev) {
  if (!lib_menu) return;
  if (ev.key === 'Escape') { ev.preventDefault(); lib_closeMenu(true); return; }
  if (ev.key !== 'ArrowDown' && ev.key !== 'ArrowUp') return;
  const menu = ev.target && ev.target.closest && ev.target.closest('.lib-menu');
  if (!menu) return;
  const items = Array.prototype.slice.call(menu.querySelectorAll('.lib-mi'));
  const n = items.length;
  if (!n) return;
  ev.preventDefault();
  const i = items.indexOf(document.activeElement);
  items[(i + (ev.key === 'ArrowDown' ? 1 : -1) + n) % n].focus();
}

/* ---------------- the switches ---------------- */

async function lib_save(key, tag, url, body, apply) {
  const busy = key + ':' + tag;
  if (lib_saving[busy] || !key) return null;
  const a = lib_app(key);
  if (!a) return null;
  lib_saving[busy] = true;
  lib_keep[key] = lib_keep[key] || lib_tabOf(a);
  const before = Object.assign({}, a);
  apply(a);                           /* the switch moves at once */
  lib_render();
  let r = null;
  try {
    r = await API.post(url, body);
  } catch (e) {
    r = {error: 'Could not save that - see the log.'};
  }
  delete lib_saving[busy];
  if (r && r.error) {
    Object.assign(a, before);
    toast(r.error, 'error');
  }
  /* The next poll redraws from what the server now says. */
  lib_sig = '';
  lib_render();
  return r;
}

async function lib_setGame(btn, key, game) {
  if (!key || (btn && btn.getAttribute('aria-disabled') === 'true')) return;
  const move = !!btn && btn.getAttribute('data-act') === 'lib-move';
  const r = await lib_save(key, 'lib-records', '/api/library/game', {key: key, game: !!game},
                           a => { a.game = !!game; });
  /* A moved app leaves Other apps: that is the whole point of the button. */
  if (move && r && !r.error) {
    delete lib_keep[key];
    lib_render();
    toast(lib_name(key) + ' moved to Games.', 'ok');
  }
}

function lib_setStream(btn, key, stream) {
  if (!key || (btn && btn.getAttribute('aria-disabled') === 'true')) return null;
  return lib_save(key, 'lib-golive', '/api/library/stream', {key: key, stream: !!stream},
                  a => { a.stream = !!stream; });
}

/* ---------------- notes, thumbnail, launch, rescan ---------------- */

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

/* Assigning a thumbnail is a path, not a file upload: the image stays where the
   user made it, and games.yaml holds a reference. A prompt rather than a file
   dialog because the page is served over HTTP and cannot see the filesystem;
   the server checks the path exists before saving, so a typo is rejected with a
   reason rather than stored and discovered at go-live. */
async function lib_thumb(gameKey, appKey) {
  if (!gameKey) return;
  const app = lib_apps.filter(function (a) {
    return (a.game_key || a.key) === gameKey;
  })[0] || {};
  const now = app.thumbnail || '';
  const label = app.name || lib_name(appKey);
  const next = window.prompt(
    'Thumbnail for ' + label + '.\n\n'
    + 'Full path to a PNG or JPG. It is used exactly as given - nothing is '
    + 'drawn over it. Leave empty to go back to the automatic one.', now);
  if (next === null) return;                 /* cancelled */
  try {
    const r = await API.post('/api/games/thumbnail',
                             { key: gameKey, path: next.trim() });
    if (r && r.error) { toast(r.error, 'error'); return; }
    toast(next.trim() ? 'Thumbnail assigned to ' + label + '.'
                      : 'Thumbnail cleared for ' + label + '.', 'ok');
    lib_sig = '';                            /* force the next poll to re-render */
  } catch (e) {
    toast('Could not save that thumbnail.', 'error');
  }
}

async function lib_launch(btn, key, stream) {
  if (lib_busy || !key) return;
  lib_busy = true;
  if (btn) btn.disabled = true;

  const name = lib_name(key);
  try {
    const r = await API.post('/api/launch', { key: key, stream: !!stream });
    if (r && r.error) toast(r.error, 'error');
    else toast(stream ? 'Launching ' + name + ' and taking it live.' : 'Launching ' + name + '.', 'ok');
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
    const g = lib_apps.filter(a => a.game).length;
    const o = lib_apps.length - g;
    toast('Found ' + g + (g === 1 ? ' game' : ' games') + ' and ' + o
          + (o === 1 ? ' other app.' : ' other apps.'), 'ok');
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
    lib_keep = {};
    lib_menu = '';
    lib_ingest((typeof STATUS !== 'undefined' && STATUS && STATUS.apps) || []);
    lib_render();
    lib_note(typeof STATUS !== 'undefined' ? STATUS : null);
  },
  onTick: function (status) {
    if (lib_ingest((status && status.apps) || []) && !lib_scanning) {
      /* Not while a menu is open: the redraw would close it under the pointer. */
      if (lib_menu) lib_dirty = true;
      else lib_render();
    }
    lib_note(status);
  }
};
"""
