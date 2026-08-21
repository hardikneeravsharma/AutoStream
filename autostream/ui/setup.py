"""First-run setup wizard: the eight steps between a fresh install and a live channel.

WHY THIS IS A PORT AND NOT A REWRITE
    This flow is the only part of AutoStream a user cannot skip, and its copy is
    hard-won: the Google Cloud instructions encode which console page each setting
    actually lives on today, and the "Publish App" warning exists because leaving the
    OAuth consent screen in Testing mode expires the refresh token after ~7 days and
    streaming then stops silently, days later, with no error the user can connect to
    the cause. Every step index, every request body and every string below is carried
    over verbatim from the pre-rewrite ui_assets.py. Only the markup and the event
    wiring changed.

WHY THE DOM IDS ARE NAMESPACED
    The old wizard owned the whole page, so ids like #title, #privacy and #arm were
    safe. In the new shell every view exists in the document at once, so the Settings
    page also has a control for title.template and would win getElementById() by
    document order (#setup-root is emitted after .app). Every id here is therefore
    prefixed "setup-". Nothing outside this module reads them.

WHY EVENTS ARE DELEGATED INSTEAD OF INLINE onclick
    The old wizard rebuilt the step card with innerHTML and relied on inline onclick
    handlers resolving to globals. That works only while the page script stays a
    single classic top-level scope. One delegated listener on #setup-root, dispatching
    on data-act, survives the card being replaced and does not care how the composed
    script is wrapped -- and it removes the need to interpolate user data into a
    handler string, which is where the old esc() quote bug could have bitten.

SHELL CONTRACT USED
    API.get / API.post, esc(), toast(). Nothing else. Only window.PAGE_SETUP is
    exported; every other top-level name is prefixed setup_.
"""
from __future__ import annotations

from .icons import LOGO_LOCKUP

# ---------------------------------------------------------------------------
# Markup
# ---------------------------------------------------------------------------
# Layout-only inline styles on the two structural wrappers: the wizard is the one
# view that renders with the rail and topbar hidden, so it has no content column to
# inherit a gutter from, and css.py's class vocabulary has no container class for it.
# clamp() keeps the gutters on the design grid at both ends of the range (16px at the
# 420px floor, 24px from ~1090px up) without needing a media query in an attribute.
SETUP_HTML: str = (
    '<div id="setup-page" style="max-width:720px;margin:0 auto;'
    'padding:clamp(24px,4vw,40px) clamp(16px,2.2vw,24px) 56px">\n'
    '  <div id="setup-brand" style="display:flex;align-items:center;gap:16px;'
    'margin:0 0 32px;color:var(--text-primary)">\n'
    '    <span style="display:flex;flex:0 0 auto">' + LOGO_LOCKUP + '</span>\n'
    '    <span class="muted" style="margin-left:auto">First-run setup</span>\n'
    '  </div>\n'
    '  <div id="setup-progress" style="display:flex;align-items:baseline;gap:12px;'
    'margin:0 0 8px">\n'
    '    <span class="muted" id="setup-stepname"></span>\n'
    '    <span class="muted mono" id="setup-stepcount" style="margin-left:auto"></span>\n'
    '  </div>\n'
    '  <div class="steps" id="setup-stepbar"></div>\n'
    '  <div class="card" id="setup-stepcard"></div>\n'
    '</div>\n'
)


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------
# Raw string: the escape sequences below are JavaScript's, not Python's.
SETUP_JS: str = r"""
/* ===================== first-run setup wizard ===================== */
/* Step order, request bodies and copy are a verbatim port of the pre-rewrite
   wizard. See autostream/ui/setup.py for why. */

const setup_STEPS = ['Welcome','Google Cloud','YouTube','OBS','Stream','Timing','Apps','Branding','Finish'];

let setup_step = 0;
let setup_state = {};      /* SetupFlow.snapshot() payload, refreshed by every ok:true */
let setup_wired = false;

const setup_$ = id => document.getElementById(id);
const setup_val = id => { const e = setup_$(id); return e ? e.value : ''; };

/* The shell's esc() round-trips through a text node, so it escapes & < > but not
   quotes. That is fine for element content and wrong for the value="..." attributes
   this wizard writes -- an OBS password containing a quote would break out of the
   attribute. Attribute interpolation goes through this instead. */
function setup_attr(v){
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function setup_toast(message, kind){
  try { toast(message, kind); } catch (e) { /* shell toast is optional here */ }
}

const setup_errText = e => String((e && e.message) || e || 'Request failed');
/* A 403 means the shell has already replaced the document; let it propagate. */
const setup_isAuthFail = e => setup_errText(e).indexOf('403') >= 0;

/* Every wizard endpoint reports its own failures as {ok:false,error} with HTTP 200,
   so a rejection here means the request never completed. _failed marks that case:
   the steps that ignore their response body still must not advance past a request
   that did not happen. */
async function setup_post(path, body){
  try {
    const r = await API.post(path, body || {});
    if (r && typeof r === 'object') return r;
    return {ok:false, error:'Unexpected response from AutoStream.', _failed:true};
  } catch (e) {
    if (setup_isAuthFail(e)) throw e;
    return {ok:false, error: setup_errText(e), _failed:true};
  }
}

/* Message slots. kind '' is a quiet caption (the old <p class="muted">), 'ok' /
   'warn' / 'bad' promote it to the matching note. */
function setup_say(id, kind, html){
  const el = setup_$(id);
  if (!el) return;
  el.className = kind ? ('note ' + kind) : 'muted';
  el.innerHTML = html || '';
}
const setup_spin = t => '<span class="spin"></span> ' + t;

/* ---------------- chrome ---------------- */

function setup_bar(){
  const b = setup_$('setup-stepbar');
  if (b) b.innerHTML = setup_STEPS.map((_, i) =>
    '<div class="stp' + (i < setup_step ? ' done' : (i === setup_step ? ' on' : '')) +
    '"></div>').join('');
  const n = setup_$('setup-stepname');
  if (n) n.textContent = setup_STEPS[setup_step] || '';
  const c = setup_$('setup-stepcount');
  if (c) c.textContent = 'Step ' + (setup_step + 1) + ' of ' + setup_STEPS.length;
}

/* back=false drops the Back button; next=false disables Continue; next as a string
   names an entry in setup_ACTIONS. Mirrors the old nav(back, next, nextLabel). */
function setup_nav(back, next, nextLabel){
  return '<div class="nav">' +
    (back !== false
      ? '<button type="button" class="btn btn-ghost" data-act="back">Back</button>'
      : '') +
    '<button type="button" class="btn btn-primary" id="setup-nextb"' +
    (next === false ? ' disabled' : '') +
    ' data-act="' + (next || 'next') + '">' + (nextLabel || 'Continue') +
    '</button></div>';
}

function setup_card(title, sub, body){
  return '<div class="card-head"><div class="card-title">' + title + '</div>' +
    (sub ? '<div class="card-sub">' + sub + '</div>' : '') +
    '</div><div class="card-body">' + body + '</div>';
}

function setup_opt(v, l, cur){
  return '<option value="' + setup_attr(v) + '"' + (cur === v ? ' selected' : '') +
    '>' + l + '</option>';
}

function setup_go(i){
  setup_step = Math.max(0, Math.min(setup_STEPS.length - 1, i));
  setup_bar();
  setup_draw();
}

/* ---------------- steps ---------------- */

function setup_draw(){
  const c = setup_$('setup-stepcard');
  if (!c) return;

  if (setup_step === 0) c.innerHTML = setup_card(
    'Welcome to AutoStream',
    'This will set up automatic YouTube live streaming that starts by itself when ' +
    'you launch a game. It takes about ten minutes, most of it waiting on Google.',
    '<div class="note"><b>You will need:</b> a YouTube channel with live streaming ' +
    'already enabled, and OBS Studio installed.</div>' +
    '<div class="note warn">Enabling live streaming on a new channel can take up to ' +
    '24 hours. Do that first at youtube.com if you have not already.</div>' +
    setup_nav(false));

  else if (setup_step === 1) c.innerHTML = setup_card(
    'Google Cloud credentials',
    'AutoStream talks to YouTube through your own Google Cloud project, so your ' +
    'daily API allowance is yours alone.',
    '<ol class="steps-list">' +
    '<li>Go to <a href="https://console.cloud.google.com/projectcreate" target="_blank" ' +
    'rel="noopener">console.cloud.google.com</a> and create a project.</li>' +
    '<li>APIs &amp; Services &rarr; Library &rarr; enable <b>YouTube Data API v3</b>.</li>' +
    '<li>Google Auth Platform &rarr; <b>Branding</b>: set an app name and your email.</li>' +
    '<li>Google Auth Platform &rarr; <b>Audience</b>: User type <b>External</b>, then ' +
    '<b>Publish App</b>. <em>Skip verification.</em></li>' +
    '<li>Google Auth Platform &rarr; <b>Data Access</b>: add scopes ' +
    '<code class="mono">.../auth/youtube</code> and ' +
    '<code class="mono">.../auth/youtube.force-ssl</code>.</li>' +
    '<li>Google Auth Platform &rarr; <b>Clients</b> &rarr; Create client &rarr; ' +
    '<b>Desktop app</b> &rarr; Download JSON.</li></ol>' +
    '<div class="note warn"><b>Do not skip step 4.</b> While the app is in Testing mode ' +
    'your login expires after about 7 days and streaming silently stops.</div>' +
    (setup_state.client_secret
      ? '<div class="note ok">Found <b>' + esc(setup_state.client_secret) + '</b></div>'
      : '<div class="field">' +
        '<label class="field-label" for="setup-cs">Paste the contents of the ' +
        'downloaded JSON file</label>' +
        '<textarea class="textarea mono" id="setup-cs" spellcheck="false" ' +
        'placeholder=\'{"installed":{"client_id":"..."}}\'></textarea></div>' +
        '<button type="button" class="btn btn-block" data-act="saveSecret">' +
        'Save credentials</button>' +
        '<p class="muted" id="setup-csmsg"></p>') +
    setup_nav(true, setup_state.client_secret ? null : false));

  else if (setup_step === 2) c.innerHTML = setup_card(
    'Connect your channel',
    'Your browser will open so you can grant AutoStream access to your own channel.',
    '<div class="note warn">You <b>will</b> see &ldquo;Google hasn&rsquo;t verified this ' +
    'app&rdquo;. That is expected for a personal app &mdash; click <b>Advanced</b>, then ' +
    '<b>Go to &hellip; (unsafe)</b>.</div>' +
    (setup_state.channel
      ? '<div class="note ok">Connected as <b>' + esc(setup_state.channel) + '</b></div>'
      : '<button type="button" class="btn btn-primary btn-block" id="setup-authb" ' +
        'data-act="doAuth">Authorise with YouTube</button>' +
        '<p class="muted" id="setup-authmsg"></p>') +
    setup_nav(true, setup_state.channel ? null : false));

  else if (setup_step === 3) c.innerHTML = setup_card(
    'OBS Studio',
    'In OBS: <b>Tools &rarr; WebSocket Server Settings</b>. Tick <b>Enable WebSocket ' +
    'server</b>, keep port 4455, set a password, then click <b>Apply</b> and <b>OK</b>.',
    '<div class="note">The Apply step matters &mdash; OBS does not open the port until ' +
    'the dialog is committed.</div>' +
    '<div class="field-row">' +
    '<div class="field"><label class="field-label" for="setup-obspw">Password</label>' +
    '<input class="input" id="setup-obspw" type="password" autocomplete="off" ' +
    'value="' + setup_attr(setup_state.obs_password || '') + '"></div>' +
    '<div class="field"><label class="field-label" for="setup-obsport">Port</label>' +
    '<input class="input mono" id="setup-obsport" type="number" min="1" max="65535" ' +
    'inputmode="numeric" autocomplete="off" ' +
    'value="' + setup_attr(setup_state.obs_port || 4455) + '"></div>' +
    '</div>' +
    '<div class="field">' +
    '<label class="field-label" for="setup-obspath">Path to obs64.exe</label>' +
    '<input class="input mono" id="setup-obspath" type="text" spellcheck="false" ' +
    'autocomplete="off" value="' + setup_attr(setup_state.obs_path || '') + '"></div>' +
    '<button type="button" class="btn btn-block" data-act="testObs">' +
    'Test connection</button>' +
    '<p class="muted" id="setup-obsmsg"></p>' +
    setup_nav(true, 'saveObs'));

  else if (setup_step === 4) c.innerHTML = setup_card(
    'Stream settings', '',
    '<div class="field">' +
    '<label class="field-label" for="setup-privacy">Who can see your streams</label>' +
    '<select class="select" id="setup-privacy">' +
    setup_opt('unlisted', 'Unlisted - only people with the link', setup_state.privacy) +
    setup_opt('public', 'Public - anyone can find it', setup_state.privacy) +
    setup_opt('private', 'Private - only you', setup_state.privacy) +
    '</select></div>' +
    '<div class="note">Start on <b>unlisted</b> for your first week. You can change ' +
    'this any time.</div>' +
    '<div class="field-row">' +
    '<div class="field"><label class="field-label" for="setup-latency">Latency</label>' +
    '<select class="select" id="setup-latency">' +
    setup_opt('low', 'Low', setup_state.latency) +
    setup_opt('normal', 'Normal', setup_state.latency) +
    setup_opt('ultraLow', 'Ultra low', setup_state.latency) +
    '</select></div>' +
    '<div class="field">' +
    '<label class="field-label" for="setup-switch">When you switch game</label>' +
    '<select class="select" id="setup-switch">' +
    setup_opt('rolling', 'Rename the same stream', setup_state.switch_policy) +
    setup_opt('new_broadcast', 'Start a new stream', setup_state.switch_policy) +
    '</select></div></div>' +
    '<div class="field">' +
    '<label class="field-label" for="setup-title">Title template</label>' +
    '<input class="input mono" id="setup-title" type="text" spellcheck="false" ' +
    'autocomplete="off" value="' +
    setup_attr(setup_state.title || '{game} - {hook} | {day} night stream') + '">' +
    '<div class="field-help">Available: {game} {hook} {day} {date} {time} {n} ' +
    '{session_games}</div></div>' +
    setup_nav(true, 'saveStream'));

  else if (setup_step === 5) c.innerHTML = setup_card(
    'Timing and safety', '',
    '<div class="field-row">' +
    '<div class="field"><label class="field-label" for="setup-arm">' +
    'Wait before streaming (seconds)</label>' +
    '<input class="input" id="setup-arm" type="number" min="0" inputmode="numeric" ' +
    'value="' + setup_attr(setup_state.arm_delay || 30) + '"></div>' +
    '<div class="field"><label class="field-label" for="setup-grace">' +
    'Cancel window before going public</label>' +
    '<input class="input" id="setup-grace" type="number" min="0" inputmode="numeric" ' +
    'value="' + setup_attr(setup_state.abort_grace || 20) + '"></div>' +
    '</div>' +
    '<div class="field-row">' +
    '<div class="field"><label class="field-label" for="setup-cool">' +
    'Keep streaming after you quit (seconds)</label>' +
    '<input class="input" id="setup-cool" type="number" min="0" inputmode="numeric" ' +
    'value="' + setup_attr(setup_state.cooldown || 300) + '"></div>' +
    '<div class="field"><label class="field-label" for="setup-maxh">' +
    'Max session length (hours)</label>' +
    '<input class="input" id="setup-maxh" type="number" min="1" inputmode="numeric" ' +
    'value="' + setup_attr(setup_state.max_session_hours || 8) + '"></div>' +
    '</div>' +
    '<div class="field">' +
    '<div class="field-label">Never start automatically between</div>' +
    '<div class="field-row">' +
    '<div class="field"><label class="field-label" for="setup-q1">From</label>' +
    '<input class="input mono" id="setup-q1" type="text" placeholder="03:30" ' +
    'autocomplete="off" value="' + setup_attr(setup_state.quiet_from || '') + '"></div>' +
    '<div class="field"><label class="field-label" for="setup-q2">Until</label>' +
    '<input class="input mono" id="setup-q2" type="text" placeholder="09:00" ' +
    'autocomplete="off" value="' + setup_attr(setup_state.quiet_to || '') + '"></div>' +
    '</div>' +
    '<div class="field-help">Leave both blank to allow streaming at any hour.</div>' +
    '</div>' +
    setup_nav(true, 'saveTiming'));

  else if (setup_step === 6) {
    c.innerHTML = setup_card(
      'Games and apps',
      'Pick what shows up on your dashboard. Ticked items also offer ' +
      '<b>Open + stream</b>.',
      '<button type="button" class="btn btn-block" data-act="scanApps">' +
      'Scan my computer</button>' +
      '<p class="muted" id="setup-scanmsg"></p>' +
      '<div class="scroll" id="setup-applist"></div>' +
      setup_nav(true, 'saveApps'));
    setup_renderApps();
  }

  else if (setup_step === 7) {
    c.innerHTML = setup_card(
      'Your channel',
      'Used to build a thumbnail from the live picture each time you go live, ' +
      'and to tell your kills from other players when clipping.',
      '<div class="field">' +
      '<label class="field-label" for="setup-chan">Channel name</label>' +
      '<input class="input" id="setup-chan" type="text" autocomplete="off" ' +
      'placeholder="YuvaNeta" value="' + setup_attr(setup_state.channel_name || '') + '"></div>' +
      '<div class="field">' +
      '<label class="field-label" for="setup-logo">Channel logo</label>' +
      '<input class="input mono" id="setup-logo" type="text" spellcheck="false" ' +
      'autocomplete="off" placeholder="C:\Users\you\Pictures\logo.png" value="' +
      setup_attr(setup_state.logo || '') + '">' +
      '<div class="field-help">Full path to a PNG. Transparency strongly preferred - ' +
      'a logo on a white background shows its box over the gameplay.</div></div>' +
      '<div class="field">' +
      '<label class="field-label" for="setup-head">Thumbnail headline</label>' +
      '<input class="input mono" id="setup-head" type="text" spellcheck="false" ' +
      'autocomplete="off" value="' + setup_attr(setup_state.headline || '{game}') + '">' +
      '<div class="field-help">Tokens: {game} {channel} {username} {day} {date} {time}. ' +
      'Keep it short - it is read at about 210 pixels wide.</div></div>' +
      '<div class="field">' +
      '<label class="field-label" for="setup-sub">Second line</label>' +
      '<input class="input mono" id="setup-sub" type="text" spellcheck="false" ' +
      'autocomplete="off" value="' +
      setup_attr(setup_state.subtitle === undefined ? '{channel} | {day} night' : setup_state.subtitle) +
      '"></div>' +
      '<div class="field"><span class="field-label">Your in-game names</span>' +
      '<div class="field-help">Only needed for games you want clipped. Leave blank ' +
      'to skip.</div>' +
      '<div id="setup-usernames"></div></div>' +
      setup_nav(true, 'saveBranding'));
    setup_renderUsernames();
  }

  else if (setup_step === 8) c.innerHTML = setup_card(
    'Nearly there',
    'This creates your permanent YouTube ingestion stream and writes the key into ' +
    'OBS. It only happens once.',
    /* No nav() on the last step: there is deliberately no Back from here. */
    '<button type="button" class="btn btn-primary btn-block" id="setup-finb" ' +
    'data-act="finish">Finish setup</button>' +
    '<p class="muted" id="setup-finmsg"></p>');

  setup_bar();
}

/* ---------------- actions ---------------- */

async function setup_saveSecret(){
  const t = setup_val('setup-cs').trim();
  setup_say('setup-csmsg', '', setup_spin('Checking...'));
  const r = await setup_post('/api/setup/client_secret', {json: t});
  if (r.ok) { setup_state = r.setup || setup_state; setup_draw(); }
  else setup_say('setup-csmsg', 'bad', esc(r.error || 'Invalid JSON'));
}

async function setup_doAuth(){
  const b = setup_$('setup-authb');
  if (b) b.disabled = true;
  setup_say('setup-authmsg', '', setup_spin('Waiting for your browser...'));
  const r = await setup_post('/api/setup/auth', {});
  if (r.ok) { setup_state = r.setup || setup_state; setup_draw(); }
  else {
    if (b) b.disabled = false;
    setup_say('setup-authmsg', 'bad', esc(r.error || 'Failed'));
  }
}

async function setup_testObs(){
  setup_say('setup-obsmsg', '', setup_spin('Connecting...'));
  const r = await setup_post('/api/setup/obs_test', {
    password: setup_val('setup-obspw'),
    port: setup_val('setup-obsport'),
    path: setup_val('setup-obspath')});
  if (r.ok) setup_say('setup-obsmsg', 'ok', 'Connected to OBS ' + esc(r.version) +
    ' - scenes: ' + esc((r.scenes || []).join(', ')));
  else setup_say('setup-obsmsg', 'bad', esc(r.error || 'Could not connect'));
}

async function setup_saveObs(){
  const r = await setup_post('/api/setup/save', {section: 'obs', values: {
    password: setup_val('setup-obspw'),
    port: parseInt(setup_val('setup-obsport'), 10) || 4455,
    path: setup_val('setup-obspath')}});
  if (r._failed) {
    setup_say('setup-obsmsg', 'bad', esc(r.error));
    setup_toast(r.error, 'error');
    return;
  }
  setup_go(setup_step + 1);
}

function setup_renderUsernames(){
  const host = document.getElementById('setup-usernames');
  if (!host) return;
  /* Only games, not every shortcut - asking for an in-game name against
     Notepad would be noise. */
  const games = (setup_state.apps || []).filter(function(a){
    return a.source === 'steam' || a.source === 'epic';
  }).slice(0, 12);
  if (!games.length){
    host.innerHTML = '<p class="muted">No games found yet. You can add these later ' +
                     'in config\games.yaml.</p>';
    return;
  }
  host.innerHTML = games.map(function(a){
    const prev = (setup_state.usernames || {})[a.exe || ''] || '';
    return '<div class="field-row" style="align-items:center">' +
      '<label class="field-label" for="setup-un-' + setup_attr(a.key) + '">' +
      esc(a.name) + '</label>' +
      '<input class="input" id="setup-un-' + setup_attr(a.key) + '" type="text" ' +
      'autocomplete="off" data-exe="' + setup_attr(a.exe || '') + '" ' +
      'placeholder="your name in this game" value="' + setup_attr(prev) + '"></div>';
  }).join('');
}

async function setup_saveBranding(){
  const names = {};
  const inputs = document.querySelectorAll('#setup-usernames input[data-exe]');
  for (let i = 0; i < inputs.length; i++){
    const exe = inputs[i].getAttribute('data-exe');
    const val = (inputs[i].value || '').trim();
    if (exe && val) names[exe] = val;
  }
  const chan = setup_val('setup-chan');
  const r = await setup_post('/api/setup/save', {section: 'branding', values: {
    channel_name: chan,
    logo: setup_val('setup-logo'),
    headline: setup_val('setup-head'),
    subtitle: setup_val('setup-sub'),
    /* Only switch thumbnails on if there is something to put on them. */
    enabled: !!(chan || setup_val('setup-logo')),
    upload: true,
    usernames: names}});
  if (r._failed) { setup_toast(r.error, 'error'); return; }
  setup_go(setup_step + 1);
}

async function setup_saveStream(){
  const r = await setup_post('/api/setup/save', {section: 'stream', values: {
    privacy: setup_val('setup-privacy'),
    latency: setup_val('setup-latency'),
    switch_policy: setup_val('setup-switch'),
    title: setup_val('setup-title')}});
  if (r._failed) { setup_toast(r.error, 'error'); return; }
  setup_go(setup_step + 1);
}

async function setup_saveTiming(){
  const r = await setup_post('/api/setup/save', {section: 'timing', values: {
    arm_delay: setup_val('setup-arm'),
    abort_grace: setup_val('setup-grace'),
    cooldown: setup_val('setup-cool'),
    max_session_hours: setup_val('setup-maxh'),
    quiet_from: setup_val('setup-q1'),
    quiet_to: setup_val('setup-q2')}});
  if (r._failed) { setup_toast(r.error, 'error'); return; }
  setup_go(setup_step + 1);
}

async function setup_scanApps(){
  setup_say('setup-scanmsg', '', setup_spin('Looking for games and apps...'));
  const r = await setup_post('/api/setup/scan', {});
  if (r._failed) { setup_say('setup-scanmsg', 'bad', esc(r.error)); return; }
  setup_state.apps = r.apps || [];
  setup_say('setup-scanmsg', '', 'Found ' + setup_state.apps.length + '.');
  setup_renderApps();
}

function setup_renderApps(){
  const box = setup_$('setup-applist');
  if (!box) return;
  const list = setup_state.apps || [];
  box.innerHTML = list.length ? list.map((a, i) =>
    '<label class="chk"><input type="checkbox" data-i="' + i + '"' +
    (a.stream ? ' checked' : '') + '>' +
    '<span class="t"><b>' + esc(a.name) + '</b><span>' + esc(a.source) +
    ' &middot; ' + esc(a.exe) + '</span></span></label>').join('')
    : '<div class="empty">Nothing yet - press Scan.</div>';
}

async function setup_saveApps(){
  const list = setup_state.apps || [];
  document.querySelectorAll('#setup-applist input[type=checkbox]').forEach(cb => {
    const a = list[parseInt(cb.dataset.i, 10)];
    if (a) a.stream = cb.checked;
  });
  const r = await setup_post('/api/setup/apps', {apps: list});
  if (r._failed) {
    setup_say('setup-scanmsg', 'bad', esc(r.error));
    setup_toast(r.error, 'error');
    return;
  }
  setup_go(setup_step + 1);
}

async function setup_finish(){
  const b = setup_$('setup-finb');
  if (b) b.disabled = true;
  setup_say('setup-finmsg', '', setup_spin('Creating your stream...'));
  const r = await setup_post('/api/setup/finish', {});
  if (r.ok) {
    setup_say('setup-finmsg', 'ok', 'Done. Starting up...');
    setTimeout(() => location.reload(), 1600);
  } else {
    if (b) b.disabled = false;
    setup_say('setup-finmsg', 'bad', esc(r.error || 'Failed'));
  }
}

/* ---------------- wiring ---------------- */

const setup_ACTIONS = {
  back:       () => setup_go(setup_step - 1),
  next:       () => setup_go(setup_step + 1),
  saveSecret: setup_saveSecret,
  doAuth:     setup_doAuth,
  testObs:    setup_testObs,
  saveObs:    setup_saveObs,
  saveStream: setup_saveStream,
  saveBranding: setup_saveBranding,
  saveTiming: setup_saveTiming,
  scanApps:   setup_scanApps,
  saveApps:   setup_saveApps,
  finish:     setup_finish
};

function setup_wire(){
  if (setup_wired) return;
  const root = setup_$('setup-root');
  if (!root) return;
  root.addEventListener('click', function(ev){
    const t = ev.target && ev.target.closest ? ev.target.closest('[data-act]') : null;
    if (!t || t.disabled) return;
    const fn = setup_ACTIONS[t.getAttribute('data-act')];
    if (!fn) return;
    ev.preventDefault();
    fn();
  });
  setup_wired = true;
}

/* The shell may hand us the bootstrap payload it already fetched; if it does not,
   fetch our own rather than depending on a shared global that may not exist. */
async function setup_bootstrap(boot){
  let b = boot;
  if (!b || !b.setup) {
    try { if (BOOT && BOOT.setup) b = BOOT; } catch (e) { /* shell may not expose it */ }
  }
  if (!b || !b.setup) {
    try { b = await API.get('/api/bootstrap'); } catch (e) { b = null; }
  }
  setup_state = (b && b.setup) ? b.setup : {};
}

window.PAGE_SETUP = {
  start: async function(boot){
    setup_wire();
    setup_step = 0;
    setup_bar();
    const c = setup_$('setup-stepcard');
    if (c) c.innerHTML = setup_card('Getting ready', '',
      '<p class="muted">' + setup_spin('Loading setup...') + '</p>');
    await setup_bootstrap(boot);
    setup_draw();
  }
};
"""
