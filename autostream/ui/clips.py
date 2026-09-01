r"""The Clips page: turn a finished stream into clips.

SHAPE OF THE PAGE
    A list of past streams on top, the options for the selected one below, and
    one primary button. Everything the run needs is visible at once, because
    the choices interact -- a thirty-second clip and a minimum of three kills
    behave very differently together than either does alone -- and hiding half
    of them behind a dialog would mean guessing at the result.

PROGRESS COMES FROM THE STATUS POLL
    A run takes minutes. Rather than invent a second polling loop, the job
    publishes into the payload the shell already fetches every two seconds and
    this page reads it in onTick. That means progress survives a reload and
    keeps working if the page is closed and reopened mid-run, neither of which
    a page-local timer would manage.

NAMING
    Everything top level is prefixed clip_, and the single unprefixed global is
    window.PAGE_CLIPS. All page files share one scope, so a duplicate top-level
    const is a SyntaxError that takes the whole UI down.
"""
from __future__ import annotations

from .icons import ICONS


def _svg(name: str, size: int = 16) -> str:
    body = ICONS.get(name, "")
    return (f'<svg class="icon" viewBox="0 0 24 24" width="{size}" height="{size}"'
            f' aria-hidden="true" focusable="false">{body}</svg>')


CLIPS_HTML: str = (
    """
<div class="clip-setup card hide" id="clip-setup">
  <div class="card-head"><h2 class="card-title">One thing missing</h2></div>
  <p class="card-sub" id="clip-setup-text"></p>
  <pre class="clip-pre mono" id="clip-setup-detail"></pre>
</div>

<div class="card" id="clip-local">
  <div class="card-head">
    <div>
      <h2 class="card-title">Clip a video file</h2>
      <p class="card-sub">Any recording you already have - AutoStream does not have
         to have made it. Pick the file, say which game it is, and the highlights
         come out the same way they do for a stream.</p>
    </div>
  </div>
  <div class="card-body">
    <div class="localclip">
      <button class="btn" type="button" data-act="pick-local">Choose video&hellip;</button>
      <div class="field">
        <label class="field-label" for="clip-local-game">Game</label>
        <select class="select" id="clip-local-game"></select>
      </div>
      <button class="btn btn-primary" type="button" data-act="use-local"
              id="clip-local-go" disabled>Use this video</button>
      <p class="localclip-path" id="clip-local-path"></p>
      <div class="panel hide" id="clip-local-namewrap" style="flex:1 1 100%">
        <p class="muted" id="clip-local-namewhy"></p>
        <div class="field-inline">
          <input class="input" id="clip-local-name" type="text" spellcheck="false"
                 autocomplete="off" placeholder="Your name, exactly as the feed shows it">
          <button class="btn btn-sm" type="button" data-act="save-name">Save name</button>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="searchbar">
  <span class="overline">Streams</span>
  <select class="select" id="clip-game" aria-label="Filter by game">
    <option value="">All games</option>
  </select>
  <button class="btn btn-sm" type="button" id="clip-refresh">"""
    + _svg("refresh")
    + """<span>Refresh</span></button>
  <span class="muted" id="clip-count"></span>
</div>

<div class="panel" id="clip-listwrap">
  <div class="clip-list" id="clip-list"></div>
</div>

<div class="empty hide" id="clip-empty">"""
    + _svg("film", 20)
    + """<p>No finished streams yet.</p>
  <p class="muted">Turn on <strong>Record while streaming</strong> in Settings, then
     stream once. When it ends, the recording shows up here.</p>
</div>

<div class="card hide" id="clip-made-card">
  <div class="card-head">
    <div>
      <h2 class="card-title">This stream already has clips</h2>
      <p class="card-sub" id="clip-made-sub">&nbsp;</p>
    </div>
    <div class="field-inline">
      <button class="btn btn-sm btn-ghost" type="button" id="clip-made-hide">
        <span>Hide</span></button>
      <button class="btn btn-sm" type="button" id="clip-made-play">
        <span>Play them</span></button>
    </div>
  </div>
  <div class="card-body">
    <div class="clip-made-list" id="clip-made-list"></div>
  </div>
</div>

<div class="card hide" id="clip-player-card">
  <div class="card-head">
    <div>
      <h2 class="card-title" id="clip-play-title">&nbsp;</h2>
      <p class="card-sub" id="clip-play-sub">&nbsp;</p>
    </div>
    <button class="btn btn-sm btn-ghost" type="button" id="clip-play-close">
      <span>Close</span></button>
  </div>
  <div class="card-body clip-play-body">
    <div class="clip-play-left">
      <div class="clip-play-stage">
        <video id="clip-video" playsinline preload="metadata"></video>
      </div>

      <div class="clip-play-bar">
        <button class="btn btn-icon" type="button" data-play="prev"
                title="Previous clip" aria-label="Previous clip">&#9198;</button>
        <button class="btn btn-icon btn-primary" type="button" data-play="toggle"
                title="Play or pause (space)" aria-label="Play or pause"
                id="clip-play-toggle">&#9654;</button>
        <button class="btn btn-icon" type="button" data-play="next"
                title="Next clip" aria-label="Next clip">&#9197;</button>
        <span class="clip-play-time mono" id="clip-play-time">0:00 / 0:00</span>
        <input class="clip-play-seek" id="clip-play-seek" type="range"
               min="0" max="1000" value="0" step="1" aria-label="Seek">
        <button class="btn btn-icon" type="button" data-play="mute"
                title="Mute (m)" aria-label="Mute" id="clip-play-mute">&#128266;</button>
        <input class="clip-play-vol" id="clip-play-vol" type="range"
               min="0" max="100" value="100" step="1" aria-label="Volume">
        <select class="select clip-play-speed" id="clip-play-speed"
                aria-label="Playback speed">
          <option value="0.25">0.25x</option>
          <option value="0.5">0.5x</option>
          <option value="0.75">0.75x</option>
          <option value="1" selected>1x</option>
          <option value="1.25">1.25x</option>
          <option value="1.5">1.5x</option>
          <option value="2">2x</option>
        </select>
        <button class="btn btn-icon" type="button" data-play="full"
                title="Fullscreen (f)" aria-label="Fullscreen">&#9974;</button>
      </div>
      <p class="field-help" id="clip-play-keys">Space plays and pauses. Left and
         right step five seconds, up and down change the volume, m mutes,
         f is fullscreen, n and p change clip.</p>
    </div>

    <div class="clip-play-right">
      <div class="panel">
        <h3 class="clip-play-h">This clip</h3>
        <dl class="clip-play-info" id="clip-play-meta"></dl>
      </div>

      <div class="panel">
        <h3 class="clip-play-h">Caption</h3>
        <div class="field-inline">
          <button class="switch is-on" type="button" role="switch"
                  id="clip-play-capsw" aria-checked="true"
                  aria-label="Burn a caption"><span class="switch-dot"></span></button>
          <input class="input" id="clip-play-cap" type="text"
                 placeholder="the caption to burn" style="flex:1 1 8rem">
        </div>
      </div>

      <div class="panel">
        <h3 class="clip-play-h">Spoken line</h3>
        <div class="field-inline">
          <button class="switch" type="button" role="switch"
                  id="clip-play-saysw" aria-checked="false"
                  aria-label="Speak a line"><span class="switch-dot"></span></button>
          <input class="input" id="clip-play-say" type="text"
                 placeholder="what it should say" style="flex:1 1 8rem">
        </div>
        <div class="field-inline" style="margin-top:.4rem">
          <select class="select" id="clip-play-voice" aria-label="Voice"
                  style="flex:1 1 8rem"></select>
          <button class="btn btn-sm" type="button" id="clip-play-hear">Hear it</button>
        </div>
      </div>

      <div class="panel">
        <h3 class="clip-play-h">Framing</h3>
        <div class="seg" id="clip-play-vert" role="group" aria-label="Vertical framing">
          <button class="seg-btn" type="button" data-vert="crop">Zoom in</button>
          <button class="seg-btn" type="button" data-vert="fit">Fit whole frame</button>
        </div>
        <p class="field-help">Zoom keeps the action large and loses the edges.
           Fit keeps everything and makes the gameplay smaller.</p>
      </div>

      <div class="panel">
        <h3 class="clip-play-h">Trim</h3>
        <div class="field-inline">
          <button class="btn btn-sm" type="button" data-play="setin">Start here</button>
          <button class="btn btn-sm" type="button" data-play="setout">End here</button>
          <button class="btn btn-sm btn-ghost" type="button" data-play="cleartrim">Reset</button>
        </div>
        <p class="field-help mono" id="clip-play-trim">whole clip</p>
      </div>

      <div class="clip-play-apply">
        <span class="muted" id="clip-play-editmsg"></span>
        <button class="btn btn-primary" type="button" id="clip-play-apply">
          <span>Apply and re-render</span></button>
      </div>
    </div>
  </div>
</div>

<div class="card hide" id="clip-review-card">
  <div class="card-head">
    <div>
      <h2 class="card-title">Review the clips before cutting</h2>
      <p class="card-sub" id="clip-review-sub">Nothing has been encoded yet. Each
         clip below can have its own caption and its own spoken line, or neither.</p>
    </div>
    <div class="field-inline">
      <button class="btn btn-sm btn-ghost" type="button" id="clip-review-close">
        <span>Discard</span></button>
      <button class="btn btn-primary" type="button" id="clip-review-cut">
        <span>Cut these clips</span></button>
    </div>
  </div>
  <div class="card-body">
    <div class="panel" id="clip-review-bulk">
      <div class="field-inline">
        <label class="field-label" for="clip-review-voice-all">Voice for every clip</label>
        <select class="select" id="clip-review-voice-all" style="max-width:16rem"></select>
        <button class="btn btn-sm" type="button" id="clip-review-play-all">Hear it</button>
        <span class="muted" id="clip-review-voicewhy"></span>
      </div>
    </div>
    <div class="clip-review-list" id="clip-review-list"></div>
  </div>
</div>

<div class="card hide" id="clip-options">
  <div class="card-head">
    <div>
      <h2 class="card-title" id="clip-chosen">&nbsp;</h2>
      <p class="card-sub" id="clip-chosen-sub">&nbsp;</p>
    </div>
    <button class="btn btn-ghost btn-sm" type="button" data-act="reveal-src">"""
    + _svg("folder")
    + """<span>Show file</span></button>
  </div>

  <div class="panel hide" id="clip-demowrap">
    <p class="muted" id="clip-demotext"></p>
    <textarea class="textarea mono" id="clip-democodes" rows="3" spellcheck="false"
              placeholder="Paste the match sharing code, or the whole steam:// link.
One per line - a long session often covers several matches."></textarea>
    <div class="field-inline" style="margin-top:8px">
      <button class="btn" type="button" data-act="get-demos">Download in Counter-Strike</button>
      <span class="muted" id="clip-demomsg"></span>
    </div>
  </div>

  <div class="panel clip-warn hide" id="clip-wrongwrap">
    <p class="muted" id="clip-wrongtext"></p>
    <div class="field-inline">
      <select class="select" id="clip-gamefix" aria-label="Correct the game"></select>
      <button class="btn btn-sm" type="button" data-act="setgame">Use this game</button>
    </div>
  </div>

  <div class="clip-grid">
    <div class="field clip-span2">
      <span class="field-label">Style</span>
      <div class="seg" id="clip-style" role="group" aria-label="Clip style"></div>
      <p class="field-help" id="clip-style-help"></p>
    </div>

    <div class="field hide" id="clip-rounds-field">
      <span class="field-label">What to clip</span>
      <div class="field-inline">
        <button class="switch is-on" type="button" role="switch" id="clip-rounds"
                aria-checked="true"><span class="switch-dot"></span></button>
        <label for="clip-rounds">Whole rounds, not bursts of kills</label>
      </div>
      <p class="field-help">Counter-Strike is scored by the round, so a 1v3 won
         with one kill matters more than an ordinary double. Reads the scoreboard
         as well as the kill feed.</p>
      <div class="clip-types" id="clip-types"></div>
      <div class="field-inline" style="margin-top:8px">
        <button class="switch is-on" type="button" role="switch" id="clip-whole"
                aria-checked="true"><span class="switch-dot"></span></button>
        <label for="clip-whole">Keep the whole round</label>
      </div>
      <p class="field-help">A round runs 30 to 115 seconds. Off trims to the
         finish instead, which is what fits a Short.</p>
    </div>

    <div class="field" id="clip-min-field">
      <span class="field-label">Minimum kills in a clip</span>
      <div class="seg" id="clip-min" role="group" aria-label="Minimum kills"></div>
      <p class="field-help">A clip is only kept if this many kills land inside it,
         not just inside the fight it came from.</p>
    </div>

    <div class="field">
      <span class="field-label">Clip length</span>
      <div class="seg" id="clip-len" role="group" aria-label="Clip length"></div>
      <p class="field-help">A fixed length centres on the busiest seconds of each
         fight. Whole moment follows the fight however long it runs.</p>
    </div>

    <div class="field">
      <span class="field-label">Vertical copies</span>
      <div class="seg" id="clip-vert" role="group" aria-label="Vertical copies"></div>
      <p class="field-help">A 9:16 export for Shorts and Reels, made from each clip.</p>
    </div>

    <div class="field">
      <span class="field-label">Montage</span>
      <div class="field-inline">
        <button class="switch" type="button" role="switch" id="clip-montage"
                aria-checked="true" data-act="montage"><span class="switch-track">
          <span class="switch-thumb"></span></span></button>
        <select class="select" id="clip-trans" aria-label="Transition"></select>
        <select class="select" id="clip-transms" aria-label="Transition length">
          <option value="300">0.3s</option>
          <option value="500" selected>0.5s</option>
          <option value="800">0.8s</option>
          <option value="1200">1.2s</option>
        </select>
      </div>
      <p class="field-help" id="clip-trans-help">All the clips joined into one video.</p>
    </div>
  </div>

  <div class="clip-actions">
    <span class="muted" id="clip-hint"></span>
    <div class="field-inline">
      <button class="btn btn-ghost btn-sm" type="button" data-act="calibrate">"""
    + _svg("wand")
    + """<span>Calibrate a game</span></button>
      <button class="btn btn-ghost" type="button" id="clip-review">"""
    + _svg("wand")
    + """<span>Review clips first</span></button>
      <button class="btn btn-primary" type="button" id="clip-go">"""
    + _svg("scissors")
    + """<span>Make clips</span></button>
    </div>
  </div>
</div>

<div class="card hide" id="clip-progress">
  <div class="card-head">
    <h2 class="card-title" id="clip-prog-title">Working</h2>
    <button class="btn btn-danger btn-sm" type="button" data-act="cancel">Cancel</button>
  </div>
  <div class="clip-steps" id="clip-steps"></div>
  <div class="meter" id="clip-meter" role="progressbar" aria-valuemin="0"
       aria-valuemax="100" aria-valuenow="0"><span class="meter-fill" id="clip-fill"></span></div>
  <p class="muted" id="clip-prog-msg"></p>
</div>

<div class="card hide" id="clip-results">
  <div class="card-head">
    <div>
      <h2 class="card-title" id="clip-res-title">Done</h2>
      <p class="card-sub" id="clip-res-sub"></p>
    </div>
    <button class="btn btn-sm" type="button" data-act="reveal-out">"""
    + _svg("folder")
    + """<span>Open folder</span></button>
  </div>
  <div class="clip-results" id="clip-res-list"></div>

  <div class="panel hide" id="clip-up" style="margin-top:12px">
    <div class="field-inline" style="flex-wrap:wrap;gap:10px">
      <div class="field" style="min-width:150px">
        <label class="field-label" for="clip-up-privacy">Who can see them</label>
        <select class="select" id="clip-up-privacy">
          <option value="unlisted">Unlisted - only with the link</option>
          <option value="public">Public</option>
          <option value="private">Private - only you</option>
        </select>
      </div>
      <div class="field" style="flex:1 1 260px;min-width:0">
        <label class="field-label" for="clip-up-title">Title</label>
        <input class="input" id="clip-up-title" type="text" spellcheck="false"
               autocomplete="off">
      </div>
      <button class="btn btn-primary" type="button" data-act="upload"
              id="clip-up-go">Upload</button>
      <button class="btn btn-danger btn-sm hide" type="button"
              data-act="upload-cancel" id="clip-up-stop">Stop</button>
    </div>
    <p class="field-help" id="clip-up-note"></p>
    <div class="meter hide" id="clip-up-meter"><div class="meter-fill"
         id="clip-up-fill"></div></div>
  </div>
</div>

<div class="scrim hide" id="clip-cal-scrim">
  <div class="modal clip-modal" role="dialog" aria-modal="true"
       aria-labelledby="clip-cal-title">
    <h2 class="modal-title" id="clip-cal-title">Calibrate a kill marker</h2>
    <div class="modal-body">
      <p class="muted">Scrub to a moment just after you got a kill, then drag a box
         tightly around the marker the game draws &mdash; the skull, the X, whatever
         it uses. AutoStream will check the box actually stands out before saving.</p>

      <div class="clip-cal-stage" id="clip-cal-stage">
        <img id="clip-cal-img" alt="Frame from the recording">
        <div class="clip-cal-box hide" id="clip-cal-rect"></div>
        <div class="clip-cal-wait" id="clip-cal-wait"><span class="spin"></span></div>
      </div>

      <div class="field-inline clip-cal-scrub">
        <button class="btn btn-ghost btn-sm" type="button" data-cal="-30">&minus;30s</button>
        <button class="btn btn-ghost btn-sm" type="button" data-cal="-5">&minus;5s</button>
        <input class="clip-range" type="range" id="clip-cal-range" min="0" max="100" value="0">
        <button class="btn btn-ghost btn-sm" type="button" data-cal="5">+5s</button>
        <button class="btn btn-ghost btn-sm" type="button" data-cal="30">+30s</button>
        <span class="mono muted" id="clip-cal-time">00:00:00</span>
      </div>

      <div class="field-row">
        <label class="field-label" for="clip-cal-name">Game name</label>
        <input class="input" type="text" id="clip-cal-name" maxlength="60"
               placeholder="Delta Force">
      </div>

      <div class="field-row">
        <label class="field-label">How kills show</label>
        <div class="seg" id="clip-cal-mode">
          <button class="seg-btn is-on" type="button" data-mode="template">A marker on screen</button>
          <button class="seg-btn" type="button" data-mode="killfeed">Only in the kill feed</button>
        </div>
      </div>

      <div class="field-row hide" id="clip-cal-player-row">
        <label class="field-label" for="clip-cal-player">Your in-game name</label>
        <input class="input" type="text" id="clip-cal-player" maxlength="60"
               placeholder="exactly as it appears in the feed">
      </div>
      <p class="muted small hide" id="clip-cal-mode-hint"></p>
      <p class="field-error hide" id="clip-cal-err"></p>
      <div class="clip-verdict hide" id="clip-cal-verdict"></div>
    </div>
    <div class="modal-actions">
      <button class="btn btn-ghost" type="button" data-act="cal-close">Close</button>
      <button class="btn btn-primary" type="button" id="clip-cal-save" disabled>
        Test and save</button>
    </div>
  </div>
</div>
"""
)


CLIPS_JS: str = r"""
/* ------------------------------------------------------------------ state */

var clip_state = {
  loaded: false, wired: false, busy: false,
  sessions: [], profiles: [], status: null, defaults: {},
  outputDir: '', games: [], game: '',
  pick: null,                 /* the selected session row */
  style: 'shortform',
  min: '2', len: '15', vert: 'crop', montage: true,
  trans: 'fade', transMs: 500,
  lastJob: null,
  reviewing: false,          /* a plan-only run is on its way */
  review: null,              /* {folder, source, rows: [...]} once it lands */
  voices: null,              /* the installed voices, once fetched */
  audio: null,               /* the one <audio> that plays samples */
  made: null,                /* clips a previous run already produced */
  player: null,              /* {list, i, folder, trim} while the player is up */
  editing: false,            /* a re-render is in flight */
  stopping: false,           /* Cancel pressed, job not finished yet */
  cal: {open: false, t: 0, dur: 0, box: null, drag: null, path: '', busy: false}
};

/* Styles set pre-roll, tail and length together. The numbers come from how
   gaming clips are actually cut -- about a second or two before the kill and
   two after -- because most viewers who leave a short do so inside the first
   three seconds, and a long run-up spends the hook on nothing happening. */
var CLIP_STYLES = [
  ['shortform', 'Short-form', '1.5s before, 2s after, 15s clips. Opens on the action.'],
  ['montage',   'Montage cut', '1s before, 1.5s after, 6s clips. Cuts together without dragging.'],
  ['context',   'Full context', '6s before, 4s after, 30s clips. Better for watching back than posting.'],
  ['custom',    'Custom', 'Uses the lengths you pick below.']
];

var CLIP_MINS = [['1', '1+'], ['2', '2+'], ['3', '3+'], ['4', '4+'], ['5', '5+']];
var CLIP_LENS = [['10', '10s'], ['20', '20s'], ['30', '30s'], ['45', '45s'],
                 ['auto', 'Whole moment']];
var CLIP_VERTS = [['crop', 'Zoom'], ['fit', 'Fit'], ['none', 'None']];
/* Labels are ours; the values are real ffmpeg xfade names. "Swirl" maps to
   radial because xfade has 58 transitions and none of them is a swirl - radial
   sweeps round the centre and is the nearest real thing. */
var CLIP_TRANS = [['fade', 'Fade'], ['fadeblack', 'Dip to black'],
                  ['dissolve', 'Dissolve'], ['radial', 'Swirl'],
                  ['zoomin', 'Zoom'], ['slideleft', 'Slide'],
                  ['pixelize', 'Pixelize'], ['wipeleft', 'Wipe'],
                  ['cut', 'Hard cut'], ['mixed', 'Mixed']];
var CLIP_STEPS = [['scan', 'Find kills'], ['cut', 'Cut clips'],
                  ['vertical', 'Vertical'], ['montage', 'Montage']];

function clip_el(id) { return document.getElementById(id); }
function clip_show(id, on) {
  var e = clip_el(id);
  if (e) e.classList.toggle('hide', !on);
}

function clip_bytes(n) {
  if (!n) return '';
  var gb = n / 1073741824;
  if (gb >= 1) return gb.toFixed(1) + ' GB';
  return Math.round(n / 1048576) + ' MB';
}

function clip_when(ts) {
  if (!ts) return '';
  var d = new Date(ts * 1000);
  var now = new Date();
  var sameDay = d.toDateString() === now.toDateString();
  var time = d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  if (sameDay) return 'Today ' + time;
  return d.toLocaleDateString([], {day: 'numeric', month: 'short'}) + ' ' + time;
}

function clip_dur(s) {
  if (!s) return '';
  var h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? (h + 'h ' + m + 'm') : (m + 'm');
}

/* ------------------------------------------------------------------ chrome */

function clip_segs(host, items, current, act) {
  var h = '';
  for (var i = 0; i < items.length; i++) {
    var on = String(items[i][0]) === String(current);
    h += '<button class="seg-btn' + (on ? ' is-active' : '') + '" type="button"' +
         ' data-act="' + act + '" data-val="' + esc(items[i][0]) + '"' +
         ' aria-pressed="' + (on ? 'true' : 'false') + '">' +
         esc(items[i][1]) + '</button>';
  }
  var e = clip_el(host);
  if (e) e.innerHTML = h;
}

function clip_options(sel, items, current) {
  var e = clip_el(sel);
  if (!e) return;
  var h = '';
  for (var i = 0; i < items.length; i++) {
    h += '<option value="' + esc(items[i][0]) + '"' +
         (String(items[i][0]) === String(current) ? ' selected' : '') + '>' +
         esc(items[i][1]) + '</option>';
  }
  e.innerHTML = h;
}

/* -------------------------------------------------------------- the list */

function clip_row(s, i) {
  var gone = !s.has_recording;
  var sub = [];
  if (s.duration) sub.push(clip_dur(s.duration));
  if (s.recording_bytes) sub.push(clip_bytes(s.recording_bytes));
  if (s.kills_known) sub.push(s.kills_known + ' kills found');
  /* OBS was already recording when the session started, so most of this file
     is footage AutoStream never saw - possibly a different game entirely. */
  if (s.game_uncertain) sub.push(clip_dur(s.pre_session_seconds) + ' before this session');
  /* Only for games that HAVE replays -- has_demo is null for the rest, and
     "no demo" against Valorant would read as a fault rather than as not
     applicable. With one, a run reads twelve minutes instead of the whole
     recording and the clips carry real round context; without, it reads
     everything and guesses the rounds off the screen. */
  if (s.demo_state === 'have') sub.push('demo on disk');
  /* "listed" means the match is in your Counter-Strike history and the
     download has not finished -- the .dem.info is written when the match
     appears, the .dem when the download lands. Saying "no demo" there sends
     somebody looking for a match that is already in front of them. */
  else if (s.demo_state === 'listed') sub.push('demo not downloaded yet');
  else if (s.demo_state === 'none') sub.push('no demo - slower, rougher clips');

  var tag;
  if (gone) tag = '<span class="tag is-warn">Recording gone</span>';
  else if (s.demo_state === 'listed' && s.can_scan)
    tag = '<span class="tag is-warn">Demo not downloaded</span>';
  else if (s.demo_state === 'none' && s.can_scan)
    tag = '<span class="tag is-warn">No demo</span>';
  else if (s.game_uncertain) tag = '<span class="tag is-warn">Game may be wrong</span>';
  else if (s.can_scan) tag = '<span class="tag">' + esc(s.profile) + '</span>';
  /* A killfeed game IS calibrated - it is just missing the in-game name. Saying
     "Not calibrated" would send the user to draw a box that already exists. */
  else if (s.scan_mode === 'killfeed') tag = '<span class="tag is-warn">No name set</span>';
  else tag = '<span class="tag is-warn">Not calibrated</span>';

  var on = clip_state.pick && clip_state.pick.recording_path === s.recording_path;
  return '<button class="clip-row' + (on ? ' is-active' : '') +
    (gone ? ' is-gone' : '') + '" type="button" data-act="pick" data-i="' + i + '">' +
    '<span class="clip-row-main">' +
      '<span class="clip-row-name">' + esc(s.game || 'Unknown game') + '</span>' +
      '<span class="clip-row-sub muted">' + esc(sub.join('  ·  ')) + '</span>' +
    '</span>' +
    '<span class="clip-row-when muted">' + esc(clip_when(s.display_started || s.started)) + '</span>' +
    '<span class="clip-row-tag">' + tag + '</span>' +
    '</button>';
}

function clip_renderList() {
  var host = clip_el('clip-list');
  if (!host) return;
  var rows = clip_state.sessions;
  if (clip_state.game) {
    rows = rows.filter(function (r) { return r.game === clip_state.game; });
  }
  clip_state.shown = rows;
  host.innerHTML = rows.map(clip_row).join('');

  var none = clip_state.sessions.length === 0;
  clip_show('clip-empty', none);
  clip_show('clip-listwrap', !none);
  var c = clip_el('clip-count');
  if (c) {
    c.textContent = none ? '' :
      rows.length + (rows.length === 1 ? ' stream' : ' streams');
  }
}

function clip_renderGames() {
  var sel = clip_el('clip-game');
  if (!sel) return;
  var h = '<option value="">All games</option>';
  for (var i = 0; i < clip_state.games.length; i++) {
    var g = clip_state.games[i];
    h += '<option value="' + esc(g) + '"' +
         (g === clip_state.game ? ' selected' : '') + '>' + esc(g) + '</option>';
  }
  sel.innerHTML = h;
  sel.parentNode.classList.toggle('hide', clip_state.games.length < 2);
}

/* ----------------------------------------------------------- the options */

/* The highlight types, in the order rounds.py ranks them. Losses are kept
   deliberately: a 1v3 lost at the last moment is often better viewing than a
   1v2 won, so ALMOST sits alongside CLUTCH rather than replacing it. */
/* Every round type that can be chosen between. It has to list everything the
   app can label a round with, because a type missing from here was dropped by
   the filter rather than left alone -- MATCH POINT and PISTOL ROUND never
   reached a clip from this page for exactly that reason. Labels that are a
   DETAIL of a round rather than a type of round -- how a kill happened -- are
   deliberately absent and are never filtered; see rounds.FILTERABLE. */
var CLIP_ROUND_TYPES = [
  {key: 'ACE',      label: 'Ace (5 kills)'},
  {key: 'CLUTCH',   label: '1vN clutch won'},
  {key: 'ALMOST',   label: '1vN nearly won'},
  {key: 'KILLS',    label: '4 kills'},
  {key: 'LAST ALIVE', label: 'Last one alive'},
  {key: 'K IN',     label: 'Quick multi-kill'},
  {key: 'CHAOS',    label: 'Chaotic round'},
  {key: 'SURVIVED', label: 'Survived a loss'},
  {key: 'MATCH POINT', label: 'Match point'},
  {key: 'PISTOL',   label: 'Pistol round'},
  {key: 'STREAK BREAKER', label: 'Broke a losing streak'},
  /* Valorant's own ceremony names, read off the match record. */
  {key: 'FLAWLESS', label: 'Flawless (nobody died)'},
  {key: 'THRIFTY',  label: 'Thrifty (won on worse guns)'},
  {key: 'CLOSER',   label: 'Closed out the match'}
];

function clip_renderTypes() {
  var box = clip_el('clip-types');
  if (!box) return;
  if (!clip_state.types) {
    clip_state.types = CLIP_ROUND_TYPES.map(function (t) { return t.key; });
  }
  box.innerHTML = CLIP_ROUND_TYPES.map(function (t) {
    var on = clip_state.types.indexOf(t.key) >= 0;
    return '<button class="chip' + (on ? ' is-on' : '') + '" type="button" ' +
           'data-type="' + esc(t.key) + '">' + esc(t.label) + '</button>';
  }).join('');
}

function clip_renderOptions() {
  var s = clip_state.pick;
  clip_show('clip-options', !!s);
  if (!s) return;

  clip_el('clip-chosen').textContent = s.game || 'Unknown game';
  var bits = [clip_when(s.display_started || s.started)];
  if (s.duration) bits.push(clip_dur(s.duration));
  if (s.recording_bytes) bits.push(clip_bytes(s.recording_bytes));
  clip_el('clip-chosen-sub').textContent = bits.join('  ·  ');

  clip_segs('clip-style', CLIP_STYLES.map(function (s) { return [s[0], s[1]]; }),
            clip_state.style, 'style');
  var sh = clip_el('clip-style-help');
  if (sh) {
    var row = CLIP_STYLES.filter(function (s) { return s[0] === clip_state.style; })[0];
    sh.textContent = row ? row[2] : '';
  }
  /* A style owns the length, so showing an editable length control beside it
     would imply the two disagree. Only Custom exposes it. */
  var lenField = clip_el('clip-len');
  if (lenField && lenField.parentNode) {
    lenField.parentNode.classList.toggle('hide', clip_state.style !== 'custom');
  }

  var supports = !!(clip_state.pick && clip_state.pick.rounds);
  clip_show('clip-rounds-field', supports);
  var roundMode = supports && clip_state.rounds !== false;
  /* Minimum kills is meaningless for a round clip -- the round decides, not a
     kill count -- so it is hidden rather than left to mislead. */
  clip_show('clip-min-field', !roundMode);
  if (supports) clip_renderTypes();
  clip_segs('clip-min', CLIP_MINS, clip_state.min, 'min');
  clip_segs('clip-len', CLIP_LENS, clip_state.len, 'len');
  clip_segs('clip-vert', CLIP_VERTS, clip_state.vert, 'vert');
  clip_options('clip-trans', CLIP_TRANS, clip_state.trans);
  var ms = clip_el('clip-transms');
  if (ms) ms.value = String(clip_state.transMs);

  var sw = clip_el('clip-montage');
  if (sw) sw.setAttribute('aria-checked', clip_state.montage ? 'true' : 'false');
  [['clip-rounds', clip_state.rounds !== false],
   ['clip-whole', clip_state.whole !== false]].forEach(function (pair) {
    var el = clip_el(pair[0]);
    if (!el) return;
    el.setAttribute('aria-checked', pair[1] ? 'true' : 'false');
    el.classList.toggle('is-on', !!pair[1]);
  });
  var td = clip_el('clip-trans'), tm = clip_el('clip-transms');
  if (td) td.disabled = !clip_state.montage;
  if (tm) tm.disabled = !clip_state.montage || clip_state.trans === 'cut';

  /* Two reasons to offer the game chooser, and they read differently.

     One: the recording predates the session, so the detected game describes a
     minute of a much longer file.

     Two: SEVERAL GAMES were played into one recording. The session is labelled
     with the LAST of them, and a scan only ever reads one game -- so without
     this the other games in the file are silently unreachable, which is what
     happened to a session holding both Counter-Strike 2 and Delta Force. */
  clip_renderDemoBox();

  var played = (s.games || []).filter(function (g) { return !!g; });
  var multi = played.length > 1;
  clip_show('clip-wrongwrap', !!s.game_uncertain || multi);
  if (s.game_uncertain || multi) {
    clip_el('clip-wrongtext').textContent = s.game_uncertain
      ? ('OBS was already recording ' + clip_dur(s.pre_session_seconds) +
         ' before this session started, so most of this file is footage AutoStream ' +
         'never saw. It is labelled ' + (s.game || 'unknown') +
         ' because that is what was running at the end. If that is wrong, correct it here.')
      : ('This session covered ' + played.join(' and ') + '. A scan reads one ' +
         'game at a time, and this file is set to ' + (s.game || 'unknown') +
         ' because that is what you finished on. Pick another to cut its ' +
         'highlights instead.');
    var sel = clip_el('clip-gamefix');
    if (sel) {
      /* The games actually played come first: on a multi-game recording they
         are the only ones that can find anything. */
      var profs = clip_state.profiles || [];
      var first = profs.filter(function (pr) { return played.indexOf(pr.label) >= 0; });
      var rest = profs.filter(function (pr) { return played.indexOf(pr.label) < 0; });
      var opts = first.concat(rest).map(function (pr) {
        var here = played.indexOf(pr.label) >= 0;
        return '<option value="' + esc(pr.key) + '" data-label="' + esc(pr.label) +
               '"' + (pr.label === s.game ? ' selected' : '') + '>' + esc(pr.label) +
               (multi && here ? ' (played this session)' : '') + '</option>';
      }).join('');
      sel.innerHTML = opts || '<option value="">no calibrated games</option>';
    }
  }

  var go = clip_el('clip-go');
  var hint = clip_el('clip-hint');
  var why = '';
  if (!s.has_recording) why = 'The recording for this stream is no longer on disk.';
  else if (!s.can_scan) {
    /* The profile knows exactly what is missing, so say that rather than the
       generic line - the two causes need completely different fixes. */
    why = s.blocked || ('No kill marker is calibrated for ' +
          (s.game || 'this game') + ' yet. Use Calibrate a game first.');
  } else if (clip_state.busy) why = 'A clip job is already running.';

  /* A note is not a reason to disable anything, so it is kept separate from
     `why`. Reading a kill feed runs about 10 frames a second where a template
     match runs thousands, so an hour of footage takes minutes to scan. Better
     said before the button is pressed than discovered afterwards. */
  var note = '';
  if (!why && s.scan_mode === 'killfeed') {
    note = 'Kills for ' + esc(s.game || 'this game') + ' are read out of the ' +
           'kill feed, which is slower than a marker scan - roughly a minute ' +
           'per 10 minutes of footage. Assists are detected and not clipped.';
  }
  if (go) go.disabled = !!why;
  if (hint) hint.textContent = why || note;
}

/* ---------------------------------------------------------- the progress */

function clip_renderJob(j) {
  var running = !!j && (j.state === 'running' || j.state === 'queued');
  clip_state.busy = running;
  clip_show('clip-progress', running);

  if (running) {
    clip_el('clip-prog-title').textContent = 'Making clips from ' + (j.game || 'the stream');
    /* HOW LONG IT HAS RUN AND HOW LONG IS LEFT. A scan of a two-hour
       recording is eight minutes of nothing visible happening, and "Reading
       the feed" does not say whether that means one minute or twenty. */
    var msg = clip_el('clip-prog-msg');
    var cancelBtn = clip_el('clip-progress')
      ? clip_el('clip-progress').querySelector('[data-act="cancel"]') : null;
    if (j.stopping) {
      /* A cancelled job is not a stopped job. The chunks already decoding run
         to their end, which on a long recording is most of a minute -- and
         with the old message still on screen that reads as "it ignored me". */
      clip_state.stopping = true;
      if (cancelBtn) { cancelBtn.disabled = true; cancelBtn.textContent = 'Stopping...'; }
      if (msg) {
        msg.textContent = 'Stopping - anything already decoding finishes first' +
          ' (' + clip_fmtTime(j.stopping_for || 0) + ')';
      }
      clip_el('clip-prog-title').textContent = 'Stopping';
      return;
    }
    if (cancelBtn && cancelBtn.disabled && !clip_state.stopping) {
      cancelBtn.disabled = false;
      cancelBtn.textContent = 'Cancel';
    }
    var run = 'running ' + clip_fmtTime(j.elapsed || 0);
    var eta = (j.eta != null && j.eta > 0)
      ? ' - about ' + clip_fmtTime(j.eta) + ' left'
      : (j.eta === 0 ? ' - nearly done' : '');
    if (msg) msg.textContent = (j.message || '') + '  (' + run + eta + ')';
    var fill = clip_el('clip-fill'), meter = clip_el('clip-meter');
    if (fill) fill.style.width = j.percent + '%';
    if (meter) meter.setAttribute('aria-valuenow', String(j.percent));

    var h = '';
    for (var i = 0; i < CLIP_STEPS.length; i++) {
      var cls = i < j.step_index ? ' is-done' : (i === j.step_index ? ' is-now' : '');
      h += '<span class="clip-step' + cls + '">' + esc(CLIP_STEPS[i][1]) + '</span>';
    }
    var st = clip_el('clip-steps');
    if (st) st.innerHTML = h;
  }

  /* Results stay on screen after the run, so closing and reopening the page
     mid-job still ends with something to click. */
  var done = !!j && (j.state === 'done' || j.state === 'failed' || j.state === 'cancelled');
  if (done && clip_state.stopping) {
    clip_state.stopping = false;
    var cb = clip_el('clip-progress')
      ? clip_el('clip-progress').querySelector('[data-act="cancel"]') : null;
    if (cb) { cb.disabled = false; cb.textContent = 'Cancel'; }
  }
  clip_show('clip-results', done);
  if (!done) return;

  clip_el('clip-res-title').textContent =
    j.state === 'done' ? 'Clips ready' :
    (j.state === 'cancelled' ? 'Cancelled' : 'Could not finish');

  var sum = j.summary || {};
  var sub;
  if (j.state === 'done') {
    sub = j.clips + (j.clips === 1 ? ' clip' : ' clips') +
          (sum.kills ? '  ·  ' + sum.covered + ' of ' + sum.kills +
                       ' kills (' + sum.coverage + '%)' : '') +
          '  ·  ' + (j.folder || '');
  } else {
    sub = j.error || j.message || '';
  }
  clip_el('clip-res-sub').textContent = sub;
  clip_show('clip-res-list', j.state === 'done');
}

function clip_renderResults(list, montagePath) {
  var host = clip_el('clip-res-list');
  if (!host) return;
  var h = '';
  if (montagePath) {
    h += '<div class="clip-res is-montage">' +
         '<span class="clip-res-rank">' + icon('film') + '</span>' +
         '<span class="clip-res-name">Montage</span>' +
         '<span class="clip-res-meta muted">every clip, joined</span>' +
         '<span class="clip-res-acts">' +
         '<button class="btn btn-ghost btn-sm" type="button" data-act="reveal"' +
         ' data-path="' + esc(montagePath) + '">Show</button></span></div>';
  }
  for (var i = 0; i < list.length; i++) {
    var c = list[i];
    /* Only a vertical can be a Short, and only an un-uploaded one is worth
       ticking. A clip with no vertical is still listed -- it just cannot go. */
    var can = !!c.vertical;
    var done = !!c.video_id;
    var on = clip_upWanted(c);
    var label = c.caption ? esc(c.caption)
                          : (esc(String(c.kills)) + (c.kills === 1 ? ' kill' : ' kills'));
    h += '<div class="clip-res' + (done ? ' is-up' : '') + '">' +
      (can && !done
        ? '<input class="clip-res-tick" type="checkbox" data-up="' + i + '"' +
          (on ? ' checked' : '') + ' aria-label="Upload ' + esc(label) + '">'
        : '<span class="clip-res-rank mono">' + esc(String(c.rank)) + '</span>') +
      '<span class="clip-res-name">' + label + '</span>' +
      '<span class="clip-res-meta muted">at ' + esc(c.at) + '  ·  ' +
        Math.round(c.duration) + 's' +
        (done ? '  ·  on YouTube' : (can ? '' : '  ·  no vertical')) + '</span>' +
      '<span class="clip-res-acts">' +
      (done ? '<a class="btn btn-ghost btn-sm" target="_blank" rel="noreferrer noopener"'
              + ' href="' + esc(c.shorts_url || c.url) + '">Watch</a>' : '') +
      '<button class="btn btn-ghost btn-sm" type="button" data-res-play="' + i + '"' +
      '>Play</button>' +
      '<button class="btn btn-ghost btn-sm" type="button" data-act="reveal"' +
      ' data-path="' + esc(c.master) + '">Show</button></span></div>';
  }
  host.innerHTML = h;
  clip_state.results = list;
  clip_state.resultsFolder = (list[0] && (list[0].master || list[0].vertical) || '')
      .replace(/[\\/][^\\/]*[\\/][^\\/]*$/, '');
  clip_renderUpload();
}

/* Ticked by default where the clip earned a caption: those are the ones with
   something to say. The rest are available, not chosen. */
function clip_upWanted(c) {
  if (!c.vertical || c.video_id) return false;
  if (clip_state.upPicked && Object.prototype.hasOwnProperty.call(
        clip_state.upPicked, String(c.rank))) {
    return !!clip_state.upPicked[String(c.rank)];
  }
  return !!c.caption;
}

function clip_upSelection() {
  var out = [];
  var list = clip_state.results || [];
  for (var i = 0; i < list.length; i++) {
    if (clip_upWanted(list[i])) out.push(list[i]);
  }
  return out;
}

function clip_renderUpload() {
  var box = clip_el('clip-up');
  if (!box) return;
  /* Hidden entirely when there is nothing to publish TO -- a clips-only
     install has no YouTube, and offering an upload button there is a lie. */
  var possible = !!clip_state.canUpload &&
                 (clip_state.results || []).some(function (c) { return !!c.vertical; });
  box.classList.toggle('hide', !possible);
  if (!possible) return;

  var t = clip_el('clip-up-title');
  if (t && !t.value) t.value = clip_state.upTitle || '{caption} - {game}';
  var pv = clip_el('clip-up-privacy');
  if (pv && clip_state.upPrivacy) pv.value = clip_state.upPrivacy;

  var n = clip_upSelection().length;
  var go = clip_el('clip-up-go');
  if (go) {
    go.disabled = !n || clip_state.upBusy;
    go.innerHTML = '<span>Upload' + (n ? ' ' + n + ' clip' + (n === 1 ? '' : 's') : '') +
                   '</span>';
  }
  var note = clip_el('clip-up-note');
  if (note) {
    var cap = clip_state.upDailyMax || 0;
    note.textContent = !n
      ? 'Tick the clips you want on your channel.'
      : (n > cap
          ? n + ' selected, but the limit is ' + cap + ' a day. Raise it in Settings.'
          : n + ' of ' + cap + ' uploads left today. They go out ' +
            (clip_el('clip-up-privacy') || {}).value + '.');
  }
}

/* -------------------------------------------------------------- actions */

async function clip_load() {
  try {
    var r = await API.get('/api/clips/sessions');
    if (r && r.error) { toast(r.error, 'error'); return; }
    clip_state.sessions = (r && r.sessions) || [];
    clip_state.profiles = (r && r.profiles) || [];
    clip_state.status = (r && r.status) || null;
    clip_state.games = (r && r.games) || [];
    clip_state.outputDir = (r && r.output_dir) || '';
    clip_state.canUpload = !!(r && r.can_upload);
    clip_state.upDailyMax = (r && r.upload_daily_max) || 0;
    clip_state.upPrivacy = (r && r.upload_privacy) || 'unlisted';
    clip_state.upTitle = (r && r.upload_title) || '';
    var lj = (r && r.last_job) || null;
    if (lj) {
      clip_state.upGame = lj.game || '';
      /* The folder holding clips.json, taken off a clip path rather than
         guessed: output_dir moves, and the ids have to be written back into
         the run they came from. */
      var any = (lj.clips || [])[0];
      var mp = any && (any.master || any.vertical);
      if (mp) clip_state.upFolder = mp.replace(/[\/][^\/]+[\/][^\/]+$/, '');
    }
    clip_state.loaded = true;

    var d = (r && r.defaults) || {};
    if (d['clips.style']) clip_state.style = String(d['clips.style']);
    if (d['clips.min_kills']) clip_state.min = String(d['clips.min_kills']);
    if (d['clips.clip_seconds']) clip_state.len = String(d['clips.clip_seconds']);
    if (d['clips.vertical_mode']) clip_state.vert = String(d['clips.vertical_mode']);
    if (d['clips.transition']) clip_state.trans = String(d['clips.transition']);
    if (d['clips.transition_ms']) clip_state.transMs = Number(d['clips.transition_ms']);

    var ok = !clip_state.status || clip_state.status.ok;
    clip_show('clip-setup', !ok);
    if (!ok) {
      clip_el('clip-setup-text').textContent =
        'The Clips page needs ' + clip_state.status.missing.join(' and ') +
        '. Everything else in AutoStream works without it.';
      clip_el('clip-setup-detail').textContent = clip_state.status.detail || '';
    }

    /* Keep the selection across a refresh if that stream is still listed. */
    if (clip_state.pick) {
      var want = clip_state.pick.recording_path;
      clip_state.pick = clip_state.sessions.filter(function (s) {
        return s.recording_path === want;
      })[0] || null;
    }
    if (!clip_state.pick) {
      clip_state.pick = clip_state.sessions.filter(function (s) {
        return s.has_recording;
      })[0] || null;
    }
    clip_renderGames();
    clip_renderList();
    clip_renderOptions();
    clip_loadMade(clip_state.pick);
  } catch (e) {
    toast('Could not read the stream history.', 'error');
  }
}

/* --------------------------------------------------------------- the player

   A clip is a video, and the only honest way to decide whether it is any good
   is to watch it. Explorer could do that, but not while showing the caption
   that is burned into it, the line it says, and the controls to change either.

   The controls are the ones a media player has, because that is what people
   already know how to use: play, seek, volume, speed, next, fullscreen, and
   the same keys VLC uses. Everything else on the panel is about the clip
   rather than about playing it. */

function clip_fmtTime(t) {
  if (!isFinite(t) || t < 0) t = 0;
  var m = Math.floor(t / 60), sec = Math.floor(t % 60);
  return m + ':' + (sec < 10 ? '0' : '') + sec;
}

function clip_videoURL(path) {
  return '/api/clips/video?k=' + encodeURIComponent(SHELL_K) +
         '&path=' + encodeURIComponent(path) +
         /* Defeats the cache after a re-render writes the same filename. */
         '&v=' + Date.now();
}

function clip_openPlayer(list, i, folder) {
  var playable = (list || []).filter(function (c) { return c.vertical || c.master; });
  if (!playable.length) { toast('Nothing to play in that run.', 'error'); return; }
  clip_state.player = {
    list: playable, i: Math.max(0, Math.min(i || 0, playable.length - 1)),
    folder: folder || '', trim: {in: null, out: null}
  };
  clip_show('clip-player-card', true);
  /* Not awaited: the panel draws now and the chooser fills itself in when the
     voices land -- see clip_fillVoiceSelects. */
  clip_loadVoices();
  clip_playerLoad();
  var card = clip_el('clip-player-card');
  if (card && card.scrollIntoView) {
    card.scrollIntoView({behavior: 'smooth', block: 'start'});
  }
}

function clip_playerClip() {
  var p = clip_state.player;
  return p ? p.list[p.i] : null;
}

function clip_playerLoad() {
  var p = clip_state.player, c = clip_playerClip();
  if (!p || !c) return;
  p.trim = {in: null, out: null};
  var v = clip_el('clip-video');
  var path = c.vertical || c.master;
  if (v) {
    v.src = clip_videoURL(path);
    v.load();
    var sp = clip_el('clip-play-speed');
    v.playbackRate = sp ? Number(sp.value) : 1;
    var vol = clip_el('clip-play-vol');
    if (vol) v.volume = Number(vol.value) / 100;
    v.play().catch(function () { /* autoplay refused; the button works */ });
  }
  clip_el('clip-play-title').textContent =
    (c.caption || (c.kills + ' kill' + (c.kills === 1 ? '' : 's')));
  clip_el('clip-play-sub').textContent =
    'clip ' + (p.i + 1) + ' of ' + p.list.length +
    (c.vertical ? '' : ' - no vertical, showing the 16:9 master');
  clip_playerMeta();
  clip_playerForm();
  clip_playerTrimText();
}

function clip_playerMeta() {
  var c = clip_playerClip();
  var host = clip_el('clip-play-meta');
  if (!c || !host) return;
  var path = c.vertical || c.master || '';
  var rows = [
    ['Found at', c.at || '-'],
    ['Length', Math.round(c.duration || 0) + 's'],
    ['Kills', String(c.kills == null ? '-' : c.kills)],
    ['Caption', c.caption || 'none'],
    ['Says', c.said || 'nothing'],
    ['File', path.split('\\').pop().split('/').pop()]
  ];
  if (c.video_id) rows.push(['On YouTube', 'yes']);
  host.innerHTML = rows.map(function (r) {
    return '<dt>' + esc(r[0]) + '</dt><dd>' + esc(String(r[1])) + '</dd>';
  }).join('');
}

function clip_playerForm() {
  var c = clip_playerClip();
  if (!c) return;
  var cap = clip_el('clip-play-cap'), say = clip_el('clip-play-say');
  if (cap) cap.value = c.caption || '';
  if (say) say.value = c.said || '';
  clip_switch('clip-play-capsw', !!c.caption);
  clip_switch('clip-play-saysw', !!c.said);
  var sel = clip_el('clip-play-voice');
  if (sel) sel.innerHTML = clip_voiceOptions('');
  var mode = (c.vertical_mode || 'crop');
  var seg = clip_el('clip-play-vert');
  if (seg) {
    var btns = seg.querySelectorAll('[data-vert]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle('is-on',
        btns[i].getAttribute('data-vert') === mode);
    }
  }
}

function clip_switch(id, on) {
  var el = clip_el(id);
  if (!el) return;
  el.classList.toggle('is-on', !!on);
  el.setAttribute('aria-checked', on ? 'true' : 'false');
}

function clip_switchOn(id) {
  var el = clip_el(id);
  return !!(el && el.classList.contains('is-on'));
}

function clip_playerTrimText() {
  var p = clip_state.player;
  var el = clip_el('clip-play-trim');
  if (!p || !el) return;
  var v = clip_el('clip-video');
  var dur = v && isFinite(v.duration) ? v.duration : 0;
  if (p.trim.in == null && p.trim.out == null) {
    el.textContent = 'whole clip';
    return;
  }
  var a = p.trim.in == null ? 0 : p.trim.in;
  var b = p.trim.out == null ? dur : p.trim.out;
  el.textContent = clip_fmtTime(a) + ' to ' + clip_fmtTime(b) +
                   '  (' + Math.max(0, Math.round(b - a)) + 's)';
}

function clip_playerStep(by) {
  var p = clip_state.player;
  if (!p) return;
  var next = p.i + by;
  if (next < 0 || next >= p.list.length) return;
  p.i = next;
  clip_playerLoad();
}

function clip_playerToggle() {
  var v = clip_el('clip-video');
  if (!v) return;
  if (v.paused) v.play().catch(function () {}); else v.pause();
}

function clip_playerTick() {
  var v = clip_el('clip-video');
  if (!v) return;
  var t = clip_el('clip-play-time'), seek = clip_el('clip-play-seek');
  var dur = isFinite(v.duration) ? v.duration : 0;
  if (t) t.textContent = clip_fmtTime(v.currentTime) + ' / ' + clip_fmtTime(dur);
  if (seek && !seek.dataset.dragging && dur) {
    seek.value = String(Math.round(1000 * v.currentTime / dur));
  }
  var btn = clip_el('clip-play-toggle');
  if (btn) btn.innerHTML = v.paused ? '&#9654;' : '&#10074;&#10074;';
}

async function clip_playerApply() {
  var p = clip_state.player, c = clip_playerClip();
  if (!p || !c) return;
  if (clip_state.editing) { toast('Already re-rendering a clip.', 'error'); return; }
  var folder = p.folder;
  var name = (c.master || c.vertical || '').split('\\').pop().split('/').pop()
               .replace(/_vertical\.mp4$/, '').replace(/\.mp4$/, '');
  if (!folder || !name) { toast('That clip cannot be edited.', 'error'); return; }
  var seg = clip_el('clip-play-vert');
  var on = seg ? seg.querySelector('.is-on') : null;
  var body = {
    folder: folder, name: name,
    caption: clip_switchOn('clip-play-capsw'),
    caption_text: (clip_el('clip-play-cap') || {}).value || '',
    voice: clip_switchOn('clip-play-saysw'),
    voice_text: (clip_el('clip-play-say') || {}).value || '',
    voice_name: (clip_el('clip-play-voice') || {}).value || '',
    vertical_mode: on ? on.getAttribute('data-vert') : ''
  };
  if (p.trim.in != null) body.trim_start = p.trim.in;
  if (p.trim.out != null) body.trim_end = p.trim.out;
  var btn = clip_el('clip-play-apply');
  if (btn) btn.disabled = true;
  clip_state.editing = true;
  var msg = clip_el('clip-play-editmsg');
  if (msg) msg.textContent = 'Re-rendering...';
  try {
    var r = await API.post('/api/clips/edit', body);
    if (r && r.error) {
      toast(r.error, 'error');
      clip_state.editing = false;
      if (btn) btn.disabled = false;
      if (msg) msg.textContent = '';
    }
  } catch (e) {
    toast('Could not start the re-render.', 'error');
    clip_state.editing = false;
    if (btn) btn.disabled = false;
  }
}

/* The re-render rides the same status poll as everything else. */
function clip_renderEdit(ed) {
  if (!ed) return;
  var msg = clip_el('clip-play-editmsg'), btn = clip_el('clip-play-apply');
  if (ed.state === 'running') {
    clip_state.editing = true;
    if (btn) btn.disabled = true;
    if (msg) msg.textContent = 'Re-rendering ' + (ed.name || 'the clip') +
                               ' - ' + ed.elapsed + 's';
    return;
  }
  if (!clip_state.editing) return;      /* nothing of ours in flight */
  clip_state.editing = false;
  if (btn) btn.disabled = false;
  if (msg) msg.textContent = '';
  if (ed.state === 'failed') {
    toast(ed.error || 'Could not re-render that clip.', 'error');
    return;
  }
  if (ed.state === 'done') {
    var c = clip_playerClip();
    var res = ed.result || {};
    if (c) {
      if (res.caption !== undefined) c.caption = res.caption;
      if (res.said !== undefined) c.said = res.said;
      if (res.duration) c.duration = res.duration;
      if (res.vertical) c.vertical = res.vertical;
      if (res.master) c.master = res.master;
      var seg = clip_el('clip-play-vert');
      var on = seg ? seg.querySelector('.is-on') : null;
      if (on) c.vertical_mode = on.getAttribute('data-vert');
    }
    toast('Clip re-rendered.', 'ok');
    clip_playerLoad();                  /* reload so the new file is shown */
  }
}

/* ------------------------------------------------- clips a run already made */

async function clip_loadMade(s) {
  if (!s || !s.made_folder || !s.made_clips) {
    clip_state.made = null;
    clip_show('clip-made-card', false);
    return;
  }
  try {
    var r = await API.get('/api/clips/existing?folder=' +
                          encodeURIComponent(s.made_folder));
    if (!r || r.error || !(r.clips || []).length) {
      clip_state.made = null;
      clip_show('clip-made-card', false);
      return;
    }
    clip_state.made = r;
    clip_renderMade();
  } catch (e) {
    clip_state.made = null;
    clip_show('clip-made-card', false);
  }
}

function clip_renderMade() {
  var m = clip_state.made;
  if (!m) { clip_show('clip-made-card', false); return; }
  var when = m.when ? new Date(m.when * 1000) : null;
  var sub = clip_el('clip-made-sub');
  if (sub) {
    sub.textContent = m.clips.length + ' clip' + (m.clips.length === 1 ? '' : 's') +
      ' from ' + (m.folder || '').split('\\').pop().split('/').pop() +
      (when ? ', cut ' + when.toLocaleString() : '') +
      '. Watch them before cutting again - a re-cut of a long recording costs minutes.';
  }
  var host = clip_el('clip-made-list');
  if (host) {
    host.innerHTML = m.clips.map(function (c, i) {
      var label = c.caption || ((c.kills || 0) + ' kill' + (c.kills === 1 ? '' : 's'));
      return '<div class="clip-made-row">' +
        '<span class="clip-made-name">' + esc(label) + '</span>' +
        '<span class="muted">' + esc(c.at || '') + '  &middot;  ' +
          Math.round(c.duration || 0) + 's' +
          (c.said ? '  &middot;  says "' + esc(c.said) + '"' : '') + '</span>' +
        '<button class="btn btn-sm" type="button" data-made="' + i + '">Play</button>' +
        '</div>';
    }).join('');
  }
  clip_show('clip-made-card', true);
}

/* ------------------------------------------------- reviewing the clips

   Nothing is encoded until the plan has been seen, and the same plan is then
   cut -- which is what makes the review worth anything. It is not a guess at
   what the run would do, it IS what the run decided. */

async function clip_preview() {
  var s = clip_state.pick;
  if (!s) return;
  var b = clip_el('clip-review');
  if (b) b.disabled = true;
  try {
    var r = await API.post('/api/clips/preview', clip_runBody(s));
    if (r && r.error) { toast(r.error, 'error'); if (b) b.disabled = false; return; }
    clip_state.reviewing = true;
    clip_state.busy = true;
    clip_show('clip-results', false);
    toast(r && r.reused_kills
      ? 'Working out the clips from the kills found earlier.'
      : 'Scanning the recording. Nothing is encoded yet.', 'ok');
  } catch (e) {
    toast('Could not start the review.', 'error');
    if (b) b.disabled = false;
  }
}

function clip_openReview(j) {
  var s = clip_state.pick || {};
  var rows = (j.preview || []).map(function (row) {
    return {
      key: row.key, name: row.name, start: row.start, end: row.end,
      duration: row.duration, kills: row.kills, labels: row.labels || [],
      thumb_at: row.thumb_at,
      caption_on: true, caption_text: row.caption || '',
      caption_default: row.caption || '',
      voice_on: false, voice_text: row.voice_line || '',
      voice_default: row.voice_line || '', voice_name: ''
    };
  });
  clip_state.review = {
    folder: j.folder || '',
    source: s.recording_path || s.source || '',
    rows: rows
  };
  clip_show('clip-review-card', true);
  clip_show('clip-results', false);
  clip_loadVoices();
  clip_renderReview();
  var card = clip_el('clip-review-card');
  if (card && card.scrollIntoView) {
    card.scrollIntoView({behavior: 'smooth', block: 'start'});
  }
}

function clip_frameURL(path, at) {
  return '/api/clips/frame?k=' + encodeURIComponent(SHELL_K) +
         '&path=' + encodeURIComponent(path) + '&t=' + encodeURIComponent(at);
}

function clip_reviewRowHTML(r, i) {
  var mins = Math.floor(r.start / 60), secs = Math.round(r.start % 60);
  var at = mins + 'm' + (secs < 10 ? '0' : '') + secs + 's';
  var kills = r.kills + ' kill' + (r.kills === 1 ? '' : 's');
  var off = ' disabled';
  return '' +
    '<div class="clip-review-row" data-i="' + i + '">' +
      '<img class="clip-review-thumb" alt="" loading="lazy" src="' +
          esc(clip_frameURL(clip_state.review.source, r.thumb_at)) + '">' +
      '<div class="clip-review-body">' +
        '<div class="clip-review-head">' +
          '<strong>' + esc(r.labels[0] || kills) + '</strong>' +
          '<span class="muted">' + esc(at) + ' &middot; ' +
            Math.round(r.duration) + 's &middot; ' + esc(kills) + '</span>' +
        '</div>' +
        '<div class="clip-review-field">' +
          '<button class="switch' + (r.caption_on ? ' is-on' : '') + '" type="button"' +
            ' role="switch" data-rev="caption" data-i="' + i + '"' +
            ' aria-checked="' + (r.caption_on ? 'true' : 'false') + '"' +
            ' aria-label="Burn a caption on this clip">' +
            '<span class="switch-dot"></span></button>' +
          '<label class="field-label">Caption</label>' +
          '<input class="input" type="text" data-rev="caption_text" data-i="' + i + '"' +
            ' placeholder="' + esc(r.caption_default || 'no caption') + '"' +
            ' value="' + esc(r.caption_text) + '"' +
            (r.caption_on ? '' : off) + '>' +
        '</div>' +
        '<div class="clip-review-field">' +
          '<button class="switch' + (r.voice_on ? ' is-on' : '') + '" type="button"' +
            ' role="switch" data-rev="voice" data-i="' + i + '"' +
            ' aria-checked="' + (r.voice_on ? 'true' : 'false') + '"' +
            ' aria-label="Speak a line over this clip">' +
            '<span class="switch-dot"></span></button>' +
          '<label class="field-label">Spoken</label>' +
          '<input class="input" type="text" data-rev="voice_text" data-i="' + i + '"' +
            ' placeholder="' + esc(r.voice_default || 'nothing to say') + '"' +
            ' value="' + esc(r.voice_text) + '"' +
            (r.voice_on ? '' : off) + '>' +
          '<select class="select clip-review-voice" data-rev="voice_name"' +
            ' data-i="' + i + '" aria-label="Voice for this clip"' +
            (r.voice_on ? '' : off) + '></select>' +
          '<button class="btn btn-sm" type="button" data-rev="play" data-i="' + i + '"' +
            (r.voice_on ? '' : off) + '>Hear it</button>' +
        '</div>' +
      '</div>' +
    '</div>';
}

function clip_renderReview() {
  var rv = clip_state.review;
  if (!rv) return;
  var sub = clip_el('clip-review-sub');
  if (sub) {
    var caps = rv.rows.filter(function (r) { return r.caption_on; }).length;
    var says = rv.rows.filter(function (r) { return r.voice_on; }).length;
    sub.textContent = rv.rows.length + ' clip' + (rv.rows.length === 1 ? '' : 's') +
      ', ' + caps + ' with a caption and ' + says + ' with a spoken line. ' +
      'Nothing has been encoded yet.';
  }
  var host = clip_el('clip-review-list');
  if (!host) return;
  host.innerHTML = rv.rows.map(clip_reviewRowHTML).join('') ||
    '<p class="muted">Nothing was found to cut.</p>';
  clip_fillVoiceSelects();
}

function clip_voiceOptions(chosen) {
  var v = clip_state.voices;
  if (!v || !v.available) return '<option value="">no voices installed</option>';
  var html = '<option value="">' + esc(v.default) + ' (default)</option>';
  Object.keys(v.groups).forEach(function (label) {
    html += '<optgroup label="' + esc(label) + '">';
    v.groups[label].forEach(function (name) {
      html += '<option value="' + esc(name) + '"' +
              (name === chosen ? ' selected' : '') + '>' + esc(name) + '</option>';
    });
    html += '</optgroup>';
  });
  return html;
}

function clip_fillVoiceSelects() {
  var rv = clip_state.review;
  var all = clip_el('clip-review-voice-all');
  if (all && !all.getAttribute('data-filled')) {
    all.innerHTML = clip_voiceOptions('');
    all.setAttribute('data-filled', '1');
  }
  var why = clip_el('clip-review-voicewhy');
  if (why) {
    why.textContent = (clip_state.voices && !clip_state.voices.available)
      ? (clip_state.voices.why || '') : '';
  }
  /* The player's own chooser. Filling the voices is a fetch, so the panel is
     built before they arrive -- and this is what comes back to fill it in.
     Without it the player said "no voices installed" with 28 of them loaded. */
  var pv = clip_el('clip-play-voice');
  if (pv) {
    var keep = pv.value;
    pv.innerHTML = clip_voiceOptions(keep);
    if (keep) pv.value = keep;
  }
  if (!rv) return;
  var sels = document.querySelectorAll('.clip-review-voice');
  for (var i = 0; i < sels.length; i++) {
    var idx = Number(sels[i].getAttribute('data-i'));
    var row = rv.rows[idx];
    sels[i].innerHTML = clip_voiceOptions(row ? row.voice_name : '');
  }
}

async function clip_loadVoices() {
  if (clip_state.voices) { clip_fillVoiceSelects(); return; }
  try {
    var r = await API.get('/api/clips/voices');
    if (r && !r.error) { clip_state.voices = r; clip_fillVoiceSelects(); }
  } catch (e) { /* the selects just say so */ }
}

function clip_playVoice(name, line) {
  var v = clip_state.voices;
  if (v && !v.available) {
    toast(v.why || 'No voice model is installed.', 'error');
    return;
  }
  var url = '/api/clips/voice_sample?k=' + encodeURIComponent(SHELL_K) +
            '&name=' + encodeURIComponent(name || (v ? v.default : '')) +
            '&line=' + encodeURIComponent(line || '');
  if (!clip_state.audio) clip_state.audio = new Audio();
  var a = clip_state.audio;
  a.pause();
  a.src = url;
  a.play().catch(function () { toast('Could not play the sample.', 'error'); });
}

/* One handler for the whole list: the rows are rebuilt on every change, so a
   listener per control would have to be rebound each time. */
function clip_reviewClick(ev) {
  var el = ev.target.closest ? ev.target.closest('[data-rev]') : null;
  if (!el) return;
  var rv = clip_state.review;
  if (!rv) return;
  var what = el.getAttribute('data-rev');
  var i = Number(el.getAttribute('data-i'));
  var row = rv.rows[i];
  if (!row) return;
  if (what === 'caption' || what === 'voice') {
    ev.preventDefault();
    row[what + '_on'] = !row[what + '_on'];
    clip_renderReview();
  } else if (what === 'play') {
    ev.preventDefault();
    clip_playVoice(row.voice_name, row.voice_text || row.voice_default);
  }
}

function clip_reviewInput(ev) {
  var el = ev.target;
  if (!el || !el.getAttribute) return;
  var what = el.getAttribute('data-rev');
  if (what !== 'caption_text' && what !== 'voice_text' && what !== 'voice_name') return;
  var rv = clip_state.review;
  if (!rv) return;
  var row = rv.rows[Number(el.getAttribute('data-i'))];
  if (row) row[what] = el.value;
}

async function clip_reviewCut() {
  var rv = clip_state.review, s = clip_state.pick;
  if (!rv || !s) return;
  var b = clip_el('clip-review-cut');
  if (b) b.disabled = true;
  var per = {};
  rv.rows.forEach(function (r) {
    per[r.key] = {
      caption: !!r.caption_on,
      caption_text: r.caption_on ? (r.caption_text || '') : '',
      voice: !!r.voice_on,
      voice_text: r.voice_on ? (r.voice_text || '') : '',
      voice_name: r.voice_on ? (r.voice_name || '') : ''
    };
  });
  var body = clip_runBody(s);
  body.per_clip = per;
  /* The pass only runs at all if something wants it; the per-clip switches
     then decide which clips actually get one. */
  body.voice = rv.rows.some(function (r) { return r.voice_on; });
  body.captions = rv.rows.some(function (r) { return r.caption_on; });
  try {
    var r = await API.post('/api/clips/run', body);
    if (r && r.error) { toast(r.error, 'error'); if (b) b.disabled = false; return; }
    clip_state.busy = true;
    clip_state.review = null;
    clip_show('clip-review-card', false);
    toast('Cutting the clips you reviewed.', 'ok');
  } catch (e) {
    toast('Could not start cutting.', 'error');
    if (b) b.disabled = false;
  }
}

function clip_runBody(s) {
  return {
    /* `source` wins server-side. A file the user picked is not in the
       history, so there is no row to look it up by. */
    source: s.source || '',
    recording_path: s.recording_path,
    game: s.game, game_key: s.game_key,
    style: clip_state.style,
    min_kills: Number(clip_state.min),
    clip_seconds: clip_state.len,
    vertical_mode: clip_state.vert,
    montage: clip_state.montage,
    transition: clip_state.trans,
    transition_ms: clip_state.transMs,
    rounds: clip_state.rounds !== false,
    whole_round: clip_state.whole !== false,
    round_types: clip_state.types || null
  };
}

async function clip_run() {
  var s = clip_state.pick;
  if (!s) return;
  var go = clip_el('clip-go');
  if (go) go.disabled = true;
  try {
    var r = await API.post('/api/clips/run', clip_runBody(s));
    if (r && r.error) { toast(r.error, 'error'); if (go) go.disabled = false; return; }
    clip_state.busy = true;
    clip_show('clip-results', false);
    toast(r && r.reused_kills
      ? 'Re-cutting with the kills found earlier.'
      : 'Scanning the recording for kills.', 'ok');
  } catch (e) {
    toast('Could not start.', 'error');
    if (go) go.disabled = false;
  }
}

/* ------------------------------------------------- a file the user picked */

/* The whole clips-only path: somebody with a recording and no interest in
   streaming should not have to have made that recording with AutoStream. The
   picked file becomes an ordinary `pick`, so every option below it -- style,
   length, rounds, montage -- works exactly as it does for a stream, rather
   than growing a second, poorer copy of the same form. */
async function clip_loadGames() {
  try {
    var r = await API.get('/api/clips/games');
    clip_state.localGames = (r && r.games) || [];
  } catch (e) { clip_state.localGames = []; }
  clip_fillLocalGames();
  clip_renderNamePrompt();
}

function clip_fillLocalGames() {
  var sel = clip_el('clip-local-game');
  if (!sel) return;
  sel.innerHTML = clip_state.localGames.map(function (g) {
    /* A killfeed game is blocked by a missing NAME, not a missing template.
       Calling that "needs calibrating" sends people off to draw a box that was
       never the problem. */
    var tail = g.can_scan ? '' : (g.needs_name ? ' (needs your in-game name)'
                                               : ' (needs calibrating)');
    return '<option value="' + esc(g.game_key) + '">' + esc(g.game) + tail +
           '</option>';
  }).join('') || '<option value="">No games available</option>';
}

function clip_localGame() {
  var sel = clip_el('clip-local-game');
  if (!sel || !sel.value) return null;
  for (var i = 0; i < clip_state.localGames.length; i++) {
    if (clip_state.localGames[i].game_key === sel.value) return clip_state.localGames[i];
  }
  return null;
}

/* Asked here rather than in the calibrator: the calibrator is for drawing a
   box, and the setup wizard -- the only other writer -- lists Steam and Epic
   games only, so a game that arrives as a shortcut could never be given a name
   at all. A clips-only user may open neither. */
function clip_renderNamePrompt() {
  var g = clip_localGame();
  var wrap = clip_el('clip-local-namewrap');
  if (!wrap) return;
  var need = !!(g && g.needs_name);
  wrap.classList.toggle('hide', !need);
  if (!need) return;
  var why = clip_el('clip-local-namewhy');
  if (why) {
    why.textContent = g.game + ' finds your highlights by reading your name in ' +
      'the kill feed, so it needs to know what to look for. Type it exactly as ' +
      'the feed shows it.';
  }
  var box = clip_el('clip-local-name');
  if (box && !box.value) box.value = g.player || '';
}

async function clip_saveName() {
  var g = clip_localGame();
  var box = clip_el('clip-local-name');
  if (!g || !box) return;
  var name = String(box.value || '').trim();
  if (!name) { toast('Type the name first.', 'warn'); return; }
  var r = await API.post('/api/clips/setname',
                         {game_key: g.game_key, name: name, label: g.game});
  if (r && r.error) { toast(r.error, 'error'); return; }
  clip_state.localGames = (r && r.games) || clip_state.localGames;
  clip_renderGamesLocal();
  toast('Saved. ' + g.game + ' can be scanned now.', 'ok');
}

/* Redraws the select in place, keeping the chosen game. */
function clip_renderGamesLocal() {
  var sel = clip_el('clip-local-game');
  var keep = sel ? sel.value : '';
  clip_fillLocalGames();
  if (sel && keep) sel.value = keep;
  clip_renderNamePrompt();
}

async function clip_pickLocal() {
  var r;
  try {
    r = await API.post('/api/clips/pick', {});
  } catch (e) { toast('Could not open the file picker.', 'error'); return; }
  if (r && r.error) { toast(r.error, 'error'); return; }
  if (!r || !r.path) return;                 /* cancelled */
  clip_state.localFile = r;
  var lbl = clip_el('clip-local-path');
  if (lbl) lbl.textContent = r.name + '  ' + (r.size_mb ? r.size_mb + ' MB' : '');
  var go = clip_el('clip-local-go');
  if (go) go.disabled = false;
}

function clip_useLocal() {
  var f = clip_state.localFile;
  var sel = clip_el('clip-local-game');
  if (!f || !sel || !sel.value) {
    toast('Choose a video and a game first.', 'warn');
    return;
  }
  var g = null;
  for (var i = 0; i < clip_state.localGames.length; i++) {
    if (clip_state.localGames[i].game_key === sel.value) g = clip_state.localGames[i];
  }
  if (!g) return;
  /* Shaped like a history row so clip_renderOptions needs no special case.
     `source` is what marks it as not-from-history. */
  clip_state.pick = {
    source: f.path, recording_path: f.path,
    game: g.game, game_key: g.game_key, profile: g.profile,
    can_scan: g.can_scan, scan_mode: g.scan_mode, rounds: g.rounds,
    counts_assists: g.counts_assists, blocked: g.blocked, player: g.player,
    started: null, display_started: null, local: true
  };
  clip_renderList();
  clip_renderOptions();
  var card = clip_el('clip-options');
  if (card && card.scrollIntoView) card.scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function clip_upload() {
  var picked = clip_upSelection();
  if (!picked.length) { toast('Tick a clip first.', 'warn'); return; }
  var body = {
    clips: picked.map(function (c) {
      /* The VERTICAL is the Short. The master is 16:9 and would land as an
         ordinary video. */
      return {path: c.vertical, caption: c.caption || '', kills: c.kills,
              at: c.at, video_id: c.video_id || ''};
    }),
    folder: clip_state.upFolder || '',
    game: clip_state.upGame || '',
    privacy: (clip_el('clip-up-privacy') || {}).value || 'unlisted',
    title: (clip_el('clip-up-title') || {}).value || ''
  };
  var r = await API.post('/api/clips/upload', body);
  if (r && r.error) { toast(r.error, 'error'); return; }
  clip_state.upBusy = true;
  clip_renderUpload();
  toast('Uploading ' + picked.length + ' clip' + (picked.length === 1 ? '' : 's') +
        '.', 'ok');
}

/* Progress rides the same two-second status poll everything else uses, so it
   survives a reload and keeps working if the page is closed mid-upload. */
function clip_renderUploadJob(u) {
  var meter = clip_el('clip-up-meter');
  var stop = clip_el('clip-up-stop');
  var note = clip_el('clip-up-note');
  var running = !!u && (u.state === 'running' || u.state === 'queued');
  clip_state.upBusy = running;
  if (meter) meter.classList.toggle('hide', !running);
  if (stop) stop.classList.toggle('hide', !running);
  var fill = clip_el('clip-up-fill');
  if (fill && u) fill.style.width = Math.max(0, Math.min(100, u.percent || 0)) + '%';
  if (running && note) {
    note.textContent = (u.message || 'Uploading') + '  ·  ' +
      (u.done || 0) + ' of ' + (u.total || 0);
    return;
  }
  if (!u || u.state === 'queued') return;
  if (u.state === 'failed' && clip_state.upLast !== 'failed') {
    toast(u.error || 'Upload failed.', 'error');
  } else if (u.state === 'done' && clip_state.upLast !== 'done') {
    toast(u.message || 'Uploaded.', 'ok');
    if ((u.failed || []).length) {
      toast((u.failed || []).length + ' clip(s) were skipped - see the list.', 'warn');
    }
    clip_state.upPicked = {};        /* the ids are on disk now; re-read them */
    clip_load();
  }
  clip_state.upLast = u.state;
  clip_renderUpload();
}

/* Counter-Strike will download a match when handed its sharing code through a
   steam:// link, and that link asks the user's OWN client to do it -- so this
   needs no Steam credentials, no API key and no game-coordinator protocol, and
   AutoStream never downloads anything itself.

   Several at once because a live session routinely covers more than one match,
   and pasting them one at a time would be the tedious way to say the same
   thing. */
function clip_renderDemoBox() {
  var s = clip_state.pick;
  var wrap = clip_el('clip-demowrap');
  if (!wrap) return;
  /* Only where a demo would help and there is not already one: the panel is an
     answer to "this will be slow", not a permanent fixture. */
  var want = !!s && s.demo_state && s.demo_state !== 'have';
  wrap.classList.toggle('hide', !want);
  if (!want) return;
  var t = clip_el('clip-demotext');
  if (t) {
    t.textContent = s.demo_state === 'listed'
      ? 'This match is in your Counter-Strike history but the demo has not '
        + 'finished downloading. Paste its sharing code and AutoStream will ask '
        + 'the game to fetch it again.'
      : 'No demo for this recording. With one it is read in about twelve '
        + 'minutes instead of in full, and the clips carry real round context. '
        + 'Copy the sharing code from the match in Counter-Strike and paste it '
        + 'here.';
  }
}

async function clip_getDemos() {
  var box = clip_el('clip-democodes');
  var text = box ? String(box.value || '').trim() : '';
  if (!text) { toast('Paste a sharing code first.', 'warn'); return; }
  clip_say('clip-demomsg', 'Asking Counter-Strike...');
  var r = await API.post('/api/clips/demos', {text: text});
  if (r && r.error) { clip_say('clip-demomsg', ''); toast(r.error, 'error'); return; }
  clip_say('clip-demomsg', r.hint || '');
  toast('Counter-Strike is downloading ' + r.sent + ' match'
        + (r.sent === 1 ? '' : 'es') + '.', 'ok');
}

function clip_say(id, text) {
  var el = clip_el(id);
  if (el) el.textContent = text || '';
}

function clip_profileFor(key) {
  var list = clip_state.profiles || [];
  for (var i = 0; i < list.length; i++) {
    if (list[i].key === key) return list[i];
  }
  return null;
}

function clip_useGameLocally(key, label) {
  /* WHY SELECTING IS ENOUGH. The dropdown says "pick another to cut its
     highlights instead", so picking one and seeing the options stay as they
     were reads as though nothing happened -- and Counter-Strike's controls are
     not Delta Force's: it clips whole ROUNDS, so the minimum-kills control is
     replaced by the round types.

     This changes the options and what the next run will be told, but does NOT
     rewrite the journal. "Use this game" still does that, because correcting
     the record of a stream is a bigger claim than choosing what to cut now. */
  var s = clip_state.pick;
  if (!s || !key) return;
  var prof = clip_profileFor(key);
  s.game_key = key;
  s.game = label || (prof && prof.label) || key;
  if (prof) {
    s.rounds = !!prof.rounds;
    s.scan_mode = prof.mode || s.scan_mode;
    s.profile = prof.label;
    s.can_scan = !!prof.ready;
    s.blocked = prof.ready ? '' : s.blocked;
  }
  clip_renderOptions();
}

async function clip_setGame() {
  var s = clip_state.pick;
  var sel = clip_el('clip-gamefix');
  if (!s || !sel || !sel.value) return;
  var label = sel.options[sel.selectedIndex].getAttribute('data-label') || sel.value;
  if (s.local) {
    /* Nothing to correct in the journal: this file was never a session. */
    s.game_key = sel.value;
    s.game = label;
    clip_renderOptions();
    return;
  }
  var r = await API.post('/api/clips/setgame', {
    recording_path: s.recording_path, game: label, game_key: sel.value});
  if (r && r.error) { toast(r.error, 'error'); return; }
  toast('Now treated as ' + label + '.', 'ok');
  await clip_load();
}

async function clip_reveal(path) {
  if (!path) return;
  var r = await API.post('/api/clips/open', {path: path});
  if (r && r.error) toast(r.error, 'warn');
}

/* ----------------------------------------------------------- calibration */

function clip_calOpen() {
  var s = clip_state.pick;
  if (!s || !s.has_recording) {
    toast('Pick a stream with a recording first.', 'warn');
    return;
  }
  clip_state.cal.open = true;
  clip_state.cal.path = s.recording_path;
  clip_state.cal.dur = s.duration || 0;
  clip_state.cal.t = Math.min(60, (s.duration || 0) / 2);
  clip_state.cal.box = null;
  var range = clip_el('clip-cal-range');
  if (range) {
    range.max = String(Math.max(1, Math.floor(clip_state.cal.dur)));
    range.value = String(Math.floor(clip_state.cal.t));
  }
  var name = clip_el('clip-cal-name');
  if (name) name.value = s.game || '';
  /* Start on the mode this game actually needs. A seed says so before any
     profile exists, and an existing profile says so afterwards, so the user
     is confirming rather than guessing. */
  var player = clip_el('clip-cal-player');
  if (player) player.value = s.player || '';
  clip_calSetMode(s.scan_mode || (s.seed && s.seed.mode) || 'template');
  clip_show('clip-cal-scrim', true);
  clip_show('clip-cal-rect', false);
  clip_show('clip-cal-verdict', false);
  clip_show('clip-cal-err', false);
  clip_calFrame();
  clip_calSaveState();
}

function clip_calClose() {
  clip_state.cal.open = false;
  clip_show('clip-cal-scrim', false);
}

function clip_calFrame() {
  var img = clip_el('clip-cal-img');
  if (!img) return;
  clip_show('clip-cal-wait', true);
  var url = '/api/clips/frame?k=' + encodeURIComponent(SHELL_K) +
            '&path=' + encodeURIComponent(clip_state.cal.path) +
            '&t=' + encodeURIComponent(String(clip_state.cal.t));
  img.onload = function () { clip_show('clip-cal-wait', false); };
  img.onerror = function () {
    clip_show('clip-cal-wait', false);
    clip_calErr('Could not read that frame.');
  };
  img.src = url;
  var lbl = clip_el('clip-cal-time');
  if (lbl) lbl.textContent = shell_hms(clip_state.cal.t);
  /* A new frame invalidates the box drawn on the old one. */
  clip_state.cal.box = null;
  clip_show('clip-cal-rect', false);
  clip_show('clip-cal-verdict', false);
  clip_calSaveState();
}

function clip_calSeek(delta) {
  var c = clip_state.cal;
  c.t = Math.max(0, Math.min(c.dur || 1e9, c.t + delta));
  var range = clip_el('clip-cal-range');
  if (range) range.value = String(Math.floor(c.t));
  clip_calFrame();
}

function clip_calErr(msg) {
  var e = clip_el('clip-cal-err');
  if (!e) return;
  e.textContent = msg || '';
  e.classList.toggle('hide', !msg);
}

function clip_calSaveState() {
  var b = clip_el('clip-cal-save');
  var name = clip_el('clip-cal-name');
  if (!b) return;
  /* Reading the feed needs a name to look for. Without one the scan finds
     nothing and looks like a game with no kills, so the button stays off
     rather than letting a useless profile be saved. */
  var player = clip_el('clip-cal-player');
  var needsPlayer = clip_calMode() === 'killfeed' &&
                    !(player && player.value.trim());
  b.disabled = clip_state.cal.busy || !clip_state.cal.box ||
               !(name && name.value.trim()) || needsPlayer;
}

function clip_calDrag(stage, rect) {
  /* Fractions of the IMAGE, not of the stage: the image is letterboxed inside
     the stage, and sending stage-relative numbers would offset every box by
     the size of the black bars. */
  var img = clip_el('clip-cal-img');
  if (!img || !img.naturalWidth) return null;
  var ib = img.getBoundingClientRect();
  var x1 = (Math.min(rect.x1, rect.x2) - ib.left) / ib.width;
  var y1 = (Math.min(rect.y1, rect.y2) - ib.top) / ib.height;
  var x2 = (Math.max(rect.x1, rect.x2) - ib.left) / ib.width;
  var y2 = (Math.max(rect.y1, rect.y2) - ib.top) / ib.height;
  x1 = Math.max(0, Math.min(1, x1)); x2 = Math.max(0, Math.min(1, x2));
  y1 = Math.max(0, Math.min(1, y1)); y2 = Math.max(0, Math.min(1, y2));
  if (x2 - x1 < 0.004 || y2 - y1 < 0.006) return null;
  return [x1, y1, x2, y2];
}

var CLIP_CAL_HINTS = {
  template: 'Drag a tight box around the marker the game draws when YOU get a ' +
            'kill - usually a small icon near the crosshair.',
  killfeed: 'Drag a box around the WHOLE kill feed, wide enough to include the ' +
            'names at both ends of every line. Your name left of the weapon ' +
            'icon is a kill, right of it is a death.'
};

function clip_calMode() {
  return (clip_state.cal && clip_state.cal.mode) || 'template';
}

function clip_calSetMode(mode) {
  clip_state.cal.mode = (mode === 'killfeed') ? 'killfeed' : 'template';
  var seg = clip_el('clip-cal-mode');
  if (seg) {
    var bs = seg.querySelectorAll('[data-mode]');
    for (var i = 0; i < bs.length; i++) {
      bs[i].classList.toggle('is-on', bs[i].dataset.mode === clip_state.cal.mode);
    }
  }
  var row = clip_el('clip-cal-player-row');
  if (row) row.classList.toggle('hide', clip_state.cal.mode !== 'killfeed');
  var hint = clip_el('clip-cal-mode-hint');
  if (hint) {
    hint.textContent = CLIP_CAL_HINTS[clip_state.cal.mode] || '';
    hint.classList.remove('hide');
  }
  clip_calSaveState();
}

async function clip_calSave() {
  var c = clip_state.cal;
  var name = clip_el('clip-cal-name');
  if (!c.box || !name || !name.value.trim()) return;
  c.busy = true;
  clip_calSaveState();
  clip_calErr('');
  var v = clip_el('clip-cal-verdict');
  if (v) { v.classList.remove('hide'); v.className = 'clip-verdict';
           v.innerHTML = '<span class="spin"></span> ' + (clip_calMode() === 'killfeed'
             ? 'Checking your name is readable in that box...'
             : 'Checking the marker stands out...'); }
  try {
    var player = clip_el('clip-cal-player');
    var r = await API.post('/api/clips/calibrate', {
      path: c.path, t: c.t, box: c.box,
      label: name.value.trim(),
      key: (clip_state.pick && clip_state.pick.game_key) || '',
      mode: clip_calMode(),
      player: (player && player.value.trim()) || ''
    });
    if (r && r.error) {
      clip_calErr(r.error);
      if (v) v.classList.add('hide');
    } else if (v) {
      v.className = 'clip-verdict is-' + (r.separation || 'weak');
      v.textContent = r.note || '';
      if (r.separation === 'bad') {
        toast('That marker is not distinct enough - try again.', 'warn');
      } else {
        toast('Saved a profile for ' + r.label + '.', 'ok');
        await clip_load();
      }
    }
  } catch (e) {
    clip_calErr('Could not save that.');
  }
  c.busy = false;
  clip_calSaveState();
}

/* ------------------------------------------------------------------ wiring */

function clip_wire() {
  if (clip_state.wired) return;
  clip_state.wired = true;

  var g = clip_el('clip-game');
  if (g) g.addEventListener('change', function () {
    clip_state.game = g.value; clip_renderList();
  });
  /* Delegated: the results list is rebuilt on every finished run. */
  document.addEventListener('change', function (ev) {
    var t = ev.target;
    if (!t || !t.getAttribute) return;
    var i = t.getAttribute('data-up');
    if (i === null) return;
    var c = (clip_state.results || [])[Number(i)];
    if (!c) return;
    clip_state.upPicked = clip_state.upPicked || {};
    clip_state.upPicked[String(c.rank)] = !!t.checked;
    clip_renderUpload();
  });
  var upv = clip_el('clip-up-privacy');
  if (upv) upv.addEventListener('change', clip_renderUpload);

  var lg = clip_el('clip-local-game');
  if (lg) lg.addEventListener('change', clip_renderNamePrompt);

  var rf = clip_el('clip-refresh');
  if (rf) rf.addEventListener('click', clip_load);
  var go = clip_el('clip-go');
  if (go) go.addEventListener('click', clip_run);
  /* ---- the player. One delegated handler, because the panel is rebuilt
     whenever a clip is loaded and per-button listeners would need rebinding. */
  var pcard = clip_el('clip-player-card');
  if (pcard) pcard.addEventListener('click', function (ev) {
    var el = ev.target.closest ? ev.target.closest('[data-play],[data-vert]') : null;
    if (!el) return;
    var v = clip_el('clip-video');
    var vert = el.getAttribute('data-vert');
    if (vert) {
      var seg = clip_el('clip-play-vert');
      if (seg) {
        var all = seg.querySelectorAll('[data-vert]');
        for (var i = 0; i < all.length; i++) all[i].classList.toggle('is-on', all[i] === el);
      }
      return;
    }
    var what = el.getAttribute('data-play');
    var p = clip_state.player;
    if (what === 'toggle') clip_playerToggle();
    else if (what === 'next') clip_playerStep(1);
    else if (what === 'prev') clip_playerStep(-1);
    else if (what === 'mute' && v) {
      v.muted = !v.muted;
      el.innerHTML = v.muted ? '&#128263;' : '&#128266;';
    } else if (what === 'full') {
      var stage = pcard.querySelector('.clip-play-stage');
      if (document.fullscreenElement) document.exitFullscreen();
      else if (stage && stage.requestFullscreen) stage.requestFullscreen();
    } else if (what === 'setin' && v && p) {
      p.trim.in = Math.max(0, v.currentTime);
      if (p.trim.out != null && p.trim.out <= p.trim.in) p.trim.out = null;
      clip_playerTrimText();
    } else if (what === 'setout' && v && p) {
      p.trim.out = Math.max(0.5, v.currentTime);
      if (p.trim.in != null && p.trim.in >= p.trim.out) p.trim.in = null;
      clip_playerTrimText();
    } else if (what === 'cleartrim' && p) {
      p.trim = {in: null, out: null};
      clip_playerTrimText();
    }
  });

  var vid = clip_el('clip-video');
  if (vid) {
    vid.addEventListener('timeupdate', clip_playerTick);
    vid.addEventListener('loadedmetadata', function () {
      clip_playerTick();
      clip_playerTrimText();
    });
    vid.addEventListener('play', clip_playerTick);
    vid.addEventListener('pause', clip_playerTick);
    /* Autoplay the next clip, the way a playlist does. */
    vid.addEventListener('ended', function () { clip_playerStep(1); });
  }
  var seek = clip_el('clip-play-seek');
  if (seek) {
    seek.addEventListener('pointerdown', function () { seek.dataset.dragging = '1'; });
    var stop = function () { delete seek.dataset.dragging; };
    seek.addEventListener('pointerup', stop);
    seek.addEventListener('change', stop);
    seek.addEventListener('input', function () {
      var v = clip_el('clip-video');
      if (v && isFinite(v.duration)) v.currentTime = v.duration * Number(seek.value) / 1000;
    });
  }
  var vol = clip_el('clip-play-vol');
  if (vol) vol.addEventListener('input', function () {
    var v = clip_el('clip-video');
    if (v) { v.volume = Number(vol.value) / 100; v.muted = false; }
  });
  var spd = clip_el('clip-play-speed');
  if (spd) spd.addEventListener('change', function () {
    var v = clip_el('clip-video');
    if (v) v.playbackRate = Number(spd.value);
  });
  ['clip-play-capsw', 'clip-play-saysw'].forEach(function (id) {
    var sw = clip_el(id);
    if (sw) sw.addEventListener('click', function () {
      clip_switch(id, !clip_switchOn(id));
    });
  });
  var hear = clip_el('clip-play-hear');
  if (hear) hear.addEventListener('click', function () {
    clip_playVoice((clip_el('clip-play-voice') || {}).value || '',
                   (clip_el('clip-play-say') || {}).value || '');
  });
  var apply = clip_el('clip-play-apply');
  if (apply) apply.addEventListener('click', clip_playerApply);
  var pclose = clip_el('clip-play-close');
  if (pclose) pclose.addEventListener('click', function () {
    var v = clip_el('clip-video');
    if (v) { v.pause(); v.removeAttribute('src'); v.load(); }
    clip_state.player = null;
    clip_show('clip-player-card', false);
  });

  /* The keys a media player has. Ignored while typing, or the caption box
     would swallow every space and jump the video instead of spacing a word. */
  document.addEventListener('keydown', function (ev) {
    if (!clip_state.player) return;
    var t = ev.target && ev.target.tagName;
    if (t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT') return;
    var v = clip_el('clip-video');
    if (!v) return;
    var k = ev.key;
    if (k === ' ') { ev.preventDefault(); clip_playerToggle(); }
    else if (k === 'ArrowRight') { ev.preventDefault(); v.currentTime += 5; }
    else if (k === 'ArrowLeft') { ev.preventDefault(); v.currentTime -= 5; }
    else if (k === 'ArrowUp') { ev.preventDefault(); v.volume = Math.min(1, v.volume + 0.1); }
    else if (k === 'ArrowDown') { ev.preventDefault(); v.volume = Math.max(0, v.volume - 0.1); }
    else if (k === 'm' || k === 'M') { v.muted = !v.muted; }
    else if (k === 'n' || k === 'N') { clip_playerStep(1); }
    else if (k === 'p' || k === 'P') { clip_playerStep(-1); }
    else if (k === 'f' || k === 'F') {
      var stage = document.querySelector('.clip-play-stage');
      if (document.fullscreenElement) document.exitFullscreen();
      else if (stage && stage.requestFullscreen) stage.requestFullscreen();
    }
  });

  /* ---- clips a previous run already produced */
  var madeHide = clip_el('clip-made-hide');
  if (madeHide) madeHide.addEventListener('click', function () {
    clip_show('clip-made-card', false);
  });
  var madePlay = clip_el('clip-made-play');
  if (madePlay) madePlay.addEventListener('click', function () {
    var m = clip_state.made;
    if (m) clip_openPlayer(m.clips, 0, m.folder);
  });
  var madeList = clip_el('clip-made-list');
  if (madeList) madeList.addEventListener('click', function (ev) {
    var el = ev.target.closest ? ev.target.closest('[data-made]') : null;
    var m = clip_state.made;
    if (el && m) clip_openPlayer(m.clips, Number(el.getAttribute('data-made')), m.folder);
  });

  var gamefix = clip_el('clip-gamefix');
  if (gamefix) gamefix.addEventListener('change', function () {
    var opt = gamefix.options[gamefix.selectedIndex];
    clip_useGameLocally(gamefix.value,
                        opt ? opt.getAttribute('data-label') : '');
  });

  var rev = clip_el('clip-review');
  if (rev) rev.addEventListener('click', clip_preview);
  var revCut = clip_el('clip-review-cut');
  if (revCut) revCut.addEventListener('click', clip_reviewCut);
  var revClose = clip_el('clip-review-close');
  if (revClose) revClose.addEventListener('click', function () {
    clip_state.review = null;
    clip_show('clip-review-card', false);
  });
  var revList = clip_el('clip-review-list');
  if (revList) {
    revList.addEventListener('click', clip_reviewClick);
    revList.addEventListener('input', clip_reviewInput);
    revList.addEventListener('change', clip_reviewInput);
  }
  var allVoice = clip_el('clip-review-voice-all');
  if (allVoice) allVoice.addEventListener('change', function () {
    var rv = clip_state.review;
    if (!rv) return;
    rv.rows.forEach(function (r) { r.voice_name = allVoice.value; });
    clip_renderReview();
  });
  var playAll = clip_el('clip-review-play-all');
  if (playAll) playAll.addEventListener('click', function () {
    clip_playVoice(allVoice ? allVoice.value : '', '');
  });

  var rsw = clip_el('clip-rounds');
  if (rsw) rsw.addEventListener('click', function () {
    clip_state.rounds = clip_state.rounds === false;
    clip_renderOptions();
  });
  var wsw = clip_el('clip-whole');
  if (wsw) wsw.addEventListener('click', function () {
    clip_state.whole = clip_state.whole === false;
    clip_renderOptions();
  });
  var types = clip_el('clip-types');
  if (types) types.addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-type]');
    if (!b) return;
    var k = b.dataset.type;
    var i = clip_state.types.indexOf(k);
    if (i >= 0) clip_state.types.splice(i, 1);
    else clip_state.types.push(k);
    /* Turning everything off would silently produce nothing, so the last one
       stays on rather than the run failing with an empty selection. */
    if (!clip_state.types.length) clip_state.types = [k];
    clip_renderTypes();
  });

  var tr = clip_el('clip-trans');
  if (tr) tr.addEventListener('change', function () {
    clip_state.trans = tr.value; clip_renderOptions();
  });
  var tm = clip_el('clip-transms');
  if (tm) tm.addEventListener('change', function () {
    clip_state.transMs = Number(tm.value);
  });

  /* Playing a finished clip. Separate from data-act because the results list
     is rebuilt on every poll and the index is the only handle on a row. */
  document.addEventListener('click', function (ev) {
    var b = ev.target && ev.target.closest
      ? ev.target.closest('[data-res-play]') : null;
    if (!b) return;
    var list = clip_state.results || [];
    var i = Number(b.getAttribute('data-res-play'));
    if (list.length) clip_openPlayer(list, i, clip_state.resultsFolder || '');
  });

  /* One delegated listener for everything with a data-act. No inline onclick
     anywhere, so rebuilding a list never leaks a handler. */
  document.addEventListener('click', function (ev) {
    var b = ev.target && ev.target.closest ? ev.target.closest('[data-act]') : null;
    if (!b) return;
    var view = clip_el('view-clips');
    if (!view || !view.contains(b)) return;
    var act = b.getAttribute('data-act');

    if (act === 'style') {
      clip_state.style = b.getAttribute('data-val');
      clip_renderOptions();
    } else if (act === 'pick') {
      clip_state.pick = clip_state.shown[Number(b.getAttribute('data-i'))] || null;
      clip_renderList(); clip_renderOptions();
    } else if (act === 'min') {
      clip_state.min = b.getAttribute('data-val'); clip_renderOptions();
    } else if (act === 'len') {
      clip_state.len = b.getAttribute('data-val'); clip_renderOptions();
    } else if (act === 'vert') {
      clip_state.vert = b.getAttribute('data-val'); clip_renderOptions();
    } else if (act === 'montage') {
      clip_state.montage = !clip_state.montage; clip_renderOptions();
    } else if (act === 'cancel') {
      /* The poll is two seconds away and the job takes longer than that to
         wind down, so the button answers for itself immediately. Pressing it
         and seeing nothing change is what made a stopping job look hung. */
      b.disabled = true;
      b.textContent = 'Stopping...';
      clip_state.stopping = true;
      toast('Stopping - anything already decoding finishes first.', 'ok');
      API.post('/api/clips/cancel', {});
    } else if (act === 'reveal') {
      clip_reveal(b.getAttribute('data-path'));
    } else if (act === 'reveal-src') {
      clip_reveal(clip_state.pick && clip_state.pick.recording_path);
    } else if (act === 'reveal-out') {
      clip_reveal((clip_state.lastJob && clip_state.lastJob.folder) ||
                  clip_state.outputDir);
    } else if (act === 'pick-local') {
      clip_pickLocal();
    } else if (act === 'use-local') {
      clip_useLocal();
    } else if (act === 'get-demos') {
      clip_getDemos();
    } else if (act === 'save-name') {
      clip_saveName();
    } else if (act === 'upload') {
      clip_upload();
    } else if (act === 'upload-cancel') {
      API.post('/api/clips/upload/cancel', {});
    } else if (act === 'setgame') {
      clip_setGame();
    } else if (act === 'calibrate') {
      clip_calOpen();
    } else if (act === 'cal-close') {
      clip_calClose();
    }
  });

  /* calibration: scrub buttons, range, and the drag-a-box overlay */
  document.addEventListener('click', function (ev) {
    var b = ev.target && ev.target.closest ? ev.target.closest('[data-cal]') : null;
    if (b) clip_calSeek(Number(b.getAttribute('data-cal')));
  });
  var range = clip_el('clip-cal-range');
  if (range) range.addEventListener('change', function () {
    clip_state.cal.t = Number(range.value); clip_calFrame();
  });
  var nm = clip_el('clip-cal-name');
  if (nm) nm.addEventListener('input', clip_calSaveState);
  var pl = clip_el('clip-cal-player');
  if (pl) pl.addEventListener('input', clip_calSaveState);
  var seg = clip_el('clip-cal-mode');
  if (seg) seg.addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-mode]');
    if (b) clip_calSetMode(b.dataset.mode);
  });
  var save = clip_el('clip-cal-save');
  if (save) save.addEventListener('click', clip_calSave);

  var stage = clip_el('clip-cal-stage');
  if (stage) {
    stage.addEventListener('pointerdown', function (ev) {
      if (ev.button !== 0) return;
      clip_state.cal.drag = {x1: ev.clientX, y1: ev.clientY,
                             x2: ev.clientX, y2: ev.clientY};
      stage.setPointerCapture(ev.pointerId);
      clip_calPaint();
      ev.preventDefault();
    });
    stage.addEventListener('pointermove', function (ev) {
      var d = clip_state.cal.drag;
      if (!d) return;
      d.x2 = ev.clientX; d.y2 = ev.clientY;
      clip_calPaint();
    });
    stage.addEventListener('pointerup', function (ev) {
      var d = clip_state.cal.drag;
      clip_state.cal.drag = null;
      if (!d) return;
      try { stage.releasePointerCapture(ev.pointerId); } catch (e) {}
      var box = clip_calDrag(stage, d);
      clip_state.cal.box = box;
      if (!box) {
        clip_show('clip-cal-rect', false);
        clip_calErr('That box is too small - drag a bigger one round the marker.');
      } else {
        clip_calErr('');
      }
      clip_calSaveState();
    });
  }

  /* Escape closes the calibrator, matching every other modal convention. */
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && clip_state.cal.open) clip_calClose();
  });
}

function clip_calPaint() {
  var d = clip_state.cal.drag;
  var stage = clip_el('clip-cal-stage'), r = clip_el('clip-cal-rect');
  if (!d || !stage || !r) return;
  var sb = stage.getBoundingClientRect();
  r.classList.remove('hide');
  r.style.left = (Math.min(d.x1, d.x2) - sb.left) + 'px';
  r.style.top = (Math.min(d.y1, d.y2) - sb.top) + 'px';
  r.style.width = Math.abs(d.x2 - d.x1) + 'px';
  r.style.height = Math.abs(d.y2 - d.y1) + 'px';
}

/* ------------------------------------------------------------------ page */

window.PAGE_CLIPS = {
  onShow: function () {
    clip_wire();
    if (!clip_state.loaded) { clip_load(); clip_loadGames(); }
    else clip_renderOptions();
  },
  onTick: function (status) {
    clip_renderUploadJob(status && status.upload);
    clip_renderEdit(status && status.edit);
    var j = status && status.clips;
    if (!j) { clip_state.busy = false; return; }
    var wasBusy = clip_state.busy;
    var fresh = !clip_state.lastJob || clip_state.lastJob.folder !== j.folder ||
                clip_state.lastJob.state !== 'done';
    /* A plan-only run has clips to review and no files to show, so it opens
       the review panel rather than the results. Checked before the results
       branch because both fire on the same transition to done. */
    if (clip_state.reviewing && j.state === 'done' && fresh) {
      clip_state.reviewing = false;
      clip_state.busy = false;
      var rb = clip_el('clip-review');
      if (rb) rb.disabled = false;
      clip_openReview(j);
      clip_state.lastJob = j;
      clip_load();
      return;
    }
    if (clip_state.reviewing && (j.state === 'failed' || j.state === 'cancelled')) {
      clip_state.reviewing = false;
      var rb2 = clip_el('clip-review');
      if (rb2) rb2.disabled = false;
    }
    clip_renderJob(j);
    if (j.state === 'done' && (!clip_state.lastJob ||
        clip_state.lastJob.folder !== j.folder ||
        clip_state.lastJob.state !== 'done')) {
      /* The job payload is a summary; the per-clip list lives in the folder's
         manifest, so it is only fetched once the run actually finishes. */
      clip_fetchResults(j);
    }
    clip_state.lastJob = j;
    if (wasBusy && !clip_state.busy) {
      clip_load();
      if (j.state === 'done') toast('Clips are ready.', 'ok');
      else if (j.state === 'failed') toast(j.error || 'Clip job failed.', 'error');
    }
  }
};

async function clip_fetchResults(j) {
  /* Results ride the sessions endpoint rather than getting one of their own -
     it is already the page's refresh path. */
  try {
    var r = await API.get('/api/clips/sessions');
    var last = (r && r.last_job) || null;
    if (last && last.clips) clip_renderResults(last.clips, last.montage);
    else clip_renderResults([], j.montage);
  } catch (e) { /* the headline summary is already on screen */ }
}
"""
