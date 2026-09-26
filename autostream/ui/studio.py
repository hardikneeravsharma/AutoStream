"""Studio page: every clip the user has made, and reels edited on a timeline.

WHAT THE PAGE IS FOR
    The Clips page is organised around ONE recording at a time -- scan it, cut
    it, fix it. That is the wrong shape for making a reel, which wants the best
    moments from every session. So this page starts from the other end: all the
    clips on disk, grouped the way they were made (game, then run), selectable
    one at a time, by range, or a whole run at once.

WHY A TIMELINE AND NOT A FORM
    A reel is a sequence of decisions in time -- this shot, this long, its kill
    on this beat, this transition into the next. A form can hold those values
    but cannot show how they relate, and "the flash lands a beat late" is only
    visible when the flash, the kill and the beat are drawn on one axis. So the
    finished reel opens as tracks: video, transitions, effects, speed, text and
    music with its beat grid, and every one of them is editable there.

THE SERVER OWNS THE ARITHMETIC
    The page edits the project; /api/studio/check clamps it and returns every
    derived time. During a drag the page moves blocks with its own quick
    estimate, then asks the server once on release. Two implementations of
    where a kill lands would eventually disagree, and the one that renders is
    the one that has to be right.

NAMING
    Every top-level JS name is studio_-prefixed; window.PAGE_STUDIO is the one
    unprefixed global (see the module contract in ui/__init__.py).
"""
from __future__ import annotations

STUDIO_HTML = r"""
<div class="studio">
  <header class="studio-head">
    <div class="studio-head-text"></div>
    <div class="seg" role="tablist" aria-label="Studio views">
      <button type="button" class="seg-btn is-active" role="tab" aria-selected="true"
              data-act="studio-tab" data-tab="clips" id="studio-tab-clips">Clips</button>
      <button type="button" class="seg-btn" role="tab" aria-selected="false"
              data-act="studio-tab" data-tab="timeline" id="studio-tab-timeline" disabled>Timeline</button>
      <button type="button" class="seg-btn" role="tab" aria-selected="false"
              data-act="studio-tab" data-tab="song" id="studio-tab-song" disabled>Song</button>
      <button type="button" class="seg-btn" role="tab" aria-selected="false"
              data-act="studio-tab" data-tab="facecam" id="studio-tab-facecam" disabled>Facecam</button>
    </div>
  </header>

  <section id="studio-pane-clips" aria-label="Clips">
    <!-- THE PARTS BIN, AT THE TOP. A reel is one pick from each drawer; the
         count says how many reels those drawers can make, which is the point
         of picking rather than taking the same style every time. -->
    <header class="bin-top">
      <div class="bin-intro">
        <p class="bin-eyebrow">Reel maker · parts bin</p>
        <h1 class="bin-title">Pick the clips, deal a template</h1>
        <p class="bin-lede">Every reel is a set of picks from a few drawers: how it opens, how shots meet,
          what happens on a kill, how time bends, what colour it is, how it ends. Each pick below is shown
          by an example cut from your own clips, so you choose by watching. Select clips, then make a reel.</p>
        <p class="bin-lede" id="studio-sub">Reading your clips…</p>
      </div>
      <aside class="bin-calc" aria-label="How many templates">
        <p class="bin-eyebrow">Mix and match</p>
        <div class="bin-big" id="bin-total">—<small id="bin-total-note">counting the drawers</small></div>
        <div class="bin-slots" id="bin-slots"></div>
      </aside>
    </header>
    <div class="studio-tools">
      <input class="input studio-search" id="studio-q" type="search"
             placeholder="Search clips, captions or runs" aria-label="Search clips">
      <div class="studio-games" id="studio-games" role="group" aria-label="Games"></div>
      <button type="button" class="btn btn-ghost btn-sm" data-act="studio-refresh">Refresh</button>
      <!-- CLIPS THE PLAYER ALREADY HAS: saved by the game, by Medal, sent by a
           friend. Added here they are clips like any other. -->
      <button type="button" class="btn btn-sm" data-act="studio-imp-add">Add your own clip…</button>
    </div>
    <div class="studio-reels" id="studio-reels"></div>
    <div id="studio-lib" class="studio-lib"></div>
    <p class="muted studio-empty hide" id="studio-empty"></p>

    <section class="bin-sec" id="bin" aria-label="Parts bin">
      <div class="bin-sec-head">
        <h2>The drawers</h2><span class="count" id="bin-count"></span>
        <p>One example each, cut from your own clips by the same code that renders the reel — so a card
          shows what the reel will actually do. Click one to put it in the template you are dealing.</p>
      </div>
      <div class="bin-build">
        <span class="bin-arrange" id="bin-arrange"></span>
        <span class="bin-shape" id="bin-shape"></span>
        <button type="button" class="btn btn-sm" data-act="studio-bin-favonly" id="bin-favonly"
                aria-pressed="false" title="Show only the parts you have kept">&#9733; Favourites</button>
        <button type="button" class="btn btn-sm" data-act="studio-bin-build" id="bin-build">Cut the missing examples</button>
        <button type="button" class="btn btn-sm btn-ghost hide" data-act="studio-bin-stop" id="bin-build-stop">Stop</button>
        <span id="bin-build-msg"></span>
      </div>
      <div id="bin-drawers"></div>
    </section>
    <div class="studio-tray hide" id="studio-tray" role="region" aria-label="Selection">
      <div class="studio-tray-text">
        <strong id="studio-tray-count">0 clips</strong>
        <span class="muted" id="studio-tray-facts"></span>
        <span class="studio-adding hide" id="studio-adding"></span>
      </div>
      <button type="button" class="btn btn-ghost btn-sm" data-act="studio-fav-selected" id="studio-fav-btn">★ Favourite</button>
      <button type="button" class="btn btn-ghost btn-sm" data-act="studio-clear">Clear</button>
      <button type="button" class="btn btn-ghost btn-sm hide" data-act="studio-add-cancel" id="studio-add-cancel">Stop adding</button>
      <button type="button" class="btn btn-ghost btn-sm studio-del-btn" data-act="studio-delete">Delete…</button>
      <button type="button" class="btn btn-primary" data-act="studio-make" id="studio-make-btn">Make a reel</button>
    </div>
  </section>

  <!-- THE EDITOR. One screen, no page scroll: the picture where the eyes are,
       the tracks under it, and everything about the selected thing in one
       column beside both. It used to be a page -- player and render card, then
       the tracks, then an inspector beside only the tracks -- so editing an
       effect meant scrolling down to the tracks and back up to see it, and the
       page jumped every time the inspector redrew. Every id below is the one
       the old layout had; only where things sit has changed. -->
  <section id="studio-pane-timeline" class="hide studio-editor" aria-label="Timeline">
    <div class="ed-main">
      <div class="ed-toolbar">
        <label class="sr-only" for="studio-pname">Reel name</label>
        <input class="input ed-name" id="studio-pname" maxlength="80" placeholder="Reel name">
        <p class="muted studio-facts ed-facts" id="studio-facts"></p>
        <span class="studio-spacer"></span>
        <div class="field-inline studio-acts">
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-undo" id="studio-undo-btn" disabled>Undo</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-show" id="studio-show-btn" disabled>Show file</button>
          <button type="button" class="btn btn-ghost btn-sm hide" data-act="studio-cancel" id="studio-cancel-btn">Cancel</button>
          <button type="button" class="btn btn-primary" data-act="studio-render" id="studio-render-btn">Render</button>
        </div>
      </div>

      <div class="ed-stage">
        <div class="studio-player" id="studio-player">
          <video id="studio-video" controls playsinline preload="metadata"></video>
          <div class="studio-player-empty" id="studio-player-empty">The reel appears here once it has rendered.</div>
          <!-- THE PLAYER IS WHERE THE EYES ARE. A sidebar saying the edits are
               not in the video yet is missed by someone watching the video, so
               the video says it too, over its own top corner. -->
          <div class="studio-stale hide" id="studio-stale" aria-hidden="true"></div>
          <!-- THE HANDLE, WHERE IT WILL BE. Dragged on the picture itself,
               because "a bit higher than the kill counter" is a place you
               point at, not a number. Shown while the Reel tab is open. -->
          <div class="ed-frame hide" id="studio-frame" aria-hidden="true">
            <span class="ed-handle" id="studio-handle-chip" title="Drag to move your handle"></span>
          </div>
        </div>
      </div>

      <div class="studio-tl-bar ed-transport">
        <button type="button" class="btn btn-sm studio-transport" data-act="studio-play" id="studio-play-btn">Play</button>
        <span class="mono studio-clock" id="studio-clock">0:00.00</span>
        <span class="media-knobs" data-for="studio-video"></span>
        <label class="studio-check"><input type="checkbox" id="studio-snap" checked> Snap to beats</label>
        <!-- WHAT THE MUSIC LANE SHOWS. A waveform cannot say whether a kill sat
             on the kick it was aimed at; the spectrogram and the song's own hit
             marks can, so both are on by default and either can be turned off. -->
        <label class="studio-check"><input type="checkbox" id="studio-tl-spec" checked> Spectrogram</label>
        <label class="studio-check"><input type="checkbox" id="studio-tl-marks" checked> Song's hits</label>
        <span class="studio-spacer"></span>
        <span class="muted studio-hint" id="studio-tl-sync" role="status" aria-live="polite"></span>
        <button type="button" class="btn btn-ghost btn-sm" data-act="studio-zoom" data-z="-1" aria-label="Zoom out">−</button>
        <button type="button" class="btn btn-ghost btn-sm" data-act="studio-zoom" data-z="0">Fit</button>
        <button type="button" class="btn btn-ghost btn-sm" data-act="studio-zoom" data-z="1" aria-label="Zoom in">+</button>
        <span class="mono studio-zoomlab" id="studio-zoomlab" aria-hidden="true"></span>
      </div>
      <div class="studio-tl" id="studio-tl" tabindex="0" aria-label="Timeline, use arrow keys to move between shots">
        <div class="studio-labels" aria-hidden="true">
          <div class="st-lab st-lab-ruler"></div>
          <div class="st-lab">Video</div>
          <div class="st-lab">Transitions</div>
          <div class="st-lab">Effects</div>
          <div class="st-lab">Speed</div>
          <div class="st-lab">Text</div>
          <div class="st-lab">Music</div>
        </div>
        <div class="studio-scroll" id="studio-scroll">
          <div class="studio-tracks" id="studio-tracks"></div>
        </div>
      </div>
      <p class="muted studio-hint ed-hint">Drag a shot to move it, its edge to trim, its diamond to move the kill.
        Ctrl+wheel zooms. Arrow keys move between shots, Space plays.</p>
    </div>

    <aside class="ed-side" aria-label="Inspector">
      <!-- DOES THE VIDEO MATCH THE TIMELINE? The one question the page was
           unable to answer: "Render changes" against "Render again" is a
           two-word difference nobody reads, so an edit could sit unrendered
           for an hour. One strip owns the answer -- a colour, a sentence,
           and, when they differ, the list of what has not reached the
           video yet. -->
      <div class="studio-sync is-none" id="studio-sync">
        <p class="studio-sync-line">
          <span class="studio-sync-dot" aria-hidden="true"></span>
          <span class="studio-sync-head" id="studio-sync-head">Not rendered yet</span>
        </p>
        <!-- studio-state is the job's own words (Ready, Cancelled, the
             error). Kept as its own node: it is what the render tests read. -->
        <p class="studio-sync-sub" id="studio-sync-sub"></p>
        <p class="studio-state" id="studio-state" role="status" aria-live="polite"></p>
        <div class="meter hide" id="studio-meter-wrap" aria-hidden="true"><div class="meter-fill" id="studio-meter" style="width:0%"></div></div>
        <ul class="studio-pending hide" id="studio-pending"></ul>
      </div>

      <!-- WHAT AN EFFECT LOOKS LIKE, BEFORE IT IS PICKED. Pointing at any
           part in the inspector plays its example here -- the same two-second
           cards the parts bin shows -- so a list of names becomes a list of
           things you can watch. -->
      <div class="ed-fx hide" id="studio-fxprev" aria-live="polite">
        <div class="ed-fx-shot" id="studio-fxprev-shot"></div>
        <div class="ed-fx-text">
          <strong id="studio-fxprev-name"></strong>
          <span class="muted" id="studio-fxprev-blurb"></span>
        </div>
      </div>

      <div class="studio-insp card" id="studio-insp" aria-label="Inspector"></div>

      <!-- WHY THE REEL IS THE WAY IT IS. Five amber bullets shouting at
           once read as five problems; they are mostly the planner saying
           what it did. Anything wrong with the reel as it stands is above,
           in its own plate; the planner's account of the build is folded
           away, where it can be opened by someone who wants it. -->
      <div class="studio-why" id="studio-why"></div>
    </aside>
  </section>

  <!-- THE FACECAM. Its own place, because both jobs it has are done by eye:
       drawing a box round a camera that is already in the recording, or
       lining up a separate camera video until the laugh lands on the kill. -->
  <section id="studio-pane-facecam" class="hide studio-fc" aria-label="Facecam">
    <div class="studio-fc-head">
      <div>
        <h2 class="studio-h">Facecam</h2>
        <p class="muted studio-small">Where your camera comes from, and where it goes in this reel.</p>
      </div>
      <div class="seg" role="group" aria-label="Facecam source" id="studio-fc-src"></div>
    </div>

    <div class="studio-fc-grid">
      <div class="card"><div class="card-body studio-fc-card">
        <!-- IN THE VIDEO: a box drawn once on a frame of their own footage. -->
        <div id="studio-fc-inset" class="hide">
          <h3 class="studio-h">Draw a box round your camera</h3>
          <p class="muted studio-small">Drag on the frame. The box is kept for every reel, so a camera that is always in
            the same corner is drawn once.</p>
          <div class="field-inline">
            <label class="field-label" for="studio-fc-clip">Frame from</label>
            <select class="select" id="studio-fc-clip"></select>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-fc-frame" data-d="-2">−2 s</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-fc-frame" data-d="2">+2 s</button>
          </div>
          <div class="studio-fc-stage" id="studio-fc-stage">
            <img id="studio-fc-img" alt="A frame of your recording">
            <div class="ed-cambox hide" id="studio-fc-box"><span>Facecam</span></div>
          </div>
          <div class="field-inline">
            <button type="button" class="btn btn-sm" data-act="studio-fc-boxreset">Start over</button>
            <span class="muted studio-small" id="studio-fc-boxnote"></span>
          </div>
        </div>

        <!-- A SEPARATE VIDEO: attached to the session it was recorded with,
             and lined up by sound or by eye. -->
        <div id="studio-fc-file" class="hide">
          <h3 class="studio-h">Attach your camera video</h3>
          <p class="muted studio-small">Attach it to the session it was recorded beside, once, and every clip from that
            session uses it. Then line it up: "Find it from the sound" matches the two recordings' audio; the nudges are for
            finishing by eye.</p>
          <div id="studio-fc-links" class="studio-fc-links"></div>
          <div class="studio-fc-sync hide" id="studio-fc-syncbox">
            <div class="studio-fc-pair">
              <figure><video id="studio-fc-game" playsinline preload="metadata" muted></video><figcaption>Game</figcaption></figure>
              <figure><video id="studio-fc-cam" playsinline preload="metadata"></video><figcaption>Camera</figcaption></figure>
            </div>
            <div class="studio-tl-bar">
              <button type="button" class="btn btn-sm studio-transport" data-act="studio-fc-play" id="studio-fc-play">Play both</button>
              <span class="mono" id="studio-fc-clock">0:00.00</span>
              <span class="media-knobs" data-for="studio-fc-cam"></span>
            </div>
            <div class="field-inline studio-nudge">
              <span class="field-label">Camera offset</span>
              <button type="button" class="btn btn-ghost btn-sm" data-act="studio-fc-nudge" data-d="-1">−1 s</button>
              <button type="button" class="btn btn-ghost btn-sm" data-act="studio-fc-nudge" data-d="-0.1">−0.1</button>
              <button type="button" class="btn btn-ghost btn-sm" data-act="studio-fc-nudge" data-d="-0.02">−1 f</button>
              <span class="mono" id="studio-fc-offset">0.00 s</span>
              <button type="button" class="btn btn-ghost btn-sm" data-act="studio-fc-nudge" data-d="0.02">+1 f</button>
              <button type="button" class="btn btn-ghost btn-sm" data-act="studio-fc-nudge" data-d="0.1">+0.1</button>
              <button type="button" class="btn btn-ghost btn-sm" data-act="studio-fc-nudge" data-d="1">+1 s</button>
              <button type="button" class="btn btn-sm" data-act="studio-fc-sync" id="studio-fc-syncbtn">Find it from the sound</button>
            </div>
            <p class="muted studio-small" id="studio-fc-syncnote"></p>
          </div>
        </div>

        <p class="muted" id="studio-fc-none">No facecam in this reel. Choose where yours comes from above.</p>
      </div></div>

      <div class="card"><div class="card-body studio-fc-card">
        <h3 class="studio-h">Where it goes</h3>
        <div id="studio-fc-layout"></div>
        <!-- A mock of the frame, drawn from a still of the game and a still of
             the camera cut, so the layout is judged before anything renders. -->
        <div class="studio-fc-mockwrap"><canvas id="studio-fc-mock" aria-label="How the reel will be laid out"></canvas></div>
        <div class="field-inline">
          <button type="button" class="btn btn-primary" data-act="studio-tab-go" data-tab="timeline">Back to the timeline</button>
        </div>
      </div></div>
    </div>
  </section>

  <!-- THE SONG. Its own place, because choosing the part of a track and where
       the kills fall in it is listening work: it wants the whole song on one
       axis, the chosen part magnified on another, and the music playing. -->
  <section id="studio-pane-song" class="hide" aria-label="Song">
    <div class="studio-sg-head">
      <div class="studio-sg-title">
        <strong class="studio-sg-name" id="studio-sg-name">No song</strong>
        <span class="muted" id="studio-sg-facts">Choose a song to cut the reel to.</span>
      </div>
      <div class="field-inline">
        <button type="button" class="btn" data-act="studio-sg-pick">Choose a song…</button>
        <button type="button" class="btn" data-act="studio-yt" data-for="song">Paste a YouTube link…</button>
        <button type="button" class="btn btn-ghost" data-act="studio-sg-none">No song</button>
      </div>
    </div>
    <!-- THE SONGS ALREADY HERE. Every song downloaded for a reel stays in
         Videos\AutoStream\songs; picking one back out of a file dialog is
         work the page can do. -->
    <div class="studio-sg-songs" id="studio-sg-songs" role="group" aria-label="Songs you have"></div>
    <div class="studio-sg-body hide" id="studio-sg-body">
      <p class="field-label">The whole song — drag the highlighted part, or its edges</p>
      <canvas class="studio-sg-wave" id="studio-sg-overview" height="90" aria-label="Whole song"></canvas>
      <p class="field-label">The part you are using — click to move the playhead</p>
      <canvas class="studio-sg-wave studio-sg-detail" id="studio-sg-detail" height="130" aria-label="Chosen part"></canvas>
      <!-- WAYS OF SEEING IT. A waveform shows loudness and nothing else; a
           kill goes on a kick or a hat, and those are only visible once the
           bands are separated (clips/songview.py). The detector's own kills
           are drawn above them, so what it would cut to can be judged against
           what is marked by hand. -->
      <div class="studio-sg-viewbar" id="studio-sg-viewbar">
        <span class="field-label">Show</span>
        <div class="studio-sg-toggles" id="studio-sg-toggles"></div>
        <span class="field-label">Zoom</span>
        <span class="seg" role="group" aria-label="Zoom">
          <button type="button" class="seg-btn" data-act="studio-sg-win" data-win="2">2 s</button>
          <button type="button" class="seg-btn" data-act="studio-sg-win" data-win="4">4 s</button>
          <button type="button" class="seg-btn is-active" data-act="studio-sg-win" data-win="8">8 s</button>
          <button type="button" class="seg-btn" data-act="studio-sg-win" data-win="16">16 s</button>
        </span>
        <label class="studio-check"><input type="checkbox" id="studio-sg-showdet" checked> The detector's kills</label>
        <span class="muted" id="studio-sg-detnote"></span>
      </div>
      <div class="studio-sg-lanes" id="studio-sg-lanes"></div>
      <audio id="studio-sg-audio" preload="auto"></audio>
      <div class="studio-tl-bar">
        <button type="button" class="btn btn-sm studio-transport studio-transport-wide" data-act="studio-sg-play" id="studio-sg-play">Play the part</button>
        <label class="studio-check"><input type="checkbox" id="studio-sg-loop" checked> Loop</label>
        <span class="mono studio-clock" id="studio-sg-clock">0:00.00</span>
        <span class="muted" id="studio-sg-range"></span>
        <span class="media-knobs" data-for="studio-sg-audio"></span>
      </div>
      <div class="studio-sg-grid">
        <div class="card"><div class="card-body studio-sg-card">
          <h3 class="studio-h">Where the reel starts</h3>
          <div class="field-inline studio-nudge">
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="start" data-d="-bar">−1 bar</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="start" data-d="-beat">−1 beat</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="start" data-d="-ms">−10 ms</button>
            <span class="mono" id="studio-sg-start">0:00.00</span>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="start" data-d="ms">+10 ms</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="start" data-d="beat">+1 beat</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="start" data-d="bar">+1 bar</button>
          </div>
          <div class="field-inline">
            <button type="button" class="btn btn-sm" data-act="studio-sg-snapbar">Snap to the nearest bar</button>
            <button type="button" class="btn btn-sm" data-act="studio-sg-atdrop" id="studio-sg-atdrop">Build into the drop</button>
          </div>
          <h3 class="studio-h">Where it ends</h3>
          <div class="field-inline studio-nudge">
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="end" data-d="-bar">−1 bar</button>
            <span class="mono" id="studio-sg-end">0:00.00</span>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-nudge" data-what="end" data-d="bar">+1 bar</button>
            <button type="button" class="btn btn-sm" data-act="studio-sg-fit">Fit the timeline</button>
          </div>
          <p class="muted" id="studio-sg-fitnote"></p>
        </div></div>
        <div class="card"><div class="card-body studio-sg-card">
          <h3 class="studio-h">Mark the kills <span class="muted">(optional)</span></h3>
          <p class="muted">Play the part and press <kbd>K</kbd> on every beat a kill should land on.
             Shot 1's kill lands on mark 1, shot 2's on mark 2, and so on; the cuts move to fit.
             <kbd>Space</kbd> plays and pauses. "Where the kills are now" fills these in from the
             reel as it stands, so the marks AutoStream chose can be moved rather than retapped.</p>
          <div class="field-inline">
            <button type="button" class="btn btn-primary" data-act="studio-sg-mark">Mark a kill here (K)</button>
            <button type="button" class="btn btn-ghost" data-act="studio-sg-fromkills" id="studio-sg-fromkills">Where the kills are now</button>
            <button type="button" class="btn btn-ghost" data-act="studio-sg-unmark">Undo mark</button>
            <button type="button" class="btn btn-ghost" data-act="studio-sg-clearmarks">Clear marks</button>
          </div>
          <div class="field-inline">
            <label class="studio-check"><input type="checkbox" id="studio-sg-snap" checked> Snap marks to the beat</label>
            <label class="studio-check"><input type="checkbox" id="studio-sg-click" checked> Click on each mark as it plays</label>
          </div>
          <div class="reel-chips" id="studio-sg-chips"></div>
          <!-- A mark is chosen by clicking its chip; these move the chosen one.
               Hidden until there is one, so the row does not sit empty. -->
          <div class="field-inline studio-nudge hide" id="studio-sg-marknudge">
            <span class="muted">Mark <b id="studio-sg-marknum">1</b></span>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-marknudge" data-d="-beat">−1 beat</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-marknudge" data-d="-half">−½</button>
            <span class="mono" id="studio-sg-marktime">0:00.00</span>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-marknudge" data-d="half">+½</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-marknudge" data-d="beat">+1 beat</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-markplay">Hear it</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-sg-markdrop">Remove</button>
          </div>
          <p class="muted" id="studio-sg-marksinfo"></p>
        </div></div>
      </div>
      <div class="studio-sg-apply">
        <span class="muted" id="studio-sg-msg"></span>
        <button type="button" class="btn btn-primary" data-act="studio-sg-apply" id="studio-sg-apply">Use this part</button>
      </div>
    </div>
  </section>

  <div class="scrim hide" id="studio-make-scrim">
  <div class="modal studio-modal" id="studio-make" role="dialog" aria-modal="true" aria-labelledby="studio-make-title">
    <h2 class="modal-title" id="studio-make-title">Make a reel</h2>
    <div class="modal-body">
      <p class="muted" id="studio-make-facts"></p>
      <h3 class="studio-h">Style</h3>
      <div class="studio-styles" id="studio-styles" role="radiogroup" aria-label="Style"></div>
      <!-- THE TEMPLATE: what the style picked, shown part by part with its
           example, and changeable one drawer at a time. -->
      <h3 class="studio-h">Template</h3>
      <div class="bin-dealer">
        <button type="button" class="btn btn-sm" data-act="studio-deal">Deal a template</button>
        <button type="button" class="btn btn-ghost btn-sm" data-act="studio-deal-reset">Back to the style's own</button>
        <span class="bin-code" id="studio-deal-code"></span>
      </div>
      <div class="bin-hand" id="studio-hand"></div>
      <h3 class="studio-h">Song</h3>
      <div class="field-inline">
        <button type="button" class="btn" data-act="studio-song">Choose a song…</button>
        <button type="button" class="btn" data-act="studio-yt" data-for="make">Paste a YouTube link…</button>
        <button type="button" class="btn btn-ghost" data-act="studio-nosong">No song</button>
        <span class="muted" id="studio-song-name">No song: the clips keep their own sound, cut to a 120 BPM grid.</span>
      </div>
      <!-- THE PART, BEFORE THE PLAN: chosen afterwards a part can only take
           shots away, so a short selection on a slow song came out short. -->
      <div class="studio-mk-part hide" id="studio-mk-part">
        <h3 class="studio-h">Part of the song</h3>
        <div class="seg" role="group" aria-label="Reel length">
          <button type="button" class="seg-btn is-active" data-act="studio-mk-mode" data-mode="part">Choose the part</button>
          <button type="button" class="seg-btn" data-act="studio-mk-mode" data-mode="auto">Let AutoStream choose</button>
        </div>
        <div class="studio-mk-body" id="studio-mk-body">
          <canvas class="studio-sg-wave" id="studio-mk-wave" height="70" aria-label="The song: drag the highlighted part or its edges"></canvas>
          <!-- Only the choosing is hidden when AutoStream chooses: the song
               still has to be heard, so the player below stays. -->
          <div id="studio-mk-partctl">
          <div class="field-inline studio-nudge">
            <span class="muted">Starts</span>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-nudge" data-what="start" data-d="-bar">−1 bar</button>
            <span class="mono" id="studio-mk-start">0:00.00</span>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-nudge" data-what="start" data-d="bar">+1 bar</button>
            <span class="muted">Ends</span>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-nudge" data-what="end" data-d="-bar">−1 bar</button>
            <span class="mono" id="studio-mk-end">0:00.00</span>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-nudge" data-what="end" data-d="bar">+1 bar</button>
          </div>
          <div class="field-inline">
            <button type="button" class="btn btn-sm" data-act="studio-mk-preset" data-preset="drums">From the drums</button>
            <button type="button" class="btn btn-sm" data-act="studio-mk-preset" data-preset="drop" id="studio-mk-drop">Build into the drop</button>
            <button type="button" class="btn btn-sm" data-act="studio-mk-preset" data-preset="whole">Whole song</button>
          </div>
          </div>
          <!-- LISTEN BEFORE CHOOSING: a part is picked by ear, so it plays, pauses where
               it is, and seeks anywhere inside it. -->
          <div class="studio-mk-transport" role="group" aria-label="Play the part">
            <button type="button" class="btn btn-sm studio-mk-play" data-act="studio-mk-play" id="studio-mk-play">Play</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-skip" data-d="-5" aria-label="Back 5 seconds">−5 s</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-skip" data-d="5" aria-label="Forward 5 seconds">+5 s</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-restart">From the start</button>
            <input type="range" class="studio-mk-seek" id="studio-mk-seek" min="0" max="1000" step="1" value="0" aria-label="Position in the part">
            <span class="mono studio-mk-clock" id="studio-mk-clock">0:00.0 / 0:00.0</span>
            <label class="studio-check"><input type="checkbox" id="studio-mk-loop"> Loop</label>
            <span class="media-knobs" data-for="studio-mk-audio"></span>
            <audio id="studio-mk-audio" preload="metadata"></audio>
          </div>
          <p class="muted" id="studio-mk-facts"></p>
        </div>
      </div>
      <!-- THE INTRO, HERE AND NOT ONLY ON THE TIMELINE. It used to be
           reachable only after a reel had been rendered once, so the first
           render always went out without one. The trim and the fit stay on the
           timeline's own dialog; what belongs here is which clip and whether
           it is heard, because those are the two that change the render. -->
      <div class="studio-mk-intro hide" id="studio-mk-intro">
        <h3 class="studio-h">Intro clip</h3>
        <div class="field-inline">
          <select class="input studio-mk-introsel" id="studio-mk-introsel" aria-label="Intro clip">
            <option value="">No intro</option>
          </select>
          <label class="studio-check" id="studio-mk-introaudio-wrap">
            <input type="checkbox" id="studio-mk-introaudio"> Play its own sound
          </label>
        </div>
        <p class="muted" id="studio-mk-intronote"></p>
      </div>
      <h3 class="studio-h">Shape</h3>
      <div class="field-inline studio-shape">
        <div class="seg" role="group" aria-label="Format">
          <button type="button" class="seg-btn is-active" data-act="studio-fmt" data-fmt="landscape">Landscape 16:9</button>
          <button type="button" class="seg-btn" data-act="studio-fmt" data-fmt="vertical">Vertical 9:16</button>
        </div>
        <div class="seg" role="group" aria-label="Order">
          <button type="button" class="seg-btn is-active" data-act="studio-order" data-order="chosen">As chosen</button>
          <button type="button" class="seg-btn" data-act="studio-order" data-order="kills">Most kills first</button>
          <button type="button" class="seg-btn" data-act="studio-order" data-order="oldest">Oldest first</button>
        </div>
      </div>
      <label class="field-label" for="studio-name">Name</label>
      <input class="input" id="studio-name" maxlength="80" placeholder="Montage reel">
    </div>
    <div class="modal-actions">
      <span class="muted" id="studio-make-msg"></span>
      <button type="button" class="btn btn-ghost" data-act="studio-make-cancel">Cancel</button>
      <button type="button" class="btn btn-primary" data-act="studio-build" id="studio-build-btn">Build and render</button>
    </div>
  </div>
  </div>

  <div class="scrim hide" id="studio-yt-scrim">
  <div class="modal studio-yt" id="studio-yt" role="dialog" aria-modal="true" aria-labelledby="studio-yt-title">
    <h2 class="modal-title" id="studio-yt-title">Song from a YouTube link</h2>
    <div class="modal-body studio-yt-body">
      <label class="field-label" for="studio-yt-url">YouTube link</label>
      <input class="input" id="studio-yt-url" type="url" inputmode="url" autocomplete="off" spellcheck="false"
             placeholder="https://www.youtube.com/watch?v=…">
      <p class="muted studio-yt-hint">Only the song's audio is downloaded, into <span class="mono">Videos\AutoStream\songs</span>,
        and a link you have used before is not downloaded again. Use songs you are allowed to use: YouTube can mute or
        claim a video that has someone else's music in it.</p>
      <div class="studio-yt-progress hide" id="studio-yt-progress">
        <div class="meter"><div class="meter-fill" id="studio-yt-meter" style="width:0%"></div></div>
        <p class="studio-yt-status" id="studio-yt-status" role="status" aria-live="polite"></p>
      </div>
      <p class="studio-yt-error hide" id="studio-yt-error" role="alert"></p>
    </div>
    <div class="modal-actions">
      <button type="button" class="btn btn-ghost" data-act="studio-yt-close" id="studio-yt-close">Cancel</button>
      <button type="button" class="btn btn-primary" data-act="studio-yt-go" id="studio-yt-go">Download</button>
    </div>
  </div>
  </div>

  <div class="scrim hide" id="studio-del-scrim">
  <div class="modal" id="studio-del" role="dialog" aria-modal="true" aria-labelledby="studio-del-title">
    <h2 class="modal-title" id="studio-del-title">Delete clips</h2>
    <div class="modal-body">
      <p id="studio-del-text"></p>
      <p class="muted" id="studio-del-reels"></p>
    </div>
    <div class="modal-actions">
      <span class="muted" id="studio-del-msg"></span>
      <button type="button" class="btn btn-ghost" data-act="studio-del-cancel">Cancel</button>
      <button type="button" class="btn btn-danger" data-act="studio-del-go" id="studio-del-go">Delete</button>
    </div>
  </div>
  </div>

  <!-- THE INTRO CLIP. A dialog and not a panel in the inspector, because the
       inspector rebuilds its own HTML on every edit: a <video> living there
       would reload, lose its playhead and stop mid-trim every time a slider
       moved. Trimming by eye needs a player that stays put. -->
  <div class="scrim hide" id="studio-intro-scrim">
  <div class="modal studio-intro-modal" id="studio-intro" role="dialog" aria-modal="true" aria-labelledby="studio-intro-title">
    <h2 class="modal-title" id="studio-intro-title">Intro clip</h2>
    <div class="modal-body studio-intro-body">
      <p class="muted studio-intro-lede" id="studio-intro-lede"></p>

      <div class="studio-intro-lib" id="studio-intro-lib" role="group" aria-label="Your intro clips"></div>
      <div class="field-inline">
        <button type="button" class="btn" data-act="studio-intro-add" id="studio-intro-add">Add a GIF or video…</button>
        <span class="muted" id="studio-intro-msg"></span>
      </div>

      <div class="studio-intro-edit hide" id="studio-intro-edit">
        <div class="studio-intro-player">
          <video id="studio-intro-video" playsinline preload="metadata" muted></video>
        </div>
        <div class="studio-tl-bar">
          <button type="button" class="btn btn-sm studio-transport studio-transport-wide" data-act="studio-intro-play" id="studio-intro-play">Play the part</button>
          <label class="studio-check"><input type="checkbox" id="studio-intro-loop" checked> Loop</label>
          <span class="mono studio-clock" id="studio-intro-clock">0:00.00</span>
          <span class="muted" id="studio-intro-range"></span>
          <span class="media-knobs" data-for="studio-intro-video"></span>
        </div>

        <!-- TRIMMED TWO WAYS, BECAUSE THEY ARE TWO DIFFERENT JOBS. The sliders
             are for "about there"; "Start here"/"End here" take the playhead,
             which is how you trim to a beat you can see. -->
        <div class="studio-intro-trim">
          <label class="field-label" for="studio-intro-a">Starts at <span class="mono" id="studio-intro-astamp">0:00.00</span></label>
          <div class="field-inline studio-nudge">
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-intro-nudge" data-what="start" data-d="-1">−1 s</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-intro-nudge" data-what="start" data-d="-0.1">−0.1 s</button>
            <input type="range" id="studio-intro-a" min="0" max="1000" value="0" aria-label="Where the intro starts">
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-intro-nudge" data-what="start" data-d="0.1">+0.1 s</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-intro-nudge" data-what="start" data-d="1">+1 s</button>
            <button type="button" class="btn btn-sm" data-act="studio-intro-here" data-what="start">Start here</button>
          </div>
          <label class="field-label" for="studio-intro-b">Ends at <span class="mono" id="studio-intro-bstamp">0:00.00</span></label>
          <div class="field-inline studio-nudge">
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-intro-nudge" data-what="end" data-d="-1">−1 s</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-intro-nudge" data-what="end" data-d="-0.1">−0.1 s</button>
            <input type="range" id="studio-intro-b" min="0" max="1000" value="1000" aria-label="Where the intro ends">
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-intro-nudge" data-what="end" data-d="0.1">+0.1 s</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-intro-nudge" data-what="end" data-d="1">+1 s</button>
            <button type="button" class="btn btn-sm" data-act="studio-intro-here" data-what="end">End here</button>
          </div>
          <div class="field-inline">
            <button type="button" class="btn btn-sm" data-act="studio-intro-fit-lead" id="studio-intro-fit-lead">Fill the lead-in</button>
            <button type="button" class="btn btn-ghost btn-sm" data-act="studio-intro-whole">The whole clip</button>
          </div>
        </div>

        <div class="studio-intro-opts">
          <div class="studio-field">
            <span class="field-label">Sound</span>
            <label class="studio-check"><input type="checkbox" id="studio-intro-audio"> Play the clip's own sound</label>
            <p class="muted studio-small" id="studio-intro-audionote"></p>
          </div>
          <div class="studio-field">
            <span class="field-label">Shape</span>
            <div class="seg">
              <button type="button" class="seg-btn is-active" data-act="studio-intro-fit" data-fit="cover" id="studio-intro-fit-cover">Fill the frame</button>
              <button type="button" class="seg-btn" data-act="studio-intro-fit" data-fit="contain" id="studio-intro-fit-contain">Fit it all in</button>
            </div>
            <p class="muted studio-small" id="studio-intro-fitnote"></p>
          </div>
        </div>
      </div>
    </div>
    <div class="modal-actions">
      <span class="muted" id="studio-intro-warn"></span>
      <button type="button" class="btn btn-ghost hide" data-act="studio-intro-clear" id="studio-intro-clear">Open without an intro</button>
      <button type="button" class="btn btn-ghost" data-act="studio-intro-cancel">Cancel</button>
      <button type="button" class="btn btn-primary" data-act="studio-intro-use" id="studio-intro-use" disabled>Use this intro</button>
    </div>
  </div>
  </div>

  <!-- DELETING A REEL. Its own dialog rather than the clips one: what goes and
       what stays are the opposite way round here, and that is the whole
       question being asked. -->
  <div class="scrim hide" id="studio-rdel-scrim">
  <div class="modal" id="studio-rdel" role="dialog" aria-modal="true" aria-labelledby="studio-rdel-title">
    <h2 class="modal-title" id="studio-rdel-title">Delete reel</h2>
    <div class="modal-body">
      <p id="studio-rdel-text"></p>
      <p class="muted" id="studio-rdel-note"></p>
    </div>
    <div class="modal-actions">
      <span class="muted" id="studio-rdel-msg"></span>
      <button type="button" class="btn btn-ghost" data-act="studio-rdel-cancel">Cancel</button>
      <button type="button" class="btn btn-danger" data-act="studio-rdel-go" id="studio-rdel-go">Delete</button>
    </div>
  </div>
  </div>

  <!-- YOUR OWN CLIP. A file the player brings, its kills and what it is.
       Marked the way a song is marked: play it, press K on each kill. -->
  <div class="scrim hide" id="studio-imp-scrim">
  <div class="modal studio-imp" id="studio-imp" role="dialog" aria-modal="true" aria-labelledby="studio-imp-title">
    <h2 class="modal-title" id="studio-imp-title">Your clip</h2>
    <div class="modal-body studio-imp-body">
      <div class="studio-imp-player">
        <video id="studio-imp-video" playsinline preload="metadata"></video>
        <canvas class="studio-imp-lane" id="studio-imp-lane" height="46" aria-label="The clip: click to move the playhead"></canvas>
        <div class="studio-tl-bar">
          <button type="button" class="btn btn-sm studio-transport" data-act="studio-imp-play" id="studio-imp-play">Play</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-imp-step" data-d="-1">−1 s</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-imp-step" data-d="-0.0333">−1 f</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-imp-step" data-d="0.0333">+1 f</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-imp-step" data-d="1">+1 s</button>
          <span class="mono studio-clock" id="studio-imp-clock">0:00.00</span>
          <span class="media-knobs" data-for="studio-imp-video"></span>
        </div>
      </div>
      <div class="studio-imp-side">
        <label class="field-label" for="studio-imp-game">Game</label>
        <select class="select" id="studio-imp-game"></select>
        <label class="field-label" for="studio-imp-name">Title</label>
        <input class="input" id="studio-imp-name" maxlength="80" placeholder="e.g. 1v3 clutch">
        <div class="reel-chips" id="studio-imp-presets"></div>

        <h3 class="studio-h">Kills</h3>
        <p class="muted studio-small">Play it and press <kbd>K</kbd> the moment each kill lands, or let AutoStream find them
          for the game you chose. <kbd>Space</kbd> plays and pauses; <kbd>,</kbd> and <kbd>.</kbd> step a frame.</p>
        <div class="field-inline">
          <button type="button" class="btn btn-primary btn-sm" data-act="studio-imp-mark">Kill here (K)</button>
          <button type="button" class="btn btn-sm" data-act="studio-imp-detect" id="studio-imp-detect">Find the kills</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-imp-clear">Clear</button>
        </div>
        <p class="muted studio-small" id="studio-imp-detnote" role="status" aria-live="polite"></p>
        <div class="reel-chips" id="studio-imp-kills"></div>
      </div>
    </div>
    <div class="modal-actions">
      <span class="muted" id="studio-imp-msg"></span>
      <button type="button" class="btn btn-ghost" data-act="studio-imp-close">Close</button>
      <button type="button" class="btn btn-primary" data-act="studio-imp-save" id="studio-imp-save">Save</button>
    </div>
  </div>
  </div>

  <div class="scrim hide" id="studio-preview-scrim">
  <div class="modal studio-modal" id="studio-preview" role="dialog" aria-modal="true" aria-labelledby="studio-preview-title">
    <h2 class="modal-title" id="studio-preview-title">Clip</h2>
    <div class="modal-body"><video id="studio-preview-video" controls playsinline></video></div>
    <div class="modal-actions">
      <span class="media-knobs" data-for="studio-preview-video"></span>
      <button type="button" class="btn btn-ghost" data-act="studio-preview-close">Close</button>
    </div>
  </div>
  </div>
</div>
"""

STUDIO_JS = r"""
/* =======================================================================
   STUDIO -- all clips, reels, and the timeline editor. Prefix: studio_
   ======================================================================= */

const studio = {
  lib: null, catalog: null, loadedAt: 0,
  game: 'all', q: '', selected: [], lastClick: null,
  examples: null, picks: null, binOn: null, binObs: null, binTimer: null,
  sv: null, svShow: null, svWin: 8, songList: null,
  /* The music lane: the whole song's spectrogram as one image, which song has
     been asked for, and what the lane is showing. */
  spec: null, musicWant: '', musicPending: false, showSpec: true, showMarks: true, waveTick: 0,
  style: '', song: '', songShape: null, fmt: 'landscape', order: 'chosen',
  project: null, derived: null, notes: [], dirty: true, output: '', renderedAt: 0,
  /* WHAT HAS NOT REACHED THE VIDEO YET. `dirty` could say that something had
     changed; it could not say what, so pressing render was an act of faith and
     not pressing it was a reel watched in the wrong version. Every edit names
     itself here ({label, shot, n}); a render empties the list. */
  pending: [], jobMsg: '', failMsg: '', renderNote: '', rendering: false,
  /* Which explanations are open. The card is redrawn on every edit and on
     every poll tick, and a fold that shut itself each time could not be read. */
  folds: {build: false, clips: false},
  sel: -1, pps: 60, snap: true, undo: [], checking: 0, checkTimer: null,
  polling: null, drag: null, clipIndex: {},
  gen: 0, jobId: 0, seenJob: -1, watching: -1, busy: false, pollTok: 0, buildGen: 0,
  favParts: [], favOnly: false,
  /* SHAPING THE REEL. Multipliers on what the style's references measured,
     so 1 is 'as the style has it' and the dials read as louder/quieter
     versions of the style rather than a jump to a different one. */
  shaping: {length: 1, pace: 1, effects: 1, flash: 1},
  /* HOW THE REEL IS ORDERED, and anything pinned into a slot. Rides in the
     same payload as the dials so one Build carries all of it. */
  arrange: 'build', pins: {}, shuffleSeed: 0,
  sg: {song: '', shape: null, start: 0, end: 0, marks: [], drag: null, ticked: {}, ac: null,
       sel: -1, seeded: ''},
  /* The part of the song chosen on the Make dialog, in song seconds. */
  mk: {mode: 'part', start: 0, end: 0, touched: false, drag: null, seekTo: null, ticking: false},
  /* A song being downloaded from a YouTube link, and which picker asked for it. */
  yt: {target: 'make', timer: null, running: false},
  /* Set while clips are being added to an existing reel: what to rebuild. */
  adding: null, delPaths: [], reelDel: '',
  /* The intro-clip dialog: the library, which one is being edited, and the
     trim being made to it. Nothing here touches the project until Use. */
  intro: {list: null, pick: '', seconds: 0, hasAudio: false,
          start: 0, end: 0, audio: false, fit: 'cover', tick: null},
  /* What the Make dialog chose, before any project exists to hang it on. */
  mkIntro: {path: '', audio: false},
  /* Which inspector groups are open, by key; see studio_grp. */
  grpOpen: {},
  /* The facecam tab: the links (clips/facecam.py), the box last drawn, the
     clip a frame is taken from, and the pair being lined up. */
  fc: {inset: null, links: {}, clips: [], clipI: null, t: 0, drag: null, key: '', clip: '', start: 0, offset: 0},
  /* A clip the player added, open in its dialog. */
  imp: {path: '', seconds: 0, kills: [], sel: -1, dirty: false, games: null}
};

const studio_el = (id) => document.getElementById(id);
const studio_show = (id, on) => { const e = studio_el(id); if (e) e.classList.toggle('hide', !on); };

/* The whole route, written out at every call: the wiring test finds the pages'
   routes by their literal text, and a route assembled from pieces is a route
   nothing appears to call. */
function studio_media(route, path, extra) {
  return route + '?k=' + encodeURIComponent(SHELL_K) + '&path=' +
         encodeURIComponent(path) + (extra || '');
}

function studio_secs(t) {
  t = Math.max(0, Number(t) || 0);
  const m = Math.floor(t / 60), s = t - m * 60;
  return m + ':' + (s < 10 ? '0' : '') + s.toFixed(2);
}

function studio_dur(t) {
  t = Math.round(Math.max(0, Number(t) || 0));
  return t >= 60 ? Math.floor(t / 60) + 'm ' + String(t % 60).padStart(2, '0') + 's' : t + 's';
}

function studio_part(id) {
  const p = (studio.catalog && studio.catalog.parts || []).find(x => x.id === id);
  return p || {id: id, label: id, blurb: '', kind: ''};
}

function studio_parts(kind) {
  return (studio.catalog && studio.catalog.parts || []).filter(p => p.kind === kind);
}

/* ------------------------------------------------------------ loading */

async function studio_load(force) {
  if (!studio.catalog) {
    const cat = await API.get('/api/studio/catalog');
    if (cat && cat.ok) {
      studio.catalog = cat; studio.style = cat.default_style;
      studio.favParts = cat.favourite_parts || [];
    }
  }
  if (!force && studio.lib && Date.now() - studio.loadedAt < 30000) { studio_renderLib(); return; }
  const lib = await API.get('/api/studio/library');
  if (!lib || !lib.ok) {
    studio_el('studio-sub').textContent = (lib && lib.error) || 'Could not read the clips folder.';
    return;
  }
  studio.lib = lib; studio.loadedAt = Date.now(); studio.clipIndex = {};
  studio_binLoad(force);
  lib.games.forEach(g => g.folders.forEach(f => f.clips.forEach(c => {
    c.game = g.game; c.folderLabel = f.label; c.when = f.when; studio.clipIndex[c.id] = c;
  })));
  studio.selected = studio.selected.filter(id => studio.clipIndex[id]);
  studio_renderLib();
}

/* ------------------------------------------------------------ the library */

function studio_visible() {
  const q = studio.q.trim().toLowerCase();
  const out = [];
  const favOnly = studio.game === 'fav';
  (studio.lib ? studio.lib.games : []).forEach(g => {
    if (studio.game !== 'all' && !favOnly && g.game !== studio.game) return;
    g.folders.forEach(f => {
      const clips = f.clips.filter(c => (!favOnly || c.fav) && (!q ||
        (c.name + ' ' + c.caption + ' ' + f.label + ' ' + g.game).toLowerCase().indexOf(q) >= 0));
      if (clips.length) out.push({game: g.game, folder: f, clips: clips});
    });
  });
  return out;
}

function studio_renderLib() {
  const lib = studio.lib;
  if (!lib) return;
  const games = lib.games.length;
  studio_el('studio-sub').textContent = lib.clip_count
    ? lib.clip_count + ' clips from ' + lib.games.reduce((n, g) => n + g.folders.length, 0) +
      ' runs across ' + games + (games === 1 ? ' game' : ' games') +
      '. Pick any of them, from any run, and make a reel.'
    : 'No clips yet. Cut some on the Clips page and they will appear here.';
  studio_el('studio-games').innerHTML =
    '<button type="button" class="chip' + (studio.game === 'all' ? ' is-on' : '') +
    '" data-act="studio-game" data-game="all" aria-pressed="' + (studio.game === 'all') + '">All <b>' +
    lib.clip_count + '</b></button>' +
    lib.games.map(g => '<button type="button" class="chip' + (studio.game === g.game ? ' is-on' : '') +
      '" data-act="studio-game" data-game="' + esc(g.game) + '" aria-pressed="' + (studio.game === g.game) +
      '">' + esc(g.game) + ' <b>' + g.clips + '</b></button>').join('') +
    /* Favourites cut across games, so the chip sits apart from them. */
    '<button type="button" class="chip studio-fav-chip' + (studio.game === 'fav' ? ' is-on' : '') +
    '" data-act="studio-game" data-game="fav" aria-pressed="' + (studio.game === 'fav') + '"' +
    ((lib.fav_count || 0) ? '' : ' disabled title="Star a clip with the star on its card"') +
    '>\u2605 Favourites <b>' + (lib.fav_count || 0) + '</b></button>';

  const reels = lib.reels || [];
  studio_el('studio-reels').innerHTML = reels.length
    ? '<h3 class="studio-h">Your reels</h3><div class="studio-reel-row">' + reels.slice(0, 10).map(r =>
      '<div class="studio-reel">' +
      '<span class="studio-reel-name truncate" title="' + esc(r.name) + '">' + esc(r.name) + '</span>' +
      '<span class="muted studio-reel-meta">' + (r.shots ? r.shots + ' shots · ' : '') +
      (r.length ? studio_dur(r.length) + ' · ' : '') + new Date(r.when * 1000).toLocaleDateString() + '</span>' +
      '<span class="field-inline">' +
      (r.project ? '<button type="button" class="btn btn-sm" data-act="studio-open" data-path="' + esc(r.path) + '">Open timeline</button>'
                 : '<span class="muted studio-reel-old">Made before the Studio</span>') +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-watch" data-path="' + esc(r.path) + '">Play</button>' +
      /* A reel is the biggest file the app makes and the easiest to make
         another of, so it needs a way out that is not the file explorer. */
      '<button type="button" class="btn btn-ghost btn-sm studio-del-btn" data-act="studio-reel-del" ' +
      'data-path="' + esc(r.path) + '" data-name="' + esc(r.name) + '" ' +
      'title="Delete this reel">Delete…</button>' +
      '</span></div>').join('') + '</div>'
    : '';

  const groups = studio_visible();
  const pos = {};
  studio.selected.forEach((id, i) => { pos[id] = i + 1; });
  let lastGame = '';
  let html = '';
  groups.forEach(gr => {
    if (gr.game !== lastGame) {
      html += '<h3 class="studio-game-h">' + esc(gr.game) + '</h3>';
      lastGame = gr.game;
    }
    const allOn = gr.clips.every(c => pos[c.id]);
    html += '<section class="studio-folder" aria-label="' + esc(gr.folder.label) + '">' +
      '<div class="studio-folder-h"><span class="studio-folder-name">' + esc(gr.folder.label) + '</span>' +
      '<span class="muted">' + gr.clips.length + ' clips</span>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-folder" data-folder="' +
      esc(gr.folder.folder) + '">' + (allOn ? 'Unselect run' : 'Select run') + '</button></div>' +
      '<div class="studio-grid">' + gr.clips.map(c => studio_tile(c, pos[c.id])).join('') + '</div></section>';
  });
  studio_el('studio-lib').innerHTML = html;
  const empty = !groups.length;
  studio_show('studio-empty', empty && lib.clip_count > 0);
  if (empty && lib.clip_count) studio_el('studio-empty').textContent = 'Nothing matches that search.';
  studio_renderTray();
}

function studio_tile(c, n) {
  const kill = (c.kills && c.kills.length ? c.kills[0] : 0);
  const at = Math.max(0, kill - 0.3).toFixed(2);
  return '<div class="studio-clip' + (n ? ' is-on' : '') + '" data-clip="' + esc(c.id) + '">' +
    '<button type="button" class="studio-clip-hit" data-act="studio-pick" data-clip="' + esc(c.id) +
    '" aria-pressed="' + (!!n) + '" aria-label="' + esc(c.name) + '">' +
    '<img loading="lazy" alt="" width="320" height="180" src="' + studio_media('/api/studio/thumb', c.path, '&t=' + at + '&v=' + (c.mtime || 0)) + '">' +
    '<span class="studio-clip-n">' + (n || '') + '</span>' +
    '<span class="studio-clip-dur mono">' + studio_dur(c.duration) + '</span>' +
    '<span class="studio-clip-kills">' + (c.unmarked ? 'no kills marked' : c.kill_count > 1 ? c.kill_count + ' kills' : '1 kill') + '</span>' +
    '</button>' +
    '<div class="studio-clip-foot"><span class="truncate" title="' + esc(c.name) + '">' +
    esc(c.caption || c.name) + '</span>' +
    '<button type="button" class="studio-star' + (c.fav ? ' is-on' : '') + '" data-act="studio-fav" data-clip="' +
      esc(c.id) + '" title="' + (c.fav ? 'A favourite. Click to unstar.' : 'Mark as a favourite') +
      '" aria-pressed="' + (c.fav ? 'true' : 'false') + '" aria-label="Favourite">' +
      (c.fav ? '\u2605' : '\u2606') + '</button>' +
    (c.imported ? '<button type="button" class="btn btn-ghost btn-sm' + (c.unmarked ? ' is-warn' : '') + '" data-act="studio-imp-edit" data-path="' +
      esc(c.path) + '" title="Mark its kills and give it a title">' + (c.unmarked ? 'Mark kills' : 'Edit') + '</button>' : '') +
    '<button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="studio-preview" data-clip="' +
    esc(c.id) + '" aria-label="Play ' + esc(c.name) + '">' + icon('play') + '</button></div></div>';
}

/* Selection changes touch the tiles they change. Rebuilding the grid on every
   click reloaded every thumbnail and threw away the scroll anchor. */
function studio_syncSelection() {
  const pos = {};
  studio.selected.forEach((id, i) => { pos[id] = i + 1; });
  document.querySelectorAll('#studio-lib .studio-clip').forEach(el => {
    const n = pos[el.getAttribute('data-clip')] || 0;
    el.classList.toggle('is-on', !!n);
    const badge = el.querySelector('.studio-clip-n');
    if (badge) badge.textContent = n ? String(n) : '';
    const hit = el.querySelector('.studio-clip-hit');
    if (hit) hit.setAttribute('aria-pressed', String(!!n));
  });
  studio_visible().forEach(gr => {
    const btn = document.querySelector('#studio-lib [data-act="studio-folder"][data-folder="' + CSS.escape(gr.folder.folder) + '"]');
    if (btn) btn.textContent = gr.clips.every(c => pos[c.id]) ? 'Unselect run' : 'Select run';
  });
  studio_renderTray();
}

function studio_renderTray() {
  studio_favLabel();
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  studio_show('studio-tray', sel.length > 0);
  studio_el('studio-tray-count').textContent = sel.length + (sel.length === 1 ? ' clip' : ' clips');
  const secs = sel.reduce((n, c) => n + c.duration, 0);
  const kills = sel.reduce((n, c) => n + (c.kill_count || 1), 0);
  const games = new Set(sel.map(c => c.game)).size;
  studio_el('studio-tray-facts').textContent = sel.length
    ? studio_dur(secs) + ' of footage · ' + kills + ' kills' + (games > 1 ? ' · ' + games + ' games' : '') : '';
  const ad = studio.adding;
  studio_show('studio-adding', !!ad);
  studio_show('studio-add-cancel', !!ad);
  if (ad) studio_el('studio-adding').textContent = 'Adding clips to ' + ad.name +
    ': the clips already in it are selected. Pick more, then rebuild.';
  studio_el('studio-make-btn').textContent = ad ? 'Rebuild ' + ad.name : 'Make a reel';
}

function studio_pick(id, shift) {
  const flat = [];
  studio_visible().forEach(g => g.clips.forEach(c => flat.push(c.id)));
  const i = studio.selected.indexOf(id);
  if (shift && studio.lastClick && flat.indexOf(studio.lastClick) >= 0) {
    const a = flat.indexOf(studio.lastClick), b = flat.indexOf(id);
    const lo = Math.min(a, b), hi = Math.max(a, b);
    for (let k = lo; k <= hi; k++) if (studio.selected.indexOf(flat[k]) < 0) studio.selected.push(flat[k]);
  } else if (i >= 0) {
    studio.selected.splice(i, 1);
  } else {
    studio.selected.push(id);
  }
  studio.lastClick = id;
  studio_syncSelection();
}

function studio_folderToggle(folder) {
  const f = studio_visible().find(g => g.folder.folder === folder);
  if (!f) return;
  const ids = f.clips.map(c => c.id);
  const all = ids.every(id => studio.selected.indexOf(id) >= 0);
  if (all) studio.selected = studio.selected.filter(id => ids.indexOf(id) < 0);
  else ids.forEach(id => { if (studio.selected.indexOf(id) < 0) studio.selected.push(id); });
  studio_syncSelection();
}

function studio_preview(id) {
  const c = studio.clipIndex[id];
  if (!c) return;
  studio_el('studio-preview-title').textContent = c.caption || c.name;
  const v = studio_el('studio-preview-video');
  v.src = studio_media('/api/clips/video', c.path);
  studio_show('studio-preview-scrim', true);
  v.play().catch(() => {});
}

function studio_closeModals() {
  const v = studio_el('studio-preview-video');
  if (v) { v.pause(); v.removeAttribute('src'); v.load(); }
  const a = studio_el('studio-mk-audio');
  if (a && !a.paused) a.pause();
  ['studio-preview-scrim', 'studio-make-scrim', 'studio-del-scrim',
   'studio-rdel-scrim', 'studio-intro-scrim'].forEach(id => studio_show(id, false));
  if (!studio_el('studio-imp-scrim').classList.contains('hide')) studio_impClose(false);
  const iv = studio_el('studio-intro-video');
  if (iv && !iv.paused) iv.pause();
  if (!studio.yt.running) studio_show('studio-yt-scrim', false);
}

/* ------------------------------------------------------------ make a reel */

async function studio_openMake() {
  if (!studio.selected.length) return;
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  const ad = studio.adding;
  studio_el('studio-make-facts').textContent = sel.length + ' clips, ' +
    sel.reduce((n, c) => n + (c.kill_count || 1), 0) + ' kills. Every cut and kill lands on the beat; ' +
    'you can change anything on the timeline afterwards.' +
    (ad ? ' Rebuilding ' + ad.name + ' plans every shot again' +
      (ad.edited ? ', so the changes you made on its timeline will be replaced.' : '.') : '');
  studio_el('studio-make-title').textContent = ad ? 'Rebuild ' + ad.name : 'Make a reel';
  studio_el('studio-build-btn').textContent = ad ? 'Rebuild and render' : 'Build and render';
  studio_el('studio-make-msg').textContent = '';
  /* Draw from what is already known, then fetch once if the library has never
     been read -- the dialog must not wait on a request to appear. */
  studio_mkIntroDraw();
  if (studio.intro.list === null) studio_introLoad();
  if (ad) {
    studio.style = ad.style || studio.style;
    studio.fmt = ad.fmt || studio.fmt;
    document.querySelectorAll('#studio-make [data-act="studio-fmt"]').forEach(x =>
      x.classList.toggle('is-active', x.getAttribute('data-fmt') === studio.fmt));
    studio_el('studio-name').value = ad.name;
    if (ad.song && ad.song !== studio.song) {
      studio_el('studio-song-name').textContent = 'Reading ' + ad.song.split(/[\\/]/).pop() + '…';
      const got = await API.post('/api/reel/song', {song: ad.song});
      if (got && got.ok) {
        studio.song = ad.song; studio.songShape = got.song;
        studio_el('studio-song-name').textContent = ad.song.split(/[\\/]/).pop() + ' · ' +
          Math.round(got.song.bpm) + ' BPM · ' + studio_dur(got.song.seconds);
      }
    }
    if (ad.song && studio.songShape) {
      studio.mk.mode = 'part'; studio.mk.touched = true;
      studio.mk.start = ad.start; studio.mk.end = Math.max(ad.start + studio_mkBar(), ad.end);
    }
  }
  studio_renderStyles();
  studio_hand();
  studio_show('studio-make-scrim', true);
  studio_mkDefault();
}

function studio_renderStyles() {
  const cat = studio.catalog;
  if (!cat) return;
  studio_el('studio-styles').innerHTML = cat.styles.map(s => {
    const m = s.measured || {};
    const on = s.key === studio.style;
    return '<button type="button" class="studio-style' + (on ? ' is-on' : '') + '" role="radio" aria-checked="' + on +
      '" data-act="studio-style" data-style="' + esc(s.key) + '">' +
      '<span class="studio-style-name">' + esc(s.label) + '</span>' +
      '<span class="studio-style-blurb">' + esc(s.blurb) + '</span>' +
      (m.edits ? '<span class="studio-style-data mono">Measured on ' + m.edits + (m.edits === 1 ? ' edit' : ' edits') + ': ' +
        m.cuts_per_min + ' cuts/min · ' + m.flashes_per_min + ' flashes/min · first shot ' + m.first_shot + ' s</span>' : '') +
      '</button>';
  }).join('');
  const st = cat.styles.find(s => s.key === studio.style);
  studio_el('studio-name').placeholder = (st ? st.label : 'My') + ' reel';
}

async function studio_pickSong() {
  const r = await API.post('/api/clips/pick', {kind: 'audio'});
  if (!r || !r.path) return;
  await studio_useSong(r.path);
}

/* A song file, whichever way it arrived, as the Make dialog's song. -> whether it could be read. */
async function studio_useSong(path, label) {
  const name = label || path.split(/[\\/]/).pop();
  studio_el('studio-song-name').textContent = 'Finding the beat in ' + name + '…';
  const got = await API.post('/api/reel/song', {song: path});
  if (!got || !got.ok) {
    studio_el('studio-song-name').textContent = (got && got.error) || 'Could not read that song.';
    return false;
  }
  const a = studio_el('studio-mk-audio');
  if (a && !a.paused) a.pause();
  studio.song = path; studio.songShape = got.song;
  studio_el('studio-song-name').textContent = name + ' · ' +
    Math.round(got.song.bpm) + ' BPM · ' + studio_dur(got.song.seconds) +
    (got.song.drop ? ' · drop at ' + studio_secs(got.song.drop) : '');
  studio.mk.touched = false;
  studio_mkDefault();
  return true;
}

/* ------------------------------------------------------------ the part of the song */

function studio_mkBar() {
  const sh = studio.songShape;
  return 4 * (sh ? (sh.beat || 60 / sh.bpm) : 0.5);
}

function studio_nearestBeat(sh, t) {
  const b = (sh && sh.beats) || [];
  let best = t, d = 1e9;
  for (let i = 0; i < b.length; i++) { const x = Math.abs(b[i] - t); if (x < d) { d = x; best = b[i]; } }
  return best;
}

/* A first part: from where the drums come in, as many whole bars as the format's
   usual length -- the same place and length the planner would have chosen. */
function studio_mkDefault() {
  const sh = studio.songShape, mk = studio.mk;
  studio_show('studio-mk-part', !!sh);
  if (!sh) return;
  if (!mk.touched) {
    const bar = studio_mkBar();
    const want = studio.fmt === 'vertical' ? 30 : 46;
    const bars = Math.max(1, Math.round(want / bar));
    const from = sh.drums_in || (sh.beats && sh.beats[0]) || 0;
    mk.start = studio_nearestBeat(sh, Math.max(0, Math.min(from, sh.seconds - bar)));
    mk.end = Math.min(sh.seconds, mk.start + bars * bar);
  }
  studio_el('studio-mk-drop').disabled = !sh.drop;
  studio_mkDraw();
}

/* What the dialog's player plays: the chosen part, or the whole song while
   AutoStream is choosing. Letting it choose used to hide the player with the
   part controls, so the song could not be heard at all. */
function studio_mkSpan() {
  const sh = studio.songShape, mk = studio.mk;
  if (mk.mode === 'part' || !sh) return {start: mk.start, end: mk.end};
  return {start: 0, end: sh.seconds};
}

function studio_mkDraw() {
  const sh = studio.songShape, mk = studio.mk;
  const choosing = mk.mode === 'part';
  studio_show('studio-mk-partctl', choosing);
  document.querySelectorAll('#studio-mk-part [data-act="studio-mk-mode"]').forEach(x =>
    x.classList.toggle('is-active', x.getAttribute('data-mode') === mk.mode));
  if (!sh) return;
  const span = studio_mkSpan();
  if (!choosing) {
    studio_el('studio-mk-facts').textContent = 'AutoStream picks the part when it plans the reel. ' +
      'The player above plays the whole song.';
  } else {
    const len = mk.end - mk.start, bars = Math.round(len / studio_mkBar());
    studio_el('studio-mk-start').textContent = studio_secs(mk.start);
    studio_el('studio-mk-end').textContent = studio_secs(mk.end);
    studio_el('studio-mk-facts').textContent = studio_dur(len) + ' · ' + bars + (bars === 1 ? ' bar' : ' bars') +
      '. Every clip you chose goes in unless the part is full. If they are short of it, each kill gets a ' +
      'longer run-up, as far as its clip has footage (never over 8 s); if that is still not enough, the reel ends early.';
  }
  const c = studio_sgCanvas('studio-mk-wave', 70);
  if (!c || !sh.peaks) return;
  const {ctx, W, H} = c, n = sh.peaks.length, X = t => t / sh.seconds * W, mid = H / 2;
  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue('--accent').trim() || '#5aa9ff';
  const warn = css.getPropertyValue('--warn').trim() || '#e3b341';
  ctx.fillStyle = accent;
  for (let x = 0; x < W; x++) {
    const k = Math.min(n - 1, Math.floor(x / W * n));
    const amp = sh.peaks[k] * (mid - 2);
    ctx.globalAlpha = (x >= X(span.start) && x <= X(span.end)) ? 1 : 0.3;
    ctx.fillRect(x, mid - amp, 1, amp * 2);
  }
  if (choosing) {
    ctx.globalAlpha = 0.18;
    ctx.fillRect(X(mk.start), 0, X(mk.end) - X(mk.start), H);
    ctx.globalAlpha = 1;
    ctx.fillRect(X(mk.start) - 2, 0, 4, H); ctx.fillRect(X(mk.end) - 2, 0, 4, H);
  }
  ctx.globalAlpha = 1;
  if (sh.drop) { ctx.fillStyle = warn; ctx.fillRect(X(sh.drop) - 1, 0, 2, H); }
  const a = studio_el('studio-mk-audio');
  if (a && a.getAttribute('data-song') === studio.song && (!a.paused || a.currentTime > 0)) {
    ctx.fillStyle = '#ff5c5c'; ctx.fillRect(X(a.currentTime) - 1, 0, 2, H);
  }
  studio_mkClock();
}

function studio_mkNudge(what, how) {
  const sh = studio.songShape, mk = studio.mk;
  if (!sh) return;
  const bar = studio_mkBar(), step = how === 'bar' ? bar : -bar;
  mk.touched = true;
  if (what === 'start') {
    const len = mk.end - mk.start;
    mk.start = Math.max(0, Math.min(sh.seconds - bar, mk.start + step));
    mk.end = Math.min(sh.seconds, mk.start + len);
  } else {
    mk.end = Math.max(mk.start + bar, Math.min(sh.seconds, mk.end + step));
  }
  studio_mkDraw();
}

function studio_mkPreset(which) {
  const sh = studio.songShape, mk = studio.mk;
  if (!sh) return;
  const bar = studio_mkBar(), len = mk.end - mk.start;
  mk.touched = true;
  if (which === 'whole') {
    mk.start = (sh.beats && sh.beats[0]) || 0;
    mk.end = sh.seconds;
  } else if (which === 'drop' && sh.drop) {
    const lead = Math.min(8 * bar, sh.drop, Math.max(bar, len / 3));
    mk.start = Math.max(0, studio_nearestBeat(sh, sh.drop - lead));
    mk.end = Math.min(sh.seconds, mk.start + len);
  } else {
    mk.start = studio_nearestBeat(sh, Math.max(0, Math.min(sh.drums_in || 0, sh.seconds - bar)));
    mk.end = Math.min(sh.seconds, mk.start + len);
  }
  studio_mkDraw();
}

/* The part's player. The song is loaded on first use; a seek asked for before the
   browser knows the song's length is held and applied once it does, because a
   seek made earlier is silently dropped and playback starts from 0:00. */
function studio_mkLoad() {
  const a = studio_el('studio-mk-audio');
  if (!studio.song || !a) return null;
  if (a.getAttribute('data-song') !== studio.song) {
    a.src = studio_media('/api/reel/audio', studio.song);
    a.setAttribute('data-song', studio.song);
  }
  return a;
}

function studio_mkSeek(t) {
  const a = studio_mkLoad(), mk = studio.mk, span = studio_mkSpan();
  if (!a) return;
  t = Math.max(span.start, Math.min(span.end, t));
  if (a.readyState >= 1) a.currentTime = t; else mk.seekTo = t;
  studio_mkDraw();
}

function studio_mkPlay() {
  const a = studio_mkLoad(), mk = studio.mk;
  if (!a) return;
  if (!a.paused) { a.pause(); return; }
  const at = a.readyState >= 1 ? a.currentTime : (mk.seekTo == null ? -1 : mk.seekTo);
  const span = studio_mkSpan();
  if (at < span.start - 0.05 || at >= span.end - 0.05) studio_mkSeek(span.start);
  a.play().catch(() => toast('The song could not be played.', 'warn'));
}

function studio_mkSkip(d) {
  const a = studio_mkLoad();
  if (!a) return;
  const now = a.readyState >= 1 ? a.currentTime : (studio.mk.seekTo == null ? studio_mkSpan().start : studio.mk.seekTo);
  studio_mkSeek(now + d);
}

/* Where playback is, inside the part: the slider, the clock and the playhead. */
function studio_mkClock() {
  const a = studio_el('studio-mk-audio'), mk = studio.mk, span = studio_mkSpan();
  const len = Math.max(0, span.end - span.start);
  const ours = a && a.getAttribute('data-song') === studio.song;
  const t = ours ? (a.readyState >= 1 ? a.currentTime : (mk.seekTo == null ? span.start : mk.seekTo)) : span.start;
  const pos = Math.max(0, Math.min(len, t - span.start));
  const seek = studio_el('studio-mk-seek');
  if (seek && document.activeElement !== seek) seek.value = String(len ? Math.round(pos / len * 1000) : 0);
  const clock = studio_el('studio-mk-clock');
  if (clock) clock.textContent = studio_secs(pos).replace(/(\.\d)\d$/, '$1') + ' / ' + studio_secs(len).replace(/(\.\d)\d$/, '$1');
  const btn = studio_el('studio-mk-play');
  if (btn) {
    const playing = ours && !a.paused;
    btn.textContent = playing ? 'Pause' : 'Play';
    btn.setAttribute('aria-label', playing ? 'Pause the part' : 'Play the part');
  }
}

function studio_mkAudio(e) {
  const a = studio_el('studio-mk-audio'), mk = studio.mk;
  if (!a) return;
  if (e.type === 'loadedmetadata' && mk.seekTo != null) { a.currentTime = mk.seekTo; mk.seekTo = null; }
  const span = studio_mkSpan();
  if (e.type === 'timeupdate' && !a.paused && a.currentTime >= span.end - 0.02) {
    if (studio_el('studio-mk-loop').checked) a.currentTime = span.start;
    else { a.pause(); a.currentTime = span.start; }
  }
  if (e.type === 'play' && !mk.ticking) { mk.ticking = true; requestAnimationFrame(studio_mkTick); }
  studio_mkDraw();
}

/* Smooth playhead while playing; timeupdate alone moves it four times a second. */
function studio_mkTick() {
  const a = studio_el('studio-mk-audio'), mk = studio.mk;
  if (!a || a.paused || studio_el('studio-make-scrim').classList.contains('hide')) { mk.ticking = false; return; }
  if (a.currentTime >= studio_mkSpan().end - 0.02) studio_mkAudio({type: 'timeupdate'});
  studio_mkDraw();
  requestAnimationFrame(studio_mkTick);
}

function studio_mkSeekInput() {
  const span = studio_mkSpan(), seek = studio_el('studio-mk-seek');
  studio_mkSeek(span.start + Number(seek.value) / 1000 * (span.end - span.start));
}

/* ------------------------------------------------------------ a song from a YouTube link */

function studio_ytOpen(target) {
  const yt = studio.yt;
  yt.target = target === 'song' ? 'song' : 'make';
  if (!yt.running) {
    studio_el('studio-yt-url').value = '';
    studio_show('studio-yt-progress', false);
    studio_ytError('');
    studio_el('studio-yt-go').disabled = false;
    studio_el('studio-yt-go').textContent = 'Download';
    studio_el('studio-yt-close').textContent = 'Cancel';
  }
  studio_show('studio-yt-scrim', true);
  setTimeout(() => { const i = studio_el('studio-yt-url'); if (i && !yt.running) i.focus(); }, 30);
}

function studio_ytKey(e) {
  if (e.key === 'Enter' && !studio.yt.running) { e.preventDefault(); studio_ytGo(); }
}

function studio_ytError(msg) {
  const e = studio_el('studio-yt-error');
  e.textContent = msg || '';
  studio_show('studio-yt-error', !!msg);
}

function studio_ytBusy(on) {
  studio.yt.running = on;
  studio_el('studio-yt-go').disabled = on;
  studio_el('studio-yt-url').disabled = on;
  studio_el('studio-yt-close').textContent = on ? 'Stop download' : 'Cancel';
}

async function studio_ytGo() {
  const url = studio_el('studio-yt-url').value.trim();
  studio_ytError('');
  if (!url) { studio_ytError('Paste a YouTube link first.'); return; }
  studio_ytBusy(true);
  studio_ytShow({state: 'starting'});
  let r;
  try {
    r = await API.post('/api/studio/songfetch', {url: url});
  } catch (e) {
    studio_ytBusy(false);
    studio_show('studio-yt-progress', false);
    studio_ytError('AutoStream didn\'t answer. Make sure it is still running, then try again.');
    return;
  }
  if (!r || !r.ok) {
    studio_ytBusy(false);
    studio_show('studio-yt-progress', false);
    studio_ytError((r && r.error) || 'The download could not start.');
    return;
  }
  studio_ytShow(r.fetch);
  studio_ytPoll();
}

function studio_ytMB(n) {
  return (Number(n) || 0) >= 1048576 ? ((Number(n) || 0) / 1048576).toFixed(1) + ' MB' : Math.round((Number(n) || 0) / 1024) + ' KB';
}

function studio_ytShow(f) {
  const title = f.title ? '\u201c' + f.title + '\u201d' : 'the song';
  const meter = studio_el('studio-yt-meter'), status = studio_el('studio-yt-status');
  studio_show('studio-yt-progress', true);
  meter.classList.toggle('is-busy', f.state === 'starting' || f.state === 'reading' || f.state === 'converting' || f.state === 'analysing');
  if (f.state === 'starting' || f.state === 'reading') {
    meter.style.width = '100%';
    status.textContent = 'Reading the link…';
  } else if (f.state === 'downloading') {
    meter.style.width = Math.max(2, Math.min(100, f.percent || 0)) + '%';
    const parts = ['Downloading ' + title];
    if (f.total_bytes) parts.push(studio_ytMB(f.done_bytes) + ' of ' + studio_ytMB(f.total_bytes), Math.round(f.percent || 0) + '%');
    if (f.eta != null && f.eta > 0) parts.push(Math.round(f.eta) + ' s left');
    status.textContent = parts.join(' · ');
  } else if (f.state === 'converting') {
    meter.style.width = '100%';
    status.textContent = 'Converting the audio of ' + title + '…';
  } else if (f.state === 'analysing') {
    meter.style.width = '100%';
    status.textContent = 'Finding the beat in ' + title + '…';
  } else if (f.state === 'done') {
    meter.style.width = '100%';
    status.textContent = (f.reused ? 'Already downloaded: ' : 'Downloaded ') + title + '.';
  } else if (f.state === 'cancelled') {
    meter.style.width = '0%';
    status.textContent = 'Download stopped.';
  } else if (f.state === 'failed') {
    studio_show('studio-yt-progress', false);
  }
}

async function studio_ytPoll() {
  const yt = studio.yt;
  clearTimeout(yt.timer);
  let r;
  try {
    r = await API.get('/api/studio/songfetch/status');
  } catch (e) {
    studio_ytBusy(false);
    studio_ytError('AutoStream stopped answering during the download. Make sure it is still running, then try again.');
    return;
  }
  const f = (r && r.fetch) || {state: 'idle'};
  studio_ytShow(f);
  if (f.state === 'starting' || f.state === 'reading' || f.state === 'downloading' || f.state === 'converting') {
    yt.timer = setTimeout(studio_ytPoll, 350);
    return;
  }
  if (f.state === 'failed') {
    studio_ytBusy(false);
    studio_ytError(f.error || 'The download failed.');
    return;
  }
  if (f.state !== 'done') {
    studio_ytBusy(false);
    return;
  }
  studio_ytShow(Object.assign({}, f, {state: 'analysing'}));
  const ok = yt.target === 'song' ? await studio_sgUseSong(f.path) : await studio_useSong(f.path, f.title || '');
  studio_ytBusy(false);
  if (!ok) {
    studio_show('studio-yt-progress', false);
    studio_ytError('The song downloaded, but its beat couldn\'t be read. Try another upload of the song.');
    return;
  }
  studio_show('studio-yt-scrim', false);
  toast((f.reused ? 'Using ' : 'Downloaded ') + (f.title || 'the song') + '.', 'ok');
}

async function studio_ytClose() {
  if (studio.yt.running) {
    await API.post('/api/studio/songfetch/cancel', {}).catch(() => null);
    return;                       /* the poll reports "Download stopped" and frees the dialog */
  }
  clearTimeout(studio.yt.timer);
  studio_show('studio-yt-scrim', false);
}

function studio_mkPointer(e) {
  const sh = studio.songShape, mk = studio.mk, cv = studio_el('studio-mk-wave');
  if (!sh || !cv) return;
  if (e.type === 'pointerdown' && mk.mode !== 'part') {
    /* Nothing to drag while AutoStream chooses; a click is a seek. */
    const r = cv.getBoundingClientRect();
    studio_mkSeek((e.clientX - r.left) / r.width * sh.seconds);
    return;
  }
  if (e.type === 'pointerdown') {
    const r = cv.getBoundingClientRect();
    const t = (e.clientX - r.left) / r.width * sh.seconds;
    const edge = 6 / r.width * sh.seconds;
    const kind = Math.abs(t - mk.start) < edge ? 'start' : Math.abs(t - mk.end) < edge ? 'end'
      : (t > mk.start && t < mk.end) ? 'move' : 'jump';
    mk.touched = true;
    if (kind === 'jump') {
      const len = mk.end - mk.start;
      mk.start = studio_nearestBeat(sh, Math.max(0, Math.min(sh.seconds - len, t - len / 2)));
      mk.end = Math.min(sh.seconds, mk.start + len);
      studio_mkDraw();
      return;
    }
    mk.drag = {kind: kind, x0: e.clientX, start: mk.start, end: mk.end, w: r.width, pointer: e.pointerId};
    try { cv.setPointerCapture(e.pointerId); } catch (err) { /* fine without */ }
    e.preventDefault();
    return;
  }
  const g = mk.drag;
  if (!g || e.pointerId !== g.pointer) return;
  const dt = (e.clientX - g.x0) / g.w * sh.seconds;
  if (e.type === 'pointermove') {
    if (g.kind === 'start') mk.start = Math.max(0, Math.min(mk.end - 1, g.start + dt));
    else if (g.kind === 'end') mk.end = Math.max(mk.start + 1, Math.min(sh.seconds, g.end + dt));
    else {
      const len = g.end - g.start;
      mk.start = Math.max(0, Math.min(sh.seconds - len, g.start + dt));
      mk.end = mk.start + len;
    }
  } else {
    mk.drag = null;
    /* Dropped on a beat, so the reel's cuts are the song's beats. */
    const len = mk.end - mk.start;
    if (g.kind !== 'end') {
      mk.start = studio_nearestBeat(sh, mk.start);
      if (g.kind === 'move') mk.end = Math.min(sh.seconds, mk.start + len);
    } else {
      mk.end = Math.max(mk.start + studio_mkBar() / 4, studio_nearestBeat(sh, mk.end));
    }
  }
  studio_mkDraw();
}

/* =======================================================================
   THE PARTS BIN
   A reel is one pick from each drawer. Each pick is shown by a two-second
   example cut from this machine's own clips (clips/examples.py), so a choice
   is made by watching rather than by reading "k04 Freeze" in a list. The
   examples play only while they are on screen: sixty looping videos at once
   made the page stutter.
   ======================================================================= */

const BIN_DRAWERS = {intro: 'Opening', transition: 'Between shots', kill: 'On the kill',
  hero: 'The big moment', camera: 'Camera', speed: 'Time', grade: 'Colour',
  overlay: 'Overlay', outro: 'Ending'};

function studio_binName(kind) { return BIN_DRAWERS[kind] || kind; }

/* Play what is on screen, pause what is not. */
function studio_binWatch() {
  if (studio.binObs) studio.binObs.disconnect();
  if (!('IntersectionObserver' in window)) return;
  studio.binObs = new IntersectionObserver(function (es) {
    es.forEach(function (e) {
      const v = e.target;
      if (e.isIntersecting) { const q = v.play(); if (q && q.catch) q.catch(function () {}); }
      else v.pause();
    });
  }, {rootMargin: '150px'});
  document.querySelectorAll('.bin-shot video').forEach(function (v) { studio.binObs.observe(v); });
}

function studio_binShot(id) {
  const ex = (studio.examples && studio.examples.examples || {})[id];
  const tag = '<span class="bin-tag">' + esc(id) + '</span>';
  if (!ex) {
    const none = studio.examples && (studio.examples.nothing || []).indexOf(id) >= 0;
    return '<span class="bin-shot">' + tag + '<span class="bin-none">' +
      (none ? 'nothing added' : 'no example yet') + '</span></span>';
  }
  const src = '/api/studio/example?k=' + encodeURIComponent(SHELL_K) +
    '&id=' + encodeURIComponent(id) + '&v=' + (ex.when || 0);
  const media = ex.type === 'image/gif'
    ? '<img src="' + src + '" alt="" loading="lazy">'
    : '<video src="' + src + '" muted loop playsinline preload="none" aria-hidden="true" data-knobs="off"></video>';
  const sample = ex.stock ? '<span class="bin-sample" title="Shown on sample footage until it is cut from your own clips">sample</span>' : '';
  return '<span class="bin-shot">' + media + tag + sample + '</span>';
}

function studio_binCard(p, on, act) {
  const fav = studio.favParts.indexOf(p.id) >= 0;
  return '<button type="button" class="bin-card' + (on ? ' is-on' : '') +
    '" data-act="' + act + '" data-kind="' + esc(p.kind) + '" data-part="' + esc(p.id) + '"' +
    ' aria-pressed="' + (on ? 'true' : 'false') + '">' + studio_binShot(p.id) +
    '<span class="bin-star' + (fav ? ' is-on' : '') + '" role="button" tabindex="0"' +
    ' data-act="studio-bin-fav" data-part="' + esc(p.id) + '"' +
    ' aria-pressed="' + (fav ? 'true' : 'false') + '"' +
    ' title="' + (fav ? 'Remove from favourites' : 'Keep in favourites') + '">' +
    (fav ? '★' : '☆') + '</span>' +
    '<span class="bin-meat"><span class="bin-name">' + esc(p.label || p.id) + '</span>' +
    '<span class="bin-blurb">' + esc(p.blurb || '') + '</span></span></button>';
}

/* FAVOURITES FIRST, and on their own when the filter is on. With a hundred
   cards in a drawer the ones a person keeps coming back to are the only ones
   they will find twice, so they float to the top of their own drawer rather
   than into a tenth drawer of their own. */
/* Four dials, each a step either side of centre. Buttons rather than sliders:
   a slider invites hunting for a number, and the honest answer to "how much
   longer" is one notch at a time with the result in front of you. */
const SHAPE_DIALS = [
  {k: 'length',  name: 'Length',  down: 'Shorter', up: 'Longer',  lo: 0.55, hi: 1.8},
  {k: 'pace',    name: 'Pace',    down: 'Slower',  up: 'Faster',  lo: 0.55, hi: 1.8},
  {k: 'effects', name: 'Effects', down: 'Fewer',   up: 'More',    lo: 0.0,  hi: 2.0},
  {k: 'flash',   name: 'Flash',   down: 'Less',    up: 'More',    lo: 0.0,  hi: 2.5}
];

function studio_shapeDraw() {
  const host = studio_el('bin-shape');
  if (!host) return;
  host.innerHTML = SHAPE_DIALS.map(function (d) {
    const v = studio.shaping[d.k];
    const off = Math.abs(v - 1) > 0.01;
    return '<span class="shape-dial' + (off ? ' is-on' : '') + '">' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-shape" ' +
      'data-dial="' + d.k + '" data-by="-1" title="' + esc(d.down) + '"' +
      (v <= d.lo + 0.001 ? ' disabled' : '') + '>&minus;</button>' +
      '<b>' + esc(d.name) + (off ? '<i>' + (v > 1 ? d.up : d.down) + '</i>' : '') + '</b>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-shape" ' +
      'data-dial="' + d.k + '" data-by="1" title="' + esc(d.up) + '"' +
      (v >= d.hi - 0.001 ? ' disabled' : '') + '>+</button></span>';
  }).join('') +
  '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-shape-reset"' +
  (studio_shapeIsCentred() ? ' disabled' : '') + '>Reset</button>';
}

const ARRANGES = [
  {k: 'build', name: 'Build up', why: 'A strong opener, the best one two thirds in, a strong close.'},
  {k: 'time', name: 'As it happened', why: 'The fights in the order you played them.'},
  {k: 'best', name: 'Best first', why: 'The strongest moment opens the reel.'},
  {k: 'shuffle', name: 'Shuffle', why: 'A fresh draw. Press again for another.'}
];

function studio_arrangeDraw() {
  const host = studio_el('bin-arrange');
  if (!host) return;
  host.innerHTML = ARRANGES.map(function (a) {
    const on = studio.arrange === a.k;
    return '<button type="button" class="btn btn-sm' + (on ? ' is-active' : '') +
      '" data-act="studio-arrange" data-how="' + a.k + '" aria-pressed="' + on + '"' +
      ' title="' + esc(a.why) + '">' + esc(a.name) + '</button>';
  }).join('');
}

function studio_arrangePick(how) {
  // Pressing Shuffle again is how you ask for another draw, so it re-rolls
  // rather than doing nothing.
  // Pressing Shuffle again is how you ask for another draw, so it always
  // re-rolls rather than doing nothing the second time.
  if (how === 'shuffle') studio.shuffleSeed = Math.floor(Math.random() * 2147483000) + 1;
  studio.arrange = how;
  studio_arrangeDraw();
  toast('Make the reel again to see it.');
}

/* PINNING A CLIP TO A SLOT. Moving a shot with the arrows moves it once; a pin
   survives every rebuild, every style change and every new draw, which is what
   somebody means by "this one opens it". */
const PIN_SLOTS = [
  {k: 'open', name: 'Opens', done: 'Opens the reel'},
  {k: 'climax', name: 'Climax', done: 'Is the climax'},
  {k: 'close', name: 'Closes', done: 'Closes the reel'}
];

function studio_pinRow(clip) {
  const mine = PIN_SLOTS.filter(function (x) { return studio.pins[x.k] === clip; });
  return '<div class="field-inline studio-pins">' +
    '<span class="field-label">Pin</span>' +
    PIN_SLOTS.map(function (x) {
      const on = studio.pins[x.k] === clip;
      const taken = studio.pins[x.k] && !on;
      return '<button type="button" class="btn btn-ghost btn-sm' + (on ? ' is-active' : '') +
        '" data-act="studio-pin" data-slot="' + x.k + '" data-clip="' + esc(clip) + '"' +
        ' aria-pressed="' + on + '" title="' + (on ? 'Unpin' : taken ? 'Takes the slot from another clip' : x.done) +
        '">' + esc(x.name) + '</button>';
    }).join('') +
    (mine.length ? '<span class="muted">' + esc(mine[0].done) + ' on every rebuild.</span>' : '') +
    '</div>';
}

function studio_pin(slot, clip) {
  if (!slot || !clip) return;
  // One clip per slot and one slot per clip: pinning the opener to a clip that
  // was already the closer would otherwise ask for it in two places at once.
  if (studio.pins[slot] === clip) delete studio.pins[slot];
  else {
    Object.keys(studio.pins).forEach(function (k) {
      if (studio.pins[k] === clip) delete studio.pins[k];
    });
    studio.pins[slot] = clip;
  }
  studio_drawInspector();
  toast('Make the reel again to move it.');
}

function studio_shapeIsCentred() {
  return SHAPE_DIALS.every(function (d) { return Math.abs(studio.shaping[d.k] - 1) < 0.01; });
}

function studio_shapeNudge(key, by) {
  const d = SHAPE_DIALS.filter(function (x) { return x.k === key; })[0];
  if (!d) return;
  // A fifth either way: small enough that a nudge is a nudge, big enough that
  // the reel that comes back is visibly a different one.
  const v = Math.round((studio.shaping[key] + by * 0.2) * 100) / 100;
  studio.shaping[key] = Math.max(d.lo, Math.min(d.hi, v));
  studio_shapeDraw();
  toast('Make the reel again to hear it.');
}

function studio_shapeReset() {
  SHAPE_DIALS.forEach(function (d) { studio.shaping[d.k] = 1; });
  studio_shapeDraw();
}

function studio_binSort(parts) {
  const fav = studio.favParts;
  if (studio.favOnly) return parts.filter(function (p) { return fav.indexOf(p.id) >= 0; });
  return parts.slice().sort(function (a, b) {
    return (fav.indexOf(b.id) >= 0) - (fav.indexOf(a.id) >= 0);
  });
}

async function studio_binFav(id) {
  const on = studio.favParts.indexOf(id) < 0;
  const r = await API.post('/api/studio/favourite-part', {part: id, on: on});
  if (!r || !r.ok) { toast((r && r.error) || 'That part could not be starred.'); return; }
  studio.favParts = r.favourite_parts || [];
  studio_binDraw();
}

function studio_binFavOnly() {
  studio.favOnly = !studio.favOnly;
  studio_binDraw();
}

function studio_binDraw() {
  const box = studio_el('bin-drawers');
  if (!box || !studio.catalog) return;
  const drawers = studio.catalog.drawers || Object.keys(BIN_DRAWERS);
  const picks = studio_template();
  box.innerHTML = drawers.map(function (kind) {
    const all = studio_parts(kind);
    const parts = studio_binSort(all);
    if (!parts.length) return '';
    const kept = all.filter(function (x) { return studio.favParts.indexOf(x.id) >= 0; }).length;
    return '<section class="bin-sec bin-drawer">' +
      '<div class="bin-sec-head"><h2>' + esc(studio_binName(kind)) + '</h2>' +
      '<span class="count">' + parts.length + ' to pick from' +
      (kept && !studio.favOnly ? ' · ' + kept + ' kept' : '') + '</span></div>' +
      '<div class="bin-grid">' +
      parts.map(function (p) { return studio_binCard(p, picks[kind] === p.id, 'studio-bin-pick'); }).join('') +
      '</div></section>';
  }).join('');
  const ex = studio.examples || {};
  const list = ex.examples || {};
  const own = Object.keys(list).filter(k => !list[k].stock).length;
  const stock = Object.keys(list).length - own;
  const miss = (ex.missing || []).length;
  const c = studio_el('bin-count');
  if (c) c.textContent = own + ' of ' + (own + miss) + ' cut from your own clips' +
    (stock ? ' · ' + stock + ' shown on sample footage' : '');
  const b = studio_el('bin-build');
  if (b) {
    b.disabled = !miss;
    b.textContent = miss ? (stock ? 'Cut ' + miss + ' from your own clips' : 'Cut the ' + miss + ' missing example' + (miss === 1 ? '' : 's'))
      : 'Every part has an example';
  }
  const fo = studio_el('bin-favonly');
  if (fo) {
    fo.setAttribute('aria-pressed', studio.favOnly ? 'true' : 'false');
    fo.classList.toggle('is-active', !!studio.favOnly);
    fo.disabled = !studio.favParts.length && !studio.favOnly;
  }
  studio_shapeDraw();
  studio_arrangeDraw();
  studio_binSlots();
  studio_binWatch();
}

/* HOW MANY REELS THESE DRAWERS MAKE: the point of picking. Four drawers of
   ten parts each is ten thousand reels, not five styles. */
function studio_binSlots() {
  const box = studio_el('bin-slots');
  if (!box || !studio.catalog) return;
  const drawers = studio.catalog.drawers || [];
  if (!studio.binOn) {
    studio.binOn = {};
    drawers.forEach(function (k) { studio.binOn[k] = true; });
  }
  box.innerHTML = drawers.map(function (k) {
    return '<label class="bin-slot"><input type="checkbox" data-act="studio-bin-slot" data-kind="' +
      esc(k) + '"' + (studio.binOn[k] ? ' checked' : '') + '> ' + esc(studio_binName(k)) +
      ' <b>' + studio_parts(k).length + '</b></label>';
  }).join('');
  let total = 1, on = 0;
  drawers.forEach(function (k) {
    if (studio.binOn[k]) { total *= Math.max(1, studio_parts(k).length); on++; }
  });
  const big = studio_el('bin-total');
  if (big && big.firstChild) big.firstChild.nodeValue = on ? total.toLocaleString() : '0';
  const note = studio_el('bin-total-note');
  if (note) {
    note.textContent = on ? 'reels from ' + on + ' drawer' + (on === 1 ? '' : 's') + ', one pick each'
      : 'tick a drawer to count it';
  }
}

async function studio_binLoad(force) {
  if (studio.examples && !force) { studio_binDraw(); return; }
  const r = await API.get('/api/studio/examples');
  if (!r || !r.ok) return;
  studio.examples = r;
  studio_binDraw();
  if (r.build && r.build.state === 'running') studio_binPoll();
}

async function studio_binBuild() {
  const msg = studio_el('bin-build-msg');
  if (msg) msg.textContent = 'Starting…';
  const r = await API.post('/api/studio/examples/build', {});
  if (!r || !r.ok) { if (msg) msg.textContent = (r && r.error) || 'Could not start.'; return; }
  const b = studio_el('bin-build');
  if (b) b.disabled = true;
  studio_show('bin-build-stop', true);
  studio_binPoll();
}

/* A few hundred examples is most of an hour of full CPU, and there was no way
   to end it short of quitting. It stops after the part it is cutting. */
async function studio_binStop() {
  const s = studio_el('bin-build-stop');
  if (s) s.disabled = true;
  const r = await API.post('/api/studio/examples/cancel', {});
  const msg = studio_el('bin-build-msg');
  if (msg && r && r.build) msg.textContent = r.build.message || '';
}

function studio_binPoll() {
  if (studio.binTimer) return;
  studio.binTimer = setInterval(async function () {
    const r = await API.get('/api/studio/examples');
    if (!r || !r.ok) return;
    const b = r.build || {};
    const msg = studio_el('bin-build-msg');
    if (msg) msg.textContent = b.message || '';
    studio_show('bin-build-stop', b.state === 'running');
    if (b.state === 'running') return;
    const s = studio_el('bin-build-stop');
    if (s) s.disabled = false;
    clearInterval(studio.binTimer);
    studio.binTimer = null;
    studio.examples = r;
    studio_binDraw();
    studio_hand();
  }, 1500);
}

/* ---------------------------------------------------------------- template */

/* The picks in force: what the style chose, plus anything dealt or clicked. */
function studio_template() {
  const cat = studio.catalog;
  const st = cat && (cat.styles || []).find(function (s) { return s.key === studio.style; });
  return Object.assign({}, (st && st.picks) || {}, studio.picks || {});
}

function studio_hand() {
  const box = studio_el('studio-hand');
  if (!box || !studio.catalog) return;
  const picks = studio_template();
  const drawers = studio.catalog.drawers || [];
  box.innerHTML = drawers.map(function (kind) {
    const p = studio_part(picks[kind]) || {id: picks[kind] || '-', label: 'Nothing', kind: kind, blurb: ''};
    return '<div class="bin-slotcard"><span class="bin-drawer-label">' + esc(studio_binName(kind)) +
      '</span>' + studio_binCard(p, false, 'studio-hand-next') + '</div>';
  }).join('');
  const code = studio_el('studio-deal-code');
  if (code) {
    code.textContent = drawers.map(function (k) { return picks[k]; }).filter(Boolean).join(' · ');
  }
  studio_binWatch();
}

/* Deal: one part from each drawer, preferring ones with an example to show. */
function studio_deal() {
  const drawers = (studio.catalog && studio.catalog.drawers) || [];
  const have = (studio.examples && studio.examples.examples) || {};
  const picks = {};
  drawers.forEach(function (k) {
    const parts = studio_parts(k);
    const shown = parts.filter(function (p) { return have[p.id]; });
    const from = shown.length ? shown : parts;
    if (from.length) picks[k] = from[Math.floor(Math.random() * from.length)].id;
  });
  studio.picks = picks;
  studio_hand();
  studio_binDraw();
}

function studio_dealReset() {
  studio.picks = null;
  studio_hand();
  studio_binDraw();
}

/* Click a card in a drawer: that becomes the drawer's pick. */
function studio_binPick(kind, part) {
  studio.picks = Object.assign({}, studio_template());
  studio.picks[kind] = part;
  studio_hand();
  studio_binDraw();
}

/* Click the card in the hand: step to the next part in that drawer. */
function studio_handNext(kind) {
  const parts = studio_parts(kind);
  if (!parts.length) return;
  const now = studio_template()[kind];
  let i = -1;
  parts.forEach(function (p, j) { if (p.id === now) i = j; });
  studio_binPick(kind, parts[(i + 1) % parts.length].id);
}

/* ------------------------------------------------------------- favourites */

/* The star is drawn from studio.lib, so it flips before the round trip and is
   put back if the write fails -- the library is only re-read on Refresh. */
async function studio_setFav(clips, on) {
  if (!clips.length) return;
  const ids = {};
  clips.forEach(c => { ids[c.id] = true; c.fav = on; });
  studio.lib.fav_count = Math.max(0, (studio.lib.fav_count || 0) + (on ? clips.length : -clips.length));
  if (studio.game === 'fav' && !on) studio.selected = studio.selected.filter(id => !ids[id]);
  studio_renderLib();
  const r = await API.post('/api/studio/favourite', {paths: clips.map(c => c.path), on: on});
  if (!r || !r.ok) {
    clips.forEach(c => { c.fav = !on; });
    studio.lib.fav_count = Math.max(0, (studio.lib.fav_count || 0) + (on ? -clips.length : clips.length));
    studio_renderLib();
    toast((r && r.error) || 'Could not save that favourite.', 'warn');
  }
}

function studio_fav(id) {
  const c = studio.clipIndex[id];
  if (c) studio_setFav([c], !c.fav);
}

/* Star everything selected, or unstar it when it is all starred already. */
function studio_favLabel() {
  const b = studio_el('studio-fav-btn');
  if (!b) return;
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  const off = sel.length && sel.every(c => c.fav);
  b.textContent = (off ? '\u2606 Unfavourite' : '\u2605 Favourite') +
    (sel.length > 1 ? ' ' + sel.length : '');
}

function studio_favSelected() {
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  if (!sel.length) return;
  studio_setFav(sel, !sel.every(c => c.fav));
}

function studio_ordered() {
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  if (studio.order === 'kills') return sel.slice().sort((a, b) => (b.kill_count || 1) - (a.kill_count || 1));
  if (studio.order === 'oldest') return sel.slice().sort((a, b) => (a.when - b.when) || (a.rank - b.rank));
  return sel;
}

async function studio_build() {
  const btn = studio_el('studio-build-btn');
  btn.disabled = true;
  /* The dialog's Cancel sits beside this button and stays live while the plan
     is fetched. Pressing it bumps this counter, which is how the rest of the
     build below learns it is no longer wanted -- it used to close the dialog
     and nothing else, so the render started anyway a moment later and looked
     like a Cancel that had been ignored. */
  const gen = ++studio.buildGen;
  studio_el('studio-make-msg').textContent = studio.song ? 'Finding the beat and planning every shot…' : 'Planning every shot…';
  try {
    const body = {
      clips: studio_ordered().map(c => c.path), style: studio.style, song: studio.song,
      format: studio.fmt, name: studio_el('studio-name').value.trim(),
      /* Only what was DEALT or CLICKED. Sending the style's own picks back
         narrowed every drawer to the one part the style leads with, and a
         montage came out with the same kill effect on all six kills. */
      template: studio.picks || null,
      shaping: Object.assign({}, studio.shaping, {arrange: studio.arrange,
        pins: studio.pins, shuffle_seed: studio.shuffleSeed})
    };
    /* The whole clip, cover-fitted: the trim and the fit are the timeline
       dialog's job, and normalise clamps both anyway. What is chosen here is
       which intro and whether it is heard. */
    if (studio.mkIntro.path) {
      const got = (studio.intro.list || []).find(x => x.path === studio.mkIntro.path);
      body.intro_clip = {path: studio.mkIntro.path, start: 0,
                         end: got ? Number(got.seconds) : 0,
                         audio: !!studio.mkIntro.audio, fit: 'cover'};
    }
    if (studio.song && studio.songShape && studio.mk.mode === 'part' && studio.mk.end > studio.mk.start) {
      body.part_start = studio.mk.start;
      body.part_end = studio.mk.end;
    }
    const r = await API.post('/api/studio/plan', body);
    if (gen !== studio.buildGen) return;          /* cancelled while planning */
    if (!r || !r.ok) { studio_el('studio-make-msg').textContent = (r && r.error) || 'Could not plan that reel.'; return; }
    studio_closeModals();
    const ad = studio.adding;
    /* A rebuild renders over the reel it rebuilds rather than beside it. */
    if (ad && ad.output) r.project.output = ad.output;
    studio_setProject(r.project, r.derived, r.notes, r.song);
    studio.output = ad && ad.output ? ad.output : ''; studio.undo = [];
    /* A fresh reel has no video to differ from; a rebuild over an existing one
       has exactly one difference, and it is the whole reel. */
    studio.pending = []; studio.dirty = true; studio.failMsg = '';
    if (studio.output) studio_touched('Rebuilt from the clips');
    studio.adding = null;
    studio_renderTray();
    studio_tab('timeline');
    studio_fit();
    studio_render();
  } finally {
    btn.disabled = false;
  }
}

/* The dialog's Cancel. Closing the dialog was all it used to do, so a build
   whose plan was still in flight carried on and started rendering a moment
   later -- indistinguishable, from the page, from a Cancel that was ignored.
   Bumping the counter is what abandons it. Nothing is posted: the render has
   not been asked for yet, and the dialog is already gone by the time one has
   (studio_build closes it before it renders), so a POST from here could only
   reach an unrelated render. */
function studio_buildCancel() {
  studio.buildGen++;
  studio_closeModals();
}

/* ------------------------------------------------------------ project */

function studio_setProject(project, derived, notes, songShape) {
  studio.project = project; studio.derived = derived; studio.notes = notes || [];
  if (songShape !== undefined) studio.songShape = songShape;
  if (project.output) studio.output = project.output;
  studio_el('studio-tab-timeline').disabled = false;
  studio_el('studio-tab-song').disabled = false;
  studio_el('studio-tab-facecam').disabled = false;
  studio_el('studio-pname').value = project.name || '';
  if (studio.sel >= project.shots.length) studio.sel = project.shots.length - 1;
  studio_drawAll();
}

function studio_pushUndo(snapshot) {
  studio.undo.push(snapshot);
  if (studio.undo.length > 60) studio.undo.shift();
}

/* ------------------------------------------------- what is not rendered yet

   Three rules, and they are what make the count trustworthy enough to put on
   a button: one undo step is one unit of change here, a render clears the
   list, and an undo takes a unit back off it. When the count reaches zero the
   project is byte-for-byte the one that was rendered, so "the video matches
   your edits" is a fact and not a guess. */

/* Shots are numbered from 1 on the timeline, so they are numbered from 1 here. */
function studio_shotName(i) { return 'Shot ' + (Number(i) + 1); }

/* How long ago, roughly. "Rendered 2 days ago" is the fact that decides whether
   the video on screen can be trusted, and an exact timestamp does not say it. */
function studio_ago(when) {
  const s = Math.max(0, (Date.now() - (Number(when) || 0)) / 1000);
  if (s < 90) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return m + (m === 1 ? ' minute ago' : ' minutes ago');
  const h = Math.round(m / 60);
  if (h < 36) return h + (h === 1 ? ' hour ago' : ' hours ago');
  const d = Math.round(h / 24);
  return d + (d === 1 ? ' day ago' : ' days ago');
}

function studio_touched(label, shot) {
  studio.dirty = true;
  studio.failMsg = '';
  /* "Ready · rendered in 23 s" stops being true the moment anything is
     touched, and a verdict left sitting under a warning is how the page said
     two opposite things at once. */
  studio_state('');
  const name = label || 'An edit on the timeline';
  const at = (shot === undefined || shot === null) ? -1 : shot;
  /* A slider fires per step and a nudge button per press: the same edit, made
     again, is one line with a count and not twenty lines. */
  const same = studio.pending.filter(x => x.label === name && x.shot === at)[0];
  if (same) {
    same.n++;
    studio.pending.splice(studio.pending.indexOf(same), 1);
    studio.pending.push(same);
    return;
  }
  studio.pending.push({label: name, shot: at, n: 1});
}

/* Rendered: the video and the project are the same thing again. */
function studio_settled() { studio.dirty = false; studio.pending = []; studio.failMsg = ''; }

/* Removing or reordering shots renumbers them, so every shot index already on
   the list now points at the wrong shot. The edits still count; they just stop
   claiming to know which shot they were. */
function studio_forgetShots() { studio.pending.forEach(x => { x.shot = -1; }); }

function studio_untouched() {
  const last = studio.pending[studio.pending.length - 1];
  if (last && last.n > 1) { last.n--; return; }
  if (last) {
    studio.pending.pop();
    studio.dirty = studio.pending.length > 0 || !studio.output;
    return;
  }
  /* Undone past the last render: the project is behind the video now, which
     is still a difference, and still needs rendering to resolve. */
  studio_touched('Undone past the last render');
}

/* `label` is what the card will call this edit, and `shot` the shot it happened
   to, so the timeline can mark it. Both optional -- an unlabelled edit still
   counts, it just reads as a generic one. */
function studio_change(mutate, label, shot) {
  if (!studio.project) return;
  studio_pushUndo(JSON.stringify(studio.project));
  studio.gen++;
  mutate(studio.project);
  studio_touched(label, shot);
  studio_localDerive();
  studio_drawAll();
  clearTimeout(studio.checkTimer);
  studio.checkTimer = setTimeout(studio_check, 250);
}

async function studio_check() {
  const n = ++studio.checking;
  const gen = studio.gen;
  const r = await API.post('/api/studio/check', {project: studio.project});
  /* An answer about an older project must never replace a newer one: an edit
     made while this was in flight would silently disappear. */
  if (n !== studio.checking || gen !== studio.gen) return;
  if (!r || !r.ok) { toast((r && r.error) || 'That edit could not be applied.', 'warn'); return; }
  studio.project = r.project; studio.derived = r.derived; studio.notes = r.notes || [];
  studio_drawAll();
}

function studio_undo() {
  const last = studio.undo.pop();
  if (!last) return;
  studio.gen++;
  studio.project = JSON.parse(last);
  studio_untouched();
  studio_localDerive(); studio_drawAll();
  studio_check();
}

/* A quick estimate while dragging. The server's answer replaces it. */
function studio_localDerive() {
  const p = studio.project, d = studio.derived;
  if (!p) return;
  let t = 0;
  const rows = p.shots.map((s, i) => {
    const old = (d && d.shots[i]) || {};
    const row = {index: i, start: t, end: t + s.duration, kill_reel: t + s.pre,
                 kills_reel: [t + s.pre], pieces: old.pieces || [[0, s.duration, 1]]};
    t += s.duration;
    return row;
  });
  const beat = p.beat || 0.5;
  const beats = [];
  for (let b = 0; b <= t + 1e-6; b += beat) beats.push(b);
  /* Carried through, not recomputed: neither follows from the shots, and a
     drag that dropped them made the intro band blink off the timeline until
     the server answered. */
  studio.derived = {length: t, shots: rows, kills: rows.map(r => r.kill_reel), beats: beats, beat: beat,
                    bpm: 60 / beat, selection: (d && d.selection) || [],
                    lead_in: (d && d.lead_in) || 0, intro_clip: (d && d.intro_clip) || null};
}

function studio_snapTo(t) {
  const beat = (studio.project && studio.project.beat) || 0.5;
  return studio_el('studio-snap').checked ? Math.round(t / beat) * beat : Math.round(t * 60) / 60;
}

/* ------------------------------------------------------------ rendering */

async function studio_render() {
  if (!studio.project) return;
  /* A check still waiting or in flight describes the project before the
     server allocates its output; letting it land afterwards would wipe that. */
  clearTimeout(studio.checkTimer);
  studio.gen++;
  /* The previous render is old news once a new one is asked for: a poll that
     lands in between must not say "Ready" about the reel being replaced. */
  studio.seenJob = studio.jobId; studio.watching = -1;
  studio.project.name = studio_el('studio-pname').value.trim() || studio.project.name;
  /* The list of what is pending belongs to the project being sent. Clearing it
     here rather than on the job's reply means the card stops claiming, for the
     length of the render, that those edits are still missing. */
  const sent = studio.pending.slice();
  studio_settled();
  /* Said before the round trip, not after it: the gap between pressing the
     button and the first poll is exactly where the page used to look as if
     nothing had happened. */
  studio_busy(true);
  studio_el('studio-meter').style.width = '0%';
  studio_state('Starting the render…');
  studio_drawRenderCard();
  const r = await API.post('/api/studio/render', {project: studio.project});
  if (!r || !r.ok) {
    studio_busy(false);
    studio.pending = sent; studio.dirty = sent.length > 0;
    studio_state((r && r.error) || 'Could not start the render.', true);
    studio_drawRenderCard();
    return;
  }
  studio.project = r.project; studio.derived = r.derived; studio.notes = r.notes || [];
  studio.output = r.output;
  studio.jobId = r.job || 0;
  studio_drawAll();
  studio_poll();
}

function studio_state(msg, bad) {
  const el = studio_el('studio-state');
  if (!el) return;
  el.textContent = msg || '';
  el.classList.toggle('is-bad', !!bad);
  if (bad) studio.failMsg = msg || '';
}

async function studio_poll() {
  clearTimeout(studio.polling);
  /* One loop. Render and every visit to the page start a poll; without this
     each left its predecessor running, and they multiplied. */
  const mine = ++studio.pollTok;
  const j = await API.get('/api/studio/job');
  if (mine !== studio.pollTok) return;
  if (!j || j.state === 'idle') { studio_busy(false); studio_drawRenderCard(); return; }
  const running = j.state === 'running' || j.state === 'queued';
  studio_busy(running);
  studio_el('studio-meter').style.width = (running ? j.percent : 100) + '%';
  if (running) {
    studio.watching = j.id;       /* seen running on this page: its finish is news */
    studio.jobMsg = j.message + (j.cached ? ' · ' + j.cached + ' shots unchanged' : '');
    studio_state(studio.jobMsg);
    studio_drawRenderCard();
    studio.polling = setTimeout(studio_poll, 700);
    return;
  }
  studio.jobMsg = '';
  /* A finished job is news once, and only to a page that started it or watched
     it run. The server keeps the last job for as long as it runs, so without
     this every visit to the page announced the same reel again. */
  const news = j.id !== studio.seenJob && (j.id === studio.jobId || j.id === studio.watching);
  studio.seenJob = j.id;
  if (!news) { studio_drawRenderCard(); return; }
  if (j.state === 'done') {
    const same = studio.project && j.output === studio.project.output;
    studio.renderNote = 'took ' + j.elapsed + ' s' + (j.cached ? ' · ' + j.cached + ' shots reused' : '');
    studio_state('Ready · rendered in ' + j.elapsed + ' s' + (j.cached ? ' · ' + j.cached + ' shots reused' : ''));
    if (same) {
      /* Not studio_settled(): an edit made while the render ran is a real
         difference from the video that has just arrived, and saying otherwise
         would lose it. studio_render() already cleared what it sent. */
      studio.output = j.output; studio.renderedAt = Date.now();
      studio_loadVideo();
    }
    toast('Reel ready.', 'ok');
    studio.loadedAt = 0;
  } else if (j.state === 'failed') {
    /* A failed render leaves the edits unrendered, so they go back on the list
       -- as one line, because which of them it was is no longer knowable. */
    if (!studio.pending.length && studio.output) studio_touched('The edits from the render that failed');
    studio_state(j.error || 'The render failed.', true);
  } else {
    if (!studio.pending.length && studio.output) studio_touched('The edits from the render you cancelled');
    studio_state('Cancelled.');
  }
  studio_drawRenderCard();
}

function studio_busy(on) {
  studio.rendering = !!on;
  studio_show('studio-cancel-btn', on);
  studio_el('studio-render-btn').disabled = on;
  studio_show('studio-meter-wrap', on);
}

function studio_loadVideo() {
  const v = studio_el('studio-video');
  if (!studio.output) { v.removeAttribute('src'); studio_show('studio-player-empty', true); return; }
  v.src = studio_media('/api/clips/video', studio.output, '&v=' + studio.renderedAt);
  studio_show('studio-player-empty', false);
}

function studio_drawRenderCard() {
  const p = studio.project, d = studio.derived;
  if (!p || !d) return;
  const st = (studio.catalog ? studio.catalog.styles : []).find(s => s.key === p.style);
  studio_el('studio-facts').textContent = studio_dur(d.length) + ' · ' + p.shots.length + ' shots · ' +
    Math.round(d.bpm) + ' BPM grid · ' + (st ? st.label : p.style) + ' · ' +
    (p.format === 'vertical' ? '9:16' : '16:9') + (p.song ? '' : ' · no song');
  studio_drawSync();
  studio_el('studio-undo-btn').disabled = !studio.undo.length;
  studio_el('studio-show-btn').disabled = !studio.output || studio.dirty && !studio.renderedAt;
  studio_drawWhy();
}

/* How many single edits are waiting, which is what the button counts. */
function studio_pendingCount() {
  return studio.pending.reduce((a, x) => a + x.n, 0);
}

/* THE ANSWER TO "IS WHAT I AM WATCHING WHAT I HAVE EDITED?", in one strip:
   a state colour, a sentence, and the list of what is missing when any is. */
function studio_drawSync() {
  const box = studio_el('studio-sync');
  if (!box) return;
  const n = studio_pendingCount();
  const btn = studio_el('studio-render-btn');
  let kind, head, sub, label;
  /* #studio-state, just below, carries the job's own words -- "Ready ·
     rendered in 23 s", "Cancelled.", the error. Nothing here repeats them. */
  if (studio.rendering) {
    kind = 'busy'; label = 'Rendering…';
    head = 'Rendering your changes';
    sub = '';
  } else if (studio.failMsg) {
    kind = 'bad'; label = n ? 'Try again · ' + n + (n === 1 ? ' change' : ' changes') : 'Try again';
    head = 'The last render failed';
    sub = 'Your edits are still here. Nothing was lost.';
  } else if (!studio.output) {
    kind = 'none'; label = 'Render';
    head = 'Not rendered yet';
    sub = 'There is nothing to watch until this reel has been rendered once.';
  } else if (studio.dirty) {
    kind = 'stale';
    label = n ? 'Apply ' + n + (n === 1 ? ' change' : ' changes') : 'Apply your changes';
    head = n ? n + (n === 1 ? ' change is not in the video' : ' changes are not in the video')
             : 'Your changes are not in the video';
    sub = 'The player is still showing the last render.';
  } else {
    kind = 'ok'; label = 'Render again';
    head = 'The video matches your edits';
    /* Only once the render has stopped being news: while it is, the line below
       is still saying "Ready · rendered in 23 s", which says it better. */
    const ago = studio.renderedAt ? studio_ago(studio.renderedAt) : '';
    sub = (ago && ago !== 'just now') ? 'Rendered ' + ago + '.' : '';
  }
  box.className = 'studio-sync is-' + kind;
  studio_el('studio-sync-head').textContent = head;
  studio_el('studio-sync-sub').textContent = sub;
  studio_show('studio-sync-sub', !!sub);
  if (btn) {
    btn.textContent = label;
    btn.classList.toggle('btn-warn', kind === 'stale');
    btn.classList.toggle('btn-primary', kind !== 'stale');
  }
  /* WHICH changes, not just how many -- the newest first, because that is the
     one being second-guessed. Six is as many as the card can hold without
     becoming the thing it replaced. */
  const list = studio_el('studio-pending');
  const show = kind === 'stale' || (kind === 'bad' && n);
  studio_show('studio-pending', show && n > 0);
  if (show && n > 0) {
    const rows = studio.pending.slice().reverse();
    list.innerHTML = rows.slice(0, 6).map(x =>
      '<li>' + esc(x.label) + (x.n > 1 ? '<span class="studio-pending-n">×' + x.n + '</span>' : '') + '</li>').join('') +
      (rows.length > 6 ? '<li class="studio-pending-more">and ' + (rows.length - 6) + ' more</li>' : '');
  }
  /* The player says it too: the sidebar is not where someone watching looks. */
  const stale = studio_el('studio-stale');
  if (stale) {
    studio_show('studio-stale', kind === 'stale' && !!studio.output);
    stale.textContent = 'Last render · ' + n + (n === 1 ? ' change not shown' : ' changes not shown');
  }
}

/* WHY THE REEL IS THE WAY IT IS. Two kinds of note arrive as one list of
   strings, and showing them as one list of amber bullets made the planner's
   running commentary look like five things going wrong. They are told apart by
   where they came from: plan_notes is the account of the build, kept on the
   project; anything in the latest reply that is NOT in it is the server
   answering for the edit just made, which is the part worth interrupting for. */
function studio_drawWhy() {
  const p = studio.project, d = studio.derived, box = studio_el('studio-why');
  if (!p || !box) return;
  /* Read back what is open before replacing it. The card is redrawn on every
     edit and every poll tick, and a fold that shut itself each time could not
     be read to the end. */
  Array.prototype.forEach.call(box.querySelectorAll('details[data-fold]'),
    d => { studio.folds[d.getAttribute('data-fold')] = d.open; });
  const plan = p.plan_notes || [];
  const live = (studio.notes || []).filter(n => plan.indexOf(n) < 0);
  const sel = (d && d.selection) || [];
  const out = sel.filter(x => !x.in);
  let h = '';
  if (live.length) {
    h += '<div class="studio-alert"><p class="studio-alert-h">' +
      (live.length === 1 ? 'One thing to know about that edit' : live.length + ' things to know about that edit') +
      '</p><ul>' + live.map(n => '<li>' + esc(n) + '</li>').join('') + '</ul></div>';
  }
  if (plan.length) {
    h += '<details class="studio-fold" data-fold="build"' + (studio.folds.build ? ' open' : '') +
      '><summary>How this reel was built' +
      '<span class="studio-fold-n">' + plan.length + '</span></summary>' +
      '<ul class="studio-fold-list">' + plan.map(n => '<li>' + esc(n) + '</li>').join('') + '</ul></details>';
  }
  if (sel.length) {
    const used = sel.length - out.length;
    h += out.length
      ? '<details class="studio-fold" data-fold="clips"' + (studio.folds.clips ? ' open' : '') +
        '><summary>Clips<span class="studio-fold-n">' + used + ' of ' + sel.length +
        '</span></summary><p class="studio-fold-lede">' + out.length +
        (out.length === 1 ? ' clip was left out:' : ' clips were left out:') + '</p><ul class="studio-fold-list">' +
        out.map(x => '<li><strong>' + esc(x.name) + '</strong> — ' + esc(x.why) + '</li>').join('') + '</ul></details>'
      : '<p class="studio-fold-flat">All ' + sel.length + ' chosen clips are in this reel</p>';
  }
  h += '<button type="button" class="btn btn-sm studio-add-btn" data-act="studio-add">Add clips…</button>';
  box.innerHTML = h;
}

/* Back to the clips with this reel's selection picked, to add more and rebuild. */
async function studio_addClips() {
  const p = studio.project, d = studio.derived;
  if (!p) return;
  await studio_load(false);
  const want = (p.selection && p.selection.length) ? p.selection.map(x => x.clip) : p.shots.map(x => x.clip);
  const byPath = {};
  Object.keys(studio.clipIndex).forEach(id => { byPath[String(studio.clipIndex[id].path).toLowerCase()] = id; });
  const ids = [];
  want.forEach(path => {
    const id = byPath[String(path).toLowerCase()];
    if (id && ids.indexOf(id) < 0) ids.push(id);
  });
  studio.selected = ids;
  studio.adding = {
    name: p.name, style: p.style, song: p.song || '', fmt: p.format,
    output: studio.output || p.output || '',
    start: p.song_offset || 0, end: p.part_end || ((p.song_offset || 0) + (d ? d.length : 0)),
    edited: !!(d && d.edited) || studio.undo.length > 0
  };
  studio_tab('clips');
  studio_renderLib();
  if (ids.length < new Set(want).size) toast('Some of the clips in this reel are not in the clips folder any more.', 'warn');
}

/* ------------------------------------------------------------ deleting clips */

function studio_bytes(n) {
  const gb = (Number(n) || 0) / 1073741824;
  return gb >= 1 ? gb.toFixed(1) + ' GB' : Math.round((Number(n) || 0) / 1048576) + ' MB';
}

async function studio_deleteAsk() {
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  if (!sel.length) return;
  const go = studio_el('studio-del-go');
  go.disabled = true; go.textContent = 'Delete';
  studio_el('studio-del-text').textContent = 'Checking ' + sel.length + (sel.length === 1 ? ' clip…' : ' clips…');
  studio_el('studio-del-reels').textContent = '';
  studio_el('studio-del-msg').textContent = '';
  studio_show('studio-del-scrim', true);
  studio.delPaths = sel.map(c => c.path);
  const r = await API.post('/api/studio/delete', {paths: studio.delPaths, dry_run: true});
  if (!r || !r.ok) { studio_el('studio-del-text').textContent = (r && r.error) || 'Could not check those clips.'; return; }
  const n = r.clips, one = n === 1;
  studio_el('studio-del-text').textContent = n
    ? 'Delete ' + n + (one ? ' clip and its vertical copy' : ' clips and their vertical copies') + '? This frees ' +
      studio_bytes(r.bytes) + '. They are removed from disk for good; the recordings they were cut from are not touched.'
    : 'None of these clips are in the clips folder any more.';
  const reels = r.reels || [];
  studio_el('studio-del-reels').textContent = reels.length
    ? (reels.length === 1 ? 'The reel “' + reels[0] + '” uses' : reels.length + ' reels use') + ' some of these clips' +
      (reels.length > 1 ? ' (' + reels.map(x => '“' + x + '”').join(', ') + ')' : '') + '. ' +
      (reels.length === 1 ? 'Its video stays' : 'Their videos stay') + ', but opening ' +
      (reels.length === 1 ? 'its timeline' : 'their timelines') + ' again leaves these shots out.'
    : '';
  go.textContent = 'Delete ' + n + (one ? ' clip' : ' clips');
  go.disabled = !n;
}

async function studio_deleteGo() {
  const go = studio_el('studio-del-go');
  go.disabled = true;
  studio_el('studio-del-msg').textContent = 'Deleting…';
  const r = await API.post('/api/studio/delete', {paths: studio.delPaths || []});
  if (!r || !r.ok) {
    studio_el('studio-del-msg').textContent = (r && r.error) || 'Could not delete those clips.';
    go.disabled = false;
    return;
  }
  studio_show('studio-del-scrim', false);
  studio.selected = []; studio.delPaths = [];
  const bad = (r.errors || []).length;
  toast('Deleted ' + r.clips + (r.clips === 1 ? ' clip' : ' clips') + ' and freed ' + studio_bytes(r.bytes) +
    (bad ? '. ' + bad + (bad === 1 ? ' file is' : ' files are') + ' still in use and could not be removed.' : '.'),
    bad ? 'warn' : 'ok');
  studio_load(true);
}

/* =======================================================================
   THE INTRO CLIP
   A song that takes nine seconds to arrive leaves the opener holding for
   nine seconds, and the built-in intro effects are a second long. This is
   what goes on screen during that build: the user's own GIF or video, over
   the head of the reel, with the song running underneath. See
   clips/intros.py for why it is an overlay and not a shot.
   ======================================================================= */

/* The inspector's one line about it. The editing happens in the dialog; this
   says what is set and opens it. */
function studio_introRow(p) {
  const ic = p.intro_clip;
  const len = ic ? (Number(ic.end) - Number(ic.start)) : 0;
  return '<div class="studio-introrow">' +
    (ic
      ? '<span class="studio-introrow-on"><b class="truncate">' + esc(ic.name || 'Intro clip') + '</b>' +
        '<span class="muted">' + len.toFixed(1) + ' s · ' +
        (ic.audio && ic.has_audio ? 'with its sound' : 'silent') + '</span></span>'
      : '<span class="muted">No intro clip</span>') +
    '<span class="field-inline">' +
    '<button type="button" class="btn btn-sm" data-act="studio-intro-open">' +
    (ic ? 'Edit the intro clip…' : 'Add an intro clip…') + '</button>' +
    (ic ? '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-intro-off">Remove</button>' : '') +
    '</span></div>';
}

async function studio_introOpen() {
  const p = studio.project;
  if (!p) return;
  const ic = p.intro_clip;
  studio.intro.pick = ic ? ic.path : '';
  studio.intro.start = ic ? Number(ic.start) : 0;
  studio.intro.end = ic ? Number(ic.end) : 0;
  studio.intro.audio = ic ? !!ic.audio : false;
  studio.intro.fit = (ic && ic.fit) || 'cover';
  studio.intro.seconds = 0; studio.intro.hasAudio = false;
  studio_el('studio-intro-msg').textContent = '';
  studio_show('studio-intro-clear', !!ic);
  studio_show('studio-intro-scrim', true);
  studio_introLede();
  await studio_introLoad();
  if (studio.intro.pick) studio_introChoose(studio.intro.pick, true);
  else studio_introDraw();
}

function studio_introLede() {
  const d = studio.derived;
  const lead = d ? Number(d.lead_in || 0) : 0;
  studio_el('studio-intro-lede').textContent = lead > 0.5
    ? 'This reel opens with a ' + lead.toFixed(1) + ' s run-up before its first kill — the song has '
      + 'not arrived yet. An intro clip plays before all of it.'
    : 'An intro clip plays before the reel, then the reel runs in full. '
      + 'It covers nothing and never changes where anything is cut.';
  const b = studio_el('studio-intro-fit-lead');
  studio_show('studio-intro-fit-lead', lead > 0.5);
  if (b && lead > 0.5) b.textContent = 'Fill the lead-in (' + lead.toFixed(1) + ' s)';
}

async function studio_introLoad() {
  const r = await API.get('/api/studio/intros');
  studio.intro.list = (r && r.ok) ? (r.intros || []) : [];
  studio_introLib();
  studio_mkIntroDraw();
}

/* THE MAKE DIALOG'S INTRO ROW. The whole section hides when there are no
   intros in the library: an empty picker is a question nobody can answer. */
function studio_mkIntroDraw() {
  const sel = studio_el('studio-mk-introsel');
  if (!sel) return;
  const list = studio.intro.list || [];
  studio_show('studio-mk-intro', list.length > 0);
  if (!list.length) return;
  const keep = studio.mkIntro.path;
  sel.innerHTML = '<option value="">No intro</option>' + list.map(x =>
    '<option value="' + esc(x.path) + '">' + esc(x.name) + ' · ' +
    Number(x.seconds).toFixed(1) + ' s' + (x.has_audio ? '' : ' · silent') +
    '</option>').join('');
  /* A chosen intro deleted from the library falls back to none rather than
     leaving a name selected that no longer resolves. */
  sel.value = list.some(x => x.path === keep) ? keep : '';
  studio.mkIntro.path = sel.value;
  const got = list.find(x => x.path === sel.value) || null;
  const au = studio_el('studio-mk-introaudio');
  au.disabled = !got || !got.has_audio;
  if (au.disabled) studio.mkIntro.audio = false;
  au.checked = !!studio.mkIntro.audio;
  studio_el('studio-mk-intronote').textContent = !got
    ? ''
    : studio.mkIntro.audio
      ? 'The intro plays its own sound. The song starts with the reel.'
      : (studio.song
          ? 'The song starts ' + Number(got.seconds).toFixed(1) + ' s earlier and plays '
            + 'through the intro, so it runs into the reel unbroken.'
          : 'No song chosen, so the intro plays silent.')
      + (got.has_audio ? '' : ' This clip has no sound of its own.');
}

function studio_introLib() {
  const box = studio_el('studio-intro-lib');
  const list = studio.intro.list;
  if (list === null) { box.innerHTML = '<p class="muted">Reading your intros…</p>'; return; }
  if (!list.length) {
    box.innerHTML = '<p class="muted">No intro clips yet. Add a GIF or a video and it stays here for every reel.</p>';
    return;
  }
  box.innerHTML = list.map(x =>
    '<div class="studio-introcard' + (x.path === studio.intro.pick ? ' is-on' : '') + '">' +
    '<button type="button" class="studio-introcard-hit" data-act="studio-intro-pick" data-path="' + esc(x.path) + '">' +
    '<span class="studio-introcard-name truncate">' + esc(x.name) + '</span>' +
    '<span class="muted studio-introcard-meta">' + Number(x.seconds).toFixed(1) + ' s · ' +
    (x.width && x.height ? x.width + '×' + x.height : '') + (x.has_audio ? ' · sound' : ' · silent') + '</span></button>' +
    '<button type="button" class="btn btn-ghost btn-sm studio-del-btn" data-act="studio-intro-del" ' +
    'data-path="' + esc(x.path) + '" data-name="' + esc(x.name) + '" title="Delete this intro">Delete</button>' +
    '</div>').join('');
}

function studio_introChoose(path, keepTrim) {
  const x = (studio.intro.list || []).find(i => i.path === path);
  if (!x) return;
  const iv = studio.intro;
  iv.pick = path; iv.seconds = Number(x.seconds) || 0; iv.hasAudio = !!x.has_audio;
  if (!keepTrim || iv.end <= iv.start) {
    iv.start = 0; iv.end = iv.seconds;
    /* A fresh pick takes the clip at its word: a video handed over with sound
       is a video whose sound was the point, so muting is the deliberate act
       and not the default. A reel being reopened keeps what it was saved with. */
    iv.audio = !!x.has_audio;
  }
  iv.start = Math.max(0, Math.min(iv.start, Math.max(0, iv.seconds - 0.3)));
  iv.end = Math.max(iv.start + 0.3, Math.min(iv.end || iv.seconds, iv.seconds));
  if (!iv.hasAudio) iv.audio = false;
  const v = studio_el('studio-intro-video');
  const want = studio_media('/api/studio/intro', path, '');
  if (v.getAttribute('data-path') !== path) {
    v.setAttribute('data-path', path);
    v.src = want;
    v.currentTime = iv.start;
  }
  studio_introLib();
  studio_introDraw();
}

/* Everything in the dialog that follows from the trim. */
function studio_introDraw() {
  const iv = studio.intro, on = !!iv.pick && iv.seconds > 0;
  studio_show('studio-intro-edit', on);
  studio_el('studio-intro-use').disabled = !on;
  if (!on) { studio_el('studio-intro-warn').textContent = ''; return; }
  const len = Math.max(0, iv.end - iv.start);
  const a = studio_el('studio-intro-a'), b = studio_el('studio-intro-b');
  if (document.activeElement !== a) a.value = String(Math.round(iv.start / iv.seconds * 1000));
  if (document.activeElement !== b) b.value = String(Math.round(iv.end / iv.seconds * 1000));
  studio_el('studio-intro-astamp').textContent = studio_secs(iv.start);
  studio_el('studio-intro-bstamp').textContent = studio_secs(iv.end);
  studio_el('studio-intro-range').textContent =
    /* The same precision both sides: 4.02 of a 4.02 s clip read as
       "4.02 s of 4.0 s", more than the whole. */
    len.toFixed(2) + ' s of ' + iv.seconds.toFixed(2) + ' s';
  const au = studio_el('studio-intro-audio');
  au.checked = iv.audio && iv.hasAudio;
  au.disabled = !iv.hasAudio;
  studio_el('studio-intro-audionote').textContent = iv.hasAudio
    ? (iv.audio ? 'Plays with the intro, before the song starts.' : 'The clip plays silent.')
    : 'This clip has no sound of its own.';
  studio_el('studio-intro-fitnote').textContent = iv.fit === 'cover'
    ? 'Cropped to fill the reel. Anything outside the frame is cut off.'
    : 'The whole clip is shown, with black around it where the shapes differ.';
  ['cover', 'contain'].forEach(k => {
    const el = studio_el('studio-intro-fit-' + k);
    if (el) el.classList.toggle('is-active', iv.fit === k);
  });
  /* The two things that can be wrong are worth saying before Use, not after
     the server clamps them in silence. */
  const d = studio.derived, reel = d ? Number(d.length || 0) : 0, lead = d ? Number(d.lead_in || 0) : 0;
  let warn = '';
  if (reel && len > reel) warn = 'Longer than the reel — it will be cut to ' + reel.toFixed(1) + ' s.';
  else if (lead > 0.5 && len > lead + 0.05) warn = 'Runs ' + (len - lead).toFixed(1) + ' s past the first kill.';
  studio_el('studio-intro-warn').textContent = warn;
}

function studio_introSet(what, t) {
  const iv = studio.intro;
  const v = Math.max(0, Math.min(iv.seconds, t));
  if (what === 'start') iv.start = Math.min(v, iv.end - 0.3);
  else iv.end = Math.max(v, iv.start + 0.3);
  iv.start = Math.max(0, iv.start);
  iv.end = Math.min(iv.seconds, iv.end);
  studio_introDraw();
  const vid = studio_el('studio-intro-video');
  if (vid && vid.paused) vid.currentTime = what === 'start' ? iv.start : Math.max(iv.start, iv.end - 0.25);
}

function studio_introPlay() {
  const v = studio_el('studio-intro-video'), iv = studio.intro;
  if (!v || !v.src) return;
  if (v.paused) {
    if (v.currentTime < iv.start || v.currentTime >= iv.end - 0.02) v.currentTime = iv.start;
    v.muted = !(iv.audio && iv.hasAudio);
    v.play().catch(() => {});
  } else {
    v.pause();
  }
}

/* Keeps the preview inside the trim, and loops it when asked. */
function studio_introTick() {
  const v = studio_el('studio-intro-video'), iv = studio.intro;
  if (!v) return;
  if (!v.paused && v.currentTime >= iv.end - 0.02) {
    if (studio_el('studio-intro-loop').checked) v.currentTime = iv.start;
    else { v.pause(); v.currentTime = iv.start; }
  }
  const c = studio_el('studio-intro-clock');
  if (c) c.textContent = studio_secs(Math.max(0, v.currentTime - iv.start));
  if (!v.paused) requestAnimationFrame(studio_introTick);
}

async function studio_introAdd() {
  const btn = studio_el('studio-intro-add'), msg = studio_el('studio-intro-msg');
  const r = await API.post('/api/clips/pick', {kind: 'intro'});
  if (!r || !r.path) return;
  btn.disabled = true;
  msg.textContent = 'Converting ' + String(r.name || 'that file') + '…';
  const got = await API.post('/api/studio/intro-add', {path: r.path});
  btn.disabled = false;
  if (!got || !got.ok) { msg.textContent = (got && got.error) || 'Could not add that intro.'; return; }
  msg.textContent = '';
  await studio_introLoad();
  studio.intro.start = 0; studio.intro.end = 0;
  studio_introChoose(got.intro.path, false);
}

async function studio_introDelete(path, name) {
  /* Asked first, like a clip or a reel. One click used to delete the file,
     and it is the only copy the app keeps. */
  if (!window.confirm('Delete the intro “' + name + '”? Its file is removed ' +
                      'from your intros folder, and any reel that uses it ' +
                      'opens without it.')) return;
  const msg = studio_el('studio-intro-msg');
  msg.textContent = 'Deleting “' + name + '”…';
  const r = await API.post('/api/studio/intro-delete', {path: path});
  if (!r || !r.ok) { msg.textContent = (r && r.error) || 'Could not delete that intro.'; return; }
  msg.textContent = '';
  if (studio.intro.pick === path) {
    studio.intro.pick = ''; studio.intro.seconds = 0;
    const v = studio_el('studio-intro-video');
    v.pause(); v.removeAttribute('src'); v.removeAttribute('data-path');
  }
  await studio_introLoad();
  studio_introDraw();
  toast('Deleted “' + name + '”.', 'ok');
}

function studio_introUse() {
  const iv = studio.intro;
  if (!iv.pick || iv.end <= iv.start) return;
  const x = (iv.list || []).find(i => i.path === iv.pick) || {};
  studio_change(pr => {
    pr.intro_clip = {path: iv.pick, name: x.name || '', start: Number(iv.start.toFixed(3)),
                     end: Number(iv.end.toFixed(3)), audio: !!(iv.audio && iv.hasAudio),
                     has_audio: !!iv.hasAudio, fit: iv.fit};
  }, 'The intro clip');
  studio_introClose();
  toast('Intro set — ' + (iv.end - iv.start).toFixed(1) + ' s over the start of the reel.', 'ok');
}

function studio_introOff(quiet) {
  if (!studio.project || !studio.project.intro_clip) { studio_introClose(); return; }
  studio_change(pr => { pr.intro_clip = null; }, 'The intro clip taken off');
  studio_introClose();
  if (!quiet) toast('The reel opens without an intro clip now.', 'ok');
}

function studio_introClose() {
  const v = studio_el('studio-intro-video');
  if (v && !v.paused) v.pause();
  studio_show('studio-intro-scrim', false);
}

/* ------------------------------------------------------------ deleting reels */

/* The dry run first: the server decides what a reel's path really owns, and
   the confirmation says it back before anything is unlinked. */
async function studio_reelDeleteAsk(path, name) {
  if (!path) return;
  studio.reelDel = path;
  const go = studio_el('studio-rdel-go');
  go.disabled = true;
  studio_el('studio-rdel-text').textContent = 'Checking “' + name + '”…';
  studio_el('studio-rdel-note').textContent = '';
  studio_el('studio-rdel-msg').textContent = '';
  studio_show('studio-rdel-scrim', true);
  const r = await API.post('/api/studio/reel-delete', {paths: [path], dry_run: true});
  if (studio.reelDel !== path) return;
  if (!r || !r.ok) { studio_el('studio-rdel-text').textContent = (r && r.error) || 'Could not check that reel.'; return; }
  if (!r.reels) { studio_el('studio-rdel-text').textContent = 'That reel is not in the reels folder any more.'; return; }
  studio_el('studio-rdel-text').textContent =
    'Delete “' + (r.names[0] || name) + '” and its timeline? This frees ' + studio_bytes(r.bytes) +
    '. The video and the project it reopens from are removed from disk for good.';
  studio_el('studio-rdel-note').textContent =
    'The clips it was made from are not touched, so the same reel can be made again.';
  go.disabled = false;
}

async function studio_reelDeleteGo() {
  const go = studio_el('studio-rdel-go');
  go.disabled = true;
  studio_el('studio-rdel-msg').textContent = 'Deleting…';
  const r = await API.post('/api/studio/reel-delete', {paths: [studio.reelDel || '']});
  if (!r || !r.ok) {
    studio_el('studio-rdel-msg').textContent = (r && r.error) || 'Could not delete that reel.';
    go.disabled = false;
    return;
  }
  studio_show('studio-rdel-scrim', false);
  /* The timeline on screen may be the reel that has just gone: it can still be
     edited, but it would be rendering into a file that no longer exists, so it
     is treated as never rendered rather than left claiming to match a video. */
  if (studio.project && studio.output && studio.output.toLowerCase() === String(studio.reelDel).toLowerCase()) {
    studio.output = ''; studio.renderedAt = 0; studio.renderNote = '';
    studio.project.output = '';
    studio_touched('The reel this was rendered to was deleted');
    studio_loadVideo();
    studio_drawAll();
  }
  studio.reelDel = '';
  const bad = (r.errors || []).length;
  toast('Deleted “' + (r.names[0] || 'that reel') + '” and freed ' + studio_bytes(r.bytes) +
    (bad ? '. ' + bad + (bad === 1 ? ' file is' : ' files are') + ' still in use and could not be removed.' : '.'),
    bad ? 'warn' : 'ok');
  studio_load(true);
}

/* ------------------------------------------------------------ timeline */

/* The music lane, top to bottom: the song's hits, the spectrogram, the
   waveform, and the reel's kills under them. The row height is the sum, so
   moving a band never leaves the lane and its label disagreeing. */
const STUDIO_MUSIC = {marks: 15, spec: 55, wave: 18, kills: 18};
const STUDIO_ROW = {ruler: 26, video: 64, trans: 30, fx: 34, speed: 38, text: 30,
                    music: STUDIO_MUSIC.marks + STUDIO_MUSIC.spec + STUDIO_MUSIC.wave + STUDIO_MUSIC.kills};
/* Pixels a second: from the whole reel on one screen to a frame being three
   pixels wide, which is what checking a kill against a hit by eye needs. */
const STUDIO_ZOOM = [8, 1600];

function studio_drawAll() {
  studio_fitEditor();
  studio_drawRenderCard();
  studio_drawTimeline();
  /* Rebuilding the panel under a focused field throws away what is being
     typed; the panel is redrawn when the field is left instead. */
  const a = document.activeElement;
  const typing = a && a.closest && a.closest('#studio-insp') &&
    /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) && a.type !== 'checkbox' && a.type !== 'range';
  if (!typing) studio_drawInspector();
  studio_frameDraw();
  if (!studio_el('studio-pane-facecam').classList.contains('hide')) studio_fcDraw();
}

function studio_fit() {
  const d = studio.derived;
  const box = studio_el('studio-scroll');
  if (!d || !box) return;
  const w = Math.max(320, box.clientWidth - 24);
  studio.pps = Math.max(12, Math.min(STUDIO_ZOOM[1], w / Math.max(1, d.length)));
}

/* ZOOMING KEEPS ONE SECOND STILL. Changing the scale alone throws the view
   somewhere else on the reel -- the shot being looked at slides off screen and
   has to be found again. The second under the pointer (or under the playhead,
   for the buttons) is held in place instead, which is what every editor does. */
function studio_zoomAt(pps, clientX) {
  const box = studio_el('studio-scroll');
  if (!box || !studio.derived) return;
  const r = box.getBoundingClientRect();
  const px = (clientX === null || clientX === undefined)
    ? box.clientWidth / 2 : Math.max(0, Math.min(box.clientWidth, clientX - r.left));
  const t = (box.scrollLeft + px) / studio.pps;
  const next = Math.max(STUDIO_ZOOM[0], Math.min(STUDIO_ZOOM[1], pps));
  if (Math.abs(next - studio.pps) < 1e-6) return;
  studio.pps = next;
  studio_drawTimeline();
  box.scrollLeft = Math.max(0, t * studio.pps - px);
  studio_drawWave();
}

/* The playhead when it is on screen, so zooming from the buttons keeps the
   frame being watched rather than the middle of the view. */
function studio_anchorX() {
  const box = studio_el('studio-scroll'), v = studio_el('studio-video');
  if (!box) return null;
  const t = (v && v.src) ? (v.currentTime || 0) : 0;
  const px = t * studio.pps - box.scrollLeft;
  if (px < 0 || px > box.clientWidth) return null;
  return box.getBoundingClientRect().left + px;
}

function studio_wheel(e) {
  const box = studio_el('studio-scroll');
  if (!box || !studio.project) return;
  if (e.ctrlKey || e.metaKey || e.altKey) {
    e.preventDefault();
    /* A line-mode wheel reports 3 lines where a trackpad reports pixels. */
    const dy = (e.deltaY || 0) * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1);
    studio_zoomAt(studio.pps * Math.exp(-dy * 0.0025), e.clientX);
    return;
  }
  const dx = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : (e.shiftKey ? e.deltaY : 0);
  if (dx) { e.preventDefault(); box.scrollLeft += dx; }
}

function studio_drawTimeline() {
  const p = studio.project, d = studio.derived;
  const host = studio_el('studio-tracks');
  if (!p || !d || !host) return;
  const pps = studio.pps, L = d.length, W = Math.ceil(L * pps) + 24;
  const X = (t) => (t * pps).toFixed(1);
  let top = 0;
  const rows = {};
  Object.keys(STUDIO_ROW).forEach(k => { rows[k] = top; top += STUDIO_ROW[k]; });
  /* The label beside each track is the same height as the track, always: the
     two were written down twice and the music lane grew out of its label. */
  const labs = document.querySelectorAll('#view-studio .studio-labels .st-lab');
  Object.keys(STUDIO_ROW).forEach((k, i) => { if (labs[i]) labs[i].style.height = STUDIO_ROW[k] + 'px'; });
  let h = '<div class="st-area" style="width:' + W + 'px;height:' + top + 'px">';

  /* ruler: seconds, bars and beats */
  h += '<div class="st-ruler" data-act="studio-seek" style="top:0;height:' + STUDIO_ROW.ruler + 'px">';
  const step = pps > 120 ? 1 : pps > 40 ? 2 : pps > 18 ? 5 : 10;
  for (let t = 0; t <= L + 1e-6; t += step) {
    h += '<span class="st-tick" style="left:' + X(t) + 'px">' + studio_secs(t).replace(/\.\d+$/, '') + '</span>';
  }
  h += '</div>';
  (d.beats || []).forEach((b, i) => {
    const bar = i % 4 === 0;
    if (!bar && pps < 30) return;
    h += '<i class="st-beat' + (bar ? ' is-bar' : '') + '" style="left:' + X(b) + 'px;top:' + STUDIO_ROW.ruler +
         'px;height:' + (top - STUDIO_ROW.ruler) + 'px"></i>';
  });

  /* video */
  const edited = {};
  studio.pending.forEach(x => { if (x.shot >= 0) edited[x.shot] = true; });
  p.shots.forEach((s, i) => {
    const r = d.shots[i];
    if (!r) return;
    const c = studio.clipIndex[s.clip_id] || null;
    const thumb = studio_media('/api/studio/thumb', s.clip, '&t=' + Math.max(0, s.kill - 0.3).toFixed(2) +
                               '&v=' + ((c && c.mtime) || 0));
    const w = Math.max(6, (r.end - r.start) * pps);
    /* A shot edited since the last render is flagged where the edit was made,
       not only in the sidebar: "which shot did I change?" is a timeline
       question and deserves a timeline answer. */
    h += '<div class="st-shot' + (i === studio.sel ? ' is-sel' : '') + (s.hero ? ' is-hero' : '') +
      (edited[i] ? ' is-edited' : '') +
      '" data-shot="' + i + '" style="left:' + X(r.start) + 'px;top:' + rows.video + 'px;width:' + w.toFixed(1) +
      'px;height:' + STUDIO_ROW.video + 'px;background-image:url(\'' + thumb + '\')" title="' + esc(s.name) + '">' +
      '<span class="st-shot-name">' + (i + 1) + (w > 70 ? ' · ' + esc((c && c.caption) || s.name) : '') + '</span>' +
      '<span class="st-kill" data-kill="' + i + '" style="left:' + ((r.kill_reel - r.start) * pps).toFixed(1) +
      'px" title="Kill — drag to move it"></span>' +
      '<span class="st-trim" data-trim="' + i + '" title="Drag to change the length"></span></div>';
  });

  /* THE INTRO CLIP, DRAWN OVER WHAT IT COVERS. It is not a shot and never
     moves a cut, so it is a band across the head of the video row rather than
     a block in the row: what it hides is exactly what is under it. */
  const icd = d.intro_clip;
  if (icd && icd.seconds > 0) {
    const iw = Math.max(2, icd.seconds * pps);
    h += '<div class="st-introclip" data-act="studio-intro-open" style="left:' + X(0) +
      'px;top:' + rows.video + 'px;width:' + iw.toFixed(1) + 'px;height:' + STUDIO_ROW.video +
      'px" title="' + esc(icd.name || 'Intro clip') + ' — ' + icd.seconds.toFixed(1) +
      ' s. Click to edit.">' +
      (iw > 64 ? '<span class="st-introclip-tag">Intro · ' + icd.seconds.toFixed(1) + ' s</span>' : '') +
      '</div>';
  }

  /* transitions: a label where there is room for one, a marker where not */
  p.shots.forEach((s, i) => {
    if (i === 0) return;
    const r = d.shots[i];
    const part = studio_part(s.transition);
    const hard = s.transition === 't01';
    const room = Math.min((r.end - r.start) * pps, (d.shots[i - 1].end - d.shots[i - 1].start) * pps);
    const compact = room < 44;
    h += '<button type="button" class="st-tr' + (hard ? ' is-cut' : '') + (compact ? ' is-compact' : '') +
      (i === studio.sel ? ' is-sel' : '') + '" data-act="studio-select" data-shot="' + i + '" style="left:' + X(r.start) +
      'px;top:' + rows.trans + 'px' + (compact ? '' : ';width:' + Math.max(26, s.tlen * pps).toFixed(1) + 'px') +
      '" title="Shot ' + (i + 1) + ': ' + esc(part.label) + '">' +
      (compact ? '' : esc(hard ? '|' : s.transition.toUpperCase())) + '</button>';
  });

  /* effects: every id on a wide shot, a count on a narrow one */
  p.shots.forEach((s, i) => {
    const r = d.shots[i];
    const ids = s.fx.concat(s.hero ? s.hero_fx : []);
    if (!ids.length) return;
    const room = (r.end - r.start) * pps;
    const full = ids.map(x => x.toUpperCase()).join(' ');
    const label = room >= full.length * 7 + 16 ? full : room >= 30 ? String(ids.length) : '';
    h += '<button type="button" class="st-fx' + (s.hero ? ' is-hero' : '') + (label === full ? '' : ' is-compact') +
      '" data-act="studio-select" data-shot="' + i +
      '" style="left:' + X(r.kill_reel) + 'px;top:' + (rows.fx + 6) + 'px" title="Shot ' + (i + 1) + ': ' +
      esc(ids.map(id => studio_part(id).label).join(', ')) + ' — click to change">' + esc(label) + '</button>';
  });

  /* speed: one line per shot, real speed through the middle */
  h += '<svg class="st-speed" style="top:' + rows.speed + 'px;height:' + STUDIO_ROW.speed + 'px;width:' + W +
       'px" viewBox="0 0 ' + W + ' ' + STUDIO_ROW.speed + '" preserveAspectRatio="none" aria-hidden="true">';
  const mid = STUDIO_ROW.speed / 2;
  h += '<line class="st-speed-base" x1="0" x2="' + W + '" y1="' + mid + '" y2="' + mid + '"></line>';
  p.shots.forEach((s, i) => {
    const r = d.shots[i];
    const pts = [];
    (r.pieces || []).forEach(pc => {
      const y = (mid - Math.max(-1.8, Math.min(1.8, Math.log2(pc[2]))) * (mid - 4) / 1.8).toFixed(1);
      pts.push(X(r.start + pc[0]) + ',' + y, X(r.start + pc[1]) + ',' + y);
    });
    if (pts.length) h += '<polyline class="st-speed-line' + (s.speed !== 's00' ? ' is-ramp' : '') + '" points="' + pts.join(' ') + '"></polyline>';
  });
  h += '</svg>';

  /* text & overlays */
  const texts = [];
  if (p.intro && p.intro !== 'i00') texts.push([0, Math.min(L, 1.2), studio_part(p.intro).label]);
  if (p.outro && p.outro !== 'e12') texts.push([Math.max(0, L - 1.2), L, studio_part(p.outro).label]);
  (p.overlays || []).forEach(o => texts.push(o === 'i04' ? [1, Math.min(L, 7), studio_part(o).label] : [0, L, studio_part(o).label]));
  p.shots.forEach((s, i) => {
    if (s.hero && s.hero_fx.indexOf('h05') >= 0 && s.caption) {
      texts.push([d.shots[i].kill_reel, Math.min(L, d.shots[i].kill_reel + 1.4), '“' + s.caption + '”']);
    }
  });
  texts.forEach((t, k) => {
    h += '<button type="button" class="st-text" data-act="studio-select" data-shot="-1" style="left:' + X(t[0]) +
      'px;top:' + (rows.text + 3 + (k % 2) * 2) + 'px;width:' + Math.max(12, (t[1] - t[0]) * pps).toFixed(1) +
      'px" title="' + esc(t[2]) + '">' + esc(t[2]) + '</button>';
  });

  /* music */
  h += '<canvas class="st-music" id="studio-wave" style="top:' + rows.music + 'px;height:' + STUDIO_ROW.music + 'px"></canvas>';
  h += '<div class="st-ph" id="studio-ph" style="height:' + top + 'px"></div>';
  h += '</div>';
  host.innerHTML = h;
  const zl = studio_el('studio-zoomlab');
  if (zl) zl.textContent = pps >= 100 ? Math.round(pps) + ' px/s' : pps.toFixed(1) + ' px/s';
  studio_drawWave();
  studio_syncNote();
  studio_playhead();
}

/* =======================================================================
   THE MUSIC LANE
   A waveform says how loud the song is and nothing else. Whether a kill
   landed on the hit it was aimed at is a question about WHICH SOUND is
   there -- a kick, a hat -- so this lane draws the same spectrogram the
   Song tab draws, on the reel's own axis, with the hits the reel was cut
   to above it and the kills as they actually fall below it. A kill on its
   hit is the one claim a montage makes; now it can be checked by eye.

   IT DRAWS THE VISIBLE WINDOW, NOT THE WHOLE REEL. A canvas as wide as a
   deeply zoomed timeline is past what a browser will allocate, and the
   spectrogram would be redrawn blurred to fit it; this one moves with the
   scroll and stays one canvas pixel per screen pixel at any zoom.
   ======================================================================= */

function studio_drawWave() {
  const cv = studio_el('studio-wave');
  const box = studio_el('studio-scroll');
  const p = studio.project, d = studio.derived, sh = studio.songShape;
  if (!cv || !box || !p || !d) return;
  const pps = studio.pps, H = STUDIO_ROW.music;
  const W = Math.ceil(d.length * pps) + 24;
  const x0 = Math.max(0, Math.min(box.scrollLeft, Math.max(0, W - 1)));
  const vw = Math.max(1, Math.min(box.clientWidth || W, W - x0));
  const dpr = window.devicePixelRatio || 1;
  cv.style.left = x0 + 'px';
  cv.style.width = vw + 'px';
  cv.width = Math.round(vw * dpr); cv.height = Math.round(H * dpr);
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, vw, H);
  const X = (t) => t * pps - x0;
  const t0 = x0 / pps, t1 = (x0 + vw) / pps;
  const off = p.song_offset || 0;
  const yMarks = 0, ySpec = STUDIO_MUSIC.marks;
  const yWave = ySpec + STUDIO_MUSIC.spec, yKills = yWave + STUDIO_MUSIC.wave;

  if (!p.song) {
    g.fillStyle = studio_tok('--accent');
    g.globalAlpha = 0.35; g.fillRect(0, H / 2 - 1, vw, 2); g.globalAlpha = 1;
    g.font = '12px sans-serif';
    g.fillText('No song — the clips keep their own sound', 8, H / 2 - 6);
    return;
  }
  studio_musicNeed();

  /* the spectrogram, cut out of the whole song's image at this zoom */
  const spec = studio.showSpec === false ? null : studio_specImage();
  if (spec) {
    const all = (t1 - t0) * spec.fps;
    let sx = (off + t0) * spec.fps, sw = all, dx = 0, dw = vw;
    if (sx < 0) { const cut = Math.min(-sx, sw); sx = 0; sw -= cut; dx = cut / all * vw; dw -= dx; }
    if (sx + sw > spec.frames) { const cut = sx + sw - spec.frames; sw -= cut; dw -= cut / all * vw; }
    if (sw > 0 && dw > 0) g.drawImage(spec.canvas, sx, 0, sw, spec.bins, dx, ySpec, dw, STUDIO_MUSIC.spec);
  } else if (studio.showSpec !== false) {
    g.fillStyle = studio_tok('--text-tertiary'); g.font = '11px sans-serif';
    g.fillText(studio.musicPending ? 'Reading the song…' : 'The spectrogram needs the song read once.',
               8, ySpec + 12);
  }

  /* the waveform: the song's own loudness at 100 a second once it is read,
     the plan's coarse peaks until then. With the spectrogram off it takes
     that band too rather than leaving a gap where it was. */
  const rms = studio_svSame() ? studio_svLane('rms') : null;
  const wTop = spec ? yWave : ySpec;
  const wH = spec ? STUDIO_MUSIC.wave : STUDIO_MUSIC.spec + STUDIO_MUSIC.wave;
  const mid = wTop + wH / 2, amp = wH / 2 - 1;
  g.fillStyle = studio_tok('--accent');
  if (rms) {
    const fps = studio.sv.meta.fps;
    for (let i = 0; i < vw; i++) {
      const a = Math.floor((off + (x0 + i) / pps) * fps);
      const b = Math.max(a + 1, Math.floor((off + (x0 + i + 1) / pps) * fps));
      let peak = 0;
      for (let k = Math.max(0, a); k < Math.min(rms.length, b); k++) if (rms[k] > peak) peak = rms[k];
      const hh = peak / 255 * amp;
      if (hh > 0.2) g.fillRect(i, mid - hh, 1, hh * 2);
    }
  } else if (sh && sh.peaks && sh.peaks.length) {
    const n = sh.peaks.length, per = sh.seconds / n;
    for (let i = 0; i < vw; i += 2) {
      const k = Math.floor((off + (x0 + i) / pps) / per);
      if (k < 0 || k >= n) continue;
      const hh = sh.peaks[k] * amp;
      g.fillRect(i, mid - hh, 1.5, hh * 2);
    }
  }

  /* the drop, where the song has one */
  if (sh && sh.drop) {
    const x = X(sh.drop - off);
    if (x >= -2 && x <= vw + 2) { g.fillStyle = studio_tok('--warn'); g.fillRect(x - 1, ySpec, 2, H - ySpec); }
  }

  /* THE SONG'S HITS: where a kill was meant to land. Every other hit the
     song has is a faint tick behind them -- the same pair the Song tab
     draws -- because "it missed" and "it landed on the hit next door" are
     different answers and only the neighbours tell them apart. */
  const mk = studio.showMarks === false ? null : studio_marks();
  if (mk && pps >= 20) {
    g.fillStyle = 'rgba(47,212,200,0.45)';
    mk.minor.forEach(t => {
      if (t < t0 || t > t1) return;
      if (mk.at.some(m => Math.abs(m - t) < 0.02)) return;
      g.fillRect(X(t) - 0.5, yMarks + 7, 1, 4);
    });
  }
  if (mk) {
    mk.at.forEach((t, i) => {
      if (t < t0 - 0.05 || t > t1 + 0.05) return;
      const x = X(t), big = mk.big.some(b => Math.abs(b - t) < 0.02);
      g.fillStyle = 'rgba(47,212,200,0.38)';
      g.fillRect(x - 0.5, yMarks + 11, 1, H - yMarks - 11);
      g.fillStyle = '#2fd4c8';
      g.fillRect(x - (big ? 1.5 : 0.5), yMarks + 3, big ? 3 : 1, 8);
      if (big) { g.beginPath(); g.moveTo(x - 4, yMarks + 1); g.lineTo(x + 4, yMarks + 1); g.lineTo(x, yMarks + 7); g.fill(); }
      if (pps > 80) {
        g.fillStyle = studio_tok('--text-tertiary'); g.font = '9px monospace';
        g.fillText(String(i + 1), x + 3, yMarks + 9);
      }
    });
  }

  /* THE KILLS AS THEY FALL. The shot's own kill is the diamond; any other
     kill inside the shot is a tick, because it is in the footage too. */
  g.fillStyle = studio_tok('--text-tertiary');
  (d.kills || []).forEach(t => {
    if (t < t0 || t > t1) return;
    g.globalAlpha = 0.5; g.fillRect(X(t) - 0.5, yKills + 2, 1, STUDIO_MUSIC.kills - 4); g.globalAlpha = 1;
  });
  const win = d.on_mark_window || 0.05;
  const ky = yKills + STUDIO_MUSIC.kills / 2;
  (d.shots || []).forEach((r, i) => {
    const t = r.kill_reel;
    if (t < t0 - 0.5 || t > t1 + 0.5) return;
    const near = studio_nearMark(mk, r, t);
    const drift = near === null ? null : t - near;
    const ok = drift !== null && Math.abs(drift) <= win;
    const col = drift === null ? studio_tok('--text-secondary') : ok ? studio_tok('--ok') : studio_tok('--warn');
    const x = X(t);
    if (drift !== null && !ok) {
      /* the gap itself, drawn as the bar it is: which way and how far */
      g.fillStyle = col; g.globalAlpha = 0.55;
      g.fillRect(Math.min(x, X(near)), ky - 1, Math.abs(x - X(near)), 2);
      g.globalAlpha = 1;
    }
    g.fillStyle = col;
    g.beginPath(); g.moveTo(x, ky - 5); g.lineTo(x + 5, ky); g.lineTo(x, ky + 5); g.lineTo(x - 5, ky); g.closePath(); g.fill();
    if (i === studio.sel) { g.strokeStyle = studio_tok('--accent'); g.lineWidth = 1.5; g.stroke(); }
    if (drift !== null && !ok && pps > 60) {
      g.fillStyle = col; g.font = '9px monospace';
      g.fillText((drift > 0 ? '+' : '') + drift.toFixed(2), x + 7, ky + 3);
    }
  });
}

/* Is the song that has been read the song this reel uses? */
function studio_svSame() {
  return !!(studio.sv && studio.sv.meta && studio.project && studio.sv.song === studio.project.song);
}

/* THE HITS THE KILLS WERE AIMED AT, in reel seconds.
   The server works them out for a reel planned since they were recorded
   (derived.marks); older reels have none stored, so the page falls back to
   what the detector finds in the song now -- the same set the Song tab draws
   -- and says which of the two it is showing. */
function studio_marks() {
  const p = studio.project, d = studio.derived;
  if (!p || !p.song || !d) return null;
  const off = p.song_offset || 0, L = d.length;
  const sh = studio.songShape;
  const det = studio_svSame() ? studio.sv.det : null;
  const reel = (t) => t - off;
  const inside = (t) => t >= -0.5 && t <= L + 0.5;
  const big = ((sh && sh.big) || []).map(reel);
  const minor = (((det && det.hits) || (sh && sh.hits) || [])).map(reel).filter(inside);
  if (d.marks && d.marks.length) return {at: d.marks, minor: minor, big: big, what: 'planned'};
  const from = (det && det.kills && det.kills.length) ? det.kills : ((sh && sh.hits) || []);
  const at = from.map(reel).filter(inside);
  if (!at.length) return null;
  return {at: at, minor: minor, big: big, what: (det && det.kills.length) ? 'detector' : 'hits'};
}

/* The mark nearest a kill: the server's answer where there is one, so the
   drift drawn is the drift the render produced.

   A lead-in shot has none. Its footage could not reach the first mark, so it
   opens the reel and the mark went to the shot behind it -- scoring its kill
   against the nearest mark anyway drew a six-second miss for a shot that was
   never aimed at one. */
function studio_nearMark(mk, row, t) {
  if (row && row.lead_in) return null;
  if (row && row.mark !== undefined && row.mark !== null && mk && mk.what === 'planned') return row.mark;
  if (!mk || !mk.at.length) return null;
  let best = mk.at[0];
  for (let i = 1; i < mk.at.length; i++) if (Math.abs(mk.at[i] - t) < Math.abs(best - t)) best = mk.at[i];
  return best;
}

function studio_syncNote() {
  const el = studio_el('studio-tl-sync');
  const p = studio.project, d = studio.derived;
  if (!el || !p || !d) return;
  const mk = studio_marks();
  if (!p.song || !mk) { el.textContent = ''; return; }
  const win = d.on_mark_window || 0.05;
  let on = 0, have = 0, worst = 0;
  (d.shots || []).forEach(r => {
    const near = studio_nearMark(mk, r, r.kill_reel);
    if (near === null) return;
    have++;
    const drift = r.kill_reel - near;
    if (Math.abs(drift) <= win) on++;
    else if (Math.abs(drift) > Math.abs(worst)) worst = drift;
  });
  if (!have) { el.textContent = ''; return; }
  el.textContent = on + ' of ' + have + ' kills land on ' +
    (mk.what === 'planned' ? 'the hit they were cut to'
      : mk.what === 'detector' ? "the hits the Song tab marks" : "the song's own hits") +
    ' (±' + win.toFixed(2) + ' s)' +
    (worst ? '; the furthest is ' + Math.abs(worst).toFixed(2) + ' s ' + (worst > 0 ? 'late' : 'early') : '') + '.';
}

/* The whole song as one image, built once and cut out of at every zoom.
   Redrawing 80 bands a frame per paint is what made the Song tab's lanes cost
   what they cost; the timeline repaints on every scroll and cannot afford it. */
function studio_specImage() {
  if (!studio_svSame() || !studio.sv.bytes) return null;
  const song = studio.sv.song;
  if (studio.spec && studio.spec.song === song) return studio.spec;
  const m = studio.sv.meta, bins = m.spec_bins, sp = studio_svLane('spec');
  if (!sp || !m.frames || !bins) return null;
  /* A canvas is not allowed to be as wide as a long song has frames. */
  const step = Math.ceil(m.frames / 30000);
  const cols = Math.ceil(m.frames / step);
  const cv = document.createElement('canvas');
  cv.width = cols; cv.height = bins;
  const g = cv.getContext('2d');
  const img = g.createImageData(cols, bins);
  for (let i = 0; i < cols; i++) {
    const f = i * step;
    for (let b = 0; b < bins; b++) {
      const v = sp[f * bins + b], o = ((bins - 1 - b) * cols + i) * 4;
      img.data[o] = SG_PAL[v * 3]; img.data[o + 1] = SG_PAL[v * 3 + 1];
      img.data[o + 2] = SG_PAL[v * 3 + 2]; img.data[o + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  studio.spec = {song: song, canvas: cv, bins: bins, fps: m.fps / step, frames: cols};
  return studio.spec;
}

/* The song read once for the timeline, the same bytes the Song tab uses. It
   is asked for once per song: a failed read must not be retried on every
   paint, and a paint happens on every scroll. */
function studio_musicNeed() {
  const p = studio.project;
  const song = (p && p.song) || '';
  if (!song || studio.musicPending || studio_svSame()) return;
  if (studio.musicWant === song && studio.sv === null) return;
  studio.musicWant = song;
  studio.musicPending = true;
  studio_svLoad(song).then(() => {
    studio.musicPending = false;
    studio.spec = null;
    const tl = studio_el('studio-pane-timeline');
    if (studio.project && tl && !tl.classList.contains('hide')) { studio_drawWave(); studio_syncNote(); }
  }, () => { studio.musicPending = false; });
}

function studio_playhead() {
  const v = studio_el('studio-video'), ph = studio_el('studio-ph');
  const t = v && v.src ? v.currentTime || 0 : 0;
  if (ph) ph.style.left = (t * studio.pps).toFixed(1) + 'px';
  const c = studio_el('studio-clock');
  if (c) c.textContent = studio_secs(t);
}

function studio_select(i) {
  studio.sel = i;
  studio_drawTimeline();
  studio_drawInspector();
}

/* ------------------------------------------------------------ inspector */

function studio_select_html(id, kind, value, allowNone) {
  return '<select class="select" id="' + id + '">' + studio_parts(kind).map(p =>
    '<option value="' + esc(p.id) + '"' + (p.id === value ? ' selected' : '') + '>' + esc(p.id.toUpperCase() + ' · ' + p.label) + '</option>'
  ).join('') + '</select>';
}

function studio_pool_html(kind, values) {
  return '<div class="studio-checks">' + studio_parts(kind).filter(p => p.id !== 't01' || kind === 'transition').map(p =>
    '<label class="studio-check-chip' + (values.indexOf(p.id) >= 0 ? ' is-on' : '') + '" title="' + esc(p.blurb) + '">' +
    '<input type="checkbox" data-pool="' + kind + '" value="' + esc(p.id) + '"' + (values.indexOf(p.id) >= 0 ? ' checked' : '') + '> ' +
    esc(p.label) + '</label>').join('') + '</div>';
}

function studio_checks_html(name, kind, values, skip) {
  return '<div class="studio-checks">' + studio_parts(kind).filter(p => !(skip || []).includes(p.id)).map(p =>
    '<label class="studio-check-chip' + (values.indexOf(p.id) >= 0 ? ' is-on' : '') + '" title="' + esc(p.blurb) + '">' +
    '<input type="checkbox" data-list="' + name + '" value="' + esc(p.id) + '"' + (values.indexOf(p.id) >= 0 ? ' checked' : '') + '> ' +
    esc(p.label) + '</label>').join('') + '</div>';
}

/* The inspector is rebuilt from the project on every edit, and a rebuilt
   panel starts scrolled to its top -- so ticking an effect halfway down the
   list threw the list back to the top on every click. Its scroll position
   survives a redraw of the same view, and resets only for a different one. */
function studio_drawInspector() {
  const box = studio_el('studio-insp');
  if (!box) return;
  const view = String(studio.sel);
  const old = box.querySelector('.studio-insp-body');
  const top = old && box.getAttribute('data-view') === view ? old.scrollTop : 0;
  const pageHost = document.getElementById('views');
  const pageTop = pageHost ? pageHost.scrollTop : 0;
  studio_drawInspectorBody();
  box.setAttribute('data-view', view);
  const body = box.querySelector('.studio-insp-body');
  if (body) body.scrollTop = top;
  if (pageHost && pageHost.scrollTop !== pageTop) pageHost.scrollTop = pageTop;
}

/* A folded group of the inspector. Which groups are open is remembered for
   the session, so the one being worked in stays open through every redraw. */
const STUDIO_GROUPS_OPEN = {timing: true, fx: true, look: true, pools: true, ending: true, cam: true, handle: true, sound: false,
                            trans: true, hero: false, camera: false};
function studio_grp(key, title, body, note) {
  const open = key in (studio.grpOpen || {}) ? studio.grpOpen[key] : STUDIO_GROUPS_OPEN[key] !== false;
  return '<details class="ed-group" data-grp="' + key + '"' + (open ? ' open' : '') + '><summary>' + esc(title) +
    (note ? ' <span class="ed-group-note">' + esc(note) + '</span>' : '') + '</summary>' +
    '<div class="ed-group-body">' + body + '</div></details>';
}

/* Nine places, laid out as the frame they stand for. `at` is [x, y] in 0..1. */
function studio_grid9(act, at) {
  let h = '<div class="ed-grid9" role="group">';
  [0, 0.5, 1].forEach(y => [0, 0.5, 1].forEach(x => {
    const on = at && Math.abs(at[0] - x) < 0.01 && Math.abs(at[1] - y) < 0.01;
    h += '<button type="button" class="' + (on ? 'is-on' : '') + '" data-act="' + act + '" data-x="' + x + '" data-y="' + y + '"' +
      ' aria-label="' + (y === 0 ? 'top' : y === 1 ? 'bottom' : 'middle') + ' ' + (x === 0 ? 'left' : x === 1 ? 'right' : 'centre') + '"></button>';
  }));
  return h + '</div>';
}

function studio_seg(act, key, value, opts) {
  return '<div class="seg" role="group">' + opts.map(o =>
    '<button type="button" class="seg-btn' + (o[0] === value ? ' is-active' : '') + '" data-act="' + act + '" data-' + key + '="' + o[0] + '">' + esc(o[1]) + '</button>').join('') + '</div>';
}

const STUDIO_OUTRO_LENS = [[0, 'Style’s own'], [2, '2 s'], [3, '3 s'], [4, '4 s'], [5, '5 s'], [6, '6 s'], [8, '8 s']];

function studio_drawInspectorBody() {
  const box = studio_el('studio-insp');
  const p = studio.project;
  if (!box || !p) return;
  const tabs = '<div class="seg studio-insp-tabs" role="tablist">' +
    '<button type="button" class="seg-btn' + (studio.sel >= 0 ? ' is-active' : '') + '" data-act="studio-select" data-shot="' + Math.max(0, studio.sel) + '"' + (p.shots.length ? '' : ' disabled') + '>Shot</button>' +
    '<button type="button" class="seg-btn' + (studio.sel < 0 ? ' is-active' : '') + '" data-act="studio-select" data-shot="-1">Reel</button></div>';
  if (studio.sel >= 0 && p.shots[studio.sel]) {
    const i = studio.sel, s = p.shots[i], r = studio.derived.shots[i] || {};
    const beat = p.beat || 0.5;
    const kills = s.kills.map((k, j) => '<option value="' + k + '"' + (Math.abs(k - s.kill) < 0.01 ? ' selected' : '') + '>Kill ' + (j + 1) + ' at ' + k.toFixed(2) + ' s</option>').join('');
    box.innerHTML = tabs + '<div class="card-body studio-insp-body">' +
      '<div class="studio-insp-head"><strong>Shot ' + (i + 1) + ' of ' + p.shots.length + '</strong>' +
      '<span class="field-inline"><button type="button" class="btn btn-ghost btn-sm" data-act="studio-move" data-d="-1"' + (i ? '' : ' disabled') + ' aria-label="Move earlier">◀</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-move" data-d="1"' + (i < p.shots.length - 1 ? '' : ' disabled') + ' aria-label="Move later">▶</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-remove">Remove</button></span></div>' +
      '<p class="muted truncate" title="' + esc(s.name) + '">' + esc(s.name) + '</p>' +
      studio_pinRow(s.clip) +
      '<p class="muted mono">' + studio_secs(r.start) + ' → ' + studio_secs(r.end) + ' · kill at ' + studio_secs(r.kill_reel) + '</p>' +
      studio_grp('timing', 'Timing',
        '<div class="studio-field"><span class="field-label">Kill</span>' +
        (s.kills.length > 1 ? '<select class="select" id="studio-f-kill">' + kills + '</select>' : '<span class="muted">' + s.kill.toFixed(2) + ' s into the clip</span>') +
        '<span class="field-inline studio-nudge"><button type="button" class="btn btn-ghost btn-sm" data-act="studio-slip" data-d="-0.1">−0.1s</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-slip" data-d="-0.0167">−1f</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-slip" data-d="0.0167">+1f</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-slip" data-d="0.1">+0.1s</button></span></div>' +
        '<div class="studio-field"><span class="field-label">Run-up</span><span class="field-inline">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-beats" data-what="pre" data-d="-1">−</button>' +
        '<span class="mono">' + (s.pre / beat).toFixed(s.pre % beat < 0.01 ? 0 : 1) + ' beats · ' + s.pre.toFixed(2) + ' s</span>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-beats" data-what="pre" data-d="1">+</button></span></div>' +
        '<div class="studio-field"><span class="field-label">Length</span><span class="field-inline">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-beats" data-what="duration" data-d="-1">−</button>' +
        '<span class="mono">' + (s.duration / beat).toFixed(s.duration % beat < 0.01 ? 0 : 1) + ' beats · ' + s.duration.toFixed(2) + ' s</span>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-beats" data-what="duration" data-d="1">+</button></span></div>' +
        '<div class="studio-field"><label class="field-label" for="studio-f-speed">Speed</label>' + studio_select_html('studio-f-speed', 'speed', s.speed) +
        (s.stretch ? '<span class="muted studio-small">Run-up slowed to ' + Number(s.stretch[0]).toFixed(2) + '× so its kill reaches its mark; the last ' +
          Number(s.stretch[1]).toFixed(1) + ' s play as recorded' + (Number(s.stretch[2] || 0) > 0 ? ', after its first frame holds ' + Number(s.stretch[2]).toFixed(1) + ' s' : '') +
          '. Choosing a speed replaces it.</span>' : '') + '</div>') +
      studio_grp('trans', 'Transition in',
        (i ? '<div class="studio-field">' + studio_select_html('studio-f-trans', 'transition', s.transition) +
          '<input type="range" id="studio-f-tlen" min="0.1" max="1" step="0.05" value="' + (s.tlen || 0.3) + '"' + (s.transition === 't01' ? ' disabled' : '') + ' aria-label="Transition length">' +
          '<button type="button" class="btn btn-ghost btn-sm studio-add-btn" data-act="studio-tr-all">Use this transition on every cut</button></div>'
          : '<span class="muted">The first shot opens the reel.</span>')) +
      studio_grp('fx', 'Kill effects',
        studio_checks_html('fx', 'kill', s.fx) +
        '<button type="button" class="btn btn-ghost btn-sm studio-add-btn" data-act="studio-fx-all">Use these on every shot</button>',
        s.fx.length ? s.fx.length + ' on' : 'none') +
      studio_grp('hero', 'Hero moment',
        '<label class="studio-check"><input type="checkbox" id="studio-f-hero"' + (s.hero ? ' checked' : '') + '> Make this the hero shot</label>' +
        (s.hero ? studio_checks_html('hero_fx', 'hero', s.hero_fx) +
          '<label class="field-label" for="studio-f-caption">Caption</label><input class="input" id="studio-f-caption" maxlength="40" value="' + esc(s.caption) + '">' : ''),
        s.hero ? 'on' : '') +
      studio_grp('camera', 'Camera move',
        studio_select_html('studio-f-camera', 'camera', s.camera)) +
      '</div>';
    return;
  }
  const styles = (studio.catalog ? studio.catalog.styles : []);
  const pools = p.pools || {};
  const cam = p.cam || {source: 'none'};
  const vertical = p.format === 'vertical';
  const showHandle = (p.overlays || []).indexOf('o07') >= 0;
  const outroLen = Number(p.outro_len || 0);
  box.innerHTML = tabs + '<div class="card-body studio-insp-body">' +
    '<p class="studio-tip">To change one shot\'s kill effects, speed or transition, click that shot on the timeline. Point at any effect to see it.</p>' +
    studio_grp('look', 'Look and shape',
      '<div class="studio-field"><span class="field-label">Format</span>' +
      studio_seg('studio-rfmt', 'fmt', p.format, [['landscape', 'Normal 16:9'], ['vertical', 'Vertical 9:16']]) + '</div>' +
      '<div class="studio-field"><span class="field-label">Framing</span>' +
      studio_seg('studio-rfit', 'fit', p.vfit || 'zoom', [['zoom', 'Zoom to fill'], ['fit', 'Fit the whole picture']]) +
      '<span class="muted studio-small">' + ((p.vfit || 'zoom') === 'fit'
        ? 'All of the game shows, over a blurred copy of itself.'
        : (vertical ? 'The middle of the game fills the tall frame; the sides are cropped.' : 'The game fills the frame.')) + '</span></div>' +
      '<div class="studio-field"><label class="field-label" for="studio-r-style">Style</label>' +
      '<select class="select" id="studio-r-style">' + styles.map(s => '<option value="' + esc(s.key) + '"' + (s.key === p.style ? ' selected' : '') + '>' + esc(s.label) + '</option>').join('') + '</select>' +
      '<button type="button" class="btn btn-sm studio-add-btn" data-act="studio-restyle" id="studio-restyle-btn"' + (studio.busy ? ' disabled' : '') + '>Rebuild with this style</button>' +
      '<span class="muted studio-small">Replans every shot. Undo brings your edits back.</span></div>' +
      '<div class="studio-field"><label class="field-label" for="studio-r-grade">Colour</label>' + studio_select_html('studio-r-grade', 'grade', p.grade) +
      '<label class="studio-check"><input type="checkbox" id="studio-r-vignette"' + (p.vignette ? ' checked' : '') + '> Soft vignette</label></div>') +
    studio_grp('cam', 'Facecam',
      '<div class="studio-field">' +
      studio_seg('studio-cam-src', 'src', cam.source || 'none', [['none', 'None'], ['inset', 'In the video'], ['file', 'Separate video']]) +
      '<span class="muted studio-small">' + (cam.source === 'inset' ? 'Cut out of a corner of the recording itself.'
        : cam.source === 'file' ? 'Its own video file, lined up with each clip.' : 'No facecam in this reel.') + '</span>' +
      '<button type="button" class="btn btn-sm studio-add-btn" data-act="studio-tab-go" data-tab="facecam">' +
      (cam.source === 'none' ? 'Set up a facecam…' : 'Facecam setup…') + '</button></div>' +
      (cam.source && cam.source !== 'none'
        ? (vertical ? '<div class="studio-field"><span class="field-label">Layout</span>' +
            studio_seg('studio-cam-layout', 'layout', cam.layout || 'stack', [['stack', 'Camera on top'], ['corner', 'In a corner']]) + '</div>' : '') +
          (vertical && (cam.layout || 'stack') === 'stack'
            ? '<div class="studio-field"><label class="field-label" for="studio-r-camsplit">Camera height ' + Math.round((cam.split || 0.38) * 100) + '%</label>' +
              '<input type="range" id="studio-r-camsplit" min="0.2" max="0.6" step="0.01" value="' + (cam.split || 0.38) + '"></div>'
            : '<div class="studio-field"><span class="field-label">Where</span><div class="ed-row">' + studio_grid9('studio-cam-pos', cam.pos || [0, 0]) +
              '<label class="field-label" for="studio-r-camsize">Size ' + Math.round((cam.size || 0.3) * 100) + '%</label>' +
              '<input type="range" id="studio-r-camsize" min="0.12" max="0.6" step="0.01" value="' + (cam.size || 0.3) + '"></div>' +
              '<label class="studio-check"><input type="checkbox" id="studio-r-camborder"' + (cam.border !== false ? ' checked' : '') + '> Thin border</label></div>')
        : ''),
      cam.source === 'inset' ? 'in the video' : cam.source === 'file' ? 'separate' : 'off') +
    studio_grp('handle', 'Your handle',
      '<div class="studio-field"><label class="studio-check"><input type="checkbox" id="studio-r-showhandle"' + (showHandle ? ' checked' : '') + '> Show my handle on the reel</label>' +
      '<input class="input" id="studio-r-handle" maxlength="40" placeholder="@yourhandle" value="' + esc(p.handle) + '"></div>' +
      '<div class="studio-field"><span class="field-label">Where</span><div class="ed-row">' + studio_grid9('studio-handle-pos', p.handle_pos || [1, 1]) +
      '<span class="muted studio-small">Or drag it on the picture.</span></div></div>',
      showHandle && p.handle ? p.handle : 'off') +
    studio_grp('ending', 'Opening and ending',
      '<div class="studio-field"><label class="field-label" for="studio-r-intro">Intro</label>' + studio_select_html('studio-r-intro', 'intro', p.intro) +
      studio_introRow(p) + '</div>' +
      '<div class="studio-field"><label class="field-label" for="studio-r-outro">Ending</label>' + studio_select_html('studio-r-outro', 'outro', p.outro) +
      '<label class="field-label" for="studio-r-outrolen">How long it takes</label>' +
      '<select class="select" id="studio-r-outrolen"' + (p.outro === 'e12' ? ' disabled' : '') + '>' +
      STUDIO_OUTRO_LENS.map(o => '<option value="' + o[0] + '"' + (Math.abs(o[0] - outroLen) < 0.01 ? ' selected' : '') + '>' + o[1] + '</option>').join('') + '</select>' +
      '<span class="muted studio-small">' + (p.outro === 'e12' ? 'A hard cut has no length. Pick a fading ending to make it longer.'
        : outroLen ? 'The picture and the song fade together over ' + outroLen + ' s, and the last frame is held if the footage runs out, so the last kill is never faded.'
        : 'Longer endings fade the picture and the song together, and ease rather than stop.') + '</span></div>') +
    studio_grp('pools', 'Effects every shot draws from',
      '<p class="muted studio-small">Each kill gets its own mix from these, never the same as the shot before.</p>' +
      '<span class="field-label">Kill effects</span>' + studio_pool_html('kill', pools.kill || []) +
      '<span class="field-label">Transitions</span>' + studio_pool_html('transition', pools.transition || []) +
      '<span class="field-inline">' +
      '<button type="button" class="btn btn-sm" data-act="studio-mix" data-what="kill">Mix kill effects</button>' +
      '<button type="button" class="btn btn-sm" data-act="studio-mix" data-what="transition">Mix transitions</button>' +
      '<button type="button" class="btn btn-sm" data-act="studio-mix" data-what="all">Mix everything</button></span>' +
      '<span class="field-label">Overlays</span>' + studio_checks_html('overlays', 'overlay', (p.overlays || []).filter(o => o !== 'o07'), ['o07'])) +
    studio_grp('sound', 'Song and sound',
      '<div class="studio-field">' +
      '<span class="muted truncate">' + (p.song ? esc(p.song.split(/[\\/]/).pop()) : 'No song') + '</span>' +
      '<button type="button" class="btn btn-sm studio-add-btn" data-act="studio-edit-song">' + (p.song ? 'Edit the song and mark kills…' : 'Add a song…') + '</button>' +
      (p.song ? '<span class="field-inline"><button type="button" class="btn btn-ghost btn-sm" data-act="studio-offset" data-d="-4">−1 bar</button>' +
        '<span class="mono">starts at ' + studio_secs(p.song_offset) + '</span>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-offset" data-d="4">+1 bar</button></span>' : '') +
      '<label class="field-label" for="studio-r-music">Music ' + p.music_db.toFixed(0) + ' dB</label>' +
      '<input type="range" id="studio-r-music" min="-20" max="6" step="1" value="' + p.music_db + '"' + (p.song ? '' : ' disabled') + '>' +
      '<label class="field-label" for="studio-r-game">Game sound ' + p.game_db.toFixed(0) + ' dB</label>' +
      '<input type="range" id="studio-r-game" min="-20" max="12" step="1" value="' + p.game_db + '">' +
      '<label class="studio-check"><input type="checkbox" id="studio-r-duck"' + (p.duck ? ' checked' : '') + '> Duck the music under gunfire</label></div>') +
    '</div>';
}

function studio_inspectorInput(e) {
  const t = e.target;
  if (!t || !studio.project || !t.closest || !t.closest('#studio-insp')) return;
  const i = studio.sel, p = studio.project;
  const s = i >= 0 ? p.shots[i] : null;
  const pool = t.getAttribute('data-pool');
  if (pool) {
    const vals = Array.prototype.slice.call(studio_el('studio-insp').querySelectorAll('input[data-pool="' + pool + '"]:checked')).map(x => x.value);
    if (!vals.length) { t.checked = true; toast('Keep at least one to choose from.', 'warn'); return; }
    studio_change(pr => { pr.pools = Object.assign({}, pr.pools || {}); pr.pools[pool] = vals; },
                  'The ' + pool + ' effects to choose from');
    studio_mix(pool, false);
    return;
  }
  const list = t.getAttribute('data-list');
  if (list) {
    const vals = Array.prototype.slice.call(studio_el('studio-insp').querySelectorAll('input[data-list="' + list + '"]:checked')).map(x => x.value);
    /* The handle has its own switch, so its overlay is not in this list and
       must survive the list being rewritten. */
    studio_change(pr => {
      if (list === 'overlays') pr.overlays = vals.concat((pr.overlays || []).includes('o07') ? ['o07'] : []);
      else pr.shots[i][list] = vals;
    },
                  list === 'overlays' ? 'Overlays' : studio_shotName(i) + ' · effects', list === 'overlays' ? -1 : i);
    return;
  }
  /* Each edit names itself for the card's list of what is not rendered yet. */
  const map = {
    'studio-f-kill': () => studio_change(pr => { pr.shots[i].kill = Number(t.value); }, studio_shotName(i) + ' · where the kill is', i),
    'studio-f-speed': () => studio_change(pr => { pr.shots[i].speed = t.value; delete pr.shots[i].stretch; }, studio_shotName(i) + ' · speed', i),
    'studio-f-trans': () => studio_change(pr => { pr.shots[i].transition = t.value; pr.shots[i].tlen = 0; }, studio_shotName(i) + ' · transition', i),
    'studio-f-tlen': () => studio_change(pr => { pr.shots[i].tlen = Number(t.value); }, studio_shotName(i) + ' · transition length', i),
    'studio-f-hero': () => studio_change(pr => { const sh = pr.shots[i]; sh.hero = t.checked; if (t.checked && !sh.hero_fx.length) sh.hero_fx = ['h01']; }, studio_shotName(i) + (t.checked ? ' · made a hero shot' : ' · no longer a hero shot'), i),
    'studio-f-caption': () => studio_change(pr => { pr.shots[i].caption = t.value; }, studio_shotName(i) + ' · caption', i),
    'studio-f-camera': () => studio_change(pr => { pr.shots[i].camera = t.value; }, studio_shotName(i) + ' · camera move', i),
    'studio-r-grade': () => studio_change(pr => { pr.grade = t.value; }, 'Colour'),
    'studio-r-vignette': () => studio_change(pr => { pr.vignette = t.checked; }, 'Vignette'),
    'studio-r-intro': () => studio_change(pr => { pr.intro = t.value; }, 'The opening'),
    'studio-r-outro': () => studio_change(pr => { pr.outro = t.value; }, 'The ending'),
    'studio-r-outrolen': () => studio_change(pr => { pr.outro_len = Number(t.value) || 0; }, 'How long the ending takes'),
    'studio-r-camsplit': () => studio_change(pr => { pr.cam = Object.assign({}, pr.cam, {split: Number(t.value)}); }, 'Facecam height'),
    'studio-r-camsize': () => studio_change(pr => { pr.cam = Object.assign({}, pr.cam, {size: Number(t.value)}); }, 'Facecam size'),
    'studio-r-camborder': () => studio_change(pr => { pr.cam = Object.assign({}, pr.cam, {border: t.checked}); }, 'Facecam border'),
    'studio-r-showhandle': () => studio_change(pr => {
      const ov = (pr.overlays || []).filter(o => o !== 'o07');
      pr.overlays = t.checked ? ov.concat(['o07']) : ov;
    }, t.checked ? 'Your handle · shown' : 'Your handle · hidden'),
    'studio-r-handle': () => studio_change(pr => { pr.handle = t.value; }, 'Your handle'),
    'studio-r-music': () => studio_change(pr => { pr.music_db = Number(t.value); }, 'Music level'),
    'studio-r-game': () => studio_change(pr => { pr.game_db = Number(t.value); }, 'Game sound level'),
    'studio-r-duck': () => studio_change(pr => { pr.duck = t.checked; }, 'Ducking the music under gunfire')
  };
  if (s === null && t.id && t.id.indexOf('studio-f-') === 0) return;
  if (map[t.id]) map[t.id]();
}

/* ------------------------------------------------------------ dragging */

function studio_pointerDown(e) {
  const tl = studio_el('studio-tracks');
  if (!studio.project || !tl || !tl.contains(e.target) || e.button !== 0) return;
  const trim = e.target.closest('[data-trim]'), kill = e.target.closest('[data-kill]');
  const shot = e.target.closest('.st-shot');
  if (!trim && !kill && !shot) return;
  const i = Number((trim || kill || shot).getAttribute(trim ? 'data-trim' : kill ? 'data-kill' : 'data-shot'));
  const s = studio.project.shots[i];
  studio.drag = {kind: trim ? 'trim' : kill ? 'kill' : 'move', i: i, x0: e.clientX, moved: false,
                 dur: s.duration, pre: s.pre, snapshot: JSON.stringify(studio.project), pointer: e.pointerId};
  /* Captured on the timeline itself, which survives the redraws a drag does. */
  try { tl.setPointerCapture(e.pointerId); } catch (err) { /* no capture, still works with a mouse */ }
  e.preventDefault();
}

function studio_pointerMove(e) {
  const g = studio.drag;
  if (!g || (g.pointer !== undefined && e.pointerId !== g.pointer)) return;
  const dx = e.clientX - g.x0;
  if (!g.moved && Math.abs(dx) < 4) return;
  g.moved = true;
  const p = studio.project, s = p.shots[g.i], dt = dx / studio.pps, beat = p.beat || 0.5;
  if (g.kind === 'trim') {
    s.duration = Math.max(beat, studio_snapTo(g.dur + dt));
    s.pre = Math.min(s.pre, s.duration);
  } else if (g.kind === 'kill') {
    s.pre = Math.max(0, Math.min(s.duration, studio_snapTo(g.pre + dt)));
  } else {
    const d = studio.derived, last = d.shots.length - 1;
    const mid = d.shots[g.i].start + (d.shots[g.i].end - d.shots[g.i].start) / 2 + dt;
    /* Past either end is "first" or "last", not "nowhere". */
    let to = mid < 0 ? 0 : mid >= d.shots[last].end ? last : g.i;
    d.shots.forEach((r, k) => { if (mid >= r.start && mid < r.end) to = k; });
    if (to !== g.i) {
      const before = d.shots[g.i].start;
      const [moved] = p.shots.splice(g.i, 1);
      p.shots.splice(to, 0, moved);
      g.i = to; studio.sel = to;
      /* Where the moved shot now starts, from the new order -- not where the
         shot it swapped with used to start, which differs by their lengths. */
      studio_localDerive();
      g.x0 += (studio.derived.shots[to].start - before) * studio.pps;
    }
  }
  studio_localDerive();
  studio_drawTimeline();
}

function studio_pointerUp(e) {
  const g = studio.drag;
  if (!g || (e && g.pointer !== undefined && e.pointerId !== g.pointer)) return;
  studio.drag = null;
  if (e && e.type === 'pointercancel') {
    /* The browser took the gesture (a touch pan): put the shot back. */
    if (g.moved) { studio.project = JSON.parse(g.snapshot); studio_localDerive(); studio_drawAll(); }
    return;
  }
  if (!g.moved) { studio_select(g.i); return; }
  studio.gen++;
  studio_pushUndo(g.snapshot);
  studio_touched(studio_shotName(g.i) + (g.kind === 'trim' ? ' · trimmed' : g.kind === 'kill' ? ' · the kill moved' : ' moved'), g.i);
  studio.sel = g.i;
  studio_drawAll();
  studio_check();
}

/* ------------------------------------------------------------ opening */

async function studio_open(path) {
  const r = await API.get('/api/studio/project?path=' + encodeURIComponent(path));
  if (!r || !r.ok) { toast((r && r.error) || 'Could not open that reel.', 'warn'); return; }
  studio.undo = []; studio.sel = -1;
  studio_setProject(r.project, r.derived, r.notes, r.song);
  studio.output = r.project.output; studio.renderedAt = r.when || Date.now();
  studio_settled();
  studio.renderNote = '';
  studio_tab('timeline');
  studio_fit();
  studio_drawAll();
  studio_loadVideo();
}

function studio_tab(which) {
  const view = document.getElementById('view-studio');
  if (view) view.classList.toggle('is-editing', which === 'timeline');
  ['clips', 'timeline', 'song', 'facecam'].forEach(k => {
    studio_show('studio-pane-' + k, k === which);
    const b = studio_el('studio-tab-' + k);
    b.classList.toggle('is-active', k === which);
    b.setAttribute('aria-selected', String(k === which));
  });
  const a = studio_el('studio-sg-audio');
  if (which !== 'song' && a && !a.paused) a.pause();
  if (which === 'timeline') { studio_fitEditor(); studio_fit(); studio_drawAll(); }
  if (which === 'song') studio_sgOpen();
  if (which === 'facecam') studio_fcOpen();
  const fg = studio_el('studio-fc-game');
  if (which !== 'facecam' && fg && !fg.paused) studio_fcPlay();
}

/* ------------------------------------------------------------ the editor */

/* The editor fills the window and nothing else: its height is what the view
   has left below the Studio's own header, so the page never scrolls while
   editing and the tracks are never below the fold. */
function studio_fitEditor() {
  const ed = studio_el('studio-pane-timeline'), host = document.getElementById('views');
  if (!ed || !host || ed.classList.contains('hide')) return;
  const top = ed.getBoundingClientRect().top - host.getBoundingClientRect().top + host.scrollTop;
  const h = Math.max(600, host.clientHeight - top - 20);
  ed.style.setProperty('--ed-h', h + 'px');
  const pl = studio_el('studio-player');
  if (pl && studio.project) pl.classList.toggle('is-vertical', studio.project.format === 'vertical');
  studio_frameDraw();
}

/* WHAT AN EFFECT LOOKS LIKE. The example of the part the pointer is on --
   the same card the parts bin plays -- over the inspector. */
function studio_fxPreview(id) {
  const box = studio_el('studio-fxprev');
  if (!box) return;
  const part = id ? studio_part(id) : null;
  if (!part || !part.id) { return; }
  if (studio.fxShown === id) return;
  studio.fxShown = id;
  if (!studio.examples && !studio.exLoading) {
    studio.exLoading = true;
    studio_binLoad(false).then(() => { studio.exLoading = false; const was = studio.fxShown; studio.fxShown = ''; studio_fxPreview(was); });
  }
  studio_el('studio-fxprev-shot').innerHTML = studio_binShot(id);
  studio_el('studio-fxprev-name').textContent = part.label || id;
  studio_el('studio-fxprev-blurb').textContent = part.blurb || '';
  box.classList.remove('hide');
  const v = box.querySelector('video');
  if (v) { v.preload = 'auto'; v.play().catch(() => {}); }
  document.querySelectorAll('#studio-insp .studio-check-chip.is-previewing').forEach(x => x.classList.remove('is-previewing'));
}

function studio_fxHover(e) {
  const t = e.target;
  if (!t || !t.closest) return;
  const chip = t.closest('#studio-insp .studio-check-chip');
  if (chip) {
    const inp = chip.querySelector('input');
    if (inp) { studio_fxPreview(inp.value); chip.classList.add('is-previewing'); }
    return;
  }
  const sel = t.closest('#studio-insp select');
  if (sel && /^studio-(f|r)-(speed|trans|camera|grade|intro|outro)$/.test(sel.id)) studio_fxPreview(sel.value);
}

/* THE FRAME OVER THE PLAYER: where the handle will be, dragged into place.
   Drawn over the picture the video actually occupies (object-fit leaves bars),
   with the same arithmetic the render uses: the handle's position is a share
   of the room the text leaves, margins included. */
function studio_videoRect() {
  const v = studio_el('studio-video'), pl = studio_el('studio-player');
  if (!v || !pl) return null;
  const W = pl.clientWidth, H = pl.clientHeight;
  const vert = studio.project && studio.project.format === 'vertical';
  const ar = vert ? 9 / 16 : 16 / 9;
  let w = W, h = W / ar;
  if (h > H) { h = H; w = H * ar; }
  return {x: (W - w) / 2, y: (H - h) / 2, w: w, h: h};
}

function studio_frameDraw() {
  const fr = studio_el('studio-frame'), chip = studio_el('studio-handle-chip'), p = studio.project;
  if (!fr || !chip) return;
  const on = !!(p && studio.sel < 0 && (p.overlays || []).indexOf('o07') >= 0 && p.handle);
  fr.classList.toggle('hide', !on);
  if (!on) return;
  const r = studio_videoRect();
  if (!r) return;
  chip.textContent = p.handle;
  /* The reel draws it at 3.2% of the frame's height. */
  chip.style.fontSize = Math.max(9, r.h * 0.032) + 'px';
  const pos = (studio.handleDrag && studio.handleDrag.pos) || p.handle_pos || [1, 1];
  const mx = r.w * 0.025, my = r.h * 0.03;
  const tw = chip.offsetWidth, th = chip.offsetHeight;
  chip.style.left = (r.x + mx + (r.w - tw - 2 * mx) * pos[0]) + 'px';
  chip.style.top = (r.y + my + (r.h - th - 2 * my) * pos[1]) + 'px';
}

function studio_handlePointer(e) {
  const chip = studio_el('studio-handle-chip'), p = studio.project;
  if (!chip || !p) return;
  if (e.type === 'pointerdown') {
    if (e.target !== chip) return;
    const r = studio_videoRect();
    studio.handleDrag = {x0: e.clientX, y0: e.clientY, pos: (p.handle_pos || [1, 1]).slice(),
                         start: (p.handle_pos || [1, 1]).slice(), r: r, id: e.pointerId};
    try { chip.setPointerCapture(e.pointerId); } catch (err) { /* fine */ }
    e.preventDefault();
    return;
  }
  const g = studio.handleDrag;
  if (!g || e.pointerId !== g.id) return;
  const roomX = g.r.w * 0.95 - chip.offsetWidth, roomY = g.r.h * 0.94 - chip.offsetHeight;
  const cl = v => Math.max(0, Math.min(1, v));
  g.pos = [cl(g.start[0] + (e.clientX - g.x0) / Math.max(1, roomX)),
           cl(g.start[1] + (e.clientY - g.y0) / Math.max(1, roomY))];
  if (e.type === 'pointermove') { studio_frameDraw(); return; }
  studio.handleDrag = null;
  const pos = [Math.round(g.pos[0] * 1000) / 1000, Math.round(g.pos[1] * 1000) / 1000];
  if (Math.abs(pos[0] - g.start[0]) + Math.abs(pos[1] - g.start[1]) > 0.002) {
    studio_change(pr => { pr.handle_pos = pos; }, 'Your handle · moved');
  } else studio_frameDraw();
}

/* ------------------------------------------------------------ the facecam tab */

async function studio_fcLoad() {
  const r = await API.get('/api/studio/facecam');
  if (r && r.ok) { studio.fc.inset = r.inset; studio.fc.links = r.links || {}; }
}

/* The run a clip belongs to, the way clips/facecam.py keys its links. */
function studio_fcKey(path) {
  const parts = String(path || '').split(/[\\/]/);
  return parts.length >= 3 && parts[parts.length - 2] === 'clips' ? parts[parts.length - 3] : parts[parts.length - 2] || '';
}

function studio_fcClipRow(path) {
  const lc = String(path).toLowerCase();
  for (const id in studio.clipIndex) {
    const c = studio.clipIndex[id];
    if (String(c.path).toLowerCase() === lc) return c;
  }
  return null;
}

async function studio_fcOpen() {
  await studio_fcLoad();
  const p = studio.project;
  if (!p) return;
  const clips = [];
  const seen = {};
  p.shots.forEach(s => { if (!seen[s.clip]) { seen[s.clip] = 1; clips.push(s); } });
  const sel = studio_el('studio-fc-clip');
  sel.innerHTML = clips.map((s, i) => '<option value="' + i + '">' + esc(s.name) + '</option>').join('');
  studio.fc.clips = clips;
  if (studio.fc.clipI == null || studio.fc.clipI >= clips.length) studio.fc.clipI = 0;
  sel.value = String(studio.fc.clipI);
  const s0 = clips[studio.fc.clipI];
  studio.fc.t = s0 ? Math.max(0, s0.kill - 0.5) : 0;
  studio_fcFrame();
  studio_fcDraw();
}

function studio_fcFrame() {
  const s = (studio.fc.clips || [])[studio.fc.clipI];
  const img = studio_el('studio-fc-img');
  if (!s || !img) return;
  studio.fc.t = Math.max(0, Math.min(Number(s.clip_seconds || 0) - 0.1, studio.fc.t));
  img.onload = () => { studio_fcBox(); studio_fcMock(); };
  img.src = studio_media('/api/studio/thumb', s.clip, '&t=' + studio.fc.t.toFixed(2) + '&w=960');
}

function studio_fcDraw() {
  const p = studio.project;
  if (!p) return;
  const cam = p.cam || {source: 'none'};
  const src = cam.source || 'none';
  studio_el('studio-fc-src').innerHTML = [['none', 'No facecam'], ['inset', 'It is in my recording'], ['file', 'It is a separate video']].map(o =>
    '<button type="button" class="seg-btn' + (o[0] === src ? ' is-active' : '') + '" data-act="studio-cam-src" data-src="' + o[0] + '">' + o[1] + '</button>').join('');
  studio_show('studio-fc-inset', src === 'inset');
  studio_show('studio-fc-file', src === 'file');
  studio_show('studio-fc-none', src === 'none');
  studio_el('studio-fc-layout').innerHTML = src === 'none'
    ? '<p class="muted">Choose where your camera comes from first.</p>'
    : studio_camControls(p, 'fcl');
  if (src === 'inset') studio_fcBox();
  if (src === 'file') studio_fcLinks();
  studio_fcMock();
}

/* The layout controls, for the inspector's Facecam group and this tab alike.
   `pre` keeps their ids apart: both are in the page at once. */
function studio_camControls(p, pre) {
  const cam = p.cam || {}, vertical = p.format === 'vertical';
  const layout = vertical ? (cam.layout || 'stack') : 'corner';
  return (vertical ? '<div class="studio-field"><span class="field-label">Layout</span>' +
      studio_seg('studio-cam-layout', 'layout', layout, [['stack', 'Camera on top, game below'], ['corner', 'Camera in a corner']]) + '</div>'
      : '<p class="muted studio-small">A 16:9 reel keeps the whole game; the camera sits in a corner of it.</p>') +
    (layout === 'stack'
      ? '<div class="studio-field"><label class="field-label" for="studio-' + pre + '-camsplit">Camera height ' + Math.round((cam.split || 0.38) * 100) + '% of the frame</label>' +
        '<input type="range" id="studio-' + pre + '-camsplit" data-cam="split" min="0.2" max="0.6" step="0.01" value="' + (cam.split || 0.38) + '"></div>' +
        '<div class="studio-field"><span class="field-label">The game below it</span>' +
        studio_seg('studio-rfit', 'fit', p.vfit || 'zoom', [['zoom', 'Zoom to fill'], ['fit', 'Fit the whole picture']]) + '</div>'
      : '<div class="studio-field"><span class="field-label">Where</span><div class="ed-row">' + studio_grid9('studio-cam-pos', cam.pos || [0, 0]) +
        '<div class="studio-field"><label class="field-label" for="studio-' + pre + '-camsize">Size ' + Math.round((cam.size || 0.3) * 100) + '% of the width</label>' +
        '<input type="range" id="studio-' + pre + '-camsize" data-cam="size" min="0.12" max="0.6" step="0.01" value="' + (cam.size || 0.3) + '"></div></div>' +
        '<label class="studio-check"><input type="checkbox" id="studio-' + pre + '-camborder" data-cam="border"' + (cam.border !== false ? ' checked' : '') + '> Thin border</label></div>');
}

/* ---- in the video: the box */

function studio_fcBox() {
  const p = studio.project, img = studio_el('studio-fc-img'), box = studio_el('studio-fc-box');
  if (!p || !img || !box) return;
  const b = (studio.fc.drag && studio.fc.drag.box) || ((p.cam || {}).box) || [0, 0, 1, 1];
  const full = b[2] >= 0.999 && b[3] >= 0.999;
  box.classList.toggle('hide', full || !img.naturalWidth);
  box.style.left = (img.offsetLeft + b[0] * img.clientWidth) + 'px';
  box.style.top = (img.offsetTop + b[1] * img.clientHeight) + 'px';
  box.style.width = (b[2] * img.clientWidth) + 'px';
  box.style.height = (b[3] * img.clientHeight) + 'px';
  studio_el('studio-fc-boxnote').textContent = full ? 'No box yet: drag one round your camera.' :
    'Box at ' + Math.round(b[0] * 100) + '%, ' + Math.round(b[1] * 100) + '% · ' + Math.round(b[2] * 100) + '% × ' + Math.round(b[3] * 100) + '% of the frame.';
}

function studio_fcPointer(e) {
  const img = studio_el('studio-fc-img');
  if (!img || !studio.project) return;
  if (e.type === 'pointerdown') {
    if (!e.target.closest || !e.target.closest('#studio-fc-stage')) return;
    const r = img.getBoundingClientRect();
    studio.fc.drag = {r: r, x0: (e.clientX - r.left) / r.width, y0: (e.clientY - r.top) / r.height, id: e.pointerId};
    try { studio_el('studio-fc-stage').setPointerCapture(e.pointerId); } catch (err) { /* fine */ }
    e.preventDefault();
    return;
  }
  const g = studio.fc.drag;
  if (!g || e.pointerId !== g.id) return;
  const cl = v => Math.max(0, Math.min(1, v));
  const x1 = cl((e.clientX - g.r.left) / g.r.width), y1 = cl((e.clientY - g.r.top) / g.r.height);
  g.box = [Math.min(g.x0, x1), Math.min(g.y0, y1), Math.abs(x1 - g.x0), Math.abs(y1 - g.y0)];
  if (e.type === 'pointermove') { studio_fcBox(); studio_fcMock(); return; }
  studio.fc.drag = null;
  if (!g.box || g.box[2] < 0.03 || g.box[3] < 0.03) { studio_fcBox(); return; }   /* a click, not a box */
  const box = g.box.map(v => Math.round(v * 10000) / 10000);
  studio.fc.inset = box;
  API.post('/api/studio/facecam/inset', {box: box});
  studio_change(pr => { pr.cam = Object.assign({}, pr.cam, {source: 'inset', box: box}); }, 'Facecam · the box round it');
}

/* ---- a separate video: the links, and lining one up */

function studio_fcLinks() {
  const p = studio.project, host = studio_el('studio-fc-links');
  if (!p || !host) return;
  const runs = {};
  p.shots.forEach(s => {
    const k = studio_fcKey(s.clip);
    (runs[k] = runs[k] || {key: k, clips: []}).clips.push(s);
  });
  host.innerHTML = Object.keys(runs).map(k => {
    const link = studio.fc.links[k];
    const n = runs[k].clips.length;
    return '<div class="studio-fc-link' + (studio.fc.key === k ? ' is-on' : '') + '">' +
      '<div class="studio-fc-link-text"><strong class="truncate">' + esc(k.indexOf('import-') === 0 ? 'Added clip · ' + k.slice(7) : k) + '</strong>' +
      '<span class="muted studio-small">' + n + (n === 1 ? ' shot' : ' shots') + ' · ' +
      (link ? esc(String(link.file).split(/[\\/]/).pop()) + ' · offset ' + Number(link.offset || 0).toFixed(2) + ' s' : 'no camera video') + '</span></div>' +
      '<span class="field-inline">' +
      '<button type="button" class="btn btn-sm" data-act="studio-fc-attach" data-key="' + esc(k) + '" data-clip="' + esc(runs[k].clips[0].clip) + '">' + (link ? 'Change…' : 'Attach…') + '</button>' +
      (link ? '<button type="button" class="btn btn-sm" data-act="studio-fc-lineup" data-key="' + esc(k) + '" data-clip="' + esc(runs[k].clips[0].clip) + '">Line up</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-fc-unlink" data-key="' + esc(k) + '">Remove</button>' : '') +
      '</span></div>';
  }).join('');
}

async function studio_fcAttach(key, clip) {
  const r = await API.post('/api/clips/pick', {kind: 'video'});
  if (!r || !r.path) return;
  const got = await API.post('/api/studio/facecam/link', {key: key, path: r.path, offset: 0});
  if (!got || !got.ok) { toast((got && got.error) || 'Could not attach that video.', 'warn'); return; }
  studio.fc.links = got.links;
  studio_fcTouched('Facecam · camera video attached');
  studio_fcLineup(key, clip);
  studio_fcSync();
}

async function studio_fcUnlink(key) {
  const got = await API.post('/api/studio/facecam/unlink', {key: key});
  if (got && got.ok) studio.fc.links = got.links;
  if (studio.fc.key === key) { studio.fc.key = ''; studio_show('studio-fc-syncbox', false); }
  studio_fcTouched('Facecam · camera video removed');
}

/* A link lives outside the project, so the timeline cannot see it change.
   An empty edit of `cam` makes the page ask the server again, which is where
   the per-shot facecam files come from, and puts the change on the render list. */
function studio_fcTouched(label) {
  studio_change(pr => { pr.cam = Object.assign({}, pr.cam); }, label);
  studio_fcDraw();
}

function studio_fcLineup(key, clip) {
  const link = studio.fc.links[key];
  if (!link) return;
  studio.fc.key = key; studio.fc.clip = clip;
  const row = studio_fcClipRow(clip);
  /* A link on a session is against its recording; this clip starts `start` into it. */
  studio.fc.start = row && key === studio_fcKey(clip) ? Number(row.start || 0) : 0;
  studio.fc.offset = Number(link.offset || 0);
  const g = studio_el('studio-fc-game'), c = studio_el('studio-fc-cam');
  g.src = studio_media('/api/clips/video', clip);
  c.src = studio_media('/api/studio/facecam/video', link.file);
  studio_show('studio-fc-syncbox', true);
  studio_el('studio-fc-syncnote').textContent = '';
  studio_fcClock();
  studio_fcLinks();
}

function studio_fcCamTime() {
  const g = studio_el('studio-fc-game');
  return (g ? g.currentTime : 0) + studio.fc.start + studio.fc.offset;
}

function studio_fcClock() {
  studio_el('studio-fc-offset').textContent = (studio.fc.offset >= 0 ? '+' : '') + studio.fc.offset.toFixed(2) + ' s';
  const g = studio_el('studio-fc-game');
  studio_el('studio-fc-clock').textContent = studio_secs(g ? g.currentTime : 0);
  studio_el('studio-fc-play').textContent = g && !g.paused ? 'Pause' : 'Play both';
}

function studio_fcPlay() {
  const g = studio_el('studio-fc-game'), c = studio_el('studio-fc-cam');
  if (!g || !c) return;
  if (!g.paused) { g.pause(); c.pause(); studio_fcClock(); return; }
  c.currentTime = Math.max(0, studio_fcCamTime());
  g.play().catch(() => {}); c.play().catch(() => {});
  const tick = () => {
    if (g.paused) { c.pause(); studio_fcClock(); return; }
    /* Two players drift apart; pull the camera back when it is a frame or two out. */
    const want = studio_fcCamTime();
    if (Math.abs(c.currentTime - want) > 0.08) c.currentTime = Math.max(0, want);
    studio_fcClock();
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function studio_fcNudge(d) {
  studio.fc.offset = Math.round((studio.fc.offset + d) * 1000) / 1000;
  const c = studio_el('studio-fc-cam');
  if (c) c.currentTime = Math.max(0, studio_fcCamTime());
  studio_fcClock();
  clearTimeout(studio.fc.saveT);
  studio.fc.saveT = setTimeout(studio_fcSaveOffset, 500);
}

async function studio_fcSaveOffset() {
  const got = await API.post('/api/studio/facecam/offset', {key: studio.fc.key, offset: studio.fc.offset});
  if (got && got.ok) { studio.fc.links = got.links; studio_fcTouched('Facecam · lined up'); }
}

async function studio_fcSync() {
  const btn = studio_el('studio-fc-syncbtn'), note = studio_el('studio-fc-syncnote');
  if (!studio.fc.key) return;
  btn.disabled = true;
  note.textContent = 'Listening to both recordings…';
  const r = await API.post('/api/studio/facecam/sync', {key: studio.fc.key, clip: studio.fc.clip});
  btn.disabled = false;
  if (r && r.ok) {
    studio.fc.offset = Number(r.offset);
    note.textContent = 'Lined up by their sound (confidence ' + r.confidence + '). Play both to check it.';
    await studio_fcSaveOffset();
  } else {
    note.textContent = (r && r.error) || 'Could not line them up.';
  }
  studio_fcClock();
}

/* ---- the mock: the layout drawn from stills, before anything renders */

function studio_fcMock() {
  const cv = studio_el('studio-fc-mock'), p = studio.project, img = studio_el('studio-fc-img');
  if (!cv || !p) return;
  const vertical = p.format === 'vertical';
  const W = vertical ? 1080 : 1920, H = vertical ? 1920 : 1080;
  const scale = vertical ? 0.16 : 0.18;
  cv.width = Math.round(W * scale); cv.height = Math.round(H * scale);
  const x = cv.getContext('2d');
  x.setTransform(scale, 0, 0, scale, 0, 0);
  x.fillStyle = '#000'; x.fillRect(0, 0, W, H);
  const cam = p.cam || {}, have = img && img.naturalWidth;
  const src = cam.source || 'none';
  const lay = studio_camLayout(p.format, W, H, cam, p.vfit || 'zoom', src !== 'none');
  const [gx, gy, gw, gh] = lay.game;
  const drawCover = (sx, sy, sw, sh, dx, dy, dw, dh) => {
    const sa = sw / sh, da = dw / dh;
    let cx = sx, cy = sy, cw = sw, ch = sh;
    if (sa > da) { cw = sh * da; cx = sx + (sw - cw) / 2; } else { ch = sw / da; cy = sy + (sh - ch) / 2; }
    x.drawImage(img, cx, cy, cw, ch, dx, dy, dw, dh);
  };
  if (have) {
    const iw = img.naturalWidth, ih = img.naturalHeight;
    if (lay.fit === 'fit') {
      x.save(); x.filter = 'blur(20px) brightness(0.8)'; drawCover(0, 0, iw, ih, gx, gy, gw, gh); x.restore();
      const k = Math.min(gw / iw, gh / ih);
      x.drawImage(img, gx + (gw - iw * k) / 2, gy + (gh - ih * k) / 2, iw * k, ih * k);
    } else drawCover(0, 0, iw, ih, gx, gy, gw, gh);
    if (lay.cam) {
      const [cx, cy, cw, ch] = lay.cam;
      if (src === 'inset') {
        const b = cam.box || [0, 0, 1, 1];
        drawCover(b[0] * iw, b[1] * ih, b[2] * iw, b[3] * ih, cx, cy, cw, ch);
      } else {
        x.fillStyle = '#2a2f3a'; x.fillRect(cx, cy, cw, ch);
        x.fillStyle = '#9aa3b2'; x.font = 'bold ' + Math.round(ch * 0.12) + 'px sans-serif';
        x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText('CAMERA', cx + cw / 2, cy + ch / 2);
      }
      if (cam.border !== false && lay.cam[2] < W) { x.strokeStyle = 'rgba(255,255,255,.9)'; x.lineWidth = 6; x.strokeRect(cx, cy, cw, ch); }
    }
  }
}

/* The same arithmetic as clips/facecam.py layout(), for the mock only: the
   render asks the server, which is the one that has to be right. */
function studio_camLayout(fmt, W, H, cam, fit, has) {
  const even = v => Math.max(2, Math.round(v / 2) * 2);
  const out = {fit: fit === 'fit' ? 'fit' : 'zoom', game: [0, 0, W, H], cam: null};
  if (!has) return out;
  if (fmt === 'vertical' && (cam.layout || 'stack') === 'stack') {
    const ch = even(H * (cam.split || 0.38));
    out.cam = [0, 0, W, ch]; out.game = [0, ch, W, H - ch];
    return out;
  }
  const b = cam.box || [0, 0, 1, 1];
  const aspect = (b[3] / Math.max(b[2], 1e-3)) / (16 / 9);
  let cw = even(W * (cam.size || 0.3)), ch = even(cw * aspect);
  if (ch > H * 0.7) { ch = even(H * 0.7); cw = even(ch / Math.max(aspect, 1e-3)); }
  const m = even(Math.min(W, H) * 0.03), pos = cam.pos || [0, 0];
  out.cam = [even(m + (W - cw - 2 * m) * pos[0]), even(m + (H - ch - 2 * m) * pos[1]), cw, ch];
  return out;
}

/* The layout controls' inputs, wherever they are. */
function studio_camInput(e) {
  const t = e.target;
  const what = t && t.getAttribute && t.getAttribute('data-cam');
  if (!what || !studio.project || !t.closest('#view-studio')) return;
  if (t.closest('#studio-insp')) return;           /* the inspector's own handler has it */
  const v = what === 'border' ? t.checked : Number(t.value);
  if (e.type === 'input' && what !== 'border') {
    /* Live while dragging, into the mock only; the edit lands on release. */
    studio.project.cam = Object.assign({}, studio.project.cam, {[what]: v});
    studio_fcMock();
    return;
  }
  studio_change(pr => { pr.cam = Object.assign({}, pr.cam, {[what]: v}); }, 'Facecam · ' + what);
}

/* ------------------------------------------------------------ your own clips */

async function studio_impAdd() {
  const r = await API.post('/api/clips/pick', {kind: 'video'});
  if (!r || !r.path) return;
  toast('Adding ' + r.path.split(/[\\/]/).pop() + '…');
  const got = await API.post('/api/studio/import', {path: r.path});
  if (!got || !got.ok) { toast((got && got.error) || 'Could not add that clip.', 'warn'); return; }
  await studio_impOpen(got.clip.path, true);
}

async function studio_impGames() {
  if (studio.imp.games) return studio.imp.games;
  const r = await API.get('/api/clips/games');
  studio.imp.games = (r && r.games) || (Array.isArray(r) ? r : []);
  return studio.imp.games;
}

async function studio_impOpen(path, fresh) {
  const info = await API.post('/api/studio/import/info', {path: path});
  if (!info || !info.ok) { toast((info && info.error) || 'Could not open that clip.', 'warn'); return; }
  const imp = studio.imp;
  imp.path = path; imp.seconds = Number(info.seconds) || 0; imp.kills = (info.kills || []).slice();
  imp.fresh = !!fresh; imp.dirty = false; imp.sel = -1;
  const games = await studio_impGames();
  const gsel = studio_el('studio-imp-game');
  gsel.innerHTML = games.map(g => '<option value="' + esc(g.game_key) + '" data-name="' + esc(g.game) + '"' +
    (g.game === info.game ? ' selected' : '') + '>' + esc(g.game) + '</option>').join('') +
    '<option value=""' + (games.some(g => g.game === info.game) ? '' : ' selected') + ' data-name="Other">Another game (mark by hand)</option>';
  studio_el('studio-imp-name').value = info.title || '';
  studio_el('studio-imp-presets').innerHTML = (info.presets || []).map(t =>
    '<button type="button" class="reel-chip" data-act="studio-imp-preset" data-t="' + esc(t) + '">' + esc(t) + '</button>').join('');
  studio_el('studio-imp-title').textContent = fresh ? 'Added · mark its kills' : 'Your clip';
  studio_el('studio-imp-detnote').textContent = '';
  studio_el('studio-imp-msg').textContent = '';
  const v = studio_el('studio-imp-video');
  v.src = studio_media('/api/clips/video', path);
  studio_show('studio-imp-scrim', true);
  studio_impDraw();
}

function studio_impDraw() {
  const imp = studio.imp, v = studio_el('studio-imp-video');
  imp.kills.sort((a, b) => a - b);
  studio_el('studio-imp-kills').innerHTML = imp.kills.length
    ? imp.kills.map((k, i) => '<span class="reel-chip' + (i === imp.sel ? ' is-on' : '') + '" data-act="studio-imp-seek" data-i="' + i + '">' +
        (i + 1) + ' · ' + studio_secs(k) + ' <button type="button" class="studio-imp-x" data-act="studio-imp-drop" data-i="' + i + '" aria-label="Remove kill ' + (i + 1) + '">×</button></span>').join('')
    : '<span class="muted studio-small">No kills marked yet.</span>';
  const t = v ? v.currentTime || 0 : 0;
  studio_el('studio-imp-clock').textContent = studio_secs(t);
  studio_el('studio-imp-play').textContent = v && !v.paused ? 'Pause' : 'Play';
  const c = studio_sgCanvas('studio-imp-lane', 46);
  if (!c) return;
  const {ctx, W, H} = c, dur = imp.seconds || (v && v.duration) || 1, X = s => s / dur * W;
  ctx.fillStyle = studio_tok('--surface-sunken') || '#111'; ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = studio_tok('--border-subtle') || '#333';
  for (let s = 0; s <= dur; s += 1) ctx.fillRect(X(s), H - 8, 1, 8);
  imp.kills.forEach((k, i) => {
    ctx.fillStyle = i === imp.sel ? studio_tok('--warn') || '#e3b341' : studio_tok('--accent') || '#5aa9ff';
    ctx.save(); ctx.translate(X(k), H / 2); ctx.rotate(Math.PI / 4); ctx.fillRect(-6, -6, 12, 12); ctx.restore();
    ctx.fillStyle = '#fff'; ctx.font = 'bold 11px sans-serif'; ctx.fillText(String(i + 1), X(k) + 9, 14);
  });
  ctx.fillStyle = '#ff5c5c'; ctx.fillRect(X(t) - 1, 0, 2, H);
}

function studio_impMark() {
  const v = studio_el('studio-imp-video'), imp = studio.imp;
  if (!v) return;
  const t = Math.round(v.currentTime * 1000) / 1000;
  if (imp.kills.some(k => Math.abs(k - t) < 0.05)) return;
  if (imp.kills.length >= 12) { toast('Twelve kills is the most one clip can carry.', 'warn'); return; }
  imp.kills.push(t); imp.dirty = true;
  studio_impDraw();
}

async function studio_impDetect() {
  const gsel = studio_el('studio-imp-game'), opt = gsel.selectedOptions[0];
  const note = studio_el('studio-imp-detnote'), btn = studio_el('studio-imp-detect');
  if (!gsel.value) { note.textContent = 'AutoStream has no kill detector for another game. Mark them by hand while it plays.'; return; }
  btn.disabled = true;
  note.textContent = 'Reading the kills…';
  let st = await API.post('/api/studio/import/detect', {path: studio.imp.path, game_key: gsel.value, game: opt ? opt.getAttribute('data-name') : ''});
  while (st && st.state === 'running') {
    note.textContent = 'Reading the kills' + (st.total ? ' · ' + st.done + ' of ' + st.total : '') + '…';
    await new Promise(r => setTimeout(r, 700));
    st = await API.get('/api/studio/import/detect/status');
  }
  btn.disabled = false;
  if (!st) { note.textContent = 'Detection stopped.'; return; }
  note.textContent = st.message || '';
  if (st.state === 'done' && (st.kills || []).length) {
    const had = studio.imp.kills;
    /* What it found is a proposal: kept beside anything marked by hand. */
    (st.kills || []).forEach(k => { if (!had.some(h => Math.abs(h - k) < 0.3)) had.push(k); });
    studio.imp.dirty = true;
    studio_impDraw();
  }
}

async function studio_impSave(close) {
  const imp = studio.imp, gsel = studio_el('studio-imp-game'), opt = gsel.selectedOptions[0];
  const got = await API.post('/api/studio/import/save', {path: imp.path, kills: imp.kills,
    title: studio_el('studio-imp-name').value, game: opt ? opt.getAttribute('data-name') : ''});
  if (!got || !got.ok) { studio_el('studio-imp-msg').textContent = (got && got.error) || 'Could not save.'; return false; }
  imp.dirty = false;
  if (!got.kills.length) toast('Saved without kills: mark at least one, or the reel has nothing to cut to.', 'warn');
  else toast('Saved ' + got.kills.length + (got.kills.length === 1 ? ' kill.' : ' kills.'), 'ok');
  if (close) studio_impClose(true);
  studio_load(true);
  return true;
}

function studio_impClose(force) {
  const imp = studio.imp;
  if (!force && imp.dirty && !confirm('Close without saving the kills you marked?')) return;
  const v = studio_el('studio-imp-video');
  if (v) { v.pause(); v.removeAttribute('src'); v.load(); }
  /* A detection this dialog started has nothing left to report to. */
  API.post('/api/studio/import/detect/cancel', {});
  studio_show('studio-imp-scrim', false);
}

function studio_impKey(e) {
  if (studio_el('studio-imp-scrim').classList.contains('hide')) return false;
  const a = document.activeElement;
  if (a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) && a.type !== 'range') return false;
  const v = studio_el('studio-imp-video');
  if (e.key === 'k' || e.key === 'K') { studio_impMark(); }
  else if (e.key === ' ') { if (v.paused) v.play().catch(() => {}); else v.pause(); }
  else if (e.key === ',') { v.pause(); v.currentTime = Math.max(0, v.currentTime - 1 / 30); }
  else if (e.key === '.') { v.pause(); v.currentTime = Math.min(v.duration || 1e9, v.currentTime + 1 / 30); }
  else if (e.key === 'Escape') { studio_impClose(false); }
  else return false;
  e.preventDefault();
  return true;
}

/* ------------------------------------------------------------ wiring */

function studio_wire() {
  if (studio.wired) return;
  studio.wired = true;
  document.addEventListener('click', e => {
    const b = e.target.closest ? e.target.closest('[data-act^="studio-"]') : null;
    if (!b || !b.closest('#view-studio')) return;
    const act = b.getAttribute('data-act');
    const p = studio.project;
    if (act === 'studio-tab') studio_tab(b.getAttribute('data-tab'));
    else if (act === 'studio-edit-song') studio_tab('song');
    else if (act === 'studio-refresh') studio_load(true);
    else if (act === 'studio-game') { studio.game = b.getAttribute('data-game'); studio_renderLib(); }
    else if (act === 'studio-pick') studio_pick(b.getAttribute('data-clip'), e.shiftKey);
    else if (act === 'studio-folder') studio_folderToggle(b.getAttribute('data-folder'));
    else if (act === 'studio-preview') studio_preview(b.getAttribute('data-clip'));
    else if (act === 'studio-preview-close') studio_closeModals();
    else if (act === 'studio-make-cancel') studio_buildCancel();
    else if (act === 'studio-clear') { studio.selected = []; studio.adding = null; studio_syncSelection(); }
    else if (act === 'studio-make') studio_openMake();
    else if (act === 'studio-style') {
      /* A style is a template: taking one drops the picks dealt over the last. */
      studio.style = b.getAttribute('data-style');
      studio.picks = null;
      studio_renderStyles(); studio_hand(); studio_binDraw();
    }
    else if (act === 'studio-sg-song') studio_sgUseSong(b.getAttribute('data-path'));
    else if (act === 'studio-sg-win') studio_svWin(Number(b.getAttribute('data-win')) || 8);
    else if (act === 'studio-sg-lane') studio_svToggle(b.getAttribute('data-lane'));
    else if (act === 'studio-fav') studio_fav(b.getAttribute('data-clip'));
    else if (act === 'studio-fav-selected') studio_favSelected();
    else if (act === 'studio-bin-pick') studio_binPick(b.getAttribute('data-kind'), b.getAttribute('data-part'));
    else if (act === 'studio-bin-fav') studio_binFav(b.getAttribute('data-part'));
    else if (act === 'studio-bin-favonly') studio_binFavOnly();
    else if (act === 'studio-shape') studio_shapeNudge(b.getAttribute('data-dial'), Number(b.getAttribute('data-by')));
    else if (act === 'studio-shape-reset') studio_shapeReset();
    else if (act === 'studio-arrange') studio_arrangePick(b.getAttribute('data-how'));
    else if (act === 'studio-pin') studio_pin(b.getAttribute('data-slot'), b.getAttribute('data-clip'));
    else if (act === 'studio-hand-next') studio_handNext(b.getAttribute('data-kind'));
    else if (act === 'studio-deal') studio_deal();
    else if (act === 'studio-deal-reset') studio_dealReset();
    else if (act === 'studio-bin-build') studio_binBuild();
    else if (act === 'studio-bin-stop') studio_binStop();
    else if (act === 'studio-song') studio_pickSong();
    else if (act === 'studio-nosong') {
      studio.song = ''; studio.songShape = null;
      studio_el('studio-song-name').textContent = 'No song: the clips keep their own sound, cut to a 120 BPM grid.';
      studio_mkDefault();
    }
    else if (act === 'studio-mk-mode') { studio.mk.mode = b.getAttribute('data-mode'); studio_mkDraw(); }
    else if (act === 'studio-mk-nudge') studio_mkNudge(b.getAttribute('data-what'), b.getAttribute('data-d') === 'bar' ? 'bar' : '-bar');
    else if (act === 'studio-mk-preset') studio_mkPreset(b.getAttribute('data-preset'));
    else if (act === 'studio-mk-play') studio_mkPlay();
    else if (act === 'studio-mk-skip') studio_mkSkip(Number(b.getAttribute('data-d')) || 0);
    else if (act === 'studio-mk-restart') studio_mkSeek(studio_mkSpan().start);
    else if (act === 'studio-yt') studio_ytOpen(b.getAttribute('data-for'));
    else if (act === 'studio-yt-go') studio_ytGo();
    else if (act === 'studio-yt-close') studio_ytClose();
    else if (act === 'studio-add') studio_addClips();
    else if (act === 'studio-add-cancel') { studio.adding = null; studio.selected = []; studio_syncSelection(); }
    else if (act === 'studio-delete') studio_deleteAsk();
    else if (act === 'studio-del-cancel') studio_closeModals();
    else if (act === 'studio-del-go') studio_deleteGo();
    else if (act === 'studio-intro-open') studio_introOpen();
    else if (act === 'studio-intro-off') studio_introOff(false);
    else if (act === 'studio-intro-add') studio_introAdd();
    else if (act === 'studio-intro-pick') studio_introChoose(b.getAttribute('data-path'), false);
    else if (act === 'studio-intro-del') studio_introDelete(b.getAttribute('data-path'), b.getAttribute('data-name'));
    else if (act === 'studio-intro-play') studio_introPlay();
    else if (act === 'studio-intro-nudge') {
      const what = b.getAttribute('data-what'), d = Number(b.getAttribute('data-d')) || 0;
      studio_introSet(what, (what === 'start' ? studio.intro.start : studio.intro.end) + d);
    }
    else if (act === 'studio-intro-here') {
      const v = studio_el('studio-intro-video');
      studio_introSet(b.getAttribute('data-what'), v ? v.currentTime : 0);
    }
    else if (act === 'studio-intro-whole') {
      studio.intro.start = 0; studio.intro.end = studio.intro.seconds; studio_introDraw();
    }
    else if (act === 'studio-intro-fit-lead') {
      const lead = studio.derived ? Number(studio.derived.lead_in || 0) : 0;
      const iv = studio.intro;
      /* From the start of the trim, as far as the clip can reach. A clip
         shorter than the lead-in fills what it can and says so. */
      iv.end = Math.min(iv.seconds, iv.start + lead);
      if (iv.end - iv.start < lead - 0.05) {
        toast('This clip is ' + (iv.end - iv.start).toFixed(1) + ' s — shorter than the ' +
              lead.toFixed(1) + ' s lead-in. The rest is the opener.', 'warn');
      }
      studio_introDraw();
    }
    else if (act === 'studio-intro-fit') { studio.intro.fit = b.getAttribute('data-fit'); studio_introDraw(); }
    else if (act === 'studio-intro-use') studio_introUse();
    else if (act === 'studio-intro-clear') studio_introOff(false);
    else if (act === 'studio-intro-cancel') studio_introClose();
    else if (act === 'studio-reel-del') studio_reelDeleteAsk(b.getAttribute('data-path'), b.getAttribute('data-name'));
    else if (act === 'studio-rdel-cancel') { studio.reelDel = ''; studio_show('studio-rdel-scrim', false); }
    else if (act === 'studio-rdel-go') studio_reelDeleteGo();
    else if (act === 'studio-fmt' || act === 'studio-order') {
      const key = act === 'studio-fmt' ? 'fmt' : 'order';
      studio[key] = b.getAttribute('data-' + key);
      b.parentElement.querySelectorAll('.seg-btn').forEach(x => x.classList.toggle('is-active', x === b));
      if (key === 'fmt') studio_mkDefault();
    }
    else if (act === 'studio-build') studio_build();
    else if (act === 'studio-open') studio_open(b.getAttribute('data-path'));
    else if (act === 'studio-watch') {
      studio_el('studio-preview-title').textContent = b.closest('.studio-reel').querySelector('.studio-reel-name').textContent;
      const v = studio_el('studio-preview-video');
      v.src = studio_media('/api/clips/video', b.getAttribute('data-path'));
      studio_show('studio-preview-scrim', true);
      v.play().catch(() => {});
    }
    else if (act === 'studio-render') studio_render();
    else if (act === 'studio-cancel') API.post('/api/studio/cancel', {}).then(studio_poll);
    else if (act === 'studio-undo') studio_undo();
    else if (act === 'studio-show') { if (studio.output && typeof clip_reveal === 'function') clip_reveal(studio.output); }
    else if (act === 'studio-play') {
      const v = studio_el('studio-video');
      if (v.src) { if (v.paused) v.play().catch(() => {}); else v.pause(); }
    }
    else if (act === 'studio-zoom') {
      const z = Number(b.getAttribute('data-z'));
      if (z === 0) { studio_fit(); studio_drawTimeline(); }
      else studio_zoomAt(studio.pps * (z > 0 ? 1.5 : 1 / 1.5), studio_anchorX());
    }
    else if (act === 'studio-seek') {
      const v = studio_el('studio-video');
      const box = b.getBoundingClientRect();
      if (v.src) v.currentTime = Math.max(0, (e.clientX - box.left) / studio.pps);
      studio_playhead();
    }
    else if (act === 'studio-select') studio_select(Number(b.getAttribute('data-shot')));
    else if (act === 'studio-move' && p) {
      const d = Number(b.getAttribute('data-d')), i = studio.sel, j = i + d;
      if (j < 0 || j >= p.shots.length) return;
      studio_forgetShots();
      studio_change(pr => { const t = pr.shots[i]; pr.shots[i] = pr.shots[j]; pr.shots[j] = t; },
                    'Shots reordered');
      studio.sel = j; studio_drawAll();
    }
    else if (act === 'studio-remove' && p) {
      if (p.shots.length <= 1) { toast('A reel needs at least one shot.', 'warn'); return; }
      const i = studio.sel;
      const gone = studio_shotName(i);
      studio_forgetShots();
      studio_change(pr => { pr.shots.splice(i, 1); }, gone + ' removed');
      studio.sel = Math.min(i, p.shots.length - 1); studio_drawAll();
    }
    else if (act === 'studio-slip' && p) {
      const d = Number(b.getAttribute('data-d')), i = studio.sel;
      studio_change(pr => { const s = pr.shots[i]; s.kill = Math.max(0, Math.min(s.clip_seconds, s.kill + d)); },
                    studio_shotName(i) + ' · where the kill is', i);
    }
    else if (act === 'studio-beats' && p) {
      const what = b.getAttribute('data-what'), d = Number(b.getAttribute('data-d')), beat = p.beat || 0.5, i = studio.sel;
      studio_change(pr => {
        const s = pr.shots[i];
        if (what === 'pre') s.pre = Math.max(0, Math.min(s.duration, s.pre + d * beat));
        else { s.duration = Math.max(beat, s.duration + d * beat); s.pre = Math.min(s.pre, s.duration); }
      }, studio_shotName(i) + (what === 'pre' ? ' · the run-up to the kill' : ' · length'), i);
    }
    else if (act === 'studio-offset' && p) {
      const d = Number(b.getAttribute('data-d')), beat = p.beat || 0.5;
      studio_change(pr => { pr.song_offset = Math.max(0, pr.song_offset + d * beat); }, 'Where the song starts');
    }
    else if (act === 'studio-rfmt' && p) studio_change(pr => { pr.format = b.getAttribute('data-fmt'); },
      'Format · ' + (b.getAttribute('data-fmt') === 'vertical' ? '9:16' : '16:9'));
    else if (act === 'studio-rfit' && p) studio_change(pr => { pr.vfit = b.getAttribute('data-fit'); },
      'Framing · ' + (b.getAttribute('data-fit') === 'fit' ? 'fit the whole picture' : 'zoom to fill'));
    else if (act === 'studio-cam-src' && p) {
      const src = b.getAttribute('data-src');
      studio_change(pr => {
        pr.cam = Object.assign({}, pr.cam, {source: src});
        /* The box drawn last time, so a streamer whose camera is always in
           the same corner draws it once, ever. */
        if (src === 'inset' && studio.fc.inset && !(pr.cam.box && pr.cam.box[2] < 1)) pr.cam.box = studio.fc.inset.slice();
      }, 'Facecam · ' + (src === 'none' ? 'off' : src === 'inset' ? 'in the video' : 'separate video'));
      if (src !== 'none' && !(src === 'inset' && studio.fc.inset)) studio_tab('facecam');
    }
    else if (act === 'studio-cam-layout' && p) studio_change(pr => { pr.cam = Object.assign({}, pr.cam, {layout: b.getAttribute('data-layout')}); },
      'Facecam layout');
    else if (act === 'studio-cam-pos' && p) studio_change(pr => {
      pr.cam = Object.assign({}, pr.cam, {pos: [Number(b.getAttribute('data-x')), Number(b.getAttribute('data-y'))]});
    }, 'Facecam position');
    else if (act === 'studio-handle-pos' && p) studio_change(pr => {
      pr.handle_pos = [Number(b.getAttribute('data-x')), Number(b.getAttribute('data-y'))];
    }, 'Your handle · moved');
    else if (act === 'studio-tab-go') studio_tab(b.getAttribute('data-tab'));
    else if (act === 'studio-fc-frame') { studio.fc.t += Number(b.getAttribute('data-d')); studio_fcFrame(); }
    else if (act === 'studio-fc-boxreset' && p) studio_change(pr => { pr.cam = Object.assign({}, pr.cam, {box: [0, 0, 1, 1]}); }, 'Facecam · box cleared');
    else if (act === 'studio-fc-attach') studio_fcAttach(b.getAttribute('data-key'), b.getAttribute('data-clip'));
    else if (act === 'studio-fc-unlink') studio_fcUnlink(b.getAttribute('data-key'));
    else if (act === 'studio-fc-lineup') studio_fcLineup(b.getAttribute('data-key'), b.getAttribute('data-clip'));
    else if (act === 'studio-fc-play') studio_fcPlay();
    else if (act === 'studio-fc-nudge') studio_fcNudge(Number(b.getAttribute('data-d')));
    else if (act === 'studio-fc-sync') studio_fcSync();
    else if (act === 'studio-imp-add') studio_impAdd();
    else if (act === 'studio-imp-edit') studio_impOpen(b.getAttribute('data-path'), false);
    else if (act === 'studio-imp-play') { const v = studio_el('studio-imp-video'); if (v.paused) v.play().catch(() => {}); else v.pause(); }
    else if (act === 'studio-imp-step') { const v = studio_el('studio-imp-video'); v.pause(); v.currentTime = Math.max(0, v.currentTime + Number(b.getAttribute('data-d'))); }
    else if (act === 'studio-imp-mark') studio_impMark();
    else if (act === 'studio-imp-clear') { studio.imp.kills = []; studio.imp.dirty = true; studio_impDraw(); }
    else if (act === 'studio-imp-drop') { e.stopPropagation(); studio.imp.kills.splice(Number(b.getAttribute('data-i')), 1); studio.imp.sel = -1; studio.imp.dirty = true; studio_impDraw(); }
    else if (act === 'studio-imp-seek') { const i = Number(b.getAttribute('data-i')); studio.imp.sel = i; const v = studio_el('studio-imp-video'); v.pause(); v.currentTime = studio.imp.kills[i]; studio_impDraw(); }
    else if (act === 'studio-imp-preset') { studio_el('studio-imp-name').value = b.getAttribute('data-t'); studio.imp.dirty = true; }
    else if (act === 'studio-imp-detect') studio_impDetect();
    else if (act === 'studio-imp-save') studio_impSave(true);
    else if (act === 'studio-imp-close') studio_impClose(false);
    else if (act === 'studio-restyle' && p) studio_restyle();
    else if (act === 'studio-mix' && p) studio_mix(b.getAttribute('data-what'), true);
    else if (act === 'studio-fx-all' && p && studio.sel >= 0) {
      const fx = p.shots[studio.sel].fx.slice();
      studio_change(pr => { pr.shots.forEach(s => { s.fx = fx.slice(); }); }, 'The same kill effect on every shot');
      toast('Every shot now uses ' + (fx.length ? fx.map(id => studio_part(id).label).join(' + ') : 'no kill effect') + '.', 'ok');
    }
    else if (act === 'studio-tr-all' && p && studio.sel > 0) {
      const t = p.shots[studio.sel].transition, len = p.shots[studio.sel].tlen;
      studio_change(pr => { pr.shots.forEach((s, k) => { if (k) { s.transition = t; s.tlen = len; } }); },
                    'The same transition on every cut');
      toast('Every cut is now ' + studio_part(t).label + '.', 'ok');
    }
    else if (act === 'studio-sg-pick') studio_sgPick();
    else if (act === 'studio-sg-none') studio_sgApply(true);
    else if (act === 'studio-sg-play') studio_sgPlay();
    else if (act === 'studio-sg-mark') studio_sgMark();
    else if (act === 'studio-sg-fromkills') studio_sgFromKills();
    else if (act === 'studio-sg-marknudge') studio_sgNudgeMark(b.getAttribute('data-d'));
    else if (act === 'studio-sg-markplay') studio_sgHearMark();
    else if (act === 'studio-sg-markdrop') studio_sgDropMark();
    else if (act === 'studio-sg-unmark') { studio.sg.marks.pop(); studio.sg.sel = -1; studio_sgDraw(); }
    else if (act === 'studio-sg-clearmarks') { studio.sg.marks = []; studio.sg.sel = -1; studio_sgDraw(); }
    else if (act === 'studio-sg-nudge') studio_sgNudge(b.getAttribute('data-what'), b.getAttribute('data-d'));
    else if (act === 'studio-sg-snapbar') studio_sgSnapBar();
    else if (act === 'studio-sg-atdrop') studio_sgAtDrop();
    else if (act === 'studio-sg-fit') studio_sgFit();
    else if (act === 'studio-sg-apply') studio_sgApply(false);
  });
  document.addEventListener('change', studio_inspectorInput);
  document.addEventListener('change', studio_camInput);
  document.addEventListener('input', studio_camInput);
  /* The inspector's groups remember whether they are open (toggle does not
     bubble, so it is caught on the way down). */
  document.addEventListener('toggle', e => {
    const d = e.target;
    if (d && d.matches && d.matches('#studio-insp details.ed-group')) studio.grpOpen[d.getAttribute('data-grp')] = d.open;
  }, true);
  document.addEventListener('mouseover', studio_fxHover);
  document.addEventListener('focusin', studio_fxHover);
  document.addEventListener('change', e => { if (e.target && e.target.closest && e.target.closest('#studio-insp select')) { studio.fxShown = ''; studio_fxHover(e); } });
  ['pointerdown', 'pointermove', 'pointerup', 'pointercancel'].forEach(ev => {
    const chip = studio_el('studio-handle-chip');
    if (chip) chip.addEventListener(ev, studio_handlePointer);
    const st = studio_el('studio-fc-stage');
    if (st) st.addEventListener(ev, studio_fcPointer);
  });
  window.addEventListener('resize', () => { studio_fitEditor(); studio_fcBox(); });
  const fsel = studio_el('studio-fc-clip');
  if (fsel) fsel.addEventListener('change', () => {
    studio.fc.clipI = Number(fsel.value);
    const s0 = (studio.fc.clips || [])[studio.fc.clipI];
    studio.fc.t = s0 ? Math.max(0, s0.kill - 0.5) : 0;
    studio_fcFrame();
  });
  const iv = studio_el('studio-imp-video');
  if (iv) ['timeupdate', 'play', 'pause', 'seeked', 'loadedmetadata'].forEach(ev => iv.addEventListener(ev, () => {
    if (ev === 'play') { const tick = () => { studio_impDraw(); if (!iv.paused) requestAnimationFrame(tick); }; requestAnimationFrame(tick); }
    studio_impDraw();
  }));
  const ilane = studio_el('studio-imp-lane');
  if (ilane) ilane.addEventListener('pointerdown', e => {
    const r = ilane.getBoundingClientRect(), v = studio_el('studio-imp-video');
    v.currentTime = Math.max(0, (e.clientX - r.left) / r.width * (studio.imp.seconds || v.duration || 0));
  });
  const iname = studio_el('studio-imp-name');
  if (iname) iname.addEventListener('input', () => { studio.imp.dirty = true; });
  const fv = studio_el('studio-fc-game');
  if (fv) fv.addEventListener('seeked', () => { const c = studio_el('studio-fc-cam'); if (c && fv.paused) c.currentTime = Math.max(0, studio_fcCamTime()); studio_fcClock(); });
  document.addEventListener('change', e => {
    const b = e.target && e.target.closest ? e.target.closest('[data-act="studio-bin-slot"]') : null;
    if (!b) return;
    studio.binOn = studio.binOn || {};
    studio.binOn[b.getAttribute('data-kind')] = b.checked;
    studio_binSlots();
  });
  /* The music lane draws only what is on screen, so scrolling redraws it --
     once a frame, because a scroll fires far more often than that. */
  const sc = studio_el('studio-scroll');
  if (sc) sc.addEventListener('scroll', () => {
    if (studio.waveTick) return;
    studio.waveTick = requestAnimationFrame(() => { studio.waveTick = 0; studio_drawWave(); });
  });
  const tlbox = studio_el('studio-tl');
  if (tlbox) tlbox.addEventListener('wheel', studio_wheel, {passive: false});
  ['studio-tl-spec', 'studio-tl-marks'].forEach(id => {
    const c = studio_el(id);
    if (c) c.addEventListener('change', () => {
      studio.showSpec = studio_el('studio-tl-spec').checked;
      studio.showMarks = studio_el('studio-tl-marks').checked;
      studio_drawWave(); studio_syncNote();
    });
  });
  const mkw = studio_el('studio-mk-wave');
  if (mkw) ['pointerdown', 'pointermove', 'pointerup', 'pointercancel'].forEach(ev => mkw.addEventListener(ev, studio_mkPointer));
  const mka = studio_el('studio-mk-audio');
  if (mka) ['play', 'pause', 'timeupdate', 'loadedmetadata', 'seeked'].forEach(ev => mka.addEventListener(ev, studio_mkAudio));
  const mks = studio_el('studio-mk-seek');
  if (mks) mks.addEventListener('input', studio_mkSeekInput);
  const yti = studio_el('studio-yt-url');
  if (yti) yti.addEventListener('keydown', studio_ytKey);
  const q = studio_el('studio-q');
  if (q) q.addEventListener('input', () => { studio.q = q.value; studio_renderLib(); });
  /* The intro dialog's own controls. Wired once, because unlike the inspector
     this markup is never rebuilt. */
  ['studio-intro-a', 'studio-intro-b'].forEach(id => {
    const el = studio_el(id);
    if (el) el.addEventListener('input', () => {
      const iv = studio.intro;
      studio_introSet(id === 'studio-intro-a' ? 'start' : 'end',
                      Number(el.value) / 1000 * iv.seconds);
    });
  });
  const ia = studio_el('studio-intro-audio');
  if (ia) ia.addEventListener('change', () => {
    studio.intro.audio = ia.checked;
    const v = studio_el('studio-intro-video');
    if (v) v.muted = !(studio.intro.audio && studio.intro.hasAudio);
    studio_introDraw();
  });
  const mis = studio_el('studio-mk-introsel');
  if (mis) mis.addEventListener('change', () => {
    studio.mkIntro.path = mis.value;
    studio_mkIntroDraw();
  });
  const mia = studio_el('studio-mk-introaudio');
  if (mia) mia.addEventListener('change', () => {
    studio.mkIntro.audio = mia.checked;
    studio_mkIntroDraw();
  });
  const ivid = studio_el('studio-intro-video');
  if (ivid) {
    ivid.addEventListener('play', () => {
      studio_el('studio-intro-play').textContent = 'Pause the part';
      requestAnimationFrame(studio_introTick);
    });
    ivid.addEventListener('pause', () => { studio_el('studio-intro-play').textContent = 'Play the part'; });
    ivid.addEventListener('timeupdate', studio_introTick);
    ivid.addEventListener('loadedmetadata', () => {
      /* The sidecar's length is what the trim was clamped against; if the file
         disagrees, the file wins -- it is what the render will read. */
      const iv = studio.intro;
      if (ivid.duration && isFinite(ivid.duration) && Math.abs(ivid.duration - iv.seconds) > 0.05) {
        iv.seconds = ivid.duration;
        iv.end = Math.min(iv.end || iv.seconds, iv.seconds);
        studio_introDraw();
      }
      ivid.currentTime = iv.start;
    });
  }

  const pn = studio_el('studio-pname');
  if (pn) pn.addEventListener('change', () => { if (studio.project) studio_change(pr => { pr.name = pn.value.trim() || pr.name; }, 'Reel name'); });
  document.addEventListener('pointerdown', studio_pointerDown);
  document.addEventListener('pointermove', studio_pointerMove);
  document.addEventListener('pointerup', studio_pointerUp);
  document.addEventListener('pointercancel', studio_pointerUp);
  const v = studio_el('studio-video');
  if (v) {
    ['timeupdate', 'seeked', 'loadedmetadata'].forEach(ev => v.addEventListener(ev, studio_playhead));
    v.addEventListener('play', function tick() {
      studio_playhead();
      studio_el('studio-play-btn').textContent = 'Pause';
      if (!v.paused) requestAnimationFrame(tick);
    });
    v.addEventListener('pause', () => { studio_el('studio-play-btn').textContent = 'Play'; });
  }
  ['studio-make-scrim', 'studio-preview-scrim'].forEach(id => {
    const sc = studio_el(id);
    if (sc) sc.addEventListener('click', e => { if (e.target === sc) studio_closeModals(); });
  });
  document.addEventListener('keydown', e => {
    if (shell_page !== 'studio') return;
    if (studio_impKey(e)) return;
    if (e.key === 'Escape') { studio_closeModals(); return; }
    const tag = (e.target.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    /* A focused button owns Space and Backspace: Space presses it. */
    const onButton = tag === 'BUTTON' || (e.target.closest && e.target.closest('button,[role="tab"],a'));
    const song = !studio_el('studio-pane-song').classList.contains('hide');
    if (song && studio.sg.shape) {
      if ((e.key || '').toLowerCase() === 'k') { e.preventDefault(); studio_sgMark(); }
      else if (e.key === ' ' && !onButton) { e.preventDefault(); studio_sgPlay(); }
      return;
    }
    if (onButton && (e.key === ' ' || e.key === 'Backspace' || e.key === 'Enter')) return;
    const tl = !studio_el('studio-pane-timeline').classList.contains('hide');
    if (!tl || !studio.project) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); studio_undo(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); studio_select(Math.min(studio.project.shots.length - 1, studio.sel + 1)); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); studio_select(Math.max(0, studio.sel - 1)); }
    else if (e.key === ' ') { e.preventDefault(); const vv = studio_el('studio-video'); if (vv.src) { if (vv.paused) vv.play().catch(() => {}); else vv.pause(); } }
    else if (e.key === '+' || e.key === '=') { e.preventDefault(); studio_zoomAt(studio.pps * 1.5, studio_anchorX()); }
    else if (e.key === '-' || e.key === '_') { e.preventDefault(); studio_zoomAt(studio.pps / 1.5, studio_anchorX()); }
    else if (e.key === '0') { e.preventDefault(); studio_fit(); studio_drawTimeline(); }
    else if ((e.key === 'Delete' || e.key === 'Backspace') && studio.sel >= 0 && studio.project.shots.length > 1) {
      e.preventDefault();
      const i = studio.sel, gone = studio_shotName(i);
      studio_forgetShots();
      studio_change(pr => { pr.shots.splice(i, 1); }, gone + ' removed');
      studio.sel = Math.min(i, studio.project.shots.length - 1); studio_drawAll();
    }
  });
  window.addEventListener('resize', () => { if (studio.project && shell_page === 'studio') studio_drawTimeline(); });
}

async function studio_restyle() {
  const p = studio.project, sel = studio_el('studio-r-style');
  if (!p || !sel || studio.busy) return;
  const key = sel.value;
  const label = (sel.options[sel.selectedIndex] || {}).text || key;
  studio.busy = true;
  const btn = studio_el('studio-restyle-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Rebuilding…'; }
  try {
    const snapshot = JSON.stringify(p);
    /* The clips this reel was made from, each once. Sending the timeline's
       shots made a clip used in nine of them arrive nine times, and the
       rebuild filled itself with that one clip. */
    const from = (p.selection && p.selection.length) ? p.selection.map(x => x.clip) : p.shots.map(x => x.clip);
    const clips = [];
    from.forEach(c => { if (clips.indexOf(c) < 0) clips.push(c); });
    const r = await API.post('/api/studio/plan', {clips: clips, style: key,
      song: p.song, format: p.format, name: p.name, shaping: Object.assign({}, studio.shaping,
        {arrange: studio.arrange, pins: studio.pins, shuffle_seed: studio.shuffleSeed})});
    if (!r || !r.ok) { toast((r && r.error) || 'Could not rebuild with that style.', 'warn'); return; }
    studio_pushUndo(snapshot);
    studio.gen++;
    r.project.output = p.output;
    studio.sel = -1;
    studio_touched('Rebuilt as ' + label);
    studio_setProject(r.project, r.derived, r.notes, r.song);
    studio_fit(); studio_drawAll();
    toast('Rebuilt as ' + label + ' — ' + r.project.shots.length + ' shots. Render to see it.', 'ok');
  } finally {
    studio.busy = false;
    studio_drawInspector();
  }
}

async function studio_mix(what, announce) {
  const p = studio.project;
  if (!p) return;
  const gen = ++studio.gen;
  const snapshot = JSON.stringify(p);
  const r = await API.post('/api/studio/vary', {project: p, what: what});
  if (gen !== studio.gen) return;
  if (!r || !r.ok) { toast((r && r.error) || 'Could not mix the effects.', 'warn'); return; }
  if (announce) studio_pushUndo(snapshot);
  studio.project = r.project; studio.derived = r.derived; studio.notes = r.notes || [];
  /* An unannounced mix rides along with the pool edit that asked for it, and
     that edit has already named itself; naming it twice would double the count. */
  if (announce) {
    studio_touched(what === 'all' ? 'Everything mixed again'
                 : what === 'kill' ? 'Kill effects mixed again' : 'Transitions mixed again');
  } else {
    studio.dirty = true;
  }
  studio_drawAll();
  if (announce) toast(what === 'all' ? 'Everything mixed again.' : what === 'kill' ? 'Kill effects mixed again.' : 'Transitions mixed again.', 'ok');
}

/* ------------------------------------------------------------ the song */

/* =======================================================================
   WAYS OF SEEING THE SONG
   The bands, the onsets and the spectrogram at 100 frames a second, drawn
   straight from the bytes clips/songview.py sends (no signal processing in
   the page), plus the kills clips/hits.py would cut to. A kill belongs on a
   kick or a hat; neither is visible in a waveform.
   ======================================================================= */

const SG_LANES = [
  {id: 'wave', h: 74, name: 'Waveform \u2014 the sound itself'},
  {id: 'bands', h: 96, name: 'Kick \u00b7 snare \u00b7 hats \u2014 energy in three bands'},
  {id: 'flux', h: 70, name: 'Onset strength \u2014 new sound arriving'},
  {id: 'spec', h: 128, name: 'Spectrogram \u2014 every frequency over time'}
];
const SG_PAL = (function () {
  /* magma-ish, so a spectrogram reads the way every other tool draws one */
  const stops = [[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66],
                 [245, 125, 21], [252, 194, 71], [252, 253, 191]];
  const out = new Uint8Array(256 * 3);
  for (let i = 0; i < 256; i++) {
    const t = i / 255 * (stops.length - 1), a = stops[Math.floor(t)], b = stops[Math.min(stops.length - 1, Math.ceil(t))];
    const f = t - Math.floor(t);
    for (let c = 0; c < 3; c++) out[i * 3 + c] = Math.round(a[c] + (b[c] - a[c]) * f);
  }
  return out;
})();

/* One CSS token, read fresh: the app's theme can change under the page. */
function studio_tok(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#8894a5';
}

function studio_svLane(name) {
  const m = studio.sv && studio.sv.meta;
  if (!m || !studio.sv.bytes) return null;
  const at = m.lanes[name];
  return at ? studio.sv.bytes.subarray(at[0], at[0] + at[1]) : null;
}

async function studio_svLoad(song) {
  if (!song) { studio.sv = null; studio_svBuild(); return; }
  if (studio.sv && studio.sv.song === song) { studio_svBuild(); return; }
  studio.sv = {song: song, meta: null, bytes: null, det: null};
  studio_el('studio-sg-detnote').textContent = 'Reading the song\u2026';
  const meta = await API.get('/api/studio/songview?song=' + encodeURIComponent(song));
  if (!meta || !meta.ok) {
    studio.sv = null;
    studio_el('studio-sg-detnote').textContent = (meta && meta.error) || 'Could not read that song.';
    studio_svBuild();
    return;
  }
  const buf = await (await fetch('/api/studio/songview.bin?k=' + encodeURIComponent(SHELL_K) +
    '&song=' + encodeURIComponent(song))).arrayBuffer();
  if (!studio.sv || studio.sv.song !== song) return;
  studio.sv.meta = meta;
  studio.sv.bytes = new Uint8Array(buf);
  studio.sv.det = meta.detected || null;
  const d = studio.sv.det;
  studio_el('studio-sg-detnote').textContent = d && d.kills.length
    ? d.pattern + ': ' + d.kills.length + ' kills, ' + d.big.length + ' big'
    : '';
  studio_svBuild();
}

function studio_svBuild() {
  const box = studio_el('studio-sg-lanes');
  if (!box) return;
  if (!studio.sv || !studio.sv.meta) { box.innerHTML = ''; studio_el('studio-sg-toggles').innerHTML = ''; return; }
  studio.svShow = studio.svShow || {wave: true, bands: true, flux: false, spec: true};
  studio_el('studio-sg-toggles').innerHTML = SG_LANES.map(l =>
    '<button type="button" class="studio-sg-toggle" data-act="studio-sg-lane" data-lane="' + l.id +
    '" aria-pressed="' + !!studio.svShow[l.id] + '">' + esc(l.name.split(' \u2014 ')[0]) + '</button>').join('');
  box.innerHTML = SG_LANES.filter(l => studio.svShow[l.id]).map(l =>
    '<div class="studio-sg-lane" data-lane="' + l.id + '"><canvas height="' + l.h +
    '" style="height:' + l.h + 'px"></canvas><span class="name">' + esc(l.name) + '</span></div>').join('');
  studio_svDraw();
}

/* WHERE THE SONG IS NOW. The audio element, not a field of our own: the
   lanes were drawn around studio.sg.at, which nothing ever sets, so they sat
   at zero while the song played. */
function studio_svNow() {
  const a = studio_el('studio-sg-audio');
  return (a && a.currentTime) || 0;
}

function studio_svWindow() {
  const t = studio_svNow();
  const w = studio.svWin || 8;
  return {t0: t - w * 0.375, t1: t - w * 0.375 + w, w: w};
}

function studio_svDraw() {
  if (!studio.sv || !studio.sv.meta) return;
  const v = studio_svWindow();
  document.querySelectorAll('#studio-sg-lanes .studio-sg-lane').forEach(el =>
    studio_svLaneDraw(el.getAttribute('data-lane'), el.querySelector('canvas'), v));
}

function studio_svLaneDraw(id, c, v) {
  const dpr = window.devicePixelRatio || 1;
  const W = c.clientWidth, H = c.clientHeight;
  if (!W || !H) return;
  c.width = Math.round(W * dpr); c.height = Math.round(H * dpr);
  const x = c.getContext('2d');
  x.setTransform(dpr, 0, 0, dpr, 0, 0);
  x.clearRect(0, 0, W, H);
  const m = studio.sv.meta, fps = m.fps, pad = 18;
  const X = t => (t - v.t0) / v.w * W;
  const curve = (arr, colour, fill) => {
    if (!arr) return;
    x.strokeStyle = colour; x.fillStyle = colour; x.lineWidth = 1.5; x.beginPath();
    for (let i = 0; i < W; i++) {
      const k0 = Math.floor((v.t0 + i / W * v.w) * fps);
      const k1 = Math.max(k0 + 1, Math.floor((v.t0 + (i + 1) / W * v.w) * fps));
      let top = 0;
      for (let k = Math.max(0, k0); k < Math.min(arr.length, k1); k++) if (arr[k] > top) top = arr[k];
      const h = top / 255 * (H - pad - 5);
      if (fill) x.fillRect(i, H - 3 - h, 1, h);
      else if (i === 0) x.moveTo(i, H - 3 - h); else x.lineTo(i, H - 3 - h);
    }
    if (!fill) x.stroke();
  };
  if (id === 'wave') curve(studio_svLane('rms'), studio_tok('--accent'), true);
  else if (id === 'flux') curve(studio_svLane('flux'), studio_tok('--ok'), true);
  else if (id === 'bands') {
    curve(studio_svLane('low'), '#ff8a5c', false);
    curve(studio_svLane('mid'), studio_tok('--accent'), false);
    curve(studio_svLane('high'), '#c98bff', false);
  } else if (id === 'spec') {
    const bins = m.spec_bins, sp = studio_svLane('spec'), f0 = Math.floor(v.t0 * fps);
    const n = Math.max(1, Math.ceil(v.w * fps));
    const img = x.createImageData(n, bins);
    for (let i = 0; i < n; i++) {
      const f = f0 + i;
      for (let b = 0; b < bins; b++) {
        const val = (f >= 0 && f < m.frames) ? sp[f * bins + b] : 0;
        const o = ((bins - 1 - b) * n + i) * 4;
        img.data[o] = SG_PAL[val * 3]; img.data[o + 1] = SG_PAL[val * 3 + 1];
        img.data[o + 2] = SG_PAL[val * 3 + 2]; img.data[o + 3] = 255;
      }
    }
    const off = document.createElement('canvas');
    off.width = n; off.height = bins;
    off.getContext('2d').putImageData(img, 0, 0);
    x.imageSmoothingEnabled = false;
    x.drawImage(off, 0, pad, W, H - pad);
  }
  /* the beat grid, so the song's own tempo can be compared with the hits */
  const sh = studio.songShape;
  if (sh && sh.beats) {
    for (let i = 0; i < sh.beats.length; i++) {
      const b = sh.beats[i];
      if (b < v.t0 - 0.1 || b > v.t1 + 0.1) continue;
      const down = (i % 4) === (sh.downbeat_pos || 0);
      x.fillStyle = down ? studio_tok('--text-tertiary') : studio_tok('--border-subtle');
      x.globalAlpha = id === 'spec' ? 0.55 : 1;
      x.fillRect(X(b) - (down ? 1 : 0.5), pad, down ? 2 : 1, H - pad);
      x.globalAlpha = 1;
    }
  }
  /* what the detector would cut to, in the strip above the view */
  const det = studio.sv.det;
  if (det && studio_el('studio-sg-showdet').checked) {
    const big = new Set(det.big);
    x.fillStyle = '#1f7a72';
    det.accents.forEach(t => { if (t >= v.t0 && t <= v.t1) x.fillRect(X(t) - 0.5, pad - 5, 1, 5); });
    det.kills.forEach(t => {
      if (t < v.t0 || t > v.t1) return;
      const isBig = big.has(t), px = X(t);
      x.fillStyle = '#2fd4c8';
      x.fillRect(px - (isBig ? 1 : 0.5), 2, isBig ? 2 : 1, pad - 2);
      x.beginPath(); x.moveTo(px - 4, 1); x.lineTo(px + 4, 1); x.lineTo(px, isBig ? 9 : 6); x.fill();
    });
  }
  /* the part being used, and the kills marked by hand */
  const sg = studio.sg;
  if (sg) {
    x.fillStyle = studio_tok('--warn');
    (sg.marks || []).forEach(t => {
      if (t >= v.t0 && t <= v.t1) x.fillRect(X(t) - 1, pad, 2, H - pad);
    });
    if (sg.start >= v.t0 && sg.start <= v.t1) {
      x.fillStyle = studio_tok('--ok'); x.fillRect(X(sg.start) - 1, 0, 2, H);
    }
    if (sg.end >= v.t0 && sg.end <= v.t1) {
      x.fillStyle = studio_tok('--ok'); x.fillRect(X(sg.end) - 1, 0, 2, H);
    }
    x.fillStyle = studio_tok('--bad');
    x.fillRect(X(studio_svNow()) - 1, 0, 2, H);
  }
}

/* The songs already downloaded, so one can be picked without a file dialog. */
async function studio_sgSongs(force) {
  const box = studio_el('studio-sg-songs');
  if (!box) return;
  if (!studio.songList || force) {
    const r = await API.get('/api/studio/songs');
    studio.songList = (r && r.ok && r.songs) || [];
  }
  const here = (studio.song || '').toLowerCase();
  box.innerHTML = studio.songList.length
    ? studio.songList.map(s =>
      '<button type="button" class="studio-sg-song' + (s.path.toLowerCase() === here ? ' is-on' : '') +
      '" data-act="studio-sg-song" data-path="' + esc(s.path) + '" title="' + esc(s.file) + '">' +
      esc(s.name) + '</button>').join('')
    : '<span class="muted">No songs downloaded yet. Paste a YouTube link and one will appear here.</span>';
}

function studio_svWin(w) {
  studio.svWin = w;
  document.querySelectorAll('[data-act="studio-sg-win"]').forEach(b =>
    b.classList.toggle('is-active', Number(b.getAttribute('data-win')) === w));
  studio_svDraw();
}

function studio_svToggle(id) {
  studio.svShow = studio.svShow || {};
  studio.svShow[id] = !studio.svShow[id];
  studio_svBuild();
}

function studio_sgOpen() {
  const p = studio.project, sg = studio.sg;
  if (!p) return;
  if (p.song && (!sg.shape || sg.song !== p.song)) {
    sg.song = p.song;
    sg.shape = studio.songShape && studio.songShape.beats ? studio.songShape : null;
    if (!sg.shape) {
      API.post('/api/reel/song', {song: p.song}).then(got => {
        if (got && got.ok) { sg.shape = got.song; studio.songShape = got.song; studio_sgReset(); }
      });
    }
  }
  if (!p.song) { sg.song = ''; sg.shape = null; }
  studio_sgSongs();
  studio_svLoad(sg.song || '');
  studio_sgReset();
}

function studio_sgReset() {
  const p = studio.project, sg = studio.sg, sh = sg.shape;
  studio_show('studio-sg-body', !!sh);
  studio_el('studio-sg-name').textContent = sg.song ? sg.song.split(/[\\/]/).pop() : 'No song';
  studio_el('studio-sg-facts').textContent = sh
    ? Math.round(sh.bpm) + ' BPM · ' + studio_dur(sh.seconds) + (sh.drop ? ' · drop at ' + studio_secs(sh.drop) : '') +
      (sh.drums_in ? ' · drums in at ' + studio_secs(sh.drums_in) : '')
    : 'Choose a song to cut the reel to. Without one the clips keep their own sound on a 120 BPM grid.';
  if (!sh) return;
  const len = (studio.derived && studio.derived.length) || 30;
  if (sg.song === p.song && !sg.touched) {
    sg.start = p.song_offset || 0;
    sg.end = Math.min(sh.seconds, sg.start + len);
  }
  // Open on the marks this reel is already using, so the section is an editor
  // of what is there rather than a blank sheet. Once per song: retyping them
  // over the player's own edits every redraw would be worse than no seeding.
  if (sg.song && sg.seeded !== sg.song && !sg.marks.length && (p.song_marks || []).length) {
    // Placed against the part the reel was planned on, so if the part has
    // since been moved they keep their place in it -- see studio_sgMovePart.
    const dt = sg.song === p.song ? sg.start - (p.song_offset || 0) : 0;
    sg.marks = p.song_marks.map(m => Math.round((m + dt) * 1000) / 1000).sort((a, b) => a - b);
    sg.sel = -1;
  }
  if (sg.song) sg.seeded = sg.song;
  studio_el('studio-sg-atdrop').disabled = !sh.drop;
  const a = studio_el('studio-sg-audio');
  const want = studio_media('/api/reel/audio', sg.song);
  if (a.getAttribute('data-song') !== sg.song) { a.src = want; a.setAttribute('data-song', sg.song); }
  studio_sgDraw();
}

function studio_sgBeat() {
  const sh = studio.sg.shape;
  return sh ? sh.beat || (60 / sh.bpm) : 0.5;
}

function studio_sgNearestBeat(t) {
  const b = (studio.sg.shape && studio.sg.shape.beats) || [];
  let best = t, d = 1e9;
  for (let i = 0; i < b.length; i++) { const x = Math.abs(b[i] - t); if (x < d) { d = x; best = b[i]; } }
  return best;
}

function studio_sgNudge(what, how) {
  const sg = studio.sg, sh = sg.shape;
  if (!sh) return;
  const beat = studio_sgBeat();
  const step = {bar: 4 * beat, '-bar': -4 * beat, beat: beat, '-beat': -beat, ms: 0.01, '-ms': -0.01}[how] || 0;
  sg.touched = true;
  if (what === 'start') {
    studio_sgMovePart(sg.start + step);
  } else {
    sg.end = Math.max(sg.start + beat, Math.min(sh.seconds, sg.end + step));
  }
  studio_sgDraw();
}

function studio_sgSnapBar() {
  const sg = studio.sg, sh = sg.shape;
  if (!sh || !sh.beats || !sh.beats.length) return;
  const bars = sh.beats.filter((b, i) => (i % 4) === (sh.downbeat_pos || 0));
  let best = sg.start, d = 1e9;
  bars.forEach(b => { const x = Math.abs(b - sg.start); if (x < d) { d = x; best = b; } });
  sg.touched = true;
  studio_sgMovePart(best);
  studio_sgDraw();
}

function studio_sgAtDrop() {
  const sg = studio.sg, sh = sg.shape;
  if (!sh || !sh.drop) return;
  const len = sg.end - sg.start;
  const lead = Math.min(8 * 4 * studio_sgBeat(), sh.drop, Math.max(4 * studio_sgBeat(), len / 3));
  sg.touched = true;
  studio_sgMovePart(Math.max(0, studio_sgNearestBeat(sh.drop - lead)));
  studio_sgDraw();
}

function studio_sgFit() {
  const sg = studio.sg, sh = sg.shape, d = studio.derived;
  if (!sh || !d) return;
  sg.touched = true;
  sg.end = Math.min(sh.seconds, sg.start + d.length);
  studio_sgDraw();
}

function studio_sgPlay() {
  const a = studio_el('studio-sg-audio'), sg = studio.sg;
  if (!sg.shape || !a.src) return;
  if (a.paused) {
    if (a.currentTime < sg.start || a.currentTime >= sg.end) a.currentTime = sg.start;
    sg.ticked = {};
    a.play().catch(() => toast('The song could not be played.', 'warn'));
  } else {
    a.pause();
  }
}

/* THE MARKS AUTOSTREAM ALREADY CHOSE, so they can be moved instead of retapped.
   A reel's kills are on the song's bass hits by the time the timeline exists;
   without this the Song section opened on an empty list and the only way to
   change one placement was to tap all twenty again. `song_marks` is what a
   previous Use-these-marks stored; where there is none the kills themselves are
   where the reel currently puts them, which is the same thing to edit. */
function studio_sgKillMarks() {
  const p = studio.project, d = studio.derived, sg = studio.sg;
  if (!p || !d) return [];
  if ((p.song_marks || []).length) return p.song_marks.slice().sort((a, b) => a - b);
  return (d.shots || []).map(r => sg.start + r.kill_reel).sort((a, b) => a - b);
}

function studio_sgFromKills() {
  const sg = studio.sg, got = studio_sgKillMarks();
  if (!got.length) { toast('This reel has no kills to mark yet.'); return; }
  const snap = studio_el('studio-sg-snap').checked;
  sg.marks = got.map(t => snap ? studio_sgNearestBeat(t) : Math.round(t * 1000) / 1000)
                .filter((t, i, a) => i === 0 || t - a[i - 1] > 0.03);
  sg.sel = -1;
  sg.touched = true;
  studio_sgDraw();
  toast(sg.marks.length + ' marks from the reel. Move any of them, then use them.');
}

function studio_sgSelect(i) {
  const sg = studio.sg;
  sg.sel = (sg.sel === i) ? -1 : i;
  studio_sgDraw();
}

/* Moving a mark keeps the list in order, so mark 2 is always after mark 1 --
   shot N's kill lands on mark N, and a list that crossed over would silently
   swap two shots' places in the song. A nudge that would cross its neighbour
   stops against it instead. */
function studio_sgNudgeMark(how) {
  const sg = studio.sg, sh = sg.shape;
  if (!sh || sg.sel < 0 || sg.sel >= sg.marks.length) return;
  const beat = studio_sgBeat();
  const d = (how === 'beat' ? beat : how === '-beat' ? -beat : how === 'half' ? beat / 2 : -beat / 2);
  const lo = sg.sel > 0 ? sg.marks[sg.sel - 1] + 0.03 : sg.start;
  const hi = sg.sel < sg.marks.length - 1 ? sg.marks[sg.sel + 1] - 0.03 : sh.seconds;
  sg.marks[sg.sel] = Math.max(lo, Math.min(hi, sg.marks[sg.sel] + d));
  sg.touched = true;
  studio_sgDraw();
}

/* A mark is a moment in the music, so the way to judge one is to hear it: this
   plays the bar it sits in rather than asking the ear to remember. */
function studio_sgHearMark() {
  const sg = studio.sg, a = studio_el('studio-sg-audio');
  if (sg.sel < 0 || sg.sel >= sg.marks.length || !a) return;
  a.currentTime = Math.max(0, sg.marks[sg.sel] - studio_sgBeat() * 2);
  a.play();
}

function studio_sgDropMark() {
  const sg = studio.sg;
  if (sg.sel < 0 || sg.sel >= sg.marks.length) return;
  sg.marks.splice(sg.sel, 1);
  sg.sel = -1;
  sg.touched = true;
  studio_sgDraw();
}

function studio_sgMark() {
  const a = studio_el('studio-sg-audio'), sg = studio.sg;
  if (!sg.shape) return;
  let t = a.currentTime || sg.start;
  if (studio_el('studio-sg-snap').checked) t = studio_sgNearestBeat(t);
  if (t < sg.start - 0.01 || t > sg.end + 0.01) { toast('Marks go inside the part you are using.', 'warn'); return; }
  if (sg.marks.some(m => Math.abs(m - t) < 0.03)) return;
  sg.marks.push(t);
  sg.marks.sort((x, y) => x - y);
  studio_sgDraw();
}

function studio_sgClick() {
  try {
    const C = window.AudioContext || window.webkitAudioContext;
    if (!C) return;
    studio.sg.ac = studio.sg.ac || new C();
    const ac = studio.sg.ac, o = ac.createOscillator(), g = ac.createGain();
    o.frequency.value = 1800; g.gain.value = 0.15;
    o.connect(g); g.connect(ac.destination);
    o.start(); o.stop(ac.currentTime + 0.03);
  } catch (e) { /* no audio context, no click */ }
}

function studio_sgTick() {
  const a = studio_el('studio-sg-audio'), sg = studio.sg;
  if (!sg.shape) return;
  if (!a.paused && studio_el('studio-sg-loop').checked && a.currentTime >= sg.end) {
    a.currentTime = sg.start; sg.ticked = {};
  }
  if (!a.paused && studio_el('studio-sg-click').checked) {
    sg.marks.forEach((m, i) => {
      if (Math.abs(a.currentTime - m) < 0.05 && !sg.ticked[i]) { sg.ticked[i] = 1; studio_sgClick(); }
    });
  }
  studio_el('studio-sg-clock').textContent = studio_secs(a.currentTime || 0);
  studio_sgDrawWaves();
  if (!a.paused) requestAnimationFrame(studio_sgTick);
}

/* THE MARKS ARE SONG SECONDS, AND THEY MOVE ONLY WHEN THE PART MOVES.
   A mark is a moment of the song -- the snare a kill lands on -- so it is
   stored as song time and drawn from it. Moving the whole part (dragging it,
   clicking elsewhere on the song, the start nudges, snapping to a bar, "build
   into the drop") carries every mark with it by exactly the distance the part
   moved, so a kill ten seconds into the part is still ten seconds in.
   Resizing the part by an edge moves nothing: the marks stay on the beats
   they were tapped on.

   It used to be inferred instead -- any change to the start since the last
   redraw shifted the marks -- so dragging the START EDGE dragged every mark
   along with it, off the beats they were tapped on, and the release's snap to
   a beat moved them again. Now each thing that moves the part says so. */
function studio_sgMovePart(start) {
  const sg = studio.sg, sh = sg.shape;
  if (!sh) return;
  const len = sg.end - sg.start;
  const to = Math.max(0, Math.min(sh.seconds - Math.min(len, sh.seconds), start));
  const dt = to - sg.start;
  sg.start = to;
  sg.end = Math.min(sh.seconds, to + len);
  if (Math.abs(dt) > 1e-6) {
    // Kept even where they fall past the song's end: dragging the part to the
    // end and back must not cost marks, and none past the end is used.
    sg.marks = sg.marks.map(m => Math.round((m + dt) * 1000) / 1000);
  }
}

function studio_sgDraw() {
  const sg = studio.sg, sh = sg.shape, d = studio.derived, p = studio.project;
  if (!sh) return;
  studio_el('studio-sg-start').textContent = studio_secs(sg.start);
  studio_el('studio-sg-end').textContent = studio_secs(sg.end);
  studio_el('studio-sg-range').textContent = 'Using ' + studio_secs(sg.start) + ' → ' + studio_secs(sg.end) +
    ' (' + studio_dur(sg.end - sg.start) + ')';
  const len = d ? d.length : 0, part = sg.end - sg.start;
  studio_el('studio-sg-fitnote').textContent = len > part + 0.05
    ? 'The timeline is ' + studio_dur(len) + '; shots past ' + studio_dur(part) + ' will be left out. "Fit the timeline" keeps them all.'
    : 'The whole timeline fits in this part.';
  if (sg.sel >= sg.marks.length) sg.sel = -1;
  studio_el('studio-sg-chips').innerHTML = sg.marks.map((m, i) =>
    '<span class="reel-chip' + (i === sg.sel ? ' is-on' : '') + '" data-sgmark="' + i +
    '" title="click to choose this mark">' + (i + 1) + ' · ' + studio_secs(m) + '</span>').join('');
  studio_show('studio-sg-marknudge', sg.sel >= 0);
  if (sg.sel >= 0) {
    studio_el('studio-sg-marknum').textContent = String(sg.sel + 1);
    studio_el('studio-sg-marktime').textContent = studio_secs(sg.marks[sg.sel]);
  }
  studio_el('studio-sg-fromkills').disabled = !studio_sgKillMarks().length;
  const shots = p ? p.shots.length : 0;
  studio_el('studio-sg-marksinfo').textContent = sg.marks.length
    ? sg.marks.length + ' marks for ' + shots + ' shots' + (sg.marks.length < shots ? ' — the rest keep their spacing after the last mark.' : sg.marks.length > shots ? ' — the extra marks will not be used.' : '.')
    : 'No marks: the shots keep the lengths they have, starting from here.';
  studio_el('studio-sg-apply').textContent = sg.marks.length ? 'Use this part and these marks' : 'Use this part';
  studio_sgDrawWaves();
}

function studio_sgCanvas(id, H) {
  const cv = studio_el(id);
  if (!cv) return null;
  const dpr = window.devicePixelRatio || 1, W = Math.max(200, cv.clientWidth);
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {cv: cv, ctx: ctx, W: W, H: H};
}

function studio_sgDrawWaves() {
  studio_svDraw();                      /* the lanes follow the playhead too */
  const sg = studio.sg, sh = sg.shape;
  if (!sh || !sh.peaks) return;
  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue('--accent').trim() || '#5aa9ff';
  const warn = css.getPropertyValue('--warn').trim() || '#e3b341';
  const faint = css.getPropertyValue('--border-strong').trim() || '#555';
  const a = studio_el('studio-sg-audio');
  const now = a ? a.currentTime || 0 : 0;
  const n = sh.peaks.length, per = sh.seconds / n;

  /* the whole song */
  const o = studio_sgCanvas('studio-sg-overview', 90);
  if (o) {
    const {ctx, W, H} = o, X = t => t / sh.seconds * W, mid = H / 2;
    ctx.fillStyle = accent;
    ctx.globalAlpha = 0.35;
    for (let x = 0; x < W; x++) {
      const k = Math.min(n - 1, Math.floor(x / W * n));
      const amp = sh.peaks[k] * (mid - 2);
      ctx.globalAlpha = (x >= X(sg.start) && x <= X(sg.end)) ? 1 : 0.3;
      ctx.fillRect(x, mid - amp, 1, amp * 2);
    }
    ctx.globalAlpha = 0.18; ctx.fillStyle = accent;
    ctx.fillRect(X(sg.start), 0, X(sg.end) - X(sg.start), H);
    ctx.globalAlpha = 1;
    ctx.fillStyle = accent;
    ctx.fillRect(X(sg.start) - 2, 0, 4, H); ctx.fillRect(X(sg.end) - 2, 0, 4, H);
    if (sh.drop) { ctx.fillStyle = warn; ctx.fillRect(X(sh.drop) - 1, 0, 2, H); }
    ctx.fillStyle = '#ff5c5c'; ctx.fillRect(X(now) - 1, 0, 2, H);
    o.cv.title = 'Drag the highlighted part to move it, or its edges to resize it';
  }

  /* the part, magnified */
  const dt = studio_sgCanvas('studio-sg-detail', 130);
  if (dt) {
    const {ctx, W, H} = dt;
    const pad = Math.max(0.5, (sg.end - sg.start) * 0.04);
    const t0 = Math.max(0, sg.start - pad), t1 = Math.min(sh.seconds, sg.end + pad);
    const X = t => (t - t0) / (t1 - t0) * W, mid = H / 2;
    ctx.fillStyle = accent;
    for (let x = 0; x < W; x += 2) {
      const t = t0 + x / W * (t1 - t0), k = Math.min(n - 1, Math.floor(t / per));
      const amp = sh.peaks[k] * (mid - 14);
      ctx.globalAlpha = (t >= sg.start && t <= sg.end) ? 0.9 : 0.25;
      ctx.fillRect(x, mid - amp, 1.5, amp * 2);
    }
    ctx.globalAlpha = 1;
    (sh.beats || []).forEach((b, i) => {
      if (b < t0 || b > t1) return;
      const bar = (i % 4) === (sh.downbeat_pos || 0);
      ctx.fillStyle = faint;
      ctx.globalAlpha = bar ? 0.9 : 0.35;
      ctx.fillRect(X(b), bar ? 0 : H - 12, 1, bar ? H : 12);
    });
    ctx.globalAlpha = 1;
    ctx.fillStyle = accent;
    ctx.fillRect(X(sg.start) - 1, 0, 3, H); ctx.fillRect(X(sg.end) - 1, 0, 3, H);
    if (sh.drop && sh.drop >= t0 && sh.drop <= t1) {
      ctx.fillStyle = warn; ctx.fillRect(X(sh.drop) - 1, 0, 2, H);
      ctx.font = '11px sans-serif'; ctx.fillText('drop', X(sh.drop) + 4, 12);
    }
    sg.marks.forEach((m, i) => {
      const x = X(m);
      ctx.save(); ctx.translate(x, H - 20); ctx.rotate(Math.PI / 4);
      ctx.fillStyle = '#fff'; ctx.fillRect(-6, -6, 12, 12);
      ctx.strokeStyle = accent; ctx.lineWidth = 2; ctx.strokeRect(-6, -6, 12, 12);
      ctx.restore();
      ctx.fillStyle = css.getPropertyValue('--text-primary').trim() || '#fff';
      ctx.font = '11px sans-serif'; ctx.fillText(String(i + 1), x + 8, H - 26);
    });
    ctx.fillStyle = '#ff5c5c'; ctx.fillRect(X(now) - 1, 0, 2, H);
    dt.cv.setAttribute('data-t0', t0); dt.cv.setAttribute('data-t1', t1);
  }
}

function studio_sgPointer(e) {
  const sg = studio.sg, sh = sg.shape;
  if (!sh) return;
  const ov = studio_el('studio-sg-overview'), de = studio_el('studio-sg-detail');
  const a = studio_el('studio-sg-audio');
  if (e.type === 'pointerdown' && e.target === de) {
    const r = de.getBoundingClientRect();
    const t0 = Number(de.getAttribute('data-t0')), t1 = Number(de.getAttribute('data-t1'));
    a.currentTime = Math.max(0, t0 + (e.clientX - r.left) / r.width * (t1 - t0));
    studio_sgDrawWaves();
    studio_el('studio-sg-clock').textContent = studio_secs(a.currentTime);
    return;
  }
  if (e.type === 'pointerdown' && e.target === ov) {
    const r = ov.getBoundingClientRect();
    const t = (e.clientX - r.left) / r.width * sh.seconds;
    const edge = 6 / r.width * sh.seconds;
    const kind = Math.abs(t - sg.start) < edge ? 'start' : Math.abs(t - sg.end) < edge ? 'end'
      : (t > sg.start && t < sg.end) ? 'move' : 'jump';
    if (kind === 'jump') {
      sg.touched = true;
      studio_sgMovePart(t - (sg.end - sg.start) / 2);
      studio_sgDraw();
      return;
    }
    sg.drag = {kind: kind, x0: e.clientX, start: sg.start, end: sg.end, w: r.width, pointer: e.pointerId};
    try { ov.setPointerCapture(e.pointerId); } catch (err) { /* fine without */ }
    e.preventDefault();
    return;
  }
  const g = sg.drag;
  if (!g || e.pointerId !== g.pointer) return;
  if (e.type === 'pointermove') {
    const dt = (e.clientX - g.x0) / g.w * sh.seconds;
    sg.touched = true;
    if (g.kind === 'start') sg.start = Math.max(0, Math.min(sg.end - 1, g.start + dt));
    else if (g.kind === 'end') sg.end = Math.max(sg.start + 1, Math.min(sh.seconds, g.end + dt));
    else studio_sgMovePart(g.start + dt);
    studio_sgDraw();
  } else {
    sg.drag = null;
    /* Dragging lands the part on a beat; the 10 ms nudges are for leaving it.
       A moved part takes its marks to the beat with it; a resized one does not. */
    if (g.kind === 'move') studio_sgMovePart(studio_sgNearestBeat(sg.start));
    else if (g.kind === 'start') sg.start = Math.min(sg.end - 0.5, studio_sgNearestBeat(sg.start));
    else sg.end = Math.max(sg.start + 0.5, studio_sgNearestBeat(sg.end));
    studio_sgDraw();
  }
}

async function studio_sgPick() {
  const r = await API.post('/api/clips/pick', {kind: 'audio'});
  if (!r || !r.path) return;
  await studio_sgUseSong(r.path);
}

/* A song file as the Song tab's song. -> whether it could be read. */
async function studio_sgUseSong(path) {
  studio_el('studio-sg-facts').textContent = 'Finding the beat in ' + path.split(/[\\/]/).pop() + '…';
  const got = await API.post('/api/reel/song', {song: path});
  if (!got || !got.ok) { studio_el('studio-sg-facts').textContent = (got && got.error) || 'Could not read that song.'; return false; }
  const sg = studio.sg, sh = got.song, len = (studio.derived && studio.derived.length) || 30;
  /* A new song: the marks were beats of the old one, so they go. */
  sg.song = path; sg.shape = sh; sg.marks = []; sg.sel = -1; sg.touched = true;
  studio.songShape = sh;
  studio_sgSongs();
  studio_svLoad(path);
  const from = sh.drums_in || (sh.beats && sh.beats[0]) || 0;
  sg.start = studio_sgNearestBeat(Math.max(0, Math.min(from, sh.seconds - len)));
  sg.end = Math.min(sh.seconds, sg.start + len);
  studio_sgReset();
  return true;
}

async function studio_sgApply(noSong) {
  const p = studio.project, sg = studio.sg;
  if (!p) return;
  const btn = studio_el('studio-sg-apply');
  btn.disabled = true;
  studio_el('studio-sg-msg').textContent = noSong ? 'Taking the song off…' : 'Fitting the timeline to the song…';
  try {
    const snapshot = JSON.stringify(p);
    const gen = ++studio.gen;
    const body = noSong ? {project: p, song: ''} :
      {project: p, song: sg.song, start: sg.start, end: sg.end, marks: sg.marks};
    const r = await API.post('/api/studio/song', body);
    if (gen !== studio.gen) return;
    if (!r || !r.ok) { studio_el('studio-sg-msg').textContent = (r && r.error) || 'Could not use that song.'; return; }
    studio_pushUndo(snapshot);
    r.project.output = p.output;
    studio_touched(noSong ? 'The song taken off'
                 : sg.marks.length ? 'The song, and ' + sg.marks.length + ' kill marks' : 'The part of the song');
    studio_setProject(r.project, r.derived, r.notes, r.song);
    if (noSong) { sg.song = ''; sg.shape = null; sg.marks = []; }
    sg.touched = false;
    studio_el('studio-sg-msg').textContent = '';
    toast(noSong ? 'The reel has no song now.' : sg.marks.length
      ? 'Kills moved onto your ' + Math.min(sg.marks.length, r.project.shots.length) + ' marks. Render to hear it.'
      : 'Song part set. Render to hear it.', 'ok');
    studio_tab('timeline');
  } finally {
    btn.disabled = false;
  }
}

function studio_sgWire() {
  const ov = studio_el('studio-sg-overview'), de = studio_el('studio-sg-detail');
  ['pointerdown', 'pointermove', 'pointerup', 'pointercancel'].forEach(ev => {
    if (ov) ov.addEventListener(ev, studio_sgPointer);
    if (de && ev === 'pointerdown') de.addEventListener(ev, studio_sgPointer);
  });
  const a = studio_el('studio-sg-audio');
  if (a) {
    /* "Pause the part", not "Pause": a button that renames itself must not
       resize itself under the pointer that just pressed it, and two labels of
       the same length cannot. The min-width in the CSS is the belt to this. */
    a.addEventListener('play', () => { studio_el('studio-sg-play').textContent = 'Pause the part'; requestAnimationFrame(studio_sgTick); });
    a.addEventListener('pause', () => { studio_el('studio-sg-play').textContent = 'Play the part'; studio_sgDrawWaves(); });
    a.addEventListener('seeked', studio_sgDrawWaves);
  }
  document.addEventListener('click', e => {
    const c = e.target.closest ? e.target.closest('[data-sgmark]') : null;
    if (!c) return;
    // Choosing, not removing. A chip used to delete on click, which is a hard
    // thing to undo when the marks are the twenty AutoStream placed; Remove is
    // its own button on the row that appears.
    studio_sgSelect(Number(c.getAttribute('data-sgmark')));
  });
  window.addEventListener('resize', () => { if (shell_page === 'studio') studio_sgDrawWaves(); });
}

window.PAGE_STUDIO = {
  onShow: function () {
    if (!studio.wired) studio_sgWire();
    studio_wire();
    studio_load(false);
    studio_poll();
  },
  onTick: function () {}
};
"""

__all__ = ["STUDIO_HTML", "STUDIO_JS"]
