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
      <!-- THREE JOBS, THREE TABS. The clips pane used to carry all of them at
           once: picking clips, browsing every finished reel, and choosing a
           look from nine drawers. Ninety reels and a 223-trillion counter
           above the clips meant the first screen of the page you came to for
           clips had no clips on it. -->
      <button type="button" class="seg-btn" role="tab" aria-selected="false"
              data-act="studio-tab" data-tab="reels" id="studio-tab-reels">Reels <b id="studio-tab-reels-n"></b></button>
      <button type="button" class="seg-btn" role="tab" aria-selected="false"
              data-act="studio-tab" data-tab="looks" id="studio-tab-looks">Looks</button>
      <button type="button" class="seg-btn" role="tab" aria-selected="false"
              data-act="studio-tab" data-tab="timeline" id="studio-tab-timeline" disabled>Timeline</button>
      <button type="button" class="seg-btn" role="tab" aria-selected="false"
              data-act="studio-tab" data-tab="song" id="studio-tab-song" disabled>Song</button>
      <button type="button" class="seg-btn" role="tab" aria-selected="false"
              data-act="studio-tab" data-tab="facecam" id="studio-tab-facecam" disabled>Facecam</button>
    </div>
    <!-- THE WAY IN TO EVERY ACTION. Ctrl+K is worth nothing to someone who
         does not know it is there, so the shortcut is printed on a button
         that does the same thing. It sits in the header rather than the
         editor's toolbar because the actions it lists are not only the
         timeline's. -->
    <button type="button" class="btn btn-sm studio-palbtn" data-act="studio-palette"
            id="studio-palbtn" title="Run a command (Ctrl+K)">
      <span aria-hidden="true">&#9906;</span> Actions <kbd>Ctrl K</kbd>
    </button>
  </header>

  <section id="studio-pane-clips" aria-label="Clips">
    <header class="bin-top">
      <div class="bin-intro">
        <p class="bin-eyebrow">Reel maker</p>
        <h1 class="bin-title">Pick your clips, then pick a look</h1>
        <p class="bin-lede" id="studio-sub">Reading your clips…</p>
      </div>
      <button type="button" class="btn btn-primary" data-act="studio-gd-open" id="studio-gd-open">Make a reel, step by step</button>
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
    <div id="studio-lib" class="studio-lib"></div>
    <p class="muted studio-empty hide" id="studio-empty"></p>

    <div class="studio-tray hide" id="studio-tray" role="region" aria-label="Selection">
      <div class="studio-tray-text">
        <strong id="studio-tray-count">0 clips</strong>
        <span class="muted" id="studio-tray-facts"></span>
        <span class="studio-adding hide" id="studio-adding"></span>
      </div>
      <!-- WHICH RUNS THE PICKS CAME FROM. A count says the selection is
           scattered; these say where, and each one opens that run. -->
      <div class="studio-tray-runs hide" id="studio-tray-runs"></div>
      <button type="button" class="btn btn-ghost btn-sm" data-act="studio-fav-selected" id="studio-fav-btn">★ Favourite</button>
      <button type="button" class="btn btn-ghost btn-sm" data-act="studio-clear">Clear</button>
      <button type="button" class="btn btn-ghost btn-sm hide" data-act="studio-add-cancel" id="studio-add-cancel">Stop adding</button>
      <button type="button" class="btn btn-ghost btn-sm studio-del-btn" data-act="studio-delete">Delete…</button>
      <button type="button" class="btn btn-primary" data-act="studio-make" id="studio-make-btn">Make a reel</button>
    </div>
  </section>

  <!-- EVERY REEL YOU HAVE MADE, with room for its own search, filters and
       order. It used to sit between the clips and the drawers, pushing both
       out of the first screen. -->
  <section id="studio-pane-reels" class="hide" aria-label="Reels">
      <!-- A TAB THAT OPENS ON NOTHING IS A DEAD END, which is the thing this
           split exists to remove. Before the first reel there is a sentence
           saying what to do, not a blank pane. -->
      <p class="muted studio-empty hide" id="studio-reels-none">No reels yet. Pick some clips on
        the Clips tab, choose a look, and the reels you make appear here.</p>
      <!-- EVERY REEL, NOT THE LAST TEN. The tools are markup of their own and
           only the grid is redrawn, so typing in the search never loses focus. -->
      <section class="studio-reels hide" id="studio-reels" aria-labelledby="studio-reels-h">
        <div class="studio-reels-head">
          <h3 class="studio-h" id="studio-reels-h">Your reels <b id="studio-reels-count"></b></h3>
          <input class="input studio-search" id="studio-reel-q" type="search"
                 placeholder="Search reels by name, style or song" aria-label="Search reels">
          <div class="studio-games" id="studio-reel-fmts" role="group" aria-label="Reel shape"></div>
          <label class="studio-reel-sortl"><span class="muted">Sort</span>
            <select class="select" id="studio-reel-sort" aria-label="Sort reels">
              <option value="new">Newest first</option>
              <option value="old">Oldest first</option>
              <option value="name">Name A&ndash;Z</option>
              <option value="long">Longest first</option>
            </select></label>
        </div>
        <div class="studio-reel-row" id="studio-reel-grid"></div>
        <p class="muted studio-empty hide" id="studio-reel-none"></p>
        <button type="button" class="btn btn-sm studio-reels-more hide" data-act="studio-reels-more"
                id="studio-reels-more" aria-expanded="false"></button>
      </section>
  </section>

  <!-- THE LOOK, AND WHAT IT DRAWS FROM. The drawers belong beside the look
       they fill, not above the clips: 223 trillion combinations is a fact
       about the app, not a decision anybody has to make before picking a
       clip. -->
  <section id="studio-pane-looks" class="hide" aria-label="Looks">
    <aside class="bin-calc" aria-label="How many templates">
      <p class="bin-eyebrow">Mix and match</p>
      <div class="bin-big" id="bin-total">—<small id="bin-total-note">counting the drawers</small></div>
      <div class="bin-slots" id="bin-slots"></div>
    </aside>
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
          <!-- UNDO WAS A ONE-WAY DOOR. A step popped off the stack was gone,
               so Ctrl+Z pressed once too often could not be taken back. Both
               buttons now say what they will do rather than only that they
               can do something. -->
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-redo" id="studio-redo-btn" disabled>Redo</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-hist" id="studio-hist-btn"
                  aria-expanded="false" title="Everything you have done to this reel">History</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-show" id="studio-show-btn" disabled>Show file</button>
          <!-- THE REEL AS A TIMELINE SOMEBODY ELSE CAN OPEN. `.reel.json` was
               always a project file; this writes it in a vocabulary Resolve
               and Premiere read, with a sheet beside it saying what survived
               the trip. A silent downgrade is how somebody loses an
               afternoon. -->
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-export"
                  id="studio-export-btn" data-kind="otio"
                  title="Write this reel out as an OpenTimelineIO timeline (Resolve and most others)">Export&hellip;</button>
          <button type="button" class="btn btn-ghost btn-sm hide" data-act="studio-export"
                  data-kind="fcp7" id="studio-export-xml"
                  title="Write it as Final Cut Pro 7 XML, which is what Premiere imports">Export for Premiere</button>
          <button type="button" class="btn btn-ghost btn-sm hide" data-act="studio-cancel" id="studio-cancel-btn">Cancel</button>
          <button type="button" class="btn btn-primary" data-act="studio-render" id="studio-render-btn">Render</button>
        </div>
      </div>

      <div class="ed-stage">
        <div class="studio-player" id="studio-player">
          <video id="studio-video" controls playsinline preload="metadata"></video>
          <!-- THE TIMELINE, PLAYED OFF THE CLIPS. Deleting a shot used to mean
               a render and a 10-20 second wait before the player could say
               whether it was the right shot. This plays the edit as it stands,
               straight from the clip files: two players swapped at each cut,
               the next one already loaded, and the song under both. The cuts,
               the order, the timing and the music are the reel's own; the
               effects and the colour arrive with the render, and the label
               says so. See studio_pvTick. -->
          <div class="studio-pv hide" id="studio-pv">
            <!-- 9:16 WITH THE WHOLE PICTURE FITTED: the render puts the game
                 over a blurred copy of itself, and the preview showed black
                 bands there instead. A small canvas, redrawn from the player
                 on screen, blurred and stretched by CSS, is that copy. -->
            <canvas class="studio-pv-bg" id="studio-pv-bg" width="54" height="96" aria-hidden="true"></canvas>
            <video class="studio-pv-v" id="studio-pv-a" playsinline preload="auto" data-knobs="off"></video>
            <video class="studio-pv-v" id="studio-pv-b" playsinline preload="auto" data-knobs="off"></video>
            <audio id="studio-pv-song" preload="auto" data-knobs="off"></audio>
            <!-- THE LYRICS, BEFORE THE RENDER. The render's own subtitle
                 script, drawn alone into a transparent video by the server
                 (/api/studio/lyrics/preview) and kept on the reel's clock --
                 so a new look shows in seconds, not after a render. -->
            <video class="studio-pv-lyr hide" id="studio-pv-lyr" muted playsinline preload="auto"
                   data-knobs="off" aria-hidden="true"></video>
            <span class="studio-pv-tag" id="studio-pv-tag">Preview · effects appear when rendered</span>
            <!-- THE PREVIEW'S OWN BAR. The rendered video brings the browser's
                 -- play, seek, mute, fullscreen -- and the preview, two players
                 swapped at each cut, has none, so the bar vanished the moment
                 an edit was made ("the on screen play back option
                 disappeared"). This one drives the reel's clock, so a seek
                 lands on the shot the timeline has there. -->
            <div class="studio-pv-bar" id="studio-pv-bar">
              <button type="button" class="studio-pv-btn" data-act="studio-play" id="studio-pv-play"
                      title="Play (space)" aria-label="Play">&#9654;</button>
              <span class="mono studio-pv-time" id="studio-pv-time">0:00 / 0:00</span>
              <input type="range" class="studio-pv-seek" id="studio-pv-seek" min="0" max="1000" step="1" value="0"
                     aria-label="Seek">
              <button type="button" class="studio-pv-btn" data-act="studio-pv-mute" id="studio-pv-mute"
                      title="Mute" aria-label="Mute" aria-pressed="false">&#128266;</button>
              <button type="button" class="studio-pv-btn" data-act="studio-pv-full" id="studio-pv-full"
                      title="Fullscreen" aria-label="Fullscreen">&#9974;</button>
            </div>
          </div>
          <div class="studio-player-empty" id="studio-player-empty">Press Render and your reel plays here.</div>
          <!-- THE PLAYER IS WHERE THE EYES ARE. A sidebar saying the edits are
               not in the video yet is missed by someone watching the video, so
               the video says it too, over its own top corner. -->
          <div class="studio-stale hide" id="studio-stale" aria-hidden="true"></div>
          <!-- THE HANDLE, WHERE IT WILL BE. Dragged on the picture itself,
               because "a bit higher than the kill counter" is a place you
               point at, not a number. Shown while the Reel tab is open. -->
          <div class="ed-frame hide" id="studio-frame" aria-hidden="true">
            <span class="ed-handle" id="studio-handle-chip" title="Drag to move your handle"></span>
            <span class="ed-handle ed-lyrics" id="studio-lyrics-chip" title="Drag to move the lyrics">LYRICS</span>
          </div>
          <!-- THE BOXES THE WORDS ARE DEALT INTO. Width and Size were two
               numbers describing a rectangle nobody could see; this is that
               rectangle, drawn where the words will be. Drag on the empty
               picture to make one, drag it to move it, its corners to resize,
               the knob above it to turn it. The number on each box is the
               order the lines are dealt in, which is the whole feature -- so
               it is drawn on the box rather than explained underneath. -->
          <div class="ed-boxes hide" id="studio-lyrboxes"></div>
        </div>
      </div>

      <div class="studio-tl-bar ed-transport">
        <button type="button" class="btn btn-sm studio-transport" data-act="studio-play" id="studio-play-btn">Play</button>
        <span class="mono studio-clock" id="studio-clock">0:00.00</span>
        <span class="mono studio-shuttle" id="studio-shuttle-lab"
              role="status" aria-live="polite"></span>
        <span class="media-knobs" data-for="studio-video"></span>
        <label class="studio-check"><input type="checkbox" id="studio-snap" checked> Keep cuts on the beat</label>
        <!-- WHAT THE MUSIC LANE SHOWS. Loudness alone cannot say whether a kill
             landed on the kick it was aimed at; the colour view and the song's
             own hit marks can, so both are on and either can be turned off. -->
        <label class="studio-check"><input type="checkbox" id="studio-tl-spec" checked> Show the music</label>
        <label class="studio-check"><input type="checkbox" id="studio-tl-marks" checked> Mark the beats</label>
        <!-- SHOTS LOCKED TOGETHER move as one when the cut before them moves:
             shift- or ctrl-click shots to pick several, then lock them. -->
        <button type="button" class="btn btn-sm" data-act="studio-lock" id="studio-lock-btn" disabled
                title="Shift-click or Ctrl-click shots on the timeline to pick several">Lock shots</button>
        <!-- THE TOOLS. Select is the hand that was always here; Roll and Razor
             are the two the timeline genuinely did not have. Each is also a
             modifier on the drag people already know -- Ctrl rolls -- so
             nobody has to pick a tool, and Escape always comes back to Select
             so nobody is stranded holding one. -->
        <span class="studio-tools" role="group" aria-label="Timeline tool">
          <button type="button" class="btn btn-sm studio-tool is-on" data-act="studio-tool"
                  data-tool="select" aria-pressed="true"
                  title="Select — move a shot; drag an edge to move that cut, Shift-drag to push everything after it (V)">Select</button>
          <button type="button" class="btn btn-sm studio-tool" data-act="studio-tool"
                  data-tool="roll" aria-pressed="false"
                  title="Roll — an edge always moves the cut and never pushes the reel, even with Shift held (N)">Roll</button>
          <button type="button" class="btn btn-sm studio-tool" data-act="studio-tool"
                  data-tool="razor" aria-pressed="false"
                  title="Razor — click a shot to cut it in two (C)">Razor</button>
        </span>
        <!-- WHERE TO LOOK, not what the reel is. In and out pick a stretch to
             watch and a mark says "come back to this"; neither changes a
             frame of the video, which is why they sit apart from the tools. -->
        <span class="studio-marks" role="group" aria-label="In, out and marks">
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-in"
                  title="In point — start of the stretch you want to watch (I)">In</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-out"
                  title="Out point — end of it (O)">Out</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-io-clear"
                  title="Forget the in and out points">Clear</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mark"
                  title="Drop a mark at the playhead (M)">Mark</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mark-clear"
                  title="Take every mark off">No marks</button>
        </span>
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
          <!-- IN, OUT AND THE MARKS, over the tracks rather than in them:
               they are about where to look, not about what the reel is,
               and a lane of their own would make them look like an edit. -->
          <div class="studio-io" id="studio-io" aria-hidden="true"></div>
          <div class="studio-tracks" id="studio-tracks"></div>
        </div>
      </div>
      <p class="muted studio-hint ed-hint">Drag a shot to move it. Drag either edge to move that cut &mdash; the shots either side give and take, so every kill stays on its beat; Shift-drag to push everything after it. Its diamond moves the kill.
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
        <!-- THE RENDER NOBODY HAS TO ASK FOR. A couple of seconds after the
             last edit the real render starts by itself, so the finished video
             is usually there by the time the preview has been watched. The
             same setting as Settings > Clips; see studio_autoGo. -->
        <div class="studio-auto">
          <label class="studio-check"><input type="checkbox" id="studio-auto-render" checked> Render in the background</label>
          <span class="studio-auto-state" id="studio-auto-state" role="status" aria-live="polite"></span>
        </div>
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

      <!-- EVERYTHING DONE TO THIS REEL, and where in it you are standing.
           The steps you have undone stay on the list rather than vanishing,
           because the whole point of a history is that a step too far is
           recoverable. Click any step to go there. The words are the ones the
           change list above uses -- one set of names, two views of it. -->
      <div class="studio-hist hide" id="studio-hist" aria-label="History"></div>
    </aside>
  </section>

  <!-- THE FACECAM. Its own place, because both jobs it has are done by eye:
       drawing a box round a camera that is already in the recording, or
       lining up a separate camera video until the laugh lands on the kill. -->
  <section id="studio-pane-facecam" class="hide studio-fc" aria-label="Facecam">
    <div class="studio-fc-head">
      <div>
        <h2 class="studio-h">Your camera</h2>
        <p class="muted studio-small">Put your webcam in the corner of the reel, so people see your
          reaction as well as the play.</p>
      </div>
      <div class="seg" role="group" aria-label="Facecam source" id="studio-fc-src"></div>
    </div>

    <div class="studio-fc-grid">
      <div class="card"><div class="card-body studio-fc-card">
        <!-- IN THE VIDEO: a box drawn once on a frame of their own footage. -->
        <div id="studio-fc-inset" class="hide">
          <h3 class="studio-h">Draw a box round your camera</h3>
          <p class="muted studio-small">Your camera is already baked into the recording, so show us where it
            is: drag a box around your face. Do this once and AutoStream remembers it.</p>
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
        <span class="muted" id="studio-sg-facts">Pick a song and your clips get cut in time with it.</span>
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
      <p class="field-label">The whole song &mdash; drag the lit-up part to move it, or its edges to resize.
        The faint lines are the beat; bright ones start a bar.</p>
      <canvas class="studio-sg-wave" id="studio-sg-overview" height="90" aria-label="Whole song"></canvas>
      <p class="field-label">The part you picked, up close &mdash; click anywhere to jump there</p>
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
            <label class="studio-check"><input type="checkbox" id="studio-sg-snap"> Snap marks to the beat</label>
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

  <div class="scrim studio-page hide" id="studio-guide-scrim">
  <div class="studio-page-card studio-gd" id="studio-gd" role="region" aria-label="Make a reel, step by step">
    <header class="mk-head">
      <button type="button" class="btn btn-ghost" data-act="studio-gd" data-gd="close">&larr; Back to the clips</button>
      <h2 class="mk-title">Make a reel</h2>
    </header>
    <ol class="gd-steps" id="studio-gd-steps"></ol>
    <section class="gd-body" id="studio-gd-body" aria-live="polite"></section>
    <div class="gd-chip" id="studio-gd-chip" role="status"></div>
    <footer class="gd-foot">
      <button type="button" class="btn btn-ghost btn-sm" data-act="studio-gd" data-gd="all">All settings</button>
      <span class="gd-nav">
        <button type="button" class="btn" data-act="studio-gd" data-gd="back" id="studio-gd-back">Back</button>
        <button type="button" class="btn btn-primary" data-act="studio-gd" data-gd="next" id="studio-gd-next">Next</button>
      </span>
    </footer>
  </div>
  </div>

  <div class="scrim studio-page hide" id="studio-make-scrim">
  <div class="studio-page-card" id="studio-make" role="region" aria-labelledby="studio-make-title">
    <header class="mk-head">
      <button type="button" class="btn btn-ghost" data-act="studio-make-cancel" id="studio-make-back">&larr; Back to the clips</button>
      <div class="mk-head-text">
        <h2 class="mk-title" id="studio-make-title">Make a reel</h2>
        <p class="muted" id="studio-make-facts"></p>
      </div>
    </header>
    <div class="mk-layout">
      <nav class="mk-nav" id="studio-mk-nav" aria-label="Sections of this page">
        <button type="button" class="mk-nav-b is-on" data-act="studio-mk-jump" data-sec="style">Style</button>
        <button type="button" class="mk-nav-b" data-act="studio-mk-jump" data-sec="look">Look</button>
        <button type="button" class="mk-nav-b" data-act="studio-mk-jump" data-sec="song">Song &amp; part</button>
        <button type="button" class="mk-nav-b" data-act="studio-mk-jump" data-sec="kills">Kills</button>
        <button type="button" class="mk-nav-b" data-act="studio-mk-jump" data-sec="shape">Shape &amp; order</button>
      </nav>
      <div class="mk-body">
        <section class="mk-sec" id="mk-sec-style">
      <h3 class="studio-h">Style <span class="muted studio-small" id="studio-style-count"></span></h3>
      <!-- EVERY STYLE ON THE SAME KILLS. Each card plays fifteen seconds cut from the SAME
           clips, so the only thing that differs between two of them is the style. The set
           ships with the app; cutting them again on the player's own kills is optional. -->
      <div class="studio-samples-bar" id="studio-samples-bar">
        <button type="button" class="btn btn-ghost btn-sm" data-act="studio-samples-start" id="studio-samples-btn">Show them on my own kills</button>
        <button type="button" class="btn btn-ghost btn-sm hide" data-act="studio-samples-stop" id="studio-samples-stop">Stop</button>
        <span class="muted studio-small" id="studio-samples-msg" role="status" aria-live="polite"></span>
      </div>
      <div class="studio-styles" id="studio-styles" role="radiogroup" aria-label="Style"></div>
        </section>
        <section class="mk-sec" id="mk-sec-look">
      <!-- THE TEMPLATE: what the style picked, shown part by part with its
           example, and changeable one drawer at a time. -->
      <h3 class="studio-h">Template</h3>
      <div class="bin-dealer">
        <button type="button" class="btn btn-sm" data-act="studio-deal">Deal a template</button>
        <button type="button" class="btn btn-ghost btn-sm" data-act="studio-deal-reset">Back to the style's own</button>
        <span class="bin-code" id="studio-deal-code"></span>
      </div>
      <p class="muted studio-small hide" id="studio-fast-note" role="note"></p>
      <div class="bin-hand" id="studio-hand"></div>
        </section>
        <section class="mk-sec" id="mk-sec-song">
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
        </section>
        <section class="mk-sec" id="mk-sec-kills">
      <!-- M4: THE KILLS, EDITABLE HERE. The Song tab lets you mark where each kill lands; this
           is the same thing before the reel exists. "Show where the kills will land" plans the
           reel the way Build would and draws every kill on the song; touch one and it becomes
           yours, and Build puts the rest around it. -->
      <div class="studio-mk-kills hide" id="studio-mk-killsbox">
        <h3 class="studio-h">Kills <span class="muted studio-small">where each one lands on the song</span></h3>
        <p class="muted studio-small" id="studio-mk-killnote"></p>
        <div class="field-inline">
          <button type="button" class="btn btn-sm" data-act="studio-mk-plan" id="studio-mk-plan">Show where the kills will land</button>
          <button type="button" class="btn btn-sm" data-act="studio-mk-addmark" title="Drops a kill at the playhead, exactly where it is (K)">Mark a kill here <kbd>K</kbd></button>
          <button type="button" class="btn btn-sm" data-act="studio-mk-adddrop" title="Marks a bass drop at the playhead (D)">Mark a drop here <kbd>D</kbd></button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-clearmarks" id="studio-mk-clearmarks">Back to automatic</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-cleardrops" id="studio-mk-cleardrops">Drops back to automatic</button>
          <span class="muted studio-small" id="studio-mk-killmsg" role="status" aria-live="polite"></span>
        </div>
        <!-- WHOSE EACH MARK IS, at a glance: AutoStream's hollow, the player's solid, drops on their own lane. -->
        <div class="studio-mk-legend" aria-hidden="true">
          <span><i class="mk-key mk-key-auto"></i>AutoStream's kill</span>
          <span><i class="mk-key mk-key-hand"></i>Your kill</span>
          <span><i class="mk-key mk-key-dropauto"></i>Drop found</span>
          <span><i class="mk-key mk-key-drophand"></i>Your drop</span>
          <label class="studio-check"><input type="checkbox" id="studio-mk-tick" checked> Sound on each mark as it plays</label>
          <label class="studio-check"><input type="checkbox" id="studio-mk-snap"> Snap marks to the beat</label>
        </div>
        <canvas class="studio-sg-wave" id="studio-mk-kills" height="140"
                aria-label="The part of the song: drops along the top, kills below. Click a mark to select it, Ctrl-click or Shift-click for several, Shift-drag to box-select, drag to move, double-click to add or remove"></canvas>
        <!-- SEVERAL AT ONCE. Fifty marks taken out one cross at a time was the only way to clear a stretch. -->
        <div class="field-inline studio-mk-selbar">
          <button type="button" class="btn btn-sm" data-act="studio-mk-delsel" id="studio-mk-delsel" disabled>Delete selected</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-selall" id="studio-mk-selall">Select all</button>
          <button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-selnone" id="studio-mk-selnone" disabled>Select none</button>
          <span class="muted studio-small">Tick marks below, Ctrl-click them on the song, or Shift-drag across it. <kbd>Delete</kbd> removes them.</span>
        </div>
        <ol class="studio-mk-marklist studio-mk-droplist" id="studio-mk-droplist" aria-label="Drops"></ol>
        <ol class="studio-mk-marklist" id="studio-mk-marklist" aria-label="Kills"></ol>
      </div>
        </section>
        <section class="mk-sec" id="mk-sec-shape">
      <h3 class="studio-h">Shape</h3>
      <div class="field-inline studio-shape">
        <div class="seg" role="group" aria-label="Format">
          <button type="button" class="seg-btn is-active" data-act="studio-fmt" data-fmt="landscape">Landscape 16:9</button>
          <button type="button" class="seg-btn" data-act="studio-fmt" data-fmt="vertical">Vertical 9:16</button>
        </div>
        <!-- HOW A 16:9 GAME FILLS A 9:16 FRAME: cropped to its middle, or all
             of it over a blurred copy. Only asked when it is a question. -->
        <div class="seg hide" role="group" aria-label="Vertical framing" id="studio-mk-fit">
          <button type="button" class="seg-btn is-active" data-act="studio-mk-fit" data-fit="zoom">Zoom to fill</button>
          <button type="button" class="seg-btn" data-act="studio-mk-fit" data-fit="fit">Fit the whole picture</button>
          <button type="button" class="seg-btn" data-act="studio-mk-fit" data-fit="near">Near fit</button>
        </div>
      </div>
      <!-- THE ORDER, ASKED WHERE THE REEL IS MADE.

           It used to be asked twice, in two places, with different answers.
           Here sat three buttons -- As chosen / Most kills first / Oldest
           first -- which only sorted the clip list in the page before it was
           sent. The real arrangements, the ones the planner runs with the
           song in hand, were six buttons in the drawers strip at the foot of
           the page: Build up, As it happened, Best first, Shuffle, Best order
           and Perfect fit. So the two that matter most -- Best order and
           Perfect fit -- could not be reached from the dialog where somebody
           decides how their reel is built, and "Most kills first" quietly
           overlapped with "Best first" while meaning something weaker.

           One control now, the six real ones. The old three are not lost:
           Most kills first is Best first done by the planner, and Oldest
           first is As it happened. -->
      <h3 class="studio-h">Order <span class="muted studio-small">how the kills line up</span></h3>
      <div class="studio-mk-arrange" id="studio-mk-arrange" role="group" aria-label="Order"></div>
      <!-- HOW LONG, ASKED RATHER THAN DECIDED. The style used to set the
           length as well as the feel, so a long part and twenty-five clips
           came out a 43 s Hype reel with eleven clips left out. The style
           now keeps the pace, the effects and the flashes either way. -->
      <h3 class="studio-h">How long</h3>
      <div class="seg studio-fill" role="group" aria-label="How long" id="studio-fill">
        <button type="button" class="seg-btn" data-act="studio-fill" data-fill="style">The style's length</button>
        <button type="button" class="seg-btn" data-act="studio-fill" data-fill="part" id="studio-fill-part">Fill the song part I picked</button>
        <button type="button" class="seg-btn" data-act="studio-fill" data-fill="all">Every clip I chose</button>
      </div>
      <p class="muted studio-small" id="studio-fill-note"></p>
      <label class="studio-check" id="studio-keep-row"><input type="checkbox" id="studio-keep-all"> Keep every kill</label>
      <p class="muted studio-small">A kill with little run-up starts on its clip's first frame, or its run-up
        is slowed, instead of being left out; to fit a length the kills move closer together.</p>
      <label class="field-label" for="studio-name">Name</label>
      <input class="input" id="studio-name" maxlength="80" placeholder="Montage reel">
      <!-- Valorant clips carry a headshot reading per kill; shown only when some do. -->
      <label class="studio-check hide" id="studio-hs-row"><input type="checkbox" id="studio-hs-only">
        Headshot kills only <span class="muted studio-small" id="studio-hs-note"></span></label>
        </section>
      </div>
    </div>
    <div class="gd-chip" id="studio-mk-chip" role="status" hidden></div>
    <div class="mk-bar">
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

  <!-- CHOOSING AN EFFECT. A dialog and not a dropdown, because an effect is
       something you watch: every card plays its two-second example, the one
       under the pointer plays large beside the list, and a search box takes a
       name or a code ("freeze", "K04"). A dropdown of "K04 · Freeze" lines, or
       a wall of forty checkboxes, asked people to pick from names they had
       never seen move. The inspector rebuilds its HTML on every edit, so the
       players live here, where they stay put. -->
  <div class="scrim hide" id="studio-fxp-scrim">
  <div class="modal studio-fxp-modal" id="studio-fxp" role="dialog" aria-modal="true" aria-labelledby="studio-fxp-title">
    <div class="studio-fxp-head">
      <div>
        <h2 class="modal-title" id="studio-fxp-title">Choose an effect</h2>
        <p class="muted studio-small" id="studio-fxp-lede"></p>
      </div>
      <label class="sr-only" for="studio-fxp-q">Search by name or code</label>
      <input class="input studio-fxp-q" id="studio-fxp-q" type="search" autocomplete="off"
             placeholder="Search by name or code, e.g. freeze or K04">
    </div>
    <!-- THE EFFECT IS THE POINT, SO IT IS THE BIGGEST THING HERE. The list
         used to fill the dialog and the one being looked at sat in a 300 px
         corner beside it -- too small to tell fine grain from coarse ("put the
         actual preview in the centre and big so that it is easy to spot the
         difference"). Now the list is a narrow column and the stage takes the
         rest, playing a sharp copy cut for it (examples.make_large). -->
    <div class="studio-fxp-main">
      <div class="studio-fxp-list" id="studio-fxp-list"></div>
      <section class="studio-fxp-prev" id="studio-fxp-prev" aria-live="polite" aria-label="The one being shown">
        <div class="studio-fxp-prevshot" id="studio-fxp-prevshot"></div>
        <div class="studio-fxp-prevfoot">
          <div class="studio-fxp-prevtext">
            <p class="studio-fxp-prevname"><strong id="studio-fxp-prevname"></strong>
              <span class="bin-code" id="studio-fxp-prevcode"></span></p>
            <p class="muted studio-small" id="studio-fxp-prevblurb"></p>
            <p class="muted studio-small studio-fxp-prevnote" id="studio-fxp-prevnote"></p>
          </div>
          <button type="button" class="btn" data-act="studio-fxp-stage" id="studio-fxp-stage">Use this</button>
        </div>
      </section>
    </div>
    <div class="modal-actions">
      <span class="muted studio-fxp-count" id="studio-fxp-count" role="status" aria-live="polite"></span>
      <button type="button" class="btn btn-ghost hide" data-act="studio-fxp-clear" id="studio-fxp-clear">Clear all</button>
      <button type="button" class="btn btn-ghost" data-act="studio-fxp-cancel" id="studio-fxp-cancel">Cancel</button>
      <button type="button" class="btn btn-primary hide" data-act="studio-fxp-done" id="studio-fxp-done">Done</button>
    </div>
  </div>
  </div>

  <!-- EVERY ACTION, BY NAME (Ctrl+K). The page declares 147 distinct actions
       and could list none of them, which is why there was nothing to search.
       Both this and the key sheet below are drawn from ui/commands.py and
       hold no list of their own, so a command added there appears in both
       without being typed twice.

       A command that cannot run now SAYS WHY. Greying out in silence is how
       someone presses a key three times and concludes the app is broken. -->
  <div class="scrim hide" id="studio-pal-scrim">
  <div class="modal studio-pal" id="studio-pal" role="dialog" aria-modal="true" aria-labelledby="studio-pal-title">
    <h2 class="sr-only" id="studio-pal-title">Run a command</h2>
    <div class="studio-pal-head">
      <span class="studio-pal-ico" aria-hidden="true">&#9906;</span>
      <label class="sr-only" for="studio-pal-q">Search commands by name</label>
      <input class="input studio-pal-q" id="studio-pal-q" type="search" autocomplete="off"
             placeholder="Search every action &mdash; try render, beat or ending">
      <span class="muted studio-pal-count" id="studio-pal-count" role="status" aria-live="polite"></span>
    </div>
    <div class="studio-pal-list" id="studio-pal-list" role="listbox" aria-label="Commands"></div>
    <div class="studio-pal-foot">
      <span><kbd>&uarr;</kbd><kbd>&darr;</kbd> move</span>
      <span><kbd>&crarr;</kbd> run</span>
      <span><kbd>Esc</kbd> close</span>
      <span class="studio-spacer"></span>
      <button type="button" class="btn btn-ghost btn-sm" data-act="studio-keys" id="studio-pal-keys">All the keys</button>
      <button type="button" class="btn btn-ghost btn-sm" data-act="studio-pal-close">Close</button>
    </div>
  </div>
  </div>

  <!-- THE KEY SHEET (?). Written from the registry, so it cannot drift from
       what the keys actually do -- a sheet typed by hand is wrong the first
       time a binding moves. The scopes print in the keydown block's own
       precedence order, because that order is the answer to "why did Space
       press the button instead of playing". -->
  <div class="scrim hide" id="studio-keys-scrim">
  <div class="modal studio-keys" id="studio-keys" role="dialog" aria-modal="true" aria-labelledby="studio-keys-title">
    <div class="studio-keys-head">
      <div>
        <h2 class="modal-title" id="studio-keys-title">Keys</h2>
        <p class="muted studio-small">Each group takes the keys while it is open, top first. A focused
          button keeps Space, Enter and Backspace for pressing itself.</p>
      </div>
      <span class="muted studio-small" id="studio-keys-count"></span>
    </div>
    <div class="studio-keys-cols" id="studio-keys-cols"></div>
    <div class="modal-actions">
      <button type="button" class="btn btn-ghost" data-act="studio-palette">Run a command&hellip;</button>
      <button type="button" class="btn btn-primary" data-act="studio-keys-close">Done</button>
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
    <div class="studio-imp-head">
      <h2 class="modal-title" id="studio-imp-title">Your clip</h2>
      <!-- WHICH ONE OF HOW MANY. Adding twenty clips and being shown one with
           no way back meant the only way to revisit the third was to close,
           find it in the library and open it again. -->
      <div class="studio-imp-nav hide" id="studio-imp-nav">
        <button type="button" class="btn btn-ghost btn-sm" data-act="studio-imp-prev"
                id="studio-imp-prev" aria-label="Previous clip">&#8592;</button>
        <span class="mono studio-imp-count" id="studio-imp-count"
              role="status" aria-live="polite">1 of 1</span>
        <button type="button" class="btn btn-ghost btn-sm" data-act="studio-imp-next"
                id="studio-imp-next" aria-label="Next clip">&#8594;</button>
      </div>
    </div>
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
        <!-- CUTTING A BIT OUT, said as removing rather than as keeping. What
             somebody watching a clip wants is "this bit at the front is dead,
             take it off" -- phrasing it as a keep-range makes them work out
             the complement of the thing they can actually see. -->
        <div class="studio-tl-bar studio-imp-trim">
          <span class="field-label studio-small">Remove a piece</span>
          <button type="button" class="btn btn-ghost btn-sm"
                  data-act="studio-imp-cutfrom">From here</button>
          <button type="button" class="btn btn-ghost btn-sm"
                  data-act="studio-imp-cutto">To here</button>
          <span class="mono studio-small" id="studio-imp-cutspan">nothing chosen</span>
          <button type="button" class="btn btn-sm" data-act="studio-imp-cut"
                  id="studio-imp-cut" disabled>Remove it</button>
          <button type="button" class="btn btn-ghost btn-sm"
                  data-act="studio-imp-cutclear">Clear</button>
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
          <button type="button" class="btn btn-sm hide" data-act="studio-imp-detectall"
                  id="studio-imp-detectall">Find them in all</button>
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
  /* WHERE IN THE LIBRARY THE PLAYER IS. `game` is the open folder ('all' is
     the folder grid itself, 'fav' the favourites) and `run` the open run's
     path. Both live here rather than in the markup because the pane is
     rebuilt on every edit -- state kept in the DOM would drop the player back
     at the top every time they came back from making a reel. */
  game: 'all', run: '', q: '', onlyPicked: false, selected: [], lastClick: null,
  reelQ: '', reelSort: 'new', reelFmt: 'all', reelsAll: false,
  examples: null, picks: null, binOn: null, binObs: null, binTimer: null,
  sv: null, svShow: null, svWin: 8, songList: null,
  /* The music lane: the whole song's spectrogram as one image, which song has
     been asked for, and what the lane is showing. */
  spec: null, musicWant: '', musicPending: false, showSpec: true, showMarks: true, waveTick: 0,
  style: '', song: '', songShape: null, fmt: 'landscape', vfit: 'zoom', order: 'chosen',
  project: null, derived: null, notes: [], dirty: true, output: '', renderedAt: 0,
  /* WHAT HAS NOT REACHED THE VIDEO YET. `dirty` could say that something had
     changed; it could not say what, so pressing render was an act of faith and
     not pressing it was a reel watched in the wrong version. Every edit names
     itself here ({label, shot, paths}); a render empties the list. `base` is
     the project the video was rendered from (or opened as), and an edit whose
     fields are back to it leaves the list on its own. */
  pending: [], base: null, shelved: [], jobMsg: '', failMsg: '', renderNote: '', rendering: false,
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
  /* HOW LONG and KEEP EVERY KILL, from the Make dialog. '' is "not chosen":
     the part when one is picked, otherwise the style's length -- what the
     server does with nothing asked, so the button lit is the one that runs. */
  fill: '', keepAll: false,
  sg: {song: '', shape: null, start: 0, end: 0, marks: [], drag: null, ticked: {}, ac: null,
       sel: -1, seeded: ''},
  /* The part of the song chosen on the Make dialog, in song seconds. */
  mk: {mode: 'part', start: 0, end: 0, touched: false, drag: null, seekTo: null, ticking: false,
       /* THE KILLS, as the player has them: `planned` is where a plan put them (song seconds, with the
          clip each belongs to), `hand` is what they have placed or moved, and only `edited` marks are
          sent -- an untouched preview must not turn into marks the next plan is forced to keep. */
       hand: [], edited: false, planned: null,
       /* The bass drops, null while they are the ones the song analysis found; `sel` is the marks
          selected by id, kills and drops alike; `lastT` is where playback was a frame ago, so a mark
          it passed can be sounded. */
       drops: null, sel: {}, nid: 0, markDrag: null, boxSel: null, lastT: null, ac: null, listSig: ''},
  /* Styles shown on the player's own kills: {key, ready: {style: file}, running, state}. */
  samples: {key: '', ready: {}, running: false, state: null, timer: null, held: ''},
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
  imp: {path: '', seconds: 0, kills: [], sel: -1, dirty: false, games: null,
        /* A BATCH YOU CAN WALK BOTH WAYS, not a queue that is eaten. It was a
           queue: Save shifted the next path off it and there was no way back,
           so revisiting the third of twenty meant closing the dialog, finding
           it in the library and opening it again. `batch` is every path
           picked in one go; `at` is where you are in it. */
        batch: [], at: 0,
        /* The piece being removed, in clip seconds. See studio_impCut. */
        cutFrom: null, cutTo: null},
  /* THE INSTANT PREVIEW (studio_pvTick). `on` is whether the player is showing
     it rather than the rendered file; `t` the reel second it is paused on, or
     `base` + the wall clock since `t0` while it plays; `act` which of the two
     <video>s is on screen and `shot` the shot it holds. `cuts` is every cut it
     has played, with how late it was -- read by the browser test. `info`
     remembers, per shot, what the server worked out about its footage, so a
     shot the page has only moved keeps playing the right seconds. */
  pv: {on: false, t: 0, base: 0, t0: 0, playing: false, act: 0, shot: -1, raf: 0,
       cuts: [], info: {}, planSig: '', rate: 1, muted: false, scrub: false,
       lyr: {sig: '', want: '', busy: false, timer: 0, name: '', note: ''}},
  /* THE BACKGROUND RENDER (studio_autoGo). `sig` is the project the running
     or last one was given, `armed` the project the idle timer was started for,
     `held` why it is waiting, `failed` a project that failed once and is not
     retried until it changes. */
  auto: {on: true, known: false, timer: null, dueAt: 0, armed: '', sig: '', job: 0,
         running: false, pct: 0, held: '', heldUntil: 0, failed: '', idleMs: 2500,
         waitMs: 2500, lastMs: 0, log: []},
  /* THE COMMAND LIST (Ctrl+K) and the key sheet (?). `rows` is what the
     search last matched, in the order drawn, so Up/Down and Enter act on the
     same list the eye is reading. */
  pal: {open: false, q: '', sel: 0, rows: [], recent: []},
  /* The states ahead of you: what Ctrl+Z has set aside and Ctrl+Shift+Z
     puts back. Emptied by any fresh edit -- see studio_pushUndo. */
  redo: [],
  /* Whether the history panel is open. Not the history itself: that is the
     two stacks, which exist whether anybody is looking or not. */
  histOpen: false,
  /* WHICH TOOL THE POINTER IS HOLDING. 'select' is the hand everybody
     already had; the rest are additions, and Escape always comes back here so
     nobody is ever stranded holding one. A modifier on the drag does the same
     job without picking a tool at all -- Ctrl rolls -- so the rail is a
     convenience, never the only way in. */
  tool: 'select',
  /* IN AND OUT, and the shuttle. The range is a PLAY range and a place to
     look, NEVER a render range: the change list says what has not reached
     the video yet, and a part-render would let that strip claim the video
     matches the timeline when it matches a slice of it. Marks live on the
     project, because they are notes about the reel rather than about this
     sitting at the screen. */
  io: {a: null, b: null},
  shuttle: 0,
  /* THE LYRIC BOXES, while they are being drawn. `on` is the mode, `sel` the
     box being worked on, `drag` whatever the pointer is in the middle of.
     None of it is the project: the project only learns about a box when the
     pointer comes up, so one drag is one edit and one press of undo. */
  lyrBox: {on: false, sel: -1, drag: null}
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

/* ONE ENTRY PER EFFECT, ITS VERSIONS BEHIND IT (asked 2026-10-17). A drawer listed
   every strength, length and direction of an effect as a new one -- 566 cards for
   about ninety effects -- so a list shows each effect's lead and its other versions
   open from it. A catalog without groups (an older server) lists everything. */
function studio_leads(kind) {
  const all = studio_parts(kind);
  const leads = all.filter(p => p.lead);
  return leads.length ? leads : all;
}

function studio_versions(kind, group) {
  return studio_parts(kind).filter(p => p.group === group);
}

/* The effect's own name on its lead card: "Wipe" for Wipe left, "Colour tint" for Teal. */
function studio_leadName(p) {
  return p.group_label || p.label || p.id;
}

function studio_moreChip(p, act, chosen) {
  if (!p.versions || p.versions < 2) return '';
  return '<span class="bin-more' + (chosen ? ' is-on' : '') + '" role="button" tabindex="0"' +
    ' data-act="' + act + '" data-kind="' + esc(p.kind) + '" data-group="' + esc(p.group) + '"' +
    ' title="Show every version of ' + esc(studio_leadName(p)) + '">' +
    p.versions + ' versions' + (chosen ? ' · ' + chosen + ' in use' : '') + ' ›</span>';
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
    c.game = g.game; c.folderLabel = f.label; c.when = f.when;
    /* The run a clip belongs to. Without it a selection could be counted
       but not placed, which is the whole complaint: "I don't know from
       which folder, from which run the current clips are selected". */
    c.folder = f.folder; studio.clipIndex[c.id] = c;
  })));
  studio.selected = studio.selected.filter(id => studio.clipIndex[id]);
  studio_renderLib();
}

/* ------------------------------------------------------------ the library */

/* WHAT IS IN SCOPE RIGHT NOW: the folders whose clips the player is looking
   at, which is what the tray counts, what shift-range runs over and what
   "Select run" toggles. The library is a drill-down -- folders, then the runs
   in one folder, then the clips in one run -- so scope narrows as you go in.

   A SEARCH IS NOT NARROWED BY WHERE YOU ARE. Typing looks through every clip
   in every folder: a drill-down that could only search the drawer you had
   already opened would have taken something away. */
function studio_visible() {
  const q = studio.q.trim().toLowerCase();
  const out = [];
  const favOnly = studio.game === 'fav';
  /* ONLY THE PICKED ONES, from any level. A filter rather than a highlight,
     so the tray, a shift-range and Select run all agree with what is on
     screen -- the three places a highlight would have quietly disagreed. */
  const only = studio.onlyPicked ? new Set(studio.selected) : null;
  (studio.lib ? studio.lib.games : []).forEach(g => {
    if (!q && !favOnly && !only && studio.game !== 'all' && g.game !== studio.game) return;
    g.folders.forEach(f => {
      if (!q && !only && studio.run && f.folder !== studio.run) return;
      const clips = f.clips.filter(c => (!favOnly || c.fav) && (!only || only.has(c.id)) && (!q ||
        (c.name + ' ' + c.caption + ' ' + f.label + ' ' + g.game).toLowerCase().indexOf(q) >= 0));
      /* IN THE ORDER THEY ARE ON SCREEN, because this is what shift-click
         ranges over. An open run draws its clips under the match each came
         from, so the rank order the manifest has is not what the eye sees,
         and a range would take clips from three groups at once. */
      if (!q && f.folder === studio.run && (f.matches || []).length) {
        const last = f.matches.length;
        clips.sort((a, b) => (a.match === undefined ? last : a.match) -
                             (b.match === undefined ? last : b.match));
      }
      if (clips.length) out.push({game: g.game, folder: f, clips: clips});
    });
  });
  return out;
}

/* WHERE THE PICKED CLIPS ARE, counted once per render.

   A drill-down hides clips behind a click, so a selection made two levels in
   -- or handed to you by "Add clips to this reel" -- is invisible from the
   folder grid. Every level therefore says how many of its clips are picked,
   and the tray names the runs. Counted from `studio.selected` against the
   library the page already has; no new route. */
function studio_picked() {
  const on = new Set(studio.selected);
  const byGame = {}, byFolder = {}, runs = [];
  const seen = {};
  studio.selected.forEach(id => {
    const c = studio.clipIndex[id];
    if (!c) return;
    byGame[c.game] = (byGame[c.game] || 0) + 1;
    byFolder[c.folder] = (byFolder[c.folder] || 0) + 1;
    if (!seen[c.folder]) {
      seen[c.folder] = {folder: c.folder, game: c.game, label: c.folderLabel, n: 0};
      runs.push(seen[c.folder]);
    }
    seen[c.folder].n++;
  });
  runs.sort((a, b) => b.n - a.n);
  return {on: on, byGame: byGame, byFolder: byFolder, runs: runs, total: on.size};
}

/* The pill that says how many of something are picked. Nothing when none
   are: a row of zeroes is noise, and the absence is the answer. */
function studio_pickedPill(n, word) {
  if (!n) return '';
  return '<span class="studio-picked">' + n + ' ' + (word || 'picked') + '</span>';
}

/* A run as a chip: the game, when it was, and how many of its clips are in.
   Pressing it opens that run, which is the question behind the question. */
function studio_runChip(r, word) {
  return '<button type="button" class="chip studio-srcchip" data-act="studio-open-run" data-folder="' +
    esc(r.folder) + '" title="Open this run">' + esc(r.game) + ' · ' + esc(r.label) +
    ' <b>' + r.n + '</b></button>';
}

/* Which of the three levels is on screen. The search is a level of its own:
   it answers across the whole library, from wherever it was typed. */
function studio_level() {
  if (studio.onlyPicked) return 'picked';
  if (studio.q.trim()) return 'search';
  if (studio.game === 'all') return 'folders';
  if (studio.game === 'fav') return 'fav';
  return studio.run ? 'clips' : 'runs';
}

/* The run a folder path belongs to, and the game it is in. */
function studio_runOf(path) {
  let hit = null;
  (studio.lib ? studio.lib.games : []).forEach(g => g.folders.forEach(f => {
    if (f.folder === path) hit = {game: g.game, folder: f};
  }));
  return hit;
}

function studio_thumbOf(c, cls) {
  const kill = (c && c.kills && c.kills.length ? c.kills[0] : 0);
  const at = Math.max(0, kill - 0.3).toFixed(2);
  return '<img loading="lazy" alt="" class="' + cls + '" src="' +
    studio_media('/api/studio/thumb', c.path, '&t=' + at + '&v=' + (c.mtime || 0)) + '">';
}

/* Where a match starts in the recording, said the way a person would say it. */
function studio_into(t) {
  t = Math.max(0, Math.round(Number(t) || 0));
  const h = Math.floor(t / 3600), m = Math.round((t % 3600) / 60);
  return t < 60 ? t + 's' : h ? h + 'h ' + m + 'm' : m + 'm';
}

function studio_longDur(t) {
  t = Math.max(0, Math.round(Number(t) || 0));
  return t < 60 ? t + 's' : studio_into(t);
}

/* LEVEL 1 -- one card per game, not 339 clip tiles. The mosaic is the newest
   runs' best clip, so a folder is recognised by its footage rather than read
   as a line of text. */
function studio_folderCards() {
  const lib = studio.lib;
  const picked = studio_picked();
  let html = '<div class="studio-folders">';
  lib.games.forEach(g => {
    const covers = [];
    g.folders.forEach(f => { if (covers.length < 4 && f.clips.length) covers.push(f.clips[0]); });
    (g.folders[0] ? g.folders[0].clips : []).forEach(c => {
      if (covers.length < 4 && covers.indexOf(c) < 0) covers.push(c);
    });
    const runs = g.folders.length;
    const newest = g.folders[0] ? g.folders[0].label : '';
    html += '<button type="button" class="studio-folder-card" data-act="studio-open-folder" ' +
      'data-game="' + esc(g.game) + '" aria-label="Open ' + esc(g.game) + ', ' + g.clips + ' clips">' +
      '<span class="studio-folder-mosaic">' +
      covers.map(c => studio_thumbOf(c, '')).join('') + '</span>' +
      '<span class="studio-folder-card-body"><span class="studio-folder-card-name">' + esc(g.game) +
      studio_pickedPill(picked.byGame[g.game], studio.adding ? 'in this reel' : 'picked') + '</span>' +
      '<span class="studio-folder-card-facts">' + g.clips + ' clips · ' + runs +
      (runs === 1 ? ' run' : ' runs') + (newest ? '<br>newest ' + esc(newest) : '') + '</span>' +
      '<span class="studio-folder-go">Open →</span></span></button>';
  });
  /* Favourites cut across every game, so the card sits with the folders
     rather than inside one of them. */
  html += '<button type="button" class="studio-folder-card studio-fav-card" data-act="studio-open-folder" ' +
    'data-game="fav" aria-label="Open your favourites"' +
    ((lib.fav_count || 0) ? '' : ' disabled title="Star a clip with the star on its card"') + '>' +
    '<span class="studio-folder-mosaic studio-folder-star">★</span>' +
    '<span class="studio-folder-card-body"><span class="studio-folder-card-name">Favourites</span>' +
    '<span class="studio-folder-card-facts">' + (lib.fav_count || 0) +
    ' clips · across every game</span><span class="studio-folder-go">Open →</span></span></button>';
  return html + '</div>';
}

/* A match as a chip: the map and the score, coloured by whether it was won. */
function studio_matchChip(m) {
  const cls = m.won === true ? ' is-win' : m.won === false ? ' is-loss' : '';
  return '<span class="studio-mchip' + cls + '">' + esc(m.map || 'Match') +
    (m.score ? ' · ' + m.score[0] + '–' + m.score[1] : m.mode ? ' · ' + esc(m.mode) : '') + '</span>';
}

/* LEVEL 2 -- the runs in one folder. A run is a sitting at the PC, which is
   what the folder on disk is; the matches inside it come from the Riot records
   the Clips page already fetched. */
function studio_runRows(game) {
  const g = (studio.lib.games || []).filter(x => x.game === game)[0];
  if (!g) return '';
  const picked = studio_picked();
  const pos = {};
  studio.selected.forEach(id => { pos[id] = 1; });
  let html = '<div class="studio-runs">';
  g.folders.forEach(f => {
    const ms = f.matches || [];
    const kills = f.clips.reduce((n, c) => n + (c.kill_count || 0), 0);
    const secs = f.clips.reduce((n, c) => n + (c.duration || 0), 0);
    const allOn = f.clips.every(c => pos[c.id]);
    html += '<div class="studio-run">' +
      '<button type="button" class="studio-run-hit" data-act="studio-open-run" data-folder="' +
      esc(f.folder) + '" aria-label="Open ' + esc(f.label) + '">' +
      (f.clips.length ? studio_thumbOf(f.clips[0], 'studio-run-shot') : '') +
      '<span class="studio-run-who"><span class="studio-run-name">' + esc(f.label) +
      studio_pickedPill(picked.byFolder[f.folder], studio.adding ? 'in this reel' : 'picked') + '</span>' +
      '<span class="studio-run-facts">' + f.clips.length +
      (f.clips.length === 1 ? ' clip · ' : ' clips · ') + kills +
      (kills === 1 ? ' kill · ' : ' kills · ') + studio_longDur(secs) + ' of footage' +
      (ms.length ? ' · ' + ms.length + (ms.length === 1 ? ' match' : ' matches') : '') + '</span>' +
      (ms.length ? '<span class="studio-mchips">' + ms.map(studio_matchChip).join('') + '</span>' : '') +
      '</span></button>' +
      '<span class="studio-run-acts">' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-folder" data-folder="' +
      esc(f.folder) + '">' + (allOn ? 'Unselect run' : 'Select run') + '</button>' +
      '<button type="button" class="btn btn-sm" data-act="studio-open-run" data-folder="' +
      esc(f.folder) + '">Open</button></span></div>';
  });
  return html + '</div>';
}

/* LEVEL 3 -- the clips in one run, under the match each was cut from.

   Nothing here is detected: the match spans are in the run's own session.json
   and the map, mode and score in the record the Clips page fetched. A run with
   no records (CS2, anything imported) shows the one grid it always did, and
   clips that fall outside every match get their own group rather than being
   quietly dropped. */
function studio_matchSections(gr, pos) {
  const ms = gr.folder.matches || [];
  const tile = c => studio_tile(c, pos[c.id]);
  if (!ms.length) return '<div class="studio-grid">' + gr.clips.map(tile).join('') + '</div>';
  let html = '';
  ms.forEach((m, i) => {
    const mine = gr.clips.filter(c => c.match === i);
    if (!mine.length) return;
    const allOn = mine.every(c => pos[c.id]);
    const cls = m.won === true ? ' is-win' : m.won === false ? ' is-loss' : '';
    html += '<section class="studio-match" aria-label="' + esc(m.map || ('Match ' + (i + 1))) + '">' +
      '<div class="studio-match-h"><span class="studio-match-name">Match ' + (i + 1) +
      (m.map ? ' · ' + esc(m.map) : '') + '</span>' +
      studio_pickedPill(mine.filter(c => pos[c.id]).length, studio.adding ? 'in this reel' : 'picked') +
      (m.mode ? '<span class="muted">' + esc(m.mode) + '</span>' : '') +
      (m.score ? '<span class="studio-match-score mono' + cls + '">' + m.score[0] + ' – ' + m.score[1] + '</span>' : '') +
      (m.kills === undefined ? '' : '<span class="muted">' + m.kills + ' / ' + m.deaths + ' / ' + m.assists + ' K/D/A</span>') +
      '<span class="muted">' + mine.length + ' clips · ' + m.clip_kills + ' kills · ' +
      studio_longDur(m.clip_seconds) + '</span>' +
      '<span class="muted">at ' + studio_into(m.at) + ' into the recording</span>' +
      '<button type="button" class="btn btn-ghost btn-sm studio-match-btn" data-act="studio-match" ' +
      'data-match="' + i + '">' + (allOn ? 'Unselect match' : 'Select match') + '</button></div>' +
      '<div class="studio-grid">' + mine.map(tile).join('') + '</div></section>';
  });
  const rest = gr.clips.filter(c => c.match === undefined);
  if (rest.length) {
    const allOn = rest.every(c => pos[c.id]);
    html += '<section class="studio-match" aria-label="Outside those matches">' +
      '<div class="studio-match-h"><span class="studio-match-name">Outside those matches</span>' +
      '<span class="muted">' + rest.length + (rest.length === 1 ? ' clip' : ' clips') +
      ' · warm-up, the range, or a match with no record</span>' +
      '<button type="button" class="btn btn-ghost btn-sm studio-match-btn" data-act="studio-match" ' +
      'data-match="-1">' + (allOn ? 'Unselect these' : 'Select these') + '</button></div>' +
      '<div class="studio-grid">' + rest.map(tile).join('') + '</div></section>';
  }
  return html;
}

/* ADDING CLIPS TO A REEL: WHICH ONES, AND FROM WHERE.

   "Add clips" pre-selects everything already in the reel, and the library
   opens on folder cards -- so the thirteen clips it just ticked for you were
   invisible until you happened to open the right run. The band names the
   reel, counts what is in it, and carries a chip per run those clips came
   from; each chip opens that run. */
function studio_addingBand(picked) {
  const ad = studio.adding;
  if (!ad) return '';
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  const secs = sel.reduce((n, c) => n + (c.duration || 0), 0);
  const kills = sel.reduce((n, c) => n + studio_killsOf(c), 0);
  return '<section class="studio-band" aria-label="Adding clips to ' + esc(ad.name) + '">' +
    '<div class="studio-band-who"><strong>Adding to ' + esc(ad.name) + '</strong>' +
    '<span class="muted studio-small">' + sel.length + (sel.length === 1 ? ' clip' : ' clips') +
    ' in it · ' + studio_dur(secs) + ' · ' + kills + (kills === 1 ? ' kill' : ' kills') + '</span></div>' +
    (picked.runs.length
      ? '<div class="studio-band-runs"><span class="muted studio-small">from</span>' +
        picked.runs.map(r => studio_runChip(r)).join('') +
        '<button type="button" class="chip' + (studio.onlyPicked ? ' is-on' : '') +
        '" data-act="studio-only-picked" aria-pressed="' + (studio.onlyPicked ? 'true' : 'false') + '">' +
        (studio.onlyPicked ? 'Show every clip' : 'Show only these ' + picked.total) + '</button></div>'
      : '<span class="muted studio-small">Nothing is picked yet. Tick the clips you want to add.</span>') +
    '<span class="studio-band-acts">' +
    '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-add-cancel">Stop adding</button>' +
    '<button type="button" class="btn btn-sm" data-act="studio-make">Rebuild ' + esc(ad.name) + '</button>' +
    '</span></section>';
}

/* The line above the library saying where you are and how to get back. */
function studio_crumbs(level, game, label) {
  if (level === 'folders') return '';
  const back = '<button type="button" class="studio-crumb" data-act="studio-crumb" data-to="folders">Folders</button>';
  if (level === 'search') return '<nav class="studio-crumbs" aria-label="Where you are">' + back +
    '<span class="studio-crumb-sep">›</span><span class="studio-crumb-now">Search</span></nav>';
  if (level === 'picked') return '<nav class="studio-crumbs" aria-label="Where you are">' + back +
    '<span class="studio-crumb-sep">›</span><span class="studio-crumb-now">The clips you have picked</span></nav>';
  if (level === 'fav') return '<nav class="studio-crumbs" aria-label="Where you are">' + back +
    '<span class="studio-crumb-sep">›</span><span class="studio-crumb-now">★ Favourites</span></nav>';
  let html = '<nav class="studio-crumbs" aria-label="Where you are">' + back + '<span class="studio-crumb-sep">›</span>';
  if (level === 'clips') {
    html += '<button type="button" class="studio-crumb" data-act="studio-crumb" data-to="runs">' +
      esc(game) + '</button><span class="studio-crumb-sep">›</span>' +
      '<span class="studio-crumb-now">' + esc(label) + '</span>';
  } else {
    html += '<span class="studio-crumb-now">' + esc(game) + '</span>';
  }
  return html + '</nav>';
}

/* YOUR REELS. It used to be the newest ten and nothing else: an eleventh reel
   could only be reached through the file explorer, and the timeline it was
   made on not at all. Now every reel, folded to two rows until asked, with a
   search, the reel's shape and an order -- and a still of its first kill, so a
   grid of eighty is something to look at rather than to read. */
const STUDIO_REELS_FOLDED = 8;
const STUDIO_REEL_SORTS = {
  new: (a, b) => b.when - a.when,
  old: (a, b) => a.when - b.when,
  name: (a, b) => String(a.name).localeCompare(String(b.name), undefined, {numeric: true, sensitivity: 'base'}),
  long: (a, b) => (b.length || 0) - (a.length || 0)
};

function studio_reelCard(r) {
  const fmt = r.format === 'vertical' ? '9:16' : r.format === 'landscape' ? '16:9' : '';
  const style = studio.catalog ? (studio.catalog.styles || []).filter(s => s.key === r.style)[0] : null;
  const facts = [style ? style.label : '', r.shots ? r.shots + ' shots' : '',
                 r.lyrics ? 'lyrics' : ''].filter(Boolean).join(' · ');
  return '<article class="studio-reel" aria-label="' + esc(r.name) + '">' +
    /* The still plays the reel: the biggest target on the card does the
       commonest thing. */
    '<button type="button" class="studio-reel-thumb' + (r.format === 'vertical' ? ' is-tall' : '') + '" data-act="studio-watch" ' +
    'data-path="' + esc(r.path) + '" aria-label="Play ' + esc(r.name) + '">' +
    '<img loading="lazy" alt="" src="' + studio_media('/api/studio/thumb', r.path, '&t=' + (r.poster || 1) + '&v=' + r.when) + '">' +
    (fmt ? '<span class="studio-reel-badge">' + fmt + '</span>' : '') +
    (r.length ? '<span class="studio-reel-len">' + studio_dur(r.length) + '</span>' : '') +
    '</button>' +
    '<span class="studio-reel-name truncate" title="' + esc(r.name) + '">' + esc(r.name) + '</span>' +
    '<span class="muted studio-reel-meta">' + esc(facts ? facts + ' · ' : '') +
    new Date(r.when * 1000).toLocaleDateString() + '</span>' +
    (r.song ? '<span class="muted studio-reel-meta truncate" title="' + esc(r.song) + '">♪ ' + esc(r.song.replace(/\s*\[[^\]]*\]\s*$/, '')) + '</span>' : '') +
    '<span class="field-inline">' +
    (r.project ? '<button type="button" class="btn btn-sm" data-act="studio-open" data-path="' + esc(r.path) + '">Open timeline</button>'
               : '<span class="muted studio-reel-old">Made before the Studio</span>') +
    /* A reel is the biggest file the app makes and the easiest to make
       another of, so it needs a way out that is not the file explorer. */
    '<button type="button" class="btn btn-ghost btn-sm studio-del-btn" data-act="studio-reel-del" ' +
    'data-path="' + esc(r.path) + '" data-name="' + esc(r.name) + '" ' +
    'title="Delete this reel">Delete…</button>' +
    '</span></article>';
}

function studio_renderReels() {
  const all = (studio.lib && studio.lib.reels) || [];
  studio_show('studio-reels', all.length > 0);
  studio_show('studio-reels-none', !all.length);
  const tabn = studio_el('studio-tab-reels-n');
  if (tabn) tabn.textContent = all.length || '';
  if (!all.length) return;
  studio_el('studio-reels-count').textContent = all.length;
  const counts = {all: all.length, vertical: 0, landscape: 0};
  all.forEach(r => { if (counts[r.format] !== undefined) counts[r.format]++; });
  const fmt = studio.reelFmt || 'all';
  studio_el('studio-reel-fmts').innerHTML = [['all', 'All'], ['vertical', 'Vertical'], ['landscape', 'Landscape']]
    .filter(f => f[0] === 'all' || counts[f[0]])
    .map(f => '<button type="button" class="chip' + (fmt === f[0] ? ' is-on' : '') + '" data-act="studio-reel-fmt" data-fmt="' +
      f[0] + '" aria-pressed="' + (fmt === f[0]) + '">' + f[1] + ' <b>' + counts[f[0]] + '</b></button>').join('');
  const q = (studio.reelQ || '').trim().toLowerCase();
  const words = q ? q.split(/\s+/) : [];
  const styleName = k => { const s = studio.catalog ? (studio.catalog.styles || []).filter(x => x.key === k)[0] : null; return s ? s.label : k; };
  const hits = all.filter(r => (fmt === 'all' || r.format === fmt) &&
    words.every(w => (r.name + ' ' + styleName(r.style) + ' ' + (r.song || '') + ' ' + (r.lyrics ? 'lyrics' : '')).toLowerCase().indexOf(w) >= 0))
    .slice().sort(STUDIO_REEL_SORTS[studio.reelSort] || STUDIO_REEL_SORTS.new);
  /* Folded only when nothing narrows the list: a search or a filter is
     already the answer to "which of my reels", and hiding half of it would be
     a second question. */
  const narrowed = !!words.length || fmt !== 'all';
  const shown = studio.reelsAll || narrowed ? hits : hits.slice(0, STUDIO_REELS_FOLDED);
  studio_el('studio-reel-grid').innerHTML = shown.map(studio_reelCard).join('');
  const none = studio_el('studio-reel-none');
  studio_show('studio-reel-none', !hits.length);
  if (!hits.length) none.textContent = 'No reel matches that.';
  const more = studio_el('studio-reels-more');
  const folds = !narrowed && hits.length > STUDIO_REELS_FOLDED;
  studio_show('studio-reels-more', folds);
  if (folds) {
    more.textContent = studio.reelsAll ? 'Show fewer' : 'Show all ' + hits.length + ' reels';
    more.setAttribute('aria-expanded', studio.reelsAll ? 'true' : 'false');
  }
}

function studio_renderLib() {
  const lib = studio.lib;
  if (!lib) return;
  /* A run deleted, or a game whose last clip has gone, since the page was
     last read: fall back to the level above rather than to an empty pane. */
  if (studio.run && !studio_runOf(studio.run)) studio.run = '';
  if (studio.game !== 'all' && studio.game !== 'fav' &&
      !lib.games.some(g => g.game === studio.game)) { studio.game = 'all'; studio.run = ''; }
  const games = lib.games.length;
  const runs = lib.games.reduce((n, g) => n + g.folders.length, 0);
  studio_el('studio-sub').textContent = lib.clip_count
    ? lib.clip_count + (lib.clip_count === 1 ? ' clip' : ' clips') + ' in ' +
      runs + (runs === 1 ? ' run' : ' runs') +
      ' across ' + games + (games === 1 ? ' game' : ' games') +
      '. Open a folder to pick from it — or search, which looks in all of them.'
    : 'No clips yet. Cut some on the Clips page and they will appear here.';
  /* The chips are the quick way between folders: the same navigation as the
     cards, for someone already two levels in. */
  studio_el('studio-games').innerHTML =
    '<button type="button" class="chip' + (studio.game === 'all' ? ' is-on' : '') +
    '" data-act="studio-game" data-game="all" aria-pressed="' + (studio.game === 'all') + '">All folders <b>' +
    lib.clip_count + '</b></button>' +
    lib.games.map(g => '<button type="button" class="chip' + (studio.game === g.game ? ' is-on' : '') +
      '" data-act="studio-game" data-game="' + esc(g.game) + '" aria-pressed="' + (studio.game === g.game) +
      '">' + esc(g.game) + ' <b>' + g.clips + '</b></button>').join('') +
    /* Favourites cut across games, so the chip sits apart from them. */
    '<button type="button" class="chip studio-fav-chip' + (studio.game === 'fav' ? ' is-on' : '') +
    '" data-act="studio-game" data-game="fav" aria-pressed="' + (studio.game === 'fav') + '"' +
    ((lib.fav_count || 0) ? '' : ' disabled title="Star a clip with the star on its card"') +
    '>\u2605 Favourites <b>' + (lib.fav_count || 0) + '</b></button>';

  studio_renderReels();

  /* THE LIBRARY OPENS ON FOLDERS, NOT ON EVERY CLIP. It used to write a
     heading per game and a tile per clip in one pane: 339 clips in 42 runs on
     the developer's own machine, which is 339 thumbnails and four buttons each
     before the player has said what they are looking for. Now a folder opens
     on its runs and a run opens on its clips, grouped by the match they came
     from -- and the search still answers from the whole library. */
  const level = studio_level();
  const open = studio.run ? studio_runOf(studio.run) : null;
  const groups = studio_visible();
  const pos = {};
  studio.selected.forEach((id, i) => { pos[id] = i + 1; });
  const picked = studio_picked();
  let html = studio_addingBand(picked) + studio_crumbs(level, studio.game, open ? open.folder.label : '');
  if (level === 'folders') {
    html += studio_folderCards();
  } else if (level === 'runs') {
    html += studio_runRows(studio.game);
  } else if (level === 'clips' && open) {
    const gr = groups.filter(x => x.folder.folder === studio.run)[0];
    const kills = gr ? gr.clips.reduce((n, c) => n + (c.kill_count || 0), 0) : 0;
    const allOn = gr && gr.clips.every(c => pos[c.id]);
    html += '<div class="studio-folder-h studio-run-head"><h3 class="studio-game-h">' +
      esc(open.folder.label) + '</h3><span class="muted">' + (gr ? gr.clips.length : 0) +
      ' clips · ' + kills + ' kills</span>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-folder" data-folder="' +
      esc(studio.run) + '">' + (allOn ? 'Unselect run' : 'Select run') + '</button></div>' +
      (gr ? studio_matchSections(gr, pos) : '');
  } else {
    /* Favourites, and every search result: one grid per run it came from, so
       a hit still says which sitting it belongs to. */
    let lastGame = '';
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
  }
  studio_el('studio-lib').innerHTML = html;
  const empty = level !== 'folders' && !groups.length;
  studio_show('studio-empty', empty && lib.clip_count > 0);
  if (empty && lib.clip_count) studio_el('studio-empty').textContent = level === 'search'
    ? 'Nothing matches that search.'
    : level === 'fav' ? 'No favourites yet. Star a clip with the star on its card.'
    : 'Nothing in this folder.';
  studio_renderTray();
}

/* How many kills a clip carries. A clip with no count at all is one kill, as
   it always was; a count of ZERO is zero. `kill_count || 1` read both as one,
   so a round cut for a team label showed as "1 kill" and added to every total. */
function studio_killsOf(c) {
  return typeof c.kill_count === 'number' ? c.kill_count : 1;
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
    '<span class="studio-clip-kills">' + (c.unmarked ? 'no kills marked' : studio_killsOf(c) === 0 ? 'no kills'
      : studio_killsOf(c) > 1 ? studio_killsOf(c) + ' kills' : '1 kill') +
      /* Valorant: how many of them were read as headshots. */
      (c.hs && c.hs.length ? ' · ' + c.hs.filter(h => h === true).length + ' HS' : '') + '</span>' +
    '</button>' +
    '<div class="studio-clip-foot"><span class="truncate" title="' + esc(c.name) + '">' +
    esc(c.caption || c.name) + '</span>' +
    '<button type="button" class="studio-star' + (c.fav ? ' is-on' : '') + '" data-act="studio-fav" data-clip="' +
      esc(c.id) + '" title="' + (c.fav ? 'A favourite. Click to unstar.' : 'Mark as a favourite') +
      '" aria-pressed="' + (c.fav ? 'true' : 'false') + '" aria-label="Favourite">' +
      (c.fav ? '\u2605' : '\u2606') + '</button>' +
    /* EDIT ON EVERY CLIP, not only on imported ones.

       This was gated on `c.imported`, and that flag is set only for clips
       that came in through Add your own clip -- so a clip AutoStream cut for
       itself had no way back into the marker at all. If the detector put a
       kill half a second late, or a clip deserved a better title, there was
       nothing to press.

       The marker never cared where a clip came from: studio_impOpen(path)
       takes a path. What was missing was the way in. */
    '<button type="button" class="btn btn-ghost btn-sm' +
      (c.unmarked ? ' is-warn' : '') + '" data-act="studio-imp-edit" ' +
      'data-path="' + esc(c.path) + '" title="' +
      (c.imported ? 'Mark its kills and give it a title'
                  : 'Correct its kills or change the title') + '">' +
      (c.unmarked ? 'Mark kills' : 'Edit') + '</button>' +
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
  const vis = studio_visible();
  vis.forEach(gr => {
    const btn = document.querySelector('#studio-lib [data-act="studio-folder"][data-folder="' + CSS.escape(gr.folder.folder) + '"]');
    if (btn) btn.textContent = gr.clips.every(c => pos[c.id]) ? 'Unselect run' : 'Select run';
  });
  /* The per-match buttons on the open run, which are the same promise over a
     smaller set and would otherwise go on saying Select after one. */
  const open = vis.filter(gr => gr.folder.folder === studio.run)[0];
  if (open) document.querySelectorAll('#studio-lib [data-act="studio-match"]').forEach(btn => {
    const i = Number(btn.getAttribute('data-match'));
    const mine = open.clips.filter(c => (c.match === undefined ? -1 : c.match) === i);
    if (!mine.length) return;
    const allOn = mine.every(c => pos[c.id]);
    btn.textContent = i < 0 ? (allOn ? 'Unselect these' : 'Select these')
                            : (allOn ? 'Unselect match' : 'Select match');
  });
  studio_renderTray();
}

function studio_renderTray() {
  studio_favLabel();
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  studio_show('studio-tray', sel.length > 0);
  studio_el('studio-tray-count').textContent = sel.length + (sel.length === 1 ? ' clip' : ' clips');
  const secs = sel.reduce((n, c) => n + c.duration, 0);
  const kills = sel.reduce((n, c) => n + studio_killsOf(c), 0);
  const games = new Set(sel.map(c => c.game)).size;
  const picked = studio_picked();
  studio_el('studio-tray-facts').textContent = sel.length
    ? studio_dur(secs) + ' of footage · ' + kills + ' kills' +
      (games > 1 ? ' · ' + games + ' games' : '') +
      (picked.runs.length > 1 ? ' · from ' + picked.runs.length + ' runs' : '') : '';
  /* WHICH RUNS, not just how many. A count tells you the selection is
     scattered; the chips tell you where, and each one opens that run. */
  const where = studio_el('studio-tray-runs');
  if (where) {
    const many = picked.runs.length > 1 && !studio.adding;
    studio_show('studio-tray-runs', many);
    if (many) where.innerHTML = picked.runs.map(r => studio_runChip(r)).join('');
  }
  const ad = studio.adding;
  /* The band at the top of the pane says all of this now, and says where
     the clips are as well -- which a line in the tray could not. */
  studio_show('studio-adding', false);
  studio_show('studio-add-cancel', !!ad);
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

/* Moving between the levels. The library pane is scrolled to rather than the
   page top: the reels sit above it, and arriving at a folder's runs with the
   reels filling the screen reads as nothing having happened. */
function studio_libShow() {
  studio_renderLib();
  const lib = studio_el('studio-lib');
  if (lib) lib.scrollIntoView({block: 'start'});
}

function studio_goLib(to) {
  if (to === 'folders') studio.game = 'all';
  studio.run = '';
  /* Going back up is how you get out of "only these": a crumb that left the
     filter on would show a folder grid of one game and no way to tell why. */
  studio.onlyPicked = false;
  studio_libShow();
}

function studio_openFolder(game) {
  studio.game = game;
  studio.run = '';
  studio_libShow();
}

function studio_openRun(folder) {
  const hit = studio_runOf(folder);
  if (!hit) return;
  studio.game = hit.game;
  studio.run = folder;
  studio_libShow();
}

/* Every clip of one match, on or off together -- the same promise "Select
   run" makes one level up. -1 is the clips that fall outside every match. */
function studio_matchToggle(i) {
  const gr = studio_visible().filter(x => x.folder.folder === studio.run)[0];
  if (!gr) return;
  const ids = gr.clips.filter(c => (c.match === undefined ? -1 : c.match) === i).map(c => c.id);
  if (!ids.length) return;
  const all = ids.every(id => studio.selected.indexOf(id) >= 0);
  if (all) studio.selected = studio.selected.filter(id => ids.indexOf(id) < 0);
  else ids.forEach(id => { if (studio.selected.indexOf(id) < 0) studio.selected.push(id); });
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
  if (studio.fxp) studio_fxpClose();
  const v = studio_el('studio-preview-video');
  if (v) { v.pause(); v.removeAttribute('src'); v.load(); }
  const a = studio_el('studio-mk-audio');
  if (a && !a.paused) a.pause();
  ['studio-preview-scrim', 'studio-make-scrim', 'studio-guide-scrim', 'studio-del-scrim',
   'studio-rdel-scrim', 'studio-intro-scrim'].forEach(id => studio_show(id, false));
  studio_makePage(false);
  if (!studio_el('studio-imp-scrim').classList.contains('hide')) studio_impClose(false);
  const iv = studio_el('studio-intro-video');
  if (iv && !iv.paused) iv.pause();
  if (!studio.yt.running) studio_show('studio-yt-scrim', false);
  studio_palClose();
  studio_show('studio-keys-scrim', false);
}

/* --------------------------------------------------- every action, by name

   STUDIO_CMDS and STUDIO_SCOPES come from ui/commands.py. NOTHING HERE KEEPS
   A SECOND LIST: the command list (Ctrl+K), the key sheet (?) and the browser
   tier's /api/studio/commands all read that one, which is the whole point --
   a sheet typed by hand is wrong the first time a binding moves.

   A command RUNS by pressing the control the page already has for it, found
   by its data-act and whatever data attributes pick it out. That is
   deliberate: 147 actions already work, and a list that reimplemented any of
   them would be a second answer to the same question, free to disagree. The
   few with no control of their own (next shot, close this) name a function in
   STUDIO_RUN instead.

   WHY, NOT GREY. studio_cmdWhy returns the reason a command cannot run, in
   words, and both the list and the key read it. A key that does nothing in
   silence is how someone presses it three times and concludes the app is
   broken. */

const STUDIO_RUN = {
  'studio.palette': () => studio_palOpen(),
  'studio.keys': () => studio_keysOpen(),
  'studio.palette-close': () => studio_palClose(),
  'studio.keys-close': () => studio_show('studio-keys-scrim', false),
  'studio.escape': () => studio_closeModals(),
  'timeline.next-shot': () => studio_select(Math.min(studio.project.shots.length - 1, studio.sel + 1)),
  'timeline.prev-shot': () => studio_select(Math.max(0, studio.sel - 1))
};

/* The guards that are about the reel rather than about the control. Delete
   refusing to go below one shot lives HERE, so the key, the button and the
   list all obey the one rule; it used to be a condition inside the keydown
   block, where nothing else could see it. */
const STUDIO_WHEN = {
  'timeline.next-shot': () => (studio.project && studio.sel < studio.project.shots.length - 1)
    ? '' : 'You are on the last shot.',
  'timeline.prev-shot': () => (studio.project && studio.sel > 0) ? '' : 'You are on the first shot.',
  'timeline.remove-shot': () => !studio.project ? 'Open a reel first.'
    : studio.sel < 0 ? 'Select a shot first.'
    : studio.project.shots.length < 2 ? 'A reel keeps at least one shot, and this is the last one.' : '',
  'timeline.undo': () => studio.undo.length ? '' : 'There is nothing to undo.',
  'make.open': () => studio.selected.length ? '' : 'Pick some clips first.',
  'library.clear': () => studio.selected.length ? '' : 'No clips are picked.',
  'library.favourite-picked': () => studio.selected.length ? '' : 'No clips are picked.',
  'library.delete': () => studio.selected.length ? '' : 'No clips are picked.',
  'studio.go-timeline': () => studio.project ? '' : 'Make or open a reel first.',
  'studio.go-song': () => studio.project ? '' : 'Make or open a reel first.',
  'studio.go-facecam': () => studio.project ? '' : 'Make or open a reel first.'
};

function studio_cmd(id) { return STUDIO_CMDS.filter(c => c.id === id)[0] || null; }

function studio_scopeName(id) {
  const s = STUDIO_SCOPES.filter(x => x.id === id)[0];
  return s ? s.label : id;
}

/* The control a command stands on. A per-shot button is drawn once per shot,
   so the visible one wins; offsetParent is null for anything inside a folded
   or hidden pane, which is also how "not on screen just now" is known. */
function studio_cmdEl(c) {
  if (!c.act) return null;
  const host = document.getElementById('view-studio');
  if (!host) return null;
  let q = '[data-act="' + c.act + '"]';
  Object.keys(c.args || {}).forEach(k => { q += '[' + k + '="' + c.args[k] + '"]'; });
  let all = [];
  try { all = [].slice.call(host.querySelectorAll(q)); } catch (err) { return null; }
  return all.filter(el => el.offsetParent !== null && !el.disabled)[0] || all[0] || null;
}

/* '' when it can run, otherwise why not, in the user's words. */
function studio_cmdWhy(c) {
  if (!c) return 'That command is gone.';
  if (STUDIO_WHEN[c.id]) {
    const said = STUDIO_WHEN[c.id]();
    if (said) return said;
  }
  if (STUDIO_RUN[c.id]) return '';
  const el = studio_cmdEl(c);
  if (!el) return c.why || 'Not on this part of the page.';
  if (el.disabled) return c.why || 'Not just now.';
  if (el.offsetParent === null) return c.why || 'Not on screen just now.';
  return '';
}

function studio_cmdRun(id) {
  const c = studio_cmd(id);
  const why = studio_cmdWhy(c);
  if (why) { toast(why, 'warn'); return false; }
  studio.pal.recent = [id].concat(studio.pal.recent.filter(x => x !== id)).slice(0, 8);
  if (STUDIO_RUN[c.id]) { STUDIO_RUN[c.id](); return true; }
  const el = studio_cmdEl(c);
  if (!el) return false;
  el.click();
  return true;
}

/* Which scope's keys are in force, by the same order the keydown block reads
   them in. The list puts this scope's commands first: the answer to "what can
   I do" depends on where you are. */
function studio_palScope() {
  if (!studio_el('studio-imp-scrim').classList.contains('hide')) return 'import';
  if (studio.fxp) return 'picker';
  if (!studio_el('studio-pane-song').classList.contains('hide')) return 'song';
  if (!studio_el('studio-pane-timeline').classList.contains('hide')) return 'timeline';
  if (!studio_el('studio-pane-looks').classList.contains('hide')) return 'looks';
  return 'library';
}

/* One key as the sheet and the list draw it. */
function studio_keyCap(key) {
  const named = {Space: 'Space', Escape: 'Esc', Enter: '↵', Delete: 'Del',
                 Backspace: '⌫', ArrowLeft: '←', ArrowRight: '→',
                 ArrowUp: '↑', ArrowDown: '↓'};
  return String(key).split('+').map(part => {
    const one = named[part] || part;
    return '<kbd>' + esc(one) + '</kbd>';
  }).join('');
}

function studio_cmdKeys(c) {
  /* The first binding only. A command with three ways in ("+" and "=") would
     otherwise read as three keys to learn. */
  return c.keys.length ? studio_keyCap(c.keys[0]) : '';
}

function studio_palMatch(c, words) {
  if (!words.length) return true;
  const hay = (c.label + ' ' + c.id + ' ' + (c.act || '') + ' ' +
               studio_scopeName(c.scope)).toLowerCase();
  return words.every(w => hay.indexOf(w) >= 0);
}

function studio_palOpen() {
  studio.pal.open = true;
  studio.pal.q = '';
  studio.pal.sel = 0;
  studio_show('studio-pal-scrim', true);
  const q = studio_el('studio-pal-q');
  if (q) q.value = '';
  studio_palDraw();
  if (q) q.focus();
}

function studio_palClose() {
  if (!studio.pal.open) return;
  studio.pal.open = false;
  studio_show('studio-pal-scrim', false);
}

function studio_palDraw() {
  const host = studio_el('studio-pal-list');
  if (!host) return;
  const words = studio.pal.q.toLowerCase().split(/\s+/).filter(Boolean);
  const offered = STUDIO_CMDS.filter(c => c.palette && studio_palMatch(c, words));
  const here = studio_palScope();
  /* This pane first, then the rest in the order the keys are read. Recently
     run ones lead when nothing has been typed -- the thing done last is the
     thing most likely wanted again, and a search answers for itself. */
  const order = [here].concat(STUDIO_SCOPES.map(s => s.id).filter(x => x !== here));
  const groups = [];
  if (!words.length) {
    const recent = studio.pal.recent.map(studio_cmd)
      .filter(c => c && c.palette && !studio_cmdWhy(c));
    if (recent.length) groups.push({name: 'Just used', rows: recent});
  }
  order.forEach(sid => {
    const rows = offered.filter(c => c.scope === sid);
    if (rows.length) groups.push({name: studio_scopeName(sid) + (sid === here ? ' · where you are' : ''), rows: rows});
  });
  studio.pal.rows = [];
  groups.forEach(g => g.rows.forEach(c => studio.pal.rows.push(c)));
  if (studio.pal.sel >= studio.pal.rows.length) studio.pal.sel = 0;

  let n = -1;
  host.innerHTML = groups.map(g => {
    const rows = g.rows.map(c => {
      n += 1;
      const why = studio_cmdWhy(c);
      return '<button type="button" role="option" class="studio-pal-row' +
        (n === studio.pal.sel ? ' is-on' : '') + (why ? ' is-off' : '') +
        '" data-pal="' + esc(c.id) + '" data-n="' + n + '" aria-selected="' +
        (n === studio.pal.sel) + '">' +
        '<span class="studio-pal-lab">' + esc(c.label) +
        (why ? '<span class="studio-pal-why">' + esc(why) + '</span>' : '') + '</span>' +
        '<span class="studio-pal-keys">' + studio_cmdKeys(c) + '</span></button>';
    }).join('');
    return '<p class="studio-pal-grp">' + esc(g.name) + '</p>' + rows;
  }).join('') ||
    '<p class="studio-pal-none">Nothing by that name. The key sheet lists every action with a key.</p>';

  const count = studio_el('studio-pal-count');
  if (count) {
    const all = STUDIO_CMDS.filter(c => c.palette).length;
    count.textContent = studio.pal.rows.length === all
      ? all + ' actions'
      : studio.pal.rows.length + ' of ' + all;
  }
  const on = host.querySelector('.studio-pal-row.is-on');
  if (on && on.scrollIntoView) on.scrollIntoView({block: 'nearest'});
}

function studio_palMove(by) {
  const n = studio.pal.rows.length;
  if (!n) return;
  studio.pal.sel = (studio.pal.sel + by + n) % n;
  studio_palDraw();
}

/* The list's own keys, read before anything else on the page: while it is
   open it owns Up, Down, Enter and Escape even though the caret is in a text
   field, which is the one case the input guard below would get wrong. */
function studio_palKey(e) {
  if (!studio.pal.open) return false;
  if (e.key === 'Escape') { studio_palClose(); }
  else if (e.key === 'ArrowDown') { studio_palMove(1); }
  else if (e.key === 'ArrowUp') { studio_palMove(-1); }
  else if (e.key === 'Enter') {
    const c = studio.pal.rows[studio.pal.sel];
    if (!c) return true;
    studio_palClose();
    studio_cmdRun(c.id);
  }
  else return false;
  e.preventDefault();
  return true;
}

/* ------------------------------------------------------------- the key sheet

   Generated, never typed. The scopes print in the order the keydown block
   reads them, because that order is the answer to "why did Space press the
   button instead of playing the reel". */
function studio_keysOpen() {
  studio_palClose();
  const host = studio_el('studio-keys-cols');
  if (host) {
    host.innerHTML = STUDIO_SCOPES.map(s => {
      const rows = STUDIO_CMDS.filter(c => c.scope === s.id && c.keys.length);
      if (!rows.length) return '';
      return '<section class="studio-keys-grp"><h3>' + esc(s.label) + '</h3>' +
        '<p class="muted studio-small">' + esc(s.blurb) + '</p>' +
        rows.map(c => '<p class="studio-keys-row"><span>' + esc(c.label) + '</span>' +
          c.keys.map(k => studio_keyCap(k)).join('<span class="studio-keys-or">or</span>') +
          '</p>').join('') + '</section>';
    }).join('');
  }
  const count = studio_el('studio-keys-count');
  if (count) {
    const bound = STUDIO_CMDS.filter(c => c.keys.length).length;
    count.textContent = STUDIO_CMDS.length + ' actions, ' + bound + ' of them on a key';
  }
  studio_show('studio-keys-scrim', true);
  const done = document.querySelector('#studio-keys [data-act="studio-keys-close"]');
  if (done) done.focus();
}

/* ------------------------------------------------------------ make a reel */

async function studio_openMake() {
  if (!studio.selected.length) return;
  const sel = studio.selected.map(id => studio.clipIndex[id]).filter(Boolean);
  const ad = studio.adding;
  studio_el('studio-make-facts').textContent = sel.length + ' clips, ' +
    sel.reduce((n, c) => n + studio_killsOf(c), 0) + ' kills. Every cut and kill lands on the beat; ' +
    'you can change anything on the timeline afterwards.' +
    (ad ? ' Rebuilding ' + ad.name + ' plans every shot again' +
      (ad.edited ? ', so the changes you made on its timeline will be replaced.' : '.') : '');
  /* HEADSHOTS ONLY, offered when some chosen kills carry a headshot reading
     (Valorant). The note says what it would keep, so ticking it is not a
     guess at how short the reel becomes. */
  const hsKnown = sel.filter(c => c.hs && c.hs.length);
  const hsRow = studio_el('studio-hs-row');
  if (hsRow) {
    hsRow.classList.toggle('hide', !hsKnown.length);
    const heads = sel.reduce((n, c) => n + (c.hs || []).filter(h => h === true).length, 0);
    const all = sel.reduce((n, c) => n + (c.kills || []).length, 0);
    const withHs = sel.filter(c => (c.hs || []).some(h => h === true)).length;
    studio_el('studio-hs-note').textContent = '— ' + heads + ' of ' + all + ' kills were headshots, in ' +
      withHs + ' of ' + sel.length + ' clips. The rest are left out.';
  }
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
        studio.mk.drops = null; studio.mk.sel = {};
        studio.song = ad.song; studio.songShape = got.song;
        studio_el('studio-song-name').textContent = ad.song.split(/[\\/]/).pop() + ' · ' +
          Math.round(got.song.bpm) + ' BPM · ' + studio_dur(got.song.seconds);
      }
    }
    if (ad.song && studio.songShape) {
      studio.mk.mode = 'part'; studio.mk.touched = true;
      studio.mk.start = ad.start; studio.mk.end = Math.max(ad.start + studio_mkBar(), ad.end);
    }
    /* What the reel asked for, so a rebuild is the same kind of reel. */
    studio.fill = ad.fill || '';
    studio.keepAll = !!ad.keep_all;
  }
  studio_renderStyles();
  studio_hand();
  studio_show('studio-make-scrim', true);
  studio_makePage(true);
  studio_show('studio-mk-fit', studio.fmt === 'vertical');
  studio_mkDefault();
  studio_mkArrangeDraw();
  studio_fillDraw();
  studio_samplesCheck();
  studio_mkKillsDraw();
  studio_mkChip();
}

/* THE SAME CHIP AS THE GUIDED MAKER, on the full page: one verdict for the style, the song, the
   clips and the shape chosen here, from the same dry-run plan (clips/feasible.py). The page used to
   say nothing until the reel came out wrong. A fix that belongs to the guided steps is offered as
   what to do here, in words. */
function studio_mkChip() {
  const el = studio_el('studio-mk-chip');
  if (!el || studio_el('studio-make-scrim').classList.contains('hide') || !studio.selected.length) return;
  const ticket = studio.mkChipAsk = (studio.mkChipAsk || 0) + 1;
  clearTimeout(studio.mkChipTimer);
  studio.mkChipTimer = setTimeout(async () => {
    const got = await API.post('/api/studio/feasible', studio_planBody(false)).catch(() => null);
    if (ticket !== studio.mkChipAsk || !got || !got.ok) return;
    const v = got.verdict, label = {ok: 'Works', warn: 'Will work, but', bad: "Won't work"}[v.level];
    const act = {'pick-song': 'Choose another song above.', 'pick-clips': 'Go back and pick more clips.',
                 'format:vertical': '', 'style:drop': 'Choose Build and drop above.'}[v.fix] || '';
    el.className = 'gd-chip ' + v.level;
    el.innerHTML = '<span class="gd-dot">' + label + '</span><p>' + esc(v.text) + (act ? ' ' + esc(act) : '') + '</p>' +
      (v.fix === 'format:vertical' ? '<button type="button" class="btn btn-primary btn-sm" data-act="studio-mk-chipfix">Use 9:16</button>' : '<span></span>');
    el.hidden = false;
  }, 300);
}

/* THE MAKE PAGE IS A PAGE. It used to be a dialog over the Clips tab -- centred, narrow, closed by
   clicking the dark around it -- which is a poor place to choose a style, a song, forty effects and
   where every kill lands. While it is open the rest of the Studio steps aside, and it scrolls with
   the app like any other page. */
function studio_makePage(on) {
  const v = document.getElementById('view-studio');
  if (v) v.classList.toggle('is-making', !!on);
  const sc = document.getElementById('views');
  if (on && sc) sc.scrollTop = 0;
}

function studio_mkJump(sec) {
  const el = document.getElementById('mk-sec-' + sec);
  if (!el) return;
  el.scrollIntoView({behavior: 'smooth', block: 'start'});
  studio_mkNavMark(sec);
}

function studio_mkNavMark(sec) {
  document.querySelectorAll('#studio-mk-nav .mk-nav-b').forEach(b =>
    b.classList.toggle('is-on', b.getAttribute('data-sec') === sec));
}

/* The section nearest the top is the one the nav says you are in. */
function studio_mkSpy() {
  const sc = document.getElementById('views');
  if (!sc || document.getElementById('studio-make-scrim').classList.contains('hide')) return;
  let best = 'style', gap = 1e9;
  ['style', 'look', 'song', 'kills', 'shape'].forEach(sec => {
    const el = document.getElementById('mk-sec-' + sec);
    if (!el) return;
    const d = Math.abs(el.getBoundingClientRect().top - 140);
    if (d < gap && el.getBoundingClientRect().top < 260) { gap = d; best = sec; }
  });
  studio_mkNavMark(best);
}

/* STYLES ARE SHOWN, NOT DESCRIBED. Each card plays fifteen seconds of that style cut from the same
   kills as every other card; the statistics it used to carry are one click away, folded.

   THE SHIPPED ONE UNTIL THE PLAYER'S OWN. Every card used to open as "Not shown yet" until somebody
   pressed a button and waited minutes while eleven samples were cut. A set cut from the same VALORANT
   clips ships with the app, so a card plays from the moment the page opens; one cut from the player's
   own kills replaces it when they ask for that. */
function studio_sampleUrl(style) {
  const sm = studio.samples;
  const base = '/api/studio/sample?k=' + encodeURIComponent(SHELL_K) + '&style=' + encodeURIComponent(style);
  if (sm.ready && sm.ready[style]) return base + '&key=' + encodeURIComponent(sm.key);
  const st = studio.catalog && studio.catalog.styles.find(s => s.key === style);
  return st && st.stock_sample ? base + '&key=stock' : '';
}

function studio_sampleOwn(style) {
  const sm = studio.samples;
  return !!(sm.ready && sm.ready[style]);
}

/* Play the cards on screen, pause the rest: eleven loops decoding off screen is waste. */
function studio_stylesWatch() {
  if (studio.styleObs) studio.styleObs.disconnect();
  const vids = document.querySelectorAll('#studio-styles video');
  if (!('IntersectionObserver' in window)) {
    vids.forEach(v => { const q = v.play(); if (q && q.catch) q.catch(() => {}); });
    return;
  }
  studio.styleObs = new IntersectionObserver(es => es.forEach(e => {
    const v = e.target;
    if (e.isIntersecting) { const q = v.play(); if (q && q.catch) q.catch(() => {}); }
    else v.pause();
  }), {rootMargin: '100px'});
  vids.forEach(v => studio.styleObs.observe(v));
}

function studio_renderStyles() {
  const cat = studio.catalog;
  if (!cat) return;
  const sm = studio.samples;
  studio_el('studio-styles').innerHTML = cat.styles.map(s => {
    const m = s.measured || {};
    const on = s.key === studio.style;
    const url = studio_sampleUrl(s.key);
    const cutting = sm.running && sm.state && sm.state.style === s.key;
    const failed = sm.state && sm.state.failed && sm.state.failed[s.key];
    return '<div class="studio-style-card' + (on ? ' is-on' : '') + '" data-style="' + esc(s.key) + '">' +
      '<div class="studio-style-media">' +
      (url ? '<video muted loop playsinline autoplay preload="auto" src="' + esc(url) + '" aria-label="' + esc(s.label) +
             (studio_sampleOwn(s.key) ? ' on your kills' : ' on sample kills') + '"></video>' +
             (studio_sampleOwn(s.key) ? '<span class="studio-style-own">Your kills</span>' : '') +
             (cutting ? '<span class="studio-style-own">Cutting on your kills&hellip;</span>' : '')
           : '<span class="studio-style-none">' + (cutting ? 'Cutting this one now&hellip;' : failed ? 'Could not be cut.' : 'Not shown yet') + '</span>') +
      '</div>' +
      '<button type="button" class="studio-style" role="radio" aria-checked="' + on + '" data-act="studio-style" data-style="' + esc(s.key) + '">' +
      '<span class="studio-style-name">' + esc(s.label) + (s.fast_cuts ? ' <span class="studio-style-tag">fast cuts</span>' : '') + '</span>' +
      '<span class="studio-style-blurb">' + esc(s.blurb) + '</span></button>' +
      (m.edits ? '<details class="studio-style-more"><summary>Measured on ' + m.edits + (m.edits === 1 ? ' edit' : ' edits') + '</summary>' +
        '<span class="mono">' + m.cuts_per_min + ' cuts/min · ' + m.flashes_per_min + ' flashes/min · first shot ' + m.first_shot + ' s</span></details>' : '') +
      '</div>';
  }).join('');
  const have = Object.keys(sm.ready || {}).length;
  const cnt = studio_el('studio-style-count');
  if (cnt) cnt.textContent = cat.styles.length + ' styles' + (have ? ' · ' + have + ' shown on your kills' : '');
  const st = cat.styles.find(s => s.key === studio.style);
  studio_el('studio-name').placeholder = (st ? st.label : 'My') + ' reel';
  studio_samplesBar();
  studio_stylesWatch();
  studio_fillDraw();                       /* its note names the style */
}

/* ----- the samples: ask what is already cut, cut the rest in the background, watch it ----- */

function studio_samplesBody() {
  const b = {clips: studio_ordered().map(c => c.path), format: studio.fmt, song: studio.song || ''};
  if (studio_mkHasPart()) { b.part_start = studio.mk.start; b.part_end = studio.mk.end; }
  return b;
}

function studio_samplesBar() {
  const sm = studio.samples, st = studio.catalog ? studio.catalog.styles.length : 0;
  const have = Object.keys(sm.ready || {}).length;
  const btn = studio_el('studio-samples-btn'), stop = studio_el('studio-samples-stop'), msg = studio_el('studio-samples-msg');
  if (!btn) return;
  btn.disabled = sm.running || !studio.selected.length;
  btn.textContent = have >= st && st ? 'Cut them again on my kills' : have ? 'Show the rest on my own kills' : 'Show them on my own kills';
  stop.classList.toggle('hide', !sm.running);
  msg.textContent = sm.running && sm.state ? (sm.state.message || 'Cutting...')
    : sm.held ? sm.held
    : have ? have + ' of ' + st + ' shown on your own kills. The same clips in each one, so the difference is the style.'
    : 'Every style plays the same 15 s of kills, so you compare the look and not the footage. Optional: cut them on your own clips (a few minutes).';
}

async function studio_samplesCheck() {
  if (!studio.selected.length) return;
  const r = await API.post('/api/studio/samples/check', studio_samplesBody());
  if (!r || !r.ok) return;
  const sm = studio.samples;
  if (sm.key !== r.key) sm.state = null;
  sm.key = r.key; sm.ready = r.ready || {}; sm.running = !!r.running; sm.held = '';
  studio_renderStyles();
  if (sm.running) studio_samplesPoll();
}

async function studio_samplesStart() {
  const sm = studio.samples;
  sm.held = '';
  const r = await API.post('/api/studio/samples/start', studio_samplesBody());
  if (!r || !r.ok) { sm.held = (r && (r.held || r.error)) || 'Could not start.'; studio_samplesBar(); return; }
  sm.state = r.state; sm.key = r.state.key || sm.key; sm.ready = r.state.ready || sm.ready;
  sm.running = r.state.state === 'running';
  studio_renderStyles();
  if (sm.running) studio_samplesPoll();
}

function studio_samplesPoll() {
  const sm = studio.samples;
  clearTimeout(sm.timer);
  sm.timer = setTimeout(async () => {
    const r = await API.get('/api/studio/samples/status');
    if (!r || !r.ok) return;
    const was = Object.keys(sm.ready || {}).length;
    sm.state = r.state;
    if (r.state.key === sm.key) sm.ready = r.state.ready || sm.ready;
    sm.running = r.state.state === 'running';
    if (Object.keys(sm.ready || {}).length !== was || !sm.running) studio_renderStyles(); else studio_samplesBar();
    if (sm.running) studio_samplesPoll();
  }, 2000);
}

async function studio_samplesStop() {
  await API.post('/api/studio/samples/cancel', {});
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
  /* A drop belongs to the song it was marked on; another song starts from the drops found in it. */
  if (studio.song !== path) { studio.mk.drops = null; studio.mk.sel = {}; }
  studio.song = path; studio.songShape = got.song;
  studio_el('studio-song-name').textContent = name + ' · ' +
    Math.round(got.song.bpm) + ' BPM · ' + studio_dur(got.song.seconds) +
    (got.song.drop ? ' · drop at ' + studio_secs(got.song.drop) : '');
  studio.mk.touched = false;
  studio_mkStale();
  studio_mkDefault();
  studio_samplesCheck();
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
    let from = sh.drums_in || (sh.beats && sh.beats[0]) || 0;
    /* BUILD AND DROP NEEDS ITS DROP INSIDE THE PART, with the build before it. From where the
       drums come in, Lalala's 30 s part left 2 s before its first drop: the take could not fit,
       so it went to the second drop 18 s in, and the reel was the 15 s that were left. */
    const guided = !studio_el('studio-guide-scrim').classList.contains('hide');
    const drop = (guided ? studio.gd.style : studio.style) === 'drop' ? studio_mkMainDrop() : null;
    if (drop != null) from = Math.max(0, drop - Math.min(16, want / 2));
    mk.start = studio_nearestBeat(sh, Math.max(0, Math.min(from, sh.seconds - bar)));
    mk.end = Math.min(sh.seconds, mk.start + bars * bar);
  }
  studio_el('studio-mk-drop').disabled = studio_mkMainDrop() == null;
  studio_mkDraw();
}

/* THE BEATS AUTOSTREAM FOUND, drawn on a whole-song canvas.

   These decide everything the page then does -- dragging the part snaps to
   them, the clips cut on them, the bar count comes off them -- and they were
   drawn nowhere a person could see them. Only the zoomed detail view had a
   grid, so the song you pick the part on showed a waveform, a drop, and no
   reason for the selection to keep jumping as you dragged it.

   THINNED TO WHAT CAN BE SEEN. A three-minute track at 120 BPM is 360 beats;
   across 900 px that is one every 2.5 px, which is not a grid but a grey
   wash that hides the waveform underneath. So beats are drawn only while
   they are far enough apart to read, bars take over when they are not, and
   when even bars crowd, every Nth bar is drawn instead. The line always
   means the same thing -- a stronger one is a bar -- so a glance at the
   spacing is a glance at the tempo. */
function studio_beatGrid(ctx, X, H, sh, opts) {
  const o = opts || {};
  const beats = (sh && sh.beats) || [];
  if (beats.length < 2) return;
  const per = Math.max(1, X(beats[1]) - X(beats[0]));   /* px between beats */
  const down = sh.downbeat_pos || 0;
  let every = 1;                                        /* draw every Nth beat */
  if (per < 4) every = 4;                               /* bars only */
  if (per * 4 < 10) every = 4 * Math.ceil(10 / (per * 4));
  const css = getComputedStyle(document.documentElement);
  const faint = css.getPropertyValue('--border-subtle').trim() || '#3a3a3a';
  const strong = css.getPropertyValue('--text-tertiary').trim() || '#8a8a8a';
  const top = o.top || 0, h = o.height || H;
  ctx.save();
  for (let i = 0; i < beats.length; i += every) {
    const bar = (i % 4) === down;
    if (every > 1 && !bar) continue;
    const x = X(beats[i]);
    if (x < -2 || x > (o.width || 1e9) + 2) continue;
    ctx.fillStyle = bar ? strong : faint;
    ctx.globalAlpha = (bar ? 0.75 : 0.3) * (o.alpha === undefined ? 1 : o.alpha);
    ctx.fillRect(x, bar ? top : top + h * 0.6, bar ? 1.5 : 1, bar ? h : h * 0.4);
  }
  /* Where the drums come in: the moment most people actually want the part to
     start, and the one fact the facts line names that had no mark. */
  if (sh.drums_in) {
    ctx.globalAlpha = 1;
    ctx.fillStyle = css.getPropertyValue('--ok').trim() || '#3fb950';
    ctx.fillRect(X(sh.drums_in) - 1, top, 2, h);
  }
  ctx.restore();
}

/* What the dialog's player plays: the chosen part, or the whole song while
   AutoStream is choosing. Letting it choose used to hide the player with the
   part controls, so the song could not be heard at all. */
function studio_mkSpan() {
  const sh = studio.songShape, mk = studio.mk;
  if (mk.mode === 'part' || !sh) return {start: mk.start, end: mk.end};
  return {start: 0, end: sh.seconds};
}

/* Whether the Make dialog will send a part: the same test studio_build makes. */
function studio_mkHasPart() {
  const mk = studio.mk;
  return !!(studio.song && studio.songShape && mk.mode === 'part' && mk.end > mk.start);
}

/* The How long that will run: what was chosen, or what nothing chosen means. */
function studio_fillNow() {
  const f = studio.fill;
  if (f === 'part' && !studio_mkHasPart()) return 'style';
  return f || (studio_mkHasPart() ? 'part' : 'style');
}

function studio_fillDraw() {
  const now = studio_fillNow(), part = studio_mkHasPart();
  document.querySelectorAll('#studio-fill [data-act="studio-fill"]').forEach(x => {
    const on = x.getAttribute('data-fill') === now;
    x.classList.toggle('is-active', on);
    x.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  const pb = studio_el('studio-fill-part');
  if (pb) {
    pb.disabled = !part;
    pb.title = part ? '' : 'Choose a song and a part of it first.';
  }
  const st = studio.catalog && studio.catalog.styles.find(s => s.key === studio.style);
  const name = st ? st.label : 'The style';
  const len = studio.mk.end - studio.mk.start;
  const note = studio_el('studio-fill-note');
  if (note) {
    note.textContent = now === 'part'
      ? 'The kills are spread over the ' + studio_dur(len) + ' part, each on a hit. ' + name +
        ' still sets the pace, effects and flashes; with fewer kills than the part needs at that pace, the cuts come slower.'
      : now === 'all'
        ? 'Every clip you chose goes in, at ' + name + "'s pace, however long that runs" +
          (part ? ' — from the start of the part, past its end if it needs to.' : '.')
        : name + ' decides the length, as it always has' +
          (part ? ', starting at the part you picked and never past its end.' : '.') +
          ' Clips that do not fit are left out, and the reel says which.';
  }
  const ka = studio_el('studio-keep-all');
  if (ka) ka.checked = !!studio.keepAll;
}

function studio_mkDraw() {
  const sh = studio.songShape, mk = studio.mk;
  const choosing = mk.mode === 'part';
  studio_fillDraw();
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
      '. How long, below, decides whether the reel fills it.';
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
  ctx.globalAlpha = 1;
  /* Under the selection, so dragging reads as landing ON something. */
  studio_beatGrid(ctx, X, H, sh, {width: W});
  if (choosing) {
    ctx.fillStyle = accent;
    ctx.globalAlpha = 0.18;
    ctx.fillRect(X(mk.start), 0, X(mk.end) - X(mk.start), H);
    ctx.globalAlpha = 1;
    ctx.fillRect(X(mk.start) - 2, 0, 4, H); ctx.fillRect(X(mk.end) - 2, 0, 4, H);
  }
  ctx.globalAlpha = 1;
  ctx.fillStyle = warn;
  studio_mkDropList().forEach(d => ctx.fillRect(X(d.t) - 1, 0, 2, H));
  const a = studio_el('studio-mk-audio');
  if (a && a.getAttribute('data-song') === studio.song && (!a.paused || a.currentTime > 0)) {
    ctx.fillStyle = '#ff5c5c'; ctx.fillRect(X(a.currentTime) - 1, 0, 2, H);
  }
  studio_mkClock();
  studio_mkKillsDraw();
}

/* ===== M4: THE KILLS, ON THE PAGE ===================================================================== */

/* EVERY MARK IS AN OBJECT WITH AN ID: {id, t, auto, name}. `auto` is "AutoStream put it there", so
   the page can draw AutoStream's kills and the player's in different colours once both are on the
   song -- they used to become one colour the moment one was touched, and nobody could tell which of
   fifty they had placed. The id is what a selection holds, so selecting survives a sort. */

/* The kills as they stand: the player's own once they have touched one, else where the plan put them. */
function studio_mkKillList() {
  const mk = studio.mk;
  if (mk.edited) return mk.hand.map(k => ({id: k.id, t: k.t, hand: !k.auto, name: k.name || ''}));
  if (mk.planned) return mk.planned.marks.map((t, i) => ({id: 'p' + i, t: t, hand: false, name: mk.planned.names[i] || ''}));
  return [];
}

/* A first touch makes the plan the player's: every kill becomes a mark they can move, so moving one does
   not discard the rest. The ones they did not touch stay AutoStream's, and are drawn as such. */
function studio_mkOwn() {
  const mk = studio.mk;
  if (mk.edited) return;
  mk.hand = mk.planned ? mk.planned.marks.map((t, i) => ({id: 'p' + i, t: t, auto: true, name: mk.planned.names[i] || ''})) : [];
  mk.edited = true;
}

/* THE DROPS, AS MARKS. The main bass drops the song analysis found used to be one thin line, and only
   the biggest of them; they are now marks on the song like the kills, every one found, and the player
   can move them, add their own and take AutoStream's away. `mk.drops` is null while they are
   AutoStream's -- and only then is nothing sent, so the planner keeps reading the song itself. */
function studio_mkDropList() {
  const sh = studio.songShape, mk = studio.mk;
  if (mk.drops) return mk.drops.map(d => ({id: d.id, t: d.t, hand: !d.auto}));
  if (!sh) return [];
  const found = (sh.drops && sh.drops.length) ? sh.drops : (sh.drop ? [sh.drop] : []);
  return found.map((t, i) => ({id: 'a' + i, t: t, hand: false}));
}

function studio_mkOwnDrops() {
  const mk = studio.mk;
  if (mk.drops) return;
  mk.drops = studio_mkDropList().map(d => ({id: d.id, t: d.t, auto: true}));
}

/* THE drop: the analysis's own, or -- once the player has marked theirs -- the one of theirs nearest it,
   the same choice the server makes with the list. */
function studio_mkMainDrop() {
  const sh = studio.songShape, mk = studio.mk;
  if (!mk.drops) return sh && sh.drop ? sh.drop : null;
  if (!mk.drops.length) return null;
  const ref = sh && sh.drop;
  return ref ? mk.drops.reduce((b, d) => Math.abs(d.t - ref) < Math.abs(b - ref) ? d.t : b, mk.drops[0].t) : mk.drops[0].t;
}

function studio_mkKillSpan() {
  const sh = studio.songShape;
  if (!sh) return {start: 0, end: 1};
  const sp = studio_mkSpan();
  return {start: sp.start, end: Math.max(sp.end, sp.start + 1)};
}

/* EXACT, UNLESS ASKED. A mark is where the player pressed K or let go of it, to the millisecond: it used
   to be pulled to the nearest beat, so a kill marked on an off-beat hit landed somewhere they had not
   put it. Snapping is a choice on the page now, off until it is ticked. */
function studio_mkSnap(t) {
  const box = studio_el('studio-mk-snap');
  return box && box.checked ? studio_nearestBeat(studio.songShape, t) : Math.round(t * 1000) / 1000;
}

function studio_mkSelCount() {
  return Object.keys(studio.mk.sel || {}).length;
}

/* Where the lanes sit on the canvas: drops along the top, kills through the middle. */
const MK_DROP_LANE = 26;
const MK_KILLS_H = 140;

function studio_mkKillsDraw() {
  const box = studio_el('studio-mk-killsbox');
  if (!box) return;
  const sh = studio.songShape, mk = studio.mk;
  box.classList.toggle('hide', !sh);
  const note = studio_el('studio-mk-killnote');
  if (!sh) {
    if (note) note.textContent = '';
    return;
  }
  mk.sel = mk.sel || {};
  const list = studio_mkKillList(), drops = studio_mkDropList();
  const mine = list.filter(k => k.hand).length;
  if (note) {
    note.textContent = mk.edited
      ? list.length + ' kill(s): ' + mine + ' placed by you, ' + (list.length - mine) + ' by AutoStream. Build puts every shot around them; "Back to automatic" lets AutoStream choose again.'
      : mk.planned
        ? 'Where the plan puts ' + list.length + ' kills on the song. Drag one, press K at the playhead, or double-click the song to place your own.'
        : 'AutoStream puts each kill on a hit of the song. Press "Show where the kills will land" to see them here, then move any you like.';
  }
  const c = studio_sgCanvas('studio-mk-kills', MK_KILLS_H);
  if (!c || !sh.peaks) return;
  const {ctx, W, H} = c, span = studio_mkKillSpan(), len = span.end - span.start;
  const X = t => (t - span.start) / len * W, top = MK_DROP_LANE, mid = top + (H - top - 14) / 2;
  const css = getComputedStyle(document.documentElement);
  const tok = (n, d) => css.getPropertyValue(n).trim() || d;
  const accent = tok('--accent', '#5aa9ff'), auto = tok('--ok', '#4fc97a'), warn = tok('--warn', '#e3b341');
  const faint = tok('--text-tertiary', '#8a8a8a'), text = tok('--text-primary', '#fff'), surface = tok('--surface', '#111');
  const n = sh.peaks.length;
  ctx.fillStyle = faint;
  ctx.globalAlpha = 0.45;
  for (let x = 0; x < W; x++) {
    const t = span.start + x / W * len;
    const amp = (sh.peaks[Math.min(n - 1, Math.max(0, Math.floor(t / sh.seconds * n)))] || 0) * (mid - top - 4);
    ctx.fillRect(x, mid - amp, 1, amp * 2 || 1);
  }
  ctx.globalAlpha = 1;
  studio_beatGrid(ctx, X, H - 14, sh, {width: W, alpha: 0.9, top: top, height: H - 14 - top});
  /* Where kills CAN land: the song's own hits, as small ticks under the waveform. */
  ctx.fillStyle = faint;
  ctx.globalAlpha = 0.7;
  (sh.hits || []).forEach(t => { if (t >= span.start && t <= span.end) ctx.fillRect(X(t) - 0.5, H - 12, 1, 8); });
  ctx.globalAlpha = 1;
  /* The drop lane. */
  ctx.fillStyle = tok('--surface-sunken', '#080b10');
  ctx.fillRect(0, 0, W, top - 2);
  const md = mk.markDrag, dt = md && md.moved ? md.dt : 0;
  const at = (id, t) => (md && md.moved && md.ids[id]) ? t + dt : t;
  drops.forEach(d => {
    const t = at(d.id, d.t);
    if (t < span.start - 0.01 || t > span.end + 0.01) return;
    const x = X(t), on = !!mk.sel[d.id];
    ctx.globalAlpha = 0.55;
    ctx.fillStyle = warn;
    ctx.fillRect(x - 0.75, top, 1.5, H - 14 - top);
    ctx.globalAlpha = 1;
    ctx.beginPath();
    ctx.moveTo(x - 8, 5); ctx.lineTo(x + 8, 5); ctx.lineTo(x, 20); ctx.closePath();
    if (d.hand) { ctx.fillStyle = warn; ctx.fill(); }
    else { ctx.fillStyle = surface; ctx.fill(); ctx.strokeStyle = warn; ctx.lineWidth = 1.5; ctx.stroke(); }
    if (on) { ctx.strokeStyle = text; ctx.lineWidth = 2; ctx.stroke(); }
    ctx.fillStyle = warn; ctx.font = '10px monospace';
    ctx.fillText('drop', x + 10, 15);
  });
  /* The kills: AutoStream's are hollow and green, the player's solid in the accent, a selected one ringed. */
  list.forEach((k, i) => {
    const t = at(k.id, k.t);
    if (t < span.start - 0.01 || t > span.end + 0.01) return;
    const x = X(t), y = mid, on = !!mk.sel[k.id], col = k.hand ? accent : auto;
    ctx.beginPath();
    ctx.moveTo(x, y - 8); ctx.lineTo(x + 8, y); ctx.lineTo(x, y + 8); ctx.lineTo(x - 8, y); ctx.closePath();
    if (k.hand) { ctx.fillStyle = col; ctx.fill(); }
    else { ctx.fillStyle = surface; ctx.fill(); ctx.strokeStyle = col; ctx.lineWidth = 1.75; ctx.stroke(); }
    if (on) {
      ctx.beginPath(); ctx.arc(x, y, 12, 0, Math.PI * 2);
      ctx.strokeStyle = text; ctx.lineWidth = 2; ctx.stroke();
    }
    ctx.fillStyle = col;
    ctx.font = '10px monospace';
    ctx.fillText(String(i + 1), x - 3, y - 13);
  });
  /* A box being dragged out to select. */
  const bs = mk.boxSel;
  if (bs) {
    ctx.fillStyle = accent; ctx.globalAlpha = 0.15;
    ctx.fillRect(Math.min(X(bs.t0), X(bs.t1)), 0, Math.abs(X(bs.t1) - X(bs.t0)), H);
    ctx.globalAlpha = 1;
  }
  const a = studio_el('studio-mk-audio');
  if (a && a.getAttribute('data-song') === studio.song && (!a.paused || a.currentTime > 0)) {
    ctx.fillStyle = '#ff5c5c'; ctx.fillRect(X(a.currentTime) - 1, 0, 2, H);
  }
  studio_mkListDraw(list, drops);
}

/* The lists under the song: what lands where, whose each one is, and a box to pick several.
   Rebuilt only when something in them changed -- the playhead redraws the canvas sixty times a
   second, and a list rebuilt that often eats the click that was meant for one of its boxes. */
function studio_mkListDraw(list, drops) {
  const mk = studio.mk;
  const sig = JSON.stringify([list, drops, mk.sel]);
  if (sig !== mk.listSig) {
    mk.listSig = sig;
    const row = (k, i, what) => {
      const name = (what === 'drop' ? 'drop ' : 'kill ') + (i + 1);
      return '<li class="studio-mk-markrow' + (k.hand ? ' is-hand' : ' is-auto') + (mk.sel[k.id] ? ' is-sel' : '') + (what === 'drop' ? ' is-drop' : '') + '">' +
        '<label class="studio-mk-markpick"><input type="checkbox" data-act="studio-mk-pick" data-id="' + esc(k.id) + '"' + (mk.sel[k.id] ? ' checked' : '') +
        ' aria-label="Select ' + name + '"><span class="mono">' + (what === 'drop' ? 'D' : '') + (i + 1) + '</span></label>' +
        '<span class="mono">' + esc(studio_secs(k.t)) + '</span>' +
        '<span class="studio-mk-who">' + (k.hand ? 'yours' : 'auto') + '</span>' +
        '<span class="muted studio-mk-markname">' + esc(k.name || '') + '</span>' +
        '<span class="studio-mk-marktools">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-nudgemark" data-id="' + esc(k.id) + '" data-d="-1" aria-label="Move ' + name + ' a tenth of a second earlier">&minus;0.1</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-nudgemark" data-id="' + esc(k.id) + '" data-d="1" aria-label="Move ' + name + ' a tenth of a second later">+0.1</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-mk-delmark" data-id="' + esc(k.id) + '" aria-label="Remove ' + name + '">&times;</button>' +
        '</span></li>';
    };
    const dl = studio_el('studio-mk-droplist');
    if (dl) dl.innerHTML = drops.map((d, i) => row(d, i, 'drop')).join('');
    const ol = studio_el('studio-mk-marklist');
    if (ol) ol.innerHTML = list.map((k, i) => row(k, i, 'kill')).join('');
  }
  const n = studio_mkSelCount();
  const del = studio_el('studio-mk-delsel');
  if (del) { del.disabled = !n; del.textContent = n ? 'Delete ' + n + ' selected' : 'Delete selected'; }
  const none = studio_el('studio-mk-selnone');
  if (none) none.disabled = !n;
  const all = studio_el('studio-mk-selall');
  if (all) all.disabled = !(list.length + drops.length);
  const clear = studio_el('studio-mk-clearmarks');
  if (clear) clear.disabled = !mk.edited;
  const dclear = studio_el('studio-mk-cleardrops');
  if (dclear) dclear.disabled = !mk.drops;
}

/* Which kind an id is: kills are p# (planned) or h# (placed), drops a# (found) or u# (placed). */
function studio_mkIsDrop(id) { return /^[au]/.test(String(id)); }

/* Where the playhead is, or the start of the part before anything has played. */
function studio_mkHead() {
  const a = studio_el('studio-mk-audio');
  return a && a.getAttribute('data-song') === studio.song && a.readyState >= 1 ? a.currentTime : studio_mkSpan().start;
}

function studio_mkAddMark(at) {
  const sh = studio.songShape;
  if (!sh) { toast('Choose a song first.', 'warn'); return; }
  const t = at !== undefined ? at : studio_mkHead();
  const sp = studio_mkKillSpan();
  if (t < sp.start - 0.01 || t > sp.end + 0.01) { toast('That is outside the part you chose.', 'warn'); return; }
  const mk = studio.mk;
  studio_mkOwn();
  mk.nid = (mk.nid || 0) + 1;
  mk.hand.push({id: 'h' + mk.nid, t: studio_mkSnap(t), auto: false, name: ''});
  mk.hand.sort((x, y) => x.t - y.t);
  studio_mkKillsDraw();
}

/* A DROP MARKED BY THE PLAYER: where the bass comes in, as they hear it. Build and drop builds into
   it, and the drop flash goes on the kill that lands on it. */
function studio_mkAddDrop(at) {
  const sh = studio.songShape;
  if (!sh) { toast('Choose a song first.', 'warn'); return; }
  const t = at !== undefined ? at : studio_mkHead();
  const sp = studio_mkKillSpan();
  if (t < sp.start - 0.01 || t > sp.end + 0.01) { toast('That is outside the part you chose.', 'warn'); return; }
  const mk = studio.mk;
  studio_mkOwnDrops();
  mk.nid = (mk.nid || 0) + 1;
  mk.drops.push({id: 'u' + mk.nid, t: studio_mkSnap(t), auto: false});
  mk.drops.sort((x, y) => x.t - y.t);
  studio_mkDropsChanged();
}

function studio_mkDropsChanged() {
  if (studio.mk.planned) studio_el('studio-mk-killmsg').textContent = 'The drops changed: "Show where the kills will land" plans again around them.';
  studio_mkDraw();
}

/* Remove marks by id, kills and drops alike -- one, or everything selected. */
function studio_mkDelIds(ids) {
  const mk = studio.mk, kill = ids.filter(id => !studio_mkIsDrop(id)), drop = ids.filter(studio_mkIsDrop);
  if (kill.length) {
    studio_mkOwn();
    mk.hand = mk.hand.filter(k => kill.indexOf(k.id) < 0);
  }
  if (drop.length) {
    studio_mkOwnDrops();
    mk.drops = mk.drops.filter(d => drop.indexOf(d.id) < 0);
  }
  ids.forEach(id => { delete mk.sel[id]; });
  if (drop.length) studio_mkDropsChanged(); else studio_mkKillsDraw();
}

function studio_mkDelMark(id) { studio_mkDelIds([id]); }

function studio_mkDelSelected() {
  const ids = Object.keys(studio.mk.sel || {});
  if (!ids.length) return;
  studio_mkDelIds(ids);
  studio_el('studio-mk-killmsg').textContent = ids.length + (ids.length === 1 ? ' mark' : ' marks') + ' removed.';
}

function studio_mkPick(id, on) {
  const mk = studio.mk;
  mk.sel = mk.sel || {};
  if (on) mk.sel[id] = true; else delete mk.sel[id];
  studio_mkKillsDraw();
}

function studio_mkSelAll(on) {
  const mk = studio.mk;
  mk.sel = {};
  if (on) studio_mkKillList().concat(studio_mkDropList()).forEach(k => { mk.sel[k.id] = true; });
  studio_mkKillsDraw();
}

function studio_mkNudgeMark(id, d) {
  const mk = studio.mk, drop = studio_mkIsDrop(id);
  if (drop) studio_mkOwnDrops(); else studio_mkOwn();
  const m = (drop ? mk.drops : mk.hand).find(x => x.id === id);
  if (!m) return;
  m.t = Math.max(0, Math.round((m.t + d * 0.1) * 1000) / 1000);
  m.auto = false;
  (drop ? mk.drops : mk.hand).sort((x, y) => x.t - y.t);
  if (drop) studio_mkDropsChanged(); else studio_mkKillsDraw();
}

function studio_mkClearMarks() {
  const mk = studio.mk;
  mk.hand = []; mk.edited = false;
  Object.keys(mk.sel || {}).forEach(id => { if (!studio_mkIsDrop(id)) delete mk.sel[id]; });
  studio_mkKillsDraw();
}

function studio_mkClearDrops() {
  const mk = studio.mk;
  mk.drops = null;
  Object.keys(mk.sel || {}).forEach(id => { if (studio_mkIsDrop(id)) delete mk.sel[id]; });
  studio_mkDropsChanged();
}

/* A style, a part, a song or the clips changed: where a plan PLACED the kills no longer holds. Marks the
   player placed are theirs and stay -- they are about the song, not the plan -- and the page says so. */
function studio_mkStale() {
  const mk = studio.mk;
  studio_mkChip();
  if (!mk.planned) return;
  mk.planned = null;
  studio_el('studio-mk-killmsg').textContent = mk.edited ? 'Your marks are kept.' : '';
  studio_mkKillsDraw();
}

async function studio_mkPlan() {
  if (!studio.selected.length || !studio.song) { toast('Choose a song first: kills land on its hits.', 'warn'); return; }
  const btn = studio_el('studio-mk-plan'), msg = studio_el('studio-mk-killmsg');
  btn.disabled = true;
  msg.textContent = 'Planning the reel to find where each kill lands... this is the plan Build would make' +
    (studio.arrange === 'fit' ? ', and a perfect fit takes up to ~30 s.' : '.');
  try {
    const r = await API.post('/api/studio/plan', studio_planBody(false));
    if (!r || !r.ok) { msg.textContent = (r && r.error) || 'Could not plan that reel.'; return; }
    const p = r.project, marks = (p.song_marks || []).slice();
    const names = (p.shots || []).map(x => (x.caption || x.name || '').replace(/\.mp4$/i, ''));
    studio.mk.planned = {marks: marks, names: names};
    msg.textContent = marks.length + ' kills placed on the song.';
  } finally {
    btn.disabled = false;
    studio_mkKillsDraw();
  }
}

/* THE CANVAS. Click a mark to select it (Ctrl or Shift adds to the selection), drag to move it -- and
   everything selected with it -- Shift-drag the empty song to box-select, click the empty song to hear
   it from there, double-click to add or remove. The top lane is the drops, the rest the kills. */
function studio_mkKillPointer(e) {
  const cv = studio_el('studio-mk-kills'), mk = studio.mk;
  if (!cv || !studio.songShape) return;
  mk.sel = mk.sel || {};
  const r = cv.getBoundingClientRect(), span = studio_mkKillSpan(), len = span.end - span.start;
  const x = Math.max(0, Math.min(r.width, e.clientX - r.left)), y = e.clientY - r.top;
  const t = span.start + x / r.width * len;
  const inDrops = y < MK_DROP_LANE * r.height / MK_KILLS_H;
  const pool = inDrops ? studio_mkDropList() : studio_mkKillList();
  let near = -1, gap = 11;
  pool.forEach((k, i) => { const d = Math.abs((k.t - span.start) / len * r.width - x); if (d < gap) { gap = d; near = i; } });
  const hit = near >= 0 ? pool[near] : null;
  if (e.type === 'pointerdown') {
    if (e.button !== undefined && e.button !== 0) return;
    if (hit) {
      if (e.ctrlKey || e.metaKey || e.shiftKey) {
        if (mk.sel[hit.id]) delete mk.sel[hit.id]; else mk.sel[hit.id] = true;
        studio_mkKillsDraw();
      } else {
        if (!mk.sel[hit.id]) mk.sel = {[hit.id]: true};
        const ids = {};
        Object.keys(mk.sel).forEach(id => { ids[id] = true; });
        mk.markDrag = {t0: t, dt: 0, ids: ids, moved: false};
        try { cv.setPointerCapture(e.pointerId); } catch (err) { /* a mouse still works */ }
        studio_mkKillsDraw();
      }
    } else if (e.shiftKey) {
      mk.boxSel = {t0: t, t1: t, add: e.ctrlKey || e.metaKey};
      try { cv.setPointerCapture(e.pointerId); } catch (err) { /* a mouse still works */ }
    } else {
      mk.sel = {};
      studio_mkSeek(Math.max(span.start, Math.min(span.end, t)));      /* click the song: hear it from there */
    }
    e.preventDefault();
  } else if (e.type === 'pointermove' && mk.markDrag) {
    const md = mk.markDrag;
    md.dt = t - md.t0;
    md.moved = md.moved || Math.abs(md.dt) * r.width / len > 2;
    studio_mkKillsDraw();
  } else if (e.type === 'pointermove' && mk.boxSel) {
    mk.boxSel.t1 = t;
    studio_mkKillsDraw();
  } else if ((e.type === 'pointerup' || e.type === 'pointercancel') && mk.markDrag) {
    const md = mk.markDrag;
    mk.markDrag = null;
    if (md.moved && e.type === 'pointerup') studio_mkMoveSel(md.ids, md.dt);
    else studio_mkKillsDraw();
  } else if ((e.type === 'pointerup' || e.type === 'pointercancel') && mk.boxSel) {
    const bs = mk.boxSel, lo = Math.min(bs.t0, bs.t1), hi = Math.max(bs.t0, bs.t1);
    mk.boxSel = null;
    if (!bs.add) mk.sel = {};
    studio_mkKillList().concat(studio_mkDropList()).forEach(k => { if (k.t >= lo && k.t <= hi) mk.sel[k.id] = true; });
    studio_mkKillsDraw();
  } else if (e.type === 'dblclick') {
    if (hit) studio_mkDelMark(hit.id);
    else if (inDrops) studio_mkAddDrop(Math.max(span.start, Math.min(span.end, t)));
    else studio_mkAddMark(Math.max(span.start, Math.min(span.end, t)));
  }
}

/* Move every selected mark by the same amount. One that is moved is the player's from then on. */
function studio_mkMoveSel(ids, dt) {
  const mk = studio.mk, span = studio_mkKillSpan();
  const list = Object.keys(ids), kills = list.some(id => !studio_mkIsDrop(id)), drops = list.some(studio_mkIsDrop);
  const one = list.length === 1;
  const move = m => {
    if (!ids[m.id]) return;
    const to = Math.max(span.start, Math.min(span.end, m.t + dt));
    m.t = one ? studio_mkSnap(to) : Math.round(to * 1000) / 1000;
    m.auto = false;
  };
  if (kills) { studio_mkOwn(); mk.hand.forEach(move); mk.hand.sort((x, y) => x.t - y.t); }
  if (drops) { studio_mkOwnDrops(); mk.drops.forEach(move); mk.drops.sort((x, y) => x.t - y.t); }
  if (drops) studio_mkDropsChanged(); else studio_mkKillsDraw();
}

/* A SOUND AS THE PLAYHEAD PASSES A MARK, so a kill placed by eye can be checked by ear: a short tick
   for a kill, a low thump for a drop. Crossings, not proximity -- a frame that skips past a mark
   still sounds it, and a seek sounds nothing. */
function studio_mkTickSound(kind) {
  try {
    const C = window.AudioContext || window.webkitAudioContext;
    if (!C) return;
    const mk = studio.mk;
    mk.ac = mk.ac || new C();
    const ac = mk.ac, o = ac.createOscillator(), g = ac.createGain(), now = ac.currentTime;
    if (kind === 'drop') {
      o.type = 'sine';
      o.frequency.setValueAtTime(140, now); o.frequency.exponentialRampToValueAtTime(50, now + 0.18);
      g.gain.setValueAtTime(0.5, now); g.gain.exponentialRampToValueAtTime(0.001, now + 0.2);
    } else {
      o.type = 'square';
      o.frequency.value = 1900;
      g.gain.setValueAtTime(0.12, now); g.gain.exponentialRampToValueAtTime(0.001, now + 0.04);
    }
    o.connect(g); g.connect(ac.destination);
    o.start(now);
    o.stop(now + (kind === 'drop' ? 0.21 : 0.05));
  } catch (err) { /* no audio context, no tick */ }
}

function studio_mkTickMarks(a) {
  const mk = studio.mk, now = a.currentTime, last = mk.lastT;
  mk.lastT = now;
  const box = studio_el('studio-mk-tick');
  if (a.paused || last == null || !(box && box.checked)) return;
  const step = now - last;
  if (step <= 0 || step > 0.5) return;                    /* a seek or a loop, not playback */
  const crossed = t => t > last && t <= now;
  if (studio_mkDropList().some(d => crossed(d.t))) studio_mkTickSound('drop');
  else if (studio_mkKillList().some(k => crossed(k.t))) studio_mkTickSound('kill');
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
  } else if (which === 'drop' && studio_mkMainDrop() != null) {
    const drop = studio_mkMainDrop();
    const lead = Math.min(8 * bar, drop, Math.max(bar, len / 3));
    mk.start = Math.max(0, studio_nearestBeat(sh, drop - lead));
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
  mk.lastT = null;                                  /* a seek passes no marks */
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
  if (e.type === 'play') mk.lastT = a.currentTime;
  if (e.type === 'play' && !mk.ticking) { mk.ticking = true; requestAnimationFrame(studio_mkTick); }
  studio_mkDraw();
}

/* Smooth playhead while playing; timeupdate alone moves it four times a second. */
function studio_mkTick() {
  const a = studio_el('studio-mk-audio'), mk = studio.mk;
  if (!a || a.paused || studio_el('studio-make-scrim').classList.contains('hide')) { mk.ticking = false; return; }
  studio_mkTickMarks(a);
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

function studio_binCard(p, on, act, more) {
  const fav = studio.favParts.indexOf(p.id) >= 0;
  return '<button type="button" class="bin-card' + (on ? ' is-on' : '') +
    '" data-act="' + act + '" data-kind="' + esc(p.kind) + '" data-part="' + esc(p.id) + '"' +
    ' aria-pressed="' + (on ? 'true' : 'false') + '">' + studio_binShot(p.id) +
    '<span class="bin-star' + (fav ? ' is-on' : '') + '" role="button" tabindex="0"' +
    ' data-act="studio-bin-fav" data-part="' + esc(p.id) + '"' +
    ' aria-pressed="' + (fav ? 'true' : 'false') + '"' +
    ' title="' + (fav ? 'Remove from favourites' : 'Keep in favourites') + '">' +
    (fav ? '★' : '☆') + '</span>' +
    '<span class="bin-meat"><span class="bin-name">' + esc(more ? studio_leadName(p) : (p.label || p.id)) + '</span>' +
    '<span class="bin-blurb">' + esc(p.blurb || '') + '</span>' + (more || '') + '</span></button>';
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
  {k: 'shuffle', name: 'Shuffle', why: 'A fresh draw. Press again for another.'},
  {k: 'hits', name: 'Best order', why: "Puts your biggest moments - aces, clutches, multi-kills - on the song's " +
    'biggest hits. Quick to plan, and the one to start with.'},
  /* Not an order but a search: every kill of every clip on a beat of the song,
     every clip of three or more kills whole. Up to half a minute to plan. */
  {k: 'fit', name: 'Perfect fit (slower)',
   why: 'Makes EVERY kill land exactly on a beat, even the small ones, by trying many orders. ' +
     'Slower (up to ~30 s), and the order is whatever fits best rather than the best moments first.'}
];

/* THE SAME SIX, IN THE MAKE DIALOG, where the decision is actually taken.
   Drawn as cards rather than a segmented row: an arrangement needs its
   sentence to be choosable -- "Best order" and "Perfect fit" mean nothing as
   two words on a button, which is how they went unnoticed in the strip. */
const ARRANGE_NOTE = {hits: 'recommended', fit: '~30 s to plan'};

function studio_mkArrangeDraw() {
  const host = studio_el('studio-mk-arrange');
  if (!host) return;
  host.innerHTML = ARRANGES.map(function (a) {
    const on = studio.arrange === a.k;
    const note = ARRANGE_NOTE[a.k];
    return '<button type="button" class="studio-mk-arr' + (on ? ' is-on' : '') +
      '" data-act="studio-arrange" data-how="' + a.k + '" aria-pressed="' + on + '">' +
      '<span class="studio-mk-arr-name">' + esc(a.name) +
      (note ? '<span class="studio-mk-arr-note">' + esc(note) + '</span>' : '') + '</span>' +
      '<span class="studio-mk-arr-why">' + esc(a.why) + '</span></button>';
  }).join('');
}

function studio_arrangeDraw() {
  studio_mkArrangeDraw();
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
  toast(how === 'fit' ? 'Make the reel again to see it. A perfect fit takes up to ~30 s to plan.'
                      : 'Make the reel again to see it.');
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
  const open = studio.binOpen || {};
  box.innerHTML = drawers.map(function (kind) {
    const all = studio_parts(kind);
    const ids = studio_pickIds(picks[kind]);
    // Favourites on their own are the versions that were starred; otherwise each effect once.
    const parts = studio.favOnly ? studio_binSort(all) : studio_binSort(studio_leads(kind));
    if (!parts.length) return '';
    const kept = all.filter(function (x) { return studio.favParts.indexOf(x.id) >= 0; }).length;
    const inUse = function (p) {
      return studio_versions(kind, p.group).filter(function (v) { return ids.indexOf(v.id) >= 0; }).length;
    };
    const cards = parts.map(function (p) {
      const n = studio.favOnly ? 0 : inUse(p);
      return studio_binCard(p, ids.indexOf(p.id) >= 0 || n > 0, 'studio-bin-pick',
                            studio.favOnly ? '' : studio_moreChip(p, 'studio-bin-group', n));
    }).join('');
    const g = open[kind];
    const lead = g ? studio_leads(kind).filter(function (p) { return p.group === g; })[0] : null;
    const versions = lead && !studio.favOnly
      ? '<div class="bin-versions" data-kind="' + esc(kind) + '"><div class="bin-sec-head"><h3>' +
        'Every version of ' + esc(studio_leadName(lead)) + '</h3>' +
        '<button type="button" class="btn btn-sm" data-act="studio-bin-group" data-kind="' + esc(kind) +
        '" data-group="">Close</button></div><div class="bin-grid">' +
        studio_versions(kind, g).map(function (p) {
          return studio_binCard(p, ids.indexOf(p.id) >= 0, 'studio-bin-pick');
        }).join('') + '</div></div>'
      : '';
    return '<section class="bin-sec bin-drawer">' +
      '<div class="bin-sec-head"><h2>' + esc(studio_binName(kind)) + '</h2>' +
      '<span class="count">' + parts.length + (studio.favOnly ? ' kept' : ' effects') +
      (!studio.favOnly && all.length > parts.length ? ' · ' + all.length + ' versions in all' : '') +
      (kept && !studio.favOnly ? ' · ' + kept + ' kept' : '') + '</span></div>' +
      '<div class="bin-grid">' + cards + '</div>' + versions + '</section>';
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

/* THE DRAWERS THAT CAN HOLD SEVERAL. A reel draws a kill effect, a transition, a hero
   treatment, a camera move and a speed PER SHOT from a pool, and the Make page used to show
   one pick per drawer -- so it said one thing and the timeline did another. An opening, an
   ending, a colour and an overlay are one per reel and stay one. */
const MAKE_MULTI = ['transition', 'kill', 'hero', 'camera', 'speed'];
const MAKE_WEIGHT_MAX = 4;

/* A drawer's pick as a list of ids: a string is one, an array is a set in which an id
   listed twice is drawn about twice as often. */
function studio_pickIds(v) {
  const raw = Array.isArray(v) ? v : [v];
  return raw.filter(x => typeof x === 'string' && x);
}

function studio_pickUnique(v) {
  return studio_pickIds(v).filter((x, i, a) => a.indexOf(x) === i);
}

function studio_pickWeight(v, id) {
  return studio_pickIds(v).filter(x => x === id).length;
}

/* Write a drawer's set back: ids in order, each repeated by its weight, and a single id
   with weight one stored as the plain string the server always took. */
function studio_makeStore(kind, ids, weights) {
  const flat = [];
  ids.forEach(id => {
    const w = Math.max(1, Math.min(MAKE_WEIGHT_MAX, (weights && weights[id]) || 1));
    for (let i = 0; i < w; i++) flat.push(id);
  });
  studio.picks = Object.assign({}, studio_template());
  studio.picks[kind] = (flat.length === 1) ? flat[0] : flat;
  studio_hand();
  studio_binDraw();
}

function studio_makeWeights(kind) {
  const w = {};
  studio_pickIds(studio_template()[kind]).forEach(id => { w[id] = (w[id] || 0) + 1; });
  return w;
}

function studio_makeSet(kind, ids) {
  const was = studio_makeWeights(kind);
  const keep = {};
  ids.forEach(id => { keep[id] = was[id] || 1; });
  studio_makeStore(kind, ids, keep);
}

function studio_makeWeight(kind, id, d) {
  const w = studio_makeWeights(kind);
  if (!w[id]) return;
  w[id] = Math.max(1, Math.min(MAKE_WEIGHT_MAX, w[id] + d));
  studio_makeStore(kind, studio_pickUnique(studio_template()[kind]), w);
}

function studio_makeRemove(kind, id) {
  const ids = studio_pickUnique(studio_template()[kind]);
  if (ids.length < 2) { toast('Keep at least one.', 'warn'); return; }
  const w = studio_makeWeights(kind);
  studio_makeStore(kind, ids.filter(x => x !== id), w);
}

/* What the drawer will actually draw from, in a sentence: the thing the page used to leave
   the timeline to reveal. */
function studio_makeSummary(kind) {
  const ids = studio_pickUnique(studio_template()[kind]);
  if (!ids.length) return '';
  const label = id => (studio_part(id) || {}).label || id;
  if (ids.length === 1) return 'Every shot: ' + label(ids[0]) + '.';
  const w = studio_makeWeights(kind);
  const total = ids.reduce((n, id) => n + w[id], 0);
  return 'Each shot draws one: ' + ids.map(id => label(id) + ' ' + Math.round(100 * w[id] / total) + '%').join(' · ') + '.';
}

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
    const ids = studio_pickUnique(picks[kind]);
    const p = studio_part(ids[0]) || {id: ids[0] || '-', label: 'Nothing', kind: kind, blurb: ''};
    const multi = MAKE_MULTI.indexOf(kind) >= 0;
    /* THE CARD OPENS A LIST. It used to step to the NEXT part in the drawer, which made a
       drawer of fifty effects something you reached by clicking fifty times. */
    let h = '<div class="bin-slotcard" data-drawer="' + esc(kind) + '"><span class="bin-drawer-label">' +
      esc(studio_binName(kind)) + '</span>' + studio_binCard(p, false, 'studio-hand-pick');
    if (multi) {
      const w = studio_makeWeights(kind);
      h += '<div class="studio-set" data-set="' + esc(kind) + '">' + ids.map(function (id) {
        const part = studio_part(id) || {label: id};
        return '<span class="studio-set-chip"><span class="studio-set-name">' + esc(part.label || id) + '</span>' +
          '<button type="button" class="studio-set-w" data-act="studio-set-weight" data-kind="' + esc(kind) +
          '" data-part="' + esc(id) + '" data-d="-1" aria-label="Less often: ' + esc(part.label || id) + '"' +
          (w[id] <= 1 ? ' disabled' : '') + '>&minus;</button>' +
          '<span class="studio-set-n" title="How often it is drawn, against the others">' + w[id] + '</span>' +
          '<button type="button" class="studio-set-w" data-act="studio-set-weight" data-kind="' + esc(kind) +
          '" data-part="' + esc(id) + '" data-d="1" aria-label="More often: ' + esc(part.label || id) + '"' +
          (w[id] >= MAKE_WEIGHT_MAX ? ' disabled' : '') + '>+</button>' +
          (ids.length > 1 ? '<button type="button" class="studio-set-x" data-act="studio-set-remove" data-kind="' +
            esc(kind) + '" data-part="' + esc(id) + '" aria-label="Remove ' + esc(part.label || id) + '">&times;</button>' : '') +
          '</span>';
      }).join('') +
        '<button type="button" class="btn btn-ghost btn-sm studio-set-add" data-act="studio-hand-pick" data-kind="' +
        esc(kind) + '" data-multi="1">Choose several&hellip;</button></div>' +
        '<p class="muted studio-small studio-set-sum">' + esc(studio_makeSummary(kind)) + '</p>';
    }
    return h + '</div>';
  }).join('');
  const code = studio_el('studio-deal-code');
  if (code) {
    code.textContent = drawers.map(function (k) { return studio_pickUnique(picks[k]).join('+'); }).filter(Boolean).join(' \u00b7 ');
  }
  /* THE STYLE SAYS WHEN IT WILL NOT MIX, so a Hype reel that comes out with one effect on
     every kill is the rule working, not a bug in the template. */
  const note = studio_el('studio-fast-note');
  if (note) {
    const st = studio.catalog && (studio.catalog.styles || []).find(x => x.key === studio.style);
    const bpm = studio.songShape ? studio.songShape.bpm : 0;
    const on = !!(st && st.fast_cuts);
    note.classList.toggle('hide', !on);
    if (on) {
      note.textContent = st.label + ' is a fast-cut style. ' + (bpm && bpm < 110
        ? 'This song is ' + Math.round(bpm) + ' BPM, so it mixes effects as other styles do. '
        : 'On a song of 110 BPM or more it keeps ONE transition, ONE kill effect and real speed, because at ' +
          'this pace variety reads as noise and a speed ramp makes the hit arrive late. ') +
        'Choose several in a drawer to mix them anyway.';
    }
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

/* Click the card in the hand: choose from a list. A list, because the other way to reach the
   thirtieth effect in a drawer was twenty-nine clicks. */
function studio_handPick(kind, multi) {
  const b = document.createElement('button');
  b.setAttribute('data-kind', kind);
  b.setAttribute('data-make', kind);
  if (multi) b.setAttribute('data-multi', '1');
  b.id = 'studio-hand-opener-' + kind;
  studio_fxpOpen(b);
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
  if (studio.order === 'kills') return sel.slice().sort((a, b) => studio_killsOf(b) - studio_killsOf(a));
  if (studio.order === 'oldest') return sel.slice().sort((a, b) => (a.when - b.when) || (a.rank - b.rank));
  return sel;
}

/* WHAT A PLAN IS ASKED FOR, once: Build sends it, and so does "Show where the kills will land", so the
   preview is the plan Build would make and not an approximation of it. `withMarks` adds the kills the
   player placed by hand. */
function studio_planBody(withMarks) {
  const body = {
    clips: studio_ordered().map(c => c.path), style: studio.style, song: studio.song,
    format: studio.fmt, vfit: studio.fmt === 'vertical' ? studio.vfit : 'zoom',
    name: studio_el('studio-name').value.trim(),
    /* Only what was DEALT or CLICKED. Sending the style's own picks back narrowed every drawer to the
       one part the style leads with, and a montage came out with the same kill effect on all six
       kills. A drawer's SET goes as a list, each id as many times as it is weighted. */
    template: studio.picks || null,
    shaping: Object.assign({}, studio.shaping, {arrange: studio.arrange,
      pins: studio.pins, shuffle_seed: studio.shuffleSeed,
      hs_only: !!(studio_el('studio-hs-only') && studio_el('studio-hs-only').checked &&
                  !studio_el('studio-hs-row').classList.contains('hide')),
      /* As chosen, '' when not: the server resolves '' exactly as studio_fillNow draws it, and the
         project keeps what was ASKED. */
      fill: studio.fill === 'part' && !studio_mkHasPart() ? '' : studio.fill,
      keep_all: !!studio.keepAll})
  };
  /* THE CLIP CHOSEN TO BUILD ON, from the guided maker's build slot. It was never sent, so the
     director built on whichever set-up scored best -- a double, with the ACE picked for it unused. */
  const build = studio.style === 'drop' && studio.buildClip &&
    studio.selected.some(id => (studio.clipIndex[id] || {}).path === studio.buildClip) ? studio.buildClip : '';
  if (build) body.shaping.build_clip = build;
  /* The whole clip, cover-fitted: the trim and the fit are the timeline dialog's job, and normalise
     clamps both anyway. What is chosen here is which intro and whether it is heard. */
  if (studio.mkIntro.path) {
    const got = (studio.intro.list || []).find(x => x.path === studio.mkIntro.path);
    body.intro_clip = {path: studio.mkIntro.path, start: 0,
                       end: got ? Number(got.seconds) : 0,
                       audio: !!studio.mkIntro.audio, fit: 'cover'};
  }
  if (studio_mkHasPart()) {
    body.part_start = studio.mk.start;
    body.part_end = studio.mk.end;
    /* Drawn by the page, never moved: Build and drop takes it as a length, not an end. */
    if (!studio.mk.touched) body.shaping.part_auto = true;
  }
  if (withMarks && studio.song && studio.mk.edited && studio.mk.hand.length) {
    body.marks = studio.mk.hand.map(k => Math.round(k.t * 1000) / 1000);
  }
  /* THE DROPS, once the player has touched them -- every plan, the preview's as well as Build's, so
     the kills it shows are the ones it will build around them. An empty list is "no drop at all". */
  if (studio.song && studio.mk.drops) {
    body.drops = studio.mk.drops.map(d => Math.round(d.t * 1000) / 1000);
  }
  return body;
}

async function studio_build(opts) {
  /* The guided maker plans from its own page: its button, its chip for the words. */
  const o = opts || {};
  const btn = o.btn || studio_el('studio-build-btn');
  const say = o.say || (t => { studio_el('studio-make-msg').textContent = t; });
  btn.disabled = true;
  /* The dialog's Cancel sits beside this button and stays live while the plan
     is fetched. Pressing it bumps this counter, which is how the rest of the
     build below learns it is no longer wanted -- it used to close the dialog
     and nothing else, so the render started anyway a moment later and looked
     like a Cancel that had been ignored. */
  const gen = ++studio.buildGen;
  say(!studio.song ? 'Planning every shot…'
    : studio.arrange === 'fit' ? 'Finding the perfect fit of every kill to the song — this can take up to ~30 s…'
    : 'Finding the beat and planning every shot…');
  try {
    const body = studio_planBody(true);
    /* A rebuild keeps the reel's own choices -- facecam, handle, ending --
       which belong to the reel and not to the plan being redone. */
    if (studio.adding && studio.adding.keep) body.keep = studio.adding.keep;
    const r = await API.post('/api/studio/plan', body);
    if (gen !== studio.buildGen) return;          /* cancelled while planning */
    if (!r || !r.ok) { say((r && r.error) || 'Could not plan that reel.', true); return; }
    studio_closeModals();
    const ad = studio.adding;
    /* A rebuild renders over the reel it rebuilds rather than beside it. */
    if (ad && ad.output) r.project.output = ad.output;
    studio_setProject(r.project, r.derived, r.notes, r.song);
    studio.output = ad && ad.output ? ad.output : ''; studio.undo = []; studio.redo = [];
    /* A fresh reel has no video to differ from; a rebuild over an existing one
       has exactly one difference, and it is the whole reel. */
    studio.pending = []; studio.dirty = true; studio.failMsg = '';
    studio.base = JSON.parse(JSON.stringify(studio.project));
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
  /* The reel's own arrangement, so a rebuild or a new style keeps it: a
     perfect-fit reel restyled from a fresh session came back built up. */
  if (project.arrange && ARRANGES.some(a => a.k === project.arrange) && project.arrange !== studio.arrange) {
    studio.arrange = project.arrange;
    studio_arrangeDraw();
  }
  studio_drawAll();
}

/* ------------------------------------------------------- back, and forward

   Undo used to be a POP: the step came off the stack and was gone, so a
   Ctrl+Z pressed once too often could not be taken back, and there was
   nothing anywhere to show what had been done. It is a cursor now -- two
   stacks, which is that cursor kept simply: `undo` holds the states behind
   you and `redo` the states ahead, and a step MOVES between them instead of
   being destroyed.

   Each entry carries the LABEL of the edit it belongs to, and that label is
   the one studio_change already wrote for the change list. The history is a
   second VIEW of those same words, never a second list of its own: two lists
   describing one set of edits would eventually disagree, and then neither
   could be believed. */

function studio_pushUndo(snapshot, label) {
  studio.undo.push({snap: snapshot, label: label || 'An edit on the timeline'});
  if (studio.undo.length > 60) studio.undo.shift();
  /* A fresh edit abandons the way forward: what you had undone is not a
     future of THIS project any more. */
  studio.redo = [];
}

/* The one place a step is crossed, in either direction, so back and forward
   cannot drift apart. */
function studio_step(from, to) {
  const got = from.pop();
  if (!got) return false;
  to.push({snap: JSON.stringify(studio.project), label: got.label});
  studio.gen++;
  studio.project = JSON.parse(got.snap);
  studio_untouched();
  studio_localDerive(); studio_drawAll();
  studio_check();
  return true;
}

/* ------------------------------------------------- what is not rendered yet

   The count is a comparison, not a tally of clicks. Each line on the list
   remembers the fields its edit changed; after every edit, undo and server
   answer, a line whose fields are all back to what was rendered goes. So a
   switch turned on and off again is no change at all, and three edits with one
   undone is two. A tally counted both clicks, and "Apply 2 changes" to a
   project identical to the video was a button that could not be believed.

   Two kinds of line cannot be compared and stay until a render: one with no
   fields (a failed render, a deleted reel, a camera video attached -- none of
   them live in the project), and any line about a shot while the shots are
   not in the order the render had them, because "shot 3" then names another
   shot. Both err toward saying the video is behind, never toward saying it
   matches when it does not. */

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

/* Equal for the purpose of "would the video differ": a number the server
   rounded is the number the page sent, and a field that is absent is the
   same as one that is null. */
function studio_same(a, b) {
  if (a === b) return true;
  if (a === null || a === undefined || b === null || b === undefined)
    return (a === null || a === undefined) && (b === null || b === undefined);
  if (typeof a === 'number' && typeof b === 'number') return Math.abs(a - b) < 1e-6;
  if (typeof a !== 'object' || typeof b !== 'object' || Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) return a.length === b.length && a.every((x, i) => studio_same(x, b[i]));
  return Object.keys(Object.assign({}, a, b)).every(k => studio_same(a[k], b[k]));
}

/* Every field that differs between two projects, as a list of key paths --
   ['vignette'], ['shots', '2', 'speed'], ['lyrics', 'pos']. A list of plain
   values (a shot's effects, a position) is one field, not one per item: taking
   an effect off and putting it back is the same list again. */
function studio_diff(a, b, at, out) {
  at = at || []; out = out || [];
  const obj = x => x !== null && typeof x === 'object';
  const deep = obj(a) && obj(b) && Array.isArray(a) === Array.isArray(b) &&
               (!Array.isArray(a) || a.concat(b).some(obj));
  if (!deep) { if (!studio_same(a, b)) out.push(at); return out; }
  const keys = Array.isArray(a) ? Array.from({length: Math.max(a.length, b.length)}, (_, i) => i)
                                : Object.keys(Object.assign({}, a, b));
  keys.forEach(k => studio_diff(a[k], b[k], at.concat([String(k)]), out));
  return out;
}

function studio_at(obj, path) {
  return path.reduce((o, k) => (o === null || o === undefined) ? undefined : o[k], obj);
}

/* Which clip is in which place. While it differs from the render's, a shot
   number names a different shot in each, so no shot's edit can be compared. */
function studio_shotOrder(p) { return ((p && p.shots) || []).map(s => s.clip).join('\n'); }

/* Does this line still describe a difference from the render? */
function studio_differs(x) {
  const base = studio.base, p = studio.project;
  if (!x.paths || !base || !p) return true;
  const ordered = studio_shotOrder(base) === studio_shotOrder(p);
  return x.paths.some(k => (!ordered && k[0] === 'shots') || !studio_same(studio_at(base, k), studio_at(p, k)));
}

/* Drop every line whose fields are all back to what was rendered. A dropped
   line is kept aside, so an undo that brings its difference back brings back
   its name too, rather than calling it something vaguer. */
function studio_reconcile() {
  const gone = studio.pending.filter(x => !studio_differs(x));
  if (gone.length) {
    studio.pending = studio.pending.filter(x => gone.indexOf(x) < 0);
    studio.shelved = (studio.shelved || []).filter(x => gone.indexOf(x) < 0).concat(gone).slice(-60);
  }
  studio.dirty = studio.pending.length > 0 || !studio.output;
}

/* `paths` is what the edit changed (studio_diff). Left out, the line cannot be
   compared and stays until a render. */
function studio_touched(label, shot, paths) {
  studio.dirty = true;
  studio.failMsg = '';
  /* "Ready · rendered in 23 s" stops being true the moment anything is
     touched, and a verdict left sitting under a warning is how the page said
     two opposite things at once. */
  studio_state('');
  const name = label || 'An edit on the timeline';
  const at = (shot === undefined || shot === null) ? -1 : shot;
  const keys = paths || null;
  /* A slider fires per step and a nudge button per press: the same edit, made
     again, is still one line. So is the same field reached by another control
     -- the kill dragged, then nudged -- because it is one thing that differs. */
  const sig = ks => JSON.stringify(ks.map(k => k.join('\u0001')).sort());
  const same = studio.pending.filter(x => x.label === name && x.shot === at)[0] ||
    (keys && keys.length ? studio.pending.filter(x => x.paths && x.paths.length && sig(x.paths) === sig(keys))[0] : null);
  if (same) {
    studio.pending.splice(studio.pending.indexOf(same), 1);
    same.label = name; same.shot = at;
    same.paths = studio_union(same.paths, keys);
    studio.pending.push(same);
  } else {
    studio.pending.push({label: name, shot: at, paths: keys});
  }
  studio_reconcile();
}

/* Two lines' fields as one; a line that cannot be compared makes both so. */
function studio_union(a, b) {
  if (!a || !b) return null;
  const one = k => k.join('\u0001');
  return a.concat(b.filter(k => !a.some(j => one(j) === one(k))));
}

/* Rendered: the video and the project are the same thing again, and this is
   the project every later edit is compared against. */
function studio_settled() {
  studio.dirty = false; studio.pending = []; studio.shelved = []; studio.failMsg = '';
  studio.base = studio.project ? JSON.parse(JSON.stringify(studio.project)) : null;
  /* The LYRICS stand-in is for placing the words; once a render is on its
     way the reel shows the real ones, and the stand-in would only cover them. */
  studio.lyrMove = false;
  studio_frameDraw();
}

/* An unrendered move of the lyrics: the stand-in stays up until the render
   shows the words where it says they are. */
function studio_lyrPending() {
  return studio.pending.some(x => /^Lyrics · (moved|back)/.test(x.label));
}

/* Removing or reordering shots renumbers them, so every shot index already on
   the list now points at the wrong shot. The edits still count; they just stop
   claiming to know which shot they were. */
function studio_forgetShots() { studio.pending.forEach(x => { x.shot = -1; }); }

/* A SHOT TAKEN OUT OR MOVED CLOSES UP ON THE SONG'S HITS (chosen 2026-10-19).
   Splicing the list slid every shot after it by the length of the one that
   went, so a reel cut to its song's hits was off every one of them. This asks
   the server to lay the marks back on (studio.normalise): each shot after the
   change moves up one hit. Said once, with the edit -- the answer comes back
   without it. */
function studio_remark(p) { if ((p.song_marks || []).length) p.remark = true; }

/* What a render writes about itself rather than what anyone chose: never a
   reason to render again. */
const STUDIO_NOT_EDITS = {output: 1, plan_notes: 1, lyrics_note: 1, render: 1, version: 1, remark: 1};
/* ...nor is which shots are locked together: the timeline reads it, the render does not. */
function studio_isEdit(k) { return k.length && !STUDIO_NOT_EDITS[k[0]] && k[k.length - 1] !== 'lock'; }

function studio_untouched() {
  studio_reconcile();
  const base = studio.base, p = studio.project;
  if (!base || !p) return;
  /* An edit that had been set back by hand, and that this undo has brought
     back again: it returns under its own name. */
  const back = (studio.shelved || []).filter(x => studio_differs(x));
  studio.shelved = (studio.shelved || []).filter(x => back.indexOf(x) < 0);
  back.forEach(x => {
    const twin = studio.pending.filter(y => y.label === x.label && y.shot === x.shot)[0];
    if (twin) twin.paths = studio_union(twin.paths, x.paths);
    else studio.pending.push(x);
  });
  /* Undone past the last render: the project is behind the video now, which
     is still a difference, and still needs rendering to resolve. Only what no
     line on the list already accounts for. */
  const mine = [];
  studio.pending.forEach(x => (x.paths || []).forEach(k => mine.push(k)));
  const under = (a, b) => a.length <= b.length && a.every((x, i) => x === b[i]);
  const left = studio_diff(base, p).filter(k => studio_isEdit(k) &&
    !mine.some(m => under(m, k) || under(k, m)));
  if (left.length) studio_touched('Undone past the last render', -1, left);
  studio.dirty = studio.pending.length > 0 || !studio.output;
}

/* `label` is what the card will call this edit, and `shot` the shot it happened
   to, so the timeline can mark it. Both optional -- an unlabelled edit still
   counts, it just reads as a generic one. `sticky` is for an edit the project
   cannot see (a camera video attached): it stays on the list until a render. */
function studio_change(mutate, label, shot, sticky) {
  if (!studio.project) return;
  const was = JSON.stringify(studio.project);
  studio_pushUndo(was, label);
  studio.gen++;
  mutate(studio.project);
  studio_touched(label, shot, sticky ? null : studio_diff(JSON.parse(was), studio.project));
  studio_localDerive();
  studio_drawAll();
  clearTimeout(studio.checkTimer);
  studio.checkTimer = setTimeout(studio_check, 250);
}

async function studio_check() {
  const n = ++studio.checking;
  const gen = studio.gen;
  const sent = JSON.stringify(studio.project);
  const r = await API.post('/api/studio/check', {project: studio.project});
  /* An answer about an older project must never replace a newer one: an edit
     made while this was in flight would silently disappear. */
  if (n !== studio.checking || gen !== studio.gen) return;
  if (!r || !r.ok) { toast((r && r.error) || 'That edit could not be applied.', 'warn'); return; }
  studio.project = r.project; studio.derived = r.derived; studio.notes = r.notes || [];
  /* What the server did in answer -- a slower speed trimming the shot to the
     footage there is -- belongs to the edit that caused it, so setting that
     edit back does not claim the video matches while the trim remains. And
     the answer can put a field back where the render had it: a transition
     changed and changed back only gets its old length again here. */
  const last = studio.pending[studio.pending.length - 1];
  if (last && last.paths && studio.base) {
    const knock = studio_diff(JSON.parse(sent), r.project).filter(k => studio_isEdit(k) &&
      !studio_same(studio_at(studio.base, k), studio_at(r.project, k)));
    last.paths = studio_union(last.paths, knock);
  }
  studio_reconcile();
  studio_drawAll();
}

/* The list, drawn from the two stacks and nothing else. Behind you, oldest
   first; then where you are; then what you have undone, which is still here.
   A step is numbered by how far it is from where you stand, because that is
   what clicking it costs. */
function studio_histDraw() {
  const host = studio_el('studio-hist');
  if (!host) return;
  host.classList.toggle('hide', !studio.histOpen || !studio.project);
  if (!studio.histOpen || !studio.project) return;
  const back = studio.undo, fwd = studio.redo;
  /* THE ACTION IS WRITTEN OUT, not assembled. The registry's own rule --
     every command names an action the page renders -- reads the source as
     text, and an action built from a variable is one nothing can find. The
     same reason the routes are written out in full at every call. */
  const guts = (label) => '<span class="studio-hist-dot" aria-hidden="true"></span>' +
    '<span class="studio-hist-lab">' + esc(label) + '</span></button>';
  const backRow = (label, n) =>
    '<button type="button" class="studio-hist-row" data-act="studio-hist-back" data-n="' +
    n + '">' + guts(label);
  const fwdRow = (label, n) =>
    '<button type="button" class="studio-hist-row is-off" data-act="studio-hist-fwd" data-n="' +
    n + '">' + guts(label);
  let html = '<div class="studio-hist-head"><h3>History</h3><span class="muted">' +
    (back.length + fwd.length) + (back.length + fwd.length === 1 ? ' step' : ' steps') +
    '</span></div>';
  if (!back.length && !fwd.length) {
    html += '<p class="muted studio-small studio-hist-none">Nothing done to this reel yet.</p>';
  } else {
    back.forEach((e, i) => { html += backRow(e.label, back.length - i); });
    html += '<p class="studio-hist-here"><span class="studio-hist-dot" aria-hidden="true"></span>' +
            'The reel is here</p>';
    /* The redo stack has the NEXT step on top, so it reads backwards. */
    for (let i = fwd.length - 1; i >= 0; i--) {
      html += fwdRow(fwd[i].label, fwd.length - i);
    }
    if (fwd.length) {
      html += '<p class="muted studio-small studio-hist-note">Undone &mdash; still here, ' +
              'still yours to put back.</p>';
    }
  }
  host.innerHTML = html;
}

function studio_undo() {
  if (!studio_step(studio.undo, studio.redo)) toast('There is nothing to undo.', 'warn');
}

function studio_redo() {
  if (!studio_step(studio.redo, studio.undo)) toast('There is nothing to put back.', 'warn');
}

/* Jump to a point in the history by crossing the steps between here and
   there, rather than by restoring that state directly -- so the two stacks
   stay exactly as they would after pressing the key that many times, and the
   change list is reconciled at every step rather than once at the end. */
function studio_histGo(back, fwd) {
  for (let i = 0; i < back; i++) if (!studio_step(studio.undo, studio.redo)) break;
  for (let i = 0; i < fwd; i++) if (!studio_step(studio.redo, studio.undo)) break;
}

/* A quick estimate while dragging. The server's answer replaces it. */
function studio_localDerive() {
  const p = studio.project, d = studio.derived;
  if (!p) return;
  studio_lockTidy(p.shots);
  let t = 0;
  const rows = p.shots.map((s, i) => {
    const old = (d && d.shots[i]) || {};
    /* THE OTHER KILLS ARE RE-BASED, NOT THROWN AWAY. They used to be
       replaced by the shot's own kill for the length of a drag, so every
       other diamond vanished the moment the hand moved and came back when
       the server answered. They do not follow from the shots, so they are
       carried and shifted by however far the shot moved. */
    const was = (old.kills_reel && old.kills_reel.length) ? old.kills_reel : [old.kill_reel];
    const shift = t - (old.start === undefined ? t : old.start);
    const row = {index: i, start: t, end: t + s.duration, kill_reel: t + s.pre,
                 kills_reel: was.map(k => (k === undefined ? t + s.pre : k + shift)),
                 /* WHICH SOURCE SECONDS THIS SHOT USES, carried like `pieces`.
                    Dropped here, `studio_shotKills` filtered against undefined,
                    got an empty list, and every drag after the first one
                    anchored nothing -- found by a browser pressing the button,
                    which is the only place it could have been found. */
                 source_in: old.source_in, source_out: old.source_out,
                 pieces: old.pieces || [[0, s.duration, 1]]};
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

/* LET GO OF THE OLD REEL BEFORE A NEW ONE REPLACES IT.
   The player streams the finished mp4 through our own server, which keeps the
   file open for the length of the response -- and Windows refuses to rename
   over a file anything has open. So a render of the reel on screen finished
   all its work and then died on its last line, WinError 5.
   Nothing is lost by dropping it here: the instant preview is what is shown
   while a render is in flight anyway, which is the whole reason it exists. */
function studio_freeOutput() {
  const v = studio_el('studio-video');
  if (!v || !v.getAttribute('src')) return;
  try {
    v.pause();
    v.removeAttribute('src');
    v.load();                       /* without this the handle survives */
  } catch (e) { /* a player that will not let go is the server's problem */ }
}

async function studio_render() {
  if (!studio.project) return;
  studio_freeOutput();
  /* A check still waiting or in flight describes the project before the
     server allocates its output; letting it land afterwards would wipe that. */
  clearTimeout(studio.checkTimer);
  studio.gen++;
  /* The previous render is old news once a new one is asked for: a poll that
     lands in between must not say "Ready" about the reel being replaced. */
  studio.seenJob = studio.jobId; studio.watching = -1;
  /* Render beats the background render: the server cancels that one to start
     this, and its timer has nothing left to do. */
  clearTimeout(studio.auto.timer); studio.auto.timer = null;
  studio.auto.running = false; studio.auto.job = 0; studio.auto.held = '';
  studio.project.name = studio_el('studio-pname').value.trim() || studio.project.name;
  /* The list of what is pending belongs to the project being sent. Clearing it
     here rather than on the job's reply means the card stops claiming, for the
     length of the render, that those edits are still missing. */
  const sent = studio.pending.slice(), sentBase = studio.base;
  studio_settled();
  /* Said before the round trip, not after it: the gap between pressing the
     button and the first poll is exactly where the page used to look as if
     nothing had happened. */
  studio_busy(true);
  studio_el('studio-meter').style.width = '0%';
  studio_state('Starting the render…');
  studio_drawRenderCard();
  const gen = studio.gen;
  const r = await API.post('/api/studio/render', {project: studio.project});
  if (!r || !r.ok) {
    studio_busy(false);
    studio.pending = sent.concat(studio.pending); studio.base = sentBase; studio.dirty = studio.pending.length > 0;
    studio_state((r && r.error) || 'Could not start the render.', true);
    studio_drawRenderCard();
    return;
  }
  /* AN EDIT MADE WHILE THE SERVER WAS ANSWERING STAYS. The answer is the project
     as it was when Render was pressed; taking it over an edit made since threw
     that edit away and with it the line saying it was not rendered yet -- so it
     never rendered. Found when the clip strip's player made the answer slower. */
  if (gen === studio.gen) {
    studio.project = r.project; studio.derived = r.derived; studio.notes = r.notes || [];
  } else {
    studio.project.output = r.project.output;
  }
  studio.output = r.output;
  /* What the server will render, rounded and clamped, is what later edits are
     measured against -- not what the page sent a moment before. */
  studio.base = JSON.parse(JSON.stringify(r.project)); studio_reconcile();
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
  if (!j || j.state === 'idle') { studio_busy(false); studio.auto.running = false; studio_drawRenderCard(); return; }
  const running = j.state === 'running' || j.state === 'queued';
  /* A background render does not take the Render button away: pressing it
     replaces the background one. */
  const bg = !!j.auto;
  studio_busy(running && !bg);
  studio.auto.running = running && bg;
  if (running && bg) { studio.auto.job = j.id; studio.auto.pct = j.percent || 0; }
  studio_show('studio-meter-wrap', running);
  studio_el('studio-meter').style.width = (running ? j.percent : 100) + '%';
  if (running) {
    studio.watching = j.id;       /* seen running on this page: its finish is news */
    studio.jobMsg = j.message + (j.cached ? ' · ' + j.cached + ' shots unchanged' : '');
    studio_state(bg ? '' : studio.jobMsg);
    studio_drawRenderCard();
    studio.polling = setTimeout(studio_poll, 700);
    return;
  }
  studio.jobMsg = '';
  if (bg) { studio_autoDone(j); return; }
  /* A finished job is news once, and only to a page that started it or watched
     it run. The server keeps the last job for as long as it runs, so without
     this every visit to the page announced the same reel again. */
  const news = j.id !== studio.seenJob && (j.id === studio.jobId || j.id === studio.watching);
  studio.seenJob = j.id;
  if (!news) { studio_drawRenderCard(); return; }
  if (j.state === 'done') {
    const same = studio.project && j.output === studio.project.output;
    studio.renderNote = 'took ' + j.elapsed + ' s' + (j.cached ? ' · ' + j.cached + ' shots reused' : '');
    /* What the lyrics did is only knowable after the render: found or not,
       and how many words landed on kills. The Lyrics group shows it. */
    if ((j.lyrics_note || '') !== (studio.lyricsNote || '')) {
      studio.lyricsNote = j.lyrics_note || '';
      studio_drawInspector();
    }
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

/* A background render has finished, one way or another. Said quietly: nobody
   pressed anything, so there is no toast -- the player changing over to the
   real video, and the strip turning green, are the news. */
function studio_autoDone(j) {
  const a = studio.auto;
  a.running = false;
  /* What this reel costs to render, learned from the render itself -- a
     render the user started teaches it too, since that is the same work. */
  if (Number(j.elapsed) > 0) a.lastMs = Number(j.elapsed) * 1000;
  const news = j.id !== studio.seenJob && (j.id === studio.jobId || j.id === studio.watching || j.id === a.job);
  studio.seenJob = j.id;
  if (!news) { studio_drawRenderCard(); return; }
  const mine = j.id === a.job;
  if (j.state === 'done') {
    /* The video IS the project only if nothing was edited since it was sent.
       Otherwise it is still newer than the last one -- worth loading -- and
       the preview stays up over it until the render of the newest edit. */
    const fresh = mine && !!a.sig && a.sig === studio_projSig();
    const extra = j.cached ? ' · ' + j.cached + ' shots reused' : '';
    studio.renderNote = 'took ' + j.elapsed + ' s' + extra;
    if ((j.lyrics_note || '') !== (studio.lyricsNote || '')) {
      studio.lyricsNote = j.lyrics_note || '';
      studio_drawInspector();
    }
    if (studio.project && j.output === studio.project.output) {
      studio.output = j.output; studio.renderedAt = Date.now();
      if (fresh) studio_settled();
      studio_loadVideo();
    }
    studio_state(fresh ? 'Rendered in the background in ' + j.elapsed + ' s' + extra : '');
    studio_autoLog('done', String(j.elapsed));
  } else if (j.state === 'failed') {
    if (mine) a.failed = a.sig;
    studio_state(j.error || 'The render failed.', true);
    studio_autoLog('failed', j.error || '');
  } else {
    /* Replaced by a newer edit or switched off: nothing went wrong, and
       nothing was taken off the list of edits, so there is nothing to say. */
    studio_autoLog('cancelled');
  }
  if (mine) a.sig = '';
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

/* ------------------------------------------------- the instant preview

   An edit used to be invisible until it had been rendered. Now the player
   plays the timeline itself whenever the rendered file is not the project on
   screen: every shot is its clip file, played from the second the render
   would take, at the speed the render would play it, with the song started
   where the reel starts it. Nothing is encoded, so a deleted shot is gone from
   the player in the same frame it is gone from the timeline.

   What it is not: the effects, the grade, the transitions' blends, the text.
   Those are ffmpeg's, and the label over the picture says they arrive with
   the render -- which, with background rendering on, is already under way. */

/* Seconds of a shot's footage consumed by `upto` seconds of its output. */
function studio_pvUsed(ps, upto) {
  let used = 0;
  for (const p of ps) {
    if (upto <= p[0]) break;
    used += (Math.min(p[1], upto) - p[0]) * p[2];
  }
  return used;
}

/* What decides a shot's footage, as one string: two shots that agree on it
   play the same seconds of the same clip. */
function studio_pvKey(s) {
  return JSON.stringify([s.clip, s.kill, s.pre, s.duration, s.speed, s.stretch || null,
                         s.kills || [], s.fx || [], !!s.hero, s.hero_fx || []]);
}

/* The server's account of shot i's footage: where it starts in the clip, its
   speed map, and how long the kill's frame is held. Only the server's derive
   carries them; while the page's own quick estimate stands in (a drag, the
   quarter second before /check answers), a shot nothing has changed about
   keeps what the server said last time, and a shot being changed plays at
   real speed from where its kill puts it. */
function studio_pvInfo(i) {
  const p = studio.project, d = studio.derived;
  const s = p && p.shots[i], r = d && d.shots[i];
  if (!s || !r) return null;
  const key = studio_pvKey(s);
  if (r.source_in !== undefined && r.freeze !== undefined) {
    const got = {source_in: r.source_in, pieces: r.pieces, freeze: r.freeze};
    studio.pv.info[key] = got;
    return got;
  }
  return studio.pv.info[key] ||
    {source_in: Math.max(0, s.kill - s.pre), pieces: [[0, s.duration, 1]], freeze: 0};
}

/* WHERE THE REEL IS AT REEL SECOND t: which shot, which second of its clip,
   and how fast -- 0 while a frame is held. clips/studio.py preview_at() is the
   same arithmetic, and the browser test holds the two to each other. */
function studio_pvAt(t) {
  const d = studio.derived, rows = (d && d.shots) || [];
  if (!rows.length) return {shot: -1, src: 0, rate: 0};
  t = Math.max(0, Number(t) || 0);
  let i = 0;
  while (i + 1 < rows.length && t >= rows[i + 1].start) i++;
  const r = rows[i], info = studio_pvInfo(i);
  const ps = info.pieces, dur = r.end - r.start;
  let u = t - r.start;
  const pre = r.kill_reel - r.start, freeze = Number(info.freeze) || 0;
  const held = u >= dur;
  u = Math.min(u, dur);
  if (freeze && u >= pre && u < pre + freeze) {
    return {shot: i, src: info.source_in + studio_pvUsed(ps, pre), rate: 0};
  }
  if (freeze && u >= pre + freeze) u -= freeze;
  let rate = 0;
  if (!held) {
    const piece = ps.find(x => x[0] <= u && u < x[1]);
    rate = piece ? piece[2] : ps[ps.length - 1][2];
  }
  /* Slower than a browser will play is a held frame, which is what the
     render's HOLD_RATE is for anyway. */
  if (rate < 0.0625) rate = 0;
  return {shot: i, src: info.source_in + studio_pvUsed(ps, u), rate: rate};
}

function studio_pvEls() { return [studio_el('studio-pv-a'), studio_el('studio-pv-b')]; }

/* The reel second the preview is on. */
function studio_pvTime() {
  const pv = studio.pv;
  return pv.playing ? pv.base + (performance.now() - pv.t0) / 1000 * pv.rate : pv.t;
}

/* The app's one volume and speed (shell mediaKnobs) under the preview too.
   Its players opt out of shell_knobApply (data-knobs="off"), because the
   rate is the shot's own and the volume the project's game level -- the
   viewer's choice is multiplied in here instead of written over them. */
function studio_pvKnobs() {
  return typeof shell_knobPrefs === 'function' ? shell_knobPrefs() : {vol: 1, rate: 1};
}

function studio_pvLevels(vol) {
  const pv = studio.pv, p = studio.project;
  if (typeof vol !== 'number' || isNaN(vol)) vol = studio_pvKnobs().vol;
  const el = studio_pvEls()[pv.act], a = studio_el('studio-pv-song');
  if (el && p) { el.muted = pv.muted; el.volume = Math.max(0, Math.min(1, studio_dbGain(p.game_db) * vol)); }
  if (a && p) { a.muted = pv.muted; a.volume = Math.max(0, Math.min(1, studio_dbGain(p.music_db) * vol)); }
  const m = studio_el('studio-pv-mute');
  if (m) {
    m.innerHTML = pv.muted ? '&#128263;' : '&#128266;';
    m.setAttribute('aria-pressed', pv.muted ? 'true' : 'false');
    m.setAttribute('aria-label', pv.muted ? 'Unmute' : 'Mute');
    m.title = pv.muted ? 'Unmute' : 'Mute';
  }
}

/* ---- the preview's lyrics (studio_pvLyrSync asks, studio_pvLyrClock keeps time)

   What the overlay was drawn from: everything lyrics.prepare reads. Two
   projects with the same of these have the same words in the same places. */
function studio_pvLyrSig() {
  const p = studio.project, d = studio.derived;
  if (!p || !d) return '';
  const l = p.lyrics || {};
  if (!l.look || l.look === 'off' || !p.song) return '';
  return studio_canon([l, p.song, Number(p.song_offset) || 0, p.format, d.length, d.kills || []]);
}

/* After an edit: ask for the overlay of the project as it now is, unless it
   is the one on screen. Asked a moment after the last edit, so a look clicked
   through quickly is drawn once; one ask at a time, the newest wins. */
function studio_pvLyrSync() {
  const L = studio.pv.lyr, sig = studio.pv.on ? studio_pvLyrSig() : '';
  L.want = sig;
  if (!sig) { L.sig = ''; studio_pvLyrShow(''); return; }
  if (sig === L.sig) return;
  clearTimeout(L.timer);
  L.timer = setTimeout(studio_pvLyrAsk, 350);
  studio_pvLyrTag();
}

async function studio_pvLyrAsk() {
  const L = studio.pv.lyr;
  if (L.busy || !L.want || L.want === L.sig) return;
  const sig = L.want;
  L.busy = true;
  studio_pvLyrTag();
  let r = null;
  try { r = await API.post('/api/studio/lyrics/preview', {project: studio.project}); } catch (e) { r = null; }
  L.busy = false;
  if (L.want !== sig) { studio_pvLyrAsk(); return; }     /* edited meanwhile: that one, now */
  L.sig = sig;
  L.note = r ? (r.held || r.error || r.none || '') : 'The lyrics could not be drawn for the preview.';
  studio_pvLyrShow(r && r.ok && r.overlay ? r.overlay : '');
  studio_pvLyrTag();
}

function studio_pvLyrShow(name) {
  const L = studio.pv.lyr, v = studio_el('studio-pv-lyr');
  if (!v) return;
  if (name !== L.name) {
    L.name = name;
    if (name) {
      v.src = '/api/studio/lyrics/overlay?k=' + encodeURIComponent(SHELL_K) + '&name=' + encodeURIComponent(name);
      v.addEventListener('loadedmetadata', () => studio_pvLyrClock(studio_pvTime(), studio.pv.playing), {once: true});
    } else { v.pause(); v.removeAttribute('src'); v.load(); }
  }
  studio_show('studio-pv-lyr', !!name);
}

/* The overlay on the reel's clock, as the song is. */
function studio_pvLyrClock(t, playing) {
  const v = studio_el('studio-pv-lyr'), pv = studio.pv;
  if (!v || !pv.lyr.name || v.readyState < 1) return;
  if (Math.abs(v.playbackRate - pv.rate) > 0.001) v.playbackRate = pv.rate;
  if (!playing) { if (!v.paused) v.pause(); if (Math.abs(v.currentTime - t) > 0.04) v.currentTime = t; return; }
  if (Math.abs(v.currentTime - t) > 0.15 && !v.seeking) v.currentTime = t;
  if (v.paused) v.play().catch(() => {});
}

function studio_pvLyrTag() {
  const tag = studio_el('studio-pv-tag'), L = studio.pv.lyr;
  if (!tag) return;
  const drawing = !!L.want && L.want !== L.sig;
  tag.textContent = 'Preview · ' + (drawing ? 'drawing the lyrics… · ' : '') + 'effects appear when rendered';
}

/* The blurred copy behind a fitted 9:16 picture: the middle of the frame on
   screen, cropped to the reel's shape -- what the render's boxblur is fed. */
function studio_pvBg() {
  const pl = studio_el('studio-player'), cv = studio_el('studio-pv-bg');
  if (!pl || !cv || !pl.classList.contains('is-vertical') || !pl.classList.contains('is-fit')) return;
  const el = studio_pvEls()[studio.pv.act];
  if (!el || el.readyState < 2 || !el.videoWidth) return;
  const vw = el.videoWidth, vh = el.videoHeight, want = cv.width / cv.height;
  let sw = vw, sh = vh;
  if (vw / vh > want) sw = vh * want; else sh = vw / want;
  try {
    cv.getContext('2d').drawImage(el, (vw - sw) / 2, (vh - sh) / 2, sw, sh, 0, 0, cv.width, cv.height);
  } catch (e) { /* a frame not decoded yet: the next one draws */ }
}

/* The bar over the preview: its button, its clock and where its seek is. */
function studio_pvBar() {
  const pv = studio.pv, d = studio.derived;
  const len = d ? d.length : 0, t = Math.min(studio_pvTime(), len);
  const mmss = x => { x = Math.max(0, Math.floor(x)); return Math.floor(x / 60) + ':' + String(x % 60).padStart(2, '0'); };
  const tm = studio_el('studio-pv-time');
  if (tm) tm.textContent = mmss(t) + ' / ' + mmss(len);
  const sk = studio_el('studio-pv-seek');
  if (sk && !pv.scrub) sk.value = String(len > 0 ? Math.round(t / len * 1000) : 0);
  const b = studio_el('studio-pv-play');
  if (b) {
    b.innerHTML = pv.playing ? '&#10073;&#10073;' : '&#9654;';
    b.setAttribute('aria-label', pv.playing ? 'Pause' : 'Play');
    b.title = (pv.playing ? 'Pause' : 'Play') + ' (space)';
  }
  const box = studio_el('studio-pv');
  if (box) box.classList.toggle('is-playing', pv.playing);
}

/* Fullscreen takes the whole player, not the preview alone: the render can
   finish while it is up, and the rendered video is beside the preview in it. */
function studio_pvFull() {
  const pl = studio_el('studio-player');
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  else if (pl && pl.requestFullscreen) pl.requestFullscreen().catch(() => {});
}

/* Is the rendered file NOT the project on screen? Then the player shows the
   preview: never rendered, an edit since, or a render of it still running. */
function studio_pvWanted() {
  return !!(studio.project && studio.derived && studio.project.shots.length &&
            (!studio.output || studio.dirty || studio.rendering));
}

/* The reel second the player is on, whichever it is showing. */
function studio_now() {
  if (studio.pv.on) return studio_pvTime();
  const v = studio_el('studio-video');
  return v && v.src ? v.currentTime || 0 : 0;
}

function studio_dbGain(db) { return Math.max(0, Math.min(1, Math.pow(10, (Number(db) || 0) / 20))); }

/* Put shot i's clip in a player, at source second `src`. A player already
   holding that clip only seeks; one that is still loading seeks when it can. */
function studio_pvLoad(el, i, src) {
  const s = studio.project.shots[i];
  if (!el || !s) return;
  el.setAttribute('data-shot', String(i));
  if (el.getAttribute('data-clip') !== s.clip) {
    el.setAttribute('data-clip', s.clip);
    el.setAttribute('data-seek', String(src));
    el.src = studio_media('/api/clips/video', s.clip);
    return;
  }
  if (el.readyState >= 1) {
    if (Math.abs(el.currentTime - src) > 0.02) el.currentTime = src;
  } else el.setAttribute('data-seek', String(src));
}

/* The next shot, cued in the player that is off screen, so the cut is a swap
   and not a load. */
function studio_pvCue(i) {
  const pv = studio.pv, rows = studio.derived.shots;
  const other = studio_pvEls()[1 - pv.act];
  if (i + 1 >= rows.length) return;
  const at = studio_pvAt(rows[i + 1].start);
  other.pause();
  studio_pvLoad(other, i + 1, at.src);
}

/* Show shot `at.shot` -- the cued player if it holds it, else load it here. */
function studio_pvCut(at, t) {
  const pv = studio.pv, els = studio_pvEls();
  const p = studio.project, rows = studio.derived.shots;
  let cued = false;
  if (Number(els[1 - pv.act].getAttribute('data-shot')) === at.shot && pv.shot >= 0) {
    pv.act = 1 - pv.act;
    cued = true;
  }
  const el = els[pv.act], off = els[1 - pv.act];
  studio_pvLoad(el, at.shot, at.src);
  el.classList.add('is-on');
  off.classList.remove('is-on');
  off.pause();
  off.muted = true;
  studio_pvLevels();
  if (pv.playing && at.rate > 0) { el.playbackRate = Math.min(16, at.rate * pv.rate); el.play().catch(() => {}); }
  if (pv.playing && pv.shot >= 0) {
    const want = rows[at.shot].start;
    pv.cuts.push({shot: at.shot, at: Math.round(t * 1000) / 1000, want: want,
                  late: Math.round((t - want) * 1000) / 1000, cued: cued, ready: el.readyState});
    if (pv.cuts.length > 50) pv.cuts.shift();
  }
  pv.shot = at.shot;
  studio_pvCue(at.shot);
}

function studio_pvSongSync(t, playing) {
  const a = studio_el('studio-pv-song'), p = studio.project, pv = studio.pv;
  if (!a) return;
  if (!p || !p.song || !playing) { if (!a.paused) a.pause(); return; }
  const want = (Number(p.song_offset) || 0) + t;
  if (a.getAttribute('data-song') !== p.song) {
    a.setAttribute('data-song', p.song);
    a.src = studio_media('/api/reel/audio', p.song);
  }
  studio_pvLevels();
  a.preservesPitch = true;
  if (Math.abs(a.playbackRate - pv.rate) > 0.001) a.playbackRate = pv.rate;
  if (a.readyState >= 1 && Math.abs(a.currentTime - want) > 0.12) a.currentTime = want;
  if (a.paused) { if (a.readyState >= 1) a.currentTime = want; a.play().catch(() => {}); }
}

/* One frame of playback: the clock says where the reel is, and everything
   follows it -- the shot on screen, its speed, the song. The players are
   corrected toward the clock rather than trusted, because a <video> that
   stalls for a moment would otherwise carry every later cut late with it. */
function studio_pvTick() {
  const pv = studio.pv, d = studio.derived;
  pv.raf = 0;
  if (!pv.playing || !pv.on || !d) return;
  if (shell_page !== 'studio') { studio_pvPause(); return; }
  let t = studio_pvTime();
  if (t >= d.length) { pv.t = d.length; studio_pvPause(); return; }
  const at = studio_pvAt(t);
  if (at.shot !== pv.shot) studio_pvCut(at, t);
  const el = studio_pvEls()[pv.act];
  if (at.rate === 0) {
    if (!el.paused) el.pause();
    if (el.readyState >= 1 && Math.abs(el.currentTime - at.src) > 0.05 && !el.seeking) el.currentTime = at.src;
  } else if (el.readyState >= 1) {
    const drift = el.currentTime - at.src;
    if (Math.abs(drift) > 0.3) { if (!el.seeking) el.currentTime = at.src; }
    const rate = Math.max(0.0625, Math.min(16, at.rate * pv.rate * (1 - Math.max(-0.25, Math.min(0.25, drift)))));
    if (Math.abs(el.playbackRate - rate) > 0.02) el.playbackRate = rate;
    if (el.paused) el.play().catch(() => {});
  }
  studio_pvSongSync(t, true);
  studio_pvLyrClock(t, true);
  studio_pvBg();
  studio_playhead();
  pv.raf = requestAnimationFrame(studio_pvTick);
}

/* Paused on reel second t: the right frame of the right clip, still. */
function studio_pvShow(t) {
  const pv = studio.pv, d = studio.derived;
  if (!d || !studio.project) return;
  pv.t = Math.max(0, Math.min(Number(t) || 0, d.length));
  const at = studio_pvAt(Math.min(pv.t, Math.max(0, d.length - 0.001)));
  if (at.shot < 0) return;
  studio_pvCut(at, pv.t);
  studio_pvEls()[pv.act].pause();
  studio_pvSongSync(pv.t, false);
  studio_pvLyrClock(pv.t, false);
  studio_pvBg();
  studio_playhead();
}

function studio_pvPlay() {
  const pv = studio.pv, d = studio.derived;
  if (!pv.on || !d || pv.playing) return;
  if (pv.t >= d.length - 0.05) pv.t = 0;
  pv.rate = studio_pvKnobs().rate || 1;
  pv.base = pv.t; pv.t0 = performance.now(); pv.playing = true;
  pv.shot = -1;               /* the first frame re-takes the shot it is in */
  studio_el('studio-play-btn').textContent = 'Pause';
  studio_pvBar();
  pv.raf = requestAnimationFrame(studio_pvTick);
}

function studio_pvPause() {
  const pv = studio.pv;
  if (pv.playing) pv.t = studio_pvTime();
  pv.playing = false;
  if (pv.raf) cancelAnimationFrame(pv.raf);
  pv.raf = 0;
  studio_pvEls().forEach(v => { if (v && !v.paused) v.pause(); });
  studio_pvSongSync(pv.t, false);
  studio_pvLyrClock(pv.t, false);
  const b = studio_el('studio-play-btn');
  if (b) b.textContent = 'Play';
  studio_playhead();
  studio_pvBar();
}

/* The player's transport, whichever it is showing. */
function studio_toggle() {
  if (studio.pv.on) { if (studio.pv.playing) studio_pvPause(); else studio_pvPlay(); return; }
  const v = studio_el('studio-video');
  if (v.src) { if (v.paused) v.play().catch(() => {}); else v.pause(); }
}

function studio_seekTo(t) {
  t = Math.max(0, Number(t) || 0);
  if (studio.pv.on) {
    if (studio.pv.playing) { studio.pv.base = t; studio.pv.t0 = performance.now(); studio.pv.shot = -1; }
    else studio_pvShow(t);
  } else {
    const v = studio_el('studio-video');
    if (v.src) v.currentTime = t;
  }
  studio_playhead();
}

/* Called whenever the render card is redrawn, which is after every edit, every
   answer from /check and every poll of the render: which player is up, and
   whether the preview's shots still mean what they meant. */
function studio_pvSync() {
  const pv = studio.pv, want = studio_pvWanted(), v = studio_el('studio-video');
  if (!v) return;
  if (want !== pv.on) {
    if (want) {
      /* From the rendered file to the preview, at the same second. */
      const t = v.src ? v.currentTime || 0 : pv.t, was = v.src && !v.paused;
      if (!v.paused) v.pause();
      pv.on = true; pv.t = t; pv.shot = -1; pv.planSig = '';
      studio_pvEls().forEach(e => e.setAttribute('data-shot', '-1'));
      studio_pvShow(t);
      if (was) studio_pvPlay();
    } else {
      /* The render has caught up: the real thing, at the same second. */
      const t = studio_pvTime(), was = pv.playing;
      studio_pvPause();
      pv.on = false;
      const go = () => { v.currentTime = Math.min(t, v.duration || t); if (was) v.play().catch(() => {}); };
      if (v.readyState >= 1) go(); else v.addEventListener('loadedmetadata', go, {once: true});
    }
  }
  studio_show('studio-pv', pv.on);
  v.classList.toggle('hide', pv.on);
  studio_pvLyrSync();
  if (pv.on) studio_show('studio-player-empty', false);
  else studio_show('studio-player-empty', !studio.output);
  if (!pv.on) return;
  /* The shots moved under the preview -- deleted, reordered, re-timed. Shot 3
     may be a different clip now, so nothing cued can be trusted. */
  const d = studio.derived, p = studio.project;
  const sig = JSON.stringify(d.shots.map((r, i) => [p.shots[i] && p.shots[i].clip, r.start, r.end,
                                                     r.source_in, r.freeze])) + '|' + d.length;
  if (sig === pv.planSig) return;
  pv.planSig = sig;
  pv.shot = -1;
  studio_pvEls().forEach(e => e.setAttribute('data-shot', '-1'));
  if (pv.playing) {
    const t = Math.min(studio_pvTime(), d.length);
    pv.base = t; pv.t0 = performance.now();
  } else studio_pvShow(Math.min(pv.t, d.length));
}

/* ------------------------------------------------- the background render

   The preview is exact about the cut and approximate about the look, so the
   real render is still wanted -- just not as a thing to remember to press.
   When the edits stop for a couple of seconds it starts by itself; an edit
   made while it runs replaces it (the server cancels it; the shots it had
   finished stay cached); and Render still works, and wins.

   It never starts while you are live, recording or cutting clips: the
   encoder is the broadcast's first. The page checks, and so does the server
   (webui.studio_auto_held), because a timer the page forgot to stop is not
   what should decide whether a live stream drops frames. */

/* The project as one string, minus where it renders to (which the server
   fills in) -- so "is the video this project?" is a string comparison. */
function studio_canon(v) {
  if (Array.isArray(v)) return '[' + v.map(studio_canon).join(',') + ']';
  if (v && typeof v === 'object') {
    return '{' + Object.keys(v).filter(k => k !== 'output').sort()
      .map(k => JSON.stringify(k) + ':' + studio_canon(v[k])).join(',') + '}';
  }
  return JSON.stringify(v === undefined ? null : v);
}

function studio_projSig() { return studio.project ? studio_canon(studio.project) : ''; }

function studio_autoLog(what, why) {
  const a = studio.auto;
  a.log.push({at: Date.now(), what: what, why: why || '', job: a.job});
  if (a.log.length > 40) a.log.shift();
}

/* Whatever on this machine has a better claim on the encoder, from the
   status poll the shell already makes. */
function studio_autoBusyElsewhere() {
  const s = (typeof STATUS !== 'undefined' && STATUS) || {};
  if (s.phase && s.phase !== 'IDLE') return 'Waiting until you are not live.';
  if (s.recording) return 'Waiting until the recording stops.';
  const j = s.clips;
  if (j && (j.state === 'running' || j.state === 'queued')) return 'Waiting for the clip job to finish.';
  return '';
}

/* After every redraw of the render card: a project that has changed since the
   timer was last started starts it again. */
/* The longest the page will sit on an edit before rendering it anyway. Long
   enough for a four-minute render to survive ordinary editing, short enough
   that nobody wonders whether it is coming. */
const AUTO_WAIT_MAX = 20000;

function studio_autoArm() {
  const a = studio.auto, sig = studio_projSig();
  if (sig === a.armed) return;
  a.armed = sig;
  clearTimeout(a.timer); a.timer = null;
  /* WAIT IN PROPORTION TO WHAT A RENDER COSTS ON THIS REEL. 2.5 s was a
     pause between keystrokes; on a 47-shot reel the render takes 4m18s and
     `yield_auto` throws the running one away for the next edit, so a steady
     editor restarted it forever and nothing ever landed -- which reads as
     "the render does not start by itself". A tenth of the last render,
     capped, is long enough to mean the editing has actually stopped.

     Counted from the last edit even when something is in the way, so the
     poll that finds the way clear does not start it mid-gesture. */
  a.waitMs = Math.min(AUTO_WAIT_MAX, Math.max(a.idleMs, (a.lastMs || 0) / 10));
  a.dueAt = Date.now() + a.waitMs;
  if (!a.on || !studio.project || !studio.dirty) return;
  if (studio.rendering) {
    /* Never a second encode beside the one the user asked for. The edit
       waits, and the poll starts it when that render is done. */
    a.held = 'Waiting for the render you started.';
    studio_autoLog('held', a.held);
    return;
  }
  if (a.running && sig === a.sig) return;
  a.held = '';
  a.timer = setTimeout(studio_autoGo, a.waitMs || a.idleMs);
}

async function studio_autoGo() {
  const a = studio.auto;
  clearTimeout(a.timer); a.timer = null;
  if (!a.on || !studio.project || !studio.dirty) { studio_autoDraw(); return; }
  if (studio.drag) { a.timer = setTimeout(studio_autoGo, 600); return; }
  const sig = studio_projSig();
  if (a.running && a.sig === sig) return;
  let held = studio.rendering ? 'Waiting for the render you started.' : studio_autoBusyElsewhere();
  if (!held && sig === a.failed) held = 'The last render of these edits failed. Press Render to try again.';
  if (held) { a.held = held; studio_autoLog('held', held); studio_autoDraw(); return; }
  const gen = studio.gen;
  a.held = '';
  a.sig = sig;
  studio_autoLog('start');
  clearTimeout(studio.checkTimer);
  /* The background render replaces the same file, so it has to let go of it
     too -- and it is the one that runs most often. */
  studio_freeOutput();
  const r = await API.post('/api/studio/render', {project: studio.project, auto: true}).catch(() => null);
  if (!r || !r.ok) {
    a.sig = '';
    if (r && r.held) { a.held = r.held; a.heldUntil = Date.now() + 5000; studio_autoLog('held', r.held); }
    else { a.failed = sig; a.held = (r && r.error) || 'The background render could not start.'; studio_autoLog('refused', a.held); }
    studio_autoDraw();
    return;
  }
  /* The answer is the project normalised, with the file it renders to. Taken
     only if nothing was edited during the round trip -- an edit made since is
     newer than this answer, and already has its own timer running. */
  if (gen === studio.gen) {
    studio.project = r.project; studio.derived = r.derived; studio.notes = r.notes || [];
    a.sig = studio_projSig();
    a.armed = a.sig;
  }
  studio.output = r.output;
  a.job = r.job || 0; a.running = true; a.pct = 0;
  studio.seenJob = studio.jobId; studio.watching = -1;
  studio.jobId = a.job;
  studio_drawAll();
  studio_poll();
}

/* The status poll's turn, every two seconds while the Studio is open: an
   edit left waiting -- for a render the user started, a stream, a clip job --
   goes as soon as nothing is in its way. */
function studio_autoTick() {
  const a = studio.auto;
  if (!a.on || !studio.project || !studio.dirty || a.timer || a.running || studio.rendering) return;
  if (Date.now() < a.heldUntil || Date.now() < a.dueAt) return;
  if (studio_projSig() === a.failed) return;
  studio_autoGo();
}

/* The switch, which is the same setting as Settings > Clips. */
async function studio_autoSet(on) {
  const a = studio.auto;
  a.on = !!on; a.armed = ''; a.held = '';
  if (!a.on) {
    clearTimeout(a.timer); a.timer = null;
    if (a.running) API.post('/api/studio/cancel', {}).then(studio_poll);
  }
  studio_drawRenderCard();
  const r = await API.post('/api/settings/save', {values: {'clips.auto_render': a.on}}).catch(() => null);
  if (!r || r.error || (r.errors && r.errors['clips.auto_render'])) toast('Could not save that setting.', 'warn');
}

/* The setting, read once per visit: Settings may have changed it. */
async function studio_autoLoad() {
  const r = await API.get('/api/settings/values').catch(() => null);
  if (!r) return;
  studio.auto.on = r['clips.auto_render'] !== false;
  studio.auto.known = true;
  studio_drawRenderCard();
}

function studio_autoDraw() {
  const a = studio.auto, box = studio_el('studio-auto-state'), cb = studio_el('studio-auto-render');
  if (cb && cb.checked !== a.on) cb.checked = a.on;
  if (!box) return;
  let say = '';
  if (!a.on) say = 'Off · press Render when you want the video.';
  else if (a.running) say = 'Rendering in the background' + (a.pct ? ' · ' + a.pct + '%' : '…');
  else if (a.held && studio.dirty) say = a.held;
  else if (a.timer) say = 'Starts when you stop editing.';
  else if (studio.output && !studio.dirty && !studio.rendering) say = 'Up to date.';
  box.textContent = say;
}

function studio_drawRenderCard() {
  const p = studio.project, d = studio.derived;
  if (!p || !d) return;
  const st = (studio.catalog ? studio.catalog.styles : []).find(s => s.key === p.style);
  studio_el('studio-facts').textContent = studio_dur(d.length) + ' · ' + p.shots.length + ' shots · ' +
    Math.round(d.bpm) + ' BPM grid · ' + (st ? st.label : p.style) + ' · ' +
    (p.format === 'vertical' ? '9:16' : '16:9') + (p.song ? '' : ' · no song');
  studio_drawSync();
  /* Each button names the step it would cross, so "Undo" is never a guess.
     The title is where it goes: the strip is already crowded, and a label
     that changes width makes the row jump on every edit. */
  const ub = studio_el('studio-undo-btn'), rb = studio_el('studio-redo-btn');
  if (ub) {
    ub.disabled = !studio.undo.length;
    const top = studio.undo[studio.undo.length - 1];
    ub.title = top ? 'Undo: ' + top.label : 'There is nothing to undo';
  }
  if (rb) {
    rb.disabled = !studio.redo.length;
    const nxt = studio.redo[studio.redo.length - 1];
    rb.title = nxt ? 'Put back: ' + nxt.label : 'There is nothing to put back';
  }
  studio_histDraw();
  studio_el('studio-show-btn').disabled = !studio.output || studio.dirty && !studio.renderedAt;
  studio_drawWhy();
  studio_pvSync();
  studio_autoArm();
  studio_autoDraw();
}

/* How many things differ from the video, which is what the button counts --
   one per line, however many clicks it took to get there. */
function studio_pendingCount() {
  return studio.pending.length;
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
  } else if (studio.auto.running && !studio.failMsg) {
    /* Not "N changes are not in the video": they are on their way into it,
       and the preview is already showing them. */
    kind = 'busy'; label = 'Render now';
    head = 'Rendering your changes in the background';
    sub = 'The preview is showing them already. Keep editing; a newer edit starts it again.';
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
    /* The player is on the preview whenever this is true (studio_pvWanted),
       so what is missing is the look, not the edit. */
    sub = 'The player is previewing them; rendering adds the effects and colour.';
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
    list.innerHTML = rows.slice(0, 6).map(x => '<li>' + esc(x.label) + '</li>').join('') +
      (rows.length > 6 ? '<li class="studio-pending-more">and ' + (rows.length - 6) + ' more</li>' : '');
  }
  /* The player says it too: the sidebar is not where someone watching looks. */
  const stale = studio_el('studio-stale');
  if (stale) {
    /* Not over the preview: that IS the edits, and says what it leaves out. */
    studio_show('studio-stale', kind === 'stale' && !!studio.output && !studio_pvWanted());
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
    /* A clip can be in the reel with one of its kills not: that is a
       decision too, and says why, kill by kill. */
    const part = sel.filter(x => x.in && x.kills_out && x.kills_out.length);
    const nk = part.reduce((n, x) => n + x.kills_out.length, 0);
    if (nk) {
      h += '<details class="studio-fold" data-fold="kills"' + (studio.folds.kills ? ' open' : '') +
        '><summary>Kills not shown<span class="studio-fold-n">' + nk + '</span></summary>' +
        '<ul class="studio-fold-list">' + part.map(x => '<li><strong>' + esc(x.name) + '</strong> — ' +
          x.kills_out.map(k => esc(studio_secs(k.kill) + ': ' + k.why)).join('; ') + '</li>').join('') +
        '</ul></details>';
    }
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
    fill: p.fill || '', keep_all: !!p.keep_all,
    edited: !!(d && d.edited) || studio.undo.length > 0,
    keep: {cam: p.cam, vfit: p.vfit, handle: p.handle, handle_pos: p.handle_pos,
           outro_len: p.outro_len, overlays: p.overlays, lyrics: p.lyrics}
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
  const box = studio_el('studio-scroll');
  if (!box) return null;
  const t = studio_now();
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
  studio_lockBtn();
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
      ((studio.multi || []).length > 1 && studio.multi.indexOf(i) >= 0 ? ' is-multi' : '') +
      (s.lock ? ' is-locked' : '') +
      (edited[i] ? ' is-edited' : '') +
      '" data-shot="' + i + '" style="left:' + X(r.start) + 'px;top:' + rows.video + 'px;width:' + w.toFixed(1) +
      'px;height:' + STUDIO_ROW.video + 'px;background-image:url(\'' + thumb + '\')" title="' + esc(s.name) + '">' +
      '<span class="st-shot-name">' + (i + 1) + (w > 70 ? ' · ' + esc((c && c.caption) || s.name) : '') + '</span>' +
      '<span class="st-kill" data-kill="' + i + '" style="left:' + ((r.kill_reel - r.start) * pps).toFixed(1) +
      'px" title="Kill — drag to move it"></span>' +
      /* EVERY OTHER KILL IN THE SHOT, as a diamond of its own. Dragging one
         does NOT move the cut: it anchors that kill to where it was dropped
         and the shot is re-timed inside its own length to hit it. That is the
         whole difference -- moving the cut is what pushed every later shot
         down the timeline and knocked the kills after it off the beat. */
      studio_extraKills(s, r, i, pps) +
      '<span class="st-trim-l" data-trim-l="' + i + '" title="Drag to move the cut before this shot: ' +
      'the shot before gives or takes the time, so every kill stays on its beat"></span>' +
      '<span class="st-trim" data-trim="' + i + '" title="Drag to move the cut after this shot: ' +
      'the shot after gives or takes the time. Shift-drag to push everything after it instead"></span></div>';
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

  /* LOCKED SHOTS: one band under each run, a padlock on its first shot. Drawn,
     not hit: a drag on a locked shot is a drag on the shot. */
  studio_lockRuns(p.shots).forEach(run => {
    const a = d.shots[run[0]], b = d.shots[run[1]];
    if (!a || !b) return;
    h += '<div class="st-lockband" style="left:' + X(a.start) + 'px;top:' + (rows.video + STUDIO_ROW.video - 6) +
      'px;width:' + Math.max(4, (b.end - a.start) * pps).toFixed(1) + 'px" title="Shots ' + (run[0] + 1) + '–' + (run[1] + 1) +
      ' are locked together"><span class="st-lockband-ico" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg></span></div>';
  });

  /* transitions: a label where there is room for one, a marker where not */
  p.shots.forEach((s, i) => {
    if (i === 0) return;
    const r = d.shots[i];
    const part = studio_part(s.transition);
    const hard = s.transition === 't01';
    const room = Math.min((r.end - r.start) * pps, (d.shots[i - 1].end - d.shots[i - 1].start) * pps);
    const compact = room < 44;
    h += '<button type="button" class="st-tr' + (hard ? ' is-cut' : '') + (compact ? ' is-compact' : '') +
      (i === studio.sel ? ' is-sel' : '') + '" data-act="studio-select" data-shot="' + i + '" data-part="' + esc(s.transition) + '" style="left:' + X(r.start) +
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
      '" data-act="studio-select" data-shot="' + i + '" data-part="' + esc(ids[0]) +
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
  studio_ioDraw();
  const ph = studio_el('studio-ph');
  const t = studio_now();
  if (ph) ph.style.left = (t * studio.pps).toFixed(1) + 'px';
  const c = studio_el('studio-clock');
  if (c) c.textContent = studio_secs(t);
  if (studio.pv.on) studio_pvBar();
}

function studio_select(i) {
  if (!studio.keepMulti) studio.multi = i >= 0 ? [i] : [];
  studio.keepMulti = false;
  studio.sel = i;
  studio_drawTimeline();
  studio_drawInspector();
}

/* ------------------------------------------------------------ inspector */

/* ONE LINE PER CHOICE, AND A DIALOG TO MAKE IT. These used to be a dropdown
   of "K04 · Freeze" lines and walls of forty checkboxes -- names nobody had
   seen move. Now the inspector says what is chosen, and Change opens the
   picker (studio_fxpOpen), where every option plays. The button carries the
   old control's id, so its <label for> still names it. */
function studio_partCode(id) { return String(id || '').toUpperCase(); }

function studio_select_html(id, kind, value) {
  const part = value ? studio_part(value) : null;
  const name = part && part.id ? (part.label || part.id) : 'None';
  return '<button type="button" class="studio-pick-btn" id="' + id + '" data-act="studio-fxp-open"' +
    ' data-kind="' + esc(kind) + '" data-target="' + id + '" data-part="' + esc(value || '') + '"' +
    ' aria-haspopup="dialog">' +
    '<span class="bin-code">' + esc(studio_partCode(value)) + '</span>' +
    '<span class="studio-pick-name truncate">' + esc(name) + '</span>' +
    '<span class="studio-pick-go">Change…</span></button>';
}

/* Several at once -- a shot's kill effects, the overlays, the pools every shot
   draws from. What is on shows as chips that can each be taken off; adding
   or swapping is the picker's job. */
function studio_multi_html(attr, name, kind, values, skip) {
  const on = (values || []).filter(v => !(skip || []).includes(v));
  const chips = on.map(v => {
    const part = studio_part(v);
    const label = (part && part.label) || v;
    return '<span class="studio-pick-chip" data-part="' + esc(v) + '">' +
      '<span class="bin-code">' + esc(studio_partCode(v)) + '</span>' +
      '<span class="truncate">' + esc(label) + '</span>' +
      '<button type="button" class="studio-pick-x" data-act="studio-fxp-drop" ' + attr + '="' + esc(name) + '"' +
      ' data-kind="' + esc(kind) + '" data-part="' + esc(v) + '"' +
      ' aria-label="Remove ' + esc(label) + '">×</button></span>';
  }).join('');
  return '<div class="studio-pick-multi" ' + attr + '-row="' + esc(name) + '">' +
    (chips || '<span class="muted studio-small">None</span>') +
    '<button type="button" class="btn btn-sm studio-pick-add" data-act="studio-fxp-open" ' + attr + '="' + esc(name) + '"' +
    ' data-kind="' + esc(kind) + '" aria-haspopup="dialog">' + (on.length ? 'Add or change…' : 'Add…') + '</button></div>';
}

function studio_pool_html(kind, values) {
  return studio_multi_html('data-pool', kind, kind, values, kind === 'transition' ? [] : ['t01']);
}

function studio_checks_html(name, kind, values, skip) {
  return studio_multi_html('data-list', name, kind, values, skip);
}

/* ------------------------------------------------------------ the picker */

const FXP_RECENT_KEY = 'autostream.fxRecent';
const FXP_RECENT_MAX = 8;
const FXP_TITLES = {intro: 'an opening', outro: 'an ending', transition: 'a transition', kill: 'kill effects',
  hero: 'hero effects', camera: 'a camera move', speed: 'a speed', grade: 'a colour', overlay: 'overlays'};

/* Recently used, per kind, kept in this browser only: a convenience, never
   the record of anything -- the reel itself is the record. */
function studio_fxpRecent(kind) {
  try {
    const all = JSON.parse(localStorage.getItem(FXP_RECENT_KEY) || '{}');
    return (all[kind] || []).filter(id => studio_part(id).id);
  } catch (e) { return []; }
}

function studio_fxpRemember(kind, ids) {
  try {
    const all = JSON.parse(localStorage.getItem(FXP_RECENT_KEY) || '{}');
    const was = (all[kind] || []).filter(x => ids.indexOf(x) < 0);
    all[kind] = ids.concat(was).slice(0, FXP_RECENT_MAX);
    localStorage.setItem(FXP_RECENT_KEY, JSON.stringify(all));
  } catch (e) { /* private window, blocked storage: recents simply stay empty */ }
}

/* What a list or pool holds right now, straight from the reel. */
function studio_fxpCurrent(st) {
  if (st.make) return studio_pickUnique(studio_template()[st.make]);
  const p = studio.project;
  if (!p) return [];
  if (st.pool) return ((p.pools || {})[st.pool] || []).slice();
  if (st.list === 'overlays') return (p.overlays || []).filter(o => o !== 'o07');
  if (st.list && studio.sel >= 0 && p.shots[studio.sel]) return (p.shots[studio.sel][st.list] || []).slice();
  return [];
}

function studio_fxpOpen(b) {
  const st = {
    kind: b.getAttribute('data-kind'), target: b.getAttribute('data-target') || '',
    list: b.getAttribute('data-list') || '', pool: b.getAttribute('data-pool') || '', q: '',
    opener: b.id || '', openerKey: b.getAttribute('data-list') || b.getAttribute('data-pool') || ''
  };
  /* The Make page owns it when `data-make` is set: it edits the template that is about to be
     planned, not a reel that exists. Several at once only where a drawer can hold several. */
  st.make = b.getAttribute('data-make') || '';
  st.multi = st.make ? (MAKE_MULTI.indexOf(st.kind) >= 0 && b.getAttribute('data-multi') === '1')
                     : !!(st.list || st.pool);
  st.sel = st.make ? studio_fxpCurrent(st)
                   : (st.multi ? studio_fxpCurrent(st) : [b.getAttribute('data-part') || '']);
  st.was = st.sel.slice();
  studio.fxp = st;
  studio_el('studio-fxp-title').textContent = 'Choose ' + (FXP_TITLES[st.kind] || 'an effect');
  studio_el('studio-fxp-lede').textContent = st.multi
    ? 'Click as many as you like, then press Done. Point at one to see it large.'
    : 'Point at one to see it large, click it to use it. It applies as you click, so try '
      + 'as many as you like: Done keeps the last one, Cancel puts back what you had.';
  studio_el('studio-fxp-q').value = '';
  /* THE DIALOG STAYS OPEN UNTIL IT IS DISMISSED, in both modes. A single
     choice used to close it on the first click, so choosing four endings --
     or trying four and keeping the best -- meant opening it four times.
     Cancel still means what it says in both: for a choice that has already
     been applied it puts back what was there when the dialog opened. */
  studio_show('studio-fxp-done', true);
  studio_show('studio-fxp-clear', st.multi && !st.pool && !st.make);
  studio_show('studio-fxp-scrim', true);
  studio_el('studio-fxp-prev').classList.add('is-empty');
  if (!studio.examples && !studio.exLoading) {
    studio.exLoading = true;
    studio_binLoad(false).then(() => {
      studio.exLoading = false;
      if (studio.fxp) { const was = studio.fxp.shown; studio.fxp.shown = ''; studio_fxpDraw(); if (was) studio_fxpPreview(was); }
    });
  }
  studio_fxpDraw();
  const first = st.sel[0] || studio_fxpRecent(st.kind)[0] || (studio_parts(st.kind)[0] || {}).id;
  if (first) studio_fxpPreview(first);
  setTimeout(() => { const q = studio_el('studio-fxp-q'); if (q) q.focus(); }, 0);
}

function studio_fxpMatches(part, q) {
  if (!q) return true;
  const hay = (part.id + ' ' + (part.label || '') + ' ' + (part.blurb || '')).toLowerCase();
  return q.split(/\s+/).every(w => hay.indexOf(w) >= 0);
}

function studio_fxpCard(part, asLead) {
  const st = studio.fxp, on = st.sel.indexOf(part.id) >= 0;
  // A lead card stands for its whole effect: lit when any version of it is chosen.
  const inUse = asLead ? studio_versions(part.kind, part.group).filter(v => st.sel.indexOf(v.id) >= 0).length : 0;
  const lit = on || inUse > 0;
  return '<button type="button" class="bin-card studio-fxp-card' + (lit ? ' is-on' : '') + '" role="option"' +
    ' data-act="studio-fxp-pick" data-part="' + esc(part.id) + '" aria-selected="' + lit + '">' +
    studio_binShot(part.id) +
    (lit ? '<span class="studio-fxp-tick" aria-hidden="true">✓</span>' : '') +
    '<span class="bin-meat"><span class="bin-name">' + esc(asLead ? studio_leadName(part) : (part.label || part.id)) + '</span>' +
    '<span class="bin-blurb">' + esc(part.blurb || '') + '</span>' +
    (asLead ? studio_moreChip(part, 'studio-fxp-group', inUse) : '') + '</span></button>';
}

/* Open one effect's versions in the picker, or ('' ) go back to every effect. */
function studio_fxpGroup(group) {
  if (!studio.fxp) return;
  studio.fxp.group = group || '';
  studio_el('studio-fxp-list').scrollTop = 0;
  studio_fxpDraw();
}

function studio_fxpSkip(st) {
  if (st.list === 'overlays') return ['o07'];
  if (st.pool && st.pool !== 'transition') return ['t01'];
  return [];
}

function studio_fxpDraw() {
  const st = studio.fxp;
  const host = studio_el('studio-fxp-list');
  if (!st || !host) return;
  const top = host.scrollTop;
  const q = (studio_el('studio-fxp-q').value || '').trim().toLowerCase();
  st.q = q;
  const skip = studio_fxpSkip(st);
  const all = studio_parts(st.kind).filter(part => skip.indexOf(part.id) < 0);
  const multi = st.multi ? 'true' : 'false';
  let h = '';
  if (st.group && !q) {
    // ONE EFFECT, EVERY VERSION OF IT -- opened from its card's "versions".
    const vs = all.filter(p => p.group === st.group);
    const lead = vs.filter(p => p.lead)[0] || vs[0];
    h += '<div class="studio-fxp-back"><button type="button" class="btn btn-sm" data-act="studio-fxp-group"' +
      ' data-group="">‹ Every effect</button></div>' +
      '<h3 class="studio-fxp-sec">' + esc(lead ? studio_leadName(lead) : '') + ' · ' + vs.length + ' versions</h3>' +
      '<div class="bin-grid studio-fxp-grid" role="listbox" aria-label="Versions" aria-multiselectable="' + multi + '">' +
      vs.map(p => studio_fxpCard(p, false)).join('') + '</div>';
  } else {
    // A search looks through every version; the plain list shows each effect once.
    const shown = q ? all : all.filter(p => p.lead || !all.some(x => x.lead));
    const hits = shown.filter(part => studio_fxpMatches(part, q));
    const recent = q ? [] : studio_fxpRecent(st.kind).filter(id => skip.indexOf(id) < 0).map(id => studio_part(id));
    if (recent.length) {
      h += '<h3 class="studio-fxp-sec">Recently used</h3>' +
        '<div class="bin-grid studio-fxp-grid" role="listbox" aria-label="Recently used" aria-multiselectable="' + multi + '">' +
        recent.map(p => studio_fxpCard(p, false)).join('') + '</div>';
    }
    h += '<h3 class="studio-fxp-sec">' + (q ? hits.length + ' found' : shown.length + ' effects') + '</h3>';
    h += hits.length
      ? '<div class="bin-grid studio-fxp-grid" role="listbox" aria-label="' + (q ? 'Search results' : 'Every option') + '"' +
        ' aria-multiselectable="' + multi + '">' + hits.map(p => studio_fxpCard(p, !q)).join('') + '</div>'
      : '<p class="muted studio-fxp-none">Nothing matches “' + esc(q) + '”. Try a shorter word, or a code like K04.</p>';
  }
  host.innerHTML = h;
  host.scrollTop = top;
  studio_el('studio-fxp-count').textContent = st.multi
    ? (st.sel.length ? st.sel.length + ' chosen' : 'None chosen') : '';
  studio_binWatch();
}

/* THE ONE UNDER THE POINTER, ON THE STAGE. The card's own example plays there
   at once; the sharp copy is asked for and swapped in when it is ready, at
   the same point in its loop, so a look across ten options is ten looks and
   not ten waits. */
function studio_fxpPreview(id) {
  const part = studio_part(id);
  if (!part || !part.id || !studio.fxp) return;
  if (studio.fxp.shown === id) return;
  studio.fxp.shown = id;
  clearTimeout(studio.fxp.largeTimer);
  const box = studio_el('studio-fxp-prev');
  box.classList.remove('is-empty');
  const shot = studio_el('studio-fxp-prevshot');
  shot.innerHTML = studio_binShot(id);
  shot.classList.remove('is-large');
  studio_el('studio-fxp-prevname').textContent = part.label || id;
  studio_el('studio-fxp-prevcode').textContent = studio_partCode(id);
  studio_el('studio-fxp-prevblurb').textContent = part.blurb || '';
  studio_el('studio-fxp-prevnote').textContent = '';
  const v = box.querySelector('video');
  if (v) { v.preload = 'auto'; v.play().catch(() => {}); }
  studio_fxpStageBtn();
  studio_fxpLarge(id, 0);
}

/* The stage's own button: what a click on the card would do, said in words. */
function studio_fxpStageBtn() {
  const st = studio.fxp, b = studio_el('studio-fxp-stage');
  if (!st || !b) return;
  const on = st.sel.indexOf(st.shown) >= 0;
  b.textContent = st.multi ? (on ? 'Take it out' : 'Add it') : (on ? 'In use' : 'Use this');
  b.disabled = !st.multi && on;
  b.classList.toggle('btn-primary', !on);
  b.setAttribute('aria-pressed', st.multi && on ? 'true' : 'false');
}

async function studio_fxpLarge(id, tries) {
  const st = studio.fxp;
  if (!st || st.shown !== id || !(studio.examples && (studio.examples.examples || {})[id])) return;
  let r = null;
  try { r = await API.post('/api/studio/example/large', {id: id}); } catch (e) { r = null; }
  if (!studio.fxp || studio.fxp.shown !== id || !r) return;
  const note = studio_el('studio-fxp-prevnote');
  if (r.state === 'ready') {
    const old = document.querySelector('#studio-fxp-prevshot video');
    if (!old) return;
    const big = old.cloneNode(false);
    big.src = '/api/studio/example?k=' + encodeURIComponent(SHELL_K) + '&id=' + encodeURIComponent(id) +
      '&size=large&v=' + (r.when || 0);
    big.preload = 'auto';
    big.addEventListener('loadeddata', () => {
      if (!studio.fxp || studio.fxp.shown !== id || !old.isConnected) return;
      try { big.currentTime = old.currentTime || 0; } catch (e) { /* not seekable yet */ }
      old.replaceWith(big);
      big.play().catch(() => {});
      studio_el('studio-fxp-prevshot').classList.add('is-large');
      note.textContent = '';
    }, {once: true});
    big.load();
    return;
  }
  if (r.state === 'making') {
    note.textContent = tries > 2 ? 'Cutting a sharper copy…' : '';
    st.largeTimer = setTimeout(() => studio_fxpLarge(id, tries + 1), 700);
    return;
  }
  /* Held (live, recording, a render running) or impossible (no clips to cut
     it from): the card plays on the stage, and the stage says why it is soft. */
  note.textContent = r.state === 'held' ? (r.why || '')
    : r.state === 'failed' ? 'Shown at card size: ' + (r.error || 'a sharper copy could not be cut.') : '';
}

/* A pointer crossing the list on its way to the stage passes over other
   cards; only one it rests on for a moment takes the stage. Keyboard focus
   takes it at once. */
function studio_fxpHover(e) {
  const t = e.target;
  if (!studio.fxp || !t || !t.closest) return;
  const card = t.closest('#studio-fxp .studio-fxp-card');
  if (!card) return;
  const id = card.getAttribute('data-part');
  clearTimeout(studio.fxp.hoverTimer);
  if (e.type === 'focusin') studio_fxpPreview(id);
  else studio.fxp.hoverTimer = setTimeout(() => studio_fxpPreview(id), 90);
}

function studio_fxpPick(id) {
  const st = studio.fxp;
  if (!st) return;
  if (!st.multi) {
    /* Apply, and stay. `sel` follows the choice so the tick, the stage
       button and the count all say what is in use now; `was` stays as it
       was opened, because it is what the edit is compared against. */
    if (id === st.sel[0]) return;
    studio_fxpRemember(st.kind, [id]);
    st.sel = [id];
    if (st.make) studio_binPick(st.make, id); else studio_inspectorSet(st.target, id);
    studio_fxpDraw();
    studio_fxpStageBtn();
    return;
  }
  const at = st.sel.indexOf(id);
  if (at >= 0) st.sel.splice(at, 1); else st.sel.push(id);
  studio_fxpDraw();
  studio_fxpStageBtn();
}

function studio_fxpDone() {
  const st = studio.fxp;
  if (!st) return;
  if (!st.multi) { studio_fxpClose(); return; }   /* already applied, click by click */
  if ((st.pool || st.make) && !st.sel.length) { toast('Keep at least one to choose from.', 'warn'); return; }
  studio_fxpClose();
  const added = st.sel.filter(id => st.was.indexOf(id) < 0);
  if (added.length) studio_fxpRemember(st.kind, added);
  const same = st.sel.length === st.was.length && st.sel.every(id => st.was.indexOf(id) >= 0);
  if (same) return;
  if (st.make) studio_makeSet(st.make, st.sel.slice());
  else if (st.pool) studio_setPool(st.pool, st.sel.slice());
  else studio_setList(st.list, st.sel.slice());
}

/* Cancel. A single choice has already been applied by the time it is pressed
   -- that is the point of the dialog staying open -- so putting the opening
   value back is the only reading of "cancel" that is true. It goes through
   the same path as any other edit, so the change count simply returns to
   what it was. */
function studio_fxpCancel() {
  const st = studio.fxp;
  if (st && !st.multi && st.sel[0] !== st.was[0]) {
    if (st.make) studio_binPick(st.make, st.was[0]); else studio_inspectorSet(st.target, st.was[0] || '');
  }
  studio_fxpClose();
}

function studio_fxpClose() {
  const st = studio.fxp;
  if (st) { clearTimeout(st.largeTimer); clearTimeout(st.hoverTimer); }
  studio_show('studio-fxp-scrim', false);
  document.querySelectorAll('#studio-fxp video').forEach(v => v.pause());
  studio.fxp = null;
  /* Focus goes back where it came from, so a keyboard user is not dropped at
     the top of the page. The inspector may have been rebuilt meanwhile. */
  if (!st) return;
  const refocus = () => {
    const sel = st.opener ? null : '#studio-insp [data-act="studio-fxp-open"][data-' + (st.pool ? 'pool' : 'list') +
      '="' + st.openerKey + '"]';
    const back = st.opener ? studio_el(st.opener) : document.querySelector(sel);
    if (back) back.focus();
  };
  refocus();
  setTimeout(refocus, 0);           /* again, after an edit has rebuilt the inspector */
}

function studio_fxpDrop(b) {
  const id = b.getAttribute('data-part');
  const pool = b.getAttribute('data-pool') || '', list = b.getAttribute('data-list') || '';
  const vals = studio_fxpCurrent({pool: pool, list: list}).filter(x => x !== id);
  if (pool) {
    if (!vals.length) { toast('Keep at least one to choose from.', 'warn'); return; }
    studio_setPool(pool, vals);
  } else studio_setList(list, vals);
}

/* An edit made from the picker goes through exactly the path the old control
   took, so its name in the "not rendered yet" list and its undo are unchanged. */
function studio_inspectorSet(id, value) {
  studio_inspectorInput({target: {id: id, value: value, checked: false,
                                  closest: () => true, getAttribute: () => null}});
}

function studio_setPool(pool, vals) {
  const label = 'The ' + pool + ' effects to choose from';
  studio_change(pr => { pr.pools = Object.assign({}, pr.pools || {}); pr.pools[pool] = vals; }, label);
  studio_mix(pool, false, label);
}

function studio_setList(list, vals) {
  const i = studio.sel;
  /* The handle has its own switch, so its overlay is not in this list and
     must survive the list being rewritten. */
  studio_change(pr => {
    if (list === 'overlays') pr.overlays = vals.concat((pr.overlays || []).includes('o07') ? ['o07'] : []);
    else pr.shots[i][list] = vals;
  }, list === 'overlays' ? 'Overlays' : studio_shotName(i) + ' · effects', list === 'overlays' ? -1 : i);
}

function studio_fxpKey(e) {
  if (!studio.fxp) return false;
  if (e.key === 'Escape') { e.preventDefault(); studio_fxpClose(); return true; }
  if (e.key === 'Enter' && e.target && e.target.id === 'studio-fxp-q') {
    e.preventDefault();
    const first = document.querySelector('#studio-fxp-list .studio-fxp-card');
    if (first) studio_fxpPick(first.getAttribute('data-part'));
    return true;
  }
  return false;
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

/* THE SONG'S OWN WORDS OVER THE REEL. A look and a typeface: the look owns the
   motion and the colours, the typeface only swaps the font, and "the look's
   own" keeps whichever font that look was copied with. The words are found
   when the reel renders, so whether they were is reported after it. */
/* The steps offered for the three. Named rather than numbered: "Half the
   frame" is a decision, "0.5" is a measurement. */
const LYR_BOXES = [[1, 'The whole frame'], [0.75, 'Three quarters'], [0.5, 'Half the frame'],
                   [0.35, 'A third'], [0.25, 'A quarter']];
const LYR_SIZES = [[1.6, 'Much bigger'], [1.3, 'Bigger'], [1, 'The look’s own'],
                   [0.8, 'Smaller'], [0.6, 'Much smaller'], [0.5, 'Smallest']];
const LYR_ALPHAS = [[1, 'Solid'], [0.85, 'Barely faded'], [0.7, 'Faded'],
                    [0.5, 'Half there'], [0.3, 'A ghost']];

function studio_lyricsGroup(p) {
  const cat = (studio.catalog && studio.catalog.lyrics) || {looks: [], faces: []};
  const ly = p.lyrics || {look: 'off', face: '', clean: false, reveal: 'look',
                          box: 1, size: 1, alpha: 1};
  const look = cat.looks.filter(l => l.key === ly.look)[0];
  const own = look ? cat.faces.filter(f => f.key === look.face)[0] : null;
  const on = !!look;
  const opt = (v, label, sel) => '<option value="' + esc(v) + '"' + (sel ? ' selected' : '') + '>' + esc(label) + '</option>';
  return studio_grp('lyrics', 'Lyrics',
    '<div class="studio-field"><label class="field-label" for="studio-r-lyrics">Look</label>' +
    '<select class="select" id="studio-r-lyrics"' + (p.song ? '' : ' disabled') + '>' +
    opt('off', 'No lyrics', !on) + cat.looks.map(l => opt(l.key, l.label, l.key === ly.look)).join('') + '</select>' +
    '<span class="muted studio-small">' + esc(!p.song ? 'Add a song first: the words are the song’s own.'
      : look ? look.blurb : 'The song’s own words, each on its sung syllable, with the word sung at a kill in red.') + '</span></div>' +
    (on ? '<div class="studio-field"><label class="field-label" for="studio-r-lyricface">Typeface</label>' +
      '<select class="select" id="studio-r-lyricface">' +
      opt('', 'The look’s own' + (own ? ' (' + own.label + ')' : ''), !ly.face) +
      cat.faces.map(f => opt(f.key, f.label, f.key === ly.face)).join('') + '</select>' +
      /* HOW THE WORDS ARRIVE, asked separately from the look. It used to be
         welded to it -- Stamp was one word at a time because Stamp was -- so
         somebody who wanted whole lines in Stamp's type had no way to ask. */
      '<label class="field-label" for="studio-r-lyricreveal">How they arrive</label>' +
      '<select class="select" id="studio-r-lyricreveal">' +
      (cat.reveals || []).map(r => opt(r.key, r.label, r.key === (ly.reveal || 'look'))).join('') + '</select>' +
      '<span class="muted studio-small">' + esc(((cat.reveals || [])
        .filter(r => r.key === (ly.reveal || 'look'))[0] || {}).blurb || '') + '</span>' +
      /* WHERE THE WORDS GO, DRAWN RATHER THAN DESCRIBED. Width and Size are
         two numbers for a rectangle nobody can see; a box is that rectangle,
         put on the picture where the words will be, and it answers "how big"
         by itself. Several boxes deal the lines round them in turn, which is
         why each one wears its number.

         Width and Size stay, folded away, for the reels that have no boxes --
         which is every reel made before this -- and they say plainly that the
         boxes are in charge once there are any. */
      '<span class="field-label">Where the words go</span>' +
      '<div class="field-inline studio-lyrbox-bar">' +
      '<button type="button" class="btn btn-sm" data-act="studio-lyrbox-mode" ' +
      'aria-pressed="' + (studio.lyrBox.on ? 'true' : 'false') + '">' +
      (studio.lyrBox.on ? 'Done with the boxes' : 'Draw boxes on the picture') + '</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-lyrbox-add">Add a box</button>' +
      (studio_lyrBoxes(p).length
        ? '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-lyrbox-clear">Clear</button>'
        : '') +
      '<span class="muted studio-small">' +
      (studio_lyrBoxes(p).length
        ? studio_lyrBoxes(p).length + (studio_lyrBoxes(p).length === 1 ? ' box' : ' boxes') +
          ' — the lines go round them in order'
        : 'None yet') + '</span></div>' +
      (studio_lyrBoxes(p).length
        ? '<span class="muted studio-small">Width and Size are what the boxes decide now. ' +
          'Clear the boxes to go back to them.</span>'
        : '<label class="field-label" for="studio-r-lyricbox">Width</label>' +
          '<select class="select" id="studio-r-lyricbox">' +
          LYR_BOXES.map(b => opt(b[0], b[1], Math.abs(b[0] - (ly.box === undefined ? 1 : ly.box)) < 0.001)).join('') +
          '</select>' +
          '<label class="field-label" for="studio-r-lyricsize">Size</label>' +
          '<select class="select" id="studio-r-lyricsize">' +
          LYR_SIZES.map(b => opt(b[0], b[1], Math.abs(b[0] - (ly.size === undefined ? 1 : ly.size)) < 0.001)).join('') +
          '</select>') +
      '<label class="field-label" for="studio-r-lyricalpha">Opacity</label>' +
      '<select class="select" id="studio-r-lyricalpha">' +
      LYR_ALPHAS.map(b => opt(b[0], b[1], Math.abs(b[0] - (ly.alpha === undefined ? 1 : ly.alpha)) < 0.001)).join('') +
      '</select>' +
      '<label class="studio-check"><input type="checkbox" id="studio-r-lyricclean"' + (ly.clean ? ' checked' : '') + '> Star out swear words</label>' +
      '<span class="muted studio-small">' + esc(studio.lyricsNote ||
        'Synced lyrics are looked up on LRCLIB when the reel renders. A .lrc file named like the song, beside it, is used first.') +
      '</span></div>' +
      /* TIMING BY EAR. A lyric timed on another release of the song comes in
         early or late by the same amount on every line; the player hears it,
         and moves them all at once. */
      '<div class="studio-field"><span class="field-label">Timing</span><span class="field-inline">' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-lyr-shift" data-d="-0.5">−0.5 s</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-lyr-shift" data-d="-0.1">−0.1</button>' +
      '<span class="mono" id="studio-lyr-shift-val">' + ((ly.shift || 0) > 0 ? '+' : '') + Number(ly.shift || 0).toFixed(1) + ' s</span>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-lyr-shift" data-d="0.1">+0.1</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-lyr-shift" data-d="0.5">+0.5 s</button>' +
      (ly.shift ? '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-lyr-shift" data-d="0">Reset</button>' : '') +
      '</span><span class="muted studio-small">Words early? Press +. Late? Press −. Every line moves together.</span></div>' +
      '<div class="studio-field"><span class="field-label">Where</span><div class="ed-row">' +
      studio_grid9('studio-lyr-pos', studio_lyrGrid(studio_lyrPos(p))) +
      '<span class="muted studio-small"><button type="button" class="btn btn-sm" data-act="studio-lyr-move" ' +
      'aria-pressed="' + (studio.lyrMove ? 'true' : 'false') + '">' + (studio.lyrMove ? 'Done moving' : 'Move on the picture') + '</button>' +
      (ly.pos ? ' <button type="button" class="btn btn-ghost btn-sm" data-act="studio-lyr-pos-reset">Back to the look’s place</button>' : '') +
      '</span></div></div>' : ''),
    on ? look.label : 'off');
}

/* WHERE THE WORDS SIT: the centre of the line, as shares of the frame -- what
   clips/lyrics.py draws at. Unset is the look's own place for this shape. The
   nine quick places are a grid of centres, kept clear of the edges, because
   a line of words centred on a corner would hang off it. */
const STUDIO_LYR_X = [0.25, 0.5, 0.75], STUDIO_LYR_Y = [0.15, 0.5, 0.85];
function studio_lyrPos(p) {
  const ly = (p && p.lyrics) || {};
  if (ly.pos) return ly.pos;
  const d = (studio.catalog && studio.catalog.lyrics && studio.catalog.lyrics.default_pos) || {};
  return d[p && p.format === 'vertical' ? 'vertical' : 'landscape'] || [0.5, 0.4];
}
function studio_lyrGrid(pos) {
  const ix = STUDIO_LYR_X.findIndex(v => Math.abs(v - pos[0]) < 0.005);
  const iy = STUDIO_LYR_Y.findIndex(v => Math.abs(v - pos[1]) < 0.005);
  return ix >= 0 && iy >= 0 ? [ix / 2, iy / 2] : null;
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

/* THE SHOT'S FOOTAGE, SEEN (asked 2026-10-17). The inspector said "kill 3.35 s
   into the clip, 6.5 beats before it" and nothing showed which part of the clip
   that was. Now the clip is a bar with a box over the part in the reel and a tick
   on each kill, and the part plays above it.

     an edge of the box   moves that cut -- the same move as Before / After the
                          kill: the shot either side gives or takes the time,
                          so every kill stays on its beat
     the box itself       slides the shot along its clip: the shot keeps its
                          length and its place, so what plays on its kill's beat
                          is a different moment -- and a kill of the clip near
                          the beat pulls the box onto it (Alt to place freely)

   The box stops at the clip's ends and the drag says why. */
const STUDIO_STRIP_THUMBS = 8;
const STUDIO_STRIP_SNAP = 0.25;      // source seconds: a kill this close to the beat takes it

/* Which seconds of its clip a shot plays. Read off the shot at real speed, where
   it is exact and follows a drag frame by frame; off the server's derive for a
   shot with a speed ramp, a stretch or a pinned kill, where only it knows. */
function studio_stripSpan(s, r) {
  const plain = (s.speed === 's00' || !s.speed) && !s.stretch && !(s.anchors && s.anchors.length);
  if (plain || !r || r.source_in === undefined) {
    return [Number(s.kill) - Number(s.pre) * studio_rateAt(r, 'head'),
            Number(s.kill) + (Number(s.duration) - Number(s.pre)) * studio_rateAt(r, 'tail')];
  }
  return [Number(r.source_in), Number(r.source_out)];
}

function studio_stripSummary(s, r) {
  const sp = studio_stripSpan(s, r);
  return 'uses ' + sp[0].toFixed(2) + '–' + sp[1].toFixed(2) + ' s of ' + Number(s.clip_seconds).toFixed(1) + ' s';
}

function studio_stripHtml(s, r, i) {
  const L = Math.max(0.01, Number(s.clip_seconds) || 0.01), sp = studio_stripSpan(s, r);
  const c = studio.clipIndex[s.clip_id] || null;
  let thumbs = '';
  for (let k = 0; k < STUDIO_STRIP_THUMBS; k++) {
    const at = (k + 0.5) * L / STUDIO_STRIP_THUMBS;
    thumbs += '<span class="studio-strip-th" style="background-image:url(\'' +
      studio_media('/api/studio/thumb', s.clip, '&t=' + at.toFixed(2) + '&v=' + ((c && c.mtime) || 0)) + '\')"></span>';
  }
  const pct = x => (Math.max(0, Math.min(1, x / L)) * 100).toFixed(3) + '%';
  const ticks = (s.kills || []).map(k => '<i class="studio-strip-kill' + (Math.abs(k - s.kill) < 0.02 ? ' is-main' : '') +
    '" style="left:' + pct(k) + '" title="Kill at ' + k.toFixed(2) + ' s"></i>').join('');
  return '<div class="studio-strip" id="studio-strip" data-shot="' + i + '">' +
    '<div class="studio-strip-view"><span class="studio-strip-video-slot" id="studio-strip-slot"></span>' +
    '<span class="studio-strip-cap mono" id="studio-strip-cap">' + studio_stripSummary(s, r) + '</span></div>' +
    '<div class="studio-strip-track" id="studio-strip-track" data-strip="seek" title="The whole clip. The box is the part in the reel: press anywhere on the clip to bring the box there.">' +
    thumbs + '<span class="studio-strip-dim is-l" style="width:' + pct(sp[0]) + '"></span>' +
    '<span class="studio-strip-dim is-r" style="left:' + pct(sp[1]) + '"></span>' +
    '<span class="studio-strip-box" id="studio-strip-box" data-strip="slip" style="left:' + pct(sp[0]) +
    ';width:calc(' + pct(sp[1]) + ' - ' + pct(sp[0]) + ')" title="Drag to use another part of the clip">' +
    '<span class="studio-strip-h is-head" data-strip="head" title="Drag to move the cut before this shot"></span>' +
    '<span class="studio-strip-h is-tail" data-strip="tail" title="Drag to move the cut after this shot"></span></span>' +
    ticks + '</div>' +
    '<div class="studio-strip-nudge" role="group" aria-label="Move the moment, keeping the length">' +
    '<span class="muted studio-small">Move the moment</span>' +
    [['-1', '&minus;1 s'], ['-0.1', '&minus;0.1'], ['0.1', '+0.1'], ['1', '+1 s']].map(x =>
      '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-strip-nudge" data-d="' + x[0] + '">' + x[1] + '</button>').join('') +
    '</div>' +
    '<p class="muted studio-small">The length stays the same. Press anywhere on the clip, or drag the box, to use another part of it; ' +
    'drag an edge to show more or less. Ticks are kills; the bright one is on this shot\'s beat.</p></div>';
}

/* ONE PLAYER, KEPT ACROSS REDRAWS. The inspector is redrawn on every edit, and a
   new <video> each time reloaded the clip and started it again; this one moves
   into the new slot and keeps playing. It loops the part the box covers. */
function studio_stripInit() {
  const slot = studio_el('studio-strip-slot'), p = studio.project;
  if (!slot || !p || studio.sel < 0) return;
  const s = p.shots[studio.sel];
  if (!s) return;
  let v = studio.stripVideo;
  if (!v) {
    v = document.createElement('video');
    v.className = 'studio-strip-video';
    v.muted = true; v.playsInline = true; v.preload = 'auto'; v.loop = false;
    v.setAttribute('aria-label', 'The part of the clip in the reel');
    v.addEventListener('timeupdate', () => {
      const span = studio.stripSpan;
      if (span && (v.currentTime >= span[1] || v.currentTime < span[0] - 0.25)) {
        v.currentTime = span[0];
      }
    });
    studio.stripVideo = v;
  }
  slot.replaceWith(v);
  const src = studio_media('/api/clips/video', s.clip);
  const was = studio.stripSpan;
  studio.stripSpan = studio_stripSpan(s, studio.derived && studio.derived.shots[studio.sel]);
  if (v.getAttribute('data-clip') !== s.clip) {
    v.setAttribute('data-clip', s.clip);
    v.src = src;
    v.addEventListener('loadedmetadata', () => { try { v.currentTime = studio.stripSpan[0]; } catch (e) { /* not yet */ } }, {once: true});
  } else if (!was || Math.abs(was[0] - studio.stripSpan[0]) > 0.02) {
    try { v.currentTime = studio.stripSpan[0]; } catch (e) { /* not seekable yet */ }
  }
  if (!studio.pv.playing) v.play().catch(() => {});
}

/* Redraw the box, the dimmed ends and the caption in place: during a drag the
   inspector is not redrawn, so the player keeps playing under the hand. */
function studio_stripPaint() {
  const p = studio.project, i = studio.sel;
  const box = studio_el('studio-strip-box'), track = studio_el('studio-strip-track');
  if (!p || i < 0 || !box || !track) return;
  const s = p.shots[i], r = studio.derived && studio.derived.shots[i];
  const L = Math.max(0.01, Number(s.clip_seconds) || 0.01), sp = studio_stripSpan(s, r);
  const pct = x => (Math.max(0, Math.min(1, x / L)) * 100).toFixed(3) + '%';
  box.style.left = pct(sp[0]);
  box.style.width = 'calc(' + pct(sp[1]) + ' - ' + pct(sp[0]) + ')';
  const dl = track.querySelector('.studio-strip-dim.is-l'), dr = track.querySelector('.studio-strip-dim.is-r');
  if (dl) dl.style.width = pct(sp[0]);
  if (dr) dr.style.left = pct(sp[1]);
  track.querySelectorAll('.studio-strip-kill').forEach((el, k) => {
    el.classList.toggle('is-main', Math.abs((s.kills || [])[k] - s.kill) < 0.02);
  });
  const cap = studio_el('studio-strip-cap');
  if (cap) cap.textContent = studio_stripSummary(s, r);
  studio.stripSpan = sp;
}

function studio_stripDown(e) {
  /* A gesture is never left half-held: whatever press came before is over. */
  studio.strip = null;
  const h = e.target.closest && e.target.closest('#studio-strip [data-strip]');
  if (!h || !studio.project || studio.sel < 0 || e.button !== 0) return false;
  const track = studio_el('studio-strip-track');
  const i = studio.sel, s = studio.project.shots[i];
  let kind = h.getAttribute('data-strip'), jump = 0;
  if (kind === 'seek') {
    /* Anywhere on the clip: the box comes to the press, and a drag carries on from there. */
    const r0 = studio.derived && studio.derived.shots ? studio.derived.shots[i] : null;
    const sp0 = studio_stripSpan(s, r0), tr = track.getBoundingClientRect();
    kind = 'slip';
    jump = (e.clientX - tr.left) / Math.max(1, tr.width) * (Number(s.clip_seconds) || 1) - (sp0[0] + sp0[1]) / 2;
  }
  studio.strip = {kind: kind, jump: jump, i: i, x0: e.clientX, moved: false,
                  w: track.getBoundingClientRect().width, L: Number(s.clip_seconds) || 1,
                  snapshot: JSON.stringify(studio.project), derivedSnap: JSON.stringify(studio.derived),
                  free: e.altKey, pointer: e.pointerId};
  try { track.setPointerCapture(e.pointerId); } catch (err) { /* a mouse works without it */ }
  e.preventDefault();
  /* A press on the bare clip brings the box there at once, before any drag. */
  if (jump) studio_stripMove({clientX: e.clientX, pointerId: e.pointerId, altKey: e.altKey});
  return true;
}

function studio_stripMove(e) {
  const g = studio.strip;
  if (!g || (g.pointer !== undefined && e.pointerId !== g.pointer)) return false;
  const dx = e.clientX - g.x0;
  if (!g.moved && Math.abs(dx) < 3 && !g.jump) return true;
  g.moved = true;
  if (!g.base) g.base = {p: JSON.parse(g.snapshot), d: JSON.parse(g.derivedSnap)};
  const dsrc = dx / Math.max(1, g.w) * g.L + (g.kind === 'slip' ? (g.jump || 0) : 0);
  const p = JSON.parse(g.snapshot), b0 = g.base.p.shots[g.i], r0 = g.base.d.shots[g.i];
  g.limit = '';
  if (g.kind === 'head' || g.kind === 'tail') {
    /* The cut on that side, through the same roll as the timeline's edges and
       the Before / After buttons -- so the limits are theirs too. */
    const end = g.kind;
    const j = end === 'head' ? g.i - 1 : g.i;
    const by = dsrc / studio_rateAt(r0, end);
    const at = studio_cutAt(g.base.d, j);
    const res = studio_rollCut(p, g.base, j, studio_snapTo(at + by) - at);
    g.limit = res.why;
  } else {
    const sp = studio_stripSpan(b0, r0);
    let k = Number(b0.kill) + Math.max(-sp[0], Math.min(g.L - sp[1], dsrc));
    if (dsrc < -sp[0] - 1e-6) g.limit = 'the clip starts there';
    if (dsrc > g.L - sp[1] + 1e-6) g.limit = 'the clip ends there';
    if (!g.free && !e.altKey) {
      const near = (b0.kills || []).filter(x => Math.abs(x - k) <= STUDIO_STRIP_SNAP &&
        x - (b0.kill - sp[0]) >= -1e-6 && x + (sp[1] - b0.kill) <= g.L + 1e-6);
      if (near.length) k = near.reduce((a, x) => Math.abs(x - k) < Math.abs(a - k) ? x : a);
    }
    const s = p.shots[g.i];
    s.kill = Math.round(k * 1000) / 1000;
    /* A pinned kill names a moment of the footage, and the footage under it has
       just moved: the pin would hold the wrong frame. */
    delete s.anchors;
  }
  studio.project = p;
  studio_localDerive();
  studio_drawTimeline();
  studio_stripPaint();
  return true;
}

/* The same slip as the drag, by a set amount: the length stays and the footage under it moves. */
function studio_stripNudge(d) {
  const p0 = studio.project, i = studio.sel;
  if (!p0 || i < 0 || !p0.shots[i] || !isFinite(d)) return;
  const snap = JSON.stringify(p0), r = studio.derived && studio.derived.shots ? studio.derived.shots[i] : null;
  const p = JSON.parse(snap), s = p.shots[i], L = Number(s.clip_seconds) || 1;
  const sp = studio_stripSpan(s, r);
  const by = Math.max(-sp[0], Math.min(L - sp[1], d));
  if (Math.abs(by) < 1e-6) { toast(d < 0 ? 'The clip starts there.' : 'The clip ends there.', 'info'); return; }
  s.kill = Math.round((Number(s.kill) + by) * 1000) / 1000;
  delete s.anchors;
  studio.project = p;
  studio.gen++;
  studio_localDerive();
  const what = studio_shotName(i) + ' · another part of its clip';
  studio_pushUndo(snap, what);
  studio_touched(what, i, studio_diff(JSON.parse(snap), studio.project));
  studio_drawAll();
  studio_check();
}

function studio_stripUp(e) {
  const g = studio.strip;
  if (!g) return false;
  /* Cleared on ANY pointer coming up, not only the one that pressed: a strip
     drag left set routes every later move through here and replays the
     snapshot it was pressed on over whatever was edited since. */
  studio.strip = null;
  if (e && e.type === 'pointercancel') {
    if (g.moved) { studio.project = JSON.parse(g.snapshot); studio_localDerive(); studio_drawAll(); }
    return true;
  }
  if (!g.moved) return true;
  studio.gen++;
  const what = studio_shotName(g.i) + (g.kind === 'slip' ? ' · another part of its clip'
                                        : g.kind === 'head' ? ' · before the kill' : ' · after the kill');
  studio_pushUndo(g.snapshot, what);
  studio_touched(what, g.i, studio_diff(JSON.parse(g.snapshot), studio.project));
  studio_drawAll();
  studio_check();
  if (g.limit) toast('It stopped there: ' + g.limit + '.', 'info');
  return true;
}

/* THE INSPECTOR IN BLOCKS (asked 2026-10-17: "no clear distinction to separate
   different sections like songs and sound, lyrics, opening and ending"). Each
   block has a header saying what it is and what is set in it, and a jump bar at
   the top reaches every one. The settings inside are the same folds as before. */
const STUDIO_SHOT_BLOCKS = [['footage', 'Footage'], ['cut', 'Cut in'], ['kill', 'On the kill'], ['camera', 'Camera']];
const STUDIO_REEL_BLOCKS = [['music', 'Music'], ['words', 'Words'], ['look', 'Look'], ['start', 'Start & end'], ['you', 'You']];
const STUDIO_BLOCK_ICON = {
  footage: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18M8 5v4M16 5v4"/>',
  cut: '<path d="M6 4v16M18 4v16M6 12h12"/>',
  kill: '<circle cx="12" cy="12" r="7"/><path d="M12 2v5M12 17v5M2 12h5M17 12h5"/>',
  camera: '<rect x="3" y="7" width="13" height="10" rx="2"/><path d="M16 11l5-3v8l-5-3z"/>',
  music: '<path d="M9 18V6l11-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  words: '<path d="M4 6h16M4 12h10M4 18h13"/>',
  look: '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 0 0 16z"/>',
  start: '<path d="M5 4v16l7-8zM13 4v16l7-8z"/>',
  you: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/>'
};
function studio_blockName(key) {
  const f = STUDIO_SHOT_BLOCKS.concat(STUDIO_REEL_BLOCKS).filter(b => b[0] === key)[0];
  return f ? f[1] : key;
}
function studio_block(key, summary, body) {
  /* A block that holds one fold IS that fold: its header already names it and
     says what is set, so the fold's own heading goes and it stays open. */
  if (body.split('<details class="ed-group"').length === 2) {
    body = body.replace('<details class="ed-group"', '<details open class="ed-group is-solo"');
  }
  return '<section class="ed-block" id="studio-blk-' + key + '" data-blk="' + key + '">' +
    '<header class="ed-block-head"><svg class="ed-block-ico" viewBox="0 0 24 24" aria-hidden="true">' +
    (STUDIO_BLOCK_ICON[key] || '') + '</svg><span class="ed-block-name">' + esc(studio_blockName(key)) + '</span>' +
    '<span class="ed-block-sum truncate" title="' + esc(summary || '') + '">' + esc(summary || '') + '</span></header>' +
    '<div class="ed-block-body">' + body + '</div></section>';
}
function studio_inspNav(blocks) {
  return '<nav class="ed-blocknav" aria-label="Sections">' + blocks.map(b =>
    '<button type="button" class="ed-blocknav-b" data-act="studio-insp-jump" data-blk="' + b[0] + '">' + esc(b[1]) + '</button>').join('') +
    '</nav>';
}
function studio_partName(id) {
  const part = id ? studio_part(id) : null;
  return part && part.id ? (part.label || part.id) : 'none';
}

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
      studio_inspNav(STUDIO_SHOT_BLOCKS) +
      studio_block('footage', studio_stripSummary(s, r),
        studio_stripHtml(s, r, i) +
        '<p class="muted mono">' + studio_secs(r.start) + ' → ' + studio_secs(r.end) + ' · kill at ' + studio_secs(r.kill_reel) + '</p>' +
      studio_grp('timing', 'Timing',
        '<div class="studio-field"><span class="field-label">Kill</span>' +
        (s.kills.length > 1 ? '<select class="select" id="studio-f-kill">' + kills + '</select>' : '<span class="muted">' + s.kill.toFixed(2) + ' s into the clip</span>') +
        '<span class="field-inline studio-nudge"><button type="button" class="btn btn-ghost btn-sm" data-act="studio-slip" data-d="-0.1">−0.1s</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-slip" data-d="-0.0167">−1f</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-slip" data-d="0.0167">+1f</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-slip" data-d="0.1">+0.1s</button></span></div>' +
        /* BEFORE AND AFTER THE KILL, each moving the cut on that side. Not
           "Run-up" and "Length": those moved the kill off its beat and pushed
           every later shot, and neither is what somebody shortening a lead-up
           means. The kill stays where it plays; the neighbours give and take. */
        '<div class="studio-field"><span class="field-label">Before the kill</span><span class="field-inline">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-cut" data-end="head" data-d="-1" title="Show less before the kill">−</button>' +
        '<span class="mono">' + (s.pre / beat).toFixed(s.pre % beat < 0.01 ? 0 : 1) + ' beats · ' + s.pre.toFixed(2) + ' s</span>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-cut" data-end="head" data-d="1" title="Show more before the kill">+</button></span></div>' +
        '<div class="studio-field"><span class="field-label">After the kill</span><span class="field-inline">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-cut" data-end="tail" data-d="-1" title="Cut away sooner after the kill">−</button>' +
        '<span class="mono">' + ((s.duration - s.pre) / beat).toFixed((s.duration - s.pre) % beat < 0.01 ? 0 : 1) + ' beats · ' + (s.duration - s.pre).toFixed(2) + ' s</span>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-act="studio-cut" data-end="tail" data-d="1" title="Stay longer after the kill">+</button></span></div>' +
        '<p class="muted studio-small">The kill stays on its beat; the shots either side give and take the time. ' +
        'A beat a press, or a quarter of one with “Keep cuts on the beat” off.</p>' +
        '<div class="studio-field"><label class="field-label" for="studio-f-speed">Speed</label>' + studio_select_html('studio-f-speed', 'speed', s.speed) +
        (s.stretch ? '<span class="muted studio-small">Run-up slowed to ' + Number(s.stretch[0]).toFixed(2) + '× so its kill reaches its mark; the last ' +
          Number(s.stretch[1]).toFixed(1) + ' s play as recorded' + (Number(s.stretch[2] || 0) > 0 ? ', after its first frame holds ' + Number(s.stretch[2]).toFixed(1) + ' s' : '') +
          '. Choosing a speed replaces it.</span>' : '') + '</div>')) +
      studio_block('cut', i ? studio_partName(s.transition) : 'opens the reel',
      studio_grp('trans', 'Transition in',
        (i ? '<div class="studio-field">' + studio_select_html('studio-f-trans', 'transition', s.transition) +
          '<input type="range" id="studio-f-tlen" min="0.1" max="1" step="0.05" value="' + (s.tlen || 0.3) + '"' + (s.transition === 't01' ? ' disabled' : '') + ' aria-label="Transition length">' +
          '<button type="button" class="btn btn-ghost btn-sm studio-add-btn" data-act="studio-tr-all">Use this transition on every cut</button></div>'
          : '<span class="muted">The first shot opens the reel.</span>'))) +
      studio_block('kill', (s.fx.length ? s.fx.map(studio_partName).join(' + ') : 'no effect') + (s.hero ? ' · hero' : ''),
      studio_grp('fx', 'Kill effects',
        studio_checks_html('fx', 'kill', s.fx) +
        '<button type="button" class="btn btn-ghost btn-sm studio-add-btn" data-act="studio-fx-all">Use these on every shot</button>',
        s.fx.length ? s.fx.length + ' on' : 'none') +
      studio_grp('hero', 'Hero moment',
        '<label class="studio-check"><input type="checkbox" id="studio-f-hero"' + (s.hero ? ' checked' : '') + '> Make this the hero shot</label>' +
        (s.hero ? studio_checks_html('hero_fx', 'hero', s.hero_fx) +
          '<label class="field-label" for="studio-f-caption">Caption</label><input class="input" id="studio-f-caption" maxlength="40" value="' + esc(s.caption) + '">' : ''),
        s.hero ? 'on' : '')) +
      studio_block('camera', studio_partName(s.camera),
      studio_grp('camera', 'Camera move',
        studio_select_html('studio-f-camera', 'camera', s.camera))) +
      '</div>';
    studio_stripInit();
    return;
  }
  const styles = (studio.catalog ? studio.catalog.styles : []);
  const pools = p.pools || {};
  const cam = p.cam || {source: 'none'};
  const vertical = p.format === 'vertical';
  const showHandle = (p.overlays || []).indexOf('o07') >= 0;
  const outroLen = Number(p.outro_len || 0);
  const G = {};
  G.look = studio_grp('look', 'Look and shape',
      '<div class="studio-field"><span class="field-label">Format</span>' +
      studio_seg('studio-rfmt', 'fmt', p.format, [['landscape', 'Normal 16:9'], ['vertical', 'Vertical 9:16']]) + '</div>' +
      '<div class="studio-field"><span class="field-label">Framing</span>' +
      studio_seg('studio-rfit', 'fit', p.vfit || 'zoom', STUDIO_FITS) +
      '<span class="muted studio-small">' + ((p.vfit || 'zoom') === 'fit'
        ? 'All of the game shows, over a blurred copy of itself.'
        : (p.vfit || 'zoom') === 'near'
        ? 'The middle three quarters of the game, a third taller than a full fit: the minimap and kill feed mostly stay.'
        : (vertical ? 'The middle of the game fills the tall frame; the sides are cropped.' : 'The game fills the frame.')) + '</span></div>' +
      '<div class="studio-field"><label class="field-label" for="studio-r-style">Style</label>' +
      '<select class="select" id="studio-r-style">' + styles.map(s => '<option value="' + esc(s.key) + '"' + (s.key === p.style ? ' selected' : '') + '>' + esc(s.label) + '</option>').join('') + '</select>' +
      '<button type="button" class="btn btn-sm studio-add-btn" data-act="studio-restyle" id="studio-restyle-btn"' + (studio.busy ? ' disabled' : '') + '>Rebuild with this style</button>' +
      '<span class="muted studio-small">Replans every shot. Undo brings your edits back.</span></div>' +
      '<div class="studio-field"><label class="field-label" for="studio-r-grade">Colour</label>' + studio_select_html('studio-r-grade', 'grade', p.grade) +
      '<label class="studio-check"><input type="checkbox" id="studio-r-vignette"' + (p.vignette ? ' checked' : '') + '> Soft vignette</label></div>');
  G.cam = studio_grp('cam', 'Facecam',
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
      cam.source === 'inset' ? 'in the video' : cam.source === 'file' ? 'separate' : 'off');
  G.handle = studio_grp('handle', 'Your handle',
      '<div class="studio-field"><label class="studio-check"><input type="checkbox" id="studio-r-showhandle"' + (showHandle ? ' checked' : '') + '> Show my handle on the reel</label>' +
      '<input class="input" id="studio-r-handle" maxlength="40" placeholder="@yourhandle" value="' + esc(p.handle) + '"></div>' +
      '<div class="studio-field"><span class="field-label">Where</span><div class="ed-row">' + studio_grid9('studio-handle-pos', p.handle_pos || [1, 1]) +
      '<span class="muted studio-small">Or drag it on the picture.</span></div></div>',
      showHandle && p.handle ? p.handle : 'off');
  G.ending = studio_grp('ending', 'Opening and ending',
      '<div class="studio-field"><label class="field-label" for="studio-r-intro">Intro</label>' + studio_select_html('studio-r-intro', 'intro', p.intro) +
      studio_introRow(p) + '</div>' +
      '<div class="studio-field"><label class="field-label" for="studio-r-outro">Ending</label>' + studio_select_html('studio-r-outro', 'outro', p.outro) +
      '<label class="field-label" for="studio-r-outrolen">How long it takes</label>' +
      '<select class="select" id="studio-r-outrolen"' + (p.outro === 'e12' ? ' disabled' : '') + '>' +
      STUDIO_OUTRO_LENS.map(o => '<option value="' + o[0] + '"' + (Math.abs(o[0] - outroLen) < 0.01 ? ' selected' : '') + '>' + o[1] + '</option>').join('') + '</select>' +
      '<span class="muted studio-small">' + (p.outro === 'e12' ? 'A hard cut has no length. Pick a fading ending to make it longer.'
        : outroLen ? 'The picture and the song fade together over ' + outroLen + ' s, and the last frame is held if the footage runs out, so the last kill is never faded.'
        : 'Longer endings fade the picture and the song together, and ease rather than stop.') + '</span></div>');
  G.pools = studio_grp('pools', 'Effects every shot draws from',
      '<p class="muted studio-small">Each kill gets its own mix from these, never the same as the shot before.</p>' +
      '<span class="field-label">Kill effects</span>' + studio_pool_html('kill', pools.kill || []) +
      '<span class="field-label">Transitions</span>' + studio_pool_html('transition', pools.transition || []) +
      '<span class="field-inline">' +
      '<button type="button" class="btn btn-sm" data-act="studio-mix" data-what="kill">Mix kill effects</button>' +
      '<button type="button" class="btn btn-sm" data-act="studio-mix" data-what="transition">Mix transitions</button>' +
      '<button type="button" class="btn btn-sm" data-act="studio-mix" data-what="all">Mix everything</button></span>' +
      '<span class="field-label">Overlays</span>' + studio_checks_html('overlays', 'overlay', (p.overlays || []).filter(o => o !== 'o07'), ['o07']));
  G.lyrics = studio_lyricsGroup(p);
  G.sound = studio_grp('sound', 'Song and sound',
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
      '<label class="studio-check"><input type="checkbox" id="studio-r-duck"' + (p.duck ? ' checked' : '') + '> Duck the music under gunfire</label></div>');
  /* IN THE ORDER A NEW EDITOR THINKS OF THEM, each its own block with a header
     that says what is set. They used to be seven identical folds in a column,
     and nothing said where sound ended and the opening began. */
  const ly = (p.lyrics && p.lyrics.look && p.lyrics.look !== 'off') ? p.lyrics.look : '';
  const song = p.song ? p.song.split(/[\\/]/).pop().replace(/\.[^.]+$/, '').replace(/\s*\[[^\]]*\]\s*$/, '') : '';
  box.innerHTML = tabs + '<div class="card-body studio-insp-body">' +
    '<p class="studio-tip">To change one shot\'s kill effects, speed or transition, click that shot on the timeline. Point at any effect to see it.</p>' +
    studio_inspNav(STUDIO_REEL_BLOCKS) +
    studio_block('music', song ? song + ' · from ' + studio_secs(p.song_offset) : 'no song', G.sound) +
    studio_block('words', ly ? ly.charAt(0).toUpperCase() + ly.slice(1) : 'off', G.lyrics) +
    studio_block('look', (p.format === 'vertical' ? 'Vertical' : 'Normal') + ' · ' + studio_partName(p.grade), G.look + G.pools) +
    studio_block('start', studio_partName(p.intro) + ' → ' + studio_partName(p.outro), G.ending) +
    studio_block('you', [showHandle && p.handle ? p.handle : '', cam.source && cam.source !== 'none' ? 'facecam' : '']
      .filter(Boolean).join(' · ') || 'nothing of yours on it', G.handle + G.cam) +
    '</div>';
}

function studio_inspectorInput(e) {
  const t = e.target;
  if (!t || !studio.project || !t.closest || !t.closest('#studio-insp')) return;
  const i = studio.sel, p = studio.project;
  const s = i >= 0 ? p.shots[i] : null;
  /* Lists and pools are edited in the picker now -- studio_setList and
     studio_setPool. Each edit names itself for the card's list of what is not
     rendered yet. */
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
    'studio-r-duck': () => studio_change(pr => { pr.duck = t.checked; }, 'Ducking the music under gunfire'),
    'studio-r-lyrics': () => studio_change(pr => { pr.lyrics = Object.assign({}, pr.lyrics, {look: t.value}); },
      t.value === 'off' ? 'Lyrics · off' : 'Lyrics · ' + t.options[t.selectedIndex].text),
    'studio-r-lyricface': () => studio_change(pr => { pr.lyrics = Object.assign({}, pr.lyrics, {face: t.value}); },
      'Lyrics typeface · ' + t.options[t.selectedIndex].text),
    'studio-r-lyricreveal': () => studio_change(pr => { pr.lyrics = Object.assign({}, pr.lyrics, {reveal: t.value}); },
      'Lyrics · ' + t.options[t.selectedIndex].text.toLowerCase()),
    'studio-r-lyricbox': () => studio_change(pr => { pr.lyrics = Object.assign({}, pr.lyrics, {box: Number(t.value)}); },
      'Lyrics width · ' + t.options[t.selectedIndex].text.toLowerCase()),
    'studio-r-lyricsize': () => studio_change(pr => { pr.lyrics = Object.assign({}, pr.lyrics, {size: Number(t.value)}); },
      'Lyrics size · ' + t.options[t.selectedIndex].text.toLowerCase()),
    'studio-r-lyricalpha': () => studio_change(pr => { pr.lyrics = Object.assign({}, pr.lyrics, {alpha: Number(t.value)}); },
      'Lyrics opacity · ' + t.options[t.selectedIndex].text.toLowerCase()),
    'studio-r-lyricclean': () => studio_change(pr => { pr.lyrics = Object.assign({}, pr.lyrics, {clean: t.checked}); },
      t.checked ? 'Lyrics · swears starred' : 'Lyrics · as sung')
  };
  if (s === null && t.id && t.id.indexOf('studio-f-') === 0) return;
  if (map[t.id]) map[t.id]();
}

/* ------------------------------------------------------- the tools

   WHAT WAS ACTUALLY MISSING, said plainly rather than counted. This timeline
   has no gaps: the shots are a sequence and the reel is as long as their sum.
   So a trim ALREADY ripples -- shortening a shot pulls everything after it
   back, because there is nowhere for a hole to be. Adding a "ripple tool"
   beside the trim that already ripples would be two names for one behaviour.

   The two the timeline genuinely did not have:

     ROLL   moves the join between two shots. One grows, the next shrinks by
            the same amount, so everything after it stays exactly where it is
            and the reel keeps its length. That is the edit you want when the
            cut is a beat late but the kills after it are on their marks.
     RAZOR  cuts one shot into two, so a long shot can carry its own cut.

   Both are reachable without picking a tool: Ctrl while trimming rolls.
   Escape always returns to Select. */

function studio_tool(name) {
  studio.tool = name;
  document.querySelectorAll('#view-studio .studio-tool').forEach(b => {
    const on = b.getAttribute('data-tool') === name;
    b.classList.toggle('is-on', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  const tl = studio_el('studio-tl');
  if (tl) tl.classList.toggle('is-razor', name === 'razor');
}

/* Where a shot is cut in two. Everything after the cut becomes a second shot
   of the same clip, starting where the first one stopped.

   The server owns the arithmetic, as it does for every drag: this makes the
   obvious edit and /api/studio/check clamps it and hands back every derived
   time. Two implementations of where a kill lands would disagree eventually. */
function studio_razor(i, at) {
  const p = studio.project;
  if (!p || !p.shots[i]) return;
  const s = p.shots[i], beat = p.beat || 0.5;
  /* Neither half may be shorter than a beat: a frame-long shot is not a shot,
     and the planner's own minimum is the beat. */
  if (at < beat || s.duration - at < beat) {
    toast('Too close to the edge — each half has to be at least a beat long.', 'warn');
    return;
  }
  studio_forgetShots();
  studio_change(pr => {
    const a = pr.shots[i], b = JSON.parse(JSON.stringify(a));
    a.duration = Number(at.toFixed(5));
    /* THE KILL GOES WITH THE HALF IT HAPPENS IN. `pre` is how long the shot
       runs before its kill, so the second half starts `at` later in the same
       footage: its kill is that much nearer its own start, and a kill left
       behind in the first half is simply not in the second. */
    b.pre = Number(Math.max(0, a.pre - at).toFixed(5));
    b.duration = Number((s.duration - at).toFixed(5));
    if (a.pre > a.duration) a.pre = Number(a.duration.toFixed(5));
    /* The transition belongs to the join it was chosen for, which is now the
       SECOND half's. A hard cut between the two halves is what a razor makes. */
    a.transition = 't01'; a.tlen = 0;
    pr.shots.splice(i + 1, 0, b);
  }, studio_shotName(i) + ' cut in two', i);
  studio.sel = i + 1;
  studio_drawAll();
}

/* ---------------------------------------------------------- export

   The reel written out as a timeline another editor can open. Which format
   is asked rather than guessed: OTIO is right for Resolve and almost
   everything else, FCP7 XML is what Premiere wants, and someone who needs
   the other one knows which. The sheet the server returns is shown, not
   hidden behind a success toast -- what did NOT survive is the part worth
   reading. */
async function studio_export(kind) {
  if (!studio.project || studio.busy) return;
  studio.busy = true;
  const btn = studio_el('studio-export-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Writing\u2026'; }
  try {
    const r = await API.post('/api/studio/export',
                             {project: studio.project, kind: kind || 'otio'});
    if (!r || !r.ok) { toast((r && r.error) || 'Could not write the timeline.', 'warn'); return; }
    toast('Written to ' + r.folder + ' \u2026 the .export.txt beside it says what survived.', 'ok');
    /* THE SHEET IS SHOWN, NOT HIDDEN BEHIND A TOAST. What did NOT survive
       the trip is the part worth reading, and a toast is gone in four
       seconds. */
    const why = studio_el('studio-why');
    if (why) {
      why.innerHTML = '<details open class="studio-grp">' +
        '<summary>What the other editor will get</summary>' +
        '<pre class="studio-sheet">' + esc(r.sheet || '') + '</pre></details>';
    }
  } finally {
    studio.busy = false;
    if (btn) { btn.disabled = false; btn.textContent = 'Export\u2026'; }
  }
}

/* ------------------------------------------- in, out, marks and shuttle

   None of this changes the reel. In and out say which stretch to watch, a
   mark says "look here", and J/K/L is how every editor in the world moves
   through footage. They are navigation, and they are kept apart from the
   edits for that reason -- see studio.io.

   J and L SHUTTLE rather than toggle: pressed again they go faster, and
   pressed the other way they slow down and then reverse, which is the
   behaviour the keys have everywhere else. K stops. */

const STUDIO_SHUTTLE = [-8, -4, -2, -1, 0, 1, 2, 4, 8];

function studio_shuttle(by) {
  const now = studio.shuttle;
  const i = STUDIO_SHUTTLE.indexOf(now);
  const at = i < 0 ? STUDIO_SHUTTLE.indexOf(0) : i;
  const want = Math.max(0, Math.min(STUDIO_SHUTTLE.length - 1, at + by));
  studio.shuttle = STUDIO_SHUTTLE[want];
  studio_shuttleApply();
}

function studio_shuttleApply() {
  const r = studio.shuttle;
  const v = studio_el('studio-video');
  if (r === 0) {
    if (studio.pv.on) studio_pvPause();
    else if (v && v.src && !v.paused) v.pause();
  } else if (studio.pv.on) {
    /* The preview plays its own clock, so a rate is all it needs; backwards
       is not something two swapped <video>s can do, so it steps instead. */
    studio.pv.rate = Math.abs(r);
    if (r > 0) studio_pvPlay();
    else { studio_pvPause(); studio_seekTo(Math.max(0, studio_now() - 0.5)); }
  } else if (v && v.src) {
    if (r > 0) { v.playbackRate = r; v.play().catch(() => {}); }
    else { v.pause(); v.currentTime = Math.max(0, v.currentTime - 0.5); }
  }
  studio_ioDraw();
}

/* `a` and `b` are set independently, so an out before an in is possible for a
   moment. Read them the way round they end up. */
function studio_ioRange() {
  const {a, b} = studio.io;
  if (a === null || b === null) return null;
  return a <= b ? [a, b] : [b, a];
}

function studio_ioSet(which) {
  const t = Math.max(0, studio_now());
  studio.io[which] = Number(t.toFixed(3));
  studio_ioDraw();
  const r = studio_ioRange();
  toast(which === 'a' ? 'In at ' + studio_secs(t) : 'Out at ' + studio_secs(t),
        r ? 'ok' : 'info');
}

function studio_ioClear() {
  studio.io = {a: null, b: null};
  studio_ioDraw();
}

/* A mark is a time on the reel with a name you can give it later. On the
   project, so it survives a reload and can become a chapter one day. */
function studio_markAdd() {
  const p = studio.project;
  if (!p) return;
  const t = Number(Math.max(0, studio_now()).toFixed(3));
  const have = (p.markers || []).slice();
  /* Pressing M twice on the same frame is one mark, not two. */
  if (have.some(m => Math.abs(Number(m.t || m) - t) < 0.05)) {
    toast('There is already a mark there.', 'info');
    return;
  }
  studio_change(pr => {
    pr.markers = (pr.markers || []).concat([{t: t, label: ''}])
      .sort((x, y) => Number(x.t) - Number(y.t));
  }, 'A mark at ' + studio_secs(t));
}

function studio_markClear() {
  if (!studio.project || !(studio.project.markers || []).length) {
    toast('There are no marks to clear.', 'info');
    return;
  }
  studio_change(pr => { pr.markers = []; }, 'The marks cleared');
}

/* The band and the marks, over the ruler. Drawn from the page's own state and
   the project, so a redraw after any edit keeps them. */
function studio_ioDraw() {
  const host = studio_el('studio-io');
  if (!host) return;
  const p = studio.project;
  const r = studio_ioRange();
  const marks = (p && p.markers) || [];
  let html = '';
  if (r) {
    html += '<span class="st-io-band" style="left:' + (r[0] * studio.pps).toFixed(1) +
            'px;width:' + ((r[1] - r[0]) * studio.pps).toFixed(1) + 'px"></span>';
  }
  if (studio.io.a !== null) {
    html += '<span class="st-io-edge st-io-a" style="left:' +
            (studio.io.a * studio.pps).toFixed(1) + 'px">I</span>';
  }
  if (studio.io.b !== null) {
    html += '<span class="st-io-edge st-io-b" style="left:' +
            (studio.io.b * studio.pps).toFixed(1) + 'px">O</span>';
  }
  marks.forEach((m, i) => {
    const t = Number(m.t || m) || 0;
    html += '<button type="button" class="st-mark" data-act="studio-mark-go" data-n="' + i +
            '" style="left:' + (t * studio.pps).toFixed(1) + 'px" title="' +
            esc(m.label || ('Mark at ' + studio_secs(t))) + '"></button>';
  });
  host.innerHTML = html;
  const lab = studio_el('studio-shuttle-lab');
  if (lab) {
    lab.textContent = studio.shuttle ? (studio.shuttle > 0 ? '\u25B6 ' : '\u25C0 ') +
      Math.abs(studio.shuttle) + '\u00D7' : '';
  }
}

/* ------------------------------------------------------------ dragging */

/* MOVING A CUT, AND NOTHING ELSE.

   Asked for in so many words: "the second shot cuts just before the kill and we
   were showing the lead-up more than the actual kill, so I wanted to shorten the
   lead-up and increase the time after -- but it shifted the whole timeline."
   Measured off the recording that came with it: the tools within reach each moved
   the wrong thing. Run-up and the kill diamond moved the KILL inside a shot that
   stayed put, so it left its beat; Length and the edge drag changed the shot's
   length and pushed every shot after it; and Roll, the one tool meant for this,
   moved the next shot's start without trimming its head, so THAT shot's kill
   slid off its beat by however far the cut went.

   A cut belongs to two shots. Moving it lengthens one and shortens the other by
   the same amount, and the shot that loses time loses it from the side the cut
   is on -- its head, if the cut is before it -- so its kill plays at exactly the
   same moment. Every kill in the reel stays on its beat. Nothing after the two
   shots moves at all.

   The start of the reel is a cut with nothing before it: trimming the first
   shot's head moves reel zero, and the song is moved by the same amount so every
   kill still meets the same moment of the music. */
const STUDIO_MIN_SHOT = 0.25;        // studio.MIN_SHOT: below this a shot is a flicker
const STUDIO_MIN_LEAD = 0.1;         // a cut this close before a kill shows nothing of it
const STUDIO_MIN_AFTER = 0.1;        // ...or this close after
/* Two frames short of the footage, not on it: the server measures what a ramp
   eats more exactly than this can, and a shot cut past its footage is trimmed
   there by a whole beat -- which pushes everything after it, the fault itself. */
const STUDIO_ROOM_MARGIN = 2 / 60;

function studio_rateAt(r, end) {
  const ps = (r && r.pieces) || [];
  if (!ps.length) return 1;
  const pc = end === 'tail' ? ps[ps.length - 1] : ps[0];
  return Math.max(0.05, Number(pc[2]) || 1);
}

/* Footage a shot has but does not use, past its tail or before its head, in
   OUTPUT seconds -- through its speed at that end, because a ramp eats source
   faster than it plays. */
function studio_room(s, r, end) {
  if (!r) return 0;
  const src = end === 'tail' ? (Number(s.clip_seconds) || 0) - (Number(r.source_out) || 0)
                             : (Number(r.source_in) || 0);
  return Math.max(0, src / studio_rateAt(r, end) - STUDIO_ROOM_MARGIN);
}

/* Move the cut after shot j by `by` seconds, later being positive. j = -1 is the
   start of the reel and j = last its end. Measured from `base` -- the project
   and derive as they were before the gesture -- so a drag is one move from
   where it started rather than a compound of every frame it passed through.
   -> {by: what was applied, why: '' or the limit that stopped it}. */
function studio_rollCut(p, base, j, by) {
  const n = p.shots.length;
  const a0 = j >= 0 ? base.p.shots[j] : null, b0 = j + 1 < n ? base.p.shots[j + 1] : null;
  const ar = j >= 0 ? base.d.shots[j] : null, br = j + 1 < n ? base.d.shots[j + 1] : null;
  let lo = -Infinity, hi = Infinity, whyLo = '', whyHi = '';
  const tighten = (side, v, why) => {
    if (side === 'hi' && v < hi) { hi = v; whyHi = why; }
    if (side === 'lo' && v > lo) { lo = v; whyLo = why; }
  };
  if (a0) {
    const name = studio_shotName(j);
    tighten('hi', studio_room(a0, ar, 'tail'), name + ' has no more footage after this');
    tighten('lo', Math.max(STUDIO_MIN_SHOT, a0.pre + STUDIO_MIN_AFTER) - a0.duration,
            'the cut cannot go back past the kill in ' + name);
  }
  if (b0) {
    const name = studio_shotName(j + 1);
    tighten('hi', Math.min(b0.pre - STUDIO_MIN_LEAD, b0.duration - STUDIO_MIN_SHOT),
            'the cut cannot go past the kill in ' + name);
    tighten('lo', -studio_room(b0, br, 'head'), name + ' has no more footage before its kill');
  }
  if (j < 0 && base.p.song) {
    tighten('lo', -(Number(base.p.song_offset) || 0), 'the song cannot start before its first second');
  }
  /* A CUT BETWEEN TWO LOCKED SHOTS DOES NOT MOVE: they are one piece now. */
  if (a0 && b0 && a0.lock && a0.lock === b0.lock) {
    return {by: 0, why: studio_shotName(j) + ' and ' + studio_shotName(j + 1).toLowerCase() +
                        ' are locked together; unlock them to move this cut'};
  }
  /* A CUT JUST BEFORE A LOCKED RUN SLIDES THE RUN (asked 2026-10-17): the shot
     before it changes length and every locked shot after it keeps its own, so
     the reel grows or shrinks by the move. The shot after the run -- if there is
     one -- gives or takes the time at its head, so the rest of the reel stays
     where it was. Locked runs side by side slide together. */
  if (a0 && b0 && b0.lock) {
    lo = -Infinity; hi = Infinity; whyLo = ''; whyHi = '';
    const name = studio_shotName(j);
    tighten('hi', studio_room(a0, ar, 'tail'), name + ' has no more footage after this');
    tighten('lo', Math.max(STUDIO_MIN_SHOT, a0.pre + STUDIO_MIN_AFTER) - a0.duration,
            'the cut cannot go back past the kill in ' + name);
    let e = j + 1;
    while (e + 1 < n && base.p.shots[e + 1].lock) e++;
    const c0 = e + 1 < n ? base.p.shots[e + 1] : null, cr = c0 ? base.d.shots[e + 1] : null;
    if (c0) {
      const cname = studio_shotName(e + 1);
      tighten('hi', Math.min(c0.pre - STUDIO_MIN_LEAD, c0.duration - STUDIO_MIN_SHOT),
              'the locked shots cannot push past the kill in ' + cname);
      tighten('lo', -studio_room(c0, cr, 'head'), cname + ' has no more footage before its kill');
    } else {
      const sh = studio.songShape, songS = sh && Number(sh.seconds);
      if (base.p.song && songS) {
        tighten('hi', songS - (Number(base.p.song_offset) || 0) - Number(base.d.length || 0),
                'the song ends there');
      }
    }
    let got = by, why = '';
    if (lo > hi) { got = 0; why = whyHi || whyLo; }
    else if (by > hi) { got = hi; why = whyHi; }
    else if (by < lo) { got = lo; why = whyLo; }
    got = Math.round(got * 1e5) / 1e5;
    p.shots[j].duration = Math.round((a0.duration + got) * 1e5) / 1e5;
    if (c0) {
      const C = p.shots[e + 1];
      C.duration = Math.round((c0.duration - got) * 1e5) / 1e5;
      C.pre = Math.round((c0.pre - got) * 1e5) / 1e5;
    }
    return {by: got, why: why, slid: true};
  }
  let got = by, why = '';
  if (lo > hi) { got = 0; why = whyHi || whyLo; }
  else if (by > hi) { got = hi; why = whyHi; }
  else if (by < lo) { got = lo; why = whyLo; }
  got = Math.round(got * 1e5) / 1e5;
  const A = j >= 0 ? p.shots[j] : null, B = j + 1 < n ? p.shots[j + 1] : null;
  if (A) A.duration = Math.round((a0.duration + got) * 1e5) / 1e5;
  if (B) {
    B.duration = Math.round((b0.duration - got) * 1e5) / 1e5;
    B.pre = Math.round((b0.pre - got) * 1e5) / 1e5;
  }
  if (j < 0 && base.p.song) p.song_offset = Math.round(((Number(base.p.song_offset) || 0) + got) * 1e4) / 1e4;
  return {by: got, why: why};
}

/* ------------------------------------------------------------ locked shots */

/* [first, last] of every run of shots locked together, in timeline order. */
function studio_lockRuns(shots) {
  const out = [];
  let i = 0;
  while (i < shots.length) {
    const lk = shots[i].lock;
    let j = i;
    while (lk && j + 1 < shots.length && shots[j + 1].lock === lk) j++;
    if (lk && j > i) out.push([i, j]);
    i = j + 1;
  }
  return out;
}

/* A lock holds two or more shots side by side. A shot moved out of the middle of
   a run, or a run cut to one shot, no longer joins anything -- the same rule the
   server keeps (studio.tidy_locks). In place. */
function studio_lockTidy(shots) {
  const seen = {};
  let i = 0;
  while (i < shots.length) {
    const lk = shots[i].lock;
    let j = i;
    while (lk && j + 1 < shots.length && shots[j + 1].lock === lk) j++;
    if (lk) {
      const keep = j > i && !seen[lk];
      if (keep) seen[lk] = true;
      if (!keep) for (let k = i; k <= j; k++) delete shots[k].lock;
    }
    i = j + 1;
  }
}

/* Click picks one shot; shift-click picks the run from the last pick; ctrl-click
   adds or takes away one. */
function studio_pickShot(i, shift, ctrl) {
  const was = (studio.multi && studio.multi.length) ? studio.multi.slice() : (studio.sel >= 0 ? [studio.sel] : []);
  let multi = [i];
  if (shift && studio.sel >= 0) {
    const a = Math.min(studio.sel, i), b = Math.max(studio.sel, i);
    multi = [];
    for (let k = a; k <= b; k++) multi.push(k);
  } else if (ctrl) {
    multi = was.indexOf(i) >= 0 ? was.filter(k => k !== i) : was.concat([i]);
    if (!multi.length) multi = [i];
  }
  studio.multi = multi.sort((a, b) => a - b);
  studio.keepMulti = true;
  studio_select(i);
}

function studio_lockBtn() {
  const b = studio_el('studio-lock-btn'), p = studio.project;
  if (!b) return;
  const multi = studio.multi || [];
  const s = p && studio.sel >= 0 ? p.shots[studio.sel] : null;
  if (multi.length > 1) {
    const a = multi[0] + 1, z = multi[multi.length - 1] + 1;
    b.disabled = false;
    b.textContent = 'Lock shots ' + a + '–' + z;
    b.setAttribute('data-mode', 'lock');
    b.title = 'They move as one when the cut before them moves; the reel gets longer or shorter instead.';
  } else if (s && s.lock) {
    b.disabled = false;
    b.textContent = 'Unlock';
    b.setAttribute('data-mode', 'unlock');
    b.title = 'Let these shots move on their own again';
  } else {
    b.disabled = true;
    b.textContent = 'Lock shots';
    b.setAttribute('data-mode', '');
    b.title = 'Shift-click or Ctrl-click shots on the timeline to pick several';
  }
}

/* Locking is not an edit of the video: nothing renders differently. So it goes
   on the undo list but not on the list of what the video does not show yet. */
function studio_lockAct() {
  const p = studio.project, b = studio_el('studio-lock-btn');
  if (!p || !b) return;
  const mode = b.getAttribute('data-mode');
  const snap = JSON.stringify(p);
  let what = '';
  if (mode === 'lock') {
    const multi = studio.multi || [];
    const a = multi[0], z = multi[multi.length - 1];
    const id = 'L' + Date.now().toString(36).slice(-6);
    for (let k = a; k <= z; k++) p.shots[k].lock = id;
    what = 'Shots ' + (a + 1) + '–' + (z + 1) + ' locked together';
  } else if (mode === 'unlock') {
    const lk = p.shots[studio.sel].lock;
    p.shots.forEach(s => { if (s.lock === lk) delete s.lock; });
    what = 'Shots unlocked';
  } else {
    return;
  }
  studio_lockTidy(p.shots);
  studio_pushUndo(snap, what);
  studio.gen++;
  studio.multi = studio.sel >= 0 ? [studio.sel] : [];
  studio_localDerive();
  studio_drawAll();
  clearTimeout(studio.checkTimer);
  studio.checkTimer = setTimeout(studio_check, 250);
  toast(what + '.', 'info');
}

/* Where the cut after shot j sits on the reel: the time the next one starts. */
function studio_cutAt(d, j) {
  if (j < 0) return 0;
  return j + 1 < d.shots.length ? d.shots[j + 1].start : d.length;
}

/* The kills of this shot that are not the one it is cut around, in the order
   derive() reports them -- which is the order of `s.kills` filtered to the
   footage the shot uses, so the index is the same on both sides. */
function studio_shotKills(s, r) {
  return (s.kills || []).filter(k => k >= r.source_in - 1e-6 && k <= r.source_out + 1e-6);
}

function studio_extraKills(s, r, i, pps) {
  const pinned = {};
  (s.anchors || []).forEach(a => { pinned[a[0].toFixed(3)] = true; });
  const src = studio_shotKills(s, r);
  return (r.kills_reel || []).map((kt, j) => {
    if (Math.abs(kt - r.kill_reel) < 0.02) return '';
    const on = src[j] !== undefined && pinned[src[j].toFixed(3)];
    return '<span class="st-kill is-extra' + (on ? ' is-pinned' : '') +
      '" data-anchor="' + i + ':' + j + '" style="left:' +
      ((kt - r.start) * pps).toFixed(1) + 'px" title="' +
      (on ? 'Pinned here - alt-click to let it float again' :
            'Another kill in this shot - drag it onto a beat') + '"></span>';
  }).join('');
}

function studio_pointerDown(e) {
  if (studio_stripDown(e)) return;
  const tl = studio_el('studio-tracks');
  if (!studio.project || !tl || !tl.contains(e.target) || e.button !== 0) return;
  const trim = e.target.closest('[data-trim]'), kill = e.target.closest('[data-kill]');
  const anchor = e.target.closest('[data-anchor]');
  const trimL = e.target.closest('[data-trim-l]');
  const shot = e.target.closest('.st-shot');
  if (!trim && !trimL && !kill && !anchor && !shot) return;
  let aj = -1;
  let i;
  if (anchor) {
    const bits = anchor.getAttribute('data-anchor').split(':');
    i = Number(bits[0]); aj = Number(bits[1]);
  } else if (trimL) {
    i = Number(trimL.getAttribute('data-trim-l'));
  } else {
    i = Number((trim || kill || shot).getAttribute(trim ? 'data-trim' : kill ? 'data-kill' : 'data-shot'));
  }
  const s = studio.project.shots[i];
  /* ALT-CLICK LETS A PINNED KILL FLOAT AGAIN. Unpinning had to be as cheap as
     pinning, or a mistake costs a rebuild. */
  if (anchor && e.altKey) {
    const r0 = studio.derived.shots[i];
    const src0 = studio_shotKills(s, r0)[aj];
    if (src0 !== undefined && s.anchors && s.anchors.length) {
      const snap = JSON.stringify(studio.project);
      s.anchors = s.anchors.filter(a => Math.abs(a[0] - src0) > 1e-3);
      if (!s.anchors.length) delete s.anchors;
      studio.gen++;
      const what = studio_shotName(i) + ' · the kill floats again';
      studio_pushUndo(snap, what);
      studio_touched(what, i, studio_diff(JSON.parse(snap), studio.project));
      studio.sel = i;
      studio_localDerive();
      studio_drawAll();
      studio_check();
    }
    e.preventDefault();
    return;
  }
  /* THE RAZOR CUTS WHERE YOU CLICK, so it acts on the press and starts no
     drag: a cut that followed the pointer would be a trim with a new name. */
  if (studio.tool === 'razor') {
    const row = (shot || trim || kill).closest('.st-shot') || shot;
    const box = (row || e.target).getBoundingClientRect();
    studio_razor(i, (e.clientX - box.left) / studio.pps);
    e.preventDefault();
    return;
  }
  studio.drag = {kind: trim ? 'trim' : trimL ? 'head' : anchor ? 'anchor' : kill ? 'kill' : 'move',
                 i: i, j: aj, x0: e.clientX, moved: false,
                 /* Shift on the press asks for the old trim: this shot changes
                    length and everything after it moves. Decided on the press
                    and kept -- letting go of Shift halfway through must not
                    turn one into the other under the hand, which would make
                    the reel's length jump mid-gesture. The Roll tool never
                    ripples, which is all that is left for it to mean now that
                    an edge moves the cut by default. */
                 ripple: !!trim && e.shiftKey && studio.tool !== 'roll',
                 /* For a click that turns out not to be a drag: picking shots. */
                 shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey,
                 derivedSnap: JSON.stringify(studio.derived),
                 at: anchor ? (studio.derived.shots[i].kills_reel || [])[aj] : 0,
                 dur: s.duration, pre: s.pre, snapshot: JSON.stringify(studio.project), pointer: e.pointerId};
  /* Captured on the timeline itself, which survives the redraws a drag does. */
  try { tl.setPointerCapture(e.pointerId); } catch (err) { /* no capture, still works with a mouse */ }
  e.preventDefault();
}

function studio_pointerMove(e) {
  if (studio.strip) { studio_stripMove(e); return; }
  const g = studio.drag;
  if (!g || (g.pointer !== undefined && e.pointerId !== g.pointer)) return;
  const dx = e.clientX - g.x0;
  if (!g.moved && Math.abs(dx) < 4) return;
  g.moved = true;
  const p = studio.project, s = p.shots[g.i], dt = dx / studio.pps, beat = p.beat || 0.5;
  if (g.kind === 'trim' && g.ripple) {
    /* THE OLD TRIM, on Shift: this shot changes length and every shot after it
       moves with it. Kept because it is sometimes what is meant -- but it knocks
       every later kill off its beat, so it is no longer what an edge does. */
    s.duration = Math.max(STUDIO_MIN_SHOT, studio_snapTo(g.dur + dt));
    s.pre = Math.min(s.pre, s.duration);
  } else if (g.kind === 'trim' || g.kind === 'head') {
    /* THE CUT MOVES; NOTHING ELSE DOES. See studio_rollCut. Rebuilt from the
       state at the press every time, so the limit a drag runs into is measured
       from where it began and a drag that comes back undoes itself exactly. */
    if (!g.base) g.base = {p: JSON.parse(g.snapshot), d: JSON.parse(g.derivedSnap)};
    const j = g.kind === 'head' ? g.i - 1 : g.i;
    const at = studio_cutAt(g.base.d, j);
    const res = studio_rollCut(p, g.base, j, studio_snapTo(at + dt) - at);
    g.limit = res.why;
    g.rolled = true;
  } else if (g.kind === 'kill') {
    s.pre = Math.max(0, Math.min(s.duration, studio_snapTo(g.pre + dt)));
  } else if (g.kind === 'anchor') {
    /* THE CUT DOES NOT MOVE. Only where this kill plays inside the shot does,
       and the renderer bends the rate to hit it (studio.fit_pieces). Moving
       the cut instead is what pushed every later shot down the timeline and
       knocked the kills after it off the beat. */
    const r = studio.derived.shots[g.i];
    const src = studio_shotKills(s, r)[g.j];
    if (src !== undefined) {
      const reelT = Math.max(r.start + 0.05, Math.min(r.end - 0.05, studio_snapTo(g.at + dt)));
      const out = reelT - r.start;
      s.anchors = (s.anchors || []).filter(a => Math.abs(a[0] - src) > 1e-3);
      s.anchors.push([Math.round(src * 1e4) / 1e4, Math.round(out * 1e4) / 1e4]);
      s.anchors.sort((a, b) => a[1] - b[1]);
      /* Drawn where it was dropped straight away: the real position comes
         back with the server's next derive, and a diamond that springs back
         under the hand reads as the drag having failed. */
      r.kills_reel[g.j] = reelT;
    }
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
      g.i = to; studio.sel = to; g.reordered = true;
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
  if (studio.strip) { studio_stripUp(e); return; }
  const g = studio.drag;
  if (!g || (e && g.pointer !== undefined && e.pointerId !== g.pointer)) return;
  studio.drag = null;
  if (e && e.type === 'pointercancel') {
    /* The browser took the gesture (a touch pan): put the shot back. */
    if (g.moved) { studio.project = JSON.parse(g.snapshot); studio_localDerive(); studio_drawAll(); }
    return;
  }
  if (!g.moved) { studio_pickShot(g.i, g.shift, g.ctrl); return; }
  if (g.reordered) studio_remark(studio.project);
  studio.gen++;
  const moveName = studio_shotName(g.i) +
    (g.kind === 'trim' || g.kind === 'head' ? (g.rolled ? ' · the cut moved' : ' · trimmed, and everything after it moved')
     : g.kind === 'kill' ? ' · the kill moved'
     : g.kind === 'anchor' ? ' · a kill pinned to the beat' : ' moved');
  studio_pushUndo(g.snapshot, moveName);
  studio_touched(moveName, g.i,
                 studio_diff(JSON.parse(g.snapshot), studio.project));
  studio.sel = g.i;
  studio_drawAll();
  studio_check();
  /* SAID, NOT SWALLOWED. A cut that stopped short of where the hand let go
     looks like a drag that did not work unless something says why. */
  if (g.limit) toast('The cut stopped there: ' + g.limit + '.', 'info');
}

/* ------------------------------------------------------------ opening */

async function studio_open(path) {
  const r = await API.get('/api/studio/project?path=' + encodeURIComponent(path));
  if (!r || !r.ok) { toast((r && r.error) || 'Could not open that reel.', 'warn'); return; }
  studio.undo = []; studio.redo = []; studio.sel = -1;
  studio_setProject(r.project, r.derived, r.notes, r.song);
  /* `when` is the file's mtime in SECONDS; the page counts in milliseconds,
     so an opened reel read as rendered 20,000 days ago. */
  studio.output = r.project.output; studio.renderedAt = r.when ? r.when * 1000 : Date.now();
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
  ['clips', 'reels', 'looks', 'timeline', 'song', 'facecam'].forEach(k => {
    studio_show('studio-pane-' + k, k === which);
    const b = studio_el('studio-tab-' + k);
    b.classList.toggle('is-active', k === which);
    b.setAttribute('aria-selected', String(k === which));
  });
  /* Each pane draws itself when it is opened: the reels grid and the
     drawers are the two heaviest things on this page, and neither should be
     built while somebody is picking clips. */
  if (which === 'reels') studio_renderReels();
  if (which === 'looks') { studio_arrangeDraw(); studio_binDraw(); }
  const a = studio_el('studio-sg-audio');
  if (which !== 'song' && a && !a.paused) a.pause();
  if (which !== 'timeline' && studio.pv.playing) studio_pvPause();
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
  if (pl && studio.project) {
    pl.classList.toggle('is-vertical', studio.project.format === 'vertical');
    pl.classList.toggle('is-fit', studio.project.vfit === 'fit' || studio.project.vfit === 'near');
    pl.classList.toggle('is-near', studio.project.vfit === 'near');
    studio_pvBg();
  }
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
}

function studio_fxHover(e) {
  const t = e.target;
  if (!t || !t.closest) return;
  /* The effect and transition marks on the tracks show theirs too. */
  const mark = t.closest('#studio-tracks [data-part]');
  if (mark) { studio_fxPreview(mark.getAttribute('data-part')); return; }
  /* The inspector's choices -- one line per pick, a chip per effect on. */
  const pick = t.closest('#studio-insp .studio-pick-btn[data-part], #studio-insp .studio-pick-chip[data-part]');
  if (pick && pick.getAttribute('data-part')) studio_fxPreview(pick.getAttribute('data-part'));
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
  const lc = studio_el('studio-lyrics-chip');
  if (!fr || !chip) return;
  const on = !!(p && studio.sel < 0 && (p.overlays || []).indexOf('o07') >= 0 && p.handle);
  /* NOT ALWAYS ON. Over a rendered reel the stand-in sat on top of the real
     words; it shows only while the words are being placed -- "Move on the
     picture" pressed, a drag under way, or a move not rendered yet. */
  const lyr = !!(p && studio.sel < 0 && p.lyrics && p.lyrics.look && p.lyrics.look !== 'off' &&
                 (studio.lyrMove || studio.lyrDrag || studio_lyrPending()));
  fr.classList.toggle('hide', !on && !lyr);
  chip.classList.toggle('hide', !on);
  if (lc) lc.classList.toggle('hide', !lyr);
  /* The boxes live on the same picture and move with it, so they are redrawn
     wherever the stand-in is -- including on a window resize. */
  studio_boxDraw();
  const r = studio_videoRect();
  if (!r) return;
  if (lyr && lc) {
    /* Centred where the words will be centred: the render puts the middle of
       the line at this share of the frame. */
    lc.style.fontSize = Math.max(10, r.h * 0.045) + 'px';
    const lp = (studio.lyrDrag && studio.lyrDrag.pos) || studio_lyrPos(p);
    lc.style.left = (r.x + r.w * lp[0] - lc.offsetWidth / 2) + 'px';
    lc.style.top = (r.y + r.h * lp[1] - lc.offsetHeight / 2) + 'px';
  }
  if (!on) return;
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

/* The lyrics, dragged anywhere on the picture. Same shape as the handle's
   drag; the position is the line's centre, held clear of the edges the way
   clips/lyrics.py clamps it. */
function studio_lyrPointer(e) {
  const chip = studio_el('studio-lyrics-chip'), p = studio.project;
  if (!chip || !p) return;
  if (e.type === 'pointerdown') {
    const start = studio_lyrPos(p).slice();
    studio.lyrDrag = {x0: e.clientX, y0: e.clientY, pos: start.slice(), start: start,
                      r: studio_videoRect(), id: e.pointerId};
    try { chip.setPointerCapture(e.pointerId); } catch (err) { /* fine */ }
    e.preventDefault();
    return;
  }
  const g = studio.lyrDrag;
  if (!g || e.pointerId !== g.id || !g.r) return;
  const cl = v => Math.max(0.05, Math.min(0.95, v));
  g.pos = [cl(g.start[0] + (e.clientX - g.x0) / Math.max(1, g.r.w)),
           cl(g.start[1] + (e.clientY - g.y0) / Math.max(1, g.r.h))];
  if (e.type === 'pointermove') { studio_frameDraw(); return; }
  studio.lyrDrag = null;
  const pos = [Math.round(g.pos[0] * 1000) / 1000, Math.round(g.pos[1] * 1000) / 1000];
  if (Math.abs(pos[0] - g.start[0]) + Math.abs(pos[1] - g.start[1]) > 0.002) {
    studio_change(pr => { pr.lyrics = Object.assign({}, pr.lyrics, {pos: pos}); }, 'Lyrics · moved');
  } else studio_frameDraw();
}

/* ------------------------------------------------- the boxes the words go in

   Width and Size asked for two numbers describing a rectangle nobody could
   see. A box IS that rectangle, drawn on the picture where the words will be,
   and it answers "how big" by itself because the type becomes whatever fits.

   More than one box turns placement into an arrangement: the lines are DEALT
   round them in the order they were drawn, so the number on each box is not
   decoration -- it is the thing being chosen. The server does the dealing
   (clips/lyrics.py); this is only where the rectangles are drawn.

   A reel with no boxes behaves exactly as it always did. */

const LYR_BOX_MIN = 0.06;                 /* clips/lyrics.py BOX_SIDE_MIN */
const LYR_BOX_MAX = 6;                    /* clips/lyrics.py BOXES_MAX */

function studio_lyrBoxes(p) {
  const b = p && p.lyrics && p.lyrics.boxes;
  return Array.isArray(b) ? b : [];
}

/* The boxes as the pointer has them this instant: the project's, with
   whatever is being dragged laid over the top. Drawing reads this so a drag
   is seen as it happens, and the project is only written on pointerup. */
function studio_boxNow() {
  const live = studio.lyrBox.drag && studio.lyrBox.drag.boxes;
  return live ? live : studio_lyrBoxes(studio.project).map(b => Object.assign({}, b));
}

function studio_boxDraw() {
  const host = studio_el('studio-lyrboxes'), p = studio.project;
  if (!host) return;
  const lyr = !!(p && p.lyrics && p.lyrics.look && p.lyrics.look !== 'off');
  const on = studio.lyrBox.on && lyr && studio.sel < 0;
  host.classList.toggle('hide', !on);
  if (!on) { host.innerHTML = ''; return; }
  const r = studio_videoRect();
  if (!r) return;
  host.style.left = r.x + 'px'; host.style.top = r.y + 'px';
  host.style.width = r.w + 'px'; host.style.height = r.h + 'px';
  const boxes = studio_boxNow();
  const HANDLES = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];
  host.innerHTML = boxes.map((b, i) => {
    const sel = i === studio.lyrBox.sel;
    const hs = sel ? HANDLES.map(h => '<span class="ed-box-h ed-box-' + h + '" data-bh="' + h +
                                      '" data-bi="' + i + '"></span>').join('') +
                     '<span class="ed-box-h ed-box-rot" data-bh="rot" data-bi="' + i + '" ' +
                     'title="Turn this box"></span>' : '';
    return '<div class="ed-box' + (sel ? ' is-on' : '') + '" data-bi="' + i + '" style="' +
      'left:' + (b.x - b.w / 2) * 100 + '%;top:' + (b.y - b.h / 2) * 100 + '%;' +
      'width:' + b.w * 100 + '%;height:' + b.h * 100 + '%;' +
      'transform:rotate(' + (Number(b.rot) || 0) + 'deg)">' +
      '<span class="ed-box-num">' + (i + 1) + '</span>' + hs + '</div>';
  }).join('') + (boxes.length ? '' :
    '<p class="ed-box-hint">Drag on the picture to draw the first box.</p>');
}

/* One drag: make a box, move it, resize it from a corner, or turn it. The
   project is written once, on pointerup, so the change list counts one edit
   however far the pointer travelled. */
function studio_boxPointer(e) {
  const host = studio_el('studio-lyrboxes'), p = studio.project;
  if (!host || !p || !studio.lyrBox.on) return;
  const st = studio.lyrBox;

  if (e.type === 'pointerdown') {
    const r = studio_videoRect();
    if (!r) return;
    const boxes = studio_lyrBoxes(p).map(b => Object.assign({}, b));
    const h = e.target.closest ? e.target.closest('.ed-box-h') : null;
    const inBox = e.target.closest ? e.target.closest('.ed-box') : null;
    const fx = (e.clientX - r.x) / Math.max(1, r.w), fy = (e.clientY - r.y) / Math.max(1, r.h);
    if (h) {
      st.sel = Number(h.getAttribute('data-bi'));
      st.drag = {how: h.getAttribute('data-bh'), i: st.sel, x0: fx, y0: fy,
                 was: Object.assign({}, boxes[st.sel]), boxes: boxes, r: r, id: e.pointerId};
    } else if (inBox) {
      st.sel = Number(inBox.getAttribute('data-bi'));
      st.drag = {how: 'move', i: st.sel, x0: fx, y0: fy,
                 was: Object.assign({}, boxes[st.sel]), boxes: boxes, r: r, id: e.pointerId};
    } else {
      /* On the empty picture: a new box, sized by the drag. Refused rather
         than silently ignored once there are as many as the render deals. */
      if (boxes.length >= LYR_BOX_MAX) {
        toast('That is as many boxes as a reel deals round. Remove one first.', 'warn');
        return;
      }
      boxes.push({x: fx, y: fy, w: LYR_BOX_MIN, h: LYR_BOX_MIN, rot: 0});
      st.sel = boxes.length - 1;
      st.drag = {how: 'new', i: st.sel, x0: fx, y0: fy,
                 was: {x: fx, y: fy}, boxes: boxes, r: r, id: e.pointerId};
    }
    try { host.setPointerCapture(e.pointerId); } catch (err) { /* fine */ }
    e.preventDefault();
    studio_boxDraw();
    return;
  }

  const g = st.drag;
  if (!g || e.pointerId !== g.id) return;
  const fx = (e.clientX - g.r.x) / Math.max(1, g.r.w);
  const fy = (e.clientY - g.r.y) / Math.max(1, g.r.h);
  const dx = fx - g.x0, dy = fy - g.y0;
  const b = g.boxes[g.i];
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  if (g.how === 'new') {
    b.x = (g.was.x + fx) / 2; b.y = (g.was.y + fy) / 2;
    b.w = Math.max(LYR_BOX_MIN, Math.abs(fx - g.was.x));
    b.h = Math.max(LYR_BOX_MIN, Math.abs(fy - g.was.y));
  } else if (g.how === 'move') {
    b.x = g.was.x + dx; b.y = g.was.y + dy;
  } else if (g.how === 'rot') {
    /* The angle from the box's centre to the pointer, measured from straight
       up, because that is where the knob sits. */
    const cx = g.r.x + g.r.w * b.x, cy = g.r.y + g.r.h * b.y;
    let a = Math.atan2(e.clientX - cx, cy - e.clientY) * 180 / Math.PI;
    if (!e.shiftKey) a = Math.round(a / 5) * 5;           /* Shift for any angle */
    b.rot = clamp(Math.round(a * 10) / 10, -90, 90);
  } else {
    /* A corner or an edge. The pointer's travel is turned into the box's own
       axes first, so a turned box resizes along ITS sides rather than the
       frame's, and the corner opposite the one held stays where it is. */
    const a = (Number(g.was.rot) || 0) * Math.PI / 180;
    const cos = Math.cos(a), sin = Math.sin(a);
    const lx = dx * cos + dy * sin, ly = -dx * sin + dy * cos;
    const sx = g.how.indexOf('e') >= 0 ? 1 : (g.how.indexOf('w') >= 0 ? -1 : 0);
    const sy = g.how.indexOf('s') >= 0 ? 1 : (g.how.indexOf('n') >= 0 ? -1 : 0);
    const w = Math.max(LYR_BOX_MIN, g.was.w + sx * lx);
    const h = Math.max(LYR_BOX_MIN, g.was.h + sy * ly);
    /* Half of what the box grew, pushed back out along its own axes. */
    const mx = sx * (w - g.was.w) / 2, my = sy * (h - g.was.h) / 2;
    b.w = w; b.h = h;
    b.x = g.was.x + mx * cos - my * sin;
    b.y = g.was.y + mx * sin + my * cos;
  }
  /* Held inside the picture by its own half-width, the same rule the server
     applies -- so what is drawn is what will be rendered. */
  b.w = clamp(b.w, LYR_BOX_MIN, 1); b.h = clamp(b.h, LYR_BOX_MIN, 1);
  b.x = clamp(b.x, b.w / 2, 1 - b.w / 2);
  b.y = clamp(b.y, b.h / 2, 1 - b.h / 2);

  if (e.type === 'pointermove') { studio_boxDraw(); return; }
  studio.lyrBox.drag = null;
  const tidy = g.boxes.map(x => ({x: Math.round(x.x * 1e4) / 1e4, y: Math.round(x.y * 1e4) / 1e4,
                                  w: Math.round(x.w * 1e4) / 1e4, h: Math.round(x.h * 1e4) / 1e4,
                                  rot: Number(x.rot) || 0}));
  const name = g.how === 'new' ? 'Lyrics · box ' + (g.i + 1) + ' drawn'
             : g.how === 'move' ? 'Lyrics · box ' + (g.i + 1) + ' moved'
             : g.how === 'rot' ? 'Lyrics · box ' + (g.i + 1) + ' turned'
             : 'Lyrics · box ' + (g.i + 1) + ' resized';
  studio_boxSave(tidy, name);
}

/* Every change to the boxes goes through here: one edit, one line on the
   change list, one undo -- and the background render takes it like any other. */
function studio_boxSave(boxes, label) {
  studio_change(pr => {
    pr.lyrics = Object.assign({}, pr.lyrics, {boxes: boxes});
  }, label);
  studio_boxDraw();
}

function studio_boxAdd() {
  const boxes = studio_lyrBoxes(studio.project).map(b => Object.assign({}, b));
  if (boxes.length >= LYR_BOX_MAX) {
    toast('That is as many boxes as a reel deals round.', 'warn');
    return;
  }
  /* Stepped down the frame rather than stacked on the last one, so a second
     box is visible the moment it appears instead of hiding under the first. */
  const n = boxes.length;
  boxes.push({x: 0.5, y: Math.min(0.85, 0.3 + n * 0.18), w: 0.6, h: 0.14, rot: 0});
  studio.lyrBox.on = true;
  studio.lyrBox.sel = boxes.length - 1;
  studio_boxSave(boxes, 'Lyrics · box ' + boxes.length + ' added');
}

function studio_boxDel(i) {
  const boxes = studio_lyrBoxes(studio.project).map(b => Object.assign({}, b));
  if (i < 0 || i >= boxes.length) return;
  boxes.splice(i, 1);
  studio.lyrBox.sel = Math.min(i, boxes.length - 1);
  studio_boxSave(boxes, boxes.length ? 'Lyrics · a box removed' : 'Lyrics · boxes cleared');
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
        studio_seg('studio-rfit', 'fit', p.vfit || 'zoom', STUDIO_FITS) + '</div>'
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
  studio_change(pr => { pr.cam = Object.assign({}, pr.cam); }, label, -1, true);
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
/* The three ways a 16:9 game fills a 9:16 reel (studio.VFITS). */
const STUDIO_FITS = [['zoom', 'Zoom to fill'], ['fit', 'Fit the whole picture'], ['near', 'Near fit']];

function studio_camLayout(fmt, W, H, cam, fit, has) {
  const even = v => Math.max(2, Math.round(v / 2) * 2);
  const out = {fit: fit === 'fit' || fit === 'near' ? fit : 'zoom', game: [0, 0, W, H], cam: null};
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

/* ADDING CLIPS, PLURAL.

   This took one file and stopped, so somebody with a folder of twenty did
   the whole dance twenty times: open the dialog, choose one, wait, mark the
   kills, save, press Add again. The picker has always been able to offer
   more than one -- Tk has askopenfilenames beside askopenfilename -- and
   nothing here ever asked it to.

   The marker opens on the first and moves to the next on Save, so a batch is
   one pass rather than twenty. */
async function studio_impAdd() {
  const r = await API.post('/api/clips/pick', {kind: 'video', multi: true});
  const chosen = (r && r.paths && r.paths.length)
    ? r.paths : ((r && r.path) ? [r.path] : []);
  if (!chosen.length) return;
  if (r && r.missing && r.missing.length) {
    toast(r.missing.length + ' of those files are no longer there.', 'warn');
  }
  toast(chosen.length === 1
    ? 'Adding ' + studio_baseName(chosen[0])
    : 'Adding ' + chosen.length + ' clips');

  const added = [];
  for (let i = 0; i < chosen.length; i++) {
    const got = await API.post('/api/studio/import', {path: chosen[i]});
    /* ONE BAD FILE DOES NOT STOP THE BATCH. Nineteen imported and the
       twentieth refused is a far better outcome than nothing imported and
       one error about a file nobody can see any more. */
    if (got && got.ok) added.push(got.clip.path);
    else toast((got && got.error) ||
               ('Could not add ' + studio_baseName(chosen[i])), 'warn');
  }
  if (!added.length) return;
  if (added.length > 1) {
    toast('Added ' + added.length + ' clips. Mark each one and press Save to ' +
          'move to the next.', 'ok');
  }
  studio.imp.batch = added.slice();
  studio.imp.at = 0;
  await studio_impOpen(added[0], true);
}

/* The file's own name, without a regex. A character class holding a
   backslash has to survive being written inside a Python string, and the
   first attempt came out as /[/\]/ -- where the backslash escapes the
   bracket and the regex never closes. The JS then did not parse at all. */
function studio_baseName(path) {
  const s = String(path || '');
  const cut = Math.max(s.lastIndexOf('/'), s.lastIndexOf(String.fromCharCode(92)));
  return cut >= 0 ? s.slice(cut + 1) : s;
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
  imp.cutFrom = imp.cutTo = null;
  studio_impNav();
  studio_impCutLabel();
  studio_el('studio-imp-detnote').textContent = '';
  studio_el('studio-imp-msg').textContent = '';
  const v = studio_el('studio-imp-video');
  v.src = studio_media('/api/clips/video', path);
  studio_show('studio-imp-scrim', true);
  studio_impDraw();
}

/* WHICH CLIP OF HOW MANY, and the two buttons that move between them.
   Hidden for a single clip: a "1 of 1" with two dead arrows is three controls
   that cannot do anything. */
function studio_impNav() {
  const imp = studio.imp, n = (imp.batch || []).length;
  studio_show('studio-imp-nav', n > 1);
  studio_show('studio-imp-detectall', n > 1);
  if (n <= 1) return;
  const at = Math.max(0, Math.min(n - 1, imp.at | 0));
  studio_el('studio-imp-count').textContent = (at + 1) + ' of ' + n;
  studio_el('studio-imp-prev').disabled = at <= 0;
  studio_el('studio-imp-next').disabled = at >= n - 1;
  const all = studio_el('studio-imp-detectall');
  if (all) all.textContent = 'Find them in all ' + n;
}

/* Moving off a clip SAVES IT FIRST when anything was marked. Losing marks to
   an arrow press would be the worst possible behaviour for a control whose
   whole purpose is to let you wander back and forth. */
async function studio_impGo(delta) {
  const imp = studio.imp, n = (imp.batch || []).length;
  if (n < 2) return;
  const want = Math.max(0, Math.min(n - 1, (imp.at | 0) + delta));
  if (want === (imp.at | 0)) return;
  if (imp.dirty && !(await studio_impSave(false))) return;
  imp.at = want;
  await studio_impOpen(imp.batch[want], false);
}

/* ---- removing a piece ---- */

function studio_impCutMark(which) {
  const v = studio_el('studio-imp-video'), imp = studio.imp;
  if (!v) return;
  const t = Math.round(v.currentTime * 1000) / 1000;
  if (which === 'from') imp.cutFrom = t; else imp.cutTo = t;
  /* Marked in either order, because somebody who scrubs to the end of the
     bit they dislike and presses "To here" first is not making a mistake. */
  if (imp.cutFrom !== null && imp.cutTo !== null && imp.cutTo < imp.cutFrom) {
    const a = imp.cutFrom; imp.cutFrom = imp.cutTo; imp.cutTo = a;
  }
  studio_impCutLabel();
  studio_impDraw();
}

function studio_impCutClear() {
  studio.imp.cutFrom = studio.imp.cutTo = null;
  studio_impCutLabel();
  studio_impDraw();
}

function studio_impCutLabel() {
  const imp = studio.imp, el = studio_el('studio-imp-cutspan');
  const btn = studio_el('studio-imp-cut');
  const both = imp.cutFrom !== null && imp.cutTo !== null;
  if (el) {
    el.textContent = both
      ? studio_secs(imp.cutFrom) + ' to ' + studio_secs(imp.cutTo) +
        '  (' + (imp.cutTo - imp.cutFrom).toFixed(2) + 's)'
      : (imp.cutFrom !== null ? 'from ' + studio_secs(imp.cutFrom)
         : (imp.cutTo !== null ? 'to ' + studio_secs(imp.cutTo)
            : 'nothing chosen'));
  }
  if (btn) btn.disabled = !both || (imp.cutTo - imp.cutFrom) < 0.05;
}

async function studio_impCut() {
  const imp = studio.imp;
  if (imp.cutFrom === null || imp.cutTo === null) return;
  const len = (imp.cutTo - imp.cutFrom).toFixed(2);
  if (!confirm('Remove ' + len + ' seconds from this clip? The original is kept beside it.')) return;
  const btn = studio_el('studio-imp-cut');
  if (btn) btn.disabled = true;
  studio_el('studio-imp-msg').textContent = 'Removing ' + len + 's...';
  const got = await API.post('/api/studio/import/trim',
                             {path: imp.path, start: imp.cutFrom, end: imp.cutTo});
  if (!got || !got.ok) {
    studio_el('studio-imp-msg').textContent = (got && got.error) || 'Could not cut that out.';
    studio_impCutLabel();
    return;
  }
  /* THE MARKS CAME BACK MOVED. A kill after the piece that went is earlier
     now by exactly its length, and one inside it is gone -- the server did
     that arithmetic, and taking its answer is what keeps the two in step. */
  imp.kills = (got.kills || []).slice();
  imp.seconds = Number(got.seconds) || imp.seconds;
  imp.cutFrom = imp.cutTo = null;
  imp.dirty = false;
  const v = studio_el('studio-imp-video');
  if (v) {
    /* Re-fetched rather than re-seeked: the file behind this URL has been
       replaced, and a cached one would play the old length. */
    v.src = studio_media('/api/clips/video', imp.path) + '&v=' + Date.now();
    v.load();
  }
  studio_el('studio-imp-msg').textContent = '';
  studio_impCutLabel();
  studio_impDraw();
  studio_load(true);
  toast('Removed ' + len + 's. ' + studio_secs(imp.seconds) + ' left.', 'ok');
}

/* ---- the kills, across the whole batch ---- */

async function studio_impDetectAll() {
  const imp = studio.imp, paths = (imp.batch || []).slice();
  if (paths.length < 2) return;
  const gsel = studio_el('studio-imp-game'), opt = gsel.selectedOptions[0];
  const note = studio_el('studio-imp-detnote');
  if (!gsel.value) {
    note.textContent = 'AutoStream has no kill detector for another game. Mark them by hand while it plays.';
    return;
  }
  /* SAVED FIRST. This walks away from the clip on screen and comes back to
     it, and anything marked by hand in between would otherwise be lost to a
     button that says nothing about saving. */
  if (imp.dirty && !(await studio_impSave(false))) return;

  const all = studio_el('studio-imp-detectall');
  if (all) all.disabled = true;
  const game = opt ? opt.getAttribute('data-name') : '';
  let found = 0, failed = 0;
  for (let i = 0; i < paths.length; i++) {
    note.textContent = 'Reading clip ' + (i + 1) + ' of ' + paths.length + '...';
    let st = await API.post('/api/studio/import/detect',
                            {path: paths[i], game_key: gsel.value, game: game});
    while (st && st.state === 'running') {
      await new Promise(r => setTimeout(r, 700));
      st = await API.get('/api/studio/import/detect/status');
    }
    if (!st || st.state !== 'done') { failed++; continue; }
    const kills = (st.kills || []).slice();
    if (!kills.length) continue;
    found++;
    /* WRITTEN AS IT GOES, not collected and saved at the end: a run over
       twenty clips that is cancelled halfway should leave the first ten
       marked rather than nothing. */
    if (paths[i] === imp.path) {
      kills.forEach(k => {
        if (!imp.kills.some(h => Math.abs(h - k) < 0.3)) imp.kills.push(k);
      });
      await studio_impSave(false);
      studio_impDraw();
    } else {
      await API.post('/api/studio/import/save', {path: paths[i], kills: kills});
    }
  }
  if (all) all.disabled = false;
  note.textContent = 'Found kills in ' + found + ' of ' + paths.length + ' clips'
    + (failed ? ', ' + failed + ' could not be read' : '') + '.';
  studio_load(true);
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
  /* THE PIECE THAT WILL GO, drawn where it was chosen. A from/to pair
     shown only as two timestamps is a cut somebody has to picture; the band
     is the only way to see that it covers the wrong thing before pressing
     Remove. */
  if (imp.cutFrom !== null || imp.cutTo !== null) {
    const a = imp.cutFrom === null ? 0 : imp.cutFrom;
    const b = imp.cutTo === null ? dur : imp.cutTo;
    ctx.fillStyle = 'rgba(248,81,73,.28)';
    ctx.fillRect(X(a), 0, Math.max(2, X(b) - X(a)), H);
    ctx.fillStyle = studio_tok('--danger') || '#f85149';
    ctx.fillRect(X(a) - 1, 0, 2, H);
    ctx.fillRect(X(b) - 1, 0, 2, H);
  }
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
  /* STRAIGHT ON TO THE NEXT. Saving one of a batch and being put back on the
     Studio page, to press Add again for a file already imported, is the
     twenty-times dance with extra steps.

     STEPPED THROUGH, NOT CONSUMED. This used to shift the next path off a
     queue, which meant the batch shrank as you went and there was no way
     back to one you had already saved. */
  const n = (imp.batch || []).length;
  if (close && n > 1 && (imp.at | 0) < n - 1) {
    imp.at = (imp.at | 0) + 1;
    studio_load(true);
    await studio_impOpen(imp.batch[imp.at], true);
    const left = n - 1 - imp.at;
    toast(left ? left + ' more in this batch.' : 'Last one.', 'ok');
    return true;
  }
  if (close) studio_impClose(true);
  studio_load(true);
  return true;
}

function studio_impClose(force) {
  const imp = studio.imp;
  if (!force && imp.dirty && !confirm('Close without saving the kills you marked?')) return;
  /* A BATCH THAT SURVIVED BEING DISMISSED would reopen a dialog the user had
     just shut, which is the one thing a Close button must never do. The
     clips are imported either way; only the walk through them stops. */
  imp.batch = []; imp.at = 0;
  imp.cutFrom = imp.cutTo = null;
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
  /* A row in the command list carries the command's id, not an action of its
     own: it runs whatever that command runs, through the one route every
     command takes. */
  document.addEventListener('click', e => {
    const r = e.target.closest ? e.target.closest('[data-pal]') : null;
    if (!r) return;
    const id = r.getAttribute('data-pal');
    studio.pal.sel = Number(r.getAttribute('data-n')) || 0;
    if (studio_cmdWhy(studio_cmd(id))) { studio_palDraw(); studio_cmdRun(id); return; }
    studio_palClose();
    studio_cmdRun(id);
  });
  document.addEventListener('click', e => {
    const b = e.target.closest ? e.target.closest('[data-act^="studio-"]') : null;
    if (!b || !b.closest('#view-studio')) return;
    const act = b.getAttribute('data-act');
    const p = studio.project;
    if (act === 'studio-tab') studio_tab(b.getAttribute('data-tab'));
    else if (act === 'studio-edit-song') studio_tab('song');
    else if (act === 'studio-refresh') studio_load(true);
    else if (act === 'studio-game') studio_openFolder(b.getAttribute('data-game'));
    else if (act === 'studio-open-folder') studio_openFolder(b.getAttribute('data-game'));
    else if (act === 'studio-open-run') studio_openRun(b.getAttribute('data-folder'));
    else if (act === 'studio-crumb') studio_goLib(b.getAttribute('data-to'));
    else if (act === 'studio-only-picked') { studio.onlyPicked = !studio.onlyPicked; studio_libShow(); }
    else if (act === 'studio-match') studio_matchToggle(Number(b.getAttribute('data-match')));
    else if (act === 'studio-reel-fmt') { studio.reelFmt = b.getAttribute('data-fmt'); studio_renderReels(); }
    else if (act === 'studio-reels-more') {
      studio.reelsAll = !studio.reelsAll;
      studio_renderReels();
      /* Folding back up from the bottom of eighty reels leaves the page
         scrolled into the clips; bring the section's top back into view. */
      if (!studio.reelsAll) studio_el('studio-reels').scrollIntoView({block: 'start'});
    }
    else if (act === 'studio-pick') studio_pick(b.getAttribute('data-clip'), e.shiftKey);
    else if (act === 'studio-folder') studio_folderToggle(b.getAttribute('data-folder'));
    else if (act === 'studio-preview') studio_preview(b.getAttribute('data-clip'));
    else if (act === 'studio-preview-close') studio_closeModals();
    else if (act === 'studio-make-cancel') studio_buildCancel();
    else if (act === 'studio-clear') { studio.selected = []; studio.adding = null; studio_syncSelection(); }
    else if (act === 'studio-make') studio_openMake();
    else if (act === 'studio-gd-open') studio_gdOpen();
    else if (act === 'studio-mk-chipfix') {
      const v = document.querySelector('#studio-make [data-act="studio-fmt"][data-fmt="vertical"]');
      if (v) v.click();
    }
    else if (act === 'studio-gd') studio_gdAct(b);
    else if (act === 'studio-style') {
      /* A style is a template: taking one drops the picks dealt over the last. */
      studio.style = b.getAttribute('data-style');
      studio.picks = null;
      studio_mkStale();
      studio_mkDefault();                  /* an untouched part follows the style: see studio_mkDefault */
      studio_renderStyles(); studio_hand(); studio_binDraw();
    }
    else if (act === 'studio-sg-song') studio_sgUseSong(b.getAttribute('data-path'));
    else if (act === 'studio-sg-win') studio_svWin(Number(b.getAttribute('data-win')) || 8);
    else if (act === 'studio-sg-lane') studio_svToggle(b.getAttribute('data-lane'));
    else if (act === 'studio-fav') studio_fav(b.getAttribute('data-clip'));
    else if (act === 'studio-fav-selected') studio_favSelected();
    else if (act === 'studio-bin-pick') studio_binPick(b.getAttribute('data-kind'), b.getAttribute('data-part'));
    else if (act === 'studio-bin-fav') studio_binFav(b.getAttribute('data-part'));
    else if (act === 'studio-bin-group') {
      studio.binOpen = Object.assign({}, studio.binOpen || {});
      const k = b.getAttribute('data-kind'), g = b.getAttribute('data-group') || '';
      studio.binOpen[k] = studio.binOpen[k] === g ? '' : g;
      studio_binDraw();
    }
    else if (act === 'studio-bin-favonly') studio_binFavOnly();
    else if (act === 'studio-shape') studio_shapeNudge(b.getAttribute('data-dial'), Number(b.getAttribute('data-by')));
    else if (act === 'studio-shape-reset') studio_shapeReset();
    else if (act === 'studio-arrange') studio_arrangePick(b.getAttribute('data-how'));
    else if (act === 'studio-pin') studio_pin(b.getAttribute('data-slot'), b.getAttribute('data-clip'));
    else if (act === 'studio-hand-pick') studio_handPick(b.getAttribute('data-kind'), b.getAttribute('data-multi') === '1');
    else if (act === 'studio-set-weight') studio_makeWeight(b.getAttribute('data-kind'), b.getAttribute('data-part'), Number(b.getAttribute('data-d')));
    else if (act === 'studio-set-remove') studio_makeRemove(b.getAttribute('data-kind'), b.getAttribute('data-part'));
    else if (act === 'studio-deal') studio_deal();
    else if (act === 'studio-deal-reset') studio_dealReset();
    else if (act === 'studio-bin-build') studio_binBuild();
    else if (act === 'studio-bin-stop') studio_binStop();
    else if (act === 'studio-song') studio_pickSong();
    else if (act === 'studio-nosong') {
      studio.song = ''; studio.songShape = null; studio_mkStale(); studio_mkKillsDraw(); studio_samplesCheck();
      studio_el('studio-song-name').textContent = 'No song: the clips keep their own sound, cut to a 120 BPM grid.';
      studio_mkDefault();
    }
    else if (act === 'studio-mk-mode') { studio.mk.mode = b.getAttribute('data-mode'); studio_mkStale(); studio_mkDraw(); studio_samplesCheck(); }
    else if (act === 'studio-strip-nudge') studio_stripNudge(Number(b.getAttribute('data-d')));
    else if (act === 'studio-mk-jump') studio_mkJump(b.getAttribute('data-sec'));
    else if (act === 'studio-mk-plan') studio_mkPlan();
    else if (act === 'studio-mk-addmark') studio_mkAddMark();
    else if (act === 'studio-mk-clearmarks') studio_mkClearMarks();
    else if (act === 'studio-mk-delmark') studio_mkDelMark(b.getAttribute('data-id'));
    else if (act === 'studio-mk-nudgemark') studio_mkNudgeMark(b.getAttribute('data-id'), Number(b.getAttribute('data-d')));
    else if (act === 'studio-mk-adddrop') studio_mkAddDrop();
    else if (act === 'studio-mk-cleardrops') studio_mkClearDrops();
    else if (act === 'studio-mk-delsel') studio_mkDelSelected();
    else if (act === 'studio-mk-selall') studio_mkSelAll(true);
    else if (act === 'studio-mk-selnone') studio_mkSelAll(false);
    else if (act === 'studio-mk-pick') studio_mkPick(b.getAttribute('data-id'), !!b.checked);
    else if (act === 'studio-samples-start') studio_samplesStart();
    else if (act === 'studio-samples-stop') studio_samplesStop();
    else if (act === 'studio-fill') { studio.fill = b.getAttribute('data-fill'); studio_fillDraw(); }
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
    else if (act === 'studio-fmt') {
      studio.fmt = b.getAttribute('data-fmt');
      b.parentElement.querySelectorAll('.seg-btn').forEach(x => x.classList.toggle('is-active', x === b));
      studio_mkDefault();
      studio_show('studio-mk-fit', studio.fmt === 'vertical');
      studio_mkChip();
    }
    else if (act === 'studio-mk-fit') {
      studio.vfit = b.getAttribute('data-fit');
      b.parentElement.querySelectorAll('.seg-btn').forEach(x => x.classList.toggle('is-active', x === b));
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
    else if (act === 'studio-redo') studio_redo();
    else if (act === 'studio-tool') studio_tool(b.getAttribute('data-tool'));
    else if (act === 'studio-export' && p) studio_export(b.getAttribute('data-kind'));
    else if (act === 'studio-mark') studio_markAdd();
    else if (act === 'studio-mark-clear') studio_markClear();
    else if (act === 'studio-in') studio_ioSet('a');
    else if (act === 'studio-out') studio_ioSet('b');
    else if (act === 'studio-io-clear') studio_ioClear();
    else if (act === 'studio-mark-go' && p) {
      const m = (p.markers || [])[Number(b.getAttribute('data-n')) || 0];
      if (m) studio_seekTo(Number(m.t || m) || 0);
    }
    else if (act === 'studio-hist') {
      studio.histOpen = !studio.histOpen;
      b.setAttribute('aria-expanded', studio.histOpen ? 'true' : 'false');
      studio_histDraw();
    }
    else if (act === 'studio-hist-back') studio_histGo(Number(b.getAttribute('data-n')) || 0, 0);
    else if (act === 'studio-hist-fwd') studio_histGo(0, Number(b.getAttribute('data-n')) || 0);
    else if (act === 'studio-palette') studio_palOpen();
    else if (act === 'studio-keys') studio_keysOpen();
    else if (act === 'studio-pal-close') studio_palClose();
    else if (act === 'studio-keys-close') studio_show('studio-keys-scrim', false);
    else if (act === 'studio-show') { if (studio.output && typeof clip_reveal === 'function') clip_reveal(studio.output); }
    else if (act === 'studio-play') studio_toggle();
    else if (act === 'studio-pv-mute') { studio.pv.muted = !studio.pv.muted; studio_pvLevels(); }
    else if (act === 'studio-pv-full') studio_pvFull();
    else if (act === 'studio-zoom') {
      const z = Number(b.getAttribute('data-z'));
      if (z === 0) { studio_fit(); studio_drawTimeline(); }
      else studio_zoomAt(studio.pps * (z > 0 ? 1.5 : 1 / 1.5), studio_anchorX());
    }
    else if (act === 'studio-seek') {
      const box = b.getBoundingClientRect();
      studio_seekTo((e.clientX - box.left) / studio.pps);
    }
    else if (act === 'studio-select') studio_select(Number(b.getAttribute('data-shot')));
    else if (act === 'studio-move' && p) {
      const d = Number(b.getAttribute('data-d')), i = studio.sel, j = i + d;
      if (j < 0 || j >= p.shots.length) return;
      studio_forgetShots();
      studio_change(pr => { const t = pr.shots[i]; pr.shots[i] = pr.shots[j]; pr.shots[j] = t; studio_remark(pr); },
                    'Shots reordered');
      studio.sel = j; studio_drawAll();
    }
    else if (act === 'studio-remove' && p) {
      if (p.shots.length <= 1) { toast('A reel needs at least one shot.', 'warn'); return; }
      const i = studio.sel;
      const gone = studio_shotName(i);
      studio_forgetShots();
      studio_change(pr => { pr.shots.splice(i, 1); studio_remark(pr); }, gone + ' removed');
      studio.sel = Math.min(i, p.shots.length - 1); studio_drawAll();
    }
    else if (act === 'studio-lock' && p) studio_lockAct();
    else if (act === 'studio-insp-jump') {
      const blk = studio_el('studio-blk-' + b.getAttribute('data-blk'));
      if (blk) blk.scrollIntoView({block: 'start', behavior: 'smooth'});
    }
    else if (act === 'studio-slip' && p) {
      const d = Number(b.getAttribute('data-d')), i = studio.sel;
      studio_change(pr => { const s = pr.shots[i]; s.kill = Math.max(0, Math.min(s.clip_seconds, s.kill + d)); },
                    studio_shotName(i) + ' · where the kill is', i);
    }
    else if (act === 'studio-cut' && p) {
      const end = b.getAttribute('data-end'), d = Number(b.getAttribute('data-d')), i = studio.sel;
      const beat = p.beat || 0.5;
      const step = studio_el('studio-snap').checked ? beat : beat / 4;
      /* More BEFORE the kill is the cut before it moving earlier; more AFTER is
         the cut after it moving later. */
      const j = end === 'head' ? i - 1 : i, by = end === 'head' ? -d * step : d * step;
      const base = {p: JSON.parse(JSON.stringify(p)), d: JSON.parse(JSON.stringify(studio.derived))};
      const trial = studio_rollCut(JSON.parse(JSON.stringify(p)), base, j, by);
      if (Math.abs(trial.by) < 1e-6) { toast('That cut cannot move: ' + (trial.why || 'nothing to give') + '.', 'warn'); }
      else {
        studio_change(pr => { studio_rollCut(pr, base, j, by); },
                      studio_shotName(i) + (end === 'head' ? ' · before the kill' : ' · after the kill'), i);
        if (trial.why) toast('Moved as far as it can: ' + trial.why + '.', 'info');
      }
    }
    else if (act === 'studio-offset' && p) {
      const d = Number(b.getAttribute('data-d')), beat = p.beat || 0.5;
      studio_change(pr => { pr.song_offset = Math.max(0, pr.song_offset + d * beat); }, 'Where the song starts');
    }
    else if (act === 'studio-rfmt' && p) studio_change(pr => { pr.format = b.getAttribute('data-fmt'); },
      'Format · ' + (b.getAttribute('data-fmt') === 'vertical' ? '9:16' : '16:9'));
    else if (act === 'studio-rfit' && p) studio_change(pr => { pr.vfit = b.getAttribute('data-fit'); },
      'Framing · ' + ({fit: 'fit the whole picture', near: 'near fit'}[b.getAttribute('data-fit')] || 'zoom to fill'));
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
    else if (act === 'studio-lyr-pos' && p) studio_change(pr => {
      const x = STUDIO_LYR_X[Math.round(Number(b.getAttribute('data-x')) * 2)];
      const y = STUDIO_LYR_Y[Math.round(Number(b.getAttribute('data-y')) * 2)];
      pr.lyrics = Object.assign({}, pr.lyrics, {pos: [x, y]});
    }, 'Lyrics · moved');
    else if (act === 'studio-lyr-shift' && p) studio_change(pr => {
      const d = Number(b.getAttribute('data-d'));
      const was = Number((pr.lyrics || {}).shift || 0);
      const now = d === 0 ? 0 : Math.max(-5, Math.min(5, Math.round((was + d) * 100) / 100));
      pr.lyrics = Object.assign({}, pr.lyrics, {shift: now});
    }, 'Lyrics · timing');
    else if (act === 'studio-lyr-move' && p) {
      studio.lyrMove = !studio.lyrMove;
      studio_drawInspector();
      studio_frameDraw();
    }
    else if (act === 'studio-lyrbox-mode' && p) {
      studio.lyrBox.on = !studio.lyrBox.on;
      /* The stand-in and the boxes answer the same question two ways; having
         both on the picture at once is two lots of "the words go here". */
      if (studio.lyrBox.on) studio.lyrMove = false;
      studio_drawInspector();
      studio_frameDraw();
    }
    else if (act === 'studio-lyrbox-add' && p) studio_boxAdd();
    else if (act === 'studio-lyrbox-clear' && p) {
      studio.lyrBox.sel = -1;
      studio_boxSave([], 'Lyrics · boxes cleared');
      studio_drawInspector();
    }
    else if (act === 'studio-lyr-pos-reset' && p) studio_change(pr => {
      pr.lyrics = Object.assign({}, pr.lyrics, {pos: null});
    }, 'Lyrics · back to the look’s place');
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
    else if (act === 'studio-imp-edit') {
      /* One clip opened from the library is a batch of one, so the arrows
         and "find them in all" stay hidden rather than describing a batch
         that is not there. */
      studio.imp.batch = [b.getAttribute('data-path')];
      studio.imp.at = 0;
      studio_impOpen(b.getAttribute('data-path'), false);
    }
    else if (act === 'studio-imp-play') { const v = studio_el('studio-imp-video'); if (v.paused) v.play().catch(() => {}); else v.pause(); }
    else if (act === 'studio-imp-step') { const v = studio_el('studio-imp-video'); v.pause(); v.currentTime = Math.max(0, v.currentTime + Number(b.getAttribute('data-d'))); }
    else if (act === 'studio-imp-mark') studio_impMark();
    else if (act === 'studio-imp-clear') { studio.imp.kills = []; studio.imp.dirty = true; studio_impDraw(); }
    else if (act === 'studio-imp-drop') { e.stopPropagation(); studio.imp.kills.splice(Number(b.getAttribute('data-i')), 1); studio.imp.sel = -1; studio.imp.dirty = true; studio_impDraw(); }
    else if (act === 'studio-imp-seek') { const i = Number(b.getAttribute('data-i')); studio.imp.sel = i; const v = studio_el('studio-imp-video'); v.pause(); v.currentTime = studio.imp.kills[i]; studio_impDraw(); }
    else if (act === 'studio-imp-preset') { studio_el('studio-imp-name').value = b.getAttribute('data-t'); studio.imp.dirty = true; }
    else if (act === 'studio-imp-detect') studio_impDetect();
    else if (act === 'studio-imp-save') studio_impSave(true);
    else if (act === 'studio-imp-prev') studio_impGo(-1);
    else if (act === 'studio-imp-next') studio_impGo(1);
    else if (act === 'studio-imp-cutfrom') studio_impCutMark('from');
    else if (act === 'studio-imp-cutto') studio_impCutMark('to');
    else if (act === 'studio-imp-cut') studio_impCut();
    else if (act === 'studio-imp-cutclear') studio_impCutClear();
    else if (act === 'studio-imp-detectall') studio_impDetectAll();
    else if (act === 'studio-imp-close') studio_impClose(false);
    else if (act === 'studio-restyle' && p) studio_restyle();
    else if (act === 'studio-mix' && p) studio_mix(b.getAttribute('data-what'), true);
    else if (act === 'studio-fxp-open' && p) studio_fxpOpen(b);
    else if (act === 'studio-fxp-pick') studio_fxpPick(b.getAttribute('data-part'));
    else if (act === 'studio-fxp-group') studio_fxpGroup(b.getAttribute('data-group') || '');
    else if (act === 'studio-fxp-stage') { if (studio.fxp && studio.fxp.shown) studio_fxpPick(studio.fxp.shown); }
    else if (act === 'studio-fxp-done') studio_fxpDone();
    else if (act === 'studio-fxp-cancel') studio_fxpCancel();
    else if (act === 'studio-fxp-clear' && studio.fxp) { studio.fxp.sel = []; studio_fxpDraw(); }
    else if (act === 'studio-fxp-drop' && p) studio_fxpDrop(b);
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
  document.addEventListener('input', e => { if (e.target && e.target.id === 'studio-gd-name') studio.gd.name = e.target.value; });
  /* The inspector's groups remember whether they are open (toggle does not
     bubble, so it is caught on the way down). */
  document.addEventListener('toggle', e => {
    const d = e.target;
    if (d && d.matches && d.matches('#studio-insp details.ed-group')) studio.grpOpen[d.getAttribute('data-grp')] = d.open;
  }, true);
  document.addEventListener('mouseover', studio_fxHover);
  document.addEventListener('focusin', studio_fxHover);
  document.addEventListener('mouseover', studio_fxpHover);
  document.addEventListener('focusin', studio_fxpHover);
  const fq = studio_el('studio-fxp-q');
  if (fq) fq.addEventListener('input', studio_fxpDraw);
  ['pointerdown', 'pointermove', 'pointerup', 'pointercancel'].forEach(ev => {
    const chip = studio_el('studio-handle-chip');
    if (chip) chip.addEventListener(ev, studio_handlePointer);
    const lchip = studio_el('studio-lyrics-chip');
    if (lchip) lchip.addEventListener(ev, studio_lyrPointer);
    const lbox = studio_el('studio-lyrboxes');
    if (lbox) lbox.addEventListener(ev, studio_boxPointer);
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
  const mkk = studio_el('studio-mk-kills');
  if (mkk) ['pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'dblclick'].forEach(ev => mkk.addEventListener(ev, studio_mkKillPointer));
  const vws = document.getElementById('views');
  if (vws) vws.addEventListener('scroll', studio_mkSpy, {passive: true});
  const mka = studio_el('studio-mk-audio');
  if (mka) ['play', 'pause', 'timeupdate', 'loadedmetadata', 'seeked'].forEach(ev => mka.addEventListener(ev, studio_mkAudio));
  const mks = studio_el('studio-mk-seek');
  if (mks) mks.addEventListener('input', studio_mkSeekInput);
  const yti = studio_el('studio-yt-url');
  if (yti) yti.addEventListener('keydown', studio_ytKey);
  const q = studio_el('studio-q');
  if (q) q.addEventListener('input', () => { studio.q = q.value; studio_renderLib(); });
  const rq = studio_el('studio-reel-q');
  if (rq) rq.addEventListener('input', () => { studio.reelQ = rq.value; studio_renderReels(); });
  const rs = studio_el('studio-reel-sort');
  if (rs) rs.addEventListener('change', () => { studio.reelSort = rs.value; studio_renderReels(); });
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
  const keepAll = studio_el('studio-keep-all');
  if (keepAll) keepAll.addEventListener('change', () => { studio.keepAll = keepAll.checked; });
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
  /* A preview player given a new clip seeks once it knows the clip's length;
     before that, currentTime is not the browser's to set. */
  studio_pvEls().forEach(pe => {
    if (!pe) return;
    pe.addEventListener('loadedmetadata', () => {
      const at = pe.getAttribute('data-seek');
      if (at !== null) { pe.removeAttribute('data-seek'); pe.currentTime = Number(at) || 0; }
    });
    /* Paused, nothing redraws the blurred copy but a frame arriving. */
    ['seeked', 'loadeddata'].forEach(ev => pe.addEventListener(ev, () => {
      if (!studio.pv.playing && pe === studio_pvEls()[studio.pv.act]) studio_pvBg();
    }));
  });
  /* The preview bar's seek: dragged, it shows each second it passes; let go,
     the clock carries on from there. */
  const sk = studio_el('studio-pv-seek');
  if (sk) {
    const to = () => { if (studio.derived) studio_seekTo(Number(sk.value) / 1000 * studio.derived.length); };
    sk.addEventListener('pointerdown', () => { studio.pv.scrub = true; });
    sk.addEventListener('input', () => { studio.pv.scrub = true; to(); });
    sk.addEventListener('change', () => { to(); studio.pv.scrub = false; studio_pvBar(); });
    ['pointerup', 'pointercancel', 'blur'].forEach(ev => sk.addEventListener(ev, () => { studio.pv.scrub = false; }));
  }
  /* A click on the picture plays and pauses it, as it does the rendered video. */
  const pvBox = studio_el('studio-pv');
  if (pvBox) pvBox.addEventListener('click', e => { if (!e.target.closest('.studio-pv-bar')) studio_toggle(); });
  /* The app's volume and speed, changed while the preview is up. A new speed
     mid-play restarts the clock from where it is, at the new rate. */
  const onKnob = e => {
    const which = e.target && e.target.getAttribute && e.target.getAttribute('data-knob');
    if (!which || !studio.pv.on) return;
    /* Read off the control rather than the saved choice: shell_knobsBind's
       listener, which saves it, is not promised to have run first. */
    if (which === 'vol') { studio_pvLevels(Number(e.target.value) / 100); return; }
    const pv = studio.pv, r = Number(e.target.value) || 1;
    if (pv.playing && r !== pv.rate) { pv.base = studio_pvTime(); pv.t0 = performance.now(); }
    pv.rate = r;
    studio_pvSongSync(studio_pvTime(), pv.playing);
    studio_pvLyrClock(studio_pvTime(), pv.playing);
  };
  document.addEventListener('input', onKnob);
  document.addEventListener('change', onKnob);
  const ar = studio_el('studio-auto-render');
  if (ar) ar.addEventListener('change', () => studio_autoSet(ar.checked));
  ['studio-preview-scrim', 'studio-fxp-scrim'].forEach(id => {
    const sc = studio_el(id);
    if (sc) sc.addEventListener('click', e => { if (e.target === sc) studio_closeModals(); });
  });
  document.addEventListener('keydown', e => {
    if (shell_page !== 'studio') return;
    if (studio_impKey(e)) return;
    if (studio_fxpKey(e)) return;
    /* The command list, while it is open, owns Up, Down, Enter and Escape --
       and it is read here, above the input guard, because its caret is in a
       search field and the guard below would hand those keys to the field. */
    if (studio_palKey(e)) return;
    /* K DROPS A KILL AT THE PLAYHEAD on the Make page, as it does on the Song tab. */
    if (!studio_el('studio-make-scrim').classList.contains('hide') && !e.ctrlKey && !e.metaKey && !e.altKey
        && (e.key || '').toLowerCase() === 'k' && !/^(INPUT|TEXTAREA|SELECT)$/.test((e.target || {}).tagName || '')) {
      e.preventDefault(); studio_mkAddMark(); return;
    }
    /* D MARKS A DROP, and Delete takes away every selected mark -- on the Make page only, and never
       while something is being typed. Delete is read only with a selection, so it falls through to
       the timeline otherwise. */
    if (!studio_el('studio-make-scrim').classList.contains('hide') && !e.ctrlKey && !e.metaKey && !e.altKey
        && !/^(INPUT|TEXTAREA|SELECT)$/.test((e.target || {}).tagName || '')) {
      if (e.key === 'd' || e.key === 'D') { e.preventDefault(); studio_mkAddDrop(); return; }
      if ((e.key === 'Delete' || e.key === 'Backspace') && studio_mkSelCount()) { e.preventDefault(); studio_mkDelSelected(); return; }
    }
    if (e.key === 'Escape') {
      studio_closeModals();
      /* Nobody is stranded holding a tool. */
      if (studio.tool !== 'select') studio_tool('select');
      return;
    }
    /* Ctrl+K is not typing, so it is read before the input guard: the list
       opens from a reel name half-renamed as readily as from the timeline. */
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault(); studio_palOpen(); return;
    }
    const tag = (e.target.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    /* '?' IS A CHARACTER SOMEBODY MIGHT BE TYPING, so unlike Ctrl+K it waits
       until after the guard above. */
    if (e.key === '?') { e.preventDefault(); studio_keysOpen(); return; }
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
    /* THE TOOLS AND THE NAVIGATION ARE TIMELINE KEYS, and they sit HERE for
       a reason the browser tier found the hard way: put above, the shuttle's
       K stole the song pane's K and marking a kill silently stopped working.
       Every scope's keys belong below the scopes that are read before it --
       that order is the whole contract of this block, and the registry says
       these are `timeline`, so this is where they go.

       Escape is already "close whatever is open" above; on a timeline with
       nothing open it also puts the tool back to Select. */
    if (e.key === 'v' || e.key === 'V') { e.preventDefault(); studio_tool('select'); return; }
    if (e.key === 'n' || e.key === 'N') { e.preventDefault(); studio_tool('roll'); return; }
    if (e.key === 'c' || e.key === 'C') { e.preventDefault(); studio_tool('razor'); return; }
    /* J K L, in, out and a mark. Navigation, not edits -- see studio.io. */
    if (e.key === 'j' || e.key === 'J') { e.preventDefault(); studio_shuttle(-1); return; }
    if (e.key === 'k' || e.key === 'K') { e.preventDefault(); studio.shuttle = 0; studio_shuttleApply(); return; }
    if (e.key === 'l' || e.key === 'L') { e.preventDefault(); studio_shuttle(1); return; }
    if (e.key === 'i' || e.key === 'I') { e.preventDefault(); studio_ioSet('a'); return; }
    if (e.key === 'o' || e.key === 'O') { e.preventDefault(); studio_ioSet('b'); return; }
    if (e.key === 'm' || e.key === 'M') { e.preventDefault(); studio_markAdd(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
      /* Shift goes the other way. Checked here rather than as its own branch
         so the two can never be bound to different scopes by accident. */
      e.preventDefault();
      if (e.shiftKey) studio_redo(); else studio_undo();
    }
    else if (e.key === 'ArrowRight') { e.preventDefault(); studio_select(Math.min(studio.project.shots.length - 1, studio.sel + 1)); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); studio_select(Math.max(0, studio.sel - 1)); }
    else if (e.key === ' ') { e.preventDefault(); studio_toggle(); }
    else if (e.key === '+' || e.key === '=') { e.preventDefault(); studio_zoomAt(studio.pps * 1.5, studio_anchorX()); }
    else if (e.key === '-' || e.key === '_') { e.preventDefault(); studio_zoomAt(studio.pps / 1.5, studio_anchorX()); }
    else if (e.key === '0') { e.preventDefault(); studio_fit(); studio_drawTimeline(); }
    else if ((e.key === 'Delete' || e.key === 'Backspace') && studio.sel >= 0 && studio.project.shots.length > 1) {
      e.preventDefault();
      const i = studio.sel, gone = studio_shotName(i);
      studio_forgetShots();
      studio_change(pr => { pr.shots.splice(i, 1); studio_remark(pr); }, gone + ' removed');
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
    /* THE PART GOES WITH IT. A new style used to re-plan without the part
       the reel was cut to, so the style's own length came back and the
       clips that had filled the part fell out "to fit the reel's length".
       How long and Keep every kill go too. */
    const body = {clips: clips, style: key,
      song: p.song, format: p.format, name: p.name, shaping: Object.assign({}, studio.shaping,
        {arrange: studio.arrange, pins: studio.pins, shuffle_seed: studio.shuffleSeed,
         hs_only: !!p.hs_only, fill: p.fill || '', keep_all: !!p.keep_all})};
    if (p.song && p.part_end > (p.song_offset || 0)) {
      body.part_start = p.song_offset || 0;
      body.part_end = p.part_end;
    }
    const r = await API.post('/api/studio/plan', body);
    if (!r || !r.ok) { toast((r && r.error) || 'Could not rebuild with that style.', 'warn'); return; }
    studio_pushUndo(snapshot, 'Rebuilt as ' + label);
    studio.gen++;
    r.project.output = p.output;
    /* The words belong to the song, not to the style: a new cut keeps them. */
    if (p.lyrics) r.project.lyrics = p.lyrics;
    studio.sel = -1;
    /* After the project is replaced, not before: the line is measured against
       the reel it describes. */
    studio_setProject(r.project, r.derived, r.notes, r.song);
    studio_touched('Rebuilt as ' + label, -1, studio_diff(JSON.parse(snapshot), r.project));
    studio_fit(); studio_drawAll();
    toast('Rebuilt as ' + label + ' — ' + r.project.shots.length + ' shots. Render to see it.', 'ok');
  } finally {
    studio.busy = false;
    studio_drawInspector();
  }
}

async function studio_mix(what, announce, ride) {
  const p = studio.project;
  if (!p) return;
  const gen = ++studio.gen;
  const snapshot = JSON.stringify(p);
  const r = await API.post('/api/studio/vary', {project: p, what: what});
  if (gen !== studio.gen) return;
  if (!r || !r.ok) { toast((r && r.error) || 'Could not mix the effects.', 'warn'); return; }
  if (announce) studio_pushUndo(snapshot, 'Kill effects mixed');
  studio.project = r.project; studio.derived = r.derived; studio.notes = r.notes || [];
  /* An unannounced mix rides along with the pool edit that asked for it, and
     that edit has already named itself; naming it twice would double the count.
     It goes onto that edit's line instead, so putting the pool back does not
     claim the video matches while the shots still carry the new mix. */
  const changed = studio_diff(JSON.parse(snapshot), r.project);
  if (announce) {
    studio_touched(what === 'all' ? 'Everything mixed again'
                 : what === 'kill' ? 'Kill effects mixed again' : 'Transitions mixed again', -1, changed);
  } else if (changed.length) {
    studio_touched(ride, -1, changed);
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

/* Named by what you would USE them for. These were named after the signal
   processing that produces them -- "onset strength", "spectrogram" -- which
   tells somebody deciding where to put a kill precisely nothing. */
const SG_LANES = [
  {id: 'wave', h: 74, name: 'Loudness \u2014 where the song gets big'},
  {id: 'hits', h: 92, name: 'Hits \u2014 every kick, snare and hat, and the song\u2019s parts'},
  {id: 'bands', h: 96, name: 'Drums \u2014 kick, snare and hi-hat, separately'},
  {id: 'flux', h: 70, name: 'New sounds \u2014 spikes are good places for a kill'},
  {id: 'spec', h: 128, name: 'Everything at once \u2014 bass low, cymbals high'}
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
  studio.svShow = studio.svShow || {wave: true, hits: true, bands: true, flux: false, spec: true};
  if (!studio.svShow.hasOwnProperty('hits')) studio.svShow.hits = true;
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
  else if (id === 'hits') studio_svHits(x, m.rhythm, v, W, H, pad, X);
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

/* THE HITS LANE. clips/rhythm.py reads the song as layers -- the kick that
   kills land on, the snare cuts land on, the hats the camera moves to -- and
   the parts a reel is paced by. One row per layer, a tick per hit, as tall as
   the hit is loud; the parts as a strip along the top, named. A curve shows a
   band getting louder; it does not show where the hits ARE, which is what an
   edit is timed to. */
const SG_HIT_ROWS = [['kick', '#ff8a5c'], ['snare', '--accent'], ['hats', '#c98bff']];
const SG_PARTS = {intro: 'Intro', verse: 'Verse', build: 'Build', riser: 'Rise', drop: 'Drop',
                  groove: 'Groove', 'break': 'Break', outro: 'Outro'};

function studio_svHits(x, r, v, W, H, pad, X) {
  if (!r) {
    x.fillStyle = studio_tok('--text-tertiary');
    x.font = '12px system-ui, sans-serif';
    x.fillText('The hits could not be read for this song.', 8, pad + 16);
    return;
  }
  /* the parts: a band per section, the loud ones stronger */
  (r.sections || []).forEach(s => {
    if (s.end < v.t0 || s.start > v.t1) return;
    const a = Math.max(0, X(s.start)), b = Math.min(W, X(s.end));
    const hot = s.kind === 'drop' || s.kind === 'riser';
    x.fillStyle = hot ? studio_tok('--warn') : studio_tok('--border-subtle');
    x.globalAlpha = hot ? 0.45 : 0.6;
    x.fillRect(a, 1, Math.max(1, b - a - 1), pad - 4);
    x.globalAlpha = 1;
    x.fillStyle = studio_tok('--text-secondary');
    x.font = '11px system-ui, sans-serif';
    if (b - a > 34) x.fillText(SG_PARTS[s.kind] || s.kind, a + 4, pad - 6);
  });
  const rowH = (H - pad - 4) / SG_HIT_ROWS.length;
  SG_HIT_ROWS.forEach(([name, colour], i) => {
    const L = r.layers && r.layers[name];
    if (!L) return;
    const base = pad + 2 + (i + 1) * rowH;
    x.fillStyle = colour.startsWith('--') ? studio_tok(colour) : colour;
    for (let k = 0; k < L.times.length; k++) {
      const t = L.times[k];
      if (t < v.t0 || t > v.t1) continue;
      const h = Math.max(3, L.strength[k] * (rowH - 3));
      x.fillRect(X(t) - 1, base - h, 2, h);
    }
  });
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
    /* On the part the reel was cut to, not on the reel's length: opened on
       the length, a part chosen longer than the reel was forgotten the
       moment the tab was left. */
    sg.end = Math.min(sh.seconds, p.part_end > sg.start ? p.part_end : sg.start + len);
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
    ctx.globalAlpha = 1;
    studio_beatGrid(ctx, X, H, sh, {width: W});
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
    studio_pushUndo(snapshot, noSong ? 'The song taken off' : 'The part of the song');
    r.project.output = p.output;
    studio_setProject(r.project, r.derived, r.notes, r.song);
    studio_touched(noSong ? 'The song taken off'
                 : sg.marks.length ? 'The song, and ' + sg.marks.length + ' kill marks' : 'The part of the song',
                   -1, studio_diff(JSON.parse(snapshot), r.project));
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

/* =====================================================================
   THE GUIDED MAKER: one question per screen.
   The Make page asks everything at once -- eleven styles, six orders, three lengths, four dials
   -- and lets any style meet any song. A new player who touches nothing got the weakest pair.
   This asks one thing at a time, says after each whether the choices so far work together
   (clips/feasible.py: one verdict, one fix), and hands the answers to the Make page's own
   machinery -- the same plan, the same render -- so there is one maker underneath and this is a
   way of choosing, not a second engine. "All settings" opens the full page with what was chosen
   already in it.
   ===================================================================== */
const GD_STEPS = ['Style', 'Song', 'Clips', 'Look', 'Check and make'];
/* The styles that have been through the review loop. Fast-paced headshot since v1.79.8: ChatGPT's third review of
   its render (7.3/10) said yes, "ready to be offered as a recommended style". */
const GD_BEST = ['drop', 'fasthead'];
studio.gd = {step: 0, style: '', auto: false, setup: '', quick: [], fmt: 'vertical', fit: 'fit', name: '',
             verdict: null, asked: 0, busy: false, timer: null};

/* WHAT WAS CHOSEN LAST TIME, remembered as intent -- the style, the shape, the framing -- and not as
   results: the song and the clips are checked again against what exists now, and the chip is asked
   again, so a remembered answer never skips the check. */
const GD_KEY = 'autostream.guide';
function studio_gdRemember() {
  const gd = studio.gd;
  try { localStorage.setItem(GD_KEY, JSON.stringify({style: gd.style, fmt: gd.fmt, fit: gd.fit, song: studio.song || '',
                                                      setup: gd.setup, quick: gd.quick})); } catch (e) { /* private window: nothing remembered */ }
}
function studio_gdRecall() {
  let m = null;
  try { m = JSON.parse(localStorage.getItem(GD_KEY) || 'null'); } catch (e) { m = null; }
  if (!m || typeof m !== 'object') return false;
  const gd = studio.gd, have = id => !!studio.clipIndex[id];
  if (m.style && studio.catalog.styles.some(s => s.key === m.style)) gd.style = m.style;
  if (m.fmt === 'vertical' || m.fmt === 'landscape') gd.fmt = m.fmt;
  if (['fit', 'near', 'zoom'].includes(m.fit)) gd.fit = m.fit;
  gd.setup = have(m.setup) ? m.setup : '';
  gd.quick = (Array.isArray(m.quick) ? m.quick : []).filter(have);
  return !!gd.style;
}

function studio_gdStyle() {
  const cat = studio.catalog;
  return cat ? cat.styles.find(s => s.key === studio.gd.style) : null;
}

/* every clip the library holds, of the game the player has most favourites in */
function studio_gdClips() {
  const all = Object.values(studio.clipIndex || {}).filter(c => (c.kills || []).length);
  const by = {};
  all.forEach(c => { const g = c.game || ''; by[g] = by[g] || {n: 0, fav: 0}; by[g].n++; if (c.fav) by[g].fav++; });
  const games = Object.keys(by).sort((a, b) => (by[b].fav - by[a].fav) || (by[b].n - by[a].n));
  return all.filter(c => (c.game || '') === games[0]);
}
function studio_gdHs(c) { return (c.hs || []).filter(h => h === true).length; }
function studio_gdBig(c) { return /CLUTCH|LAST.ALIVE|1V|ACE/i.test((c.labels || []).join(' ') + ' ' + (c.name || '')); }
/* As director.is_setup: not from a mode with no rounds, and in Valorant no more than five kills -- a
   round has five enemies, so a 7- or 12-kill run is a Deathmatch, not a clutch or an ace. */
function studio_gdRoundBased(c) {
  return !c.respawn && !(/VALORANT/i.test(c.game || c.name || '') && (c.kills || []).length > 5 && c.round == null);
}
function studio_gdIsSetup(c) {
  const k = (c.kills || []).length;
  return studio_gdRoundBased(c) && (k >= 3 || (k >= 2 && studio_gdBig(c)));
}
function studio_gdSetupScore(c) {
  return (c.kills || []).length * 2 + (studio_gdBig(c) ? 3 : 0) + (c.fav ? 2 : 0) + 0.5 * studio_gdHs(c);
}
function studio_gdQuickScore(c) {
  const k = (c.kills || []).length;
  return (c.fav ? 2 : 0) + (studio_gdHs(c) > 0 ? 1.5 : 0) + (k === 2 ? 0.5 : 0);
}
/* THE CLIPS EACH STYLE CAN USE. Build and drop splits them into a build and quick kills.
   Fast-paced headshot is headshots only (clips/fasthead.py): a clip with none is no use to it,
   and Pick for me used to fill its slots with body kills the plan then left out. Any other style
   takes every clip -- the build's clutches included, which only Build and drop sets apart. */
function studio_gdPools() {
  const all = studio_gdClips(), style = studio.gd.style;
  const setups = all.filter(studio_gdIsSetup).sort((a, b) => studio_gdSetupScore(b) - studio_gdSetupScore(a));
  if (style === 'fasthead') {
    const quick = all.filter(c => studio_gdHs(c) > 0)
      .sort((a, b) => (studio_gdHsDouble(b) - studio_gdHsDouble(a)) || (studio_gdQuickScore(b) - studio_gdQuickScore(a)));
    return {setups: [], quick: quick};
  }
  const quick = all.filter(c => (style !== 'drop' || !studio_gdIsSetup(c)) && c.id !== studio.gd.setup)
    .sort((a, b) => studio_gdQuickScore(b) - studio_gdQuickScore(a));
  return {setups: setups, quick: quick};
}
/* two headshots of one clip within 2.5 s: a real double, the only finale Fast-paced headshot takes */
function studio_gdHsDouble(c) {
  const ks = (c.kills || []).map((k, i) => [Number(k), (c.hs || [])[i] === true]).sort((a, b) => a[0] - b[0]);
  return ks.some((k, i) => i > 0 && k[1] && ks[i - 1][1] && k[0] - ks[i - 1][0] >= 0.25 && k[0] - ks[i - 1][0] <= 2.5) ? 1 : 0;
}
/* how many quick kills the part wants after a build of about eight seconds, half a second apart --
   or, for Fast-paced headshot, one headshot a second or so for its 36 s */
function studio_gdNeed() {
  const mk = studio.mk || {};
  if (studio.gd.style === 'fasthead') return Math.max(8, Math.round(((mk.end - mk.start) > 4 ? (mk.end - mk.start) : 36) * 0.95));
  const len = (mk.end - mk.start) > 4 ? (mk.end - mk.start) : 28;
  return Math.max(6, Math.round((len - 8.5) / 0.52));
}
function studio_gdKillsIn(ids) {
  return ids.reduce((n, id) => n + (((studio.clipIndex[id] || {}).kills || []).length || 0), 0);
}
function studio_gdIds() {
  const gd = studio.gd;
  return (gd.setup ? [gd.setup] : []).concat(gd.quick.filter(id => id !== gd.setup));
}

async function studio_gdOpen() {
  if (!studio.songList) {                  /* the songs already downloaded, for step two */
    const r = await API.get('/api/studio/songs').catch(() => null);
    studio.songList = (r && r.ok && r.songs) || [];
  }
  if (!studio.catalog || !Object.keys(studio.clipIndex || {}).length) { toast('The clips are still loading.', 'warn'); return; }
  studio.gd.step = 0; studio.gd.verdict = null;
  if (!studio.gd.style && !studio.gd.auto) studio_gdRecall();
  studio_show('studio-preview-scrim', false);
  studio_show('studio-make-scrim', false);
  studio_show('studio-guide-scrim', true);
  studio_makePage(true);
  studio_gdDraw();
}
function studio_gdClose() {
  if (studio.gd.busy) studio.buildGen++;   /* closing while it plans abandons the plan */
  studio_show('studio-guide-scrim', false);
  studio_makePage(false);
}

function studio_gdCanGo(i) {
  const gd = studio.gd;
  if (i <= 0) return true;
  if (!gd.style && !gd.auto) return false;
  if (i >= 2 && !studio.song) return false;
  if (i >= 3 && !gd.quick.length && !gd.setup) return false;
  return true;
}

function studio_gdDraw() {
  const gd = studio.gd;
  studio_el('studio-gd-steps').innerHTML = GD_STEPS.map((n, i) =>
    '<li><button type="button" class="gd-step' + (i === gd.step ? ' is-on' : '') + (i < gd.step ? ' is-done' : '') +
    '" data-act="studio-gd" data-gd="step" data-i="' + i + '"' + (studio_gdCanGo(i) ? '' : ' disabled') +
    ' aria-current="' + (i === gd.step ? 'step' : 'false') + '"><b>Step ' + (i + 1) + '</b><span>' + esc(n) + '</span></button></li>').join('');
  const draw = [studio_gdDrawStyle, studio_gdDrawSong, studio_gdDrawClips, studio_gdDrawLook, studio_gdDrawCheck][gd.step];
  studio_el('studio-gd-body').innerHTML = draw();
  studio_el('studio-gd-back').disabled = gd.step === 0;
  const next = studio_el('studio-gd-next');
  next.textContent = gd.step === 4 ? 'Make the reel' : 'Next';
  next.disabled = gd.step < 4 ? !studio_gdCanGo(gd.step + 1) : (gd.busy || !!(gd.verdict && gd.verdict.level === 'bad'));
  studio_gdChip();
  if (gd.step >= 1) studio_gdAsk();
  studio_gdRemember();
}

function studio_gdDrawStyle() {
  const gd = studio.gd, cat = studio.catalog;
  const card = s => {
    const url = studio_sampleUrl(s.key), on = gd.style === s.key, best = GD_BEST.includes(s.key);
    return '<button type="button" class="gd-card' + (on ? ' is-on' : '') + (best ? ' is-best' : '') + '" data-act="studio-gd" data-gd="style" data-key="' + esc(s.key) + '" aria-pressed="' + on + '">' +
      (url ? '<video muted loop playsinline autoplay preload="auto" src="' + esc(url) + '" aria-hidden="true"></video>' : '') +
      '<span class="gd-card-name">' + esc(s.label) + (best ? '<span class="gd-best">Use this for best result</span>' : '') + '</span>' +
      '<span class="muted">' + esc(s.blurb) + '</span></button>';
  };
  const best = cat.styles.filter(s => GD_BEST.includes(s.key)), rest = cat.styles.filter(s => !GD_BEST.includes(s.key));
  return '<div class="gd-q"><h3>What kind of reel?</h3><p class="muted">Pick a style, or give us a song and we will choose one for it.</p></div>' +
    '<button type="button" class="gd-auto' + (gd.auto ? ' is-on' : '') + '" data-act="studio-gd" data-gd="auto"><strong>Not sure? Give us a song and we will pick the style.</strong>' +
    '<span class="muted">We read the song for its drop and tempo and choose the style that suits it.</span></button>' +
    (gd.auto && studio.song && !gd.style ? '<p class="gd-note">That song has no clear drop, so no style is picked for you yet. Choose one below.</p>' : '') +
    '<div class="gd-grid gd-grid-best">' + best.map(card).join('') + '</div>' +
    '<details class="gd-more"' + (gd.style && !GD_BEST.includes(gd.style) ? ' open' : '') + '><summary>More styles <span class="muted">(not reviewed yet: they work, but are not at the standard of the ones above)</span></summary>' +
    '<div class="gd-grid">' + rest.map(card).join('') + '</div></details>';
}

function studio_gdDrawSong() {
  const sh = studio.songShape, list = studio.songList || [], mk = studio.mk || {};
  const drops = sh ? (sh.drops && sh.drops.length ? sh.drops : (sh.drop ? [sh.drop] : [])) : [];
  return '<div class="gd-q"><h3>Which song?</h3><p class="muted">We pick the best part of it for ' + esc((studio_gdStyle() || {label: 'the style'}).label) + '. You can change it under All settings.</p></div>' +
    '<div class="gd-grid">' + list.map(s => '<button type="button" class="gd-card' + (studio.song && s.path.toLowerCase() === studio.song.toLowerCase() ? ' is-on' : '') +
      '" data-act="studio-gd" data-gd="song" data-path="' + esc(s.path) + '" data-name="' + esc(s.name) + '"><span class="gd-card-name">' + esc(s.name) + '</span></button>').join('') + '</div>' +
    '<div><button type="button" class="btn" data-act="studio-gd" data-gd="pick-song">Choose a song file&hellip;</button> ' +
    '<span class="muted" id="studio-gd-song-msg"></span></div>' +
    (sh ? '<div class="gd-facts"><span><b>Tempo</b> ' + Math.round(sh.bpm) + ' BPM</span><span><b>Length</b> ' + studio_dur(sh.seconds) + '</span>' +
      '<span><b>Drop</b> ' + (drops.length ? drops.map(d => studio_secs(d)).join(', ') : 'none found') + '</span>' +
      (mk.end > mk.start ? '<span><b>Part used</b> ' + studio_secs(mk.start) + ' &rarr; ' + studio_secs(mk.end) + '</span>' : '') + '</div>' : '');
}

function studio_gdDrawClips() {
  const gd = studio.gd, pools = studio_gdPools(), need = studio_gdNeed();
  const have = gd.quick.reduce((n, id) => n + (((studio.clipIndex[id] || {}).kills || []).length >= 2 ? 2 : 1), 0);
  const tile = (c, on, act) => '<button type="button" class="gd-clip' + (on ? ' is-on' : '') + '" data-act="studio-gd" data-gd="' + act + '" data-id="' + esc(c.id) + '" aria-pressed="' + on + '">' +
    '<span class="gd-tags">' + (studio_gdHs(c) ? '<i class="gd-hs">Headshot</i>' : '<i>Body</i>') +
    (c.fav ? '<i class="gd-fav">&#9733;</i>' : '') + ((c.kills || []).length > 1 ? '<i>' + c.kills.length + ' kills</i>' : '') +
    ((c.labels || [])[0] ? '<i>' + esc(c.labels[0]) + '</i>' : '') + '</span><span class="mono">' + esc(c.name || c.id) + '</span></button>';
  const isBD = gd.style === 'drop', isFH = gd.style === 'fasthead';
  if (isFH) {
    const doubles = gd.quick.filter(id => studio_gdHsDouble(studio.clipIndex[id] || {})).length;
    return '<div class="gd-q"><h3>Pick the clips, by what they do</h3><p class="muted">Headshots only: a clip with none has nothing for this style.</p></div>' +
      '<div><button type="button" class="btn btn-primary" data-act="studio-gd" data-gd="pickall">Pick for me</button></div>' +
      '<section class="gd-slot"><div class="gd-slothead"><h4>Headshots, one a cut</h4><span class="mono">' + gd.quick.length + ' of ' + need + '</span></div>' +
      '<div class="gd-bar" aria-hidden="true"><i style="width:' + Math.min(100, Math.round(gd.quick.length / Math.max(1, need) * 100)) + '%"></i></div>' +
      '<p class="muted" style="margin:0">' + (doubles ? 'The finale: ' + doubles + ' chosen clip' + (doubles > 1 ? 's have' : ' has') + ' two headshots close together.'
        : 'No chosen clip has two headshots close together, so the reel ends on a single kill, not a multi-kill.') + '</p>' +
      '<div class="gd-grid">' + pools.quick.slice(0, 60).map(c => tile(c, gd.quick.includes(c.id), 'quick')).join('') +
      (pools.quick.length ? '' : '<p class="muted">None of your clips has a kill read as a headshot.</p>') + '</div></section>';
  }
  /* Said as it is: every clip of the game is a candidate, the favourites ranked first, and only the best of
     each kind is drawn here -- "from your favourites" read as if nothing else was considered. */
  const all = studio_gdClips().length;
  return '<div class="gd-q"><h3>Pick the clips, by what they do</h3><p class="muted">All ' + all + ' of your ' + esc((studio_gdClips()[0] || {}).game || '') +
    ' clips are candidates, favourites first. The best ' + Math.min(8, pools.setups.length) + ' of ' + pools.setups.length +
    ' builds and ' + Math.min(48, pools.quick.length) + ' of ' + pools.quick.length + ' quick kills are shown; Pick for me draws on all of them.</p></div>' +
    '<div><button type="button" class="btn btn-primary" data-act="studio-gd" data-gd="pickall">Pick for me</button></div>' +
    (isBD ? '<section class="gd-slot"><div class="gd-slothead"><h4>The build: a clutch, an ace or a multi-kill</h4><span class="mono">' + (gd.setup ? '1 of 1' : '0 of 1') + '</span></div>' +
      '<div class="gd-grid">' + (pools.setups.slice(0, 8).map(c => tile(c, gd.setup === c.id, 'setup')).join('') || '<p class="muted">None of your clips has three kills or a clutch label.</p>') + '</div></section>' : '') +
    '<section class="gd-slot"><div class="gd-slothead"><h4>' + (isBD ? 'After the drop: quick kills' : 'Your clips') + '</h4><span class="mono">' + (isBD ? have + ' of ' + need : gd.quick.length + ' chosen') + '</span></div>' +
    (isBD ? '<div class="gd-bar" aria-hidden="true"><i style="width:' + Math.min(100, Math.round(have / Math.max(1, need) * 100)) + '%"></i></div><p class="muted" style="margin:0">Headshots first. A two-kill clip counts as two: it plays as a quick run.</p>' : '') +
    '<div class="gd-grid">' + pools.quick.slice(0, 48).map(c => tile(c, gd.quick.includes(c.id), 'quick')).join('') + '</div></section>';
}

function studio_gdSeg(name, val, opts) {
  return '<div class="seg" role="group">' + opts.map(o => '<button type="button" class="seg-btn' + (val === o[0] ? ' is-active' : '') + '" data-act="studio-gd" data-gd="set" data-k="' + name + '" data-v="' + o[0] + '" aria-pressed="' + (val === o[0]) + '">' + esc(o[1]) + '</button>').join('') + '</div>';
}
function studio_gdDrawLook() {
  const gd = studio.gd;
  return '<div class="gd-q"><h3>How should it look?</h3><p class="muted">Only what changes the picture. The effects come with the style; lyrics and the rest are under All settings.</p></div>' +
    '<div class="gd-field"><h4>Shape</h4>' + studio_gdSeg('fmt', gd.fmt, [['vertical', '9:16 Short or Reel'], ['landscape', '16:9 YouTube']]) + '</div>' +
    (gd.fmt === 'vertical' ? '<div class="gd-field"><h4>Framing</h4>' + studio_gdSeg('fit', gd.fit, [['fit', 'Fit the whole picture'], ['near', 'Near fit'], ['zoom', 'Zoom to fill']]) + '</div>' : '');
}

function studio_gdDrawCheck() {
  const gd = studio.gd, s = studio_gdStyle(), ids = studio_gdIds();
  const song = studio.song ? studio.song.split(/[\\/]/).pop().replace(/\.[^.]+$/, '') : '';
  return '<div class="gd-q"><h3>Check and make</h3><p class="muted">Planned, not rendered yet. This is what the reel will be.</p></div>' +
    '<div class="gd-facts"><span><b>Style</b> ' + esc(s ? s.label : '') + '</span><span><b>Song</b> ' + esc(song) + '</span>' +
    '<span><b>Clips</b> ' + ids.length + ' (' + studio_gdKillsIn(ids) + ' kills)</span><span><b>Shape</b> ' + (gd.fmt === 'vertical' ? '9:16' : '16:9') + '</span>' +
    (gd.verdict && gd.verdict.length ? '<span><b>Length</b> ' + Math.round(gd.verdict.length) + ' s</span>' : '') + '</div>' +
    '<div class="gd-field"><label class="field-label" for="studio-gd-name">Name</label>' +
    '<input class="input" id="studio-gd-name" maxlength="80" placeholder="' + esc(studio_gdDefaultName()) + '" value="' + esc(gd.name || '') + '"></div>' +
    '<p class="muted">After it is rendered we read the finished reel back and check every kill is on its beat, in focus and not repeated.</p>';
}

/* The name a reel gets when none is typed: the song's title and the style, not "Build and drop reel"
   for every one. "Y2K, bbno$ - Lalala (Official Video) [N2Y2vQ-1m7M]" is "Lalala". */
function studio_gdDefaultName() {
  const s = studio_gdStyle();
  let song = studio.song ? studio.song.split(/[\\/]/).pop().replace(/\.[^.]+$/, '') : '';
  song = song.replace(/\s*\[[^\]]*\]/g, '').replace(/\s*\((official|lyric|audio|music)[^)]*\)/ig, '');
  if (song.includes(' - ')) song = song.split(' - ').slice(1).join(' - ');
  return ((song.trim() ? song.trim() + ' ' : '') + (s ? s.label.toLowerCase() : 'reel')).replace(/^./, c => c.toUpperCase());
}

/* THE CHIP: the server's verdict, or the one thing known without asking */
function studio_gdChip() {
  const gd = studio.gd, el = studio_el('studio-gd-chip');
  let v = gd.verdict;
  if (gd.step === 0) {
    v = (!gd.style && !gd.auto) ? {level: 'warn', text: 'Pick a style, or pick a song and we will choose one.'}
      : {level: 'ok', text: gd.style ? 'Good. Next: the song.' : 'Pick a song next and we will choose the style.'};
  }
  if (gd.step >= 1 && !v) v = {level: 'ok', text: 'Checking this against your song and clips…'};
  const label = {ok: 'Works', warn: 'Will work, but', bad: "Won't work"}[v.level];
  el.className = 'gd-chip ' + v.level;
  el.innerHTML = '<span class="gd-dot">' + label + '</span><p>' + esc(v.text) + '</p>' +
    (v.fix ? '<button type="button" class="btn btn-primary btn-sm" data-act="studio-gd" data-gd="fix" data-fix="' + esc(v.fix) + '">' + esc(v.fix_label || 'Fix it') + '</button>' : '<span></span>');
}

/* Ask the server once the last answer has settled; a newer question makes an older answer stale. */
function studio_gdAsk() {
  const gd = studio.gd;
  clearTimeout(gd.timer);
  if (!gd.style || !studio.song) { gd.verdict = null; studio_gdChip(); return; }
  const ticket = ++gd.asked;
  gd.timer = setTimeout(async () => {
    studio.style = gd.style; studio.fmt = gd.fmt; studio.vfit = gd.fit;
    const keep = studio.selected; studio.selected = studio_gdIds();
    const body = studio_planBody(false);
    studio.selected = keep;
    const got = await API.post('/api/studio/feasible', body).catch(() => null);
    if (ticket !== gd.asked) return;
    gd.verdict = got && got.ok ? Object.assign({}, got.verdict, {length: got.length})
                               : {level: 'warn', text: 'Could not check this against your clips just now.'};
    studio_gdChip();
    if (gd.step === 4) {
      studio_el('studio-gd-body').innerHTML = studio_gdDrawCheck();
      studio_el('studio-gd-next').disabled = gd.busy || gd.verdict.level === 'bad';
    }
  }, 250);
}

function studio_gdPickAll() {
  const gd = studio.gd, need = studio_gdNeed();
  if (gd.style === 'drop') { const s = studio_gdPools().setups[0]; gd.setup = s ? s.id : ''; }
  gd.quick = [];
  let n = 0;
  for (const c of studio_gdPools().quick) {
    if (n >= need) break;
    gd.quick.push(c.id);
    n += gd.style === 'fasthead' ? 1 : (c.kills || []).length >= 2 ? 2 : 1;
  }
}

async function studio_gdUseSong(path, name) {
  const msg = studio_el('studio-gd-song-msg');
  if (msg) msg.textContent = 'Finding the beat…';
  const ok = await studio_useSong(path, name);
  if (!ok) { if (msg) msg.textContent = 'Could not read that song.'; return; }
  const sh = studio.songShape, gd = studio.gd;
  const hasDrop = !!(sh && ((sh.drops && sh.drops.length) || sh.drop));
  if (gd.auto) {
    gd.step = 0;
    gd.style = hasDrop ? 'drop' : '';
    if (hasDrop) toast('Build and drop suits this song: it has a clear drop.', 'ok');
  }
  gd.verdict = null;
  studio_gdDraw();
}

function studio_gdFix(fix) {
  const gd = studio.gd;
  if (fix.indexOf('style:') === 0) { gd.style = fix.slice(6); gd.auto = false; }
  else if (fix === 'pick-song') { gd.step = 1; }
  else if (fix === 'pick-clips') { studio_gdPickAll(); gd.step = 2; }
  else if (fix === 'format:vertical') { gd.fmt = 'vertical'; }
  gd.verdict = null;
  studio_gdDraw();
}

function studio_gdAllSettings() {
  const gd = studio.gd;
  if (gd.style) studio.style = gd.style;
  studio.fmt = gd.fmt; studio.vfit = gd.fit;
  const ids = studio_gdIds();
  if (ids.length) { studio.selected = ids; studio_syncSelection(); }
  studio_gdClose();
  if (studio.selected.length) studio_openMake();
}

/* MAKE, FROM THE GUIDE ITSELF. It used to open All settings and build from there, so the player
   watched a page they had not asked for, its Build button greyed for the minute the plan takes,
   with a name nobody had asked them for. Now the guide plans in place and opens the timeline. */
async function studio_gdMake() {
  const gd = studio.gd;
  if (gd.busy) return;
  const nameEl = studio_el('studio-gd-name');
  if (nameEl) gd.name = nameEl.value.trim();
  gd.busy = true;
  studio.style = gd.style; studio.picks = null; studio.fmt = gd.fmt; studio.vfit = gd.fit;
  studio.selected = studio_gdIds(); studio_syncSelection();
  const setup = gd.setup && studio.clipIndex[gd.setup];
  studio.buildClip = gd.style === 'drop' && setup ? setup.path : '';
  studio.adding = null;                    /* the guide makes a new reel; it never rebuilds one */
  studio_el('studio-name').value = gd.name || studio_gdDefaultName();
  const hs = studio_el('studio-hs-only');
  if (hs) hs.checked = false;              /* headshots only is not a question the guide asks */
  studio_mkDefault();
  const next = studio_el('studio-gd-next');
  next.textContent = 'Planning…';
  const chip = (text, level) => {
    const el = studio_el('studio-gd-chip');
    el.className = 'gd-chip ' + level;
    el.innerHTML = '<span class="gd-dot">' + (level === 'bad' ? "Won't work" : 'Making it') + '</span><p>' + esc(text) + '</p><span></span>';
  };
  try {
    await studio_build({btn: next, say: (t, failed) => failed ? chip(t, 'bad')
      : chip(t + ' This takes about a minute; the reel opens on the timeline when it is planned.', 'ok')});
  } finally {
    gd.busy = false;
    next.textContent = 'Make the reel';
  }
}

function studio_gdAct(b) {
  const gd = studio.gd, what = b.getAttribute('data-gd');
  if (what === 'close') return studio_gdClose();
  if (gd.busy) return;                     /* planning: only closing it is offered */
  if (what === 'all') return studio_gdAllSettings();
  if (what === 'fix') return studio_gdFix(b.getAttribute('data-fix'));
  if (what === 'song') { studio_gdUseSong(b.getAttribute('data-path'), b.getAttribute('data-name')); return; }
  if (what === 'pick-song') {
    studio_pickSong().then(() => { if (gd.auto && studio.song) studio_gdUseSong(studio.song, ''); else studio_gdDraw(); });
    return;
  }
  if (what === 'step') { gd.step = Number(b.getAttribute('data-i')); }
  else if (what === 'back') { gd.step = Math.max(0, gd.step - 1); }
  else if (what === 'next') { if (gd.step === 4) return studio_gdMake(); gd.step++; }
  else if (what === 'style') {
    gd.style = b.getAttribute('data-key'); gd.auto = false;
    if (gd.style !== 'drop') gd.setup = '';
    gd.verdict = null;
  }
  else if (what === 'auto') { gd.auto = true; gd.style = ''; gd.step = 1; gd.verdict = null; }
  else if (what === 'setup') {
    const id = b.getAttribute('data-id');
    gd.setup = gd.setup === id ? '' : id; gd.quick = gd.quick.filter(x => x !== gd.setup); gd.verdict = null;
  }
  else if (what === 'quick') {
    const id = b.getAttribute('data-id');
    gd.quick = gd.quick.indexOf(id) >= 0 ? gd.quick.filter(x => x !== id) : gd.quick.concat([id]); gd.verdict = null;
  }
  else if (what === 'pickall') { studio_gdPickAll(); gd.verdict = null; }
  else if (what === 'set') { gd[b.getAttribute('data-k')] = b.getAttribute('data-v'); gd.verdict = null; }
  studio_gdDraw();
}


window.PAGE_STUDIO = {
  onShow: function () {
    if (!studio.wired) studio_sgWire();
    studio_wire();
    studio_load(false);
    studio_poll();
    studio_autoLoad();
  },
  onTick: function () { studio_autoTick(); }
};
"""

__all__ = ["STUDIO_HTML", "STUDIO_JS"]
