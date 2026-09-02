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

SETTINGS_HTML = r"""
<div class="settings-layout">
  <nav class="settings-nav" id="set-nav" aria-label="Settings sections"></nav>
  <div class="settings-body">
    <div id="set-panels">
      <div class="empty"><span class="spin"></span> Loading settings...</div>
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

SETTINGS_JS = r"""
/* ============================ settings page ============================ */

var set_state = {
  loaded: false, loading: false, wired: false, guarded: false,
  sections: [], fields: {}, values: {}, tags: {},
  themes: [], theme: '', active: '', saving: false
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
  return '<div class="field-inline" id="set-themes">' + list.map(function(t){
    var on = String(t.id) === String(cur);
    var sw = (t.swatch || []).map(function(c){
      return '<span style="display:block;height:6px;background:' + set_attr(c) + '"></span>';
    }).join('');
    return '<button class="btn btn-ghost" type="button" data-act="theme"' +
      ' data-theme="' + set_attr(t.id) + '" aria-pressed="' + (on ? 'true' : 'false') + '"' +
      (on ? ' style="box-shadow:inset 0 0 0 2px var(--accent)"' : '') + '>' +
      '<span style="display:block;width:44px;overflow:hidden;border-radius:3px">' + sw + '</span>' +
      '<span>' + esc(t.label || t.id) + '</span>' +
      (on ? '<span aria-hidden="true">' + icon('check') + '</span>' : '') +
      '</button>';
  }).join('') + '</div>';
}

/* ------------------------------------------------------------- page markup */

function set_fieldHtml(f){
  var slug = set_slug(f.path);
  /* time_range owns two inputs, so the label points at the first one. */
  var target = f.control === 'time_range' ? 'set-f-' + slug + '-a' : 'set-f-' + slug;
  var marks = '';
  if (f.restart) marks += '<span class="tag">Needs restart</span>';
  if (f.danger) marks += '<span class="tag">Confirm to change</span>';
  var help = f.help ? '<p class="field-help">' + esc(f.help) + '</p>' : '';
  if (f.danger && f.control === 'readonly'){
    help += '<p class="field-help"><b>Written by setup.</b> Changing this by hand ' +
            'breaks the next session without warning.</p>';
  }
  return '<div class="field" data-path="' + set_attr(f.path) + '" id="set-w-' + slug + '">' +
    '<div class="field-row">' +
      '<div>' +
        '<label class="field-label" id="set-l-' + slug + '" for="' + target + '">' +
          esc(f.label || f.path) + '</label>' +
        '<div class="mono muted">' + esc(f.path) + '</div>' +
        (marks ? '<div class="field-inline">' + marks + '</div>' : '') +
      '</div>' +
      '<div>' + set_controlHtml(f) + help +
        '<p class="field-error hide" id="set-e-' + slug + '"></p>' +
      '</div>' +
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

function set_sectionHtml(sec){
  var plain = [], adv = [];
  (sec.fields || []).forEach(function(f){
    (f.advanced ? adv : plain).push(set_fieldHtml(f));
  });
  var body = '';
  if (sec.advanced){
    /* A whole advanced section stays folded until asked for. */
    body = '<details class="panel"><summary>' +
      '<span class="field-label">Show these settings</span>' +
      '</summary><div>' + plain.join('') + adv.join('') + '</div></details>';
  } else {
    body = plain.join('');
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
    body += '<div class="controls" style="margin-top:12px">' +
      '<button class="btn" type="button" id="set-se-fetch">' +
      'Fetch my StreamElements scenes</button>' +
      '<button class="btn" type="button" id="set-build-screens">' +
      'Create the scenes in OBS</button>' +
      '<span class="muted" id="set-build-screens-note"></span></div>';
  }
  return '<section class="settings-section card' + (sec.id === set_state.active ? '' : ' hide') +
    '" id="set-sec-' + set_slug(sec.id) + '" data-sec="' + set_attr(sec.id) + '">' +
    '<div class="settings-section-head">' +
      '<div class="card-title">' + esc(sec.label || sec.id) + '</div>' +
      (sec.blurb ? '<p class="card-sub">' + esc(sec.blurb) + '</p>' : '') +
    '</div>' +
    '<div class="card-body">' + body + '</div>' +
  '</section>';
}

function set_navHtml(){
  return set_state.sections.map(function(sec){
    return '<button class="settings-nav-item' + (sec.id === set_state.active ? ' is-active' : '') +
      '" type="button" data-sec="' + set_attr(sec.id) + '">' +
      icon(sec.icon || 'settings') + '<span>' + esc(sec.label || sec.id) + '</span></button>';
  }).join('');
}

function set_render(){
  set_el('set-nav').innerHTML = set_navHtml();
  set_el('set-panels').innerHTML = set_state.sections.map(set_sectionHtml).join('');
  set_wireBuildScreens();
  set_wireStreamElements();
  set_growVisible();
  set_updateActions();
}

/* A textarea in a hidden section measures zero, so auto-grow is re-run every
   time a section is revealed rather than once at render. */
function set_growVisible(){
  var boxes = set_el('set-panels').querySelectorAll('.settings-section:not(.hide) textarea');
  for (var i = 0; i < boxes.length; i++) set_grow(boxes[i]);
}

function set_showSection(id){
  set_state.active = id;
  var items = set_el('set-nav').querySelectorAll('.settings-nav-item');
  for (var i = 0; i < items.length; i++){
    items[i].classList.toggle('is-active', items[i].getAttribute('data-sec') === id);
  }
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

  set_el('set-nav').addEventListener('click', function(ev){
    var b = ev.target.closest ? ev.target.closest('.settings-nav-item') : null;
    if (b) set_showSection(b.getAttribute('data-sec'));
  });

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
    } else if (act === 'theme'){
      set_theme(btn.getAttribute('data-theme'));
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

/* The palette lives in the :root block the server renders, so after the theme
   is saved we re-read that block and push it onto the document as inline
   custom properties. That repaints every view without losing this page. */
async function set_repaint(){
  var r = await fetch('/' + (location.search || ''), { cache: 'no-store' });
  var html = await r.text();
  var m = html.match(/:root\s*\{([^}]*)\}/);
  if (!m) throw new Error('no palette');
  var applied = 0;
  m[1].split(';').forEach(function(line){
    var i = line.indexOf(':');
    if (i < 0) return;
    var name = line.slice(0, i).trim(), value = line.slice(i + 1).trim();
    if (name.indexOf('--') !== 0 || !value) return;
    document.documentElement.style.setProperty(name, value);
    applied++;
  });
  if (!applied) throw new Error('no palette');
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
  if (!sections.some(function(s){ return s.id === set_state.active; })){
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
  if (sub && window.SHELL_BOOT && SHELL_BOOT.version){
    sub.textContent = 'AutoStream ' + SHELL_BOOT.version;
  }
}

window.PAGE_SETTINGS = {
  onShow: function(){
    set_guardNav();
    set_wireUpdates();
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

function set_verRender(r) {
  var sub = set_el('set-ver-sub');
  if (sub) {
    sub.textContent = 'AutoStream ' + (r.current || '?') +
      (r.available ? '  -  ' + r.latest + ' is available'
                   : (r.latest ? '  -  up to date' : ''));
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
    set_verSay('');
  }
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
