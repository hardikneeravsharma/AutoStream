"""The Settings page: one real control for every key in CONFIG_SCHEMA.

The old page shipped a raw YAML textarea, which meant every setting was a
guessing game about spelling, units and legal values, and a typo took the
daemon down at the next start. This page renders the schema instead: the
server describes the config once (autostream/schema.py) and the browser draws
the matching control, so a new key needs no JavaScript at all.

Three decisions here are load-bearing rather than cosmetic:

Nothing saves on change. Edits collect into a dirty set and go out in one
POST, because config.yaml is read by a daemon that is very likely mid-session;
a half-applied form is worse than an unapplied one. The sticky action bar only
exists while there is something to lose.

The client validates with the same rules the server does, but the server still
decides. Client checks exist to catch the obvious mistake without a round
trip; per-field errors that come back stay dirty, so a failed field is never
silently forgotten while its neighbours save.

The theme picker is the one exception: it applies immediately through the
existing /api/theme, because a colour scheme you cannot see until you press
Save is not a colour scheme you can choose.
"""
from __future__ import annotations

import json

from ..schema import GROUPS

# NINETY KEYS ACROSS TWELVE SECTIONS. Finding one meant knowing which section
# somebody had filed it under, and the names are not always the guess a person
# makes -- the clip length lives under Clips, the clip UPLOAD privacy under
# Clips too, and the stream privacy under Stream. Searching asks nothing of
# that. The box itself sits in the top bar (set_searchBox), where the approved
# layout puts it; the count and the empty answer stay with the results.
SET_SEARCH_BOX = (
    '<div class="set-topsearch">'
    '<input class="input" id="set-search" type="search" autocomplete="off"'
    ' spellcheck="false" aria-label="Search every setting"'
    ' placeholder="Search settings">'
    '</div>'
)

SETTINGS_HTML = r"""
<div class="settings-layout">
  <nav class="settings-nav" id="set-nav" aria-label="Settings sections"></nav>
  <div class="settings-body">
    <p class="settings-search-count" id="set-search-count"
       role="status" aria-live="polite"></p>
    <div id="set-panels">
      <div class="empty"><span class="spin"></span> Loading settings...</div>
    </div>
    <div class="card settings-noresult hide" id="set-noresult">
      <p>Nothing here matches <b id="set-noresult-q"></b>.</p>
      <p class="muted">Try a shorter word, or part of the key -- searching
         looks through the names, the explanations and the keys themselves.</p>
    </div>
    <div class="card set-about" id="set-about">
      <div class="card-head">
        <div>
          <h2 class="card-title">This version</h2>
          <p class="card-sub" id="set-ver-sub">&nbsp;</p>
        </div>
        <div class="field-inline">
          <button class="btn btn-sm" type="button" id="set-ver-check">
            <span>Check for updates</span></button>
          <button class="btn btn-primary btn-sm hide" type="button" id="set-ver-get">
            <span>Download</span></button>
          <button class="btn btn-primary btn-sm hide" type="button" id="set-ver-open">
            <span>Open the installer</span></button>
        </div>
      </div>
      <div class="card-body hide" id="set-ver-body">
        <div class="meter hide" id="set-ver-meter" role="progressbar"
             aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
          <span class="meter-fill" id="set-ver-fill"></span></div>
        <p class="muted" id="set-ver-msg"></p>
        <details id="set-ver-noteswrap" class="hide">
          <summary>What changed</summary>
          <pre class="set-ver-notes" id="set-ver-notes"></pre>
        </details>
      </div>
    </div>

    <div class="card set-about" id="set-trouble">
      <div class="card-head">
        <div>
          <h2 class="card-title">Something is not working</h2>
          <p class="card-sub">A report about this install: versions, whether
             OBS and ffmpeg were found, your settings with the secrets taken
             out, and the last forty lines of the log.</p>
        </div>
        <div class="field-inline">
          <button class="btn btn-sm" type="button" id="set-diag-get">
            <span>Build a report</span></button>
          <button class="btn btn-sm hide" type="button" id="set-diag-copy">
            <span>Copy it</span></button>
        </div>
      </div>
      <div class="card-body hide" id="set-diag-body">
        <p class="muted" id="set-diag-msg"></p>
        <textarea class="set-diag-text hide" id="set-diag-text" readonly
                  spellcheck="false" aria-label="Diagnostic report"></textarea>
      </div>
    </div>

    <div class="settings-actions hide" id="set-actions">
      <span class="muted" id="set-count">No unsaved changes</span>
      <div class="field-inline">
        <button class="btn btn-ghost" type="button" id="set-discard">Discard</button>
        <button class="btn btn-primary" type="button" id="set-save">Save changes</button>
      </div>
    </div>
  </div>
</div>
"""

SETTINGS_JS = (
    "/* The nav's four headings, from autostream/schema.py, and the search box\n"
    "   the page puts in the top bar. */\n"
    "var set_GROUPS = " + json.dumps(GROUPS) + ";\n"
    "var set_SEARCH_BOX = " + json.dumps(SET_SEARCH_BOX) + ";\n"
) + r"""
/* ============================ settings page ============================ */

var set_state = {
  loaded: false, loading: false, wired: false, guarded: false,
  sections: [], fields: {}, values: {}, tags: {},
  themes: [], theme: '', active: '', saving: false,
  platforms: {}          /* twitch/kick: configured + connected */
};

var set_timeRe = /^([01]?[0-9]|2[0-3]):([0-5][0-9])$/;

/* ---------------------------------------------------------- small helpers */

function set_slug(path){ return String(path).replace(/[^A-Za-z0-9]+/g, '-'); }

function set_attr(v){
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function set_el(id){ return document.getElementById(id); }
/* What is typed in the search box. Held here rather than read from the DOM
   so a re-render cannot silently drop the filter. */
var set_query = '';

function set_show(id, on){
  var el = set_el(id);
  if (el) el.classList.toggle('hide', !on);
}

function set_num(v){
  if (v === null || v === undefined || v === '') return null;
  var n = Number(v);
  return isFinite(n) ? n : null;
}

function set_unit(f, n){
  var txt = String(n);
  return f.unit ? txt + ' ' + f.unit : txt;
}

/* Normalise a server value into the shape the control round-trips. Without
   this a null overlay_source and an empty text box look like a change. */
function set_norm(f, v){
  var c = f.control;
  if (c === 'toggle') return v === true;
  if (c === 'number') { var n = set_num(v); return n === null ? '' : n; }
  if (c === 'taglist') {
    if (!Array.isArray(v)) return [];
    return v.map(function(x){ return String(x == null ? '' : x); })
            .filter(function(x){ return x !== ''; });
  }
  if (c === 'time_range') {
    if (!Array.isArray(v) || v.length !== 2) return [];
    var a = String(v[0] == null ? '' : v[0]), b = String(v[1] == null ? '' : v[1]);
    return (a === '' && b === '') ? [] : [a, b];
  }
  return v == null ? '' : String(v);
}

function set_same(a, b){
  try { return JSON.stringify(a) === JSON.stringify(b); }
  catch (e) { return a === b; }
}

function set_options(f){
  if (f.path === 'ui.theme' && set_state.themes.length) {
    return set_state.themes.map(function(t){
      return { value: String(t.id), label: String(t.label || t.id) };
    });
  }
  return (f.options || []).map(function(o){
    return { value: String(o.value), label: String(o.label == null ? o.value : o.label) };
  });
}

/* ------------------------------------------------------------ validation */

function set_validate(f, v){
  var c = f.control;
  if (c === 'readonly') return null;
  if (c === 'toggle') return (v === true || v === false) ? null : 'Expected true or false.';

  if (c === 'number'){
    if (v === '' || v === null || v === undefined) return 'Enter a number.';
    var n = Number(v);
    if (!isFinite(n)) return 'Enter a number.';
    if (f.integer !== false && Math.abs(n - Math.round(n)) > 1e-9) return 'Enter a whole number.';
    if (f.min !== null && f.min !== undefined && n < f.min)
      return 'Must be ' + set_unit(f, f.min) + ' or more.';
    if (f.max !== null && f.max !== undefined && n > f.max)
      return 'Must be ' + set_unit(f, f.max) + ' or less.';
    return null;
  }

  if (c === 'select'){
    var legal = set_options(f).map(function(o){ return o.value; });
    if (legal.length && legal.indexOf(String(v)) < 0) return 'Choose one of the listed options.';
    return null;
  }

  if (c === 'taglist'){
    if (!Array.isArray(v)) return 'Expected a list of entries.';
    var per = f.item_max_chars || 120;
    for (var i = 0; i < v.length; i++){
      if (String(v[i]).length > per) return 'Each entry must be under ' + per + ' characters.';
    }
    if (f.max_items && v.length > f.max_items) return 'At most ' + f.max_items + ' entries.';
    return null;
  }

  if (c === 'time_range'){
    if (!Array.isArray(v) || v.length === 0) return null;
    var a = String(v[0] || '').trim(), b = String(v[1] || '').trim();
    if (a === '' && b === '') return null;
    if (a === '' || b === '')
      return 'Set both times, or clear both to allow streaming at any hour.';
    if (!set_timeRe.test(a) || !set_timeRe.test(b))
      return 'Use 24-hour times like 23:30.';
    if (a === b) return 'Start and end cannot be the same time.';
    return null;
  }

  var text = String(v == null ? '' : v);
  if (f.max_chars && text.length > f.max_chars)
    return 'Keep this under ' + f.max_chars + ' characters.';
  if (!text && f.required) return 'This cannot be left empty.';
  return null;
}

/* --------------------------------------------------------- control markup */

function set_controlHtml(f){
  var slug = set_slug(f.path);
  var id = 'set-f-' + slug;
  var v = set_state.values[f.path];
  var ph = f.placeholder ? ' placeholder="' + set_attr(f.placeholder) + '"' : '';
  var maxc = f.max_chars ? ' maxlength="' + f.max_chars + '"' : '';
  var lab = ' aria-labelledby="set-l-' + slug + '"';
  var c = f.control;

  if (f.path === 'ui.theme') return set_themesHtml();

  if (c === 'select'){
    var opts = set_options(f).map(function(o){
      return '<option value="' + set_attr(o.value) + '"' +
             (String(v) === o.value ? ' selected' : '') + '>' + esc(o.label) + '</option>';
    }).join('');
    return '<select class="select" id="' + id + '"' + lab + '>' + opts + '</select>';
  }

  if (c === 'toggle'){
    return set_switchHtml(id, v === true, lab);
  }

  if (c === 'number'){
    var attrs = '';
    if (f.min !== null && f.min !== undefined) attrs += ' min="' + set_attr(f.min) + '"';
    if (f.max !== null && f.max !== undefined) attrs += ' max="' + set_attr(f.max) + '"';
    attrs += ' step="' + set_attr(f.step || (f.integer === false ? 'any' : 1)) + '"';
    return '<div class="field-inline">' +
      '<input class="input" type="number" inputmode="decimal" id="' + id + '"' +
      attrs + ph + lab + ' value="' + set_attr(v) + '">' +
      (f.unit ? '<span class="muted">' + esc(f.unit) + '</span>' : '') +
      '</div>';
  }

  if (c === 'password'){
    return '<div class="field-inline">' +
      '<input class="input mono" type="password" id="' + id + '"' + ph + maxc + lab +
      ' autocomplete="off" spellcheck="false" value="' + set_attr(v) + '">' +
      '<button class="btn btn-ghost btn-sm btn-icon" type="button" data-act="reveal"' +
      ' aria-label="Show value" title="Show value">' + icon('eye') + '</button>' +
      '</div>';
  }

  if (c === 'textarea'){
    return '<textarea class="textarea mono" id="' + id + '" rows="3"' + ph + maxc + lab +
           ' spellcheck="false">' + esc(v) + '</textarea>';
  }

  if (c === 'time_range'){
    var arr = Array.isArray(v) && v.length === 2 ? v : ['', ''];
    return '<div class="field-inline">' +
      '<input class="input mono" type="time" id="' + id + '-a" value="' + set_attr(arr[0]) + '"' +
      ' aria-label="Quiet hours start">' +
      '<span class="muted">to</span>' +
      '<input class="input mono" type="time" id="' + id + '-b" value="' + set_attr(arr[1]) + '"' +
      ' aria-label="Quiet hours end">' +
      '<button class="btn btn-ghost btn-sm" type="button" data-act="clear-time">Clear</button>' +
      '</div>';
  }

  if (c === 'taglist'){
    return '<div class="taglist" id="' + id + '">' + set_tagsHtml(f) + '</div>';
  }

  if (c === 'readonly'){
    var shown = String(v == null ? '' : v);
    return '<div class="field-inline">' +
      '<input class="input mono" type="text" id="' + id + '" readonly tabindex="0"' + lab +
      ' value="' + set_attr(shown || 'not set') + '">' +
      '<button class="btn btn-ghost btn-sm btn-icon" type="button" data-act="copy"' +
      ' aria-label="Copy value" title="Copy value">' + icon('copy') + '</button>' +
      '</div>';
  }

  return '<input class="input" type="text" id="' + id + '"' + ph + maxc + lab +
         ' value="' + set_attr(v) + '">';
}

function set_switchHtml(id, on, extra){
  return '<button class="switch" type="button" role="switch" id="' + id + '"' +
    ' aria-checked="' + (on ? 'true' : 'false') + '"' + (extra || '') + ' data-act="toggle">' +
    '<span class="switch-track"><span class="switch-thumb"></span></span></button>';
}

function set_tagsHtml(f){
  var list = set_state.tags[f.path] || [];
  var chips = list.map(function(t, i){
    return '<span class="tag">' + esc(t) +
      '<button class="tag-x" type="button" data-act="tag-x" data-i="' + i + '"' +
      ' aria-label="Remove ' + set_attr(t) + '">' + icon('x') + '</button></span>';
  }).join('');
  var full = f.max_items && list.length >= f.max_items;
  return chips + '<input class="tag-add" type="text"' +
    (full ? ' disabled' : '') +
    ' placeholder="' + set_attr(full ? 'limit reached' : (f.placeholder || 'Add and press Enter')) +
    '" aria-label="Add an entry to ' + set_attr(f.label || f.path) + '">';
}

function set_themesHtml(){
  var list = set_state.themes;
  if (!list.length) return '<p class="field-help">No themes available.</p>';
  var cur = set_state.theme || set_state.values['ui.theme'];
  /* System, Dark, Light as one segmented control: three words need no swatch. */
  return '<div class="seg" id="set-themes" role="radiogroup" aria-label="Theme">' + list.map(function(t){
    var on = String(t.id) === String(cur);
    return '<button class="seg-btn' + (on ? ' is-active' : '') + '" type="button" role="radio"' +
      ' data-act="theme" data-theme="' + set_attr(t.id) + '"' +
      ' aria-checked="' + (on ? 'true' : 'false') + '">' + esc(t.label || t.id) + '</button>';
  }).join('') + '</div>';
}

/* ------------------------------------------------------------- page markup */

/* THE CONFIG KEY IS FOR THE PERSON WHO ASKED FOR IT. `ui.theme` under a
   label called Theme is a second name for the same thing, in a language a
   stranger does not speak, on every one of ninety rows. It stays where
   somebody has said they want the machinery: the Advanced section, whose
   values are written by setup and are pasted out of logs, and anywhere at
   all once Developer mode is on. The search still matches it either way. */
function set_keyShown(secId, dev){
  return secId === 'advanced' || dev === true;
}

/* Controls that need the row's whole width -- a paragraph, a list of tags --
   sit under the words. Everything else sits on the right of them. */
var set_WIDE = {textarea: 1, taglist: 1};

function set_fieldHtml(f, secId){
  var slug = set_slug(f.path);
  /* time_range owns two inputs, so the label points at the first one. */
  var target = f.control === 'time_range' ? 'set-f-' + slug + '-a' : 'set-f-' + slug;
  var marks = '';
  if (f.restart) marks += '<span class="set-flag">Needs a restart</span>';
  if (f.danger) marks += '<span class="set-flag">Asks before saving</span>';
  var help = f.help ? '<p class="field-help">' + esc(f.help) + '</p>' : '';
  if (f.danger && f.control === 'readonly'){
    help += '<p class="field-help"><b>Written by setup.</b> Changing this by hand ' +
            'breaks the next session without warning.</p>';
  }
  var key = '';
  if (set_keyShown(secId, set_state.values['ui.developer_mode'] === true)){
    key = '<div class="field-key">' + esc(f.path) + '</div>';
  }
  var only = (f.only_for && f.only_for.length)
    ? ' data-only="' + set_attr(f.only_for.join(' ')) + '"' : '';
  /* WHAT A SEARCH LOOKS THROUGH, built once at render rather than read off
     the DOM on every keystroke. The key is in here because people paste keys
     out of the docs and the log, and the help text because the word somebody
     remembers is usually in the explanation rather than in the label --
     "quota" appears in no label on this page. */
  var find = ' data-find="' + set_attr(
    ((f.label || '') + ' ' + f.path + ' ' + (f.help || '')).toLowerCase()) + '"';
  return '<div class="field" data-path="' + set_attr(f.path) + '"' + only + find +
    ' id="set-w-' + slug + '">' +
    '<div class="set-row' + (set_WIDE[f.control] ? ' set-row-wide' : '') + '">' +
      '<div class="set-row-text">' +
        '<div class="set-row-head">' +
          '<label class="field-label" id="set-l-' + slug + '" for="' + target + '">' +
            esc(f.label || f.path) + '</label>' + marks +
        '</div>' +
        help + key +
        '<p class="field-error hide" id="set-e-' + slug + '"></p>' +
      '</div>' +
      '<div class="set-row-control">' + set_controlHtml(f) + '</div>' +
    '</div>' +
  '</div>';
}

/* Fills the three screen-saver fields from the channel's overlays. The values
   are only PUT IN THE FORM, never saved behind the user's back: a channel can
   hold two installs of the same theme -- and this one does -- so which copy is
   the live one is a choice, not something a name can settle. */
async function set_wireStreamElements(){
  const btn = set_el('set-se-fetch');
  if (!btn || btn.dataset.wired) return;
  btn.dataset.wired = '1';
  btn.addEventListener('click', async function(){
    const note = set_el('set-build-screens-note');
    btn.disabled = true;
    try {
      let r = await API.post('/api/se/overlays', {});
      if (r && r.error === 'no token stored'){
        const jwt = window.prompt(
          'Paste your StreamElements JWT token.\n\n'
          + 'Account settings on streamelements.com, the Channels section, '
          + '"Show secrets". It is stored in secrets\\ and never in '
          + 'config.yaml.\n\n'
          + 'This token can change your overlays and alerts, not only read '
          + 'them.', '');
        if (!jwt){ btn.disabled = false; return; }
        r = await API.post('/api/se/connect', { jwt: jwt.trim() });
        if (r && r.error){ toast(r.error, 'error'); btn.disabled = false; return; }
        r = await API.post('/api/se/overlays', {});
      }
      if (r && r.error){ toast(r.error, 'error'); btn.disabled = false; return; }

      const picked = (r && r.suggest) || {};
      const map = { starting: 'screens.starting_file',
                    paused:   'screens.paused_file',
                    ending:   'screens.ending_file' };
      let filled = 0;
      Object.keys(map).forEach(function(which){
        if (!picked[which]) return;
        const el = set_el('set-f-' + set_slug(map[which]));
        if (!el) return;
        el.value = picked[which];
        /* Bubbles to the panels listener, which is what marks it dirty --
           setting .value alone leaves Save greyed out. */
        el.dispatchEvent(new Event('input', { bubbles: true }));
        filled++;
      });
      const n = (r.overlays || []).length;
      if (note) note.textContent = n + ' overlays found, ' + filled
        + ' filled in. Check them, then Save.';
      toast(filled ? 'Filled ' + filled + ' screen(s) from StreamElements. '
                     + 'Review and save.'
                   : 'Found ' + n + ' overlays but none named like a start, '
                     + 'be-right-back or ending scene.', filled ? 'ok' : 'warn');
    } catch (e){
      toast('Could not reach StreamElements.', 'error');
    }
    btn.disabled = false;
  });
}

/* Save first, then build: the endpoint reads the saved config, so building
   before saving would create scenes for the paths that were there before. */
function set_wireBuildScreens(){
  const btn = set_el('set-build-screens');
  if (!btn || btn.dataset.wired) return;
  btn.dataset.wired = '1';
  btn.addEventListener('click', async function(){
    const note = set_el('set-build-screens-note');
    btn.disabled = true;
    if (note) note.textContent = 'Saving, then asking OBS...';
    try {
      /* set_save() returns immediately when nothing is dirty. */
      if (typeof set_save === 'function') await set_save();
      const r = await API.post('/api/screens/build', {});
      if (r && r.error){
        if (note) note.textContent = r.error;
        toast(r.error, 'error');
      } else {
        const made = (r && r.scenes) || [];
        if (note) note.textContent = 'Ready in OBS: ' + made.join(', ');
        toast('Built ' + made.length + ' scene' + (made.length === 1 ? '' : 's')
              + ' in OBS.', 'ok');
      }
    } catch (e){
      if (note) note.textContent = 'Could not reach OBS.';
      toast('Could not reach OBS.', 'error');
    }
    btn.disabled = false;
  });
}

/* CONNECTING TWITCH OR KICK. A sign-in, not a setting -- it opens a browser
   and comes back with a token -- so it is a panel at the top of the Stream
   section rather than a field in the list. It also says the two states apart:
   credentials in secrets/ mean the app CAN ask, and a token means the user
   has said yes. One line for both would make "paste the client id" and
   "press Connect" look like the same step. */
function set_connectHtml(){
  var st = set_state.platforms || {};
  var rows = [['twitch', 'Twitch'], ['kick', 'Kick']].map(function(p){
    var k = p[0], label = p[1];
    var s = st[k] || {};
    var where = s.connected ? 'Connected'
              : s.configured ? 'Not connected yet'
              : 'No client id or secret in secrets/' + k + '.json';
    return '<div class="field-inline" style="justify-content:space-between">' +
      '<span><b>' + label + '</b> <span class="muted">' + set_esc(where) + '</span></span>' +
      '<button class="btn btn-sm" type="button" data-act="connect" data-platform="' +
        k + '"' + (s.configured ? '' : ' disabled') + '>' +
        (s.connected ? 'Reconnect' : 'Connect') + '</button></div>';
  }).join('');
  return '<div class="panel">' +
    '<p class="field-label">Sign in to a platform</p>' + rows +
    '<p class="field-help">Twitch goes live on the stream key alone; signing ' +
    'in is what lets AutoStream set the title and category. Kick hands over ' +
    'its stream key through the API, so it needs the sign-in to stream at ' +
    'all.</p></div>';
}

function set_esc(v){
  return String(v == null ? '' : v).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}

/* OPENS A BROWSER AND WAITS. The token lands on this server's own callback,
   not in this tab, so there is nothing to await -- the status is polled until
   it flips, and gives up rather than polling forever if the user closes the
   tab without finishing. */
async function set_connect(name){
  if (!name) return;
  var r;
  try { r = await API.post('/api/platform/connect', {platform: name}); }
  catch (e) { toast('Could not start the sign-in.', 'error'); return; }
  if (!r || r.error || !r.url){ toast((r && r.error) || 'Could not start the sign-in.', 'error'); return; }
  window.open(r.url, '_blank', 'noopener');
  toast('Finish the sign-in in your browser.', 'ok');
  for (var i = 0; i < 60; i++){
    await new Promise(function(ok){ setTimeout(ok, 2000); });
    await set_loadPlatforms();
    var st = (set_state.platforms || {})[name] || {};
    if (st.connected){
      toast(name.charAt(0).toUpperCase() + name.slice(1) + ' is connected.', 'ok');
      set_render();
      return;
    }
  }
}

async function set_loadPlatforms(){
  try {
    var r = await API.get('/api/platform/status');
    if (r && r.platforms) set_state.platforms = r.platforms;
  } catch (e) { /* the panel says "not connected", which is true */ }
}

function set_sectionHtml(sec){
  var plain = [], adv = [];
  (sec.fields || []).forEach(function(f){
    (f.advanced ? adv : plain).push(set_fieldHtml(f, sec.id));
  });
  var body = '';
  if (sec.advanced){
    /* A whole advanced section stays folded until asked for. */
    body = '<details class="panel"><summary>' +
      '<span class="field-label">Show these settings</span>' +
      '</summary><div>' + plain.join('') + adv.join('') + '</div></details>';
  } else {
    body = (sec.id === 'stream' ? set_connectHtml() : '') + plain.join('');
    if ((sec.fields || []).some(function(f){ return f.only_for; })){
      body += '<p class="field-help settings-only-note hide" data-sec="' +
        set_attr(sec.id) + '"></p>';
    }
    if (adv.length){
      body += '<details class="panel"><summary>' +
        '<span class="field-label">Advanced</span>' +
        '</summary><div>' + adv.join('') + '</div></details>';
    }
  }
  /* One section carries an action of its own: the screen savers are not real
     until the scenes exist in OBS, and building them at the moment of going
     live would mean a failure is discovered by the audience. */
  if (sec.id === 'screens'){
    body += '<div class="controls set-sec-acts">' +
      '<button class="btn" type="button" id="set-se-fetch">' +
      'Fetch my StreamElements scenes</button>' +
      '<button class="btn" type="button" id="set-build-screens">' +
      'Create the scenes in OBS</button>' +
      '<span class="muted" id="set-build-screens-note"></span></div>';
  }
  return set_sectionShell(sec, body);
}

/* A section is a heading, one sentence, and its rows -- no plate around it.
   The page is one section at a time, so a card would only be a box around
   everything. */
function set_sectionShell(sec, body){
  var slug = set_slug(sec.id);
  return '<section class="settings-section' + (sec.id === set_state.active ? '' : ' hide') +
    '" id="set-sec-' + slug + '" data-sec="' + set_attr(sec.id) + '"' +
    ' aria-labelledby="set-h-' + slug + '">' +
    '<div class="settings-section-head">' +
      '<h2 class="set-sec-title" id="set-h-' + slug + '">' + esc(sec.label || sec.id) + '</h2>' +
      (sec.blurb ? '<p class="set-sec-blurb">' + esc(sec.blurb) + '</p>' : '') +
    '</div>' +
    '<div class="set-sec-body">' + body + '</div>' +
  '</section>';
}

/* ------------------------------------------------------------- shortcuts

   EVERY KEY THE APP ANSWERS TO, IN ONE PLACE. The two hotkeys live in the
   Safety section beside what they do, and the Studio's keys live in its own
   key sheet behind "?" -- so "what can I press" had no single answer. This is
   that answer, read-only: it lists, it does not rebind. Changing a hotkey is
   still done on its own row, which this links to, because that row is where
   the validation and the warning about clashing with a game already are. */

var set_SHORTCUTS = {id: 'shortcuts', label: 'Shortcuts', group: 'app',
  blurb: 'Every key AutoStream answers to. To change a hotkey, open its setting.'};

/* -> [{label, blurb, rows: [{label, keys, path?}]}]. The two system-wide
   hotkeys first, then each Studio scope in its own precedence order, keeping
   only the commands that have a key. */
function set_shortcutRows(values, cmds, scopes){
  var v = values || {};
  var hot = function(path, label){
    var k = String(v[path] == null ? '' : v[path]).trim();
    return {label: label, keys: k ? [k] : [], path: path};
  };
  var out = [{label: 'Anywhere, even in a game', blurb: 'Pressed while AutoStream is running in the background.',
    rows: [hot('rules.replay_hotkey', 'Save an instant replay'),
           hot('rules.kill_switch_hotkey', 'Stop the stream now')]},
    {label: 'Anywhere in this window', blurb: 'The page size is also on screen, top right.',
     rows: [{label: 'Make the page bigger', keys: ['Ctrl+Scroll up', 'Ctrl++']},
            {label: 'Make the page smaller', keys: ['Ctrl+Scroll down', 'Ctrl+-']},
            {label: 'Page at actual size', keys: ['Ctrl+0']},
            {label: 'Search and run anything', keys: ['Ctrl+K']}]}];
  (scopes || []).forEach(function(s){
    var rows = (cmds || []).filter(function(c){
      return c.scope === s.id && c.keys && c.keys.length;
    }).map(function(c){ return {label: c.label, keys: c.keys.slice()}; });
    if (rows.length) out.push({label: s.label, blurb: s.blurb || '', rows: rows});
  });
  return out;
}

/* "ArrowRight" is a word for a programmer; the key cap says an arrow. A
   hotkey is stored the way the keyboard library wants it, "ctrl+alt+r", and
   is shown the way the keys are printed, "Ctrl+Alt+R". */
function set_keyCap(k){
  var names = {ArrowRight: 'Right arrow', ArrowLeft: 'Left arrow', ArrowUp: 'Up arrow',
               ArrowDown: 'Down arrow', Escape: 'Esc', Backspace: 'Backspace', ' ': 'Space'};
  if (names[k]) return names[k];
  var s = String(k);
  if (s.length > 1 && s.indexOf('+') > 0){
    return s.split('+').map(function(p){
      return p ? p.charAt(0).toUpperCase() + p.slice(1) : '+';
    }).join('+');
  }
  return s;
}

function set_shortcutsHtml(){
  var cmds = (typeof STUDIO_CMDS !== 'undefined') ? STUDIO_CMDS : [];
  var scopes = (typeof STUDIO_SCOPES !== 'undefined') ? STUDIO_SCOPES : [];
  var groups = set_shortcutRows(set_state.values, cmds, scopes);
  var body = groups.map(function(g){
    return '<div class="set-keys">' +
      '<h3 class="set-keys-title">' + esc(g.label) + '</h3>' +
      (g.blurb ? '<p class="field-help">' + esc(g.blurb) + '</p>' : '') +
      '<ul class="set-keys-list">' + g.rows.map(function(r){
        var caps = r.keys.length
          ? r.keys.map(function(k){ return '<kbd class="kbd">' + esc(set_keyCap(k)) + '</kbd>'; })
              .join('<span class="set-keys-or">or</span>')
          : '<span class="muted">Not set</span>';
        var change = r.path
          ? '<button class="btn btn-ghost btn-sm" type="button" data-act="set-goto"' +
            ' data-path="' + set_attr(r.path) + '" aria-label="Change: ' + set_attr(r.label) + '">' +
            'Change</button>'
          : '';
        return '<li class="set-keys-row"><span class="set-keys-what">' + esc(r.label) + '</span>' +
          '<span class="set-keys-caps">' + caps + change + '</span></li>';
      }).join('') + '</ul></div>';
  }).join('');
  return set_sectionShell(set_SHORTCUTS, body);
}

/* ------------------------------------------------------------- the groups */

/* Sections under the four headings, in the headings' order. A group left
   empty -- the Mac build has no streaming sections -- is dropped rather than
   drawn as a heading over nothing, and a section naming a group this page
   has never heard of lands under the last one rather than vanishing. */
function set_grouped(sections, groups){
  var out = (groups || []).map(function(g){ return {id: g.id, label: g.label, sections: []}; });
  var by = {};
  out.forEach(function(g){ by[g.id] = g; });
  (sections || []).forEach(function(s){
    var g = by[s.group] || out[out.length - 1];
    if (g) g.sections.push(s);
  });
  return out.filter(function(g){ return g.sections.length; });
}

/* What the nav and the panels are drawn from: the schema's sections, plus
   Shortcuts, which is the page's own. */
function set_navGroups(){
  return set_grouped(set_state.sections.concat([set_SHORTCUTS]), set_GROUPS);
}

/* ---------------------------------------------- settings that are not yours

   Most of the `youtube.*` block belongs to YouTube alone. Twitch has no
   privacy setting, no latency choice, no "made for kids" flag and no
   broadcast object to start a second of; Kick has none of them either. A page
   that offers those controls while Twitch is selected is describing something
   it will not do, and the first time that matters is when somebody sets a
   stream to Unlisted, goes live on Twitch, and finds it public.

   Hidden rather than disabled. A greyed-out row still has to be read before
   it can be dismissed, and there are five of them. What is left in its place
   is one line saying which platform is selected and that the rest did not
   apply -- so the gap is explained where the gap is.

   NOTHING IS WRITTEN. The values stay exactly as they were, and switching
   back to YouTube brings the same settings back untouched. Hiding a control
   is not the same as changing it. */

function set_platformNow(){
  var f = set_state.fields['youtube.platform'];
  /* Read the control, not the saved value: the rows have to follow the
     dropdown while the change is still unsaved. */
  return (f ? String(set_read(f) || '') : '') || 'youtube';
}

/* ONE PASS, TWO REASONS. A row can be hidden because the platform does not
   have that setting, or because it does not match what is being searched
   for. Two functions each toggling `hide` would undo one another depending
   on which ran last, which is a bug that only shows up when a user searches
   with Twitch selected -- so both reasons are decided here, together. */
function set_applyFilters(){
  var panels = set_el('set-panels');
  if (!panels) return;

  var now = set_platformNow();
  var terms = set_query.toLowerCase().split(/\s+/).filter(Boolean);
  var searching = terms.length > 0;

  var rows = panels.querySelectorAll('.field[data-path]');
  var dropped = {};         /* sections with a row the platform does not have */
  var hits = {};            /* sections with a row matching the search */
  var found = 0;

  for (var i = 0; i < rows.length; i++){
    var row = rows[i];
    var sec = row.closest ? row.closest('.settings-section') : null;
    var id = sec ? sec.getAttribute('data-sec') : '';

    var only = row.getAttribute('data-only');
    var mine = !only || only.split(' ').indexOf(now) >= 0;
    if (!mine && id) dropped[id] = true;

    var hay = row.getAttribute('data-find') || '';
    var matched = true;
    for (var t = 0; t < terms.length; t++){
      if (hay.indexOf(terms[t]) < 0) { matched = false; break; }
    }

    var show = mine && (!searching || matched);
    row.classList.toggle('hide', !show);
    if (show && searching){ found++; if (id) hits[id] = true; }
  }

  /* The note explaining the platform gap is about the whole section, so it
     has no place in a result list that is showing three rows out of forty. */
  var label = set_platformLabel(now);
  var notes = panels.querySelectorAll('.settings-only-note');
  for (var j = 0; j < notes.length; j++){
    var nid = notes[j].getAttribute('data-sec');
    notes[j].classList.toggle('hide', searching || !dropped[nid]);
    notes[j].textContent = 'Some settings are hidden because they are ' +
      'YouTube’s own and ' + label + ' has no equivalent. They are not ' +
      'changed, and come back if you switch to YouTube.';
  }

  set_applySections(searching, hits, found);
}

/* Which sections are on screen: one at a time normally, every section with a
   hit while searching. */
function set_applySections(searching, hits, found){
  var panels = set_el('set-panels');
  var secs = panels.querySelectorAll('.settings-section');
  for (var i = 0; i < secs.length; i++){
    var sec = secs[i];
    var id = sec.getAttribute('data-sec');
    sec.classList.toggle('is-hit', !!(searching && hits[id]));
    sec.classList.toggle('hide',
      searching ? !hits[id] : id !== set_state.active);
    /* A match folded inside Advanced is a match nobody can see, so a search
       opens the folds -- and puts them back exactly as it found them when it
       clears. Without the remembering, searching once left every Advanced
       section on the page hanging open, which is a different page from the
       one the user had. */
    var folds = sec.querySelectorAll('details.panel');
    for (var d = 0; d < folds.length; d++){
      var fold = folds[d];
      if (searching){
        if (fold.getAttribute('data-washut') === null){
          fold.setAttribute('data-washut', fold.hasAttribute('open') ? '0' : '1');
        }
        if (hits[id]) fold.setAttribute('open', 'open');
      } else if (fold.getAttribute('data-washut') !== null){
        if (fold.getAttribute('data-washut') === '1') fold.removeAttribute('open');
        else fold.setAttribute('open', 'open');
        fold.removeAttribute('data-washut');
      }
    }
  }

  /* Everything that is not a settings section belongs to the page rather
     than to a search: the version card, the diagnostics card. */
  ['set-about', 'set-trouble'].forEach(function(id){
    var el = set_el(id);
    if (el) el.classList.toggle('hide', !!searching);
  });

  /* THE NAV STAYS. Hiding it during a search took away the way out of one:
     the only remaining exit was clearing the box, and a page that removes
     its own navigation when you type in it reads as having gone somewhere
     else. Pressing a section clears the search and goes there. */

  var count = set_el('set-search-count');
  if (count){
    count.textContent = !searching ? ''
      : (found === 1 ? '1 setting' : found + ' settings');
  }

  var none = set_el('set-noresult');
  if (none) none.classList.toggle('hide', !(searching && found === 0));
  set_growVisible();
}

/* Kept as the name the rest of the page calls after a platform change. */
function set_applyPlatform(){ set_applyFilters(); }

/* OPEN ONE SETTING: its section, scrolled to it, focus on its control. What
   every "fix it" button means -- the Dashboard's checklist, the Logs, Ctrl K.
   They used to search Settings for a word instead, and on a first visit the
   search ran before the page had loaded anything, so 'Turn recording on'
   landed on Appearance. Asked before the load, it waits for it. */
function set_open(path){
  if (typeof go === 'function' && shell_page !== 'settings') go('settings');
  set_search('');
  if (!set_state.loaded){ set_state.openAfterLoad = path; return; }
  set_state.openAfterLoad = '';
  set_reveal(path);
}

/* What Ctrl K finds in Settings: a setting by its name, its help text or its
   key. Opening one opens that setting (set_open). */
pal_source('Settings', function (q) {
  if (!String(q || '').trim()) return [];
  var out = [];
  Object.keys(set_state.fields || {}).forEach(function (k) {
    var f = set_state.fields[k];
    if (out.length < 6 && f && f.label && pal_match(q, f.label + ' ' + (f.help || '') + ' ' + f.path))
      out.push({label: f.label, hint: f.section_label || '',
                run: function () { set_open(f.path); }});
  });
  return out;
});

function set_search(value){
  set_query = String(value == null ? '' : value).trim();
  /* The box follows the query, not only the other way round: the Dashboard,
     the Logs fix buttons and Ctrl K all open this page searched, and a filter
     with an empty box above it is a page that looks broken. */
  var box = set_el('set-search');
  if (box && box.value.trim() !== set_query) box.value = set_query;
  var q = set_el('set-noresult-q');
  if (q) q.textContent = set_query;
  set_applyFilters();
}

/* THE SEARCH LIVES IN THE TOP BAR, which the shell empties on every page
   change -- so it is put back, and wired again, each time this page shows.
   The query itself is held in set_query, so it survives the box being
   rebuilt. */
function set_searchBox(){
  if (typeof shell_setActions !== 'function') return;
  shell_setActions(set_SEARCH_BOX);
  var search = set_el('set-search');
  if (!search || search.dataset.wired) return;
  search.dataset.wired = '1';
  search.value = set_query;
  search.addEventListener('input', function(){ set_search(search.value); });
  search.addEventListener('keydown', function(ev){
    /* Escape clears rather than closing anything, because there is nothing
       open -- and a search box that swallows Escape with no effect is the
       reason people reach for the mouse. */
    if (ev.key === 'Escape' && search.value){
      search.value = '';
      set_search('');
      ev.stopPropagation();
    }
  });
}

function set_platformLabel(id){
  var f = set_state.fields['youtube.platform'];
  var opts = (f && f.options) || [];
  for (var i = 0; i < opts.length; i++){
    if (opts[i].value === id) return opts[i].label;
  }
  return id;
}

/* Group headings are words above the items, not buttons: there is nothing to
   open, and a heading that took focus would be one more stop for every Tab. */
function set_navHtml(){
  return set_navGroups().map(function(g){
    return '<div class="set-nav-group" role="group" aria-labelledby="set-g-' + set_attr(g.id) + '">' +
      '<div class="set-nav-head" id="set-g-' + set_attr(g.id) + '">' + esc(g.label) + '</div>' +
      g.sections.map(function(sec){
        var on = sec.id === set_state.active;
        return '<button class="settings-nav-item' + (on ? ' is-active' : '') +
          '" type="button" data-sec="' + set_attr(sec.id) + '"' +
          (on ? ' aria-current="true"' : '') + '>' +
          '<span>' + esc(sec.label || sec.id) + '</span></button>';
      }).join('') + '</div>';
  }).join('');
}

function set_render(){
  set_el('set-nav').innerHTML = set_navHtml();
  /* Drawn in the nav's order, so a search's results read top to bottom in
     the same order as the list beside them. */
  set_el('set-panels').innerHTML = set_navGroups().map(function(g){
    return g.sections.map(function(sec){
      return sec.id === 'shortcuts' ? set_shortcutsHtml() : set_sectionHtml(sec);
    }).join('');
  }).join('');
  set_wireBuildScreens();
  set_wireStreamElements();
  set_applyFilters();
  set_navEdges();
  set_growVisible();
  set_updateActions();
}

/* A textarea in a hidden section measures zero, so auto-grow is re-run every
   time a section is revealed rather than once at render. */
function set_growVisible(){
  var boxes = set_el('set-panels').querySelectorAll('.settings-section:not(.hide) textarea');
  for (var i = 0; i < boxes.length; i++) set_grow(boxes[i]);
}

function set_navMark(id){
  var nav = set_el('set-nav');
  if (!nav) return;
  var items = nav.querySelectorAll('.settings-nav-item');
  var here = null;
  for (var i = 0; i < items.length; i++){
    var mine = items[i].getAttribute('data-sec') === id;
    items[i].classList.toggle('is-active', mine);
    if (mine) { here = items[i]; items[i].setAttribute('aria-current', 'true'); }
    else items[i].removeAttribute('aria-current');
  }
  /* THE STRIP SCROLLS, so the section you just chose can be off the end of
     it -- which is how a nav item reads as not having been pressed. */
  if (here && here.scrollIntoView && nav.scrollWidth > nav.clientWidth){
    here.scrollIntoView({block: 'nearest', inline: 'nearest'});
  }
  set_navEdges();
}

/* Which edges still have sections past them. CSS cannot ask this, so the
   fade that says "there is more" is driven from here -- on render, on
   scroll, and on resize, because a window drag changes the answer. */
function set_navEdges(){
  var nav = set_el('set-nav');
  if (!nav) return;
  var over = nav.scrollWidth - nav.clientWidth;
  /* A couple of pixels of rounding is not more content. */
  var room = over > 2;
  nav.classList.toggle('set-more-start', room && nav.scrollLeft > 2);
  nav.classList.toggle('set-more-end', room && nav.scrollLeft < over - 2);
}

function set_showSection(id){
  set_state.active = id;
  /* A search is showing every section that matched; moving one of them in
     front of the others would be meaningless, and hiding the rest would
     throw away the results. */
  if (set_query){ set_navMark(id); return; }
  set_navMark(id);
  var secs = set_el('set-panels').querySelectorAll('.settings-section');
  for (var j = 0; j < secs.length; j++){
    secs[j].classList.toggle('hide', secs[j].getAttribute('data-sec') !== id);
  }
  set_growVisible();
}

/* -------------------------------------------------------- reading controls */

function set_read(f){
  var slug = set_slug(f.path);
  var c = f.control;
  if (f.path === 'ui.theme') return set_state.theme;
  if (c === 'taglist') return (set_state.tags[f.path] || []).slice();

  if (c === 'time_range'){
    var a = set_el('set-f-' + slug + '-a'), b = set_el('set-f-' + slug + '-b');
    var av = a ? a.value.trim() : '', bv = b ? b.value.trim() : '';
    return (av === '' && bv === '') ? [] : [av, bv];
  }

  var el = set_el('set-f-' + slug);
  if (!el) return set_state.values[f.path];
  if (c === 'toggle') return el.getAttribute('aria-checked') === 'true';
  if (c === 'number') { var t = el.value.trim(); return t === '' ? '' : Number(t); }
  if (c === 'textarea') return el.value.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  if (c === 'readonly') return set_state.values[f.path];
  return el.value.trim();
}

function set_isDirty(f){
  if (f.control === 'readonly' || f.path === 'ui.theme') return false;
  return !set_same(set_read(f), set_state.values[f.path]);
}

function set_dirtyPaths(){
  var out = [];
  for (var p in set_state.fields){
    if (Object.prototype.hasOwnProperty.call(set_state.fields, p) &&
        set_isDirty(set_state.fields[p])) out.push(p);
  }
  return out;
}

/* ------------------------------------------------------------ dirty & errors */

function set_updateActions(){
  var n = set_dirtyPaths().length;
  var bar = set_el('set-actions');
  if (!bar) return;
  bar.classList.toggle('hide', n === 0);
  set_el('set-count').textContent =
    n === 1 ? '1 unsaved change' : n + ' unsaved changes';
}

function set_error(path, msg){
  var e = set_el('set-e-' + set_slug(path));
  if (!e) return;
  if (msg){ e.textContent = msg; e.classList.remove('hide'); }
  else { e.textContent = ''; e.classList.add('hide'); }
}

function set_clearErrors(){
  for (var p in set_state.fields){
    if (Object.prototype.hasOwnProperty.call(set_state.fields, p)) set_error(p, '');
  }
}

/* Validate a single field live, so a bad number is flagged as it is typed. */
function set_touch(path){
  var f = set_state.fields[path];
  if (!f) return;
  if (set_isDirty(f)) set_error(path, set_validate(f, set_read(f)));
  else set_error(path, '');
  if (path === 'youtube.platform') set_applyFilters();
  set_updateActions();
}

function set_grow(el){
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = (el.scrollHeight + 2) + 'px';
}

/* ------------------------------------------------------------------ wiring */

function set_wire(){
  if (set_state.wired) return;
  set_state.wired = true;
  var panels = set_el('set-panels');

  var nav = set_el('set-nav');
  nav.addEventListener('click', function(ev){
    var b = ev.target.closest ? ev.target.closest('.settings-nav-item') : null;
    if (!b) return;
    /* Pressing a section while a search is open means "show me that
       section", which it cannot do while the results are on screen. */
    if (set_query){
      var box = set_el('set-search');
      if (box) box.value = '';
      set_search('');
    }
    set_showSection(b.getAttribute('data-sec'));
  });
  nav.addEventListener('scroll', set_navEdges, {passive: true});
  /* A horizontal strip and a wheel that only scrolls vertically: on a laptop
     with no trackpad gesture there is otherwise no way to reach the last
     sections except by dragging a scrollbar that is deliberately hidden. */
  nav.addEventListener('wheel', function(ev){
    if (nav.scrollWidth <= nav.clientWidth) return;
    if (Math.abs(ev.deltaY) <= Math.abs(ev.deltaX)) return;
    nav.scrollLeft += ev.deltaY;
    ev.preventDefault();
  }, {passive: false});

  window.addEventListener('resize', set_navEdges);

  panels.addEventListener('input', function(ev){
    var wrap = ev.target.closest ? ev.target.closest('.field') : null;
    if (!wrap) return;
    if (ev.target.tagName === 'TEXTAREA') set_grow(ev.target);
    if (ev.target.classList.contains('tag-add')) return;
    set_touch(wrap.getAttribute('data-path'));
  });

  panels.addEventListener('change', function(ev){
    var wrap = ev.target.closest ? ev.target.closest('.field') : null;
    if (wrap && !ev.target.classList.contains('tag-add')) {
      set_touch(wrap.getAttribute('data-path'));
    }
  });

  panels.addEventListener('keydown', function(ev){
    if (!ev.target.classList || !ev.target.classList.contains('tag-add')) return;
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    var wrap = ev.target.closest('.field');
    if (wrap) set_tagCommit(wrap.getAttribute('data-path'));
  });

  panels.addEventListener('focusout', function(ev){
    if (!ev.target.classList || !ev.target.classList.contains('tag-add')) return;
    if (!ev.target.value.trim()) return;
    /* Committing here would re-render the chips and destroy the button that is
       mid-click, so leaving towards a remove button is left to that click. */
    var to = ev.relatedTarget;
    if (to && to.closest && to.closest('[data-act="tag-x"]')) return;
    var wrap = ev.target.closest('.field');
    if (wrap) set_tagCommit(wrap.getAttribute('data-path'));
  });

  panels.addEventListener('click', function(ev){
    var btn = ev.target.closest ? ev.target.closest('[data-act]') : null;
    if (!btn) return;
    var act = btn.getAttribute('data-act');
    var wrap = btn.closest('.field');
    var path = wrap ? wrap.getAttribute('data-path') : '';

    if (act === 'toggle'){
      var on = btn.getAttribute('aria-checked') === 'true';
      btn.setAttribute('aria-checked', on ? 'false' : 'true');
      set_touch(path);
    } else if (act === 'reveal'){
      var inp = wrap.querySelector('input.input');
      var hidden = inp.type === 'password';
      inp.type = hidden ? 'text' : 'password';
      btn.innerHTML = icon(hidden ? 'eye-off' : 'eye');
      btn.setAttribute('aria-label', hidden ? 'Hide value' : 'Show value');
    } else if (act === 'copy'){
      set_copy(wrap.querySelector('input.input'));
    } else if (act === 'clear-time'){
      var slug = set_slug(path);
      var a = set_el('set-f-' + slug + '-a'), b = set_el('set-f-' + slug + '-b');
      if (a) a.value = ''; if (b) b.value = '';
      set_touch(path);
    } else if (act === 'tag-x'){
      var list = set_state.tags[path] || [];
      list.splice(parseInt(btn.getAttribute('data-i'), 10), 1);
      set_tagRender(path);
      set_touch(path);
    } else if (act === 'connect'){
      /* `btn`, which is what this handler resolved. `t` is not in scope here
         and threw on every press -- the button did nothing at all. */
      set_connect(btn.getAttribute('data-platform'));
    } else if (act === 'theme'){
      set_theme(btn.getAttribute('data-theme'));
    } else if (act === 'set-goto'){
      set_reveal(btn.getAttribute('data-path'));
    }
  });

  /* `toggle` does not bubble, so the disclosure listener runs in capture. */
  panels.addEventListener('toggle', function(){ set_growVisible(); }, true);

  set_el('set-save').addEventListener('click', set_save);
  set_el('set-discard').addEventListener('click', set_discard);
}

function set_tagCommit(path){
  var f = set_state.fields[path];
  if (!f) return;
  var box = set_el('set-f-' + set_slug(path));
  var inp = box ? box.querySelector('.tag-add') : null;
  if (!inp) return;
  var text = inp.value.trim();
  inp.value = '';
  if (!text) return;
  var list = set_state.tags[path] || (set_state.tags[path] = []);
  var per = f.item_max_chars || 120;
  if (text.length > per){
    set_error(path, 'Each entry must be under ' + per + ' characters.');
    return;
  }
  if (f.max_items && list.length >= f.max_items){
    set_error(path, 'At most ' + f.max_items + ' entries.');
    return;
  }
  if (list.indexOf(text) < 0) list.push(text);
  set_tagRender(path);
  set_touch(path);
  var again = set_el('set-f-' + set_slug(path)).querySelector('.tag-add');
  if (again && !again.disabled) again.focus();
}

function set_tagRender(path){
  var f = set_state.fields[path];
  var box = set_el('set-f-' + set_slug(path));
  if (f && box) box.innerHTML = set_tagsHtml(f);
}

function set_copy(inp){
  if (!inp) return;
  var text = inp.value || '';
  var done = function(){ toast('Copied.', 'ok'); };
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(done, function(){ set_copyFallback(inp); });
  } else {
    set_copyFallback(inp);
  }
}

function set_copyFallback(inp){
  try {
    inp.removeAttribute('readonly');
    inp.select();
    document.execCommand('copy');
    inp.setAttribute('readonly', 'readonly');
    toast('Copied.', 'ok');
  } catch (e){
    toast('Could not copy - select the text instead.', 'warn');
  }
}

/* -------------------------------------------------------------- the theme */

/* The palette lives in its own <style id="theme-vars"> that the server
   renders, so after the theme is saved we fetch the page again and swap that
   element's text. Swapping the whole block (rather than copying values onto
   the root as inline properties, as this used to) is what lets System work:
   its light half sits inside a prefers-color-scheme block, and an inline
   property would override it. */
async function set_repaint(){
  var r = await fetch('/' + (location.search || ''), { cache: 'no-store' });
  var html = await r.text();
  var m = html.match(/<style id="theme-vars">([\s\S]*?)<\/style>/);
  var host = document.getElementById('theme-vars');
  if (!m || !host || m[1].indexOf('--') < 0) throw new Error('no palette');
  host.textContent = m[1];
}

async function set_theme(id){
  if (!id || id === set_state.theme) return;
  var previous = set_state.theme;
  set_state.theme = id;
  set_state.values['ui.theme'] = id;
  var host = set_el('set-themes');
  if (host && host.parentNode) host.outerHTML = set_themesHtml();
  try {
    await API.post('/api/theme', { theme: id });
  } catch (e){
    set_state.theme = previous;
    set_state.values['ui.theme'] = previous;
    var again = set_el('set-themes');
    if (again && again.parentNode) again.outerHTML = set_themesHtml();
    toast('Could not change the theme.', 'error');
    return;
  }
  try {
    await set_repaint();
    shell_themeChanged();
  } catch (e){
    /* Last resort: reload. The shell restores the page from the hash. */
    try { location.hash = '#settings'; } catch (e2){}
    location.reload();
  }
}

/* -------------------------------------------------------------- load, save */

function set_ingest(sections, values, boot){
  set_state.sections = sections;
  set_state.fields = {};
  set_state.tags = {};
  set_state.values = {};
  sections.forEach(function(sec){
    (sec.fields || []).forEach(function(f){
      set_state.fields[f.path] = f;
      set_state.values[f.path] = set_norm(f, values[f.path]);
      if (f.control === 'taglist') set_state.tags[f.path] = set_state.values[f.path].slice();
    });
  });
  set_state.themes = (boot && boot.themes) || [];
  set_state.theme = (boot && boot.theme) || set_state.values['ui.theme'] || '';
  if (set_state.active !== 'shortcuts' &&
      !sections.some(function(s){ return s.id === set_state.active; })){
    var first = sections.filter(function(s){ return !s.advanced; })[0] || sections[0];
    set_state.active = first ? first.id : '';
  }
}

async function set_load(){
  if (set_state.loading) return;
  set_state.loading = true;
  try {
    var results = await Promise.all([
      API.get('/api/settings/schema'),
      API.get('/api/settings/values'),
      API.get('/api/bootstrap').catch(function(){ return {}; })
    ]);
    var raw = results[0];
    var sections = Array.isArray(raw) ? raw
      : (raw && (raw.sections || raw.schema || raw.groups)) || [];
    var vraw = results[1];
    var values = (vraw && typeof vraw === 'object' && vraw.values &&
                  typeof vraw.values === 'object') ? vraw.values : (vraw || {});
    set_ingest(sections, values, results[2]);
    set_render();
    set_wire();
    set_state.loaded = true;
    /* A fix button asked for one setting before the page could show it. */
    if (set_state.openAfterLoad){
      var want = set_state.openAfterLoad;
      set_state.openAfterLoad = '';
      set_reveal(want);
    }
  } catch (e){
    set_el('set-panels').innerHTML = '<div class="empty">Could not load settings. ' +
      esc(String((e && e.message) || e)) + '</div>';
  } finally {
    set_state.loading = false;
  }
}

/* Re-read values when the page is reopened clean, so a change made by setup or
   by hand shows up. Never while dirty: that would eat the user's typing. */
async function set_refresh(){
  var vraw = await API.get('/api/settings/values');
  var values = (vraw && vraw.values && typeof vraw.values === 'object') ? vraw.values : (vraw || {});
  var changed = false;
  for (var p in set_state.fields){
    if (!Object.prototype.hasOwnProperty.call(set_state.fields, p)) continue;
    var next = set_norm(set_state.fields[p], values[p]);
    if (!set_same(next, set_state.values[p])){ set_state.values[p] = next; changed = true; }
    if (set_state.fields[p].control === 'taglist') set_state.tags[p] = set_state.values[p].slice();
  }
  if (changed) set_render();
}

async function set_save(){
  if (set_state.saving) return;
  var paths = set_dirtyPaths();
  if (!paths.length) return;

  var payload = {}, bad = 0, firstBad = '', dangerous = [];
  paths.forEach(function(p){
    var f = set_state.fields[p];
    var v = set_read(f);
    var err = set_validate(f, v);
    if (err){ set_error(p, err); bad++; if (!firstBad) firstBad = p; return; }
    set_error(p, '');
    payload[p] = v;
    if (f.danger) dangerous.push(f.label || p);
  });

  if (bad){
    set_reveal(firstBad);
    toast(bad === 1 ? 'One setting needs fixing.' : bad + ' settings need fixing.', 'warn');
    return;
  }

  if (dangerous.length){
    var msg = 'These are written by setup and pair with state held in OBS and ' +
      'YouTube:\n\n  ' + dangerous.join('\n  ') +
      '\n\nChanging them can stop the next session reaching YouTube. Save anyway?';
    if (!window.confirm(msg)) return;
  }

  set_state.saving = true;
  var btn = set_el('set-save');
  btn.disabled = true;
  try {
    var r = await API.post('/api/settings/save', { values: payload });
    var saved = (r && r.saved) || [];
    var errors = (r && r.errors) || {};

    saved.forEach(function(p){
      if (Object.prototype.hasOwnProperty.call(payload, p)){
        set_state.values[p] = set_norm(set_state.fields[p] || { control: 'text' }, payload[p]);
        set_error(p, '');
      }
    });

    var badPaths = Object.keys(errors);
    badPaths.forEach(function(p){ set_error(p, errors[p]); });
    set_updateActions();

    if (badPaths.length){
      set_reveal(badPaths[0]);
      toast(saved.length
        ? saved.length + ' saved, ' + badPaths.length + ' rejected.'
        : 'Nothing was saved.', 'error');
    } else if (!r || r.ok !== true){
      /* A 500 returns {error:...} with no ok/saved/errors. Testing for
         ok===false would let that fall through to the success branch and
         report a lost edit as saved, so require an explicit ok:true. */
      toast((r && r.error) || 'Settings could not be saved.', 'error');
    } else {
      toast(saved.length === 1 ? '1 setting saved.' : saved.length + ' settings saved.', 'ok');
    }

    if (r && r.restart_required){
      toast('Restart AutoStream for those to take effect.', 'warn');
    }
    /* Developer mode decides whether rows show their keys, so saving it
       redraws the page -- but only once nothing is left unsaved, because a
       redraw puts every control back to its saved value. */
    if (saved.indexOf('ui.developer_mode') >= 0 && !set_dirtyPaths().length) set_render();
  } catch (e){
    toast('Could not save: ' + String((e && e.message) || e), 'error');
  } finally {
    set_state.saving = false;
    btn.disabled = false;
  }
}

function set_reveal(path){
  var f = set_state.fields[path];
  if (!f) return;
  var owner = set_state.sections.filter(function(s){
    return (s.fields || []).some(function(x){ return x.path === path; });
  })[0];
  if (owner && owner.id !== set_state.active) set_showSection(owner.id);
  var wrap = set_el('set-w-' + set_slug(path));
  if (!wrap) return;
  var det = wrap.closest ? wrap.closest('details') : null;
  if (det) det.open = true;
  if (wrap.scrollIntoView) wrap.scrollIntoView({ block: 'center' });
  var el = set_el('set-f-' + set_slug(path));
  if (el && el.focus) el.focus();
}

function set_discard(){
  var n = set_dirtyPaths().length;
  if (!n) return;
  if (!window.confirm('Discard ' + (n === 1 ? 'this change' : 'these ' + n + ' changes') + '?')) return;
  set_clearErrors();
  set_state.sections.forEach(function(sec){
    (sec.fields || []).forEach(function(f){
      if (f.control === 'taglist') set_state.tags[f.path] = set_state.values[f.path].slice();
    });
  });
  set_render();
}

/* Leaving the page silently would throw the edits away, and the rail is one
   click from here, so wrap the shell's router once. */
function set_onSettings(){
  var view = document.getElementById('view-settings');
  return !!(view && view.classList.contains('is-active'));
}

function set_guardNav(){
  if (set_state.guarded) return;
  try {
    if (typeof go !== 'function') return;
    var original = go;
    go = function(page){
      if (page !== 'settings' && set_state.loaded && set_onSettings()){
        var n = set_dirtyPaths().length;
        if (n && !window.confirm('You have ' +
              (n === 1 ? '1 unsaved change' : n + ' unsaved changes') +
              ' in Settings. Leave without saving?')) return;
      }
      return original.apply(null, arguments);
    };
    set_state.guarded = true;
  } catch (e){
    /* Shell froze the binding; the sticky bar is then the only warning. */
  }
}

function set_wireUpdates(){
  if (set_update.wired) return;
  set_update.wired = true;
  var check = set_el('set-ver-check');
  if (check) check.addEventListener('click', set_verCheck);
  var get = set_el('set-ver-get');
  if (get) get.addEventListener('click', set_verGet);
  var diag = set_el('set-diag-get');
  if (diag) diag.addEventListener('click', set_diagGet);
  var copy = set_el('set-diag-copy');
  if (copy) copy.addEventListener('click', set_diagCopy);
  var open = set_el('set-ver-open');
  /* A Mac swaps the app itself rather than opening an installer. */
  if (open && SHELL_BOOT.platform === 'macos') open.querySelector('span').textContent = 'Install and restart';
  if (open) open.addEventListener('click', async function(){
    open.disabled = true;
    try {
      var r = await API.post('/api/update/install', {});
      if (r && r.error){ set_verSay(r.error, 'warn'); open.disabled = false; }
      else set_verSay('Installing. AutoStream will close and reopen.');
    } catch (e){
      /* The app quits as part of this, so a dropped request is the expected
         shape of success rather than a failure. */
      set_verSay('Installing. AutoStream will close and reopen.');
    }
  });
  /* The version is known without asking anybody. */
  var sub = set_el('set-ver-sub');
  /* SHELL_BOOT is a `let`, so it is a global binding but never a property of
     window: `window.SHELL_BOOT` was always undefined, and this never ran. */
  if (sub && typeof SHELL_BOOT !== 'undefined' && SHELL_BOOT && SHELL_BOOT.version){
    sub.textContent = 'AutoStream ' + SHELL_BOOT.version;
  }
}

window.PAGE_SETTINGS = {
  onShow: function(){
    set_guardNav();
    set_wireUpdates();
    set_searchBox();
    // Asked every time the page opens: a connect finishes in another tab, so
    // the only way this one learns about it is by looking again.
    set_loadPlatforms().then(function(){
      if (set_state.loaded) set_render();
    });
    if (!set_state.loaded){ set_load(); return; }
    if (!set_dirtyPaths().length) set_refresh().catch(function(){});
  },
  onTick: function(status){
    set_verProgress(status && status.update);
  }
};

/* ------------------------------------------------------------ updates

   Checking is a button rather than something that happens on every start:
   GitHub allows 60 unauthenticated requests an hour, and an app that spends
   them silently is an app that stops being able to check when asked. The
   answer is cached server-side for the same reason.

   Downloading stops at a verified file on disk. Replacing a running program
   is the installer's job, and there is one -- so what a person gets is a
   button that opens it, not a surprise restart. */

var set_update = {latest: null, path: ''};

function set_verSay(text, kind) {
  var el = set_el('set-ver-msg');
  if (el) el.textContent = text || '';
  set_show('set-ver-body', !!text || !!set_update.path);
  if (el) el.classList.toggle('is-warn', kind === 'warn');
}

/* A version that is NEWER than the newest release is a build from source, not
   an error -- and it is the one case where "no update" is genuinely puzzling
   rather than reassuring, so it says so in as many words. */
function set_verAhead(r) {
  return !!(r && r.latest && r.current &&
            set_verNum(r.current) > set_verNum(r.latest));
}

/* A newer release that has nothing attached to it -- a tag published without
   its build. There is still nothing to download, but "up to date" beside a
   higher version number is a lie, and reads as a broken updater. */
function set_verStuck(r) {
  return !!(r && r.newer && !r.available);
}

/* "1.10.0" -> 1001000. Not a string compare: "1.9.1" sorts above "1.10.0"
   that way, which is exactly backwards. */
function set_verNum(text) {
  var p = String(text || '').match(/\d+/g) || ['0'];
  return (Number(p[0]) || 0) * 1e6 + (Number(p[1]) || 0) * 1e3 +
         (Number(p[2]) || 0);
}

function set_verRender(r) {
  var sub = set_el('set-ver-sub');
  var ahead = set_verAhead(r);
  var stuck = set_verStuck(r);
  if (sub) {
    sub.textContent = 'AutoStream ' + (r.current || '?') +
      (r.available ? '  -  ' + r.latest + ' is available'
                   : (r.latest ? (ahead ? '  -  newer than the latest release'
                                        : (stuck ? '  -  ' + r.latest
                                                   + ' has no download yet'
                                                 : '  -  up to date')) : ''));
  }
  set_show('set-ver-get', !!r.available);
  var notes = set_el('set-ver-notes');
  if (notes && r.notes) notes.textContent = r.notes;
  set_show('set-ver-noteswrap', !!(r.available && r.notes));
  if (r.why) {
    set_verSay(r.why, 'warn');
  } else if (r.available) {
    var mb = r.bytes ? ' (' + Math.round(r.bytes / 1e6) + ' MB' +
             (r.verifiable ? ', checksummed' : ', no checksum published') + ')' : '';
    set_verSay('Version ' + r.latest + ' is available' + mb + '.' +
      (r.installable ? '' : ' This release ships as a zip, so it has to be '
                          + 'unpacked by hand once it is downloaded.'));
  } else if (r.latest) {
    /* THE ANSWER "NOTHING TO DO" HAS TO BE VISIBLE.
       This used to clear the message, which also hides the panel it sits in --
       so pressing Check for updates showed "Asking GitHub...", then wiped it,
       and the only trace left was three words in the subtitle above. Being
       told nothing is indistinguishable from a button that does not work, and
       it got reported as exactly that. */
    set_verSay(ahead
      ? ('You are running ' + r.current + ', which is NEWER than the latest '
         + 'release (' + r.latest + '). This is a build from source, so there '
         + 'is nothing to update to - the release will catch up when ' +
         r.current + ' is published.')
      : (stuck
         ? ('Release ' + r.latest + ' was published ' + set_verWhen(r.published)
            + ' and is newer than this build (' + r.current + '), but it has '
            + 'no package attached to it - no installer and no zip - so there '
            + 'is nothing to download. The release page is the place to look.')
         : ('You have the latest release. ' + r.latest + ' was published ' +
            set_verWhen(r.published) + ', and nothing newer exists yet.')),
      stuck ? 'warn' : '');
  }
}

/* "2026-09-02T16:02:16Z" -> "on 2 September". Whatever the browser makes of
   the date, because the point is only to show the answer moved. */
function set_verWhen(iso) {
  if (!iso) return 'earlier';
  var d = new Date(iso);
  if (isNaN(d.getTime())) return 'earlier';
  try {
    return 'on ' + d.toLocaleDateString(undefined,
                                        {day: 'numeric', month: 'long'});
  } catch (e) { return 'earlier'; }
}

async function set_verCheck() {
  var btn = set_el('set-ver-check');
  if (btn) btn.disabled = true;
  set_verSay('Asking GitHub...');
  try {
    var r = await API.get('/api/update/check');
    if (r && r.error) set_verSay(r.error, 'warn');
    else { set_update.latest = r; set_verRender(r); }
  } catch (e) {
    set_verSay('Could not reach GitHub.', 'warn');
  }
  if (btn) btn.disabled = false;
}

async function set_verGet() {
  var btn = set_el('set-ver-get');
  if (btn) btn.disabled = true;
  try {
    var r = await API.post('/api/update/download', {});
    if (r && r.error) { set_verSay(r.error, 'warn'); if (btn) btn.disabled = false; }
  } catch (e) {
    set_verSay('Could not start the download.', 'warn');
    if (btn) btn.disabled = false;
  }
}

/* Rides the same status poll as everything else. */
function set_verProgress(u) {
  if (!u || !u.state || u.state === 'idle') return;
  var meter = set_el('set-ver-meter'), fill = set_el('set-ver-fill');
  if (u.state === 'downloading') {
    set_show('set-ver-meter', true);
    var pct = u.total ? Math.round(100 * u.done / u.total) : 0;
    if (fill) fill.style.width = pct + '%';
    if (meter) meter.setAttribute('aria-valuenow', String(pct));
    set_verSay('Downloading ' + (u.version || '') + ' - ' + pct + '%');
    return;
  }
  set_show('set-ver-meter', false);
  if (u.state === 'failed') {
    set_verSay(u.error || 'The download failed.', 'warn');
    var g = set_el('set-ver-get');
    if (g) g.disabled = false;
    return;
  }
  if (u.state === 'ready' && u.path && set_update.path !== u.path) {
    set_update.path = u.path;
    set_show('set-ver-get', false);
    set_show('set-ver-open', true);
    var open = set_el('set-ver-open');
    if (u.installable === false) {
      /* A zip cannot install itself. Point at the file instead of offering a
         button that would only be able to explain why it does not work. */
      set_show('set-ver-open', false);
      set_verSay('Version ' + u.version + ' is downloaded to ' + u.path
                 + '. Unpack it over your installation to update.');
      return;
    }
    if (open) open.disabled = false;
    set_verSay('Version ' + u.version + ' is downloaded and verified. '
               + 'Installing it will close AutoStream, replace this version '
               + 'and start it again.');
  }
}

/* ------------------------------------------------------- a paste-able report

   Every problem this app has had reported to it arrived as a photograph of a
   screen, and a photograph cannot say which OBS version, which build, or what
   the log said thirty seconds earlier. The endpoint that answers all of that
   has existed for a while with nothing able to call it.

   The secrets are removed server-side -- passwords, tokens, and any URL
   carrying one, in the config and in the log lines alike -- so what lands in
   the box is safe to paste anywhere. */

function set_diagSay(text, kind) {
  var el = set_el('set-diag-msg');
  if (el) {
    el.textContent = text || '';
    el.classList.toggle('is-warn', kind === 'warn');
  }
  set_show('set-diag-body', !!text);
}

async function set_diagGet() {
  var btn = set_el('set-diag-get');
  if (btn) btn.disabled = true;
  set_diagSay('Collecting...');
  try {
    var r = await API.post('/api/diagnostics', {});
    if (!r || r.error || !r.text) {
      set_diagSay((r && r.error) || 'Could not build a report.', 'warn');
    } else {
      var box = set_el('set-diag-text');
      if (box) box.value = r.text;
      set_show('set-diag-text', true);
      set_show('set-diag-copy', true);
      var lines = r.text.split('\n').length;
      set_diagSay(lines + ' lines. The secrets have been removed, so this is '
                  + 'safe to paste anywhere.');
    }
  } catch (e) {
    set_diagSay('Could not build a report.', 'warn');
  }
  if (btn) btn.disabled = false;
}

async function set_diagCopy() {
  var box = set_el('set-diag-text');
  if (!box || !box.value) return;
  /* Two ways, because a WebView is not a browser tab: the clipboard API needs
     a permission this host may not grant, and selecting the text at least
     leaves it where Ctrl+C can reach it. */
  try {
    await navigator.clipboard.writeText(box.value);
    toast('Report copied.', 'ok');
    return;
  } catch (e) {
    /* fall through */
  }
  try {
    box.focus();
    box.select();
    if (document.execCommand && document.execCommand('copy')) {
      toast('Report copied.', 'ok');
      return;
    }
  } catch (e2) {
    /* fall through */
  }
  set_diagSay('This window would not let me reach the clipboard. The report '
              + 'is selected above - press Ctrl+C.', 'warn');
}
"""
